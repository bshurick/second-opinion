from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json
from second_opinion import market
from page_dom import assert_page_help, render_and_audit, requires_chrome


@pytest.fixture
def yahoo(monkeypatch):
    calls: list[str] = []

    def company_info(symbol):
        calls.append(("info", symbol))
        return {"symbol": symbol, "name": "Realty Income", "sector": "Real Estate", "industry": "REIT - Retail", "current_price": 50.0, "shares_outstanding": 100_000_000, "dividend_yield": 0.06, "market_cap": 5e9}

    def financials(symbol, quarterly=False):
        calls.append(("financials", symbol))
        return {
            "symbol": symbol, "quarterly": False,
            "income_statement": {"2025-12-31": {"Net Income": 200e6, "Gain On Sale Of Security": 50e6}, "2024-12-31": {"Net Income": 180e6}},
            "cash_flow": {"2025-12-31": {"Depreciation And Amortization": 250e6, "Capital Expenditure": -40e6}, "2024-12-31": {"Depreciation And Amortization": 240e6}},
            "balance_sheet": {},
        }

    def dividends(symbol):
        calls.append(("dividends", symbol))
        return {"symbol": symbol, "count": 4, "dividends": [{"date": f"2026-{m:02d}-15", "dividend": 0.75} for m in (1, 4, 7, 8)]}

    monkeypatch.setattr(market, "company_info", company_info)
    monkeypatch.setattr(market, "financials", financials)
    monkeypatch.setattr(market, "dividends", dividends)
    return calls


def test_reit_script_builds_ffo_from_statements(yahoo, capsys) -> None:
    rc, out = run_json(load_script("real-estate/scripts/reit.py"), ["o", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["symbol"] == "O" and out["name"] == "Realty Income" and out["fiscal_year"] == "2025-12-31"
    assert out["inputs"] == {"price": 50.0, "shares": 100_000_000.0, "net_income": 200e6, "depreciation": 250e6, "gains_on_sale": 50e6, "recurring_capex": 40e6, "dividend_per_share": 3.0, "nav_per_share": None}
    assert out["ffo_per_share"] == 4.0 and out["p_ffo"] == 12.5 and out["dividend_yield"] == 0.06 and out["ffo_payout"] == 0.75
    assert out["sources"] == {"statements": "yahoo", "dividends": "yahoo"} and out["notes"]
    assert [c[0] for c in yahoo] == ["info", "financials", "dividends"]


def test_reit_script_not_a_reit_still_reports(monkeypatch, yahoo, capsys) -> None:
    monkeypatch.setattr(market, "company_info", lambda s: {"symbol": s, "name": "Apple", "sector": "Technology", "industry": "Consumer Electronics", "current_price": 100.0, "shares_outstanding": 1e9})
    rc, out = run_json(load_script("real-estate/scripts/reit.py"), ["AAPL", "--as-of", "2026-09-04"], capsys)
    assert rc == 0 and out["is_reit"] is False and "not classified as a REIT" in out["notes"][0]


def test_reit_script_missing_statements_exit_5(monkeypatch, yahoo, capsys) -> None:
    monkeypatch.setattr(market, "financials", lambda s, quarterly=False: {"symbol": s, "income_statement": {}, "cash_flow": {}, "balance_sheet": {}})
    rc, out = run_json(load_script("real-estate/scripts/reit.py"), ["O"], capsys)
    assert rc == 5 and out["code"] == "NO_STATEMENTS"


def _run_math(payload: dict, capsys, monkeypatch) -> dict:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("real-estate/scripts/realestate.py").main()
    return json.loads(capsys.readouterr().out)


def test_realestate_math_script_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"action": "mortgage", "principal": 100000, "rate": 0.12, "years": 1})))
    load_script("real-estate/scripts/realestate.py").main()
    assert json.loads(capsys.readouterr().out)["payment"] == 8884.88


def test_realestate_mortgage_pmi_steps_off_at_80pct_ltv(capsys, monkeypatch) -> None:
    out = _run_math({"action": "mortgage", "price": 375000, "down_payment": 37500, "rate": 0.06, "years": 30, "pmi_rate": 0.005}, capsys, monkeypatch)
    assert out["months"] == 360 and out["pmi_monthly"] == 140.62
    rows = {r["year"]: r for r in out["schedule"]}
    assert rows[7]["pmi"] == 1687.44 and rows[8]["pmi"] == 703.1 and rows[9]["pmi"] == 0.0
    assert out["pmi_off_year"] == 8 and out["pmi_total"] == 12515.18


