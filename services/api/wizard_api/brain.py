"""The Brain page (/brain): the knowledge base as a 3D graph, made to show Wizard to people.

Everything on it is read, never written for the occasion: the knowledge base's areas, notes and the links between them
(each note's own `related` links, the notes it names in its text, the notes it shares most tags with), its glossary
terms, the systems this person may use and the reports catalogued in each, and, from the company PostgreSQL server, how
many tables and views the read-only account can read and the news table an automation keeps filling. The database is
read with Wizard's own fixed catalog and news queries, under the protections of every database read (postgres_query.py:
one statement as a subquery, a READ ONLY transaction that is always rolled back, a fresh connection closed after each
call, the read-only account). None of this is a Gemini tool, and the page never says Wizard is reading something.

The news table is found by name: WIZARD_NEWS_TABLE (schema.name, optionally in WIZARD_NEWS_DATABASE), else the readable
table or view called news, else the one whose name contains "news" with the most news-like columns, in the default
database first and then the others on the server. Its columns are matched by name (title, category, published date,
source, link, summary, market); a column that is not there is simply not shown."""
from __future__ import annotations

import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from wizard_connectors.fixture_source import SourceError
from wizard_connectors.knowledge import KnowledgeBase, Note
from wizard_connectors.pg import literal, quote
from wizard_connectors.postgres_query import DATABASES, RELATIONS, PostgresQuery, sql_name

AREA_NAMES = {"company": "Company", "org": "Organisation", "products": "Products", "markets": "Markets",
              "processes": "Processes", "platforms": "Platforms", "datasets": "Data dictionary", "metrics": "Metrics",
              "glossary": "Glossary", "faq": "Executive questions", "decisions": "Decisions", "general": "Foundations"}
MAX_LINKS = 9000
SHARED_PER_NOTE = 3      # topic links kept per note: its notes with the most tags in common
COMMON_TAG = 60          # a tag on more notes than this says little about how two notes relate
MENTION_CHARS = 4        # a shorter name (BI, PG) names too many things to count as a mention
MENTION_WORDS = 8        # longer titles are matched by their id and aliases only
MENTIONS_PER_NOTE = 12   # mention links kept per note: the notes it names most often
COMMON_NAME = 0.25       # a name found in more than this share of notes (8 or more) is an ordinary word there
MAX_TERMS = 3000         # glossary entries drawn as points of their own
MAX_TAGS = 15            # the knowledge standard's most tags per note
WORD = re.compile(r"[a-z0-9]+")
TABLE_NAME = re.compile(r"^(?:([A-Za-z_][A-Za-z0-9_$]{0,62})\.)?([A-Za-z_][A-Za-z0-9_$]{0,62})$")
DATABASE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]{0,62}$")
LIVE_SECONDS = 45.0      # the page polls; the server is read at most this often
SEARCH_SECONDS = 10.0
MAX_OTHER_DATABASES = 12
LATEST = 40

# Column names that hold each part of a news item, most likely first. A date must be a date or timestamp column.
ROLES: dict[str, tuple[str, ...]] = {
    "title": ("title", "headline", "news_title", "article_title", "subject", "heading", "name"),
    "category": ("category", "categories", "news_category", "category_name", "topic", "topics", "theme", "themes",
                 "classification", "label", "labels", "tag", "tags", "section", "segment"),
    "date": ("published_at", "published", "publish_date", "published_date", "published_on", "pub_date",
             "publication_date", "news_date", "article_date", "date", "datetime", "timestamp", "time"),
    "added": ("created_at", "inserted_at", "collected_at", "scraped_at", "fetched_at", "ingested_at", "loaded_at",
              "added_at", "crawled_at", "created", "inserted", "updated_at"),
    "source": ("source", "source_name", "publisher", "outlet", "media", "site", "website", "domain", "provider", "feed"),
    "url": ("url", "link", "article_url", "news_url", "source_url", "href"),
    "summary": ("summary", "ai_summary", "description", "abstract", "snippet", "excerpt", "brief", "content", "body", "text"),
    "market": ("market", "markets", "country", "countries", "region", "geo", "location"),
}
ROLE_WEIGHT = {"title": 4, "category": 3, "date": 2, "added": 1, "source": 1, "url": 1, "summary": 1, "market": 1}
NEWS_COLUMNS = ("SELECT n.nspname AS schema, c.relname AS name, a.attname AS column, "
                "pg_catalog.format_type(a.atttypid, a.atttypmod) AS type "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid "
                "WHERE c.relkind IN ('r', 'v', 'm', 'p', 'f') AND a.attnum > 0 AND NOT a.attisdropped "
                "AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\\_%' "
                "AND pg_catalog.has_schema_privilege(n.oid, 'USAGE') AND pg_catalog.has_table_privilege(c.oid, 'SELECT')")


