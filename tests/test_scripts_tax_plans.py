"""Tax-aware deep review: tax_plans.py (the math), render_plans.py (the page), plan_store.py (the later check)."""
from __future__ import annotations

import copy
import io
import json

import pytest
from page_dom import assert_page_help, render_and_audit, requires_chrome
from scripts_util import load_script, run_json

PLANS = "tax-aware/scripts/tax_plans.py"
RENDER = "tax-aware/scripts/render_plans.py"
STORE = "tax-aware/scripts/plan_store.py"
AS_OF = "2026-11-01"

# Invented, round figures so each test's arithmetic can be done by hand. Not any real year's law.
RULE_YEAR = {
    "status": "enacted",
    "standard_deduction": 10000.0,
    "ordinary": [[50000.0, 0.10], [100000.0, 0.20], [None, 0.30]],
    "long_term": [[40000.0, 0.0], [200000.0, 0.15], [None, 0.20]],
    "niit_threshold": 200000.0,
    "niit_rate": 0.04,
    "loss_limit": 3000.0,
    "source": "Rev. Proc. sample",
    "primary": True,
    "date": "2026-01-15",
}


def _rule(rule: str) -> dict:
    return {"rule": rule, "says": f"{rule} says this", "source": "IRC sample section", "primary": True, "date": "2026-01-15"}


CITED = [_rule(r) for r in ("capital_gains", "wash_sale", "loss_limit", "roth_conversion", "niit")]


def _lot(symbol="AAA", units=100.0, cost=1000.0, price=20.0, buy="2020-01-10", ltd="2021-01-11") -> dict:
    return {"symbol": symbol, "account_id": "a1", "buy_date": buy, "units": units, "cost": cost, "price": price, "long_term_date": ltd}


BOOK = {"as_of": AS_OF, "open_lots": [_lot(), _lot("BBB", 100.0, 5000.0, 30.0, "2026-06-01", "2027-06-02")], "summary": {"loss_carryforward": 0.0}}


def _params(*plans, **over) -> dict:
    base = {
        "as_of": AS_OF, "filing": "single", "book": BOOK,
        "years": [2026, 2027],
        "rule_tables": {"2026": RULE_YEAR, "2027": RULE_YEAR},
        "rules": CITED,
        "income": {"2026": {"ordinary": 60000.0, "withheld": 7000.0}, "2027": {"ordinary": 60000.0, "withheld": 7000.0}},
        "accounts": {"traditional": 0.0, "traditional_basis": 0.0, "roth": 0.0},
        "assumptions": {"growth": 0.0, "exit_long_term": 0.15, "exit_ordinary": 0.20, "state_rate": 0.0},
        "plans": [{"name": "Do nothing", "why": "The baseline", "actions": []}, *plans],
        "tests": [],
    }
    return {**base, **over}


def _sell(symbol="AAA", units=100.0, year=2026, date=None) -> dict:
    return {"type": "sell", "year": year, "symbol": symbol, "units": units, **({"date": date} if date else {})}


def _run(params: dict) -> dict:
    return load_script(PLANS).run_plans(params)


def _flag(out: dict, code: str) -> str | None:
    return next((f["message"] for f in out["flags"] if f["code"] == code), None)


def _plan(out: dict, name: str) -> dict:
    return next(p for p in out["plans"] if p["name"] == name)


def test_wage_tax_on_the_brackets() -> None:
    year = _plan(_run(_params()), "Do nothing")["years"][0]
    # taxable 50000: all at 10%
    assert year["ordinary_tax"] == 5000.0 and year["total_tax"] == 5000.0 and year["activity_tax"] == 0.0
    assert year["balance_due"] == -2000.0


def test_long_term_gain_stacks_on_top_of_ordinary_income() -> None:
    out = _run(_params({"name": "Sell", "why": "x", "actions": [_sell()]}))
    year = _plan(out, "Sell")["years"][0]
    # gain 1000 on $2000 proceeds; ordinary taxable 50000 is past the 40000 0% band, so 15%
    assert year["long_term_net"] == 1000.0 and year["capital_gains_tax"] == 150.0 and year["activity_tax"] == 150.0


