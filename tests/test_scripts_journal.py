from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json
from second_opinion import ledger, market


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _add(capsys, *extra):
    return run_json(load_script("trade-journal/scripts/journal.py"), ["add", "AAPL", "--side", "long", "--entry", "100", "--target", "130", "--stop", "90", "--horizon", "90", "--conviction", "4", "--tag", "earnings", "--tag", "momentum", "--thesis", "beat and raise into WWDC", "--date", "2026-01-05", *extra], capsys)


def test_add_list_and_close(data_dir, capsys) -> None:
    rc, out = _add(capsys)
    assert rc == 0, out
    assert out["added"]["id"] == "j-2026-01-05-aapl-1" and out["added"]["planned_rr"] == 3.0 and out["journal_path"] == str(data_dir / "journal.json")
    rc, out = _add(capsys)
    assert rc == 0 and out["added"]["id"] == "j-2026-01-05-aapl-2"
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["list"], capsys)
    assert rc == 0 and out["count"] == 2 and [e["status"] for e in out["entries"]] == ["open", "open"]
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["close", "j-2026-01-05-aapl-1", "--price", "131", "--date", "2026-03-10", "--notes", "target hit"], capsys)
    assert rc == 0 and out["closed"]["status"] == "closed" and out["closed"]["closed"] == {"date": "2026-03-10", "price": 131.0, "notes": "target hit"}
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["list", "--status", "open"], capsys)
    assert rc == 0 and out["count"] == 1
    book = json.loads((data_dir / "journal.json").read_text())
    assert book["entries"][0]["status"] == "closed" and book["entries"][0]["thesis"] == "beat and raise into WWDC"


def test_add_validation(data_dir, capsys) -> None:
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["add", "AAPL", "--entry", "100", "--target", "90", "--stop", "110", "--thesis", "levels backwards"], capsys)
    assert rc == 2 and "target must be above" in out["error"]
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["add", "AAPL", "--entry", "100"], capsys)
    assert rc == 2 and "--thesis" in out["error"]
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["close", "nope", "--price", "1"], capsys)
    assert rc == 2 and "no journal entry" in out["error"]


def test_review_matches_ledger_round_trips(data_dir, monkeypatch, capsys) -> None:
    _add(capsys)
    book = ledger.load(data_dir / "ledger.json")
    ledger.merge(book, [
        {"date": "2026-01-06", "type": "BUY", "symbol": "AAPL", "units": 10, "price": 100.0, "amount": -1000.0, "fee": 0.0, "reinvested": False, "description": "BUY", "security_name": None, "account_id": "a", "source_id": "1"},
        {"date": "2026-03-10", "type": "SELL", "symbol": "AAPL", "units": 10, "price": 131.0, "amount": 1310.0, "fee": 0.0, "reinvested": False, "description": "SELL", "security_name": None, "account_id": "a", "source_id": "2"},
    ], source="test")
    ledger.save(book, data_dir / "ledger.json")
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    monkeypatch.setattr(market, "day_changes", lambda symbols: {})
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    e = out["entries"][0]
    assert e["matched"] is True and e["exit"] == "target hit" and e["realized_return"] == 0.31 and e["source"] == "ledger"
    assert out["summary"]["matched_to_ledger"] == 1 and out["sources"] == {"journal": str(data_dir / "journal.json"), "ledger": str(data_dir / "ledger.json"), "round_trips": 1}


def test_review_without_ledger_uses_journal_closes(data_dir, capsys) -> None:
    _add(capsys)
    run_json(load_script("trade-journal/scripts/journal.py"), ["close", "j-2026-01-05-aapl-1", "--price", "88", "--date", "2026-02-01"], capsys)
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review", "--as-of", "2026-09-04"], capsys)
    assert rc == 0 and out["entries"][0]["exit"] == "stopped" and out["entries"][0]["source"] == "journal" and out["sources"]["ledger"] is None


def test_review_empty_journal_exit_2(data_dir, capsys) -> None:
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review"], capsys)
    assert rc == 2 and "journal.py add" in out["error"]


def test_journalreview_math_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    params = {"as_of": "2026-09-04", "entries": [{"id": "j1", "date": "2026-01-05", "symbol": "AAPL", "side": "long", "thesis": "t", "entry_price": 100, "target": 130, "stop": 90, "horizon_days": 90, "conviction": 3, "tags": [], "status": "open", "closed": None}], "round_trips": []}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(params)))
    load_script("trade-journal/scripts/journalreview.py").main()
    assert json.loads(capsys.readouterr().out)["summary"]["open"] == 1


