#!/usr/bin/env python3
"""Usage: horizon.py < input.json — what you earn if you hold to your horizon.

Reads one JSON object from stdin and writes one JSON object to stdout: the
annualised return locked in over a chosen holding period, re-priced across
+/-200 bp of yield, and whether that horizon is the one that immunises the
position against the move.

Two input shapes are accepted, because the question is asked both about a
single bond and about a bond fund.

*Bond-like* — decimals at the top level, the shape ``bond.py`` reads on stdin::

    {"coupon_rate": 0.0379, "years": 8.2, "ytm": 0.0531, "horizon_years": 6.91}

*Fund-like* — ``fund.py``'s own output, percentages under ``characteristics``::

    {"characteristics": {"coupon_pct": 3.785, "ytm_pct": 5.31,
                         "wal_years": 8.27, "duration_years": 5.748},
     "horizon_years": 6.91, "circularity_note": "..."}

``horizon_years`` is required in both shapes. A key that is absent, or present
as ``null``, counts as absent: ``fund.py`` emits ``null`` for a figure the page
did not carry, and a missing figure is never modelled as a zero. A payload that
is recognisably ``bond.py``'s output — it has ``ytm`` and ``macaulay_duration``
but not ``coupon_rate``/``years`` at the top level — exits 2 naming the two
parameters to pass alongside it. ``bond.py`` does echo them, under
``assumptions``; ``resolve_inputs`` reads the top level only, so they have to be
lifted out of that block rather than asked for again.

Output JSON contract (stdout), for the bond example above — measured from this
script's own output, not written by hand::

    {
      "horizon_years": 6.91,
      "duration_years": 6.9085,                 # MACAULAY — the immunising horizon
      "modified_duration_years": 6.7298,        # price sensitivity per unit yield
      "matched": true,                          # 6.91 is within 20% of 6.9085
      "locked_in_return_pct": 5.3805,
      "scenarios": [{"delta_yield_bp": -200, "immediate_price_change_pct": 14.5822,
                     "total_return_pct": 43.7594, "annualised_pct": 5.3932}, ...],
      "spread_pct": 0.014,                      # the whole +/-200 bp range, in points
      "value_paths": [{"delta_yield_bp": -100, "points": [{"years": 0, "value": 1.070024},
                      {"years": 0.5, ...}, ..., {"years": 6.91, ...}]}, ...],
      "mismatch_cost_note": "...",
      "assumptions": {...},
      "circularity_note": "..."                 # passed through when the input has one
    }

Note the sign: at a matched horizon the whole +/-200 bp range spans 0.014
percentage points, and every scenario is a gain, because that is what immunity
means. ``immediate_price_change_pct`` is the other half of the same picture: what the
move does to the price the day it happens. ``value_paths`` draws the two together for
moves of -100, 0 and +100 bp — what 1 invested today is worth at each coupon date up
to the horizon — so a reader can see the early loss earned back. The fund shape
adds one key, ``published_effective_duration_years``, carrying the input's
``characteristics.duration_years`` through unchanged; a bond-like payload carries
no such figure, so the key is absent rather than zero.

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
# The plugin's shared math package lives in lib/ at the plugin root.
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import bondmath  # noqa: E402

# The parallel shocks the return is re-priced across, in basis points.
SHOCK_BP = (-200, -100, 0, 100, 200)
# The value paths draw only the one-point moves: three lines a reader can tell apart.
PATH_SHOCK_BP = (-100, 0, 100)

# A horizon counts as matched when it is within this share of the Macaulay
# duration — the immunisation window, not an equality test.
MATCH_TOLERANCE = 0.20

FREQ = 2

# A RESOURCE bound, not a domain rule: the most coupon periods this script will
# price. A million payments is 500,000 years of semi-annual coupons, which no
# instrument approaches, so nothing real is refused by it — a 100-year bond is
# 200 periods. It exists because ``bondmath.cashflows`` materialises every period
# as a list entry before anything is discounted, so ``years * freq`` is allocated
# up front and a large enough figure does not reject: the process allocates until
# it is killed. Measured 2026-09-18 against the previous commit: years=1e8 and
# freq=1e9 each ran to a 10 s timeout with no exit code, no JSON and no stdout —
# a caller waits forever instead of reading an error, which breaks the one
# contract every script here has. Along ``years`` the bound costs nothing: a
# maturity long enough to exceed it already overflowed (measured at freq=2:
# 25,000 years is 50,000 periods and exits 2 with "Result too large"), so there
# the guard only replaces a hang with the rejection those payloads already got.
# Along ``freq`` that does NOT hold, because a larger freq raises the period
# count while shrinking ``ytm / freq``, so nothing overflows: years=1000 with
# freq=1001 is 1,001,000 periods and returned a figure before this bound (2.1 s
# and 178 MB to produce it) that it now refuses. That one payload shape is a
# deliberate behaviour change rather than a preserved rejection, and it is
# pinned in the tests.
MAX_PERIODS = 1_000_000

BOND_KEYS = ("coupon_rate", "years", "ytm")
FUND_KEYS = ("coupon_pct", "ytm_pct", "wal_years")

# Present in bond.py's output but never in its input: the tell that a caller has
# piped a result back in and still needs to supply the bond's own parameters.
BOND_OUTPUT_MARKERS = ("macaulay_duration", "price_map")

# Every disclosure string is a module-level constant emitted from that constant,
# never rebuilt at the dict site, so a test can assert the emitted text *is* the
# constant — and a failure names the constant that stopped being emitted. What
# identity cannot do is see an edit to the constant itself, because the
# expectation moves with it; and an anchor on a phrase cannot see a sentence
# added beside intact wording. So the tests also carry these four strings word
# for word, keyed by output path, and the payload has to equal them. The fund
# path's dynamic sentences are built in ``assumptions``.
_APPROXIMATION_NOTE = (
    "The fund path models the whole fund as ONE bond: the average coupon as the "
    "coupon rate, the weighted average life as the maturity, and the published "
    "yield to maturity as the yield. That is an approximation — a fund is not a "
    "bond and a weighted average life is not a maturity, so the cash-flow timing "
    "here stands in for a portfolio that actually rolls."
)

_DURATION_MEANINGS_NOTE = (
    "Three durations appear in this output and only the first is the "
    "hold-to-horizon answer. duration_years is the MACAULAY duration of the cash "
    "flows above: the horizon at which the price loss from a rate move and the "
    "higher reinvestment rate cancel, so it is the figure the matched flag is "
    "measured against. modified_duration_years is price sensitivity per unit of "
    "yield — a first-order price change, not a holding-period return. A fund's "
    "published EFFECTIVE duration (reported as published_effective_duration_years "
    "when the input carries one) describes its actual portfolio and is not "
    "expected to equal the Macaulay figure."
)

_HEADLINE_NOTE = (
    "The locked-in return is implied by today's price and is not a forecast: at a "
    "matched horizon it reproduces the market's own yield because the price "
    "already reflects it. The scenarios show how far the outcome moves if rates "
    "CHANGE by up to 200 basis points — a sensitivity, not a prediction that they "
    "will. Nothing here is a fair value, and nothing here is a view on whether the "
    "bond or the fund is cheap or expensive."
)

_REINVESTMENT_NOTE = (
    "The shock lands immediately, is parallel across the curve, and every coupon "
    "received after it is reinvested at the shocked yield; whatever is left is "
    "sold at the horizon at the shocked price. No default, no credit migration, "
    "no change in the coupon."
)


class InputError(ValueError):
    """The payload cannot be read: a load-bearing figure is absent or unusable."""


def horizon_return(
    coupon_rate: float,
    years: float,
    ytm: float,
    horizon_years: float,
    delta_yield: float,
    freq: int = 2,
    face: float = 100.0,
) -> float:
    """Annualised total return over ``horizon_years`` after a parallel shock.

    The shock lands immediately; coupons received afterwards are reinvested at
    the new yield. Near the duration point the price loss and the higher
    reinvestment rate offset, which is why a matched horizon is nearly immune
    to rate moves.
    """
    if horizon_years <= 0:
        raise ValueError("horizon_years must be positive")
    growth = value_at(coupon_rate, years, ytm, horizon_years, delta_yield, freq, face)
    return growth ** (1.0 / horizon_years) - 1.0


def value_at(
    coupon_rate: float,
    years: float,
    ytm: float,
    at_years: float,
    delta_yield: float,
    freq: int = 2,
    face: float = 100.0,
) -> float:
    """What 1 invested today is worth ``at_years`` from now, after a parallel shock today.

    At 0 it is the price change the shock causes at once; at the horizon it is the
    growth ``horizon_return`` annualises. Every cash flow — a coupon already
    received and reinvested, or one still to come and discounted — is valued at the
    same shocked rate, so the sum factors: the repriced bond, compounded forward.
    Stub periods need no special case, which is why a horizon inside the final
    coupon period, or past maturity, works.
    """
    start_price = bondmath.price_from_yield(coupon_rate, years, ytm, freq, face)
    moved_price = bondmath.price_from_yield(coupon_rate, years, ytm + delta_yield, freq, face)
    per = (ytm + delta_yield) / freq
    return moved_price / start_price * (1.0 + per) ** (at_years * freq)


# A resource bound on the value paths, not a domain rule: a line needs no more
# points than this to be drawn, and an absurd horizon must not allocate one dict
# per coupon date.
MAX_PATH_POINTS = 120


def value_path(
    coupon_rate: float,
    years: float,
    ytm: float,
    horizon_years: float,
    delta_yield: float,
    freq: int = 2,
) -> list[dict[str, float]]:
    """``value_at`` at every coupon date up to the horizon, plus the horizon itself.

    Past ``MAX_PATH_POINTS`` coupon dates the path steps every few coupons instead.
    """
    periods = int(math.floor(horizon_years * freq + 1e-9))
    stride = max(1, math.ceil(periods / MAX_PATH_POINTS))
    steps = [k / freq for k in range(0, periods + 1, stride)]
    if steps[-1] < horizon_years - 1e-9:
        steps.append(horizon_years)
    return [
        {
            "years": 0 if t == 0 else round(t, 4),
            "value": round(value_at(coupon_rate, years, ytm, t, delta_yield, freq), 6),
        }
        for t in steps
    ]


def _present(mapping: Any, key: str) -> bool:
    """True only when ``key`` exists and is not ``None`` — null counts as absent."""
    return isinstance(mapping, dict) and mapping.get(key) is not None


def _json_kind(value: Any) -> str:
    """The JSON kind of a parsed value, for an error that says what arrived."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _number(mapping: dict[str, Any], key: str, label: str) -> float:
    """``mapping[key]`` as a finite float, or an ``InputError`` naming ``label``."""
    try:
        value = float(mapping[key])
    except (TypeError, ValueError) as exc:
        raise InputError(f"{label} must be a number, got {mapping[key]!r}") from exc
    if not math.isfinite(value):
        # ``json`` parses bare NaN/Infinity by default and ``json.dumps``
        # re-emits them, which is not JSON: a strict parser rejects the whole
        # object, so a non-finite input is invalid input, not a number.
        raise InputError(f"{label} must be a finite number, got {mapping[key]!r}")
    return value


