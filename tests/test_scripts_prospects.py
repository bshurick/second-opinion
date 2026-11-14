from __future__ import annotations

import json

from scripts_util import load_script, run_json

prospects = load_script("stock-screener/scripts/prospects.py")


def _edgar(*, ups=6, fcf=(50e6, 60e6, 70e6, 80e6), dividends=20e6, ni_ttm=96e6, ni_prior=80e6):
    """An edgar.py report: 12 quarters (the last 8 with ``ups`` year-over-year rises), 4 annual years."""
    quarterly = []
    for i in range(12):
        y, q = 2024 + i // 4, i % 4
        last8 = i - 4
        yoy = None if i < 4 else (0.08 if last8 < ups else -0.03)
        ni = (ni_ttm if i >= 8 else ni_prior) / 4
        quarterly.append({"fiscal_year": y, "period_end": f"{y}-{(q + 1) * 3:02d}-28", "revenue": 200e6,
                          "net_income": ni, "revenue_yoy": yoy, "derived": False})
    annual = [{"fiscal_year": 2022 + i, "free_cash_flow": v, "dividends_paid": dividends, "revenue": 780e6}
              for i, v in enumerate(fcf)]
    return {"symbol": "AAA", "company": "Acme Corp", "annual": annual, "quarterly": quarterly,
            "ttm": {"revenue": 800e6, "net_income": ni_ttm, "revenue_ttm_yoy": 0.05}, "flags": []}


def _info(**over):
    base = {"name": "Acme Corporation", "market_cap": 1.0e9, "pe_ratio": 11.0, "forward_pe": 10.0,
            "current_price": 45.0, "52_week_high": 50.0, "analyst_count": 3, "institutional_ownership": 0.85}
    return {**base, **over}


def _patch(monkeypatch, reports, infos=None, changes=None):
    def report(sym):
        r = reports.get(sym)
        if r is None:
            return 2, {"error": f"{sym} is not in the SEC ticker list", "code": "INVALID_INPUT"}
        return r if isinstance(r, tuple) else (0, r)

    def info(sym):
        v = (infos or {}).get(sym, _info())
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(prospects, "edgar_report", report)
    monkeypatch.setattr(prospects.market, "company_info", info)
    monkeypatch.setattr(prospects, "price_changes", lambda syms: {s: (changes or {}).get(s) for s in syms})


def test_all_four_tests_pass(monkeypatch, capsys):
    _patch(monkeypatch, {"AAA": _edgar()}, changes={"AAA": 0.05})
    rc, out = run_json(prospects, ["aaa"], capsys)
    assert rc == 0 and out["as_of"] and out["not_found"] == []
    p = out["prospects"][0]
    assert p["ticker"] == "AAA" and p["name"] == "Acme Corporation" and p["market_cap"] == 1.0e9
    assert p["tests_passed"] == 4 and p["size_ok"] is True
    t = p["tests"]
    assert t["trajectory"] == {"pass": True, "figures": {"quarters_up_of_8": 6, "ttm_revenue_growth": 0.05,
                                                         "net_margin_ttm": 0.12, "net_margin_prior_ttm": 0.1}}
    assert t["cash"] == {"pass": True, "figures": {"fcf_positive_years_of_4": 4, "dividends_covered": True}}
    assert t["price"]["pass"] is True
    assert t["price"]["figures"] == {"pe": 11.0, "forward_pe": 10.0, "fcf_yield": 0.08, "change_12m": 0.05, "pct_of_52w_high": 0.9}
    assert t["overlooked"] == {"pass": True, "figures": {"analyst_count": 3, "institutional_ownership": 0.85, "change_12m": 0.05}}
    for word in ("trajectory", "cash", "price", "overlooked", "6 of 8", "4 of 4", "P/E 11", "3 analysts"):
        assert word in p["why"]


def test_price_is_null_not_failed_when_neither_figure_is_cheap(monkeypatch, capsys):
    _patch(monkeypatch, {"AAA": _edgar(fcf=(10e6, 12e6, 15e6, 20e6), dividends=None)},
           infos={"AAA": _info(pe_ratio=30.0, analyst_count=22)}, changes={"AAA": 0.3})
    rc, out = run_json(prospects, ["AAA"], capsys)
    p = out["prospects"][0]
    assert p["tests"]["price"]["pass"] is None and p["tests"]["price"]["figures"]["fcf_yield"] == 0.02
    assert p["tests"]["cash"]["figures"]["dividends_covered"] is True  # nothing paid
    assert p["tests"]["overlooked"]["pass"] is False
    assert p["tests_passed"] == 2 and "price" not in p["why"] and "overlooked" not in p["why"]


def test_failing_trajectory_and_cash(monkeypatch, capsys):
    _patch(monkeypatch, {"AAA": _edgar(ups=4, fcf=(-5e6, -1e6, 30e6, 10e6), dividends=20e6, ni_ttm=60e6)})
    _, out = run_json(prospects, ["AAA"], capsys)
    t = out["prospects"][0]["tests"]
    assert t["trajectory"]["pass"] is False and t["trajectory"]["figures"]["quarters_up_of_8"] == 4
    assert t["cash"]["pass"] is False
    assert t["cash"]["figures"] == {"fcf_positive_years_of_4": 2, "dividends_covered": False}


