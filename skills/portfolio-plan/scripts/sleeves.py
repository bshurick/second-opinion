#!/usr/bin/env python3
"""Usage: sleeves.py < input.json

The picks sleeve's inside engine (portfolio-plan): the mix of core funds, single-stock picks
(satellite), employer stock and cash across all accounts, and per-account trade plans that move money
into the picks (by the saved weighting strategy) without passing the sleeve's target (``ceiling``: the
target in force, 1.0 when the sleeve has none): a fixed amount or a new pick. ``rebalance`` moves money
between the picks and adds none.

Reads one JSON object from stdin and writes one JSON object to stdout. Exit
code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "mode": "mix" | "add" | "new-pick" | "rebalance",
      "positions": [{"symbol", "units", "price", "account",
                     "bucket": "core" | "satellite" | "employer" | "cash"}],
      "accounts": {aid: {"role": "trading" | "retirement" | "savings"}},
      "cash_by_account": {aid: float},
      "settings": {...},                     # sleeve_run._store(): ceiling (target in force or null),
                                             # weighting, include_light, short_term_gain_policy, employer_symbol
      "picks": {SYM: {...}}, "sectors": {SYM: str}, "employer_sector": str | null,
      "lots": {SYM: [{units, cost_per_unit, term, account?, acquired?}]},
      "rates": {"short_term", "long_term"}, "today": "YYYY-MM-DD",
      "amount": float,                       # add: money into picks
      "new_pick": {"symbol", "price", "amount"?},   # new-pick: a symbol not held
      "excluded_symbols": [SYM],             # new-pick: held symbols left out of positions
      "core_rank": {SYM: int},               # core sale order: 0 US equity, 1 international,
                                             # 2 other or unknown (the default), 3 bonds
      "sell_first": [SYM],                   # optional: core funds sold first, in this order
      "weighting": "equal" | "market_cap" | "valuation" | "size",   # optional; wins over settings.weighting
      "market_caps": {SYM: float | null},    # market_cap: each pick's company market cap
      "unreadable_picks": [SYM],             # picks whose saved data could not be read: they take no money
      "pick_store_unreadable": bool,         # rebalance: bad input when true, the holds cannot be known
      "include_light": bool,                 # optional; wins over settings.include_light; refused at deep depth
      "allocation": "fill" | "split",        # optional, default fill: how added money is split (see below)
      "depth": "standard" | "deep",          # optional, default standard; deep holds light picks
                                             # (DEEP_VALUATION_NEEDED), ignores a saved include_light,
                                             # and refuses new-pick on a light pick
      "over_ceiling": false, "whole_shares": false
    }

    picks[SYM] = {"kind": "deep" | "light", "central_value", "expected_return",
                  "age_days", "recheck_due", "needs_valuation"?}

Output JSON contract (stdout)::

    {
      "mode", "mix": {total, core, satellite, employer, cash: {value, weight},
                      trading_value, trading_cash, retirement_value, n_eff, tracking_error, ceiling,
                      ceiling_source: "target" | "none", proposed_size,
                      room_under_ceiling, single_stock_total},
      "weighting_used": "equal" | "market_cap" | "valuation" | "size",
                                      # the strategy applied; equal when valuation found no eligible pick
      "splits": [{symbol, current, target, delta, account, flags}],
                                      # split flags: PICK_CAP, NO_MARKET_CAP, PICK_BASELINE_MISSING,
                                      # LIGHT_VALUATION, NO_SAVED_VALUATION, RECHECK_DUE,
                                      # HELD_FOR_RECHECK, DEEP_VALUATION_NEEDED,
                                      # IN_BAND, TRIM_HELD_BACK, TRIM_UNPLACEABLE (rebalance)
      "held_back": [{symbol, value, account, long_term_date}],
      "accounts": [{account, funding: {cash, core_sells}, rebalance}],
      "trades": [every account's rebalance trades, each with account],
      "new_pick": null | {symbol, needed, allocated, account},
      "over_ceiling_amount",
      "unallocated_amount",           # money left as cash: pick-cap leftover, buys scaled
                                      # down by ACCOUNT_SHORT, whole-share rebalance remainder
      "satellite_net",                # satellite-pick BUY values less SELL values in trades
      "settings_used": {ceiling, weighting, allocation, include_light, short_term_gain_policy,
                        employer_symbol, depth},
      "flags": [{code, message}]   # STANDING_DEFAULT, PICK_IN_RETIREMENT,
                                   # EMPLOYER_CONCENTRATION, LOW_N_EFF, SECTOR_HEAVY,
                                   # ABOVE_CEILING, NO_SATELLITE, ACCOUNT_SHORT,
                                   # UNALLOCATED, VALUATION_FALLBACK, LIGHT_VALUATION,
                                   # NO_SAVED_VALUATION, RECHECK_DUE, HELD_FOR_RECHECK,
                                   # DEEP_VALUATION_NEEDED, NO_MARKET_CAP,
                                   # CORE_HELD_BACK, TRIM_HELD_BACK, TRIM_UNPLACEABLE,
                                   # BOND_FUND_SOLD
    }

Method: total is every position in every account plus all cash. Satellite
value counts satellite holdings in every account (retirement copies get
PICK_IN_RETIREMENT and no trades); employer stock is its own bucket and is
outside the ceiling, N_eff and tracking error. N_eff is over per-symbol
satellite values. ``add`` spreads ``amount`` over the trading-account picks
(fill or split, below), sends each pick's whole delta to the trading
account holding more of it (tie: account id order), and limits buys to the
room under the target in force (none: no limit) unless
``over_ceiling``. An account short of cash moves the shortfall to another
trading account that holds the same pick, else its buys are scaled down
(ACCOUNT_SHORT). Each trading account with a change gets its own
``run_rebalance`` call: picks are symbol targets, core funds are class
``core``, employer and other rows are left out, CASH takes the rest; sells
use the smallest-gain order.

Adding money (``add``, and the rest of ``new-pick`` with ``amount``) only buys: it never sells a pick.
Allocation ``fill`` (the default, every strategy but ``size``): each pick taking money has a target of
its raw weight's share of those picks' value plus the amount, and the amount goes to the gaps below
target (weights.fill_gaps), so a pick at or above target gets nothing. ``new-pick`` with ``amount``
puts the new symbol in the fill at 0 with its own raw weight (valuation: its saved pick's tilt factor,
neutral without one; market_cap: ``market_caps`` for it; equal: 1); under ``size``, ``split``, with no
existing trading-account pick, or with no market cap for it (NO_MARKET_CAP) it opens at the median
and the rest goes to the picks as for ``add``. Allocation ``split``: ``amount`` by the raw weights,
whatever the picks hold. The strategy's raw weights
(weights.strategy_weights) are ``equal`` 1, ``market_cap`` the company's market cap, ``valuation``
weights.tilt_factor and ``size`` the current value, whatever else the picks hold; ``equal`` is used
when nothing is saved. A pick takes no money when it is due for a recheck or of unknown age
(HELD_FOR_RECHECK, or DEEP_VALUATION_NEEDED when ``needs_valuation``), is in ``unreadable_picks``
(PICK_BASELINE_MISSING), or under ``market_cap`` has no finite market cap above 0 (NO_MARKET_CAP); no
market cap for any other pick is bad input.
The 5% pick cap limits buys under every strategy but ``size``: the overflow goes to the other picks by
their shares, and what no pick can take stays as cash (UNALLOCATED). The employer symbol can be a new
pick when ``picks`` has a deep entry for it, and EMPLOYER_CONCENTRATION counts it in every bucket.

An unset (null) ``settings.employer_symbol`` raises STANDING_DEFAULT ("employer_symbol is
unset: ..."); a saved "none" means no employer stock.

Valuation weighting: a pick is eligible when its kind is deep (or light with ``include_light``) and
it has central_value and expected_return; confidence is ``weights.confidence(age_days, recheck_due)``,
and an age_days of null counts as recheck_due (RECHECK_DUE). The score is absolute (see weights.py), so
near-equal returns give near-equal splits. An ineligible pick gets the neutral weight (1). An overvalued
pick (price above central_value x 1.05, weights.TRIM_MIN_GAP) gets a smaller share and, when adding
money, is not sold. With no eligible pick of confidence above 0 an add's weights are all neutral, so the
split comes out equal (VALUATION_FALLBACK) and ``weighting_used`` is equal.

Funding a new pick: each trading
account funds its buys from its own cash, then by selling its own core funds:
the ``sell_first`` funds in their order, then the rest by ``core_rank`` (US
equity, international, other, bonds last), then in the smallest-gain
order run_rebalance uses (each fund limited to what the
short-term-gain policy lets it sell); retirement
core is never sold. A core sale takes loss lots (cost at or above price), then long-term gain lots,
then short-term or unknown-term gain lots (and units with no lot) only when short_term_gain_policy is
allow, using only those lots for its tax estimate. Under hold, or unset (STANDING_DEFAULT, hold assumed), the blocked part of an
account's shortfall is a held_back row for the core fund (CORE_HELD_BACK) whose long_term_date
is acquired + 1 year + 1 day (Feb 29 -> Mar 1; null without a date), and
money no account can fund is unallocated_amount. A sale of a bond-ranked fund adds
BOND_FUND_SOLD.

``new-pick`` sizes a pick not yet held at ``needed``: the median trading value of the current picks,
capped at the 5% pick cap (``amount`` when there are none). The strategy does not change its size. A
saved pick due for a recheck or of unknown age still opens at the median, flagged RECHECK_DUE, or
DEEP_VALUATION_NEEDED when ``needs_valuation``. It goes to the trading
account holding the most pick value, where the picks are kept; with no
trading-account picks, to the one with the most cash plus core value (tie:
account id order). Without
``amount`` the plan is ``needed``; with it the new pick gets min(amount, needed)
and the rest goes to the current picks as an add. The target limits it as in ``add``; funding is
as above. Bad input: a symbol in ``positions`` (any bucket) or in
``excluded_symbols``, or equal to settings.employer_symbol (any case).

``rebalance`` runs only on request and moves the trading-account picks toward strategy share x the
sleeve's current value. Sells fund buys in the same account: no cash is used, no core fund is sold, the
ceiling is not consulted. A held pick (as in adding money) keeps its value and its share goes to the
others. A target never passes the 5% pick cap (PICK_CAP), and overflow never goes to a pick overvalued
under valuation. A pick is trimmed when at least weights.band above target, under the short-term-gain
policy (TRIM_HELD_BACK), and each account trims no further than the picks routed to it can take. Any pick
below target can receive the proceeds, furthest below target first; a sale's proceeds buy only picks
routed to its own account, and proceeds no buy spends are not sold, whole-share buys rounding down; what
whole shares leave as cash is unallocated_amount. IN_BAND marks a pick off target, inside its band, with
no trade. A pick above its band that keeps part of its excess says why: TRIM_HELD_BACK for what the
short-term-gain policy keeps from a buy that could take it, TRIM_UNPLACEABLE for what no pick below target
in its account can take.
Bad input: ``size``, ``sell_first``, ``over_ceiling``, ``pick_store_unreadable``, valuation with no
eligible pick of confidence above 0, or negative cash in an account with trades. With fewer than two
trading-account picks there are no trades.

Money 2 dp, weights 4 dp. This produces a plan, not orders.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import weights  # noqa: E402
from rebalance import run_rebalance  # noqa: E402

_BUCKETS = ("core", "satellite", "employer", "cash")
_ROLES = ("trading", "retirement", "savings")
_MODES = ("mix", "add", "new-pick", "rebalance")
_RANK_UNKNOWN = 2
_RANK_BONDS = 3
_EMPLOYER_LIMIT = 0.10
_TECH = "Technology"
_EPS = 0.005


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _num(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise TypeError(f"{field} must be numeric")
    return float(v)


def _flag(flags: list[dict], code: str, message: str) -> None:
    flags.append({"code": code, "message": message})


# --- input --------------------------------------------------------------------------------------


def _read_accounts(params: dict) -> dict[str, str]:
    roles: dict[str, str] = {}
    for aid, info in (params.get("accounts") or {}).items():
        role = info.get("role") if isinstance(info, dict) else None
        if role not in _ROLES:
            raise ValueError(f"account {aid} role must be trading, retirement or savings")
        roles[str(aid)] = role
    return roles


def _read_positions(params: dict, roles: dict[str, str]) -> list[dict]:
    rows = []
    for p in params.get("positions") or []:
        if not isinstance(p, dict) or not p.get("symbol") or p.get("units") is None or p.get("price") is None:
            raise ValueError("each position requires symbol, units and price")
        aid = str(p.get("account"))
        if aid not in roles:
            raise ValueError(f"position {p['symbol']} is in account {aid}, which has no role in accounts")
        if p.get("bucket") not in _BUCKETS:
            raise ValueError(f"position {p['symbol']} bucket must be core, satellite, employer or cash")
        units, price = _num(p["units"], "units"), _num(p["price"], "price")
        rows.append({"symbol": str(p["symbol"]).upper(), "units": units, "price": price,
                     "value": units * price, "account": aid, "role": roles[aid], "bucket": p["bucket"]})
    return rows


def _read_cash(params: dict, roles: dict[str, str]) -> dict[str, float]:
    cash = {}
    for aid, v in (params.get("cash_by_account") or {}).items():
        if str(aid) not in roles:
            raise ValueError(f"cash_by_account has account {aid}, which has no role in accounts")
        cash[str(aid)] = _num(v, f"cash_by_account.{aid}") or 0.0
    return cash


def _settings_used(settings: dict, params: dict) -> tuple[dict, str]:
    """Effective settings: input ``weighting``/``include_light`` win over saved ones."""
    ceiling = settings.get("ceiling")  # the sleeve's target in force; none: its size is unmanaged
    if ceiling is None:
        ceiling, source = 1.0, "none"
    else:
        ceiling, source = _num(ceiling, "settings.ceiling"), "target"
        if not 0 < ceiling <= 1:
            raise ValueError("settings.ceiling must be above 0 and at most 1")
    weighting = params.get("weighting") or settings.get("weighting") or "equal"
    if weighting not in ("equal", "market_cap", "valuation", "size"):
        raise ValueError("weighting must be equal, market_cap, valuation or size")
    depth = params.get("depth", "standard")
    if depth not in ("standard", "deep"):
        raise ValueError("depth must be standard or deep")
    light = params.get("include_light")
    if light is None:
        light = settings.get("include_light")
    if light is not None and not isinstance(light, bool):
        raise ValueError("include_light must be true or false")
    if depth == "deep":
        if params.get("include_light") is True:
            raise ValueError("include_light is not available when depth is deep; light picks take no money")
        light = False  # a saved include_light is ignored at deep depth
    allocation = params.get("allocation") or "fill"
    if allocation not in ("fill", "split"):
        raise ValueError("allocation must be fill or split")
    policy = settings.get("short_term_gain_policy")
    if policy not in (None, "hold", "allow"):
        raise ValueError("settings.short_term_gain_policy must be hold or allow")
    used = {
        "ceiling": ceiling,
        "weighting": weighting,
        "allocation": allocation,
        "include_light": bool(light),
        "short_term_gain_policy": policy,
        "employer_symbol": settings.get("employer_symbol"),
        "depth": depth,
    }
    return used, source


# --- mix ----------------------------------------------------------------------------------------


def _classify(positions: list[dict], cash: dict[str, float], roles: dict[str, str],
              ceiling: float, source: str, sectors: dict, employer_sector: str | None,
              flags: list[dict], employer_symbol: str | None = None) -> dict:
    """The sleeve mix across all accounts, plus the flags it raises."""
    buckets = {b: sum(p["value"] for p in positions if p["bucket"] == b) for b in _BUCKETS}
    buckets["cash"] += sum(cash.values())
    total = sum(buckets.values())
    if total <= 0:
        raise ValueError("positions or cash are required")

    def role_value(role: str) -> float:
        return (sum(p["value"] for p in positions if p["role"] == role)
                + sum(v for a, v in cash.items() if roles[a] == role))

    sat_by_symbol: dict[str, float] = {}
    for p in positions:
        if p["bucket"] == "satellite":
            sat_by_symbol[p["symbol"]] = sat_by_symbol.get(p["symbol"], 0.0) + p["value"]
    sat = buckets["satellite"]
    n = weights.n_eff(sat_by_symbol)
    w_sat = sat / total
    heavy_sectors = {_TECH, employer_sector} - {None}
    heavy_value = sum(v for s, v in sat_by_symbol.items() if (sectors or {}).get(s) in heavy_sectors)
    sector_heavy = sat > 0 and heavy_value / sat >= weights.SECTOR_HEAVY
    room = max(0.0, ceiling * total - sat)

    for p in positions:
        if p["bucket"] == "satellite" and p["role"] == "retirement":
            _flag(flags, "PICK_IN_RETIREMENT", f"{p['symbol']} in retirement account {p['account']} counts toward the satellite and gets no trades")
    employer = str(employer_symbol or "").upper()
    held = buckets["employer"] + sum(p["value"] for p in positions
                                     if p["bucket"] == "satellite" and employer and p["symbol"] == employer)
    if held / total > _EMPLOYER_LIMIT:
        _flag(flags, "EMPLOYER_CONCENTRATION", f"employer stock is {held / total:.1%} of total value, above {_EMPLOYER_LIMIT:.0%}")
    if not any(p["bucket"] == "satellite" and p["role"] == "trading" for p in positions):
        _flag(flags, "NO_SATELLITE", "no satellite holdings in trading accounts")
    elif n < weights.MIN_N_EFF:
        _flag(flags, "LOW_N_EFF", f"effective number of picks is {n:.1f}, below {weights.MIN_N_EFF}")
    if sector_heavy:
        _flag(flags, "SECTOR_HEAVY", f"{heavy_value / sat:.1%} of the satellite is in {', '.join(sorted(heavy_sectors))}; the proposed size is cut")
    if sat > ceiling * total + _EPS:
        _flag(flags, "ABOVE_CEILING", f"the picks sleeve is {w_sat:.1%} of total value, above its {ceiling:.0%} target")

    mix = {b: {"value": _r2(v), "weight": _r4(v / total)} for b, v in buckets.items()}
    mix.update({
        "total": {"value": _r2(total), "weight": 1.0},
        "trading_value": _r2(role_value("trading")),
        "trading_cash": _r2(sum(v for a, v in cash.items() if roles[a] == "trading")),
        "retirement_value": _r2(role_value("retirement")),
        "n_eff": _r4(n),
        "tracking_error": _r4(weights.tracking_error(w_sat, n)),
        "ceiling": _r4(ceiling),
        "ceiling_source": source,
        "proposed_size": weights.proposed_size(ceiling, n, sector_heavy),
        "room_under_ceiling": _r2(room),
        "single_stock_total": _r2(sat + buckets["employer"]),
    })
    return {"mix": mix, "total": total, "satellite": sat, "room": room,
            "proposed_size": mix["proposed_size"]}


# --- split and route ----------------------------------------------------------------------------


def _holdings(positions: list[dict], bucket: str) -> dict[str, dict[str, float]]:
    """Trading-account value by symbol, then account, for one bucket."""
    out: dict[str, dict[str, float]] = {}
    for p in positions:
        if p["bucket"] == bucket and p["role"] == "trading":
            acct = out.setdefault(p["symbol"], {})
            acct[p["account"]] = acct.get(p["account"], 0.0) + p["value"]
    return out


def _route(by_account: dict[str, float]) -> str:
    """The trading account holding the larger value; tie goes to the first account id."""
    return sorted(by_account.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _fund(deltas: dict[str, float], sat: dict[str, dict[str, float]],
          spare: dict[str, float], flags: list[dict],
          shorts: dict[str, float] | None = None) -> dict[str, dict[str, float]]:
    """Place each pick delta in its routed account within that account's spare money.

    Returns {account: {symbol: delta}}. A shortfall moves to another trading account
    holding the same pick; what cannot move is scaled down (ACCOUNT_SHORT) and, when
    ``shorts`` is given, added to ``shorts[account]``.
    """
    alloc: dict[str, dict[str, float]] = {}
    for sym, d in deltas.items():
        if d > 0:
            aid = _route(sat[sym])
            alloc.setdefault(aid, {})[sym] = alloc.get(aid, {}).get(sym, 0.0) + d
    for aid in sorted(alloc):
        short = sum(alloc[aid].values()) - spare.get(aid, 0.0)
        for sym in sorted(alloc[aid]):
            if short <= _EPS:
                break
            for other in sorted(a for a in sat[sym] if a != aid):
                room = spare.get(other, 0.0) - sum(alloc.get(other, {}).values())
                move = min(short, alloc[aid][sym], max(0.0, room))
                if move > 0:
                    alloc[aid][sym] -= move
                    alloc.setdefault(other, {})[sym] = alloc.get(other, {}).get(sym, 0.0) + move
                    short -= move
        if short > _EPS:
            need = sum(alloc[aid].values())
            scale = spare.get(aid, 0.0) / need if need > 0 else 0.0
            alloc[aid] = {s: v * max(0.0, scale) for s, v in alloc[aid].items()}
            if shorts is not None:
                shorts[aid] = shorts.get(aid, 0.0) + short
            _flag(flags, "ACCOUNT_SHORT", f"account {aid} is {short:.2f} short of money; its pick buys are scaled down")
    for aid in spare:
        if aid not in alloc:
            continue
        spare[aid] -= sum(alloc[aid].values())
    return alloc


def _account_plan(aid: str, positions: list[dict], cash: float, pick_delta: dict[str, float],
                  core_delta: float, params: dict, lot_override: dict | None = None,
                  core_sells: dict[str, float] | None = None,
                  new_positions: list[dict] | None = None) -> dict:
    """One run_rebalance call for one trading account so each pick lands on its target.

    ``lot_override`` ({symbol: lots}) replaces a trimmed pick's (or a sold core
    fund's) lots with the ones the sale may use, so the tax estimate uses only those
    lots. ``core_sells`` ({symbol: value}) gives each listed core fund its own target,
    its value less the sale. ``new_positions`` are picks not yet held.
    """
    rows = [p for p in positions if p["account"] == aid and p["bucket"] in ("core", "satellite")]
    acct_total = sum(p["value"] for p in rows) + cash
    targets: dict[str, float] = {}
    classes: dict[str, str] = {}
    for p in rows:
        if p["bucket"] == "satellite":
            targets[p["symbol"]] = targets.get(p["symbol"], 0.0) + p["value"]
        else:
            classes[p["symbol"]] = "core"
    for sym, d in pick_delta.items():
        targets[sym] = targets.get(sym, 0.0) + d
    sold = {s: v for s, v in (core_sells or {}).items() if v > _EPS}
    for sym, v in sold.items():
        targets[sym] = sum(p["value"] for p in rows if p["symbol"] == sym and p["bucket"] == "core") - v
    core_value = sum(p["value"] for p in rows if p["bucket"] == "core" and p["symbol"] not in sold)
    if any(s not in sold for s in classes):
        targets["core"] = core_value + core_delta
    weights_ = {k: min(1.0, max(0.0, v / acct_total)) for k, v in targets.items()}
    weights_["CASH"] = max(0.0, 1.0 - sum(weights_.values()))
    lots = {
        sym: [lot for lot in rows_ if lot.get("account") in (None, aid)]
        for sym, rows_ in (params.get("lots") or {}).items()
    }
    lots.update(lot_override or {})
    plan = run_rebalance({
        "positions": [{"symbol": p["symbol"], "units": p["units"], "price": p["price"], "account": aid} for p in rows],
        "cash": cash,
        "targets": weights_,
        "classes": classes,
        "allow_sells": True,
        "class_sells": "smallest_gain",
        "whole_shares": bool(params.get("whole_shares", False)),
        "lots": lots,
        "new_positions": new_positions or [],
        "rates": params.get("rates") or {},
        "accounts": {aid: {"taxable": True}},
    })
    core_sells = sum(t["value"] for t in plan["trades"] if t["side"] == "SELL" and t["symbol"] in classes)
    return {
        "account": aid,
        "funding": {"cash": _r2(plan["buys_total"] - plan["sells_total"]), "core_sells": _r2(core_sells)},
        "rebalance": plan,
    }


def _plan_accounts(positions, cash, alloc, core, params, lot_override=None,
                   core_sells=None, new_positions=None) -> list[dict]:
    out = []
    for aid in sorted(set(alloc) | set(core)):
        picks = {s: d for s, d in alloc.get(aid, {}).items() if abs(d) > _EPS}
        if picks or core.get(aid, 0.0) > _EPS:
            new = [n for n in new_positions or [] if n["account"] == aid and n["symbol"] in picks]
            out.append(_account_plan(aid, positions, cash.get(aid, 0.0), picks, core.get(aid, 0.0),
                                     params, (lot_override or {}).get(aid), (core_sells or {}).get(aid), new))
    return out


def _splits(sat: dict[str, dict[str, float]], alloc: dict[str, dict[str, float]],
            targets: dict[str, float] | None = None, pick_flags: dict[str, list[str]] | None = None) -> list[dict]:
    rows = []
    for sym in sorted(sat):
        current = sum(sat[sym].values())
        delta = sum(a.get(sym, 0.0) for a in alloc.values())
        rows.append({
            "symbol": sym, "current": _r2(current),
            "target": _r2(targets[sym] if targets else current + delta), "delta": _r2(delta),
            "account": _route(sat[sym]), "flags": sorted(set((pick_flags or {}).get(sym, []))),
        })
    return rows


# --- strategy inputs, holds and trims -----------------------------------------------------------


def _pick_inputs(sat: dict[str, dict[str, float]], positions: list[dict], picks: dict,
                 include_light: bool, flags: list[dict],
                 pick_flags: dict[str, list[str]], unreadable: set[str] = frozenset()) -> list[dict]:
    """The weights.strategy_weights input for each trading-account pick, plus pick flags.

    Eligible: kind deep (or light with include_light) with central_value and
    expected_return. Only eligible picks carry central_value, so an ineligible
    pick gets the neutral weight.
    """
    price = {p["symbol"]: p["price"] for p in positions if p["bucket"] == "satellite" and p["role"] == "trading"}
    out = []
    for sym in sorted(sat):
        pick = picks.get(sym)
        if pick is not None and not isinstance(pick, dict):
            raise ValueError(f"picks.{sym} must be an object")
        row = {"symbol": sym, "value": sum(sat[sym].values()), "price": price[sym],
               "central_value": None, "expected_return": None, "eligible": False, "confidence": 0.0}
        out.append(row)
        if pick is None:
            if sym in unreadable:
                _flag(flags, "NO_SAVED_VALUATION", f"{sym} holds at its current value because its saved valuation could not be read")
            else:
                _flag(flags, "NO_SAVED_VALUATION", f"{sym} has no saved valuation and gets the neutral weight")
            pick_flags.setdefault(sym, []).append("NO_SAVED_VALUATION")
            continue
        central = _num(pick.get("central_value"), f"picks.{sym}.central_value")
        er = _num(pick.get("expected_return"), f"picks.{sym}.expected_return")
        kind = pick.get("kind")
        has_values = central is not None and er is not None
        if kind == "light":
            pick_flags.setdefault(sym, []).append("LIGHT_VALUATION")
            if not include_light:
                _flag(flags, "LIGHT_VALUATION", f"{sym} has a light valuation only; not used for the tilt, it gets the neutral weight")
            elif has_values:
                _flag(flags, "LIGHT_VALUATION", f"{sym} has a light valuation only; it was included in the tilt (include_light), and its expected return is a 3-year convergence estimate from the light fair value")
            else:
                _flag(flags, "LIGHT_VALUATION", f"{sym} has a light valuation without an expected return; not used for the tilt")
        age = _num(pick.get("age_days"), f"picks.{sym}.age_days")
        due = bool(pick.get("recheck_due")) or age is None
        if pick.get("recheck_due"):
            _flag(flags, "RECHECK_DUE", f"{sym} valuation is due for a recheck; its confidence is 0 and it gets no tilt")
            pick_flags.setdefault(sym, []).append("RECHECK_DUE")
        elif age is None:
            _flag(flags, "RECHECK_DUE", f"{sym} valuation has no known age; it is treated as due for a recheck, its confidence is 0 and it gets no tilt")
            pick_flags.setdefault(sym, []).append("RECHECK_DUE")
        if (kind == "deep" or (kind == "light" and include_light)) and has_values:
            row.update(central_value=central, expected_return=er, eligible=True,
                       confidence=weights.confidence(age or 0.0, due))
    return out


def _long_term_date(acquired: str | None) -> str | None:
    """The first long-term sale date: the day after the one-year anniversary (Feb 29 -> Mar 1)."""
    if not acquired:
        return None
    try:
        d = date.fromisoformat(str(acquired))
    except ValueError as exc:
        raise ValueError(f"lot acquired date {acquired!r} must be YYYY-MM-DD") from exc
    try:
        anniversary = d.replace(year=d.year + 1)
    except ValueError:  # Feb 29
        anniversary = d.replace(year=d.year + 1, day=28)
    return (anniversary + timedelta(days=1)).isoformat()


def _trim_account(sym: str, aid: str, value: float, price: float, units_held: float,
                  lots: list[dict], allow: bool, whole: bool = False) -> tuple[float, list[dict], list[dict]]:
    """Split a trim of ``value`` in one account into what may sell and what is held back.

    Lot order: losses (cost >= price), long-term gains, then short-term or
    unknown-term gains (and units with no lot) only when ``allow``. With
    ``whole`` the sold units round down, so a sale never passes the allowed
    value. Returns (sell value, held_back rows, the lots the sale may use).
    """
    loss, long_, rest = [], [], []
    for lot in lots:
        cost = _num(lot.get("cost_per_unit"), f"lots.{sym}.cost_per_unit")
        if cost is not None and cost >= price:
            loss.append(lot)
        elif lot.get("term") == "long":
            long_.append(lot)
        else:
            rest.append(lot)
    rest.sort(key=lambda lot: (lot.get("acquired") is None, str(lot.get("acquired") or "")))
    pieces, left = [], units_held
    for kind, group in (("free", loss), ("free", long_), ("gain", rest)):
        for lot in group:
            u = min(_num(lot.get("units"), f"lots.{sym}.units") or 0.0, left)
            if u > 0:
                pieces.append((kind, lot, u))
                left -= u
    if left > 0:
        pieces.append(("gain", None, left))
    need = value / price if price > 0 else 0.0
    sell_units, sellable, held = 0.0, [], {}
    for kind, lot, u in pieces:
        if need <= 1e-9:
            break
        take = min(u, need)
        need -= take
        if kind == "free" or allow:
            sell_units += take
            if lot is not None:
                sellable.append(lot)
        else:
            ltd = _long_term_date(lot.get("acquired") if lot else None)
            held[ltd] = held.get(ltd, 0.0) + take * price
    if whole:
        sell_units = math.floor(sell_units + 1e-9)
    rows = [{"symbol": sym, "value": _r2(v), "account": aid, "long_term_date": d}
            for d, v in sorted(held.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))]
    return sell_units * price, rows, sellable


def _hold(sym: str, value: float, pick: object, flags: list[dict], pick_flags: dict[str, list[str]]) -> bool:
    """Flag and return True when ``pick`` is due for a recheck (or has no age): it holds at ``value``."""
    if not isinstance(pick, dict) or not (pick.get("recheck_due") or pick.get("age_days") is None):
        return False
    code = "DEEP_VALUATION_NEEDED" if pick.get("needs_valuation") else "HELD_FOR_RECHECK"
    pick_flags.setdefault(sym, []).append(code)
    why = "its deep valuation is rerun" if code == "DEEP_VALUATION_NEEDED" else "its recheck completes"
    _flag(flags, code, f"{sym} holds at its current value ({value:.2f}) until {why}; it is not traded")
    return True


def _trim_split(over: dict[str, float], sat: dict[str, dict[str, float]], demand: dict[str, float],
                free: dict[str, dict[str, float]], dust: float) -> dict[str, dict[str, float]]:
    """How much of each pick in ``over`` ({symbol: value it may lose}) to trim in each account.

    An account's trims stop at its ``demand`` (what the picks routed to it can take), shared among
    the picks it holds pro rata to what each can give. ``free`` ({symbol: {account: value}}) is what
    may sell; only demand it cannot meet then asks for the rest of the holding, which the
    short-term-gain policy holds back. A holding or a part worth ``dust`` or less is not sold: it is
    what rounding leaves, too small for an order. Returns {symbol: {account: value}}.
    """
    demand = dict(demand)
    left = dict(over)
    out = {sym: {a: 0.0 for a in sat[sym]} for sym in over}
    for limit in (free, sat):
        for aid in sorted(demand):
            room = {sym: min(left[sym], limit[sym][aid] - out[sym][aid]) for sym in sorted(over) if aid in sat[sym]}
            room = {sym: v for sym, v in room.items() if v > dust}
            total = sum(room.values())
            take = min(demand[aid], total)
            for sym, v in room.items():
                part = v * take / total
                if part > dust:
                    out[sym][aid] += part
                    left[sym] -= part
                    demand[aid] -= part
    return out


def _apply_trims(cuts: dict[str, float], sat: dict[str, dict[str, float]], price: dict[str, float],
                 units: dict[tuple[str, str], float], params: dict, used: dict, spare: dict[str, float],
                 flags: list[dict], pick_flags: dict[str, list[str]],
                 split: dict[str, dict[str, float]] | None = None) -> tuple[dict, list[dict], dict, dict]:
    """Sell ``cuts`` ({symbol: value}) across the trading accounts holding each pick, pro rata to
    value, or as ``split`` ({symbol: {account: value}}) gives.

    Each account's part goes through ``_trim_account`` under the short-term-gain policy; its
    proceeds are added to that account's ``spare``. Returns (trims {account: {symbol: sold}},
    held_back rows, lot_override, kept {symbol: value the policy kept unsold}).
    """
    lots_in = params.get("lots") or {}
    policy = used["short_term_gain_policy"]
    trims: dict[str, dict[str, float]] = {}
    held_back: list[dict] = []
    lot_override: dict[str, dict[str, list[dict]]] = {}
    kept: dict[str, float] = {}
    for sym in sorted(cuts):
        current = sum(sat[sym].values())
        for aid in sorted(sat[sym]):
            part = split[sym][aid] if split else cuts[sym] * sat[sym][aid] / current
            lots = [lot for lot in lots_in.get(sym) or [] if lot.get("account") in (None, aid)]
            sold, rows, sellable = _trim_account(sym, aid, part, price[sym], units[(sym, aid)],
                                                 lots, policy == "allow", bool(params.get("whole_shares")))
            kept[sym] = kept.get(sym, 0.0) + part - sold
            held_back.extend(rows)
            if sold > _EPS:
                trims.setdefault(aid, {})[sym] = sold
                spare[aid] = spare.get(aid, 0.0) + sold
                if policy != "allow":
                    lot_override.setdefault(aid, {})[sym] = sellable
    _trims_held_back(held_back, policy, flags, pick_flags)
    return trims, held_back, lot_override, kept


def _trims_held_back(rows: list[dict], policy: str | None, flags: list[dict], pick_flags: dict[str, list[str]]) -> None:
    """TRIM_HELD_BACK for ``rows``, plus STANDING_DEFAULT under an unset policy."""
    if not rows:
        return
    syms = {r["symbol"] for r in rows}
    for sym in syms:
        pick_flags.setdefault(sym, []).append("TRIM_HELD_BACK")
    total = sum(r["value"] for r in rows)
    _flag(flags, "TRIM_HELD_BACK", f"{total:.2f} of trims in {', '.join(sorted(syms))} is held back: those units are short-term or unknown-term gains")
    if policy is None:
        _policy_needed(flags)


def _participants(sat: dict[str, dict[str, float]], positions: list[dict], params: dict, used: dict,
                  flags: list[dict], pick_flags: dict[str, list[str]]) -> tuple[list[dict], dict[str, float], set[str]]:
    """Each trading-account pick's row, the strategy's raw weights and the picks that hold.

    Returns (rows, raw, held). A held pick takes no money and does not move: it is due for a
    recheck (``_hold``), in ``unreadable_picks`` (PICK_BASELINE_MISSING), or under market_cap has
    no finite cap above 0 (NO_MARKET_CAP). ``raw`` covers only the others. Under market_cap, no
    cap at all among them is bad input.
    """
    strategy = used["weighting"]
    picks = params.get("picks") or {}
    given_unreadable = params.get("unreadable_picks") or []
    if not isinstance(given_unreadable, list):
        raise ValueError("unreadable_picks must be a list")
    if not isinstance(params.get("market_caps") or {}, dict):
        raise ValueError("market_caps must be an object")
    unreadable = {str(s).upper() for s in given_unreadable}
    if strategy == "valuation":
        rows = _pick_inputs(sat, positions, picks, used["include_light"], flags, pick_flags, unreadable)
    else:
        price = {p["symbol"]: p["price"] for p in positions if p["bucket"] == "satellite" and p["role"] == "trading"}
        rows = [{"symbol": sym, "value": sum(sat[sym].values()), "price": price[sym]} for sym in sorted(sat)]
    held = {r["symbol"] for r in rows if _hold(r["symbol"], r["value"], picks.get(r["symbol"]), flags, pick_flags)} | (unreadable & set(sat))
    for sym in unreadable & set(sat):
        pick_flags.setdefault(sym, []).append("PICK_BASELINE_MISSING")
    caps = None
    if strategy == "market_cap":
        given = params.get("market_caps") or {}
        caps = {r["symbol"]: _num(given.get(r["symbol"]), f"market_caps.{r['symbol']}") for r in rows if r["symbol"] not in held}
        missing = {sym for sym, v in caps.items() if v is None or not math.isfinite(v) or v <= 0}
        if caps and missing == set(caps):
            raise ValueError("market_cap weighting needs a market cap, and no pick that can take money has a market cap")
        for sym in sorted(missing):
            held.add(sym)
            pick_flags.setdefault(sym, []).append("NO_MARKET_CAP")
            _flag(flags, "NO_MARKET_CAP", f"{sym} has no market cap; it gets no new money and holds its value")
    raw = weights.strategy_weights([r for r in rows if r["symbol"] not in held], strategy, caps)
    return rows, raw, held


def _new_pick_weight(new: dict, params: dict, used: dict, flags: list[dict]) -> float | None:
    """The new pick's raw weight under the strategy, or None when it has none (size, no market cap)."""
    strategy, sym = used["weighting"], new["symbol"]
    if strategy == "equal":
        return 1.0
    if strategy == "valuation":
        row = _pick_inputs({sym: {new["account"]: 0.0}},
                           [{"symbol": sym, "price": new["price"], "bucket": "satellite", "role": "trading"}],
                           {sym: (params.get("picks") or {}).get(sym)} if (params.get("picks") or {}).get(sym) is not None else {},
                           used["include_light"], [], {})[0]
        return weights.tilt_factor(row)
    if strategy == "market_cap":
        cap = _num((params.get("market_caps") or {}).get(sym), f"market_caps.{sym}")
        if cap is not None and math.isfinite(cap) and cap > 0:
            return cap
        _flag(flags, "NO_MARKET_CAP", f"{sym} has no market cap; it opens at the median pick value and the rest is split by market cap")
    return None


