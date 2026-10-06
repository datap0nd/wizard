"""Spreadsheets and CSV files as typed tables, so Wizard can filter, group and total every row of an attached file
(wizard_query_attachment) instead of reading a summary. Written next to the converted text:
  tables.json        [{sheet, file, columns: [{key, label, type}], rows, total_rows, truncated, non_numeric}]
  tables/<n>.csv     the rows, with the column keys as the header
wizard_connectors.attachment_tables reads them back and runs the queries."""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .common import column_letter
from .sheets import header_row, show

MAX_TABLE_ROWS = 300_000
MAX_TABLE_COLUMNS = 60
NUMBER = re.compile(r"^[-+]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$|^[-+]?\.\d+$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")


@dataclass
class Table:
    sheet: str
    columns: list[dict[str, Any]]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool
    non_numeric: dict[str, int] = field(default_factory=dict)  # numeric columns: cells that were not numbers


def key_of(label: str, index: int) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not key:
        return f"col_{column_letter(index).lower()}"
    return (f"c_{key}" if key[0].isdigit() else key)[:60]


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and NUMBER.match(value.strip()):
        return float(value.strip().replace(",", ""))
    return None


def as_date(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds").removesuffix(" 00:00:00")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str) and ISO_DATE.match(value.strip()):
        return value.strip()
    return None


def build(sheet: str, grid: list[list[Any]], total_rows: int | None = None) -> Table | None:
    """A typed table from a sheet's cells: the header row found as in the profile, then every row below it."""
    if not any(str(v).strip() for row in grid for v in row if v is not None):
        return None
    header = header_row(grid)
    width = min(max((len(r) for r in grid), default=0), MAX_TABLE_COLUMNS)
    labels = [show(grid[header][j]) if header is not None and j < len(grid[header]) else "" for j in range(width)]
    keys: list[str] = []
    for index, label in enumerate(labels):
        key = key_of(label, index)
        while key in keys:
            key += "_2"
        keys.append(key)
    body = [(list(r) + [None] * width)[:width] for r in grid[(header + 1) if header is not None else 0:]]
    body = [r for r in body if any(v is not None and str(v).strip() for v in r)]
    columns, non_numeric = [], {}
    for j, key in enumerate(keys):
        values = [r[j] for r in body if r[j] is not None and str(r[j]).strip()]
        numbers = sum(1 for v in values if as_number(v) is not None)
        dates = sum(1 for v in values if as_date(v) is not None)
        kind = "string"
        if values and numbers >= 0.9 * len(values):
            kind = "number"
            if numbers < len(values):
                non_numeric[key] = len(values) - numbers
        elif values and dates >= 0.9 * len(values):
            kind = "date"
        columns.append({"key": key, "label": labels[j] or key, "type": kind})
        for row in body:
            value = row[j]
            if value is None or (isinstance(value, str) and not value.strip()):
                row[j] = None
            elif kind == "number":
                row[j] = as_number(value)
            elif kind == "date":
                row[j] = as_date(value) or show(value)
            else:
                row[j] = show(value)
    truncated = len(body) > MAX_TABLE_ROWS or (total_rows is not None and total_rows > len(grid))
    return Table(sheet, columns, body[:MAX_TABLE_ROWS], max(total_rows or 0, len(body)), truncated, non_numeric)


def from_csv(path: Path, delimiter: str) -> Table | None:
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        grid: list[list[Any]] = []
        for index, row in enumerate(csv.reader(handle, delimiter=delimiter)):
            if index > MAX_TABLE_ROWS:
                break
            grid.append(list(row))
    return build(path.stem, grid)


def write(tables: list[Table], folder: Path) -> list[dict[str, Any]]:
    """Write tables.json and tables/<n>.csv in `folder`; returns the index."""
    index = []
    (folder / "tables").mkdir(parents=True, exist_ok=True)
    for number, table in enumerate(tables, start=1):
        name = f"tables/{number}.csv"
        with (folder / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([c["key"] for c in table.columns])
            writer.writerows([["" if v is None else repr(v) if isinstance(v, float) else v for v in row] for row in table.rows])
        meta = asdict(table)
        meta.pop("rows")
        index.append({**meta, "file": name, "rows": len(table.rows)})
    (folder / "tables.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index
