"""Settings → Source order (owner, 2 Nov 2026): the company's order of the data sources, its levels and "use it for"
lines, sources used only when asked, the prompt's <where_to_start> block, Auto without those sources (and Gemini asking
for one), validation, Settings, provisioning and export. Every source line and name here is invented."""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, login, make_settings, wait_run
from tests.integration.test_steering_api import ScriptedRuntime, say

from wizard_agent.prompting import compose, where_to_start_block
from wizard_api import provisioning, settings_pane, source_order, systems
from wizard_api.app import create_app
from wizard_api.config import ConfigError, load_settings
from wizard_api.source_order import DEFAULT, Entry, OrderError
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.tools import build_services
from wizard_connectors.tools.systems import ASK_FOR_SYSTEM, SystemChoice, offered

KEY = "WIZARD_SOURCE_ORDER"
ALL = {"dashboards": "Dashboards", "asap": "ASAP", "gscm": "GSCM", "nerp": "NERP", "bdp": "Big Data Portal",
       "postgresql": "AI Team Database"}
# NERP kept for when someone asks, ASAP and GSCM on one level with a line each.
ORDER = json.dumps([{"id": "asap", "use": "Customer segmentation by age and channel"},
                    {"id": "gscm", "same": True, "use": "Stock and shipments by week"},
                    {"id": "nerp", "when_asked": True, "use": "Spend and budget"}])


def ids(levels: list[list[tuple[str, Entry]]]) -> list[list[str]]:
    return [[source for source, _ in level] for level in levels]


# The setting -------------------------------------------------------------------------------------------------------
def test_the_default_order_is_the_owners():
    """Owner, 2 Nov 2026: dashboards, then the database, then ASAP/GSCM, then NERP, then the Big Data Portal."""
    assert source_order.parse("") is None and source_order.parse(None) is None
    assert ids(source_order.levels(None, ALL)) == [["dashboards"], ["postgresql"], ["asap", "gscm"], ["nerp"], ["bdp"]]
    assert source_order.view(None)[3] == {"id": "gscm", "same": True}


def test_reordered_levels_lines_and_only_when_asked_are_read_back():
    entries = source_order.parse('[{"id":"postgresql","use":"Weekly and daily detail"},{"id":"dashboards","same":true},'
                                 '{"id":"bdp","when_asked":true}]')
    assert entries == (Entry("postgresql", use="Weekly and daily detail"), Entry("dashboards", same=True),
                       Entry("bdp", when_asked=True))
    assert ids(source_order.levels(entries, ALL)) == [["postgresql", "dashboards"], ["bdp"], ["asap"], ["gscm"], ["nerp"]], \
        "the sources it does not name come last, each on a level of its own"
    assert source_order.held_back(entries, ALL) == {"bdp"} and source_order.held_back(entries, ["asap"]) == set()
    assert source_order.render(entries) == ('[{"id":"postgresql","use":"Weekly and daily detail"},'
                                            '{"id":"dashboards","same":true},{"id":"bdp","when_asked":true}]')
    assert source_order.parse('[{"id":"asap","same":true}]') == (Entry("asap"),), "the first source has no level above"
    assert source_order.parse("[]") == ()
    assert source_order.parse(source_order.render([Entry("asap", use="  Segments\tby   age ")])) == (Entry("asap", use="Segments by age"),)


def test_unknown_sources_go_last_and_missing_ones_are_ignored():
    here = {"gscm": "GSCM", "postgresql": "AI Team Database", "crm": "CRM portal"}
    levels = source_order.levels(source_order.parse(ORDER), here)
    assert ids(levels) == [["gscm"], ["postgresql"], ["crm"]], \
        "GSCM keeps a level of its own when its level-mate ASAP is missing; NERP is not on this PC; a new portal is last"
    assert ids(source_order.levels(None, ALL, allowed={"nerp", "asap", "knowledge"})) == [["asap"], ["nerp"]]


@pytest.mark.parametrize(("text", "words"), [
    ("{", "not valid JSON"),
    ('{"id":"asap"}', "must be a list"),
    ('["asap"]', "an object with an id"),
    ('[{"id":"ASAP!"}]', "not a source id"),
    ('[{"id":"knowledge"}]', "not a data source to order"),
    ('[{"id":"asap"},{"id":"asap"}]', "named twice"),
    ('[{"id":"asap","first":true}]', "first is not part of"),
    ('[{"id":"asap","same":"yes"}]', "same must be true or false"),
    ('[{"id":"asap","use":7}]', "use must be text"),
    (json.dumps([{"id": "asap", "use": "x" * 201}]), "at most 200 characters"),
    ('[{"id":"asap","use":"<b>segments</b>"}]', "plain text"),
    (json.dumps([{"id": f"s{i}"} for i in range(41)]), "more than 40"),
])
def test_an_invalid_order_is_refused(text, words):
    with pytest.raises(OrderError, match=words):
        source_order.parse(text)


