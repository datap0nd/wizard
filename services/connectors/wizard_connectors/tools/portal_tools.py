"""Gemini's tools for the company portals: read a portal's guide, run its own browser script in the person's signed-in
Wizard browser, and keep a script that worked for next time.

The scripts are Gemini's own, like its SQL: steps (open a page, click, fill, wait, read a table, look around) and
JavaScript evaluated in the page, where the portal's own data requests can be called with fetch() under the person's
session (W.* helpers carry what Metronome learned about ASAP's MicroStrategy and GSCM's Nexacro). The rules that keep
them read-only live in portals.py and portal_browser.py, inside the tool. Every table a script returns is evidence:
LIVE (never verified), with the script as its query."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import portals
from ..portal_browser import PortalError
from .registry import UNTRUSTED_NOTICE, ToolContext, ToolError, ToolSpec

GUIDES = Path(__file__).resolve().parents[1] / "portal_guides"
SYSTEM = r"^[a-z][a-z0-9]{1,15}$"
SCRIPT_NAME = r"^[a-z0-9][a-z0-9-]{1,59}$"
MAX_VALUE_CHARS = 60_000
MAX_TABLE_CHARS = 120_000
MAX_SAVED = 60


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Step(Args):
    action: Literal["goto", "click", "fill", "select", "press", "wait", "evaluate", "read_table", "look", "back",
                    "use_page"] = Field(description=(
        "goto: open url (a path on the portal, or a portal address). click / fill / select: the element named by "
        "selector, role (+ name) or text; fill and select take value. press: a key (value, e.g. Enter). wait: for the "
        "element to be visible (or value 'hidden'), or value 'load'/'networkidle', or timeout_ms alone. evaluate: run "
        "script, JavaScript in the page (an async function body ending in return; W helpers and P parameters are "
        "defined). read_table: an HTML table as rows (selector, default the first table). look: the page's controls, "
        "tables, frames and text, to explore. back: browser back. use_page: switch to open page number nth (popups)."))
    url: str | None = Field(default=None, max_length=2000, description="goto: '/path?query' on the portal, or a full portal address.")
    selector: str | None = Field(default=None, max_length=500, description="Playwright selector: CSS ('[id=\"…btn_search\"]', '#content-frame'), 'text=Run', or 'role=button[name=\"Go\"]'.")
    role: str | None = Field(default=None, max_length=40, description="ARIA role, e.g. button, link, tab, menuitem, option.")
    name: str | None = Field(default=None, max_length=200, description="Accessible name with role.")
    text: str | None = Field(default=None, max_length=200, description="Exact visible text of the element.")
    frame: str | None = Field(default=None, max_length=200, description="Frame name (e.g. content-frame) or part of its address; default the page itself.")
    nth: int | None = Field(default=None, ge=0, le=50, description="Which match when several elements match (0 = first); for use_page, the page number.")
    value: str | None = Field(default=None, max_length=2000, description="Text to fill, option to select, key to press, or the wait condition.")
    script: str | None = Field(default=None, max_length=30_000, description="evaluate: JavaScript body, e.g. 'const d = W.nexacro.read(\"ds_list\"); return d;'. Return a table as {columns, rows} or a list of objects to cite it.")
    timeout_ms: int | None = Field(default=None, ge=500, le=150_000, description="Limit for this step (default 30000).")
    limit: int | None = Field(default=None, ge=5, le=200, description="look: how many controls to list (default 60).")
    save_as: str | None = Field(default=None, max_length=60, description="A short name for this step's result.")

    @model_validator(mode="after")
    def complete(self) -> Step:
        if self.action == "goto" and not self.url:
            raise ValueError("goto needs url")
        if self.action == "evaluate" and not (self.script or "").strip():
            raise ValueError("evaluate needs script")
        if self.action in ("click", "fill", "select") and not (self.selector or self.role or self.text):
            raise ValueError(f"{self.action} needs selector, role or text")
        return self


class Param(Args):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$", description="Parameter name, used as P.name in scripts and {{name}} in other fields.")
    value: str = Field(max_length=2000)


class RunArgs(Args):
    system: str = Field(pattern=SYSTEM, description="The portal: asap, gscm or bdp (portal_guide lists the ones this person has).")
    steps: list[Step] | None = Field(default=None, max_length=30, description="The steps to run, in order. Omit when running a saved script.")
    script: str | None = Field(default=None, pattern=SCRIPT_NAME, description="Run a script saved earlier with portal_save_script instead of steps.")
    params: list[Param] = Field(default_factory=list, max_length=20, description="Values for the script's parameters (P.name / {{name}}).")
    title: str | None = Field(default=None, max_length=160, description="What this reads, in business words, e.g. 'GSCM weekly sell-out by market, W40'. Names the evidence.")
    max_rows: int = Field(default=200, ge=1, le=500, description="Rows of each table returned to you (all rows are counted).")


class GuideArgs(Args):
    system: str = Field(pattern=SYSTEM, description="asap, gscm or bdp.")


class SaveArgs(Args):
    system: str = Field(pattern=SYSTEM)
    name: str = Field(pattern=SCRIPT_NAME, description="Short kebab-case name, e.g. weekly-sellout-by-market.")
    description: str = Field(min_length=10, max_length=600, description="What it returns and when to use it.")
    steps: list[Step] = Field(min_length=1, max_length=30)
    params: list[Param] = Field(default_factory=list, max_length=20, description="Parameters with an example value each.")


def _portal(ctx: ToolContext, system: str) -> portals.Portal:
    browsers = ctx.services.portals
    if browsers is None:
        raise ToolError("portals_unavailable", "This Wizard has no company portals configured (Settings → Portals).")
    portal = browsers.settings.portal(system)
    if portal is None or not ctx.identity.can_use_system(system):
        names = ", ".join(p.id for p in browsers.settings.portals)
        raise ToolError("portal_not_available", f"'{system}' is not a portal this person has. Portals: {names}.")
    return portal


def _scripts_file(ctx: ToolContext) -> Path:
    assert ctx.services.portals is not None
    return ctx.services.portals.for_user(ctx.identity.id).root / "scripts.json"


def _saved(ctx: ToolContext) -> list[dict[str, Any]]:
    try:
        value = json.loads(_scripts_file(ctx).read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _guide_text(system: str) -> str:
    parts = []
    for name in ("general", system):
        path = GUIDES / f"{name}.md"
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def guide(ctx: ToolContext, args: GuideArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    browser = ctx.services.portals.for_user(ctx.identity.id)  # type: ignore[union-attr]
    status = browser.status()
    saved = [{"name": s["name"], "description": s["description"], "params": s.get("params", []),
              "last_ok": s.get("last_ok")} for s in _saved(ctx) if s.get("system") == portal.id]
    address = urlsplit(portal.url)
    start = (address.path or "/") + (f"?{address.query}" if address.query else "")
    return {"system": portal.id, "name": portal.name, "start_page": start, "browser": status["browser"],
            "last_sign_in": status["last_sign_in"], "signing_in": status["signing_in"], "saved_scripts": saved,
            "guide": _guide_text(portal.id),
            "note": "Steps run in the person's own Wizard browser, signed in as them, in the background. Wizard refuses "
                    "writes (save, delete, submit, upload, sign out...) and any host outside the portals."}


def _fill(value: Any, params: dict[str, str]) -> Any:
    if isinstance(value, str):
        return re.sub(r"\{\{([a-z][a-z0-9_]{0,39})\}\}", lambda m: params.get(m.group(1), m.group(0)), value)
    return value


def _steps(ctx: ToolContext, args: RunArgs, portal: portals.Portal) -> tuple[list[dict[str, Any]], dict[str, str]]:
    params = {p.name: p.value for p in args.params}
    if args.script:
        found = next((s for s in _saved(ctx) if s.get("system") == portal.id and s.get("name") == args.script), None)
        if found is None:
            raise ToolError("script_not_found", f"No saved {portal.name} script named '{args.script}'. portal_guide lists them.")
        missing = [p["name"] for p in found.get("params", []) if p["name"] not in params]
        if missing:
            raise ToolError("invalid_arguments", f"The script needs {', '.join(missing)}.")
        raw = found["steps"]
    elif args.steps:
        raw = [s.model_dump(exclude_none=True) for s in args.steps]
    else:
        raise ToolError("invalid_arguments", "Give steps, or the name of a saved script.")
    steps = [{k: (v if k == "script" else _fill(v, params)) for k, v in step.items()} for step in raw]
    return steps, params


def _cap_value(value: Any) -> Any:
    value = portals.redact_json(value)
    encoded = portals.scrub(json.dumps(value, ensure_ascii=False, default=str))
    if len(encoded) <= MAX_VALUE_CHARS:
        try:
            return json.loads(encoded)
        except ValueError:  # a shortened value broke the JSON: send it as text
            return {"text": encoded}
    return {"truncated": True, "characters": len(encoded), "start": encoded[:MAX_VALUE_CHARS],
            "note": "The result was too large. Return less: filter or aggregate in the script, or return a table."}


def run(ctx: ToolContext, args: RunArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    steps, params = _steps(ctx, args, portal)
    browser = ctx.services.portals.for_user(ctx.identity.id)  # type: ignore[union-attr]
    try:
        result = browser.execute(portal, steps, params)
    except PortalError as error:
        raise ToolError(error.code, portals.scrub(error.message)) from None
    retrieved = ctx.services.now().isoformat()
    evidence_ids: list[str] = []
    shown_outputs = []
    page = result.get("page", {})
    for output in result["outputs"]:
        value = output.pop("value", None)
        table = portals.table_from(value) if output["action"] in ("evaluate", "read_table") else None
        if table is None:
            if value is not None:
                output["value"] = _cap_value(value)
            shown_outputs.append(output)
            continue
        columns, rows, total = table
        rows = portals.redact_rows(columns, [[portals.plain_cell(c) for c in row] for row in rows])
        evidence_id = _record(ctx, portal, args, steps, output, page, columns, rows, total, retrieved)
        evidence_ids.append(evidence_id)
        shown = rows[:args.max_rows]
        while shown and len(json.dumps(shown, default=str)) > MAX_TABLE_CHARS:
            shown = shown[:max(1, len(shown) * 2 // 3)]
        output.update({"evidence_id": evidence_id, "cite_as": f"[{evidence_id}]", "columns": columns, "rows": shown,
                       "row_count": len(shown), "total_rows": total, "truncated": len(shown) < total})
        shown_outputs.append(output)
    if args.script:
        _touch(ctx, portal.id, args.script)
    data: dict[str, Any] = {"system": portal.id, "data_mode": "LIVE", "outputs": shown_outputs, "page": page,
                            "requests": result["log"]["requests"], "refused": result["log"]["blocked"],
                            "dialogs": result["log"]["dialogs"], "console_errors": result["log"]["console_errors"],
                            "source_text_policy": UNTRUSTED_NOTICE}
    if evidence_ids:
        data["evidence_id"] = evidence_ids[0]
        data["evidence_ids"] = evidence_ids
    if "stopped" in result:
        data["stopped"] = {**result["stopped"], "message": portals.scrub(result["stopped"]["message"])}
    data["dialogs"] = [portals.scrub(d) for d in data["dialogs"]]
    data["console_errors"] = [portals.scrub(c) for c in data["console_errors"]]
    return data


def _record(ctx: ToolContext, portal: portals.Portal, args: RunArgs, steps: list[dict[str, Any]], output: dict[str, Any],
            page: dict[str, Any], columns: list[str], rows: list[list[Any]], total: int, retrieved: str) -> str:
    kept = rows[:500]
    request = {"steps": steps, "script_name": args.script, "params": {p.name: p.value for p in args.params},
               "page": page.get("url"), "page_title": page.get("title"), "step": output["step"]}
    digest = portals.digest({"request": request, "rows": kept})
    title = (args.title or output.get("name") or page.get("title") or f"{portal.name} page").strip()[:160]
    warnings = [f"{len(kept)} of {total} rows are kept as evidence."] if total > len(kept) else []
    return ctx.recorder.add_evidence({
        "tool": "portal_run", "system": portal.id, "system_name": portal.name,
        "report_id": f"{portal.id}-web-{digest[:12]}", "report_name": title,
        "folder_path": [page.get("title")] if page.get("title") else [],
        "data_mode": "LIVE", "connector_status": "BROWSER_SESSION", "request": request,
        "columns": portals.column_types(columns, kept), "rows": kept, "total_rows": total, "truncated": total > len(kept),
        "as_of": retrieved, "retrieved_at": retrieved, "digest": digest, "warnings": warnings,
        "access_note": f"Read from {portal.name} in the person's own signed-in Wizard browser; not verified.",
        "caveats": [], "locator": {"system": portal.id, "report_id": f"{portal.id}-web-{digest[:12]}",
                                   "open_url": page.get("url")},
    })


def _touch(ctx: ToolContext, system: str, name: str) -> None:
    saved = _saved(ctx)
    for item in saved:
        if item.get("system") == system and item.get("name") == name:
            item["last_ok"] = time.strftime("%Y-%m-%d")
    _write(ctx, saved)


def _write(ctx: ToolContext, saved: list[dict[str, Any]]) -> None:
    path = _scripts_file(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def save_script(ctx: ToolContext, args: SaveArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    saved = [s for s in _saved(ctx) if not (s.get("system") == portal.id and s.get("name") == args.name)]
    if len(saved) >= MAX_SAVED:
        raise ToolError("too_many_scripts", f"{MAX_SAVED} scripts are saved already; reuse one.")
    saved.append({"system": portal.id, "name": args.name, "description": args.description,
                  "steps": [s.model_dump(exclude_none=True) for s in args.steps],
                  "params": [{"name": p.name, "example": p.value} for p in args.params],
                  "saved": time.strftime("%Y-%m-%d"), "last_ok": None})
    _write(ctx, saved)
    return {"saved": args.name, "system": portal.id,
            "note": f"Run it with portal_run(system='{portal.id}', script='{args.name}', params=[...]). It is kept on "
                    "this PC for this person only."}


PORTAL_TOOLS = [
    ToolSpec("portal_guide",
             "How a company portal (ASAP, GSCM, the Big Data Portal) works and how to read it with portal_run: its "
             "structure, where its data really comes from, the background data requests to call instead of clicking, "
             "the W.* JavaScript helpers, pitfalls, and the scripts saved for it on this PC. Read it before writing "
             "steps for a portal.", GuideArgs, guide, "portal", "knowledge"),
    ToolSpec("portal_run",
             "Read a company portal live, in the person's own signed-in Wizard browser (Chrome, in the background): "
             "your own steps (open pages, click, fill, wait, look around, read tables) and JavaScript evaluated in the "
             "page, where W.* helpers read Nexacro datasets, walk ASAP's menu, replay the portal's own data requests "
             "(W.requests, W.replay) and query Superset. Prefer the portal's data requests over clicking through "
             "screens. Every table you return (a {columns, rows} object or a list of objects) is recorded as evidence "
             "with an id such as E3: cite it next to its numbers. The result also lists the data requests the page "
             "made, with secrets removed. Wizard refuses saves, deletes, submissions, uploads, sign-outs and other "
             "hosts.", RunArgs, run, "portal", "source"),
    ToolSpec("portal_save_script",
             "Keep steps that worked as a named script for this person's portal, with parameters, so a later question "
             "runs it with portal_run(script=...) instead of exploring again. Saves on this PC only; it changes "
             "nothing in the portal.", SaveArgs, save_script, "portal", "present"),
]
