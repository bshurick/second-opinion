from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from scripts_util import load_script, run_json
from second_opinion import market


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


@pytest.fixture
def yahoo(monkeypatch):
    calls: dict[str, list] = {"quotes": [], "history": []}

    def day_changes(symbols, hub=None):
        calls["quotes"].append(list(symbols))
        return {"AAPL": {"price": 148.0, "previous_close": 160.0}, "MSFT": {"price": 510.0, "previous_close": 505.0}}

    def close_histories(symbols, start):
        calls["history"].append(list(symbols))
        return {
            s: [
                {"date": "2026-01-02", "close": 200.0 if s == "AAPL" else 520.0, "adj_close": 0.0, "volume": 1_000_000},
                {"date": "2026-09-03", "close": 150.0 if s == "AAPL" else 510.0, "adj_close": 0.0, "volume": 2_000_000},
            ]
            for s in symbols
        }

    monkeypatch.setattr(market, "day_changes", day_changes)
    monkeypatch.setattr(market, "close_histories", close_histories)
    return calls


def test_add_list_remove(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "aapl", "--note", "buy zone", "--below", "150", "--day-move", "0.05", "--from-added", "-0.10", "--date", "2026-06-01"], capsys)
    assert rc == 0, out
    assert out["added"]["symbol"] == "AAPL" and out["added"]["added_price"] == 148.0 and [r["type"] for r in out["added"]["rules"]] == ["price_below", "day_move", "from_added"]
    assert out["watchlist_path"] == str(data_dir / "watchlist.json") and yahoo["quotes"] == [["AAPL"]]
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "MSFT", "--above", "500", "--drawdown", "0.15", "--added-price", "400"], capsys)
    assert rc == 0 and out["added"]["added_price"] == 400.0 and out["count"] == 2
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "AAPL", "--above", "180"], capsys)
    assert rc == 0 and out["added"]["symbol"] == "AAPL" and [r["type"] for r in out["added"]["rules"]] == ["price_below", "day_move", "from_added", "price_above"] and out["count"] == 2
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["list"], capsys)
    assert rc == 0 and [w["symbol"] for w in out["watchlist"]] == ["AAPL", "MSFT"]
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["remove", "msft"], capsys)
    assert rc == 0 and out["removed"] == "MSFT" and out["count"] == 1
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["remove", "NOPE"], capsys)
    assert rc == 2 and "not on the watchlist" in out["error"]


def test_check_evaluates_rules_with_quotes_and_highs(data_dir, yahoo, capsys) -> None:
    run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "AAPL", "--below", "150", "--added-price", "170", "--date", "2026-06-01"], capsys)
    run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "MSFT", "--drawdown", "0.15", "--added-price", "400"], capsys)
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["check", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["summary"]["triggered_rules"] == 1 and out["triggered"][0]["type"] == "price_below"
    rows = {r["symbol"]: r for r in out["watchlist"]}
    assert rows["AAPL"]["from_52w_high"] == -0.26 and rows["MSFT"]["from_52w_high"] == -0.0192
    assert out["sources"] == {"watchlist": str(data_dir / "watchlist.json"), "quotes": "yahoo", "highs": "yahoo"}
    assert yahoo["history"][-1] == ["AAPL", "MSFT"]


def test_check_without_history_and_empty(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["check"], capsys)
    assert rc == 2 and "watchlist.py add" in out["error"]
    run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "AAPL", "--below", "150"], capsys)
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["check", "--no-history"], capsys)
    assert rc == 0 and out["sources"]["highs"] is None and out["watchlist"][0]["from_52w_high"] is None


def test_check_closes_and_volumes_stay_aligned_across_a_volume_gap(data_dir, monkeypatch, capsys) -> None:
    def day_changes(symbols, hub=None):
        return {"AAPL": {"price": 148.0, "previous_close": 160.0}}

    def close_histories(symbols, start):
        # the middle row has a close but no volume (a data gap): it must be
        # dropped from BOTH series, not just from "volumes", so the two stay
        # aligned (closes[-1] and volumes[-1] refer to the same session)
        return {
            "AAPL": [
                {"date": "2026-08-01", "close": 100.0, "volume": 1_000_000},
                {"date": "2026-08-02", "close": 999.0, "volume": None},
                {"date": "2026-08-03", "close": 150.0, "volume": 2_000_000},
            ]
        }

    monkeypatch.setattr(market, "day_changes", day_changes)
    monkeypatch.setattr(market, "close_histories", close_histories)
    run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "AAPL", "--below", "150"], capsys)
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["check", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    # the 999.0 gap row is excluded from the 52w high too (highs and closes share the filter):
    # high is 150.0 (not 999.0), so from_52w_high is quote price 148.0 vs high 150.0
    assert out["watchlist"][0]["from_52w_high"] == round(148.0 / 150.0 - 1, 4)


def test_add_requires_a_rule_or_note_and_validates(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "AAPL"], capsys)
    assert rc == 2 and "at least one rule or --note" in out["error"]
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "AAPL", "--day-move", "-0.05"], capsys)
    assert rc == 2 and "--day-move must be positive" in out["error"]


