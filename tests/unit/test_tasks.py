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
from wizard_connectors.content import validate_knowledge
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
def kb_context(tmp_path: Path, saved: list[tuple[dict[str, bytes], str]] | None,
               notes: dict[str, str] | None = None) -> tuple[Any, ToolContext]:
    content = tmp_path / "content"
    for path, text in {"knowledge/metrics/market-share.md": NOTE, **(notes or {})}.items():
        (content / path).parent.mkdir(parents=True, exist_ok=True)
        (content / path).write_text(text, encoding="utf-8")
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


# Moving, renaming and removing notes (owner, 2 Nov 2026: notes about dashboards were filed under datasets/) ----------
def kb_note(note_id: str, kind: str, body: str, related: str = "", status: str = "DRAFT_UNSIGNED") -> str:
    return (f"---\nid: {note_id}\ntitle: {note_id.replace('-', ' ').capitalize()}\ntype: {kind}\nstatus: {status}\n"
            f"owner: TBD - sales operations\ntags: [sell-in, weekly, dashboard, market]\nsummary: An invented {kind} note.\n"
            f"related: [{related}]\nupdated: 2026-11-02\n---\n{body}\n")


MISFILED = "knowledge/datasets/weekly-sell-in-dashboard.md"
MOVED = "knowledge/dashboards/weekly-sell-in-dashboard.md"
RENAMED = "knowledge/dashboards/sell-in-weekly-dashboard.md"
REVIEWED = {
    MISFILED: kb_note("weekly-sell-in-dashboard", "dataset", "The weekly sell-in dashboard shows sell-in by market and "
                      "week.", related="sell-in"),
    "knowledge/metrics/sell-in.md": kb_note("sell-in", "metric", "Sell-in is units shipped to partners. The "
                                            "weekly-sell-in-dashboard note says how the dashboard shows it.",
                                            related="weekly-sell-in-dashboard, market-share"),
    "knowledge/datasets/source-order.md": kb_note("source-order", "dataset", "Read the cube first, then the views."),
    "knowledge/company/fiscal-calendar.md": kb_note("fiscal-calendar", "concept", "The fiscal year starts in January.",
                                                    status="SIGNED"),
}


def test_a_task_moves_a_note_to_another_area_and_the_rest_of_the_run_sees_it(tmp_path: Path):
    saved: list[tuple[dict[str, bytes], str]] = []
    registry, context = kb_context(tmp_path, saved, REVIEWED)
    result = registry.execute("wizard_kb_save_notes", {"moves": [{"id": "weekly-sell-in-dashboard", "to": MOVED}],
                                                       "message": "Dashboards have their own area"}, context)
    assert result.ok, result.error_message
    assert result.data["moved"] == [{"id": "weekly-sell-in-dashboard", "from": MISFILED, "to": MOVED}]
    assert saved == [({f"wizard/{MISFILED}": None, f"wizard/{MOVED}": REVIEWED[MISFILED].encode()},
                      "Wizard task: Dashboards have their own area")], "one commit: the old file goes, the same file lands"
    assert not result.data["links_updated"], "the id stays, so no link changes"
    knowledge = context.services.knowledge
    assert knowledge.by_id["weekly-sell-in-dashboard"].area == "dashboards"
    assert [n.id for n in knowledge.index("datasets")] == ["source-order"] and len(knowledge.notes) == 5
    source = registry.execute("wizard_kb_note_source", {"ids": ["weekly-sell-in-dashboard"]}, context).data["notes"][0]
    assert source == {"id": "weekly-sell-in-dashboard", "path": MOVED, "text": REVIEWED[MISFILED]}
    browse = registry.execute("wizard_browse_knowledge", {"area": "dashboards"}, context)
    assert "weekly-sell-in-dashboard" in str(browse.data)
    # A move can change the note's text in the same commit: given whole at its new path.
    entity = REVIEWED["knowledge/datasets/source-order.md"].replace("type: dataset", "type: entity")
    result = registry.execute("wizard_kb_save_notes", {
        "moves": [{"id": "source-order", "to": "knowledge/dashboards/source-order.md"}],
        "notes": [{"path": "knowledge/dashboards/source-order.md", "text": entity}], "message": "Not a dataset"}, context)
    assert result.ok, result.error_message
    assert saved[1][0] == {"wizard/knowledge/datasets/source-order.md": None,
                           "wizard/knowledge/dashboards/source-order.md": entity.encode()}
    assert context.services.knowledge.by_id["source-order"].type == "entity"