def test_missing_figures_give_null_tests(monkeypatch, capsys):
    report = _edgar()
    report["quarterly"], report["ttm"], report["annual"] = [], {"revenue": None, "net_income": None, "revenue_ttm_yoy": None}, []
    _patch(monkeypatch, {"AAA": report}, infos={"AAA": RuntimeError("429")})
    rc, out = run_json(prospects, ["AAA"], capsys)
    assert rc == 0
    p = out["prospects"][0]
    assert p["name"] == "Acme Corp" and p["market_cap"] is None and p["size_ok"] is None
    assert [p["tests"][k]["pass"] for k in ("trajectory", "cash", "price", "overlooked")] == [None] * 4
    assert p["tests"]["trajectory"]["figures"]["quarters_up_of_8"] is None
    assert p["tests_passed"] == 0 and p["why"] == ""
    assert "QUOTE_UNAVAILABLE" in p["flags"]
    assert "QUOTE_UNAVAILABLE" in [f["code"] for f in out["flags"]]


def test_overlooked_on_a_fall_and_small_size(monkeypatch, capsys):
    _patch(monkeypatch, {"AAA": _edgar()}, infos={"AAA": _info(analyst_count=20, market_cap=2.0e8)}, changes={"AAA": -0.35})
    _, out = run_json(prospects, ["AAA"], capsys)
    p = out["prospects"][0]
    assert p["tests"]["overlooked"]["pass"] is True and "down 35" in p["why"]
    assert p["size_ok"] is False


def test_unknown_ticker_and_edgar_failure(monkeypatch, capsys, tmp_path):
    _patch(monkeypatch, {"AAA": _edgar(), "CCC": (5, {"error": "EDGAR returned HTTP 503", "code": "EDGAR_HTTP"}),
                         "DDD": (2, {"error": "no us-gaap facts", "code": "INVALID_INPUT"})})
    dest = tmp_path / "out" / "p.json"
    rc, out = run_json(prospects, ["AAA,ZZZZ,CCC,DDD", "--out", str(dest)], capsys)
    assert rc == 0
    assert out["not_found"] == ["ZZZZ"]
    assert [p["ticker"] for p in out["prospects"]] == ["AAA", "CCC", "DDD"]
    assert "no us-gaap facts" in out["flags"][0]["message"]
    assert "EDGAR_UNAVAILABLE" in out["prospects"][1]["flags"] and out["prospects"][1]["tests"]["cash"]["pass"] is None
    assert json.loads(dest.read_text())["not_found"] == ["ZZZZ"]


def test_too_many_or_bad_symbols(monkeypatch, capsys):
    _patch(monkeypatch, {})
    rc, out = run_json(prospects, [",".join(f"S{chr(65 + i)}" for i in range(26))], capsys)
    assert rc == 2 and "error" in out
    rc, _ = run_json(prospects, ["AAA,$$"], capsys)
    assert rc == 2
    rc, _ = run_json(prospects, [","], capsys)
    assert rc == 2


def test_change_from_closes():
    bars = [{"date": "2025-11-07", "close": 80.0}, {"date": "2025-11-10", "close": 100.0}, {"date": "2026-11-09", "close": 75.0}]
    assert prospects.change_12m(bars) == -0.25
    assert prospects.change_12m(bars[1:2]) is None
    assert prospects.change_12m([{"date": "2026-08-01", "close": 90.0}, {"date": "2026-11-09", "close": 75.0}]) is None


def test_dotted_class_is_looked_up_with_a_dash(monkeypatch, capsys):
    report = _edgar()
    report["flags"] = [{"code": "BANK_REVENUE_PROXY", "message": "m"}, {"code": "LEVERAGE", "message": "m"}]
    _patch(monkeypatch, {"BRK-B": report}, infos={"BRK-B": _info(analyst_count=1)}, changes={"BRK.B": 0.1})
    rc, out = run_json(prospects, ["BRK.B"], capsys)
    p = out["prospects"][0]
    assert p["ticker"] == "BRK.B" and p["tests_passed"] == 4 and "1 analyst;" not in p["why"] and p["why"].endswith("1 analyst")
    assert p["flags"] == ["BANK_REVENUE_PROXY"]


def _growth(ups=6, ttm=0.15, annual=None):
    """A report for the growth tests: ``annual`` rows (oldest first) replace the default four."""
    r = _edgar(ups=ups)
    r["ttm"]["revenue_ttm_yoy"] = ttm
    if annual is not None:
        r["annual"] = annual
    return r


def _rows(*overrides, revenue=(500e6, 600e6, 700e6, 800e6)):
    return [{"fiscal_year": 2022 + i, "revenue": revenue[i], **o} for i, o in enumerate(overrides)]


def _growth_test(report, name):
    return prospects.prospect("AAA", report, _info(), 0.0, profile="growth")["tests"][name]


