"""yfinance wrappers returning plain JSON-able dicts with ISO dates.

yfinance (and pandas) are imported lazily through ``_yf()`` so this module
imports cleanly without them and tests can inject a fake.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from second_opinion import config as _config

INDEX_SYMBOLS = {"^GSPC": "S&P 500", "^DJI": "Dow Jones", "^IXIC": "Nasdaq Composite", "^RUT": "Russell 2000", "^VIX": "VIX"}
SECTOR_ETFS = {"XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care", "XLI": "Industrials", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication Services"}
RATE_SYMBOLS = {"^IRX": "13-week T-bill", "^FVX": "5-year Treasury", "^TNX": "10-year Treasury", "^TYX": "30-year Treasury"}
MACRO_SYMBOLS = {"gold": ("GC=F", "Gold"), "dollar": ("DX-Y.NYB", "US Dollar Index"), "oil": ("CL=F", "WTI Crude Oil"), "bitcoin": ("BTC-USD", "Bitcoin"), "vix_3m": ("^VIX3M", "VIX 3-Month")}
BREADTH_SYMBOLS = {"RSP": "Invesco S&P 500 Equal Weight ETF", "SPY": "SPDR S&P 500 ETF"}
RATE_SPREADS = {"10y_13w": ("^TNX", "^IRX"), "5y_13w": ("^FVX", "^IRX"), "30y_5y": ("^TYX", "^FVX"), "30y_13w": ("^TYX", "^IRX")}

_SNAPSHOT_LOOKBACK_DAYS = 370
_SNAPSHOT_1M_BARS = 21
_SNAPSHOT_3M_BARS = 63
_SNAPSHOT_SMA_DAYS = 50
_VIX_PERCENTILE_MIN_CLOSES = 200

# The S&P 500 against its own weekly averages. 1950 is where Yahoo's daily ^GSPC history
# becomes a continuous record. Weekly closes are built from daily closes (the last close of
# each Monday-Friday week) because Yahoo's own weekly bars move their date labels and drop
# the week in progress at times, which left the reading on the prior Friday's close.
TREND_SYMBOL = "^GSPC"
TREND_START = "1950-01-01"
TREND_WINDOWS = (50, 100, 200)
# Level cut-offs on the gap's percentile within its own history. A price index drifts up,
# so the average lags below it and the typical gap is positive (median about +5% for the
# 50-week, +9% for the 100-week and +17% for the 200-week since 1950). Ranking the gap against its own history
# centres "neutral" on that typical gap instead of on zero.
TREND_LOW_PCTILE = 20
TREND_HIGH_PCTILE = 80
TREND_MIN_GAPS = 260
# Weeks of close-and-average history carried for the page's chart: five years.
TREND_SERIES_WEEKS = 260
# Weeks carried instead when the page's zoomed chart is asked for (``daily``): twenty years.
TREND_LONG_SERIES_WEEKS = 1040
# Sessions of daily close-and-average history carried for the page's zoomed chart: about a year.
TREND_DAILY_DAYS = 260
# Holdings carried per sector fund for the page's sector modal; Yahoo publishes ten.
SECTOR_TOP_HOLDINGS = 10
TREND_NOTE = (
    "The gap is the S&P 500's latest close against its 50-, 100- and 200-week simple moving "
    "averages of weekly closes, ranked against every week since 1950. It measures how far price "
    "has run from its own trend, not what the market is worth: earnings, rates and valuation "
    "multiples are not in it. 'extended' is a gap at or above its 80th percentile, 'depressed' at "
    "or below its 20th, 'neutral' between. Since 1950 none of the three has said much about the "
    "next five years (rank correlation near zero). Over the next year they split: an extended "
    "50-week gap, close to the 200-day average traders watch, was followed by a down year less "
    "often than a depressed one (about one in five against one in four), which reads as momentum; "
    "an extended 100- or 200-week gap was followed by a down year more often (about one in three "
    "against one in five), with similar average returns."
)

SECTOR_CACHE_FILE = "sector-cache.json"

COLUMN_MAP = {"Date": "date", "Datetime": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume", "Dividends": "dividends", "Stock Splits": "stock_splits"}


def _yf() -> Any:
    import yfinance  # noqa: PLC0415

    return yfinance


def _scalar(v: Any) -> Any:
    if v is None:
        return None
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%Y-%m-%d")
        except ValueError:
            return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 4)
    return v


def _records(df: Any) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    rows = df.reset_index().to_dict(orient="records")
    return [{COLUMN_MAP.get(k, str(k).lower()): _scalar(v) for k, v in row.items()} for row in rows]


def _statement(df: Any) -> dict[str, dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for col, series in df.to_dict().items():
        key = col.isoformat() if hasattr(col, "isoformat") else str(col)
        out[key] = {str(k): (None if isinstance(v, float) and math.isnan(v) else _scalar(v)) for k, v in series.items()}
    return out


def _ticker(symbol: str) -> Any:
    return _yf().Ticker(symbol.upper())


def price_history(symbol: str, period: str = "1y", start: str | None = None, end: str | None = None, interval: str = "1d") -> dict[str, Any]:
    t = _ticker(symbol)
    if start or end:
        df = t.history(start=start, end=end, interval=interval)
        label = f"{start} to {end}"
    else:
        df = t.history(period=period, interval=interval)
        label = period
    # During market hours Yahoo appends the in-progress session with a NaN close;
    # signals.py rejects such a row, so drop anything without a close.
    prices = [p for p in _records(df) if p.get("close") is not None]
    return {"symbol": symbol.upper(), "period": label, "interval": interval, "count": len(prices), "prices": prices}


def _direct_quotes(hub: Any, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if hub is None:
        return {}
    try:
        rows = hub.quote(symbols) or []
    except Exception:  # noqa: BLE001 — direct quotes are best-effort
        rows = []
    return {str(r.get("symbol", "")).upper(): r for r in rows if r.get("price") is not None}


def quote_sources(rows: list[dict[str, Any]]) -> str | None:
    sources = {r.get("source") for r in rows if r.get("source")}
    if not sources:
        return None
    return sources.pop() if len(sources) == 1 else "mixed"


def quote(symbols: list[str], hub: Any = None) -> list[dict[str, Any]]:
    direct = _direct_quotes(hub, symbols)
    out = []
    for s in symbols:
        key = s.upper()
        if key in direct:
            out.append(direct[key])
            continue
        info = _ticker(s).info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
        change = round((price / prev - 1) * 100, 4) if price and prev else None
        out.append({"symbol": key, "price": price, "previous_close": prev, "change_pct": change, "currency": info.get("currency"), "quote_type": info.get("quoteType"), "source": "yahoo", "realtime": False})
    return out


def company_info(symbol: str) -> dict[str, Any]:
    info = _ticker(symbol).info or {}
    return {
        "symbol": symbol.upper(),
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"), "industry": info.get("industry"), "country": info.get("country"),
        "website": info.get("website"), "description": info.get("longBusinessSummary"), "employees": info.get("fullTimeEmployees"),
        "market_cap": info.get("marketCap"), "enterprise_value": info.get("enterpriseValue"),
        "pe_ratio": info.get("trailingPE"), "forward_pe": info.get("forwardPE"), "peg_ratio": info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"), "dividend_yield": info.get("dividendYield"), "beta": info.get("beta"),
        "52_week_high": info.get("fiftyTwoWeekHigh"), "52_week_low": info.get("fiftyTwoWeekLow"),
        "50_day_average": info.get("fiftyDayAverage"), "200_day_average": info.get("twoHundredDayAverage"),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "shares_outstanding": info.get("sharesOutstanding"), "implied_shares_outstanding": info.get("impliedSharesOutstanding"),
        "total_debt": info.get("totalDebt"), "total_cash": info.get("totalCash"),
        "free_cash_flow": info.get("freeCashflow"), "operating_cash_flow": info.get("operatingCashflow"),
        "target_high_price": info.get("targetHighPrice"), "target_low_price": info.get("targetLowPrice"),
        "target_mean_price": info.get("targetMeanPrice"), "recommendation": info.get("recommendationKey"),
        "analyst_count": info.get("numberOfAnalystOpinions"), "institutional_ownership": info.get("heldPercentInstitutions"),
        # The quote's currency and the statements' (TSM: USD and TWD). When they differ, per-share
        # values built from the statements are not in the price's currency.
        "currency": info.get("currency"), "financial_currency": info.get("financialCurrency"),
    }


def financials(symbol: str, quarterly: bool = False) -> dict[str, Any]:
    t = _ticker(symbol)
    income = t.quarterly_income_stmt if quarterly else t.income_stmt
    balance = t.quarterly_balance_sheet if quarterly else t.balance_sheet
    cash = t.quarterly_cashflow if quarterly else t.cashflow
    return {
        "symbol": symbol.upper(), "quarterly": quarterly,
        "income_statement": _statement(income), "balance_sheet": _statement(balance), "cash_flow": _statement(cash),
        "shares_outstanding": (t.info or {}).get("sharesOutstanding"),
    }


def dividends(symbol: str) -> dict[str, Any]:
    recs = _records(_ticker(symbol).dividends.to_frame(name="dividend"))
    return {"symbol": symbol.upper(), "count": len(recs), "dividends": recs}


def splits(symbol: str) -> dict[str, Any]:
    recs = _records(_ticker(symbol).splits.to_frame(name="split_ratio"))
    return {"symbol": symbol.upper(), "count": len(recs), "splits": recs}


def earnings(symbol: str) -> dict[str, Any]:
    ed = _ticker(symbol).earnings_dates
    return {"symbol": symbol.upper(), "earnings_dates": _records(ed) if ed is not None else []}


def _snapshot_last(closes: dict[str, list[float]], symbol: str) -> float | None:
    series = closes.get(symbol) or []
    return series[-1] if series else None


def _snapshot_bars(closes: dict[str, list[float]], symbol: str) -> list[float]:
    return closes.get(symbol) or []


def _snapshot_return_pct(series: list[float], bars: int) -> float | None:
    """Percent return from the close ``bars`` sessions back to the last close."""
    if len(series) <= bars:
        return None
    return round((series[-1] / series[-1 - bars] - 1) * 100, 4)


def _vix_percentile_1y(series: list[float]) -> float | None:
    """Fraction (0-1) of trailing-year daily closes at or below the last close."""
    if len(series) < _VIX_PERCENTILE_MIN_CLOSES:
        return None
    last = series[-1]
    return round(sum(1 for c in series if c <= last) / len(series), 4)


def _trend_level(percentile: float) -> str:
    if percentile >= TREND_HIGH_PCTILE:
        return "extended"
    if percentile <= TREND_LOW_PCTILE:
        return "depressed"
    return "neutral"


def _trend_daily(week_dates: list[str], week_closes: list[float], day_dates: list[str], day_closes: list[float]) -> list[dict[str, Any]]:
    """The last ``TREND_DAILY_DAYS`` sessions as ``{date, close, wma_50, wma_100, wma_200}``.

    Each day's averages are the weekly averages as they stood at that day's close: the day's
    close stands in for its own week's close, the way the week in progress does in the headline
    reading. So the last row equals the last row of the weekly ``series``.
    """
    prefix = [0.0]
    for c in week_closes:
        prefix.append(prefix[-1] + c)
    week_of = {date.fromisoformat(d).isocalendar()[:2]: i for i, d in enumerate(week_dates)}
    rows: list[dict[str, Any]] = []
    for d, c in zip(day_dates[-TREND_DAILY_DAYS:], day_closes[-TREND_DAILY_DAYS:]):
        w = week_of.get(date.fromisoformat(d).isocalendar()[:2])
        if w is None:
            continue
        rows.append({"date": d, "close": round(c, 2), **{f"wma_{n}": (round((prefix[w] - prefix[w - n + 1] + c) / n, 2) if w >= n - 1 else None) for n in TREND_WINDOWS}})
    return rows


def trend_from_closes(dates: list[str], closes: list[float], daily: tuple[list[str], list[float]] | None = None) -> dict[str, Any] | None:
    """The last weekly close against each window's simple moving average, ranked in history.

    ``gap_pct`` is close / average - 1 in percent; ``percentile`` is the share of every
    earlier-or-equal week's gap strictly below today's (the indicators.py definition);
    ``share_below_pct`` is how often the close has sat under that average at all;
    ``band_low_pct`` and ``band_high_pct`` are the gaps at the level cut-offs, so the average
    times (1 + band / 100) draws the neutral zone. A window
    without ``TREND_MIN_GAPS`` gaps of history degrades to null. ``series`` is the last
    ``TREND_SERIES_WEEKS`` weeks of ``{date, close, wma_50, wma_100, wma_200}`` for a chart,
    an average null until its window has filled. With ``daily`` (the daily dates and closes the
    weeks were built from), ``daily`` holds the last ``TREND_DAILY_DAYS`` sessions in the same shape
    and ``series`` grows to ``TREND_LONG_SERIES_WEEKS`` weeks.
    """
    if not closes or len(dates) != len(closes):
        return None
    out: dict[str, Any] = {"symbol": TREND_SYMBOL, "as_of": dates[-1], "last": closes[-1], "history_from": dates[0], "weeks": len(closes)}
    averages: dict[int, list[float | None]] = {}
    for n in TREND_WINDOWS:
        ma: list[float | None] = [None] * len(closes)
        if len(closes) >= n:
            running = sum(closes[:n])
            ma[n - 1] = running / n
            for i in range(n, len(closes)):
                running += closes[i] - closes[i - n]
                ma[i] = running / n
        averages[n] = ma
    for n in TREND_WINDOWS:
        if len(closes) < n + TREND_MIN_GAPS:
            out[f"wma_{n}"] = None
            continue
        ma = averages[n]
        gaps = [(closes[i] / ma[i] - 1) * 100 for i in range(n - 1, len(closes))]
        today = gaps[-1]
        pct = 100.0 * sum(1 for g in gaps if g < today) / len(gaps)
        ordered = sorted(gaps)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        out[f"wma_{n}"] = {
            "average": round(ma[-1], 2),
            "gap_pct": round(today, 2),
            "percentile": round(pct),
            "level": _trend_level(round(pct)),  # the level agrees with the percentile shown
            "median_gap_pct": round(median, 2),
            "share_below_pct": round(100.0 * sum(1 for g in gaps if g < 0) / len(gaps)),
            "band_low_pct": round(ordered[int(len(ordered) * TREND_LOW_PCTILE / 100)], 2),
            "band_high_pct": round(ordered[min(len(ordered) - 1, int(len(ordered) * TREND_HIGH_PCTILE / 100))], 2),
            "gaps_from": dates[n - 1],
        }
    start = max(0, len(closes) - (TREND_LONG_SERIES_WEEKS if daily is not None else TREND_SERIES_WEEKS))
    out["series"] = [
        {"date": dates[i], "close": round(closes[i], 2), **{f"wma_{n}": (round(averages[n][i], 2) if averages[n][i] is not None else None) for n in TREND_WINDOWS}}
        for i in range(start, len(closes))
    ]
    if daily is not None:
        out["daily"] = _trend_daily(dates, closes, *daily)
    out["levels"] = {"extended": f"percentile >= {TREND_HIGH_PCTILE}", "neutral": f"between {TREND_LOW_PCTILE} and {TREND_HIGH_PCTILE}", "depressed": f"percentile <= {TREND_LOW_PCTILE}"}
    out["note"] = TREND_NOTE
    return out


def weekly_closes(dates: list[str], closes: list[float]) -> tuple[list[str], list[float]]:
    """The last daily close of each ISO (Monday-Sunday) week, dated on that close's own day.

    The week in progress is included at its latest close, so the reading moves with today's price.
    """
    out_d: list[str] = []
    out_c: list[float] = []
    last_key = None
    for d, c in zip(dates, closes):
        key = date.fromisoformat(d).isocalendar()[:2]
        if key == last_key:
            out_d[-1], out_c[-1] = d, c
        else:
            out_d.append(d)
            out_c.append(c)
            last_key = key
    return out_d, out_c


def sp500_trend(daily: bool = False) -> dict[str, Any] | None:
    """The S&P 500's weekly trend gaps from one daily download since 1950; null on any failure.

    ``daily`` adds the last year of daily closes with the averages as they stood each day and
    lengthens the weekly ``series`` from five years to twenty.
    """
    try:
        df = _yf().download([TREND_SYMBOL], start=TREND_START, interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=False)
        if df is None or getattr(df, "empty", True):
            return None
        cols = df.columns
        series = df[TREND_SYMBOL]["Close"] if getattr(cols, "nlevels", 1) > 1 else df["Close"]
        series = series.dropna()
        dates = [d.strftime("%Y-%m-%d") for d in series.index]
        closes = [round(float(v), 4) for v in series.tolist()]
    except Exception:  # noqa: BLE001 - a trend failure degrades to null, never the snapshot
        return None
    return trend_from_closes(*weekly_closes(dates, closes), daily=(dates, closes) if daily else None)


def _row_history(dated: list[tuple[str, float]]) -> dict[str, Any]:
    """A row's daily closes as ``[date, close]`` pairs with the high, low and change over them."""
    values = [c for _, c in dated]
    return {
        "history": [[d, c] for d, c in dated],
        "high_1y": max(values),
        "low_1y": min(values),
        "change_1y_pct": round((values[-1] / values[0] - 1) * 100, 4) if values[0] else None,
    }