def resolve_inputs(payload: Any) -> dict[str, Any]:
    """Read either input shape into one bond's parameters.

    Raises ``InputError`` naming the figures that are missing — never a
    ``KeyError``, and never a zero standing in for a figure that is not there.
    """
    if not isinstance(payload, dict):
        # Valid JSON, but not an object: ``payload.get`` would raise
        # ``AttributeError`` and leave stdout empty, breaking the contract that
        # every exit is JSON. Rejected here, where the rest of the input is
        # validated, rather than by widening ``main``'s handler — a handler for
        # ``AttributeError`` would also swallow a real attribute bug.
        raise InputError(
            f"input must be a JSON object, got a JSON {_json_kind(payload)}: give either "
            "coupon_rate, years and ytm as decimals, or a fund payload carrying "
            "characteristics.coupon_pct, characteristics.ytm_pct and characteristics.wal_years "
            "as percentages"
        )

    if all(_present(payload, key) for key in BOND_KEYS):
        # ``as_given`` keeps each figure under the name the caller used and at
        # the scale they wrote it, for messages that have to name the field to
        # go and fix: a fund's ytm_pct is 5.31 there and 0.0531 in the model.
        figures = {
            "coupon_rate": _number(payload, "coupon_rate", "coupon_rate"),
            "years": _number(payload, "years", "years"),
            "ytm": _number(payload, "ytm", "ytm"),
        }
        return {
            "shape": "bond",
            "coupon_rate": figures["coupon_rate"],
            "years": figures["years"],
            "ytm": figures["ytm"],
            "published_effective_duration_years": None,
            "as_given": figures,
        }

    characteristics = payload.get("characteristics")
    if isinstance(characteristics, dict) and any(key in characteristics for key in FUND_KEYS):
        missing = [key for key in FUND_KEYS if not _present(characteristics, key)]
        if missing:
            raise InputError(
                "fund payload is missing "
                + ", ".join(f"characteristics.{key}" for key in missing)
                + ": a figure the page did not carry cannot be modelled"
            )
        figures = {
            "characteristics.coupon_pct": _number(
                characteristics, "coupon_pct", "characteristics.coupon_pct"
            ),
            "characteristics.wal_years": _number(
                characteristics, "wal_years", "characteristics.wal_years"
            ),
            "characteristics.ytm_pct": _number(
                characteristics, "ytm_pct", "characteristics.ytm_pct"
            ),
        }
        return {
            "shape": "fund",
            "coupon_rate": figures["characteristics.coupon_pct"] / 100.0,
            "years": figures["characteristics.wal_years"],
            "ytm": figures["characteristics.ytm_pct"] / 100.0,
            "as_given": figures,
            "published_effective_duration_years": (
                _number(characteristics, "duration_years", "characteristics.duration_years")
                if _present(characteristics, "duration_years")
                else None
            ),
        }

    if any(key in payload for key in BOND_KEYS):
        missing = [key for key in BOND_KEYS if not _present(payload, key)]
        if _present(payload, "ytm") and any(marker in payload for marker in BOND_OUTPUT_MARKERS):
            raise InputError(
                "input looks like bond.py's output, which echoes the bond's own parameters "
                "under assumptions rather than at the top level this script reads: pass "
                + ", ".join(missing)
                + " (as decimals) alongside it, lifting them from that assumptions block"
            )
        raise InputError("bond-like input is missing " + ", ".join(missing))

    raise InputError(
        "unrecognised input: give either coupon_rate, years and ytm as decimals, or a "
        "fund payload carrying characteristics.coupon_pct, characteristics.ytm_pct and "
        "characteristics.wal_years as percentages"
    )


