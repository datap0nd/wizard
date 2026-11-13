"""The settings pane, the model picker and the update check: who may change what, where each value comes from, secrets
never sent back, .env values taken over, invalid changes rolled back, the model switched without a restart."""
from __future__ import annotations

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, make_settings

from wizard_api import knowledge_sync, provisioning, settings_pane
from wizard_api.app import create_app
from wizard_api.config import PICKER_KEYS, load_settings

PASSWORD = "pg-secret-123"
TOKEN = "github_pat_" + "y" * 40


def install(tmp_path, env_lines: str = "", **env: str):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_text("WIZARD_AGENT_RUNTIME=code-assist\nWIZARD_LOCAL_USER_NAME=Rafael\n" + env_lines, encoding="utf-8")
    return load_settings(env={"WIZARD_PROXY": "direct", **env}, home=tmp_path)


def owner(client: TestClient) -> None:
    assert client.post("/api/v1/session/login", json={"user_id": "local-owner"}, headers=HEADERS).status_code == 200


def put(client: TestClient, values: dict) -> httpx.Response:
    return client.put("/api/v1/settings", json={"values": values}, headers=HEADERS)


def field(view: dict, key: str) -> dict:
    return next(f for f in view["fields"] if f["key"] == key)


def has(found: dict, **expected) -> bool:
    return all(found.get(k) == v for k, v in expected.items())


