"""Code Assist route against a scripted fake of Google's endpoints (no network)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from wizard_agent import google_oauth
from wizard_agent.code_assist import CodeAssistRuntime, gemini_schema, thinking_config
from wizard_agent.runtime import AgentFailure, AgentRequest
from wizard_agent.secret_box import SecretBox


class FakeGoogle:
    def __init__(self, turns: list[list[dict]], capacity_errors: int = 0):
        self.turns = turns
        self.capacity_errors = capacity_errors
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(google_oauth.TOKEN_ENDPOINT):
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["refresh-1"]
            return httpx.Response(200, json={"access_token": "ya29.access", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer ya29.access"
        if url.endswith(":loadCodeAssist"):
            return httpx.Response(200, json={"currentTier": {"id": "standard-tier"}, "cloudaicompanionProject": "corp-gemini"})
        if ":streamGenerateContent" in url:
            if self.capacity_errors:
                self.capacity_errors -= 1
                return httpx.Response(429, json={"error": {"details": [{"retryDelay": "0s"}]}})
            body = json.loads(request.content)
            self.requests.append(body)
            chunks = self.turns[len(self.requests) - 1]
            sse = "".join(f"data: {json.dumps({'response': {'candidates': [{'content': {'role': 'model', 'parts': [c]}}]}})}\n\n"
                          for c in chunks)
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)


class Bridge:
    def __init__(self):
        self.calls = []

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return True, json.dumps({"evidence_id": "E1", "rows": [["EG", 1500000]]})

    def describe(self):
        return [{"name": "nerp_run_report", "description": "d", "inputSchema": {"type": "object", "properties": {
            "report_id": {"type": "string"}, "rows": {"type": "array", "items": {"anyOf": [{"type": "number"}, {"type": "string"}]}}},
            "required": ["report_id"], "additionalProperties": False}}]

    def evidence_index(self):
        return []


def make(tmp_path: Path, fake: FakeGoogle) -> tuple[CodeAssistRuntime, AgentRequest]:
    box = SecretBox(force_plain=True)
    home = tmp_path / "users" / "a"
    box.write(CodeAssistRuntime.token_path(home), "refresh-1")
    rt = CodeAssistRuntime("gemini-3.8-flash", box, transport=httpx.MockTransport(fake))
    req = AgentRequest(run_id="run_1", user_id="u-ceo", user_email="ceo@wizard.test", user_home=home, prompt="Which market?",
                       question="Which market?", kind="ask")
    return rt, req


def test_agent_loop_executes_tool_calls_and_echoes_thought_signatures(tmp_path):
    fake = FakeGoogle([
        [{"text": "Checking NERP."}, {"functionCall": {"name": "nerp_run_report", "args": {"report_id": "nerp-mkt-spend-quarterly"}},
                                      "thoughtSignature": "sig-abc"}],
        [{"text": "EG spent $1.5M [E1]."}],
    ])
    rt, req = make(tmp_path, fake)
    events, bridge = [], Bridge()

    async def emit(kind, payload):
        events.append((kind, payload))

    asyncio.run(rt.run(req, emit, bridge, lambda: False))
    assert bridge.calls == [("nerp_run_report", {"report_id": "nerp-mkt-spend-quarterly"})]
    first, second = fake.requests
    assert first["project"] == "corp-gemini" and first["model"] == "gemini-3.8-flash"
    assert first["request"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "HIGH"}
    declaration = first["request"]["tools"][0]["functionDeclarations"][0]
    assert declaration["parameters"]["type"] == "OBJECT" and "additionalProperties" not in json.dumps(declaration)
    model_turn = second["request"]["contents"][1]
    assert model_turn["role"] == "model" and model_turn["parts"][1]["thoughtSignature"] == "sig-abc"
    response = second["request"]["contents"][2]["parts"][0]["functionResponse"]
    assert response["name"] == "nerp_run_report" and response["response"]["evidence_id"] == "E1"
    assert [e for e in events if e[0] == "text_delta"][-1][1]["text"] == "EG spent $1.5M [E1]."


def test_capacity_is_retried_then_reported(tmp_path, monkeypatch):
    monkeypatch.setattr("wizard_agent.code_assist.retry_delay", lambda body, attempt: 0)
    fake = FakeGoogle([[{"text": "ok"}]], capacity_errors=2)
    rt, req = make(tmp_path, fake)
    events = []

    async def emit(kind, payload):
        events.append(kind)

    asyncio.run(rt.run(req, emit, Bridge(), lambda: False))
    assert events.count("status") == 2 and "text_delta" in events


def test_missing_sign_in_is_a_clear_failure(tmp_path):
    rt = CodeAssistRuntime("gemini-3.8-flash", SecretBox(force_plain=True))
    req = AgentRequest(run_id="r", user_id="u", user_email="e", user_home=tmp_path, prompt="p", question="q", kind="ask")

    async def emit(*_):
        return None

    with pytest.raises(AgentFailure) as error:
        asyncio.run(rt.run(req, emit, Bridge(), lambda: False))
    assert error.value.code == "gemini_signin_required"


def test_schema_and_thinking_helpers():
    schema = gemini_schema({"type": "object", "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "d"},
                                                             "cell": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
                            "additionalProperties": False})
    assert schema == {"type": "OBJECT", "properties": {"x": {"type": "INTEGER", "description": "d"},
                                                       "cell": {"type": "STRING", "description": "(number or text)"}}}
    assert thinking_config("gemini-3.8-flash", "high") == {"thinkingLevel": "HIGH"}
    assert thinking_config("gemini-2.5-pro", "high") == {"thinkingBudget": -1}
    assert thinking_config("gemini-3.8-flash", "none") is None
