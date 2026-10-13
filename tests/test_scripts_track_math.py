"""track_math.py: which valuation scenario the reported quarters are tracking (deep), and how a light
pick's growth and margin moved since it was picked (light). Fixtures are invented."""

from __future__ import annotations

import io
import json
import sys

import pytest
from scripts_util import load_script

TM = load_script("stock-screener/scripts/track_math.py")
MODEL = load_script("valuation/scripts/model.py")
RETURNS = load_script("valuation/scripts/returns.py")

TAX = 0.25


def model_input(**over) -> dict:
    p = {
        "symbol": "ACME", "price": 20.0, "shares_outstanding": 100.0, "years": 10, "horizon": 5,
        "base_discount_rate": 0.09, "tax_rate": TAX, "cost_of_debt": 0.05,
        "claims": {"debt": 300.0, "cash": 100.0}, "payout": 0.5,
        "segments": [
            {"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.05, "margin": 0.15,
             "sales_to_capital": 2.0, "terminal": {"method": "gordon", "growth": 0.02}},
            {"name": "Corporate", "kind": "cost", "cost0": 15.0, "growth": 0.0},
        ],
        "scenarios": [
            {"name": "Steady", "summary": "Growth and margin hold.", "must_be_true": ["Margin holds at 15%"]},
            {"name": "Slump", "summary": "Volume falls and margin compresses.", "must_be_true": ["Orders fall"],
             "overrides": {"Core": {"growth": -0.05, "margin": 0.10}}},
            {"name": "Boom", "summary": "Share gains.", "must_be_true": ["New plant ramps"],
             "overrides": {"Core": {"growth": 0.12, "margin": 0.18}}},
        ],
    }
    p.update(over)
    return p


def model_output(inp: dict | None = None) -> dict:
    return MODEL.run_model(inp or model_input())


def path(out: dict, scenario: str, t: int) -> tuple[float, float]:
    """(revenue, operating income) for year t of a scenario, cost grossed up for tax."""
    sc = next(s for s in out["scenarios"] if s["name"] == scenario)
    rev = sum(sg["years"][t - 1]["revenue"] for sg in sc["segments"] if sg["kind"] == "operating")
    ebit = sum(sg["years"][t - 1]["ebit"] for sg in sc["segments"] if sg["kind"] == "operating")
    ebit -= sum(sg["years"][t - 1]["cost"] for sg in sc["segments"] if sg["kind"] == "cost") / (1 - TAX)
    return rev, ebit


LEDGER = [
    {"id": "L1", "belief": "Pricing power holds", "stakes": "high", "verdict": "supported", "if_true": "up", "headline": "Pricing holds"},
    {"id": "L2", "belief": "New plant on time", "stakes": "medium", "verdict": "open", "if_true": "up", "headline": "Plant timing"},
    {"id": "L3", "belief": "Minor FX", "stakes": "low", "verdict": "open", "if_true": "down", "headline": "FX"},
    {"id": "L4", "belief": "Settled tax case", "stakes": "medium", "verdict": "supported", "if_true": "up", "headline": "Tax"},
]


def deep(actual_rev: float | None = None, actual_oi: float | None = None, *, scenario: str = "Steady", t: int = 1,
         end: str = "2026-12-31", with_input: bool = True, price: float = 20.0, as_of: str = "2027-02-15", **over) -> dict:
    out = model_output()
    if actual_rev is None:
        actual_rev, actual_oi = path(out, scenario, t)
    params = {
        "mode": "deep", "as_of": as_of, "price": price,
        "baseline": {"as_of": "2026-02-10", "model": out, "ledger": LEDGER, **({"model_input": model_input()} if with_input else {})},
        "actuals": {"base": {"period_end": "2025-12-31", "revenue": 1000.0, "operating_income": 130.0},
                    "ttm": {"period_end": end, "revenue": actual_rev, "operating_income": actual_oi}},
    }
    params.update(over)
    return TM.run_track(params)


def codes(res: dict) -> set[str]:
    return {f["code"] for f in res["flags"]} | {r["code"] for r in res.get("reasons", [])}


# --- alignment -----------------------------------------------------------------------------