def test_a_rename_changes_the_id_and_every_link_to_it_in_the_same_commit(tmp_path: Path):
    saved: list[tuple[dict[str, bytes], str]] = []
    registry, context = kb_context(tmp_path, saved, REVIEWED)
    result = registry.execute("wizard_kb_save_notes", {"moves": [{"id": "weekly-sell-in-dashboard", "to": RENAMED}],
                                                       "message": "Name the dashboard as people say it"}, context)
    assert result.ok, result.error_message
    assert result.data["moved"] == [{"id": "sell-in-weekly-dashboard", "from": MISFILED, "to": RENAMED,
                                     "was": "weekly-sell-in-dashboard"}]
    assert result.data["links_updated"] == ["knowledge/metrics/sell-in.md"]
    (files, _), = saved
    assert files[f"wizard/{MISFILED}"] is None
    assert files[f"wizard/{RENAMED}"] == REVIEWED[MISFILED].replace("id: weekly-sell-in-dashboard",
                                                                    "id: sell-in-weekly-dashboard").encode()
    assert files["wizard/knowledge/metrics/sell-in.md"] == REVIEWED["knowledge/metrics/sell-in.md"].replace(
        "related: [weekly-sell-in-dashboard, market-share]", "related: [sell-in-weekly-dashboard, market-share]").encode()
    assert len(files) == 3, "nothing else is touched"
    assert any("sell-in.md: its text names weekly-sell-in-dashboard" in w for w in result.data["warnings"]), \
        "a mention in the text is Gemini's to change"
    assert not any("does not exist" in w for w in result.data["warnings"]), "sell-in exists, though checked alone"
    knowledge = context.services.knowledge
    assert "weekly-sell-in-dashboard" not in knowledge.by_id and knowledge.by_id["sell-in-weekly-dashboard"].path == RENAMED
    assert knowledge.by_id["sell-in"].related == ("sell-in-weekly-dashboard", "market-share")


def test_a_task_removes_a_note_and_the_links_to_it_in_one_commit(tmp_path: Path):
    saved: list[tuple[dict[str, bytes], str]] = []
    registry, context = kb_context(tmp_path, saved, REVIEWED)
    result = registry.execute("wizard_kb_save_notes", {"removes": ["source-order"],
                                                       "message": "A note that only set a source order"}, context)
    assert result.ok and result.data["removed"] == ["knowledge/datasets/source-order.md"], result.error_message
    assert saved[0][0] == {"wizard/knowledge/datasets/source-order.md": None}
    assert "source-order" not in context.services.knowledge.by_id
    unlinked = REVIEWED["knowledge/metrics/sell-in.md"].replace("weekly-sell-in-dashboard, ", "")
    result = registry.execute("wizard_kb_save_notes", {
        "removes": ["weekly-sell-in-dashboard"], "notes": [{"path": "knowledge/metrics/sell-in.md", "text": unlinked}],
        "message": "Remove the dashboard note and its link"}, context)
    assert result.ok, result.error_message
    assert saved[1][0] == {f"wizard/{MISFILED}": None, "wizard/knowledge/metrics/sell-in.md": unlinked.encode()}
    knowledge = context.services.knowledge
    assert "weekly-sell-in-dashboard" not in knowledge.by_id and knowledge.by_id["sell-in"].related == ("market-share",)
    assert sorted(knowledge.saved) == ["knowledge/metrics/sell-in.md"], "a removed file is not read as saved"


SIGNED_LINK = {"knowledge/glossary/sales-terms.md": kb_note("sales-terms", "glossary", "- **Sell-in**: shipments.",
                                                           related="weekly-sell-in-dashboard", status="SIGNED")}


