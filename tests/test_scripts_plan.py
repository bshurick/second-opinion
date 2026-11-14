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


# --- growth picks: --group/--mix pass-through and the global plan's hold -------------------------

GP = "portfolio-plan/scripts/global_plan.py"


def test_plan_contribute_passes_group(cs_sdk, monkeypatch, capsys) -> None:
    plan = load_script(P)
    seen: list[list[str]] = []
    real = plan.sleeve_run.run
    monkeypatch.setattr(plan.sleeve_run, "run", lambda args: (seen.append(args), real(args))[1])
    plan.run(["contribute", "2000", "--sleeve", "PICKS", "--group", "growth", *TODAY])
    assert seen[0][:2] == ["add", "2000.0"] and seen[0][seen[0].index("--group") + 1] == "growth"
    seen.clear()
    plan.run(["contribute", "2000", "--sleeve", "PICKS", "--mix", "70%,30%", *TODAY])
    assert seen[0][seen[0].index("--mix") + 1] == "70%,30%"
    seen.clear()
    plan.run(["contribute", "1000", *TODAY])                          # the automatic path names no group
    assert not any("--group" in a or "--mix" in a for a in seen)


def test_plan_group_and_mix_only_with_contribute_sleeve(cs_sdk, capsys) -> None:
    for args in (["contribute", "1000", "--group", "growth"], ["open", "ZZZ", "--group", "growth"],
                 ["rebalance", "--sleeve", "PICKS", "--mix", "50%,50%"], ["withdraw", "100", "--group", "value"]):
        rc, out = run_json(load_script(P), [*args, *TODAY], capsys)
        assert rc == 2 and "--sleeve PICKS" in out["error"], args


def _growth_book(cs_sdk, monkeypatch, tmp_path, value: int, growth: int) -> None:
    """acc-1 holds VTI, the value pick AAA and the growth pick GGG (units at $100) with no cash; total 10000."""
    import test_scripts_sleeves as T
    vti = (10000 - 100 * value - 100 * growth) / 200
    rows = [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": vti, "price": 200.0, "average_purchase_price": 150.0},
            {"symbol": {"symbol": {"symbol": "AAA"}}, "units": value, "price": 100.0, "average_purchase_price": 90.0},
            {"symbol": {"symbol": {"symbol": "GGG"}}, "units": growth, "price": 100.0, "average_purchase_price": 90.0}]
    book = {"acc-1": rows, "acc-2": []}
    monkeypatch.setitem(cs_sdk.bodies, "get_user_account_positions", lambda account_id: book[account_id])
    monkeypatch.setitem(cs_sdk.bodies, "get_user_account_balance",
                        lambda account_id: [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}])
    monkeypatch.setitem(T.CS_SECTORS, "GGG", {"quote_type": "EQUITY", "sector": "Technology", "fund_sectors": None})
    import json
    store = json.loads((tmp_path / "picks.json").read_text())
    store["picks"].append({"symbol": "GGG", "kind": "deep", "style": "growth", "baseline": "picks/GGG.json",
                           "baseline_as_of": "2026-10-01", "checks": []})
    (tmp_path / "picks.json").write_text(json.dumps(store))


def _side(out: dict, sym: str) -> dict[str, float]:
    sides: dict[str, float] = {}
    for t in out["trades"]:
        if t["symbol"] == sym:
            sides[t["side"]] = sides.get(t["side"], 0.0) + t["value"]
    return sides


TARGETS = ["--target", "VTI=0.9", "--target", "PICKS=0.1"]


def test_picks_line_growth_over(cs_sdk, monkeypatch, tmp_path) -> None:
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=8, growth=6)          # V 800 + G 600 over T 1000
    out = load_script(GP).run(TARGETS)
    assert not _side(out, "AAA") and not _side(out, "GGG")
    assert any(f["code"] == "GROWTH_PICKS_OVER" and "GGG" in f["message"] for f in out["flags"])
    assert {"symbol": "GGG", "value": 600.0} in out["frozen"]