def read_horizon(payload: dict[str, Any]) -> float:
    """The holding period in years — required, and strictly positive."""
    if not _present(payload, "horizon_years"):
        raise InputError("horizon_years is required: the holding period, in years")
    horizon_years = _number(payload, "horizon_years", "horizon_years")
    if horizon_years <= 0:
        raise InputError(f"horizon_years must be positive, got {horizon_years:g}")
    return horizon_years


def read_freq(payload: dict[str, Any]) -> int:
    """Coupons per year, defaulting to semi-annual as everywhere else here."""
    if not _present(payload, "freq"):
        return FREQ
    freq = int(_number(payload, "freq", "freq"))
    if freq < 1:
        raise InputError(f"freq must be at least 1, got {freq}")
    return freq


def check_period_count(years: float, freq: int, years_label: str) -> None:
    """Refuse a coupon count that cannot be priced, before anything builds it.

    ``years_label`` is the field as the caller wrote it — ``years`` for a bond
    payload, ``characteristics.wal_years`` for a fund one — so the message names
    something they can go and edit.
    """
    periods = years * freq
    if periods > MAX_PERIODS:
        raise InputError(
            f"{years_label} x freq is {periods:g} coupon periods, above the "
            f"{MAX_PERIODS:,} this script will price: check {years_label} "
            f"({years:g}) and freq ({freq})"
        )


