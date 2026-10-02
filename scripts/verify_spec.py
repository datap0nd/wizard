"""Specification and fixture gate (runs on every PR; no model, no network).

Checks, independently of the application code (this file imports nothing from services/):
  1. synthetic fixtures match their manifest and generator, and are labelled SYNTHETIC everywhere
  2. source contracts validate against contracts/source-contract.schema.json and match the CSV headers
  3. golden answers recompute from the raw CSV rows with separate arithmetic (ranking, missing-spend market, screens)
  4. replay transcripts only use published tools and known report ids, and never claim ROI
  5. knowledge notes carry an approval status; metric/measure naming is consistent
  6. relative links in Markdown documentation resolve
Usage: python scripts/verify_spec.py"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "fixtures" / "synthetic"
failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def rows(name: str) -> list[dict[str, str]]:
    with (SYN / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def quarter(month: str) -> str:
    return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"


def close(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(a - b) <= tol


def fixtures_and_labels() -> None:
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_fixtures.py"), "--check"], capture_output=True, text=True)
    check(result.returncode == 0, f"fixtures differ from generator: {result.stdout.strip()}")
    manifest = json.loads((SYN / "manifest.json").read_text(encoding="utf-8"))
    check(manifest.get("data_mode") == "SYNTHETIC", "fixture manifest must say SYNTHETIC")
    identities = json.loads((ROOT / "fixtures" / "identities.json").read_text(encoding="utf-8"))
    check(identities.get("data_mode") == "SYNTHETIC", "identities must be labelled SYNTHETIC")
    for path in (ROOT / "fixtures" / "goldens").glob("*.json"):
        check(json.loads(path.read_text(encoding="utf-8")).get("data_mode") == "SYNTHETIC", f"{path.name} must be SYNTHETIC")
    for path in (ROOT / "fixtures" / "transcripts").glob("*.json"):
        check(json.loads(path.read_text(encoding="utf-8")).get("data_mode") == "SYNTHETIC", f"{path.name} must be SYNTHETIC")


def contracts() -> dict[str, dict]:
    try:
        import jsonschema
    except ImportError:
        failures.append("jsonschema is not installed (uv sync): source contracts could not be validated")
        jsonschema = None
    schema = json.loads((ROOT / "contracts" / "source-contract.schema.json").read_text(encoding="utf-8"))
    reports: dict[str, dict] = {}
    for path in sorted((ROOT / "contracts" / "sources").glob("*.json")):
        contract = json.loads(path.read_text(encoding="utf-8"))
        if jsonschema:
            try:
                jsonschema.validate(contract, schema)
            except jsonschema.ValidationError as error:
                failures.append(f"{path.name}: {error.message}")
        check(contract["system"]["connector"]["data_mode"] == "SYNTHETIC" or path.name.endswith(".live.json"),
              f"{path.name}: a *.synthetic.json contract must use data mode SYNTHETIC")
        for report in contract["reports"]:
            reports[report["id"]] = report
            columns = [c["key"] for c in (*report["dimensions"], *report["measures"], *report["attributes"])]
            for measure in report["measures"]:
                check(re.fullmatch(r"[a-z][a-z0-9_]*", measure["key"]) is not None, f"{report['id']}: bad measure key {measure['key']}")
                if measure["type"] in ("currency", "percent"):
                    check(bool(measure.get("unit")), f"{report['id']}.{measure['key']}: currency/percent needs a unit")
                if measure["type"] == "percent":
                    check(measure["aggregation"] == "none", f"{report['id']}.{measure['key']}: a percentage must not be summed")
            if report["row_access"] == "ROWS":
                check(bool(report["file"]) and (SYN / report["file"]).is_file(), f"{report['id']}: fixture file missing")
                if report["file"] and (SYN / report["file"]).is_file():
                    header = (SYN / report["file"]).read_text(encoding="utf-8").splitlines()[0].split(",")
                    check(sorted(header) == sorted(columns), f"{report['id']}: contract columns {columns} != CSV header {header}")
            else:
                check(report["file"] is None, f"{report['id']}: navigation-only report must not have rows")
    return reports


def goldens() -> None:
    golden = json.loads((ROOT / "fixtures" / "goldens" / "ceo-investment-efficiency-2026Q3.json").read_text(encoding="utf-8"))
    spend: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows("nerp/marketing_spend_quarterly.csv"):
        spend[(r["market"], r["fiscal_quarter"])] += int(r["spend_usd"])
    sell_out: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows("gscm/sell_in_sell_out_monthly.csv"):
        sell_out[(r["market"], quarter(r["month"]))] += int(r["sell_out_units"])
    share = {(r["market"], r["fiscal_quarter"]): float(r["volume_share_pct"]) for r in rows("asap/market_share_quarterly.csv")
             if r["brand"] == "Samsung"}
    switchers: dict[str, int] = defaultdict(int)
    for r in rows("asap/smartswitch_transfers_monthly.csv"):
        if quarter(r["month"]) == "2026-Q3" and r["origin_brand"] in ("Apple", "Xiaomi"):
            switchers[r["market"]] += int(r["transfers"])
    acts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows("asap/smartswitch_coverage_monthly.csv"):
        if quarter(r["month"]) == "2026-Q3":
            acts[r["market"]][0] += int(r["new_activations"])
            acts[r["market"]][1] += int(r["opted_in_devices"])
    ranked = []
    for market in ("SA", "AE", "EG", "MA"):
        if (market, "2026-Q3") not in spend:
            check(market in [m["market"] for m in golden["not_ranked"]], f"{market} has no Q3 spend but is not marked unranked")
            continue
        proxy = (sell_out[(market, "2026-Q3")] - sell_out[(market, "2026-Q2")]) / (spend[(market, "2026-Q3")] / 1e6)
        ranked.append((proxy, market))
    ranked.sort(reverse=True)
    check([m for _, m in ranked] == [r["market"] for r in golden["ranking"]], f"CEO ranking differs: {ranked}")
    for entry in golden["ranking"]:
        m = entry["market"]
        proxy = (sell_out[(m, "2026-Q3")] - sell_out[(m, "2026-Q2")]) / (spend[(m, "2026-Q3")] / 1e6)
        check(close(proxy, entry["proxy"], 0.01), f"CEO proxy {m}: {proxy} != {entry['proxy']}")
        check(spend[(m, "2026-Q3")] == entry["spend_usd"], f"CEO spend {m}")
        check(sell_out[(m, "2026-Q2")] == entry["sell_out_q2"] and sell_out[(m, "2026-Q3")] == entry["sell_out_q3"], f"CEO sell-out {m}")
        check(close(share[(m, "2026-Q3")] - share[(m, "2026-Q2")], entry["share_gain_pp"]), f"CEO share gain {m}")
        check(switchers[m] == entry["observed_switchers_apple_xiaomi"], f"CEO switchers {m}")
        check(close(100 * acts[m][1] / acts[m][0], entry["coverage_pct"], 0.1), f"CEO coverage {m}")

    planner = json.loads((ROOT / "fixtures" / "goldens" / "planner-sell-in-vs-sell-out-2026Q3.json").read_text(encoding="utf-8"))
    flow: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    stock: dict[tuple[str, str, str], int] = {}
    for r in rows("gscm/sell_in_sell_out_monthly.csv"):
        if quarter(r["month"]) == "2026-Q3":
            flow[(r["market"], r["model_code"])][0] += int(r["sell_in_units"])
            flow[(r["market"], r["model_code"])][1] += int(r["sell_out_units"])
        stock[(r["market"], r["model_code"], r["month"])] = int(r["channel_stock_units"])
    base = {(r["market"], r["model_code"], r["month"]): int(r["active_devices"]) for r in rows("asap/installed_base_monthly.csv")}
    app = [r for r in rows("asap/app_engagement_monthly.csv") if quarter(r["month"]) == "2026-Q3"]
    for case in planner["cases"]:
        key = (case["market"], case["model_code"])
        check(flow[key] == [case["sell_in"], case["sell_out"]], f"planner flow {key}: {flow[key]}")
        if "stock_sep" in case:
            check(stock.get((*key, "2026-09")) == case["stock_sep"], f"planner stock {key}")
            check(stock.get((*key, "2026-06"), 0) == case["stock_jun"], f"planner June stock {key}")
        if "installed_base_growth_q3_pct" in case:
            growth = 100 * (base[(*key, "2026-09")] - base[(*key, "2026-06")]) / base[(*key, "2026-06")]
            check(close(growth, case["installed_base_growth_q3_pct"]), f"planner IB growth {key}: {growth:.2f}")
        if "app_engagement_rows_q3" in case:
            check(sum(1 for r in app if r["market"] == key[0]) == case["app_engagement_rows_q3"], f"planner missing feed {key}")
    concerning = [c for c in planner["cases"] if c["reading"] == "concerning"]
    check(len(concerning) == 1 and concerning[0]["sell_in"] / concerning[0]["sell_out"] > 1.5, "planner needs one clear screen")

    conquest = json.loads((ROOT / "fixtures" / "goldens" / "conquest-switchers-2026Q3.json").read_text(encoding="utf-8"))
    by_origin: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in rows("asap/smartswitch_transfers_monthly.csv"):
        by_origin[(r["market"], quarter(r["month"]), r["origin_brand"])] += int(r["transfers"])
    campaign = {(r["market"], r["fiscal_quarter"]): int(r["spend_usd"]) for r in rows("nerp/campaigns.csv") if r["objective"] == "Conquest"}
    for entry in conquest["markets"]:
        m = entry["market"]
        check(by_origin[(m, "2026-Q3", "Apple")] == entry["apple"] and by_origin[(m, "2026-Q3", "Xiaomi")] == entry["xiaomi"],
              f"conquest origins {m}")
        q2 = by_origin[(m, "2026-Q2", "Apple")] + by_origin[(m, "2026-Q2", "Xiaomi")]
        check(q2 == entry["total_q2"], f"conquest Q2 {m}")
        check(acts[m][1] == entry["opted_in_q3"], f"conquest opted-in {m}")
        check(close(1000 * entry["total_q3"] / acts[m][1], entry["per_1000_observed"]), f"conquest rate {m}")
        check(campaign.get((m, "2026-Q3")) == entry["conquest_spend_q3"], f"conquest spend {m}")


def transcripts(reports: dict[str, dict]) -> None:
    catalog = json.loads((ROOT / "contracts" / "tool-catalog.json").read_text(encoding="utf-8"))
    tools = {t["name"] for t in catalog["tools"]}
    for path in sorted((ROOT / "fixtures" / "transcripts").glob("*.json")):
        transcript = json.loads(path.read_text(encoding="utf-8"))
        for step in transcript["steps"]:
            if "tool" in step:
                check(step["tool"] in tools, f"{path.name}: unknown tool {step['tool']}")
                report_id = step.get("args", {}).get("report_id")
                if report_id:
                    check(report_id in reports, f"{path.name}: unknown report {report_id}")
            text = step.get("answer", "")
            check(not re.search(r"\bROI (is|of|was)\b|proven (ROI|return)(?! ROI)", text.replace("not proven ROI", "")),
                  f"{path.name}: answer claims ROI")


def knowledge_and_links() -> None:
    for note in (ROOT / "knowledge").rglob("*.md"):
        if note.name == "README.md":
            continue
        head = note.read_text(encoding="utf-8").split("---")
        check(len(head) >= 3 and re.search(r"^status: (DRAFT_UNSIGNED|SIGNED)$", head[1], re.M) is not None,
              f"{note.relative_to(ROOT)}: needs front matter with an approval status")
    documents = [*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md")]
    for doc in documents:
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", doc.read_text(encoding="utf-8")):
            if re.match(r"^[a-z]+:", target):
                continue
            check((doc.parent / target).exists(), f"{doc.relative_to(ROOT)}: broken link {target}")


def templates() -> None:
    copy = ROOT / "templates" / "content" / "schema" / "source-contract.schema.json"
    check(copy.is_file() and copy.read_bytes() == (ROOT / "contracts" / "source-contract.schema.json").read_bytes(),
          "templates/content/schema/source-contract.schema.json is out of sync with contracts/ (copy it again)")
    for command in (ROOT / "templates" / "content" / ".gemini" / "commands").rglob("*.toml"):
        import tomllib
        try:
            data = tomllib.loads(command.read_text(encoding="utf-8"))
            check({"description", "prompt"} <= set(data) and "{{args}}" in data["prompt"], f"{command.name}: needs description, prompt and {{{{args}}}}")
        except tomllib.TOMLDecodeError as error:
            failures.append(f"{command.name}: invalid TOML ({error})")


def main() -> int:
    fixtures_and_labels()
    templates()
    reports = contracts()
    goldens()
    transcripts(reports)
    knowledge_and_links()
    if failures:
        print("verify_spec FAILED:\n  " + "\n  ".join(failures))
        return 1
    print("verify_spec passed: fixtures, contracts, goldens, transcripts, knowledge and links are consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
