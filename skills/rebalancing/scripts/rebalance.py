"""Rebalancing: drift against target weights, band breaches, and a trade list
that reaches the targets (full rebalance) or routes new cash (contribution
only), with whole-share, minimum-trade and tax-aware lot handling.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python rebalance.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "positions": [{"symbol": "VTI", "units": 60, "price": 100.0}, ...],
      "cash": 500,
      "targets": {"VTI": 0.6, "BND": 0.3, "CASH": 0.1},   # weights sum to 1;
                                            # keys are symbols, or class names
                                            # when "classes" is given; CASH is
                                            # optional (default target 0)
      "classes": {"VTI": "stocks", "BND": "bonds"},       # optional symbol -> key;
                                            # unmapped symbols are frozen
      "bands": {"absolute": 0.05, "relative": 0.25},      # 5/25 rule (default)
      "contribution": 2000,                 # new cash (negative = withdrawal)
      "allow_sells": true,                  # false -> contribution-only mode
      "whole_shares": false, "min_trade": 0,
      "only_if_breached": false,            # true -> no trades unless a band is breached
      "lots": {"VTI": [{"units": 30, "cost_per_unit": 80.0, "term": "long",
                        "account": "roth-1"}]},   # optional; "account" is optional
      "rates": {"short_term": 0.24, "long_term": 0.15},   # optional, for est_tax
      "accounts": {"roth-1": {"taxable": false}},         # optional account taxability;
                                            # unlisted accounts count as taxable
      # every position may also carry "account": "<id>"; a lot's "account" matches
      # only sells in that account (a sell with no account never takes a tagged
      # lot), account-less lots match any account
    }

Output JSON contract (stdout)::

    {
      "mode": "full" | "contribution", "total_value", "frozen_value",
      "contribution", "withdrawal", "bands", "max_drift",
      "allocation": [{key, members, value, weight, target, drift, relative_drift,
                      breach, target_value, delta_value}],
      "trades": [{symbol, side, units, price, value, reason, lots, est_gain, est_tax,
                  account}],          # sells first, largest first; account null when
                                      # the position carried no account id
      "post_trade": [{key, value, weight, target, drift}],
      "cash_after", "buys_total", "sells_total", "turnover",
      "est_realized_gain", "est_tax", "frozen": [{symbol, value}],
      "routing": null | {             # null when no position carries an account and
        "accounts": {id: "taxable" | "tax_advantaged"},   # no accounts map is given
        "neutral": [sell rows pro rata across all accounts holding the symbol;
                    same shape as trades rows minus reason/lots],
        "tax_preferred": [the sells actually in trades],
        "est_tax": <tax_preferred total>, "est_tax_pro_rata": <neutral total>},
      "flags": [{code, message}]     # BAND_BREACH, WITHIN_BANDS, PARTIAL,
                                     # BELOW_MIN_TRADE, UNMAPPED, NO_HOLDINGS
    }

Method: the rebalanced universe is every mapped position plus cash plus the
contribution; frozen (unmapped) positions are reported but excluded. A key
breaches when |drift| >= absolute band or |drift / target| >= relative band
(Swedroe's 5/25 rule). Full mode sells overweights and buys underweights to
the target values; class deltas are spread across members pro rata to their
current value. Contribution mode never sells: it funds shortfalls from the
cash above the cash target, most underweight first. Whole shares round down.
Sells pick the highest-cost lots first when lots are given; est_tax applies
the term rate to each lot's gain. turnover = (buys + sells) / 2 / total.
Account-aware routing: when at least one position carries an "account" AND at
least one account is flagged non-taxable, a key's SELL amounts are unchanged
but are filled from tax-advantaged accounts first (pro rata to value within
the tax-advantaged group, then the taxable group); a lot sold in a
non-taxable account contributes est_gain but est_tax 0, and the "routing"
block reports the pro-rata ("neutral") sell list and its tax next to the
preferred one. Buys and contribution mode are unchanged. Money 2 dp, weights
4 dp. This produces a plan, not orders.
"""

from __future__ import annotations

import json
import math
import sys
from decimal import ROUND_HALF_UP, Decimal

