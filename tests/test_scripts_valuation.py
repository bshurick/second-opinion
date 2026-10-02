"""Valuation skill tests: shared-math stdin scripts (dcf/ddm/comps) plus the
inputs.py and peers.py Yahoo fetch scripts."""

from __future__ import annotations

import io
import json
import sys
from datetime import date, timedelta

import pytest
from scripts_util import PLUGIN_ROOT, load_script, run_json
from second_opinion import market
from page_dom import assert_page_help, render_and_audit, requires_chrome


def run_stdin(rel: str, payload: dict, capsys, monkeypatch) -> dict:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    mod = load_script(rel)
    mod.main()
    return json.loads(capsys.readouterr().out)


def run_stdin_error(rel: str, payload: dict, capsys, monkeypatch) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    mod = load_script(rel)
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    out = json.loads(capsys.readouterr().out)
    return excinfo.value.code, out


# ---------------------------------------------------------------------------
# dcf.py: stage-1 growth schedule + reverse DCF
# ---------------------------------------------------------------------------


def test_dcf_stage1_growth_schedule(capsys, monkeypatch) -> None:
    rates = [0.20, 0.15, 0.10, 0.05, 0.03]
    out = run_stdin(
        "valuation/scripts/dcf.py",
        {
            "fcf0": 100.0,
            "growth_rate": 0.08,
            "stage1_growth": rates,
            "years": 5,
            "terminal_growth": 0.025,
            "wacc": 0.09,
            "net_debt": 250.0,
            "shares_outstanding": 50.0,
        },
        capsys,
        monkeypatch,
    )
    # independent arithmetic: per-year compounding, year-N Gordon terminal
    pv_stage1 = 0.0
    fcf_t = 100.0
    for t, rate in enumerate(rates, start=1):
        fcf_t = fcf_t * (1 + rate)
        pv_stage1 += fcf_t / 1.09**t
    pv_terminal = fcf_t * 1.025 / 0.065 / 1.09**5
    expected = round((pv_stage1 + pv_terminal - 250.0) / 50.0, 2)
    assert out["fair_value_per_share"] == pytest.approx(expected, abs=0.01)
    assert out["inputs_echo"]["stage1_growth"] == rates


def test_dcf_implied_block_reproduces_the_price(capsys, monkeypatch) -> None:
    base = run_stdin(
        "valuation/scripts/dcf.py",
        {
            "fcf0": 100.0,
            "growth_rate": 0.08,
            "years": 5,
            "terminal_growth": 0.025,
            "wacc": 0.09,
            "net_debt": 250.0,
            "shares_outstanding": 50.0,
        },
        capsys,
        monkeypatch,
    )
    assert "implied" not in base
    out = run_stdin(
        "valuation/scripts/dcf.py",
        {
            "fcf0": 100.0,
            "growth_rate": 0.08,
            "years": 5,
            "terminal_growth": 0.025,
            "wacc": 0.09,
            "net_debt": 250.0,
            "shares_outstanding": 50.0,
            "current_share_price": base["fair_value_per_share"],
        },
        capsys,
        monkeypatch,
    )
    assert out["implied"]["stage1_growth"] == pytest.approx(0.08, abs=0.005)
    assert out["implied"]["terminal_growth"] == pytest.approx(0.025, abs=0.005)


def test_dcf_stage1_growth_wrong_length_exits_2(capsys, monkeypatch) -> None:
    rc, out = run_stdin_error(
        "valuation/scripts/dcf.py",
        {
            "fcf0": 100.0,
            "growth_rate": 0.08,
            "stage1_growth": [0.1, 0.1],
            "years": 5,
            "terminal_growth": 0.025,
            "wacc": 0.09,
            "net_debt": 250.0,
            "shares_outstanding": 50.0,
        },
        capsys,
        monkeypatch,
    )
    assert rc == 2 and "stage1_growth" in out["error"]


# ---------------------------------------------------------------------------
# ddm.py: Gordon / two-stage / H-model
# ---------------------------------------------------------------------------


