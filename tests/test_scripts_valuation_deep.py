"""Deep-valuation scripts: model.py (segment/scenario engine), returns.py (IRR at today's price),
render_deep.py (block page)."""

from __future__ import annotations

import io
import json
import sys

import pytest
from page_dom import assert_page_help, render_and_audit, requires_chrome
from scripts_util import PLUGIN_ROOT, load_script, run_json


def run_stdin(rel: str, payload: dict, capsys, monkeypatch) -> dict:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script(rel).main()
    return json.loads(capsys.readouterr().out)


def run_stdin_error(rel: str, payload: dict, capsys, monkeypatch) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as excinfo:
        load_script(rel).main()
    return excinfo.value.code, json.loads(capsys.readouterr().out)


MODEL = "valuation/scripts/model.py"


def base_input(**over) -> dict:
    p = {
        "symbol": "ACME", "price": 20.0, "shares_outstanding": 100.0, "years": 10, "horizon": 5,
        "base_discount_rate": 0.09, "tax_rate": 0.25, "cost_of_debt": 0.05,
        "claims": {"debt": 300.0, "cash": 100.0},
        "payout": 0.5,
        "segments": [{"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.05,
                      "margin": 0.15, "sales_to_capital": 2.0,
                      "terminal": {"method": "gordon", "growth": 0.02}}],
        "scenarios": [{"name": "Base", "summary": "Steady.", "must_be_true": ["Margin holds"]}],
    }
    p.update(over)
    return p


def closed_form_operating(rev0, g, m, s2c, tax, r, tg, n):
    pv, rev = 0.0, rev0
    for t in range(1, n + 1):
        new = rev * (1 + g)
        pv += (new * m * (1 - tax) - (new - rev) / s2c) / (1 + r) ** t
        rev = new
    nxt = rev * (1 + tg)
    tv = (nxt * m * (1 - tax) - (nxt - rev) / s2c) / (r - tg)
    return pv + tv / (1 + r) ** n


def test_model_single_operating_segment_matches_closed_form(capsys, monkeypatch) -> None:
    out = run_stdin(MODEL, base_input(), capsys, monkeypatch)
    ev = closed_form_operating(1000, 0.05, 0.15, 2.0, 0.25, 0.09, 0.02, 10)
    sc = out["scenarios"][0]
    assert sc["enterprise_value"] == pytest.approx(ev, abs=0.01)
    assert sc["equity_value"] == pytest.approx(ev - 300 + 100, abs=0.01)
    assert sc["value_per_share"] == pytest.approx((ev - 200) / 100, abs=0.01)
    assert sc["upside"] == pytest.approx(((ev - 200) / 100) / 20 - 1, abs=1e-4)
    seg = sc["segments"][0]
    assert seg["discount_rate"] == 0.09 and len(seg["years"]) == 10
    assert 0 < seg["terminal_share"] < 1


def test_model_exit_multiple_terminal(capsys, monkeypatch) -> None:
    seg = {"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.0, "margin": 0.10,
           "sales_to_capital": 2.0, "da_pct_revenue": 0.05,
           "terminal": {"method": "multiple", "metric": "ebitda", "multiple": 8}}
    out = run_stdin(MODEL, base_input(segments=[seg]), capsys, monkeypatch)
    # flat revenue: no reinvestment; FCFF = 1000*0.10*0.75 = 75 each year; TV = 8 * (100 + 50)
    pv = sum(75 / 1.09**t for t in range(1, 11)) + 8 * 150 / 1.09**10
    assert out["scenarios"][0]["enterprise_value"] == pytest.approx(pv, abs=0.01)


def test_model_cost_asset_venture_add_as_stated(capsys, monkeypatch) -> None:
    core = base_input()["segments"][0]
    extra = [
        {"name": "HQ", "kind": "cost", "cost0": 10.0, "growth": 0.0, "terminal_growth": 0.0},
        {"name": "Stake", "kind": "asset", "value": 50.0},
        {"name": "Moonshot", "kind": "venture", "value_if_success": 400.0, "probability": 0.25, "cost_pv": 30.0},
    ]
    alone = run_stdin(MODEL, base_input(), capsys, monkeypatch)["scenarios"][0]["enterprise_value"]
    out = run_stdin(MODEL, base_input(segments=[core, *extra]), capsys, monkeypatch)
    hq = -10 / 0.09  # flat perpetuity: 10 years explicit + Gordon at 0 growth == 10 / r
    assert out["scenarios"][0]["enterprise_value"] == pytest.approx(alone + hq + 50 + (0.25 * 400 - 30), abs=0.02)


def test_model_residual_income_segment(capsys, monkeypatch) -> None:
    bank = {"name": "Bank", "kind": "residual_income", "book0": 1000.0, "roe": 0.12, "retention": 0.5,
            "cost_of_equity": 0.10, "terminal_growth": 0.03}
    out = run_stdin(MODEL, base_input(segments=[bank], claims={}, years=6, horizon=5), capsys, monkeypatch)
    book, pv = 1000.0, 0.0
    for t in range(1, 7):
        pv += (0.12 - 0.10) * book / 1.10**t
        book *= 1 + 0.12 * 0.5
    tv = (0.12 - 0.10) * book / (0.10 - 0.03) / 1.10**6
    sc = out["scenarios"][0]
    assert sc["enterprise_value"] == 0
    assert sc["equity_value"] == pytest.approx(1000 + pv + tv, abs=0.01)