def test_amend_updates_entry_and_records_revision(data_dir, capsys) -> None:
    _add(capsys)
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["amend", "j-2026-01-05-aapl-1", "--stop", "85", "--thesis", "thesis broke, tightening risk"], capsys)
    assert rc == 0, out
    assert out["amended"]["stop"] == 85.0 and out["amended"]["thesis"] == "thesis broke, tightening risk"
    assert out["amended"]["planned_rr"] == round(30 / 15, 4) and out["amended"]["status"] == "open"
    assert out["revision"]["changes"] == {"stop": {"from": 90.0, "to": 85.0}, "thesis": {"from": "beat and raise into WWDC", "to": "thesis broke, tightening risk"}}
    assert out["revision"]["at"]
    book = json.loads((data_dir / "journal.json").read_text())
    assert book["entries"][0]["revisions"] == [out["revision"]]
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["amend", "j-2026-01-05-aapl-1", "--target", "125"], capsys)
    assert rc == 0 and out["amended"]["target"] == 125.0 and len(out["amended"]["revisions"]) == 2
    assert out["revision"]["changes"] == {"target": {"from": 130.0, "to": 125.0}}


def test_amend_validation(data_dir, capsys) -> None:
    _add(capsys)
    jid = "j-2026-01-05-aapl-1"
    cases = [
        (["amend", jid], "at least one of"),
        (["amend", "nope", "--stop", "80"], "no journal entry"),
        (["amend", jid, "--stop", "90"], "nothing to amend"),
        (["amend", jid, "--thesis", "   "], "--thesis"),
        (["amend", jid, "--stop", "110"], "stop below"),
        (["amend", jid, "--target", "90", "--stop", "110"], "target must be above"),
    ]
    for argv, msg in cases:
        rc, out = run_json(load_script("trade-journal/scripts/journal.py"), argv, capsys)
        assert rc == 2, (argv, out)
        assert msg in out["error"], (argv, out)
    run_json(load_script("trade-journal/scripts/journal.py"), ["close", jid, "--price", "131", "--date", "2026-03-10"], capsys)
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["amend", jid, "--stop", "80"], capsys)
    assert rc == 2 and "only open entries" in out["error"]


def test_review_live_quotes_and_horizon(data_dir, monkeypatch, capsys) -> None:
    _add(capsys)
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    monkeypatch.setattr(market, "day_changes", lambda symbols: {"AAPL": {"price": 120.0, "previous_close": 118.0}})
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review", "--as-of", "2026-01-20"], capsys)
    assert rc == 0, out
    e = out["entries"][0]
    assert e["live_price"] == 120.0 and e["live_rr"] == 2.0 and e["days_left_in_horizon"] == 75
    monkeypatch.setattr(market, "day_changes", lambda symbols: {})
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review", "--as-of", "2026-01-20"], capsys)
    e = out["entries"][0]
    assert e["live_price"] is None and e["live_rr"] is None and e["days_left_in_horizon"] == 75
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review", "--as-of", "2026-06-01"], capsys)
    assert out["entries"][0]["days_left_in_horizon"] == 0  # clamped; STALE_OPEN flags it


def test_review_live_rr_null_without_levels(data_dir, monkeypatch, capsys) -> None:
    run_json(load_script("trade-journal/scripts/journal.py"), ["add", "MSFT", "--side", "long", "--entry", "200", "--thesis", "no levels yet"], capsys)
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    monkeypatch.setattr(market, "day_changes", lambda symbols: {"MSFT": {"price": 210.0, "previous_close": 205.0}})
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review"], capsys)
    assert rc == 0, out
    e = out["entries"][0]
    assert e["live_price"] == 210.0 and e["live_rr"] is None and e["days_left_in_horizon"] is None


def test_review_passes_close_history_for_mfe_mae(data_dir, monkeypatch, capsys) -> None:
    _add(capsys)
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {"AAPL": [{"date": "2026-01-06", "close": 110.0, "adj_close": 110.0, "volume": 1000}]})
    monkeypatch.setattr(market, "day_changes", lambda symbols: {})
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    e = out["entries"][0]
    assert e["mfe_pct"] == 0.1 and e["mae_pct"] == 0.1 and e["touch_order"] == "neither"


