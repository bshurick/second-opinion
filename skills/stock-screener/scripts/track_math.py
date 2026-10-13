#!/usr/bin/env python3
"""Re-check a pick against the valuation it was picked on (stdin -> stdout JSON).

    python track_math.py < track.json

Pure arithmetic: nothing is fetched (picks.py gathers the inputs). Exit 2 with {"error"} on invalid
input. Two modes.

``deep``: which of a deep valuation's scenarios the reported quarters are tracking. Input::

    {"mode": "deep", "as_of": "YYYY-MM-DD", "price": 50.0,
     "baseline": {"as_of", "model": <model.py output>, "model_input"?: <model.json>, "ledger"?: [...],
                  "base_period_end"?: "YYYY-MM-DD"},
     "actuals": {"annual": [{"period_end", "first_filed", "revenue", "operating_income"?, "roe"?}],
                 "ttm_at_baseline"?: {"period_end", "revenue", "operating_income"?},
                 "ttm": {"period_end", "revenue", "operating_income"?, "net_income"?, "equity_start"?},
                 "known_at_baseline"?: "YYYY-MM-DD",
                 "segments"?: {"<segment>": {"revenue", "ebit"?, "base_revenue"?}}},
     "exclude_segments"?: ["<segment>"],
     "evidence"?: [{"belief": "<ledger id>" | "must:<scenario>:<index>", "finding": "supports"|"contradicts",
                    "claim", "source", "date"}]}

(``actuals.base``, one annual entry, is still accepted for ``annual``.)

Alignment. The model's starting revenue is the sum of ``revenue0`` (from ``model_input``; without
it, backed out of the yearly path, APPROX_BASE). The last reported year is the latest ``annual``
entry first filed on or before the baseline's ``as_of``. When the starting revenue matches it (in
the model's units, a power of 1000 from EDGAR's dollars), that year is year 0 and the scenarios are
scaled to its reported revenue (BASE_MISMATCH beyond 5%). When the starting revenue is more than 5%
above it, the model started from an estimate of the year in progress (FORWARD_BASE): year 0 is the
year after the last reported one, at the model's estimate, and year -1 is the reported year.
When it instead matches the trailing twelve months known on the valuation date
(``actuals.ttm_at_baseline``) more closely, year 0 ends with those twelve months (TTM_BASE).
While year 0 is in progress it is held at the last reported margin, and every scenario shares it
(SCENARIOS_SHARE_YEAR_0); segment growth is not compared then (SEGMENT_GROWTH_SKIPPED).
``baseline.base_period_end`` sets year 0's end outright. Scenario year t is the t-th fiscal year
after year 0. The TTM window ends f years after year 0's end (``elapsed_years``, negative while
year 0 is in progress) and covers (f-1, f]; each scenario's expected TTM figure is the
overlap-weighted sum of its yearly figures. ``exclude_segments`` leaves out segments that are not
in reported results yet, such as an acquisition that has not closed (SEGMENTS_EXCLUDED).
Expected operating income is operating EBIT less cost segments grossed up for tax (``model_input``
tax_rate, else 21% and DEFAULT_TAX).

Metrics. ``revenue_growth`` (TTM over the last reported year's revenue) and ``operating_margin`` (TTM operating income
over TTM revenue) when the model has operating segments; ``roe`` (TTM net income over equity a year
earlier, against each scenario's earnings over opening book) when it has only residual-income
segments; when the reported base-year ROE is more than 2 points from the central scenario's first
year (GAAP equity against an ex-AOCI model, say), every scenario is shifted by that gap
(ROE_DEFINITION). A segment named in ``actuals.segments`` adds ``<segment>:operating_margin`` and, when
its base revenue is known, ``<segment>:revenue_growth``; segment actuals are in the model's units. Tolerances: growth 2 points, margin 0.5
points, ROE 1 point. Per scenario, distance = sum over metrics of |actual - expected| / tolerance.
A metric is ``below`` or ``above`` when the actual is outside every scenario's expectation by more
than growth 3 points, margin 1 point or ROE 1.5 points (wider, since GAAP and model definitions
differ a little), else ``inside``.

Status, first match wins: ``no_new_data`` (the TTM ends on or before ``known_at_baseline``, the
latest quarter reported by the valuation date; without it, f < 0.2);
``outside`` (any metric below or above every scenario); ``shifting`` (the nearest scenario is not
the central, first, one and is closer by at least 1); ``on_track``. ``rerun_deep`` is true when
outside, when the baseline is over 15 months old (STALE_BASELINE), when evidence contradicts a
high-stakes ledger belief (HIGH_STAKES_CONTRADICTED) or one of the central scenario's conditions
(CENTRAL_CONDITION_CONTRADICTED).

Price. Scenario values per share against today's price (``below_all``, ``inside``, ``above_all``,
and the scenario whose value is nearest), and each scenario's annualized return at today's price:
the baseline's ``returns_input`` rerun through valuation's returns.py with the new price. The price
``level``, highest first: ``above_all`` (over the best scenario's value), ``above_central`` (over
the central value), ``hurdle`` (over the price at which the central scenario earns exactly the
hurdle a year), ``below_worst`` (under the worst value), else ``normal``; ``levels`` gives each
threshold price. A light pick uses bear / base / bull as worst / central / best, with no hurdle.
The level describes the price against the valuation; it never changes ``status``.

``watch`` lists what to look for evidence on: the central and nearest scenarios' ``must_be_true``
items (id ``must:<scenario>:<index>``) and the ledger beliefs with high stakes, or medium stakes
and an open or doubtful verdict.

Output: {"mode", "status", "central", "nearest", "rerun_deep", "reasons": [{"code", "message"}],
"elapsed_years", "metrics": {name: {"actual", "expected": {scenario: v}, "envelope", "position",
"tolerance"}}, "scenarios": [{"name", "distance", "value_per_share", "irr", "baseline_irr"}],
"price": {"price", "baseline_price", "position", "nearest_value"}, "watch", "evidence", "flags"}.

``light``: a funnel pick's growth and margin against the day it was picked. Input::

    {"mode": "light", "as_of", "price",
     "baseline": {"fair_values": {"bear", "base", "bull"},
                  "metrics_at_pick": {"period_end", "revenue_growth", "operating_margin"}},
     "actuals": {"period_end", "revenue_growth", "operating_margin"}}

``no_new_data`` when no later quarter is reported; ``weakening`` (and ``deep_review``) when growth
fell more than 5 points (GROWTH_FELL) or the margin more than 2 points (MARGIN_FELL); else
``on_track``. Price ``position``: below_bear, bear_base, base_bull or above_bull. Output: {"mode",
"status", "deep_review", "reasons", "metrics": {name: {"at_pick", "now", "change"}}, "price",
"flags"}.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

RETURNS_SCRIPT = Path(__file__).resolve().parents[2] / "valuation" / "scripts" / "returns.py"

TOL = {"revenue_growth": 0.02, "operating_margin": 0.005, "roe": 0.01}  # distance units, for the nearest scenario
ENVELOPE_TOL = {"revenue_growth": 0.03, "operating_margin": 0.01, "roe": 0.015}  # how far outside every scenario is "outside"
SHIFT_GAP = 1.0
MIN_ELAPSED = 0.2
STALE_DAYS = 456  # 15 months
BASE_MISMATCH = 0.05
ROE_DEFINITION_GAP = 0.02
DEFAULT_TAX = 0.21
LIGHT_GROWTH_DROP = 0.05
LIGHT_MARGIN_DROP = 0.02
FINDINGS = ("supports", "contradicts")


def _num(v: object, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


def _opt(v: object, field: str) -> float | None:
    return None if v is None else _num(v, field)


def _date(v: object, field: str) -> date:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as exc:
        raise ValueError(f"{field} must be a YYYY-MM-DD date") from exc


def _r(v: float | None, dp: int = 4) -> float | None:
    return None if v is None else round(v, dp)


def _flag(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def window_weights(f: float) -> dict[int, float]:
    """Share of the TTM window (f-1, f] that falls in each fiscal year k, which covers (k-1, k]."""
    lo, hi = f - 1.0, f
    out = {}
    for k in range(math.floor(lo) + 1, math.ceil(hi) + 1):
        a, b = max(lo, k - 1.0), min(hi, float(k))
        if b - a > 1e-9:
            out[k] = b - a
    return out


def expected_ttm(yearly: list[float], y0: float, f: float, y_prev: float | None = None) -> float:
    """Overlap-weighted TTM figure from yearly figures (index 0 is year 1), with year 0 at ``y0`` and
    year -1 (and before) at ``y_prev`` (``y0`` when not given); years past the path repeat its last year."""
    total = 0.0
    for k, w in window_weights(f).items():
        if k <= -1:
            v = y0 if y_prev is None else y_prev
        elif k == 0:
            v = y0
        else:
            v = yearly[min(k, len(yearly)) - 1]
        total += w * v
    return total


def revenue0_from_years(years: list[dict]) -> float | None:
    """A segment's starting revenue backed out of model.py's yearly rows: reinvestment_t is
    (revenue_t - revenue_t-1) / sales_to_capital_t, so with sales-to-capital the same in year 1 as in
    the first later year whose revenue moved, revenue_0 = revenue_1 - reinvestment_1 * sales_to_capital."""
    if not years:
        return None
    r1, re1 = float(years[0]["revenue"]), float(years[0].get("reinvestment") or 0.0)
    if abs(re1) < 1e-9:
        return r1
    for prev, cur in zip(years, years[1:]):
        moved, re = float(cur["revenue"]) - float(prev["revenue"]), float(cur.get("reinvestment") or 0.0)
        if abs(moved) > 1e-9 and abs(re) > 1e-9:
            return r1 - re1 * moved / re
    return None


def _returns_module():
    if not RETURNS_SCRIPT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("returns", RETURNS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _scenario_paths(sc: dict, tax: float) -> dict:
    """Yearly company totals for one scenario: revenue, operating income, ROE, and per operating segment."""
    segs = sc.get("segments") or []
    ops = [s for s in segs if s.get("kind") == "operating"]
    costs = [s for s in segs if s.get("kind") == "cost"]
    ris = [s for s in segs if s.get("kind") == "residual_income"]
    n = max((len(s.get("years") or []) for s in segs), default=0)
    rev, oi, roe = [], [], []
    for i in range(n):
        r = sum(s["years"][i]["revenue"] for s in ops if i < len(s["years"]))
        e = sum(s["years"][i]["ebit"] for s in ops if i < len(s["years"]))
        e -= sum(s["years"][i]["cost"] for s in costs if i < len(s["years"])) / (1 - tax)
        rev.append(r)
        oi.append(e)
        book = sum(s["years"][i]["book_start"] for s in ris if i < len(s["years"]))
        earn = sum(s["years"][i]["earnings"] for s in ris if i < len(s["years"]))
        roe.append(earn / book if book else None)
    by_seg = {s["name"]: {"revenue": [y["revenue"] for y in s["years"]], "ebit": [y["ebit"] for y in s["years"]]} for s in ops}
    return {"revenue": rev, "oi": oi, "roe": roe, "has_ops": bool(ops), "has_ri": bool(ris), "segments": by_seg}


def _compare(actual: float, expected: dict[str, float], tol: float) -> dict:
    lo, hi = min(expected.values()), max(expected.values())
    pos = "below" if actual < lo - tol else "above" if actual > hi + tol else "inside"
    return {"actual": _r(actual), "expected": {k: _r(v) for k, v in expected.items()}, "envelope": [_r(lo), _r(hi)],
            "position": pos, "tolerance": tol}


def _watch(scen: list[dict], names: list[str], ledger: list[dict]) -> list[dict]:
    out = []
    for s in scen:
        if s.get("name") in names:
            for i, item in enumerate(s.get("must_be_true") or []):
                out.append({"id": f"must:{s['name']}:{i}", "kind": "condition", "scenario": s["name"], "text": item})
    for e in ledger:
        stakes, verdict = e.get("stakes"), e.get("verdict")
        if stakes == "high" or (stakes == "medium" and verdict in ("open", "doubtful")):
            out.append({"id": e.get("id"), "kind": "belief", "stakes": stakes, "verdict": verdict, "if_true": e.get("if_true"),
                        "text": e.get("headline") or e.get("belief")})
    return out


def _evidence(items: object) -> list[dict]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError("evidence must be a list")
    out = []
    for i, ev in enumerate(items):
        if not isinstance(ev, dict):
            raise ValueError(f"evidence[{i}] must be an object")
        for k in ("belief", "claim", "source", "date"):
            if not ev.get(k):
                raise ValueError(f"evidence[{i}] needs a {k}: a claim without a dated source changes nothing")
        _date(ev["date"], f"evidence[{i}].date")
        if ev.get("finding") not in FINDINGS:
            raise ValueError(f"evidence[{i}].finding must be supports or contradicts")
        out.append({k: ev[k] for k in ("belief", "finding", "claim", "source", "date")})
    return out


LEVELS = ("below_worst", "normal", "hurdle", "above_central", "above_all")  # lowest to highest


def price_levels(model: dict) -> dict:
    """The prices at which a deep pick's price level changes: the worst, central (first) and best
    scenario values per share, and ``hurdle``, the price at which the central scenario's annual
    return falls to the returns input's hurdle (its distributions and exit value discounted at the
    hurdle; null without a returns input)."""
    scen = model.get("scenarios") or []
    vals = [s["value_per_share"] for s in scen if isinstance(s.get("value_per_share"), (int, float))]
    if not vals:
        raise ValueError("the model has no scenario values")
    out = {"worst": min(vals), "central": scen[0]["value_per_share"], "best": max(vals), "hurdle": None}
    ri = model.get("returns_input") or {}
    sc = next((x for x in ri.get("scenarios") or [] if x.get("name") == scen[0].get("name")), None)
    if sc:
        h = float(ri.get("hurdle", 0.10))
        dists = sc.get("distributions_per_share") or []
        exit_v = max(float(sc.get("exit_value_per_share") or 0.0), 0.0)
        out["hurdle"] = round(sum(d / (1 + h) ** t for t, d in enumerate(dists, start=1)) + exit_v / (1 + h) ** len(dists), 2)
    return out


def price_level(price: float, levels: dict) -> str:
    """The highest level the price has crossed: above_all (over the best value), above_central (over
    the central value), hurdle (over the hurdle price: the central return is under the hurdle),
    below_worst (under the worst value), else normal."""
    if price > levels["best"]:
        return "above_all"
    if price > levels["central"]:
        return "above_central"
    if levels.get("hurdle") is not None and price > levels["hurdle"]:
        return "hurdle"
    if price < levels["worst"]:
        return "below_worst"
    return "normal"


def _price_block(scen: list[dict], price: float, baseline_price: float | None, levels: dict) -> dict:
    vals = {s["name"]: s.get("value_per_share") for s in scen if isinstance(s.get("value_per_share"), (int, float))}
    pos, nearest = None, None
    if vals:
        pos = "below_all" if price < min(vals.values()) else "above_all" if price > max(vals.values()) else "inside"
        nearest = min(vals, key=lambda k: abs(vals[k] - price))
    return {"price": price, "baseline_price": baseline_price, "position": pos, "nearest_value": nearest,
            "level": price_level(price, levels), "levels": levels}


def _irrs(model: dict, price: float, flags: list[dict]) -> dict[str, float | None]:
    ri = model.get("returns_input")
    mod = _returns_module()
    if not isinstance(ri, dict) or mod is None:
        flags.append(_flag("NO_RETURNS", "the baseline has no returns input (or the valuation skill is missing), so returns at today's price are not computed"))
        return {}
    try:
        res = mod.run_returns({**ri, "price": price})
    except ValueError as exc:
        flags.append(_flag("NO_RETURNS", f"returns at today's price failed: {exc}"))
        return {}
    return {s["name"]: s["irr"] for s in res["scenarios"]}


def run_deep(params: dict) -> dict:
    base_line = params.get("baseline")
    if not isinstance(base_line, dict) or not isinstance(base_line.get("model"), dict) or not base_line["model"].get("scenarios"):
        raise ValueError("baseline.model must be a model.py output with scenarios")
    model = base_line["model"]
    scen = model["scenarios"]
    as_of = _date(params.get("as_of"), "as_of")
    base_as_of = _date(base_line.get("as_of"), "baseline.as_of")
    price = _num(params.get("price"), "price")
    actuals = params.get("actuals") or {}
    ttm = actuals.get("ttm") or {}
    annual = actuals.get("annual")
    if annual is None and actuals.get("base"):
        annual = [{**actuals["base"], "first_filed": actuals["base"].get("first_filed") or base_as_of.isoformat()}]
    if not annual or not ttm:
        raise ValueError("actuals.annual (or actuals.base) and actuals.ttm are required")
    annual = sorted((a for a in annual if isinstance(a, dict)), key=lambda a: str(a.get("period_end")))
    known = [a for a in annual if str(a.get("first_filed") or "") <= base_as_of.isoformat()] or annual[:1]
    last_fy = known[-1]
    last_end = _date(last_fy.get("period_end"), "actuals.annual.period_end")
    ttm_end = _date(ttm.get("period_end"), "actuals.ttm.period_end")
    flags: list[dict] = []
    reasons: list[dict] = []
    mi = base_line.get("model_input") if isinstance(base_line.get("model_input"), dict) else None
    tax = _num(mi["tax_rate"], "model_input.tax_rate") if mi and mi.get("tax_rate") is not None else DEFAULT_TAX
    excluded = set(params.get("exclude_segments") or [])
    if excluded:
        names = {sg.get("name") for sg in scen[0].get("segments") or []}
        for x in sorted(excluded - names):
            flags.append(_flag("UNKNOWN_SEGMENT", f"segment {x} is not in the model"))
        flags.append(_flag("SEGMENTS_EXCLUDED", f"left out of the comparison (not in reported results yet): {', '.join(sorted(excluded & names))}"))
    paths = {s["name"]: _scenario_paths({"segments": [sg for sg in s.get("segments") or [] if sg.get("name") not in excluded]}, tax)
             for s in scen}
    central = scen[0]["name"]
    first = paths[central]
    if mi is None and any(sg.get("kind") == "cost" for sg in scen[0].get("segments") or []):
        flags.append(_flag("DEFAULT_TAX", f"no model input saved; cost segments are grossed up at {DEFAULT_TAX:.0%} tax"))

    metrics: dict[str, dict] = {}
    expected: dict[str, dict[str, float]] = {}
    actual: dict[str, float] = {}
    base_end, forward = last_end, False
    if first["has_ops"]:
        ref = _num(last_fy.get("revenue"), "actuals.annual.revenue")
        rev_ttm = _num(ttm.get("revenue"), "actuals.ttm.revenue")
        if ref <= 0 or rev_ttm <= 0:
            raise ValueError("reported and TTM revenue must be positive")
        mi_ops = [sg for sg in (mi or {}).get("segments") or [] if sg.get("kind") == "operating" and sg.get("name") not in excluded]
        r0_model = 0.0
        if mi_ops and all(sg.get("revenue0") is not None for sg in mi_ops):
            r0_model = sum(_num(sg["revenue0"], f"model_input.{sg.get('name')}.revenue0") for sg in mi_ops)
        if r0_model <= 0:
            backed = [revenue0_from_years(sg.get("years") or []) for sg in scen[0].get("segments") or []
                      if sg.get("kind") == "operating" and sg.get("name") not in excluded]
            r0_model = sum(b for b in backed if b is not None)
            flags.append(_flag("APPROX_BASE", "no model input saved; the model's starting revenue is backed out of its yearly path"))
        if r0_model <= 0:
            raise ValueError("cannot tell the model's starting revenue")
        # Models are usually in millions and EDGAR in dollars: the unit is the power of 1000 between them.
        unit = 10.0 ** (3 * round(math.log10(ref / r0_model) / 3))
        gap = r0_model * unit / ref - 1
        e_ref = _opt(last_fy.get("operating_income"), "actuals.annual.operating_income")
        # A model may start from the trailing twelve months known on the valuation date instead of a fiscal year.
        tb = actuals.get("ttm_at_baseline") if isinstance(actuals.get("ttm_at_baseline"), dict) else None
        tb_gap = None
        if tb and tb.get("revenue"):
            tb_gap = r0_model * unit / _num(tb["revenue"], "actuals.ttm_at_baseline.revenue") - 1
        explicit = base_line.get("base_period_end")
        use_ttm = False
        if explicit:
            base_end = _date(explicit, "baseline.base_period_end")
            use_ttm = bool(tb) and base_end == _date(tb.get("period_end"), "actuals.ttm_at_baseline.period_end")
            forward = not use_ttm and base_end > last_end
        else:
            use_ttm = tb_gap is not None and abs(tb_gap) <= BASE_MISMATCH and abs(tb_gap) < abs(gap)
            forward = not use_ttm and gap > BASE_MISMATCH  # well above the last reported year: the year in progress
        if use_ttm:
            base_end = _date(tb.get("period_end"), "actuals.ttm_at_baseline.period_end")
            ref, gap = _num(tb["revenue"], "actuals.ttm_at_baseline.revenue"), tb_gap if tb_gap is not None else gap
            e_ref = _opt(tb.get("operating_income"), "actuals.ttm_at_baseline.operating_income")
            flags.append(_flag("TTM_BASE", f"the model starts from the twelve months to {base_end.isoformat()}, so year 0 ends there"))
        elif forward and not explicit:
            prior = known[:-1]
            step = (last_end - _date(prior[-1]["period_end"], "actuals.annual.period_end")) if prior else None
            base_end = last_end + (step if step and 350 <= step.days <= 380 else timedelta(days=365))
        oi_ttm = _opt(ttm.get("operating_income"), "actuals.ttm.operating_income")
        if forward:
            scale = unit
            r0 = r0_model * unit
            # the year in progress is held at the last reported margin: the model gives no year-0 margin
            e0 = None if e_ref is None else r0 * e_ref / ref
            prev_r, prev_e = ref, e_ref
            flags.append(_flag("FORWARD_BASE", f"the model starts from an estimate of the fiscal year ending about {base_end.isoformat()} ({gap:+.1%} on the last reported year), so the year in progress is compared with that estimate"))
        else:
            scale = ref / r0_model
            r0, e0, prev_r, prev_e = ref, e_ref, None, None
            if abs(gap) > BASE_MISMATCH:
                flags.append(_flag("BASE_MISMATCH", f"reported base-year revenue is {-gap / (1 + gap):+.1%} from the model's segment sum; the scenarios are scaled to it"))
        f = (ttm_end - base_end).days / 365.25
        if forward and f <= 0:
            flags.append(_flag("SCENARIOS_SHARE_YEAR_0", "the latest quarters fall in the year the model started from, which every scenario shares; the scenarios cannot be told apart until that year is reported"))
        exp_rev = {n: expected_ttm([v * scale for v in p["revenue"]], r0, f, prev_r) for n, p in paths.items()}
        expected["revenue_growth"] = {n: v / ref - 1 for n, v in exp_rev.items()}
        actual["revenue_growth"] = rev_ttm / ref - 1
        if e0 is None or oi_ttm is None or (forward and prev_e is None):
            flags.append(_flag("NO_OPERATING_INCOME", "operating income is not reported in XBRL; compared on revenue only"))
        else:
            expected["operating_margin"] = {n: expected_ttm([v * scale for v in p["oi"]], e0, f, prev_e) / exp_rev[n]
                                            for n, p in paths.items()}
            actual["operating_margin"] = oi_ttm / rev_ttm
        for seg, a in (actuals.get("segments") or {}).items():
            if seg in excluded:
                flags.append(_flag("SEGMENT_EXCLUDED_ACTUALS", f"segment {seg} is excluded, so its actuals are not compared"))
                continue
            if seg not in first["segments"]:
                flags.append(_flag("UNKNOWN_SEGMENT", f"segment {seg} is not in the model"))
                continue
            srev = _num(a.get("revenue"), f"segments.{seg}.revenue")
            b = a.get("base_revenue")
            if b is None and mi:
                b = next((sg.get("revenue0") for sg in mi.get("segments") or [] if sg.get("name") == seg), None)
            if b is not None and forward:
                flags.append(_flag("SEGMENT_GROWTH_SKIPPED", f"{seg}: the model starts from an estimate of the year in progress, so segment growth is not compared"))
            elif b is not None:
                b = _num(b, f"segments.{seg}.base_revenue")
                expected[f"{seg}:revenue_growth"] = {n: expected_ttm(p["segments"][seg]["revenue"], b, f) / b - 1 for n, p in paths.items()}
                actual[f"{seg}:revenue_growth"] = srev / b - 1
            if a.get("ebit") is not None:
                y1 = {n: p["segments"][seg] for n, p in paths.items()}
                # year 0 margin is unknown at segment level: blend on the scenario's own year-1 margin
                expected[f"{seg}:operating_margin"] = {
                    n: expected_ttm(s["ebit"], s["ebit"][0], max(f, 1.0)) / expected_ttm(s["revenue"], s["revenue"][0], max(f, 1.0))
                    for n, s in y1.items()}
                actual[f"{seg}:operating_margin"] = _num(a["ebit"], f"segments.{seg}.ebit") / srev
    elif first["has_ri"]:
        ni, eq = _opt(ttm.get("net_income"), "actuals.ttm.net_income"), _opt(ttm.get("equity_start"), "actuals.ttm.equity_start")
        if ni is None or not eq:
            raise ValueError("a residual-income model needs actuals.ttm.net_income and equity_start")
        f = (ttm_end - base_end).days / 365.25
        roe0 = _opt(last_fy.get("roe"), "actuals.annual.roe")
        offset = 0.0
        if roe0 is not None and first["roe"][0] is not None and abs(roe0 - first["roe"][0]) > ROE_DEFINITION_GAP:
            # Reported ROE on another definition (GAAP equity with AOCI, against an ex-AOCI model):
            # track the change from the base year, not the level.
            offset = roe0 - first["roe"][0]
            flags.append(_flag("ROE_DEFINITION", f"reported base-year ROE {roe0:.1%} is {offset * 100:+.1f} points from the model's {first['roe'][0]:.1%}; the scenarios are shifted by the gap"))
        expected["roe"] = {n: expected_ttm([v + offset for v in p["roe"]], p["roe"][0] + offset if roe0 is None else roe0, f)
                           for n, p in paths.items()}
        actual["roe"] = ni / eq
    else:
        raise ValueError("the model has no operating or residual-income segment to track")

    for name, exp in expected.items():
        metrics[name] = _compare(actual[name], exp, ENVELOPE_TOL[name.split(":")[-1]])
    dist = {n: sum(abs(actual[m] - expected[m][n]) / TOL[m.split(":")[-1]] for m in expected) for n in paths}
    nearest = min(paths, key=lambda n: (dist[n], n != central))
    outside = [m for m, v in metrics.items() if v["position"] != "inside"]

    known_q = actuals.get("known_at_baseline")
    if f > max(len(first["revenue"] or first["roe"]), 1):
        flags.append(_flag("BEYOND_PATH", "the latest quarter is past the model's last year; its last year is repeated"))
    if (known_q and ttm_end <= _date(known_q, "actuals.known_at_baseline")) or (not known_q and f < (MIN_ELAPSED - 1 if forward else MIN_ELAPSED)):
        status = "no_new_data"
    elif outside:
        status = "outside"
        for m in outside:
            reasons.append(_flag("OUTSIDE_SCENARIOS", f"{m} is {metrics[m]['position']} every scenario: actual {metrics[m]['actual']}, scenarios {metrics[m]['envelope'][0]} to {metrics[m]['envelope'][1]}"))
    elif nearest != central and dist[central] - dist[nearest] >= SHIFT_GAP:
        status = "shifting"
    else:
        status = "on_track"

    if (as_of - base_as_of).days > STALE_DAYS:
        reasons.append(_flag("STALE_BASELINE", f"the valuation is from {base_as_of.isoformat()}, over 15 months ago"))
    evidence = _evidence(params.get("evidence"))
    ledger = {e.get("id"): e for e in base_line.get("ledger") or [] if isinstance(e, dict)}
    for ev in evidence:
        if ev["finding"] != "contradicts":
            continue
        entry = ledger.get(ev["belief"])
        if entry is not None and entry.get("stakes") == "high":
            reasons.append(_flag("HIGH_STAKES_CONTRADICTED", f"{ev['belief']} ({entry.get('headline') or entry.get('belief')}): {ev['claim']} ({ev['source']}, {ev['date']})"))
        if ev["belief"].startswith(f"must:{central}:"):
            reasons.append(_flag("CENTRAL_CONDITION_CONTRADICTED", f"a condition of the central scenario: {ev['claim']} ({ev['source']}, {ev['date']})"))
    rerun = status == "outside" or any(r["code"] != "OUTSIDE_SCENARIOS" for r in reasons)
    if status == "no_new_data":
        rerun = any(r["code"] in ("STALE_BASELINE", "HIGH_STAKES_CONTRADICTED", "CENTRAL_CONDITION_CONTRADICTED") for r in reasons)

    irr = _irrs(model, price, flags)
    base_irr = {s.get("name"): s.get("irr") for s in ((base_line.get("returns") or {}).get("scenarios") or [])}
    return {
        "mode": "deep", "status": status, "central": central, "nearest": nearest, "rerun_deep": rerun, "reasons": reasons,
        "elapsed_years": round(f, 3), "metrics": metrics,
        "scenarios": [{"name": s["name"], "distance": round(dist[s["name"]], 2), "value_per_share": s.get("value_per_share"),
                       "irr": irr.get(s["name"]), "baseline_irr": base_irr.get(s["name"])} for s in scen],
        "price": _price_block(scen, price, model.get("price"), price_levels(model)),
        "watch": _watch(scen, [central, nearest], list(ledger.values())), "evidence": evidence, "flags": flags,
    }


def run_light(params: dict) -> dict:
    base_line = params.get("baseline") or {}
    at = base_line.get("metrics_at_pick")
    fv = base_line.get("fair_values")
    if not isinstance(at, dict) or not isinstance(fv, dict):
        raise ValueError("baseline needs metrics_at_pick and fair_values")
    now = params.get("actuals") or {}
    price = _num(params.get("price"), "price")
    bear, mid, bull = (_num(fv.get(k), f"fair_values.{k}") for k in ("bear", "base", "bull"))
    flags: list[dict] = []
    reasons: list[dict] = []
    metrics = {}
    for name in ("revenue_growth", "operating_margin"):
        a, b = _opt(at.get(name), f"metrics_at_pick.{name}"), _opt(now.get(name), f"actuals.{name}")
        if a is None or b is None:
            if name == "operating_margin":
                flags.append(_flag("NO_OPERATING_INCOME", "operating margin unavailable at pick or now; compared on growth only"))
            else:
                raise ValueError("revenue_growth is needed at pick and now")
            continue
        metrics[name] = {"at_pick": _r(a), "now": _r(b), "change": _r(b - a)}
    same = _date(now.get("period_end"), "actuals.period_end") <= _date(at.get("period_end"), "metrics_at_pick.period_end")
    if not same:
        if metrics["revenue_growth"]["change"] < -LIGHT_GROWTH_DROP:
            reasons.append(_flag("GROWTH_FELL", f"revenue growth fell {abs(metrics['revenue_growth']['change']):.1%} since the pick"))
        if "operating_margin" in metrics and metrics["operating_margin"]["change"] < -LIGHT_MARGIN_DROP:
            reasons.append(_flag("MARGIN_FELL", f"operating margin fell {abs(metrics['operating_margin']['change']):.1%} since the pick"))
    status = "no_new_data" if same else "weakening" if reasons else "on_track"
    pos = "below_bear" if price < bear else "bear_base" if price < mid else "base_bull" if price <= bull else "above_bull"
    levels = light_levels(fv)
    return {"mode": "light", "status": status, "deep_review": status == "weakening", "reasons": reasons, "metrics": metrics,
            "price": {"price": price, "position": pos, "fair_values": {"bear": bear, "base": mid, "bull": bull},
                      "level": price_level(price, levels), "levels": levels}, "flags": flags}


def light_levels(fair_values: dict) -> dict:
    """A light pick's levels: bear, base and bull fair values as worst, central and best; no hurdle price."""
    return {"worst": float(fair_values["bear"]), "central": float(fair_values["base"]), "best": float(fair_values["bull"]), "hurdle": None}


def run_track(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    mode = params.get("mode")
    if mode == "deep":
        return run_deep(params)
    if mode == "light":
        return run_light(params)
    raise ValueError("mode must be deep or light")


def main() -> None:
    try:
        params = json.load(sys.stdin)
        out = run_track(params)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(2)
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
