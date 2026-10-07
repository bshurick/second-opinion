from __future__ import annotations

from scripts_util import load_script, run_json

sentiment = load_script("stock-screener/scripts/sentiment.py")


def _rows(n=3):
    return [{"date": f"2026-10-0{i + 1}", "short": 40, "total": 100} for i in range(n)]


def _patch(monkeypatch, rows, news):
    monkeypatch.setattr(sentiment.finra, "short_volume", lambda syms, days=20: {s: rows.get(s, []) for s in syms})
    monkeypatch.setattr(sentiment.market, "recent_news", news)


def test_two_symbols_merged(monkeypatch, capsys):
    seen = {}

    def news(sym, days=7, limit=3):
        seen[sym] = (days, limit)
        return [{"title": f"{sym} news", "published": "2026-10-01T00:00:00+00:00"}]

    _patch(monkeypatch, {"AAA": _rows(), "BBB": _rows(2)}, news)
    rc, out = run_json(sentiment, ["aaa,BBB", "--days", "5", "--news-days", "10", "--news", "2"], capsys)
    assert rc == 0
    assert out["as_of"]
    assert set(out["symbols"]) == {"AAA", "BBB"}
    assert out["symbols"]["AAA"]["short_volume"]["days"] == 3
    assert out["symbols"]["BBB"]["short_volume"]["short_ratio"] == 40.0
    assert out["symbols"]["BBB"]["news"][0]["title"] == "BBB news"
    assert seen["AAA"] == (10, 2)
    assert out["flags"] == []


def test_no_finra_rows(monkeypatch, capsys):
    _patch(monkeypatch, {"AAA": _rows()}, lambda *a, **k: [])
    rc, out = run_json(sentiment, ["AAA,BBB"], capsys)
    assert rc == 0
    assert out["symbols"]["BBB"]["short_volume"] is None
    flags = out["flags"]
    assert [f["code"] for f in flags] == ["NO_SHORT_VOLUME"]
    assert "BBB" in flags[0]["message"]


def test_news_failure_degrades(monkeypatch, capsys):
    def news(sym, days=7, limit=3):
        if sym == "BBB":
            raise RuntimeError("boom")
        return []

    _patch(monkeypatch, {"AAA": _rows(), "BBB": _rows()}, news)
    rc, out = run_json(sentiment, ["AAA,BBB"], capsys)
    assert rc == 0
    assert out["symbols"]["BBB"]["news"] == []
    assert [f["code"] for f in out["flags"]] == ["NEWS_UNAVAILABLE"]
    assert "BBB" in out["flags"][0]["message"]


def test_too_many_symbols(monkeypatch, capsys):
    _patch(monkeypatch, {}, lambda *a, **k: [])
    syms = ",".join(f"S{chr(65 + i)}" for i in range(26))
    rc, out = run_json(sentiment, [syms], capsys)
    assert rc == 2
    assert "error" in out


def test_bad_symbol(monkeypatch, capsys):
    _patch(monkeypatch, {}, lambda *a, **k: [])
    rc, _ = run_json(sentiment, ["AAA,$$"], capsys)
    assert rc == 2


def test_days_capped_at_60(monkeypatch, capsys):
    _patch(monkeypatch, {"AAA": _rows()}, lambda *a, **k: [])
    rc, out = run_json(sentiment, ["AAA", "--days", "61"], capsys)
    assert rc == 2 and "error" in out
    rc, _ = run_json(sentiment, ["AAA", "--days", "60"], capsys)
    assert rc == 0
