#!/usr/bin/env python3
"""Shared helpers for the deep picker's growth mode: the run's profile and the growth thresholds.

Mostly a module: picker scripts load it by path or put its folder on ``sys.path``. Stdlib plus
``second_opinion.errors``; importing it has no side effects. Run as ``growth.py DIR`` it prints
the run's profile as ``{"profile": ...}`` (exit 2 on an unknown one). stdin is unused.

The profile lives in ``DIR/run.json`` as ``{"profile": "value" | "growth"}``, written by
``pick_prep.py``. A run folder without that file is a ``value`` run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion.errors import InvalidInput  # noqa: E402

PROFILES = ("value", "growth")
MIN_UPSIDE_DEFAULT = 2.0  # best-case multiple of today's price a growth pick must be able to reach
RUN_FILE = "run.json"


def run_profile(run_dir: Path) -> str:
    """The run's profile: ``value`` when ``run.json`` is missing; InvalidInput when it names another."""
    path = Path(run_dir) / RUN_FILE
    if not path.is_file():
        return "value"
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise InvalidInput(f"{path} is not valid JSON: {exc}") from exc
    profile = data.get("profile") if isinstance(data, dict) else None
    if profile not in PROFILES:
        raise InvalidInput(f"{path}: profile must be one of {', '.join(PROFILES)}, got {profile!r}")
    return profile


def write_profile(run_dir: Path, profile: str) -> Path:
    """Write ``run.json`` (replacing any earlier one) and return its path."""
    if profile not in PROFILES:
        raise InvalidInput(f"profile must be one of {', '.join(PROFILES)}, got {profile!r}")
    path = Path(run_dir) / RUN_FILE
    path.write_text(json.dumps({"profile": profile}) + "\n")
    return path


def best_irr_needed(min_upside: float, horizon: int) -> float:
    """The yearly return that reaches ``min_upside`` times today's price in ``horizon`` years."""
    if min_upside <= 1 or horizon < 1:
        raise ValueError("min_upside must be above 1 and horizon at least 1 year")
    return min_upside ** (1 / horizon) - 1


def upside_hint(quick: dict, price: float | None, fcf_latest: float | None) -> int | None:
    """A starting point for a growth card's ``upside`` score (1-5) from the quick value's bull and base.

    5: bull at least 2x the price and base above it; 4: bull at least 1.5x and base above the
    price; 3: bull at least 1.5x; 2: bull above the price; else 1. None when the quick value has
    no ``basis`` (no DCF), bull or price is missing, or the latest annual free cash flow is not
    positive (``fcf_latest`` None means the pack had none: not held against the name).
    """
    def num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None

    bull, base, px = num(quick.get("bull")), num(quick.get("base")), num(price)
    fcf = num(fcf_latest)
    if not quick.get("basis") or bull is None or px is None or px <= 0 or (fcf is not None and fcf <= 0):
        return None
    above = base is not None and base > px
    if bull / px >= 2 and above:
        return 5
    if bull / px >= 1.5 and above:
        return 4
    if bull / px >= 1.5:
        return 3
    return 2 if bull > px else 1


YARDSTICK_YEARS = 10           # years of explicit growth, fading linearly to TERMINAL_GROWTH
TERMINAL_GROWTH = 0.03
PRICE_RATE = 0.10              # the rate "the price implies" uses (as screen.py's gap)
YARDSTICK_TAX = 0.21           # turns an operating margin into an after-tax cash margin
CASH_OUTRUNS_PROFIT = 0.15     # a free-cash-flow margin this far above the operating margin is not used (screen_math's flag)
GROWTH_SEARCH = (-0.30, 1.50)  # the starting growth rates the solver will consider


def _yardstick_value(revenue: float, margin: float, g0: float, rate: float) -> float:
    """Enterprise value of revenue growing at ``g0`` in year 1, fading linearly to TERMINAL_GROWTH in
    year YARDSTICK_YEARS, earning a constant cash ``margin``, with a Gordon tail, discounted at ``rate``."""
    value, rev = 0.0, revenue
    for t in range(1, YARDSTICK_YEARS + 1):
        g = g0 + (TERMINAL_GROWTH - g0) * (t - 1) / (YARDSTICK_YEARS - 1)
        rev *= 1 + g
        value += rev * margin / (1 + rate) ** t
    tail = rev * (1 + TERMINAL_GROWTH) * margin / (rate - TERMINAL_GROWTH)
    return value + tail / (1 + rate) ** YARDSTICK_YEARS


