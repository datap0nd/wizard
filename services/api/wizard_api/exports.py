"""A visual the person exported from an answer (a PowerPoint slide, an Excel workbook of its data, a picture), saved in
their Downloads folder by Wizard itself where Wizard runs on their own PC, as Download does for edited copies
(docs/decisions/2026-10-23-edited-attachments.md): a browser download can fail on the work PC. The page builds the file
from what it already shows; Wizard only checks that it is the kind of file its name says and writes it, never over an
existing file. Elsewhere (a server, the Pages site) the browser downloads it."""
from __future__ import annotations

import io
import os
import re
import secrets
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import attachments
from .attachments import AttachmentError

MAX_BYTES = 25 * 1024 * 1024
NAME_CHARS = 120
ZIP = b"PK\x03\x04"
# What each kind of export must hold: an Office file is a zip with its main part; a picture starts with its signature.
KINDS: dict[str, tuple[bytes, str | None]] = {
    ".pptx": (ZIP, "ppt/presentation.xml"),
    ".xlsx": (ZIP, "xl/workbook.xml"),
    ".png": (b"\x89PNG\r\n\x1a\n", None),
}


def _problem(suffix: str, data: bytes) -> AttachmentError | None:
    if suffix not in KINDS:
        return AttachmentError(415, "Wizard saves only PowerPoint (.pptx), Excel (.xlsx) and picture (.png) exports.")
    if len(data) > MAX_BYTES:
        return AttachmentError(413, f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    signature, part = KINDS[suffix]
    wrong = AttachmentError(415, f"That is not a {suffix} file.")
    if not data.startswith(signature):
        return wrong
    if part:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return wrong
        if part not in names or "[Content_Types].xml" not in names:
            return wrong
    return None


def clean_name(filename: str) -> str:
    """The file's own name, without folders, at most NAME_CHARS characters, its suffix kept."""
    name = re.split(r"[\\/]", filename.strip())[-1]
    if name.startswith(".") and name.count(".") == 1:  # ".pptx": a kind without a name
        name = "Wizard visual" + name
    suffix = Path(name).suffix.lower()
    stem = Path(name).stem.strip()[: NAME_CHARS - len(suffix)].strip() or "Wizard visual"
    return stem + suffix


class Exports:
    """The exports saved on this PC, so Open opens the one the person saved (and only that one)."""

    def __init__(self, folder: Callable[[], Path] | None = None):
        self._folder = folder
        self.saved: dict[tuple[str, str], Path] = {}

    def folder(self) -> Path:
        return self._folder() if self._folder else attachments.downloads_folder()

    def save(self, identity_id: str, filename: str, data: bytes) -> dict[str, Any]:
        name = clean_name(filename)
        problem = _problem(Path(name).suffix.lower(), data)
        if problem:
            raise problem
        folder = self.folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target = attachments.free_name(folder, name)
            with target.open("xb") as out:  # never over a file that appeared meanwhile
                out.write(data)
        except FileExistsError:
            raise AttachmentError(409, f"{name} appeared in {folder} meanwhile; save it again.") from None
        except OSError as error:
            raise AttachmentError(409, f"{name} was not saved in {folder}: {error.strerror or error}.") from None
        token = secrets.token_hex(8)
        self.saved[(identity_id, token)] = target
        return {"id": token, "filename": target.name, "folder": str(folder)}

    def open(self, identity_id: str, token: str) -> Path:
        """Open a saved export with its application (PowerPoint, Excel), on the person's click."""
        path = self.saved.get((identity_id, token))
        if path is None or not path.is_file():
            raise AttachmentError(404, "Download it again: the file is no longer where Wizard saved it.")
        start = getattr(os, "startfile", None)
        if start is None:
            raise AttachmentError(409, f"Open {path.name} from {path.parent}.")
        try:
            start(str(path))
        except OSError as error:
            raise AttachmentError(409, f"{path.name} did not open ({error.strerror or error}); open it from {path.parent}.") from None
        return path
