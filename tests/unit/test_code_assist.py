"""Code Assist route against a scripted fake of Google's endpoints (no network)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from wizard_agent import code_assist, google_oauth
from wizard_agent.code_assist import CodeAssistRuntime, classify_limit, gemini_schema, thinking_config
from wizard_agent.runtime import AgentFailure, AgentRequest
from wizard_agent.secret_box import SecretBox


class FakeGoogle:
    def __init__(self, turns: list[list[dict]], capacity_errors: int = 0, refusals: dict[str, list[dict | None]] | None = None):
        self.turns = turns
        self.capacity_errors = capacity_errors
        self.refusals = refusals or {}  # model -> per request: an error body Google answers with (HTTP 429), or None
        self.requests: list[dict] = []
        self.models: list[str] = []

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
            self.models.append(body["model"])
            if self.refusals.get(body["model"]) and (refusal := self.refusals[body["model"]].pop(0)) is not None:
                return httpx.Response(429, json=refusal)
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


def make(tmp_path: Path, fake: FakeGoogle, model: str = "gemini-3.8-flash", fallback: str | None = None
         ) -> tuple[CodeAssistRuntime, AgentRequest]:
    box = SecretBox(force_plain=True)
    home = tmp_path / "users" / "a"
    box.write(CodeAssistRuntime.token_path(home), "refresh-1")
    rt = CodeAssistRuntime(model, box, transport=httpx.MockTransport(fake), fallback_model=fallback)
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


def test_a_busy_gemini_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr("wizard_agent.code_assist.retry_delay", lambda hint, attempt: 0)
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


def google_error(reason: str = "", message: str = "", delay: str | None = None, quota_id: str | None = None) -> dict:
    details: list[dict] = []
    if reason:
        details.append({"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason,
                        "domain": "cloudcode-pa.googleapis.com"})
    if quota_id:
        details.append({"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]})
    if delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    return {"error": {"code": 429, "message": message or "Resource has been exhausted", "status": "RESOURCE_EXHAUSTED",
                      "details": details}}


CAPACITY = google_error("MODEL_CAPACITY_EXHAUSTED", "No capacity available for model gemini-3.1-pro on the server")


@pytest.mark.parametrize(("status", "body", "kind", "delay"), [
    (429, CAPACITY, "capacity", None),
    (429, {"error": {"code": 429, "message": "You have exhausted your capacity on this model."}}, "capacity", None),
    (429, google_error("QUOTA_EXHAUSTED", delay="7200s"), "quota", 7200),
    (429, google_error(quota_id="GenerateRequestsPerDayPerProjectPerModel"), "quota", None),
    (429, google_error("RATE_LIMIT_EXCEEDED"), "quota", None),
    (429, google_error("RATE_LIMIT_EXCEEDED", delay="400s"), "quota", 400),
    (429, google_error("RATE_LIMIT_EXCEEDED", delay="12.5s"), "rate", 12.5),
    (429, google_error(quota_id="GenerateRequestsPerMinutePerProjectPerModel"), "rate", 60),
    (429, {"error": {"code": 429, "message": "Quota exceeded: limit: 0, model gemini-3.1-pro"}}, "quota", None),
    (429, [{"error": {"code": 429, "message": "Please retry in 1500ms", "details": []}}], "busy", 1.5),
    (503, {"error": {"code": 503, "message": "The model is overloaded."}}, "busy", None),
    (500, {"error": {"code": 500, "message": "Internal error encountered."}}, "busy", None),
])
def test_google_refusals_are_read_like_gemini_cli(status, body, kind, delay):
    limit = classify_limit(status, json.dumps(body))
    assert (limit.kind, limit.delay) == (kind, delay)


def run_and_collect(rt, req, bridge=None):
    events: list[tuple[str, dict]] = []

    async def emit(kind, payload):
        events.append((kind, payload))

    asyncio.run(rt.run(req, emit, bridge or Bridge(), lambda: False))
    return events


@pytest.fixture
def waits(monkeypatch):
    waited: list[float] = []

    async def no_wait(seconds):
        waited.append(seconds)

    monkeypatch.setattr(code_assist, "sleep", no_wait)
    return waited


def test_a_model_google_has_no_room_for_hands_over_to_the_fallback_and_says_so(tmp_path, waits):
    fake = FakeGoogle([
        [{"functionCall": {"name": "nerp_run_report", "args": {"report_id": "r"}}, "thoughtSignature": "sig-pro"}],
        [{"text": "EG [E1]."}],
        [{"text": "Again."}],
    ], refusals={"gemini-3.1-pro": [None, CAPACITY, CAPACITY, CAPACITY]})  # the first step on Pro goes through
    rt, req = make(tmp_path, fake, model="gemini-3.1-pro", fallback="gemini-3.8-flash")
    events = run_and_collect(rt, req)
    assert fake.models == ["gemini-3.1-pro", "gemini-3.1-pro", "gemini-3.1-pro", "gemini-3.1-pro", "gemini-3.8-flash"]
    assert waits == [1.0, 3.0], "two quick tries, as Gemini CLI, then no more waiting"
    sessions = [p["model"] for k, p in events if k == "agent_session"]
    assert sessions == ["gemini-3.1-pro", "gemini-3.8-flash"], "the run records the model that answered"
    warning = next(p["message"] for k, p in events if k == "warning")
    assert "no capacity for gemini-3.1-pro" in warning and "not your quota" in warning and "gemini-3.8-flash" in warning
    switched = fake.requests[-1]["request"]["contents"]
    assert switched[1]["parts"][0]["thoughtSignature"] == "skip_thought_signature_validator"
    assert [p["text"] for k, p in events if k == "text_delta"][-1] == "EG [E1]."
    # The next question starts on the fallback for a while, and says why.
    events = run_and_collect(rt, req)
    assert fake.models[-1] == "gemini-3.8-flash" and len(fake.models) == 6
    assert any(k == "warning" and "answers with gemini-3.8-flash" in p["message"] for k, p in events)


def test_a_used_up_quota_is_not_waited_for(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={"gemini-3.1-pro": [google_error("QUOTA_EXHAUSTED", delay="7200s")]})
    rt, req = make(tmp_path, fake, model="gemini-3.1-pro")
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert error.value.code == "model_quota" and waits == []
    assert "quota for gemini-3.1-pro is used up (back in about 2 h)" in error.value.message
    assert "model chip" in error.value.message


def test_a_per_minute_limit_waits_as_long_as_google_asks(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={"gemini-3.8-flash": [google_error("RATE_LIMIT_EXCEEDED", delay="17s")]})
    rt, req = make(tmp_path, fake, fallback="gemini-3.8-flash")
    events = run_and_collect(rt, req)
    assert len(waits) == 1 and 17 <= waits[0] <= 17 * 1.2
    status = next(p["message"] for k, p in events if k == "status")
    assert status.startswith("Gemini's per-minute limit for gemini-3.8-flash was reached; waiting")


def test_no_capacity_without_a_fallback_says_whose_side_it_is(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={"gemini-3.8-flash": [CAPACITY, CAPACITY, CAPACITY]})
    rt, req = make(tmp_path, fake, fallback="gemini-3.8-flash")
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert error.value.code == "model_capacity"
    assert error.value.message.startswith("Google has no capacity for gemini-3.8-flash right now. This is on Google's side")