def test_model_rejects_wrong_length_path(capsys, monkeypatch) -> None:
    p = base_input()
    p["segments"][0]["growth"] = [0.05] * 5
    rc, out = run_stdin_error(MODEL, p, capsys, monkeypatch)
    assert rc == 2 and "Core.growth" in out["error"] and "10" in out["error"]


@pytest.mark.parametrize("patch, needle", [
    ({"shares_outstanding": 0}, "shares_outstanding"),
    ({"years": 5, "horizon": 5}, "years"),
    ({"segments": []}, "segments"),
    ({"segments": [{"name": "X", "kind": "magic"}]}, "kind"),
    ({"payout": 1.5}, "payout"),
])
def test_model_validation(patch, needle, capsys, monkeypatch) -> None:
    rc, out = run_stdin_error(MODEL, base_input(**patch), capsys, monkeypatch)
    assert rc == 2 and needle in out["error"]


def test_model_gordon_growth_at_rate_is_rejected(capsys, monkeypatch) -> None:
    p = base_input()
    p["segments"][0]["terminal"] = {"method": "gordon", "growth": 0.09}
    rc, out = run_stdin_error(MODEL, p, capsys, monkeypatch)
    assert rc == 2 and "terminal growth" in out["error"]


def test_model_overrides_change_only_named_fields(capsys, monkeypatch) -> None:
    p = base_input(scenarios=[{"name": "Base"}, {"name": "Squeeze", "overrides": {"Core": {"margin": 0.10}}}])
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    base, sq = out["scenarios"]
    assert base["segments"][0]["years"][0]["revenue"] == sq["segments"][0]["years"][0]["revenue"]
    assert sq["segments"][0]["years"][0]["ebit"] == pytest.approx(1050 * 0.10, abs=0.01)
    assert sq["value_per_share"] < base["value_per_share"]


def test_model_override_unknown_segment(capsys, monkeypatch) -> None:
    p = base_input(scenarios=[{"name": "X", "overrides": {"Cor": {"margin": 0.1}}}])
    rc, out = run_stdin_error(MODEL, p, capsys, monkeypatch)
    assert rc == 2 and "'Cor'" in out["error"]


def test_model_fails_truncates_and_adds_salvage(capsys, monkeypatch) -> None:
    p = base_input(claims={}, scenarios=[{"name": "Dies", "overrides": {"Core": {"fails": {"year": 3, "salvage": 100.0}}}}])
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    pv = 0.0
    rev = 1000.0
    for t in (1, 2):
        new = rev * 1.05
        pv += (new * 0.15 * 0.75 - (new - rev) / 2.0) / 1.09**t
        rev = new
    pv += 100 / 1.09**3
    assert out["scenarios"][0]["enterprise_value"] == pytest.approx(pv, abs=0.01)