def test_review_flags_size_mismatch(data_dir, capsys, monkeypatch) -> None:
    _add(capsys, "--size", "10")
    book = ledger.load(data_dir / "ledger.json")
    ledger.merge(book, [
        {"date": "2026-01-06", "type": "BUY", "symbol": "AAPL", "units": 20, "price": 100.0, "amount": -2000.0, "fee": 0.0, "reinvested": False, "description": "BUY", "security_name": None, "account_id": "a", "source_id": "1"},
        {"date": "2026-03-10", "type": "SELL", "symbol": "AAPL", "units": 20, "price": 131.0, "amount": 2620.0, "fee": 0.0, "reinvested": False, "description": "SELL", "security_name": None, "account_id": "a", "source_id": "2"},
    ], source="test")
    ledger.save(book, data_dir / "ledger.json")
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    monkeypatch.setattr(market, "day_changes", lambda symbols: {})
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    flags = [f for f in out["flags"] if f["code"] == "SIZE_MISMATCH"]
    assert len(flags) == 1 and "j-2026-01-05-aapl-1" in flags[0]["message"]


def test_review_size_mismatch_within_tolerance(data_dir, capsys, monkeypatch) -> None:
    _add(capsys, "--size", "10")
    book = ledger.load(data_dir / "ledger.json")
    ledger.merge(book, [
        {"date": "2026-01-06", "type": "BUY", "symbol": "AAPL", "units": 11, "price": 100.0, "amount": -1100.0, "fee": 0.0, "reinvested": False, "description": "BUY", "security_name": None, "account_id": "a", "source_id": "1"},
        {"date": "2026-03-10", "type": "SELL", "symbol": "AAPL", "units": 11, "price": 131.0, "amount": 1441.0, "fee": 0.0, "reinvested": False, "description": "SELL", "security_name": None, "account_id": "a", "source_id": "2"},
    ], source="test")
    ledger.save(book, data_dir / "ledger.json")
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    monkeypatch.setattr(market, "day_changes", lambda symbols: {})
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["review", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert not [f for f in out["flags"] if f["code"] == "SIZE_MISMATCH"]


def _entry(data_dir, jid="j-2026-01-05-aapl-1") -> dict:
    return next(e for e in json.loads((data_dir / "journal.json").read_text())["entries"] if e["id"] == jid)


def test_add_with_invalidation_and_add_rule_creates_a_watchlist_rule(data_dir, capsys) -> None:
    rc, out = _add(capsys, "--invalidation", "guidance cut or WWDC slips", "--add-at", "95", "--add-qty", "20")
    assert rc == 0, out
    assert out["added"]["invalidation"] == "guidance cut or WWDC slips"
    assert out["added"]["add_rule"] == {"price": 95.0, "qty": 20.0}
    assert out["watchlist_rule"] == {
        "symbol": "AAPL", "type": "price_below", "value": 95.0,
        "note": "journal j-2026-01-05-aapl-1: planned add at 95 for 20", "watchlist_path": str(data_dir / "watchlist.json"),
    }
    assert "watchlist_error" not in out
    book = json.loads((data_dir / "watchlist.json").read_text())
    entry = next(w for w in book["watchlist"] if w["symbol"] == "AAPL")
    assert entry["rules"] == [{"type": "price_below", "value": 95.0}] and entry["added_price"] == 100.0 and "j-2026-01-05-aapl-1" in entry["note"]
    # list output carries the new fields unchanged
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["list"], capsys)
    assert rc == 0 and out["entries"][0]["add_rule"] == {"price": 95.0, "qty": 20.0} and out["entries"][0]["invalidation"] == "guidance cut or WWDC slips"
    # a plain add stores nulls and touches no watchlist
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["add", "MSFT", "--entry", "200", "--thesis", "plain"], capsys)
    assert rc == 0 and out["added"]["invalidation"] is None and out["added"]["add_rule"] is None and "watchlist_rule" not in out
    assert [w["symbol"] for w in json.loads((data_dir / "watchlist.json").read_text())["watchlist"]] == ["AAPL"]


def test_add_short_add_rule_creates_a_price_above_rule(data_dir, capsys) -> None:
    rc, out = run_json(load_script("trade-journal/scripts/journal.py"), ["add", "TSLA", "--side", "short", "--entry", "300", "--thesis", "fade", "--add-at", "315"], capsys)
    assert rc == 0, out
    assert out["added"]["add_rule"] == {"price": 315.0, "qty": None}
    assert out["watchlist_rule"]["type"] == "price_above" and out["watchlist_rule"]["value"] == 315.0 and out["watchlist_rule"]["note"].endswith("planned add at 315")


