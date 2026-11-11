#!/usr/bin/env python3
"""Usage: record-statement.py [--dry-run] [--replace] < statement.json
       record-statement.py accounts

Record one card or loan statement summary in ``statements.json`` under the plugin data dir.
stdin is one JSON object: either ``{"account": {...}, "statement": {...}}`` (the account block
creates the account on first use and updates name/issuer/last4/credit_limit later; kind cannot
change once statements exist) or a bare snapshot carrying ``account_id`` for an account that
already exists.

Card snapshots (kind card): period_end, previous_balance, payments, purchases, new_balance,
minimum_payment, due_date, apr required; credits, cash_advances, balance_transfers, fees,
interest default to 0; period_start, credit_limit (defaults to the account's), note optional.
Loan snapshots (mortgage, auto, student, heloc, other): period_end, previous_balance,
principal_paid, interest_paid, new_balance, payment_due, due_date, apr required; escrow and
fees default to 0; period_start, remaining_term_months, note optional. Rates are decimals.

Checks, in order, each exit 2 with its code: INVALID_ACCOUNT, MISSING_FIELD, BALANCE_MISMATCH
(card: previous - payments - credits + purchases + cash_advances + balance_transfers + fees +
interest = new, within $0.01; loan: previous - principal_paid = new; carries expected/got/
delta), DUPLICATE_STATEMENT (same account and period_end; --replace overwrites), then sanity
(apr in [0, 1], minimum non-negative, loan balance non-negative, due_date on or after
period_end). CHAIN_GAP (previous snapshot's new_balance differs from this previous_balance)
and OVER_LIMIT are returned in ``flags``, never rejections. --dry-run runs every check and
writes nothing. ``accounts`` lists the register with each account's latest period and balance.
Exit codes: 0, 2, 5 (STATEMENTS_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import output, statements  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_LAST4 = re.compile(r"^\d{4}$")

CARD_REQUIRED = ("period_end", "previous_balance", "payments", "purchases", "new_balance", "minimum_payment", "due_date", "apr")
CARD_ZERO = ("credits", "cash_advances", "balance_transfers", "fees", "interest")
LOAN_REQUIRED = ("period_end", "previous_balance", "principal_paid", "interest_paid", "new_balance", "payment_due", "due_date", "apr")
LOAN_ZERO = ("escrow", "fees")
CARD_ORDER = ("account_id", "period_start", "period_end", "previous_balance", "payments", "credits", "purchases", "cash_advances",
              "balance_transfers", "fees", "interest", "new_balance", "minimum_payment", "due_date", "apr", "credit_limit", "note", "recorded_at")
LOAN_ORDER = ("account_id", "period_start", "period_end", "previous_balance", "principal_paid", "interest_paid", "escrow", "fees",
              "new_balance", "payment_due", "due_date", "apr", "remaining_term_months", "credit_limit", "note", "recorded_at")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"record-statement.py: {message}")


def _r2(v: float) -> float:
    return round(float(v), 2)


def _money(obj: dict, field: str, *, required: bool, default: float | None = None, code: str = "MISSING_FIELD") -> float | None:
    v = obj.get(field)
    if v is None:
        if required:
            raise InvalidInput(f"{field} is required", code=code)
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise InvalidInput(f"{field} must be a number", code=code)
    return float(v)


def _day(obj: dict, field: str, *, required: bool) -> str | None:
    v = obj.get(field)
    if v is None:
        if required:
            raise InvalidInput(f"{field} is required", code="MISSING_FIELD")
        return None
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError as exc:
        raise InvalidInput(f"{field} must be YYYY-MM-DD, got {v!r}", code="MISSING_FIELD") from exc


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    try:
        obj = json.loads(raw) if raw.strip() else None
    except ValueError as exc:
        raise InvalidInput(f"stdin must be JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise InvalidInput("stdin must be a JSON object")
    return obj


def _resolve_account(book: dict, block: dict | None, account_id: str | None) -> dict:
    if block is not None:
        if not isinstance(block, dict):
            raise InvalidInput("account must be an object", code="INVALID_ACCOUNT")
        aid = block.get("id") or account_id
        if not isinstance(aid, str) or not _SLUG.match(aid):
            raise InvalidInput(f"account id must be a kebab-case slug, got {aid!r}", code="INVALID_ACCOUNT")
        kind = block.get("kind")
        existing = book["accounts"].get(aid)
        if existing is None and kind not in statements.KINDS:
            raise InvalidInput(f"account kind must be one of {', '.join(statements.KINDS)}, got {kind!r}", code="INVALID_ACCOUNT")
        if kind is not None and kind not in statements.KINDS:
            raise InvalidInput(f"account kind must be one of {', '.join(statements.KINDS)}, got {kind!r}", code="INVALID_ACCOUNT")
        last4 = block.get("last4", existing.get("last4") if existing else None)
        if last4 is not None and not (isinstance(last4, str) and _LAST4.match(last4)):
            raise InvalidInput("last4 must be exactly four digits (never the full account number)", code="INVALID_ACCOUNT")
        limit = _money(block, "credit_limit", required=False, default=existing.get("credit_limit") if existing else None, code="INVALID_ACCOUNT")
        if existing and kind and kind != existing["kind"] and any(s["account_id"] == aid for s in book["statements"]):
            raise InvalidInput(f"account {aid} has statements recorded as kind {existing['kind']!r}; kind cannot change", code="INVALID_ACCOUNT")
        account = {
            "id": aid,
            "name": str(block.get("name") or (existing or {}).get("name") or aid),
            "issuer": block.get("issuer", (existing or {}).get("issuer")),
            "kind": kind or existing["kind"],
            "last4": last4,
            "credit_limit": _r2(limit) if limit is not None else None,
            "added": (existing or {}).get("added") or date.today().isoformat(),
        }
        book["accounts"][aid] = account
        return account
    if not isinstance(account_id, str) or account_id not in book["accounts"]:
        raise InvalidInput(f"unknown account {account_id!r}: pass an account block to create it", code="INVALID_ACCOUNT")
    return book["accounts"][account_id]


def _build_snapshot(account: dict, stmt: dict) -> tuple[dict, bool, tuple[str, ...]]:
    """Parse and identity-check the snapshot (INVALID_ACCOUNT is the caller's job; this covers
    MISSING_FIELD and BALANCE_MISMATCH). Sanity checks and the OVER_LIMIT flag are deferred to
    ``_sanity_check`` so the caller can run DUPLICATE_STATEMENT in between, per the spec order."""
    kind = account["kind"]
    is_card = kind == "card"
    required, zero, order = (CARD_REQUIRED, CARD_ZERO, CARD_ORDER) if is_card else (LOAN_REQUIRED, LOAN_ZERO, LOAN_ORDER)
    snap: dict = {"account_id": account["id"]}
    snap["period_start"] = _day(stmt, "period_start", required=False)
    snap["period_end"] = _day(stmt, "period_end", required=True)
    snap["due_date"] = _day(stmt, "due_date", required=True)
    for f in required:
        if f in ("period_end", "due_date", "apr"):
            continue
        snap[f] = _r2(_money(stmt, f, required=True))
    snap["apr"] = _money(stmt, "apr", required=True)  # a rate, not money: kept unrounded
    for f in zero:
        snap[f] = _r2(_money(stmt, f, required=False, default=0.0))
    if is_card:
        limit = _money(stmt, "credit_limit", required=False, default=account.get("credit_limit"))
        snap["credit_limit"] = _r2(limit) if limit is not None else None
        expected = (snap["previous_balance"] - snap["payments"] - snap["credits"] + snap["purchases"] + snap["cash_advances"]
                    + snap["balance_transfers"] + snap["fees"] + snap["interest"])
    else:
        snap["credit_limit"] = _r2(account["credit_limit"]) if account.get("credit_limit") is not None else None
        term = stmt.get("remaining_term_months")
        if term is not None and (isinstance(term, bool) or not isinstance(term, int) or term < 0):
            raise InvalidInput("remaining_term_months must be a non-negative integer", code="MISSING_FIELD")
        snap["remaining_term_months"] = term
        expected = snap["previous_balance"] - snap["principal_paid"]
    snap["note"] = stmt.get("note") if isinstance(stmt.get("note"), str) else None
    expected = _r2(expected)
    if round(abs(expected - snap["new_balance"]), 2) > 0.01:  # rounded: 1775.56 - 1775.55 is 0.010000000000218 in floats
        raise InvalidInput(
            f"new_balance {snap['new_balance']} does not reconcile: the summary lines give {expected} (delta {_r2(snap['new_balance'] - expected)})",
            code="BALANCE_MISMATCH", expected=expected, got=snap["new_balance"], delta=_r2(snap["new_balance"] - expected),
        )
    return snap, is_card, order


def _sanity_check(snap: dict, is_card: bool, revolving: bool) -> list[dict]:
    minimum = snap["minimum_payment"] if is_card else snap["payment_due"]
    if minimum < 0:
        raise InvalidInput(f"{'minimum_payment' if is_card else 'payment_due'} must be non-negative")
    if not is_card and snap["new_balance"] < 0:
        raise InvalidInput("new_balance must be non-negative for a loan")
    if not 0.0 <= snap["apr"] <= 1.0:
        raise InvalidInput(f"apr must be a decimal between 0 and 1 (24.24% is 0.2424), got {snap['apr']}")
    if snap["due_date"] < snap["period_end"]:
        raise InvalidInput(f"due_date {snap['due_date']} is before period_end {snap['period_end']}")
    flags: list[dict] = []
    if revolving and snap["credit_limit"] and snap["new_balance"] > snap["credit_limit"]:
        flags.append({"flag": "OVER_LIMIT", "credit_limit": snap["credit_limit"], "new_balance": snap["new_balance"]})
    return flags


def _chain_gap(book: dict, snap: dict) -> dict | None:
    earlier = [s for s in book["statements"] if s["account_id"] == snap["account_id"] and s["period_end"] < snap["period_end"]]
    if not earlier:
        return None
    prev = max(earlier, key=lambda s: s["period_end"])
    if round(abs(float(prev["new_balance"]) - snap["previous_balance"]), 2) > 0.01:
        return {"flag": "CHAIN_GAP", "previous_new_balance": prev["new_balance"], "this_previous_balance": snap["previous_balance"],
                "previous_period_end": prev["period_end"]}
    return None


def _accounts(book: dict) -> dict:
    rows = []
    for aid in sorted(book["accounts"]):
        a = book["accounts"][aid]
        mine = [s for s in book["statements"] if s["account_id"] == aid]
        last = statements.latest(book, aid)
        rows.append({**a, "statements": len(mine), "latest_period_end": last["period_end"] if last else None,
                     "latest_balance": last["new_balance"] if last else None})
    return {"accounts": rows, "statements_path": str(statements.statements_path())}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="record-statement.py", add_help=False)
        p.add_argument("command", nargs="?", choices=["accounts"])
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--replace", action="store_true")
        ns = p.parse_args(args)
        book = statements.load()
        if ns.command == "accounts":
            return _accounts(book)
        obj = _read_stdin()
        block = obj.get("account") if "statement" in obj or "account" in obj else None
        stmt = obj.get("statement", obj) if "statement" in obj else obj
        if not isinstance(stmt, dict):
            raise InvalidInput("statement must be an object")
        account = _resolve_account(book, block, stmt.get("account_id"))
        snap, is_card, order = _build_snapshot(account, stmt)
        existing = statements.find(book, snap["account_id"], snap["period_end"])
        if existing and not ns.replace:
            raise InvalidInput(
                f"a statement for {snap['account_id']} ending {snap['period_end']} is already recorded; pass --replace to overwrite it",
                code="DUPLICATE_STATEMENT", existing=existing,
            )
        flags = _sanity_check(snap, is_card, account["kind"] in statements.REVOLVING_KINDS)
        snap["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        snap = {k: snap[k] for k in order}
        gap = _chain_gap(book, snap)
        if gap:
            flags.insert(0, gap)
        earlier = [s["period_end"] for s in book["statements"] if s["account_id"] == snap["account_id"] and s["period_end"] < snap["period_end"]]
        result = {"account": account, "snapshot": snap, "flags": flags, "previous_period_end": max(earlier) if earlier else None}
        if ns.dry_run:
            return {"dry_run": True, "valid": True, **result}
        replaced = statements.put(book, snap, replace=ns.replace)
        path = statements.save(book)
        mine = [s for s in book["statements"] if s["account_id"] == snap["account_id"]]
        return {**result, "replaced": replaced, "statements_for_account": len(mine), "statements_path": str(path)}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