def test_add_series_rules(data_dir, yahoo, capsys) -> None:
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "TSLA", "--ma-cross", "1", "--near-52w-high", "0.05", "--volume-spike", "2.0", "--added-price", "250"], capsys)
    assert rc == 0 and [r["type"] for r in out["added"]["rules"]] == ["near_52w_high", "ma_cross", "volume_spike"]
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "TSLA", "--ma-cross", "2"], capsys)
    assert rc == 2 and "--ma-cross must be +1" in out["error"]
    rc, out = run_json(load_script("watchlist/scripts/watchlist.py"), ["add", "TSLA", "--volume-spike", "0"], capsys)
    assert rc == 2 and "--volume-spike must be positive" in out["error"]


def test_check_states_new_still_acknowledged_snoozed(data_dir, yahoo, capsys) -> None:
    script = load_script("watchlist/scripts/watchlist.py")
    run_json(script, ["add", "AAPL", "--below", "150", "--added-price", "170"], capsys)
    run_json(script, ["add", "MSFT", "--above", "500", "--added-price", "400"], capsys)
    today = date.today().isoformat()
    rc, out = run_json(script, ["check"], capsys)
    assert rc == 0, out
    states = {(r["symbol"], t["type"]): t["state"] for r in out["watchlist"] for t in r["triggered"]}
    assert states == {("AAPL", "price_below"): "new", ("MSFT", "price_above"): "new"}
    assert out["summary"]["newly_triggered_symbols"] == 2 and out["summary"]["triggered_symbols"] == 2
    book = json.loads((data_dir / "watchlist.json").read_text())
    entry = next(w for w in book["watchlist"] if w["symbol"] == "AAPL")
    assert entry["last_fired"]["price_below"] == today
    rc, out = run_json(script, ["check"], capsys)
    states = {(r["symbol"], t["type"]): t["state"] for r in out["watchlist"] for t in r["triggered"]}
    assert states[("AAPL", "price_below")] == "still" and out["summary"]["newly_triggered_symbols"] == 0
    assert out["triggered"][0]["state"] == "still"
    rc, out = run_json(script, ["ack", "AAPL", "price_below"], capsys)
    assert rc == 0, out
    assert out["entry"]["acked"]["price_below"] == today and "last_fired" not in out["entry"]
    rc, out = run_json(script, ["check"], capsys)
    states = {(r["symbol"], t["type"]): t["state"] for r in out["watchlist"] for t in r["triggered"]}
    assert states[("AAPL", "price_below")] == "acknowledged" and out["summary"]["newly_triggered_symbols"] == 0
    book = json.loads((data_dir / "watchlist.json").read_text())
    entry = next(w for w in book["watchlist"] if w["symbol"] == "AAPL")
    assert entry["acked"]["price_below"] == today and "last_fired" not in entry
    # ack without a rule type stamps every rule of the entry
    rc, out = run_json(script, ["ack", "MSFT"], capsys)
    assert rc == 0 and out["acked"] == ["price_above"]
    # ack means seen today: the rule fires as new again on a later day
    rc, out = run_json(script, ["check", "--as-of", (date.today() + timedelta(days=1)).isoformat()], capsys)
    states = {(r["symbol"], t["type"]): t["state"] for r in out["watchlist"] for t in r["triggered"]}
    assert states[("AAPL", "price_below")] == "new"
    # invalid rule type and unknown symbols exit 2
    rc, out = run_json(script, ["ack", "AAPL", "bogus"], capsys)
    assert rc == 2 and "rule type must be one of" in out["error"]
    rc, out = run_json(script, ["ack", "TSLA"], capsys)
    assert rc == 2 and "not on the watchlist" in out["error"]


