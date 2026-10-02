"""Write the SYNTHETIC golden answers in fixtures/goldens (hand-specified values, independently re-derived by verify_spec.py).

The numbers below are the reference answers a reviewer expects from the synthetic fixtures. They are deliberately typed
out rather than computed here; scripts/verify_spec.py recomputes them from the CSV files with separate code. Corporate
reference answers are NOT stored in Git (they live in the approved private location, Step 04)."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "goldens"

CEO = {
    "id": "ceo-investment-efficiency-2026Q3", "data_mode": "SYNTHETIC", "story": "Executive",
    "question": "Which market gave us the best return on marketing investment last quarter — tie NERP spend to sell-through, "
                "share gain, and competitive switching, and rank them.",
    "period": "2026-Q3", "baseline": "2026-Q2",
    "metric": {"id": "investment-efficiency-proxy", "label": "Investment-efficiency proxy (not ROI)",
               "formula": "(sell_out_units[Q3] - sell_out_units[Q2]) / (spend_usd[Q3] / 1e6)", "unit": "extra units per USD 1M"},
    "ranking": [
        {"rank": 1, "market": "EG", "proxy": 14666.67, "spend_usd": 1500000, "sell_out_q2": 240000, "sell_out_q3": 262000,
         "share_gain_pp": 1.6, "observed_switchers_apple_xiaomi": 7300, "coverage_pct": 48.0},
        {"rank": 2, "market": "SA", "proxy": 10000.0, "spend_usd": 4200000, "sell_out_q2": 410000, "sell_out_q3": 452000,
         "share_gain_pp": 0.8, "observed_switchers_apple_xiaomi": 18400, "coverage_pct": 62.0},
        {"rank": 3, "market": "AE", "proxy": 9615.38, "spend_usd": 2600000, "sell_out_q2": 180000, "sell_out_q3": 205000,
         "share_gain_pp": -0.3, "observed_switchers_apple_xiaomi": 11900, "coverage_pct": 71.0},
    ],
    "not_ranked": [{"market": "MA", "reason": "No NERP marketing spend posted for 2026-Q3 (missing, not zero)",
                    "sell_out_q2": 95000, "sell_out_q3": 101000, "share_gain_pp": 0.4, "observed_switchers_apple_xiaomi": 2100}],
    "rubric": {
        "must_include": ["the result is a proxy, not proven ROI", "MA cannot be ranked because spend is missing",
                         "share gain and switching shown separately", "switching coverage differs by market"],
        "must_not": ["call the result ROI or proven return", "impute MA spend", "sum share percentages across markets"],
    },
}

PLANNER = {
    "id": "planner-sell-in-vs-sell-out-2026Q3", "data_mode": "SYNTHETIC", "story": "Planner", "period": "2026-Q3",
    "question": "Flag any model where sell-in is outpacing sell-out and installed-base growth is stalling — then check Smart "
                "Switch and app usage to tell me if it's a demand problem or a channel-stuffing problem.",
    "cases": [
        {"market": "EG", "model_code": "A37", "reading": "concerning", "sell_in": 97463, "sell_out": 62880, "stock_jun": 24092,
         "stock_sep": 58675, "installed_base_growth_q3_pct": -0.5, "installed_base_growth_q2_pct": 4.2,
         "activations": 45274, "d30_active_rate_sep_pct": 61.0},
        {"market": "AE", "model_code": "ZFL8", "reading": "launch fill", "sell_in": 20295, "sell_out": 12300, "stock_jun": 0,
         "stock_sep": 7995, "activations": 12054, "d30_active_rate_sep_pct": 93.0},
        {"market": "SA", "model_code": "A57", "reading": "contradictory", "sell_in": 120594, "sell_out": 103960, "stock_jun": 36620,
         "stock_sep": 53254, "installed_base_growth_q3_pct": 4.5, "installed_base_growth_q2_pct": 4.2, "activations": 102920},
        {"market": "MA", "model_code": "A17", "reading": "missing feed", "sell_in": 29997, "sell_out": 22220, "stock_jun": 8267,
         "stock_sep": 16044, "app_engagement_rows_q3": 0},
        {"market": "SA", "model_code": "S26U", "reading": "healthy", "sell_in": 54783, "sell_out": 54240},
    ],
    "rubric": {
        "must_include": ["screening result, not a diagnosis", "EG A37 combines loading with stalling installed base",
                         "MA app feed missing is not weak demand", "SA A57 signals conflict"],
        "must_not": ["state channel stuffing as a fact", "treat missing app data as zero"],
    },
}

CONQUEST = {
    "id": "conquest-switchers-2026Q3", "data_mode": "SYNTHETIC", "story": "Conquest", "period": "2026-Q3",
    "question": "Where are we winning switchers from Apple and Xiaomi according to Smart Switch, and does our investment and "
                "sell-out data support doubling down there?",
    "markets": [
        {"market": "SA", "apple": 12100, "xiaomi": 6300, "total_q3": 18400, "total_q2": 16700, "opted_in_q3": 273122,
         "per_1000_observed": 67.4, "conquest_spend_q3": 1050000},
        {"market": "AE", "apple": 9400, "xiaomi": 2500, "total_q3": 11900, "total_q2": 11700, "opted_in_q3": 141270,
         "per_1000_observed": 84.2, "conquest_spend_q3": 650000},
        {"market": "EG", "apple": 2900, "xiaomi": 4400, "total_q3": 7300, "total_q2": 6000, "opted_in_q3": 114442,
         "per_1000_observed": 63.8, "conquest_spend_q3": 375000},
        {"market": "MA", "apple": 900, "xiaomi": 1200, "total_q3": 2100, "total_q2": 1950, "opted_in_q3": 39188,
         "per_1000_observed": 53.6, "conquest_spend_q3": None},
    ],
    "rubric": {
        "must_include": ["counts are observed (lower bound)", "coverage differs by market",
                         "doubling down is a decision to investigate without incremental economics"],
        "must_not": ["call observed switchers all switchers", "equate correlation with marketing return"],
    },
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for golden in (CEO, PLANNER, CONQUEST):
        (OUT / f"{golden['id']}.json").write_text(json.dumps(golden, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                                 newline="\n")
    print(f"Wrote 3 goldens to {OUT}")


if __name__ == "__main__":
    main()
