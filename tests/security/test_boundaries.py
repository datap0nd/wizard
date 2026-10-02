"""Adversarial and boundary checks: session/CSRF, internal tool API, injected source text, secret exposure."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from tests.helpers import CEO_QUESTION, CONQUEST_QUESTION, HEADERS, ask, login

from wizard_api.security import run_token

ROOT = Path(__file__).resolve().parents[2]


def test_api_requires_a_session(client):
    for path in ("/api/v1/conversations", "/api/v1/sources", "/api/v1/reports", "/api/v1/account/gemini"):
        response = client.get(path)
        assert response.status_code == 401 and response.json()["login_required"]
    assert client.get("/api/v1/health").status_code == 200


def test_state_changes_need_the_wizard_header_and_same_origin(client):
    login(client, "u-ceo")
    assert client.post("/api/v1/runs", json={"question": "x"}).status_code == 403
    foreign = client.post("/api/v1/runs", json={"question": "x"}, headers={**HEADERS, "Origin": "https://evil.example"})
    assert foreign.status_code == 403
    assert client.post("/api/v1/session/login", json={"user_id": "u-ceo"}).status_code == 403


def test_forged_or_foreign_session_cookie_is_ignored(client):
    client.cookies.set("wizard_session", "eyJ1IjoidS1jZW8ifQ.AAAA")
    assert client.get("/api/v1/conversations").status_code == 401


def test_security_headers_and_no_store(client):
    response = client.get("/api/v1/health")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff" and response.headers["cache-control"] == "no-store"


def test_internal_tool_api_needs_a_valid_token_for_an_active_run(client):
    assert client.get("/internal/v1/tools").status_code == 401
    bad = client.get("/internal/v1/tools", headers={"Authorization": "Bearer nonsense"})
    assert bad.status_code == 401
    secret = client.app.state.settings.session_secret
    inactive = client.get("/internal/v1/tools", headers={"Authorization": f"Bearer {run_token(secret, 'run_gone', 'u-ceo', 60)}"})
    assert inactive.status_code == 409
    session_cookie_as_token = client.post("/api/v1/session/login", json={"user_id": "u-ceo"}, headers=HEADERS).cookies.get("wizard_session")
    assert client.get("/internal/v1/tools", headers={"Authorization": f"Bearer {session_cookie_as_token}"}).status_code == 401


def test_run_token_cannot_be_reused_for_another_users_run(client):
    from wizard_api.runs import ActiveRun
    from wizard_connectors.entitlements import IdentityDirectory
    manager = client.app.state.manager
    directory = IdentityDirectory.load(ROOT / "fixtures" / "identities.json")
    identity = directory.get("u-dir-gulf")
    manager.active["run_x"] = ActiveRun("run_x", identity, "cnv", "ask", "q", None, "gemini-cli")
    try:
        secret = client.app.state.settings.session_secret
        stolen = run_token(secret, "run_x", "u-ceo", 60)
        assert client.get("/internal/v1/tools", headers={"Authorization": f"Bearer {stolen}"}).status_code == 409
        own = run_token(secret, "run_x", "u-dir-gulf", 60)
        call = client.post("/internal/v1/tools/asap_run_report", json={"arguments": {"report_id": "asap-gross-margin"}},
                           headers={"Authorization": f"Bearer {own}"}).json()
        assert not call["ok"] and "report_not_available" in call["text"]
        wrong_server = client.post("/internal/v1/tools/nerp_run_report", json={"arguments": {}, "scope": "asap"},
                                   headers={"Authorization": f"Bearer {own}"}).json()
        assert not wrong_server["ok"] and "wrong_server" in wrong_server["text"]
        injected = client.post("/internal/v1/tools/nerp_export_all", json={"arguments": {"scope": "*"}},
                               headers={"Authorization": f"Bearer {own}"}).json()
        assert not injected["ok"] and "unknown_tool" in injected["text"]
    finally:
        manager.active.pop("run_x", None)


def test_injected_instruction_in_source_text_gains_nothing(client):
    login(client, "u-ceo")
    run = ask(client, CONQUEST_QUESTION)
    assert run["status"] == "succeeded"
    names = {e["payload"]["name"] for e in run["events"] if e["type"] == "tool_started"}
    assert names <= {s.name for s in client.app.state.registry.list()}
    assert "did not act on it" in run["answer"]
    notes = ask(client, "Show me the campaign notes for Egypt in Q3")
    assert "did not follow it" in notes["answer"]
    audit = client.app.state.store.audit_entries("u-ceo")
    assert not [a for a in audit if "export" in (a["action"] or "")]


def test_responses_never_carry_tokens_or_secrets(client):
    login(client, "u-ceo")
    run = ask(client, CEO_QUESTION)
    bodies = [client.get("/api/v1/bootstrap").text, client.get(f"/api/v1/runs/{run['id']}").text,
              client.get(f"/api/v1/reports/{run['report_id']}").text, client.get("/api/v1/account/gemini").text]
    secret_hex = client.app.state.settings.session_secret.hex()
    for body in bodies:
        assert secret_hex not in body
        assert not re.search(r"ya29\.|1//0|GOCSPX-|refresh_token|run_token", body)


def test_account_link_rejects_someone_elses_google_account(tmp_path):
    import httpx
    from fastapi.testclient import TestClient
    from tests.helpers import make_settings

    from wizard_api.app import create_app

    def google(request: httpx.Request) -> httpx.Response:
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "ya29.x", "refresh_token": "1//r", "expires_in": 3600})
        return httpx.Response(200, json={"email": "developer@wizard.test"})

    app = create_app(make_settings(tmp_path, WIZARD_AGENT_RUNTIME="code-assist"), google_transport=httpx.MockTransport(google))
    with TestClient(app) as client:
        login(client, "u-ceo")
        state = client.post("/api/v1/account/gemini/link", headers=HEADERS).json()["state"]
        refused = client.post("/api/v1/account/gemini/link/complete", json={"state": state, "code": "4/abc"}, headers=HEADERS)
        assert refused.status_code == 403 and "own enterprise Google account" in refused.json()["error"]
        assert not client.get("/api/v1/account/gemini").json()["linked"]
        replayed = client.post("/api/v1/account/gemini/link/complete", json={"state": state, "code": "4/abc"}, headers=HEADERS)
        assert replayed.status_code == 400, "a sign-in attempt can be used once"


def test_account_link_stores_tokens_only_in_the_users_home(tmp_path):
    import httpx
    from fastapi.testclient import TestClient
    from tests.helpers import make_settings

    from wizard_api.app import create_app

    def google(request: httpx.Request) -> httpx.Response:
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "ya29.x", "refresh_token": "1//r", "expires_in": 3600})
        return httpx.Response(200, json={"email": "ceo@wizard.test"})

    app = create_app(make_settings(tmp_path, WIZARD_AGENT_RUNTIME="code-assist"), google_transport=httpx.MockTransport(google))
    with TestClient(app) as client:
        login(client, "u-ceo")
        state = client.post("/api/v1/account/gemini/link", headers=HEADERS).json()["state"]
        status = client.post("/api/v1/account/gemini/link/complete", json={"state": state, "code": "4/abc"}, headers=HEADERS).json()
        assert status["linked"] and status["google_email"] == "ceo@wizard.test" and "1//r" not in json.dumps(status)
        settings = app.state.settings
        ceo_home, cfo_home = settings.user_home("u-ceo"), settings.user_home("u-cfo")
        assert (ceo_home / "gemini" / ".gemini" / "oauth_creds.json").is_file()
        assert not cfo_home.exists() or not any(cfo_home.rglob("*cred*"))
        login(client, "u-cfo")
        assert not client.get("/api/v1/account/gemini").json()["linked"]
        login(client, "u-ceo")
        assert not client.delete("/api/v1/account/gemini", headers=HEADERS).json()["linked"]


def test_repository_secret_scan_is_clean():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "scan_secrets.py")], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