def mismatch_cost_note(horizon_years: float, macaulay: float, spread_pct: float) -> str:
    """What the distance between the caller's horizon and Macaulay costs, in bp."""
    gap = horizon_years - macaulay
    if abs(gap) <= MATCH_TOLERANCE * macaulay:
        return (
            f"The horizon of {horizon_years:g} years is within "
            f"{MATCH_TOLERANCE:.0%} of the Macaulay duration ({macaulay:.2f} years), so "
            f"the return is largely locked in: a parallel move of +/-200 bp moves the "
            f"annualised outcome by only {spread_pct:.2f} percentage points."
        )
    return (
        f"The horizon of {horizon_years:g} years is {abs(gap):.2f} years "
        f"{'past' if gap > 0 else 'short of'} the Macaulay duration "
        f"({macaulay:.2f} years), so the return is not locked in: a parallel move of "
        f"+/-200 bp moves the annualised outcome by {spread_pct:.2f} percentage points, "
        f"and that spread is the cost of the mismatch."
    )


def assumptions(
    spec: dict[str, Any],
    horizon_years: float,
    freq: int,
    macaulay: float,
    published: float | None,
) -> dict[str, Any]:
    """What a reader has to know to use the headline correctly."""
    out: dict[str, Any] = {
        "input_shape": spec["shape"],
        "frequency": freq,
        "horizon_years": horizon_years,
        "shock_grid_bp": list(SHOCK_BP),
        "match_tolerance": MATCH_TOLERANCE,
        "headline_is_not_a_forecast": _HEADLINE_NOTE,
        "duration_meanings": _DURATION_MEANINGS_NOTE,
        "reinvestment": _REINVESTMENT_NOTE,
    }
    if spec["shape"] == "fund":
        out["single_bond_approximation"] = _APPROXIMATION_NOTE
    if published is not None:
        gap_pct = (macaulay - published) / published * 100.0
        out["published_effective_duration_meaning"] = (
            f"The input's characteristics.duration_years is the fund's published "
            f"effective duration ({published:g} years) and is passed through unchanged "
            f"as published_effective_duration_years. This script's duration_years is the "
            f"Macaulay duration of the single-bond approximation above "
            f"({macaulay:.2f} years). They are different quantities and are not expected "
            f"to match: here they differ by {gap_pct:.0f}% by design."
        )
    return out


