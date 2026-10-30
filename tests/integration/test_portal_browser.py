"""Gemini's portal tools in a real Chromium, against a simulated portal on this machine: a GSCM-like Nexacro application
object with datasets and a bookmark list, an ASAP-like MicroStrategy session with menuInfo.do, Nexacro SSV transactions,
a sign-in page, a Big Data Portal whose information catalog and Superset sit on two hosts, and the controls and requests
Wizard must refuse. The real portals are first read on a work PC.

Needs a Chromium or Chrome (WIZARD_TEST_BROWSER, Playwright's browser cache, or an installed Chrome); BLOCKED otherwise."""
from __future__ import annotations

import functools
import glob
import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from tests.helpers import TEST_TMP, MemoryRecorder

from wizard_agent.secret_box import SecretBox
from wizard_connectors import access_requests
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.portal_browser import FILL_EVERY_S, PortalBrowser, PortalBrowsers
from wizard_connectors.portals import settings_from
from wizard_connectors.tools import ToolContext, build_registry, build_services


def find_browser() -> str | None:
    candidates = [os.environ.get("WIZARD_TEST_BROWSER") or ""]
    for pattern in ("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome", "/opt/pw-browsers/chromium-*/chrome-linux*/chrome",
                    "~/AppData/Local/ms-playwright/chromium-*/chrome-win*/chrome.exe"):
        candidates += sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)
    candidates += [shutil.which(name) or "" for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")]
    candidates += [r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
    return next((c for c in candidates if c and Path(c).is_file()), None)


BROWSER = find_browser()
pytestmark = [pytest.mark.browser,
              pytest.mark.skipif(BROWSER is None, reason="BLOCKED: no Chromium or Chrome for the portal browser tests "
                                                         "(set WIZARD_TEST_BROWSER)")]
TOKEN = "TOKEN-" + "k" * 48  # the ASAP session token: it must never appear in what Gemini sees

GSCM_PAGE = """<!doctype html><html><head><title>GSCM</title><script>
const ds = (name, cols, rows) => ({name, getRowCount() { return rows.length; }, getColumn(r, c) { return rows[r][cols.indexOf(c)]; },
  getColCount() { return cols.length; }, getColID(i) { return cols[i]; }});
const ds_list = ds('ds_list', ['MARKET', 'WEEK', 'UNITS'], [['AE', '2026W40', 120], ['SA', '2026W40', 340], ['KW', '2026W40', null]]);
const ds_market = ds('ds_market', ['CODE', 'NAME'], [['AE', 'UAE'], ['SA', 'Saudi Arabia']]);
const grid = {id: 'grd_list', name: 'grd_list', binddataset: 'ds_list', _type_name: 'Grid'};
const cbo = {id: 'cbo_market', name: 'cbo_market', _type_name: 'Combo', value: 'AE', codecolumn: 'CODE', datacolumn: 'NAME',
             innerdataset: 'ds_market'};
const btn = {id: 'btn_search', name: 'btn_search', _type_name: 'Button', text: 'Search'};
// Nexacro forms also name each component as a property, and carry the report's own functions (fn_*).
const form = {components: [grid, cbo, btn], grd_list: grid, ds_list, ds_market, fn_search(week) { return 'searched ' + week; }};
for (const c of [grid, cbo, btn]) c.parent = form;
const APP = {mainframe: {VFrameSet: {WorkFrame0: {form}}},
  gds_bookmark: ds('gds_bookmark', ['userreportid', 'userreportname', 'publicscope', 'scope', 'gbm', 'menuscope', 'menuid', 'menuname',
                                    'menugroupid', 'menugroupname'],
                   [['RC_1', 'MENA_Actual_sales', 'PUBLIC', 'AS', 'MOBILE', 'MP', 'AS470', 'Actual Sales', 'AS313', 'SCM']]),
  gds_menu: ds('gds_menu', ['MENU_ID', 'MENU_NAME', 'PARENT_ID'], [['AS313', 'SCM', ''], ['AS470', 'Actual Sales', 'AS313']]),
  gfn_openMenu(menuId) { return 'opened ' + menuId; }};
window.nexacro = {getApplication: () => APP};
</script></head><body>
<div id="mainframe.VFrameSet.WorkFrame0.form.grd_list" style="width:300px;height:60px">grid</div>
<div id="mainframe.VFrameSet.WorkFrame0.form.sta_title:text" style="width:100px;height:20px">Weekly</div>
<button id="mainframe.VFrameSet.TopFrame.Setting0.form.div_favorite.form.btn_save">Save</button>
<button id="go" onclick="if (confirm('Delete every bookmark?')) location.href = '/svc/deleteAll.do';">Go</button>
<table id="t"><tr><th>Market</th><th>Units</th></tr><tr><td>AE</td><td>1,234</td></tr><tr><td>SA</td><td>(56)</td></tr></table>
<script>
const x = new XMLHttpRequest(); x.open('POST', '/svc/selectWeekly.do'); x.setRequestHeader('Content-Type', 'text/plain');
x.send('SSV:utf-8\\x1eweek:string=2026W40\\x1f\\x1e');
</script></body></html>"""

ASAP_PAGE = """<!doctype html><html><head><title>ASAP</title><script>
const _COMMON_INFO = {"MSTR_MAIN_MENU_ID": "ROOT", "MSTR_CUSTOM_WEB_CONTEXT_PATH": "/mstr"};
const _SESSION = {"MSTRWEB_AUTH_TOKEN_ENC": "TOKEN"};
</script></head><body><nav><a href="#">Sales</a></nav></body></html>""".replace('"TOKEN"', f'"{TOKEN}"')

CATALOG_PAGE = """<!doctype html><html><head><title>Information catalog</title></head><body>
<table id="found"><tr><th>Table</th><th>Description</th><th>Access</th></tr>
<tr><td>sales_daily</td><td>Daily sell-out by market</td><td>No</td></tr></table>
<button id="ask" onclick="fetch('/api/v1/access-requests', {method: 'POST', body: '{}'})">Request access</button>
</body></html>"""

# A catalog table page whose request form appears when the person presses Request access.
TABLE_PAGE = """<!doctype html><html><head><title>sales_daily</title></head><body>
<label>Search <input id="search" type="search"></label><h1>sales_daily</h1><p>Daily sell-out by market</p>
<button id="ask" onclick="document.getElementById('dialog').style.display = 'block'">Request access</button>
<div id="dialog" class="modal" style="display:none"><form id="request" method="post" action="/api/requestAccess">
<label for="purpose">Purpose *</label><input id="purpose" name="purpose">
<div class="form-item"><label>Manager</label><input name="mgr"></div>
<div class="form-item"><label>Department</label><input name="dept" value="Finance"></div>
<label>Duration <select name="duration"><option value="">Choose</option><option value="3m">3 months</option>
<option value="6m">6 months</option></select></label>
<table><tr><td>Table name</td><td><input name="tbl"></td></tr></table>
<textarea aria-label="Justification" name="why"></textarea>
<label>Password <input type="password" name="pw"></label>
<button id="send" type="submit">Send request</button></form></div></body></html>"""

MENU = {"ROOT": [{"id": "S", "name": "01.Sales"}, {"id": "F", "name": "02.Finance"}],
        "S": {"id": "S", "name": "01.Sales", "children": [{"id": "G", "name": "Sell-out", "child": [{"id": "R1", "name": "Weekly Sell-out"}]}]},
        "F": {"id": "F", "name": "02.Finance", "children": [{"id": "R2", "name": "P&L"}]}}


class Portal(SimpleHTTPRequestHandler):
    hits: list[str] = []

    def log_message(self, *args: Any) -> None:
        pass

    def reply(self, body: str | bytes, kind: str = "text/html", status: int = 200) -> None:
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        self.hits.append(f"GET {self.path}")
        pages = {"/": GSCM_PAGE, "/asap": ASAP_PAGE, "/login": "<title>Sign in</title><input type=password>",
                 "/sso": "<title>Company</title><p>Single Sign On</p><input type=email>",
                 "/help": "<title>Help</title><p>Trouble with single sign-on? Call the desk.</p><input type=text>",
                 "/report": "<title>Report</title><table><tr><th>A</th></tr><tr><td>1</td></tr></table>",
                 "/superset": "<title>Superset</title><div id=app data-bootstrap='{}'>SQL Lab</div>",
                 "/catalog": CATALOG_PAGE, "/catalog/table/sales_daily": TABLE_PAGE}
        self.reply(pages.get(self.path.split("?")[0], "<title>Not found</title>"), status=200 if self.path.split("?")[0] in pages else 404)

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("content-length") or 0)).decode()
        self.hits.append(f"POST {self.path} {body[:80]}")
        if self.path.startswith("/mstr/menuInfo.do"):
            if f"authToken={TOKEN}" not in body:
                self.reply('{"errorCode": 401, "data": null}', "application/json")
                return
            folder = self.path.split("folderId=")[1]
            self.reply(json.dumps({"errorCode": 0, "data": json.dumps(MENU[folder])}), "application/json")
        elif self.path.startswith("/svc/selectWeekly.do"):
            week = body.split("week:string=")[1].split("\x1f")[0]
            self.reply(f"SSV:utf-8\x1eErrorCode:int=0\x1fErrorMsg:string=OK\x1eDataset:ds_out\x1e_RowType_\x1fMARKET:STRING(8)"
                       f"\x1fWEEK:STRING(8)\x1fQTY:INT(4)\x1eN\x1fAE\x1f{week}\x1f10\x1eN\x1fSA\x1f{week}\x1f\x03\x1e\x1e", "text/plain")
        else:
            self.reply("ok", "text/plain")


