"""stock-screener: screen_math.py's metrics, criteria, presets and ranking. Pure math, no network."""
from __future__ import annotations

import pytest

from scripts_util import load_script

MATH = load_script("stock-screener/scripts/screen_math.py")
YEARS = [2022, 2023, 2024, 2025]


def _by_year(values) -> dict[str, float]:
    return {str(y): v for y, v in zip(YEARS, values) if v is not None}


def company(ticker="AAA", revenue=(1000e6, 1100e6, 1210e6, 1331e6), *, op=0.20, ni=0.12, ocf=0.22, capex=0.04,
            sbc=0.01, shares=(100e6, 100e6, 100e6, 100e6), balance=None, prior=None, quarter=None, market=None, **annual):
    """A steady 10%-a-year company; margins are shares of revenue unless a series is given."""

    def flow(v):
        return _by_year(v) if isinstance(v, (list, tuple)) else _by_year([v * r for r in revenue])

    rec = {
        "cik": abs(hash(ticker)) % 10**6, "ticker": ticker, "name": f"{ticker} Inc",
        "annual": {"revenue": _by_year(revenue), "gross_profit": flow(0.5), "operating_income": flow(op), "net_income": flow(ni),
                   "ocf": flow(ocf), "capex": flow(capex), "sbc": flow(sbc), "diluted_shares": _by_year(shares)},
        "balance": {"equity": 800e6, "debt": 200e6, "cash": 100e6, "assets": 1500e6, "current_assets": 600e6, "current_liabilities": 300e6} if balance is None else balance,
        "balance_prior": {"assets": 1400e6, "debt": 220e6, "current_assets": 500e6, "current_liabilities": 300e6} if prior is None else prior,
    }
    for k, v in annual.items():
        rec["annual"][k] = flow(v)
    if quarter is not None:
        rec["quarter"] = quarter
    if market is not None:
        rec["market"] = market
    return rec


REV = (1000e6, 1100e6, 1210e6, 1331e6)


def margins(*ms) -> list[float]:
    """Absolute figures from a margin per year on the default revenue."""
    return [m * r for m, r in zip(ms, REV)]


def screen(companies, preset=None, **criteria):
    return MATH.run_screen_math({"years": YEARS, "companies": companies, "preset": preset, "criteria": criteria})


def one(c, preset=None, **criteria):
    return screen([c], preset, **criteria)["companies"][0]


# --- capital spending -------------------------------------------------------------------------


def test_missing_capex_is_unknown_not_zero() -> None:
    row = one(company(capex=[None, None, None, None]), fcf_positive_latest=True, min_fcf_margin=0.05)
    m = row["metrics"]
    assert m["capex_reported"] is False and m["fcf_latest"] is None and m["fcf_after_sbc_norm"] is None
    assert row["failed"] == ["min_fcf_margin", "fcf_positive_latest"] and "CAPEX_NOT_REPORTED" in row["flags"]


def test_a_year_without_capex_fails_the_every_year_cash_test() -> None:
    row = one(company(capex=[40e6, None, 48e6, 53e6]), fcf_positive_all_years=True, fcf_positive_latest=True)
    assert row["failed"] == ["fcf_positive_all_years"] and row["metrics"]["capex_reported"] is True


def test_capex_sign_does_not_matter() -> None:
    assert one(company(capex=-0.04))["metrics"]["fcf_latest"] == one(company(capex=0.04))["metrics"]["fcf_latest"]


# --- normalized cash --------------------------------------------------------------------------


def test_cash_is_the_lower_of_last_year_and_the_average_margin() -> None:
    peak = one(company(ocf=margins(0.10, 0.10, 0.10, 0.50), capex=0.0, sbc=0.0))["metrics"]
    assert peak["fcf_latest"] == pytest.approx(0.50 * 1331e6)
    assert peak["fcf_norm"] == pytest.approx(0.20 * 1331e6)  # average margin (10+10+10+50)/4
    trough = one(company(ocf=margins(0.30, 0.30, 0.30, 0.10), capex=0.0, sbc=0.0))["metrics"]
    assert trough["fcf_norm"] == pytest.approx(0.10 * 1331e6)  # last year is the lower one