def area_name(area: str) -> str:
    return AREA_NAMES.get(area) or area.replace("-", " ").replace("_", " ").strip().capitalize() or "Other"


def stage(note: Note) -> str:
    """How far a note has come: SIGNED by its owner, EXPERT_CHECKED (an expert answered a quiz on it) or DRAFT."""
    return "SIGNED" if note.status == "SIGNED" else "EXPERT_CHECKED" if note.reviewed else "DRAFT"


def mentions(notes: list[Note]) -> dict[tuple[str, str], int]:
    """Notes whose text names another note: by its id, its title or one of its aliases, as whole words. A name two notes
    share, a name shorter than MENTION_CHARS and a name found in more than COMMON_NAME of the notes are left out. For
    each note, the MENTIONS_PER_NOTE notes it names most often; the count is how often."""
    owner: dict[tuple[str, ...], str | None] = {}
    for note in notes:
        for name in {note.id, note.title, *note.aliases}:
            words = tuple(WORD.findall(name.casefold()))
            if not words or len(words) > MENTION_WORDS or len("".join(words)) < MENTION_CHARS:
                continue
            owner[words] = note.id if owner.get(words, note.id) == note.id else None  # shared by two notes: ambiguous
    longest = max((len(words) for words in owner), default=0)
    found: dict[str, Counter[str]] = {}
    seen_in: Counter[tuple[str, ...]] = Counter()
    for note in notes:
        text = WORD.findall(note.body.casefold())
        named: Counter[str] = Counter()
        names: set[tuple[str, ...]] = set()
        for i in range(len(text)):
            for size in range(min(longest, len(text) - i), 0, -1):
                target = owner.get(tuple(text[i:i + size]))
                if target and target != note.id:
                    named[target] += 1
                    names.add(tuple(text[i:i + size]))
                    break
        seen_in.update(names)
        found[note.id] = named
    common = {owner[name] for name, count in seen_in.items() if len(notes) >= 8 and count > COMMON_NAME * len(notes)}
    pairs: dict[tuple[str, str], int] = {}
    for source, named in found.items():
        kept = [(target, count) for target, count in named.items() if target not in common]
        for target, count in sorted(kept, key=lambda item: (-item[1], item[0]))[:MENTIONS_PER_NOTE]:
            pair = (min(source, target), max(source, target))
            pairs[pair] = pairs.get(pair, 0) + count
    return pairs


def links(notes: list[Note]) -> list[dict[str, Any]]:
    """The notes' own `related` links; then the notes each one names in its text (mentions); then, for each note, the few
    notes it shares most tags with (at least two). A pair is listed once, under the first of these that joins it."""
    ids = {note.id for note in notes}
    found: dict[tuple[str, str], tuple[str, int]] = {}
    for note in notes:
        for other in note.related:
            if other in ids and other != note.id:
                found.setdefault((min(note.id, other), max(note.id, other)), ("related", 1))
    for pair, count in mentions(notes).items():
        found.setdefault(pair, ("mention", count))
    by_tag: dict[str, list[str]] = {}
    for note in notes:
        for tag in {t.casefold() for t in note.tags}:
            by_tag.setdefault(tag, []).append(note.id)
    shared: Counter[tuple[str, str]] = Counter()
    for members in by_tag.values():
        if 1 < len(members) <= COMMON_TAG:
            shared.update(combinations(sorted(members), 2))
    best: dict[str, list[tuple[int, tuple[str, str]]]] = {}
    for pair, count in shared.items():
        if count >= 2:
            for end in pair:
                best.setdefault(end, []).append((count, pair))
    for note_id in sorted(best):
        for count, pair in sorted(best[note_id], key=lambda item: (-item[0], item[1]))[:SHARED_PER_NOTE]:
            found.setdefault(pair, ("shared", count))
    rank = {"related": 0, "mention": 1, "shared": 2}
    ordered = sorted(found.items(), key=lambda item: (rank[item[1][0]], item[0]))[:MAX_LINKS]
    return [{"source": a, "target": b, "kind": kind, "weight": weight} for (a, b), (kind, weight) in ordered]


