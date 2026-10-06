"""Gemini's read-only SQL tool without a server: the SQL is sent as written inside a read-only transaction that is always
rolled back, results are capped and typed, rights and evidence, Check my data replays, and the local Owner's access."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, MemoryRecorder

from wizard_api.app import create_app
from wizard_api.config import load_settings
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.fixture_source import SourceError
from wizard_connectors.pg import PgError, PgSettings
from wizard_connectors.postgres_query import PostgresQuery, without_terminator
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
