"""The folder or file the person chose for a task (owner, 1 Nov 2026: "a task that asks me for a folder, and I point it
to that folder, and it digests the whole thing and adds to the knowledge base").

A task whose front matter asks for a folder or a file gets one when the person runs it from Settings → Tasks. Gemini
reads it only through the task-file tools (tools/task_tools.py), inside that path and nowhere else: the files are
listed with a short id each, read as text with the converter Wizard uses for attached files, and, for presentations,
read for how they look (design.py). Nothing in the folder is changed; conversions are kept under the data folder so a
file is converted once.

A task that goes through every file runs in rounds (runs.py) and keeps here which files are done for this folder, so
the next round, or the next run after a restart, starts with the files left. A file that changed since is not done.

The converter runs in its own process, one file at a time; this module only receives it (Documents), so the connectors
never import the document converter."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

KINDS = {
    "slides": (".pptx", ".pptm", ".ppsx", ".potx", ".potm", ".ppt", ".pps", ".pot"),
    "document": (".docx", ".docm", ".dotx", ".doc", ".rtf"),
    "spreadsheet": (".xlsx", ".xlsm", ".xls", ".xlsb", ".csv", ".tsv"),
    "email": (".eml", ".msg"),
    "text": (".txt", ".md"),
}
SUFFIXES = {suffix: kind for kind, suffixes in KINDS.items() for suffix in suffixes}
INPUTS = {"folder": "folder", "file": "file", "folder or file": "either", "file or folder": "either", "either": "either"}
MAX_FILES = 5000
MAX_DEPTH = 12
LISTING_S = 60.0  # a folder is walked again at most once a minute


class TaskFolderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class Documents(Protocol):
    """The document converter, run by the API in a separate process: convert(source, out) -> its JSON result (text.md in
    out), design(sources) -> one result per source ({status, profile} or {status, note}), combine(profiles)."""

    def convert(self, source: Path, out: Path) -> dict[str, Any]: ...
    def design(self, sources: list[Path]) -> list[dict[str, Any]]: ...
    def combine(self, profiles: list[dict[str, Any]]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class TaskFile:
    id: str        # f + 8 hex characters of its relative path: the same file keeps its id from round to round
    path: Path
    relative: str  # inside the chosen folder, with / between folders (the file's name when one file was chosen)
    kind: str
    bytes: int
    modified: float

    def public(self, done: bool | None = None) -> dict[str, Any]:
        item: dict[str, Any] = {"id": self.id, "path": self.relative, "kind": self.kind, "kb": max(1, round(self.bytes / 1024)),
                                "modified": datetime.fromtimestamp(self.modified, UTC).strftime("%Y-%m-%d")}
        if done is not None:
            item["done"] = done
        return item


def input_kind(value: str) -> str | None:
    """A task's `input` front matter: folder, file, or folder or file (either); None when it asks for nothing."""
    return INPUTS.get(" ".join(value.casefold().split())) if value.strip() else None


def file_id(relative: str) -> str:
    return "f" + hashlib.sha1(relative.casefold().encode("utf-8")).hexdigest()[:8]  # noqa: S324 - a name, not security


def check_path(text: str, wanted: str) -> Path:
    """The path the person typed, as a folder or file Wizard can read: quotes from Copy as path removed, ~ and
    %VARIABLES% expanded, resolved. Raises TaskFolderError with words they can act on."""
    cleaned = text.strip().strip('"').strip("'").strip()
    if not cleaned:
        raise TaskFolderError("no_path", "Type or paste the path of the " + ("folder" if wanted == "folder" else
                                                                             "file" if wanted == "file" else "folder or file") + ".")
    try:
        path = Path(os.path.expandvars(os.path.expanduser(cleaned))).resolve(strict=True)
    except (OSError, RuntimeError):
        raise TaskFolderError("not_found", f"Wizard cannot find {cleaned} on this PC. Copy the path from File Explorer "
                                           "(right-click, Copy as path) and paste it here.") from None
    if path.is_dir():
        if wanted == "file":
            raise TaskFolderError("not_a_file", "This task reads one file: paste the path of a file, not a folder.")
        if path.parent == path or path == Path.home():
            raise TaskFolderError("too_wide", "Choose the folder that holds the documents, not a whole drive or your "
                                              "home folder.")
        return path
    if wanted == "folder":
        raise TaskFolderError("not_a_folder", "This task reads a folder: paste the path of the folder, not of a file.")
    if path.suffix.lower() not in SUFFIXES:
        raise TaskFolderError("unreadable_kind", f"Wizard reads PowerPoint, Word, Excel, email and text files; "
                                                 f"{path.suffix or 'this file'} is not one of them.")
    return path


