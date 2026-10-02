#!/usr/bin/env python3
"""Usage: earnings.py <symbol> [symbol ...]

Next earnings date and next ex-dividend date per symbol from Yahoo Finance's
calendar: {as_of, earnings: [{symbol, next_earnings_date, next_ex_dividend}],
missing: [symbol, ...]}. Symbols with neither an upcoming earnings date nor an
upcoming ex-dividend date are left out of "earnings" and listed in "missing";
as_of is the UTC timestamp of the run. Accepts 1-20 symbols; stdin is unused.
Exit codes: 0, 2 (no symbols given, an invalid symbol, or more than 20), 5, 6.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

_MAX_SYMBOLS = 20


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"earnings.py: {message}")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="earnings.py", add_help=False)
        p.add_argument("symbols", nargs="+")
        ns = p.parse_args(args)
        if len(ns.symbols) > _MAX_SYMBOLS:
            raise InvalidInput(f"earnings.py: at most {_MAX_SYMBOLS} symbols, got {len(ns.symbols)}")
        symbols = [brokerage.validate_symbol(s) for s in ns.symbols]
        earnings: list[dict] = []
        missing: list[str] = []
        for s in symbols:
            events = market.next_events(s)
            next_earnings, next_ex_dividend = events.get("next_earnings"), events.get("next_ex_dividend")
            if next_earnings or next_ex_dividend:
                earnings.append({"symbol": s, "next_earnings_date": next_earnings, "next_ex_dividend": next_ex_dividend})
            else:
                missing.append(s)
        return {"as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "earnings": earnings, "missing": missing}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
