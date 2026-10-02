"""Aggregate SnapTrade positions from several accounts by symbol.

This script reads a JSON object from stdin, sums units per symbol across the
given portfolios, prices each symbol at the value-weighted average of the
broker's prices (or a refreshed price when one is supplied), and writes a
JSON object to stdout whose ``positions`` array pipes straight into
allocation.py. It is invoked as:

    python aggregate.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "portfolios": [                              # required, non-empty
        {"account_id": "acc-1",
         "positions": [<SnapTrade position objects: symbol.symbol.symbol,
                        units, price>, ...]},
        ...
      ],
      "prices": {"VTI": 110.0}      # optional refreshed per-symbol prices
                                    # (e.g. from market.day_changes); a symbol
                                    # absent from the map (or mapped to null)
                                    # keeps its value-weighted broker price
    }

Output JSON contract (stdout)::

    {
      "positions": [                 # sorted by value desc (ties: symbol asc)
        {"symbol": "VTI",            # symbol extraction unwraps SnapTrade's
          "units": 100.0,            #   nested symbol objects; units summed,
                                     #   6dp; units <= 0 rows are skipped
          "price": 100.8,            #   value-weighted broker price or the
                                     #   refreshed price, 4dp
          "value": 10080.0}],        #   units * price, 2dp
      "accounts": ["acc-1", ...],    # sorted unique account ids
      "total_value": 11580.0,        # 2dp
      "flags": [{"code": "UNPRICED_SKIPPED",
                 "message": "1 position row(s) without a price were valued "
                            "at the symbol's value-weighted average price"}]
    }

A position row without a price (and no refreshed price for its symbol) is not
dropped: its units are folded into the symbol's total and priced at that
symbol's value-weighted average price from the rows that do have one (a
``prices`` override always wins regardless). Such rows are counted in the
``UNPRICED_SKIPPED`` flag's message even though they are kept. A symbol with
NO priced units anywhere — nothing to build an average from, and no
``prices`` override — has nothing to price it with and is dropped entirely:
it does not appear in ``positions`` and its units do not count toward
``total_value``. Rows with units <= 0 or no symbol are skipped silently.
Validation errors (non-object input, missing/empty/invalid ``portfolios``, a
non-object ``prices``, or no priced positions at all) are reported as
``{"error": "..."}`` on stdout with exit code 2.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _symbol(position: dict[str, Any]) -> str | None:
    """Unwrap SnapTrade's nested symbol objects down to the ticker string."""
    symbol = position.get("symbol")
    for _ in range(2):
        if isinstance(symbol, dict):
            symbol = symbol.get("symbol")
    if isinstance(symbol, str) and symbol.strip():
        return symbol.strip().upper()
    return None


def run_aggregate(params: dict[str, Any]) -> dict[str, Any]:
    """Run the cross-account aggregation described by ``params``.

    Raises ValueError (or TypeError for non-numeric fields) on invalid input;
    callers that need the stdin/stdout error contract should use main().
    """
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")

    portfolios = params.get("portfolios")
    if not isinstance(portfolios, list) or not portfolios:
        raise ValueError("portfolios must be a non-empty list")

    prices = params.get("prices") or {}
    if not isinstance(prices, dict):
        raise ValueError("prices must be an object")

    book: dict[str, dict[str, float]] = {}
    skipped = 0
    accounts: set[str] = set()
    for portfolio in portfolios:
        if not isinstance(portfolio, dict):
            raise ValueError("each portfolio must be an object")
        accounts.add(str(portfolio.get("account_id") or ""))
        positions = portfolio.get("positions") or []
        if not isinstance(positions, list):
            raise ValueError("each portfolio's positions must be a list")
        for position in positions:
            if not isinstance(position, dict):
                raise ValueError("each position must be an object")
            symbol = _symbol(position)
            if not symbol:
                continue
            units = float(position.get("units") or 0)
            if units <= 0:
                continue
            price = position.get("price")
            row = book.setdefault(symbol, {"units": 0.0, "value": 0.0, "priced": 0.0})
            row["units"] += units
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                row["value"] += units * float(price)
                row["priced"] += units
            else:
                skipped += 1

    out_positions: list[dict[str, Any]] = []
    for symbol in sorted(book):
        row = book[symbol]
        refresh = prices.get(symbol)
        if isinstance(refresh, (int, float)) and not isinstance(refresh, bool) and refresh > 0:
            price = float(refresh)
        elif row["priced"] > 0:
            price = row["value"] / row["priced"]
        else:
            continue  # nothing to price this symbol with
        out_positions.append(
            {
                "symbol": symbol,
                "units": round(row["units"], 6),
                "price": round(price, 4),
                "value": round(row["units"] * price, 2),
            }
        )

    if not out_positions:
        raise ValueError("no priced positions in the given portfolios")
    out_positions.sort(key=lambda p: (-p["value"], p["symbol"]))

    flags: list[dict[str, str]] = []
    if skipped:
        flags.append(
            {
                "code": "UNPRICED_SKIPPED",
                "message": (
                    f"{skipped} position row(s) without a price were valued "
                    "at the symbol's value-weighted average price"
                ),
            }
        )

    return {
        "positions": out_positions,
        "accounts": sorted(accounts),
        "total_value": round(sum(p["value"] for p in out_positions), 2),
        "flags": flags,
    }


def main() -> None:
    """Read JSON params from stdin, write the aggregate result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
        result = run_aggregate(params)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
