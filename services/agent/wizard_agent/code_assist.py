"""Code Assist runtime: the same agent loop over the Code Assist API that Gemini CLI uses, under the user's own sign-in.

This is the plan's per-user OAuth route (Step 02) for hosts where running isolated CLI processes is not approved.
Ported from Scribble's GeminiCodeAssistGateway (datap0nd/scribble 41ab532): project resolution via loadCodeAssist /
onboardUser with GOOGLE_CLOUD_PROJECT for enterprise tiers, SSE streamGenerateContent, function calling with thought
signatures echoed back, and Gemini CLI style 429 handling. Gemini still chooses every tool call; Wizard only executes
them through the same registry, rights checks and evidence capture as the MCP path.

Limits are read the way Gemini CLI reads them (packages/core/src/utils/googleQuotaErrors.ts): Google's error details
tell apart a model with no capacity on Google's side, a used-up (daily) quota, and a per-minute rate limit. Only the
last is worth waiting for. When the chosen model cannot answer, the rest of the run continues on the fallback model,
and the run says so."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from . import google_oauth, outbound
from .prompting import system_prompt
from .runtime import AgentFailure, AgentRequest, Emit, RuntimeKind, ToolBridge
from .secret_box import SecretBox

API_BASE = "https://cloudcode-pa.googleapis.com/v1internal"
# Model turns per run: a runaway backstop only. The run's time limit and Wizard's tool checks (runs.py) end a long run
# with an answer; this guards against a model that keeps calling tools after they refuse.
MAX_STEPS = 200
MAX_RETRIES = 6
CAPACITY_RETRIES = 2         # quick tries before leaving a model Google has no room for (Gemini CLI: 1 s, then 3 s)
MAX_RETRYABLE_DELAY_S = 300  # a longer suggested wait means the quota will not come back within the run
CAPACITY_REST_S = 600        # after leaving a model for lack of capacity, later questions start on the fallback
RETRY_STATUSES = (429, 499, 500, 502, 503, 504)
log = logging.getLogger("wizard.gemini")
sleep = asyncio.sleep  # one place to wait, so tests need not
KEEP_SCHEMA_KEYS = ("description", "enum", "required", "minItems", "maxItems", "minimum", "maximum")


def gemini_schema(node: Any) -> dict[str, Any]:
    """Reduce JSON Schema to the subset Gemini function declarations accept (types upper-case, no refs/unions)."""
    if not isinstance(node, dict):
        return {"type": "OBJECT"}
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        types = {o.get("type") for o in options}
        if len(types) == 1:
            merged = {**options[0], **{k: v for k, v in node.items() if k != "anyOf"}}
            return gemini_schema(merged)
        return {"type": "STRING", "description": (node.get("description", "") + " (number or text)").strip()}
    out: dict[str, Any] = {}
    kind = node.get("type", "object")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    out["type"] = str(kind).upper()
    for key in KEEP_SCHEMA_KEYS:
        if key in node:
            out[key] = node[key]
    if "properties" in node:
        out["properties"] = {name: gemini_schema(value) for name, value in node["properties"].items()}
    if "items" in node:
        out["items"] = gemini_schema(node["items"])
    return out


def thinking_config(model: str, level: str) -> dict[str, Any] | None:
    if level == "none":
        return None
    name = model.lower()
    if "gemini-2.5" in name:
        return {"thinkingBudget": -1 if level == "high" else 1024}
    return {"thinkingLevel": level.upper()}


@dataclass
class Limit:
    """Why Google refused a request: no room for the model on its side, the person's quota used up, a per-minute
    rate limit, or a busy server."""
    kind: Literal["capacity", "quota", "rate", "busy"]
    delay: float | None  # Google's suggested wait, in seconds
    detail: str          # Google's own message, for the log


def _seconds(text: str) -> float | None:
    match = re.fullmatch(r"\s*([0-9.]+)\s*(ms|s)\s*", text or "")
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value / 1000 if match.group(2) == "ms" else value


def classify_limit(status: int, body: str) -> Limit:
    """A 429 (or 499/5xx) the way Gemini CLI reads it, from google.rpc ErrorInfo, QuotaFailure and RetryInfo."""
    try:
        data: Any = json.loads(body)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        data = data[0] if data else None
    found = data.get("error") if isinstance(data, dict) else None
    error: dict[str, Any] = found if isinstance(found, dict) else {}
    message = str(error.get("message") or body or f"HTTP {status}").strip()[:500]
    details = [d for d in error.get("details") or [] if isinstance(d, dict)]

    def detail(kind: str) -> dict[str, Any]:
        return next((d for d in details if str(d.get("@type", "")).endswith(kind)), {})

    info, failure, retry = detail("google.rpc.ErrorInfo"), detail("google.rpc.QuotaFailure"), detail("google.rpc.RetryInfo")
    hint = re.search(r'"retryDelay"\s*:\s*"([0-9.]+m?s)"', body) or re.search(r"retry in ([0-9.]+m?s)", message, re.IGNORECASE)
    delay = _seconds(str(retry.get("retryDelay") or "")) or (_seconds(hint.group(1)) if hint else None)
    reason = str(info.get("reason") or "")
    quota_ids = [str(v.get("quotaId") or "") for v in failure.get("violations") or [] if isinstance(v, dict)]
    quota_ids.append(str((info.get("metadata") or {}).get("quota_limit") or ""))
    lower = message.lower()
    if reason in ("MODEL_CAPACITY_EXHAUSTED", "MODEL_CAPACITY_EXCEEDED") or re.search(
            r"exhausted your capacity|capacity exceeded|model_capacity_exhausted|no capacity available", lower):
        return Limit("capacity", delay, message)
    if status not in (429, 499, 503) and not delay:
        return Limit("busy", None, message)  # a server error: try again
    if (re.search(r"limit:\s*0(?!\d|\.\d)", lower) or reason in ("QUOTA_EXHAUSTED", "INSUFFICIENT_G1_CREDITS_BALANCE")
            or any("PerDay" in q or "Daily" in q for q in quota_ids) or (delay or 0) > MAX_RETRYABLE_DELAY_S
            or (reason == "RATE_LIMIT_EXCEEDED" and delay is None)):
        return Limit("quota", delay, message)
    if reason == "RATE_LIMIT_EXCEEDED" or any("PerMinute" in q for q in quota_ids):
        return Limit("rate", delay if delay is not None else 60.0, message)
    return Limit("busy", delay, message)


def retry_delay(hint: float | None, attempt: int) -> float:
    """At least Google's suggested wait; otherwise 5, 10, 20, 30 s (Gemini CLI), with up to 20 % jitter."""
    backoff = min(30.0, 5.0 * 2 ** attempt)
    return min(float(MAX_RETRYABLE_DELAY_S), max(backoff, hint or 0.0)) * (1 + 0.2 * random.random())  # noqa: S311 - jitter


