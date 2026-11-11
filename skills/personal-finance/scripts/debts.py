#!/usr/bin/env python3
"""Usage: debts.py [--as-of YYYY-MM-DD] [--stale-days N] [--utilization-warn X]
       debts.py --history ACCOUNT_ID

The debt picture from ``statements.json`` under the plugin data dir (populated by
record-statement.py): per-account latest balance, APR, minimum, due date, utilization, interest
this period and trailing twelve months, movement, flags; totals; and ``debt_input``, shaped for
the personal-finance skill's finance.py ``debt`` action. ``--history`` prints one account's
snapshots in period order with per-period balance, interest, fees, payments, purchases and the
running change. Runs debtpicture.py; no network, no stdin. Exit codes: 0, 2, 4
(CONFIG_MISSING: nothing recorded yet), 5 (STATEMENTS_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import debtpicture  # noqa: E402
from second_opinion import output, statements  # noqa: E402
from second_opinion.errors import ConfigError, InvalidInput  # noqa: E402

_SETUP_HINT = "no statements recorded yet: run record-statement.py with a statement summary first"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"debts.py: {message}")


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _history(book: dict, account_id: str) -> dict:
    account = book["accounts"].get(account_id)
    if account is None:
        raise InvalidInput(f"unknown account {account_id!r}; run record-statement.py accounts to list them")
    is_card = account.get("kind") == "card"
    rows = sorted((s for s in book["statements"] if s["account_id"] == account_id), key=lambda s: s["period_end"])
    out = []
    prev = None
    for s in rows:
        payments = s.get("payments") if is_card else sum(float(s.get(f) or 0.0) for f in ("principal_paid", "interest_paid", "escrow"))
        out.append({
            "period_end": s["period_end"],
            "balance": _r2(s["new_balance"]),
            "interest": _r2(s.get("interest") if is_card else s.get("interest_paid")),
            "fees": _r2(s.get("fees") or 0.0),
            "payments": _r2(payments),
            "purchases": _r2(s.get("purchases")) if is_card else None,
            "minimum": _r2(s.get("minimum_payment") if is_card else s.get("payment_due")),
            "due_date": s.get("due_date"),
            "apr": s.get("apr"),
            "change": _r2(float(s["new_balance"]) - float(prev["new_balance"])) if prev else None,
        })
        prev = s
    return {"account": account, "statements": out, "statements_path": str(statements.statements_path())}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="debts.py", add_help=False)
        p.add_argument("--as-of", default=None)
        p.add_argument("--stale-days", type=int, default=45)
        p.add_argument("--utilization-warn", type=float, default=0.30)
        p.add_argument("--history", default=None, metavar="ACCOUNT_ID")
        ns = p.parse_args(args)
        path = statements.statements_path()
        if not path.is_file():
            raise ConfigError("no statements file", hint=_SETUP_HINT, path=str(path))
        book = statements.load(path)
        if ns.history:
            return _history(book, ns.history)
        params = {"accounts": book["accounts"], "statements": book["statements"], "stale_days": ns.stale_days, "utilization_warn": ns.utilization_warn}
        if ns.as_of:
            params["as_of"] = ns.as_of
        try:
            picture = debtpicture.run_debtpicture(params)
        except (ValueError, TypeError) as exc:
            raise InvalidInput(str(exc)) from exc
        return {**picture, "statements_path": str(path)}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
