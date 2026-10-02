"""Momentum, reversal, and technical summary statistics for one security.

This script reads a JSON object from stdin, computes trailing-window
returns, 12-1 momentum, annualized volatility, drawdowns, moving
averages, and 52-week range statistics from a daily closing-price
series, and writes a JSON object to stdout. It is invoked as:

    python signals.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "prices": [
        {"date": "2025-01-02", "close": 123.45},
        ...
        # Daily closes. Dates are ISO "YYYY-MM-DD" strings and must be
        # unique; the script sorts them ascending, so input order does
        # not matter. Every close must be > 0. At least 2 entries.
        #
        # Each row MAY also carry "high", "low", and/or "volume" (all
        # optional, independently of one another). "high"/"low" must be
        # positive finite numbers with high >= low when both are given;
        # "volume" must be a non-negative finite number. A row may omit
        # any of these fields or send JSON null for them.
      ],
      "benchmark": [                       # optional, additive
        {"date": "2025-01-02", "close": 456.78}, ...
        # Same shape as "prices" (date + close only). Used to compute
        # the "relative" block below. Dates that don't appear in BOTH
        # "prices" and "benchmark" are dropped before any window is
        # measured.
      ],
      "pivots": 3,                         # optional, additive
        # Integer >= 2. k-bar swing-pivot lookback (see "pivots" below).
      "series": true                       # optional, additive
        # Boolean. When true the output carries the trailing moving-average
        # SERIES behind sma_50 / sma_200 (see "series" below) so a chart can
        # draw them; the scalar fields are unchanged.
    }

All windows below are TRADING DAYS counted back from the most recent
close: 1w=5, 1m=21, 3m=63, 6m=126, 12m=252. A window's statistic is
null when the series is too short for it — never extrapolated.

Output JSON contract (stdout)::

    {
      "as_of": "2025-06-30",        # date of the last close
      "last_close": ...,             # 4dp
      "observations": ...,           # number of price points used
      "returns": {                   # simple returns, 4dp or null:
        "1w": ..., "1m": ...,        #   close[t] / close[t-k] - 1
        "3m": ..., "6m": ...,
        "12m": ...
      },
      "momentum_12_1": ...,          # 4dp or null. The Jegadeesh-Titman
                                      # formation signal: the 12-month
                                      # return SKIPPING the most recent
                                      # month, close[t-21]/close[t-252]-1
                                      # (needs >= 253 observations).
      "annualized_volatility": ...,  # 4dp or null. Sample stdev (ddof=1)
                                      # of daily simple returns over the
                                      # trailing min(252, n-1) days,
                                      # scaled by sqrt(252). Null when
                                      # fewer than 20 daily returns are
                                      # available.
      "max_drawdown": ...,           # 4dp, <= 0. Largest peak-to-trough
                                      # decline over the FULL series.
      "current_drawdown": ...,       # 4dp, <= 0. Last close vs the
                                      # full-series high.
      "sma_50": ...,                 # 4dp or null (needs >= 50 closes)
      "sma_200": ...,                # 4dp or null (needs >= 200 closes)
      "price_vs_sma_50": ...,        # 4dp or null; last/sma - 1
      "price_vs_sma_200": ...,       # 4dp or null; last/sma - 1
      "high_52w": ...,               # 4dp. High/low over the trailing
      "low_52w": ...,                #   min(252, n) closes.
      "pct_from_52w_high": ...,      # 4dp, <= 0; last/high_52w - 1
      "pct_from_52w_low": ...,       # 4dp, >= 0; last/low_52w - 1

      # --- additive: only present when "prices" rows carry "high"/"low" ---
      "atr_14_pct": ...,              # 4dp or null. 14-period Average
                                       # True Range (Wilder's smoothing:
                                       # seed = simple mean of the first
                                       # 14 true-range values, then
                                       # atr = (atr*13 + tr)/14 for every
                                       # later bar, applied across the
                                       # full available history) as a
                                       # percent of the last close. Needs
                                       # >= 15 rows with BOTH high and low
                                       # present on every row; null (but
                                       # the key is still present) when
                                       # any row in the series is missing
                                       # high or low, or there are fewer
                                       # than 15 rows.
      "gap_stats": {                  # or null (same >= 15-row gating,
                                       # plus needs >= 60 rows total).
                                       # Computed over every consecutive
                                       # pair in the series (not just a
                                       # trailing window): gap-up when
                                       # low[i] > close[i-1], gap-down
                                       # when high[i] < close[i-1].
        "up_gap_frequency": ...,       # 4dp. up_gap_count / (n - 1)
        "up_gap_count": ...,           # int
        "down_gap_count": ...          # int
      },

      # --- additive: only present when "prices" rows carry "volume" ---
      "relative_volume_20_252": ...,  # 4dp or null. mean(volume of the
                                       # last 20 rows) / mean(volume of
                                       # the trailing min(252, n) rows).
                                       # Needs >= 30 rows, all with
                                       # volume present.
      "avg_dollar_volume_20": ...,    # 2dp or null. mean(close * volume)
                                       # over the last 20 rows. Needs
                                       # >= 20 rows, all with volume
                                       # present.

      # --- additive: only present when "benchmark" is given ---
      "relative": {
        "1m": ..., "3m": ..., "12m": ...,   # 4dp or null. Position
                                             # return minus benchmark
                                             # return over the same
                                             # window, computed on the
                                             # date-aligned series.
        "momentum_12_1": ...,               # 4dp or null. Position
                                             # momentum_12_1 minus
                                             # benchmark momentum_12_1
                                             # (both on the aligned
                                             # series).
        "relative_12_1": ...                # 4dp or null. The SAME
                                             # skip-a-month momentum
                                             # formula applied to the
                                             # ratio series
                                             # (position/benchmark)
                                             # instead of to either
                                             # series alone.
      },

      # --- additive: only present when "pivots" is given ---
      "pivots": {
        "k": ...,                      # echoed input
        "highs": [{"date", "close"}],  # close-based k-bar swing pivot
        "lows": [{"date", "close"}]    # highs/lows, most recent 10,
                                        # latest first. A pivot high is
                                        # a close STRICTLY greater than
                                        # the k closes on each side (a
                                        # pivot low: strictly less);
                                        # ties are never pivots.
      },

      # --- additive: only present when "series" is true ---
      "series": {
        "sma_50": [{"date", "value"}],  # the 50-close simple moving
                                        # average on every date from the
                                        # 50th close onward (4dp), oldest
                                        # first; the last value equals
                                        # sma_50. Empty when fewer than
                                        # 50 closes.
        "sma_200": [{"date", "value"}]  # likewise for 200 closes.
      }
    }

Validation errors (non-object input, missing/empty/short prices list,
non-positive or non-numeric closes/highs/lows, high < low, negative or
non-numeric volume, missing or duplicate dates, an invalid "benchmark"
list, a "pivots" value that isn't an integer >= 2, or a "series" value
that isn't a boolean) are reported as
``{"error": "..."}`` on stdout with exit code 2.

Interpretation belongs to the caller: per the research notes in the
owning skill, the 12-1 momentum signal relates to 3-12 month
continuation, while the 1w return is dominated by microstructure noise
and is NOT a reversal signal on its own.
"""

