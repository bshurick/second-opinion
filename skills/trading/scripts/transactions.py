#!/usr/bin/env python3
"""Usage: transactions.py <account_id> [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--count N]

Transactions for one account (client-side filtered): {"account_id", "transactions": [...]}.
A --start/--end that is not YYYY-MM-DD is exit 2, never a broker call.
Exit codes: 0, 2, 4, 5, 6.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"transactions.py: {message}")


def _date(value: str | None, flag: str) -> str | None:
    if value is None:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise InvalidInput(f"{flag} must be YYYY-MM-DD, got {value!r}") from exc
    return value


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="transactions.py", add_help=False)
        p.add_argument("account_id")
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--count", type=int, default=50)
        ns = p.parse_args(args)
        start = _date(ns.start, "--start")
        end = _date(ns.end, "--end")
        return router.load().list_transactions(ns.account_id, start=start, end=end, count=ns.count)

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