def test_a_cash_peak_is_flagged_and_does_not_buy_a_higher_yield() -> None:
    mkt = {"market_cap": 2e9, "enterprise_value": 2e9}
    peak = one(company(ocf=margins(0.10, 0.10, 0.10, 0.50), capex=0.0, sbc=0.0, market=mkt))
    steady = one(company(ocf=0.20, capex=0.0, sbc=0.0, market=mkt))
    assert "CASH_ABOVE_ITS_AVERAGE" in peak["flags"] and "CASH_ABOVE_ITS_AVERAGE" not in steady["flags"]
    assert peak["metrics"]["fcf_yield"] == steady["metrics"]["fcf_yield"]


# --- leverage ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "balance, interest, basis, passes",
    [
        ({"debt": 500e6, "cash": 100e6}, None, "net_debt", True),         # 400 / 266 ebit = 1.5x
        ({"debt": 1500e6, "cash": 100e6}, None, "net_debt", False),       # 5.3x
        ({"debt": 200e6, "cash": 900e6}, None, "net_debt", True),         # net cash
        ({}, 20e6, "interest_cover", True),                               # 266 / 20 = 13x
        ({}, 100e6, "interest_cover", False),                             # 2.7x
        ({}, None, "none_reported", True),                                # no debt, no interest
    ],
)
def test_leverage_uses_net_debt_then_interest_cover_then_nothing(balance, interest, basis, passes) -> None:
    c = company(balance=balance, interest_expense=[None, None, None, interest])
    row = one(c, max_net_debt_to_ebit=3.0)
    assert row["metrics"]["leverage_basis"] == basis
    assert (row["failed"] == []) is passes and row["not_reported"] == []


def test_debt_with_no_profit_to_service_it_fails() -> None:
    row = one(company(op=-0.05, balance={"debt": 500e6, "cash": 0}), max_net_debt_to_ebit=3.0)
    assert row["failed"] == ["max_net_debt_to_ebit"]


def test_negative_equity_no_longer_passes_a_debt_test_unmeasured() -> None:
    c = company(balance={"equity": -300e6, "debt": 3000e6, "cash": 50e6})
    assert one(c, "value")["failed"].count("max_net_debt_to_ebit") == 1


def test_legacy_long_term_debt_key_is_read_as_debt() -> None:
    m = one(company(balance={"equity": 1000e6, "long_term_debt": 250e6}))["metrics"]
    assert m["debt"] == 250e6 and m["debt_to_equity"] == 0.25


def test_ebit_falls_back_to_net_income_plus_tax_and_interest() -> None:
    c = company(op=[None] * 4, income_tax=[None, None, None, 40e6], interest_expense=[None, None, None, 10e6])
    m = one(c)["metrics"]
    assert m["ebit_latest"] == pytest.approx(0.12 * 1331e6 + 50e6) and m["ebit_basis"] == "net_plus_tax_and_interest"


# --- returns, liquidity, payout ---------------------------------------------------------------


def test_roce_and_current_ratio() -> None:
    m = one(company())["metrics"]
    assert m["roce"] == pytest.approx(0.20 * 1331e6 / (1500e6 - 300e6), abs=1e-4)
    assert m["current_ratio"] == 2.0 and m["working_capital"] == 300e6
    assert one(company(balance={"assets": 1500e6}), min_roce=0.1)["failed"] == ["min_roce"]  # unclassified balance sheet


def test_graham_balance_sheet_tests() -> None:
    assert one(company(), min_current_ratio=2.0, max_debt_to_working_capital=1.0)["failed"] == []
    heavy = company(balance={"debt": 400e6, "current_assets": 600e6, "current_liabilities": 300e6})
    assert one(heavy, max_debt_to_working_capital=1.0)["failed"] == ["max_debt_to_working_capital"]
    assert one(company(), min_current_ratio=2.5)["failed"] == ["min_current_ratio"]


