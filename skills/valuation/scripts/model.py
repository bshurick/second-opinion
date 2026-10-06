#!/usr/bin/env python3
"""Driver-based valuation, segment by segment, under named scenarios (stdin -> stdout JSON).

    python model.py < model.json

Exit 0 with the result on stdout, or exit 2 with ``{"error": "..."}`` on invalid input. Pure
arithmetic: nothing is fetched. Units are the caller's own (e.g. millions, shares in millions).

Input::

    {"symbol": "ACME", "price": 50.0,          # price optional; enables "upside"
     "shares_outstanding": 100.0, "years": 10, "horizon": 5,   # years >= horizon + 1, years <= 30
     "base_discount_rate": 0.09, "tax_rate": 0.21, "cost_of_debt": 0.06,
     "claims": {"debt", "cash", "leases", "minority_interest", "pension_deficit", "preferred", "options"},
     "payout": 0.6,                 # share of positive FCFE paid out (dividends + buybacks), 0..1;
                                    # default 1. Retained cash earns only cost_of_debt on the path.
     "annual_dilution": 0.0,        # yearly share-count change on the path (+ dilution, - shrink)
     "hurdle": 0.10,                # echoed into returns_input
     "history": {"Core": {"max_margin": 0.18}},     # optional; feeds MARGIN_ABOVE_HISTORY
     "segments": [<segment>, ...],
     "scenarios": [<scenario>, ...],                # optional; default one scenario "Base"
     "sensitivity": {"scenario": "Base",
                     "a": {"segment": "Core", "field": "margin_shift", "values": [...]},
                     "b": {"segment": "Core", "field": "discount_premium", "values": [...]}}}

Segment kinds (growth, margin, sales_to_capital, roe, retention: a scalar or a list of ``years``):

- ``operating``: revenue0, growth, margin (EBIT), sales_to_capital, tax_rate?, discount_rate?,
  discount_premium?, premium_reason?, da_pct_revenue?, terminal {"method": "gordon", "growth"} or
  {"method": "multiple", "metric": "ebit"|"ebitda"|"revenue", "multiple"}, fails?
  {"year", "salvage"}. FCFF_t = EBIT_t(1 - tax) - (Rev_t - Rev_t-1) / sales_to_capital_t. The Gordon
  terminal value is FCFF_N+1 / (r - g), with year N+1 built the same way at growth g.
- ``cost``: cost0 (after tax, positive), growth?, terminal_growth? (0.02), discount_premium?. A
  negative cash flow with a Gordon tail.
- ``asset``: value. ``venture``: value_if_success, probability, cost_pv -> probability * value - cost.
- ``residual_income``: book0, roe, retention, cost_of_equity, discount_premium?, terminal_growth?
  (0.02). Equity value = book0 + PV of (ROE_t - ke) * book_t-1 + Gordon tail; added to equity, not
  enterprise value. Its yearly flows (earnings * (1 - retention)) are already dividends.

The discount rate is ``discount_rate`` when given, else ``base_discount_rate`` (``cost_of_equity``
for residual income), plus ``discount_premium``. ``value_ex_premiums`` reruns with every premium at 0.

Scenario: {"name", "summary", "must_be_true": [...], "overrides": {"<segment>": {field: value}},
"payout"?, "annual_dilution"?, "claims"?, "exit_multiple"? {"metric": "ebit"|"ebitda"|"revenue"|
"fcfe", "multiple"}}. Overrides replace the named fields only; "fails": null removes a failure.

Path to the horizon, per scenario, t = 1..horizon: FCFE_t = sum FCFF_t + residual-income dividends
- cost_of_debt * (1 - tax) * net_debt_t-1; distributions_t = payout * max(FCFE_t, 0); net_debt_t =
net_debt_t-1 - (FCFE_t - distributions_t); shares_t = shares_t-1 * (1 + annual_dilution). Net debt
starts at debt - cash + leases; the other claims stay fixed. Exit ``dcf_roll`` is every segment's
value at year H (its flows after H and its tail, at its own rate) less net debt_H and the other
claims, per share_H. Exit ``multiple`` applies ``exit_multiple`` to year-H company totals (EBIT
nets out cost segments grossed up for tax; EBITDA adds da_pct_revenue * revenue).

Output: {"symbol", "price", "horizon", "scenarios": [{"name", "summary", "must_be_true",
"enterprise_value", "equity_value", "value_per_share", "value_ex_premiums", "upside",
"segments": [{"name", "kind", "value", "pv_terminal", "terminal_share", "discount_rate", "premium",
"premium_reason", "years": [...]}], "bridge", "path": [{"t", "fcfe", "distributions_per_share",
"net_debt", "shares"}], "exit": {"dcf_roll", "multiple"}}], "sensitivity", "returns_input",
"flags": [{"code", "message"}]}. Sensitivity fields: growth_shift, margin_shift (added to every
year), roe_shift (residual income, added to every year), discount_premium, terminal_growth,
terminal_multiple, sales_to_capital (set), and discount_shift with segment "*" (added to every
segment's discount rate); a cell whose inputs are invalid is null. ``implied`` is what the price
implies: the one shift to every operating margin (field margin_shift), or to every residual-income
ROE when there is no operating segment (roe_shift), that makes the first scenario worth the price;
null when no shift within +/-50 points does. A scenario may also override ``cost_of_debt``. The
sensitivity block also carries ``base`` (each axis's value as modeled, 0 for a shift) and
``discount_rate`` (each axis segment's rate before any premium; for "*", the rate all segments share,
else null).
Flags: TERMINAL_HEAVY (a segment > 75% terminal), NEGATIVE_EQUITY,
MARGIN_ABOVE_HISTORY, REINVESTMENT_NEGATIVE; each segment flag is raised once, naming the scenarios
it fires in.
"""

