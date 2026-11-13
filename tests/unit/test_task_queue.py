"""The task queue (owner, 2 Nov 2026): "a 'run all tasks' button ... it goes from one to another (only when all of them
succeeded)", and "tick like 5 of them and click run selected tasks ... so I can go to lunch and leave them running".
Tasks run one after another in Settings → Tasks, the next only when the one before succeeded; a task may repeat until
done (`repeat: until_done`, its summary's `Left:` line); the queue outlives a restart."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, login, make_settings
from tests.unit.test_tasks import NOTE

from wizard_agent.prompting import compose, left_to_do
from wizard_agent.runtime import AgentFailure
from wizard_api import knowledge_sync
from wizard_api.app import create_app
from wizard_api.awake import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, KeepAwake
from wizard_api.tasks import TaskBoard, parse, run_order
from wizard_connectors.portal_map import Published


def task(task_id: str, title: str, added: str, extra: str = "") -> str:
    return f"---\nid: {task_id}\ntitle: {title}\nsummary: One line.\nadded: {added}\n{extra}---\nDo {title}.\n"


A = task("a-first", "Task A", "2026-10-30")
B = task("b-second", "Task B", "2026-11-01")
C = task("c-third", "Task C", "2026-11-01")
ABC = {"a-first": A, "b-second": B, "c-third": C}


class Scripted:
    """A scripted Gemini. plan: a task's title -> what each of its runs does, in turn (the last one repeats): steps joined
    by +: save (a note to the knowledge base), leftN (end the summary with Left: N), fail, block (until released or
    stopped)."""
    kind = "code-assist"
    model = "gemini-3.8-flash"

    def __init__(self, plan: dict[str, list[str]] | None = None):
        self.plan = plan or {}
        self.questions: list[str] = []
        self.prompts: list[str] = []
        self.release = threading.Event()
        self.saved = 0

    def label(self) -> str:
        return "Queue test runtime"

    async def readiness(self, home: Path, email: str) -> dict[str, Any]:
        return {"ready": True, "reason": None}

    @staticmethod
    def title(question: str) -> str:
        return question.removeprefix("Task: ").split(" (")[0]

    async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
        self.questions.append(request.question)
        self.prompts.append(request.prompt)
        name = self.title(request.question)
        steps = self.plan.get(name, ["ok"])
        turn = sum(1 for q in self.questions if self.title(q) == name)
        summary = f"{name} done."
        for action in steps[min(turn, len(steps)) - 1].split("+"):
            if action == "fail":
                raise AgentFailure("model_quota", "Gemini's quota is used up.")
            if action == "block":
                while not self.release.is_set():
                    await asyncio.sleep(0.01)
            if action == "save":
                self.saved += 1
                note_id = f"queue-note-{self.saved}"
                ok, text = await tools.call("wizard_kb_save_notes", {"notes": [{
                    "path": f"knowledge/metrics/{note_id}.md", "text": NOTE.replace("market-share", note_id)}],
                    "message": "A note"})
                assert ok, text
            if action.startswith("left"):
                summary += f"\n\nLeft: {action[4:]}"
        await emit("text_delta", {"text": summary})


def queue_app(tmp_path: Path, runtime: Scripted, tasks: dict[str, str], install: bool = True) -> TestClient:
    settings = make_settings(tmp_path, WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = install
    app = create_app(settings, runtime=runtime)  # type: ignore[arg-type]
    bundled = tmp_path / "bundled"
    bundled.mkdir(exist_ok=True)
    for name, text in tasks.items():
        (bundled / f"{name}.md").write_text(text, encoding="utf-8")
    board: TaskBoard = app.state.task_board
    board.bundled = bundled
    app.state.manager.services.kb_writer = lambda files, message: Published("published", "ok", "c1")
    return TestClient(app)


def until(client: TestClient, done: Any, timeout: float = 20) -> dict[str, Any]:
    deadline = time.time() + timeout
    view: dict[str, Any] = {}
    while time.time() < deadline:
        view = client.get("/api/v1/tasks").json()
        if done(view):
            return view
        time.sleep(0.03)
    raise AssertionError(f"the queue did not get there: {json.dumps(view.get('queue'), indent=1)}")


def post(client: TestClient, path: str, body: Any = None, status: int = 200) -> dict[str, Any]:
    response = client.post(path, json=body, headers=HEADERS) if body is not None else client.post(path, headers=HEADERS)
    assert response.status_code == status, response.text
    return dict(response.json())


def ids(view: dict[str, Any]) -> list[str]:
    return [i["id"] for i in view["queue"]["items"]]


def states(view: dict[str, Any]) -> list[tuple[str, str]]:
    return [(i["id"], i["state"]) for i in view["queue"]["items"]]


def key(view: dict[str, Any], task_id: str) -> str:
    return str(next(i["key"] for i in view["queue"]["items"] if i["id"] == task_id))


# Order -------------------------------------------------------------------------------------------------------------------
def test_run_all_queues_oldest_first_and_the_person_reorders_before_start(tmp_path: Path):
    runtime = Scripted()
    with queue_app(tmp_path, runtime, ABC) as client:
        login(client, "local-owner")
        listed = client.get("/api/v1/tasks?refresh=true").json()
        assert [t["id"] for t in listed["tasks"]] == ["c-third", "b-second", "a-first"], "the list stays newest first"
        assert listed["queue"]["state"] == "empty" and listed["queue"]["items"] == []
        view = post(client, "/api/v1/tasks/queue", {})
        assert ids(view) == ["a-first", "b-second", "c-third"], "oldest added first, then id"
        assert view["queue"]["state"] == "ready" and view["queue"]["left_out"] == [] and runtime.questions == []
        view = post(client, f"/api/v1/tasks/queue/items/{key(view, 'c-third')}/move", {"by": -1})
        view = post(client, f"/api/v1/tasks/queue/items/{key(view, 'c-third')}/move", {"by": -1})
        assert ids(view) == ["c-third", "a-first", "b-second"]
        post(client, f"/api/v1/tasks/queue/items/{key(view, 'c-third')}/move", {"by": -1}, status=409)
        view = client.delete(f"/api/v1/tasks/queue/items/{key(view, 'b-second')}", headers=HEADERS).json()
        assert ids(view) == ["c-third", "a-first"]
        view = post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["state"] == "done")
        assert runtime.questions == ["Task: Task C", "Task: Task A"], "the order the person chose"
        assert view["queue"]["message"] == "All 2 tasks succeeded." and view["queue"]["done"] == 2
        assert {t["id"]: t["state"] for t in view["tasks"]} == {"c-third": "done", "b-second": "todo", "a-first": "done"}
        conversations = {i["conversation_id"] for i in view["queue"]["items"]}
        assert len(conversations) == 2, "each task in a conversation of its own"
        assert [run_order([parse(t) for t in (C, B, A)])[i].id for i in range(3)] == ["a-first", "b-second", "c-third"]  # type: ignore[misc]


def test_numbered_tasks_added_together_run_in_their_numbers_order():
    texts = [f"---\nid: review-{n}-step\ntitle: Review step {n}\nsummary: Step {n}.\nadded: 2026-11-02\n---\nDo step {n}.\n"
             for n in (3, 0, 2, 1)]
    found = [parse(t) for t in texts]
    assert all(found)
    assert [t.id for t in run_order(found)] == [f"review-{n}-step" for n in range(4)]  # type: ignore[union-attr]


# Running -----------------------------------------------------------------------------------------------------------------
def test_success_moves_on_and_a_failure_stops_the_queue_until_continue(tmp_path: Path):
    runtime = Scripted({"Task B": ["fail", "ok"]})
    with queue_app(tmp_path, runtime, ABC) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/queue", {})
        post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["state"] == "failed")
        assert states(view) == [("a-first", "done"), ("b-second", "failed"), ("c-third", "waiting")]
        assert view["queue"]["message"] == "Stopped at “Task B”, which failed: Gemini's quota is used up."
        assert view["queue"]["position"] == 2 and view["queue"]["done"] == 1 and runtime.questions == ["Task: Task A", "Task: Task B"]
        assert view["queue"]["items"][1]["conversation_id"], "See why links to its conversation"
        post(client, "/api/v1/tasks/queue/start")  # Continue
        view = until(client, lambda v: v["queue"]["state"] == "done")
        assert runtime.questions == ["Task: Task A", "Task: Task B", "Task: Task B", "Task: Task C"], "from the failed task on"
        assert states(view) == [("a-first", "done"), ("b-second", "done"), ("c-third", "done")]
        client.delete("/api/v1/tasks/queue", headers=HEADERS)
        assert client.get("/api/v1/tasks").json()["queue"]["state"] == "empty"


def test_stop_stops_the_run_and_the_queue_and_continue_runs_that_task_again(tmp_path: Path):
    runtime = Scripted({"Task A": ["block", "ok"]})
    with queue_app(tmp_path, runtime, ABC) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/queue", {})
        view = post(client, "/api/v1/tasks/queue/start")
        assert view["queue"]["state"] == "running" and view["queue"]["position"] == 1
        assert view["queue"]["current"] == view["queue"]["items"][0]["key"] and view["queue"]["items"][0]["conversation_id"]
        until(client, lambda v: runtime.questions == ["Task: Task A"])
        refused = client.post("/api/v1/tasks/b-second/run", headers=HEADERS)
        assert refused.status_code == 429 and "queue is running" in refused.json()["error"], "one task at a time"
        assert client.post("/api/v1/tasks/queue", json={}, headers=HEADERS).status_code == 409
        assert client.delete("/api/v1/tasks/queue", headers=HEADERS).status_code == 409
        view = post(client, "/api/v1/tasks/queue/stop")
        assert view["queue"]["state"] == "stopped" and view["queue"]["message"] == "You stopped the queue at “Task A”."
        view = until(client, lambda v: v["queue"]["items"][0]["state"] == "stopped")
        assert view["tasks"][-1]["state"] == "stopped" and runtime.questions == ["Task: Task A"], "Task B never started"
        post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["state"] == "done")
        assert runtime.questions == ["Task: Task A", "Task: Task A", "Task: Task B", "Task: Task C"]


def test_a_run_cancelled_in_its_conversation_stops_the_queue_there(tmp_path: Path):
    runtime = Scripted({"Task B": ["block", "ok"]})
    with queue_app(tmp_path, runtime, ABC) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/queue", {})
        post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["position"] == 2 and v["queue"]["state"] == "running")
        run_id = view["queue"]["items"][1]["run_id"]
        until(client, lambda v: len(runtime.questions) == 2)
        assert client.post(f"/api/v1/runs/{run_id}/cancel", headers=HEADERS).json() == {"cancelled": True}
        view = until(client, lambda v: v["queue"]["state"] == "stopped")
        assert view["queue"]["message"] == "Stopped at “Task B”, which was stopped: Its run was stopped."
        assert states(view) == [("a-first", "done"), ("b-second", "stopped"), ("c-third", "waiting")]
        post(client, "/api/v1/tasks/queue/start")
        until(client, lambda v: v["queue"]["state"] == "done")
        assert runtime.questions[-2:] == ["Task: Task B", "Task: Task C"]


def test_ticked_tasks_are_kept_until_the_queue_starts_and_a_task_is_added_while_it_runs(tmp_path: Path):
    runtime = Scripted({"Task A": ["block"]})
    with queue_app(tmp_path, runtime, ABC) as client:
        login(client, "local-owner")
        view = client.put("/api/v1/tasks/selection", json={"ids": ["c-third", "a-first"]}, headers=HEADERS).json()
        assert view["queue"]["selected"] == ["c-third", "a-first"]
        saved = json.loads((tmp_path / "var" / "tasks" / "queues.json").read_text(encoding="utf-8"))
        assert saved["local-owner"]["selected"] == ["c-third", "a-first"], "kept in the data folder, per person"
        assert client.get("/api/v1/tasks").json()["queue"]["selected"] == ["c-third", "a-first"]
        post(client, "/api/v1/tasks/queue", {"ids": []}, status=400)
        view = post(client, "/api/v1/tasks/queue", {"ids": ["c-third", "a-first"]})
        assert ids(view) == ["a-first", "c-third"] and view["queue"]["selected"] == ["c-third", "a-first"]
        view = post(client, "/api/v1/tasks/queue/start")
        assert view["queue"]["selected"] == [], "the ticks clear once the queue starts"
        until(client, lambda v: runtime.questions == ["Task: Task A"])
        post(client, "/api/v1/tasks/c-third/queue", {}, status=409)  # already waiting in it
        view = post(client, "/api/v1/tasks/b-second/queue", {})
        assert ids(view) == ["a-first", "c-third", "b-second"] and view["queue"]["state"] == "running"
        runtime.release.set()
        view = until(client, lambda v: v["queue"]["state"] == "done")
        assert runtime.questions == ["Task: Task A", "Task: Task C", "Task: Task B"]
        view = post(client, "/api/v1/tasks/a-first/queue", {})
        assert ids(view) == ["a-first"] and view["queue"]["state"] == "ready", "adding to a finished queue starts a new one"


def test_the_pc_stays_awake_for_the_whole_queue(tmp_path: Path):
    calls: list[int] = []
    runtime = Scripted()
    with queue_app(tmp_path, runtime, ABC) as client:
        client.app.state.manager.awake = KeepAwake(lambda flags: (calls.append(flags), 1)[1])
        login(client, "local-owner")
        post(client, "/api/v1/tasks/queue", {})
        post(client, "/api/v1/tasks/queue/start")
        until(client, lambda v: v["queue"]["state"] == "done")
        assert len(runtime.questions) == 3
        assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS], "awake from Start to the end, never let go between tasks"
        assert client.app.state.manager.awake.running == 0


# Tasks that ask for a path -----------------------------------------------------------------------------------------------
def test_a_task_that_asks_for_a_path_is_queued_only_with_one(tmp_path: Path):
    folder = tmp_path / "Notes"
    folder.mkdir()
    (folder / "terms.txt").write_text("GTM: go-to-market.", encoding="utf-8")
    reader = task("p-folder", "Read a folder", "2026-10-29", "input: folder\n")
    runtime = Scripted()
    with queue_app(tmp_path, runtime, {**ABC, "p-folder": reader}) as client:
        login(client, "local-owner")
        view = post(client, "/api/v1/tasks/queue", {})
        assert ids(view) == ["a-first", "b-second", "c-third"]
        assert [(o["id"], o["title"]) for o in view["queue"]["left_out"]] == [("p-folder", "Read a folder")]
        assert "asks for a folder" in view["queue"]["left_out"][0]["reason"], "Run all says which it left out"
        view = post(client, "/api/v1/tasks/queue", {"paths": {"p-folder": str(tmp_path / "nowhere")}})
        assert "cannot find" in view["queue"]["left_out"][0]["reason"], "checked like a single run"
        refused = client.post("/api/v1/tasks/p-folder/queue", json={}, headers=HEADERS)
        assert refused.status_code == 400 and "Type or paste the path" in refused.json()["error"]
        view = post(client, "/api/v1/tasks/queue", {"paths": {"p-folder": f'"{folder}"'}})
        assert ids(view) == ["p-folder", "a-first", "b-second", "c-third"] and view["queue"]["left_out"] == []
        assert view["queue"]["items"][0]["path"] == str(folder.resolve())
        post(client, "/api/v1/tasks/queue/start")
        until(client, lambda v: v["queue"]["state"] == "done")
        assert f"The person chose this folder for the task: {folder.resolve()}" in runtime.prompts[0]
        assert client.get("/api/v1/tasks").json()["tasks"][-1]["path"] == str(folder.resolve()), "the path box remembers it"


def test_a_queued_path_that_is_gone_when_its_turn_comes_stops_the_queue(tmp_path: Path):
    folder = tmp_path / "Notes"
    folder.mkdir()
    (folder / "terms.txt").write_text("GTM: go-to-market.", encoding="utf-8")
    reader = task("p-folder", "Read a folder", "2026-11-05", "input: folder\n")
    runtime = Scripted()
    with queue_app(tmp_path, runtime, {"a-first": A, "p-folder": reader}) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/queue", {"paths": {"p-folder": str(folder)}})
        (folder / "terms.txt").unlink()
        folder.rmdir()
        post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["state"] == "failed")
        assert states(view) == [("a-first", "done"), ("p-folder", "failed")]
        assert view["queue"]["message"].startswith("Stopped at “Read a folder”: ") and "cannot find" in view["queue"]["message"]


def test_a_queued_task_removed_from_the_list_stops_the_queue_and_can_be_removed(tmp_path: Path):
    runtime = Scripted()
    with queue_app(tmp_path, runtime, ABC) as client:
        login(client, "local-owner")
        view = post(client, "/api/v1/tasks/queue", {})
        (tmp_path / "bundled" / "b-second.md").unlink()  # deleted from the tasks folder after it was queued
        post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["state"] == "failed")
        assert view["queue"]["message"] == ("Stopped at “Task B”: it is no longer in the task list: remove it from the "
                                            "queue, then press Continue.")
        view = client.delete(f"/api/v1/tasks/queue/items/{key(view, 'b-second')}", headers=HEADERS).json()
        post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["state"] == "done")
        assert runtime.questions == ["Task: Task A", "Task: Task C"] and ids(view) == ["a-first", "c-third"]


def test_a_task_that_goes_through_every_file_hands_on_only_after_its_last_round(tmp_path: Path):
    from tests.unit.test_task_files import Digester, decks, folder_app

    class Mixed(Digester):
        async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
            if "Digest" in request.question:
                await super().run(request, emit, tools, cancelled)
                return
            self.prompts.append(request.prompt)
            await emit("text_delta", {"text": "Done."})

    folder = decks(tmp_path / "Decks").resolve()
    runtime = Mixed()
    with folder_app(tmp_path, runtime) as client:
        (tmp_path / "bundled" / "z-after.md").write_text(task("z-after", "After the decks", "2026-11-02"), encoding="utf-8")
        client.app.state.manager.services.kb_writer = lambda files, message: Published("published", "ok", "c1")
        login(client, "local-owner")
        view = post(client, "/api/v1/tasks/queue", {"paths": {"digest-decks": str(folder)}})
        assert ids(view) == ["digest-decks", "z-after"] and [o["id"] for o in view["queue"]["left_out"]] == ["deck-guide"]
        post(client, "/api/v1/tasks/queue/start")
        seen: list[str | None] = []
        view = until(client, lambda v: (seen.append(v["queue"]["items"][0]["message"]), v["queue"]["state"] == "done")[1])
        rounds = [p for p in runtime.prompts if "goes through every file" in p]
        assert len(rounds) == 2 and runtime.prompts[-1] not in rounds, "the next task only after the last round"
        assert view["queue"]["items"][0]["message"] == "All 3 files done in 2 round(s)."
        assert any(m and m.startswith("Round ") for m in seen), "the queue shows the round while it runs"


# Repeat until done -------------------------------------------------------------------------------------------------------
def repeat(max_runs: str = "") -> str:
    return task("r-review", "Review", "2026-11-02", "repeat: until_done\n" + (f"max_runs: {max_runs}\n" if max_runs else ""))


def test_repeat_front_matter():
    assert (parse(repeat()).repeat, parse(repeat()).max_runs) == (True, 5)  # type: ignore[union-attr]
    assert parse(repeat("3")).max_runs == 3 and parse(repeat("80")).max_runs == 50  # type: ignore[union-attr]
    assert parse(repeat("7  # a long review")).max_runs == 7  # type: ignore[union-attr]
    assert parse(A).repeat is False and parse(A).work()["max_runs"] is None  # type: ignore[union-attr]
    folder = task("f", "F", "2026-11-02", "input: folder\nevery_file: true\nrepeat: until_done\n")
    assert parse(folder).repeat is False, "a task that goes through every file already runs until each file is done"  # type: ignore[union-attr]
    assert parse(repeat()).work()["max_runs"] == 5  # type: ignore[union-attr]


def test_the_task_frame_asks_for_the_left_line_only_when_it_repeats():
    import datetime
    once = compose("Task: Review", [], "task", datetime.date(2026, 11, 2), task=parse(A).work())  # type: ignore[union-attr]
    again = compose("Task: Review", [], "task", datetime.date(2026, 11, 2), task={**parse(repeat()).work(), "round": 2})  # type: ignore[union-attr]
    assert "Left:" not in once and "This is run 2 of up to 5" in again and "exactly: Left: <number>" in again
    assert [left_to_do(t) for t in ("Done.\nLeft: 12", "**Left:** 3", "Left: 0", "Nothing to say.", "Left: 1,200")] == [
        12, 3, 0, None, 1200]


def test_a_task_runs_again_while_work_is_left_and_it_changes_something(tmp_path: Path):
    runtime = Scripted({"Review": ["save+left2", "save+block+left1", "save+left0"]})
    with queue_app(tmp_path, runtime, {"r-review": repeat("4")}) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/r-review/run", {})  # a single Run repeats the same way
        view = until(client, lambda v: v["tasks"][0]["round"] == 2)
        shown = view["tasks"][0]
        assert (shown["state"], shown["round"], shown["max_runs"]) == ("running", 2, 4)
        assert shown["message"] == "Run 2 of up to 4: 2 left after run 1."
        runtime.release.set()
        view = until(client, lambda v: v["tasks"][0]["state"] == "done")
        assert view["tasks"][0]["message"] == "Done in 3 runs: nothing left."
        assert runtime.questions == ["Task: Review", "Task: Review (run 2)", "Task: Review (run 3)"]
        assert "This is run 3 of up to 4" in runtime.prompts[2] and "Review done.\n\nLeft: 1" in runtime.prompts[2]
        conversation = client.get(f"/api/v1/conversations/{view['tasks'][0]['conversation_id']}").json()
        assert len(conversation["runs"]) == 3, "fresh runs in the same conversation"


def test_a_run_that_changed_nothing_ends_the_repeats(tmp_path: Path):
    runtime = Scripted({"Review": ["save+left5", "left4"]})
    with queue_app(tmp_path, runtime, {"r-review": repeat()}) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/r-review/run", {})
        view = until(client, lambda v: v["tasks"][0]["state"] == "done")
        assert view["tasks"][0]["message"] == "Run 2 changed nothing with 4 left, so Wizard did not run it again."
        assert len(runtime.questions) == 2


def test_repeats_end_at_max_runs_and_without_a_left_line(tmp_path: Path):
    runtime = Scripted({"Review": ["save+left9"]})
    with queue_app(tmp_path, runtime, {"r-review": repeat("3")}) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/r-review/run", {})
        view = until(client, lambda v: v["tasks"][0]["state"] == "done")
        assert view["tasks"][0]["message"] == "Ran 3 times, its limit, with 9 left: run it again to go on."
        assert len(runtime.questions) == 3
        runtime.plan["Review"] = ["save"]
        post(client, "/api/v1/tasks/r-review/run", {})
        view = until(client, lambda v: v["tasks"][0]["state"] == "done" and len(runtime.questions) == 4)
        assert view["tasks"][0]["message"] == "Done in 1 run (the last run did not say what is left)."


def test_the_queue_moves_on_after_a_repeating_task_ends_and_stops_when_a_repeat_fails(tmp_path: Path):
    runtime = Scripted({"Review": ["save+left1", "save+left0"], "Task B": ["ok"]})
    with queue_app(tmp_path, runtime, {"r-review": repeat(), "b-second": B}) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/queue", {})
        post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["state"] == "done")
        assert runtime.questions == ["Task: Task B", "Task: Review", "Task: Review (run 2)"]
        runtime.plan["Review"] = ["save+left3", "fail"]  # run 2 fails, is tried once more, and fails again
        runtime.questions.clear()
        view = post(client, "/api/v1/tasks/queue", {"ids": ["r-review", "b-second"]})
        view = client.post(f"/api/v1/tasks/queue/items/{key(view, 'r-review')}/move", json={"by": -1}, headers=HEADERS).json()
        post(client, "/api/v1/tasks/queue/start")
        view = until(client, lambda v: v["queue"]["state"] == "failed")
        assert view["queue"]["message"] == "Stopped at “Review”, which failed: Run 3 failed again: Gemini's quota is used up."
        assert states(view) == [("r-review", "failed"), ("b-second", "waiting")]


def test_a_failed_run_is_tried_once_more_and_the_task_goes_on(tmp_path: Path):
    """Owner, 2 Nov 2026: \"the task is not retrying by itself\": a run that fails is tried once more."""
    runtime = Scripted({"Review": ["save+left3", "fail", "block+save+left0"]})
    with queue_app(tmp_path, runtime, {"r-review": repeat()}) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/r-review/run", {})
        view = until(client, lambda v: v["tasks"][0]["round"] == 3)
        assert view["tasks"][0]["message"] == "Run 3 of up to 5: run 2 failed, so Wizard tries once more."
        runtime.release.set()
        view = until(client, lambda v: v["tasks"][0]["state"] == "done")
        assert view["tasks"][0]["message"] == "Done in 3 runs: nothing left." and len(runtime.questions) == 3


