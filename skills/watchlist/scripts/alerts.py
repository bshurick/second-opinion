"""Watchlist alert evaluation: price above/below, daily move, change since
added, drawdown from and proximity to the 52-week high, 50/200-day MA cross,
and volume spike, per watched symbol.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python alerts.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "as_of": "2026-09-04",                        # optional
      "watchlist": [{"symbol": "AAPL", "note": "...", "added": "2026-06-01",
                     "added_price": 170.0,
                     "rules": [{"type": "price_below", "value": 150},
                               {"type": "price_above", "value": 200},
                               {"type": "day_move", "value": 0.05},        # |day change| >= 5%
                               {"type": "from_added", "value": -0.10},     # <= -10% since added;
                                                                # a positive value means >= +x%
                               {"type": "drawdown", "value": 0.15},        # >= 15% below 52w high
                               {"type": "near_52w_high", "value": 0.05},   # drawdown <= 5%
                               {"type": "ma_cross", "value": 1},      # +1 golden (50d MA crosses
                                      # above 200d), -1 death cross
                               {"type": "volume_spike", "value": 2.0}]}],  # vol >= 2x 20d avg
      "quotes": {"AAPL": {"price": 148.0, "previous_close": 160.0}},
      "highs_52w": {"AAPL": 200.0},                 # optional
      "closes": {"AAPL": [170.0, ...]},             # optional, ascending by date;
                              # > 200 rows (i.e. 201+) required for ma_cross: the
                              # 200-day MA needs 200 closes AND a prior session's
                              # 200-day MA to compare against, otherwise it is unevaluated
      "volumes": {"AAPL": [1e6, ...]}               # optional, aligned with closes; >= 21 rows
                                                    # required for volume_spike
    }

Output JSON contract (stdout)::

    {
      "as_of",
      "watchlist": [{symbol, note, added, added_price, price, previous_close,
                     day_change_pct, since_added_pct, from_52w_high, quote_missing,
                     triggered: [{type, value, current, message}],
                     untriggered: [{type, value, current}]}],
      "triggered": [{symbol, type, message}],       # flat, in watchlist order
      "summary": {symbols, with_rules, triggered_symbols, triggered_rules, missing_quotes},
      "flags": [{code, message}]                    # MISSING_QUOTES, NO_RULES
    }

Semantics of the series rules: ``ma_cross`` +1 triggers when the 50-day simple
MA finished the last session above the 200-day while the session before it was
at or below (golden cross); -1 is the mirror. ``near_52w_high`` triggers when
the drawdown from the 52-week high is at or below ``value``. ``volume_spike``
triggers when the latest volume is at or above ``value`` times the mean of the
prior 20 volumes.

Rules that cannot be evaluated (no quote, no 52-week high, no added price, too
few closes or volumes) are left out of both lists. Percentages in messages are
1 dp; ratios 4 dp.
"""

from __future__ import annotations

import json
import sys
from datetime import date