def _about(seconds: float | None) -> str:
    if not seconds:
        return ""
    minutes = round(seconds / 60)
    if minutes < 1:
        return f" (back in about {seconds:.0f} s)"
    return f" (back in about {minutes} min)" if minutes < 90 else f" (back in about {minutes / 60:.0f} h)"


def limit_message(limit: Limit, model: str, fallback: str | None = None) -> str:
    """What the person reads when a model cannot answer, and what Wizard does about it."""
    then = f" Wizard continues with {fallback}." if fallback else ""
    if limit.kind == "capacity":
        return (f"Google has no capacity for {model} right now. This is on Google's side, not your quota."
                + (then or " Try again in a few minutes, or pick another model in the model chip."))
    if limit.kind == "quota":
        return (f"Your Gemini quota for {model} is used up{_about(limit.delay)}."
                + (then or " Pick another model in the model chip."))
    return (f"Gemini kept refusing requests for {model} ({'per-minute limit' if limit.kind == 'rate' else 'busy'})."
            + (then or " Try again in a few minutes."))


class _Unavailable(Exception):
    """The run's model cannot answer now; the run may continue on the fallback model."""

    def __init__(self, limit: Limit):
        super().__init__(limit.kind)
        self.limit = limit


def summarize_quota(raw: dict[str, Any], model: str) -> dict[str, Any]:
    """retrieveUserQuota buckets -> what the UI shows. The selected bucket is the configured model's most constraining one
    (a model can have several, e.g. requests and tokens); a model variant such as `<model>-preview` also matches."""
    buckets: list[dict[str, Any]] = []
    for bucket in raw.get("buckets") or []:
        if not isinstance(bucket, dict) or bucket.get("remainingFraction") is None:
            continue
        fraction = max(0.0, min(1.0, float(bucket["remainingFraction"])))
        amount = str(bucket.get("remainingAmount") or "")
        remaining = int(amount) if amount.isdigit() else None
        limit = round(remaining / fraction) if remaining is not None and fraction > 0 else None
        buckets.append({"model_id": str(bucket.get("modelId") or ""), "token_type": bucket.get("tokenType"),
                        "remaining_fraction": fraction, "used_fraction": round(1 - fraction, 4), "remaining": remaining,
                        "limit": limit, "reset_time": bucket.get("resetTime")})
    exact = [b for b in buckets if b["model_id"] == model]
    related = exact or [b for b in buckets if b["model_id"] and (b["model_id"].startswith(model) or model.startswith(b["model_id"]))]
    selected = min(related, key=lambda b: b["remaining_fraction"]) if related else None
    return {"model": model, "selected": selected, "buckets": buckets}


