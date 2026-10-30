#!/usr/bin/env python3
"""Usage: imported by sleeves.py; no command line.

Sizing and weighting math for the core/satellite split: effective number of
picks, tracking error, proposed satellite size, pro-rata splits, confidence
decay and valuation-tilted pick targets. All functions are pure.

valuation_targets: score a_i = SHRINK_K x confidence x (expected_return - MARKET_RETURN), on an
absolute scale (not standardised across picks), so near-equal returns give near-size weights.
Raw weight = value x max(0, 1 + TILT_LAMBDA x a_i / TILT_SCALE), scaled to the target total.
A trusted pick (eligible, confidence above 0, with central_value) is overvalued when price is
above central_value x (1 + TRIM_MIN_GAP); its target is value x (1 - confidence x (1 -
central_value / price)). The pick cap limits new money only; excess left by capped picks goes to
uncapped, non-overvalued eligible picks with a_i above 0, else to any pick with room.

new_pick_multiplier: the same tilt for one pick not yet held, as a multiple of its size share:
the trim factor when overvalued, else max(0, 1 + TILT_LAMBDA x a / TILT_SCALE); 1 when it is not
eligible or its confidence is 0.
"""
from __future__ import annotations

import math
import statistics
import sys

DEFAULT_CEILING = 0.20
SIGMA_IDIO = 0.30
TE_BUDGET = 0.015
MIN_N_EFF = 15
SECTOR_HEAVY = 0.25
SECTOR_HAIRCUT = 0.75
PICK_CAP = 0.05
MARKET_RETURN = 0.07
SHRINK_K = 0.5
TILT_LAMBDA = 0.5
HALF_LIFE_DAYS = 182
TILT_SCALE = 0.10      # a score of 0.10 moves a pick's raw weight by TILT_LAMBDA
TRIM_MIN_GAP = 0.05    # overvalued only when price is above central_value x (1 + this)

_EPS = 1e-9


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def n_eff(values: dict[str, float]) -> float:
    total = sum(values.values())
    if not values or total <= 0:
        return 0
    return 1.0 / sum((v / total) ** 2 for v in values.values())


def tracking_error(w_sat: float, n: float) -> float:
    if n == 0:
        return 0
    return w_sat * SIGMA_IDIO / math.sqrt(n)


def proposed_size(ceiling: float, n: float, sector_heavy: bool) -> float:
    size = min(ceiling, TE_BUDGET * math.sqrt(n) / SIGMA_IDIO)
    if sector_heavy:
        size *= SECTOR_HAIRCUT
    return round(size, 4)


def size_split(current: dict[str, float], amount: float) -> dict[str, float]:
    if not current:
        return {}
    total = sum(current.values())
    if total <= 0:
        return {k: amount / len(current) for k in current}
    return {k: amount * v / total for k, v in current.items()}


def confidence(age_days: int, recheck_due: bool) -> float:
    if recheck_due:
        return 0.0
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def median_pick_value(current: dict[str, float]) -> float:
    return statistics.median(current.values()) if current else 0.0


def _fallback(picks: list[dict], target_total: float) -> dict:
    current = {p["symbol"]: float(p["value"]) for p in picks}
    extra = size_split(current, target_total - sum(current.values()))
    targets = {s: _r2(current[s] + extra[s]) for s in current}
    return {"targets": targets, "scores": {s: None for s in current}, "capped": [], "fallback": True}


def new_pick_multiplier(pick: dict) -> float:
    if not pick.get("eligible") or pick.get("confidence", 0) <= 0:
        return 1.0
    conf, central, price = pick["confidence"], pick["central_value"], pick["price"]
    if price > central * (1 + TRIM_MIN_GAP):
        return 1 - conf * (1 - central / price)
    return max(0.0, 1 + TILT_LAMBDA * SHRINK_K * conf * (pick["expected_return"] - MARKET_RETURN) / TILT_SCALE)


def valuation_targets(picks: list[dict], target_total: float, portfolio_total: float) -> dict:
    elig = [p for p in picks if p.get("eligible") and p.get("confidence", 0) > 0]
    if not elig:
        return _fallback(picks, target_total)

    a = {p["symbol"]: SHRINK_K * p["confidence"] * (p["expected_return"] - MARKET_RETURN) for p in elig}

    raw: dict[str, float] = {}
    fixed: dict[str, float] = {}
    for p in picks:
        s, value = p["symbol"], float(p["value"])
        # Only an eligible pick with confidence above 0 can count as overvalued and be
        # trimmed; a pick due for a recheck (confidence 0) keeps at least its value.
        trusted = p.get("eligible") and p.get("confidence", 0) > 0 and p.get("central_value") is not None
        if trusted and p["price"] > p["central_value"] * (1 + TRIM_MIN_GAP):
            fixed[s] = value * (1 - p["confidence"] * (1 - p["central_value"] / p["price"]))
        elif s in a:
            raw[s] = value * max(0.0, 1 + TILT_LAMBDA * a[s] / TILT_SCALE)
        else:
            raw[s] = value
    values = {p["symbol"]: float(p["value"]) for p in picks}
    cap = PICK_CAP * portfolio_total

    budget = target_total - sum(fixed.values())
    raw_sum = sum(raw.values())
    t = {s: (r * budget / raw_sum if raw_sum > 0 else 0.0) for s, r in raw.items()}
    # The cap limits new money only: a pick that is not overvalued never goes below its value.
    lo = {s: values[s] for s in raw}
    hi = {s: max(cap, lo[s]) for s in raw}
    capped: set[str] = {s for s in raw if lo[s] >= cap}

    for _ in range(100):
        for s in t:
            if t[s] < lo[s]:
                t[s] = lo[s]
            if t[s] > hi[s]:
                t[s] = hi[s]
                capped.add(s)
        excess = budget - sum(t.values())
        if abs(excess) < _EPS:
            break
        if excess > 0:
            room = [s for s in t if t[s] < cap - _EPS]
            pref = [s for s in room if a.get(s, 0) > 0]
        else:
            room = [s for s in t if t[s] > lo[s] + _EPS]
            pref = []
        recipients = pref or room
        weight = sum(raw[s] for s in recipients)
        if not recipients:
            break
        for s in recipients:
            share = raw[s] / weight if weight > 0 else 1 / len(recipients)
            t[s] += excess * share

    targets = {p["symbol"]: _r2(fixed.get(p["symbol"], t.get(p["symbol"], 0.0))) for p in picks}
    scores = {p["symbol"]: _r4(a.get(p["symbol"])) for p in picks}
    return {
        "targets": targets,
        "scores": scores,
        "capped": [p["symbol"] for p in picks if p["symbol"] in capped],
        "fallback": False,
    }


if __name__ == "__main__":
    print("weights.py is imported by sleeves.py and has no command line.", file=sys.stderr)
    sys.exit(2)
