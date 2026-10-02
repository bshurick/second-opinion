#!/usr/bin/env python3
"""Usage: tax-report.py [--account ID ...] [--as-of YYYY-MM-DD] [--short-term R] [--long-term R] [--state R] [--niit R] [--price SYMBOL=PRICE ...] [--sell SYMBOL UNITS ...] [--sell-after YYYY-MM-DD] [--min-loss N] [--min-loss-pct R]

Tax view of the local ledger (built by the statement-import skill): open
lots with holding periods and tax if sold, year-to-date realized gains with
wash-sale detection, netting and an estimated liability, harvesting
candidates, and (with --sell, repeatable) FIFO versus highest-cost versus
tax-minimal lot selection for planned sales. --sell-after DATE models every
planned sale as of that date (lots held more than one year by then are
long-term). Current prices come from ONE batched Yahoo quote for the
symbols still held; --price overrides or fills a quote. Rates are decimals
(defaults: short-term 0.24, long-term 0.15, state 0, NIIT 0). Output is
tax.py's contract plus ``sources``, ``ledger`` and ``missing_prices``.
stdin is unused. Exit codes: 0, 2 (empty ledger, bad flags), 5, 6.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import tax  # noqa: E402
from second_opinion import ledger, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"tax-report.py: {message}")


def _open_symbols(rows: list[dict]) -> list[str]:
    held: dict[tuple[str, str], float] = {}
    for t in rows:
        if t.get("type") in ("BUY", "SELL") and t.get("symbol") and t.get("units"):
            key = (str(t.get("account_id")), t["symbol"].upper())
            held[key] = held.get(key, 0.0) + (t["units"] if t["type"] == "BUY" else -t["units"])
    return sorted({sym for (_, sym), units in held.items() if units > 1e-9})


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="tax-report.py", add_help=False)
        p.add_argument("--account", action="append", default=None)
        p.add_argument("--as-of", dest="as_of", default=None)
        p.add_argument("--short-term", type=float, default=0.24)
        p.add_argument("--long-term", type=float, default=0.15)
        p.add_argument("--state", type=float, default=0.0)
        p.add_argument("--niit", type=float, default=0.0)
        p.add_argument("--price", action="append", default=[])
        p.add_argument("--sell", nargs=2, metavar=("SYMBOL", "UNITS"), action="append", default=[])
        p.add_argument("--sell-after", dest="sell_after", default=None)
        p.add_argument("--min-loss", type=float, default=None)
        p.add_argument("--min-loss-pct", type=float, default=None)
        ns = p.parse_args(args)
        as_of = ns.as_of or date.today().isoformat()
        overrides: dict[str, float] = {}
        for item in ns.price:
            sym, sep, val = item.partition("=")
            try:
                overrides[sym.strip().upper()] = float(val)
            except ValueError as exc:
                raise InvalidInput(f"--price expects SYMBOL=PRICE, got {item!r}") from exc
            if not sep or not sym.strip():
                raise InvalidInput(f"--price expects SYMBOL=PRICE, got {item!r}")

        book = ledger.load()
        rows = book["transactions"]
        if not rows:
            raise InvalidInput("the ledger is empty: run import-csv.py <file.csv> or sync-broker.py first")
        if ns.account:
            wanted = set(ns.account)
            rows = [t for t in rows if str(t.get("account_id")) in wanted]
            if not rows:
                raise InvalidInput("no ledger transactions match the account filter")

        symbols = [s for s in _open_symbols(rows) if s not in overrides]
        sources = {"ledger": str(ledger.ledger_path()), "prices": None}
        prices = dict(overrides)
        if symbols:
            try:
                quotes = market.day_changes(symbols)
                prices.update({s: q["price"] for s, q in quotes.items() if q.get("price") is not None})
                sources["prices"] = "yahoo"
            except Exception:  # noqa: BLE001 — a quote outage must not sink the report
                sources["prices"] = None
        missing = [s for s in _open_symbols(rows) if s not in prices]

        params = {
            "as_of": as_of, "transactions": rows, "prices": prices,
            "rates": {"short_term": ns.short_term, "long_term": ns.long_term, "state": ns.state, "niit": ns.niit},
        }
        if ns.min_loss is not None:
            params["min_loss"] = ns.min_loss
        if ns.min_loss_pct is not None:
            params["min_loss_pct"] = ns.min_loss_pct
        sells = []
        for sym, units in ns.sell:
            try:
                sells.append({"symbol": str(sym).upper(), "units": float(units)})
            except ValueError as exc:
                raise InvalidInput("--sell expects SYMBOL UNITS") from exc
        if ns.sell_after and not sells:
            raise InvalidInput("--sell-after requires at least one --sell SYMBOL UNITS")
        if sells:
            if ns.sell_after:
                for entry in sells:
                    entry["sell_as_of"] = ns.sell_after
            if len(sells) == 1:
                params["planned_sale"] = sells[0]
            else:
                params["planned_sales"] = sells
        try:
            result = tax.run_tax(params)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        if missing:
            result["flags"].append({"code": "MISSING_PRICES", "message": f"no current price for: {', '.join(missing)}; unrealized figures exclude them (pass --price SYMBOL=PRICE)"})
        summary = ledger.summary(rows)
        return {"sources": sources, "ledger": {"transactions_used": len(rows), "accounts": list(summary["accounts"]), "date_range": summary["date_range"]}, "missing_prices": missing, **result}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
