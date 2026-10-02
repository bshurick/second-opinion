#!/usr/bin/env python3
"""Usage: plan.py [--target KEY=WEIGHT ...] [--class SYMBOL=KEY ...] [--targets FILE] [--save] [--account ID ...] [--contribute AMOUNT] [--withdraw AMOUNT] [--no-sells] [--whole-shares] [--min-trade N] [--band-abs R] [--band-rel R] [--short-term R] [--long-term R] [--taxable ID ...] [--tax-advantaged ID ...] [--suggest-bands] [--only-if-breached] [--partial]

Rebalancing plan for the connected accounts: SnapTrade accounts once, positions
and balances once per account, one batched Yahoo quote for current prices
(falls back to the broker's price), then rebalance.py. Targets come from
--target/--class flags, from --targets FILE, or from ``targets.json`` in the
plugin data dir (written with --save). Cost basis: when ``ledger.json`` holds
BUY/SELL history for a symbol, entries are replayed FIFO per (symbol, account)
and open lots carry the holding period as their term (long/short, 365-day
split); symbols whose replayed open units do not match the broker within 1%
keep SnapTrade's average purchase price and the term stays unknown, so the
short-term rate is applied. ``lot_sources`` and ``sources.lots`` say which
source each symbol's lots came from. Accounts are classified taxable vs
tax-advantaged from their raw type (a guess, echoed in ``routing.accounts``;
--taxable and --tax-advantaged override it), and when a tax-advantaged account
exists sells are filled there first. ``--suggest-bands`` adds per-key annualized
volatility from one batched year of Yahoo closes and proposes band widths —
proposals, not advice. Output is rebalance.py's contract plus ``sources``,
``accounts``, ``holdings_by_account``, ``lot_sources`` and, with
--suggest-bands, ``suggested_bands``. stdin is unused. This is a plan; orders
go through the portfolio-analysis trading protocol.

Exit codes: 0, 2 (no targets, bad weights, unknown account), 4, 5, 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import rebalance  # noqa: E402
from second_opinion import ledger, market, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

TARGETS_FILE = "targets.json"
TAX_ADV_KEYWORDS = ("ira", "roth", "401", "403", "457", "hsa", "529", "pension", "tsp", "tfsa", "rrsp", "lira")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"plan.py: {message}")


def _pairs(items: list[str], flag: str, numeric: bool) -> dict:
    out: dict = {}
    for item in items:
        key, sep, val = item.partition("=")
        if not sep or not key.strip() or not val.strip():
            raise InvalidInput(f"{flag} expects KEY=VALUE, got {item!r}")
        if numeric:
            try:
                out[key.strip()] = float(val)
            except ValueError as exc:
                raise InvalidInput(f"{flag} weight must be a number, got {item!r}") from exc
        else:
            out[key.strip().upper()] = val.strip()
    return out


def _is_tax_advantaged(raw: object) -> bool:
    text = str(raw or "").lower()
    return any(k in text for k in TAX_ADV_KEYWORDS)


def _term(bought: str, today: date) -> str:
    """Long-term only when held more than one year: sold after the purchase's calendar
    anniversary (a Feb 29 purchase's anniversary is Feb 28), so 366 days across a leap
    day is still short-term."""
    try:
        start = date.fromisoformat(str(bought)[:10])
    except ValueError:
        return "short"
    try:
        anniversary = start.replace(year=start.year + 1)
    except ValueError:
        anniversary = date(start.year + 1, 2, 28)
    return "long" if today > anniversary else "short"


def _replay_lots(transactions: list, today: date) -> dict[str, list[dict]]:
    """Replay BUY/SELL/SPLIT ledger entries FIFO per (symbol, account) and keep
    the open lots with their holding-period term and owning account."""
    open_lots: dict[tuple[str, str], list[dict]] = {}
    for t in sorted(transactions or [], key=lambda e: str(e.get("date") or "")):
        kind = str(t.get("type") or "").upper()
        sym = str(t.get("symbol") or "").upper()
        if kind not in {"BUY", "SELL", "SPLIT"} or not sym:
            continue
        k = (sym, str(t.get("account_id") or ""))
        if kind == "BUY":
            units = float(t.get("units") or 0)
            if units <= 0:
                continue
            price = t.get("price")
            if price is None and t.get("amount") is not None:
                price = abs(float(t["amount"])) / units
            open_lots.setdefault(k, []).append(
                {"units": units, "cost": float(price or 0.0), "date": str(t.get("date") or "")}
            )
        elif kind == "SELL":
            remaining = float(t.get("units") or 0)
            for lot in open_lots.get(k, []):
                if remaining <= 1e-9:
                    break
                take = min(lot["units"], remaining)
                lot["units"] -= take
                remaining -= take
        else:
            try:
                ratio = float(t.get("split_ratio"))
            except (TypeError, ValueError):
                continue
            if ratio > 0:
                for lot in open_lots.get(k, []):
                    lot["units"] *= ratio
                    lot["cost"] /= ratio  # total cost basis is unchanged by a split
    out: dict[str, list[dict]] = {}
    for (sym, aid), entries in sorted(open_lots.items()):
        for e in entries:
            if e["units"] > 1e-9:
                out.setdefault(sym, []).append(
                    {
                        "units": e["units"],
                        "cost_per_unit": e["cost"],
                        "term": _term(e["date"], today),
                        "account": aid,
                    }
                )
    return out


def _suggest_bands(
    book: dict, targets: dict, classes: dict
) -> list[dict]:
    """Per-key annualized volatility from one batched year of Yahoo closes ->
    proposed band widths (absolute = clip(vol/4, 0.01, 0.15), relative =
    clip(1.5*vol, 0.10, 0.50)). Proposals, not advice; a key without history
    gets no suggestion."""
    members: dict[str, dict[str, float]] = {}
    for sym, row in sorted(book.items()):
        if row["price"] is None:
            continue
        key = sym if sym in targets else classes.get(sym)
        if key not in targets or key == "CASH":
            continue
        members.setdefault(key, {})[sym] = row["units"] * float(row["price"])
    if not members:
        return []
    symbols = sorted({s for m in members.values() for s in m})
    try:
        histories = market.close_histories(symbols, (date.today() - timedelta(days=365)).isoformat())
    except Exception:  # noqa: BLE001 — suggestions must never fail the run
        histories = {}
    closes: dict[str, dict[str, float]] = {}
    for sym, rows in (histories or {}).items():
        series: dict[str, float] = {}
        for r in rows or []:
            v = r.get("adj_close") if r.get("adj_close") is not None else r.get("close")
            d = r.get("date")
            if d and v:
                series[str(d)[:10]] = float(v)
        if len(series) >= 2:
            closes[sym] = series
    out: list[dict] = []
    for key in sorted(members):
        weights = members[key]
        total = sum(weights.values())
        if total <= 0:
            continue
        rets: dict[str, dict[str, float]] = {}
        for sym, series in closes.items():
            if sym not in weights:
                continue
            days = sorted(series)
            rets[sym] = {b: series[b] / series[a] - 1 for a, b in zip(days, days[1:])}
        weighted: list[float] = []
        for d in sorted({day for r in rets.values() for day in r}):
            num = den = 0.0
            for sym, r in rets.items():
                w = weights[sym] / total
                if d in r:
                    num += w * r[d]
                    den += w
            if den > 1e-12:
                weighted.append(num / den)
        if len(weighted) < 2:
            continue
        vol = statistics.stdev(weighted) * math.sqrt(252)
        out.append(
            {
                "key": key,
                "vol_annual": round(vol, 4),
                "absolute": round(min(max(vol / 4, 0.01), 0.15), 2),
                "relative": round(min(max(1.5 * vol, 0.10), 0.50), 2),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="plan.py", add_help=False)
        p.add_argument("--target", action="append", default=[])
        p.add_argument("--partial", action="store_true")
        p.add_argument("--class", dest="classes", action="append", default=[])
        p.add_argument("--targets", default=None)
        p.add_argument("--save", action="store_true")
        p.add_argument("--account", action="append", default=None)
        p.add_argument("--contribute", type=float, default=0.0)
        p.add_argument("--withdraw", type=float, default=0.0)
        p.add_argument("--no-sells", action="store_true")
        p.add_argument("--whole-shares", action="store_true")
        p.add_argument("--min-trade", type=float, default=0.0)
        p.add_argument("--band-abs", type=float, default=None)
        p.add_argument("--band-rel", type=float, default=None)
        p.add_argument("--short-term", type=float, default=0.24)
        p.add_argument("--long-term", type=float, default=0.15)
        p.add_argument("--taxable", action="append", default=[])
        p.add_argument("--tax-advantaged", action="append", default=[])
        p.add_argument("--suggest-bands", action="store_true")
        p.add_argument("--only-if-breached", action="store_true")
        ns = p.parse_args(args)

        default_file = ledger.ledger_path().parent / TARGETS_FILE
        if ns.target:
            targets, classes, source = _pairs(ns.target, "--target", True), _pairs(ns.classes, "--class", False), "inline"
        else:
            path = Path(ns.targets).expanduser() if ns.targets else default_file
            if not path.is_file():
                raise InvalidInput(f"no targets: pass --target KEY=WEIGHT ... (add --save to keep them) or --targets FILE; nothing at {path}")
            try:
                data = json.loads(path.read_text())
            except ValueError as exc:
                raise InvalidInput(f"{path} is not valid JSON") from exc
            targets, classes, source = data.get("targets") or {}, {str(k).upper(): v for k, v in (data.get("classes") or {}).items()}, str(path)
        if ns.save:
            default_file.parent.mkdir(parents=True, exist_ok=True)
            default_file.write_text(json.dumps({"targets": targets, "classes": classes}, indent=1))

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
        tax_adv = {a["account_id"]: _is_tax_advantaged(a.get("raw_type")) for a in accounts}
        for flag, want in (("--taxable", False), ("--tax-advantaged", True)):
            ids = getattr(ns, "tax_advantaged" if want else "taxable")
            unknown = [w for w in ids if w not in tax_adv]
            if unknown:
                raise InvalidInput(f"unknown account id(s) on {flag}: {', '.join(unknown)}; run accounts.py to list them")
            for w in ids:
                tax_adv[w] = want

        book: dict[str, dict] = {}
        cash = 0.0
        holdings_by_account: dict[str, list[str]] = {}
        for a in accounts:
            aid = a["account_id"]
            for pos in hub.get_portfolio(aid)["positions"] or []:
                sym = pos.get("symbol")
                for _ in range(2):
                    if isinstance(sym, dict):
                        sym = sym.get("symbol")
                if not isinstance(sym, str) or not sym:
                    continue
                sym = sym.upper()
                units = float(pos.get("units") or 0)
                if units <= 0:
                    continue
                row = book.setdefault(sym, {"units": 0.0, "price": None, "by_account": {}})
                row["units"] += units
                row["price"] = row["price"] if row["price"] is not None else pos.get("price")
                seg = row["by_account"].setdefault(aid, {"units": 0.0, "avg": None})
                seg["units"] += units
                avg = pos.get("average_purchase_price")
                if avg is not None:
                    seg["avg"] = float(avg)
                holdings_by_account.setdefault(aid, []).append(sym)
            for b in hub.get_balance(aid)["balances"] or []:
                if isinstance(b, dict) and b.get("cash") is not None:
                    cash += float(b["cash"])

        sources = {"holdings": router.holdings_source(accounts), "prices": "snaptrade", "targets": source}
        try:
            quotes = market.day_changes(sorted(book), hub=hub)
            if quotes:
                sources["prices"] = market.quote_sources(list(quotes.values())) or "yahoo"
                for sym, q in quotes.items():
                    if sym in book and q.get("price") is not None:
                        book[sym]["price"] = q["price"]
        except Exception:  # noqa: BLE001 — broker prices are the fallback
            pass

        # Lots: replay the ledger FIFO when its open units match the broker,
        # else fall back to SnapTrade's average purchase price (term unknown).
        replayed = _replay_lots(ledger.load().get("transactions") or [], date.today())
        lots: dict[str, list[dict]] = {}
        lot_sources: dict[str, str] = {}
        for sym in sorted(book):
            row = book[sym]
            open_units = sum(lot["units"] for lot in replayed.get(sym) or [])
            if replayed.get(sym) and abs(open_units - row["units"]) <= 0.01 + 0.01 * abs(row["units"]):
                lots[sym] = replayed[sym]
                lot_sources[sym] = "ledger"
            else:
                fallback = [
                    {"units": seg["units"], "cost_per_unit": seg["avg"], "term": "unknown", "account": aid}
                    for aid, seg in sorted(row["by_account"].items())
                    if seg["avg"] is not None
                ]
                if fallback:
                    lots[sym] = fallback
                lot_sources[sym] = "snaptrade"
        kinds = set(lot_sources.values())
        sources["lots"] = "ledger" if kinds == {"ledger"} else "mixed" if kinds == {"ledger", "snaptrade"} else "snaptrade"

        positions = []
        for sym in sorted(book):
            row = book[sym]
            if row["price"] is None:
                continue
            for aid in sorted(row["by_account"]):
                seg = row["by_account"][aid]
                if seg["units"] > 0:
                    positions.append({"symbol": sym, "units": seg["units"], "price": float(row["price"]), "account": aid})
        params = {
            "positions": positions, "cash": cash, "targets": targets, "classes": classes,
            "contribution": ns.contribute - ns.withdraw, "allow_sells": not ns.no_sells, "whole_shares": ns.whole_shares,
            "min_trade": ns.min_trade, "only_if_breached": ns.only_if_breached, "lots": lots,
            "rates": {"short_term": ns.short_term, "long_term": ns.long_term},
            "accounts": {aid: {"taxable": not adv} for aid, adv in sorted(tax_adv.items())},
        }
        bands = {}
        if ns.band_abs is not None:
            bands["absolute"] = ns.band_abs
        if ns.band_rel is not None:
            bands["relative"] = ns.band_rel
        if bands:
            params["bands"] = bands
        try:
            result = rebalance.run_rebalance(params)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        result["flags"] = list(result.get("flags") or []) + hub.unavailable_flags()
        out = {"sources": sources, "accounts": [a["account_id"] for a in accounts], "holdings_by_account": {k: sorted(set(v)) for k, v in sorted(holdings_by_account.items())}, "lot_sources": lot_sources, **result}
        if ns.suggest_bands:
            out["suggested_bands"] = _suggest_bands(book, targets, classes)
        return out

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