def _strategy_deltas(amount: float, ctx: dict, positions: list[dict], params: dict, used: dict,
                     flags: list[dict], pick_flags: dict[str, list[str]],
                     new: dict | None = None) -> tuple[dict[str, float], float | None]:
    """Each trading-account pick's buy for ``amount``, and the new pick's buy (None: not filled).

    fill (the default, every strategy but size): each pick's target is its strategy share of the
    picks taking money plus ``amount``, and the money goes to the gaps below target
    (weights.fill_gaps); a new pick joins at 0 when its weight is known. split: ``amount`` by the
    strategy's shares, whatever the picks hold. The 5% pick cap limits buys except under size.
    """
    sat = _holdings(positions, "satellite")
    rows, raw, held = _participants(sat, positions, params, used, flags, pick_flags)
    if used["weighting"] == "valuation" and not any(r["eligible"] and r["confidence"] > 0 for r in rows if r["symbol"] not in held):
        _flag(flags, "VALUATION_FALLBACK", "no trading-account pick has an eligible valuation with confidence above 0; the weights are neutral, so the split is equal")
    room = None
    if used["weighting"] != "size":
        room = {sym: max(0.0, weights.PICK_CAP * ctx["total"] - sum(sat[sym].values())) for sym in raw}
    fill = used["allocation"] == "fill" and used["weighting"] != "size"
    new_w = _new_pick_weight(new, params, used, flags) if new is not None and fill else None
    if fill:
        current = {sym: sum(sat[sym].values()) for sym in raw}
        if new_w is not None:
            raw, current = {**raw, new["symbol"]: new_w}, {**current, new["symbol"]: 0.0}
            room = {**(room or {}), new["symbol"]: weights.PICK_CAP * ctx["total"]}
        deltas = weights.fill_gaps(raw, current, amount, room) if raw else {}
    else:
        deltas = weights.split_capped(raw, amount, room)
    new_delta = deltas.pop(new["symbol"], 0.0) if new_w is not None else None
    for sym, d in deltas.items():
        if room is not None and d >= room[sym] - _EPS:
            pick_flags.setdefault(sym, []).append("PICK_CAP")
    return deltas, new_delta


