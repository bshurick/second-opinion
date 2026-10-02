#!/usr/bin/env python3
"""Usage: portfolio.py <account_id>

Positions for one account: {"account_id", "positions": [SnapTrade position
objects: symbol.symbol.symbol, units, price, open_pnl, average_purchase_price]}.
Exit codes: 0, 2, 4, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        if len(args) != 1:
            raise InvalidInput("usage: portfolio.py <account_id>")
        return router.load().get_portfolio(args[0])

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
