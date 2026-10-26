"""Files attached to a question: PowerPoint, Excel, Word, email, CSV and text, converted to text that Gemini reads with
wizard_read_attachment.

Conversion runs in a separate process (scripts/wizard_docs.py convert), one file at a time and time-limited, so a stuck
Office dialog cannot stall Wizard. Files are kept per user under <data>/attachments/<user>/<attachment id>/.

Two ways in:
- Upload: the browser sends the bytes. Fine for ordinary files; a NASCA-protected file may not open from the uploaded
  copy, because NASCA binds access to the original path.
- From this PC (local installs): the person picks a file in their own Downloads, Desktop or Documents (or the folders
  in WIZARD_ATTACHMENT_FOLDERS) and Wizard reads the original where it is, which is how protected files open.
- Dropped on the desktop app (WizardBar): a file dragged onto the button at the top of the screen or onto its panel,
  from any folder. WizardBar, which holds the control token, allows Wizard to read that one file for a few minutes
  (grant); the page then attaches it as From this PC does."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wizard_connectors.entitlements import Identity
from wizard_connectors.paths import ROOT

from .config import Settings
from .store import Store, new_id, now

ACCEPTED = {".pptx", ".pptm", ".ppsx", ".ppt", ".xlsx", ".xlsm", ".xls", ".xlsb", ".docx", ".docm", ".doc", ".rtf",
            ".csv", ".tsv", ".txt", ".md", ".json", ".eml", ".msg"}
KINDS = {"slides": (".pptx", ".pptm", ".ppsx", ".ppt"), "spreadsheet": (".xlsx", ".xlsm", ".xls", ".xlsb", ".csv", ".tsv"),
         "document": (".docx", ".docm", ".doc", ".rtf"), "email": (".eml", ".msg")}
LOCAL_DAYS = 180
LOCAL_LIMIT = 200
GRANT_S = 600
EDITABLE = (".xlsx", ".xlsm", ".xls", ".xlsb")
# One Office job at a time (a conversion from the page, an edit from a tool thread): Office automation is not reentrant.
OFFICE = threading.Lock()
DOWNLOADS = uuid.UUID("374DE290-123F-4565-9164-39C4925E467B")  # FOLDERID_Downloads


def downloads_folder() -> Path:
    """The person's Downloads folder, where Windows keeps it (it may be redirected), else ~/Downloads."""
    if sys.platform == "win32":
        try:
            import ctypes
            windll = getattr(ctypes, "windll")  # noqa: B009 - Windows-only attribute; getattr keeps type checks platform-neutral
            folder_id = ctypes.create_string_buffer(DOWNLOADS.bytes_le, 16)
            found = ctypes.c_wchar_p()
            if windll.shell32.SHGetKnownFolderPath(folder_id, 0, None, ctypes.byref(found)) == 0:
                try:
                    if found.value:
                        return Path(found.value)
                finally:
                    windll.ole32.CoTaskMemFree(found)
        except (OSError, AttributeError, ValueError):
            pass
    return Path.home() / "Downloads"