def _strategy_add(amount: float, ctx: dict, positions: list[dict], spare: dict[str, float], params: dict,
                  used: dict, flags: list[dict], pick_flags: dict[str, list[str]],
                  shorts: dict[str, float] | None = None) -> dict:
    """Plan ``amount`` into the trading-account picks (``_strategy_deltas``) and place it per account. It never sells."""
    sat = _holdings(positions, "satellite")
    if not sat:
        return {"alloc": {}, "unplaced": amount}
    deltas, _ = _strategy_deltas(amount, ctx, positions, params, used, flags, pick_flags)
    alloc = _fund(deltas, sat, spare, flags, shorts)
    return {"alloc": alloc, "unplaced": max(0.0, amount - _placed(alloc))}


def _rebalance(ctx: dict, positions: list[dict], spare: dict[str, float], params: dict, used: dict,
               flags: list[dict], pick_flags: dict[str, list[str]]) -> dict:
    """Move the trading-account picks toward strategy share x the sleeve's value; sells fund buys.

    Held picks keep their value. The 5% cap limits targets only: a pick above its target can be
    trimmed however large. Picks at least one band above target are trimmed, in each account no
    further than the picks routed to it can take; each account's proceeds go to its picks furthest
    below target first, and proceeds no buy spends are not sold. Returns {alloc, held_back,
    lot_override, targets, unplaced}, ``unplaced`` being what whole shares leave as cash.
    """
    sat = _holdings(positions, "satellite")
    rows, raw, held = _participants(sat, positions, params, used, flags, pick_flags)
    if used["weighting"] == "valuation" and not any(r["eligible"] and r["confidence"] > 0 for r in rows if r["symbol"] not in held):
        raise ValueError("valuation rebalance needs a pick with an eligible valuation of confidence above 0; without one it would sell picks toward a strategy not chosen")

    current = {sym: sum(a.values()) for sym, a in sat.items()}
    fixed = {sym: current[sym] for sym in held}
    # an overvalued pick takes its own share only, never another pick's overflow
    closed = {r["symbol"] for r in rows if r["symbol"] in raw and r.get("eligible") and r["confidence"] > 0
              and r["price"] > r["central_value"] * (1 + weights.TRIM_MIN_GAP)}
    vt = weights.rebalance_targets(rows, raw, fixed, sum(current.values()), ctx["total"], closed)
    for sym in vt["capped"]:
        pick_flags.setdefault(sym, []).append("PICK_CAP")
    targets = {sym: float(v) for sym, v in vt["targets"].items()}
    movable = sorted(sym for sym in sat if sym not in held)

    buys = {sym: 0.0 for sym in movable}

    def short(sym: str) -> float:
        return targets[sym] - current[sym] - buys[sym]

    def place(money: float, order: list[str]) -> float:
        for sym in order:
            if money <= _EPS:
                break
            give = min(max(0.0, short(sym)), money)
            buys[sym] += give
            money -= give
        return money

    over = {sym: current[sym] - targets[sym] for sym in movable
            if current[sym] - targets[sym] >= weights.band(targets[sym])}
    price = {r["symbol"]: r["price"] for r in rows}
    # a value this small is what the plan's own rounding (cents, 4 dp units) leaves behind
    dust = 2 * _EPS + 1e-4 * max(price.values())
    demand: dict[str, float] = {}
    for sym in movable:
        if short(sym) > dust:
            aid = _route(sat[sym])
            demand[aid] = demand.get(aid, 0.0) + short(sym)
    units: dict[tuple[str, str], float] = {}
    for p in positions:
        if p["bucket"] == "satellite" and p["role"] == "trading":
            units[(p["symbol"], p["account"])] = units.get((p["symbol"], p["account"]), 0.0) + p["units"]
    whole = bool(params.get("whole_shares"))
    lots_in = params.get("lots") or {}
    free = {sym: {aid: _trim_account(sym, aid, value, price[sym], units[(sym, aid)],
                                     [lot for lot in lots_in.get(sym) or [] if lot.get("account") in (None, aid)],
                                     used["short_term_gain_policy"] == "allow", whole)[0]
                  for aid, value in sat[sym].items()} for sym in over}
    # each account trims only what its own buys can take, so a second run on the result has
    # nothing to do: an account still short has no pick left that can sell
    split = _trim_split(over, sat, demand, free, dust)
    cuts = {sym: sum(parts.values()) for sym, parts in split.items() if sum(parts.values()) > _EPS}
    before = dict(spare)
    trims, held_back, lot_override, _ = _apply_trims(cuts, sat, price, units, params, used, spare, flags, pick_flags, split)
    for aid in sorted(trims):        # a whole-holding sale must not round to more units than are held
        for sym, v in trims[aid].items():
            if round(v / price[sym], 4) > units[(sym, aid)] + 1e-9:
                trims[aid][sym] = math.floor(units[(sym, aid)] * 1e4 + 1e-9) / 1e4 * price[sym]
                spare[aid] -= v - trims[aid][sym]
    for aid in sorted(trims):        # a sale's proceeds buy only picks routed to its own account
        here = [sym for sym in movable if _route(sat[sym]) == aid]
        place(sum(trims[aid].values()), sorted(here, key=lambda x: (-short(x), x)))
    buys = {sym: v if v > dust else 0.0 for sym, v in buys.items()}

    for sym in movable:
        if buys[sym] <= _EPS and sym not in cuts and _EPS < abs(current[sym] - targets[sym]) < weights.band(targets[sym]):
            pick_flags.setdefault(sym, []).append("IN_BAND")
    rounded = 0.0
    if whole:                        # a buy rounds down, and what it leaves is returned below
        wanted = sum(buys.values())
        buys = {sym: math.floor(v / price[sym] + 1e-9) * price[sym] for sym, v in buys.items()}
        rounded = wanted - sum(buys.values())
    alloc = _fund({sym: v for sym, v in buys.items() if v > _EPS}, sat, spare, flags)
    unplaced = 0.0
    for aid in sorted(trims):        # proceeds no buy in this account spends are not sold
        idle = min(sum(trims[aid].values()), spare.get(aid, 0.0) - before.get(aid, 0.0))
        for sym in sorted(trims[aid]):
            back = min(idle, trims[aid][sym])
            if whole:
                back = math.floor(back / price[sym] + 1e-9) * price[sym]
            if back > _EPS:
                trims[aid][sym] -= back
                spare[aid] -= back
                idle -= back
        unplaced += idle             # under one share of the seller: whole shares cannot return it
        trims[aid] = {sym: v for sym, v in trims[aid].items() if v > _EPS}
    for aid, by_sym in trims.items():
        for sym, v in by_sym.items():
            alloc.setdefault(aid, {})[sym] = alloc.get(aid, {}).get(sym, 0.0) - v

    # the policy's part of an unsold excess is what it would have sold under allow, in an account
    # where free sellers met the demand alone: any other account's rows already report it
    open_split = _trim_split(over, sat, demand, sat, dust)
    reported = {r["account"] for r in held_back}
    passed_over: list[dict] = []
    for sym in sorted(over):
        for aid in sorted(set(sat[sym]) - reported):
            lots = [lot for lot in lots_in.get(sym) or [] if lot.get("account") in (None, aid)]
            rows_ = _trim_account(sym, aid, open_split[sym][aid], price[sym], units[(sym, aid)], lots,
                                  used["short_term_gain_policy"] == "allow")[1]
            passed_over.extend(r for r in rows_ if r["value"] > _EPS)
    _trims_held_back(passed_over, used["short_term_gain_policy"], flags, pick_flags)
    held_back.extend(passed_over)
    # the rest no pick can take; rounding leaves up to a share per holding and per buy, and is no reason
    for sym in sorted(over):
        sold = sum(by_sym.get(sym, 0.0) for by_sym in trims.values())
        rest = over[sym] - sold - sum(r["value"] for r in held_back if r["symbol"] == sym)
        slack = dust * len(movable)
        if rest > slack and (sold <= _EPS or rest > slack + (rounded + price[sym] * len(sat[sym]) if whole else 0.0)):
            pick_flags.setdefault(sym, []).append("TRIM_UNPLACEABLE")
            _flag(flags, "TRIM_UNPLACEABLE", f"{rest:.2f} of {sym}'s {over[sym]:.2f} above its target is not sold: no pick below target in its account can take the proceeds{' in whole shares' if whole else ''}")
    return {"alloc": alloc, "held_back": held_back, "lot_override": lot_override, "targets": vt["targets"], "unplaced": unplaced}


