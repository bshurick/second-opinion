#!/usr/bin/env python3
"""Usage: sleeve_run.py mix
       sleeve_run.py add AMOUNT
       sleeve_run.py new-pick SYMBOL [--amount A]
       sleeve_run.py rebalance
       common: [--weighting equal|market_cap|valuation|size] [--include-light] [--over-ceiling]
               [--whole-shares] [--sell SYM[,SYM]] [--short-term R] [--long-term R] [--partial]

The picks sleeve on the connected accounts (plan.py calls it; it runs on its own too): reads
positions, per-account cash, quotes and tax lots once (global_plan.read_book), the picks sleeve's
settings from settings.json (``_store``: the target in force from settings.glide_target, the
weighting, include_light, the short-term-gain policy and the employer members), the account roles
from settings.json, Yahoo quote types and sectors, and the stock-screener pick store, then runs
sleeves.py. stdin is unused.

A saved employer_symbol of "none" (any case) means no employer stock.

Account role: the saved ``accounts.<id>.role`` setting, else retirement when the raw account type
looks tax-advantaged, else trading. Bucket: employer for the saved employer symbol (satellite
instead when the pick store has a deep pick for it); core when the
quote type is ETF or MUTUALFUND, the sector entry carries fund_sectors or a look-through proxy, or
it is an EQUITY with no sector and a fund-shaped name (market.looks_like_a_fund_name: Yahoo
reports SPYM, "SPDR Portfolio S&P 500 ETF", that way); cash for MONEYMARKET; satellite only for
a plain EQUITY. A holding of any other or unknown type is left out (UNCLASSIFIED). A broker that
reports its money-market core position (Fidelity's SPAXX) both as a holding and as the account's
cash is counted once: per account with cash above 0, the one cash-bucket position within $1 or 1%
of that cash (the closest, when more than one) is dropped, the rule portfolio-analysis uses. Core
sale order: ``core_rank`` from the shared asset_bucket (second_opinion.proxies, the buckets
portfolio-analysis uses): US equity 0, international equity 1, other or unknown 2, bonds 3.
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
The saved depth (settings.json) goes to sleeves.py as ``depth``: at deep depth light picks hold
(DEEP_VALUATION_NEEDED) and --include-light exits 2.
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
it is used as the employer stock for this run, with a STANDING_DEFAULT flag naming the vest
evidence and the setting that changes it; with no candidate the run assumes no employer stock
(sleeves.py's STANDING_DEFAULT). The candidate is never saved without the person's yes.
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
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import global_plan  # noqa: E402
import sleeves  # noqa: E402
from second_opinion import holdings, market, output, settings  # noqa: E402
from second_opinion.holdings import (  # noqa: E402,F401  (re-exported under the old private names)
    core_rank as _core_rank, classify as _classify,
    drop_sweep_copies as _drop_sweep_copies, employer_candidate as _employer_candidate, fund_marked as _fund_marked)
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

SCREENER_DIR = _HERE.parents[1] / "stock-screener" / "scripts"
STALE_NO_EARNINGS_DAYS = 120   # a pick with no next earnings date is due for a recheck after this


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"sleeve_run.py: {message}")


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
    spec = importlib.util.spec_from_file_location("portfolio_plan_picks", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _roles(accounts: list[dict]) -> dict[str, dict]:
    return {a["account_id"]: {"role": settings.account_role(a["account_id"], a.get("raw_type"))} for a in accounts}


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


def _check_new_pick(sym: str, entry: dict | None) -> None:
    """Bad input unless ``sym`` is a plain EQUITY that is not fund-marked (fund_sectors or proxy)."""
    entry = entry or {}
    qt = str(entry.get("quote_type") or "").upper()
    if qt != "EQUITY":
        raise InvalidInput(f"{sym} is not a plain stock (quote type {qt or 'unknown'}); new-pick takes a single stock")
    if _fund_marked(entry):
        raise InvalidInput(f"{sym} is a fund (quote type EQUITY with fund holdings, a proxy or a fund name); new-pick takes a single stock")


def _store(today: str) -> dict:
    """The sleeve engine's settings, read from settings.json: ``ceiling`` is the picks sleeve's target in
    force (settings.glide_target; null when the sleeve has none, which leaves its size unmanaged)."""
    doc = settings.load()
    picks = doc["plan"]["sleeves"].get("PICKS") or {}
    members = (doc["plan"]["sleeves"].get("EMPLOYER") or {}).get("members")
    employer = None if members is None else (members[0] if members else "none")
    return {"ceiling": settings.glide_target(doc, "PICKS", date.fromisoformat(today)),
            "weighting": picks.get("weighting"), "include_light": picks.get("include_light"),
            "short_term_gain_policy": doc["taxes"].get("short_term_gain_policy"), "employer_symbol": employer}


def _employer_symbol(store: dict) -> str | None:
    """The saved employer ticker, upper case; None when unset or saved as "none" (any case)."""
    sym = str(store.get("employer_symbol") or "").strip().upper()
    return None if sym in ("", "NONE") else sym


def _current_checks(pick: dict) -> list[dict]:
    """The checks against the current baseline: a new deep valuation answers an "outside" before it."""
    return (pick.get("checks") or [])[int(pick.get("baseline_checks_from") or 0):]


def _needs_valuation(pick: dict, today: str, age_days: int | None = None) -> bool:
    """A re-check cannot clear it: the last check against the current baseline left every scenario
    ("outside"), or the pick has no next earnings date and is older than STALE_NO_EARNINGS_DAYS."""
    checks = _current_checks(pick)
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
    current = _current_checks(pick)
    return bool(current) and (current[-1] or {}).get("status") == "outside"


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
    p = _Parser(prog="sleeve_run.py", add_help=False)
    sub = p.add_subparsers(dest="mode", required=True, parser_class=_Parser)
    sub.add_parser("mix", add_help=False, parents=[common])
    sub.add_parser("add", add_help=False, parents=[common]).add_argument("amount", type=float)
    n = sub.add_parser("new-pick", add_help=False, parents=[common])
    n.add_argument("symbol")
    n.add_argument("--amount", type=float, default=None)
    sub.add_parser("rebalance", add_help=False, parents=[common])
    return p


def run(args: list[str]) -> dict:
    """One sleeve run: parse ``args`` (the usage above), read the accounts and plan; raises ScriptError."""
    ns = _parser().parse_args(args)
    if ns.today:
        try:
            today = date.fromisoformat(ns.today).isoformat()
        except ValueError as exc:
            raise InvalidInput("--today must be YYYY-MM-DD") from exc
    else:
        today = date.today().isoformat()
    store = _store(today)

    hub = router.load()
    hub.partial = ns.partial
    accounts = hub.list_accounts()
    if not accounts:
        raise ApiError("no open brokerage accounts are connected; use the connect skill", code="NO_ACCOUNTS")
    roles = _roles(accounts)
    book = global_plan.read_book(hub, accounts, date.fromisoformat(today))

    flags: list[dict] = []
    if book["no_price"]:
        flags.append(_flag("NO_PRICE", f"no price for {', '.join(book['no_price'])}; left out of the mix and the plan"))
    employer = _employer_symbol(store)
    candidate = None
    if store.get("employer_symbol") is None:
        candidate = _employer_candidate(hub, accounts, roles, today)
    if candidate:
        employer = candidate["symbol"]
        store = {**store, "employer_symbol": employer}
        flags.append(_flag("STANDING_DEFAULT", holdings.employer_default_message(candidate)))
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
        "today": today, "over_ceiling": ns.over_ceiling,
        "whole_shares": ns.whole_shares or settings.whole_shares(a["account_id"] for a in accounts),
    }
    if ns.weighting:
        params["weighting"] = ns.weighting
    if ns.include_light:
        params["include_light"] = True
    params["depth"] = settings.depth()
    if ns.mode == "add":
        params["amount"] = ns.amount
    if ns.mode == "new-pick":
        params["new_pick"] = {"symbol": new_sym, "price": new_price}
        if ns.amount is not None:
            params["new_pick"]["amount"] = ns.amount
        params["excluded_symbols"] = sorted(set(unclassified) | set(book["no_price"]))
    trades = ns.mode in ("add", "rebalance") or (ns.mode == "new-pick" and ns.amount is not None)
    if trades and (ns.weighting or store.get("weighting") or "equal") == "market_cap":
        params["market_caps"] = _market_caps(sorted(prices))
    try:
        result = sleeves.run_sleeves(params)
    except (ValueError, TypeError) as exc:     # KeyError and the like are bugs, not bad input
        raise InvalidInput(str(exc)) from exc
    result["flags"] = list(result.get("flags") or []) + flags + hub.unavailable_flags()
    return {**result, "sources": book["sources"], "no_price": book["no_price"], "employer_candidate": candidate}


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