def test_realestate_mortgage_pmi_never_applies_at_20pct_down(capsys, monkeypatch) -> None:
    out = _run_math({"action": "mortgage", "price": 375000, "down_payment": 75000, "rate": 0.06, "years": 30, "pmi_rate": 0.005}, capsys, monkeypatch)
    assert out["pmi_total"] == 0.0 and out["pmi_off_year"] is None
    assert all(r["pmi"] == 0.0 for r in out["schedule"])


def test_realestate_mortgage_pmi_never_applies_without_price(capsys, monkeypatch) -> None:
    # principal + down_payment without price is inert for PMI/LTV: no basis
    # to derive down_payment_pct, so PMI never charges (unchanged from before
    # this task), and the loan math itself is unaffected.
    out = _run_math(
        {"action": "mortgage", "principal": 300000, "down_payment": 37500, "rate": 0.06, "years": 30, "pmi_rate": 0.005},
        capsys,
        monkeypatch,
    )
    assert out["payment"] == 1798.65 and out["months"] == 360
    assert out["down_payment_pct"] is None
    assert out["pmi_monthly"] == 0.0 and out["pmi_total"] == 0.0
    assert out["pmi_off_year"] is None and all(r["pmi"] == 0.0 for r in out["schedule"])


def test_realestate_rental_capex_and_leasing_rates(capsys, monkeypatch) -> None:
    out = _run_math(
        {
            "action": "rental", "price": 200000, "down_payment": 50000, "rate": 0.07, "years": 30,
            "closing_costs": 4000, "rent": 2000, "vacancy_rate": 0.05, "property_tax_annual": 2400,
            "insurance_annual": 1200, "maintenance_rate": 0.05, "management_rate": 0.08,
            "capex_reserve_rate": 0.03, "leasing_rate": 0.05,
        },
        capsys,
        monkeypatch,
    )
    assert out["operating_expenses"] == 8388.0 and out["noi"] == 14412.0
    assert out["cash_on_cash"] == 0.0451


def test_realestate_rental_scenarios_grid(capsys, monkeypatch) -> None:
    base = {
        "action": "rental", "price": 200000, "down_payment": 50000, "rate": 0.07, "years": 30,
        "closing_costs": 4000, "rent": 2000, "vacancy_rate": 0.05, "property_tax_annual": 2400,
        "insurance_annual": 1200, "maintenance_rate": 0.05, "management_rate": 0.08,
        "hold_years": 5, "rent_growth": 0.03, "expense_growth": 0.02, "appreciation": 0.03,
        "sell_closing_rate": 0.06,
    }
    out = _run_math({**base, "scenarios": True}, capsys, monkeypatch)
    rows = out["scenarios"]
    assert len(rows) == 9
    base_row = next(r for r in rows if r["appreciation"] == 0.03 and r["rent_growth"] == 0.03)
    assert base_row["irr"] == out["projection"]["irr"]
    assert base_row["total_profit"] == out["projection"]["total_profit"]


def test_realestate_rental_scenarios_requires_hold_years(capsys) -> None:
    m = load_script("real-estate/scripts/realestate.py")
    with pytest.raises(ValueError, match="scenarios requires hold_years"):
        m.run_realestate(
            {
                "action": "rental", "price": 200000, "down_payment": 50000, "rate": 0.07,
                "years": 30, "rent": 2000, "property_tax_annual": 2400, "scenarios": True,
            }
        )


def _run_math(params: dict, capsys, monkeypatch) -> dict:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(params)))
    load_script("real-estate/scripts/realestate.py").main()
    return json.loads(capsys.readouterr().out)


def test_realestate_refinance_savings_path_crosses_zero_at_breakeven_and_ends_at_lifetime_delta(capsys, monkeypatch) -> None:
    out = _run_math({"action": "refinance", "balance": 200000, "current_rate": 0.07, "remaining_months": 300, "new_rate": 0.055, "new_years": 30, "closing_costs": 4000}, capsys, monkeypatch)
    path = out["savings_path"]
    assert [r["year"] for r in path] == list(range(1, 31))  # the longer of the two terms
    assert path[0]["cumulative_savings"] < 0 < path[1]["cumulative_savings"]  # breakeven_months 14.4 falls in year 2
    assert 12 < out["breakeven_months"] < 24 and path[-1]["cumulative_savings"] == out["lifetime_delta"]