def test_ddm_gordon(capsys, monkeypatch) -> None:
    out = run_stdin(
        "valuation/scripts/ddm.py",
        {"model": "gordon", "dividend0": 2.0, "required_return": 0.09, "terminal_growth": 0.025},
        capsys,
        monkeypatch,
    )
    assert out["model"] == "gordon"
    assert out["fair_value_per_share"] == pytest.approx(round(2.0 * 1.025 / 0.065, 2), abs=0.01)
    assert out["sensitivity_grid"]["required_return_values"] == pytest.approx(
        [0.08, 0.085, 0.09, 0.095, 0.10], abs=1e-9
    )


def test_ddm_two_stage(capsys, monkeypatch) -> None:
    out = run_stdin(
        "valuation/scripts/ddm.py",
        {
            "model": "two_stage",
            "dividend0": 2.0,
            "required_return": 0.09,
            "terminal_growth": 0.025,
            "growth_rate": 0.12,
            "years": 5,
        },
        capsys,
        monkeypatch,
    )
    # stage-1: dividends 2.24..3.14 discounted at 9%; terminal Gordon at year 5
    pv_stage1 = sum(2.0 * 1.12**t / 1.09**t for t in range(1, 6))
    d5 = 2.0 * 1.12**5
    expected = round(pv_stage1 + d5 * 1.025 / 0.065 / 1.09**5, 2)
    assert out["fair_value_per_share"] == pytest.approx(expected, abs=0.01)


def test_ddm_h_model(capsys, monkeypatch) -> None:
    out = run_stdin(
        "valuation/scripts/ddm.py",
        {
            "model": "h",
            "dividend0": 2.0,
            "required_return": 0.09,
            "terminal_growth": 0.025,
            "initial_growth": 0.15,
            "h_years": 5.0,
        },
        capsys,
        monkeypatch,
    )
    expected = round(2.0 * (1.025 + 5.0 * 0.125) / 0.065, 2)
    assert out["fair_value_per_share"] == pytest.approx(expected, abs=0.01)


def test_ddm_bad_terminal_growth_exits_2(capsys, monkeypatch) -> None:
    rc, out = run_stdin_error(
        "valuation/scripts/ddm.py",
        {"model": "gordon", "dividend0": 2.0, "required_return": 0.02, "terminal_growth": 0.025},
        capsys,
        monkeypatch,
    )
    assert rc == 2 and "terminal_growth" in out["error"]


# ---------------------------------------------------------------------------
# comps.py: new metrics pb / ev_sales / fcf_yield
# ---------------------------------------------------------------------------


