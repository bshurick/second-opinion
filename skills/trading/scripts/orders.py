#!/usr/bin/env python3
"""Usage: orders.py <account_id> [--status STATE] [--symbol SYM] [--count N]

Orders for one account (client-side filtered): {"account_id", "orders": [...]}.
Every order row keeps the broker adapter's keys and adds four flat aliases so
callers need not dig into nested objects: ``order_id`` (= brokerage_order_id,
the id cancel-order.py takes), ``symbol`` (= universal_symbol.symbol),
``side`` (= action) and ``quantity`` (= total_quantity); each is null when
the adapter did not supply the source field. Exit codes: 0, 2, 4, 5, 6.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"orders.py: {message}")


def _flatten(order: dict) -> dict:
    """Top-level order_id / symbol / side / quantity next to the adapter's own keys."""
    symbol_obj = order.get("universal_symbol")
    symbol = symbol_obj.get("symbol") if isinstance(symbol_obj, dict) else None
    flat = dict(order)
    for key, value in (("order_id", order.get("brokerage_order_id")), ("symbol", symbol), ("side", order.get("action")), ("quantity", order.get("total_quantity"))):
        if flat.get(key) is None:  # an adapter's own value for the same key wins
            flat[key] = value
    return flat


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="orders.py", add_help=False)
        p.add_argument("account_id")
        p.add_argument("--status")
        p.add_argument("--symbol")
        p.add_argument("--count", type=int, default=25)
        ns = p.parse_args(args)
        orders = router.load().list_orders(ns.account_id, status=ns.status, symbol=ns.symbol, count=ns.count)
        return {"account_id": ns.account_id, "orders": [_flatten(o) if isinstance(o, dict) else o for o in orders]}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
