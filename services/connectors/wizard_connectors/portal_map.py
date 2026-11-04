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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import portals
from .content import _secrets
from .knowledge import terms

FORMAT = 1
STATUSES = ("todo", "mapped", "partial", "failed", "skipped")
MAX_REPORTS = 3000
MAX_TOPICS = 300
MAX_LOG = 60
INDEX_LIMIT = 400        # reports listed in the map summary; the rest are found with portal_map(find=...)
TOPICS_INLINE = 16_000   # topic texts shown in full in the summary up to this many characters in all
# How much each part of a report counts when a question's words are matched against the map. use_for is written for
# exactly this match: the business questions and terms the report answers.
WEIGHTS = (("name", 4.0), ("use_for", 3.0), ("path", 2.5), ("summary", 2.0), ("menu_id", 3.0), ("id", 2.0),
           ("definitions", 1.0), ("filters", 1.0), ("data", 1.0), ("views", 2.0), ("notes", 0.5))
# Business routing (owner, 30 Oct 2026: "I dont see business logic saying: THIS report is used for THESE terms"): what a
# report answers, its near misses with the report to use instead, and the knowledge notes that define its terms.
ROUTING = ("use_for", "not_for", "definitions")
ROUTED = ("mapped", "partial")  # reports that need routing; a todo report gets it when it is mapped
TO_ROUTE_LIMIT = 15
# Every option a report has, not only its default view (owner, 3 Nov 2026: "explore not only default options, but all of
# them", above all the configuration a report grid's gear opens: DB4009 shows the account (OrgSales) only when it is
# added there). A mapped report keeps them in `views`; one mapped before has no `views` and is explored again.
TO_CONFIGURE_LIMIT = 15
# Saved scripts travel with the map (owner's run of 3 Nov 2026: the map named a script that was on no PC that read it,
# and the run spent a step finding that out). portal_save_script keeps a copy here, so every PC with the map can run it.
MAX_SCRIPTS = 1000


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def empty(system: str, name: str = "") -> dict[str, Any]:
    return {"format": FORMAT, "system": system, "name": name or system, "updated": None, "overview": "", "topics": [],
            "reports": [], "scripts": [], "log": []}


def clean(value: Any, depth: int = 0) -> Any:
    """A value as a map may keep it: secrets by name removed, long opaque tokens shortened, sizes bounded."""
    if depth > 8:
        return None
    if isinstance(value, str):
        return portals.scrub(value)[:500_000]
    if isinstance(value, dict):
        return {str(k)[:200]: (portals.REDACTED if portals.SECRET_NAME.search(str(k)) else clean(v, depth + 1))
                for k, v in list(value.items())[:5000]}
    if isinstance(value, list):
        return [clean(v, depth + 1) for v in value[:50_000]]
    return value


@dataclass
class Published:
    outcome: str  # published | unchanged | failed | not_configured
    message: str
    commit: str | None = None