# --- core funding (new-pick) ---------------------------------------------------


def _policy_needed(flags: list[dict]) -> None:
    """STANDING_DEFAULT for an unset short_term_gain_policy, raised once."""
    if not any(f["code"] == "STANDING_DEFAULT" and "short_term_gain_policy" in f["message"] for f in flags):
        _flag(flags, "STANDING_DEFAULT", "short_term_gain_policy is unset: hold is assumed, so short-term and unknown-term gains are held back; save taxes.short_term_gain_policy as allow to sell them")


def _core_capacity(positions: list[dict], params: dict, allow: bool,
                   whole: bool = False) -> dict[str, list[dict]]:
    """Each trading account's core funds in sale order, with the value each may sell.

    The order is ``sell_first`` (the named funds, in their order), then the overlap rank (``core_rank``: US equity 0, international equity 1,
    other or unknown 2, bonds 3) first, then run_rebalance's smallest_gain order:
    ascending (price - average lot cost) / price, funds without lots last. ``cap`` is what ``_trim_account`` lets
    the fund sell under the short-term-gain policy (all of it with ``allow``); with
    ``whole`` it is whole units.
    """
    held: dict[tuple[str, str], dict] = {}
    for p in positions:
        if p["bucket"] == "core" and p["role"] == "trading":
            r = held.setdefault((p["account"], p["symbol"]),
                                {"symbol": p["symbol"], "price": p["price"], "units": 0.0, "value": 0.0})
            r["units"] += p["units"]
            r["value"] += p["value"]
    rank = _core_rank(params)
    first = _sell_first(params)
    out: dict[str, list[dict]] = {}
    for (aid, sym), r in sorted(held.items()):
        lots = [lot for lot in (params.get("lots") or {}).get(sym) or [] if lot.get("account") in (None, aid)]
        cap, _, sellable = _trim_account(sym, aid, r["value"], r["price"], r["units"], lots, allow, whole)
        units = sum(_num(lot.get("units"), f"lots.{sym}.units") or 0.0 for lot in lots)
        r_ = (first.index(sym) if sym in first else len(first), rank.get(sym, _RANK_UNKNOWN))
        if units <= 0 or r["price"] <= 0:
            order = (r_, 1, 0.0, sym)
        else:
            avg = sum((_num(lot.get("units"), "units") or 0.0) * (_num(lot.get("cost_per_unit"), "cost_per_unit") or 0.0)
                      for lot in lots) / units
            order = (r_, 0, (r["price"] - avg) / r["price"], sym)
        out.setdefault(aid, []).append({**r, "cap": cap, "sellable": sellable, "lots": lots, "order": order})
    for rows in out.values():
        rows.sort(key=lambda r: r["order"])
    return out


