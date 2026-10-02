#!/usr/bin/env python3
"""Usage: aggregate_report.py <account_id> [<account_id>...] [--partial]

Symbol-aggregated positions across the given accounts, ready to pipe into
allocation.py: SnapTrade positions once per account, units summed by symbol,
each symbol's price the value-weighted average of the broker's prices
refreshed by ONE batched market.day_changes call (fallback to the broker's
price on failure or on symbols Yahoo does not cover; ``sources.quotes`` says
which — "yahoo", a direct broker's name, or "mixed"), then aggregate.py.
Output is aggregate.py's contract (``positions``
rows of symbol/units/price/value sorted by value desc, sorted ``accounts``,
``total_value``, ``flags``, which gains BROKER_UNAVAILABLE when a broker
could not be listed and one UNKNOWN_ACCOUNT per requested id no configured
broker lists — that id is skipped and the known ones are aggregated) plus
``sources``; the positions array is exactly allocation.py's expected input
shape plus units/price. stdin is unused. An id that is really a listed
account's account_number (SnapTrade reports E*Trade's accountIdKey, the
direct adapter's id, as the number) is named as such in the message.
Exit codes: 0, 2 (no ids, no known id, no priced positions), 4, 5, 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import aggregate  # noqa: E402
from second_opinion import market, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"aggregate_report.py: {message}")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="aggregate_report.py", add_help=False)
        p.add_argument("account_ids", nargs="+")
        p.add_argument("--partial", action="store_true")
        ns = p.parse_args(args)

        hub = router.load()
        hub.partial = ns.partial
        accounts = hub.list_accounts()
        known = {a["account_id"] for a in accounts}
        wanted = list(dict.fromkeys(ns.account_ids))
        unknown = [w for w in wanted if w not in known]
        if len(unknown) == len(wanted):
            raise hub.unknown_account_error(unknown)  # nothing left to aggregate

        portfolios = [
            {"account_id": aid, "positions": hub.get_portfolio(aid)["positions"] or []}
            for aid in wanted
            if aid in known
        ]
        symbols = sorted(
            {
                sym
                for portfolio in portfolios
                for pos in portfolio["positions"]
                if isinstance(pos, dict) and (sym := aggregate._symbol(pos))
            }
        )
        prices: dict = {}
        source_quotes = "snaptrade"
        if symbols:
            try:
                quotes = market.day_changes(symbols, hub=hub)
                if quotes:
                    source_quotes = market.quote_sources(list(quotes.values())) or "yahoo"
                    prices = {sym: q.get("price") for sym, q in quotes.items()}
            except Exception:  # noqa: BLE001 — broker prices are the fallback
                pass

        try:
            result = aggregate.run_aggregate({"portfolios": portfolios, "prices": prices})
        except (ValueError, TypeError) as exc:
            raise InvalidInput(str(exc)) from exc
        result["flags"] = list(result.get("flags") or []) + hub.unknown_account_flags(unknown) + hub.unavailable_flags()
        selected = [a for a in accounts if a["account_id"] in known and a["account_id"] in set(wanted)]
        return {
            "sources": {"holdings": router.holdings_source(selected), "quotes": source_quotes},
            **result,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