_TYPES = (
    "price_above",
    "price_below",
    "day_move",
    "from_added",
    "drawdown",
    "near_52w_high",
    "ma_cross",
    "volume_spike",
)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _num(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    try:
        return float(v)
    except ValueError as exc:
        raise TypeError(f"{field} must be numeric") from exc


def _pct(v: float, signed: bool = True) -> str:
    return f"{v * 100:+.1f}%" if signed else f"{abs(v) * 100:.1f}%"


def _sma(series: list[float], window: int) -> float | None:
    data = series[-window:]
    return sum(data) / len(data) if len(data) == window else None


def _evaluate(
    symbol: str,
    rule: dict,
    price: float | None,
    day: float | None,
    since: float | None,
    dd: float | None,
    added_price: float | None,
) -> tuple[bool | None, float | None, str | None]:
    """(triggered, current, message) or (None, ...) when the rule cannot be evaluated."""
    kind, value = rule["type"], rule["value"]
    if kind == "price_above":
        if price is None:
            return None, None, None
        return price >= value, price, f"{symbol} {price:.2f} is above {value:.2f}"
    if kind == "price_below":
        if price is None:
            return None, None, None
        return price <= value, price, f"{symbol} {price:.2f} is below {value:.2f}"
    if kind == "day_move":
        if day is None:
            return None, None, None
        return (
            abs(day) >= value,
            abs(day),
            f"{symbol} moved {_pct(day)} today (threshold {_pct(value, signed=False)})",
        )
    if kind == "from_added":
        if since is None:
            return None, None, None
        hit = since <= value if value < 0 else since >= value
        return (
            hit,
            since,
            f"{symbol} is {_pct(since)} since added at {added_price:.2f} (threshold {_pct(value)})",
        )
    if kind == "ma_cross":
        closes = rule["_closes"]
        if len(closes) < 200:
            return None, None, None
        ma50, ma200 = _sma(closes, 50), _sma(closes, 200)
        prev50, prev200 = _sma(closes[:-1], 50), _sma(closes[:-1], 200)
        if ma50 is None or ma200 is None or prev50 is None or prev200 is None:
            return None, None, None
        golden = ma50 > ma200 and prev50 <= prev200
        death = ma50 < ma200 and prev50 >= prev200
        hit = golden if value > 0 else death
        side = "above" if value > 0 else "below"
        return (
            hit,
            ma50 / ma200 - 1,
            f"{symbol} 50-day MA {ma50:.2f} crossed {side} its 200-day MA {ma200:.2f}",
        )
    if kind == "volume_spike":
        volumes = rule["_volumes"]
        if len(volumes) < 21:
            return None, None, None
        latest, base = volumes[-1], sum(volumes[-21:-1]) / 20
        ratio = latest / base if base else None
        if ratio is None:
            return None, None, None
        return (
            ratio >= value,
            ratio,
            f"{symbol} volume {latest:,.0f} is {ratio:.1f}x its 20-day average "
            f"(threshold {value:.1f}x)",
        )
    if dd is None:
        return None, None, None
    if kind == "drawdown":
        return (
            dd >= value,
            dd,
            f"{symbol} is {_pct(-dd)} from its 52-week high of {rule['_high']:.2f} "
            f"(threshold {_pct(-value)})",
        )
    if kind == "near_52w_high":
        return (
            dd <= value,
            dd,
            f"{symbol} is {_pct(-dd)} from its 52-week high of {rule['_high']:.2f} "
            f"(within {_pct(value, signed=False)})",
        )
    return None, None, None


def run_alerts(params: dict) -> dict:
    """Evaluate the watchlist rules in ``params``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    watch = params.get("watchlist")
    if not isinstance(watch, list) or not watch:
        raise ValueError("watchlist must be a non-empty list")
    quotes = params.get("quotes") or {}
    highs = params.get("highs_52w") or {}
    closes_map = params.get("closes") or {}
    volumes_map = params.get("volumes") or {}
    if not isinstance(closes_map, dict) or not isinstance(volumes_map, dict):
        raise ValueError("closes and volumes must be objects keyed by symbol")
    as_of = str(params.get("as_of") or date.today().isoformat())

    rows: list[dict] = []
    flat: list[dict] = []
    missing: list[str] = []
    no_rules: list[str] = []
    for w in watch:
        if not isinstance(w, dict) or not w.get("symbol"):
            raise ValueError("each watchlist entry requires a symbol")
        sym = str(w["symbol"]).upper()
        rules = w.get("rules") or []
        for r in rules:
            if not isinstance(r, dict) or r.get("type") not in _TYPES:
                raise ValueError(f"rule type must be one of: {', '.join(_TYPES)}")
            value = _num(r.get("value"), "value")
            if value is None:
                raise ValueError("each rule requires a numeric value")
            if r["type"] == "ma_cross" and value not in (1, -1):
                raise ValueError("ma_cross value must be +1 (golden cross) or -1 (death cross)")
        q = quotes.get(sym) if isinstance(quotes.get(sym), dict) else {}
        price, prev = _num(q.get("price"), "price"), _num(q.get("previous_close"), "previous_close")
        high = _num(highs.get(sym), "high")
        added_price = _num(w.get("added_price"), "added_price")
        day = price / prev - 1 if price is not None and prev else None
        since = price / added_price - 1 if price is not None and added_price else None
        from_high = price / high - 1 if price is not None and high else None
        dd = (
            -from_high
            if from_high is not None and from_high < 0
            else (0.0 if from_high is not None else None)
        )
        sym_closes = [
            c for c in (_num(v, "closes") for v in (closes_map.get(sym) or [])) if c is not None
        ]
        sym_volumes = [
            v for v in (_num(x, "volumes") for x in (volumes_map.get(sym) or [])) if v is not None
        ]
        triggered, untriggered = [], []
        for r in rules:
            rule = {
                "type": r["type"],
                "value": float(r["value"]),
                "_high": high,
                "_closes": sym_closes,
                "_volumes": sym_volumes,
            }
            hit, current, message = _evaluate(sym, rule, price, day, since, dd, added_price)
            if hit is None:
                continue
            if hit:
                triggered.append(
                    {
                        "type": rule["type"],
                        "value": rule["value"],
                        "current": _r4(current),
                        "message": message,
                    }
                )
                flat.append({"symbol": sym, "type": rule["type"], "message": message})
            else:
                untriggered.append(
                    {"type": rule["type"], "value": rule["value"], "current": _r4(current)}
                )
        if price is None:
            missing.append(sym)
        if not rules:
            no_rules.append(sym)
        rows.append(
            {
                "symbol": sym,
                "note": w.get("note"),
                "added": w.get("added"),
                "added_price": added_price,
                "price": price,
                "previous_close": prev,
                "day_change_pct": _r4(day),
                "since_added_pct": _r4(since),
                "from_52w_high": _r4(from_high),
                "quote_missing": price is None,
                "triggered": triggered,
                "untriggered": untriggered,
            }
        )
    flags = []
    if missing:
        flags.append({"code": "MISSING_QUOTES", "message": "no quote for: " + ", ".join(missing)})
    if no_rules:
        flags.append(
            {"code": "NO_RULES", "message": "watched without alert rules: " + ", ".join(no_rules)}
        )
    summary = {
        "symbols": len(rows),
        "with_rules": sum(1 for w in watch if w.get("rules")),
        "triggered_symbols": sum(1 for r in rows if r["triggered"]),
        "triggered_rules": len(flat),
        "missing_quotes": len(missing),
    }
    return {
        "as_of": as_of,
        "watchlist": rows,
        "triggered": flat,
        "summary": summary,
        "flags": flags,
    }


def main() -> None:
    """Read JSON params from stdin, write the evaluation (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_alerts(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