@pytest.mark.parametrize("f, want", [(1.0, {1: 1.0}), (0.5, {0: 0.5, 1: 0.5}), (1.25, {1: 0.75, 2: 0.25}), (0.0, {0: 1.0})])
def test_window_weights_split_the_ttm_window_across_fiscal_years(f, want) -> None:
    got = TM.window_weights(f)
    assert got.keys() == want.keys()
    for k, v in want.items():
        assert got[k] == pytest.approx(v)


def test_expected_ttm_blends_the_base_year_actual_with_the_path() -> None:
    assert TM.expected_ttm([110.0, 121.0], 100.0, 0.5) == pytest.approx(105.0)
    assert TM.expected_ttm([110.0, 121.0], 100.0, 1.5) == pytest.approx(115.5)


# --- deep status ---------------------------------------------------------------------------


def test_actuals_on_the_central_path_are_on_track() -> None:
    res = deep()
    assert res["status"] == "on_track" and res["nearest"] == "Steady" and res["central"] == "Steady"
    assert res["rerun_deep"] is False
    assert res["elapsed_years"] == pytest.approx(1.0, abs=0.01)
    assert res["metrics"]["revenue_growth"]["position"] == "inside"
    assert res["metrics"]["operating_margin"]["actual"] == pytest.approx(res["metrics"]["operating_margin"]["expected"]["Steady"], abs=1e-4)


def test_actuals_on_an_alternative_path_are_shifting() -> None:
    res = deep(scenario="Boom")
    assert res["status"] == "shifting" and res["nearest"] == "Boom" and res["rerun_deep"] is False


def test_actuals_below_every_scenario_are_outside_and_ask_for_a_rerun() -> None:
    rev, _ = path(model_output(), "Slump", 1)
    res = deep(rev * 0.9, rev * 0.9 * 0.02)
    assert res["status"] == "outside" and res["rerun_deep"] is True
    assert res["metrics"]["revenue_growth"]["position"] == "below"
    assert "OUTSIDE_SCENARIOS" in codes(res)


def test_actuals_above_every_scenario_are_outside_too() -> None:
    rev, _ = path(model_output(), "Boom", 1)
    res = deep(rev * 1.1, rev * 1.1 * 0.25)
    assert res["status"] == "outside" and res["metrics"]["operating_margin"]["position"] == "above"


def test_no_quarter_since_the_base_year_is_no_new_data_not_outside() -> None:
    res = deep(500.0, 1.0, end="2026-01-31")  # wildly off, but only a month past the base year
    assert res["status"] == "no_new_data" and res["rerun_deep"] is False


def test_cost_segments_come_off_expected_operating_income_grossed_up_for_tax() -> None:
    res = deep()
    rev, ebit = path(model_output(), "Steady", 1)
    assert res["metrics"]["operating_margin"]["expected"]["Steady"] == pytest.approx(ebit / rev, abs=1e-4)


def test_scale_from_model_input_and_base_mismatch() -> None:
    out = model_output()
    rev, oi = path(out, "Steady", 1)
    res = deep(rev * 1.08, oi * 1.08, actuals={"base": {"period_end": "2025-12-31", "revenue": 1080.0, "operating_income": 140.4},
                                                "ttm": {"period_end": "2026-12-31", "revenue": rev * 1.08, "operating_income": oi * 1.08}})
    assert res["status"] == "on_track"  # segment sums scaled to the reported base revenue
    assert "BASE_MISMATCH" in codes(res)


def test_without_model_input_the_base_is_approximate() -> None:
    assert "APPROX_BASE" in codes(deep(with_input=False))


def test_revenue0_is_backed_out_of_the_path_when_no_model_input() -> None:
    out = model_output()
    core = out["scenarios"][0]["segments"][0]
    assert TM.revenue0_from_years(core["years"]) == pytest.approx(1000.0, rel=1e-3)
    flat = [{"t": 1, "revenue": 500.0, "reinvestment": 0.0}, {"t": 2, "revenue": 500.0, "reinvestment": 0.0}]
    assert TM.revenue0_from_years(flat) == pytest.approx(500.0)


