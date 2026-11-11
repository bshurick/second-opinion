#!/usr/bin/env python3
"""Usage: global_plan.py [--target KEY=WEIGHT ...] [--class SYMBOL=KEY ...] [--targets FILE] [--save] [--account ID ...] [--contribute AMOUNT] [--withdraw AMOUNT] [--no-sells] [--whole-shares] [--min-trade N] [--band-abs R] [--band-rel R] [--short-term R] [--long-term R] [--taxable ID ...] [--tax-advantaged ID ...] [--suggest-bands] [--only-if-breached] [--partial]

The global portfolio plan for the connected accounts (plan.py calls it; it runs on its own too): SnapTrade accounts once, positions
and balances once per account, one batched Yahoo quote for current prices
(falls back to the broker's price), then rebalance.py. Targets come from
--target/--class flags, from --targets FILE, or from the ``plan.targets`` and
``plan.classes`` settings in ``settings.json`` (written with --save; class keys
are upper-cased). --short-term/--long-term default to the ``taxes.short_term_rate``
and ``taxes.long_term_rate`` settings. Cost basis: when ``ledger.json`` holds
BUY/SELL history for a symbol, entries are replayed FIFO per (symbol, account)
and open lots carry the holding period as their term (long/short, 365-day
split); symbols whose replayed open units do not match the broker within 1%
keep SnapTrade's average purchase price and the term stays unknown, so the
short-term rate is applied. ``lot_sources`` and ``sources.lots`` say which
source each symbol's lots came from. Accounts are classified taxable vs
tax-advantaged by their saved role (trading and savings are taxable, retirement
is tax-advantaged), else from their raw type (a guess); both are echoed in
``routing.accounts``, and --taxable and --tax-advantaged override them. When a
tax-advantaged account exists sells are filled there first. A sleeve key in the
targets (``PICKS``, ``EMPLOYER``) is one line: plain stocks in trading accounts
are PICKS and the saved employer member is EMPLOYER (holdings.classify);
a symbol that is a target itself or has a class keeps it, and holdings no key
reaches are left untouched (UNMAPPED). ``--suggest-bands`` adds per-key annualized
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
from second_opinion import holdings, ledger, market, output, settings  # noqa: E402
from second_opinion.settings import is_tax_advantaged  # noqa: E402,F401  (re-exported for older callers)
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"global_plan.py: {message}")


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


_is_tax_advantaged = is_tax_advantaged


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
                        "acquired": e["date"],
                        "account": aid,
                    }
                )
    return out


def _description(pos: dict) -> str | None:
    """The broker's description of a position; SnapTrade nests it under the symbol."""
    node, found = pos.get("symbol"), pos.get("description")
    while isinstance(node, dict):
        found = node.get("description") or found
        node = node.get("symbol")
    return str(found) if found else None


def read_book(hub, accounts: list[dict], today: date) -> dict:
    """Read positions, per-account cash, quotes and tax lots for the given accounts.
    Lots come from the FIFO ledger replay when its open units match the broker,
    else from the broker's average purchase price (term unknown). A symbol with
    neither a quote nor a broker price is listed in no_price and left out of
    positions."""
    book: dict[str, dict] = {}
    cash_by_account: dict[str, float] = {}
    held: dict[str, list[str]] = {}
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
            row = book.setdefault(sym, {"units": 0.0, "price": None, "by_account": {}, "name": _description(pos)})
            row["units"] += units
            row["price"] = row["price"] if row["price"] is not None else pos.get("price")
            seg = row["by_account"].setdefault(aid, {"units": 0.0, "avg": None})
            seg["units"] += units
            avg = pos.get("average_purchase_price")
            if avg is not None:
                seg["avg"] = float(avg)
            held.setdefault(aid, []).append(sym)
        total = 0.0
        for b in hub.get_balance(aid)["balances"] or []:
            if isinstance(b, dict) and b.get("cash") is not None:
                total += float(b["cash"])
        cash_by_account[aid] = total

    sources = {"holdings": router.holdings_source(accounts), "prices": "snaptrade"}
    try:
        quotes = market.day_changes(sorted(book), hub=hub)
        if quotes:
            sources["prices"] = market.quote_sources(list(quotes.values())) or "yahoo"
            for sym, q in quotes.items():
                if sym in book and q.get("price") is not None:
                    book[sym]["price"] = q["price"]
    except Exception:  # noqa: BLE001 — broker prices are the fallback
        pass

    replayed = _replay_lots(ledger.load().get("transactions") or [], today)
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
    no_price = []
    for sym in sorted(book):
        row = book[sym]
        if row["price"] is None:
            no_price.append(sym)
            continue
        for aid in sorted(row["by_account"]):
            seg = row["by_account"][aid]
            if seg["units"] > 0:
                positions.append({"symbol": sym, "units": seg["units"], "price": float(row["price"]), "account": aid, "name": row["name"]})
    return {
        "positions": positions, "cash_by_account": cash_by_account, "lots": lots, "lot_sources": lot_sources,
        "sources": sources, "holdings_by_account": {k: sorted(set(v)) for k, v in sorted(held.items())},
        "no_price": no_price,
    }


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


