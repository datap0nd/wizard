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
MAX_SAVED = 500
# Rows of one portal read kept as evidence: enough for a check against a person's own export row by row, and for Check
# my data. What Gemini sees of them is bounded separately (max_rows, MAX_TABLE_CHARS).
MAX_EVIDENCE_ROWS = 50_000


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
    reload: bool | None = Field(default=None, description="goto: open the address even when the browser is already on it with GSCM's client running (Wizard keeps that page otherwise: a reload restarts the client and its sign-in, a minute or more). Only for a stuck client.")
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
    steps: list[Step] | None = Field(default=None, max_length=60, description="The steps to run, in order. Omit when running a saved script.")
    script: str | None = Field(default=None, pattern=SCRIPT_NAME, description="Run a script saved earlier with portal_save_script instead of steps.")
    params: list[Param] = Field(default_factory=list, max_length=60, description="Values for the script's parameters (P.name / {{name}}).")
    title: str | None = Field(default=None, max_length=160, description="What this reads, in business words, e.g. 'GSCM weekly sell-out by market, W40'. Names the evidence.")
    max_rows: int = Field(default=200, ge=1, le=500, description="Rows of each table returned to you (all rows are counted).")


class GuideArgs(Args):
    system: str = Field(pattern=SYSTEM, description="asap, gscm or bdp.")


class SaveArgs(Args):
    system: str = Field(pattern=SYSTEM)
    name: str = Field(pattern=SCRIPT_NAME, description="Short kebab-case name, e.g. weekly-sellout-by-market.")
    description: str = Field(min_length=10, max_length=600, description="What it returns and when to use it.")
    steps: list[Step] = Field(min_length=1, max_length=60)
    params: list[Param] = Field(default_factory=list, max_length=60, description="Parameters with an example value each.")


class Answer(Args):
    label: str = Field(min_length=1, max_length=access_requests.MAX_LABEL, description="The field's label as the request form shows it, e.g. Reason, Table name.")
    value: str = Field(max_length=access_requests.MAX_VALUE)
    section: str | None = Field(default=None, max_length=access_requests.MAX_LABEL, description="The box the field sits in, only when two fields share a label (e.g. DPA / DSA).")


class OpenStep(Args):
    action: Literal["goto", "click", "fill", "select", "press", "wait"] = Field(description="As in portal_run: goto a url, click / fill / select an element, press Enter (to run a search), wait.")
    url: str | None = Field(default=None, max_length=2000)
    selector: str | None = Field(default=None, max_length=500)
    role: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=200)
    frame: str | None = Field(default=None, max_length=200)
    nth: int | None = Field(default=None, ge=0, le=50)
    value: str | None = Field(default=None, max_length=500, description="fill / select: the value (e.g. the table's name in the catalog's search box); press: Enter.")
    timeout_ms: int | None = Field(default=None, ge=500, le=access_requests.STEP_TIMEOUT_MS)


class RequestAccessArgs(Args):
    system: str = Field(pattern=SYSTEM, description="The portal where access is requested: bdp (its information catalog).")
    address: str | None = Field(default=None, max_length=2000, description="The page with the request form, or the table's page in the catalog where the person presses Request access (the full address you read it at). Omit to use the request page the person saved, else the catalog's start page.")
    tables: list[str] = Field(default_factory=list, max_length=20, description="The tables the person needs, as the catalog names them.")
    open_steps: list[OpenStep] = Field(default_factory=list, max_length=access_requests.MAX_STEPS, description="Only when the catalog shows every table at one address (the address does not change when a table opens): the steps from address to the table's own page, e.g. fill the search box with the table's name, press Enter, click the result. Run exactly these steps with portal_run first and see the table's page. The person's window follows them.")
    form_button: str | None = Field(default=None, max_length=80, description="The visible text of the control on the table's page that opens the request form, as you saw it (e.g. Request access). Wizard presses it in the person's window, with writes stopped, so the form opens; leave it out to let Wizard look for one.")
    answers: list[Answer] = Field(default_factory=list, max_length=20, description="This request's own fields by the form's labels (the guide lists labels seen before), only for fields the person has no saved answer for (the guide lists saved_labels), e.g. a reason in the person's words from the question. Their saved answers (purpose, the DPA / DSA box, subsidiary...) are filled too.")


