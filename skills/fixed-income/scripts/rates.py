#!/usr/bin/env python3
"""Usage: rates.py — the rate environment behind every bond valuation.

Writes one JSON object to stdout: today's Treasury par curve, the bootstrapped
zero and forward curves, the short-rate path the curve implies, the FOMC's own
projection, and where each component sits against its own history.

Reads nothing from stdin, and takes no argument that changes what it does: an
argument is accepted and discarded rather than refused.

Output JSON contract (stdout)::

    {
      "as_of": {"curve": "2026-09-16"},
      "par_curve": {"0.5": 4.22, "10": 5.01, ...},
      "zero_rates": {"1": 4.50, ...},
      "forwards": {"1y1y": 4.62, ...},
      "implied_short_rate_path": [{"start": 0, "end": 1, "rate_pct": 4.45}, ...],
      "implied_average_short_rate_pct": 4.28,
      "fomc_projection": {"longer_run_pct": 3.2, "path": [...]},
      "percentiles": {"treasury_10y": {"value": 5.11, "percentile": 48, ...},
                      "real_yield_10y": {"value": 2.68, "percentile": 99, ...}, ...},
      "benchmarks": {"fed_funds_pct": 3.63, "bill_3m_pct": 4.14},
      "assumptions": {...},
      "note": "..."
    }

Exit codes follow the plugin convention (0 ok, 5 on an upstream API error).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
# The plugin's shared math package lives in lib/ at the plugin root.
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import bondmath, fred, output  # noqa: E402

PAR_SERIES = [
    (0.0833, "DGS1MO"),
    (0.25, "DGS3MO"),
    (0.5, "DGS6MO"),
    (1.0, "DGS1"),
    (2.0, "DGS2"),
    (3.0, "DGS3"),
    (5.0, "DGS5"),
    (7.0, "DGS7"),
    (10.0, "DGS10"),
    (20.0, "DGS20"),
    (30.0, "DGS30"),
]

# Historical percentile sources. BAA10Y, not BAMLC0A0CM: FRED licenses only a
# three-year window of the ICE series, which silently truncates the history.
PERCENTILE_SERIES = [
    ("treasury_10y", "DGS10", "10-year Treasury yield"),
    ("real_yield_10y", "DFII10", "10-year real yield (TIPS)"),
    ("breakeven_10y", "T10YIE", "10-year breakeven inflation"),
    ("term_premium_10y", "THREEFYTP10", "10-year term premium"),
    ("credit_spread_baa", "BAA10Y", "Baa corporate spread over Treasuries"),
]

# Published zero-curve tenors — all inside the bootstrap's 30-year grid, where
# the curve is actually bootstrapped rather than flat-extrapolated.
ZERO_TENORS = (1, 2, 3, 5, 7, 10, 20, 30)

# Key forward rates, labelled start-by-duration. Every leg ends at or inside the
# 30-year grid point.
FORWARD_POINTS = [
    ("1y1y", 1.0, 2.0),
    ("2y1y", 2.0, 3.0),
    ("5y1y", 5.0, 6.0),
    ("10y1y", 10.0, 11.0),
]


def percentile_of(value: float, history: list[dict[str, Any]]) -> float:
    """Share of ``history`` strictly below ``value``, as a percentage."""
    values = [row["value"] for row in history]
    if not values:
        raise ValueError("empty history")
    return 100.0 * sum(1 for v in values if v < value) / len(values)


def short_rate_path(curve: dict[float, float], horizon_years: int = 6) -> list[dict[str, Any]]:
    """One-year forward rates out to ``horizon_years`` — the implied path.

    The path starts at the first bootstrap grid point (0.5 years) rather than at
    zero: a forward from exactly ``t = 0`` is the curve's constant short-rate
    extension, not an observed market forward.
    """
    path = []
    for i in range(horizon_years):
        t1, t2 = float(i), float(i + 1)
        start, end = max(t1, 0.5), max(t2, 1.0)
        rate = bondmath.forward_rate(curve, start, end)
        path.append({"start": i, "end": i + 1, "rate_pct": round(rate * 100, 3)})
    return path


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def build() -> dict[str, Any]:
    """Assemble the rate environment from FRED."""
    tenors: list[float] = []
    pars: list[float] = []
    curve_date = ""
    for tenor, series in PAR_SERIES:
        obs = fred.latest(series)
        tenors.append(tenor)
        pars.append(obs["value"] / 100.0)
        curve_date = obs["date"]

    curve = bondmath.bootstrap(tenors, pars)
    path = short_rate_path(curve)

    percentiles: dict[str, Any] = {}
    for key, series, label in PERCENTILE_SERIES:
        hist = fred.observations(series, 100000)
        now = hist[-1]["value"]
        percentiles[key] = {
            "label": label,
            "value": now,
            "percentile": round(percentile_of(now, hist)),
            "median": round(_median([r["value"] for r in hist]), 3),
            "series": series,
            "history_from": hist[0]["date"],
        }

    fomc_path = fred.observations("FEDTARMD", 100000)
    longer_run = fred.latest("FEDTARMDLR")

    return {
        "as_of": {"curve": curve_date},
        "par_curve": {str(t): round(p * 100, 3) for t, p in zip(tenors, pars)},
        "zero_rates": {str(t): round(bondmath.zero_rate(curve, t) * 100, 3) for t in ZERO_TENORS},
        "forwards": {
            label: round(bondmath.forward_rate(curve, t1, t2) * 100, 3)
            for label, t1, t2 in FORWARD_POINTS
        },
        "implied_short_rate_path": path,
        "implied_average_short_rate_pct": round(sum(r["rate_pct"] for r in path) / len(path), 3),
        "fomc_projection": {
            "longer_run_pct": longer_run["value"],
            "as_of": longer_run["date"],
            "path": [{"year": r["date"][:4], "median_pct": r["value"]} for r in fomc_path],
        },
        "percentiles": percentiles,
        "benchmarks": {
            "fed_funds_pct": fred.latest("DFF")["value"],
            "bill_3m_pct": fred.latest("DGS3MO")["value"],
        },
        "assumptions": {
            "frequency": 2,
            "max_years": 30.0,
            "path_starts_at_years": 0.5,
            "note": (
                "Par yields bootstrap to a semi-annual zero curve out to 30 years. "
                "The implied path's first row is labelled 0-1y but is priced from the "
                "first grid point (0.5y): a forward from exactly t=0 is the curve's "
                "constant short-rate extension, not an observed market forward. "
                "Nothing is queried beyond 30 years, where the curve's flat "
                "extrapolation would silently misprice."
            ),
            "breakeven_meaning": (
                "percentiles.real_yield_10y is the 10-year TIPS yield and "
                "percentiles.breakeven_10y is the 10-year breakeven, which is the "
                "difference between the nominal 10-year yield and that real yield: "
                "nominal is approximately real plus breakeven. The breakeven is the "
                "inflation rate at which a TIPS and a nominal Treasury come out even, "
                "so inflation realised above it favours the TIPS and below it favours "
                "the nominal. It is a market price rather than a forecast, and it "
                "carries an inflation risk premium as well as an expectation, so it is "
                "not the market's central estimate of inflation. Neither figure is a "
                "view on whether either instrument is cheap or expensive."
            ),
        },
        "note": (
            "A high percentile on a yield means you are paid more than usual — cheap. "
            "A low percentile on a spread means you are paid less than usual — rich. "
            "These rank today against history; they are not a forecast."
        ),
    }


def main(argv: list[str]) -> dict[str, Any]:
    """Build the rate environment.

    ``argv`` is required by ``output.run``'s signature and is deliberately
    ignored: there is nothing to select, so any argument is accepted and
    discarded rather than refused.
    """
    return build()


if __name__ == "__main__":
    raise SystemExit(output.run(main))
