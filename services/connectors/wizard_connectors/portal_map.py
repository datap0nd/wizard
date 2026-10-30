"""What Wizard has learned about a company portal, kept so a question goes straight to the right report.

Owner decision (30 October 2026, docs/decisions/2026-10-30-portal-maps.md): Gemini (3.8 Flash) explores a portal such
as GSCM in rounds and writes down everything a later question needs to be fast: how the application works and the
shortcuts it proved (topics), and per report its menu path and id, how to open it the quickest way, its filters and
their values, the datasets and columns it fills, and the data requests that return its rows with the filters as
parameters. A question then reads the map (portal_map) and reads the data in one or two portal_run calls instead of
exploring.

One map per portal, as JSON on this PC (data/portal-maps/<portal>.json). When this PC has the knowledge base's write
token, Wizard publishes it to the knowledge-base repository (portal-maps/<portal>.json and a readable .md beside it),
and a PC without a map of its own starts from the published one. Maps hold metadata only: no rows, and secrets are
removed on every save."""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import portals
from .content import _secrets
from .knowledge import terms

FORMAT = 1
STATUSES = ("todo", "mapped", "partial", "failed", "skipped")
MAX_REPORTS = 3000
MAX_TOPICS = 100
MAX_LOG = 60
INDEX_LIMIT = 400        # reports listed in the map summary; the rest are found with portal_map(find=...)
TOPICS_INLINE = 16_000   # topic texts shown in full in the summary up to this many characters in all
# How much each part of a report counts when a question's words are matched against the map.
WEIGHTS = (("name", 4.0), ("path", 2.5), ("summary", 2.0), ("menu_id", 3.0), ("id", 2.0), ("filters", 1.0),
           ("data", 1.0), ("notes", 0.5))


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def empty(system: str, name: str = "") -> dict[str, Any]:
    return {"format": FORMAT, "system": system, "name": name or system, "updated": None, "overview": "", "topics": [],
            "reports": [], "log": []}


def clean(value: Any, depth: int = 0) -> Any:
    """A value as a map may keep it: secrets by name removed, long opaque tokens shortened, sizes bounded."""
    if depth > 8:
        return None
    if isinstance(value, str):
        return portals.scrub(value)[:100_000]
    if isinstance(value, dict):
        return {str(k)[:200]: (portals.REDACTED if portals.SECRET_NAME.search(str(k)) else clean(v, depth + 1))
                for k, v in list(value.items())[:200]}
    if isinstance(value, list):
        return [clean(v, depth + 1) for v in value[:500]]
    return value


@dataclass
class Published:
    outcome: str  # published | unchanged | failed | not_configured
    message: str
    commit: str | None = None


# Writes files to the knowledge-base repository: (files by repository path, commit message) -> outcome.
Writer = Callable[[dict[str, bytes], str], Published]