# Writes files to the knowledge-base repository: (files by repository path, commit message) -> outcome. None removes
# that file (a task that moves, renames or removes a note).
Writer = Callable[[Mapping[str, bytes | None], str], Published]


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

    def mapped(self, system: str) -> int:
        """How many of this portal's reports are mapped or partly mapped, in this PC's map or else the published one.
        Read at start-up, so a malformed published map counts as none rather than stopping Wizard."""
        reports = self.load(system).get("reports")
        if not isinstance(reports, list):
            return 0
        return sum(1 for r in reports if isinstance(r, dict) and r.get("status") in ROUTED)

    def unrouted(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Mapped reports that do not say yet what they are for (mapped before the map kept business routing)."""
        return [r for r in data["reports"] if r.get("status") in ROUTED and not r.get("routed")]

    def unviewed(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Mapped reports whose options beyond the default view (the configuration gear, column choosers, view and
        grouping switches) were never explored: no `views`, not even an empty list saying there are none."""
        return [r for r in data["reports"] if r.get("status") in ROUTED and not isinstance(r.get("views"), list)]

    def to_configure(self, system: str, limit: int = TO_CONFIGURE_LIMIT) -> list[dict[str, Any]]:
        return [{"id": r["id"], "name": r.get("name"), "menu_id": r.get("menu_id"),
                 **{k: r[k] for k in ("open", "script") if r.get(k)},
                 "data": [{k: d[k] for k in ("dataset", "component", "columns") if d.get(k)}
                          for d in r.get("data") or [] if isinstance(d, dict)]}
                for r in self.unviewed(self.load(system))[:limit]]

    def status(self, system: str) -> dict[str, Any]:
        data = self.load(system)
        counts = self.counts(data)
        return {"system": system, "updated": data.get("updated"), "has_overview": bool(data.get("overview")),
                "topics": len(data["topics"]), "reports": len(data["reports"]), **{f"reports_{k}": v for k, v in counts.items()},
                "reports_to_route": len(self.unrouted(data)), "reports_to_configure": len(self.unviewed(data)),
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
                  **({"fast": True} if any(q.get("verified") for q in r.get("requests") or []) or r.get("script") else {}),
                  **({"proven": True} if any(q.get("proven") for q in r.get("requests") or []) else {}),
                  **({"script": r["script"]} if r.get("script") else {}),
                  **({"reply_check": r["reply_check"].get("verdict")} if isinstance(r.get("reply_check"), dict) else {})}
                 for r in ready[:INDEX_LIMIT]]
        out: dict[str, Any] = {"updated": data.get("updated"), "overview": data.get("overview") or None, "topics": topics,
                               "counts": counts, "reports": index}
        if len(ready) > INDEX_LIMIT:
            out["more_reports"] = f"{len(ready) - INDEX_LIMIT} more mapped reports: find them with portal_map(find=...)."
        if topics_chars > TOPICS_INLINE:
            out["topics_note"] = "Read a topic in full with portal_map(topic=...)."
        return out

    def report(self, system: str, report_id: str) -> dict[str, Any] | None:
        return _match(self.load(system)["reports"], report_id)

    def script(self, system: str, name: str) -> dict[str, Any] | None:
        """A script kept in the map (portal_save_script on any PC that publishes it), by name."""
        return next((s for s in self.load(system).get("scripts") or [] if isinstance(s, dict) and s.get("name") == name),
                    None)

    def script_names(self, system: str) -> list[str]:
        return [str(s["name"]) for s in self.load(system).get("scripts") or [] if isinstance(s, dict) and s.get("name")]

    def topic(self, system: str, topic_id: str) -> dict[str, Any] | None:
        return next((t for t in self.load(system)["topics"] if t["id"] == topic_id.strip().lower()), None)

    def todo(self, system: str, limit: int = 40, include: tuple[str, ...] = ("todo", "partial", "failed")) -> list[dict[str, Any]]:
        order = {status: index for index, status in enumerate(include)}
        waiting = [r for r in self.load(system)["reports"] if (r.get("status") or "todo") in include]
        waiting.sort(key=lambda r: order[r.get("status") or "todo"])
        return [{"id": r["id"], "name": r.get("name"), "path": r.get("path"), "menu_id": r.get("menu_id"),
                 "status": r.get("status"), **({"notes": r["notes"]} if r.get("notes") else {})} for r in waiting[:limit]]

    def to_route(self, system: str, limit: int = TO_ROUTE_LIMIT) -> list[dict[str, Any]]:
        """The next mapped reports without routing, with what says what they hold: enough to route them without
        opening each one."""
        return [{"id": r["id"], "name": r.get("name"), "path": " > ".join(r.get("path") or []),
                 **{k: r[k] for k in ("summary", "notes") if r.get(k)},
                 "filters": [f.get("name") for f in r.get("filters") or [] if isinstance(f, dict)],
                 "data": [{k: d[k] for k in ("dataset", "columns", "labels") if d.get(k)}
                          for d in r.get("data") or [] if isinstance(d, dict)]}
                for r in self.unrouted(self.load(system))[:limit]]

    def defined_by(self, note_id: str) -> list[tuple[str, dict[str, Any]]]:
        """Reports in the maps of this PC's portals whose `definitions` name this knowledge note."""
        return [(system, r) for system in self.names for r in self.load(system)["reports"]
                if note_id in (r.get("definitions") or [])]

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
            routed = [r["id"] for r in reports or [] if any(k in r for k in ROUTING)]
            for report_id in routed:
                by_id[report_id]["routed"] = stamp
            self._check_targets(system, data, routed)
            gone = set(remove or [])
            if gone:
                data["reports"] = [r for r in data["reports"] if r["id"] not in gone]
            if note:
                data["log"] = [*data.get("log", []), {"at": stamp, "note": clean(note.strip())[:600]}][-MAX_LOG:]
            data["updated"] = stamp
            data["name"] = self.names.get(system, data.get("name") or system)
            self._write(system, data)
            return {"added": added, "updated": updated, "removed": sorted(gone), "counts": self.counts(data)}

    def proven(self, system: str, report_id: str) -> list[dict[str, Any]]:
        """The report's requests Wizard itself proved (portal_prove_request), with their proof."""
        found = self.report(system, report_id)
        return [q for q in (found or {}).get("requests") or [] if isinstance(q, dict) and q.get("proven")]

    def prove(self, system: str, report_id: str, request: dict[str, Any], proof: dict[str, Any]) -> None:
        """Keep a request Wizard proved: it replaces the report's request of that name, marked verified with its proof.
        Only portal_prove_request calls this; what Gemini saves never sets verified (tools/portal_tools.py)."""
        with self._lock:
            data = self.load(system)
            report = _match(data["reports"], report_id)
            if report is None:
                raise MapError(f"No report '{report_id}' in the {system} map: save it first.")
            entry = clean({**{k: v for k, v in request.items() if v is not None}, "verified": True, "proven": proof})
            kept = [q for q in report.get("requests") or [] if isinstance(q, dict) and q.get("name") != entry.get("name")]
            report["requests"] = [*kept, entry]
            report["updated"] = data["updated"] = now()
            self._write(system, data)

    def check_reply(self, system: str, report_id: str, result: dict[str, Any]) -> None:
        """Keep the outcome of a check of the report's reply against a reference: its own screen for the same filters
        (wizard_compare_evidence) or a file the person gave a task (wizard_task_compare)."""
        with self._lock:
            data = self.load(system)
            report = _match(data["reports"], report_id)
            if report is None:
                raise MapError(f"No report '{report_id}' in the {system} map.")
            report["reply_check"] = clean(result)
            report["updated"] = data["updated"] = now()
            self._write(system, data)

    def keep_script(self, system: str, script: dict[str, Any]) -> None:
        """Keep a saved script in the map, replacing one of the same name: its steps, parameters and description (no
        rows; secrets removed like everything in the map)."""
        with self._lock:
            data = self.load(system)
            kept = [s for s in data.get("scripts") or [] if isinstance(s, dict) and s.get("name") != script["name"]]
            if len(kept) >= MAX_SCRIPTS:
                raise MapError(f"The map already keeps {MAX_SCRIPTS} scripts: reuse one.")
            entry = clean({k: script[k] for k in ("name", "description", "steps", "params") if k in script})
            data["scripts"] = [*kept, {**entry, "updated": now()}]
            data["updated"] = now()
            self._write(system, data)

    def route(self, system: str, reports: list[dict[str, Any]], note: str | None = None) -> dict[str, Any]:
        """Add business routing to reports already in the map, and nothing else. use_for, not_for and definitions are
        set, a summary only where the report has none, and the report is marked routed. The menu path, how to open it,
        filters, data, requests, script and status are never touched and no report is added or removed, so a routing
        pass over reports mapped earlier cannot undo what their mapping proved."""
        with self._lock:
            data = self.load(system)
            by_id = {r["id"]: r for r in data["reports"]}
            unknown = [r["id"] for r in reports if r["id"] not in by_id]
            if unknown:
                raise MapError(f"Not in the {system} map: {', '.join(unknown[:10])}. Routing only adds to reports the "
                               "map already holds; map a new report with portal_map_save.")
            stamp, kept = now(), []
            for report in reports:
                report = clean(report)
                old = by_id[report["id"]]
                old.update({key: report.get(key) or [] for key in ROUTING})
                if report.get("summary"):
                    if old.get("summary"):
                        kept.append(old["id"])
                    else:
                        old["summary"] = report["summary"]
                if report.get("routing_note"):
                    old["routing_note"] = report["routing_note"]
                old["routed"] = stamp
            self._check_targets(system, data, [r["id"] for r in reports])
            if note:
                data["log"] = [*data.get("log", []), {"at": stamp, "note": clean(note.strip())[:600]}][-MAX_LOG:]
            data["updated"] = stamp
            self._write(system, data)
            return {"routed": [r["id"] for r in reports], "summary_kept": kept, "left": len(self.unrouted(data))}

    def _check_targets(self, system: str, data: dict[str, Any], ids: list[str]) -> None:
        """A not_for written now must name a report that exists: in this map by id or menu id, or 'portal:id' in
        another portal's map. Older entries are not rechecked, so a report removed later never blocks a save."""
        missing = []
        for report in (r for r in data["reports"] if r["id"] in set(ids)):
            for item in report.get("not_for") or []:
                target = str(item.get("use_instead") or "") if isinstance(item, dict) else ""
                other, _, report_id = target.rpartition(":")
                reports = data["reports"] if other in ("", system) else self.load(other)["reports"]
                if target and _match(reports, report_id) is None:
                    missing.append(f"{report['id']} → {target}")
        if missing:
            raise MapError("not_for names reports no map holds: " + ", ".join(missing[:10]) + ". Use a report id from "
                           "this map, 'portal:id' for another portal's map, or leave use_instead empty.")

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