@pytest.fixture(scope="module")
def portal_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Portal, directory=str(Path(__file__).parent)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


@pytest.fixture(scope="module")
def setup(portal_url: str) -> Iterator[tuple[Any, Any]]:
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="portal-", dir=TEST_TMP))
    settings = settings_from({"WIZARD_PORTAL_GSCM_URL": portal_url, "WIZARD_PORTAL_ASAP_URL": portal_url + "asap",
                              "WIZARD_PORTAL_BDP_URL": portal_url + "superset",
                              "WIZARD_PORTAL_BDP_CATALOG_URL": catalog_address(portal_url),
                              "WIZARD_BROWSER_EXECUTABLE": BROWSER})
    assert settings is not None
    services = build_services()
    services.portals = PortalBrowsers(settings, lambda user_id: root / user_id)
    registry = build_registry(services)
    yield services, registry
    services.portals.shutdown()
    shutil.rmtree(root, ignore_errors=True)


def catalog_address(portal_url: str) -> str:
    """The Big Data Portal's information catalog, on another host than its Superset (localhost, not 127.0.0.1)."""
    return portal_url.replace("127.0.0.1", "localhost") + "catalog"


def refused(outcome: Any) -> str | None:
    """The refusal of a call: its error, or, when steps before it read something, the step it stopped at."""
    return outcome.error_code if not outcome.ok else (outcome.data.get("stopped") or {}).get("code")


