"""Runtime interface shared by the Gemini CLI, Code Assist and replay runtimes."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

RuntimeKind = Literal["gemini-cli", "code-assist", "replay"]


class AgentFailure(Exception):
    """A user-presentable failure with a stable code (model outage, sign-in required, timeout...). `details` is what the
    run card's Error details shows: the facts behind the message (Google's own reason and words), label -> value."""

    def __init__(self, code: str, message: str, details: dict[str, str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return re.sub(r"(ya29\.[A-Za-z0-9_\-]+|1//[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,})", "[redacted]", text)


@dataclass
class Turn:
    question: str
    answer: str
    work: list[str] = field(default_factory=list)  # what Wizard read for that answer: tools, SQL, evidence, the person's notes


@dataclass
class AgentRequest:
    run_id: str
    user_id: str
    user_email: str
    user_home: Path
    prompt: str
    question: str
    kind: Literal["ask", "check", "recurring", "explore"]
    history: list[Turn] = field(default_factory=list)
    run_token: str = ""
    internal_url: str = ""


Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class ToolBridge(Protocol):
    """In-process tool execution through the run manager (same checks and evidence as the MCP path), and the notes the
    person sends while the run works."""

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]: ...

    def describe(self) -> list[dict[str, Any]]: ...

    def evidence_index(self) -> list[dict[str, Any]]: ...

    def steers_waiting(self) -> bool:
        """The person sent a note (a steer) that Gemini has not read yet."""
        ...

    async def take_steers(self) -> list[str]:
        """The person's notes not yet handed to Gemini, as Gemini reads them; each is marked read on the page."""
        ...


class AgentRuntime(Protocol):
    kind: RuntimeKind
    model: str
    steering: bool  # the person's notes reach Gemini while the run works (otherwise a note stops it and asks again)

    def label(self) -> str: ...

    async def readiness(self, user_home: Path, user_email: str) -> dict[str, Any]: ...

    async def run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Callable[[], bool]) -> None: ...