def test_long_term_gain_uses_room_in_the_zero_band() -> None:
    params = _params({"name": "Sell", "why": "x", "actions": [_sell()]})
    params["income"]["2026"]["ordinary"] = 45000.0  # taxable 35000, so 5000 of room at 0%
    params["book"] = {**BOOK, "open_lots": [_lot(cost=0.0, price=100.0)]}  # gain 10000
    year = _plan(_run(params), "Sell")["years"][0]
    assert year["capital_gains_tax"] == 750.0  # 5000 at 0%, 5000 at 15%


def test_a_short_term_gain_is_ordinary_income() -> None:
    year = _plan(_run(_params({"name": "Sell", "why": "x", "actions": [_sell("BBB")]})), "Sell")["years"][0]
    # gain 3000 - 5000 cost? 100 x 30 = 3000 proceeds on 5000 cost is a 2000 short-term loss
    assert year["short_term_net"] == -2000.0 and year["loss_deducted"] == 2000.0
    assert year["ordinary_tax"] == 4800.0  # 48000 at 10%


def test_holding_past_the_long_term_date_changes_the_term() -> None:
    book = {**BOOK, "open_lots": [_lot("CCC", 100.0, 1000.0, 20.0, "2026-06-01", "2027-06-02")]}
    now = _plan(_run(_params({"name": "S", "why": "x", "actions": [_sell("CCC", year=2026)]}, book=book)), "S")["years"][0]
    later = _plan(_run(_params({"name": "S", "why": "x", "actions": [_sell("CCC", year=2027)]}, book=book)), "S")["years"][1]
    assert now["short_term_net"] == 1000.0 and now["long_term_net"] == 0.0
    assert later["long_term_net"] == 1000.0 and later["short_term_net"] == 0.0


def test_a_loss_beyond_the_limit_carries_forward_with_its_character() -> None:
    book = {**BOOK, "open_lots": [_lot("LLL", 100.0, 11000.0, 20.0, "2026-06-01", "2027-06-02")]}  # 9000 short-term loss
    years = _plan(_run(_params({"name": "H", "why": "x", "actions": [_sell("LLL")]}, book=book)), "H")["years"]
    assert years[0]["loss_deducted"] == 3000.0 and years[0]["carry_out"] == {"short": 6000.0, "long": 0.0}
    assert years[1]["loss_deducted"] == 3000.0 and years[1]["carry_out"] == {"short": 3000.0, "long": 0.0}


def test_a_carried_loss_offsets_later_gains_and_the_opening_carry_is_used() -> None:
    book = {**BOOK, "summary": {"loss_carryforward": 400.0}}
    year = _plan(_run(_params({"name": "S", "why": "x", "actions": [_sell()]}, book=book)), "S")["years"][0]
    assert year["long_term_net"] == 600.0 and year["capital_gains_tax"] == 90.0


def test_a_roth_conversion_is_ordinary_income_and_moves_the_money() -> None:
    params = _params({"name": "Convert", "why": "x", "actions": [{"type": "roth_convert", "year": 2026, "amount": 10000.0}]}, accounts={"traditional": 50000.0, "traditional_basis": 0.0, "roth": 0.0})
    out = _run(params)
    plan = _plan(out, "Convert")
    assert plan["years"][0]["ordinary_tax"] == 7000.0 and plan["years"][0]["activity_tax"] == 2000.0  # 60000 taxable: 50000 at 10%, 10000 at 20%
    assert plan["end"]["roth"] == 10000.0 and plan["end"]["traditional"] == 40000.0


def test_a_conversion_follows_the_pro_rata_rule() -> None:
    params = _params({"name": "Convert", "why": "x", "actions": [{"type": "roth_convert", "year": 2026, "amount": 10000.0}]}, accounts={"traditional": 50000.0, "traditional_basis": 25000.0, "roth": 0.0})
    plan = _plan(_run(params), "Convert")
    assert plan["years"][0]["conversion_taxable"] == 5000.0
    assert plan["end"]["traditional_basis"] == 20000.0