def call(setup: tuple[Any, Any], name: str, args: dict[str, Any], recorder: MemoryRecorder | None = None,
         systems: tuple[str, ...] = ("gscm", "asap")) -> Any:
    services, registry = setup
    identity = Identity(id="owner", email="owner@example.com", name="Owner", role="Owner",
                        entitlements={system: SystemRights(reports=["*"], markets=["*"]) for system in systems})
    context = ToolContext(identity=identity, run_id="run_t", recorder=recorder or MemoryRecorder(), services=services)
    return registry.execute(name, args, context)


def test_a_nexacro_dataset_becomes_live_evidence_with_the_script_as_its_query(setup):
    recorder = MemoryRecorder()
    script = ("await W.waitFor(() => W.nexacro.activeForms().length);"
              "const sets = W.nexacro.datasets(W.nexacro.activeForms()[0]);"
              "return W.nexacro.readGrid(sets[0].path);")
    outcome = call(setup, "portal_run", {"system": "gscm", "title": "Weekly units by market", "steps": [
        {"action": "goto", "url": "/"}, {"action": "evaluate", "script": script}]}, recorder)
    assert outcome.ok, outcome.error_message
    table = outcome.data["outputs"][-1]
    assert table["columns"] == ["MARKET", "WEEK", "UNITS"] and table["rows"][1] == ["SA", "2026W40", 340]
    assert table["evidence_id"] == "E1" and table["cite_as"] == "[E1]" and outcome.data["data_mode"] == "LIVE"
    evidence = recorder.evidence[0]
    assert evidence["data_mode"] == "LIVE" and evidence["connector_status"] == "BROWSER_SESSION"
    assert evidence["system"] == "gscm" and evidence["report_name"] == "Weekly units by market"
    assert evidence["request"]["steps"][1]["script"] == script, "the script is the evidence's query"
    assert "not verified" in evidence["access_note"]
    assert evidence["columns"][2] == {"key": "UNITS", "label": "UNITS", "type": "number"}


