#!/usr/bin/env python3
"""The gate for deep picks: the downside rule for value runs, the best-case rule for growth runs (stdin -> stdout JSON).

    python gate.py < gate.json

Input: {"hurdle": 0.10, "floor": 0.0, "finalists": [{"symbol", "price", "page",
"model": <valuation model.py output>, "returns": <valuation returns.py output>}]}.

Rule B. Each finalist's scenarios are matched to their returns by name. It passes when every
gated scenario's annual return is at least ``floor`` (default 0: no gated scenario loses money over
the horizon, dividends included) and the central scenario (the first in ``model.scenarios``) earns
at least ``hurdle`` (default 10%). A gated scenario with no return (unmatched or null) fails. A
scenario marked ``"stress": true`` in ``model.scenarios`` (the compound "several risks at once"
test) is not gated: it is reported as ``stress`` and named in ``reasons`` when it loses money, so the
worst case judged is the severest single story. A finalist that passes while every gated
scenario's value sits above the price is ``pass_flagged``: a downside case may be missing.

Growth profile. ``"profile": "growth"`` (default ``"value"``) swaps the rule: ``hurdle`` and ``floor``
are rejected (exit 2) and ``min_upside`` (default 2.0, must be above 1) applies. The horizon is the
finalist's ``model.horizon`` (a whole number of years, 1 or more; otherwise that finalist fails with
a reason). A finalist passes when its best scenario (the highest return among the gated scenarios;
the stress test is never the best) earns at least ``min_upside ** (1 / horizon) - 1`` a year
(``growth.best_irr_needed``) AND the central scenario's value is above the price. It is
``pass_flagged`` when it passes while every gated scenario's value sits above the price. The worst
scenario is still reported in ``worst`` but is not gated; ``value_range`` and ``stress`` keep their
value-rule meaning. Any gated (non-stress) scenario with no computed return fails the finalist, with
a "could not be computed" reason; the best and central scenarios also need a numeric value per
share. Output adds top-level ``profile`` and ``min_upside`` (and no ``hurdle`` or
``floor``); each result adds ``best`` ({"name", "irr", "value_per_share"} or null), ``best_multiple``
((1 + best.irr) ** horizon, 2 decimals, or null) and ``checks`` is {"best_ok", "central_above_price",
"all_above_price"}. Results run pass, pass_flagged, fail, each by best return, highest first. Value
output carries no ``profile`` key and is unchanged.

A non-finite return (NaN) counts as not computed. When ``returns`` carries the price it was
computed at, the gate uses that price, and exits 2 when it differs from the finalist's ``price`` by
more than 1%.

Output: {"hurdle", "floor", "results": [{"symbol", "price", "verdict": "pass"|"pass_flagged"|
"fail", "value_range": [lowest, highest scenario value per share, the stress test included],
"central": {"name", "irr", "value_per_share"}, "worst": {...} (the lowest-return gated scenario),
"stress": {...} or null, "checks": {"worst_ok",
"central_ok", "all_above_price"}, "reasons": [str], "page", "implied"}], "counts": {"pass",
"pass_flagged", "fail"}}. Results run pass, pass_flagged, fail, each by central return, highest
first. Exit 2 with {"error"} on invalid input.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import growth  # noqa: E402

ORDER = {"pass": 0, "pass_flagged": 1, "fail": 2}
PRICE_TOLERANCE = 0.01  # a finalist's price and the price its returns used may differ by rounding only


def _num(v: object, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


def _pct(v: float) -> str:
    return f"{abs(v) * 100:.1f}%"


def _growth_result(f: dict, price: float, rows: list[dict], stress: dict | None, min_upside: float, horizon: object) -> dict:
    """One finalist under the growth rule: best-case annual return vs the multiple wanted, central above price."""
    reasons = []
    known = [r for r in rows if r["irr"] is not None]
    best = max(known, key=lambda r: r["irr"]) if known else None
    worst = min(known, key=lambda r: r["irr"]) if known else None
    central = rows[0]
    h_ok = isinstance(horizon, int) and not isinstance(horizon, bool) and horizon >= 1
    best_ok = False
    best_multiple = None
    if not h_ok:
        reasons.append("The model has no valid horizon (a whole number of years, 1 or more), so the best case cannot be judged.")
    elif best is None:
        reasons.append("No scenario has a computed return, so the best case cannot be judged.")
    else:
        needed = growth.best_irr_needed(min_upside, horizon)
        best_multiple = round((1 + best["irr"]) ** horizon, 2)
        best_ok = best["irr"] >= needed
        if not best_ok:
            reasons.append(f"Best scenario '{best['name']}' earns {best['irr'] * 100:.1f}% a year, below the {needed * 100:.1f}% a year "
                           f"that {'doubles' if min_upside == 2 else 'multiplies'} the money ({min_upside:.1f}x) over {horizon} years.")
    missing = [r["name"] for r in rows if r["irr"] is None]
    for name in missing:
        reasons.append(f"The return for scenario '{name}' could not be computed.")
    best_value_ok = best is not None and isinstance(best["value_per_share"], (int, float)) and not isinstance(best["value_per_share"], bool)
    if best is not None and not best_value_ok:
        reasons.append(f"Best scenario '{best['name']}' has no value per share.")
    values_ok = [isinstance(r["value_per_share"], (int, float)) and not isinstance(r["value_per_share"], bool) for r in rows]
    central_above = values_ok[0] and central["value_per_share"] > price
    all_above = all(ok and r["value_per_share"] > price for ok, r in zip(values_ok, rows))
    if not central_above:
        reasons.append(f"Central scenario '{central['name']}' is not worth more than the price.")
    if best_ok and best_value_ok and central_above and not missing:
        verdict = "pass_flagged" if all_above else "pass"
        if all_above:
            reasons.append("Every scenario is worth more than the price; a downside case may be missing.")
    else:
        verdict = "fail"
    values = [r["value_per_share"] for r, ok in zip(rows, values_ok) if ok]
    if stress is not None and isinstance(stress["value_per_share"], (int, float)) and not isinstance(stress["value_per_share"], bool):
        values.append(stress["value_per_share"])
    return {"symbol": f["symbol"], "price": price, "verdict": verdict,
            "value_range": [min(values), max(values)] if values else None,
            "central": central, "worst": worst, "stress": stress,
            "best": best, "best_multiple": best_multiple,
            "checks": {"best_ok": best_ok, "central_above_price": central_above, "all_above_price": all_above},
            "reasons": reasons, "page": f.get("page"), "implied": (f.get("model") or {}).get("implied")}


def run_gate(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    profile = params.get("profile", "value")
    if profile not in growth.PROFILES:
        raise ValueError("profile must be 'value' or 'growth'")
    is_growth = profile == "growth"
    if is_growth:
        if "hurdle" in params or "floor" in params:
            raise ValueError("hurdle and floor apply to the value profile only; a growth run uses min_upside")
        min_upside = _num(params.get("min_upside", growth.MIN_UPSIDE_DEFAULT), "min_upside")
        if min_upside <= 1:
            raise ValueError("min_upside must be above 1")
        hurdle = floor = 0.0
    else:
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
        all_rows = [{"name": s.get("name"), "irr": irr_by.get(s.get("name")), "value_per_share": s.get("value_per_share"),
                     "_stress": s.get("stress") is True and i > 0} for i, s in enumerate(scen)]
        for r in all_rows:
            if not isinstance(r["irr"], (int, float)) or isinstance(r["irr"], bool) or not math.isfinite(r["irr"]):
                r["irr"] = None  # never echo NaN or infinity back out
        stress = next(({k: v for k, v in r.items() if k != "_stress"} for r in all_rows if r["_stress"]), None)
        rows = [{k: v for k, v in r.items() if k != "_stress"} for r in all_rows if not r["_stress"]]
        if is_growth:
            results.append(_growth_result(f, price, rows, stress, min_upside, (f["model"]).get("horizon")))
            continue
        reasons = []
        missing = [r["name"] for r in rows if r["irr"] is None]
        for name in missing:
            reasons.append(f"The return for scenario '{name}' could not be computed.")
        if stress is not None and stress["irr"] is not None and stress["irr"] < floor:
            verb = "loses" if stress["irr"] < 0 else "earns"
            reasons.append(f"Stress test '{stress['name']}' (several risks at once; not gated) {verb} {_pct(stress['irr'])} a year.")
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
        values = [r["value_per_share"] for r in rows + ([stress] if stress else [])
                  if isinstance(r["value_per_share"], (int, float)) and not isinstance(r["value_per_share"], bool)]
        results.append({"symbol": sym, "price": price, "verdict": verdict,
                        "value_range": [min(values), max(values)] if values else None,
                        "central": central, "worst": worst, "stress": stress,
                        "checks": {"worst_ok": worst_ok, "central_ok": central_ok, "all_above_price": all_above},
                        "reasons": reasons, "page": f.get("page"), "implied": (f.get("model") or {}).get("implied")})
    if is_growth:
        results.sort(key=lambda r: (ORDER[r["verdict"]], -(r["best"]["irr"] if r["best"] else -9)))
        counts = {k: sum(1 for r in results if r["verdict"] == k) for k in ORDER}
        return {"profile": "growth", "min_upside": min_upside, "results": results, "counts": counts}
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
