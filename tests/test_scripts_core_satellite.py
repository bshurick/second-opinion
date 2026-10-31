from __future__ import annotations

import json
from datetime import date

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import PLUGIN_ROOT, load_script, run_json
from second_opinion import client, market, profile
from second_opinion.errors import InvalidInput
from second_opinion.brokers import router

W = "core-satellite/scripts/weights.py"


def test_n_eff_and_tracking_error() -> None:
    w = load_script(W)
    assert w.n_eff({f"S{i}": 1.0 for i in range(15)}) == pytest.approx(15.0)
    assert w.n_eff({}) == 0
    assert w.tracking_error(0.20, 15) == pytest.approx(0.0155, abs=1e-4)
    assert w.tracking_error(0.20, 0) == 0


def test_proposed_size_caps_by_ceiling_te_and_sector() -> None:
    w = load_script(W)
    assert w.proposed_size(0.20, 25, False) == 0.20
    assert w.proposed_size(0.20, 5, False) == 0.1118
    assert w.proposed_size(0.20, 25, True) == 0.15


def test_confidence_halves_every_half_life_and_zero_when_due() -> None:
    w = load_script(W)
    assert w.confidence(182, False) == pytest.approx(0.5)
    assert w.confidence(10, True) == 0.0


def test_size_split_pro_rata_and_equal() -> None:
    w = load_script(W)
    assert w.size_split({"A": 300, "B": 100}, 400) == {"A": 300.0, "B": 100.0}
    assert w.size_split({"A": 0, "B": 0}, 100) == {"A": 50.0, "B": 50.0}
    assert w.median_pick_value({"A": 1, "B": 3, "C": 10}) == 3


PICKS = [
    {"symbol": "A", "value": 1000, "price": 50, "central_value": 80, "expected_return": 0.20, "eligible": True, "confidence": 1.0},
    {"symbol": "B", "value": 1000, "price": 50, "central_value": 60, "expected_return": 0.09, "eligible": True, "confidence": 1.0},
    {"symbol": "C", "value": 1000, "price": 50, "central_value": 40, "expected_return": 0.02, "eligible": True, "confidence": 1.0},
]


def test_strategy_weights() -> None:
    w = load_script(W)
    rows = [dict(PICKS[0]), dict(PICKS[1], value=3000)]
    assert w.strategy_weights(rows, "equal") == {"A": 1.0, "B": 1.0}
    assert w.strategy_weights(rows, "size") == {"A": 1000.0, "B": 3000.0}
    assert w.strategy_weights(rows, "market_cap", {"A": 3e11, "B": 1e11}) == {"A": 3e11, "B": 1e11}
    assert w.strategy_weights(rows, "valuation")["A"] == pytest.approx(w.tilt_factor(PICKS[0]))
    assert w.strategy_weights([dict(PICKS[0], eligible=False)], "valuation") == {"A": 1.0}   # neutral


def test_split_capped() -> None:
    w = load_script(W)
    assert w.split_capped({"A": 1.0, "B": 3.0}, 400.0) == {"A": 100.0, "B": 300.0}
    assert w.split_capped({"A": 1.0, "B": 1.0}, 1000.0, {"A": 240.0, "B": 9999.0}) == pytest.approx({"A": 240.0, "B": 760.0})
    out = w.split_capped({"A": 1.0, "B": 1.0}, 1000.0, {"A": 100.0, "B": 200.0})
    assert out == pytest.approx({"A": 100.0, "B": 200.0})                                   # the rest is left out
    assert w.split_capped({"A": 0.0, "B": 0.0}, 100.0) == {"A": 50.0, "B": 50.0}


def test_default_weighting_is_equal_and_all_strategies_accepted() -> None:
    sl = load_script(SL)
    assert sl.run_sleeves(_params(settings={}))["settings_used"]["weighting"] == "equal"
    for name in ("equal", "market_cap", "valuation", "size"):
        assert sl.run_sleeves(_params(weighting=name))["settings_used"]["weighting"] == name
    with pytest.raises(ValueError, match="equal, market_cap, valuation or size"):
        sl.run_sleeves(_params(weighting="momentum"))


S = "core-satellite/scripts/settings.py"


