"""Bounded, typed reads over the SYNTHETIC fixture files.

This is the Release A stand-in for a live adapter: same request shape (report id, prompt filters, optional grouping),
same result metadata (columns, units, as-of, warnings, digest). Live adapters implement the same `run` contract."""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path
from typing import Any

from .catalog import Catalog, Report

MAX_LIMIT = 500
FISCAL_YEAR_START_MONTH = 1  # SYNTHETIC calendar: fiscal quarters equal calendar quarters until the owner confirms (Step 01).


class SourceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Filter:
    field: str
    values: list[str]


@dataclass(frozen=True)
class Sort:
    field: str
    direction: str = "asc"


@dataclass
class ResultSet:
    columns: list[dict[str, Any]]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool
    as_of: str | None
    digest: str
    warnings: list[str] = field(default_factory=list)
    access_note: str | None = None


def month_to_quarter(month: str) -> str:
    year, number = int(month[:4]), int(month[5:7])
    shifted = (number - FISCAL_YEAR_START_MONTH) % 12
    fiscal_year = year if number >= FISCAL_YEAR_START_MONTH else year - 1
    return f"{fiscal_year}-Q{shifted // 3 + 1}"


def quarter_months(quarter: str) -> list[str]:
    year, q = int(quarter[:4]), int(quarter[-1])
    months = []
    for offset in range(3):
        index = FISCAL_YEAR_START_MONTH - 1 + (q - 1) * 3 + offset
        months.append(f"{year + index // 12}-{index % 12 + 1:02d}")
    return months