def test_growth_picks_over_names_only_the_growth_picks_counted(cs_sdk, monkeypatch, tmp_path) -> None:
    import json
    import test_scripts_sleeves as T
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=8, growth=6)
    rows = cs_sdk.bodies["get_user_account_positions"]("acc-1") + [
        {"symbol": {"symbol": {"symbol": "HHH"}}, "units": 1, "price": 100.0, "average_purchase_price": 90.0}]
    monkeypatch.setitem(cs_sdk.bodies, "get_user_account_positions", lambda account_id: rows if account_id == "acc-1" else [])
    monkeypatch.setitem(T.CS_SECTORS, "HHH", {"quote_type": "EQUITY", "sector": "Technology", "fund_sectors": None})
    store = json.loads((tmp_path / "picks.json").read_text())
    store["picks"].append({"symbol": "HHH", "kind": "deep", "style": "growth", "baseline": "picks/HHH.json",
                           "baseline_as_of": "2026-10-01", "checks": []})
    (tmp_path / "picks.json").write_text(json.dumps(store))
    out = load_script(GP).run([*TARGETS, "--class", "HHH=VTI"])               # HHH is classed VTI: kept, not in G
    msg = next(f["message"] for f in out["flags"] if f["code"] == "GROWTH_PICKS_OVER")
    assert "(GGG)" in msg and "HHH" not in msg


def test_global_plan_carries_the_two_picks_groups(cs_sdk, monkeypatch, tmp_path) -> None:
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=8, growth=6)          # V 800, G 600; T = 0.1 x 10000
    out = load_script(GP).run(TARGETS)
    pg = out["picks_groups"]
    assert pg["value"] == {"value": 800.0, "symbols": ["AAA"]} and pg["growth"] == {"value": 600.0, "symbols": ["GGG"]}
    assert pg["target_value"] == 1000.0 and pg["target_weight"] == 0.1
    assert pg["line_weight"] == {r["key"]: r for r in out["allocation"]}["PICKS"]["target"]
    over = [f for f in out["flags"] if f["code"] == "GROWTH_OVER_CAP"]   # GGG 600 of 10000 is above the 5% cap
    assert len(over) == 1 and over[0]["message"].startswith("GGG ")
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=12, growth=0)
    out = load_script(GP).run(TARGETS)
    assert "picks_groups" not in out and not any(f["code"] == "GROWTH_OVER_CAP" for f in out["flags"])


def _plan_dom(plan: dict, tmp_path) -> str:
    """The rendered plan page after its script ran (Chrome's --dump-dom)."""
    import json
    import subprocess
    import page_dom
    src, out = tmp_path / "plan.json", tmp_path / "p.html"
    src.write_text(json.dumps(plan))
    load_script("portfolio-plan/scripts/render.py").main(["--in", str(src), "--out", str(out)])
    doc = tmp_path / "doc.html"
    doc.write_text(f'<!doctype html><html><head><meta charset="utf-8"></head><body>{out.read_text()}</body></html>')
    return subprocess.run([*page_dom.chrome_cmd(tmp_path, budget_ms=3000), "--dump-dom", doc.as_uri()],
                          capture_output=True, text=True, timeout=90).stdout


@pytest.mark.skipif(__import__("page_dom").CHROME is None, reason="Google Chrome not found")
def test_plan_page_shows_the_two_picks_groups(cs_sdk, monkeypatch, tmp_path, capsys) -> None:
    import re
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=8, growth=6)
    dom = _plan_dom(load_script(GP).run(TARGETS), tmp_path)
    capsys.readouterr()
    groups = re.search(r'id="picks-groups"[^>]*>(.*?)</p>', dom, re.S).group(1)
    assert "Value picks $800" in groups and "growth picks $600" in groups and "GGG $600 (growth pick, left to run)" in groups
    assert "adjusted for growth picks" in groups and "saved PICKS target of 10.0%" in groups
    frozen = re.search(r'id="frozen"[^>]*>(.*?)</p>', dom, re.S).group(1)
    assert "Frozen (not in any group" not in frozen and "Growth picks, left to run" in frozen
    assert "GROWTH_OVER_CAP" in dom
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=12, growth=0)              # value only: as before
    (tmp_path / "v").mkdir()
    dom = _plan_dom(load_script(GP).run(TARGETS), tmp_path / "v")
    capsys.readouterr()
    assert re.search(r'<p class="note" id="picks-groups" hidden=""></p>', dom)


