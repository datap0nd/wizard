"""Code Assist runtime: the same agent loop over the Code Assist API that Gemini CLI uses, under the user's own sign-in.

This is the plan's per-user OAuth route (Step 02) for hosts where running isolated CLI processes is not approved.
Ported from Scribble's GeminiCodeAssistGateway (datap0nd/scribble 41ab532): project resolution via loadCodeAssist /
onboardUser with GOOGLE_CLOUD_PROJECT for enterprise tiers, SSE streamGenerateContent, function calling with thought
signatures echoed back, and Gemini CLI style 429 handling. Gemini still chooses every tool call; Wizard only executes
them through the same registry, rights checks and evidence capture as the MCP path.

Limits are read the way Gemini CLI reads them (packages/core/src/utils/googleQuotaErrors.ts): Google's error details
tell apart a model with no capacity on Google's side, a used-up (daily) quota, and a per-minute rate limit. A used-up
quota is not waited for. When the model a run is on cannot answer, the other one (the chosen model or the fallback)
takes the step and the run stays on it, as Gemini CLI does (within Gemini 3, Flash and Pro stand in for each other).
It goes both ways: a run that moved to Pro goes back to Flash when Pro refuses. Like the CLI's default (errorVerbosity
low), a lack of capacity that Wizard handles is not shown: the quick tries and the switches go to the log only, and the
run records the model that answered. Only when both models have refused (or there is no other) does Wizard wait, like
for a busy server (Google's capacity usually comes back within a minute or two). The wait is not shown either (owner, 23
October: people see Wizard working through the data, not Gemini being busy): it goes to the log and, as a `model_wait`
event, into Error details. The person reads "no capacity" only when an answer stops for it.

A turn with neither text nor a tool call is what Gemini CLI calls an invalid stream, and it asks again. Wizard asks the
same model once more, then the other model twice, before it gives up; then the failure carries what Google sent back
(its finish reason and message, the parts, the tokens) for the run card's Error details."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
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
MAX_RETRIES = 10             # Gemini CLI's DEFAULT_MAX_ATTEMPTS: with 5-30 s backoff, about 4 minutes in all
CAPACITY_RETRIES = 2         # quick tries before leaving a model Google has no room for (Gemini CLI: 1 s, then 3 s)
QUICK_TRY_S = 3.0            # the longest quick try; a longer wait Google asks for goes to the other model instead
MAX_RETRYABLE_DELAY_S = 300  # a longer suggested wait means the quota will not come back within the run
RETRY_STATUSES = (429, 499, 500, 502, 503, 504)
EMPTY_TRIES = 2              # tries per model for a turn with neither text nor a tool call (Gemini CLI asks again once)
# Google's finishReason for a turn that ended, in words (google.genai FinishReason).
FINISH_REASONS = {
    "STOP": "a normal stop, with nothing written",
    "MAX_TOKENS": "the output limit was reached, spent on thinking, before anything was written",
    "SAFETY": "Google's safety filter withheld the reply",
    "RECITATION": "Google withheld the reply because it repeated published text",
    "LANGUAGE": "the reply was in a language Gemini does not support",
    "BLOCKLIST": "Google withheld the reply because it contained a blocked term",
    "PROHIBITED_CONTENT": "Google withheld the reply as prohibited content",
    "SPII": "Google withheld the reply because it contained sensitive personal information",
    "MALFORMED_FUNCTION_CALL": "Gemini wrote a tool call that could not be read",
    "UNEXPECTED_TOOL_CALL": "Gemini asked for a tool it was not offered",
    "TOO_MANY_TOOL_CALLS": "Gemini asked for too many tools in one turn",
    "OTHER": "none given",
}
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
    status: int = 0      # the HTTP status Google answered with


@dataclass
class Reply:
    """One model turn as Google sent it: the parts kept for the conversation, the tool calls, token usage and why the
    turn ended (finishReason, finishMessage, promptFeedback's blockReason...)."""
    parts: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    finish: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """Neither words nor a tool call: nothing to show and nothing to do."""
        return not self.calls and not any(str(p.get("text") or "").strip() for p in self.parts)


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
        return Limit("capacity", delay, message, status)
    if status not in (429, 499, 503) and not delay:
        return Limit("busy", None, message, status)  # a server error: try again
    if (re.search(r"limit:\s*0(?!\d|\.\d)", lower) or reason in ("QUOTA_EXHAUSTED", "INSUFFICIENT_G1_CREDITS_BALANCE")
            or any("PerDay" in q or "Daily" in q for q in quota_ids) or (delay or 0) > MAX_RETRYABLE_DELAY_S
            or (reason == "RATE_LIMIT_EXCEEDED" and delay is None)):
        return Limit("quota", delay, message, status)
    if reason == "RATE_LIMIT_EXCEEDED" or any("PerMinute" in q for q in quota_ids):
        return Limit("rate", delay if delay is not None else 60.0, message, status)
    return Limit("busy", delay, message, status)


def google_message(status: int, body: str) -> str:
    """Google's own words from an error response, for Error details: its message and status, else the body itself."""
    try:
        data: Any = json.loads(body)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        data = data[0] if data else None
    error = data.get("error") if isinstance(data, dict) else None
    text = str(error.get("message") or "") if isinstance(error, dict) else ""
    if text and isinstance(error, dict) and error.get("status"):
        text += f" ({error['status']})"
    return f"HTTP {status}: " + (" ".join((text or body).split())[:1000] or "no message")


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


def google_says(limit: Limit) -> str:
    """Google's own words, short and on one line, so the person (and whoever helps them) sees the real reason."""
    text = " ".join(limit.detail.split())
    if not text or text.startswith(("HTTP ", "{", "[")):
        return ""
    return f' Google said: "{text[:177] + "..." if len(text) > 180 else text}"'


def limit_message(limit: Limit, model: str, fallback: str | None = None) -> str:
    """What the person reads when a model cannot answer, and what Wizard does about it."""
    then = f" Wizard continues with {fallback}." if fallback else ""
    if limit.kind == "capacity":
        text = (f"Google has no capacity for {model} right now. This is on Google's side, not your quota."
                + (then or " Wizard kept trying for several minutes; try again a little later."))
    elif limit.kind == "quota":
        text = (f"Your Gemini quota for {model} is used up{_about(limit.delay)}."
                + (then or " Try again once it resets."))
    else:
        text = (f"Gemini kept refusing requests for {model} ({'per-minute limit' if limit.kind == 'rate' else 'busy'})."
                + (then or " Try again in a few minutes."))
    return text + google_says(limit)


LIMIT_KINDS = {"capacity": "no capacity for the model on Google's side", "quota": "your quota is used up",
               "rate": "per-minute limit reached", "busy": "Google's server was busy or failed"}


def limit_details(limit: Limit, tried: list[str], rounds: int | None = None) -> dict[str, str]:
    """Error details for a model Google would not let answer."""
    details = {"Google's refusal": f"{LIMIT_KINDS[limit.kind]} (HTTP {limit.status or '?'})",
               "Google's message": limit.detail or "none", "Models tried": ", ".join(tried)}
    if limit.delay:
        details["Google's suggested wait"] = f"{limit.delay:.0f} s"
    if rounds is not None:
        details["Rounds"] = f"{rounds} of {MAX_RETRIES}, waiting between them"
    return details


def finish_words(finish: dict[str, str]) -> str:
    reason = finish.get("finishReason")
    if not reason:
        return "none: the reply ended without a finish reason (the stream was cut off)"
    return f"{FINISH_REASONS.get(reason, 'not one Wizard knows')} ({reason})"


def describe_parts(parts: list[dict[str, Any]]) -> str:
    """What a turn held, without its content: 'text (0 characters) + thoughtSignature'."""
    if not parts:
        return "nothing: no text, no tool call"
    shown = []
    for part in parts:
        keys = [f"text ({len(str(part.get('text') or '').strip())} characters)" if key == "text" else key for key in part]
        shown.append(" + ".join(keys) or "an empty part")
    return "; ".join(shown)


def turn_details(reply: Reply, step: int, tool_calls: int, tries: list[str]) -> dict[str, str]:
    """Error details for a turn that ended with nothing: Google's reason and words, what the turn held, the tokens."""
    finish, usage = reply.finish, reply.usage
    details = {"Google's finish reason": finish_words(finish)}
    if finish.get("finishMessage"):
        details["Google's message"] = finish["finishMessage"][:1000]
    if finish.get("blockReason"):
        details["Google blocked the request"] = finish["blockReason"] + (f": {finish['blockReasonMessage']}"
                                                                         if finish.get("blockReasonMessage") else "")
    if finish.get("blockedCategories"):
        details["Safety categories"] = finish["blockedCategories"]
    details["What Gemini sent back"] = describe_parts(reply.parts)
    details["Step"] = f"{step} (after {tool_calls} tool call{'s' if tool_calls != 1 else ''})"
    details["Tries"] = ", ".join(f"{model} ×{tries.count(model)}" for model in dict.fromkeys(tries))
    if usage:
        details["Tokens (last try)"] = (f"prompt {int(usage.get('promptTokenCount', 0)):,} · thinking "
                                        f"{int(usage.get('thoughtsTokenCount', 0)):,} · reply {int(usage.get('candidatesTokenCount', 0)):,}")
    if finish.get("modelVersion"):
        details["Model version"] = finish["modelVersion"]
    return details


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
        said = {"Google's reply": google_message(response.status_code, response.text), "Request": method}
        if response.status_code in (401, 403):
            raise AgentFailure("model_permission_denied", "Gemini refused the request for your account (check your "
                                                          "Gemini entitlement and Google Cloud project).", said)
        if response.status_code >= 400:
            raise AgentFailure("model_error", f"Gemini {method} failed ({response.status_code}).", said)
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

    async def _request(self, http: httpx.AsyncClient, token: str, envelope: dict[str, Any], emit: Emit) -> Reply | Limit:
        """One model turn as Google sent it, or Google's refusal to act on."""
        model = str(envelope["model"])
        dropped_thinking = False
        while True:
            reply = Reply()
            async with http.stream("POST", f"{self.api_base}:streamGenerateContent", params={"alt": "sse"}, json=envelope,
                                   headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}) as response:
                if response.status_code in RETRY_STATUSES:
                    body = (await response.aread()).decode("utf-8", "replace")
                    limit = classify_limit(response.status_code, body)
                    log.warning("Gemini refused a request for %s: %s (HTTP %s): %s", model, limit.kind,
                                response.status_code, limit.detail[:300])
                    return limit
                if response.status_code == 400 and not dropped_thinking and "thinking" in (await response.aread()).decode(
                        "utf-8", "replace").lower():
                    envelope["request"].get("generationConfig", {}).pop("thinkingConfig", None)
                    dropped_thinking = True
                    await emit("warning", {"message": "The model rejected the thinking setting; retried with its default."})
                    continue
                if response.status_code >= 400:
                    said = {"Google's reply": google_message(response.status_code, (await response.aread()).decode(
                        "utf-8", "replace")), "Model": model}
                    if response.status_code in (401, 403):
                        raise AgentFailure("model_permission_denied", "Gemini refused the request for your account.", said)
                    raise AgentFailure("model_error", f"Gemini streamGenerateContent failed ({response.status_code}).", said)
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                        continue
                    if line.strip() == "" and data_lines:
                        await self._consume("\n".join(data_lines), reply, emit)
                        data_lines = []
                if data_lines:
                    await self._consume("\n".join(data_lines), reply, emit)
            return reply

    async def _step(self, http: httpx.AsyncClient, token: str, run: _Models, contents: list[dict[str, Any]], emit: Emit
                    ) -> Reply:
        """One step of the run, answered by whichever of the two models (the chosen one and the fallback) can.

        A model Google has no room for gets Gemini CLI's two quick tries; then the other model takes the step, silently,
        and the run stays on it. So a run that moved to Pro goes back to Flash as soon as Pro refuses, instead of
        waiting on Pro at every step. Wizard waits (5 to 30 s, not shown) only once both have refused, and then tries
        both again after each wait, up to MAX_RETRIES rounds. A used-up quota is not waited for."""
        quick: dict[str, int] = {}
        refused: list[str] = []  # models that refused since the last wait
        tried: list[str] = []    # every model that refused in this step, for the failure message
        waits = 0
        while True:
            result = await self._request(http, token, run.envelope(contents), emit)
            if not isinstance(result, Limit):
                return result
            limit, model = result, run.model
            tried = list(dict.fromkeys([*tried, model]))
            other = run.other(self._resting)
            if limit.kind == "quota":
                self._resting[model] = (time.monotonic() + min(limit.delay or 3600, 6 * 3600), limit)
                if other is None:
                    raise AgentFailure("model_quota", limit_message(limit, model), limit_details(limit, tried))
                await emit("status", {"message": limit_message(limit, model, other)})
                await run.switch(other, contents, emit, limit_message(limit, model, other))
                continue
            if (limit.kind == "capacity" and other and quick.get(model, 0) < CAPACITY_RETRIES
                    and (limit.delay or 0) <= QUICK_TRY_S):  # Google asking for longer: the other model takes over now
                quick[model] = quick.get(model, 0) + 1
                # Gemini CLI's quick tries before the other model takes over: seconds, so the person is not told.
                await sleep(limit.delay if limit.delay is not None else (1.0 if quick[model] == 1 else QUICK_TRY_S))
                continue
            refused.append(model)
            if other and other not in refused:
                await run.switch(other, contents, emit, limit_message(limit, model, other))  # as Gemini CLI, silent
                continue
            if waits + 1 >= MAX_RETRIES:  # no wait after the last round
                raise AgentFailure("model_capacity", limit_message(limit, " or ".join(tried)),
                                   limit_details(limit, tried, waits + 1))
            delay = retry_delay(limit.delay, waits)
            # Not a status line: the stage keeps Wizard at work. The log and Error details keep the wait.
            log.info("run %s: waiting %.0f s for Gemini (%s for %s, round %d of %d)", run.request.run_id, delay, limit.kind,
                     " and ".join(tried), waits + 1, MAX_RETRIES)
            await emit("model_wait", {"seconds": round(delay, 1), "reason": limit.kind, "models": tried, "round": waits + 1})
            await sleep(delay)
            waits += 1
            refused.clear()

    def _start_model(self) -> tuple[str, Limit | None]:
        """The chosen model, unless its quota was used up a short while ago (then the fallback, and why). Google's lack of
        capacity is not remembered: each question starts on the chosen model, and costs at most two quick tries."""
        resting = self._resting.get(self.model)
        fallback = self.fallback_model
        if resting and resting[0] > time.monotonic() and fallback and fallback != self.model:
            spare = self._resting.get(fallback)
            if not spare or spare[0] <= time.monotonic():
                return fallback, resting[1]
        if resting and resting[0] <= time.monotonic():
            self._resting.pop(self.model, None)
        return self.model, None

    @staticmethod
    async def _consume(payload: str, reply: Reply, emit: Emit) -> None:
        try:
            root = json.loads(payload)
        except json.JSONDecodeError:
            return
        inner = root.get("response", root)
        reply.usage.update(inner.get("usageMetadata") or {})
        feedback = inner.get("promptFeedback") or {}
        candidates = inner.get("candidates") or []
        candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        for key, value in (("blockReason", feedback.get("blockReason")), ("blockReasonMessage", feedback.get("blockReasonMessage")),
                           ("finishReason", candidate.get("finishReason")), ("finishMessage", candidate.get("finishMessage")),
                           ("modelVersion", inner.get("modelVersion"))):
            if value:
                reply.finish[key] = str(value)
        blocked = [str(r.get("category")) for r in candidate.get("safetyRatings") or [] if isinstance(r, dict) and r.get("blocked")]
        if blocked:
            reply.finish["blockedCategories"] = ", ".join(blocked)
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("thought") is True:
                continue
            reply.parts.append(part)
            if isinstance(part.get("text"), str) and part["text"]:
                await emit("text_delta", {"text": part["text"], "delta": True})
            if isinstance(part.get("functionCall"), dict):
                reply.calls.append(part["functionCall"])

    def _generation(self, model: str) -> dict[str, Any]:
        thinking = thinking_config(model, self.thinking)
        return {"thinkingConfig": thinking} if thinking else {}

    async def run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        try:
            await self._run(request, emit, tools, cancelled)
        except httpx.HTTPError as error:
            raise AgentFailure("network_error", outbound.explain(error, self.api_base, self.proxy),
                               {"Network error": f"{type(error).__name__}: {error}"[:1000]}) from None

    async def _run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        async with self._http() as http:
            token = await self._access_token(http, request)
            project = await self.resolve_project(http, token, request.user_id)
            chosen = self.model  # the model picker may change self.model; a run keeps the one it started with
            model, rested = self._start_model()
            await emit("agent_session", {"session_id": request.run_id, "model": model, "project": project})
            if rested:  # a used-up quota is the person's to know; Google's capacity is not
                await emit("status", {"message": limit_message(rested, chosen, model).replace(" continues ", " answers ")})
            declarations = [{"name": t["name"], "description": t["description"], "parameters": gemini_schema(t["inputSchema"])}
                            for t in tools.describe()]
            run = _Models(self, request, project, chosen, self.fallback_model, model, declarations)
            contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": request.prompt}]}]
            totals = {"tool_calls": 0, "input_tokens": 0, "output_tokens": 0}
            for step in range(1, MAX_STEPS + 1):
                if cancelled():
                    raise AgentFailure("cancelled", "The run was cancelled.")
                reply = await self._step(http, token, run, contents, emit)
                tries = [run.model]
                while reply.empty:
                    reply = await self._again(http, token, run, contents, emit, reply, tries, step, totals, cancelled)
                totals["input_tokens"] += int(reply.usage.get("promptTokenCount", 0))
                totals["output_tokens"] += int(reply.usage.get("candidatesTokenCount", 0))
                log.info("run %s step %d on %s: %s prompt tokens, %d tool call(s)", request.run_id, step, run.model,
                         reply.usage.get("promptTokenCount", "?"), len(reply.calls))
                contents.append({"role": "model", "parts": reply.parts})
                if not reply.calls:
                    await emit("agent_stats", {"stats": totals})
                    return
                responses = []
                for call in reply.calls:
                    totals["tool_calls"] += 1
                    ok, text = await tools.call(str(call.get("name")), dict(call.get("args") or {}))
                    payload = json.loads(text)
                    responses.append({"functionResponse": {"name": call.get("name"),
                                                           "response": payload if ok else {"error": payload.get("error")}}})
                contents.append({"role": "user", "parts": responses})
            raise AgentFailure("too_many_steps", f"Gemini used more than {MAX_STEPS} steps without finishing.")

    async def _again(self, http: httpx.AsyncClient, token: str, run: _Models, contents: list[dict[str, Any]], emit: Emit,
                     reply: Reply, tries: list[str], step: int, totals: dict[str, int], cancelled: Any) -> Reply:
        """A turn came back with neither text nor a tool call. Ask the same model once more and then the other model
        (Gemini CLI asks again too), silently; a request Google blocked, or every try empty, fails with what Google said."""
        details = turn_details(reply, step, totals["tool_calls"], tries)
        if reply.finish.get("blockReason"):
            raise AgentFailure("model_blocked", f"Google blocked the request at step {step} before Gemini could answer "
                                                f"({reply.finish['blockReason']}).", details)
        if cancelled():
            raise AgentFailure("cancelled", "The run was cancelled.")
        log.warning("run %s step %d on %s: a turn with neither text nor a tool call (%s; %s)", run.request.run_id, step,
                    run.model, finish_words(reply.finish), describe_parts(reply.parts))
        if tries.count(run.model) >= EMPTY_TRIES:
            other = run.other(self._resting)
            if other is None or other in tries:
                raise AgentFailure("empty_answer", f"Gemini sent back an empty turn {len(tries)} times in a row: no answer "
                                                   f"and no request for data. Google's reason: {finish_words(reply.finish)}.",
                                   details)
            await run.switch(other, contents, emit, f"{run.model} sent back nothing {EMPTY_TRIES} times")
        again = await self._step(http, token, run, contents, emit)
        tries.append(run.model)  # the model that answered: Google's capacity may have moved the step
        return again


