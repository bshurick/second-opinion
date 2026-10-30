from __future__ import annotations

import json
from datetime import date

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import PLUGIN_ROOT, load_script, run_json
from second_opinion import client, market, profile
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


def test_valuation_tilts_toward_higher_return_and_trims_overvalued() -> None:
    w = load_script(W)
    out = w.valuation_targets(PICKS, target_total=4000, portfolio_total=100000)
    t = out["targets"]
    assert t["C"] == pytest.approx(800.0)          # trimmed to 40/50 of its value
    assert t["A"] > t["B"] >= 1000.0               # top end gets more, B not cut
    assert sum(t.values()) == pytest.approx(4000.0)
    assert out["fallback"] is False and out["capped"] == []
    assert out["scores"]["A"] > out["scores"]["B"] > out["scores"]["C"]


def test_valuation_respects_pick_cap() -> None:
    w = load_script(W)
    out = w.valuation_targets(PICKS, target_total=4000, portfolio_total=30000)
    t = out["targets"]
    assert t["A"] == 1500.0
    assert "A" in out["capped"]
    assert all(v <= 1500.0 or k == "C" for k, v in t.items())
    # C is fixed and overvalued, so it never takes excess; B also hits the cap
    # and the remainder stays unallocated for the caller to flag.
    assert sum(t.values()) <= 4000.0


def test_valuation_fallback_and_ineligible() -> None:
    w = load_script(W)
    picks = [dict(p, eligible=False) for p in PICKS]
    out = w.valuation_targets(picks, target_total=4500, portfolio_total=100000)
    assert out["fallback"] is True and out["capped"] == []
    assert out["targets"] == {"A": 1500.0, "B": 1500.0, "C": 1500.0}
    mixed = [dict(PICKS[0]), dict(PICKS[1], confidence=0.0)]
    out = w.valuation_targets(mixed, target_total=2500, portfolio_total=100000)
    assert out["scores"]["B"] is None
    assert out["targets"]["B"] >= 1000.0
    assert sum(out["targets"].values()) == pytest.approx(2500.0)


def test_valuation_cap_never_trims_a_pick_that_is_not_overvalued() -> None:
    w = load_script(W)
    picks = [dict(PICKS[0], value=2000), dict(PICKS[1])]
    out = w.valuation_targets(picks, target_total=3500, portfolio_total=30000)   # cap 1500
    assert out["targets"]["A"] >= 2000.0
    assert "A" in out["capped"]


def test_valuation_tilt_is_absolute_not_standardised() -> None:
    w = load_script(W)
    base = {"value": 1000, "price": 50, "central_value": 80, "eligible": True}
    near = [dict(base, symbol="A", expected_return=0.101, confidence=0.1),
            dict(base, symbol="B", expected_return=0.100, confidence=0.1)]
    t = w.valuation_targets(near, target_total=3000, portfolio_total=100000)["targets"]
    assert t["A"] == pytest.approx(1500.0, abs=1.0) and t["B"] == pytest.approx(1500.0, abs=1.0)
    wide = [dict(base, symbol="A", expected_return=0.30, confidence=1.0),
            dict(base, symbol="B", expected_return=0.07, confidence=1.0)]
    t = w.valuation_targets(wide, target_total=3000, portfolio_total=100000)["targets"]
    assert t["A"] == pytest.approx(3000 * 1575 / 2575, abs=0.01)     # raw 1000 x (1 + 0.5 x 0.115 / 0.10)
    assert t["A"] / t["B"] > 1.5


def test_valuation_excess_goes_to_picks_with_positive_score() -> None:
    w = load_script(W)
    base = {"value": 1000, "price": 50, "central_value": 80, "eligible": True, "confidence": 1.0}
    picks = [dict(base, symbol="A", expected_return=0.30), dict(base, symbol="B", expected_return=0.08),
             dict(base, symbol="C", expected_return=0.07)]
    t = w.valuation_targets(picks, target_total=3900, portfolio_total=30000)["targets"]   # cap 1500
    assert t["A"] == 1500.0
    assert t["C"] == pytest.approx(3900 * 1000 / 3600, abs=0.01)     # a_C = 0 takes none of A's excess