# Restarts ------------------------------------------------------------------------------------------------------------------
def test_a_restart_interrupts_the_queue_and_continue_goes_on_from_that_task(tmp_path: Path):
    runtime = Scripted({"Task B": ["block"]})
    with queue_app(tmp_path, runtime, ABC) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/queue", {})
        post(client, "/api/v1/tasks/queue/start")
        until(client, lambda v: len(runtime.questions) == 2)
        assert client.app.state.manager.busy()
    # The service stopped (an update, a new knowledge base): the run was cut off, not stopped by anyone.
    again = Scripted()
    with queue_app(tmp_path, again, ABC) as client:
        login(client, "local-owner")
        view = client.get("/api/v1/tasks").json()
        assert view["queue"]["state"] == "interrupted" and states(view) == [
            ("a-first", "done"), ("b-second", "interrupted"), ("c-third", "waiting")]
        assert view["queue"]["message"] == ("Interrupted at “Task B”: Wizard restarted before it finished. Press Continue to "
                                            "run it again and go on.")
        post(client, "/api/v1/tasks/queue/start")
        until(client, lambda v: v["queue"]["state"] == "done")
        assert again.questions == ["Task: Task B", "Task: Task C"]


def test_a_queue_left_running_by_a_crash_is_interrupted(tmp_path: Path):
    runtime = Scripted({"Task A": ["block"]})
    with queue_app(tmp_path, runtime, ABC) as client:
        login(client, "local-owner")
        post(client, "/api/v1/tasks/queue", {})
        post(client, "/api/v1/tasks/queue/start")
        until(client, lambda v: len(runtime.questions) == 1)
        crashed = (tmp_path / "var" / "tasks" / "queues.json").read_text(encoding="utf-8")
    assert json.loads(crashed)["local-owner"]["state"] == "running"
    (tmp_path / "var" / "tasks" / "queues.json").write_text(crashed, encoding="utf-8")  # the process died mid-run
    with queue_app(tmp_path, Scripted(), ABC) as client:
        login(client, "local-owner")
        view = client.get("/api/v1/tasks").json()
        assert view["queue"]["state"] == "interrupted" and view["queue"]["items"][0]["state"] == "interrupted"
        assert view["queue"]["message"].startswith("Interrupted at “Task A”") and not client.app.state.manager.busy()


