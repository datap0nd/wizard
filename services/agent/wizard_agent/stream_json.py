"""Gemini CLI `--output-format stream-json` events (JSONL on stdout), as defined by gemini-cli-core
packages/core/src/output/types.ts (verified against 0.62.0):

  init         {session_id, model}
  message      {role: user|assistant, content, delta?}
  tool_use     {tool_name, tool_id, parameters}
  tool_result  {tool_id, status: success|error, output?, error?: {type, message}}
  error        {severity: warning|error, message}
  result       {status: success|error, error?, stats?}

Non-JSON stdout lines are ignored; Wizard's own backend events remain the authority for what a tool actually did."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class Mapped:
    kind: str
    payload: dict[str, Any]


def parse_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) and isinstance(event.get("type"), str) else None


def map_event(event: dict[str, Any]) -> Mapped | None:
    kind = event["type"]
    if kind == "init":
        return Mapped("agent_session", {"session_id": event.get("session_id"), "model": event.get("model")})
    if kind == "message":
        if event.get("role") == "assistant" and isinstance(event.get("content"), str):
            return Mapped("text_delta", {"text": event["content"], "delta": bool(event.get("delta"))})
        return None
    if kind == "tool_use":
        return Mapped("model_tool_trace", {"phase": "use", "tool_id": event.get("tool_id"), "name": event.get("tool_name"),
                                           "parameters": event.get("parameters") or {}})
    if kind == "tool_result":
        error = event.get("error") or {}
        return Mapped("model_tool_trace", {"phase": "result", "tool_id": event.get("tool_id"), "status": event.get("status"),
                                           "error": error.get("message")})
    if kind == "error":
        return Mapped("warning" if event.get("severity") == "warning" else "agent_error", {"message": event.get("message")})
    if kind == "result":
        error = event.get("error") or {}
        return Mapped("agent_result", {"status": event.get("status"), "error": error.get("message"),
                                       "stats": event.get("stats") or {}})
    return None