def _core_rank(params: dict) -> dict[str, int]:
    """Input ``core_rank`` ({SYM: int}), upper-cased; a fund not in it ranks _RANK_UNKNOWN."""
    raw = params.get("core_rank") or {}
    if not isinstance(raw, dict):
        raise ValueError("core_rank must be an object of symbol: rank")
    out = {}
    for sym, v in raw.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise TypeError(f"core_rank.{sym} must be an integer")
        out[str(sym).upper()] = v
    return out


def _sell_first(params: dict) -> list[str]:
    """Input ``sell_first`` ([SYM]), upper-cased; [] when absent."""
    raw = params.get("sell_first") or []
    if not isinstance(raw, list):
        raise ValueError("sell_first must be a list of symbols")
    return [str(s).upper() for s in raw]


def _bond_sales(accounts: list[dict], params: dict, flags: list[dict]) -> None:
    """BOND_FUND_SOLD for each bond-ranked core fund sold in the plan."""
    rank = _core_rank(params)
    first = _sell_first(params)
    for a in accounts:
        for t in a["rebalance"]["trades"]:
            if t["side"] == "SELL" and rank.get(t["symbol"]) == _RANK_BONDS:
                why = "as named to sell first" if t["symbol"] in first else "after the equity core there was used up"
                _flag(flags, "BOND_FUND_SOLD", f"{t['symbol']} (a bond fund) sells {t['value']:.2f} in account {a['account']} to fund picks, {why}; that moves money from bonds to stocks")