def test_model_value_ex_premiums(capsys, monkeypatch) -> None:
    p = base_input()
    p["segments"][0].update(discount_premium=0.03, premium_reason="vague plan")
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    plain = run_stdin(MODEL, base_input(), capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert sc["segments"][0]["discount_rate"] == 0.12 and sc["segments"][0]["premium_reason"] == "vague plan"
    assert sc["value_ex_premiums"] == plain["scenarios"][0]["value_per_share"]
    assert sc["value_per_share"] < sc["value_ex_premiums"]


def test_model_path_and_roll_exit(capsys, monkeypatch) -> None:
    # no debt, payout 1, no growth: FCFE = FCFF = 112.5 each year, all distributed, exit = value at H
    seg = {"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.0, "margin": 0.15,
           "sales_to_capital": 2.0, "terminal": {"method": "gordon", "growth": 0.0}}
    out = run_stdin(MODEL, base_input(segments=[seg], claims={}, payout=1.0), capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert all(p["distributions_per_share"] == pytest.approx(1.125) for p in sc["path"])
    assert sc["exit"]["dcf_roll"] == pytest.approx(112.5 / 0.09 / 100, abs=0.01)
    assert sc["value_per_share"] == pytest.approx(112.5 / 0.09 / 100, abs=0.01)
    ri = out["returns_input"]
    assert ri["mode"] == "paths" and ri["horizon"] == 5 and ri["scenarios"][0]["exit_value_per_share"] == sc["exit"]["dcf_roll"]


def test_model_retained_cash_lowers_net_debt(capsys, monkeypatch) -> None:
    out = run_stdin(MODEL, base_input(payout=0.0), capsys, monkeypatch)
    nd = [p["net_debt"] for p in out["scenarios"][0]["path"]]
    assert nd[0] < 200 and all(b < a for a, b in zip(nd, nd[1:]))


def test_model_exit_multiple(capsys, monkeypatch) -> None:
    p = base_input(claims={}, scenarios=[{"name": "Base", "exit_multiple": {"metric": "ebit", "multiple": 10}}])
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    sc = out["scenarios"][0]
    ebit5 = 1000 * 1.05**5 * 0.15
    nd5 = sc["path"][-1]["net_debt"]
    assert sc["exit"]["multiple"] == pytest.approx((10 * ebit5 - nd5) / 100, abs=0.01)


def test_model_sensitivity_centre_equals_scenario(capsys, monkeypatch) -> None:
    p = base_input(sensitivity={"a": {"segment": "Core", "field": "margin_shift", "values": [-0.01, 0, 0.01]},
                                "b": {"segment": "Core", "field": "discount_premium", "values": [0, 0.02]}})
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    grid = out["sensitivity"]["value_per_share"]
    assert grid[1][0] == out["scenarios"][0]["value_per_share"]
    assert grid[2][0] > grid[1][0] > grid[0][0] and grid[1][1] < grid[1][0]


def test_model_sensitivity_null_cell(capsys, monkeypatch) -> None:
    p = base_input(sensitivity={"a": {"segment": "Core", "field": "terminal_growth", "values": [0.02, 0.10]},
                                "b": {"segment": "Core", "field": "discount_premium", "values": [0]}})
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    assert out["sensitivity"]["value_per_share"][1] == [None]


def test_model_flags(capsys, monkeypatch) -> None:
    p = base_input(history={"Core": {"max_margin": 0.12}}, claims={"debt": 1e6})
    p["segments"][0]["terminal"]["growth"] = 0.08
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    codes = {f["code"] for f in out["flags"]}
    assert {"TERMINAL_HEAVY", "MARGIN_ABOVE_HISTORY", "NEGATIVE_EQUITY"} <= codes


RETURNS = "valuation/scripts/returns.py"


def test_returns_known_irr(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "paths", "price": 100, "horizon": 5, "hurdle": 0.10,
                              "scenarios": [{"name": "A", "distributions_per_share": [0] * 5, "exit_value_per_share": 161.051}]}, capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert sc["irr"] == pytest.approx(0.10, abs=1e-5)
    assert sc["total_multiple"] == pytest.approx(1.6105, abs=1e-4)
    assert sc["hurdle_exit_value"] == pytest.approx(161.05, abs=0.01)


def test_returns_hurdle_round_trip_with_distributions(capsys, monkeypatch) -> None:
    p = {"mode": "paths", "price": 50, "horizon": 3, "hurdle": 0.12,
         "scenarios": [{"name": "A", "distributions_per_share": [2, 2, 2], "exit_value_per_share": 40}]}
    hev = run_stdin(RETURNS, p, capsys, monkeypatch)["scenarios"][0]["hurdle_exit_value"]
    p["scenarios"][0]["exit_value_per_share"] = hev
    assert run_stdin(RETURNS, p, capsys, monkeypatch)["scenarios"][0]["irr"] == pytest.approx(0.12, abs=1e-4)


def test_returns_irr_at_multiple(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "paths", "price": 100, "horizon": 1, "scenarios": [
        {"name": "A", "distributions_per_share": [0], "exit_value_per_share": 110, "exit_multiple_value": 120}]}, capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert sc["irr"] == pytest.approx(0.10, abs=1e-5) and sc["irr_at_multiple"] == pytest.approx(0.20, abs=1e-5)


def test_returns_convergence_at_fair_price_earns_cost_of_equity(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "convergence", "price": 40, "horizon": 5, "scenarios": [
        {"name": "Base", "fair_value": 40, "cost_of_equity": 0.09, "dividend_yield": 0.0},
        {"name": "Div", "fair_value": 40, "cost_of_equity": 0.09, "dividend_yield": 0.03}]}, capsys, monkeypatch)
    assert out["scenarios"][0]["irr"] == pytest.approx(0.09, abs=1e-5)
    assert out["scenarios"][1]["irr"] == pytest.approx(0.09, abs=1e-5)
    assert out["assumptions"]


def test_returns_convergence_cheap_stock_beats_cost_of_equity(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "convergence", "price": 30, "horizon": 5, "scenarios": [
        {"name": "Base", "fair_value": 40, "cost_of_equity": 0.09, "dividend_yield": 0.0}]}, capsys, monkeypatch)
    assert out["scenarios"][0]["irr"] == pytest.approx((40 * 1.09**5 / 30) ** 0.2 - 1, abs=1e-5)


def test_returns_total_loss(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "paths", "price": 10, "horizon": 3, "scenarios": [
        {"name": "Bust", "distributions_per_share": [0, 0, 0], "exit_value_per_share": -4}]}, capsys, monkeypatch)
    assert out["scenarios"][0]["irr"] == -1.0 and "TOTAL_LOSS" in {f["code"] for f in out["flags"]}


@pytest.mark.parametrize("payload, needle", [
    ({"mode": "paths", "price": 0, "horizon": 5, "scenarios": []}, "price"),
    ({"mode": "x", "price": 10, "horizon": 5, "scenarios": []}, "mode"),
    ({"mode": "paths", "price": 10, "horizon": 2, "scenarios": [{"name": "A", "distributions_per_share": [1], "exit_value_per_share": 1}]}, "distributions_per_share"),
])
def test_returns_validation(payload, needle, capsys, monkeypatch) -> None:
    rc, out = run_stdin_error(RETURNS, payload, capsys, monkeypatch)
    assert rc == 2 and needle in out["error"]