def test_comps_new_metrics(capsys, monkeypatch) -> None:
    out = run_stdin(
        "valuation/scripts/comps.py",
        {
            "target": {"metric_values": {"pb": 3.0, "fcf_yield": 0.04}},
            "peers": [
                {"name": "A", "pb": 2.0, "ev_sales": 1.2, "fcf_yield": 0.05},
                {"name": "B", "pb": 2.4, "ev_sales": 1.4, "fcf_yield": 0.06},
                {"name": "C", "pb": 2.8, "ev_sales": 1.6, "fcf_yield": 0.07},
            ],
            "target_financials": {
                "book_value_per_share": 50.0,
                "sales_per_share": 100.0,
                "net_debt_per_share": 10.0,
                "fcf_per_share": 3.0,
            },
        },
        capsys,
        monkeypatch,
    )
    assert out["metrics"]["pb"]["implied_value_per_share"] == pytest.approx(120.0)
    assert out["metrics"]["ev_sales"]["implied_value_per_share"] == pytest.approx(130.0)
    assert out["metrics"]["fcf_yield"]["implied_value_per_share"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# inputs.py: filled dcf.py/ddm.py inputs from Yahoo
# ---------------------------------------------------------------------------

INFO = {
    "symbol": "KO",
    "free_cash_flow": 999.0,     # Yahoo's own trailing estimate: only used when the statement has none
    "total_debt": 400.0,
    "total_cash": 100.0,
    "shares_outstanding": 1000.0,
    "market_cap": 1600.0,
    "beta": 1.2,
    "current_price": 60.0,
    "sector": "Consumer Defensive",
}

_STATEMENT_YEARS = range(2021, 2026)
# Period keys carry a time part, as Yahoo's statements do.
STATEMENTS = {
    "symbol": "KO",
    "quarterly": False,
    "income_statement": {
        f"{y}-12-31T00:00:00": {"Total Revenue": 800.0 * (1.1 ** (y - 2021)), "Interest Expense": 20.0, "Tax Rate For Calcs": 0.25} for y in _STATEMENT_YEARS
    },
    "cash_flow": {
        f"{y}-12-31T00:00:00": {"Free Cash Flow": 80.0 * (1.2 ** (y - 2021))} for y in _STATEMENT_YEARS
    },
    "shares_outstanding": 1000.0,
}


def _dividend_history() -> list[dict]:
    """Quarterly dividends for six-plus years, raised 10% each calendar year. The window opens
    mid-year, so the first calendar year holds a single payment."""
    this_year = date.today().year
    rows = [{"date": f"{this_year - 6}-11-15", "dividend": 0.10}]
    for back in range(5, 0, -1):
        for month in (2, 5, 8, 11):
            rows.append({"date": f"{this_year - back}-{month:02d}-15", "dividend": round(0.10 * 1.1 ** (5 - back), 6)})
    for months_ago in (9, 6, 3, 1):
        d = date.today() - timedelta(days=round(months_ago * 30.44))
        if d.year == this_year:
            rows.append({"date": d.isoformat(), "dividend": 0.2})
    return sorted(rows, key=lambda r: r["date"])


@pytest.fixture
def fake_yahoo(monkeypatch):
    calls: list[str] = []
    state = {"info": dict(INFO), "statements": dict(STATEMENTS), "yields": {"^TNX": 4.5, "^IRX": 4.0}}

    def company_info(symbol):
        calls.append(f"info:{symbol}")
        return dict(state["info"], symbol=symbol.upper())

    def financials(symbol, quarterly=False):
        calls.append(f"financials:{symbol}")
        return dict(state["statements"], symbol=symbol.upper(), quarterly=quarterly)

    def quote(symbols):
        calls.append(f"quote:{','.join(symbols)}")
        return [{"symbol": s, "price": state["yields"].get(s), "currency": "USD"} for s in symbols]

    def dividend_histories(symbols, years=5):
        calls.append(f"dividends:{','.join(symbols)}")
        return {s: _dividend_history() for s in symbols}

    monkeypatch.setattr(market, "company_info", company_info)
    monkeypatch.setattr(market, "financials", financials)
    monkeypatch.setattr(market, "quote", quote)
    monkeypatch.setattr(market, "dividend_histories", dividend_histories)
    return _Calls(calls, state)


class _Calls(list):
    def __init__(self, calls, state):
        super().__init__()
        self._calls, self.state = calls, state

    def seen(self):
        return list(self._calls)


INPUTS = "valuation/scripts/inputs.py"


def test_inputs_script_fills_dcf_and_ddm_inputs(fake_yahoo, capsys) -> None:
    rc, out = run_json(load_script(INPUTS), ["ko"], capsys)
    assert rc == 0, out
    assert out["symbol"] == "KO" and out["business_type"] == "industrial" and out["flags"] == []
    # exactly one call each: info, statements, the 10-year quote, dividend history
    assert fake_yahoo.seen() == ["info:KO", "financials:KO", "quote:^TNX", "dividends:KO"]

    a = out["assumptions"]
    assert a["risk_free"]["value"] == 0.045 and out["sources"]["risk_free"] == "yahoo (^TNX)"
    assert a["adjusted_beta"]["value"] == pytest.approx(0.67 * 1.2 + 0.33)
    coe = 0.045 + (0.67 * 1.2 + 0.33) * 0.05
    assert a["cost_of_equity"]["value"] == pytest.approx(coe, abs=1e-4)
    assert a["cost_of_debt"]["value"] == pytest.approx(0.05)            # 20 interest / 400 debt
    assert a["tax_rate"]["value"] == 0.25
    # 1600 equity and 400 debt at market value: 80% / 20%
    assert a["wacc"]["value"] == pytest.approx(0.8 * coe + 0.2 * 0.05 * 0.75, abs=1e-4)

    dcf_input = out["dcf_input"]
    # free cash flow grew faster than revenue, so the latest year (165.9) is above the average
    # margin on the latest revenue; the average is used. To the firm: plus after-tax interest.
    margins = [80.0 * 1.2**i / (800.0 * 1.1**i) for i in range(5)]
    normal = sum(margins) / 5 * 800.0 * 1.1**4
    assert normal < 80.0 * 1.2**4
    assert dcf_input["fcf0"] == pytest.approx(normal + 20.0 * 0.75, abs=0.01)
    assert "average free-cash-flow margin over 5 annual statements" in a["fcf0"]["source"]
    assert dcf_input["net_debt"] == 300.0 and dcf_input["shares_outstanding"] == 1000.0
    assert dcf_input["current_share_price"] == 60.0 and dcf_input["terminal_growth"] == 0.025 and dcf_input["years"] == 5
    assert dcf_input["wacc"] == a["wacc"]["value"]
    # the lower of revenue growth (10%) and free-cash-flow growth (20%)
    assert dcf_input["growth_rate"] == pytest.approx(0.10, abs=0.001)
    assert "lower of revenue CAGR 0.1" in a["growth_rate"]["source"]

    ddm_input = out["ddm_input"]
    assert ddm_input["model"] == "gordon" and ddm_input["terminal_growth"] == 0.025
    ttm = sum(r["dividend"] for r in _dividend_history() if r["date"] >= (date.today() - timedelta(days=365)).isoformat())
    assert ddm_input["dividend0"] == pytest.approx(ttm, abs=0.01)
    assert ddm_input["required_return"] == a["cost_of_equity"]["value"]   # dividends are discounted at the cost of equity

    for key in ("risk_free", "equity_risk_premium", "beta", "wacc", "growth_rate", "terminal_growth", "cost_of_debt", "fcf0"):
        assert a[key]["value"] is not None and a[key]["source"], key


def test_inputs_keeps_the_latest_year_when_it_is_not_above_the_average(fake_yahoo, capsys) -> None:
    flat = {f"{y}-12-31T00:00:00": {"Free Cash Flow": 80.0} for y in _STATEMENT_YEARS}
    fake_yahoo.state["statements"] = dict(STATEMENTS, cash_flow=flat)
    rc, out = run_json(load_script(INPUTS), ["ko"], capsys)
    assert out["dcf_input"]["fcf0"] == pytest.approx(80.0 + 15.0)
    assert "latest annual statement free cash flow (2025-12-31)" in out["assumptions"]["fcf0"]["source"]


def test_inputs_discount_rate_has_a_floor_above_the_treasury(fake_yahoo, capsys) -> None:
    fake_yahoo.state["info"].update(beta=0.0, total_debt=3000.0)     # low beta, debt-heavy: 5.1% unfloored
    rc, out = run_json(load_script(INPUTS), ["ko"], capsys)
    a = out["assumptions"]["wacc"]
    assert a["value"] == pytest.approx(0.045 + 0.025) and "raised to the floor" in a["source"]


def test_inputs_dividend_growth_ignores_the_partial_first_year(fake_yahoo, capsys) -> None:
    """One payment in the opening year against four in the next would read as a 300% raise."""
    rc, out = run_json(load_script(INPUTS), ["ko"], capsys)
    assert out["assumptions"]["dividend_cagr"]["value"] == pytest.approx(0.10, abs=0.001)


def test_inputs_scenarios_fade_growth_from_three_starting_points(fake_yahoo, capsys) -> None:
    rc, out = run_json(load_script(INPUTS), ["ko"], capsys)
    sc = out["dcf_scenarios"]
    assert sc["base"]["stage1_growth"] == pytest.approx([0.1, 0.08125, 0.0625, 0.04375, 0.025], abs=1e-4)
    assert sc["bear"]["stage1_growth"][0] == pytest.approx(0.05) and sc["bull"]["stage1_growth"][0] == pytest.approx(0.15)
    assert all(s["stage1_growth"][-1] == 0.025 and "growth_rate" not in s and s["wacc"] == out["dcf_input"]["wacc"] for s in sc.values())
    # each one is a valid dcf.py input, and they order as their names say
    values = {name: load_script("valuation/scripts/dcf.py").run_dcf(payload)["fair_value_per_share"] for name, payload in sc.items()}
    assert values["bear"] < values["base"] < values["bull"]


@pytest.mark.parametrize("sector, kind", [("Financial Services", "financial"), ("Real Estate", "reit"), ("Utilities", "utility")])
def test_inputs_flags_sectors_where_a_cash_flow_dcf_says_little(fake_yahoo, capsys, sector, kind) -> None:
    fake_yahoo.state["info"]["sector"] = sector
    rc, out = run_json(load_script(INPUTS), ["ko"], capsys)
    assert out["business_type"] == kind
    flag = out["flags"][0]
    assert flag["code"] == {"financial": "DCF_NOT_MEANINGFUL_FOR_FINANCIALS", "reit": "DCF_NOT_MEANINGFUL_FOR_REITS", "utility": "DCF_NOT_MEANINGFUL_FOR_UTILITIES"}[kind] and "intrinsic.py" in flag["message"]


def test_inputs_falls_back_for_missing_pieces(fake_yahoo, capsys) -> None:
    fake_yahoo.state["yields"]["^TNX"] = None
    fake_yahoo.state["statements"] = {"income_statement": {}, "cash_flow": {}}
    fake_yahoo.state["info"].update(free_cash_flow=-50.0, beta=0.1)
    rc, out = run_json(load_script(INPUTS), ["ko"], capsys)
    a = out["assumptions"]
    assert a["risk_free"]["value"] == 0.04 and out["sources"]["risk_free"] == "yahoo (^IRX)"
    assert a["adjusted_beta"]["value"] == pytest.approx(0.397)          # a 0.1 beta does not give a 4.5% discount rate
    assert a["cost_of_debt"]["value"] == pytest.approx(0.06) and "stated default" in a["cost_of_debt"]["source"]
    assert a["tax_rate"] == {"value": 0.21, "source": "stated default"}
    assert out["dcf_input"]["fcf0"] == -50.0 and "often unreliable" in a["fcf0"]["source"]
    assert out["dcf_input"]["growth_rate"] is None and out["dcf_scenarios"] is None
    assert [f["code"] for f in out["flags"]] == ["NEGATIVE_FCF"]


def test_inputs_script_degrades_to_nulls_when_data_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "company_info", lambda s: {"symbol": s.upper()})
    monkeypatch.setattr(market, "financials", lambda s, quarterly=False: {"symbol": s.upper(), "income_statement": {}, "cash_flow": {}})
    monkeypatch.setattr(market, "quote", lambda symbols: [{"symbol": symbols[0], "price": None}])
    monkeypatch.setattr(market, "dividend_histories", lambda symbols, years=5: {s: [] for s in symbols})
    rc, out = run_json(load_script(INPUTS), ["ko"], capsys)
    assert rc == 0, out
    assert out["dcf_input"]["fcf0"] is None
    assert out["dcf_input"]["wacc"] is None
    assert out["ddm_input"]["dividend0"] is None and out["ddm_input"]["required_return"] is None


