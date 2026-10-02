from __future__ import annotations

from datetime import date

from second_opinion.headlines import rebalancing as R
from second_opinion.headlines import tax as T

CTX = {"today": date(2026, 9, 14)}


def test_band_breach_is_an_alert_listing_breached_keys() -> None:
    res = {"main": {"flags": [{"code": "BAND_BREACH", "message": "2 classes outside bands"}],
                    "allocation": [{"key": "us_equity", "weight": 0.71, "target": 0.60, "drift": 0.11, "breach": True},
                                   {"key": "bonds", "weight": 0.12, "target": 0.25, "drift": -0.13, "breach": True},
                                   {"key": "cash", "weight": 0.17, "target": 0.15, "drift": 0.02, "breach": False}], "max_drift": 0.13,
                    "turnover": 0.084,
                    "trades": [{"symbol": "VTI", "side": "SELL", "units": 12.0, "price": 258.33, "value": 3100.00, "reason": "over target", "account": "brokerage"},
                               {"symbol": "BND", "side": "BUY", "units": 40.0, "price": 75.00, "value": 3000.00, "reason": "under target", "account": "brokerage"}]}}
    hs = R.extract(res, CTX)
    assert len(hs) == 1
    assert hs[0]["key"] == "rebalancing:BAND_BREACH:-:bonds,us_equity" and hs[0]["severity"] == "alert"
    assert hs[0]["title"] == "Allocation outside its bands: bonds -13.0 pts, us_equity +11.0 pts"
    assert hs[0]["ask"] == "What trades bring me back inside my bands?"
    assert hs[0]["url"] == ""
    assert hs[0]["answer"] == "Plan: SELL 12 VTI $3,100.00; BUY 40 BND $3,000.00 — turnover 8.4%"
    assert hs[0]["why"] == "Your allocation drifted past the tolerance band you set around each target weight."


def test_band_breach_answer_skips_trades_with_no_symbol_and_omits_units_when_not_numeric() -> None:
    res = {"main": {"flags": [{"code": "BAND_BREACH", "message": "2 classes outside bands"}],
                    "allocation": [{"key": "bonds", "drift": -0.13, "breach": True}], "turnover": 0.05,
                    "trades": [{"symbol": None, "side": "SELL", "units": 5.0, "value": 100.0},
                               {"symbol": "BND", "side": "BUY", "units": None, "value": 3000.00}]}}
    hs = R.extract(res, CTX)
    assert hs[0]["answer"] == "Plan: BUY BND $3,000.00 — turnover 5.0%"


def test_within_bands_gives_nothing_and_unmapped_is_a_notice() -> None:
    res = {"main": {"flags": [{"code": "WITHIN_BANDS", "message": "ok"}, {"code": "UNMAPPED", "message": "no class for: XYZ, ABC"}], "allocation": []}}
    hs = R.extract(res, CTX)
    assert len(hs) == 1 and hs[0]["code"] == "UNMAPPED" and hs[0]["severity"] == "notice" and hs[0]["title"] == "no class for: XYZ, ABC"
    assert hs[0]["ask"] == "Which holdings are not mapped to a target class?"
    assert hs[0]["url"] == "" and hs[0]["answer"] == "no class for: XYZ, ABC"
    assert hs[0]["why"] == "Holdings with no target class are ignored by the drift check."


