#!/usr/bin/env python3
"""The math of the real-estate deep review (stdin -> stdout JSON).

    python property_case.py < case.json

Input: {"as_of", "subject": {"kind": "property"|"market", "name", "use": "own"|"rental", "sqft"
(optional)}, "inputs": {FIELD: {"value", "basis", "source", "date"}}, "scenarios": [{"name", "why",
"one_time": "low"|"mid"|"high" (default mid), "changes": {FIELD: {"value", "basis", "source",
"date"}}}], "costs": [{"item", "low", "high", "source", "date"}], "comps": {"sales": [{"address",
"price", "sqft" (optional), "date", "source"}], "rents": [{"address", "rent", "sqft" (optional),
"date", "source"}]}, "documents": [{"kind", "status": "read"|"not_provided", "source"}],
"findings": [{"claim", "side": "for"|"against", "source", "date"}], "open_questions": [{"question",
"who"}], "watch": [{"what", "breaks_if", "check_by"}]}.

FIELD is a realestate.py input of the action the use picks: rent_vs_buy and mortgage for own, rental
for rental. basis is document, stated, local, regional or assumption. The first scenario is the
central one, and at least two are needed.

Each scenario runs the calculators on the inputs plus its changes, with one-time costs at its level
(mid is halfway between low and high). They join closing_costs for a rental and buy_closing_rate
(as cost / price) for a home. Its result is total_profit for a rental and advantage_buy at the
horizon for a home. drivers reruns the central scenario with one change at a time from the other
scenarios, largest swing in the result first. A driver is soft when the input or the change rests on
a regional figure or an assumption, or on evidence over 365 days old. soft_spot is the largest soft
driver. even_price is the price, with the down payment fixed, at which the central scenario comes
out even: buying equals renting at the horizon, or first-year cash flow is zero. A rental's property
tax stays as given there.

comps gives medians from sales in the last 365 days and rents in the last 180, and the gap between
the subject and what those medians imply.

Output: {"as_of", "subject", "inputs", "result_label", "scenarios": [{"name", "why", "one_time",
"one_time_cost", "changes", "result", ...the use's figures}], "drivers", "soft_spot", "even_price",
"costs", "comps", "documents", "findings", "open_questions", "watch", "flags"}.

Exit 2 with {"error"} on an input or claim with no source or date, a date after as_of, an unknown
field, basis, level or side, a missing required input, costs with low above high, or fewer than two
scenarios. Figures from realestate.py carry its limits: fixed-rate loans and no income-tax effects.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))

import realestate  # noqa: E402

BASES = ("document", "stated", "local", "regional", "assumption")
AGING_BASES = ("document", "local", "regional")
SOFT_BASES = ("regional", "assumption")
STALE_DAYS = 365
SALES_DAYS, RENT_DAYS = 365, 180
MIN_COMPS = 3
LEVELS = ("low", "mid", "high")
REQUIRED = {
    "own": ("price", "down_payment", "rate", "years", "horizon_years", "property_tax_rate", "insurance_annual", "maintenance_rate",
            "buy_closing_rate", "sell_closing_rate", "appreciation", "rent", "rent_growth", "investment_return"),
    "rental": ("price", "down_payment", "rate", "years", "rent", "vacancy_rate", "property_tax_annual", "insurance_annual", "maintenance_rate",
               "hold_years", "rent_growth", "expense_growth", "appreciation", "sell_closing_rate"),
}
OPTIONAL = {
    "own": ("hoa_monthly", "pmi_rate"),
    "rental": ("closing_costs", "management_rate", "hoa_monthly", "utilities_annual", "other_annual", "capex_reserve_rate", "leasing_rate", "tax_growth"),
}


def _day(v: object, what: str) -> date:
    if not isinstance(v, str) or not v:
        raise ValueError(f"{what}: date is required")
    try:
        return date.fromisoformat(v[:10])
    except ValueError as exc:
        raise ValueError(f"{what}: date {v!r} is not YYYY-MM-DD") from exc


def _sourced(item: object, what: str, as_of: date) -> date:
    if not isinstance(item, dict):
        raise ValueError(f"{what} must be an object")
    if not isinstance(item.get("source"), str) or not item["source"].strip():
        raise ValueError(f"{what} has no source")
    when = _day(item.get("date"), what)
    if when > as_of:
        raise ValueError(f"{what}: date {item['date']} is after as_of {as_of}")
    return when


def _number(v: object, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{what} must be a finite number")
    return float(v)


def _list(v: object, what: str) -> list:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        raise ValueError(f"{what} must be a list of objects")
    return v


def _input(field: str, item: object, use: str, as_of: date, what: str) -> None:
    if field not in REQUIRED[use] + OPTIONAL[use]:
        raise ValueError(f"{what}: {field} is not an input of a {use} review")
    _sourced(item, f"{what} {field}", as_of)
    _number(item.get("value"), f"{what} {field} value")
    if item.get("basis") not in BASES:
        raise ValueError(f"{what} {field}: basis must be one of {', '.join(BASES)}")


def _costs(rows: object, as_of: date) -> list[dict]:
    out = []
    for c in _list(rows, "costs"):
        if not c.get("item"):
            raise ValueError("every cost needs an item")
        _sourced(c, f"cost {c['item']}", as_of)
        low, high = _number(c.get("low"), f"cost {c['item']} low"), _number(c.get("high"), f"cost {c['item']} high")
        if low < 0 or low > high:
            raise ValueError(f"cost {c['item']}: low must be from 0 up to high")
        out.append(c)
    return out


def _level_cost(costs: list[dict], level: str) -> float:
    low, high = sum(c["low"] for c in costs), sum(c["high"] for c in costs)
    return {"low": low, "mid": (low + high) / 2, "high": high}[level]


def _calculate(use: str, values: dict, cost: float) -> dict:
    """One run of the calculators. Returns the use's figures with result."""
    if use == "rental":
        r = realestate.run_realestate({"action": "rental", **values, "closing_costs": values.get("closing_costs", 0.0) + cost})
        p = r["projection"]
        return {"result": p["total_profit"], "irr": p["irr"], "equity_multiple": p["equity_multiple"], "sale_price": p["sale_price"],
                **{k: r[k] for k in ("noi", "cap_rate", "dscr", "cash_flow", "cash_on_cash", "cash_invested")}}
    params = {**values, "buy_closing_rate": values["buy_closing_rate"] + cost / values["price"]}
    r = realestate.run_realestate({"action": "rent_vs_buy", **params})
    last = r["by_year"][-1]
    return {"result": last["advantage_buy"], "breakeven_year": r["breakeven_year"], "buy_net_worth": last["buy_net_worth"], "rent_net_worth": last["rent_net_worth"],
            "monthly_buy": r["monthly_cost_year1"]["buy"], "monthly_rent": r["monthly_cost_year1"]["rent"],
            "piti": realestate.run_realestate({"action": "mortgage", **params})["piti"]}


