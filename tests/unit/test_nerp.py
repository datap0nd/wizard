"""NERP (owner, 3 Nov 2026): a few SQL views on a PostgreSQL server of their own, restricted to one server, one database
and one schema, views only, read with one read-only account. The settings, the views-only check, the query's protections,
the tools and their evidence, and NERP taking over its report catalog. No database is needed: sessions are faked, and
every name here is invented."""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, MemoryRecorder, login, make_settings, wait_run
from tests.integration.test_steering_api import ScriptedRuntime, say

from wizard_api import provisioning, settings_pane
from wizard_api.app import create_app
from wizard_api.config import load_settings
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.fixture_source import SourceError
from wizard_connectors.knowledge import KnowledgeBase
from wizard_connectors.nerp import NerpQuery, check_views, settings_from
from wizard_connectors.pg import PgError
from wizard_connectors.tools import ToolContext, build_registry, build_services, connect_nerp

VIEWS = {"v_spend", "v_budget", "V_Mixed"}
VALUES = {"WIZARD_NERP_HOST": "nerp-db.corp.example", "WIZARD_NERP_DATABASE": "nerp", "WIZARD_NERP_SCHEMA": "reporting",
          "WIZARD_NERP_USER": "wizard_nerp_ro", "WIZARD_NERP_PASSWORD": "secret"}


# Settings: one server (an address or a URL), one database, one schema --------------------------------------------------
def test_the_server_is_a_host_host_and_port_or_a_postgresql_address():
    plain = settings_from(VALUES)
    assert plain and (plain.pg.host, plain.pg.port, plain.pg.database, plain.schema) == ("nerp-db.corp.example", 5432, "nerp", "reporting")
    assert plain.pg.schemas == ("reporting",) and plain.name == "NERP" and "views only" in plain.describe()
    ported = settings_from({**VALUES, "WIZARD_NERP_HOST": "nerp-db.corp.example:6432"})
    assert ported and ported.pg.port == 6432
    url = settings_from({k: v for k, v in VALUES.items() if k not in ("WIZARD_NERP_DATABASE", "WIZARD_NERP_USER")}
                        | {"WIZARD_NERP_HOST": "postgresql://reader@nerp-db.corp.example:7432/finance", "WIZARD_NERP_NAME": "N-ERP"})
    assert url and (url.pg.host, url.pg.port, url.pg.database, url.pg.user, url.name) == (
        "nerp-db.corp.example", 7432, "finance", "reader", "N-ERP")
    assert settings_from({}) is None, "no server: NERP is not connected"


@pytest.mark.parametrize(("change", "words"), [
    ({"WIZARD_NERP_HOST": "postgresql://reader:pw@host/db"}, "Password field"),
    ({"WIZARD_NERP_HOST": "mysql://host/db"}, "postgresql://"),
    ({"WIZARD_NERP_SCHEMA": ""}, "schema"),
    ({"WIZARD_NERP_DATABASE": ""}, "database"),
    ({"WIZARD_NERP_USER": ""}, "user"),
    ({"WIZARD_NERP_PORT": "x"}, "port"),
    ({"WIZARD_NERP_SSLMODE": "maybe"}, "SSL"),
])
def test_incomplete_settings_say_what_to_fix(change, words):
    with pytest.raises(PgError, match=words):
        settings_from({**VALUES, **change})


def test_incomplete_settings_leave_nerp_off_and_wizard_starts(tmp_path):
    settings = make_settings(tmp_path, WIZARD_NERP_HOST="nerp-db.corp.example", WIZARD_NERP_USER="ro")
    assert settings.nerp is None and "database" in (settings.nerp_problem or "")


