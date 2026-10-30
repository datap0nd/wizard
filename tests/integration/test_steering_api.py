"""Steering and the systems picker through the API: a scripted runtime that takes notes (as Code Assist does), the replay
runtime that cannot (a note stops the run and asks again), live system changes, and remembered notes."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import CEO_QUESTION, HEADERS, ask, login, make_settings, wait_run

from wizard_agent.runtime import AgentRequest, Emit, ToolBridge
from wizard_api.app import create_app

Script = Callable[[AgentRequest, Emit, ToolBridge], Awaitable[None]]


class ScriptedRuntime:
    """A runtime whose run is a test's own script, with the person's notes taken as Code Assist takes them."""
    kind = "code-assist"
    model = "scripted"
    steering = True

    def __init__(self) -> None:
        self.script: Script | None = None
        self.requests: list[AgentRequest] = []
        self.offered: list[list[str]] = []

    def label(self) -> str:
        return "Scripted (test)"

    async def readiness(self, user_home: Path, user_email: str) -> dict[str, Any]:
        return {"ready": True, "reason": None}

    async def run(self, request: AgentRequest, emit: Emit, tools: ToolBridge, cancelled: Any) -> None:
        self.requests.append(request)
        self.offered.append([t["name"] for t in tools.describe()])
        assert self.script is not None
        await self.script(request, emit, tools)


async def until_note(tools: ToolBridge, timeout: float = 10) -> list[str]:
    deadline = time.monotonic() + timeout
    while not tools.steers_waiting():
        assert time.monotonic() < deadline, "no note arrived"
        await asyncio.sleep(0.02)
    return await tools.take_steers()


async def say(emit: Emit, text: str) -> None:
    await emit("text_delta", {"text": text})


@pytest.fixture
def scripted(tmp_path: Path) -> Iterator[tuple[TestClient, ScriptedRuntime]]:
    runtime = ScriptedRuntime()
    with TestClient(create_app(make_settings(tmp_path), runtime=runtime)) as client:  # type: ignore[arg-type]
        login(client, "u-ceo")
        yield client, runtime


def events_of(client: TestClient, run_id: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/runs/{run_id}").json()["events"]


def wait_for(client: TestClient, run_id: str, kind: str, count: int = 1) -> list[dict[str, Any]]:
    deadline = time.time() + 10
    while time.time() < deadline:
        found = [e for e in events_of(client, run_id) if e["type"] == kind]
        if len(found) >= count:
            return found
        time.sleep(0.02)
    raise AssertionError(f"no {kind} event")


def test_bootstrap_says_whether_notes_reach_gemini_while_it_works(scripted, client):
    assert scripted[0].get("/api/v1/bootstrap").json()["runtime"]["steering"] is True
    login(client, "u-ceo")
    assert client.get("/api/v1/bootstrap").json()["runtime"]["steering"] is False, "replay cannot read a note"


def test_only_the_chosen_systems_are_offered_and_the_others_refuse(scripted):
    client, runtime = scripted
    outcomes: list[tuple[bool, str]] = []

    async def script(request, emit, tools):
        outcomes.append(await tools.call("nerp_search_reports", {"query": "spend"}))
        outcomes.append(await tools.call("asap_search_reports", {"query": "share"}))
        outcomes.append(await tools.call("wizard_search_catalog", {"query": "share spend switching"}))
        outcomes.append(await tools.call("wizard_ask_for_system", {"system": "ASAP", "reason": "Share lives in ASAP."}))
        await say(emit, "Spend is in NERP.")

    runtime.script = script
    started = client.post("/api/v1/runs", json={"question": "Spend and share?", "systems": ["nerp", "knowledge"]}, headers=HEADERS)
    run = wait_run(client, started.json()["run_id"])
    assert run["status"] == "succeeded" and run["systems"] == ["nerp", "knowledge"]
    offered = runtime.offered[0]
    assert "nerp_run_report" in offered and "wizard_lookup_definitions" in offered and "wizard_ask_for_system" in offered
    assert not [t for t in offered if t.startswith(("asap_", "gscm_"))]
    assert "wizard_search_catalog" in offered, "it spans the systems that are on"
    assert outcomes[0][0] is True
    refused = json.loads(outcomes[1][1])["error"]
    assert outcomes[1][0] is False and refused["code"] == "system_off" and "ASAP is switched off" in refused["message"]
    assert {r["system"] for r in json.loads(outcomes[2][1])["results"]} == {"nerp"}
    assert json.loads(outcomes[3][1])["system"] == "asap"
    requested = next(e for e in run["events"] if e["type"] == "system_requested")["payload"]
    assert requested == {"system": "asap", "name": "ASAP", "reason": "Share lives in ASAP."}
    prompt = runtime.requests[0].prompt
    assert "On: NERP, Knowledge base." in prompt and "Switched off: ASAP, GSCM, Attached files." in prompt
    report = client.get(f"/api/v1/reports/{run['report_id']}").json()["report"]
    assert report["systems"] == ["nerp", "knowledge"]
    auto = client.post("/api/v1/runs", json={"question": "Spend?", "conversation_id": run["conversation_id"]}, headers=HEADERS)
    assert wait_run(client, auto.json()["run_id"])["systems"] is None
    assert "wizard_ask_for_system" not in runtime.offered[1] and "asap_run_report" in runtime.offered[1]


def test_a_system_the_person_cannot_use_is_refused(scripted):
    client, _ = scripted
    for systems, words in ((["metronome"], "metronome"), (["sap"], "sap"), ([], "at least one")):
        response = client.post("/api/v1/runs", json={"question": "q", "systems": systems}, headers=HEADERS)
        assert response.status_code == 400 and words in response.json()["error"], response.text


def test_a_note_reaches_gemini_while_it_works_and_not_this_leaves_the_step_out(scripted):
    client, runtime = scripted
    heard: list[list[str]] = []

    async def script(request, emit, tools):
        await tools.call("nerp_search_reports", {"query": "spend"})
        heard.append(await until_note(tools))
        await say(emit, "Using the quarterly spend report.")

    runtime.script = script
    started = client.post("/api/v1/runs", json={"question": "Spend by market?"}, headers=HEADERS).json()
    wait_for(client, started["run_id"], "tool_finished")
    sent = client.post(f"/api/v1/runs/{started['run_id']}/steer",
                       json={"text": "use the quarterly report", "call_id": "c1", "reason": "table"}, headers=HEADERS)
    assert sent.status_code == 200, sent.text
    steer = sent.json()["steer"]
    assert steer["id"] == "s1" and steer["state"] == "waiting" and steer["reason"] == "table"
    assert steer["about"]["call_id"] == "c1" and steer["about"]["detail"] == "spend"
    run = wait_run(client, started["run_id"])
    assert run["status"] == "succeeded" and run["answer"] == "Using the quarterly spend report."
    assert len(heard[0]) == 1 and "Their words: use the quarterly report" in heard[0][0] and "wrong table" in heard[0][0]
    kinds = [e["type"] for e in run["events"]]
    assert kinds.index("steer") < kinds.index("steer_read") < kinds.index("run_finished")
    report = client.get(f"/api/v1/reports/{run['report_id']}").json()["report"]
    assert report["steers"][0]["text"] == "use the quarterly report" and report["steers"][0]["state"] == "read"
    assert "message" not in report["steers"][0], "the page shows the person's words, not Gemini's wording"


def test_an_answer_citing_a_step_marked_not_this_is_flagged(scripted):
    client, runtime = scripted

    async def script(request, emit, tools):
        ok, text = await tools.call("nerp_run_report", {"report_id": "nerp-mkt-spend-quarterly"})
        evidence = json.loads(text)["evidence_id"]
        await until_note(tools)
        await say(emit, f"EG spent the most [{evidence}].")

    runtime.script = script
    started = client.post("/api/v1/runs", json={"question": "Spend?"}, headers=HEADERS).json()
    wait_for(client, started["run_id"], "tool_finished")
    client.post(f"/api/v1/runs/{started['run_id']}/steer", json={"call_id": "c1", "reason": "period"}, headers=HEADERS)
    run = wait_run(client, started["run_id"])
    report = client.get(f"/api/v1/reports/{run['report_id']}").json()["report"]
    assert report["rejected_evidence"] == ["E1"]
    assert "The answer cites E1, which you marked Not this." in report["warnings"]


def test_switching_a_system_on_mid_run_opens_its_tools_and_tells_gemini(scripted):
    client, runtime = scripted
    seen: dict[str, Any] = {}

    async def script(request, emit, tools):
        seen["before"] = await tools.call("gscm_search_reports", {"query": "stock"})
        seen["note"] = await until_note(tools)
        seen["offered"] = [t["name"] for t in tools.describe()]
        seen["after"] = await tools.call("gscm_search_reports", {"query": "stock"})
        seen["nerp"] = await tools.call("nerp_search_reports", {"query": "spend"})
        await say(emit, "Stock is in GSCM.")

    runtime.script = script
    started = client.post("/api/v1/runs", json={"question": "Stock?", "systems": ["nerp"]}, headers=HEADERS).json()
    wait_for(client, started["run_id"], "tool_finished")
    changed = client.post(f"/api/v1/runs/{started['run_id']}/systems", json={"systems": ["gscm", "knowledge"]}, headers=HEADERS)
    assert changed.status_code == 200, changed.text
    run = wait_run(client, started["run_id"])
    assert json.loads(seen["before"][1])["error"]["code"] == "system_off"
    assert "switched on GSCM, Knowledge base; switched off NERP" in seen["note"][0]
    assert "gscm_run_report" in seen["offered"] and "nerp_run_report" in seen["offered"], "tools are never taken away"
    assert seen["after"][0] is True and json.loads(seen["nerp"][1])["error"]["code"] == "system_off"
    assert run["systems"] == ["gscm", "knowledge"]
    change = next(e for e in run["events"] if e["type"] == "systems_changed")["payload"]
    assert change["systems"] == ["gscm", "knowledge"] and change["on"] == ["GSCM", "Knowledge base"]
    assert client.post(f"/api/v1/runs/{started['run_id']}/systems", json={"systems": None}, headers=HEADERS).status_code == 409


def test_not_this_after_the_answer_asks_again_with_the_steps_in_context(scripted):
    client, runtime = scripted

    async def script(request, emit, tools):
        if not request.history:
            await tools.call("nerp_search_reports", {"query": "spend"})
        await say(emit, "EG spent the most.")

    runtime.script = script
    first = client.post("/api/v1/runs", json={"question": "Spend?", "systems": ["nerp", "knowledge"]}, headers=HEADERS).json()
    wait_run(client, first["run_id"])
    follow = client.post(f"/api/v1/runs/{first['run_id']}/steer",
                         json={"text": "search for marketing spend", "call_id": "c1", "reason": "filter"}, headers=HEADERS)
    assert follow.status_code == 200, follow.text
    started = follow.json()["follow_up"]
    assert started["question"].startswith("Not this step: Searched NERP reports for “spend”, wrong filter.")
    assert started["systems"] == ["nerp", "knowledge"], "the follow-up keeps the conversation's systems"
    second = wait_run(client, started["run_id"])
    assert second["status"] == "succeeded" and second["conversation_id"] == first["conversation_id"]
    previous = runtime.requests[1].history[0]
    assert previous.question == "Spend?" and previous.work[0].startswith("Searched NERP reports for “spend” ->")
    assert "What Wizard did for it:" in runtime.requests[1].prompt
    missing = client.post(f"/api/v1/runs/{first['run_id']}/steer", json={"call_id": "c9"}, headers=HEADERS)
    assert missing.status_code == 404
    assert client.post(f"/api/v1/runs/{first['run_id']}/steer", json={"text": " "}, headers=HEADERS).status_code == 400


def test_where_notes_cannot_reach_gemini_a_note_stops_the_run_and_asks_again(client):
    login(client, "u-ceo")
    manager = client.app.state.manager
    manager.runtime.delay_s = 0.05
    first = client.post("/api/v1/runs", json={"question": CEO_QUESTION}, headers=HEADERS).json()
    sent = client.post(f"/api/v1/runs/{first['run_id']}/steer", json={"text": "only the Gulf markets"}, headers=HEADERS)
    manager.runtime.delay_s = 0.0
    assert sent.status_code == 200, sent.text
    follow = sent.json()["follow_up"]
    assert follow["question"] == "only the Gulf markets"
    assert wait_run(client, first["run_id"])["status"] == "cancelled"
    assert wait_run(client, follow["run_id"])["conversation_id"] == first["conversation_id"]


def test_check_my_data_keeps_the_answers_systems(client):
    login(client, "u-ceo")
    started = client.post("/api/v1/runs", json={"question": CEO_QUESTION, "systems": ["asap", "gscm", "nerp", "knowledge"]},
                          headers=HEADERS).json()
    run = wait_run(client, started["run_id"])
    assert run["status"] == "succeeded", run.get("error_message")
    check = client.post(f"/api/v1/runs/{run['id']}/check", headers=HEADERS).json()
    assert wait_run(client, check["run_id"])["systems"] == ["asap", "gscm", "nerp", "knowledge"]


def test_attaching_a_file_switches_attached_files_on(scripted):
    client, runtime = scripted

    async def script(request, emit, tools):
        await say(emit, "Read.")

    runtime.script = script
    uploaded = client.post("/api/v1/attachments", content=b"market,units\nEG,12\n",
                           headers={**HEADERS, "Content-Type": "application/octet-stream", "X-File-Name": "units.csv"})
    assert uploaded.status_code == 200, uploaded.text
    started = client.post("/api/v1/runs", json={"question": "Units?", "systems": ["nerp"],
                                                "attachment_ids": [uploaded.json()["attachment"]["id"]]}, headers=HEADERS)
    assert wait_run(client, started.json()["run_id"])["systems"] == ["nerp", "attachment"]


def test_remembered_notes_are_the_persons_own_and_reach_every_request(scripted):
    client, runtime = scripted

    async def script(request, emit, tools):
        await say(emit, "ok")

    runtime.script = script
    run = ask(client, "Spend?")
    saved = client.post("/api/v1/memories", json={"text": "For sell-out use  the weekly view.", "run_id": run["id"]},
                        headers=HEADERS)
    assert saved.status_code == 200, saved.text
    memory = saved.json()["memory"]
    assert memory["text"] == "For sell-out use the weekly view." and memory["run_id"] == run["id"]
    ask(client, "Sell-out by market?")
    assert "- For sell-out use the weekly view." in runtime.requests[-1].prompt
    assert client.patch(f"/api/v1/memories/{memory['id']}", json={"text": "Weekly view for sell-out."},
                        headers=HEADERS).status_code == 200
    assert client.get("/api/v1/memories").json()["memories"][0]["text"] == "Weekly view for sell-out."
    login(client, "u-cfo")
    assert client.get("/api/v1/memories").json()["memories"] == [], "each person's notes are their own"
    assert client.delete(f"/api/v1/memories/{memory['id']}", headers=HEADERS).status_code == 404
    login(client, "u-ceo")
    assert client.delete(f"/api/v1/memories/{memory['id']}", headers=HEADERS).status_code == 200
    ask(client, "Sell-out by market?")
    assert "<remembered_by_this_person>" not in runtime.requests[-1].prompt
