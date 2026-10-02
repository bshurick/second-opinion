"""spending: reports over normalized spending rows. Reads one JSON object from stdin, writes one to
stdout (``python spendreport.py < input.json``); exit 0, or 2 with ``{"error": "..."}``.

Input: {"as_of" (default today), "accounts": {id: {id, name, kind}}, "transactions": [rows] (with
"id"), "report": month/range/recurring/changes/cashflow/uncategorized/search/merchants/drill, plus
"month" (YYYY-MM; month/changes; default the latest month with data before as_of's, else as_of's
with PARTIAL_MONTH), "compare_months" (default 3), "threshold" (changes, default 0.25), "min_count"
(recurring, default 3; annual needs 2), "months" (cashflow, default 6), "limit" (uncategorized,
default 25), "text"/"start"/"end" (search/range/drill; search needs text), "by" (range:
category/merchant/account/detail), "top" (merchants, default 25), "items" (explode first on
month/range/merchants/changes/uncategorized, default False; drill default True), "path" (drill,
"" or "Category[/detail/segments]").

A spend row excludes Income/Transfer; its spend amount is -amount, so refunds net out. Money 2dp,
ratios 4dp. ``avg_prior`` averages the ``compare_months`` prior months with spend (0 for a silent
month, null if never seen). ``changes`` flags |delta| over threshold x avg_prior and $25 (or, with
no prior, $25+ and ``new: true``), with ``explained_by`` (top 5 charges); ``missing_recurring`` are
due weekly/monthly series uncharged that month, ``new_recurring`` reached count that month.
Recurring needs 3+ charges (annual: 2) at a steady cadence/amount. Cash flow counts income only
from checking/savings rows; card-only is null with NO_INCOME_DATA. ``uncategorized`` groups
category_source "none" rows. ``explode`` turns items into their own rows (category_source "none"
if the item's own category is Uncategorized, else "item"; remainder keeps the parent's; an item
inherits the parent's detail only when its own category matches, else its own detail or None);
``drill`` walks the category/detail tree, Uncategorized included, each transaction carrying
``in_node`` (its rows' spend amount inside the node, refunds negative, like ``amount``). Recurring
detection (``new_recurring``/``missing_recurring``) always runs on un-exploded rows even with
``items`` set. ``month`` also carries ``transactions`` (the month's spend rows, exploded when
``items`` is set, each with id, date, merchant, description, amount (spend, refunds negative),
category, detail, account_id, item_name, has_items, parent_id), ``months`` (cashflow's per-month
rows for up to the 12 months ending with the month) and ``recurring`` (the recurring series on
un-exploded rows through the month's end, report_recurring's shape). Flags: NO_INCOME_DATA,
UNCATEGORIZED_HIGH (>10% of spend), PARTIAL_MONTH, SINGLE_ACCOUNT.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import date, timedelta

NON_SPEND = ("Income", "Transfer")
_ITEM_REPORTS = ("month", "changes", "range", "merchants", "uncategorized")
TAXONOMY_SPEND = (
    "Groceries", "Dining", "Coffee", "Transport", "Fuel", "Auto", "Housing", "Utilities",
    "Subscriptions", "Shopping", "Amazon", "Health", "Insurance", "Travel", "Entertainment",
    "Education", "Kids", "Pets", "Gifts and Charity", "Personal Care", "Fees and Interest",
    "Taxes and Government",
)  # fmt: skip
_CADENCE = (
    ("weekly", 5, 9, 52),
    ("monthly", 26, 35, 12),
    ("quarterly", 80, 100, 4),
    ("annual", 350, 380, 1),
)


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v) + 0.0, 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _parse_day(raw: object, field: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


def _parse_month(raw: object) -> str:
    text = str(raw or "")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise ValueError("month must be YYYY-MM")
    return text


def _month_of(d: str) -> str:
    return d[:7]


def _month_bounds(ym: str) -> tuple[date, date]:
    y, mo = int(ym[:4]), int(ym[5:])
    start = date(y, mo, 1)
    end = date(y + (mo == 12), (mo % 12) + 1, 1) - timedelta(days=1)
    return start, end


def _is_spend(t: dict) -> bool:
    return not t.get("transfer") and t.get("category") not in NON_SPEND


def _spend(t: dict) -> float:
    return -float(t["amount"])


def _in_window(t: dict, start: str | None, end: str | None) -> bool:
    return (start is None or t["date"] >= start) and (end is None or t["date"] <= end)


def _detail_segments(t: dict) -> list[str]:
    """The row's detail path, minus a leading segment that repeats its own category."""
    segments = [s for s in (t.get("detail") or "").split("/") if s]
    if segments and segments[0] == t.get("category"):
        segments = segments[1:]
    return segments