# Views only ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT market, sum(amount) FROM v_spend GROUP BY 1",
    "SELECT * FROM reporting.v_spend s JOIN reporting.v_budget b USING (market)",
    "WITH s AS (SELECT * FROM v_spend) SELECT * FROM s, generate_series(1, 3) g",
    'SELECT * FROM "V_Mixed"',
    "SELECT * FROM nerp.reporting.v_spend",
    "SELECT date_trunc('month', day), coalesce(sum(amount), 0) FROM v_spend WHERE day >= current_date - 7 GROUP BY 1",
    "SELECT a FROM v_spend WHERE b IN (SELECT b FROM v_budget) UNION ALL SELECT a FROM v_budget",
    "SELECT pg_catalog.upper(market) FROM v_spend",
])
def test_queries_on_the_schemas_views_pass(sql):
    check_views(sql, VIEWS, "reporting", "nerp")


@pytest.mark.parametrize(("sql", "words"), [
    ("SELECT * FROM spend_raw", "spend_raw (not one of reporting's views)"),
    ("SELECT * FROM finance.v_spend", "schema finance"),
    ("SELECT * FROM pg_catalog.pg_class", "schema pg_catalog"),
    ("SELECT * FROM information_schema.tables", "schema information_schema"),
    ("SELECT * FROM v_mixed", "not one of reporting's views"),  # unquoted folds to lower case: not "V_Mixed"
    ("SELECT * FROM other.reporting.v_spend", "another database"),
    ("SELECT * FROM (WITH spend_raw AS (SELECT 1) SELECT * FROM spend_raw) a, spend_raw", "spend_raw (not one"),
    ("SELECT query_to_xml('select * from finance.secret', true, true, '')", "query_to_xml()"),
    ("SELECT * FROM dblink('host=x', 'select 1') AS t(a int)", "dblink"),
    ("SELECT finance.decode(amount) FROM v_spend", "a function of another schema"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_read_file()"),
])
def test_anything_but_the_schemas_views_is_refused(sql, words):
    with pytest.raises(SourceError) as refused:
        check_views(sql, VIEWS, "reporting", "nerp")
    assert refused.value.code == "not_a_nerp_view" and words in refused.value.message, refused.value.message


@pytest.mark.parametrize("sql", ["SELECT 1 FROM v_spend; DELETE FROM v_spend", "DELETE FROM v_spend",
                                 "SELECT * INTO copy FROM v_spend", "UPDATE v_spend SET amount = 0"])
def test_only_one_select_is_sent(sql):
    with pytest.raises(SourceError) as refused:
        check_views(sql, VIEWS, "reporting", "nerp")
    assert refused.value.code in ("not_a_query", "query_not_checked")


class FakeSession:
    """A NERP session: the catalog lists the views; every statement is recorded."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        self.statements.append(sql)
        if "pg_catalog.pg_class c JOIN" in sql and params.get("schema") == "reporting":
            return [{"name": "v_spend", "kind": "v", "comment": "Spend postings", "columns": 3},
                    {"name": "v_budget", "kind": "m", "comment": None, "columns": 2}]
        if "format_type" in sql:
            return [{"name": "day", "type": "date", "comment": None}, {"name": "amount", "type": "numeric", "comment": "USD"}]
        return []

    def query(self, sql: str) -> tuple[list[dict[str, Any]], list[list[Any]]]:
        self.statements.append(sql)
        return [{"name": "day", "type_oid": 1082}, {"name": "amount", "type_oid": 1700}], [[dt.date(2026, 11, 2), Decimal("12.50")]]

    def close(self) -> None:
        self.closed = True


def nerp(session: FakeSession) -> NerpQuery:
    settings = settings_from(VALUES)
    assert settings is not None
    return NerpQuery(settings, connect=lambda s, database: session)


def test_a_query_runs_in_a_read_only_transaction_on_the_schemas_views_only():
    session = FakeSession()
    result = nerp(session).run("SELECT day, sum(amount) FROM v_spend GROUP BY 1", "another_db", 50)
    start, catalog, path, query, end = session.statements
    assert start == "START TRANSACTION READ ONLY" and end == "ROLLBACK" and session.closed
    assert "relkind IN ('v', 'm')" in catalog
    assert path == 'SET LOCAL search_path TO "reporting", pg_catalog', "an unqualified name means NERP's view"
    assert query.startswith("SELECT * FROM (\nSELECT day, sum(amount) FROM v_spend GROUP BY 1\n) AS wizard_query LIMIT 51")
    assert result.database == "nerp" and result.rows == [["2026-11-02", 12.5]], "never another database"

    refused = FakeSession()
    with pytest.raises(SourceError, match="not one of reporting's views"):
        nerp(refused).run("SELECT * FROM spend_raw")
    assert not any(s.startswith("SELECT * FROM (") for s in refused.statements), "a refused statement never runs"
    assert refused.statements[-1] == "ROLLBACK" and refused.closed


# The tools ----------------------------------------------------------------------------------------------------------
def tools(tmp_path: Path, notes: str = "") -> tuple[Any, ToolContext]:
    services = build_services()
    if notes:
        folder = tmp_path / "knowledge" / "datasets"
        folder.mkdir(parents=True)
        (folder / "nerp-reporting-v-spend.md").write_text(notes, encoding="utf-8")
        services.knowledge = KnowledgeBase.load(tmp_path / "knowledge")
    assert "nerp" in services.catalog.contracts, "the synthetic NERP catalog, before NERP is connected"
    settings = settings_from(VALUES)
    assert settings is not None
    connect_nerp(services, settings)
    session = FakeSession()
    services.nerp.connect = lambda s, database: session  # type: ignore[union-attr]
    identity = Identity(id="ceo", email="ceo@example.com", name="CEO", role="CEO",
                        entitlements={"nerp": SystemRights(reports=["*"], markets=["*"])})
    return build_registry(services), ToolContext(identity=identity, run_id="run_t", recorder=MemoryRecorder(), services=services)


NOTE = """---
id: nerp-reporting-v-spend
title: "reporting.v_spend: marketing spend postings"
type: dataset
status: DRAFT_UNSIGNED
owner: TBD - finance systems (ask the user)
aliases: [reporting.v_spend, v_spend, marketing spend]
---
One row per posting.
"""


def test_connected_nerp_replaces_its_catalog_with_the_view_tools(tmp_path):
    registry, context = tools(tmp_path, NOTE)
    names = [s.name for s in registry.list()]
    assert {"nerp_list_views", "nerp_view_columns", "nerp_query"} <= set(names)
    assert not [n for n in names if n in ("nerp_search_reports", "nerp_run_report", "nerp_get_report_schema")]
    assert "nerp" not in context.services.catalog.contracts and "nerp" in registry.scopes()

    listed = registry.execute("nerp_list_views", {"find": "marketing spend"}, context)
    assert listed.ok and listed.data["schema"] == "reporting" and listed.data["database"] == "nerp"
    first = listed.data["views"][0]
    assert first == {"view": "v_spend", "qualified": "reporting.v_spend", "kind": "view", "columns": 3,
                     "comment": "Spend postings", "note": "nerp-reporting-v-spend"}
    assert listed.data["unmapped"] == ["v_budget"]
    columns = registry.execute("nerp_view_columns", {"view": "reporting.v_spend"}, context)
    assert columns.ok and columns.data["columns"][1] == {"name": "amount", "type": "numeric", "comment": "USD"}
    assert columns.data["note"] == "nerp-reporting-v-spend" and "dataset note" in columns.data["how_to_use"]

    ran = registry.execute("nerp_query", {"sql": "SELECT day, sum(amount) FROM v_spend GROUP BY 1"}, context)
    assert ran.ok and ran.data["cite_as"] == "[E1]" and ran.data["rows"] == [["2026-11-02", 12.5]]
    evidence = context.recorder.evidence[0]  # type: ignore[attr-defined]
    assert (evidence["system"], evidence["data_mode"], evidence["connector_status"]) == ("nerp", "LIVE", "READ_ONLY_SQL")
    assert evidence["request"] == {"sql": "SELECT day, sum(amount) FROM v_spend GROUP BY 1", "database": "nerp",
                                   "schema": "reporting", "max_rows": 200}
    refused = registry.execute("nerp_query", {"sql": "SELECT * FROM finance.ledger"}, context)
    assert refused.error_code == "not_a_nerp_view" and "nerp_list_views" in refused.error_message


def test_a_person_without_nerp_cannot_use_it(tmp_path):
    registry, context = tools(tmp_path)
    context.identity = Identity(id="x", email="x@example.com", name="X", role="Director", entitlements={})
    assert registry.execute("nerp_list_views", {}, context).error_code == "not_entitled"


def test_settings_show_the_nerp_section_and_its_test_needs_the_essentials(tmp_path):
    assert any(section[0] == "nerp" for section in settings_pane.SECTIONS)
    keys = {f.key for f in settings_pane.FIELDS if f.section == "nerp"}
    assert keys == {"WIZARD_NERP_NAME", "WIZARD_NERP_HOST", "WIZARD_NERP_PORT", "WIZARD_NERP_DATABASE", "WIZARD_NERP_SCHEMA",
                    "WIZARD_NERP_USER", "WIZARD_NERP_PASSWORD", "WIZARD_NERP_SSLMODE"}
    assert next(f for f in settings_pane.FIELDS if f.key == "WIZARD_NERP_PASSWORD").secret
    settings = make_settings(tmp_path)
    assert settings_pane.test_nerp(settings, {"WIZARD_NERP_HOST": "postgresql://u:p@h/d"})["message"].startswith("Put NERP's password")
    assert "server, the database" in settings_pane.test_nerp(settings, {})["message"]


def test_nerp_is_a_live_database_on_the_stage_and_in_the_prompt_tools(tmp_path):
    runtime = ScriptedRuntime()
    outcomes: list[tuple[bool, str]] = []

    async def script(request, emit, tools):
        outcomes.append(await tools.call("wizard_list_sources", {}))
        await say(emit, "Done.")

    runtime.script = script
    settings = make_settings(tmp_path, **VALUES)
    with TestClient(create_app(settings, runtime=runtime)) as client:  # type: ignore[arg-type]
        login(client, "u-ceo")
        systems = {s["id"]: s for s in client.get("/api/v1/bootstrap").json()["systems"]}
        assert systems["nerp"]["kind"] == "database" and systems["nerp"]["data_mode"] == "LIVE"
        started = client.post("/api/v1/runs", json={"question": "Spend last week?"}, headers=HEADERS).json()
        assert wait_run(client, started["run_id"])["status"] == "succeeded"
        assert {"nerp_list_views", "nerp_query"} <= set(runtime.offered[0])
        assert not [t for t in runtime.offered[0] if t.startswith("nerp_search")]
        listed = {s["system"]: s for s in json.loads(outcomes[0][1])["sources"]}
        assert "nerp_list_views" in listed["nerp"]["how_to_navigate"] and "views" in listed["nerp"]["description"]


def test_a_company_file_carries_nerp_and_export_writes_it(tmp_path):
    company = provisioning.parse(provisioning.render(VALUES, "ACME"))
    assert company.settings["WIZARD_NERP_SCHEMA"] == "reporting" and "WIZARD_NERP_PASSWORD" not in company.settings, \
        "the password is a secret, kept apart (DPAPI on the PC)"
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_text("WIZARD_AGENT_RUNTIME=code-assist\n" + "".join(f"{k}={v}\n" for k, v in VALUES.items()),
                                   encoding="utf-8")
    settings = load_settings(env={"WIZARD_PROXY": "direct"}, home=tmp_path)
    assert settings.nerp is not None and settings.nerp.schema == "reporting"
    exported = settings_pane.export(settings)
    assert {"WIZARD_NERP_HOST", "WIZARD_NERP_DATABASE", "WIZARD_NERP_SCHEMA", "WIZARD_NERP_USER"} <= set(exported["settings"])
    assert exported["secrets"] == ["WIZARD_NERP_PASSWORD"]

