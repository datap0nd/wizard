"""Live, read-only PostgreSQL source: runs a report contract's query (prompt filters, optional grouping, each measure's
aggregation rule) against the database object the report names (`relation`), with the same request and result shape
as the fixture source, so search, schema, evidence and Check my data work unchanged.

No free SQL: every statement is built here from the contract (quoted identifiers) and the validated request (bound
parameters). The session is read-only with a 30 s statement timeout and a 2 s lock timeout; results are capped at 500
rows; market rights are applied in the WHERE clause. Figures are LIVE_UNVERIFIED until the report's parity is signed
(one query compared with a number the owner trusts), then LIVE_VERIFIED.

Identifiers in the SQL come only from the approved contract and always pass through quote(); request values are always
bound parameters (:name). Hence ruff's S608 is waived for this file in pyproject.toml."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from .catalog import Report
from .fixture_source import MAX_LIMIT, Filter, ResultSet, Sort, SourceError
from .pg import Pg8000Session, PgError, PgSettings, Session, error_text, quote

STATEMENT_TIMEOUT = "30s"
FRESHNESS_TTL_S = 900
NUMERIC = ("smallint", "integer", "bigint", "numeric", "decimal", "real", "double precision")


def connect_default(settings: PgSettings, database: str) -> Session:
    return Pg8000Session(settings, database, STATEMENT_TIMEOUT, "2s", "wizard")


def plain(value: Any) -> Any:
    """Database values as JSON-friendly Python: Decimal to int/float, dates to ISO text."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() and abs(value) < 10**15 else float(value)
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def missing(relation: str) -> str:
    return (f"{relation} does not exist on the server or this account cannot see it. Re-run the PostgreSQL export and "
            "check the report entry.")


def sqlstate(error: BaseException) -> str | None:
    args = getattr(error, "args", ())
    return args[0].get("C") if args and isinstance(args[0], dict) else None