def test_snooze_defers_until_the_window_passes(data_dir, yahoo, capsys) -> None:
    script = load_script("watchlist/scripts/watchlist.py")
    run_json(script, ["add", "AAPL", "--below", "150", "--added-price", "170"], capsys)
    until = (date.today() + timedelta(days=7)).isoformat()
    rc, out = run_json(script, ["snooze", "aapl", "7"], capsys)
    assert rc == 0 and out == {"symbol": "AAPL", "snooze_until": until, "watchlist_path": str(data_dir / "watchlist.json")}
    rc, out = run_json(script, ["check"], capsys)
    states = {(r["symbol"], t["type"]): t["state"] for r in out["watchlist"] for t in r["triggered"]}
    assert states[("AAPL", "price_below")] == "snoozed" and out["summary"]["newly_triggered_symbols"] == 0
    book = json.loads((data_dir / "watchlist.json").read_text())
    entry = next(w for w in book["watchlist"] if w["symbol"] == "AAPL")
    assert "last_fired" not in entry
    rc, out = run_json(script, ["snooze", "AAPL", "0"], capsys)
    assert rc == 2 and "DAYS must be at least 1" in out["error"]
    rc, out = run_json(script, ["snooze", "TSLA", "7"], capsys)
    assert rc == 2 and "not on the watchlist" in out["error"]


def test_check_events(data_dir, yahoo, monkeypatch, capsys) -> None:
    script = load_script("watchlist/scripts/watchlist.py")
    run_json(script, ["add", "AAPL", "--below", "150"], capsys)
    run_json(script, ["add", "MSFT", "--above", "500"], capsys)
    calls: list[str] = []

    def next_events(symbol, today=None):
        calls.append(symbol)
        if symbol == "AAPL":
            return {"next_earnings": (date.today() + timedelta(days=5)).isoformat(), "next_ex_dividend": None}
        return {"next_earnings": None, "next_ex_dividend": None}

    monkeypatch.setattr(market, "next_events", next_events)
    rc, out = run_json(script, ["check", "--events"], capsys)
    assert rc == 0, out
    assert out["events"] == [{"symbol": "AAPL", "next_earnings": (date.today() + timedelta(days=5)).isoformat(), "next_ex_dividend": None, "earnings_in_5_days": True}]
    assert out["sources"]["events"] == "yahoo" and calls == ["AAPL", "MSFT"]
    rc, out = run_json(script, ["check"], capsys)
    assert rc == 0 and "events" not in out and "events" not in out["sources"]


def test_alerts_math_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    params = {"watchlist": [{"symbol": "X", "rules": [{"type": "price_above", "value": 1}]}], "quotes": {"X": {"price": 2.0, "previous_close": 1.5}}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(params)))
    load_script("watchlist/scripts/alerts.py").main()
    assert json.loads(capsys.readouterr().out)["summary"]["triggered_rules"] == 1


def test_alerts_math_series_rules_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    params = {
        "watchlist": [{"symbol": "X", "rules": [{"type": "ma_cross", "value": 1}, {"type": "volume_spike", "value": 2.0}]}],
        "quotes": {"X": {"price": 102.0, "previous_close": 100.0}},
        "closes": {"X": [100.0] * 249 + [200.0]},
        "volumes": {"X": [10.0] * 20 + [30.0]},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(params)))
    load_script("watchlist/scripts/alerts.py").main()
    out = json.loads(capsys.readouterr().out)
    assert [t["type"] for t in out["watchlist"][0]["triggered"]] == ["ma_cross", "volume_spike"]


