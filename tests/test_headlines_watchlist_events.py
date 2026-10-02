from __future__ import annotations

from datetime import date

from second_opinion.headlines import events as EV
from second_opinion.headlines import watchlist as WL

CTX = {"today": date(2026, 9, 14), "now": "2026-09-14T13:05:00+00:00", "snapshot": {"events": None}, "previous": {"keys": []}}


def test_watchlist_new_triggers_become_alerts_and_others_are_dropped() -> None:
    res = {"main": {"as_of": "2026-09-14", "triggered": [
        {"symbol": "PEP", "type": "price_below", "value": 70.25, "current": 66.10, "message": "PEP 66.10 is below 70.25", "state": "new"},
        {"symbol": "KO", "type": "drawdown", "message": "KO is 12% off its 52-week high", "state": "still"},
        {"symbol": "KO", "type": "price_below", "message": "x", "state": "snoozed"},
    ], "watchlist": [
        {"symbol": "PEP", "price": 66.10, "since_added_pct": 0.042, "from_52w_high": -0.18,
         "triggered": [{"type": "price_below", "value": 70.25, "current": 66.10, "message": "PEP 66.10 is below 70.25", "state": "new"}]},
        {"symbol": "KO", "price": 31.0, "since_added_pct": -0.02, "from_52w_high": -0.12, "triggered": []},
    ]}}
    hs = WL.extract(res, CTX)
    assert len(hs) == 1
    h = hs[0]
    assert h["key"] == "watchlist:price_below:PEP:2026-09-14" and h["severity"] == "alert"
    assert h["title"] == "PEP 66.10 is below 70.25" and h["as_of"] == "2026-09-14"
    assert h["ask"] == "What on my watchlist moved?"
    assert h["url"] == "https://finance.yahoo.com/quote/PEP"
    assert h["answer"] == "Now 66.10; rule price_below at 70.25; +4.2% since added, 18.0% below the 52-week high"
    assert h["why"] == "A price rule you set on your watchlist fired on today's quote."


def test_watchlist_answer_wording_at_and_above_the_52_week_high() -> None:
    res = {"main": {"as_of": "2026-09-14", "triggered": [
        {"symbol": "AAA", "type": "price_above", "value": 100.0, "message": "AAA is above 100.0", "state": "new"},
        {"symbol": "BBB", "type": "price_above", "value": 50.0, "message": "BBB is above 50.0", "state": "new"},
    ], "watchlist": [
        {"symbol": "AAA", "price": 100.0, "since_added_pct": 0.1, "from_52w_high": 0.0, "triggered": []},
        {"symbol": "BBB", "price": 55.0, "since_added_pct": 0.1, "from_52w_high": 0.05, "triggered": []},
    ]}}
    hs = WL.extract(res, CTX)
    assert hs[0]["answer"].endswith("at the 52-week high")
    assert hs[1]["answer"].endswith("5.0% above the 52-week high")


def test_watchlist_without_triggers_is_empty() -> None:
    assert WL.extract({"main": {"as_of": "2026-09-14", "triggered": []}}, CTX) == []


def test_events_within_seven_days_are_alerts() -> None:
    ctx = {**CTX, "snapshot": {"events": [
        {"symbol": "KO", "type": "earnings", "date": "2026-09-20"},
        {"symbol": "PEP", "type": "ex_dividend", "date": "2026-09-21"},
        {"symbol": "AAPL", "type": "earnings", "date": "2026-10-28"},
        {"symbol": "OLD", "type": "earnings", "date": "2026-09-13"},
    ]}}
    hs = EV.extract({}, ctx)
    assert [h["key"] for h in hs] == ["portfolio-snapshot:EARNINGS:KO:2026-09-20", "portfolio-snapshot:EX_DIVIDEND:PEP:2026-09-21"]
    assert hs[0]["title"] == "KO reports earnings on 2026-09-20" and hs[0]["severity"] == "alert"
    assert hs[1]["title"] == "PEP goes ex-dividend on 2026-09-21"
    assert hs[0]["ask"] == "What is KO's expected move through earnings?"
    assert hs[1]["ask"] == "What is PEP's next dividend worth to me?"
    assert hs[0]["url"] == "https://finance.yahoo.com/quote/KO" and hs[0]["answer"] == ""
    assert hs[0]["why"] == "Earnings days bring the largest single-day moves; the options market prices how large."
    assert hs[1]["url"] == "https://finance.yahoo.com/quote/PEP" and hs[1]["answer"] == ""
    assert hs[1]["why"] == "You must hold the shares before the ex-dividend date to receive the next payment."


def test_events_none_is_empty() -> None:
    assert EV.extract({}, CTX) == []
