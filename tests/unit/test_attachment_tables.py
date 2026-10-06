"""Attached spreadsheets and CSV files as full tables: typed extraction, the query engine, the tool's evidence, and the
upload path that saves the tables."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, MemoryRecorder, login, make_settings
from tests.office_files import xlsx

from wizard_api.app import create_app
from wizard_connectors import attachment_tables
from wizard_connectors.tools import ToolContext
from wizard_documents.convert import Converter
from wizard_documents.tables import write

CSV = ("Market,Week,Units,Share %,Note\n" + "\n".join(
    f"{m},{w},\"{u:,}\",{s},{'n/a' if (m, w) == ('AE', '2026-09-28') else ''}"
    for m, w, u, s in [("EG", "2026-09-21", 1200, 0.31), ("EG", "2026-09-28", 1350, 0.32), ("SA", "2026-09-21", 4500, 0.28),
                       ("SA", "2026-09-28", 4700, 0.29), ("AE", "2026-09-21", 800, 0.25), ("AE", "2026-09-28", 950, 0.26)]))


def converted(tmp_path: Path, name: str, data: bytes | None = None, maker=None) -> Path:
    folder = tmp_path / "att" / "converted"
    source = tmp_path / name
    if maker:
        maker(source)
    else:
        source.write_bytes(data or b"")
    with Converter("never", tables=True) as converter:
        result = converter.convert(source, folder / "assets", folder / "attachments")
    write(result.tables, folder)
    return tmp_path / "att"


def test_csv_becomes_a_typed_table(tmp_path):
    folder = converted(tmp_path, "weekly.csv", CSV.encode())
    [entry] = attachment_tables.index(folder)
    types = {c["key"]: c["type"] for c in entry["columns"]}
    assert types == {"market": "string", "week": "date", "units": "number", "share": "number", "note": "string"}
    rows = attachment_tables.load(folder, entry)
    assert rows[0] == {"market": "EG", "week": "2026-09-21", "units": 1200.0, "share": 0.31, "note": None}


def test_xlsx_keeps_every_row_not_just_the_profile(tmp_path):
    folder = converted(tmp_path, "book.xlsx", maker=lambda p: xlsx(p, data_rows=500))
    tables = {t["sheet"]: t for t in attachment_tables.index(folder)}
    assert tables["Sales"]["rows"] == 500 and tables["Markets"]["rows"] == 2
    rows = attachment_tables.load(folder, tables["Sales"])
    total = attachment_tables.query(tables["Sales"], rows, [], [], [{"column": "units", "aggregate": "sum"}], [], 10)
    assert total["rows"] == [[sum(n * 10 for n in range(2, 502))]], "the total covers all 500 rows"


def test_query_filters_groups_sorts_and_warns(tmp_path):
    folder = converted(tmp_path, "weekly.csv", CSV.encode())
    [entry] = attachment_tables.index(folder)
    rows = attachment_tables.load(folder, entry)
    result = attachment_tables.query(entry, rows, [{"column": "week", "from": "2026-09-28", "values": None, "to": None}],
                                     ["market"], [{"column": "units", "aggregate": "sum"}, {"column": "share", "aggregate": "sum"},
                                                  {"column": "note", "aggregate": "count"}],
                                     [{"field": "sum_units", "direction": "desc"}], 2)
    assert [c["key"] for c in result["columns"]] == ["market", "sum_units", "sum_share", "count_note"]
    assert result["rows"] == [["SA", 4700, 0.29, 1], ["EG", 1350, 0.32, 1]] and result["total_rows"] == 3 and result["truncated"]
    assert any("share looks like a rate" in w for w in result["warnings"])
    eg = attachment_tables.query(entry, rows, [{"column": "market", "values": ["eg"], "from": None, "to": None}], [], [], [], 10)
    assert eg["total_rows"] == 2 and eg["rows"][0][0] == "EG"
    with pytest.raises(attachment_tables.TableError, match="not a number column"):
        attachment_tables.query(entry, rows, [], [], [{"column": "market", "aggregate": "sum"}], [], 10)
    with pytest.raises(attachment_tables.TableError, match="No column 'region'"):
        attachment_tables.query(entry, rows, [], ["region"], [], [], 10)


def test_tool_records_user_provided_evidence(tmp_path, registry, identities, services):
    folder = converted(tmp_path, "book.xlsx", maker=lambda p: xlsx(p, data_rows=80))
    recorder = MemoryRecorder()
    recorder.files = {"F1": ({"id": "att_1", "label": "F1", "filename": "book.xlsx", "kind": "spreadsheet", "status": "ok",
                              "folder": str(folder), "modified": "2026-10-06"}, "## Sheet: Sales\n...")}
    ctx = ToolContext(identity=identities.get("u-ceo"), run_id="r", recorder=recorder, services=services)
    several = registry.execute("wizard_query_attachment", {"file": "F1", "measures": [{"column": "units", "aggregate": "sum"}]}, ctx)
    assert several.error_code == "choose_sheet" and "Sales (80 rows)" in several.error_message
    outcome = registry.execute("wizard_query_attachment", {
        "file": "F1", "sheet": "sales", "group_by": ["market"], "measures": [{"column": "revenue", "aggregate": "sum"}],
        "filters": [{"column": "units", "from": "100"}]}, ctx)
    assert outcome.ok, outcome.error_message
    assert outcome.data["data_mode"] == "USER_PROVIDED" and outcome.data["sheet"] == "Sales"
    evidence = recorder.get_evidence("E1")
    assert evidence["system"] == "attachment" and evidence["data_mode"] == "USER_PROVIDED"
    assert evidence["report_name"] == "book.xlsx › Sales" and evidence["columns"][1]["key"] == "sum_revenue"
    read = registry.execute("wizard_read_attachment", {"file": "F1"}, ctx).data
    assert {t["sheet"] for t in read["tables"]} == {"Markets", "Sales"} and "wizard_query_attachment" in read["how_to_total"]


def test_uploads_save_full_tables(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        login(client, "u-ceo")
        added = client.post("/api/v1/attachments", content=CSV.encode(),
                            headers={**HEADERS, "Content-Type": "application/octet-stream", "X-File-Name": "weekly.csv"}).json()
        row = client.app.state.store.attachment("u-ceo", added["attachment"]["id"])
        index = json.loads((Path(row["folder"]) / "converted" / "tables.json").read_text(encoding="utf-8"))
        assert index[0]["rows"] == 6 and [c["key"] for c in index[0]["columns"]][:3] == ["market", "week", "units"]
