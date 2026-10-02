from __future__ import annotations

import json
from datetime import date

import pytest
from scripts_util import load_script, run_json
from second_opinion import market
from page_dom import assert_page_help, render_and_audit, requires_chrome

CHAIN = {
    "symbol": "AAPL", "spot": 100.0, "expiry": "2026-10-16", "expiries": ["2026-09-18", "2026-10-16"],
    "calls": [{"contract": f"C{k}", "strike": float(k), "last": 1.2, "bid": 1.0, "ask": 1.4, "volume": 10, "open_interest": 100, "implied_volatility": 0.2, "in_the_money": k < 100} for k in (90, 95, 100, 105, 110)],
    "puts": [{"contract": f"P{k}", "strike": float(k), "last": 1.2, "bid": 1.0, "ask": 1.4, "volume": 10, "open_interest": 100, "implied_volatility": 0.22, "in_the_money": k > 100} for k in (90, 95, 100, 105, 110)],
}

DEEP_CHAIN = {
    "symbol": "AAPL", "spot": 100.0, "expiry": "2026-10-16", "expiries": ["2026-10-16"],
    "calls": [
        {"contract": "C60", "strike": 60.0, "last": 40.0, "bid": 39.9, "ask": 40.1, "volume": 5, "open_interest": 50, "implied_volatility": 0.10, "in_the_money": True},
        {"contract": "C100", "strike": 100.0, "last": 1.2, "bid": 1.0, "ask": 1.4, "volume": 100, "open_interest": 1000, "implied_volatility": 0.20, "in_the_money": False},
    ],
    "puts": [
        {"contract": "P100", "strike": 100.0, "last": 1.2, "bid": 1.0, "ask": 1.4, "volume": 300, "open_interest": 1500, "implied_volatility": 0.22, "in_the_money": False},
        {"contract": "P150", "strike": 150.0, "last": 50.0, "bid": 49.9, "ask": 50.1, "volume": 5, "open_interest": 50, "implied_volatility": 0.10, "in_the_money": True},
    ],
}


@pytest.fixture
def yahoo(monkeypatch):
    calls: dict[str, list] = {"chain": [], "history": [], "quote": [], "info": [], "events": []}

    def option_chain(symbol, expiry=None):
        calls["chain"].append((symbol, expiry))
        return dict(CHAIN, expiry=expiry or CHAIN["expiry"])

    def price_history(symbol, period="1y", start=None, end=None, interval="1d"):
        calls["history"].append((symbol, period))
        return {"symbol": symbol, "prices": [{"date": f"2026-01-{d:02d}", "close": 100.0} for d in range(1, 29)]}

    def quote(symbols):
        calls["quote"].append(tuple(symbols))
        return [{"symbol": "^IRX", "price": 3.5, "previous_close": 3.5, "change_pct": 0.0, "currency": "USD"}]

    def company_info(symbol):
        calls["info"].append(symbol)
        return {"symbol": symbol.upper(), "dividend_yield": 0.005}

    def next_events(symbol, today=None):
        calls["events"].append(symbol)
        return {"next_earnings": "2026-09-25", "next_ex_dividend": "2026-09-10"}

    monkeypatch.setattr(market, "option_chain", option_chain)
    monkeypatch.setattr(market, "price_history", price_history)
    monkeypatch.setattr(market, "quote", quote)
    monkeypatch.setattr(market, "company_info", company_info)
    monkeypatch.setattr(market, "next_events", next_events)
    return calls


