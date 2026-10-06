"""Read-only documentation export of a PostgreSQL server's materialized views: the source of truth for the data
dictionary Gemini CLI writes (task 18).

Per materialized view: columns and types, comments, owner role, indexes, the SQL definition (how every column is
computed), what it reads from and what reads it, the pg_cron job that refreshes it, statistics, and, with the light
profile, row count, freshness (commit timestamps when the server tracks them), null rates, distinct counts, date
ranges and the values of small code columns. Business figures (sums, numeric ranges) are never read.

Connection: WIZARD_PG_HOST / _PORT / _DATABASE / _USER / _PASSWORD / _SSLMODE in Wizard's .env, else the standard
PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD / PGSSLMODE (data_governance's read-only scanner account). Never the
uploader account. The password is never printed or written.

Safety: the session is read-only, with a statement timeout and a short lock timeout (a view being refreshed is
skipped, not waited for). pg8000 is pure Python, so Application Control has no driver DLL to block.

SQL is assembled here only from catalog names, always through quote() (identifiers) and literal() (the optional schema
filter), never from model or user text; hence ruff's S608 is waived for this file in pyproject.toml."""
from __future__ import annotations

import contextlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .common import ConversionError, cell, mask_contacts

STATEMENT_TIMEOUT = "60s"
LOCK_TIMEOUT = "2s"
SAMPLE_ROWS = 200_000      # larger views are profiled on a TABLESAMPLE of about this many rows
MAX_PROFILED_COLUMNS = 80
MAX_VALUES = 25            # a text column with at most this many values gets its value list
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema")
NO_EQUALITY = ("json", "xml", "point", "line", "lseg", "box", "path", "polygon", "circle", "tsvector", "tsquery")
DATE_TYPES = ("date", "timestamp", "time")
TEXTUAL = ("text", "character varying", "character", "varchar", "char", "bpchar", "citext", "name")
TEXT_TYPES = (*TEXTUAL, "boolean")
WHOLE_NUMBERS = ("integer", "smallint", "bigint")
DATE_NAMES = re.compile(r"(^|_)(date|day|dt|week|wk|month|mon|period|year|yr|quarter|qtr|time|ts|fy)(_|$)")
# Columns that name or reach people: their values are never listed.
PERSONAL = re.compile(r"(^|_)(email|e_mail|mail|phone|mobile|tel|user|username|login|employee|emp|person|owner|contact|"
                      r"address|customer|cust|first_name|last_name|full_name|firstname|lastname|rep|representative|"
                      r"salesperson|salesman|manager|mgr|approver|requester|requestor|assignee|author|by)(_|$)")


class Session(Protocol):
    def rows(self, sql: str) -> list[dict[str, Any]]: ...


@dataclass
class PgSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    sslmode: str
    source: str  # which settings were used: ".env (WIZARD_PG_*)" or "environment (PG*)"

    def describe(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.database} (sslmode {self.sslmode}, from {self.source})"


@dataclass
class Column:
    position: int
    name: str
    type: str
    not_null: bool
    comment: str = ""
    nulls: float | None = None       # share of rows that are NULL (0-1)
    distinct: int | None = None
    range: str = ""                  # "2024-01-01 to 2026-09-30" for date-like columns
    values: list[str] = field(default_factory=list)
    more_values: bool = False


@dataclass
class MatView:
    database: str
    schema: str
    name: str
    oid: int
    owner: str
    comment: str
    populated: bool
    readable: bool
    estimated_rows: int
    bytes: int
    definition: str
    columns: list[Column] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)
    reads_from: list[str] = field(default_factory=list)   # "schema.name (kind)"
    used_by: list[str] = field(default_factory=list)
    refresh_jobs: list[str] = field(default_factory=list)
    last_analyze: str = ""
    rows: int | None = None
    rows_exact: bool = False
    sampled: bool = False
    freshness: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"


# --- Settings and connection ----------------------------------------------------------------------------------------