def explode(rows: list[dict]) -> list[dict]:
    """Turn a spend row's ``items`` into their own rows (carrying the parent's amount/category/
    detail as ``parent_*``), plus a remainder row for the rest; an item row's category_source is
    "none" if its category is Uncategorized else "item", and the remainder keeps the parent's."""
    out: list[dict] = []
    for i, t in enumerate(rows):
        items = t.get("items") or []
        if not items or not _is_spend(t):
            out.append(t)
            continue
        base = {k: v for k, v in t.items() if k != "items"}
        pid = t.get("id") or ("row", i)
        parent = {"parent_amount": t["amount"], "parent_category": t.get("category")}
        parent["parent_detail"] = t.get("detail")
        total = 0.0
        for it in items:
            total += float(it["amount"])
            row = {**base, **parent, "amount": float(it["amount"]), "category": it["category"]}
            inherits = it["category"] == t.get("category")
            row["detail"] = (it.get("detail") or t.get("detail")) if inherits else it.get("detail")
            row["item_name"], row["item"] = it.get("name"), True
            row["parent_id"], row["has_items"] = pid, True
            row["category_source"] = "none" if it["category"] == "Uncategorized" else "item"
            out.append(row)
        remainder = round(float(t["amount"]) - total, 2)
        if abs(remainder) >= 0.005:
            row = {**base, **parent, "amount": remainder, "parent_id": pid}
            out.append({**row, "has_items": True})
    return out


def _months_with_spend(rows: list[dict]) -> list[str]:
    return sorted({_month_of(t["date"]) for t in rows if _is_spend(t)})


def _is_income(t: dict, accounts: dict) -> bool:
    kind = (accounts.get(t.get("account_id")) or {}).get("kind")
    return t.get("category") == "Income" and kind in ("checking", "savings")


def _share(amount: float, total: float) -> float | None:
    return _r4(amount / total) if total > 0 else None


def _default_month(rows: list[dict], as_of: date) -> str:
    current = as_of.isoformat()[:7]
    prior = [m for m in _months_with_spend(rows) if m < current]
    return prior[-1] if prior else current


def _sum_by(rows: list[dict], key) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in rows:
        k = key(t)
        out[k] = out.get(k, 0.0) + _spend(t)
    return out


def _count_by(rows: list[dict], key) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in rows:
        k = key(t)
        out[k] = out.get(k, 0) + 1
    return out


def _income_total(rows: list[dict], accounts: dict) -> float:
    return sum(
        float(t["amount"]) for t in rows if _is_income(t, accounts) and float(t["amount"]) > 0
    )


def _avg_prior(rows: list[dict], month: str, n: int, key) -> dict[str, float | None]:
    # list[-0:] is the whole list, not none, so n == 0 needs an explicit guard.
    pm = [m for m in _months_with_spend(rows) if m < month][-n:] if n > 0 else []
    if not pm:
        return {}
    per_month = {
        m: _sum_by([t for t in rows if _is_spend(t) and _month_of(t["date"]) == m], key) for m in pm
    }
    keys = {k for totals in per_month.values() for k in totals}
    return {k: sum(per_month[m].get(k, 0.0) for m in pm) / len(pm) for k in keys}