MAP_ID = r"^[a-z0-9][a-z0-9_.-]{0,79}$"


class MapTopic(Args):
    id: str = Field(pattern=MAP_ID, description="Short stable id, e.g. open-report-by-menu-id, transactions, weeks.")
    title: str = Field(min_length=3, max_length=160)
    text: str = Field(min_length=10, max_length=200_000, description="What a later script needs: how it works, the exact calls, selectors, routes and formats, and the steps or JavaScript that proved it.")


class MapFilter(Args):
    name: str = Field(max_length=160, description="The filter's label on screen, e.g. Week, Market, Plan version.")
    component: str | None = Field(default=None, max_length=400, description="Its component path or selector.")
    kind: str | None = Field(default=None, max_length=60, description="Combo, MultiCombo, Calendar, Edit, Radio, CheckBox, popup...")
    values: str | None = Field(default=None, max_length=200_000, description="Its options (code = label, every one of them) or format (e.g. YYYYWW, Sunday-start weeks), and where the options come from (an inner dataset, a lookup request).")
    default: str | None = Field(default=None, max_length=400)
    required: bool | None = None
    param: str | None = Field(default=None, max_length=120, description="The request parameter or body field this filter sets.")
    notes: str | None = Field(default=None, max_length=2000)


class MapData(Args):
    dataset: str = Field(max_length=160, description="The dataset name, e.g. ds_list.")
    component: str | None = Field(default=None, max_length=400, description="The grid (or chart) showing it.")
    columns: list[str] = Field(default_factory=list, max_length=5000)
    labels: str | None = Field(default=None, max_length=200_000, description="Column ids with their screen headers and units, e.g. QTY = Sell-out units.")
    rows_seen: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class MapRequest(Args):
    name: str = Field(max_length=120, description="What it does, e.g. search, combo-markets.")
    method: str = Field(default="POST", max_length=10)
    url: str = Field(max_length=2000, description="The route, as a path on the portal (e.g. /gscm/xyz/selectList.do).")
    body: str | None = Field(default=None, max_length=200_000, description="The body with the filter values as {{param}} placeholders, otherwise exactly as captured.")
    headers: dict[str, str] | None = Field(default=None, description="Headers it needs (Content-Type...).")
    params: list[str] = Field(default_factory=list, max_length=40, description="The {{param}} names in url and body, each matching a filter's param.")
    reply: str | None = Field(default=None, max_length=2000, description="What comes back: dataset names, columns, paging.")
    verified: bool = Field(default=False, description="Ignored here: only portal_prove_request marks a request verified, after Wizard itself sent it twice.")
    notes: str | None = Field(default=None, max_length=2000)


class MapView(Args):
    name: str = Field(max_length=160, description="The option as the screen names it: the grid's gear / Configuration (column chooser), a view or grouping switch, a measure or unit toggle, a layout tab.")
    component: str | None = Field(default=None, max_length=400, description="How to reach it: the control's component path, and the dialog it opens.")
    path: str | None = Field(default=None, max_length=600, description="The clicks from the open report to this choice, with the labels exactly as the screen shows them, e.g. 'Configuration > Sales > Sales > ORG Sales, then Apply'.")
    requires: str | None = Field(default=None, max_length=2000, description="What must be set before the choice works, and what the portal says otherwise, e.g. 'subsidiaries chosen one by one in the search area (all of them is fine; a region such as Middle East is refused: \"cannot select so much granularity\")'.")
    options: str | None = Field(default=None, max_length=200_000, description="Every choice it offers (each selectable column, grouping, measure...), the default ones marked, e.g. 'OrgSales (account), Country, Model (default off); Region (default on)'.")
    columns: list[str] = Field(default_factory=list, max_length=5000, description="The column ids the non-default choices add to the dataset, e.g. orgsales.")
    effect: str | None = Field(default=None, max_length=50_000, description="What choosing it changes, as proved: a new request parameter (name and values), another dataset or route, or only columns the dataset already had; and whether the choice stays saved for the person.")
    how: str | None = Field(default=None, max_length=50_000, description="The proven steps or request that read the report with these choices (e.g. open the gear, tick OrgSales, Apply, search; or the request with its parameter).")
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
    status: Literal["todo", "mapped", "partial", "failed", "skipped"] | None = Field(default=None, description="todo: listed, not mapped yet. mapped: open, filters, data, every option beyond the default view (views) and a proven fast route are known. partial: some of it. failed / skipped: say why in notes.")
    summary: str | None = Field(default=None, max_length=3000, description="What the report shows in business words: measures, grain, period, units.")
    open: str | None = Field(default=None, max_length=6000, description="The fastest proven way to open it (a call, steps or JavaScript), and how to tell it has loaded. In GSCM, one evaluate step without a goto: await W.nexacro.open('<the client's open function>', '<menu id>').")
    filters: list[MapFilter] | None = Field(default=None, max_length=300)
    data: list[MapData] | None = Field(default=None, max_length=200)
    views: list[MapView] | None = Field(default=None, max_length=300, description="Every option beyond the default view: the configuration gear's column chooser, view, grouping, measure and unit switches, with every choice and what it adds. An empty list says the report has none (explored); leaving it out means it was not explored yet.")
    requests: list[MapRequest] | None = Field(default=None, max_length=200)
    script: str | None = Field(default=None, pattern=SCRIPT_NAME, description="A saved script (portal_save_script) that reads it with parameters.")
    notes: str | None = Field(default=None, max_length=50_000, description="Pitfalls: waits, popups, paging, limits, why it failed.")


