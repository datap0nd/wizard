from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from tests.helpers import CEO_QUESTION, HEADERS, ask, login, make_settings

from wizard_agent.runtime import AgentFailure
from wizard_api.app import create_app


def test_two_users_are_isolated(tmp_path):
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as ceo, TestClient(app) as director:
        login(ceo, "u-ceo")
        login(director, "u-dir-gulf")
        run = ask(ceo, CEO_QUESTION)
        assert director.get("/api/v1/conversations").json()["conversations"] == []
        assert director.get(f"/api/v1/conversations/{run['conversation_id']}").status_code == 404
        assert director.get(f"/api/v1/runs/{run['id']}").status_code == 404
        assert director.get(f"/api/v1/runs/{run['id']}/events").status_code == 404
        assert director.get(f"/api/v1/reports/{run['report_id']}").status_code == 404
        assert director.get(f"/api/v1/conversations/{run['conversation_id']}/evidence/E1").status_code == 404
        assert director.post(f"/api/v1/runs/{run['id']}/check", headers=HEADERS).status_code == 404
        assert not director.post(f"/api/v1/runs/{run['id']}/cancel", headers=HEADERS).json()["cancelled"]
        assert director.post("/api/v1/runs", json={"question": "x", "conversation_id": run["conversation_id"]},
                             headers=HEADERS).status_code == 404
        settings = app.state.settings
        assert settings.user_home("u-ceo") != settings.user_home("u-dir-gulf")


def test_director_answer_is_limited_to_entitled_markets(client):
    login(client, "u-dir-gulf")
    run = ask(client, CEO_QUESTION)
    assert run["status"] == "succeeded"
    evidence = client.get(f"/api/v1/conversations/{run['conversation_id']}/evidence/E1").json()["evidence"]
    markets = {row[0] for row in evidence["rows"]}
    assert markets <= {"SA", "AE"} and evidence["access_note"]


def test_revoked_rights_block_report_reopen(tmp_path):
    identities = json.loads(Path("fixtures/identities.json").read_text(encoding="utf-8"))
    path = tmp_path / "identities.json"
    path.write_text(json.dumps(identities), encoding="utf-8")
    settings = make_settings(tmp_path, WIZARD_IDENTITIES_FILE=str(path))
    with TestClient(create_app(settings)) as client:
        login(client, "u-ceo")
        run = ask(client, CEO_QUESTION)
    for user in identities["users"]:
        if user["id"] == "u-ceo":
            user["entitlements"]["nerp"] = {"reports": [], "markets": []}
    path.write_text(json.dumps(identities), encoding="utf-8")
    with TestClient(create_app(settings)) as client:
        login(client, "u-ceo")
        reopened = client.get(f"/api/v1/reports/{run['report_id']}")
        assert reopened.status_code == 403 and reopened.json()["code"] == "access_changed"
        assert client.get(f"/api/v1/conversations/{run['conversation_id']}/evidence/E1").status_code == 403
        audit = client.app.state.store.audit_entries("u-ceo")
        assert any(a["action"] == "report:open" and a["outcome"] == "access_changed" for a in audit)


class Outage:
    kind = "gemini-cli"
    model = "gemini-3.8-flash"

    def label(self):
        return "Outage test runtime"

    async def readiness(self, home, email):
        return {"ready": True, "reason": None}

    async def run(self, request, emit, tools, cancelled):
        await emit("text_delta", {"text": "Starting"})
        raise AgentFailure("model_unreachable", "Gemini could not be reached from this host (network, proxy or certificate).")


def test_model_outage_is_a_clear_failure(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), runtime=Outage())) as client:
        login(client, "u-ceo")
        run = ask(client, CEO_QUESTION)
        assert run["status"] == "failed" and run["error_code"] == "model_unreachable" and "proxy" in run["error_message"]
        assert run["report_id"] is None
        assert client.get("/api/v1/reports").json()["reports"] == []


