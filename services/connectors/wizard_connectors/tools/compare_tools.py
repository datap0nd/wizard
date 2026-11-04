"""Two tables compared row by row and number by number, in Wizard's code rather than by Gemini's reading (owner, 4 Nov
2026: "how can you ensure we fully map GSCM once and for all? Are we being precise with this?", then "Im not exporting
anything"). wizard_compare_evidence checks one of Wizard's reads against another: a portal's direct data request
against what the report's own screen showed for the same filters, so a map is proven to reproduce the portal exactly
without anyone exporting a file. wizard_task_compare (task_tools.py) uses the same comparison for a file a task was
given. The outcome can be kept in the report's map entry."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import portal_map
from .registry import ToolContext, ToolError, ToolSpec

SHOWN = 40  # differences and rows on one side only listed in the answer; all are counted
EVIDENCE_ID = r"^E\d{1,6}$"
SYSTEM = r"^[a-z][a-z0-9]{1,15}$"
MAP_ID = r"^[a-z0-9][a-z0-9_.-]{0,79}$"


def number(value: Any) -> float | None:
    """A cell as a number: 1,234 / (56) / -7.5 / 12 % / '-' (blank)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace(",", "").replace(" ", "").replace("%", "")
    if text in ("", "-", "--", "—"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    try:
        found = float(text.strip("()"))
    except ValueError:
        return None
    return -found if negative else found


def key_of(value: Any) -> str:
    found = number(value) if not isinstance(value, str) or re.fullmatch(r"[\s\d.,()%-]+", value) else None
    if found is not None:
        return str(int(found)) if found == int(found) else repr(found)
    return " ".join(str(value or "").split()).casefold()


def column(names: dict[str, int], wanted: str, side: str, shown: list[str]) -> int:
    found = names.get(wanted.casefold())
    if found is None:
        raise ToolError("unknown_column", f"No column '{wanted}' in {side}. Its columns: {', '.join(shown)}.")
    return found


def compare_tables(left: str, left_rows: list[list[Any]], left_keys: list[int], left_values: list[int],
                   right: str, right_rows: list[list[Any]], right_keys: list[int], right_values: list[int],
                   value_names: list[str], tolerance: float, right_truncated: bool = False) -> dict[str, Any]:
    """Rows matched by their key columns; numbers equal within the tolerance (a blank and a zero count as equal, and are
    counted); the rows only one side has; keys that repeat. MATCH only when everything agrees."""
    def by_key(rows: list[list[Any]], keys: list[int]) -> tuple[dict[tuple[str, ...], list[Any]], int]:
        found: dict[tuple[str, ...], list[Any]] = {}
        twice = 0
        for row in rows:
            key = tuple(key_of(row[i] if i < len(row) else None) for i in keys)
            if not any(key):
                continue
            twice += key in found
            found[key] = row
        return found, twice

    mine, mine_twice = by_key(left_rows, left_keys)
    theirs, theirs_twice = by_key(right_rows, right_keys)
    both = [k for k in mine if k in theirs]
    differences: list[dict[str, Any]] = []
    blank_vs_zero = values_compared = values_matched = rows_matched = 0
    for key in both:
        row_ok = True
        for name, li, ri in zip(value_names, left_values, right_values, strict=True):
            a = number(mine[key][li] if li < len(mine[key]) else None)
            b = number(theirs[key][ri] if ri < len(theirs[key]) else None)
            values_compared += 1
            if (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= tolerance):
                values_matched += 1
            elif a in (None, 0.0) and b in (None, 0.0):
                blank_vs_zero += 1
                values_matched += 1
            else:
                row_ok = False
                differences.append({"row": list(key), "column": name, left: a, right: b})
        rows_matched += row_ok
    only_left = [list(k) for k in mine if k not in theirs]
    only_right = [list(k) for k in theirs if k not in mine]
    problems = []
    if mine_twice or theirs_twice:
        problems.append(f"{mine_twice + theirs_twice} key(s) appear on more than one row: add key columns until each row "
                        "has its own (a sub-total row and a detail row can share an account)")
    if right_truncated:
        problems.append(f"the {right} evidence holds only part of its rows: narrow it (fewer days or subsidiaries)")
    verdict = ("NO_OVERLAP" if not both else
               "MATCH" if not (differences or only_left or only_right or problems) else "DIFFERENT")
    return {"verdict": verdict, f"rows_in_{left}": len(mine), f"rows_in_{right}": len(theirs), "rows_compared": len(both),
            "rows_matched": rows_matched, "values_compared": values_compared, "values_matched": values_matched,
            "blank_vs_zero": blank_vs_zero, "differences": differences[:SHOWN], "differences_total": len(differences),
            f"only_in_{left}": only_left[:SHOWN], f"only_in_{left}_total": len(only_left),
            f"only_in_{right}": only_right[:SHOWN], f"only_in_{right}_total": len(only_right), "problems": problems}


def keep_in_map(ctx: ToolContext, system: str | None, report: str | None, against: str, result: dict[str, Any],
                evidence: list[str]) -> str | None:
    """Keep a comparison's outcome in the report's map entry (reply_check); None when no report was named."""
    if not (system and report) or ctx.services.portal_maps is None:
        return None
    try:
        ctx.services.portal_maps.check_reply(system, report, {
            "at": ctx.services.now().isoformat(), "against": against, "verdict": result["verdict"],
            "rows_compared": result["rows_compared"], "rows_matched": result["rows_matched"],
            "values_compared": result["values_compared"], "values_matched": result["values_matched"],
            "differences": result["differences_total"], "evidence": evidence})
    except portal_map.MapError as error:
        return f"not kept: {error}"
    return f"{system}:{report}"


def evidence_table(ctx: ToolContext, evidence_id: str) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    evidence = ctx.recorder.get_evidence(evidence_id)
    if evidence is None:
        raise ToolError("unknown_evidence", f"No evidence {evidence_id} in this conversation.")
    shown = [str(c.get("key") if isinstance(c, dict) else c) for c in evidence.get("columns") or []]
    return evidence, shown, {name.casefold(): i for i, name in enumerate(shown)}


def truncated(evidence: dict[str, Any]) -> bool:
    return bool(evidence.get("truncated")) or int(evidence.get("total_rows") or 0) > len(evidence.get("rows") or [])


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidencePair(Args):
    reference: str = Field(min_length=1, max_length=200, description="The column in the reference evidence, by name.")
    checked: str = Field(min_length=1, max_length=200, description="The same column in the evidence being checked.")


class CompareEvidenceArgs(Args):
    reference: str = Field(pattern=EVIDENCE_ID, description="What the result must equal: e.g. the rows the report's own screen showed (its grid's dataset, read after the person's path).")
    checked: str = Field(pattern=EVIDENCE_ID, description="The evidence to check, e.g. the first reply of portal_prove_request for the same filters.")
    keys: list[EvidencePair] = Field(min_length=1, max_length=20, description="The columns that tell one row from another on both sides, e.g. the account and the country.")
    values: list[EvidencePair] = Field(min_length=1, max_length=5000, description="The numbers to compare (one pair per day for a report with a column per day).")
    tolerance: float = Field(default=0.0, ge=0, le=1_000_000, description="The largest difference two numbers may have and still match.")
    against: str = Field(default="the report's own screen", max_length=120, description="What the reference is, in words, for the map.")
    system: str | None = Field(default=None, pattern=SYSTEM, description="With report: the portal whose map keeps the outcome, e.g. gscm.")
    report: str | None = Field(default=None, pattern=MAP_ID, description="The report's id in that portal's map.")


def compare_evidence(ctx: ToolContext, args: CompareEvidenceArgs) -> dict[str, Any]:
    reference, ref_shown, ref_names = evidence_table(ctx, args.reference)
    checked, chk_shown, chk_names = evidence_table(ctx, args.checked)
    result = compare_tables(
        "reference", reference.get("rows") or [],
        [column(ref_names, p.reference, f"evidence {args.reference}", ref_shown) for p in args.keys],
        [column(ref_names, p.reference, f"evidence {args.reference}", ref_shown) for p in args.values],
        "checked", checked.get("rows") or [],
        [column(chk_names, p.checked, f"evidence {args.checked}", chk_shown) for p in args.keys],
        [column(chk_names, p.checked, f"evidence {args.checked}", chk_shown) for p in args.values],
        [p.reference for p in args.values], args.tolerance, truncated(checked))
    if truncated(reference):
        result["problems"].append("the reference evidence holds only part of its rows: narrow it")
        result["verdict"] = "DIFFERENT" if result["verdict"] == "MATCH" else result["verdict"]
    kept = keep_in_map(ctx, args.system, args.report, args.against, result, [args.reference, args.checked])
    if kept:
        result["kept_in_map"] = kept
    result["note"] = ("Every row and number of the checked evidence equals the reference." if result["verdict"] == "MATCH"
                      else "Find why before saying the report is read precisely: a filter not set the same way (dates, "
                           "subsidiaries, the account level), sub-total rows, a unit, or the wrong columns paired.")
    return result


COMPARE_TOOLS = [
    ToolSpec("wizard_compare_evidence",
             "Check one of your reads against another, row by row and number by number, in Wizard's code: e.g. a "
             "portal's direct data request (portal_prove_request's first reply) against the rows the report's own screen "
             "showed for the same filters. Rows are matched by the key columns, numbers within the tolerance; the rows "
             "only one side has are listed. MATCH means everything agrees. With system and report, the outcome is kept "
             "in that report's map entry.", CompareEvidenceArgs, compare_evidence, "wizard", "check"),
]
