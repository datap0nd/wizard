"""The Email button: open an answer as an unsent Outlook message on the user's own PC, for them to address and send.

Wizard never sends mail and Gemini has no email tool (AGENTS.md). The page builds the message from the answer it shows;
this module hands it to Outlook through the documentation kit's outlook-draft command, in a subprocess so a waiting
Outlook dialog cannot hang the server."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from wizard_connectors.paths import ROOT

from .store import new_id

DRAFT_TIMEOUT_S = 60


class DraftError(Exception):
    """Outlook could not open the draft; the message says why in words a person can act on."""


async def open_outlook_draft(folder: Path, subject: str, html: str, timeout_s: int = DRAFT_TIMEOUT_S) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{new_id('draft')}.json"
    path.write_text(json.dumps({"subject": subject, "html": html}), encoding="utf-8")
    command = [sys.executable, str(ROOT / "scripts" / "wizard_docs.py"), "outlook-draft", str(path)]
    try:
        completed = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, encoding="utf-8",
                                            errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise DraftError(f"Outlook did not open a draft within {timeout_s} seconds; a dialog may be waiting in "
                         "Outlook.") from None
    finally:
        path.unlink(missing_ok=True)
    lines = [line for line in (completed.stdout or "").splitlines() if line.startswith("{")]
    result = json.loads(lines[-1]) if lines else {
        "status": "failed", "note": ((completed.stderr or "").strip().splitlines() or ["no output"])[-1][:300]}
    if result.get("status") != "ok":
        raise DraftError(str(result.get("note") or "Outlook could not open a draft."))
