"""Default tool catalog: one read-only tool set per approved system plus the cross-source Wizard tools."""
from __future__ import annotations

from pathlib import Path

from ..catalog import Catalog
from ..fixture_source import FixtureSource
from ..knowledge import KnowledgeBase
from ..paths import KNOWLEDGE, SOURCE_CONTRACTS, SYNTHETIC
from ..pg import PgSettings
from ..postgres_query import PostgresQuery
from .core_tools import CORE_TOOLS
from .registry import Recorder, Services, ToolContext, ToolError, ToolOutcome, ToolRegistry, ToolSpec, flatten_schema
from .source_tools import make_source_tools

__all__ = ["Recorder", "Services", "ToolContext", "ToolError", "ToolOutcome", "ToolRegistry", "ToolSpec",
           "build_registry", "build_services", "flatten_schema"]


def build_services(contracts: Path = SOURCE_CONTRACTS, fixtures: Path = SYNTHETIC, knowledge: Path = KNOWLEDGE,
                   postgres: PgSettings | None = None) -> Services:
    catalog = Catalog.load(contracts)
    source = FixtureSource(catalog, fixtures)
    return Services(catalog=catalog, sources={s.id: source for s in catalog.systems}, knowledge=KnowledgeBase.load(knowledge),
                    postgres=PostgresQuery(postgres) if postgres else None)


def build_registry(services: Services) -> ToolRegistry:
    specs: list[ToolSpec] = []
    for system in services.catalog.systems:
        specs.extend(make_source_tools(system.id, system.name))
    specs.extend(CORE_TOOLS)
    return ToolRegistry(specs)