def test_wealth_at_the_end_counts_tax_still_owed() -> None:
    out = _run(_params(accounts={"traditional": 10000.0, "traditional_basis": 0.0, "roth": 5000.0}))
    end = _plan(out, "Do nothing")["end"]
    # lots worth 2000 + 3000, gains 1000 and -2000: the net gain counts only where positive, 1000 x .15 - 2000 x .15
    assert end["taxable_value"] == 5000.0 and end["unrealized_gain"] == -1000.0
    assert end["after_tax_wealth"] == round(5000 + 150 + 10000 * 0.8 + 5000, 2)


def test_plans_are_compared_on_wealth_against_doing_nothing() -> None:
    out = _run(_params({"name": "Sell", "why": "x", "actions": [_sell()]}))
    base, sell = _plan(out, "Do nothing"), _plan(out, "Sell")
    assert sell["wealth_vs_baseline"] == round(sell["end"]["after_tax_wealth"] - base["end"]["after_tax_wealth"], 2)
    assert sell["tax_vs_baseline"] == 150.0
    assert out["leading"] in ("Do nothing", "Sell")


def test_growth_reaches_the_lots_the_pot_and_the_accounts() -> None:
    assumptions = {"growth": 0.10, "exit_long_term": 0.0, "exit_ordinary": 0.0, "state_rate": 0.0}
    end = _plan(_run(_params(assumptions=assumptions, accounts={"traditional": 1000.0, "traditional_basis": 0.0, "roth": 1000.0})), "Do nothing")["end"]
    assert end["end_date"] == "2027-12-31"
    assert end["roth"] == pytest.approx(1000 * 1.1 ** (425 / 365), abs=0.01)  # 425 days from as_of to the end date
    assert end["taxable_value"] > 5000.0


def test_tax_on_activity_comes_out_of_the_pot() -> None:
    plan = _plan(_run(_params({"name": "Sell", "why": "x", "actions": [_sell()]})), "Sell")
    assert plan["end"]["pot"] == 2000.0 - 150.0


def test_niit_and_state_are_added() -> None:
    params = _params({"name": "Sell", "why": "x", "actions": [_sell()]})
    params["income"]["2026"]["ordinary"] = 250000.0
    params["assumptions"] = {**params["assumptions"], "state_rate": 0.05}
    year = _plan(_run(params), "Sell")["years"][0]
    assert year["niit"] == 40.0  # 1000 of gain x 4%, income past the threshold
    assert year["state_tax"] == round((240000 + 1000) * 0.05, 2)


def test_tests_say_when_the_leading_plan_changes() -> None:
    params = _params({"name": "Convert", "why": "x", "actions": [{"type": "roth_convert", "year": 2026, "amount": 10000.0}]},
                     accounts={"traditional": 50000.0, "traditional_basis": 0.0, "roth": 0.0},
                     assumptions={"growth": 0.0, "exit_long_term": 0.15, "exit_ordinary": 0.05, "state_rate": 0.0},
                     tests=[{"name": "Higher tax later", "why": "Rates rise", "changes": {"exit_ordinary": 0.40}}, {"name": "Lower tax later", "why": "Retired", "changes": {"exit_ordinary": 0.02}}])
    out = _run(params)
    assert out["leading"] == "Do nothing"
    rows = {t["name"]: t for t in out["tests"]}
    assert rows["Higher tax later"]["leading"] == "Convert" and rows["Higher tax later"]["flips"] is True
    assert rows["Lower tax later"]["flips"] is False
    assert out["deciding_assumptions"] == ["Higher tax later"]
    assert _flag(out, "RANKING_FLIPS")


def test_flags_for_weak_rules_and_wash_sales() -> None:
    table = {**RULE_YEAR, "status": "projected"}
    rules = [{**_rule("capital_gains"), "primary": False}, *CITED[1:]]
    # a sale at a loss with other shares of the same stock bought in the last 30 days; the shares sold do not count
    book = {**BOOK, "open_lots": [_lot("WWW", 100.0, 3000.0, 20.0, "2025-01-10", "2026-01-11"), _lot("WWW", 10.0, 200.0, 20.0, "2026-10-20", "2027-10-21")]}
    out = _run(_params({"name": "H", "why": "x", "actions": [_sell("WWW", date="2026-11-10")]}, rule_tables={"2026": RULE_YEAR, "2027": table}, rules=rules, book=book))
    assert "2027" in _flag(out, "PROJECTED_RULES")
    assert "capital_gains" in _flag(out, "SECONDARY_SOURCE")
    assert "WWW" in _flag(out, "WASH_SALE_RISK")
    assert _flag(out, "NOT_MODELLED")