from __future__ import annotations

import copy
import json
import math
import sys

KINDS = ("operating", "cost", "asset", "venture", "residual_income")
CLAIMS = ("debt", "cash", "leases", "minority_interest", "pension_deficit", "preferred", "options")
OTHER_CLAIMS = ("minority_interest", "pension_deficit", "preferred", "options")
SENS_FIELDS = ("growth_shift", "margin_shift", "roe_shift", "discount_premium", "discount_shift", "terminal_growth", "terminal_multiple", "sales_to_capital")
MARGIN_TOLERANCE = 1e-6  # a margin equal to its historical best, give or take float rounding, is not above it
EXIT_METRICS = ("ebit", "ebitda", "revenue", "fcfe")
TERMINAL_HEAVY = 0.75


def _num(v: object, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


def _int(v: object, field: str) -> int:
    if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, float) and v.is_integer())):
        raise ValueError(f"{field} must be an integer")
    return int(v)


def _path(v: object, years: int, field: str) -> list[float]:
    if isinstance(v, list):
        if len(v) != years:
            raise ValueError(f"{field} must have exactly {years} entries (one per year)")
        return [_num(x, f"{field}[{i}]") for i, x in enumerate(v)]
    return [_num(v, field)] * years


def _rate(seg: dict, base: float, name: str, zero_premium: bool) -> tuple[float, float]:
    premium = 0.0 if zero_premium else _num(seg.get("discount_premium", 0.0), f"{name}.discount_premium")
    start = _num(seg["discount_rate"], f"{name}.discount_rate") if seg.get("discount_rate") is not None else base
    rate = start + premium
    if rate <= 0:
        raise ValueError(f"{name}: discount rate must be positive")
    return rate, premium


def _finish(seg: dict, kind: str, flows: list[float], tv: float, rate: float, premium: float, rows: list[dict], horizon: int) -> dict:
    n = len(flows)
    pv_explicit = sum(f / (1 + rate) ** t for t, f in enumerate(flows, start=1))
    pv_terminal = tv / (1 + rate) ** n
    value = pv_explicit + pv_terminal
    at_h = sum(f / (1 + rate) ** (t - horizon) for t, f in enumerate(flows, start=1) if t > horizon) + tv / (1 + rate) ** (n - horizon)
    return {"name": seg["name"], "kind": kind, "value": value, "pv_terminal": pv_terminal,
            "terminal_share": (pv_terminal / value) if value > 0 else None, "discount_rate": rate,
            "premium": premium, "premium_reason": seg.get("premium_reason") or "", "flows": flows,
            "rows": rows, "value_at_h": at_h, "da_pct_revenue": seg.get("da_pct_revenue")}


