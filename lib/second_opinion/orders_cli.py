"""argparse plumbing shared by preview-order.py, place-order.py, cancel-order.py."""
from __future__ import annotations

import argparse

from second_opinion.brokerage import ORDER_TYPES, SIDES, TIME_IN_FORCE, OrderSpec, validate_quantity
from second_opinion.errors import InvalidInput


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"{self.prog}: {message}")


def _quantity(text: str) -> int | float:
    """Shares as typed: ``2`` and ``2.0`` are whole; a fraction is left for the broker adapter to accept or refuse."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid quantity: {text!r}") from None
    return validate_quantity(value, fractional=True)


def build_parser(prog: str, with_confirm: bool) -> argparse.ArgumentParser:
    p = _Parser(prog=prog, add_help=False)
    p.add_argument("account_id")
    p.add_argument("symbol")
    p.add_argument("side", type=str.upper, choices=sorted(SIDES))
    p.add_argument("quantity", type=_quantity)
    p.add_argument("--type", dest="order_type", type=str.upper, choices=sorted(ORDER_TYPES), default="MARKET")
    p.add_argument("--limit", dest="limit_price", type=float)
    p.add_argument("--stop", dest="stop_price", type=float)
    p.add_argument("--term", dest="time_in_force", type=str.upper, choices=sorted(TIME_IN_FORCE), default="GOOD_FOR_DAY")
    if with_confirm:
        p.add_argument("--confirm", action="store_true")
    return p


def spec_from_args(ns: argparse.Namespace) -> OrderSpec:
    return OrderSpec(
        account_id=ns.account_id, symbol=ns.symbol, side=ns.side, quantity=ns.quantity,
        order_type=ns.order_type, limit_price=ns.limit_price, stop_price=ns.stop_price,
        time_in_force=ns.time_in_force,
    )