def test_overvalued_trim_scales_with_confidence_and_needs_a_gap() -> None:
    w = load_script(W)
    assert w.TRIM_MIN_GAP == 0.05
    base = {"value": 1000, "price": 50, "expected_return": 0.07, "eligible": True}
    picks = [dict(base, symbol="A", central_value=40, confidence=0.5),     # 25% above central
             dict(base, symbol="B", central_value=48, confidence=1.0)]     # 4.2% above: not overvalued
    t = w.valuation_targets(picks, target_total=2000, portfolio_total=100000)["targets"]
    assert t["A"] == pytest.approx(900.0)                               # 1000 x (1 - 0.5 x (1 - 40/50))
    assert t["B"] >= 1000.0


S = "core-satellite/scripts/settings.py"


def test_decide_records_and_validates(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = run_json(load_script(S), ["decide", "ceiling", "0.15"], capsys)
    assert rc == 0 and out["ceiling"] == 0.15 and out["decisions"][-1]["key"] == "ceiling"
    rc, out = run_json(load_script(S), ["decide", "weighting", "kelly"], capsys)
    assert rc == 2 and "size" in out["error"]


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
        "settings": {},
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


def test_valuation_mode_tilts_and_trims() -> None:
    p = _params(rebalance=False, mode="add", amount=1000, weighting="valuation", settings={"short_term_gain_policy": "allow"},
                picks={"AAA": _deep(central=150, er=0.20), "BBB": _deep(central=40, er=0.02)})   # BBB price 50 -> overvalued
    out = load_script(SL).run_sleeves(p)
    sides = {(t["symbol"], t["side"]) for t in out["trades"]}
    assert ("BBB", "SELL") in sides and ("AAA", "BUY") in sides
    assert out["weighting_used"] == "valuation"


def test_overvalued_short_term_lots_are_held_back() -> None:
    p = _params(rebalance=False, mode="add", amount=1000, weighting="valuation",
                picks={"AAA": _deep(central=150, er=0.20), "BBB": _deep(central=40, er=0.02)},
                lots={"BBB": [{"units": 20, "cost_per_unit": 30.0, "term": "short", "acquired": "2026-03-01", "account": "t1"},
                              {"units": 20, "cost_per_unit": 30.0, "term": "short", "acquired": "2026-03-01", "account": "t2"}]})
    # a larger retirement core holding (total 72000, pick cap 3600) so the cap does not bind on AAA
    p["positions"].append(_pos("VTI", 250, "r1", "core"))
    out = load_script(SL).run_sleeves(p)
    assert not any(t["symbol"] == "BBB" and t["side"] == "SELL" for t in out["trades"])
    assert out["held_back"][0]["long_term_date"] == "2027-03-02"
    assert {"TRIM_HELD_BACK", "DECISION_NEEDED"} <= {f["code"] for f in out["flags"]}
    assert any(f["code"] == "DECISION_NEEDED" and "short_term_gain_policy" in f["message"] for f in out["flags"])
    assert sum(t["value"] for t in out["trades"] if t["side"] == "BUY") == pytest.approx(1000.0, abs=0.01)


def test_valuation_with_no_eligible_picks_falls_back() -> None:
    p = _params(mode="add", amount=1000, weighting="valuation", picks={"AAA": _light(), "BBB": _deep(central=60, er=0.1, recheck_due=True)})
    out = load_script(SL).run_sleeves(p)
    assert out["weighting_used"] == "size"
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


def test_trim_takes_loss_lots_and_holds_short_term_gains() -> None:
    # BBB at age 0 has confidence 1, so its trim is the full 2000 x (1 - 40/50) = 400
    p = _params(rebalance=False, mode="add", amount=1000, weighting="valuation", settings={"short_term_gain_policy": "hold"},
                picks={"AAA": _deep(central=150, er=0.20), "BBB": _deep(central=40, er=0.02, age_days=0)},
                lots={"BBB": [{"units": 20, "cost_per_unit": 60.0, "term": "short", "acquired": "2026-06-01", "account": "t1"},
                              {"units": 20, "cost_per_unit": 30.0, "term": "short", "acquired": "2026-02-01", "account": "t2"}]})
    out = load_script(SL).run_sleeves(p)
    sells = {(t["symbol"], t["account"]): t["value"] for t in out["trades"] if t["side"] == "SELL"}
    assert sells == {("BBB", "t1"): 200.0}                      # loss lot in t1 sells; t2's gain lot is held
    assert out["held_back"] == [{"symbol": "BBB", "value": 200.0, "account": "t2", "long_term_date": "2027-02-02"}]
    assert not any(f["code"] == "DECISION_NEEDED" and "short_term_gain_policy" in f["message"] for f in out["flags"])
    assert load_script(SL)._long_term_date("2024-02-29") == "2025-03-01"


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


def test_whole_share_trim_never_passes_allowed_value_under_hold() -> None:
    p = _params(mode="add", amount=1000, weighting="valuation", whole_shares=True,
                settings={"short_term_gain_policy": "hold"},
                picks={"AAA": _deep(central=150, er=0.20), "BBB": _deep(central=40, er=0.02)},
                lots={"BBB": [{"units": 2.5, "cost_per_unit": 60.0, "term": "short", "acquired": "2026-06-01", "account": "t1"},
                              {"units": 20, "cost_per_unit": 30.0, "term": "short", "acquired": "2026-02-01", "account": "t1"},
                              {"units": 20, "cost_per_unit": 30.0, "term": "short", "acquired": "2026-02-01", "account": "t2"}]})
    sells = [t for t in load_script(SL).run_sleeves(p)["trades"] if t["symbol"] == "BBB" and t["side"] == "SELL"]
    assert sum(t["value"] for t in sells) <= 2.5 * 50.0                # only the loss lot is allowed
    assert all(lot["cost_per_unit"] == 60.0 for t in sells for lot in t["lots"])
    assert all(float(t["units"]).is_integer() for t in sells)


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
                                              settings={"ceiling": 0.25, "short_term_gain_policy": "allow"}))
    sells = [t for t in out["trades"] if t["side"] == "SELL"]
    assert sells and all(t["account"] in {"t1", "t2"} and t["symbol"] in {"VTI", "VXUS"} for t in sells)