def test_dividend_and_profit_every_year() -> None:
    payer = company(dividends=0.03)
    assert one(payer, pays_dividend_all_years=True, net_income_positive_all_years=True)["failed"] == []
    skipped = company(dividends=[30e6, None, 36e6, 40e6], ni=[0.1 * 1000e6, -5e6, 0.1 * 1210e6, 0.1 * 1331e6])
    assert one(skipped, pays_dividend_all_years=True, net_income_positive_all_years=True)["failed"] == ["net_income_positive_all_years", "pays_dividend_all_years"]


def test_payout_must_be_covered_by_free_cash_flow() -> None:
    covered = company(dividends=0.05, buybacks=[None, None, None, 100e6])  # 166.6 payout vs 239.6 fcf
    m = one(covered, max_payout_to_fcf=1.0)
    assert m["failed"] == [] and m["metrics"]["payout_latest"] == pytest.approx(0.05 * 1331e6 + 100e6)
    stretched = company(dividends=0.05, buybacks=[None, None, None, 300e6])
    assert one(stretched, max_payout_to_fcf=1.0)["failed"] == ["max_payout_to_fcf"]
    assert one(company(), max_payout_to_fcf=1.0)["failed"] == []  # pays nothing
    burning = company(ocf=0.01, dividends=0.02)
    assert one(burning, max_payout_to_fcf=1.0)["failed"] == ["max_payout_to_fcf"]  # paid with no free cash


def test_acquisitive_flag() -> None:
    assert "ACQUISITIVE" in one(company(acquisitions=0.15))["flags"]
    assert "ACQUISITIVE" not in one(company(acquisitions=0.02))["flags"]
    assert one(company())["metrics"]["acquisition_pct"] is None


# --- Piotroski --------------------------------------------------------------------------------


def test_f_score_counts_nine_improving_signals() -> None:
    strong = company(
        revenue=(1000e6, 1100e6, 1210e6, 1500e6), ni=[100e6, 110e6, 120e6, 200e6], ocf=[150e6, 160e6, 170e6, 260e6],
        gross_profit=[500e6, 550e6, 600e6, 800e6],
        balance={"assets": 1500e6, "debt": 150e6, "current_assets": 700e6, "current_liabilities": 300e6},
        prior={"assets": 1450e6, "debt": 220e6, "current_assets": 500e6, "current_liabilities": 300e6},
    )
    m = one(strong)["metrics"]
    assert m["f_score"] == 9 and all(m["f_signals"].values())


def test_f_score_unknown_signals_score_nothing() -> None:
    m = one(company(balance={}, prior={}))["metrics"]
    sig = m["f_signals"]
    assert sig["return_on_assets_up"] is None and sig["debt_to_assets_down"] is None and sig["current_ratio_up"] is None and sig["asset_turnover_up"] is None
    assert m["f_score"] == sum(1 for v in sig.values() if v) == 4  # profit, cash flow, cash above profit, no new shares


def test_f_score_marks_dilution_and_rising_debt() -> None:
    weak = company(shares=(100e6, 100e6, 100e6, 104e6), prior={"assets": 1500e6, "debt": 100e6, "current_assets": 700e6, "current_liabilities": 300e6})
    sig = one(weak)["metrics"]["f_signals"]
    assert sig["no_new_shares"] is False and sig["debt_to_assets_down"] is False and sig["current_ratio_up"] is False
    assert one(weak, min_f_score=7)["failed"] == ["min_f_score"]


# --- expected growth and the gap --------------------------------------------------------------


def test_expected_growth_fades_from_the_slowest_recent_rate() -> None:
    assert MATH.expected_growth(0.03) == pytest.approx(0.03) and MATH.expected_growth(None) is None
    assert 0.45 < MATH.expected_growth(1.0) < 0.56  # a doubling company is credited with about half that over ten years
    assert -0.20 < MATH.expected_growth(-0.36) < -0.15  # and a sharp fall is not carried for ten years either
    assert isinstance(MATH.expected_growth(-1.4), float)  # a collapse does not break the arithmetic
    slowing = company(revenue=(1000e6, 1500e6, 2250e6, 2475e6), quarter={"revenue": 600e6, "revenue_year_ago": 600e6, "period": "CY2026Q2"})
    m = one(slowing)["metrics"]
    assert m["revenue_cagr"] > 0.35 and m["latest_quarter_growth"] == 0.0
    assert m["start_growth"] == 0.05  # latest year +10% averaged with a flat quarter, below the 35% multi-year rate
    assert m["expected_growth"] == pytest.approx(MATH.expected_growth(0.05), abs=1e-4)
    assert one(company())["metrics"]["start_growth"] == 0.10  # no quarter: the latest year stands alone


