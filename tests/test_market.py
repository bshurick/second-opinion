from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from second_opinion import market


class FakeFrame:
    """Just enough of a DataFrame: reset_index(), empty, to_dict(orient='records'), to_dict()."""

    def __init__(self, rows: list[dict], columns: dict | None = None) -> None:
        self.rows, self.columns_dict = rows, columns or {}

    @property
    def empty(self) -> bool:
        return not self.rows and not self.columns_dict

    def reset_index(self) -> "FakeFrame":
        return self

    def to_dict(self, orient: str = "dict"):
        return self.rows if orient == "records" else self.columns_dict


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.history_calls: list[dict] = []
        self.info = {"longName": "Apple Inc.", "sector": "Technology", "currentPrice": 150.0, "sharesOutstanding": 1000, "currency": "USD", "previousClose": 148.5, "quoteType": "EQUITY"}
        self.income_stmt = FakeFrame([], {datetime(2025, 12, 31): {"Total Revenue": 100.0, "Net Income": float("nan")}})
        self.balance_sheet = FakeFrame([], {})
        self.cashflow = FakeFrame([], {})
        self.dividends = SimpleNamespace(to_frame=lambda name: FakeFrame([{"Date": datetime(2026, 1, 2), name: 0.25}]))

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        return FakeFrame([
            {"Date": datetime(2026, 1, 2), "Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10},
            {"Date": datetime(2026, 1, 3), "Open": 1.5, "High": 2.5, "Low": 1.0, "Close": 2.0, "Volume": float("nan")},
        ])


@pytest.fixture
def fake_yf(monkeypatch):
    tickers: dict[str, FakeTicker] = {}

    def Ticker(sym):
        return tickers.setdefault(sym, FakeTicker(sym))

    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(Ticker=Ticker))
    return tickers


def test_price_history_records(fake_yf) -> None:
    out = market.price_history("aapl", period="6mo")
    assert out["symbol"] == "AAPL" and out["count"] == 2 and out["interval"] == "1d"
    assert out["prices"][0] == {"date": "2026-01-02", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}
    assert out["prices"][1]["volume"] is None
    assert fake_yf["AAPL"].history_calls == [{"period": "6mo", "interval": "1d"}]


def test_price_history_range_uses_start_end(fake_yf) -> None:
    out = market.price_history("AAPL", start="2026-01-01", end="2026-02-01")
    assert out["period"] == "2026-01-01 to 2026-02-01"
    assert fake_yf["AAPL"].history_calls == [{"start": "2026-01-01", "end": "2026-02-01", "interval": "1d"}]


def test_quote_from_info(fake_yf) -> None:
    out = market.quote(["aapl"])
    assert out == [{"symbol": "AAPL", "price": 150.0, "previous_close": 148.5, "change_pct": pytest.approx(1.0101, abs=1e-3), "currency": "USD", "quote_type": "EQUITY", "source": "yahoo", "realtime": False}]


def test_quote_rows_carry_quote_type_even_when_info_lacks_it(fake_yf) -> None:
    assert market.quote(["AAPL"])[0]["quote_type"] == "EQUITY"  # ticker cached on first call
    fake_yf["AAPL"].info = {"longName": "Apple Inc.", "currentPrice": 150.0}
    assert market.quote(["AAPL"])[0]["quote_type"] is None


def test_financials_nan_becomes_none_and_dates_iso(fake_yf) -> None:
    out = market.financials("AAPL")
    assert out["income_statement"] == {"2025-12-31T00:00:00": {"Total Revenue": 100.0, "Net Income": None}}
    assert out["shares_outstanding"] == 1000 and out["quarterly"] is False


def test_dividends(fake_yf) -> None:
    assert market.dividends("AAPL") == {"symbol": "AAPL", "count": 1, "dividends": [{"date": "2026-01-02", "dividend": 0.25}]}


SNAPSHOT_INDICES = ["^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX"]
SNAPSHOT_SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]
SNAPSHOT_RATES = ["^IRX", "^FVX", "^TNX", "^TYX"]
SNAPSHOT_MACRO = ["GC=F", "DX-Y.NYB", "CL=F", "BTC-USD", "^VIX3M"]
SNAPSHOT_BREADTH = ["RSP", "SPY"]
SNAPSHOT_ALL_SYMBOLS = set(SNAPSHOT_INDICES + SNAPSHOT_SECTORS + SNAPSHOT_RATES + SNAPSHOT_MACRO + SNAPSHOT_BREADTH)


