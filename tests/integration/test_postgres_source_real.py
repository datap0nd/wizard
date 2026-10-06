"""The live PostgreSQL source against a real server (CI runs PostgreSQL; elsewhere BLOCKED): every aggregation rule,
filters, market rights, sorting and the row cap, compared with figures computed independently in Python."""
from __future__ import annotations

import os
import secrets
from collections import defaultdict

import pytest

from wizard_connectors.catalog import Report
from wizard_connectors.fixture_source import Filter, Sort, SourceError
from wizard_connectors.pg import PgSettings
from wizard_connectors.postgres_source import PostgresSource

HOST = os.environ.get("WIZARD_TEST_PG_HOST")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not HOST, reason="BLOCKED: no PostgreSQL test server (WIZARD_TEST_PG_HOST, "
                                                  "WIZARD_TEST_PG_USER, WIZARD_TEST_PG_PASSWORD)")]

ROWS = [  # market, week, model, currency, units (text, as Metronome loads it), revenue, stock, share
    (market, week, model, "USD" if market != "EG" else ("EGP" if model == "A" else "USD"), str(units), revenue, stock, share)
    for market, week, model, units, revenue, stock, share in [
        ("EG", 202639, "A", 10, 100.0, 5, 0.31), ("EG", 202639, "S", 4, 80.0, 2, 0.12),
        ("EG", 202640, "A", 12, 120.0, 7, 0.32), ("EG", 202640, "S", 6, 90.0, 3, 0.13),
        ("SA", 202639, "A", 20, 200.0, 9, 0.28), ("SA", 202640, "A", 25, 250.0, 11, 0.29),
        ("AE", 202640, "S", 7, 140.0, 1, 0.25),
    ]
]


def report() -> Report:
    return Report.model_validate({
        "id": "postgresql-docs-reporting-mv-sellin", "name": "docs_reporting.mv_sellin", "folder": "f",
        "type": "report", "row_access": "ROWS", "file": None, "description": "Weekly sell-in", "as_of": None,
        "grain": ["market", "fiscal_week", "model"], "refresh": "nightly",
        "dimensions": [{"key": "market", "label": "Market", "type": "string", "role": "market"},
                       {"key": "fiscal_week", "label": "Week", "type": "integer", "role": "period"},
                       {"key": "model", "label": "Model", "type": "string", "role": "model", "column": "Model Family"},
                       {"key": "local_currency", "label": "Currency", "type": "string"}],
        "measures": [{"key": "units", "label": "Units", "type": "integer", "aggregation": "sum"},
                     {"key": "revenue", "label": "Revenue", "type": "currency", "unit": "local",
                      "aggregation": "sum_same_currency"},
                     {"key": "stock", "label": "Channel stock", "type": "integer", "aggregation": "last"},
                     {"key": "share", "label": "Share", "type": "percent", "unit": "%", "aggregation": "none"}],
        "attributes": [], "prompts": [], "caveats": [], "sensitivity": "internal",
        "relation": {"database": "x", "schema": "docs_reporting", "name": "mv_sellin"}})


@pytest.fixture(scope="module")
def source():
    pg8000 = pytest.importorskip("pg8000.native", reason="BLOCKED: pg8000 is not installed")
    admin = pg8000.Connection(os.environ.get("WIZARD_TEST_PG_USER", "postgres"), host=HOST,
                              port=int(os.environ.get("WIZARD_TEST_PG_PORT", "5432")),
                              password=os.environ.get("WIZARD_TEST_PG_PASSWORD"), ssl_context=False)
    password = secrets.token_hex(12)
    for statement in ["DROP SCHEMA IF EXISTS docs_reporting CASCADE", "DROP ROLE IF EXISTS wizard_live_reader",
                      "CREATE SCHEMA docs_reporting",
                      'CREATE TABLE docs_reporting.base (market text, fiscal_week integer, "Model Family" text, '
                      "local_currency text, units text, revenue numeric, stock integer, share numeric)"]:
        admin.run(statement)
    for row in ROWS:
        admin.run("INSERT INTO docs_reporting.base VALUES (:a, :b, :c, :d, :e, :f, :g, :h)",
                  a=row[0], b=row[1], c=row[2], d=row[3], e=row[4], f=row[5], g=row[6], h=row[7])
    for statement in ["CREATE MATERIALIZED VIEW docs_reporting.mv_sellin AS SELECT * FROM docs_reporting.base",
                      f"CREATE ROLE wizard_live_reader LOGIN PASSWORD '{password}'",
                      "GRANT USAGE ON SCHEMA docs_reporting TO wizard_live_reader",
                      "GRANT SELECT ON docs_reporting.mv_sellin TO wizard_live_reader"]:
        admin.run(statement)
    database = admin.run("SELECT current_database()")[0][0]
    settings = PgSettings(HOST, int(os.environ.get("WIZARD_TEST_PG_PORT", "5432")), database, "wizard_live_reader",
                          password, "prefer", "test")
    live = PostgresSource(settings)
    yield live, database
    for statement in ["DROP SCHEMA docs_reporting CASCADE", "DROP OWNED BY wizard_live_reader", "DROP ROLE wizard_live_reader"]:
        admin.run(statement)
    admin.close()


