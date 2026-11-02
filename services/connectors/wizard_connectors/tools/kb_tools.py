"""Task tools (owner, 31 Oct 2026, "the output of the task is the GitHub repo"): read a knowledge note's file and the
knowledge standard, and save notes to the company's knowledge-base repository.

Saving is the one write: it commits note files under knowledge/ in the knowledge-base repository with this PC's write
token, the way portal maps are published. A save adds or replaces whole notes, and may also move a note to another
folder, rename it (a new id, with every other note's `related` changed to match in the same commit) or remove it (owner,
2 Nov 2026: notes describing dashboards were filed under datasets/, and a task could not move them). Every resulting
note is checked first with the content validator (front matter, id, type, dates, no credentials, no contact details), a
SIGNED note is never changed, moved or removed (only its owner changes it), and nothing is committed when anything fails.
Wizard refuses wizard_kb_save_notes outside a task run (runs.py), so answering a question never changes the knowledge
base."""
from __future__ import annotations

import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..content import validate_knowledge
from ..knowledge import Note, front_matter, parse_list, unquote
from ..paths import ROOT
from .registry import ToolContext, ToolError, ToolSpec

STANDARD = ROOT / "templates" / "content" / "schema" / "knowledge-standard.md"
NOTE_PATH = r"^knowledge/([a-z0-9][a-z0-9-]*/){0,2}[a-z0-9][a-z0-9-]{0,80}\.md$"
NOTE_ID = r"^[a-z0-9][a-z0-9-]{0,80}$"
MAX_PROBLEMS = 12  # refusals named in one answer
MAX_MENTIONS = 20  # notes named whose text still mentions a renamed or removed id
# The validator checks one note alone here, so it calls every related id missing; only the ones missing after the commit are.
DANGLING = re.compile(r"related note '([^']+)' does not exist")


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


class SourceArgs(Args):
    ids: list[str] = Field(min_length=1, max_length=10, description="Note ids, e.g. ['market-share'].")


class NoteFile(Args):
    path: str = Field(pattern=NOTE_PATH, description="knowledge/<area>/<note id>.md, e.g. knowledge/metrics/market-share.md. An existing note keeps its path (wizard_kb_note_source shows it); to move or rename it, use moves.")
    text: str = Field(min_length=20, max_length=60_000, description="The whole file: front matter and body, as the knowledge standard says.")


class Move(Args):
    id: str = Field(pattern=NOTE_ID, description="The note's id now, e.g. 'sell-in-weekly'.")
    to: str = Field(pattern=NOTE_PATH, description="Its new path, knowledge/<area>/<id>.md. The same file name moves the note to that folder and keeps its id; another file name renames it: the file name is the new id, and Wizard sets it in the note and in every other note's related.")


class SaveArgs(Args):
    notes: list[NoteFile] = Field(default_factory=list, max_length=20, description="Notes to add or replace, whole files. A note that moves can be given here at its new path, when its text changes too.")
    moves: list[Move] = Field(default_factory=list, max_length=20, description="Notes to move to another folder or rename, each by its id and its new path.")
    removes: list[Annotated[str, Field(pattern=NOTE_ID)]] = Field(default_factory=list, max_length=20, description="Ids of notes to delete. Refused while another note's related names one, unless this call saves that note without the link (notes).")
    message: str = Field(min_length=5, max_length=200, description="The commit message: what this changes and why, e.g. 'Where to get it names mapped portal reports'.")

    @model_validator(mode="after")
    def _something_to_save(self) -> SaveArgs:
        if not (self.notes or self.moves or self.removes):
            raise ValueError("give notes, moves or removes")
        return self


def note_source(ctx: ToolContext, args: SourceArgs) -> dict[str, Any]:
    knowledge = ctx.services.knowledge
    if knowledge.root is None and not knowledge.saved:
        raise ToolError("not_found", "This Wizard has no knowledge-base files to read.")
    found, missing = [], []
    for note_id in dict.fromkeys(args.ids):
        note = knowledge.by_id.get(note_id)
        if note is None:
            missing.append(note_id)
            continue
        found.append({"id": note.id, "path": note.path, "text": knowledge.source(note)})
    if not found:
        raise ToolError("unknown_note", f"No note with id {', '.join(missing)}. Find ids with wizard_browse_knowledge.")
    return {"notes": found, "missing": missing or None}


def standard(ctx: ToolContext, args: NoArgs) -> dict[str, Any]:
    return {"standard": STANDARD.read_text(encoding="utf-8")}


def _problems(path: str, text: str) -> tuple[list[str], list[str]]:
    """The content validator's errors and warnings for this one note, plus an id that does not match its file name."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        found = validate_knowledge(root / "knowledge", root)
    errors = [p.message for p in found if p.level == "error"]
    parsed = front_matter(text)
    if parsed and unquote(parsed[0].get("id", "")) != Path(path).stem:
        errors.append(f"the id must be the file name ({Path(path).stem})")
    return errors, [p.message for p in found if p.level == "warning"]


def _with_field(text: str, key: str, value: str) -> str:
    """The note's file with one front matter field set, every other line as it was (no such field: unchanged)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("﻿").rstrip("\r\n") != "---":
        return text
    for index, line in enumerate(lines[1:], start=1):
        bare = line.rstrip("\r\n")
        if bare == "---":
            break
        if line.partition(":")[0].strip() == key:
            lines[index] = f"{key}: {value}{line[len(bare):]}"
            return "".join(lines)
    return text