def test_bookmarks_tables_and_the_page_outline(setup):
    outcome = call(setup, "portal_run", {"system": "gscm", "steps": [
        {"action": "goto", "url": "/"}, {"action": "evaluate", "script": "return W.nexacro.bookmarks();"},
        {"action": "read_table", "selector": "#t"}, {"action": "look"}]})
    assert outcome.ok, outcome.error_message
    bookmarks, table, look = outcome.data["outputs"][1:]
    assert bookmarks["rows"][0][:2] == ["RC_1", "MENA_Actual_sales"]
    assert table["rows"] == [["AE", 1234], ["SA", -56]]
    main = look["value"]["frames"][0]
    assert main["technology"]["nexacro"] is True
    assert main["technology"]["nexacro_report_forms"] == ["mainframe.VFrameSet.WorkFrame0.form"]
    assert any(c["label"] == "Go" for c in main["controls"])


def test_a_captured_nexacro_transaction_is_replayed_with_new_parameters(setup):
    outcome = call(setup, "portal_run", {"system": "gscm", "steps": [
        {"action": "goto", "url": "/"},
        {"action": "evaluate", "script": "await W.waitFor(() => W.requests('selectWeekly').length);"
                                          "const reply = await W.replay('selectWeekly', {replace: [['2026W40', '2026W41']]});"
                                          "return W.parse(reply.text).datasets.ds_out;"}]})
    assert outcome.ok, outcome.error_message
    assert outcome.data["outputs"][-1]["rows"] == [["AE", "2026W41", 10], ["SA", "2026W41", None]]
    seen = [r for r in outcome.data["requests"] if "selectWeekly" in r["url"]]
    assert seen and seen[0]["method"] == "POST" and "week:string=2026W40" in seen[0]["body"]


def test_the_asap_menu_is_walked_without_the_token_leaving_the_page(setup):
    outcome = call(setup, "portal_run", {"system": "asap", "steps": [
        {"action": "goto", "url": "/asap"},
        {"action": "evaluate", "script": "return {session: W.mstr.session(), reports: await W.mstr.reports()};"}]})
    assert outcome.ok, outcome.error_message
    value = outcome.data["outputs"][-1]["value"]
    assert value["session"]["signed_in"] is True and value["session"]["web_base"].endswith("/mstr")
    assert {"path": ["Sales", "Sell-out", "Weekly Sell-out"], "id": "R1"} in value["reports"]
    assert {"path": ["Finance", "P&L"], "id": "R2"} in value["reports"]
    assert TOKEN not in json.dumps(outcome.data), "the session token never reaches Gemini"
    leak = call(setup, "portal_run", {"system": "asap", "steps": [
        {"action": "evaluate", "script": "return {t: _SESSION.MSTRWEB_AUTH_TOKEN_ENC, s: _SESSION};"}]})
    assert leak.ok and TOKEN not in json.dumps(leak.data)
    recorder = MemoryRecorder()
    table = call(setup, "portal_run", {"system": "asap", "steps": [{"action": "evaluate", "script":
        "return [{market: 'AE', auth_token: _SESSION.MSTRWEB_AUTH_TOKEN_ENC, note: 'x' + _SESSION.MSTRWEB_AUTH_TOKEN_ENC}];"}]},
        recorder)
    assert table.ok and TOKEN not in json.dumps(table.data) and TOKEN not in json.dumps(recorder.evidence)
    assert table.data["outputs"][0]["rows"][0][:2] == ["AE", "<redacted>"]
    error = call(setup, "portal_run", {"system": "asap", "steps": [{"action": "evaluate", "script":
        "throw new Error('bad ' + _SESSION.MSTRWEB_AUTH_TOKEN_ENC);"}]})
    assert not error.ok and TOKEN not in (error.error_message or "")


