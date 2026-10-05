"""Describe a worksheet the way an analyst would: what it holds, not every row.

Small sheets (lookup tables, code lists, glossaries) are shown whole. Larger ones get a profile (header row, each
column's type, fill rate, examples and the formula behind it) plus the first rows, because formulas say how a figure is
computed and rows are data, not documentation. Shared by the Office (COM) and the standard-library readers."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .common import column_letter, markdown_table

FULL_ROWS = 60    # sheets up to this many rows are shown whole
SAMPLE_ROWS = 15  # larger sheets: this many rows after the header


@dataclass
class Sheet:
    name: str
    values: list[list[Any]]                 # the rows read (top-left of the used range first)
    formulas: list[list[str]] | None = None  # same shape; "" where a cell has no formula
    hidden: bool = False
    total_rows: int = 0                      # rows in the used range (may exceed the rows read)
    total_columns: int = 0
    first_row: int = 1                       # 1-based row and column of values[0][0]
    first_column: int = 1
    pivots: list[str] = field(default_factory=list)
    charts: list[str] = field(default_factory=list)


def show(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d") if (value.hour, value.minute, value.second) == (0, 0, 0) \
            else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else f"{value:.6g}"
    if isinstance(value, int) and value < -2_000_000_000:  # Excel error codes arrive as large negative ints
        return "#ERROR"
    return " ".join(str(value).split())


def kind(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "empty"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, dt.datetime | dt.date):
        return "date"
    return "text"


def header_row(rows: list[list[Any]]) -> int | None:
    """Index of the first row that looks like column headings: two or more filled cells, mostly text, with data below."""
    for index, row in enumerate(rows[:10]):
        filled = [v for v in row if kind(v) != "empty"]
        if len(filled) >= 2 and sum(kind(v) == "text" for v in filled) >= 0.6 * len(filled) and index + 1 < len(rows):
            return index
    return None


def profile(rows: list[list[Any]], formulas: list[list[str]] | None, header: int | None, first_column: int) -> str:
    width = max((len(r) for r in rows), default=0)
    names = [show(rows[header][j]) if header is not None and j < len(rows[header]) else "" for j in range(width)]
    data = rows[(header + 1) if header is not None else 0:]
    formula_rows = formulas[(header + 1) if header is not None else 0:] if formulas else []
    table = [["Column", "Heading", "Type", "Filled", "Examples", "Formula"]]
    for j in range(width):
        column = [r[j] if j < len(r) else None for r in data]
        kinds = [kind(v) for v in column]
        filled = [v for v, k in zip(column, kinds, strict=True) if k != "empty"]
        if not filled and not names[j]:
            continue
        counts = {k: kinds.count(k) for k in set(kinds) - {"empty"}}
        main = max(counts, key=lambda k: counts[k]) if counts else "empty"
        label = main if counts.get(main, 0) >= 0.9 * len(filled) else "mixed (" + "/".join(sorted(counts)) + ")"
        if main == "number" and filled:
            numbers = [float(v) for v in filled if isinstance(v, int | float)]
            low, high = (min(numbers), max(numbers)) if numbers else (None, None)
            examples = "" if low is None else show(low) if low == high else f"{show(low)} to {show(high)}"
        else:
            seen: list[str] = []
            for value in filled:
                text = show(value)[:30]
                if text and text not in seen:
                    seen.append(text)
                if len(seen) == 3:
                    break
            examples = ", ".join(seen)
        formula = ""
        if formula_rows:
            found = [r[j] for r in formula_rows if j < len(r) and isinstance(r[j], str) and r[j].startswith("=")]
            if found:
                share = round(100 * len(found) / max(len(formula_rows), 1))
                formula = f"{found[0][:70]} ({share}% of rows)"
        fill = f"{round(100 * len(filled) / max(len(column), 1))}%"
        table.append([column_letter(first_column - 1 + j), names[j], label, fill, examples, formula])
    return markdown_table(table)


def render(sheet: Sheet) -> str:
    rows = sheet.values
    total = sheet.total_rows or len(rows)
    columns = sheet.total_columns or max((len(r) for r in rows), default=0)
    start = f"{column_letter(sheet.first_column - 1)}{sheet.first_row}"
    end = f"{column_letter(sheet.first_column - 2 + max(columns, 1))}{sheet.first_row + max(total, 1) - 1}"
    head = f"## Sheet: {sheet.name}{' (hidden)' if sheet.hidden else ''}: {total} rows x {columns} columns ({start}:{end})"
    parts = [head]
    if not any(kind(v) != "empty" for row in rows for v in row):
        parts.append("(empty)")
    else:
        header = header_row(rows)
        has_formulas = bool(sheet.formulas) and any(isinstance(f, str) and f.startswith("=")
                                                    for r in sheet.formulas or [] for f in r)
        if total <= FULL_ROWS:
            parts.append(markdown_table([[show(v) for v in r] for r in rows]))
            if has_formulas:
                parts += ["Formulas:", profile(rows, sheet.formulas, header, sheet.first_column)]
        else:
            if header is not None:
                parts.append(f"Header row {sheet.first_row + header}. Column profile from the first {len(rows)} rows:")
            else:
                parts.append(f"No header row found. Column profile from the first {len(rows)} rows:")
            parts.append(profile(rows, sheet.formulas, header, sheet.first_column))
            top = (header or 0) + 1 + SAMPLE_ROWS
            parts += [f"First {min(top, len(rows))} rows:", markdown_table([[show(v) for v in r] for r in rows[:top]])]
    if sheet.pivots:
        parts.append("Pivot tables:\n" + "\n".join(f"- {p}" for p in sheet.pivots))
    if sheet.charts:
        parts.append("Charts:\n" + "\n".join(f"- {c}" for c in sheet.charts))
    return "\n\n".join(parts)
