"""Tax source: wash sales and lots about to turn long-term are alerts; sizeable harvest candidates are notices."""
from __future__ import annotations

from second_opinion import headlines as H

SKILL = "tax-aware"
LONG_TERM_WINDOW_DAYS = 30
HARVEST_MIN_LOSS = 1000.0
WHY = {"WASH_SALE": "A loss is disallowed when the same security is bought within 30 days of the sale; the loss is added to the new lot's cost basis.",
       "NEAR_LONG_TERM": "Gains on lots held over a year are taxed at the lower long-term rate.",
       "HARVEST": "Selling a losing lot realizes a loss that offsets gains or up to $3,000 of income."}


def extract(results: dict, ctx: dict) -> list[dict]:
    res = results.get("main") or {}
    today = str(ctx["today"])
    out: list[dict] = []

    # Use realized list if available, otherwise fallback to flags
    if "realized" in res:
        realized_washes = [r for r in (res.get("realized") or []) if r.get("wash_sale")]
        realized_washes.sort(key=lambda r: (str(r.get("sell_date") or ""), str(r.get("symbol") or "").upper()))
        for r in realized_washes:
            sym = str(r.get("symbol") or "").upper()
            sell_date = str(r.get("sell_date") or "")
            disallowed = float(r.get("disallowed") or 0.0)
            wash_buy_date = str(r.get("wash_buy_date") or "")
            detail = f"repurchased {wash_buy_date}; the disallowed amount is added to that lot's basis"
            out.append(H.make(SKILL, "WASH_SALE", "alert",
                             f"{sym} sold {sell_date}: {H.money(disallowed)} of loss disallowed as a wash sale",
                             symbol=sym, discriminator=sell_date,
                             detail=detail,
                             as_of=today, ask="Which of my sales were wash sales?",
                             url=H.yahoo_url(sym), answer=detail, why=WHY["WASH_SALE"]))
    else:
        # Fallback: use flags when realized is not present
        for i, f in enumerate(res.get("flags") or []):
            if f.get("code") == "WASH_SALE":
                msg = str(f.get("message") or "a wash sale disallowed a loss")
                sym = msg.split()[0].rstrip(":").upper() if msg else ""
                out.append(H.make(SKILL, "WASH_SALE", "alert", msg, symbol=sym, discriminator=f"{today}:{i}", detail=msg,
                                  as_of=today, ask="Which of my sales were wash sales?",
                                  url=H.yahoo_url(sym) if sym else "", answer=msg, why=WHY["WASH_SALE"]))
    soonest: dict[str, dict] = {}
    for lot in res.get("open_lots") or []:
        days = lot.get("days_to_long_term")
        if not isinstance(days, (int, float)) or not 0 < days <= LONG_TERM_WINDOW_DAYS:
            continue
        sym = str(lot.get("symbol") or "").upper()
        if sym and (sym not in soonest or days < soonest[sym]["days_to_long_term"]):
            soonest[sym] = lot
    for sym in sorted(soonest):
        lot = soonest[sym]
        when = str(lot.get("long_term_date") or "")
        unreal = float(lot.get("unrealized") or 0.0)
        tax_if_sold, tax_if_sold_long = lot.get("tax_if_sold"), lot.get("tax_if_sold_long")
        if isinstance(tax_if_sold, (int, float)) and isinstance(tax_if_sold_long, (int, float)):
            diff = tax_if_sold - tax_if_sold_long
            answer = f"Tax if sold now {H.money(tax_if_sold)} vs {H.money(tax_if_sold_long)} after {when} (difference {H.money(diff)})"
        else:
            answer = ""
        out.append(H.make(SKILL, "NEAR_LONG_TERM", "alert", f"{sym} lot turns long-term on {when} ({int(lot['days_to_long_term'])} days)", symbol=sym,
                          discriminator=when, detail=f"{lot.get('units')} units bought {lot.get('buy_date')}, unrealized {'-' if unreal < 0 else ''}{H.money(unreal)}",
                          as_of=today, ask=f"Which lots of {sym} are near long-term?",
                          url=H.yahoo_url(sym), answer=answer, why=WHY["NEAR_LONG_TERM"]))
    for c in res.get("harvest_candidates") or []:
        loss = float(c.get("unrealized") or 0.0)
        if loss > -HARVEST_MIN_LOSS:
            continue
        sym = str(c.get("symbol") or "").upper()
        detail = f"estimated tax benefit {H.money(float(c.get('tax_benefit') or 0.0))}" + ("; bought within 30 days" if c.get("recent_buy_within_30d") else "")
        out.append(H.make(SKILL, "HARVEST", "notice", f"{sym} carries a {H.money(loss)} unrealized loss to harvest", symbol=sym, discriminator="",
                          detail=detail,
                          as_of=today, ask=f"What would harvesting {sym} save me?",
                          url=H.yahoo_url(sym), answer=detail, why=WHY["HARVEST"]))
    return out
