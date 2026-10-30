"""The Pages site: Brain and Cases, two pages of their own on the company GitHub's Pages, each at its own address and
neither linking to the other (owner decision, 30 October 2026, docs/decisions/2026-10-30-pages-site.md).

- **Brain** (`brain/`): a snapshot of what the in-app /brain page shows this PC's person: the knowledge graph (titles,
  summaries, links; never a note's text), the systems and the reports mapped in each portal, and the news as it was read.
- **Cases** (`cases/`): analyses people chose to share, one per chat: each prompt and Wizard's answer with its charts,
  tables, data labels and the names of its sources, and what Wizard did. Never a source's rows.

Wizard publishes only at the person's click, from their own PC, with the knowledge base's write token already saved
there, as one commit to a branch that is not the notes' own (WIZARD_SITE_BRANCH, gh-pages): every PC downloads the notes'
branch whenever it changes, never this one. The branch holds the pages' code (from this Wizard build's apps/web/dist/site)
and the data files beside it; GitHub Pages serves it as it is (.nojekyll). Everything published passes the knowledge
base's credential check first. Pages itself is turned on once by a repository admin (Settings → Pages: Deploy from a
branch, gh-pages, / (root)); a Contents-only token may not do that, nor read the site's address, which the person
enters in Settings → Pages site."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from wizard_agent import outbound
from wizard_agent.prompting import squeeze
from wizard_connectors.content import _secrets

from .config import Settings
from .store import Store, now

FORMAT = 1
PAGES = ("brain", "cases")
DATA = {"brain": "brain/brain.json", "cases": "cases/cases.json"}  # a page is on the site once it has its data
CASE_KINDS = ("ask", "check")      # a question and Check my data; making a brief recurring is not an analysis
CASE_TITLE = 120
TAKEAWAY = 400
MAX_TURNS = 40
MAX_STEPS = 60                     # what Wizard did, per answer
MAX_CASE_BYTES = 4 * 1024 * 1024
# What a case keeps of each source: its name and data label, never its rows, request or folders on someone's PC.
SOURCE_KEYS = ("id", "system", "system_name", "report_name", "data_mode", "as_of", "total_rows", "truncated")
VISUAL_KEYS = ("id", "kind", "title", "subtitle", "columns", "rows", "x", "series", "evidence_ids", "note", "derived_by")
CITATION = re.compile(r"\[(E\d{1,4})\]")
STEP_CATEGORIES = ("source", "knowledge", "check", "present")  # every tool call but the person-facing ones
README = """# Wizard site

GitHub Pages serves this branch (Settings → Pages: Deploy from a branch, this branch, / (root)). Wizard writes it from
the owner's PC: `brain/` is the knowledge graph as last published, `cases/` the analyses people chose to share. Each page
has its own address and neither links to the other.

Do not edit it by hand: the next publish from Wizard replaces the pages' code (`assets/`, `*/index.html`). Remove a case
from Wizard (Share as case → Remove from the site).
"""


class SiteError(Exception):
    pass


def case_id(conversation_id: str) -> str:
    """A chat's case keeps one address however often it is published again; the chat's own id is not shown."""
    return "c" + hashlib.sha256(conversation_id.encode()).hexdigest()[:14]


def steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What Wizard did for one answer, from the run's own events: each tool call it made, how it ended, its evidence."""
    started = {e["payload"].get("call_id"): e["payload"] for e in events if e["type"] == "tool_started"}
    out: list[dict[str, Any]] = []
    for event in events:
        if event["type"] != "tool_finished":
            continue
        payload = event["payload"]
        call = started.get(payload.get("call_id"), {})
        if call.get("category") not in STEP_CATEGORIES:
            continue
        out.append({"label": squeeze(str(call.get("label") or payload.get("name") or "A step"), 200),
                    "summary": squeeze(str(payload.get("summary") or ""), 300), "ok": bool(payload.get("ok")),
                    "evidence": (payload.get("evidence") or {}).get("id")})
    return out[-MAX_STEPS:]


