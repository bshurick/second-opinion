#!/usr/bin/env python3
"""Usage: history.py <symbol> [--period 1mo|3mo|6mo|1y|2y|5y|max] [--start YYYY-MM-DD --end YYYY-MM-DD] [--interval 1d|1wk|1mo]

Daily closes from Yahoo Finance: {symbol, period, interval, count,
prices: [{date, open, high, low, close, volume}]}. Feed ``prices`` (date +
close) straight into signals.py. Exit codes: 0, 2, 5, 6.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"history.py: {message}")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="history.py", add_help=False)
        p.add_argument("symbol")
        p.add_argument("--period", default="1y")
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--interval", default="1d")
        ns = p.parse_args(args)
        if bool(ns.start) != bool(ns.end):
            raise InvalidInput("--start and --end must be given together")
        return market.price_history(brokerage.validate_symbol(ns.symbol), period=ns.period, start=ns.start, end=ns.end, interval=ns.interval)

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
