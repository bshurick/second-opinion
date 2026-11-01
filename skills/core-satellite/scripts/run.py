#!/usr/bin/env python3
"""Usage: run.py mix
       run.py add AMOUNT
       run.py deposit AMOUNT [--satellite AMOUNT]
       run.py grow [--to-weight W | --by-points P | --by-relative R | --by X | --amount A]
       run.py new-pick SYMBOL [--amount A]
       run.py plan-step
       run.py rebalance
       common: [--weighting equal|market_cap|valuation|size] [--include-light] [--over-ceiling]
               [--whole-shares] [--sell SYM[,SYM]] [--short-term R] [--long-term R] [--partial]

Core/satellite sleeves on the connected accounts: reads positions, per-account cash, quotes and
tax lots once (rebalancing's plan.read_book), the saved core-satellite settings, the account roles
from the profile, Yahoo quote types and sectors, and the stock-screener pick store, then runs
sleeves.py. stdin is unused.

A saved employer_symbol of "none" (any case) means no employer stock.

Account role: the profile's ``account_roles`` entry, else retirement when the raw account type
looks tax-advantaged, else trading. Bucket: employer for the saved employer symbol (satellite
instead when the pick store has a deep pick for it); core when the
quote type is ETF or MUTUALFUND, the sector entry carries fund_sectors or a look-through proxy, or
it is an EQUITY with no sector and a fund-shaped name (market.looks_like_a_fund_name: Yahoo
reports SPYM, "SPDR Portfolio S&P 500 ETF", that way); cash for MONEYMARKET; satellite only for
a plain EQUITY. A holding of any other or unknown type is left out (UNCLASSIFIED). A broker that
reports its money-market core position (Fidelity's SPAXX) both as a holding and as the account's
cash is counted once: per account with cash above 0, the one cash-bucket position within $1 or 1%
of that cash (the closest, when more than one) is dropped, the rule portfolio-snapshot uses. Core
sale order: ``core_rank`` from the shared asset_bucket (second_opinion.proxies, the buckets
portfolio-snapshot uses): US equity 0, international equity 1, other or unknown 2, bonds 3.
``--sell`` names core funds sold first, in the order given, before that order (``sell_first``);
each must be a core fund held in a trading account, else bad input. Picks: each held satellite
symbol saved in the pick store.
A deep pick's central_value is its baseline's central scenario value and its expected_return is
the first scenario's annual return at today's price (track_math); a light pick's central_value
is fair_values.base and its expected_return is the 3-year convergence estimate (base / price)
** (1/3) - 1 (null when price or base is 0 or below). age_days counts from baseline_as_of;
recheck_due is set when the pick is awaiting a filing, its next earnings date has passed with no
check on or after it, it has no next earnings date and is more than 120 days old
(STALE_NO_EARNINGS_DAYS), or its last check status is "outside"; sleeves.py treats an unknown
age as due too. needs_valuation marks the last two, which a re-check cannot clear.
A baseline that cannot be read
(or a deep model with no scenarios) leaves the symbol out of picks (PICK_BASELINE_MISSING) and
puts it in ``unreadable_picks``, so it holds; without the stock-screener skill there are no picks
(NO_PICK_STORE), and an unreadable pick store gives no picks (PICK_STORE_UNREADABLE) and sets
``pick_store_unreadable``, which stops ``rebalance``. The effective strategy is ``--weighting``,
else the saved one, else equal; under market_cap the held picks' company market caps are read
(``market_caps``, null for one that fails) only for a mode that trades: add, grow, plan-step,
rebalance, new-pick with --amount, deposit with --satellite. A holding with no price is left out (NO_PRICE). The grow values
--to-weight, --by-points, --by-relative and --by are fractions (0.05 = 5%); ``--by X`` is a
percent whose reading (points or relative) is unclear, and both readings are returned. ``new-pick``
takes only a plain EQUITY that is not fund-marked (else bad input naming its type), prices it
from one quote (no price is bad input) and passes the left-out symbols (UNCLASSIFIED and
NO_PRICE) as ``excluded_symbols``, so a held symbol left out of the plan is still refused.

With employer_symbol unset, the trading accounts' last two years of transactions are read for
stock deposited in kind from an equity-plan administrator (a description naming Shareworks, a
stock plan, an equity award, RSUs, vesting, ESPP and the like). The stock with the most such
deposits is ``employer_candidate``: {symbol, deposits (dates), vests (deposits more than 30 days
apart count as separate vests), every_days (median days between vests; null with one vest),
sold_within_days (median days from a vest to the next sale of the symbol; null when none)}, and
the employer_symbol DECISION_NEEDED message names it. It is never saved without the person's yes.
``new-pick`` also reads the new symbol's saved valuation into ``picks``, only so its open re-check
(RECHECK_DUE) and needed valuation rerun (DEEP_VALUATION_NEEDED) are flagged; the pick still opens
at the median.

Output: sleeves.py's contract plus ``sources`` (holdings, prices, lots), ``no_price`` and
``employer_candidate`` (null when employer_symbol is saved or no vest deposit is found). This is a
plan; orders go through the portfolio-analysis trading protocol with a human yes.

Exit codes: 0, 2 (bad input), 4 (credentials, ETRADE_REAUTH), 5 (API error), 6 (missing deps).

When a direct broker (E*Trade) only needs today's login, the script exits 4 with code
ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs without that broker
and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE.parents[1] / "rebalancing" / "scripts"))
sys.path.insert(0, str(_HERE))

import plan  # noqa: E402
import settings as cs_settings  # noqa: E402
import sleeves  # noqa: E402
from second_opinion import market, output, profile, proxies  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

SCREENER_DIR = _HERE.parents[1] / "stock-screener" / "scripts"
_FUND_TYPES = {"ETF", "MUTUALFUND"}
STALE_NO_EARNINGS_DAYS = 120   # a pick with no next earnings date is due for a recheck after this
VEST_HISTORY_DAYS = 730        # how far back the employer-candidate read looks
VEST_GAP_DAYS = 30             # deposits closer than this are one vest
_VEST_RE = re.compile(r"shareworks|stock plan|equity (award|edge)|\brsus?\b|\bvest|restricted stock|\bespp\b"
                      r"|computershare|at work|global shares|\bcarta\b", re.I)
_NOT_DEPOSITS = {"BUY", "SELL", "DIVIDEND", "REI", "SPLIT"}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"run.py: {message}")


def _flag(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _screener():
    """The stock-screener picks module (its own ``import track_math`` resolves from its
    directory), or None when that skill is not installed."""
    path = SCREENER_DIR / "picks.py"
    if not path.is_file():
        return None
    if str(SCREENER_DIR) not in sys.path:
        sys.path.insert(0, str(SCREENER_DIR))
    spec = importlib.util.spec_from_file_location("core_satellite_picks", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _roles(accounts: list[dict]) -> dict[str, dict]:
    prof = profile.load() or {}
    saved = ((prof.get("fields") or {}).get("account_roles") or {}).get("value") or {}
    out = {}
    for a in accounts:
        aid = a["account_id"]
        role = saved.get(aid) if isinstance(saved, dict) else None
        if role not in ("trading", "retirement", "savings"):
            role = "retirement" if plan.is_tax_advantaged(a.get("raw_type")) else "trading"
        out[aid] = {"role": role}
    return out


def _fund_marked(entry: dict) -> bool:
    """A fund by its sector entry: fund_sectors or a proxy, or a sector-less EQUITY with a
    fund-shaped name (Yahoo's label for SPYM when its fund data will not load)."""
    if entry.get("fund_sectors") is not None or entry.get("proxy") is not None:
        return True
    return (str(entry.get("quote_type") or "").upper() == "EQUITY" and not entry.get("sector")
            and market.looks_like_a_fund_name(entry.get("name")))


def _drop_sweep_copies(positions: list[dict], cash_by_account: dict[str, float]) -> list[dict]:
    """Positions without the money-market position a broker also reports as the account's cash.

    Per account with cash above 0, the cash-bucket position whose value is within $1 or 1% of
    that cash (the closest, when more than one) is the same money counted twice; it is dropped
    and the account's cash stays, since cash is what funds buys."""
    drop: set[int] = set()
    for aid, cash in cash_by_account.items():
        if cash <= 0:
            continue
        near = [(abs(cash - p["units"] * p["price"]), i) for i, p in enumerate(positions)
                if p["account"] == aid and p["bucket"] == "cash"
                and abs(cash - p["units"] * p["price"]) <= max(1.0, 0.01 * p["units"] * p["price"])]
        if near:
            drop.add(min(near)[1])
    return [p for i, p in enumerate(positions) if i not in drop]


def _sell_first(raw: str | None, positions: list[dict], roles: dict[str, dict]) -> list[str]:
    """``--sell`` as a list of symbols; each must be a core fund held in a trading account."""
    if not raw:
        return []
    syms = list(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))
    held = {p["symbol"] for p in positions if p["bucket"] == "core" and roles[p["account"]]["role"] == "trading"}
    bad = [s for s in syms if s not in held]
    if bad:
        raise InvalidInput(f"--sell takes core funds held in a trading account; {', '.join(bad)} is not one")
    return syms


