#!/usr/bin/env python3
"""Annualized return at today's price for each valuation scenario (stdin -> stdout JSON).

    python returns.py < input.json

Exit 0 with the result, or exit 2 with ``{"error": "..."}``. Pure arithmetic. Two modes:

``paths`` (model.py's ``returns_input``)::

    {"mode": "paths", "price": 50, "horizon": 5, "hurdle": 0.10,
     "scenarios": [{"name", "distributions_per_share": [one per year], "exit_value_per_share",
                    "exit_multiple_value": null}]}

``convergence`` (quick mode, from a dcf.py fair value)::

    {"mode": "convergence", "price": 50, "horizon": 5, "hurdle": 0.10,
     "scenarios": [{"name", "fair_value", "cost_of_equity", "dividend_yield"}]}

The price closes on fair value by the horizon; fair value compounds at cost_of_equity -
dividend_yield and pays dividend_yield on the prior year's value, so buying at fair value earns the
cost of equity exactly.

Output: {"mode", "price", "horizon", "hurdle", "scenarios": [{"name", "irr", "irr_at_multiple",
"total_multiple", "hurdle_exit_value", "exit_value_per_share", "distributions_total"}],
"assumptions": [...], "flags": [{"code", "message"}]}. ``irr`` solves price = sum of discounted
distributions + discounted exit by bisection on [-0.99, 5]; null when no rate in that range does.
``hurdle_exit_value`` is the exit value per share that earns exactly the hurdle. When the exit plus
distributions is not positive, ``irr`` is -1 and TOTAL_LOSS is flagged. A negative exit value is
floored at 0 (a shareholder cannot lose more than the price) and flagged EXIT_FLOORED; an IRR the
bracket cannot reach is null and flagged IRR_UNSOLVED.
"""

from __future__ import annotations

import json
import math
import sys

_LOW, _HIGH, _ITER = -0.99, 5.0, 200


def _num(v: object, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


def _npv(rate: float, price: float, dists: list[float], exit_v: float) -> float:
    h = len(dists)
    return sum(d / (1 + rate) ** t for t, d in enumerate(dists, start=1)) + exit_v / (1 + rate) ** h - price


def _irr(price: float, dists: list[float], exit_v: float) -> float | None:
    lo, hi = _LOW, _HIGH
    f_lo, f_hi = _npv(lo, price, dists, exit_v), _npv(hi, price, dists, exit_v)
    if f_lo * f_hi > 0:
        return None
    for _ in range(_ITER):
        mid = (lo + hi) / 2
        f_mid = _npv(mid, price, dists, exit_v)
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return round((lo + hi) / 2, 6)


def run_returns(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    mode = params.get("mode")
    if mode not in ("paths", "convergence"):
        raise ValueError("mode must be paths or convergence")
    price = _num(params.get("price"), "price")
    if price <= 0:
        raise ValueError("price must be positive")
    h = params.get("horizon")
    if isinstance(h, bool) or not isinstance(h, (int, float)) or int(h) != h or h < 1:
        raise ValueError("horizon must be a positive integer")
    h = int(h)
    hurdle = _num(params.get("hurdle", 0.10), "hurdle")
    scenarios = params.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("scenarios must be a list")
    assumptions = [f"Bought at {price:g} today and held {h} years; distributions arrive at each year end."]
    if mode == "convergence":
        assumptions.append("The price closes on fair value by the horizon; fair value compounds at the cost of equity less the dividend yield.")
    else:
        assumptions.append("Distributions are dividends plus buybacks from the model's free cash flow to equity; the exit value is the model's value at the horizon.")
    out, flags = [], []
    for i, sc in enumerate(scenarios):
        name = sc.get("name") or f"#{i + 1}"
        mult_v = None
        if mode == "paths":
            dists = sc.get("distributions_per_share")
            if not isinstance(dists, list) or len(dists) != h:
                raise ValueError(f"{name}: distributions_per_share must have {h} entries")
            dists = [_num(d, f"{name}.distributions_per_share") for d in dists]
            exit_v = _num(sc.get("exit_value_per_share"), f"{name}.exit_value_per_share")
            if sc.get("exit_multiple_value") is not None:
                mult_v = _num(sc["exit_multiple_value"], f"{name}.exit_multiple_value")
        else:
            fv = _num(sc.get("fair_value"), f"{name}.fair_value")
            ke = _num(sc.get("cost_of_equity"), f"{name}.cost_of_equity")
            y = _num(sc.get("dividend_yield", 0.0), f"{name}.dividend_yield")
            vals = [fv * (1 + ke - y) ** t for t in range(h + 1)]
            dists = [y * vals[t - 1] for t in range(1, h + 1)]
            exit_v = vals[h]
        if exit_v < 0 or (mult_v is not None and mult_v < 0):
            flags.append({"code": "EXIT_FLOORED", "message": f"{name}: the value per share at the horizon is below zero; a shareholder's loss stops at the price paid, so it counts as 0."})
            exit_v = max(exit_v, 0.0)
            mult_v = None if mult_v is None else max(mult_v, 0.0)
        total = sum(dists) + exit_v
        if total <= 0:
            irr = -1.0
            flags.append({"code": "TOTAL_LOSS", "message": f"{name}: nothing comes back to the holder in this scenario."})
        else:
            irr = _irr(price, dists, exit_v)
            if irr is None:
                flags.append({"code": "IRR_UNSOLVED", "message": f"{name}: no annual return between -99% and +500% reproduces the price."})
        hurdle_exit = (price - sum(d / (1 + hurdle) ** t for t, d in enumerate(dists, start=1))) * (1 + hurdle) ** h
        out.append({
            "name": name, "irr": irr,
            "irr_at_multiple": None if mult_v is None else (_irr(price, dists, mult_v) if sum(dists) + mult_v > 0 else -1.0),
            "total_multiple": round(total / price, 4), "hurdle_exit_value": round(hurdle_exit, 2),
            "exit_value_per_share": round(exit_v, 2), "distributions_total": round(sum(dists), 4),
        })
    return {"mode": mode, "price": price, "horizon": h, "hurdle": hurdle, "scenarios": out, "assumptions": assumptions, "flags": flags}


def main() -> None:
    try:
        result = run_returns(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
