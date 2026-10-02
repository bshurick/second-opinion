#!/usr/bin/env python3
"""Usage: indices.py

Snapshot of major US indices, sector ETFs, Treasury yields and the macro block
(gold, US dollar, WTI crude, bitcoin, VIX 3-month) from one batched Yahoo
Finance download: {as_of, indices: [{symbol, name, last, day_change_pct,
week_change_pct}], sectors: [...], rates: [...], macro: {gold, dollar, oil,
bitcoin, vix_3m}, spreads: {10y_13w, 5y_13w, 30y_5y, 30y_13w},
breadth: {rsp_spy_1m, rsp_spy_3m, sectors_above_50sma, sectors_total, note},
vix_percentile_1y}. Yields and spreads are in percentage points (^TNX 4.25 =
4.25%); breadth and RSP/SPY relative returns are proxies, not full market
breadth. Missing data degrades a row or field to null — never the snapshot.
Exit codes: 0, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import market, output  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    return output.run(lambda args: market.index_snapshot(), argv)


if __name__ == "__main__":
    sys.exit(main())