def analyse(payload: Any) -> dict[str, Any]:
    """Answer the hold-to-horizon question for either input shape."""
    spec = resolve_inputs(payload)
    horizon_years = read_horizon(payload)
    freq = read_freq(payload)

    coupon_rate = spec["coupon_rate"]
    years = spec["years"]
    ytm = spec["ytm"]

    check_period_count(
        years, freq, "characteristics.wal_years" if spec["shape"] == "fund" else "years"
    )

    try:
        macaulay = bondmath.macaulay_duration(coupon_rate, years, ytm, freq)
        modified = bondmath.modified_duration(coupon_rate, years, ytm, freq)
        scenarios = []
        for shock_bp in SHOCK_BP:
            annualised = horizon_return(
                coupon_rate, years, ytm, horizon_years, shock_bp / 10000.0, freq
            )
            immediate = value_at(coupon_rate, years, ytm, 0.0, shock_bp / 10000.0, freq) - 1.0
            scenarios.append(
                {
                    "delta_yield_bp": shock_bp,
                    "immediate_price_change_pct": round(immediate * 100.0, 4),
                    "total_return_pct": round(
                        ((1.0 + annualised) ** horizon_years - 1.0) * 100.0, 4
                    ),
                    "annualised_pct": round(annualised * 100.0, 4),
                }
            )
        value_paths = [
            {
                "delta_yield_bp": shock_bp,
                "points": value_path(
                    coupon_rate, years, ytm, horizon_years, shock_bp / 10000.0, freq
                ),
            }
            for shock_bp in PATH_SHOCK_BP
        ]
    except OverflowError as exc:
        # Every figure here is a finite JSON number, but a coupon or a yield large
        # enough overflows a discount factor, and OverflowError says only
        # "(34, 'Result too large')" — naming neither the field nor the figure, and
        # raised deep in the arithmetic where no field is in scope. So the payload's
        # own figures are named instead, as the caller wrote them. This is N5 only;
        # a coupon count too large to build is refused before this, by name, in
        # check_period_count.
        figures = ", ".join(f"{name}={value:g}" for name, value in spec["as_given"].items())
        raise InputError(
            f"no finite answer exists for these figures: {figures}, "
            f"horizon_years={horizon_years:g}, freq={freq} ({exc})"
        ) from exc

    annualised_pcts = [row["annualised_pct"] for row in scenarios]
    spread_pct = round(max(annualised_pcts) - min(annualised_pcts), 4)
    # The middle scenario is the one the caller actually earns as things stand:
    # the +/- rows are the same return under a rate move that has not happened.
    locked_in = next(row["annualised_pct"] for row in scenarios if row["delta_yield_bp"] == 0)
    matched = abs(horizon_years - macaulay) <= MATCH_TOLERANCE * macaulay

    published = spec["published_effective_duration_years"]
    durations: dict[str, Any] = {
        "duration_years": round(macaulay, 4),
        "modified_duration_years": round(modified, 4),
    }
    if published is not None:
        durations["published_effective_duration_years"] = round(published, 4)

    result: dict[str, Any] = {
        "horizon_years": horizon_years,
        **durations,
        "matched": matched,
        "locked_in_return_pct": locked_in,
        "scenarios": scenarios,
        "spread_pct": spread_pct,
        "value_paths": value_paths,
        "mismatch_cost_note": mismatch_cost_note(horizon_years, macaulay, spread_pct),
        "assumptions": assumptions(spec, horizon_years, freq, macaulay, published),
    }

    # fund.py's own note, passed through unchanged so the page keeps one voice.
    # A plain bond-like payload has none, and one is not invented for it.
    note = payload.get("circularity_note")
    if isinstance(note, str) and note:
        result["circularity_note"] = note
    return result


def _render(result: dict[str, Any]) -> str:
    """``json.dumps`` that refuses to emit a bare NaN/Infinity token.

    ``allow_nan=False`` because a finite input can still compute a non-finite
    ratio, and a bare ``NaN`` is not JSON: a strict parser rejects the whole
    object. The ``ValueError`` it raises is caught by ``main`` and reported as
    invalid input, so this is a rejection and not a crash.
    """
    try:
        return json.dumps(result, indent=2, allow_nan=False)
    except ValueError as exc:
        raise InputError(f"no finite answer exists for this input: {exc}") from exc


def main() -> None:
    """Read JSON from stdin, write the horizon analysis (or the error) to stdout."""
    raw = sys.stdin.read()
    try:
        rendered = _render(analyse(json.loads(raw)))
    except (
        ValueError,
        TypeError,
        KeyError,
        ZeroDivisionError,
        OverflowError,
        json.JSONDecodeError,
    ) as exc:
        # OverflowError is here for the absurd-but-finite payload (a maturity or
        # a horizon of 1e308) that overflows the compounding: the arithmetic has
        # no source-side bound to check it against, but it is still invalid
        # input, and it must exit 2 with JSON like every other rejection.
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(rendered)


if __name__ == "__main__":
    main()
