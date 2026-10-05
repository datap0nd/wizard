"""Dev-mode diagnostics: failure classification, the inherited Gemini project, run tracebacks and the server log."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient
from tests.helpers import ask, login, make_settings

from wizard_agent.gemini_cli import classify, inherited_project
from wizard_agent.replay import ReplayRuntime
from wizard_api.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_status_codes_are_classified_as_whole_words():
    """Regression: the word boundaries had become literal backspace characters, so 401/403/429 never matched."""
    assert classify("Request failed with status code 401")[0] == "gemini_signin_required"
    assert classify("got status 429 from the API")[0] == "model_capacity"
    assert classify("[API Error: 403 Forbidden]")[0] == "model_permission_denied"
    assert classify("[API Error: 503 Service Unavailable] The model is overloaded")[0] == "model_unavailable"
    assert classify("ConnectTimeoutError: Connect Timeout Error (attempted address: x:443)")[0] == "model_unreachable"
    assert classify("This account requires setting the GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_PROJECT_ID env var.")[0] == "project_required"
    assert classify("models/gemini-9 is not found for API version v1internal (404)")[0] == "model_not_found"
    assert classify("request 4014031 at 1790927401123 failed")[0] == "model_error", "digits inside ids are not status codes"


def test_no_control_characters_in_source():
    bad = [p for p in (ROOT / "services").rglob("*.py") if any(ord(c) < 32 and c not in "\n\r\t" for c in p.read_text(encoding="utf-8"))]
    assert not bad, f"control characters (a mangled escape such as \\b) in {bad}"


def test_project_is_inherited_from_the_users_own_gemini_cli(tmp_path):
    assert inherited_project({"GOOGLE_CLOUD_PROJECT": "from-env"}) == ("from-env", "GOOGLE_CLOUD_PROJECT environment variable")
    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".gemini" / ".env").write_text("# mine\nexport GOOGLE_CLOUD_PROJECT=\"cli-project\"\n", encoding="utf-8")
    project, source = inherited_project({"USERPROFILE": str(tmp_path)})
    assert project == "cli-project" and ".gemini" in source
    (tmp_path / ".gemini" / ".env").unlink()
    (tmp_path / ".env").write_text("GOOGLE_CLOUD_PROJECT_ID=home-project\n", encoding="utf-8")
    assert inherited_project({"USERPROFILE": str(tmp_path)})[0] == "home-project"
    assert inherited_project({"USERPROFILE": str(tmp_path / "nobody")}) == (None, "not set")


class Broken(ReplayRuntime):
    async def run(self, request, emit, tools, cancelled):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom in the runtime")


def test_unexpected_failure_shows_its_traceback_in_dev_mode(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, runtime=Broken(settings.transcripts_dir, 0))) as client:
        login(client, "u-ceo")
        run = ask(client, "Hey")
        assert run["status"] == "failed" and run["error_code"] == "internal_error"
        diagnostic = next(e["payload"] for e in run["events"] if e["type"] == "diagnostic")
        assert diagnostic["error"] == "RuntimeError: boom in the runtime" and "Traceback" in diagnostic["traceback"]


def test_server_log_is_available_in_dev_mode_only(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        login(client, "u-ceo")
        assert client.get("/api/v1/bootstrap").json()["diagnostics"] is True
        logging.getLogger("wizard.test").warning("visible in the UI log")
        assert any("visible in the UI log" in line for line in client.get("/api/v1/dev/log").json()["lines"])
    with TestClient(create_app(make_settings(tmp_path, WIZARD_DIAGNOSTICS="false"))) as client:
        login(client, "u-ceo")
        assert client.get("/api/v1/bootstrap").json()["diagnostics"] is False
        assert client.get("/api/v1/dev/log").status_code == 404