class _Models:
    """The two models a run can use (the chosen one and the fallback) and the one it is on now."""

    def __init__(self, runtime: CodeAssistRuntime, request: AgentRequest, project: str, chosen: str, fallback: str | None,
                 model: str, declarations: list[dict[str, Any]]):
        self.runtime, self.request, self.project, self.declarations = runtime, request, project, declarations
        self.models = [m for m in dict.fromkeys([chosen, fallback or chosen]) if m]
        self.model = model
        self.generation = runtime._generation(model)

    def other(self, resting: dict[str, tuple[float, Limit]]) -> str | None:
        """The model to turn to when the current one refuses: the other of the two, unless its quota is used up."""
        now = time.monotonic()
        return next((m for m in self.models if m != self.model and not (m in resting and resting[m][0] > now)), None)

    def envelope(self, contents: list[dict[str, Any]]) -> dict[str, Any]:
        return {"model": self.model, "project": self.project, "user_prompt_id": self.request.run_id, "request": {
            "contents": contents,
            "systemInstruction": {"role": "user", "parts": [{"text": system_prompt()}]},
            "tools": [{"functionDeclarations": self.declarations}],
            "generationConfig": self.generation}}  # shared: a thinking setting the model rejects stays dropped

    async def switch(self, model: str, contents: list[dict[str, Any]], emit: Emit, why: str) -> None:
        log.info("Gemini continues with %s: %s", model, why)
        self.model = model
        self.generation = self.runtime._generation(model)
        _skip_signatures(contents)
        await emit("agent_session", {"session_id": self.request.run_id, "model": model, "project": self.project})


def _skip_signatures(contents: list[dict[str, Any]]) -> None:
    """Thought signatures belong to the model that wrote them. After switching models, earlier turns carry Google's
    documented placeholder instead, so the new model does not reject them."""
    for turn in contents:
        for part in turn.get("parts") or []:
            if isinstance(part, dict) and "thoughtSignature" in part:
                part["thoughtSignature"] = "skip_thought_signature_validator"
