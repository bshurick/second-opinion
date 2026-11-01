from __future__ import annotations

import re

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client, market
from second_opinion.brokers import router
from page_dom import assert_page_help, render_and_audit, requires_chrome

POSITIONS = {
    "acc-1": [{"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": 100.0, "average_purchase_price": 80.0}],
    "acc-2": [{"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": 100.0, "average_purchase_price": 120.0}, {"symbol": {"symbol": {"symbol": "GROW"}}, "units": 5, "price": 50.0}],
}
AAPL = [{"date": f"{y}-{m:02d}-10", "dividend": 0.25} for y in (2024, 2025) for m in (2, 5, 8, 11)] + [{"date": f"2026-{m:02d}-10", "dividend": 0.26} for m in (2, 5, 8)]


def _patch_closes(monkeypatch, closes):
    calls = []

    def close_histories(symbols, start):
        calls.append((list(symbols), start))
        return closes

    monkeypatch.setattr(market, "close_histories", close_histories)
    return calls


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=lambda account_id: POSITIONS[account_id])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


@pytest.fixture
def yahoo(monkeypatch):
    calls: dict[str, list] = {"dividend_histories": [], "payout_info": []}

    def dividend_histories(symbols, years=5):
        calls["dividend_histories"].append((list(symbols), years))
        return {"AAPL": AAPL, "GROW": []}

    def payout_info(symbols):
        calls["payout_info"].append(list(symbols))
        return {s: {"payout_ratio": 0.15, "eps_ttm": 7.0, "dividend_rate": 1.04} for s in symbols}

    def quote(symbols, hub=None):
        return [{"symbol": s, "price": 50.0, "quote_type": "EQUITY", "source": "yahoo"} for s in symbols]

    monkeypatch.setattr(market, "dividend_histories", dividend_histories)
    monkeypatch.setattr(market, "payout_info", payout_info)
    monkeypatch.setattr(market, "quote", quote)
    return calls


def test_dividends_script_aggregates_and_reports_income(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["as_of"] == "2026-09-04" and out["sources"] == {"holdings": "snaptrade", "dividends": "yahoo", "fundamentals": None}
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    assert aapl["units"] == 20 and aapl["annual_income"] == 20.8 and aapl["yield_on_cost"] == 0.0104 and aapl["payout_ratio"] is None
    assert out["totals"]["annual_income"] == 20.8
    assert yahoo["dividend_histories"] == [(["AAPL", "GROW"], 5)] and yahoo["payout_info"] == []
    assert len(sdk.kwargs_for("list_user_accounts")) == 1 and len(sdk.kwargs_for("get_user_account_balance")) == 0
    # safety block comes from income.py's shared math; this fixture spans
    # 2024-2026 so the streak is 2 (-2) and the last 12 regular payments
    # .25x8/.26x3 give cv .0176
    assert aapl["safety"] == {"score": 8.0, "consecutive_years": 2, "cuts_in_window": 0, "payment_cv": 0.0176, "payout_ratio": None, "flags": []}
    assert next(p for p in out["positions"] if p["symbol"] == "GROW")["safety"] is None
    # yield-context fields are opt-in via --yield-context; absent here
    assert "price_1y_change" not in aapl and "yield_1y_ago" not in aapl and "yield_vs_1y_ago" not in aapl


def test_dividends_script_payout_flag(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-09-04", "--payout"], capsys)
    assert rc == 0 and out["sources"]["fundamentals"] == "yahoo"
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    assert aapl["payout_ratio"] == 0.15 and yahoo["payout_info"] == [["AAPL", "GROW"]]


def test_dividends_script_account_filter_and_years(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--account", "acc-1", "--years", "3", "--as-of", "2026-09-04"], capsys)
    assert rc == 0 and out["totals"]["annual_income"] == 10.4 and yahoo["dividend_histories"] == [(["AAPL"], 3)]
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--account", "nope"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_dividends_script_yahoo_failure_exit_5(sdk, monkeypatch, capsys) -> None:
    def boom(symbols, years=5):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "dividend_histories", boom)
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), [], capsys)
    assert rc == 5 and out["code"] == "API_ERROR" and "yahoo down" in out["error"]


