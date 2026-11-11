#!/usr/bin/env python3
"""Usage: imported by sleeves.py; no command line.

Sizing and weighting math for the core/satellite split: effective number of
picks, tracking error, proposed satellite size, pro-rata splits, confidence
decay, strategy weights and rebalance targets. All functions are pure.

strategy_weights: raw weight per pick for the saved weighting strategy: equal 1.0, market_cap the
cap, valuation tilt_factor, size the pick's value. split_capped splits an amount by those weights;
a pick cannot take more than its room, the overflow goes to the others by weight, and money no
pick can take is left out of the result. All-zero weights split equally.

tilt_factor: one pick's valuation weight, with score a = SHRINK_K x confidence x (expected_return -
MARKET_RETURN) on an absolute scale (not standardised across picks), so near-equal returns give
near-equal weights. A pick is overvalued when price is above central_value x (1 + TRIM_MIN_GAP); its
factor is then the trim factor 1 - confidence x (1 - central_value / price), else max(0, 1 +
TILT_LAMBDA x a / TILT_SCALE); 1 when it is not eligible or its confidence is 0.

rebalance_targets(rows, raw, fixed, target_total, portfolio_total, closed): targets for a rebalance
of the picks. Symbols in ``fixed`` take the target given (held picks). Every other pick's target is
its ``raw`` weight's share of target_total less the fixed targets, so a second run on unchanged inputs
gives the same targets. A target above PICK_CAP x portfolio_total is held there, whatever the pick
holds now, and the excess goes to the other picks by ``raw``, never to a symbol in ``closed`` (the
picks overvalued under valuation); budget no pick can take is left unassigned. band(target) is how far above
target a pick must be before it is trimmed: max(BAND_REL x target, BAND_MIN).
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
BAND_REL = 0.25        # rebalance band: 25% of the target ...
BAND_MIN = 250.0       # ... or $250, whichever is larger

_EPS = 1e-9


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


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


def tilt_factor(pick: dict) -> float:
    if not pick.get("eligible") or pick.get("confidence", 0) <= 0:
        return 1.0
    conf, central, price = pick["confidence"], pick["central_value"], pick["price"]
    if price > central * (1 + TRIM_MIN_GAP):
        return 1 - conf * (1 - central / price)
    return max(0.0, 1 + TILT_LAMBDA * SHRINK_K * conf * (pick["expected_return"] - MARKET_RETURN) / TILT_SCALE)


def strategy_weights(rows: list[dict], strategy: str, market_caps: dict[str, float] | None = None) -> dict[str, float]:
    if strategy == "equal":
        return {r["symbol"]: 1.0 for r in rows}
    if strategy == "market_cap":
        caps = market_caps or {}
        return {r["symbol"]: float(caps.get(r["symbol"], 0.0)) for r in rows}
    if strategy == "valuation":
        return {r["symbol"]: tilt_factor(r) for r in rows}
    return {r["symbol"]: float(r["value"]) for r in rows}


def split_capped(raw: dict[str, float], amount: float, room: dict[str, float] | None = None) -> dict[str, float]:
    out = {s: 0.0 for s in raw}
    open_ = set(raw)
    left = amount
    for _ in range(len(raw) + 1):
        if not open_ or left <= _EPS:
            break
        total = sum(raw[s] for s in open_)
        share = {s: (raw[s] / total if total > 0 else 1.0 / len(open_)) * left for s in open_}
        full = {s for s in open_ if room is not None and s in room and out[s] + share[s] > room[s] + _EPS}
        if not full:
            for s in open_:
                out[s] += share[s]
            break
        for s in full:
            left -= max(0.0, room[s] - out[s])
            out[s] = max(0.0, room[s])
        open_ -= full
    return out


def band(target: float) -> float:
    return max(BAND_REL * target, BAND_MIN)


def rebalance_targets(rows: list[dict], raw: dict[str, float], fixed: dict[str, float], target_total: float,
                      portfolio_total: float, closed: frozenset[str] | set[str] = frozenset()) -> dict:
    factor = {s: w for s, w in raw.items() if s not in fixed}
    budget = target_total - sum(fixed.values())
    hi = PICK_CAP * portfolio_total
    t = {s: 0.0 for s in factor}
    capped: set[str] = set()
    left = max(0.0, budget)
    for round_ in range(100):
        # a closed pick takes its own share only, never another pick's overflow
        open_ = [s for s in factor if s not in capped and (round_ == 0 or s not in closed)]
        weight = sum(factor[s] for s in open_)
        if left <= _EPS or weight <= 0:
            break
        for s in open_:
            t[s] += left * factor[s] / weight
        left = 0.0
        for s in open_:
            if t[s] > hi - _EPS:
                left += t[s] - hi
                t[s] = hi
                capped.add(s)
    targets = {**{s: _r2(v) for s, v in t.items()}, **{s: _r2(v) for s, v in fixed.items()}}
    return {"targets": targets, "capped": [r["symbol"] for r in rows if r["symbol"] in capped]}


if __name__ == "__main__":
    print("weights.py is imported by sleeves.py and has no command line.", file=sys.stderr)
    sys.exit(2)
