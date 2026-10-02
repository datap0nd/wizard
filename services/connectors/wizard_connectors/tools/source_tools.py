"""Per-system read tools: search reports, inspect a report's schema, run a report with prompt filters.

One set per approved system (three MCP connections = three systems). Rights are enforced here: a report the caller may
not see behaves exactly like a report that does not exist, and rows are limited to the caller's markets."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..catalog import Dimension, Measure, Report
from ..fixture_source import Filter, Sort
from .registry import UNTRUSTED_NOTICE, ToolContext, ToolError, ToolSpec

REPORT_ID = r"^[a-z0-9][a-z0-9-]{2,79}$"
FIELD = r"^[a-z][a-z0-9_]{0,63}$"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArgs(Args):
    query: str = Field(min_length=1, max_length=200, description="Words to look for in report names, descriptions, folders and column names, e.g. 'marketing spend quarter'.")
    limit: int = Field(default=10, ge=1, le=25, description="Maximum reports to return.")


class SchemaArgs(Args):
    report_id: str = Field(pattern=REPORT_ID, description="Report id from a search result.")


class FilterArg(Args):
    field: str = Field(pattern=FIELD, description="A dimension key from the report schema, e.g. market, fiscal_quarter, month, model_code.")
    values: list[str] = Field(min_length=1, max_length=50, description="Accepted values, e.g. ['SA','AE'] or ['2026-Q3'].")


class SortArg(Args):
    field: str = Field(pattern=FIELD)
    direction: Literal["asc", "desc"] = "asc"


class RunArgs(Args):
    report_id: str = Field(pattern=REPORT_ID, description="Report id from a search result.")
    filters: list[FilterArg] = Field(default_factory=list, max_length=10, description="Prompt answers: rows must match every filter.")
    group_by: list[str] | None = Field(default=None, max_length=6, description="Optional dimensions to aggregate to. Omit to get rows at the report grain. Measures aggregate by their declared rule (sum, period-end balance, or not aggregatable).")
    measures: list[str] | None = Field(default=None, max_length=12, description="Optional subset of measure keys; omit for all.")
    sort: list[SortArg] | None = Field(default=None, max_length=3)
    limit: int = Field(default=200, ge=1, le=500, description="Maximum rows returned (hard cap 500).")


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.casefold()) if len(w) > 1]


def visible_reports(ctx: ToolContext, system_id: str | None = None) -> list[tuple[str, Report]]:
    return [(s, r) for s, r in ctx.services.catalog.reports(system_id) if ctx.identity.can_see_report(s, r.id)]


def report_summary(ctx: ToolContext, system_id: str, report: Report) -> dict[str, Any]:
    contract = ctx.services.catalog.contracts[system_id]
    return {
        "report_id": report.id, "system": system_id, "name": report.name,
        "folder_path": ctx.services.catalog.folder_path(system_id, report.folder),
        "type": report.type, "row_access": report.row_access,
        "description": report.description[:400],
        "measures": [m.label for m in report.measures],
        "dimensions": [d.key for d in report.dimensions],
        "as_of": report.as_of, "data_mode": contract.system.connector.data_mode,
    }


def search(ctx: ToolContext, query: str, limit: int, system_id: str | None) -> list[dict[str, Any]]:
    terms = _words(query)
    scored = []
    for sid, report in visible_reports(ctx, system_id):
        name = report.name.casefold()
        columns: list[Dimension | Measure] = [*report.dimensions, *report.measures]
        body = " ".join([report.description, " ".join(ctx.services.catalog.folder_path(sid, report.folder)),
                         " ".join(f"{c.key} {c.label}" for c in columns),
                         " ".join(ctx.services.catalog.contracts[sid].system.families)]).casefold()
        score = sum(4 * name.count(t) + body.count(t) for t in terms)
        if score:
            scored.append((score, report.id, sid, report))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [report_summary(ctx, sid, r) for _, _, sid, r in scored[:limit]]


def _resolve(ctx: ToolContext, system_id: str, report_id: str) -> Report:
    found = ctx.services.catalog.report(report_id)
    if found is None or not ctx.identity.can_see_report(found[0], report_id):
        raise ToolError("report_not_available", f"No report '{report_id}' is available to you. Search to find report ids.")
    owner, report = found
    if owner != system_id:
        raise ToolError("wrong_system", f"'{report_id}' belongs to {owner.upper()}; use {owner}_run_report or {owner}_get_report_schema.")
    return report


def make_source_tools(system_id: str, system_name: str) -> list[ToolSpec]:
    def search_handler(ctx: ToolContext, args: SearchArgs) -> dict[str, Any]:
        if not ctx.identity.can_use_system(system_id):
            raise ToolError("system_not_available", f"{system_name} is not available to you.")
        results = search(ctx, args.query, args.limit, system_id)
        return {"system": system_id, "results": results,
                "note": None if results else "No matching reports you can access. Try other words or wizard_search_catalog."}

    def schema_handler(ctx: ToolContext, args: SchemaArgs) -> dict[str, Any]:
        report = _resolve(ctx, system_id, args.report_id)
        contract = ctx.services.catalog.contracts[system_id]
        source = ctx.services.sources[system_id]
        markets = ctx.identity.allowed_markets(system_id)
        return {
            **report_summary(ctx, system_id, report),
            "description": report.description,
            "grain": report.grain,
            "dimensions": source.dimensions(report) if report.row_access == "ROWS" else [d.model_dump() for d in report.dimensions],
            "measures": [m.model_dump() for m in report.measures],
            "attributes": [a.model_dump() for a in report.attributes],
            "prompts": [p.model_dump() for p in report.prompts],
            "caveats": report.caveats, "refresh": report.refresh,
            "connector_status": contract.system.connector.status,
            "your_market_access": "all markets" if markets is None else sorted(markets),
            "how_to_query": (f"Call {system_id}_run_report with filters on dimensions; add group_by to aggregate."
                             if report.row_access == "ROWS" else "Navigation only: rows cannot be read through Wizard."),
        }

    def run_handler(ctx: ToolContext, args: RunArgs) -> dict[str, Any]:
        report = _resolve(ctx, system_id, args.report_id)
        contract = ctx.services.catalog.contracts[system_id]
        result = ctx.services.sources[system_id].run(
            report,
            filters=[Filter(f.field, f.values) for f in args.filters],
            group_by=args.group_by, measures=args.measures,
            sort=[Sort(s.field, s.direction) for s in args.sort or []],
            limit=args.limit, allowed_markets=ctx.identity.allowed_markets(system_id),
        )
        request = {"filters": [f.model_dump() for f in args.filters], "group_by": args.group_by,
                   "measures": args.measures, "sort": [s.model_dump() for s in args.sort or []], "limit": args.limit}
        evidence = {
            "tool": f"{system_id}_run_report", "system": system_id, "system_name": system_name,
            "report_id": report.id, "report_name": report.name,
            "folder_path": ctx.services.catalog.folder_path(system_id, report.folder),
            "data_mode": contract.system.connector.data_mode, "connector_status": contract.system.connector.status,
            "request": request, "columns": result.columns, "rows": result.rows, "total_rows": result.total_rows,
            "truncated": result.truncated, "as_of": result.as_of, "retrieved_at": ctx.services.now().isoformat(),
            "digest": result.digest, "warnings": result.warnings, "access_note": result.access_note,
            "caveats": report.caveats,
            "locator": {"system": system_id, "report_id": report.id, "open_url": None},
        }
        evidence_id = ctx.recorder.add_evidence(evidence)
        return {
            "evidence_id": evidence_id, "cite_as": f"[{evidence_id}]",
            "source": {"system": system_id, "report_id": report.id, "report_name": report.name,
                       "data_mode": evidence["data_mode"]},
            "as_of": result.as_of, "request": request, "columns": result.columns, "rows": result.rows,
            "row_count": len(result.rows), "total_rows": result.total_rows, "truncated": result.truncated,
            "warnings": result.warnings, "access_note": result.access_note, "caveats": report.caveats,
            "source_text_policy": UNTRUSTED_NOTICE,
        }

    return [
        ToolSpec(f"{system_id}_search_reports",
                 f"Search the {system_name} report catalog you are allowed to see ({contract_families(system_id)}). "
                 "Returns report ids, names, folders, measures and whether rows can be read (row_access ROWS) or the "
                 "report is navigation only.", SearchArgs, search_handler, system_id, "source"),
        ToolSpec(f"{system_id}_get_report_schema",
                 f"Describe one {system_name} report: grain, dimensions you can filter or group by, measures with units "
                 "and aggregation rules, prompts, caveats, freshness and your market access.", SchemaArgs, schema_handler,
                 system_id, "source"),
        ToolSpec(f"{system_id}_run_report",
                 f"Read rows from one {system_name} report with prompt filters and optional grouping (read-only, at most "
                 "500 rows). Each call is recorded as evidence with an id such as E3: cite it as [E3] next to numbers "
                 "that come from it. Missing rows mean no data, not zero.", RunArgs, run_handler, system_id, "source"),
    ]


FAMILIES = {"nerp": "marketing spend and campaign budgets", "gscm": "sell-in, sell-out and channel stock",
            "asap": "market share, Smart Switch, installed base, app engagement and finance reports"}


def contract_families(system_id: str) -> str:
    return FAMILIES.get(system_id, "reports")