def test_decide_records_and_validates(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = run_json(load_script(S), ["decide", "ceiling", "0.15"], capsys)
    assert rc == 0 and out["ceiling"] == 0.15 and out["decisions"][-1]["key"] == "ceiling"
    rc, out = run_json(load_script(S), ["decide", "weighting", "kelly"], capsys)
    assert rc == 2 and "size" in out["error"]
    assert "equal, market_cap, valuation or size" in out["error"]
    for name in ("market_cap", "equal"):
        rc, out = run_json(load_script(S), ["decide", "weighting", name], capsys)
        assert rc == 0 and out["weighting"] == name
    rc, out = run_json(load_script(S), ["decide", "weighting", "momentum"], capsys)
    assert rc == 2 and "equal, market_cap, valuation or size" in out["error"]


def test_summary_prints_due_plan_step(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    s = load_script(S)
    (tmp_path / "core-satellite.json").write_text(json.dumps({"plan": {"target": 0.18, "by_date": "2027-04-30", "cadence": "monthly", "status": "active", "next_due": "2026-10-28"}}))
    assert s.summary_lines(date(2026, 10, 29)) == ["Core/satellite: plan step due since 2026-10-28 (target 18.0% by 2027-04-30); ask Claude to run it."]
    assert s.summary_lines(date(2026, 10, 27)) == []


def test_plan_advance_moves_next_due_and_finishes(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    s = load_script(S)
    rc, out = run_json(s, ["plan-set", "--target", "0.18", "--by", "2026-12-15", "--cadence", "monthly", "--funding", "cash", "--today", "2026-10-29"], capsys)
    assert rc == 0 and out["plan"]["next_due"] == "2026-10-29" and out["plan"]["status"] == "active"
    rc, out = run_json(s, ["plan-advance", "--today", "2026-10-29"], capsys)
    assert out["plan"]["next_due"] == "2026-11-29" and out["plan"]["status"] == "active"
    rc, out = run_json(s, ["plan-advance", "--today", "2026-11-29"], capsys)
    assert out["plan"]["next_due"] == "2026-12-29" and out["plan"]["status"] == "done"


def test_show_fills_nulls_and_corrupt_summary_is_silent(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    s = load_script(S)
    rc, out = run_json(s, ["show"], capsys)
    assert rc == 0 and out["ceiling"] is None and out["plan"] is None and out["decisions"] == []
    rc, out = run_json(s, ["record-increase", "--amount", "500", "--before", "0.1", "--after", "0.12", "--funded-from", "cash", "--date", "2026-10-29"], capsys)
    assert out["increases"][0]["amount"] == 500
    (tmp_path / "core-satellite.json").write_text("{bad")
    assert s.main(["summary"]) == 0 and capsys.readouterr().out == ""


@pytest.mark.parametrize("status, cmd, ok", [
    ("paused", "plan-resume", True), ("active", "plan-resume", False), ("done", "plan-resume", False),
    ("cancelled", "plan-resume", False), ("active", "plan-advance", True), ("paused", "plan-advance", False),
    ("done", "plan-advance", False), ("cancelled", "plan-advance", False),
])
def test_plan_resume_and_advance_need_the_right_status(tmp_path, monkeypatch, capsys, status, cmd, ok) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    plan = {"target": 0.18, "by_date": "2027-04-30", "cadence": "monthly", "funding": "cash", "status": status, "next_due": "2026-10-29"}
    (tmp_path / "core-satellite.json").write_text(json.dumps({"plan": plan}))
    rc, out = run_json(load_script(S), [cmd, "--today", "2026-10-29"], capsys)
    if ok:
        assert rc == 0, out
    else:
        assert rc == 2 and status in out["error"]
        assert json.loads((tmp_path / "core-satellite.json").read_text())["plan"] == plan


def test_plan_set_rejects_end_date_before_today(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    s = load_script(S)
    rc, out = run_json(s, ["plan-set", "--target", "0.18", "--by", "2026-10-28", "--cadence", "monthly", "--funding", "cash", "--today", "2026-10-29"], capsys)
    assert rc == 2 and "--by" in out["error"]
    rc, out = run_json(s, ["plan-set", "--target", "0.18", "--by", "2026-10-29", "--cadence", "monthly", "--funding", "cash", "--today", "2026-10-29"], capsys)
    assert rc == 0, out


SL = "core-satellite/scripts/sleeves.py"


def _pos(symbol: str, units: float, account: str, bucket: str) -> dict:
    price = 100.0 if symbol in ("VTI", "VXUS") else 50.0
    return {"symbol": symbol, "units": units, "price": price, "account": account, "bucket": bucket}


def _params(**over) -> dict:
    p = {
        "mode": "mix",
        "positions": [
            _pos("VTI", 100, "t1", "core"),
            _pos("AAA", 40, "t1", "satellite"),
            _pos("BBB", 20, "t1", "satellite"),
            _pos("AMZN", 80, "t1", "employer"),
            _pos("VXUS", 50, "t2", "core"),
            _pos("BBB", 20, "t2", "satellite"),
            _pos("VTI", 200, "r1", "core"),
            _pos("CCC", 10, "r1", "satellite"),
        ],
        "accounts": {"t1": {"role": "trading"}, "t2": {"role": "trading"}, "r1": {"role": "retirement"}},
        "cash_by_account": {"t1": 3000.0, "t2": 500.0, "r1": 0.0},
        "settings": {"weighting": "size"},
        "picks": {},
        "sectors": {"AAA": "Healthcare", "BBB": "Industrials", "CCC": "Energy"},
        "employer_sector": "Consumer Cyclical",
        "lots": {},
        "rates": {"short_term": 0.24, "long_term": 0.15},
        "today": "2026-10-29",
    }
    p.update(over)
    return p


def test_mix_reports_sleeves_and_flags() -> None:
    out = load_script(SL).run_sleeves(_params(mode="mix"))
    m = out["mix"]
    assert m["total"]["value"] == 47000.0 and m["satellite"]["value"] == 4500.0 and m["employer"]["value"] == 4000.0
    assert m["ceiling_source"] == "default"
    codes = {f["code"] for f in out["flags"]}
    assert {"DECISION_NEEDED", "PICK_IN_RETIREMENT", "LOW_N_EFF"} <= codes
    assert "EMPLOYER_CONCENTRATION" not in codes      # 4000/47000 < 10%
    assert out["trades"] == []


def test_add_splits_by_current_size() -> None:
    out = load_script(SL).run_sleeves(_params(mode="add", amount=1200))
    buys = {(t["symbol"], t["account"]): t["value"] for t in out["trades"] if t["side"] == "BUY"}
    assert buys == {("AAA", "t1"): 600.0, ("BBB", "t1"): 600.0}   # BBB pro rata to its 2000 total, routed to t1 (equal holding -> first by id)


def test_add_routes_to_larger_trading_holding() -> None:
    p = _params(mode="add", amount=900)
    # make t2's BBB larger: 1500 vs t1's 1000
    p["positions"][5] = _pos("BBB", 30, "t2", "satellite")
    out = load_script(SL).run_sleeves(p)
    bbb = [t for t in out["trades"] if t["symbol"] == "BBB" and t["side"] == "BUY"]
    assert bbb and all(t["account"] == "t2" for t in bbb)
    assert not any(t["account"] == "r1" for t in out["trades"])


def test_add_more_than_trading_cash_is_bad_input() -> None:
    with pytest.raises(ValueError, match="only 3500.00 cash in trading accounts"):
        load_script(SL).run_sleeves(_params(mode="add", amount=5000))


def test_add_stops_at_ceiling() -> None:
    out = load_script(SL).run_sleeves(_params(mode="add", amount=3000, settings={"ceiling": 0.10}))
    assert out["over_ceiling_amount"] > 0 and any(f["code"] == "ABOVE_CEILING" for f in out["flags"])


def test_deposit_without_split_is_a_proposal() -> None:
    out = load_script(SL).run_sleeves(_params(mode="deposit", amount=2000))
    assert out["trades"] == [] and set(out["proposal"]) == {"satellite", "core"}


def _deep(central: float, er: float, recheck_due: bool = False, age_days: int = 30) -> dict:
    return {"kind": "deep", "central_value": central, "expected_return": er,
            "age_days": age_days, "recheck_due": recheck_due}


def _light() -> dict:
    return {"kind": "light", "central_value": 70.0, "expected_return": None, "age_days": 30, "recheck_due": False}


def test_valuation_with_no_eligible_picks_falls_back() -> None:
    p = _params(mode="add", amount=1000, weighting="valuation", picks={"AAA": _light(), "BBB": _deep(central=60, er=0.1, recheck_due=True)})
    out = load_script(SL).run_sleeves(p)
    assert out["weighting_used"] == "equal"
    assert {"VALUATION_FALLBACK", "LIGHT_VALUATION", "RECHECK_DUE"} <= {f["code"] for f in out["flags"]}


def test_size_mode_never_sells() -> None:
    p = _params(mode="add", amount=1000, picks={"BBB": _deep(central=40, er=0.02)})
    assert all(t["side"] == "BUY" for t in load_script(SL).run_sleeves(p)["trades"])


def test_account_short_money_is_unallocated() -> None:
    p = _params(mode="add", amount=1000, cash_by_account={"t1": 100.0, "t2": 1000.0, "r1": 0.0})
    out = load_script(SL).run_sleeves(p)
    buys = sum(t["value"] for t in out["trades"] if t["side"] == "BUY")
    assert out["unallocated_amount"] == pytest.approx(400.0)
    assert buys == pytest.approx(600.0, abs=0.01)
    assert {"ACCOUNT_SHORT", "UNALLOCATED"} <= {f["code"] for f in out["flags"]}


def test_long_term_date_is_the_day_after_the_anniversary() -> None:
    sl = load_script(SL)
    assert sl._long_term_date("2026-03-01") == "2027-03-02"
    assert sl._long_term_date("2024-02-29") == "2025-03-01"


def test_recheck_due_pick_is_never_trimmed() -> None:
    p = _params(mode="add", amount=1000, weighting="valuation", settings={"short_term_gain_policy": "allow"},
                picks={"AAA": _deep(150, 0.2), "BBB": _deep(40, 0.02, recheck_due=True)})
    out = load_script(SL).run_sleeves(p)
    assert not any(t["symbol"] == "BBB" and t["side"] == "SELL" for t in out["trades"])
    assert next(r for r in out["splits"] if r["symbol"] == "BBB")["target"] >= 2000.0
    assert "RECHECK_DUE" in {f["code"] for f in out["flags"]}


def test_pick_with_unknown_age_is_treated_as_recheck_due() -> None:
    p = _params(mode="add", amount=1000, weighting="valuation", settings={"short_term_gain_policy": "allow"},
                picks={"AAA": _deep(150, 0.2), "BBB": _deep(40, 0.02, age_days=None)})
    out = load_script(SL).run_sleeves(p)
    assert not any(t["symbol"] == "BBB" and t["side"] == "SELL" for t in out["trades"])
    assert "RECHECK_DUE" in next(r for r in out["splits"] if r["symbol"] == "BBB")["flags"]
    assert any(f["code"] == "RECHECK_DUE" and f["message"].startswith("BBB") for f in out["flags"])


def test_account_plan_clamps_target_weights() -> None:
    sl = load_script(SL)
    p = _params(mode="add")
    positions = sl._read_positions(p, sl._read_accounts(p))
    plan = sl._account_plan("t1", positions, 3000.0, {"AAA": -5000.0}, 0.0, p)    # target below 0
    sells = [t for t in plan["rebalance"]["trades"] if t["symbol"] == "AAA"]
    assert sells and all(t["side"] == "SELL" for t in sells) and sum(t["value"] for t in sells) <= 2000.0


@pytest.mark.parametrize("exc, code", [(ValueError("bad"), 2), (TypeError("bad"), 2), (KeyError("bug"), None), (ZeroDivisionError("bug"), None)])
def test_sleeves_main_maps_only_input_errors_to_exit_2(monkeypatch, capsys, exc, code) -> None:
    import io
    sl = load_script(SL)

    def boom(params):
        raise exc

    monkeypatch.setattr(sl, "run_sleeves", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    if code is None:
        with pytest.raises(type(exc)):
            sl.main()
    else:
        with pytest.raises(SystemExit) as e:
            sl.main()
        assert e.value.code == 2 and json.loads(capsys.readouterr().out) == {"error": "bad"}


def test_sleeves_main_bad_json_is_exit_2(monkeypatch, capsys) -> None:
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("{bad"))
    with pytest.raises(SystemExit) as e:
        load_script(SL).main()
    assert e.value.code == 2


def test_include_light_must_be_boolean() -> None:
    with pytest.raises(ValueError, match="include_light"):
        load_script(SL).run_sleeves(_params(mode="mix", include_light="false"))
    with pytest.raises(ValueError, match="include_light"):
        load_script(SL).run_sleeves(_params(mode="mix", settings={"include_light": "false"}))


def test_grow_by_ambiguous_percent_returns_both_readings() -> None:
    out = load_script(SL).run_sleeves(_params(mode="grow", grow={"by_ambiguous": 0.05}))
    r = out["readings"]
    assert r["points"]["amount"] == pytest.approx(0.05 * 47000, abs=0.01)
    assert r["relative"]["amount"] == pytest.approx(4500 * 0.05, abs=0.01)
    assert out["trades"] == []
    assert "AMBIGUOUS_PERCENT" in {f["code"] for f in out["flags"]}


@pytest.mark.parametrize("grow", [
    {"to_weight": 15}, {"to_weight": 0}, {"to_weight": -0.1}, {"to_weight": 1.01},
    {"by_points": 0}, {"by_points": 1}, {"by_points": 2}, {"by_points": -0.02},
    {"by_relative": 0}, {"by_relative": -0.5},
    {"by_ambiguous": 0}, {"by_ambiguous": -0.05},
    {"amount": 0}, {"amount": -100},
])
def test_grow_values_out_of_range_are_bad_input(grow) -> None:
    key = next(iter(grow))
    with pytest.raises(ValueError, match=f"grow.{key}"):
        load_script(SL).run_sleeves(_params(mode="grow", grow=grow))


def test_run_grow_to_weight_15_is_bad_input(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script(R), ["grow", "--to-weight", "15"], capsys)
    assert rc == 2 and "to_weight" in out["error"]


def test_grow_sells_trading_core_never_retirement() -> None:
    out = load_script(SL).run_sleeves(_params(mode="grow", grow={"amount": 6000},
                                              settings={"weighting": "size", "ceiling": 0.25, "short_term_gain_policy": "allow"}))
    sells = [t for t in out["trades"] if t["side"] == "SELL"]
    assert sells and all(t["account"] in {"t1", "t2"} and t["symbol"] in {"VTI", "VXUS"} for t in sells)


def _bond_params(amount: float, core_rank: dict | None) -> dict:
    p = _params(mode="grow", grow={"amount": amount}, settings={"weighting": "size", "ceiling": 0.25, "short_term_gain_policy": "allow"},
                lots={"VTI": [{"units": 5, "cost_per_unit": 80.0, "term": "long", "account": "t1"}],
                      "BND": [{"units": 20, "cost_per_unit": 60.0, "term": "long", "account": "t1"}]})   # BND at a loss
    p["positions"][0] = _pos("VTI", 5, "t1", "core")                     # 500 of VTI in t1
    p["positions"].append(_pos("BND", 20, "t1", "core"))                  # 1000 of BND in t1
    if core_rank is not None:
        p["core_rank"] = core_rank
    return p


def test_core_sales_use_equity_before_a_loss_making_bond_fund() -> None:
    sl = load_script(SL)
    rank = {"VTI": 0, "VXUS": 1, "BND": 3}

    def sells(out: dict) -> dict:
        return {t["symbol"]: t["value"] for t in out["trades"] if t["side"] == "SELL" and t["account"] == "t1"}

    out = sl.run_sleeves(_bond_params(3400, rank))                       # t1 is 400 short of cash
    assert sells(out) == {"VTI": 400.0}
    assert "BOND_FUND_SOLD" not in {f["code"] for f in out["flags"]}
    out = sl.run_sleeves(_bond_params(4000, rank))                       # 1000 short: all VTI, then BND
    assert sells(out) == {"VTI": 500.0, "BND": 500.0}
    assert any(f["code"] == "BOND_FUND_SOLD" and "BND" in f["message"] for f in out["flags"])
    assert sells(sl.run_sleeves(_bond_params(3400, None))) == {"BND": 400.0}   # no ranks: smallest gain only


def test_run_core_rank_from_asset_bucket() -> None:
    r = load_script(R)
    info = {"VTI": {"quote_type": "ETF", "name": "Vanguard Total Stock Market ETF"},
            "VXUS": {"quote_type": "ETF", "name": "Vanguard Total International Stock ETF"},
            "BND": {"quote_type": "ETF", "name": "Vanguard Total Bond Market ETF"},
            "GLD": {"quote_type": "ETF", "name": "SPDR Gold Shares"}}
    rows = [{"symbol": s, "bucket": "core"} for s in ("VTI", "VXUS", "BND", "GLD", "XYZ")] + [{"symbol": "AAA", "bucket": "satellite"}]
    assert r._core_rank(rows, info) == {"VTI": 0, "VXUS": 1, "BND": 3, "GLD": 2, "XYZ": 2}


def test_run_passes_core_rank_to_sleeves(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)
    seen = {}
    real = r.sleeves.run_sleeves
    monkeypatch.setattr(r.sleeves, "run_sleeves", lambda params: seen.setdefault("p", params) and real(params))
    rc, out = run_json(r, ["mix"], capsys)
    assert rc == 0, out
    assert seen["p"]["core_rank"] == {"VTI": 0}


def test_grow_without_amount_offers_similar_to_last() -> None:
    s = {"increases": [{"date": "2026-08-01", "amount": 1000}, {"date": "2026-09-01", "amount": 1500}, {"date": "2026-10-01", "amount": 2000}]}
    out = load_script(SL).run_sleeves(_params(mode="grow", settings=s))
    assert out["similar_to_last"]["amount"] == 1500 and out["trades"] == []


def test_new_pick_needed_is_median_and_fixed_amount_splits() -> None:
    out = load_script(SL).run_sleeves(_params(mode="new-pick", new_pick={"symbol": "NEW", "price": 25.0}))
    assert out["new_pick"]["needed"] == 2000.0          # median of AAA 2000, BBB 2000 (CCC is retirement, excluded)
    out = load_script(SL).run_sleeves(_params(mode="new-pick", new_pick={"symbol": "NEW", "price": 25.0, "amount": 3000}))
    assert out["new_pick"]["allocated"] == 2000.0
    assert sum(t["value"] for t in out["trades"] if t["side"] == "BUY" and t["symbol"] != "NEW") == pytest.approx(1000.0, abs=0.01)


def test_plan_step_spreads_gap_over_remaining_steps() -> None:
    plan = {"target": 0.15, "by_date": "2027-01-29", "cadence": "monthly", "funding": "cash", "status": "active", "next_due": "2026-10-29"}
    out = load_script(SL).run_sleeves(_params(mode="plan-step", settings={"plan": plan, "ceiling": 0.20}))
    assert out["step"]["steps_left"] == 3
    assert out["step"]["amount"] == pytest.approx((0.15 * 47000 - 4500) / 3, abs=0.01)


def test_grow_with_unset_policy_holds_back_lotless_core() -> None:
    out = load_script(SL).run_sleeves(_params(mode="grow", grow={"amount": 6000}, settings={"weighting": "size", "ceiling": 0.25}))
    assert not any(t["side"] == "SELL" for t in out["trades"])
    decisions = [f for f in out["flags"] if f["code"] == "DECISION_NEEDED" and "short_term_gain_policy" in f["message"]]
    assert len(decisions) == 1
    assert out["unallocated_amount"] > 0
    assert out["held_back"] and all(r["symbol"] in {"VTI", "VXUS"} and r["account"] in {"t1", "t2"} for r in out["held_back"])


def test_deposit_proposal_uses_plan_step_within_room() -> None:
    plan = {"target": 0.30, "by_date": "2026-11-29", "cadence": "monthly", "funding": "cash", "status": "active", "next_due": "2026-10-29"}
    out = load_script(SL).run_sleeves(_params(mode="deposit", amount=2000, settings={"plan": plan, "ceiling": 0.10}))
    room = out["mix"]["room_under_ceiling"]
    assert room == 200.0
    assert out["proposal"] == {"satellite": 200.0, "core": 1800.0}


def _pricey_etfs(p: dict, price: float = 950.0) -> dict:
    for row in p["positions"]:
        if row["symbol"] in ("VTI", "VXUS"):
            row["price"] = price
    return p


def _assert_whole_share_cash(out: dict, amount: float) -> None:
    for a in out["accounts"]:
        assert a["rebalance"]["cash_after"] >= -0.005, a["account"]
    picks = {"AAA", "BBB", "NEW"}
    net = sum(t["value"] * (1 if t["side"] == "BUY" else -1) for t in out["trades"] if t["symbol"] in picks)
    assert net == pytest.approx(amount - out["over_ceiling_amount"] - out["unallocated_amount"], abs=0.01)
    assert all(float(t["units"]).is_integer() for t in out["trades"])


def test_whole_share_grow_core_sale_rounds_up_and_never_overspends() -> None:
    p = _pricey_etfs(_params(mode="grow", grow={"amount": 6000}, whole_shares=True,
                             settings={"ceiling": 0.30, "short_term_gain_policy": "allow"}))
    out = load_script(SL).run_sleeves(p)
    assert any(t["side"] == "SELL" and t["symbol"] in {"VTI", "VXUS"} for t in out["trades"])
    _assert_whole_share_cash(out, 6000)


def test_new_pick_lands_in_account_with_most_cash_and_core() -> None:
    out = load_script(SL).run_sleeves(_params(mode="new-pick", new_pick={"symbol": "NEW", "price": 25.0}))
    assert out["new_pick"]["account"] == "t1"
    assert any(t["symbol"] == "NEW" and t["side"] == "BUY" and t["account"] == "t1" for t in out["trades"])
    with pytest.raises(ValueError, match="AAA is already held; use add"):
        load_script(SL).run_sleeves(_params(mode="new-pick", new_pick={"symbol": "aaa", "price": 25.0}))


def test_new_pick_rejects_employer_symbol_even_when_not_held() -> None:
    p = _params(mode="new-pick", new_pick={"symbol": "AMZN", "price": 200.0}, settings={"employer_symbol": "amzn"})
    p["positions"] = [r for r in p["positions"] if r["symbol"] != "AMZN"]
    with pytest.raises(ValueError, match="AMZN is the employer symbol"):
        load_script(SL).run_sleeves(p)


def test_new_pick_rejects_held_symbol_left_out_of_the_plan() -> None:
    p = _params(mode="new-pick", new_pick={"symbol": "ddd", "price": 20.0}, excluded_symbols=["DDD"])
    with pytest.raises(ValueError, match="DDD is already held"):
        load_script(SL).run_sleeves(p)


def test_plan_step_needs_active_plan_and_cash_funding_never_sells() -> None:
    plan = {"target": 0.15, "by_date": "2027-01-29", "cadence": "monthly", "funding": "cash", "status": "paused", "next_due": "2026-10-29"}
    with pytest.raises(ValueError, match="no active plan; settings.py plan-set creates one"):
        load_script(SL).run_sleeves(_params(mode="plan-step", settings={"plan": plan}))
    plan = dict(plan, status="active", by_date="2026-11-29")       # one step: 2550, more than the 3500 cash split allows in t1
    out = load_script(SL).run_sleeves(_params(mode="plan-step", settings={"plan": plan, "short_term_gain_policy": "allow"},
                                              cash_by_account={"t1": 1000.0, "t2": 500.0, "r1": 0.0}))
    assert out["trades"] and not any(t["side"] == "SELL" for t in out["trades"])
    assert out["unallocated_amount"] > 0


# --- run.py (live wrapper) ----------------------------------------------------------------------

R = "core-satellite/scripts/run.py"
CS_POSITIONS = {
    "acc-1": [
        {"symbol": {"symbol": {"symbol": "VTI"}}, "units": 50, "price": 200.0, "average_purchase_price": 150.0},
        {"symbol": {"symbol": {"symbol": "AAA"}}, "units": 10, "price": 100.0, "average_purchase_price": 90.0},
        {"symbol": {"symbol": {"symbol": "BBB"}}, "units": 10, "price": 50.0, "average_purchase_price": 40.0},
    ],
    "acc-2": [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 20, "price": 200.0, "average_purchase_price": 120.0}],
}
CS_BALANCES = {"acc-1": [{"currency": {"code": "USD"}, "cash": 2000.0, "buying_power": 2000.0}], "acc-2": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}]}
CS_SECTORS = {
    "VTI": {"quote_type": "ETF", "sector": "ETF", "fund_sectors": {"technology": 0.3}},
    "AAA": {"quote_type": "EQUITY", "sector": "Industrials", "fund_sectors": None},
    "BBB": {"quote_type": "EQUITY", "sector": "Healthcare", "fund_sectors": None},
    "CCC": {"quote_type": "EQUITY", "sector": "Energy", "fund_sectors": None},
    "ZZZ": {"quote_type": "EQUITY", "sector": "Utilities", "fund_sectors": None},
    "QQQ": {"quote_type": "ETF", "sector": "ETF", "fund_sectors": {"technology": 0.5}},
    "SPYM": {"quote_type": "EQUITY", "sector": None, "fund_sectors": None, "proxy": "SPY"},
    "OPTX": {"quote_type": "OPTION", "sector": None, "fund_sectors": None},
}


def _deep_baseline(tmp_path, sym: str, central: float) -> str:
    rel = f"picks/{sym}-2026-10-01.json"
    (tmp_path / "picks").mkdir(exist_ok=True)
    model = {"scenarios": [{"name": "base", "value_per_share": central}, {"name": "bear", "value_per_share": central * 0.6}]}
    (tmp_path / rel).write_text(json.dumps({"symbol": sym, "as_of": "2026-10-01", "model": model}))
    return rel


@pytest.fixture
def cs_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
                   get_user_account_positions=lambda account_id: CS_POSITIONS[account_id],
                   get_user_account_balance=lambda account_id: CS_BALANCES[account_id])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {})
    monkeypatch.setattr(market, "sectors", lambda symbols, cache_path=None: {s: CS_SECTORS[s] for s in symbols if s in CS_SECTORS})
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: [{"symbol": s, "price": 25.0} for s in symbols])
    picks = [{"symbol": s, "kind": "deep", "baseline": _deep_baseline(tmp_path, s, c), "baseline_as_of": "2026-10-01",
              "next_earnings": "2027-01-30", "checks": []} for s, c in (("AAA", 120.0), ("BBB", 60.0))]
    (tmp_path / "picks.json").write_text(json.dumps({"picks": picks}))
    monkeypatch.syspath_prepend(str(PLUGIN_ROOT / "skills" / "stock-screener" / "scripts"))
    import track_math  # the module picks.py imports; run.py reads expected returns through it
    monkeypatch.setattr(track_math, "_irrs", lambda model, price, flags: {"base": 0.15})
    return fake


