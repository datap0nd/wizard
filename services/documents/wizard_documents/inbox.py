"""Bulk conversion of a content inbox into text Gemini CLI can read (it skips Office files and emails as binary).

Reads <content>/inbox/** and writes, per document:
  inbox/_text/<same relative path>.md      the text, after a small header (source id, kind, dates, parent email)
  inbox/_text/<same relative path>.assets/ slide images for mostly-visual slides
  inbox/_text/manifest.csv                 one row per file: source id, path, kind, status, characters, note
Email attachments are saved to inbox/_attachments/<email source id>/ (Outlook exports keep theirs in a sibling
'<email>.attachments' folder) and converted like any other document, with the email as their parent.

A source id is "S-" + the first 8 hex characters of the file's SHA-256: the same file always gets the same id, so notes
can cite it, and a deck attached to five emails is read once (the copies are listed as duplicates). Re-running only
converts new or changed files and retries failures. Email addresses and phone numbers are masked unless asked not to."""
from __future__ import annotations

import csv
import hashlib
import shutil
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .common import MAX_TEXT_CHARS, ConversionError, kind_of, mask_contacts
from .convert import Converter
from .office import OfficeUnavailable

MAX_FILE_BYTES = 150 * 1024 * 1024
SMALL_IMAGE_BYTES = 30 * 1024  # images this small inside emails are signatures and logos


@dataclass
class Row:
    source_id: str
    path: str
    kind: str
    status: str  # ok | native | duplicate | skipped | failed | empty
    method: str
    chars: int
    images: int
    modified: str
    bytes: int
    sha256: str
    text_path: str
    parent: str
    note: str


COLUMNS = [f.name for f in fields(Row)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, Row]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    rows = {}
    for record in records:
        values: dict[str, Any] = {key: record.get(key) or "" for key in COLUMNS}
        for number in ("chars", "images", "bytes"):
            values[number] = int(values[number] or 0)
        rows[values["path"]] = Row(**values)
    return rows


