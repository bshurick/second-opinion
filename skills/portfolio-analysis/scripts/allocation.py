"""Portfolio allocation, concentration, and sector-drift analysis.

This script reads a JSON object from stdin, computes position/sector
weights, a Herfindahl-Hirschman concentration index, top-5 concentration,
and (optionally) drift versus target sector weights, and writes a JSON
object to stdout. It is invoked as:

    python allocation.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "positions": [
        {"symbol": "AAPL", "value": 40000, "sector": "Technology"},
        ...
        # "sector" is optional per position; missing/empty/None -> "Unknown".
        # "value" must be >= 0. "symbol" must be unique across positions.
      ],
      "cash": 5000,                      # optional, defaults to 0; must be >= 0
      "targets": {"Technology": 0.3}     # optional target sector weights
    }

Output JSON contract (stdout)::

    {
      "total_value": ...,           # sum(position values) + cash, 2dp
      "weights": {                  # per symbol, 4dp; includes "CASH" iff cash > 0
        "AAPL": ..., ..., "CASH": ...
      },
      "sector_weights": {            # 4dp. Cash is EXCLUDED from both the
        "Technology": ...            # numerator and the denominator here:
      },                             # the denominator is total POSITION value
                                      # (not total_value), since cash has no
                                      # sector. If all position values are 0
                                      # (a cash-only book with zero-value
                                      # tracking positions -- total_value can
                                      # still be > 0 via cash), sector_weights
                                      # are defined as 0.0 rather than raising
                                      # a divide-by-zero.
      "hhi": ...,                    # 4dp; sum of squared symbol weights
                                      # (from "weights", i.e. CASH included)
      "hhi_interpretation": "diversified" | "moderate" | "concentrated",
                                      # hhi < 0.10 -> diversified
                                      # 0.10 <= hhi <= 0.18 -> moderate
                                      # hhi > 0.18 -> concentrated
      "effective_n": ...,            # 4dp; 1 / hhi: the number of equally
                                      # sized positions with the same
                                      # concentration; null when hhi == 0
      "effective_n_interpretation":
                          "diversified" | "moderate" | "concentrated",
                                      # this value IS hhi_interpretation (not
                                      # independently classified from
                                      # "effective_n"), read as the same
                                      # bands in position-count terms:
                                      # effective_n > 10.0 (= 1/0.10)
                                      # diversified; 1/0.18 (≈ 5.5556) <=
                                      # effective_n <= 10.0 moderate;
                                      # effective_n < 1/0.18 (≈ 5.5556)
                                      # concentrated. Both are classified on
                                      # the rounded hhi (4dp), so the label
                                      # always agrees with hhi_interpretation.
      "top_5_concentration": ...,    # 4dp; sum of the 5 largest symbol
                                      # weights from "weights" (fewer than 5
                                      # symbols -> sum of all of them)
      "drift": {                     # only present when "targets" is given
        "Technology": ...            # signed, 4dp: sector_weight - target.
      }                              # A target sector absent from the
                                      # portfolio gets drift = -target.
    }

Validation errors (non-object input, empty positions, negative value/cash,
duplicate symbols, or total_value == 0) are reported as
``{"error": "..."}`` on stdout with exit code 2. total_value == 0 (all
positions AND cash are zero) is a defined error rather than a
zero-denominator convention: every weight would be undefined (0/0), so
there is no meaningful result to return.
"""

from __future__ import annotations

import json
import sys

_TOP_N = 5
_HHI_DIVERSIFIED_MAX = 0.10
_HHI_MODERATE_MAX = 0.18


def _effective_n(hhi: float) -> float | None:
    """1 / hhi, the number of equally sized positions with that concentration."""
    return round(1.0 / hhi, 4) if hhi else None


def run_allocation(params: dict) -> dict:
    """Run the allocation/concentration/drift analysis described by ``params``.

    Raises ValueError (or TypeError for non-numeric fields) on invalid input;
    callers that need the stdin/stdout error contract should use main().
    """
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")

    positions = params.get("positions")
    if not isinstance(positions, list) or len(positions) == 0:
        raise ValueError("at least one position is required")
    for position in positions:
        if not isinstance(position, dict):
            raise ValueError("each position must be an object")
        if "symbol" not in position or "value" not in position:
            raise ValueError("each position requires 'symbol' and 'value'")

    symbols = [str(p["symbol"]) for p in positions]
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate symbol in positions is ambiguous")

    values = [float(p["value"]) for p in positions]
    if any(v < 0 for v in values):
        raise ValueError("position values must not be negative")

    cash = float(params.get("cash", 0.0))
    if cash < 0:
        raise ValueError("cash must not be negative")

    sectors = [str(p["sector"]) if p.get("sector") else "Unknown" for p in positions]

    positions_total = sum(values)
    total_value = positions_total + cash
    if total_value == 0:
        raise ValueError("portfolio has no value")

    weights: dict[str, float] = {
        symbol: value / total_value for symbol, value in zip(symbols, values, strict=True)
    }
    if cash > 0:
        weights["CASH"] = cash / total_value

    sector_totals: dict[str, float] = {}
    for sector, value in zip(sectors, values, strict=True):
        sector_totals[sector] = sector_totals.get(sector, 0.0) + value
    sector_weights = {
        sector: (total / positions_total if positions_total != 0 else 0.0)
        for sector, total in sector_totals.items()
    }

    # Classify on the ROUNDED value so the label always agrees with the
    # displayed hhi: 4*(0.2^2)+2*(0.1^2) is 0.18000000000000005 in floats,
    # which would read "concentrated" while the output shows 0.18.
    hhi = round(sum(w**2 for w in weights.values()), 4)
    if hhi < _HHI_DIVERSIFIED_MAX:
        hhi_interpretation = "diversified"
    elif hhi <= _HHI_MODERATE_MAX:
        hhi_interpretation = "moderate"
    else:
        hhi_interpretation = "concentrated"

    effective_n = _effective_n(hhi)
    # effective_n_interpretation below IS hhi_interpretation, not an
    # independent classification of effective_n. In position-count terms the
    # same bands read: > 10.0 (1/0.10) diversified, 1/0.18 (≈5.5556)-10.0
    # moderate, < 1/0.18 (≈5.5556) concentrated. Both are derived from the
    # rounded hhi so the label always agrees with hhi_interpretation.

    top_5_concentration = sum(sorted(weights.values(), reverse=True)[:_TOP_N])

    result: dict = {
        "total_value": round(total_value, 2),
        "weights": {symbol: round(w, 4) for symbol, w in weights.items()},
        "sector_weights": {sector: round(w, 4) for sector, w in sector_weights.items()},
        "hhi": round(hhi, 4),
        "hhi_interpretation": hhi_interpretation,
        "effective_n": effective_n,
        "effective_n_interpretation": hhi_interpretation,
        "top_5_concentration": round(top_5_concentration, 4),
    }

    targets = params.get("targets")
    if targets:
        if not isinstance(targets, dict):
            raise ValueError("targets must be an object")
        drift = {
            sector: round(sector_weights.get(sector, 0.0) - float(target), 4)
            for sector, target in targets.items()
        }
        result["drift"] = drift

    return result


def main() -> None:
    """Read JSON params from stdin, write the allocation result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
        result = run_allocation(params)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
