"""Wizard asks the person before a long route (owner, 3 Nov 2026: "if you believe that perhaps ASKING the user for more
info before proceeding, feel free ... like a prompt helper"). Gemini decides when, with wizard_ask_person: the options
become buttons, the one clicked is the person's next question, and the run stops gathering data once it has asked.
Only a question asks; a task, a mapping round or Check my data has nobody waiting. Gemini is scripted here."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, login, make_settings, wait_run
from tests.integration.test_steering_api import ScriptedRuntime, say

from wizard_agent.prompting import system_prompt
from wizard_api.app import create_app

ASK = "wizard_ask_person"
OPTIONS = ["Daily, from GSCM (a live read, a few minutes)", "Weekly, from the database (seconds)"]


@pytest.fixture
def scripted(tmp_path: Path) -> Iterator[tuple[TestClient, ScriptedRuntime]]:
    runtime = ScriptedRuntime()
    with TestClient(create_app(make_settings(tmp_path), runtime=runtime)) as client:  # type: ignore[arg-type]
        login(client, "u-ceo")
        yield client, runtime


def test_gemini_asks_once_with_options_and_then_stops_gathering_data(scripted):
    client, runtime = scripted
    outcomes: list[tuple[bool, str]] = []

    async def script(request, emit, tools):
        outcomes.append(await tools.call(ASK, {"question": "Daily from GSCM, or weekly from the database?",
                                               "options": OPTIONS + [OPTIONS[0]], "why": "Only GSCM has each day."}))
        outcomes.append(await tools.call("wizard_lookup_definitions", {"query": "sell-out"}))
        outcomes.append(await tools.call(ASK, {"question": "Which market?", "options": ["UAE", "KSA"]}))
        outcomes.append(await tools.call("wizard_calculate", {"expression": "a / b", "variables": [{"name": "a", "value": 1}, {"name": "b", "value": 2}]}))
        await say(emit, "Daily from GSCM, or weekly from the database?")

    runtime.script = script
    started = client.post("/api/v1/runs", json={"question": "Sell-out by operator against the day before?"}, headers=HEADERS)
    run = wait_run(client, started.json()["run_id"])
    assert run["status"] == "succeeded" and ASK in runtime.offered[0]
    asked = json.loads(outcomes[0][1])
    assert outcomes[0][0] and asked["options"] == OPTIONS, "the same option twice is shown once"
    assert "End your turn now" in asked["next"]
    research = json.loads(outcomes[1][1])["error"]
    assert research["code"] == "asked_person" and "end your turn now" in research["message"]
    assert json.loads(outcomes[2][1])["error"]["code"] == "already_asked"
    assert outcomes[3][0], "working out and presenting stay open"
    event = next(e for e in run["events"] if e["type"] == "person_asked")["payload"]
    assert event == {"question": "Daily from GSCM, or weekly from the database?", "options": OPTIONS,
                     "why": "Only GSCM has each day."}
    step = next(e for e in run["events"] if e["type"] == "tool_finished" and e["payload"]["name"] == ASK)["payload"]
    assert step["summary"].startswith("waiting for your answer: Daily, from GSCM")

    # The person clicks an option: it is their next question in the same conversation, and Gemini sees what it asked.
    async def answer(request, emit, tools):
        await say(emit, "Weekly by operator.")

    runtime.script = answer
    follow = client.post("/api/v1/runs", json={"question": OPTIONS[1], "conversation_id": run["conversation_id"]},
                         headers=HEADERS)
    assert wait_run(client, follow.json()["run_id"])["status"] == "succeeded"
    prompt = runtime.requests[1].prompt
    assert "Wizard: Daily from GSCM, or weekly from the database?" in prompt and f"<request>\n{OPTIONS[1]}" in prompt


def test_nobody_is_asked_where_nobody_is_waiting(scripted):
    client, runtime = scripted

    async def script(request, emit, tools):
        await say(emit, "Done.")

    runtime.script = script
    first = wait_run(client, client.post("/api/v1/runs", json={"question": "Share?"}, headers=HEADERS).json()["run_id"])
    check = client.post(f"/api/v1/runs/{first['id']}/check", headers=HEADERS).json()
    assert wait_run(client, check["run_id"])["status"] == "succeeded"
    assert ASK in runtime.offered[0] and ASK not in runtime.offered[1], "Check my data replays evidence; it asks nothing"


def test_the_prompt_says_when_to_ask_and_when_not_to():
    prompt = system_prompt()
    assert "wizard_ask_person" in prompt and "before a long route" in prompt
    assert "Ask at most once" in prompt and "nothing the person said settles it" in prompt
