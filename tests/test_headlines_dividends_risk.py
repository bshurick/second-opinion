from __future__ import annotations

from datetime import date

from second_opinion.headlines import dividends as D
from second_opinion.headlines import risk as RK

CTX = {"today": date(2026, 9, 14), "previous": {"keys": [], "risk": {}}}


def test_dividend_cut_is_alert_and_cautions_are_notices() -> None:
    res = {"main": {"flags": [{"code": "DIVIDEND_CUT", "message": "trailing 12-month dividends fell for: T, VZ"},
                              {"code": "VALUE_TRAP_CAUTION", "message": "T yield rose 2.1pp while price fell 8.5%"},
                              {"code": "VALUE_TRAP_CAUTION", "message": "VZ yield rose 1.5pp while price fell 3.2%"},
                              {"code": "HIGH_PAYOUT", "message": "payout ratio above 90% for: VZ"},
                              {"code": "INCOME_CONCENTRATED", "message": "T pays 41% of projected income (above 30%)"},
                              {"code": "NO_DIVIDENDS", "message": "x"}],
                    "positions": [{"symbol": "T", "forward_yield": 0.061, "annual_income": 410.50, "safety": {"score": 10.0}},
                                  {"symbol": "VZ", "forward_yield": 0.068, "annual_income": 210.00, "safety": {"score": 5}}]}}
    hs = D.extract(res, CTX)
    assert [(h["code"], h["severity"]) for h in hs] == [("DIVIDEND_CUT", "alert"), ("VALUE_TRAP_CAUTION", "notice"), ("VALUE_TRAP_CAUTION", "notice"), ("HIGH_PAYOUT", "notice"), ("INCOME_CONCENTRATED", "notice")]
    assert hs[0]["key"] == "dividend-income:DIVIDEND_CUT:-:T, VZ" and hs[0]["title"] == "trailing 12-month dividends fell for: T, VZ"
    assert hs[1]["key"] == "dividend-income:VALUE_TRAP_CAUTION:T:" and hs[1]["ask"] == "Is T's yield a value trap?"
    assert hs[2]["key"] == "dividend-income:VALUE_TRAP_CAUTION:VZ:" and hs[2]["ask"] == "Is VZ's yield a value trap?"
    assert hs[4]["key"] == "dividend-income:INCOME_CONCENTRATED:T:" and hs[4]["ask"] == "How concentrated is my dividend income?"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "trailing 12-month dividends fell for: T, VZ"
    assert hs[0]["why"] == "Trailing dividends fell versus the prior year."
    assert hs[1]["url"] == "https://finance.yahoo.com/quote/T"
    assert hs[1]["answer"] == "Yield 6.1%, annual income $410.50, safety 10/10"
    assert hs[1]["why"] == "A yield that rose because the price fell can signal trouble rather than value."
    assert hs[3]["url"] == "" and hs[3]["answer"] == "payout ratio above 90% for: VZ"
    assert hs[3]["why"] == "Paying out most of earnings leaves little room to keep paying."
    assert hs[4]["url"] == "https://finance.yahoo.com/quote/T"
    assert hs[4]["answer"] == "Yield 6.1%, annual income $410.50, safety 10/10"
    assert hs[4]["why"] == "One payer supplies a large share of your dividend income."


def test_dividends_per_symbol_answer_skips_missing_parts() -> None:
    res = {"main": {"flags": [{"code": "VALUE_TRAP_CAUTION", "message": "ZZZ yield rose"}],
                    "positions": [{"symbol": "ZZZ", "forward_yield": 0.09, "annual_income": None, "safety": None}]}}
    hs = D.extract(res, CTX)
    assert hs[0]["answer"] == "Yield 9.0%"


def test_dividends_without_flags_is_empty() -> None:
    assert D.extract({"main": {"flags": []}}, CTX) == []