def forward(actual_rev: float, actual_oi: float, **over) -> dict:
    """A model whose revenue0 (1100) is an estimate of the fiscal year in progress (ending 2026-12-31);
    the last reported year (2025) had revenue 1000."""
    inp = model_input()
    inp["segments"][0]["revenue0"] = 1100.0
    out = MODEL.run_model(inp)
    params = {
        "mode": "deep", "as_of": "2026-11-20", "price": 20.0,
        "baseline": {"as_of": "2026-03-10", "model": out, "model_input": inp},
        "actuals": {"annual": [{"period_end": "2025-12-31", "first_filed": "2026-02-20", "revenue": 1000.0, "operating_income": 130.0}],
                    "ttm": {"period_end": "2026-09-30", "revenue": actual_rev, "operating_income": actual_oi}},
    }
    params.update(over)
    return TM.run_track(params)


def test_a_model_starting_from_the_year_in_progress_compares_against_its_estimate() -> None:
    res = forward(0.25 * 1000 + 0.75 * 1100, 0.25 * 130 + 0.75 * 1100 * 0.13)  # year in progress at the last reported margin
    assert res["status"] == "on_track" and "FORWARD_BASE" in codes(res)
    assert res["elapsed_years"] == pytest.approx(-0.25, abs=0.01)


def test_running_behind_the_in_progress_estimate_is_outside() -> None:
    res = forward(980.0, 120.0)
    assert res["status"] == "outside" and res["metrics"]["revenue_growth"]["position"] == "below"


def test_explicit_base_period_end_wins() -> None:
    out = model_output()
    rev, oi = path(out, "Steady", 1)
    res = deep(rev, oi, baseline={"as_of": "2026-02-10", "model": out, "model_input": model_input(), "base_period_end": "2025-12-31"})
    assert res["status"] == "on_track" and "FORWARD_BASE" not in codes(res)


def test_excluded_segments_leave_the_comparison() -> None:
    inp = model_input()
    inp["segments"].append({"name": "Pending deal", "kind": "operating", "revenue0": 300.0, "growth": 0.04, "margin": 0.05,
                            "sales_to_capital": 2.0, "terminal": {"method": "gordon", "growth": 0.02}})
    out = MODEL.run_model(inp)
    rev, oi = path(model_output(), "Steady", 1)
    params = {"mode": "deep", "as_of": "2027-02-15", "price": 20.0, "baseline": {"as_of": "2026-02-10", "model": out, "model_input": inp},
              "actuals": {"base": {"period_end": "2025-12-31", "revenue": 1000.0, "operating_income": 130.0},
                          "ttm": {"period_end": "2026-12-31", "revenue": rev, "operating_income": oi}},
              "exclude_segments": ["Pending deal"]}
    res = TM.run_track(params)
    assert res["status"] == "on_track" and "SEGMENTS_EXCLUDED" in codes(res)
    params.pop("exclude_segments")
    assert TM.run_track(params)["status"] != "on_track"


def test_nothing_reported_since_the_valuation_is_no_new_data() -> None:
    res = deep(actuals={"base": {"period_end": "2025-12-31", "revenue": 1000.0, "operating_income": 130.0},
                        "ttm": {"period_end": "2026-12-31", "revenue": 500.0, "operating_income": 1.0},
                        "known_at_baseline": "2026-12-31"})
    assert res["status"] == "no_new_data"


def test_a_small_definitional_margin_gap_is_not_outside() -> None:
    rev, oi = path(model_output(), "Boom", 1)  # Boom carries the highest margin
    res = deep(rev, oi + 0.008 * rev)  # 0.8 points above every scenario's margin, inside the 1-point band
    assert res["metrics"]["operating_margin"]["position"] == "inside" and res["status"] != "outside"


@pytest.mark.parametrize("with_input", [True, False])
def test_a_model_in_millions_against_edgar_dollars(with_input) -> None:
    rev, oi = path(model_output(), "Steady", 1)
    res = deep(rev * 1e6, oi * 1e6, with_input=with_input,
               actuals={"base": {"period_end": "2025-12-31", "revenue": 1000e6, "operating_income": 130e6},
                        "ttm": {"period_end": "2026-12-31", "revenue": rev * 1e6, "operating_income": oi * 1e6}})
    assert res["status"] == "on_track" and res["nearest"] == "Steady"
    assert "BASE_MISMATCH" not in codes(res)


def test_missing_operating_income_compares_revenue_only() -> None:
    rev, _ = path(model_output(), "Steady", 1)
    res = deep(rev, None)
    assert "NO_OPERATING_INCOME" in codes(res) and "operating_margin" not in res["metrics"]
    assert res["status"] == "on_track"


