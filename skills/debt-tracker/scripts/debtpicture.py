"""debt-tracker: the debt picture from recorded statement snapshots.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python debtpicture.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {"as_of": "2026-09-11",             # optional, default today
     "accounts": {"<id>": {"id", "name", "issuer", "kind", "last4",
                           "credit_limit", "added"}, ...},
     "statements": [ <snapshot>, ... ], # record-statement.py's stored shape
     "stale_days": 45,                  # optional
     "utilization_warn": 0.30}          # optional

``kind`` is one of card, mortgage, auto, student, heloc, other; card and
heloc are revolving. Card snapshots carry previous_balance, payments,
credits, purchases, cash_advances, balance_transfers, fees, interest,
new_balance, minimum_payment, due_date, apr, credit_limit. Loan snapshots
carry previous_balance, principal_paid, interest_paid, escrow, fees,
new_balance, payment_due, due_date, apr, remaining_term_months. Every
snapshot has account_id and period_end (YYYY-MM-DD). heloc is revolving
but is shaped like a loan snapshot: it uses the loan fields above (not
minimum_payment/purchases) plus a credit_limit (statement or account
level) for utilization and OVER_LIMIT.

Output JSON contract (stdout)::

    {"as_of": ...,
     "accounts": [                      # sorted by id
       {"id", "name", "kind", "issuer", "period_end", "statement_age_days",
        "balance", "apr", "minimum_payment", "due_date", "days_to_due",
        "credit_limit", "utilization",   # balance / limit for revolving, else null
        "interest_this_period", "fees_this_period",
        "interest_ttm", "fees_ttm", "periods_in_ttm",   # snapshots within 365 days before as_of
        "change_vs_prior", "change_vs_3_back",           # null with too few snapshots
        "payments_this_period", "purchases_this_period", # purchases: cards only
        "paid_in_full", "minimum_only",                  # cards only, else null
        "monthly_interest_run_rate",                     # balance x apr / 12
        "remaining_term_months", "flags": [...]}],
     "totals": {"total_debt", "revolving", "installment", "weighted_apr",
                "revolving_weighted_apr", "credit_limit_total", "utilization",
                "interest_ttm", "interest_ttm_revolving",
                "monthly_interest_run_rate", "minimum_payments_total",
                "next_due": {"account_id", "due_date", "amount"} | null,
                "change_vs_prior"},
     "debt_input": {"action": "debt", "debts": [{"name", "balance", "apr",
                    "min_payment"}], "as_of"},   # finance.py's debt action, unchanged
     "flags": ["STALE:<id>", ...],
     "history": [{"account_id", "period_end", "balance", "interest", "fees",
                  "payments", "purchases", "minimum", "due_date", "apr",
                  "change"}, ...],        # every snapshot, by account id then period_end
     "assumptions": {...}}

Per-account flags, in this order: NO_STATEMENTS, STALE (statement older
than stale_days), PAST_DUE (due_date before as_of on the latest statement),
OVER_LIMIT (revolving-account balance above its limit), HIGH_UTILIZATION
(above utilization_warn), MINIMUM_ONLY (the latest two card payments each
within $1 of the prior statement's minimum), MINIMUM_BELOW_INTEREST (the
minimum payment does not cover the monthly interest run rate, i.e.
minimum <= balance x apr / 12; the debt would never amortize at that
payment). paid_in_full is payments >= previous_balance. weighted_apr is
balance-weighted over positive balances. next_due is the earliest due
date on or after as_of, else null. debt_input lists accounts with a
positive balance and a positive minimum, excluding any account flagged
MINIMUM_BELOW_INTEREST (finance.py's debt action raises on a minimum
that never amortizes). debt_input's apr is the unrounded statement APR;
the account row's apr field is rounded to 4 dp for display. For loan
kinds, debt_input's min_payment is payment_due minus escrow (floored at
0, since escrow is tax and insurance, not debt service); the account
row's minimum_payment keeps the full payment_due. When two accounts
share a display name, debt_input disambiguates every debt sharing that
name as "name (id)"; account rows keep name unchanged. history is the
per-statement series behind the rows (a loan's payments is principal +
interest + escrow, purchases null; change is the balance move since the
account's prior snapshot). Money 2 dp, ratios 4 dp.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

REVOLVING = ("card", "heloc")
FLAG_ORDER = (
    "NO_STATEMENTS",
    "STALE",
    "PAST_DUE",
    "OVER_LIMIT",
    "HIGH_UTILIZATION",
    "MINIMUM_ONLY",
    "MINIMUM_BELOW_INTEREST",
)


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _date(raw: object, field: str) -> date:
    if not isinstance(raw, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be a YYYY-MM-DD string") from exc


def _num(snapshot: dict, field: str, default: float | None = None) -> float | None:
    v = snapshot.get(field, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{field} must be a number")
    return float(v)


def _minimum(snapshot: dict) -> float | None:
    if "minimum_payment" in snapshot:
        return _num(snapshot, "minimum_payment")
    return _num(snapshot, "payment_due")


def _minimum_only(snapshot: dict, prior: dict | None) -> bool:
    if prior is None:
        return False
    prior_min = _minimum(prior) or 0.0
    return prior_min > 0 and abs((_num(snapshot, "payments") or 0.0) - prior_min) <= 1.0


def _account_row(
    account: dict, snaps: list[dict], as_of: date, stale_days: int, warn: float
) -> dict:
    kind = account.get("kind") or "other"
    revolving = kind in REVOLVING
    base = {
        "id": account["id"],
        "name": account.get("name") or account["id"],
        "kind": kind,
        "issuer": account.get("issuer"),
    }
    if not snaps:
        empty = dict.fromkeys(
            (
                "period_end",
                "statement_age_days",
                "balance",
                "apr",
                "minimum_payment",
                "due_date",
                "days_to_due",
                "credit_limit",
                "utilization",
                "interest_this_period",
                "fees_this_period",
                "interest_ttm",
                "fees_ttm",
                "change_vs_prior",
                "change_vs_3_back",
                "payments_this_period",
                "purchases_this_period",
                "paid_in_full",
                "minimum_only",
                "monthly_interest_run_rate",
                "remaining_term_months",
            )
        )
        return {**base, **empty, "periods_in_ttm": 0, "flags": ["NO_STATEMENTS"]}

    latest = snaps[-1]
    prior = snaps[-2] if len(snaps) >= 2 else None
    three_back = snaps[-4] if len(snaps) >= 4 else None
    period_end = _date(latest.get("period_end"), "period_end")
    due = _date(latest.get("due_date"), "due_date") if latest.get("due_date") else None
    balance = _num(latest, "new_balance", 0.0) or 0.0
    apr = _num(latest, "apr")
    limit = _num(latest, "credit_limit") if revolving else None
    if revolving and limit is None:
        limit = _num(account, "credit_limit")
    utilization = balance / limit if revolving and limit else None
    interest_field = "interest" if kind == "card" else "interest_paid"
    window_start = as_of - timedelta(days=365)
    in_window = [
        s for s in snaps if window_start < _date(s.get("period_end"), "period_end") <= as_of
    ]
    if kind == "card":
        payments = _num(latest, "payments", 0.0)
        purchases = _num(latest, "purchases", 0.0)
        prev_balance = _num(latest, "previous_balance", 0.0) or 0.0
        paid_in_full: bool | None = (payments or 0.0) >= prev_balance - 0.01
        minimum_only: bool | None = _minimum_only(latest, prior)
    else:
        payments = sum(
            (_num(latest, f, 0.0) or 0.0) for f in ("principal_paid", "interest_paid", "escrow")
        )
        purchases = None
        paid_in_full = None
        minimum_only = None

    flags: list[str] = []
    age = (as_of - period_end).days
    if age > stale_days:
        flags.append("STALE")
    days_to_due = (due - as_of).days if due else None
    if days_to_due is not None and days_to_due < 0:
        flags.append("PAST_DUE")
    if revolving and limit and balance > limit:
        flags.append("OVER_LIMIT")
    if utilization is not None and utilization > warn:
        flags.append("HIGH_UTILIZATION")
    prior_prior = snaps[-3] if len(snaps) >= 3 else None
    if kind == "card" and minimum_only and prior is not None and _minimum_only(prior, prior_prior):
        flags.append("MINIMUM_ONLY")
    minimum_val = _minimum(latest)
    if kind == "card":
        debt_min = minimum_val
    else:
        escrow = _num(latest, "escrow", 0.0) or 0.0
        debt_min = None if minimum_val is None else max(0.0, minimum_val - escrow)
    run_rate = balance * apr / 12 if apr is not None else None
    minimum_below_interest = (
        balance > 0
        and apr is not None
        and debt_min is not None
        and debt_min > 0
        and debt_min <= run_rate
    )
    if minimum_below_interest:
        flags.append("MINIMUM_BELOW_INTEREST")

    return {
        **base,
        "period_end": latest["period_end"],
        "statement_age_days": age,
        "balance": _r2(balance),
        "apr": _r4(apr),
        "minimum_payment": _r2(minimum_val),
        "due_date": latest.get("due_date"),
        "days_to_due": days_to_due,
        "credit_limit": _r2(limit),
        "utilization": _r4(utilization),
        "interest_this_period": _r2(_num(latest, interest_field, 0.0)),
        "fees_this_period": _r2(_num(latest, "fees", 0.0)),
        "interest_ttm": _r2(sum((_num(s, interest_field, 0.0) or 0.0) for s in in_window)),
        "fees_ttm": _r2(sum((_num(s, "fees", 0.0) or 0.0) for s in in_window)),
        "periods_in_ttm": len(in_window),
        "change_vs_prior": (
            _r2(balance - (_num(prior, "new_balance", 0.0) or 0.0)) if prior else None
        ),
        "change_vs_3_back": (
            _r2(balance - (_num(three_back, "new_balance", 0.0) or 0.0)) if three_back else None
        ),
        "payments_this_period": _r2(payments),
        "purchases_this_period": _r2(purchases),
        "paid_in_full": paid_in_full,
        "minimum_only": minimum_only,
        "monthly_interest_run_rate": _r2(run_rate),
        "remaining_term_months": latest.get("remaining_term_months"),
        "flags": sorted(flags, key=FLAG_ORDER.index),
        "_raw": {
            "balance": balance,
            "apr": apr,
            "limit": limit,
            "revolving": revolving,
            "minimum": minimum_val,
            "debt_min": debt_min,
            "interest_ttm": sum((_num(s, interest_field, 0.0) or 0.0) for s in in_window),
            "run_rate": run_rate if run_rate is not None else 0.0,
            "due": due,
            "change": balance - (_num(prior, "new_balance", 0.0) or 0.0) if prior else None,
        },
    }


def _totals(rows: list[dict], as_of: date) -> dict:
    live = [r for r in rows if r["_raw"] is not None]
    balances = [(r["_raw"]["balance"], r["_raw"]["apr"], r["_raw"]["revolving"]) for r in live]
    total = sum(b for b, _, _ in balances)
    revolving = sum(b for b, _, rev in balances if rev)
    weighted = [(b, a) for b, a, _ in balances if b > 0 and a is not None]
    weighted_rev = [(b, a) for b, a, rev in balances if b > 0 and a is not None and rev]
    limits = [r["_raw"]["limit"] for r in live if r["_raw"]["revolving"] and r["_raw"]["limit"]]
    limit_total = sum(limits)
    changes = [r["_raw"]["change"] for r in live if r["_raw"]["change"] is not None]
    due_rows = [r for r in live if r["_raw"]["due"] is not None and r["_raw"]["due"] >= as_of]
    next_due = None
    if due_rows:
        first = min(due_rows, key=lambda r: (r["_raw"]["due"], r["id"]))
        next_due = {
            "account_id": first["id"],
            "due_date": first["due_date"],
            "amount": _r2(first["_raw"]["minimum"]),
        }
    return {
        "total_debt": _r2(total),
        "revolving": _r2(revolving),
        "installment": _r2(total - revolving),
        "weighted_apr": (
            _r4(sum(b * a for b, a in weighted) / sum(b for b, _ in weighted)) if weighted else None
        ),
        "revolving_weighted_apr": (
            _r4(sum(b * a for b, a in weighted_rev) / sum(b for b, _ in weighted_rev))
            if weighted_rev
            else None
        ),
        "credit_limit_total": _r2(limit_total) if limits else None,
        "utilization": _r4(revolving / limit_total) if limit_total else None,
        "interest_ttm": _r2(sum(r["_raw"]["interest_ttm"] for r in live)),
        "interest_ttm_revolving": _r2(
            sum(r["_raw"]["interest_ttm"] for r in live if r["_raw"]["revolving"])
        ),
        "monthly_interest_run_rate": _r2(sum(r["_raw"]["run_rate"] for r in live)),
        "minimum_payments_total": _r2(sum((r["_raw"]["minimum"] or 0.0) for r in live)),
        "next_due": next_due,
        "change_vs_prior": _r2(sum(changes)) if changes else None,
    }


def _history_row(kind: str, s: dict, prev: dict | None) -> dict:
    is_card = kind == "card"
    if is_card:
        payments = _num(s, "payments", 0.0)
    else:
        payments = sum(
            (_num(s, f, 0.0) or 0.0) for f in ("principal_paid", "interest_paid", "escrow")
        )
    balance = _num(s, "new_balance", 0.0) or 0.0
    return {
        "account_id": s["account_id"],
        "period_end": s["period_end"],
        "balance": _r2(balance),
        "interest": _r2(_num(s, "interest" if is_card else "interest_paid", 0.0)),
        "fees": _r2(_num(s, "fees", 0.0)),
        "payments": _r2(payments),
        "purchases": _r2(_num(s, "purchases", 0.0)) if is_card else None,
        "minimum": _r2(_minimum(s)),
        "due_date": s.get("due_date"),
        "apr": _r4(_num(s, "apr")),
        "change": _r2(balance - (_num(prev, "new_balance", 0.0) or 0.0)) if prev else None,
    }


def run_debtpicture(params: dict) -> dict:
    """Build the picture; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    as_of = _date(params["as_of"], "as_of") if params.get("as_of") is not None else date.today()
    accounts = params.get("accounts")
    if not isinstance(accounts, dict):
        raise ValueError("accounts must be an object keyed by account id")
    statements = params.get("statements")
    if not isinstance(statements, list):
        raise ValueError("statements must be a list")
    stale_days = int(params.get("stale_days", 45))
    warn = float(params.get("utilization_warn", 0.30))
    by_account: dict[str, list[dict]] = {aid: [] for aid in accounts}
    for s in statements:
        if not isinstance(s, dict) or s.get("account_id") not in by_account:
            bad_id = s.get("account_id") if isinstance(s, dict) else s
            raise ValueError(f"unknown account in statements: {bad_id!r}")
        _date(s.get("period_end"), "period_end")
        by_account[s["account_id"]].append(s)
    rows = []
    history = []
    for aid in sorted(accounts):
        account = {**accounts[aid], "id": aid}
        snaps = sorted(by_account[aid], key=lambda s: s["period_end"])
        row = _account_row(account, snaps, as_of, stale_days, warn)
        row.setdefault("_raw", None)
        rows.append(row)
        kind = account.get("kind") or "other"
        history.extend(_history_row(kind, s, p) for s, p in zip(snaps, [None, *snaps[:-1]]))
    totals = _totals(rows, as_of)
    debts_source = [
        r
        for r in rows
        if r["_raw"] is not None
        and r["_raw"]["balance"] > 0
        and (r["_raw"]["debt_min"] or 0.0) > 0
        and r["_raw"]["apr"] is not None
        and "MINIMUM_BELOW_INTEREST" not in r["flags"]
    ]
    name_counts: dict[str, int] = {}
    for r in debts_source:
        name_counts[r["name"]] = name_counts.get(r["name"], 0) + 1
    debts = [
        {
            "name": r["name"] if name_counts[r["name"]] == 1 else f"{r['name']} ({r['id']})",
            "balance": r["balance"],
            "apr": r["_raw"]["apr"],
            "min_payment": _r2(r["_raw"]["debt_min"]),
        }
        for r in debts_source
    ]
    flags = [f"{f}:{r['id']}" for r in rows for f in r["flags"]]
    for r in rows:
        r.pop("_raw", None)
    return {
        "as_of": as_of.isoformat(),
        "accounts": rows,
        "totals": totals,
        "debt_input": {"action": "debt", "debts": debts, "as_of": as_of.isoformat()},
        "flags": flags,
        "history": history,
        "assumptions": {
            "stale_days": stale_days,
            "utilization_warn": warn,
            "run_rate": "balance x apr / 12 on the latest statement balance",
            "ttm": "snapshots with period_end within the 365 days before as_of",
            "loan_min_payment": (
                "payment_due minus escrow; escrow is tax and insurance, not debt service"
            ),
        },
    }


def main() -> None:
    """Read JSON params from stdin, write the result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_debtpicture(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