def _flags(rows, accounts, month, as_of, spend_total, uncategorized) -> list[str]:
    """NO_INCOME_DATA, UNCATEGORIZED_HIGH, PARTIAL_MONTH, SINGLE_ACCOUNT."""
    flags = []
    if not any(_is_income(t, accounts) for t in rows):
        flags.append("NO_INCOME_DATA")
    if spend_total > 0 and uncategorized / spend_total > 0.10:
        flags.append("UNCATEGORIZED_HIGH")
    if month and month == as_of.isoformat()[:7]:
        in_month = [t["date"] for t in rows if _month_of(t["date"]) == month]
        _, end = _month_bounds(month)
        if not in_month or date.fromisoformat(max(in_month)) < end - timedelta(days=3):
            flags.append("PARTIAL_MONTH")
    if len(accounts) < 2:
        flags.append("SINGLE_ACCOUNT")
    return flags


def _tx_key(t: dict, i: int):
    """Transaction identity: ``parent_id`` or ``id`` when set, else a per-row sentinel so id-less
    rows (``run_spendnormalize`` output; the store's ``merge`` assigns ``id``) don't collapse onto
    ``None``. ``explode`` stamps ``parent_id`` on every item row, so an itemized row counts once."""
    return t.get("parent_id") or t.get("id") or ("row", i)


def _merchant_rows(rows: list[dict]) -> list[dict]:
    """Group by merchant; ``count`` is distinct transactions (``parent_id`` or ``id``), not rows."""
    groups: dict[str, dict] = {}
    for i, t in enumerate(rows):
        default = {"merchant": t["merchant"], "amount": 0.0, "ids": set(), "categories": set()}
        g = groups.setdefault(t["merchant"], default)
        g["amount"] += _spend(t)
        g["ids"].add(_tx_key(t, i))
        g["categories"].add(t["category"])
    out = sorted(groups.values(), key=lambda g: (-g["amount"], g["merchant"]))
    return [
        {"merchant": g["merchant"], "amount": _r2(g["amount"]), "count": len(g["ids"])}
        | {"categories": sorted(g["categories"])}
        for g in out
    ]


def _largest_row(t):
    row = {"date": t["date"], "merchant": t["merchant"], "amount": _r2(_spend(t))}
    row["category"], row["account_id"] = t["category"], t["account_id"]
    row["item_name"] = t.get("item_name")
    return row


def _tx_row(t: dict) -> dict:
    """One transaction (or exploded item/remainder row) for ``month``'s ``transactions``."""
    pid = t.get("parent_id")
    row = {"id": t.get("id") if isinstance(t.get("id"), str) else None, "date": t["date"]}
    row["merchant"], row["description"] = t["merchant"], t.get("description")
    row["amount"], row["category"] = _r2(_spend(t)), t["category"]
    row["detail"], row["account_id"] = t.get("detail"), t.get("account_id")
    row["item_name"] = t.get("item_name")
    row["has_items"] = bool(t.get("has_items") or t.get("items"))
    row["parent_id"] = pid if isinstance(pid, str) else None
    return row


