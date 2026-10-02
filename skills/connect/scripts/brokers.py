#!/usr/bin/env python3
"""Usage: brokers.py [--query TEXT]

SnapTrade-supported brokerages: {"brokerages": [{name, slug, supports_trade,
supports_read, maintenance_mode}...], "count": N}, sorted by name.
supports_trade/supports_read are true/false/null depending on what SnapTrade
reports; maintenance_mode true means that brokerage can't be linked right now.
--query TEXT filters case-insensitively on name or slug (count becomes the
filtered count and "query" is echoed in the output).
Exit codes: 0, 2, 4, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        query = None
        it = iter(args)
        for a in it:
            if a == "--query":
                query = next(it, None)
                if query is None:
                    raise InvalidInput("--query requires TEXT")
            else:
                raise InvalidInput("usage: brokers.py [--query TEXT]")
        sdk = router.load().for_broker("snaptrade").sdk
        rows = brokerage.list_brokerages(sdk)
        if query:
            q = query.lower()
            rows = [r for r in rows if q in (r.get("name") or "").lower() or q in (r.get("slug") or "").lower()]
        result: dict = {"brokerages": rows, "count": len(rows)}
        if query:
            result["query"] = query
        return result

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
