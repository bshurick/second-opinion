#!/usr/bin/env python3
"""Usage: peers.py <symbol> --peers A,B,C

Builds the `comps.py` input JSON from Yahoo: the target's own trading
multiples (target.metric_values), one metric row per peer, and the
target's per-share financials (target_financials). The output pipes
straight into comps.py, which ignores the extra "sources"/"as_of" keys:

  {"sources": {"fundamentals": "yahoo"}, "as_of": "...",
   "target": {"metric_values": {"pe": ..., "ev_ebitda": ..., ...}},
   "peers": [{"name": "PEP", "pe": ..., ...}, ...],
   "target_financials": {"eps": ..., "sales_per_share": ..., ...}}

Metrics: pe (trailingPE), ev_ebitda (enterprise_value / EBITDA), ps
(market_cap / revenue), pb (priceToBook), ev_sales (enterprise_value /
revenue), fcf_yield (free cash flow / market_cap, the cash flow from the
latest annual statement; Yahoo's own trailing estimate only when the
statement has none), p_ffo (market_cap / (net income + depreciation and
amortization), a funds-from-operations proxy). Values a symbol doesn't
report are omitted; comps.py skips any metric with fewer than 2 reporting
peers. Two Yahoo calls per symbol (info + annual statements).

Only the multiples that mean something for the target's kind of business
are emitted, so the comps summary is not pulled about by ones that do not.
The kind comes from the target's Yahoo sector and is echoed as
"business_type" with "metrics_used": Financial Services -> pe, pb (cash
flow and enterprise value do not describe a bank or insurer); Real Estate
-> p_ffo, ev_ebitda (GAAP earnings are after property depreciation, and
book value is depreciated cost); Utilities -> pe, pb, ev_ebitda (free
cash flow is negative by design); everything else -> pe, ev_ebitda, ps,
pb, ev_sales, fcf_yield.

--peers must list at least 2 distinct symbols besides the target;
duplicates and the target itself are dropped.

Exit codes: 0, 2, 5, 6. stdin is not read.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


_BUSINESS_TYPES = {"Financial Services": "financial", "Real Estate": "reit", "Utilities": "utility"}
_METRICS_FOR = {
    "industrial": ("pe", "ev_ebitda", "ps", "pb", "ev_sales", "fcf_yield"),
    "financial": ("pe", "pb"),
    "reit": ("p_ffo", "ev_ebitda"),
    "utility": ("pe", "pb", "ev_ebitda"),
}


def _latest(statement: dict) -> dict:
    periods = sorted(p for p, row in statement.items() if isinstance(row, dict))
    return statement[periods[-1]] if periods else {}


def _fundamentals(symbol: str) -> dict:
    """One symbol's info + latest annual income statement, flattened."""
    info = market.company_info(symbol)
    stmts = market.financials(symbol)
    income = stmts.get("income_statement") or {}
    latest_period = max(income) if income else None
    row: dict = income.get(latest_period) or {} if latest_period else {}
    cash = _latest(stmts.get("cash_flow") or {})
    net_income = row.get("Net Income") or row.get("Net Income Common Stockholders")
    depreciation = cash.get("Depreciation And Amortization") or cash.get("Depreciation Amortization Depletion")
    statement_fcf = cash.get("Free Cash Flow")
    return {
        "info": info,
        "shares": info.get("shares_outstanding") or stmts.get("shares_outstanding"),
        "revenue": row.get("Total Revenue"),
        "ebitda": row.get("EBITDA"),
        "net_income": net_income,
        "fcf": statement_fcf if statement_fcf is not None else info.get("free_cash_flow"),
        "ffo": net_income + depreciation if net_income is not None and depreciation is not None else None,
    }


def _multiples(f: dict, wanted: tuple[str, ...]) -> dict:
    """The ``wanted`` trading multiples for one symbol; unreported values are omitted."""
    info = f["info"]
    ev = info.get("enterprise_value")
    market_cap = info.get("market_cap")
    price_to_book = info.get("price_to_book")

    def q(value) -> float:
        return round(float(value), 4)

    metrics: dict = {}
    if info.get("pe_ratio") is not None:
        metrics["pe"] = q(info["pe_ratio"])
    if ev and f["ebitda"] and f["ebitda"] > 0:
        metrics["ev_ebitda"] = q(ev / f["ebitda"])
    if market_cap and f["revenue"] and f["revenue"] > 0:
        metrics["ps"] = q(market_cap / f["revenue"])
    if price_to_book:
        metrics["pb"] = q(price_to_book)
    if ev and f["revenue"] and f["revenue"] > 0:
        metrics["ev_sales"] = q(ev / f["revenue"])
    if f["fcf"] is not None and market_cap:
        metrics["fcf_yield"] = q(f["fcf"] / market_cap)
    if market_cap and f["ffo"] and f["ffo"] > 0:
        metrics["p_ffo"] = q(market_cap / f["ffo"])
    return {k: v for k, v in metrics.items() if k in wanted}


def _target_financials(f: dict) -> dict:
    """Per-share financials comps.py needs from the target's fundamentals."""
    info = f["info"]
    out: dict = {}

    def put(key: str, value) -> None:
        if value is not None:
            out[key] = round(float(value), 4)

    shares = f["shares"]
    if shares:
        put("eps", f["net_income"] / shares if f["net_income"] is not None else None)
        put("ebitda_per_share", f["ebitda"] / shares if f["ebitda"] is not None else None)
        put("sales_per_share", f["revenue"] / shares if f["revenue"] is not None else None)
        put("fcf_per_share", f["fcf"] / shares if f["fcf"] is not None else None)
        put("ffo_per_share", f["ffo"] / shares if f["ffo"] is not None else None)
        total_debt = info.get("total_debt")
        total_cash = info.get("total_cash")
        if total_debt is not None and total_cash is not None:
            put("net_debt_per_share", (total_debt - total_cash) / shares)
    price = info.get("current_price")
    price_to_book = info.get("price_to_book")
    if price and price_to_book:
        put("book_value_per_share", price / price_to_book)
    return out


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        symbol_arg: str | None = None
        peers_arg: str | None = None
        rest = iter(args)
        for arg in rest:
            if arg == "--peers":
                peers_arg = next(rest, None)
            elif symbol_arg is None:
                symbol_arg = arg
            else:
                raise InvalidInput("usage: peers.py <symbol> --peers A,B,C")
        if symbol_arg is None or peers_arg is None:
            raise InvalidInput("usage: peers.py <symbol> --peers A,B,C")

        symbol = brokerage.validate_symbol(symbol_arg)
        peer_symbols: list[str] = []
        for raw in peers_arg.split(","):
            peer = brokerage.validate_symbol(raw)
            if peer != symbol and peer not in peer_symbols:
                peer_symbols.append(peer)
        if len(peer_symbols) < 2:
            raise InvalidInput(f"--peers must list at least 2 distinct symbols besides {symbol}")

        target = _fundamentals(symbol)
        business_type = _BUSINESS_TYPES.get(target["info"].get("sector") or "", "industrial")
        wanted = _METRICS_FOR[business_type]
        peers = []
        for peer in peer_symbols:
            peers.append({"name": peer, **_multiples(_fundamentals(peer), wanted)})

        return {
            "sources": {"fundamentals": "yahoo"},
            "as_of": date.today().isoformat(),
            "business_type": business_type,
            "metrics_used": list(wanted),
            "target": {"metric_values": _multiples(target, wanted)},
            "peers": peers,
            "target_financials": _target_financials(target),
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())