def report_month(
    rows: list[dict], accounts: dict, month: str, n: int, as_of: date, raw_rows=None
) -> dict:
    """``raw_rows`` (un-exploded, default ``rows``) drives ``recurring``, unaffected by items."""
    in_month = [t for t in rows if _month_of(t["date"]) == month]
    spend_rows = [t for t in in_month if _is_spend(t)]
    spend_total = sum(_spend(t) for t in spend_rows)
    income_total = _income_total(in_month, accounts)
    net = income_total - spend_total
    by_cat = _sum_by(spend_rows, lambda t: t["category"])
    prior = _avg_prior(rows, month, n, lambda t: t["category"])
    counts = _count_by(spend_rows, lambda t: t["category"])
    by_category = []
    for cat, amount in sorted(by_cat.items(), key=lambda kv: (-kv[1], kv[0])):
        avg = prior.get(cat)
        delta = amount - avg if avg is not None else None
        row = {"category": cat, "amount": _r2(amount), "share": _share(amount, spend_total)}
        row["avg_prior"], row["delta"], row["transactions"] = _r2(avg), _r2(delta), counts[cat]
        row["delta_pct"] = _r4(delta / avg) if delta is not None and avg else None
        by_category.append(row)
    start, _ = _month_bounds(month)
    lookback = (start - timedelta(days=365)).isoformat()
    seen_before = {t["merchant"] for t in rows if lookback <= t["date"] < start.isoformat()}
    has_prior_data = any(t["date"] < start.isoformat() for t in rows)
    merchants = _merchant_rows(spend_rows)
    new_merchants = (
        [g["merchant"] for g in merchants if g["merchant"] not in seen_before]
        if has_prior_data
        else []
    )
    largest = sorted(
        (t for t in spend_rows if _spend(t) > 0), key=lambda t: (-_spend(t), t["date"])
    )[:10]
    uncategorized = [t for t in spend_rows if t.get("category_source") == "none"]
    unc_amount = sum(_spend(t) for t in uncategorized)
    out = {"month": month, "spend_total": _r2(spend_total)}
    out["income_total"], out["net"] = _r2(income_total), _r2(net)
    out["savings_rate"] = _r4(net / income_total) if income_total > 0 else None
    transfers_total = sum(abs(float(t["amount"])) for t in in_month if t.get("transfer"))
    out["transfers_total"] = _r2(transfers_total)
    out["by_category"] = by_category
    out["top_merchants"] = merchants[:10]
    out["largest"] = [_largest_row(t) for t in largest]
    out["new_merchants"] = new_merchants
    refunds_total = sum(float(t["amount"]) for t in spend_rows if float(t["amount"]) > 0)
    out["refunds_total"] = _r2(refunds_total)
    out["fees_and_interest"] = _r2(by_cat.get("Fees and Interest", 0.0))
    out["uncategorized"] = {"count": len(uncategorized), "amount": _r2(unc_amount)}
    out["compare_months"] = n
    ordered = sorted(spend_rows, key=lambda t: (t["date"], t["merchant"], t.get("id") or ""))
    out["transactions"] = [_tx_row(t) for t in ordered]
    has_income = any(_is_income(t, accounts) for t in rows)
    flow_months = sorted({_month_of(t["date"]) for t in rows if not t.get("transfer")})
    flow_months = [m for m in flow_months if m <= month][-12:]
    out["months"] = _flow_rows(rows, accounts, flow_months, has_income)[0]
    end_iso = _month_bounds(month)[1].isoformat()
    history = [t for t in (rows if raw_rows is None else raw_rows) if t["date"] <= end_iso]
    out["recurring"] = [
        {k: v for k, v in s.items() if k != "reached_on"} for s in recurring_series(history, 3)
    ]
    out["flags"] = _flags(rows, accounts, month, as_of, spend_total, unc_amount)
    return out


def recurring_series(rows: list[dict], min_count: int) -> list[dict]:
    charges: dict[str, list[dict]] = {}
    for t in rows:
        if _is_spend(t) and float(t["amount"]) < 0:
            charges.setdefault(t["merchant"], []).append(t)
    series = []
    for merchant, txs in charges.items():
        txs.sort(key=lambda t: t["date"])
        dates = [date.fromisoformat(t["date"]) for t in txs]
        if len(dates) < 2:
            continue
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        gap = statistics.median(gaps)
        cadence = next(
            ((name, per_year) for name, lo, hi, per_year in _CADENCE if lo <= gap <= hi), None
        )
        if cadence is None:
            continue
        needed = 2 if cadence[0] == "annual" else min_count
        if len(txs) < needed:
            continue
        amounts = [_spend(t) for t in txs]
        typical = statistics.median(amounts)
        if any(abs(a - typical) > max(0.25 * typical, 2.0) for a in amounts):
            continue
        first, last = _spend(txs[0]), _spend(txs[-1])
        row = {"merchant": merchant, "category": sorted({t["category"] for t in txs})[0]}
        row["cadence"], row["count"] = cadence[0], len(txs)
        row["first_date"], row["last_date"] = txs[0]["date"], txs[-1]["date"]
        row["first_amount"], row["last_amount"] = _r2(first), _r2(last)
        row["typical_amount"] = _r2(typical)
        row["creep_pct"] = _r4((last - first) / first) if first else None
        row["annual_cost"] = _r2(typical * cadence[1])
        row["next_expected"] = (dates[-1] + timedelta(days=int(round(gap)))).isoformat()
        row["account_ids"] = sorted({t["account_id"] for t in txs})
        row["reached_on"] = txs[needed - 1]["date"]
        series.append(row)
    series.sort(key=lambda s: (-s["annual_cost"], s["merchant"]))
    return series