def _walk(root: Path) -> Iterator[Path]:
    """Files under root, without following links out of it, skipping hidden folders and Office's ~$ lock files."""
    stack = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith((".", "~$")):
                continue
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if depth < MAX_DEPTH:
                        stack.append((Path(entry.path), depth + 1))
                elif entry.is_file():
                    yield Path(entry.path)
            except OSError:
                continue


class TaskFiles:
    def __init__(self, data_dir: Path, documents: Documents | None = None):
        self.folder = data_dir / "tasks"
        self.documents = documents
        self._lock = threading.Lock()
        self._listings: dict[str, tuple[float, list[TaskFile], dict[str, int]]] = {}

    # What is in it ------------------------------------------------------------------------------------------------------
    def listing(self, root: Path, fresh: bool = False) -> tuple[list[TaskFile], dict[str, int]]:
        """The readable files (sorted by path) and how many of each other kind were left out."""
        key = str(root)
        cached = self._listings.get(key)
        if cached and not fresh and time.monotonic() - cached[0] < LISTING_S:
            return cached[1], cached[2]
        files: list[TaskFile] = []
        skipped: dict[str, int] = {}
        candidates = [root] if root.is_file() else _walk(root)
        for path in candidates:
            suffix = path.suffix.lower()
            if suffix not in SUFFIXES:
                skipped[suffix or "(no extension)"] = skipped.get(suffix or "(no extension)", 0) + 1
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            relative = path.name if root.is_file() else path.relative_to(root).as_posix()
            files.append(TaskFile(file_id(relative), path, relative, SUFFIXES[suffix], stat.st_size, stat.st_mtime))
            if len(files) >= MAX_FILES:
                skipped["(more than 5000 files: the rest)"] = 1
                break
        files.sort(key=lambda f: f.relative.casefold())
        self._listings[key] = (time.monotonic(), files, skipped)
        return files, skipped

    def find(self, root: Path, ids: list[str]) -> tuple[list[TaskFile], list[str]]:
        by_id = {f.id: f for f in self.listing(root)[0]}
        found = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
        missing = [i for i in dict.fromkeys(ids) if i not in by_id]
        if missing:  # a file added since the last walk
            by_id = {f.id: f for f in self.listing(root, fresh=True)[0]}
            found += [by_id[i] for i in missing if i in by_id]
            missing = [i for i in missing if i not in by_id]
        return found, missing

    # Which files are done (a task that goes through every file) ---------------------------------------------------------
    def _progress_path(self, task_id: str, root: Path) -> Path:
        digest = hashlib.sha1(str(root).casefold().encode("utf-8")).hexdigest()[:12]  # noqa: S324 - a file name
        return self.folder / "progress" / f"{task_id}-{digest}.json"

    def _progress(self, task_id: str, root: Path) -> dict[str, Any]:
        try:
            value = json.loads(self._progress_path(task_id, root).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def done(self, task_id: str, root: Path) -> set[str]:
        """Ids of the files marked done that have not changed since."""
        marked = self._progress(task_id, root).get("files") or {}
        return {f.id for f in self.listing(root)[0]
                if (entry := marked.get(f.relative)) and entry.get("bytes") == f.bytes and entry.get("modified") == round(f.modified)}

    def counts(self, task_id: str, root: Path) -> dict[str, int]:
        files = self.listing(root)[0]
        done = len(self.done(task_id, root))
        return {"total": len(files), "done": done, "left": len(files) - done}

    def mark_done(self, task_id: str, root: Path, files: list[TaskFile], note: str | None) -> None:
        with self._lock:
            progress = self._progress(task_id, root)
            marked = progress.setdefault("files", {})
            progress["root"] = str(root)
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            for item in files:
                marked[item.relative] = {"bytes": item.bytes, "modified": round(item.modified), "at": stamp,
                                         **({"note": note[:300]} if note else {})}
            target = self._progress_path(task_id, root)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(progress, indent=1, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)

    def reset(self, task_id: str, root: Path) -> None:
        self._progress_path(task_id, root).unlink(missing_ok=True)

    # Reading ----------------------------------------------------------------------------------------------------------
    def _cache(self, item: TaskFile) -> Path:
        key = f"{item.path}|{item.bytes}|{round(item.modified)}"
        return self.folder / "files" / hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]  # noqa: S324 - a folder name

    def source_id(self, item: TaskFile) -> str:
        """S- and the first 8 characters of the file's SHA-256: the id the knowledge standard cites (section 8)."""
        meta = self._cache(item) / "source.json"
        try:
            return str(json.loads(meta.read_text(encoding="utf-8"))["source_id"])
        except (OSError, ValueError, KeyError):
            pass
        digest = hashlib.sha256()
        with item.path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        source_id = "S-" + digest.hexdigest()[:8]
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps({"source_id": source_id, "path": str(item.path)}), encoding="utf-8")
        return source_id

    def text(self, item: TaskFile) -> tuple[dict[str, Any], str]:
        """The file as text (converted once, then kept): its conversion result and the text."""
        folder = self._cache(item)
        meta = folder / "converted.json"
        try:
            result = json.loads(meta.read_text(encoding="utf-8"))
            if result.get("status") != "ok":
                raise ValueError("convert again")
            return result, (folder / "converted" / "text.md").read_text(encoding="utf-8")
        except (OSError, ValueError):
            pass
        if self.documents is None:
            raise TaskFolderError("no_converter", "This Wizard cannot convert documents.")
        folder.mkdir(parents=True, exist_ok=True)
        result = self.documents.convert(item.path, folder / "converted")
        meta.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        if result.get("status") != "ok":
            return result, ""
        return result, (folder / "converted" / "text.md").read_text(encoding="utf-8")

    def design(self, items: list[TaskFile]) -> list[dict[str, Any]]:
        """Each presentation's design profile (read once, then kept), in the order given."""
        results: dict[str, dict[str, Any]] = {}
        todo = []
        for item in items:
            if item.kind != "slides":
                results[item.id] = {"status": "failed", "note": "not a presentation"}
                continue
            try:
                results[item.id] = json.loads((self._cache(item) / "design.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                todo.append(item)
        if todo:
            if self.documents is None:
                raise TaskFolderError("no_converter", "This Wizard cannot read presentations.")
            answers = self.documents.design([i.path for i in todo])
            for item, answer in zip(todo, answers, strict=False):
                results[item.id] = answer
                if answer.get("status") == "ok":
                    target = self._cache(item) / "design.json"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
            for item in todo[len(answers):]:
                results[item.id] = {"status": "failed", "note": "PowerPoint did not finish in time; try it again on its own"}
        return [results[i.id] for i in items]

    def profiled(self, root: Path) -> list[tuple[TaskFile, dict[str, Any]]]:
        """Every presentation in the folder whose design was read, with its profile."""
        found = []
        for item in self.listing(root)[0]:
            if item.kind != "slides":
                continue
            try:
                answer = json.loads((self._cache(item) / "design.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if answer.get("status") == "ok":
                found.append((item, answer["profile"]))
        return found