def test_inputs_script_usage(capsys) -> None:
    rc, out = run_json(load_script("valuation/scripts/inputs.py"), [], capsys)
    assert rc == 2 and "usage" in out["error"]


# ---------------------------------------------------------------------------
# peers.py: comps.py input from Yahoo
# ---------------------------------------------------------------------------

PEER_INFO = {
    "KO": dict(INFO, market_cap=60000.0, enterprise_value=64000.0, pe_ratio=25.0, price_to_book=6.0),
    "PEP": {
        "symbol": "PEP", "market_cap": 50000.0, "enterprise_value": 52000.0, "pe_ratio": 20.0,
        "price_to_book": 5.0, "free_cash_flow": 100.0, "shares_outstanding": 1000.0,
    },
    "DPS": {
        "symbol": "DPS", "market_cap": 40000.0, "enterprise_value": 41000.0, "pe_ratio": 22.0,
        "price_to_book": 4.0, "free_cash_flow": 80.0, "shares_outstanding": 500.0,
    },
}

PEER_STATEMENTS = {
    "KO": {"income_statement": {"2025-12-31": {"Total Revenue": 8000.0, "EBITDA": 1600.0, "Net Income": 1000.0}}, "shares_outstanding": 1000.0},
    "PEP": {"income_statement": {"2025-12-31": {"Total Revenue": 7000.0, "EBITDA": 1500.0, "Net Income": 900.0}}, "shares_outstanding": 1000.0},
    "DPS": {"income_statement": {"2025-12-31": {"Total Revenue": 6000.0, "EBITDA": 1100.0, "Net Income": 800.0}}, "shares_outstanding": 500.0},
}