class FixtureSource:
    def __init__(self, catalog: Catalog, root: Path):
        self.catalog = catalog
        self.root = root
        self._rows: dict[str, list[dict[str, Any]]] = {}

    def invalidate(self) -> None:
        self._rows.clear()

    def _load(self, report: Report) -> list[dict[str, Any]]:
        if report.file is None:
            raise SourceError("navigation_only", "This report is listed for navigation only; its rows cannot be read.")
        if report.id not in self._rows:
            path = self.root / report.file
            if not path.exists():
                raise SourceError("source_unavailable", f"The source file for {report.name} is unavailable.")
            with path.open(encoding="utf-8", newline="") as handle:
                self._rows[report.id] = [self._typed(report, row) for row in csv.DictReader(handle)]
        return self._rows[report.id]

    @staticmethod
    def _typed(report: Report, row: dict[str, str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, raw in row.items():
            column = report.column(key)
            kind = column.type if column else "string"
            if raw == "":
                out[key] = None
            elif kind == "integer":
                out[key] = int(raw)
            elif kind in ("number", "percent", "currency"):
                value = float(raw)
                out[key] = int(value) if value.is_integer() and kind == "currency" else value
            else:
                out[key] = raw
        return out

    def dimensions(self, report: Report) -> list[dict[str, Any]]:
        """Report dimensions plus a derived fiscal_quarter on monthly reports."""
        dims = [d.model_dump() for d in report.dimensions]
        keys = {d["key"] for d in dims}
        if "month" in keys and "fiscal_quarter" not in keys:
            dims.append({"key": "fiscal_quarter", "label": "Fiscal quarter (derived from month)", "type": "quarter",
                         "role": "period", "values_hint": [], "derived": True})
        return dims

    def run(self, report: Report, *, filters: list[Filter], group_by: list[str] | None, measures: list[str] | None,
            sort: list[Sort] | None, limit: int, allowed_markets: set[str] | None) -> ResultSet:
        if report.row_access != "ROWS":
            raise SourceError("navigation_only", f"'{report.name}' is navigation only: Wizard cannot read its rows. "
                                                 "Open it in the source system instead.")
        rows = [dict(r) for r in self._load(report)]
        dims = self.dimensions(report)
        dim_keys = [d["key"] for d in dims]
        derived_quarter = any(d.get("derived") for d in dims)
        if derived_quarter:
            for row in rows:
                row["fiscal_quarter"] = month_to_quarter(row["month"])
        warnings: list[str] = []
        access_note = None

        market_dim = next((d["key"] for d in dims if d.get("role") == "market"), None)
        if allowed_markets is not None and market_dim:
            rows = [r for r in rows if r.get(market_dim) in allowed_markets]
            access_note = f"Rows are limited to the markets you are entitled to: {', '.join(sorted(allowed_markets))}."

        for flt in filters:
            if flt.field not in dim_keys:
                raise SourceError("invalid_filter", f"'{flt.field}' is not a filterable dimension of this report. "
                                                    f"Use one of: {', '.join(dim_keys)}.")
            wanted = {v.strip().casefold() for v in flt.values}
            denied: list[str] = []
            if allowed_markets is not None and flt.field == market_dim:
                denied = sorted(v for v in flt.values if v.strip().upper() not in allowed_markets)
                if denied:
                    access_note = (f"You are not entitled to market(s) {', '.join(denied)} in this source; "
                                   "those rows were not returned.")
            before = rows
            rows = [r for r in rows if str(r.get(flt.field) or "").casefold() in wanted]
            dim = next(d for d in dims if d["key"] == flt.field)
            if dim.get("role") in ("market", "period", "model"):
                present = {str(r.get(flt.field) or "").casefold() for r in before}
                missing = [v for v in flt.values if v.strip().casefold() not in present and v not in denied]
                if missing:
                    warnings.append(f"No rows exist for {flt.field} = {', '.join(missing)} in this report. "
                                    "Missing rows mean the source has no data for it, not a value of zero.")

        measure_keys = measures or report.measure_keys
        unknown = [m for m in measure_keys if m not in report.measure_keys]
        if unknown:
            raise SourceError("invalid_measure", f"Unknown measure(s) {', '.join(unknown)}. "
                                                 f"Available: {', '.join(report.measure_keys)}.")
        if group_by is not None:
            bad = [g for g in group_by if g not in dim_keys]
            if bad:
                raise SourceError("invalid_group_by", f"Cannot group by {', '.join(bad)}. Dimensions: {', '.join(dim_keys)}.")
            out_rows, agg_warnings = self._aggregate(report, rows, group_by, measure_keys)
            warnings.extend(agg_warnings)
            column_keys = [*group_by, *measure_keys]
        else:
            base = [k for k in report.dimension_keys] + [a.key for a in report.attributes]
            if derived_quarter and "fiscal_quarter" not in base:
                base.insert(base.index("month") + 1, "fiscal_quarter")
            column_keys = [*base, *measure_keys]
            out_rows = [{k: r.get(k) for k in column_keys} for r in rows]

        for spec in sort or []:
            if spec.field not in column_keys:
                raise SourceError("invalid_sort", f"Cannot sort by '{spec.field}'; it is not in the result columns.")
        for spec in reversed(sort or []):
            with_value = [r for r in out_rows if r.get(spec.field) is not None]
            without_value = [r for r in out_rows if r.get(spec.field) is None]
            with_value.sort(key=itemgetter(spec.field), reverse=spec.direction == "desc")
            out_rows = with_value + without_value
        if not sort:
            order = [k for k in column_keys if k in dim_keys or k in report.grain]
            out_rows.sort(key=lambda r: tuple(str(r.get(k) or "") for k in order))

        limit = max(1, min(limit, MAX_LIMIT))
        matrix = [[r.get(k) for k in column_keys] for r in out_rows]
        digest = hashlib.sha256(json.dumps([column_keys, matrix], separators=(",", ":"), default=str).encode()).hexdigest()
        columns = []
        for key in column_keys:
            column = report.column(key)
            meta = column.model_dump() if column else next((d for d in dims if d["key"] == key), {"key": key, "label": key, "type": "string"})
            columns.append({k: meta.get(k) for k in ("key", "label", "type", "unit", "aggregation") if meta.get(k) is not None})
        return ResultSet(columns=columns, rows=matrix[:limit], total_rows=len(matrix), truncated=len(matrix) > limit,
                         as_of=report.as_of, digest=digest, warnings=warnings, access_note=access_note)

    def _aggregate(self, report: Report, rows: list[dict[str, Any]], group_by: list[str],
                   measure_keys: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        groups: dict[tuple, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(tuple(row.get(k) for k in group_by), []).append(row)
        warnings: set[str] = set()
        period_key = "month" if "month" in report.dimension_keys else "fiscal_quarter"
        out = []
        for key, members in groups.items():
            item = dict(zip(group_by, key, strict=True))
            for measure_key in measure_keys:
                measure = next(m for m in report.measures if m.key == measure_key)
                values = [m.get(measure_key) for m in members]
                if measure.aggregation == "sum":
                    present = [v for v in values if v is not None]
                    item[measure_key] = sum(present) if present else None
                elif measure.aggregation == "sum_same_currency":
                    currencies = {m.get("local_currency") for m in members}
                    if len(currencies) > 1:
                        item[measure_key] = None
                        warnings.add(f"{measure.label} mixes currencies in a group and was not added up; "
                                     "group by local_currency or use the USD measure.")
                    else:
                        item[measure_key] = sum(v for v in values if v is not None)
                elif measure.aggregation == "last":
                    latest = max(str(m.get(period_key)) for m in members)
                    item[measure_key] = sum(m.get(measure_key) or 0 for m in members if str(m.get(period_key)) == latest)
                    if period_key not in group_by:
                        warnings.add(f"{measure.label} is a period-end balance: each group shows the value at its latest "
                                     f"{period_key}, not a sum over time.")
                else:
                    if len(members) == 1:
                        item[measure_key] = values[0]
                    else:
                        item[measure_key] = None
                        warnings.add(f"{measure.label} is a rate or share and cannot be aggregated; group by the report "
                                     f"grain ({', '.join(report.grain)}) or compute it from its components.")
            out.append(item)
        return out, sorted(warnings)
