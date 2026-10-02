#!/usr/bin/env python3
"""Usage: performance_report.py <account_id> [--benchmark SPY] [--since YYYY-MM-DD] [--as-of YYYY-MM-DD] [--partial]

Money-weighted return (MWRR) for one account: SnapTrade cash balance plus
positions valued at Yahoo day-change prices (falling through to the broker's
price when Yahoo has none for that symbol, and to the broker's price alone
when the whole Yahoo fetch fails; a position with no price from either source
values at 0.0) as the current value, ledger DEPOSIT/WITHDRAWAL entries for
that account as the external flows (DEPOSIT +, WITHDRAWAL -, keyed on
``amount``, optionally restricted to --since), then performance.py's IRR
bisection over the annual rate in [-0.99, 10]. Positions with units <= 0 (or
no symbol) are skipped, as in aggregate.py. One batched Yahoo download of the
benchmark's daily closes from the first flow date (or --since) feeds the
benchmark comparison over the same window; a failed or short benchmark fetch
degrades to null benchmark fields plus a BENCHMARK_UNAVAILABLE note flag
without failing the run. With fewer than two ledger flows ``mwrr`` is null
and a TOO_FEW_FLOWS note flag explains why. Output is performance.py's
contract plus ``account_id``, ``benchmark`` (symbol) and ``sources``. stdin
is unused. This is an annualized money-weighted return, not advice. Exit
codes: 0, 2 (bad args / unknown account), 4, 5, 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import performance  # noqa: E402
from second_opinion import brokerage, ledger, market, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

_FLOW_TYPES = {"DEPOSIT": 1.0, "WITHDRAWAL": -1.0}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"performance_report.py: {message}")


def _flows(transactions: list, account_id: str, since: str | None) -> list[dict]:
    """Ledger DEPOSIT/WITHDRAWAL entries for the account as signed flow amounts."""
    flows = []
    for t in transactions or []:
        if str(t.get("account_id")) != account_id:
            continue
        sign = _FLOW_TYPES.get(str(t.get("type") or "").upper())
        amount = t.get("amount")
        if sign is None or amount is None:
            continue
        try:
            flows.append({"date": str(t.get("date") or "")[:10], "amount": sign * abs(float(amount))})
        except (TypeError, ValueError):
            continue
    if since:
        flows = [f for f in flows if f["date"] >= since]
    return sorted(flows, key=lambda f: f["date"])


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="performance_report.py", add_help=False)
        p.add_argument("account_id")
        p.add_argument("--partial", action="store_true")
        p.add_argument("--benchmark", default="SPY")
        p.add_argument("--since", default=None)
        p.add_argument("--as-of", dest="as_of", default=None)
        ns = p.parse_args(args)
        benchmark = brokerage.validate_symbol(ns.benchmark)
        since = ns.since
        if since:
            try:
                date.fromisoformat(since)
            except ValueError as exc:
                raise InvalidInput(f"--since must be YYYY-MM-DD, got {since!r}") from exc
        as_of = ns.as_of
        if as_of:
            try:
                date.fromisoformat(as_of)
            except ValueError as exc:
                raise InvalidInput(f"--as-of must be YYYY-MM-DD, got {as_of!r}") from exc

        hub = router.load()
        hub.partial = ns.partial
        accounts = hub.list_accounts()
        row = next((a for a in accounts if a["account_id"] == ns.account_id), None)
        if row is None:
            raise hub.unknown_account_error(ns.account_id)

        cash = 0.0
        symbols: list[str] = []
        broker_prices: dict[str, float] = {}
        units_by_symbol: dict[str, float] = {}
        for pos in hub.get_portfolio(ns.account_id)["positions"] or []:
            sym = pos.get("symbol")
            for _ in range(2):
                if isinstance(sym, dict):
                    sym = sym.get("symbol")
            if not isinstance(sym, str) or not sym:
                continue
            units = pos.get("units")
            if not isinstance(units, (int, float)) or isinstance(units, bool) or units <= 0:
                continue
            sym = sym.upper()
            units_by_symbol[sym] = units_by_symbol.get(sym, 0.0) + float(units)
            price = pos.get("price")
            if price is not None:
                broker_prices[sym] = float(price)
            symbols.append(sym)
        for b in hub.get_balance(ns.account_id)["balances"] or []:
            if isinstance(b, dict) and b.get("cash") is not None:
                cash += float(b["cash"])

        prices = dict(broker_prices)
        source_prices = "snaptrade"
        if symbols:
            try:
                quotes = market.day_changes(sorted(set(symbols)), hub=hub)
                if quotes:
                    source_prices = market.quote_sources(list(quotes.values())) or "yahoo"
                    for sym, q in quotes.items():
                        if q.get("price") is not None:
                            prices[sym] = q["price"]
            except Exception:  # noqa: BLE001 — broker prices are the fallback
                pass
        current_value = cash + sum(units * prices.get(sym, 0.0) for sym, units in units_by_symbol.items())

        flows = _flows(ledger.load().get("transactions") or [], ns.account_id, since)
        first_flow = min((f["date"] for f in flows), default=None)
        start = first_flow or since
        bench_prices: list[dict] = []
        source_benchmark: str | None = None
        if start:
            try:
                bench_prices = market.close_histories([benchmark], start=start).get(benchmark, [])
                if len(bench_prices) >= 2:
                    source_benchmark = "yahoo"
            except Exception:  # noqa: BLE001 — null benchmark fields, not a failed run
                pass

        params: dict = {
            "flows": flows,
            "current_value": current_value,
            "benchmark": {"symbol": benchmark, "prices": bench_prices},
        }
        if as_of:
            params["as_of"] = as_of
        try:
            result = performance.run_performance(params)
        except (ValueError, TypeError) as exc:
            raise InvalidInput(str(exc)) from exc
        return {
            "account_id": ns.account_id,
            "benchmark": benchmark,
            "sources": {
                "flows": "ledger",
                "balances": router.holdings_source([row]),
                "prices": source_prices,
                "benchmark": source_benchmark,
            },
            **result,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