def _operating(seg: dict, ctx: dict, zero_premium: bool) -> dict:
    name, n = seg["name"], ctx["years"]
    rate, premium = _rate(seg, ctx["base_rate"], name, zero_premium)
    for key in ("revenue0", "growth", "margin", "sales_to_capital", "terminal"):
        if key not in seg:
            raise ValueError(f"{name}: missing {key}")
    rev = _num(seg["revenue0"], f"{name}.revenue0")
    g = _path(seg["growth"], n, f"{name}.growth")
    m = _path(seg["margin"], n, f"{name}.margin")
    s2c = _path(seg["sales_to_capital"], n, f"{name}.sales_to_capital")
    if any(x <= 0 for x in s2c):
        raise ValueError(f"{name}.sales_to_capital must be positive")
    tax = _num(seg["tax_rate"], f"{name}.tax_rate") if seg.get("tax_rate") is not None else ctx["tax"]
    rows, flows = [], []
    for t in range(1, n + 1):
        new = rev * (1 + g[t - 1])
        ebit = new * m[t - 1]
        reinv = (new - rev) / s2c[t - 1]
        fcff = ebit * (1 - tax) - reinv
        rows.append({"t": t, "revenue": new, "ebit": ebit, "reinvestment": reinv, "fcff": fcff})
        flows.append(fcff)
        rev = new
    term = seg["terminal"]
    if not isinstance(term, dict) or term.get("method") not in ("gordon", "multiple"):
        raise ValueError(f"{name}.terminal.method must be gordon or multiple")
    if term["method"] == "gordon":
        tg = _num(term.get("growth"), f"{name}.terminal.growth")
        if tg >= rate:
            raise ValueError(f"{name}: terminal growth {tg} must be below the discount rate {rate:.4f}")
        nxt = rev * (1 + tg)
        tv = (nxt * m[-1] * (1 - tax) - (nxt - rev) / s2c[-1]) / (rate - tg)
    else:
        metric = term.get("metric")
        mult = _num(term.get("multiple"), f"{name}.terminal.multiple")
        last = rows[-1]
        if metric == "ebit":
            base_metric = last["ebit"]
        elif metric == "revenue":
            base_metric = last["revenue"]
        elif metric == "ebitda":
            da = seg.get("da_pct_revenue")
            if da is None:
                raise ValueError(f"{name}: an ebitda multiple needs da_pct_revenue")
            base_metric = last["ebit"] + _num(da, f"{name}.da_pct_revenue") * last["revenue"]
        else:
            raise ValueError(f"{name}.terminal.metric must be ebit, ebitda or revenue")
        tv = mult * base_metric
    fails = seg.get("fails")
    if fails:
        y = _int(fails.get("year"), f"{name}.fails.year")
        if not 1 <= y <= n:
            raise ValueError(f"{name}.fails.year must be between 1 and {n}")
        salvage = _num(fails.get("salvage", 0.0), f"{name}.fails.salvage")
        flows = flows[: y - 1] + [salvage] + [0.0] * (n - y)
        for r in rows[y - 1:]:
            r.update(revenue=0.0, ebit=0.0, reinvestment=0.0, fcff=0.0)
        rows[y - 1]["fcff"] = salvage
        tv = 0.0
    return _finish(seg, "operating", flows, tv, rate, premium, rows, ctx["horizon"])


def _cost(seg: dict, ctx: dict, zero_premium: bool) -> dict:
    name, n = seg["name"], ctx["years"]
    rate, premium = _rate(seg, ctx["base_rate"], name, zero_premium)
    c = _num(seg.get("cost0"), f"{name}.cost0")
    g = _path(seg.get("growth", 0.0), n, f"{name}.growth")
    tg = _num(seg.get("terminal_growth", 0.02), f"{name}.terminal_growth")
    if tg >= rate:
        raise ValueError(f"{name}: terminal growth {tg} must be below the discount rate {rate:.4f}")
    rows, flows = [], []
    for t in range(1, n + 1):
        c *= 1 + g[t - 1]
        rows.append({"t": t, "cost": c})
        flows.append(-c)
    tv = -c * (1 + tg) / (rate - tg)
    return _finish(seg, "cost", flows, tv, rate, premium, rows, ctx["horizon"])


def _flat(seg: dict, kind: str, value: float, ctx: dict) -> dict:
    out = _finish(seg, kind, [0.0] * ctx["years"], 0.0, 1.0, 0.0, [], ctx["horizon"])
    out.update(value=value, pv_terminal=0.0, terminal_share=None, discount_rate=None, value_at_h=value)
    return out