def _bond_params(amount: float, core_rank: dict | None) -> dict:
    p = _params(mode="grow", grow={"amount": amount}, settings={"ceiling": 0.25, "short_term_gain_policy": "allow"},
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
    out = load_script(SL).run_sleeves(_params(mode="grow", grow={"amount": 6000}, settings={"ceiling": 0.25}))
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


def test_whole_share_valuation_trim_never_overspends() -> None:
    p = _pricey_etfs(_params(rebalance=False, mode="grow", grow={"amount": 1000}, whole_shares=True, weighting="valuation",
                             settings={"ceiling": 0.30, "short_term_gain_policy": "allow"},
                             picks={"AAA": _deep(central=150, er=0.20), "BBB": _deep(central=43, er=0.02)},
                             cash_by_account={"t1": 0.0, "t2": 0.0, "r1": 0.0}))
    p["positions"].append(_pos("VTI", 250, "r1", "core"))
    out = load_script(SL).run_sleeves(p)
    assert any(t["side"] == "SELL" and t["symbol"] == "BBB" for t in out["trades"])
    _assert_whole_share_cash(out, 1000)


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
    pick = load_script(R)._picks({"AAA": price, "BBB": 50.0}, "2026-10-29", flags)["AAA"]
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
    assert any(f["code"] == "PICK_STORE_UNREADABLE" for f in out["flags"]) and out["weighting_used"] == "size"


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
    grown = sl.run_sleeves(_params(mode="grow", grow={"amount": 4000}, settings={"short_term_gain_policy": "allow"}))
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
                "weighting": rng.choice(["size", "valuation"]), "employer_symbol": employer}
    mode = rng.choice(["add", "deposit", "grow", "new-pick", "plan-step"])
    p = {"mode": mode, "positions": pos, "accounts": accts, "cash_by_account": cash, "settings": settings,
         "picks": picks, "lots": lots, "today": "2026-10-29", "whole_shares": rng.random() < 0.4,
         "include_light": rng.random() < 0.3, "rates": {"short_term": 0.24, "long_term": 0.15},
         "core_rank": {s: r for s, r in _CORE_SYMS.items() if rng.random() < 0.8},
         "rebalance": rng.random() < 0.6}
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
        p["same_size"] = rng.random() < 0.5
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
        if (t["symbol"] in sat_syms and p["rebalance"] and p["settings"]["weighting"] == "valuation"
                and held and (held.get("recheck_due") or held.get("age_days") is None)):   # 6, rebalance
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
        rebalancing = p["rebalance"] and p["settings"]["weighting"] == "valuation"
        if t["symbol"] in sat_syms and rebalancing:                                     # 6, rebalance
            pk = p["picks"].get(t["symbol"]) or {}
            if pk and (pk.get("recheck_due") or pk.get("age_days") is None):
                errs.append(f"pick {t['symbol']} sold though held for its recheck")
        elif t["symbol"] in sat_syms:                                                    # 6
            pk = p["picks"].get(t["symbol"]) or {}
            usable = pk.get("kind") == "deep" or (pk.get("kind") == "light" and p["include_light"])
            fresh = not pk.get("recheck_due") and pk.get("age_days") is not None
            over = pk.get("central_value") is not None and t["price"] > pk["central_value"] * 1.05
            if p["settings"]["weighting"] != "valuation" or not (usable and fresh and over):
                errs.append(f"pick {t['symbol']} sold though not an overvalued, fresh, usable valuation: {pk}")
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