def test_picks_line_value_over(cs_sdk, monkeypatch, tmp_path) -> None:
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=12, growth=3)         # value picks alone over T: sell down to T
    out = load_script(GP).run(TARGETS)
    assert _side(out, "AAA") == {"SELL": pytest.approx(200.0, abs=0.01)} and not _side(out, "GGG")
    assert any(f["code"] == "GROWTH_PICKS_OVER" for f in out["flags"])


def test_picks_line_under(cs_sdk, monkeypatch, tmp_path) -> None:
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=4, growth=3)          # 700 under T: value picks fill to T - G
    out = load_script(GP).run(TARGETS)
    assert _side(out, "AAA") == {"BUY": pytest.approx(300.0, abs=0.01)} and not _side(out, "GGG")
    assert not any(f["code"] == "GROWTH_PICKS_OVER" for f in out["flags"])


def test_picks_line_without_growth_picks_is_unchanged(cs_sdk, monkeypatch, tmp_path) -> None:
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=12, growth=0)
    out = load_script(GP).run(TARGETS)
    rows = {r["key"]: r for r in out["allocation"]}
    assert rows["PICKS"]["target"] == 0.1 and rows["VTI"]["target"] == 0.9
    assert _side(out, "AAA") == {"SELL": pytest.approx(200.0, abs=0.01)}


def test_withdraw_skips_growth(cs_sdk, monkeypatch, tmp_path) -> None:
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=8, growth=6)
    out = load_script(P).run(["withdraw", "2000", *TODAY])                 # no saved targets: today's weights of the rest
    assert out["global"]["withdrawal"] == 2000.0 and "GGG" not in out["global"]["targets_used"]
    assert not _side(out, "GGG") and _side(out, "AAA")
    settings.set_value("plan.targets", {"VTI": 0.9, "PICKS": 0.1})
    out = load_script(P).run(["withdraw", "2000", *TODAY])
    assert not _side(out, "GGG")


PLAIN = ("AAA", "BBB", "GGG")


def _no_plain_trades(out: dict) -> None:
    assert not [t for t in out["trades"] if t["symbol"] in PLAIN], out["trades"]


def _store_flag(out: dict) -> None:
    assert any(f["code"] == "PICK_STORE_UNREADABLE" for f in out["flags"]), out["flags"]


def test_unreadable_pick_store_freezes_plain_stocks_in_the_global_plan(cs_sdk, monkeypatch, tmp_path) -> None:
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=8, growth=6)
    (tmp_path / "picks.json").write_text("{not json")
    for out in (load_script(GP).run(TARGETS), load_script(P).run(["withdraw", "2000", *TODAY])):
        _no_plain_trades(out)
        _store_flag(out)
        assert not any(f["code"] == "GROWTH_PICKS_OVER" for f in out["flags"])
    msg = next(f["message"] for f in load_script(GP).run(TARGETS)["flags"] if f["code"] == "PICK_STORE_UNREADABLE")
    assert "repaired" in msg
    settings.set_value("plan.targets", {"VTI": 0.9, "PICKS": 0.1})
    for args in (["rebalance"], ["withdraw", "2000"]):
        out = load_script(P).run([*args, *TODAY])
        _no_plain_trades(out)
        _store_flag(out)


def test_unreadable_pick_store_sells_nothing_to_fund_the_held_picks_line(cs_sdk, monkeypatch, tmp_path) -> None:
    _growth_book(cs_sdk, monkeypatch, tmp_path, value=2, growth=3)          # picks under T: today's line would buy PICKS
    (tmp_path / "picks.json").write_text("{not json")
    out = load_script(GP).run(TARGETS)
    _no_plain_trades(out)
    assert not _side(out, "VTI"), out["trades"]
    settings.set_value("plan.targets", {"VTI": 0.9, "PICKS": 0.1})
    out = load_script(P).run(["withdraw", "1000", *TODAY])
    _no_plain_trades(out)
    assert _side(out, "VTI") == {"SELL": pytest.approx(1000.0, abs=1.0)}, out["trades"]


