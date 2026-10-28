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


def test_the_saved_answers_are_checked_and_kept_per_portal(tmp_path: Path):
    bdp = portal()
    assert access_requests.form(tmp_path, bdp) == {"system": "bdp", "page": "", "fields": [], "seen": [],
                                                    "default_page": "https://catalog.corp.example.com/home"}
    saved = access_requests.save(tmp_path, bdp, "https://catalog.corp.example.com/request", [
        {"label": "  Purpose  ", "value": "Weekly sales reporting "}, {"label": "Manager", "value": "Head of Sales"},
        {"label": "", "value": "dropped"}])
    assert saved["page"] == "https://catalog.corp.example.com/request"
    assert saved["fields"] == [{"label": "Purpose", "value": "Weekly sales reporting"}, {"label": "Manager", "value": "Head of Sales"}]
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
        {"label": "Table", "value": "sales_daily, stock"}]
    named = access_requests.answers(saved, [{"label": "Table name", "value": "sales_daily"}], ["sales_daily"])
    assert [a["label"] for a in named] == ["Purpose", "Manager", "Table name"], "a table field Gemini named is not doubled"


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
    outcome = registry.execute("portal_request_access", {"system": "bdp", "tables": ["sales_daily"],
                                                         "answers": [{"label": "Reason", "value": "GCC sell-out review"}]}, context)
    assert outcome.ok, outcome.error_message
    request = outcome.data["access_request"]
    assert request["address"] == "https://catalog.corp.example.com/home", "the catalog when nothing names a page"
    assert request["tables"] == ["sales_daily"] and request["answers"] == [{"label": "Reason", "value": "GCC sell-out review"}]
    assert request["saved"] == [] and "Settings → Portals" in outcome.data["note"] and "never submits" in outcome.data["note"]
    assert request["id"].startswith("AR-")
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
        "request_page": "https://catalog.corp.example.com/request", "saved_labels": ["Purpose"], "labels_seen_on_the_form": []}
    assert "portal_request_access" in guide.data["guide"]


def test_the_api_keeps_the_form_and_opens_the_request_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from wizard_api.app import create_app
    opened: list[tuple[str, str, list[dict[str, str]]]] = []

    def fake_open(self: PortalBrowser, portal: Any, address: str, answers: list[dict[str, str]]) -> dict[str, Any]:
        opened.append((portal.id, address, answers))
        return {"signing_in": True, "window": "access_request"}

    monkeypatch.setattr(PortalBrowser, "open_access_request", fake_open)
    settings = make_settings(tmp_path, **BDP, WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    with TestClient(create_app(settings)) as client:
        login(client, "local-owner")
        status = client.get("/api/v1/portals").json()
        assert [p.get("access_requests") for p in status["portals"]] == [None, True], "GSCM takes no requests; BDP does"
        assert client.get("/api/v1/portals/bdp/access-form").json()["fields"] == []
        assert client.get("/api/v1/portals/gscm/access-form").status_code == 404
        form = {"page": "", "fields": [{"label": "Purpose", "value": "Weekly sales"}, {"label": "Duration", "value": "6 months"}]}
        assert client.post("/api/v1/portals/bdp/access-form", json=form).status_code == 403, "state changes need the Wizard header"
        saved = client.post("/api/v1/portals/bdp/access-form", json=form, headers=HEADERS)
        assert saved.status_code == 200 and saved.json()["fields"] == form["fields"]
        bad = client.post("/api/v1/portals/bdp/access-form", json={"page": "https://evil.example.net/", "fields": []}, headers=HEADERS)
        assert bad.status_code == 400 and "not an address" in bad.json()["error"]
        assert client.post("/api/v1/portals/bdp/access-request", json={}, headers=HEADERS).json()["window"] == "access_request"
        client.post("/api/v1/portals/bdp/access-request", headers=HEADERS, json={
            "address": "https://catalog.corp.example.com/t/sales_daily", "tables": ["sales_daily"],
            "answers": [{"label": "Duration", "value": "3 months"}, {"label": "Reason", "value": "GCC review"}]})
        assert opened[0] == ("bdp", "https://catalog.corp.example.com/home", form["fields"])
        assert opened[1] == ("bdp", "https://catalog.corp.example.com/t/sales_daily", [
            {"label": "Purpose", "value": "Weekly sales"}, {"label": "Duration", "value": "3 months"},
            {"label": "Reason", "value": "GCC review"}, {"label": "Table", "value": "sales_daily"}])
        away = client.post("/api/v1/portals/bdp/access-request", json={"address": "https://evil.example.net/"}, headers=HEADERS)
        assert away.status_code == 400 and len(opened) == 2
        actions = [e["action"] for e in client.app.state.store.audit_entries()]
        assert "portals:access_request" in actions and "portals:access_form" in actions


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