class PortalMaps:
    def __init__(self, local: Path, published: Path | None = None, writer: Writer | None = None,
                 names: dict[str, str] | None = None, repo_prefix: str = ""):
        self.local = local
        self.published = published  # the knowledge base's portal-maps folder, when one is synced
        self.writer = writer
        self.names = names or {}
        self.repo_prefix = repo_prefix.strip("/")
        self._lock = threading.RLock()

    # Reading -----------------------------------------------------------------------------------------------------------
    def path(self, system: str) -> Path:
        return self.local / f"{system}.json"

    def load(self, system: str) -> dict[str, Any]:
        places = [self.path(system)] + ([self.published / f"{system}.json"] if self.published else [])
        for path in places:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(value, dict) and value.get("system") == system:
                base = empty(system, self.names.get(system, ""))
                return {**base, **value}
        return empty(system, self.names.get(system, ""))

    def counts(self, data: dict[str, Any]) -> dict[str, int]:
        counts = dict.fromkeys(STATUSES, 0)
        for report in data["reports"]:
            counts[report.get("status") or "todo"] = counts.get(report.get("status") or "todo", 0) + 1
        return counts

    def status(self, system: str) -> dict[str, Any]:
        data = self.load(system)
        counts = self.counts(data)
        return {"system": system, "updated": data.get("updated"), "has_overview": bool(data.get("overview")),
                "topics": len(data["topics"]), "reports": len(data["reports"]), **{f"reports_{k}": v for k, v in counts.items()},
                "published": data.get("published"), "source": self._source(system),
                "can_publish": self.writer is not None}

    def _source(self, system: str) -> str:
        if self.path(system).is_file():
            return "this_pc"
        if self.published and (self.published / f"{system}.json").is_file():
            return "knowledge_base"
        return "none"

    def summary(self, system: str) -> dict[str, Any]:
        """The map as a question first sees it: the overview and shortcuts, the counts, and the report index."""
        data = self.load(system)
        counts = self.counts(data)
        topics_chars = sum(len(t.get("text") or "") for t in data["topics"])
        topics = [{"id": t["id"], "title": t.get("title"), **({"text": t.get("text")} if topics_chars <= TOPICS_INLINE else {})}
                  for t in data["topics"]]
        ready = [r for r in data["reports"] if r.get("status") in ("mapped", "partial")]
        index = [{"id": r["id"], "name": r.get("name"), "path": " > ".join(r.get("path") or []), "status": r.get("status"),
                  **({"fast": True} if any(q.get("verified") for q in r.get("requests") or []) or r.get("script") else {})}
                 for r in ready[:INDEX_LIMIT]]
        out: dict[str, Any] = {"updated": data.get("updated"), "overview": data.get("overview") or None, "topics": topics,
                               "counts": counts, "reports": index}
        if len(ready) > INDEX_LIMIT:
            out["more_reports"] = f"{len(ready) - INDEX_LIMIT} more mapped reports: find them with portal_map(find=...)."
        if topics_chars > TOPICS_INLINE:
            out["topics_note"] = "Read a topic in full with portal_map(topic=...)."
        return out

    def report(self, system: str, report_id: str) -> dict[str, Any] | None:
        key = report_id.strip().lower()
        for report in self.load(system)["reports"]:
            if report["id"] == key or str(report.get("menu_id") or "").lower() == key:
                return report
        return None

    def topic(self, system: str, topic_id: str) -> dict[str, Any] | None:
        return next((t for t in self.load(system)["topics"] if t["id"] == topic_id.strip().lower()), None)

    def todo(self, system: str, limit: int = 40, include: tuple[str, ...] = ("todo", "partial", "failed")) -> list[dict[str, Any]]:
        order = {status: index for index, status in enumerate(include)}
        waiting = [r for r in self.load(system)["reports"] if (r.get("status") or "todo") in include]
        waiting.sort(key=lambda r: order[r.get("status") or "todo"])
        return [{"id": r["id"], "name": r.get("name"), "path": r.get("path"), "menu_id": r.get("menu_id"),
                 "status": r.get("status"), **({"notes": r["notes"]} if r.get("notes") else {})} for r in waiting[:limit]]

    def find(self, system: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
        words = set(terms(query))
        if not words:
            return []
        scored = []
        for report in self.load(system)["reports"]:
            score = 0.0
            for key, weight in WEIGHTS:
                value = report.get(key)
                text = json.dumps(value, ensure_ascii=False) if isinstance(value, list | dict) else str(value or "")
                found = set(terms(text))
                score += weight * len(words & found)
            if score:
                score += 0.5 if report.get("status") == "mapped" else 0
                scored.append((score, report))
        scored.sort(key=lambda pair: -pair[0])
        return [report for _, report in scored[:limit]]

    # Writing -----------------------------------------------------------------------------------------------------------
    def save(self, system: str, *, overview: str | None = None, topics: list[dict[str, Any]] | None = None,
             reports: list[dict[str, Any]] | None = None, remove: list[str] | None = None,
             note: str | None = None) -> dict[str, Any]:
        """Merge what Gemini learned into the map: the overview replaces the old one, topics and reports are added or
        updated by id (only the fields given change), `remove` drops reports by id."""
        with self._lock:
            data = self.load(system)
            stamp = now()
            added, updated = [], []
            if overview is not None:
                data["overview"] = clean(overview.strip())
            for topic in topics or []:
                topic = clean(topic)
                old = next((t for t in data["topics"] if t["id"] == topic["id"]), None)
                if old is None:
                    if len(data["topics"]) >= MAX_TOPICS:
                        raise MapError(f"The map already has {MAX_TOPICS} topics: update an existing one instead.")
                    data["topics"].append({**topic, "updated": stamp})
                else:
                    old.update({k: v for k, v in topic.items() if v is not None}, updated=stamp)
            by_id = {r["id"]: r for r in data["reports"]}
            for report in reports or []:
                report = clean({k: v for k, v in report.items() if v is not None})
                old = by_id.get(report["id"])
                if old is None:
                    if len(data["reports"]) >= MAX_REPORTS:
                        raise MapError(f"The map already has {MAX_REPORTS} reports.")
                    entry = {"status": "todo", **report, "updated": stamp}
                    data["reports"].append(entry)
                    by_id[entry["id"]] = entry
                    added.append(entry["id"])
                else:
                    old.update(report, updated=stamp)
                    updated.append(old["id"])
            gone = set(remove or [])
            if gone:
                data["reports"] = [r for r in data["reports"] if r["id"] not in gone]
            if note:
                data["log"] = [*data.get("log", []), {"at": stamp, "note": clean(note.strip())[:600]}][-MAX_LOG:]
            data["updated"] = stamp
            data["name"] = self.names.get(system, data.get("name") or system)
            self._write(system, data)
            return {"added": added, "updated": updated, "removed": sorted(gone), "counts": self.counts(data)}

    def forget(self, system: str) -> bool:
        with self._lock:
            path = self.path(system)
            if not path.is_file():
                return False
            path.unlink()
            return True

    def _write(self, system: str, data: dict[str, Any]) -> None:
        self.local.mkdir(parents=True, exist_ok=True)
        path = self.path(system)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    # Publishing to the knowledge base --------------------------------------------------------------------------------
    def repo_path(self, name: str) -> str:
        return "/".join(p for p in (self.repo_prefix, "portal-maps", name) if p)

    def publish(self, system: str) -> Published:
        """Commit this PC's map to the knowledge-base repository (the JSON Wizard reads and a readable page)."""
        if self.writer is None:
            return Published("not_configured", "No knowledge-base write token on this PC (Settings → Knowledge base).")
        with self._lock:
            data = self.load(system)
            if not self.path(system).is_file():
                return Published("unchanged", "This PC has no map of its own to publish.")
            body = {k: v for k, v in data.items() if k != "published"}
            text = json.dumps(body, indent=1, ensure_ascii=False)
            found = _secrets(text, f"portal-maps/{system}.json")
            if found:  # the knowledge base's own check would refuse the whole commit on every PC
                return Published("failed", f"Not published: the map {found[0].message}. Remove it from the map first.")
            files = {self.repo_path(f"{system}.json"): text.encode("utf-8"),
                     self.repo_path(f"{system}.md"): render(body).encode("utf-8")}
        counts = self.counts(data)
        try:
            result = self.writer(files, f"Wizard: {data.get('name') or system} map ({counts['mapped']} reports mapped, "
                                        f"{counts['todo']} to do)")
        except Exception as error:  # noqa: BLE001 - reported in the map's status, never fatal
            result = Published("failed", str(error)[:400])
        with self._lock:
            data = self.load(system)
            data["published"] = {"at": now(), "outcome": result.outcome, "message": result.message[:400],
                                 "commit": result.commit}
            self._write(system, data)
        return result


class MapError(ValueError):
    pass


def render(data: dict[str, Any]) -> str:
    """The map as a page people can read in the repository."""
    counts: dict[str, int] = {}
    for report in data.get("reports", []):
        counts[report.get("status") or "todo"] = counts.get(report.get("status") or "todo", 0) + 1
    lines = [f"# {data.get('name') or data.get('system')} map", "",
             f"Written by Wizard's Gemini while exploring the portal; updated {data.get('updated')}. "
             f"Reports: {', '.join(f'{v} {k}' for k, v in sorted(counts.items())) or 'none yet'}. Wizard reads the JSON "
             "file beside this page; edit the map in Wizard (map the portal again), not here.", ""]
    if data.get("overview"):
        lines += ["## How it works", "", str(data["overview"]), ""]
    for topic in data.get("topics", []):
        lines += [f"## {topic.get('title') or topic['id']}", "", str(topic.get("text") or ""), ""]
    lines += ["## Reports", ""]
    for report in data.get("reports", []):
        path = " > ".join(report.get("path") or [])
        lines.append(f"### {report.get('name') or report['id']} ({report.get('status') or 'todo'})")
        lines.append("")
        lines.append(f"- id `{report['id']}`" + (f", menu `{report['menu_id']}`" if report.get("menu_id") else "")
                     + (f", path {path}" if path else ""))
        if report.get("summary"):
            lines.append(f"- {report['summary']}")
        if report.get("open"):
            lines.append(f"- Open: {report['open']}")
        for item in report.get("filters") or []:
            lines.append(f"- Filter {item.get('name')}: {item.get('kind') or ''} {item.get('values') or ''}".rstrip())
        for item in report.get("data") or []:
            lines.append(f"- Data {item.get('dataset')}: {', '.join(item.get('columns') or [])}")
        for item in report.get("requests") or []:
            lines.append(f"- Request {item.get('name')}: {item.get('method') or 'POST'} {item.get('url')}"
                         + (" (verified)" if item.get("verified") else ""))
        if report.get("script"):
            lines.append(f"- Saved script: {report['script']}")
        if report.get("notes"):
            lines.append(f"- Notes: {report['notes']}")
        lines.append("")
    return "\n".join(lines)