def _match(reports: list[dict[str, Any]], report_id: str) -> dict[str, Any] | None:
    key = report_id.strip().lower()
    return next((r for r in reports if r["id"] == key or str(r.get("menu_id") or "").lower() == key), None)


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
    if data.get("scripts"):
        lines += ["## Saved scripts", ""]
        lines += [f"- `{item.get('name')}`: {item.get('description') or ''}".rstrip(": ")
                  for item in data["scripts"] if isinstance(item, dict)]
        lines.append("")
    lines += ["## Reports", ""]
    for report in data.get("reports", []):
        path = " > ".join(report.get("path") or [])
        lines.append(f"### {report.get('name') or report['id']} ({report.get('status') or 'todo'})")
        lines.append("")
        lines.append(f"- id `{report['id']}`" + (f", menu `{report['menu_id']}`" if report.get("menu_id") else "")
                     + (f", path {path}" if path else ""))
        if report.get("summary"):
            lines.append(f"- {report['summary']}")
        if report.get("use_for"):
            lines.append(f"- Use for: {'; '.join(str(u) for u in report['use_for'])}")
        for item in report.get("not_for") or []:
            lines.append(f"- Not for: {item.get('question')}"
                         + (f" (use {item['use_instead']})" if item.get("use_instead") else ""))
        if report.get("definitions"):
            lines.append(f"- Terms defined in: {', '.join(str(d) for d in report['definitions'])}")
        if report.get("routing_note"):
            lines.append(f"- Routing: {report['routing_note']}")
        if report.get("open"):
            lines.append(f"- Open: {report['open']}")
        for item in report.get("filters") or []:
            lines.append(f"- Filter {item.get('name')}: {item.get('kind') or ''} {item.get('values') or ''}".rstrip())
        for item in report.get("data") or []:
            lines.append(f"- Data {item.get('dataset')}: {', '.join(item.get('columns') or [])}")
        for item in report.get("views") or []:
            lines.append(f"- Option {item.get('name')}: {item.get('options') or ''}".rstrip()
                         + (f" (adds {', '.join(item['columns'])})" if item.get("columns") else "")
                         + (f"; reached by {item['path']}" if item.get("path") else "")
                         + (f"; needs {item['requires']}" if item.get("requires") else ""))
        for item in report.get("requests") or []:
            lines.append(f"- Request {item.get('name')}: {item.get('method') or 'POST'} {item.get('url')}"
                         + (f" (proven by Wizard {str(item['proven'].get('at', ''))[:10]})" if isinstance(item.get("proven"), dict)
                            else " (verified, by Gemini's own account)" if item.get("verified") else ""))
        if isinstance(report.get("reply_check"), dict):
            check = report["reply_check"]
            lines.append(f"- Checked against {check.get('against') or 'a reference'} on {str(check.get('at', ''))[:10]}: "
                         f"{check.get('verdict')} ({check.get('rows_matched', 0)} of {check.get('rows_compared', 0)} rows)")
        if report.get("script"):
            lines.append(f"- Saved script: {report['script']}")
        if report.get("notes"):
            lines.append(f"- Notes: {report['notes']}")
        lines.append("")
    return "\n".join(lines)