def test_run_mix_classifies_and_reads_roles(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script(R), ["mix"], capsys)
    assert rc == 0, out
    assert out["mix"]["satellite"]["value"] > 0 and out["mix"]["core"]["value"] > 0
    assert out["mix"]["satellite"]["value"] == 1500.0 and out["mix"]["core"]["value"] == 14000.0
    assert out["mix"]["retirement_value"] == 4000.0 and out["sources"]["holdings"] == "snaptrade"
    assert out["no_price"] == []


def test_run_add_valuation_uses_pick_store(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script(R), ["add", "500", "--weighting", "valuation"], capsys)
    assert rc == 0, out
    assert out["weighting_used"] == "valuation"
    assert {s["symbol"] for s in out["splits"]} == {"AAA", "BBB"}
    assert not any(f["code"] in ("NO_SAVED_VALUATION", "PICK_BASELINE_MISSING", "NO_PICK_STORE") for f in out["flags"])


def test_run_skips_holding_without_price(cs_sdk, capsys, monkeypatch) -> None:
    ccc = {"symbol": {"symbol": {"symbol": "CCC"}}, "units": 5, "price": None, "average_purchase_price": 10.0}
    monkeypatch.setitem(CS_POSITIONS, "acc-1", [*CS_POSITIONS["acc-1"], ccc])
    rc, out = run_json(load_script(R), ["mix"], capsys)
    assert rc == 0, out
    assert any(f["code"] == "NO_PRICE" and "CCC" in f["message"] for f in out["flags"])
    assert out["no_price"] == ["CCC"] and out["mix"]["satellite"]["value"] == 1500.0


def test_run_new_pick_without_price_is_bad_input(cs_sdk, capsys, monkeypatch) -> None:
    monkeypatch.setattr(market, "quote", lambda syms, hub=None: [])
    rc, out = run_json(load_script(R), ["new-pick", "ZZZ"], capsys)
    assert rc == 2
    assert "ZZZ" in out["error"]


def test_classify_buckets_and_leaves_unknown_types_out() -> None:
    rows = [{"symbol": s, "units": 1.0, "price": 10.0, "account": "acc-1"} for s in ("VTI", "AAA", "SPYM", "MMF", "EMP", "OPT", "NONE")]
    info = {"VTI": {"quote_type": "ETF"}, "AAA": {"quote_type": "EQUITY", "fund_sectors": None},
            "SPYM": {"quote_type": "EQUITY", "proxy": "SPY"}, "MMF": {"quote_type": "MONEYMARKET"},
            "EMP": {"quote_type": "EQUITY"}, "OPT": {"quote_type": "OPTION"}}
    out, unknown = load_script(R)._classify(rows, info, "EMP")
    assert {p["symbol"]: p["bucket"] for p in out} == {"VTI": "core", "AAA": "satellite", "SPYM": "core", "MMF": "cash", "EMP": "employer"}
    assert unknown == ["NONE", "OPT"]


def test_run_leaves_unclassified_holding_out(cs_sdk, capsys, monkeypatch) -> None:
    ddd = {"symbol": {"symbol": {"symbol": "DDD"}}, "units": 5, "price": 10.0, "average_purchase_price": 10.0}
    monkeypatch.setitem(CS_POSITIONS, "acc-1", [*CS_POSITIONS["acc-1"], ddd])
    rc, out = run_json(load_script(R), ["mix"], capsys)
    assert rc == 0, out
    assert [f for f in out["flags"] if f["code"] == "UNCLASSIFIED"][0]["message"].startswith("type of DDD")
    assert out["mix"]["satellite"]["value"] == 1500.0 and out["mix"]["total"]["value"] == 17500.0


def test_run_saved_role_overrides_raw_type(cs_sdk, capsys) -> None:
    p = profile.new_profile("complete")
    profile.set_field(p, "account_roles", {"acc-2": "trading"})
    profile.save(p)
    rc, out = run_json(load_script(R), ["mix"], capsys)
    assert rc == 0, out
    assert out["mix"]["retirement_value"] == 0.0 and out["mix"]["trading_value"] == 17500.0


def test_run_invalid_saved_role_falls_back_to_raw_type(cs_sdk, capsys, tmp_path) -> None:
    p = profile.new_profile("complete")
    p["fields"]["account_roles"] = {"value": {"acc-2": "bogus"}, "source": "declared", "at": "2026-10-01"}
    profile.save(p)
    rc, out = run_json(load_script(R), ["mix"], capsys)
    assert rc == 0, out
    assert out["mix"]["retirement_value"] == 4000.0


def _edit_pick(tmp_path, sym: str, **fields) -> None:
    path = tmp_path / "picks.json"
    book = json.loads(path.read_text())
    next(p for p in book["picks"] if p["symbol"] == sym).update(fields)
    path.write_text(json.dumps(book))


def _recheck_codes(capsys) -> list[str]:
    rc, out = run_json(load_script(R), ["add", "500", "--weighting", "valuation", "--today", "2026-10-29"], capsys)
    assert rc == 0, out
    return [f["message"].split()[0] for f in out["flags"] if f["code"] == "RECHECK_DUE"]


@pytest.mark.parametrize("fields, due", [
    ({"awaiting_filing": True}, True),
    ({"next_earnings": "2026-10-20", "checks": [{"date": "2026-10-10", "status": "inside"}]}, True),
    ({"next_earnings": "2026-10-20", "checks": [{"date": "2026-10-21", "status": "inside"}]}, False),
    ({"checks": [{"date": "2026-10-21", "status": "outside"}]}, True),
    ({"checks": [{"date": "2026-10-21", "status": "inside"}]}, False),
    ({"next_earnings": None, "baseline_as_of": "2026-06-01"}, True),      # 150 days, no earnings date
    ({"next_earnings": None, "baseline_as_of": "2026-07-01"}, False),     # 120 days: not past the line
    ({"next_earnings": None}, False),
])
def test_run_recheck_due_branches(cs_sdk, capsys, tmp_path, fields, due) -> None:
    _edit_pick(tmp_path, "AAA", **fields)
    assert _recheck_codes(capsys) == (["AAA"] if due else [])


@pytest.mark.parametrize("base, price, expected", [(150.0, 100.0, 1.5 ** (1 / 3) - 1), (80.0, 100.0, 0.8 ** (1 / 3) - 1),
                                                    (0.0, 100.0, None), (150.0, 0.0, None)])
def test_run_light_pick_expected_return_is_three_year_convergence(cs_sdk, tmp_path, base, price, expected) -> None:
    (tmp_path / "picks" / "AAA-light.json").write_text(json.dumps({"symbol": "AAA", "fair_values": {"base": base, "bear": base * 0.7}}))
    _edit_pick(tmp_path, "AAA", kind="light", baseline="picks/AAA-light.json")
    flags: list[dict] = []
    pick = load_script(R)._picks({"AAA": price, "BBB": 50.0}, "2026-10-29", flags, [])["AAA"]
    assert pick["kind"] == "light" and pick["central_value"] == base
    assert pick["expected_return"] == (None if expected is None else pytest.approx(expected))


def test_light_pick_in_tilt_says_three_year_estimate() -> None:
    light = {"kind": "light", "central_value": 70.0, "expected_return": 0.1187, "age_days": 30, "recheck_due": False}
    out = load_script(SL).run_sleeves(_params(mode="add", amount=1000, weighting="valuation", include_light=True,
                                              picks={"AAA": light, "BBB": _deep(60, 0.1)}))
    msg = next(f["message"] for f in out["flags"] if f["code"] == "LIGHT_VALUATION")
    assert "3-year convergence estimate from the light fair value" in msg
    assert "LIGHT_VALUATION" in next(r for r in out["splits"] if r["symbol"] == "AAA")["flags"]


def test_run_grow_conflict_and_ambiguous_by(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script(R), ["grow", "--by", "0.05", "--to-weight", "0.1"], capsys)
    assert rc == 2 and "not allowed" in out["error"]
    rc, out = run_json(load_script(R), ["grow", "--by", "0.05"], capsys)
    assert rc == 0, out
    assert set(out["readings"]) == {"points", "relative"} and out["trades"] == []
    assert any(f["code"] == "AMBIGUOUS_PERCENT" for f in out["flags"])


@pytest.mark.parametrize("bad", ["missing", "no_scenarios"])
def test_run_unusable_baseline_leaves_pick_out(cs_sdk, capsys, tmp_path, bad) -> None:
    if bad == "missing":
        _edit_pick(tmp_path, "AAA", baseline="picks/AAA-gone.json")
    else:
        (tmp_path / "picks" / "AAA-2026-10-01.json").write_text(json.dumps({"symbol": "AAA", "model": {"scenarios": []}}))
    rc, out = run_json(load_script(R), ["add", "500", "--weighting", "valuation"], capsys)
    assert rc == 0, out
    codes = {(f["code"], f["message"].split()[0].rstrip(":")) for f in out["flags"]}
    assert ("PICK_BASELINE_MISSING", "AAA") in codes and ("NO_SAVED_VALUATION", "AAA") in codes
    assert ("NO_SAVED_VALUATION", "BBB") not in codes


def test_run_corrupt_pick_store_continues(cs_sdk, capsys, tmp_path) -> None:
    (tmp_path / "picks.json").write_text("{bad")
    rc, out = run_json(load_script(R), ["add", "500", "--weighting", "valuation"], capsys)
    assert rc == 0, out
    assert any(f["code"] == "PICK_STORE_UNREADABLE" for f in out["flags"]) and out["weighting_used"] == "equal"


def test_run_employer_symbol_is_its_own_bucket(cs_sdk, capsys, tmp_path) -> None:
    (tmp_path / "core-satellite.json").write_text(json.dumps({"employer_symbol": "BBB"}))
    rc, out = run_json(load_script(R), ["mix"], capsys)      # BBB has a saved deep pick: it is a pick
    assert rc == 0, out
    assert out["mix"]["employer"]["value"] == 0.0 and out["mix"]["satellite"]["value"] == 1500.0
    store = json.loads((tmp_path / "picks.json").read_text())
    store["picks"] = [pk for pk in store["picks"] if pk["symbol"] != "BBB"]
    (tmp_path / "picks.json").write_text(json.dumps(store))
    rc, out = run_json(load_script(R), ["mix"], capsys)      # no deep pick: its own bucket
    assert rc == 0, out
    assert out["mix"]["employer"]["value"] == 500.0 and out["mix"]["satellite"]["value"] == 1000.0


