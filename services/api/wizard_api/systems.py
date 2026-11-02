"""The systems a person's Wizard can draw on: shown on the systems stage, and offered in the composer's systems picker."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from wizard_connectors.entitlements import Identity
from wizard_connectors.tools import Services
from wizard_connectors.tools.systems import SystemChoice

from . import source_order
from .config import Settings


def can_schedule(settings: Settings, services: Services, identity: Identity) -> bool:
    """Recurring extractions: Metronome is connected and the person may query the whole database."""
    return bool(settings.metronome and services.postgres and identity.can_use_system("postgresql")
                and identity.allowed_markets("postgresql") is None)


def available(settings: Settings, services: Services, identity: Identity) -> list[dict[str, Any]]:
    """The team's dashboards, report platforms, portals, the database, the knowledge base, attached files and Metronome:
    only what this person may use. The dashboards come first (owner, 2 Nov 2026: "the first thing in the priority list");
    a dashboards folder this PC cannot reach is listed all the same, as a database that does not answer is, and its tools
    say so."""
    found: list[dict[str, Any]] = []
    if services.dashboards and identity.can_use_system("dashboards"):
        found.append({"id": "dashboards", "name": services.dashboards.name, "kind": "dashboards", "data_mode": "LIVE"})
    found += [{"id": s.id, "name": s.name, "kind": "reports", "data_mode": s.connector.data_mode}
              for s in services.catalog.systems if identity.can_use_system(s.id)]
    for portal in settings.portals.portals if settings.portals else ():
        if not identity.can_use_system(portal.id):
            continue
        # A portal read live in the person's browser; it takes over a navigation-only catalog of the same system.
        found = [s for s in found if s["id"] != portal.id]
        found.append({"id": portal.id, "name": portal.name, "kind": "portal", "data_mode": "LIVE"})
    if services.postgres and identity.can_use_system("postgresql"):
        found.append({"id": "postgresql", "name": services.postgres_name, "kind": "database", "data_mode": "LIVE"})
    if services.knowledge.notes:
        found.append({"id": "knowledge", "name": "Knowledge base", "kind": "knowledge", "notes": len(services.knowledge.notes)})
    found.append({"id": "attachment", "name": "Attached files", "kind": "files"})
    if can_schedule(settings, services, identity):
        found.append({"id": "metronome", "name": "Metronome", "kind": "schedules"})
    # Sources the company uses only when asked (Settings → Source order): Auto leaves them out, the picker says so.
    held = source_order.held_back(settings.source_order, [s["id"] for s in found if s["kind"] in source_order.KINDS])
    return [{**s, "only_when_asked": True} if s["id"] in held else s for s in found]


def sources(settings: Settings, services: Services, identity: Identity) -> dict[str, str]:
    """The data sources the source order arranges, id -> name: the dashboards, report catalogs, portals and the database
    (not the knowledge base, attached files or Metronome)."""
    return {s["id"]: s["name"] for s in available(settings, services, identity) if s["kind"] in source_order.KINDS}


def choosable(settings: Settings, services: Services, identity: Identity) -> dict[str, str]:
    """The systems the picker offers, id -> name. Metronome is left out: it sends recurring emails, it is not a source."""
    return {s["id"]: s["name"] for s in available(settings, services, identity) if s["kind"] != "schedules"}


class UnknownSystem(ValueError):
    pass


def choice(settings: Settings, services: Services, identity: Identity, systems: Iterable[str] | None) -> SystemChoice | None:
    """The person's choice for a request; None is Auto. Auto with sources the company uses only when asked is every
    other system, marked `auto` (stored and shown as Auto). Raises UnknownSystem for a system they cannot choose."""
    listed = available(settings, services, identity)
    names = {s["id"]: s["name"] for s in listed if s["kind"] != "schedules"}
    if systems is None:
        held = frozenset(s["id"] for s in listed if s.get("only_when_asked"))
        return SystemChoice(frozenset(names) - held, names, auto=True) if held else None
    wanted = list(dict.fromkeys(systems))
    unknown = [s for s in wanted if s not in names]
    if unknown:
        raise UnknownSystem(f"Not a system you can use here: {', '.join(unknown)}.")
    if not wanted:
        raise UnknownSystem("Choose at least one system, or Auto.")
    return SystemChoice(frozenset(wanted), names)
