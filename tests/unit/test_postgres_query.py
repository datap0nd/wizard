"""Gemini's read-only SQL tool without a server: the SQL is sent as written inside a read-only transaction that is always
rolled back, results are capped and typed, rights and evidence, Check my data replays, and the local Owner's access."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, MemoryRecorder

from wizard_api.app import create_app
from wizard_api.config import ConfigError, load_settings
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.fixture_source import SourceError
from wizard_connectors.pg import PgError, PgSettings, schema_list
from wizard_connectors.postgres_query import PostgresQuery, plan_relations, without_terminator
from wizard_connectors.tools import ToolContext, build_registry, build_services

SETTINGS = PgSettings("db.corp", 5432, "meto_db", "reader", "secret", "prefer", "test")
COLUMNS = [{"name": "market", "type_oid": 25}, {"name": "units", "type_oid": 20}, {"name": "amount", "type_oid": 1700},
           {"name": "amount", "type_oid": 1700}, {"name": "week_start", "type_oid": 1082}]


class FakeSession:
    def __init__(self, rows: list[list[Any]] | None = None, error: Exception | None = None) -> None:
        self.statements: list[str] = []
        self.closed = False
        self.result = rows if rows is not None else [["EG", 12, Decimal("1234.50"), Decimal("7"), dt.date(2026, 9, 28)]]
        self.error = error

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        self.statements.append(sql)
        return []

    def query(self, sql: str) -> tuple[list[dict[str, Any]], list[list[Any]]]:
        self.statements.append(sql)
        if self.error:
            raise self.error
        return COLUMNS, self.result

    def close(self) -> None:
        self.closed = True


def test_the_query_runs_as_written_in_a_read_only_transaction():
    session = FakeSession()
    result = PostgresQuery(SETTINGS, connect=lambda s, d: session).run(
        "SELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv GROUP BY 1 -- by market\n;; ", max_rows=50)
    start, query, end = session.statements
    assert start == "START TRANSACTION READ ONLY" and end == "ROLLBACK" and session.closed
    assert query == ("SELECT * FROM (\nSELECT market, sum(units) FROM bi_reporting.sell_in_amt_mv GROUP BY 1 -- by market\n"
                     ") AS wizard_query LIMIT 51"), "trailing semicolons go; a trailing comment cannot eat the parenthesis"
    assert [c["key"] for c in result.columns] == ["market", "units", "amount", "amount_2", "week_start"]
    assert [c["type"] for c in result.columns] == ["string", "integer", "number", "number", "string"]
    assert result.rows == [["EG", 12, 1234.5, 7, "2026-09-28"]] and not result.truncated and result.database == "meto_db"


@pytest.mark.parametrize(("sql", "sent"), [
    ("SELECT 1 ORDER BY 1 DESC;  -- latest week\n", "SELECT 1 ORDER BY 1 DESC"),
    ("SELECT 1;; /* done */ \n -- really\n", "SELECT 1"),
    ("SELECT ';' AS s; -- x", "SELECT ';' AS s"),
    ("SELECT 'a'';--' AS s", "SELECT 'a'';--' AS s"),
    ("SELECT E'it\\'s;' AS s;", "SELECT E'it\\'s;' AS s"),
    ('SELECT 1 AS ";" ;', 'SELECT 1 AS ";" '),
    ("SELECT $q$ ; -- $q$ AS s;", "SELECT $q$ ; -- $q$ AS s"),
    ("SELECT 1 /* a /* nested ; */ b */;", "SELECT 1 /* a /* nested ; */ b */"),
    ("SELECT 1; SELECT 2", "SELECT 1; SELECT 2"),
    ("SELECT 1; 'x'", "SELECT 1; 'x'"),
])
def test_only_a_final_semicolon_is_dropped(sql, sent):
    assert without_terminator(sql).strip() == sent.strip(), "a semicolon followed by more SQL is left for PostgreSQL to refuse"


def test_rows_are_capped_and_errors_are_explained():
    many = FakeSession(rows=[["EG", i, Decimal(i), Decimal(i), None] for i in range(11)])
    capped = PostgresQuery(SETTINGS, connect=lambda s, d: many).run("SELECT 1", database="other_db", max_rows=10)
    assert len(capped.rows) == 10 and capped.truncated and capped.database == "other_db"
    broken = FakeSession(error=Exception({"S": "ERROR", "C": "42601", "M": 'syntax error at or near "DELETE"'}))
    with pytest.raises(SourceError) as error:
        PostgresQuery(SETTINGS, connect=lambda s, d: broken).run("DELETE FROM t")
    assert error.value.code == "query_failed" and "SQLSTATE 42601" in error.value.message
    assert "Send one query per call" in error.value.message and broken.statements[-1] == "ROLLBACK" and broken.closed

    def unreachable(settings: PgSettings, database: str) -> FakeSession:
        raise PgError("could not connect to db.corp:5432/meto_db as reader: timeout")
    with pytest.raises(SourceError, match="not reachable"):
        PostgresQuery(SETTINGS, connect=unreachable).run("SELECT 1")
    with pytest.raises(SourceError, match="empty"):
        PostgresQuery(SETTINGS, connect=lambda s, d: FakeSession()).run(" ; ")


class CatalogSession(FakeSession):
    """A database whose catalog lists `relations` (schema, name) and, from the server, `databases`."""

    def __init__(self, relations: list[tuple[str, str]], databases: list[str] | None = None, error: Exception | None = None):
        super().__init__(error=error)
        self.relations, self.databases, self.closed = relations, databases or [], False

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        self.statements.append(sql)
        if "pg_database" in sql:
            return [{"datname": d} for d in self.databases]
        if "pg_class" in sql:
            wanted = [(s, n) for s, n in self.relations if not params or (n.lower() == params["relname"].lower()
                      and params["schema"].lower() in ("", s.lower()))]
            return [{"schema": s, "name": n} for s, n in wanted]
        return []


MISSING = Exception({"S": "ERROR", "C": "42P01", "M": 'relation "bi_reporting.global_lc_v" does not exist'})


def test_a_missing_relation_names_where_to_look_instead():
    # The owner's 22 Oct run: the dataset notes named bi_reporting.global_lc_v and bi_reporting.mena_lc, PostgreSQL said
    # they do not exist, and Gemini spent steps guessing.
    here = CatalogSession([("bi_reporting", "global_lc_v_weekly"), ("bi_reporting", "Mena_LC"), ("sales", "orders")],
                          databases=["dwh", "archive"], error=MISSING)
    sessions = {"meto_db": here, "dwh": CatalogSession([("bi_reporting", "global_lc_v")]), "archive": CatalogSession([])}
    with pytest.raises(SourceError) as error:
        PostgresQuery(SETTINGS, connect=lambda s, d: sessions[d]).run("SELECT * FROM bi_reporting.global_lc_v")
    message = error.value.message
    assert error.value.code == "query_failed" and 'relation "bi_reporting.global_lc_v" does not exist (SQLSTATE 42P01)' in message
    assert "Found bi_reporting.global_lc_v in database dwh: set database to query it." in message
    assert "similar name in database meto_db: bi_reporting.global_lc_v_weekly." in message and "orders" not in message
    assert here.statements[2:4] == ["ROLLBACK", "START TRANSACTION READ ONLY"], "a fresh read-only transaction"
    assert here.statements[-1] == "ROLLBACK" and here.closed
    for other in ("dwh", "archive"):
        assert sessions[other].statements[0] == "START TRANSACTION READ ONLY" and sessions[other].statements[-1] == "ROLLBACK"
        assert sessions[other].closed

    capitals = CatalogSession([("bi_reporting", "Mena_LC")], error=Exception(
        {"S": "ERROR", "C": "42P01", "M": 'relation "bi_reporting.mena_lc" does not exist'}))
    with pytest.raises(SourceError) as error:
        PostgresQuery(SETTINGS, connect=lambda s, d: capitals).run("SELECT * FROM bi_reporting.mena_lc")
    assert 'similar name in database meto_db: bi_reporting."Mena_LC".' in error.value.message, "quoted, as SQL needs it"

    nothing = CatalogSession([("sales", "orders")], error=MISSING)
    with pytest.raises(SourceError) as error:
        PostgresQuery(SETTINGS, connect=lambda s, d: nothing).run("SELECT * FROM bi_reporting.global_lc_v")
    assert "No readable table or view in database meto_db has a similar name" in error.value.message


def test_postgresql_hints_reach_gemini():
    column = FakeSession(error=Exception({"S": "ERROR", "C": "42703", "M": 'column "unit" does not exist',
                                          "H": 'Perhaps you meant to reference the column "s.units".'}))
    with pytest.raises(SourceError) as error:
        PostgresQuery(SETTINGS, connect=lambda s, d: column).run("SELECT unit FROM sql_reporting.sales s")
    assert error.value.message.endswith('(SQLSTATE 42703). Hint: Perhaps you meant to reference the column "s.units".')


def owner(markets: list[str] | None = None) -> Identity:
    rights = {"postgresql": SystemRights(reports=["*"], markets=markets or ["*"])}
    return Identity(id="o", email="o@corp.test", name="O", role="Owner", entitlements=rights)


def test_tool_rights_evidence_and_replay(identities):
    services = build_services()
    registry = build_registry(services)
    args = {"sql": "SELECT market, sum(units) AS units FROM bi_reporting.sell_in_amt_mv GROUP BY 1"}
    ctx = ToolContext(identity=owner(), run_id="r", recorder=MemoryRecorder(), services=services)
    assert registry.execute("wizard_query_postgresql", args, ctx).error_code == "source_unavailable"
    sessions = [FakeSession(), FakeSession(), FakeSession(rows=[["EG", 13, Decimal(1), Decimal(1), None]])]
    services.postgres = PostgresQuery(SETTINGS, connect=lambda s, d: sessions.pop(0))
    try:
        for identity in (identities.get("u-ceo"), owner(markets=["EG"])):
            denied = registry.execute("wizard_query_postgresql", args, ToolContext(identity=identity, run_id="r",
                                                                                 recorder=MemoryRecorder(), services=services))
            assert denied.error_code == "not_entitled", "a free query cannot be limited to some markets"
        outcome = registry.execute("wizard_query_postgresql", args, ctx)
        assert outcome.ok, outcome.error_message
        assert outcome.data["data_mode"] == "LIVE" and outcome.data["rows"][0][0] == "EG"
        evidence = ctx.recorder.get_evidence("E1")
        assert evidence["data_mode"] == "LIVE" and evidence["connector_status"] == "READ_ONLY_SQL"
        assert evidence["request"] == {"sql": args["sql"], "database": "meto_db", "max_rows": 200}
        listed = registry.execute("wizard_list_sources", {}, ctx).data["sources"]
        assert [s["system"] for s in listed] == ["postgresql"]
        check = registry.execute("wizard_check_my_data", {"replay_evidence_ids": ["E1", "E1"]}, ctx)
        assert check.ok, check.error_message
        assert [r["status"] for r in check.data["replays"]] == ["UNCHANGED", "CHANGED"], "the same SQL is run again"
    finally:
        services.postgres = None


def test_the_local_owner_can_query_and_sees_live_data(tmp_path):
    settings = load_settings(env={"WIZARD_AGENT_RUNTIME": "replay", "WIZARD_PG_HOST": "db.corp", "WIZARD_PG_USER": "reader",
                                  "WIZARD_ATTACHMENT_OFFICE": "never", "WIZARD_ATTACHMENT_FOLDERS": "none"}, home=tmp_path)
    assert settings.postgres is not None and settings.postgres.database == "postgres"
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS)
        assert "LIVE" in client.get("/api/v1/bootstrap").json()["data_modes"]
        assert client.app.state.manager.services.postgres is not None


# The schemas Wizard may query (WIZARD_PG_SCHEMAS; owner, 2 Nov 2026: one schema allowed, another forbidden) -----------
LIMITED = dataclasses.replace(SETTINGS, schemas=("reporting",))


def scan(schema: str, name: str, node: str = "Seq Scan") -> dict[str, Any]:
    return {"Node Type": node, "Relation Name": name, "Schema": schema, "Alias": name, "Output": ["x"]}


class PlanSession(FakeSession):
    """A session whose EXPLAIN (VERBOSE, FORMAT JSON) returns `plan`, a faked PostgreSQL plan (parsed, or as text)."""

    def __init__(self, plan: Any) -> None:
        super().__init__()
        self.plan = plan

    def query(self, sql: str) -> tuple[list[dict[str, Any]], list[list[Any]]]:
        if sql.startswith("EXPLAIN"):
            self.statements.append(sql)
            return [{"name": "QUERY PLAN", "type_oid": 114}], [[self.plan]]
        return super().query(sql)


ALLOWED_PLAN = [{"Plan": {"Node Type": "Hash Join", "Plans": [
    scan("reporting", "sell_out_weekly"),
    {"Node Type": "Hash", "Plans": [scan("reporting", "markets", "Index Scan")]},
    {"Node Type": "Function Scan", "Function Name": "generate_series", "Schema": "pg_catalog", "Alias": "weeks"},
    scan("pg_catalog", "pg_class"), scan("information_schema", "sql_features")]}}]
# A CTE in an init plan, a subquery and a join, two levels down, reading the forbidden schema; as text, as pg8000 may
# hand it over.
REFUSED_PLAN = json.dumps([{"Plan": {"Node Type": "Nested Loop", "Plans": [
    {"Node Type": "CTE Scan", "CTE Name": "segments", "Alias": "segments"},
    {"Node Type": "Subquery Scan", "Alias": "s", "Parent Relationship": "InitPlan", "Subplan Name": "CTE segments",
     "Plans": [{"Node Type": "Aggregate", "Plans": [scan("restricted", "customers"), scan("reporting", "orders")]}]},
    scan("restricted", "customers", "Index Only Scan")]}}])


def test_a_query_in_the_allowed_schemas_runs_after_its_plan_is_checked():
    session = PlanSession(ALLOWED_PLAN)
    result = PostgresQuery(LIMITED, connect=lambda s, d: session).run("SELECT 1 FROM reporting.sell_out_weekly;")
    start, explained, query, end = session.statements
    assert start == "START TRANSACTION READ ONLY" and end == "ROLLBACK" and session.closed
    assert explained == f"EXPLAIN (VERBOSE, FORMAT JSON) {query}", "the same statement, planned in the same transaction"
    assert query.startswith("SELECT * FROM (\nSELECT 1 FROM reporting.sell_out_weekly\n) AS wizard_query") and result.rows
    assert ("pg_catalog", "generate_series") in plan_relations(ALLOWED_PLAN), "metadata schemas are always allowed"


def test_a_query_that_reads_another_schema_is_refused_before_it_runs():
    session = PlanSession(REFUSED_PLAN)
    with pytest.raises(SourceError) as error:
        PostgresQuery(LIMITED, connect=lambda s, d: session).run(
            "WITH segments AS (SELECT * FROM restricted.customers) SELECT * FROM segments")
    assert error.value.code == "schema_not_allowed"
    message = error.value.message
    assert message.startswith("This query reads restricted.customers (schema restricted), and Wizard may query only the "
                              "schema reporting of this database (with pg_catalog and information_schema for metadata).")
    assert "A view counts by the tables it reads." in message and "reporting.orders" not in message
    assert [s.split(" ")[0] for s in session.statements] == ["START", "EXPLAIN", "ROLLBACK"], "the query itself never ran"
    assert session.closed
    two = dataclasses.replace(SETTINGS, schemas=("reporting", "Sales Data"))
    with pytest.raises(SourceError, match="only the schemas reporting, Sales Data of this database"):
        PostgresQuery(two, connect=lambda s, d: PlanSession(REFUSED_PLAN)).run("SELECT 1")
    assert plan_relations(json.loads(REFUSED_PLAN)) == [("restricted", "customers"), ("reporting", "orders"),
                                                        ("restricted", "customers")]


def test_with_no_schemas_set_nothing_is_explained():
    session = PlanSession(REFUSED_PLAN)
    PostgresQuery(SETTINGS, connect=lambda s, d: session).run("SELECT * FROM restricted.customers")
    assert not any(s.startswith("EXPLAIN") for s in session.statements), "empty: no limit, today's behaviour"


def test_a_plan_that_cannot_be_read_or_made_is_not_waved_through():
    with pytest.raises(SourceError, match="no plan"):
        PostgresQuery(LIMITED, connect=lambda s, d: PlanSession(None)).run("SELECT 1")
    broken = FakeSession(error=Exception({"S": "ERROR", "C": "42601", "M": 'syntax error at or near "FORM"'}))
    with pytest.raises(SourceError) as error:
        PostgresQuery(LIMITED, connect=lambda s, d: broken).run("SELECT * FORM reporting.orders")
    assert error.value.code == "query_failed" and broken.statements[1].startswith("EXPLAIN")
    assert len(broken.statements) == 3 and broken.statements[-1] == "ROLLBACK" and broken.closed


def test_a_missing_relation_never_points_at_a_schema_wizard_may_not_query():
    here = CatalogSession([("restricted", "global_lc_v"), ("reporting", "global_lc_v_weekly")], databases=["dwh"],
                          error=MISSING)
    sessions = {"meto_db": here, "dwh": CatalogSession([("restricted", "global_lc_v")])}
    with pytest.raises(SourceError) as error:
        PostgresQuery(LIMITED, connect=lambda s, d: sessions[d]).run("SELECT * FROM bi_reporting.global_lc_v")
    message = error.value.message
    assert "similar name in database meto_db: reporting.global_lc_v_weekly." in message
    assert "restricted" not in message and "database dwh" not in message


def test_the_schemas_setting_is_read_as_postgresql_names_them(tmp_path):
    assert schema_list(' Reporting , "Sales Data", reporting,, ') == ("reporting", "Sales Data")
    assert schema_list("") == ()
    for wrong in ("sales data", "reporting;drop", '"bad"name"'):
        with pytest.raises(PgError, match="schema names separated by commas"):
            schema_list(wrong)
    env = {"WIZARD_AGENT_RUNTIME": "replay", "WIZARD_PG_HOST": "db.corp", "WIZARD_PG_USER": "reader",
           "WIZARD_ATTACHMENT_OFFICE": "never", "WIZARD_ATTACHMENT_FOLDERS": "none"}
    settings = load_settings(env={**env, "WIZARD_PG_SCHEMAS": "Reporting"}, home=tmp_path)
    assert settings.postgres is not None and settings.postgres.schemas == ("reporting",)
    assert "schemas reporting only" in settings.postgres.describe(), "run.py --check says so"
    with pytest.raises(ConfigError, match="PostgreSQL settings: the schemas Wizard may query"):
        load_settings(env={**env, "WIZARD_PG_SCHEMAS": "a b"}, home=tmp_path)


def test_the_tool_refuses_another_schema_and_records_no_evidence():
    services = build_services()
    services.postgres = PostgresQuery(LIMITED, connect=lambda s, d: PlanSession(REFUSED_PLAN))
    ctx = ToolContext(identity=owner(), run_id="r", recorder=MemoryRecorder(), services=services)
    outcome = build_registry(services).execute("wizard_query_postgresql", {"sql": "SELECT * FROM restricted.customers"}, ctx)
    assert not outcome.ok and outcome.error_code == "schema_not_allowed"
    assert "restricted.customers" in str(outcome.error_message) and ctx.recorder.get_evidence("E1") is None
