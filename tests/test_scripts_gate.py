"""Pre-trade discipline gate: checks an order against the journal's written plan and the ledger."""

from __future__ import annotations

import json

import pytest

from scripts_util import load_script, run_json
from second_opinion import ledger, market


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    (tmp_path / "installed.json").write_text('{"skills": [], "extras": {"trade-journal": true}}')  # the extra is opt-in
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: [{"symbol": s.upper(), "price": 100.0, "source": "yahoo", "realtime": False} for s in symbols])
    return tmp_path


def _gate(args: list[str], capsys):
    return run_json(load_script("trading/scripts/gate.py"), args, capsys)


def _journal(capsys, *extra: str, symbol: str = "AAPL"):
    return run_json(
        load_script("trade-journal/scripts/journal.py"),
        ["add", symbol, "--entry", "100", "--target", "130", "--stop", "90", "--horizon", "90", "--size", "10", "--thesis", "beat and raise", "--date", "2026-01-05", *extra],
        capsys,
    )


def _check(out: dict, rule: str) -> dict:
    return next(c for c in out["checks"] if c["rule"] == rule)


def test_buy_with_no_written_plan_is_review_not_no_go(data_dir, capsys) -> None:
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert rc == 0 and out["decision"] == "REVIEW"
    assert _check(out, "written_plan")["status"] == "review" and "no written plan for AAPL" in out["reasons"][0]
    assert out["journal_id"] is None and out["recorded"] is False


def test_buy_inside_the_plan_is_go_and_recorded_on_the_entry(data_dir, capsys) -> None:
    _journal(capsys)
    rc, out = _gate(["AAPL", "BUY", "5", "--as-of", "2026-01-06"], capsys)
    assert rc == 0 and out["decision"] == "GO" and out["reasons"] == []
    assert out["journal_id"] == "j-2026-01-05-aapl-1"
    assert {c["rule"]: c["status"] for c in out["checks"]} == {
        "written_plan": "pass", "stop_predefined": "pass", "size_within_plan": "pass", "risk_within_plan": "pass", "recent_loss": "skip",
    }
    assert out["price"] == 100.0 and out["price_source"] == "quote"
    book = json.loads((data_dir / "journal.json").read_text())
    gates = book["entries"][0]["gates"]
    assert out["recorded"] is True and len(gates) == 1 and gates[0]["decision"] == "GO" and gates[0]["quantity"] == 5.0


def test_buy_without_a_predefined_stop_is_no_go(data_dir, capsys) -> None:
    run_json(load_script("trade-journal/scripts/journal.py"), ["add", "AAPL", "--entry", "100", "--size", "10", "--thesis", "no stop yet", "--date", "2026-01-05"], capsys)
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert rc == 0 and out["decision"] == "NO_GO"
    assert _check(out, "stop_predefined")["status"] == "fail"
    assert _check(out, "risk_within_plan")["status"] == "skip"


def test_buy_above_the_journaled_size_is_no_go(data_dir, capsys) -> None:
    _journal(capsys)
    rc, out = _gate(["AAPL", "BUY", "12"], capsys)
    assert out["decision"] == "NO_GO" and _check(out, "size_within_plan")["status"] == "fail"
    assert "12" in _check(out, "size_within_plan")["detail"] and "10" in _check(out, "size_within_plan")["detail"]


def test_buy_with_no_journaled_size_is_review(data_dir, capsys) -> None:
    run_json(load_script("trade-journal/scripts/journal.py"), ["add", "AAPL", "--entry", "100", "--stop", "90", "--thesis", "unsized", "--date", "2026-01-05"], capsys)
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert out["decision"] == "REVIEW" and _check(out, "size_within_plan")["status"] == "review"
    assert _check(out, "risk_within_plan")["status"] == "skip"