def _is_soft(item: dict, as_of: date) -> bool:
    return item.get("basis") in SOFT_BASES or (item.get("basis") in AGING_BASES and (as_of - _day(item["date"], "input")).days > STALE_DAYS)


def _drivers(use: str, inputs: dict, values: dict, scenarios: list[dict], costs: list[dict], as_of: date) -> list[dict]:
    central = scenarios[0]
    base_cost = central["one_time_cost"]
    rows, seen = [], set()
    for s in scenarios[1:]:
        for field, change in s["changes"].items():
            if (field, change["value"]) in seen or change["value"] == values.get(field):
                continue
            seen.add((field, change["value"]))
            result = _calculate(use, {**values, field: change["value"]}, base_cost)["result"]
            held = inputs.get(field)
            rows.append({"field": field, "central_value": held["value"] if held else None, "tested_value": change["value"], "scenario": s["name"],
                         "swing": round(result - central["result"], 2), "basis": held["basis"] if held else None,
                         "source": held["source"] if held else None, "date": held["date"] if held else None,
                         "tested_basis": change["basis"], "tested_source": change["source"], "tested_date": change["date"],
                         "soft": _is_soft(change, as_of) or (bool(held) and _is_soft(held, as_of))})
        if costs and s["one_time_cost"] != base_cost and ("one_time_costs", s["one_time_cost"]) not in seen:
            seen.add(("one_time_costs", s["one_time_cost"]))
            result = _calculate(use, values, s["one_time_cost"])["result"]
            rows.append({"field": "one_time_costs", "central_value": base_cost, "tested_value": s["one_time_cost"], "scenario": s["name"],
                         "swing": round(result - central["result"], 2), "basis": "document", "source": "; ".join(dict.fromkeys(c["source"] for c in costs)),
                         "date": max(c["date"] for c in costs), "tested_basis": "document", "tested_source": None, "tested_date": None,
                         "soft": any((as_of - _day(c["date"], "cost")).days > STALE_DAYS for c in costs)})
    return sorted(rows, key=lambda d: -abs(d["swing"]))


