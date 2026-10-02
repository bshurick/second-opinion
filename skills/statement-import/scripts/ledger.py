#!/usr/bin/env python3
"""Usage: ledger.py [--symbol SYM] [--type TYPE] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--limit N] [--summary] [--verify]

Show what is in the local ledger (``ledger.json`` under the plugin data dir):
summary counts plus the matching transactions (newest last, default limit
200). --summary omits the transactions. stdin is unused.

--verify adds a read-only health check and never writes:
- orphan account ids: ledger account ids no connected broker lists (skipped,
  with the broker's own hint, when credentials are missing or a login is
  needed; a broker that could not be listed contributes its cached ids, or
  the check is skipped and a BROKER_UNAVAILABLE flag is added, so its rows
  are never called orphans);
- near-duplicate rows: same (account_id, date, type, symbol, units) with
  amounts within $0.01 — the exact-match dedup misses these; up to 25 pairs;
- date gaps: between an account's earliest and latest ledger dates, any
  window longer than 45 days with no rows for that account (longest first,
  up to 25);
- DUPLICATE_ACROSS_ACCOUNTS: identical (date, type, symbol, units, amount)
  rows filed under two different account ids — the same history imported
  twice under two ids for one brokerage account (up to 25, count included).
ok is true when there are no orphans, near-duplicates, gaps or
cross-account duplicates.

Output: {ledger_path, count, date_range, types, accounts, symbols, imports,
filtered, transactions, hint?, verify?: {ok, orphan_accounts:
[{account_id, rows}], near_duplicates, near_duplicate_count, gaps,
gap_count, duplicate_across_accounts, duplicate_across_accounts_count,
flags, skipped?, hint?}}. Exit codes: 0, 2, 5 (LEDGER_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import ledger, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ConfigError, InvalidInput  # noqa: E402

_GAP_DAYS = 45
_DUP_TOLERANCE = 0.01
_MAX_VERIFY_ROWS = 25


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"ledger.py: {message}")


def _verify(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"orphan_accounts": [], "near_duplicates": [], "gaps": [], "duplicate_across_accounts": [], "flags": []}
    hub = None
    try:
        hub = router.load()
        hub.partial = True  # an orphan check runs with whatever brokers answer
        connected = {a["account_id"] for a in hub.list_accounts()}
    except ConfigError as e:
        out["skipped"] = "brokerage credentials missing or a login is required (see hint)"
        out["hint"] = e.extra.get("hint")
        connected = None
    if hub is not None and hub.broker_errors and connected is not None:
        # A broker that could not be listed owns account ids we cannot see: its
        # ledger rows are not orphans. Use its cached ids, or skip the check.
        out["flags"] = hub.unavailable_flags()
        failed = {e["broker"] for e in hub.broker_errors}
        cached = {
            aid for aid, row in (hub.registry.load() if hub.registry is not None else {}).items()
            if isinstance(row, dict) and row.get("broker") in failed
        }
        if cached:
            connected |= cached
        else:
            connected = None
            out["skipped"] = f"orphan check skipped: {', '.join(sorted(failed))} could not be listed and no account ids are cached"
    if connected is not None:
        orphans: dict[str, int] = {}
        for t in rows:
            aid = t.get("account_id")
            if aid and aid not in connected:
                orphans[str(aid)] = orphans.get(str(aid), 0) + 1
        out["orphan_accounts"] = [{"account_id": k, "rows": n} for k, n in sorted(orphans.items())]

    groups: dict[tuple, list[dict[str, Any]]] = {}
    for t in rows:
        k = (t.get("account_id"), t["date"], t["type"], t.get("symbol"), t.get("units"))
        groups.setdefault(k, []).append(t)
    pairs: list[dict[str, Any]] = []
    for k in sorted(groups, key=lambda k: (str(k[1]), str(k[2]), str(k[3]), str(k[0]), str(k[4]))):
        group = groups[k]
        for i in range(len(group) - 1):
            for j in range(i + 1, len(group)):
                amounts = (group[i].get("amount"), group[j].get("amount"))
                if not all(isinstance(a, (int, float)) and not isinstance(a, bool) for a in amounts):
                    continue
                if abs(float(amounts[0]) - float(amounts[1])) > _DUP_TOLERANCE + 1e-9:
                    continue
                pairs.append(
                    {
                        "account_id": k[0],
                        "date": k[1],
                        "type": k[2],
                        "symbol": k[3],
                        "units": k[4],
                        "amounts": [round(float(amounts[0]), 4), round(float(amounts[1]), 4)],
                        "source_ids": [group[i].get("source_id"), group[j].get("source_id")],
                    }
                )
    out["near_duplicate_count"] = len(pairs)
    out["near_duplicates"] = pairs[:_MAX_VERIFY_ROWS]

    dates_by_account: dict[str, set[str]] = {}
    for t in rows:
        aid = t.get("account_id")
        if aid:
            dates_by_account.setdefault(str(aid), set()).add(t["date"])
    gaps: list[dict[str, Any]] = []
    for aid, dates in sorted(dates_by_account.items()):
        ordered = sorted(dates)
        for d1, d2 in zip(ordered, ordered[1:]):
            days = (date.fromisoformat(d2) - date.fromisoformat(d1)).days
            if days > _GAP_DAYS:
                gaps.append({"account_id": aid, "start": d1, "end": d2, "days": days})
    gaps.sort(key=lambda g: (-g["days"], g["account_id"]))
    out["gap_count"] = len(gaps)
    out["gaps"] = gaps[:_MAX_VERIFY_ROWS]

    # The same activity imported under two account ids — what happens when an
    # account synced through SnapTrade is later served directly.
    across: dict[tuple, set[str]] = {}
    for t in rows:
        aid = t.get("account_id")
        if not aid:
            continue
        across.setdefault((t["date"], t["type"], t.get("symbol"), t.get("units"), t.get("amount")), set()).add(str(aid))
    cross = [
        {"date": k[0], "type": k[1], "symbol": k[2], "units": k[3], "amount": k[4], "account_ids": sorted(ids)}
        for k, ids in sorted(across.items(), key=lambda kv: tuple(str(x) for x in kv[0]))
        if len(ids) > 1
    ]
    out["duplicate_across_accounts_count"] = len(cross)
    out["duplicate_across_accounts"] = cross[:_MAX_VERIFY_ROWS]
    out["ok"] = not (out["orphan_accounts"] or pairs or gaps or cross)
    return out


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="ledger.py", add_help=False)
        p.add_argument("--symbol")
        p.add_argument("--type", dest="kind")
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--limit", type=int, default=200)
        p.add_argument("--summary", action="store_true")
        p.add_argument("--verify", action="store_true")
        ns = p.parse_args(args)
        book = ledger.load()
        rows = book["transactions"]
        result = {"ledger_path": str(ledger.ledger_path()), **ledger.summary(rows), "imports": book["imports"][-20:]}
        if not rows:
            result["hint"] = "the ledger is empty: run import-csv.py <file.csv> or sync-broker.py first"
        if ns.verify:
            result["verify"] = _verify(rows)
        if ns.summary:
            return result
        matched = ledger.filter(rows, symbol=ns.symbol, kind=ns.kind, start=ns.start, end=ns.end)
        result["filtered"] = len(matched)
        result["transactions"] = matched[-ns.limit :] if ns.limit > 0 else matched
        return result

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