def report_recurring(rows: list[dict], min_count: int) -> dict:
    series = recurring_series(rows, min_count)
    for s in series:
        s.pop("reached_on", None)
    annual = sum(s["annual_cost"] for s in series)
    totals = {"monthly_equivalent": _r2(annual / 12), "annual": _r2(annual), "count": len(series)}
    return {"series": series, "totals": totals, "min_count": min_count}


def _moves(in_month, rows, month, n, threshold, key):
    totals, prior = _sum_by(in_month, key), _avg_prior(rows, month, n, key)
    out = []
    for k, amount in totals.items():
        avg = prior.get(k)
        is_new = avg is None
        delta = None if is_new else amount - avg
        if is_new and amount < 25:
            continue
        if not is_new and (abs(delta) < 25 or abs(delta) <= threshold * avg):
            continue
        entry = {"amount": _r2(amount), "avg_prior": _r2(avg), "delta": _r2(delta), "new": is_new}
        entry["delta_pct"] = _r4(delta / avg) if delta is not None and avg else None
        charges = sorted(
            (t for t in in_month if key(t) == k and _spend(t) > 0), key=lambda t: -_spend(t)
        )[:5]
        entry["explained_by"] = [
            {"date": t["date"], "merchant": t["merchant"], "amount": _r2(_spend(t))}
            | {"description": t["description"]}
            for t in charges
        ]
        out.append((k, entry))
    out.sort(
        key=lambda p: (-(abs(p[1]["delta"]) if p[1]["delta"] is not None else p[1]["amount"]), p[0])
    )
    return out


def report_changes(rows, accounts, month, threshold, n, as_of, raw_rows=None) -> dict:
    """``raw_rows`` (un-exploded, default ``rows``) drives recurring, unaffected by items."""
    in_month = [t for t in rows if _month_of(t["date"]) == month and _is_spend(t)]
    start, end = _month_bounds(month)
    start_iso, end_iso = start.isoformat(), end.isoformat()
    history = [t for t in (rows if raw_rows is None else raw_rows) if t["date"] <= end_iso]
    series = recurring_series(history, 3)
    missing, new_recurring = [], []
    for s in series:
        due = s["cadence"] in ("weekly", "monthly") and start_iso <= s["next_expected"] <= end_iso
        charged = any(
            t["merchant"] == s["merchant"] and _month_of(t["date"]) == month for t in in_month
        )
        if due and not charged:
            row = {"merchant": s["merchant"], "expected": s["next_expected"]}
            missing.append({**row, "typical_amount": s["typical_amount"], "cadence": s["cadence"]})
        if _month_of(s["reached_on"]) == month:
            new_recurring.append({k: v for k, v in s.items() if k != "reached_on"})
    spend_total = sum(_spend(t) for t in in_month)
    unc_total = sum(_spend(t) for t in in_month if t.get("category_source") == "none")
    out = {"month": month, "threshold": threshold, "compare_months": n}
    out["categories"] = [
        {"category": k, **v}
        for k, v in _moves(in_month, rows, month, n, threshold, lambda t: t["category"])
    ]
    out["merchants"] = [
        {"merchant": k, **v}
        for k, v in _moves(in_month, rows, month, n, threshold, lambda t: t["merchant"])
    ]
    out["missing_recurring"] = missing
    out["new_recurring"] = new_recurring
    out["flags"] = _flags(rows, accounts, month, as_of, spend_total, unc_total)
    return out