def test_an_invalid_order_stops_loading_with_a_clear_message(tmp_path):
    with pytest.raises(ConfigError, match="WIZARD_SOURCE_ORDER .Settings → Source order.: asap is named twice"):
        make_settings(tmp_path, **{KEY: '[{"id":"asap"},{"id":"asap"}]'})
    assert make_settings(tmp_path, **{KEY: ORDER}).source_order == source_order.parse(ORDER)


# The prompt --------------------------------------------------------------------------------------------------------
def test_the_where_to_start_block_lists_the_levels_and_the_sufficiency_test():
    levels = source_order.for_prompt(source_order.parse(ORDER), {"asap": "ASAP", "gscm": "GSCM", "nerp": "NERP"})
    assert levels == [[("ASAP", "Customer segmentation by age and channel"), ("GSCM", "Stock and shipments by week")],
                      [("NERP", "Spend and budget")]]
    block = where_to_start_block(levels)
    assert block.startswith("<where_to_start>") and block.endswith("</where_to_start>")
    assert ("1. ASAP (use it for: Customer segmentation by age and channel); GSCM (use it for: Stock and shipments by "
            "week)\n2. NERP (use it for: Spend and budget)") in block
    for rule in ("Start with the first source in this order that holds what is asked",
                 "covers the measure, every breakdown asked for, the period, the markets and the granularity",
                 "A study or analysis needs every breakdown the sources hold for the measure",
                 "when its as-of is too old for the question", "\"ASAP has the segmentation\"",
                 "Before you use a later source because an earlier one is stale, say so outright",
                 "Sources on one level: choose by coverage", "When you stop early, say in one line",
                 "a metric's \"Where to get it\"", "Within a portal, its map comes before its menu"):
        assert rule in block, rule
    plain = where_to_start_block([[("Dashboards", "")], [("AI Team Database", "")]])
    assert "1. Dashboards\n2. AI Team Database\n" in plain


def test_the_block_is_limited_to_the_runs_sources_and_absent_for_one_source():
    entries = source_order.parse(ORDER)
    assert source_order.for_prompt(entries, {"asap": "ASAP"}) is None, "one source: nothing to order"
    assert source_order.for_prompt(entries, ALL, allowed={"gscm", "knowledge"}) is None
    assert source_order.for_prompt(entries, ALL, allowed={"gscm", "nerp"}) == [[("GSCM", "Stock and shipments by week")],
                                                                               [("NERP", "Spend and budget")]]
    prompt = compose("Attach rate by age?", [], "ask", date(2026, 11, 2), order=[[("ASAP", "")], [("NERP", "")]],
                     when_asked=["NERP"])
    assert prompt.index("<calendar>") < prompt.index("<systems>") < prompt.index("<where_to_start>") < prompt.index("<request>")
    assert "except the ones the company uses only when asked: NERP." in prompt and "wizard_ask_for_system" in prompt
    assert "<where_to_start>" not in compose("q", [], "ask", date(2026, 11, 2))


# Auto and "only when asked" ------------------------------------------------------------------------------------------
def ceo() -> Identity:
    rights = {s: SystemRights(reports=["*"], markets=["*"]) for s in ("asap", "gscm", "nerp")}
    return Identity(id="c", email="c@corp.test", name="C", role="CEO", entitlements=rights)


def test_auto_leaves_out_the_sources_used_only_when_asked(tmp_path):
    settings = make_settings(tmp_path, **{KEY: ORDER})
    services = build_services()
    listed = {s["id"]: s for s in systems.available(settings, services, ceo())}
    assert listed["nerp"]["only_when_asked"] is True and "only_when_asked" not in listed["asap"]
    auto = systems.choice(settings, services, ceo(), None)
    assert auto is not None and auto.auto and auto.chosen() is None
    assert "nerp" not in auto.on and {"asap", "gscm", "knowledge", "attachment"} <= auto.on and auto.off() == ["nerp"]
    catalogs = portals = ["asap", "gscm", "nerp"]
    assert not offered("nerp_run_report", auto, catalogs, portals) and offered("asap_run_report", auto, catalogs, portals)
    assert offered(ASK_FOR_SYSTEM, auto, catalogs, portals)
    assert "used only when the person asks for it" in auto.why_off("nerp")
    picked = systems.choice(settings, services, ceo(), ["nerp", "asap"])
    assert picked is not None and not picked.auto and picked.allows("nerp"), "a source picked explicitly is used"
    assert systems.choice(make_settings(tmp_path / "default"), services, ceo(), None) is None, "nothing held back: Auto"
    assert systems.sources(settings, services, ceo()) == {"asap": "ASAP", "gscm": "GSCM", "nerp": "NERP"}