def _ramp(base: float, n: int, step: float = 1.0) -> list[float]:
    """A rising close series: base, base+step, ..., base+step*(n-1)."""
    return [round(base + i * step, 4) for i in range(n)]


class _FakeSeries:
    """Just enough of a pandas Series: dropna().tolist()."""

    def __init__(self, values: list[float]) -> None:
        self._values = [v for v in values if v is not None]

    def dropna(self) -> "_FakeSeries":
        return self

    def tolist(self) -> list[float]:
        return list(self._values)


class _FakeSymbolColumns:
    """df[symbol] -> something subscriptable by column name."""

    def __init__(self, values: list[float]) -> None:
        self._values = values

    def __getitem__(self, column: str) -> _FakeSeries:
        assert column == "Close"
        return _FakeSeries(self._values)


class FakeDownloadFrame:
    """Just enough of a group_by='ticker' download frame for market._closes."""

    def __init__(self, data: dict[str, list[float]]) -> None:
        self._data = data

    @property
    def empty(self) -> bool:
        return not self._data

    @property
    def columns(self):
        keys = list(self._data)
        return SimpleNamespace(nlevels=2, get_level_values=lambda level: keys)

    def __getitem__(self, symbol: str) -> _FakeSymbolColumns:
        if symbol not in self._data:
            raise KeyError(symbol)
        return _FakeSymbolColumns(self._data[symbol])


def _snapshot_closes() -> dict[str, list[float]]:
    data = {s: _ramp(5000.0, 70) for s in SNAPSHOT_INDICES if s != "^VIX"}
    data["^VIX"] = [5.0] * 100 + [15.0] * 100 + [25.0] * 19 + [20.0]  # 220 closes, last 20.0
    data.update({s: _ramp(100.0, 70) for s in SNAPSHOT_SECTORS})
    data["XLRE"] = _ramp(200.0, 70, step=-1.0)  # falling: below its 50-day SMA
    data.update({s: _ramp(b, 70) for s, b in {"^IRX": 5.0, "^FVX": 4.2, "^TNX": 4.5, "^TYX": 4.8}.items()})
    data.update({s: _ramp(100.0, 70) for s in SNAPSHOT_MACRO})
    data["RSP"] = _ramp(180.0, 70)
    data["SPY"] = _ramp(550.0, 70)
    return data


@pytest.fixture
def snapshot_yf(monkeypatch):
    calls: list[dict] = []

    def download(symbols, **kwargs):
        calls.append({"symbols": list(symbols), **kwargs})
        return FakeDownloadFrame(_snapshot_closes())

    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(download=download))
    return calls


def test_index_snapshot_shape(snapshot_yf) -> None:
    out = market.index_snapshot()
    assert set(out) == {"as_of", "indices", "sectors", "rates", "macro", "spreads", "breadth", "vix_percentile_1y"}
    row = out["indices"][0]
    assert set(row) == {"symbol", "name", "last", "day_change_pct", "week_change_pct"}
    assert out["indices"][0]["last"] == 5069.0
    assert out["indices"][0]["day_change_pct"] == pytest.approx(100 / 5068, abs=1e-3)
    assert out["sectors"][0]["last"] == 169.0 and out["sectors"][0]["week_change_pct"] == pytest.approx(5 / 164 * 100, abs=1e-3)


def test_index_snapshot_one_batched_download(snapshot_yf) -> None:
    market.index_snapshot()
    assert len(snapshot_yf) == 1
    call = snapshot_yf[0]
    assert set(call["symbols"]) == SNAPSHOT_ALL_SYMBOLS
    assert call["group_by"] == "ticker" and call["auto_adjust"] is False and call["interval"] == "1d"
    assert call["progress"] is False and call["threads"] is True
    start = date.fromisoformat(call["start"])
    days = (date.today() - start).days
    assert 350 <= days <= 400