def _flow_rows(rows: list[dict], accounts: dict, months: list[str], has_income: bool) -> tuple:
    """One cash-flow row per month (income null without income data, spend, transfers, net,
    savings_rate) plus the unrounded spends, incomes and rates behind them."""
    out_rows, incomes, spends, rates = [], [], [], []
    for m in months:
        in_m = [t for t in rows if _month_of(t["date"]) == m]
        income = _income_total(in_m, accounts) if has_income else None
        spend = sum(_spend(t) for t in in_m if _is_spend(t))
        net = income - spend if income is not None else None
        rate = net / income if income else None
        row = {"month": m, "income": _r2(income), "spend": _r2(spend)}
        transfers = [float(t["amount"]) for t in in_m if t.get("transfer")]
        row["transfers_out"] = _r2(-sum(a for a in transfers if a < 0))
        row["transfers_in"] = _r2(sum(a for a in transfers if a > 0))
        row["net"], row["savings_rate"] = _r2(net), _r4(rate)
        out_rows.append(row)
        spends.append(spend)
        if income is not None:
            incomes.append(income)
        if rate is not None:
            rates.append(rate)
    return out_rows, spends, incomes, rates


def report_cashflow(rows: list[dict], accounts: dict, months_n: int, as_of: date) -> dict:
    current = as_of.isoformat()[:7]
    all_months = sorted({_month_of(t["date"]) for t in rows if not t.get("transfer")})
    months = [m for m in all_months if m < current][-months_n:]
    has_income = any(_is_income(t, accounts) for t in rows)
    out_rows, spends, incomes, rates = _flow_rows(rows, accounts, months, has_income)
    spend_total = sum(spends)
    unc_total = sum(
        _spend(t)
        for t in rows
        if _is_spend(t) and t.get("category_source") == "none" and _month_of(t["date"]) in months
    )
    out = {"months": out_rows}
    out["avg_monthly_income"] = (
        _r2(sum(incomes) / len(out_rows)) if out_rows and has_income else None
    )
    out["avg_monthly_outflow"] = _r2(spend_total / len(out_rows)) if out_rows else None
    out["avg_savings_rate"] = _r4(sum(rates) / len(rates)) if rates else None
    out["flags"] = _flags(rows, accounts, None, as_of, spend_total, unc_total)
    return out


def report_uncategorized(rows: list[dict], limit: int) -> dict:
    spend_rows = [t for t in rows if _is_spend(t)]
    unc = [t for t in spend_rows if t.get("category_source") == "none"]
    groups: dict[str, dict] = {}
    for t in unc:
        default = {"merchant": t["merchant"], "amount": 0.0, "count": 0, "last_date": t["date"]}
        g = groups.setdefault(t["merchant"], default)
        g["amount"] += _spend(t)
        g["count"] += 1
        g["last_date"] = max(g["last_date"], t["date"])
    merchants = sorted(groups.values(), key=lambda g: (-g["amount"], g["merchant"]))[:limit]
    total = sum(_spend(t) for t in unc)
    spend_total = sum(_spend(t) for t in spend_rows)
    out_merchants = [{**g, "amount": _r2(g["amount"]), "suggested": None} for g in merchants]
    out = {"merchants": out_merchants, "total": _r2(total), "count": len(unc)}
    out["share_of_spend"] = _r4(total / spend_total) if spend_total else None
    return out


def report_search(rows: list[dict], text: str, start: str | None, end: str | None) -> dict:
    needle = text.lower()
    hits = [
        t
        for t in rows
        if _in_window(t, start, end)
        and any(needle in (t.get(f) or "").lower() for f in ("description", "merchant"))
    ]
    hits.sort(key=lambda t: (t["date"], t["account_id"]))
    running = 0.0
    out = []
    for t in hits:
        running += float(t["amount"])
        row = {"date": t["date"], "account_id": t["account_id"], "merchant": t["merchant"]}
        row["description"], row["amount"] = t["description"], _r2(t["amount"])
        row["category"], row["transfer"] = t["category"], bool(t.get("transfer"))
        row["running_total"] = _r2(running)
        out.append(row)
    total = _r2(sum(float(t["amount"]) for t in hits))
    return {"query": text, "count": len(out), "total": total, "rows": out}