def top_holdings(symbol: str, limit: int = SECTOR_TOP_HOLDINGS) -> list[dict[str, Any]] | None:
    """A fund's largest holdings from Yahoo as ``{symbol, name, weight_pct}``, largest first; null on any failure.

    Yahoo publishes the top ten and gives them no date.
    """
    try:
        df = _ticker(symbol).funds_data.top_holdings
        rows = [
            {"symbol": str(sym), "name": str(row["Name"]), "weight_pct": round(float(row["Holding Percent"]) * 100, 2)}
            for sym, row in df.iterrows()
        ]
    except Exception:  # noqa: BLE001 - a holdings failure degrades to null, never the snapshot
        return None
    rows.sort(key=lambda r: -r["weight_pct"])
    return rows[:limit] or None


def index_snapshot(history: bool = False, holdings: bool = False) -> dict[str, Any]:
    """Indices, sector ETFs, rates, macro futures/ETFs, yield spreads and breadth
    proxies from ONE batched Yahoo download.

    Top-level keys: ``as_of``, ``indices``, ``sectors``, ``rates`` (lists of
    ``{symbol, name, last, day_change_pct, week_change_pct}``), plus the additive
    ``macro`` block ({gold, dollar, oil, bitcoin, vix_3m} -> same row shape),
    ``spreads`` ({10y_13w, 5y_13w, 30y_5y, 30y_13w} in percentage points, computed
    from the rates' last yields), ``breadth`` ({rsp_spy_1m, rsp_spy_3m,
    sectors_above_50sma, sectors_total, note} — RSP/SPY relative returns and the
    count of sector ETFs above their 50-day SMA; proxies, not full market breadth)
    and ``vix_percentile_1y`` (fraction 0-1; where ^VIX's last close sits in its
    trailing-year distribution), and ``trend`` (``sp500_trend()``: the S&P 500's gap
    to its 50-, 100- and 200-week averages ranked since 1950, from a second, daily
    download grouped into weeks). Missing data degrades one row or one field to null — never the
    whole snapshot.

    ``history`` adds to every row its daily closes over the snapshot's trailing year
    (``history`` as ``[date, close]`` pairs, ``high_1y``, ``low_1y``, ``change_1y_pct``) and
    ``trend.daily``. ``holdings`` adds ``top_holdings`` to each sector row, one Yahoo lookup per
    sector fund. Both are for the page's charts and modals and are off by default.
    """
    symbols = {**{s: s for s in INDEX_SYMBOLS}, **{s: s for s in SECTOR_ETFS}, **{s: s for s in RATE_SYMBOLS}}
    symbols.update({sym: sym for _, (sym, _) in MACRO_SYMBOLS.items()})
    symbols.update({s: s for s in BREADTH_SYMBOLS})
    start = (date.today() - timedelta(days=_SNAPSHOT_LOOKBACK_DAYS)).isoformat()
    df = _yf().download(list(symbols), start=start, interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
    closes = {s: _closes(df, s) for s in symbols}

    def row(symbol: str, name: str) -> dict[str, Any]:
        series = _snapshot_bars(closes, symbol)
        last = series[-1] if series else None
        day = round((series[-1] / series[-2] - 1) * 100, 4) if len(series) >= 2 else None
        week = round((series[-1] / series[-6] - 1) * 100, 4) if len(series) >= 6 else None
        out = {"symbol": symbol, "name": name, "last": last, "day_change_pct": day, "week_change_pct": week}
        if history:
            dated = _dated_closes(df, symbol)
            if len(dated) > 1:
                out.update(_row_history(dated))
        return out

    def sector_row(symbol: str, name: str) -> dict[str, Any]:
        out = row(symbol, name)
        if holdings:
            out["top_holdings"] = top_holdings(symbol)
        return out

    spreads: dict[str, float | None] = {}
    for key, (long_sym, short_sym) in RATE_SPREADS.items():
        long_rate, short_rate = _snapshot_last(closes, long_sym), _snapshot_last(closes, short_sym)
        spreads[key] = round(long_rate - short_rate, 4) if long_rate is not None and short_rate is not None else None

    rsp_1m = _snapshot_return_pct(_snapshot_bars(closes, "RSP"), _SNAPSHOT_1M_BARS)
    spy_1m = _snapshot_return_pct(_snapshot_bars(closes, "SPY"), _SNAPSHOT_1M_BARS)
    rsp_3m = _snapshot_return_pct(_snapshot_bars(closes, "RSP"), _SNAPSHOT_3M_BARS)
    spy_3m = _snapshot_return_pct(_snapshot_bars(closes, "SPY"), _SNAPSHOT_3M_BARS)
    above_sma = sum(1 for s in SECTOR_ETFS if len(_snapshot_bars(closes, s)) >= _SNAPSHOT_SMA_DAYS and _snapshot_bars(closes, s)[-1] > sum(_snapshot_bars(closes, s)[-_SNAPSHOT_SMA_DAYS:]) / _SNAPSHOT_SMA_DAYS)

    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indices": [row(s, n) for s, n in INDEX_SYMBOLS.items()],
        "sectors": [sector_row(s, n) for s, n in SECTOR_ETFS.items()],
        "rates": [row(s, n) for s, n in RATE_SYMBOLS.items()],
        "macro": {cat: row(sym, name) for cat, (sym, name) in MACRO_SYMBOLS.items()},
        "spreads": spreads,
        "breadth": {
            "rsp_spy_1m": round(rsp_1m - spy_1m, 4) if rsp_1m is not None and spy_1m is not None else None,
            "rsp_spy_3m": round(rsp_3m - spy_3m, 4) if rsp_3m is not None and spy_3m is not None else None,
            "sectors_above_50sma": above_sma,
            "sectors_total": len(SECTOR_ETFS),
            "note": "proxies, not full market breadth",
        },
        "vix_percentile_1y": _vix_percentile_1y(_snapshot_bars(closes, "^VIX")),
        "trend": sp500_trend(daily=True) if history else sp500_trend(),
    }