class MapRoute(MapRouting):
    id: str = Field(pattern=MAP_ID, description="The id of a report already in the map.")
    summary: str | None = Field(default=None, max_length=3000, description="What the report shows in business words: measures, grain, period, units. Kept only when the report has no summary yet.")
    routing_note: str | None = Field(default=None, max_length=600, description="Only when the map says too little to tell what the report is for: what is missing.")


class ProveArgs(Args):
    system: str = Field(pattern=SYSTEM, description="The portal: asap, gscm or bdp.")
    report: str = Field(pattern=MAP_ID, description="The report's id in the map, e.g. db4009.")
    request: MapRequest = Field(description="The data request as you will keep it: url and body with {{param}} placeholders for its filters, method, headers, params.")
    first: list[Param] = Field(min_length=1, max_length=60, description="Values for every {{param}}: the ones the screen used (or the person's own export).")
    second: list[Param] = Field(min_length=1, max_length=60, description="The same values with one changed, e.g. the date one day earlier or another subsidiary.")


class MapRouteArgs(Args):
    system: str = Field(pattern=SYSTEM)
    reports: list[MapRoute] = Field(min_length=1, max_length=50, description="Reports already in the map, each with its routing; what you give replaces its earlier routing.")
    note: str | None = Field(default=None, max_length=600, description="One line for the map's log.")


class MapArgs(Args):
    system: str = Field(pattern=SYSTEM, description="The portal: asap, gscm or bdp.")
    find: str | None = Field(default=None, max_length=300, description="Business words or a report name: returns the best matching reports in full.")
    report: str | None = Field(default=None, max_length=120, description="One report's id or menu id: returns it in full.")
    topic: str | None = Field(default=None, max_length=80, description="One topic's id: returns its full text.")
    todo: bool = Field(default=False, description="True: the reports still to map (todo, partial, failed), for exploring, the mapped reports whose options beyond the default view are still to explore (to_configure), and the mapped reports still to route (portal_map_route).")


