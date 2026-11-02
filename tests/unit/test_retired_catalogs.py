"""Portal report catalogs retired by the portal maps (owner, 2 Nov 2026, docs/decisions/2026-11-02-retire-portal-catalogs.md).

Once a portal's map has mapped reports, the map is the one place Wizard finds that portal's reports: no <system>_*
catalog tools, no catalog results in wizard_search_catalog, and wizard_list_sources points at portal_map. A portal with
no mapped report yet, a system that is not a portal, and the synthetic demo keep their catalogs. Every report, portal
and map here is invented."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from tests.helpers import MemoryRecorder, login, make_settings
from tests.unit.test_content import catalog, content

from wizard_api.app import create_app
from wizard_connectors.content import errors, validate_content
from wizard_connectors.entitlements import Identity, IdentityDirectory, SystemRights
from wizard_connectors.portal_browser import PortalBrowsers
from wizard_connectors.portal_map import PortalMaps
from wizard_connectors.portals import settings_from
from wizard_connectors.tools import Services, ToolContext, build_registry, build_services, retire_portal_catalogs
from wizard_connectors.tools.systems import SystemChoice

PORTALS = {"WIZARD_PORTAL_GSCM_URL": "https://gscm.corp.example.com/", "WIZARD_PORTAL_ASAP_URL": "https://asap.corp.example.com/"}
MAPPED = {"id": "so200", "name": "Weekly channel sell-out", "path": ["Sales", "Weekly channel sell-out"], "menu_id": "SO200",
          "status": "mapped", "use_for": ["sell-out units by market and week"]}
TODO = {"id": "st300", "name": "Channel stock", "path": ["Stock", "Channel stock"], "menu_id": "ST300"}


def with_portals(services: Services, tmp_path: Path, published: Path | None = None) -> Services:
    settings = settings_from(PORTALS)
    assert settings is not None
    services.portals = PortalBrowsers(settings, lambda user_id: tmp_path / user_id)
    services.portal_maps = PortalMaps(tmp_path / "maps", published, names={"gscm": "GSCM", "asap": "ASAP"})
    return services


def context(services: Services) -> ToolContext:
    identity = Identity(id="owner", email="owner@example.com", name="Owner", role="Owner",
                        entitlements={s: SystemRights(reports=["*"], markets=["*"]) for s in ("gscm", "asap", "nerp")})
    return ToolContext(identity=identity, run_id="run_t", recorder=MemoryRecorder(), services=services)


def catalog_tools(names: list[str], system: str) -> list[str]:
    return [n for n in names if n.startswith(f"{system}_")]


def test_a_portal_with_a_mapped_report_is_read_through_its_map_and_its_catalog_is_retired(tmp_path: Path):
    # Real content (catalogs load as navigation only) on a PC with GSCM and ASAP set up as portals. GSCM's map has a
    # mapped report; ASAP's map has only reports still to map; NERP is not a portal.
    services = with_portals(build_services(real_content=True), tmp_path)
    assert services.portal_maps is not None
    services.portal_maps.save("gscm", reports=[MAPPED, TODO])
    services.portal_maps.save("asap", reports=[{**TODO, "id": "ab100", "name": "Share tracker"}])
    query = {"query": "units market quarter", "limit": 25}
    before = build_registry(services).execute("wizard_search_catalog", query, context(services)).data["results"]
    assert {r["system"] for r in before} == {"asap", "gscm", "nerp"}
    assert retire_portal_catalogs(services) == {"gscm"} and services.retired_catalogs == {"gscm"}
    registry = build_registry(services)
    names = list(registry.specs)
    assert catalog_tools(names, "gscm") == [] and "gscm" not in registry.scopes(), "no GSCM catalog tools, no MCP server"
    assert catalog_tools(names, "asap") and catalog_tools(names, "nerp"), "a portal not mapped yet and NERP keep theirs"
    assert "portal_map" in names and "gscm" not in services.catalog.contracts

    ctx = context(services)
    found = registry.execute("wizard_search_catalog", query, ctx)
    assert found.ok and {r["system"] for r in found.data["results"]} == {"asap", "nerp"}
    assert "GSCM" in found.data["portal_maps"] and "portal_map(system='gscm', find=...)" in found.data["portal_maps"]
    assert "ASAP" not in found.data["portal_maps"]
    assert registry.execute("gscm_search_reports", {"query": "sell-out"}, ctx).error_code == "unknown_tool"

    listed = registry.execute("wizard_list_sources", {}, ctx).data["sources"]
    catalogs = {s["system"] for s in listed if s["connector_status"] != "BROWSER_SESSION"}
    portals = {s["system"]: s for s in listed if s["connector_status"] == "BROWSER_SESSION"}
    assert catalogs == {"asap", "nerp"}, "GSCM is listed once: as the portal"
    gscm = portals["gscm"]
    assert gscm["reports_mapped"] == 1 and gscm["how_to_navigate"].startswith("portal_map(system='gscm', find=...)")
    assert "Read through its map" in gscm["reports"] and "catalog for GSCM is retired" in gscm["reports"]
    assert "reports_mapped" not in portals["asap"] and portals["asap"]["how_to_navigate"].startswith("portal_guide(")
    asap_catalog = registry.execute("asap_search_reports", {"query": "share"}, ctx)
    assert asap_catalog.ok and "not ASAP itself" in asap_catalog.data["live_portal"], "unchanged for a portal not mapped yet"


def test_the_published_map_counts_and_the_choice_of_systems_is_respected(tmp_path: Path):
    published = tmp_path / "kb" / "portal-maps"
    published.mkdir(parents=True)
    (published / "gscm.json").write_text(json.dumps({"format": 1, "system": "gscm", "name": "GSCM",
                                                     "reports": [{**MAPPED, "status": "partial"}]}), encoding="utf-8")
    (published / "asap.json").write_text(json.dumps({"system": "asap", "reports": "not a list"}), encoding="utf-8")
    services = with_portals(build_services(real_content=True), tmp_path, published)
    assert retire_portal_catalogs(services) == {"gscm"}, "the published map counts; a malformed one counts as none"
    registry = build_registry(services)
    ctx = context(services)
    ctx.choice = SystemChoice(frozenset({"nerp"}), {"gscm": "GSCM", "asap": "ASAP", "nerp": "NERP"})
    found = registry.execute("wizard_search_catalog", {"query": "sell-out"}, ctx)
    assert found.ok and "portal_maps" not in found.data, "GSCM is switched off for this request: not mentioned"


def test_synthetic_mode_and_a_pc_without_portals_keep_every_catalog(tmp_path: Path):
    reference = [t["name"] for t in build_registry(build_services()).describe()]
    plain = build_services(real_content=True)
    assert retire_portal_catalogs(plain) == frozenset(), "no portals on this PC: nothing is retired"
    # The synthetic demo with the same mapped portal: its catalogs are fixtures with readable rows, never retired.
    services = with_portals(build_services(), tmp_path)
    assert services.portal_maps is not None
    services.portal_maps.save("gscm", reports=[MAPPED])
    assert retire_portal_catalogs(services) == frozenset() and services.retired_catalogs == frozenset()
    registry = build_registry(services)
    assert [n for n in registry.specs if not n.startswith("portal_")] == reference
    ctx = context(services)
    found = registry.execute("wizard_search_catalog", {"query": "sell-out channel stock"}, ctx)
    assert any(r["system"] == "gscm" for r in found.data["results"]) and "portal_maps" not in found.data
    run = registry.execute("gscm_run_report", {"report_id": "gscm-sell-in-sell-out-monthly", "limit": 5}, ctx)
    assert run.ok and run.data["source"]["data_mode"] == "SYNTHETIC"


def uncertain(**overrides: Any) -> dict[str, Any]:
    return catalog(caveats=["UNCERTAIN: is this sell-out or sell-in? Owner to confirm."], **overrides)


def write_map(root: Path, system: str, status: str) -> None:
    (root / "portal-maps").mkdir(parents=True, exist_ok=True)
    (root / "portal-maps" / f"{system}.json").write_text(json.dumps({
        "format": 1, "system": system, "reports": [{**MAPPED, "status": status}]}), encoding="utf-8")


def test_the_validator_says_once_that_a_mapped_portals_catalog_is_retired(tmp_path: Path):
    retired = content(tmp_path / "a", uncertain())
    write_map(retired, "asap", "mapped")
    problems = [p for p in validate_content(retired) if p.level == "warning"]
    assert [p.where for p in problems if "retired" in p.message] == ["contracts/sources/asap.json"]
    assert not any(p.message == "has UNCERTAIN choices waiting for owner review" for p in problems), "no nagging"
    assert errors(validate_content(retired)) == []
    # Still a review to ask for: a portal whose map has nothing mapped yet, and a system that is not a portal.
    waiting = content(tmp_path / "b", uncertain())
    write_map(waiting, "asap", "todo")
    assert any(p.message == "has UNCERTAIN choices waiting for owner review" for p in validate_content(waiting))
    other = uncertain(id="nerp-spend")
    other["system"]["id"] = "nerp"
    plain = content(tmp_path / "c", other, name="nerp")
    write_map(plain, "nerp", "mapped")
    found = validate_content(plain)
    assert any(p.message == "has UNCERTAIN choices waiting for owner review" for p in found)
    assert not any("retired" in p.message for p in found)


def test_wizard_starts_without_the_catalog_of_a_mapped_portal(tmp_path: Path):
    root = content(tmp_path / "wizard-content", uncertain())
    write_map(root, "asap", "mapped")  # the map published to the knowledge base
    app = create_app(make_settings(tmp_path, WIZARD_CONTENT_DIR=str(root), WIZARD_AGENT_RUNTIME="code-assist",
                                   WIZARD_PORTAL_ASAP_URL="https://asap.corp.example.com/"))
    with TestClient(app) as client:
        login(client, "u-ceo")
        assert client.get("/api/v1/sources").json()["sources"] == [], "the Sources tab has no retired catalog either"
        systems = {s["id"]: s for s in client.get("/api/v1/bootstrap").json()["systems"]}
        assert systems["asap"]["kind"] == "portal"
    services, registry = app.state.manager.services, app.state.registry
    assert services.retired_catalogs == {"asap"} and catalog_tools(list(registry.specs), "asap") == []
    identity = IdentityDirectory.load(app.state.settings.identities_file).get("u-ceo")
    assert identity is not None
    ctx = ToolContext(identity=identity, run_id="r", recorder=MemoryRecorder(), services=services)
    listed = registry.execute("wizard_list_sources", {}, ctx).data["sources"]
    assert [(s["system"], s["connector_status"], s["reports_mapped"]) for s in listed] == [("asap", "BROWSER_SESSION", 1)]
    app.state.store.db.close()