def test_dividends_script_no_accounts_exit_5(monkeypatch, yahoo, capsys) -> None:
    fake = FakeSdk(list_user_accounts=[], list_brokerage_authorizations=[])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), [], capsys)
    assert rc == 5 and out["code"] == "NO_ACCOUNTS"


# ---------------------------------------------------------------------------
# --yield-context (one batched close-history download, payer rows only)
# ---------------------------------------------------------------------------


def test_dividends_script_yield_context_value_trap(sdk, yahoo, monkeypatch, capsys) -> None:
    # base 100 -> last 50: price -50%; ttm regular now 1.03/50 = .0206 vs
    # 1.00/100 = .01 a year ago -> +1.06pp: yield up because price fell
    calls = _patch_closes(monkeypatch, {"AAPL": [
        {"date": "2025-09-04", "close": 100.0, "adj_close": 100.0},
        {"date": "2026-09-04", "close": 50.0, "adj_close": 50.0},
    ]})
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-09-04", "--yield-context"], capsys)
    assert rc == 0, out
    # ONE batched download for payers only, ~370 days back from as_of
    assert calls == [(["AAPL"], "2025-08-30")]
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    assert aapl["price_1y_change"] == -0.5
    assert aapl["yield_1y_ago"] == 0.01
    assert aapl["yield_vs_1y_ago"] == 0.0106
    assert {"code": "VALUE_TRAP_CAUTION", "message": "AAPL yield rose 1.06pp while price fell 50.0%"} in out["flags"]
    # non-payers carry neither the fields nor a fetch
    grow = next(p for p in out["positions"] if p["symbol"] == "GROW")
    assert "price_1y_change" not in grow and "yield_1y_ago" not in grow


def test_dividends_script_yield_context_benign_and_short_history(sdk, yahoo, monkeypatch, capsys) -> None:
    # price up 10%, yield slightly down -> fields, no flag; GROW has no closes
    _patch_closes(monkeypatch, {"AAPL": [
        {"date": "2025-09-04", "close": 100.0, "adj_close": 100.0},
        {"date": "2026-09-04", "close": 110.0, "adj_close": 110.0},
    ], "GROW": [{"date": "2026-09-04", "close": 50.0, "adj_close": 50.0}]})
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-09-04", "--yield-context"], capsys)
    assert rc == 0
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    assert aapl["price_1y_change"] == 0.1
    assert aapl["yield_1y_ago"] == 0.01
    assert aapl["yield_vs_1y_ago"] == -0.0006  # 1.03/110 - .01
    assert not any(f["code"] == "VALUE_TRAP_CAUTION" for f in out["flags"])
    # a close history too short to reach ~1y ago degrades to nulls
    short = _patch_closes(monkeypatch, {"AAPL": [{"date": "2026-09-04", "close": 100.0, "adj_close": 100.0}]})
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-09-04", "--yield-context"], capsys)
    assert rc == 0 and short == [(["AAPL"], "2025-08-30")]
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    assert aapl["price_1y_change"] is None and aapl["yield_vs_1y_ago"] is None


def test_dividends_script_yield_context_fetch_failure_never_fails_run(sdk, yahoo, monkeypatch, capsys) -> None:
    def boom(symbols, start):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "close_histories", boom)
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-09-04", "--yield-context"], capsys)
    assert rc == 0, out
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    assert aapl["price_1y_change"] is None and aapl["yield_1y_ago"] is None and aapl["yield_vs_1y_ago"] is None
    assert any(f["code"] == "YIELD_CONTEXT_UNAVAILABLE" and "yahoo down" in f["message"] for f in out["flags"])
    assert not any(f["code"] == "VALUE_TRAP_CAUTION" for f in out["flags"])


