"""Tasks that ask for a folder or file (owner, 1 Nov 2026: "a task that asks me for a folder ... digests the whole thing
and adds to the knowledge base", and one that writes how to make the company's presentations): how a presentation
looks (design.py, read from the file and through PowerPoint), the chosen folder (task_files.py), the task-file tools,
notes a task saved seen at once, and a task that goes through every file running in rounds from Settings → Tasks."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, MemoryRecorder, login, make_settings
from tests.office_files import designed_pptx, pptx
from tests.unit.test_documents import Bag, ComError, FakeSession, Items

from wizard_agent.prompting import compose
from wizard_api.app import create_app
from wizard_api.tasks import TaskBoard, parse
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.paths import ROOT
from wizard_connectors.portal_map import Published
from wizard_connectors.task_files import TaskFiles, TaskFolderError, check_path, file_id
from wizard_connectors.tools import ToolContext, build_registry, build_services
from wizard_documents.convert import convert
from wizard_documents.design import bgr, combine, office_facts, ooxml_facts, summarize, where

NOTE = """---
id: {id}
title: {title}
type: glossary
status: DRAFT_UNSIGNED
owner: TBD - strategy office
tags: [glossary, terms, planning, business]
sources: [S-1a2b3c4d]
updated: 2026-11-01
---
Terms used in planning decks.

