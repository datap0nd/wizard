from __future__ import annotations

import pytest

from wizard_checks.calc import CalcError, evaluate
from wizard_connectors.fixture_source import FixtureSource

SPEND = {"report_id": "nerp-mkt-spend-quarterly", "filters": [{"field": "fiscal_quarter", "values": ["2026-Q2", "2026-Q3"]}],
         "group_by": ["market", "fiscal_quarter"], "measures": ["spend_usd"]}
SELL_OUT = {"report_id": "gscm-sell-through-quarterly", "filters": [{"field": "fiscal_quarter", "values": ["2026-Q2", "2026-Q3"]}],
            "measures": ["sell_out_units"]}


def where(market, quarter):
    return [{"field": "market", "values": [market]}, {"field": "fiscal_quarter", "values": [quarter]}]


@pytest.fixture
def ctx(registry, context):
    c = context()
    assert registry.execute("nerp_run_report", SPEND, c).ok
    assert registry.execute("gscm_run_report", SELL_OUT, c).ok
    return c


def check(registry, ctx, claims, replay=()):
    outcome = registry.execute("wizard_check_my_data", {"claims": claims, "replay_evidence_ids": list(replay)}, ctx)
    assert outcome.ok, outcome.error_message
    return outcome.data


def test_correct_direct_and_derived_figures_match(registry, ctx):
    result = check(registry, ctx, [
        {"label": "EG Q3 spend", "stated_value": 1500000, "evidence_id": "E1", "measure": "spend_usd", "where": where("EG", "2026-Q3")},
        {"label": "EG proxy", "stated_value": 14667, "expression": "(q3 - q2) / (s / 1000000)", "inputs": [
            {"name": "q3", "evidence_id": "E2", "measure": "sell_out_units", "where": where("EG", "2026-Q3"), "period": "2026-Q3"},
            {"name": "q2", "evidence_id": "E2", "measure": "sell_out_units", "where": where("EG", "2026-Q2"), "period": "2026-Q2"},
            {"name": "s", "evidence_id": "E1", "measure": "spend_usd", "where": where("EG", "2026-Q3"), "period": "2026-Q3"}]},
    ], replay=["E1", "E2"])
    assert result["overall"] == "CHECKED"
    assert [c["status"] for c in result["claims"]] == ["MATCH", "MATCH"]
    assert [r["status"] for r in result["replays"]] == ["UNCHANGED", "UNCHANGED"]
    assert ctx.recorder.checks and ctx.recorder.checks[-1]["overall"] == "CHECKED"


def test_altered_figure_is_a_discrepancy(registry, ctx):
    result = check(registry, ctx, [{"label": "SA Q3 spend", "stated_value": 4300000, "evidence_id": "E1",
                                    "measure": "spend_usd", "where": where("SA", "2026-Q3")}])
    assert result["overall"] == "DISCREPANCY"
    assert result["claims"][0]["status"] == "DISCREPANCY" and result["claims"][0]["recomputed_value"] == 4200000


def test_mismatched_period_is_reported(registry, ctx):
    result = check(registry, ctx, [{"label": "AE Q3 spend", "stated_value": 2400000, "evidence_id": "E1", "measure": "spend_usd",
                                    "where": where("AE", "2026-Q2"), "period": "2026-Q3"}])
    assert result["claims"][0]["status"] == "PERIOD_MISMATCH" and result["overall"] == "DISCREPANCY"


def test_incomplete_quarter_is_reported(registry, context):
    c = context()
    registry.execute("asap_run_report", {"report_id": "asap-smartswitch-transfers", "filters": [
        {"field": "month", "values": ["2026-07", "2026-08"]}, {"field": "market", "values": ["SA"]}]}, c)
    result = check(registry, c, [{"label": "SA Q3 switchers", "stated_value": 1, "evidence_id": "E1", "measure": "transfers",
                                  "period": "2026-Q3"}])
    assert result["claims"][0]["status"] == "PERIOD_MISMATCH" and "2026-09" in result["claims"][0]["notes"][0]


def test_unverifiable_claims_are_not_upgraded(registry, ctx):
    result = check(registry, ctx, [{"label": "MA Q3 spend", "stated_value": 0, "evidence_id": "E1", "measure": "spend_usd",
                                    "where": where("MA", "2026-Q3")},
                                   {"label": "ghost", "stated_value": 1, "evidence_id": "E9", "measure": "spend_usd"}])
    assert [c["status"] for c in result["claims"]] == ["NOT_VERIFIABLE", "NOT_VERIFIABLE"]
    assert result["overall"] == "NOT_VERIFIABLE"


def test_replay_detects_changed_source(registry, ctx, services, tmp_path):
    original = services.sources["nerp"]
    changed_root = tmp_path / "synthetic"
    (changed_root / "nerp").mkdir(parents=True)
    text = (original.root / "nerp" / "marketing_spend_quarterly.csv").read_text(encoding="utf-8")
    (changed_root / "nerp" / "marketing_spend_quarterly.csv").write_text(text.replace("1050000", "1050001"), encoding="utf-8")
    services.sources["nerp"] = FixtureSource(services.catalog, changed_root)
    try:
        result = check(registry, ctx, [], replay=["E1"])
    finally:
        services.sources["nerp"] = original
    assert result["replays"][0]["status"] == "CHANGED" and result["overall"] == "DISCREPANCY"


def test_claim_needs_one_kind(registry, ctx):
    outcome = registry.execute("wizard_check_my_data", {"claims": [{"label": "x", "stated_value": 1}]}, ctx)
    assert outcome.error_code == "invalid_arguments"


@pytest.mark.parametrize("expression", ["__import__('os')", "a.b", "open('x')", "[1]", "lambda: 1", "2 ** 100"])
def test_calculator_rejects_unsafe_syntax(expression):
    with pytest.raises(CalcError):
        evaluate(expression, {"a": 1})


def test_calculator_basics():
    assert evaluate("round(avg(a, b) * 2, 1)", {"a": 1, "b": 2}) == 3.0
    with pytest.raises(CalcError):
        evaluate("1 / 0")
