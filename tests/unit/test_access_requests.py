"""Access requests in the Big Data Portal's information catalog, without a browser: the person's saved answers, the
addresses a request window may open, what it fills, Gemini's proposal and the API. The window itself, filling a real
form, is tested in tests/integration/test_portal_browser.py."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.helpers import HEADERS, MemoryRecorder, login, make_settings

from wizard_connectors import access_requests
from wizard_connectors.access_requests import AccessFormError
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.portal_browser import PortalBrowser, PortalBrowsers
from wizard_connectors.portals import settings_from
from wizard_connectors.tools import ToolContext, build_registry, build_services

BDP = {"WIZARD_PORTAL_BDP_URL": "https://superset.corp.example.com/sqllab/",
       "WIZARD_PORTAL_BDP_CATALOG_URL": "https://catalog.corp.example.com/home",
       "WIZARD_PORTAL_GSCM_URL": "https://gscm.other.example.org/"}


def portal() -> Any:
    settings = settings_from(BDP)
    assert settings is not None
    return settings.portal("bdp")


PRESET_NAMES = ["Purpose", "DPA / DSA › Purpose", "DPA / DSA › Subsidiary Name (Full Legal Name)", "DPA / DSA › Subsidiary Address"]


def own(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in fields if not f.get("preset")]


def test_the_form_starts_with_the_portals_predefined_fields_for_the_person_to_answer(tmp_path: Path):
    bdp = portal()
    form = access_requests.form(tmp_path, bdp)
    assert {k: v for k, v in form.items() if k != "fields"} == {
        "system": "bdp", "page": "", "seen": [], "default_page": "https://catalog.corp.example.com/home", "queue": [],
        "sending": {"enabled": False, "proof": None, "last_submission": None}}
    assert [access_requests.name(f) for f in form["fields"]] == PRESET_NAMES
    assert all(f["preset"] and f["value"] == "" and f["hint"] for f in form["fields"]), "the person sets every value"
    assert [f["kind"] for f in form["fields"]] == ["text", "choice", "choice", "text"]
    # The free-text Purpose and the DPA / DSA box's Purpose drop-down are two fields: each keeps its own answer.
    saved = access_requests.save(tmp_path, bdp, "", [
        {"label": "Purpose", "value": "Will be used for analytics in the MENA region", "kind": "text"},
        {"label": "Purpose", "section": "DPA / DSA", "value": "5", "kind": "choice"},
        {"label": "Subsidiary Name (Full Legal Name)", "section": "DPA / DSA", "value": "(ABC) Example Co.", "kind": "choice"},
        {"label": "Duration", "value": "6 months"}])
    assert [(access_requests.name(f), f["value"]) for f in saved["fields"]] == [
        ("Purpose", "Will be used for analytics in the MENA region"), ("DPA / DSA › Purpose", "5"),
        ("DPA / DSA › Subsidiary Name (Full Legal Name)", "(ABC) Example Co."), ("DPA / DSA › Subsidiary Address", ""),
        ("Duration", "6 months")]
    assert own(saved["fields"]) == [{"label": "Duration", "value": "6 months"}]
    with pytest.raises(AccessFormError, match="dpa / dsa › purpose' is there twice"):
        access_requests.save(tmp_path, bdp, "", [{"label": "Purpose", "section": "DPA / DSA", "value": "1"},
                                                 {"label": "purpose", "section": "dpa / dsa", "value": "2"}])
    with pytest.raises(AccessFormError, match="drop-down"):
        access_requests.save(tmp_path, bdp, "", [{"label": "Purpose", "value": "1", "kind": "radio"}])


def test_the_saved_answers_are_checked_and_kept_per_portal(tmp_path: Path):
    bdp = portal()
    saved = access_requests.save(tmp_path, bdp, "https://catalog.corp.example.com/request", [
        {"label": "  Purpose  ", "value": "Weekly sales reporting "}, {"label": "Manager", "value": "Head of Sales"},
        {"label": "", "value": "dropped"}])
    assert saved["page"] == "https://catalog.corp.example.com/request"
    assert saved["fields"][0]["value"] == "Weekly sales reporting", "an answer saved before the presets fills its preset"
    assert own(saved["fields"]) == [{"label": "Manager", "value": "Head of Sales"}]
    access_requests.remember_seen(tmp_path, "bdp", ["Purpose", "Duration"])
    access_requests.remember_seen(tmp_path, "bdp", ["Cost centre", "Purpose"])
    assert access_requests.form(tmp_path, bdp)["seen"] == ["Cost centre", "Purpose", "Duration"]
    assert access_requests.form(tmp_path, bdp)["fields"] == saved["fields"], "remembering labels keeps the answers"
    for bad in ([{"label": "Purpose", "value": "a"}, {"label": "PURPOSE", "value": "b"}], [{"label": "x" * 121, "value": ""}],
                [{"label": "Reason", "value": "x" * 2001}], "Purpose", [["Purpose", "a"]],
                [{"label": f"F{i}", "value": "v"} for i in range(41)]):
        with pytest.raises(AccessFormError):
            access_requests.save(tmp_path, bdp, "", bad)
    with pytest.raises(AccessFormError, match="not an address"):
        access_requests.save(tmp_path, bdp, "https://evil.example.net/request", [])


def test_a_request_window_opens_only_the_portals_own_addresses():
    bdp = portal()
    for address in ("https://catalog.corp.example.com/t/sales_daily", "https://superset.corp.example.com/x",
                    "https://itsm.corp.example.com/access/new"):
        assert access_requests.check_address(bdp, address) == address
    for address in ("https://gscm.other.example.org/", "https://evil.example.net/", "javascript:alert(1)",
                    "https://me:pw@catalog.corp.example.com/", "catalog.corp.example.com/x"):
        with pytest.raises(AccessFormError):
            access_requests.check_address(bdp, address)
    assert access_requests.on_portal(bdp, "catalog.corp.example.com") and not access_requests.on_portal(bdp, "gscm.other.example.org")


def test_what_the_window_fills_saved_answers_this_requests_own_and_the_tables():
    saved = [{"label": "Purpose", "value": "Weekly sales"}, {"label": "Manager", "value": "Head of Sales"},
             {"label": "Duration", "value": ""}]
    assert access_requests.answers(saved, [{"label": "purpose", "value": "GCC sell-out review"}], ["sales_daily", "stock"]) == [
        {"label": "purpose", "value": "GCC sell-out review"}, {"label": "Manager", "value": "Head of Sales"},
        {"label": "Table", "value": "sales_daily, stock", "auto": True}]
    named = access_requests.answers(saved, [{"label": "Table name", "value": "sales_daily"}], ["sales_daily"])
    assert [a["label"] for a in named] == ["Purpose", "Manager", "Table name"], "a table field Gemini named is not doubled"
    boxed = [{"label": "Purpose", "value": "Analytics", "kind": "text", "preset": True, "hint": "h"},
             {"label": "Purpose", "section": "DPA / DSA", "value": "5", "kind": "choice", "preset": True}]
    assert access_requests.answers(boxed, [{"label": "Purpose", "value": "GCC review"}], []) == [
        {"label": "Purpose", "value": "GCC review", "kind": "text"},
        {"label": "Purpose", "value": "5", "section": "DPA / DSA", "kind": "choice"}], \
        "this request's purpose replaces the free-text one, keeps its kind, and leaves the drop-down's"


def test_prepared_requests_wait_in_order_until_the_person_opens_them(tmp_path: Path):
    def request(n: int) -> dict[str, Any]:
        return {"id": f"AR-{n:010d}", "address": f"https://catalog.corp.example.com/t/{n}", "tables": [f"t{n}"], "answers": []}
    assert access_requests.enqueue(tmp_path, "bdp", request(1)) == {"position": 1, "waiting": 1}
    assert access_requests.enqueue(tmp_path, "bdp", request(2)) == {"position": 2, "waiting": 2}
    assert access_requests.enqueue(tmp_path, "bdp", request(1)) == {"position": 1, "waiting": 2}, "the same request once"
    access_requests.enqueue(tmp_path, "bdp", request(3))
    assert access_requests.next_waiting(tmp_path, "bdp")["id"] == "AR-0000000001"
    access_requests.mark_opened(tmp_path, "bdp", "AR-0000000001")
    assert access_requests.next_waiting(tmp_path, "bdp", after="AR-0000000001")["id"] == "AR-0000000002"
    assert access_requests.next_waiting(tmp_path, "bdp", after="AR-0000000003")["id"] == "AR-0000000002", "it wraps round"
    assert access_requests.place(tmp_path, "bdp", "AR-0000000002") == {"position": 2, "total": 3, "waiting": 1}, \
        "the others still to show"
    assert [i["opened"] is not None for i in access_requests.queue(tmp_path, "bdp")] == [True, False, False]
    assert [i["id"] for i in access_requests.remove(tmp_path, "bdp", ["AR-0000000003"], opened=True)] == ["AR-0000000002"]
    for n in range(4, 4 + access_requests.MAX_QUEUE - 1):
        access_requests.enqueue(tmp_path, "bdp", request(n))
    with pytest.raises(AccessFormError, match="waiting"):
        access_requests.enqueue(tmp_path, "bdp", request(999))
    access_requests.mark_opened(tmp_path, "bdp", "AR-0000000002")
    assert access_requests.enqueue(tmp_path, "bdp", request(999))["position"] == access_requests.MAX_QUEUE, \
        "an opened request makes room"
    assert "AR-0000000002" not in [i["id"] for i in access_requests.queue(tmp_path, "bdp")]
    assert access_requests.form(tmp_path, portal())["queue"][0]["id"] == "AR-0000000004"


def test_what_wizard_types_to_find_an_option_in_a_drop_downs_search():
    assert access_requests.search_texts("(ABC) Example Electronics Co., Ltd.") == [
        "(ABC) Example Electronics Co., Ltd.", "ABC", "Example"]
    assert access_requests.search_texts("abc") == ["abc"]
    assert access_requests.search_texts("5") == [] and access_requests.search_texts("  ") == [], "a number picks, never types"


def tool_setup(tmp_path: Path, systems: tuple[str, ...] = ("bdp",)) -> tuple[Any, ToolContext]:
    settings = settings_from(BDP)
    assert settings is not None
    services = build_services()
    services.portals = PortalBrowsers(settings, lambda user_id: tmp_path / user_id)
    identity = Identity(id="owner", email="owner@example.com", name="Owner", role="Owner",
                        entitlements={s: SystemRights(reports=["*"], markets=["*"]) for s in systems})
    return build_registry(services), ToolContext(identity=identity, run_id="run_t", recorder=MemoryRecorder(), services=services)


def test_gemini_proposes_a_request_and_never_sends_it(tmp_path: Path):
    registry, context = tool_setup(tmp_path, ("bdp", "gscm"))
    assert registry.specs["portal_request_access"].read_only and registry.specs["portal_request_access"].category == "present"
    # A table with only the catalog's start page would open the catalog, not the table's request form (owner, 1 Nov).
    for start in ({}, {"address": "https://catalog.corp.example.com/home/"}, {"address": "https://superset.corp.example.com/sqllab"}):
        refused = registry.execute("portal_request_access", {"system": "bdp", "tables": ["sales_daily"], **start}, context)
        assert not refused.ok and refused.error_code == "invalid_arguments" and "start page" in (refused.error_message or "")
        assert "open_steps" in (refused.error_message or "")
    assert access_requests.queue(tmp_path / "owner" / "portal-browser", "bdp") == [], "nothing prepared"
    outcome = registry.execute("portal_request_access", {"system": "bdp", "tables": ["sales_daily"],
                                                         "address": "https://catalog.corp.example.com/home#/table/sales_daily",
                                                         "answers": [{"label": "Reason", "value": "GCC sell-out review"}]}, context)
    assert outcome.ok, outcome.error_message
    request = outcome.data["access_request"]
    assert request["address"] == "https://catalog.corp.example.com/home#/table/sales_daily", "the table's own page"
    assert "open_steps" not in request and "form_button" not in request
    assert request["tables"] == ["sales_daily"] and request["answers"] == [{"label": "Reason", "value": "GCC sell-out review"}]
    assert request["saved"] == [] and "Settings → Portals" in outcome.data["note"] and "submit the request themselves" in outcome.data["note"]
    assert request["id"].startswith("AR-") and outcome.data["queued"] == {"position": 1, "waiting": 1}
    queued = access_requests.queue(tmp_path / "owner" / "portal-browser", "bdp")
    assert [(i["id"], i["tables"], i["opened"]) for i in queued] == [(request["id"], ["sales_daily"], None)], \
        "prepared, never opened by Gemini"
    access_requests.save(tmp_path / "owner" / "portal-browser", portal(), "https://catalog.corp.example.com/request",
                         [{"label": "Purpose", "value": "Weekly sales"}, {"label": "Manager", "value": ""}])
    again = registry.execute("portal_request_access", {"system": "bdp"}, context)
    assert again.ok and again.data["access_request"]["address"] == "https://catalog.corp.example.com/request"
    assert again.data["access_request"]["saved"] == ["Purpose"], "only answers that have a value are filled"
    away = registry.execute("portal_request_access", {"system": "bdp", "address": "https://evil.example.net/"}, context)
    assert not away.ok and away.error_code == "invalid_arguments"
    gscm = registry.execute("portal_request_access", {"system": "gscm"}, context)
    assert not gscm.ok and gscm.error_code == "invalid_arguments"
    guide = registry.execute("portal_guide", {"system": "bdp"}, context)
    assert guide.ok and guide.data["access_request_form"] == {
        "request_page": "https://catalog.corp.example.com/request", "saved_labels": ["Purpose"], "labels_seen_on_the_form": [],
        "form_pages_seen": [], "sending_on": False, "prepared_requests": {"total": 2, "not_opened": 2, "tables": ["sales_daily"],
                                                     "to_prepare_again": []}}
    assert "portal_request_access" in guide.data["guide"]


def test_a_catalog_that_keeps_one_address_is_reached_with_steps_gemini_proved(tmp_path: Path):
    registry, context = tool_setup(tmp_path)
    root = tmp_path / "owner" / "portal-browser"
    steps = [{"action": "fill", "selector": "input[type=search]", "value": "sales_daily"}, {"action": "press", "value": "Enter"},
             {"action": "click", "role": "link", "name": "sales_daily"}]
    outcome = registry.execute("portal_request_access", {"system": "bdp", "tables": ["sales_daily"],
                                                         "open_steps": steps, "form_button": "Request access"}, context)
    assert outcome.ok, outcome.error_message
    request = outcome.data["access_request"]
    assert request["address"] == "https://catalog.corp.example.com/home" and request["form_button"] == "Request access"
    assert [s["action"] for s in request["open_steps"]] == ["fill", "press", "click"]
    assert access_requests.queue(root, "bdp")[0]["open_steps"] == request["open_steps"], "the list keeps the way there"
    for bad, why in (({"open_steps": [{"action": "press", "value": "Tab"}]}, "only Enter"),
                     ({"open_steps": [{"action": "evaluate", "script": "x"}]}, "open_steps"),
                     ({"open_steps": [{"action": "click"}]}, "name the element"),
                     ({"open_steps": steps, "form_button": "Submit"}, "not a control that opens"),
                     ({"open_steps": steps, "form_button": "Save request"}, "not a control that opens")):
        refused = registry.execute("portal_request_access", {"system": "bdp", "tables": ["sales_daily"], **bad}, context)
        assert not refused.ok and refused.error_code == "invalid_arguments" and why in (refused.error_message or ""), (bad, refused)
    assert access_requests.clean_button(" Request  access ") == "Request access" and access_requests.clean_button("") == ""
    # Prepared again for the same table with a better route: it takes the earlier one's place, not a second row.
    first = registry.execute("portal_request_access", {"system": "bdp", "tables": ["stock_daily"],
                                                       "address": "https://catalog.corp.example.com/t/1"}, context)
    better = registry.execute("portal_request_access", {"system": "bdp", "tables": ["stock_daily"],
                                                        "address": "https://catalog.corp.example.com/t/stock_daily"}, context)
    listed = access_requests.queue(root, "bdp")
    assert [i["tables"] for i in listed] == [["sales_daily"], ["stock_daily"]]
    assert listed[1]["id"] == better.data["access_request"]["id"] != first.data["access_request"]["id"]
    assert listed[1]["address"].endswith("/t/stock_daily") and better.data["queued"]["position"] == 2
    access_requests.mark_opened(root, "bdp", listed[1]["id"])
    registry.execute("portal_request_access", {"system": "bdp", "tables": ["stock_daily"],
                                               "address": "https://catalog.corp.example.com/t/stock_daily?v=2"}, context)
    assert len(access_requests.queue(root, "bdp")) == 3, "an opened request stays as it was; the new one is added"
    # A request prepared before the way to the table was required opens only the start page: the guide says so.
    access_requests.enqueue(root, "bdp", {"id": "AR-00000000aa", "address": "https://catalog.corp.example.com/home",
                                          "tables": ["old_table"], "answers": []})
    guide = registry.execute("portal_guide", {"system": "bdp"}, context)
    assert guide.data["access_request_form"]["prepared_requests"]["to_prepare_again"] == ["old_table"]
    access_requests.remember_page(root, "bdp", ["sales_daily"], "https://catalog.corp.example.com/home#/req/9")
    assert access_requests.pages_seen(root, "bdp")[0]["url"].endswith("#/req/9")


def test_the_api_keeps_the_form_and_opens_the_request_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from wizard_api.app import create_app
    opened: list[tuple[str, str, list[dict[str, str]]]] = []
    queued: list[str | None] = []

    routes: list[dict[str, Any] | None] = []

    def fake_open(self: PortalBrowser, portal: Any, address: str, answers: list[dict[str, str]],
                  queued_: str | None = None, route: dict[str, Any] | None = None) -> dict[str, Any]:
        opened.append((portal.id, address, answers))
        queued.append(queued_)
        routes.append(route)
        return {"signing_in": True, "window": "access_request"}

    monkeypatch.setattr(PortalBrowser, "open_access_request", fake_open)
    settings = make_settings(tmp_path, **BDP, WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    with TestClient(create_app(settings)) as client:
        login(client, "local-owner")
        status = client.get("/api/v1/portals").json()
        assert [p.get("access_requests") for p in status["portals"]] == [None, True], "GSCM takes no requests; BDP does"
        assert [f["value"] for f in client.get("/api/v1/portals/bdp/access-form").json()["fields"]] == ["", "", "", ""]
        assert client.get("/api/v1/portals/gscm/access-form").status_code == 404
        form = {"page": "", "fields": [{"label": "Purpose", "value": "Weekly sales"}, {"label": "Duration", "value": "6 months"}]}
        assert client.post("/api/v1/portals/bdp/access-form", json=form).status_code == 403, "state changes need the Wizard header"
        saved = client.post("/api/v1/portals/bdp/access-form", json=form, headers=HEADERS)
        assert saved.status_code == 200 and saved.json()["fields"][0]["value"] == "Weekly sales"
        assert own(saved.json()["fields"]) == [{"label": "Duration", "value": "6 months"}]
        bad = client.post("/api/v1/portals/bdp/access-form", json={"page": "https://evil.example.net/", "fields": []}, headers=HEADERS)
        assert bad.status_code == 400 and "not an address" in bad.json()["error"]
        assert client.post("/api/v1/portals/bdp/access-request", json={}, headers=HEADERS).json()["window"] == "access_request"
        client.post("/api/v1/portals/bdp/access-request", headers=HEADERS, json={
            "address": "https://catalog.corp.example.com/t/sales_daily", "tables": ["sales_daily"],
            "answers": [{"label": "Duration", "value": "3 months"}, {"label": "Reason", "value": "GCC review"}]})
        assert opened[0] == ("bdp", "https://catalog.corp.example.com/home", [
            {"label": "Purpose", "value": "Weekly sales", "kind": "text"}, {"label": "Duration", "value": "6 months"}])
        assert opened[1] == ("bdp", "https://catalog.corp.example.com/t/sales_daily", [
            {"label": "Purpose", "value": "Weekly sales", "kind": "text"}, {"label": "Duration", "value": "3 months"},
            {"label": "Reason", "value": "GCC review"}, {"label": "Table", "value": "sales_daily", "auto": True}])
        assert queued == [None, None], "neither is a prepared request"
        away = client.post("/api/v1/portals/bdp/access-request", json={"address": "https://evil.example.net/"}, headers=HEADERS)
        assert away.status_code == 400 and len(opened) == 2

        # Prepared requests: the next one, a named one, and a card's request found in the list.
        root = settings.user_home("local-owner") / "portal-browser"
        for n in (1, 2):
            access_requests.enqueue(root, "bdp", {"id": f"AR-{n:010d}", "address": f"https://catalog.corp.example.com/t/t{n}",
                                                  "tables": [f"t{n}"], "answers": [{"label": "Reason", "value": f"r{n}"}]})
        assert client.post("/api/v1/portals/bdp/access-request", json={"queued": "next"}, headers=HEADERS).status_code == 200
        assert opened[-1][1] == "https://catalog.corp.example.com/t/t1" and queued[-1] == "AR-0000000001"
        assert {"label": "Reason", "value": "r1"} in opened[-1][2] and {"label": "Table", "value": "t1", "auto": True} in opened[-1][2]
        assert client.post("/api/v1/portals/bdp/access-request", json={"queued": "next"}, headers=HEADERS).status_code == 200
        assert queued[-1] == "AR-0000000002"
        assert client.post("/api/v1/portals/bdp/access-request", json={"queued": "next"}, headers=HEADERS).status_code == 404
        assert client.post("/api/v1/portals/bdp/access-request", json={"queued": "AR-0000000001"}, headers=HEADERS).status_code == 200
        assert client.post("/api/v1/portals/bdp/access-request", json={"queued": "AR-ffffffffff"}, headers=HEADERS).status_code == 404
        # A card whose request left the list opens with its own fields, its way to the table included.
        gone = {"queued": "AR-ffffffffff", "address": "https://catalog.corp.example.com/home", "tables": ["t7"],
                "open_steps": [{"action": "fill", "selector": "#q", "value": "t7"}, {"action": "press", "value": "Enter"}],
                "form_button": "Request access"}
        assert client.post("/api/v1/portals/bdp/access-request", json=gone, headers=HEADERS).status_code == 200
        assert queued[-1] is None and routes[-1] == {"tables": ["t7"], "open_steps": gone["open_steps"], "form_button": "Request access"}
        bad = {**gone, "open_steps": [{"action": "evaluate", "script": "1"}]}
        assert client.post("/api/v1/portals/bdp/access-request", json=bad, headers=HEADERS).status_code == 400
        assert client.post("/api/v1/portals/bdp/access-request", json={"queued": "../x"}, headers=HEADERS).status_code == 400
        card = {"address": "https://catalog.corp.example.com/t/t9", "tables": ["t9"], "answers": []}
        access_requests.enqueue(root, "bdp", {"id": access_requests.request_id("bdp", card["address"], ["t9"], []), **card})
        client.post("/api/v1/portals/bdp/access-request", json=card, headers=HEADERS)
        assert queued[-1] == access_requests.request_id("bdp", card["address"], ["t9"], []), "the card's request is in the list"
        listed = client.get("/api/v1/portals/bdp/access-form").json()["queue"]
        assert all(i["opened"] for i in listed), "each open is noted"
        left = client.post("/api/v1/portals/bdp/access-queue/remove", json={"ids": ["AR-0000000001"]}, headers=HEADERS)
        assert [i["id"] for i in left.json()["queue"]] == ["AR-0000000002", listed[-1]["id"]]
        assert client.post("/api/v1/portals/bdp/access-queue/remove", json={"opened": True}, headers=HEADERS).json()["queue"] == []
        actions = [e["action"] for e in client.app.state.store.audit_entries()]
        assert {"portals:access_request", "portals:access_form", "portals:access_queue"} <= set(actions)


def test_a_reopened_answer_keeps_its_access_request(tmp_path: Path):
    from fastapi.testclient import TestClient

    from wizard_api.app import create_app
    settings = make_settings(tmp_path, **BDP, WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    with TestClient(create_app(settings)) as client:
        login(client, "local-owner")
        store = client.app.state.store
        conversation = store.create_conversation("local-owner")
        run_id = client.post("/api/v1/runs", json={"question": "Weekly sell-out from BDP", "conversation_id": conversation},
                             headers=HEADERS).json()["run_id"]
        request = {"id": "AR-1", "system": "bdp", "portal": "Big Data Portal", "address": "https://catalog.corp.example.com/t",
                   "tables": ["sales_daily"], "answers": [], "saved": []}
        store.add_event(run_id, 9999, "access_request_proposed", {"request": request})
        events = client.get(f"/api/v1/runs/{run_id}").json()["events"]
        assert {"type": "access_request_proposed", "payload": {"request": request}}.items() <= \
            next(e for e in events if e["type"] == "access_request_proposed").items()


def test_the_stage_and_activity_name_the_request(tmp_path: Path):
    from wizard_api.runs import tool_label, tool_summary
    from wizard_connectors.tools.registry import ToolOutcome
    registry, context = tool_setup(tmp_path)
    assert tool_label("portal_request_access", {"system": "bdp", "tables": ["sales_daily"]}, context.services) == \
        "Prepared an access request in Big Data Portal: sales_daily"
    assert "submit" in tool_summary("portal_request_access", ToolOutcome(True, {"access_request": {}}, 1))


def test_sending_is_turned_on_only_from_a_request_the_person_submitted_and_sends_only_what_they_approve(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from wizard_api.app import create_app
    # The submission the window saw: its pattern takes the ids out, its answer keeps the success fields.
    pattern = access_requests.path_pattern("https://catalog.corp.example.com/dis-api/requests/123?x=1")
    assert pattern == {"host": "catalog.corp.example.com", "path": "/dis-api/requests/*"}
    assert access_requests.path_matches(pattern, "https://catalog.corp.example.com/dis-api/requests/9")
    assert not access_requests.path_matches(pattern, "https://catalog.corp.example.com/dis-api/delete/9")
    assert not access_requests.path_matches(pattern, "https://other.corp.example.com/dis-api/requests/9")
    assert access_requests.expect_fields('{"success": true, "code": "0000", "data": {"id": 5}, "message": "ok"}') == \
        {"success": True, "code": "0000"}
    assert access_requests.expect_fields("<html>") == {}

    sent: list[list[str]] = []

    def fake_send(self: PortalBrowser, portal_: Any, ids: list[str]) -> dict[str, Any]:
        sent.append(ids)
        return {"signing_in": True, "window": "access_request"}

    monkeypatch.setattr(PortalBrowser, "send_requests", fake_send)
    settings = make_settings(tmp_path, **BDP, WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    with TestClient(create_app(settings)) as client:
        login(client, "local-owner")
        root = settings.user_home("local-owner") / "portal-browser"
        for n in (1, 2, 3):
            access_requests.enqueue(root, "bdp", {"id": f"AR-{n:010d}", "address": f"https://catalog.corp.example.com/t/{n}",
                                                  "tables": [f"t{n}"], "answers": []})
        off = client.post("/api/v1/portals/bdp/access-send", json={"waiting": True}, headers=HEADERS)
        assert off.status_code == 409 and "Submit one request yourself" in off.json()["error"] and sent == []
        refused = client.post("/api/v1/portals/bdp/access-sending", json={"enabled": True}, headers=HEADERS)
        assert refused.status_code == 400, "no submission of the person's own yet"
        access_requests.remember_submission(root, "bdp", {"tables": ["t1"], "button": "Submit", "method": "POST",
                                                          "match": pattern, "path": "/dis-api/requests/123", "status": 500})
        assert client.post("/api/v1/portals/bdp/access-sending", json={"enabled": True}, headers=HEADERS).status_code == 400, \
            "a submission the portal refused proves nothing"
        access_requests.remember_submission(root, "bdp", {"tables": ["t1"], "button": "Submit", "method": "POST",
                                                          "match": pattern, "path": "/dis-api/requests/123", "status": 200,
                                                          "expect": {"success": True}, "request_id": "AR-0000000001"})
        access_requests.mark_sent(root, "bdp", "AR-0000000001", "you", 200, "/dis-api/requests/123")
        on = client.post("/api/v1/portals/bdp/access-sending", json={"enabled": True}, headers=HEADERS).json()
        assert on["sending"]["enabled"] and on["sending"]["proof"]["button"] == "Submit" and on["sending"]["proof"]["proved_at"]
        assert on["queue"][0]["sent"]["by"] == "you"
        assert client.post("/api/v1/portals/bdp/access-send", json={"waiting": True}, headers=HEADERS).status_code == 200
        assert sent[-1] == ["AR-0000000002", "AR-0000000003"], "every approved request not sent yet, in order"
        assert client.post("/api/v1/portals/bdp/access-send", json={"ids": ["AR-0000000003"]}, headers=HEADERS).status_code == 200
        assert sent[-1] == ["AR-0000000003"]
        none = client.post("/api/v1/portals/bdp/access-send", json={"ids": ["AR-0000000001"]}, headers=HEADERS)
        assert none.status_code == 404, "a request already sent is not sent again"
        assert client.post("/api/v1/portals/bdp/access-send", json={"waiting": True}).status_code == 403, "needs the Wizard header"
        off_again = client.post("/api/v1/portals/bdp/access-sending", json={"enabled": False}, headers=HEADERS).json()
        assert not off_again["sending"]["enabled"] and off_again["sending"]["last_submission"]["status"] == 200
        assert client.post("/api/v1/portals/bdp/access-send", json={"waiting": True}, headers=HEADERS).status_code == 409
        actions = [e["action"] for e in client.app.state.store.audit_entries()]
        assert actions.count("portals:access_sending") == 2 and actions.count("portals:access_send") == 2


def test_gemini_offers_send_only_when_the_person_turned_sending_on(tmp_path: Path):
    registry, context = tool_setup(tmp_path)
    root = tmp_path / "owner" / "portal-browser"
    args = {"system": "bdp", "tables": ["t1"], "address": "https://catalog.corp.example.com/t/t1"}
    first = registry.execute("portal_request_access", args, context)
    assert first.ok and first.data["access_request"]["can_send"] is False and "Open the request form" in first.data["note"]
    access_requests.remember_submission(root, "bdp", {"button": "Submit", "method": "POST", "status": 200,
                                                      "match": {"host": "catalog.corp.example.com", "path": "/r"}})
    access_requests.set_sending(root, "bdp", True)
    second = registry.execute("portal_request_access", {**args, "tables": ["t2"]}, context)
    assert second.data["access_request"]["can_send"] is True and "Send request" in second.data["note"]
    assert "Nothing is sent without that click" in second.data["note"]
    assert registry.execute("portal_guide", {"system": "bdp"}, context).data["access_request_form"]["sending_on"] is True
    assert not any("send" in name for name in registry.specs if name.startswith("portal_")), "Gemini has no send tool"