def test_run_new_pick_with_quoted_price(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script(R), ["new-pick", "zzz"], capsys)
    assert rc == 0, out
    assert out["new_pick"]["symbol"] == "ZZZ" and out["new_pick"]["account"] == "acc-1"
    assert any(t["symbol"] == "ZZZ" and t["side"] == "BUY" and t["account"] == "acc-1" for t in out["trades"])


@pytest.mark.parametrize("sym, kind", [("QQQ", "ETF"), ("SPYM", "fund"), ("OPTX", "OPTION"), ("NOPE", "unknown")])
def test_run_new_pick_must_be_a_plain_stock(cs_sdk, capsys, sym, kind) -> None:
    rc, out = run_json(load_script(R), ["new-pick", sym], capsys)
    assert rc == 2, out
    assert sym in out["error"] and kind in out["error"]


def test_run_new_pick_rejects_employer_and_left_out_holdings(cs_sdk, capsys, tmp_path, monkeypatch) -> None:
    (tmp_path / "core-satellite.json").write_text(json.dumps({"employer_symbol": "ZZZ"}))
    rc, out = run_json(load_script(R), ["new-pick", "ZZZ"], capsys)
    assert rc == 2 and "employer" in out["error"]
    (tmp_path / "core-satellite.json").write_text(json.dumps({"employer_symbol": "none"}))
    ccc = {"symbol": {"symbol": {"symbol": "CCC"}}, "units": 5, "price": None, "average_purchase_price": 10.0}
    monkeypatch.setitem(CS_POSITIONS, "acc-1", [*CS_POSITIONS["acc-1"], ccc])
    rc, out = run_json(load_script(R), ["new-pick", "CCC"], capsys)
    assert rc == 2 and "CCC is already held" in out["error"]


@pytest.mark.parametrize("exc", [KeyError("bug"), ZeroDivisionError("bug")])
def test_run_lets_bugs_surface_not_bad_input(cs_sdk, capsys, monkeypatch, exc) -> None:
    r = load_script(R)

    def boom(params):
        raise exc

    monkeypatch.setattr(r.sleeves, "run_sleeves", boom)
    rc, out = run_json(r, ["mix"], capsys)
    assert rc != 2 and out["type"] == type(exc).__name__


def test_settings_used_carries_employer_symbol() -> None:
    sl = load_script(SL)
    assert sl.run_sleeves(_params(mode="mix"))["settings_used"]["employer_symbol"] is None
    out = sl.run_sleeves(_params(mode="mix", settings={"employer_symbol": "AMZN"}))
    assert out["settings_used"]["employer_symbol"] == "AMZN"


def test_unset_employer_symbol_raises_decision_needed() -> None:
    sl = load_script(SL)

    def employer_flags(settings: dict) -> list[str]:
        out = sl.run_sleeves(_params(mode="mix", settings=settings))
        return [f["message"] for f in out["flags"] if f["code"] == "DECISION_NEEDED" and f["message"].startswith("employer_symbol is unset: ")]

    assert len(employer_flags({})) == 1
    assert len(employer_flags({"employer_symbol": None})) == 1
    assert employer_flags({"employer_symbol": "none"}) == []
    assert employer_flags({"employer_symbol": "AMZN"}) == []


@pytest.mark.parametrize("saved, employer", [("none", None), ("NONE", None), ("None", None), (None, None), ("", None), ("amzn", "AMZN")])
def test_run_saved_none_means_no_employer(saved, employer) -> None:
    assert load_script(R)._employer_symbol({"employer_symbol": saved}) == employer


def test_run_saved_none_employer_has_no_decision(cs_sdk, capsys, tmp_path) -> None:
    (tmp_path / "core-satellite.json").write_text(json.dumps({"employer_symbol": "none"}))
    rc, out = run_json(load_script(R), ["mix"], capsys)
    assert rc == 0, out
    assert out["mix"]["employer"]["value"] == 0.0
    assert not any(f["message"].startswith("employer_symbol is unset") for f in out["flags"])


def test_satellite_net_is_pick_buys_less_pick_sells() -> None:
    sl = load_script(SL)
    out = sl.run_sleeves(_params(mode="add", amount=1200))
    net = sum(t["value"] * (1 if t["side"] == "BUY" else -1) for t in out["trades"] if t["symbol"] in ("AAA", "BBB", "CCC"))
    assert out["satellite_net"] == round(net, 2) == 1200.0
    assert sl.run_sleeves(_params(mode="mix"))["satellite_net"] == 0.0
    grown = sl.run_sleeves(_params(mode="grow", grow={"amount": 4000}, settings={"weighting": "size", "short_term_gain_policy": "allow"}))
    assert any(t["side"] == "SELL" and t["symbol"] in ("VTI", "VXUS") for t in grown["trades"])
    picks_only = sum(t["value"] * (1 if t["side"] == "BUY" else -1) for t in grown["trades"] if t["symbol"] in ("AAA", "BBB"))
    assert grown["satellite_net"] == round(picks_only, 2) > 0


def test_skill_hands_off_sells_with_specific_lots() -> None:
    text = (PLUGIN_ROOT / "skills" / "core-satellite" / "SKILL.md").read_text()
    assert "`trades[].lots`" in text
    assert "specific-lot identification for exactly those lots" in text
    assert "the plan's tax result does not hold" in text


# --- randomized invariants ----------------------------------------------------------------------

_CORE_SYMS = {"VTI": 0, "VXUS": 1, "GLD": 2, "BND": 3}


def _fuzz_case(rng) -> dict:
    accts = {"t1": {"role": "trading"}, "t2": {"role": "trading"}, "r1": {"role": "retirement"}}
    if rng.random() < 0.4:
        accts["s1"] = {"role": "savings"}
    homes = list(accts)
    pos, lots, picks = [], {}, {}
    acquired = [None, "2026-03-01", "2025-01-05", "2024-02-29", "2026-09-30"]
    for sym in ["AAA", "BBB", "CCC", "DDD", "EEE"][: rng.randint(1, 5)]:
        price = rng.uniform(20, 300)
        for a in rng.sample(homes, rng.randint(1, 2)):
            units = rng.randint(1, 60)
            pos.append({"symbol": sym, "units": units, "price": price, "account": a, "bucket": "satellite"})
            left, n = units, rng.randint(0, 3)
            for i in range(n):
                lu = left if i == n - 1 else rng.randint(0, left)
                left -= lu
                if lu > 0:
                    lots.setdefault(sym, []).append({"units": lu, "cost_per_unit": price * rng.uniform(0.5, 1.5),
                                                     "term": rng.choice(["long", "short", "unknown"]), "account": a,
                                                     "acquired": rng.choice(acquired)})
        if rng.random() < 0.8:
            picks[sym] = {"kind": rng.choice(["deep", "deep", "light"]), "central_value": price * rng.uniform(0.6, 1.5),
                          "expected_return": rng.uniform(-0.05, 0.25),
                          "age_days": None if rng.random() < 0.1 else rng.randint(0, 600),
                          "recheck_due": rng.random() < 0.2}
    for sym in rng.sample(sorted(_CORE_SYMS), rng.randint(1, 4)):
        price = rng.uniform(50, 300)
        for a in rng.sample(homes, rng.randint(1, len(homes))):
            units = rng.randint(1, 200)
            pos.append({"symbol": sym, "units": units, "price": price, "account": a, "bucket": "core"})
            if rng.random() < 0.7:
                lots.setdefault(sym, []).append({"units": units, "cost_per_unit": price * rng.uniform(0.5, 1.5),
                                                 "term": rng.choice(["long", "short", "unknown"]), "account": a,
                                                 "acquired": rng.choice(acquired)})
    employer = rng.choice(["AMZN", "AMZN", None, "none"])
    if employer == "AMZN":
        for a in rng.sample(homes, rng.randint(1, 2)):
            pos.append({"symbol": "AMZN", "units": rng.randint(1, 80), "price": 200.0, "account": a, "bucket": "employer"})
            lots.setdefault("AMZN", []).append({"units": 1, "cost_per_unit": 100.0, "term": "long", "account": a})
    cash = {a: rng.uniform(0, 20000 if accts[a]["role"] == "trading" else 5000) for a in accts}
    settings = {"ceiling": rng.choice([None, 0.1, 0.2, 0.3]), "short_term_gain_policy": rng.choice([None, "hold", "allow"]),
                "weighting": rng.choice(["equal", "market_cap", "size", "valuation"]), "employer_symbol": employer}
    mode = rng.choice(["add", "deposit", "grow", "new-pick", "plan-step"])
    p = {"mode": mode, "positions": pos, "accounts": accts, "cash_by_account": cash, "settings": settings,
         "picks": picks, "lots": lots, "today": "2026-10-29", "whole_shares": rng.random() < 0.4,
         "include_light": rng.random() < 0.3, "rates": {"short_term": 0.24, "long_term": 0.15},
         "core_rank": {s: r for s, r in _CORE_SYMS.items() if rng.random() < 0.8},
         "market_caps": {x["symbol"]: None if rng.random() < 0.2 else rng.uniform(1e9, 1e12) for x in pos if x["bucket"] == "satellite"}}
    trading_cash = cash["t1"] + cash["t2"]
    if mode == "add":
        p["amount"] = rng.uniform(1, max(2, trading_cash))
    elif mode == "deposit":
        p["amount"] = rng.uniform(1, max(2, trading_cash))
        p["satellite_amount"] = p["amount"] * rng.random()
    elif mode == "grow":
        key = rng.choice(["to_weight", "by_points", "by_relative", "amount"])
        p["grow"] = {key: {"to_weight": rng.uniform(0.05, 0.4), "by_points": rng.uniform(0.005, 0.1),
                           "by_relative": rng.uniform(0.05, 1.0), "amount": rng.uniform(100, 20000)}[key]}
    elif mode == "new-pick":
        p["new_pick"] = {"symbol": "NEWP", "price": 40.0, **({"amount": rng.uniform(500, 8000)} if rng.random() < 0.5 else {})}
    else:
        settings["plan"] = {"status": "active", "target": rng.choice([0.15, 0.25]), "by_date": "2027-06-01",
                            "cadence": rng.choice(["monthly", "quarterly"]), "funding": rng.choice(["cash", "core"])}
    return p


def _invariant_errors(p: dict, out: dict) -> list[str]:
    errs = []
    roles = {a: v["role"] for a, v in p["accounts"].items()}
    pos = p["positions"]
    total = sum(x["units"] * x["price"] for x in pos) + sum(p["cash_by_account"].values())
    sat = sum(x["units"] * x["price"] for x in pos if x["bucket"] == "satellite")
    sat_syms = {x["symbol"] for x in pos if x["bucket"] == "satellite"}
    employer = {x["symbol"] for x in pos if x["bucket"] == "employer"} | {str(p["settings"]["employer_symbol"]).upper()}
    allow = p["settings"]["short_term_gain_policy"] == "allow"
    net: dict[str, float] = {}
    for t in out["trades"]:
        a = t["account"]
        if roles.get(a) != "trading":                                                    # 1
            errs.append(f"trade in {roles.get(a)} account {a}")
        if t["symbol"] in employer:                                                      # 2
            errs.append(f"employer symbol {t['symbol']} traded")
        net[a] = net.get(a, 0.0) + (t["value"] if t["side"] == "BUY" else -t["value"])
        held = p["picks"].get(t["symbol"]) or {}
        if t["symbol"] in sat_syms and held and (held.get("recheck_due") or held.get("age_days") is None):   # 6
            errs.append(f"pick {t['symbol']} traded ({t['side']}) though held for its recheck")
        if t["side"] != "SELL":
            continue
        if not allow:                                                                    # 4
            src = [lot for lot in p["lots"].get(t["symbol"], []) if lot.get("account") in (None, a)]
            safe = sum(lot["units"] for lot in src if lot["cost_per_unit"] >= t["price"] or lot["term"] == "long")
            if t["units"] > safe + 1e-6:
                errs.append(f"{t['symbol']} sells {t['units']} units, only {safe} are losses or long-term in {a}")
            if any(lot["term"] != "long" and lot["gain"] > 0.01 for lot in t.get("lots") or []):
                errs.append(f"{t['symbol']} sells a short-term or unknown-term gain lot")
        if t["symbol"] in sat_syms:                                                      # 6
            errs.append(f"pick {t['symbol']} sold")
    for a, v in net.items():                                                             # 3
        if v > p["cash_by_account"][a] + 0.02:
            errs.append(f"account {a} spends {v:.2f} net with {p['cash_by_account'][a]:.2f} cash")
    ceiling = p["settings"]["ceiling"] or 0.2
    if sat + out["satellite_net"] > max(ceiling * total, sat) + 0.05:                     # 5
        errs.append(f"satellite ends at {sat + out['satellite_net']:.2f}, ceiling {ceiling * total:.2f}")
    if p["mode"] == "add" and out["satellite_net"] > p["amount"] + 0.02:                 # 7
        errs.append("add puts more than amount into picks")
    return errs


def test_randomized_plans_keep_the_money_invariants() -> None:
    import random
    sl = load_script(SL)
    rng = random.Random(20261029)
    checked, failures = 0, []
    for i in range(300):
        p = _fuzz_case(rng)
        try:
            out = sl.run_sleeves(p)
        except (ValueError, TypeError):
            continue                                 # bad input by design (e.g. grow below current)
        checked += 1
        errs = _invariant_errors(p, out)
        if errs:
            failures.append((i, p["mode"], errs[:3]))
    assert checked >= 250, checked
    assert not failures, failures[:5]


