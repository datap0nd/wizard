"""Default tool catalog: one read-only tool set per approved system, the cross-source Wizard tools, and the portal
tools when company portals are configured."""
from __future__ import annotations

from pathlib import Path

from ..catalog import Catalog
from ..fixture_source import FixtureSource
from ..knowledge import KnowledgeBase
from ..paths import KNOWLEDGE, SOURCE_CONTRACTS, SYNTHETIC
from ..pg import PgSettings
from ..postgres_query import PostgresQuery
from .core_tools import CORE_TOOLS
from .kb_tools import KB_TOOLS
from .portal_tools import PORTAL_TOOLS
from .registry import Recorder, Services, ToolContext, ToolError, ToolOutcome, ToolRegistry, ToolSpec, flatten_schema
from .source_tools import make_source_tools
from .task_tools import TASK_FILE_TOOLS

__all__ = ["Recorder", "Services", "ToolContext", "ToolError", "ToolOutcome", "ToolRegistry", "ToolSpec",
           "build_registry", "build_services", "flatten_schema", "retire_portal_catalogs"]


def build_services(contracts: Path = SOURCE_CONTRACTS, fixtures: Path = SYNTHETIC, knowledge: Path = KNOWLEDGE,
                   postgres: PgSettings | None = None, postgres_name: str = "AI Team Database",
                   real_content: bool = False, skip: frozenset[str] = frozenset()) -> Services:
    """real_content: the catalogs come from a knowledge base or content folder, so they load as navigation only. skip:
    files of that content (paths such as contracts/sources/asap.json or knowledge/x/y.md) left out for their errors."""
    catalog = Catalog.load(contracts, real=real_content, skip=frozenset(Path(p).name for p in skip if p.startswith("contracts/")))
    source = FixtureSource(catalog, fixtures)
    return Services(catalog=catalog, sources={s.id: source for s in catalog.systems}, knowledge=KnowledgeBase.load(knowledge, skip=frozenset(p for p in skip if p.startswith("knowledge/"))),
                    postgres=PostgresQuery(postgres) if postgres else None, postgres_name=postgres_name)


def retire_portal_catalogs(services: Services) -> frozenset[str]:
    """Owner decision (2 November 2026, docs/decisions/2026-11-02-retire-portal-catalogs.md): a company portal's report
    catalog is retired once Wizard has a map of that portal with mapped (or partly mapped) reports, this PC's map or
    the one published to the knowledge base. The map is then the one place Wizard finds that portal's reports: the
    catalog leaves `services.catalog`, so it has no <system>_* tools, no results in wizard_search_catalog and no entry
    in the Sources tab, and wizard_list_sources says the portal is read through its map.

    Called once at start-up, before the registry is built (the tools and their MCP servers are fixed then too): a map
    that gains its first mapped report while Wizard runs retires the catalog at the next start. Catalogs of systems
    that are not portals on this PC, or portals with no mapped report yet, stay. The repository's synthetic catalogs
    (SYNTHETIC_FIXTURE) are never retired, so the demo, goldens and evals do not change."""
    portals, maps = services.portals, services.portal_maps
    if portals is None or maps is None:
        return frozenset()
    retired = frozenset(s.id for s in services.catalog.systems if s.connector.status != "SYNTHETIC_FIXTURE"
                        and portals.settings.portal(s.id) is not None and maps.mapped(s.id))
    if retired:
        services.catalog = services.catalog.without(retired)
        services.retired_catalogs = services.retired_catalogs | retired
    return retired


def build_registry(services: Services) -> ToolRegistry:
    specs: list[ToolSpec] = []
    for system in services.catalog.systems:
        specs.extend(make_source_tools(system.id, system.name))
    specs.extend(CORE_TOOLS)
    specs.extend(KB_TOOLS)
    specs.extend(TASK_FILE_TOOLS)
    if services.portals is not None:
        specs.extend(PORTAL_TOOLS)
    return ToolRegistry(specs)
