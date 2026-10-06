"""Default tool catalog: one read-only tool set per approved system plus the cross-source Wizard tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..catalog import Catalog
from ..fixture_source import FixtureSource
from ..knowledge import KnowledgeBase
from ..paths import KNOWLEDGE, SOURCE_CONTRACTS, SYNTHETIC
from .core_tools import CORE_TOOLS
from .registry import Recorder, Services, ToolContext, ToolError, ToolOutcome, ToolRegistry, ToolSpec, flatten_schema
from .source_tools import make_source_tools

__all__ = ["Recorder", "Services", "ToolContext", "ToolError", "ToolOutcome", "ToolRegistry", "ToolSpec",
           "build_registry", "build_services", "flatten_schema"]


def build_services(contracts: Path = SOURCE_CONTRACTS, fixtures: Path = SYNTHETIC, knowledge: Path = KNOWLEDGE,
                   live: dict[str, Any] | None = None) -> Services:
    """`live` maps a system id to its live source (e.g. postgresql -> PostgresSource); others read fixtures."""
    catalog = Catalog.load(contracts)
    source = FixtureSource(catalog, fixtures)
    live = live or {}
    return Services(catalog=catalog, sources={s.id: live.get(s.id, source) for s in catalog.systems},
                    knowledge=KnowledgeBase.load(knowledge))


def build_registry(services: Services) -> ToolRegistry:
    specs: list[ToolSpec] = []
    for system in services.catalog.systems:
        specs.extend(make_source_tools(system.id, system.name))
    specs.extend(CORE_TOOLS)
    return ToolRegistry(specs)