def test_stale_baseline_asks_for_a_rerun() -> None:
    res = deep(as_of="2027-06-01", end="2027-03-31")
    assert res["rerun_deep"] is True and "STALE_BASELINE" in codes(res)


def test_contradicted_high_stakes_belief_asks_for_a_rerun() -> None:
    ev = [{"belief": "L1", "finding": "contradicts", "claim": "Price cuts announced", "source": "Q3 10-Q MD&A", "date": "2027-02-01"}]
    res = deep(evidence=ev)
    assert res["status"] == "on_track" and res["rerun_deep"] is True and "HIGH_STAKES_CONTRADICTED" in codes(res)


def test_contradicted_central_condition_asks_for_a_rerun() -> None:
    ev = [{"belief": "must:Steady:0", "finding": "contradicts", "claim": "Margin fell to 12%", "source": "Q3 8-K", "date": "2027-02-01"}]
    assert "CENTRAL_CONDITION_CONTRADICTED" in codes(deep(evidence=ev))


def test_supporting_evidence_changes_nothing() -> None:
    ev = [{"belief": "L2", "finding": "supports", "claim": "Plant opened", "source": "8-K", "date": "2027-01-10"}]
    res = deep(evidence=ev)
    assert res["rerun_deep"] is False and res["evidence"][0]["belief"] == "L2"


def test_undated_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="date"):
        deep(evidence=[{"belief": "L1", "finding": "contradicts", "claim": "x", "source": "y"}])


def test_watch_list_holds_conditions_and_unsettled_beliefs() -> None:
    res = deep(scenario="Boom")
    ids = [w["id"] for w in res["watch"]]
    assert "must:Steady:0" in ids and "must:Boom:0" in ids and "must:Slump:0" not in ids
    assert "L1" in ids and "L2" in ids and "L3" not in ids and "L4" not in ids


# --- price ---------------------------------------------------------------------------------


def test_returns_at_the_new_price_match_returns_py() -> None:
    out = model_output()
    res = deep(price=15.0)
    want = RETURNS.run_returns({**out["returns_input"], "price": 15.0})
    got = {s["name"]: s["irr"] for s in res["scenarios"]}
    assert got == {s["name"]: s["irr"] for s in want["scenarios"]}
    assert res["price"]["price"] == 15.0 and res["price"]["position"] in ("below_all", "inside", "above_all")


def test_price_position_against_scenario_values() -> None:
    out = model_output()
    lo = min(s["value_per_share"] for s in out["scenarios"])
    assert deep(price=lo * 0.5)["price"]["position"] == "below_all"


# --- residual income -----------------------------------------------------------------------


def ri_input() -> dict:
    return {
        "symbol": "BANK", "price": 50.0, "shares_outstanding": 10.0, "years": 10, "horizon": 5,
        "base_discount_rate": 0.10, "tax_rate": 0.21, "claims": {},
        "segments": [{"name": "Bank", "kind": "residual_income", "book0": 400.0, "roe": 0.14, "retention": 0.6, "cost_of_equity": 0.10}],
        "scenarios": [{"name": "Steady", "summary": "ROE holds.", "must_be_true": ["ROE 14%"]},
                      {"name": "Squeeze", "summary": "ROE falls.", "must_be_true": ["ROE 9%"], "overrides": {"Bank": {"roe": 0.09}}}],
    }


def test_residual_income_models_compare_on_roe() -> None:
    out = MODEL.run_model(ri_input())
    res = TM.run_track({
        "mode": "deep", "as_of": "2027-02-15", "price": 50.0,
        "baseline": {"as_of": "2026-02-10", "model": out},
        "actuals": {"base": {"period_end": "2025-12-31", "revenue": 300.0, "roe": 0.14},
                    "ttm": {"period_end": "2026-12-31", "revenue": 310.0, "net_income": 36.0, "equity_start": 400.0}},
    })
    assert set(res["metrics"]) == {"roe"}
    assert res["nearest"] == "Squeeze" and res["status"] == "shifting"


