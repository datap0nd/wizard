"""Code Assist runtime: the same agent loop over the Code Assist API that Gemini CLI uses, under the user's own sign-in.

This is the plan's per-user OAuth route (Step 02) for hosts where running isolated CLI processes is not approved.
Ported from Scribble's GeminiCodeAssistGateway (datap0nd/scribble 41ab532): project resolution via loadCodeAssist /
onboardUser with GOOGLE_CLOUD_PROJECT for enterprise tiers, SSE streamGenerateContent, function calling with thought
signatures echoed back, and Gemini CLI style 429 handling. Gemini still chooses every tool call; Wizard only executes
them through the same registry, rights checks and evidence capture as the MCP path."""
from __future__ import annotations

import asyncio
import json
import random
import re
from pathlib import Path
from typing import Any

import httpx

from . import google_oauth, outbound
from .prompting import system_prompt
from .runtime import AgentFailure, AgentRequest, Emit, RuntimeKind, ToolBridge
from .secret_box import SecretBox

API_BASE = "https://cloudcode-pa.googleapis.com/v1internal"
MAX_STEPS = 24
MAX_RETRIES = 6
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


def retry_delay(body: str, attempt: int) -> float:
    match = re.search(r'"retryDelay"\s*:\s*"(\d+)', body) or re.search(r"after\s+(\d+)\s*s", body)
    hint = int(match.group(1)) if match else 0
    backoff = min(30, 2 ** (attempt + 1))
    return min(90, max(backoff, hint)) * (1 + 0.2 * random.random())  # noqa: S311 - jitter, not security


def summarize_quota(raw: dict[str, Any], model: str) -> dict[str, Any]:
    """retrieveUserQuota buckets -> what the UI shows. The selected bucket is the configured model's most constraining one
    (a model can have several, e.g. requests and tokens); a model variant such as `<model>-preview` also matches."""
    buckets = []
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
                 api_base: str = API_BASE, transport: httpx.AsyncBaseTransport | None = None, proxy: str | None = None):
        self.model = model
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
            onboard = {**body, "tierId": tier}
            operation = await self._post(http, token, "onboardUser", onboard)
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
        dropped_thinking = False
        for attempt in range(MAX_RETRIES):
            parts: list[dict[str, Any]] = []
            calls: list[dict[str, Any]] = []
            usage: dict[str, Any] = {}
            async with http.stream("POST", f"{self.api_base}:streamGenerateContent", params={"alt": "sse"}, json=envelope,
                                   headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}) as response:
                if response.status_code == 429:
                    body = (await response.aread()).decode("utf-8", "replace")
                    delay = retry_delay(body, attempt)
                    await emit("status", {"message": f"Gemini is at capacity; retrying in {delay:.0f}s "
                                                     f"(attempt {attempt + 1} of {MAX_RETRIES})."})
                    await asyncio.sleep(delay)
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
        raise AgentFailure("model_capacity", f"Gemini stayed at capacity through {MAX_RETRIES} attempts. Try again later.")

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

    async def run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        try:
            await self._run(request, emit, tools, cancelled)
        except httpx.HTTPError as error:
            raise AgentFailure("network_error", outbound.explain(error, self.api_base, self.proxy)) from None

    async def _run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        async with self._http() as http:
            token = await self._access_token(http, request)
            project = await self.resolve_project(http, token, request.user_id)
            await emit("agent_session", {"session_id": request.run_id, "model": self.model, "project": project})
            declarations = [{"name": t["name"], "description": t["description"], "parameters": gemini_schema(t["inputSchema"])}
                            for t in tools.describe()]
            generation: dict[str, Any] = {}
            thinking = thinking_config(self.model, self.thinking)
            if thinking:
                generation["thinkingConfig"] = thinking
            contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": request.prompt}]}]
            totals = {"tool_calls": 0, "input_tokens": 0, "output_tokens": 0}
            for _ in range(MAX_STEPS):
                if cancelled():
                    raise AgentFailure("cancelled", "The run was cancelled.")
                envelope = {"model": self.model, "project": project, "user_prompt_id": request.run_id, "request": {
                    "contents": contents,
                    "systemInstruction": {"role": "user", "parts": [{"text": system_prompt()}]},
                    "tools": [{"functionDeclarations": declarations}],
                    "generationConfig": generation}}
                parts, calls, usage = await self._stream(http, token, envelope, emit)
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