def test_index_snapshot_macro_block(snapshot_yf) -> None:
    out = market.index_snapshot()
    assert set(out["macro"]) == {"gold", "dollar", "oil", "bitcoin", "vix_3m"}
    gold = out["macro"]["gold"]
    assert set(gold) == {"symbol", "name", "last", "day_change_pct", "week_change_pct"}
    assert gold["symbol"] == "GC=F" and gold["last"] == 169.0
    assert out["macro"]["vix_3m"]["symbol"] == "^VIX3M"


def test_index_snapshot_spreads(snapshot_yf) -> None:
    out = market.index_snapshot()
    # TNX 4.5+0.69, FVX 4.2+0.69, IRX 5.0+0.69, TYX 4.8+0.69 — offsets cancel
    assert out["spreads"] == {"10y_13w": -0.5, "5y_13w": -0.8, "30y_5y": 0.6, "30y_13w": -0.2}


def test_index_snapshot_breadth(snapshot_yf) -> None:
    out = market.index_snapshot()
    b = out["breadth"]
    assert set(b) == {"rsp_spy_1m", "rsp_spy_3m", "sectors_above_50sma", "sectors_total", "note"}
    # 21-bar and 63-bar returns off a base+1.0 daily ramp
    rsp_1m = round((249 / 228 - 1) * 100, 4)
    spy_1m = round((619 / 598 - 1) * 100, 4)
    assert b["rsp_spy_1m"] == round(rsp_1m - spy_1m, 4)
    rsp_3m = round((249 / 186 - 1) * 100, 4)
    spy_3m = round((619 / 556 - 1) * 100, 4)
    assert b["rsp_spy_3m"] == round(rsp_3m - spy_3m, 4)
    assert b["sectors_above_50sma"] == 10 and b["sectors_total"] == 11  # XLRE is falling
    assert b["note"] == "proxies, not full market breadth"


def test_index_snapshot_vix_percentile(snapshot_yf) -> None:
    # 220 closes: 100x5.0, 100x15.0, 19x25.0, then 20.0 -> 201/220 at or below the last close
    out = market.index_snapshot()
    assert out["vix_percentile_1y"] == round(201 / 220, 4)


def test_index_snapshot_missing_symbols_degrade_to_nulls(monkeypatch) -> None:
    data = _snapshot_closes()
    del data["^TNX"], data["RSP"], data["^VIX"]
    monkeypatch.setattr(market, "_yf", lambda: SimpleNamespace(download=lambda symbols, **kw: FakeDownloadFrame(data)))
    out = market.index_snapshot()
    tnx = [r for r in out["rates"] if r["symbol"] == "^TNX"][0]
    assert tnx["last"] is None and tnx["day_change_pct"] is None and tnx["week_change_pct"] is None
    assert out["spreads"]["10y_13w"] is None  # needs ^TNX
    assert out["spreads"]["5y_13w"] == -0.8 and out["spreads"]["30y_5y"] == 0.6 and out["spreads"]["30y_13w"] == -0.2
    assert out["breadth"]["rsp_spy_1m"] is None and out["breadth"]["rsp_spy_3m"] is None
    assert out["vix_percentile_1y"] is None
    # everything else is intact
    assert out["indices"][0]["last"] == 5069.0 and out["macro"]["gold"]["last"] == 169.0


class NaTLike:
    """Has strftime but raises ValueError like pd.NaT."""

    def strftime(self, fmt: str) -> None:
        raise ValueError("NaTType does not support strftime")


def test_scalar_nat_strftime_raises_becomes_none() -> None:
    nat_like = NaTLike()
    frame = FakeFrame([{"Date": nat_like, "Close": 100.0}])
    records = market._records(frame)
    assert records == [{"date": None, "close": 100.0}]


def test_company_info_keys_complete(fake_yf) -> None:
    backend_keys = frozenset({
        "symbol", "name", "sector", "industry", "country", "website", "description", "employees",
        "market_cap", "enterprise_value", "pe_ratio", "forward_pe", "peg_ratio", "price_to_book",
        "dividend_yield", "beta", "52_week_high", "52_week_low", "50_day_average", "200_day_average",
        "current_price", "target_high_price", "target_low_price", "target_mean_price", "recommendation",
    })
    out = market.company_info("AAPL")
    assert backend_keys.issubset(set(out))