def test_selling_the_only_recent_lot_is_no_wash_sale() -> None:
    book = {**BOOK, "open_lots": [_lot("WWW", 100.0, 3000.0, 20.0, "2026-10-20", "2027-10-21")]}
    out = _run(_params({"name": "H", "why": "x", "actions": [_sell("WWW", date="2026-11-10")]}, book=book))
    assert _flag(out, "WASH_SALE_RISK") is None


def test_a_balance_due_and_a_short_pot_are_flagged() -> None:
    params = _params({"name": "Convert", "why": "x", "actions": [{"type": "roth_convert", "year": 2026, "amount": 40000.0}]}, accounts={"traditional": 50000.0, "traditional_basis": 0.0, "roth": 0.0})
    params["income"]["2026"]["withheld"] = 5000.0
    out = _run(params)
    assert "Convert" in _flag(out, "BALANCE_DUE")
    assert "Convert" in _flag(out, "PAID_FROM_ELSEWHERE") and _plan(out, "Convert")["end"]["pot"] < 0


def test_a_sale_cannot_exceed_what_is_held_or_come_after_the_book() -> None:
    with pytest.raises(ValueError, match="more than"):
        _run(_params({"name": "S", "why": "x", "actions": [_sell(units=101.0)]}))
    with pytest.raises(ValueError, match="not held"):
        _run(_params({"name": "S", "why": "x", "actions": [_sell("ZZZ")]}))


@pytest.mark.parametrize("mutate, needle", [
    (lambda p: p["rule_tables"].pop("2027"), "2027"),
    (lambda p: p["rule_tables"]["2026"].__setitem__("source", ""), "source"),
    (lambda p: p["rule_tables"].__setitem__("2026", {**RULE_YEAR, "date": "2027-02-01"}), "after"),
    (lambda p: p["rule_tables"].__setitem__("2026", {**RULE_YEAR, "status": "rumor"}), "status"),
    (lambda p: p["rule_tables"].__setitem__("2026", {**RULE_YEAR, "ordinary": [[50000.0, 0.10]]}), "open"),
    (lambda p: p["rule_tables"].__setitem__("2026", {**RULE_YEAR, "ordinary": [[50000.0, 1.5], [None, 0.2]]}), "rate"),
    (lambda p: p["income"].pop("2027"), "2027"),
    (lambda p: p.update(filing="joint-ish"), "filing"),
    (lambda p: p["plans"].__setitem__(0, {"name": "First", "why": "x", "actions": [_sell()]}), "no actions"),
    (lambda p: p["plans"].append({"name": "Do nothing", "why": "y", "actions": []}), "twice"),
    (lambda p: p["plans"].append({"name": "X", "why": "y", "actions": [{"type": "wish", "year": 2026}]}), "type"),
    (lambda p: p["plans"].append({"name": "X", "why": "y", "actions": [_sell(year=2030)]}), "2030"),
    (lambda p: p["plans"].append({"name": "X", "why": "y", "actions": [{"type": "roth_convert", "year": 2026, "amount": -5.0}]}), "amount"),
    (lambda p: p["plans"].append({"name": "X", "why": "y", "actions": [{"type": "roth_convert", "year": 2026, "amount": 5.0}]}), "more"),
    (lambda p: p["assumptions"].update(growth=None), "growth"),
    (lambda p: p["tests"].append({"name": "T", "why": "y", "changes": {"gorwth": 0.1}}), "gorwth"),
    (lambda p: p["rules"].pop(0), "capital_gains"),
    (lambda p: p["rules"][0].pop("date"), "date"),
])
def test_uncited_or_impossible_inputs_are_rejected(mutate, needle) -> None:
    params = copy.deepcopy(_params({"name": "Sell", "why": "x", "actions": [_sell()]}))
    mutate(params)
    with pytest.raises(ValueError, match=needle):
        _run(params)