def test_only_the_person_on_their_own_install_can_change_settings(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:  # a server, not an install
        client.post("/api/v1/session/login", json={"user_id": "u-ceo"}, headers=HEADERS)
        assert client.get("/api/v1/settings").status_code == 404
        assert client.get("/api/v1/bootstrap").json()["settings_editable"] is False
    with TestClient(create_app(install(tmp_path / "pc"))) as client:
        client.post("/api/v1/session/login", json={"user_id": "u-ceo"}, headers=HEADERS)
        assert client.get("/api/v1/settings").status_code == 404, "a synthetic test identity is not the person at the PC"
        owner(client)
        assert client.get("/api/v1/bootstrap").json()["settings_editable"] is True
        assert client.get("/api/v1/settings").status_code == 200


def test_sources_are_shown_and_secrets_are_never_sent(tmp_path):
    company = tmp_path / "company.provision"
    company.write_text(json.dumps({"wizard_provision": 1, "name": "ACME", "settings": {
        "WIZARD_PG_HOST": "db.corp.example", "WIZARD_PG_USER": "wizard_ro", "WIZARD_PG_PASSWORD": PASSWORD}}), encoding="utf-8")
    provisioning.import_file(company, tmp_path / "data")
    settings = install(tmp_path, "WIZARD_PG_DATABASE=bi\n")
    with TestClient(create_app(settings)) as client:
        owner(client)
        response = client.get("/api/v1/settings")
        assert PASSWORD not in response.text
        view = response.json()
        assert has(field(view, "WIZARD_PG_HOST"), value="db.corp.example", source="company", editable=True)
        assert has(field(view, "WIZARD_PG_PASSWORD"), value=None, set=True, source="company", secret=True)
        assert field(view, "WIZARD_PG_DATABASE")["source"] == "env_file"
        assert view["company_file"]["name"] == "ACME" and view["restart"] == "manual"


def test_saving_moves_values_out_of_env_and_survives_a_new_company_file(tmp_path):
    settings = install(tmp_path, f"WIZARD_PG_HOST=old.example\nWIZARD_PG_PASSWORD={PASSWORD}\n")
    with TestClient(create_app(settings)) as client:
        owner(client)
        saved = put(client, {"WIZARD_PG_HOST": "db2.example", "WIZARD_PG_USER": "ro", "WIZARD_PG_PASSWORD": "new-pass-456"})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["apply"] == "manual" and set(body["changed"]) == {"WIZARD_PG_HOST", "WIZARD_PG_USER", "WIZARD_PG_PASSWORD"}
        assert "new-pass-456" not in saved.text and field(body, "WIZARD_PG_PASSWORD")["source"] == "this_pc"
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "WIZARD_PG_HOST" not in env_text and PASSWORD not in env_text, "taken over from .env, no plain password left"
    assert "WIZARD_AGENT_RUNTIME=code-assist" in env_text
    stored = (tmp_path / "data" / "settings" / "settings.json").read_text(encoding="utf-8")
    assert "new-pass-456" not in stored
    reloaded = load_settings(env={}, home=tmp_path)
    assert reloaded.postgres and (reloaded.postgres.host, reloaded.postgres.password) == ("db2.example", "new-pass-456")
    company = tmp_path / "c.provision"
    company.write_text(json.dumps({"wizard_provision": 1, "settings": {"WIZARD_PG_HOST": "company.example"}}), encoding="utf-8")
    provisioning.import_file(company, tmp_path / "data")
    assert load_settings(env={}, home=tmp_path).postgres.host == "db2.example", "this PC's choice beats the company file"
    with TestClient(create_app(load_settings(env={}, home=tmp_path))) as client:
        owner(client)
        assert put(client, {"WIZARD_PG_HOST": ""}).status_code == 200
    assert load_settings(env={}, home=tmp_path).postgres.host == "company.example", "empty returns to the company value"


def test_an_invalid_change_is_rolled_back(tmp_path):
    settings = install(tmp_path, "WIZARD_KB_REPO=acme/kb\n")
    before = (tmp_path / ".env").read_text(encoding="utf-8")
    with TestClient(create_app(settings)) as client:
        owner(client)
        refused = put(client, {"WIZARD_KB_REPO": "not a repo"})
        assert refused.status_code == 400 and "owner/name" in refused.json()["error"]
        assert put(client, {"WIZARD_PG_SSLMODE": "sometimes"}).status_code == 400
        assert put(client, {"WIZARD_DATA_DIR": "x"}).status_code == 400
        assert put(client, {"WIZARD_GEMINI_MODEL": "Gemini 3.1 Pro!"}).status_code == 400
    assert (tmp_path / ".env").read_text(encoding="utf-8") == before
    assert provisioning.load(tmp_path / "data", layer="local") is None


def test_everyone_is_on_the_default_model_and_a_picked_one_no_longer_applies(tmp_path):
    """The in-app model picker was removed (owner, 20 Oct 2026): Gemini 3.8 Flash, falling back to 3.1 Pro preview as
    in Gemini CLI. A model saved with the picker is ignored."""
    provisioning.update_local(tmp_path / "data", {"WIZARD_GEMINI_MODEL": "gemini-3.1-pro",
                                                  "WIZARD_GEMINI_FALLBACK_MODEL": "none"})
    settings = install(tmp_path)
    assert (settings.model, settings.fallback_model) == ("gemini-3.8-flash", "gemini-3.1-pro-preview")
    with TestClient(create_app(settings)) as client:
        owner(client)
        keys = {f["key"] for f in client.get("/api/v1/settings").json()["fields"]}
        assert not keys & {"WIZARD_GEMINI_MODEL", "WIZARD_GEMINI_FALLBACK_MODEL"}
        assert put(client, {"WIZARD_GEMINI_MODEL": "gemini-3.1-pro"}).status_code == 400
        assert client.get("/api/v1/models").status_code == 404
        assert client.get("/api/v1/bootstrap").json()["runtime"]["model"] == "gemini-3.8-flash"
    assert install(tmp_path, WIZARD_GEMINI_MODEL="gemini-3.1-flash").model == "gemini-3.1-flash", "the environment still can"


def test_desktop_restarts_itself_to_apply_other_settings(tmp_path):
    settings = install(tmp_path)
    settings.desktop = True
    app = create_app(settings)
    asked: list[str] = []
    app.state.request_restart = lambda: asked.append("restart")
    with TestClient(app) as client:
        owner(client)
        assert client.get("/api/v1/settings").json()["restart"] == "automatic"
        assert put(client, {"WIZARD_PROXY": "http://proxy.corp:8080"}).json()["apply"] == "now"
        deadline = time.time() + 5
        while not asked and time.time() < deadline:
            time.sleep(0.1)
    assert asked == ["restart"]


def test_a_value_set_in_the_environment_cannot_be_changed_here(tmp_path, monkeypatch):
    monkeypatch.setenv("WIZARD_PG_HOST", "env.example")
    with TestClient(create_app(install(tmp_path))) as client:
        owner(client)
        assert has(field(client.get("/api/v1/settings").json(), "WIZARD_PG_HOST"), source="environment", editable=False)
        locked = put(client, {"WIZARD_PG_HOST": "other.example"})
        assert locked.status_code == 409 and "environment variable" in locked.json()["error"]


def test_connection_tests_use_the_proposed_values(tmp_path, monkeypatch):
    def github(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert str(request.url).startswith("https://github.sec.samsung.net/api/v3/repos/")
        return httpx.Response(200, text="c" * 40) if "acme/kb" in str(request.url) else httpx.Response(404)

    original = knowledge_sync.check
    monkeypatch.setattr(knowledge_sync, "check", lambda source, **kw: original(source, transport=httpx.MockTransport(github)))
    with TestClient(create_app(install(tmp_path))) as client:
        owner(client)
        test = lambda section, values: client.post("/api/v1/settings/test", json={"section": section, "values": values},  # noqa: E731
                                                   headers=HEADERS).json()
        ok = test("knowledge", {"WIZARD_KB_REPO": "acme/kb", "WIZARD_KB_TOKEN": TOKEN})
        assert ok["ok"] and "cccccccccccc" in ok["message"]
        assert "Contents: read" in test("knowledge", {"WIZARD_KB_REPO": "acme/other", "WIZARD_KB_TOKEN": TOKEN})["message"]
        assert test("knowledge", {"WIZARD_KB_REPO": "acme/kb"})["message"] == "Fill in the repository and the token."
        assert test("postgres", {})["message"] == "Fill in at least the server and the user."
        failed = test("postgres", {"WIZARD_PG_HOST": "127.0.0.1", "WIZARD_PG_PORT": "1", "WIZARD_PG_USER": "ro"})
        assert failed["ok"] is False and failed["message"].startswith("Could not connect")
    assert provisioning.load(tmp_path / "data", layer="local") is None, "a test saves nothing"


def test_update_check_compares_with_the_installed_build(tmp_path, monkeypatch):
    manifest = {"version": "1.0.9.0", "commit": "d" * 40, "installer_sha256": "e" * 64, "size": 1}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=manifest))
    settings = install(tmp_path)
    monkeypatch.setattr(settings_pane, "installed_build", lambda: {"version": "1.0.4.0", "commit": "a" * 40})
    newer = settings_pane.check_update(settings, transport=transport)
    assert newer["available"] and newer["latest"] == "1.0.9.0" and newer["download"].endswith("/WizardSetup.exe")
    monkeypatch.setattr(settings_pane, "installed_build", lambda: {"version": "1.0.9.0"})
    assert settings_pane.check_update(settings, transport=transport)["available"] is False
    offline = settings_pane.check_update(settings, transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    assert offline["ok"] is False and "Could not read the release" in offline["message"] and "503" in offline["message"]
    with TestClient(create_app(settings)) as client:
        owner(client)
        monkeypatch.setattr(settings_pane, "check_update", lambda s: {"ok": True, "available": False, "message": "latest"})
        assert client.get("/api/v1/updates").json()["message"] == "latest"


def test_update_check_routes_each_redirect_hop_on_its_own(monkeypatch):
    """GitHub redirects a release link to its download host; the Windows proxy settings may route that host differently."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Release(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's name
            if self.path == "/download/wizard-desktop.json":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}/asset/wizard-desktop.json")
                self.end_headers()
                return
            body = b'{"version": "1.0.66.0"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Release)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    routed: list[str] = []
    monkeypatch.setattr(settings_pane.outbound, "proxy_for", lambda url, override=None: (routed.append(url), (None, "direct"))[1])
    try:
        start = f"http://127.0.0.1:{server.server_port}/download/wizard-desktop.json"
        assert settings_pane._read_release(start, None, None) == {"version": "1.0.66.0"}
    finally:
        server.shutdown()
        server.server_close()
    assert routed == [start, f"http://localhost:{server.server_port}/asset/wizard-desktop.json"]


def test_update_check_reads_the_mirror_first_then_the_release(tmp_path, monkeypatch):
    """Owner, 30 Oct 2026: GitHub downloads were tightened on the work network; read where Metronome's setup.ps1 reads.
    api.github.com's manifest on the mirror branch first, then the release; a proxy's page is not a manifest."""
    settings = install(tmp_path)
    monkeypatch.setattr(settings_pane, "installed_build", lambda: {"version": "1.0.59.0"})
    manifest = {"version": "1.0.66.0", "commit": "f" * 40}
    asked: list[httpx.Request] = []
    down: set[str] = set()

    def github(request):
        asked.append(request)
        if request.url.host in down:
            return httpx.Response(403, json={"message": "Blocked by policy"})
        if request.url.host == "api.github.com" and "proxy-page" in down:
            return httpx.Response(200, json={"message": "Blocked by policy"})
        return httpx.Response(200, json=manifest)

    transport = httpx.MockTransport(github)
    found = settings_pane.check_update(settings, transport=transport)
    assert found["ok"] and found["available"] and found["latest"] == "1.0.66.0"
    assert [str(r.url) for r in asked] == [settings_pane.MIRROR_MANIFEST], "the mirror answered; the release is not needed"
    assert asked[0].headers["accept"] == "application/vnd.github.raw+json" and asked[0].headers["user-agent"] == "Wizard"

    for blocked in ("api.github.com", "proxy-page"):
        asked.clear()
        down.clear()
        down.add(blocked)
        rescued = settings_pane.check_update(settings, transport=transport)
        assert rescued["ok"] and rescued["latest"] == "1.0.66.0", f"the release answers when the mirror cannot ({blocked})"
        assert [str(r.url) for r in asked] == [settings_pane.MIRROR_MANIFEST, settings_pane.RELEASE + "wizard-desktop.json"]
        assert asked[1].headers["accept"] == "*/*", "the release is asked plainly"

    down.add("github.com")
    down.add("api.github.com")
    failed = settings_pane.check_update(settings, transport=transport)
    assert failed["ok"] is False and failed["message"].startswith("Could not read the release: api.github.com: ")
    assert "github.com: " in failed["message"] and "403" in failed["message"]

    def handshake_timeout(request):
        raise httpx.ConnectTimeout("_ssl.c:1015: The handshake operation timed out", request=request)

    stuck = settings_pane.check_update(settings, transport=httpx.MockTransport(handshake_timeout))["message"]
    assert "Wizard could not reach api.github.com" in stuck and "Wizard could not reach github.com" in stuck
    assert "_ssl.c:1015" in stuck


def test_update_check_never_starts_powershell():
    """Owner, 30 Oct 2026: Microsoft Defender reported Wizard's hidden PowerShell downloads as malware
    (execution/mdp.powershell.m4192). The service reads the manifest itself; Check with Windows is WizardBar's."""
    import inspect

    source = inspect.getsource(settings_pane)
    assert "powershell.exe" not in source.lower() and "subprocess" not in source and "Invoke-WebRequest" not in source


@pytest.mark.parametrize("key", [f.key for f in settings_pane.FIELDS])
def test_every_pane_field_is_a_setting_wizard_reads(key):
    import pathlib
    config = (pathlib.Path(__file__).resolve().parents[2] / "services" / "api" / "wizard_api" / "config.py").read_text(encoding="utf-8")
    pg = (pathlib.Path(__file__).resolve().parents[2] / "services" / "connectors" / "wizard_connectors" / "pg.py").read_text(encoding="utf-8")
    portals = (pathlib.Path(__file__).resolve().parents[2] / "services" / "connectors" / "wizard_connectors" / "portals.py").read_text(encoding="utf-8")
    nerp = (pathlib.Path(__file__).resolve().parents[2] / "services" / "connectors" / "wizard_connectors" / "nerp.py").read_text(encoding="utf-8")
    assert f'"{key}"' in config or (key.startswith("WIZARD_PG_") and "WIZARD_PG_" in pg) or \
        (key.startswith(("WIZARD_PORTAL_", "WIZARD_BROWSER")) and f'"{key}"' in portals) or \
        (key.startswith("WIZARD_NERP_") and (f'"{key}"' in nerp or f'get("{key.removeprefix("WIZARD_NERP_")}"' in nerp))


def test_export_writes_this_pcs_settings_as_a_provisioning_file_for_another_pc(tmp_path):
    """Owner, 30 Oct 2026: "I want to export my settings file basically. and imkport it there"."""
    settings = install(tmp_path, "WIZARD_PG_PORT=5433\n")
    company = tmp_path / "company.provision"
    company.write_text(provisioning.render({"WIZARD_KB_REPO": "acme/wizard-content", "WIZARD_KB_TOKEN": TOKEN,
                                            "WIZARD_PG_HOST": "db.corp", "WIZARD_PG_USER": "ro", "WIZARD_PG_PASSWORD": "old",
                                            "WIZARD_NEWS_TABLE": "public.news"}, "ACME Wizard"), encoding="utf-8")
    provisioning.import_file(company, settings.data_dir)
    provisioning.update_local(settings.data_dir, {"WIZARD_PG_PASSWORD": PASSWORD, "WIZARD_KB_WRITE_TOKEN": "github_pat_" + "w" * 40,
                                                  "WIZARD_PORTAL_GSCM_URL": "https://gscm.corp/", "WIZARD_GEMINI_MODEL": "old-pick"})
    exported = settings_pane.export(settings)
    found = provisioning.parse(exported["text"])
    assert found.name == "ACME Wizard (exported)"
    assert found.values() == {"WIZARD_KB_REPO": "acme/wizard-content", "WIZARD_KB_TOKEN": TOKEN, "WIZARD_PG_HOST": "db.corp",
                              "WIZARD_PG_USER": "ro", "WIZARD_PG_PASSWORD": PASSWORD, "WIZARD_PG_PORT": "5433",
                              "WIZARD_NEWS_TABLE": "public.news", "WIZARD_PORTAL_GSCM_URL": "https://gscm.corp/"}, \
        "this PC's choice beats the company file, .env beats both; per-PC values, the write token and old picks stay"
    assert exported["secrets"] == ["WIZARD_KB_TOKEN", "WIZARD_PG_PASSWORD"] and exported["left_out"] == ["WIZARD_KB_WRITE_TOKEN"]
    assert "WIZARD_PG_HOST" in exported["settings"] and "WIZARD_KB_TOKEN" not in exported["settings"]
    # The other PC imports it as its company file and ends up with the same values.
    other = tmp_path / "other"
    offered = tmp_path / "wizard.provision"
    offered.write_text(exported["text"], encoding="utf-8")
    provisioning.import_file(offered, other)
    assert provisioning.load(other).values() == found.values() and not offered.exists()
    with pytest.raises(settings_pane.PaneError, match="no settings to export"):
        settings_pane.export(install(tmp_path / "empty"))


def test_quick_setup_imports_the_settings_file_the_person_chose_and_restarts(tmp_path):
    """Owner, 13 Nov 2026: Quick setup in Settings takes a new person "through importing a settings file". The page sends
    the file's text; Wizard checks it, stores it as the company file (secrets encrypted) and restarts to apply it."""
    settings = install(tmp_path)
    settings.desktop = True
    app = create_app(settings)
    asked: list[str] = []
    app.state.request_restart = lambda: asked.append("restart")
    text = "﻿" + provisioning.render({"WIZARD_PG_HOST": "db.corp", "WIZARD_PG_USER": "ro", "WIZARD_PG_PASSWORD": PASSWORD},
                                          "ACME Wizard")
    with TestClient(app) as client:
        assert client.post("/api/v1/settings/import", json={"text": text}, headers=HEADERS).status_code == 401
        client.post("/api/v1/session/login", json={"user_id": "u-ceo"}, headers=HEADERS)
        assert client.post("/api/v1/settings/import", json={"text": text}, headers=HEADERS).status_code in (401, 404), \
            "the person at the PC only"
        assert provisioning.load(settings.data_dir) is None
        owner(client)
        bad = client.post("/api/v1/settings/import", json={"text": json.dumps({"settings": {"WIZARD_PG_HOST": "x"}})},
                          headers=HEADERS)
        assert bad.status_code == 400 and "not a Wizard provisioning file" in bad.json()["error"]
        assert provisioning.load(settings.data_dir) is None, "nothing is stored from a file that is not valid"
        local = client.post("/api/v1/settings/import", headers=HEADERS, json={"text": provisioning.render(
            {"WIZARD_PG_HOST": "db.corp"}, "x").replace('"WIZARD_PG_HOST"', '"WIZARD_DATA_DIR"')})
        assert local.status_code == 400 and "set on each PC" in local.json()["error"]
        done = client.post("/api/v1/settings/import", json={"text": text}, headers=HEADERS)
        assert done.status_code == 200, done.text
        assert done.json() == {"name": "ACME Wizard", "settings": 2, "secrets": 1, "apply": "now"}
        assert PASSWORD not in done.text
        deadline = time.time() + 5
        while not asked and time.time() < deadline:
            time.sleep(0.1)
    assert asked == ["restart"]
    assert PASSWORD not in (settings.data_dir / "provision" / "settings.json").read_text(encoding="utf-8")
    reloaded = load_settings(env={}, home=tmp_path)
    assert reloaded.postgres and (reloaded.postgres.host, reloaded.postgres.password) == ("db.corp", PASSWORD)
    assert reloaded.provision["name"] == "ACME Wizard"


def test_run_limits_are_set_in_minutes_up_to_ten_hours(tmp_path):
    """Owner, 13 Nov 2026: "Wizard should have all its configuration settings in the settings pane. stuff like max time
    total (Its 30m, should be able to go up to 10h)". The pane shows the time limit in minutes; Wizard reads seconds."""
    settings = install(tmp_path, "WIZARD_MAX_TOOL_CALLS=300\n")
    with TestClient(create_app(settings)) as client:
        owner(client)
        view = client.get("/api/v1/settings").json()
        assert "runs" in [s["id"] for s in view["sections"]]
        limit = field(view, "WIZARD_RUN_TIMEOUT_S")
        assert has(limit, section="runs", source="default", value="", placeholder="30", editable=True)
        assert limit["number"] == {"low": 1, "high": 600, "unit": "minutes", "whole": False}
        assert has(field(view, "WIZARD_MAX_TOOL_CALLS"), value="300", source="env_file")
        saved = put(client, {"WIZARD_RUN_TIMEOUT_S": "600", "WIZARD_MAX_TOOL_CALLS": "2000"})
        assert saved.status_code == 200, saved.text
        assert has(field(saved.json(), "WIZARD_RUN_TIMEOUT_S"), value="600", source="this_pc")
        for values, why in (({"WIZARD_RUN_TIMEOUT_S": "601"}, "between 1 and 600 minutes"),
                            ({"WIZARD_RUN_TIMEOUT_S": "ten"}, "must be a number"),
                            ({"WIZARD_MAX_TOOL_CALLS": "2001"}, "between 1 and 2,000 calls"),
                            ({"WIZARD_MAX_TOOL_CALLS": "12.5"}, "whole number")):
            refused = put(client, values)
            assert refused.status_code == 400 and why in refused.json()["error"], (values, refused.text)
    reloaded = load_settings(env={}, home=tmp_path)
    assert (reloaded.run_timeout_s, reloaded.max_tool_calls) == (36000, 2000)
    assert provisioning.load(settings.data_dir, layer="local").values()["WIZARD_RUN_TIMEOUT_S"] == "36000"
    assert "WIZARD_MAX_TOOL_CALLS" not in (tmp_path / ".env").read_text(encoding="utf-8"), "Save moves it out of .env"
    assert settings_pane.export(reloaded)["text"].count('"WIZARD_RUN_TIMEOUT_S": "36000"') == 1, "another PC gets it too"


def test_a_time_limit_in_seconds_is_shown_in_minutes(tmp_path):
    settings = install(tmp_path, "WIZARD_RUN_TIMEOUT_S=1000\nWIZARD_ATTACHMENT_TIMEOUT_S=90\n")
    view = settings_pane.describe(settings)
    assert field(view, "WIZARD_RUN_TIMEOUT_S")["value"] == "16.67"
    assert has(field(view, "WIZARD_ATTACHMENT_TIMEOUT_S"), value="90", number={"low": 10, "high": 3600, "unit": "seconds",
                                                                                "whole": True})
    assert settings_pane._clean({"WIZARD_RUN_TIMEOUT_S": "1.5"}) == {"WIZARD_RUN_TIMEOUT_S": "90"}


def test_choices_show_words_people_read(tmp_path):
    view = settings_pane.describe(install(tmp_path))
    assert has(field(view, "WIZARD_DIAGNOSTICS"), choices=["true", "false"], choice_labels=["Shown", "Hidden"])
    assert has(field(view, "WIZARD_GEMINI_THINKING"), choices=["high", "low", "none"], placeholder="high")
    assert field(view, "WIZARD_PG_SSLMODE")["choice_labels"] == []


def test_attachment_folders_are_this_pcs_own(tmp_path):
    """The folders From this PC lists are set in the pane, never by a company file or carried by Export settings…"""
    folder = tmp_path / "Reports"
    folder.mkdir()
    settings = install(tmp_path / "pc")
    with TestClient(create_app(settings)) as client:
        owner(client)
        assert put(client, {"WIZARD_ATTACHMENT_FOLDERS": str(tmp_path / "missing")}).status_code == 400
        assert put(client, {"WIZARD_ATTACHMENT_FOLDERS": str(folder), "WIZARD_PG_NAME": "BI"}).status_code == 200
    assert load_settings(env={}, home=tmp_path / "pc").attachment_folders == [folder.resolve()]
    exported = settings_pane.export(settings)
    assert "WIZARD_ATTACHMENT_FOLDERS" not in exported["text"] and exported["left_out"] == []
    company = tmp_path / "company.provision"
    company.write_text(json.dumps({"wizard_provision": 1, "settings": {"WIZARD_ATTACHMENT_FOLDERS": "C:\\x"}}), encoding="utf-8")
    with pytest.raises(provisioning.ProvisionError, match="set on each PC"):
        provisioning.import_file(company, tmp_path / "other")


def test_the_desktop_does_not_put_back_a_default_the_person_changed(tmp_path):
    """Save takes a key out of .env; the desktop's start-up adds missing defaults to .env, which would win again."""
    from wizard_api import desktop
    home = tmp_path / "home"
    desktop.ensure_env(home)
    assert "WIZARD_DIAGNOSTICS=false" in (home / ".env").read_text(encoding="utf-8")
    settings = load_settings(env={}, home=home)
    settings_pane.save(settings, {"WIZARD_DIAGNOSTICS": "true"})
    assert desktop.ensure_env(home) == []
    assert load_settings(env={}, home=home).diagnostics is True


# What the pane leaves out, and why: the install itself (folders, port, sign-in mode, set by the installer or setup), a
# server behind SSO, a protection, and developers' tests. Everything else Wizard reads is a Settings field.
NOT_IN_THE_PANE = {
    "WIZARD_AGENT_RUNTIME", "WIZARD_HOST", "WIZARD_PORT", "WIZARD_DATA_DIR", "WIZARD_LOCAL_USER_EMAIL",
    "WIZARD_LOCAL_USER_NAME", "WIZARD_CONTENT_DIR", "WIZARD_CONTROL_TOKEN",
    "WIZARD_AUTH_MODE", "WIZARD_IDENTITY_HEADER", "WIZARD_TRUSTED_PROXIES", "WIZARD_PUBLIC_ORIGIN", "WIZARD_SECURE_COOKIES",
    "WIZARD_REQUIRE_GOOGLE_EMAIL_MATCH", "WIZARD_GOOGLE_CLOUD_PROJECT",  # the pane sets GOOGLE_CLOUD_PROJECT, its other name
    "WIZARD_GEMINI_CLI_JS", "WIZARD_NODE", "WIZARD_GEMINI_FAKE_RESPONSES", "WIZARD_IDENTITIES_FILE", "WIZARD_TRANSCRIPTS_DIR",
    "WIZARD_WEB_DIST", "WIZARD_REPLAY_DELAY_S", "WIZARD_BROWSER_EXECUTABLE",
}


def test_every_setting_wizard_reads_is_in_the_pane():
    import pathlib
    import re
    config = (pathlib.Path(__file__).resolve().parents[2] / "services" / "api" / "wizard_api" / "config.py").read_text(encoding="utf-8")
    read = set(re.findall(r'get\("(WIZARD_[A-Z0-9_]+)"', config)) | {"WIZARD_BROWSER_EXECUTABLE"}
    missing = read - set(settings_pane.BY_KEY) - NOT_IN_THE_PANE - set(PICKER_KEYS)
    assert not missing, f"add these to Settings (settings_pane.FIELDS) or say why not in NOT_IN_THE_PANE: {sorted(missing)}"
    assert not NOT_IN_THE_PANE & set(settings_pane.BY_KEY)
