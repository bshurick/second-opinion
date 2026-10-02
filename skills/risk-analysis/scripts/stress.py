#!/usr/bin/env python3
"""Usage: stress.py [--account ID ...] [--years N] [--benchmark SPY] [--shock SYMBOL=RETURN ...] [--scenario NAME=BENCHMARK_RETURN ...] [--no-builtin] [--risk-free R] [--as-of YYYY-MM-DD] [--partial]

Risk and stress test of the connected accounts: SnapTrade accounts once,
positions and balances once per account (aggregated by symbol), ONE batched
Yahoo download of N years (default 3) of daily closes for every symbol plus
the benchmark, then risk.py. Built-in scenarios replay the 2008 crisis, the
2018 Q4 selloff, the 2020 COVID crash and the 2022 rate shock when the
history covers them and otherwise scale each position's beta by the S&P 500
drawdown of that episode; --scenario adds a beta-scaled custom shock and
--shock a per-symbol what-if. A second ONE batched Yahoo download fetches
IJR/MTUM/VLUE/HYG (small-cap, momentum, value, credit proxies) and passes
them to risk.py as ``factors``; a failed proxy fetch just omits ``factors``
(echoed in ``sources.factors``), it never fails the run. Additive
``liquidity``: a ``{symbol, avg_dollar_volume, position_value, pct_of_adv}``
row per position from the main download's per-day volume (20-day average
dollar volume; null when volume is unavailable), plus an
``ILLIQUID_POSITION`` flag when a position exceeds ~1% of its average daily
dollar volume. Output is risk.py's contract plus ``as_of``, ``sources`` and
``liquidity``. stdin is unused. Exit codes: 0, 2, 4, 5 (SnapTrade or Yahoo
error), 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import risk  # noqa: E402
from second_opinion import market, output, proxies  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

# S&P 500 peak-to-trough closes for each episode
BUILTIN_SCENARIOS = [
    {"name": "2008 financial crisis", "start": "2007-10-09", "end": "2009-03-09", "benchmark_return": -0.5678},
    {"name": "2018 Q4 selloff", "start": "2018-09-20", "end": "2018-12-24", "benchmark_return": -0.1978},
    {"name": "2020 COVID crash", "start": "2020-02-19", "end": "2020-03-23", "benchmark_return": -0.3392},
    {"name": "2022 rate shock", "start": "2022-01-03", "end": "2022-10-12", "benchmark_return": -0.2543},
]

# Proxy factor ETFs: small-cap/size, momentum, value, credit
FACTOR_PROXIES = ["IJR", "MTUM", "VLUE", "HYG"]
_LIQUIDITY_LOOKBACK_DAYS = 20
_ILLIQUID_PCT_OF_ADV = 0.01


def _avg_dollar_volume(rows: list[dict]) -> float | None:
    """20-day average of close x volume from the tail of ``rows``; null when
    no row in the window carries both fields."""
    vols = [
        r["close"] * r["volume"]
        for r in rows[-_LIQUIDITY_LOOKBACK_DAYS:]
        if r.get("close") is not None and r.get("volume") is not None
    ]
    return sum(vols) / len(vols) if vols else None


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"stress.py: {message}")


def _pairs(items: list[str], flag: str) -> dict[str, float]:
    out = {}
    for item in items:
        key, sep, val = item.partition("=")
        try:
            out[key.strip().upper() if flag == "--shock" else key.strip()] = float(val)
        except ValueError as exc:
            raise InvalidInput(f"{flag} expects {'SYMBOL' if flag == '--shock' else 'NAME'}=RETURN (decimal), got {item!r}") from exc
        if not sep or not key.strip():
            raise InvalidInput(f"{flag} expects {'SYMBOL' if flag == '--shock' else 'NAME'}=RETURN (decimal), got {item!r}")
    return out


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="stress.py", add_help=False)
        p.add_argument("--account", action="append", default=None)
        p.add_argument("--partial", action="store_true")
        p.add_argument("--years", type=int, default=3)
        p.add_argument("--benchmark", default="SPY")
        p.add_argument("--shock", action="append", default=[])
        p.add_argument("--scenario", action="append", default=[])
        p.add_argument("--no-builtin", action="store_true")
        p.add_argument("--risk-free", type=float, default=0.0)
        p.add_argument("--as-of", dest="as_of", default=None)
        ns = p.parse_args(args)
        shocks = _pairs(ns.shock, "--shock")
        custom = _pairs(ns.scenario, "--scenario")
        as_of = date.fromisoformat(ns.as_of) if ns.as_of else date.today()
        benchmark = ns.benchmark.strip().upper()

        hub = router.load()
        hub.partial = ns.partial
        accounts = hub.list_accounts()
        if not accounts:
            raise ApiError("no open brokerage accounts are connected; use the connect skill", code="NO_ACCOUNTS")
        if ns.account:
            known = {a["account_id"] for a in accounts}
            unknown = [w for w in ns.account if w not in known]
            if unknown:
                raise hub.unknown_account_error(unknown)
            accounts = [a for a in accounts if a["account_id"] in set(ns.account)]
        book: dict[str, float] = {}
        names: dict[str, str | None] = {}
        cash = 0.0
        cash_like: list[str] = []
        for a in accounts:
            aid = a["account_id"]
            for pos in hub.get_portfolio(aid)["positions"] or []:
                sym = pos.get("symbol")
                name = pos.get("name")
                for _ in range(2):
                    if isinstance(sym, dict):
                        name = sym.get("description") or name
                        sym = sym.get("symbol")
                units, price = pos.get("units"), pos.get("price")
                if isinstance(sym, str) and sym and units and price is not None:
                    value = float(units) * float(price)
                    if proxies.is_cash_like(sym, name):
                        # a money-market fund or cash placeholder sits at $1.00 with no price
                        # history: it is cash for risk purposes, not a missing series
                        cash += value
                        if sym.upper() not in cash_like:
                            cash_like.append(sym.upper())
                        continue
                    book[sym.upper()] = book.get(sym.upper(), 0.0) + value
                    names[sym.upper()] = names.get(sym.upper()) or (name if isinstance(name, str) else None)
            for b in hub.get_balance(aid)["balances"] or []:
                if isinstance(b, dict) and b.get("cash") is not None:
                    cash += float(b["cash"])
        if not book:
            raise InvalidInput("no priced positions in the selected accounts")

        start = (as_of - timedelta(days=365 * ns.years)).isoformat()
        symbols = sorted(set(book) | {benchmark})
        histories = market.close_histories(symbols, start=start)
        # Tracking error is measured against each holding's own reference (bonds against BND,
        # international equity against VXUS, US equity against the benchmark); the bucket comes
        # from the cached Yahoo description the snapshot also uses. Unavailable -> every position
        # tracks the benchmark, as before.
        references: dict[str, str] = {}
        proxy_flags: list[dict] = []
        try:
            info = market.sectors(sorted(book))
            for s in sorted(book):
                row = {**(info.get(s) or {})}
                row["name"] = row.get("name") or names.get(s)
                ref = proxies.tracking_reference(proxies.asset_bucket(s, row), benchmark)
                if ref:
                    references[s] = ref
        except Exception as e:  # noqa: BLE001 — additive: no buckets means the old benchmark-only tracking error
            references = {}
            proxy_flags.append({"code": "TRACKING_REFERENCES_UNAVAILABLE", "message": f"asset buckets unavailable ({e}); tracking error is against {benchmark} for every position"})
        # An institutional share class Yahoo has no history for borrows its public twin's
        # (VANG INST 500 IDX TR -> VOO). One extra batched call fetches the proxies and the
        # tracking references not already downloaded.
        proxied: dict[str, str] = {}
        wanted = {
            s: proxies.lookthrough_proxy_for(names.get(s))
            for s in book
            if not histories.get(s) and proxies.lookthrough_proxy_for(names.get(s)) not in (None, s)
        }
        extra = sorted({p for p in wanted.values() if p and not histories.get(p)} | {r for r in references.values() if not histories.get(r)})
        if extra:
            try:
                histories.update(market.close_histories(extra, start=start))
            except Exception as e:  # noqa: BLE001 — additive: a failed fetch leaves proxied classes unpriced and references unmeasured
                proxy_flags.append({"code": "PROXY_HISTORY_UNAVAILABLE", "message": f"proxy and reference price history fetch failed ({e}); institutional share classes stay unpriced"})
        for s, proxy in sorted(wanted.items()):
            if proxy and histories.get(proxy):
                histories[s] = histories[proxy]
                proxied[s] = proxy
        reference_prices = {r: histories[r] for r in sorted(set(references.values())) if histories.get(r)}
        if proxied:
            uses = ", ".join(f"{s} uses {p}'s" + (" price history" if i == 0 else "") for i, (s, p) in enumerate(sorted(proxied.items())))
            proxy_flags.append({"code": "PROXY_HISTORY", "message": f"{uses} (institutional share classes Yahoo has no quotes for)"})
        try:
            factor_histories = market.close_histories(sorted(FACTOR_PROXIES), start=start)
        except Exception:  # noqa: BLE001 — factor betas are additive, never a failed run
            factor_histories = {}
        factors = {name: rows for name, rows in factor_histories.items() if rows}
        scenarios = [] if ns.no_builtin else list(BUILTIN_SCENARIOS)
        scenarios += [{"name": name, "benchmark_return": ret} for name, ret in custom.items()]
        params = {
            "positions": [{"symbol": s, "value": v} for s, v in sorted(book.items())], "cash": cash,
            "prices": {s: histories.get(s, []) for s in book},
            "benchmark": {"symbol": benchmark, "prices": histories.get(benchmark, [])},
            "scenarios": scenarios, "shocks": shocks, "risk_free": ns.risk_free,
        }
        if references:
            params["tracking_references"] = references
            params["reference_prices"] = reference_prices
        if factors:
            params["factors"] = factors
        try:
            result = risk.run_risk(params)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc

        liquidity = []
        for s, v in sorted(book.items()):
            adv = None if s in proxied else _avg_dollar_volume(histories.get(s, []))
            pct = v / adv if adv else None
            liquidity.append(
                {
                    "symbol": s,
                    "avg_dollar_volume": round(adv, 2) if adv is not None else None,
                    "position_value": round(v, 2),
                    "pct_of_adv": round(pct, 4) if pct is not None else None,
                }
            )
        result["flags"] = result["flags"] + [
            {
                "code": "ILLIQUID_POSITION",
                "message": f"{r['symbol']} is {round(r['pct_of_adv'] * 100, 1)}% of 20-day average dollar volume",
            }
            for r in liquidity
            if r["pct_of_adv"] is not None and r["pct_of_adv"] > _ILLIQUID_PCT_OF_ADV
        ]
        result["liquidity"] = liquidity
        result["flags"] = result["flags"] + proxy_flags + hub.unavailable_flags()
        return {
            "as_of": as_of.isoformat(),
            "sources": {
                "holdings": router.holdings_source(accounts), "prices": "yahoo", "benchmark": benchmark, "factors": sorted(factors),
                "proxies": proxied, "cash_like": sorted(cash_like), "tracking_references": references,
            },
            **result,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
