"""Task tools (owner, 31 Oct 2026, "the output of the task is the GitHub repo"): read a knowledge note's file and the
knowledge standard, and save notes to the company's knowledge-base repository.

Saving is the one write: it commits whole note files under knowledge/ in the knowledge-base repository with this PC's
write token, the way portal maps are published. Every note is checked first with the content validator (front matter,
id, type, dates, no credentials, no contact details) and nothing is committed when one fails. Wizard refuses
wizard_kb_save_notes outside a task run (runs.py), so answering a question never changes the knowledge base."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..content import validate_knowledge
from ..knowledge import front_matter, unquote
from ..paths import ROOT
from .registry import ToolContext, ToolError, ToolSpec

STANDARD = ROOT / "templates" / "content" / "schema" / "knowledge-standard.md"
NOTE_PATH = r"^knowledge/([a-z0-9][a-z0-9-]*/){0,2}[a-z0-9][a-z0-9-]{0,80}\.md$"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


class SourceArgs(Args):
    ids: list[str] = Field(min_length=1, max_length=10, description="Note ids, e.g. ['market-share'].")


class NoteFile(Args):
    path: str = Field(pattern=NOTE_PATH, description="knowledge/<area>/<note id>.md, e.g. knowledge/metrics/market-share.md. An existing note keeps its path (wizard_kb_note_source shows it).")
    text: str = Field(min_length=20, max_length=60_000, description="The whole file: front matter and body, as the knowledge standard says.")


class SaveArgs(Args):
    notes: list[NoteFile] = Field(min_length=1, max_length=20, description="Notes to add or replace, whole files.")
    message: str = Field(min_length=5, max_length=200, description="The commit message: what this changes and why, e.g. 'Where to get it names mapped portal reports'.")


def note_source(ctx: ToolContext, args: SourceArgs) -> dict[str, Any]:
    knowledge = ctx.services.knowledge
    if knowledge.root is None:
        raise ToolError("not_found", "This Wizard has no knowledge-base files to read.")
    found, missing = [], []
    for note_id in dict.fromkeys(args.ids):
        note = knowledge.by_id.get(note_id)
        if note is None:
            missing.append(note_id)
            continue
        found.append({"id": note.id, "path": note.path, "text": (knowledge.root / note.path).read_text(encoding="utf-8-sig")})
    if not found:
        raise ToolError("unknown_note", f"No note with id {', '.join(missing)}. Find ids with wizard_browse_knowledge.")
    return {"notes": found, "missing": missing or None}


def standard(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    return {"standard": STANDARD.read_text(encoding="utf-8")}


def _problems(note: NoteFile) -> tuple[list[str], list[str]]:
    """The content validator's errors and warnings for this one note, plus an id that does not match its file name."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        target = root / note.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(note.text, encoding="utf-8")
        found = validate_knowledge(root / "knowledge", root)
    errors = [p.message for p in found if p.level == "error"]
    parsed = front_matter(note.text)
    if parsed and unquote(parsed[0].get("id", "")) != Path(note.path).stem:
        errors.append(f"the id must be the file name ({Path(note.path).stem})")
    return errors, [p.message for p in found if p.level == "warning"]


def save_notes(ctx: ToolContext, args: SaveArgs) -> dict[str, Any]:
    writer = ctx.services.kb_writer
    if writer is None:
        raise ToolError("no_write_token", "This PC has no knowledge-base write token, so nothing can be saved: the person "
                                          "adds it in Settings → Knowledge base.")
    paths = [n.path for n in args.notes]
    if len(set(paths)) != len(paths):
        raise ToolError("invalid_arguments", "The same path appears twice.")
    refused, warnings = [], []
    for note in args.notes:
        errors, notes_warnings = _problems(note)
        taken = ctx.services.knowledge.by_id.get(Path(note.path).stem)
        if taken is not None and taken.path != note.path:
            errors.append(f"id {taken.id} is already the note {taken.path}: change that file instead")
        refused += [f"{note.path}: {e}" for e in errors]
        warnings += [f"{note.path}: {w}" for w in notes_warnings]
    if refused:
        raise ToolError("invalid_note", "Nothing was saved. Fix these and save again: " + "; ".join(refused[:12]))
    prefix = ctx.services.kb_prefix.strip("/")
    files = {"/".join(p for p in (prefix, n.path) if p): n.text.encode("utf-8") for n in args.notes}
    result = writer(files, f"Wizard task: {args.message}")
    if result.outcome == "failed":
        raise ToolError("publish_failed", f"Not saved: {result.message}")
    return {"saved": paths, "outcome": result.outcome, "commit": result.commit, "warnings": warnings or None,
            "note": "Saved to the company knowledge base. Every Wizard picks it up at its next knowledge-base sync."}


KB_TOOLS = [
    ToolSpec("wizard_kb_note_source",
             "The file of knowledge notes as it is in the knowledge base (front matter and body) with its path, to "
             "change it with wizard_kb_save_notes.", SourceArgs, note_source, "wizard", "knowledge"),
    ToolSpec("wizard_kb_standard",
             "The knowledge standard: how every knowledge note is written (front matter, areas, sections, sources, "
             "status). Read it before writing or changing a note.", NoArgs, standard, "wizard", "knowledge"),
    ToolSpec("wizard_kb_save_notes",
             "Only in a task run (Settings → Tasks): add or replace whole knowledge notes in the company's knowledge-base "
             "repository, in one commit. Each note is checked against the knowledge standard first and nothing is "
             "saved when one fails.", SaveArgs, save_notes, "wizard", "present"),
]
TASK_ONLY = frozenset({"wizard_kb_save_notes"})