def test_growth_gap_compares_expected_growth_with_what_the_price_implies() -> None:
    m = one(company(market={"market_cap": 3e9, "enterprise_value": 3e9}))["metrics"]
    assert m["implied_growth"] is not None
    assert m["growth_gap"] == pytest.approx(m["expected_growth"] - m["implied_growth"], abs=2e-4)
    assert m["growth_gap"] < m["revenue_cagr"] - m["implied_growth"]  # the fade lowers it


# --- price metrics ----------------------------------------------------------------------------


def test_price_metrics() -> None:
    c = company(dividends=0.03, buybacks=[None, None, None, 60e6], market={"market_cap": 4e9, "enterprise_value": 4.1e9, "sector": "Industrials", "momentum": -0.31})
    row = one(c)
    m = row["metrics"]
    assert m["pe"] == pytest.approx(4e9 / (0.12 * 1331e6), abs=1e-3) and m["pb"] == 5.0
    assert m["pe_times_pb"] == pytest.approx(m["pe"] * 5, abs=1e-2)
    assert m["earnings_yield"] == pytest.approx(0.20 * 1331e6 / 4.1e9, abs=1e-4)
    assert m["shareholder_yield"] == pytest.approx((0.03 * 1331e6 + 60e6) / 4e9, abs=1e-4)
    assert m["sector"] == "Industrials" and m["momentum"] == -0.31 and "PRICE_FALLING" in row["flags"]


def test_new_price_criteria() -> None:
    mkt = {"market_cap": 4e9, "enterprise_value": 4e9, "momentum": 0.05}
    assert one(company(market=mkt), min_earnings_yield=0.05, min_momentum=0.0)["failed"] == []
    assert one(company(market=mkt), min_earnings_yield=0.10, min_momentum=0.10, max_pe_times_pb=22.5, min_shareholder_yield=0.01)["failed"] == [
        "min_earnings_yield", "min_shareholder_yield", "max_pe_times_pb", "min_momentum"]


# --- exclusions -------------------------------------------------------------------------------


def test_financial_filers_are_set_aside_before_any_test() -> None:
    bank = company("BANK")
    bank["financial"] = True
    out = screen([bank, company("AAA")], min_revenue_cagr=0.05)
    assert [r["failed"] for r in out["companies"]] == [["financial_filer"], []]
    assert out["funnel"][1] == {"stage": "financial_filer", "remaining": 1} and out["near_misses"] == []
    assert screen([bank], include_financials=True)["companies"][0]["failed"] == []
    assert "financial_filer" not in [s["stage"] for s in screen([company()])["funnel"]]


def test_excluded_sectors() -> None:
    util = company("UTIL", market={"market_cap": 3e9, "enterprise_value": 3e9, "sector": "Utilities"})
    tech = company("TECH", market={"market_cap": 3e9, "enterprise_value": 3e9, "sector": "Technology"})
    out = screen([util, tech], "magic", min_revenue=None)
    assert [s["ticker"] for s in out["survivors"]] == ["TECH"]
    assert {"stage": "sector_excluded", "remaining": 1} in out["funnel"]
    assert screen([util], exclude_sectors="Utilities, Energy")["criteria"]["exclude_sectors"] == ["Utilities", "Energy"]
    with pytest.raises(ValueError, match="exclude_sectors"):
        screen([util], exclude_sectors=3)


