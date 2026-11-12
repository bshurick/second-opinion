"""plan.py, the portfolio-plan dispatcher: golden equivalence with the sleeve engine, and the no-target paths."""
from __future__ import annotations

import pytest
from scripts_util import load_script, run_json
from second_opinion import settings
from test_scripts_sleeves import cs_sdk  # noqa: F401  (fixture: VTI 10000 + AAA 1000 + BBB 500 + 2000 cash in acc-1, VTI 4000 in the Roth acc-2)

P = "portfolio-plan/scripts/plan.py"
SR = "portfolio-plan/scripts/sleeve_run.py"
TODAY = ["--today", "2026-11-10"]


def _same(sleeve: dict, ref: dict) -> None:
    for k in ("trades", "splits", "flags", "new_pick", "held_back"):
        assert sleeve[k] == ref[k], k


def test_contribute_sleeve_equals_sleeve_add(cs_sdk) -> None:
    ref = load_script(SR).run(["add", "500", *TODAY])
    out = load_script(P).run(["contribute", "500", "--sleeve", "PICKS", *TODAY])
    assert out["command"] == "contribute" and out["amount"] == 500.0 and out["global"] is None
    _same(out["sleeve"], ref)
    assert out["trades"] == ref["trades"] and out["flags"] == ref["flags"]


def test_open_equals_new_pick(cs_sdk) -> None:
    ref = load_script(SR).run(["new-pick", "ZZZ", "--amount", "600", *TODAY])
    out = load_script(P).run(["open", "ZZZ", "--amount", "600", *TODAY])
    assert out["command"] == "open"
    _same(out["sleeve"], ref)
    assert out["trades"] == ref["trades"]


def test_rebalance_sleeve_equals_sleeve_rebalance(cs_sdk) -> None:
    ref = load_script(SR).run(["rebalance", "--weighting", "equal", *TODAY])
    out = load_script(P).run(["rebalance", "--sleeve", "PICKS", "--weighting", "equal", *TODAY])
    _same(out["sleeve"], ref)
    assert out["trades"] == ref["trades"]


def test_contribute_no_targets_buys_core_pro_rata(cs_sdk) -> None:
    out = load_script(P).run(["contribute", "1000", *TODAY])
    assert out["sleeve"] is None
    assert out["trades"] and all(t["side"] == "BUY" and t["symbol"] == "VTI" for t in out["trades"])
    assert sum(t["value"] for t in out["trades"]) == pytest.approx(1000.0, abs=0.01)
    assert out["global"]["sources"]["targets"] == "held core funds"


def test_contribute_sleeve_below_target_first(cs_sdk) -> None:
    settings.set_value("plan.sleeves.PICKS.target", 0.1)            # 10% of 17500 = 1750; picks hold 1500
    out = load_script(P).run(["contribute", "1000", "--weighting", "equal", *TODAY])
    assert out["sleeve"]["satellite_net"] == pytest.approx(250.0, abs=0.01)
    pick_buys = sum(t["value"] for t in out["trades"] if t["symbol"] in ("AAA", "BBB"))
    core_buys = sum(t["value"] for t in out["trades"] if t["symbol"] == "VTI")
    assert pick_buys == pytest.approx(250.0, abs=0.01) and core_buys == pytest.approx(750.0, abs=0.01)


def test_contribute_with_targets_routes_the_rest_without_the_sleeve(cs_sdk) -> None:
    settings.set_value("plan.targets", {"VTI": 0.9, "PICKS": 0.1})  # VTI alone after the sleeve key is set aside
    out = load_script(P).run(["contribute", "1000", "--weighting", "equal", *TODAY])
    assert out["sleeve"]["satellite_net"] == pytest.approx(250.0, abs=0.01)
    assert out["global"]["sources"]["targets"] == "overrides"
    assert not any(t["side"] == "SELL" for t in out["trades"])
    assert sum(t["value"] for t in out["trades"] if t["symbol"] == "VTI") == pytest.approx(750.0, abs=0.01)


def test_contribute_more_than_the_cash_is_bad_input(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script(P), ["contribute", "5000", *TODAY], capsys)
    assert rc == 2 and "2000.00" in out["error"]


def test_withdraw_no_targets_pro_rata(cs_sdk) -> None:
    out = load_script(P).run(["withdraw", "3500", *TODAY])
    g = out["global"]
    assert g["withdrawal"] == 3500.0 and g["sources"]["targets"] == "held weights"
    sells = [t for t in out["trades"] if t["side"] == "SELL"]
    assert sells and all(t["account"] == "acc-2" for t in sells if t["symbol"] == "VTI")   # tax-advantaged first


def test_rebalance_no_targets_offers_derived(cs_sdk) -> None:
    out = load_script(P).run(["rebalance", *TODAY])
    assert out["no_targets"] is True and out["trades"] == []
    d = out["derived_targets"]
    assert set(d) == {"VTI", "AAA", "BBB", "CASH"} and sum(d.values()) == pytest.approx(1.0, abs=0.001)


