"""Yahoo helpers used by the dividend-income skill: batched dividend history and payout lookups."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from second_opinion import market


def _patch(monkeypatch, tickers: dict | None = None, download=None) -> None:
    tickers = tickers or {}
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(Ticker=lambda s: tickers[s], download=download))


def test_dividend_histories_one_download_nonzero_rows_only(monkeypatch) -> None:
    pd = pytest.importorskip("pandas")
    calls: list[dict] = []

    def download(tickers, **kw):
        calls.append({"tickers": tickers, **kw})
        idx = pd.to_datetime(["2026-05-11", "2026-08-10", "2026-08-11"])
        cols = pd.MultiIndex.from_product([["AAPL", "GROW"], ["Close", "Dividends"]])
        df = pd.DataFrame(0.0, index=idx, columns=cols)
        df[("AAPL", "Dividends")] = [0.26, 0.26, 0.0]
        return df

    _patch(monkeypatch, download=download)
    out = market.dividend_histories(["aapl", "GROW"], years=5)
    assert len(calls) == 1 and calls[0]["tickers"] == ["AAPL", "GROW"] and calls[0]["actions"] is True and calls[0]["period"] == "5y"
    assert out == {
        "AAPL": [{"date": "2026-05-11", "dividend": 0.26}, {"date": "2026-08-10", "dividend": 0.26}],
        "GROW": [],
    }


def test_dividend_histories_single_symbol_flat_frame(monkeypatch) -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"Close": [1.0, 1.0], "Dividends": [0.0, 0.5]}, index=pd.to_datetime(["2026-01-02", "2026-03-02"]))
    _patch(monkeypatch, download=lambda tickers, **kw: df)
    assert market.dividend_histories(["VTI"]) == {"VTI": [{"date": "2026-03-02", "dividend": 0.5}]}


def test_dividend_histories_empty_input(monkeypatch) -> None:
    _patch(monkeypatch, download=lambda *a, **k: pytest.fail("download called"))
    assert market.dividend_histories([]) == {}


def test_payout_info_reads_info_per_symbol_and_degrades(monkeypatch) -> None:
    class T:
        def __init__(self, info=None, fail=False):
            self._info, self._fail = info, fail

        @property
        def info(self):
            if self._fail:
                raise RuntimeError("down")
            return self._info

    _patch(monkeypatch, {"AAPL": T({"payoutRatio": 0.153, "trailingEps": 6.42, "dividendRate": 1.04}), "BAD": T(fail=True), "VTI": T({})})
    assert market.payout_info(["aapl", "BAD", "VTI"]) == {
        "AAPL": {"payout_ratio": 0.153, "eps_ttm": 6.42, "dividend_rate": 1.04},
        "BAD": {"payout_ratio": None, "eps_ttm": None, "dividend_rate": None},
        "VTI": {"payout_ratio": None, "eps_ttm": None, "dividend_rate": None},
    }
