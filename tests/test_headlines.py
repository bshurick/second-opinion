from __future__ import annotations

import pytest
from second_opinion import headlines as H


def test_make_builds_a_stable_key_and_new_status() -> None:
    h = H.make("tax-aware", "NEAR_LONG_TERM", "alert", "AAPL lot turns long-term on 2026-10-02",
               symbol="AAPL", discriminator="2026-10-02", detail="142 shares", as_of="2026-09-14",
               ask="Which lots of AAPL are near long-term?")
    assert h["key"] == "tax-aware:NEAR_LONG_TERM:AAPL:2026-10-02"
    assert h["status"] == "new" and h["severity"] == "alert" and h["symbol"] == "AAPL"
    assert H.make("risk-analysis", "HIGH_BETA", "notice", "t")["key"] == "risk-analysis:HIGH_BETA:-:"


def test_make_rejects_unknown_severity() -> None:
    with pytest.raises(ValueError):
        H.make("x", "Y", "loud", "t")


def test_cap_keeps_alerts_first_then_notices() -> None:
    hs = [H.make("s", "A", "info", "i"), H.make("s", "B", "notice", "n1"), H.make("s", "C", "alert", "a"),
          H.make("s", "D", "notice", "n2"), H.make("s", "E", "notice", "n3")]
    kept = H.cap(hs)
    assert [h["code"] for h in kept] == ["C", "B", "D"]


def test_order_puts_new_first_regardless_of_severity_then_severity_then_source_order() -> None:
    a_still = {**H.make("debt-tracker", "PAST_DUE", "alert", "a"), "status": "still"}
    a_new = H.make("watchlist", "TRIGGER", "alert", "b")
    n_market = {**H.make("market-analysis", "VIX", "notice", "c"), "status": "still"}
    n_watch = {**H.make("watchlist", "X", "notice", "d"), "status": "still"}
    i_new = H.make("market-analysis", "DAY", "info", "e")
    out = H.order([i_new, n_watch, a_still, n_market, a_new], ["watchlist", "market-analysis", "debt-tracker"])
    # a new info headline outranks every still alert; within new and within still, severity then source order
    assert [h["key"] for h in out] == [a_new["key"], i_new["key"], a_still["key"], n_watch["key"], n_market["key"]]


def test_apply_status_marks_seen_keys_still() -> None:
    hs = [H.make("s", "A", "alert", "a"), H.make("s", "B", "alert", "b")]
    out = H.apply_status(hs, {"s:A:-:"})
    assert [h["status"] for h in out] == ["still", "new"]


def test_last_file_round_trip_is_atomic(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    assert H.load_last() == {"as_of": None, "keys": [], "risk": {}}
    p = H.save_last("2026-09-14T13:05:00+00:00", [H.make("s", "A", "alert", "a")], {"max_drawdown": -0.21})
    assert p == tmp_path / "brief-last.json" and not list(tmp_path.glob("*.tmp"))
    assert H.load_last() == {"as_of": "2026-09-14T13:05:00+00:00", "keys": ["s:A:-:"], "risk": {"max_drawdown": -0.21}}


def test_load_last_tolerates_damaged_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    (tmp_path / "brief-last.json").write_text("{not json")
    assert H.load_last()["keys"] == []


def test_symbol_from_message_extracts_a_leading_ticker() -> None:
    assert H.symbol_from_message("aapl cut its dividend") == "AAPL"
    assert H.symbol_from_message("Concentration is high across payers") is None
    assert H.symbol_from_message("") is None


def test_money_formats_with_a_dollar_sign_and_absolute_value() -> None:
    assert H.money(-1234.5) == "$1,234.50"
    assert H.money(1234.5) == "$1,234.50"


def test_make_includes_url_answer_why_keys_defaulting_to_empty_strings() -> None:
    h = H.make("tax-aware", "NEAR_LONG_TERM", "alert", "AAPL lot turns long-term on 2026-10-02")
    assert "url" in h and h["url"] == ""
    assert "answer" in h and h["answer"] == ""
    assert "why" in h and h["why"] == ""


def test_yahoo_url_builds_a_quote_link() -> None:
    assert H.yahoo_url("AAPL") == "https://finance.yahoo.com/quote/AAPL"


def test_edgar_url_builds_a_company_filings_search() -> None:
    assert H.edgar_url("PEP") == "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=PEP&type=10-K&owner=include&count=10"


def test_pct_formats_a_fraction_as_a_percent() -> None:
    assert H.pct(0.123) == "12.3%"
    assert H.pct(-0.05) == "-5.0%"
    assert H.pct(0.1, digits=0) == "10%"


def test_make_carries_through_url_answer_why_values() -> None:
    h = H.make("market-analysis", "VIX_HIGH", "notice", "VIX at 84th percentile",
               url="https://example.com/vix", answer="VIX is at its highest in a year",
               why="High volatility signals investor uncertainty and can affect portfolio risk")
    assert h["url"] == "https://example.com/vix"
    assert h["answer"] == "VIX is at its highest in a year"
    assert h["why"] == "High volatility signals investor uncertainty and can affect portfolio risk"
