#!/usr/bin/env python3
"""Usage: preview-order.py <account_id> <symbol> <BUY|SELL> <qty> [--type MARKET|LIMIT|STOP|STOP_LIMIT] [--limit X] [--stop X] [--term GOOD_FOR_DAY|GOOD_UNTIL_CANCEL|IMMEDIATE_OR_CANCEL|FILL_OR_KILL]

Preview only — never places. Output: {trade_id, price, units, estimated_cost,
remaining_cash, estimated_commission, currency, estimated_buying_power,
account_id, symbol, side, quantity, order_type, limit_price, stop_price,
time_in_force, broker, client_order_id, flags, raw}. ``broker`` is the
adapter that priced it, ``client_order_id`` is the id a direct broker will
carry on the order, and ``flags`` holds warnings such as UNSETTLED_CASH.
<qty> may be fractional (up to 3 decimals) on a direct E*Trade account only;
SnapTrade refuses it with FRACTIONAL_NOT_SUPPORTED.
Exit codes: 0, 2 (incl. READ_ONLY_ACCOUNT, SHADOWED_ACCOUNT), FRACTIONAL_*, 4, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import orders_cli, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        ns = orders_cli.build_parser("preview-order.py", with_confirm=False).parse_args(args)
        return router.load().preview_order(orders_cli.spec_from_args(ns))

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