def test_classify_sectorless_equity_with_fund_name_is_core() -> None:
    rows = [{"symbol": s, "units": 1.0, "price": 10.0, "account": "acc-1"} for s in ("SPYM", "IDXC")]
    info = {"SPYM": {"quote_type": "EQUITY", "sector": None, "fund_sectors": None,
                     "name": "State Street SPDR Portfolio S&P 500 ETF"},
            "IDXC": {"quote_type": "EQUITY", "sector": "Financial Services", "name": "Index Fund Holdings Corp"}}
    out, _ = load_script(R)._classify(rows, info, None)
    assert {p["symbol"]: p["bucket"] for p in out} == {"SPYM": "core", "IDXC": "satellite"}
    with pytest.raises(Exception, match="SPYM is a fund"):
        load_script(R)._check_new_pick("SPYM", info["SPYM"])


def test_sweep_position_reported_as_cash_counts_once() -> None:
    rows = [{"symbol": "SPAXX", "units": 5000.0, "price": 1.0, "account": "fid", "bucket": "cash"},
            {"symbol": "MVRXX", "units": 6000.0, "price": 1.0, "account": "et", "bucket": "cash"},
            {"symbol": "VTI", "units": 10.0, "price": 200.0, "account": "fid", "bucket": "core"}]
    out = load_script(R)._drop_sweep_copies(rows, {"fid": 5000.4, "et": 0.04})
    assert [p["symbol"] for p in out] == ["MVRXX", "VTI"]      # SPAXX matched fid's cash; MVRXX is not et's cash


def test_sell_first_sells_the_named_bond_fund_before_equity() -> None:
    sl = load_script(SL)
    p = _bond_params(3400, {"VTI": 0, "VXUS": 1, "BND": 3})
    p["sell_first"] = ["BND"]
    out = sl.run_sleeves(p)
    assert {t["symbol"]: t["value"] for t in out["trades"] if t["side"] == "SELL" and t["account"] == "t1"} == {"BND": 400.0}
    assert any(f["code"] == "BOND_FUND_SOLD" and "as named to sell first" in f["message"] for f in out["flags"])


def test_run_sell_must_name_a_trading_core_fund(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script(R), ["new-pick", "ZZZ", "--sell", "AAA"], capsys)
    assert rc == 2 and "AAA is not one" in out["error"]
    rc, out = run_json(load_script(R), ["new-pick", "ZZZ", "--sell", "vti"], capsys)
    assert rc == 0, out


def test_new_pick_lands_with_the_picks_not_the_most_cash() -> None:
    out = load_script(SL).run_sleeves(_params(mode="new-pick", new_pick={"symbol": "NEW", "price": 25.0},
                                              cash_by_account={"t1": 0.0, "t2": 50000.0, "r1": 0.0},
                                              settings={"short_term_gain_policy": "allow"}))
    assert out["new_pick"]["account"] == "t1"                   # t1 holds 3000 of picks, t2 1000
    assert any(t["symbol"] == "VTI" and t["side"] == "SELL" and t["account"] == "t1" for t in out["trades"])


class _History:
    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows

    def list_transactions(self, account_id, start=None, end=None, count=50):
        return {"account_id": account_id, "transactions": self.rows.get(account_id, [])}


def _tx(day: str, kind: str, sym: str, units: float, desc: str) -> dict:
    return {"trade_date": day, "type": kind, "units": units, "symbol": {"symbol": sym}, "description": desc}


def test_employer_candidate_from_vest_deposits() -> None:
    rows = {"t1": [_tx("2025-03-03", "CONTRIBUTION", "EMPL", 10, "Transfer from stock plan 0001"),
                   _tx("2025-03-05", "SELL", "EMPL", 10, "EMPLOYER CORP SOLD"),
                   _tx("2025-06-02", "CONTRIBUTION", "EMPL", 20, "RSU vest deposit 0002"),
                   _tx("2025-06-09", "CONTRIBUTION", "EMPL", 15, "Transfer from Shareworks 0003"),
                   _tx("2025-06-10", "SELL", "EMPL", 30, "EMPLOYER CORP SOLD"),
                   _tx("2025-09-01", "CONTRIBUTION", "EMPL", 25, "Equity award deposit 0004"),
                   _tx("2025-09-07", "SELL", "EMPL", 25, "EMPLOYER CORP SOLD"),
                   _tx("2025-09-15", "CONTRIBUTION", "EMPL", 5, "EMPLOYER CORP JOURNAL TO MARGIN")],
            "r1": [_tx("2026-03-01", "CONTRIBUTION", "XYZ", 5, "Shareworks"),
                   _tx("2026-06-01", "CONTRIBUTION", "XYZ", 5, "Shareworks"),
                   _tx("2026-09-01", "CONTRIBUTION", "XYZ", 5, "Shareworks"),
                   _tx("2026-10-01", "CONTRIBUTION", "XYZ", 5, "Shareworks")]}
    roles = {"t1": {"role": "trading"}, "r1": {"role": "retirement"}}
    accounts = [{"account_id": "t1"}, {"account_id": "r1"}]
    c = load_script(R)._employer_candidate(_History(rows), accounts, roles, "2025-10-29")
    assert c == {"symbol": "EMPL", "deposits": ["2025-03-03", "2025-06-02", "2025-06-09", "2025-09-01"],
                 "vests": ["2025-03-03", "2025-06-02", "2025-09-01"], "every_days": 91, "sold_within_days": 4}
    assert load_script(R)._employer_candidate(_History({}), accounts, roles, "2026-10-29") is None


def test_tilt_factor_tilts_by_valuation() -> None:
    w = load_script(W)
    pick = {"eligible": True, "confidence": 1.0, "central_value": 100.0, "price": 80.0, "expected_return": 0.15}
    assert w.tilt_factor(pick) == pytest.approx(1.2)            # 1 + 0.5 x 0.5 x (0.15 - 0.07) / 0.10
    assert w.tilt_factor(dict(pick, expected_return=0.07)) == pytest.approx(1.0)   # at the market return
    assert w.tilt_factor(dict(pick, price=125.0)) == pytest.approx(0.8)            # overvalued: trim factor
    assert w.tilt_factor(dict(pick, price=104.0)) == pytest.approx(1.2)            # within the 5% gap: not overvalued
    assert w.tilt_factor(dict(pick, confidence=0.0)) == 1.0
    assert w.tilt_factor(dict(pick, eligible=False)) == 1.0


def test_rebalance_targets_equal_weight_times_tilt() -> None:
    w = load_script(W)
    rows = [{"symbol": "A", "value": 5000, "price": 80, "central_value": 100, "expected_return": 0.15, "eligible": True, "confidence": 1.0},
            {"symbol": "B", "value": 1000, "price": 80, "central_value": 100, "expected_return": 0.07, "eligible": True, "confidence": 1.0},
            {"symbol": "C", "value": 2000, "price": 50, "central_value": 40, "expected_return": 0.0, "eligible": True, "confidence": 1.0}]
    out = w.rebalance_targets(rows, w.strategy_weights(rows, "valuation"), {"H": 1000.0}, 9000.0, 1_000_000.0)
    # base 1 each; tilt A 1.2, B 1.0, C trim factor 0.8 -> 8000 x [1.2, 1.0, 0.8] / 3.0
    assert out["targets"] == pytest.approx({"A": 3200.0, "B": 2666.67, "C": 2133.33, "H": 1000.0}, abs=0.01)
    assert out["capped"] == []
    assert w.band(400.0) == 250.0 and w.band(2000.0) == 500.0


def test_rebalance_targets_cap_redistributes() -> None:
    w = load_script(W)
    rows = [{"symbol": s, "value": 0, "price": 80, "central_value": 100, "expected_return": er, "eligible": True, "confidence": 1.0}
            for s, er in (("A", 0.30), ("B", 0.07), ("C", 0.07))]
    out = w.rebalance_targets(rows, w.strategy_weights(rows, "valuation"), {}, 3000.0, 20000.0)   # cap 1000 each
    assert out["targets"] == pytest.approx({"A": 1000.0, "B": 1000.0, "C": 1000.0})
    assert out["capped"] == ["A", "B", "C"]


# --- tilt, targets, holds and the shared _rb_params fixture -----------------------------------------

_RB_SETTINGS = {"weighting": "valuation", "short_term_gain_policy": "allow", "ceiling": 1.0, "employer_symbol": "none"}


def _rb_params(sat: dict[str, float], picks: dict, cash: float = 0.0, core: float = 300000.0, **over) -> dict:
    positions = [_pos("VTI", core / 100, "t1", "core")]
    positions += [{"symbol": s, "units": v / 50.0, "price": 50.0, "account": "t1", "bucket": "satellite"} for s, v in sat.items()]
    p = {"mode": "add", "positions": positions, "accounts": {"t1": {"role": "trading"}},
         "cash_by_account": {"t1": cash}, "settings": dict(_RB_SETTINGS), "picks": picks,
         "sectors": {s: "Industrials" for s in sat}, "lots": {}, "rates": {"short_term": 0.24, "long_term": 0.15},
         "today": "2026-10-29"}
    p.update(over)
    return p


def _rb_trades(out: dict) -> dict[str, float]:
    """Signed trade value by symbol (BUY +, SELL -)."""
    net: dict[str, float] = {}
    for t in out["trades"]:
        net[t["symbol"]] = net.get(t["symbol"], 0.0) + (t["value"] if t["side"] == "BUY" else -t["value"])
    return net


_GOOD, _FAIR = _deep(central=150.0, er=0.20), _deep(central=60.0, er=0.07)   # price 50 is below both centrals


def test_small_add_is_fully_placed() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 2000}, {"AAA": _GOOD, "BBB": _FAIR}, cash=100, amount=100))
    assert out["unallocated_amount"] == 0.0 and out["satellite_net"] == pytest.approx(100.0, abs=0.02)


def test_held_pick_never_trades() -> None:
    sl = load_script(SL)
    for extra, flag in (({}, "HELD_FOR_RECHECK"), ({"needs_valuation": True}, "DEEP_VALUATION_NEEDED")):
        bbb = {**_deep(central=60.0, er=0.07, recheck_due=True), **extra}
        out = sl.run_sleeves(_rb_params({"AAA": 1000, "BBB": 6000}, {"AAA": _GOOD, "BBB": bbb}, cash=100, amount=100))
        assert "BBB" not in _rb_trades(out)
        assert _rb_trades(out) == pytest.approx({"AAA": 100.0}, abs=0.02)
        assert flag in next(s for s in out["splits"] if s["symbol"] == "BBB")["flags"]
        assert any(f["code"] == flag and "BBB" in f["message"] for f in out["flags"])


def test_employer_new_pick_allowed_with_deep_pick() -> None:
    sl = load_script(SL)
    base = _rb_params({"AAA": 2000, "BBB": 2000}, {"AAA": _GOOD, "BBB": _FAIR}, mode="new-pick",
                      new_pick={"symbol": "AMZN", "price": 200.0}, settings={**_RB_SETTINGS, "employer_symbol": "AMZN"})
    with pytest.raises(ValueError, match="AMZN is the employer symbol"):
        sl.run_sleeves(base)
    out = sl.run_sleeves({**base, "picks": {**base["picks"], "AMZN": _deep(central=300.0, er=0.15)}})
    assert _rb_trades(out).get("AMZN", 0.0) > 0


def test_rebalance_targets_overflow_skips_overvalued() -> None:
    w = load_script(W)
    rows = [{"symbol": "A", "value": 0, "price": 80, "central_value": 100, "expected_return": 0.30, "eligible": True, "confidence": 1.0},
            {"symbol": "B", "value": 0, "price": 50, "central_value": 40, "expected_return": 0.0, "eligible": True, "confidence": 1.0}]
    raw = w.strategy_weights(rows, "valuation")               # cap 1000; A 1.575, B trim 0.8
    out = w.rebalance_targets(rows, raw, {}, 2500.0, 20000.0, closed={"B"})
    assert out["targets"]["A"] == 1000.0
    assert out["targets"]["B"] == pytest.approx(2500 * 0.8 / 2.375, abs=0.01)   # its own share only; the rest unassigned


def _captured_params(r, monkeypatch) -> dict:
    seen: dict = {}
    real = r.sleeves.run_sleeves
    monkeypatch.setattr(r.sleeves, "run_sleeves", lambda params: seen.update(p=params) or real(params))
    return seen