def test_risk_flags_are_notices() -> None:
    res = {"main": {"portfolio": {"max_drawdown": -0.21, "beta": 1.32, "volatility": 0.24, "total_value": 250000.0, "avg_pairwise_correlation": 0.62},
                    "flags": [{"code": "HIGH_BETA", "message": "beta 1.32"}, {"code": "ILLIQUID_POSITION", "message": "ZZZ is 12.5% of 20-day average dollar volume"}, {"code": "ILLIQUID_POSITION", "message": "QQQ is 8.7% of 20-day average dollar volume"}, {"code": "SHORT_HISTORY", "message": "x"}],
                    "liquidity": [{"symbol": "ZZZ", "avg_dollar_volume": 400000.0, "position_value": 50000.0, "pct_of_adv": 0.125},
                                  {"symbol": "QQQ", "avg_dollar_volume": 900000.0, "position_value": 78300.0, "pct_of_adv": 0.087}]}}
    hs = RK.extract(res, CTX)
    assert [(h["code"], h["severity"]) for h in hs] == [("HIGH_BETA", "notice"), ("ILLIQUID_POSITION", "notice"), ("ILLIQUID_POSITION", "notice")]
    assert hs[0]["ask"] == "How much would a 20% market drop cost me?"
    assert hs[1]["key"] == "risk-analysis:ILLIQUID_POSITION:ZZZ:" and hs[1]["ask"] == "Which positions are hard to sell quickly?"
    assert hs[2]["key"] == "risk-analysis:ILLIQUID_POSITION:QQQ:" and hs[2]["ask"] == "Which positions are hard to sell quickly?"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "Beta 1.32; a 20% market drop maps to about $66,000.00"
    assert hs[0]["why"] == "Beta is how much the portfolio moves when the market moves 1%."
    assert hs[1]["url"] == "https://finance.yahoo.com/quote/ZZZ"
    assert hs[1]["answer"] == "$50,000.00 position vs $400,000.00 average daily volume (12.5%)"
    assert hs[1]["why"] == "A position larger than a slice of daily volume takes days to sell without moving the price."
    assert hs[2]["answer"] == "$78,300.00 position vs $900,000.00 average daily volume (8.7%)"


def test_high_beta_answer_names_partial_coverage() -> None:
    res = {"main": {"portfolio": {"beta": 0.24, "total_value": 400000.0, "coverage": 0.655}, "flags": [{"code": "HIGH_BETA", "message": "beta 0.24"}]}}
    hs = RK.extract(res, CTX)
    assert hs[0]["answer"] == "Beta 0.24; a 20% market drop maps to about $19,200.00 (statistics cover 65.5% of value; the rest is assumed unchanged)"
    full = {"main": {"portfolio": {"beta": 0.24, "total_value": 400000.0, "coverage": 1.0}, "flags": [{"code": "HIGH_BETA", "message": "beta 0.24"}]}}
    assert RK.extract(full, CTX)[0]["answer"] == "Beta 0.24; a 20% market drop maps to about $19,200.00"


def test_risk_high_correlation_answer() -> None:
    res = {"main": {"portfolio": {"avg_pairwise_correlation": 0.62}, "flags": [{"code": "HIGH_CORRELATION", "message": "avg pairwise correlation 0.62"}]}}
    hs = RK.extract(res, CTX)
    assert hs[0]["answer"] == "Average pairwise correlation 0.62"
    assert hs[0]["why"] == "Holdings that move together give less diversification than their count implies."


def test_risk_drawdown_worse_than_last_brief_is_a_notice() -> None:
    res = {"main": {"portfolio": {"max_drawdown": -0.27}, "flags": [],
                    "risk_contributions": [{"symbol": "AAPL", "share": 0.18}, {"symbol": "MSFT", "share": 0.41}, {"symbol": "ZZZ", "share": 0.05}]}}
    ctx = {**CTX, "previous": {"keys": [], "risk": {"max_drawdown": -0.21}}}
    hs = RK.extract(res, ctx)
    assert len(hs) == 1 and hs[0]["code"] == "DRAWDOWN_DEEPER" and hs[0]["key"] == "risk-analysis:DRAWDOWN_DEEPER:-:2026-09-14"
    assert hs[0]["title"] == "Max drawdown deepened to 27.0% from 21.0% at the last brief"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "Largest risk contributor MSFT at 41% of portfolio variance"
    assert hs[0]["why"] == "Max drawdown is the deepest peak-to-trough fall over the period."
    assert RK.extract(res, {**CTX, "previous": {"keys": [], "risk": {"max_drawdown": -0.25}}}) == []
    assert RK.extract(res, CTX) == []


def test_risk_snapshot_for_last() -> None:
    assert RK.snapshot_for_last({"main": {"portfolio": {"max_drawdown": -0.27}}}) == {"max_drawdown": -0.27}
    assert RK.snapshot_for_last({}) == {}


def test_risk_extract_records_the_raw_result_for_the_caller() -> None:
    res = {"main": {"portfolio": {"max_drawdown": -0.21}, "flags": []}}
    ctx = {**CTX, "risk_results": {}}
    RK.extract(res, ctx)
    assert ctx["risk_results"] == res