@pytest.fixture
def ordered(tmp_path: Path) -> Iterator[tuple[TestClient, ScriptedRuntime]]:
    runtime = ScriptedRuntime()
    with TestClient(create_app(make_settings(tmp_path, **{KEY: ORDER}), runtime=runtime)) as client:  # type: ignore[arg-type]
        login(client, "u-ceo")
        yield client, runtime


def test_in_auto_a_source_used_only_when_asked_is_not_offered_and_gemini_asks_for_it(ordered):
    client, runtime = ordered
    outcomes: list[tuple[bool, str]] = []

    async def script(request, emit, tools):
        outcomes.append(await tools.call("nerp_search_reports", {"query": "spend"}))
        outcomes.append(await tools.call("wizard_list_sources", {}))
        outcomes.append(await tools.call(ASK_FOR_SYSTEM, {"system": "NERP", "reason": "Spend lives in NERP."}))
        await say(emit, "ASAP has the segmentation; NERP would add spend.")

    runtime.script = script
    started = client.post("/api/v1/runs", json={"question": "Warranty attach rate by customer age?"}, headers=HEADERS)
    run = wait_run(client, started.json()["run_id"])
    assert run["status"] == "succeeded" and run["systems"] is None, "stored and shown as Auto"
    offered_tools = runtime.offered[0]
    assert not [t for t in offered_tools if t.startswith("nerp_")] and "asap_run_report" in offered_tools
    assert ASK_FOR_SYSTEM in offered_tools
    refused = json.loads(outcomes[0][1])["error"]
    assert refused["code"] == "system_off" and "NERP is used only when the person asks for it" in refused["message"]
    listed = json.loads(outcomes[1][1])
    assert "nerp" not in [s["system"] for s in listed["sources"]] and "only when the person asks" in listed["note"]
    assert json.loads(outcomes[2][1])["system"] == "nerp"
    requested = next(e for e in run["events"] if e["type"] == "system_requested")["payload"]
    assert requested == {"system": "nerp", "name": "NERP", "reason": "Spend lives in NERP."}
    prompt = runtime.requests[0].prompt
    assert "Auto: every system this person can use is on, except the ones the company uses only when asked: NERP." in prompt
    assert ("1. ASAP (use it for: Customer segmentation by age and channel); GSCM (use it for: Stock and shipments by "
            "week)\n- Start with") in prompt, "the block holds only the sources this run may use"
    bootstrap = {s["id"]: s for s in client.get("/api/v1/bootstrap").json()["systems"]}
    assert bootstrap["nerp"]["only_when_asked"] is True

    # The person switches NERP on (the button under the answer): an explicit choice, NERP in the order again.
    runtime.script = script
    chosen = client.post("/api/v1/runs", json={"question": "Continue with NERP switched on.", "conversation_id": run["conversation_id"],
                                               "systems": ["asap", "gscm", "nerp", "knowledge", "attachment"]}, headers=HEADERS)
    again = wait_run(client, chosen.json()["run_id"])
    assert again["systems"] == ["asap", "gscm", "nerp", "knowledge", "attachment"]
    assert "nerp_run_report" in runtime.offered[1] and json.loads(outcomes[3][1]).get("results") is not None
    assert "2. NERP (use it for: Spend and budget)" in runtime.requests[1].prompt
    assert "only when asked" not in runtime.requests[1].prompt.split("<where_to_start>")[0]


def test_check_my_data_after_an_auto_answer_keeps_the_source_held_back(ordered):
    client, runtime = ordered

    async def script(request, emit, tools):
        await say(emit, "Done.")

    runtime.script = script
    first = wait_run(client, client.post("/api/v1/runs", json={"question": "Share?"}, headers=HEADERS).json()["run_id"])
    check = client.post(f"/api/v1/runs/{first['id']}/check", headers=HEADERS).json()
    assert wait_run(client, check["run_id"])["systems"] is None
    assert not [t for t in runtime.offered[1] if t.startswith("nerp_")] and ASK_FOR_SYSTEM in runtime.offered[1]
    assert "<where_to_start>" not in runtime.requests[1].prompt, "a check replays evidence; the order is for questions"


def test_switching_back_to_auto_mid_run_keeps_the_held_back_source_off(ordered):
    client, runtime = ordered
    seen: dict[str, Any] = {}

    async def script(request, emit, tools):
        from tests.integration.test_steering_api import until_note
        seen["note"] = await until_note(tools)
        seen["nerp"] = await tools.call("nerp_search_reports", {"query": "spend"})
        await say(emit, "Done.")

    runtime.script = script
    started = client.post("/api/v1/runs", json={"question": "Stock?", "systems": ["gscm"]}, headers=HEADERS).json()
    assert client.post(f"/api/v1/runs/{started['run_id']}/systems", json={"systems": None}, headers=HEADERS).status_code == 200
    run = wait_run(client, started["run_id"])
    assert run["systems"] is None and json.loads(seen["nerp"][1])["error"]["code"] == "system_off"
    assert "Auto now: every system is on, except the ones the company uses only when asked: NERP." in seen["note"][0]