@pytest.fixture
def fake_peers(monkeypatch):
    calls: list[str] = []

    def company_info(symbol):
        calls.append(f"info:{symbol}")
        return dict(PEER_INFO[symbol.upper()])

    def financials(symbol, quarterly=False):
        calls.append(f"financials:{symbol}")
        return {"symbol": symbol.upper(), "quarterly": quarterly, **PEER_STATEMENTS[symbol.upper()]}

    monkeypatch.setattr(market, "company_info", company_info)
    monkeypatch.setattr(market, "financials", financials)
    return calls


def test_peers_script_builds_comps_input(fake_peers, capsys) -> None:
    rc, out = run_json(load_script("valuation/scripts/peers.py"), ["ko", "--peers", "pep,dps"], capsys)
    assert rc == 0, out
    assert out["sources"]["fundamentals"] == "yahoo"
    # two Yahoo calls per symbol: info + statements
    assert fake_peers == [
        "info:KO", "financials:KO",
        "info:PEP", "financials:PEP",
        "info:DPS", "financials:DPS",
    ]
    assert out["target"]["metric_values"]["pe"] == pytest.approx(25.0)
    assert out["target"]["metric_values"]["ev_ebitda"] == pytest.approx(64000.0 / 1600.0)
    assert out["target"]["metric_values"]["ev_sales"] == pytest.approx(64000.0 / 8000.0)
    # no cash-flow statement in this fixture: Yahoo's own figure stands in
    assert out["target"]["metric_values"]["fcf_yield"] == pytest.approx(999.0 / 60000.0, abs=1e-4)
    assert out["business_type"] == "industrial" and out["metrics_used"] == ["pe", "ev_ebitda", "ps", "pb", "ev_sales", "fcf_yield"]

    assert [p["name"] for p in out["peers"]] == ["PEP", "DPS"]
    pep = out["peers"][0]
    assert pep["pe"] == pytest.approx(20.0)
    assert pep["ev_ebitda"] == pytest.approx(52000.0 / 1500.0)

    fin = out["target_financials"]
    assert fin["eps"] == pytest.approx(1.0)
    assert fin["ebitda_per_share"] == pytest.approx(1.6)
    assert fin["sales_per_share"] == pytest.approx(8.0)
    assert fin["book_value_per_share"] == pytest.approx(10.0)  # 60 / pb 6
    assert fin["fcf_per_share"] == pytest.approx(0.999)
    assert fin["net_debt_per_share"] == pytest.approx(0.3)  # (400 debt - 100 cash) / 1000 shares

    # the built input pipes straight into comps.py
    comps_in = {k: out[k] for k in ("target", "peers", "target_financials")}
    import subprocess

    comps_path = PLUGIN_ROOT / "skills/valuation/scripts/comps.py"
    proc = subprocess.run(
        [sys.executable, str(comps_path)],
        input=json.dumps(comps_in), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    comps_out = json.loads(proc.stdout)
    # peer pe median of [20, 22] is 21; target eps is 1.0
    assert comps_out["metrics"]["pe"]["implied_value_per_share"] == pytest.approx(21.0)


def test_peers_uses_statement_cash_flow_and_only_the_multiples_that_fit(fake_peers, monkeypatch, capsys) -> None:
    for sym in PEER_STATEMENTS:
        monkeypatch.setitem(PEER_STATEMENTS[sym], "cash_flow", {"2025-12-31T00:00:00": {"Free Cash Flow": 300.0, "Depreciation And Amortization": 500.0}})
    rc, out = run_json(load_script("valuation/scripts/peers.py"), ["ko", "--peers", "pep,dps"], capsys)
    assert out["target"]["metric_values"]["fcf_yield"] == pytest.approx(300.0 / 60000.0, abs=1e-4)
    assert out["target_financials"]["ffo_per_share"] == pytest.approx((1000.0 + 500.0) / 1000.0)
    assert "p_ffo" not in out["target"]["metric_values"]                  # not a REIT

    for sector, kind, metrics in (("Real Estate", "reit", ["p_ffo", "ev_ebitda"]), ("Financial Services", "financial", ["pe", "pb"]), ("Utilities", "utility", ["pe", "pb", "ev_ebitda"])):
        monkeypatch.setitem(PEER_INFO["KO"], "sector", sector)
        rc, out = run_json(load_script("valuation/scripts/peers.py"), ["ko", "--peers", "pep,dps"], capsys)
        assert out["business_type"] == kind and out["metrics_used"] == metrics
        assert set(out["target"]["metric_values"]) <= set(metrics) and all(set(p) - {"name"} <= set(metrics) for p in out["peers"])
    assert out["peers"][0].get("fcf_yield") is None


def test_comps_reit_multiple_and_summary_leaves_out_values_that_are_not_positive(capsys, monkeypatch) -> None:
    comps = load_script("valuation/scripts/comps.py")
    out = comps.run_comps({
        "peers": [{"name": "A", "p_ffo": 14.0, "fcf_yield": -0.05}, {"name": "B", "p_ffo": 18.0, "fcf_yield": -0.07}],
        "target": {"metric_values": {"p_ffo": 12.0}},
        "target_financials": {"ffo_per_share": 4.0, "fcf_per_share": 1.5},
    })
    assert out["metrics"]["p_ffo"] == {"peer_median": 16.0, "implied_value_per_share": 64.0, "premium_discount_vs_peers": -0.25}
    assert out["metrics"]["fcf_yield"]["implied_value_per_share"] == -25.0
    assert out["excluded_from_summary"] == ["fcf_yield"] and out["summary"] == {"min": 64.0, "max": 64.0, "median": 64.0}


def test_peers_script_drops_duplicates_and_target(fake_peers, capsys) -> None:
    rc, out = run_json(load_script("valuation/scripts/peers.py"), ["ko", "--peers", "pep,PEP,ko,dps"], capsys)
    assert rc == 0, out
    assert [p["name"] for p in out["peers"]] == ["PEP", "DPS"]


def test_peers_script_needs_two_peers(fake_peers, capsys) -> None:
    rc, out = run_json(load_script("valuation/scripts/peers.py"), ["ko", "--peers", "pep"], capsys)
    assert rc == 2 and "2" in out["error"]


def test_peers_script_usage(capsys) -> None:
    rc, out = run_json(load_script("valuation/scripts/peers.py"), ["ko"], capsys)
    assert rc == 2 and "usage" in out["error"]

# ---------------------------------------------------------------------------
# render.py: one page from the collected results
# ---------------------------------------------------------------------------


def test_render_builds_a_self_contained_page(tmp_path, capsys) -> None:
    from test_scripts_intrinsic import BASE

    intrinsic = load_script("valuation/scripts/intrinsic.py").run_intrinsic(BASE)
    dcf_mod = load_script("valuation/scripts/dcf.py")
    dcf = dcf_mod.run_dcf({"fcf0": 100.0, "growth_rate": 0.08, "years": 5, "terminal_growth": 0.025, "wacc": 0.09, "net_debt": 250.0, "shares_outstanding": 100.0, "current_share_price": 12.0})
    mid = dcf_mod.run_dcf(intrinsic["normalized"]["dcf_input_mid_cycle"])
    comps = load_script("valuation/scripts/comps.py").run_comps({"target": {"metric_values": {"pe": 12.6}}, "peers": [{"name": "A", "pe": 14, "pb": 1.6}, {"name": "B", "pe": 16, "pb": 2.0}],
                                                                  "target_financials": {"eps": 1.0, "book_value_per_share": 6.6}})
    ddm = load_script("valuation/scripts/ddm.py").run_ddm({"model": "gordon", "dividend0": 0.2, "required_return": 0.09, "terminal_growth": 0.03})
    intrinsic["flags"].append({"code": "NOTE", "message": "a <b>tagged</b> message"})
    data = {"symbol": "AC&ME", "price": 12.0, "dcf": dcf, "dcf_mid_cycle": mid, "intrinsic": intrinsic, "comps": comps, "ddm": ddm}
    src = tmp_path / "valuation.json"
    src.write_text(json.dumps(data))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("valuation/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res["out"] == str(out) and res["symbol"] == "AC&ME" and res["flags"] == 4
    assert res["methods"] == ["dcf", "dcf_mid_cycle", "intrinsic", "comps", "ddm"]
    html = out.read_text()
    assert html.startswith("<title>AC&amp;ME Valuation</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"graham_number":11.88' in html and "a <b>tagged<\\/b> message" in html and "</b> message" not in html
    assert all(f'id="{i}"' in html for i in ("tiles", "mos", "dcf-grid", "graham", "buffett", "norm", "comps", "ddm-grid", "flags"))
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html
    assert "not financial, tax, or legal advice" in html
    # plain-language layer: the explain box slot and the glossary calls (term spans are produced by JS at runtime)
    assert 'id="explain"' in html and 'class="explain"' in html and "data-term=" in html
    assert "FA.explain(" in html and "FA.term(" in html and "Object.assign(F.glossary, {" in html
    assert '"enterprise value": [' in html and '"sensitivity analysis": [' in html  # local glossary additions for this page


def test_render_wraps_a_bare_intrinsic_result_and_rejects_other_input(tmp_path, capsys) -> None:
    from test_scripts_intrinsic import BASE

    intrinsic = load_script("valuation/scripts/intrinsic.py").run_intrinsic(BASE)
    src = tmp_path / "intrinsic.json"
    src.write_text(json.dumps(intrinsic))
    rc, res = run_json(load_script("valuation/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "a.html")], capsys)
    assert rc == 0 and res["title"] == "Valuation" and res["methods"] == ["intrinsic"] and res["flags"] == 3
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": 1}')
    rc, res = run_json(load_script("valuation/scripts/render.py"), ["--in", str(bad), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "dcf, intrinsic, comps, ddm" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit("valuation/scripts/render.py", ["--in", str(PLUGIN_ROOT / "docs/samples/valuation.json")], tmp_path, capsys)
    assert_page_help(a)
    assert {c["h2"] for c in a["cards"] if not c["hidden"] and c["help"] == "authored"} >= {"Discounted cash flow", "Comparable multiples"}


@requires_chrome
def test_graham_explainer_names_the_larger_figure(tmp_path, capsys) -> None:
    from page_dom import card_text
    a = render_and_audit("valuation/scripts/render.py", ["--in", str(PLUGIN_ROOT / "docs/samples/valuation.json")], tmp_path, capsys)
    text = card_text(a, "Graham")  # sample: Graham number $153.01, growth formula $324.40
    assert "higher of the two" in text and "lower of the two" not in text