def test_buy_whose_actual_risk_exceeds_planned_risk_is_no_go(data_dir, capsys) -> None:
    _journal(capsys)  # planned risk: 10 units x (100 - 90) = 100
    rc, out = _gate(["AAPL", "BUY", "10", "--limit", "104"], capsys)  # actual: 10 x (104 - 90) = 140
    assert out["decision"] == "NO_GO"
    risk = _check(out, "risk_within_plan")
    assert risk["status"] == "fail" and risk["actual_risk"] == 140.0 and risk["planned_risk"] == 100.0
    assert out["price"] == 104.0 and out["price_source"] == "limit"


def test_buy_when_no_price_is_available_is_review(data_dir, capsys, monkeypatch) -> None:
    _journal(capsys)
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: (_ for _ in ()).throw(RuntimeError("yahoo down")))
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert out["decision"] == "REVIEW" and _check(out, "risk_within_plan")["status"] == "review"
    assert out["price"] is None and out["price_source"] is None


def test_buy_after_a_recent_realized_loss_is_review(data_dir, capsys) -> None:
    _journal(capsys, symbol="MSFT")
    book = ledger.load(data_dir / "ledger.json")
    ledger.merge(book, [
        {"date": "2026-03-02", "type": "BUY", "symbol": "AAPL", "units": 10, "price": 100.0, "amount": -1000.0, "fee": 0.0, "reinvested": False, "description": "BUY", "security_name": None, "account_id": "a", "source_id": "1"},
        {"date": "2026-03-09", "type": "SELL", "symbol": "AAPL", "units": 10, "price": 90.0, "amount": 900.0, "fee": 0.0, "reinvested": False, "description": "SELL", "security_name": None, "account_id": "a", "source_id": "2"},
    ], source="test")
    ledger.save(book, data_dir / "ledger.json")
    rc, out = _gate(["MSFT", "BUY", "5", "--as-of", "2026-03-10"], capsys)
    assert out["decision"] == "REVIEW"
    loss = _check(out, "recent_loss")
    assert loss["status"] == "review" and "AAPL" in loss["detail"] and "2026-03-09" in loss["detail"]
    rc, out = _gate(["MSFT", "BUY", "5", "--as-of", "2026-03-20"], capsys)
    assert out["decision"] == "GO" and _check(out, "recent_loss")["status"] == "pass"
    rc, out = _gate(["MSFT", "BUY", "5", "--as-of", "2026-03-10", "--cooldown-days", "0"], capsys)
    assert out["decision"] == "GO"


def test_sell_of_a_journaled_symbol_is_go_and_annotated_against_the_plan(data_dir, capsys) -> None:
    _journal(capsys)
    rc, out = _gate(["AAPL", "SELL", "10", "--limit", "89", "--as-of", "2026-02-04"], capsys)
    assert rc == 0 and out["decision"] == "GO" and out["reasons"] == []
    exit_check = _check(out, "exit_vs_plan")
    assert exit_check["status"] == "pass" and exit_check["exit"] == "at_or_through_stop" and exit_check["days_held"] == 30 and exit_check["within_horizon"] is True
    rc, out = _gate(["AAPL", "SELL", "10", "--limit", "131", "--as-of", "2026-06-01"], capsys)
    assert _check(out, "exit_vs_plan")["exit"] == "at_or_through_target" and _check(out, "exit_vs_plan")["within_horizon"] is False
    rc, out = _gate(["AAPL", "SELL", "10", "--limit", "110"], capsys)
    assert _check(out, "exit_vs_plan")["exit"] == "between"
    book = json.loads((data_dir / "journal.json").read_text())
    assert len(book["entries"][0]["gates"]) == 3 and book["entries"][0]["gates"][0]["side"] == "SELL"


def test_sell_of_an_unjournaled_symbol_is_go_and_not_gated(data_dir, capsys) -> None:
    rc, out = _gate(["BND", "SELL", "100"], capsys)
    assert rc == 0 and out["decision"] == "GO" and out["journal_id"] is None
    assert _check(out, "written_plan")["status"] == "skip" and "not gated" in _check(out, "written_plan")["detail"]
    assert not (data_dir / "journal.json").exists()