def test_a_running_queue_keeps_the_desktop_service_from_restarting(tmp_path: Path):
    from tests.unit.test_desktop import NOTE as KB_NOTE
    from tests.unit.test_desktop import FakeGitHub, desktop_app, kb

    app = desktop_app(tmp_path)
    asked: list[str] = []
    with TestClient(app) as client:
        login(client, "local-owner")
        knowledge_sync.sync(kb(), app.state.settings.data_dir,
                            transport=httpx.MockTransport(FakeGitHub("a" * 40, {"knowledge/company/overview.md": KB_NOTE})))
        app.state.request_restart = lambda: asked.append("restart")
        queue = app.state.task_queues.queue("local-owner")
        queue["state"] = "running"  # between two tasks: no run is active
        assert not app.state.manager.active and app.state.manager.busy()
        assert app.state.restart_if_idle(0) is False and asked == []
        queue["state"] = "done"
        assert app.state.restart_if_idle(0) is True and asked == ["restart"]


def test_the_queue_belongs_to_the_person_at_their_own_pc(tmp_path: Path):
    with queue_app(tmp_path, Scripted(), ABC, install=False) as client:
        login(client, "u-ceo")
        assert client.post("/api/v1/tasks/queue", json={}, headers=HEADERS).status_code == 403
        assert client.post("/api/v1/tasks/queue/start", headers=HEADERS).status_code == 403
        assert client.put("/api/v1/tasks/selection", json={"ids": []}, headers=HEADERS).status_code == 403
        assert client.post("/api/v1/tasks/a-first/queue", json={}, headers=HEADERS).status_code == 403