def _residual_income(seg: dict, ctx: dict, zero_premium: bool) -> dict:
    name, n, h = seg["name"], ctx["years"], ctx["horizon"]
    ke, premium = _rate(seg, _num(seg.get("cost_of_equity"), f"{name}.cost_of_equity"), name, zero_premium)
    book = _num(seg.get("book0"), f"{name}.book0")
    roe = _path(seg.get("roe"), n, f"{name}.roe")
    ret = _path(seg.get("retention"), n, f"{name}.retention")
    tg = _num(seg.get("terminal_growth", 0.02), f"{name}.terminal_growth")
    if tg >= ke:
        raise ValueError(f"{name}: terminal growth {tg} must be below the cost of equity {ke:.4f}")
    book0, rows, ri, divs, book_h = book, [], [], [], book
    for t in range(1, n + 1):
        earn = roe[t - 1] * book
        rows.append({"t": t, "book_start": book, "roe": roe[t - 1], "earnings": earn, "residual_income": (roe[t - 1] - ke) * book, "dividends": earn * (1 - ret[t - 1])})
        ri.append((roe[t - 1] - ke) * book)
        divs.append(earn * (1 - ret[t - 1]))
        book += earn * ret[t - 1]
        if t == h:
            book_h = book
    tv = (roe[-1] - ke) * book / (ke - tg)
    pv_ri = sum(x / (1 + ke) ** t for t, x in enumerate(ri, start=1))
    pv_tv = tv / (1 + ke) ** n
    value = book0 + pv_ri + pv_tv
    at_h = book_h + sum(x / (1 + ke) ** (t - h) for t, x in enumerate(ri, start=1) if t > h) + tv / (1 + ke) ** (n - h)
    return {"name": name, "kind": "residual_income", "value": value, "pv_terminal": pv_tv,
            "terminal_share": (pv_tv / value) if value > 0 else None, "discount_rate": ke, "premium": premium,
            "premium_reason": seg.get("premium_reason") or "", "flows": divs, "rows": rows, "value_at_h": at_h,
            "da_pct_revenue": None}


def _segment(seg: dict, ctx: dict, zero_premium: bool) -> dict:
    kind = seg.get("kind")
    if kind == "operating":
        return _operating(seg, ctx, zero_premium)
    if kind == "cost":
        return _cost(seg, ctx, zero_premium)
    if kind == "asset":
        return _flat(seg, "asset", _num(seg.get("value"), f"{seg['name']}.value"), ctx)
    if kind == "venture":
        p = _num(seg.get("probability"), f"{seg['name']}.probability")
        if not 0 <= p <= 1:
            raise ValueError(f"{seg['name']}.probability must be between 0 and 1")
        v = p * _num(seg.get("value_if_success"), f"{seg['name']}.value_if_success") - _num(seg.get("cost_pv", 0.0), f"{seg['name']}.cost_pv")
        return _flat(seg, "venture", v, ctx)
    return _residual_income(seg, ctx, zero_premium)


def _claims(raw: object) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("claims must be an object")
    unknown = set(raw) - set(CLAIMS)
    if unknown:
        raise ValueError(f"unknown claims: {', '.join(sorted(unknown))}")
    return {k: _num(raw.get(k, 0.0), f"claims.{k}") for k in CLAIMS}


def _value(segs: list[dict], ctx: dict, claims: dict, shares: float, zero_premium: bool = False) -> tuple[list[dict], float, float, float]:
    vals = [_segment(s, ctx, zero_premium) for s in segs]
    ev = sum(v["value"] for v in vals if v["kind"] != "residual_income")
    ri = sum(v["value"] for v in vals if v["kind"] == "residual_income")
    equity = ev - claims["debt"] + claims["cash"] - claims["leases"] - sum(claims[k] for k in OTHER_CLAIMS) + ri
    return vals, ev, equity, equity / shares


def _resolve(base_segs: list[dict], sc: dict) -> list[dict]:
    segs = copy.deepcopy(base_segs)
    by = {s["name"]: s for s in segs}
    overrides = sc.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ValueError(f"scenario {sc['name']}: overrides must be an object")
    for seg_name, fields in overrides.items():
        if seg_name not in by:
            raise ValueError(f"scenario {sc['name']}: override names unknown segment {seg_name!r}")
        if not isinstance(fields, dict):
            raise ValueError(f"scenario {sc['name']}: override for {seg_name} must be an object")
        by[seg_name].update(fields)
    return segs


