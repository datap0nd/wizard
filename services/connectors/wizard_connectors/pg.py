"""Read-only PostgreSQL sessions shared by the documentation export (wizard_documents.postgres) and the live
PostgreSQL query tool (postgres_query.py).

Settings: WIZARD_PG_HOST / _PORT / _DATABASE / _USER / _PASSWORD / _SSLMODE (Wizard's .env), else the standard
PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD / PGSSLMODE of a read-only account (data_governance's scanner).
The password is never printed or written. Every session is read-only, with a statement timeout and a short lock
timeout. pg8000 is pure Python, so Application Control has no driver DLL to block (psycopg2's was blocked)."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

SSL_MODES = ("disable", "prefer", "require", "verify-ca", "verify-full")


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

    def describe(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.database} (sslmode {self.sslmode}, from {self.source})"


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
    return PgSettings(host, port, get("DATABASE", "postgres"), user, get("PASSWORD"), sslmode, source)


MISSING = ("no PostgreSQL connection settings: add WIZARD_PG_HOST, WIZARD_PG_PORT, WIZARD_PG_DATABASE, WIZARD_PG_USER "
           "and WIZARD_PG_PASSWORD (a read-only account) to Wizard's .env, or set the PGHOST/PGUSER/PGPASSWORD variables "
           "of the read-only scanner account")


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
