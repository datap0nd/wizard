"""The prompt queue (owner, 4 Nov 2026: "I will put in 20 prompts, delimited with ';' ... once it finishes a prompt, goes
to the next one, so I can run overnight. If there's an error, a retry, up to 2 retries per prompt."). Gemini is scripted:
a prompt containing FAIL fails as many times as it says, one containing SIGNIN cannot run at all."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, login, make_settings
from tests.integration.test_steering_api import ScriptedRuntime, say

from wizard_agent.runtime import AgentFailure
from wizard_api import prompt_queue
from wizard_api.app import create_app
from wizard_api.prompt_queue import QueueError, split


@pytest.fixture
def queued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, ScriptedRuntime, dict[str, int]]]:
    monkeypatch.setattr(prompt_queue, "RETRY_WAITS_S", (0.05, 0.05))
    runtime = ScriptedRuntime()
    tries: dict[str, int] = {}

    async def script(request, emit, tools):
        question = request.question
        tries[question] = tries.get(question, 0) + 1
        if "SIGNIN" in question:
            raise AgentFailure("gemini_signin_required", "Link your Google account in Settings.")
        if "FAIL" in question and tries[question] <= int(question.split("FAIL", 1)[1][:1]):
            raise AgentFailure("model_error", f"Gemini failed (try {tries[question]}).")
        await say(emit, f"Answer to {question}.")

    runtime.script = script
    with TestClient(create_app(make_settings(tmp_path), runtime=runtime)) as client:  # type: ignore[arg-type]
        login(client, "u-ceo")
        yield client, runtime, tries


def settle(client: TestClient, until: tuple[str, ...] = ("done", "failed", "stopped", "interrupted"),
           timeout: float = 30) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get("/api/v1/prompts/queue", headers=HEADERS).json()
        if view["state"] in until:
            return dict(view)
        time.sleep(0.05)
    raise AssertionError(f"the queue did not settle: {view}")


def test_the_text_is_cut_at_the_separator_chosen():
    assert split(" a ; b;;\n c ;", "semicolon") == ["a", "b", "c"]
    assert split("one\r\ntwo\n\n three ", "newline") == ["one", "two", "three"]
    assert split("first line\nstill first\n  \nsecond", "blank_line") == ["first line\nstill first", "second"]
    assert split("a | b", "pipe") == ["a", "b"] and split("a\n---\nb", "dashes") == ["a", "b"]
    assert split("a ## b ##c", "custom", "##") == ["a", "b", "c"]
    assert split("a\\nb", "custom", "\\n") == ["a\\nb"], "a typed \\n in a custom separator is a line break"
    with pytest.raises(QueueError):
        split("a;b", "custom", "  ")


def test_prompts_run_one_after_another_each_in_its_own_chat(queued):
    client, runtime, _ = queued
    added = client.post("/api/v1/prompts/queue", json={"text": "Share in UAE?; Sell-out by operator?; Spend by market?"},
                        headers=HEADERS)
    assert added.status_code == 200 and added.json()["state"] == "ready" and added.json()["total"] == 3
    started = client.post("/api/v1/prompts/queue/start", headers=HEADERS)
    assert started.status_code == 200
    view = settle(client)
    assert view["state"] == "done" and view["done"] == 3 and view["message"] == "3 of 3 prompts answered."
    assert [r.question for r in runtime.requests] == ["Share in UAE?", "Sell-out by operator?", "Spend by market?"]
    chats = {i["conversation_id"] for i in view["items"]}
    assert len(chats) == 3 and None not in chats, "each prompt in a chat of its own"
    assert all(i["attempts"] == 1 for i in view["items"])
    listed = {c["id"] for c in client.get("/api/v1/conversations", headers=HEADERS).json()["conversations"]}
    assert chats <= listed, "the chats are in the person's list, to read in the morning"
    assert "wizard_ask_person" not in runtime.offered[0], "nobody is there to answer a question"
    assert "<from_the_prompt_queue>" in runtime.requests[0].prompt


def test_a_failed_prompt_is_tried_again_twice_then_the_queue_goes_on(queued):
    client, runtime, tries = queued
    client.post("/api/v1/prompts/queue", json={"text": "First FAIL2\nSecond FAIL9\nThird", "separator": "newline"},
                headers=HEADERS)
    client.post("/api/v1/prompts/queue/start", headers=HEADERS)
    view = settle(client)
    first, second, third = view["items"]
    assert first["state"] == "done" and first["attempts"] == 3, "two failures, answered on the second retry"
    assert second["state"] == "failed" and second["attempts"] == 3 and tries["Second FAIL9"] == 3
    assert "Failed 3 times" in second["message"] and "try 3" in second["message"]
    assert third["state"] == "done", "the queue went on after a prompt failed every try"
    assert view["message"] == "2 of 3 prompts answered, 1 failed after 3 tries."
    runs = client.get(f"/api/v1/conversations/{first['conversation_id']}", headers=HEADERS).json()["runs"]
    assert [r["status"] for r in runs] == ["failed", "failed", "succeeded"], "the retries run in the prompt's own chat"

    back = client.post("/api/v1/prompts/queue/retry-failed", headers=HEADERS).json()
    assert back["state"] == "stopped" and back["items"][1]["state"] == "waiting" and back["items"][1]["attempts"] == 0


def test_a_failure_no_retry_mends_stops_the_queue_until_continue(queued):
    client, runtime, tries = queued
    client.post("/api/v1/prompts/queue", json={"text": "One|SIGNIN two|Three", "separator": "pipe"}, headers=HEADERS)
    client.post("/api/v1/prompts/queue/start", headers=HEADERS)
    view = settle(client)
    assert view["state"] == "failed" and "Link your Google account" in view["message"] and "Continue" in view["message"]
    assert [i["state"] for i in view["items"]] == ["done", "waiting", "waiting"]
    assert tries["SIGNIN two"] == 1, "not tried again: every try would fail the same way"
    assert view["items"][1]["attempts"] == 0


def test_stop_and_continue(queued):
    client, runtime, _ = queued
    slow = {"go": False}

    async def script(request, emit, tools):
        while not slow["go"] and request.question == "Slow":
            await asyncio.sleep(0.02)
        await say(emit, "ok")

    runtime.script = script
    client.post("/api/v1/prompts/queue", json={"text": "Slow; Next"}, headers=HEADERS)
    client.post("/api/v1/prompts/queue/start", headers=HEADERS)
    deadline = time.time() + 10
    while client.get("/api/v1/prompts/queue", headers=HEADERS).json()["items"][0]["state"] != "running":
        assert time.time() < deadline
        time.sleep(0.05)
    stopped = client.post("/api/v1/prompts/queue/stop", headers=HEADERS).json()
    assert stopped["state"] == "stopped" and "You stopped the queue at “Slow”" in stopped["message"]
    deadline = time.time() + 10
    while client.get("/api/v1/prompts/queue", headers=HEADERS).json()["items"][0]["state"] == "running":
        assert time.time() < deadline
        time.sleep(0.05)
    view = client.get("/api/v1/prompts/queue", headers=HEADERS).json()
    assert view["items"][0]["state"] == "stopped" and view["items"][0]["attempts"] == 0, "a stop costs no try"
    assert client.delete("/api/v1/prompts/queue", headers=HEADERS).json()["state"] == "empty", "Clear when stopped"


def test_the_persons_own_question_runs_beside_the_queue(queued):
    client, runtime, _ = queued
    gate = {"open": False}

    async def script(request, emit, tools):
        if request.question == "Queued":
            deadline = time.time() + 10
            while not gate["open"] and time.time() < deadline:
                await asyncio.sleep(0.02)
        await say(emit, "ok")

    runtime.script = script
    client.post("/api/v1/prompts/queue", json={"text": "Queued"}, headers=HEADERS)
    client.post("/api/v1/prompts/queue/start", headers=HEADERS)
    mine = client.post("/api/v1/runs", json={"question": "Mine"}, headers=HEADERS)
    assert mine.status_code == 200, "a question of the person's own is not refused as busy"
    gate["open"] = True
    assert settle(client)["state"] == "done"
    mine_run = client.get(f"/api/v1/runs/{mine.json()['run_id']}", headers=HEADERS).json()
    deadline = time.time() + 10
    while mine_run["status"] not in ("succeeded", "failed"):
        assert time.time() < deadline
        time.sleep(0.05)
        mine_run = client.get(f"/api/v1/runs/{mine.json()['run_id']}", headers=HEADERS).json()
    assert mine_run["status"] == "succeeded"
    asked_mine = next(r for r in runtime.requests if r.question == "Mine")
    assert "<from_the_prompt_queue>" not in asked_mine.prompt


def test_limits_and_a_queue_kept_across_a_restart(tmp_path: Path):
    runtime = ScriptedRuntime()
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, runtime=runtime)) as client:  # type: ignore[arg-type]
        login(client, "u-ceo")
        assert client.post("/api/v1/prompts/queue", json={"text": " ; ;"}, headers=HEADERS).status_code == 400
        too_many = ";".join(f"q{n}" for n in range(prompt_queue.MAX_PROMPTS + 1))
        assert client.post("/api/v1/prompts/queue", json={"text": too_many}, headers=HEADERS).status_code == 400
        assert client.post("/api/v1/prompts/queue", json={"text": "a;b"}, headers=HEADERS).json()["total"] == 2
    saved = json.loads((settings.data_dir / prompt_queue.QUEUE_FILE).read_text(encoding="utf-8"))
    user = next(iter(saved))
    saved[user]["state"] = "running"
    saved[user]["items"][0].update(state="running", attempts=1)
    (settings.data_dir / prompt_queue.QUEUE_FILE).write_text(json.dumps(saved), encoding="utf-8")
    with TestClient(create_app(settings, runtime=runtime)) as client:  # type: ignore[arg-type]
        login(client, "u-ceo")
        view = client.get("/api/v1/prompts/queue", headers=HEADERS).json()
        assert view["state"] == "interrupted" and "Press Continue" in view["message"]
        assert view["items"][0]["state"] == "interrupted" and view["items"][0]["attempts"] == 0
