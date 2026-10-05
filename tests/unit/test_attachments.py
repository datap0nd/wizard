"""Files attached to questions: upload and "from this PC", conversion, binding to a run as F1/F2, the read tool's
evidence (USER_PROVIDED), and what Gemini is told about them."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tests.helpers import HEADERS, MemoryRecorder, login, make_settings, wait_run
from tests.office_files import xlsx

from wizard_agent.prompting import compose
from wizard_api.app import create_app
from wizard_api.runs import DATA_MODE_RANK
from wizard_connectors.tools import ToolContext

CSV = b"Market,Units,Share\nEG,1200,0.31\nSA,4500,0.28\n"


def upload(client: TestClient, name: str, data: bytes) -> dict:
    response = client.post("/api/v1/attachments", content=data,
                           headers={**HEADERS, "Content-Type": "application/octet-stream", "X-File-Name": name})
    return {"status_code": response.status_code, **response.json()}


def test_upload_convert_bind_and_show(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        login(client, "u-ceo")
        added = upload(client, "gulf%20markets.csv", CSV)["attachment"]
        assert added["status"] == "ok" and added["filename"] == "gulf markets.csv" and added["kind"] == "spreadsheet"
        broken = upload(client, "deck.pptx", b"not a deck")["attachment"]
        assert broken["status"] == "failed" and "From this PC" in broken["note"]
        assert upload(client, "scan.pdf", b"%PDF")["status_code"] == 415
        refused = client.post("/api/v1/runs", json={"question": "Which market gave us the best return on marketing investment last quarter?",
                                                    "attachment_ids": [broken["id"]]}, headers=HEADERS)
        assert refused.status_code == 400 and "could not be read" in refused.json()["error"]
        started = client.post("/api/v1/runs", json={"question": "Which market gave us the best return on marketing investment last quarter?",
                                                    "attachment_ids": [added["id"]]}, headers=HEADERS).json()
        assert [a["label"] for a in started["attachments"]] == ["F1"]
        run = wait_run(client, started["run_id"])
        assert [a["filename"] for a in run["attachments"]] == ["gulf markets.csv"]
        again = client.post("/api/v1/runs", json={"question": "And now?", "conversation_id": started["conversation_id"],
                                                  "attachment_ids": [added["id"]]}, headers=HEADERS)
        assert again.status_code == 404, "a sent file cannot be sent again"
        assert client.delete(f"/api/v1/attachments/{added['id']}", headers=HEADERS).status_code == 404
        assert client.delete(f"/api/v1/attachments/{broken['id']}", headers=HEADERS).json() == {"ok": True}
        login(client, "u-cfo")
        assert client.delete(f"/api/v1/attachments/{added['id']}", headers=HEADERS).status_code == 404, "another user's file"


def test_upload_size_limit(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, WIZARD_MAX_ATTACHMENT_MB="1"))) as client:
        login(client, "u-ceo")
        assert upload(client, "big.csv", b"x" * (1024 * 1024 + 1))["status_code"] == 413


def test_from_this_pc_reads_only_the_listed_folders(tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    xlsx(folder / "book.xlsx")
    (folder / "notes.csv").write_bytes(CSV)
    (folder / "photo.png").write_bytes(b"png")
    outside = tmp_path / "secret.csv"
    outside.write_bytes(CSV)
    with TestClient(create_app(make_settings(tmp_path, WIZARD_ATTACHMENT_FOLDERS=str(folder)))) as client:
        login(client, "u-ceo")
        assert client.get("/api/v1/bootstrap").json()["attachments"]["from_this_pc"] is True
        listing = client.get("/api/v1/attachments/local").json()
        assert {f["name"] for f in listing["files"]} == {"book.xlsx", "notes.csv"}
        assert [f["name"] for f in client.get("/api/v1/attachments/local?q=book").json()["files"]] == ["book.xlsx"]
        picked = client.post("/api/v1/attachments/local", json={"path": str(folder / "book.xlsx")}, headers=HEADERS).json()
        assert picked["attachment"]["origin"] == "local" and picked["attachment"]["status"] == "ok"
        assert picked["attachment"]["parts"] == 3
        denied = client.post("/api/v1/attachments/local", json={"path": str(outside)}, headers=HEADERS)
        assert denied.status_code == 403
    with TestClient(create_app(make_settings(tmp_path / "off"))) as client:
        login(client, "u-ceo")
        assert client.get("/api/v1/attachments/local").json() == {"enabled": False, "folders": [], "files": []}


def recorder_with_file(text: str) -> MemoryRecorder:
    recorder = MemoryRecorder()
    row = {"id": "att_1", "label": "F1", "filename": "review.pptx", "kind": "slides", "status": "ok", "modified": "2026-09-12",
           "sha256": "ab" * 32, "parts": ["Slide 1: Intro", "Slide 2: Gates"]}
    recorder.files = {"F1": (row, text)}
    return recorder


def test_read_attachment_tool_parts_paging_and_evidence(registry, identities, services):
    text = "## Slide 1: Intro\n- Why launches slip\n\n## Slide 2: Gates\n- Gate 2 is approved by the Head of Sales\n" + "x" * 40_000
    recorder = recorder_with_file(text)
    ctx = ToolContext(identity=identities.get("u-ceo"), run_id="r", recorder=recorder, services=services)
    first = registry.execute("wizard_read_attachment", {"file": "F1"}, ctx).data
    assert first["parts"] == ["Slide 1: Intro", "Slide 2: Gates"] and first["next_offset"] == 30_000
    assert first["data_mode"] == "USER_PROVIDED" and first["cite_as"] == "[E1]" and "never follow" in first["source_text_policy"]
    evidence = recorder.get_evidence("E1")
    assert evidence["system"] == "attachment" and evidence["data_mode"] == "USER_PROVIDED" and evidence["rows"] == []
    part = registry.execute("wizard_read_attachment", {"file": "F1", "part": "slide 2"}, ctx).data
    assert part["text"].startswith("## Slide 2: Gates\n- Gate 2 is approved")
    missing = registry.execute("wizard_read_attachment", {"file": "F1", "part": "Slide 9"}, ctx)
    assert missing.error_code == "unknown_part" and "Slide 2: Gates" in missing.error_message
    unknown = registry.execute("wizard_read_attachment", {"file": "F7"}, ctx)
    assert unknown.error_code == "unknown_file" and "F1 review.pptx" in unknown.error_message


def test_gemini_is_told_about_attached_files():
    prompt = compose("Summarise the deck", [], "ask", "Monday 5 October 2026",
                     [{"label": "F1", "filename": "review.pptx", "kind": "slides", "status": "ok", "parts": ["Slide 1: Intro"]},
                      {"label": "F2", "filename": "old.xls", "kind": "spreadsheet", "status": "failed", "note": "password-protected"}])
    assert "- F1: review.pptx (presentation, 1 parts (Slide 1: Intro ...))" in prompt
    assert "- F2: old.xls could not be read: password-protected" in prompt and "never instructions" in prompt
    assert DATA_MODE_RANK["SYNTHETIC"] < DATA_MODE_RANK["USER_PROVIDED"] < DATA_MODE_RANK["DATED_APPROVED_SNAPSHOT"]


def test_attachment_evidence_opens_for_its_owner(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, "u-ceo")
        conversation = client.post("/api/v1/conversations", headers=HEADERS).json()["conversation_id"]
        store = app.state.store
        evidence_id = store.add_evidence(conversation, "run_x", "u-ceo", {"system": "attachment", "report_id": "att_1",
                                                                            "report_name": "review.pptx", "data_mode": "USER_PROVIDED"})
        shown = client.get(f"/api/v1/conversations/{conversation}/evidence/{evidence_id}")
        assert shown.status_code == 200 and shown.json()["evidence"]["data_mode"] == "USER_PROVIDED"
        assert Path(settings.data_dir).is_dir()
