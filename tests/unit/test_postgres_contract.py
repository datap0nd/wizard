"""Drafting queryable report entries from the PostgreSQL export, and the parity sample that runs Wizard's own query."""
from __future__ import annotations

import json
from typing import Any

import pytest
from tests.unit.test_postgres_docs import FakeDatabase, settings

from wizard_connectors.content import errors, validate_content
from wizard_connectors.postgres_source import PostgresSource
from wizard_documents.common import ConversionError
from wizard_documents.postgres import export
from wizard_documents.postgres_contract import draft, sample


def exported(tmp_path):
    export(tmp_path, settings(), connector=FakeDatabase())
    return tmp_path


def test_draft_from_the_export_is_valid_and_marks_its_guesses(tmp_path):
    content = exported(tmp_path)
    lines = draft(content, ["bi_reporting.mv_sellout_weekly"])
    assert lines[0].startswith("added  postgresql-bi-reporting-mv-sellout-weekly: 4 dimension(s), 1 measure(s)")
    contract = json.loads((content / "contracts" / "sources" / "postgresql.json").read_text(encoding="utf-8"))
    report = contract["reports"][0]
    dims = {d["key"]: d for d in report["dimensions"]}
    assert dims["market"]["role"] == "market" and dims["market"]["values_hint"] == ["SA", "EG", "AE"]
    assert dims["fiscal_week"]["role"] == "period" and "role" not in dims["updated_at"], "one period: the week"
    assert report["measures"] == [{"key": "sell_out", "label": "Sell out", "type": "number", "aggregation": "sum"}]
    assert report["grain"] == ["market", "fiscal_week", "sales_rep"]
    assert report["relation"] == {"database": "meto_db", "schema": "bi_reporting", "name": "mv_sellout_weekly"}
    assert report["refresh"].startswith("pg_cron job 7") and any(c.startswith("UNCERTAIN") for c in report["caveats"])
    assert contract["system"]["connector"] == {"status": "ROWS_UNVERIFIED", "data_mode": "LIVE_UNVERIFIED",
                                               "transport": "postgresql", "live_interface": "PostgreSQL read-only (pg8000)"}
    problems = validate_content(content)
    assert not errors(problems), errors(problems)
    assert draft(content, ["bi_reporting.mv_sellout_weekly"])[0].startswith("kept"), "reviewed entries are not overwritten"
    with pytest.raises(ConversionError, match="not in the export"):
        draft(content, ["bi_reporting.nope"])


class SampleSession:
    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        if "pg_attribute" in sql:
            return [{"name": "market", "type": "text"}, {"name": "fiscal_week", "type": "integer"},
                    {"name": "sell_out", "type": "numeric"}]
        if "track_commit_timestamp" in sql:
            return [{"tracked": False}]
        if "DISTINCT" in sql:
            return [{"v": "eg"}]
        return [{"c0": "EG", "c1": 1500, "__n": 2, "__total": 1}]

    def close(self) -> None:
        pass


def test_sample_runs_wizards_query_for_a_parity_check(tmp_path):
    content = exported(tmp_path)
    draft(content, ["bi_reporting.mv_sellout_weekly"])
    live = PostgresSource(settings(), connect=lambda s, d: SampleSession())
    text = sample(content, settings(), "postgresql-bi-reporting-mv-sellout-weekly", ["market=EG"], ["market"],
                  ["sell_out"], 20, source=live)
    assert "LIVE_UNVERIFIED: live from PostgreSQL, not yet checked" in text and "| EG | 1500 |" in text
    assert "record the parity" in text
    with pytest.raises(ConversionError, match="must look like"):
        sample(content, settings(), "postgresql-bi-reporting-mv-sellout-weekly", ["market"], None, None, 5, source=live)
