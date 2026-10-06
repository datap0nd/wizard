"""PostgreSQL materialized-view export against a fake database: settings, catalog, lineage, pg_cron, the light profile
(sampling, ranges, value lists, personal columns), output files, and that only SELECTs are ever sent."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from wizard_documents.common import ConversionError
from wizard_documents.postgres import check, export, settings_from

DEFINITION = (" SELECT s.market, s.fiscal_week, sum(s.units) AS sell_out, s.sales_rep, max(s.loaded) AS updated_at\n"
              "   FROM bi_staging.asap_import s\n  GROUP BY s.market, s.fiscal_week, s.sales_rep;")


class FakeDatabase:
    """Answers the exporter's queries by what they ask for; records every statement."""

    def __init__(self, locked: bool = False):
        self.sql: list[str] = []
        self.locked = locked

    def __call__(self, settings: Any, database: str | None = None) -> FakeDatabase:
        return self

    def close(self) -> None:
        pass

    def rows(self, sql: str) -> list[dict[str, Any]]:
        self.sql.append(sql)
        if "current_setting('server_version')" in sql:
            return [{"user_name": "wizard_reader", "database": "meto_db", "version": "16.4", "read_only": "on",
                     "commit_timestamps": "on"}]
        if "pg_roles" in sql:
            return [{"superuser": False, "createrole": False, "createdb": False}]
        if "pg_database" in sql:
            return [{"datname": "meto_db"}]
        if "to_regclass('cron.job')" in sql:
            return [{"present": True}]
        if "FROM cron.job" in sql:
            return [{"jobid": 7, "schedule": "0 2 * * *", "database": "meto_db", "active": True,
                     "command": "REFRESH MATERIALIZED VIEW CONCURRENTLY bi_reporting.mv_sellout_weekly"}]
        if "pg_get_viewdef" in sql:
            return [{"oid": 1, "schema": "bi_reporting", "name": "mv_sellout_weekly", "owner": "metronome",
                     "comment": "Weekly sell-out by market", "populated": True, "estimated_rows": 300_000,
                     "bytes": 52_428_800, "definition": DEFINITION, "readable": True},
                    {"oid": 2, "schema": "bi_reporting", "name": "mv_busy", "owner": "metronome", "comment": None,
                     "populated": True, "estimated_rows": 1_000, "bytes": 8192, "definition": "SELECT 1 AS one;",
                     "readable": True}]
        if "pg_attribute" in sql:
            names = [("market", "text"), ("fiscal_week", "integer"), ("sell_out", "numeric"), ("sales_rep", "text"),
                     ("updated_at", "timestamp with time zone")]
            return [*[{"oid": 1, "position": i, "name": n, "type": t, "not_null": i == 1, "comment": None}
                      for i, (n, t) in enumerate(names, start=1)],
                    {"oid": 2, "position": 1, "name": "one", "type": "integer", "not_null": False, "comment": None}]
        if "pg_index" in sql:
            return [{"oid": 1, "definition": "CREATE UNIQUE INDEX mv_sellout_key ON bi_reporting.mv_sellout_weekly "
                                             "USING btree (market, fiscal_week, sales_rep)"}]
        if "pg_rewrite" in sql:
            return [{"reader": 1, "reader_kind": "m", "reader_schema": "bi_reporting", "reader_name": "mv_sellout_weekly",
                     "source": 50, "source_kind": "r", "source_schema": "bi_staging", "source_name": "asap_import"},
                    {"reader": 60, "reader_kind": "v", "reader_schema": "bi_reporting", "reader_name": "v_dashboard",
                     "source": 1, "source_kind": "m", "source_schema": "bi_reporting", "source_name": "mv_sellout_weekly"}]
        if "pg_stat_all_tables" in sql:
            return [{"oid": 1, "analyzed": datetime(2026, 10, 5, 2, 5, tzinfo=UTC)}]
        if '"mv_busy"' in sql:
            raise RuntimeError({"S": "ERROR", "C": "55P03", "M": "canceling statement due to lock timeout"})
        if sql.startswith("SELECT count(*) AS n FROM"):
            return [{"n": 300_000}]
        if "pg_xact_commit_timestamp" in sql:
            return [{"t": datetime(2026, 10, 5, 2, 1, tzinfo=UTC)}]
        if sql.startswith("SELECT count(*) AS total"):
            return [{"total": 200_000, "n0": 200_000, "d0": 3, "n1": 200_000, "d1": 40, "n2": 190_000, "d2": 150_000,
                     "n3": 200_000, "d3": 4, "n4": 200_000, "d4": 30}]
        if "AS lo0" in sql:
            return [{"lo0": "202601", "hi0": "202640", "lo1": "2026-01-03 01:00:00+00", "hi1": "2026-10-05 02:00:00+00"}]
        if "AS v, count(*) AS n" in sql and '"market"' in sql:
            return [{"v": "SA", "n": 9}, {"v": "EG", "n": 5}, {"v": "AE", "n": 2}]
        raise AssertionError(f"unexpected query: {sql}")