def _apply_sens(segs: list[dict], spec: dict, v: float, years: int) -> list[dict]:
    segs = copy.deepcopy(segs)
    f = spec["field"]
    if f == "discount_shift":  # every discounted segment at once: a company-wide discount-rate axis
        for s in segs:
            if s["kind"] in ("operating", "cost", "residual_income"):
                s["discount_premium"] = float(s.get("discount_premium", 0.0)) + v
        return segs
    seg = next(s for s in segs if s["name"] == spec["segment"])
    if f == "roe_shift":
        seg["roe"] = [x + v for x in _path(seg["roe"], years, "roe")]
    elif f == "growth_shift":
        seg["growth"] = [x + v for x in _path(seg.get("growth", 0.0), years, "growth")]
    elif f == "margin_shift":
        seg["margin"] = [x + v for x in _path(seg["margin"], years, "margin")]
    elif f == "terminal_growth" and seg["kind"] in ("cost", "residual_income"):
        seg["terminal_growth"] = v
    elif f == "terminal_growth":
        seg["terminal"] = {**seg["terminal"], "growth": v}
    elif f == "terminal_multiple":
        seg["terminal"] = {**seg["terminal"], "multiple": v}
    else:
        seg[f] = v
    return segs


_SENS_APPLIES = {
    "growth_shift": ("operating", "cost"), "margin_shift": ("operating",), "sales_to_capital": ("operating",),
    "discount_premium": ("operating", "cost", "residual_income"), "terminal_growth": ("operating", "cost", "residual_income"),
    "terminal_multiple": ("operating",), "roe_shift": ("residual_income",),
}


def _check_sens_axis(ax: dict, segs: list[dict]) -> None:
    """Refuse an axis that cannot move the value, rather than print a flat grid."""
    if (ax["segment"] == "*") != (ax["field"] == "discount_shift"):
        raise ValueError("sensitivity: discount_shift goes with segment \"*\" (every segment), and \"*\" only with discount_shift")
    if ax["segment"] == "*":
        return
    seg = next(s for s in segs if s["name"] == ax["segment"])
    f, kind = ax["field"], seg["kind"]
    method = (seg.get("terminal") or {}).get("method")
    if kind not in _SENS_APPLIES[f]:
        raise ValueError(f"sensitivity: {f} does not apply to {ax['segment']}, a {kind} segment")
    if kind == "operating" and f == "terminal_growth" and method != "gordon":
        raise ValueError(f"sensitivity: terminal_growth does not move {ax['segment']}, whose terminal value is a multiple")
    if kind == "operating" and f == "terminal_multiple" and method != "multiple":
        raise ValueError(f"sensitivity: terminal_multiple does not move {ax['segment']}, whose terminal value is a Gordon growth")


def _exit_multiple(em: dict, vals: list[dict], h: int, fcfe_h: float, nd_0: float, nd_h: float, other: float, ri_h: float, shares_h: float, tax: float) -> float:
    metric = em.get("metric")
    mult = _num(em.get("multiple"), "exit_multiple.multiple")
    if metric not in EXIT_METRICS:
        raise ValueError("exit_multiple.metric must be ebit, ebitda, revenue or fcfe")
    if metric == "fcfe":
        return (mult * fcfe_h + (nd_0 - nd_h)) / shares_h  # the multiple prices the flow; cash kept along the path is on top
    ops = [v for v in vals if v["kind"] == "operating"]
    rev = sum(v["rows"][h - 1]["revenue"] for v in ops)
    ebit = sum(v["rows"][h - 1]["ebit"] for v in ops) - sum(v["rows"][h - 1]["cost"] for v in vals if v["kind"] == "cost") / (1 - tax)
    if metric == "ebitda":
        if any(v["da_pct_revenue"] is None for v in ops):
            raise ValueError("an ebitda exit multiple needs da_pct_revenue on every operating segment")
        ebit += sum(float(v["da_pct_revenue"]) * v["rows"][h - 1]["revenue"] for v in ops)
    base = {"ebit": ebit, "ebitda": ebit, "revenue": rev}[metric]
    flat = sum(v["value"] for v in vals if v["kind"] in ("asset", "venture"))
    return (mult * base + flat - nd_h - other + ri_h) / shares_h


