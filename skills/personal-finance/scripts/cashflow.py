#!/usr/bin/env python3
"""Usage: cashflow.py

Monthly cash flow implied by the local ledger (``ledger.json`` under the
plugin data dir, the same file statement-import's ``import-csv.py`` /
``sync-broker.py`` populate). No SnapTrade calls, no Yahoo calls, no stdin
-- this only reads what is already on disk.

DEPOSIT/DIVIDEND/INTEREST rows are inflows; WITHDRAWAL/FEE rows are
outflows (amounts are taken by absolute value, so sign in the ledger does
not matter). Every other row type (BUY, SELL, SPLIT, ...) is ignored here.

Output: {months: [{month: "YYYY-MM", inflow, outflow, net}, ...] ascending,
only months with at least one classified row;
avg_monthly_inflow, avg_monthly_outflow: mean over those months, null when
there are none; savings_rate: (total inflow - total outflow) / total
inflow over the whole window, 4 dp, null when total inflow is 0;
cash: {avg_balance, note} | null}.

``cash.avg_balance`` is the mean, across the same set of months, of each
month's cumulative ending balance -- the running signed sum of every
classified cash row in date order (deposits/dividends/interest positive,
withdrawals/fees negative), evaluated at the end of each month. It is
implied entirely from ledger cash rows: investment gains/losses and price
changes are never in it (see the ``note``). ``cash`` is ``null`` -- not a
failed run -- when the ledger has no DEPOSIT/DIVIDEND/INTEREST/WITHDRAWAL/
FEE rows at all (e.g. an all-trades ledger).

Exit codes: 0, 2 (unexpected arguments), 4 (CONFIG_MISSING -- no ledger
file yet; same setup hint as ledger.py's), 5 (LEDGER_EMPTY -- the ledger
file exists but has zero transactions; LEDGER_CORRUPT bubbles up unchanged
from ``ledger.load()`` for an unreadable/malformed file), 6 (Python deps
missing). Money 2 dp, savings_rate 4 dp.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import ledger, output  # noqa: E402
from second_opinion.errors import ApiError, ConfigError, InvalidInput  # noqa: E402

_INFLOW_TYPES = {"DEPOSIT", "DIVIDEND", "INTEREST"}
_OUTFLOW_TYPES = {"WITHDRAWAL", "FEE"}
_LEDGER_SETUP_HINT = "the ledger is empty: run import-csv.py <file.csv> or sync-broker.py first"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"cashflow.py: {message}")


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _signed(row: dict) -> float | None:
    """Signed cash-flow amount for one ledger row, or None if it is not a cash row."""
    kind = str(row.get("type") or "").upper()
    amount = row.get("amount")
    if amount is None or isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return None
    if kind in _INFLOW_TYPES:
        return abs(float(amount))
    if kind in _OUTFLOW_TYPES:
        return -abs(float(amount))
    return None


def build_cashflow(rows: list[dict]) -> dict:
    """Pure computation over ledger transaction rows; used directly by tests."""
    cash_rows: list[tuple[str, float]] = []
    for t in rows:
        signed = _signed(t)
        if signed is None:
            continue
        d = str(t.get("date") or "")[:10]
        if not d:
            continue
        cash_rows.append((d, signed))
    cash_rows.sort(key=lambda r: r[0])

    monthly: dict[str, dict[str, float]] = {}
    for d, signed in cash_rows:
        bucket = monthly.setdefault(d[:7], {"inflow": 0.0, "outflow": 0.0})
        if signed >= 0:
            bucket["inflow"] += signed
        else:
            bucket["outflow"] += -signed

    months = [
        {
            "month": m,
            "inflow": _r2(v["inflow"]),
            "outflow": _r2(v["outflow"]),
            "net": _r2(v["inflow"] - v["outflow"]),
        }
        for m, v in sorted(monthly.items())
    ]
    total_inflow = sum(v["inflow"] for v in monthly.values())
    total_outflow = sum(v["outflow"] for v in monthly.values())
    avg_inflow = _r2(total_inflow / len(months)) if months else None
    avg_outflow = _r2(total_outflow / len(months)) if months else None
    savings_rate = _r4((total_inflow - total_outflow) / total_inflow) if total_inflow > 0 else None

    cash = None
    if cash_rows:
        running = 0.0
        ending_by_month: dict[str, float] = {}
        for d, signed in cash_rows:
            running += signed
            ending_by_month[d[:7]] = running
        avg_balance = sum(ending_by_month.values()) / len(ending_by_month)
        cash = {
            "avg_balance": _r2(avg_balance),
            "note": "implied from ledger cash rows only; investment gains and price changes are not in this number",
        }

    return {
        "months": months,
        "avg_monthly_inflow": avg_inflow,
        "avg_monthly_outflow": avg_outflow,
        "savings_rate": savings_rate,
        "cash": cash,
    }


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="cashflow.py", add_help=False)
        p.parse_args(args)
        path = ledger.ledger_path()
        if not path.is_file():
            raise ConfigError(
                "no ledger found; nothing has been imported yet", hint=_LEDGER_SETUP_HINT
            )
        book = ledger.load(path)
        rows = book.get("transactions") or []
        if not rows:
            raise ApiError(
                "ledger has no transactions yet", code="LEDGER_EMPTY", hint=_LEDGER_SETUP_HINT
            )
        return build_cashflow(rows)

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