class PostgresSource:
    def __init__(self, settings: PgSettings | None, connect: Callable[[PgSettings, str], Session] = connect_default):
        self.settings = settings
        self.connect = connect
        self._types: dict[str, dict[str, str]] = {}
        self._fresh: dict[str, tuple[float, str | None]] = {}

    def invalidate(self) -> None:
        self._types.clear()
        self._fresh.clear()

    def dimensions(self, report: Report) -> list[dict[str, Any]]:
        return [d.model_dump(exclude={"column"}) for d in report.dimensions]

    # -- helpers --------------------------------------------------------------------------------------------------------

    @staticmethod
    def column(report: Report, key: str) -> str:
        found = report.column(key)
        return quote(found.column or key) if found else quote(key)

    def _column_types(self, session: Session, key: str, relation: str) -> dict[str, str]:
        if key not in self._types:
            rows = session.rows("SELECT a.attname AS name, pg_catalog.format_type(a.atttypid, a.atttypmod) AS type "
                                "FROM pg_catalog.pg_attribute a WHERE a.attrelid = pg_catalog.to_regclass(:rel) "
                                "AND a.attnum > 0 AND NOT a.attisdropped", rel=relation)
            if not rows:
                raise SourceError("source_unavailable", missing(relation))
            self._types[key] = {r["name"]: r["type"] for r in rows}
        return self._types[key]

    def _number(self, report: Report, key: str, types: dict[str, str]) -> str:
        found = report.column(key)
        name = found.column or key if found else key
        kind = types.get(name, "")
        if kind.startswith(NUMERIC):
            return quote(name)
        if kind == "money":
            return f"{quote(name)}::numeric"
        return f"CAST(NULLIF(btrim({quote(name)}::text), '') AS numeric)"  # Metronome loads many columns as text

    def _freshness(self, session: Session, key: str, relation: str) -> str | None:
        cached = self._fresh.get(key)
        if cached and time.monotonic() - cached[0] < FRESHNESS_TTL_S:
            return cached[1]
        stamp: str | None = None
        try:
            tracked = session.rows("SELECT current_setting('track_commit_timestamp') = 'on' AS tracked")[0]["tracked"]
            if tracked:
                session.rows("SET statement_timeout = '5s'")
                value = session.rows(f"SELECT max(pg_catalog.pg_xact_commit_timestamp(xmin)) AS t FROM {relation}")[0]["t"]
                session.rows(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
                stamp = plain(value) if value is not None else None
        except Exception:  # noqa: BLE001 - freshness is best effort; a slow scan must not fail the query
            stamp = None
        self._fresh[key] = (time.monotonic(), stamp)
        return stamp

    # -- run ------------------------------------------------------------------------------------------------------------

    def run(self, report: Report, *, filters: list[Filter], group_by: list[str] | None, measures: list[str] | None,
            sort: list[Sort] | None, limit: int, allowed_markets: set[str] | None) -> ResultSet:
        if report.row_access != "ROWS" or report.relation is None:
            raise SourceError("navigation_only", f"'{report.name}' is navigation only: Wizard cannot read its rows. "
                                                 "Open it in the source system instead.")
        if self.settings is None:
            raise SourceError("source_unavailable", "PostgreSQL connection settings are missing on this Wizard server "
                                                    "(WIZARD_PG_* in .env). Ask the person who runs Wizard to add them.")
        dim_keys = report.dimension_keys
        for flt in filters:
            if flt.field not in dim_keys:
                raise SourceError("invalid_filter", f"'{flt.field}' is not a filterable dimension of this report. "
                                                    f"Use one of: {', '.join(dim_keys)}.")
        measure_keys = measures or report.measure_keys
        unknown = [m for m in measure_keys if m not in report.measure_keys]
        if unknown:
            raise SourceError("invalid_measure", f"Unknown measure(s) {', '.join(unknown)}. "
                                                 f"Available: {', '.join(report.measure_keys)}.")
        if group_by is not None:
            bad = [g for g in group_by if g not in dim_keys]
            if bad:
                raise SourceError("invalid_group_by", f"Cannot group by {', '.join(bad)}. Dimensions: {', '.join(dim_keys)}.")
            column_keys = [*group_by, *measure_keys]
        else:
            column_keys = [*dim_keys, *[a.key for a in report.attributes], *measure_keys]
        for spec in sort or []:
            if spec.field not in column_keys:
                raise SourceError("invalid_sort", f"Cannot sort by '{spec.field}'; it is not in the result columns.")
        limit = max(1, min(limit, MAX_LIMIT))
        relation = f"{quote(report.relation.namespace)}.{quote(report.relation.name)}"
        key = f"{report.relation.database}:{relation}"
        try:
            session = self.connect(self.settings, report.relation.database)
        except PgError as error:
            raise SourceError("source_unavailable", f"PostgreSQL is not reachable: {error}") from None
        try:
            return self._run(session, key, report, relation, filters, group_by, measure_keys, column_keys, sort, limit,
                             allowed_markets)
        except SourceError:
            raise
        except Exception as error:  # noqa: BLE001 - database errors become one readable tool error
            if sqlstate(error) in ("42P01", "42703"):  # the view or a column went away since Wizard started
                self._types.pop(key, None)
                raise SourceError("source_unavailable", f"{missing(relation)} ({error_text(error)})") from None
            raise SourceError("source_error", f"PostgreSQL could not run this query: {error_text(error)}") from None
        finally:
            getattr(session, "close", lambda: None)()

    def _run(self, session: Session, key: str, report: Report, relation: str, filters: list[Filter],
             group_by: list[str] | None, measure_keys: list[str], column_keys: list[str], sort: list[Sort] | None,
             limit: int, allowed_markets: set[str] | None) -> ResultSet:
        types = self._column_types(session, key, relation)
        where: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        warnings: list[str] = []
        access_note = None
        market = next((d for d in report.dimensions if d.role == "market"), None)
        if allowed_markets is not None and market is not None:
            where.append(f"upper(btrim({self.column(report, market.key)}::text)) = ANY(:allowed_markets)")
            params["allowed_markets"] = sorted(m.upper() for m in allowed_markets)
            access_note = f"Rows are limited to the markets you are entitled to: {', '.join(sorted(allowed_markets))}."
        for index, flt in enumerate(filters):
            wanted = [v.strip().casefold() for v in flt.values]
            where.append(f"lower(btrim({self.column(report, flt.field)}::text)) = ANY(:f{index})")
            params[f"f{index}"] = wanted
            dimension = next(d for d in report.dimensions if d.key == flt.field)
            denied: list[str] = []
            if allowed_markets is not None and market is not None and flt.field == market.key:
                denied = sorted(v for v in flt.values if v.strip().upper() not in allowed_markets)
                if denied:
                    access_note = (f"You are not entitled to market(s) {', '.join(denied)} in this source; those rows were "
                                   "not returned.")
            if dimension.role in ("market", "period", "model"):
                expression = f"lower(btrim({self.column(report, flt.field)}::text))"
                present = {r["v"] for r in session.rows(f"SELECT DISTINCT {expression} AS v FROM {relation} "
                                                        f"WHERE {expression} = ANY(:wanted)", wanted=wanted)}
                missing = [v for v in flt.values if v.strip().casefold() not in present and v not in denied]
                if missing:
                    warnings.append(f"No rows exist for {flt.field} = {', '.join(missing)} in this report. Missing rows "
                                    "mean the source has no data for it, not a value of zero.")
        condition = f" WHERE {' AND '.join(where)}" if where else ""
        alias = {key: f"c{i}" for i, key in enumerate(column_keys)}

        def order_by(default: list[str]) -> str:
            specs = [(s.field, s.direction) for s in sort or []] or [(k, "asc") for k in default]
            return " ORDER BY " + ", ".join(f"{alias[k]} {d.upper()} NULLS LAST" for k, d in specs) if specs else ""

        if group_by is None:
            selects = [f"{self.column(report, k)} AS {alias[k]}" for k in column_keys if k not in measure_keys]
            selects += [f"{self._number(report, k, types)} AS {alias[k]}" for k in measure_keys]
            default = [k for k in column_keys if k in report.dimension_keys or k in report.grain]
            sql = (f"SELECT {', '.join(selects)}, count(*) OVER () AS __total FROM {relation}{condition}"
                   f"{order_by(default)} LIMIT :limit")
            rows = session.rows(sql, **params)
            single_flags: list[dict[str, Any]] = []
        else:
            sql, notes = self._grouped_sql(report, relation, condition, group_by, measure_keys, types, alias)
            warnings += notes
            sql += order_by(group_by) + " LIMIT :limit"
            rows = session.rows(sql, **params)
            if not group_by and rows and int(rows[0].get("__n") or 0) == 0:
                rows = []  # an aggregate over no rows is no row, as in the fixture engine
            single_flags = rows
            measures_by_key = {m.key: m for m in report.measures}
            for key in measure_keys:
                measure = measures_by_key[key]
                if measure.aggregation == "none" and any(int(r.get("__n") or 0) > 1 for r in single_flags):
                    warnings.append(f"{measure.label} is a rate or share and cannot be aggregated; group by the report "
                                    f"grain ({', '.join(report.grain)}) or compute it from its components.")
                if measure.aggregation == "sum_same_currency" and any(int(r.get("__cur") or 0) > 1 for r in single_flags):
                    warnings.append(f"{measure.label} mixes currencies in a group and was not added up; group by the "
                                    "currency or use a single-currency measure.")
                if measure.aggregation == "last":
                    period = next(d.key for d in report.dimensions if d.role == "period")
                    if period not in group_by:
                        warnings.append(f"{measure.label} is a period-end balance: each group shows the value at its "
                                        f"latest {period}, not a sum over time.")
        total = int(rows[0]["__total"]) if rows else 0
        matrix = [[plain(r.get(alias[k])) for k in column_keys] for r in rows]
        digest = hashlib.sha256(json.dumps([column_keys, matrix], separators=(",", ":"), default=str).encode()).hexdigest()
        columns = []
        for key in column_keys:
            found = report.column(key)
            meta = found.model_dump(exclude={"column"}) if found else {"key": key, "label": key, "type": "string"}
            columns.append({k: meta.get(k) for k in ("key", "label", "type", "unit", "aggregation") if meta.get(k) is not None})
        as_of = self._freshness(session, key, relation)
        if as_of is None:
            warnings.append("The server does not record when these rows were last written, so their freshness is unknown.")
        verified = report.parity is not None
        return ResultSet(columns=columns, rows=matrix, total_rows=total, truncated=total > len(matrix), as_of=as_of,
                         digest=digest, warnings=list(dict.fromkeys(warnings)), access_note=access_note,
                         data_mode="LIVE_VERIFIED" if verified else "LIVE_UNVERIFIED",
                         verification=(f"checked {report.parity.checked} by {report.parity.by} against "
                                       f"{report.parity.reference}" if report.parity else
                                       "live from PostgreSQL, not yet checked against a report the owner trusts"))

    def _grouped_sql(self, report: Report, relation: str, condition: str, group_by: list[str], measure_keys: list[str],
                     types: dict[str, str], alias: dict[str, str]) -> tuple[str, list[str]]:
        measures = {m.key: m for m in report.measures}
        rules = {measures[k].aggregation for k in measure_keys}
        period = next((d.key for d in report.dimensions if d.role == "period"), None)
        currency = next((d.key for d in report.dimensions if "currency" in d.key), None)
        base = [f"{self.column(report, g)} AS {alias[g]}" for g in group_by]
        base += [f"{self._number(report, k, types)} AS {alias[k]}" for k in measure_keys]
        if "last" in rules:
            if period is None:
                raise SourceError("invalid_report", "This report has a period-end balance but no period dimension.")
            base.append(f"{self.column(report, period)} AS __p")
        if "sum_same_currency" in rules and currency:
            base.append(f"{self.column(report, currency)} AS __c")
        partition = ", ".join(alias[g] for g in group_by)
        source = f"(SELECT {', '.join(base)} FROM {relation}{condition}) AS base"
        if "last" in rules:
            source = (f"(SELECT base.*, max(__p) OVER ({'PARTITION BY ' + partition if partition else ''}) AS __latest "
                      f"FROM {source}) AS ranked")
        selects = [alias[g] for g in group_by]
        for key in measure_keys:
            rule, name = measures[key].aggregation, alias[key]
            if rule == "sum":
                selects.append(f"sum({name}) AS {name}")
            elif rule == "sum_same_currency":
                selects.append(f"CASE WHEN count(DISTINCT __c) > 1 THEN NULL ELSE sum({name}) END AS {name}"
                               if currency else f"sum({name}) AS {name}")
            elif rule == "last":
                selects.append(f"sum({name}) FILTER (WHERE __p = __latest) AS {name}")
            else:
                selects.append(f"CASE WHEN count(*) = 1 THEN max({name}) END AS {name}")
        selects.append("count(*) AS __n")
        if "sum_same_currency" in rules and currency:
            selects.append("count(DISTINCT __c) AS __cur")
        selects.append("count(*) OVER () AS __total")
        grouping = f" GROUP BY {partition}" if partition else ""
        return f"SELECT {', '.join(selects)} FROM {source}{grouping}", []