def report_merchants(rows: list[dict], top: int, start: str | None, end: str | None) -> dict:
    spend_rows = [t for t in rows if _is_spend(t) and _in_window(t, start, end)]
    spend_total = sum(_spend(t) for t in spend_rows)
    months = sorted({_month_of(t["date"]) for t in spend_rows})[-6:]
    out = []
    for g in _merchant_rows(spend_rows)[:top]:
        mine = [t for t in spend_rows if t["merchant"] == g["merchant"]]
        cats = _count_by(mine, lambda t: t["category"])
        by_month = _sum_by(
            [t for t in mine if _month_of(t["date"]) in months], lambda t: _month_of(t["date"])
        )
        row = {"merchant": g["merchant"], "amount": g["amount"], "count": g["count"]}
        row["share"] = _r4(g["amount"] / spend_total) if spend_total else None
        row["category"] = max(cats.items(), key=lambda kv: (kv[1], kv[0]))[0]
        row["months"] = {m: _r2(v) for m, v in sorted(by_month.items())}
        out.append(row)
    return {"merchants": out, "spend_total": _r2(spend_total), "start": start, "end": end}


def report_range(rows: list[dict], accounts: dict, start: str, end: str, by: str) -> dict:
    in_window = [t for t in rows if _in_window(t, start, end)]
    spend_rows = [t for t in in_window if _is_spend(t)]
    keys = {"category": lambda t: t["category"], "merchant": lambda t: t["merchant"]}
    keys["account"], keys["detail"] = (
        lambda t: t["account_id"],
        lambda t: t.get("detail") or "(none)",
    )
    key = keys[by]
    totals, counts = _sum_by(spend_rows, key), _count_by(spend_rows, key)
    spend_total = sum(totals.values())
    income_total = _income_total(in_window, accounts)
    by_list = [
        {**{"key": k, "amount": _r2(v), "share": _share(v, spend_total)}, "count": counts[k]}
        for k, v in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    out = {"start": start, "end": end, "by_key": by, "spend_total": _r2(spend_total)}
    out["income_total"] = _r2(income_total)
    out["net"] = _r2(income_total - spend_total)
    out["by"] = by_list
    return out


def _drill_key(t: dict, depth: int) -> str:
    segments = _detail_segments(t)
    return segments[depth] if len(segments) > depth else "(none)"


def report_drill(rows, accounts, path, start, end, as_of: date) -> dict:
    """Walk the category/detail tree at ``path`` ("" root, one segment a category incl.
    Uncategorized, more its detail path); ``rows`` exploded or not per the caller's ``items``."""
    segments = [s.strip() for s in (path or "").split("/") if s.strip()]
    if segments and segments[0] not in TAXONOMY_SPEND + ("Uncategorized",):
        raise ValueError("path must start with a spend category")
    window = [t for t in rows if _is_spend(t) and _in_window(t, start, end)]
    spend_total = sum(_spend(t) for t in window)
    depth = None if not segments else len(segments) - 1
    level = "root" if not segments else ("category" if len(segments) == 1 else "detail")
    if not segments:
        node = window
    else:
        node = [
            t
            for t in window
            if t.get("category") == segments[0] and _detail_segments(t)[:depth] == segments[1:]
        ]
    total = sum(_spend(t) for t in node)
    key = (lambda t: t["category"]) if depth is None else (lambda t: _drill_key(t, depth))
    groups, counts = _sum_by(node, key), _count_by(node, key)
    pairs = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))
    children = [
        {"key": k, "amount": _r2(v), "share": _share(v, total), "count": counts[k]}
        for k, v in pairs
    ]
    if level == "detail" and len(children) == 1 and children[0]["key"] == "(none)":
        children = []
    parents: dict[str | tuple, dict] = {}
    for i, t in enumerate(node):
        pid = _tx_key(t, i)
        p = parents.setdefault(pid, {"date": t["date"], "merchant": t["merchant"], "_spend": 0.0})
        p["id"] = pid if isinstance(pid, str) else None
        p["has_items"] = bool(t.get("has_items") or t.get("items"))
        p["_spend"] = p["_spend"] + _spend(t)
        p["amount"] = -float(t.get("parent_amount", t["amount"]))
        p["category"] = t.get("parent_category", t["category"])
        p["detail"] = t.get("parent_detail", t.get("detail"))
    ordered = sorted(parents.items(), key=lambda kv: (-kv[1]["_spend"], kv[1]["date"]))
    transactions = [
        {"id": p["id"], "date": p["date"], "merchant": p["merchant"], "amount": _r2(p["amount"])}
        | {"category": p["category"], "detail": p["detail"], "has_items": p["has_items"]}
        | {"in_node": _r2(p["_spend"])}
        for _pid, p in ordered
    ]
    item_rows = []
    for t in node:
        if t.get("item"):
            pid = t.get("parent_id")
            row = {"transaction_id": pid if isinstance(pid, str) else None, "date": t["date"]}
            row["merchant"], row["name"] = t["merchant"], t.get("item_name")
            row["amount"], row["category"] = _r2(_spend(t)), t["category"]
            row["detail"] = t.get("detail")
            item_rows.append(row)
    item_rows.sort(key=lambda r: (-r["amount"], r["date"]))
    uncategorized = sum(_spend(t) for t in window if t.get("category_source") == "none")
    merchants = _merchant_rows(node)[:25]
    out = {"path": "/".join(segments), "level": level, "start": start, "end": end}
    out["total"] = _r2(total)
    out["share_of_spend"] = _share(total, spend_total) if spend_total else 0.0
    out["children"], out["merchants"] = children, merchants
    out["transactions"], out["items"] = transactions[:50], item_rows[:50]
    out["flags"] = _flags(rows, accounts, None, as_of, spend_total, uncategorized)
    return out


