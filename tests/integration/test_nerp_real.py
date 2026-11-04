"""NERP's view tools against a real PostgreSQL server (CI runs a PostgreSQL service; elsewhere this is BLOCKED): a view
whose tables sit in another schema is read through the view; the table under it, another schema's view and the catalog
are refused before they run; an unqualified name means NERP's view even when another schema has one by that name; and
nothing writes, even under an account that may."""
from __future__ import annotations

import os
import secrets

import pytest

from wizard_connectors.fixture_source import SourceError
from wizard_connectors.nerp import NerpQuery, settings_from

HOST = os.environ.get("WIZARD_TEST_PG_HOST")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not HOST, reason="BLOCKED: no PostgreSQL test server (WIZARD_TEST_PG_HOST, "
                                                  "WIZARD_TEST_PG_USER, WIZARD_TEST_PG_PASSWORD)")]


@pytest.fixture(scope="module")
def nerp():
    pg8000 = pytest.importorskip("pg8000.native", reason="BLOCKED: pg8000 is not installed")
    port = int(os.environ.get("WIZARD_TEST_PG_PORT", "5432"))
    admin = pg8000.Connection(os.environ.get("WIZARD_TEST_PG_USER", "postgres"), host=HOST, port=port,
                              password=os.environ.get("WIZARD_TEST_PG_PASSWORD"), ssl_context=False)
    password = secrets.token_hex(12)
    for statement in [
        "DROP SCHEMA IF EXISTS nerp_views CASCADE", "DROP SCHEMA IF EXISTS nerp_raw CASCADE",
        "DROP SCHEMA IF EXISTS nerp_other CASCADE", "DROP ROLE IF EXISTS wizard_nerp_writer",
        "CREATE SCHEMA nerp_raw", "CREATE SCHEMA nerp_views", "CREATE SCHEMA nerp_other",
        "CREATE TABLE nerp_raw.postings (market text, day date, amount numeric, cost_centre text)",
        "INSERT INTO nerp_raw.postings VALUES ('EG', '2026-11-01', 100, 'CC1'), ('EG', '2026-11-02', 50, 'CC2'), "
        "('SA', '2026-11-02', 400, 'CC1')",
        # The view leaves a column out: reading the table would show what the view does not.
        "CREATE VIEW nerp_views.v_spend AS SELECT market, day, amount FROM nerp_raw.postings",
        "CREATE MATERIALIZED VIEW nerp_views.v_spend_daily AS SELECT day, sum(amount) AS amount FROM nerp_raw.postings "
        "GROUP BY day",
        "CREATE TABLE nerp_views.scratch (x int)",
        "CREATE VIEW nerp_other.v_spend AS SELECT 'other' AS market, current_date AS day, 0::numeric AS amount",
        # Deliberately able to write and to read the tables: the tool itself must refuse.
        f"CREATE ROLE wizard_nerp_writer LOGIN PASSWORD '{password}'",
        "GRANT USAGE ON SCHEMA nerp_views, nerp_raw, nerp_other TO wizard_nerp_writer",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA nerp_views, nerp_raw, nerp_other "
        "TO wizard_nerp_writer",
    ]:
        admin.run(statement)
    database = admin.run("SELECT current_database()")[0][0]
    settings = settings_from({"WIZARD_NERP_HOST": f"{HOST}:{port}", "WIZARD_NERP_DATABASE": database,
                              "WIZARD_NERP_SCHEMA": "nerp_views", "WIZARD_NERP_USER": "wizard_nerp_writer",
                              "WIZARD_NERP_PASSWORD": password, "WIZARD_NERP_SSLMODE": "prefer"})
    assert settings is not None
    yield NerpQuery(settings), admin
    for statement in ["DROP SCHEMA nerp_views CASCADE", "DROP SCHEMA nerp_raw CASCADE", "DROP SCHEMA nerp_other CASCADE",
                      "DROP OWNED BY wizard_nerp_writer", "DROP ROLE wizard_nerp_writer"]:
        admin.run(statement)
    admin.close()


def test_the_views_are_listed_and_read_though_their_tables_sit_elsewhere(nerp):
    query, _ = nerp
    assert [(v["name"], v["kind"], v["columns"]) for v in query.views(fresh=True)] == [
        ("v_spend", "v", 3), ("v_spend_daily", "m", 2)], "views and materialized views; never the table beside them"
    assert [c["name"] for c in query.columns("v_spend")] == ["market", "day", "amount"]
    result = query.run("""
        WITH daily AS (SELECT market, day, sum(amount) AS amount FROM v_spend GROUP BY 1, 2)
        SELECT market, sum(amount) AS amount, count(*) AS days FROM daily GROUP BY 1 ORDER BY 1""")
    assert result.rows == [["EG", 150, 2], ["SA", 400, 1]]
    assert query.run("SELECT market FROM v_spend GROUP BY 1 ORDER BY 1").rows == [["EG"], ["SA"]], \
        "unqualified v_spend is NERP's, not nerp_other's"
    assert query.run("SELECT sum(amount) FROM nerp_views.v_spend_daily").rows == [[550]]


@pytest.mark.parametrize(("sql", "code"), [
    ("SELECT * FROM nerp_raw.postings", "not_a_nerp_view"),
    ("SELECT * FROM postings", "not_a_nerp_view"),
    ("SELECT * FROM nerp_views.scratch", "not_a_nerp_view"),
    ("SELECT * FROM nerp_other.v_spend", "not_a_nerp_view"),
    ("SELECT relname FROM pg_class", "not_a_nerp_view"),
    ("SELECT query_to_xml('SELECT cost_centre FROM nerp_raw.postings', true, true, '')", "not_a_nerp_view"),
    ("DELETE FROM v_spend", "not_a_query"),
    ("SELECT 1) AS a; DELETE FROM nerp_raw.postings; SELECT * FROM (SELECT 1", "not_a_query"),
])
def test_tables_other_schemas_the_catalog_and_writes_are_refused(nerp, sql, code):
    query, admin = nerp
    with pytest.raises(SourceError) as refused:
        query.run(sql)
    assert refused.value.code in (code, "query_not_checked"), refused.value.message
    assert admin.run("SELECT count(*) FROM nerp_raw.postings")[0][0] == 3, "nothing changed"


def test_only_the_listed_views_are_read(nerp):
    query, _ = nerp
    limited = NerpQuery(settings_from({"WIZARD_NERP_HOST": f"{query.settings.host}:{query.settings.port}",
                                       "WIZARD_NERP_DATABASE": query.settings.database, "WIZARD_NERP_SCHEMA": "nerp_views",
                                       "WIZARD_NERP_USER": query.settings.user, "WIZARD_NERP_PASSWORD": query.settings.password,
                                       "WIZARD_NERP_VIEWS": "v_spend_daily"}))  # type: ignore[arg-type]
    assert [v["name"] for v in limited.views(fresh=True)] == ["v_spend_daily"]
    assert limited.run("SELECT sum(amount) FROM v_spend_daily").rows == [[550]]
    with pytest.raises(SourceError) as refused:
        limited.run("SELECT * FROM v_spend")
    assert refused.value.code == "not_a_nerp_view"
    assert limited.columns("v_spend") == [], "a view not listed is not described either"

