"""Debt source: past-due or due within 7 days is an alert; high utilization and stale statements are notices."""
from __future__ import annotations

from second_opinion import headlines as H

SKILL = "debt-tracker"
DUE_WINDOW_DAYS = 7
WHY = {"PAST_DUE": "A payment past its due date accrues interest and can be reported late.",
       "DUE_SOON": "A statement payment falls due within a week.",
       "HIGH_UTILIZATION": "Utilization above 30% weighs on credit scores.",
       "STALE": "The debt picture is only as fresh as the last statement recorded."}


def _payment_answer(a: dict) -> str:
    minimum, balance, apr, run_rate = a.get("minimum_payment"), a.get("balance"), a.get("apr"), a.get("monthly_interest_run_rate")
    if not all(isinstance(v, (int, float)) for v in (minimum, balance, apr, run_rate)):
        return ""
    return f"Minimum {H.money(minimum)} on {H.money(balance)} at {apr:.1%} APR ({H.money(run_rate)} interest a month)"


def extract(results: dict, ctx: dict) -> list[dict]:
    res = results.get("main") or {}
    today = str(ctx["today"])
    alerts: list[dict] = []
    notices: list[dict] = []
    for a in res.get("accounts") or []:
        aid, name = str(a.get("id") or ""), str(a.get("name") or a.get("id") or "account")
        flags = set(a.get("flags") or [])
        due, days = a.get("due_date"), a.get("days_to_due")
        interest_ask = f"How much interest am I paying on {name}?"
        payment_answer = _payment_answer(a)
        if "PAST_DUE" in flags:
            ago = f" ({abs(int(days))} days ago)" if isinstance(days, (int, float)) else ""
            alerts.append(H.make(SKILL, "PAST_DUE", "alert", f"{name} payment was due {due}{ago}", discriminator=f"{aid}:{due}", as_of=today, ask=interest_ask,
                                 answer=payment_answer, why=WHY["PAST_DUE"]))
        elif isinstance(days, (int, float)) and 0 <= days <= DUE_WINDOW_DAYS:
            alerts.append(H.make(SKILL, "DUE_SOON", "alert", f"{name} payment is due {due} ({int(days)} days)", discriminator=f"{aid}:{due}", as_of=today, ask=interest_ask,
                                 answer=payment_answer, why=WHY["DUE_SOON"]))
        if "HIGH_UTILIZATION" in flags:
            util, limit, balance = a.get("utilization"), a.get("credit_limit"), a.get("balance")
            text = f"{name} utilization is {float(util) * 100:.1f}%" if isinstance(util, (int, float)) else f"{name} utilization is high"
            answer = f"{H.money(balance)} of a {H.money(limit)} limit" if isinstance(balance, (int, float)) and isinstance(limit, (int, float)) else ""
            notices.append(H.make(SKILL, "HIGH_UTILIZATION", "notice", text, discriminator=aid, as_of=today, ask=interest_ask,
                                  answer=answer, why=WHY["HIGH_UTILIZATION"]))
        if "STALE" in flags:
            period_end = a.get("period_end")
            answer = f"Last statement {period_end}" if period_end else ""
            notices.append(H.make(SKILL, "STALE", "notice", f"{name} statement is {a.get('statement_age_days')} days old", discriminator=aid, as_of=today,
                                  ask="What do I owe across all my accounts?", answer=answer, why=WHY["STALE"]))
    return alerts + notices
