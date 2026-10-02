"""Risk source: beta, correlation and liquidity flags are notices, as is a max drawdown deeper than the last brief's."""
from __future__ import annotations

from second_opinion import headlines as H

SKILL = "risk-analysis"
DRAWDOWN_STEP = 0.05
_PER_SYMBOL = {"ILLIQUID_POSITION"}
_ASK = {"HIGH_BETA": "How much would a 20% market drop cost me?", "HIGH_CORRELATION": "Which holdings move together the most?",
        "ILLIQUID_POSITION": "Which positions are hard to sell quickly?"}
WHY = {"HIGH_BETA": "Beta is how much the portfolio moves when the market moves 1%.",
       "HIGH_CORRELATION": "Holdings that move together give less diversification than their count implies.",
       "ILLIQUID_POSITION": "A position larger than a slice of daily volume takes days to sell without moving the price.",
       "DRAWDOWN_DEEPER": "Max drawdown is the deepest peak-to-trough fall over the period."}


def _drawdown(res: dict) -> float | None:
    v = (res.get("portfolio") or {}).get("max_drawdown")
    return float(v) if isinstance(v, (int, float)) else None


def _row(rows: list, symbol: str) -> dict | None:
    return next((r for r in rows or [] if isinstance(r, dict) and r.get("symbol") == symbol), None)


def _high_beta_answer(portfolio: dict) -> str:
    beta, total_value = portfolio.get("beta"), portfolio.get("total_value")
    if not isinstance(beta, (int, float)) or not isinstance(total_value, (int, float)):
        return ""
    text = f"Beta {beta:.2f}; a 20% market drop maps to about {H.money(0.2 * beta * total_value)}"
    coverage = portfolio.get("coverage")
    if isinstance(coverage, (int, float)) and coverage < 0.99:
        text += f" (statistics cover {H.pct(coverage)} of value; the rest is assumed unchanged)"
    return text


def _illiquid_answer(liquidity: list, sym: str | None) -> str:
    row = _row(liquidity, sym) if sym else None
    if not row:
        return ""
    pos_value, adv, pct_of_adv = row.get("position_value"), row.get("avg_dollar_volume"), row.get("pct_of_adv")
    if not all(isinstance(v, (int, float)) for v in (pos_value, adv, pct_of_adv)):
        return ""
    return f"{H.money(pos_value)} position vs {H.money(adv)} average daily volume ({pct_of_adv:.1%})"


def _top_risk_contributor(contributions: list) -> dict | None:
    rows = [r for r in contributions or [] if isinstance(r, dict) and isinstance(r.get("share"), (int, float))]
    return max(rows, key=lambda r: r["share"]) if rows else None


def snapshot_for_last(results: dict) -> dict:
    dd = _drawdown(results.get("main") or {})
    return {"max_drawdown": dd} if dd is not None else {}


def extract(results: dict, ctx: dict) -> list[dict]:
    if isinstance(ctx.get("risk_results"), dict):
        ctx["risk_results"].update(results)
    res = results.get("main") or {}
    today = str(ctx["today"])
    portfolio = res.get("portfolio") or {}
    liquidity = res.get("liquidity") or []
    out: list[dict] = []
    for f in res.get("flags") or []:
        code = str(f.get("code"))
        if code in _ASK:
            message = str(f.get("message") or code)
            if code in _PER_SYMBOL:
                sym = H.symbol_from_message(message)
                out.append(H.make(SKILL, code, "notice", message, symbol=sym, discriminator="", as_of=today, ask=_ASK[code],
                                  url=H.yahoo_url(sym) if sym else "", answer=_illiquid_answer(liquidity, sym), why=WHY[code]))
            elif code == "HIGH_BETA":
                out.append(H.make(SKILL, code, "notice", message, discriminator="", as_of=today, ask=_ASK[code],
                                  answer=_high_beta_answer(portfolio), why=WHY[code]))
            elif code == "HIGH_CORRELATION":
                corr = portfolio.get("avg_pairwise_correlation")
                answer = f"Average pairwise correlation {corr:.2f}" if isinstance(corr, (int, float)) else ""
                out.append(H.make(SKILL, code, "notice", message, discriminator="", as_of=today, ask=_ASK[code], answer=answer, why=WHY[code]))
            else:
                out.append(H.make(SKILL, code, "notice", message, discriminator="", as_of=today, ask=_ASK[code]))
    now, prev = _drawdown(res), (ctx.get("previous") or {}).get("risk", {}).get("max_drawdown")
    if now is not None and isinstance(prev, (int, float)) and abs(now) - abs(float(prev)) >= DRAWDOWN_STEP:
        top = _top_risk_contributor(res.get("risk_contributions") or [])
        answer = f"Largest risk contributor {top['symbol']} at {top['share']:.0%} of portfolio variance" if top else ""
        out.append(H.make(SKILL, "DRAWDOWN_DEEPER", "notice", f"Max drawdown deepened to {abs(now) * 100:.1f}% from {abs(float(prev)) * 100:.1f}% at the last brief",
                          discriminator=today, as_of=today, ask="What is driving my portfolio's drawdown?",
                          answer=answer, why=WHY["DRAWDOWN_DEEPER"]))
    return out