from __future__ import annotations

import json
import math
import statistics
import sys

_RETURN_WINDOWS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "12m": 252}
_SKIP_DAYS = 21  # most-recent month skipped by the 12-1 momentum signal
_VOL_WINDOW = 252
_VOL_MIN_RETURNS = 20
_RANGE_WINDOW = 252

_ATR_PERIOD = 14
_ATR_MIN_ROWS = _ATR_PERIOD + 1
_GAP_MIN_ROWS = 60
_REL_VOL_SHORT = 20
_REL_VOL_LONG = 252
_REL_VOL_MIN_ROWS = 30
_DOLLAR_VOL_WINDOW = 20
_RELATIVE_WINDOWS = {"1m": 21, "3m": 63, "12m": 252}


def _round4(value: float | None) -> float | None:
    """Round to 4dp, passing None through."""
    return None if value is None else round(value, 4)


def _round2(value: float | None) -> float | None:
    """Round to 2dp, passing None through."""
    return None if value is None else round(value, 2)


def _parse_positive(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a number")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be a positive finite number")
    return value


def _parse_optional_positive(entry: dict, key: str, label: str) -> float | None:
    value = entry.get(key)
    if value is None:
        return None
    return _parse_positive(value, label)


def _parse_optional_nonnegative(entry: dict, key: str, label: str) -> float | None:
    value = entry.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a number")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a non-negative finite number")
    return value


