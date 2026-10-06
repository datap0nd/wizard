"""Draft report entries that make documented materialized views queryable by Wizard, and run a report's query for a
parity check (task 19).

`draft()` reads the export (inbox/_postgres/<database>.json) and writes contracts/sources/postgresql.json: one report
per chosen view, with dimensions, measures, an aggregation rule per measure, roles, value hints and the view as its
`relation`. Every guess is marked "UNCERTAIN:" for review; the dataset note's summary becomes the description.
`sample()` runs the exact query Wizard would run (same live source) so the owner can compare one number with a report
they trust before signing the view's parity."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wizard_connectors.catalog import SourceContract
from wizard_connectors.fixture_source import Filter, SourceError
from wizard_connectors.knowledge import front_matter, unquote
from wizard_connectors.pg import PgSettings
from wizard_connectors.postgres_source import PostgresSource

from .common import ConversionError, markdown_table

SYSTEM = {"id": "postgresql", "name": "PostgreSQL",
          "description": "The reporting database Metronome loads (ASAP, GSCM and other exports); materialized views are "
                         "read live through a read-only account.",
          "families": ["reporting"], "owner": "TBD - database owner",
          "connector": {"status": "ROWS_UNVERIFIED", "data_mode": "LIVE_UNVERIFIED", "transport": "postgresql",
                        "live_interface": "PostgreSQL read-only (pg8000)"}, "open_url_template": None}
NUMERIC = ("smallint", "integer", "bigint", "numeric", "decimal", "real", "double precision", "money")
MARKET = re.compile(r"(^|_)(market|mkt|country|cty|subsidiary|sub|region|territory)(_|$)")
PERIOD = re.compile(r"(^|_)(date|day|week|wk|yyyyww|yearweek|month|mon|period|quarter|qtr|year|yr|fy)(_|$)")
MODEL = re.compile(r"(^|_)(model|product|sku|family|series|item)(_|$)")
IDENTIFIER = re.compile(r"(^|_)(id|code|key|no|num|number)$")
NOT_ADDITIVE = re.compile(r"(^|_)(rate|pct|percent|share|ratio|avg|average|mean|price|asp|growth|index|idx|margin_pct)(_|$)")
BALANCE = re.compile(r"(^|_)(stock|inventory|inv|on_hand|onhand|balance|backlog|installed|active|headcount|wos)(_|$)")
AMOUNT = re.compile(r"(^|_)(amt|amount|revenue|value|cost|usd|eur|gbp|sales_value|price|asp)(_|$)")
# A text column holds a number when its name ENDS with a quantity word: net_sales, sell_in_qty (not sales_rep).
QUANTITY = re.compile(r"(^|_)(qty|quantity|units|unit|volume|vol|amt|amount|revenue|value|cost|sales|sell_in|sell_out|"
                      r"stock|inventory|count|total|sum)$")
PERIOD_PREFERENCE = ("week", "wk", "yyyyww", "yearweek", "date", "day", "month", "mon", "period", "quarter", "qtr", "year")


def key_of(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "column"
    return f"c_{key}" if key[0].isdigit() else key[:64]


def kebab(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def note_summary(content: Path, schema: str, name: str) -> str:
    for path in (content / "knowledge" / "datasets").glob("*.md") if (content / "knowledge" / "datasets").is_dir() else []:
        parsed = front_matter(path.read_text(encoding="utf-8-sig"))
        if parsed and (parsed[0].get("id") == kebab(f"{schema}-{name}") or f"{schema}.{name}" in parsed[0].get("aliases", "")):
            return unquote(parsed[0].get("summary", ""))
    return ""


def draft_report(content: Path, database: str, view: dict[str, Any], exported: str) -> dict[str, Any]:
    schema, name = view["schema"], view["name"]
    caveats = [f"DRAFT: generated from the PostgreSQL export of {exported}; owner review required."]
    dimensions: list[dict[str, Any]] = []
    measures: list[dict[str, Any]] = []
    period_candidates: list[tuple[int, dict[str, Any]]] = []
    for column in view["columns"]:
        raw, kind = column["name"], column["type"].lower()
        key = key_of(raw)
        lower = raw.lower()
        numeric = kind.startswith(NUMERIC)
        is_period = bool(PERIOD.search(lower)) or kind.startswith(("date", "timestamp"))
        text_number = not numeric and bool(QUANTITY.search(lower)) and not is_period and not IDENTIFIER.search(lower)
        entry: dict[str, Any] = {"key": key, "label": raw.replace("_", " ").strip().capitalize()}
        if key != raw:
            entry["column"] = raw
        if (numeric and not is_period and not IDENTIFIER.search(lower)) or text_number:
            aggregation = "none" if NOT_ADDITIVE.search(lower) else "last" if BALANCE.search(lower) else "sum"
            if re.search(r"(^|_)(pct|percent|share|rate)(_|$)", lower):
                entry.update(type="percent", unit="%", aggregation="none")
            elif AMOUNT.search(lower):
                entry.update(type="currency", unit="USD" if "usd" in lower else "UNKNOWN currency (owner to confirm)",
                             aggregation="sum_same_currency" if aggregation == "sum" and "usd" not in lower else aggregation)
                if "usd" not in lower:
                    caveats.append(f"UNCERTAIN: the currency of {key} is unknown; it is added up only within one currency.")
            else:
                entry.update(type="integer" if kind.startswith(("smallint", "integer", "bigint")) else "number",
                             aggregation=aggregation)
            caveats.append(f"UNCERTAIN: {key} is added up as '{entry['aggregation']}', guessed from its name.")
            if text_number:
                caveats.append(f"UNCERTAIN: {key} is stored as text in the view; Wizard reads it as a number.")
            measures.append(entry)
            continue
        entry["type"] = "integer" if kind.startswith(("smallint", "integer", "bigint")) else "string"
        if MARKET.search(lower):
            entry["role"] = "market"
        elif MODEL.search(lower):
            entry["role"] = "model"
        if is_period:
            rank = next((i for i, word in enumerate(PERIOD_PREFERENCE) if re.search(rf"(^|_){word}(_|$)", lower)), 50)
            period_candidates.append((rank, entry))
        if column.get("values"):
            entry["values_hint"] = column["values"][:25]
        dimensions.append(entry)
    if period_candidates:
        period_candidates.sort(key=lambda item: item[0])
        period_candidates[0][1]["role"] = "period"
    has_period = any(d.get("role") == "period" for d in dimensions)
    has_currency = any("currency" in d["key"] for d in dimensions)
    for measure in measures:
        if measure["aggregation"] == "last" and not has_period:
            measure["aggregation"] = "none"
            caveats.append(f"UNCERTAIN: {measure['key']} looks like a balance but the view has no period column; it is "
                           "not added up.")
        if measure["aggregation"] == "sum_same_currency" and not has_currency:
            measure["aggregation"] = "none"
            caveats.append(f"UNCERTAIN: {measure['key']} is an amount without a currency column; it is not added up "
                           "until the owner confirms its currency.")
    grain: list[str] = []
    for index in view.get("indexes", []):
        found = re.search(r"CREATE UNIQUE INDEX .*?\((.+)\)\s*$", index)
        if found:
            grain = [key_of(part.strip().strip('"')) for part in found.group(1).split(",")]
            break
    if not grain:
        caveats.append("UNCERTAIN: no unique index, so what one row is (the grain) is not known from the catalog.")
    description = note_summary(content, schema, name) or view.get("comment") or ""
    if not description:
        description = "UNKNOWN: describe what one row is and what the view is for (owner review required)."
    if view.get("freshness"):
        caveats.append(f"Freshness at export: {view['freshness']}.")
    return {"id": f"postgresql-{kebab(schema)}-{kebab(name)}"[:80], "name": f"{schema}.{name}",
            "folder": f"postgresql-{kebab(database)}-{kebab(schema)}"[:80], "type": "report", "row_access": "ROWS",
            "file": None, "description": description, "grain": grain, "as_of": None,
            "refresh": "; ".join(view.get("refresh_jobs", [])) or "Unknown (no pg_cron job visible)",
            "dimensions": dimensions, "measures": measures, "attributes": [], "prompts": [], "caveats": caveats,
            "sensitivity": "internal", "relation": {"database": database, "schema": schema, "name": name}}


def draft(content: Path, views: list[str], replace: bool = False) -> list[str]:
    """Add (or with replace, regenerate) report entries for 'schema.view' or 'database:schema.view'. Returns lines."""
    exports = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (content / "inbox" / "_postgres").glob("*.json")} \
        if (content / "inbox" / "_postgres").is_dir() else {}
    if not exports:
        raise ConversionError("no PostgreSQL export yet: run postgres-catalog first")
    target = content / "contracts" / "sources" / "postgresql.json"
    contract: dict[str, Any] = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else \
        {"contract_version": 1, "system": SYSTEM, "folders": [], "reports": []}
    lines = []
    for wanted in views:
        database, _, qualified = wanted.rpartition(":")
        candidates = [(db, v) for db, export in exports.items() for v in export["materialized_views"]
                      if f"{v['schema']}.{v['name']}" == qualified and database in ("", db)]
        if not candidates:
            raise ConversionError(f"{wanted} is not in the export (names look like bi_reporting.sell_in_amt_mv; prefix "
                                  "database: when two databases share a name)")
        if len(candidates) > 1:
            raise ConversionError(f"{wanted} exists in several databases ({', '.join(db for db, _ in candidates)}): "
                                  "write database:schema.view")
        database, view = candidates[0]
        exported = exports[database].get("exported", "")
        entry = draft_report(content, database, view, exported)
        existing = next((i for i, r in enumerate(contract["reports"]) if r.get("relation", {}) == entry["relation"]), None)
        if existing is not None and not replace:
            lines.append(f"kept   {entry['id']} (already in the catalog; --replace regenerates it)")
            continue
        if existing is not None:
            contract["reports"][existing] = entry
        else:
            contract["reports"].append(entry)
        folder_id = entry["folder"]
        if not any(f["id"] == folder_id for f in contract["folders"]):
            contract["folders"].append({"id": folder_id, "name": f"{database} / {view['schema']}", "parent": None})
        uncertain = sum(1 for c in entry["caveats"] if c.startswith("UNCERTAIN"))
        lines.append(f"{'updated' if existing is not None else 'added '} {entry['id']}: {len(entry['dimensions'])} "
                     f"dimension(s), {len(entry['measures'])} measure(s), {uncertain} UNCERTAIN choice(s)")
    SourceContract.model_validate(contract)  # the draft must load once reviewed
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines.append("Written to contracts/sources/postgresql.json. Review every UNCERTAIN caveat against the dataset notes, "
                 "then run validate.")
    return lines


def sample(content: Path, settings: PgSettings, report_id: str, filters: list[str], group_by: list[str] | None,
           measures: list[str] | None, limit: int, source: PostgresSource | None = None) -> str:
    """Run a report's query exactly as Wizard would and show the result, for comparison with a trusted number."""
    path = content / "contracts" / "sources" / "postgresql.json"
    if not path.is_file():
        raise ConversionError("no contracts/sources/postgresql.json yet: run postgres-contract first")
    contract = SourceContract.model_validate(json.loads(path.read_text(encoding="utf-8")))
    report = next((r for r in contract.reports if r.id == report_id), None)
    if report is None:
        raise ConversionError(f"no report {report_id}; ids: {', '.join(r.id for r in contract.reports)}")
    parsed = []
    for text in filters:
        field, _, values = text.partition("=")
        if not values:
            raise ConversionError(f"filter '{text}' must look like market=EG,SA")
        parsed.append(Filter(field.strip(), [v.strip() for v in values.split(",") if v.strip()]))
    live = source or PostgresSource(settings)
    try:
        result = live.run(report, filters=parsed, group_by=group_by, measures=measures, sort=None, limit=limit,
                          allowed_markets=None)
    except SourceError as error:
        raise ConversionError(f"{error.code}: {error.message}") from None
    header = [c["key"] + (f" ({c['unit']})" if c.get("unit") else "") for c in result.columns]
    lines = [f"Report {report.id} ({report.name}) · {result.data_mode}: {result.verification}",
             f"Retrieved {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · data as of {result.as_of or 'unknown'} · "
             f"{result.total_rows} row(s){' (showing ' + str(len(result.rows)) + ')' if result.truncated else ''}", "",
             markdown_table([header, *[["" if v is None else str(v) for v in row] for row in result.rows]])]
    lines += [f"Warning: {w}" for w in result.warnings]
    lines.append("Compare a number here with the same filters in a report you trust. If it matches, record the parity "
                 "(task 19); if not, the report entry or the view needs a closer look.")
    return "\n".join(lines)