def test_dividends_next_ex_amount_est_is_last_regular_dividend_times_units(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    assert aapl["next_ex_date_est"] == "2026-11-09" and aapl["next_ex_amount_est"] == 5.2  # 0.26 x 20 units
    assert next(p for p in out["positions"] if p["symbol"] == "GROW")["next_ex_amount_est"] is None


# ---------------------------------------------------------------------------
# money market funds and holdings with no public data
# ---------------------------------------------------------------------------

def _pos(symbol, units, price, name=None, avg=None):
    row = {"symbol": {"symbol": {"symbol": symbol, "description": name}}, "units": units, "price": price}
    if avg is not None:
        row["average_purchase_price"] = avg
    return row


MIXED = {
    "acc-1": [_pos("AAPL", 10, 100.0, avg=80.0), _pos("SPAXX", 100000, 1.0, "Fidelity Government Money Market Fund", 1.0), _pos("GROW", 5, 50.0)],
    "acc-2": [_pos("QBN5", 100, 300.0, "ACME INST 500 IDX TR"), _pos("MYSTRY", 10, 100.0, "PLAN STABLE VALUE"), _pos("FDRXX", 1000, 1.0, "Fidelity Government Cash Reserves", 1.0)],
}


@pytest.fixture
def mixed(monkeypatch):
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=lambda account_id: MIXED[account_id])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    calls = {"histories": []}

    def dividend_histories(symbols, years=5):
        calls["histories"].append(list(symbols))
        history = {"AAPL": AAPL, "VOO": [{"date": "2026-06-20", "dividend": 2.0}, {"date": "2026-03-20", "dividend": 2.0}]}
        return {s: history.get(s, []) for s in symbols}

    def quote(symbols, hub=None):
        known = {
            "SPAXX": {"price": 1.0, "seven_day_yield": 3.6, "source": "etrade"},
            "FDRXX": {"price": 1.0, "quote_type": "MONEYMARKET", "source": "yahoo"},  # no E*Trade yield
            "GROW": {"price": 50.0, "quote_type": "EQUITY", "source": "yahoo"},
            "VOO": {"price": 400.0, "quote_type": "ETF", "source": "yahoo"},
        }
        return [{"symbol": s, "source": "yahoo", "price": None, **known.get(s, {})} for s in symbols]

    monkeypatch.setattr(market, "dividend_histories", dividend_histories)
    monkeypatch.setattr(market, "quote", quote)
    return calls


def _row(out, symbol):
    return next(p for p in out["positions"] if p["symbol"] == symbol)


def _flag(out, code):
    return next((f["message"] for f in out["flags"] if f["code"] == code), None)