def test_roe_on_another_definition_is_offset_by_the_base_year_gap() -> None:
    """An insurer modelled on ex-AOCI ROE reports GAAP ROE several points higher: not a miss."""
    out = MODEL.run_model(ri_input())
    res = TM.run_track({
        "mode": "deep", "as_of": "2027-02-15", "price": 50.0,
        "baseline": {"as_of": "2026-02-10", "model": out},
        "actuals": {"base": {"period_end": "2025-12-31", "revenue": 300.0, "roe": 0.20},
                    "ttm": {"period_end": "2026-12-31", "revenue": 310.0, "net_income": 80.0, "equity_start": 400.0}},
    })
    assert res["status"] == "on_track" and res["nearest"] == "Steady"
    assert "ROE_DEFINITION" in codes(res)


def test_missing_model_is_bad_input(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"mode": "deep", "baseline": {}, "actuals": {}, "price": 1})))
    with pytest.raises(SystemExit) as exc:
        TM.main()
    assert exc.value.code == 2 and "model" in json.loads(capsys.readouterr().out)["error"]


# --- light ---------------------------------------------------------------------------------


def light(now_growth: float = 0.10, now_margin: float | None = 0.20, *, end: str = "2026-12-31", price: float = 50.0) -> dict:
    return TM.run_track({
        "mode": "light", "as_of": "2027-02-15", "price": price,
        "baseline": {"fair_values": {"bear": 40.0, "base": 55.0, "bull": 70.0},
                     "metrics_at_pick": {"period_end": "2026-09-30", "revenue_growth": 0.11, "operating_margin": 0.205}},
        "actuals": {"period_end": end, "revenue_growth": now_growth, "operating_margin": now_margin},
    })


def test_light_on_track() -> None:
    res = light()
    assert res["status"] == "on_track" and res["deep_review"] is False
    assert res["metrics"]["revenue_growth"]["change"] == pytest.approx(-0.01)


@pytest.mark.parametrize("g, m, code", [(0.05, 0.20, "GROWTH_FELL"), (0.10, 0.18, "MARGIN_FELL")])
def test_light_weakening(g, m, code) -> None:
    res = light(g, m)
    assert res["status"] == "weakening" and res["deep_review"] is True and code in codes(res)


def test_light_same_period_is_no_new_data() -> None:
    assert light(0.01, 0.05, end="2026-09-30")["status"] == "no_new_data"


@pytest.mark.parametrize("p, pos", [(30.0, "below_bear"), (45.0, "bear_base"), (60.0, "base_bull"), (80.0, "above_bull")])
def test_light_price_position(p, pos) -> None:
    assert light(price=p)["price"]["position"] == pos


def test_light_without_margin_compares_growth_only() -> None:
    res = light(0.10, None)
    assert "operating_margin" not in res["metrics"] and "NO_OPERATING_INCOME" in codes(res)


def test_a_model_starting_from_ttm_anchors_on_that_ttm() -> None:
    """revenue0 is the TTM to 2026-06-30 (1000); the last fiscal year (2025) had 877."""
    out = model_output()
    rev, oi = path(out, "Steady", 1)
    res = TM.run_track({
        "mode": "deep", "as_of": "2027-08-20", "price": 20.0,
        "baseline": {"as_of": "2026-08-20", "model": out, "model_input": model_input()},
        "actuals": {"annual": [{"period_end": "2025-12-31", "first_filed": "2026-02-20", "revenue": 877.0, "operating_income": 110.0}],
                    "ttm_at_baseline": {"period_end": "2026-06-30", "revenue": 1000.0, "operating_income": 130.0},
                    "known_at_baseline": "2026-06-30",
                    "ttm": {"period_end": "2027-06-30", "revenue": rev, "operating_income": oi}},
    })
    assert res["status"] == "on_track" and "FORWARD_BASE" not in codes(res) and "TTM_BASE" in codes(res)
    assert res["elapsed_years"] == pytest.approx(1.0, abs=0.01)


def test_forward_base_flags_that_scenarios_share_the_year_in_progress() -> None:
    res = forward(0.25 * 1000 + 0.75 * 1100, 0.25 * 130 + 0.75 * 1100 * 0.13)
    assert "SCENARIOS_SHARE_YEAR_0" in codes(res) and res["nearest"] == res["central"]
    # the year in progress is held at the last reported margin (13%), not the central year-1 margin
    assert res["status"] == "on_track"


