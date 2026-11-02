"""The company's source order (Settings → Source order, `WIZARD_SOURCE_ORDER`): which data source Gemini starts with,
which sources share a level, what each is for, and which are used only when the person asks for them.

Owner, 2 Nov 2026: "dashboards first (html dashboards). Then AI team DB. Then ASAP/GSCM. Then BDP, etc. I would love to
be able to reorganize this in settings"; "Also NERP needs to be there". One company-wide order, carried by the
provisioning file and Export settings…, never per person.

It is guidance in the prompt with a sufficiency test (prompting.where_to_start_block), never code that forces a tool
sequence (decision 2026-11-02-source-order). The one thing it enforces is "only when asked": in Auto such a source's
tools are not offered, and Gemini asks for it with wizard_ask_for_system (systems.choice).

Stored as compact JSON on one line, a list from the first source down:
    [{"id":"dashboards","use":"Monthly KPIs by market"},{"id":"postgresql"},{"id":"asap"},{"id":"gscm","same":true},
     {"id":"nerp","when_asked":true},{"id":"bdp"}]
`same`: on the same level as the source above it. `use`: what it is for, plain text, at most 200 characters.
`when_asked`: used only when the person asks for it. A source the order does not name (a portal configured later) goes
at the end; a named source missing on this PC is ignored, and its entry is kept, so a PC without it never drops it."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

KEY = "WIZARD_SOURCE_ORDER"
MAX_USE = 200
MAX_ENTRIES = 40
MAX_CHARS = 12_000  # the stored line: 40 entries with a full "use it for" each fit
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
FIELDS = frozenset({"id", "same", "use", "when_asked"})
# What Wizard reads data from: the dashboards, the report catalogs, the portals and the database. The knowledge base,
# attached files and Metronome are not sources to order (systems.available kinds "knowledge", "files", "schedules").
KINDS = frozenset({"dashboards", "reports", "portal", "database"})
NOT_SOURCES = frozenset({"knowledge", "attachment", "metronome"})


class OrderError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    id: str
    same: bool = False        # on the same level as the source above it
    use: str = ""             # what it is for, in the company's words
    when_asked: bool = False  # used only when the person asks for it

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, **({"same": True} if self.same else {}), **({"use": self.use} if self.use else {}),
                **({"when_asked": True} if self.when_asked else {})}


# Owner, 2 Nov 2026: dashboards, then the database, then ASAP and GSCM, then NERP, then the Big Data Portal, then the rest.
DEFAULT: tuple[Entry, ...] = (Entry("dashboards"), Entry("postgresql"), Entry("asap"), Entry("gscm", same=True),
                              Entry("nerp"), Entry("bdp"))


def clean_use(text: str) -> str:
    """A "use it for" line as stored: one line of plain text, at most MAX_USE characters. Raises OrderError."""
    flat = " ".join(str(text).split())
    if len(flat) > MAX_USE:
        raise OrderError(f"a \"use it for\" line has at most {MAX_USE} characters ({len(flat)} given)")
    if any(ord(c) < 32 or c in "<>" for c in flat):
        raise OrderError("a \"use it for\" line is plain text: no < or > and no control characters")
    return flat


def parse(text: str | None) -> tuple[Entry, ...] | None:
    """The stored order, validated; None when it is not set (the default applies). Raises OrderError."""
    if text is None or not text.strip():
        return None
    if len(text) > MAX_CHARS:
        raise OrderError(f"it is longer than {MAX_CHARS:,} characters")
    try:
        raw = json.loads(text)
    except ValueError:
        raise OrderError("it is not valid JSON (a list such as [{\"id\":\"dashboards\"},{\"id\":\"postgresql\"}])") from None
    if not isinstance(raw, list):
        raise OrderError("it must be a list of sources, the first one first")
    if len(raw) > MAX_ENTRIES:
        raise OrderError(f"it names more than {MAX_ENTRIES} sources")
    entries: list[Entry] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise OrderError("each source is an object with an id, such as {\"id\":\"postgresql\"}")
        source = item["id"]
        if not ID.match(source):
            raise OrderError(f"{source!r} is not a source id (lower-case letters, digits, - and _)")
        if source in NOT_SOURCES:
            raise OrderError(f"{source} is not a data source to order (the knowledge base, attached files and Metronome "
                             "are always available)")
        if any(e.id == source for e in entries):
            raise OrderError(f"{source} is named twice")
        unknown = sorted(set(item) - FIELDS)
        if unknown:
            raise OrderError(f"{source}: {', '.join(unknown)} is not part of a source's entry (id, same, use, when_asked)")
        for flag in ("same", "when_asked"):
            if flag in item and not isinstance(item[flag], bool):
                raise OrderError(f"{source}: {flag} must be true or false")
        use = item.get("use", "")
        if not isinstance(use, str):
            raise OrderError(f"{source}: use must be text")
        try:
            use = clean_use(use)
        except OrderError as error:
            raise OrderError(f"{source}: {error}") from None
        entries.append(Entry(source, bool(item.get("same")) and bool(entries), use, bool(item.get("when_asked"))))
    return tuple(entries)


def render(entries: Iterable[Entry]) -> str:
    """The stored line: compact JSON, checked as it will be read."""
    text = json.dumps([e.as_dict() for e in entries], ensure_ascii=False, separators=(",", ":"))
    parse(text)
    return text


def effective(entries: tuple[Entry, ...] | None) -> tuple[Entry, ...]:
    return DEFAULT if entries is None else entries


def levels(entries: tuple[Entry, ...] | None, sources: Mapping[str, str],
           allowed: Iterable[str] | None = None) -> list[list[tuple[str, Entry]]]:
    """The levels in order, each a list of (source id, entry), for the sources given (id -> name, in the systems list's
    order) and, when `allowed` is set, only those. Levels are worked out on the whole stored order first, so a source
    whose level-mate is missing on this PC keeps a level of its own; then the missing ones are left out. A source the
    order does not name gets a level of its own at the end."""
    wanted = [s for s in sources if allowed is None or s in set(allowed)]
    grouped: list[list[Entry]] = []
    for entry in effective(entries):
        if entry.same and grouped:
            grouped[-1].append(entry)
        else:
            grouped.append([entry])
    named = {e.id for e in effective(entries)}
    grouped += [[Entry(s)] for s in wanted if s not in named]
    found = [[(e.id, e) for e in level if e.id in wanted] for level in grouped]
    return [level for level in found if level]


def held_back(entries: tuple[Entry, ...] | None, sources: Iterable[str]) -> frozenset[str]:
    """The sources (of those given) that are used only when the person asks for them."""
    here = set(sources)
    return frozenset(e.id for e in effective(entries) if e.when_asked and e.id in here)


def for_prompt(entries: tuple[Entry, ...] | None, sources: Mapping[str, str],
               allowed: Iterable[str] | None = None) -> list[list[tuple[str, str]]] | None:
    """The levels as the run prompt shows them, (name, use it for) per source, limited to the sources this run may
    use; None when it may use one source or none (there is nothing to order)."""
    found = levels(entries, sources, allowed)
    if sum(len(level) for level in found) < 2:
        return None
    return [[(sources[source], entry.use) for source, entry in level] for level in found]


def view(entries: tuple[Entry, ...] | None) -> list[dict[str, Any]]:
    return [e.as_dict() for e in effective(entries)]
