"""Rebalancing source: a band breach is an alert naming the classes outside their bands; unmapped symbols are a notice."""
from __future__ import annotations

from second_opinion import headlines as H

SKILL = "rebalancing"
WHY = {"BAND_BREACH": "Your allocation drifted past the tolerance band you set around each target weight.",
       "UNMAPPED": "Holdings with no target class are ignored by the drift check."}


def _trade_plan(trades: list, turnover) -> str:
    if not trades or not isinstance(turnover, (int, float)):
        return ""
    parts = []
    for t in trades:
        sym = t.get("symbol")
        if not sym:
            continue
        units = t.get("units")
        units_part = f"{units:g} " if isinstance(units, (int, float)) else ""
        parts.append(f"{str(t.get('side') or '').upper()} {units_part}{sym} {H.money(float(t.get('value') or 0))}")
        if len(parts) == 3:
            break
    if not parts:
        return ""
    return "Plan: " + "; ".join(parts) + f" — turnover {turnover:.1%}"


def extract(results: dict, ctx: dict) -> list[dict]:
    res = results.get("main") or {}
    today = str(ctx["today"])
    codes = {str(f.get("code")): str(f.get("message") or "") for f in res.get("flags") or []}
    out: list[dict] = []
    if "BAND_BREACH" in codes:
        breached = sorted((r for r in res.get("allocation") or [] if r.get("breach")), key=lambda r: str(r.get("key")))
        keys = ",".join(str(r.get("key")) for r in breached)
        parts = [f"{r.get('key')} {float(r.get('drift') or 0) * 100:+.1f} pts" for r in breached]
        out.append(H.make(SKILL, "BAND_BREACH", "alert", "Allocation outside its bands: " + ", ".join(parts) if parts else codes["BAND_BREACH"],
                          discriminator=keys, detail=codes["BAND_BREACH"], as_of=today, ask="What trades bring me back inside my bands?",
                          answer=_trade_plan(res.get("trades") or [], res.get("turnover")), why=WHY["BAND_BREACH"]))
    if "UNMAPPED" in codes:
        out.append(H.make(SKILL, "UNMAPPED", "notice", codes["UNMAPPED"], discriminator="", as_of=today,
                          ask="Which holdings are not mapped to a target class?", answer=codes["UNMAPPED"], why=WHY["UNMAPPED"]))
    return out