@pytest.mark.parametrize("arguments, extra, code, expected", [
    ({"moves": [{"id": "fiscal-calendar", "to": "knowledge/processes/fiscal-calendar.md"}]}, {}, "refused", "is SIGNED"),
    ({"removes": ["fiscal-calendar"]}, {}, "refused", "is SIGNED"),
    ({"notes": [{"path": "knowledge/company/fiscal-calendar.md",
                 "text": REVIEWED["knowledge/company/fiscal-calendar.md"].replace("January", "April")}]}, {},
     "refused", "is SIGNED"),
    ({"moves": [{"id": "weekly-sell-in-dashboard", "to": RENAMED}]}, SIGNED_LINK, "refused",
     "sales-terms.md is SIGNED"),
    ({"removes": ["weekly-sell-in-dashboard"]}, {}, "refused",
     "knowledge/metrics/sell-in.md names weekly-sell-in-dashboard in related"),
    ({"moves": [{"id": "weekly-sell-in-dashboard", "to": MOVED}],
      "notes": [{"path": MOVED, "text": REVIEWED[MISFILED].replace("type: dataset", "type: dashboard")}]}, {},
     "invalid_note", "type 'dashboard' is not one of"),
    ({"moves": [{"id": "weekly-sell-in-dashboard", "to": "knowledge/metrics/sell-in.md"}]}, {}, "refused",
     "is already the note sell-in"),
    ({"moves": [{"id": "weekly-sell-in-dashboard", "to": MOVED}],
      "notes": [{"path": MISFILED, "text": REVIEWED[MISFILED]}]}, {}, "refused", "takes this file away"),
    ({"removes": ["no-such-note"]}, {}, "refused", "no note has this id"),
], ids=["move-signed", "remove-signed", "replace-signed", "rename-linked-from-signed", "remove-still-linked",
        "validator-error", "move-onto-another-note", "save-at-a-path-moved-away", "unknown-id"])
def test_a_move_rename_or_remove_that_breaks_a_rule_commits_nothing(tmp_path: Path, arguments: dict[str, Any],
                                                                   extra: dict[str, str], code: str, expected: str):
    saved: list[tuple[dict[str, bytes], str]] = []
    registry, context = kb_context(tmp_path, saved, {**REVIEWED, **extra})
    before = context.services.knowledge
    result = registry.execute("wizard_kb_save_notes", {**arguments, "message": "Try it"}, context)
    assert (result.error_code, saved) == (code, []), result.error_message
    assert expected in (result.error_message or "") and "Nothing was saved" in (result.error_message or "")
    assert context.services.knowledge is before, "the run's knowledge base is unchanged"


def test_a_save_needs_something_to_save(tmp_path: Path):
    registry, context = kb_context(tmp_path, [])
    result = registry.execute("wizard_kb_save_notes", {"message": "Nothing at all"}, context)
    assert result.error_code == "invalid_arguments" and "notes, moves or removes" in (result.error_message or "")