def _even_price(use: str, values: dict, cost: float) -> dict | None:
    price = values["price"]
    measure = "first-year cash flow" if use == "rental" else "buying against renting at the horizon"

    def gap(p: float) -> float:
        figures = _calculate(use, {**values, "price": p}, cost)
        return figures["cash_flow"] if use == "rental" else figures["result"]

    low, high = max(values["down_payment"] * 1.01, price * 0.25), price * 2
    if low >= high or gap(low) < 0 or gap(high) > 0:
        return None
    for _ in range(40):
        mid = (low + high) / 2
        if gap(mid) > 0:
            low = mid
        else:
            high = mid
    even = (low + high) / 2
    return {"price": round(even, 2), "vs_price": round(even / price - 1, 4), "measure": measure}


def _comp_stats(rows: list[dict], key: str, days: int, subject_value: float, sqft: float | None, as_of: date, what: str) -> dict:
    recent = []
    for c in rows:
        when = _sourced(c, f"{what} comp {c.get('address', '?')}", as_of)
        amount = _number(c.get(key), f"{what} comp {c.get('address', '?')} {key}")
        if amount <= 0:
            raise ValueError(f"{what} comp {c.get('address', '?')} {key} must be positive")
        if (as_of - when).days <= days:
            recent.append(c)
    amounts = [c[key] for c in recent]
    per_sqft = [c[key] / c["sqft"] for c in recent if isinstance(c.get("sqft"), (int, float)) and c["sqft"] > 0]
    mid = median(amounts) if amounts else None
    rate = round(median(per_sqft), 4) if per_sqft else None
    implied = round(rate * sqft, 2) if rate and sqft else (float(mid) if mid is not None else None)
    label = "median_price" if key == "price" else "median_rent"
    return {"count": len(rows), "recent": len(recent), "window_days": days, label: mid, "low": min(amounts) if amounts else None, "high": max(amounts) if amounts else None,
            "median_per_sqft": rate, f"implied_{'value' if key == 'price' else 'rent'}": implied,
            "gap": round(subject_value / implied - 1, 4) if implied else None, "rows": rows}


def _comps(comps: object, values: dict, sqft: float | None, as_of: date) -> dict | None:
    if comps is None:
        return None
    if not isinstance(comps, dict):
        raise ValueError("comps must be an object")
    return {"sales": _comp_stats(_list(comps.get("sales"), "comps sales"), "price", SALES_DAYS, values["price"], sqft, as_of, "sale"),
            "rents": _comp_stats(_list(comps.get("rents"), "comps rents"), "rent", RENT_DAYS, values["rent"], sqft, as_of, "rent")}


def _flags(subject: dict, inputs: dict, scenarios: list[dict], comps: dict | None, documents: list[dict], findings: list[dict], questions: list[dict], as_of: date) -> list[dict]:
    flags = []

    def add(code: str, message: str) -> None:
        flags.append({"code": code, "message": message})

    if subject["kind"] == "property":
        gaps = [d["kind"] for d in documents if d["status"] == "not_provided"]
        if not documents:
            add("DOCUMENT_GAPS", "No documents were read, so everything here comes from public sources and what was stated.")
        elif gaps:
            add("DOCUMENT_GAPS", f"Not provided: {', '.join(gaps)}. Costs and rules that sit in them are missing from the result.")
        thin = [k for k in ("sales", "rents") if comps is None or comps[k]["recent"] < MIN_COMPS]
        if thin:
            add("THIN_COMPS", f"Fewer than {MIN_COMPS} recent comparable {' and '.join(thin)} were found, so the gap to them is weak evidence.")
    assumed = [k for k, v in inputs.items() if v["basis"] == "assumption"]
    if assumed:
        add("ASSUMED_INPUTS", f"These inputs are assumptions, not findings: {', '.join(assumed)}.")
    stale = [k for k, v in inputs.items() if v["basis"] in AGING_BASES and (as_of - _day(v["date"], k)).days > STALE_DAYS]
    if stale:
        add("STALE_INPUTS", f"The evidence for these inputs is over {STALE_DAYS} days old: {', '.join(stale)}.")
    if not any(s["result"] < scenarios[0]["result"] for s in scenarios[1:]):
        add("NO_DOWNSIDE", "No scenario comes out worse than the central one, so a downside case may be missing.")
    if not any(f["side"] == "against" for f in findings):
        add("NO_OPPOSING_EVIDENCE", "No evidence against the central case was found, so the view is one-sided.")
    if questions:
        add("OPEN_QUESTIONS", f"{len(questions)} open {'question' if len(questions) == 1 else 'questions'} could change the result and need someone other than this review to answer.")
    add("NOT_MODELLED", "Income-tax effects, adjustable-rate and interest-only loans, and local reassessment or rent rules beyond the inputs given are not modelled.")
    return flags