# --- portfolio-analysis helpers ---------------------------------------------------


def _unique_upper(symbols: list[str]) -> list[str]:
    return sorted({s.strip().upper() for s in symbols if s and s.strip()})


def _closes(df: Any, symbol: str) -> list[float]:
    """Non-null closes for ``symbol`` from a yfinance download frame (grouped by ticker, or flat for one symbol)."""
    if df is None or getattr(df, "empty", True):
        return []
    try:
        cols = df.columns
        if getattr(cols, "nlevels", 1) > 1:
            if symbol not in cols.get_level_values(0):
                return []
            series = df[symbol]["Close"]
        else:
            series = df["Close"]
    except (KeyError, TypeError):
        return []
    return [round(float(v), 4) for v in series.dropna().tolist()]


def _dated_closes(df: Any, symbol: str) -> list[tuple[str, float]]:
    """``(date, close)`` pairs for ``symbol`` from a download frame; empty when it has none or carries no dates."""
    try:
        cols = df.columns
        if getattr(cols, "nlevels", 1) > 1:
            if symbol not in cols.get_level_values(0):
                return []
            series = df[symbol]["Close"]
        else:
            series = df["Close"]
        series = series.dropna()
        return [(d.strftime("%Y-%m-%d"), round(float(v), 4)) for d, v in zip(series.index, series.tolist())]
    except Exception:  # noqa: BLE001 - history is optional; the row keeps its levels without it
        return []