def _sens_base(ax: dict, segs: list[dict], years: int) -> float | None:
    """The axis value that is the scenario as modeled (shifts are 0), so the page can outline that cell."""
    f = ax["field"]
    if f.endswith("_shift"):
        return 0.0
    seg = next(s for s in segs if s["name"] == ax["segment"])
    term = seg.get("terminal") or {}
    if f == "discount_premium":
        return float(seg.get("discount_premium", 0.0))
    if f == "terminal_growth":
        return float(seg.get("terminal_growth", 0.02) if seg["kind"] in ("cost", "residual_income") else term.get("growth"))
    if f == "terminal_multiple":
        return float(term.get("multiple"))
    if f == "sales_to_capital":
        return _path(seg["sales_to_capital"], years, "sales_to_capital")[-1]
    return None


def _pre_premium_rate(ax: dict, segs: list[dict], base_rate: float) -> float | None:
    """The discount rate before any premium for the axis's segment (or the one rate every segment shares, for "*")."""
    def rate(s: dict) -> float:
        if s.get("discount_rate") is not None:
            return float(s["discount_rate"])
        return float(s["cost_of_equity"]) if s["kind"] == "residual_income" else base_rate
    if ax["segment"] != "*":
        seg = next(s for s in segs if s["name"] == ax["segment"])
        return round(rate(seg), 6) if seg["kind"] in ("operating", "cost", "residual_income") else None
    rates = {round(rate(s), 6) for s in segs if s["kind"] in ("operating", "cost", "residual_income")}
    return rates.pop() if len(rates) == 1 else None


def _implied(resolved: tuple[list[dict], dict], sname: str, price: float | None, ctx: dict, shares: float, years: int) -> dict:
    """What the price implies: the one shift to every operating margin (and every residual-income ROE)
    that makes the first scenario's value per share equal the price. Null when no shift within
    +/-50 points does, or when there is no price."""
    segs, claims = resolved
    field = "margin_shift" if any(s["kind"] == "operating" for s in segs) else "roe_shift"
    out = {"scenario": sname, "field": field, "value": None}
    if price is None or not any(s["kind"] in ("operating", "residual_income") for s in segs):
        return out

    def value(x: float) -> float | None:
        shifted = copy.deepcopy(segs)
        for s in shifted:
            if s["kind"] == "operating":
                s["margin"] = [m + x for m in _path(s["margin"], years, "margin")]
            elif s["kind"] == "residual_income":
                s["roe"] = [r + x for r in _path(s["roe"], years, "roe")]
        try:
            return _value(shifted, ctx, claims, shares)[3]
        except (ValueError, ZeroDivisionError):
            return None

    lo, hi = -0.5, 0.5
    f_lo, f_hi = value(lo), value(hi)
    if f_lo is None or f_hi is None or not f_lo <= price <= f_hi:
        return out
    for _ in range(80):
        mid = (lo + hi) / 2
        f_mid = value(mid)
        if f_mid is None:
            return out
        if f_mid < price:
            lo = mid
        else:
            hi = mid
    out["value"] = round((lo + hi) / 2, 4)
    return out


def _r(v: float | None, dp: int = 2) -> float | None:
    return None if v is None else round(v, dp)


def _rows_out(rows: list[dict]) -> list[dict]:
    return [{k: (v if k == "t" else round(v, 2)) for k, v in r.items()} for r in rows]