- **GTM**: go-to-market. [S-1a2b3c4d]
"""


# How a presentation looks -----------------------------------------------------------------------------------------------
def test_a_decks_design_is_read_from_the_file_and_summarized(tmp_path: Path):
    profile = summarize(ooxml_facts(designed_pptx(tmp_path / "review.pptx")))
    assert profile["slide_size"] == {"width_cm": 33.87, "height_cm": 19.05, "aspect": "16:9"}
    assert profile["theme"]["colors"]["accent 1"] == "#1428A0" and profile["theme"]["colors"]["dark 1"] == "#000000"
    assert profile["theme"]["fonts"] == {"heading": "Company Sans Bold", "heading (East Asian)": "Company Gothic",
                                         "body": "Company Sans", "body (East Asian)": "Company Gothic"}
    assert profile["master_text_styles"]["title"] == {"font": "Company Sans Bold", "size": 28.0, "color": "#1428A0", "bold": True}
    assert profile["layouts_in_template"] == ["Title Slide", "Title and Content"]
    assert {"kind": "picture", "where": "top right", "masters_and_layouts": 1} in profile["on_every_slide"], "the logo"
    assert any(e.get("text") == "Confidential - internal use only" and e["where"] == "bottom left" for e in profile["on_every_slide"])
    assert profile["text"]["title_sizes_pt"] == [{"pt": 28.0, "share_pct": 100}]
    assert profile["text"]["colors"][0] == {"color": "#1428A0", "share_pct": 44, "theme": "accent 1"}
    assert profile["shape_fills"] == [{"color": "#1428A0", "theme": "accent 1", "shapes": 1}]
    assert profile["charts"] == {"column": 1} and profile["slides_with_table"] == 1
    assert profile["outline"] == ["1. [Title Slide] Quarterly business review", "2. [Title and Content] Sell-out grew in every market"]
    assert "Prepared by" not in json.dumps(profile), "no slide body text: titles and recurring labels only"


def test_what_many_decks_share_is_counted_once_per_deck(tmp_path: Path):
    decks = [summarize(ooxml_facts(designed_pptx(tmp_path / f"{n}.pptx", accent=accent)))
             for n, accent in enumerate(("1428A0", "1428A0", "FF0000"))]
    shared = combine(decks)
    assert shared["decks"] == 3 and shared["slide_sizes"] == [{"size": "33.87 x 19.05 cm (16:9)", "decks": 3}]
    assert {"color": "#1428A0 (accent 1)", "decks": 2} in shared["theme_colors"]
    assert {"color": "#FF0000 (accent 1)", "decks": 1} in shared["theme_colors"]
    assert shared["on_every_slide"][0]["decks"] == 3 and shared["layouts"][0] == {"layout": "Title Slide", "decks": 3, "slides": 3}
    assert shared["charts"] == {"column": 3} and shared["share_of_slides_with"] == {"chart": 50, "table": 50, "picture": 0}


def test_positions_and_com_colors():
    assert where(10_000, 0, 1000, 500, 12_000, 6_000) == "top right" and where(0, 5_000, 100, 100, 12_000, 6_000) == "bottom left"
    assert bgr(0xA02814) == "#1428A0" and bgr(-1) == "" and bgr(None) == ""


class Runs:
    def __init__(self, runs: list[Bag]):
        self._runs = runs
        self.Text = "".join(r.Text for r in runs)

    def Runs(self) -> Items:  # noqa: N802 - a method in late binding, like pywin32's
        return Items(self._runs)


def font(name: str, size: float, rgb: int, theme: int = 0, bold: int = 0) -> Bag:
    return Bag(Name=name, Size=size, Bold=bold, Color=Bag(RGB=rgb, ObjectThemeColor=theme))


def test_a_protected_deck_is_read_through_powerpoint():
    accent = 0xA02814  # #1428A0 as COM writes it (blue, green, red)
    theme = Bag(ThemeColorScheme=Bag(Colors=lambda i: Bag(RGB=accent if i == 5 else 0)),
                ThemeFontScheme=Bag(MajorFont=Bag(Item=lambda i: Bag(Name="Company Sans Bold" if i == 1 else "Company Gothic")),
                                    MinorFont=Bag(Item=lambda i: Bag(Name="Company Sans"))))
    logo = Bag(Type=13, Left=860, Top=10, Width=80, Height=30)
    label = Bag(Type=17, Left=20, Top=510, Width=200, Height=20, HasTextFrame=-1,
                TextFrame=Bag(HasText=-1, TextRange=Bag(Text="Confidential")))
    master = Bag(Theme=theme, Design=Bag(Name="Company Theme"), Shapes=Items([logo, label]),
                 TextStyles=lambda kind: Bag(Levels=lambda level: Bag(Font=font("Company Sans Bold", 28, accent, 5, -1))))
    layout = Bag(Name="Title and Content", Shapes=Items([]))
    title = Bag(Type=14, PlaceholderFormat=Bag(Type=1, ContainedType=0), HasTextFrame=-1,
                TextFrame=Bag(HasText=-1, TextRange=Runs([Bag(Text="Sell-out grew", Font=font("Company Sans Bold", 28, 0, 5, -1))])))
    body = Bag(Type=1, Fill=Bag(Visible=-1, ForeColor=Bag(RGB=accent, ObjectThemeColor=0)), HasTextFrame=-1,
               TextFrame=Bag(HasText=-1, TextRange=Runs([Bag(Text="Mid-range led", Font=font("Company Sans", 14, 0x333333))])))
    chart = Bag(Type=3, HasChart=-1, Chart=Bag(ChartType=51))
    shapes = Items([title, body, chart])
    shapes.HasTitle, shapes.Title = -1, Bag(TextFrame=Bag(HasText=-1, TextRange=Bag(Text="Sell-out grew")))  # type: ignore[attr-defined]
    slide = Bag(SlideIndex=1, Shapes=shapes, CustomLayout=layout, SlideShowTransition=Bag(Hidden=0))
    presentation = Bag(PageSetup=Bag(SlideWidth=960, SlideHeight=540), SlideMaster=master, Slides=Items([slide]),
                       Designs=Items([Bag(SlideMaster=Bag(CustomLayouts=Items([layout])))]), Close=lambda: None)
    opened: list[dict[str, Any]] = []
    app = Bag(Presentations=Bag(Open=lambda path, **options: opened.append(options) or presentation))
    profile = summarize(office_facts(FakeSession({"powerpoint": app}), Path("deck.pptx")))  # type: ignore[arg-type]
    assert opened == [{"ReadOnly": True, "Untitled": False, "WithWindow": False}], "read-only, no window"
    assert profile["read_with"].startswith("PowerPoint") and profile["slide_size"]["aspect"] == "16:9"
    assert profile["theme"]["colors"]["accent 1"] == "#1428A0" and profile["theme"]["fonts"]["heading"] == "Company Sans Bold"
    assert profile["master_text_styles"]["title"]["color"] == "#1428A0", "a theme color is named by the theme's value"
    assert {"kind": "picture", "where": "top right", "masters_and_layouts": 1} in profile["on_every_slide"]
    assert {"kind": "text", "where": "bottom left", "text": "Confidential", "masters_and_layouts": 1} in profile["on_every_slide"]
    assert profile["text"]["title_sizes_pt"] == [{"pt": 28.0, "share_pct": 100}]
    assert {"color": "#333333", "share_pct": 50} in profile["text"]["colors"]
    assert profile["shape_fills"] == [{"color": "#1428A0", "theme": "accent 1", "shapes": 1}]
    assert profile["charts"] == {"column": 1} and profile["outline"] == ["1. [Title and Content] Sell-out grew"]


def test_powerpoint_errors_are_a_clear_failure():
    def refuse(path: str, **options: Any) -> Any:
        raise ComError("The file is protected")
    with pytest.raises(Exception, match="protected"):
        office_facts(FakeSession({"powerpoint": Bag(Presentations=Bag(Open=refuse))}), Path("deck.pptx"))  # type: ignore[arg-type]


def test_the_design_command_prints_one_line_per_deck(tmp_path: Path):
    deck = designed_pptx(tmp_path / "a.pptx")
    broken = tmp_path / "b.pptx"
    broken.write_bytes(b"NASCA protected")
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "wizard_docs.py"), "design", str(deck), str(broken),
                             "--office", "never"], capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert [line["status"] for line in lines] == ["ok", "failed"] and result.returncode == 0
    assert lines[0]["profile"]["theme"]["name"] == "Company Theme" and "PowerPoint" in lines[1]["note"]


# The folder the person chose ----------------------------------------------------------------------------------------------
class FakeDocuments:
    """The converter process, in this process: plain files only (what CI can read)."""

    def __init__(self) -> None:
        self.converted: list[str] = []
        self.designed: list[str] = []

    def convert(self, source: Path, out: Path) -> dict[str, Any]:
        self.converted.append(source.name)
        result = convert(source, out / "assets", out / "attachments", office="never")
        out.mkdir(parents=True, exist_ok=True)
        (out / "text.md").write_text(result.text, encoding="utf-8")
        return {"status": "ok", "method": result.method, "chars": len(result.text), "parts": result.parts, "notes": result.notes}

    def design(self, sources: list[Path]) -> list[dict[str, Any]]:
        self.designed += [s.name for s in sources]
        return [{"status": "ok", "profile": summarize(ooxml_facts(s))} for s in sources]

    def combine(self, profiles: list[dict[str, Any]]) -> dict[str, Any]:
        return combine(profiles)


def decks(folder: Path) -> Path:
    (folder / "2026" / ".hidden").mkdir(parents=True)
    designed_pptx(folder / "Business review.pptx")
    pptx(folder / "2026" / "Launch process.pptx")
    designed_pptx(folder / "2026" / "Plan.pptx", "Plan for 2027", "FF0000")
    (folder / "2026" / "~$Plan.pptx").write_bytes(b"lock file")
    (folder / "2026" / ".hidden" / "secret.pptx").write_bytes(b"hidden")
    (folder / "scan.pdf").write_bytes(b"%PDF")
    return folder


def test_the_path_the_person_types_is_checked(tmp_path: Path):
    folder = decks(tmp_path / "Decks")
    assert check_path(f'"{folder}"', "folder") == folder.resolve(), "Copy as path adds quotes"
    assert check_path(str(folder / "Business review.pptx"), "either").name == "Business review.pptx"
    for text, wanted, code in [("", "folder", "no_path"), (str(tmp_path / "nowhere"), "folder", "not_found"),
                               (str(folder / "Business review.pptx"), "folder", "not_a_folder"),
                               (str(folder), "file", "not_a_file"), (str(folder / "scan.pdf"), "either", "unreadable_kind"),
                               (str(Path.home()), "folder", "too_wide"), (os.path.abspath(os.sep), "folder", "too_wide")]:
        with pytest.raises(TaskFolderError) as raised:
            check_path(text, wanted)
        assert raised.value.code == code, text


def test_a_folder_is_listed_with_stable_ids_and_files_marked_done_until_they_change(tmp_path: Path):
    folder = decks(tmp_path / "Decks").resolve()
    files = TaskFiles(tmp_path / "data")
    listed, skipped = files.listing(folder)
    assert [f.relative for f in listed] == ["2026/Launch process.pptx", "2026/Plan.pptx", "Business review.pptx"]
    assert skipped == {".pdf": 1}, "hidden folders and Office lock files are not files to read"
    assert listed[0].id == file_id("2026/Launch process.pptx") and listed[0].id.startswith("f") and len(listed[0].id) == 9
    files.mark_done("digest", folder, listed[:2], "terms saved")
    assert files.counts("digest", folder) == {"total": 3, "done": 2, "left": 1}
    assert files.counts("other-task", folder)["done"] == 0, "progress belongs to one task and folder"
    os.utime(listed[0].path, (time.time() + 100, time.time() + 100))
    files.listing(folder, fresh=True)
    assert files.counts("digest", folder)["done"] == 1, "a file changed since it was done is to do again"
    files.reset("digest", folder)
    assert files.counts("digest", folder)["done"] == 0


def test_a_file_is_converted_once_and_has_the_standards_source_id(tmp_path: Path):
    folder = decks(tmp_path / "Decks").resolve()
    documents = FakeDocuments()
    files = TaskFiles(tmp_path / "data", documents)
    item = files.listing(folder)[0][0]
    result, text = files.text(item)
    assert result["status"] == "ok" and "Gate 1: concept approval" in text
    files.text(item)
    assert documents.converted == ["Launch process.pptx"], "kept after the first conversion"
    import hashlib
    assert files.source_id(item) == "S-" + hashlib.sha256(item.path.read_bytes()).hexdigest()[:8]


# The task-file tools ------------------------------------------------------------------------------------------------------
def tool_context(tmp_path: Path, path: Path | None, saved: list[Any] | None = None) -> tuple[Any, ToolContext, FakeDocuments]:
    content = tmp_path / "content"
    (content / "knowledge" / "glossary").mkdir(parents=True)
    services = build_services(knowledge=content / "knowledge")
    documents = FakeDocuments()
    services.task_files = TaskFiles(tmp_path / "data", documents)
    if saved is not None:
        services.kb_writer = lambda files, message: (saved.append((files, message)), Published("published", "ok", "c1"))[1]
    identity = Identity(id="owner", email="owner@example.com", name="Owner", role="Owner",
                        entitlements={"asap": SystemRights(reports=["*"], markets=["*"])})
    task = {"id": "digest", "title": "Digest", "path": str(path), "every_file": True} if path else None
    return build_registry(services), ToolContext(identity=identity, run_id="r", recorder=MemoryRecorder(), services=services,
                                                 task=task), documents


def test_the_task_file_tools_read_only_the_chosen_folder(tmp_path: Path):
    folder = decks(tmp_path / "Decks").resolve()
    registry, context, documents = tool_context(tmp_path, folder)
    listed = registry.execute("wizard_task_files", {}, context)
    assert listed.ok and listed.data["total"] == 3 and listed.data["left"] == 3 and listed.data["left_out"] == {".pdf": 1}
    ids = {f["path"]: f["id"] for f in listed.data["files"]}
    read = registry.execute("wizard_task_read_file", {"file": ids["2026/Launch process.pptx"]}, context)
    assert read.ok and "Head of Sales" in read.data["text"] and read.data["source_id"].startswith("S-")
    assert read.data["parts"] == ["Slide 1: Launch process", "Slide 2: Backup (hidden slide)"] and read.data["evidence_id"] == "E1"
    evidence = context.recorder.evidence[0]  # type: ignore[attr-defined]
    assert evidence["data_mode"] == "USER_PROVIDED" and evidence["report_name"] == "2026/Launch process.pptx"
    part = registry.execute("wizard_task_read_file", {"file": ids["2026/Launch process.pptx"], "part": "Slide 2"}, context)
    assert part.data["text"].startswith("## Slide 2: Backup (hidden slide)")
    design = registry.execute("wizard_task_design", {"files": [ids["Business review.pptx"], ids["2026/Plan.pptx"]]}, context)
    assert design.ok and design.data["profiles"][0]["profile"]["theme"]["colors"]["accent 1"] == "#1428A0"
    assert design.data["profiles"][0]["source_id"].startswith("S-"), "a deck only looked at is cited too"
    assert design.data["all_read_so_far"]["presentations_read"] == 2 and design.data["all_read_so_far"]["presentations_in_folder"] == 3
    assert design.data["all_read_so_far"]["shared"]["decks"] == 2
    registry.execute("wizard_task_design", {"files": [ids["Business review.pptx"]]}, context)
    assert documents.designed == ["Business review.pptx", "Plan.pptx"], "a deck's design is read once"
    done = registry.execute("wizard_task_files_done", {"files": [ids["2026/Launch process.pptx"]], "note": "gates saved"}, context)
    assert done.ok and done.data["done"] == 1 and done.data["left"] == 2
    left = registry.execute("wizard_task_files", {}, context)
    assert [f["path"] for f in left.data["files"]] == ["2026/Plan.pptx", "Business review.pptx"]
    every = registry.execute("wizard_task_files", {"left": False, "find": "plan"}, context)
    assert every.data["files"][0]["path"] == "2026/Plan.pptx" and every.data["files"][0]["done"] is False
    unknown = registry.execute("wizard_task_read_file", {"file": "f00000000"}, context)
    assert unknown.error_code == "unknown_file"


def test_outside_a_task_with_a_path_the_tools_read_nothing(tmp_path: Path):
    registry, context, _ = tool_context(tmp_path, None)
    for name, args in [("wizard_task_files", {}), ("wizard_task_read_file", {"file": "f00000000"}),
                       ("wizard_task_design", {"files": ["f00000000"]}), ("wizard_task_files_done", {"files": ["f00000000"]})]:
        assert registry.execute(name, args, context).error_code == "task_only", name


def test_a_note_a_task_saved_is_read_and_found_before_the_next_sync(tmp_path: Path):
    folder = decks(tmp_path / "Decks").resolve()
    saved: list[Any] = []
    registry, context, _ = tool_context(tmp_path, folder, saved)
    text = NOTE.format(id="planning-terms", title="Planning terms")
    result = registry.execute("wizard_kb_save_notes", {"notes": [{"path": "knowledge/glossary/planning-terms.md", "text": text}],
                                                       "message": "Terms from the planning decks"}, context)
    assert result.ok, result.error_message
    source = registry.execute("wizard_kb_note_source", {"ids": ["planning-terms"]}, context)
    assert source.ok and source.data["notes"][0]["text"] == text, "the next round reads it to add to it"
    found = registry.execute("wizard_lookup_definitions", {"query": "GTM go-to-market"}, context)
    assert "planning-terms" in json.dumps(found.data)
    clash = registry.execute("wizard_kb_save_notes", {"notes": [{"path": "knowledge/processes/planning-terms.md", "text": text}],
                                                      "message": "Same id elsewhere"}, context)
    assert clash.error_code == "invalid_note" and len(saved) == 1, "its id stays its own"


# Settings → Tasks: a task that asks for a folder ---------------------------------------------------------------------------
DIGEST = """---
id: digest-decks
title: Digest the presentations
summary: One line.
added: 2026-11-01
input: folder
input_label: The folder with the presentations
every_file: true
---
Read every presentation and save what it teaches.
"""
GUIDE = """---
id: deck-guide
title: Write the presentation guide
summary: One line.
added: 2026-11-01
input: folder or file
---
Read how the decks look and write the guide.
"""


def test_task_front_matter_asks_for_a_folder():
    digest, guide, plain = parse(DIGEST), parse(GUIDE), parse(DIGEST.replace("input: folder\n", ""))
    assert digest and (digest.input, digest.input_label, digest.every_file) == ("folder", "The folder with the presentations", True)
    assert guide and (guide.input, guide.input_label, guide.every_file) == ("either", "The folder or file", False)
    assert plain and (plain.input, plain.every_file) == (None, False), "every file needs a folder to go through"


def test_the_task_request_names_the_folder_and_the_round(tmp_path: Path):
    work = {"title": "Digest", "body": "Read them.", "path": str(tmp_path), "chosen": "folder", "every_file": True,
            "round": 3, "done": 40, "total": 300, "left": 260}
    prompt = compose("Task: Digest", [], "task", __import__("datetime").date(2026, 11, 1), task=work)
    assert f"chose this folder for the task: {tmp_path}" in prompt and "wizard_task_files" in prompt
    assert "This is round 3: 40 of 300 files are done, 260 left" in prompt and "wizard_task_files_done" in prompt
    once = compose("Task: Guide", [], "task", __import__("datetime").date(2026, 11, 1),
                   task={**work, "every_file": False, "chosen": "file"})
    assert "chose this file" in once and "round" not in once


class Digester:
    """A scripted Gemini: each round reads two files, saves a note, and marks them done; a question tries the tools."""
    kind = "code-assist"
    model = "gemini-3.8-flash"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.offered: list[list[str]] = []
        self.results: list[tuple[str, bool, str]] = []

    def label(self) -> str:
        return "Task test runtime"

    async def readiness(self, home: Path, email: str) -> dict[str, Any]:
        return {"ready": True, "reason": None}

    async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
        self.prompts.append(request.prompt)
        self.offered.append([t["name"] for t in tools.describe()])
        if request.kind != "task":
            ok, text = await tools.call("wizard_task_files", {})
            self.results.append((request.kind, ok, text))
            await emit("text_delta", {"text": "Answered."})
            return
        for _ in range(3):  # the files left change as files are marked done, so the same call answers anew
            ok, text = await tools.call("wizard_task_files", {"limit": 2})
            assert ok, text
        ids = [f["id"] for f in json.loads(text)["files"]]
        for file in ids:
            await tools.call("wizard_task_read_file", {"file": file})
        round_number = len([p for p in self.prompts if "goes through every file" in p])
        await tools.call("wizard_kb_save_notes", {"notes": [{"path": f"knowledge/glossary/terms-{round_number}.md",
                                                             "text": NOTE.format(id=f"terms-{round_number}", title=f"Terms {round_number}")}],
                                                  "message": "Terms from the decks"})
        await tools.call("wizard_task_files_done", {"files": ids})
        await asyncio.sleep(0)
        await emit("text_delta", {"text": f"Round done: {len(ids)} files."})


def folder_app(tmp_path: Path, runtime: Digester) -> TestClient:
    settings = make_settings(tmp_path, WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    app = create_app(settings, runtime=runtime)  # type: ignore[arg-type]
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "digest-decks.md").write_text(DIGEST, encoding="utf-8")
    (bundled / "deck-guide.md").write_text(GUIDE, encoding="utf-8")
    board: TaskBoard = app.state.task_board
    board.bundled = bundled
    app.state.manager.services.task_files.documents = FakeDocuments()
    return TestClient(app)


def wait_for(client: TestClient, task_id: str, done: Any, timeout: float = 30) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = next(t for t in client.get("/api/v1/tasks").json()["tasks"] if t["id"] == task_id)
        if done(task):
            return dict(task)
        time.sleep(0.05)
    raise AssertionError(f"the task did not get there: {task}")


def test_a_task_goes_through_every_file_of_the_folder_in_rounds(tmp_path: Path):
    folder = decks(tmp_path / "Decks").resolve()
    runtime = Digester()
    saved: list[Any] = []
    with folder_app(tmp_path, runtime) as client:
        client.app.state.manager.services.kb_writer = lambda files, message: (saved.append(files), Published("published", "ok", "c1"))[1]
        login(client, "local-owner")
        listed = {t["id"]: t for t in client.get("/api/v1/tasks?refresh=true").json()["tasks"]}
        assert listed["digest-decks"]["input"] == "folder" and listed["digest-decks"]["every_file"] is True
        assert listed["deck-guide"]["input"] == "either" and listed["digest-decks"]["path"] is None
        for body, words in [({}, "Type or paste the path"), ({"path": str(tmp_path / "nowhere")}, "cannot find"),
                            ({"path": str(folder / "scan.pdf")}, "paste the path of the folder")]:
            refused = client.post("/api/v1/tasks/digest-decks/run", json=body, headers=HEADERS)
            assert refused.status_code == 400 and words in refused.json()["error"], refused.text
        started = client.post("/api/v1/tasks/digest-decks/run", json={"path": f'"{folder}"'}, headers=HEADERS)
        assert started.status_code == 200, started.text
        task = wait_for(client, "digest-decks", lambda t: t["state"] == "done")
        assert task["message"] == "All 3 files done in 2 round(s)." and task["progress"] == {"total": 3, "done": 3, "left": 0}
        assert task["path"] == str(folder) and task["round"] == 2
        assert "This is round 1: 0 of 3 files are done" in runtime.prompts[0]
        assert "This is round 2: 2 of 3 files are done" in runtime.prompts[1] and str(folder) in runtime.prompts[1]
        assert "wizard_task_design" in runtime.offered[0] and len(saved) == 2
        conversation = client.get(f"/api/v1/conversations/{task['conversation_id']}").json()
        assert [r["question"] for r in conversation["runs"]] == ["Task: Digest the presentations",
                                                                 "Task: Digest the presentations (round 2)"]
        again = client.post("/api/v1/tasks/digest-decks/run", json={"path": str(folder)}, headers=HEADERS)
        assert again.status_code == 400 and "already done" in again.json()["error"]
        fresh = client.post("/api/v1/tasks/digest-decks/run", json={"path": str(folder), "fresh": True}, headers=HEADERS)
        assert fresh.status_code == 200
        wait_for(client, "digest-decks", lambda t: t["state"] == "done" and t["conversation_id"] != task["conversation_id"])
        from tests.helpers import ask
        ask(client, "List my files")
        kind, ok, text = runtime.results[-1]
        assert kind == "ask" and not ok and "task_only" in text
        assert "wizard_task_files" not in runtime.offered[-1], "a question is not offered the folder tools"


def test_rounds_that_mark_nothing_done_stop(tmp_path: Path):
    folder = decks(tmp_path / "Decks").resolve()

    class Idle(Digester):
        async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
            self.prompts.append(request.prompt)
            await tools.call("wizard_task_files", {})
            await emit("text_delta", {"text": "Nothing to keep."})

    runtime = Idle()
    with folder_app(tmp_path, runtime) as client:
        login(client, "local-owner")
        assert client.post("/api/v1/tasks/digest-decks/run", json={"path": str(folder)}, headers=HEADERS).status_code == 200
        task = wait_for(client, "digest-decks", lambda t: t["state"] == "failed")
        assert "2 rounds in a row marked no file done (3 left)" in task["message"] and len(runtime.prompts) == 2


def test_a_task_that_reads_a_folder_once_runs_one_round(tmp_path: Path):
    folder = decks(tmp_path / "Decks").resolve()

    class Guide(Digester):
        async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
            self.prompts.append(request.prompt)
            ok, text = await tools.call("wizard_task_files", {"find": "review"})
            ok, text = await tools.call("wizard_task_design", {"files": [json.loads(text)["files"][0]["id"]]})
            self.results.append((request.kind, ok, text))
            await emit("text_delta", {"text": "Guide written."})

    runtime = Guide()
    with folder_app(tmp_path, runtime) as client:
        login(client, "local-owner")
        deck = folder / "Business review.pptx"
        assert client.post("/api/v1/tasks/deck-guide/run", json={"path": str(deck)}, headers=HEADERS).status_code == 200
        task = wait_for(client, "deck-guide", lambda t: t["state"] == "done")
        assert task["path"] == str(deck) and task["progress"] is None and len(runtime.prompts) == 1
        assert "chose this file for the task" in runtime.prompts[0] and "round" not in runtime.prompts[0]
        assert runtime.results[0][1] and "Company Theme" in runtime.results[0][2]


def test_the_two_presentation_tasks_ship_and_ask_for_their_path():
    digest = parse((ROOT / "tasks" / "digest-presentations.md").read_text(encoding="utf-8"))
    guide = parse((ROOT / "tasks" / "presentation-guide.md").read_text(encoding="utf-8"))
    assert digest and digest.input == "folder" and digest.every_file and "wizard_task_files_done" in digest.body
    assert guide and guide.input == "either" and not guide.every_file and "wizard_task_design" in guide.body
    for task in (digest, guide):
        assert "wizard_kb_save_notes" in task.body and "SIGNED" in task.body
