"""Gemini's SQL tool against a real PostgreSQL server (CI runs a PostgreSQL service; elsewhere this is BLOCKED): real
analysis works (CTEs, window functions, joins), and nothing a query tries can write, chain statements or loosen the
session, even under an account that is allowed to write."""
from __future__ import annotations

import os
import secrets

import pytest

from wizard_connectors.fixture_source import SourceError
from wizard_connectors.pg import PgSettings
from wizard_connectors.postgres_query import PostgresQuery

HOST = os.environ.get("WIZARD_TEST_PG_HOST")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not HOST, reason="BLOCKED: no PostgreSQL test server (WIZARD_TEST_PG_HOST, "
                                                  "WIZARD_TEST_PG_USER, WIZARD_TEST_PG_PASSWORD)")]
SALES = [("EG", 202639, 100), ("EG", 202640, 150), ("SA", 202639, 400), ("SA", 202640, 380), ("AE", 202640, 90)]


@pytest.fixture(scope="module")
def tool():
    pg8000 = pytest.importorskip("pg8000.native", reason="BLOCKED: pg8000 is not installed")
    admin = pg8000.Connection(os.environ.get("WIZARD_TEST_PG_USER", "postgres"), host=HOST,
                              port=int(os.environ.get("WIZARD_TEST_PG_PORT", "5432")),
                              password=os.environ.get("WIZARD_TEST_PG_PASSWORD"), ssl_context=False)
    password = secrets.token_hex(12)
    for statement in [
        "DROP SCHEMA IF EXISTS sql_reporting CASCADE", "DROP ROLE IF EXISTS wizard_sql_writer",
        "CREATE SCHEMA sql_reporting",
        "CREATE TABLE sql_reporting.markets (market text PRIMARY KEY, region text)",
        "INSERT INTO sql_reporting.markets VALUES ('EG', 'North Africa'), ('SA', 'Gulf'), ('AE', 'Gulf')",
        "CREATE TABLE sql_reporting.sales (market text, fiscal_week integer, units numeric)",
        "INSERT INTO sql_reporting.sales VALUES ('EG', 202639, 100), ('EG', 202640, 150), ('SA', 202639, 400), "
        "('SA', 202640, 380), ('AE', 202640, 90)",  # SALES
        "CREATE MATERIALIZED VIEW sql_reporting.sell_in_mv AS SELECT * FROM sql_reporting.sales",
        # Deliberately able to write: the tool itself must refuse.
        f"CREATE ROLE wizard_sql_writer LOGIN PASSWORD '{password}'",
        "GRANT USAGE, CREATE ON SCHEMA sql_reporting TO wizard_sql_writer",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA sql_reporting TO wizard_sql_writer",
    ]:
        admin.run(statement)
    database = admin.run("SELECT current_database()")[0][0]
    settings = PgSettings(HOST, int(os.environ.get("WIZARD_TEST_PG_PORT", "5432")), database, "wizard_sql_writer",
                          password, "prefer", "test")
    yield PostgresQuery(settings), admin
    for statement in ["DROP SCHEMA sql_reporting CASCADE", "DROP OWNED BY wizard_sql_writer", "DROP ROLE wizard_sql_writer"]:
        admin.run(statement)
    admin.close()


def test_real_analysis(tool):
    query, _ = tool
    result = query.run("""
        WITH weekly AS (
          SELECT m.region, s.market, s.fiscal_week, sum(s.units) AS units
          FROM sql_reporting.sell_in_mv s JOIN sql_reporting.markets m USING (market)
          GROUP BY 1, 2, 3),
        compared AS (
          SELECT region, market, fiscal_week, units,
                 units - lag(units) OVER (PARTITION BY market ORDER BY fiscal_week) AS change,
                 round(100.0 * units / sum(units) OVER (PARTITION BY fiscal_week), 1) AS share_pct
          FROM weekly)
        SELECT * FROM compared WHERE fiscal_week = 202640 ORDER BY units DESC;  -- latest week
    """)
    assert [c["key"] for c in result.columns] == ["region", "market", "fiscal_week", "units", "change", "share_pct"]
    assert result.rows == [["Gulf", "SA", 202640, 380, -20, 61.3], ["North Africa", "EG", 202640, 150, 50, 24.2],
                           ["Gulf", "AE", 202640, 90, None, 14.5]], "order, numbers and the window functions survive"
    assert query.run("SELECT sum(units) AS total FROM sql_reporting.sales").rows == [[1120]]
    capped = query.run("SELECT * FROM sql_reporting.sales ORDER BY units", max_rows=2)
    assert capped.truncated and [r[2] for r in capped.rows] == [90, 100]


@pytest.mark.parametrize("sql", [
    "DELETE FROM sql_reporting.sales",
    "SELECT 1) AS a; DELETE FROM sql_reporting.sales; SELECT * FROM (SELECT 1",
    "WITH gone AS (DELETE FROM sql_reporting.sales RETURNING *) SELECT * FROM gone",
    "SELECT * FROM sql_reporting.sales FOR UPDATE",
    "SELECT 1) AS a; COMMIT; SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE; SELECT * FROM (SELECT 1",
    "SELECT 1) AS a; CREATE TABLE sql_reporting.planted (x int); SELECT * FROM (SELECT 1",
])
def test_nothing_writes(tool, sql):
    query, admin = tool
    with pytest.raises(SourceError) as error:
        query.run(sql)
    assert error.value.code == "query_failed"
    assert admin.run("SELECT count(*) FROM sql_reporting.sales")[0][0] == len(SALES)
    assert admin.run("SELECT to_regclass('sql_reporting.planted')")[0][0] is None


def test_settings_a_query_changes_do_not_outlive_it(tool):
    query, _ = tool
    query.run("SELECT set_config('default_transaction_read_only', 'off', false) AS loosened")
    assert query.run("SELECT current_setting('transaction_read_only') AS ro").rows == [["on"]]
    with pytest.raises(SourceError, match="does not exist"):
        query.run("SELECT * FROM sql_reporting.missing_view")