SLEEVE_KEYS = ("PICKS", "EMPLOYER")


def _employer(hub, accounts: list[dict], flags: list[dict]) -> str | None:
    """The employer stock: the saved plan.sleeves.EMPLOYER.members, or, unset, the vest-deposit
    candidate from account history (a STANDING_DEFAULT flag says so), else none."""
    members = settings.get("plan.sleeves.EMPLOYER.members")
    if members is not None:
        return str(members[0]).upper() if members and str(members[0]).lower() != "none" else None
    roles = {a["account_id"]: {"role": settings.account_role(a["account_id"], a.get("raw_type"))} for a in accounts}
    cand = holdings.employer_candidate(hub, accounts, roles, date.today().isoformat())
    if not cand:
        return None
    flags.append({"code": "STANDING_DEFAULT", "message": holdings.employer_default_message(cand)})
    return cand["symbol"]


def _buckets(positions: list[dict], employer: str | None) -> dict[tuple[str, str], str]:
    """(symbol, account) -> holdings.classify bucket (``employer`` from _employer; a saved deep pick
    of the employer stock is a pick); unknown types have no entry."""
    info = market.sectors(sorted({p["symbol"] for p in positions} | ({employer} if employer else set())))
    deep: set[str] = set()
    if employer:
        import sleeve_run  # noqa: PLC0415 — sleeve_run imports this module
        deep = sleeve_run._deep_symbols()
    classified, _ = holdings.classify(positions, info, employer, deep)
    return {(p["symbol"], p["account"]): p["bucket"] for p in classified}


def sleeve_positions(positions: list[dict], accounts: list[dict], keys: set[str], keep: set[str],
                     buckets: dict[tuple[str, str], str]) -> list[dict]:
    """Positions with ``key`` set to their sleeve, for the sleeve names in ``keys``: a plain stock in a
    trading account is PICKS, an EMPLOYER member is EMPLOYER. A symbol in ``keep`` (a target itself or
    one with an explicit class) is left as it is."""
    trading = {a["account_id"] for a in accounts if settings.account_role(a["account_id"], a.get("raw_type")) == "trading"}
    out = []
    for p in positions:
        b = buckets.get((p["symbol"], p["account"]))
        key = None
        if p["symbol"] not in keep:
            if b == "satellite" and p["account"] in trading and "PICKS" in keys:
                key = "PICKS"
            elif b == "employer" and "EMPLOYER" in keys:
                key = "EMPLOYER"
        out.append({**p, "key": key} if key else p)
    return out


