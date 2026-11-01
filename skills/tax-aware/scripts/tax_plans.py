#!/usr/bin/env python3
"""The math of the tax-aware deep review: multi-year plans compared on after-tax wealth (stdin -> stdout JSON).

    python tax_plans.py < plans.json

Input: {"as_of", "filing": "single"|"mfj"|"mfs"|"hoh", "book": <tax-report.py result>, "years":
[2026, ...], "rule_tables": {"2026": {"status": "enacted"|"projected", "standard_deduction",
"ordinary": [[up_to, rate], ..., [null, rate]], "long_term": [[up_to, rate], ..., [null, rate]],
"niit_threshold", "niit_rate", "loss_limit", "source", "primary", "date"}}, "rules": [{"rule", "says",
"source", "primary", "date"}], "income": {"2026": {"ordinary", "qualified_dividends" (optional),
"withheld" (optional)}}, "accounts": {"traditional", "traditional_basis", "roth"}, "assumptions":
{"growth", "exit_long_term", "exit_ordinary", "state_rate"}, "plans": [{"name", "why", "actions":
[{"type": "sell", "year", "symbol", "units", "date" (optional, default year end), "order":
"fifo"|"highest_cost" (default fifo)} | {"type": "roth_convert", "year", "amount"}]}], "tests":
[{"name", "why", "changes": {assumption: value}}]}.

The first plan must have no actions: it is the baseline. A sell action needs the capital_gains,
loss_limit and wash_sale rules cited, and a conversion needs roth_conversion.

Each year: ordinary income plus the taxable part of conversions (pro rata against the Traditional
balance's after-tax basis) plus net short-term gain, less the standard deduction and the allowed
capital loss, falls on the ordinary brackets. Net long-term gain and qualified dividends stack above
that on the long_term brackets. NIIT is its rate on the smaller of investment income and income past
the threshold. State is a flat rate on taxable income. Netting follows Schedule D: each term against
its own carry, then against each other. A net loss offsets ordinary income up to loss_limit,
short-term first, and the rest carries with its character. Gains and losses the book has already
realized in its report year count in that year for every plan, against the carry coming into the
year. A book from an earlier year opens with its loss_carryforward instead. Opening carry is long-term.

A lot's price and the accounts grow at growth from as_of, in days over 365. A sale on or after the
lot's long_term_date is long-term. Proceeds go into a reinvested pot at their full value, and each
year's activity_tax (total_tax less the tax on income and sales already made, which every plan pays) comes out of it
at year end. The pot can go below zero, which is flagged: the money would come from elsewhere.

At the end of the last year, after_tax_wealth is the lots and the pot, less exit_long_term on their
net unrealized gain (a net loss counts as a credit at that rate, as does any unused carry), plus the
Traditional balance less exit_ordinary on its pre-tax part, plus the Roth balance. Plans run highest
first. A test reruns every plan with its changes and says whether the leading plan changes.

Output: {"as_of", "filing", "years", "plans": [{"name", "why", "actions", "years": [{"year",
"taxable_ordinary", "ordinary_tax", "capital_gains_tax", "niit", "state_tax", "total_tax", "wage_tax",
"activity_tax", "balance_due", "short_term_net", "long_term_net", "loss_deducted", "carry_out",
"conversion_taxable"}], "end": {...}, "total_tax", "tax_vs_baseline", "wealth_vs_baseline", "short"}],
"leading", "tests", "deciding_assumptions", "rule_tables", "rules", "flags", "inputs"}. inputs holds
what plan_store.py needs for a rerun. Figures are estimates on stated assumptions, not a return.

Exit 2 with {"error"} on a rule with no source or date, a date after as_of, a missing rule or year,
an uncited action, a bracket table with no open top band or a rate out of range, a sale of more than
is held, or a conversion of more than the Traditional balance. With "allow_short": true
(plan_store.py check), a sale of what is no longer held sells what is left and is listed in short.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta

FILINGS = ("single", "mfj", "mfs", "hoh")
ASSUMPTIONS = ("growth", "exit_long_term", "exit_ordinary", "state_rate")
ACTION_RULES = {"sell": ("capital_gains", "loss_limit", "wash_sale"), "roth_convert": ("roth_conversion",)}
WASH_DAYS = 30


def _day(v: object, what: str) -> date:
    if not isinstance(v, str) or not v:
        raise ValueError(f"{what}: date is required")
    try:
        return date.fromisoformat(v[:10])
    except ValueError as exc:
        raise ValueError(f"{what}: date {v!r} is not YYYY-MM-DD") from exc


def _num(v: object, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{what} must be a finite number")
    return float(v)


def _cited(item: object, what: str, as_of: date) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"{what} must be an object")
    if not isinstance(item.get("source"), str) or not item["source"].strip():
        raise ValueError(f"{what} has no source")
    when = _day(item.get("date"), what)
    if when > as_of:
        raise ValueError(f"{what}: date {item['date']} is after as_of {as_of}")


def _brackets(rows: object, what: str) -> list[tuple[float | None, float]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{what} needs bands")
    out, last = [], -math.inf
    for i, row in enumerate(rows):
        top, rate = row
        if not 0 <= _num(rate, f"{what} rate") <= 1:
            raise ValueError(f"{what} rate must be from 0 to 1")
        if top is None:
            if i != len(rows) - 1:
                raise ValueError(f"{what}: only the last band can be open")
        else:
            top = _num(top, f"{what} band")
            if top <= last:
                raise ValueError(f"{what}: bands must rise")
            last = top
        out.append((top, float(rate)))
    if out[-1][0] is not None:
        raise ValueError(f"{what}: the last band must be open, with null as its top")
    return out


def _tax_on(brackets: list, start: float, amount: float) -> float:
    """Tax on ``amount`` of income sitting above ``start`` on these bands."""
    tax, low = 0.0, 0.0
    end = start + amount
    for top, rate in brackets:
        high = math.inf if top is None else top
        tax += max(0.0, min(end, high) - max(start, low)) * rate
        low = high
    return tax


def _year_tax(table: dict, ordinary: float, st: float, lt: float, qdiv: float, loss_used: float, state_rate: float) -> dict:
    gross = ordinary + max(st, 0.0) - loss_used
    leftover = max(0.0, table["standard_deduction"] - gross)
    taxable_ordinary = max(0.0, gross - table["standard_deduction"])
    preferred = max(0.0, max(lt, 0.0) + qdiv - leftover)
    ordinary_tax = _tax_on(_brackets(table["ordinary"], "ordinary"), 0.0, taxable_ordinary)
    gains_tax = _tax_on(_brackets(table["long_term"], "long_term"), taxable_ordinary, preferred)
    investment = max(st, 0.0) + max(lt, 0.0) + qdiv
    magi = gross + max(lt, 0.0) + qdiv
    niit = table["niit_rate"] * min(investment, max(0.0, magi - table["niit_threshold"]))
    state = state_rate * (taxable_ordinary + preferred)
    return {"taxable_ordinary": round(taxable_ordinary, 2), "ordinary_tax": round(ordinary_tax, 2), "capital_gains_tax": round(gains_tax, 2),
            "niit": round(niit, 2), "state_tax": round(state, 2), "total_tax": round(ordinary_tax + gains_tax + niit + state, 2)}


def _net(st: float, lt: float, carry: dict, limit: float) -> tuple[float, float, float, dict]:
    st -= carry["short"]
    lt -= carry["long"]
    if st < 0 < lt:
        lt, st = max(lt + st, 0.0), min(lt + st, 0.0)
    elif lt < 0 < st:
        st, lt = max(st + lt, 0.0), min(st + lt, 0.0)
    short_loss, long_loss = max(-st, 0.0), max(-lt, 0.0)
    used_short = min(short_loss, limit)
    used_long = min(long_loss, limit - used_short)
    return st, lt, used_short + used_long, {"short": round(short_loss - used_short, 2), "long": round(long_loss - used_long, 2)}


def _lots(book: dict) -> tuple[list[dict], list[str]]:
    lots, unpriced = [], []
    for lot in book.get("open_lots") or []:
        units = _num(lot.get("units"), f"lot {lot.get('symbol')} units")
        cost = _num(lot.get("cost"), f"lot {lot.get('symbol')} cost")
        price = lot.get("price")
        if price is None:
            unpriced.append(str(lot.get("symbol")))
            price = cost / units if units else 0.0
        lots.append({"symbol": str(lot.get("symbol")).upper(), "units": units, "unit_cost": cost / units if units else 0.0, "price": float(price),
                     "buy_date": _day(lot.get("buy_date"), f"lot {lot.get('symbol')}"),
                     "long_term_date": _day(lot.get("long_term_date"), f"lot {lot.get('symbol')}")})
    return sorted(lots, key=lambda x: x["buy_date"]), sorted(set(unpriced))


def _opening(book: dict, years: list[int]) -> tuple[dict, tuple[float, float]]:
    """The carry into the first year, and what the book already realized in it (short, long)."""
    summary = book.get("summary") or {}
    year = book.get("year")
    if year is None or year < years[0]:
        return {"short": 0.0, "long": float(summary.get("loss_carryforward") or 0.0)}, (0.0, 0.0)
    if year > years[0]:
        raise ValueError(f"the tax report is for {year}, later than the plans' first year {years[0]}")
    prior = [r for r in summary.get("carryforward_history") or [] if r.get("year", year) < year]
    carry_in = float(prior[-1].get("carryforward") or 0.0) if prior else 0.0
    return {"short": 0.0, "long": carry_in}, (float(summary.get("short_term_net") or 0.0), float(summary.get("long_term_net") or 0.0))


def _grow(value: float, growth: float, days: int) -> float:
    return value * (1 + growth) ** (days / 365)


def _sell(action: dict, lots: list[dict], when: date, as_of: date, growth: float, lenient: bool, plan: str) -> tuple[float, float, float, bool, bool]:
    """Sell from the lots. Returns proceeds, short-term gain, long-term gain, whether it ran short, and wash-sale risk."""
    symbol = str(action.get("symbol") or "").upper()
    held = [x for x in lots if x["symbol"] == symbol and x["units"] > 0]
    units = _num(action.get("units"), f"plan {plan}: sale units")
    if units <= 0:
        raise ValueError(f"plan {plan}: sale units must be positive")
    if not held and not lenient:
        raise ValueError(f"plan {plan}: {symbol} is not held")
    have = sum(x["units"] for x in held)
    if units > have + 1e-9 and not lenient:
        raise ValueError(f"plan {plan}: selling {units:g} {symbol} is more than the {have:g} held")
    short = units > have + 1e-9
    if action.get("order", "fifo") == "highest_cost":
        held = sorted(held, key=lambda x: -x["unit_cost"])
    elif action.get("order", "fifo") != "fifo":
        raise ValueError(f"plan {plan}: order must be fifo or highest_cost")
    proceeds = st = lt = 0.0
    left = units
    loss_sold = False
    for lot in held:
        take = min(left, lot["units"])
        if take <= 0:
            break
        value = take * _grow(lot["price"], growth, (when - as_of).days)
        gain = value - take * lot["unit_cost"]
        proceeds += value
        if when >= lot["long_term_date"]:
            lt += gain
        else:
            st += gain
        loss_sold = loss_sold or gain < 0
        lot["units"] -= take
        left -= take
    window = timedelta(days=WASH_DAYS)
    wash = loss_sold and any(x["symbol"] == symbol and x["units"] > 1e-9 and when - window <= x["buy_date"] <= when + window for x in lots)
    return proceeds, st, lt, short, wash


def _run_plan(plan: dict, ctx: dict, assume: dict) -> dict:
    as_of, years = ctx["as_of"], ctx["years"]
    growth, lenient = assume["growth"], ctx["lenient"]
    lots = [dict(x) for x in ctx["lots"]]
    accounts = ctx["accounts"]
    trad, basis, roth = accounts["traditional"], accounts["traditional_basis"], accounts["roth"]
    clock = as_of
    pot_flows: list[tuple[date, float]] = []
    carry = dict(ctx["opening_carry"])
    rows, short, wash = [], [], []
    for year in years:
        table, income = ctx["tables"][str(year)], ctx["income"][str(year)]
        year_end = max(date(year, 12, 31), as_of)
        st = lt = conv_taxable = 0.0
        for a in sorted((a for a in plan["actions"] if a["year"] == year), key=lambda a: a.get("date") or f"{year}-12-31"):
            when = max(_day(a["date"], "action") if a.get("date") else year_end, as_of)
            if a["type"] == "sell":
                proceeds, s, l, ran_short, risk = _sell(a, lots, when, as_of, growth, lenient, plan["name"])
                st += s
                lt += l
                pot_flows.append((when, proceeds))
                if ran_short:
                    short.append(str(a["symbol"]).upper())
                if risk:
                    wash.append(str(a["symbol"]).upper())
            else:
                days = (when - clock).days
                trad, roth = _grow(trad, growth, days), _grow(roth, growth, days)
                clock = when
                amount = _num(a.get("amount"), f"plan {plan['name']}: conversion amount")
                if amount <= 0:
                    raise ValueError(f"plan {plan['name']}: conversion amount must be positive")
                if amount > trad + 1e-9:
                    if not lenient:
                        raise ValueError(f"plan {plan['name']}: converting {amount:g} is more than the Traditional balance of {trad:.2f}")
                    amount = trad
                free = amount * (basis / trad) if trad > 0 else 0.0
                conv_taxable += amount - free
                basis -= free
                trad -= amount
                roth += amount
        done_st, done_lt = ctx["realized"] if year == years[0] else (0.0, 0.0)
        done = _net(done_st, done_lt, carry if year == years[0] else {"short": 0.0, "long": 0.0}, table["loss_limit"])
        st_net, lt_net, used, carry_out = _net(st + done_st, lt + done_lt, carry, table["loss_limit"])
        carry = carry_out
        ordinary, qdiv = income["ordinary"], income.get("qualified_dividends", 0.0)
        tax = _year_tax(table, ordinary + conv_taxable, st_net, lt_net, qdiv, used, assume["state_rate"])
        wage = _year_tax(table, ordinary, done[0], done[1], qdiv, done[2], assume["state_rate"])["total_tax"]
        activity = round(tax["total_tax"] - wage, 2)
        pot_flows.append((year_end, -activity))
        withheld = income.get("withheld")
        rows.append({"year": year, **tax, "wage_tax": wage, "activity_tax": activity, "balance_due": round(tax["total_tax"] - withheld, 2) if withheld is not None else None,
                     "short_term_net": round(st_net, 2), "long_term_net": round(lt_net, 2), "loss_deducted": round(used, 2), "carry_out": carry_out, "conversion_taxable": round(conv_taxable, 2)})
    end = max(date(years[-1], 12, 31), as_of)
    days = (end - clock).days
    trad, roth = _grow(trad, growth, days), _grow(roth, growth, days)
    span = (end - as_of).days
    lot_value = sum(x["units"] * _grow(x["price"], growth, span) for x in lots)
    lot_cost = sum(x["units"] * x["unit_cost"] for x in lots)
    pot = sum(_grow(v, growth, (end - d).days) for d, v in pot_flows)
    pot_basis = sum(v for _, v in pot_flows)
    unrealized = lot_value - lot_cost + pot - pot_basis
    taxable = lot_value + pot
    unused = carry["short"] + carry["long"]
    wealth = taxable - unrealized * assume["exit_long_term"] + unused * assume["exit_long_term"] + trad - (trad - min(basis, trad)) * assume["exit_ordinary"] + roth
    return {"name": plan["name"], "why": plan["why"], "actions": plan["actions"], "years": rows, "total_tax": round(sum(r["total_tax"] for r in rows), 2),
            "end": {"end_date": str(end), "taxable_value": round(taxable, 2), "pot": round(pot, 2), "unrealized_gain": round(unrealized, 2), "traditional": round(trad, 2),
                    "traditional_basis": round(basis, 2), "roth": round(roth, 2), "unused_carry": round(unused, 2), "after_tax_wealth": round(wealth, 2)},
            "short": sorted(set(short)), "_wash": sorted(set(wash))}


def _validate_rule_tables(params: dict, years: list[int], as_of: date) -> dict:
    tables = params.get("rule_tables")
    if not isinstance(tables, dict):
        raise ValueError("rule_tables must be an object")
    for year in years:
        table = tables.get(str(year))
        if not isinstance(table, dict):
            raise ValueError(f"rule_tables has no row for {year}")
        _cited(table, f"rule table {year}", as_of)
        if table.get("status") not in ("enacted", "projected"):
            raise ValueError(f"rule table {year}: status must be enacted or projected")
        _brackets(table.get("ordinary"), f"rule table {year} ordinary")
        _brackets(table.get("long_term"), f"rule table {year} long_term")
        for field in ("standard_deduction", "niit_threshold", "niit_rate", "loss_limit"):
            _num(table.get(field), f"rule table {year} {field}")
    return tables


def _validate_plans(raw: object, years: list[int], cited: set[str]) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("plans must be a non-empty list")
    names = set()
    for plan in raw:
        if not isinstance(plan, dict) or not plan.get("name") or not plan.get("why"):
            raise ValueError("every plan needs a name and a why")
        if plan["name"] in names:
            raise ValueError(f"plan {plan['name']} appears twice")
        names.add(plan["name"])
        for a in plan.get("actions") or []:
            kind = a.get("type") if isinstance(a, dict) else None
            if kind not in ACTION_RULES:
                raise ValueError(f"plan {plan['name']}: action type must be sell or roth_convert")
            if a.get("year") not in years:
                raise ValueError(f"plan {plan['name']}: year {a.get('year')} is not in years")
            if a.get("date") and _day(a["date"], "action").year != a["year"]:
                raise ValueError(f"plan {plan['name']}: an action's date must fall in its year")
            for rule in ACTION_RULES[kind]:
                if rule not in cited:
                    raise ValueError(f"plan {plan['name']}: a {kind} action needs the {rule} rule cited")
    if raw[0].get("actions"):
        raise ValueError("the first plan is the baseline, so it must have no actions")
    return [{**p, "actions": p.get("actions") or []} for p in raw]


def _flags(params: dict, plans: list[dict], years: list[int], unpriced: list[str], flips: list[str]) -> list[dict]:
    flags = []
    projected = [str(y) for y in years if params["rule_tables"][str(y)]["status"] == "projected"]
    if projected:
        flags.append({"code": "PROJECTED_RULES", "message": f"The tables for {', '.join(projected)} are projections, not enacted law. They can change."})
    secondary = [r["rule"] for r in params["rules"] if not r.get("primary")] + [f"{y} table" for y in years if not params["rule_tables"][str(y)].get("primary")]
    if secondary:
        flags.append({"code": "SECONDARY_SOURCE", "message": f"Not checked against a primary source: {', '.join(secondary)}."})
    for p in plans:
        if p["_wash"]:
            flags.append({"code": "WASH_SALE_RISK", "message": f"{p['name']}: selling {', '.join(p['_wash'])} at a loss sits within {WASH_DAYS} days of other shares bought, so the loss may be disallowed. Purchases in any account or by dividend reinvestment count."})
    due = [p["name"] for p in plans[1:] if any((y["balance_due"] or 0) > 0 for y in p["years"])]
    if due:
        flags.append({"code": "BALANCE_DUE", "message": f"{', '.join(due)}: tax for a year runs above what is withheld, which can mean a payment at filing or an estimated-tax penalty."})
    below = [p["name"] for p in plans if p["end"]["pot"] < 0]
    if below:
        flags.append({"code": "PAID_FROM_ELSEWHERE", "message": f"{', '.join(below)}: the tax runs above the proceeds of the sales, so the money would come from elsewhere."})
    if unpriced:
        flags.append({"code": "MISSING_PRICES", "message": f"No price for {', '.join(unpriced)}, so each is valued at cost."})
    if flips:
        flags.append({"code": "RANKING_FLIPS", "message": f"The leading plan changes under: {', '.join(flips)}."})
    flags.append({"code": "NOT_MODELLED", "message": "AMT, state rules beyond a flat rate, Medicare premiums, ACA credits, required distributions, early-withdrawal penalties, the qualified-dividend holding test and award vesting beyond the income given are not modelled."})
    return flags


def run_plans(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    as_of = _day(params.get("as_of"), "as_of")
    if params.get("filing") not in FILINGS:
        raise ValueError(f"filing must be one of {', '.join(FILINGS)}")
    years = params.get("years")
    if not isinstance(years, list) or not years or not all(isinstance(y, int) for y in years) or years != sorted(set(years)):
        raise ValueError("years must be a rising list of whole years")
    book = params.get("book")
    if not isinstance(book, dict) or "open_lots" not in book:
        raise ValueError("book (a tax-report.py result) is required")
    tables = _validate_rule_tables(params, years, as_of)
    rules = params.get("rules") or []
    for r in rules:
        if not isinstance(r, dict) or not r.get("rule") or not r.get("says"):
            raise ValueError("every rule needs its rule and what it says")
        _cited(r, f"rule {r['rule']}", as_of)
    cited = {r["rule"] for r in rules}
    income = params.get("income")
    if not isinstance(income, dict):
        raise ValueError("income must be an object")
    clean_income = {}
    for year in years:
        row = income.get(str(year))
        if not isinstance(row, dict):
            raise ValueError(f"income has no row for {year}")
        clean_income[str(year)] = {"ordinary": _num(row.get("ordinary"), f"income {year} ordinary")}
        for field in ("qualified_dividends", "withheld"):
            if row.get(field) is not None:
                clean_income[str(year)][field] = _num(row[field], f"income {year} {field}")
    raw_accounts = params.get("accounts") or {}
    accounts = {k: _num(raw_accounts.get(k, 0.0), f"accounts {k}") for k in ("traditional", "traditional_basis", "roth")}
    assumptions = params.get("assumptions") or {}
    assume = {k: _num(assumptions.get(k), f"assumptions {k}") for k in ASSUMPTIONS}
    plans = _validate_plans(params.get("plans"), years, cited)
    tests = params.get("tests") or []
    for t in tests:
        if not isinstance(t, dict) or not t.get("name") or not t.get("why"):
            raise ValueError("every test needs a name and a why")
        for field in t.get("changes") or {}:
            if field not in ASSUMPTIONS:
                raise ValueError(f"test {t['name']}: {field} is not an assumption")

    lots, unpriced = _lots(book)
    opening, realized = _opening(book, years)
    ctx = {"as_of": as_of, "years": years, "lots": lots, "accounts": accounts, "opening_carry": opening, "realized": realized, "tables": tables, "income": clean_income, "lenient": params.get("allow_short") is True}
    results = [_run_plan(p, ctx, assume) for p in plans]
    base = results[0]
    for r in results:
        r["tax_vs_baseline"] = round(r["total_tax"] - base["total_tax"], 2)
        r["wealth_vs_baseline"] = round(r["end"]["after_tax_wealth"] - base["end"]["after_tax_wealth"], 2)
    ranked = sorted(results, key=lambda r: -r["end"]["after_tax_wealth"])  # stable: the baseline keeps a tie
    leading = ranked[0]["name"]
    test_rows, flips = [], []
    for t in tests:
        trial = {**assume, **{k: _num(v, f"test {t['name']} {k}") for k, v in (t.get("changes") or {}).items()}}
        runs = [_run_plan(p, ctx, trial) for p in plans]
        wealth = {r["name"]: r["end"]["after_tax_wealth"] for r in runs}
        top = max(runs, key=lambda r: r["end"]["after_tax_wealth"])["name"]
        test_rows.append({"name": t["name"], "why": t["why"], "changes": t.get("changes") or {}, "leading": top, "flips": top != leading, "wealth": wealth})
        if top != leading:
            flips.append(t["name"])
    flags = _flags({**params, "rules": rules, "rule_tables": tables}, results, years, unpriced, flips)
    for r in ranked:
        del r["_wash"]
    return {"as_of": str(as_of), "filing": params["filing"], "years": years, "plans": ranked, "leading": leading, "tests": test_rows, "deciding_assumptions": flips,
            "rule_tables": {str(y): tables[str(y)] for y in years}, "rules": rules, "flags": flags,
            "inputs": {"filing": params["filing"], "years": years, "rule_tables": tables, "rules": rules, "income": income, "accounts": accounts, "assumptions": assume, "plans": plans, "tests": tests}}


def main() -> None:
    try:
        result = run_plans(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
