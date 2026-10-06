"""The PostgreSQL export against a real server (CI runs a PostgreSQL service; elsewhere this is BLOCKED): catalog
queries, lineage, the light profile, and that the session refuses writes even for an account allowed to write."""
from __future__ import annotations

import os
import secrets

import pytest

from wizard_documents.common import ConversionError
from wizard_documents.postgres import Pg8000Session, PgSettings, check, export

HOST = os.environ.get("WIZARD_TEST_PG_HOST")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not HOST, reason="BLOCKED: no PostgreSQL test server (WIZARD_TEST_PG_HOST, "
                                                  "WIZARD_TEST_PG_USER, WIZARD_TEST_PG_PASSWORD)")]


@pytest.fixture
def server():
    pg8000 = pytest.importorskip("pg8000.native", reason="BLOCKED: pg8000 is not installed")
    admin = pg8000.Connection(os.environ.get("WIZARD_TEST_PG_USER", "postgres"), host=HOST,
                              port=int(os.environ.get("WIZARD_TEST_PG_PORT", "5432")),
                              password=os.environ.get("WIZARD_TEST_PG_PASSWORD"), ssl_context=False)
    password = secrets.token_hex(12)
    for statement in [
        "DROP SCHEMA IF EXISTS docs_staging CASCADE", "DROP SCHEMA IF EXISTS docs_reporting CASCADE",
        "DROP ROLE IF EXISTS wizard_docs_reader",
        "CREATE SCHEMA docs_staging", "CREATE SCHEMA docs_reporting",
        "CREATE TABLE docs_staging.asap_import (market text, fiscal_week integer, units integer, sales_rep text)",
        "INSERT INTO docs_staging.asap_import SELECT (ARRAY['EG','SA','AE'])[1 + i % 3], 202601 + i % 40, i, 'Rep ' || i % 4 "
        "FROM generate_series(1, 500) AS i",
        "CREATE MATERIALIZED VIEW docs_reporting.mv_sellout AS SELECT market, fiscal_week, sum(units) AS sell_out, "
        "sales_rep FROM docs_staging.asap_import GROUP BY 1, 2, 4",
        "COMMENT ON MATERIALIZED VIEW docs_reporting.mv_sellout IS 'Weekly sell-out by market'",
        "CREATE UNIQUE INDEX mv_sellout_key ON docs_reporting.mv_sellout (market, fiscal_week, sales_rep)",
        "CREATE VIEW docs_reporting.v_dashboard AS SELECT market, sum(sell_out) AS total FROM docs_reporting.mv_sellout GROUP BY 1",
        f"CREATE ROLE wizard_docs_reader LOGIN PASSWORD '{password}'",
        "GRANT USAGE ON SCHEMA docs_staging, docs_reporting TO wizard_docs_reader",
        "GRANT SELECT ON ALL TABLES IN SCHEMA docs_staging, docs_reporting TO wizard_docs_reader",
    ]:
        admin.run(statement)
    database = admin.run("SELECT current_database()")[0][0]
    yield PgSettings(HOST, int(os.environ.get("WIZARD_TEST_PG_PORT", "5432")), database, "wizard_docs_reader", password,
                     "prefer", "test")
    for statement in ["DROP SCHEMA docs_reporting CASCADE", "DROP SCHEMA docs_staging CASCADE",
                      "DROP OWNED BY wizard_docs_reader", "DROP ROLE wizard_docs_reader"]:
        admin.run(statement)
    admin.close()


def test_real_server_export(server, tmp_path):
    summary = export(tmp_path, server, only=[server.database], schemas=["docs_reporting", "docs_staging"])
    assert summary["databases"][server.database]["materialized_views"] == 1
    page = (tmp_path / "inbox" / "postgres" / server.database / "docs_reporting.mv_sellout.md").read_text(encoding="utf-8")
    assert "- Comment in the database: Weekly sell-out by market" in page
    assert "## Reads from\n\n- docs_staging.asap_import (table)" in page
    assert "## Read by\n\n- docs_reporting.v_dashboard (view)" in page
    assert "CREATE UNIQUE INDEX mv_sellout_key" in page
    assert "| market | text | 0% | 3 | " in page and "SA" in page and "EG" in page
    assert "| fiscal_week | integer | 0% | 40 | 202601 to 202640 |" in page
    assert "Rep 1" not in page, "people's names are not listed"
    assert "Rows: " in page and "(planner estimate)" not in page.split("- Rows:")[1].splitlines()[0]
    assert "FROM docs_staging.asap_import" in page


def test_real_server_session_is_read_only(server):
    lines = check(server)
    assert any(line.startswith("PASS  session is read-only") for line in lines)
    session = Pg8000Session(server)
    try:
        # Every account may create temporary tables; only the read-only session stops it.
        with pytest.raises(Exception, match="read-only transaction"):
            session.rows("CREATE TEMP TABLE should_fail (x int)")
    finally:
        session.close()
    with pytest.raises(ConversionError, match="could not connect"):
        Pg8000Session(PgSettings(server.host, server.port, server.database, server.user, "wrong-password", "prefer", "test"))
