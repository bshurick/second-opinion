"""Money-weighted return (MWRR) for one portfolio from its external cash flows
and a current valuation.

This script reads a JSON object from stdin, solves the internal rate of
return by bisection, compares the result with a benchmark over the same
window, and writes a JSON object to stdout. It is invoked as:

    python performance.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "flows": [                                     # net external cash flows:
        {"date": "2025-09-05", "amount": 1000.0},    #   deposit  -> amount > 0
        {"date": "2025-12-05", "amount": -100.0},    #   withdrawal -> amount < 0
        ...                                          # optional; default []
      ],
      "current_value": 2000.0,      # required, >= 0: the portfolio's value at as_of
      "as_of": "2026-09-05",        # optional, default today (YYYY-MM-DD)
      "benchmark": {                # optional benchmark comparison
        "symbol": "SPY",
        "prices": [{"date": "YYYY-MM-DD", "close": 100.0, "adj_close": 100.0}, ...]
      }
    }

Output JSON contract (stdout)::

    {
      "as_of": "YYYY-MM-DD",
      "flow_count": 2,
      "net_flows": 900.0,            # 2dp: sum of the flow amounts
      "current_value": 2000.0,       # 2dp echo
      "window": {"start": "YYYY-MM-DD" | null,   # first flow date
                 "end": "YYYY-MM-DD",            # as_of
                 "days": 365 | null},            # as_of - first flow date
      "mwrr": 0.1234 | null,       # annualized money-weighted return, 4dp
      "benchmark_total_return": 0.1 | null,      # fraction over the window, 4dp
      "benchmark_annualized": 0.1 | null,        # (1+total)^(365/days) - 1, 4dp
      "flags": [{"code": "...", "message": "..."}]
    }

Method: the IRR solves ``current_value = sum(flow_i * (1+r)^t_i)`` with
``t_i`` the years from flow i to ``as_of`` (deposits positive) -- the
standard IRR equation written with the flows compounded forward to as_of.
Bisection on the annual rate r in [-0.99, 10]: 100 iterations,
tolerance 1e-10 on the residual. The reported rate is annualized
(compound-equivalent); no non-annualized variant is reported. Flows dated
after ``as_of`` are ignored (a future flow has no discounting term yet).

Flags:
- ``TOO_FEW_FLOWS``: fewer than 2 flows -> ``mwrr`` is null (a
  money-weighted return needs at least 2 external flows).
- ``IRR_NOT_BRACKETED``: the residual has the same sign at both ends of
  [-0.99, 10], so there is no rate to report -> ``mwrr`` null.
- ``BENCHMARK_UNAVAILABLE``: fires only when a benchmark block IS supplied
  but its price list has fewer than 2 usable rows -> benchmark fields null.
  A request with no ``benchmark`` block at all is not flagged; the
  benchmark fields are simply null.

Validation errors (non-object input, missing/negative/non-numeric
current_value, malformed flows) are reported as ``{"error": "..."}`` on
stdout with exit code 2.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any

_RATE_MIN = -0.99
_RATE_MAX = 10.0
_MAX_ITERATIONS = 100
_TOLERANCE = 1e-10
_TOO_FEW_FLOWS = "too few external flows; a money-weighted return needs them"


def _flows(params: dict[str, Any]) -> list[tuple[date, float]]:
    flows = params.get("flows")
    if flows is None:
        return []
    if not isinstance(flows, list):
        raise ValueError("flows must be a list")
    out: list[tuple[date, float]] = []
    for flow in flows:
        if not isinstance(flow, dict):
            raise ValueError("each flow must be an object")
        if "date" not in flow or "amount" not in flow:
            raise ValueError("each flow requires 'date' and 'amount'")
        try:
            when = date.fromisoformat(str(flow["date"])[:10])
        except ValueError as exc:
            raise ValueError(f"flow date must be YYYY-MM-DD, got {flow['date']!r}") from exc
        amount = flow["amount"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError("flow amount must be numeric")
        out.append((when, float(amount)))
    return out


def _current_value(params: dict[str, Any]) -> float:
    if "current_value" not in params:
        raise ValueError("current_value is required")
    value = params["current_value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("current_value must be numeric")
    if value < 0:
        raise ValueError("current_value must not be negative")
    return float(value)


def _benchmark(benchmark: object) -> tuple[float, list[tuple[str, float]]]:
    """(unrounded total return, usable dated price rows) from the benchmark block.

    ``adj_close`` is preferred over ``close`` when a row carries both; rows
    without a usable positive price are skipped. Fewer than two usable rows
    means no benchmark return: (0.0, []).
    """
    if not isinstance(benchmark, dict):
        return 0.0, []
    rows: list[tuple[str, float]] = []
    for row in benchmark.get("prices") or []:
        if not isinstance(row, dict):
            continue
        when = str(row.get("date") or "")[:10]
        price = row.get("adj_close")
        if price is None:
            price = row.get("close")
        if when and isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
            rows.append((when, float(price)))
    rows.sort()
    if len(rows) < 2:
        return 0.0, []
    return rows[-1][1] / rows[0][1] - 1, rows


def run_performance(params: dict[str, Any]) -> dict[str, Any]:
    """Run the MWRR/benchmark analysis described by ``params``.

    Raises ValueError (or TypeError for non-numeric fields) on invalid input;
    callers that need the stdin/stdout error contract should use main().
    """
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")

    current_value = _current_value(params)
    flows = _flows(params)
    as_of_raw = params.get("as_of")
    as_of = date.fromisoformat(str(as_of_raw)[:10]) if as_of_raw else date.today()

    flows = [(when, amount) for when, amount in flows if when <= as_of]
    net_flows = sum(amount for _, amount in flows)
    first_flow = min((when for when, _ in flows), default=None)
    days = (as_of - first_flow).days if first_flow else None

    flags: list[dict[str, str]] = []
    mwrr: float | None = None
    if len(flows) < 2:
        flags.append({"code": "TOO_FEW_FLOWS", "message": _TOO_FEW_FLOWS})
    else:
        solved = _solve_irr(flows, as_of, current_value)
        if isinstance(solved, float):
            mwrr = round(solved, 4)
        else:
            flags.append({"code": "IRR_NOT_BRACKETED", "message": solved})

    benchmark = params.get("benchmark")
    total, rows = _benchmark(benchmark)
    benchmark_total: float | None = None
    benchmark_annualized: float | None = None
    if rows:
        benchmark_total = round(total, 4)
        if days and days > 0:
            benchmark_annualized = round((1 + total) ** (365 / days) - 1, 4)
    elif benchmark is not None:
        # a benchmark was requested (or the fetch failed) but no usable history came back
        flags.append(
            {
                "code": "BENCHMARK_UNAVAILABLE",
                "message": "no benchmark price history over the window",
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "flow_count": len(flows),
        "net_flows": round(net_flows, 2),
        "current_value": round(current_value, 2),
        "window": {
            "start": first_flow.isoformat() if first_flow else None,
            "end": as_of.isoformat(),
            "days": days,
        },
        "mwrr": mwrr,
        "benchmark_total_return": benchmark_total,
        "benchmark_annualized": benchmark_annualized,
        "flags": flags,
    }


def _solve_irr(flows: list[tuple[date, float]], as_of: date, current_value: float) -> float | str:
    """Bisection on the annual rate in [-0.99, 10]; the rate, or a reason string."""

    def npv(rate: float) -> float:
        total = 0.0
        for when, amount in flows:
            total += amount * (1.0 + rate) ** ((as_of - when).days / 365.0)
        return current_value - total

    lo, hi = _RATE_MIN, _RATE_MAX
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if f_lo * f_hi > 0:
        return f"no rate in [{_RATE_MIN}, {_RATE_MAX}] solves the MWRR equation"
    mid = lo
    for _ in range(_MAX_ITERATIONS):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) <= _TOLERANCE or (hi - lo) / 2 <= 1e-12:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return mid


def main() -> None:
    """Read JSON params from stdin, write the performance result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
        result = run_performance(params)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