def test_unreadable_pick_store_no_targets_withdraw_freezes_plain_stocks_in_any_account(cs_sdk, monkeypatch, tmp_path) -> None:
    import test_scripts_sleeves as T
    rows = [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 40, "price": 200.0, "average_purchase_price": 150.0}]
    roth = [{"symbol": {"symbol": {"symbol": "GGG"}}, "units": 20, "price": 100.0, "average_purchase_price": 90.0}]
    book = {"acc-1": rows, "acc-2": roth}
    monkeypatch.setitem(cs_sdk.bodies, "get_user_account_positions", lambda account_id: book[account_id])
    monkeypatch.setitem(cs_sdk.bodies, "get_user_account_balance",
                        lambda account_id: [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}])
    monkeypatch.setitem(T.CS_SECTORS, "GGG", {"quote_type": "EQUITY", "sector": "Technology", "fund_sectors": None})
    (tmp_path / "picks.json").write_text("{not json")
    out = load_script(P).run(["withdraw", "1000", *TODAY])
    _no_plain_trades(out)
    _store_flag(out)
    assert _side(out, "VTI")


def test_unreadable_pick_store_holds_every_pick_in_add_and_contribute(cs_sdk, tmp_path) -> None:
    (tmp_path / "picks.json").write_text("{not json")
    out = load_script(SR).run(["add", "500", *TODAY])
    assert out["trades"] == [] and out["unallocated_amount"] == 500.0
    _store_flag(out)
    settings.set_value("plan.sleeves.PICKS.target", 0.1)            # the sleeve sits below target: add runs first
    out = load_script(P).run(["contribute", "500", *TODAY])
    assert out["sleeve"] is not None
    _no_plain_trades(out)
    _store_flag(out)


def test_unreadable_pick_store_new_pick_opens_but_fills_no_held_pick(cs_sdk, tmp_path) -> None:
    (tmp_path / "picks.json").write_text("{not json")
    out = load_script(SR).run(["new-pick", "ZZZ", "--amount", "600", *TODAY])
    _no_plain_trades(out)
    _store_flag(out)
    assert {t["symbol"] for t in out["trades"] if t["side"] == "BUY"} == {"ZZZ"}
    assert out["new_pick"]["allocated"] > 0


def _roth_growth(cs_sdk, monkeypatch, tmp_path) -> None:
    """VTI 8000 in acc-1 (trading) and the growth pick GGG 2000 held only in the Roth acc-2; no cash."""
    import json
    import test_scripts_sleeves as T
    rows = [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 40, "price": 200.0, "average_purchase_price": 150.0}]
    roth = [{"symbol": {"symbol": {"symbol": "GGG"}}, "units": 20, "price": 100.0, "average_purchase_price": 90.0}]
    book = {"acc-1": rows, "acc-2": roth}
    monkeypatch.setitem(cs_sdk.bodies, "get_user_account_positions", lambda account_id: book[account_id])
    monkeypatch.setitem(cs_sdk.bodies, "get_user_account_balance",
                        lambda account_id: [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}])
    monkeypatch.setitem(T.CS_SECTORS, "GGG", {"quote_type": "EQUITY", "sector": "Technology", "fund_sectors": None})
    store = json.loads((tmp_path / "picks.json").read_text())
    store["picks"].append({"symbol": "GGG", "kind": "deep", "style": "growth", "baseline": "picks/GGG.json",
                           "baseline_as_of": "2026-10-01", "checks": []})
    (tmp_path / "picks.json").write_text(json.dumps(store))


def test_withdraw_never_sells_a_growth_pick_held_in_retirement(cs_sdk, monkeypatch, tmp_path) -> None:
    _roth_growth(cs_sdk, monkeypatch, tmp_path)
    out = load_script(P).run(["withdraw", "1000", *TODAY])                 # no saved targets
    assert not _side(out, "GGG") and _side(out, "VTI")
    assert "GGG" not in out["global"]["targets_used"]
    settings.set_value("plan.targets", {"VTI": 0.9, "PICKS": 0.1})
    for args in (["withdraw", "1000"], ["rebalance"]):
        assert not _side(load_script(P).run([*args, *TODAY]), "GGG"), args
    settings.set_value("plan.targets", {"VTI": 1.0})
    for args in (["withdraw", "1000"], ["rebalance"]):
        assert not _side(load_script(P).run([*args, *TODAY]), "GGG"), args
