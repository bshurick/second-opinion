#!/usr/bin/env python3
"""Usage: run-review.py [--account ID ...] [--symbol SYM ...] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--benchmark SPY] [--as-of YYYY-MM-DD] [--no-prices] [--research-top N] [--save]

Review the trading decisions recorded in the local ledger (``ledger.json``
under the plugin data dir, built by the statement-import skill): reads the
ledger, pulls daily prices for every traded symbol plus the benchmark in ONE
batched Yahoo download (from 400 days before the first trade, so pre-buy
momentum has history), and runs review.py. Output is review.py's contract
plus ``sources``, ``ledger`` (what was used) and, with --save,
``report_path`` (JSON copy in the plugin data dir). stdin is unused.

--account/--symbol/--start/--end filter the ledger before the review; note
that filtering out the buys behind a sale makes that sale "unmatched".
--no-prices skips Yahoo (round trips still work; drift, context and
counterfactuals do not). If Yahoo fails the review still runs and adds a
PRICES_UNAVAILABLE flag. --research-top N (integer >= 0) truncates
``research_queue`` to the N rows with the largest |total_pnl| (the
untruncated queue keeps its own order). Output also carries
``largest_buys``: per symbol (sorted, at most 25 symbols), the two largest
BUY ledger rows by |amount| — the lots behind a "was buying X wise" question
when the run is scoped with --symbol X. Exit codes: 0, 2 (empty ledger, bad
dates, bad --research-top), 5 (LEDGER_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import review  # noqa: E402
from second_opinion import ledger, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

_LOOKBACK_DAYS = 400


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"run-review.py: {message}")


def _iso(raw: str | None, flag: str) -> str | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise InvalidInput(f"{flag} must be YYYY-MM-DD") from exc


def _largest_buys(rows: list[dict]) -> list[dict]:
    """The two biggest BUY rows per symbol (sorted, capped at 25 symbols)."""
    def size(t: dict) -> float:
        a = t.get("amount")
        if a is not None:
            return abs(float(a))
        u, p = t.get("units"), t.get("price")
        return abs(float(u) * float(p)) if u is not None and p is not None else 0.0

    by_symbol: dict[str, list[dict]] = {}
    for t in rows:
        if str(t.get("type") or "").upper() == "BUY" and t.get("symbol"):
            by_symbol.setdefault(str(t["symbol"]).upper(), []).append(t)
    out = []
    for sym in sorted(by_symbol)[:25]:
        for t in sorted(by_symbol[sym], key=lambda t: (-size(t), str(t.get("date"))))[:2]:
            out.append(
                {
                    "symbol": sym,
                    "date": t.get("date"),
                    "units": t.get("units"),
                    "price": t.get("price"),
                    "amount": t.get("amount"),
                }
            )
    return out


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="run-review.py", add_help=False)
        p.add_argument("--account", action="append", default=None)
        p.add_argument("--symbol", action="append", default=None)
        p.add_argument("--start", default=None)
        p.add_argument("--end", default=None)
        p.add_argument("--benchmark", default="SPY")
        p.add_argument("--as-of", dest="as_of", default=None)
        p.add_argument("--no-prices", action="store_true")
        p.add_argument("--research-top", dest="research_top", default=None, type=int)
        p.add_argument("--save", action="store_true")
        ns = p.parse_args(args)
        if ns.research_top is not None and ns.research_top < 0:
            raise InvalidInput("--research-top must be an integer >= 0")
        start, end, as_of = _iso(ns.start, "--start"), _iso(ns.end, "--end"), _iso(ns.as_of, "--as-of") or date.today().isoformat()
        benchmark = ns.benchmark.strip().upper() if ns.benchmark and ns.benchmark.strip() else None

        book = ledger.load()
        rows = book["transactions"]
        if not rows:
            raise InvalidInput("the ledger is empty: run import-csv.py <file.csv> or sync-broker.py first")
        if ns.account:
            wanted = set(ns.account)
            rows = [t for t in rows if str(t.get("account_id")) in wanted]
        if ns.symbol:
            wanted = {s.upper() for s in ns.symbol}
            rows = [t for t in rows if (t.get("symbol") or "").upper() in wanted]
        rows = ledger.filter(rows, start=start, end=end)
        if not rows:
            raise InvalidInput("no ledger transactions match the filters")
        traded = sorted({(t.get("symbol") or "").upper() for t in rows if t.get("type") in ("BUY", "SELL") and t.get("symbol")})

        sources = {"ledger": str(ledger.ledger_path()), "prices": None, "benchmark": None}
        prices: dict = {}
        bench = None
        extra_flags: list[dict] = []
        if not ns.no_prices and traded:
            since = (date.fromisoformat(rows[0]["date"]) - timedelta(days=_LOOKBACK_DAYS)).isoformat()
            symbols = sorted(set(traded) | ({benchmark} if benchmark else set()))
            try:
                fetched = market.close_histories(symbols, start=since)
                prices = {s: fetched.get(s, []) for s in traded}
                sources["prices"] = "yahoo"
                if benchmark and fetched.get(benchmark):
                    bench = {"symbol": benchmark, "prices": fetched[benchmark]}
                    sources["benchmark"] = benchmark
            except Exception as e:  # noqa: BLE001 — a price outage must not sink the review
                extra_flags.append({"code": "PRICES_UNAVAILABLE", "message": f"Yahoo prices failed ({e}); drift, context and counterfactuals are unavailable"})

        params = {"as_of": as_of, "transactions": rows, "prices": prices}
        if bench:
            params["benchmark"] = bench
        result = review.run_review(params)
        result["flags"].extend(extra_flags)
        if ns.research_top is not None:
            ranked = sorted(
                enumerate(result.get("research_queue") or []),
                key=lambda pair: (-abs(pair[1].get("total_pnl") or 0.0), pair[0]),
            )
            result["research_queue"] = [row for _, row in ranked[: ns.research_top]]
        summary = ledger.summary(rows)
        out = {
            "sources": sources,
            "ledger": {"transactions_used": len(rows), "accounts": list(summary["accounts"]), "date_range": summary["date_range"]},
            "largest_buys": _largest_buys(rows),
            **result,
        }
        if ns.save:
            path = ledger.ledger_path().parent / f"trade-review-{as_of}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, indent=1))
            out["report_path"] = str(path)
        return out

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
