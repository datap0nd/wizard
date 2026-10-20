"""A whole run that explores a portal: a recorded transcript opens the fake portal, clicks through to a report and reads
its table. The person's run streams a picture of each step (browser_frame events, served only to them), the table is
LIVE evidence with the page address, the portal shows on the systems stage, and deleting the conversation deletes the
pictures."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, ask, find_browser, login, make_settings
from tests.portal_site import Site

from wizard_api.app import create_app

BROWSER = find_browser()
pytestmark = pytest.mark.browser

TRANSCRIPT = {
    "id": "portal-sell-in", "kind": "ask", "data_mode": "LIVE", "match": ["sell-in+portal"],
    "steps": [
        {"say": "Looking for the sell-in report on the DEMO portal."},
        {"tool": "wizard_portal_open", "args": {"portal": "demo"}},
        {"tool": "wizard_portal_open", "args": {"portal": "demo", "path": "/report/sell-in-monthly"}},
        {"tool": "wizard_portal_read_table", "as": "table", "args": {"portal": "demo"}},
        {"say": "SA sold in 1,234 units of Model A in July 2026 [{table}]."},
    ],
}


@pytest.fixture
def portal_client(tmp_path: Path) -> Iterator[tuple[TestClient, Site]]:
    if BROWSER is None:
        pytest.skip("BLOCKED: no Chromium-based browser here for the portal tests (set WIZARD_TEST_BROWSER)")
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "portal.json").write_text(json.dumps(TRANSCRIPT), encoding="utf-8")
    with Site() as site:
        settings = make_settings(tmp_path, WIZARD_PORTAL_DEMO=site.url, WIZARD_BROWSER=BROWSER,
                                 WIZARD_LOCAL_USER_EMAIL="owner@wizard.test", WIZARD_TRANSCRIPTS_DIR=str(transcripts))
        with TestClient(create_app(settings)) as client:
            yield client, site


def test_a_run_explores_the_portal_and_shows_each_step(portal_client: tuple[TestClient, Site]) -> None:
    client, site = portal_client
    login(client, "local-owner")
    systems = client.get("/api/v1/bootstrap").json()["systems"]
    assert {"id": "demo", "name": "DEMO", "kind": "portal", "data_mode": "LIVE", "portal": True} in systems
    assert client.get("/api/v1/portals").json()["portals"][0]["id"] == "demo"

    run = ask(client, "What was sell-in for Model A on the portal?")
    assert run["status"] == "succeeded", run.get("error_message")
    events = run["events"]
    frames = [e["payload"] for e in events if e["type"] == "browser_frame"]
    calls = {e["payload"]["call_id"]: e["payload"]["name"] for e in events if e["type"] == "tool_started"}
    assert [calls[f["call_id"]] for f in frames] == ["wizard_portal_open", "wizard_portal_open", "wizard_portal_read_table"]
    assert [f["phase"] for f in frames] == ["after", "after", "before"]
    assert frames[2]["action"] == "Reading the table “Sell-in”" and frames[2]["target"]["width"] > 0
    assert frames[1]["url"].endswith("/report/sell-in-monthly") and frames[1]["viewport"] == {"width": 1280, "height": 800}
    # Each picture's event comes between its call's start and finish.
    order = [(e["type"], e["payload"].get("call_id")) for e in events if e["type"] in ("tool_started", "browser_frame", "tool_finished")]
    assert order[:3] == [("tool_started", "c1"), ("browser_frame", "c1"), ("tool_finished", "c1")]

    picture = client.get(f"/api/v1/runs/{run['id']}/frames/{frames[0]['frame']}")
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/jpeg"
    assert picture.content.startswith(b"\xff\xd8")
    assert client.get(f"/api/v1/runs/{run['id']}/frames/../../wizard.sqlite3").status_code == 404
    assert client.get(f"/api/v1/runs/{run['id']}/frames/f999").status_code == 404

    finished = [e["payload"] for e in events if e["type"] == "tool_finished"]
    assert finished[0]["summary"].startswith("Reports home · ")
    evidence = finished[-1]["evidence"]
    assert (evidence["system"], evidence["data_mode"], evidence["system_name"]) == ("portal", "LIVE", "DEMO (portal page)")
    detail = client.get(f"/api/v1/conversations/{run['conversation_id']}/evidence/{evidence['id']}").json()["evidence"]
    assert detail["connector_status"] == "BROWSER_READ" and detail["locator"]["open_url"].endswith("/report/sell-in-monthly")
    assert detail["rows"][0] == ["SA", "Model A", "2026-07", 1234, 12.5]
    assert "[E1]" in run["answer"] and run["data_mode"] == "LIVE"
    assert not [r for r in site.requests if r.startswith("POST")]

    # Another person never sees these pictures; deleting the conversation deletes them.
    frames_dir = Path(client.app.state.settings.data_dir) / "frames" / run["id"]  # type: ignore[attr-defined]
    assert len(list(frames_dir.glob("f*.jpg"))) == 3
    assert client.delete(f"/api/v1/conversations/{run['conversation_id']}", headers=HEADERS).status_code == 200
    assert not frames_dir.exists()


def test_checking_a_portal_and_the_sign_in_window_rules(portal_client: tuple[TestClient, Site]) -> None:
    client, _ = portal_client
    login(client, "local-owner")
    checked = client.post("/api/v1/portals/demo/check", headers=HEADERS).json()
    assert (checked["state"], checked["title"]) == ("ready", "Reports home")
    assert client.get("/api/v1/portals").json()["portals"][0]["state"] == "ready"
    assert client.post("/api/v1/portals/nope/check", headers=HEADERS).status_code == 404
    assert client.post("/api/v1/portals/signin/done", headers=HEADERS).json() == {"ok": True}
    login(client, "u-ceo")  # a test identity has no portal rights
    assert client.get("/api/v1/portals").json()["portals"] == []
    assert client.post("/api/v1/portals/demo/check", headers=HEADERS).status_code == 404
