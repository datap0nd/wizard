"""Read-only SQL on the company PostgreSQL server, written by Gemini (tool wizard_query_postgresql).

Gemini writes its own query, guided by the dataset notes; Wizard does not choose the analysis. What protects
the server:
- the account (WIZARD_PG_* in .env, else PG*): a read-only role, whose grants decide what can be read;
- every call opens its own connection and sends exactly one statement through PostgreSQL's extended protocol, which
  refuses a second statement. The statement is wrapped as a subquery, so it can only be a query, and runs in a READ ONLY
  transaction that is always rolled back, with statement and lock timeouts. The connection is then closed, so nothing a
  query sets or locks outlives the call;
- at most MAX_ROWS rows come back to Gemini, which aggregates in SQL for anything larger;
- when the company limits the schemas Wizard may query (WIZARD_PG_SCHEMAS; owner, 2 Nov 2026: one schema allowed,
  another forbidden), the statement is first explained in the same read-only transaction (EXPLAIN (VERBOSE, FORMAT
  JSON), which plans it without running it) and refused when the plan reads a relation in any other schema: every scan
  of a table, materialized view or foreign table, in CTEs, subqueries and joins, and the tables under a view alike.
  pg_catalog and information_schema (metadata) are always allowed.
When a query names a table or view that does not exist, the error says where to look instead: readable relations with a
similar name in that database, and the other databases on the server that have one by that name. A dataset note can
name a view that was renamed or lives elsewhere, and guessing costs Gemini a step each time. These are catalog reads,
under the same protections.
Model-written SQL is sent exactly as written: pg8000's own placeholder parsing is bypassed. Building a statement from
that text is the point of this module, hence ruff's S608 is waived for this file in pyproject.toml."""
from __future__ import annotations

import contextlib
import datetime as dt
import difflib
import hashlib
import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from .fixture_source import SourceError
from .pg import Pg8000Session, PgError, PgSettings, error_text, quote, sqlstate

MAX_ROWS = 500
STATEMENT_TIMEOUT = "60s"
INTEGER_OIDS = {20, 21, 23}
NUMBER_OIDS = {700, 701, 790, 1700}
DOLLAR_TAG = re.compile(r"\$[A-Za-z_]?[A-Za-z0-9_]*\$")
MISSING_RELATION = re.compile(r'relation "([^"]+)" does not exist')
PLAIN_NAME = re.compile(r"[a-z_][a-z0-9_$]*")
# Readable tables, views and materialized views, as schema and name; :relname / :schema narrow it to one name.
RELATIONS = ("SELECT n.nspname AS schema, c.relname AS name FROM pg_catalog.pg_class c "
             "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
             "WHERE c.relkind IN ('r', 'v', 'm', 'p', 'f') AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
             "AND n.nspname NOT LIKE 'pg\\_%' AND pg_catalog.has_schema_privilege(n.oid, 'USAGE') "
             "AND pg_catalog.has_table_privilege(c.oid, 'SELECT')")
NAMED = " AND lower(c.relname) = lower(:relname) AND (:schema = '' OR lower(n.nspname) = lower(:schema))"
DATABASES = ("SELECT datname FROM pg_catalog.pg_database WHERE datallowconn AND NOT datistemplate "
             "AND datname <> current_database() AND pg_catalog.has_database_privilege(datname, 'CONNECT') ORDER BY 1")
# Metadata schemas a query may always read, whatever WIZARD_PG_SCHEMAS allows.
METADATA_SCHEMAS = frozenset({"pg_catalog", "information_schema"})
MAX_RELATIONS = 20_000      # names compared for a missing relation
MAX_SIMILAR = 5
MAX_OTHER_DATABASES = 12
SEARCH_SECONDS = 10.0       # the other databases are searched for at most this long


def _code(sql: str) -> Iterator[tuple[int, str]]:
    """Each character of SQL outside comments, with its index. A string literal, quoted name or dollar-quoted body is
    one item, its opening quote, so a semicolon inside it is never seen."""
    i, n = 0, len(sql)
    while i < n:
        c, start = sql[i], i
        if c == "'":
            escapes = i > 0 and sql[i - 1] in "eE"
            i += 1
            while i < n and not (sql[i] == "'" and not (i + 1 < n and sql[i + 1] == "'")):
                i += 2 if (sql[i] == "'" or (escapes and sql[i] == "\\")) else 1
        elif c == '"':
            i = sql.find('"', i + 1)
            i = n if i < 0 else i
        elif sql.startswith("--", i):
            i = sql.find("\n", i)
            i = n if i < 0 else i
            continue
        elif sql.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                depth += 1 if sql.startswith("/*", i) else -1 if sql.startswith("*/", i) else 0
                i += 2 if sql.startswith(("/*", "*/"), i) else 1
            continue
        elif c == "$" and (tag := DOLLAR_TAG.match(sql, i)):
            close = sql.find(tag.group(), tag.end())
            i = n if close < 0 else close + len(tag.group()) - 1
        yield start, c
        i += 1