def test_tax_wash_sale_lots_near_long_term_and_harvest_candidates() -> None:
    res = {"main": {"flags": [{"code": "WASH_SALE", "message": "AAPL: $310.00 of loss disallowed"}, {"code": "NEAR_LONG_TERM", "message": "x"}],
                    "realized": [{"symbol": "AAPL", "sell_date": "2026-09-03", "disallowed": 310.0, "wash_sale": True, "wash_buy_date": "2026-08-20"},
                                 {"symbol": "MSFT", "sell_date": "2026-09-01", "disallowed": 120.0, "wash_sale": True, "wash_buy_date": "2026-08-25"},
                                 {"symbol": "GOOGL", "sell_date": "2026-09-02", "wash_sale": False}],
                    "open_lots": [{"symbol": "PEP", "buy_date": "2025-10-02", "units": 142, "unrealized": 1240.0, "days_to_long_term": 18,
                                   "long_term_date": "2026-10-02", "term": "short", "tax_if_sold": 372.00, "tax_if_sold_long": 186.00},
                                  {"symbol": "PEP", "buy_date": "2025-10-20", "units": 10, "unrealized": 50.0, "days_to_long_term": 36,
                                   "long_term_date": "2026-10-20", "term": "short", "tax_if_sold": 15.00, "tax_if_sold_long": 7.50},
                                  {"symbol": "KO", "buy_date": "2024-01-01", "units": 5, "unrealized": 9.0, "days_to_long_term": 0,
                                   "long_term_date": "2025-01-01", "term": "long", "tax_if_sold": 2.70, "tax_if_sold_long": 1.35}],
                    "harvest_candidates": [{"symbol": "XOM", "units": 30, "unrealized": -1500.0, "tax_benefit": 360.0, "recent_buy_within_30d": False},
                                           {"symbol": "T", "units": 30, "unrealized": -400.0, "tax_benefit": 96.0, "recent_buy_within_30d": False}]}}
    hs = T.extract(res, CTX)
    assert [h["key"] for h in hs] == ["tax-aware:WASH_SALE:MSFT:2026-09-01", "tax-aware:WASH_SALE:AAPL:2026-09-03", "tax-aware:NEAR_LONG_TERM:PEP:2026-10-02", "tax-aware:HARVEST:XOM:"]
    assert hs[0]["severity"] == "alert" and hs[0]["title"] == "MSFT sold 2026-09-01: $120.00 of loss disallowed as a wash sale"
    assert hs[0]["detail"] == "repurchased 2026-08-25; the disallowed amount is added to that lot's basis"
    assert hs[0]["ask"] == "Which of my sales were wash sales?"
    assert hs[0]["url"] == "https://finance.yahoo.com/quote/MSFT" and hs[0]["answer"] == hs[0]["detail"]
    assert hs[0]["why"] == ("A loss is disallowed when the same security is bought within 30 days of the sale; "
                             "the loss is added to the new lot's cost basis.")
    assert hs[1]["severity"] == "alert" and hs[1]["title"] == "AAPL sold 2026-09-03: $310.00 of loss disallowed as a wash sale"
    assert hs[2]["severity"] == "alert" and hs[2]["title"] == "PEP lot turns long-term on 2026-10-02 (18 days)"
    assert hs[2]["detail"] == "142 units bought 2025-10-02, unrealized $1,240.00" and hs[2]["ask"] == "Which lots of PEP are near long-term?"
    assert hs[2]["url"] == "https://finance.yahoo.com/quote/PEP"
    assert hs[2]["answer"] == "Tax if sold now $372.00 vs $186.00 after 2026-10-02 (difference $186.00)"
    assert hs[2]["why"] == "Gains on lots held over a year are taxed at the lower long-term rate."
    assert hs[3]["severity"] == "notice" and hs[3]["title"] == "XOM carries a $1,500.00 unrealized loss to harvest"
    assert hs[3]["ask"] == "What would harvesting XOM save me?"
    assert hs[3]["url"] == "https://finance.yahoo.com/quote/XOM" and hs[3]["answer"] == hs[3]["detail"]
    assert hs[3]["why"] == "Selling a losing lot realizes a loss that offsets gains or up to $3,000 of income."


def test_tax_wash_sale_fallback_without_realized_list() -> None:
    res = {"main": {"flags": [{"code": "WASH_SALE", "message": "AAPL: $310.00 of loss disallowed"}, {"code": "WASH_SALE", "message": "MSFT: $120.00 of loss disallowed"}],
                    "open_lots": [], "harvest_candidates": []}}
    hs = T.extract(res, CTX)
    assert len(hs) == 2
    assert hs[0]["key"] == "tax-aware:WASH_SALE:AAPL:2026-09-14:0" and hs[0]["severity"] == "alert"
    assert hs[1]["key"] == "tax-aware:WASH_SALE:MSFT:2026-09-14:1" and hs[1]["severity"] == "alert"
    assert hs[0]["url"] == "https://finance.yahoo.com/quote/AAPL" and hs[0]["answer"] == hs[0]["detail"]
    assert hs[0]["why"] == ("A loss is disallowed when the same security is bought within 30 days of the sale; "
                             "the loss is added to the new lot's cost basis.")


def test_tax_empty_result_is_empty() -> None:
    assert T.extract({"main": {"flags": [], "open_lots": [], "harvest_candidates": []}}, CTX) == []
