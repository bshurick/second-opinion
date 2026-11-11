"""The session inbox (setup/scripts/inbox.py): at most six lines, each with the sentence that handles it."""
from __future__ import annotations

import json
from datetime import date

import pytest
from scripts_util import load_script

TODAY = date(2026, 11, 10)


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _inbox():
    return load_script("get-started/scripts/inbox.py")


def _last_read(data, arrivals):
    (data / "portfolio-last-check.json").write_text(json.dumps({"as_of": "2026-11-09T10:00:00", "partial": False, "arrivals": arrivals}))


def _picks(data, picks):
    (data / "picks.json").write_text(json.dumps({"picks": picks}))


def _pick(sym, **kw):
    return {"symbol": sym, "kind": "deep", "added": "2026-08-01", "added_price": 10.0, "baseline_as_of": "2026-08-01", "checks": [], **kw}


def _watch(data, triggered, as_of="2026-11-05"):
    (data / "watchlist-last-check.json").write_text(json.dumps({"as_of": as_of, "triggered": triggered, "watchlist": []}))


def test_nothing_to_report_prints_nothing(data, capsys) -> None:
    assert _inbox().lines(TODAY) == []
    assert _inbox().main([]) == 0 and capsys.readouterr().out == ""


def test_cash_arrivals_are_one_line(data) -> None:
    _last_read(data, [{"kind": "cash", "account": "a1", "name": "Individual", "amount": 4210.0, "since": "2026-11-05"},
                      {"kind": "cash", "account": "a2", "name": "Joint", "amount": 500.0, "since": "2026-11-07"}])
    out = _inbox().lines(TODAY)
    assert out == ["Second Opinion, 1 thing:",
                   '- Cash: $4,210 arrived in Individual since Nov 5 and $500 in Joint since Nov 7.  "put the new cash to work"']


def test_vest_line(data) -> None:
    _last_read(data, [{"kind": "vest", "account": "a1", "name": "Individual", "symbol": "AMZN", "units": 12.0, "since": "2026-11-05"}])
    assert _inbox().lines(TODAY)[1] == '- Vest: 12 AMZN arrived in Individual since Nov 5.  "my RSUs vested"'


def test_picks_due_counts_and_awaiting_filings(data) -> None:
    _picks(data, [_pick("AAA", next_earnings="2026-11-03"), _pick("BBB", next_earnings="2026-10-20", awaiting_filing=True),
                  _pick("CCC", next_earnings="2027-01-30")])
    assert _inbox().lines(TODAY)[1] == '- Picks: 2 of 3 due for a re-check (1 awaiting a 10-Q).  "re-check my picks"'


def test_watchlist_one_alert_names_it(data) -> None:
    _watch(data, [{"symbol": "PRDO", "state": "new", "type": "from_added", "message": "PRDO is -15.9% since added at 33.10 (threshold -10.0%)"},
                  {"symbol": "LRN", "state": "still", "type": "from_added", "message": "old"}])
    assert _inbox().lines(TODAY)[1] == '- Watchlist: PRDO is -15.9% since added at 33.10 (threshold -10.0%), as of Nov 5.  "what happened to PRDO"'


def test_watchlist_several_alerts_are_one_line(data) -> None:
    _watch(data, [{"symbol": s, "state": "new", "message": f"{s} moved"} for s in ("PRDO", "LRN", "GL")])
    assert _inbox().lines(TODAY)[1] == '- Watchlist: 3 new alerts (PRDO, LRN, GL), as of Nov 5.  "show my watchlist alerts"'


def test_order_and_the_six_line_cap(data) -> None:
    _last_read(data, [{"kind": "cash", "account": "a1", "name": "Individual", "amount": 4210.0, "since": "2026-11-05"},
                      {"kind": "vest", "account": "a1", "name": "Individual", "symbol": "AMZN", "units": 12.0, "since": "2026-11-05"}])
    _picks(data, [_pick("AAA", next_earnings="2026-11-03")])
    _watch(data, [{"symbol": "PRDO", "state": "new", "message": "PRDO moved"}])
    out = _inbox().lines(TODAY)
    assert out[0] == "Second Opinion, 4 things:"
    assert [line.split(":")[0] for line in out[1:]] == ["- Cash", "- Vest", "- Picks", "- Watchlist"]
    assert len(_inbox().lines(TODAY, limit=2)) == 3


def test_corrupt_sources_are_skipped(data, capsys) -> None:
    (data / "portfolio-last-check.json").write_text("{bad")
    (data / "picks.json").write_text("{bad")
    _watch(data, [{"symbol": "PRDO", "state": "new", "message": "PRDO moved"}])
    out = _inbox().lines(TODAY)
    assert out[0] == "Second Opinion, 1 thing:" and out[1].startswith("- Watchlist:")
    (data / "watchlist-last-check.json").write_text("[1, 2]")
    assert _inbox().main([]) == 0 and capsys.readouterr().err == ""


def test_light_picks_needing_deep_valuation_at_deep_depth(data) -> None:
    from second_opinion import settings
    settings.set_value("depth", "deep")
    _picks(data, [_pick("AAA", kind="light", next_earnings="2027-01-30"), _pick("BBB", next_earnings="2027-01-30")])
    assert _inbox().lines(TODAY)[1] == '- Picks: 1 light pick needs a deep valuation (AAA).  "re-check my picks"'
