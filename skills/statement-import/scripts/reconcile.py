#!/usr/bin/env python3
"""Usage: reconcile.py [--account ACCOUNT_ID ...] [--partial]

Compare per-symbol share counts in the local ledger (``ledger.json`` under
the plugin data dir) against live SnapTrade positions. It reads the broker;
it changes nothing. With no --account every open connected account is
reconciled; --account scopes the run (repeatable). Ledger rows whose
account_id is not a connected account are reported under ``unassigned``
instead of reconciled; rows for connected accounts outside the --account
selection are simply not reconciled.

Per account, ledger units per symbol = +units for BUY/TRANSFER_IN,
-units for SELL/TRANSFER_OUT, and units x split_ratio for SPLIT entries that
carry a parsed ratio (entries without one contribute 0 — forward-compatible
with old ledgers). Symbols netted to 0 in the ledger with no broker position
are skipped. status is ``matched`` (|ledger - broker| <= max(0.01, 1% of the
broker's units)), ``quantity_mismatched``, ``ledger_only`` (no broker
position) or ``broker_only`` (no ledger rows); the absent side is null and
``diff`` uses 0 for it. stdin is unused.

Output: {sources, accounts: [{account_id, symbols: [{symbol, ledger_units,
broker_units, diff, status, likely_cause?}]}], unassigned?: {symbols: [...]},
summary: {matched, quantity_mismatched, ledger_only, broker_only}, flags
(BROKER_UNAVAILABLE when a broker could not be listed; its accounts are not
reconciled and its ledger rows show as unassigned), hint?}.
Exit codes: 0, 2 (unknown account), 4 (credentials missing), 5 (NO_ACCOUNTS,
API_ERROR), 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import ledger, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

_TOLERANCE_ABS = 0.01
_TOLERANCE_REL = 0.01
_ADD = {"BUY", "TRANSFER_IN"}
_SUB = {"SELL", "TRANSFER_OUT"}
_LIKELY_CAUSE = {
    "quantity_mismatched": "missing import rows, an unrecorded split, or a transfer",
    "ledger_only": "sold before the ledger's coverage, or a stale/manual import",
    "broker_only": "acquired before the import window (CSV gap or pre-two-year history)",
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"reconcile.py: {message}")


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def _position_symbol(pos: dict[str, Any]) -> str | None:
    """Ticker from a SnapTrade position, unwrapping the nested symbol object."""
    sym = pos.get("symbol")
    for _ in range(2):
        if isinstance(sym, dict):
            sym = sym.get("symbol")
    return sym.upper() if isinstance(sym, str) and sym else None


def _entry_units(entry: dict[str, Any]) -> float | None:
    kind = entry.get("type")
    if kind == "SPLIT":
        ratio = entry.get("split_ratio")
        units = entry.get("units")
        if isinstance(ratio, (int, float)) and units:
            return float(units) * float(ratio)
        return 0.0
    if kind in _ADD:
        return float(entry.get("units") or 0.0)
    if kind in _SUB:
        return -float(entry.get("units") or 0.0)
    return None  # dividends, cash and unknown types hold no shares


def _ledger_units_by_symbol(rows: list[dict[str, Any]]) -> dict[str, float]:
    units: dict[str, float] = {}
    for t in rows:
        sym = str(t.get("symbol") or "").upper()
        delta = _entry_units(t)
        if not sym or delta is None:
            continue
        units[sym] = units.get(sym, 0.0) + delta
    return units


def _broker_units_by_symbol(hub: Any, account_id: str) -> dict[str, float]:
    units: dict[str, float] = {}
    for pos in hub.get_portfolio(account_id)["positions"] or []:
        sym = _position_symbol(pos)
        u = float(pos.get("units") or 0)
        if not sym or u <= 0:
            continue
        units[sym] = units.get(sym, 0.0) + u
    return units


def _reconcile(ledger_map: dict[str, float], broker_map: dict[str, float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym in sorted(set(ledger_map) | set(broker_map)):
        l_units = ledger_map.get(sym)
        b_units = broker_map.get(sym)
        if not l_units and b_units is None:
            continue  # netted to 0 in the ledger with nothing at the broker: consistent
        if l_units is not None and b_units is not None:
            diff = l_units - b_units
            tolerance = max(_TOLERANCE_ABS, _TOLERANCE_REL * abs(b_units))
            status = "matched" if abs(diff) <= tolerance else "quantity_mismatched"
        elif b_units is None:
            diff, status = l_units, "ledger_only"
        else:
            diff, status, l_units = -b_units, "broker_only", None
        row = {
            "symbol": sym,
            "ledger_units": _round(l_units),
            "broker_units": _round(b_units),
            "diff": _round(diff),
            "status": status,
        }
        if status != "matched":
            row["likely_cause"] = _LIKELY_CAUSE[status]
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="reconcile.py", add_help=False)
        p.add_argument("--account", action="append", default=None)
        p.add_argument("--partial", action="store_true")
        ns = p.parse_args(args)

        hub = router.load()
        hub.partial = ns.partial
        all_accounts = hub.list_accounts()
        accounts = all_accounts
        if not accounts:
            raise ApiError("no open brokerage accounts are connected; use the connect skill", code="NO_ACCOUNTS")
        if ns.account:
            known = {a["account_id"] for a in accounts}
            unknown = [w for w in ns.account if w not in known]
            if unknown:
                raise hub.unknown_account_error(unknown)
            accounts = [a for a in accounts if a["account_id"] in set(ns.account)]

        rows = ledger.load()["transactions"]
        connected = {a["account_id"] for a in all_accounts}
        report: list[dict[str, Any]] = []
        summary = {"matched": 0, "quantity_mismatched": 0, "ledger_only": 0, "broker_only": 0}
        for a in accounts:
            aid = a["account_id"]
            l_map = _ledger_units_by_symbol([t for t in rows if t.get("account_id") == aid])
            symbols = _reconcile(l_map, _broker_units_by_symbol(hub, aid))
            for s in symbols:
                summary[s["status"]] += 1
            report.append({"account_id": aid, "symbols": symbols})

        result: dict[str, Any] = {
            "sources": {"ledger": "ledger.json", "positions": router.holdings_source(all_accounts)},
            "accounts": report,
            "summary": summary,
            "flags": hub.unavailable_flags(),
        }
        unassigned = _ledger_units_by_symbol(
            [t for t in rows if t.get("account_id") and t["account_id"] not in connected]
        )
        leftover = [{"symbol": s, "ledger_units": _round(u)} for s, u in sorted(unassigned.items()) if u]
        if leftover:
            result["unassigned"] = {"symbols": leftover}
        if not rows:
            result["hint"] = "the ledger is empty: run import-csv.py <file.csv> or sync-broker.py first"
        return result

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