def test_closed_entries_do_not_count_as_a_plan(data_dir, capsys) -> None:
    _journal(capsys)
    run_json(load_script("trade-journal/scripts/journal.py"), ["close", "j-2026-01-05-aapl-1", "--price", "120", "--date", "2026-02-01"], capsys)
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert out["decision"] == "REVIEW" and out["journal_id"] is None


def test_bad_arguments_exit_2(data_dir, capsys) -> None:
    rc, out = _gate(["AAPL", "HOLD", "5"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
    rc, out = _gate(["AAPL", "BUY", "0"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
    rc, out = _gate(["AAPL", "BUY", "5", "--as-of", "yesterday"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_buy_with_a_thesis_invalidation_but_no_stop_is_review_not_no_go(data_dir, capsys) -> None:
    run_json(
        load_script("trade-journal/scripts/journal.py"),
        ["add", "AAPL", "--entry", "100", "--size", "10", "--thesis", "no price stop", "--invalidation", "a guidance cut, or the product slips past the quarter " + "x" * 200, "--date", "2026-01-05"],
        capsys,
    )
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert rc == 0 and out["decision"] == "REVIEW"
    stop = _check(out, "stop_predefined")
    assert stop["status"] == "review" and stop["detail"].startswith("thesis-based invalidation recorded: a guidance cut")
    assert len(stop["detail"]) == len("thesis-based invalidation recorded: ") + 120
    assert _check(out, "risk_within_plan") == {"rule": "risk_within_plan", "status": "skip", "detail": "no price stop (thesis-based invalidation)"}
    assert _check(out, "size_within_plan")["status"] == "pass"
    assert "add_rule" not in {c["rule"] for c in out["checks"]}
    assert out["reasons"] == [stop["detail"]]


def test_buy_with_neither_stop_nor_invalidation_stays_no_go(data_dir, capsys) -> None:
    rc, _ = run_json(load_script("trade-journal/scripts/journal.py"), ["add", "AAPL", "--entry", "100", "--size", "10", "--thesis", "bare", "--invalidation", "   ", "--date", "2026-01-05"], capsys)
    assert rc == 2  # an all-whitespace invalidation is rejected at add time, so the entry below has none
    run_json(load_script("trade-journal/scripts/journal.py"), ["add", "AAPL", "--entry", "100", "--size", "10", "--thesis", "bare", "--date", "2026-01-05"], capsys)
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert out["decision"] == "NO_GO" and _check(out, "stop_predefined")["status"] == "fail"


def test_buy_at_or_below_the_planned_add_price_passes_the_add_rule(data_dir, capsys) -> None:
    _journal(capsys, "--add-at", "95", "--add-qty", "20")  # size 10 at 100, stop 90; planned add 20 at 95
    rc, out = _gate(["AAPL", "BUY", "25", "--limit", "95", "--as-of", "2026-01-06"], capsys)
    assert rc == 0, out
    assert out["decision"] == "GO" and out["reasons"] == []
    add = _check(out, "add_rule")
    assert add["status"] == "pass" and add["detail"] == "price within the planned add rule (add at 95 for 20)" and add["add_price"] == 95.0 and add["add_qty"] == 20.0
    assert _check(out, "size_within_plan")["status"] == "pass" and "plus a planned add of 20" in _check(out, "size_within_plan")["detail"]
    risk = _check(out, "risk_within_plan")
    assert risk["status"] == "pass" and risk["planned_risk"] == 200.0 and risk["actual_risk"] == 125.0  # 10x10 + 20x5 planned; 25x5 actual
    # size above base + add is still NO_GO
    rc, out = _gate(["AAPL", "BUY", "31", "--limit", "95", "--as-of", "2026-01-06"], capsys)
    assert out["decision"] == "NO_GO" and _check(out, "size_within_plan")["status"] == "fail" and "(30)" in _check(out, "size_within_plan")["detail"]


def test_buy_above_the_planned_add_price_is_judged_on_the_base_plan(data_dir, capsys) -> None:
    _journal(capsys, "--add-at", "95", "--add-qty", "20")
    rc, out = _gate(["AAPL", "BUY", "5", "--limit", "98", "--as-of", "2026-01-06"], capsys)
    assert out["decision"] == "GO"
    add = _check(out, "add_rule")
    assert add["status"] == "skip" and add["detail"] == "price 98 is above the planned add price 95"
    assert _check(out, "size_within_plan")["detail"] == "5 of a planned 10" and _check(out, "risk_within_plan")["planned_risk"] == 100.0
    rc, out = _gate(["AAPL", "BUY", "25", "--limit", "98", "--as-of", "2026-01-06"], capsys)
    assert out["decision"] == "NO_GO" and _check(out, "size_within_plan")["status"] == "fail"


def test_add_rule_without_a_price_is_skipped(data_dir, capsys, monkeypatch) -> None:
    _journal(capsys, "--add-at", "95", "--add-qty", "20")
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: (_ for _ in ()).throw(RuntimeError("yahoo down")))
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert out["decision"] == "REVIEW"
    assert _check(out, "add_rule") == {"rule": "add_rule", "status": "skip", "detail": "no price available to compare with the planned add", "add_price": 95.0, "add_qty": 20.0}


def test_without_the_trade_journal_skill_the_gate_skips(data_dir, capsys, monkeypatch, tmp_path) -> None:
    mod = load_script("trading/scripts/gate.py")
    monkeypatch.setattr(mod, "_JOURNAL_DIR", tmp_path / "absent")
    (data_dir / "journal.json").write_text("{corrupt")  # never read without the journal skill
    rc, out = run_json(mod, ["AAPL", "BUY", "5"], capsys)
    assert rc == 0 and out["decision"] == "SKIP"
    assert out["reasons"] == ["the trade-journal extra is not installed"]
    assert out["checks"] == [] and out["recorded"] is False and out["journal_id"] is None
    assert out["symbol"] == "AAPL" and out["side"] == "BUY" and out["quantity"] == 5.0


def test_without_the_trade_journal_skill_bad_arguments_still_fail(data_dir, capsys, monkeypatch, tmp_path) -> None:
    mod = load_script("trading/scripts/gate.py")
    monkeypatch.setattr(mod, "_JOURNAL_DIR", tmp_path / "absent")
    rc, out = run_json(mod, ["AAPL", "HOLD", "5"], capsys)
    assert rc == 2 and "BUY or SELL" in out["error"]


@pytest.mark.parametrize(
    "record",
    [None, '{"skills": [], "extras": {"trade-journal": false}}', '{"skills": ["trading"], "extras": {"follow_ups": true}}', "not json"],
)
def test_the_gate_skips_unless_the_record_turns_the_extra_on(data_dir, capsys, monkeypatch, record) -> None:
    """A marketplace install ships the trade-journal skill to everyone; the extra stays opt-in."""
    from second_opinion import config

    monkeypatch.setattr(config, "PLUGIN_ROOT", data_dir / "no-root")
    if record is None:
        (data_dir / "installed.json").unlink()
    else:
        (data_dir / "installed.json").write_text(record)
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert rc == 0 and out["decision"] == "SKIP"


def test_a_copy_install_record_listing_the_skill_turns_the_gate_on(data_dir, capsys) -> None:
    (data_dir / "installed.json").write_text('{"skills": ["trading", "trade-journal"], "extras": {"follow_ups": false}}')
    rc, out = _gate(["AAPL", "BUY", "5"], capsys)
    assert rc == 0 and out["decision"] == "REVIEW"  # no written plan yet
