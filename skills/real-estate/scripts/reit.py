#!/usr/bin/env python3
"""Usage: reit.py <symbol> [--nav NAV_PER_SHARE] [--as-of YYYY-MM-DD]

REIT multiples from Yahoo Finance statements: FFO (net income + depreciation
and amortization - gains on sale, per NAREIT), AFFO (FFO - recurring capex,
approximated by the cash-flow statement's capital expenditure), P/FFO,
P/AFFO, FFO yield, dividend yield, payout ratios and, with --nav, the
premium or discount to net asset value. Dividend per share is the trailing
12 months of declared dividends. Runs realestate.py's ``reit`` action on the
assembled inputs and echoes them under ``inputs``. stdin is unused.

Exit codes: 0, 2, 5 (NO_STATEMENTS when Yahoo has no annual statements), 6.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import realestate  # noqa: E402
from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

_NI = ("Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations")
_DA = ("Depreciation And Amortization", "Depreciation Amortization Depletion", "Depreciation", "Reconciled Depreciation")
_GAINS = ("Gain On Sale Of Security", "Gain On Sale Of Business", "Gain On Sale Of Ppe", "Net Non Operating Interest Income Expense")
_CAPEX = ("Capital Expenditure", "Purchase Of PPE")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"reit.py: {message}")


def _pick(row: dict, names: tuple[str, ...]) -> tuple[float | None, str | None]:
    for n in names:
        v = row.get(n)
        if v is not None:
            return float(v), n
    return None, None


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="reit.py", add_help=False)
        p.add_argument("symbol")
        p.add_argument("--nav", type=float, default=None)
        p.add_argument("--as-of", dest="as_of", default=None)
        ns = p.parse_args(args)
        symbol = brokerage.validate_symbol(ns.symbol)
        as_of = date.fromisoformat(ns.as_of) if ns.as_of else date.today()

        info = market.company_info(symbol)
        fin = market.financials(symbol)
        income, cash = fin.get("income_statement") or {}, fin.get("cash_flow") or {}
        if not income:
            raise ApiError(f"Yahoo has no annual statements for {symbol}", code="NO_STATEMENTS")
        fy = max(income)
        fy_label = str(fy)[:10]
        inc_row, cf_row = income[fy], cash.get(fy) or {}
        net_income, ni_label = _pick(inc_row, _NI)
        dep, da_label = _pick(cf_row, _DA)
        gains, gains_label = _pick(inc_row, _GAINS)
        capex, capex_label = _pick(cf_row, _CAPEX)
        if net_income is None:
            raise ApiError(f"no net income line in {symbol}'s {fy} statements", code="NO_STATEMENTS")

        div = market.dividends(symbol)
        floor = (as_of - timedelta(days=365)).isoformat()
        ttm = sum(d["dividend"] for d in div.get("dividends", []) if d.get("date") and floor < d["date"] <= as_of.isoformat() and d.get("dividend"))
        price, shares = info.get("current_price"), info.get("shares_outstanding")
        if not price or not shares:
            raise ApiError(f"Yahoo has no price or share count for {symbol}", code="NO_STATEMENTS")
        inputs = {
            "price": float(price), "shares": float(shares), "net_income": net_income, "depreciation": dep or 0.0,
            "gains_on_sale": max(gains or 0.0, 0.0), "recurring_capex": abs(capex or 0.0),
            "dividend_per_share": round(ttm, 4) if ttm else None, "nav_per_share": ns.nav,
        }
        result = realestate.run_realestate({"action": "reit", **inputs})
        industry = str(info.get("industry") or "")
        is_reit = "reit" in industry.lower() or "real estate" in str(info.get("sector") or "").lower()
        notes = []
        if not is_reit:
            notes.append(f"{symbol} is not classified as a REIT by Yahoo (industry: {industry or 'unknown'}); FFO is only meaningful for property owners")
        notes.append(f"FFO uses {ni_label} + {da_label or 'no D&A line (0)'} - {gains_label or 'no gains line (0)'}; AFFO subtracts {capex_label or 'no capex line (0)'} as a proxy for recurring capex; companies report their own FFO/AFFO, which can differ")
        return {
            "symbol": symbol, "name": info.get("name"), "industry": industry or None, "is_reit": is_reit, "fiscal_year": fy_label,
            "inputs": inputs, "sources": {"statements": "yahoo", "dividends": "yahoo"}, "notes": notes, **result,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
