"""Read-only SQL on the company PostgreSQL server, written by Gemini (tool wizard_query_postgresql).

Gemini writes its own query, guided by the dataset notes (task 18); Wizard does not choose the analysis. What protects
the server:
- the account (WIZARD_PG_* in .env, else PG*): a read-only role, whose grants decide what can be read;
- every call opens its own connection and sends exactly one statement through PostgreSQL's extended protocol, which
  refuses a second statement. The statement is wrapped as a subquery, so it can only be a query, and runs in a READ ONLY
  transaction that is always rolled back, with statement and lock timeouts. The connection is then closed, so nothing a
  query sets or locks outlives the call;
- at most MAX_ROWS rows come back to Gemini, which aggregates in SQL for anything larger.
Model-written SQL is sent exactly as written: pg8000's own placeholder parsing is bypassed. Building a statement from
that text is the point of this module, hence ruff's S608 is waived for this file in pyproject.toml."""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from .fixture_source import SourceError
from .pg import Pg8000Session, PgError, PgSettings, error_text

MAX_ROWS = 500
STATEMENT_TIMEOUT = "60s"
INTEGER_OIDS = {20, 21, 23}
NUMBER_OIDS = {700, 701, 790, 1700}
DOLLAR_TAG = re.compile(r"\$[A-Za-z_]?[A-Za-z0-9_]*\$")


def without_terminator(sql: str) -> str:
    """Drop a final semicolon when only whitespace and comments follow it ('... DESC;  -- latest week'), scanning
    string literals, quoted names, dollar quotes and comments so a semicolon inside them is never touched. A semicolon
    followed by more SQL stays: PostgreSQL then refuses the second statement."""
    i, n, end = 0, len(sql), None
    while i < n:
        c = sql[i]
        if c in "'\"$":
            end = None  # a literal, quoted name or parameter is more SQL after any semicolon
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
        elif c == ";":
            end = i if end is None else end
        elif not c.isspace():
            end = None
        i += 1
    return sql[:end] if end is not None else sql


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
            columns, rows = session.query(wrapped)
        except Exception as error:  # noqa: BLE001 - a database error becomes one readable tool error Gemini can act on
            message = error_text(error)
            if "syntax error" in message or "multiple commands" in message:
                message += (". Send one query per call: SELECT ... or WITH ... SELECT ..., without other statements "
                            "(it runs as a subquery).")
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
