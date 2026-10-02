"""Check my data: recompute stated figures from captured evidence rows, check claimed periods, replay cited requests.

Statuses per claim:
  MATCH            recomputed value equals the stated value within tolerance (and the stated rounding)
  DISCREPANCY      recomputed value differs
  PERIOD_MISMATCH  rows used do not belong to the period the claim states, or the period is incomplete
  NOT_VERIFIABLE   evidence, field or rows needed to recompute are missing
Replays: UNCHANGED, CHANGED (the source now returns different rows), UNAVAILABLE."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .calc import CalcError, evaluate

AGGREGATES = ("sum", "value", "mean", "min", "max", "count")


@dataclass
class Selector:
    evidence_id: str
    measure: str
    where: list[tuple[str, list[str]]] = field(default_factory=list)
    aggregate: str = "sum"
    period: str | None = None
    name: str | None = None


@dataclass
class Claim:
    label: str
    stated_value: float
    selector: Selector | None = None
    expression: str | None = None
    inputs: list[Selector] = field(default_factory=list)
    period: str | None = None
    tolerance_pct: float = 0.5


def _quarter(month: str) -> str:
    return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"


def _rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [c["key"] for c in evidence["columns"]]
    return [dict(zip(keys, row, strict=False)) for row in evidence["rows"]]


def _period_problem(rows: list[dict[str, Any]], period: str | None) -> str | None:
    if not period or not rows:
        return None
    months = {str(r["month"]) for r in rows if r.get("month")}
    quarters = {str(r["fiscal_quarter"]) for r in rows if r.get("fiscal_quarter")} | {_quarter(m) for m in months}
    if len(period) == 7 and "-Q" in period:
        if quarters and quarters != {period}:
            return f"rows cover {', '.join(sorted(quarters))}, not {period}"
        if months:
            expected = {f"{period[:4]}-{(int(period[-1]) - 1) * 3 + i:02d}" for i in (1, 2, 3)}
            missing = sorted(expected - months)
            if missing:
                return f"{period} is incomplete in the evidence: months {', '.join(missing)} are missing"
    elif len(period) == 7 and months and months != {period}:
        return f"rows cover {', '.join(sorted(months))}, not {period}"
    return None


def compute(selector: Selector, evidence_by_id: dict[str, dict[str, Any]]) -> tuple[float | None, str | None, int]:
    """Returns (value, problem, rows_used). A problem string means the value could not be recomputed or is suspect."""
    evidence = evidence_by_id.get(selector.evidence_id)
    if evidence is None:
        return None, f"evidence {selector.evidence_id} does not exist in this conversation", 0
    keys = {c["key"] for c in evidence["columns"]}
    if selector.measure not in keys:
        return None, f"{selector.measure} is not a column of {selector.evidence_id}", 0
    if evidence.get("truncated"):
        return None, f"{selector.evidence_id} was truncated; rerun the request without truncation to recompute", 0
    rows = _rows(evidence)
    for field_name, values in selector.where:
        if field_name not in keys:
            return None, f"{field_name} is not a column of {selector.evidence_id}", 0
        wanted = {str(v).casefold() for v in values}
        rows = [r for r in rows if str(r.get(field_name)).casefold() in wanted]
    if not rows:
        return None, f"no rows of {selector.evidence_id} match the stated filters", 0
    problem = _period_problem(rows, selector.period)
    values = [r[selector.measure] for r in rows if isinstance(r.get(selector.measure), int | float)]
    if selector.aggregate == "count":
        return float(len(rows)), problem, len(rows)
    if not values:
        return None, f"{selector.measure} has no numeric values in the matching rows", len(rows)
    if selector.aggregate == "value":
        if len(values) != 1:
            return None, f"expected exactly one matching row, found {len(values)}; add filters or use sum", len(rows)
        result = values[0]
    elif selector.aggregate == "sum":
        result = sum(values)
    elif selector.aggregate == "mean":
        result = sum(values) / len(values)
    elif selector.aggregate == "min":
        result = min(values)
    else:
        result = max(values)
    return float(result), problem, len(rows)


def _allowance(stated: float, recomputed: float, tolerance_pct: float) -> float:
    exponent = Decimal(repr(stated)).normalize().as_tuple().exponent
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    rounding = 0.5 * 10 ** (-decimals)
    return max(abs(recomputed) * tolerance_pct / 100, rounding, 1e-9)


def check(claims: list[Claim], evidence_by_id: dict[str, dict[str, Any]],
          replay: Callable[[str], tuple[str, str]] | None = None, replay_ids: list[str] | None = None) -> dict[str, Any]:
    results = []
    for claim in claims:
        notes: list[str] = []
        inputs_out = []
        recomputed: float | None = None
        status = "MATCH"
        if claim.selector is not None:
            recomputed, problem, used = compute(claim.selector, evidence_by_id)
            inputs_out.append({"evidence_id": claim.selector.evidence_id, "measure": claim.selector.measure,
                               "value": recomputed, "rows_used": used})
            if problem and recomputed is None:
                status, notes = "NOT_VERIFIABLE", [problem]
            elif problem:
                status, notes = "PERIOD_MISMATCH", [problem]
        elif claim.expression:
            variables: dict[str, float] = {}
            for selector in claim.inputs:
                value, problem, used = compute(selector, evidence_by_id)
                inputs_out.append({"name": selector.name, "evidence_id": selector.evidence_id, "measure": selector.measure,
                                   "period": selector.period, "value": value, "rows_used": used})
                if value is None:
                    status = "NOT_VERIFIABLE"
                    notes.append(f"{selector.name}: {problem}")
                    continue
                if problem and status == "MATCH":
                    status = "PERIOD_MISMATCH"
                if problem:
                    notes.append(f"{selector.name}: {problem}")
                variables[selector.name or ""] = value
            if status != "NOT_VERIFIABLE":
                try:
                    recomputed = evaluate(claim.expression, variables)
                except CalcError as error:
                    status, recomputed = "NOT_VERIFIABLE", None
                    notes.append(str(error))
        else:
            status = "NOT_VERIFIABLE"
            notes.append("a claim needs either an evidence selector or an expression with inputs")
        difference = None
        if recomputed is not None:
            difference = claim.stated_value - recomputed
            if abs(difference) > _allowance(claim.stated_value, recomputed, claim.tolerance_pct) and status == "MATCH":
                status = "DISCREPANCY"
                notes.append(f"stated {claim.stated_value:,.6g} but the evidence gives {recomputed:,.6g}")
        results.append({"label": claim.label, "status": status, "stated_value": claim.stated_value,
                        "recomputed_value": None if recomputed is None else round(recomputed, 6),
                        "difference": None if difference is None else round(difference, 6), "period": claim.period,
                        "inputs": inputs_out, "notes": notes})

    replays = []
    for evidence_id in replay_ids or []:
        if replay is None or evidence_id not in evidence_by_id:
            replays.append({"evidence_id": evidence_id, "status": "UNAVAILABLE", "detail": "unknown evidence id"})
            continue
        status, detail = replay(evidence_id)
        replays.append({"evidence_id": evidence_id, "status": status, "detail": detail})

    bad = [r for r in results if r["status"] in ("DISCREPANCY", "PERIOD_MISMATCH")]
    changed = [r for r in replays if r["status"] == "CHANGED"]
    unverifiable = [r for r in results if r["status"] == "NOT_VERIFIABLE"]
    if bad or changed:
        overall = "DISCREPANCY"
    elif results and len(unverifiable) == len(results):
        overall = "NOT_VERIFIABLE"
    elif not results and not replays:
        overall = "NOT_VERIFIABLE"
    else:
        overall = "CHECKED"
    matched = sum(1 for r in results if r["status"] == "MATCH")
    summary = f"{matched} of {len(results)} claim(s) match the cited evidence"
    if bad:
        summary += "; " + "; ".join(f"{r['label']}: {r['status']} ({'; '.join(r['notes'])})" for r in bad)
    if unverifiable:
        summary += f"; {len(unverifiable)} could not be recomputed"
    if replays:
        summary += "; replays: " + ", ".join(f"{r['evidence_id']} {r['status']}" for r in replays)
    return {"overall": overall, "summary": summary + ".", "claims": results, "replays": replays,
            "guidance": "Correct or clearly qualify any claim that does not match. Do not silently drop it."}
