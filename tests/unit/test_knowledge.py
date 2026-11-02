"""Company knowledge: the note format, section-level search, the browse/read tools and the content validator."""
from __future__ import annotations

from pathlib import Path

from tests.helpers import MemoryRecorder

from wizard_connectors.content import errors, validate_content, validate_knowledge
from wizard_connectors.knowledge import KnowledgeBase, parse_list, split_sections
from wizard_connectors.note_checks import owner_problem
from wizard_connectors.paths import ROOT
from wizard_connectors.tools import Services, ToolContext, build_registry

NOTE = """---
id: {id}
title: {title}
type: {type}
status: DRAFT_UNSIGNED
owner: {owner}
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
          aliases: str = "", related: str = "", reviewed: str = "", reviewed_by: str = "",
          owner: str = "TBD - Finance") -> Path:
    folder = root / "knowledge" / area if area else root / "knowledge"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{note_id}.md"
    path.write_text(NOTE.format(id=note_id, title=title or note_id.replace("-", " ").title(), type=kind, summary=summary,
                                aliases=aliases, related=related, reviewed=reviewed, reviewed_by=reviewed_by, body=body,
                                owner=owner),
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


# The knowledge-base review (2 Nov 2026) found these in real notes; every figure, address and name below is invented.
REVIEW = ("performance figure", "only work on one PC", "owner '", "without `## Where to get it`",
          "without `## Example query`", "empty `related`")
FIGURES = """The accessory tracker counts 3.6 million hosts, 7.3% attach in the Gulf markets [S-1a2b3c4d].

## What the tracker showed
Sell-out rose 12.8x after the relaunch, and marketing spend reached USD 2.4M in the quarter.

## Questions this note answers
- What was <brand>'s share in Q2 2025?
- What is our share in <market> by quarter?
"""
PC_SPECIFIC = """The demand dashboard runs at http://10.20.30.40:8501 and reads Z:\\Planning\\weekly.xlsx.

## How to refresh it
Copy the files from \\\\filesrv01\\planning into content\\inbox\\_text, then run update_cache.bat.
"""
CLEAN_METRIC = """Attach rate is accessory units sold with a phone over phone units sold, in % [S-1a2b3c4d].

## How attach rate is computed
Attach rate = accessory units / phone units x 100, reported per 1,000 devices; a change in attach rate is given in
percentage points, e.g. 31.0% - 30.0% = +1.0 pp. Shares of all brands add up to 100%. Premium phones are those priced at USD 700
or more. As of October 2026 the tracker covers 9 markets and 1,450 retail stores, and the fiscal year starts on
1 January [S-1a2b3c4d]. Write rates with one decimal (12.3%) and units with a thousands separator (1,234).

## Where to get it
`sales.attach_weekly` in `meto_db` holds attach rate by market and week; `"Unit/Value" = 'Units'` selects units.

## Questions this note answers
- What is the attach rate in <market> by month?
- Where do I find attach rate for Q3 2026?
- How is attach rate calculated?
"""
CLEAN_DATASET = """`meto_db`, `sales.attach_weekly`: one row per market, model and week, refreshed every Monday [S-1a2b3c4d].

## Columns
| Column | Meaning | Type | Notes |
|---|---|---|---|
| units | Accessory units sold, 1,000s | numeric | 3.1% of rows are restated |
| attach_rate | Attach rate in %, e.g. 7.3% | numeric | never summed |
| price_band | Price band of the phone | text | |

## Pitfalls
The discount rate column takes the values 5%, 15% and 25%. Phone price bands are USD 0-199, USD 200-399 and
USD 400+. Units sold range from 0 to 48,000 per row. The view holds about 1.2 million rows of weekly sell-in.

## Example query
```sql
SELECT "Week", SUM(units) FROM sales.attach_weekly WHERE units > 12500 GROUP BY 1  -- 7.3% attach, 3.6 million hosts
```