def test_new_pick_multiplier_tilts_by_valuation() -> None:
    w = load_script(W)
    pick = {"eligible": True, "confidence": 1.0, "central_value": 100.0, "price": 80.0, "expected_return": 0.15}
    assert w.new_pick_multiplier(pick) == pytest.approx(1.2)            # 1 + 0.5 x 0.5 x (0.15 - 0.07) / 0.10
    assert w.new_pick_multiplier(dict(pick, expected_return=0.07)) == pytest.approx(1.0)   # at the market return
    assert w.new_pick_multiplier(dict(pick, price=125.0)) == pytest.approx(0.8)            # overvalued: trim factor
    assert w.new_pick_multiplier(dict(pick, confidence=0.0)) == 1.0
    assert w.new_pick_multiplier(dict(pick, eligible=False)) == 1.0


def test_new_pick_sized_by_its_valuation_under_valuation_weighting() -> None:
    sl = load_script(SL)
    base = dict(mode="new-pick", new_pick={"symbol": "NEW", "price": 80.0}, settings={"weighting": "valuation"})
    out = sl.run_sleeves(_params(rebalance=False, **base, picks={"NEW": _deep(central=100.0, er=0.11, age_days=0)}))
    assert out["new_pick"]["size_needed"] == 2000.0 and out["new_pick"]["valuation_multiplier"] == 1.1
    assert out["new_pick"]["needed"] == 2200.0 and out["new_pick"]["allocated"] == 2200.0
    assert "VALUATION_FALLBACK" not in {f["code"] for f in out["flags"]} and out["weighting_used"] == "valuation"
    out = sl.run_sleeves(_params(**base))                               # no saved valuation: size share
    assert out["new_pick"]["needed"] == 2000.0 and out["new_pick"]["valuation_multiplier"] == 1.0
    assert "VALUATION_FALLBACK" in {f["code"] for f in out["flags"]}
    out = sl.run_sleeves(_params(**dict(base, settings={}), picks={"NEW": _deep(central=100.0, er=0.15, age_days=0)}))
    assert out["new_pick"]["needed"] == 2000.0                          # size weighting ignores it
    out = sl.run_sleeves(_params(**base, picks={"NEW": _deep(central=500.0, er=0.60, age_days=0)}))
    assert out["new_pick"]["needed"] == 2350.0                          # 5% pick cap of the 47000 total