def day_changes(symbols: list[str], hub: Any = None) -> dict[str, dict[str, Any]]:
    """Last and previous close per symbol: direct broker quotes first, then ONE batched Yahoo download.

    Symbols with fewer than two closes in the window (and no usable direct quote) are omitted.
    """
    syms = _unique_upper(symbols)
    if not syms:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for s, r in _direct_quotes(hub, syms).items():
        if r.get("previous_close") is not None:
            out[s] = {"price": float(r["price"]), "previous_close": float(r["previous_close"]), "source": str(r["source"]) if r.get("source") else None}
    rest = [s for s in syms if s not in out]
    if rest:
        df = _yf().download(rest, period="5d", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
        for s in rest:
            closes = _closes(df, s)
            if len(closes) >= 2:
                out[s] = {"price": closes[-1], "previous_close": closes[-2], "source": "yahoo"}
    return out


def sector_cache_path() -> Path:
    base = str(_config.data_dir())
    return Path(base) / SECTOR_CACHE_FILE


_SECTOR_FIELDS = ("sector", "name", "quote_type", "category", "country", "summary", "website", "fund_sectors", "fund_asset_classes", "fund_fetched")
_FUND_QUOTE_TYPES = ("ETF", "MUTUALFUND")
_FUND_DATA_MAX_AGE_DAYS = 30  # a fund entry WITH sector data is refreshed after this many days
_FUND_DATA_RETRY_DAYS = 1  # a fund entry with NO sector data yet is retried much sooner


def _fund_data_stale(fund_fetched: Any, has_data: bool) -> bool:
    if not isinstance(fund_fetched, str):
        return True
    try:
        fetched = datetime.strptime(fund_fetched, "%Y-%m-%d").date()
    except ValueError:
        return True
    days = (date.today() - fetched).days
    if has_data:
        return days > _FUND_DATA_MAX_AGE_DAYS
    return days >= _FUND_DATA_RETRY_DAYS  # a null result is retried AT the 1-day mark, not after it


def _fund_fields(t: Any, quote_type: str | None) -> dict[str, Any]:
    """Fund sector weightings and asset-class split for an ETF/mutual-fund ticker, each fetched
    and guarded independently so one failure doesn't blank the other; stocks get null fields.
    ``fund_fetched`` is recorded on every attempt, success or failure, so a symbol whose
    ``sector_weightings`` keeps failing is not hammered on every call -- it is simply retried
    sooner (see ``_FUND_DATA_RETRY_DAYS``) than one that already has data."""
    if str(quote_type or "").upper() not in _FUND_QUOTE_TYPES:
        return {"fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None}
    try:
        sw = t.funds_data.sector_weightings
        fund_sectors = dict(sw) if isinstance(sw, dict) else None
    except Exception:  # noqa: BLE001 — bond funds and lookup failures both degrade to null
        fund_sectors = None
    try:
        ac = t.funds_data.asset_classes
        fund_asset_classes = dict(ac) if isinstance(ac, dict) else None
    except Exception:  # noqa: BLE001
        fund_asset_classes = None
    return {
        "fund_sectors": fund_sectors,
        "fund_asset_classes": fund_asset_classes,
        "fund_fetched": date.today().isoformat(),
    }


# Yahoo sometimes reports quoteType EQUITY with no sector for something that is really an index
# ETF (e.g. SPYM, "SPDR Portfolio S&P 500 ETF"); these name shapes are the tell.
_MISLABELED_FUND_NAME_PATTERNS = (
    re.compile(r"\bETF\b", re.I),
    re.compile(r"Index Fund", re.I),
    re.compile(r"\bIndex\b.*\b(Fund|Trust|Portfolio)\b", re.I),
    re.compile(r"Portfolio S&P", re.I),
)


def looks_like_a_fund_name(name: str | None) -> bool:
    """True for a fund-shaped name ("... ETF", "Index Fund", "Portfolio S&P ..."): the tell for a
    fund Yahoo reports as a sector-less EQUITY."""
    return bool(name) and any(p.search(name) for p in _MISLABELED_FUND_NAME_PATTERNS)


def sectors(symbols: list[str], cache_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Sector, long name, Yahoo quote type, fund category, issuer country, business summary,
    website, and (for ETFs/mutual funds) a sector-weightings look-through and asset-class split
    per symbol, served from an on-disk JSON cache and filled from Yahoo ``info``/``funds_data`` on
    a miss. ETFs get sector "ETF"; stocks get ``fund_sectors: null``. Yahoo sometimes reports
    quoteType EQUITY with no sector for something that is really an index/portfolio ETF (e.g.
    SPYM); when the name looks like a fund's (``\\bETF\\b``, "Index Fund",
    ``\\bIndex\\b.*\\b(Fund|Trust|Portfolio)\\b``, "Portfolio S&P"), the fund-data fetch is
    retried, and quote_type/sector are corrected to "ETF" only when that retry actually finds
    real sector weightings -- otherwise the entry stays a plain, sector-less EQUITY, but
    ``fund_fetched`` is still set so this retry runs exactly once per symbol, not on every call. A
    cache entry written before this retry existed (quote_type EQUITY, no sector, a fund-shaped
    name, ``fund_fetched`` still null) gets that one retry on its next use too, so an old cache
    does not serve a mislabeled ETF as a stock forever. A failed base lookup returns nulls and is
    NOT cached, so it is retried next time. Cache entries written before ``category``
    and ``country`` existed are refreshed on first use; a fund entry that lacks the
    ``fund_sectors`` key at all is refreshed too (stocks are unaffected by either rule). A fund
    entry that HAS ``fund_fetched`` is refreshed once it is more than 30 days old when it has real
    sector data, or 1 day old or more when ``fund_sectors`` is null (a failed fetch is retried the
    very next day, not on every call the same day, but also not left stale for a month). An
    already-relabeled ETF (cached ``quote_type: "ETF"`` with real ``fund_sectors``) whose scheduled
    30-day refresh finds Yahoo's own ``info`` still saying EQUITY (it never actually changes) and
    whose retried ``funds_data`` fetch fails or comes back empty keeps its cached relabel and fund
    fields rather than being permanently demoted back to a sector-less EQUITY -- only
    ``fund_fetched`` moves to today, so the 30-day cycle simply continues."""
    path = cache_path or sector_cache_path()
    cache: dict[str, Any] = {}
    try:
        loaded = json.loads(path.read_text())
        cache = loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        cache = {}
    out: dict[str, dict[str, Any]] = {}
    changed = False
    for s in _unique_upper(symbols):
        hit = cache.get(s)
        if isinstance(hit, dict) and all(k in hit for k in ("category", "country", "summary", "website")):
            quote_type_cached = str(hit.get("quote_type") or "").upper()
            fund_stale = quote_type_cached in _FUND_QUOTE_TYPES and (
                "fund_sectors" not in hit
                or _fund_data_stale(hit.get("fund_fetched"), hit.get("fund_sectors") is not None)
            )
            # A cache entry written before the mislabeled-fund retry existed (or before this
            # symbol's name started looking like a fund): quote_type EQUITY, no sector, a
            # fund-shaped name, and fund_fetched never set. It gets exactly one retry attempt,
            # same as a fresh fetch would; after that attempt, fund_fetched is always set (see
            # below) so this same check never fires for it again.
            mislabel_candidate = (
                quote_type_cached == "EQUITY"
                and not hit.get("sector")
                and hit.get("fund_fetched") is None
                and looks_like_a_fund_name(hit.get("name"))
            )
            if not fund_stale and not mislabel_candidate:
                out[s] = {k: hit.get(k) for k in _SECTOR_FIELDS}
                continue
        try:
            t = _ticker(s)
            info = t.info or {}
        except Exception:  # noqa: BLE001 — degrade per symbol, never fail the snapshot
            stale = hit if isinstance(hit, dict) else {}
            out[s] = {k: stale.get(k) for k in _SECTOR_FIELDS}
            continue
        quote_type = info.get("quoteType")
        name = info.get("longName") or info.get("shortName")
        fund_fields = _fund_fields(t, quote_type)
        if (
            str(quote_type or "").upper() == "EQUITY"
            and not info.get("sector")
            and looks_like_a_fund_name(name)
        ):
            # Retry as if it were a fund; only adopt "ETF" when that actually finds real sector
            # weightings, so a genuine no-sector stock whose name happens to say "Index" is
            # untouched. Either way, record that the attempt was made (fund_fetched), so the
            # cache-hit check above never retries this same entry again -- one attempt, ever.
            retry = _fund_fields(t, "ETF")
            already_relabeled = (
                isinstance(hit, dict)
                and str(hit.get("quote_type") or "").upper() == "ETF"
                and hit.get("fund_sectors") is not None
            )
            if retry["fund_sectors"]:
                quote_type = "ETF"
                fund_fields = retry
            elif already_relabeled:
                # This symbol was already correctly relabeled by an earlier fetch (Yahoo's own
                # quoteType field never actually changes -- it always re-reports EQUITY, which is
                # why we're retrying at all). A funds_data hiccup on this scheduled 30-day refresh
                # must not permanently demote a known-good ETF back to a sector-less EQUITY --
                # keep the cached relabel and fund_sectors, only refreshing fund_fetched so the
                # 30-day cycle continues from today instead of falling back to the 1-day one.
                # sector_weightings and asset_classes are fetched independently (see
                # _fund_fields), so today's asset_classes fetch may well have succeeded even
                # though sector_weightings didn't -- prefer that fresh value when it did, and
                # only fall back to the cached one when today's fetch also came back empty.
                quote_type = hit.get("quote_type")
                fresh_classes = retry.get("fund_asset_classes")
                fund_fields = {
                    "fund_sectors": hit.get("fund_sectors"),
                    # truthiness, not "is not None": an empty {} isn't a real update either
                    "fund_asset_classes": fresh_classes if fresh_classes else hit.get("fund_asset_classes"),
                    "fund_fetched": retry["fund_fetched"],
                }
            else:
                fund_fields = {**fund_fields, "fund_fetched": retry["fund_fetched"]}
        sector = info.get("sector") or ("ETF" if str(quote_type or "").upper() == "ETF" else None)
        entry = {
            "sector": sector,
            "name": name,
            "quote_type": quote_type,
            "category": info.get("category"),  # fund category, e.g. "Intermediate Core Bond"
            "country": info.get("country"),  # issuer country for stocks
            "summary": (str(info.get("longBusinessSummary") or "")[:1200] or None),  # what the business/fund is
            "website": info.get("website"),
            **fund_fields,
        }
        out[s] = entry
        cache[s] = entry
        changed = True
    if changed:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache, indent=2, sort_keys=True))
        except OSError:
            pass
    return out


def _iso_date(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%Y-%m-%d")
        except ValueError:
            return None
    return str(v)[:10] if isinstance(v, str) and len(v) >= 10 else None


def next_events(symbol: str, today: date | None = None) -> dict[str, str | None]:
    """Next earnings date and ex-dividend date from Yahoo's calendar; nulls when unknown.

    Yahoo keeps reporting the LAST ex-dividend date after it has passed, so any
    date before ``today`` is dropped rather than presented as upcoming.
    """
    none = {"next_earnings": None, "next_ex_dividend": None}
    try:
        cal = _ticker(symbol).calendar
    except Exception:  # noqa: BLE001
        return none
    if not isinstance(cal, dict):
        return none
    floor = (today or datetime.now(timezone.utc).date()).isoformat()
    raw = cal.get("Earnings Date")
    candidates = raw if isinstance(raw, (list, tuple)) else [raw]
    earnings = sorted(d for d in (_iso_date(x) for x in candidates) if d and d >= floor)
    ex_div = _iso_date(cal.get("Ex-Dividend Date"))
    return {"next_earnings": earnings[0] if earnings else None, "next_ex_dividend": ex_div if ex_div and ex_div >= floor else None}


# --- dividend-income helpers -------------------------------------------------------


def _column(df: Any, symbol: str, name: str) -> Any:
    cols = df.columns
    if getattr(cols, "nlevels", 1) > 1:
        if symbol not in cols.get_level_values(0):
            return None
        return df[symbol][name]
    return df[name]


def dividend_histories(symbols: list[str], years: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Per-share cash dividends by ex-date for every symbol from ONE batched
    Yahoo download (``actions=True``). Symbols without dividends map to []."""
    syms = _unique_upper(symbols)
    if not syms:
        return {}
    df = _yf().download(syms, period=f"{int(years)}y", interval="1d", group_by="ticker", actions=True, auto_adjust=False, progress=False, threads=True)
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in syms}
    if df is None or getattr(df, "empty", True):
        return out
    for s in syms:
        try:
            series = _column(df, s, "Dividends")
        except (KeyError, TypeError):
            series = None
        if series is None:
            continue
        for idx, value in series.dropna().items():
            if value and float(value) > 0:
                out[s].append({"date": _scalar(idx), "dividend": round(float(value), 4)})
    return out


def payout_info(symbols: list[str]) -> dict[str, dict[str, float | None]]:
    """Payout ratio, trailing EPS and Yahoo's stated dividend rate per symbol
    (one ``info`` call each; failures degrade to nulls)."""
    out: dict[str, dict[str, float | None]] = {}
    for s in _unique_upper(symbols):
        try:
            info = _ticker(s).info or {}
        except Exception:  # noqa: BLE001
            info = {}
        out[s] = {"payout_ratio": _scalar(info.get("payoutRatio")), "eps_ttm": _scalar(info.get("trailingEps")), "dividend_rate": _scalar(info.get("dividendRate"))}
    return out


# --- trade-review helpers ----------------------------------------------------------


def close_histories(symbols: list[str], start: str) -> dict[str, list[dict[str, Any]]]:
    """Daily close and adjusted close per symbol since ``start`` from ONE batched
    Yahoo download (``auto_adjust=False`` so both columns are present)."""
    syms = _unique_upper(symbols)
    if not syms:
        return {}
    df = _yf().download(syms, start=start, interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in syms}
    if df is None or getattr(df, "empty", True):
        return out
    for s in syms:
        try:
            close = _column(df, s, "Close")
        except (KeyError, TypeError):
            close = None
        if close is None:
            continue
        try:
            adj = _column(df, s, "Adj Close")
        except (KeyError, TypeError):
            adj = None
        try:
            volume = _column(df, s, "Volume")
        except (KeyError, TypeError):
            volume = None
        adj_map = {} if adj is None else {idx: v for idx, v in adj.items()}
        vol_map = {} if volume is None else {idx: v for idx, v in volume.items()}
        for idx, value in close.items():
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            a = adj_map.get(idx)
            a = value if a is None or (isinstance(a, float) and math.isnan(a)) else a
            vol = vol_map.get(idx)
            out[s].append(
                {
                    "date": _scalar(idx),
                    "close": round(float(value), 4),
                    "adj_close": round(float(a), 4),
                    "volume": None if vol is None or (isinstance(vol, float) and math.isnan(vol)) else int(vol),
                }
            )
    return out


# --- options helpers ------------------------------------------------------------------

_MIN_EXPIRY_DAYS = 7


def _chain_rows(df: Any) -> list[dict[str, Any]]:
    rows = []
    for r in _records(df):
        iv = r.get("impliedvolatility")
        rows.append(
            {
                "contract": r.get("contractsymbol"), "strike": float(r["strike"]),
                "last": r.get("lastprice"), "bid": r.get("bid"), "ask": r.get("ask"),
                "volume": int(r.get("volume") or 0), "open_interest": int(r.get("openinterest") or 0),
                "implied_volatility": round(float(iv), 4) if iv is not None else None,
                "in_the_money": bool(r.get("inthemoney")) if r.get("inthemoney") is not None else None,
            }
        )
    return sorted(rows, key=lambda r: r["strike"])


def option_chain(symbol: str, expiry: str | None = None) -> dict[str, Any]:
    """Calls and puts for one expiry (default: the first expiry at least 7 days
    out) with the spot price and the list of available expiries."""
    t = _ticker(symbol)
    expiries = [str(e) for e in (t.options or ())]
    if not expiries:
        raise ValueError(f"{symbol.upper()} has no listed options")
    if expiry is None:
        floor = (date.today() + timedelta(days=_MIN_EXPIRY_DAYS)).isoformat()
        expiry = next((e for e in expiries if e >= floor), expiries[-1])
    if expiry not in expiries:
        raise ValueError(f"{expiry} is not an available expiry for {symbol.upper()}; choose one of {', '.join(expiries[:8])}")
    chain = t.option_chain(expiry)
    fi = getattr(t, "fast_info", None) or {}
    spot = fi.get("lastPrice") if hasattr(fi, "get") else getattr(fi, "last_price", None)
    if spot is None:
        closes = [p["close"] for p in price_history(symbol, period="5d")["prices"] if p.get("close") is not None]
        spot = closes[-1] if closes else None
    return {"symbol": symbol.upper(), "spot": _scalar(spot), "expiry": expiry, "expiries": expiries, "calls": _chain_rows(chain.calls), "puts": _chain_rows(chain.puts)}


def _search_news(symbol: str, count: int) -> list[Any]:
    """Yahoo's search endpoint's stories for ``symbol``, less those not tagged with it.

    The search matches the ticker as a word, so "DECK" also returns stories about roof decks and
    Upper Deck cards, which Yahoo tags with an empty ``relatedTickers`` list. A story is kept when
    its list names the symbol, or when it carries no ``relatedTickers`` field at all."""
    sym = symbol.upper()
    rows = getattr(_yf().Search(sym, news_count=count), "news", None) or []
    out = []
    for item in rows:
        related = item.get("relatedTickers") if isinstance(item, dict) else None
        if isinstance(related, list) and sym not in {str(r).upper() for r in related}:
            continue
        out.append(item)
    return out


def recent_news(symbol: str, days: int = 7, limit: int = 3) -> list[dict[str, Any]]:
    """Up to ``limit`` Yahoo headlines for ``symbol`` published in the last ``days`` days, newest first.

    Each item: {title, publisher, published (ISO date-time), url, summary}. Items without a publication
    date are dropped (the dateline is what makes a headline usable), so an empty list means no dated
    story in the window, not a failure.

    Source: ``Ticker.news``; when that raises or returns nothing (yfinance 1.7's endpoint answers
    HTTP 404 for every symbol), Yahoo's search endpoint (``Search(symbol).news``), whose stories are
    kept when tagged with the symbol or carrying no ticker field at all (an empty ticker list is a
    word match on the symbol and is dropped); its items carry no summary. Raises
    ``Ticker.news``'s error only when the search fails too.
    """
    try:
        raw, failure = _ticker(symbol).news or [], None
    except Exception as exc:  # noqa: BLE001 — any failure of the first endpoint sends us to the second
        raw, failure = [], exc
    if not raw:
        try:
            raw = _search_news(symbol, max(10, limit * 3))
        except Exception:  # noqa: BLE001
            if failure is not None:
                raise failure from None
            raw = []
    floor = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict[str, Any]] = []
    for item in raw:
        c = item.get("content") if isinstance(item, dict) and isinstance(item.get("content"), dict) else item
        if not isinstance(c, dict):
            continue
        when = c.get("pubDate") or c.get("displayTime") or c.get("providerPublishTime")
        try:
            published = (
                datetime.fromtimestamp(int(when), tz=timezone.utc)
                if isinstance(when, (int, float))
                else datetime.fromisoformat(str(when).replace("Z", "+00:00"))
            )
        except (TypeError, ValueError):
            continue
        if published < floor:
            continue
        provider = c.get("provider") or {}
        link = (c.get("canonicalUrl") or c.get("clickThroughUrl") or {}) if isinstance(c.get("canonicalUrl") or c.get("clickThroughUrl"), dict) else {}
        out.append(
            {
                "title": str(c.get("title") or "").strip(),
                "publisher": (provider.get("displayName") if isinstance(provider, dict) else provider) or c.get("publisher"),
                "published": published.isoformat(timespec="minutes"),
                "url": link.get("url") or c.get("link"),
                "summary": (str(c.get("summary") or "")[:240] or None),
            }
        )
    out.sort(key=lambda x: x["published"], reverse=True)
    return out[:limit]