def test_price_history_drops_rows_without_a_close(fake_yf) -> None:
    # During market hours Yahoo appends the in-progress session as a row whose Close is
    # NaN; signals.py rejects such a row, so price_history must not emit it.
    t = fake_yf.setdefault("AAPL", FakeTicker("AAPL"))
    t.history = lambda **kwargs: FakeFrame([
        {"Date": datetime(2026, 1, 2), "Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10},
        {"Date": datetime(2026, 1, 3), "Open": 1.5, "High": 2.5, "Low": 1.0, "Close": 2.0, "Volume": 12},
        {"Date": datetime(2026, 1, 4), "Open": 2.0, "High": float("nan"), "Low": float("nan"), "Close": float("nan"), "Volume": 0},
    ])
    out = market.price_history("AAPL")
    assert [p["date"] for p in out["prices"]] == ["2026-01-02", "2026-01-03"]
    assert out["count"] == 2


class HubStub:
    def __init__(self, rows):
        self.rows = rows

    def quote(self, symbols):
        return self.rows


def test_quote_prefers_hub_rows_and_fills_the_rest_from_yahoo(monkeypatch) -> None:
    monkeypatch.setattr(market, "_ticker", lambda s: type("T", (), {"info": {"currentPrice": 9.0, "previousClose": 8.0, "currency": "USD", "quoteType": "EQUITY"}})())
    hub = HubStub([{"symbol": "AAPL", "price": 201.0, "previous_close": 200.0, "change_pct": 0.5, "currency": "USD", "source": "etrade", "realtime": True, "as_of": "t"}])
    rows = market.quote(["AAPL", "MSFT"], hub=hub)
    assert rows[0]["source"] == "etrade" and rows[0]["price"] == 201.0
    assert rows[1] == {"symbol": "MSFT", "price": 9.0, "previous_close": 8.0, "change_pct": 12.5, "currency": "USD", "quote_type": "EQUITY", "source": "yahoo", "realtime": False}
    assert market.quote_sources(rows) == "mixed"


def test_quote_without_hub_is_all_yahoo(monkeypatch) -> None:
    monkeypatch.setattr(market, "_ticker", lambda s: type("T", (), {"info": {"currentPrice": 1.0, "previousClose": 1.0}})())
    rows = market.quote(["X"])
    assert rows[0]["source"] == "yahoo" and market.quote_sources(rows) == "yahoo"


def test_day_changes_uses_hub_then_yahoo(monkeypatch) -> None:
    monkeypatch.setattr(market, "_yf", lambda: type("Y", (), {"download": staticmethod(lambda *a, **k: None)})())
    monkeypatch.setattr(market, "_closes", lambda df, s: [10.0, 11.0] if s == "MSFT" else [])
    hub = HubStub([{"symbol": "AAPL", "price": 201.0, "previous_close": 200.0, "source": "etrade", "realtime": True}])
    out = market.day_changes(["aapl", "msft", "none"], hub=hub)
    assert out == {"AAPL": {"price": 201.0, "previous_close": 200.0, "source": "etrade"}, "MSFT": {"price": 11.0, "previous_close": 10.0, "source": "yahoo"}}


def test_day_changes_passes_a_missing_source_through_as_null(monkeypatch) -> None:
    monkeypatch.setattr(market, "_yf", lambda: type("Y", (), {"download": staticmethod(lambda *a, **k: None)})())
    hub = HubStub([{"symbol": "AAPL", "price": 1.0, "previous_close": 1.0, "realtime": True}])
    out = market.day_changes(["AAPL"], hub=hub)
    assert out["AAPL"]["source"] is None  # never the string "None"
    assert market.quote_sources(list(out.values())) is None


def test_day_changes_skips_yahoo_when_hub_covers_everything(monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("Yahoo should not be called")

    monkeypatch.setattr(market, "_yf", boom)
    hub = HubStub([{"symbol": "AAPL", "price": 1.0, "previous_close": 1.0, "source": "etrade", "realtime": True}])
    assert market.day_changes(["AAPL"], hub=hub) == {"AAPL": {"price": 1.0, "previous_close": 1.0, "source": "etrade"}}
