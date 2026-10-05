"""Files attached to a question: PowerPoint, Excel, Word, email, CSV and text, converted to text that Gemini reads with
wizard_read_attachment.

Conversion runs in a separate process (scripts/wizard_docs.py convert), one file at a time and time-limited, so a stuck
Office dialog cannot stall Wizard. Files are kept per user under <data>/attachments/<user>/<attachment id>/.

Two ways in:
- Upload: the browser sends the bytes. Fine for ordinary files; a NASCA-protected file may not open from the uploaded
  copy, because NASCA binds access to the original path.
- From this PC (local installs): the person picks a file in their own Downloads, Desktop or Documents (or the folders
  in WIZARD_ATTACHMENT_FOLDERS) and Wizard reads the original where it is, which is how protected files open."""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
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
        self._lock: asyncio.Lock | None = None

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

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

    async def attach_local(self, identity: Identity, path_text: str) -> dict[str, Any]:
        if not self.local_enabled():
            raise AttachmentError(403, "Attaching files from this PC is switched off here; upload the file instead.")
        try:
            path = Path(path_text).resolve(strict=True)
        except (OSError, RuntimeError):
            raise AttachmentError(404, "That file no longer exists.") from None
        allowed = [base.resolve() for base in self.settings.attachment_folders]
        if not path.is_file() or not any(path.is_relative_to(base) for base in allowed):
            raise AttachmentError(403, "Only files in your Downloads, Desktop or Documents folders can be attached this way.")
        name = self.check_name(path.name, path.stat().st_size)
        attachment_id = new_id("att")
        folder = self.folder(identity.id, attachment_id)
        folder.mkdir(parents=True, exist_ok=True)
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%d")
        return await self._convert(identity, attachment_id, path, folder, name, "local", str(path), modified)

    # Conversion ----------------------------------------------------------------------------------------------------------
    async def _convert(self, identity: Identity, attachment_id: str, source: Path, folder: Path, name: str, origin: str,
                       source_path: str | None, modified: str) -> dict[str, Any]:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        command = [sys.executable, str(ROOT / "scripts" / "wizard_docs.py"), "convert", str(source),
                   "--out", str(folder / "converted"), "--json", "--slide-images", "none",
                   "--office", self.settings.attachment_office]
        async with self.lock:  # one Office conversion at a time
            try:
                completed = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True,
                                                    encoding="utf-8", errors="replace",
                                                    timeout=self.settings.attachment_timeout_s)
                lines = [line for line in (completed.stdout or "").splitlines() if line.startswith("{")]
                result: dict[str, Any] = json.loads(lines[-1]) if lines else {
                    "status": "failed", "note": ((completed.stderr or "").strip().splitlines() or ["no output"])[-1][:300]}
            except subprocess.TimeoutExpired:
                result = {"status": "failed", "note": f"Office did not finish within {self.settings.attachment_timeout_s} "
                                                      "seconds (a dialog such as a password prompt may be open in Office)"}
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
        self.store.add_attachment(row)
        self.store.audit(identity.id, "attachment:add", outcome=str(row["status"]),
                         detail={"attachment_id": attachment_id, "kind": row["kind"], "origin": origin, "bytes": row["bytes"]})
        return public(row)

    def remove(self, identity: Identity, attachment_id: str) -> bool:
        removed = self.store.delete_attachment(identity.id, attachment_id)
        if removed:
            shutil.rmtree(removed["folder"], ignore_errors=True)
        return removed is not None
