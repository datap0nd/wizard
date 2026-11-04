"""NERP: a few SQL views on a PostgreSQL server of their own, read with Gemini's own SELECT (tools nerp_*).

Owner decision (3 November 2026, docs/decisions/2026-11-03-nerp-views.md): "NERP is just a few sql views or tables. I
should be able to restrict it to a certain DB, with a certain URL, certain Schema. It only will have access to views."
Settings → NERP names the server (an address, host:port or a postgresql:// URL), the database, the one schema and a
read-only account, carried by the company file like the AI Team Database's.

What protects it, inside the tool:
- everything the AI Team Database's query has (postgres_query.py): one statement as a subquery, its own connection
  closed after the call, a READ ONLY transaction always rolled back, statement and lock timeouts, at most MAX_ROWS rows;
- the database is the configured one, never another (no `database` argument, no search of other databases);
- the statement may name only the views (and materialized views) of the configured schema: it is parsed (sqlglot, pure
  Python) and every relation it reads, in every CTE, subquery and join, must be one of them; a table, another schema's
  view, the catalog or a function that runs SQL text or reaches outside the database is refused before it runs; the
  search_path is that schema, so an unqualified name means its view;
- the account's own grants (the owner: views only) decide the rest.
A view reads its own tables with its owner's rights, so the statement is checked by the names it uses, not by its plan
(a view's plan shows the tables under it, which may sit in other schemas)."""
from __future__ import annotations

import contextlib
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote as url_unquote
from urllib.parse import urlsplit

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope

from .fixture_source import SourceError
from .pg import SSL_MODES, PgError, PgSettings, error_text, quote, schema_list
from .postgres_query import PostgresQuery, QueryResult, QuerySession, similar_relations

SYSTEM = "nerp"
DEFAULT_NAME = "NERP"
# The views (v) and materialized views (m) of the schema this account may read.
VIEWS = ("SELECT c.relname AS name, c.relkind AS kind, pg_catalog.obj_description(c.oid, 'pg_class') AS comment, "
         "(SELECT count(*) FROM pg_catalog.pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 "
         "AND NOT a.attisdropped) AS columns FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
         "ON n.oid = c.relnamespace WHERE n.nspname = :schema AND c.relkind IN ('v', 'm') "
         "AND pg_catalog.has_table_privilege(c.oid, 'SELECT') ORDER BY c.relname")
COLUMNS = ("SELECT a.attname AS name, pg_catalog.format_type(a.atttypid, a.atttypmod) AS type, "
           "pg_catalog.col_description(c.oid, a.attnum) AS comment FROM pg_catalog.pg_attribute a "
           "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
           "WHERE n.nspname = :schema AND c.relname = :view AND c.relkind IN ('v', 'm') AND a.attnum > 0 "
           "AND NOT a.attisdropped ORDER BY a.attnum")
VIEWS_CACHE_S = 300.0
# Functions a query may not call: they run SQL text of their own (query_to_xml), reach another server (dblink), read
# the server's files or large objects, change settings, or hold the session.
BLOCKED_FUNCTIONS = re.compile(r"^(dblink.*|query_to_xml.*|table_to_xml.*|cursor_to_xml.*|schema_to_xml.*|"
                               r"database_to_xml.*|pg_read_.*|pg_ls_.*|pg_stat_file|lo_.*|set_config|pg_sleep.*|"
                               r"pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|pg_advisory.*|"
                               r"pg_notify|pg_logical_.*|pg_replication_.*|pg_file_.*|copy)$", re.I)


@dataclass(frozen=True)
class NerpSettings:
    """The server, database, schema and read-only account of NERP (WIZARD_NERP_*)."""
    pg: PgSettings
    schema: str
    name: str = DEFAULT_NAME
    # The views Wizard may read (WIZARD_NERP_VIEWS, comma-separated like the schemas): empty, every view of the schema.
    views: tuple[str, ...] = ()

    def describe(self) -> str:
        only = f": {', '.join(self.views)} only" if self.views else ""
        return (f"{self.pg.user}@{self.pg.host}:{self.pg.port}/{self.pg.database}, schema {self.schema}, views only{only} "
                f"(sslmode {self.pg.sslmode})")

    def allows(self, view: str) -> bool:
        return not self.views or view in self.views


