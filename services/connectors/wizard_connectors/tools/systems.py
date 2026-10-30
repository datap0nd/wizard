"""The person's choice of systems for a request: which system each tool reads, and the choice the tools see.

Auto (no choice) is every system the person may use, as before. A choice switches the others off: their tools are not
offered to Gemini and the run refuses a call that names one (the portal tools name their portal in `system`). Wizard's
own work (calculating, charts, Check my data, proposing a recurring brief) belongs to no system and stays available; the
tools that span systems (the source list, the search across every catalog) list only the systems that are on."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

PORTAL_TOOLS = frozenset({"portal_run", "portal_guide", "portal_save_script", "portal_request_access", "portal_map",
                          "portal_map_save", "portal_map_route"})
KNOWLEDGE_TOOLS = frozenset({"wizard_lookup_definitions", "wizard_browse_knowledge", "wizard_read_knowledge"})
ATTACHMENT_TOOLS = frozenset({"wizard_read_attachment", "wizard_query_attachment", "wizard_edit_attachment"})
CATALOG_TOOL = re.compile(r"^([a-z0-9]+)_(search_reports|get_report_schema|run_report)$")
ASK_FOR_SYSTEM = "wizard_ask_for_system"


@dataclass(frozen=True)
class SystemChoice:
    """`on`: the systems this request may use. `names`: every system the person could choose, id -> name."""
    on: frozenset[str]
    names: dict[str, str]

    def allows(self, system: str) -> bool:
        return system in self.on

    def off(self) -> list[str]:
        return [s for s in self.names if s not in self.on]

    def name(self, system: str) -> str:
        return self.names.get(system, system.upper())


def system_of(name: str, args: dict[str, Any] | None = None) -> str | None:
    """The system a tool call reads; None for Wizard's own work and for the tools that span systems."""
    if name in PORTAL_TOOLS:
        system = (args or {}).get("system")
        return str(system) if system else None
    if name == "wizard_query_postgresql":
        return "postgresql"
    if name in KNOWLEDGE_TOOLS:
        return "knowledge"
    if name in ATTACHMENT_TOOLS:
        return "attachment"
    match = CATALOG_TOOL.match(name)
    return match.group(1) if match else None


def offered(name: str, choice: SystemChoice | None, catalogs: Iterable[str], portals: Iterable[str]) -> bool:
    """Whether Gemini is offered this tool under the choice (None, Auto: every tool but the one that asks for a system)."""
    if choice is None:
        return name != ASK_FOR_SYSTEM
    if name in PORTAL_TOOLS:
        return any(choice.allows(p) for p in portals)
    if name == "wizard_search_catalog":
        return any(choice.allows(c) for c in catalogs)
    if name == ASK_FOR_SYSTEM:
        return bool(choice.off())
    system = system_of(name)
    return system is None or choice.allows(system)
