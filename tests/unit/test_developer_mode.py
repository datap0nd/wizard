"""Developer mode (owner, 19 Nov 2026): Tasks and the other developer settings appear once the person at this PC enters
the developer PIN. Only the PIN's digest is in the repository; the flag is this PC's own and never travels in a settings
file. docs/decisions/2026-11-19-developer-mode.md."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient
from tests.helpers import HEADERS, make_settings
from tests.unit.test_desktop import CONTROL, desktop_app
from tests.unit.test_settings_pane import PASSWORD, install, owner

from wizard_api import developer_mode, provisioning, settings_pane
from wizard_api.app import create_app

TEST_PIN = "4711"


def test_only_the_digest_of_the_pin_is_kept():
    assert re.fullmatch(r"[0-9a-f]{64}", developer_mode.PIN_SHA256)
    expected = developer_mode.digest(TEST_PIN)
    assert developer_mode.pin_matches(TEST_PIN, expected) and developer_mode.pin_matches(f" {TEST_PIN} ", expected)
    for wrong in ("", "   ", "4712", TEST_PIN * 9):
        assert not developer_mode.pin_matches(wrong, expected)
    assert not developer_mode.pin_matches(TEST_PIN), "the test PIN is not the owner's"


def test_the_person_at_this_pc_turns_it_on_with_the_pin_and_off_again(tmp_path, monkeypatch):
    monkeypatch.setattr(developer_mode, "PIN_SHA256", developer_mode.digest(TEST_PIN))
    settings = install(tmp_path)
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/session/login", json={"user_id": "u-ceo"}, headers=HEADERS)
        assert client.post("/api/v1/developer-mode", json={"pin": TEST_PIN}, headers=HEADERS).status_code == 404, \
            "a synthetic test identity is not the person at the PC"
        owner(client)
        assert client.get("/api/v1/bootstrap").json()["developer_mode"] is False
        assert client.get("/api/v1/settings").json()["developer_mode"] is False
        wrong = client.post("/api/v1/developer-mode", json={"pin": "0000"}, headers=HEADERS)
        assert wrong.status_code == 403 and wrong.json()["error"] == "That PIN is not right."
        assert not developer_mode.is_on(settings.data_dir)
        right = client.post("/api/v1/developer-mode", json={"pin": TEST_PIN}, headers=HEADERS)
        assert right.status_code == 200 and right.json() == {"developer_mode": True}
        assert client.get("/api/v1/bootstrap").json()["developer_mode"] is True
        assert client.get("/api/v1/settings").json()["developer_mode"] is True
        assert TEST_PIN not in developer_mode.path(settings.data_dir).read_text(encoding="utf-8"), "the PIN is never stored"
    with TestClient(create_app(install(tmp_path))) as client:  # Wizard restarted: it stays on for this PC
        owner(client)
        assert client.get("/api/v1/bootstrap").json()["developer_mode"] is True
        assert client.delete("/api/v1/developer-mode", headers=HEADERS).json() == {"developer_mode": False}
        assert client.get("/api/v1/bootstrap").json()["developer_mode"] is False
    assert not developer_mode.path(settings.data_dir).exists()


def test_a_server_has_no_developer_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(developer_mode, "PIN_SHA256", developer_mode.digest(TEST_PIN))
    with TestClient(create_app(make_settings(tmp_path))) as client:  # a server behind SSO, not a person's install
        client.post("/api/v1/session/login", json={"user_id": "u-ceo"}, headers=HEADERS)
        assert client.post("/api/v1/developer-mode", json={"pin": TEST_PIN}, headers=HEADERS).status_code == 404
        assert client.get("/api/v1/bootstrap").json()["developer_mode"] is False


def test_the_tray_reads_it_from_the_control_api(tmp_path):
    app = desktop_app(tmp_path)
    with TestClient(app) as client:
        status = client.get("/internal/v1/desktop/status", headers={"X-Wizard-Control": CONTROL}).json()
        assert status["developer_mode"] is False
        developer_mode.turn_on(tmp_path / "data")
        status = client.get("/internal/v1/desktop/status", headers={"X-Wizard-Control": CONTROL}).json()
        assert status["developer_mode"] is True


def test_no_settings_file_carries_it_to_another_pc(tmp_path):
    settings = install(tmp_path)
    provisioning.update_local(settings.data_dir, {"WIZARD_PG_HOST": "db.corp", "WIZARD_PG_PASSWORD": PASSWORD})
    developer_mode.turn_on(settings.data_dir)
    exported = settings_pane.export(settings)
    assert "developer" not in exported["text"].lower(), "Export settings… leaves it on this PC"
    assert developer_mode.path(settings.data_dir).parent == settings.data_dir
    assert not developer_mode.path(settings.data_dir).is_relative_to(provisioning.folder(settings.data_dir))
    other = tmp_path / "other"
    offered = tmp_path / "wizard.provision"
    offered.write_text(exported["text"], encoding="utf-8")
    provisioning.import_file(offered, other)
    assert not developer_mode.is_on(other), "a PC that imports the file starts as a beginner's"


def test_a_damaged_flag_file_means_off(tmp_path):
    developer_mode.path(tmp_path).write_text("not json", encoding="utf-8")
    assert not developer_mode.is_on(tmp_path)
    developer_mode.path(tmp_path).write_text('{"on": "yes"}', encoding="utf-8")
    assert not developer_mode.is_on(tmp_path)
    developer_mode.path(tmp_path).write_text("[]", encoding="utf-8")
    assert not developer_mode.is_on(tmp_path)


def test_the_tray_hides_its_developer_items_until_developer_mode_is_on():
    from wizard_connectors.paths import ROOT

    context = (ROOT / "apps" / "desktop" / "WizardBar" / "WizardContext.cs").read_text(encoding="utf-8")
    assert 'Backend.Text(status, "developer_mode") == "True"' in context
    assert "syncNow.Visible = developerMode;" in context and "exportSettings.Visible = developerMode;" in context
    assert 'new ToolStripMenuItem("Export settings…", null' not in context, "Export settings… is the hidden item, not a second one"
