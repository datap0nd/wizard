"""Turn one document into Markdown text (plus slide images and saved email attachments): the single entry point used
by the documentation kit (bulk, on the work PC) and by Wizard's chat attachments.

Office files go through the installed Office applications when pywin32 can drive them (richer output: slide images,
chart values, formulas, pivot tables, and the only way to open NASCA-protected files). Without Office, plain Office Open
XML files are read with the standard library; legacy formats and .msg then fail with a clear reason."""
from __future__ import annotations

from pathlib import Path

from . import ooxml
from .common import OOXML, ConversionError, Converted, kind_of, tidy
from .emails import html_text, read_eml
from .office import OfficeSession, OfficeUnavailable, read_excel, read_msg, read_powerpoint, read_word
from .tables import from_csv


class Converter:
    """Converts many files with one Office session (applications start once, on first need)."""

    def __init__(self, office: str = "auto", slide_images: str = "auto", max_rows: int = 1000, tables: bool = False):
        if office not in ("auto", "always", "never"):
            raise ValueError("office must be auto, always or never")
        self.office, self.slide_images, self.max_rows, self.tables = office, slide_images, max_rows, tables
        self._session: OfficeSession | None = None
        self._unavailable: str | None = None

    def __enter__(self) -> Converter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def session(self) -> OfficeSession | None:
        if self.office == "never" or self._unavailable:
            return None
        if self._session is None:
            try:
                self._session = OfficeSession()
            except OfficeUnavailable as error:
                self._unavailable = str(error)
                if self.office == "always":
                    raise
                return None
        return self._session

    def convert(self, path: Path, assets: Path, attachments: Path) -> Converted:
        """Read `path`. Slide images go to `assets`, email attachments to `attachments` (created only when needed)."""
        kind, suffix = kind_of(path), path.suffix.lower()
        if kind == "text":
            raw = path.read_bytes().decode("utf-8-sig", errors="replace")
            if suffix in (".html", ".htm"):
                raw = html_text(raw)
            elif suffix in (".csv", ".tsv"):
                lines = raw.splitlines()
                limit = self.max_rows + 1
                raw = "\n".join(lines[:limit]) + (f"\n(first {self.max_rows} of {len(lines) - 1} rows)" if len(lines) > limit else "")
                if self.tables:
                    table = from_csv(path, "\t" if suffix == ".tsv" else ",")
                    return Converted(tidy(raw), "text", tables=[table] if table else [])
            return Converted(tidy(raw), "text")
        if suffix == ".eml":
            return read_eml(path, attachments)
        if kind not in ("document", "slides", "spreadsheet", "email"):
            raise ConversionError(f"{suffix or 'this file type'} is not converted to text")
        session = self.session()
        if session is not None:
            try:
                if suffix == ".msg":
                    return read_msg(session, path, attachments)
                if kind == "slides":
                    return read_powerpoint(session, path, assets, self.slide_images)
                if kind == "spreadsheet":
                    return read_excel(session, path, self.max_rows, self.tables)
                return read_word(session, path)
            except OfficeUnavailable:
                raise
            except ConversionError as error:
                if suffix not in OOXML:
                    raise
                office_error = str(error)
                try:
                    converted = ooxml.read(path, self.max_rows, self.tables)
                except ConversionError:
                    raise ConversionError(f"Office could not open it: {office_error}") from None
                converted.notes.append(f"Office could not open it ({office_error}); read without Office instead.")
                return converted
        if suffix in OOXML:
            converted = ooxml.read(path, self.max_rows, self.tables)
            if self._unavailable:
                converted.notes.append(f"Read without Office ({self._unavailable}).")
            return converted
        reason = self._unavailable or "Office automation is switched off"
        raise ConversionError(f"{suffix} files need the Office applications: {reason}")


def convert(path: Path, assets: Path, attachments: Path, office: str = "auto", slide_images: str = "auto",
            max_rows: int = 1000) -> Converted:
    with Converter(office, slide_images, max_rows) as converter:
        return converter.convert(path, assets, attachments)