def test_the_nexacro_helpers_find_the_menu_the_shortcuts_and_a_reports_filters(setup):
    outcome = call(setup, "portal_run", {"system": "gscm", "steps": [
        {"action": "goto", "url": "/"},
        {"action": "evaluate", "script": "return {sets: W.nexacro.appDatasets(), fns: W.nexacro.functions(), inputs: W.nexacro.inputs()};"}]})
    assert outcome.ok, outcome.error_message
    value = outcome.data["outputs"][-1]["value"]
    assert value["sets"][0] == {"name": "gds_menu", "rows": 2, "columns": ["MENU_ID", "MENU_NAME", "PARENT_ID"]}
    assert [s["name"] for s in value["sets"]] == ["gds_menu", "gds_bookmark"]
    functions = {f["name"]: f for f in value["fns"]}
    assert functions["gfn_openMenu"]["where"] == "application" and "menuId" in functions["gfn_openMenu"]["source"]
    assert functions["fn_search"]["where"] == "mainframe.VFrameSet.WorkFrame0.form"
    inputs = {i["name"]: i for i in value["inputs"]}
    assert inputs["cbo_market"] == {"path": "mainframe.VFrameSet.WorkFrame0.form.cbo_market", "type": "Combo", "name": "cbo_market",
                                    "value": "AE", "options_dataset": "ds_market", "options_count": 2,
                                    "options": ["AE = UAE", "SA = Saudi Arabia"]}
    assert inputs["btn_search"]["text"] == "Search"
    assert inputs["grd_list"]["dataset"] == "ds_list" and inputs["grd_list"]["rows"] == 3


def test_a_request_step_reads_a_transaction_straight_from_the_browser_without_opening_the_portal(setup, portal_url):
    away = call(setup, "portal_run", {"system": "bdp", "steps": [{"action": "goto", "url": catalog_address(portal_url)}]},
                systems=("bdp",))
    assert away.ok, away.error_message
    Portal.hits.clear()
    recorder = MemoryRecorder()
    body = "SSV:utf-8\x1eweek:string={{week}}\x1f\x1e"
    outcome = call(setup, "portal_run", {"system": "gscm", "title": "Weekly units", "params": [{"name": "week", "value": "2026W44"}],
                                         "steps": [{"action": "request", "url": "/svc/selectWeekly.do", "body": body,
                                                    "headers": {"Content-Type": "text/plain"}}]}, recorder)
    assert outcome.ok, outcome.error_message
    table = outcome.data["outputs"][0]
    assert table["columns"] == ["MARKET", "WEEK", "QTY"] and table["rows"] == [["AE", "2026W44", 10], ["SA", "2026W44", None]]
    assert table["evidence_id"] == "E1" and recorder.evidence[0]["data_mode"] == "LIVE"
    assert recorder.evidence[0]["request"]["steps"][0]["body"] == body.replace("{{week}}", "2026W44"), "the request is the query"
    assert "GET /" not in Portal.hits, "GSCM's start page (its whole client) was never opened"
    assert Portal.hits[0] == "GET /robots.txt" and Portal.hits[1].startswith("POST /svc/selectWeekly.do")
    Portal.hits.clear()
    scripted = call(setup, "portal_run", {"system": "gscm", "steps": [
        {"action": "request", "url": "/svc/selectWeekly.do", "body": body.replace("{{week}}", "2026W45"),
         "script": "return {status: R.status, code: R.data.parameters.ErrorCode, weeks: R.data.datasets.ds_out.rows.map(r => r[1])};"}]})
    assert scripted.ok and scripted.data["outputs"][0]["value"] == {"status": 200, "code": "0", "weeks": ["2026W45", "2026W45"]}
    assert [h.split(" ")[0] for h in Portal.hits] == ["POST"], "on the portal's origin already: no page opens"


def test_a_request_step_follows_the_same_read_only_rules(setup):
    Portal.hits.clear()
    for step, code in (({"url": "/svc/saveBookmark.do", "body": "x"}, "request_refused"),
                       ({"url": "/api/thing", "method": "PUT", "body": "{}"}, "request_refused"),
                       ({"url": "https://example.com/collect"}, "host_not_allowed")):
        outcome = call(setup, "portal_run", {"system": "gscm", "steps": [{"action": "request", **step}]})
        assert refused(outcome) == code, step
    assert not any("saveBookmark" in hit or "/api/thing" in hit for hit in Portal.hits)