def run(source, **request):
    live, database = source
    entry = report().model_copy(update={"relation": report().relation.model_copy(update={"database": database})})
    options = {"filters": [], "group_by": None, "measures": None, "sort": None, "limit": 200, "allowed_markets": None}
    options.update(request)
    return live.run(entry, **options)


def table(result):
    keys = [c["key"] for c in result.columns]
    return [dict(zip(keys, row, strict=True)) for row in result.rows]


def test_rows_filters_and_text_measures(source):
    result = run(source, filters=[Filter("market", ["eg"])], sort=[Sort("units", "desc")])
    rows = table(result)
    assert [r["units"] for r in rows] == [12, 10, 6, 4], "text units are read as numbers; filters ignore case"
    assert rows[0]["model"] == "A" and result.total_rows == 4 and not result.truncated
    assert result.data_mode == "LIVE_UNVERIFIED" and "not yet checked" in result.verification


def test_sum_last_none_and_currency_rules(source):
    by_market = {r["market"]: r for r in table(run(source, group_by=["market"]))}
    expected_units: dict[str, int] = defaultdict(int)
    for row in ROWS:
        expected_units[row[0]] += int(row[4])
    assert {m: r["units"] for m, r in by_market.items()} == expected_units
    assert by_market["EG"]["stock"] == 10 and by_market["SA"]["stock"] == 11, "period-end balance at the latest week"
    assert by_market["EG"]["revenue"] is None and by_market["SA"]["revenue"] == 450, "EG mixes EGP and USD"
    assert by_market["AE"]["share"] == 0.25 and by_market["EG"]["share"] is None, "a share is never added up"
    warnings = " ".join(run(source, group_by=["market"]).warnings)
    assert "mixes currencies" in warnings and "rate or share" in warnings and "period-end balance" in warnings
    weekly = table(run(source, group_by=["market", "fiscal_week"], filters=[Filter("market", ["SA"])]))
    assert [(r["fiscal_week"], r["units"], r["stock"]) for r in weekly] == [(202639, 20, 9), (202640, 25, 11)]


def test_market_rights_missing_values_and_cap(source):
    limited = run(source, group_by=["market"], allowed_markets={"SA"})
    assert [r["market"] for r in table(limited)] == ["SA"] and "SA" in limited.access_note
    denied = run(source, filters=[Filter("market", ["EG"])], allowed_markets={"SA"})
    assert denied.rows == [] and "not entitled to market(s) EG" in denied.access_note
    missing = run(source, filters=[Filter("fiscal_week", ["202650"])])
    assert missing.rows == [] and any("No rows exist for fiscal_week = 202650" in w for w in missing.warnings)
    capped = run(source, limit=3)
    assert len(capped.rows) == 3 and capped.total_rows == len(ROWS) and capped.truncated
    total = table(run(source, group_by=[], measures=["units"]))
    assert total == [{"units": sum(int(r[4]) for r in ROWS)}]


def test_the_session_cannot_write_and_errors_are_explained(source):
    with pytest.raises(SourceError, match="invalid_filter|not a filterable"):
        run(source, filters=[Filter("units", ["1"])])
    live, database = source
    broken = report().model_copy(update={"relation": report().relation.model_copy(update={"database": database,
                                                                                           "name": "missing_view"})})
    with pytest.raises(SourceError) as error:
        live.run(broken, filters=[], group_by=None, measures=None, sort=None, limit=5, allowed_markets=None)
    assert error.value.code == "source_unavailable" and "does not exist" in error.value.message