def test_run_rebalance_command_and_removed_flags(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    assert run_json(r, ["rebalance", "--weighting", "equal"], capsys)[0] == 0
    assert seen["p"]["mode"] == "rebalance" and "rebalance" not in seen["p"]
    for bad in (["add", "100", "--no-rebalance"], ["new-pick", "ZZZ", "--same-size"]):
        with pytest.raises(InvalidInput):
            r._parser().parse_args(bad)


@pytest.mark.parametrize("argv,reads", [
    (["mix", "--weighting", "market_cap"], False),
    (["deposit", "100", "--weighting", "market_cap"], False),
    (["new-pick", "ZZZ", "--weighting", "market_cap"], False),
    (["add", "100", "--weighting", "equal"], False),
    (["add", "100", "--weighting", "market_cap"], True),
    (["deposit", "100", "--satellite", "50", "--weighting", "market_cap"], True),
    (["grow", "--amount", "100", "--weighting", "market_cap"], True),
    (["plan-step", "--weighting", "market_cap"], True),
    (["rebalance", "--weighting", "market_cap"], True),
    (["new-pick", "ZZZ", "--amount", "100", "--weighting", "market_cap"], True),
])
def test_run_reads_market_caps_only_when_needed(cs_sdk, capsys, monkeypatch, argv, reads) -> None:
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    calls = []
    monkeypatch.setattr(market, "company_info", lambda s: calls.append(s) or {"market_cap": 1e11})
    run_json(r, argv, capsys)
    assert bool(calls) is reads and ("market_caps" in seen["p"]) is reads
    if reads:
        assert "ZZZ" not in seen["p"]["market_caps"] and all(v == 1e11 for v in seen["p"]["market_caps"].values())


def test_run_market_cap_from_saved_settings(cs_sdk, capsys, tmp_path, monkeypatch) -> None:
    (tmp_path / "core-satellite.json").write_text(json.dumps({"weighting": "market_cap"}))
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    monkeypatch.setattr(market, "company_info", lambda s: {"market_cap": 1e11})
    assert run_json(r, ["add", "100"], capsys)[0] == 0
    assert seen["p"]["market_caps"]


def test_run_new_pick_opens_without_its_own_market_cap(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)
    monkeypatch.setattr(market, "company_info", lambda s: {"market_cap": None if s == "ZZZ" else 1e11})
    rc, out = run_json(r, ["new-pick", "ZZZ", "--amount", "100", "--weighting", "market_cap"], capsys)
    assert rc == 0, out
    assert out["new_pick"]["allocated"] > 0


def test_run_market_cap_partial_failure(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)

    from yfinance.exceptions import YFRateLimitError

    def flaky(s):
        if s == "AAA":
            raise YFRateLimitError()
        return {"market_cap": 1e11}
    monkeypatch.setattr(market, "company_info", flaky)
    rc, out = run_json(r, ["add", "100", "--weighting", "market_cap"], capsys)
    assert rc == 0, out
    assert seen["p"]["market_caps"]["AAA"] is None and seen["p"]["market_caps"]["BBB"] == 1e11
    assert any(f["code"] == "NO_MARKET_CAP" and f["message"].startswith("AAA") for f in out["flags"])


def test_run_market_cap_failures(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)

    def boom(_s):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(market, "company_info", boom)
    rc, out = run_json(r, ["add", "100", "--weighting", "market_cap"], capsys)
    assert rc == 2 and "market_cap" in out["error"]
    assert run_json(r, ["mix", "--weighting", "market_cap"], capsys)[0] == 0


def test_run_unreadable_pick_data_reaches_the_plan(cs_sdk, capsys, tmp_path, monkeypatch) -> None:
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    _edit_pick(tmp_path, "AAA", baseline="picks/AAA-gone.json")
    rc, out = run_json(r, ["add", "100", "--weighting", "valuation"], capsys)
    assert rc == 0, out
    assert seen["p"]["unreadable_picks"] == ["AAA"] and seen["p"]["pick_store_unreadable"] is False
    msg = next(f["message"] for f in out["flags"] if f["code"] == "NO_SAVED_VALUATION" and f["message"].startswith("AAA"))
    assert "holds at its current value" in msg and "could not be read" in msg
    (tmp_path / "picks.json").write_text("{bad")
    rc, out = run_json(r, ["rebalance", "--weighting", "equal"], capsys)
    assert rc == 2 and "pick store" in out["error"]
    assert seen["p"]["pick_store_unreadable"] is True


def test_run_marks_needs_valuation(cs_sdk, capsys, tmp_path, monkeypatch) -> None:
    picks = [{"symbol": "AAA", "kind": "deep", "baseline": _deep_baseline(tmp_path, "AAA", 120.0), "baseline_as_of": "2026-10-01",
              "next_earnings": "2027-01-30", "checks": [{"date": "2026-10-20", "status": "outside"}]},
             {"symbol": "BBB", "kind": "deep", "baseline": _deep_baseline(tmp_path, "BBB", 60.0), "baseline_as_of": "2026-10-01",
              "next_earnings": "2027-01-30", "checks": []}]
    (tmp_path / "picks.json").write_text(json.dumps({"picks": picks}))
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    assert run_json(r, ["mix"], capsys)[0] == 0
    assert seen["p"]["picks"]["AAA"]["needs_valuation"] is True and seen["p"]["picks"]["AAA"]["recheck_due"] is True
    assert seen["p"]["picks"]["BBB"]["needs_valuation"] is False


def test_classify_employer_with_deep_pick_is_satellite() -> None:
    rows = [{"symbol": "EMP", "units": 1.0, "price": 10.0, "account": "acc-1"}]
    info = {"EMP": {"quote_type": "EQUITY", "sector": "Consumer Cyclical"}}
    r = load_script(R)
    assert r._classify(rows, info, "EMP")[0][0]["bucket"] == "employer"
    assert r._classify(rows, info, "EMP", {"EMP"})[0][0]["bucket"] == "satellite"


def test_employer_held_as_a_pick_still_counts_for_concentration() -> None:
    p = _params(settings={"employer_symbol": "AMZN"})
    p["positions"] = [dict(r, bucket="satellite") if r["symbol"] == "AMZN" else r for r in p["positions"]]
    p["positions"].append(_pos("AMZN", 80, "t2", "satellite"))                # 8000 of AMZN as a pick, 51000 total
    out = load_script(SL).run_sleeves(p)
    assert any(f["code"] == "EMPLOYER_CONCENTRATION" for f in out["flags"])


def test_fallback_never_buys_held_picks() -> None:
    picks = {"AAA": _deep(central=150.0, er=0.20, recheck_due=True), "BBB": _deep(central=60.0, er=0.07, recheck_due=True)}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 6000}, picks, cash=1000, amount=1000))
    assert out["trades"] == [] and out["unallocated_amount"] == pytest.approx(1000.0)
    for sym in ("AAA", "BBB"):
        assert "HELD_FOR_RECHECK" in next(s for s in out["splits"] if s["symbol"] == sym)["flags"]


def test_fallback_split_skips_held_picks_only() -> None:
    picks = {"AAA": _deep(central=150.0, er=0.20, recheck_due=True), "BBB": _light()}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 6000}, picks, cash=1000, amount=1000))
    assert _rb_trades(out) == pytest.approx({"BBB": 1000.0}, abs=0.02)


def test_cap_binding_rebalance_does_not_ratchet() -> None:
    sl = load_script(SL)
    sat = {"S00": 1959.0, "S01": 13803.0, "S02": 3660.0, "S03": 13183.0}
    picks = {"S00": _deep(central=52.67, er=0.267, age_days=92), "S01": _deep(central=43.42, er=0.098, age_days=132),
             "S02": _deep(central=69.88, er=0.130, age_days=253), "S03": _deep(central=60.0, er=0.10, recheck_due=True)}
    first = sl.run_sleeves(_rb_params(sat, picks, core=30000.0, mode="rebalance"))
    net = _rb_trades(first)                                  # total 62605, cap 3130.25: S00 takes what S01 sells
    assert net == pytest.approx({"S00": 1171.25, "S01": -1171.25}, abs=0.02)
    after = {s: v + net.get(s, 0.0) for s, v in sat.items()}
    assert sl.run_sleeves(_rb_params(after, picks, core=30000.0, mode="rebalance"))["trades"] == []


# --- adding money only buys; a new pick opens at the median -----------------------------------

def test_add_equal_gives_same_dollars() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 4000, "CCC": 4000}, {}, cash=900, amount=900, weighting="equal"))
    assert _rb_trades(out) == pytest.approx({"AAA": 300.0, "BBB": 300.0, "CCC": 300.0}, abs=0.02)


def test_add_size_is_pro_rata() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 3000}, {}, cash=400, amount=400, weighting="size"))
    assert _rb_trades(out) == pytest.approx({"AAA": 100.0, "BBB": 300.0}, abs=0.02)


def test_add_market_cap_splits_by_cap_and_holds_a_missing_one() -> None:
    caps = {"AAA": 3e11, "BBB": 1e11, "CCC": None}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000, "CCC": 1000}, {}, cash=400, amount=400,
                                                 weighting="market_cap", market_caps=caps))
    assert _rb_trades(out) == pytest.approx({"AAA": 300.0, "BBB": 100.0}, abs=0.02)
    assert "NO_MARKET_CAP" in {f["code"] for f in out["flags"]}


def test_add_market_cap_with_no_caps_is_bad_input() -> None:
    with pytest.raises(ValueError, match="market_cap"):
        load_script(SL).run_sleeves(_rb_params({"AAA": 1000}, {}, cash=400, amount=400, weighting="market_cap", market_caps={}))


def test_add_valuation_ignores_current_size() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 8000}, {"AAA": _GOOD, "BBB": _GOOD}, cash=1000, amount=1000))
    assert _rb_trades(out) == pytest.approx({"AAA": 500.0, "BBB": 500.0}, abs=0.02)


def test_add_never_sells_an_overvalued_pick() -> None:
    picks = {"AAA": _GOOD, "BBB": _deep(central=30.0, er=0.02)}             # BBB priced 50, well above central
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 2000}, picks, cash=1000, amount=1000))
    assert all(t["side"] == "BUY" for t in out["trades"])
    assert 0 < _rb_trades(out)["BBB"] < _rb_trades(out)["AAA"]


def test_add_valuation_no_eligible_splits_equal_and_says_so() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 3000}, {}, cash=400, amount=400))
    assert _rb_trades(out) == pytest.approx({"AAA": 200.0, "BBB": 200.0}, abs=0.02)
    assert out["weighting_used"] == "equal"
    assert "equal" in next(f["message"] for f in out["flags"] if f["code"] == "VALUATION_FALLBACK")


def test_add_cap_limits_buys_and_overflow_goes_to_others() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 14800, "BBB": 2000}, {}, cash=1000, core=283000, amount=1000, weighting="equal"))
    assert _rb_trades(out) == pytest.approx({"AAA": 240.0, "BBB": 760.0}, abs=0.02)        # total 300800, cap 15040


@pytest.mark.parametrize("name", ["equal", "market_cap", "valuation", "size"])
def test_add_holds_a_pick_due_for_recheck_under_every_strategy(name) -> None:
    picks = {"AAA": _deep(central=150.0, er=0.2, recheck_due=True), "BBB": _GOOD}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000}, picks, cash=400, amount=400, weighting=name,
                                                 market_caps={"AAA": 1e11, "BBB": 1e11}))
    assert _rb_trades(out) == pytest.approx({"BBB": 400.0}, abs=0.02)
    assert "HELD_FOR_RECHECK" in {f["code"] for f in out["flags"]}


@pytest.mark.parametrize("name", ["equal", "valuation"])
def test_new_pick_opens_at_median_and_touches_nothing_else(name) -> None:
    picks = {"NEW": _GOOD, "AAA": _GOOD, "BBB": _FAIR, "CCC": _FAIR}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 2000, "CCC": 6000}, picks, cash=5000, mode="new-pick",
                                                 weighting=name, new_pick={"symbol": "NEW", "price": 40.0}))
    assert _rb_trades(out) == pytest.approx({"NEW": 2000.0}, abs=0.02)
    assert out["new_pick"]["needed"] == 2000.0 and "valuation_multiplier" not in out["new_pick"]


def test_new_pick_amount_sends_the_rest_to_existing_picks() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 2000, "CCC": 2000}, {}, cash=5000, mode="new-pick", weighting="equal",
                                                 new_pick={"symbol": "NEW", "price": 40.0, "amount": 2300}))
    assert _rb_trades(out) == pytest.approx({"NEW": 2000.0, "AAA": 100.0, "BBB": 100.0, "CCC": 100.0}, abs=0.02)


def test_new_pick_capped_at_five_percent() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 8000, "BBB": 8000}, {}, cash=9000, core=75000, mode="new-pick", weighting="equal",
                                                 new_pick={"symbol": "NEW", "price": 40.0}))
    assert out["new_pick"]["needed"] == 5000.0                              # total 100000


@pytest.mark.parametrize("extra,code", [({"recheck_due": True}, "RECHECK_DUE"),
                                        ({"recheck_due": True, "needs_valuation": True}, "DEEP_VALUATION_NEEDED")])
def test_new_pick_with_open_question_still_opens_and_flags(extra, code) -> None:
    picks = {"NEW": {**_GOOD, **extra}}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000}, picks, cash=5000, mode="new-pick", new_pick={"symbol": "NEW", "price": 40.0}))
    assert _rb_trades(out) == pytest.approx({"NEW": 2000.0}, abs=0.02)
    assert code in {f["code"] for f in out["flags"]}


def test_add_holds_an_unreadable_pick() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000}, {}, cash=400, amount=400, weighting="equal", unreadable_picks=["BBB"]))
    assert _rb_trades(out) == pytest.approx({"AAA": 400.0}, abs=0.02)


def test_add_output_drops_the_rebalance_fields() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000}, {"AAA": _GOOD}, cash=400, amount=400, rebalance=False, same_size=False))
    assert set(out["splits"][0]) == {"symbol", "current", "target", "delta", "account", "flags"}
    assert out["splits"][0]["target"] == pytest.approx(1400.0, abs=0.02)
    assert not {"rebalance", "same_size"} & set(out["settings_used"]) and out["weighting_used"] == "valuation"


def test_valuation_flags_only_under_valuation() -> None:
    picks = {"AAA": _light(), "BBB": _deep(central=60.0, er=0.1, age_days=None)}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000}, picks, cash=400, amount=400, weighting="equal"))
    assert not {"LIGHT_VALUATION", "RECHECK_DUE", "NO_SAVED_VALUATION", "VALUATION_FALLBACK"} & {f["code"] for f in out["flags"]}


def test_mix_raises_no_valuation_fallback() -> None:
    assert "VALUATION_FALLBACK" not in {f["code"] for f in load_script(SL).run_sleeves(_rb_params({"AAA": 1000}, {}, mode="mix"))["flags"]}


# --- rebalance: its own mode, sells fund buys in the same account ---------------------------------

def _rb_mode(sat, picks=None, **over):
    return load_script(SL).run_sleeves(_rb_params(sat, picks or {}, mode="rebalance", **{"weighting": "equal", **over}))


def test_rebalance_in_band_picks_receive_proceeds() -> None:
    sat = {"AAA": 9000, **{f"S{i}": 3500 for i in range(10)}}
    out = _rb_mode(sat, cash=1000)
    assert _rb_trades(out) == pytest.approx({"AAA": -5000.0, **{f"S{i}": 500.0 for i in range(10)}}, abs=0.02)
    assert out["satellite_net"] == pytest.approx(0.0, abs=0.02)
    assert out["accounts"][0]["funding"]["cash"] == pytest.approx(0.0, abs=0.02)
    assert out["accounts"][0]["funding"]["core_sells"] == pytest.approx(0.0, abs=0.02)


