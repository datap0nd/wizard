"""Validate an external content folder (the internal wizard-content repository) before Wizard loads it.

Layout: <dir>/contracts/sources/<platform>.json (report catalogs) and optionally <dir>/knowledge/**/*.md (platform
guides and definitions). Used by `scripts/validate_content.py` and by the API at start-up (WIZARD_CONTENT_DIR): any
error stops the service with a readable message instead of serving a half-valid catalog.

Real content may only describe reports; it cannot make a report readable. Until a live adapter and a signed parity
check exist, every report must be NAVIGATION_ONLY with no fixture file, and no system may claim ROWS_VERIFIED."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .catalog import SourceContract
from .knowledge import FRONT_MATTER

LIVE_ADAPTERS: set[str] = set()  # systems with an approved, parity-tested live adapter (none yet)
SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "Google access token": re.compile(r"ya29\.[0-9A-Za-z_\-]{20,}"),
    "Google refresh token": re.compile(r"1//0[0-9A-Za-z_\-]{30,}"),
    "OAuth client secret": re.compile(r"GOCSPX-[0-9A-Za-z_\-]{20,}"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "password assignment": re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]"),
    "MicroStrategy auth token": re.compile(r"X-MSTR-AuthToken:\s*[0-9a-z]{20,}"),
}


@dataclass(frozen=True)
class Problem:
    level: str  # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()} {self.where}: {self.message}"


def _secrets(text: str, where: str) -> list[Problem]:
    return [Problem("error", where, f"looks like a {name}; content files must never hold credentials")
            for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]


def validate_content(root: Path) -> list[Problem]:
    problems: list[Problem] = []
    sources = root / "contracts" / "sources"
    if not root.is_dir():
        return [Problem("error", str(root), "content folder does not exist")]
    files = sorted(sources.glob("*.json")) if sources.is_dir() else []
    if not files:
        problems.append(Problem("error", "contracts/sources", "no report catalogs found (expected <platform>.json files)"))
    seen_reports: dict[str, str] = {}
    for path in files:
        where = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        problems += _secrets(text, where)
        try:
            contract = SourceContract.model_validate(json.loads(text))
        except json.JSONDecodeError as error:
            problems.append(Problem("error", where, f"not valid JSON: {error.msg} (line {error.lineno})"))
            continue
        except ValidationError as error:
            for item in error.errors()[:10]:
                location = ".".join(str(p) for p in item["loc"])
                problems.append(Problem("error", where, f"{location}: {item['msg']}"))
            continue
        system = contract.system
        if path.stem != system.id:
            problems.append(Problem("error", where, f"file name must match system id '{system.id}'"))
        if system.connector.status in ("ROWS_VERIFIED", "SYNTHETIC_FIXTURE") and system.id not in LIVE_ADAPTERS:
            problems.append(Problem("error", where, f"connector status {system.connector.status} is not allowed for real "
                                                    "content: no approved live adapter exists for this system yet "
                                                    "(use NAVIGATION_ONLY)"))
        if system.connector.data_mode == "SYNTHETIC":
            problems.append(Problem("error", where, "data_mode SYNTHETIC belongs in the Wizard repo, not in real content"))
        folders = {f.id for f in contract.folders}
        for folder in contract.folders:
            if folder.parent and folder.parent not in folders:
                problems.append(Problem("error", where, f"folder {folder.id} has unknown parent {folder.parent}"))
        for report in contract.reports:
            label = f"{where} › {report.id}"
            if not report.id.startswith(f"{system.id}-"):
                problems.append(Problem("error", label, f"report id must start with '{system.id}-'"))
            if report.id in seen_reports:
                problems.append(Problem("error", label, f"duplicate report id (also in {seen_reports[report.id]})"))
            seen_reports[report.id] = where
            if report.folder not in folders:
                problems.append(Problem("error", label, f"unknown folder '{report.folder}'"))
            if report.row_access == "ROWS" and system.id not in LIVE_ADAPTERS:
                problems.append(Problem("error", label, "row_access ROWS needs an approved live adapter and signed parity; "
                                                        "keep it NAVIGATION_ONLY"))
            if report.file is not None:
                problems.append(Problem("error", label, "file must be null: real content never points at data files"))
            for measure in report.measures:
                if measure.type in ("currency", "percent") and not measure.unit:
                    problems.append(Problem("error", label, f"measure {measure.key} needs a unit"))
                if measure.type == "percent" and measure.aggregation != "none":
                    problems.append(Problem("error", label, f"measure {measure.key} is a percentage and must not be summed"))
            if not report.description.strip():
                problems.append(Problem("warning", label, "missing description: Gemini will struggle to choose this report"))
            if any(c.upper().startswith("UNCERTAIN") for c in report.caveats):
                problems.append(Problem("warning", label, "has UNCERTAIN choices waiting for owner review"))
    knowledge = root / "knowledge"
    for note in sorted(knowledge.rglob("*.md")) if knowledge.is_dir() else []:
        where = note.relative_to(root).as_posix()
        if note.name == "README.md":
            continue
        text = note.read_text(encoding="utf-8").replace("\r\n", "\n")
        problems += _secrets(text, where)
        match = FRONT_MATTER.match(text)
        if not match:
            problems.append(Problem("error", where, "missing front matter (id, title, status, owner, tags)"))
            continue
        meta: dict[str, str] = {}
        for line in match.group(1).splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        for key in ("id", "title", "status", "owner", "tags"):
            if not meta.get(key):
                problems.append(Problem("error", where, f"front matter needs '{key}'"))
        if meta.get("status") not in (None, "", "DRAFT_UNSIGNED", "SIGNED"):
            problems.append(Problem("error", where, "status must be DRAFT_UNSIGNED or SIGNED"))
    for stray in root.rglob("*"):
        if stray.is_file() and stray.suffix.lower() in (".csv", ".xlsx", ".xls", ".docx", ".parquet") \
                and "register" not in stray.parts and "inbox" not in stray.parts:
            problems.append(Problem("error", stray.relative_to(root).as_posix(),
                                    "data or document files do not belong in content (only register/*.csv)"))
    return problems


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level == "error"]
