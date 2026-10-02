"""Tax-aware view of a ledger (US rules): open lots with holding periods and
tax if sold, year-to-date realized gains with wash-sale detection, netting
and an estimated liability, loss carryforward, tax-loss-harvesting
candidates, and specific-lot selection for a planned sale.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python tax.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "as_of": "2026-09-04",                # optional, default today
      "transactions": [ ...ledger entries from statement-import (normalize.py) ... ],
      "prices": {"AAPL": 140.0},            # current price per symbol (optional)
      "rates": {"short_term": 0.24, "long_term": 0.15, "state": 0.0, "niit": 0.0},
                                            # decimals; defaults shown
      "min_loss": 100, "min_loss_pct": 0.05,   # harvesting thresholds
      "planned_sale": {"symbol": "AAPL", "units": 5}   # optional (singular)
      "planned_sales": [                    # optional LIST; combined with the
        {"symbol": "AAPL", "units": 5,      #   singular sale (it comes first)
         "price": 140.0,                    #   when both are given
         "sell_as_of": "2027-06-10"}        # term computed as of that date
      ]
    }

Output JSON contract (stdout)::

    {
      "as_of", "year", "rates",
      "open_lots": [{symbol, account_id, buy_date, units, cost, basis_adjustment,
                     price, value, unrealized, holding_days, term, long_term_date,
                     days_to_long_term, tax_if_sold, tax_if_sold_long}],
      "unrealized": {short, long, total, tax_if_all_sold},
      "realized": [{symbol, account_id, sell_date, units, proceeds, cost, gain,
                    holding_days, term, wash_sale, wash_buy_date, disallowed,
                    allowed_gain}],                        # sales in as_of's year
      "prior_year_sales_ignored": N,
      "summary": {short_term_net, long_term_net, disallowed_losses,
                  net_capital_gain, taxed_as, capital_gains_tax,
                  deductible_against_income, ordinary_income_tax_saved,
                  loss_carryforward, prior_year_net_losses,
                  carryforward_history: [{year, net, deductible, carryforward}],
                  dividends, dividend_tax, interest,
                  interest_tax, estimated_tax},
      "harvest_candidates": [{symbol, units, cost, value, unrealized, pct, term,
                              tax_benefit, last_buy_date, recent_buy_within_30d,
                              warning}],
      "harvest_total": {losses, tax_benefit},
      "lot_selection": {symbol, units, price, fifo: {lots, gain, tax},
                        highest_cost: {lots, gain, tax}, tax_saved_vs_fifo,
                        minimal: {lots, gain, tax}, tax_saved_vs_minimal} | null,
      "lot_selections": [<one lot_selection-shaped row per planned sale>],
      "flags": [{code, message}]     # NEAR_LONG_TERM, WASH_SALE, LOSS_CARRYFORWARD
    }

Method (US federal, simplified; state and NIIT are flat add-ons):
- Lots are matched FIFO per account and symbol. Lot cost is -amount when
  present, else units x price. SPLIT rows with units add shares pro rata.
- Holding period: long-term only when held MORE than one year (IRS Pub 550:
  the clock starts the day after the purchase), i.e. sold after the
  calendar anniversary of the buy date. long_term_date is the day after
  that anniversary; a sale on the anniversary itself is short-term, even
  when the year spans Feb 29 (366 days). A Feb 29 purchase's anniversary in
  a non-leap year is Feb 28, so it turns long-term on Mar 1.
  holding_days is the plain day count, for display only.
- Wash sale: a loss on a sale is disallowed to the extent substantially
  identical shares (same symbol, any account) were bought within 30 days
  before or after the sale, excluding the shares sold in that sale;
  the disallowed amount is added to the basis of the replacement lot.
- Netting: short-term and long-term results are netted separately, then
  against each other; a net gain is taxed at the rate of the side that
  remains; a net loss is deductible against ordinary income up to 3,000
  a year (1,500 for married filing separately -- not modelled; the script
  always uses 3,000) and the rest carries forward. The chain is replayed across every
  calendar year present in the ledger in ascending order, so the current
  year starts from the incoming carryforward; carryforward_history shows
  each year's net, 3,000 deduction and carried loss. Simplifications: a
  prior year's sales use raw gains (no wash-sale disallowance is replayed),
  and today's flat rates would apply to prior years too — a documented
  approximation for planning.
- Dividends are assumed qualified (long-term rate) and interest ordinary
  (short-term rate) unless the user says otherwise; REIT and bond-fund
  distributions are usually ordinary.
- Harvest candidates are whole positions (all lots of a symbol) with an
  unrealized loss of at least min_loss and min_loss_pct; the benefit is the
  loss times the applicable rate. A buy within the last 30 days is flagged.
- Lot selection compares FIFO with highest-cost-first (specific
  identification) and with the tax-minimal order for a planned sale at the
  given price. Tax-minimal picks long-term loss lots first (most negative
  gain per unit), then short-term loss lots, then gain lots — long-term
  before short-term, highest cost per unit first (smallest gain, lowest
  rate); ties break to the earlier buy date. tax_saved_vs_minimal is FIFO
  minus minimal. A planned sale's sell_as_of computes every holding period
  as of that date -- typically later than as_of (modelling a future sale
  that has gone long-term), but sell_as_of earlier than as_of is accepted
  with no validation and simply recomputes terms as of that past date.
- prior_year_net_losses is the sum of each prior year's negative net in
  carryforward_history (i.e. sum(-net) over rows with year < the current
  year and net < 0); each prior year's net already reflects the carry it
  absorbed from the year before it, so this is not the same as summing raw
  gains/losses per year.
Money 2 dp. This is an estimate for planning, not tax advice or a filing.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEFAULT_RATES = {"short_term": 0.24, "long_term": 0.15, "state": 0.0, "niit": 0.0}
_LOSS_DEDUCTION_CAP = 3000.0
_WASH_WINDOW_DAYS = 30
_NEAR_LT_DAYS = 60
_RECENT_BUY_WARNING = (
    "bought within the last 30 days: a partial sale at a loss is a wash sale; "
    "sell the whole position or wait"
)


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _num(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    return float(v)


def _parse_date(raw: object, field: str) -> date:
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    return date.fromisoformat(raw)


def _validate(params: dict) -> tuple[list[dict], dict]:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    txs = params.get("transactions")
    if not isinstance(txs, list) or not txs:
        raise ValueError("at least one transaction is required")
    rates = dict(_DEFAULT_RATES)
    for k, v in (params.get("rates") or {}).items():
        if k in rates:
            val = _num(v, f"rates.{k}")
            if val is None or not 0 <= val < 1:
                raise ValueError("rates must be decimals between 0 and 1 (0.24 for 24%)")
            rates[k] = val
    out = []
    for i, t in enumerate(txs):
        if not isinstance(t, dict) or not t.get("date") or not t.get("type"):
            raise ValueError(
                "each transaction requires date, type, symbol (symbol for BUY/SELL/DIVIDEND)"
            )
        kind = str(t["type"]).upper()
        if kind in ("BUY", "SELL", "DIVIDEND", "SPLIT") and not t.get("symbol"):
            raise ValueError(
                "each transaction requires date, type, symbol (symbol for BUY/SELL/DIVIDEND)"
            )
        if kind not in ("BUY", "SELL", "DIVIDEND", "SPLIT", "INTEREST"):
            continue
        out.append(
            {
                "i": i,
                "date": _parse_date(t["date"], "transaction date"),
                "type": kind,
                "symbol": str(t.get("symbol") or "").upper() or None,
                "account": str(t.get("account_id")),
                "units": _num(t.get("units"), "units"),
                "price": _num(t.get("price"), "price"),
                "amount": _num(t.get("amount"), "amount"),
                "fee": _num(t.get("fee"), "fee") or 0.0,
            }
        )
    return sorted(out, key=lambda t: (t["date"], t["i"])), rates


def _anniversary(bought: date) -> date:
    """The same calendar day one year later; a Feb 29 purchase maps to Feb 28."""
    try:
        return bought.replace(year=bought.year + 1)
    except ValueError:  # Feb 29 -> a non-leap year
        return date(bought.year + 1, 2, 28)


def _long_term_date(bought: date) -> date:
    """First sale date that counts as held more than one year (the day after the anniversary)."""
    return _anniversary(bought) + timedelta(days=1)


def _term(bought: date, sold: date) -> str:
    return "long" if sold >= _long_term_date(bought) else "short"


def _rate_for(term: str, rates: dict) -> float:
    return (
        (rates["long_term"] if term == "long" else rates["short_term"])
        + rates["state"]
        + rates["niit"]
    )


def run_tax(params: dict) -> dict:
    """Compute the tax view described by ``params``; raises ValueError/TypeError on bad input."""
    events, rates = _validate(params)
    as_of = (
        _parse_date(params["as_of"], "as_of") if params.get("as_of") is not None else date.today()
    )
    year = as_of.year
    prices = {str(k).upper(): _num(v, "price") for k, v in (params.get("prices") or {}).items()}
    min_loss = _num(params.get("min_loss"), "min_loss")
    min_loss = 100.0 if min_loss is None else min_loss
    min_pct = _num(params.get("min_loss_pct"), "min_loss_pct")
    min_pct = 0.05 if min_pct is None else min_pct

    # --- lot engine -------------------------------------------------------------------
    lots: dict[tuple[str, str], list[dict]] = {}
    all_lots: list[dict] = []
    sales: list[dict] = []
    buys_by_symbol: dict[str, list[dict]] = {}
    dividends = interest = 0.0
    prior_year_sales = 0
    for e in events:
        if e["type"] == "DIVIDEND":
            if e["date"].year == year:
                dividends += abs(e["amount"] or 0.0)
            continue
        if e["type"] == "INTEREST":
            if e["date"].year == year:
                interest += abs(e["amount"] or 0.0)
            continue
        key = (e["account"], e["symbol"])
        book = lots.setdefault(key, [])
        if e["type"] == "BUY":
            units = e["units"] or 0.0
            if units <= 0:
                continue
            cost = abs(
                -e["amount"] if e["amount"] is not None else units * (e["price"] or 0.0) + e["fee"]
            )
            lot = {
                "symbol": e["symbol"],
                "account": e["account"],
                "date": e["date"],
                "units": units,
                "orig_units": units,
                "cost": cost,
                "adjust": 0.0,
            }
            book.append(lot)
            all_lots.append(lot)
            buys_by_symbol.setdefault(e["symbol"], []).append(lot)
        elif e["type"] == "SPLIT":
            added = e["units"] or 0.0
            held = sum(lot["units"] for lot in book)
            if added > 0 and held > 0:
                for lot in book:
                    lot["units"] += added * lot["units"] / held
        elif e["type"] == "SELL":
            units = e["units"] or 0.0
            if units <= 0:
                continue
            if e["date"].year < year:
                prior_year_sales += 1
            proceeds_total = (
                abs(e["amount"])
                if e["amount"] is not None
                else units * (e["price"] or 0.0) - e["fee"]
            )
            remaining = units
            consumed: list[dict] = []
            cost = 0.0
            first: date | None = None
            while remaining > 1e-12 and book:
                lot = book[0]
                take = min(lot["units"], remaining)
                frac = take / lot["units"]
                lot_cost = lot["cost"] * frac
                cost += lot_cost
                consumed.append(lot)
                first = lot["date"] if first is None or lot["date"] < first else first
                lot["units"] -= take
                lot["cost"] -= lot_cost
                remaining -= take
                if lot["units"] <= 1e-12:
                    book.pop(0)
            matched = units - remaining
            if matched <= 1e-12 or first is None:
                continue
            proceeds = proceeds_total * matched / units
            sales.append(
                {
                    "symbol": e["symbol"],
                    "account": e["account"],
                    "date": e["date"],
                    "units": matched,
                    "proceeds": proceeds,
                    "cost": cost,
                    "first": first,
                    "consumed": consumed,
                    "price": e["price"] or proceeds / matched,
                }
            )

    # --- wash sales (any account; replacement = buys in the window not sold in this sale) -----
    realized: list[dict] = []
    flags: list[dict] = []
    for s in sales:
        gain = s["proceeds"] - s["cost"]
        days = (s["date"] - s["first"]).days
        wash_date = None
        disallowed = 0.0
        if gain < 0:
            lo, hi = (
                s["date"] - timedelta(days=_WASH_WINDOW_DAYS),
                s["date"] + timedelta(days=_WASH_WINDOW_DAYS),
            )
            repl = [
                lot
                for lot in buys_by_symbol.get(s["symbol"], [])
                if lo <= lot["date"] <= hi and lot not in s["consumed"]
            ]
            repl_units = sum(lot["orig_units"] for lot in repl)
            if repl_units > 0:
                disallowed = -gain * min(repl_units, s["units"]) / s["units"]
                wash_date = min(lot["date"] for lot in repl).isoformat()
                # add the disallowed loss to the basis of the replacement lot(s), pro rata by units
                for lot in repl:
                    share = disallowed * lot["orig_units"] / repl_units
                    lot["adjust"] += share
                    lot["cost"] += (
                        share * (lot["units"] / lot["orig_units"]) if lot["orig_units"] else 0.0
                    )
        if s["date"].year != year:
            continue
        realized.append(
            {
                "symbol": s["symbol"],
                "account_id": s["account"],
                "sell_date": s["date"].isoformat(),
                "units": _r4(s["units"]),
                "proceeds": _r2(s["proceeds"]),
                "cost": _r2(s["cost"]),
                "gain": _r2(gain),
                "holding_days": days,
                "term": _term(s["first"], s["date"]),
                "wash_sale": disallowed > 0,
                "wash_buy_date": wash_date,
                "disallowed": _r2(disallowed),
                "allowed_gain": _r2(gain + disallowed),
            }
        )
        if disallowed > 0:
            msg = (
                f"{s['symbol']} loss of {_r2(-gain)} on {s['date'].isoformat()} is disallowed "
                f"({_r2(disallowed)}) by the {wash_date} purchase; "
                "the amount is added to that lot's basis"
            )
            flags.append({"code": "WASH_SALE", "message": msg})

    # --- open lots ---------------------------------------------------------------------
    open_lots = []
    for lot in all_lots:
        if lot["units"] <= 1e-12:
            continue
        price = prices.get(lot["symbol"])
        value = lot["units"] * price if price is not None else None
        unreal = value - lot["cost"] if value is not None else None
        days = (as_of - lot["date"]).days
        term = _term(lot["date"], as_of)
        lt_date = _long_term_date(lot["date"])
        to_lt = max((lt_date - as_of).days, 0)
        tax_now = unreal * _rate_for(term, rates) if unreal is not None else None
        tax_long = unreal * _rate_for("long", rates) if unreal is not None else None
        row = {
            "symbol": lot["symbol"],
            "account_id": lot["account"],
            "buy_date": lot["date"].isoformat(),
            "units": _r4(lot["units"]),
            "cost": _r2(lot["cost"]),
            "basis_adjustment": _r2(lot["adjust"]),
            "price": _r2(price),
            "value": _r2(value),
            "unrealized": _r2(unreal),
            "holding_days": days,
            "term": term,
            "long_term_date": lt_date.isoformat(),
            "days_to_long_term": to_lt,
            "tax_if_sold": _r2(tax_now),
            "tax_if_sold_long": _r2(tax_long),
        }
        open_lots.append(row)
        if unreal is not None and unreal > 0 and 0 < to_lt <= _NEAR_LT_DAYS:
            msg = (
                f"{lot['symbol']} lot of {row['buy_date']} turns long-term "
                f"on {row['long_term_date']} "
                f"({to_lt} days): waiting saves an estimated {_r2(tax_now - tax_long):.2f} "
                f"on a {_r2(unreal):.2f} gain"
            )
            flags.append({"code": "NEAR_LONG_TERM", "message": msg})
    open_lots.sort(key=lambda lot: (lot["symbol"], lot["account_id"], lot["buy_date"]))
    priced = [lot for lot in open_lots if lot["unrealized"] is not None]
    unreal_short = sum(lot["unrealized"] for lot in priced if lot["term"] == "short")
    unreal_long = sum(lot["unrealized"] for lot in priced if lot["term"] == "long")
    unrealized = {
        "short": _r2(unreal_short),
        "long": _r2(unreal_long),
        "total": _r2(unreal_short + unreal_long),
        "tax_if_all_sold": _r2(sum(lot["tax_if_sold"] for lot in priced)),
    }

    # --- netting and liability (multi-year chain) --------------------------------------
    st_net = sum(r["allowed_gain"] for r in realized if r["term"] == "short")
    lt_net = sum(r["allowed_gain"] for r in realized if r["term"] == "long")
    carry_in = 0.0
    history: list[dict] = []
    prior_losses = 0.0
    cur_net = cur_deductible = cur_carry = 0.0
    for y in sorted({e["date"].year for e in events} | {year}):
        if y == year:
            gains = st_net + lt_net
        else:
            # prior years use raw gains: wash-sale disallowance is only
            # replayed for the current year (documented approximation)
            gains = sum(s["proceeds"] - s["cost"] for s in sales if s["date"].year == y)
        net = gains - carry_in
        if net < 0:
            deductible = min(-net, _LOSS_DEDUCTION_CAP)
            carry_out = -net - deductible
        else:
            deductible, carry_out = 0.0, 0.0
        if y < year and net < 0:
            prior_losses += -net
        history.append(
            {
                "year": y,
                "net": _r2(net),
                "deductible": _r2(deductible),
                "carryforward": _r2(carry_out),
            }
        )
        if y == year:
            cur_net, cur_deductible, cur_carry = net, deductible, carry_out
        carry_in = carry_out
    if cur_net > 0:
        scale = cur_net / (st_net + lt_net)  # the incoming carryforward's share
        taxed_as = "long" if lt_net > 0 and (st_net <= 0 or lt_net >= st_net) else "short"
        if st_net > 0 and lt_net > 0:
            cg_tax = scale * (
                st_net * _rate_for("short", rates) + lt_net * _rate_for("long", rates)
            )
            taxed_as = "mixed"
        else:
            cg_tax = cur_net * _rate_for(taxed_as, rates)
        cur_deductible = cur_carry = saved = 0.0
    else:
        taxed_as, cg_tax = "none", 0.0
        cur_deductible = min(-cur_net, _LOSS_DEDUCTION_CAP)
        cur_carry = -cur_net - cur_deductible
        saved = cur_deductible * (rates["short_term"] + rates["state"])
        if cur_carry > 0:
            msg = (
                f"net capital loss {_r2(-cur_net)}: {_r2(cur_deductible)} is deductible against "
                f"income this year and {_r2(cur_carry)} carries forward"
            )
            flags.append({"code": "LOSS_CARRYFORWARD", "message": msg})
    div_tax = dividends * _rate_for("long", rates)
    int_tax = interest * _rate_for("short", rates)
    summary = {
        "short_term_net": _r2(st_net),
        "long_term_net": _r2(lt_net),
        "disallowed_losses": _r2(sum(r["disallowed"] for r in realized)),
        "net_capital_gain": _r2(cur_net),
        "taxed_as": taxed_as,
        "capital_gains_tax": _r2(cg_tax),
        "deductible_against_income": _r2(cur_deductible),
        "ordinary_income_tax_saved": _r2(saved),
        "loss_carryforward": _r2(cur_carry),
        "prior_year_net_losses": _r2(prior_losses),
        "carryforward_history": history,
        "dividends": _r2(dividends),
        "dividend_tax": _r2(div_tax),
        "interest": _r2(interest),
        "interest_tax": _r2(int_tax),
        "estimated_tax": _r2(cg_tax + div_tax + int_tax - saved),
    }

    # --- harvesting candidates (whole positions) --------------------------------------
    by_symbol: dict[str, list[dict]] = {}
    for lot in priced:
        by_symbol.setdefault(lot["symbol"], []).append(lot)
    candidates = []
    for sym, rows in sorted(by_symbol.items()):
        unreal = sum(lot["unrealized"] for lot in rows)
        cost = sum(lot["cost"] for lot in rows)
        if unreal >= 0 or -unreal < min_loss or (cost and -unreal / cost < min_pct):
            continue
        term = (
            "long"
            if all(lot["term"] == "long" for lot in rows)
            else "short"
            if all(lot["term"] == "short" for lot in rows)
            else "mixed"
        )
        benefit = sum(-lot["unrealized"] * _rate_for(lot["term"], rates) for lot in rows)
        last_buy = max(lot["date"] for lot in buys_by_symbol.get(sym, []))
        recent = (as_of - last_buy).days <= _WASH_WINDOW_DAYS
        candidates.append(
            {
                "symbol": sym,
                "units": _r4(sum(lot["units"] for lot in rows)),
                "cost": _r2(cost),
                "value": _r2(sum(lot["value"] for lot in rows)),
                "unrealized": _r2(unreal),
                "pct": _r4(unreal / cost) if cost else None,
                "term": term,
                "tax_benefit": _r2(benefit),
                "last_buy_date": last_buy.isoformat(),
                "recent_buy_within_30d": recent,
                "warning": _RECENT_BUY_WARNING if recent else None,
            }
        )
    harvest_total = {
        "losses": _r2(sum(c["unrealized"] for c in candidates)),
        "tax_benefit": _r2(sum(c["tax_benefit"] for c in candidates)),
    }

    # --- planned sales: FIFO vs highest cost vs tax-minimal ---------------------------
    def _build_selection(
        sym: str, want: float, price: float | None, when: date, label: str
    ) -> dict:
        rows = [lot for lot in open_lots if lot["symbol"] == sym]
        if not rows:
            raise ValueError(f"no open lots for {sym}")
        if price is None:
            raise ValueError(f"a price for {sym} is required for the planned sale")
        held = sum(lot["units"] for lot in rows)
        if want <= 0 or want > held + 1e-9:
            raise ValueError(f"{label}.units must be between 0 and the {held} units held")
        if when == as_of:
            rows_for_term = rows
        else:
            rows_for_term = []
            for lot in rows:
                row = dict(lot)
                row["term"] = _term(date.fromisoformat(lot["buy_date"]), when)
                rows_for_term.append(row)

        def pick(order: list[dict]) -> dict:
            left, out_lots, gain, tax = want, [], 0.0, 0.0
            for lot in order:
                if left <= 1e-12:
                    break
                take = min(lot["units"], left)
                cost = lot["cost"] * take / lot["units"]
                g = take * price - cost
                out_lots.append(
                    {
                        "buy_date": lot["buy_date"],
                        "units": _r4(take),
                        "cost": _r2(cost),
                        "gain": _r2(g),
                        "term": lot["term"],
                    }
                )
                gain += g
                tax += g * _rate_for(lot["term"], rates)
                left -= take
            return {"lots": out_lots, "gain": _r2(gain), "tax": _r2(tax)}

        def minimal_key(lot: dict) -> tuple:
            per_unit = price - lot["cost"] / lot["units"]
            if per_unit < 0:  # loss lots: long-term first, most negative first
                return (0 if lot["term"] == "long" else 1, per_unit, lot["buy_date"])
            # gain lots: long-term first, highest cost per unit (smallest gain) first
            bucket = 2 if lot["term"] == "long" else 3
            return (bucket, -(lot["cost"] / lot["units"]), lot["buy_date"])

        fifo = pick(sorted(rows_for_term, key=lambda lot: lot["buy_date"]))
        highest = pick(
            sorted(rows_for_term, key=lambda lot: (-(lot["cost"] / lot["units"]), lot["buy_date"]))
        )
        minimal = pick(sorted(rows_for_term, key=minimal_key))
        return {
            "symbol": sym,
            "units": _r4(want),
            "price": _r2(price),
            "fifo": fifo,
            "highest_cost": highest,
            "tax_saved_vs_fifo": _r2(fifo["tax"] - highest["tax"]),
            "minimal": minimal,
            "tax_saved_vs_minimal": _r2(fifo["tax"] - minimal["tax"]),
        }

    selection = None
    selections: list[dict] = []
    plan = params.get("planned_sale")
    if isinstance(plan, dict) and plan.get("symbol"):
        sym = str(plan["symbol"]).upper()
        want = _num(plan.get("units"), "planned_sale.units") or 0.0
        price = _num(plan.get("price"), "planned_sale.price")
        if price is None:
            price = prices.get(sym)
        when = as_of
        if plan.get("sell_as_of") is not None:
            when = _parse_date(plan["sell_as_of"], "planned_sale.sell_as_of")
        selection = _build_selection(sym, want, price, when, "planned_sale")
    planned_sales = params.get("planned_sales")
    if planned_sales is not None:
        if not isinstance(planned_sales, list):
            raise ValueError("planned_sales must be a list")
        for item in planned_sales:
            if not isinstance(item, dict) or not item.get("symbol"):
                raise ValueError("each planned_sales entry requires symbol and units")
            sym = str(item["symbol"]).upper()
            want = _num(item.get("units"), "planned_sales.units") or 0.0
            price = _num(item.get("price"), "planned_sales.price")
            if price is None:
                price = prices.get(sym)
            when = as_of
            if item.get("sell_as_of") is not None:
                when = _parse_date(item["sell_as_of"], "planned_sales.sell_as_of")
            selections.append(_build_selection(sym, want, price, when, "planned_sales"))
    if selection is not None:
        selections.insert(0, selection)  # combined with the singular planned sale

    return {
        "as_of": as_of.isoformat(),
        "year": year,
        "rates": rates,
        "open_lots": open_lots,
        "unrealized": unrealized,
        "realized": sorted(realized, key=lambda r: (r["sell_date"], r["symbol"])),
        "prior_year_sales_ignored": prior_year_sales,
        "summary": summary,
        "harvest_candidates": candidates,
        "harvest_total": harvest_total,
        "lot_selection": selection,
        "lot_selections": selections,
        "flags": flags,
    }


def main() -> None:
    """Read JSON params from stdin, write the tax view (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_tax(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
