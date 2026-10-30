"""Steering and the systems picker, below the API: the prompt pieces, what a follow-up knows of earlier steps, which system
each tool reads, and Code Assist handing the person's notes to Gemini between steps."""
from __future__ import annotations

import asyncio
import json
from datetime import date

from tests.unit.test_code_assist import Bridge, FakeGoogle, make

from wizard_agent.prompting import STOPPED, compose, correction_question, steer_text, systems_changed_text
from wizard_agent.runtime import Turn
from wizard_api.runs import step_about, work_log
from wizard_connectors.tools.systems import ASK_FOR_SYSTEM, SystemChoice, offered, system_of

SQL = "SELECT market, SUM(units) FROM sales.raw_sellout WHERE week >= 40 GROUP BY 1"
EVENTS = [
    {"type": "tool_started", "payload": {"call_id": "c1", "name": "wizard_lookup_definitions", "label": "Looked up “sell-out”",
                                         "category": "knowledge", "arguments": {"query": "sell-out"}}},
    {"type": "tool_finished", "payload": {"call_id": "c1", "name": "wizard_lookup_definitions", "ok": True,
                                          "summary": "Sell-out"}},
    {"type": "tool_started", "payload": {"call_id": "c2", "name": "wizard_query_postgresql", "label": "Queried the AI Team Database",
                                         "category": "source", "arguments": {"sql": SQL}}},
    {"type": "tool_finished", "payload": {"call_id": "c2", "name": "wizard_query_postgresql", "ok": True, "summary": "12 rows",
                                          "evidence": {"id": "E3"}}},
    {"type": "tool_started", "payload": {"call_id": "c3", "name": "wizard_render_visual", "label": "Prepared a bar: Units",
                                         "category": "present", "arguments": {"title": "Units"}}},
    {"type": "tool_finished", "payload": {"call_id": "c3", "name": "wizard_render_visual", "ok": True, "summary": "V1 ready"}},
    {"type": "steer", "payload": {"steer": {"text": "use the weekly view", "reason": "table",
                                            "about": {"label": "Queried the AI Team Database", "evidence_id": "E3"}}}},
]


def test_a_step_is_named_by_its_sql_and_evidence():
    about = step_about(EVENTS, "c2")
    assert about == {"call_id": "c2", "name": "wizard_query_postgresql", "label": "Queried the AI Team Database",
                     "detail": SQL, "evidence_id": "E3"}
    assert step_about(EVENTS, "c9") is None


def test_the_work_log_keeps_what_was_read_and_the_persons_notes():
    lines = work_log(EVENTS)
    assert lines[0] == "Looked up “sell-out” -> Sell-out"
    assert lines[1] == f"Queried the AI Team Database: {SQL} -> 12 rows [E3]"
    assert not any("Prepared a bar" in line for line in lines), "presenting is not reading"
    assert lines[2].startswith("The person's note about Queried the AI Team Database, evidence E3: use the weekly view")
    many = [e for i in range(20) for e in (
        {"type": "tool_started", "payload": {"call_id": f"c{i}", "label": f"step {i}", "category": "source", "arguments": {}}},
        {"type": "tool_finished", "payload": {"call_id": f"c{i}", "ok": i != 19, "summary": "done"}})]
    capped = work_log(many)
    assert len(capped) == 15 and capped[0] == "(6 earlier steps not shown)" and capped[-1] == "step 19 -> failed: done"


def test_a_follow_up_prompt_carries_the_earlier_steps_the_systems_and_remembered_notes():
    prompt = compose("Use the weekly view instead", [Turn("Units by market?", "EG sold 12 [E3].", work_log(EVENTS)),
                                                     Turn("And Q2?", STOPPED, [])], "ask", date(2026, 10, 30),
                     systems=(["AI Team Database", "Knowledge base"], ["ASAP", "GSCM"]),
                     remembered=["For sell-out use sales.mv_sellout_weekly."])
    assert "<remembered_by_this_person>" in prompt and "- For sell-out use sales.mv_sellout_weekly." in prompt
    assert "On: AI Team Database, Knowledge base." in prompt and "Switched off: ASAP, GSCM." in prompt
    assert "wizard_ask_for_system" in prompt
    assert f"What Wizard did for it:\n- Looked up “sell-out” -> Sell-out\n- Queried the AI Team Database: {SQL}" in prompt
    assert f"User: And Q2?\nWizard: {STOPPED}" in prompt
    assert prompt.index("<remembered_by_this_person>") < prompt.index("<request>")
    auto = compose("q", [], "ask", date(2026, 10, 30))
    assert "<systems>" not in auto and "<remembered_by_this_person>" not in auto, "Auto and no notes change nothing"


def test_a_note_reads_as_the_persons_instruction_about_one_step():
    about = step_about(EVENTS, "c2")
    text = steer_text("use sales.mv_sellout_weekly", about, "table", "12:03")
    assert text.startswith("<note_from_the_person at='12:03'>") and text.endswith("</note_from_the_person>")
    assert "It is about one of your steps: Queried the AI Team Database (SELECT market" in text
    assert "The person says: wrong table." in text and "Their words: use sales.mv_sellout_weekly" in text
    assert "Do not use or cite E3 in your answer." in text
    plain = steer_text("only Gulf markets")
    assert "about one of your steps" not in plain and "cite" not in plain
    assert correction_question("use the weekly view", about, "table") == (
        "Not this step: Queried the AI Team Database [E3], wrong table. use the weekly view Redo the answer.")
    assert correction_question("only Gulf markets") == "only Gulf markets"
    changed = systems_changed_text(["GSCM"], ["ASAP"], ["GSCM"], ["ASAP"])
    assert "switched on GSCM; switched off ASAP" in changed and "Their tools refuse." in changed


