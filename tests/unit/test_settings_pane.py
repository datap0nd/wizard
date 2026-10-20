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
from wizard_api.config import load_settings

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
        assert has(field(view, "WIZARD_GEMINI_MODEL"), value="gemini-3.8-flash", source="default")
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


def test_the_model_changes_without_a_restart(tmp_path):
    with TestClient(create_app(install(tmp_path))) as client:
        owner(client)
        saved = put(client, {"WIZARD_GEMINI_MODEL": "gemini-3.1-pro"}).json()
        assert saved["apply"] == "none" and saved["model"] == "gemini-3.1-pro"
        assert client.get("/api/v1/bootstrap").json()["runtime"]["model"] == "gemini-3.1-pro"
        assert client.get("/api/v1/models").json()["current"] == "gemini-3.1-pro"
    assert load_settings(env={}, home=tmp_path).model == "gemini-3.1-pro", "kept after a restart"


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


def test_model_options_come_from_the_persons_own_quota(tmp_path):
    def google(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2.googleapis.com/token" in url:
            return httpx.Response(200, json={"access_token": "ya29.x", "refresh_token": "1//r", "expires_in": 3600})
        if "userinfo" in url:
            return httpx.Response(200, json={"email": "rafael@company.example"})
        if url.endswith(":loadCodeAssist"):
            return httpx.Response(200, json={"currentTier": {"id": "standard-tier"}, "cloudaicompanionProject": "p"})
        if url.endswith(":retrieveUserQuota"):
            return httpx.Response(200, json={"buckets": [{"modelId": "gemini-3.8-flash", "remainingFraction": 0.9},
                                                         {"modelId": "gemini-3.1-pro", "remainingFraction": 0.5}]})
        return httpx.Response(404)

    # gemini-cli: the quota then goes through the separate Code Assist client that takes the fake transport.
    settings = install(tmp_path, WIZARD_AGENT_RUNTIME="gemini-cli")
    with TestClient(create_app(settings, google_transport=httpx.MockTransport(google))) as client:
        owner(client)
        assert client.get("/api/v1/models").json()["reason"], "not linked yet: only the current model, with the reason"
        state = client.post("/api/v1/account/gemini/link", headers=HEADERS).json()["state"]
        client.post("/api/v1/account/gemini/link/complete", json={"state": state, "code": "4/abc"}, headers=HEADERS)
        listed = client.get("/api/v1/models").json()
        assert listed["options"] == ["gemini-3.1-pro", "gemini-3.8-flash"] and listed["editable"]


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
    assert offline["ok"] is False and "Could not read the release" in offline["message"]
    with TestClient(create_app(settings)) as client:
        owner(client)
        monkeypatch.setattr(settings_pane, "check_update", lambda s: {"ok": True, "available": False, "message": "latest"})
        assert client.get("/api/v1/updates").json()["message"] == "latest"


@pytest.mark.parametrize("key", [f.key for f in settings_pane.FIELDS])
def test_every_pane_field_is_a_setting_wizard_reads(key):
    import pathlib
    config = (pathlib.Path(__file__).resolve().parents[2] / "services" / "api" / "wizard_api" / "config.py").read_text(encoding="utf-8")
    pg = (pathlib.Path(__file__).resolve().parents[2] / "services" / "connectors" / "wizard_connectors" / "pg.py").read_text(encoding="utf-8")
    from wizard_api.config import PORTAL_KEY  # WIZARD_PORTAL_<NAME>: any portal, read by pattern
    assert f'"{key}"' in config or (key.startswith("WIZARD_PG_") and "WIZARD_PG_" in pg) or PORTAL_KEY.match(key)
