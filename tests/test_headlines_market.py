from __future__ import annotations

from datetime import date

from second_opinion.headlines import market as M

CTX = {"today": date(2026, 9, 14), "now": "2026-09-14T13:05:00+00:00"}


def _indices(spx=0.4, spx_week=1.1, ndx=0.7, ndx_week=1.9, vix=15.2, vix_pct=0.42, spread=0.35, above=6, rsp_spy=0.4, irx=4.30):
    return {"as_of": "2026-09-14T13:00:00+00:00",
            "indices": [{"symbol": "^GSPC", "name": "S&P 500", "last": 6400.1, "day_change_pct": spx, "week_change_pct": spx_week},
                        {"symbol": "^IXIC", "name": "Nasdaq", "last": 21000.5, "day_change_pct": ndx, "week_change_pct": ndx_week},
                        {"symbol": "^VIX", "name": "VIX", "last": vix, "day_change_pct": -1.0}],
            "rates": [{"symbol": "^TNX", "name": "10-year", "last": 4.12}, {"symbol": "^IRX", "name": "3-month", "last": irx}],
            "spreads": {"10y_13w": spread}, "breadth": {"sectors_above_50sma": above, "sectors_total": 11, "rsp_spy_1m": rsp_spy},
            "vix_percentile_1y": vix_pct}


def test_quiet_day_gives_only_the_info_line() -> None:
    hs = M.extract({"indices": _indices()}, CTX)
    assert len(hs) == 1 and hs[0]["severity"] == "info"
    assert hs[0]["key"] == "market-analysis:DAY:-:2026-09-14"
    assert hs[0]["title"] == "S&P 500 +0.4% · Nasdaq +0.7% · 10y 4.12% · VIX 15.2"
    assert hs[0]["ask"] == "How is the market positioned this week?"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "" and hs[0]["why"] == ""


def test_index_move_vix_inversion_and_breadth_are_notices() -> None:
    hs = M.extract({"indices": _indices(spx=-1.6, spx_week=-4.2, vix=28.0, vix_pct=0.91, spread=-0.2, above=2, rsp_spy=-1.3)}, CTX)
    codes = [h["code"] for h in hs]
    assert codes[:4] == ["INDEX_MOVE", "VIX_HIGH", "CURVE_INVERTED", "BREADTH_WEAK"] and hs[-1]["code"] == "DAY"
    assert hs[0]["title"] == "S&P 500 fell 1.6% today" and hs[0]["severity"] == "notice"
    assert hs[1]["title"] == "VIX 28.0 is at the 91st percentile of the last year"
    assert hs[2]["title"] == "Yield curve inverted: 10-year minus 3-month is -0.20 points"
    assert hs[3]["title"] == "Only 2 of 11 sectors are above their 50-day average"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "S&P 500 6,400.10, -4.2% on the week"
    assert hs[0]["why"] == "A one-day move of 1% or more is unusual for a broad index."
    assert hs[1]["answer"] == "VIX 28.0 versus a one-year range; above the 80th percentile"
    assert hs[1]["why"] == "The VIX is the market's expected 30-day volatility; a high reading means options are pricing bigger swings."
    assert hs[2]["answer"] == "3-month 4.30% vs 10-year 4.12%"
    assert hs[2]["why"] == "Short rates above long rates has preceded most US recessions, usually with a long lag."
    assert hs[3]["answer"] == "2 of 11 sectors above their 50-day; RSP/SPY -1.3% over one month"
    assert hs[3]["why"] == "Breadth is how many sectors are trending up; narrow breadth means a few names carry the index."
    assert hs[-1]["answer"] == "" and hs[-1]["why"] == ""


def test_breadth_strong_and_nasdaq_move_wording() -> None:
    hs = M.extract({"indices": _indices(ndx=1.0, ndx_week=2.5, above=10)}, CTX)
    assert [h["code"] for h in hs] == ["INDEX_MOVE", "BREADTH_STRONG", "DAY"]
    assert hs[0]["title"] == "Nasdaq rose 1.0% today" and hs[1]["title"] == "10 of 11 sectors are above their 50-day average"
    assert hs[0]["answer"] == "Nasdaq 21,000.50, +2.5% on the week"


