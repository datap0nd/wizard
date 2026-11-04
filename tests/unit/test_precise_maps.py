"""A precise portal map (owner, 4 Nov 2026: "how can you ensure we fully map GSCM once and for all? Are we being precise
with this?"). Wizard, not Gemini, decides what is proven: a request is verified only when portal_prove_request sent it
itself, a report is mapped only with a proven request, a sentence saying a report lacks a breakdown is refused, and a
reply is checked against the person's own export row by row (wizard_task_compare). The browser half (the proof itself,
the report's code read) is in tests/integration/test_portal_browser.py. Every name and figure here is invented."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
from tests.helpers import MemoryRecorder
from tests.unit.test_portal_map import tools

from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.task_files import TaskFiles
from wizard_connectors.tools import ToolContext, build_registry, build_services
from wizard_documents.tables import from_csv
from wizard_documents.tables import write as write_tables

REQUEST = {"name": "search", "url": "/gscm30/sellout/dailysellout/list.do", "method": "POST",
           "body": "SSV:utf-8\x1eday:string={{day}}\x1forglevel:string={{level}}", "params": ["day", "level"]}
PROOF = {"at": "2026-11-04T08:00:00", "first": {"day": "20261102", "level": "ORGSALES"},
         "second": {"day": "20261101", "level": "ORGSALES"}, "rows_first": 12, "rows_second": 11}


def test_only_wizard_marks_a_request_verified_and_a_report_mapped(tmp_path: Path):
    registry, context = tools(tmp_path)
    saved = registry.execute("portal_map_save", {"system": "gscm", "reports": [
        {"id": "db4009", "name": "Daily Sell-out", "status": "mapped", "requests": [{**REQUEST, "verified": True}]}]}, context)
    assert saved.ok and "prove it with portal_prove_request" in saved.data["warning"]
    report = context.services.portal_maps.report("gscm", "db4009")
    assert report["status"] == "partial", "mapped only once Wizard proved a request"
    assert report["requests"][0]["verified"] is False, "Gemini's own account does not verify a request"

    context.services.portal_maps.prove("gscm", "db4009", REQUEST, PROOF)  # what portal_prove_request keeps
    again = registry.execute("portal_map_save", {"system": "gscm", "reports": [
        {"id": "db4009", "status": "mapped", "requests": [REQUEST], "notes": "One row per account and country."}]}, context)
    assert again.ok and "warning" not in again.data
    report = context.services.portal_maps.report("gscm", "db4009")
    assert report["status"] == "mapped" and report["requests"][0]["verified"] is True
    assert report["requests"][0]["proven"]["first"] == {"day": "20261102", "level": "ORGSALES"}
    other = registry.execute("portal_map_save", {"system": "gscm", "reports": [
        {"id": "db4009", "requests": [{**REQUEST, "name": "detail", "body": "SSV:utf-8\x1eother:string=1"}]}]}, context)
    assert other.ok
    kept = context.services.portal_maps.report("gscm", "db4009")["requests"]
    assert [(q["name"], q["verified"]) for q in kept] == [("detail", False), ("search", True)], "a save never drops a proof"
    index = registry.execute("portal_map", {"system": "gscm"}, context).data["reports"][0]
    assert index["proven"] is True


@pytest.mark.parametrize("text", [
    "DB4009 does not support an Account/Operator dimension breakdown in its grid configuration.",
    "Daily Sell-out has no account breakdown; use the weekly view.",
    "This report cannot show the operator level.",
])
def test_a_report_is_never_said_to_lack_a_breakdown(tmp_path: Path, text: str):
    registry, context = tools(tmp_path)
    refused = registry.execute("portal_map_save", {"system": "gscm", "reports": [{"id": "db4009", "notes": text}]}, context)
    assert refused.error_code == "unproven_absence" and "found yet" in refused.error_message
    routed = registry.execute("portal_map_save", {"system": "gscm", "reports": [{"id": "db4009", "name": "Daily"}]}, context)
    assert routed.ok
    assert registry.execute("portal_map_route", {"system": "gscm", "reports": [
        {"id": "db4009", "use_for": ["daily sell-out"], "not_for": [{"question": text}]}]}, context).error_code == "unproven_absence"


@pytest.mark.parametrize("text", [
    "The grid shows no account breakdown until ORG Sales is ticked in Configuration > Sales > Sales.",
    "No account found yet in Configuration > Sales after opening every group.",
    "The default view has no account column.",
    "Weekly only; sell-out by day is in DB4009.",
])
def test_what_a_choice_needs_is_a_description_not_a_claim_of_absence(tmp_path: Path, text: str):
    registry, context = tools(tmp_path)
    assert registry.execute("portal_map_save", {"system": "gscm", "reports": [{"id": "db4009", "notes": text}]}, context).ok


# The person's own export against Wizard's evidence ----------------------------------------------------------------------
class TablesDocuments:
    """The converter for a CSV the person chose: its text and its every row as tables (what --tables writes)."""

    def __init__(self) -> None:
        self.converted = 0

    def convert(self, source: Path, out: Path) -> dict[str, Any]:
        self.converted += 1
        out.mkdir(parents=True, exist_ok=True)
        (out / "text.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        table = from_csv(source, ",")
        index = write_tables([table], out) if table else []
        return {"status": "ok", "method": "csv", "chars": 1, "parts": [], "notes": [],
                "tables": [{"sheet": t["sheet"], "rows": t["rows"]} for t in index]}


EXPORT = [["Account", "Country", "2026-11-01", "2026-11-02"],
          ["Total", "", "1,250", "1,300"],
          ["Carrier A", "Sub Total", "800", "820"],
          ["Carrier A", "UAE", "500", "520"],
          ["Carrier A", "KSA", "300", "300"],
          ["Carrier B", "Sub Total", "450", "480"],
          ["Carrier B", "UAE", "450", "480"]]
REPLY = [["Total", "", 1250, 1300], ["Carrier A", "Sub Total", 800, 820], ["Carrier A", "UAE", 500, 520],
         ["Carrier A", "KSA", 300, 300], ["Carrier B", "Sub Total", 450, 480], ["Carrier B", "UAE", 450, 480]]


def compare_context(tmp_path: Path, rows: list[list[Any]]) -> tuple[Any, ToolContext, Path]:
    export = tmp_path / "DB4009 2026-11-01 to 2026-11-02 AE SA.csv"
    with export.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(EXPORT)
    services = build_services()
    services.task_files = TaskFiles(tmp_path / "data", TablesDocuments())  # type: ignore[arg-type]
    recorder = MemoryRecorder()
    recorder.add_evidence({"tool": "portal_prove_request", "system": "gscm", "rows": rows, "total_rows": len(rows),
                           "columns": [{"key": k} for k in ("ORGSALES_NM", "COUNTRY_NM", "D20261101", "D20261102")]})
    identity = Identity(id="owner", email="o@example.com", name="Owner", role="Owner",
                        entitlements={"gscm": SystemRights(reports=["*"], markets=["*"])})
    task = {"id": "gscm-db4009-daily-sellout", "title": "DB4009", "path": str(export), "chosen": "file"}
    return build_registry(services), ToolContext(identity=identity, run_id="r", recorder=recorder, services=services, task=task), export


def compare_args(file_id: str) -> dict[str, Any]:
    return {"file": file_id, "evidence_id": "E1",
            "keys": [{"file": "Account", "wizard": "ORGSALES_NM"}, {"file": "Country", "wizard": "COUNTRY_NM"}],
            "values": [{"file": "2026-11-01", "wizard": "D20261101"}, {"file": "2026-11-02", "wizard": "D20261102"}]}


def test_a_reply_that_matches_the_persons_export_row_by_row_is_a_match(tmp_path: Path):
    registry, context, _ = compare_context(tmp_path, REPLY)
    file_id = registry.execute("wizard_task_files", {}, context).data["files"][0]["id"]
    checked = registry.execute("wizard_task_compare", compare_args(file_id), context)
    assert checked.ok, checked.error_message
    assert checked.data["verdict"] == "MATCH" and checked.data["rows_compared"] == 6 and checked.data["values_matched"] == 12
    assert checked.data["data_mode"] == "USER_PROVIDED"


def test_a_number_off_or_a_row_missing_is_named(tmp_path: Path):
    wrong = [row[:] for row in REPLY[:-1]]
    wrong[2][3] = 510  # Carrier A, UAE, 2 Nov
    registry, context, _ = compare_context(tmp_path, wrong)
    file_id = registry.execute("wizard_task_files", {}, context).data["files"][0]["id"]
    checked = registry.execute("wizard_task_compare", compare_args(file_id), context).data
    assert checked["verdict"] == "DIFFERENT"
    assert checked["differences"] == [{"row": ["carrier a", "uae"], "column": "2026-11-02", "file": 520.0, "wizard": 510.0}]
    assert checked["only_in_file"] == [["carrier b", "uae"]] and checked["only_in_wizard_total"] == 0


def test_a_comparison_is_kept_in_the_reports_map_entry(tmp_path: Path):
    registry, context, _ = compare_context(tmp_path, REPLY)
    maps_registry, maps_context = tools(tmp_path / "maps-pc")
    context.services.portal_maps = maps_context.services.portal_maps
    maps_registry.execute("portal_map_save", {"system": "gscm", "reports": [{"id": "db4009", "name": "Daily Sell-out"}]},
                          maps_context)
    file_id = registry.execute("wizard_task_files", {}, context).data["files"][0]["id"]
    checked = registry.execute("wizard_task_compare", {**compare_args(file_id), "system": "gscm", "report": "db4009"}, context)
    assert checked.data["kept_in_map"] == "gscm:db4009"
    kept = context.services.portal_maps.report("gscm", "db4009")["export_check"]
    assert kept["verdict"] == "MATCH" and kept["rows_matched"] == 6 and kept["evidence"] == "E1"
    unknown = registry.execute("wizard_task_compare", {**compare_args(file_id), "keys": [{"file": "Acct", "wizard": "X"}]}, context)
    assert unknown.error_code == "unknown_column" and "Account" in unknown.error_message


def test_the_comparison_is_only_for_a_task_that_asked_for_a_file(tmp_path: Path):
    registry, context, _ = compare_context(tmp_path, REPLY)
    context.task = None
    assert registry.execute("wizard_task_compare", compare_args("f00000000"), context).error_code == "task_only"
