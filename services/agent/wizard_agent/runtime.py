"""Runtime interface shared by the Gemini CLI, Code Assist and replay runtimes."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

RuntimeKind = Literal["gemini-cli", "code-assist", "replay"]


class AgentFailure(Exception):
    """A user-presentable failure with a stable code (model outage, sign-in required, timeout...)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Turn:
    question: str
    answer: str


@dataclass
class AgentRequest:
    run_id: str
    user_id: str
    user_email: str
    user_home: Path
    prompt: str
    question: str
    kind: Literal["ask", "check"]
    history: list[Turn] = field(default_factory=list)
    run_token: str = ""
    internal_url: str = ""


Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class ToolBridge(Protocol):
    """In-process tool execution through the run manager (same checks and evidence as the MCP path)."""

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]: ...

    def describe(self) -> list[dict[str, Any]]: ...

    def evidence_index(self) -> list[dict[str, Any]]: ...


class AgentRuntime(Protocol):
    kind: RuntimeKind
    model: str

    def label(self) -> str: ...

    async def readiness(self, user_home: Path, user_email: str) -> dict[str, Any]: ...

    async def run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Callable[[], bool]) -> None: ...