def _core_funding(alloc: dict[str, dict[str, float]], cash: dict[str, float],
                  capacity: dict[str, list[dict]], policy: str | None, shorts: dict[str, float],
                  held_back: list[dict], lot_override: dict, flags: list[dict],
                  whole: bool = False) -> dict[str, dict[str, float]]:
    """Core sells per trading account for the buys its own cash does not cover.

    Fills each account's need fund by fund in ``capacity`` order. Under hold or an
    unset policy, the part of an account's shortfall that the policy blocked becomes
    held_back rows (CORE_HELD_BACK) and the sold funds' lots are limited to the ones
    the sale may use. With ``whole`` each sale rounds up to whole units, never past
    the fund's cap (itself whole units). Returns {account: {symbol: sell value}}.
    """
    sells: dict[str, dict[str, float]] = {}
    for aid in sorted(alloc):
        need = sum(alloc[aid].values()) - cash.get(aid, 0.0)
        for r in capacity.get(aid, []):
            if need <= _EPS:
                break
            take = min(need, r["cap"])
            if whole and r["price"] > 0:
                take = min(math.ceil(take / r["price"] - 1e-9), round(r["cap"] / r["price"])) * r["price"]
            if take > _EPS:
                sells.setdefault(aid, {})[r["symbol"]] = take
                need -= take
                if policy != "allow":
                    lot_override.setdefault(aid, {})[r["symbol"]] = r["sellable"]
    if policy == "allow":
        return sells
    rows: list[dict] = []
    for aid in sorted(shorts):
        left = shorts[aid]
        for r in capacity.get(aid, []):
            if left <= _EPS:
                break
            h = min(left, r["value"] - r["cap"])
            if h > _EPS:
                rows.extend(_trim_account(r["symbol"], aid, r["cap"] + h, r["price"], r["units"], r["lots"], False)[1])
                left -= h
    if rows:
        held_back.extend(rows)
        total = sum(r["value"] for r in rows)
        syms = ", ".join(sorted({r["symbol"] for r in rows}))
        _flag(flags, "CORE_HELD_BACK", f"{total:.2f} of core sales in {syms} is held back: those units are short-term or unknown-term gains")
        if policy is None:
            _policy_needed(flags)
    return sells


