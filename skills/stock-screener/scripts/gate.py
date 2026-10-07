#!/usr/bin/env python3
"""The downside gate for deep picks (stdin -> stdout JSON).

    python gate.py < gate.json

Input: {"hurdle": 0.10, "floor": 0.0, "finalists": [{"symbol", "price", "page",
"model": <valuation model.py output>, "returns": <valuation returns.py output>}]}.

Rule B. Each finalist's scenarios are matched to their returns by name. It passes when every
scenario's annual return is at least ``floor`` (default 0: no scenario loses money over the
horizon, dividends included) and the central scenario (the first in ``model.scenarios``) earns
at least ``hurdle`` (default 10%). A scenario with no return (unmatched or null) fails. A
finalist that passes while every scenario's value sits above the price is ``pass_flagged``: a
downside case may be missing.

A non-finite return (NaN) counts as not computed. When ``returns`` carries the price it was
computed at, the gate uses that price, and exits 2 when it differs from the finalist's ``price`` by
more than 1%.

Output: {"hurdle", "floor", "results": [{"symbol", "price", "verdict": "pass"|"pass_flagged"|
"fail", "value_range": [lowest, highest scenario value per share], "central": {"name", "irr",
"value_per_share"}, "worst": {...}, "checks": {"worst_ok",
"central_ok", "all_above_price"}, "reasons": [str], "page", "implied"}], "counts": {"pass",
"pass_flagged", "fail"}}. Results run pass, pass_flagged, fail, each by central return, highest
first. Exit 2 with {"error"} on invalid input.
"""

from __future__ import annotations

import json
import math
import sys

ORDER = {"pass": 0, "pass_flagged": 1, "fail": 2}
PRICE_TOLERANCE = 0.01  # a finalist's price and the price its returns used may differ by rounding only


def _num(v: object, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


def _pct(v: float) -> str:
    return f"{abs(v) * 100:.1f}%"


def run_gate(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    hurdle = _num(params.get("hurdle", 0.10), "hurdle")
    floor = _num(params.get("floor", 0.0), "floor")
    if hurdle <= -1 or floor <= -1:
        raise ValueError("hurdle and floor must be above -1")
    finalists = params.get("finalists")
    if not isinstance(finalists, list) or not finalists:
        raise ValueError("finalists must be a non-empty list")
    results = []
    for f in finalists:
        sym = f.get("symbol") if isinstance(f, dict) else None
        if not sym:
            raise ValueError("every finalist needs a symbol")
        price = _num(f.get("price"), f"{sym}.price")
        if price <= 0:
            raise ValueError(f"{sym}.price must be positive")
        r_price = (f.get("returns") or {}).get("price") if isinstance(f.get("returns"), dict) else None
        if r_price is not None:  # the returns were computed at this price, so the gate uses it too
            r_price = _num(r_price, f"{sym}.returns.price")
            if abs(r_price / price - 1) > PRICE_TOLERANCE:
                raise ValueError(f"{sym}: price {price:g} differs from the price the returns used ({r_price:g}); rerun returns.py or fix the price")
            price = r_price
        scen = ((f.get("model") or {}).get("scenarios")) if isinstance(f.get("model"), dict) else None
        rets = ((f.get("returns") or {}).get("scenarios")) if isinstance(f.get("returns"), dict) else None
        if not isinstance(scen, list) or not scen or not isinstance(rets, list):
            raise ValueError(f"{sym}: needs model.scenarios and returns.scenarios")
        irr_by = {r.get("name"): r.get("irr") for r in rets if isinstance(r, dict)}
        rows = [{"name": s.get("name"), "irr": irr_by.get(s.get("name")), "value_per_share": s.get("value_per_share")} for s in scen]
        reasons = []
        missing = [r["name"] for r in rows
                   if not isinstance(r["irr"], (int, float)) or isinstance(r["irr"], bool) or not math.isfinite(r["irr"])]
        for r in rows:
            if r["name"] in missing:
                r["irr"] = None  # never echo NaN or infinity back out
        for name in missing:
            reasons.append(f"The return for scenario '{name}' could not be computed.")
        known = [r for r in rows if r["name"] not in missing]
        central = rows[0]
        worst = min(known, key=lambda r: r["irr"]) if known else None
        worst_ok = not missing and worst is not None and worst["irr"] >= floor
        central_ok = central["name"] not in missing and central["irr"] >= hurdle
        all_above = all(isinstance(r["value_per_share"], (int, float)) and r["value_per_share"] > price for r in rows)
        if worst is not None and worst["irr"] < floor:
            verb = "loses" if worst["irr"] < 0 else "earns"
            reasons.insert(0, f"Worst scenario '{worst['name']}' {verb} {_pct(worst['irr'])} a year, below the {floor * 100:.1f}% floor.")
        if central["name"] not in missing and central["irr"] < hurdle:
            reasons.append(f"Central scenario '{central['name']}' earns {central['irr'] * 100:.1f}% a year, below the {hurdle * 100:.1f}% hurdle.")
        if worst_ok and central_ok:
            verdict = "pass_flagged" if all_above else "pass"
            if all_above:
                reasons.append("Every scenario is worth more than the price; a downside case may be missing.")
        else:
            verdict = "fail"
        values = [r["value_per_share"] for r in rows if isinstance(r["value_per_share"], (int, float)) and not isinstance(r["value_per_share"], bool)]
        results.append({"symbol": sym, "price": price, "verdict": verdict,
                        "value_range": [min(values), max(values)] if values else None,
                        "central": central, "worst": worst,
                        "checks": {"worst_ok": worst_ok, "central_ok": central_ok, "all_above_price": all_above},
                        "reasons": reasons, "page": f.get("page"), "implied": (f.get("model") or {}).get("implied")})
    results.sort(key=lambda r: (ORDER[r["verdict"]], -(r["central"]["irr"] if isinstance(r["central"]["irr"], (int, float)) else -9)))
    counts = {k: sum(1 for r in results if r["verdict"] == k) for k in ORDER}
    return {"hurdle": hurdle, "floor": floor, "results": results, "counts": counts}


def main() -> None:
    try:
        result = run_gate(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
