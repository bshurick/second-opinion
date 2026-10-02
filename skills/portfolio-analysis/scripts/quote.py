#!/usr/bin/env python3
"""Usage: quote.py <symbol> [<symbol>...]

Real-time from E*Trade when a direct session is live, else delayed Yahoo;
each row has `source` and `realtime`.
Exit codes: 0, 2, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        if not args:
            raise InvalidInput("usage: quote.py <symbol> [<symbol>...]")
        hub = router.try_load()
        rows = market.quote([brokerage.validate_symbol(s) for s in args], hub=hub)
        return {"quotes": rows, "source": market.quote_sources(rows)}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