def test_model_pipes_into_returns(capsys, monkeypatch) -> None:
    ri = run_stdin(MODEL, base_input(), capsys, monkeypatch)["returns_input"]
    out = run_stdin(RETURNS, ri, capsys, monkeypatch)
    assert out["scenarios"][0]["name"] == "Base" and out["scenarios"][0]["irr"] is not None


RENDER = "valuation/scripts/render_deep.py"
SAMPLE = PLUGIN_ROOT / "docs/samples/valuation-deep.json"


def page_input() -> dict:
    p = base_input(
        segments=[*base_input()["segments"], {"name": "HQ", "kind": "cost", "cost0": 10.0}],
        scenarios=[{"name": "Base", "summary": "Steady.", "must_be_true": ["Margin holds"]},
                   {"name": "Squeeze", "summary": "Pricing gives.", "must_be_true": ["Rivals cut price"],
                    "overrides": {"Core": {"margin": 0.10, "discount_premium": 0.02, "premium_reason": "guidance track record is poor"}}}],
        sensitivity={"a": {"segment": "Core", "field": "margin_shift", "values": [-0.02, 0, 0.02]},
                     "b": {"segment": "Core", "field": "discount_premium", "values": [0, 0.02]}})
    model = json.loads(json.dumps(load_script(MODEL).run_model(p)))
    rets = json.loads(json.dumps(load_script(RETURNS).run_returns(model["returns_input"])))
    ledger = [{"id": "B1", "belief": "Price increases stick", "holder": "management", "stakes": "high", "verdict": "doubtful",
               "if_true": "up", "headline": "Price increases not sticking", "takeaway": "Price increases are not sticking: volumes fell 6% as prices rose 4%.",
               "for": [{"claim": "Q2 price up 4%", "source": "10-Q Item 2", "date": "2026-08-01"}],
               "against": [{"claim": "Volumes fell 6%", "source": "10-Q Item 2", "date": "2026-08-01"}],
               "consequence": {"segment": "Core", "field": "margin", "change": "10% in Squeeze"}, "thread": "threads/1-pricing.md"}]
    return {"symbol": "ACME", "price": 20.0, "as_of": "2026-10-05", "model": model, "returns": rets, "ledger": ledger,
            "blocks": [{"type": "segments", "scenario": "Base"}, {"type": "drivers", "segment": "Core", "field": "fcff"},
                       {"type": "ledger"}, {"type": "track_record", "rows": [{"period": "FY2025", "metric": "Revenue growth", "guided": "8%", "actual": "5%", "source": "8-K 2026-02-10"}]},
                       {"type": "forensics", "items": [{"finding": "Receivables up 20% vs revenue up 5%", "severity": "medium", "source": "10-K 2026-02-20"}]},
                       {"type": "skepticism"}, {"type": "sensitivity"},
                       {"type": "custom", "title": "Lease adjustment", "file": "custom/leases.py", "result": "12.3", "explanation": "Capitalized operating leases."},
                       {"type": "text", "title": "What the market may be missing", "markdown": "**Pricing** is the swing factor.\n\n- one\n- two"}],
            "missing_roles": ["industry"], "notes": ["Sample built from invented figures."]}


def test_render_deep_every_block(tmp_path, capsys, monkeypatch) -> None:
    data = page_input()
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 0, res
    assert res["scenarios"] == ["Base", "Squeeze"] and len(res["blocks"]) == 9 and res["flags"] >= 2
    html = (tmp_path / "p.html").read_text()
    assert "ACME" in html and "<script" in html


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["blocks"].append({"type": "chart3d"}), "chart3d"),
    (lambda d: d["blocks"].append({"type": "drivers", "segment": "Core"}), "field"),
    (lambda d: d["blocks"].append({"type": "drivers", "segment": "Nope", "field": "fcff"}), "Nope"),
    (lambda d: d.pop("model"), "model"),
])
def test_render_deep_rejects_bad_blocks(mutate, needle, tmp_path, capsys, monkeypatch) -> None:
    data = page_input()
    mutate(data)
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"]


def test_render_deep_rejects_undated_claim(tmp_path, capsys, monkeypatch) -> None:
    data = page_input()
    del data["ledger"][0]["against"][0]["date"]
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and "B1" in res["error"] and "date" in res["error"]


def test_render_deep_sample_is_current(capsys, monkeypatch) -> None:
    """docs/samples/valuation-deep.json is page_input() as committed; regenerate it when this fails."""
    assert json.loads(SAMPLE.read_text()) == page_input()


def test_render_deep_body_intros() -> None:
    import re
    body = load_script(RENDER).BODY
    for m in re.finditer(r'<section([^>]*)>\s*<h2[^>]*>(.*?)</h2>\s*(<p class="sub)?', body, re.S):
        assert m.group(3), f"section {m.group(2)!r} has no intro line"
    from second_opinion import page
    assert page.FLAGS_INTRO in body


