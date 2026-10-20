"""Recurring extractions end to end, with a scripted model and a fake Metronome: the proposal streams as a card, only the
person's click creates the Flow (as Metronome's Wizard user, once), failures can be retried, an uncertain outcome is
never resent, other people cannot touch it, Make recurring starts a follow-up, and Settings tests the connection."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, WIZARD_KEY, FakeMetronome, ask, login, wait_run
from tests.unit.test_postgres_query import SETTINGS, FakeSession
from tests.unit.test_schedule_tool import ARGS

from wizard_agent.prompting import RECURRING_REQUEST
from wizard_agent.replay import ReplayRuntime
from wizard_api.app import create_app
from wizard_api.config import load_settings
from wizard_connectors.postgres_query import PostgresQuery


class Scripted(ReplayRuntime):
    """Gemini as far as Wizard can see it: one tool call through the bridge, then the answer."""

    prompts: list[str] = []

    async def run(self, request, emit, tools, cancelled):  # type: ignore[no-untyped-def]
        Scripted.prompts.append(request.prompt)
        await emit("agent_session", {"session_id": request.run_id, "model": "scripted"})
        if "schedule" in request.question:
            ok, text = await tools.call("wizard_schedule_extraction", ARGS)
            assert ok, text
            await emit("text_delta", {"text": "Here is the schedule [R1]: confirm it on the card. [E1]"})
        else:
            await emit("text_delta", {"text": "Who should receive it, and when?"})


@pytest.fixture
def app(tmp_path: Path):
    settings = load_settings(env={"WIZARD_AGENT_RUNTIME": "replay", "WIZARD_PG_HOST": "db.corp", "WIZARD_PG_USER": "reader",
                                  "WIZARD_LOCAL_USER_EMAIL": "o@corp.test", "WIZARD_LOCAL_USER_NAME": "Rafael",
                                  "WIZARD_METRONOME_URL": "http://metronome.corp:8000",
                                  "WIZARD_METRONOME_CLIENT_KEY": WIZARD_KEY, "WIZARD_ATTACHMENT_OFFICE": "never",
                                  "WIZARD_ATTACHMENT_FOLDERS": "none"}, home=tmp_path)
    fake = FakeMetronome()
    with TestClient(create_app(settings, runtime=Scripted(settings.transcripts_dir, 0),
                               metronome_transport=fake.transport())) as client:
        client.app.state.manager.services.postgres = PostgresQuery(SETTINGS, connect=lambda s, d: FakeSession())
        login(client, "local-owner")
        yield client, fake


def proposed(client: TestClient) -> dict[str, Any]:
    run = ask(client, "Send me this schedule every Monday")
    assert run["status"] == "succeeded", run
    [schedule] = run["schedules"]
    assert [e["payload"]["schedule"]["id"] for e in run["events"] if e["type"] == "schedule_proposed"] == [schedule["id"]]
    return dict(schedule)


def create(client: TestClient, schedule_id: str) -> Any:
    return client.post(f"/api/v1/schedules/{schedule_id}/create", headers=HEADERS)


def test_only_the_click_creates_the_flow_as_wizard_and_only_once(app):
    client, fake = app
    boot = client.get("/api/v1/bootstrap").json()
    assert boot["metronome"] == {"enabled": True, "user": "Wizard"}
    assert {"id": "metronome", "name": "Metronome", "kind": "schedules"} in boot["systems"]
    schedule = proposed(client)
    assert schedule["status"] == "proposed" and schedule["label"] == "R1" and not fake.calls, "proposing sends nothing"
    assert schedule["requested_by"] == {"name": "Rafael"} and schedule["schedule_text"].startswith("Every Monday")
    created = create(client, schedule["id"]).json()["schedule"]
    assert created["status"] == "created" and created["flow"]["id"] == 41 and created["flow"]["owner"] == "Wizard"
    assert fake.flows[0]["owner_name"] == "Wizard" and fake.flows[0]["email_delivery"]["recipients"] == ["o@corp.test", "cfo@corp.test"]
    assert create(client, schedule["id"]).json()["schedule"]["status"] == "created"
    assert len(fake.flows) == 1, "a second click does not create a second Flow"
    assert client.post(f"/api/v1/schedules/{schedule['id']}/dismiss", headers=HEADERS).status_code == 409
    run = client.get(f"/api/v1/runs/{schedule['run_id']}").json()
    assert run["schedules"][0]["status"] == "created", "a reopened answer shows the current state"
    audit = client.app.state.store.audit_entries()
    assert any(a["action"] == "metronome:create_flow" and a["outcome"] == "ok" for a in audit)


def test_a_refusal_can_be_retried_and_an_uncertain_outcome_cannot(app):
    client, fake = app
    fake.fail_create = 409
    schedule = proposed(client)
    failed = create(client, schedule["id"]).json()["schedule"]
    assert failed["status"] == "failed" and "already exists" in failed["error"]
    fake.fail_create = "timeout"
    uncertain = create(client, schedule["id"]).json()["schedule"]
    assert uncertain["status"] == "uncertain" and "may have been created" in uncertain["error"]
    fake.fail_create = None
    assert create(client, schedule["id"]).status_code == 409, "never resent by itself"
    fake.fail_create = "garbage"
    odd = proposed(client)
    assert create(client, odd["id"]).json()["schedule"]["status"] == "uncertain", "an unreadable reply may have created it"
    fake.fail_create = None
    assert client.post(f"/api/v1/schedules/{schedule['id']}/dismiss", headers=HEADERS).status_code == 409
    other = proposed(client)
    assert other["label"] == "R1", "labels count per conversation"
    assert len(fake.flows) == 0
    assert client.post(f"/api/v1/schedules/{other['id']}/dismiss", headers=HEADERS).json()["schedule"]["status"] == "dismissed"
    assert create(client, other["id"]).status_code == 409 and not fake.flows


def test_other_people_cannot_see_or_create_it(app):
    client, fake = app
    schedule = proposed(client)
    login(client, "u-ceo")
    assert create(client, schedule["id"]).status_code == 404
    assert client.get("/api/v1/bootstrap").json()["metronome"]["enabled"] is False, "no PostgreSQL right, no schedules"
    assert not fake.calls


def test_make_recurring_starts_a_follow_up_that_asks(app):
    client, _ = app
    first = ask(client, "Weekly sell-out by market")
    started = client.post(f"/api/v1/runs/{first['id']}/recurring", headers=HEADERS).json()
    run = wait_run(client, started["run_id"])
    assert run["kind"] == "recurring" and run["question"] == "Make this recurring" and run["status"] == "succeeded"
    assert RECURRING_REQUEST in Scripted.prompts[-1]
    assert "User: Weekly sell-out by market" in Scripted.prompts[-1]
    later = ask(client, "To me, Mondays at 8", started["conversation_id"])
    assert "User: Make this recurring" in Scripted.prompts[-1] and later["status"] == "succeeded"


def test_settings_test_the_metronome_connection(tmp_path):
    (tmp_path / ".env").write_text("WIZARD_AGENT_RUNTIME=code-assist\n", encoding="utf-8")
    settings = load_settings(env={"WIZARD_PROXY": "direct"}, home=tmp_path)
    fake = FakeMetronome()
    with TestClient(create_app(settings, metronome_transport=fake.transport())) as client:
        login(client, "local-owner")
        section = next(s for s in client.get("/api/v1/settings").json()["sections"] if s["id"] == "metronome")
        assert section["title"] == "Metronome"
        values = {"WIZARD_METRONOME_URL": "http://metronome.corp:8000", "WIZARD_METRONOME_CLIENT_KEY": WIZARD_KEY}
        tested = client.post("/api/v1/settings/test", json={"section": "metronome", "values": values}, headers=HEADERS).json()
        assert tested["ok"] is True and "as Wizard" in tested["message"]
        fake.keys[WIZARD_KEY] = 1
        tested = client.post("/api/v1/settings/test", json={"section": "metronome", "values": values}, headers=HEADERS).json()
        assert tested["ok"] is False and "as Rafael, not Wizard" in tested["message"]
        empty = client.post("/api/v1/settings/test", json={"section": "metronome", "values": {}}, headers=HEADERS).json()
        assert empty == {"ok": False, "message": "Fill in Metronome's address and Wizard's key."}