def documents(system: dict[str, Any], note: Note) -> bool:
    """A note that documents a system: a dataset note documents the database; a platform note, or any note tagged with
    the system's id, documents that platform."""
    sid = str(system["id"]).casefold()
    if sid in ("knowledge", "attachment"):
        return False
    tags = {t.casefold() for t in note.tags}
    if sid == "postgresql":
        return note.type == "dataset" or note.area == "datasets" or "postgresql" in tags
    words = set(re.split(r"[^a-z0-9]+", f"{note.id} {note.title}".casefold()))
    named = sid in words or str(system.get("name", "")).casefold() in note.title.casefold()
    return sid in tags or ((note.type == "platform" or note.area == "platforms") and named)


def knowledge_map(kb: KnowledgeBase, systems: list[dict[str, Any]], reports: dict[str, int], content: str) -> dict[str, Any]:
    """Areas, notes, links and systems for the map, with the counts the page shows."""
    notes = kb.notes
    terms = {note.id: sum(1 for s in kb.sections.get(note.id, ()) if s.entry) for note in notes}
    per_area = Counter(note.area for note in notes)
    areas = [{"id": area, "name": area_name(area), "description": kb.areas.get(area, ""), "notes": count,
              "order": list(AREA_NAMES).index(area) if area in AREA_NAMES else len(AREA_NAMES)}
             for area, count in per_area.items()]
    areas.sort(key=lambda a: (a.pop("order"), a["name"]))
    out_systems = []
    for system in systems:
        documented = [note.id for note in notes if documents(system, note)]
        out_systems.append({**system, "reports": reports.get(str(system["id"])), "documented_by": documented[:300]})
    found = links(notes)
    stages = Counter(stage(note) for note in notes)
    ordered = sorted(notes, key=lambda n: (n.area, n.title.casefold()))
    entries = [{"note": n.id, "term": section.heading[:80]} for n in ordered for section in kb.sections.get(n.id, ())
               if section.entry][:MAX_TERMS]
    return {
        "content": content,
        "areas": areas,
        "notes": [{"id": n.id, "title": n.title, "area": n.area, "type": n.type or None, "stage": stage(n),
                   "summary": n.summary[:220], "tags": list(n.tags[:MAX_TAGS]), "terms": terms[n.id] or None,
                   "words": len(WORD.findall(n.body.casefold())), "updated": n.updated or None} for n in ordered],
        "links": found,
        "terms": entries,
        "systems": out_systems,
        "counts": {"notes": len(notes), "areas": len(areas), "links": len(found),
                   "related": sum(1 for link in found if link["kind"] == "related"),
                   "mentions": sum(1 for link in found if link["kind"] == "mention"),
                   "glossary_terms": sum(terms.values()),
                   "datasets": sum(1 for n in notes if n.type == "dataset" or n.area == "datasets"),
                   "metrics": sum(1 for n in notes if n.type == "metric" or n.area == "metrics"),
                   "signed": stages["SIGNED"], "expert_checked": stages["EXPERT_CHECKED"],
                   "reports": sum(v for v in reports.values() if v), "systems": len(systems)},
    }


# Live: the company database --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NewsTable:
    database: str
    schema: str
    name: str
    columns: dict[str, str]   # role -> column name
    arrays: frozenset[str]    # roles whose column is an array

    @property
    def sql(self) -> str:
        return sql_name(self.schema, self.name)


def _is_date(kind: str) -> bool:
    return kind.startswith("timestamp") or kind == "date"


def match_columns(columns: list[tuple[str, str]]) -> tuple[dict[str, str], frozenset[str]]:
    """Which column holds each part of a news item, by its name (exact first, then a name containing the word)."""
    by_name = {name.casefold(): (name, kind) for name, kind in columns}
    exact = {n for names in ROLES.values() for n in names}
    chosen: dict[str, str] = {}
    arrays: set[str] = set()
    taken: set[str] = set()
    for role, names in ROLES.items():
        dated = role in ("date", "added")
        pick = next((by_name[n] for n in names if n in by_name and by_name[n][0] not in taken
                     and (not dated or _is_date(by_name[n][1]))), None)
        if pick is None and not dated:
            # news_headline, article_category...: a name that contains the word, and is not another part's exact name
            pick = next(((name, kind) for word in names[:3] for name, kind in columns
                         if word in name.casefold() and name not in taken and name.casefold() not in exact), None)
        if pick is None and role == "date":
            pick = next(((name, kind) for name, kind in columns if _is_date(kind) and name not in taken
                         and name.casefold() not in ROLES["added"]), None)
        if pick:
            chosen[role] = pick[0]
            taken.add(pick[0])
            if pick[1].endswith("[]"):
                arrays.add(role)
    if "date" not in chosen and "added" in chosen:
        chosen["date"] = chosen["added"]
    return chosen, frozenset(arrays)


