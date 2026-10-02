from __future__ import annotations

import pytest

from wizard_connectors.fixture_source import Filter, SourceError, month_to_quarter, quarter_months


def run(services, report_id, **kwargs):
    system, report = services.catalog.report(report_id)
    defaults = {"filters": [], "group_by": None, "measures": None, "sort": None, "limit": 500, "allowed_markets": None}
    defaults.update(kwargs)
    return services.sources[system].run(report, **defaults)


def as_dicts(result):
    keys = [c["key"] for c in result.columns]
    return [dict(zip(keys, row, strict=True)) for row in result.rows]


def test_calendar_helpers():
    assert month_to_quarter("2026-07") == "2026-Q3"
    assert quarter_months("2026-Q3") == ["2026-07", "2026-08", "2026-09"]


def test_sum_grouping_matches_quarterly_report(services):
    monthly = as_dicts(run(services, "gscm-sell-in-sell-out-monthly", filters=[Filter("fiscal_quarter", ["2026-Q3"])],
                           group_by=["market"], measures=["sell_out_units"]))
    quarterly = as_dicts(run(services, "gscm-sell-through-quarterly", filters=[Filter("fiscal_quarter", ["2026-Q3"])]))
    assert {r["market"]: r["sell_out_units"] for r in monthly} == {r["market"]: r["sell_out_units"] for r in quarterly}
    assert {r["market"]: r["sell_out_units"] for r in monthly} == {"AE": 205000, "EG": 262000, "MA": 101000, "SA": 452000}


def test_period_end_balance_is_not_summed_over_months(services):
    result = run(services, "gscm-sell-in-sell-out-monthly",
                 filters=[Filter("fiscal_quarter", ["2026-Q3"]), Filter("market", ["EG"]), Filter("model_code", ["A37"])],
                 group_by=["market", "model_code"], measures=["channel_stock_units"])
    assert as_dicts(result) == [{"market": "EG", "model_code": "A37", "channel_stock_units": 58675}]
    assert any("period-end balance" in w for w in result.warnings)


def test_rates_are_not_aggregated(services):
    result = run(services, "asap-share-quarterly", filters=[Filter("fiscal_quarter", ["2026-Q3"])], group_by=["fiscal_quarter"],
                 measures=["volume_share_pct"])
    assert as_dicts(result)[0]["volume_share_pct"] is None
    assert any("cannot be aggregated" in w for w in result.warnings)


def test_missing_rows_are_flagged_not_zero(services):
    result = run(services, "nerp-mkt-spend-quarterly", filters=[Filter("market", ["MA"]), Filter("fiscal_quarter", ["2026-Q3"])])
    assert result.total_rows == 0
    assert any("not a value of zero" in w for w in result.warnings)


def test_market_scope_limits_rows_and_says_so(services):
    result = run(services, "nerp-mkt-spend-quarterly", filters=[Filter("market", ["SA", "EG"])], group_by=["market"],
                 measures=["spend_usd"], allowed_markets={"SA", "AE"})
    assert [r["market"] for r in as_dicts(result)] == ["SA"]
    assert "EG" in (result.access_note or "")
    assert not any("EG" in w for w in result.warnings), "a denied market must not be reported as missing data"


def test_navigation_only_report_has_no_rows(services):
    with pytest.raises(SourceError) as error:
        run(services, "asap-exec-dossier")
    assert error.value.code == "navigation_only"


def test_invalid_filter_field(services):
    with pytest.raises(SourceError) as error:
        run(services, "nerp-mkt-spend-quarterly", filters=[Filter("password", ["x"])])
    assert error.value.code == "invalid_filter"


def test_limit_is_capped_and_digest_covers_all_rows(services):
    small = run(services, "asap-smartswitch-transfers", limit=10)
    large = run(services, "asap-smartswitch-transfers", limit=10_000)
    assert small.truncated and len(small.rows) == 10 and small.total_rows == 540
    assert len(large.rows) == 500 and large.truncated
    assert small.digest == large.digest