def _render(result: dict, tmp_path, capsys, name: str = "re") -> tuple[int, dict, str]:
    src = tmp_path / f"{name}.json"
    src.write_text(json.dumps(result))
    out = tmp_path / f"{name}.html"
    rc, res = run_json(load_script("real-estate/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    return rc, res, out.read_text() if out.exists() else ""


def test_render_builds_a_mortgage_page(capsys, monkeypatch, tmp_path) -> None:
    result = _run_math({"action": "mortgage", "price": 375000, "down_payment": 37500, "rate": 0.065, "years": 30, "extra_payment": 200, "property_tax_rate": 0.012, "insurance_annual": 1500, "hoa_monthly": 100, "pmi_rate": 0.005}, capsys, monkeypatch)
    result["flags"] = [{"code": "NOTE", "message": "rate from <b>user</b>"}]
    rc, res, html = _render(result, tmp_path, capsys)
    assert rc == 0 and res["title"] == "Real Estate Calculator" and res["calculators"] == ["mortgage"] and res["flags"] == 1
    assert html.startswith("<title>Real Estate Calculator</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"schedule"' in html and '"with_extra"' in html and "const FA" in html
    assert "</b>" not in html.split("window.DATA")[1].split("</script>")[0]  # the flag text is embedded as JSON, closing tags stay escaped
    assert "<h1>Mortgage and amortization</h1>" in html and f"payment ${result['payment']:,.2f}" in html  # static headline without JS
    for section in ("Balance, interest and principal by year", "Amortization schedule", "Flags", "fixed-rate only"):
        assert section in html
    # glossary sweep: the explain box and term markers (built by JS at runtime, so assert the toolkit + the SCRIPT calls)
    assert '<div id="explain"></div>' in html and 'class="explain"' in html and "data-term=" in html
    script = html.split("const FA")[1]
    assert "FA.explain(" in script and "FA.term(" in script and "Object.assign(FA.glossary" in script
    for term in ("piti", "pmi", "amortization", "noi", "cap rate", "dscr", "irr", "ffo", "affo", "nav", "28/36 rule", "break-even point"):
        assert f"T('{term}'" in script, term


def test_render_picks_sections_by_keys(capsys, monkeypatch, tmp_path) -> None:
    refi = _run_math({"action": "refinance", "balance": 200000, "current_rate": 0.07, "remaining_months": 300, "new_rate": 0.055, "new_years": 30, "closing_costs": 4000}, capsys, monkeypatch)
    rc, res, html = _render(refi, tmp_path, capsys, "refi")
    assert rc == 0 and res["calculators"] == ["refinance"] and "<h1>Refinance breakeven</h1>" in html and '"savings_path"' in html and "breakeven 14.4 months" in html
    rvb = _run_math({"action": "rent_vs_buy", "price": 500000, "down_payment": 100000, "rate": 0.065, "horizon_years": 5, "rent": 2500, "appreciation": 0.03, "rent_growth": 0.03, "investment_return": 0.06, "sell_closing_rate": 0.06}, capsys, monkeypatch)
    rc, res, html = _render(rvb, tmp_path, capsys, "rvb")
    assert rc == 0 and res["calculators"] == ["rent_vs_buy"] and "<h1>Rent vs buy</h1>" in html and '"by_year"' in html
    rental = _run_math({"action": "rental", "price": 300000, "down_payment": 75000, "rate": 0.07, "rent": 2600, "vacancy_rate": 0.05, "property_tax_annual": 3600, "hold_years": 10, "appreciation": 0.03, "rent_growth": 0.03, "scenarios": True}, capsys, monkeypatch)
    rc, res, html = _render(rental, tmp_path, capsys, "rental")
    assert rc == 0 and res["calculators"] == ["rental"] and "<h1>Rental underwriting</h1>" in html and '"scenarios"' in html and f"NOI ${rental['noi']:,.2f}" in html
    afford = _run_math({"action": "affordability", "annual_income": 150000, "monthly_debts": 600, "down_payment": 60000, "rate": 0.065}, capsys, monkeypatch)
    rc, res, html = _render(afford, tmp_path, capsys, "afford")
    assert rc == 0 and res["calculators"] == ["affordability"] and "<h1>Affordability</h1>" in html and "front-end 28%" in html
    reit = _run_math({"action": "reit", "price": 50, "shares": 1e8, "net_income": 2e8, "depreciation": 2.5e8, "dividend_per_share": 3.0, "nav_per_share": 55}, capsys, monkeypatch)
    reit.update({"symbol": "O", "notes": ["FFO uses Net Income + D&A </i>proxy"]})  # as reit.py adds them
    rc, res, html = _render(reit, tmp_path, capsys, "reit")
    assert rc == 0 and res["calculators"] == ["reit"] and "<h1>REIT metrics — O</h1>" in html and "D&A </i>proxy" not in html and '"notes"' in html


def test_render_rejects_non_realestate_input(tmp_path, capsys) -> None:
    src = tmp_path / "bad.json"
    src.write_text('{"totals": {"total_value": 1}}')
    rc, res = run_json(load_script("real-estate/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "realestate.py or reit.py result" in res["error"]
    src.write_text("[]")
    rc, res = run_json(load_script("real-estate/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2


@requires_chrome
@pytest.mark.parametrize("payload", [
    {"action": "mortgage", "price": 375000, "down_payment": 37500, "rate": 0.065, "years": 30, "extra_payment": 200, "property_tax_rate": 0.012, "insurance_annual": 1500},
    {"action": "refinance", "balance": 200000, "current_rate": 0.07, "remaining_months": 300, "new_rate": 0.055, "new_years": 30, "closing_costs": 4000},
    {"action": "rent_vs_buy", "price": 500000, "down_payment": 100000, "rate": 0.065, "horizon_years": 5, "rent": 2500, "appreciation": 0.03, "rent_growth": 0.03, "investment_return": 0.06, "sell_closing_rate": 0.06},
    {"action": "rental", "price": 300000, "down_payment": 75000, "rate": 0.07, "rent": 2600, "vacancy_rate": 0.05, "property_tax_annual": 3600, "hold_years": 10, "appreciation": 0.03, "rent_growth": 0.03, "scenarios": True},
    {"action": "affordability", "annual_income": 150000, "monthly_debts": 600, "down_payment": 60000, "rate": 0.065},
    {"action": "reit", "price": 50, "shares": 1e8, "net_income": 2e8, "depreciation": 2.5e8, "dividend_per_share": 3.0, "nav_per_share": 55},
], ids=lambda p: p["action"])
def test_every_card_explains_itself(payload, capsys, monkeypatch, tmp_path) -> None:
    result = _run_math(payload, capsys, monkeypatch)
    src = tmp_path / "re.json"
    src.write_text(json.dumps(result))
    assert_page_help(render_and_audit("real-estate/scripts/render.py", ["--in", str(src)], tmp_path, capsys))


@requires_chrome
def test_reit_flow_subtracts_gains_and_scenarios_skip_read_grid(capsys, monkeypatch, tmp_path) -> None:
    from page_dom import card_text
    reit = _run_math({"action": "reit", "price": 50, "shares": 1e8, "net_income": 2e8, "depreciation": 2.5e8, "gains_on_sale": 5e7, "dividend_per_share": 3.0, "nav_per_share": 55}, capsys, monkeypatch)
    reit["inputs"] = {"price": 50, "shares": 1e8, "net_income": 2e8, "depreciation": 2.5e8, "gains_on_sale": 5e7, "recurring_capex": None, "dividend_per_share": 3.0, "nav_per_share": 55}  # as reit.py echoes them
    src = tmp_path / "reit.json"
    src.write_text(json.dumps(reit))
    assert "gains on property sales" in card_text(render_and_audit("real-estate/scripts/render.py", ["--in", str(src)], tmp_path, capsys), "REIT")
    rental = _run_math({"action": "rental", "price": 300000, "down_payment": 75000, "rate": 0.07, "rent": 2600, "vacancy_rate": 0.05, "property_tax_annual": 3600, "hold_years": 10, "appreciation": 0.03, "rent_growth": 0.03, "scenarios": True}, capsys, monkeypatch)
    src.write_text(json.dumps(rental))
    text = card_text(render_and_audit("real-estate/scripts/render.py", ["--in", str(src)], tmp_path, capsys), "Scenarios")
    assert "outlined" not in text and "lower to higher" not in text