class MapSaveArgs(Args):
    system: str = Field(pattern=SYSTEM)
    overview: str | None = Field(default=None, max_length=30_000, description="How the portal works as a whole (replaces the old overview): the client, frames, sign-in and session, how menus and reports open, the data request format, waits and popups.")
    topics: list[MapTopic] = Field(default_factory=list, max_length=100, description="Technical details and shortcuts, added or updated by id.")
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
    if ctx.services.portal_maps is not None:
        mine = {s["name"] for s in saved}
        saved += [{"name": s["name"], "description": s.get("description"), "params": s.get("params", []), "from": "map"}
                  for s in ctx.services.portal_maps.load(portal.id).get("scripts") or []
                  if isinstance(s, dict) and s.get("name") and s["name"] not in mine]
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
                                       "saved_labels": [access_requests.name(f) for f in form["fields"] if f.get("value")],
                                       "labels_seen_on_the_form": form["seen"],
                                       "form_pages_seen": access_requests.pages_seen(browser.root, portal.id),
                                       "sending_on": access_requests.sending(browser.root, portal.id)["enabled"],
                                       "prepared_requests": {"total": len(form["queue"]),
                                                             "not_opened": sum(1 for i in form["queue"] if not i.get("opened")),
                                                             "tables": sorted({t for i in form["queue"] for t in i.get("tables") or []})[:200],
                                                             "to_prepare_again": sorted({
                                                                 t for i in form["queue"] if not i.get("opened")
                                                                 and not i.get("open_steps")
                                                                 and access_requests.start_page(portal, str(i["address"]))
                                                                 for t in i.get("tables") or []})[:200]}}
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
        if found is None and ctx.services.portal_maps is not None:
            found = ctx.services.portal_maps.script(portal.id, args.script)
        if found is None:
            raise ToolError("script_not_found", f"No saved {portal.name} script named '{args.script}', on this PC or in "
                                                "the map. Read the report with its request or its open steps from the map "
                                                "instead, and save the steps that work with portal_save_script.")
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
    kept = rows[:MAX_EVIDENCE_ROWS]
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
    in_map = False
    if ctx.services.portal_maps is not None:
        try:
            ctx.services.portal_maps.keep_script(portal.id, saved[-1])
            in_map = True
        except portal_map.MapError:
            pass
    return {"saved": args.name, "system": portal.id, "in_map": in_map,
            "note": f"Run it with portal_run(system='{portal.id}', script='{args.name}', params=[...]). " + (
                "It is kept on this PC and in the portal's map, which Wizard publishes, so a report in the map can name "
                "it." if in_map else "It is kept on this PC for this person only.")}


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
        data["report"] = _with_scripts(ctx, portal.id, [found])[0]
    elif args.topic:
        found = maps.topic(portal.id, args.topic)
        if found is None:
            raise ToolError("not_found", f"No topic '{args.topic}' in the {portal.name} map.")
        data["topic"] = found
    elif args.find:
        data["reports"] = _with_scripts(ctx, portal.id, maps.find(portal.id, args.find))
        if not data["reports"]:
            data["note"] = "Nothing in the map matches: explore the portal (portal_guide), then save what you find."
    elif args.todo:
        data["todo"] = maps.todo(portal.id)
        data["counts"] = maps.counts(maps.load(portal.id))
        unrouted = len(maps.unrouted(maps.load(portal.id)))
        unviewed = len(maps.unviewed(maps.load(portal.id)))
        if unviewed:
            data["to_configure"] = maps.to_configure(portal.id)
            data["to_configure_left"] = unviewed
            data["to_configure_note"] = ("Mapped reports whose options beyond the default view were never explored. Open "
                                         "each, explore its configuration gear and every other option, and save its "
                                         "views with portal_map_save (an empty list when it has none).")
        if unrouted:
            data["to_route"] = maps.to_route(portal.id)
            data["to_route_left"] = unrouted
            data["to_route_note"] = ("Mapped reports that do not say yet what they are for. Route them first with "
                                     "portal_map_route, a batch at a time; it changes nothing else in the map.")
    else:
        data.update(maps.summary(portal.id))
    return data


def _script_known(ctx: ToolContext, system: str, name: str) -> bool:
    maps = ctx.services.portal_maps
    return any(s.get("system") == system and s.get("name") == name for s in _saved(ctx)) or (
        maps is not None and maps.script(system, name) is not None)