def test_money_market_income_comes_from_the_seven_day_yield(mixed, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01"], capsys)
    assert rc == 0, out
    fund = _row(out, "SPAXX")
    assert fund["income_status"] == "money_market" and fund["seven_day_yield"] == 0.036
    assert fund["annual_income"] == 3600.0 and fund["forward_yield"] == 0.036 and fund["frequency"] == "monthly"
    assert fund["next_ex_amount_est"] == 300.0 and fund["next_ex_date_est"] == "2026-11-30"  # last weekday of the month
    assert fund["ttm_income"] is None and fund["safety"] is None
    # it pays in every month of the schedule, on top of AAPL's quarterly payments
    assert all("SPAXX" in m["payers"] for m in out["monthly"]) and len(out["monthly"]) == 12
    assert next(m for m in out["monthly"] if m["month"] == "2026-12")["income"] == 300.0  # QBN5 pays in Mar and Jun in the fake
    assert next(m for m in out["monthly"] if m["month"] == "2026-11")["income"] == 302.6  # + AAPL 0.26 x 10
    assert out["totals"]["money_market_income"] == 3600.0
    assert out["totals"]["annual_income"] == 4210.4
    assert _flag(out, "MONEY_MARKET_ESTIMATED") == "money market income of $3,600.00 a year is estimated from seven-day yields (SPAXX 3.60%), which change often; trailing 12 months excludes it"
    assert "SPAXX" not in (_flag(out, "NO_DIVIDENDS") or "")


def test_month_end_rolls_to_the_next_month_and_skips_weekends(mixed, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2027-01-29"], capsys)
    assert rc == 0, out
    assert _row(out, "SPAXX")["next_ex_date_est"] == "2027-02-26"  # Jan 29 is January's last weekday and has arrived


def test_holdings_with_no_public_data_are_unknown_not_zero(mixed, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01"], capsys)
    assert rc == 0, out
    row = _row(out, "MYSTRY")
    assert row["income_status"] == "unknown" and row["annual_income"] is None and row["forward_yield"] is None and row["safety"] is None
    # a money market fund with no yield from this source is unknown too, never a non-payer
    assert _row(out, "FDRXX")["income_status"] == "unknown"
    assert _row(out, "GROW")["income_status"] == "no_dividends" and _row(out, "AAPL")["income_status"] == "dividends"
    assert _flag(out, "NO_DIVIDENDS") == "no dividends in history for: GROW"
    t = out["totals"]
    assert t["unknown_income_value"] == 2000.0 and t["market_value"] == 133250.0
    assert t["income_coverage"] == 0.985 and t["payer_count"] == 3 and t["position_count"] == 6
    # the yield is measured on what is known, so unknown holdings do not dilute it
    assert t["portfolio_yield"] == round(4210.4 / 131250.0, 4)
    message = _flag(out, "INCOME_UNKNOWN")
    assert message == "income unknown for $2,000.00 of holdings, counted in no income figure: FDRXX ($1,000.00), MYSTRY ($1,000.00)."


def test_unquoted_fund_counts_through_its_tracking_etf(mixed, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01"], capsys)
    assert rc == 0, out
    row = _row(out, "QBN5")
    assert row["income_status"] == "lookthrough" and row["lookthrough_proxy"] == "VOO"
    # VOO pays 2.00 a quarter on a 400 price; a 300 unit earns the same yield: 1.50 a quarter
    assert row["forward_yield"] == round(row["annual_income"] / 30000.0, 4) and row["annual_income"] > 0
    assert row["frequency"] == "quarterly" and row["annual_income"] == 600.0 and row["last_dividend"] == 1.5
    assert row["next_ex_amount_est"] == 150.0
    # an estimate of what the index earns: no trailing figures, no safety score of its own
    assert row["ttm_income"] is None and row["ttm_change"] is None and row["safety"] is None
    assert out["totals"]["lookthrough_income"] == 600.0
    assert out["totals"]["annual_income"] == 4210.4 and out["totals"]["ttm_income"] == _row(out, "AAPL")["ttm_income"]
    # its months say how much of that month is this estimate, because it is not paid out as cash
    june = next(m for m in out["monthly"] if m["month"] == "2027-06")
    assert "QBN5" in june["payers"] and june["lookthrough_income"] == 150.0
    assert next(m for m in out["monthly"] if m["month"] == "2027-01")["lookthrough_income"] == 0.0
    message = _flag(out, "LOOKTHROUGH_ESTIMATED")
    assert message.startswith("income of $600.00 a year is estimated from tracking ETFs (QBN5 via VOO)")
    assert "not paid out as cash" in message
    # MYSTRY matches no ETF and stays unknown; the proxy's history is one extra download
    assert _row(out, "MYSTRY")["income_status"] == "unknown" and "QBN5" not in _flag(out, "INCOME_UNKNOWN")
    assert mixed["histories"][-1] == ["VOO"] and len(mixed["histories"]) == 2


def test_cost_unknown_on_a_tracked_fund_keeps_yield_on_cost(mixed, capsys) -> None:
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01"], capsys)
    assert rc == 0, out
    assert out["totals"]["cost_basis"] == 100800.0 and out["totals"]["yield_on_cost"] == round(3610.4 / 100800.0, 4)


def test_tracked_fund_with_a_failed_proxy_stays_unknown(mixed, monkeypatch, capsys) -> None:
    real = market.quote
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: [] if symbols == ["VOO"] else real(symbols, hub=hub))
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01"], capsys)
    assert rc == 0, out
    assert _row(out, "QBN5")["income_status"] == "unknown" and "QBN5 ($30,000.00)" in _flag(out, "INCOME_UNKNOWN")


def test_cash_placeholder_is_a_non_payer_not_unknown(mixed, monkeypatch, capsys) -> None:
    monkeypatch.setitem(MIXED, "acc-1", [*MIXED["acc-1"], _pos("FCASH", 5, 1.0, "CASH")])
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01"], capsys)
    assert rc == 0, out
    assert _row(out, "FCASH")["income_status"] == "no_dividends"


def test_failed_quote_is_unknown_not_a_non_payer(mixed, monkeypatch, capsys) -> None:
    def boom(symbols, hub=None):
        raise RuntimeError("quote down")

    monkeypatch.setattr(market, "quote", boom)
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01"], capsys)
    assert rc == 0, out
    assert _row(out, "GROW")["income_status"] == "unknown" and _flag(out, "NO_DIVIDENDS") is None
    assert _row(out, "AAPL")["income_status"] == "dividends"


def test_yield_context_skips_money_market_funds(mixed, monkeypatch, capsys) -> None:
    calls = _patch_closes(monkeypatch, {})
    rc, out = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01", "--yield-context"], capsys)
    assert rc == 0, out
    assert calls[0][0] == ["AAPL"] and "price_1y_change" not in _row(out, "SPAXX")


def test_income_py_treats_a_symbol_with_no_history_supplied_as_unknown() -> None:
    income = load_script("dividend-income/scripts/income.py")
    out = income.run_income({"as_of": "2026-11-01", "positions": [{"symbol": "AAA", "units": 1, "price": 10.0}], "dividends": {}})
    assert out["positions"][0]["income_status"] == "unknown"
    assert out["totals"]["unknown_income_value"] == 10.0 and out["totals"]["income_coverage"] == 0.0 and out["totals"]["portfolio_yield"] is None
    assert [f["code"] for f in out["flags"]] == ["INCOME_UNKNOWN"]


def test_render_shows_unknown_income_and_money_market_on_the_page(mixed, tmp_path, capsys) -> None:
    import json

    rc, report = run_json(load_script("dividend-income/scripts/dividends.py"), ["--as-of", "2026-11-01"], capsys)
    assert rc == 0, report
    src = tmp_path / "income.json"
    src.write_text(json.dumps(report))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("dividend-income/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0, res
    html = out.read_text()
    for text in ("unknown_income_value", "Income unknown:", "seven-day yield", "lookthrough_income", "QBN5"):
        assert text in html


INCOME_REPORT = {
    "as_of": "2026-09-04",
    "sources": {"holdings": "snaptrade", "dividends": "yahoo", "fundamentals": None},
    "totals": {"annual_income": 140.8, "ttm_income": 140.6, "market_value": 6250.0, "portfolio_yield": 0.0225, "cost_basis": 6600.0, "yield_on_cost": 0.0213, "payer_count": 2, "position_count": 3, "top_payer": "CUT&CO", "top_payer_share": 0.8523},
    "positions": [
        {"symbol": "CUT&CO", "units": 100.0, "price": 40.0, "market_value": 4000.0, "cost_basis": 5000.0, "frequency": "quarterly", "payments_per_year": 4, "last_dividend": 0.3, "last_ex_date": "2026-06-20", "next_ex_date_est": "2026-09-19", "next_ex_amount_est": 30.0, "forward_rate": 1.2, "forward_yield": 0.03, "yield_on_cost": 0.024, "annual_income": 120.0, "income_share": 0.8523, "ttm_per_share": 1.2, "ttm_income": 120.0, "prior_ttm_per_share": 1.6, "ttm_change": -0.25, "growth_1y": -0.4, "growth_3y": -0.1566, "growth_5y": None, "special_ttm": 0.0, "payout_ratio": 0.95,
         "safety": {"score": 2.0, "consecutive_years": 4, "cuts_in_window": 1, "payment_cv": 0.25, "payout_ratio": 0.95, "flags": ["DIVIDEND_CUT", "DIVIDEND_UNSTABLE", "HIGH_PAYOUT"]}},
        {"symbol": "AAPL", "units": 20.0, "price": 100.0, "market_value": 2000.0, "cost_basis": 1600.0, "frequency": "quarterly", "payments_per_year": 4, "last_dividend": 0.26, "last_ex_date": "2026-08-10", "next_ex_date_est": "2026-11-09", "next_ex_amount_est": 5.2, "forward_rate": 1.04, "forward_yield": 0.0104, "yield_on_cost": 0.013, "annual_income": 20.8, "income_share": 0.1477, "ttm_per_share": 1.03, "ttm_income": 20.6, "prior_ttm_per_share": 1.0, "ttm_change": 0.03, "growth_1y": 0.0, "growth_3y": 0.0, "growth_5y": None, "special_ttm": 0.0, "payout_ratio": 0.15,
         "safety": {"score": 8.0, "consecutive_years": 4, "cuts_in_window": 0, "payment_cv": 0.0171, "payout_ratio": 0.15, "flags": []}},
        {"symbol": "GROW", "units": 5.0, "price": 50.0, "market_value": 250.0, "cost_basis": None, "frequency": None, "payments_per_year": None, "last_dividend": None, "last_ex_date": None, "next_ex_date_est": None, "next_ex_amount_est": None, "forward_rate": 0.0, "forward_yield": 0.0, "yield_on_cost": None, "annual_income": 0.0, "income_share": 0.0, "ttm_per_share": 0.0, "ttm_income": 0.0, "prior_ttm_per_share": 0.0, "ttm_change": None, "growth_1y": None, "growth_3y": None, "growth_5y": None, "special_ttm": 0.0, "payout_ratio": None, "safety": None},
    ],
    "monthly": [{"month": m, "income": inc, "payers": pay} for m, inc, pay in (("2026-09", 30.0, ["CUT&CO"]), ("2026-10", 0.0, []), ("2026-11", 5.2, ["AAPL"]), ("2026-12", 30.0, ["CUT&CO"]), ("2027-01", 0.0, []), ("2027-02", 5.2, ["AAPL"]), ("2027-03", 30.0, ["CUT&CO"]), ("2027-04", 0.0, []), ("2027-05", 5.2, ["AAPL"]), ("2027-06", 30.0, ["CUT&CO"]), ("2027-07", 0.0, []), ("2027-08", 5.2, ["AAPL"]))],
    "flags": [{"code": "DIVIDEND_CUT", "message": "trailing 12-month dividends fell for: CUT&CO (-25.0%)"}, {"code": "HIGH_PAYOUT", "message": "payout ratio above 80% for: CUT&CO (95.0%)"}, {"code": "NO_DIVIDENDS", "message": "no dividends in history for: GROW"}],
}


def test_render_builds_a_self_contained_page(tmp_path, capsys) -> None:
    import json

    src = tmp_path / "income.json"
    src.write_text(json.dumps(INCOME_REPORT))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("dividend-income/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "Dividend Income", "positions": 3, "payers": 2, "flags": 3}
    html = out.read_text()
    assert html.startswith("<title>Dividend Income</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"CUT&CO"' in html and '"next_ex_amount_est":30.0' in html  # data is JSON; the page escapes at render time
    for section in ("Income by month", "Upcoming ex-dates", "Holdings", "Flags", "Payers only"):
        assert section in html
    assert "Forward figures are the last regular dividend" in html and "not financial, tax, or legal advice" in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html
    assert "<script src" not in html and "<link" not in html and "fetch(" not in html  # nothing fetched at runtime
    assert all(u.startswith(("https://www.investopedia.com/", "http://www.w3.org/")) for u in re.findall(r"https?://[^\s\"'<>]+", html))  # only glossary links
    # plain-language layer: the explain box and glossary terms (the term spans are produced by JS at runtime, so check the script source)
    assert 'id="explain"' in html and 'class="explain"' in html and "data-term=" in html
    assert "FA.explain(" in html and "FA.term(" in html and "FA.armTerms(" in html
    assert "Object.assign(FA.glossary, {" in html and '"forward dividend rate"' in html and '"dividend growth"' in html


def test_render_rejects_non_income_input(tmp_path, capsys) -> None:
    src = tmp_path / "bad.json"
    src.write_text('{"totals": {"total_value": 1}, "positions": []}')  # a snapshot, not an income report
    rc, res = run_json(load_script("dividend-income/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "income.py result" in res["error"]
    src.write_text("not json")
    rc, res = run_json(load_script("dividend-income/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    import json

    src = tmp_path / "income.json"
    src.write_text(json.dumps(INCOME_REPORT))
    assert_page_help(render_and_audit("dividend-income/scripts/render.py", ["--in", str(src)], tmp_path, capsys))
