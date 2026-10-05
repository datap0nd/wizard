"""Shared pieces of the document converter: file kinds, the conversion result, and text helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

KINDS = {
    "document": {".docx", ".docm", ".dotx", ".doc", ".rtf", ".odt"},
    "slides": {".pptx", ".pptm", ".ppsx", ".potx", ".ppt", ".pps", ".odp"},
    "spreadsheet": {".xlsx", ".xlsm", ".xltx", ".xls", ".xlsb", ".ods"},
    "email": {".eml", ".msg"},
    "pdf": {".pdf"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"},
    "text": {".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm", ".xml"},
}
OOXML = {".docx", ".docm", ".dotx", ".pptx", ".pptm", ".ppsx", ".potx", ".xlsx", ".xlsm", ".xltx"}
MAX_TEXT_CHARS = 300_000
MAX_COLUMNS = 60

EMAIL_ADDRESS = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<![\w-])\+?\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4}(?![\w-])")


class ConversionError(Exception):
    """The file could not be read; the message says why in words a user can act on."""


@dataclass
class Converted:
    text: str
    method: str  # office | ooxml | eml | text
    images: list[Path] = field(default_factory=list)       # slide pictures Gemini should look at
    attachments: list[Path] = field(default_factory=list)  # files saved from an email, to convert in turn
    notes: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)          # "Slide 3: Pricing", "Sheet: Markets" ... for navigation


def kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    return next((kind for kind, suffixes in KINDS.items() if suffix in suffixes), "other")


def tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0b", "\n").replace("\x0c", "\n").replace("\x07", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def mask_contacts(text: str) -> str:
    return PHONE.sub("<phone>", EMAIL_ADDRESS.sub("<email>", text))


def cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "/")


def markdown_table(rows: list[list[str]], note: str = "") -> str:
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return "(empty)"
    width = min(max(len(r) for r in rows), MAX_COLUMNS)
    rows = [(list(r) + [""] * width)[:width] for r in rows]
    lines = ["| " + " | ".join(cell(c) for c in rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(lines) + (f"\n\n{note}" if note else "")


def safe_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "attachment"
    return cleaned[:120]


def unique(path: Path) -> Path:
    candidate, number = path, 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        number += 1
    return candidate


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def chart_block(title: str, series: list[tuple[str, list[str], list[str]]]) -> str:
    """A chart as text: its title and a table of categories by series (the numbers are often the slide's message)."""
    lines = [f"Chart: {title or '(untitled chart)'}"]
    series = series[:8]
    categories = max((s[1] for s in series), key=len, default=[])
    if categories:
        rows = [["Category", *[s[0] for s in series]]]
        for index, category in enumerate(categories[:40]):
            rows.append([category, *[s[2][index] if index < len(s[2]) else "" for s in series]])
        lines.append(markdown_table(rows))
    elif series:
        lines.append("Series: " + "; ".join(f"{name}: {', '.join(values[:40])}" for name, _, values in series))
    return "\n".join(lines)