def turns(store: Store, conversation_id: str) -> list[dict[str, Any]]:
    """Every finished answer of a chat, in order, as a case shows it."""
    from .runs import run_title

    out = []
    evidence_by_id = {e["id"]: e for e in store.evidence(conversation_id)}
    for run in store.runs(conversation_id):
        if run["kind"] not in CASE_KINDS or run["status"] != "succeeded" or not run.get("answer"):
            continue
        report = store.report(run["report_id"]) if run.get("report_id") else None
        if report and not report.get("expired"):
            answer, visuals, evidence = report["answer"], report.get("visuals") or [], report.get("evidence") or []
            check = report.get("check") or {}
        else:  # the dated report expired: the chat still has the answer, its visuals and its evidence
            answer, visuals = run["answer"], store.visuals(conversation_id, run["id"])
            evidence = [evidence_by_id[i] for i in dict.fromkeys(CITATION.findall(run["answer"])) if i in evidence_by_id]
            check = {"status": run.get("check_status"), "summary": run.get("check_summary")}
        out.append({
            "run_id": run["id"], "kind": run["kind"], "prompt": run_title(run["kind"], run["question"]),
            "asked_at": run["created_at"], "answer": answer, "data_mode": run.get("data_mode"),
            "check": {"status": check.get("status") or run.get("check_status") or "NOT_CHECKED", "summary": check.get("summary")},
            "visuals": [{k: v.get(k) for k in VISUAL_KEYS} for v in visuals],
            "sources": [{k: e.get(k) for k in SOURCE_KEYS} for e in evidence],
            "steps": steps(store.events(run["id"])), "model": run.get("runtime_label"),
        })
    return out[:MAX_TURNS]


def build_case(conversation: dict[str, Any], chosen: list[dict[str, Any]], title: str, takeaway: str,
               author: str | None, keep_runs: bool = False) -> dict[str, Any]:
    """The case as the site publishes it; `keep_runs` keeps each answer's run id, for Share as case to choose from."""
    if not chosen:
        raise SiteError("Choose at least one answer to share.")
    systems = list(dict.fromkeys(str(s["system_name"]) for t in chosen for s in t["sources"] if s.get("system_name")))
    modes = list(dict.fromkeys(str(t["data_mode"]) for t in chosen if t.get("data_mode")))
    case = {"format": FORMAT, "id": case_id(conversation["id"]),
            "title": squeeze(title, CASE_TITLE) or squeeze(str(conversation.get("title") or ""), CASE_TITLE) or "An analysis",
            "takeaway": squeeze(takeaway, TAKEAWAY), "author": author, "published_at": now(),
            "systems": systems, "data_modes": modes,
            "turns": [{k: v for k, v in t.items() if keep_runs or k != "run_id"} | {"n": i + 1} for i, t in enumerate(chosen)]}
    text = json.dumps(case, ensure_ascii=False)
    found = _secrets(text, "the case")
    if found:
        raise SiteError(f"Not published: {found[0].message.replace('content files', 'a published case')}. Leave that "
                        "answer out, or ask again without it.")
    if len(text.encode("utf-8")) > MAX_CASE_BYTES:
        raise SiteError(f"The case is larger than {MAX_CASE_BYTES // (1024 * 1024)} MB: leave some answers out.")
    return case


def entry(case: dict[str, Any], first_published: str | None) -> dict[str, Any]:
    """A case as the gallery lists it."""
    return {"id": case["id"], "title": case["title"], "takeaway": case["takeaway"], "author": case["author"],
            "published_at": first_published or case["published_at"], "updated_at": case["published_at"],
            "prompts": len(case["turns"]), "systems": case["systems"], "data_modes": case["data_modes"],
            "first_prompt": squeeze(case["turns"][0]["prompt"], 280)}