def _employer_candidate(hub, accounts: list[dict], roles: dict[str, dict], today: str) -> dict | None:
    """The stock deposited in kind most often from an equity-plan administrator in the trading
    accounts' last VEST_HISTORY_DAYS, with its vest dates, cadence and how soon it was sold."""
    start = (date.fromisoformat(today) - timedelta(days=VEST_HISTORY_DAYS)).isoformat()
    deposits: dict[str, list[str]] = {}
    sales: dict[str, list[str]] = {}
    for a in accounts:
        aid = a["account_id"]
        if roles[aid]["role"] != "trading":
            continue
        try:
            rows = hub.list_transactions(aid, start=start, end=today, count=1000).get("transactions") or []
        except ApiError:
            continue
        for t in rows:
            sym = str(((t.get("symbol") or {}).get("symbol")) or "").upper()
            day = str(t.get("trade_date") or "")[:10]
            kind = str(t.get("type") or "").upper()
            if not sym or not day:
                continue
            if kind == "SELL":
                sales.setdefault(sym, []).append(day)
            elif (kind not in _NOT_DEPOSITS and (t.get("units") or 0) > 0
                  and _VEST_RE.search(str(t.get("description") or ""))):
                deposits.setdefault(sym, []).append(day)
    if not deposits:
        return None
    sym = sorted(deposits, key=lambda s: (-len(deposits[s]), s))[0]
    days = sorted(set(deposits[sym]))
    vests = [d for i, d in enumerate(days)
             if i == 0 or (date.fromisoformat(d) - date.fromisoformat(days[i - 1])).days > VEST_GAP_DAYS]
    gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(vests, vests[1:])]
    sold = sorted(sales.get(sym) or [])
    waits = [(date.fromisoformat(next(s for s in sold if s >= d)) - date.fromisoformat(d)).days
             for d in days if any(s >= d for s in sold)]
    return {"symbol": sym, "deposits": days, "vests": vests,
            "every_days": round(statistics.median(gaps)) if gaps else None,
            "sold_within_days": round(statistics.median(waits)) if waits else None}