_ANALYST_ACTION_DAYS = 180
_ANALYST_ACTION_LIMIT = 10


def _positive(v: Any) -> float | None:
    """A price target as a number, or None: Yahoo writes a missing target as 0."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _analyst_part(t: Any, attr: str) -> Any:
    try:
        return getattr(t, attr)
    except Exception:  # noqa: BLE001 — each Yahoo analyst endpoint fails on its own (429, no coverage)
        return None


def _estimate_rows(df: Any, year_ago: str) -> list[dict[str, Any]]:
    return [
        {"period": r.get("period"), "avg": r.get("avg"), "low": r.get("low"), "high": r.get("high"),
         "year_ago": r.get(year_ago), "analysts": r.get("numberofanalysts"), "growth": r.get("growth")}
        for r in _records(df) if r.get("period") is not None
    ]


def analyst_view(symbol: str) -> dict[str, Any]:
    """Yahoo's analyst consensus for ``symbol``: price targets, this month's ratings, recent rating
    actions and the EPS and revenue estimates. It never raises: a part Yahoo does not return is None
    (``actions`` is ``[]``), so a caller can tell "no coverage" from the parts that did arrive.

    {"symbol", "as_of", "source": "yahoo",
     "targets": {"current", "low", "mean", "median", "high"} | None,
     "recommendations": {"strong_buy", "buy", "hold", "sell", "strong_sell", "count"} | None,
     "actions": [{"date", "firm", "action", "from_grade", "to_grade", "target", "prior_target"}],
     "estimates": {"eps": [{"period", "avg", "low", "high", "year_ago", "analysts", "growth"}], "revenue": [...]} | None}

    ``targets`` is None when no low, mean, median or high target is above zero (Yahoo's ``current``
    is the share price, not a target). ``recommendations`` is the current month's row (``0m``).
    ``actions`` covers the last 180 days, newest first, at most 10; a zero target is None.
    """
    today = date.today()
    out: dict[str, Any] = {"symbol": symbol.upper(), "as_of": today.isoformat(), "source": "yahoo",
                           "targets": None, "recommendations": None, "actions": [], "estimates": None}
    try:
        t = _ticker(symbol)
    except Exception:  # noqa: BLE001
        return out

    try:
        raw = _analyst_part(t, "analyst_price_targets")
        if isinstance(raw, dict):
            tg = {k: _positive(_scalar(raw.get(k))) for k in ("current", "low", "mean", "median", "high")}
            if any(tg[k] is not None for k in ("low", "mean", "median", "high")):
                out["targets"] = tg
    except Exception:  # noqa: BLE001
        pass

    try:
        rows = _records(_analyst_part(t, "recommendations_summary"))
        row = next((r for r in rows if r.get("period") == "0m"), None)
        if row:
            rec = {name: int(row.get(key) or 0) for name, key in
                   (("strong_buy", "strongbuy"), ("buy", "buy"), ("hold", "hold"), ("sell", "sell"), ("strong_sell", "strongsell"))}
            rec["count"] = sum(rec.values())
            if rec["count"]:
                out["recommendations"] = rec
    except Exception:  # noqa: BLE001
        pass

    try:
        floor = (today - timedelta(days=_ANALYST_ACTION_DAYS)).isoformat()
        actions = []
        for r in _records(_analyst_part(t, "upgrades_downgrades")):
            when = r.get("gradedate")
            if not isinstance(when, str) or when[:10] < floor:
                continue
            actions.append({"date": when[:10], "firm": r.get("firm") or None, "action": r.get("action") or None,
                            "from_grade": r.get("fromgrade") or None, "to_grade": r.get("tograde") or None,
                            "target": _positive(r.get("currentpricetarget")), "prior_target": _positive(r.get("priorpricetarget"))})
        actions.sort(key=lambda a: a["date"], reverse=True)
        out["actions"] = actions[:_ANALYST_ACTION_LIMIT]
    except Exception:  # noqa: BLE001
        pass

    try:
        eps = _estimate_rows(_analyst_part(t, "earnings_estimate"), "yearagoeps")
        revenue = _estimate_rows(_analyst_part(t, "revenue_estimate"), "yearagorevenue")
        if eps or revenue:
            out["estimates"] = {"eps": eps, "revenue": revenue}
    except Exception:  # noqa: BLE001
        pass
    return out