def _weights(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    return {k: round(v / total, 6) for k, v in sorted(values.items())} if total > 0 else {}


def run(args: list[str], *, overrides: dict | None = None) -> dict:
    """One global plan: parse ``args`` (the usage above), read the accounts and plan; raises ScriptError.

    ``overrides`` (for the plan.py dispatcher) may set ``targets`` (used instead of any flag, file or
    saved targets; saved classes still apply), ``derive`` ("core": today's weights of the core funds
    held; "all": today's weights of every holding and the cash), ``freeze_sleeves`` (picks and
    employer stock left untouched even with no sleeve key in the targets), ``buy_cash_spent``
    ({account: cash already spent}; contribution buys then land in accounts with the cash left),
    ``cash`` (the cash the
    plan may use instead of the accounts' cash) and ``contribution`` (instead of
    --contribute/--withdraw). The output then carries ``targets_used``."""
    overrides = overrides or {}
    if overrides.get("derive") not in (None, "core", "all"):
        raise ValueError("overrides.derive must be core or all")
    p = _Parser(prog="global_plan.py", add_help=False)
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
    p.add_argument("--short-term", type=float, default=None)
    p.add_argument("--long-term", type=float, default=None)
    p.add_argument("--taxable", action="append", default=[])
    p.add_argument("--tax-advantaged", action="append", default=[])
    p.add_argument("--suggest-bands", action="store_true")
    p.add_argument("--only-if-breached", action="store_true")
    ns = p.parse_args(args)

    if ns.short_term is None:
        ns.short_term = settings.get("taxes.short_term_rate")
    if ns.long_term is None:
        ns.long_term = settings.get("taxes.long_term_rate")
    if overrides.get("derive"):
        targets, classes, source = {}, {}, "derived"
    elif "targets" in overrides:
        targets, source = dict(overrides["targets"]), "overrides"
        classes = {str(k).upper(): v for k, v in settings.get("plan.classes").items()}
    elif ns.target:
        targets, classes, source = _pairs(ns.target, "--target", True), _pairs(ns.classes, "--class", False), "inline"
    elif ns.targets:
        path = Path(ns.targets).expanduser()
        if not path.is_file():
            raise InvalidInput(f"no targets: nothing at {path}; pass --targets FILE with an existing file, or --target KEY=WEIGHT ... (add --save to keep them)")
        try:
            data = json.loads(path.read_text())
        except ValueError as exc:
            raise InvalidInput(f"{path} is not valid JSON") from exc
        targets, classes, source = data.get("targets") or {}, {str(k).upper(): v for k, v in (data.get("classes") or {}).items()}, str(path)
    else:
        targets = settings.get("plan.targets")
        if not targets:
            raise InvalidInput(f"no targets: pass --target KEY=WEIGHT ... (add --save to keep them) or --targets FILE; none saved in {settings.path()}")
        classes = {str(k).upper(): v for k, v in settings.get("plan.classes").items()}
        source = str(settings.path())
    if ns.save and source not in (str(settings.path()), "derived", "overrides"):  # saved already, or not the user's targets
        settings.set_value("plan.targets", targets)
        settings.set_value("plan.classes", classes)

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
    tax_adv = {a["account_id"]: settings.account_role(a["account_id"], a.get("raw_type")) == "retirement" for a in accounts}
    for flag, want in (("--taxable", False), ("--tax-advantaged", True)):
        ids = getattr(ns, "tax_advantaged" if want else "taxable")
        unknown = [w for w in ids if w not in tax_adv]
        if unknown:
            raise InvalidInput(f"unknown account id(s) on {flag}: {', '.join(unknown)}; run accounts.py to list them")
        for w in ids:
            tax_adv[w] = want

    held = read_book(hub, accounts, date.today())
    sources = {"holdings": held["sources"]["holdings"], "prices": held["sources"]["prices"], "targets": source, "lots": held["sources"]["lots"]}
    positions, lots, lot_sources = held["positions"], held["lots"], held["lot_sources"]
    holdings_by_account = held["holdings_by_account"]
    # the acquired date is for other callers; plan output stays as before
    plan_lots = {s: [{k: v for k, v in lot.items() if k != "acquired"} for lot in ls] for s, ls in lots.items()}
    cash = float(overrides["cash"]) if "cash" in overrides else sum(held["cash_by_account"].values())
    derive = overrides.get("derive")
    sleeves = {k for k in SLEEVE_KEYS if k in targets or overrides.get("freeze_sleeves")}
    employer_flags: list[dict] = []
    buckets = _buckets(positions, _employer(hub, accounts, employer_flags)) if sleeves or derive == "core" else {}
    if sleeves:
        positions = sleeve_positions(positions, accounts, sleeves, set(targets) | set(classes), buckets)
    if derive == "core":
        core: dict[str, float] = {}
        for pos in positions:
            if buckets.get((pos["symbol"], pos["account"])) == "core":
                core[pos["symbol"]] = core.get(pos["symbol"], 0.0) + pos["units"] * pos["price"]
        targets, classes, sources["targets"] = _weights(core), {}, "held core funds"
        if not targets:
            raise InvalidInput("no core funds are held to buy; save targets or name a fund (portfolio-plan settings)")
    elif derive == "all":
        held_value: dict[str, float] = {}
        for pos in positions:
            held_value[pos["symbol"]] = held_value.get(pos["symbol"], 0.0) + pos["units"] * pos["price"]
        if cash > 0:
            held_value["CASH"] = cash
        targets, classes, sources["targets"] = _weights(held_value), {}, "held weights"
        if targets:
            drift = round(1.0 - sum(targets.values()), 6)
            first = max(targets, key=targets.get)
            targets[first] = round(targets[first] + drift, 6)
    book: dict[str, dict] = {}
    for pos in positions:
        row = book.setdefault(pos["symbol"], {"units": 0.0, "price": pos["price"]})
        row["units"] += pos["units"]
    params = {
        "positions": positions, "cash": cash, "targets": targets, "classes": classes,
        "contribution": float(overrides["contribution"]) if "contribution" in overrides else ns.contribute - ns.withdraw, "allow_sells": not ns.no_sells, "whole_shares": ns.whole_shares or settings.whole_shares(a["account_id"] for a in accounts),
        "min_trade": ns.min_trade, "only_if_breached": ns.only_if_breached, "lots": plan_lots,
        "rates": {"short_term": ns.short_term, "long_term": ns.long_term},
        "accounts": {aid: {"taxable": not adv} for aid, adv in sorted(tax_adv.items())},
        "freeze_unmapped": bool(sleeves or derive),
    }
    if "buy_cash_spent" in overrides:
        spent = overrides["buy_cash_spent"] or {}
        params["buy_cash"] = {aid: max(0.0, v - float(spent.get(aid) or 0.0)) for aid, v in held["cash_by_account"].items()}
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
    result["flags"] = list(result.get("flags") or []) + employer_flags + hub.unavailable_flags()
    out = {"sources": sources, "accounts": [a["account_id"] for a in accounts], "holdings_by_account": holdings_by_account, "lot_sources": lot_sources, **result}
    if overrides:
        out["targets_used"] = targets
    if ns.suggest_bands:
        out["suggested_bands"] = _suggest_bands(book, targets, classes)
    return out


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