def settings_from(values: dict[str, str]) -> NerpSettings | None:
    """WIZARD_NERP_*: None when no server is set. The server may be a host, host:port or a postgresql:// URL (its
    port, database and user fill what is not set separately; a password in it is refused: it goes in its own field).
    Raises PgError for anything a person must fix."""
    def get(key: str, default: str = "") -> str:
        return (values.get(f"WIZARD_NERP_{key}") or "").strip() or default

    address = get("HOST")
    if not address:
        return None
    host, port, database, user = address, get("PORT"), get("DATABASE"), get("USER")
    if "://" in address:
        parts = urlsplit(address)
        if parts.scheme not in ("postgres", "postgresql"):
            raise PgError("NERP's server must be a host name or a postgresql:// address")
        if parts.password:
            raise PgError("put NERP's password in its Password field, not in the server address")
        try:
            url_port = parts.port
        except ValueError:
            raise PgError("NERP's port must be a number") from None
        host = parts.hostname or ""
        port = port or (str(url_port) if url_port else "")
        database = database or url_unquote(parts.path.strip("/"))
        user = user or url_unquote(parts.username or "")
    elif address.count(":") == 1:
        host, _, from_address = address.partition(":")
        port = port or from_address
    if not host:
        raise PgError("NERP's server has no host name")
    try:
        number = int(port or "5432")
    except ValueError:
        raise PgError("NERP's port must be a number") from None
    if not user:
        raise PgError("NERP needs its read-only user")
    if not database:
        raise PgError("NERP needs the database its views are in")
    schema = get("SCHEMA")
    if not schema:
        raise PgError("NERP needs the schema its views are in")
    sslmode = get("SSLMODE", "prefer").lower()
    if sslmode not in SSL_MODES:
        raise PgError("NERP's SSL mode must be disable, prefer, require, verify-ca or verify-full")
    views = schema_list(get("VIEWS"), "views Wizard may query in NERP", "view")
    return NerpSettings(PgSettings(host, number, database, user, values.get("WIZARD_NERP_PASSWORD") or "", sslmode,
                                   "Settings (WIZARD_NERP_*)", (schema,)), schema,
                        (get("NAME", DEFAULT_NAME) or DEFAULT_NAME)[:60], views)


def _identifier(node: exp.Expression | None) -> tuple[str, bool] | None:
    """An identifier as PostgreSQL reads it: (name, quoted). Unquoted names fold to lower case."""
    if not isinstance(node, exp.Identifier):
        return None
    return (node.this, True) if node.quoted else (str(node.this).lower(), False)