# Settings, provisioning and export ----------------------------------------------------------------------------------
def install(tmp_path: Path, **env: str) -> Any:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_text("WIZARD_AGENT_RUNTIME=code-assist\nWIZARD_LOCAL_USER_NAME=Rafael\n", encoding="utf-8")
    return load_settings(env={"WIZARD_PROXY": "direct", **env}, home=tmp_path)


def test_settings_show_the_order_and_save_it_compact(tmp_path):
    with TestClient(create_app(install(tmp_path))) as client:
        login(client, "local-owner")
        view = client.get("/api/v1/settings").json()
        assert next(s for s in view["sections"] if s["id"] == "sources")["title"] == "Source order"
        found = next(f for f in view["fields"] if f["key"] == KEY)
        assert found["section"] == "sources" and found["source"] == "default" and found["value"] == ""
        assert view["source_order"]["default"] == [e.as_dict() for e in DEFAULT] and view["source_order"]["max_use"] == 200
        assert [s["id"] for s in view["source_order"]["sources"]] == ["asap", "gscm", "nerp"]
        assert any(f["key"] == "WIZARD_PG_SCHEMAS" and f["section"] == "postgres" for f in view["fields"])
        long_line = json.dumps([{"id": f"portal{i}", "use": "y" * 190} for i in range(12)], indent=1).replace("\n", " ")
        assert len(long_line) > 2000
        saved = client.put("/api/v1/settings", json={"values": {KEY: long_line}}, headers=HEADERS)
        assert saved.status_code == 200, saved.text
        stored = provisioning.load(client.app.state.settings.data_dir, layer="local").settings[KEY]
        assert stored.startswith('[{"id":"portal0","use":"yyy') and " " not in stored, "kept compact, one line"
        refused = client.put("/api/v1/settings", json={"values": {KEY: '[{"id":"nerp"},{"id":"nerp"}]'}}, headers=HEADERS)
        assert refused.status_code == 400 and "Source order: nerp is named twice" in refused.json()["error"]
        schemas = client.put("/api/v1/settings", json={"values": {"WIZARD_PG_HOST": "db.corp.example", "WIZARD_PG_USER": "ro",
                                                                   "WIZARD_PG_SCHEMAS": "reporting, Bad Name"}}, headers=HEADERS)
        assert schemas.status_code == 400 and "schema names separated by commas" in schemas.json()["error"]


def test_the_order_and_the_schemas_travel_in_the_company_file_and_export(tmp_path):
    company = tmp_path / "company.provision"
    company.write_text(provisioning.render({KEY: ORDER, "WIZARD_PG_HOST": "db.corp", "WIZARD_PG_USER": "ro",
                                            "WIZARD_PG_SCHEMAS": "reporting"}, "ACME Wizard"), encoding="utf-8")
    settings = install(tmp_path)
    provisioning.import_file(company, settings.data_dir)
    settings = install(tmp_path)
    assert settings.source_order == source_order.parse(ORDER) and settings.postgres is not None
    assert settings.postgres.schemas == ("reporting",)
    provisioning.update_local(settings.data_dir, {KEY: '[{"id":"gscm"},{"id":"asap","same":true}]'})
    exported = provisioning.parse(settings_pane.export(install(tmp_path))["text"]).values()
    assert exported[KEY] == '[{"id":"gscm"},{"id":"asap","same":true}]', "this PC's order beats the company file's"
    assert exported["WIZARD_PG_SCHEMAS"] == "reporting"
    other = tmp_path / "other"
    offered_file = tmp_path / "wizard.provision"
    offered_file.write_text(settings_pane.export(install(tmp_path))["text"], encoding="utf-8")
    provisioning.import_file(offered_file, other / "data")
    again = load_settings(env={"WIZARD_PROXY": "direct", "WIZARD_DATA_DIR": str(other / "data")}, home=other)
    assert again.source_order == (Entry("gscm"), Entry("asap", same=True))


def test_a_choice_is_never_auto_when_the_person_picked(tmp_path):
    names = {"asap": "ASAP", "nerp": "NERP"}
    assert SystemChoice(frozenset({"asap"}), names).chosen() == ["asap"]
    assert SystemChoice(frozenset({"asap"}), names, auto=True).chosen() is None
    assert SystemChoice(frozenset({"asap"}), names).why_off("nerp") == "NERP is switched off for this request"