def pick_table(rows: Iterable[dict[str, Any] | list[Any]], database: str) -> NewsTable | None:
    """The best news table among catalog rows (schema, name, column, type)."""
    tables: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for row in rows:
        schema, name, column, kind = (row[k] for k in ("schema", "name", "column", "type")) if isinstance(row, dict) else row
        tables.setdefault((str(schema), str(name)), []).append((str(column), str(kind)))
    best: tuple[float, NewsTable] | None = None
    for (schema, name), columns in tables.items():
        chosen, arrays = match_columns(columns)
        if "title" not in chosen:
            continue
        lowered = name.casefold()
        named = 20 if lowered == "news" else 6 if lowered.startswith("news") or lowered.endswith("news") else 0
        score = sum(ROLE_WEIGHT[r] for r in chosen) + named - 0.01 * len(name)  # the shorter name on a tie
        if best is None or score > best[0]:
            best = (score, NewsTable(database, schema, name, chosen, arrays))
    return best[1] if best else None


def _rows(postgres: PostgresQuery, sql: str, database: str | None = None, max_rows: int = 500) -> list[dict[str, Any]]:
    result = postgres.run(sql, database, max_rows)
    keys = [c["key"] for c in result.columns]
    return [dict(zip(keys, row, strict=True)) for row in result.rows]


def find_news(postgres: PostgresQuery, table: str | None = None, database: str | None = None) -> NewsTable | None:
    """The news table: the configured one, else the best match in the default database, then in the other databases."""
    if table:
        match = TABLE_NAME.match(table.strip())
        if not match:
            raise SourceError("invalid_setting", "WIZARD_NEWS_TABLE must be a table name such as news or public.news.")
        schema, name = match.group(1), match.group(2)
        named = f" AND lower(c.relname) = lower({literal(name)})" + (f" AND lower(n.nspname) = lower({literal(schema)})" if schema else "")
        return pick_table(_rows(postgres, f"{NEWS_COLUMNS}{named} ORDER BY 1, 2, a.attnum", database), database or postgres.settings.database)
    like = " AND c.relname ILIKE '%news%' AND c.relname NOT ILIKE '%newsletter%'"
    home = database or postgres.settings.database
    found = pick_table(_rows(postgres, f"{NEWS_COLUMNS}{like} ORDER BY 1, 2, a.attnum", home), home)
    if found or database:
        return found
    deadline = time.monotonic() + SEARCH_SECONDS
    for row in _rows(postgres, DATABASES, home)[:MAX_OTHER_DATABASES]:
        if time.monotonic() > deadline:
            break
        other = str(row["datname"])
        try:
            found = pick_table(_rows(postgres, f"{NEWS_COLUMNS}{like} ORDER BY 1, 2, a.attnum", other), other)
        except SourceError:
            continue  # a database this account cannot read
        if found:
            return found
    return None


def news_queries(table: NewsTable) -> dict[str, str]:
    """Wizard's fixed queries over the news table: totals, categories, articles per week, the latest articles."""
    cols, t = table.columns, table.sql
    # Recency and weeks count by publication date, which a curated table loaded in one go still spreads over time;
    # the time a row was added (when there is a column for it) is only reported.
    date = quote(cols["date"]) if "date" in cols else None
    parts = ["count(*) AS total"]
    if date:
        parts += [f"min({date}) AS first", f"max({date}) AS last",
                  f"count(*) FILTER (WHERE {date} >= now() - interval '7 days') AS last_7_days",
                  f"count(*) FILTER (WHERE {date} >= now() - interval '1 day') AS last_day"]
    if "added" in cols:
        parts.append(f"max({quote(cols['added'])}) AS last_added")
    queries = {"summary": f"SELECT {', '.join(parts)} FROM {t}"}
    if "category" in cols:
        category = quote(cols["category"])
        queries["categories"] = (
            f"SELECT u.name::text AS name, count(*) AS count FROM {t} AS t CROSS JOIN LATERAL unnest(t.{category}) AS u(name) "
            f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 40" if "category" in table.arrays else
            f"SELECT {category}::text AS name, count(*) AS count FROM {t} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 40")
    if date:
        queries["weekly"] = (f"SELECT date_trunc('week', {date})::date AS week, count(*) AS count FROM {t} "
                             f"WHERE {date} IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT 400")
    picked = []
    for role, width in (("title", 300), ("category", 160), ("source", 120), ("url", 600), ("summary", 420), ("market", 80)):
        if role in cols:
            column = quote(cols[role])
            text = f"array_to_string({column}, ', ')" if role in table.arrays else f"{column}::text"
            picked.append(f"left({text}, {width}) AS {role}")
    if date:
        picked.append(f"{date} AS date")
    order = f" ORDER BY {date} DESC NULLS LAST" if date else ""
    queries["latest"] = f"SELECT {', '.join(picked)} FROM {t}{order} LIMIT {LATEST}"
    return queries