def _cap_to_funds(alloc: dict[str, dict[str, float]], cash: dict[str, float],
                  core_sells: dict[str, dict[str, float]], core: dict[str, float],
                  flags: list[dict]) -> float:
    """Scale each account's pick buys down to its cash plus its sales; returns the cut.

    Funds are the account's cash, its core sales and its trim proceeds, less its
    core buys, so no account plan spends more than it has (ACCOUNT_SHORT).
    """
    cut = 0.0
    for aid in sorted(alloc):
        buys = sum(v for v in alloc[aid].values() if v > 0)
        funds = (cash.get(aid, 0.0) + sum((core_sells.get(aid) or {}).values())
                 - sum(v for v in alloc[aid].values() if v < 0) - core.get(aid, 0.0))
        if buys > funds + _EPS:
            scale = max(0.0, funds) / buys
            alloc[aid] = {s: v * scale if v > 0 else v for s, v in alloc[aid].items()}
            cut += buys - max(0.0, funds)
            _flag(flags, "ACCOUNT_SHORT", f"account {aid} is {buys - max(0.0, funds):.2f} short after whole-unit sales; its pick buys are scaled down")
    return cut


def _rounding_left(alloc: dict[str, dict[str, float]], accounts: list[dict]) -> float:
    """Planned net pick money less the net pick trades: what whole-unit buys left as cash."""
    picks = {s for a in alloc.values() for s in a}
    planned = sum(v for a in alloc.values() for v in a.values())
    traded = sum(t["value"] * (1 if t["side"] == "BUY" else -1)
                 for a in accounts for t in a["rebalance"]["trades"] if t["symbol"] in picks)
    return max(0.0, planned - traded)


def _satellite_net(positions: list[dict], accounts: list[dict], new_symbol: str | None) -> float:
    """Net value of the satellite-pick trades: BUY values less SELL values."""
    picks = {p["symbol"] for p in positions if p["bucket"] == "satellite"} | ({new_symbol} if new_symbol else set())
    return sum(t["value"] * (1 if t["side"] == "BUY" else -1)
               for a in accounts for t in a["rebalance"]["trades"] if t["symbol"] in picks)


# --- inputs --------------------------------------------------------------------------


def _day(v: object, field: str) -> date:
    try:
        return date.fromisoformat(str(v))
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


# --- modes --------------------------------------------------------------------------------------


def _limit(amount: float, ctx: dict, params: dict, flags: list[dict]) -> tuple[float, float]:
    """``amount`` limited to the room under the ceiling, and the part left out."""
    over = 0.0
    if params.get("over_ceiling"):
        if ctx["satellite"] + amount > ctx["ceiling"] * ctx["total"] + _EPS:
            _flag(flags, "ABOVE_CEILING", f"over_ceiling is set; the picks sleeve ends above its {ctx['ceiling']:.0%} target")
    elif amount > ctx["room"] + _EPS:
        over = amount - ctx["room"]
        amount = ctx["room"]
        _flag(flags, "ABOVE_CEILING", f"{over:.2f} of the amount would pass the picks sleeve's {ctx['ceiling']:.0%} target and is left out")
    return amount, over


def _placed(alloc: dict[str, dict[str, float]]) -> float:
    return sum(v for a in alloc.values() for v in a.values() if v > 0)