class EmptyTurns(Outage):
    """Code Assist after a tool call: Gemini sent back nothing, twice on each model (code_assist raises this)."""
    kind = "code-assist"

    def __init__(self, note: str = ""):
        self.note = note

    async def run(self, request, emit, tools, cancelled):
        if self.note:
            await emit("text_delta", {"text": self.note})
        await tools.call("wizard_lookup_definitions", {"query": "share"})
        await emit("status", {"message": "Gemini is busy; trying again in 5 s (attempt 1 of 10)."})
        raise AgentFailure("empty_answer", "Gemini sent back an empty turn 4 times in a row: no answer and no request for "
                                           "data. Google's reason: a normal stop, with nothing written (STOP).",
                           {"Google's finish reason": "a normal stop, with nothing written (STOP)",
                            "Google's message": "token ya29.a0AfB_secret leaked into a message"})


def test_a_failed_answer_says_exactly_why_under_error_details(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), runtime=EmptyTurns())) as client:
        login(client, "u-ceo")
        run = ask(client, CEO_QUESTION)
        assert run["status"] == "failed" and run["error_code"] == "empty_answer"
        failed = next(e["payload"] for e in run["events"] if e["type"] == "run_failed")
        details = failed["details"]
        assert list(details)[:3] == ["Error code", "Google's finish reason", "Google's message"], "the runtime's facts first"
        assert details["Error code"] == "empty_answer" and details["Google's finish reason"].endswith("(STOP)")
        assert details["Google's message"] == "token [redacted] leaked into a message"
        assert details["Model"] == "gemini-3.8-flash" and details["Connection"] == "Outage test runtime"
        assert details["Tool calls"] == "1" and details["Last tool call"].startswith("wizard_lookup_definitions at ")
        assert details["Last tool call"].endswith(": ok")
        assert details["Last status"] == "Gemini is busy; trying again in 5 s (attempt 1 of 10)."
        assert details["Run"] == run["id"] and details["Ran for"].endswith(" s")


def test_an_empty_last_turn_after_a_message_shows_that_message(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), runtime=EmptyTurns(note="EG leads on share."))) as client:
        login(client, "u-ceo")
        run = ask(client, CEO_QUESTION)
        assert run["status"] == "succeeded" and run["answer"] == "EG leads on share."
        finished = next(e["payload"] for e in run["events"] if e["type"] == "run_finished")
        assert "Gemini finished without a separate final answer; its last message is shown." in finished["warnings"]


class Broken(Outage):
    async def run(self, request, emit, tools, cancelled):
        raise KeyError("evidence_id")


def test_an_internal_error_names_the_exception_and_where(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), runtime=Broken())) as client:
        login(client, "u-ceo")
        run = ask(client, CEO_QUESTION)
        details = next(e["payload"] for e in run["events"] if e["type"] == "run_failed")["details"]
        assert run["error_code"] == "internal_error" and details["Exception"] == "KeyError: 'evidence_id'"
        assert details["Where"].startswith("test_isolation_and_failures.py, line ") and details["Where"].endswith(" in run")


class Unlinked(Outage):
    async def readiness(self, home, email):
        return {"ready": False, "reason": "Link your own Gemini account to ask questions."}


def test_unlinked_account_never_falls_back_to_another_login(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), runtime=Unlinked())) as client:
        login(client, "u-ceo")
        run = ask(client, CEO_QUESTION)
        assert run["status"] == "failed" and run["error_code"] == "gemini_signin_required"


def test_source_outage_is_disclosed(tmp_path):
    from wizard_connectors.fixture_source import FixtureSource
    with TestClient(create_app(make_settings(tmp_path))) as client:
        services = client.app.state.manager.services
        services.sources["gscm"] = FixtureSource(services.catalog, tmp_path / "missing")
        login(client, "u-ceo")
        run = ask(client, CEO_QUESTION)
        assert run["status"] == "failed" and run["error_code"] == "replay_error"
        finished = [e["payload"] for e in run["events"] if e["type"] == "tool_finished"]
        gscm = next(f for f in finished if f["name"] == "gscm_run_report")
        assert not gscm["ok"] and gscm["error_code"] == "source_unavailable"


def test_restart_marks_interrupted_runs(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings)
    store = app.state.store
    conversation = store.create_conversation("u-ceo")
    store.create_run({"id": "run_stuck", "conversation_id": conversation, "user_id": "u-ceo", "kind": "ask", "question": "q",
                      "status": "running", "created_at": "2026-10-02T00:00:00Z"})
    restarted = create_app(settings)
    with TestClient(restarted) as client:
        login(client, "u-ceo")
        run = client.get("/api/v1/runs/run_stuck").json()
        assert run["status"] == "failed" and run["error_code"] == "interrupted"
