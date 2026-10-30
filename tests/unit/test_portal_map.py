"""The portal map (owner, 30 Oct 2026): what Gemini learned exploring a portal, kept on this PC, read first by later
questions, published to the knowledge base with the write token entered on this PC, and the rounds of a mapping run
that follow one another until nothing is left to map. Gemini is scripted here; the browser is not needed."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import HEADERS, MemoryRecorder, ask, login, make_settings

from wizard_agent.prompting import compose
from wizard_agent.runtime import AgentFailure
from wizard_api import provisioning
from wizard_api.app import create_app
from wizard_connectors.content import errors, validate_content
from wizard_connectors.entitlements import Identity, SystemRights
from wizard_connectors.portal_browser import PortalBrowsers
from wizard_connectors.portal_map import PortalMaps, Published, render
from wizard_connectors.portals import settings_from
from wizard_connectors.tools import ToolContext, build_registry, build_services

TOKEN = "Tk" + "x" * 50
REPORTS = [{"id": "as470", "name": "Actual Sales", "path": ["SCM", "Sales", "Actual Sales"], "menu_id": "AS470"},
           {"id": "as480", "name": "Weekly Sell-out", "path": ["SCM", "Sales", "Weekly Sell-out"], "menu_id": "AS480"},
           {"id": "mt100", "name": "Model master", "path": ["MDM", "Model master"], "menu_id": "MT100"}]


def test_the_map_merges_what_each_save_adds_and_finds_reports_by_business_words(tmp_path: Path):
    maps = PortalMaps(tmp_path / "maps", names={"gscm": "GSCM"})
    assert maps.status("gscm")["source"] == "none" and maps.summary("gscm")["counts"]["todo"] == 0
    first = maps.save("gscm", overview="A Nexacro client.", reports=REPORTS, note="Listed the menu.")
    assert first["added"] == ["as470", "as480", "mt100"] and first["counts"]["todo"] == 3
    maps.save("gscm", topics=[{"id": "open-report", "title": "Open a report by menu id",
                               "text": "application.gfn_openMenu('AS470') opens it in a new WorkFrame."}],
              reports=[{"id": "as480", "status": "mapped", "summary": "Sell-out units by market and week.",
                        "filters": [{"name": "Week", "kind": "Calendar", "values": "YYYYWW", "param": "week"}],
                        "requests": [{"name": "search", "method": "POST", "url": "/gscm/selectSellout.do",
                                      "body": "SSV:utf-8\x1eweek:string={{week}}", "params": ["week"], "verified": True}]}])
    report = maps.report("gscm", "AS480")
    assert report and report["name"] == "Weekly Sell-out" and report["status"] == "mapped", "kept fields and the new ones"
    assert report["requests"][0]["body"].endswith("{{week}}")
    assert [r["id"] for r in maps.find("gscm", "weekly sell-out by market")][:1] == ["as480"]
    assert [r["id"] for r in maps.todo("gscm")] == ["as470", "mt100"]
    summary = maps.summary("gscm")
    assert summary["overview"] == "A Nexacro client." and summary["counts"] == {"todo": 2, "mapped": 1, "partial": 0,
                                                                                 "failed": 0, "skipped": 0}
    assert summary["reports"] == [{"id": "as480", "name": "Weekly Sell-out", "path": "SCM > Sales > Weekly Sell-out",
                                   "status": "mapped", "fast": True}]
    assert summary["topics"][0]["text"].startswith("application.gfn_openMenu")
    maps.save("gscm", remove=["mt100"])
    assert maps.report("gscm", "mt100") is None and maps.load("gscm")["log"][0]["note"] == "Listed the menu."
    assert "Weekly Sell-out (mapped)" in render(maps.load("gscm"))
    assert maps.forget("gscm") and maps.status("gscm")["source"] == "none"


def test_a_map_keeps_no_secrets(tmp_path: Path):
    maps = PortalMaps(tmp_path / "maps")
    maps.save("gscm", reports=[{"id": "r1", "notes": f"session {TOKEN}", "requests": [
        {"name": "search", "url": "/x.do", "headers": {"Content-Type": "text/plain", "X-Auth-Token": "abc"}}]}])
    text = maps.path("gscm").read_text(encoding="utf-8")
    assert TOKEN not in text and '"X-Auth-Token": "<redacted>"' in text and '"Content-Type": "text/plain"' in text


def test_publishing_writes_the_map_and_a_readable_page_under_the_knowledge_base_folder(tmp_path: Path):
    sent: list[tuple[dict[str, bytes], str]] = []

    def writer(files: dict[str, bytes], message: str) -> Published:
        sent.append((files, message))
        return Published("published", "Committed.", "c0ffee")

    maps = PortalMaps(tmp_path / "maps", writer=writer, names={"gscm": "GSCM"}, repo_prefix="content")
    assert maps.publish("gscm").outcome == "unchanged", "nothing of this PC's own to publish yet"
    maps.save("gscm", overview="How it works.", reports=REPORTS[:1])
    result = maps.publish("gscm")
    assert result.outcome == "published" and result.commit == "c0ffee"
    files, message = sent[0]
    assert set(files) == {"content/portal-maps/gscm.json", "content/portal-maps/gscm.md"}
    assert json.loads(files["content/portal-maps/gscm.json"])["system"] == "gscm" and message.startswith("Wizard: GSCM map")
    assert maps.status("gscm")["published"]["commit"] == "c0ffee"
    maps.save("gscm", reports=[{"id": "as470", "notes": "token ghp_" + "a" * 36}])
    assert "ghp_" + "a" * 36 not in maps.path("gscm").read_text(encoding="utf-8"), "a long token is gone on save"
    maps.save("gscm", reports=[{"id": "as470", "notes": "password = 'hunter22x'"}])
    refused = maps.publish("gscm")
    assert refused.outcome == "failed" and "password assignment" in refused.message and len(sent) == 1
    assert PortalMaps(tmp_path / "other").publish("gscm").outcome == "not_configured"


def test_a_pc_without_its_own_map_starts_from_the_published_one(tmp_path: Path):
    published = tmp_path / "kb" / "portal-maps"
    published.mkdir(parents=True)
    (published / "gscm.json").write_text(json.dumps({"system": "gscm", "overview": "Shared.", "reports": REPORTS}), "utf-8")
    maps = PortalMaps(tmp_path / "maps", published)
    assert maps.status("gscm")["source"] == "knowledge_base" and maps.load("gscm")["overview"] == "Shared."
    maps.save("gscm", reports=[{"id": "as470", "status": "mapped"}])
    assert maps.status("gscm")["source"] == "this_pc" and maps.status("gscm")["reports"] == 3


def test_the_knowledge_base_checks_published_maps(tmp_path: Path):
    root = tmp_path / "content"
    (root / "portal-maps").mkdir(parents=True)
    (root / "portal-maps" / "gscm.json").write_text(json.dumps({"system": "gscm"}), "utf-8")
    assert not errors(validate_content(root)), "a map alone is content to load"
    (root / "portal-maps" / "asap.json").write_text(json.dumps({"system": "gscm", "x": "ghp_" + "b" * 36}), "utf-8")
    found = [str(p) for p in errors(validate_content(root))]
    assert any("GitHub token" in p for p in found) and any("match its file name" in p for p in found)


def test_the_write_token_is_chosen_on_the_pc_never_in_a_company_file(tmp_path: Path):
    with pytest.raises(provisioning.ProvisionError, match="set on each PC"):
        provisioning.parse(json.dumps({"wizard_provision": 1, "settings": {"WIZARD_KB_WRITE_TOKEN": "github_pat_x"}}))
    provisioning.update_local(tmp_path / "var", {"WIZARD_KB_REPO": "acme/kb", "WIZARD_KB_TOKEN": "read",
                                                 "WIZARD_KB_WRITE_TOKEN": "write"})
    settings = make_settings(tmp_path, WIZARD_AGENT_RUNTIME="code-assist")
    assert settings.kb_write_token == "write" and settings.kb_token == "read"
    from wizard_api import settings_pane
    field = settings_pane.BY_KEY["WIZARD_KB_WRITE_TOKEN"]
    assert field.section == "knowledge" and field.secret and "Contents read and write" in field.help


def test_the_mapping_request_names_the_portal_and_its_round():
    prompt = compose("Map GSCM (round 3)", [], "explore", __import__("datetime").date(2026, 10, 30),
                     explore={"system": "gscm", "name": "GSCM", "round": 3})
    assert "You are mapping GSCM (portal 'gscm')" in prompt and "This is round 3" in prompt
    assert "portal_map(system='gscm', todo=true)" in prompt and "{{param}}" in prompt


# The tools, without a browser ------------------------------------------------------------------------------------------
def tools(tmp_path: Path) -> tuple[Any, Any]:
    services = build_services()
    settings = settings_from({"WIZARD_PORTAL_GSCM_URL": "https://gscm.corp.example.com/"})
    assert settings is not None
    services.portals = PortalBrowsers(settings, lambda user_id: tmp_path / user_id)
    services.portal_maps = PortalMaps(tmp_path / "maps", names={"gscm": "GSCM"})
    identity = Identity(id="owner", email="owner@example.com", name="Owner", role="Owner",
                        entitlements={"gscm": SystemRights(reports=["*"], markets=["*"])})
    return build_registry(services), ToolContext(identity=identity, run_id="run_t", recorder=MemoryRecorder(), services=services)


def test_gemini_reads_the_map_first_and_adds_to_it(tmp_path: Path):
    registry, context = tools(tmp_path)
    saved = registry.execute("portal_map_save", {"system": "gscm", "overview": "A Nexacro client.", "reports": REPORTS,
                                                 "note": "menu"}, context)
    assert saved.ok and saved.data["counts"]["todo"] == 3
    mapped = registry.execute("portal_map_save", {"system": "gscm", "reports": [
        {"id": "as470", "status": "mapped", "summary": "Actual sales by market",
         "requests": [{"name": "search", "url": "/gscm/selectActual.do", "body": "SSV:utf-8\x1emarket:string={{market}}",
                       "params": ["market"], "verified": True}], "script": "actual-sales"}]}, context)
    assert mapped.ok and mapped.data["updated"] == ["as470"]
    found = registry.execute("portal_map", {"system": "gscm", "find": "actual sales by market"}, context)
    assert found.ok and found.data["reports"][0]["requests"][0]["url"] == "/gscm/selectActual.do"
    todo = registry.execute("portal_map", {"system": "gscm", "todo": True}, context)
    assert [r["id"] for r in todo.data["todo"]] == ["as480", "mt100"]
    guide = registry.execute("portal_guide", {"system": "gscm"}, context)
    assert guide.ok and guide.data["map"]["reports"][0]["id"] == "as470" and "portal_map(find=" in guide.data["map"]["how_to_use"]
    assert "Read the map first" in guide.data["guide"] and "W.nexacro.functions()" in guide.data["guide"]
    assert not registry.execute("portal_map", {"system": "gscm", "report": "nope"}, context).ok
    assert registry.execute("portal_map_save", {"system": "gscm"}, context).error_code == "invalid_arguments"
    bad = registry.execute("portal_map_save", {"system": "gscm", "reports": [{"id": "../x"}]}, context)
    assert bad.error_code == "invalid_arguments"


# Mapping rounds through the API, with a scripted Gemini --------------------------------------------------------------
class Mapper:
    """Each mapping round maps one more report; a question answers at once. `stall` makes rounds add nothing, `hold`
    keeps a round running until it is cancelled, `signed_out` reads a portal that asks for a sign-in."""
    kind = "code-assist"
    model = "gemini-3.8-flash"

    def __init__(self, stall: bool = False, hold: bool = False, signed_out: bool = False):
        self.stall, self.hold, self.signed_out = stall, hold, signed_out
        self.prompts: list[str] = []

    def label(self) -> str:
        return "Mapping test runtime"

    async def readiness(self, home: Path, email: str) -> dict[str, Any]:
        return {"ready": True, "reason": None}

    async def run(self, request: Any, emit: Any, tools: Any, cancelled: Any) -> None:
        if request.kind != "explore":
            await emit("text_delta", {"text": "Answered."})
            return
        self.prompts.append(request.prompt)
        if self.signed_out:
            await tools.call("portal_run", {"system": "gscm", "steps": [{"action": "goto", "url": "/"}]})
            await emit("text_delta", {"text": "GSCM asks for a sign-in."})
            return
        if self.hold:
            while not cancelled():
                await asyncio.sleep(0.02)
            raise AgentFailure("cancelled", "cancelled")
        if not self.stall:
            ok, text = await tools.call("portal_map", {"system": "gscm", "todo": True})
            todo = json.loads(text)["todo"] if ok else []
            if "This is round 1;" in request.prompt:
                await tools.call("portal_map_save", {"system": "gscm", "overview": "A Nexacro client.", "reports": REPORTS})
            elif todo:
                await tools.call("portal_map_save", {"system": "gscm", "reports": [{"id": todo[0]["id"], "status": "mapped"}]})
        await emit("text_delta", {"text": "Round done."})


def mapping_app(tmp_path: Path, runtime: Mapper) -> TestClient:
    settings = make_settings(tmp_path, WIZARD_PORTAL_GSCM_URL="https://gscm.corp.example.com/",
                             WIZARD_LOCAL_USER_EMAIL="owner@example.com")
    settings.install_mode = True
    return TestClient(create_app(settings, runtime=runtime))


def wait_mapping(client: TestClient, done: Any, timeout: float = 20) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get("/api/v1/portals/gscm/map").json()
        if done(view):
            return dict(view)
        time.sleep(0.05)
    raise AssertionError(f"mapping did not get there: {view}")


def test_mapping_runs_in_rounds_until_nothing_is_left_and_a_question_can_run_meanwhile(tmp_path: Path):
    runtime = Mapper()
    with mapping_app(tmp_path, runtime) as client:
        login(client, "local-owner")
        assert client.get("/api/v1/portals").json()["maps"]["gscm"]["source"] == "none"
        started = client.post("/api/v1/portals/gscm/map", headers=HEADERS)
        assert started.status_code == 200, started.text
        view = wait_mapping(client, lambda v: v["mapping"]["state"] != "running")
        assert view["mapping"]["state"] == "finished" and view["mapping"]["round"] == 4, view
        assert view["map"]["reports_mapped"] == 3 and view["map"]["reports_todo"] == 0 and view["map"]["source"] == "this_pc"
        assert "This is round 4;" in runtime.prompts[-1] and len(runtime.prompts) == 4
        runs = client.get(f"/api/v1/conversations/{view['mapping']['conversation_id']}").json()["runs"]
        assert [r["question"] for r in runs] == ["Map GSCM", "Map GSCM (round 2)", "Map GSCM (round 3)", "Map GSCM (round 4)"]
        assert all(r["status"] == "succeeded" for r in runs)
        assert client.get("/api/v1/portals").json()["mapping"]["state"] == "finished"


def test_mapping_stops_when_rounds_add_nothing(tmp_path: Path):
    with mapping_app(tmp_path, Mapper(stall=True)) as client:
        login(client, "local-owner")
        assert client.post("/api/v1/portals/gscm/map", headers=HEADERS).status_code == 200
        view = wait_mapping(client, lambda v: v["mapping"]["state"] != "running")
        assert view["mapping"]["state"] == "failed" and view["mapping"]["round"] == 2
        assert "added nothing" in view["mapping"]["message"]


def test_mapping_stops_at_once_when_the_portal_asks_for_a_sign_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from wizard_connectors.portal_browser import PortalBrowser, PortalError

    def signed_out(self: PortalBrowser, portal: Any, steps: Any, params: Any) -> Any:
        raise PortalError("sign_in_required", "GSCM asks for a sign-in in Wizard's browser.")
    monkeypatch.setattr(PortalBrowser, "execute", signed_out)
    with mapping_app(tmp_path, Mapper(signed_out=True)) as client:
        login(client, "local-owner")
        assert client.post("/api/v1/portals/gscm/map", headers=HEADERS).status_code == 200
        view = wait_mapping(client, lambda v: v["mapping"]["state"] != "running")
        assert view["mapping"]["state"] == "failed" and view["mapping"]["round"] == 1
        assert "asks for a sign-in" in view["mapping"]["message"] and "Continue mapping" in view["mapping"]["message"]


def test_the_person_stops_a_mapping_and_asks_questions_while_it_runs(tmp_path: Path):
    with mapping_app(tmp_path, Mapper(hold=True)) as client:
        login(client, "local-owner")
        assert client.post("/api/v1/portals/gscm/map", headers=HEADERS).status_code == 200
        assert client.post("/api/v1/portals/gscm/map", headers=HEADERS).status_code == 429, "one mapping at a time"
        assert ask(client, "How are sales?")["answer"] == "Answered.", "a question runs beside the mapping"
        assert client.delete("/api/v1/portals/gscm/map", headers=HEADERS).status_code == 409, "stop it first"
        stopped = client.post("/api/v1/portals/gscm/map/stop", headers=HEADERS).json()
        assert stopped["mapping"]["state"] == "stopped"
        view = wait_mapping(client, lambda v: v["mapping"]["run_id"] and client.get(
            f"/api/v1/runs/{v['mapping']['run_id']}").json()["status"] == "cancelled")
        assert view["mapping"]["round"] == 1
        assert client.post("/api/v1/portals/gscm/map/publish", headers=HEADERS).status_code == 409, "no write token here"


def test_a_round_that_saved_to_the_map_publishes_it(tmp_path: Path):
    published: list[str] = []
    with mapping_app(tmp_path, Mapper()) as client:
        maps = client.app.state.manager.services.portal_maps
        maps.writer = lambda files, message: (published.append(message), Published("published", "ok", "abc"))[1]
        login(client, "local-owner")
        client.post("/api/v1/portals/gscm/map", headers=HEADERS)
        wait_mapping(client, lambda v: v["mapping"]["state"] != "running")
        assert len(published) == 4 and maps.status("gscm")["published"]["commit"] == "abc"
        status = client.get("/api/v1/portals").json()["maps"]["gscm"]
        assert status["can_publish"] is True and status["published"]["outcome"] == "published"
