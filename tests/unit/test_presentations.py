"""Presentations (owner, 13 Nov 2026: "Wizard should be able to make complete powerpoint presentations, start to finish
... powerpoints are all about storyline ... any changes can be requested in the chat easily").

Gemini asks which story the deck tells (wizard_propose_storylines: a card whose choice is the person's next message),
makes the deck from the conversation's visuals and evidence (wizard_make_presentation), and changes it as the person
asks in the chat (wizard_change_presentation: a new version). The look comes from the knowledge base's
presentation-look note, else Wizard's neutral design. Gemini is scripted here; the page draws and writes the file
(apps/web/src/deck)."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, login, make_settings, wait_run
from tests.integration.test_steering_api import ScriptedRuntime, say

from wizard_agent.prompting import compose, system_prompt
from wizard_api.app import create_app
from wizard_connectors.deck_design import DEFAULT, company_design, merge, tokens_block
from wizard_connectors.knowledge import Note
from wizard_connectors.tools import ToolContext

STORY = "Flagship carried Q3 while Mass lost share: shift spend to the A-series."
CHART = {"kind": "bar", "title": "Sell-out by segment", "columns": [
    {"key": "segment", "label": "Segment", "type": "string"}, {"key": "q2", "label": "Q2", "type": "number", "unit": "units"},
    {"key": "q3", "label": "Q3", "type": "number", "unit": "units"}],
    "rows": [["Flagship", 100, 118], ["Mass", 300, 280]], "x": "segment", "series": ["q2", "q3"]}
TABLE = {**CHART, "kind": "table", "title": "Segments against plan"}


@pytest.fixture
def tools(registry, context) -> tuple[Any, ToolContext]:
    return registry, context("u-ceo")


def call(setup: tuple[Any, ToolContext], name: str, args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    registry, ctx = setup
    outcome = registry.execute(name, args, ctx)
    return outcome.ok, outcome.data if outcome.ok else {"code": outcome.error_code, "message": outcome.error_message}


def deck(slides: list[dict[str, Any]], **head: Any) -> dict[str, Any]:
    return {"title": "Q3 review", "storyline": STORY, "slides": slides, **head}


def visuals(setup: tuple[Any, ToolContext]) -> None:
    _, ctx = setup
    evidence = ctx.recorder.add_evidence({"system": "postgresql", "system_name": "AI Team Database",
                                          "report_name": "Sell-out by segment", "data_mode": "SYNTHETIC",
                                          "as_of": "2026-11-10"})
    assert call(setup, "wizard_render_visual", {**CHART, "evidence_ids": [evidence]})[0]
    assert call(setup, "wizard_render_visual", {**TABLE, "evidence_ids": [evidence]})[0]


COVER = {"kind": "cover", "title": "Q3 review", "meta": "MENA · November 2026"}


def test_a_deck_keeps_its_slides_visuals_sources_and_the_design_it_was_made_in(tools):
    visuals(tools)
    three = ["**Flagship:** +18%", "**Mass:** -7%", "**Eco:** flat"]
    ok, made = call(tools, "wizard_make_presentation", deck([
        COVER, {"kind": "summary", "title": "Flagship carried Q3", "points": ["**Flagship:** +18%", {"text": "Mass fell", "sub": ["C-brands"]},
                                                                            "**Eco:** flat"], "evidence_ids": ["E1"]},
        {"kind": "chart", "title": "Flagship grew while Mass fell", "visual": "V1", "chart": "column", "points": three},
        {"kind": "table", "title": "Mass is the gap", "visual": "V2", "highlights": [{"row": "Mass", "column": "Q3", "tone": "bad"}],
         "points": three},
        {"kind": "closing", "title": "Shift spend to the A-series", "points": [*three, "**Owner:** marketing"]}]))
    assert ok, made
    assert made["deck_id"] == "D1" and made["cite_as"] == "[D1]" and made["slides"] == 5 and made["version"] == 1
    assert made["outline"][0] == "1. Cover: Q3 review" and made["outline"][3] == "4. Table: Mass is the gap"
    assert "neutral design" in made["design"] and made["warnings"] == []
    kept = tools[1].recorder.decks[0]
    assert set(kept["visuals"]) == {"V1", "V2"} and kept["evidence_ids"] == ["E1"]
    assert kept["sources"]["E1"] == {"name": "AI Team Database · Sell-out by segment", "as_of": "2026-11-10", "data_mode": "SYNTHETIC"}
    assert kept["data_mode"] == "SYNTHETIC" and kept["design"]["tokens"] == DEFAULT
    assert kept["slides"][1]["points"][:2] == ["**Flagship:** +18%", {"text": "Mass fell", "sub": ["C-brands"]}]
    assert "subtitle" not in kept["slides"][0], "a slide keeps only the fields it has"


def test_what_the_page_cannot_draw_is_refused_with_every_reason(tools):
    visuals(tools)
    ok, refused = call(tools, "wizard_make_presentation", deck([
        COVER, {"kind": "chart", "title": "A table as a chart", "visual": "V2"},
        {"kind": "chart", "title": "No such chart", "visual": "V9"},
        {"kind": "table", "title": "Wrong cells", "visual": "V2", "highlights": [{"row": "Eco", "column": "Q4", "tone": "good"}]},
        {"kind": "cards", "title": "One card", "cards": [{"heading": "Only"}]},
        {"kind": "kpis", "title": "Unknown evidence", "kpis": [{"value": "1", "label": "a", "evidence_ids": ["E7"]},
                                                              {"value": "2", "label": "b"}]},
        {"kind": "text"}]))
    assert not ok and refused["code"] == "invalid_presentation"
    message = refused["message"]
    for reason in ("Slide 2: V2 is a table", "Slide 3: there is no visual V9", "no row 'Eco' in V2", "no column 'Q4' in V2",
                   "Slide 5 (cards) needs 2 to 4 cards", "Slide 6: unknown evidence id(s) E7", "Slide 7 (text) needs a title"):
        assert reason in message, reason
    assert not tools[1].recorder.decks


def test_a_stacked_chart_needs_two_series_and_warnings_name_what_to_fix(tools):
    visuals(tools)
    one = {**CHART, "series": ["q3"], "title": "Q3 only"}
    assert call(tools, "wizard_render_visual", one)[0]
    ok, refused = call(tools, "wizard_make_presentation", deck([{"kind": "chart", "title": "Stacked", "visual": "V3", "chart": "stacked"}]))
    assert not ok and "a stacked chart needs a bar visual with two or more series" in refused["message"]
    many = [{"row": r, "column": "Q3", "tone": "good"} for r in ("Flagship", "Mass")] * 3
    ok, made = call(tools, "wizard_make_presentation", deck([
        {"kind": "table", "title": "x" * 120, "visual": "V2", "highlights": many},
        {"kind": "text", "title": "Too many bullets", "points": [f"Point {n}" for n in range(8)]},
        {"kind": "kpis", "title": "Figures without sources", "kpis": [{"value": "12%", "label": "a"}, {"value": "3", "label": "b"}]}]))
    assert ok
    assert any("title has 120 characters" in w for w in made["warnings"])
    assert any("shades 6 good cells" in w for w in made["warnings"])
    assert any("Slide 2 has 8 bullets" in w for w in made["warnings"])
    assert any("Slide 3 states figures but cites no evidence" in w for w in made["warnings"])
    assert any("first slide is not a cover" in w for w in made["warnings"])


def test_thin_slides_are_named_so_the_deck_has_no_empty_space(tools):
    visuals(tools)
    ok, made = call(tools, "wizard_make_presentation", deck([
        COVER, {"kind": "section", "title": "Where we stand"},
        {"kind": "chart", "title": "A chart alone", "visual": "V1"},
        {"kind": "text", "title": "Two points", "points": ["a", "b"]},
        {"kind": "cards", "title": "Thin cards", "cards": [{"heading": "One", "points": ["a"]}, {"heading": "Two", "points": ["b", "c", "d"]}]},
        {"kind": "kpis", "title": "Figures alone", "kpis": [{"value": "1", "label": "a", "evidence_ids": ["E1"]}, {"value": "2", "label": "b"}]},
        {"kind": "grid", "title": "Three panels", "panels": [{"heading": "A", "visual": "V1"}, {"heading": "B", "points": ["x"]}]},
        {"kind": "closing", "title": "Thank you"}]))
    assert ok, made
    warned = " ".join(made["warnings"])
    for slide, words in ((2, "section divider in a 8-slide deck"), (3, "shows its chart with no takeaway"), (4, "has 2 point(s)"),
                         (5, "give every card 3 to 5 bullets"), (6, "shows figures without analysis"), (7, "a panel with fewer than 3 points"),
                         (8, "has no point(s)")):
        assert f"Slide {slide}" in warned and words in warned, words
    ok, refused = call(tools, "wizard_make_presentation", deck([{"kind": "grid", "title": "One panel", "panels": [{"heading": "A"}]},
                                                               {"kind": "text", "title": "Panels", "points": ["a"], "panels": [{"points": ["x"]}, {"points": ["y"]}]}]))
    assert not ok and "Slide 1 (grid) needs 2 to 4 panels" in refused["message"] and "panel 1 needs a visual or points" in refused["message"]
    assert "Slide 2: panels belong to a grid slide" in refused["message"]


def test_changes_make_a_new_version_and_reading_returns_every_slide(tools):
    visuals(tools)
    assert call(tools, "wizard_make_presentation", deck([COVER, {"kind": "chart", "title": "Old title", "visual": "V1"},
                                                        {"kind": "text", "title": "Drop me", "points": ["x"]},
                                                        {"kind": "closing", "title": "Next steps"}]))[0]
    ok, changed = call(tools, "wizard_change_presentation", {"deck": "D1", "changes": [
        {"action": "update", "at": 2, "slide": {"title": "Flagship grew 18%", "chart": "line"}},
        {"action": "delete", "at": 3},
        {"action": "insert", "at": 2, "slide": {"kind": "table", "title": "Mass is the gap", "visual": "V2"}},
        {"action": "move", "at": 4, "to": 2},
        {"action": "deck", "deck": {"title": "Q3 review, final"}}]})
    assert ok, changed
    assert changed["deck_id"] == "D2" and changed["revises"] == "D1" and changed["version"] == 2 and changed["family"] == "D1"
    assert changed["outline"] == ["1. Cover: Q3 review", "2. Closing: Next steps", "3. Chart: Flagship grew 18%",
                                  "4. Table: Mass is the gap"]
    second = tools[1].recorder.decks[1]
    assert second["title"] == "Q3 review, final" and second["slides"][2]["chart"] == "line"
    assert second["design"] == tools[1].recorder.decks[0]["design"], "a version keeps its deck's design"

    ok, removed = call(tools, "wizard_change_presentation", {"deck": "D2", "changes": [{"action": "update", "at": 3, "slide": {"chart": None}}]})
    assert ok and "chart" not in tools[1].recorder.decks[2]["slides"][2] and removed["version"] == 3

    ok, bad = call(tools, "wizard_change_presentation", {"deck": "D2", "changes": [{"action": "delete", "at": 9}]})
    assert not ok and bad["code"] == "invalid_change" and "slide number 9 is not in the deck (1 to 4)" in bad["message"]
    ok, bad = call(tools, "wizard_change_presentation", {"deck": "D2", "changes": [{"action": "insert", "at": 1, "slide": {"title": "No kind"}}]})
    assert not ok and "with its kind" in bad["message"]
    ok, bad = call(tools, "wizard_change_presentation", {"deck": "D7", "changes": [{"action": "delete", "at": 1}]})
    assert not ok and bad["code"] == "unknown_deck"
    ok, again = call(tools, "wizard_change_presentation", {"deck": "D1", "changes": [{"action": "delete", "at": 4}]})
    assert ok and "D1 had already been changed into D2" in again["note"]

    ok, read = call(tools, "wizard_read_presentation", {"deck": "D2", "slides": [3]})
    assert ok and read["changed_into"] == ["D3"] and [s["number"] for s in read["slides"]] == [3]
    assert read["slides"][0]["visual"] == "V1" and read["storyline"] == STORY


def test_storylines_are_two_to_four_different_stories(tools):
    ok, asked = call(tools, "wizard_propose_storylines", {"storylines": [
        {"title": STORY, "arc": ["Q3 beat plan", "Flagship drove it", "Mass lost share", "Three moves"], "best_for": "a board update"},
        {"title": STORY.upper(), "arc": ["a", "b"]},
        {"title": "A market-by-market review", "arc": ["UAE", "KSA", " "]}]})
    assert ok and [s["title"] for s in asked["storylines"]] == [STORY, "A market-by-market review"]
    assert asked["question"] == "What story should the presentation tell?" and asked["storylines"][1]["arc"] == ["UAE", "KSA"]
    assert "End your turn now" in asked["next"]
    ok, one = call(tools, "wizard_propose_storylines", {"storylines": [{"title": STORY, "arc": ["a", "b"]}, {"title": STORY, "arc": ["c", "d"]}]})
    assert not ok and "two different storylines" in one["message"]


# --- The design ------------------------------------------------------------------------------------------------------


def knowledge(body: str | None) -> Any:
    notes = {} if body is None else {"presentation-look": Note(id="presentation-look", title="How presentations look",
                                                                 status="DRAFT_UNSIGNED", owner="TBD", tags=(), body=body,
                                                                 path="knowledge/presentations/presentation-look.md")}
    return SimpleNamespace(by_id=notes)


def test_the_company_design_comes_from_the_knowledge_base_and_bad_values_fall_back():
    body = """Lead.