def test_growth_trajectory():
    assert _growth_test(_growth(ups=6, ttm=0.15), "trajectory")["pass"] is True
    assert _growth_test(_growth(ups=5, ttm=0.30), "trajectory")["pass"] is False
    assert _growth_test(_growth(ups=7, ttm=0.12), "trajectory")["pass"] is False
    t = _growth_test(_growth(ups=6, ttm=0.15), "trajectory")
    assert t["figures"] == {"quarters_up_of_8": 6, "ttm_revenue_growth": 0.15}
    r = _growth(ups=6)
    r["ttm"].pop("revenue_ttm_yoy")
    assert _growth_test(r, "trajectory")["pass"] is None


def test_growth_funded():
    def funded(**last):
        base = {"free_cash_flow": 10e6, "operating_income": 50e6}
        return _growth_test(_growth(annual=_rows({}, {}, {}, {**base, **last})), "funded")

    assert funded(cash=20e6)["pass"] is True
    t = funded(free_cash_flow=-40e6, cash=60e6, short_term_investments=40e6, operating_income=-30e6)
    assert t["pass"] is True and t["figures"]["runway_years"] == 2.5
    assert funded(free_cash_flow=-60e6, cash=60e6, short_term_investments=40e6)["pass"] is False
    assert funded(long_term_debt=250e6, cash=0)["pass"] is False  # net debt 5x operating income
    assert funded(long_term_debt=200e6, cash=0)["pass"] is True  # exactly 4x
    assert funded(long_term_debt=100e6, operating_income=-5e6, cash=10e6)["pass"] is False
    assert funded(long_term_debt=100e6, operating_income=-5e6, cash=150e6)["pass"] is True  # net cash
    assert funded(free_cash_flow=None)["pass"] is None


def test_growth_reinvestment():
    def reinv(*rows, revenue=(500e6, 600e6, 700e6, 800e6)):
        return _growth_test(_growth(annual=_rows(*rows, revenue=revenue)), "reinvestment")

    rich = reinv({}, {}, {}, {"research_and_development": 66e6, "capex": 30e6})  # 12% of 800M
    assert rich["pass"] is True and rich["figures"]["reinvestment_to_revenue"] == 0.12
    # 6% of revenue (48M of 800M); revenue is up 60% over the three years
    assert reinv({"research_and_development": 20e6, "capex": 5e6}, {}, {}, {"research_and_development": 30e6, "capex": 18e6})["pass"] is True  # spending +92%
    assert reinv({"research_and_development": 40e6, "capex": 20e6}, {}, {}, {"research_and_development": 30e6, "capex": 18e6})["pass"] is False  # spending -20%
    assert reinv({}, {}, {}, {"capex": 20e6})["pass"] is None  # 2.5% and no earlier figures
    assert reinv({}, {}, {}, {})["pass"] is None
    assert reinv({}, {}, {}, {})["figures"]["reinvestment_to_revenue"] is None


def test_growth_scale():
    def scale(*margins):
        rows = [{"gross_profit": None if m is None else m * 100e6} for m in margins]
        annual = [{"fiscal_year": 2021 + i, "revenue": 100e6, **row} for i, row in enumerate(rows)]
        return _growth_test(_growth(annual=annual), "scale")

    assert scale(0.40, 0.41, 0.42, 0.45)["pass"] is True
    assert scale(0.25, 0.27, 0.28, 0.30)["pass"] is True
    assert scale(0.30, 0.30, 0.30, 0.30)["pass"] is False
    assert scale(0.25, 0.28, 0.27, 0.30)["pass"] is False
    assert scale(None, None, None, None)["pass"] is None
    assert scale(0.30, 0.31)["pass"] is None  # too few years to call it falling or rising
    assert scale(0.30, 0.31)["figures"]["gross_margin"] == 0.31


def test_growth_rows_keep_the_row_shape():
    row = prospects.prospect("AAA", _growth(), _info(), 0.0, profile="growth")
    assert set(row["tests"]) == {"trajectory", "funded", "reinvestment", "scale"}
    assert {"ticker", "name", "market_cap", "tests_passed", "size_ok", "why", "flags"} <= set(row)
    assert row["tests_passed"] == sum(1 for t in row["tests"].values() if t["pass"] is True)


def test_value_profile_rows_unchanged():
    row = prospects.prospect("AAA", _edgar(), _info(), 0.0)
    assert set(row["tests"]) == {"trajectory", "cash", "price", "overlooked"}
    assert row == prospects.prospect("AAA", _edgar(), _info(), 0.0, profile="value")


def test_profile_flag_reaches_the_rows(monkeypatch, capsys):
    _patch(monkeypatch, {"AAA": _growth()})
    rc, out = run_json(prospects, ["AAA", "--profile", "growth"], capsys)
    assert rc == 0 and set(out["prospects"][0]["tests"]) == {"trajectory", "funded", "reinvestment", "scale"}
    assert run_json(prospects, ["AAA", "--profile", "bogus"], capsys)[0] == 2