def test_writes_other_hosts_and_forbidden_clicks_are_refused(setup):
    Portal.hits.clear()
    save = call(setup, "portal_run", {"system": "gscm", "steps": [{"action": "goto", "url": "/"},
                                                                   {"action": "click", "text": "Save"}]})
    assert refused(save) == "click_refused"
    for script in ("return (await fetch('/svc/saveBookmark.do', {method: 'POST', body: 'x'})).status;",
                   "return (await fetch('https://example.com/collect?d=1')).status;",
                   "return (await fetch('/api/thing', {method: 'PUT', body: '{}'})).status;"):
        outcome = call(setup, "portal_run", {"system": "gscm", "steps": [{"action": "evaluate", "script": script}]})
        assert refused(outcome) == "request_refused", script
    confirm = call(setup, "portal_run", {"system": "gscm", "steps": [{"action": "click", "selector": "#go"},
                                                                      {"action": "wait", "timeout_ms": 800}]})
    assert confirm.ok and confirm.data["dialogs"] == ["confirm: Delete every bookmark?"]
    assert not any("saveBookmark" in hit or "deleteAll" in hit or "/api/thing" in hit for hit in Portal.hits)
    away = call(setup, "portal_run", {"system": "gscm", "steps": [{"action": "goto", "url": "https://example.com/"}]})
    assert refused(away) == "host_not_allowed"


def test_a_sign_in_page_stops_the_read_and_says_how_to_sign_in(setup):
    outcome = call(setup, "portal_run", {"system": "gscm", "steps": [{"action": "goto", "url": "/login"}]})
    assert not outcome.ok and outcome.error_code == "sign_in_required"
    assert "Settings → Portals" in (outcome.error_message or "")
    picker = call(setup, "portal_run", {"system": "gscm", "steps": [{"action": "goto", "url": "/sso"}]})
    assert not picker.ok and picker.error_code == "sign_in_required", "sign-in text without a password field"
    help_page = call(setup, "portal_run", {"system": "gscm", "steps": [{"action": "goto", "url": "/help"}]})
    assert help_page.ok, "one sign-in phrase on a portal page is not a sign-in page"


def test_a_step_that_fails_keeps_what_the_steps_before_it_read(setup):
    outcome = call(setup, "portal_run", {"system": "gscm", "steps": [
        {"action": "goto", "url": "/report"}, {"action": "read_table"},
        {"action": "click", "selector": "#missing", "timeout_ms": 600}]})
    assert outcome.ok and outcome.data["evidence_ids"] == ["E1"]
    assert outcome.data["stopped"]["code"] == "step_failed" and "Step 3" in outcome.data["stopped"]["message"]


def test_a_script_that_worked_is_kept_and_rerun_with_parameters(setup):
    saved = call(setup, "portal_save_script", {"system": "gscm", "name": "weekly-units", "description": "Weekly units by market for one week.",
                                               "params": [{"name": "week", "value": "2026W40"}], "steps": [
        {"action": "goto", "url": "/"},
        {"action": "evaluate", "script": "await W.waitFor(() => W.requests('selectWeekly').length);"
                                          "return W.parse((await W.replay('selectWeekly', {replace: [['2026W40', P.week]]})).text).datasets.ds_out;"}]})
    assert saved.ok, saved.error_message
    guide = call(setup, "portal_guide", {"system": "gscm"})
    assert guide.ok and [s["name"] for s in guide.data["saved_scripts"]] == ["weekly-units"]
    assert "Nexacro" in guide.data["guide"] and "W.replay" in guide.data["guide"] and guide.data["start_page"] == "/"
    rerun = call(setup, "portal_run", {"system": "gscm", "script": "weekly-units", "params": [{"name": "week", "value": "2026W45"}]})
    assert rerun.ok, rerun.error_message
    assert rerun.data["outputs"][-1]["rows"][0] == ["AE", "2026W45", 10]
    missing = call(setup, "portal_run", {"system": "gscm", "script": "weekly-units"})
    assert not missing.ok and "week" in (missing.error_message or "")


def test_a_portal_the_person_lacks_is_not_available(setup):
    outcome = call(setup, "portal_run", {"system": "bdp", "steps": [{"action": "look"}]})
    assert not outcome.ok and outcome.error_code == "portal_not_available"


