"""Tasks (owner, 31 Oct 2026): instructions read from the Wizard repository's tasks/ folder at runtime, run from
Settings → Tasks as Gemini runs that save notes to the company knowledge base, and nowhere else."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, MemoryRecorder, login, make_settings

from wizard_agent.prompting import compose
from wizard_api.app import create_app
from wizard_api.tasks import LISTING, TaskBoard, parse
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.paths import ROOT
from wizard_connectors.portal_map import Published
from wizard_connectors.tools import ToolContext, build_registry, build_services

TASK = """---
id: tidy-notes
title: Tidy the notes
summary: One line.
added: 2026-10-31
---
Read every metric note and fix its summary.
"""
NOTE = """---
id: market-share
title: Market share and share gain
status: DRAFT_UNSIGNED
owner: TBD - market intelligence
tags: [share, market share]
summary: Volume and value share; share gain in percentage points.
---
Volume share is brand units over all smartphone units.
"""


def test_every_task_in_the_repository_is_well_formed():
    files = [p for p in (ROOT / "tasks").glob("*.md") if p.name != "README.md"]
    assert files, "the first task ships with this version"
    for path in files:
        task = parse(path.read_text(encoding="utf-8"))
        assert task and task.id == path.stem and task.title and task.summary and task.added, path.name
    assert not (ROOT / "workpc" / "tasks").exists(), "the numbered Gemini CLI tasks are retired"


def github(files: dict[str, str], calls: list[str], fail: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if fail:
            raise httpx.ConnectError("no route", request=request)
        if str(request.url) == LISTING:
            if request.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304)
            return httpx.Response(200, headers={"etag": '"v1"'}, json=[
                {"type": "file", "name": name, "sha": f"sha-{name}", "url": f"https://api.github.com/x/{name}"}
                for name in [*files, "README.md"]])
        return httpx.Response(200, text=files[str(request.url).rsplit("/", 1)[1]])
    return httpx.MockTransport(handler)


def test_tasks_come_from_github_and_fall_back_to_the_bundled_copy(tmp_path: Path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "old-task.md").write_text(TASK.replace("tidy-notes", "old-task"), encoding="utf-8")
    calls: list[str] = []
    board = TaskBoard(tmp_path / "data", bundled, transport=github({}, calls, fail=True))
    cache = board.refresh(force=True)
    assert [t.id for t in board.tasks(cache)[0]] == ["old-task"] and board.tasks(cache)[1] == "bundled"
    assert "no route" in cache["message"], "says why GitHub was not read"
    board.transport = github({"tidy-notes.md": TASK}, calls)
    cache = board.refresh(force=True)
    assert [t.id for t in board.tasks(cache)[0]] == ["tidy-notes"], "GitHub's list replaces the bundled one"
    assert not any(c.endswith("README.md") for c in calls), "the folder's README is not a task"
    calls.clear()
    board.refresh(force=True)
    assert calls == [LISTING], "an unchanged folder costs one conditional request"
    assert board.refresh()["checked"] and calls == [LISTING], "and is not asked again within minutes"
    board.transport = github({}, calls, fail=True)
    assert [t.id for t in board.tasks(board.refresh(force=True))[0]] == ["tidy-notes"], "the last good list stays"


def test_the_task_request_carries_the_instructions():
    task = parse(TASK)
    assert task
    prompt = compose("Task: Tidy the notes", [], "task", __import__("datetime").date(2026, 10, 31),
                     task={"title": task.title, "body": task.body})
    assert '"Tidy the notes"' in prompt and "fix its summary" in prompt and "wizard_kb_save_notes" in prompt


# The knowledge-base tools ------------------------------------------------------------------------------------------
def kb_context(tmp_path: Path, saved: list[tuple[dict[str, bytes], str]] | None) -> tuple[Any, ToolContext]:
    content = tmp_path / "content"
    (content / "knowledge" / "metrics").mkdir(parents=True)
    (content / "knowledge" / "metrics" / "market-share.md").write_text(NOTE, encoding="utf-8")
    services = build_services(knowledge=content / "knowledge")
    if saved is not None:
        services.kb_writer = lambda files, message: (saved.append((files, message)), Published("published", "ok", "c1"))[1]
        services.kb_prefix = "wizard"
    identity = Identity(id="owner", email="owner@example.com", name="Owner", role="Owner",
                        entitlements={"asap": SystemRights(reports=["*"], markets=["*"])})
    return build_registry(services), ToolContext(identity=identity, run_id="r", recorder=MemoryRecorder(), services=services)


def test_a_task_reads_a_note_as_a_file_and_saves_checked_notes_to_the_knowledge_base(tmp_path: Path):
    saved: list[tuple[dict[str, bytes], str]] = []
    registry, context = kb_context(tmp_path, saved)
    source = registry.execute("wizard_kb_note_source", {"ids": ["market-share"]}, context).data["notes"][0]
    assert source["path"] == "knowledge/metrics/market-share.md" and source["text"].startswith("---\nid: market-share")
    assert "Knowledge standard" in registry.execute("wizard_kb_standard", {}, context).data["standard"]
    changed = source["text"].replace("Volume share is", "Volume share (%) is")
    result = registry.execute("wizard_kb_save_notes", {"notes": [{"path": source["path"], "text": changed}],
                                                "message": "Units in the share definition"}, context)
    assert result.ok and result.data["outcome"] == "published", result.error_message
    files, message = saved[0]
    assert files == {"wizard/knowledge/metrics/market-share.md": changed.encode()} and message.startswith("Wizard task:")


@pytest.mark.parametrize("path, text, expected", [
    ("knowledge/metrics/other.md", NOTE, "id must be the file name"),
    ("knowledge/glossary/market-share.md", NOTE, "already the note knowledge/metrics/market-share.md"),
    ("knowledge/metrics/new-note.md", "no front matter at all here", "missing front matter"),
    ("knowledge/metrics/new-note.md", NOTE.replace("market-share", "new-note") + "\npassword = 'hunter22secret'\n", "credentials"),
])
def test_a_note_that_breaks_the_standard_saves_nothing(tmp_path: Path, path: str, text: str, expected: str):
    saved: list[tuple[dict[str, bytes], str]] = []
    registry, context = kb_context(tmp_path, saved)
    result = registry.execute("wizard_kb_save_notes", {"notes": [{"path": path, "text": text}], "message": "Try it"}, context)
    assert result.error_code == "invalid_note" and expected in (result.error_message or "") and saved == []


def test_without_a_write_token_a_task_saves_nothing(tmp_path: Path):
    registry, context = kb_context(tmp_path, None)
    result = registry.execute("wizard_kb_save_notes", {"notes": [{"path": "knowledge/metrics/market-share.md", "text": NOTE}],
                                                "message": "Try it"}, context)
    assert result.error_code == "no_write_token" and "Settings" in (result.error_message or "")


# Settings → Tasks through the API, with a scripted Gemini -------------------------------------------------------------
class Worker:
    """A task run saves a note; a question tries to and is refused."""
    kind = "code-assist"
    model = "gemini-3.8-flash"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.results: list[tuple[str, bool, str]] = []

    def label(self) -> str:
        return "Task test runtime"

    async def readiness(self, home: Path, email: str) -> dict[str, Any]:
        return {"ready": True, "reason": None}

    async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
        self.prompts.append(request.prompt)
        ok, text = await tools.call("wizard_kb_save_notes", {"notes": [{"path": "knowledge/metrics/new-note.md",
                                                                 "text": NOTE.replace("market-share", "new-note")}],
                                                      "message": "A new note"})
        self.results.append((request.kind, ok, text))
        await asyncio.sleep(0)
        await emit("text_delta", {"text": "Saved new-note." if ok else "Answered."})


def task_app(tmp_path: Path, runtime: Worker, install: bool = True) -> TestClient:
    settings = make_settings(tmp_path, WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = install
    app = create_app(settings, runtime=runtime)  # type: ignore[arg-type]
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "tidy-notes.md").write_text(TASK, encoding="utf-8")
    board: TaskBoard = app.state.task_board
    board.bundled, board.transport = bundled, github({}, [], fail=True)
    return TestClient(app)


def wait(client: TestClient, done: Any, timeout: float = 20) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get("/api/v1/tasks").json()
        if done(view):
            return dict(view)
        time.sleep(0.05)
    raise AssertionError(f"the task did not get there: {view}")


def test_a_task_runs_from_settings_and_only_a_task_may_save_to_the_knowledge_base(tmp_path: Path):
    runtime = Worker()
    saved: list[tuple[dict[str, bytes], str]] = []
    with task_app(tmp_path, runtime) as client:
        services = client.app.state.manager.services
        services.kb_writer = lambda files, message: (saved.append((files, message)), Published("published", "ok", "c1"))[1]
        login(client, "local-owner")
        listed = client.get("/api/v1/tasks?refresh=true").json()
        assert listed["source"] == "bundled" and listed["can_save"] is True
        assert [(t["id"], t["state"]) for t in listed["tasks"]] == [("tidy-notes", "todo")]
        started = client.post("/api/v1/tasks/tidy-notes/run", headers=HEADERS)
        assert started.status_code == 200, started.text
        view = wait(client, lambda v: v["tasks"][0]["state"] == "done")
        conversation = client.get(f"/api/v1/conversations/{view['tasks'][0]['conversation_id']}").json()
        assert conversation["runs"][0]["question"] == "Task: Tidy the notes"
        assert "fix its summary" in runtime.prompts[0] and list(saved[0][0]) == ["knowledge/metrics/new-note.md"]
        assert client.post("/api/v1/tasks/nope/run", headers=HEADERS).status_code == 404
        from tests.helpers import ask
        ask(client, "Save a note for me")
        kind, ok, text = runtime.results[-1]
        assert kind == "ask" and not ok and "only in a task" in text and len(saved) == 1, "a question never writes"


def test_tasks_belong_to_the_person_at_their_own_pc(tmp_path: Path):
    with task_app(tmp_path, Worker(), install=False) as client:
        login(client, "u-ceo")
        assert client.get("/api/v1/tasks").status_code == 403
        assert client.post("/api/v1/tasks/tidy-notes/run", headers=HEADERS).status_code == 403


def test_the_old_task_files_are_cleaned_from_installs():
    setup = (ROOT / "setup.ps1").read_text(encoding="utf-8")
    assert r"workpc\tasks" not in setup and r"commands\wizard\tasks.toml" in setup and "Remove-Item" in setup
