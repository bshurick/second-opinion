"""intrinsic.py: Graham and Buffett value-investing math over the fundamentals annual table."""

from __future__ import annotations

import io
import json
import sys

import pytest
from scripts_util import load_script


def _row(fy, rev, ni, eps, eq, oi, ocf, capex, da, ca, cl, liab, ltd, cash, divs, shares=100.0):
    return {
        "fiscal_year": fy, "revenue": rev, "net_income": ni, "eps_diluted": eps, "equity": eq,
        "operating_income": oi, "operating_cash_flow": ocf, "capex": capex, "free_cash_flow": ocf - capex,
        "depreciation_amortization": da, "current_assets": ca, "current_liabilities": cl,
        "total_liabilities": liab, "long_term_debt": ltd, "cash": cash, "dividends_paid": divs,
        "diluted_shares": shares,
    }


ANNUAL = [
    _row(2021, 1000.0, 80.0, 0.80, 500.0, 120.0, 100.0, 30.0, 25.0, 300.0, 150.0, 400.0, 150.0, 50.0, 20.0),
    _row(2022, 1050.0, 85.0, 0.85, 540.0, 125.0, 105.0, 30.0, 25.0, 310.0, 150.0, 400.0, 150.0, 50.0, 20.0),
    _row(2023, 1100.0, 90.0, 0.90, 580.0, 130.0, 110.0, 30.0, 26.0, 320.0, 150.0, 400.0, 150.0, 50.0, 20.0),
    _row(2024, 1150.0, 95.0, 0.95, 620.0, 135.0, 115.0, 30.0, 26.0, 330.0, 150.0, 400.0, 150.0, 50.0, 20.0),
    _row(2025, 1200.0, 100.0, 1.00, 660.0, 140.0, 120.0, 30.0, 27.0, 340.0, 150.0, 400.0, 150.0, 50.0, 20.0),
]
BASE = {"annual": ANNUAL, "price": 12.0, "aaa_yield": 0.05, "treasury_10y": 0.042, "min_revenue": 1000.0}


