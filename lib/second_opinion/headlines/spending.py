"""Spending source: a category that moved sharply against its recent average, and any newly recurring charge, are notices."""
from __future__ import annotations

from second_opinion import headlines as H

SKILL = "spending"
MOVE_PCT = 0.25
MOVE_ABS = 200.0
EVERYDAY_CATEGORIES = {"Groceries", "Dining", "Coffee", "Transport", "Fuel"}
WHY = {"CATEGORY_MOVE": "A category that moved 25% and $200 against its three-month average.",
       "NEW_RECURRING": "A charge that now repeats on a schedule and did not a month ago."}


def _valid_charge(c) -> bool:
    return isinstance(c, dict) and bool(c.get("merchant")) and isinstance(c.get("amount"), (int, float))


def _category_move_answer(row: dict) -> str:
    charges = [c for c in row.get("explained_by") or [] if _valid_charge(c)]
    if not charges:
        return ""
    top = sorted(charges, key=lambda c: float(c["amount"]), reverse=True)[:2]
    first = f"{top[0]['merchant']} {H.money(float(top[0]['amount']))}"
    if top[0].get("date"):
        first += f" on {top[0]['date']}"
    if len(top) == 1:
        return f"Largest: {first}"
    second = f"{top[1]['merchant']} {H.money(float(top[1]['amount']))}"
    return f"Largest: {first}; {second}"


def extract(results: dict, ctx: dict) -> list[dict]:
    ch = results.get("changes") or {}
    month = str(ch.get("month") or str(ctx["today"])[:7])
    today = str(ctx["today"])
    out: list[dict] = []
    for row in ch.get("categories") or []:
        delta, pct = row.get("delta"), row.get("delta_pct")
        if not isinstance(delta, (int, float)) or not isinstance(pct, (int, float)):
            continue
        if abs(pct) < MOVE_PCT or abs(delta) < MOVE_ABS:
            continue
        cat = str(row.get("category") or "?")
        direction = "up" if delta > 0 else "down"
        out.append(H.make(SKILL, "CATEGORY_MOVE", "notice",
                          f"{cat} is {direction} {abs(pct) * 100:.1f}% this month ({H.money(float(row.get('amount') or 0))} vs {H.money(float(row.get('avg_prior') or 0))} average)",
                          discriminator=f"{month}:{cat}", as_of=today, ask=f"What drove {cat} spending in {month}?",
                          answer=_category_move_answer(row), why=WHY["CATEGORY_MOVE"]))
    for s in ch.get("new_recurring") or []:
        if s.get("category") in EVERYDAY_CATEGORIES:
            continue
        merchant = str(s.get("merchant") or "?")
        annual_cost, next_expected = s.get("annual_cost"), s.get("next_expected")
        answer = f"{H.money(float(annual_cost))} a year; next expected {next_expected}" if isinstance(annual_cost, (int, float)) and next_expected else ""
        out.append(H.make(SKILL, "NEW_RECURRING", "notice", f"New recurring charge: {merchant} {H.money(float(s.get('typical_amount') or 0))} {s.get('cadence') or ''}".rstrip(),
                          discriminator=f"{merchant}:{s.get('first_date')}", as_of=today, ask="What are all my recurring charges?",
                          answer=answer, why=WHY["NEW_RECURRING"]))
    return out
