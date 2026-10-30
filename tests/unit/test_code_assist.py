"""Code Assist route against a scripted fake of Google's endpoints (no network)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from wizard_agent import code_assist, google_oauth
from wizard_agent.code_assist import CodeAssistRuntime, classify_limit, gemini_schema, thinking_config
from wizard_agent.runtime import AgentFailure, AgentRequest
from wizard_agent.secret_box import SecretBox
from wizard_api.config import load_settings


class FakeGoogle:
    def __init__(self, turns: list[list[dict] | dict], capacity_errors: int = 0, refusals: dict[str, list[dict | None]] | None = None,
                 buckets: list[dict] | None = None):
        self.turns = turns
        self.capacity_errors = capacity_errors
        self.refusals = refusals or {}  # model -> per request: an error body Google answers with (HTTP 429), or None
        self.buckets = buckets  # retrieveUserQuota's buckets (the person's quota numbers); None: Google does not answer
        self.quota_checks = 0
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
        if url.endswith(":retrieveUserQuota") and self.buckets is not None:
            assert json.loads(request.content) == {"project": "corp-gemini"}
            self.quota_checks += 1
            return httpx.Response(200, json={"buckets": self.buckets})
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
            if isinstance(chunks, dict):  # a whole response as Google sends it (finishReason, promptFeedback...)
                return httpx.Response(200, text=f"data: {json.dumps({'response': chunks})}\n\n",
                                      headers={"content-type": "text/event-stream"})
            sse = "".join(f"data: {json.dumps({'response': {'candidates': [{'content': {'role': 'model', 'parts': [c]}}]}})}\n\n"
                          for c in chunks)
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)


class Bridge:
    def __init__(self):
        self.calls = []
        self.steers: list[str] = []  # notes the person sent, not yet read by Gemini
        self.on_call = None  # called with each tool call: a test sends a note mid-step

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if self.on_call:
            self.on_call(name)
        return True, json.dumps({"evidence_id": "E1", "rows": [["EG", 1500000]]})

    def steers_waiting(self):
        return bool(self.steers)

    async def take_steers(self):
        taken, self.steers = self.steers, []
        return taken

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
    assert events.count("model_wait") == 2 and "text_delta" in events
    assert "status" not in events, "people see Wizard working, not Gemini being busy (owner, 23 Oct)"


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


FLASH_CAPACITY = google_error("MODEL_CAPACITY_EXHAUSTED", "No capacity available for model gemini-3.8-flash on the server")


def test_flash_without_capacity_hands_over_to_pro_like_gemini_cli(tmp_path, waits):
    fake = FakeGoogle([
        [{"functionCall": {"name": "nerp_run_report", "args": {"report_id": "r"}}, "thoughtSignature": "sig-flash"}],
        [{"text": "EG [E1]."}],
        [{"text": "Again."}],
    ], refusals={"gemini-3.8-flash": [None] + [FLASH_CAPACITY] * 3})  # the first step on Flash goes through
    settings = load_settings(env={"WIZARD_DATA_DIR": str(tmp_path / "var")}, home=tmp_path)
    rt, req = make(tmp_path, fake, model=settings.model, fallback=settings.fallback_model)  # the defaults
    events = run_and_collect(rt, req)
    assert fake.models == ["gemini-3.8-flash"] * 4 + ["gemini-3.1-pro-preview"]
    assert waits == [1.0, 3.0], "two quick tries, as Gemini CLI, then no more waiting"
    sessions = [p["model"] for k, p in events if k == "agent_session"]
    assert sessions == ["gemini-3.8-flash", "gemini-3.1-pro-preview"], "the run records the model that answered"
    assert not any(k in ("warning", "status") for k, _ in events), "as in Gemini CLI, the switch is silent: no error, no notice"
    switched = fake.requests[-1]["request"]["contents"]
    assert switched[1]["parts"][0]["thoughtSignature"] == "skip_thought_signature_validator"
    assert fake.requests[-1]["request"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "HIGH"}
    assert [p["text"] for k, p in events if k == "text_delta"][-1] == "EG [E1]."
    # The next question starts on Flash again: Google's capacity comes and goes, and Pro is the slower model.
    events = run_and_collect(rt, req)
    assert fake.models[-1] == "gemini-3.8-flash" and len(fake.models) == 6
    assert [p["model"] for k, p in events if k == "agent_session"] == ["gemini-3.8-flash"]
    assert not any(k in ("warning", "status") for k, _ in events)


def test_a_used_up_quota_still_says_why_another_model_answers(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}], [{"text": "again"}]],
                      refusals={"gemini-3.8-flash": [google_error("QUOTA_EXHAUSTED", delay="7200s")]})
    rt, req = make(tmp_path, fake, fallback="gemini-3.1-pro-preview")
    events = run_and_collect(rt, req)
    assert fake.models == ["gemini-3.8-flash", "gemini-3.1-pro-preview"] and waits == []
    switch = next(p["message"] for k, p in events if k == "status")
    assert "quota for gemini-3.8-flash is used up" in switch and "Wizard continues with gemini-3.1-pro-preview." in switch
    events = run_and_collect(rt, req)
    assert any(k == "status" and "answers with gemini-3.1-pro-preview" in p["message"] for k, p in events)


def test_a_used_up_quota_is_not_waited_for(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={"gemini-3.1-pro": [google_error("QUOTA_EXHAUSTED", delay="7200s")]})
    rt, req = make(tmp_path, fake, model="gemini-3.1-pro")
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert error.value.code == "model_quota" and waits == []
    assert "quota for gemini-3.1-pro is used up (back in about 2 h). Try again once it resets." in error.value.message
    assert "model chip" not in error.value.message, "the model picker is gone"


def test_a_per_minute_limit_waits_as_long_as_google_asks(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={"gemini-3.8-flash": [google_error("RATE_LIMIT_EXCEEDED", delay="17s")]})
    rt, req = make(tmp_path, fake, fallback="gemini-3.8-flash")
    events = run_and_collect(rt, req)
    assert len(waits) == 1 and 17 <= waits[0] <= 17 * 1.2
    wait = next(p for k, p in events if k == "model_wait")
    assert wait["reason"] == "rate" and wait["seconds"] == pytest.approx(waits[0], abs=0.1) and wait["round"] == 1
    assert not any(k in ("status", "warning") for k, _ in events), "the wait is not shown"


@pytest.mark.parametrize("fallback", ["gemini-3.8-flash", None])
def test_no_capacity_with_no_other_model_is_waited_out(tmp_path, waits, fallback):
    # The default: the fallback is the model itself, so there is nowhere to go. Gemini CLI (unattended) keeps trying.
    fake = FakeGoogle([[{"text": "ok"}]], refusals={"gemini-3.8-flash": [CAPACITY, CAPACITY, CAPACITY]})
    rt, req = make(tmp_path, fake, fallback=fallback)
    events = run_and_collect(rt, req)
    assert [p["text"] for k, p in events if k == "text_delta"] == ["ok"]
    assert len(waits) == 3 and all(base <= wait <= base * 1.2 for base, wait in zip([5, 10, 20], waits, strict=True))
    assert [p["round"] for k, p in events if k == "model_wait"] == [1, 2, 3]
    assert not any(k in ("status", "warning") for k, _ in events), "the stage keeps Wizard at work: no \"Gemini is busy\""


def test_no_capacity_through_every_attempt_says_whose_side_it_is(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={"gemini-3.8-flash": [CAPACITY] * code_assist.MAX_RETRIES})
    rt, req = make(tmp_path, fake, fallback="gemini-3.8-flash")
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert error.value.code == "model_capacity"
    assert error.value.message.startswith("Google has no capacity for gemini-3.8-flash right now. This is on Google's side")
    assert "Wizard kept trying for several minutes" in error.value.message and "model chip" not in error.value.message
    assert len(fake.models) == code_assist.MAX_RETRIES and len(waits) == code_assist.MAX_RETRIES - 1, "no wait after the last"


PRO = "gemini-3.1-pro-preview"
FLASH = "gemini-3.8-flash"


def call_turn(signature: str) -> list[dict]:
    return [{"functionCall": {"name": "nerp_run_report", "args": {"report_id": "r"}}, "thoughtSignature": signature}]


def test_pro_answers_only_the_step_flash_could_not(tmp_path, waits):
    # The owner, 30 Oct: Pro's quota was used up for the day while Flash was at 20 %. Flash had no room once, and the run
    # stayed on Pro for every step after it. Now Pro takes that step only, and the next step is Flash's again.
    fake = FakeGoogle([call_turn("sig-pro"), call_turn("sig-flash"), [{"text": "EG [E1]."}]],
                      refusals={FLASH: [FLASH_CAPACITY] * 3})
    rt, req = make(tmp_path, fake, fallback=PRO)
    events = run_and_collect(rt, req)
    assert fake.models == [FLASH] * 3 + [PRO] + [FLASH, FLASH], "one step on Pro, then back to Flash"
    assert waits == [1.0, 3.0], "Flash's two quick tries, then Pro, with no waiting"
    assert [p["model"] for k, p in events if k == "agent_session"] == [FLASH, PRO, FLASH]
    assert not any(k in ("warning", "status") for k, _ in events), "silent, as Gemini CLI"
    assert fake.requests[1]["model"] == FLASH and fake.requests[1]["request"]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "HIGH"}
    assert fake.requests[1]["request"]["contents"][1]["parts"][0]["thoughtSignature"] == "skip_thought_signature_validator"
    assert [p["text"] for k, p in events if k == "text_delta"] == ["EG [E1]."]


def test_a_run_on_pro_stays_only_while_google_asks_flash_to_wait_and_goes_back_when_pro_refuses(tmp_path, waits):
    # The owner's 22 Oct run: every step waited on Pro once Pro had no room. Flash asked for 23 s, so the next step is
    # still Pro's; Pro refuses, and after its two quick tries Flash takes the step back instead of a wait.
    later = google_error("MODEL_CAPACITY_EXHAUSTED", "No capacity available for model gemini-3.8-flash", delay="23s")
    fake = FakeGoogle([call_turn("sig-pro"), [{"text": "EG [E1]."}]],
                      refusals={FLASH: [later], PRO: [None] + [CAPACITY] * 3})
    rt, req = make(tmp_path, fake, fallback=PRO)
    events = run_and_collect(rt, req)
    assert fake.models == [FLASH, PRO] + [PRO] * 3 + [FLASH]
    assert waits == [1.0, 3.0], "quick tries only: no step waits while the other model can answer"
    assert [p["model"] for k, p in events if k == "agent_session"] == [FLASH, PRO, FLASH]
    assert not any(k in ("warning", "status") for k, _ in events)
    assert [p["text"] for k, p in events if k == "text_delta"] == ["EG [E1]."]


def test_when_both_models_refuse_wizard_waits_and_tries_both_again(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={FLASH: [FLASH_CAPACITY] * 4, PRO: [CAPACITY] * 4})
    rt, req = make(tmp_path, fake, fallback=PRO)
    events = run_and_collect(rt, req)
    assert fake.models == [FLASH] * 3 + [PRO] * 4 + [FLASH] * 2, "after each wait, one more try on each model"
    assert waits[:4] == [1.0, 3.0, 1.0, 3.0] and 5 <= waits[4] <= 6 and 10 <= waits[5] <= 12 and len(waits) == 6
    assert [(p["round"], p["models"]) for k, p in events if k == "model_wait"] == [(1, [FLASH, PRO]), (2, [FLASH, PRO])]
    assert not any(k in ("status", "warning") for k, _ in events), "nothing on the stage about Gemini waiting"
    assert [p["text"] for k, p in events if k == "text_delta"] == ["ok"]


def test_both_models_without_capacity_through_every_round_name_both(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={FLASH: [FLASH_CAPACITY] * 50, PRO: [CAPACITY] * 50})
    rt, req = make(tmp_path, fake, fallback=PRO)
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert error.value.code == "model_capacity"
    assert error.value.message.startswith(f"Google has no capacity for {FLASH} or {PRO} right now. This is on Google's side")
    assert len([w for w in waits if w >= 5]) == code_assist.MAX_RETRIES - 1, "no wait after the last round"


def test_a_long_wait_google_asks_for_goes_to_the_other_model_at_once(tmp_path, waits):
    later = google_error("MODEL_CAPACITY_EXHAUSTED", "No capacity available for model gemini-3.8-flash", delay="23s")
    fake = FakeGoogle([[{"text": "ok"}]], refusals={FLASH: [later]})
    rt, req = make(tmp_path, fake, fallback=PRO)
    run_and_collect(rt, req)
    assert fake.models == [FLASH, PRO] and waits == [], "no silent 23 s quick tries while Pro can answer"


def test_a_model_whose_quota_is_used_up_is_not_gone_back_to(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={FLASH: [google_error("QUOTA_EXHAUSTED", delay="7200s")], PRO: [CAPACITY]})
    rt, req = make(tmp_path, fake, fallback=PRO)
    events = run_and_collect(rt, req)
    assert fake.models == [FLASH, PRO, PRO], "Pro is the only model left, so it is waited for, without quick tries"
    assert len(waits) == 1 and 5 <= waits[0] <= 6
    statuses = [p["message"] for k, p in events if k == "status"]
    assert len(statuses) == 1 and "quota for gemini-3.8-flash is used up" in statuses[0], "the quota is told, the wait is not"
    assert [p["reason"] for k, p in events if k == "model_wait"] == ["capacity"]


# The owner's 30 Oct failure: "Google has no capacity for gemini-3.8-flash or gemini-3.1-pro-preview right now. This is on
# Google's side, not your quota. Google said: You have exhausted your capacity on this model. Your quota will reset after
# 30s." Pro's quota was used up for the day; Google words that as no capacity, with a 30 s wait.
EXHAUSTED = google_error(message="You have exhausted your capacity on this model. Your quota will reset after 30s.",
                         delay="30s")


def quota_numbers(pro_left: float) -> list[dict]:
    reset = (datetime.now(UTC) + timedelta(hours=9)).isoformat().replace("+00:00", "Z")
    return [{"modelId": FLASH, "tokenType": "REQUESTS", "remainingFraction": 0.8, "resetTime": reset},
            {"modelId": PRO, "tokenType": "REQUESTS", "remainingFraction": pro_left, "resetTime": reset}]


def test_a_used_up_quota_google_words_as_no_capacity_is_told_by_the_quota_numbers(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}], [{"text": "again"}]], refusals={FLASH: [EXHAUSTED] * 2, PRO: [EXHAUSTED]},
                      buckets=quota_numbers(pro_left=0.0))
    rt, req = make(tmp_path, fake, fallback=PRO)
    events = run_and_collect(rt, req)
    assert fake.models == [FLASH, PRO, FLASH, FLASH], "Pro, used up, is not waited on: only Flash is"
    assert len(waits) == 1 and 30 <= waits[0] <= 36, "Google's 30 s for Flash"
    assert [(p["reason"], p["models"]) for k, p in events if k == "model_wait"] == [("capacity", [FLASH])]
    [status] = [p["message"] for k, p in events if k == "status"]
    assert status.startswith(f"Your Gemini quota for {PRO} is used up (back in about 9 h). Wizard continues with {FLASH}.")
    assert fake.quota_checks == 1, "the numbers are read once, not at every refusal"
    # The next question does not turn to Pro either while its quota is used up.
    fake.refusals[FLASH] = [EXHAUSTED]
    run_and_collect(rt, req)
    assert fake.models[4:] == [FLASH, FLASH]


def test_flash_with_quota_left_is_still_googles_side_and_the_failure_names_pros_quota(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={FLASH: [EXHAUSTED] * 50, PRO: [EXHAUSTED] * 50},
                      buckets=quota_numbers(pro_left=0.0))
    rt, req = make(tmp_path, fake, fallback=PRO)
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert error.value.code == "model_capacity" and fake.models.count(PRO) == 1
    assert error.value.message.startswith(f"Google has no capacity for {FLASH} right now. This is on Google's side")
    assert f"Your quota for {PRO} is used up (back in about 9 h). Google said:" in error.value.message
    assert error.value.details["Models tried"] == f"{FLASH}, {PRO}"


def test_a_refusal_stands_when_the_quota_numbers_show_quota_left_or_cannot_be_read(tmp_path, waits):
    for buckets in (quota_numbers(pro_left=0.4), None):
        fake = FakeGoogle([[{"text": "ok"}]], refusals={FLASH: [EXHAUSTED], PRO: [EXHAUSTED]}, buckets=buckets)
        rt, req = make(tmp_path, fake, fallback=PRO)
        events = run_and_collect(rt, req)
        assert fake.models == [FLASH, PRO, PRO], "both kept as no capacity: after the wait, the run's model is asked again"
        assert [p["models"] for k, p in events if k == "model_wait"] == [[FLASH, PRO]]
        assert not any(k == "status" for k, _ in events)


def empty_turn(reason: str | None = "STOP", **extra) -> dict:
    """A turn with neither text nor a tool call, as Gemini 3 sends it: an empty text part carrying a thought signature."""
    candidate = {"content": {"role": "model", "parts": [{"text": "", "thoughtSignature": "sig"}]}, **extra}
    if reason:
        candidate["finishReason"] = reason
    return {"candidates": [candidate], "modelVersion": "gemini-3.8-flash-001",
            "usageMetadata": {"promptTokenCount": 182331, "thoughtsTokenCount": 1204, "candidatesTokenCount": 0}}


def test_an_empty_turn_is_asked_again_silently(tmp_path):
    # The owner's 23 Oct failure: "Wizard could not finish this answer. Gemini finished without an answer." Gemini CLI
    # treats a turn with neither text nor a tool call as an invalid stream and asks again; so does Wizard.
    fake = FakeGoogle([
        [{"functionCall": {"name": "nerp_run_report", "args": {"report_id": "r"}}}],
        empty_turn(),
        [{"text": "EG spent $1.5M [E1]."}],
    ])
    rt, req = make(tmp_path, fake, fallback=PRO)
    events = run_and_collect(rt, req)
    assert fake.models == [FLASH, FLASH, FLASH], "the same model is asked once more, with the same conversation"
    assert fake.requests[1]["request"]["contents"] == fake.requests[2]["request"]["contents"]
    assert not any(k in ("warning", "status") for k, _ in events)
    assert [p["text"] for k, p in events if k == "text_delta"] == ["EG spent $1.5M [E1]."]
    assert len(fake.requests[2]["request"]["contents"]) == 3, "the empty turn is not kept in the conversation"


def test_empty_turns_on_both_models_fail_with_what_google_sent_back(tmp_path):
    malformed = empty_turn("MALFORMED_FUNCTION_CALL", finishMessage="Malformed function call: print(wizard_query(...")
    fake = FakeGoogle([[{"functionCall": {"name": "nerp_run_report", "args": {"report_id": "r"}}}]] + [malformed] * 4)
    rt, req = make(tmp_path, fake, fallback=PRO)
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert fake.models == [FLASH, FLASH, FLASH, PRO, PRO], "twice on each model, then it stops"
    failure = error.value
    assert failure.code == "empty_answer"
    assert failure.message == ("Gemini sent back an empty turn 4 times in a row: no answer and no request for data. Google's "
                               "reason: Gemini wrote a tool call that could not be read (MALFORMED_FUNCTION_CALL).")
    assert failure.details["Google's finish reason"] == "Gemini wrote a tool call that could not be read (MALFORMED_FUNCTION_CALL)"
    assert failure.details["Google's message"] == "Malformed function call: print(wizard_query(..."
    assert failure.details["What Gemini sent back"] == "text (0 characters) + thoughtSignature"
    assert failure.details["Step"] == "2 (after 1 tool call)"
    assert failure.details["Tries"] == f"{FLASH} ×2, {PRO} ×2"
    assert failure.details["Tokens (last try)"] == "prompt 182,331 · thinking 1,204 · reply 0"
    assert failure.details["Model version"] == "gemini-3.8-flash-001"


def test_an_empty_turn_without_a_finish_reason_says_the_stream_was_cut(tmp_path):
    fake = FakeGoogle([empty_turn(None), {"candidates": []}])
    rt, req = make(tmp_path, fake)
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert error.value.code == "empty_answer" and "2 times in a row" in error.value.message
    assert "without a finish reason (the stream was cut off)" in error.value.message
    assert error.value.details["What Gemini sent back"] == "nothing: no text, no tool call"


def test_a_request_google_blocks_is_not_asked_again(tmp_path):
    blocked = {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT", "blockReasonMessage": "The prompt was blocked."}}
    fake = FakeGoogle([blocked, [{"text": "never"}]])
    rt, req = make(tmp_path, fake, fallback=PRO)
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert fake.models == [FLASH] and error.value.code == "model_blocked"
    assert error.value.details["Google blocked the request"] == "PROHIBITED_CONTENT: The prompt was blocked."


def test_a_request_google_rejects_says_what_google_said(tmp_path):
    def google(request: httpx.Request) -> httpx.Response:
        if ":streamGenerateContent" in str(request.url):
            return httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message":
                                                       "The input token count (1250000) exceeds the maximum (1048576)."}})
        return FakeGoogle([])(request)

    rt, req = make(tmp_path, google)  # type: ignore[arg-type]
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    assert error.value.code == "model_error"
    assert error.value.details["Google's reply"] == ("HTTP 400: The input token count (1250000) exceeds the maximum (1048576). "
                                                     "(INVALID_ARGUMENT)")


def test_running_out_of_capacity_keeps_googles_words_for_the_details(tmp_path, waits):
    fake = FakeGoogle([[{"text": "ok"}]], refusals={FLASH: [FLASH_CAPACITY] * 50, PRO: [CAPACITY] * 50})
    rt, req = make(tmp_path, fake, fallback=PRO)
    with pytest.raises(AgentFailure) as error:
        run_and_collect(rt, req)
    details = error.value.details
    assert details["Google's refusal"] == "no capacity for the model on Google's side (HTTP 429)"
    assert details["Google's message"].startswith("No capacity available for model") and details["Models tried"] == f"{FLASH}, {PRO}"
    assert details["Rounds"] == f"{code_assist.MAX_RETRIES} of {code_assist.MAX_RETRIES}, waiting between them"
