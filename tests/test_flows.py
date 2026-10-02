"""Pure market-flow math: CFTC positioning by trader class, ETF creation flows, money fund cash, short volume ratios."""
from __future__ import annotations

from second_opinion import flows


def _cot_row(date: str, oi: int, am_long: int, am_short: int, lev_long: int, lev_short: int, small_long: int = 100, small_short: int = 50, code: str = "13874A", name: str = "E-MINI S&P 500") -> dict:
    return {
        "report_date_as_yyyy_mm_dd": f"{date}T00:00:00.000",
        "cftc_contract_market_code": code,
        "contract_market_name": name,
        "open_interest_all": str(oi),
        "change_in_open_interest_all": "10",
        "dealer_positions_long_all": "300", "dealer_positions_short_all": "900",
        "change_in_dealer_long_all": "1", "change_in_dealer_short_all": "-2",
        "asset_mgr_positions_long": str(am_long), "asset_mgr_positions_short": str(am_short),
        "change_in_asset_mgr_long": "5", "change_in_asset_mgr_short": "3",
        "lev_money_positions_long": str(lev_long), "lev_money_positions_short": str(lev_short),
        "change_in_lev_money_long": "-4", "change_in_lev_money_short": "6",
        "other_rept_positions_long": "10", "other_rept_positions_short": "20",
        "change_in_other_rept_long": "0", "change_in_other_rept_short": "0",
        "nonrept_positions_long_all": str(small_long), "nonrept_positions_short_all": str(small_short),
        "change_in_nonrept_long_all": "7", "change_in_nonrept_short_all": "-1",
    }


def test_cot_summary_nets_each_trader_class_and_ranks_the_latest_week() -> None:
    rows = [
        _cot_row("2026-09-08", 2000, 1100, 200, 150, 500),   # latest: AM net +900, lev net -350
        _cot_row("2026-09-01", 1990, 1000, 300, 200, 400),   # AM net +700, lev net -200
        _cot_row("2026-08-25", 1980, 900, 400, 250, 300),    # AM net +500, lev net -50
    ]
    out = flows.cot_summary({"13874A": rows})
    es = out[0]
    assert es["code"] == "13874A" and es["name"] == "E-MINI S&P 500" and es["label"] == "S&P 500 e-mini" and es["group"] == "index"
    assert es["report_date"] == "2026-09-08" and es["open_interest"] == 2000 and es["open_interest_change"] == 10 and es["weeks"] == 3
    am = es["classes"]["asset_managers"]
    assert am == {"long": 1100, "short": 200, "net": 900, "net_change": 200, "net_pct_oi": 45.0, "percentile": 100.0, "long_change": 5, "short_change": 3}
    lev = es["classes"]["leveraged_funds"]
    assert lev["net"] == -350 and lev["net_change"] == -150 and lev["percentile"] == 0.0
    assert es["classes"]["small_traders"]["net"] == 50 and es["classes"]["dealers"]["net"] == -600 and es["classes"]["other_reportables"]["net"] == -10


def test_cot_summary_tolerates_a_single_week_and_unknown_codes() -> None:
    out = flows.cot_summary({"ZZZZ": [_cot_row("2026-09-08", 100, 60, 10, 5, 20, code="ZZZZ", name="MYSTERY FUTURE")]})
    assert out[0]["label"] == "MYSTERY FUTURE" and out[0]["group"] == "other" and out[0]["weeks"] == 1
    assert out[0]["classes"]["asset_managers"]["net_change"] is None and out[0]["classes"]["asset_managers"]["percentile"] is None


def test_cot_summary_orders_by_group_then_label_and_skips_empty() -> None:
    out = flows.cot_summary({"13874I": [_cot_row("2026-09-08", 10, 5, 1, 1, 2, code="13874I", name="E-MINI S&P TECHNOLOGY INDEX")], "13874A": [_cot_row("2026-09-08", 10, 5, 1, 1, 2)], "098662": []})
    assert [c["code"] for c in out] == ["13874A", "13874I"]


def test_etf_flow_summary_derives_flows_from_share_count_changes() -> None:
    series = {
        "XLK": [
            {"date": "2026-09-08", "nav": 180.0, "aum_usd": 180_000_000.0, "shares": 1_000_000},
            {"date": "2026-09-09", "nav": 182.0, "aum_usd": 184_730_000.0, "shares": 1_015_000},
            {"date": "2026-09-10", "nav": 181.0, "aum_usd": 182_810_000.0, "shares": 1_010_000},
            {"date": "2026-09-11", "nav": 185.0, "aum_usd": 190_550_000.0, "shares": 1_030_000},
        ],
        "XLE": [{"date": "2026-09-11", "nav": 65.0, "aum_usd": 65_000_000.0, "shares": 1_000_000}],
    }
    out = flows.etf_flow_summary(series)
    xlk = next(r for r in out if r["ticker"] == "XLK")
    assert xlk["name"] == "Technology" and xlk["as_of"] == "2026-09-11" and xlk["shares"] == 1_030_000 and xlk["observations"] == 4
    assert xlk["flow_1d_usd"] == 20_000 * 185.0
    assert xlk["flow_5d_usd"] == 15_000 * 182.0 - 5_000 * 181.0 + 20_000 * 185.0
    assert xlk["flow_5d_pct_aum"] == round(xlk["flow_5d_usd"] / 190_550_000.0 * 100, 2)
    assert xlk["flow_20d_usd"] == xlk["flow_5d_usd"] and xlk["flow_1d_pct_aum"] == round(20_000 * 185.0 / 190_550_000.0 * 100, 2)
    xle = next(r for r in out if r["ticker"] == "XLE")
    assert xle["observations"] == 1 and xle["flow_1d_usd"] is None and xle["flow_5d_usd"] is None and xle["flow_20d_usd"] is None
    assert [r["ticker"] for r in out] == ["XLK", "XLE"]  # flows first, then unknowns