def test_status_reports_sleeve_target_and_glide(cs_sdk) -> None:
    settings.set_value("plan.sleeves.PICKS.glide", {"to": 0.2, "by": "2027-02-10"})
    out = load_script(P).run(["status", *TODAY])
    assert out["targets_saved"] is False and out["global"] is None
    assert out["sleeves"]["mix"]["satellite"]["value"] == 1500.0
    assert out["sleeve_target"] == 0.2
    assert out["glide"] == {"to": 0.2, "by": "2027-02-10", "months_left": 3, "monthly": pytest.approx(666.67, abs=0.01)}


def test_status_with_targets_has_a_global_plan_without_trades(cs_sdk) -> None:
    settings.set_value("plan.targets", {"VTI": 0.8, "PICKS": 0.1, "CASH": 0.1})
    out = load_script(P).run(["status", *TODAY])
    assert out["targets_saved"] is True and out["sleeve_target"] == 0.1 and out["glide"] is None
    assert {r["key"] for r in out["global"]["allocation"]} == {"VTI", "PICKS", "CASH"}
    assert "trades" not in out["global"]


def test_unknown_sleeve_is_bad_input(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script(P), ["rebalance", "--sleeve", "BONDS", *TODAY], capsys)
    assert rc == 2 and "PICKS" in out["error"]


def test_targets_with_picks_and_no_picks_held(cs_sdk, monkeypatch) -> None:
    import test_scripts_sleeves as T
    only_core = {"acc-1": [T.CS_POSITIONS["acc-1"][0]], "acc-2": T.CS_POSITIONS["acc-2"]}
    monkeypatch.setitem(cs_sdk.bodies, "get_user_account_positions", lambda account_id: only_core[account_id])
    settings.set_value("plan.targets", {"VTI": 0.9, "PICKS": 0.1})
    status = load_script(P).run(["status", *TODAY])
    rows = {r["key"]: r for r in status["global"]["allocation"]}
    assert rows["PICKS"]["value"] == 0.0 and rows["VTI"]["value"] == 14000.0
    out = load_script(P).run(["contribute", "1000", *TODAY])
    assert not any(t["symbol"] not in ("VTI",) for t in out["trades"])
    assert sum(t["value"] for t in out["trades"]) == pytest.approx(1000.0, abs=0.01)
    reb = load_script(P).run(["rebalance", *TODAY])
    assert any(f["code"] == "NO_HOLDINGS" and "PICKS" in f["message"] for f in reb["flags"])


def test_contribute_buys_land_in_accounts_with_the_cash(cs_sdk) -> None:
    out = load_script(P).run(["contribute", "1000", *TODAY])                 # all cash sits in acc-1; the Roth has none
    assert out["trades"] and all(t["account"] == "acc-1" for t in out["trades"])
    assert sum(t["value"] for t in out["trades"]) == pytest.approx(1000.0, abs=0.01)


def test_contribute_global_part_uses_only_the_cash_the_sleeve_left(cs_sdk) -> None:
    settings.set_value("plan.sleeves.PICKS.target", 0.1)
    out = load_script(P).run(["contribute", "2000", "--weighting", "equal", *TODAY])   # 250 to picks, 1750 left in acc-1
    assert all(t["account"] == "acc-1" for t in out["trades"])
    assert sum(t["value"] for t in out["trades"]) == pytest.approx(2000.0, abs=0.01)
    assert not any(f["code"] == "ACCOUNT_SHORT" for f in out["flags"])


def test_employer_default_is_one_flag_across_both_engines(cs_sdk, monkeypatch) -> None:
    import sys
    from second_opinion import holdings
    cand = {"symbol": "BBB", "deposits": ["2026-08-01"], "vests": ["2026-08-01"], "every_days": None, "sold_within_days": None}
    settings.set_value("plan.targets", {"VTI": 0.8, "PICKS": 0.2})
    plan = load_script(P)
    monkeypatch.setattr(holdings, "employer_candidate", lambda hub, accounts, roles, today: cand)
    monkeypatch.setattr(sys.modules["sleeve_run"], "_employer_candidate", lambda hub, accounts, roles, today: cand)
    out = plan.run(["contribute", "500", *TODAY])
    assert out["global"] is not None
    msgs = [f["message"] for f in out["flags"] if f["code"] == "STANDING_DEFAULT" and f["message"].startswith("employer_symbol is unset")]
    assert len(msgs) == 1, msgs


def test_contribute_split_reaches_the_sleeve(cs_sdk) -> None:
    out = load_script(P).run(["contribute", "500", "--sleeve", "PICKS", "--split", *TODAY])
    assert out["sleeve"]["settings_used"]["allocation"] == "split"
    out = load_script(P).run(["contribute", "500", "--sleeve", "PICKS", *TODAY])
    assert out["sleeve"]["settings_used"]["allocation"] == "fill"
