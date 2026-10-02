"""Prompt assembly: Wizard's short system instructions plus the conversation so far and the new request.

Each run starts a fresh agent session and receives the prior turns as context, so a follow-up never depends on CLI
session files and conversations stay inside the user's own state."""
from __future__ import annotations

from pathlib import Path

from .runtime import Turn

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"
MAX_TURNS = 6
MAX_ANSWER_CHARS = 4000

CHECK_REQUEST = (
    "The user pressed Check my data for your previous answer. Use wizard_check_my_data on the important figures in that "
    "answer (direct figures and derived ones such as ratios and growth), replaying the cited evidence. Then give a short "
    "updated answer: what matched, what you corrected, and what you could not verify."
)


def system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def compose(question: str, history: list[Turn], kind: str, today: str) -> str:
    parts = [f"Today is {today}."]
    if history:
        lines = ["<conversation_so_far>"]
        for turn in history[-MAX_TURNS:]:
            answer = turn.answer if len(turn.answer) <= MAX_ANSWER_CHARS else turn.answer[:MAX_ANSWER_CHARS] + " [...]"
            lines.append(f"User: {turn.question}\nWizard: {answer}")
        lines.append("</conversation_so_far>")
        lines.append("Evidence ids from earlier turns (E1, E2, ...) remain valid in this conversation.")
        parts.append("\n\n".join(lines))
    request = CHECK_REQUEST if kind == "check" else question
    parts.append(f"<request>\n{request}\n</request>")
    return "\n\n".join(parts)