@requires_chrome
def test_render_deep_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit(RENDER, ["--in", str(SAMPLE)], tmp_path, capsys)
    assert_page_help(a)
    shown = {c["h2"] for c in a["cards"] if not c["hidden"]}
    assert {"Scenarios", "Price against the scenarios", "Belief ledger"} <= shown


def test_model_flags_are_one_per_segment_across_scenarios(capsys, monkeypatch) -> None:
    """A real run raised one REINVESTMENT_NEGATIVE per scenario per segment (12 lines saying one thing)."""
    p = base_input(scenarios=[{"name": "A"}, {"name": "B"}, {"name": "C"}])
    p["segments"][0]["growth"] = [-0.05] + [0.03] * 9
    p["segments"][0]["terminal"]["growth"] = 0.08
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    for code in ("REINVESTMENT_NEGATIVE", "TERMINAL_HEAVY"):
        hits = [f for f in out["flags"] if f["code"] == code]
        assert len(hits) == 1, hits
        assert "Core" in hits[0]["message"] and all(n in hits[0]["message"] for n in ("A", "B", "C"))


# --- final-review fixes -------------------------------------------------------------------------


def test_returns_negative_exit_is_floored_at_zero(capsys, monkeypatch) -> None:
    """Equity has limited liability: a negative exit is worth 0, so the IRR solves instead of going null."""
    out = run_stdin(RETURNS, {"mode": "paths", "price": 50, "horizon": 5, "scenarios": [
        {"name": "Bust", "distributions_per_share": [1, 1, 1, 1, 1], "exit_value_per_share": -3, "exit_multiple_value": -2}]}, capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert sc["exit_value_per_share"] == 0 and sc["irr"] is not None and sc["irr"] < -0.4
    assert sc["irr_at_multiple"] == sc["irr"]
    assert any(f["code"] == "EXIT_FLOORED" for f in out["flags"])


def test_model_default_payout_earns_the_discount_rate_at_value(capsys, monkeypatch) -> None:
    """With no payout given, buying at value_per_share earns the discount rate (no idle cash)."""
    p = base_input(claims={}, tax_rate=0.25, cost_of_debt=0.0)
    del p["payout"]
    m = run_stdin(MODEL, p, capsys, monkeypatch)
    ri = m["returns_input"]
    ri["price"] = m["scenarios"][0]["value_per_share"]
    assert run_stdin(RETURNS, ri, capsys, monkeypatch)["scenarios"][0]["irr"] == pytest.approx(0.09, abs=2e-4)


def test_model_fcfe_exit_multiple_keeps_retained_cash(capsys, monkeypatch) -> None:
    sc = [{"name": "Base", "exit_multiple": {"metric": "fcfe", "multiple": 10}}]
    keep = run_stdin(MODEL, base_input(claims={}, payout=0.0, cost_of_debt=0.0, scenarios=sc), capsys, monkeypatch)["scenarios"][0]
    pay = run_stdin(MODEL, base_input(claims={}, payout=1.0, cost_of_debt=0.0, scenarios=sc), capsys, monkeypatch)["scenarios"][0]
    retained = -keep["path"][-1]["net_debt"] / 100
    assert retained > 1 and keep["exit"]["multiple"] == pytest.approx(pay["exit"]["multiple"] + retained, abs=0.01)


def test_model_sensitivity_terminal_growth_on_cost_segment(capsys, monkeypatch) -> None:
    p = base_input(segments=[*base_input()["segments"], {"name": "HQ", "kind": "cost", "cost0": 10.0}],
                   sensitivity={"a": {"segment": "HQ", "field": "terminal_growth", "values": [0.0, 0.02]},
                                "b": {"segment": "HQ", "field": "growth_shift", "values": [0.0, 0.01]}})
    grid = run_stdin(MODEL, p, capsys, monkeypatch)["sensitivity"]["value_per_share"]
    assert grid[0][0] > grid[1][0] and grid[0][0] > grid[0][1]


@pytest.mark.parametrize("seg_terminal, field", [
    ({"method": "multiple", "metric": "ebit", "multiple": 10}, "terminal_growth"),
    ({"method": "gordon", "growth": 0.02}, "terminal_multiple"),
])
def test_model_sensitivity_axis_that_does_nothing_is_rejected(seg_terminal, field, capsys, monkeypatch) -> None:
    p = base_input(sensitivity={"a": {"segment": "Core", "field": field, "values": [1, 2]},
                                "b": {"segment": "Core", "field": "margin_shift", "values": [0]}})
    p["segments"][0]["terminal"] = seg_terminal
    rc, out = run_stdin_error(MODEL, p, capsys, monkeypatch)
    assert rc == 2 and field in out["error"] and "Core" in out["error"]


@pytest.mark.parametrize("block, needle", [
    ({"type": "track_record", "rows": "abc"}, "rows"),
    ({"type": "forensics", "items": [1, 2]}, "items"),
    ({"type": "drivers", "segment": "HQ", "field": "ebit"}, "operating"),
])
def test_render_deep_rejects_malformed_block_payloads(block, needle, tmp_path, capsys) -> None:
    data = page_input()
    data["blocks"].append(block)
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"]


# --- fixes from the five-stock deep runs (MTG, ES, ADBE, INTU, GPN) ----------------------------------


BANK = {"name": "Bank", "kind": "residual_income", "book0": 1000.0, "roe": 0.12, "retention": 0.5,
        "cost_of_equity": 0.10, "terminal_growth": 0.03}


def test_model_residual_income_rows_carry_roe(capsys, monkeypatch) -> None:
    out = run_stdin(MODEL, base_input(segments=[BANK], claims={}), capsys, monkeypatch)
    row = out["scenarios"][0]["segments"][0]["years"][0]
    assert row["roe"] == 0.12 and row["book_start"] == 1000.0


def test_model_sensitivity_roe_shift_and_company_discount_shift(capsys, monkeypatch) -> None:
    p = base_input(segments=[*base_input()["segments"], BANK],
                   sensitivity={"a": {"segment": "Bank", "field": "roe_shift", "values": [-0.01, 0, 0.01]},
                                "b": {"segment": "*", "field": "discount_shift", "values": [0, 0.01]}})
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    grid = out["sensitivity"]["value_per_share"]
    assert grid[1][0] == out["scenarios"][0]["value_per_share"]
    assert grid[2][0] > grid[1][0] > grid[0][0]
    assert grid[1][1] < grid[1][0]


def test_model_roe_shift_rejected_on_operating_segment(capsys, monkeypatch) -> None:
    p = base_input(sensitivity={"a": {"segment": "Core", "field": "roe_shift", "values": [0]},
                                "b": {"segment": "*", "field": "discount_shift", "values": [0]}})
    rc, out = run_stdin_error(MODEL, p, capsys, monkeypatch)
    assert rc == 2 and "roe_shift" in out["error"]


def test_model_implied_shift_reproduces_the_price(capsys, monkeypatch) -> None:
    """What the price implies: the uniform margin (or ROE) shift on the first scenario that makes value equal price."""
    hi = base_input()
    hi["segments"][0]["margin"] = 0.16
    target = run_stdin(MODEL, hi, capsys, monkeypatch)["scenarios"][0]["value_per_share"]
    out = run_stdin(MODEL, base_input(price=target), capsys, monkeypatch)
    imp = out["implied"]
    assert imp["scenario"] == "Base" and imp["field"] == "margin_shift"
    assert imp["value"] == pytest.approx(0.01, abs=1e-4)


def test_model_implied_is_null_when_unreachable(capsys, monkeypatch) -> None:
    out = run_stdin(MODEL, base_input(price=1e9), capsys, monkeypatch)
    assert out["implied"]["value"] is None


def test_model_margin_flag_tolerates_rounding(capsys, monkeypatch) -> None:
    p = base_input(history={"Core": {"max_margin": 0.81}})
    p["segments"][0]["margin"] = 0.81
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    assert "MARGIN_ABOVE_HISTORY" not in {f["code"] for f in out["flags"]}


def test_model_scenario_can_override_cost_of_debt(capsys, monkeypatch) -> None:
    p = base_input(payout=0.0, scenarios=[{"name": "Cheap"}, {"name": "Dear", "cost_of_debt": 0.12}])
    a, b = run_stdin(MODEL, p, capsys, monkeypatch)["scenarios"]
    assert b["path"][-1]["net_debt"] > a["path"][-1]["net_debt"]


def test_render_deep_drivers_on_residual_income_segment(tmp_path, capsys) -> None:
    data = page_input()
    m = load_script(MODEL).run_model(base_input(segments=[BANK], claims={}))
    data["model"] = json.loads(json.dumps(m))
    data["returns"] = json.loads(json.dumps(load_script(RETURNS).run_returns(m["returns_input"])))
    data["blocks"] = [{"type": "drivers", "segment": "Bank", "field": "roe"}]
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 0, res
    data["blocks"] = [{"type": "drivers", "segment": "Bank", "field": "ebit"}]
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and "roe" in res["error"]


def test_render_deep_shows_what_the_price_implies() -> None:
    assert 'id="implied"' in load_script(RENDER).BODY


# --- ledger: effect on value ---------------------------------------------------------------------


@pytest.mark.parametrize("if_true, verdict, effect", [
    ("up", "supported", "helps"), ("up", "doubtful", "hurts"), ("up", "contradicted", "hurts"),
    ("down", "supported", "hurts"), ("down", "doubtful", "helps"), ("down", "contradicted", "helps"),
    ("up", "open", "unsettled"), ("down", "unknowable", "unsettled"), (None, "supported", None),
])
def test_ledger_effect_combines_direction_and_verdict(if_true, verdict, effect) -> None:
    e = {"id": "B1", "belief": "x", "verdict": verdict}
    if if_true:
        e["if_true"] = if_true
    assert load_script(RENDER).ledger_effect(e) == effect


def test_render_deep_counts_ledger_effects(tmp_path, capsys) -> None:
    data = page_input()
    data["ledger"][0].update(if_true="up", takeaway="Price increases are not sticking: volumes fell 6%.", effect_per_share=-2.35)
    data["ledger"].append({"id": "B2", "belief": "Losses keep rising", "verdict": "doubtful", "if_true": "down", "stakes": "high",
                           "takeaway": "Losses are not rising as feared.", "for": [], "against": []})
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 0, res
    assert res["ledger"] == {"helps": 1, "hurts": 1, "unsettled": 0, "unmarked": 0}


@pytest.mark.parametrize("patch, needle", [({"if_true": "sideways"}, "if_true"), ({"effect_per_share": "big"}, "effect_per_share")])
def test_render_deep_rejects_bad_ledger_effect_fields(patch, needle, tmp_path, capsys) -> None:
    data = page_input()
    data["ledger"][0].update(patch)
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"] and "B1" in res["error"]


def test_render_deep_ledger_headline_is_short(tmp_path, capsys) -> None:
    data = page_input()
    data["ledger"][0]["headline"] = "Price increases not sticking"
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 0, res
    data["ledger"][0]["headline"] = "Price increases are not sticking: volumes fell 6% as prices rose 4% across every region in the quarter"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and "headline" in res["error"] and "B1" in res["error"]


def test_render_deep_driver_charts_use_the_legend_not_end_labels() -> None:
    """Scenarios often share a path, so names at the line ends overprint; the legend and tooltip name them."""
    script = load_script(RENDER).SCRIPT
    drivers = script[script.index("b.type === 'drivers'"):script.index("b.type === 'ledger'")]
    assert "endLabels: false" in drivers


import shutil
import subprocess


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_render_deep_text_markdown_lists() -> None:
    """The text block's mini-markdown: a trailing blank line, wrapped lines and nested bullets stay lists."""
    script = load_script(RENDER).SCRIPT
    start, end = script.index("// md-start"), script.index("// md-end")
    js = ("const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');\n" + script[start:end] +
          "\nconst cases = JSON.parse(process.argv[1]); console.log(JSON.stringify(cases.map(md)));")
    cases = [
        "Intro line.\n\n- **A:** one\n- **B:** two\n",                # trailing blank line (the GPN page)
        "- first item\n  wraps here\n- second\n  - nested",          # continuation and a nested bullet
        "Lead text\n- item after text on the next line",              # text then bullets in one paragraph
        "<b>x</b> **bold**",
    ]
    out = json.loads(subprocess.run(["node", "-e", js, json.dumps(cases)], capture_output=True, text=True, check=True).stdout)
    assert out[0] == "<p>Intro line.</p><ul><li><b>A:</b> one</li><li><b>B:</b> two</li></ul>"
    assert out[1] == '<ul><li>first item wraps here</li><li>second</li><li class="sub">nested</li></ul>'
    assert out[2] == "<p>Lead text</p><ul><li>item after text on the next line</li></ul>"
    assert out[3] == "<p>&lt;b>x&lt;/b> <b>bold</b></p>"


# --- readable sensitivity grid and custom results -------------------------------------------------


def test_model_sensitivity_reports_the_modeled_point(capsys, monkeypatch) -> None:
    """The page outlines the cell that is the scenario as modeled, so the grid says where that is."""
    p = base_input(sensitivity={"a": {"segment": "Core", "field": "discount_premium", "values": [0, 0.01, 0.02]},
                                "b": {"segment": "Core", "field": "terminal_growth", "values": [0.01, 0.02, 0.03]}})
    p["segments"][0]["discount_premium"] = 0.01
    s = run_stdin(MODEL, p, capsys, monkeypatch)["sensitivity"]
    assert s["base"] == {"a": 0.01, "b": 0.02}
    assert s["discount_rate"] == {"a": 0.09, "b": 0.09}  # the rate before any premium, so the page can show the resulting rate
    p["sensitivity"] = {"a": {"segment": "Core", "field": "margin_shift", "values": [-0.01, 0]},
                        "b": {"segment": "*", "field": "discount_shift", "values": [0, 0.01]}}
    s = run_stdin(MODEL, p, capsys, monkeypatch)["sensitivity"]
    assert s["base"] == {"a": 0.0, "b": 0.0}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_render_deep_sensitivity_axis_labels() -> None:
    """Axes read as plain inputs with the value they produce, not model field names and shifts."""
    script = load_script(RENDER).SCRIPT
    start, end = script.index("// axis-start"), script.index("// axis-end")
    js = ("const F = {num: (v, d) => Number(v).toFixed(d)};\n" + script[start:end] +
          "\nconst cases = JSON.parse(process.argv[1]); console.log(JSON.stringify(cases.map(([ax, rate, v]) => { const a = axis(ax, rate); return [a.title, a.label(v)]; })));")
    cases = [
        [{"segment": "US MI", "field": "discount_premium"}, 0.0919, 0.01],
        [{"segment": "US MI", "field": "terminal_growth"}, None, 0.025],
        [{"segment": "Core", "field": "margin_shift"}, None, 0.015],
        [{"segment": "Core", "field": "margin_shift"}, None, 0],
        [{"segment": "*", "field": "discount_shift"}, 0.0919, 0.0081],
        [{"segment": "*", "field": "discount_shift"}, None, 0.0081],
        [{"segment": "Bank", "field": "roe_shift"}, None, -0.01],
        [{"segment": "Core", "field": "terminal_multiple"}, None, 12],
        [{"segment": "Core", "field": "sales_to_capital"}, None, 1.2],
        [{"segment": "Core", "field": "growth_shift"}, None, 0.01],
    ]
    ctx_cases = [[{"segment": "*", "field": "discount_shift"}, 0.0919, 0, {"equityOnly": True, "single": True}],
                 [{"segment": "*", "field": "discount_shift"}, 0.09, 0.01, {"single": True}]]
    js2 = js.replace("cases.map(([ax, rate, v]) => { const a = axis(ax, rate);", "cases.map(([ax, rate, v, ctx]) => { const a = axis(ax, rate, ctx);")
    assert json.loads(subprocess.run(["node", "-e", js2, json.dumps(ctx_cases)], capture_output=True, text=True, check=True).stdout) == [
        ["Cost of equity", "9.2%"], ["Discount rate", "10.0%"]]
    out = json.loads(subprocess.run(["node", "-e", js, json.dumps(cases)], capture_output=True, text=True, check=True).stdout)
    assert out == [
        ["Discount rate — US MI", "10.2%"],
        ["Long-run growth — US MI", "2.5%"],
        ["Operating margin — Core", "+1.5 pts"],
        ["Operating margin — Core", "as modeled"],
        ["Discount rate, every segment", "10.0%"],
        ["Discount rate, every segment", "+0.8 pts"],
        ["Return on equity — Bank", "−1.0 pts"],
        ["Exit multiple — Core", "12.0×"],
        ["Sales per $1 of capital — Core", "1.20"],
        ["Revenue growth a year — Core", "+1.0 pts"],
    ]


@pytest.mark.parametrize("result, ok", [
    ({"answer": "At an 8% cost of equity the central value is $31.96.", "table": {"columns": ["ROE", "8.0%"], "rows": [["−2 pts", "$25.06"]]}}, True),
    ({"answer": "x", "table": {"columns": ["ROE", "8.0%"], "rows": [["−2 pts"]]}}, False),
    ({"answer": "x", "table": {"columns": "ROE", "rows": []}}, False),
])
def test_render_deep_custom_table_shape(result, ok, tmp_path, capsys) -> None:
    data = page_input()
    next(b for b in data["blocks"] if b["type"] == "custom")["result"] = result
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert (rc == 0) if ok else (rc == 2 and "table" in res["error"])


# --- the central case up front -------------------------------------------------------------------


def _dom(data: dict, tmp_path) -> str:
    """The page after its script ran: Chrome's --dump-dom of the rendered file."""
    import subprocess

    import page_dom
    src, out = tmp_path / "page.json", tmp_path / "p.html"
    src.write_text(json.dumps(data))
    run = subprocess.run([sys.executable, str(PLUGIN_ROOT / "skills" / RENDER), "--in", str(src), "--out", str(out)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout
    doc = tmp_path / "doc.html"
    doc.write_text(f'<!doctype html><html><head><meta charset="utf-8"></head><body>{out.read_text()}</body></html>')
    return subprocess.run([page_dom.CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=3000",
                           "--dump-dom", doc.as_uri()], capture_output=True, text=True, timeout=90).stdout


def _lowest_first(data: dict) -> dict:
    """Central (scenarios[0]) is the lowest-value scenario, so a value sort alone would put it last."""
    data["model"]["scenarios"].sort(key=lambda s: s["value_per_share"])
    return data


def test_render_deep_headline_markup_and_docstring() -> None:
    mod = load_script(RENDER)
    assert 'id="headline"' in mod.BODY
    for label in ("Price", "Central value", "Central return / yr", "Worst case", "Range"):
        assert f"tile('{label}'" in mod.SCRIPT
    assert "not averaged" in mod.SCRIPT and "pin: r => r.central" in mod.SCRIPT
    assert "central case" in mod.__doc__ and "nothing is averaged" in mod.__doc__


@requires_chrome
def test_render_deep_headline_tiles_and_pinned_central(tmp_path) -> None:
    import re
    data = _lowest_first(page_input())
    central = data["model"]["scenarios"][0]
    dom = _dom(data, tmp_path)
    text = re.search(r'id="headline".*?id="sc-card"', dom, re.S).group(0)
    for label in ("Price", "Central value", "Central return / yr", "Worst case", "Range"):
        assert f'<div class="k">{label}</div>' in text
    assert f"${central['value_per_share']:,.2f}" in text and "scenarios not averaged" in text
    rows = re.findall(r"<tr>(.*?)</tr>", re.search(r'id="sc".*?</table>', dom, re.S).group(0), re.S)[1:]
    assert central["name"] in rows[0] and "Central" in rows[0] and all("Central<" not in r for r in rows[1:])
    assert "not averaged" in re.search(r'id="intro".*?</div>', dom, re.S).group(0)


@requires_chrome
def test_render_deep_central_without_returns_row_shows_dash(tmp_path) -> None:
    import re
    data = page_input()
    data["returns"]["scenarios"] = [s for s in data["returns"]["scenarios"] if s["name"] != data["model"]["scenarios"][0]["name"]]
    dom = _dom(data, tmp_path)
    tile = re.search(r'Central return / yr</div><div class="v">(.*?)</div>', dom).group(1)
    assert tile == "—"
    data["returns"] = None
    assert 'Central return / yr</div><div class="v">—</div>' in _dom(data, tmp_path)