def settings() -> Any:
    return settings_from(None, {"PGHOST": "db.corp", "PGUSER": "wizard_reader", "PGPASSWORD": "secret", "PGDATABASE": "meto_db"})


def test_settings_come_from_env_file_first_then_pg_variables(tmp_path):
    env = tmp_path / ".env"
    env.write_text("WIZARD_PG_HOST=pg.internal\nWIZARD_PG_USER=reader\nWIZARD_PG_PASSWORD='p w'\nWIZARD_PG_SSLMODE=require\n",
                   encoding="utf-8")
    chosen = settings_from(env, {"PGHOST": "other", "PGUSER": "writer"})
    assert (chosen.host, chosen.user, chosen.password, chosen.port, chosen.database, chosen.sslmode) == \
        ("pg.internal", "reader", "p w", 5432, "postgres", "require")
    assert "secret" not in settings().describe() and "p w" not in chosen.describe(), "the password is never shown"
    assert settings().source == "environment (PG*)"
    with pytest.raises(ConversionError, match="no PostgreSQL connection settings"):
        settings_from(None, {})
    with pytest.raises(ConversionError, match="sslmode"):
        settings_from(None, {"PGHOST": "h", "PGUSER": "u", "PGSSLMODE": "sometimes"})


def test_export_documents_materialized_views_read_only(tmp_path):
    database = FakeDatabase()
    summary = export(tmp_path, settings(), connector=database)
    assert summary["databases"] == {"meto_db": {"materialized_views": 2, "profiled": 1, "notes": 3}}
    assert all(sql.startswith("SELECT") for sql in database.sql), "nothing but SELECT is ever sent"
    assert any("TABLESAMPLE SYSTEM (66.666667)" in sql for sql in database.sql), "300k rows are profiled on a sample"
    page = (tmp_path / "inbox" / "postgres" / "meto_db" / "bi_reporting.mv_sellout_weekly.md").read_text(encoding="utf-8")
    assert page.startswith("---\nsource: postgresql\ndatabase: meto_db\nobject: bi_reporting.mv_sellout_weekly")
    assert "- Rows: 300,000; size 50.0 MB; populated: yes" in page
    assert "- Freshness: rows last written 2026-10-05 02:01 UTC (commit timestamps)" in page
    assert 'pg_cron job 7: "0 2 * * *": REFRESH MATERIALIZED VIEW CONCURRENTLY bi_reporting.mv_sellout_weekly' in page
    assert "## Reads from\n\n- bi_staging.asap_import (table)" in page
    assert "## Read by\n\n- bi_reporting.v_dashboard (view)" in page
    assert "| 1 | market | text not null | 0% | 3 | SA, EG, AE |  |" in page
    assert "| 2 | fiscal_week | integer | 0% | 40 | 202601 to 202640 |  |" in page, "periods kept as numbers get a range"
    assert "| 3 | sell_out | numeric | 5% | 150,000 |  |  |" in page, "business figures get no range or values"
    assert "| 4 | sales_rep | text | 0% | 4 |  |  |" in page, "people's names are not listed"
    assert "| 5 | updated_at | timestamp with time zone | 0% | 30 | 2026-01-03 01:00:00+00 to 2026-10-05 02:00:00+00 |" in page
    assert "```sql\nSELECT s.market, s.fiscal_week, sum(s.units) AS sell_out" in page
    busy = (tmp_path / "inbox" / "postgres" / "meto_db" / "bi_reporting.mv_busy.md").read_text(encoding="utf-8")
    assert "Rows: 1,000 (planner estimate)" in busy and "canceling statement due to lock timeout (SQLSTATE 55P03)" in busy
    overview = (tmp_path / "inbox" / "postgres" / "meto_db" / "00-overview.md").read_text(encoding="utf-8")
    assert "| bi_reporting.mv_sellout_weekly | 300,000 | 50.0 MB |" in overview and "pg_cron jobs visible: yes" in overview
    machine = json.loads((tmp_path / "inbox" / "_postgres" / "meto_db.json").read_text(encoding="utf-8"))
    assert [v["name"] for v in machine["materialized_views"]] == ["mv_sellout_weekly", "mv_busy"]
    assert "secret" not in json.dumps(machine) and "secret" not in page


def test_structure_only_never_reads_the_data(tmp_path):
    database = FakeDatabase()
    export(tmp_path, settings(), profiled=False, connector=database)
    assert not any("FROM \"bi_reporting\"" in sql for sql in database.sql)
    page = (tmp_path / "inbox" / "postgres" / "meto_db" / "bi_reporting.mv_sellout_weekly.md").read_text(encoding="utf-8")
    assert "about 300,000 (planner estimate)" in page and "(read-only catalog)" in page


def test_check_reports_the_read_only_session():
    lines = check(settings(), connector=FakeDatabase())
    assert lines[0] == "PASS  connected: wizard_reader@db.corp:5432/meto_db (sslmode prefer, from environment (PG*))"
    assert "PASS  session is read-only (transaction_read_only on)" in lines
    assert "INFO  databases this account can connect to: meto_db" in lines