def _parse_prices(
    params: dict,
) -> tuple[
    list[str], list[float], list[float | None], list[float | None], list[float | None], bool, bool
]:
    """Validate params and return the sorted (by date, ascending) price
    series plus two flags: whether any row carried a "high"/"low" key,
    and whether any row carried a "volume" key.
    """
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    prices = params.get("prices")
    if not isinstance(prices, list) or not prices:
        raise ValueError("prices must be a non-empty list")
    if len(prices) < 2:
        raise ValueError("at least 2 price points are required")

    rows: list[tuple[str, float, float | None, float | None, float | None]] = []
    hl_cols_present = False
    vol_cols_present = False
    for i, entry in enumerate(prices):
        if not isinstance(entry, dict):
            raise ValueError(f"prices[{i}] must be an object")
        date = entry.get("date")
        if not isinstance(date, str) or not date:
            raise ValueError(f"prices[{i}].date must be a non-empty string")
        close = _parse_positive(entry.get("close"), f"prices[{i}].close")
        high = _parse_optional_positive(entry, "high", f"prices[{i}].high")
        low = _parse_optional_positive(entry, "low", f"prices[{i}].low")
        if high is not None and low is not None and high < low:
            raise ValueError(f"prices[{i}].high must be >= prices[{i}].low")
        volume = _parse_optional_nonnegative(entry, "volume", f"prices[{i}].volume")
        if "high" in entry or "low" in entry:
            hl_cols_present = True
        if "volume" in entry:
            vol_cols_present = True
        rows.append((date, close, high, low, volume))

    dates = [r[0] for r in rows]
    if len(set(dates)) != len(dates):
        raise ValueError("duplicate dates in prices")

    rows.sort(key=lambda r: r[0])
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    volumes = [r[4] for r in rows]
    return dates, closes, highs, lows, volumes, hl_cols_present, vol_cols_present


def _parse_benchmark(entries: object) -> tuple[list[str], list[float]]:
    """Validate and return a benchmark (date, close) series sorted by date."""
    if not isinstance(entries, list) or not entries:
        raise ValueError("benchmark must be a non-empty list")

    rows: list[tuple[str, float]] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"benchmark[{i}] must be an object")
        date = entry.get("date")
        if not isinstance(date, str) or not date:
            raise ValueError(f"benchmark[{i}].date must be a non-empty string")
        close = _parse_positive(entry.get("close"), f"benchmark[{i}].close")
        rows.append((date, close))

    dates = [d for d, _ in rows]
    if len(set(dates)) != len(dates):
        raise ValueError("duplicate dates in benchmark")

    rows.sort(key=lambda r: r[0])
    return [d for d, _ in rows], [c for _, c in rows]


def _align_by_date(
    dates_a: list[str], values_a: list[float], dates_b: list[str], values_b: list[float]
) -> tuple[list[float], list[float]]:
    """Pair up values whose dates appear in both series, in ``a``'s date order."""
    lookup_b = dict(zip(dates_b, values_b, strict=True))
    aligned_a: list[float] = []
    aligned_b: list[float] = []
    for date, value in zip(dates_a, values_a, strict=True):
        if date in lookup_b:
            aligned_a.append(value)
            aligned_b.append(lookup_b[date])
    return aligned_a, aligned_b


def _window_return(series: list[float], k: int) -> float | None:
    if len(series) < k + 1:
        return None
    return series[-1] / series[-1 - k] - 1


def _momentum_12_1(series: list[float]) -> float | None:
    window = _RETURN_WINDOWS["12m"]
    if len(series) < window + 1:
        return None
    return series[-1 - _SKIP_DAYS] / series[-1 - window] - 1