def _classify(positions: list[dict], info: dict, employer: str | None,
              deep: set[str] | frozenset[str] = frozenset()) -> tuple[list[dict], list[str]]:
    """Each position with its bucket, plus the symbols of unknown type (left out).

    employer for the saved employer symbol; core for quote type ETF or MUTUALFUND or a
    fund-marked entry (fund_sectors or proxy); cash for MONEYMARKET; satellite only for a
    plain EQUITY. With no quote type at all, the broker's name decides: a 401(k) trust matching
    a tracking ETF is core and a cash line is cash. Anything else is unclassified."""
    out, unknown = [], set()
    for p in positions:
        sym = p["symbol"]
        entry = info.get(sym) or {}
        qt = str(entry.get("quote_type") or "").upper()
        name = p.get("name")
        if employer and sym == employer and sym not in deep:
            bucket = "employer"
        elif qt in _FUND_TYPES or _fund_marked(entry) or (not qt and proxies.lookthrough_proxy_for(name)):
            bucket = "core"
        elif qt == "MONEYMARKET" or (not qt and proxies.is_cash_like(sym, name)):
            bucket = "cash"
        elif qt == "EQUITY":
            bucket = "satellite"
        else:
            unknown.add(sym)
            continue
        out.append({**p, "bucket": bucket})
    return out, sorted(unknown)


_CORE_RANK = {"us_equity": 0, "intl_equity": 1, "other": 2, "bonds": 3}


