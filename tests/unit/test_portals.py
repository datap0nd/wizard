"""The rules that keep Gemini's portal scripts read-only, without a browser: settings, reachable hosts, write detection
(paths, service names, methods, SQL Lab), Metronome's forbidden clicks, redaction, and tables from script results."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.helpers import HEADERS, login, make_settings

from wizard_connectors import portals
from wizard_connectors.portals import (
    HostPolicy,
    PortalConfigError,
    click_refusal,
    settings_from,
    sql_problem,
    write_reason,
)


def test_portals_come_from_their_addresses_and_nothing_else():
    assert settings_from({}) is None
    configured = settings_from({"WIZARD_PORTAL_GSCM_URL": "https://gscm.corp.example.com/gscm30/",
                                "WIZARD_PORTAL_ASAP_URL": "https://asap.corp.example.com/", "WIZARD_BROWSER": "msedge",
                                "WIZARD_PORTAL_HOSTS": "login.microsoftonline.com, *.sso.example.net"})
    assert configured is not None
    assert [p.id for p in configured.portals] == ["asap", "gscm"] and configured.channel == "msedge"
    assert configured.portal("gscm").host == "gscm.corp.example.com"
    assert configured.portal("gscm").origin == "https://gscm.corp.example.com"
    assert configured.extra_hosts == ("login.microsoftonline.com", "*.sso.example.net")
    for bad in ({"WIZARD_PORTAL_ASAP_URL": "asap.corp"}, {"WIZARD_PORTAL_ASAP_URL": "ftp://asap.corp/"},
                {"WIZARD_PORTAL_ASAP_URL": "https://me:pw@asap.corp/"},
                {"WIZARD_PORTAL_ASAP_URL": "https://asap.corp/", "WIZARD_BROWSER": "firefox"},
                {"WIZARD_PORTAL_ASAP_URL": "https://asap.corp/", "WIZARD_PORTAL_HOSTS": "*.com"},
                {"WIZARD_PORTAL_ASAP_URL": "https://asap.corp/", "WIZARD_PORTAL_HOSTS": "evil host"}):
        with pytest.raises(PortalConfigError):
            settings_from(bad)


def test_the_big_data_portal_is_its_information_catalog_and_superset():
    both = settings_from({"WIZARD_PORTAL_BDP_URL": "https://superset.example.com/sqllab/",
                          "WIZARD_PORTAL_BDP_CATALOG_URL": "https://catalog.example.net/search"})
    assert both is not None
    bdp = both.portal("bdp")
    assert bdp is not None and bdp.url == "https://superset.example.com/sqllab/", "steps start in Superset"
    assert [(p.id, p.label) for p in bdp.parts] == [("superset", "Superset"), ("catalog", "information catalog")]
    assert bdp.pages == [("bdp-superset", "Big Data Portal: Superset", "https://superset.example.com/sqllab/"),
                         ("bdp-catalog", "Big Data Portal: information catalog", "https://catalog.example.net/search")]
    assert bdp.hosts == ("superset.example.com", "catalog.example.net")
    policy = HostPolicy(both)
    assert policy.allowed("catalog.example.net") and policy.allowed("superset.example.com")
    assert not policy.allowed("other.example.net")
    assert policy.portal_for("catalog.example.net") is bdp and policy.portal_domain("catalog.example.net")
    only_catalog = settings_from({"WIZARD_PORTAL_BDP_CATALOG_URL": "https://catalog.example.net/"})
    assert only_catalog is not None and only_catalog.portal("bdp").url == "https://catalog.example.net/"
    gscm = settings_from({"WIZARD_PORTAL_GSCM_URL": "https://gscm.corp.example.com/"}).portal("gscm")
    assert gscm.parts == () and gscm.pages == [("gscm", "GSCM", "https://gscm.corp.example.com/")]
    with pytest.raises(PortalConfigError, match="WIZARD_PORTAL_BDP_CATALOG_URL"):
        settings_from({"WIZARD_PORTAL_BDP_URL": "https://superset.example.com/", "WIZARD_PORTAL_BDP_CATALOG_URL": "catalog"})


def test_a_path_stays_on_the_portal_application_the_page_is_on():
    from wizard_connectors.portal_browser import _address
    bdp = settings_from({"WIZARD_PORTAL_BDP_URL": "https://superset.example.com/",
                         "WIZARD_PORTAL_BDP_CATALOG_URL": "https://catalog.example.net/"}).portal("bdp")
    assert _address(bdp, "/search?q=sales", "https://catalog.example.net/home") == "https://catalog.example.net/search?q=sales"
    assert _address(bdp, "sqllab/", "https://superset.example.com/x") == "https://superset.example.com/sqllab/"
    assert _address(bdp, "/sqllab/", "about:blank") == "https://superset.example.com/sqllab/"
    assert _address(bdp, "/x", "https://gscm.corp.example.com/") == "https://superset.example.com/x", "another portal's page"
    assert _address(bdp, "https://catalog.example.net/t/1", "") == "https://catalog.example.net/t/1"


def test_only_the_portals_their_company_domain_and_sign_in_hosts_are_reachable():
    configured = settings_from({"WIZARD_PORTAL_GSCM_URL": "https://gscm.corp.example.com/",
                                "WIZARD_PORTAL_BDP_URL": "https://bdp.example.com/", "WIZARD_PORTAL_HOSTS": "*.idp.example.org"})
    assert configured is not None
    policy = HostPolicy(configured, {"sso.partner.example.net"})
    for host in ("gscm.corp.example.com", "static.corp.example.com", "corp.example.com", "bdp.example.com",
                 "a.idp.example.org", "sso.partner.example.net", "GSCM.CORP.EXAMPLE.COM"):
        assert policy.allowed(host), host
    # bdp.example.com has no company domain of its own: example.com is not widened to every host under it.
    for host in ("example.com", "other.example.com", "evil.com", "corp.example.com.evil.com", "idp.example.org", None, ""):
        assert not policy.allowed(host), host
    assert portals.company_domain("10.1.2.3") is None


@pytest.mark.parametrize(("method", "url", "body"), [
    ("GET", "https://p.corp.example.com/gscm30/common/master/tree.do", None),
    ("POST", "https://p.corp.example.com/mstr/menuInfo.do?folderId=A1", "authToken=x&depth=2"),
    ("POST", "https://p.corp.example.com/svc/selectWeeklyList.do", "SSV:utf-8\x1eDataset:ds_in\x1e"),
    ("POST", "https://p.corp.example.com/mstr/taskProc?taskId=reportExecute", None),
    ("PUT", "https://p.corp.example.com/MicroStrategyLibrary/api/reports/R1/instances/I1/prompts/answers", "{}"),
    ("GET", "https://p.corp.example.com/getUpdatedList.do", None),
    ("GET", "https://p.corp.example.com/addressBook/list", None),
    ("POST", "https://bdp.example.com/api/v1/sqllab/execute/", json.dumps({"sql": "SELECT REPLACE(name, 'a', 'b'), comment FROM t"})),
    # The information catalog: searching, reading a table and listing one's own access requests are reads.
    ("POST", "https://catalog.example.com/api/search", json.dumps({"query": "mutation testing tables", "page": 1})),
    ("POST", "https://catalog.example.com/api/graphql", json.dumps({"query": "query { search(input: {query: \"sales\"}) { total } }"})),
    ("GET", "https://catalog.example.com/api/v1/access-requests?status=pending", None),
    ("GET", "https://catalog.example.com/tables/sales_daily/requests", None),
    ("POST", "https://p.corp.example.com/svc/selectAccessRequestList.do", "SSV:utf-8\x1e"),
])
def test_reads_go_through(method, url, body):
    assert write_reason(method, url, body) is None


@pytest.mark.parametrize(("method", "url", "body", "word"), [
    ("POST", "https://p.corp.example.com/svc/saveBookmark.do", "x", "save"),
    ("POST", "https://p.corp.example.com/svc/deleteUserReport.do", None, "delete"),
    ("GET", "https://p.corp.example.com/mstr/logout.do", None, "logout"),
    ("POST", "https://p.corp.example.com/svc/update_plan", None, "update"),
    ("POST", "https://p.corp.example.com/mstr/taskProc?taskId=saveReport", None, "save"),
    ("POST", "https://p.corp.example.com/mstr/taskProc", "taskId=deleteObject&x=1", "delete"),
    ("POST", "https://p.corp.example.com/nexacro/run.do", '<Root><Parameters><Parameter id="svcid">insertPlan</Parameter>'
                                                          '</Parameters></Root>', "insert"),
    ("PUT", "https://p.corp.example.com/api/v1/chart/3", "{}", "PUT"),
    ("DELETE", "https://p.corp.example.com/api/v1/chart/3", None, "DELETE"),
    ("PATCH", "https://p.corp.example.com/api/thing", "{}", "PATCH"),
    # Access to a table is requested by the person, never by Wizard: in the information catalog or in Superset.
    ("POST", "https://catalog.example.com/api/requestAccess", json.dumps({"table": "t"}), "request"),
    ("GET", "https://superset.example.com/superset/request_access/?datasource_id=3", None, "request"),
    ("POST", "https://catalog.example.com/api/v1/access-requests", json.dumps({"table": "t"}), "requests access"),
    ("POST", "https://catalog.example.com/api/tables/t/permissionRequest", "{}", "requests access"),
    ("POST", "https://catalog.example.com/svc/tableAccessRequest.do", "id=t", "requests access"),
    ("POST", "https://catalog.example.com/api/graphql", json.dumps({"query": "mutation { createAccessRequest(urn: \"t\") }"}),
     "mutation"),
    ("POST", "https://catalog.example.com/api/graphql", json.dumps([{"query": "# ask\n  mutation Ask { x }"}]), "mutation"),
])
def test_writes_are_refused(method, url, body, word):
    reason = write_reason(method, url, body)
    assert reason and word in reason


@pytest.mark.parametrize("sql", [
    "DELETE FROM t", "SELECT 1; DROP TABLE t", "WITH gone AS (DELETE FROM t RETURNING *) SELECT * FROM gone",
    "SELECT * INTO copy FROM t", "EXPLAIN ANALYZE DELETE FROM t", "INSERT OVERWRITE TABLE t SELECT 1", "", "SET x = 1",
])
def test_sql_lab_runs_one_select_only(sql):
    assert sql_problem(json.dumps({"sql": sql}))
    assert write_reason("POST", "https://bdp.example.com/api/v1/sqllab/execute/", json.dumps({"sql": sql}))


def test_sql_lab_reads_pass():
    for sql in ("SELECT 1", "with x as (select 1) select * from x;", "-- note; with semicolon\nSELECT ';' AS s",
                "SHOW TABLES", "SELECT updated_at, delete_flag FROM t"):
        assert sql_problem(json.dumps({"sql": sql})) is None, sql
    assert sql_problem("not json")


def test_metronomes_forbidden_controls_are_never_clicked():
    for control in ({"text": "Save"}, {"text": "  Delete row "}, {"id": "mainframe.VFrameSet.TopFrame.Setting0.form.btn_save:icontext"},
                    {"aria": "Unselect all"}, {"title": "Pin to home"}, {"text": "Sign out"}, {"value": "Submit"},
                    {"text": "Log Out"}, {"name": "btnApply"}, {"id": "div_favorite.form.btn_unpin"},
                    {"text": "Request access"}, {"aria": "Request"}, {"id": "btnRequestAccess"}):
        assert click_refusal(control), control
    for control in ({"text": "Go >>"}, {"text": "RUN"}, {"text": "Shipping"}, {"text": "Address"}, {"text": "Renewal"},
                    {"id": "mainframe.VFrameSet.WorkFrame0.form.div_addInfo.form.btn_search"}, {"text": "Favorite"},
                    {"text": "Export Wizard (Detail)"}, {"text": "My requests"}, {"text": "Requested on"}):
        assert click_refusal(control) is None, control


def test_secrets_never_reach_gemini():
    url = portals.redact_url("https://p.example.com/x?authToken=abc&week=2026W40&SESSIONID=1")
    assert "abc" not in url and "week=2026W40" in url
    assert "s3cret" not in portals.redact_text("authToken=s3cret&depth=1")
    xml = '<Parameter id="authToken">s3cret</Parameter><Parameter id="week">2026W40</Parameter>'
    assert "s3cret" not in portals.redact_text(xml) and "2026W40" in portals.redact_text(xml)
    body = json.dumps({"csrf_token": "s3cret", "rows": [{"a": 1}]})
    assert "s3cret" not in portals.redact_text(body) and '"a": 1' in portals.redact_text(body)
    token = "A" * 30 + "b" * 30
    assert token not in portals.redact_text(f"value {token} end")
    ssv = "SSV:utf-8\x1eErrorCode:int=0\x1fErrorMsg:string=OK\x1e"
    assert portals.redact_text(ssv) == ssv
    assert portals.redact_json({"x": {"MSTRWEB_AUTH_TOKEN_ENC": "t", "Password": "p", "n": 1}}) == \
        {"x": {"MSTRWEB_AUTH_TOKEN_ENC": "<redacted>", "Password": "<redacted>", "n": 1}}


def test_tables_and_errors_lose_their_secrets():
    token = "Z" * 50
    assert portals.redact_rows(["market", "sessionId", "note"], [["AE", "abc", f"x {token}"], ["SA", None, "short"]]) == \
        [["AE", "<redacted>", "x ZZZZZZ…<redacted>"], ["SA", None, "short"]]
    assert token not in portals.scrub(f"Error: bad {token}")
    # Names a script needs stay whole: Nexacro component paths and long routes are not secrets.
    for name in ("mainframe.VFrameSet.MdiFrame.form.div_frameButton.form.btn_exceldown",
                 "/gscm/scm/sales/weekly/selectWeeklySellOutList.do", "https://gscm.corp.example.com/gscm/scm/selectPlanVersionList.do"):
        assert portals.scrub(f"open {name} now") == f"open {name} now", name
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvd25lckBleGFtcGxlLmNvbSJ9.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
    for secret in (jwt, "3F2A9C8B7D6E5F4A3B2C1D0E9F8A7B6C5D4E3F2A.worker1", "/" + "Ab+cD" * 10, "QWxhZGRpbjpvcGVuIHNlc2FtZQ/" * 3):
        assert secret not in portals.scrub(f"x {secret} y"), secret
    configured = settings_from({"WIZARD_PORTAL_GSCM_URL": "https://gscm.corp.example.com/"})
    assert configured is not None
    policy = HostPolicy(configured, {"login.idp.example.org", "gscm.corp.example.com"})
    assert policy.portal_domain("app.corp.example.com") and not policy.portal_domain("login.idp.example.org")


def test_a_script_result_is_a_table_only_when_it_says_so():
    assert portals.table_from({"columns": ["m", "u"], "rows": [["AE", 1], ["SA"]], "total_rows": 9}) == \
        (["m", "u"], [["AE", 1], ["SA", None]], 9)
    assert portals.table_from([{"m": "AE", "u": 1}, {"m": "SA", "x": 2}]) == (["m", "u", "x"], [["AE", 1, None], ["SA", None, 2]], 2)
    assert portals.table_from({"columns": [{"key": "m"}], "rows": [{"m": "AE"}]}) == (["m"], [["AE"]], 1)
    for value in (None, 3, "text", [], [1, 2], {"rows": []}, {"columns": ["a"], "rows": [1]}):
        assert portals.table_from(value) is None
    assert portals.column_types(["m", "u"], [["AE", 1], ["SA", 2.5]]) == [
        {"key": "m", "label": "m", "type": "string"}, {"key": "u", "label": "u", "type": "number"}]


def test_portals_are_a_single_person_pc_feature(tmp_path: Path):
    from wizard_api.config import ConfigError
    with pytest.raises(ConfigError, match="desktop app or a work-PC install"):
        make_settings(tmp_path, WIZARD_PORTAL_GSCM_URL="https://gscm.corp.example.com/", WIZARD_AUTH_MODE="trusted-header",
                      WIZARD_PUBLIC_ORIGIN="https://wizard.example.com")
    with pytest.raises(ConfigError, match="WIZARD_BROWSER"):
        make_settings(tmp_path, WIZARD_PORTAL_GSCM_URL="https://gscm.corp.example.com/", WIZARD_BROWSER="safari")


def test_a_company_file_cannot_choose_the_browser_binary():
    from wizard_api import provisioning
    assert "WIZARD_BROWSER_EXECUTABLE" in provisioning.LOCAL_ONLY


def test_configured_portals_are_on_the_stage_with_their_tools_and_sign_in(tmp_path: Path):
    from fastapi.testclient import TestClient

    from wizard_api.app import create_app
    settings = make_settings(tmp_path, WIZARD_PORTAL_GSCM_URL="https://gscm.corp.example.com/start",
                             WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    with TestClient(create_app(settings)) as client:
        assert {"portal_guide", "portal_run", "portal_save_script"} <= set(client.app.state.registry.specs)
        assert client.app.state.registry.specs["portal_run"].scope == "portal"
        login(client, "local-owner")
        systems = client.get("/api/v1/bootstrap").json()["systems"]
        assert {"id": "gscm", "name": "GSCM", "kind": "portal", "data_mode": "LIVE"} in systems
        status = client.get("/api/v1/portals").json()
        assert status["portals"] == [{"id": "gscm", "name": "GSCM", "host": "gscm.corp.example.com"}]
        assert status["browser"] == "Google Chrome" and status["signing_in"] is False and status["running"] is False
        assert client.post("/api/v1/portals/sign-in").status_code == 403, "state changes need the Wizard header"
    from wizard_api import settings_pane
    assert "portals" in [section for section, _, _ in settings_pane.SECTIONS]
    assert settings_pane.BY_KEY["WIZARD_BROWSER"].choices == ("chrome", "msedge")
    assert settings_pane.BY_KEY["WIZARD_PORTAL_BDP_CATALOG_URL"].section == "portals"
    assert settings_pane.BY_KEY["WIZARD_PORTAL_BDP_URL"].label == "Big Data Portal: Superset"


def test_settings_show_both_big_data_portal_addresses(tmp_path: Path):
    from fastapi.testclient import TestClient

    from wizard_api.app import create_app
    settings = make_settings(tmp_path, WIZARD_PORTAL_BDP_URL="https://superset.corp.example.com/sqllab/",
                             WIZARD_PORTAL_BDP_CATALOG_URL="https://catalog.corp.example.com/",
                             WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    with TestClient(create_app(settings)) as client:
        login(client, "local-owner")
        systems = client.get("/api/v1/bootstrap").json()["systems"]
        assert [s for s in systems if s["id"] == "bdp"] == [{"id": "bdp", "name": "Big Data Portal", "kind": "portal",
                                                              "data_mode": "LIVE"}], "one system with two applications"
        assert client.get("/api/v1/portals").json()["portals"] == [
            {"id": "bdp", "name": "Big Data Portal", "host": "superset.corp.example.com",
             "parts": [{"id": "superset", "name": "Superset", "host": "superset.corp.example.com"},
                       {"id": "catalog", "name": "information catalog", "host": "catalog.corp.example.com"}],
             "access_requests": True}]


def test_without_portals_there_are_no_portal_tools(client):
    assert not any(name.startswith("portal_") for name in client.app.state.registry.specs)
    login(client, "u-ceo")
    assert client.get("/api/v1/portals").status_code == 404
    assert client.post("/api/v1/portals/sign-in", headers=HEADERS).status_code == 404
