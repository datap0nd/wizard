"""Cross-source tools: list sources, search the whole catalog, look up definitions, calculate, present a visual and the
optional Check my data verification."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wizard_checks.calc import CalcError, evaluate
from wizard_checks.checker import Claim, Selector, check

from ..fixture_source import Filter, Sort, SourceError
from .registry import ToolContext, ToolError, ToolSpec
from .source_tools import search, visible_reports

EVIDENCE_ID = r"^E[0-9]{1,4}$"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


class CatalogSearchArgs(Args):
    query: str = Field(min_length=1, max_length=200, description="Words describing the data you need, e.g. 'smart switch apple'.")
    limit: int = Field(default=10, ge=1, le=25)


class DefinitionArgs(Args):
    query: str = Field(min_length=1, max_length=200, description="Term or topic, e.g. 'sell-through', 'fiscal quarter', 'ROI'.")
    limit: int = Field(default=3, ge=1, le=8)


class Variable(Args):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
    value: float


class CalculateArgs(Args):
    expression: str = Field(min_length=1, max_length=500, description="Arithmetic using + - * / ** % ( ) and abs, min, max, sum, avg, round, sqrt, e.g. '(q3 - q2) / spend_musd'.")
    variables: list[Variable] = Field(default_factory=list, max_length=40)


class VisualColumn(Args):
    key: str = Field(pattern=r"^[A-Za-z0-9_]{1,40}$")
    label: str = Field(min_length=1, max_length=80)
    type: Literal["string", "integer", "number", "percent", "currency"] = "string"
    unit: str | None = Field(default=None, max_length=16)


class VisualArgs(Args):
    kind: Literal["bar", "line", "scatter", "table"] = Field(description="bar for ranking/comparison, line for time series, scatter for two measures, table for exact values.")
    title: str = Field(min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=240)
    columns: list[VisualColumn] = Field(min_length=1, max_length=12)
    rows: list[list[float | str | None]] = Field(min_length=1, max_length=100, description="One list per row, in column order. Numbers may be given as numbers or numeric text.")
    x: str | None = Field(default=None, description="Column key for categories or time (charts).")
    series: list[str] = Field(default_factory=list, max_length=6, description="Numeric column keys to plot (charts).")
    evidence_ids: list[str] = Field(default_factory=list, max_length=20, description="Evidence ids the values come from, e.g. ['E1','E2'].")
    note: str | None = Field(default=None, max_length=400, description="How values were derived and any caveat.")


class Where(Args):
    field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    values: list[str] = Field(min_length=1, max_length=50)


class Input(Args):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
    evidence_id: str = Field(pattern=EVIDENCE_ID)
    measure: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    where: list[Where] = Field(default_factory=list, max_length=8)
    aggregate: Literal["sum", "value", "mean", "min", "max", "count"] = "sum"
    period: str | None = Field(default=None, pattern=r"^[0-9]{4}-(Q[1-4]|[0-9]{2})$", description="Period this input should cover, e.g. 2026-Q3 or 2026-07.")


class ClaimArg(Args):
    label: str = Field(min_length=1, max_length=160, description="The statement being checked, e.g. 'EG Q3 spend'.")
    stated_value: float = Field(description="The number as stated in the answer.")
    evidence_id: str | None = Field(default=None, pattern=EVIDENCE_ID, description="For a direct figure: the evidence it comes from.")
    measure: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    where: list[Where] = Field(default_factory=list, max_length=8)
    aggregate: Literal["sum", "value", "mean", "min", "max", "count"] = "sum"
    period: str | None = Field(default=None, pattern=r"^[0-9]{4}-(Q[1-4]|[0-9]{2})$")
    expression: str | None = Field(default=None, max_length=300, description="For a derived figure: arithmetic over input names.")
    inputs: list[Input] = Field(default_factory=list, max_length=8)
    tolerance_pct: float = Field(default=0.5, ge=0, le=10)

    @model_validator(mode="after")
    def one_kind(self) -> ClaimArg:
        direct = self.evidence_id is not None and self.measure is not None
        derived = self.expression is not None and bool(self.inputs)
        if direct == derived:
            raise ValueError("give either evidence_id + measure (direct figure) or expression + inputs (derived figure)")
        return self


class CheckArgs(Args):
    claims: list[ClaimArg] = Field(default_factory=list, max_length=30, description="Figures from your answer to recompute from cited evidence.")
    replay_evidence_ids: list[str] = Field(default_factory=list, max_length=10, description="Evidence ids whose source request should be re-run to detect changed data.")


def list_sources(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    guides = {n.id: n for n in ctx.services.knowledge.notes if n.id.startswith("platform-")}
    systems = []
    for system in ctx.services.catalog.systems:
        if not ctx.identity.can_use_system(system.id):
            continue
        reports = visible_reports(ctx, system.id)
        markets = ctx.identity.allowed_markets(system.id)
        guide = guides.get(f"platform-{system.id}")
        systems.append({"system": system.id, "name": system.name, "description": system.description,
                        "data_families": system.families, "connector_status": system.connector.status,
                        "data_mode": system.connector.data_mode, "reports_visible": len(reports),
                        "reports_with_rows": sum(1 for _, r in reports if r.row_access == "ROWS"),
                        "your_market_access": "all markets" if markets is None else sorted(markets),
                        "platform_guide": f"wizard_lookup_definitions('{guide.title}')" if guide else None,
                        "how_to_navigate": f"{system.id}_search_reports → {system.id}_get_report_schema → {system.id}_run_report"})
    return {"sources": systems, "note": "Only sources and reports you are entitled to are listed."}


def search_catalog(ctx: ToolContext, args: CatalogSearchArgs) -> dict[str, Any]:
    return {"results": search(ctx, args.query, args.limit, None)}


def lookup_definitions(ctx: ToolContext, args: DefinitionArgs) -> dict[str, Any]:
    notes = ctx.services.knowledge.search(args.query, args.limit)
    return {"definitions": [{"id": n.id, "title": n.title, "approval_status": n.status, "owner": n.owner,
                             "text": n.body} for n in notes],
            "note": "DRAFT_UNSIGNED definitions are working assumptions; say so when you rely on them."
            if any(n.status != "SIGNED" for n in notes) else None}


def calculate(ctx: ToolContext, args: CalculateArgs) -> dict[str, Any]:
    try:
        value = evaluate(args.expression, {v.name: v.value for v in args.variables})
    except CalcError as error:
        raise ToolError("calculation_error", str(error)) from None
    return {"expression": args.expression, "variables": {v.name: v.value for v in args.variables}, "result": value}


NUMBER = re.compile(r"^[-+]?[0-9][0-9,]*(\.[0-9]+)?%?$|^[-+]?\.[0-9]+%?$")


def render_visual(ctx: ToolContext, args: VisualArgs) -> dict[str, Any]:
    keys = [c.key for c in args.columns]
    if len(set(keys)) != len(keys):
        raise ToolError("invalid_visual", "Column keys must be unique.")
    numeric = {c.key for c in args.columns if c.type != "string"}
    rows = []
    for index, row in enumerate(args.rows):
        if len(row) != len(keys):
            raise ToolError("invalid_visual", f"Row {index + 1} has {len(row)} values; expected {len(keys)}.")
        clean: list[Any] = []
        for key, value in zip(keys, row, strict=True):
            if key in numeric and isinstance(value, str):
                text = value.strip()
                if not NUMBER.match(text):
                    raise ToolError("invalid_visual", f"Row {index + 1}, {key}: '{value[:20]}' is not a number.")
                value = float(text.replace(",", "").rstrip("%"))
            if key not in numeric and value is not None and not isinstance(value, str):
                value = str(value)
            clean.append(value)
        rows.append(clean)
    if args.kind != "table":
        if args.x not in keys:
            raise ToolError("invalid_visual", "Charts need x set to one of the column keys.")
        bad = [s for s in args.series if s not in numeric]
        if not args.series or bad:
            raise ToolError("invalid_visual", "Charts need series set to numeric column keys.")
        if args.kind == "scatter" and len(args.series) != 2:
            raise ToolError("invalid_visual", "A scatter chart needs exactly two numeric series (x measure, y measure).")
    known = {e["id"] for e in ctx.recorder.all_evidence()}
    unknown = [e for e in args.evidence_ids if e not in known]
    if unknown:
        raise ToolError("unknown_evidence", f"Unknown evidence id(s) {', '.join(unknown)}. Known: {', '.join(sorted(known)) or 'none yet'}.")
    payload = {**args.model_dump(), "rows": rows, "derived_by": "model"}
    visual_id = ctx.recorder.add_visual(payload)
    return {"visual_id": visual_id, "cite_as": f"[{visual_id}]",
            "placement": f"Put [{visual_id}] on its own line in your answer where it should appear.",
            "uncited": not args.evidence_ids}


def check_my_data(ctx: ToolContext, args: CheckArgs) -> dict[str, Any]:
    evidence = {e["id"]: e for e in ctx.recorder.all_evidence()}

    def selector(item: Any, name: str | None = None) -> Selector:
        return Selector(evidence_id=item.evidence_id, measure=item.measure,
                        where=[(w.field, w.values) for w in item.where], aggregate=item.aggregate,
                        period=item.period, name=name)

    claims = [Claim(label=c.label, stated_value=c.stated_value, period=c.period, tolerance_pct=c.tolerance_pct,
                    selector=selector(c) if c.evidence_id else None, expression=c.expression,
                    inputs=[selector(i, i.name) for i in c.inputs]) for c in args.claims]

    def replay(evidence_id: str) -> tuple[str, str]:
        original = evidence[evidence_id]
        found = ctx.services.catalog.report(original["report_id"])
        if found is None or not ctx.identity.can_see_report(found[0], original["report_id"]):
            return "UNAVAILABLE", "the report is no longer available to you"
        request = original["request"]
        try:
            fresh = ctx.services.sources[found[0]].run(
                found[1], filters=[Filter(f["field"], f["values"]) for f in request["filters"]],
                group_by=request["group_by"], measures=request["measures"],
                sort=[Sort(s["field"], s["direction"]) for s in request["sort"]], limit=request["limit"],
                allowed_markets=ctx.identity.allowed_markets(found[0]))
        except SourceError as error:
            return "UNAVAILABLE", error.message
        if fresh.digest == original["digest"]:
            return "UNCHANGED", "the source returns the same rows today"
        return "CHANGED", "the source now returns different rows than when the answer was prepared"

    result = check(claims, evidence, replay, args.replay_evidence_ids)
    ctx.recorder.add_check(result)
    return result


CORE_TOOLS = [
    ToolSpec("wizard_list_sources", "List the source systems you can use, their data families (spend, sell-out, share, "
             "switching...), connector status and data mode (SYNTHETIC, DATED_APPROVED_SNAPSHOT or LIVE_VERIFIED).",
             NoArgs, list_sources, "wizard", "source"),
    ToolSpec("wizard_search_catalog", "Search every report you can access across all systems at once. Use when you do "
             "not know which system holds the data.", CatalogSearchArgs, search_catalog, "wizard", "source"),
    ToolSpec("wizard_lookup_definitions", "Look up business definitions and conventions: metrics (sell-through, share, "
             "investment-efficiency proxy, observed switchers), fiscal calendar, markets and models. Each definition shows "
             "whether an owner has signed it.", DefinitionArgs, lookup_definitions, "wizard", "knowledge"),
    ToolSpec("wizard_calculate", "Evaluate arithmetic exactly over named numbers (e.g. growth, ratios, per-million "
             "normalisation) instead of doing long arithmetic in your head.", CalculateArgs, calculate, "wizard", "check"),
    ToolSpec("wizard_render_visual", "Show a chart or table in the answer. Provide the exact values, units and the "
             "evidence ids they come from; returns an id such as V1 to place in the answer.", VisualArgs, render_visual,
             "wizard", "present"),
    ToolSpec("wizard_check_my_data", "Optional verification. Recompute figures you state from the cited evidence rows, "
             "check that each figure covers the period you claim, and optionally re-run cited requests to detect changed "
             "source data. Reports MATCH, DISCREPANCY, PERIOD_MISMATCH or NOT_VERIFIABLE per figure; it never edits your "
             "answer.", CheckArgs, check_my_data, "wizard", "check"),
]