def run_case(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    as_of = _day(params.get("as_of"), "as_of")
    subject = params.get("subject")
    if not isinstance(subject, dict) or not subject.get("name"):
        raise ValueError("subject needs a name")
    if subject.get("kind") not in ("property", "market"):
        raise ValueError("subject kind must be property or market")
    use = subject.get("use")
    if use not in REQUIRED:
        raise ValueError("subject use must be own or rental")
    sqft = _number(subject["sqft"], "subject sqft") if subject.get("sqft") is not None else None
    inputs = params.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object")
    for field, item in inputs.items():
        _input(field, item, use, as_of, "input")
    missing = [f for f in REQUIRED[use] if f not in inputs]
    if missing:
        raise ValueError(f"a {use} review needs these inputs: {', '.join(missing)}")
    values = {k: float(v["value"]) for k, v in inputs.items()}
    if values["price"] <= 0:
        raise ValueError("price must be positive")
    costs = _costs(params.get("costs"), as_of)

    raw = _list(params.get("scenarios"), "scenarios")
    if len(raw) < 2:
        raise ValueError("at least two scenarios are needed, and the first is the central one")
    scenarios, names = [], set()
    for s in raw:
        name = s.get("name")
        if not name or not s.get("why"):
            raise ValueError("every scenario needs a name and a why")
        if name in names:
            raise ValueError(f"scenario {name} appears twice")
        names.add(name)
        level = s.get("one_time", "mid")
        if level not in LEVELS:
            raise ValueError(f"scenario {name}: one_time must be one of {', '.join(LEVELS)}")
        changes = s.get("changes") or {}
        if not isinstance(changes, dict):
            raise ValueError(f"scenario {name}: changes must be an object")
        for field, item in changes.items():
            _input(field, item, use, as_of, f"scenario {name}")
        cost = _level_cost(costs, level)
        run = _calculate(use, {**values, **{k: float(v["value"]) for k, v in changes.items()}}, cost)
        scenarios.append({"name": name, "why": s["why"], "one_time": level, "one_time_cost": round(cost, 2), "changes": changes, **run})

    documents = _list(params.get("documents"), "documents")
    for d in documents:
        if d.get("status") not in ("read", "not_provided"):
            raise ValueError(f"document {d.get('kind', '?')}: status must be read or not_provided")
        if not d.get("kind"):
            raise ValueError("every document needs a kind")
    findings = _list(params.get("findings"), "findings")
    for f in findings:
        if not f.get("claim"):
            raise ValueError("every finding needs a claim")
        if f.get("side") not in ("for", "against"):
            raise ValueError(f"finding {f['claim']!r}: side must be for or against")
        _sourced(f, f"finding {f['claim']!r}", as_of)
    questions = _list(params.get("open_questions"), "open_questions")
    for q in questions:
        if not q.get("question"):
            raise ValueError("every open question needs its question")
    watch = _list(params.get("watch"), "watch")
    for w in watch:
        for field in ("what", "breaks_if"):
            if not w.get(field):
                raise ValueError(f"a watch item has no {field}")
        _day(w.get("check_by"), "watch check_by")

    comps = _comps(params.get("comps"), values, sqft, as_of)
    drivers = _drivers(use, inputs, values, scenarios, costs, as_of)
    return {"as_of": str(as_of), "subject": subject, "inputs": inputs, "result_label": "total_profit" if use == "rental" else "advantage_buy",
            "scenarios": scenarios, "drivers": drivers, "soft_spot": next((d for d in drivers if d["soft"]), None),
            "even_price": _even_price(use, values, scenarios[0]["one_time_cost"]), "costs": costs, "comps": comps, "documents": documents,
            "findings": findings, "open_questions": questions, "watch": watch,
            "flags": _flags(subject, inputs, scenarios, comps, documents, findings, questions, as_of)}


def main() -> None:
    try:
        result = run_case(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, AttributeError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
