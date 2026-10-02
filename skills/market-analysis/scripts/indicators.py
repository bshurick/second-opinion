#!/usr/bin/env python3
"""Usage: indicators.py — where today's market-wide indicators sit against their own history.

`indices.py` reports levels and ranks only the VIX, against a trailing year.
`rates.py` in the fixed-income skill ranks four credit and inflation series. This
script covers what neither does: the yield curve and financial conditions, each
ranked against its whole history rather than a recent window.

Takes no arguments and reads nothing from stdin. Writes one JSON object::

    {
      "as_of": "2026-09-24",
      "indicators": {
        "curve_10y_3m": {
          "label": "10-year minus 3-month Treasury spread",
          "series": "T10Y3M",
          "value": 0.94,
          "percentile": 62,
          "median": 1.55,
          "history_from": "1982-01-04",
          "observations": 11185,
          "meaning": "..."
        },
        ...
      },
      "note": "..."
    }

A percentile is the share of that series' own history strictly below today's
reading, so it says where today sits and nothing about where it goes next.

Exit codes follow the plugin convention (0 ok, 5 on an upstream API error).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import fred, output  # noqa: E402

# Long histories only, and none that duplicates rates.py's four. BAMLH0A0HYM2 (high-yield
# OAS) was the obvious fifth and is deliberately absent: FRED licenses only a three-year
# window of the ICE series, so it returns ~780 observations from 2023 and a "percentile"
# computed on it would silently mean something entirely different from the others. The
# same trap is recorded against BAA10Y in rates.py.
SERIES = [
    ("curve_10y_3m", "T10Y3M", "10-year minus 3-month Treasury spread"),
    ("curve_10y_2y", "T10Y2Y", "10-year minus 2-year Treasury spread"),
    ("vix", "VIXCLS", "VIX, against its whole history"),
    ("financial_conditions", "NFCI", "Chicago Fed National Financial Conditions Index"),
]

# Each string is emitted verbatim and pinned to a test-local literal. They exist to keep a
# rank readable as a rank: every one says what the number is and what it has meant, and
# none says what to do about it.
MEANINGS = {
    "curve_10y_3m": (
        "The 10-year yield minus the 3-month bill. It goes negative when short rates are above "
        "long ones, which has preceded every US recession since 1970 with a lag of roughly one to "
        "two years — a lag long and variable enough that the sign is context, not timing."
    ),
    "curve_10y_2y": (
        "The 10-year yield minus the 2-year. The same shape read against a maturity the market "
        "trades more heavily than the bill, so it turns earlier and is noisier."
    ),
    "vix": (
        "The VIX, ranked against its whole history rather than the trailing year that "
        "indices.py reports. A high rank is fear already priced, not fear to come; a low rank is "
        "calm already priced."
    ),
    "financial_conditions": (
        "The Chicago Fed's National Financial Conditions Index, a weekly summary of money, debt "
        "and equity markets. Zero is the historical average: positive is tighter than average, "
        "negative is looser."
    ),
}

NOTE = (
    "Each percentile is the share of that series' own history strictly below today's reading, so "
    "the four are ranked over different spans and are not comparable with each other as numbers — "
    "read each against its own median. A rank describes where today sits against the past. It is "
    "not a forecast, and nothing here is a view on what any of it is worth."
)


def percentile_of(value: float, history: list[dict[str, Any]]) -> float:
    """Share of ``history`` strictly below ``value``, as a percentage.

    The same definition rates.py uses, duplicated for the reason its own copy is: the
    skills' scripts do not import each other.
    """
    values = [row["value"] for row in history]
    if not values:
        raise ValueError("empty history")
    return 100.0 * sum(1 for v in values if v < value) / len(values)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def build() -> dict[str, Any]:
    """Rank every series against its own full history."""
    indicators: dict[str, Any] = {}
    as_of = None
    for key, series, label in SERIES:
        hist = [r for r in fred.observations(series, 100_000) if isinstance(r.get("value"), (int, float))]
        if not hist:
            raise ValueError(f"{series} returned no usable observations")
        latest = hist[-1]
        values = [r["value"] for r in hist]
        as_of = max(as_of, latest["date"]) if as_of else latest["date"]
        indicators[key] = {
            "label": label,
            "series": series,
            "value": latest["value"],
            "percentile": round(percentile_of(latest["value"], hist)),
            "median": round(_median(values), 3),
            "history_from": hist[0]["date"],
            "observations": len(hist),
            "meaning": MEANINGS[key],
        }
    return {"as_of": as_of, "indicators": indicators, "note": NOTE}


def main(argv: list[str] | None = None) -> int:
    """``argv`` is accepted and ignored: there is nothing to select.

    Shaped like indices.py's and earnings.py's: this skill's scripts call
    ``output.run`` themselves and return its exit code, where the fixed-income
    scripts return the payload and wrap at ``__main__``. Both are in the tree;
    the local one is the one the tests drive.
    """
    return output.run(lambda args: build(), argv)


if __name__ == "__main__":
    sys.exit(main())