def free_name(folder: Path, filename: str) -> Path:
    """A place in `folder` no file has yet, named as a browser would: Sales.xlsx, then Sales (1).xlsx..."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", filename).strip().strip(".") or "file"
    stem, suffix = Path(name).stem, Path(name).suffix
    for number in range(100):
        candidate = folder / (name if number == 0 else f"{stem} ({number}){suffix}")
        if not candidate.exists():
            return candidate
    raise AttachmentError(409, f"Downloads already has {name} and 99 copies of it.")


class AttachmentError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def kind_of(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return next((kind for kind, suffixes in KINDS.items() if suffix in suffixes), "text")


def public(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "label": row.get("label"), "filename": row["filename"], "kind": row["kind"],
            "bytes": row["bytes"], "origin": row["origin"], "status": row["status"], "method": row.get("method"),
            "chars": row.get("chars") or 0, "note": row.get("note") or None, "parts": len(row.get("parts") or []),
            "created_at": row["created_at"], "run_id": row.get("run_id")}


class Attachments:
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store
        self.root = settings.data_dir / "attachments"
        self.granted: dict[str, float] = {}
        self.saved: dict[tuple[str, str], Path] = {}  # (user, attachment) -> the copy saved in Downloads, for Open

    def folder(self, user_id: str, attachment_id: str) -> Path:
        return self.root / hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:20] / attachment_id

    def text(self, row: dict[str, Any]) -> str:
        path = Path(row["folder"]) / "converted" / "text.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def check_name(self, name: str, size: int) -> str:
        clean = Path(name.replace("\\", "/")).name.strip()
        if not clean or Path(clean).suffix.lower() not in ACCEPTED:
            raise AttachmentError(415, "Wizard reads PowerPoint, Excel, Word, email (.msg, .eml), CSV and text files. "
                                       "PDF and images are not supported yet.")
        if size > self.settings.max_attachment_mb * 1024 * 1024:
            raise AttachmentError(413, f"The file is larger than {self.settings.max_attachment_mb} MB.")
        if size == 0:
            raise AttachmentError(400, "The file is empty.")
        return clean

    async def upload(self, identity: Identity, filename: str, data: bytes) -> dict[str, Any]:
        name = self.check_name(filename, len(data))
        attachment_id = new_id("att")
        folder = self.folder(identity.id, attachment_id)
        folder.mkdir(parents=True, exist_ok=True)
        original = folder / ("original" + Path(name).suffix.lower())
        original.write_bytes(data)
        return await self._convert(identity, attachment_id, original, folder, name, "upload", None,
                                   datetime.now(UTC).strftime("%Y-%m-%d"))

    # From this PC --------------------------------------------------------------------------------------------------------
    def local_enabled(self) -> bool:
        return bool(self.settings.attachment_folders)

    def local_files(self, query: str = "") -> list[dict[str, Any]]:
        wanted = query.casefold().strip()
        oldest = (datetime.now() - timedelta(days=LOCAL_DAYS)).timestamp()
        found: list[dict[str, Any]] = []
        for base in self.settings.attachment_folders:
            for path in [*base.glob("*"), *base.glob("*/*")]:
                try:
                    if not path.is_file() or path.suffix.lower() not in ACCEPTED or path.name.startswith(("~$", ".")):
                        continue
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_mtime < oldest or (wanted and wanted not in path.name.casefold()):
                    continue
                found.append({"path": str(path), "name": path.name, "kind": kind_of(path.name), "bytes": stat.st_size,
                              "folder": str(path.parent.relative_to(base.parent)),
                              "modified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds")})
        found.sort(key=lambda f: str(f["modified"]), reverse=True)
        return found[:LOCAL_LIMIT]

    def grant(self, path_text: str) -> dict[str, Any]:
        """A file the person dropped on WizardBar: checked now, then readable once by attach_local for GRANT_S seconds."""
        name = Path(path_text.replace("\\", "/")).name or path_text
        try:
            path = Path(path_text).resolve(strict=True)
            if not path.is_file():
                raise AttachmentError(400, "Only files can be attached, not folders.")
            name = self.check_name(path.name, path.stat().st_size)
        except AttachmentError as error:
            return {"path": path_text, "name": name, "error": error.message}
        except (OSError, RuntimeError):
            return {"path": path_text, "name": name, "error": "That file could not be opened."}
        clock = time.monotonic()
        self.granted = {p: until for p, until in self.granted.items() if until > clock}
        self.granted[str(path)] = clock + GRANT_S
        return {"path": str(path), "name": name}

    async def attach_local(self, identity: Identity, path_text: str) -> dict[str, Any]:
        try:
            path = Path(path_text).resolve(strict=True)
        except (OSError, RuntimeError):
            path = None
        dropped = path is not None and self.granted.pop(str(path), 0.0) > time.monotonic()
        if not dropped and not self.local_enabled():
            raise AttachmentError(403, "Attaching files from this PC is switched off here; upload the file instead.")
        if path is None:
            raise AttachmentError(404, "That file no longer exists.")
        allowed = [base.resolve() for base in self.settings.attachment_folders]
        if not path.is_file() or not (dropped or any(path.is_relative_to(base) for base in allowed)):
            raise AttachmentError(403, "Only files in your Downloads, Desktop or Documents folders can be attached this way.")
        name = self.check_name(path.name, path.stat().st_size)
        attachment_id = new_id("att")
        folder = self.folder(identity.id, attachment_id)
        folder.mkdir(parents=True, exist_ok=True)
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%d")
        return await self._convert(identity, attachment_id, path, folder, name, "local", str(path), modified)

    # Conversion ----------------------------------------------------------------------------------------------------------
    def _docs(self, *arguments: str) -> dict[str, Any]:
        """Run one documentation-kit command (convert, edit) in its own process, time-limited, one at a time, and return
        its JSON result line."""
        command = [sys.executable, str(ROOT / "scripts" / "wizard_docs.py"), *arguments]
        with OFFICE:
            try:
                completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                           timeout=self.settings.attachment_timeout_s)
            except subprocess.TimeoutExpired:
                return {"status": "failed", "note": f"Office did not finish within {self.settings.attachment_timeout_s} "
                                                    "seconds (a dialog such as a password prompt may be open in Office)"}
        lines = [line for line in (completed.stdout or "").splitlines() if line.startswith("{")]
        return json.loads(lines[-1]) if lines else {
            "status": "failed", "note": ((completed.stderr or "").strip().splitlines() or ["no output"])[-1][:300]}

    async def _convert(self, identity: Identity, attachment_id: str, source: Path, folder: Path, name: str, origin: str,
                       source_path: str | None, modified: str) -> dict[str, Any]:
        row = await asyncio.to_thread(self._converted, identity, attachment_id, source, folder, name, origin, source_path,
                                      modified)
        self.store.add_attachment(row)
        self.store.audit(identity.id, "attachment:add", outcome=str(row["status"]),
                         detail={"attachment_id": attachment_id, "kind": row["kind"], "origin": origin, "bytes": row["bytes"]})
        return public(row)

    def _converted(self, identity: Identity, attachment_id: str, source: Path, folder: Path, name: str, origin: str,
                   source_path: str | None, modified: str) -> dict[str, Any]:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        result = self._docs("convert", str(source), "--out", str(folder / "converted"), "--json", "--slide-images", "none",
                            "--office", self.settings.attachment_office, "--tables")
        if origin == "upload" and result.get("status") == "failed" and "protected" in str(result.get("note", "")):
            result["note"] = str(result["note"]) + ". Protected files open only from their original place: use From this PC."
        row: dict[str, Any] = {"id": attachment_id, "user_id": identity.id, "conversation_id": None, "run_id": None, "label": None,
               "filename": name, "kind": kind_of(name), "bytes": source.stat().st_size, "sha256": digest, "origin": origin,
               "status": "ok" if result.get("status") == "ok" else "failed" if result.get("status") == "failed" else "empty",
               "method": result.get("method"), "chars": int(result.get("chars") or 0),
               "note": str(result.get("note") or "; ".join(result.get("notes") or []))[:500],
               "parts": list(result.get("parts") or []), "modified": modified, "folder": str(folder),
               "source_path": source_path, "created_at": now()}
        if row["status"] == "empty":
            row["note"] = row["note"] or "No text could be read from this file."
        return row

    # Edited copies -------------------------------------------------------------------------------------------------------
    def original(self, row: dict[str, Any]) -> Path | None:
        """The file itself: where it was read in place (From this PC), or the copy Wizard keeps."""
        if row.get("source_path"):
            return Path(row["source_path"])
        return next(iter(sorted(Path(row["folder"]).glob("original.*"))), None)

    def edit(self, identity: Identity, conversation_id: str, run_id: str, row: dict[str, Any],
             operations: list[dict[str, Any]], name: str | None = None) -> dict[str, Any]:
        """Apply Gemini's operations to a copy of an attached workbook. The copy becomes a new file in the conversation
        (labelled like any attached file, read back like one) that the person downloads; the original is never written."""
        suffix = Path(row["filename"]).suffix.lower()
        if suffix not in EDITABLE:
            raise AttachmentError(415, f"{row['filename']} is not an Excel workbook; Wizard edits .xlsx, .xlsm, .xls and "
                                       ".xlsb files.")
        source = self.original(row)
        if source is None or not source.is_file():
            raise AttachmentError(404, f"{row['filename']} is no longer where it was attached; attach it again.")
        attachment_id = new_id("att")
        folder = self.folder(identity.id, attachment_id)
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / ("original" + suffix)
        operations_file = folder / "operations.json"
        operations_file.write_text(json.dumps(operations, ensure_ascii=False), encoding="utf-8")
        result = self._docs("edit", str(source), "--operations", str(operations_file), "--out", str(output),
                            "--office", self.settings.attachment_office)
        if result.get("status") != "ok" or not output.is_file():
            shutil.rmtree(folder, ignore_errors=True)
            self.store.audit(identity.id, "attachment:edit", outcome="failed", detail={"from": row["id"]})
            raise AttachmentError(422, f"The edit was not made: {result.get('note') or 'unknown reason'}.")
        stem = re.sub(r'[\\/:*?"<>|]+', " ", name or f"{Path(row['filename']).stem} (edited)").strip()[:120] or "edited"
        filename = stem if stem.lower().endswith(suffix) else stem + suffix
        edited = self._converted(identity, attachment_id, output, folder, filename, "edited", None,
                                 datetime.now(UTC).strftime("%Y-%m-%d"))
        changes = [str(c) for c in result.get("changes") or []]
        edited["note"] = (f"Edited copy of {row.get('label') or row['filename']} ({row['filename']}): "
                          + "; ".join(changes))[:500]
        self.store.add_attachment(edited)
        bound = next(a for a in self.store.bind_attachments(identity.id, [attachment_id], conversation_id, run_id)
                     if a["id"] == attachment_id)
        self.store.audit(identity.id, "attachment:edit", detail={"from": row["id"], "to": attachment_id,
                                                                  "operations": len(operations), "method": result.get("method")})
        return {**public(bound), "changes": changes, "warnings": [str(w) for w in result.get("warnings") or []],
                "method": result.get("method"), "sheets": result.get("sheets") or []}

    # Saved on this PC ------------------------------------------------------------------------------------------------------
    def save_to_downloads(self, identity: Identity, attachment_id: str) -> dict[str, Any]:
        """Download where Wizard runs on the person's own PC: Wizard writes the copy into their Downloads folder itself,
        with Excel when Office runs here, instead of the browser. A browser download of a workbook Excel saved can fail
        there ("Couldn't finish download"), and a NASCA-protected copy the browser wrote would not open."""
        row = self.store.attachment(identity.id, attachment_id)
        source = self.original(row) if row and row.get("origin") != "local" else None
        if row is None or source is None or not source.is_file():
            raise AttachmentError(404, "That file is not available.")
        folder = downloads_folder()
        target = free_name(folder, row["filename"])
        result = self._docs("save-copy", str(source), "--out", str(target), "--office", self.settings.attachment_office)
        if result.get("status") != "ok" or not target.is_file():
            self.store.audit(identity.id, "attachment:save", outcome="failed", detail={"attachment_id": attachment_id})
            raise AttachmentError(422, f"{row['filename']} was not saved: {result.get('note') or 'unknown reason'}.")
        self.saved[(identity.id, attachment_id)] = target
        self.store.audit(identity.id, "attachment:save", detail={"attachment_id": attachment_id, "method": result.get("method")})
        return {"filename": target.name, "folder": str(folder), "method": result.get("method"),
                "warnings": [str(w) for w in result.get("warnings") or []]}

    def open_saved(self, identity: Identity, attachment_id: str) -> None:
        """Open the copy saved in Downloads with its application (Excel), on the person's click."""
        path = self.saved.get((identity.id, attachment_id))
        if path is None or not path.is_file():
            raise AttachmentError(404, "Download the file again: it is no longer where Wizard saved it.")
        start = getattr(os, "startfile", None)
        if start is None:
            raise AttachmentError(409, f"Open {path.name} from {path.parent}.")
        try:
            start(str(path))
        except OSError as error:
            raise AttachmentError(409, f"{path.name} did not open ({error.strerror or error}); open it from {path.parent}.") from None
        self.store.audit(identity.id, "attachment:open", detail={"attachment_id": attachment_id})

    def remove(self, identity: Identity, attachment_id: str) -> bool:
        removed = self.store.delete_attachment(identity.id, attachment_id)
        if removed:
            shutil.rmtree(removed["folder"], ignore_errors=True)
        return removed is not None
