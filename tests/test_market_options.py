"""Option-chain fetch used by the options skill."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from second_opinion import market


class _Ticker:
    options = ("2026-09-11", "2026-09-18", "2026-10-16")

    def __init__(self) -> None:
        self.fast_info = {"lastPrice": 100.5}
        self.calls: list[str] = []

    def option_chain(self, expiry):
        pd = pytest.importorskip("pandas")
        self.calls.append(expiry)
        calls = pd.DataFrame([{"contractSymbol": "AAPL260918C00100000", "strike": 100.0, "lastPrice": 3.2, "bid": 3.0, "ask": 3.4, "volume": 12.0, "openInterest": 400, "impliedVolatility": 0.25, "inTheMoney": True}])
        puts = pd.DataFrame([{"contractSymbol": "AAPL260918P00100000", "strike": 100.0, "lastPrice": 2.9, "bid": 2.8, "ask": 3.0, "volume": float("nan"), "openInterest": 350, "impliedVolatility": 0.27, "inTheMoney": False}])
        return SimpleNamespace(calls=calls, puts=puts)


def test_option_chain_picks_expiry_and_normalizes_rows(monkeypatch) -> None:
    t = _Ticker()
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(Ticker=lambda s: t))
    out = market.option_chain("aapl", expiry="2026-09-18")
    assert out["symbol"] == "AAPL" and out["spot"] == 100.5 and out["expiry"] == "2026-09-18" and out["expiries"] == ["2026-09-11", "2026-09-18", "2026-10-16"]
    assert out["calls"] == [{"contract": "AAPL260918C00100000", "strike": 100.0, "last": 3.2, "bid": 3.0, "ask": 3.4, "volume": 12, "open_interest": 400, "implied_volatility": 0.25, "in_the_money": True}]
    assert out["puts"][0]["volume"] == 0 and out["puts"][0]["implied_volatility"] == 0.27
    assert t.calls == ["2026-09-18"]


def test_option_chain_default_expiry_is_first_at_least_seven_days_out(monkeypatch) -> None:
    from datetime import date

    t = _Ticker()
    t.options = ((date.today()).isoformat(), "2099-01-15", "2099-02-19")
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(Ticker=lambda s: t))
    assert market.option_chain("AAPL")["expiry"] == "2099-01-15"


def test_option_chain_unknown_expiry_raises(monkeypatch) -> None:
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(Ticker=lambda s: _Ticker()))
    with pytest.raises(ValueError, match="2026-12-31 is not an available expiry"):
        market.option_chain("AAPL", expiry="2026-12-31")


def test_option_chain_no_options(monkeypatch) -> None:
    t = _Ticker()
    t.options = ()
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(Ticker=lambda s: t))
    with pytest.raises(ValueError, match="no listed options"):
        market.option_chain("BRK-A")