def read_news(postgres: PostgresQuery, table: str | None = None, database: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    if database and not DATABASE_NAME.match(database):
        raise SourceError("invalid_setting", "WIZARD_NEWS_DATABASE must be a database name.")
    found = find_news(postgres, table, database)
    if found is None:
        where = f"{table} " if table else "a readable table or view whose name contains news "
        return {"status": "not_found", "message": f"Wizard found no {where}with a title column on the company database. "
                "Set WIZARD_NEWS_TABLE (schema.name) if the news table has another name."}
    queries = news_queries(found)
    summary = _rows(postgres, queries["summary"], found.database, 1)[0]
    categories = _rows(postgres, queries["categories"], found.database, 40) if "categories" in queries else []
    weekly = list(reversed(_rows(postgres, queries["weekly"], found.database, 400))) if "weekly" in queries else []
    latest = _rows(postgres, queries["latest"], found.database, LATEST)
    for item in latest:
        url = item.get("url")
        if url and not str(url).lower().startswith(("https://", "http://")):
            item["url"] = None  # only web links open from the page
    return {"status": "ok", "database": found.database, "table": found.sql, "columns": found.columns,
            "total": summary.get("total") or 0, "first": summary.get("first"), "last": summary.get("last"),
            "last_added": summary.get("last_added"), "last_7_days": summary.get("last_7_days"),
            "last_day": summary.get("last_day"),
            "categories": [{"name": c["name"] if c["name"] not in (None, "") else "Uncategorised", "count": c["count"]}
                           for c in categories],
            "weekly": [{"week": w["week"], "count": w["count"]} for w in weekly],
            "latest": latest, "queries": list(queries.values()), "data_mode": "LIVE",
            "elapsed_ms": int((time.perf_counter() - started) * 1000)}


def read_database(postgres: PostgresQuery) -> dict[str, Any]:
    """How many tables and views the read-only account can read, and in how many schemas."""
    row = _rows(postgres, f"SELECT count(*) AS relations, count(DISTINCT schema) AS schemas FROM ({RELATIONS}) AS r",
                None, 1)[0]
    return {"status": "ok", "database": postgres.settings.database, "relations": row.get("relations") or 0,
            "schemas": row.get("schemas") or 0, "data_mode": "LIVE"}


class LiveCache:
    """One read of the server for everyone who has the page open, at most every LIVE_SECONDS."""

    def __init__(self, seconds: float = LIVE_SECONDS) -> None:
        self.seconds = seconds
        self.lock = threading.Lock()
        self.saved: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, key: str, read: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self.lock:
            saved = self.saved.get(key)
            if saved and time.monotonic() - saved[0] < self.seconds:
                return saved[1]
            try:
                value = read()
            except SourceError as error:
                value = {"status": "error", "message": error.message}
            value = {**value, "read_at": time.time()}
            self.saved[key] = (time.monotonic(), value)
            return value


def live(postgres: PostgresQuery | None, allowed: bool, cache: LiveCache, table: str | None, database: str | None,
         name: str) -> dict[str, Any]:
    if postgres is None:
        off = {"status": "not_configured", "message": "No company database is set up on this Wizard."}
        return {"name": name, "database": off, "news": off}
    if not allowed:
        off = {"status": "not_allowed", "message": f"Your Wizard account may not read the whole {name}."}
        return {"name": name, "database": off, "news": off}
    key = f"{postgres.settings.host}/{postgres.settings.database}"
    return {"name": name,
            "database": cache.get(f"{key}:database", lambda: read_database(postgres)),
            "news": cache.get(f"{key}:news:{table or ''}:{database or ''}", lambda: read_news(postgres, table, database))}