def test_rebalance_is_idempotent() -> None:
    assert _rb_mode({"AAA": 4000, "BBB": 4000})["trades"] == []


@pytest.mark.parametrize("over", [{"weighting": "equal"},
                                  {"weighting": "valuation", "picks": {"AAA": _GOOD, "BBB": _GOOD}}])
def test_rebalance_trims_a_large_pick_that_is_not_overvalued(over) -> None:
    over = dict(over)
    picks = over.pop("picks", {})
    out = _rb_mode({"AAA": 30000, "BBB": 10000}, picks, core=460000, **over)        # total 500000, cap 25000
    assert _rb_trades(out) == pytest.approx({"AAA": -10000.0, "BBB": 10000.0}, abs=0.02)


def test_rebalance_cap_limits_targets_and_trims_go_no_further_than_others_take() -> None:
    out = _rb_mode({"AAA": 30000, "BBB": 1000, "CCC": 1000}, core=68000)            # total 100000, cap 5000
    assert _rb_trades(out) == pytest.approx({"AAA": -8000.0, "BBB": 4000.0, "CCC": 4000.0}, abs=0.02)


def test_rebalance_market_cap() -> None:
    out = _rb_mode({"AAA": 20000, "BBB": 20000}, core=1000000, weighting="market_cap", market_caps={"AAA": 3e11, "BBB": 1e11})
    assert _rb_trades(out) == pytest.approx({"AAA": 10000.0, "BBB": -10000.0}, abs=0.02)


def test_rebalance_unvalued_pick_gets_neutral_weight_and_can_trade() -> None:
    out = _rb_mode({"AAA": 2000, "BBB": 10000}, {"AAA": _FAIR}, weighting="valuation")
    assert _rb_trades(out)["BBB"] < 0


def test_rebalance_holds_recheck_unreadable_and_missing_cap() -> None:
    picks = {"HLD": _deep(central=150.0, er=0.2, recheck_due=True)}
    out = _rb_mode({"HLD": 9000, "BAD": 9000, "AAA": 1000, "BBB": 7000}, picks, unreadable_picks=["BAD"])
    assert not {"HLD", "BAD"} & set(_rb_trades(out))
    assert _rb_trades(out) == pytest.approx({"AAA": 3000.0, "BBB": -3000.0}, abs=0.02)
    out = _rb_mode({"AAA": 1000, "BBB": 7000, "CCC": 9000}, weighting="market_cap", market_caps={"AAA": 1e11, "BBB": 1e11})
    assert "CCC" not in _rb_trades(out) and "NO_MARKET_CAP" in {f["code"] for f in out["flags"]}


def test_rebalance_respects_short_term_hold() -> None:
    sat = {"AAA": 10000, "BBB": 2000}
    p = _rb_params(sat, {}, mode="rebalance", weighting="equal", settings={**_RB_SETTINGS, "short_term_gain_policy": "hold"},
                   lots={"AAA": [{"units": 200, "cost_per_unit": 10.0, "term": "short", "acquired": "2026-06-01", "account": "t1"}]})
    out = load_script(SL).run_sleeves(p)
    assert "AAA" not in _rb_trades(out) and "TRIM_HELD_BACK" in {f["code"] for f in out["flags"]}


@pytest.mark.parametrize("over,match", [
    ({"weighting": "size"}, "equal, market_cap or valuation"),
    ({"sell_first": ["VTI"]}, "sell"),
    ({"over_ceiling": True}, "over_ceiling"),
    ({"weighting": "valuation"}, "eligible"),                                # no pick has a valuation
    ({"pick_store_unreadable": True}, "pick store"),
    ({"weighting": "market_cap", "market_caps": {}}, "market_cap"),
])
def test_rebalance_bad_input(over, match) -> None:
    with pytest.raises(ValueError, match=match):
        _rb_mode({"AAA": 1000, "BBB": 5000}, **over)


def test_add_and_mix_still_work_with_saved_size() -> None:
    p = _rb_params({"AAA": 1000, "BBB": 3000}, {}, cash=400, amount=400, settings={**_RB_SETTINGS, "weighting": "size"})
    assert _rb_trades(load_script(SL).run_sleeves(p)) == pytest.approx({"AAA": 100.0, "BBB": 300.0}, abs=0.02)
    assert load_script(SL).run_sleeves({**p, "mode": "mix"})["trades"] == []


@pytest.mark.parametrize("sat", [{}, {"AAA": 5000}])
def test_rebalance_one_pick_or_none_has_no_trades(sat) -> None:
    assert _rb_mode(sat)["trades"] == []


def test_rebalance_whole_shares_spend_no_more_than_proceeds() -> None:
    out = _rb_mode({"AAA": 10025, "BBB": 1010, "CCC": 1030}, cash=500, whole_shares=True)
    assert all(float(t["units"]).is_integer() for t in out["trades"])
    bought = sum(t["value"] for t in out["trades"] if t["side"] == "BUY")
    sold = sum(t["value"] for t in out["trades"] if t["side"] == "SELL")
    assert sold > 0 and bought <= sold + 0.01


def test_rebalance_whole_shares_do_not_sell_what_rounded_buys_leave() -> None:
    out = _rb_mode({"AAA": 10025, "BBB": 1010, "CCC": 1030}, cash=500, whole_shares=True)   # targets 4021.67
    assert _rb_trades(out) == pytest.approx({"AAA": -5950.0, "BBB": 3000.0, "CCC": 2950.0}, abs=0.02)
    assert out["satellite_net"] == 0.0 and out["unallocated_amount"] == 0.0


def test_rebalance_overflow_skips_an_overvalued_pick_and_splits_show_targets() -> None:
    picks = {"AAA": _GOOD, "BBB": _deep(central=30.0, er=0.02)}             # BBB priced 50, well above central
    out = _rb_mode({"AAA": 5000, "BBB": 1000}, picks, core=54000, weighting="valuation")    # total 60000, cap 3000
    split = {r["symbol"]: r for r in out["splits"]}
    assert split["AAA"]["target"] == 3000.0 and "PICK_CAP" in split["AAA"]["flags"]
    assert split["BBB"]["target"] < 2000.0                                  # its own share, not AAA's overflow
    assert _rb_trades(out)["BBB"] == pytest.approx(split["BBB"]["target"] - 1000.0, abs=0.02)


def test_rebalance_across_accounts_leaves_no_proceeds_as_cash() -> None:
    positions = [{"symbol": "AAA", "units": 200, "price": 50.0, "account": "t1", "bucket": "satellite"},
                 {"symbol": "BBB", "units": 20, "price": 50.0, "account": "t2", "bucket": "satellite"},
                 _pos("VTI", 3000, "t1", "core"), _pos("VTI", 3000, "t2", "core")]
    p = _rb_params({}, {}, mode="rebalance", weighting="equal", positions=positions,
                   accounts={"t1": {"role": "trading"}, "t2": {"role": "trading"}}, cash_by_account={"t1": 0.0, "t2": 0.0})
    assert load_script(SL).run_sleeves(p)["trades"] == []                    # t1's proceeds cannot buy BBB in t2


def _split_params(**over) -> dict:
    p = _rb_params({"AAA": 1000}, {}, cash=100, mode="rebalance", weighting="equal", **over)
    p["accounts"]["t2"] = {"role": "trading"}
    p["cash_by_account"]["t2"] = 0.0
    p["positions"] += [{"symbol": "BBB", "units": 40, "price": 50.0, "account": "t1", "bucket": "satellite"},
                       {"symbol": "BBB", "units": 80, "price": 50.0, "account": "t2", "bucket": "satellite"}]
    return p


@pytest.mark.parametrize("over", [{}, {"whole_shares": True}])
def test_rebalance_split_pick_trims_where_the_buys_land(over) -> None:
    out = load_script(SL).run_sleeves(_split_params(**over))        # targets 3500: BBB 6000 (t1 2000, t2 4000), AAA 1000 in t1
    signed = {(t["account"], t["symbol"]): t["value"] if t["side"] == "BUY" else -t["value"] for t in out["trades"]}
    assert signed == pytest.approx({("t1", "BBB"): -2000.0, ("t1", "AAA"): 2000.0}, abs=0.02)


def test_rebalance_two_accounts_with_cap_binding_sells_all_at_once() -> None:
    positions = [_pos("VTI", 770, "t1", "core"),                            # total 100000, cap 5000
                 {"symbol": "AAA", "units": 20, "price": 50.0, "account": "t1", "bucket": "satellite"},
                 {"symbol": "BBB", "units": 220, "price": 50.0, "account": "t1", "bucket": "satellite"},
                 {"symbol": "CCC", "units": 220, "price": 50.0, "account": "t2", "bucket": "satellite"}]
    p = _rb_params({}, {}, mode="rebalance", weighting="equal", positions=positions,
                   accounts={"t1": {"role": "trading"}, "t2": {"role": "trading"}}, cash_by_account={"t1": 0.0, "t2": 0.0})
    sl = load_script(SL)
    assert _rb_trades(sl.run_sleeves(p)) == pytest.approx({"AAA": 4000.0, "BBB": -4000.0}, abs=0.02)
    assert sl.run_sleeves(_after_trades(p, sl.run_sleeves(p)))["trades"] == []


def test_rebalance_proceeds_go_furthest_below_target_first() -> None:
    caps = {"SEL": 1e11, "BIG": 1e12, "SML": 1e11}                          # targets 1000, 10000, 1000
    lots = {"SEL": [{"units": 12, "cost_per_unit": 10.0, "term": "long", "account": "t1"},
                    {"units": 38, "cost_per_unit": 10.0, "term": "short", "acquired": "2026-06-01", "account": "t1"}]}
    p = _rb_params({"SEL": 2500, "BIG": 9000, "SML": 500}, {}, mode="rebalance", weighting="market_cap", market_caps=caps,
                   lots=lots, settings={**_RB_SETTINGS, "short_term_gain_policy": "hold"})
    out = load_script(SL).run_sleeves(p)                                    # only 600 of SEL may sell; BIG is 1000 short, SML 500
    assert _rb_trades(out) == pytest.approx({"SEL": -600.0, "BIG": 600.0}, abs=0.02)


def test_in_band_only_for_a_pick_inside_its_band() -> None:
    def flags(out: dict, sym: str) -> list[str]:
        return next(r["flags"] for r in out["splits"] if r["symbol"] == sym)
    out = _rb_mode({"AAA": 4200, "BBB": 3800})                              # targets 4000, band 1000
    assert out["trades"] == [] and "IN_BAND" in flags(out, "AAA") and "IN_BAND" in flags(out, "BBB")
    out = _rb_mode({"AAA": 22000, "BBB": 5000, "CCC": 5000}, core=68000)    # AAA target 5000, nothing can take its proceeds
    assert out["trades"] == [] and "IN_BAND" not in flags(out, "AAA")


def _split_flags(out: dict, sym: str) -> list[str]:
    return next(r["flags"] for r in out["splits"] if r["symbol"] == sym)


def _flag_message(out: dict, code: str, sym: str) -> str:
    return next(f["message"] for f in out["flags"] if f["code"] == code and sym in f["message"])


def _two_account_params(**over) -> dict:
    positions = [{"symbol": "AAA", "units": 200, "price": 50.0, "account": "t1", "bucket": "satellite"},
                 {"symbol": "BBB", "units": 20, "price": 50.0, "account": "t2", "bucket": "satellite"},
                 _pos("VTI", 3000, "t1", "core"), _pos("VTI", 3000, "t2", "core")]
    return _rb_params({}, {}, mode="rebalance", weighting="equal", positions=positions,
                      accounts={"t1": {"role": "trading"}, "t2": {"role": "trading"}},
                      cash_by_account={"t1": 0.0, "t2": 0.0}, **over)


def test_rebalance_says_when_no_pick_in_the_account_can_take_the_proceeds() -> None:
    out = load_script(SL).run_sleeves(_two_account_params())                 # AAA in t1 over, BBB in t2 under
    assert out["trades"] == []
    assert "TRIM_UNPLACEABLE" in _split_flags(out, "AAA") and "TRIM_UNPLACEABLE" not in _split_flags(out, "BBB")
    assert "no pick below target in its account" in _flag_message(out, "TRIM_UNPLACEABLE", "AAA")


def test_rebalance_says_when_every_other_pick_is_at_its_cap() -> None:
    out = _rb_mode({"AAA": 22000, "BBB": 5000, "CCC": 5000}, core=68000)     # total 100000, cap 5000
    assert out["trades"] == []
    assert {"PICK_CAP", "TRIM_UNPLACEABLE"} <= set(_split_flags(out, "AAA"))
    assert "TRIM_UNPLACEABLE" not in _split_flags(out, "BBB") + _split_flags(out, "CCC")
    assert "17000.00" in _flag_message(out, "TRIM_UNPLACEABLE", "AAA")


_BLOCKED_AAA = {"AAA": [{"units": 200, "cost_per_unit": 10.0, "term": "short", "acquired": "2026-06-01", "account": "t1"}],
                "BBB": [{"units": 200, "cost_per_unit": 10.0, "term": "long", "account": "t1"}]}


@pytest.mark.parametrize("policy", ["hold", None])
def test_rebalance_says_when_a_blocked_seller_is_passed_over(policy) -> None:
    p = _rb_params({"AAA": 10000, "BBB": 10000, "CCC": 3000}, {}, core=77000, mode="rebalance", weighting="equal",
                   lots=_BLOCKED_AAA, settings={**_RB_SETTINGS, "short_term_gain_policy": policy})
    out = load_script(SL).run_sleeves(p)                                     # cap 5000; CCC takes 2000, BBB alone can give it
    assert _rb_trades(out) == pytest.approx({"BBB": -2000.0, "CCC": 2000.0}, abs=0.02)
    assert {"TRIM_HELD_BACK", "TRIM_UNPLACEABLE"} <= set(_split_flags(out, "AAA"))
    assert "TRIM_HELD_BACK" not in _split_flags(out, "BBB") and "TRIM_UNPLACEABLE" in _split_flags(out, "BBB")
    assert out["held_back"] == [{"symbol": "AAA", "value": 1000.0, "account": "t1", "long_term_date": "2027-06-02"}]
    assert "AAA" in _flag_message(out, "TRIM_HELD_BACK", "AAA")
    needed = [f["message"] for f in out["flags"] if f["code"] == "DECISION_NEEDED" and "short_term_gain_policy" in f["message"]]
    assert len(needed) == (1 if policy is None else 0)