def without_terminator(sql: str) -> str:
    """Drop a final semicolon when only whitespace and comments follow it ('... DESC;  -- latest week'), scanning
    string literals, quoted names, dollar quotes and comments so a semicolon inside them is never touched. A semicolon
    followed by more SQL stays: PostgreSQL then refuses the second statement."""
    end = None
    for i, c in _code(sql):
        if c == ";":
            end = i if end is None else end
        elif not c.isspace():
            end = None
    return sql[:end] if end is not None else sql


def one_statement(sql: str) -> str:
    """The query without a final semicolon, or SourceError when a semicolon outside literals and comments separates it
    from more SQL. For a query that runs where PostgreSQL's extended protocol does not refuse a second statement (a
    recurring extraction's script on Metronome)."""
    text = without_terminator(sql).strip()
    if not text:
        raise SourceError("invalid_sql", "The query is empty.")
    if any(c == ";" for _, c in _code(text)):
        raise SourceError("invalid_sql", "Send one query: SELECT ... or WITH ... SELECT ..., without other statements.")
    return text


class QuerySession(Protocol):
    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]: ...
    def query(self, sql: str) -> tuple[list[dict[str, Any]], list[list[Any]]]: ...
    def close(self) -> None: ...


def connect_default(settings: PgSettings, database: str) -> QuerySession:
    return Pg8000Session(settings, database, STATEMENT_TIMEOUT, "2s", "wizard-query")


def plain(value: Any) -> Any:
    """Database values as JSON-friendly Python: numbers stay numbers, dates and times become ISO text."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() and abs(value) < 10**15 else float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{len(bytes(value))} bytes>"
    return str(value)


def column_type(oid: int | None) -> str:
    return "integer" if oid in INTEGER_OIDS else "number" if oid in NUMBER_OIDS else "string"


@dataclass
class QueryResult:
    database: str
    columns: list[dict[str, Any]]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: int
    digest: str


class PostgresQuery:
    def __init__(self, settings: PgSettings, connect: Callable[[PgSettings, str], QuerySession] = connect_default):
        self.settings = settings
        self.connect = connect

    def run(self, sql: str, database: str | None = None, max_rows: int = 200) -> QueryResult:
        text = without_terminator(sql).strip()
        if not text:
            raise SourceError("invalid_sql", "The query is empty.")
        database = database or self.settings.database
        max_rows = max(1, min(max_rows, MAX_ROWS))
        # The newlines keep a trailing -- comment from swallowing the closing parenthesis.
        wrapped = f"SELECT * FROM (\n{text}\n) AS wizard_query LIMIT {max_rows + 1}"
        try:
            session = self.connect(self.settings, database)
        except PgError as error:
            raise SourceError("source_unavailable", f"PostgreSQL is not reachable: {error}") from None
        started = time.perf_counter()
        try:
            session.rows("START TRANSACTION READ ONLY")
            self.check(session, text, wrapped)
            columns, rows = session.query(wrapped)
        except SourceError:
            raise
        except Exception as error:  # noqa: BLE001 - a database error becomes one readable tool error Gemini can act on
            message = error_text(error)
            if "syntax error" in message or "multiple commands" in message:
                message += (". Send one query per call: SELECT ... or WITH ... SELECT ..., without other statements "
                            "(it runs as a subquery).")
            missing = MISSING_RELATION.search(message) if sqlstate(error) == "42P01" else None
            if missing:
                message += self.where_is(session, database, missing.group(1))
            raise SourceError("query_failed", f"PostgreSQL could not run this query: {message}") from None
        finally:
            with contextlib.suppress(Exception):  # the connection is closed next either way
                session.rows("ROLLBACK")
            session.close()
        names: list[str] = []
        for column in columns:
            name = str(column.get("name") or "column")
            key, n = name, 2
            while key in names:  # SQL allows two columns with one name; evidence rows are matched by key
                key, n = f"{name}_{n}", n + 1
            names.append(key)
        out_columns = [{"key": key, "label": key, "type": column_type(c.get("type_oid"))} for key, c in zip(names, columns, strict=True)]
        out_rows = [[plain(v) for v in row] for row in rows[:max_rows]]
        digest = hashlib.sha256(json.dumps([names, out_rows], default=str, sort_keys=True).encode()).hexdigest()
        return QueryResult(database, out_columns, out_rows, len(rows) > max_rows,
                           int((time.perf_counter() - started) * 1000), digest)

    def check(self, session: QuerySession, text: str, wrapped: str) -> None:
        """What a statement must pass before it runs, in its own read-only transaction: here, the schemas it reads.
        NERP's query (nerp.py) checks that it names only the views of its schema instead."""
        if self.settings.schemas:
            self.check_schemas(session, wrapped)

    def allows(self, schema: str) -> bool:
        """A query may read this schema: no limit is set, it is listed, or it is metadata."""
        return not self.settings.schemas or schema in self.settings.schemas or schema in METADATA_SCHEMAS

    def check_schemas(self, session: QuerySession, wrapped: str) -> None:
        """Refuse the statement when its plan reads a relation outside the schemas Wizard may query. Runs in the
        query's own read-only transaction; EXPLAIN without ANALYZE plans the statement and runs nothing."""
        _, found = session.query(f"EXPLAIN (VERBOSE, FORMAT JSON) {wrapped}")
        plan = found[0][0] if found and found[0] else None
        if isinstance(plan, str | bytes):
            plan = json.loads(plan)
        if not isinstance(plan, list | dict):
            raise SourceError("query_failed", "PostgreSQL returned no plan for this query, so Wizard cannot check which "
                                              "schemas it reads.")
        outside = list(dict.fromkeys((schema, name) for schema, name in plan_relations(plan) if not self.allows(schema)))
        if outside:
            read = ", ".join(f"{sql_name(schema, name) if name else schema} (schema {schema})" for schema, name in outside[:8])
            allowed = self.settings.schemas
            raise SourceError("schema_not_allowed",
                              f"This query reads {read}, and Wizard may query only the schema"
                              f"{'s' if len(allowed) > 1 else ''} {', '.join(allowed)} of this database (with pg_catalog "
                              "and information_schema for metadata). A view counts by the tables it reads. Use tables "
                              "and views in the allowed schemas, and say so if the answer needs data that is only "
                              "elsewhere.")

    def where_is(self, session: QuerySession, database: str, missing: str) -> str:
        """For "relation ... does not exist": the readable relations with a similar name in this database, and the other
        databases on the server that have a readable one by that name. Catalog reads only, each in a read-only
        transaction that is rolled back; another database gets its own connection, closed after one lookup."""
        schema, _, relname = missing.rpartition(".")
        try:
            session.rows("ROLLBACK")  # the failed query aborted the transaction
            session.rows("START TRANSACTION READ ONLY")
            names = [(str(r["schema"]), str(r["name"])) for r in session.rows(f"{RELATIONS} ORDER BY 1, 2 LIMIT {MAX_RELATIONS}")
                     if self.allows(str(r["schema"]))]  # never point at a schema Wizard may not query
            others = [str(r["datname"]) for r in session.rows(DATABASES)][:MAX_OTHER_DATABASES]
        except Exception:  # noqa: BLE001 - the hint is a courtesy; the query's own error stands
            return ""
        similar = similar_relations(missing, names)
        found: list[str] = []
        deadline = time.monotonic() + SEARCH_SECONDS
        for other in others:
            if time.monotonic() > deadline:
                break
            try:
                elsewhere = self.connect(self.settings, other)
            except PgError:
                continue
            try:
                with contextlib.suppress(Exception):  # a database this account cannot read is skipped
                    elsewhere.rows("START TRANSACTION READ ONLY")
                    rows = elsewhere.rows(f"{RELATIONS}{NAMED} ORDER BY 1, 2 LIMIT 3", relname=relname, schema=schema)
                    found += [f"{sql_name(str(r['schema']), str(r['name']))} in database {other}" for r in rows
                              if self.allows(str(r["schema"]))]
            finally:
                with contextlib.suppress(Exception):
                    elsewhere.rows("ROLLBACK")
                elsewhere.close()
        hints = []
        if found:
            hints.append(f"Found {'; '.join(found)}: set database to query it.")
        if similar:
            hints.append(f"Readable relations with a similar name in database {database}: {', '.join(similar)}.")
        if not hints:
            hints.append(f"No readable table or view in database {database}{' or the other databases' if others else ''} "
                         "has a similar name; look in information_schema.tables rather than guessing.")
        return ". " + " ".join(hints)