def test_rebalance_targets_equal_weight_times_tilt() -> None:
    w = load_script(W)
    rows = [{"symbol": "A", "value": 5000, "price": 80, "central_value": 100, "expected_return": 0.15, "eligible": True, "confidence": 1.0},
            {"symbol": "B", "value": 1000, "price": 80, "central_value": 100, "expected_return": 0.07, "eligible": True, "confidence": 1.0},
            {"symbol": "C", "value": 2000, "price": 50, "central_value": 40, "expected_return": 0.0, "eligible": True, "confidence": 1.0}]
    out = w.rebalance_targets(rows, {"H": 1000.0}, 9000.0, 1_000_000.0)
    # base 1 each; tilt A 1.2, B 1.0, C trim factor 0.8 -> 8000 x [1.2, 1.0, 0.8] / 3.0
    assert out["targets"] == pytest.approx({"A": 3200.0, "B": 2666.67, "C": 2133.33, "H": 1000.0}, abs=0.01)
    assert out["capped"] == []
    assert w.band(400.0) == 250.0 and w.band(2000.0) == 500.0


def test_rebalance_targets_cap_redistributes() -> None:
    w = load_script(W)
    rows = [{"symbol": s, "value": 0, "price": 80, "central_value": 100, "expected_return": er, "eligible": True, "confidence": 1.0}
            for s, er in (("A", 0.30), ("B", 0.07), ("C", 0.07))]
    out = w.rebalance_targets(rows, {}, 3000.0, 20000.0)       # cap 1000 each
    assert out["targets"] == pytest.approx({"A": 1000.0, "B": 1000.0, "C": 1000.0})
    assert out["capped"] == ["A", "B", "C"]


# --- rebalance by valuation (equal weight x tilt, bands on moves between holdings) -----------------

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


def test_rebalance_add_moves_toward_equal_weight_tilt() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 2000}, {"AAA": _GOOD, "BBB": _FAIR}, cash=500, amount=500))
    assert _rb_trades(out) == pytest.approx({"AAA": 500.0}, abs=0.02)        # AAA target ~2535, BBB ~1965 (inside its band)
    assert out["satellite_net"] == pytest.approx(500.0, abs=0.02) and out["settings_used"]["rebalance"] is True
    assert "IN_BAND" in next(s for s in out["splits"] if s["symbol"] == "BBB")["flags"]


def test_small_add_is_fully_placed() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 2000}, {"AAA": _GOOD, "BBB": _FAIR}, cash=100, amount=100))
    assert out["unallocated_amount"] == 0.0 and out["satellite_net"] == pytest.approx(100.0, abs=0.02)


def test_rebalance_trims_outside_band() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 6000}, {"AAA": _GOOD, "BBB": _FAIR}, cash=100, amount=100))
    net = _rb_trades(out)                                                     # T 7100: AAA ~4000, BBB ~3100
    assert net["BBB"] == pytest.approx(-2900.0, abs=30) and net["AAA"] == pytest.approx(3000.0, abs=30)
    assert out["satellite_net"] == pytest.approx(100.0, abs=0.05)


def test_rebalance_is_idempotent() -> None:
    sl = load_script(SL)
    first = sl.run_sleeves(_rb_params({"AAA": 1000, "BBB": 6000}, {"AAA": _GOOD, "BBB": _FAIR}, cash=100, amount=100))
    after = {s["symbol"]: s["target"] for s in first["splits"]}
    again = sl.run_sleeves(_rb_params(after, {"AAA": _GOOD, "BBB": _FAIR}, cash=1.0, amount=1.0))
    assert not any(t["side"] == "SELL" for t in again["trades"])
    assert sum(t["value"] for t in again["trades"]) <= 1.0 + 0.01


def test_held_pick_never_trades() -> None:
    sl = load_script(SL)
    for extra, flag in (({}, "HELD_FOR_RECHECK"), ({"needs_valuation": True}, "DEEP_VALUATION_NEEDED")):
        bbb = {**_deep(central=60.0, er=0.07, recheck_due=True), **extra}
        out = sl.run_sleeves(_rb_params({"AAA": 1000, "BBB": 6000}, {"AAA": _GOOD, "BBB": bbb}, cash=100, amount=100))
        assert "BBB" not in _rb_trades(out)
        assert _rb_trades(out) == pytest.approx({"AAA": 100.0}, abs=0.02)
        assert flag in next(s for s in out["splits"] if s["symbol"] == "BBB")["flags"]
        assert any(f["code"] == flag and "BBB" in f["message"] for f in out["flags"])