def test_a_conversion_needs_its_rule_cited() -> None:
    params = _params({"name": "C", "why": "x", "actions": [{"type": "roth_convert", "year": 2026, "amount": 1000.0}]}, accounts={"traditional": 5000.0, "traditional_basis": 0.0, "roth": 0.0}, rules=[_rule("capital_gains"), _rule("niit"), _rule("loss_limit")])
    with pytest.raises(ValueError, match="roth_conversion"):
        _run(params)


def test_the_cli_exits_2_with_an_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"as_of": AS_OF})))
    with pytest.raises(SystemExit) as exc:
        load_script(PLANS).main()
    assert exc.value.code == 2 and "error" in json.loads(capsys.readouterr().out)


def _good_params() -> dict:
    return _params({"name": "Sell", "why": "Realize at a known rate", "actions": [_sell()]}, tests=[{"name": "Faster growth", "why": "Markets", "changes": {"growth": 0.05}}])


def _page(**over) -> dict:
    return {"as_of": AS_OF, "headline": "The comparison turns on the tax rate at withdrawal, which nobody can know yet.", "summary": "Selling costs tax now and little later.",
            "plans": _run(_good_params()), "missing_roles": ["Red team"], "notes": [], **over}


def test_render_builds_the_page(tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page()))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0, res
    assert res["title"] == "Tax Plan Comparison" and res["plans"] == 2 and res["flags"] >= 2
    html = out.read_text()
    for section in ("Plans compared", "Year by year", "What decides it", "Rules behind the math", "Flags", "Not modelled"):
        assert section in html


@requires_chrome
def test_every_card_on_the_page_has_help(tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page()))
    assert_page_help(render_and_audit(RENDER, ["--in", str(src)], tmp_path, capsys))


@pytest.mark.parametrize("over, needle", [
    ({"headline": "You should convert now"}, "should"),
    ({"headline": " ".join(["word"] * 26)}, "25 words"),
    ({"headline": ""}, "headline"),
    ({"summary": "We recommend the second plan"}, "recommend"),
    ({"plans": {}}, "plans"),
])
def test_render_rejects(over, needle, tmp_path, capsys) -> None:
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page(**over)))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"]


@pytest.fixture
def saved(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "data"))
    src = tmp_path / "page.json"
    src.write_text(json.dumps(_page()))
    rc, res = run_json(load_script(STORE), ["save", "--in", str(src), "--source", "https://claude.ai/artifact/x"], capsys)
    assert rc == 0, res
    return tmp_path


def _report(tmp_path, realized=(), lots=None) -> str:
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"as_of": AS_OF, "open_lots": lots if lots is not None else BOOK["open_lots"], "realized": list(realized), "summary": {"loss_carryforward": 0.0}}))
    return str(path)


def test_list_shows_saved_comparisons(saved, capsys) -> None:
    rc, res = run_json(load_script(STORE), ["list"], capsys)
    assert rc == 0 and res["reviews"][0]["as_of"] == AS_OF and res["reviews"][0]["plans"] == 2


def test_check_reruns_on_the_new_book_with_nothing_changed(saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), ["check", "--report", _report(saved), "--as-of", "2026-11-05"], capsys)
    assert rc == 0, out
    row = next(p for p in out["plans"] if p["name"] == "Sell")
    assert row["then"]["after_tax_wealth"] == row["now"]["after_tax_wealth"]
    assert out["review_age_days"] == 4 and out["leading_then"] == out["leading_now"]


def test_check_lists_actions_due_and_what_was_done(saved, capsys) -> None:
    realized = [{"symbol": "AAA", "units": 40.0, "sell_date": "2026-11-20", "gain": 400.0}]
    rc, out = run_json(load_script(STORE), ["check", "--report", _report(saved, realized), "--as-of", "2026-12-01"], capsys)
    assert rc == 0, out
    due = out["actions_due"][0]
    assert due["plan"] == "Sell" and due["symbol"] == "AAA" and due["units"] == 100.0 and due["units_sold_so_far"] == 40.0
    assert due["days_left"] == 30
    assert any("year end" in r for r in out["rerun_reasons"])