def _core_rank(positions: list[dict], info: dict) -> dict[str, int]:
    """Each core symbol's sale rank from the shared asset_bucket (portfolio-snapshot's buckets):
    US equity 0, international equity 1, other 2, bonds 3; unknown or cash 2."""
    out = {}
    for p in positions:
        if p["bucket"] == "core":
            entry = info.get(p["symbol"]) or {"name": p.get("name")}
            out[p["symbol"]] = _CORE_RANK.get(proxies.asset_bucket(p["symbol"], entry) or "", 2)
    return out


def _check_new_pick(sym: str, entry: dict | None) -> None:
    """Bad input unless ``sym`` is a plain EQUITY that is not fund-marked (fund_sectors or proxy)."""
    entry = entry or {}
    qt = str(entry.get("quote_type") or "").upper()
    if qt != "EQUITY":
        raise InvalidInput(f"{sym} is not a plain stock (quote type {qt or 'unknown'}); new-pick takes a single stock")
    if _fund_marked(entry):
        raise InvalidInput(f"{sym} is a fund (quote type EQUITY with fund holdings, a proxy or a fund name); new-pick takes a single stock")


def _employer_symbol(store: dict) -> str | None:
    """The saved employer ticker, upper case; None when unset or saved as "none" (any case)."""
    sym = str(store.get("employer_symbol") or "").strip().upper()
    return None if sym in ("", "NONE") else sym


def _needs_valuation(pick: dict, today: str, age_days: int | None = None) -> bool:
    """A re-check cannot clear it: the last check left every scenario ("outside"), or the pick
    has no next earnings date and is older than STALE_NO_EARNINGS_DAYS."""
    checks = pick.get("checks") or []
    if not pick.get("next_earnings") and age_days is not None and age_days > STALE_NO_EARNINGS_DAYS:
        return True
    return bool(checks) and (checks[-1] or {}).get("status") == "outside"


def _deep_symbols() -> set[str]:
    """Symbols with a saved deep pick; empty when the pick store is missing or unreadable
    (_picks raises the flag for that)."""
    pk = _screener()
    if pk is None:
        return set()
    try:
        store = pk.load()
    except ApiError:
        return set()
    return {str(p.get("symbol") or "").upper() for p in store.get("picks") or [] if p.get("kind") == "deep"}


def _recheck_due(pick: dict, today: str, age_days: int | None = None) -> bool:
    if pick.get("awaiting_filing"):
        return True
    checks = pick.get("checks") or []
    nxt = pick.get("next_earnings")
    if not nxt and age_days is not None and age_days > STALE_NO_EARNINGS_DAYS:
        return True
    if nxt and str(nxt)[:10] <= today and not any(str(c.get("date") or "")[:10] >= str(nxt)[:10] for c in checks):
        return True
    return bool(checks) and (checks[-1] or {}).get("status") == "outside"


def _age_days(as_of: object, today: str) -> int | None:
    try:
        return (date.fromisoformat(today) - date.fromisoformat(str(as_of)[:10])).days
    except ValueError:
        return None


def _market_caps(symbols: list[str]) -> dict[str, float | None]:
    """Each symbol's company market cap; None for one that cannot be read."""
    out: dict[str, float | None] = {}
    for sym in symbols:
        try:
            info = market.company_info(sym)
        except Exception:  # noqa: BLE001 — yfinance raises its own errors; degrade per symbol (NO_MARKET_CAP)
            out[sym] = None
            continue
        cap = info.get("market_cap")
        out[sym] = float(cap) if isinstance(cap, (int, float)) and not isinstance(cap, bool) else None
    return out


