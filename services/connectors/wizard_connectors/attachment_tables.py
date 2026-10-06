"""Query the full tables of an attached spreadsheet or CSV (written by the converter: tables.json + tables/<n>.csv):
filter, group and total every row, bounded like a report query. The figures are the user's (USER_PROVIDED)."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

MAX_RESULT_ROWS = 500
NOT_ADDITIVE = re.compile(r"(^|_)(pct|percent|share|rate|ratio|avg|average|mean|price|asp|index|idx|growth)(_|$)")


class TableError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def index(folder: Path) -> list[dict[str, Any]]:
    path = folder / "converted" / "tables.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def load(folder: Path, entry: dict[str, Any]) -> list[dict[str, Any]]:
    kinds = {c["key"]: c["type"] for c in entry["columns"]}
    rows = []
    with (folder / "converted" / entry["file"]).open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            rows.append({k: None if v == "" else float(v) if kinds.get(k) == "number" else v for k, v in raw.items()})
    return rows


def choose(tables: list[dict[str, Any]], sheet: str | None) -> dict[str, Any]:
    if not tables:
        raise TableError("no_table", "This file has no table to query (only spreadsheets and CSV files do). Read it with "
                                     "wizard_read_attachment instead.")
    if sheet is None:
        if len(tables) > 1:
            raise TableError("choose_sheet", "This file has several sheets; name one: "
                                             + ", ".join(f"{t['sheet']} ({t['rows']:,} rows)" for t in tables))
        return tables[0]
    found = next((t for t in tables if t["sheet"].casefold() == sheet.casefold()), None)
    if found is None:
        raise TableError("unknown_sheet", f"No sheet '{sheet}'. Sheets: {', '.join(t['sheet'] for t in tables)}")
    return found


def _matches(value: Any, values: list[str] | None, low: str | None, high: str | None, number: bool) -> bool:
    if values is not None and str(_shown(value)).casefold() not in {v.strip().casefold() for v in values}:
        return False
    if low is None and high is None:
        return True
    if value is None:
        return False
    if number:
        try:
            return (low is None or value >= float(low)) and (high is None or value <= float(high))
        except ValueError:
            raise TableError("invalid_filter", "from/to must be numbers for a number column") from None
    text = str(value)
    return (low is None or text >= low) and (high is None or text <= high)


def _shown(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def query(entry: dict[str, Any], rows: list[dict[str, Any]], filters: list[dict[str, Any]], group_by: list[str],
          measures: list[dict[str, str]], sort: list[dict[str, str]], limit: int) -> dict[str, Any]:
    columns = {c["key"]: c for c in entry["columns"]}
    for name in [f["column"] for f in filters] + group_by + [m["column"] for m in measures if m["aggregate"] != "count"]:
        if name not in columns:
            raise TableError("unknown_column", f"No column '{name}'. Columns: {', '.join(columns)}")
    warnings: list[str] = []
    for flt in filters:
        number = columns[flt["column"]]["type"] == "number"
        rows = [r for r in rows if _matches(r.get(flt["column"]), flt.get("values"), flt.get("from"), flt.get("to"), number)]
    for measure in measures:
        name = measure["column"]
        if measure["aggregate"] in ("sum", "avg", "min", "max") and columns[name]["type"] != "number":
            raise TableError("invalid_measure", f"'{name}' is not a number column; use count, or group by it instead.")
        if measure["aggregate"] == "sum" and NOT_ADDITIVE.search(name):
            warnings.append(f"{name} looks like a rate, share or price: a sum of it is usually meaningless.")
        skipped = entry.get("non_numeric", {}).get(name)
        if skipped:
            warnings.append(f"{name} has {skipped} cell(s) that are not numbers; they are left out of its figures.")
    if group_by or measures:
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(tuple(_shown(row.get(k)) for k in group_by), []).append(row)
        out_keys = [*group_by, *[f"{m['aggregate']}_{m['column']}" for m in measures]]
        out = []
        for key, members in groups.items():
            item = dict(zip(group_by, key, strict=True))
            for measure in measures:
                values: list[float] = [float(r[measure["column"]]) for r in members
                                       if isinstance(r.get(measure["column"]), int | float)]
                aggregate = measure["aggregate"]
                result: Any
                if aggregate == "count":
                    result = len(members)
                elif not values:
                    result = None
                elif aggregate == "sum":
                    result = sum(values)
                elif aggregate == "avg":
                    result = sum(values) / len(values)
                elif aggregate == "min":
                    result = min(values)
                else:
                    result = max(values)
                item[f"{aggregate}_{measure['column']}"] = _shown(round(result, 6)) if isinstance(result, float) else result
            out.append(item)
        meta = [{**columns[k], "type": columns[k]["type"]} for k in group_by] + [
            {"key": f"{m['aggregate']}_{m['column']}", "label": f"{m['aggregate']} of {columns.get(m['column'], {}).get('label', m['column'])}",
             "type": "integer" if m["aggregate"] == "count" else "number"} for m in measures]
    else:
        out_keys = list(columns)
        out = [{k: _shown(r.get(k)) for k in out_keys} for r in rows]
        meta = list(columns.values())
    for spec in reversed(sort):
        if spec["field"] not in out_keys:
            raise TableError("invalid_sort", f"Cannot sort by '{spec['field']}'; result columns: {', '.join(out_keys)}")
        present = [r for r in out if r.get(spec["field"]) is not None]
        present.sort(key=lambda r: r[spec["field"]], reverse=spec.get("direction") == "desc")
        out = present + [r for r in out if r.get(spec["field"]) is None]
    if not sort and group_by:
        out.sort(key=lambda r: tuple(str(r.get(k) or "") for k in group_by))
    limit = max(1, min(limit, MAX_RESULT_ROWS))
    matrix = [[r.get(k) for k in out_keys] for r in out]
    digest = hashlib.sha256(json.dumps([out_keys, matrix], separators=(",", ":"), default=str).encode()).hexdigest()
    columns_out = [{k: c[k] for k in ("key", "label", "type") if k in c} for c in meta]
    return {"columns": columns_out, "rows": matrix[:limit], "total_rows": len(matrix), "truncated": len(matrix) > limit,
            "digest": digest, "warnings": warnings}