def test_add_rule_and_invalidation_validation(data_dir, capsys) -> None:
    cases = [
        (["add", "AAPL", "--entry", "100", "--thesis", "t", "--add-at", "105"], "--add-at must be below the entry for a long"),
        (["add", "AAPL", "--side", "short", "--entry", "100", "--thesis", "t", "--add-at", "95"], "--add-at must be above the entry for a short"),
        (["add", "AAPL", "--entry", "100", "--thesis", "t", "--add-qty", "5"], "--add-qty needs --add-at"),
        (["add", "AAPL", "--entry", "100", "--thesis", "t", "--add-at", "95", "--add-qty", "0"], "--add-qty must be above zero"),
        (["add", "AAPL", "--entry", "100", "--thesis", "t", "--add-at", "0"], "--add-at must be above zero"),
        (["add", "AAPL", "--entry", "100", "--thesis", "t", "--invalidation", "   "], "--invalidation cannot be empty"),
    ]
    for argv, msg in cases:
        rc, out = run_json(load_script("trade-journal/scripts/journal.py"), argv, capsys)
        assert rc == 2, (argv, out)
        assert msg in out["error"], (argv, out)
    assert not (data_dir / "journal.json").exists() and not (data_dir / "watchlist.json").exists()


def test_amend_invalidation_and_add_rule_record_revisions(data_dir, capsys) -> None:
    _add(capsys)
    jid = "j-2026-01-05-aapl-1"
    script = load_script("trade-journal/scripts/journal.py")
    rc, out = run_json(script, ["amend", jid, "--invalidation", "loses the 200-day on volume"], capsys)
    assert rc == 0, out
    assert out["amended"]["invalidation"] == "loses the 200-day on volume"
    assert out["revision"]["changes"] == {"invalidation": {"from": None, "to": "loses the 200-day on volume"}}
    assert "watchlist_rule" not in out
    rc, out = run_json(script, ["amend", jid, "--add-at", "94", "--add-qty", "15"], capsys)
    assert rc == 0, out
    assert out["revision"]["changes"] == {"add_rule": {"from": None, "to": {"price": 94.0, "qty": 15.0}}}
    assert out["watchlist_rule"]["type"] == "price_below" and out["watchlist_rule"]["value"] == 94.0
    # --add-qty alone re-sizes the existing add; --add-at alone keeps the planned quantity and replaces the watchlist rule
    rc, out = run_json(script, ["amend", jid, "--add-qty", "25"], capsys)
    assert rc == 0 and out["amended"]["add_rule"] == {"price": 94.0, "qty": 25.0}
    assert out["revision"]["changes"] == {"add_rule": {"from": {"price": 94.0, "qty": 15.0}, "to": {"price": 94.0, "qty": 25.0}}} and "watchlist_rule" not in out
    rc, out = run_json(script, ["amend", jid, "--add-at", "92"], capsys)
    assert rc == 0 and out["amended"]["add_rule"] == {"price": 92.0, "qty": 25.0} and out["watchlist_rule"]["value"] == 92.0
    rules = next(w for w in json.loads((data_dir / "watchlist.json").read_text())["watchlist"] if w["symbol"] == "AAPL")["rules"]
    assert rules == [{"type": "price_below", "value": 92.0}]
    assert len(_entry(data_dir)["revisions"]) == 4
    for argv, msg in [
        (["amend", jid, "--add-qty", "25"], "nothing to amend"),
        (["amend", jid, "--invalidation", "loses the 200-day on volume"], "nothing to amend"),
        (["amend", jid, "--add-at", "101"], "--add-at must be below the entry"),
        (["amend", jid, "--invalidation", " "], "--invalidation cannot be empty"),
    ]:
        rc, out = run_json(script, argv, capsys)
        assert rc == 2 and msg in out["error"], (argv, out)
    rc, out = run_json(script, ["add", "MSFT", "--entry", "200", "--thesis", "t", "--date", "2026-01-05"], capsys)
    rc, out = run_json(script, ["amend", "j-2026-01-05-msft-1", "--add-qty", "5"], capsys)
    assert rc == 2 and "--add-qty needs --add-at" in out["error"]


def test_add_rule_watchlist_failure_is_reported_not_fatal(data_dir, capsys, monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setitem(sys.modules, "watchlist", SimpleNamespace(upsert_rule=boom))
    rc, out = _add(capsys, "--add-at", "95", "--add-qty", "20")
    assert rc == 0, out
    assert out["added"]["add_rule"] == {"price": 95.0, "qty": 20.0} and "watchlist_rule" not in out
    assert out["watchlist_error"] == "RuntimeError: disk full"
    assert _entry(data_dir)["add_rule"] == {"price": 95.0, "qty": 20.0}
    assert not (data_dir / "watchlist.json").exists()