def test_the_big_data_portal_reads_its_information_catalog_and_superset_but_never_requests_access(setup, portal_url):
    catalog = catalog_address(portal_url)
    guide = call(setup, "portal_guide", {"system": "bdp"}, systems=("bdp",))
    assert guide.ok, guide.error_message
    assert guide.data["applications"] == [
        {"part": "superset", "name": "Superset", "address": portal_url + "superset"},
        {"part": "catalog", "name": "information catalog", "address": catalog}]
    assert "information catalog" in guide.data["guide"] and "W.superset.sql" in guide.data["guide"]
    found = call(setup, "portal_run", {"system": "bdp", "title": "Tables about sell-out", "steps": [
        {"action": "goto", "url": catalog}, {"action": "read_table", "selector": "#found"},
        {"action": "goto", "url": "/report"}]}, systems=("bdp",))
    assert found.ok, found.error_message
    assert found.data["outputs"][1]["rows"] == [["sales_daily", "Daily sell-out by market", "No"]]
    assert found.data["page"]["url"].startswith("http://localhost:"), "a path stays on the catalog's host"
    Portal.hits.clear()
    ask = call(setup, "portal_run", {"system": "bdp", "steps": [{"action": "goto", "url": catalog},
                                                                {"action": "click", "selector": "#ask"}]}, systems=("bdp",))
    assert refused(ask) == "click_refused"
    script = "return (await fetch('/api/v1/access-requests', {method: 'POST', body: '{}'})).status;"
    sent = call(setup, "portal_run", {"system": "bdp", "steps": [{"action": "evaluate", "script": script}]}, systems=("bdp",))
    assert refused(sent) == "request_refused"
    assert not any("access-requests" in hit for hit in Portal.hits)
    checked = setup[0].portals.for_user("owner").check()["portals"]
    assert [(c["id"], c["name"], c["signed_in"]) for c in checked if c["id"].startswith("bdp")] == [
        ("bdp-superset", "Big Data Portal: Superset", True), ("bdp-catalog", "Big Data Portal: information catalog", True)]


def wait_until(condition: Any, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.25)


def test_the_access_request_form_is_filled_from_saved_answers_and_only_the_person_submits_it(setup, portal_url):
    services = setup[0]
    browser = services.portals.for_user("owner")
    browser.show_windows = False  # the person's window, headless on a test machine
    portal = services.portals.settings.portal("bdp")
    access_requests.save(browser.root, portal, "", [
        {"label": "Purpose", "value": "Weekly sales reporting"}, {"label": "Manager", "value": "Head of Sales"},
        {"label": "Department", "value": "Sales"}, {"label": "Duration", "value": "6 months"},
        {"label": "Password", "value": "never-typed"}])
    proposal = call(setup, "portal_request_access", {"system": "bdp", "address": catalog_address(portal_url) + "/table/sales_daily",
                                                     "tables": ["sales_daily"],
                                                     "answers": [{"label": "Justification", "value": "GCC sell-out review"}]},
                    systems=("bdp",))
    assert proposal.ok, proposal.error_message
    request = proposal.data["access_request"]
    Portal.hits.clear()
    saved = access_requests.form(browser.root, portal)["fields"]
    status = browser.open_access_request(portal, request["address"],
                                         access_requests.answers(saved, request["answers"], request["tables"]))
    assert status["window"] == "access_request" and status["access_request"]["filled"] == [], "the form is not shown yet"
    busy = call(setup, "portal_run", {"system": "bdp", "steps": [{"action": "look"}]}, systems=("bdp",))
    assert not busy.ok and busy.error_code == "signing_in" and "access request" in (busy.error_message or "")

    def page() -> Any:
        return browser._context.pages[0]
    browser.run(lambda: page().click("#ask"))  # the person presses Request access; Wizard fills the form as it appears
    wait_until(lambda: len(browser.status()["access_request"]["filled"]) >= 5)
    status = browser.status()["access_request"]
    assert sorted(status["filled"]) == ["Duration", "Justification", "Manager", "Purpose", "Table"]
    assert status["missing"] == ["Password"], "a password field is never filled"
    values = browser.run(lambda: page().evaluate(
        "() => Object.fromEntries([...document.querySelectorAll('#request [name], #search')].map(e => [e.name || e.id, e.value]))"))
    assert values == {"purpose": "Weekly sales reporting", "mgr": "Head of Sales", "dept": "Finance", "duration": "6m",
                      "tbl": "sales_daily", "why": "GCC sell-out review", "pw": "", "search": ""}, "only empty fields, only the form"
    assert "submit the request yourself" in browser.run(lambda: page().inner_text("#wizard-access-banner"))
    browser.run(lambda: page().fill("#purpose", ""))  # the person clears a field Wizard filled: it stays as they left it
    time.sleep(2 * FILL_EVERY_S + 0.5)
    assert browser.run(lambda: page().input_value("#purpose")) == ""
    assert not any("requestAccess" in hit for hit in Portal.hits), "Wizard never submits the request"
    browser.run(lambda: page().click("#send"))  # the person submits: their own window does not refuse it
    wait_until(lambda: any(hit.startswith("POST /api/requestAccess") for hit in Portal.hits))
    assert any(hit.startswith("POST /api/requestAccess") for hit in Portal.hits)
    assert browser.finish_sign_in()["window"] is None
    seen = access_requests.form(browser.root, portal)["seen"]
    assert {"Purpose", "Manager", "Department", "Duration", "Table name", "Justification"} <= set(seen)
    assert "Password" not in seen and "Search" not in seen
    after = call(setup, "portal_run", {"system": "bdp", "steps": [{"action": "goto", "url": catalog_address(portal_url)}]},
                 systems=("bdp",))
    assert after.ok, "Gemini reads again once the window is closed"


