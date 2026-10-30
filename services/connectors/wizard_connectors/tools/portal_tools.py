"""Gemini's tools for the company portals: read a portal's guide, run its own browser script in the person's signed-in
Wizard browser, and keep a script that worked for next time.

The scripts are Gemini's own, like its SQL: steps (open a page, click, fill, wait, read a table, look around) and
JavaScript evaluated in the page, where the portal's own data requests can be called with fetch() under the person's
session (W.* helpers carry what Metronome learned about ASAP's MicroStrategy and GSCM's Nexacro). The rules that keep
them read-only live in portals.py and portal_browser.py, inside the tool. Every table a script returns is evidence:
LIVE (never verified), with the script as its query.

The portal map (portal_map.py) is what Gemini learned exploring a portal: how it works, its shortcuts and, per report,
how to open it, its filters and the data requests that return its rows. portal_map reads it, portal_map_save adds to
it, so a later question goes straight to the data."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import access_requests, portal_map, portals
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
                    "use_page", "request"] = Field(description=(
        "goto: open url (a path on the portal, or a portal address). click / fill / select: the element named by "
        "selector, role (+ name) or text; fill and select take value. press: a key (value, e.g. Enter). wait: for the "
        "element to be visible (or value 'hidden'), or value 'load'/'networkidle', or timeout_ms alone. evaluate: run "
        "script, JavaScript in the page (an async function body ending in return; W helpers and P parameters are "
        "defined). read_table: an HTML table as rows (selector, default the first table). look: the page's controls, "
        "tables, frames and text, to explore. back: browser back. use_page: switch to open page number nth (popups). "
        "request: send one data request (url, method, body, headers) straight from the browser with the person's "
        "session cookies, without opening or waiting for a page: the fastest way to call a portal route the map "
        "knows. The reply is parsed (Nexacro SSV or XML, JSON); a reply with one dataset comes back as a table, else "
        "give script, a JavaScript body that gets R = {status, contentType, text, data} and returns a table."))
    url: str | None = Field(default=None, max_length=4000, description="goto / request: '/path?query' on the portal application the page is on, or a full portal address (portal_guide lists them; the Big Data Portal's information catalog and Superset have one each).")
    method: Literal["GET", "POST", "PUT"] | None = Field(default=None, description="request: the HTTP method (default POST with a body, else GET).")
    body: str | None = Field(default=None, max_length=200_000, description="request: the request body exactly as the portal sends it (a Nexacro SSV or XML body, form fields, JSON); {{name}} parameters are filled in.")
    headers: dict[str, str] | None = Field(default=None, description="request: headers the route needs, such as Content-Type (cookies are the browser's own).")
    selector: str | None = Field(default=None, max_length=500, description="Playwright selector: CSS ('[id=\"…btn_search\"]', '#content-frame'), 'text=Run', or 'role=button[name=\"Go\"]'.")
    role: str | None = Field(default=None, max_length=40, description="ARIA role, e.g. button, link, tab, menuitem, option.")
    name: str | None = Field(default=None, max_length=200, description="Accessible name with role.")
    text: str | None = Field(default=None, max_length=200, description="Exact visible text of the element.")
    frame: str | None = Field(default=None, max_length=200, description="Frame name (e.g. content-frame) or part of its address; default the page itself.")
    nth: int | None = Field(default=None, ge=0, le=50, description="Which match when several elements match (0 = first); for use_page, the page number.")
    value: str | None = Field(default=None, max_length=2000, description="Text to fill, option to select, key to press, or the wait condition.")
    script: str | None = Field(default=None, max_length=30_000, description="evaluate: JavaScript body, e.g. 'const d = W.nexacro.read(\"ds_list\"); return d;'. request: what to return from the reply R, e.g. 'return R.data.datasets.ds_out;'. Return a table as {columns, rows} or a list of objects to cite it.")
    timeout_ms: int | None = Field(default=None, ge=500, le=150_000, description="Limit for this step (default 30000).")
    limit: int | None = Field(default=None, ge=5, le=200, description="look: how many controls to list (default 60).")
    save_as: str | None = Field(default=None, max_length=60, description="A short name for this step's result.")

    @model_validator(mode="after")
    def complete(self) -> Step:
        if self.action in ("goto", "request") and not self.url:
            raise ValueError(f"{self.action} needs url")
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


class Answer(Args):
    label: str = Field(min_length=1, max_length=access_requests.MAX_LABEL, description="The field's label as the request form shows it, e.g. Reason, Table name.")
    value: str = Field(max_length=access_requests.MAX_VALUE)


class RequestAccessArgs(Args):
    system: str = Field(pattern=SYSTEM, description="The portal where access is requested: bdp (its information catalog).")
    address: str | None = Field(default=None, max_length=2000, description="The page with the request form, or the table's page in the catalog where the person presses Request access (the full address you read it at). Omit to use the request page the person saved, else the catalog's start page.")
    tables: list[str] = Field(default_factory=list, max_length=20, description="The tables the person needs, as the catalog names them.")
    answers: list[Answer] = Field(default_factory=list, max_length=20, description="This request's own fields by the form's labels (the guide lists labels seen before), e.g. the reason, in the person's words from the question. Their saved answers (purpose, manager, duration...) are filled too.")


MAP_ID = r"^[a-z0-9][a-z0-9_.-]{0,79}$"


class MapTopic(Args):
    id: str = Field(pattern=MAP_ID, description="Short stable id, e.g. open-report-by-menu-id, transactions, weeks.")
    title: str = Field(min_length=3, max_length=160)
    text: str = Field(min_length=10, max_length=20_000, description="What a later script needs: how it works, the exact calls, selectors, routes and formats, and the steps or JavaScript that proved it.")


class MapFilter(Args):
    name: str = Field(max_length=160, description="The filter's label on screen, e.g. Week, Market, Plan version.")
    component: str | None = Field(default=None, max_length=400, description="Its component path or selector.")
    kind: str | None = Field(default=None, max_length=60, description="Combo, MultiCombo, Calendar, Edit, Radio, CheckBox, popup...")
    values: str | None = Field(default=None, max_length=6000, description="Its options (code = label, at most about 100) or format (e.g. YYYYWW, Sunday-start weeks), and where the options come from (an inner dataset, a lookup request).")
    default: str | None = Field(default=None, max_length=400)
    required: bool | None = None
    param: str | None = Field(default=None, max_length=120, description="The request parameter or body field this filter sets.")
    notes: str | None = Field(default=None, max_length=2000)


class MapData(Args):
    dataset: str = Field(max_length=160, description="The dataset name, e.g. ds_list.")
    component: str | None = Field(default=None, max_length=400, description="The grid (or chart) showing it.")
    columns: list[str] = Field(default_factory=list, max_length=300)
    labels: str | None = Field(default=None, max_length=6000, description="Column ids with their screen headers and units, e.g. QTY = Sell-out units.")
    rows_seen: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class MapRequest(Args):
    name: str = Field(max_length=120, description="What it does, e.g. search, combo-markets.")
    method: str = Field(default="POST", max_length=10)
    url: str = Field(max_length=2000, description="The route, as a path on the portal (e.g. /gscm/xyz/selectList.do).")
    body: str | None = Field(default=None, max_length=60_000, description="The body with the filter values as {{param}} placeholders, otherwise exactly as captured.")
    headers: dict[str, str] | None = Field(default=None, description="Headers it needs (Content-Type...).")
    params: list[str] = Field(default_factory=list, max_length=40, description="The {{param}} names in url and body, each matching a filter's param.")
    reply: str | None = Field(default=None, max_length=2000, description="What comes back: dataset names, columns, paging.")
    verified: bool = Field(default=False, description="True only when you sent it again with a changed filter and the reply matched what the screen shows.")
    notes: str | None = Field(default=None, max_length=2000)


NOTE_ID = r"^[a-z0-9][a-z0-9-]{0,80}$"
TARGET = r"^([a-z][a-z0-9]{1,15}:)?[a-z0-9][a-z0-9_.-]{0,79}$"


class MapNotFor(Args):
    question: str = Field(min_length=3, max_length=300, description="A question this report looks right for but must not answer, e.g. 'retail sell-out share'.")
    use_instead: str | None = Field(default=None, pattern=TARGET, description="The report that does answer it: its id in this map, or 'portal:id' for another portal's map. Leave it out when no mapped report does.")


class MapRouting(Args):
    use_for: list[str] | None = Field(default=None, max_length=8, description="2-5 short phrases: the business questions and terms the report answers, in the words people use, with the acronyms in its name (e.g. 'MS' = market share): 'shipment market share by vendor', 'foldable share by price tier'.")
    not_for: list[MapNotFor] | None = Field(default=None, max_length=8, description="Near misses, above all a report that measures the same term differently (retail panel share vs shipment share, sell-in vs sell-out, plan vs actual).")
    definitions: list[str] | None = Field(default=None, max_length=8, description="Ids of the knowledge notes that define its terms (wizard_lookup_definitions / wizard_browse_knowledge), e.g. 'market-share'.")


class MapReport(MapRouting):
    id: str = Field(pattern=MAP_ID, description="Stable id: the menu id or a short kebab-case name, e.g. as470 or weekly-sellout.")
    name: str | None = Field(default=None, max_length=200)
    path: list[str] | None = Field(default=None, max_length=8, description="Menu path, top level first.")
    menu_id: str | None = Field(default=None, max_length=120)
    status: Literal["todo", "mapped", "partial", "failed", "skipped"] | None = Field(default=None, description="todo: listed, not mapped yet. mapped: open, filters, data and a proven fast route are known. partial: some of it. failed / skipped: say why in notes.")
    summary: str | None = Field(default=None, max_length=3000, description="What the report shows in business words: measures, grain, period, units.")
    open: str | None = Field(default=None, max_length=6000, description="The fastest proven way to open it (a call, steps or JavaScript), and how to tell it has loaded.")
    filters: list[MapFilter] | None = Field(default=None, max_length=60)
    data: list[MapData] | None = Field(default=None, max_length=30)
    requests: list[MapRequest] | None = Field(default=None, max_length=20)
    script: str | None = Field(default=None, pattern=SCRIPT_NAME, description="A saved script (portal_save_script) that reads it with parameters.")
    notes: str | None = Field(default=None, max_length=6000, description="Pitfalls: waits, popups, paging, limits, why it failed.")


class MapRoute(MapRouting):
    id: str = Field(pattern=MAP_ID, description="The id of a report already in the map.")
    summary: str | None = Field(default=None, max_length=3000, description="What the report shows in business words: measures, grain, period, units. Kept only when the report has no summary yet.")
    routing_note: str | None = Field(default=None, max_length=600, description="Only when the map says too little to tell what the report is for: what is missing.")


class MapRouteArgs(Args):
    system: str = Field(pattern=SYSTEM)
    reports: list[MapRoute] = Field(min_length=1, max_length=50, description="Reports already in the map, each with its routing; what you give replaces its earlier routing.")
    note: str | None = Field(default=None, max_length=600, description="One line for the map's log.")


class MapArgs(Args):
    system: str = Field(pattern=SYSTEM, description="The portal: asap, gscm or bdp.")
    find: str | None = Field(default=None, max_length=300, description="Business words or a report name: returns the best matching reports in full.")
    report: str | None = Field(default=None, max_length=120, description="One report's id or menu id: returns it in full.")
    topic: str | None = Field(default=None, max_length=80, description="One topic's id: returns its full text.")
    todo: bool = Field(default=False, description="True: the reports still to map (todo, partial, failed), for exploring, and the mapped reports still to route (portal_map_route).")


class MapSaveArgs(Args):
    system: str = Field(pattern=SYSTEM)
    overview: str | None = Field(default=None, max_length=30_000, description="How the portal works as a whole (replaces the old overview): the client, frames, sign-in and session, how menus and reports open, the data request format, waits and popups.")
    topics: list[MapTopic] = Field(default_factory=list, max_length=30, description="Technical details and shortcuts, added or updated by id.")
    reports: list[MapReport] = Field(default_factory=list, max_length=300, description="Reports added or updated by id; only the fields you give change.")
    remove: list[str] = Field(default_factory=list, max_length=100, description="Report ids to drop (duplicates, entries that are not reports).")
    note: str | None = Field(default=None, max_length=600, description="One line for the map's log: what this save adds.")


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
    data = {"system": portal.id, "name": portal.name, "start_page": start, "browser": status["browser"],
            "last_sign_in": status["last_sign_in"], "signing_in": status["signing_in"], "saved_scripts": saved,
            "guide": _guide_text(portal.id),
            "note": "Steps run in the person's own Wizard browser, signed in as them, in the background. Wizard refuses "
                    "writes (save, delete, submit, upload, request access, sign out...) and any host outside the portals."}
    maps = ctx.services.portal_maps
    if maps is not None:
        data["map"] = {**maps.summary(portal.id),
                       "how_to_use": "What Wizard learned exploring this portal. Look here first: portal_map(find=...) "
                                     "returns a report's menu id, what it is for and not for (use_for, not_for with the "
                                     "report to use instead), how to open it, its filters and the data request with "
                                     "the filters as parameters, so one portal_run (a request step or the saved script) "
                                     "reads it. Add what you learn with portal_map_save."}
    if portal.parts:
        data["applications"] = [{"part": part.id, "name": part.label, "address": part.url} for part in portal.parts]
    if portal.id in access_requests.REQUEST_PORTALS:
        form = access_requests.form(browser.root, portal)
        data["access_request_form"] = {"request_page": form["page"] or None,
                                       "saved_labels": [f["label"] for f in form["fields"] if f.get("value")],
                                       "labels_seen_on_the_form": form["seen"]}
        data["start_page_note"] = ("This portal is several applications, each at its own address: goto one by its full "
                                   "address; a '/path' then stays on that application.")
    return data


def _fill(value: Any, params: dict[str, str]) -> Any:
    if isinstance(value, str):
        return re.sub(r"\{\{([a-z][a-z0-9_]{0,39})\}\}", lambda m: params.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: _fill(v, params) for k, v in value.items()}
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
        readable = output["action"] in ("evaluate", "read_table", "request")
        table = portals.table_from(value) if readable else None
        if table is None:
            if value is not None:
                output["value"] = _cap_value(value)
            # Anything else a script read is evidence too, as (key, value) rows, so it can be cited as it is.
            pairs = portals.key_values(portals.redact_json(value)) if readable and value is not None else None
            if pairs is not None:
                columns, rows, total = pairs
                rows = portals.redact_rows(columns, [[portals.plain_cell(c) for c in row] for row in rows])
                evidence_id = _record(ctx, portal, args, steps, output, page, columns, rows, total, retrieved)
                evidence_ids.append(evidence_id)
                output.update({"evidence_id": evidence_id, "cite_as": f"[{evidence_id}]", "total_rows": total,
                               "evidence_note": "Recorded as evidence as it is (key/value rows): cite it, no need to "
                                                "return it again as a table."})
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


def _maps(ctx: ToolContext) -> portal_map.PortalMaps:
    if ctx.services.portal_maps is None:
        raise ToolError("portals_unavailable", "This Wizard keeps no portal maps (no portals are configured).")
    return ctx.services.portal_maps


def read_map(ctx: ToolContext, args: MapArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    maps = _maps(ctx)
    data: dict[str, Any] = {"system": portal.id, "source_text_policy": UNTRUSTED_NOTICE}
    if args.report:
        found = maps.report(portal.id, args.report)
        if found is None:
            raise ToolError("not_found", f"No report '{args.report}' in the {portal.name} map; portal_map(find=...) searches it.")
        data["report"] = found
    elif args.topic:
        found = maps.topic(portal.id, args.topic)
        if found is None:
            raise ToolError("not_found", f"No topic '{args.topic}' in the {portal.name} map.")
        data["topic"] = found
    elif args.find:
        data["reports"] = maps.find(portal.id, args.find)
        if not data["reports"]:
            data["note"] = "Nothing in the map matches: explore the portal (portal_guide), then save what you find."
    elif args.todo:
        data["todo"] = maps.todo(portal.id)
        data["counts"] = maps.counts(maps.load(portal.id))
        unrouted = len(maps.unrouted(maps.load(portal.id)))
        if unrouted:
            data["to_route"] = maps.to_route(portal.id)
            data["to_route_left"] = unrouted
            data["to_route_note"] = ("Mapped reports that do not say yet what they are for. Route them first with "
                                     "portal_map_route, a batch at a time; it changes nothing else in the map.")
    else:
        data.update(maps.summary(portal.id))
    return data


def _check_definitions(ctx: ToolContext, reports: list[MapReport] | list[MapRoute]) -> None:
    unknown = sorted({d for r in reports for d in r.definitions or [] if d not in ctx.services.knowledge.by_id})
    if unknown:
        raise ToolError("unknown_note", f"No knowledge note with id {', '.join(unknown)}. Find note ids with "
                                        "wizard_lookup_definitions or wizard_browse_knowledge, or leave definitions out.")


def save_map(ctx: ToolContext, args: MapSaveArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    if args.overview is None and not (args.topics or args.reports or args.remove):
        raise ToolError("invalid_arguments", "Give an overview, topics, reports or report ids to remove.")
    _check_definitions(ctx, args.reports)
    try:
        result = _maps(ctx).save(portal.id, overview=args.overview, topics=[t.model_dump() for t in args.topics],
                                 reports=[r.model_dump(exclude_none=True) for r in args.reports], remove=args.remove,
                                 note=args.note)
    except portal_map.MapError as error:
        raise ToolError("map_full", str(error)) from None
    return {"system": portal.id, **result,
            "note": f"Saved in the {portal.name} map on this PC; Wizard publishes it to the knowledge base after this run "
                    "when this PC has the knowledge base's write token."}


def route_map(ctx: ToolContext, args: MapRouteArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    _check_definitions(ctx, args.reports)
    try:
        result = _maps(ctx).route(portal.id, [r.model_dump(exclude_none=True) for r in args.reports], note=args.note)
    except portal_map.MapError as error:
        raise ToolError("invalid_arguments", str(error)) from None
    return {"system": portal.id, **result,
            "note": "Only the routing changed: use_for, not_for, definitions, and a summary where there was none."
                    + (" These kept their own summary: " + ", ".join(result["summary_kept"]) + "." if result["summary_kept"] else "")}


def request_access(ctx: ToolContext, args: RequestAccessArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    if portal.id not in access_requests.REQUEST_PORTALS:
        raise ToolError("invalid_arguments", f"Access to {portal.name} is not requested through Wizard; the Big Data "
                                             "Portal (bdp) is.")
    browser = ctx.services.portals.for_user(ctx.identity.id)  # type: ignore[union-attr]
    saved = access_requests.form(browser.root, portal)
    try:
        address = access_requests.check_address(portal, args.address or saved["page"] or saved["default_page"])
    except access_requests.AccessFormError as error:
        raise ToolError("invalid_arguments", str(error)) from None
    tables = [" ".join(t.split())[:200] for t in args.tables if t.strip()]
    extra = [{"label": " ".join(a.label.split()), "value": a.value.strip()} for a in args.answers if a.value.strip()]
    request = {"id": access_requests.request_id(portal.id, address, tables, extra), "system": portal.id,
               "portal": portal.name, "address": address, "tables": tables, "answers": extra,
               "saved": [f["label"] for f in saved["fields"] if f.get("value")]}
    note = ("The person now sees a button, 'Open the request form': it opens this page in Wizard's browser window on "
            "their PC and fills their saved answers and yours into the form's empty fields. Tell them to check every "
            "field and submit the request themselves; Wizard never submits it, and portal reads wait until they close "
            "that window.")
    if not request["saved"]:
        note += (" They have no saved answers yet: they can add the ones they give every time in Settings → Portals → "
                 "Access request form.")
    return {"access_request": request, "form_labels_seen": saved["seen"], "note": note}


PORTAL_TOOLS = [
    ToolSpec("portal_guide",
             "How a company portal (ASAP, GSCM, the Big Data Portal: its information catalog, where tables are found, "
             "and Superset, where they are queried) works and how to read it with portal_run: its applications and "
             "addresses, its structure, where its data really comes from, the background data requests to call instead "
             "of clicking, the W.* JavaScript helpers, pitfalls, and the scripts saved for it on this PC. Read it "
             "before writing steps for a portal.", GuideArgs, guide, "portal", "knowledge"),
    ToolSpec("portal_run",
             "Read a company portal live, in the person's own signed-in Wizard browser (Chrome, in the background): "
             "your own steps (open pages, click, fill, wait, look around, read tables) and JavaScript evaluated in the "
             "page, where W.* helpers read Nexacro datasets, walk ASAP's menu, replay the portal's own data requests "
             "(W.requests, W.replay), search the Big Data Portal's information catalog and query Superset, and request "
             "steps that send a portal's data request straight from the browser with the person's session. Prefer the "
             "portal's data requests over clicking through screens, and the map's (portal_map) routes and saved scripts "
             "over exploring. Everything a step reads is recorded as evidence with an id such as E3 (a table, a "
             "{columns, rows} object or a list of objects, as its rows; anything else as key/value rows): cite it "
             "next to its numbers and lists. The "
             "result also lists the data requests the page made, with secrets removed. Wizard refuses saves, deletes, "
             "submissions, uploads, access requests, sign-outs and other hosts.", RunArgs, run, "portal", "source"),
    ToolSpec("portal_save_script",
             "Keep steps that worked as a named script for this person's portal, with parameters, so a later question "
             "runs it with portal_run(script=...) instead of exploring again. Saves on this PC only; it changes "
             "nothing in the portal.", SaveArgs, save_script, "portal", "present"),
    ToolSpec("portal_request_access",
             "Prepare an access request in a portal's information catalog (the Big Data Portal) for tables the person "
             "cannot query yet. Wizard never sends it: the person gets a button that opens the request page in Wizard's "
             "visible browser window, with their saved answers (purpose, manager, duration...) and your answers for "
             "this request filled into the form's empty fields; they check every field and submit it themselves. Use it "
             "after you found the table and saw that the person lacks access, and name the table in your answer.",
             RequestAccessArgs, request_access, "portal", "present"),
    ToolSpec("portal_map",
             "The map Wizard keeps of a company portal (GSCM, ASAP, the Big Data Portal): what Gemini learned exploring "
             "it. Without arguments: how the portal works, its proven shortcuts, and the index of mapped reports. find: "
             "the reports that match business words, in full: what each is for (use_for) and not for (not_for, with "
             "the report to use instead), the knowledge notes defining its terms, menu path and id, how to open it "
             "fastest, its filters and their values, the datasets and columns, and the data requests that return its "
             "rows with the filters as parameters. Read it before exploring a portal: a mapped report is read in one "
             "portal_run.",
             MapArgs, read_map, "portal", "knowledge"),
    ToolSpec("portal_map_save",
             "Add what you learned about a portal to its map, so later questions go straight to the data: the "
             "overview, topics (technical details and shortcuts you proved), and reports by id (menu path and id, a "
             "business summary, what it is for and not for, how to open it, filters and their values, datasets and "
             "columns, data requests with {{param}} placeholders, status). Only the fields you give change. Metadata "
             "only: never data rows or secrets. Saved on this PC and published to the knowledge base when this PC can "
             "write to it; it changes nothing in the portal.",
             MapSaveArgs, save_map, "portal", "present"),
    ToolSpec("portal_map_route",
             "Say what reports already in a portal's map are for: use_for (the business questions and terms each "
             "answers), not_for (near misses, with the report to use instead) and definitions (the knowledge notes for "
             "its terms), plus a business summary where a report has none. It changes nothing else: not the menu path, "
             "how to open it, filters, data, requests, script or status, and it adds or removes no report. Use it for "
             "the reports portal_map(todo=true) lists under to_route.",
             MapRouteArgs, route_map, "portal", "present"),
]
