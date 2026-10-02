#!/usr/bin/env python3
"""Usage: cancel-order.py <account_id> <order_id> --confirm

Without --confirm exits 3 with {"code": "NOT_CONFIRMED", "order_id": ...}.
Output: {account_id, order_id, cancelled, raw}. Exit codes: 0, 2, 3, 4, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput, NotConfirmed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        confirm = "--confirm" in args
        rest = [a for a in args if a != "--confirm"]
        if len(rest) != 2:
            raise InvalidInput("usage: cancel-order.py <account_id> <order_id> --confirm")
        account_id, order_id = rest
        if not confirm:
            raise NotConfirmed("re-run with --confirm after the user explicitly approves cancelling this order", account_id=account_id, order_id=order_id)
        return router.load().cancel_order(account_id, order_id)

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
