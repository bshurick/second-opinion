"""Trade-journal source: an open entry whose live price is through its stop is an alert; review flags are notices."""
from __future__ import annotations

import re

from second_opinion import headlines as H

SKILL = "trade-journal"
_ASK = {"STALE_OPEN": "Which journal entries are past their horizon?", "OVERSTAYED": "Which journal entries are past their horizon?",
        "STOP_DRIFTED": "Which stops have I moved since entry?"}
WHY = {"STOP_HIT": "Your journal's stop for this trade has been crossed; the plan called for an exit or a re-think.",
       "STALE_OPEN": "An open trade past its planned horizon.", "OVERSTAYED": "An open trade past its planned horizon.",
       "STOP_DRIFTED": "The stop was moved after entry, which weakens the original plan."}
_STOP_DRIFTED_PATTERN = re.compile(r'^(\S+)\s+\(([^)]+)\):')


def _stop_hit_answer(stored: dict, review_row: dict) -> str:
    parts = []
    entry_price = stored.get("entry_price")
    if isinstance(entry_price, (int, float)):
        parts.append(f"Entry {entry_price:.2f}")
    stop = stored.get("stop")
    if isinstance(stop, (int, float)):
        parts.append(f"stop {stop:.2f}")
    target = stored.get("target")
    if isinstance(target, (int, float)):
        parts.append(f"target {target:.2f}")
    live_rr = review_row.get("live_rr")
    if isinstance(live_rr, (int, float)):
        parts.append(f"live R:R {live_rr:.2f}")
    return ", ".join(parts)


def _parse_stop_drifted(message: str) -> tuple[str | None, str | None]:
    """Parse STOP_DRIFTED message format: 'id (SYMBOL): text' -> (id, symbol_upper)."""
    match = _STOP_DRIFTED_PATTERN.match(str(message))
    if match:
        return match.group(1), match.group(2).upper()
    # Fallback: extract first token as id, rest as None
    parts = str(message).split()
    return parts[0] if parts else None, None


def extract(results: dict, ctx: dict) -> list[dict]:
    review = results.get("review") or {}
    stops = {str(e.get("id")): e for e in (results.get("open") or {}).get("entries") or []}
    today = str(ctx["today"])
    out: list[dict] = []
    for e in review.get("entries") or []:
        if e.get("exit") != "open" or not isinstance(e.get("live_price"), (int, float)):
            continue
        stored = stops.get(str(e.get("id"))) or {}
        stop = stored.get("stop")
        if not isinstance(stop, (int, float)):
            continue
        price, side, sym = float(e["live_price"]), str(e.get("side") or stored.get("side") or "long").lower(), str(e.get("symbol") or "").upper()
        through = price >= stop if side == "short" else price <= stop
        if through:
            out.append(H.make(SKILL, "STOP_HIT", "alert", f"{sym} at {price:.2f} is through its {float(stop):.2f} stop (journal {e.get('id')})", symbol=sym,
                              discriminator=str(e.get("id")), as_of=today, ask=f"Am I following my plan on {sym}?",
                              url=H.yahoo_url(sym), answer=_stop_hit_answer(stored, e), why=WHY["STOP_HIT"]))
    for f in review.get("flags") or []:
        code = str(f.get("code"))
        if code not in _ASK:
            continue
        message = str(f.get("message") or code)
        if code == "STOP_DRIFTED":
            entry_id, sym = _parse_stop_drifted(message)
            out.append(H.make(SKILL, code, "notice", message, symbol=sym, discriminator=entry_id or "", as_of=today, ask=_ASK[code],
                              answer=message, why=WHY[code]))
        else:
            out.append(H.make(SKILL, code, "notice", message, discriminator="", as_of=today, ask=_ASK[code],
                              answer=message, why=WHY[code]))
    return out