def test_a_missing_latest_quarter_is_flagged_when_the_test_applies() -> None:
    assert "LATEST_QUARTER_NOT_REPORTED" in one(company(), min_latest_quarter_growth=0.0)["flags"]
    assert "LATEST_QUARTER_NOT_REPORTED" not in one(company())["flags"]


# --- ranking and presets ----------------------------------------------------------------------


def _priced(ticker, cap, **kw):
    return company(ticker, market={"market_cap": cap, "enterprise_value": cap, "sector": "Industrials"}, **kw)


def test_magic_formula_ranks_on_earnings_yield_plus_return_on_capital() -> None:
    cheap_good = _priced("BEST", 2e9, op=0.30)        # highest yield and highest return
    dear_good = _priced("GOOD", 12e9, op=0.28)
    cheap_poor = _priced("POOR", 3e9, op=0.05)
    out = screen([dear_good, cheap_poor, cheap_good], "magic")
    assert out["rank_by"] == "magic_rank" and [s["ticker"] for s in out["survivors"]][0] == "BEST"
    assert [s["metrics"]["magic_rank"] for s in out["survivors"]] == sorted(s["metrics"]["magic_rank"] for s in out["survivors"])
    assert out["survivors"][0]["metrics"]["magic_rank"] == 2


def test_ascending_rank_keys_put_the_lowest_first() -> None:
    a, b = _priced("LOW", 1.5e9), _priced("HIGH", 6e9)
    out = screen([b, a], rank_by="pe_times_pb")
    assert [s["ticker"] for s in out["survivors"]] == ["LOW", "HIGH"]
    assert [s["ticker"] for s in screen([a, b], rank_by="pe")["survivors"]] == ["LOW", "HIGH"]


def test_unpriced_runs_can_rank_on_a_fundamental_figure() -> None:
    out = screen([company("LOWR", op=0.05), company("HIGHR", op=0.30)], rank_by="roce")
    assert out["rank_by"] == "roce" and [s["ticker"] for s in out["survivors"]] == ["HIGHR", "LOWR"]
    assert screen([company()], rank_by="fcf_yield")["rank_by"] == "revenue_cagr"


def test_graham_preset() -> None:
    passing = _priced("GRAM", 1.2e9, dividends=0.03, balance={"equity": 1000e6, "debt": 200e6, "cash": 100e6, "assets": 1500e6, "current_assets": 600e6, "current_liabilities": 300e6})
    out = screen([passing], "graham")
    m = out["survivors"][0]["metrics"]
    assert m["pe"] < 15 and m["pe_times_pb"] < 22.5 and out["rank_by"] == "pe_times_pb"
    assert screen([_priced("NODIV", 1.2e9)], "graham")["companies"][0]["failed"] == ["pays_dividend_all_years"]


def test_payout_preset() -> None:
    c = _priced("CASH", 2e9, dividends=0.04, buybacks=[None, None, None, 60e6], shares=(100e6, 99e6, 98e6, 97e6))
    out = screen([c], "payout")
    assert [s["ticker"] for s in out["survivors"]] == ["CASH"] and out["rank_by"] == "shareholder_yield"
    assert out["survivors"][0]["metrics"]["shareholder_yield"] > 0.04
    diluting = _priced("DILU", 2e9, dividends=0.06, shares=(100e6, 101e6, 102e6, 103e6))
    assert screen([diluting], "payout")["companies"][0]["failed"] == ["max_share_growth"]


def test_value_preset_fails_a_quarter_that_has_turned() -> None:
    falling = _priced("TRAP", 1.5e9, quarter={"revenue": 300e6, "revenue_year_ago": 400e6, "period": "CY2026Q2"})
    assert "min_latest_quarter_growth" in screen([falling], "value")["companies"][0]["failed"]


def test_every_preset_uses_known_criteria() -> None:
    known = set(MATH.FUNDAMENTAL + MATH.PRICE + MATH.SETTINGS)
    for name, crit in MATH.PRESETS.items():
        assert set(crit) <= known, name
        assert screen([company()], name)["preset"] == name


def test_held_is_passed_through() -> None:
    c = company()
    c["held"] = True
    assert one(c)["held"] is True and one(company())["held"] is False