def _with_scripts(ctx: ToolContext, system: str, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reports as a question reads them: one whose script is saved neither on this PC nor in the map says so, so the
    question reads it with its request or open steps instead of trying the script."""
    out = []
    for report in reports:
        name = report.get("script")
        if name and not _script_known(ctx, system, str(name)):
            report = {**report, "script_missing": f"The script '{name}' is not saved on this PC or in the map: read this "
                                                  "report with its request or open steps, and save the steps that work "
                                                  "with portal_save_script under that name."}
        out.append(report)
    return out


def _check_definitions(ctx: ToolContext, reports: list[MapReport] | list[MapRoute]) -> None:
    unknown = sorted({d for r in reports for d in r.definitions or [] if d not in ctx.services.knowledge.by_id})
    if unknown:
        raise ToolError("unknown_note", f"No knowledge note with id {', '.join(unknown)}. Find note ids with "
                                        "wizard_lookup_definitions or wizard_browse_knowledge, or leave definitions out.")


# A sentence saying a report lacks something: refused in the map (owner's task run of 3 Nov 2026 wrote that the daily
# sell-out report had no account breakdown, which it has three levels deep in its Configuration). What was not found
# is unknown; a sentence that says what it needs ("only after", "until") is a description, not a claim of absence.
ABSENCE = re.compile(r"\b(does not|doesn't|do not|don't|cannot|can't|can not|has no|have no|lacks?|without|missing|"
                     r"no)\b[^.;\n]{0,60}?\b(breakdown|dimension|account|operator|customer|retailer|carrier|orgsales|"
                     r"org sales)s?\b", re.IGNORECASE)
# A sentence that says what a choice needs, what was not found yet, or how rows look describes; it claims no absence.
CONDITIONAL = re.compile(r"\b(until|unless|only (when|after|if|once)|before|first|by default|default view|not yet|"
                         r"found yet|rows?)\b", re.IGNORECASE)


def _absence_claims(value: Any) -> list[str]:
    """Sentences in a report's map entry that say it lacks a breakdown."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for sentence in re.split(r"(?<=[.;!?])\s+|\n", node):
                if ABSENCE.search(sentence) and not CONDITIONAL.search(sentence):
                    found.append(sentence.strip()[:200])
        elif isinstance(node, dict):
            for key, child in node.items():
                if key not in ("url", "body", "headers", "open", "script", "id", "menu_id", "path", "requests", "requires"):
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found


def _refuse_absence(reports: list[dict[str, Any]]) -> None:
    claims = [f"{r['id']}: \"{c}\"" for r in reports for c in _absence_claims(r)]
    if claims:
        raise ToolError("unproven_absence",
                        "The map does not keep that a report lacks a breakdown: a choice nobody found is unknown, not "
                        "absent (a report's Configuration can hold it several levels deep). Write what you looked at and "
                        "did not find yet (\"no account found yet in Configuration > Sales after opening every group\"), "
                        "or leave it out. Refused: " + "; ".join(claims[:5]))


def _unproven(ctx: ToolContext, system: str, reports: list[dict[str, Any]]) -> list[str]:
    """Keep proof Wizard's own: a request keeps verified only when it is the one portal_prove_request proved; a report
    is mapped only with a proven request (else it is saved as partial). Returns the warnings."""
    maps = _maps(ctx)
    warnings = []
    for report in reports:
        proven = {(q.get("url"), q.get("method") or "POST", q.get("body")): q for q in maps.proven(system, report["id"])}
        requests = report.get("requests")
        if requests is not None:
            kept = []
            for request in requests:
                key = (request.get("url"), request.get("method") or "POST", request.get("body"))
                if key in proven:
                    kept.append({**request, "verified": True, "proven": proven[key]["proven"]})
                else:
                    if request.get("verified"):
                        warnings.append(f"{report['id']}: request {request.get('name')} kept as not verified: prove it "
                                        "with portal_prove_request")
                    kept.append({**request, "verified": False})
            # Proven requests stay unless they are given again: a save never drops Wizard's proof.
            given = {(q.get("url"), q.get("method") or "POST", q.get("body")) for q in kept}
            kept += [q for key, q in proven.items() if key not in given]
            report["requests"] = kept
        if report.get("status") == "mapped" and not (proven or any(q.get("proven") for q in report.get("requests") or [])):
            report["status"] = "partial"
            warnings.append(f"{report['id']}: saved as partial: a report is mapped once Wizard proved one of its data "
                            "requests (portal_prove_request)")
    return warnings


def save_map(ctx: ToolContext, args: MapSaveArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    if args.overview is None and not (args.topics or args.reports or args.remove):
        raise ToolError("invalid_arguments", "Give an overview, topics, reports or report ids to remove.")
    _check_definitions(ctx, args.reports)
    reports = [r.model_dump(exclude_none=True) for r in args.reports]
    _refuse_absence(reports)
    proof_warnings = _unproven(ctx, portal.id, reports)
    try:
        result = _maps(ctx).save(portal.id, overview=args.overview, topics=[t.model_dump() for t in args.topics],
                                 reports=reports, remove=args.remove, note=args.note)
    except portal_map.MapError as error:
        raise ToolError("map_full", str(error)) from None
    unsaved = sorted({r.script for r in args.reports if r.script and not _script_known(ctx, portal.id, r.script)})
    warnings = proof_warnings + ([f"Not saved as scripts yet: {', '.join(unsaved)}. Save each with portal_save_script "
                                  "under that name, or the report names a script no PC can run."] if unsaved else [])
    return {"system": portal.id, **result,
            **({"warning": " ".join(warnings)} if warnings else {}),
            "note": f"Saved in the {portal.name} map on this PC; Wizard publishes it to the knowledge base after this run "
                    "when this PC has the knowledge base's write token."}


def route_map(ctx: ToolContext, args: MapRouteArgs) -> dict[str, Any]:
    portal = _portal(ctx, args.system)
    _check_definitions(ctx, args.reports)
    _refuse_absence([r.model_dump(exclude_none=True) for r in args.reports])
    try:
        result = _maps(ctx).route(portal.id, [r.model_dump(exclude_none=True) for r in args.reports], note=args.note)
    except portal_map.MapError as error:
        raise ToolError("invalid_arguments", str(error)) from None
    return {"system": portal.id, **result,
            "note": "Only the routing changed: use_for, not_for, definitions, and a summary where there was none."
                    + (" These kept their own summary: " + ", ".join(result["summary_kept"]) + "." if result["summary_kept"] else "")}


# A request step's reply, summed up for a proof: every dataset with its columns and row count, the portal's own error
# code and message, and the biggest dataset's rows (kept as evidence, to cite and to check against an export).
PROOF_SCRIPT = """
const d = (R.data && typeof R.data === 'object') ? R.data : {};
const p = d.parameters || {};
const sets = {};
if (d.datasets) for (const [n, t] of Object.entries(d.datasets)) sets[n] = t;
else {
  const src = d.json && typeof d.json === 'object' ? d.json : d;
  const found = Array.isArray(src) ? [['rows', src]] : Object.entries(src);
  for (const [k, v] of found) if (Array.isArray(v) && v.length && v[0] && typeof v[0] === 'object') {
    const cols = Object.keys(v[0]); sets[k] = {columns: cols, rows: v.map(o => cols.map(c => o[c]))}; }
}
const name = c => (typeof c === 'string' ? c : (c && (c.id || c.name || c.key)) || String(c));
const summary = Object.entries(sets).map(([n, t]) => ({name: n, columns: (t.columns || []).map(name), rows: (t.rows || []).length}));
const big = summary.slice().sort((a, b) => b.rows - a.rows)[0];
return {status: R.status, error_code: p.ErrorCode === undefined ? null : p.ErrorCode, error_msg: p.ErrorMsg || null,
        datasets: summary, dataset: big ? big.name : null, columns: big ? big.columns : [],
        rows: big ? sets[big.name].rows : [], total_rows: big ? big.rows : 0};
"""


def prove_request(ctx: ToolContext, args: ProveArgs) -> dict[str, Any]:
    """Wizard itself sends the request twice, with the values given and with one changed, and keeps it as proven only
    when both answers are clean and alike in shape (the same datasets and columns) and the changed value changed the
    rows. Gemini's own account of a request never marks it verified."""
    portal = _portal(ctx, args.system)
    maps = _maps(ctx)
    template = args.request.model_dump(exclude_none=True)
    template.pop("verified", None)
    first, second = ({p.name: p.value for p in values} for values in (args.first, args.second))
    if first == second:
        raise ToolError("invalid_arguments", "first and second must differ in at least one value.")
    steps = []
    for values in (first, second):
        url, body = _fill(template["url"], values), _fill(template.get("body") or "", values) or None
        left = sorted(set(re.findall(r"\{\{([a-z][a-z0-9_]{0,39})\}\}", f"{url} {body or ''}")))
        if left:
            raise ToolError("invalid_arguments", f"No value for {', '.join(left)}: give it in first and second.")
        step = {"action": "request", "url": url, "method": template.get("method") or ("POST" if body else "GET"),
                "script": PROOF_SCRIPT, "timeout_ms": 120_000}
        if body:
            step["body"] = body
        if template.get("headers"):
            step["headers"] = template["headers"]
        steps.append(step)
    browser = ctx.services.portals.for_user(ctx.identity.id)  # type: ignore[union-attr]
    try:
        result = browser.execute(portal, steps, {})
    except PortalError as error:
        raise ToolError(error.code, error.message) from None
    replies = [o.get("value") for o in result.get("outputs", [])]
    problems = []
    if "stopped" in result or len(replies) < 2 or not all(isinstance(r, dict) for r in replies):
        problems.append(str((result.get("stopped") or {}).get("message") or "a request did not answer"))
    else:
        for label, reply in zip(("first", "second"), replies, strict=True):
            if reply.get("status") != 200:
                problems.append(f"the {label} reply's status is {reply.get('status')}")
            try:
                failed = reply.get("error_code") is not None and int(reply["error_code"]) < 0
            except (TypeError, ValueError):
                failed = False
            if failed:
                problems.append(f"the portal refused the {label} request: {reply.get('error_code')} {reply.get('error_msg') or ''}".strip())
        shapes = [[(d["name"], tuple(d["columns"])) for d in r.get("datasets") or []] for r in replies]
        if not problems and shapes[0] != shapes[1]:
            problems.append("the two replies hold different datasets or columns")
        if not problems and not replies[0].get("total_rows"):
            problems.append("the first reply has no rows: use values that have data (the ones the screen showed)")
        if not problems and portals.digest(replies[0].get("rows")) == portals.digest(replies[1].get("rows")):
            problems.append("the changed value did not change the rows: it may not be the filter, or both values hold the "
                            "same data")
    retrieved = ctx.services.now().isoformat()
    evidence = []
    run_args = RunArgs(system=portal.id, title=f"{args.report}: {template.get('name')}")
    for index, reply in enumerate(replies):
        if isinstance(reply, dict) and reply.get("columns"):
            columns = [str(c) for c in reply["columns"]][:portals.MAX_TABLE_COLUMNS]
            rows = portals.redact_rows(columns, [[portals.plain_cell(c) for c in (row[:len(columns)] if isinstance(row, list) else [])]
                                                 for row in reply.get("rows") or []])
            output = {"step": index + 1, "action": "request"}
            evidence.append(_record(ctx, portal, run_args, [steps[index]], output, result.get("page", {}), columns, rows,
                                    int(reply.get("total_rows") or len(rows)), retrieved))
    summary = [{"values": values, "status": r.get("status") if isinstance(r, dict) else None,
                "datasets": r.get("datasets") if isinstance(r, dict) else None,
                "rows": r.get("total_rows") if isinstance(r, dict) else None}
               for values, r in zip((first, second), replies + [None] * (2 - len(replies)), strict=False)]
    if problems:
        return {"system": portal.id, "report": args.report, "proven": False, "problems": problems, "replies": summary,
                "evidence_ids": evidence,
                "note": "Not kept as proven. Fix the request (its body, a parameter, the values) and prove it again."}
    proof = {"at": retrieved, "first": first, "second": second, "datasets": replies[0].get("datasets"),
             "rows_first": replies[0].get("total_rows"), "rows_second": replies[1].get("total_rows")}
    if maps.report(portal.id, args.report) is None:  # proved before it was saved: the proof starts its entry
        maps.save(portal.id, reports=[{"id": args.report, "status": "partial"}], note=f"{args.report}: a request proven")
    try:
        maps.prove(portal.id, args.report, template, proof)
    except portal_map.MapError as error:
        raise ToolError("not_found", str(error)) from None
    return {"system": portal.id, "report": args.report, "proven": True, "replies": summary, "evidence_ids": evidence,
            "cite_as": [f"[{e}]" for e in evidence],
            "note": f"Kept in the map as proven: request {template.get('name')} of {args.report}. The first reply is "
                    f"evidence {evidence[0] if evidence else '-'}."}


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
    try:
        extra = access_requests.clean_fields([a.model_dump(exclude_none=True) for a in args.answers if a.value.strip()])
        steps = access_requests.clean_steps([s.model_dump(exclude_none=True) for s in args.open_steps])
        button = access_requests.clean_button(args.form_button)
    except access_requests.AccessFormError as error:
        raise ToolError("invalid_arguments", str(error)) from None
    if tables and not steps and address != saved["page"] and access_requests.start_page(portal, address):
        raise ToolError("invalid_arguments", (
            f"{address} is the start page: the person would have to find {', '.join(tables)} themselves, and the "
            "request form would not open. Open the table in the catalog with portal_run and pass the address its page "
            "shows (page.url) as address. If the address stays the same whatever table is open, pass open_steps: the "
            "steps you just ran from that address to the table's page (fill the search with its name, press Enter, "
            "click the result), and form_button: the text of the control there that opens the request form."))
    route = {"open_steps": steps, "form_button": button}
    can_send = access_requests.sending(browser.root, portal.id)["enabled"]
    request = {"id": access_requests.request_id(portal.id, address, tables, extra, route), "system": portal.id,
               "portal": portal.name, "address": address, "tables": tables, "answers": extra,
               **({"open_steps": steps} if steps else {}), **({"form_button": button} if button else {}),
               "saved": [access_requests.name(f) for f in saved["fields"] if f.get("value")], "can_send": can_send}
    if can_send:
        note = ("The person now sees 'Send request': with their click, Wizard opens the table's page in its browser "
                "window on their PC, fills the form from their saved answers and yours and submits it the way their "
                "own proven request went, and checks the catalog's answer. Nothing is sent without that click. Portal "
                "reads wait until the window is closed.")
    else:
        note = ("The person now sees a button, 'Open the request form': it opens this page in Wizard's browser window "
                "on their PC and fills their saved answers and yours into the form's empty fields. Tell them to check "
                "every field and submit the request themselves; Wizard does not submit it until they have submitted "
                "one themselves and turned sending on. Portal reads wait until they close that window.")
    try:
        place = access_requests.enqueue(browser.root, portal.id, request)
        note += (f" It is also number {place['position']} in their prepared requests ({place['waiting']} not opened "
                 "yet), in Settings → Portals → Prepared requests, where 'Open the next request' and the window's own "
                 "'Next request' take them through the list.")
    except access_requests.AccessFormError as error:
        place = None
        note += f" It is not in their prepared requests: {error}"
    if not request["saved"]:
        note += (" They have no saved answers yet: they can add the ones they give every time in Settings → Portals → "
                 "Access request form.")
    return {"access_request": request, **({"queued": place} if place else {}), "form_labels_seen": saved["seen"],
            "note": note}


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
             "visible browser window, with their saved answers (purpose, the DPA / DSA drop-downs, subsidiary...) and "
             "your answers for this request filled into the form's empty fields; they check every field and submit it "
             "themselves. It is also added to their prepared requests (Settings → Portals), which they go through one "
             "after another. Use it after you found the table and saw that the person lacks access, one call per "
             "table, and name the table in your answer. address must be the table's own page in the catalog, where "
             "its request control is; when the catalog keeps one address for every table, give open_steps that reach "
             "the table from it (proved with portal_run) and form_button, the text of the control that opens the "
             "form.",
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
    ToolSpec("portal_prove_request",
             "Prove a report's data request: Wizard sends it twice from the person's browser, with the values given "
             "(first) and with one changed (second), and keeps it in the map as proven only when both answers are clean "
             "(no error from the portal), hold the same datasets and columns, and the changed value changed the rows. "
             "Only this marks a request verified, and a report is mapped only once one of its requests is proven. Each "
             "reply is evidence to cite and to check against the person's own export. Same read-only rules as "
             "portal_run.", ProveArgs, prove_request, "portal", "source"),
    ToolSpec("portal_map_route",
             "Say what reports already in a portal's map are for: use_for (the business questions and terms each "
             "answers), not_for (near misses, with the report to use instead) and definitions (the knowledge notes for "
             "its terms), plus a business summary where a report has none. It changes nothing else: not the menu path, "
             "how to open it, filters, data, requests, script or status, and it adds or removes no report. Use it for "
             "the reports portal_map(todo=true) lists under to_route.",
             MapRouteArgs, route_map, "portal", "present"),
]
