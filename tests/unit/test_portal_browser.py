"""Wizard's portal browser: the boundary rules on their own (no browser), then real exploration of a fake portal in a
Chromium-based browser (marker `browser`): folders, a clickable <div> list, a choice field, a search, a table and an ARIA
grid read as rows, and the things it must refuse or stop: export buttons, downloads, code editors, other hosts, sign-in
pages, message boxes and a run that wanders."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.helpers import TEST_TMP, MemoryRecorder, find_browser, make_settings
from tests.portal_site import Site

from wizard_api.config import ConfigError
from wizard_connectors import portal_browser
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.portal_browser import (
    BrowserOptions,
    Frame,
    Portal,
    PortalBrowser,
    PortalError,
    host_matches,
    refuse_click,
    refuse_typing,
    shape_table,
    to_number,
)
from wizard_connectors.tools import ToolContext, build_registry, build_services

# The boundary rules ---------------------------------------------------------------------------------------------------


def test_portal_addresses_are_https_except_on_this_pc() -> None:
    portal = Portal.make("gscm", "https://gscm.corp.example/reports/", "GSCM", ["static.corp.example", "*.cdn.corp.example"])
    assert portal.allows("gscm.corp.example") and portal.allows("a.cdn.corp.example") and not portal.allows("corp.example")
    assert Portal.make("demo", "http://127.0.0.1:8790/").allows("127.0.0.1")
    for bad in ("http://gscm.corp.example/", "ftp://gscm.corp.example/", "gscm.corp.example"):
        with pytest.raises(ValueError, match="https://"):
            Portal.make("gscm", bad)
    with pytest.raises(ValueError, match="portal id"):
        Portal.make("GSCM!", "https://gscm.corp.example/")
    assert host_matches("login.microsoftonline.com", portal_browser.DEFAULT_SIGNIN_HOSTS)
    assert host_matches("acme.okta.com", portal_browser.DEFAULT_SIGNIN_HOSTS)
    assert not host_matches("okta.com.evil.example", portal_browser.DEFAULT_SIGNIN_HOSTS)


@pytest.mark.parametrize("info", [
    {"tag": "button", "name": "Export to Excel"}, {"tag": "button", "name": "Share"}, {"tag": "div", "role": "menuitem", "name": "Delete"},
    {"tag": "a", "name": "Subscribe to this report", "href": "/x"}, {"tag": "button", "name": "Save as"},
    {"tag": "button", "name": "New dossier"}, {"tag": "div", "role": "menuitem", "name": "Create report"},
    {"tag": "a", "name": "Q3 numbers", "href": "/reports/export?id=4"}, {"tag": "a", "name": "file", "download": True},
    {"tag": "button", "name": "Sign out"}, {"tag": "button", "name": "Add to library"},
])
def test_clicks_that_change_send_or_export_are_refused(info: dict[str, Any]) -> None:
    with pytest.raises(PortalError) as refused:
        refuse_click(info)
    assert refused.value.code == "refused"


@pytest.mark.parametrize("info", [
    {"tag": "a", "name": "Market share", "href": "/folders/market-share"}, {"tag": "a", "name": "Exports by market", "href": "/r/exports-q3"},
    {"tag": "a", "name": "New Zealand", "href": "/markets/nz"}, {"tag": "div", "role": "treeitem", "name": "Sell-in"},
    {"tag": "button", "name": "Run report"}, {"tag": "button", "name": "Apply"}, {"tag": "div", "role": "option", "name": "Add-ons"},
])
def test_reading_clicks_are_allowed(info: dict[str, Any]) -> None:
    refuse_click(info)


def test_only_plain_fields_take_text() -> None:
    assert refuse_typing({"tag": "input", "type": "search"}) == "text"
    assert refuse_typing({"tag": "select"}) == "select"
    assert refuse_typing({"tag": "div", "role": "combobox"}) == "text"
    for info, code in (({"tag": "input", "type": "password"}, "refused"), ({"tag": "textarea", "editor": True}, "refused"),
                       ({"tag": "div", "role": "textbox", "editable": True}, "refused"), ({"tag": "input", "type": "file"}, "not_a_field"),
                       ({"tag": "button"}, "not_a_field")):
        with pytest.raises(PortalError) as refused:
            refuse_typing(info)
        assert refused.value.code == code


def test_table_cells_become_typed_columns() -> None:
    assert [to_number(v) for v in ("1,234", "(56)", "-7.5", "12.5%", "$1,000", "2K", "SA", "2026-07", "")] == \
        [1234, -56, -7.5, 12.5, 1000, 2000.0, None, None, None]
    columns, rows = shape_table(["Market", "Units", "Units", ""], [["SA", "1,000", "5%", "x"], ["AE", "-", "6%"]])
    assert [(c["key"], c["type"]) for c in columns] == [("market", "string"), ("units", "number"), ("units_2", "percent"),
                                                        ("column_4", "string")]
    assert rows == [["SA", 1000, 5, "x"], ["AE", None, 6, ""]]


def test_portal_settings(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, WIZARD_PORTAL_GSCM="https://gscm.corp.example/", WIZARD_PORTAL_GSCM_HOSTS="api.corp.example",
                             WIZARD_PORTAL_BDP="https://bdp.corp.example/superset/", WIZARD_PORTAL_BDP_NAME="Big Data Portal",
                             WIZARD_PORTAL_SIGNIN_HOSTS="sso.corp.example", WIZARD_BROWSER="chrome")
    assert {p.id: (p.name, sorted(p.hosts)) for p in settings.portals} == {
        "gscm": ("GSCM", ["api.corp.example", "gscm.corp.example"]), "bdp": ("Big Data Portal", ["bdp.corp.example"])}
    assert settings.browser.browser == "chrome" and "sso.corp.example" in settings.browser.signin_hosts
    assert make_settings(tmp_path, WIZARD_PORTAL_GSCM="https://gscm.corp.example/", WIZARD_BROWSER="off").portals == []
    with pytest.raises(ConfigError, match="https://"):
        make_settings(tmp_path, WIZARD_PORTAL_GSCM="http://gscm.corp.example/")
    with pytest.raises(ConfigError, match="host name"):
        make_settings(tmp_path, WIZARD_PORTAL_GSCM="https://gscm.corp.example/", WIZARD_PORTAL_GSCM_HOSTS="bad host")
    with pytest.raises(ConfigError, match="own PC"):
        make_settings(tmp_path, WIZARD_PORTAL_GSCM="https://gscm.corp.example/", WIZARD_AUTH_MODE="trusted-header",
                      WIZARD_PUBLIC_ORIGIN="https://wizard.corp.example")


def test_portal_tools_exist_only_where_portals_are_set_up(tmp_path: Path) -> None:
    assert not [n for n in build_registry(build_services()).specs if n.startswith("wizard_portal_")]
    browser = PortalBrowser([Portal.make("gscm", "https://gscm.corp.example/")], BrowserOptions(), lambda u: tmp_path / u)
    services = build_services(portals=browser)
    registry = build_registry(services)
    assert sorted(n for n in registry.specs if n.startswith("wizard_portal_")) == [
        "wizard_portal_click", "wizard_portal_open", "wizard_portal_page", "wizard_portal_read_table", "wizard_portal_type"]
    assert all(registry.specs[n].scope == "wizard" and registry.specs[n].read_only for n in registry.specs if "_portal_" in n)

    def context(identity: Identity) -> ToolContext:
        return ToolContext(identity=identity, run_id="run_t", recorder=MemoryRecorder(), services=services)
    stranger = Identity(id="u", email="u@x", name="U", role="Viewer")
    refused = registry.execute("wizard_portal_open", {"portal": "gscm"}, context(stranger))
    assert (refused.ok, refused.error_code) == (False, "not_entitled")
    unknown = registry.execute("wizard_portal_open", {"portal": "asap"}, context(stranger))
    assert unknown.error_code == "unknown_portal"
    owner = Identity(id="o", email="o@x", name="O", role="Owner", entitlements={"portal-gscm": SystemRights(reports=["*"], markets=["*"])})
    listed = registry.execute("wizard_list_sources", {}, context(owner))
    assert [s["system"] for s in listed.data["sources"] if s.get("kind") == "portal"] == ["gscm"]
    assert registry.execute("wizard_portal_open", {"portal": "gscm", "path": "//evil.example/x"}, context(owner)).error_code == "not_on_portal"


# Exploring a real page --------------------------------------------------------------------------------------------------

BROWSER = find_browser()
browser_test = pytest.mark.browser


@pytest.fixture(scope="module")
def portal() -> Iterator[tuple[Site, PortalBrowser]]:
    if BROWSER is None:
        pytest.skip("BLOCKED: no Chromium-based browser here for the portal-browser tests (set WIZARD_TEST_BROWSER)")
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    profiles = TEST_TMP / "portal-profiles"
    with Site() as site:
        browser = PortalBrowser([Portal.make("demo", site.url, "DEMO")], BrowserOptions(browser=BROWSER), lambda u: profiles / u)
        try:
            yield site, browser
        finally:
            browser.close()


@pytest.fixture
def frames() -> list[Frame]:
    return []


def ref(page: dict[str, Any], name: str) -> int:
    return next(e["ref"] for e in page["elements"] if e["name"] == name)


@browser_test
def test_explores_folders_prompts_and_reads_a_table(portal: tuple[Site, PortalBrowser], frames: list[Frame]) -> None:
    site, browser = portal
    show: Callable[[Frame], None] = frames.append
    home = browser.open("me", "run_a", "demo", None, show)
    assert home["page_title"] == "Reports home" and home["address"] == "/"
    assert {"Sell-in reports", "Market share", "Export all"} <= {e["name"] for e in home["elements"]}
    folder = browser.click("me", "run_a", "demo", ref(home, "Sell-in reports"), show)
    assert folder["page_title"] == "Sell-in reports" and folder["clicked"] == "Sell-in reports"
    kinds = {e["name"]: e["kind"] for e in folder["elements"]}
    assert kinds["Sell-in by model and month"] == "clickable" and kinds["Market"] == "select" and kinds["SQL"] == "code-editor"
    browser.type("me", "run_a", "demo", ref(folder, "Market"), "AE", False, show)
    found = browser.type("me", "run_a", "demo", ref(folder, "Search reports"), "sell-in", True, show)
    assert found["page_title"] == "Search results" and "Results for sell-in in AE" in found["text"]
    report = browser.click("me", "run_a", "demo", ref(found, "Sell-in by model and month"), show)
    assert report["tables"][0]["headers"] == ["Market", "Model", "Month", "Sell-in units", "Share"]
    table = browser.read_table("me", "run_a", "demo", None, 100, show)
    assert [c["key"] for c in table["columns"]] == ["market", "model", "month", "sell_in_units", "share"]
    assert table["rows"] == [["SA", "Model A", "2026-07", 1234, 12.5], ["SA", "Model B", "2026-07", -56, 3],
                             ["AE", "Model A", "2026-07", 2000, None]]
    assert table["trail"][-3:] == ["Sell-in reports", "Search results", "Sell-in by model and month"]
    assert table["url"].endswith("/report/sell-in-monthly") and len(table["digest"]) == 64

    # The person saw every step: an outlined target before each click, typing and read, and the page after each step.
    assert all(f.image.startswith(b"\xff\xd8") and f.portal == "demo" for f in frames)
    before = [f for f in frames if f.phase == "before"]
    assert [f.action for f in before][:2] == ["Clicking “Sell-in reports”", "Choosing “AE” in “Market”"]
    assert all(f.target and f.target["width"] > 0 for f in before)
    assert [f.action for f in frames if f.phase == "after"][0] == "Opened DEMO"
    assert not [r for r in site.requests if r.startswith("POST")]


@browser_test
def test_grids_say_when_rows_are_missing(portal: tuple[Site, PortalBrowser], frames: list[Frame]) -> None:
    _, browser = portal
    browser.open("me", "run_b", "demo", "/report/grid", frames.append)
    table = browser.read_table("me", "run_b", "demo", None, 100, frames.append)
    assert table["rows"] == [["SA", 10], ["AE", 20]] and "39 rows" in table["warnings"][0]
    with pytest.raises(PortalError) as wrong:
        browser.read_table("me", "run_b", "demo", 99, 100, frames.append)
    assert wrong.value.code == "unknown_table"


@browser_test
def test_refuses_exports_downloads_and_editors(portal: tuple[Site, PortalBrowser], frames: list[Frame]) -> None:
    site, browser = portal
    home = browser.open("me", "run_c", "demo", None, frames.append)
    for name, message in (("Export all", "only reads"), ("Get CSV", "download")):
        with pytest.raises(PortalError, match=message) as refused:
            browser.click("me", "run_c", "demo", ref(home, name), frames.append)
        assert refused.value.code == "refused"
    folder = browser.click("me", "run_c", "demo", ref(home, "Sell-in reports"), frames.append)
    with pytest.raises(PortalError, match="code or SQL") as refused:
        browser.type("me", "run_c", "demo", ref(folder, "SQL"), "DROP TABLE x", False, frames.append)
    with pytest.raises(PortalError) as stale:
        browser.click("me", "run_c", "demo", 999, frames.append)
    assert stale.value.code == "unknown_element"
    assert not [r for r in site.requests if r.startswith("POST") or r.startswith("GET /files")]


@browser_test
def test_stays_on_the_portal(portal: tuple[Site, PortalBrowser], frames: list[Frame]) -> None:
    site, browser = portal
    home = browser.open("me", "run_d", "demo", None, frames.append)
    stopped = browser.click("me", "run_d", "demo", ref(home, "Partner site"), frames.append)
    assert stopped["page_title"] == "Reports home" and "Stopped a page on localhost" in stopped["notices"][0]
    assert site.other_host_hits == []
    popup = browser.click("me", "run_d", "demo", ref(stopped, "Open in new tab"), frames.append)
    assert popup["page_title"] == "Pop-up report" and "new tab" in popup["notices"][0]
    home = browser.open("me", "run_d", "demo", None, frames.append)
    hello = browser.click("me", "run_d", "demo", ref(home, "Say hello"), frames.append)
    assert hello["notices"] == ["The page showed a message box (hello); Wizard dismissed it."]
    back = browser.page_action("me", "run_d", "demo", "back", frames.append)  # the followed tab's own history
    assert back["page_title"] == "Pop-up report"


@browser_test
def test_sign_in_pages_stop_the_step(portal: tuple[Site, PortalBrowser], frames: list[Frame]) -> None:
    _, browser = portal
    with pytest.raises(PortalError, match="Sign in") as signin:
        browser.open("me", "run_e", "demo", "/private", frames.append)
    assert signin.value.code == "signin_required"
    assert frames[-1].title == "Sign in"  # the person sees the sign-in page in the preview
    assert browser.status("me")[0]["state"] == "signin_required"
    assert browser.check("me", "demo")["state"] == "ready"


@browser_test
def test_the_portal_session_survives_the_browser_closing(portal: tuple[Site, PortalBrowser], frames: list[Frame]) -> None:
    _, browser = portal
    browser.open("me", "run_g", "demo", "/session", frames.append)  # the portal sets a session cookie
    assert browser.open("me", "run_g", "demo", "/members", frames.append)["page_title"] == "Members area"
    session = browser._sessions["me"]
    browser._call(lambda: browser._close_context(session))  # an idle close, or the sign-in window being closed
    assert any(c["name"] == "sid" for c in session.cookies)
    assert browser.open("me", "run_g", "demo", "/members", frames.append)["page_title"] == "Members area"
    stranger = browser._session("someone-else")
    assert not stranger.cookies, "one person's session never reaches another's browser"


@browser_test
def test_a_run_has_a_step_limit(portal: tuple[Site, PortalBrowser], frames: list[Frame], monkeypatch: pytest.MonkeyPatch) -> None:
    _, browser = portal
    monkeypatch.setattr(portal_browser, "MAX_STEPS", 2)
    browser.open("me", "run_f", "demo", None, frames.append)
    browser.page_action("me", "run_f", "demo", "scroll_down", frames.append)
    with pytest.raises(PortalError) as limit:
        browser.page_action("me", "run_f", "demo", "look", frames.append)
    assert limit.value.code == "step_limit"


def test_a_navigation_only_report_points_to_its_portal(tmp_path: Path) -> None:
    browser = PortalBrowser([Portal.make("asap", "https://asap.corp.example/")], BrowserOptions(), lambda u: tmp_path / u)
    services = build_services(portals=browser)
    registry = build_registry(services)
    rights = SystemRights(reports=["*"], markets=["*"])
    with_portal = Identity(id="o", email="o@x", name="O", role="Owner", entitlements={"asap": rights, "portal-asap": rights})
    without = Identity(id="d", email="d@x", name="D", role="Director", entitlements={"asap": rights})

    def call(identity: Identity, name: str) -> Any:
        context = ToolContext(identity=identity, run_id="run_t", recorder=MemoryRecorder(), services=services)
        return registry.execute(name, {"report_id": "asap-exec-dossier"}, context)
    schema = call(with_portal, "asap_get_report_schema").data["how_to_query"]
    assert schema.startswith("Navigation only") and "wizard_portal_open('asap')" in schema
    refused = call(with_portal, "asap_run_report")
    assert refused.error_code == "navigation_only" and "wizard_portal_open('asap')" in (refused.error_message or "")
    assert "wizard_portal_open" not in call(without, "asap_get_report_schema").data["how_to_query"]