def test_chain_script_summarises_with_hv(yahoo, capsys) -> None:
    rc, out = run_json(load_script("options/scripts/chain.py"), ["aapl", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["symbol"] == "AAPL" and out["expiry"] == "2026-10-16" and out["expiries"] == ["2026-09-18", "2026-10-16"]
    assert out["days"] == 42 and out["atm_strike"] == 100.0 and out["atm_iv"] == 0.21 and out["hv_30"] == 0.0
    assert out["max_pain"] == 100.0 and len(out["strikes"]) == 5
    assert yahoo["chain"] == [("AAPL", None)] and yahoo["history"] == [("AAPL", "6mo")]
    # real risk-free rate (^IRX at 3.5) and dividend yield, echoed under sources
    assert out["rate"] == 0.035 and out["dividend_yield"] == 0.005
    assert yahoo["quote"] == [("^IRX",)] and yahoo["info"] == ["AAPL"]
    assert out["sources"] == {
        "chain": "yahoo",
        "history": "yahoo",
        "rate": "yahoo (^IRX)",
        "dividend_yield": "yahoo",
        "events": "yahoo",
    }
    # next events with in-expiry flags
    assert out["next_earnings"] == "2026-09-25" and out["earnings_in_expiry"] is True
    assert out["next_ex_dividend"] == "2026-09-10" and out["ex_dividend_in_expiry"] is True
    assert out["ex_dividend_days"] == 6


def test_chain_script_expiry_and_no_history(yahoo, capsys) -> None:
    rc, out = run_json(load_script("options/scripts/chain.py"), ["AAPL", "--expiry", "2026-09-18", "--no-history", "--as-of", "2026-09-04"], capsys)
    assert rc == 0 and out["expiry"] == "2026-09-18" and out["days"] == 14 and out["hv_30"] is None
    assert yahoo["chain"] == [("AAPL", "2026-09-18")] and yahoo["history"] == [] and out["sources"]["history"] is None


def test_chain_script_events_beyond_expiry_flagged_false(yahoo, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        market, "next_events", lambda s, today=None: {"next_earnings": "2026-12-18", "next_ex_dividend": "2026-11-20"}
    )
    rc, out = run_json(load_script("options/scripts/chain.py"), ["AAPL", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["earnings_in_expiry"] is False and out["ex_dividend_in_expiry"] is False
    assert out["ex_dividend_days"] is None  # no ex-dividend date is passed to options.py


def test_chain_script_rate_and_events_degrade_gracefully(monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "option_chain", lambda symbol, expiry=None: dict(CHAIN, expiry=expiry or CHAIN["expiry"]))

    def boom(symbols):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "quote", boom)
    monkeypatch.setattr(market, "company_info", lambda s: {"symbol": s.upper()})  # no dividend_yield
    monkeypatch.setattr(market, "next_events", lambda s, today=None: {"next_earnings": None, "next_ex_dividend": None})
    rc, out = run_json(load_script("options/scripts/chain.py"), ["AAPL", "--no-history", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    # options.py's documented defaults apply when Yahoo could not fill the fields
    assert out["rate"] == 0.04 and out["dividend_yield"] == 0.0
    assert out["next_earnings"] is None and out["earnings_in_expiry"] is False
    assert out["sources"]["rate"] is None and out["sources"]["dividend_yield"] is None
    assert out["sources"]["events"] is None


def test_chain_script_normalizes_percentage_dividend_yield(yahoo, monkeypatch, capsys) -> None:
    # live Yahoo reports AAPL's yield in percentage points (e.g. 0.33 for 0.33%)
    monkeypatch.setattr(market, "company_info", lambda s: {"symbol": s.upper(), "dividend_yield": 0.33})
    rc, out = run_json(load_script("options/scripts/chain.py"), ["AAPL", "--no-history", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["dividend_yield"] == 0.0033


def test_chain_script_flags_assignment_candidates(yahoo, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        market, "option_chain", lambda symbol, expiry=None: dict(DEEP_CHAIN, expiry=expiry or DEEP_CHAIN["expiry"])
    )
    rc, out = run_json(load_script("options/scripts/chain.py"), ["AAPL", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    cands = out["assignment_candidates"]
    assert [(c["type"], c["strike"]) for c in cands] == [("call", 60.0), ("put", 150.0)]
    assert cands[0]["mid"] == 40.0 and cands[0]["exercise_gain"] == 0.125  # 0.005 * 100 / 4
    assert any("ex-dividend in 6 days" in r for r in cands[0]["reasons"])
    assert cands[1]["exercise_gain"] == round(0.035 * 150 * 42 / 365, 4)  # ^IRX 3.5% on the 150 strike
    assert any("interest on strike" in r for r in cands[1]["reasons"])


def test_chain_script_term_structure(yahoo, monkeypatch, capsys) -> None:
    expiries = [
        "2026-09-18", "2026-09-25", "2026-10-02", "2026-10-16",
        "2026-11-20", "2026-12-18", "2027-01-15", "2027-06-18",
    ]

    def option_chain(symbol, expiry=None):
        yahoo["chain"].append((symbol, expiry))
        return dict(CHAIN, expiry=expiry or expiries[0], expiries=expiries)

    monkeypatch.setattr(market, "option_chain", option_chain)
    rc, out = run_json(load_script("options/scripts/chain.py"), ["AAPL", "--term-structure", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    rows = out["rows"]
    assert len(rows) == 6  # ~6 of the 8 listed expiries, evenly spread front to back
    assert rows[0]["expiry"] == "2026-09-18" and rows[-1]["expiry"] == "2027-06-18"
    assert rows[0]["days"] == 14 and rows[-1]["days"] == (date(2027, 6, 18) - date(2026, 9, 4)).days
    assert out["front"]["expiry"] == "2026-09-18" and out["back"]["expiry"] == "2027-06-18"
    assert out["iv_term_shape"] == "flat"  # identical fake rows front to back
    assert set(rows[0]) == {
        "expiry", "days", "atm_strike", "atm_iv", "atm_straddle",
        "iv_move_pct", "straddle_move_pct", "put_skew",
    }
    # the base fetch is reused for the front expiry; no rate/events fetches happen here
    assert len(yahoo["chain"]) == 6 and yahoo["quote"] == [] and yahoo["events"] == []
    assert out["sources"] == {"chain": "yahoo"}


def test_chain_script_bad_expiry_exit_2(monkeypatch, capsys) -> None:
    def boom(symbol, expiry=None):
        raise ValueError("2026-12-31 is not an available expiry")

    monkeypatch.setattr(market, "option_chain", boom)
    rc, out = run_json(load_script("options/scripts/chain.py"), ["AAPL", "--expiry", "2026-12-31"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT" and "not an available expiry" in out["error"]


def test_options_math_script_runs_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "expected_move", "spot": 100, "iv": 0.2, "days": 30})))
    mod = load_script("options/scripts/options.py")
    mod.main()
    assert json.loads(capsys.readouterr().out)["move_1sd"] == 5.7338


def test_options_math_term_structure_and_early_assignment() -> None:
    mod = load_script("options/scripts/options.py")
    out = mod.run_options(
        {
            "action": "term_structure",
            "spot": 100,
            "as_of": "2026-09-04",
            "expiries": [
                {
                    "expiry": "2026-09-18",
                    "calls": [{"strike": 100, "bid": 3.0, "ask": 3.4, "implied_volatility": 0.3}],
                    "puts": [{"strike": 100, "bid": 2.7, "ask": 3.1, "implied_volatility": 0.3}],
                },
                {
                    "expiry": "2026-10-16",
                    "calls": [{"strike": 100, "bid": 4.4, "ask": 4.8, "implied_volatility": 0.25}],
                    "puts": [{"strike": 100, "bid": 3.9, "ask": 4.3, "implied_volatility": 0.25}],
                },
            ],
        }
    )
    assert [r["days"] for r in out["rows"]] == [14, 42]
    assert out["rows"][0]["atm_straddle"] == 6.1
    assert out["iv_term_shape"] == "falling"
    greeks = mod.run_options(
        {"action": "greeks", "spot": 100, "strike": 130, "type": "put", "days": 30, "iv": 0.15, "rate": 0.06}
    )
    assert greeks["early_assignment"]["plausible"] is True

def test_render_builds_a_self_contained_page(tmp_path, capsys) -> None:
    mod = load_script("options/scripts/options.py")
    chain = mod.run_options({"action": "chain", "spot": 100.0, "expiry": "2026-10-16", "as_of": "2026-09-04", "rate": 0.035,
                             "calls": CHAIN["calls"], "puts": CHAIN["puts"], "history": [{"date": f"2026-01-{d:02d}", "close": 100.0 + d % 3} for d in range(1, 29)]})
    payoff = mod.run_options({"action": "payoff", "spot": 100.0, "iv": 0.2, "days": 42, "legs": [
        {"type": "call", "side": "long", "strike": 100, "premium": 1.2}, {"type": "call", "side": "short", "strike": 110, "premium": 1.2}]})
    data = {
        "chain": {"symbol": "A&B", "expiries": CHAIN["expiries"], "next_earnings": "2026-09-25", "next_ex_dividend": None, "earnings_in_expiry": True,
                  "ex_dividend_in_expiry": False, "sources": {"chain": "yahoo", "history": "yahoo", "rate": "yahoo (^IRX)", "dividend_yield": None, "events": "yahoo"},
                  **chain, "assignment_candidates": [{"type": "put", "strike": 110.0, "mid": 10.1, "time_value": 0.1, "exercise_gain": 0.4, "ex_dividend_days": None, "reasons": ["deep ITM </b> (delta -0.95)"]}]},
        "payoff": payoff,
        "legs": [{"type": "call", "side": "long", "strike": 100, "premium": 1.2, "qty": 1}, {"type": "call", "side": "short", "strike": 110, "premium": 1.2, "qty": 1}],
    }
    src = tmp_path / "options.json"
    src.write_text(json.dumps(data))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("options/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res["out"] == str(out) and res["symbol"] == "A&B" and res["strikes"] == 5 and res["payoff"] is True
    html = out.read_text()
    assert html.startswith("<title>A&amp;B Options</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"bull call spread"' in html and "</b> (delta" not in html  # data is JSON; tags stay escaped at render time
    assert 'id="chain"' in html and 'id="payoff"' in html and 'id="cone"' in html and 'id="assign"' in html and 'id="risks"' in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html
    assert "not financial, tax, or legal advice" in html
    # plain-language layer: the explain box slot and the glossary calls (term spans are produced by JS at runtime)
    assert 'id="explain"' in html and 'class="explain"' in html and "data-term=" in html
    assert "FA.explain(" in html and "FA.term(" in html and "Object.assign(F.glossary, {" in html
    assert '"at the money": [' in html and '"historical volatility": [' in html  # local glossary additions for this page


def test_render_accepts_a_bare_chain_result_and_rejects_other_input(tmp_path, capsys) -> None:
    mod = load_script("options/scripts/options.py")
    chain = mod.run_options({"action": "chain", "spot": 100.0, "days": 42, "calls": CHAIN["calls"], "puts": CHAIN["puts"]})
    src = tmp_path / "chain.json"
    src.write_text(json.dumps({"symbol": "AAPL", "expiries": [], "sources": {"chain": "yahoo"}, **chain}))
    rc, res = run_json(load_script("options/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "a.html")], capsys)
    assert rc == 0 and res["title"] == "AAPL Options" and res["payoff"] is False
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": 1}')
    rc, res = run_json(load_script("options/scripts/render.py"), ["--in", str(bad), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "chain.py result" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    mod = load_script("options/scripts/options.py")
    chain = mod.run_options({"action": "chain", "spot": 100.0, "expiry": "2026-10-16", "as_of": "2026-09-04", "rate": 0.035,
                             "calls": CHAIN["calls"], "puts": CHAIN["puts"], "history": [{"date": f"2026-01-{d:02d}", "close": 100.0 + d % 3} for d in range(1, 29)]})
    payoff = mod.run_options({"action": "payoff", "spot": 100.0, "iv": 0.2, "days": 42, "legs": [
        {"type": "call", "side": "long", "strike": 100, "premium": 1.2}, {"type": "call", "side": "short", "strike": 110, "premium": 1.2}]})
    data = {"chain": {"symbol": "AB", "expiries": CHAIN["expiries"], **chain,
                      "assignment_candidates": [{"type": "put", "strike": 110.0, "mid": 10.1, "time_value": 0.1, "exercise_gain": 0.4, "ex_dividend_days": None, "reasons": ["deep ITM"]}]},
            "payoff": payoff}
    src = tmp_path / "options.json"
    src.write_text(json.dumps(data))
    assert_page_help(render_and_audit("options/scripts/render.py", ["--in", str(src)], tmp_path, capsys))
