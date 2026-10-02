"""Ledger source: a ledger last imported more than 30 days ago is a notice, because every ledger-based skill goes stale with it."""
from __future__ import annotations

from datetime import date

from second_opinion import headlines as H

SKILL = "statement-import"
STALE_DAYS = 30
WHY = {"STALE_LEDGER": "Tax, trade-review and journal analysis read this ledger; a stale ledger makes them stale."}


def _date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def extract(results: dict, ctx: dict) -> list[dict]:
    res = results.get("main") or {}
    today: date = ctx["today"]
    imports = res.get("imports") or []
    last = _date(imports[-1].get("at")) if imports and isinstance(imports[-1], dict) else None
    if last is None:
        last = _date((res.get("date_range") or {}).get("end"))
    if last is None:
        return []
    age = (today - last).days
    if age <= STALE_DAYS:
        return []
    count = res.get("count")
    end = (res.get("date_range") or {}).get("end")
    last_import = imports[-1] if imports and isinstance(imports[-1], dict) else {}
    source, added = last_import.get("source"), last_import.get("added")
    if isinstance(count, int) and end:
        answer = f"{count} transactions through {end}"
        if isinstance(source, str) and isinstance(added, (int, float)):
            answer += f"; last import {source} added {added}"
    else:
        answer = ""
    return [H.make(SKILL, "STALE_LEDGER", "notice", f"Ledger last imported {last.isoformat()} ({age} days ago)", discriminator=last.isoformat(),
                   as_of=str(today), ask="How recent is my imported activity?", answer=answer, why=WHY["STALE_LEDGER"])]
