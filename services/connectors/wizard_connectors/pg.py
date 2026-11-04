"""Read-only PostgreSQL sessions for the live PostgreSQL query tool (postgres_query.py) and the Brain page's news.

Settings: WIZARD_PG_HOST / _PORT / _DATABASE / _USER / _PASSWORD / _SSLMODE (Wizard's .env), else the standard
PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD / PGSSLMODE of a read-only account (data_governance's scanner).
WIZARD_PG_SCHEMAS lists the schemas Gemini's queries may read (postgres_query.py refuses any other); empty, every schema
the account can read. The password is never printed or written. Every session is read-only, with a statement timeout and a short lock
timeout. pg8000 is pure Python, so Application Control has no driver DLL to block (psycopg2's was blocked)."""
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from typing import Any, Protocol

SSL_MODES = ("disable", "prefer", "require", "verify-ca", "verify-full")
# A schema as written in WIZARD_PG_SCHEMAS: a plain name (folded to lower case, as PostgreSQL folds it) or a
# double-quoted one (kept as written).
PLAIN_SCHEMA = re.compile(r"[A-Za-z_][A-Za-z0-9_$]{0,62}")
QUOTED_SCHEMA = re.compile(r'"([^"]{1,63})"')


class PgError(Exception):
    """A connection or settings problem, in words a person can act on."""


class Session(Protocol):
    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class PgSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    sslmode: str
    source: str  # ".env (WIZARD_PG_*)" or "environment (PG*)"
    # The schemas Gemini's queries may read (WIZARD_PG_SCHEMAS); empty: no limit beyond the account's own grants.
    schemas: tuple[str, ...] = ()

    def describe(self) -> str:
        limit = f", schemas {', '.join(self.schemas)} only" if self.schemas else ""
        return f"{self.user}@{self.host}:{self.port}/{self.database} (sslmode {self.sslmode}{limit}, from {self.source})"


def settings_from(values: dict[str, str], environ: dict[str, str]) -> PgSettings | None:
    """WIZARD_PG_* from `values` (or the environment), else PG* from the environment; None when neither names a host
    and a user. Raises PgError for a malformed port or sslmode."""
    if values.get("WIZARD_PG_HOST") or environ.get("WIZARD_PG_HOST"):
        def get(key: str, default: str = "") -> str:
            return values.get(f"WIZARD_PG_{key}") or environ.get(f"WIZARD_PG_{key}") or default
        source = ".env (WIZARD_PG_*)"
    else:
        def get(key: str, default: str = "") -> str:
            return environ.get(f"PG{key}", "") or default  # PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE
        source = "environment (PG*)"
    host, user = get("HOST"), get("USER")
    if not host or not user:
        return None
    try:
        port = int(get("PORT", "5432"))
    except ValueError:
        raise PgError("the PostgreSQL port must be a number") from None
    sslmode = get("SSLMODE", "prefer").lower()
    if sslmode not in SSL_MODES:
        raise PgError("the PostgreSQL sslmode must be disable, prefer, require, verify-ca or verify-full")
    schemas = schema_list(values.get("WIZARD_PG_SCHEMAS") or environ.get("WIZARD_PG_SCHEMAS") or "")
    return PgSettings(host, port, get("DATABASE", "postgres"), user, get("PASSWORD"), sslmode, source, schemas)


def schema_list(text: str, what: str = "schemas Wizard may query", kind: str = "schema") -> tuple[str, ...]:
    """WIZARD_PG_SCHEMAS (or NERP's views, WIZARD_NERP_VIEWS) as the names PostgreSQL stores: comma-separated, a plain
    name in lower case (as PostgreSQL folds it), a double-quoted one as written. Raises PgError for anything else."""
    found: list[str] = []
    for raw in text.split(","):
        item = raw.strip()
        if not item:
            continue
        quoted = QUOTED_SCHEMA.fullmatch(item)
        if quoted:
            name = quoted.group(1)
        elif PLAIN_SCHEMA.fullmatch(item):
            name = item.lower()
        else:
            raise PgError(f"the {what} must be {kind} names separated by commas; {item!r} is not one "
                          '(write a name with capitals or symbols in double quotes, e.g. "Sales Data")')
        if name not in found:
            found.append(name)
    return tuple(found)


def error_text(error: BaseException) -> str:
    args = getattr(error, "args", ())
    if args and isinstance(args[0], dict):  # pg8000 DatabaseError: {'S': 'ERROR', 'C': '57014', 'M': 'canceling ...'}
        detail = args[0]
        hint = f". Hint: {detail['H']}" if detail.get("H") else ""  # e.g. 'Perhaps you meant to reference the column ...'
        return f"{detail.get('M', 'database error')} (SQLSTATE {detail.get('C', '?')}){hint}"
    return " ".join(str(error).split())[:300] or type(error).__name__


def sqlstate(error: BaseException) -> str | None:
    args = getattr(error, "args", ())
    return str(args[0].get("C")) if args and isinstance(args[0], dict) and args[0].get("C") else None


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


class Pg8000Session:
    """A read-only pg8000 session; rows come back as dicts. Parameters use pg8000's :name placeholders."""

    def __init__(self, settings: PgSettings, database: str | None = None, statement_timeout: str = "60s",
                 lock_timeout: str = "2s", application_name: str = "wizard"):
        try:
            import pg8000.native
        except ImportError as error:
            raise PgError(f"the PostgreSQL driver pg8000 is not installed ({error}); run setup.ps1 again") from None
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
                ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # the Windows certificate store
            except ImportError:
                ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = settings.sslmode == "verify-full"
        try:
            self.connection = pg8000.native.Connection(
                settings.user, host=settings.host, port=settings.port, database=database or settings.database,
                password=settings.password or None, ssl_context=ssl_context, timeout=30, application_name=application_name)
        except Exception as error:  # noqa: BLE001 - driver errors become one readable line
            raise PgError(f"could not connect to {settings.host}:{settings.port}/{database or settings.database} as "
                          f"{settings.user}: {error_text(error)}") from None
        for statement in ("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY",
                          f"SET statement_timeout = {literal(statement_timeout)}", f"SET lock_timeout = {literal(lock_timeout)}"):
            self.connection.run(statement)

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        result = self.connection.run(sql, **params) or []
        names = [c["name"] for c in self.connection.columns or []]
        return [dict(zip(names, row, strict=False)) for row in result]

    def query(self, sql: str) -> tuple[list[dict[str, Any]], list[list[Any]]]:
        """One statement through the extended protocol, which PostgreSQL refuses to run with a second statement in it,
        sent exactly as written (no :name placeholder parsing). Returns the column descriptions and the rows."""
        context = self.connection.execute_unnamed(sql)
        return list(context.columns or []), [list(row) for row in context.rows or []]

    def close(self) -> None:
        with contextlib.suppress(Exception):  # closing a broken connection is not an error worth reporting
            self.connection.close()