def read_env(path: Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if path is None or not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def settings_from(env_file: Path | None, environ: dict[str, str] | None = None) -> PgSettings:
    env = read_env(env_file)
    environ = dict(os.environ) if environ is None else environ
    if env.get("WIZARD_PG_HOST") or environ.get("WIZARD_PG_HOST"):
        def get(key: str, default: str = "") -> str:
            return env.get(f"WIZARD_PG_{key}") or environ.get(f"WIZARD_PG_{key}") or default
        source = ".env (WIZARD_PG_*)"
    else:
        def get(key: str, default: str = "") -> str:
            return environ.get(f"PG{key}", "") or default  # PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE
        source = "environment (PG*)"
    host, user = get("HOST"), get("USER")
    if not host or not user:
        raise ConversionError("no PostgreSQL connection settings: add WIZARD_PG_HOST, WIZARD_PG_PORT, WIZARD_PG_DATABASE, "
                              "WIZARD_PG_USER and WIZARD_PG_PASSWORD (a read-only account) to Wizard's .env, or set the "
                              "PGHOST/PGUSER/PGPASSWORD variables of the read-only scanner account")
    try:
        port = int(get("PORT", "5432"))
    except ValueError:
        raise ConversionError("the PostgreSQL port must be a number") from None
    sslmode = get("SSLMODE", "prefer").lower()
    if sslmode not in ("disable", "prefer", "require", "verify-ca", "verify-full"):
        raise ConversionError("the PostgreSQL sslmode must be disable, prefer, require, verify-ca or verify-full")
    return PgSettings(host, port, get("DATABASE", "postgres"), user, get("PASSWORD"), sslmode, source)


class Pg8000Session:
    """A read-only pg8000 session (rows come back as dicts)."""

    def __init__(self, settings: PgSettings, database: str | None = None):
        try:
            import pg8000.native
        except ImportError as error:
            raise ConversionError(f"the PostgreSQL driver pg8000 is not installed ({error}); run setup.ps1 again") from None
        ssl_context: Any
        if settings.sslmode == "disable":
            ssl_context = False
        elif settings.sslmode == "prefer":
            ssl_context = None  # pg8000: TLS when the server offers it, plain otherwise
        elif settings.sslmode == "require":
            ssl_context = True
        else:
            import ssl
            try:
                import truststore
                ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # Windows certificate store
            except ImportError:
                ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = settings.sslmode == "verify-full"
        try:
            self.connection = pg8000.native.Connection(
                settings.user, host=settings.host, port=settings.port, database=database or settings.database,
                password=settings.password or None, ssl_context=ssl_context, timeout=30, application_name="wizard-docs")
        except Exception as error:  # noqa: BLE001 - driver errors become one readable line
            raise ConversionError(f"could not connect to {settings.host}:{settings.port}/{database or settings.database} "
                                  f"as {settings.user}: {error_text(error)}") from None
        for statement in ("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY",
                          f"SET statement_timeout = '{STATEMENT_TIMEOUT}'", f"SET lock_timeout = '{LOCK_TIMEOUT}'"):
            self.connection.run(statement)

    def rows(self, sql: str) -> list[dict[str, Any]]:
        result = self.connection.run(sql) or []
        names = [c["name"] for c in self.connection.columns or []]
        return [dict(zip(names, row, strict=False)) for row in result]

    def close(self) -> None:
        with contextlib.suppress(Exception):  # closing a broken connection is not an error worth reporting
            self.connection.close()


def error_text(error: BaseException) -> str:
    args = getattr(error, "args", ())
    if args and isinstance(args[0], dict):  # pg8000 DatabaseError: {'S': 'ERROR', 'C': '57014', 'M': 'canceling ...'}
        detail = args[0]
        return f"{detail.get('M', 'database error')} (SQLSTATE {detail.get('C', '?')})"
    return " ".join(str(error).split())[:300] or type(error).__name__


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


# --- Catalog --------------------------------------------------------------------------------------------------------


def server_facts(session: Session) -> dict[str, Any]:
    row = session.rows("SELECT current_user AS user_name, current_database() AS database, "
                       "current_setting('server_version') AS version, current_setting('transaction_read_only') AS read_only, "
                       "current_setting('track_commit_timestamp') AS commit_timestamps")[0]
    role = session.rows("SELECT rolsuper AS superuser, rolcreaterole AS createrole, rolcreatedb AS createdb "
                        "FROM pg_catalog.pg_roles WHERE rolname = current_user")
    return {**row, **(role[0] if role else {})}


def databases(session: Session) -> list[str]:
    return [r["datname"] for r in session.rows(
        "SELECT datname FROM pg_catalog.pg_database WHERE datallowconn AND NOT datistemplate "
        "AND has_database_privilege(datname, 'CONNECT') ORDER BY 1")]


def schema_filter(schemas: list[str] | None) -> str:
    base = "n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%' " \
           "AND n.nspname NOT LIKE 'pg_temp%'"
    if schemas:
        base += " AND n.nspname IN (" + ", ".join(literal(s) for s in schemas) + ")"
    return base


def read_catalog(session: Session, database: str, schemas: list[str] | None = None) -> list[MatView]:
    where = schema_filter(schemas)
    views = [MatView(database=database, schema=r["schema"], name=r["name"], oid=int(r["oid"]), owner=r["owner"] or "",
                     comment=r["comment"] or "", populated=bool(r["populated"]), readable=bool(r["readable"]),
                     estimated_rows=max(int(r["estimated_rows"] or 0), 0), bytes=int(r["bytes"] or 0),
                     definition=(r["definition"] or "").strip())
             for r in session.rows(
                 "SELECT c.oid::bigint AS oid, n.nspname AS schema, c.relname AS name, "
                 "pg_catalog.pg_get_userbyid(c.relowner) AS owner, pg_catalog.obj_description(c.oid, 'pg_class') AS comment, "
                 "c.relispopulated AS populated, c.reltuples::bigint AS estimated_rows, "
                 "pg_catalog.pg_total_relation_size(c.oid) AS bytes, pg_catalog.pg_get_viewdef(c.oid, true) AS definition, "
                 "pg_catalog.has_table_privilege(c.oid, 'SELECT') AS readable "
                 "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                 f"WHERE c.relkind = 'm' AND has_schema_privilege(n.oid, 'USAGE') AND {where} ORDER BY 2, 3")]
    by_oid = {v.oid: v for v in views}
    if not views:
        return views
    for r in session.rows(
            "SELECT c.oid::bigint AS oid, a.attnum AS position, a.attname AS name, "
            "pg_catalog.format_type(a.atttypid, a.atttypmod) AS type, a.attnotnull AS not_null, "
            "pg_catalog.col_description(c.oid, a.attnum) AS comment "
            "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid "
            f"WHERE c.relkind = 'm' AND a.attnum > 0 AND NOT a.attisdropped AND {where} ORDER BY 1, 2"):
        if int(r["oid"]) in by_oid:
            by_oid[int(r["oid"])].columns.append(Column(int(r["position"]), r["name"], r["type"], bool(r["not_null"]),
                                                        r["comment"] or ""))
    for r in session.rows(
            "SELECT i.indrelid::bigint AS oid, pg_catalog.pg_get_indexdef(i.indexrelid) AS definition "
            "FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid = i.indrelid "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE c.relkind = 'm' AND {where} ORDER BY 1, 2"):
        if int(r["oid"]) in by_oid:
            by_oid[int(r["oid"])].indexes.append(r["definition"])
    for r in session.rows(  # lineage through the views' rewrite rules, in both directions
            "SELECT DISTINCT v.oid::bigint AS reader, v.relkind AS reader_kind, vn.nspname AS reader_schema, "
            "v.relname AS reader_name, s.oid::bigint AS source, s.relkind AS source_kind, sn.nspname AS source_schema, "
            "s.relname AS source_name "
            "FROM pg_catalog.pg_class v JOIN pg_catalog.pg_namespace vn ON vn.oid = v.relnamespace "
            "JOIN pg_catalog.pg_rewrite r ON r.ev_class = v.oid "
            "JOIN pg_catalog.pg_depend d ON d.objid = r.oid AND d.classid = 'pg_catalog.pg_rewrite'::regclass "
            "AND d.refclassid = 'pg_catalog.pg_class'::regclass "
            "JOIN pg_catalog.pg_class s ON s.oid = d.refobjid AND s.oid <> v.oid "
            "JOIN pg_catalog.pg_namespace sn ON sn.oid = s.relnamespace "
            "WHERE (v.relkind = 'm' OR s.relkind = 'm') AND v.relkind IN ('m', 'v') ORDER BY 3, 4, 7, 8"):
        if int(r["reader"]) in by_oid:
            by_oid[int(r["reader"])].reads_from.append(f"{r['source_schema']}.{r['source_name']} ({kind_name(r['source_kind'])})")
        if int(r["source"]) in by_oid:
            by_oid[int(r["source"])].used_by.append(f"{r['reader_schema']}.{r['reader_name']} ({kind_name(r['reader_kind'])})")
    for r in session.rows(
            "SELECT relid::bigint AS oid, greatest(last_analyze, last_autoanalyze) AS analyzed "
            "FROM pg_catalog.pg_stat_all_tables WHERE relid IN ("
            + ", ".join(str(v.oid) for v in views) + ")"):
        if int(r["oid"]) in by_oid and r["analyzed"]:
            by_oid[int(r["oid"])].last_analyze = stamp(r["analyzed"])
    return views


def kind_name(kind: Any) -> str:
    return {"r": "table", "v": "view", "m": "materialized view", "p": "partitioned table", "f": "foreign table"}.get(
        str(kind), f"relation {kind}")


def stamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if value.tzinfo else value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def cron_jobs(session: Session) -> list[dict[str, Any]]:
    """pg_cron jobs visible to this account (none when pg_cron is absent or not readable)."""
    present = session.rows("SELECT pg_catalog.to_regclass('cron.job') IS NOT NULL AS present")
    if not present or not present[0]["present"]:
        return []
    return session.rows("SELECT jobid, schedule, command, database, active FROM cron.job ORDER BY jobid")


def attach_jobs(views: list[MatView], jobs: list[dict[str, Any]]) -> None:
    for view in views:
        pattern = re.compile(r"refresh\s+materialized\s+view\s+(concurrently\s+)?(\"?" + re.escape(view.schema)
                             + r"\"?\.)?\"?" + re.escape(view.name) + r"\"?(\W|$)", re.IGNORECASE)
        for job in jobs:
            database = job.get("database") or view.database
            if database == view.database and pattern.search(str(job.get("command", ""))):
                state = "" if job.get("active", True) else " (inactive)"
                view.refresh_jobs.append(f"pg_cron job {job.get('jobid')}: \"{job.get('schedule')}\"{state}: "
                                         f"{' '.join(str(job.get('command', '')).split())[:200]}")


# --- Light profile --------------------------------------------------------------------------------------------------


def is_type(column: Column, prefixes: tuple[str, ...]) -> bool:
    return column.type.lower().startswith(prefixes)


def profile(session: Session, view: MatView, commit_timestamps: bool) -> None:
    """Row count, freshness, null rates, distinct counts, date ranges and small value lists, each step time-limited."""
    if not view.readable:
        view.notes.append("This account cannot SELECT from it: structure only.")
        return
    if not view.populated:
        view.notes.append("Not populated (never refreshed WITH DATA): structure only.")
        return
    target = f"{quote(view.schema)}.{quote(view.name)}"

    def attempt(label: str, sql: str) -> list[dict[str, Any]] | None:
        try:
            return session.rows(sql)
        except Exception as error:  # noqa: BLE001 - one slow or locked view must not stop the export
            view.notes.append(f"{label} skipped: {error_text(error)}")
            return None

    counted = attempt("Row count", f"SELECT count(*) AS n FROM {target}")
    if counted:
        view.rows, view.rows_exact = int(counted[0]["n"]), True
    else:
        view.rows = view.estimated_rows
    if commit_timestamps:
        latest = attempt("Freshness", f"SELECT max(pg_catalog.pg_xact_commit_timestamp(xmin)) AS t FROM {target}")
        if latest and latest[0]["t"]:
            view.freshness = f"rows last written {stamp(latest[0]['t'])} (commit timestamps)"
    columns = view.columns[:MAX_PROFILED_COLUMNS]
    if len(view.columns) > MAX_PROFILED_COLUMNS:
        view.notes.append(f"Only the first {MAX_PROFILED_COLUMNS} columns were profiled.")
    rows = view.rows or 0
    sample = ""
    if rows > SAMPLE_ROWS:
        sample = f" TABLESAMPLE SYSTEM ({min(100.0, 100.0 * SAMPLE_ROWS / rows):.6f})"
        view.sampled = True
    parts = []
    for index, column in enumerate(columns):
        name = quote(column.name)
        parts.append(f"count({name}) AS n{index}")
        if not is_type(column, NO_EQUALITY):
            parts.append(f"count(DISTINCT {name}) AS d{index}")
    if parts:
        stats = attempt("Column profile", f"SELECT count(*) AS total, {', '.join(parts)} FROM {target}{sample}")
        if stats:
            total = int(stats[0]["total"] or 0)
            for index, column in enumerate(columns):
                filled = int(stats[0].get(f"n{index}") or 0)
                column.nulls = (total - filled) / total if total else None
                if f"d{index}" in stats[0]:
                    column.distinct = int(stats[0][f"d{index}"] or 0)
    # Coverage, not business figures: dates, and periods kept as text or whole numbers (week 202640, year 2026).
    ranged = [c for c in columns if is_type(c, DATE_TYPES)
              or (is_type(c, (*TEXTUAL, *WHOLE_NUMBERS)) and DATE_NAMES.search(c.name.lower()))]
    if ranged:
        selects = ", ".join(f"min({quote(c.name)})::text AS lo{i}, max({quote(c.name)})::text AS hi{i}"
                            for i, c in enumerate(ranged))
        bounds = attempt("Date ranges", f"SELECT {selects} FROM {target}")
        if bounds:
            for index, column in enumerate(ranged):
                low, high = bounds[0].get(f"lo{index}"), bounds[0].get(f"hi{index}")
                if low is not None:
                    lexical = " (text order)" if is_type(column, TEXTUAL) else ""
                    column.range = f"{low} to {high}{lexical}"
    for column in columns:
        small = column.distinct is not None and 0 < column.distinct <= MAX_VALUES
        if not small or not is_type(column, TEXT_TYPES) or PERSONAL.search(column.name.lower()) or column.range:
            continue
        name = quote(column.name)
        listed = attempt(f"Values of {column.name}", f"SELECT {name}::text AS v, count(*) AS n FROM {target} "
                                                    f"WHERE {name} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {MAX_VALUES + 1}")
        if listed is not None:
            column.values = [mask_contacts(str(r["v"]))[:40] for r in listed[:MAX_VALUES]]
            column.more_values = len(listed) > MAX_VALUES


# --- Output ---------------------------------------------------------------------------------------------------------


def size(value: int) -> str:
    amount = float(value)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:,.0f} {unit}" if unit == "bytes" else f"{amount:,.1f} {unit}"
        amount /= 1024
    return f"{value} bytes"


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "unnamed"


def render(view: MatView, profiled: bool, exported: str) -> str:
    if view.rows is None:
        rows = f"about {view.estimated_rows:,} (planner estimate)"
    else:
        rows = f"{view.rows:,}" + ("" if view.rows_exact else " (planner estimate)")
    lines = ["---", "source: postgresql", f"database: {view.database}", f"object: {view.qualified}",
             "kind: materialized view", f"exported: {exported} (read-only catalog{'; light profile' if profiled else ''})",
             "---", "", f"# Materialized view {view.qualified} (database {view.database})", "",
             f"- Comment in the database: {view.comment or 'none'}",
             f"- Owner role: {view.owner or 'unknown'}",
             f"- Rows: {rows}; size {size(view.bytes)}; populated: {'yes' if view.populated else 'no'}",
             f"- Freshness: {view.freshness or 'not recorded by the server'}",
             f"- Statistics last updated: {view.last_analyze or 'unknown'}",
             "- Refresh schedule: " + ("; ".join(view.refresh_jobs) if view.refresh_jobs
                                       else "no pg_cron job found (refreshed by something else, or not visible)")]
    if view.sampled:
        lines.append(f"- Profile: null rates and distinct counts from a sample of about {SAMPLE_ROWS:,} rows; ranges and "
                     "value lists from all rows.")
    lines += [f"- Note: {note}" for note in view.notes]
    lines += ["", "## Reads from", ""] + ([f"- {item}" for item in view.reads_from] or ["- nothing found in the catalog"])
    lines += ["", "## Read by", ""] + ([f"- {item}" for item in view.used_by] or ["- no view or materialized view reads it"])
    if view.indexes:
        lines += ["", "## Indexes", ""] + [f"- `{index}`" for index in view.indexes]
    lines += ["", "## Columns", "", "| # | Column | Type | Nulls | Distinct | Range or values | Comment |", "|---|---|---|---|---|---|---|"]
    for column in view.columns:
        nulls = "" if column.nulls is None else f"{column.nulls:.0%}" if column.nulls >= 0.005 or column.nulls == 0 else "<1%"
        distinct = "" if column.distinct is None else f"{column.distinct:,}"
        shown = column.range or (", ".join(column.values) + (", ..." if column.more_values else "") if column.values else "")
        lines.append(f"| {column.position} | {cell(column.name)} | {cell(column.type)}{' not null' if column.not_null else ''} | "
                     f"{nulls} | {distinct} | {cell(shown)} | {cell(column.comment)} |")
    definition = view.definition if len(view.definition) <= 20_000 else view.definition[:20_000] + "\n-- (truncated)"
    lines += ["", "## Definition (how every column is computed)", "", "```sql", definition or "-- not readable", "```", ""]
    return "\n".join(lines)


def render_overview(database: str, facts: dict[str, Any], views: list[MatView], jobs_visible: bool, exported: str) -> str:
    lines = ["---", "source: postgresql", f"database: {database}", "object: overview", f"exported: {exported}", "---", "",
             f"# Materialized views in database {database}", "",
             f"- Server: PostgreSQL {facts.get('version', '?')}",
             f"- Commit timestamps tracked: {'yes' if facts.get('commit_timestamps') == 'on' else 'no'} "
             "(without them, freshness is unknown)",
             f"- pg_cron jobs visible: {'yes' if jobs_visible else 'no'}",
             f"- Materialized views this account can see: {len(views)}", "",
             "| Materialized view | Rows | Size | Freshness | Refresh | Reads from |", "|---|---|---|---|---|---|"]
    for view in views:
        rows = f"{view.rows:,}" if view.rows is not None else f"~{view.estimated_rows:,}"
        refresh = "pg_cron" if view.refresh_jobs else "-"
        lines.append(f"| {view.qualified} | {rows} | {size(view.bytes)} | {cell(view.freshness or '-')} | {refresh} | "
                     f"{cell(', '.join(view.reads_from[:6]) + (' ...' if len(view.reads_from) > 6 else '') or '-')} |")
    return "\n".join(lines) + "\n"


def check(settings: PgSettings, connector: Any = Pg8000Session) -> list[str]:
    session = connector(settings)
    try:
        facts = server_facts(session)
        lines = [f"PASS  connected: {settings.describe()}",
                 f"PASS  PostgreSQL {facts.get('version')} as {facts.get('user_name')}, database {facts.get('database')}",
                 f"{'PASS' if facts.get('read_only') == 'on' else 'FAIL'}  session is read-only "
                 f"(transaction_read_only {facts.get('read_only')})"]
        if any(facts.get(k) for k in ("superuser", "createrole", "createdb")):
            lines.append("WARN  this account has elevated rights; Wizard only reads, but a read-only account is safer")
        lines.append(f"INFO  commit timestamps tracked: {'yes' if facts.get('commit_timestamps') == 'on' else 'no (freshness unknown)'}")
        names = databases(session)
        lines.append(f"INFO  databases this account can connect to: {', '.join(names) or 'none'}")
        return lines
    finally:
        close = getattr(session, "close", None)
        if close:
            close()


def export(content: Path, settings: PgSettings, only: list[str] | None = None, schemas: list[str] | None = None,
           profiled: bool = True, connector: Any = Pg8000Session) -> dict[str, Any]:
    """Write inbox/postgres/<database>/<schema>.<view>.md (and 00-overview.md) plus inbox/_postgres/<database>.json."""
    exported = datetime.now(UTC).strftime("%Y-%m-%d")
    jobs: list[dict[str, Any]] = []
    first = connector(settings)
    try:
        names = only or databases(first)
        with contextlib.suppress(Exception):  # pg_cron is optional and often not readable
            jobs += cron_jobs(first)  # it lives in one database (usually postgres), which may not be exported
    finally:
        getattr(first, "close", lambda: None)()
    summary: dict[str, Any] = {"databases": {}, "skipped": {}}
    sessions = {}
    try:
        for name in names:
            try:
                sessions[name] = connector(settings, name)
            except ConversionError as error:
                summary["skipped"][name] = str(error)
                continue
            with contextlib.suppress(Exception):  # pg_cron is optional and often not readable
                jobs += [j for j in cron_jobs(sessions[name]) if j not in jobs]
        for name, session in sessions.items():
            facts = server_facts(session)
            views = read_catalog(session, name, schemas)
            attach_jobs(views, jobs)
            for view in views:
                if profiled:
                    profile(session, view, facts.get("commit_timestamps") == "on")
            folder = content / "inbox" / "postgres" / slug(name)
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("*.md"):
                old.unlink()
            for view in views:
                (folder / f"{slug(view.schema)}.{slug(view.name)}.md").write_text(render(view, profiled, exported), encoding="utf-8")
            if views:
                (folder / "00-overview.md").write_text(render_overview(name, facts, views, bool(jobs), exported), encoding="utf-8")
            machine = content / "inbox" / "_postgres"
            machine.mkdir(parents=True, exist_ok=True)
            (machine / f"{slug(name)}.json").write_text(json.dumps(
                {"database": name, "exported": exported, "profiled": profiled, "server": facts,
                 "materialized_views": [asdict(v) for v in views]}, default=str, indent=1), encoding="utf-8")
            summary["databases"][name] = {"materialized_views": len(views),
                                          "profiled": sum(1 for v in views if v.rows_exact),
                                          "notes": sum(len(v.notes) for v in views)}
    finally:
        for session in sessions.values():
            getattr(session, "close", lambda: None)()
    return summary
