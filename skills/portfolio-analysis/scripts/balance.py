#!/usr/bin/env python3
"""Usage: balance.py <account_id>

Balances for one account: {"account_id", "balances": [SnapTrade balance
objects: currency, cash, buying_power]}. Exit codes: 0, 2, 4, 5, 6.
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
            raise InvalidInput("usage: balance.py <account_id>")
        return router.load().get_balance(args[0])

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