def _atr_14_pct(closes: list[float], highs: list[float], lows: list[float]) -> float | None:
    """Wilder-smoothed 14-period ATR as a fraction of the last close.

    Requires every row's high/low to be present; callers gate on that
    (and on the minimum row count) before calling this.
    """
    n = len(closes)
    if n < _ATR_MIN_ROWS:
        return None
    true_ranges = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, n)
    ]
    if len(true_ranges) < _ATR_PERIOD:
        return None
    atr = statistics.fmean(true_ranges[:_ATR_PERIOD])
    for tr in true_ranges[_ATR_PERIOD:]:
        atr = (atr * (_ATR_PERIOD - 1) + tr) / _ATR_PERIOD
    return atr / closes[-1]


def _gap_stats(closes: list[float], highs: list[float], lows: list[float]) -> dict | None:
    n = len(closes)
    if n < _GAP_MIN_ROWS:
        return None
    up_count = 0
    down_count = 0
    for i in range(1, n):
        prev_close = closes[i - 1]
        if lows[i] > prev_close:
            up_count += 1
        if highs[i] < prev_close:
            down_count += 1
    total = n - 1
    return {
        "up_gap_frequency": _round4(up_count / total),
        "up_gap_count": up_count,
        "down_gap_count": down_count,
    }


def _relative_volume(volumes: list[float]) -> float | None:
    n = len(volumes)
    if n < _REL_VOL_MIN_ROWS:
        return None
    window = min(_REL_VOL_LONG, n)
    short_mean = statistics.fmean(volumes[-_REL_VOL_SHORT:])
    long_mean = statistics.fmean(volumes[-window:])
    if long_mean == 0:
        return None
    return short_mean / long_mean


def _avg_dollar_volume(closes: list[float], volumes: list[float]) -> float | None:
    n = len(closes)
    if n < _DOLLAR_VOL_WINDOW:
        return None
    return statistics.fmean(
        c * v
        for c, v in zip(closes[-_DOLLAR_VOL_WINDOW:], volumes[-_DOLLAR_VOL_WINDOW:], strict=True)
    )


def _compute_relative(dates: list[str], closes: list[float], benchmark_input: object) -> dict:
    bench_dates, bench_closes = _parse_benchmark(benchmark_input)
    aligned_closes, aligned_bench = _align_by_date(dates, closes, bench_dates, bench_closes)

    relative: dict[str, float | None] = {}
    for label, k in _RELATIVE_WINDOWS.items():
        pos = _window_return(aligned_closes, k)
        bench = _window_return(aligned_bench, k)
        relative[label] = _round4(pos - bench) if pos is not None and bench is not None else None

    pos_mom = _momentum_12_1(aligned_closes)
    bench_mom = _momentum_12_1(aligned_bench)
    relative["momentum_12_1"] = (
        _round4(pos_mom - bench_mom) if pos_mom is not None and bench_mom is not None else None
    )

    ratio = (
        [c / b for c, b in zip(aligned_closes, aligned_bench, strict=True)] if aligned_bench else []
    )
    relative["relative_12_1"] = _round4(_momentum_12_1(ratio)) if ratio else None
    return relative