def run_model(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    shares = _num(params.get("shares_outstanding"), "shares_outstanding")
    if shares <= 0:
        raise ValueError("shares_outstanding must be positive")
    years = _int(params.get("years", 10), "years")
    horizon = _int(params.get("horizon", 5), "horizon")
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if not horizon + 1 <= years <= 30:
        raise ValueError(f"years must be between horizon + 1 ({horizon + 1}) and 30")
    base_rate = _num(params.get("base_discount_rate"), "base_discount_rate")
    if base_rate <= 0:
        raise ValueError("base_discount_rate must be positive")
    tax = _num(params.get("tax_rate", 0.21), "tax_rate")
    if not 0 <= tax < 1:
        raise ValueError("tax_rate must be in [0, 1)")
    cod = _num(params.get("cost_of_debt", 0.0), "cost_of_debt")
    price = params.get("price")
    price = None if price is None else _num(price, "price")
    hurdle = _num(params.get("hurdle", 0.10), "hurdle")
    segs = params.get("segments")
    if not isinstance(segs, list) or not segs:
        raise ValueError("segments must be a non-empty list")
    names = []
    for s in segs:
        if not isinstance(s, dict) or not s.get("name"):
            raise ValueError("every segment needs a name")
        if s.get("kind") not in KINDS:
            raise ValueError(f"{s['name']}: kind must be one of {', '.join(KINDS)}")
        names.append(s["name"])
    if len(set(names)) != len(names):
        raise ValueError("segment names must be unique")
    scenarios = params.get("scenarios") or [{"name": "Base"}]
    sc_names = [s.get("name") for s in scenarios if isinstance(s, dict)]
    if len(sc_names) != len(scenarios) or not all(sc_names) or len(set(sc_names)) != len(sc_names):
        raise ValueError("scenarios need unique names")
    ctx = {"years": years, "horizon": horizon, "base_rate": base_rate, "tax": tax}
    history = params.get("history") or {}
    flags: list[dict] = []

    def flag(code: str, message: str) -> None:
        if not any(f["code"] == code and f["message"] == message for f in flags):
            flags.append({"code": code, "message": message})

    results, resolved = [], {}
    seg_flags: dict[tuple[str, str], list[str]] = {}  # one flag per segment, naming every scenario it fires in
    for sc in scenarios:
        payout = _num(sc.get("payout", params.get("payout", 1.0)), "payout")
        if not 0 <= payout <= 1:
            raise ValueError("payout must be between 0 and 1")
        dil = _num(sc.get("annual_dilution", params.get("annual_dilution", 0.0)), "annual_dilution")
        if dil <= -1:
            raise ValueError("annual_dilution must be above -1")
        claims = _claims({**(params.get("claims") or {}), **(sc.get("claims") or {})})
        sc_cod = _num(sc.get("cost_of_debt", cod), "cost_of_debt")
        s_segs = _resolve(segs, sc)
        resolved[sc["name"]] = (s_segs, claims)
        vals, ev, equity, vps = _value(s_segs, ctx, claims, shares)
        _, _, _, vps_ex = _value(s_segs, ctx, claims, shares, zero_premium=True)
        # path to the horizon
        nd = nd_0 = claims["debt"] - claims["cash"] + claims["leases"]
        other = sum(claims[k] for k in OTHER_CLAIMS)
        sh, path, fcfe = shares, [], 0.0
        for t in range(1, horizon + 1):
            ops_flow = sum(v["flows"][t - 1] for v in vals)
            fcfe = ops_flow - sc_cod * (1 - tax) * nd
            dist = payout * max(fcfe, 0.0)
            nd -= fcfe - dist
            sh *= 1 + dil
            path.append({"t": t, "fcfe": round(fcfe, 2), "distributions_per_share": round(dist / sh, 4), "net_debt": round(nd, 2), "shares": round(sh, 4)})
        ev_h = sum(v["value_at_h"] for v in vals if v["kind"] != "residual_income")
        ri_h = sum(v["value_at_h"] for v in vals if v["kind"] == "residual_income")
        roll = (ev_h - nd - other + ri_h) / sh
        em = sc.get("exit_multiple")
        mult_exit = _exit_multiple(em, vals, horizon, fcfe, nd_0, nd, other, ri_h, sh, tax) if em else None
        for v in vals:
            if v["kind"] != "operating":
                continue
            if v["terminal_share"] is not None and v["terminal_share"] > TERMINAL_HEAVY:
                seg_flags.setdefault(("TERMINAL_HEAVY", v["name"]), []).append(sc["name"])
            if any(r["reinvestment"] < 0 for r in v["rows"]):
                seg_flags.setdefault(("REINVESTMENT_NEGATIVE", v["name"]), []).append(sc["name"])
            cap = (history.get(v["name"]) or {}).get("max_margin")
            if cap is not None and any(r["revenue"] and r["ebit"] / r["revenue"] > float(cap) + MARGIN_TOLERANCE for r in v["rows"]):
                seg_flags.setdefault(("MARGIN_ABOVE_HISTORY", v["name"]), []).append(sc["name"])
        if equity <= 0:
            flag("NEGATIVE_EQUITY", f"{sc['name']}: the debt and other claims exceed the business value.")
        results.append({
            "name": sc["name"], "summary": sc.get("summary") or "", "must_be_true": list(sc.get("must_be_true") or []),
            "enterprise_value": round(ev, 2), "equity_value": round(equity, 2), "value_per_share": round(vps, 2),
            "value_ex_premiums": round(vps_ex, 2),
            "upside": round(vps / price - 1, 4) if price else None,
            "segments": [{"name": v["name"], "kind": v["kind"], "value": round(v["value"], 2), "pv_terminal": round(v["pv_terminal"], 2),
                          "terminal_share": _r(v["terminal_share"], 4), "discount_rate": _r(v["discount_rate"], 4),
                          "premium": round(v["premium"], 4), "premium_reason": v["premium_reason"], "years": _rows_out(v["rows"])} for v in vals],
            "bridge": {"enterprise_value": round(ev, 2), **{k: round(claims[k], 2) for k in CLAIMS},
                       "residual_income_equity": round(sum(v["value"] for v in vals if v["kind"] == "residual_income"), 2),
                       "equity_value": round(equity, 2)},
            "path": path,
            "exit": {"dcf_roll": round(roll, 2), "multiple": _r(mult_exit)},
        })

    seg_text = {
        "TERMINAL_HEAVY": "{seg} gets more than {pct:.0%} of its value from the years after the forecast ({where}).",
        "REINVESTMENT_NEGATIVE": "{seg} shrinks in some years, so the model releases capital back as cash ({where}).",
        "MARGIN_ABOVE_HISTORY": "{seg} margin exceeds its historical best of {cap:.1%} ({where}).",
    }
    for (code, seg), where in seg_flags.items():
        cap = float((history.get(seg) or {}).get("max_margin") or 0)
        flag(code, seg_text[code].format(seg=seg, pct=TERMINAL_HEAVY, cap=cap, where=", ".join(where)))

    sens = None
    spec = params.get("sensitivity")
    if spec:
        sname = spec.get("scenario") or results[0]["name"]
        if sname not in resolved:
            raise ValueError(f"sensitivity.scenario {sname!r} is not a scenario")
        for axis in ("a", "b"):
            ax = spec.get(axis) or {}
            if ax.get("segment") not in (*names, "*") or ax.get("field") not in SENS_FIELDS or not isinstance(ax.get("values"), list) or not ax["values"]:
                raise ValueError(f"sensitivity.{axis} needs a segment, a field in {', '.join(SENS_FIELDS)} and values")
        s_segs, claims = resolved[sname]
        _check_sens_axis(spec["a"], s_segs)
        _check_sens_axis(spec["b"], s_segs)
        grid = []
        for va in spec["a"]["values"]:
            row = []
            for vb in spec["b"]["values"]:
                try:
                    cell = _apply_sens(_apply_sens(s_segs, spec["a"], _num(va, "sensitivity value"), years), spec["b"], _num(vb, "sensitivity value"), years)
                    row.append(round(_value(cell, ctx, claims, shares)[3], 2))
                except (ValueError, ZeroDivisionError):
                    row.append(None)
            grid.append(row)
        sens = {"scenario": sname, "a": spec["a"], "b": spec["b"], "value_per_share": grid,
                "base": {k: _sens_base(spec[k], s_segs, years) for k in ("a", "b")},
                "discount_rate": {k: _pre_premium_rate(spec[k], s_segs, base_rate) for k in ("a", "b")}}

    implied = _implied(resolved[results[0]["name"]], results[0]["name"], price, ctx, shares, years)

    return {
        "symbol": params.get("symbol"), "price": price, "horizon": horizon, "scenarios": results, "sensitivity": sens,
        "implied": implied,
        "returns_input": {"mode": "paths", "price": price, "horizon": horizon, "hurdle": hurdle,
                          "scenarios": [{"name": r["name"], "distributions_per_share": [p["distributions_per_share"] for p in r["path"]],
                                         "exit_value_per_share": r["exit"]["dcf_roll"], "exit_multiple_value": r["exit"]["multiple"]} for r in results]},
        "flags": flags,
    }


def main() -> None:
    try:
        result = run_model(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
