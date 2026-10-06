"""Live PostgreSQL source without a server: SQL shape (quoted identifiers, bound values, read-only SELECTs only),
contract rules for live reports, the tool's evidence (LIVE_UNVERIFIED until parity is signed) and settings."""
from __future__ import annotations

import json
from typing import Any

import pytest
from tests.helpers import MemoryRecorder

from wizard_connectors.catalog import Report, SourceContract
from wizard_connectors.content import errors, validate_content
from wizard_connectors.fixture_source import Filter, SourceError
from wizard_connectors.pg import PgError, PgSettings, settings_from
from wizard_connectors.postgres_source import PostgresSource
from wizard_connectors.tools import ToolContext, build_registry, build_services

SETTINGS = PgSettings("db.corp", 5432, "meto_db", "reader", "secret", "prefer", "test")


def contract(parity: dict[str, str] | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "id": "postgresql-bi-reporting-sell-in-amt-mv", "name": "bi_reporting.sell_in_amt_mv", "folder": "pg-meto-db",
        "type": "report", "row_access": "ROWS", "file": None, "description": "SIBP sell-in amount by market and week",
        "grain": ["market", "week"], "as_of": None, "refresh": "pg_cron nightly",
        "dimensions": [{"key": "market", "label": "Market", "type": "string", "role": "market"},
                       {"key": "week", "label": "Week", "type": "integer", "role": "period", "column": "Fiscal Week"}],
        "measures": [{"key": "sell_in_amt", "label": "Sell-in amount", "type": "currency", "unit": "USD", "aggregation": "sum"}],
        "attributes": [], "prompts": [], "caveats": [], "sensitivity": "internal",
        "relation": {"database": "meto_db", "schema": "bi_reporting", "name": "sell_in_amt_mv"}}
    if parity:
        report["parity"] = parity
    return {"contract_version": 1,
            "system": {"id": "postgresql", "name": "PostgreSQL", "description": "Metronome's reporting database",
                       "families": ["sell_in"], "owner": "TBD",
                       "connector": {"status": "ROWS_UNVERIFIED", "data_mode": "LIVE_UNVERIFIED", "transport": "postgresql",
                                     "live_interface": "PostgreSQL read-only (pg8000)"}, "open_url_template": None},
            "folders": [{"id": "pg-meto-db", "name": "meto_db / bi_reporting", "parent": None}], "reports": [report]}


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        if "pg_attribute" in sql:
            return [{"name": "market", "type": "text"}, {"name": "Fiscal Week", "type": "integer"},
                    {"name": "sell_in_amt", "type": "text"}]
        if "DISTINCT" in sql:
            return [{"v": "eg"}]
        if "track_commit_timestamp" in sql:
            return [{"tracked": False}]
        if "__total" in sql:
            from decimal import Decimal
            return [{"c0": "EG", "c1": Decimal("1234.50"), "__n": 3, "__total": 1}]
        return []

    def close(self) -> None:
        pass


def test_grouped_query_is_quoted_bound_and_read_only():
    session = FakeSession()
    live = PostgresSource(SETTINGS, connect=lambda settings, database: session)
    report = Report.model_validate(contract()["reports"][0])
    result = live.run(report, filters=[Filter("market", ["EG", "x'); DROP TABLE t;--"])], group_by=["market"],
                      measures=None, sort=None, limit=50, allowed_markets={"EG"})
    sql, params = next(c for c in session.calls if "__total" in c[0])
    assert sql.startswith("SELECT ") and "DROP" not in sql, "values never reach the SQL text"
    assert params["f0"] == ["eg", "x'); drop table t;--"] and params["allowed_markets"] == ["EG"]
    assert 'FROM "bi_reporting"."sell_in_amt_mv"' in sql and "CAST(NULLIF(btrim(\"sell_in_amt\"::text), '') AS numeric)" in sql
    assert "sum(c1) AS c1" in sql and "GROUP BY c0" in sql and "LIMIT :limit" in sql and params["limit"] == 50
    assert all(c[0].startswith(("SELECT", "SET statement_timeout")) for c in session.calls)
    assert result.rows == [["EG", 1234.5]] and result.data_mode == "LIVE_UNVERIFIED"
    assert any("freshness is unknown" in w for w in result.warnings)
    assert "not entitled to market(s) x'); DROP TABLE t;--" in result.access_note, "an unentitled market is a rights note"


def test_mapped_column_names_and_missing_settings():
    session = FakeSession()
    live = PostgresSource(SETTINGS, connect=lambda settings, database: session)
    report = Report.model_validate(contract()["reports"][0])
    live.run(report, filters=[], group_by=None, measures=None, sort=None, limit=10, allowed_markets=None)
    sql = next(c[0] for c in session.calls if "__total" in c[0])
    assert '"Fiscal Week" AS c1' in sql and "ORDER BY c0 ASC NULLS LAST, c1 ASC NULLS LAST" in sql
    with pytest.raises(SourceError, match="connection settings are missing"):
        PostgresSource(None).run(report, filters=[], group_by=None, measures=None, sort=None, limit=10, allowed_markets=None)


