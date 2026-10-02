#!/usr/bin/env python3
"""Usage: sync-broker.py [--account ACCOUNT_ID ...] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--partial]

Pull brokerage activity (trades, dividends, cash movements) for every open
connected account into the local ledger. SnapTrade serves at most two years
of history, so --start defaults to 729 days ago. Entries are normalized by
normalize.py and deduplicated against the ledger; rows from a direct broker
are labelled "snaptrade:<account_id>" too, because normalize.py is shared
and unchanged — the account id, not the label, says where a row came from.
stdin is unused.

Output: {start, end, accounts: [{account_id, fetched, imported, duplicates,
skipped_count}], ledger_path, ledger_count, flags (BROKER_UNAVAILABLE when a
broker could not be listed; nothing was synced for it)}. Exit codes: 0, 2, 4,
5 (NO_ACCOUNTS, LEDGER_CORRUPT, API_ERROR), 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import normalize  # noqa: E402
from second_opinion import ledger, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

_MAX_HISTORY_DAYS = 729


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"sync-broker.py: {message}")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="sync-broker.py", add_help=False)
        p.add_argument("--account", action="append", default=None)
        p.add_argument("--partial", action="store_true")
        p.add_argument("--start", default=None)
        p.add_argument("--end", default=None)
        ns = p.parse_args(args)
        start = ns.start or (date.today() - timedelta(days=_MAX_HISTORY_DAYS)).isoformat()
        if normalize.parse_date(start) != start or (ns.end and normalize.parse_date(ns.end) != ns.end):
            raise InvalidInput("--start/--end must be YYYY-MM-DD")

        hub = router.load()
        hub.partial = ns.partial
        accounts = hub.list_accounts()
        if not accounts:
            raise ApiError("no open brokerage accounts are connected; use the connect skill", code="NO_ACCOUNTS")
        if ns.account:
            known = {a["account_id"] for a in accounts}
            unknown = [w for w in ns.account if w not in known]
            if unknown:
                raise hub.unknown_account_error(unknown)
            accounts = [a for a in accounts if a["account_id"] in set(ns.account)]

        book = ledger.load()
        report = []
        for a in accounts:
            aid = a["account_id"]
            items = hub.list_transactions(aid, start=start, end=ns.end, count=10**6)["transactions"]
            if items:
                result = normalize.run_normalize({"source": "snaptrade", "account_id": aid, "rows": items})
                added, dupes = ledger.merge(book, result["transactions"], source=f"snaptrade:{aid}")
                skipped = len(result["skipped"])
            else:
                added = dupes = skipped = 0
            report.append({"account_id": aid, "fetched": len(items), "imported": added, "duplicates": dupes, "skipped_count": skipped})
        saved = ledger.save(book)
        return {"start": start, "end": ns.end, "accounts": report, "ledger_path": str(saved), "ledger_count": len(book["transactions"]), "flags": hub.unavailable_flags()}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