def run(payload, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("valuation/scripts/intrinsic.py").main()
    return json.loads(capsys.readouterr().out)


def run_error(payload, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as excinfo:
        load_script("valuation/scripts/intrinsic.py").main()
    return excinfo.value.code, json.loads(capsys.readouterr().out)


def checks(block):
    return {c["check"]: c["passed"] for c in block["checks"]}


def test_graham_number_growth_formula_and_ncav(capsys, monkeypatch) -> None:
    out = run(BASE, capsys, monkeypatch)
    ps = out["per_share"]
    assert ps["eps_3y_avg"] == pytest.approx(0.95) and ps["book_value"] == pytest.approx(6.6)
    g = out["graham"]
    assert g["graham_number"] == pytest.approx(11.88, abs=0.005)
    # V = EPS x (8.5 + 2g) x 4.4 / Y with g = min(EPS CAGR 5.74%, revenue CAGR 4.66%) in percentage points
    # and Y the AAA yield in percent
    assert g["growth_formula"]["value"] == pytest.approx(14.90, abs=0.005)
    assert g["growth_formula"]["growth_used"] == pytest.approx(0.0466, abs=0.0001)
    assert g["growth_formula"]["aaa_yield"] == 0.05
    assert g["ncav_per_share"] == pytest.approx(-0.60)
    assert g["net_net"] == {"two_thirds_ncav": None, "price_below": False}
    assert {"code": "NEGATIVE_NCAV", "message": "current assets do not cover total liabilities; the net-net test does not apply"} in out["flags"]


def test_defensive_investor_checklist(capsys, monkeypatch) -> None:
    out = run(BASE, capsys, monkeypatch)
    d = out["graham"]["defensive_checklist"]
    assert (d["score"], d["out_of"]) == (5, 7)
    assert checks(d) == {
        "adequate_size": True,
        "financial_condition": True,       # current ratio 2.27 >= 2 and LTD 150 <= net current assets 190
        "earnings_stability": True,
        "dividend_record": True,
        "earnings_growth": False,          # 3y-avg EPS 0.85 -> 0.95 is +11.8%, under one third
        "moderate_pe": True,               # 12 / 0.95 = 12.6
        "moderate_pb": False,              # P/B 1.82 > 1.5 and P/E x P/B 22.97 > 22.5
    }
    by = {c["check"]: c for c in d["checks"]}
    assert by["financial_condition"]["value"] == {"current_ratio": pytest.approx(2.2667, abs=0.0001), "long_term_debt": 150.0, "net_current_assets": 190.0}
    assert by["earnings_growth"]["value"] == pytest.approx(0.1176, abs=0.0001)
    assert by["moderate_pb"]["value"] == {"price_to_book": pytest.approx(1.8182, abs=0.0001), "pe_times_pb": pytest.approx(22.97, abs=0.01)}
    assert d["years_covered"] == 5
    assert any(f["code"] == "SHORT_HISTORY" for f in out["flags"])


def test_owner_earnings_and_dcf_handoff(capsys, monkeypatch) -> None:
    out = run(BASE, capsys, monkeypatch)
    oe = out["buffett"]["owner_earnings"]
    # maintenance capex defaults to the larger of D&A and the table's average capex: max(27, 30) = 30
    assert oe["maintenance_capex"] == 30.0 and oe["maintenance_capex_method"] == "max(depreciation_amortization, average_capex)"
    assert oe["estimates"] == {"depreciation_amortization": 27.0, "average_capex": 30.0, "one_percent_of_revenue": 12.0}
    assert oe["value"] == pytest.approx(97.0) and oe["per_share"] == pytest.approx(0.97)
    assert [y["value"] for y in oe["by_year"]] == [75.0, 80.0, 86.0, 91.0, 97.0]
    dcf = out["buffett"]["dcf_input"]
    assert dcf == {
        "fcf0": 97.0,
        "growth_rate": pytest.approx(0.0466, abs=0.0001),
        "years": 10,
        "terminal_growth": 0.02,
        "wacc": 0.08,                      # treasury 4.2% is below the 8% floor
        "net_debt": 0.0,                   # owner earnings are after interest: equity cash flow
        "net_debt_note": dcf["net_debt_note"],
        "shares_outstanding": 100.0,
        "current_share_price": 12.0,
    }
    assert "after interest" in dcf["net_debt_note"] and "100.00" in dcf["net_debt_note"]
    assert out["inputs"]["discount_rate"] == {"value": 0.08, "source": "max(treasury_10y 0.042, discount_rate_floor 0.08)"}


def test_owner_earnings_override_and_discount_above_floor(capsys, monkeypatch) -> None:
    out = run({**BASE, "maintenance_capex": 20.0, "treasury_10y": 0.09}, capsys, monkeypatch)
    oe = out["buffett"]["owner_earnings"]
    assert oe["maintenance_capex_method"] == "override" and oe["value"] == pytest.approx(107.0)
    assert out["buffett"]["dcf_input"]["wacc"] == 0.09


def test_buffett_tenets(capsys, monkeypatch) -> None:
    t = run(BASE, capsys, monkeypatch)["buffett"]["tenets"]
    assert (t["score"], t["out_of"]) == (6, 7)
    assert checks(t) == {
        "consistent_high_roe": True,       # every year >= 15%
        "low_leverage": True,              # debt/equity 0.23
        "high_net_margin": False,          # 8.3% < 10%
        "consistent_operating_profit": True,
        "positive_owner_earnings": True,
        "cash_conversion": True,           # FCF/NI 0.9
        "share_count_not_rising": True,
    }


def test_margin_of_safety_bands(capsys, monkeypatch) -> None:
    mos = run(BASE, capsys, monkeypatch)["margin_of_safety"]
    by = {m["method"]: m for m in mos}
    assert set(by) == {"graham_number", "graham_number_10y", "graham_growth_formula"}   # NCAV is negative, so no net-net row
    assert by["graham_number"]["price_to_value"] == pytest.approx(1.0103, abs=0.0001)
    assert by["graham_number"]["discount"] == pytest.approx(-0.0103, abs=0.0001) and by["graham_number"]["band"] == "premium"
    assert by["graham_number_10y"]["value"] == pytest.approx(11.56, abs=0.005) and by["graham_number_10y"]["band"] == "premium"
    assert by["graham_growth_formula"]["discount"] == pytest.approx(0.1948, abs=0.0001) and by["graham_growth_formula"]["band"] == "0-25%"


def test_without_price_or_aaa_yield_degrades(capsys, monkeypatch) -> None:
    out = run({"annual": ANNUAL}, capsys, monkeypatch)
    assert out["graham"]["growth_formula"]["value"] is None
    assert out["margin_of_safety"] == []
    by = {c["check"]: c for c in out["graham"]["defensive_checklist"]["checks"]}
    assert by["moderate_pe"]["passed"] is None and by["moderate_pb"]["passed"] is None
    assert out["graham"]["defensive_checklist"]["out_of"] == 5
    assert out["buffett"]["dcf_input"]["current_share_price"] is None
    codes = {f["code"] for f in out["flags"]}
    assert {"NO_PRICE", "NO_AAA_YIELD"} <= codes


def test_negative_earnings_and_net_net(capsys, monkeypatch) -> None:
    rows = [dict(r, net_income=-10.0, eps_diluted=-0.10, total_liabilities=100.0) for r in ANNUAL]
    out = run({**BASE, "annual": rows, "price": 1.0}, capsys, monkeypatch)
    g = out["graham"]
    assert g["graham_number"] is None and g["growth_formula"]["value"] is None
    assert g["ncav_per_share"] == pytest.approx(2.4)                    # (340 - 100) / 100
    assert g["net_net"] == {"two_thirds_ncav": pytest.approx(1.6), "price_below": True}
    assert {m["method"]: m["band"] for m in out["margin_of_safety"]} == {"ncav": "50%+"}


def test_invalid_input_exits_2(capsys, monkeypatch) -> None:
    code, out = run_error({"annual": []}, capsys, monkeypatch)
    assert code == 2 and "annual" in out["error"]
    code, out = run_error([1, 2], capsys, monkeypatch)
    assert code == 2
    code, out = run_error({**BASE, "business_type": "bank"}, capsys, monkeypatch)
    assert code == 2 and "business_type" in out["error"]


# ── growth default ─────────────────────────────────────────────────────────


def test_growth_default_is_min_of_eps_and_revenue_cagr_clipped_to_8pct(capsys, monkeypatch) -> None:
    out = run(BASE, capsys, monkeypatch)
    g = out["inputs"]["growth_rate"]
    assert g["value"] == pytest.approx(0.0466, abs=0.0001)               # revenue 1000 -> 1200 over 4 years
    assert g["source"] == "min(EPS CAGR 0.0574, revenue CAGR 0.0466) = 0.0466, clipped to [0, 0.08]"
    alt = out["inputs"]["growth_alternatives"]
    assert alt["eps_cagr"] == pytest.approx(0.0574, abs=0.0001) and alt["revenue_cagr"] == pytest.approx(0.0466, abs=0.0001)
    assert alt["span_years"] == 4
    # V = 0.95 x (8.5 + 2g) x 4.4 / 5 at g = 5, 10, 15
    assert alt["growth_formula_at"] == {"0.05": pytest.approx(15.47, abs=0.005), "0.10": pytest.approx(23.83, abs=0.005), "0.15": pytest.approx(32.19, abs=0.005)}

    fast = [dict(r, revenue=1000.0 * 1.25 ** i, eps_diluted=0.8 * 1.3 ** i) for i, r in enumerate(ANNUAL)]
    out = run({**BASE, "annual": fast}, capsys, monkeypatch)
    assert out["inputs"]["growth_rate"]["value"] == 0.08                 # min(30%, 25%) = 25%, clipped
    assert out["inputs"]["growth_rate"]["source"].startswith("min(EPS CAGR 0.3000, revenue CAGR 0.2500) = 0.2500, clipped")


def test_growth_default_falls_back_to_revenue_cagr_and_to_input(capsys, monkeypatch) -> None:
    rows = [dict(r, eps_diluted=-0.1 if r["fiscal_year"] == 2021 else r["eps_diluted"]) for r in ANNUAL]
    out = run({**BASE, "annual": rows}, capsys, monkeypatch)
    g = out["inputs"]["growth_rate"]
    assert g["value"] == pytest.approx(0.0466, abs=0.0001)
    assert g["source"] == "revenue CAGR 0.0466 (EPS CAGR unavailable), clipped to [0, 0.08]"
    assert out["inputs"]["growth_alternatives"]["eps_cagr"] is None

    rows = [dict(r, revenue=None, eps_diluted=None) for r in ANNUAL]
    out = run({**BASE, "annual": rows}, capsys, monkeypatch)
    assert out["inputs"]["growth_rate"] == {"value": None, "source": "no positive EPS or revenue at both ends of the table; set growth_rate"}
    assert out["graham"]["growth_formula"]["value"] is None

    out = run({**BASE, "growth_rate": 0.12}, capsys, monkeypatch)
    assert out["inputs"]["growth_rate"] == {"value": 0.12, "source": "input"}
    assert out["graham"]["growth_formula"]["growth_used"] == 0.12        # the override is not clipped


# ── normalized (mid-cycle) earnings ────────────────────────────────────────


def test_normalized_block_and_graham_number_10y(capsys, monkeypatch) -> None:
    out = run(BASE, capsys, monkeypatch)
    nz = out["normalized"]
    assert nz["years"] == {"owner_earnings": 5, "eps": 5}
    assert nz["owner_earnings_10y_avg"] == pytest.approx(85.8)            # mean of 75, 80, 86, 91, 97
    assert nz["owner_earnings_10y_avg_per_share"] == pytest.approx(0.858)
    assert nz["eps_10y_avg"] == pytest.approx(0.90)
    assert nz["graham_number_10y"] == pytest.approx(11.56, abs=0.005)     # sqrt(22.5 x 0.90 x 6.6)
    assert nz["dcf_input_mid_cycle"] == {**out["buffett"]["dcf_input"], "fcf0": 85.8, "growth_rate": 0.02}
    assert not any(f["code"] == "CYCLE_PEAK" for f in out["flags"])


def test_normalized_needs_five_years(capsys, monkeypatch) -> None:
    out = run({**BASE, "annual": ANNUAL[-4:]}, capsys, monkeypatch)
    nz = out["normalized"]
    assert nz["years"] == {"owner_earnings": 4, "eps": 4}
    assert nz["owner_earnings_10y_avg"] is None and nz["eps_10y_avg"] is None
    assert nz["graham_number_10y"] is None and nz["dcf_input_mid_cycle"] is None
    assert "graham_number_10y" not in {m["method"] for m in out["margin_of_safety"]}


def test_cycle_peak_flag(capsys, monkeypatch) -> None:
    rows = [dict(r) for r in ANNUAL]
    rows[-1]["net_income"] = 400.0                                         # latest OE 397 vs 10y avg 145.8
    out = run({**BASE, "annual": rows}, capsys, monkeypatch)
    flag = next(f for f in out["flags"] if f["code"] == "CYCLE_PEAK")
    assert flag["message"].startswith("latest owner earnings are 2.72x the 5-year average")
    assert out["normalized"]["owner_earnings_10y_avg"] == pytest.approx(145.8)


# ── business type ──────────────────────────────────────────────────────────


def _bank_rows():
    rows = []
    for i, r in enumerate(ANNUAL):
        rows.append(dict(r, total_assets=6000.0 + 200.0 * i, current_assets=None, current_liabilities=None,
                         capex=5.0, free_cash_flow=r["operating_cash_flow"] - 5.0, long_term_debt=2000.0))
    return rows


def test_financial_business_type(capsys, monkeypatch) -> None:
    out = run({**BASE, "annual": _bank_rows(), "business_type": "financial"}, capsys, monkeypatch)
    assert out["inputs"]["business_type"] == "financial"
    g = out["graham"]
    assert g["ncav_per_share"] is None and g["net_net"] == {"two_thirds_ncav": None, "price_below": None}
    codes = {f["code"] for f in out["flags"]}
    assert "NEGATIVE_NCAV" not in codes
    na = next(f for f in out["flags"] if f["code"] == "NOT_APPLICABLE")
    assert "business_type financial" in na["message"] and "net-net" in na["message"]
    fc = next(c for c in g["defensive_checklist"]["checks"] if c["check"] == "financial_condition")
    assert fc["passed"] is True                                            # 660 / 6800 = 9.7% >= 8%
    assert fc["value"] == {"equity_to_assets": pytest.approx(0.0971, abs=0.0001), "equity": 660.0, "total_assets": 6800.0}
    assert fc["threshold"].startswith("equity / total assets >= 0.08 (business_type financial")
    # DCF still built, flagged, with net debt zeroed
    assert "DCF_NOT_MEANINGFUL_FOR_FINANCIALS" in codes
    dcf = out["buffett"]["dcf_input"]
    assert dcf["fcf0"] == 100.0 and dcf["net_debt"] == 0.0 and "business_type financial" in dcf["net_debt_note"]   # 100 + 27 - max(27, 5)
    assert out["normalized"]["dcf_input_mid_cycle"]["net_debt"] == 0.0
    # little-debt tenet skipped, so the tenets score out of six
    t = out["buffett"]["tenets"]
    ll = next(c for c in t["checks"] if c["check"] == "low_leverage")
    assert ll["passed"] is None and ll["value"] is None and "financial" in ll["threshold"]
    assert t["out_of"] == 6
    bv = out["buffett"]["book_value_tests"]
    assert bv["price_to_book"] == pytest.approx(1.8182, abs=0.0001)
    assert bv["roe_latest"] == pytest.approx(0.1515, abs=0.0001)          # 100 / 660
    assert bv["roe_10y_avg"] == pytest.approx(0.1555, abs=0.0001)
    assert bv["price_to_book_x_roe_note"].startswith("P/B 1.82 against ROE 15.2% (10y avg 15.5%)")
    assert bv["price_to_book_x_roe_note"].endswith("(ROE - g) / (r - g) = 2.26")   # (0.1555 - 0.02) / (0.08 - 0.02)
    assert out["buffett"]["reit_tests"] is None
    assert "ncav" not in {m["method"] for m in out["margin_of_safety"]}


def test_financial_condition_fails_thin_equity_and_needs_total_assets(capsys, monkeypatch) -> None:
    rows = [dict(r, total_assets=12000.0) for r in _bank_rows()]
    out = run({**BASE, "annual": rows, "business_type": "financial"}, capsys, monkeypatch)
    fc = next(c for c in out["graham"]["defensive_checklist"]["checks"] if c["check"] == "financial_condition")
    assert fc["passed"] is False and fc["value"]["equity_to_assets"] == pytest.approx(0.055)
    rows = [dict(r, total_assets=None) for r in _bank_rows()]
    out = run({**BASE, "annual": rows, "business_type": "financial"}, capsys, monkeypatch)
    fc = next(c for c in out["graham"]["defensive_checklist"]["checks"] if c["check"] == "financial_condition")
    assert fc["passed"] is None and fc["value"]["equity_to_assets"] is None


def test_reit_business_type(capsys, monkeypatch) -> None:
    out = run({**BASE, "business_type": "reit"}, capsys, monkeypatch)
    oe = out["buffett"]["owner_earnings"]
    assert oe["maintenance_capex"] == 12.0 and oe["maintenance_capex_method"] == "1% of revenue (business_type reit)"
    assert oe["value"] == pytest.approx(115.0)                              # 100 + 27 - 12
    assert [y["value"] for y in oe["by_year"]] == [95.0, 99.5, 105.0, 109.5, 115.0]
    rt = out["buffett"]["reit_tests"]
    assert rt["affo_proxy_per_share"] == pytest.approx(1.15)
    assert rt["price_to_affo_proxy"] == pytest.approx(10.4348, abs=0.0001)
    assert rt["affo_proxy_yield"] == pytest.approx(1.15 / 12, abs=0.0001)
    assert rt["affo_proxy_per_share_cagr"] == pytest.approx((1.15 / 0.95) ** 0.25 - 1, abs=0.0001)
    assert rt["dividend_yield"] == pytest.approx(0.0167, abs=0.0001)               # 0.20 / 12
    assert rt["dividend_per_share_cagr"] == 0.0
    assert rt["payout_of_affo_proxy"] == pytest.approx(0.1739, abs=0.0001)         # 0.20 / 1.15
    assert rt["net_debt_to_ebitda"] == pytest.approx((150 - 50) / (140 + 27), abs=0.0001)
    assert rt["ddm_input"]["model"] == "gordon" and rt["ddm_input"]["dividend0"] == 0.2 and rt["ddm_input"]["terminal_growth"] == 0.0
    # the growth default is the AFFO proxy's own per-share record, not GAAP EPS
    assert out["inputs"]["growth_rate"]["source"].startswith("min(AFFO-proxy-per-share CAGR 0.0489, revenue CAGR 0.0466)")
    # Graham's EPS-based values are still reported but not set against the price
    assert [m["method"] for m in out["margin_of_safety"]] == []
    assert out["buffett"]["book_value_tests"] is None
    codes = {f["code"] for f in out["flags"]}
    assert "GAAP_EPS_UNDERSTATES_REIT" in codes and "NOT_APPLICABLE" not in codes
    assert next(f for f in out["flags"] if f["code"] == "MAINTENANCE_CAPEX_ESTIMATED")["message"].startswith("maintenance capex is estimated as 1% of revenue")
    assert out["graham"]["graham_number"] == pytest.approx(11.88, abs=0.005)   # still reported
    assert out["graham"]["ncav_per_share"] == pytest.approx(-0.60)
    # the override still wins
    out = run({**BASE, "business_type": "reit", "maintenance_capex": 20.0}, capsys, monkeypatch)
    assert out["buffett"]["owner_earnings"]["maintenance_capex_method"] == "override"
    assert out["buffett"]["reit_tests"]["affo_proxy_per_share"] == pytest.approx(1.07)


def test_industrial_is_the_default_and_has_no_type_blocks(capsys, monkeypatch) -> None:
    out = run(BASE, capsys, monkeypatch)
    assert out["inputs"]["business_type"] == "industrial"
    assert out["buffett"]["book_value_tests"] is None and out["buffett"]["reit_tests"] is None
    assert out["buffett"]["tenets"]["out_of"] == 7


def _without(field, rows):
    return [{**r, field: None} for r in rows]


def test_owner_earnings_dcf_does_not_subtract_debt_a_second_time(capsys, monkeypatch) -> None:
    """Measured 2026-09-30 on VICI and EXC: owner earnings (net income + D&A - maintenance capex)
    are after interest, yet the handoff subtracted long-term debt again, pricing VICI at $32
    instead of $47 and Exelon at $6 instead of $54. The handoff is an equity cash flow now."""
    out = run(BASE, capsys, monkeypatch)
    for key in ("dcf_input",):
        assert out["buffett"][key]["net_debt"] == 0.0
    mid = out["normalized"]["dcf_input_mid_cycle"]
    assert mid["net_debt"] == 0.0 and mid["net_debt_note"] == out["buffett"]["dcf_input"]["net_debt_note"]
    note = out["buffett"]["dcf_input"]["net_debt_note"]
    assert "long-term debt 150.00 less cash 50.00 = 100.00" in note and "twice" in note


@pytest.mark.parametrize("missing", [("long_term_debt",), ("cash",), ("cash", "long_term_debt")])
def test_untagged_debt_or_cash_no_longer_matters(missing, capsys, monkeypatch) -> None:
    rows = ANNUAL
    for field in missing:
        rows = _without(field, rows)
    out = run({**BASE, "annual": rows}, capsys, monkeypatch)
    dcf = out["buffett"]["dcf_input"]
    assert dcf["net_debt"] == 0.0 and "after interest" in dcf["net_debt_note"]
    assert "less cash" not in dcf["net_debt_note"]            # no balance-sheet figure to quote
    assert "NET_DEBT_ASSUMED" not in [f["code"] for f in out["flags"]]


# --- per-share history, sale gains, utilities ---------------------------------------------------


def _with(rows, **cols):
    """ANNUAL with one or more columns replaced, one value per year."""
    return [{**r, **{k: v[i] for k, v in cols.items()}} for i, r in enumerate(rows)]


def test_growth_default_uses_revenue_per_share_so_issued_shares_do_not_count(capsys, monkeypatch) -> None:
    doubled = _with(ANNUAL, diluted_shares=[100.0, 120.0, 140.0, 170.0, 200.0])
    out = run({**BASE, "annual": doubled}, capsys, monkeypatch)
    alt = out["inputs"]["growth_alternatives"]
    assert alt["revenue_cagr"] == pytest.approx(0.0466, abs=1e-4)
    assert alt["revenue_per_share_cagr"] == pytest.approx((1200 / 200 / (1000 / 100)) ** 0.25 - 1, abs=1e-4)
    assert out["inputs"]["growth_rate"]["value"] == 0.0  # revenue per share fell, clipped at zero
    assert "revenue-per-share CAGR" in out["inputs"]["growth_rate"]["source"]


def test_growth_default_does_not_credit_buybacks_either(capsys, monkeypatch) -> None:
    shrunk = _with(ANNUAL, diluted_shares=[100.0, 90.0, 80.0, 70.0, 60.0])
    out = run({**BASE, "annual": shrunk}, capsys, monkeypatch)
    alt = out["inputs"]["growth_alternatives"]
    assert alt["revenue_per_share_cagr"] > alt["revenue_cagr"]
    assert out["inputs"]["growth_rate"]["value"] == pytest.approx(0.0466, abs=1e-4)   # total revenue, the lower one
    assert "revenue CAGR 0.0466" in out["inputs"]["growth_rate"]["source"]


def test_mid_cycle_averages_per_share_on_each_years_share_count(capsys, monkeypatch) -> None:
    """A company that issued shares to grow: the dollar average would mark it down for having
    been smaller, and would call the latest year a cycle peak."""
    grown = _with(
        ANNUAL,
        net_income=[20.0, 40.0, 60.0, 80.0, 100.0],
        depreciation_amortization=[30.0] * 5,
        diluted_shares=[20.0, 40.0, 60.0, 80.0, 100.0],
    )
    out = run({**BASE, "annual": grown, "maintenance_capex": 30.0}, capsys, monkeypatch)
    norm = out["normalized"]
    assert norm["basis"].startswith("per share")
    assert norm["owner_earnings_10y_avg_per_share"] == 1.0         # 1.00 a share every year
    assert norm["owner_earnings_10y_avg"] == 100.0                 # on today's 100 shares, not the 60 dollar average
    assert norm["dcf_input_mid_cycle"]["fcf0"] == 100.0
    assert "CYCLE_PEAK" not in {f["code"] for f in out["flags"]}


def test_mid_cycle_falls_back_to_dollars_without_share_counts(capsys, monkeypatch) -> None:
    out = run({**BASE, "annual": _with(ANNUAL, diluted_shares=[None] * 5), "shares_outstanding": 100.0}, capsys, monkeypatch)
    assert out["normalized"]["basis"].startswith("total dollars")
    assert out["normalized"]["owner_earnings_10y_avg"] is not None


def test_reit_owner_earnings_leave_out_gains_on_property_sales(capsys, monkeypatch) -> None:
    sold = _with(ANNUAL, gain_on_property_sales=[None, None, None, None, 40.0])
    out = run({**BASE, "annual": sold, "business_type": "reit"}, capsys, monkeypatch)
    assert out["buffett"]["owner_earnings"]["value"] == pytest.approx(75.0)   # 100 + 27 - 40 gain - 12
    assert out["buffett"]["reit_tests"]["property_sale_gains_excluded"] == 40.0
    # an industrial keeps its gains: they are not taken out of owner earnings
    out = run({**BASE, "annual": sold}, capsys, monkeypatch)
    assert out["buffett"]["owner_earnings"]["value"] == pytest.approx(100.0 + 27.0 - 30.0)


def test_utility_business_type(capsys, monkeypatch) -> None:
    out = run({**BASE, "business_type": "utility"}, capsys, monkeypatch)
    oe = out["buffett"]["owner_earnings"]
    assert oe["maintenance_capex"] == 27.0 and oe["maintenance_capex_method"].startswith("depreciation_amortization")
    assert oe["value"] == pytest.approx(100.0)                              # net income: D&A stands in for upkeep
    ut = out["buffett"]["utility_tests"]
    assert ut["pe"] == pytest.approx(12.0) and ut["price_to_book"] == pytest.approx(12 / 6.6, abs=1e-4)
    assert ut["roe_latest"] == pytest.approx(100 / 660, abs=1e-4)
    assert ut["dividend_yield"] == pytest.approx(0.2 / 12, abs=1e-4) and ut["payout_of_eps"] == pytest.approx(0.2)
    assert ut["ddm_input"] == out["buffett"]["utility_tests"]["ddm_input"] and ut["ddm_input"]["required_return"] == 0.08
    codes = {f["code"] for f in out["flags"]}
    assert "DCF_NOT_MEANINGFUL_FOR_UTILITIES" in codes
    assert out["buffett"]["reit_tests"] is None and out["buffett"]["book_value_tests"] is None
    assert run(BASE, capsys, monkeypatch)["buffett"]["utility_tests"] is None


def test_mostly_negative_owner_earnings_withhold_the_mid_cycle_dcf(capsys, monkeypatch) -> None:
    burning = _with(ANNUAL, net_income=[-50.0, -40.0, -30.0, -10.0, 20.0])
    out = run({**BASE, "annual": burning}, capsys, monkeypatch)
    flag = next(f for f in out["flags"] if f["code"] == "OWNER_EARNINGS_MOSTLY_NEGATIVE")
    assert "4 of 5 years" in flag["message"]
    assert out["normalized"]["dcf_input_mid_cycle"] is None
    assert "OWNER_EARNINGS_MOSTLY_NEGATIVE" not in {f["code"] for f in run(BASE, capsys, monkeypatch)["flags"]}


def test_ddm_growth_is_the_dividend_record_clipped(capsys, monkeypatch) -> None:
    raised = _with(ANNUAL, dividends_paid=[10.0, 12.0, 15.0, 18.0, 22.0])
    out = run({**BASE, "annual": raised, "business_type": "utility"}, capsys, monkeypatch)
    ddm = out["buffett"]["utility_tests"]["ddm_input"]
    assert out["buffett"]["utility_tests"]["dividend_per_share_cagr"] == pytest.approx((22 / 10) ** 0.25 - 1, abs=1e-4)
    assert ddm["terminal_growth"] == 0.04 and "clipped" in ddm["terminal_growth_note"]
    none_paid = _with(ANNUAL, dividends_paid=[None] * 5)
    assert run({**BASE, "annual": none_paid, "business_type": "utility"}, capsys, monkeypatch)["buffett"]["utility_tests"]["ddm_input"] is None
