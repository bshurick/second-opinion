"""Dividend source: a cut is an alert; value-trap, payout and income-concentration cautions are notices."""
from __future__ import annotations

from second_opinion import headlines as H

SKILL = "dividend-income"
_SEVERITY = {"DIVIDEND_CUT": "alert", "VALUE_TRAP_CAUTION": "notice", "HIGH_PAYOUT": "notice", "INCOME_CONCENTRATED": "notice"}
_PER_SYMBOL = {"VALUE_TRAP_CAUTION", "INCOME_CONCENTRATED"}
_ASK = {"DIVIDEND_CUT": "Which of my payers cut their dividend?", "VALUE_TRAP_CAUTION": "Is {s}'s yield a value trap?",
        "HIGH_PAYOUT": "Which payers have a payout ratio above 90%?", "INCOME_CONCENTRATED": "How concentrated is my dividend income?"}
WHY = {"DIVIDEND_CUT": "Trailing dividends fell versus the prior year.",
       "VALUE_TRAP_CAUTION": "A yield that rose because the price fell can signal trouble rather than value.",
       "HIGH_PAYOUT": "Paying out most of earnings leaves little room to keep paying.",
       "INCOME_CONCENTRATED": "One payer supplies a large share of your dividend income."}


def _symbols_after_colon(message: str) -> str:
    return message.split(":", 1)[1].strip() if ":" in message else ""


def _position(positions: list, sym: str) -> dict | None:
    return next((p for p in positions or [] if isinstance(p, dict) and str(p.get("symbol") or "").upper() == sym), None)


def _position_answer(positions: list, sym: str | None) -> str:
    row = _position(positions, sym) if sym else None
    if not row:
        return ""
    parts = []
    y = row.get("forward_yield")
    if y is None:
        y = row.get("yield")
    if isinstance(y, (int, float)):
        parts.append(f"Yield {y:.1%}")
    income = row.get("annual_income")
    if isinstance(income, (int, float)):
        parts.append(f"annual income {H.money(income)}")
    safety = row.get("safety") or {}
    score = safety.get("score") if isinstance(safety, dict) else None
    if isinstance(score, (int, float)):
        parts.append(f"safety {score:g}/10")
    return ", ".join(parts)


def extract(results: dict, ctx: dict) -> list[dict]:
    res = results.get("main") or {}
    today = str(ctx["today"])
    positions = res.get("positions") or []
    out: list[dict] = []
    for f in res.get("flags") or []:
        code = str(f.get("code"))
        if code not in _SEVERITY:
            continue
        message = str(f.get("message") or code)
        if code in _PER_SYMBOL:
            sym = H.symbol_from_message(message)
            ask = _ASK[code].format(s=sym) if sym else _ASK[code].replace("{s}'s", "my payers'")
            out.append(H.make(SKILL, code, _SEVERITY[code], message, symbol=sym, discriminator="", as_of=today, ask=ask,
                              url=H.yahoo_url(sym) if sym else "", answer=_position_answer(positions, sym), why=WHY[code]))
        else:
            syms = _symbols_after_colon(message)
            ask = _ASK[code]
            out.append(H.make(SKILL, code, _SEVERITY[code], message, discriminator=syms, as_of=today, ask=ask,
                              answer=message, why=WHY[code]))
    return out