def plan_relations(plan: Any) -> list[tuple[str, str]]:
    """Every (schema, name) an EXPLAIN (VERBOSE, FORMAT JSON) plan reads: each node with a Schema key (a table, a view's
    table, a materialized view or foreign table it scans, or a function it scans), at any depth (CTEs, subqueries,
    joins, init plans), in plan order."""
    found: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            schema = node.get("Schema")
            if isinstance(schema, str):
                found.append((schema, str(node.get("Relation Name") or node.get("Function Name") or "")))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(plan)
    return found


def sql_name(schema: str, name: str) -> str:
    """schema.name as it must be written in SQL: quoted only where PostgreSQL would otherwise fold or reject it."""
    return ".".join(part if PLAIN_NAME.fullmatch(part) else quote(part) for part in (schema, name))


def similar_relations(missing: str, names: list[tuple[str, str]]) -> list[str]:
    """The relations closest to a missing name: the same name in another schema (or spelt with capitals) first, then
    close spellings of the name (global_lc_v -> global_lc_v_weekly), in the same schema before others. Names are
    compared without their schema, which would make every view of a schema look alike."""
    schema, _, relname = missing.lower().rpartition(".")
    scored: list[tuple[float, str]] = []
    for found_schema, found_name in names:
        alone = found_name.lower()
        score = 2.0 if alone == relname else difflib.SequenceMatcher(None, relname, alone).ratio()
        score += 0.05 if found_schema.lower() == schema else 0.0
        if score >= 0.6:
            scored.append((score, sql_name(found_schema, found_name)))
    return [name for _, name in sorted(scored, key=lambda item: -item[0])[:MAX_SIMILAR]]