class SessionPortal(BaseHTTPRequestHandler):
    """A portal whose sign-in is a session-only cookie, as most portal and sign-in sessions are, beside a lasting one."""

    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        if self.path == "/signed-in":  # where the person's sign-in ends
            self.send_response(302)
            self.send_header("set-cookie", "sid=session-1; Path=/; HttpOnly")
            self.send_header("set-cookie", "lang=en; Path=/; Max-Age=86400")
            self.send_header("location", "/")
        elif self.path == "/" and "sid=session-1" not in (self.headers.get("cookie") or ""):
            self.send_response(302)
            self.send_header("location", "/login")
        else:
            body = (b"<title>GSCM</title><p>Welcome</p>" if self.path == "/"
                    else b"<title>Sign in</title><input type=password>")
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_header("content-length", "0")
        self.end_headers()


class Headless:
    """Playwright with the sign-in window headless too, so the test runs where there is no display."""

    def __init__(self) -> None:
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.chromium = self

    def launch_persistent_context(self, profile: str, **options: Any) -> Any:
        return self.playwright.chromium.launch_persistent_context(profile, **{**options, "headless": True})

    def stop(self) -> None:
        self.playwright.stop()


def test_the_sign_in_outlives_its_window_and_a_restart():
    """Chrome drops session-only cookies when it closes: Check sign-in said "asks for a sign-in" right after the person
    signed in (owner, 28 October 2026). Wizard keeps them, protected, and puts them back when the browser starts."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), SessionPortal)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    root = Path(tempfile.mkdtemp(prefix="portal-session-", dir=TEST_TMP)) / "portal-browser"
    settings = settings_from({"WIZARD_PORTAL_GSCM_URL": url, "WIZARD_BROWSER_EXECUTABLE": BROWSER})
    assert settings is not None
    box = SecretBox(force_plain=True)
    browser = PortalBrowser(settings, root, Headless, box)
    try:
        browser.begin_sign_in()
        browser.run(lambda: browser._context.pages[0].goto(url + "signed-in"))  # the person signs in
        browser.run(lambda: [page.close() for page in list(browser._context.pages)])  # and closes the window
        deadline = time.monotonic() + 15
        while browser.status()["signing_in"] and time.monotonic() < deadline:
            time.sleep(0.2)
        assert [(c["signed_in"], c["title"]) for c in browser.check()["portals"]] == [(True, "GSCM")]
    finally:
        browser.shutdown()
    kept = json.loads(box.read(root / "session.bin") or "[]")
    assert [c["name"] for c in kept] == ["sid"], "only the session-only cookie: Chrome keeps the lasting one itself"
    again = PortalBrowser(settings, root, Headless, box)  # Wizard restarted
    try:
        assert [(c["signed_in"], c["title"]) for c in again.check()["portals"]] == [(True, "GSCM")]
    finally:
        again.shutdown()
        server.shutdown()
        shutil.rmtree(root.parent, ignore_errors=True)