def _function_name(node: Any) -> str:
    """A function call's name as written (an unknown function) or as sqlglot knows it, in lower case."""
    return str(node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def check_views(sql: str, views: set[str], schema: str, database: str) -> None:
    """Refuse a statement that is not one query naming only `views` (exact names) of `schema` in `database`."""
    try:
        trees = sqlglot.parse(sql, read="postgres")
    except SqlglotError as error:
        raise SourceError("query_not_checked", f"Wizard could not read this query to check that it uses only "
                                               f"{schema}'s views ({str(error).splitlines()[0][:200]}). Write one plain "
                                               "SELECT (or WITH ... SELECT).") from None
    trees = [t for t in trees if t is not None]
    if len(trees) != 1 or not isinstance(trees[0], exp.Query) or trees[0].find(exp.Into):
        raise SourceError("not_a_query", "Send exactly one SELECT (or WITH ... SELECT); NERP is read only.")
    tree = trees[0]
    try:
        scopes = traverse_scope(tree)
    except SqlglotError as error:
        raise SourceError("query_not_checked", f"Wizard could not read this query's parts ({str(error)[:200]}). "
                                               "Write it more simply.") from None
    tables = {id(source): source for scope in scopes for source in scope.sources.values() if isinstance(source, exp.Table)}
    ctes = {str(cte.alias_or_name).lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):  # every table the scopes did not account for, unless it names a CTE
        if id(table) not in tables and not (not table.db and str(table.name).lower() in ctes):
            tables[id(table)] = table
    wrong: list[str] = []
    for table in tables.values():
        catalog = _identifier(table.args.get("catalog"))
        if catalog and catalog[0] != database:
            wrong.append(f"{table.sql(dialect='postgres')} (another database)")
            continue
        qualifier = _identifier(table.args.get("db"))
        if not isinstance(table.this, exp.Identifier):  # a function in FROM: generate_series(...), unnest(...)
            if qualifier and qualifier[0] not in (schema, "pg_catalog"):
                wrong.append(f"{table.sql(dialect='postgres')} (a function of another schema)")
            continue
        if qualifier and qualifier[0] != schema:
            wrong.append(f"{table.sql(dialect='postgres')} (schema {qualifier[0]})")
            continue
        name = _identifier(table.this)
        if name is None or name[0] not in views:
            wrong.append(f"{table.sql(dialect='postgres')} (not one of {schema}'s views)")
    for node in tree.find_all(exp.Func):
        if BLOCKED_FUNCTIONS.match(_function_name(node)):
            wrong.append(f"{_function_name(node)}() (a function that runs SQL text or reaches outside the database)")
    for dot in tree.find_all(exp.Dot):
        if isinstance(dot.expression, exp.Func):
            qualifier = _identifier(dot.this if isinstance(dot.this, exp.Identifier) else
                                    dot.this.this if isinstance(dot.this, exp.Column) else None)
            if qualifier is None or qualifier[0] not in (schema, "pg_catalog"):
                wrong.append(f"{dot.sql(dialect='postgres')[:80]} (a function of another schema)")
    if wrong:
        shown = sorted(set(wrong))[:8]
        raise SourceError("not_a_nerp_view",
                          f"NERP queries may read only the views Wizard may query in schema {schema}; this one names "
                          f"{', '.join(shown)}. nerp_list_views lists them; join and filter those views.")


class NerpQuery(PostgresQuery):
    """Gemini's SELECT on NERP's views, and the list of those views and their columns."""

    def __init__(self, settings: NerpSettings, **kwargs: Any):
        super().__init__(settings.pg, **kwargs)
        self.nerp = settings
        self._views: tuple[float, list[dict[str, Any]]] | None = None

    @property
    def schema(self) -> str:
        return self.nerp.schema

    @property
    def name(self) -> str:
        return self.nerp.name

    def run(self, sql: str, database: str | None = None, max_rows: int = 200) -> QueryResult:
        return super().run(sql, self.settings.database, max_rows)  # never another database

    def check(self, session: QuerySession, text: str, wrapped: str) -> None:
        views = {str(v["name"]) for v in self._catalog(session)}
        check_views(text, views, self.schema, self.settings.database)
        session.rows(f"SET LOCAL search_path TO {quote(self.schema)}, pg_catalog")

    def allows(self, schema: str) -> bool:
        return schema == self.schema

    def where_is(self, session: QuerySession, database: str, missing: str) -> str:
        """A view that does not exist: NERP's views with a similar name (never another schema or database)."""
        try:
            session.rows("ROLLBACK")
            session.rows("START TRANSACTION READ ONLY")
            names = [(self.schema, str(v["name"])) for v in session.rows(VIEWS, schema=self.schema)
                 if self.nerp.allows(str(v["name"]))]
        except Exception:  # noqa: BLE001 - the hint is a courtesy; the query's own error stands
            return ""
        similar = similar_relations(missing, names)
        return (f". NERP views with a similar name: {', '.join(similar)}." if similar else
                ". nerp_list_views lists NERP's views.")

    def _catalog(self, session: QuerySession) -> list[dict[str, Any]]:
        cached = self._views
        if cached and time.monotonic() - cached[0] < VIEWS_CACHE_S:
            return cached[1]
        found = [dict(r) for r in session.rows(VIEWS, schema=self.schema) if self.nerp.allows(str(r["name"]))]
        self._views = (time.monotonic(), found)
        return found

    def _read(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        """A catalog read in its own read-only transaction, rolled back, on a connection closed after it."""
        try:
            session = self.connect(self.settings, self.settings.database)
        except PgError as error:
            raise SourceError("source_unavailable", f"NERP is not reachable: {error}") from None
        try:
            session.rows("START TRANSACTION READ ONLY")
            return [dict(r) for r in session.rows(sql, **params)]
        except SourceError:
            raise
        except Exception as error:  # noqa: BLE001 - one readable tool error
            raise SourceError("query_failed", f"NERP could not list its views: {error_text(error)}") from None
        finally:
            with contextlib.suppress(Exception):
                session.rows("ROLLBACK")
            session.close()

    def views(self, fresh: bool = False) -> list[dict[str, Any]]:
        """The schema's views this account reads and the settings allow (WIZARD_NERP_VIEWS)."""
        if fresh or not self._views or time.monotonic() - self._views[0] >= VIEWS_CACHE_S:
            self._views = (time.monotonic(), [r for r in self._read(VIEWS, schema=self.schema)
                                              if self.nerp.allows(str(r["name"]))])
        return self._views[1]

    def missing(self) -> list[str]:
        """Views the settings allow that the schema does not hold (a typo, or a view the account cannot read)."""
        have = {str(r["name"]) for r in self.views()}
        return [v for v in self.nerp.views if v not in have]

    def columns(self, view: str) -> list[dict[str, Any]]:
        if not self.nerp.allows(view):
            return []
        return self._read(COLUMNS, schema=self.schema, view=view)

