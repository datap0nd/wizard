"""The person's choice of systems for a request: which system each tool reads, and the choice the tools see.

Auto (no choice) is every system the person may use, as before. A choice switches the others off: their tools are not
offered to Gemini and the run refuses a call that names one (the portal tools name their portal in `system`). Wizard's
own work (calculating, charts, Check my data, proposing a recurring brief) belongs to no system and stays available; the
tools that span systems (the source list, the search across every catalog) list only the systems that are on.

Auto with sources the company uses only when asked (Settings → Source order; decision 2026-11-02-source-order) is a
choice marked `auto`: every system but those, so their tools are not offered either, and Gemini asks for one with
wizard_ask_for_system as it would for a system the person switched off. It is stored and shown as Auto."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

PORTAL_TOOLS = frozenset({"portal_run", "portal_guide", "portal_save_script", "portal_request_access", "portal_map",
                          "portal_map_save", "portal_map_route"})
KNOWLEDGE_TOOLS = frozenset({"wizard_lookup_definitions", "wizard_browse_knowledge", "wizard_read_knowledge"})
ATTACHMENT_TOOLS = frozenset({"wizard_read_attachment", "wizard_query_attachment", "wizard_edit_attachment"})
DASHBOARD_TOOLS = frozenset({"wizard_dashboards", "wizard_read_dashboard"})  # the Dashboards system (dashboards.py)
NERP_TOOLS = frozenset({"nerp_list_views", "nerp_view_columns", "nerp_query"})  # NERP's views, read live (nerp.py)
CATALOG_TOOL = re.compile(r"^([a-z0-9]+)_(search_reports|get_report_schema|run_report)$")
ASK_FOR_SYSTEM = "wizard_ask_for_system"


@dataclass(frozen=True)
class SystemChoice:
    """`on`: the systems this request may use. `names`: every system the person could choose, id -> name. `auto`: the
    person chose Auto, and the systems that are off are the ones the company uses only when asked."""
    on: frozenset[str]
    names: dict[str, str]
    auto: bool = False

    def allows(self, system: str) -> bool:
        return system in self.on

    def off(self) -> list[str]:
        return [s for s in self.names if s not in self.on]

    def name(self, system: str) -> str:
        return self.names.get(system, system.upper())

    def chosen(self) -> list[str] | None:
        """The ids the person chose, in the systems list's order; None for Auto."""
        return None if self.auto else [s for s in self.names if s in self.on]

    def why_off(self, system: str) -> str:
        """Why a system's tools refuse in this request, in words for Gemini."""
        if self.auto:
            return f"{self.name(system)} is used only when the person asks for it (the company's source order)"
        return f"{self.name(system)} is switched off for this request"


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
    if name in DASHBOARD_TOOLS:
        return "dashboards"
    if name in NERP_TOOLS:
        return "nerp"
    match = CATALOG_TOOL.match(name)
    return match.group(1) if match else None


def offered(name: str, choice: SystemChoice | None, catalogs: Iterable[str], portals: Iterable[str]) -> bool:
    """Whether Gemini is offered this tool under the choice (None, Auto: every tool but the one that asks for a system;
    Auto with sources used only when asked: as a choice of every other system)."""
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
