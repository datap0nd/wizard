"""A visual's export (PowerPoint slide, Excel workbook, picture), saved in Downloads by Wizard on the person's own PC."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from tests.helpers import HEADERS, login, make_settings

from wizard_api import attachments as attachments_module
from wizard_api.app import create_app
from wizard_api.exports import clean_name


def office(main: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(main, "<x/>")
    return out.getvalue()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def save(client: TestClient, name: str, data: bytes, headers: dict[str, str] | None = None):
    return client.post("/api/v1/exports", content=data, headers={**(HEADERS if headers is None else headers),
                                                                  "Content-Type": "application/octet-stream",
                                                                  "X-File-Name": name})


def test_an_export_is_saved_in_downloads_never_over_a_file_and_opens_there(tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    monkeypatch.setattr(attachments_module, "downloads_folder", lambda: downloads)
    opened: list[str] = []
    monkeypatch.setattr("wizard_api.exports.os.startfile", opened.append, raising=False)
    with TestClient(create_app(make_settings(tmp_path))) as client:
        login(client, "u-ceo")
        slide = save(client, "Q3 spend by market.pptx", office("ppt/presentation.xml"))
        assert slide.status_code == 200, slide.text
        saved = slide.json()["saved"]
        assert saved["filename"] == "Q3 spend by market.pptx" and saved["folder"] == str(downloads)
        again = save(client, "Q3 spend by market.pptx", office("ppt/presentation.xml")).json()["saved"]
        assert again["filename"] == "Q3 spend by market (1).pptx", "a file already in Downloads is never overwritten"
        assert save(client, "Spend.xlsx", office("xl/workbook.xml")).status_code == 200
        assert save(client, "Spend.png", PNG).status_code == 200
        assert client.post(f"/api/v1/exports/{saved['id']}/open", headers=HEADERS).json() == {"ok": True}
        assert opened == [str(downloads / "Q3 spend by market.pptx")]
        assert sorted(p.name for p in downloads.iterdir()) == ["Q3 spend by market (1).pptx", "Q3 spend by market.pptx",
                                                               "Spend.png", "Spend.xlsx"]
        audit = [r["action"] for r in client.app.state.store.db.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'export:%' ORDER BY rowid").fetchall()]
        assert audit == ["export:save"] * 4 + ["export:open"]

        # Only the kinds a visual exports, and only files that are what their name says.
        assert save(client, "run.exe", b"MZ\x90\x00").status_code == 415
        assert save(client, "Spend.xlsx", office("ppt/presentation.xml")).status_code == 415, "a slide named .xlsx"
        assert save(client, "Spend.pptx", b"PK\x03\x04 not a zip").status_code == 415
        assert save(client, "Spend.png", b"GIF89a").status_code == 415
        assert save(client, "Spend.png", PNG, headers={}).status_code == 403, "the Wizard request header is required"
        assert save(client, "..\\..\\Windows\\evil.png", PNG).json()["saved"]["filename"] == "evil.png"
        assert not (tmp_path / "Windows").exists()

        login(client, "u-cfo")
        assert client.post(f"/api/v1/exports/{saved['id']}/open", headers=HEADERS).status_code == 404, "another person's file"
    with TestClient(client.app, client=("10.20.30.40", 50000)) as remote:
        login(remote, "u-ceo")
        refused = save(remote, "Spend.png", PNG)
        assert refused.status_code == 409 and refused.json()["code"] == "not_on_this_pc", \
            "away from the person's PC the page downloads it through the browser instead"


def test_export_names_stay_in_the_folder_and_keep_their_kind():
    assert clean_name("C:\\Users\\x\\Q3: spend.xlsx") == "Q3: spend.xlsx"  # free_name removes what Windows refuses
    assert clean_name("../../a.pptx") == "a.pptx"
    assert clean_name(".pptx") == "Wizard visual.pptx"
    assert clean_name("x" * 300 + ".PNG").endswith(".png") and len(clean_name("x" * 300 + ".png")) == 120
    assert Path(clean_name("  ")).suffix == ""