def _picks(satellite: dict[str, float], today: str, flags: list[dict], unreadable: list[str]) -> dict:
    """The sleeves.py ``picks`` input for each held satellite symbol in the pick store.

    A symbol whose saved valuation cannot be read is left out and appended to ``unreadable``."""
    pk = _screener()
    if pk is None:
        flags.append(_flag("NO_PICK_STORE", "the stock-screener skill is not installed, so there are no saved valuations"))
        return {}
    try:
        store = pk.load()
    except ApiError as exc:
        flags.append(_flag("PICK_STORE_UNREADABLE", f"the pick store could not be read ({exc}); no saved valuations are used"))
        return {}
    out = {}
    for pick in store.get("picks") or []:
        sym = str(pick.get("symbol") or "").upper()
        if sym not in satellite:
            continue
        try:
            baseline = pk.load_baseline(pick)
            if pick.get("kind") == "deep":
                model = baseline["model"]
                if not model.get("scenarios"):
                    raise ValueError("the model has no scenarios")
                central = pk.pick_levels(baseline)["central"]
                irr_flags: list[dict] = []
                irrs = pk.track_math._irrs(model, satellite[sym], irr_flags)
                expected = irrs.get((model.get("scenarios") or [{}])[0].get("name"))
                flags.extend(_flag(f["code"], f"{sym}: {f['message']}") for f in irr_flags)
            else:
                central = float(baseline["fair_values"]["base"])
                price = satellite[sym]
                expected = (central / price) ** (1 / 3) - 1 if price > 0 and central > 0 else None
        except (InvalidInput, ValueError, KeyError, TypeError, IndexError, OSError) as exc:
            flags.append(_flag("PICK_BASELINE_MISSING", f"{sym}: the saved valuation could not be read ({exc})"))
            unreadable.append(sym)
            continue
        age = _age_days(pick.get("baseline_as_of"), today)
        out[sym] = {"kind": pick.get("kind"), "central_value": central, "expected_return": expected,
                    "age_days": age, "recheck_due": _recheck_due(pick, today, age),
                    "needs_valuation": _needs_valuation(pick, today, age)}
    return out


def _quote_price(sym: str) -> float:
    rows = market.quote([sym]) or []
    price = next((r.get("price") for r in rows if str(r.get("symbol") or "").upper() == sym), None)
    if not isinstance(price, (int, float)) or price <= 0:
        raise InvalidInput(f"no price for {sym}; check the symbol")
    return float(price)


