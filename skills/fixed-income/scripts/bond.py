#!/usr/bin/env python3
"""Usage: bond.py < input.json — price one bond and report its risk measures.

Reads one JSON object from stdin and writes one JSON object to stdout.

Input JSON contract (stdin)::

    {
      "coupon_rate": 0.045,   # annual coupon as a decimal, required
      "years": 10,            # years to maturity, required
      "ytm": 0.0531,          # yield as a decimal — give this OR "price"
      "price": 95.0,          # clean price per "face" — give this OR "ytm"
      "freq": 2,              # coupons per year, default 2
      "face": 100.0           # face value, default 100
    }

Output JSON contract (stdout), for the input above with ``ytm`` given and
``price`` omitted — measured from this script's own output, not written by
hand::

    {
      "price": 93.7779, "ytm": 0.0531,
      "macaulay_duration": 8.0893, "modified_duration": 7.88, "convexity": 74.74,
      "cashflow_count": 20, "total_coupons": 45.0,
      "price_map": [{"ytm": 0.0281, "price": 114.6443},
                    {"ytm": 0.0306, "price": 112.3249}, ...],
      "assumptions": {"coupon_rate": 0.045, "years": 10.0, "freq": 2,
                      "face": 100.0, "solved_for": "price", "note": "..."}
    }

``price_map`` is 21 rows on a fixed grid: ten 25 bp steps below ``ytm``, ``ytm``
itself, ten above. The grid is built from ``ytm``, so a round number is on it
only by coincidence — here it starts at 0.0281, not 0.03.

``assumptions`` echoes the bond's own parameters, so a caller holding this
output already has ``coupon_rate`` and ``years``. They are one level down, and
``horizon.py`` reads the top level only, which is why piping this straight into
it exits 2: lift them out of ``assumptions`` rather than asking for them again.

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# The plugin's shared math package lives in lib/ at the plugin root.
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import bondmath  # noqa: E402


def analyse(params: dict) -> dict:
    """Price the bond and return its risk measures and a price/yield map."""
    coupon_rate = float(params["coupon_rate"])
    years = float(params["years"])
    freq = int(params.get("freq", 2))
    face = float(params.get("face", 100.0))

    has_price = params.get("price") is not None
    has_ytm = params.get("ytm") is not None
    if has_price == has_ytm:
        raise ValueError("give exactly one of 'price' or 'ytm'")

    if has_ytm:
        ytm = float(params["ytm"])
        price = bondmath.price_from_yield(coupon_rate, years, ytm, freq, face)
    else:
        price = float(params["price"])
        ytm = bondmath.yield_from_price(price, coupon_rate, years, freq, face)

    cf = bondmath.cashflows(coupon_rate, years, freq, face)
    mod = bondmath.modified_duration(coupon_rate, years, ytm, freq, face)
    cvx = bondmath.convexity(coupon_rate, years, ytm, freq, face)

    step = 0.0025
    lo = max(ytm - 10 * step, 0.0001)
    price_map = []
    for i in range(21):
        y = lo + i * step
        price_map.append(
            {
                "ytm": round(y, 6),
                "price": round(bondmath.price_from_yield(coupon_rate, years, y, freq, face), 4),
            }
        )

    return {
        "price": round(price, 4),
        "ytm": round(ytm, 6),
        "macaulay_duration": round(
            bondmath.macaulay_duration(coupon_rate, years, ytm, freq, face), 4
        ),
        "modified_duration": round(mod, 4),
        "convexity": round(cvx, 2),
        "cashflow_count": len(cf),
        "total_coupons": round(sum(a for _, a in cf) - face, 4),
        "price_map": price_map,
        "assumptions": {
            "coupon_rate": coupon_rate,
            "years": years,
            "freq": freq,
            "face": face,
            "solved_for": "price" if has_ytm else "ytm",
            "note": (
                "Flat-yield pricing. A real bond also carries a credit spread and, "
                "if callable, an option cost."
            ),
        },
    }


def main() -> None:
    """Read JSON params from stdin, write the bond analysis (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = analyse(json.loads(raw))
        # ``allow_nan=False`` because a finite input can still compute a non-finite
        # figure: a coupon and face of 1e308 price to Infinity, and the durations
        # that divide by that price to NaN. Python emits both as bare tokens that
        # strict parsers (jq, JSON.parse) reject, so the script would exit 0 having
        # printed something no caller can read. Rejecting it here keeps the one
        # promise every script in this plugin makes -- JSON on stdout, or exit 2
        # with an error that says why.
        rendered = json.dumps(result, allow_nan=False)
    except (
        ValueError,
        TypeError,
        KeyError,
        ZeroDivisionError,
        OverflowError,
        json.JSONDecodeError,
    ) as exc:
        # OverflowError joins the list for the same reason it does in horizon.py:
        # a yield of 1e308 overflows a discount factor on a one-year bond, and an
        # uncaught one exits 1 with an empty stdout, which the docstring above
        # promises never happens.
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(rendered)


if __name__ == "__main__":
    main()