def _parse_pivots_k(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        raise ValueError("pivots must be an integer >= 2")
    return value


def _compute_pivots(dates: list[str], closes: list[float], k: int) -> dict:
    n = len(closes)
    highs: list[tuple[str, float]] = []
    lows: list[tuple[str, float]] = []
    for i in range(k, n - k):
        neighbors = closes[i - k : i] + closes[i + 1 : i + 1 + k]
        if not neighbors:
            continue
        if closes[i] > max(neighbors):
            highs.append((dates[i], closes[i]))
        if closes[i] < min(neighbors):
            lows.append((dates[i], closes[i]))
    highs.sort(key=lambda r: r[0], reverse=True)
    lows.sort(key=lambda r: r[0], reverse=True)
    return {
        "k": k,
        "highs": [{"date": d, "close": round(c, 4)} for d, c in highs[:10]],
        "lows": [{"date": d, "close": round(c, 4)} for d, c in lows[:10]],
    }


def _sma_series(dates: list[str], closes: list[float], window: int) -> list[dict]:
    """The trailing ``window``-close simple moving average on every date it exists."""
    if len(closes) < window:
        return []
    total = sum(closes[:window])
    out = [{"date": dates[window - 1], "value": round(total / window, 4)}]
    for i in range(window, len(closes)):
        total += closes[i] - closes[i - window]
        out.append({"date": dates[i], "value": round(total / window, 4)})
    return out


def run_signals(params: dict) -> dict:
    """Compute the signal summary described by ``params``.

    Raises ValueError on invalid input; callers that need the
    stdin/stdout error contract should use main().
    """
    dates, closes, highs, lows, volumes, hl_cols_present, vol_cols_present = _parse_prices(params)
    n = len(closes)
    last = closes[-1]

    returns = {
        label: _round4(last / closes[-1 - k] - 1 if n >= k + 1 else None)
        for label, k in _RETURN_WINDOWS.items()
    }

    momentum_12_1 = None
    if n >= _RETURN_WINDOWS["12m"] + 1:
        momentum_12_1 = closes[-1 - _SKIP_DAYS] / closes[-1 - _RETURN_WINDOWS["12m"]] - 1

    vol_span = min(_VOL_WINDOW, n - 1)
    annualized_volatility = None
    if vol_span >= _VOL_MIN_RETURNS:
        daily = [closes[i] / closes[i - 1] - 1 for i in range(n - vol_span, n)]
        annualized_volatility = statistics.stdev(daily) * math.sqrt(252)

    peak = closes[0]
    max_drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        max_drawdown = min(max_drawdown, close / peak - 1)
    current_drawdown = last / max(closes) - 1

    sma_50 = statistics.fmean(closes[-50:]) if n >= 50 else None
    sma_200 = statistics.fmean(closes[-200:]) if n >= 200 else None

    range_window = closes[-min(_RANGE_WINDOW, n) :]
    high_52w = max(range_window)
    low_52w = min(range_window)

    result = {
        "as_of": dates[-1],
        "last_close": round(last, 4),
        "observations": n,
        "returns": returns,
        "momentum_12_1": _round4(momentum_12_1),
        "annualized_volatility": _round4(annualized_volatility),
        "max_drawdown": _round4(max_drawdown),
        "current_drawdown": _round4(current_drawdown),
        "sma_50": _round4(sma_50),
        "sma_200": _round4(sma_200),
        "price_vs_sma_50": _round4(last / sma_50 - 1 if sma_50 else None),
        "price_vs_sma_200": _round4(last / sma_200 - 1 if sma_200 else None),
        "high_52w": round(high_52w, 4),
        "low_52w": round(low_52w, 4),
        "pct_from_52w_high": _round4(last / high_52w - 1),
        "pct_from_52w_low": _round4(last / low_52w - 1),
    }

    if hl_cols_present:
        hl_complete = all(
            h is not None and low is not None for h, low in zip(highs, lows, strict=True)
        )
        result["atr_14_pct"] = (
            _round4(_atr_14_pct(closes, highs, lows))
            if hl_complete and n >= _ATR_MIN_ROWS
            else None
        )
        result["gap_stats"] = (
            _gap_stats(closes, highs, lows) if hl_complete and n >= _GAP_MIN_ROWS else None
        )

    if vol_cols_present:
        vol_complete = all(v is not None for v in volumes)
        result["relative_volume_20_252"] = (
            _round4(_relative_volume(volumes)) if vol_complete and n >= _REL_VOL_MIN_ROWS else None
        )
        result["avg_dollar_volume_20"] = (
            _round2(_avg_dollar_volume(closes, volumes))
            if vol_complete and n >= _DOLLAR_VOL_WINDOW
            else None
        )

    benchmark_input = params.get("benchmark")
    if benchmark_input is not None:
        result["relative"] = _compute_relative(dates, closes, benchmark_input)

    pivots_input = params.get("pivots")
    if pivots_input is not None:
        k = _parse_pivots_k(pivots_input)
        result["pivots"] = _compute_pivots(dates, closes, k)

    series_input = params.get("series")
    if series_input is not None:
        if not isinstance(series_input, bool):
            raise ValueError("series must be a boolean")
        if series_input:
            result["series"] = {
                "sma_50": _sma_series(dates, closes, 50),
                "sma_200": _sma_series(dates, closes, 200),
            }

    return result


def main() -> None:
    """Read JSON params from stdin, write the signal summary (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
        result = run_signals(params)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
