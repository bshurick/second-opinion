"""Watchlist source: every rule that newly fired on this run is an alert."""
from __future__ import annotations

from second_opinion import headlines as H

SKILL = "watchlist"
WHY = {"TRIGGER": "A price rule you set on your watchlist fired on today's quote."}


def _row(rows: list, symbol: str) -> dict | None:
    return next((r for r in rows or [] if isinstance(r, dict) and r.get("symbol") == symbol), None)


def _from_high_text(from_high: float) -> str:
    if from_high > 0:
        return f"{from_high:.1%} above the 52-week high"
    if from_high < 0:
        return f"{abs(from_high):.1%} below the 52-week high"
    return "at the 52-week high"


def _answer(row: dict | None, t: dict) -> str:
    if not row:
        return ""
    price, since, from_high = row.get("price"), row.get("since_added_pct"), row.get("from_52w_high")
    if not isinstance(price, (int, float)) or not isinstance(since, (int, float)) or not isinstance(from_high, (int, float)):
        return ""
    return f"Now {price:.2f}; rule {t.get('type')} at {t.get('value')}; {since:+.1%} since added, {_from_high_text(from_high)}"


def extract(results: dict, ctx: dict) -> list[dict]:
    res = results.get("main") or {}
    as_of = res.get("as_of") or str(ctx["today"])
    watchlist = res.get("watchlist") or []
    out = []
    for t in res.get("triggered") or []:
        if t.get("state") != "new":
            continue
        sym = t.get("symbol")
        row = _row(watchlist, sym)
        out.append(H.make(SKILL, str(t.get("type") or "rule"), "alert", str(t.get("message") or f"{sym} rule fired"),
                          symbol=sym, discriminator=as_of, as_of=as_of, ask="What on my watchlist moved?",
                          url=H.yahoo_url(sym) if sym else "", answer=_answer(row, t), why=WHY["TRIGGER"]))
    return out
