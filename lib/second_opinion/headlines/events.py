"""Holdings events source: an earnings date or ex-dividend date inside the next 7 days is an alert."""
from __future__ import annotations

from datetime import date

from second_opinion import headlines as H

SKILL = "portfolio-snapshot"
WINDOW_DAYS = 7
_TITLE = {"earnings": "{s} reports earnings on {d}", "ex_dividend": "{s} goes ex-dividend on {d}"}
_ASK = {"earnings": "What is {s}'s expected move through earnings?", "ex_dividend": "What is {s}'s next dividend worth to me?"}
WHY = {"EARNINGS": "Earnings days bring the largest single-day moves; the options market prices how large.",
       "EX_DIVIDEND": "You must hold the shares before the ex-dividend date to receive the next payment."}


def extract(results: dict, ctx: dict) -> list[dict]:
    today: date = ctx["today"]
    out = []
    for ev in ctx.get("snapshot", {}).get("events") or []:
        kind, sym, when = ev.get("type"), ev.get("symbol"), ev.get("date")
        if kind not in _TITLE or not sym or not when:
            continue
        try:
            d = date.fromisoformat(str(when)[:10])
        except ValueError:
            continue
        if not 0 <= (d - today).days <= WINDOW_DAYS:
            continue
        code = kind.upper()
        out.append(H.make(SKILL, code, "alert", _TITLE[kind].format(s=sym, d=d.isoformat()), symbol=sym,
                          discriminator=d.isoformat(), as_of=str(today), ask=_ASK[kind].format(s=sym),
                          url=H.yahoo_url(sym), answer="", why=WHY[code]))
    return out