def test_cftc_extreme_and_cash_record_from_flows() -> None:
    flows = {"positioning": {"report_date": "2026-09-09", "contracts": [
                {"code": "ES", "label": "S&P 500 e-mini", "group": "index", "weeks": 52,
                 "classes": {"asset_managers": {"net": 120000, "net_change": 8000, "net_pct_oi": 22.5, "percentile": 97.0},
                             "leveraged_funds": {"net": -50000, "net_change": -2000, "net_pct_oi": 9.4, "percentile": 40.0}}},
                {"code": "ZN", "label": "10-year note", "group": "rates", "weeks": 52,
                 "classes": {"asset_managers": {"net": 10, "net_change": 1, "net_pct_oi": 0.1, "percentile": 50.0},
                             "leveraged_funds": {"net": -900000, "net_change": -30000, "net_pct_oi": 41.2, "percentile": 2.0}}}]},
             "cash": {"series": "WRMFNS", "latest": 7310.0, "date": "2026-09-10", "unit": "billions of dollars, weekly", "change_4w": 60.0, "change_52w_pct": 12.0,
                      "observations": [{"date": "2026-09-03", "value": 7250.0}, {"date": "2026-09-10", "value": 7310.0}]}}
    hs = M.extract({"indices": _indices(), "flows": flows}, CTX)
    codes = [h["code"] for h in hs]
    assert codes == ["CFTC_EXTREME", "CFTC_EXTREME", "CASH_RECORD", "DAY"]
    assert hs[0]["key"] == "market-analysis:CFTC_EXTREME:-:ES:asset_managers:2026-09-09"
    assert hs[0]["title"] == "Institutions are the most net long S&P 500 e-mini futures in 52 weeks"
    assert hs[0]["url"] == "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
    assert hs[0]["answer"] == "Net +120,000 contracts, 22.5% of open interest, +8,000 on the week"
    assert hs[0]["why"] == ("Weekly CFTC positioning of hedge funds (leveraged funds) and institutions (asset managers) "
                            "in futures; an extreme reading has more often preceded a reversal than a continuation.")
    assert hs[1]["title"] == "Hedge funds are the most net short 10-year note futures in 52 weeks"
    assert hs[1]["answer"] == "Net -900,000 contracts, 41.2% of open interest, -30,000 on the week"
    assert hs[2]["title"] == "Money-fund cash 7310.00 billions of dollars, weekly is a one-year high (2026-09-10)"
    assert hs[2]["key"] == "market-analysis:CASH_RECORD:-:2026-09-10"
    assert hs[2]["url"] == "https://fred.stlouisfed.org/series/WRMFNS"
    assert hs[2]["answer"] == "+60 billion over four weeks, +12.0% over a year"
    assert hs[2]["why"] == "Cash parked in money-market funds; a high level is dry powder that has not been put into stocks or bonds."


def test_cftc_extreme_skips_sector_contracts_and_short_history() -> None:
    flows = {"positioning": {"report_date": "2026-09-09", "contracts": [
                {"code": "XLF", "label": "Financials", "group": "sector", "weeks": 52,
                 "classes": {"asset_managers": {"net": 5000, "net_change": 100, "net_pct_oi": 5.0, "percentile": 97.0}}},
                {"code": "ES", "label": "S&P 500 e-mini", "group": "index", "weeks": 5,
                 "classes": {"asset_managers": {"net": 120000, "net_change": 8000, "net_pct_oi": 22.5, "percentile": 97.0}}}]}}
    hs = M.extract({"flows": flows}, CTX)
    assert [h["code"] for h in hs] == []


def test_cftc_extreme_positive_net_at_low_percentile_reads_least_net_long() -> None:
    flows = {"positioning": {"report_date": "2026-09-09", "contracts": [
                {"code": "ES", "label": "S&P 500 e-mini", "group": "index", "weeks": 52,
                 "classes": {"asset_managers": {"net": 50000, "net_change": 1000, "net_pct_oi": 3.0, "percentile": 3.0}}}]}}
    hs = M.extract({"flows": flows}, CTX)
    assert hs[0]["title"] == "Institutions are the least net long S&P 500 e-mini futures in 52 weeks"
    assert hs[0]["answer"] == "Net +50,000 contracts, 3.0% of open interest, +1,000 on the week"


def test_cash_record_unit_word_covers_trillions_and_other_units() -> None:
    def _cash(unit):
        return {"flows": {"cash": {"series": "S1", "latest": 5.0, "date": "2026-09-10", "unit": unit, "change_4w": 10.0, "change_52w_pct": 1.0,
                                   "observations": [{"date": "2026-09-03", "value": 4.0}, {"date": "2026-09-10", "value": 5.0}]}}}
    trillions = M.extract(_cash("trillions of dollars"), CTX)
    assert trillions[0]["answer"] == "+10 trillion over four weeks, +1.0% over a year"
    other = M.extract(_cash("index points"), CTX)
    assert other[0]["answer"] == "+10 index points over four weeks, +1.0% over a year"


def test_flows_error_block_and_missing_indices_are_tolerated() -> None:
    assert M.extract({"flows": {"positioning": {"error": "cftc down", "code": "API_ERROR"}, "cash": {"error": "x"}}}, CTX) == []
    assert M.extract({}, CTX) == []
