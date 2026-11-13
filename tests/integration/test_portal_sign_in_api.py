"""The portals' sign-in check before an answer (owner, 13 Nov 2026, docs/decisions/2026-11-13-portal-sign-in-check.md),
through the API with a stand-in for the person's Wizard browser: each question checks, in code and beside the answer,
the portals it may read, and its card says how each stands."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

from tests.helpers import CEO_QUESTION, HEADERS, ask, login, wait_run

from wizard_connectors.portal_browser import SIGN_IN_AGAIN


class Browser:
    """What runs.py and the API use of a PortalBrowser: GSCM has ended the person's sign-in."""

    def __init__(self, hold: threading.Event | None = None) -> None:
        self.asked: list[list[str]] = []
        self.hold = hold
        self.state = "unknown"

    def sign_in_state(self, portal_ids: Any = None) -> dict[str, Any]:
        portals = [{"id": "gscm", "portal": "gscm", "name": "GSCM", "state": self.state, "signed_in": False},
                   {"id": "bdp-superset", "portal": "bdp", "name": "Big Data Portal: Superset", "state": "signed_in",
                    "signed_in": True}]
        return {"portals": [p for p in portals if portal_ids is None or p["portal"] in portal_ids], "checking": False,
                "signing_in": False, "checked_at": None, "why": SIGN_IN_AGAIN}

    def sign_in_due(self, portal_ids: Any) -> list[str]:
        return [] if self.state != "unknown" else list(portal_ids)

    def check_for_question(self, portal_ids: Any) -> dict[str, Any]:
        self.asked.append(list(portal_ids))
        if self.hold is not None:
            self.hold.wait(30)
        self.state = "signed_out"
        return self.sign_in_state(portal_ids)


class Browsers:
    def __init__(self, browser: Browser) -> None:
        self.browser = browser
        self.settings = SimpleNamespace(portals=[SimpleNamespace(id="gscm", name="GSCM"),
                                                 SimpleNamespace(id="bdp", name="Big Data Portal")])

    def for_user(self, user_id: str) -> Browser:
        return self.browser

    def shutdown(self) -> None:
        pass


def sign_in_events(client: Any, run: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in client.get(f"/api/v1/runs/{run['id']}").json()["events"] if e["type"] == "portal_sign_in"]


def test_each_question_checks_the_portals_it_may_read_and_its_card_says_which_ended_the_sign_in(client):
    browser = Browser()
    client.app.state.manager.services.portals = Browsers(browser)
    login(client, "u-ceo")  # GSCM and ASAP are hers; the Big Data Portal is not
    run = ask(client, CEO_QUESTION)
    assert run["status"] == "succeeded"
    assert browser.asked == [["gscm"]], "only the portals this person may use, and only those configured"
    events = sign_in_events(client, run)
    assert [e["payload"]["checking"] for e in events] == [True, False], "checking, then the result"
    assert [(p["id"], p["state"]) for p in events[-1]["payload"]["portals"]] == [("gscm", "signed_out")]
    assert events[-1]["payload"]["why"] == SIGN_IN_AGAIN
    again = ask(client, "And last week?", run["conversation_id"])
    assert browser.asked == [["gscm"], ["gscm"]] and [e["payload"]["checking"] for e in sign_in_events(client, again)] == [False]
    # Signed out stays known: the next question announces it at once, without a "checking" first.


def test_a_question_that_may_not_read_a_portal_checks_none(client):
    browser = Browser()
    client.app.state.manager.services.portals = Browsers(browser)
    login(client, "u-ceo")
    started = client.post("/api/v1/runs", json={"question": CEO_QUESTION, "systems": ["nerp"]}, headers=HEADERS)
    assert started.status_code == 200, started.text
    run = wait_run(client, started.json()["run_id"])
    assert browser.asked == [] and sign_in_events(client, run) == []


def test_a_check_that_ends_after_the_answer_adds_nothing_to_the_finished_run(client):
    hold = threading.Event()
    browser = Browser(hold)
    client.app.state.manager.services.portals = Browsers(browser)
    login(client, "u-ceo")
    try:
        started = client.post("/api/v1/runs", json={"question": CEO_QUESTION}, headers=HEADERS).json()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            run = client.get(f"/api/v1/runs/{started['run_id']}").json()
            if any(e["type"] == "run_finished" for e in run["events"]):
                break
            time.sleep(0.05)
    finally:
        hold.set()
    assert run["status"] == "succeeded", "the answer waits only a moment for the check"
    assert [e["payload"]["checking"] for e in sign_in_events(client, run)] == [True]
    deadline = time.monotonic() + 10
    while browser.state != "signed_out" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert browser.state == "signed_out", "the browser keeps the result: the page's yellow bar reads it from there"
    types = [e["type"] for e in client.get(f"/api/v1/runs/{run['id']}").json()["events"]]
    assert types[-1] == "run_finished" and types.count("portal_sign_in") == 1