def test_same_size_funds_new_pick_from_trims() -> None:
    syms = [f"P{i:02d}" for i in range(16)]
    picks = {s: _deep(central=60.0, er=0.10) for s in syms} | {"NEW": _deep(central=60.0, er=0.10)}
    p = _rb_params({s: 2000 for s in syms}, picks, mode="new-pick", same_size=True,
                   new_pick={"symbol": "NEW", "price": 50.0})
    out = load_script(SL).run_sleeves(p)
    net = _rb_trades(out)
    assert net["NEW"] == pytest.approx(32000 / 17, abs=1.0)                  # equal targets, 17 picks, same total
    assert sum(v for s, v in net.items() if s in syms) == pytest.approx(-net["NEW"], abs=1.0)
    assert "VTI" not in net and out["new_pick"]["allocated"] == pytest.approx(net["NEW"], abs=0.02)


def test_no_rebalance_matches_previous_behaviour() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 6000}, {"AAA": _GOOD, "BBB": _FAIR},
                                                  cash=100, amount=100, rebalance=False))
    assert not any(t["side"] == "SELL" for t in out["trades"])               # BBB is not overvalued: never sold
    assert out["satellite_net"] == pytest.approx(100.0, abs=0.02) and out["settings_used"]["rebalance"] is False


def test_new_pick_rebalance_includes_new_pick() -> None:
    picks = {"AAA": _GOOD, "BBB": _FAIR, "NEW": _deep(central=60.0, er=0.15, age_days=0)}
    p = _rb_params({"AAA": 2000, "BBB": 6000}, picks, mode="new-pick", new_pick={"symbol": "NEW", "price": 40.0})
    out = load_script(SL).run_sleeves(p)
    net = _rb_trades(out)        # seed 4000 (median); T 12000; NEW ~4126, AAA ~4436, BBB ~3438
    assert net["NEW"] == pytest.approx(4126.0, abs=40) and net["BBB"] == pytest.approx(-2562.0, abs=40)
    assert net["AAA"] == pytest.approx(2436.0, abs=40) and net["VTI"] == pytest.approx(-4000.0, abs=40)
    assert out["new_pick"]["allocated"] == pytest.approx(net["NEW"], abs=0.02)


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
    out = w.rebalance_targets(rows, {}, 2500.0, 20000.0)      # cap 1000; A 1.575, B trim 0.8
    assert out["targets"]["A"] == 1000.0
    assert out["targets"]["B"] == pytest.approx(2500 * 0.8 / 2.375, abs=0.01)   # its own share only; the rest unassigned


def test_rebalance_new_pick_beside_unvalued_picks_gets_its_seed() -> None:
    p = _params(mode="new-pick", new_pick={"symbol": "NEW", "price": 80.0}, settings={"weighting": "valuation"},
                picks={"NEW": _deep(central=100.0, er=0.11, age_days=0)})      # AAA and BBB have no saved valuation
    out = load_script(SL).run_sleeves(p)
    assert out["new_pick"]["allocated"] == pytest.approx(2000.0, abs=0.02)    # the median seed; AAA and BBB keep their value
    assert sum(1 for f in out["flags"] if f["code"] == "NO_SAVED_VALUATION" and f["message"].startswith("AAA ")) == 1


def _captured_params(r, monkeypatch) -> dict:
    seen: dict = {}
    real = r.sleeves.run_sleeves
    monkeypatch.setattr(r.sleeves, "run_sleeves", lambda params: seen.update(p=params) or real(params))
    return seen


def test_run_passes_rebalance_flags(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    assert run_json(r, ["add", "100"], capsys)[0] == 0
    assert seen["p"]["rebalance"] is True and seen["p"].get("same_size", False) is False
    assert run_json(r, ["add", "100", "--no-rebalance"], capsys)[0] == 0
    assert seen["p"]["rebalance"] is False
    rc, out = run_json(r, ["new-pick", "ZZZ", "--same-size", "--weighting", "valuation"], capsys)
    assert rc == 0, out
    assert seen["p"]["same_size"] is True


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


def test_fallback_size_split_skips_held_picks_only() -> None:
    picks = {"AAA": _deep(central=150.0, er=0.20, recheck_due=True), "BBB": _light()}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 6000}, picks, cash=1000, amount=1000))
    assert _rb_trades(out) == pytest.approx({"BBB": 1000.0}, abs=0.02)