class Inbox:
    def __init__(self, content: Path, converter: Converter, keep_contacts: bool = False, force: bool = False):
        self.content = content
        self.inbox = content / "inbox"
        self.out = self.inbox / "_text"
        self.attachments = self.inbox / "_attachments"
        self.converter = converter
        self.keep_contacts = keep_contacts
        self.manifest = self.out / "manifest.csv"
        self.previous = {} if force else read_manifest(self.manifest)
        self.rows: dict[str, Row] = {}
        self.first_path: dict[str, str] = {}  # sha256 -> the path whose text stands for every copy
        self.external: dict[Path, str] = {}   # files read in place from folders listed in inbox/_sources.txt

    def relative(self, path: Path) -> str:
        return self.external.get(path) or path.relative_to(self.inbox).as_posix()

    def source_folders(self) -> list[Path]:
        """Folders listed in inbox/_sources.txt (one per line, # comments), read where they are instead of copied:
        NASCA-protected files may only open from their original place."""
        listing = self.inbox / "_sources.txt"
        if not listing.is_file():
            return []
        folders = []
        for line in listing.read_text(encoding="utf-8-sig").splitlines():
            entry = line.strip().strip('"')
            if entry and not entry.startswith("#") and Path(entry).is_dir():
                folders.append(Path(entry).resolve())
        return folders

    def files(self) -> list[Path]:
        """Every document under inbox/ (saved attachments included, not the generated _text/ or _digests/), then the
        documents of the folders listed in inbox/_sources.txt."""
        found = []
        for path in sorted(self.inbox.rglob("*")):
            relative = path.relative_to(self.inbox)
            top = relative.parts[0]
            if path.is_file() and (not top.startswith("_") or top == "_attachments") \
                    and not path.name.startswith(("~$", ".")):
                found.append(path)
        for folder in self.source_folders():
            label = f"_external/{folder.name}-{hashlib.sha1(str(folder).lower().encode(), usedforsecurity=False).hexdigest()[:6]}"
            for path in sorted(folder.rglob("*")):
                if path.is_file() and not path.name.startswith(("~$", ".")) and kind_of(path) != "other":
                    self.external[path] = f"{label}/{path.relative_to(folder).as_posix()}"
                    found.append(path)
        return found

    def shown(self, path: Path) -> str:
        """Where Gemini finds the original: inbox/... for collected files, the full path for files read in place."""
        return str(path) if path in self.external else f"inbox/{self.relative(path)}"

    def parent_of(self, path: Path) -> str:
        """The source id of the email a file was attached to, if any."""
        if path in self.external:
            return ""
        parts = path.relative_to(self.inbox).parts
        if len(parts) > 2 and parts[0] == "_attachments":
            return parts[1]
        for folder in path.parents:
            if folder == self.inbox:
                break
            if folder.name.endswith(".attachments"):
                email = folder.with_name(folder.name[: -len(".attachments")])
                if email.is_file():
                    return f"S-{sha256(email)[:8]}"
        return ""

    def run(self) -> dict[str, int]:
        self.out.mkdir(parents=True, exist_ok=True)
        queue = self.files()
        while queue:
            following: list[Path] = []
            for path in queue:
                following += self.extract(path)
            queue = following
        self.write_manifest()
        counts: dict[str, int] = {}
        for row in self.rows.values():
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts

    def extract(self, path: Path) -> list[Path]:
        if not path.is_file():  # an attachment folder rewritten earlier in this run
            return []
        relative, stat = self.relative(path), path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%d")
        old = self.previous.get(relative)
        if old and old.bytes == stat.st_size and old.modified == modified and old.status != "failed" \
                and (old.status != "ok" or (self.content / old.text_path).is_file()):
            self.rows[relative] = old
            if old.status != "duplicate":
                self.first_path.setdefault(old.sha256, relative)
            return []
        kind = kind_of(path)
        digest = sha256(path)
        source_id = f"S-{digest[:8]}"
        row = Row(source_id, relative, kind, "ok", "", 0, 0, modified, stat.st_size, digest, "", self.parent_of(path), "")
        self.rows[relative] = row
        if self.first_path.setdefault(digest, relative) != relative:
            row.status, row.note = "duplicate", f"same content as inbox/{self.first_path[digest]}"
            return []
        if stat.st_size > MAX_FILE_BYTES:
            row.status, row.note = "skipped", "larger than 150 MB"
            return []
        if kind in ("pdf", "image"):
            if kind == "image" and row.parent and stat.st_size < SMALL_IMAGE_BYTES:
                row.status, row.note = "skipped", "small image inside an email (signature or logo)"
            else:
                row.status, row.method, row.text_path = "native", "gemini-cli", self.shown(path)
            return []
        if kind == "other":
            row.status, row.note = "skipped", f"unsupported file type {path.suffix or '(none)'}"
            return []
        target = self.out / f"{relative}.md"
        assets = self.out / f"{relative}.assets"
        attachments = self.attachments / source_id
        for folder in (assets, attachments if kind == "email" else None):
            if folder is not None and folder.is_dir():
                shutil.rmtree(folder)  # converting again rewrites images and attachments
        try:
            converted = self.converter.convert(path, assets, attachments)
        except OfficeUnavailable as error:
            row.status, row.note = "failed", f"Office automation unavailable: {error}"
            return []
        except ConversionError as error:
            row.status, row.note = "failed", str(error)[:300]
            return []
        except Exception as error:  # noqa: BLE001 - one bad document must not stop the batch
            row.status, row.note = "failed", f"{type(error).__name__}: {str(error)[:250]}"
            return []
        text = converted.text if self.keep_contacts else mask_contacts(converted.text)
        notes = list(converted.notes)
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + f"\n\n(truncated: first {MAX_TEXT_CHARS} characters)"
            notes.append("truncated")
        row.method, row.chars, row.images = converted.method, len(text), len(converted.images)
        row.note = "; ".join(notes)[:300]
        if not text.strip() and not converted.images:
            row.status = "empty"
        header = [f"source_id: {source_id}", f"source_path: {self.shown(path)}", f"kind: {kind}", f"modified: {modified}",
                  f"extracted: {datetime.now(UTC).strftime('%Y-%m-%d')} ({converted.method})"]
        if row.parent:
            header.append(f"attached_to: {row.parent}")
        if converted.images:
            header.append(f"slide_images: {len(converted.images)} in {target.name[:-3]}.assets/ (look at them)")
        if converted.attachments:
            header.append(f"attachments: {len(converted.attachments)} (converted separately, attached_to {source_id})")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("---\n" + "\n".join(header) + "\n---\n\n" + text + "\n", encoding="utf-8")
        row.text_path = target.relative_to(self.content).as_posix()
        return converted.attachments

    def write_manifest(self) -> None:
        with self.manifest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            for relative in sorted(self.rows):
                writer.writerow(asdict(self.rows[relative]))