def _opt(params: dict, key: str, default):
    v = params.get(key)
    return default if v is None else v


def run_spendreport(params: dict) -> dict:
    """Dispatch one report; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    as_of = _parse_day(params["as_of"], "as_of") if params.get("as_of") else date.today()
    accounts = params.get("accounts")
    if not isinstance(accounts, dict):
        raise ValueError("accounts must be an object keyed by account id")
    raw_rows = params.get("transactions")
    if not isinstance(raw_rows, list) or not all(
        isinstance(t, dict) and t.get("date") and "amount" in t for t in raw_rows
    ):
        raise ValueError("transactions must be a list of normalized rows with date and amount")
    report = params.get("report")
    rows = raw_rows
    if _opt(params, "items", False) and report in _ITEM_REPORTS:
        rows = explode(raw_rows)
    n = int(_opt(params, "compare_months", 3))
    if report in ("month", "changes"):
        month = (
            _parse_month(params["month"]) if params.get("month") else _default_month(rows, as_of)
        )
        if report == "month":
            return report_month(rows, accounts, month, n, as_of, raw_rows)
        threshold = float(_opt(params, "threshold", 0.25))
        return report_changes(rows, accounts, month, threshold, n, as_of, raw_rows)
    if report == "recurring":
        return report_recurring(rows, int(_opt(params, "min_count", 3)))
    if report == "cashflow":
        return report_cashflow(rows, accounts, int(_opt(params, "months", 6)), as_of)
    if report == "uncategorized":
        return report_uncategorized(rows, int(_opt(params, "limit", 25)))
    if report == "search":
        text = params.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text is required for search")
        return report_search(rows, text.strip(), params.get("start"), params.get("end"))
    if report == "merchants":
        top = int(_opt(params, "top", 25))
        return report_merchants(rows, top, params.get("start"), params.get("end"))
    if report == "range":
        if not params.get("start") or not params.get("end"):
            raise ValueError("start and end are required for range")
        by = params.get("by") or "category"
        if by not in ("category", "merchant", "account", "detail"):
            raise ValueError("by must be category, merchant, account or detail")
        start = _parse_day(params["start"], "start").isoformat()
        end = _parse_day(params["end"], "end").isoformat()
        return report_range(rows, accounts, start, end, by)
    if report == "drill":
        drill_rows = explode(rows) if _opt(params, "items", True) else rows
        start = _parse_day(params["start"], "start").isoformat() if params.get("start") else None
        end = _parse_day(params["end"], "end").isoformat() if params.get("end") else None
        return report_drill(drill_rows, accounts, str(params.get("path") or ""), start, end, as_of)
    raise ValueError("unknown report: " + str(report))


def main() -> None:
    """Read JSON params from stdin, write the result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_spendreport(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