def _related(text: str) -> tuple[str, ...]:
    parsed = front_matter(text)
    return parse_list(parsed[0].get("related", "")) if parsed else ()


def _body(text: str) -> str:
    parsed = front_matter(text)
    return parsed[1] if parsed else text


def _relinked(text: str, renamed: dict[str, str]) -> str:
    """The file with each renamed id in its related replaced by the new id."""
    related = _related(text)
    if not any(r in renamed for r in related):
        return text
    return _with_field(text, "related", "[" + ", ".join(dict.fromkeys(renamed.get(r, r) for r in related)) + "]")


def _signed(note: Note, what: str) -> str:
    return (f"{note.path} is SIGNED, so {what}: only its owner changes it. Leave it and propose the change in your "
            "summary for its owner")


def save_notes(ctx: ToolContext, args: SaveArgs) -> dict[str, Any]:
    writer = ctx.services.kb_writer
    if writer is None:
        raise ToolError("no_write_token", "This PC has no knowledge-base write token, so nothing can be saved: the person "
                                          "adds it in Settings → Knowledge base.")
    knowledge = ctx.services.knowledge
    paths = [n.path for n in args.notes]
    if len(set(paths)) != len(paths):
        raise ToolError("invalid_arguments", "The same path appears twice.")
    ids = [m.id for m in args.moves] + list(args.removes)
    if len(set(ids)) != len(ids):
        raise ToolError("invalid_arguments", "A note appears twice in moves and removes: move or remove each note once.")
    if len({m.to for m in args.moves}) != len(args.moves):
        raise ToolError("invalid_arguments", "Two moves go to the same path.")
    at_path = {n.path: n for n in knowledge.notes}
    written = {n.path: n.text for n in args.notes}
    refused: list[str] = []  # what stops the call besides the validator: unknown ids, SIGNED notes, paths, links
    files: dict[str, str | None] = {}  # the commit: path -> the file's new text; None removes the file
    moved: list[dict[str, str]] = []
    renamed: dict[str, str] = {}  # old id -> new id
    removed: list[Note] = []
    for note_id in args.removes:
        note = knowledge.by_id.get(note_id)
        if note is None:
            refused.append(f"{note_id}: no note has this id (wizard_browse_knowledge lists them)")
        elif note.status == "SIGNED":
            refused.append(_signed(note, "it cannot be removed"))
        else:
            files[note.path] = None
            removed.append(note)
    for move in args.moves:
        note = knowledge.by_id.get(move.id)
        if note is None:
            refused.append(f"{move.id}: no note has this id (wizard_browse_knowledge lists them)")
            continue
        if note.status == "SIGNED":
            refused.append(_signed(note, "it cannot be moved or renamed"))
            continue
        if move.to == note.path:
            refused.append(f"{move.id} is already {move.to}")
            continue
        if move.to in at_path:
            refused.append(f"{move.to} is already the note {at_path[move.to].id}: move {move.id} elsewhere, or remove "
                           "that note in a call of its own first")
            continue
        new_id = Path(move.to).stem
        if move.to in written:
            text = written[move.to]
        else:
            try:
                text = knowledge.source(note)
            except OSError:
                refused.append(f"{note.path}: Wizard cannot read this note's file to move it")
                continue
            if new_id != note.id:
                text = _with_field(text, "id", new_id)
        files[note.path], files[move.to] = None, text
        moved.append({"id": new_id, "from": note.path, "to": move.to} | ({"was": note.id} if new_id != note.id else {}))
        if new_id != note.id:
            renamed[note.id] = new_id
    for path, text in written.items():
        if path in files and files[path] is None:
            refused.append(f"{path}: a move or remove in this call takes this file away")
            continue
        existing = at_path.get(path)
        if existing is not None and existing.status == "SIGNED":
            refused.append(_signed(existing, "it cannot be replaced"))
        files[path] = text
    # A rename changes every other note's related to the new id in the same commit, a note this call saves included.
    relinked: list[str] = []
    for path, content in list(files.items()):
        if content is not None:
            files[path] = _relinked(content, renamed)
    for note in knowledge.notes:
        names = [r for r in note.related if r in renamed]
        if note.path in files or not names:
            continue
        if note.status == "SIGNED":
            refused.append(_signed(note, f"Wizard cannot change the link to {', '.join(names)} in its related, and "
                                         "the rename would leave it naming a note that is gone"))
            continue
        try:
            files[note.path] = _relinked(knowledge.source(note), renamed)
        except OSError:
            refused.append(f"{note.path} names {', '.join(names)} in related, and Wizard cannot read its file to change it")
            continue
        relinked.append(note.path)

    def after() -> Iterator[tuple[str, str | None, Note | None]]:
        """Every note as it will be after this commit: its path, its new text (None: unchanged) and the note it was."""
        for note in knowledge.notes:
            if note.path not in files:
                yield note.path, None, note
        for path, content in files.items():
            if content is not None:
                yield path, content, at_path.get(path)

    # A removed note may not stay linked: no note left after this commit may name it in related.
    gone = {n.id for n in removed}
    for path, content, was in after() if gone else ():
        for link in [r for r in (_related(content) if content is not None else was.related if was else ()) if r in gone]:
            refused.append(f"{path} names {link} in related" + (
                f", and it is SIGNED, so {link} cannot be removed: propose it to that note's owner"
                if content is None and was is not None and was.status == "SIGNED" else
                f": save {path} without that link in this same call (notes), or keep {link}"))
    # Every file this commit writes is checked as it will be committed, and its id must be its own.
    invalid: list[str] = []
    warnings: list[str] = []
    leaving = {p for p, t in files.items() if t is None}
    ids_after = {n.id for n in knowledge.notes if n.path not in files} | {Path(p).stem for p, t in files.items() if t}
    stems: dict[str, str] = {}
    for path, content in files.items():
        if content is None:
            continue
        errors, notes_warnings = _problems(path, content)
        stem = Path(path).stem
        taken = knowledge.by_id.get(stem)
        if taken is not None and taken.path != path and taken.path not in leaving:
            errors.append(f"id {taken.id} is already the note {taken.path}: change that file instead")
        if stem in stems:
            errors.append(f"id {stem} is also {stems[stem]} in this call")
        stems[stem] = path
        why = " (its related names a renamed note, so this call changes it)" if path in relinked else ""
        invalid += [f"{path}: {e}{why}" for e in errors]
        if path not in relinked:  # the notes the task wrote; a relinked note's own warnings are not this call's
            warnings += [f"{path}: {w}" for w in notes_warnings
                         if not ((match := DANGLING.search(w)) and match.group(1) in ids_after)]
    if refused or invalid:
        raise ToolError("refused" if refused else "invalid_note",
                        "Nothing was saved. Fix these and save again: " + "; ".join((refused + invalid)[:MAX_PROBLEMS]))
    # Notes whose text (not related) names a renamed or removed id: Gemini decides whether they mean that note.
    mentions = []
    for path, content, was in after():
        body = _body(content) if content is not None else was.body if was else ""
        for old in [*renamed, *gone]:
            if re.search(rf"(?<![a-z0-9-]){re.escape(old)}(?![a-z0-9-])", body):
                change = f"renames to {renamed[old]}" if old in renamed else "removes"
                mentions.append(f"{path}: its text names {old}, which this call {change}; change it if it means that note")
    warnings += mentions[:MAX_MENTIONS] + ([f"and {len(mentions) - MAX_MENTIONS} more notes name them"]
                                           if len(mentions) > MAX_MENTIONS else [])
    prefix = ctx.services.kb_prefix.strip("/")
    commit = {"/".join(p for p in (prefix, path) if p): None if content is None else content.encode("utf-8")
              for path, content in files.items()}
    result = writer(commit, f"Wizard task: {args.message}")
    if result.outcome == "failed":
        raise ToolError("publish_failed", f"Not saved: {result.message}")
    # This Wizard sees the change now (search, browse, read, note source), so the rest of the task builds on it.
    ctx.services.knowledge = knowledge.with_saved(files)
    return {"saved": paths, "moved": moved or None, "removed": [n.path for n in removed] or None,
            "links_updated": relinked or None, "outcome": result.outcome, "commit": result.commit,
            "warnings": warnings or None,
            "note": "Saved to the company knowledge base. This Wizard uses it from now on; every other Wizard picks it "
                    "up at its next knowledge-base sync."}


KB_TOOLS = [
    ToolSpec("wizard_kb_note_source",
             "The file of knowledge notes as it is in the knowledge base (front matter and body) with its path, to "
             "change it with wizard_kb_save_notes.", SourceArgs, note_source, "wizard", "knowledge"),
    ToolSpec("wizard_kb_standard",
             "The knowledge standard: how every knowledge note is written (front matter, areas, sections, sources, "
             "status). Read it before writing or changing a note.", NoArgs, standard, "wizard", "knowledge"),
    ToolSpec("wizard_kb_save_notes",
             "Only in a task run (Settings → Tasks): change the company's knowledge-base repository in one commit. "
             "notes adds or replaces whole notes; moves moves a note to another folder (same file name, same id) or "
             "renames it (a new file name is its new id: Wizard sets it in the note and in every other note's related); "
             "removes deletes notes no other note links to (or whose links this call removes). Every resulting note is "
             "checked against the knowledge standard first, a SIGNED note is never changed, moved or removed, and "
             "nothing is saved when anything fails.", SaveArgs, save_notes, "wizard", "present"),
]
TASK_ONLY = frozenset({"wizard_kb_save_notes"})