def _parser() -> _Parser:
    common = _Parser(add_help=False)
    common.add_argument("--weighting", choices=("equal", "market_cap", "valuation", "size"), default=None)
    common.add_argument("--include-light", action="store_true")
    common.add_argument("--over-ceiling", action="store_true")
    common.add_argument("--whole-shares", action="store_true")
    common.add_argument("--sell", default=None)
    common.add_argument("--short-term", type=float, default=0.24)
    common.add_argument("--long-term", type=float, default=0.15)
    common.add_argument("--partial", action="store_true")
    common.add_argument("--today", help=argparse.SUPPRESS)
    p = _Parser(prog="run.py", add_help=False)
    sub = p.add_subparsers(dest="mode", required=True, parser_class=_Parser)
    sub.add_parser("mix", add_help=False, parents=[common])
    sub.add_parser("add", add_help=False, parents=[common]).add_argument("amount", type=float)
    d = sub.add_parser("deposit", add_help=False, parents=[common])
    d.add_argument("amount", type=float)
    d.add_argument("--satellite", type=float, default=None)
    g = sub.add_parser("grow", add_help=False, parents=[common])
    ex = g.add_mutually_exclusive_group()
    ex.add_argument("--to-weight", type=float, dest="to_weight")
    ex.add_argument("--by-points", type=float, dest="by_points")
    ex.add_argument("--by-relative", type=float, dest="by_relative")
    ex.add_argument("--by", type=float, dest="by_ambiguous")
    ex.add_argument("--amount", type=float, dest="grow_amount")
    n = sub.add_parser("new-pick", add_help=False, parents=[common])
    n.add_argument("symbol")
    n.add_argument("--amount", type=float, default=None)
    sub.add_parser("plan-step", add_help=False, parents=[common])
    sub.add_parser("rebalance", add_help=False, parents=[common])
    return p


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        ns = _parser().parse_args(args)
        if ns.today:
            try:
                today = date.fromisoformat(ns.today).isoformat()
            except ValueError as exc:
                raise InvalidInput("--today must be YYYY-MM-DD") from exc
        else:
            today = date.today().isoformat()
        store = cs_settings.load()

        hub = router.load()
        hub.partial = ns.partial
        accounts = hub.list_accounts()
        if not accounts:
            raise ApiError("no open brokerage accounts are connected; use the connect skill", code="NO_ACCOUNTS")
        roles = _roles(accounts)
        book = plan.read_book(hub, accounts, date.fromisoformat(today))

        flags: list[dict] = []
        if book["no_price"]:
            flags.append(_flag("NO_PRICE", f"no price for {', '.join(book['no_price'])}; left out of the mix and the plan"))
        employer = _employer_symbol(store)
        new_sym = ns.symbol.strip().upper() if ns.mode == "new-pick" else None
        symbols = sorted({p["symbol"] for p in book["positions"]} | ({employer} if employer else set())
                         | ({new_sym} if new_sym else set()))
        info = market.sectors(symbols) if symbols else {}
        if new_sym:
            _check_new_pick(new_sym, info.get(new_sym))
        positions, unclassified = _classify(book["positions"], info, employer, _deep_symbols() if employer else set())
        positions = _drop_sweep_copies(positions, book["cash_by_account"])
        sell_first = _sell_first(ns.sell, positions, roles)
        if unclassified:
            flags.append(_flag("UNCLASSIFIED", f"type of {', '.join(unclassified)} is unknown (not a stock, fund or money market); left out of the mix and the plan"))
        prices = {p["symbol"]: p["price"] for p in positions if p["bucket"] == "satellite"}
        sectors = {s: (info.get(s) or {}).get("sector") for s in sorted(set(prices) | ({employer} if employer else set()))}
        employer_sector = (info.get(employer) or {}).get("sector") if employer and employer in info else None
        new_price = _quote_price(new_sym) if new_sym else None

        unreadable: list[str] = []
        picks = _picks({**prices, new_sym: new_price} if new_sym else prices, today, flags, unreadable)
        params = {
            "mode": ns.mode, "positions": positions, "accounts": roles,
            "cash_by_account": book["cash_by_account"], "settings": store,
            "picks": picks, "unreadable_picks": unreadable,
            "pick_store_unreadable": any(f["code"] == "PICK_STORE_UNREADABLE" for f in flags),
            "sectors": sectors, "employer_sector": employer_sector,
            "core_rank": _core_rank(positions, info), "sell_first": sell_first,
            "lots": book["lots"], "rates": {"short_term": ns.short_term, "long_term": ns.long_term},
            "today": today, "over_ceiling": ns.over_ceiling, "whole_shares": ns.whole_shares,
        }
        if ns.weighting:
            params["weighting"] = ns.weighting
        if ns.include_light:
            params["include_light"] = True
        if ns.mode in ("add", "deposit"):
            params["amount"] = ns.amount
        if ns.mode == "deposit" and ns.satellite is not None:
            params["satellite_amount"] = ns.satellite
        if ns.mode == "grow":
            fields = {"to_weight": ns.to_weight, "by_points": ns.by_points, "by_relative": ns.by_relative,
                      "by_ambiguous": ns.by_ambiguous, "amount": ns.grow_amount}
            params["grow"] = {k: v for k, v in fields.items() if v is not None}
        if ns.mode == "new-pick":
            params["new_pick"] = {"symbol": new_sym, "price": new_price}
            if ns.amount is not None:
                params["new_pick"]["amount"] = ns.amount
            params["excluded_symbols"] = sorted(set(unclassified) | set(book["no_price"]))
        trades = (ns.mode in ("add", "grow", "plan-step", "rebalance")
                  or (ns.mode == "new-pick" and ns.amount is not None)
                  or (ns.mode == "deposit" and ns.satellite is not None))
        if trades and (ns.weighting or store.get("weighting") or "equal") == "market_cap":
            params["market_caps"] = _market_caps(sorted(prices))
        try:
            result = sleeves.run_sleeves(params)
        except (ValueError, TypeError) as exc:     # KeyError and the like are bugs, not bad input
            raise InvalidInput(str(exc)) from exc
        candidate = None
        if store.get("employer_symbol") is None:
            candidate = _employer_candidate(hub, accounts, roles, today)
        if candidate:
            every = f", about every {candidate['every_days']} days" if candidate["every_days"] else ""
            sold = (f", sold within {candidate['sold_within_days']} days" if candidate["sold_within_days"] is not None
                    else "")
            note = (f"; account history shows {candidate['symbol']} shares deposited from an equity plan on "
                    f"{len(candidate['vests'])} vest dates ({candidate['vests'][0]} to {candidate['vests'][-1]}{every}{sold})")
            for f in result.get("flags") or []:
                if f["code"] == "DECISION_NEEDED" and f["message"].startswith("employer_symbol is unset"):
                    f["message"] += note
        result["flags"] = list(result.get("flags") or []) + flags + hub.unavailable_flags()
        return {**result, "sources": book["sources"], "no_price": book["no_price"], "employer_candidate": candidate}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