class CodeAssistRuntime:
    kind: RuntimeKind = "code-assist"

    def __init__(self, model: str, secret_box: SecretBox, project: str | None = None, thinking: str = "high",
                 api_base: str = API_BASE, transport: httpx.AsyncBaseTransport | None = None, proxy: str | None = None,
                 fallback_model: str | None = None):
        self.model = model
        self.fallback_model = fallback_model
        self._resting: dict[str, tuple[float, Limit]] = {}  # model -> (until, why): later runs start on the fallback
        self.proxy = proxy
        self.secret_box = secret_box
        self.project_override = project
        self.thinking = thinking
        self.api_base = api_base
        self.transport = transport
        self._projects: dict[str, str] = {}

    def label(self) -> str:
        return f"Gemini Code Assist API · {self.model}"

    @staticmethod
    def token_path(user_home: Path) -> Path:
        return user_home / "secrets" / "google_refresh_token.bin"

    async def readiness(self, user_home: Path, user_email: str) -> dict[str, Any]:
        if self.secret_box.read(self.token_path(user_home)) is None:
            return {"ready": False, "reason": "Link your own Gemini account to ask questions."}
        return {"ready": True, "reason": None}

    def _http(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(180.0, connect=20.0)
        if self.transport:
            return httpx.AsyncClient(timeout=timeout, transport=self.transport)
        return outbound.client(self.api_base, override=self.proxy, timeout=timeout)

    async def _access_token(self, http: httpx.AsyncClient, request: AgentRequest) -> str:
        return await self._access_token_for(http, request.user_home)

    async def _access_token_for(self, http: httpx.AsyncClient, user_home: Path) -> str:
        refresh_token = self.secret_box.read(self.token_path(user_home))
        if not refresh_token:
            raise AgentFailure("gemini_signin_required", "Link your own Gemini account before asking questions.")
        try:
            return (await google_oauth.refresh(http, refresh_token)).access_token
        except google_oauth.OAuthError as error:
            raise AgentFailure("gemini_signin_required", error.message) from None

    async def _post(self, http: httpx.AsyncClient, token: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await http.post(f"{self.api_base}:{method}", json=body, headers={"Authorization": f"Bearer {token}"})
        if response.status_code in (401, 403):
            raise AgentFailure("model_permission_denied", "Gemini refused the request for your account (check your "
                                                          "Gemini entitlement and Google Cloud project).")
        if response.status_code >= 400:
            raise AgentFailure("model_error", f"Gemini {method} failed ({response.status_code}).")
        return dict(response.json())

    async def quota(self, user_home: Path, user_id: str) -> dict[str, Any]:
        """Gemini CLI's retrieveUserQuota for this person, under their own sign-in and project: per-model buckets with
        remainingFraction, optional remainingAmount and resetTime. Read-only: never onboards an account."""
        try:
            async with self._http() as http:
                token = await self._access_token_for(http, user_home)
                project = await self.resolve_project(http, token, user_id, onboard=False)
                return await self._post(http, token, "retrieveUserQuota", {"project": project})
        except httpx.HTTPError as error:
            raise AgentFailure("network_error", outbound.explain(error, self.api_base, self.proxy)) from None

    async def resolve_project(self, http: httpx.AsyncClient, token: str, user_id: str, onboard: bool = True) -> str:
        """Mirror Gemini CLI: an onboarded account uses loadCodeAssist's project or GOOGLE_CLOUD_PROJECT; a new account is
        onboarded once. Never call generateContent with an empty project (Google answers with an opaque HTTP 500)."""
        if user_id in self._projects:
            return self._projects[user_id]
        configured = (self.project_override or "").strip()
        metadata: dict[str, Any] = {"ideType": "IDE_UNSPECIFIED", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}
        if configured:
            metadata["duetProject"] = configured
        body: dict[str, Any] = {"metadata": metadata}
        if configured:
            body["cloudaicompanionProject"] = configured
        load = await self._post(http, token, "loadCodeAssist", body)
        project = str(load.get("cloudaicompanionProject") or "")
        if isinstance(load.get("currentTier"), dict):
            resolved = project or configured
        elif not onboard:
            resolved = configured
        else:
            tier = next((t.get("id") for t in load.get("allowedTiers", []) if t.get("isDefault")), "free-tier")
            onboarding = {**body, "tierId": tier}
            operation = await self._post(http, token, "onboardUser", onboarding)
            for _ in range(15):
                if operation.get("done") or not operation.get("name"):
                    break
                await asyncio.sleep(2)
                response = await http.get(f"{self.api_base}/{operation['name']}", headers={"Authorization": f"Bearer {token}"})
                operation = response.json() if response.status_code == 200 else operation
            value = (operation.get("response") or {}).get("cloudaicompanionProject")
            resolved = (value.get("id") if isinstance(value, dict) else value) or configured
        if not resolved:
            raise AgentFailure("gemini_project_unresolved", "Google did not provide a Gemini project for this account. Set "
                                                            "GOOGLE_CLOUD_PROJECT to your organisation's Gemini project.")
        self._projects[user_id] = resolved
        return resolved

    async def _stream(self, http: httpx.AsyncClient, token: str, envelope: dict[str, Any], emit: Emit
                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        model = str(envelope["model"])
        dropped_thinking = False
        capacity_tries = 0
        limit = Limit("busy", None, "")
        for attempt in range(MAX_RETRIES):
            parts: list[dict[str, Any]] = []
            calls: list[dict[str, Any]] = []
            usage: dict[str, Any] = {}
            async with http.stream("POST", f"{self.api_base}:streamGenerateContent", params={"alt": "sse"}, json=envelope,
                                   headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}) as response:
                if response.status_code in RETRY_STATUSES:
                    body = (await response.aread()).decode("utf-8", "replace")
                    limit = classify_limit(response.status_code, body)
                    log.warning("Gemini refused a request for %s: %s (HTTP %s): %s", model, limit.kind,
                                response.status_code, limit.detail[:300])
                    if limit.kind == "quota":
                        raise _Unavailable(limit)
                    if limit.kind == "capacity":
                        capacity_tries += 1
                        if capacity_tries > CAPACITY_RETRIES:
                            raise _Unavailable(limit)
                        delay = limit.delay if limit.delay is not None else (1.0 if capacity_tries == 1 else 3.0)
                        message = f"Google has no capacity for {model} right now; trying again in {delay:.0f} s."
                    else:
                        delay = retry_delay(limit.delay, attempt)
                        message = (f"Gemini's per-minute limit for {model} was reached; waiting {delay:.0f} s"
                                   if limit.kind == "rate" else f"Gemini is busy; trying again in {delay:.0f} s")
                        message += f" (attempt {attempt + 1} of {MAX_RETRIES})."
                    await emit("status", {"message": message})
                    await sleep(delay)
                    continue
                if response.status_code == 400 and not dropped_thinking and "thinking" in (await response.aread()).decode(
                        "utf-8", "replace").lower():
                    envelope["request"].get("generationConfig", {}).pop("thinkingConfig", None)
                    dropped_thinking = True
                    await emit("warning", {"message": "The model rejected the thinking setting; retried with its default."})
                    continue
                if response.status_code in (401, 403):
                    raise AgentFailure("model_permission_denied", "Gemini refused the request for your account.")
                if response.status_code >= 400:
                    raise AgentFailure("model_error", f"Gemini streamGenerateContent failed ({response.status_code}).")
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                        continue
                    if line.strip() == "" and data_lines:
                        await self._consume("\n".join(data_lines), parts, calls, usage, emit)
                        data_lines = []
                if data_lines:
                    await self._consume("\n".join(data_lines), parts, calls, usage, emit)
            return parts, calls, usage
        raise _Unavailable(limit)

    def _start_model(self) -> tuple[str, Limit | None]:
        """The chosen model, unless it was left for the fallback a short while ago (then the fallback, and why)."""
        resting = self._resting.get(self.model)
        if resting and resting[0] > time.monotonic() and self.fallback_model and self.fallback_model != self.model:
            return self.fallback_model, resting[1]
        self._resting.pop(self.model, None)
        return self.model, None

    @staticmethod
    async def _consume(payload: str, parts: list[dict[str, Any]], calls: list[dict[str, Any]], usage: dict[str, Any],
                       emit: Emit) -> None:
        try:
            root = json.loads(payload)
        except json.JSONDecodeError:
            return
        inner = root.get("response", root)
        usage.update(inner.get("usageMetadata") or {})
        candidates = inner.get("candidates") or []
        content = (candidates[0].get("content") if candidates else None) or {}
        for part in content.get("parts") or []:
            if part.get("thought") is True:
                continue
            parts.append(part)
            if isinstance(part.get("text"), str) and part["text"]:
                await emit("text_delta", {"text": part["text"], "delta": True})
            if isinstance(part.get("functionCall"), dict):
                calls.append(part["functionCall"])

    def _generation(self, model: str) -> dict[str, Any]:
        thinking = thinking_config(model, self.thinking)
        return {"thinkingConfig": thinking} if thinking else {}

    async def run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        try:
            await self._run(request, emit, tools, cancelled)
        except httpx.HTTPError as error:
            raise AgentFailure("network_error", outbound.explain(error, self.api_base, self.proxy)) from None

    async def _run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        async with self._http() as http:
            token = await self._access_token(http, request)
            project = await self.resolve_project(http, token, request.user_id)
            chosen = self.model  # the model picker may change self.model; a run keeps the one it started with
            model, rested = self._start_model()
            await emit("agent_session", {"session_id": request.run_id, "model": model, "project": project})
            if rested:
                await emit("warning", {"message": limit_message(rested, chosen, model).replace(" continues ", " answers ")})
            declarations = [{"name": t["name"], "description": t["description"], "parameters": gemini_schema(t["inputSchema"])}
                            for t in tools.describe()]
            generation = self._generation(model)
            contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": request.prompt}]}]
            totals = {"tool_calls": 0, "input_tokens": 0, "output_tokens": 0}
            for _ in range(MAX_STEPS):
                if cancelled():
                    raise AgentFailure("cancelled", "The run was cancelled.")
                envelope = {"model": model, "project": project, "user_prompt_id": request.run_id, "request": {
                    "contents": contents,
                    "systemInstruction": {"role": "user", "parts": [{"text": system_prompt()}]},
                    "tools": [{"functionDeclarations": declarations}],
                    "generationConfig": generation}}
                try:
                    parts, calls, usage = await self._stream(http, token, envelope, emit)
                except _Unavailable as unavailable:
                    fallback = self.fallback_model
                    if not fallback or fallback == model:
                        raise AgentFailure("model_quota" if unavailable.limit.kind == "quota" else "model_capacity",
                                           limit_message(unavailable.limit, model)) from None
                    if model == chosen:
                        rest = (unavailable.limit.delay or 3600) if unavailable.limit.kind == "quota" else CAPACITY_REST_S
                        self._resting[chosen] = (time.monotonic() + min(rest, 6 * 3600), unavailable.limit)
                    await emit("warning", {"message": limit_message(unavailable.limit, model, fallback)})
                    model = fallback
                    generation = self._generation(model)
                    _skip_signatures(contents)
                    await emit("agent_session", {"session_id": request.run_id, "model": model, "project": project})
                    continue
                totals["input_tokens"] += int(usage.get("promptTokenCount", 0))
                totals["output_tokens"] += int(usage.get("candidatesTokenCount", 0))
                if not parts:
                    raise AgentFailure("model_error", "Gemini returned neither text nor a tool call.")
                contents.append({"role": "model", "parts": parts})
                if not calls:
                    await emit("agent_stats", {"stats": totals})
                    return
                responses = []
                for call in calls:
                    totals["tool_calls"] += 1
                    ok, text = await tools.call(str(call.get("name")), dict(call.get("args") or {}))
                    payload = json.loads(text)
                    responses.append({"functionResponse": {"name": call.get("name"),
                                                           "response": payload if ok else {"error": payload.get("error")}}})
                contents.append({"role": "user", "parts": responses})
            raise AgentFailure("too_many_steps", f"Gemini used more than {MAX_STEPS} steps without finishing.")


def _skip_signatures(contents: list[dict[str, Any]]) -> None:
    """Thought signatures belong to the model that wrote them. After switching models, earlier turns carry Google's
    documented placeholder instead, so the new model does not reject them."""
    for turn in contents:
        for part in turn.get("parts") or []:
            if isinstance(part, dict) and "thoughtSignature" in part:
                part["thoughtSignature"] = "skip_thought_signature_validator"