def test_the_writer_removes_files_in_the_same_commit_and_only_files_still_there(monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from wizard_api.app import map_writer
    from wizard_documents import kb
    on_branch = {"wizard/knowledge/datasets/a.md", "wizard/knowledge/metrics/b.md"}
    made: list[dict[str, bytes | None]] = []

    def update_branch(repo: str, token: str, branch: str, make: Any, **kw: Any) -> str:
        made.append(make(on_branch, lambda path: None))
        return "c2"
    monkeypatch.setattr(kb, "update_branch", update_branch)
    monkeypatch.setattr(kb, "write_files", lambda *a, **k: pytest.fail("a commit that removes goes through update_branch"))
    write = map_writer(SimpleNamespace(kb_repo="acme/kb", kb_write_token="t", kb_ref="main", github_proxy=None))  # type: ignore[arg-type]
    files = {"wizard/knowledge/datasets/a.md": None, "wizard/knowledge/dashboards/a.md": b"---\nid: a\n---\n"}
    assert write(files, "Move a").commit == "c2" and made == [files]
    gone = write({"wizard/knowledge/datasets/x.md": None}, "Remove x")
    assert gone.outcome == "failed" and "no longer in acme/kb" in gone.message and len(made) == 1


DASHBOARD = """---
id: weekly-sell-in-dashboard
title: Weekly sell-in dashboard
type: entity
status: DRAFT_UNSIGNED
owner: TBD - Sales operations (ask the user)
summary: The HTML dashboard of weekly sell-in by market and channel: what it shows, its business logic and its data.
aliases: [weekly-sell-in, sell-in dashboard, weekly sell-in report]
tags: [dashboard, sell-in, weekly, market, channel, shipments, partners, html]
related: [sell-in, bi-sell-in-weekly]
sources: [S-1a2b3c4d]
updated: 2026-11-02
---
The weekly sell-in dashboard shows units shipped to partners by market and channel, week by week and year to date. It
is refreshed every Monday. It excludes demo units, so its totals are lower than the raw table's [S-1a2b3c4d].

## What it shows
| Measure | Breakdowns | Periods |
|---|---|---|
| Sell-in units | market, channel | week, year to date |

## Business logic
The weekly sell-in dashboard counts actual shipments only (`"Unit/Value"` = 'Units', `"Version"` = 'Actual') and leaves
out demo units (`channel` <> 'DEMO') [S-1a2b3c4d]. Wizard can reproduce it in SQL from bi-sell-in-weekly with those
filters. UNKNOWN: whether returns are netted (ask: Sales operations).

## Where the data comes from
The weekly sell-in dashboard reads bi-sell-in-weekly [S-1a2b3c4d].

## Refresh and as-of
The weekly sell-in dashboard is refreshed every Monday; its header shows the last week included [S-1a2b3c4d].

## Who maintains it
Sales operations maintains the weekly sell-in dashboard.

## File
`sales/weekly-sell-in.html` in the dashboards folder.

## Questions this note answers
- What does the weekly sell-in dashboard leave out?
- Where does the sell-in dashboard get its data?
- How fresh is the weekly sell-in dashboard?

## Open questions
- UNKNOWN: whether returns are netted (ask: Sales operations)
"""


def test_a_dashboard_note_written_to_the_standard_passes_the_validator(tmp_path: Path):
    standard = (ROOT / "templates" / "content" / "schema" / "knowledge-standard.md").read_text(encoding="utf-8")
    assert "| `dashboards/` |" in standard and "## 13. Dashboard notes" in standard
    knowledge = tmp_path / "knowledge"
    (knowledge / "dashboards").mkdir(parents=True)
    (knowledge / "dashboards" / "weekly-sell-in-dashboard.md").write_text(DASHBOARD, encoding="utf-8")
    problems = validate_knowledge(knowledge, tmp_path)
    assert [p for p in problems if p.level == "error"] == []
    saved: list[tuple[dict[str, bytes], str]] = []
    registry, context = kb_context(tmp_path, saved)
    result = registry.execute("wizard_kb_save_notes", {"notes": [{"path": MOVED, "text": DASHBOARD}],
                                                       "message": "The weekly sell-in dashboard"}, context)
    assert result.ok and list(saved[0][0]) == [f"wizard/{MOVED}"], result.error_message
    assert context.services.knowledge.by_id["weekly-sell-in-dashboard"].area == "dashboards"


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


class Mover(Worker):
    """A question that tries to move and remove notes."""

    async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
        ok, text = await tools.call("wizard_kb_save_notes", {"moves": [{"id": "market-share", "to": MOVED}],
                                                             "removes": ["sell-in"], "message": "Tidy the areas"})
        self.results.append((request.kind, ok, text))
        await emit("text_delta", {"text": "Answered."})


def test_a_question_never_moves_or_removes_a_note(tmp_path: Path):
    runtime = Mover()
    saved: list[tuple[dict[str, bytes], str]] = []
    with task_app(tmp_path, runtime) as client:
        services = client.app.state.manager.services
        services.kb_writer = lambda files, message: (saved.append((files, message)), Published("published", "ok", "c1"))[1]
        login(client, "local-owner")
        from tests.helpers import ask
        ask(client, "Move the dashboard notes to their own area")
        kind, ok, text = runtime.results[-1]
        assert kind == "ask" and not ok and "only in a task" in text and saved == []


def test_tasks_belong_to_the_person_at_their_own_pc(tmp_path: Path):
    with task_app(tmp_path, Worker(), install=False) as client:
        login(client, "u-ceo")
        assert client.get("/api/v1/tasks").status_code == 403
        assert client.post("/api/v1/tasks/tidy-notes/run", headers=HEADERS).status_code == 403


def test_the_old_task_files_are_cleaned_from_installs():
    setup = (ROOT / "setup.ps1").read_text(encoding="utf-8")
    assert r"workpc\tasks" not in setup and r"commands\wizard\tasks.toml" in setup and "Remove-Item" in setup
