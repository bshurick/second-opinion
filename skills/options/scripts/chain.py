#!/usr/bin/env python3
"""Usage: chain.py <symbol> [--expiry YYYY-MM-DD] [--around N] [--no-history] [--term-structure] [--as-of YYYY-MM-DD]

Option chain summary for one expiry from Yahoo Finance, run through
options.py's ``chain`` action: spot, days to expiry, ATM strike and IV,
expected move, put/call open-interest and volume ratios, max pain, top
open interest, skew, a strike table (N strikes each side of ATM, default 10)
with mid, IV and delta, plus 30/90-day historical volatility and the IV/HV
ratio from six months of closes (skip with --no-history). The risk-free rate
is the ^IRX 13-week T-bill yield and the dividend yield comes from Yahoo's
company profile (both degrade to options.py's defaults when Yahoo cannot
fill them); the next earnings and ex-dividend dates are reported with
whether each falls inside the expiry, and deep-ITM contracts where early
exercise is plausible are flagged in ``assignment_candidates``.
--expiry defaults to the first expiry at least seven days out; the JSON
lists ``expiries``. --term-structure instead summarizes about six expiries
spread across the listed term (front to back): per-expiry ATM IV, ATM
straddle and put skew with the IV and skew slopes between front and back
(options.py's ``term_structure`` action). stdin is unused.
Exit codes: 0, 2 (unknown expiry, no options), 5, 6.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import options  # noqa: E402
from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

_RISK_FREE_SYMBOL = "^IRX"
_TERM_POINTS = 6


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"chain.py: {message}")


def _rate() -> float | None:
    """13-week T-bill yield from ^IRX (quoted in percentage points), or None."""
    try:
        quotes = market.quote([_RISK_FREE_SYMBOL])
        price = quotes[0].get("price") if quotes else None
        return round(float(price) / 100, 4) if price else None
    except Exception:  # noqa: BLE001 — the chain is the primary data; the rate degrades
        return None


def _dividend_yield(symbol: str) -> float | None:
    """Dividend yield (fraction) from Yahoo's company profile, or None.

    Yahoo reports the yield in percentage points for some symbols (0.33 for
    0.33%); anything above 25% is read as percentage points and divided by 100.
    """
    try:
        y = market.company_info(symbol).get("dividend_yield")
        if not y:
            return None
        y = float(y)
        if y > 0.25:
            y /= 100.0
        return round(y, 4)
    except Exception:  # noqa: BLE001 — the chain is the primary data; the yield degrades
        return None


def _spread(expiries: list[str]) -> list[str]:
    """Up to ``_TERM_POINTS`` expiries evenly spaced from the front to the back."""
    n = len(expiries)
    if n <= _TERM_POINTS:
        return list(expiries)
    idx = sorted({round(i * (n - 1) / (_TERM_POINTS - 1)) for i in range(_TERM_POINTS)})
    return [expiries[i] for i in idx]


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="chain.py", add_help=False)
        p.add_argument("symbol")
        p.add_argument("--expiry", default=None)
        p.add_argument("--around", type=int, default=10)
        p.add_argument("--no-history", action="store_true")
        p.add_argument("--term-structure", dest="term_structure", action="store_true")
        p.add_argument("--as-of", dest="as_of", default=None)
        ns = p.parse_args(args)
        symbol = brokerage.validate_symbol(ns.symbol)
        try:
            chain = market.option_chain(symbol, expiry=None if ns.term_structure else ns.expiry)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc

        if ns.term_structure:
            expiries = []
            for e in _spread([str(x) for x in chain["expiries"]]):
                if e == chain["expiry"]:
                    picked = chain
                else:
                    try:
                        picked = market.option_chain(symbol, expiry=e)
                    except ValueError as exc:
                        raise InvalidInput(str(exc)) from exc
                expiries.append(
                    {"expiry": picked["expiry"], "calls": picked["calls"], "puts": picked["puts"]}
                )
            params = {"action": "term_structure", "spot": chain["spot"], "expiries": expiries}
            if ns.as_of:
                params["as_of"] = ns.as_of
            try:
                summary = options.run_options(params)
            except ValueError as exc:
                raise InvalidInput(str(exc)) from exc
            return {
                "symbol": symbol,
                "expiries": chain["expiries"],
                "sources": {"chain": "yahoo"},
                **summary,
            }

        rate = _rate()
        q = _dividend_yield(symbol)
        events = market.next_events(symbol)
        next_earnings, next_ex_dividend = events.get("next_earnings"), events.get("next_ex_dividend")
        expiry = str(chain["expiry"])
        params = {
            "action": "chain",
            "spot": chain["spot"],
            "expiry": chain["expiry"],
            "around": ns.around,
            "calls": chain["calls"],
            "puts": chain["puts"],
        }
        if rate is not None:
            params["rate"] = rate
        if q is not None:
            params["dividend_yield"] = q
        if next_ex_dividend and next_ex_dividend <= expiry:
            params["ex_dividend_date"] = next_ex_dividend
        if ns.as_of:
            params["as_of"] = ns.as_of
        sources: dict = {"chain": "yahoo", "history": None, "rate": None, "dividend_yield": None, "events": None}
        if rate is not None:
            sources["rate"] = "yahoo (^IRX)"
        if q is not None:
            sources["dividend_yield"] = "yahoo"
        if next_earnings or next_ex_dividend:
            sources["events"] = "yahoo"
        if not ns.no_history:
            params["history"] = market.price_history(symbol, period="6mo")["prices"]
            sources["history"] = "yahoo"
        try:
            summary = options.run_options(params)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        return {
            "symbol": symbol,
            "expiries": chain["expiries"],
            "next_earnings": next_earnings,
            "next_ex_dividend": next_ex_dividend,
            "earnings_in_expiry": bool(next_earnings and next_earnings <= expiry),
            "ex_dividend_in_expiry": bool(next_ex_dividend and next_ex_dividend <= expiry),
            "sources": sources,
            **summary,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