_DEFAULT_BANDS = {"absolute": 0.05, "relative": 0.25}
_CASH = "CASH"
_NO_HOLDINGS_MSG = "{key} has a target but no holdings to buy; name a symbol for it"
_TAX_ADV = "tax_advantaged"
_TAXABLE = "taxable"


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _num(v: object, field: str, required: bool = False) -> float | None:
    if v is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    return float(v)


def _pct1(v: float) -> str:
    """Percent with one decimal, rounded half-up (11.25% -> 11.3%)."""
    return str(
        Decimal(str(round(abs(v) * 100, 6))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    )


def _pct(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}{_pct1(v)}%"


def _pro_rata(rows: list[dict], amount: float) -> list[tuple[str | None, float]]:
    """Spread ``amount`` over ``rows`` pro rata to value -> [(account, share)]."""
    group = sum(r["value"] for r in rows)
    if group <= 0:
        n = len(rows)
        return [(r["account"], amount / n) for r in rows]
    return [(r["account"], amount * r["value"] / group) for r in rows]


def run_rebalance(params: dict) -> dict:
    """Build the rebalance plan for ``params``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    positions_in = params.get("positions") or []
    cash = _num(params.get("cash"), "cash") or 0.0
    if not isinstance(positions_in, list) or (not positions_in and cash <= 0):
        raise ValueError("positions or cash are required")
    targets_in = params.get("targets")
    if not isinstance(targets_in, dict) or not targets_in:
        raise ValueError("targets are required")
    targets: dict[str, float] = {}
    for k, v in targets_in.items():
        w = _num(v, f"targets.{k}", True)
        if not 0 <= w <= 1:
            raise ValueError("target weights must be between 0 and 1")
        targets[str(k).upper() if str(k).upper() == _CASH else str(k)] = w
    if abs(sum(targets.values()) - 1.0) > 0.001:
        raise ValueError("targets must sum to 1 (100%)")
    classes = {str(k).upper(): str(v) for k, v in (params.get("classes") or {}).items()}
    bands = {
        **_DEFAULT_BANDS,
        **{k: _num(v, f"bands.{k}") for k, v in (params.get("bands") or {}).items()},
    }
    contribution = _num(params.get("contribution"), "contribution") or 0.0
    allow_sells = params.get("allow_sells", True) is not False
    whole = bool(params.get("whole_shares", False))
    min_trade = _num(params.get("min_trade"), "min_trade") or 0.0
    lots_in = params.get("lots") or {}
    rates = {
        "short_term": 0.24,
        "long_term": 0.15,
        **{k: _num(v, f"rates.{k}") for k, v in (params.get("rates") or {}).items()},
    }

    # --- accounts ----------------------------------------------------------------------------
    tax_map: dict[str, bool] = {}  # account id -> taxable flag (default True)
    for aid, info in (params.get("accounts") or {}).items():
        if not isinstance(info, dict):
            raise ValueError("each accounts entry must be an object with a taxable flag")
        tax_map[str(aid)] = info.get("taxable") is not False

    def is_taxable(aid: str | None) -> bool:
        return tax_map.get(aid, True) if aid is not None else True

    # --- positions -> keys -----------------------------------------------------------------
    positions: list[dict] = []
    frozen: list[dict] = []
    for p in positions_in:
        if (
            not isinstance(p, dict)
            or not p.get("symbol")
            or p.get("units") is None
            or p.get("price") is None
        ):
            raise ValueError("each position requires symbol, units and price")
        sym = str(p["symbol"]).upper()
        units, price = _num(p["units"], "units"), _num(p["price"], "price")
        value = units * price
        if sym in targets:
            key = sym
        elif sym in classes and classes[sym] in targets:
            key = classes[sym]
        elif classes:
            frozen.append({"symbol": sym, "value": _r2(value)})
            continue
        else:
            raise ValueError(
                f"{sym} has no target and no class; add it to targets, classes, "
                "or set its target to 0"
            )
        account = p.get("account")
        if account is not None:
            account = str(account)
            tax_map.setdefault(account, True)
        positions.append(
            {
                "symbol": sym,
                "units": units,
                "price": price,
                "value": value,
                "key": key,
                "account": account,
            }
        )

    cash_avail = cash + contribution
    total = sum(p["value"] for p in positions) + cash_avail
    if total <= 0:
        raise ValueError("the rebalanced universe has no value")
    keys = list(targets)
    if _CASH not in targets:
        targets[_CASH] = 0.0
        keys.append(_CASH)

    def key_value(key: str) -> float:
        return cash_avail if key == _CASH else sum(p["value"] for p in positions if p["key"] == key)

    allocation = []
    breached = []
    for key in keys:
        value, target = key_value(key), targets[key]
        weight = value / total
        drift = weight - target
        rel = drift / target if target > 0 else None
        breach = abs(drift) >= bands["absolute"] or (
            rel is not None and abs(rel) >= bands["relative"]
        )
        if breach:
            breached.append((key, drift))
        allocation.append(
            {
                "key": key,
                "members": sorted({p["symbol"] for p in positions if p["key"] == key})
                if key != _CASH
                else [],
                "value": _r2(value),
                "weight": _r4(weight),
                "target": target,
                "drift": _r4(drift),
                "relative_drift": _r4(rel),
                "breach": breach,
                "target_value": _r2(target * total),
                "delta_value": _r2(target * total - value),
            }
        )
    flags: list[dict] = []
    if breached:
        abs_pct, rel_pct = f"{bands['absolute'] * 100:g}", f"{bands['relative'] * 100:g}"
        detail = ", ".join(f"{k} ({_pct(d)})" for k, d in sorted(breached))
        flags.append(
            {
                "code": "BAND_BREACH",
                "message": f"outside the {abs_pct}% / {rel_pct}% bands: {detail}",
            }
        )
    if frozen:
        flags.append(
            {
                "code": "UNMAPPED",
                "message": "not in classes and left untouched: "
                + ", ".join(f"{f['symbol']} ({f['value']:.2f})" for f in frozen),
            }
        )

    # --- trades --------------------------------------------------------------------------------
    mode = "full" if allow_sells else "contribution"
    trades: list[dict] = []
    skipped: list[str] = []
    drift_by_key = {a["key"]: a["drift"] for a in allocation}
    any_account = any(p["account"] for p in positions)
    routing_active = bool(any_account) and any(not t for t in tax_map.values())
    sells_by_symbol: dict[str, float] = {}  # pre-rounding sell values, for the neutral list

    def add_trade(
        symbol: str, side: str, value: float, price: float, key: str, account: str | None = None
    ) -> None:
        units = value / price
        if whole:
            units = math.floor(units + 1e-9)
        value = units * price
        if units <= 0:
            return
        if min_trade and value < min_trade:
            skipped.append(f"{symbol} {side.lower()} {value:.2f}")
            return
        d = drift_by_key[key]
        trades.append(
            {
                "symbol": symbol,
                "side": side,
                "units": _r4(units),
                "price": _r2(price),
                "value": _r2(value),
                "reason": f"{'overweight' if d > 0 else 'underweight'} by {_pct1(d)}%",
                "account": account,
                "_key": key,
                "_units": units,
                "_value": value,
            }
        )

    if params.get("only_if_breached") and not breached and contribution == 0:
        flags.append(
            {
                "code": "WITHIN_BANDS",
                "message": "every target is inside its band; no trades generated",
            }
        )
    elif allow_sells:
        for key in keys:
            if key == _CASH:
                continue
            delta = targets[key] * total - key_value(key)
            members = [p for p in positions if p["key"] == key]
            if not members:
                if delta > 0:
                    flags.append(
                        {
                            "code": "NO_HOLDINGS",
                            "message": _NO_HOLDINGS_MSG.format(key=key),
                        }
                    )
                continue
            class_value = sum(p["value"] for p in members)
            if routing_active:
                amounts: dict[str, float] = {}
                for p in members:
                    share = p["value"] / class_value if class_value > 0 else 1.0 / len(members)
                    amount = delta * share
                    if abs(amount) < 0.005:
                        continue
                    amounts[p["symbol"]] = amounts.get(p["symbol"], 0.0) + amount
                for sym, amount in sorted(amounts.items()):
                    rows = [p for p in members if p["symbol"] == sym]
                    price = rows[0]["price"]
                    if amount < 0:
                        sells_by_symbol[sym] = sells_by_symbol.get(sym, 0.0) - amount
                        remaining = -amount
                        adv = [r for r in rows if not is_taxable(r["account"])]
                        if adv:
                            cap = sum(r["value"] for r in adv)
                            take = min(cap, remaining)
                            for aid, seg in _pro_rata(adv, take):
                                add_trade(sym, "SELL", seg, price, key, aid)
                            remaining -= take
                        if remaining > 0.005:
                            for aid, seg in _pro_rata(
                                [r for r in rows if is_taxable(r["account"])], remaining
                            ):
                                add_trade(sym, "SELL", seg, price, key, aid)
                    else:
                        accounts_ = {r["account"] for r in rows}
                        add_trade(
                            sym,
                            "BUY",
                            amount,
                            price,
                            key,
                            accounts_.pop() if len(accounts_) == 1 else None,
                        )
            else:
                for p in members:
                    share = p["value"] / class_value if class_value > 0 else 1.0 / len(members)
                    amount = delta * share
                    if abs(amount) < 0.005:
                        continue
                    add_trade(
                        p["symbol"],
                        "SELL" if amount < 0 else "BUY",
                        abs(amount),
                        p["price"],
                        key,
                        p["account"],
                    )
    else:
        budget = cash_avail - targets[_CASH] * total
        short = []
        for key in keys:
            if key == _CASH:
                continue
            need = targets[key] * total - key_value(key)
            if need > 0.005:
                short.append((drift_by_key[key], key, need))
        short.sort()
        for _, key, need in short:
            if budget <= 0.005:
                break
            spend = min(need, budget)
            members = [p for p in positions if p["key"] == key]
            if not members:
                flags.append(
                    {
                        "code": "NO_HOLDINGS",
                        "message": _NO_HOLDINGS_MSG.format(key=key),
                    }
                )
                continue
            class_value = sum(p["value"] for p in members)
            for p in members:
                share = p["value"] / class_value if class_value > 0 else 1.0 / len(members)
                add_trade(p["symbol"], "BUY", spend * share, p["price"], key)
            budget -= spend
        over = [k for k in keys if k != _CASH and drift_by_key[k] > 0.0005]
        unfilled = [
            k for _, k, need in short if need > 0 and not any(t["_key"] == k for t in trades)
        ]
        if over or (unfilled and budget <= 0.005):
            who = ", ".join(over) if over else ", ".join(unfilled)
            side = "overweight" if over else "underweight"
            flags.append(
                {
                    "code": "PARTIAL",
                    "message": f"cash-only rebalance cannot reach every target; {who} stays {side} "
                    "(sells disabled)",
                }
            )
    if skipped:
        flags.append(
            {
                "code": "BELOW_MIN_TRADE",
                "message": f"skipped trades under {min_trade:,.2f}: " + ", ".join(skipped),
            }
        )
    trades.sort(key=lambda t: (t["side"] != "SELL", -t["_value"], t["symbol"]))

    # --- tax-aware lots --------------------------------------------------------------------
    fresh = {s: [float(lot.get("units") or 0) for lot in entries] for s, entries in lots_in.items()}
    lot_state = {s: list(v) for s, v in fresh.items()}

    def fill_lots(
        symbol: str, units: float, price: float, account: str | None
    ) -> tuple[list[dict], float, float]:
        """Pick the highest-cost unconsumed lots for a sale of ``units`` in
        ``account``; account-tagged lots match only that account, account-less
        lots match any. Returns (picked, gain, tax); tax is 0 in a
        non-taxable account."""
        entries = lots_in.get(symbol) or []
        if not entries:
            return [], 0.0, 0.0
        state = lot_state.setdefault(symbol, list(fresh[symbol]))
        order = sorted(
            range(len(entries)), key=lambda i: -float(entries[i].get("cost_per_unit") or 0)
        )
        picked: list[dict] = []
        gain = tax = 0.0
        remaining = units
        for i in order:
            if remaining <= 1e-9:
                break
            lot = entries[i]
            lacc = lot.get("account")
            if lacc is not None and (account is None or str(lacc) != str(account)):
                continue  # an account-tagged lot only fills a sell in that account
            take = min(state[i], remaining)
            if take <= 1e-9:
                continue
            cost = float(lot.get("cost_per_unit") or 0)
            term = str(lot.get("term") or "short")
            g = take * (price - cost)
            picked.append(
                {"units": _r4(take), "cost_per_unit": _r2(cost), "term": term, "gain": _r2(g)}
            )
            gain += g
            if is_taxable(account):
                tax += g * (rates["long_term"] if term == "long" else rates["short_term"])
            state[i] -= take
            remaining -= take
        return picked, gain, tax

    any_lots = False
    total_gain = total_tax = 0.0
    for t in trades:
        t["lots"] = t["est_gain"] = t["est_tax"] = None
        if t["side"] != "SELL" or not lots_in.get(t["symbol"]):
            continue
        any_lots = True
        picked, gain, tax = fill_lots(t["symbol"], t["_units"], t["price"], t["account"])
        t["lots"], t["est_gain"], t["est_tax"] = picked, _r2(gain), _r2(tax)
        total_gain += gain
        total_tax += tax

    # --- routing block -----------------------------------------------------------------------
    routing: dict | None = None
    if any_account or tax_map:
        neutral: list[dict] = []
        neutral_tax = 0.0
        if routing_active:
            lot_state = {s: list(v) for s, v in fresh.items()}  # a fresh pass for the neutral list
            for sym, value in sorted(sells_by_symbol.items()):
                rows = [p for p in positions if p["symbol"] == sym]
                price = rows[0]["price"]
                for aid, seg in _pro_rata(rows, value):
                    units = seg / price
                    picked, gain, tax = fill_lots(sym, units, price, aid)
                    neutral.append(
                        {
                            "symbol": sym,
                            "side": "SELL",
                            "units": _r4(units),
                            "price": _r2(price),
                            "value": _r2(seg),
                            "account": aid,
                            "est_gain": _r2(gain) if lots_in.get(sym) else None,
                            "est_tax": _r2(tax) if lots_in.get(sym) else None,
                        }
                    )
                    neutral_tax += tax
        routing = {
            "accounts": {
                aid: (_TAX_ADV if not taxable else _TAXABLE)
                for aid, taxable in sorted(tax_map.items())
            },
            "neutral": neutral,
            "tax_preferred": [
                {
                    k: t[k]
                    for k in (
                        "symbol",
                        "side",
                        "units",
                        "price",
                        "value",
                        "account",
                        "est_gain",
                        "est_tax",
                    )
                }
                for t in trades
                if t["side"] == "SELL"
            ],
            "est_tax": _r2(sum(t["est_tax"] or 0.0 for t in trades if t["side"] == "SELL")),
            "est_tax_pro_rata": _r2(neutral_tax),
        }

    # --- post-trade ----------------------------------------------------------------------------
    sells = sum(t["_value"] for t in trades if t["side"] == "SELL")
    buys = sum(t["_value"] for t in trades if t["side"] == "BUY")
    cash_after = cash_avail + sells - buys
    post_values = {k: key_value(k) for k in keys}
    for t in trades:
        post_values[t["_key"]] += t["_value"] if t["side"] == "BUY" else -t["_value"]
    post_values[_CASH] = cash_after
    post = [
        {
            "key": k,
            "value": _r2(v),
            "weight": _r4(v / total),
            "target": targets[k],
            "drift": _r4(v / total - targets[k]),
        }
        for k, v in post_values.items()
    ]
    for t in trades:
        for k in ("_key", "_units", "_value"):
            t.pop(k)

    return {
        "mode": mode,
        "total_value": _r2(total),
        "frozen_value": _r2(sum(f["value"] for f in frozen)),
        "contribution": _r2(max(contribution, 0.0)),
        "withdrawal": _r2(max(-contribution, 0.0)),
        "bands": {"absolute": bands["absolute"], "relative": bands["relative"]},
        "max_drift": _r4(max(abs(a["drift"]) for a in allocation)),
        "allocation": allocation,
        "trades": trades,
        "post_trade": post,
        "cash_after": _r2(cash_after),
        "buys_total": _r2(buys),
        "sells_total": _r2(sells),
        "turnover": _r4((buys + sells) / 2 / total),
        "est_realized_gain": _r2(total_gain) if any_lots else None,
        "est_tax": _r2(total_tax) if any_lots else None,
        "routing": routing,
        "frozen": frozen,
        "flags": flags,
    }


def main() -> None:
    """Read JSON params from stdin, write the plan (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_rebalance(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