## Questions this note answers
- What is attach rate by market last week?
"""


def review(root: Path, where: str) -> list[str]:
    return [p.message for p in validate_knowledge(root / "knowledge", root)
            if p.where == where and any(k in p.message for k in REVIEW)]


def test_the_review_findings_are_warnings_never_errors(tmp_path):
    root = knowledge(tmp_path)
    write(root, "faq", "tracker-figures", FIGURES)
    write(root, "platforms", "demand-dashboard", PC_SPECIFIC)
    write(root, "org", "two-owners", "Who plans.", owner="TBD - Role / Person (ask the user)")
    write(root, "org", "odd-owner", "Who plans.", owner="Planning team")
    write(root, "metrics", "metric-only-meaning", "Sell-through is sell-out over sell-in.", kind="metric")
    write(root, "datasets", "sales-attach-weekly", "One row per market and week.", kind="dataset")
    problems = validate_knowledge(root / "knowledge", root)
    assert not errors(problems), "a review finding never leaves a note out or stops a sync"
    figures = review(root, "knowledge/faq/tracker-figures.md")
    assert len(figures) == 1 and figures[0].startswith("5 performance figure(s)"), figures
    assert "3.6 million hosts" in figures[0] and "7.3% attach" in figures[0] and "12.8x" in figures[0]
    assert "USD 2.4M" not in figures[0] and "Q2 2025" not in figures[0], "up to three examples"
    assert "placeholders" in figures[0] and "rule 7" in figures[0]
    write(root, "faq", "share-question", "## Questions this note answers\n- What was <brand>'s share in Q2 2025?\n")
    assert "What was <brand>'s share in Q2 2025?" in review(root, "knowledge/faq/share-question.md")[0]
    pc = review(root, "knowledge/platforms/demand-dashboard.md")
    assert len(pc) == 1 and "a server address (http://10.20.30.40:8501)" in pc[0], pc
    assert "a drive letter (Z:\\Planning\\weekly.xlsx)" in pc[0] and "a network share path" in pc[0]
    assert "the team's shared drive" in pc[0]
    write(root, "platforms", "kit-paths", "Converted text is in content\\inbox\\_text; refresh it with update_cache.bat.")
    kit = review(root, "knowledge/platforms/kit-paths.md")
    assert len(kit) == 1 and "a path into a PC's folders" in kit[0] and "a local script (update_cache.bat)" in kit[0]
    assert "names several owners" in review(root, "knowledge/org/two-owners.md")[0]
    assert "not in the standard's form" in review(root, "knowledge/org/odd-owner.md")[0]
    metric = review(root, "knowledge/metrics/metric-only-meaning.md")
    assert len(metric) == 1 and "without `## Where to get it`" in metric[0] and "section 11" in metric[0]
    dataset = review(root, "knowledge/datasets/sales-attach-weekly.md")
    assert len(dataset) == 2 and "`## Example query`" in dataset[0] and "empty `related`" in dataset[1]
    loaded = KnowledgeBase.load(root / "knowledge").by_id
    assert {"tracker-figures", "demand-dashboard", "two-owners", "sales-attach-weekly"} <= set(loaded), "all still load"


def test_clean_notes_do_not_warn(tmp_path):
    root = knowledge(tmp_path)
    write(root, "metrics", "attach-rate", CLEAN_METRIC, kind="metric", related="sales-attach-weekly")
    write(root, "datasets", "sales-attach-weekly", CLEAN_DATASET, kind="dataset", related="attach-rate")
    write(root, "org", "named-owner", "The planning office.", owner="Alex Example, Head of planning")
    write(root, "org", "tbd-owner", "The sales office.", owner="TBD - Sales operations (ask the user)")
    problems = [p for p in validate_knowledge(root / "knowledge", root)
                if p.where.startswith(("knowledge/metrics", "knowledge/datasets", "knowledge/org"))]
    assert problems == [], [str(p) for p in problems]
    write(root, "faq", "value-lists-in-prose", CLEAN_DATASET)
    prose = review(root, "knowledge/faq/value-lists-in-prose.md")
    assert len(prose) == 1 and "5%, 15%" in prose[0], "value lists are allowed in dataset notes only"


def test_the_repository_notes_pass_the_review_checks():
    found = [str(p) for p in validate_knowledge(ROOT / "knowledge", ROOT) if any(k in p.message for k in REVIEW)]
    assert found == []
    standard = (ROOT / "templates" / "content" / "schema" / "knowledge-standard.md").read_text(encoding="utf-8")
    assert "owner: TBD - Product marketing (ask the user)" in standard and owner_problem("TBD - Product marketing "
                                                                                         "(ask the user)") is None


def test_content_with_notes_only_is_allowed(tmp_path):
    root = knowledge(tmp_path)
    problems = validate_content(root)
    assert not errors(problems) and any("no report catalogs yet" in p.message for p in problems)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert errors(validate_content(empty))
