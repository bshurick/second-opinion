#!/usr/bin/env python3
"""Usage: indices.py [--history] [--holdings]

Snapshot of major US indices, sector ETFs, Treasury yields and the macro block
(gold, US dollar, WTI crude, bitcoin, VIX 3-month) from one batched Yahoo
Finance download: {as_of, indices: [{symbol, name, last, day_change_pct,
week_change_pct}], sectors: [...], rates: [...], macro: {gold, dollar, oil,
bitcoin, vix_3m}, spreads: {10y_13w, 5y_13w, 30y_5y, 30y_13w},
breadth: {rsp_spy_1m, rsp_spy_3m, sectors_above_50sma, sectors_total, note},
vix_percentile_1y}. Yields and spreads are in percentage points (^TNX 4.25 =
4.25%); breadth and RSP/SPY relative returns are proxies, not full market
breadth. Missing data degrades a row or field to null — never the snapshot.
``--history`` adds each row's daily closes over the trailing year (history as
[date, close] pairs, high_1y, low_1y, change_1y_pct) and trend.daily, the last
year of daily S&P 500 closes with the weekly averages as they stood each day,
and lengthens trend.series from five years of weeks to twenty.
``--holdings`` adds top_holdings ([{symbol, name, weight_pct}], Yahoo's top
ten, undated) to each sector row. Both feed render.py's charts and modals;
leave them off when only the levels are needed.
Exit codes: 0, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import market, output  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def run(args: list[str]) -> dict:
        flags = {k: True for k in ("history", "holdings") if f"--{k}" in args}
        return market.index_snapshot(**flags)

    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
