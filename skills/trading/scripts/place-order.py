#!/usr/bin/env python3
"""Usage: place-order.py <account_id> <symbol> <BUY|SELL> <qty> [order options as preview-order.py] --confirm

Without --confirm: prints the preview and exits 3 (NOT_CONFIRMED) — this is the
gate, not a bug. With --confirm: runs a FRESH preview, then places using that
preview's trade id. Output: {order_id, status, state, preview, raw} (`state`
is a compatibility alias for `status`).
Exit codes: 0, 2, 3, 4, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import orders_cli, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import NotConfirmed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        ns = orders_cli.build_parser("place-order.py", with_confirm=True).parse_args(args)
        hub = router.load()
        spec = orders_cli.spec_from_args(ns)
        if not ns.confirm:
            preview = hub.preview_order(spec)
            raise NotConfirmed("preview shown; re-run with --confirm after the user explicitly approves this order", preview=preview)
        return hub.place_order(spec)

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