class GoneSession(FakeSession):
    """The view existed when Wizard read its columns, then was dropped (pg8000 reports SQLSTATE 42P01)."""

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        if "__total" in sql:
            raise Exception({"S": "ERROR", "C": "42P01", "M": 'relation "bi_reporting.sell_in_amt_mv" does not exist'})
        return super().rows(sql, **params)


def test_a_missing_view_is_unavailable_not_a_query_error():
    report = Report.model_validate(contract()["reports"][0])
    args = {"filters": [], "group_by": None, "measures": None, "sort": None, "limit": 10, "allowed_markets": None}
    empty = FakeSession()
    empty.rows = lambda sql, **params: [] if "pg_attribute" in sql else FakeSession.rows(empty, sql, **params)  # type: ignore[method-assign]
    with pytest.raises(SourceError) as error:
        PostgresSource(SETTINGS, connect=lambda s, d: empty).run(report, **args)
    assert error.value.code == "source_unavailable" and "does not exist" in error.value.message
    sessions = iter([FakeSession(), GoneSession(), FakeSession()])
    live = PostgresSource(SETTINGS, connect=lambda s, d: next(sessions))
    live.run(report, **args)
    with pytest.raises(SourceError) as error:
        live.run(report, **args)
    assert error.value.code == "source_unavailable" and "42P01" in error.value.message
    assert live._types == {}, "the stale column list is dropped, so the next query re-reads the view"
    moved = report.model_copy(update={"relation": report.relation.model_copy(update={"name": "other_mv"})})
    live.run(moved, **args)
    assert list(live._types) == ['meto_db:"bi_reporting"."other_mv"'], "column types are cached per database and view"


def test_contract_rules_for_live_reports(tmp_path):
    root = tmp_path / "content"
    (root / "contracts" / "sources").mkdir(parents=True)
    target = root / "contracts" / "sources" / "postgresql.json"
    target.write_text(json.dumps(contract()), encoding="utf-8")
    problems = validate_content(root)
    assert not errors(problems) and any("not yet checked" in p.message for p in problems)
    bad = contract()
    bad["system"]["connector"]["status"] = "ROWS_VERIFIED"
    bad["reports"][0].pop("relation")
    bad["reports"][0]["measures"].append({"key": "stock", "label": "Stock", "type": "integer", "aggregation": "last"})
    bad["reports"][0]["dimensions"][1]["role"] = None
    target.write_text(json.dumps(bad), encoding="utf-8")
    messages = " | ".join(p.message for p in errors(validate_content(root)))
    for expected in ("never the whole system at once", "names the object it reads", "needs exactly one dimension with role period"):
        assert expected in messages
    other = contract()
    other["system"]["id"] = "gscm"
    other["reports"][0]["id"] = "gscm-sell-in"
    target.unlink()
    (root / "contracts" / "sources" / "gscm.json").write_text(json.dumps(other), encoding="utf-8")
    assert any("needs an approved live adapter" in p.message for p in errors(validate_content(root)))


def test_evidence_is_live_unverified_until_parity_is_signed(tmp_path, identities):
    folder = tmp_path / "sources"
    folder.mkdir()
    for parity, mode in ((None, "LIVE_UNVERIFIED"),
                         ({"checked": "2026-10-10", "by": "Ana Silva (Finance)", "reference": "SIBP EG week 202640"}, "LIVE_VERIFIED")):
        (folder / "postgresql.json").write_text(json.dumps(contract(parity)), encoding="utf-8")
        SourceContract.model_validate(contract(parity))
        session = FakeSession()
        services = build_services(contracts=folder, knowledge=tmp_path / "none",
                                  live={"postgresql": PostgresSource(SETTINGS, connect=lambda s, d, session=session: session)})
        owner = identities.get("u-ceo").__class__(id="o", email="o@x", name="O", role="Owner",
                                                  entitlements={"postgresql": identities.get("u-ceo").entitlements["nerp"].__class__(
                                                      reports=["*"], markets=["*"])})
        ctx = ToolContext(identity=owner, run_id="r", recorder=MemoryRecorder(), services=services)
        outcome = build_registry(services).execute("postgresql_run_report", {
            "report_id": "postgresql-bi-reporting-sell-in-amt-mv", "group_by": ["market"]}, ctx)
        assert outcome.ok, outcome.error_message
        assert outcome.data["source"]["data_mode"] == mode and ctx.recorder.get_evidence("E1")["data_mode"] == mode
        assert ("note" in outcome.data) == (mode == "LIVE_UNVERIFIED")


def test_settings_resolution():
    assert settings_from({}, {}) is None
    found = settings_from({"WIZARD_PG_HOST": "h", "WIZARD_PG_USER": "u"}, {"PGHOST": "other"})
    assert found is not None and (found.host, found.port, found.sslmode, found.source) == ("h", 5432, "prefer", ".env (WIZARD_PG_*)")
    with pytest.raises(PgError):
        settings_from({}, {"PGHOST": "h", "PGUSER": "u", "PGPORT": "x"})
