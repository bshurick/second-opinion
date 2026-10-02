#!/usr/bin/env python3
"""Usage: flows.py [--cot] [--etf] [--cash] [--short SYM [SYM ...]] [--weeks N] [--days N] [--history]

Market flows and positioning: who is buying and selling, from the public
reporting regimes rather than price and volume. Three blocks by default
(--cot, --etf, --cash select a subset; --short always adds a fourth), each fetched
and summarised on its own so one failing source degrades to
{"error", "code"} inside its block instead of failing the run:

positioning: CFTC Traders in Financial Futures, weekly (Tuesday data,
  released Friday) for the S&P 500, Nasdaq 100, Russell 2000 and Dow
  futures, the eleven S&P sector index futures, 2-year and 10-year notes,
  the Ultra bond, the dollar index, VIX and bitcoin. Per contract, per
  trader class (asset managers, leveraged funds, dealers, other reportables,
  small traders): long, short, net, week-over-week net change, net as % of
  open interest, and the percentile of the latest net within --weeks (default
  52; 100 = most net-long of the window). Sector futures are thinly traded
  and can skip weeks. --history adds each contract's weekly net position per
  trader class over the window (oldest first), the series render.py charts.
etf_flows: SPDR sector ETFs (XLK ... XLC) plus SPY. Shares outstanding =
  AUM / NAV from State Street's daily fund finder, appended to a local
  series under the plugin data directory; flow = change in shares x NAV over
  the last 1, 5 and 20 observations. The series starts the first day this
  runs, so flows are null until a second day is recorded; observations and
  first_observation say how much history exists.
cash: FRED WRMFNS, retail money market fund assets (billions, weekly data
  that the Fed's H.6 release publishes monthly, so up to six weeks behind),
  with 1-, 4-, 13- and 52-week changes.
short_volume (--short): FINRA daily short-sale volume for the symbols
  given, latest short-volume ratio against its --days average (default 20).

Output: {as_of, positioning, etf_flows, cash, short_volume?, sources, notes}.
stdin is unused. Exit codes: 0, 2 (bad arguments), 6.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import cftc, finra, flows, fred, output, ssga  # noqa: E402
from second_opinion.errors import InvalidInput, ScriptError  # noqa: E402
from second_opinion.market import SECTOR_ETFS  # noqa: E402

_SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
_CASH_SERIES = "WRMFNS"
_ETF_TICKERS = [*SECTOR_ETFS, "SPY"]
SOURCES = {
    "positioning": "CFTC Commitments of Traders, Traders in Financial Futures (futures only), publicreporting.cftc.gov dataset gpe5-46if",
    "etf_flows": "State Street SPDR fund finder (daily NAV and AUM); shares series accumulated locally",
    "cash": "FRED series WRMFNS (Retail Money Market Funds, Federal Reserve H.6)",
    "short_volume": "FINRA Reg SHO consolidated daily short-sale volume files",
}
NOTES = [
    "Positioning is futures only: it shows how each trader class is positioned, not cash-equity ownership.",
    "ETF flows mix investor demand with arbitrage by authorized participants; a large one-day print is often a creation-unit rebalance.",
    "Short volume is the share of the day's volume sold short, dominated by market-maker hedging in ETFs; compare against the symbol's own average, not across symbols.",
    "Every block carries its own as-of date; the sources lag by a day (FINRA, SPDR), a week (CFTC) or up to six weeks (FRED's H.6 release is monthly with weekly data).",
]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"flows.py: {message}")


def _block(fn: Any) -> Any:
    try:
        return fn()
    except ScriptError as e:
        return {"error": str(e), "code": e.code}
    except ValueError as e:
        return {"error": str(e), "code": "INVALID_INPUT"}


def _positioning(weeks: int, history: bool = False) -> dict[str, Any]:
    rows = cftc.positioning(list(flows.CONTRACTS), weeks=weeks)
    contracts = flows.cot_summary(rows, history=history)
    dates = [c["report_date"] for c in contracts if c["report_date"]]
    return {"report_date": max(dates) if dates else None, "weeks": weeks, "contracts": contracts, "missing": [code for code, r in rows.items() if not r]}


def _etf_flows() -> dict[str, Any]:
    snap = ssga.snapshot(_ETF_TICKERS)
    series = ssga.record(snap)
    funds = flows.etf_flow_summary({t: series.get(t, []) for t in _ETF_TICKERS if series.get(t)})
    dates = [f["as_of"] for f in funds]
    return {"as_of": max(dates) if dates else None, "funds": funds, "unavailable": [t for t, s in snap.items() if s is None], "series_file": str(ssga.series_path())}


def _cash() -> dict[str, Any]:
    return flows.cash_summary(_CASH_SERIES, fred.observations(_CASH_SERIES, 53))


def _short(symbols: list[str], days: int) -> dict[str, Any]:
    rows = finra.short_volume(symbols, days=days)
    return {"days": days, "symbols": flows.short_volume_summary(rows)}


def _run(args: list[str]) -> dict[str, Any]:
    p = _Parser(prog="flows.py", add_help=False)
    p.add_argument("--cot", action="store_true")
    p.add_argument("--etf", action="store_true")
    p.add_argument("--cash", action="store_true")
    p.add_argument("--short", nargs="+", metavar="SYM")
    p.add_argument("--weeks", type=int, default=52)
    p.add_argument("--days", type=int, default=20)
    p.add_argument("--history", action="store_true")
    ns = p.parse_args(args)
    if not 1 <= ns.weeks <= 260:
        raise InvalidInput("--weeks must be between 1 and 260")
    if not 1 <= ns.days <= 120:
        raise InvalidInput("--days must be between 1 and 120")
    symbols = [s.upper() for s in ns.short or []]
    for s in symbols:
        if not _SYMBOL_RE.match(s):
            raise InvalidInput(f"invalid symbol {s!r}")
    if len(symbols) > 20:
        raise InvalidInput("--short takes at most 20 symbols")
    selected = {k for k, on in (("positioning", ns.cot), ("etf_flows", ns.etf), ("cash", ns.cash)) if on}
    if not selected:
        selected = {"positioning", "etf_flows", "cash"}
    out: dict[str, Any] = {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if "positioning" in selected:
        out["positioning"] = _block(lambda: _positioning(ns.weeks, ns.history))
    if "etf_flows" in selected:
        out["etf_flows"] = _block(_etf_flows)
    if "cash" in selected:
        out["cash"] = _block(_cash)
    if symbols:
        out["short_volume"] = _block(lambda: _short(symbols, ns.days))
        selected.add("short_volume")
    out["sources"] = {k: SOURCES[k] for k in SOURCES if k in selected}
    out["notes"] = NOTES
    return out


def main(argv: list[str] | None = None) -> int:
    return output.run(_run, argv)


if __name__ == "__main__":
    sys.exit(main())