def test_rebalance_held_back_counts_only_what_a_buy_could_take() -> None:
    lots = {"AAA": _BLOCKED_AAA["AAA"]}                                      # AAA all short-term gains
    p = _rb_params({"AAA": 10000, "BBB": 1000}, {}, core=89000, mode="rebalance", weighting="equal", lots=lots,
                   settings={**_RB_SETTINGS, "short_term_gain_policy": "hold"})
    out = load_script(SL).run_sleeves(p)                                     # cap 5000; AAA 5000 over, BBB takes 4000
    assert out["trades"] == [] and sum(r["value"] for r in out["held_back"]) == pytest.approx(4000.0, abs=0.02)
    assert "1000.00" in _flag_message(out, "TRIM_UNPLACEABLE", "AAA")


@pytest.mark.parametrize("sat,core", [({"AAA": 9000, **{f"S{i}": 3500 for i in range(10)}}, 300000),
                                      ({"AAA": 30000, "BBB": 10000}, 460000)])
def test_rebalance_full_trim_raises_no_trim_flag(sat, core) -> None:
    out = _rb_mode(sat, core=core)
    assert out["trades"] and "TRIM_UNPLACEABLE" not in {f["code"] for f in out["flags"]}
    assert not any("TRIM_UNPLACEABLE" in r["flags"] for r in out["splits"]) and out["held_back"] == []


def test_rebalance_whole_share_rounding_alone_raises_no_trim_flag() -> None:
    out = _rb_mode({"AAA": 10025, "BBB": 1010, "CCC": 1030}, cash=500, whole_shares=True)   # 53.33 of AAA's excess stays
    assert out["trades"] and "TRIM_UNPLACEABLE" not in {f["code"] for f in out["flags"]}


def test_rebalance_whole_shares_says_when_no_share_can_be_bought() -> None:
    positions = [{"symbol": "AAA", "units": 180, "price": 50.0, "account": "t1", "bucket": "satellite"},
                 {"symbol": "BBB", "units": 1, "price": 5000.0, "account": "t1", "bucket": "satellite"},
                 _pos("VTI", 3000, "t1", "core")]
    p = _rb_params({}, {}, mode="rebalance", weighting="equal", positions=positions, whole_shares=True)
    out = load_script(SL).run_sleeves(p)                                     # targets 7000; BBB is 2000 short, a share is 5000
    assert out["trades"] == [] and "TRIM_UNPLACEABLE" in _split_flags(out, "AAA")


def test_rebalance_negative_cash_is_a_clear_error() -> None:
    p = _rb_params({"AAA": 10000, "BBB": 1000}, {}, cash=-500.0, mode="rebalance", weighting="equal")
    with pytest.raises(ValueError, match=r"account t1 .*-500\.00"):
        load_script(SL).run_sleeves(p)


def test_rebalance_negative_cash_in_an_account_with_no_trades_does_not_stop_the_others() -> None:
    p = _rb_params({"AAA": 10000, "BBB": 1000}, {}, mode="rebalance", weighting="equal")
    p["accounts"]["t2"] = {"role": "trading"}
    p["cash_by_account"]["t2"] = -500.0
    assert _rb_trades(load_script(SL).run_sleeves(p)) == pytest.approx({"AAA": -4500.0, "BBB": 4500.0}, abs=0.02)


@pytest.mark.parametrize("cap", [float("nan"), float("inf"), float("-inf")])
def test_add_market_cap_not_finite_holds_the_pick(cap) -> None:
    caps = {"AAA": cap, "BBB": 3e11, "CCC": 1e11}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000, "CCC": 1000}, {}, cash=400, amount=400,
                                                 weighting="market_cap", market_caps=caps))
    assert _rb_trades(out) == pytest.approx({"BBB": 300.0, "CCC": 100.0}, abs=0.02)
    assert "NO_MARKET_CAP" in _split_flags(out, "AAA") and "NaN" not in json.dumps(out) and "Infinity" not in json.dumps(out)


@pytest.mark.parametrize("cap", [float("nan"), float("inf"), float("-inf")])
def test_rebalance_market_cap_not_finite_holds_the_pick(cap) -> None:
    out = _rb_mode({"AAA": 9000, "BBB": 7000, "CCC": 1000}, weighting="market_cap", market_caps={"AAA": cap, "BBB": 1e11, "CCC": 1e11})
    assert _rb_trades(out) == pytest.approx({"BBB": -3000.0, "CCC": 3000.0}, abs=0.02)
    assert "NO_MARKET_CAP" in _split_flags(out, "AAA") and "NaN" not in json.dumps(out) and "Infinity" not in json.dumps(out)


@pytest.mark.parametrize("cap", [float("nan"), float("inf")])
def test_market_cap_with_no_finite_cap_is_bad_input(cap) -> None:
    with pytest.raises(ValueError, match="market_cap"):
        _rb_mode({"AAA": 1000, "BBB": 5000}, weighting="market_cap", market_caps={"AAA": cap, "BBB": cap})


def test_market_cap_error_is_about_the_picks_that_can_take_money() -> None:
    picks = {"AAA": _deep(central=150.0, er=0.2, recheck_due=True)}          # AAA's cap is readable, but AAA holds
    with pytest.raises(ValueError, match="no pick that can take money has a market cap"):
        load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000}, picks, cash=400, amount=400, weighting="market_cap",
                                               market_caps={"AAA": 1e11, "BBB": None}))


@pytest.mark.parametrize("weighting", ["equal", "market_cap", "size", "valuation"])
def test_add_unreadable_pick_says_so_on_its_split_row(weighting) -> None:
    picks = {"AAA": _GOOD, "BBB": _GOOD}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000, "BAD": 1000}, picks, cash=400, amount=400, weighting=weighting,
                                                 market_caps={"AAA": 1e11, "BBB": 1e11, "BAD": 1e11}, unreadable_picks=["BAD"]))
    row = next(r for r in out["splits"] if r["symbol"] == "BAD")
    assert row["delta"] == 0.0 and "PICK_BASELINE_MISSING" in row["flags"]
    assert "PICK_BASELINE_MISSING" not in _split_flags(out, "AAA")


def test_rebalance_unreadable_pick_says_so_on_its_split_row() -> None:
    out = _rb_mode({"BAD": 9000, "AAA": 1000, "BBB": 7000}, unreadable_picks=["BAD"])
    assert "PICK_BASELINE_MISSING" in _split_flags(out, "BAD") and "BAD" not in _rb_trades(out)


def test_rebalance_whole_shares_report_the_idle_remainder() -> None:
    positions = [{"symbol": "AAA", "units": 50, "price": 120.0, "account": "t1", "bucket": "satellite"},
                 {"symbol": "BBB", "units": 15, "price": 70.0, "account": "t1", "bucket": "satellite"},
                 _pos("VTI", 3000, "t1", "core")]
    p = _rb_params({}, {}, mode="rebalance", weighting="equal", positions=positions, whole_shares=True)
    out = load_script(SL).run_sleeves(p)                                     # sells 20 x 120 = 2400, buys 34 x 70 = 2380
    assert _rb_trades(out) == pytest.approx({"AAA": -2400.0, "BBB": 2380.0}, abs=0.02)
    assert out["unallocated_amount"] == pytest.approx(20.0, abs=0.02) and out["satellite_net"] == pytest.approx(-20.0, abs=0.02)
    assert "20.00" in next(f["message"] for f in out["flags"] if f["code"] == "UNALLOCATED")


def _after_trades(p: dict, out: dict) -> dict:
    """``p`` with ``out``'s trades applied to its positions, and sold units taken off the lots that may sell."""
    q = json.loads(json.dumps(p))
    for t in out["trades"]:
        row = next(x for x in q["positions"] if x["symbol"] == t["symbol"] and x["account"] == t["account"])
        row["units"] += t["units"] if t["side"] == "BUY" else -t["units"]
        left = t["units"] if t["side"] == "SELL" else 0.0
        for lot in q["lots"].get(t["symbol"]) or []:
            if lot.get("account") in (None, t["account"]) and (lot["cost_per_unit"] >= t["price"] or lot["term"] == "long"):
                take = min(lot["units"], left)
                lot["units"] -= take
                left -= take
    return q


@pytest.mark.parametrize("units", [1.123446, 1.123456])                     # 4 dp rounding: 1.1234, 1.1235
def test_rebalance_sold_out_account_leaves_no_residual_trades(units) -> None:
    positions = [{"symbol": "SEL", "units": units, "price": 400.0, "account": "t1", "bucket": "satellite"},
                 {"symbol": "SEL", "units": 100, "price": 400.0, "account": "t2", "bucket": "satellite"},
                 {"symbol": "BUY", "units": 1, "price": 100.0, "account": "t1", "bucket": "satellite"},
                 _pos("VTI", 5000, "t1", "core"), _pos("VTI", 5000, "t2", "core")]
    p = _rb_params({}, {}, mode="rebalance", weighting="equal", positions=positions,
                   accounts={"t1": {"role": "trading"}, "t2": {"role": "trading"}}, cash_by_account={"t1": 0.0, "t2": 0.0})
    sl = load_script(SL)
    out = sl.run_sleeves(p)
    sale = next(t for t in out["trades"] if t["side"] == "SELL")
    assert sale["symbol"] == "SEL" and sale["account"] == "t1" and sale["units"] == 1.1234     # never above what is held
    assert _rb_trades(out) == pytest.approx({"SEL": -449.36, "BUY": 449.36}, abs=0.03)
    assert sl.run_sleeves(_after_trades(p, out))["trades"] == []


def _fuzz_rebalance_case(rng) -> dict:
    """A ``_fuzz_case`` as a rebalance, with some picks priced above $300 and some units to 6 dp."""
    p = _fuzz_case(rng)
    p["mode"] = "rebalance"
    p["settings"]["weighting"] = rng.choice(["equal", "market_cap", "valuation"])
    scale = {x["symbol"]: rng.uniform(2, 15) if rng.random() < 0.3 else 1.0 for x in p["positions"] if x["bucket"] == "satellite"}
    for x in p["positions"]:
        if x["bucket"] == "satellite":
            x["price"] *= scale[x["symbol"]]
            if rng.random() < 0.4:
                x["units"] = round(rng.choice([rng.uniform(0.5, 3), x["units"] + rng.random()]), 6)
    for sym, k in scale.items():
        for lot in p["lots"].get(sym) or []:
            lot["cost_per_unit"] *= k
        if sym in p["picks"]:
            p["picks"][sym]["central_value"] *= k
    return p


def test_randomized_rebalances_keep_the_money_invariants() -> None:
    import random
    sl = load_script(SL)
    rng = random.Random(20261030)
    checked, traded, failures = 0, 0, []
    for i in range(300):
        p = _fuzz_rebalance_case(rng)
        try:
            out = sl.run_sleeves(p)
        except ValueError as exc:                    # valuation with no eligible pick, no market caps at all
            assert "eligible" in str(exc) or "market_cap" in str(exc)
            continue
        checked += 1
        traded += bool(out["trades"])
        errs, by_acct = [], {}
        for t in out["trades"]:
            side = by_acct.setdefault(t["account"], {"BUY": 0.0, "SELL": 0.0})
            side[t["side"]] += t["value"]
            pick = p["picks"].get(t["symbol"]) or {}
            if t["units"] == 0:
                errs.append(f"{t['side']} {t['symbol']} for 0 units, value {t['value']}")
            held = sum(x["units"] for x in p["positions"] if x["symbol"] == t["symbol"] and x["account"] == t["account"])
            if t["side"] == "SELL" and t["units"] > held + 1e-9:
                errs.append(f"{t['symbol']} sells {t['units']} units with {held} held in {t['account']}")
            if t["symbol"] in _CORE_SYMS:
                errs.append(f"core fund {t['symbol']} traded")
            if pick and (pick.get("recheck_due") or pick.get("age_days") is None):
                errs.append(f"pick {t['symbol']} traded though held for its recheck")
        errs += [f"account {a} buys {v['BUY']:.2f} with {v['SELL']:.2f} of sells"
                 for a, v in by_acct.items() if v["BUY"] > v["SELL"] + 0.01]
        slack = 0.01 * len(out["trades"])
        if out["satellite_net"] > slack or (not p["whole_shares"] and out["satellite_net"] < -slack):
            errs.append(f"satellite_net {out['satellite_net']:.2f}")        # whole shares can leave under one unit as cash
        if not p["whole_shares"] and out["trades"]:
            again = sl.run_sleeves(_after_trades(p, out))["trades"]
            if again:
                errs.append(f"second run trades {[(t['symbol'], t['side'], t['value']) for t in again][:3]}")
        if not p["whole_shares"]:                    # a pick left out of its band says why
            for r in out["splits"]:
                unsold = r["current"] + r["delta"] - r["target"]
                if (r["current"] - r["target"] >= 250.0 + 0.01 and r["current"] - r["target"] >= 0.25 * r["target"] + 0.01 and unsold > 1.0
                        and not {"HELD_FOR_RECHECK", "DEEP_VALUATION_NEEDED", "NO_MARKET_CAP", "TRIM_UNPLACEABLE", "TRIM_HELD_BACK"} & set(r["flags"])):
                    errs.append(f"{r['symbol']} stays {unsold:.2f} above its target with no reason")
        if errs:
            failures.append((i, errs[:3]))
    assert checked >= 150 and traded >= 30, (checked, traded)
    assert not failures, failures[:5]