def run_sleeves(params: dict) -> dict:
    """Build the sleeve mix and plan for ``params``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    mode = params.get("mode")
    if mode not in _MODES:
        raise ValueError("mode must be mix, add, new-pick or rebalance")
    settings = params.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    roles = _read_accounts(params)
    positions = _read_positions(params, roles)
    cash = _read_cash(params, roles)
    used, source = _settings_used(settings, params)
    if used["depth"] == "deep" and isinstance(params.get("picks"), dict):
        # A light pick at deep depth holds like one whose deep valuation is due (DEEP_VALUATION_NEEDED).
        params = {**params, "picks": {sym: {**p, "needs_valuation": True, "recheck_due": True}
                                      if isinstance(p, dict) and p.get("kind") == "light" else p
                                      for sym, p in params["picks"].items()}}
    if params.get("today"):
        _day(params["today"], "today")
    flags: list[dict] = []
    ctx = _classify(positions, cash, roles, used["ceiling"], source,
                    params.get("sectors") or {}, params.get("employer_sector"), flags,
                    None if str(settings.get("employer_symbol") or "").upper() == "NONE" else settings.get("employer_symbol"))
    ctx["ceiling"] = used["ceiling"]
    if settings.get("employer_symbol") is None:
        _flag(flags, "STANDING_DEFAULT", "employer_symbol is unset: no employer stock is assumed, so employer shares, if any, count as picks; save plan.sleeves.EMPLOYER.members (a ticker or none) to change it")

    trading_cash = sum(v for a, v in cash.items() if roles[a] == "trading")
    spare = {a: v for a, v in cash.items() if roles[a] == "trading"}
    policy = used["short_term_gain_policy"]
    whole = bool(params.get("whole_shares"))
    alloc: dict[str, dict[str, float]] = {}
    core: dict[str, float] = {}
    over = 0.0
    new_pick = None
    unplaced = 0.0
    held_back: list[dict] = []
    lot_override: dict = {}
    core_sells: dict[str, dict[str, float]] = {}
    new_positions: list[dict] = []
    shorts: dict[str, float] = {}
    pick_flags: dict[str, list[str]] = {}
    targets: dict[str, float] | None = None

    def satellite(amount: float, left_out: float | None = None) -> tuple[dict, float]:
        """Plan ``amount`` into the picks by the strategy; returns (alloc, the part left out)."""
        nonlocal unplaced
        if left_out is None:
            amount, left_out = _limit(amount, ctx, params, flags)
        res = _strategy_add(amount, ctx, positions, spare, params, used, flags, pick_flags, shorts)
        unplaced += res["unplaced"]
        return res["alloc"], left_out

    def funded(amount: float, use_core: bool, new: dict | None = None) -> None:
        """new-pick: buys from each account's cash, then its own core."""
        nonlocal alloc, over, unplaced, core_sells
        capacity = _core_capacity(positions, params, policy == "allow", whole) if use_core else {}
        for aid, rows in capacity.items():
            spare[aid] = spare.get(aid, 0.0) + sum(r["cap"] for r in rows)
        amount, over = _limit(amount, ctx, params, flags)
        got = 0.0
        rest = None
        if new is not None and new.get("fill") and _holdings(positions, "satellite"):
            rest, new_delta = _strategy_deltas(amount, ctx, positions, params, used, flags, pick_flags, new)
            if new_delta is None:
                rest = None
            else:
                new = {**new, "needed": new_delta}
        if new is not None:
            want = min(amount, new["needed"])
            got = max(0.0, min(want, spare.get(new["account"], 0.0)))
            if want - got > _EPS:
                shorts[new["account"]] = shorts.get(new["account"], 0.0) + want - got
                unplaced += want - got
                _flag(flags, "ACCOUNT_SHORT", f"account {new['account']} is {want - got:.2f} short of money; the {new['symbol']} buy is scaled down")
            spare[new["account"]] = spare.get(new["account"], 0.0) - got
            amount -= want
        if rest is not None:
            alloc = _fund(rest, _holdings(positions, "satellite"), spare, flags, shorts)
            unplaced += max(0.0, amount - _placed(alloc))
        elif amount > _EPS:
            alloc, _ = satellite(amount, 0.0)
        if got > _EPS:
            alloc.setdefault(new["account"], {})[new["symbol"]] = got
        core_sells = _core_funding(alloc, cash, capacity, policy, shorts, held_back, lot_override, flags, whole)

    def need_amount(field: str) -> float:
        v = _num(params.get(field), field)
        if v is None or v <= 0:
            raise ValueError(f"{field} must be a positive number")
        if v > trading_cash + _EPS:
            raise ValueError(f"only {trading_cash:.2f} cash in trading accounts")
        return v

    if mode == "add":
        alloc, over = satellite(need_amount("amount"))
    elif mode == "new-pick":
        np_in = params.get("new_pick")
        if not isinstance(np_in, dict) or not np_in.get("symbol"):
            raise ValueError("new_pick requires symbol and price")
        sym = str(np_in["symbol"]).upper()
        employer = str(settings.get("employer_symbol") or "").upper()
        employer_pick = ((params.get("picks") or {}).get(sym) or {}).get("kind") == "deep"
        if employer not in ("", "NONE") and sym == employer and not employer_pick:
            raise ValueError(f"{sym} is the employer symbol; it receives satellite money only as a saved deep pick")
        if any(p["symbol"] == sym for p in positions):
            raise ValueError(f"{sym} is already held; use add")
        excluded = params.get("excluded_symbols") or []
        if not isinstance(excluded, list):
            raise ValueError("excluded_symbols must be a list")
        if sym in {str(x).upper() for x in excluded}:
            raise ValueError(f"{sym} is already held (left out of the plan: unclassified or no price); it cannot be a new pick")
        price = _num(np_in.get("price"), "new_pick.price")
        if price is None or price <= 0:
            raise ValueError("new_pick.price must be a positive number")
        amount = _num(np_in.get("amount"), "new_pick.amount")
        if amount is not None and amount <= 0:
            raise ValueError("new_pick.amount must be a positive number")
        current = {s: sum(a.values()) for s, a in _holdings(positions, "satellite").items()}
        needed = min(weights.median_pick_value(current), weights.PICK_CAP * ctx["total"])
        if not current:
            if amount is None:
                raise ValueError("no trading-account picks to size the new pick by; pass new_pick.amount")
            needed = amount
        accts = sorted(a for a, r in roles.items() if r == "trading")
        if not accts:
            raise ValueError("a new pick needs a trading account")
        held = {a: sum(p["value"] for p in positions if p["account"] == a and p["bucket"] == "satellite")
                for a in accts}
        room = {a: cash.get(a, 0.0) + sum(p["value"] for p in positions
                                          if p["account"] == a and p["bucket"] == "core") for a in accts}
        account = sorted(accts, key=lambda a: (-held[a], -room[a], a))[0]
        saved = (params.get("picks") or {}).get(sym)
        if used["depth"] == "deep" and isinstance(saved, dict) and saved.get("kind") == "light":
            raise ValueError(f"{sym} is a light pick and depth is deep: save a deep valuation for it, then open it")
        if isinstance(saved, dict) and (saved.get("recheck_due") or saved.get("age_days") is None):
            code = "DEEP_VALUATION_NEEDED" if saved.get("needs_valuation") else "RECHECK_DUE"
            why = "its deep valuation needs a rerun" if code == "DEEP_VALUATION_NEEDED" else "its valuation is due for a recheck"
            _flag(flags, code, f"{sym} still opens at the median though {why}")
        new_pick = {"symbol": sym, "needed": _r2(needed), "allocated": 0.0, "account": account}
        new_positions = [{"symbol": sym, "price": price, "account": account}]
        funded(needed if amount is None else amount, True,
               {"symbol": sym, "needed": needed, "account": account, "price": price, "fill": amount is not None})
        new_pick["allocated"] = _r2(sum(a.get(sym, 0.0) for a in alloc.values()))
    elif mode == "rebalance":
        if used["weighting"] == "size":
            raise ValueError("rebalance needs equal, market_cap or valuation; size cannot rebalance, every pick already sits at its own size")
        if params.get("sell_first"):
            raise ValueError("rebalance does not take sell_first: it sells no core fund")
        if params.get("over_ceiling"):
            raise ValueError("rebalance does not take over_ceiling: it keeps the sleeve total and does not consult the ceiling")
        if params.get("pick_store_unreadable"):
            raise ValueError("the pick store could not be read, so the picks that must hold are unknown; rebalance stops")
        if len(_holdings(positions, "satellite")) >= 2:
            res = _rebalance(ctx, positions, {a: 0.0 for a in spare}, params, used, flags, pick_flags)
            alloc, held_back, lot_override, targets = res["alloc"], res["held_back"], res["lot_override"], res["targets"]
            unplaced += res["unplaced"]
            for aid in sorted(alloc):
                if cash.get(aid, 0.0) < -_EPS and any(abs(d) > _EPS for d in alloc[aid].values()):
                    raise ValueError(f"account {aid} has negative cash ({cash[aid]:.2f}, a margin debit); rebalance cannot plan its trades until it is paid off")

    if whole:
        unplaced += _cap_to_funds(alloc, cash, core_sells, core, flags)
    accounts = _plan_accounts(positions, cash, alloc, core, params, lot_override, core_sells, new_positions)
    _bond_sales(accounts, params, flags)
    if whole:
        unplaced += _rounding_left(alloc, accounts)
    if unplaced > _EPS:
        _flag(flags, "UNALLOCATED", f"{unplaced:.2f} is not placed in buys and stays as cash")
    return {
        "mode": mode,
        "mix": ctx["mix"],
        "weighting_used": "equal" if any(f["code"] == "VALUATION_FALLBACK" for f in flags) else used["weighting"],
        "splits": _splits(_holdings(positions, "satellite"), alloc, targets, pick_flags),
        "held_back": held_back,
        "accounts": accounts,
        "trades": [t for a in accounts for t in a["rebalance"]["trades"]],
        "new_pick": new_pick,
        "over_ceiling_amount": _r2(over),
        "unallocated_amount": _r2(unplaced),
        "satellite_net": _r2(_satellite_net(positions, accounts, (new_pick or {}).get("symbol"))),
        "settings_used": {**used, "ceiling": _r4(used["ceiling"])},
        "flags": flags,
    }


def main() -> None:
    """Read JSON params from stdin, write the plan (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_sleeves(json.loads(raw))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:   # KeyError and the like are bugs
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
