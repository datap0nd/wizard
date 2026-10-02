"""Replay runtime: plays a frozen transcript of tool calls and answer text for CI and offline demos.

The tool calls are real (same registry, rights, synthetic data and evidence capture); the model is not. Every replay run
and report is labelled REPLAY. Placeholders in transcripts:
  {name}          id returned by an earlier step with "as": "name" (evidence or visual id)
  {E:<report_id>} latest evidence id in this conversation for that report (used by check transcripts)"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from .runtime import AgentFailure, AgentRequest, Emit, RuntimeKind, ToolBridge

PLACEHOLDER = re.compile(r"\{(E:[a-z0-9-]+|[a-z_][a-z0-9_]*)\}")
NO_TRANSCRIPT = ("**Replay mode** has no recorded transcript for this question, and replay never improvises an answer.\n\n"
                 "Try one of the suggested questions, or run Wizard with a live Gemini runtime "
                 "(`WIZARD_AGENT_RUNTIME=gemini-cli` or `code-assist`).")


class ReplayRuntime:
    kind: RuntimeKind = "replay"
    model = "replay"

    def __init__(self, directory: Path, delay_s: float = 0.0):
        self.directory = directory
        self.delay_s = delay_s
        self.transcripts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]

    def label(self) -> str:
        return "Replay (recorded transcript, not a live model)"

    async def readiness(self, user_home: Path, user_email: str) -> dict[str, Any]:
        return {"ready": True, "reason": "Replay mode: recorded transcripts over synthetic data, not a live model."}

    def match(self, question: str, kind: str) -> dict[str, Any] | None:
        """Ask runs match the question; check runs match the question being checked (the previous ask)."""
        text = question.casefold()
        for transcript in self.transcripts:
            if transcript.get("kind", "ask") != kind:
                continue
            if any(all(word in text for word in phrase.split("+")) for phrase in transcript["match"]):
                return transcript
        return None

    async def run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        await emit("agent_session", {"session_id": request.run_id, "model": "replay"})
        subject = request.history[-1].question if request.kind == "check" and request.history else request.question
        transcript = self.match(subject, request.kind)
        if transcript is None:
            await self._say(emit, NO_TRANSCRIPT)
            return
        names: dict[str, str] = {}

        def resolve(value: Any) -> Any:
            if isinstance(value, str):
                def substitute(match: re.Match[str]) -> str:
                    key = match.group(1)
                    if key.startswith("E:"):
                        found = [e["id"] for e in tools.evidence_index() if e["report_id"] == key[2:]]
                        if not found:
                            raise AgentFailure("replay_error", f"Transcript expects earlier evidence from {key[2:]}.")
                        return found[-1]
                    if key not in names:
                        raise AgentFailure("replay_error", f"Transcript placeholder {{{key}}} is not bound.")
                    return names[key]
                return PLACEHOLDER.sub(substitute, value)
            if isinstance(value, list):
                return [resolve(v) for v in value]
            if isinstance(value, dict):
                return {k: resolve(v) for k, v in value.items()}
            return value

        for step in transcript["steps"]:
            if cancelled():
                raise AgentFailure("cancelled", "The run was cancelled.")
            if "say" in step:
                await self._say(emit, resolve(step["say"]))
            elif "tool" in step:
                ok, text = await tools.call(step["tool"], resolve(step.get("args", {})))
                if not ok and not step.get("expect_error"):
                    raise AgentFailure("replay_error", f"Recorded tool call {step['tool']} failed: {text[:300]}")
                if ok and "as" in step:
                    data = json.loads(text)
                    names[step["as"]] = data.get("evidence_id") or data.get("visual_id") or ""
            elif "answer" in step:
                await self._say(emit, resolve(step["answer"]))
        await emit("agent_stats", {"stats": {"transcript": transcript["id"]}})

    async def _say(self, emit: Emit, text: str) -> None:
        chunks = re.findall(r"\S+\s*", text) or [text]
        size = max(1, len(chunks) // 12)
        for index in range(0, len(chunks), size):
            await emit("text_delta", {"text": "".join(chunks[index:index + size]), "delta": True})
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