def test_each_tool_reads_one_system_and_wizards_own_work_reads_none():
    assert system_of("wizard_query_postgresql") == "postgresql"
    assert system_of("asap_run_report") == "asap" and system_of("nerp_search_reports") == "nerp"
    assert system_of("portal_run", {"system": "gscm"}) == "gscm"
    assert system_of("wizard_read_knowledge") == "knowledge" and system_of("wizard_query_attachment") == "attachment"
    for own in ("wizard_calculate", "wizard_render_visual", "wizard_check_my_data", "wizard_schedule_brief",
                "wizard_search_catalog", "wizard_list_sources", ASK_FOR_SYSTEM):
        assert system_of(own) is None, own


def test_only_the_chosen_systems_tools_are_offered():
    names = {"postgresql": "AI Team Database", "asap": "ASAP", "gscm": "GSCM", "knowledge": "Knowledge base"}
    choice = SystemChoice(frozenset({"postgresql", "knowledge"}), names)
    catalogs, portals = ["asap", "gscm"], ["asap", "gscm"]
    assert offered("wizard_query_postgresql", choice, catalogs, portals)
    assert offered("wizard_lookup_definitions", choice, catalogs, portals)
    assert not offered("asap_run_report", choice, catalogs, portals)
    assert not offered("portal_run", choice, catalogs, portals) and not offered("wizard_search_catalog", choice, catalogs, portals)
    assert offered("wizard_calculate", choice, catalogs, portals) and offered(ASK_FOR_SYSTEM, choice, catalogs, portals)
    gscm = SystemChoice(frozenset({"gscm"}), names)
    assert offered("portal_run", gscm, catalogs, portals) and offered("wizard_search_catalog", gscm, catalogs, portals)
    assert offered("asap_run_report", None, catalogs, portals) and not offered(ASK_FOR_SYSTEM, None, catalogs, portals)
    assert choice.off() == ["asap", "gscm"] and choice.name("nerp") == "NERP"


def run_code_assist(tmp_path, fake: FakeGoogle, bridge: Bridge) -> list[tuple[str, dict]]:
    rt, req = make(tmp_path, fake)
    events: list[tuple[str, dict]] = []

    async def emit(kind, payload):
        events.append((kind, payload))

    asyncio.run(rt.run(req, emit, bridge, lambda: False))
    return events


def call(name: str, **args) -> dict:
    return {"functionCall": {"name": name, "args": args}}


def test_a_note_sent_mid_step_stops_the_rest_of_the_step_and_reaches_gemini_next(tmp_path):
    fake = FakeGoogle([
        [call("nerp_run_report", report_id="a"), call("nerp_run_report", report_id="b"), call("nerp_run_report", report_id="c")],
        [{"text": "Using the weekly view [E1]."}],
    ])
    bridge = Bridge()
    bridge.on_call = lambda name: bridge.steers.append("<note_from_the_person>use the weekly view</note_from_the_person>") \
        if len(bridge.calls) == 1 else None
    run_code_assist(tmp_path, fake, bridge)
    assert [args["report_id"] for _, args in bridge.calls] == ["a"], "the calls after the note were not run"
    turn = fake.requests[1]["request"]["contents"][-1]
    assert turn["role"] == "user"
    responses = [p["functionResponse"] for p in turn["parts"] if "functionResponse" in p]
    assert [r["response"].get("error", {}).get("code") for r in responses] == [None, "not_run", "not_run"]
    assert turn["parts"][-1] == {"text": "<note_from_the_person>use the weekly view</note_from_the_person>"}


def test_a_note_sent_while_gemini_writes_its_answer_reopens_the_work(tmp_path):
    fake = FakeGoogle([[{"text": "EG leads."}], [{"text": "With Gulf markets only, KSA leads."}]])
    bridge = Bridge()
    bridge.steers.append("only Gulf markets")
    original_take = bridge.take_steers
    taken: list[list[str]] = []

    async def take_late():  # the note arrives after the first step began: it waits for the answer to finish
        if not fake.requests:
            return []
        notes = await original_take()
        if notes:
            taken.append(notes)
        return notes

    bridge.take_steers = take_late  # type: ignore[method-assign]
    events = run_code_assist(tmp_path, fake, bridge)
    assert len(fake.requests) == 2 and taken == [["only Gulf markets"]]
    contents = fake.requests[1]["request"]["contents"]
    assert contents[-2] == {"role": "model", "parts": [{"text": "EG leads."}]}
    assert contents[-1] == {"role": "user", "parts": [{"text": "only Gulf markets"}]}
    assert events[-1][0] == "agent_stats"


def test_a_system_switched_on_mid_run_brings_its_tools_at_the_next_step(tmp_path):
    fake = FakeGoogle([[call("nerp_run_report", report_id="a")], [{"text": "done"}]])
    bridge = Bridge()
    tools = bridge.describe()
    extra = {"name": "gscm_run_report", "description": "d", "inputSchema": {"type": "object", "properties": {}}}
    bridge.describe = lambda: tools + ([extra] if bridge.calls else [])  # type: ignore[method-assign]
    run_code_assist(tmp_path, fake, bridge)
    offered_names = [[d["name"] for d in r["request"]["tools"][0]["functionDeclarations"]] for r in fake.requests]
    assert offered_names == [["nerp_run_report"], ["nerp_run_report", "gscm_run_report"]]
    assert json.dumps(fake.requests[0]).count("gscm") == 0
