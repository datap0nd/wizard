"""Company knowledge: the note format, section-level search, the browse/read tools and the content validator."""
from __future__ import annotations

from pathlib import Path

from tests.helpers import MemoryRecorder

from wizard_connectors.content import errors, validate_content, validate_knowledge
from wizard_connectors.knowledge import KnowledgeBase, parse_list, split_sections
from wizard_connectors.tools import Services, ToolContext, build_registry

NOTE = """---
id: {id}
title: {title}
type: {type}
status: DRAFT_UNSIGNED
owner: TBD - Finance
summary: {summary}
aliases: [{aliases}]
tags: [finance, planning]
related: [{related}]
sources: [S-1a2b3c4d]
updated: 2026-10-05
reviewed: {reviewed}
reviewed_by: {reviewed_by}
---
{body}
"""


def write(root: Path, area: str, note_id: str, body: str, title: str = "", kind: str = "concept", summary: str = "A note.",
          aliases: str = "", related: str = "", reviewed: str = "", reviewed_by: str = "") -> Path:
    folder = root / "knowledge" / area if area else root / "knowledge"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{note_id}.md"
    path.write_text(NOTE.format(id=note_id, title=title or note_id.replace("-", " ").title(), type=kind, summary=summary,
                                aliases=aliases, related=related, reviewed=reviewed, reviewed_by=reviewed_by, body=body),
                    encoding="utf-8")
    return path


LONG_PROCESS = "The month close fixes the books.\n\n" + "\n\n".join(
    f"## Step {n}: {name}\nThe month close step {name} " + "detail " * 120 for n, name in
    enumerate(["ledger lock", "accruals", "FX revaluation", "restatement window", "sign-off"], start=1))


def knowledge(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    write(root, "processes", "month-close", LONG_PROCESS, title="Month close", kind="process",
          summary="How finance closes each month, step by step.", aliases="closing, period close", related="glossary-finance",
          reviewed="2026-10-20", reviewed_by="Ana Silva (Finance controller)")
    write(root, "glossary", "glossary-finance", "Finance terms.\n\n- **BDP**: Business Data Platform, the weekly partner feed. [S-1a2b3c4d]\n"
          "- **FX**: foreign exchange; rates come from the treasury table. [S-1a2b3c4d]\n- **OPEX**: operating expenses.",
          title="Finance glossary", kind="glossary", summary="Finance acronyms.")
    write(root, "company", "company-overview", "What the company does in the region.", title="Company overview",
          kind="overview", summary="What the company does.")
    return root


def test_front_matter_lists_and_sections(tmp_path):
    assert parse_list('[a, "b, c", d]') == ("a", "b, c", "d") and parse_list("[]") == ()
    base = KnowledgeBase.load(knowledge(tmp_path) / "knowledge")
    note = base.by_id["month-close"]
    assert note.area == "processes" and note.aliases == ("closing", "period close") and note.reviewed == "2026-10-20"
    glossary = split_sections(base.by_id["glossary-finance"])
    assert [s.heading for s in glossary] == ["", "BDP", "FX", "OPEX"] and all(s.entry for s in glossary[1:])


def test_search_finds_the_right_section_and_glossary_entry(tmp_path):
    base = KnowledgeBase.load(knowledge(tmp_path) / "knowledge")
    assert base.search("what is BDP")[0].id == "glossary-finance", "stopwords do not decide the ranking"
    assert base.search("period close")[0].id == "month-close", "aliases are names"
    hit = base.find("FX revaluation")[0]
    text, left_out = base.excerpt(hit)
    assert hit.note.id == "month-close" and "## Step 3: FX revaluation" in text and text.startswith("The month close fixes")
    assert "Step 1: ledger lock" in left_out and "Step 3: FX revaluation" not in left_out


def test_knowledge_tools(tmp_path, identities):
    root = knowledge(tmp_path)
    from wizard_connectors.tools import build_services
    services: Services = build_services(knowledge=root / "knowledge")
    registry = build_registry(services)
    ctx = ToolContext(identity=identities.get("u-ceo"), run_id="r", recorder=MemoryRecorder(), services=services)
    found = registry.execute("wizard_lookup_definitions", {"query": "month close accruals"}, ctx).data
    first = found["definitions"][0]
    assert first["id"] == "month-close" and first["other_sections"] and first["expert_checked"] == "2026-10-20"
    assert "wizard_read_knowledge" in found["note"] and "DRAFT_UNSIGNED" in found["note"]
    index = registry.execute("wizard_browse_knowledge", {}, ctx).data
    assert {a["area"] for a in index["areas"]} == {"company", "glossary", "processes"}
    assert {"id": "company-overview", "title": "Company overview", "area": "company", "type": "overview",
            "summary": "What the company does.", "approval_status": "DRAFT_UNSIGNED"} in index["notes"]
    assert registry.execute("wizard_browse_knowledge", {"area": "hr"}, ctx).error_code == "unknown_area"
    read = registry.execute("wizard_read_knowledge", {"ids": ["month-close", "nope"]}, ctx).data
    assert read["notes"][0]["text"] == LONG_PROCESS.strip() and read["missing"] == ["nope"]
    assert registry.execute("wizard_read_knowledge", {"ids": ["nope"]}, ctx).error_code == "unknown_note"
    assert registry.execute("wizard_lookup_definitions", {"query": "zzz"}, ctx).data["definitions"] == []


def test_validator_enforces_the_knowledge_standard(tmp_path):
    root = knowledge(tmp_path)
    assert not errors(validate_knowledge(root / "knowledge", root))
    write(root, "org", "month-close", "Duplicate id.")
    write(root, "org", "Bad_Id", "Bad id.")
    write(root, "org", "typed", "Body.", kind="memo")
    write(root, "org", "contact", "Write to ana.silva@example.com for access.")
    nested = root / "knowledge" / "org" / "nested.md"
    nested.write_text("---\nid: nested\ntitle: Nested\nstatus: DRAFT_UNSIGNED\nowner: x\ntags:\n  - a\n---\nBody\n", encoding="utf-8")
    write(root, "org", "orphan", "Body.", related="does-not-exist")
    messages = [str(p) for p in validate_knowledge(root / "knowledge", root)]
    assert any("duplicate id 'month-close'" in m for m in messages)
    assert any("must be lowercase kebab-case" in m for m in messages)
    assert any("type 'memo'" in m for m in messages)
    assert any("email address" in m for m in messages)
    assert any("front matter must be flat" in m for m in messages)
    assert any("WARNING" in m and "does-not-exist" in m for m in messages)


def test_content_with_notes_only_is_allowed(tmp_path):
    root = knowledge(tmp_path)
    problems = validate_content(root)
    assert not errors(problems) and any("no report catalogs yet" in p.message for p in problems)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert errors(validate_content(empty))