## Design tokens

```json
{"name": "Executive dense", "fonts": {"title": "Sharp Sans Bold", "east_asian": "Malgun Gothic", "comic": "x"},
 "colors": {"brand": "#1428a0", "card": "blue", "series": ["#1428A0", "nope"]},
 "sizes": {"title": 40, "footnote": 6.5, "body": 300}, "cover": {"background": "white"},
 "footer": {"text": "Confidential", "page_numbers": false}, "rules": {"max_highlights": 3}, "logo": "x.png"}
```
"""
    design = company_design(knowledge(body))  # type: ignore[arg-type]
    tokens = design["tokens"]
    assert design["source"] == "knowledge" and design["status"] == "DRAFT_UNSIGNED"
    assert tokens["name"] == "Executive dense" and tokens["fonts"]["title"] == "Sharp Sans Bold"
    assert tokens["colors"]["brand"] == "#1428A0" and tokens["colors"]["card"] == DEFAULT["colors"]["card"]
    assert tokens["colors"]["series"] == ["#1428A0"] and tokens["sizes"]["title"] == 40 and tokens["sizes"]["footnote"] == 6.5
    assert tokens["sizes"]["body"] == DEFAULT["sizes"]["body"] and tokens["cover"]["background"] == "white"
    assert tokens["footer"] == {"text": "Confidential", "page_numbers": False} and tokens["rules"]["max_highlights"] == 3
    for problem in ("unknown key 'fonts.comic'", "'colors.card' is not a #RRGGBB color", "'colors.series' must be a list of #RRGGBB colors",
                    "'sizes.body' must be a number from 5 to 96", "unknown key 'logo'"):
        assert problem in design["problems"], problem
    assert "left out:" in design["about"]


def test_without_tokens_the_deck_is_drawn_in_wizards_neutral_design():
    assert company_design(knowledge(None))["source"] == "default"  # type: ignore[arg-type]
    missing = company_design(knowledge("## Design tokens\n\nNot written yet."))  # type: ignore[arg-type]
    assert missing["source"] == "default" and "no design tokens block" in missing["about"]
    broken = company_design(knowledge('```json\n{"colors": {"brand": "#000000",}}\n```'))  # type: ignore[arg-type]
    assert broken["source"] == "default" and "not valid JSON" in broken["problems"][0]
    assert tokens_block('```json\n{"other": 1}\n```\n```json\n{"sizes": {"title": 30}}\n```')[0] == {"sizes": {"title": 30}}
    assert merge({})[0] == DEFAULT


# --- In a run --------------------------------------------------------------------------------------------------------


@pytest.fixture
def scripted(tmp_path: Path) -> Iterator[tuple[TestClient, ScriptedRuntime]]:
    runtime = ScriptedRuntime()
    with TestClient(create_app(make_settings(tmp_path), runtime=runtime)) as client:  # type: ignore[arg-type]
        login(client, "u-ceo")
        yield client, runtime


def finished(run: dict[str, Any]) -> dict[str, Any]:
    return next(e for e in run["events"] if e["type"] == "run_finished")["payload"]


def test_powerpoint_output_asks_the_storyline_then_makes_and_changes_the_deck(scripted):
    client, runtime = scripted
    outcomes: list[tuple[bool, str]] = []

    async def first(request, emit, tools):
        outcomes.append(await tools.call("wizard_render_visual", CHART))
        outcomes.append(await tools.call("wizard_propose_storylines", {"storylines": [
            {"title": STORY, "arc": ["Q3 beat plan", "Flagship drove it"]}, {"title": "A segment review", "arc": ["Flagship", "Mass"]}]}))
        outcomes.append(await tools.call("wizard_lookup_definitions", {"query": "sell-out"}))
        outcomes.append(await tools.call("wizard_ask_person", {"question": "Which market?", "options": ["UAE", "KSA"]}))
        await say(emit, "Which story should the deck tell?")

    runtime.script = first
    started = client.post("/api/v1/runs", json={"question": "Q3 review deck", "output": "presentation"}, headers=HEADERS)
    run = wait_run(client, started.json()["run_id"])
    assert run["status"] == "succeeded" and run["output"] == "presentation"
    assert "<output>\nThe person chose PowerPoint" in runtime.requests[0].prompt
    assert {"wizard_propose_storylines", "wizard_make_presentation", "wizard_change_presentation"} <= set(runtime.offered[0])
    assert json.loads(outcomes[2][1])["error"]["code"] == "asked_person", "no more data once the storyline is asked"
    assert json.loads(outcomes[3][1])["error"]["code"] == "already_asked", "one question per request"
    proposed = next(e for e in run["events"] if e["type"] == "storylines_proposed")["payload"]
    assert [s["title"] for s in proposed["storylines"]] == [STORY, "A segment review"]
    step = next(e for e in run["events"] if e["type"] == "tool_finished" and e["payload"]["name"] == "wizard_propose_storylines")
    assert step["payload"]["summary"].startswith("waiting for your storyline: " + STORY)

    async def second(request, emit, tools):
        outcomes.append(await tools.call("wizard_make_presentation", deck([COVER, {"kind": "chart", "title": "Flagship grew", "visual": "V1"}])))
        await say(emit, "Here is the deck.\n\n[D1]\n")

    runtime.script = second
    conversation = run["conversation_id"]
    chosen = client.post("/api/v1/runs", json={"question": f"Storyline: {STORY}", "conversation_id": conversation,
                                               "output": "presentation"}, headers=HEADERS)
    made = wait_run(client, chosen.json()["run_id"])
    prompt = runtime.requests[1].prompt
    assert "<visuals_in_this_conversation>" in prompt and "- V1: bar, “Sell-out by segment” (Q2, Q3), 2 rows" in prompt
    assert made["decks"][0]["id"] == "D1" and made["decks"][0]["slides"][1]["visual"] == "V1"
    assert next(e for e in made["events"] if e["type"] == "deck_added")["payload"]["deck"]["id"] == "D1"
    assert not finished(made)["warnings"]

    async def third(request, emit, tools):
        outcomes.append(await tools.call("wizard_change_presentation", {"deck": "D1", "changes": [
            {"action": "update", "at": 2, "slide": {"title": "Flagship grew 18% in Q3"}}]}))
        await say(emit, "Changed.\n\n[D2]\n\n[D9]")

    runtime.script = third
    asked = client.post("/api/v1/runs", json={"question": "Make slide 2's title say by how much", "conversation_id": conversation},
                        headers=HEADERS)
    changed = wait_run(client, asked.json()["run_id"])
    prompt = runtime.requests[2].prompt
    assert "<presentations_in_this_conversation>" in prompt and "  2. chart: Flagship grew [V1]" in prompt
    assert "<output>" not in prompt and changed["output"] == "analysis"
    assert changed["decks"][0]["revises"] == "D1" and changed["decks"][0]["version"] == 2
    assert "The answer refers to presentations that were not made: D9." in finished(changed)["warnings"]
    full = client.get(f"/api/v1/conversations/{conversation}").json()
    assert [d["id"] for r in full["runs"] for d in r["decks"]] == ["D1", "D2"]


def test_nobody_is_asked_for_a_storyline_where_nobody_is_waiting(scripted):
    client, runtime = scripted
    outcome: list[tuple[bool, str]] = []

    async def script(request, emit, tools):
        outcome.append(await tools.call("wizard_propose_storylines", {"storylines": [
            {"title": STORY, "arc": ["a", "b"]}, {"title": "Another story", "arc": ["c", "d"]}]}))
        await say(emit, "Done.")

    runtime.script = script
    first = wait_run(client, client.post("/api/v1/runs", json={"question": "Deck?"}, headers=HEADERS).json()["run_id"])
    check = client.post(f"/api/v1/runs/{first['id']}/check", headers=HEADERS).json()
    wait_run(client, check["run_id"])
    assert "wizard_propose_storylines" not in runtime.offered[1]
    refused = json.loads(outcome[1][1])["error"]
    assert refused["code"] == "no_one_to_ask" and "Choose the storyline the evidence supports best" in refused["message"]


def test_the_prompt_says_how_presentations_are_made():
    prompt = system_prompt()
    assert "wizard_propose_storylines" in prompt and "wizard_change_presentation" in prompt
    assert "full-sentence takeaway" in prompt
    request = compose("Deck", [], "check", __import__("datetime").date(2026, 11, 13), output="presentation")
    assert "<output>" not in request, "only a question takes the Output"