def test_check_copes_with_lots_sold_since(saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), ["check", "--report", _report(saved, lots=[BOOK["open_lots"][1]]), "--as-of", "2026-11-05"], capsys)
    assert rc == 0, out
    row = next(p for p in out["plans"] if p["name"] == "Sell")
    assert row["short"] == ["AAA"]


def test_check_is_due_in_a_new_year_or_when_old(saved, capsys) -> None:
    rc, out = run_json(load_script(STORE), ["check", "--report", _report(saved), "--as-of", "2027-01-05"], capsys)
    assert rc == 0, out
    assert any("calendar year" in r for r in out["rerun_reasons"])
    rc, out = run_json(load_script(STORE), ["check", "--report", _report(saved), "--as-of", "2027-06-01"], capsys)
    assert rc == 0 and any("180 days" in r for r in out["rerun_reasons"])


def test_check_with_nothing_saved_exits_2(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "empty"))
    rc, out = run_json(load_script(STORE), ["check", "--report", _report(tmp_path)], capsys)
    assert rc == 2 and "no saved" in out["error"]


def _book_with(year=2026, st=0.0, lt=0.0, carry_out=0.0, carry_in=0.0, lots=None) -> dict:
    history = [{"year": year - 1, "net": 0.0, "deductible": 0.0, "carryforward": carry_in}, {"year": year, "net": st + lt - carry_in, "deductible": 0.0, "carryforward": carry_out}]
    return {"as_of": AS_OF, "year": year, "open_lots": lots if lots is not None else [_lot()],
            "summary": {"short_term_net": st, "long_term_net": lt, "loss_carryforward": carry_out, "carryforward_history": history}}


def test_gains_realized_this_year_are_taxed_in_every_plan_and_are_not_activity() -> None:
    out = _run(_params(book=_book_with(lt=10000.0)))
    row = _plan(out, "Do nothing")["years"][0]
    assert row["long_term_net"] == 10000.0
    assert row["capital_gains_tax"] > 0
    assert row["activity_tax"] == 0.0
    assert _plan(out, "Do nothing")["end"]["pot"] == 0.0
    assert _flag(out, "PAID_FROM_ELSEWHERE") is None


def test_a_harvested_loss_offsets_a_gain_already_realized_this_year() -> None:
    loser = _lot("CCC", 100.0, 5000.0, 30.0)
    out = _run(_params({"name": "Harvest", "why": "x", "actions": [_sell("CCC")]}, book=_book_with(lt=2000.0, lots=[loser])))
    row = _plan(out, "Harvest")["years"][0]
    assert row["long_term_net"] == 0.0
    assert row["activity_tax"] < 0


def test_this_years_loss_is_not_counted_twice_through_the_carryforward() -> None:
    out = _run(_params(book=_book_with(st=-5000.0, carry_out=2000.0)))
    row = _plan(out, "Do nothing")["years"][0]
    assert row["loss_deducted"] == 3000.0
    assert row["carry_out"] == {"short": 2000.0, "long": 0.0}
    assert row["activity_tax"] == 0.0


def test_the_carry_into_the_report_year_opens_the_first_year() -> None:
    out = _run(_params(book=_book_with(lt=1000.0, carry_in=4000.0)))
    row = _plan(out, "Do nothing")["years"][0]
    assert row["long_term_net"] == -3000.0
    assert row["loss_deducted"] == 3000.0


def test_a_report_from_an_earlier_year_opens_with_its_carry_out_and_no_realized_gains() -> None:
    out = _run(_params(book=_book_with(year=2025, lt=9000.0, carry_out=4000.0)))
    row = _plan(out, "Do nothing")["years"][0]
    assert row["long_term_net"] == -4000.0
    assert row["loss_deducted"] == 3000.0
    assert row["carry_out"]["long"] == 1000.0


def test_a_report_from_a_later_year_is_rejected() -> None:
    with pytest.raises(ValueError, match="later"):
        load_script(PLANS).run_plans(_params(book=_book_with(year=2027)))