def test_cap_binding_rebalance_does_not_ratchet() -> None:
    sl = load_script(SL)
    sat = {"S00": 1959.0, "S01": 13803.0, "S02": 3660.0, "S03": 13183.0}
    picks = {"S00": _deep(central=52.67, er=0.267, age_days=92), "S01": _deep(central=43.42, er=0.098, age_days=132),
             "S02": _deep(central=69.88, er=0.130, age_days=253), "S03": _deep(central=60.0, er=0.10, recheck_due=True)}
    p = _rb_params(sat, picks, cash=0.0, core=30000.0, mode="grow", grow={"amount": 4486.9})
    first = sl.run_sleeves(p)
    net = _rb_trades(first)
    sold = -sum(v for s, v in net.items() if s in sat and v < 0)
    assert sold <= sum(v for s, v in net.items() if s in sat and v > 0) + 0.05   # no trim proceeds left as cash
    after = {s: v + net.get(s, 0.0) for s, v in sat.items()}
    again = sl.run_sleeves(_rb_params(after, picks, cash=1.0, core=30000.0 + net.get("VTI", 0.0), amount=1.0))
    assert not any(t["side"] == "SELL" for t in again["trades"])


def _split_params(**over) -> dict:
    p = _rb_params({"AAA": 1000}, {"AAA": _GOOD, "BBB": _FAIR}, cash=100, amount=100, **over)
    p["accounts"]["t2"] = {"role": "trading"}
    p["cash_by_account"]["t2"] = 0.0
    p["positions"] += [{"symbol": "BBB", "units": 40, "price": 50.0, "account": "t1", "bucket": "satellite"},
                       {"symbol": "BBB", "units": 80, "price": 50.0, "account": "t2", "bucket": "satellite"}]
    return p


def test_split_pick_trims_where_proceeds_are_spent() -> None:
    sl = load_script(SL)
    for over in ({}, {"whole_shares": True}):
        out = sl.run_sleeves(_split_params(**over))
        by_acct: dict[str, float] = {}
        for t in out["trades"]:
            by_acct[t["account"]] = by_acct.get(t["account"], 0.0) + (t["value"] if t["side"] == "BUY" else -t["value"])
        assert by_acct.get("t2", 0.0) >= -0.02, out["trades"]       # t2 has nothing to buy: nothing sold there to sit idle
        assert out["satellite_net"] >= -0.02 and out["unallocated_amount"] <= 100.0 + 0.02


@pytest.mark.parametrize("over", [{"rebalance": False}, {"weighting": "size"}])
def test_same_size_needs_valuation_rebalance(over) -> None:
    p = _rb_params({"AAA": 2000, "BBB": 6000}, {"AAA": _GOOD, "BBB": _FAIR, "NEW": _deep(central=60.0, er=0.10)},
                   mode="new-pick", same_size=True, new_pick={"symbol": "NEW", "price": 40.0}, **over)
    with pytest.raises(ValueError, match="same_size"):
        load_script(SL).run_sleeves(p)


def test_same_size_rejects_amount() -> None:
    p = _rb_params({"AAA": 2000, "BBB": 6000}, {"AAA": _GOOD, "BBB": _FAIR, "NEW": _deep(central=60.0, er=0.10)},
                   mode="new-pick", same_size=True, new_pick={"symbol": "NEW", "price": 40.0, "amount": 500})
    with pytest.raises(ValueError, match="same_size"):
        load_script(SL).run_sleeves(p)


def test_same_size_fallback_is_bad_input() -> None:
    picks = {"AAA": _deep(central=150.0, er=0.20, recheck_due=True), "BBB": _deep(central=60.0, er=0.07, recheck_due=True)}
    p = _rb_params({"AAA": 2000, "BBB": 6000}, picks, mode="new-pick", same_size=True, new_pick={"symbol": "NEW", "price": 40.0})
    with pytest.raises(ValueError, match="same_size"):
        load_script(SL).run_sleeves(p)