def test_forward_base_skips_segment_growth() -> None:
    res = forward(1075.0, 140.0, actuals={
        "annual": [{"period_end": "2025-12-31", "first_filed": "2026-02-20", "revenue": 1000.0, "operating_income": 130.0}],
        "ttm": {"period_end": "2026-09-30", "revenue": 1075.0, "operating_income": 140.0},
        "segments": {"Core": {"revenue": 1075.0}}})
    assert "Core:revenue_growth" not in res["metrics"] and "SEGMENT_GROWTH_SKIPPED" in codes(res)


def test_missing_revenue0_in_model_input_falls_back_to_the_path() -> None:
    inp = model_input()
    del inp["segments"][0]["revenue0"]
    out = model_output()
    rev, oi = path(out, "Steady", 1)
    res = deep(rev, oi, baseline={"as_of": "2026-02-10", "model": out, "model_input": inp})
    assert res["status"] == "on_track" and "APPROX_BASE" in codes(res)


def test_excluding_every_operating_segment_is_bad_input() -> None:
    with pytest.raises(ValueError):
        deep(exclude_segments=["Core"])


def test_segment_actuals_for_an_excluded_segment_say_excluded() -> None:
    inp = model_input()
    inp["segments"].append({"name": "Pending deal", "kind": "operating", "revenue0": 300.0, "growth": 0.04, "margin": 0.05,
                            "sales_to_capital": 2.0, "terminal": {"method": "gordon", "growth": 0.02}})
    out = MODEL.run_model(inp)
    rev, oi = path(model_output(), "Steady", 1)
    res = TM.run_track({"mode": "deep", "as_of": "2027-02-15", "price": 20.0, "baseline": {"as_of": "2026-02-10", "model": out, "model_input": inp},
                        "actuals": {"base": {"period_end": "2025-12-31", "revenue": 1000.0, "operating_income": 130.0},
                                    "ttm": {"period_end": "2026-12-31", "revenue": rev, "operating_income": oi},
                                    "segments": {"Pending deal": {"revenue": 10.0}}},
                        "exclude_segments": ["Pending deal"]})
    msgs = [f["message"] for f in res["flags"] if "Pending deal" in f["message"]]
    assert not any("not in the model" in m for m in msgs) and "SEGMENT_EXCLUDED_ACTUALS" in codes(res)


# --- price levels --------------------------------------------------------------------------


def test_hurdle_price_is_where_the_central_return_equals_the_hurdle() -> None:
    out = model_output()
    lv = TM.price_levels(out)
    got = RETURNS.run_returns({**out["returns_input"], "price": lv["hurdle"]})["scenarios"][0]["irr"]
    assert got == pytest.approx(out["returns_input"]["hurdle"], abs=1e-4)
    vals = [s["value_per_share"] for s in out["scenarios"]]
    assert lv["central"] == vals[0] and lv["best"] == max(vals) and lv["worst"] == min(vals)


@pytest.mark.parametrize("price, want", [(0.5, "below_worst"), ("mid", "normal"), ("hurdle", "hurdle"), ("central", "above_central"), (1e6, "above_all")])
def test_price_level_names_the_highest_level_crossed(price, want) -> None:
    lv = {"worst": 10.0, "hurdle": 18.0, "central": 20.0, "best": 30.0}
    p = {"mid": 15.0, "hurdle": 19.0, "central": 25.0}.get(price, price)
    assert TM.price_level(p, lv) == want


def test_hurdle_above_central_still_ranks_by_condition() -> None:
    lv = {"worst": 10.0, "hurdle": 22.0, "central": 20.0, "best": 30.0}
    assert TM.price_level(21.0, lv) == "above_central"
    assert TM.price_level(23.0, lv) == "above_central"  # past both; above_central outranks hurdle


def test_deep_result_carries_the_price_level() -> None:
    out = model_output()
    best = max(s["value_per_share"] for s in out["scenarios"])
    res = deep(price=best * 1.1)
    assert res["price"]["level"] == "above_all" and res["price"]["levels"]["best"] == best


def test_light_result_carries_the_price_level() -> None:
    assert light(price=75.0)["price"]["level"] == "above_all"
    assert light(price=60.0)["price"]["level"] == "above_central"
    assert light(price=35.0)["price"]["level"] == "below_worst"