def page_html(template: str, page: str) -> bytes:
    """The built page for one folder of the site: it knows which page it is, and finds the shared code one level up."""
    title = {"brain": "Knowledge graph · Wizard", "cases": "Cases · Wizard"}[page]
    html = template.replace('data-page=""', f'data-page="{page}"', 1).replace('"./assets/', '"../assets/')
    return re.sub(r"<title>[^<]*</title>", f"<title>{title}</title>", html, count=1).encode("utf-8")


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def _load(data: bytes | None, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(data or b"")
    except ValueError:
        return fallback
    return value if isinstance(value, dict) else fallback


Make = Callable[[set[str], Callable[[str], bytes | None]], dict[str, bytes | None]]
Writer = Callable[[Make, str], str | None]


@dataclass
class Outcome:
    outcome: str  # published | unchanged | removed
    message: str
    commit: str | None = None
    url: str | None = None


class Site:
    def __init__(self, settings: Settings, writer: Writer | None = None,
                 pages_url: Callable[[], str | None] | None = None):
        self.settings = settings
        self.repo, self.branch = settings.site_repo, settings.site_branch
        self.dist = settings.web_dist / "site"
        self._writer = writer
        self._pages_url = pages_url
        self._found_url: str | None = None

    # What the app shows ------------------------------------------------------------------------------------------------
    def problem(self) -> str | None:
        if not self.repo:
            return "No repository for the Pages site: set the knowledge base (Settings → Knowledge base) first."
        if not self.settings.kb_write_token and self._writer is None:
            return "No write token on this PC: add the knowledge base's write token (Settings → Knowledge base)."
        if not (self.dist / "site.html").is_file():
            return "This Wizard build has no site pages (apps/web/dist/site). Update Wizard."
        return None

    def url(self) -> str | None:
        if self.settings.site_url:
            return self.settings.site_url
        if self._found_url is None and self.repo and not self.problem():
            try:
                found = self._pages_url() if self._pages_url else self._ask_github()
            except httpx.HTTPError:
                found = None
            self._found_url = (found.rstrip("/") + "/") if found else ""
        return self._found_url or None

    def addresses(self) -> dict[str, str | None]:
        base = self.url()
        return {page: f"{base}{page}/" for page in PAGES} if base else dict.fromkeys(PAGES)

    def status(self) -> dict[str, Any]:
        problem = self.problem()
        return {"enabled": problem is None, "problem": problem, "repo": self.repo, "branch": self.branch,
                "url": self.url() if problem is None else None, "pages": self.addresses() if problem is None else dict.fromkeys(PAGES),
                "setup": None if problem or self.url() else
                f"Wizard does not know the site's address yet. If Pages is not on: on GitHub, {self.repo} → Settings → "
                f"Pages → Deploy from a branch → {self.branch} → / (root) → Save. Then copy the address GitHub shows there "
                "into Settings → Pages site → Site address."}

    # Publishing --------------------------------------------------------------------------------------------------------
    def _ask_github(self) -> str | None:
        from wizard_documents import kb
        assert self.repo and self.settings.kb_write_token
        return kb.pages_url(self.repo, self.settings.kb_write_token, proxy=self.settings.github_proxy)

    def _write(self, make: Make, message: str) -> str | None:
        problem = self.problem()
        if problem:
            raise SiteError(problem)
        if self._writer is not None:
            return self._writer(make, message)
        from wizard_documents import kb
        assert self.repo and self.settings.kb_write_token
        try:
            return kb.update_branch(self.repo, self.settings.kb_write_token, self.branch, make, message=message,
                                    proxy=self.settings.github_proxy)
        except kb.PublishError as error:
            raise SiteError(str(error)) from None
        except httpx.HTTPError as error:
            raise SiteError(outbound.explain(error, kb.API, self.settings.github_proxy, windows=True)) from None

    def app_files(self, existing: set[str], pages: set[str]) -> dict[str, bytes | None]:
        """The pages' code from this Wizard build, for the pages the site has; code an older build left is removed."""
        template = (self.dist / "site.html").read_text(encoding="utf-8")
        files: dict[str, bytes | None] = {".nojekyll": b"", "README.md": README.encode("utf-8")}
        assets = self.dist / "assets"
        for path in sorted(assets.rglob("*")) if assets.is_dir() else []:
            if path.is_file():
                files[f"assets/{path.relative_to(assets).as_posix()}"] = path.read_bytes()
        for old in existing:
            if old.startswith("assets/") and old not in files:
                files[old] = None
        for page in pages:
            files[f"{page}/index.html"] = page_html(template, page)
        return files

    @staticmethod
    def _pages(existing: set[str], *also: str) -> set[str]:
        """The pages the site has: the one being published and those already holding data."""
        return {p for p in PAGES if p in also or DATA[p] in existing}

    def publish_case(self, case: dict[str, Any]) -> Outcome:
        cid = case["id"]

        def make(existing: set[str], read: Callable[[str], bytes | None]) -> dict[str, bytes | None]:
            files = self.app_files(existing, self._pages(existing, "cases"))
            index = _load(read("cases/cases.json"), {"format": FORMAT, "cases": []})
            listed = [e for e in index.get("cases") or [] if isinstance(e, dict)]
            first = next((e.get("published_at") for e in listed if e.get("id") == cid), None)
            listed = [entry(case, first), *[e for e in listed if e.get("id") != cid]]
            files["cases/cases.json"] = _json({"format": FORMAT, "updated": case["published_at"], "cases": listed})
            files[f"cases/{cid}.json"] = _json(case)
            return files

        commit = self._write(make, f"Wizard: case \"{squeeze(case['title'], 70)}\" ({len(case['turns'])} prompts)")
        base = self.addresses()["cases"]
        url = f"{base}?case={cid}" if base else None
        if commit is None:
            return Outcome("unchanged", "The site already has this case as it is.", None, url)
        return Outcome("published", f"Published to {self.repo} ({self.branch}).", commit, url)

    def remove_case(self, cid: str) -> Outcome:
        def make(existing: set[str], read: Callable[[str], bytes | None]) -> dict[str, bytes | None]:
            index = _load(read("cases/cases.json"), {"format": FORMAT, "cases": []})
            listed = [e for e in index.get("cases") or [] if isinstance(e, dict) and e.get("id") != cid]
            return {"cases/cases.json": _json({"format": FORMAT, "updated": now(), "cases": listed}), f"cases/{cid}.json": None}

        commit = self._write(make, "Wizard: a case removed from the site")
        return Outcome("removed" if commit else "unchanged", "Removed from the site." if commit else "The site did not have it.",
                       commit)

    def publish_brain(self, snapshot: dict[str, Any]) -> Outcome:
        text = json.dumps(snapshot, ensure_ascii=False)
        found = _secrets(text, "the knowledge graph")
        if found:
            raise SiteError(f"Not published: {found[0].message.replace('content files', 'the published graph')}.")

        def make(existing: set[str], read: Callable[[str], bytes | None]) -> dict[str, bytes | None]:
            files = self.app_files(existing, self._pages(existing, "brain"))
            files["brain/brain.json"] = (text + "\n").encode("utf-8")
            return files

        counts = (snapshot.get("map") or {}).get("counts") or {}
        commit = self._write(make, f"Wizard: knowledge graph ({counts.get('notes', 0)} notes, "
                                   f"{counts.get('mapped_reports', 0)} portal reports mapped)")
        url = self.addresses()["brain"]
        if commit is None:
            return Outcome("unchanged", "The site already has this graph.", None, url)
        return Outcome("published", f"Published to {self.repo} ({self.branch}).", commit, url)


def brain_snapshot(map_: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    """What the Brain page reads on the site: the map and the news as Wizard read them now."""
    return {"format": FORMAT, "published_at": now(), "map": map_, "live": live}
