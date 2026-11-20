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
``--history`` also adds interest_rates for the page's rates chart beside the trend:
{series: [{series, label, points: [[date, percent]]}], unavailable: [{series,
label, error}]} with the fed funds rate (DFF), the 2- and 10-year Treasury
yields (DGS2, DGS10) and the 30-year mortgage rate (MORTGAGE30US) from FRED over
twenty years: every observation in the latest year, the last one of each week
before it. A series FRED can't serve goes to unavailable; the rest still draw.
``--holdings`` adds top_holdings ([{symbol, name, weight_pct}], Yahoo's top
ten, undated) to each sector row. Both feed render.py's charts and modals;
leave them off when only the levels are needed.
Exit codes: 0, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from datetime import date, timedelta  # noqa: E402

from second_opinion import fred, market, output  # noqa: E402
from second_opinion.errors import ApiError  # noqa: E402

RATES = [("DFF", "Fed funds"), ("DGS2", "2-yr Treasury"), ("DGS10", "10-yr Treasury"), ("MORTGAGE30US", "30-yr mortgage")]
RATE_YEARS = 20


def _thin(obs: list[dict], daily_from: str) -> list[list]:
    """Every observation from ``daily_from`` on; before it, the last observation of each ISO week."""
    out: list[list] = []
    week = None
    for o in obs:
        if o["date"] >= daily_from:
            out.append([o["date"], o["value"]])
            continue
        wk = date.fromisoformat(o["date"]).isocalendar()[:2]
        if out and wk == week:
            out[-1] = [o["date"], o["value"]]
        else:
            out.append([o["date"], o["value"]])
        week = wk
    return out


def interest_rates(today: date | None = None) -> dict:
    today = today or date.today()
    start = (today - timedelta(days=round(365.25 * RATE_YEARS))).isoformat()
    daily_from = (today - timedelta(days=366)).isoformat()
    series: list[dict] = []
    unavailable: list[dict] = []
    for sid, label in RATES:
        try:
            obs = fred.observations(sid, 1_000_000)
        except (ApiError, ValueError) as exc:
            unavailable.append({"series": sid, "label": label, "error": str(exc)})
            continue
        first = max((i for i, o in enumerate(obs) if o["date"] <= start), default=0)
        points = _thin(obs[first:], daily_from)
        if len(points) > 1:
            series.append({"series": sid, "label": label, "points": points})
        else:
            unavailable.append({"series": sid, "label": label, "error": "no observations"})
    return {"series": series, "unavailable": unavailable}


def main(argv: list[str] | None = None) -> int:
    def run(args: list[str]) -> dict:
        flags = {k: True for k in ("history", "holdings") if f"--{k}" in args}
        snap = market.index_snapshot(**flags)
        if flags.get("history"):
            snap["interest_rates"] = interest_rates()
        return snap

    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