def test_check_persists_the_last_result_and_summary_prints_text(data_dir, yahoo, capsys) -> None:
    script = load_script("watchlist/scripts/watchlist.py")
    rc = script.main(["summary"])
    text = capsys.readouterr().out
    assert rc == 0 and text.strip() == "Watchlist: no check has run yet (run watchlist.py check)."
    run_json(script, ["add", "AAPL", "--below", "150", "--added-price", "170", "--date", "2026-06-01"], capsys)
    run_json(script, ["add", "MSFT", "--above", "600", "--added-price", "400"], capsys)
    rc, out = run_json(script, ["check", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    saved = json.loads((data_dir / "watchlist-last-check.json").read_text())
    assert saved["as_of"] == "2026-09-04" and saved["checked_at"] and saved["triggered"] == out["triggered"] and saved["sources"] == out["sources"]
    rc = script.main(["summary"])
    text = capsys.readouterr().out
    assert rc == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)
    lines = text.rstrip("\n").split("\n")
    age = (date.today() - date(2026, 9, 4)).days
    assert lines[0] == f"Watchlist check as of 2026-09-04 ({age}d old):"
    assert lines[1].startswith("  ALERT AAPL: ") and "150" in lines[1]
    aapl = next(line for line in lines if line.startswith("  AAPL 148.0"))
    assert "day -7.5%" in aapl and "since added -12.9%" in aapl and "from 52w high -26.0%" in aapl and "waiting: none" in aapl
    msft = next(line for line in lines if line.startswith("  MSFT 510.0"))
    assert "waiting: price_above 600.0 (now 510.0)" in msft
    assert not any("next earnings" in line for line in lines)


def test_summary_text_renders_events_flags_and_seen_states(data_dir, capsys) -> None:
    script = load_script("watchlist/scripts/watchlist.py")
    saved = {
        "as_of": "2026-09-04",
        "triggered": [{"symbol": "AAPL", "type": "price_below", "state": "still", "message": "AAPL 148 below 150"}],
        "watchlist": [{"symbol": "AAPL", "price": 148.0, "day_change_pct": None, "since_added_pct": -0.1294, "from_52w_high": None, "untriggered": []}],
        "events": [{"symbol": "AAPL", "next_earnings": "2026-09-08", "next_ex_dividend": None, "earnings_in_5_days": True}],
        "flags": [{"code": "NO_QUOTE", "message": "no quote for TSLA"}],
    }
    text = script.summary_text(saved, today=date(2026, 9, 4))
    assert text.split("\n") == [
        "Watchlist check as of 2026-09-04 (today):",
        "  No new alerts.",
        "  (AAPL price_below still)",
        "  AAPL 148.0 day n/a, since added -12.9%, from 52w high n/a; waiting: none",
        "  AAPL next earnings 2026-09-08 (within 5 trading days); next ex-dividend None",
        "  flag: no quote for TSLA",
    ]
    (data_dir / "watchlist-last-check.json").write_text("{not json")
    rc = script.main(["summary"])
    out = capsys.readouterr().out
    assert rc == 0 and "not valid JSON" in out


def test_install_cron_prints_the_lines_and_changes_nothing(data_dir, capsys, monkeypatch) -> None:
    monkeypatch.delenv("SNAPTRADE_PY", raising=False)
    script = load_script("watchlist/scripts/watchlist.py")
    rc, out = run_json(script, ["install-cron"], capsys)
    assert rc == 0, out
    script_path = str(Path(script.__file__).resolve())
    assert out["schedule"] == "weekdays at 09:37 local time" and out["python"] == "python3" and out["script"] == script_path
    assert out["data_dir"] == str(data_dir) and out["last_check_file"] == str(data_dir / "watchlist-last-check.json")
    line = out["crontab_line"]
    assert line.startswith("37 9 * * 1-5 ") and f"SECOND_OPINION_DATA={data_dir}" in line and f"python3 {script_path} check --events" in line
    assert line.endswith(f"> {data_dir / 'logs' / 'watchlist' / 'check.log'} 2>&1")
    assert "session_start_hook" not in out and "settings_file" not in out  # the plugin ships that hook itself
    assert out["instructions"][0].startswith("Nothing was installed.")
    assert sorted(p.name for p in data_dir.iterdir()) == []  # nothing written, no crontab or settings touched
    (data_dir / "venv" / "bin").mkdir(parents=True)
    (data_dir / "venv" / "bin" / "python").write_text("")
    rc, out = run_json(script, ["install-cron", "--hour", "7", "--minute", "5"], capsys)
    assert rc == 0 and out["crontab_line"].startswith("5 7 * * 1-5 ") and out["python"] == str(data_dir / "venv" / "bin" / "python")
    monkeypatch.setenv("SNAPTRADE_PY", "/opt/py/bin/python")
    rc, out = run_json(script, ["install-cron"], capsys)
    assert rc == 0 and out["python"] == "/opt/py/bin/python"
    for argv in (["install-cron", "--hour", "24"], ["install-cron", "--minute", "60"], ["install-cron", "--hour", "-1"]):
        rc, out = run_json(script, argv, capsys)
        assert rc == 2 and "must be between" in out["error"], (argv, out)


def test_upsert_rule_creates_or_replaces_one_rule(data_dir, yahoo, capsys) -> None:
    script = load_script("watchlist/scripts/watchlist.py")
    saved = script.upsert_rule("aapl", "price_below", 95, note="journal j-1: planned add at 95", added_price=100.0)
    assert saved["count"] == 1 and saved["watchlist_path"] == str(data_dir / "watchlist.json")
    assert saved["entry"]["symbol"] == "AAPL" and saved["entry"]["added_price"] == 100.0 and saved["entry"]["rules"] == [{"type": "price_below", "value": 95.0}]
    assert saved["entry"]["note"] == "journal j-1: planned add at 95" and saved["entry"]["added"] == date.today().isoformat()
    run_json(script, ["add", "AAPL", "--above", "180"], capsys)
    saved = script.upsert_rule("AAPL", "price_below", 92, note="journal j-1: planned add at 92")
    assert saved["entry"]["rules"] == [{"type": "price_above", "value": 180.0}, {"type": "price_below", "value": 92.0}] and saved["count"] == 1
    assert yahoo["quotes"] == []  # the helper never fetches a quote
    with pytest.raises(Exception, match="rule type must be one of"):
        script.upsert_rule("AAPL", "bogus", 1)
