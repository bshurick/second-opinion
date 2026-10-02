"""Batched close history used by the trade-review skill."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from second_opinion import market


def test_close_histories_one_download_with_adjusted_closes(monkeypatch) -> None:
    pd = pytest.importorskip("pandas")
    calls: list[dict] = []

    def download(tickers, **kw):
        calls.append({"tickers": tickers, **kw})
        idx = pd.to_datetime(["2025-01-02", "2025-01-03"])
        cols = pd.MultiIndex.from_product([["AAPL", "SPY"], ["Close", "Adj Close"]])
        df = pd.DataFrame(index=idx, columns=cols, dtype="float64")
        df[("AAPL", "Close")] = [100.0, 101.0]
        df[("AAPL", "Adj Close")] = [99.0, 100.0]
        df[("SPY", "Close")] = [400.0, float("nan")]
        df[("SPY", "Adj Close")] = [398.0, float("nan")]
        return df

    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(download=download))
    out = market.close_histories(["aapl", "SPY"], start="2024-01-01")
    assert len(calls) == 1 and calls[0]["tickers"] == ["AAPL", "SPY"] and calls[0]["start"] == "2024-01-01" and calls[0]["auto_adjust"] is False
    assert out == {
        "AAPL": [{"date": "2025-01-02", "close": 100.0, "adj_close": 99.0, "volume": None}, {"date": "2025-01-03", "close": 101.0, "adj_close": 100.0, "volume": None}],
        "SPY": [{"date": "2025-01-02", "close": 400.0, "adj_close": 398.0, "volume": None}],
    }


def test_close_histories_single_symbol_and_missing_adj(monkeypatch) -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.to_datetime(["2025-01-02", "2025-01-03"]))
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(download=lambda tickers, **kw: df))
    assert market.close_histories(["VTI"], start="2025-01-01") == {"VTI": [{"date": "2025-01-02", "close": 1.0, "adj_close": 1.0, "volume": None}, {"date": "2025-01-03", "close": 2.0, "adj_close": 2.0, "volume": None}]}


def test_close_histories_empty(monkeypatch) -> None:
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(download=lambda *a, **k: pytest.fail("download called")))
    assert market.close_histories([], start="2025-01-01") == {}