def _solve_growth(revenue: float, margin: float, target: float, rate: float) -> float | None:
    """The starting growth at which ``_yardstick_value`` equals ``target`` (bisection), or None outside GROWTH_SEARCH."""
    lo, hi = GROWTH_SEARCH
    if not (_yardstick_value(revenue, margin, lo, rate) <= target <= _yardstick_value(revenue, margin, hi, rate)):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if _yardstick_value(revenue, margin, mid, rate) < target:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def yardstick(market_cap: float | None, net_debt: float | None, revenue: float | None, operating_margin: float | None,
              net_margin: float | None, fcf_margin: float | None, recent_growth: float | None,
              consensus_growth: float | None = None, min_upside: float = MIN_UPSIDE_DEFAULT, horizon: int = 5) -> dict:
    """What the price asks of a growth company, against what it has done (pure arithmetic, no forecast).

    ``revenue`` is trailing-twelve-month revenue. ``margin`` is today's cash margin, held flat: the
    larger of the after-tax operating margin (``operating_margin`` x (1 - 21%); ``net_margin`` in its
    place when there is no operating margin) and ``fcf_margin``. The free-cash-flow margin is left out,
    with the flag CASH_OUTRUNS_PROFIT, when it runs more than 15 points above the operating (else net)
    margin: customer float or loan funding counted as cash, as at a lender or a marketplace. Revenue
    grows at a starting rate that fades linearly to 3% over 10 years, with a Gordon tail.

    - ``implied_growth``: the starting growth at which today's enterprise value is worth it at 10%
      (``PRICE_RATE``): what the price already assumes.
    - ``growth_for_upside``: the starting growth at which it is worth it at the yearly return that
      reaches ``min_upside`` times the price over ``horizon`` years (14.9% for 2x in 5): what the growth
      gate's best case has to show, at today's margins.
    - ``recent_growth``: trailing-twelve-month revenue growth, as given; ``consensus_growth``: the
      analysts' revenue growth for the next fiscal year, as given (null when there is none).
    - ``benchmark``: the growth the hint measures against: consensus when given, else recent growth,
      and never more than recent growth (a one-year figure, so the fade over ten years asks more).
    - ``hint`` (1-5): growth_for_upside against the benchmark: 5 at most 0.6x, 4 at most 0.8x, 3 at
      most 1x, 2 at most 1.3x, else 1 (a benchmark of zero or less: 1 when growth is needed, else 3).
      Null when an input is missing, the margin is not positive, or a growth is outside -30%..+150%.

    Margins that expand from here are not in it: a company earning little today on revenue that will
    scale reads as dear, and the quick reader judges that from the filings.
    """
    out: dict = {"margin": None, "enterprise_value": None, "implied_growth": None, "growth_for_upside": None,
                 "recent_growth": recent_growth, "consensus_growth": consensus_growth, "benchmark": None,
                 "rate_for_upside": None, "hint": None, "why": None, "flags": []}

    def num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None

    mcap, rev, recent = num(market_cap), num(revenue), num(recent_growth)
    if mcap is None or rev is None or recent is None or rev <= 0 or mcap <= 0:
        out["why"] = "market value, trailing revenue or recent growth missing"
        return out
    op, ni, fcf = num(operating_margin), num(net_margin), num(fcf_margin)
    profit = op * (1 - YARDSTICK_TAX) if op is not None else ni
    check = op if op is not None else ni
    margins = [m for m in (profit,) if m is not None]
    if fcf is not None:
        if check is not None and fcf > check + CASH_OUTRUNS_PROFIT:
            out["flags"].append("CASH_OUTRUNS_PROFIT")
        else:
            margins.append(fcf)
    if not margins or max(margins) <= 0:
        out["why"] = "no positive cash margin today, so the price cannot be read from today's economics"
        return out
    margin = max(margins)
    ev = mcap + (num(net_debt) or 0.0)
    rate_up = best_irr_needed(min_upside, horizon)
    out.update(margin=round(margin, 4), enterprise_value=ev, rate_for_upside=round(rate_up, 4))
    if ev <= 0:
        out.update(why="enterprise value is not positive (net cash above the market value)", hint=5)
        return out
    out["implied_growth"] = _solve_growth(rev, margin, ev, PRICE_RATE)
    need = _solve_growth(rev, margin, ev, rate_up)
    out["growth_for_upside"] = need
    if need is None:
        out["why"] = "the growth the price needs is outside -30%..+150% a year at today's margin"
        return out
    cons = num(consensus_growth)
    have = min(cons, recent) if cons is not None else recent
    out["benchmark"] = round(have, 4)
    if have <= 0:
        hint = 1 if need > 0 else 3
    else:
        ratio = need / have
        hint = 5 if ratio <= 0.6 else 4 if ratio <= 0.8 else 3 if ratio <= 1 else 2 if ratio <= 1.3 else 1
    out["hint"] = hint
    why = f"at today's {margin:.0%} cash margin, {min_upside:g}x in {horizon} years needs revenue growth starting near {need:.0%} a year (fading to 3%)"
    if out["implied_growth"] is not None:
        why += f"; the price alone assumes {out['implied_growth']:.0%}"
    why += f"; revenue grew {recent:.0%} over the last twelve months"
    if cons is not None:
        why += f" and analysts expect {cons:.0%} next year"
    out["why"] = why
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: growth.py DIR", file=sys.stderr)
        return 2
    try:
        print(json.dumps({"profile": run_profile(Path(args[0]))}))
    except InvalidInput as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