def test_etf_flow_summary_uses_the_span_of_observations_not_calendar_days() -> None:
    series = {"SPY": [{"date": "2026-08-01", "nav": 700.0, "aum_usd": 7e11, "shares": 1_000_000_000}, {"date": "2026-09-11", "nav": 760.0, "aum_usd": 7.6e11 + 7.6e8, "shares": 1_001_000_000}]}
    out = flows.etf_flow_summary(series)
    assert out[0]["flow_1d_usd"] == 1_000_000 * 760.0 and out[0]["first_observation"] == "2026-08-01" and out[0]["flow_1d_span_days"] == 41


def test_cash_summary_reports_changes_over_one_four_thirteen_and_fifty_two_weeks() -> None:
    from datetime import date, timedelta

    start = date(2025, 9, 1)
    obs = [{"date": (start + timedelta(weeks=i)).isoformat(), "value": 2500.0 + i} for i in range(53)]  # weekly, oldest first
    out = flows.cash_summary("WRMFNS", obs)
    assert out["series"] == "WRMFNS" and out["name"] == "Retail Money Market Funds" and out["unit"] == "billions of dollars, weekly"
    assert out["latest"] == 2552.0 and out["date"] == (start + timedelta(weeks=52)).isoformat()
    assert out["change_1w"] == 1.0 and out["change_4w"] == 4.0 and out["change_13w"] == 13.0 and out["change_52w"] == 52.0
    assert out["change_52w_pct"] == round((2552.0 / 2500.0 - 1) * 100, 2)
    assert "change_1m" not in out


def test_cash_summary_with_short_history_leaves_missing_changes_null() -> None:
    out = flows.cash_summary("WRMFNS", [{"date": "2026-08-01", "value": 3000.0}, {"date": "2026-08-08", "value": 3010.0}])
    assert out["change_1w"] == 10.0 and out["change_4w"] is None and out["change_13w"] is None and out["change_52w"] is None


def test_short_volume_summary_ratios_and_averages() -> None:
    rows = {"AAPL": [{"date": "2026-09-08", "short": 400.0, "total": 1000.0}, {"date": "2026-09-09", "short": 500.0, "total": 1000.0}, {"date": "2026-09-10", "short": 600.0, "total": 1000.0}], "ZZZ": []}
    out = flows.short_volume_summary(rows)
    aapl = out[0]
    assert aapl["symbol"] == "AAPL" and aapl["date"] == "2026-09-10" and aapl["short_ratio"] == 60.0 and aapl["short_ratio_avg"] == 50.0 and aapl["days"] == 3
    assert aapl["short_volume"] == 600.0 and aapl["total_volume"] == 1000.0 and aapl["ratio_vs_avg"] == 10.0
    assert out[1] == {"symbol": "ZZZ", "date": None, "short_ratio": None, "short_ratio_avg": None, "ratio_vs_avg": None, "short_volume": None, "total_volume": None, "days": 0}


def test_cot_summary_marks_contracts_reported_behind_the_newest_week() -> None:
    out = flows.cot_summary({
        "13874A": [_cot_row("2026-09-08", 10, 5, 1, 1, 2)],
        "13874R": [_cot_row("2025-09-16", 10, 5, 1, 1, 2, code="13874R", name="E-MINI S&P REAL ESTATE INDEX")],
        "138747": [_cot_row("2026-09-01", 10, 5, 1, 1, 2, code="138747", name="E-MINI S&P CONSUMER DISC INDEX")],
    })
    by = {c["code"]: c for c in out}
    assert by["13874A"]["weeks_behind"] == 0 and by["138747"]["weeks_behind"] == 1 and by["13874R"]["weeks_behind"] == 51


def test_cot_summary_history_lists_weekly_nets_oldest_first_when_asked() -> None:
    rows = [_cot_row("2026-09-08", 2000, 1100, 200, 150, 500), _cot_row("2026-09-01", 1990, 1000, 300, 200, 400)]
    assert "history" not in flows.cot_summary({"13874A": rows})[0]
    out = flows.cot_summary({"13874A": rows}, history=True)[0]
    assert out["history"] == [
        {"date": "2026-09-01", "open_interest": 1990, "asset_managers": 700, "leveraged_funds": -200, "dealers": -600, "other_reportables": -10, "small_traders": 50},
        {"date": "2026-09-08", "open_interest": 2000, "asset_managers": 900, "leveraged_funds": -350, "dealers": -600, "other_reportables": -10, "small_traders": 50},
    ]


def test_cash_summary_carries_its_observations_for_charting() -> None:
    out = flows.cash_summary("WRMFNS", [{"date": "2026-09-01", "value": 3010.0}, {"date": "2026-08-01", "value": 3000.0}])
    assert out["observations"] == [{"date": "2026-08-01", "value": 3000.0}, {"date": "2026-09-01", "value": 3010.0}]
