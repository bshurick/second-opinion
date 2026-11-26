"""Debt source: the next payment due within 7 days is an alert; high utilization is a notice.

Statements are typed in by hand, so they are sparse and often a month or two old. A due date on a recorded
statement is read as a monthly schedule: it rolls forward a month at a time to the next date on or after
today. A payment therefore never shows as past due because the newer statement was not recorded, and an old
statement still gives the next date. ``upcoming`` turns the same projection into rows for the brief's
Upcoming events table.
"""
from __future__ import annotations

import calendar
from datetime import date

from second_opinion import headlines as H

SKILL = "personal-finance"
DUE_WINDOW_DAYS = 7
DUE_ALERT_DAYS = 3  # due this soon is an alert; later inside the window, a notice
WHY = {"DUE_SOON": "A loan or card payment falls due within a week.",
       "HIGH_UTILIZATION": "Utilization above 30% weighs on credit scores."}


def _add_months(d: date, n: int, day: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_due(due: object, today: date) -> tuple[date, bool] | None:
    """``(next due date on or after today, projected)`` from a statement's due date, or None if unparseable.

    ``projected`` is True when the date was rolled forward from the statement rather than printed on it.
    """
    try:
        d = date.fromisoformat(str(due)[:10])
    except ValueError:
        return None
    if d >= today:
        return d, False
    n = (today.year - d.year) * 12 + today.month - d.month
    nxt = _add_months(d, n, d.day)
    if nxt < today:
        nxt = _add_months(d, n + 1, d.day)
    return nxt, True


def _payment_answer(a: dict) -> str:
    minimum, balance, apr, run_rate = a.get("minimum_payment"), a.get("balance"), a.get("apr"), a.get("monthly_interest_run_rate")
    if not all(isinstance(v, (int, float)) for v in (minimum, balance, apr, run_rate)):
        return ""
    return f"Minimum {H.money(minimum)} on {H.money(balance)} at {apr:.1%} APR ({H.money(run_rate)} interest a month)"


def _next(a: dict, today: date) -> tuple[date, bool] | None:
    """debts.py's own ``next_due_date`` when present, else the same roll-forward from ``due_date``."""
    if a.get("next_due_date"):
        try:
            d = date.fromisoformat(str(a["next_due_date"])[:10])
        except ValueError:
            d = None
        if d is not None and d >= today:
            return d, bool(a.get("due_projected"))
    return next_due(a.get("due_date"), today)


def _accounts(results: dict) -> list[dict]:
    return [a for a in ((results.get("main") or {}).get("accounts") or []) if isinstance(a, dict)]


def upcoming(results: dict, today: date) -> list[dict]:
    """One Upcoming-events row per account with a due date: its next payment on or after today."""
    rows = []
    for a in _accounts(results):
        nd = _next(a, today)
        if nd is None:
            continue
        minimum = a.get("minimum_payment")
        label = f"payment {H.money(minimum)}" if isinstance(minimum, (int, float)) else "payment"
        if nd[1]:
            label += " (from the monthly schedule)"
        rows.append({"symbol": str(a.get("name") or a.get("id") or "account"), "type": "payment", "date": nd[0].isoformat(),
                     "label": label, "projected": nd[1]})
    return rows


def extract(results: dict, ctx: dict) -> list[dict]:
    today = ctx["today"]
    alerts: list[dict] = []
    notices: list[dict] = []
    for a in _accounts(results):
        aid, name = str(a.get("id") or ""), str(a.get("name") or a.get("id") or "account")
        interest_ask = f"How much interest am I paying on {name}?"
        nd = _next(a, today)
        if nd is not None and (nd[0] - today).days <= DUE_WINDOW_DAYS:
            due, days = nd[0].isoformat(), (nd[0] - today).days
            answer = _payment_answer(a)
            if nd[1] and answer:
                answer += f"; date from the monthly schedule of the {str(a.get('due_date'))[:10]} statement"
            sev = "alert" if days <= DUE_ALERT_DAYS else "notice"
            alerts.append(H.make(SKILL, "DUE_SOON", sev, f"{name} payment is due {due} ({days} days)", discriminator=f"{aid}:{due}",
                                 as_of=str(today), ask=interest_ask, answer=answer, why=WHY["DUE_SOON"]))
        if "HIGH_UTILIZATION" in set(a.get("flags") or []):
            util, limit, balance = a.get("utilization"), a.get("credit_limit"), a.get("balance")
            text = f"{name} utilization is {float(util) * 100:.1f}%" if isinstance(util, (int, float)) else f"{name} utilization is high"
            answer = f"{H.money(balance)} of a {H.money(limit)} limit" if isinstance(balance, (int, float)) and isinstance(limit, (int, float)) else ""
            notices.append(H.make(SKILL, "HIGH_UTILIZATION", "notice", text, discriminator=aid, as_of=str(today), ask=interest_ask,
                                  answer=answer, why=WHY["HIGH_UTILIZATION"]))
    return alerts + notices
