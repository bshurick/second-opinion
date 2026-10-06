# Deep Valuation Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the valuation skill a deep mode. In it, subagents research a company's filings and news, keep a sourced belief ledger, chase contested beliefs, and feed a segment-by-segment scenario engine. The engine reports a value per share and an annualized return at today's price for each named scenario.

**Architecture:** There are three new pure scripts in `skills/valuation/scripts/`:

- `model.py`: a driver-based engine for segments and scenarios
- `returns.py`: IRR at today's price
- `render_deep.py`: a block-based page

`SKILL.md` gains a Deep case that coordinates Agent-tool subagents through a case folder. The role briefs live in one reference file. Quick mode gains a returns row.

**Tech Stack:** Python 3 standard library only (as `dcf.py`); `second_opinion.page` / `output` / `errors` for the page script; pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-deep-valuation-design.md`

## Global Constraints

- Scripts:
  - start with a docstring that describes stdin or starts with `Usage:`
  - have a `if __name__ == "__main__":` guard
  - are executable (`chmod +x`)
- Pure-math scripts print `{"error": "..."}` and exit 2 on invalid input.
- `SKILL.md`:
  - keeps the headings opening line / Background / Scripts / Steps / Reply format / Rules, in that order
  - stays at or under 500 lines
  - has a description at or under 260 characters, containing "Use when" and no ": "
  - has no prose line over 400 characters
- Commands in `SKILL.md` start `"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/`.
- Reference files:
  - each new one is registered in `REFERENCE_FILES` in `tests/test_skills_structure.py`
  - one over 100 lines starts with `## Contents` naming every `##` section
- These words never appear in new prose, page text, or reference files: "recommend", "advise", "should", "suggest" (or their stems).
- Pages:
  - every visible card has authored `FA.help`
  - every card or section in BODY opens with `<p class="sub">`
  - Flags sections use `page.FLAGS_INTRO`
- There is no probability weighting anywhere.

## Review Focus

1. **A Gordon terminal growth at or above a segment's discount rate**, including in a sensitivity cell. The input is exit 2, and the grid cell is null, not a crash. *Test: Task 2 `test_model_sensitivity_null_cell`.*
2. **A scenario override that names a segment that doesn't exist** (an agent typo). Expected: exit 2 naming it. *Test: Task 2 `test_model_override_unknown_segment`.*
3. **Every distribution is zero and the exit value is negative** (a distressed scenario). Expected: `irr` −1 with `TOTAL_LOSS`, not a bisection failure. *Test: Task 3 `test_returns_total_loss`.*
4. **A ledger claim missing its `date`** (an agent skipped the citation rule). Expected: `render_deep.py` exits 2 naming the belief id. *Test: Task 4 `test_render_deep_rejects_undated_claim`.*
5. **A per-year list of the wrong length** (`growth` with 5 entries when `years` is 10). Expected: exit 2 naming the field. *Test: Task 1 `test_model_rejects_wrong_length_path`.*

---

### Task 1: `model.py` — segment kinds, bridge, validation

**Files:**
- Create: `skills/valuation/scripts/model.py`
- Test: `tests/test_scripts_valuation_deep.py`

**Interfaces:**
- Produces: `run_model(params: dict) -> dict` (raises `ValueError`) and `main()` (stdin → stdout, exit 2 on error).
- Produces: the output keys `scenarios[].{name, summary, must_be_true, enterprise_value, equity_value, value_per_share, value_ex_premiums, upside, segments[], bridge, path[], exit{dcf_roll, multiple}}`, `sensitivity`, `returns_input`, `flags`. Tasks 3 and 4 consume these.

- [ ] **Step 1: Write the failing tests**

```python
"""Deep-valuation scripts: model.py (segment/scenario engine), returns.py (IRR at today's price),
render_deep.py (block page)."""

from __future__ import annotations

import io
import json
import sys

import pytest
from scripts_util import load_script


def run_stdin(rel: str, payload: dict, capsys, monkeypatch) -> dict:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script(rel).main()
    return json.loads(capsys.readouterr().out)


def run_stdin_error(rel: str, payload: dict, capsys, monkeypatch) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as excinfo:
        load_script(rel).main()
    return excinfo.value.code, json.loads(capsys.readouterr().out)


MODEL = "valuation/scripts/model.py"


def base_input(**over) -> dict:
    p = {
        "symbol": "ACME", "price": 20.0, "shares_outstanding": 100.0, "years": 10, "horizon": 5,
        "base_discount_rate": 0.09, "tax_rate": 0.25, "cost_of_debt": 0.05,
        "claims": {"debt": 300.0, "cash": 100.0},
        "payout": 0.5,
        "segments": [{"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.05,
                      "margin": 0.15, "sales_to_capital": 2.0,
                      "terminal": {"method": "gordon", "growth": 0.02}}],
        "scenarios": [{"name": "Base", "summary": "Steady.", "must_be_true": ["Margin holds"]}],
    }
    p.update(over)
    return p


def closed_form_operating(rev0, g, m, s2c, tax, r, tg, n):
    pv, rev = 0.0, rev0
    for t in range(1, n + 1):
        new = rev * (1 + g)
        pv += (new * m * (1 - tax) - (new - rev) / s2c) / (1 + r) ** t
        rev = new
    nxt = rev * (1 + tg)
    tv = (nxt * m * (1 - tax) - (nxt - rev) / s2c) / (r - tg)
    return pv + tv / (1 + r) ** n


def test_model_single_operating_segment_matches_closed_form(capsys, monkeypatch) -> None:
    out = run_stdin(MODEL, base_input(), capsys, monkeypatch)
    ev = closed_form_operating(1000, 0.05, 0.15, 2.0, 0.25, 0.09, 0.02, 10)
    sc = out["scenarios"][0]
    assert sc["enterprise_value"] == pytest.approx(ev, abs=0.01)
    assert sc["equity_value"] == pytest.approx(ev - 300 + 100, abs=0.01)
    assert sc["value_per_share"] == pytest.approx((ev - 200) / 100, abs=0.01)
    assert sc["upside"] == pytest.approx(((ev - 200) / 100) / 20 - 1, abs=1e-4)
    seg = sc["segments"][0]
    assert seg["discount_rate"] == 0.09 and len(seg["years"]) == 10
    assert 0 < seg["terminal_share"] < 1


def test_model_exit_multiple_terminal(capsys, monkeypatch) -> None:
    seg = {"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.0, "margin": 0.10,
           "sales_to_capital": 2.0, "da_pct_revenue": 0.05,
           "terminal": {"method": "multiple", "metric": "ebitda", "multiple": 8}}
    out = run_stdin(MODEL, base_input(segments=[seg]), capsys, monkeypatch)
    # flat revenue: no reinvestment; FCFF = 1000*0.10*0.75 = 75 each year; TV = 8 * (100 + 50)
    pv = sum(75 / 1.09**t for t in range(1, 11)) + 8 * 150 / 1.09**10
    assert out["scenarios"][0]["enterprise_value"] == pytest.approx(pv, abs=0.01)


def test_model_cost_asset_venture_add_as_stated(capsys, monkeypatch) -> None:
    core = base_input()["segments"][0]
    extra = [
        {"name": "HQ", "kind": "cost", "cost0": 10.0, "growth": 0.0, "terminal_growth": 0.0},
        {"name": "Stake", "kind": "asset", "value": 50.0},
        {"name": "Moonshot", "kind": "venture", "value_if_success": 400.0, "probability": 0.25, "cost_pv": 30.0},
    ]
    alone = run_stdin(MODEL, base_input(), capsys, monkeypatch)["scenarios"][0]["enterprise_value"]
    out = run_stdin(MODEL, base_input(segments=[core, *extra]), capsys, monkeypatch)
    hq = -10 / 0.09  # flat perpetuity: 10 years explicit + Gordon at 0 growth == 10 / r
    assert out["scenarios"][0]["enterprise_value"] == pytest.approx(alone + hq + 50 + (0.25 * 400 - 30), abs=0.02)


def test_model_residual_income_segment(capsys, monkeypatch) -> None:
    bank = {"name": "Bank", "kind": "residual_income", "book0": 1000.0, "roe": 0.12, "retention": 0.5,
            "cost_of_equity": 0.10, "terminal_growth": 0.03}
    out = run_stdin(MODEL, base_input(segments=[bank], claims={}, years=6, horizon=5), capsys, monkeypatch)
    book, pv = 1000.0, 0.0
    for t in range(1, 7):
        pv += (0.12 - 0.10) * book / 1.10**t
        book *= 1 + 0.12 * 0.5
    tv = (0.12 - 0.10) * book / (0.10 - 0.03) / 1.10**6
    sc = out["scenarios"][0]
    assert sc["enterprise_value"] == 0
    assert sc["equity_value"] == pytest.approx(1000 + pv + tv, abs=0.01)


def test_model_rejects_wrong_length_path(capsys, monkeypatch) -> None:
    p = base_input()
    p["segments"][0]["growth"] = [0.05] * 5
    rc, out = run_stdin_error(MODEL, p, capsys, monkeypatch)
    assert rc == 2 and "Core.growth" in out["error"] and "10" in out["error"]


@pytest.mark.parametrize("patch, needle", [
    ({"shares_outstanding": 0}, "shares_outstanding"),
    ({"years": 5, "horizon": 5}, "years"),
    ({"segments": []}, "segments"),
    ({"segments": [{"name": "X", "kind": "magic"}]}, "kind"),
    ({"payout": 1.5}, "payout"),
])
def test_model_validation(patch, needle, capsys, monkeypatch) -> None:
    rc, out = run_stdin_error(MODEL, base_input(**patch), capsys, monkeypatch)
    assert rc == 2 and needle in out["error"]


def test_model_gordon_growth_at_rate_is_rejected(capsys, monkeypatch) -> None:
    p = base_input()
    p["segments"][0]["terminal"] = {"method": "gordon", "growth": 0.09}
    rc, out = run_stdin_error(MODEL, p, capsys, monkeypatch)
    assert rc == 2 and "terminal growth" in out["error"]
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `pytest tests/test_scripts_valuation_deep.py -v`
Expected: FAIL (`model.py` not found).

- [ ] **Step 3: Write `model.py`**

````python
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
     "payout": 0.6,                 # share of positive FCFE paid out (dividends + buybacks), 0..1
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
year), discount_premium, terminal_growth, terminal_multiple, sales_to_capital (set); a cell whose
inputs are invalid is null. Flags: TERMINAL_HEAVY (a segment > 75% terminal), NEGATIVE_EQUITY,
MARGIN_ABOVE_HISTORY, REINVESTMENT_NEGATIVE.
"""

from __future__ import annotations

import copy
import json
import math
import sys

KINDS = ("operating", "cost", "asset", "venture", "residual_income")
CLAIMS = ("debt", "cash", "leases", "minority_interest", "pension_deficit", "preferred", "options")
OTHER_CLAIMS = ("minority_interest", "pension_deficit", "preferred", "options")
SENS_FIELDS = ("growth_shift", "margin_shift", "discount_premium", "terminal_growth", "terminal_multiple", "sales_to_capital")
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
        rows.append({"t": t, "book_start": book, "earnings": earn, "residual_income": (roe[t - 1] - ke) * book, "dividends": earn * (1 - ret[t - 1])})
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
    seg = next(s for s in segs if s["name"] == spec["segment"])
    f = spec["field"]
    if f == "growth_shift":
        seg["growth"] = [x + v for x in _path(seg["growth"], years, "growth")]
    elif f == "margin_shift":
        seg["margin"] = [x + v for x in _path(seg["margin"], years, "margin")]
    elif f == "terminal_growth":
        seg["terminal"] = {**seg["terminal"], "growth": v}
    elif f == "terminal_multiple":
        seg["terminal"] = {**seg["terminal"], "multiple": v}
    else:
        seg[f] = v
    return segs


def _exit_multiple(em: dict, vals: list[dict], h: int, fcfe_h: float, nd_h: float, other: float, ri_h: float, shares_h: float, tax: float) -> float:
    metric = em.get("metric")
    mult = _num(em.get("multiple"), "exit_multiple.multiple")
    if metric not in EXIT_METRICS:
        raise ValueError("exit_multiple.metric must be ebit, ebitda, revenue or fcfe")
    if metric == "fcfe":
        return mult * fcfe_h / shares_h
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
    for sc in scenarios:
        payout = _num(sc.get("payout", params.get("payout", 0.0)), "payout")
        if not 0 <= payout <= 1:
            raise ValueError("payout must be between 0 and 1")
        dil = _num(sc.get("annual_dilution", params.get("annual_dilution", 0.0)), "annual_dilution")
        if dil <= -1:
            raise ValueError("annual_dilution must be above -1")
        claims = _claims({**(params.get("claims") or {}), **(sc.get("claims") or {})})
        s_segs = _resolve(segs, sc)
        resolved[sc["name"]] = (s_segs, claims)
        vals, ev, equity, vps = _value(s_segs, ctx, claims, shares)
        _, _, _, vps_ex = _value(s_segs, ctx, claims, shares, zero_premium=True)
        # path to the horizon
        nd = claims["debt"] - claims["cash"] + claims["leases"]
        other = sum(claims[k] for k in OTHER_CLAIMS)
        sh, path, fcfe = shares, [], 0.0
        for t in range(1, horizon + 1):
            ops_flow = sum(v["flows"][t - 1] for v in vals)
            fcfe = ops_flow - cod * (1 - tax) * nd
            dist = payout * max(fcfe, 0.0)
            nd -= fcfe - dist
            sh *= 1 + dil
            path.append({"t": t, "fcfe": round(fcfe, 2), "distributions_per_share": round(dist / sh, 4), "net_debt": round(nd, 2), "shares": round(sh, 4)})
        ev_h = sum(v["value_at_h"] for v in vals if v["kind"] != "residual_income")
        ri_h = sum(v["value_at_h"] for v in vals if v["kind"] == "residual_income")
        roll = (ev_h - nd - other + ri_h) / sh
        em = sc.get("exit_multiple")
        mult_exit = _exit_multiple(em, vals, horizon, fcfe, nd, other, ri_h, sh, tax) if em else None
        for v in vals:
            if v["kind"] == "operating" and v["terminal_share"] is not None and v["terminal_share"] > TERMINAL_HEAVY:
                flag("TERMINAL_HEAVY", f"{sc['name']}: {v['name']} gets {v['terminal_share']:.0%} of its value from the years after the forecast.")
            if v["kind"] == "operating" and any(r["reinvestment"] < 0 for r in v["rows"]):
                flag("REINVESTMENT_NEGATIVE", f"{sc['name']}: {v['name']} shrinks, so the model releases capital back as cash.")
            cap = (history.get(v["name"]) or {}).get("max_margin")
            if v["kind"] == "operating" and cap is not None and any(r["revenue"] and r["ebit"] / r["revenue"] > float(cap) for r in v["rows"]):
                flag("MARGIN_ABOVE_HISTORY", f"{sc['name']}: {v['name']} margin exceeds its historical best of {float(cap):.1%}.")
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

    sens = None
    spec = params.get("sensitivity")
    if spec:
        sname = spec.get("scenario") or results[0]["name"]
        if sname not in resolved:
            raise ValueError(f"sensitivity.scenario {sname!r} is not a scenario")
        for axis in ("a", "b"):
            ax = spec.get(axis) or {}
            if ax.get("segment") not in names or ax.get("field") not in SENS_FIELDS or not isinstance(ax.get("values"), list) or not ax["values"]:
                raise ValueError(f"sensitivity.{axis} needs a segment, a field in {', '.join(SENS_FIELDS)} and values")
        s_segs, claims = resolved[sname]
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
        sens = {"scenario": sname, "a": spec["a"], "b": spec["b"], "value_per_share": grid}

    return {
        "symbol": params.get("symbol"), "price": price, "horizon": horizon, "scenarios": results, "sensitivity": sens,
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
````

Then `chmod +x skills/valuation/scripts/model.py`.

- [ ] **Step 4: Run the tests and check they pass**

Run: `pytest tests/test_scripts_valuation_deep.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/valuation/scripts/model.py tests/test_scripts_valuation_deep.py
git commit -m "feat(valuation): model.py segment-by-segment scenario engine"
```

### Task 2: `model.py` — scenarios, path, exit, sensitivity

**Files:**
- Test: `tests/test_scripts_valuation_deep.py` (append)
- Modify: `skills/valuation/scripts/model.py`, only if a test exposes a defect

**Interfaces:**
- Consumes: `run_model`, `base_input`, `run_stdin`, `run_stdin_error` from Task 1.

- [ ] **Step 1: Write the tests**

```python
def test_model_overrides_change_only_named_fields(capsys, monkeypatch) -> None:
    p = base_input(scenarios=[{"name": "Base"}, {"name": "Squeeze", "overrides": {"Core": {"margin": 0.10}}}])
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    base, sq = out["scenarios"]
    assert base["segments"][0]["years"][0]["revenue"] == sq["segments"][0]["years"][0]["revenue"]
    assert sq["segments"][0]["years"][0]["ebit"] == pytest.approx(1050 * 0.10, abs=0.01)
    assert sq["value_per_share"] < base["value_per_share"]


def test_model_override_unknown_segment(capsys, monkeypatch) -> None:
    p = base_input(scenarios=[{"name": "X", "overrides": {"Cor": {"margin": 0.1}}}])
    rc, out = run_stdin_error(MODEL, p, capsys, monkeypatch)
    assert rc == 2 and "'Cor'" in out["error"]


def test_model_fails_truncates_and_adds_salvage(capsys, monkeypatch) -> None:
    p = base_input(claims={}, scenarios=[{"name": "Dies", "overrides": {"Core": {"fails": {"year": 3, "salvage": 100.0}}}}])
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    pv = 0.0
    rev = 1000.0
    for t in (1, 2):
        new = rev * 1.05
        pv += (new * 0.15 * 0.75 - (new - rev) / 2.0) / 1.09**t
        rev = new
    pv += 100 / 1.09**3
    assert out["scenarios"][0]["enterprise_value"] == pytest.approx(pv, abs=0.01)


def test_model_value_ex_premiums(capsys, monkeypatch) -> None:
    p = base_input()
    p["segments"][0].update(discount_premium=0.03, premium_reason="vague plan")
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    plain = run_stdin(MODEL, base_input(), capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert sc["segments"][0]["discount_rate"] == 0.12 and sc["segments"][0]["premium_reason"] == "vague plan"
    assert sc["value_ex_premiums"] == plain["scenarios"][0]["value_per_share"]
    assert sc["value_per_share"] < sc["value_ex_premiums"]


def test_model_path_and_roll_exit(capsys, monkeypatch) -> None:
    # no debt, payout 1, no growth: FCFE = FCFF = 112.5 each year, all distributed, exit = value at H
    seg = {"name": "Core", "kind": "operating", "revenue0": 1000.0, "growth": 0.0, "margin": 0.15,
           "sales_to_capital": 2.0, "terminal": {"method": "gordon", "growth": 0.0}}
    out = run_stdin(MODEL, base_input(segments=[seg], claims={}, payout=1.0), capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert all(p["distributions_per_share"] == pytest.approx(1.125) for p in sc["path"])
    assert sc["exit"]["dcf_roll"] == pytest.approx(112.5 / 0.09 / 100, abs=0.01)
    assert sc["value_per_share"] == pytest.approx(112.5 / 0.09 / 100, abs=0.01)
    ri = out["returns_input"]
    assert ri["mode"] == "paths" and ri["horizon"] == 5 and ri["scenarios"][0]["exit_value_per_share"] == sc["exit"]["dcf_roll"]


def test_model_retained_cash_lowers_net_debt(capsys, monkeypatch) -> None:
    out = run_stdin(MODEL, base_input(payout=0.0), capsys, monkeypatch)
    nd = [p["net_debt"] for p in out["scenarios"][0]["path"]]
    assert nd[0] < 200 and all(b < a for a, b in zip(nd, nd[1:]))


def test_model_exit_multiple(capsys, monkeypatch) -> None:
    p = base_input(claims={}, scenarios=[{"name": "Base", "exit_multiple": {"metric": "ebit", "multiple": 10}}])
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    sc = out["scenarios"][0]
    ebit5 = 1000 * 1.05**5 * 0.15
    nd5 = sc["path"][-1]["net_debt"]
    assert sc["exit"]["multiple"] == pytest.approx((10 * ebit5 - nd5) / 100, abs=0.01)


def test_model_sensitivity_centre_equals_scenario(capsys, monkeypatch) -> None:
    p = base_input(sensitivity={"a": {"segment": "Core", "field": "margin_shift", "values": [-0.01, 0, 0.01]},
                                "b": {"segment": "Core", "field": "discount_premium", "values": [0, 0.02]}})
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    grid = out["sensitivity"]["value_per_share"]
    assert grid[1][0] == out["scenarios"][0]["value_per_share"]
    assert grid[2][0] > grid[1][0] > grid[0][0] and grid[1][1] < grid[1][0]


def test_model_sensitivity_null_cell(capsys, monkeypatch) -> None:
    p = base_input(sensitivity={"a": {"segment": "Core", "field": "terminal_growth", "values": [0.02, 0.10]},
                                "b": {"segment": "Core", "field": "discount_premium", "values": [0]}})
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    assert out["sensitivity"]["value_per_share"][1] == [None]


def test_model_flags(capsys, monkeypatch) -> None:
    p = base_input(history={"Core": {"max_margin": 0.12}}, claims={"debt": 1e6})
    p["segments"][0]["terminal"]["growth"] = 0.08
    out = run_stdin(MODEL, p, capsys, monkeypatch)
    codes = {f["code"] for f in out["flags"]}
    assert {"TERMINAL_HEAVY", "MARGIN_ABOVE_HISTORY", "NEGATIVE_EQUITY"} <= codes
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_scripts_valuation_deep.py -v`
Expected: PASS. Task 1's code implements all of this. If any test fails, fix `model.py` (not the test) unless the test's arithmetic is wrong. If the test is wrong, correct it and state why in the commit.

- [ ] **Step 3: Commit**

```bash
git add tests/test_scripts_valuation_deep.py skills/valuation/scripts/model.py
git commit -m "test(valuation): model.py scenarios, path, exit and sensitivity"
```

### Task 3: `returns.py`

**Files:**
- Create: `skills/valuation/scripts/returns.py`
- Test: `tests/test_scripts_valuation_deep.py` (append)

**Interfaces:**
- Consumes: `model.py`'s `returns_input` (`{"mode":"paths","price","horizon","hurdle","scenarios":[{"name","distributions_per_share","exit_value_per_share","exit_multiple_value"}]}`).
- Produces: `{"mode","price","horizon","hurdle","scenarios":[{"name","irr","irr_at_multiple","total_multiple","hurdle_exit_value","exit_value_per_share","distributions_total"}],"assumptions":[str],"flags":[{"code","message"}]}`. Tasks 4 and 5 consume this.

- [ ] **Step 1: Write the failing tests**

```python
RETURNS = "valuation/scripts/returns.py"


def test_returns_known_irr(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "paths", "price": 100, "horizon": 5, "hurdle": 0.10,
                              "scenarios": [{"name": "A", "distributions_per_share": [0] * 5, "exit_value_per_share": 161.051}]}, capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert sc["irr"] == pytest.approx(0.10, abs=1e-5)
    assert sc["total_multiple"] == pytest.approx(1.6105, abs=1e-4)
    assert sc["hurdle_exit_value"] == pytest.approx(161.05, abs=0.01)


def test_returns_hurdle_round_trip_with_distributions(capsys, monkeypatch) -> None:
    p = {"mode": "paths", "price": 50, "horizon": 3, "hurdle": 0.12,
         "scenarios": [{"name": "A", "distributions_per_share": [2, 2, 2], "exit_value_per_share": 40}]}
    hev = run_stdin(RETURNS, p, capsys, monkeypatch)["scenarios"][0]["hurdle_exit_value"]
    p["scenarios"][0]["exit_value_per_share"] = hev
    assert run_stdin(RETURNS, p, capsys, monkeypatch)["scenarios"][0]["irr"] == pytest.approx(0.12, abs=1e-4)


def test_returns_irr_at_multiple(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "paths", "price": 100, "horizon": 1, "scenarios": [
        {"name": "A", "distributions_per_share": [0], "exit_value_per_share": 110, "exit_multiple_value": 120}]}, capsys, monkeypatch)
    sc = out["scenarios"][0]
    assert sc["irr"] == pytest.approx(0.10, abs=1e-5) and sc["irr_at_multiple"] == pytest.approx(0.20, abs=1e-5)


def test_returns_convergence_at_fair_price_earns_cost_of_equity(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "convergence", "price": 40, "horizon": 5, "scenarios": [
        {"name": "Base", "fair_value": 40, "cost_of_equity": 0.09, "dividend_yield": 0.0},
        {"name": "Div", "fair_value": 40, "cost_of_equity": 0.09, "dividend_yield": 0.03}]}, capsys, monkeypatch)
    assert out["scenarios"][0]["irr"] == pytest.approx(0.09, abs=1e-5)
    assert out["scenarios"][1]["irr"] == pytest.approx(0.09, abs=1e-5)
    assert out["assumptions"]


def test_returns_convergence_cheap_stock_beats_cost_of_equity(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "convergence", "price": 30, "horizon": 5, "scenarios": [
        {"name": "Base", "fair_value": 40, "cost_of_equity": 0.09, "dividend_yield": 0.0}]}, capsys, monkeypatch)
    assert out["scenarios"][0]["irr"] == pytest.approx((40 * 1.09**5 / 30) ** 0.2 - 1, abs=1e-5)


def test_returns_total_loss(capsys, monkeypatch) -> None:
    out = run_stdin(RETURNS, {"mode": "paths", "price": 10, "horizon": 3, "scenarios": [
        {"name": "Bust", "distributions_per_share": [0, 0, 0], "exit_value_per_share": -4}]}, capsys, monkeypatch)
    assert out["scenarios"][0]["irr"] == -1.0 and out["flags"][0]["code"] == "TOTAL_LOSS"


@pytest.mark.parametrize("payload, needle", [
    ({"mode": "paths", "price": 0, "horizon": 5, "scenarios": []}, "price"),
    ({"mode": "x", "price": 10, "horizon": 5, "scenarios": []}, "mode"),
    ({"mode": "paths", "price": 10, "horizon": 2, "scenarios": [{"name": "A", "distributions_per_share": [1], "exit_value_per_share": 1}]}, "distributions_per_share"),
])
def test_returns_validation(payload, needle, capsys, monkeypatch) -> None:
    rc, out = run_stdin_error(RETURNS, payload, capsys, monkeypatch)
    assert rc == 2 and needle in out["error"]


def test_model_pipes_into_returns(capsys, monkeypatch) -> None:
    ri = run_stdin(MODEL, base_input(), capsys, monkeypatch)["returns_input"]
    out = run_stdin(RETURNS, ri, capsys, monkeypatch)
    assert out["scenarios"][0]["name"] == "Base" and out["scenarios"][0]["irr"] is not None
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `pytest tests/test_scripts_valuation_deep.py -k returns -v`
Expected: FAIL (`returns.py` not found).

- [ ] **Step 3: Write `returns.py`**

```python
#!/usr/bin/env python3
"""Annualized return at today's price for each valuation scenario (stdin -> stdout JSON).

    python returns.py < input.json

Exit 0 with the result, or exit 2 with ``{"error": "..."}``. Pure arithmetic. Two modes:

``paths`` (model.py's ``returns_input``)::

    {"mode": "paths", "price": 50, "horizon": 5, "hurdle": 0.10,
     "scenarios": [{"name", "distributions_per_share": [one per year], "exit_value_per_share",
                    "exit_multiple_value": null}]}

``convergence`` (quick mode, from a dcf.py fair value)::

    {"mode": "convergence", "price": 50, "horizon": 5, "hurdle": 0.10,
     "scenarios": [{"name", "fair_value", "cost_of_equity", "dividend_yield"}]}

The price closes on fair value by the horizon; fair value compounds at cost_of_equity -
dividend_yield and pays dividend_yield on the prior year's value, so buying at fair value earns the
cost of equity exactly.

Output: {"mode", "price", "horizon", "hurdle", "scenarios": [{"name", "irr", "irr_at_multiple",
"total_multiple", "hurdle_exit_value", "exit_value_per_share", "distributions_total"}],
"assumptions": [...], "flags": [{"code", "message"}]}. ``irr`` solves price = sum of discounted
distributions + discounted exit by bisection on [-0.99, 5]; null when no rate in that range does.
``hurdle_exit_value`` is the exit value per share that earns exactly the hurdle. When the exit plus
distributions is not positive, ``irr`` is -1 and TOTAL_LOSS is flagged.
"""

from __future__ import annotations

import json
import math
import sys

_LOW, _HIGH, _ITER = -0.99, 5.0, 200


def _num(v: object, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


def _npv(rate: float, price: float, dists: list[float], exit_v: float) -> float:
    h = len(dists)
    return sum(d / (1 + rate) ** t for t, d in enumerate(dists, start=1)) + exit_v / (1 + rate) ** h - price


def _irr(price: float, dists: list[float], exit_v: float) -> float | None:
    lo, hi = _LOW, _HIGH
    f_lo, f_hi = _npv(lo, price, dists, exit_v), _npv(hi, price, dists, exit_v)
    if f_lo * f_hi > 0:
        return None
    for _ in range(_ITER):
        mid = (lo + hi) / 2
        f_mid = _npv(mid, price, dists, exit_v)
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return round((lo + hi) / 2, 6)


def run_returns(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    mode = params.get("mode")
    if mode not in ("paths", "convergence"):
        raise ValueError("mode must be paths or convergence")
    price = _num(params.get("price"), "price")
    if price <= 0:
        raise ValueError("price must be positive")
    h = params.get("horizon")
    if isinstance(h, bool) or not isinstance(h, (int, float)) or int(h) != h or h < 1:
        raise ValueError("horizon must be a positive integer")
    h = int(h)
    hurdle = _num(params.get("hurdle", 0.10), "hurdle")
    scenarios = params.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("scenarios must be a list")
    assumptions = [f"Bought at {price:g} today and held {h} years; distributions arrive at each year end."]
    if mode == "convergence":
        assumptions.append("The price closes on fair value by the horizon; fair value compounds at the cost of equity less the dividend yield.")
    else:
        assumptions.append("Distributions are dividends plus buybacks from the model's free cash flow to equity; the exit value is the model's value at the horizon.")
    out, flags = [], []
    for i, sc in enumerate(scenarios):
        name = sc.get("name") or f"#{i + 1}"
        mult_v = None
        if mode == "paths":
            dists = sc.get("distributions_per_share")
            if not isinstance(dists, list) or len(dists) != h:
                raise ValueError(f"{name}: distributions_per_share must have {h} entries")
            dists = [_num(d, f"{name}.distributions_per_share") for d in dists]
            exit_v = _num(sc.get("exit_value_per_share"), f"{name}.exit_value_per_share")
            if sc.get("exit_multiple_value") is not None:
                mult_v = _num(sc["exit_multiple_value"], f"{name}.exit_multiple_value")
        else:
            fv = _num(sc.get("fair_value"), f"{name}.fair_value")
            ke = _num(sc.get("cost_of_equity"), f"{name}.cost_of_equity")
            y = _num(sc.get("dividend_yield", 0.0), f"{name}.dividend_yield")
            vals = [fv * (1 + ke - y) ** t for t in range(h + 1)]
            dists = [y * vals[t - 1] for t in range(1, h + 1)]
            exit_v = vals[h]
        total = sum(dists) + exit_v
        if total <= 0:
            irr = -1.0
            flags.append({"code": "TOTAL_LOSS", "message": f"{name}: nothing comes back to the holder in this scenario."})
        else:
            irr = _irr(price, dists, exit_v)
        hurdle_exit = (price - sum(d / (1 + hurdle) ** t for t, d in enumerate(dists, start=1))) * (1 + hurdle) ** h
        out.append({
            "name": name, "irr": irr,
            "irr_at_multiple": _irr(price, dists, mult_v) if mult_v is not None and sum(dists) + mult_v > 0 else None,
            "total_multiple": round(total / price, 4), "hurdle_exit_value": round(hurdle_exit, 2),
            "exit_value_per_share": round(exit_v, 2), "distributions_total": round(sum(dists), 4),
        })
    return {"mode": mode, "price": price, "horizon": h, "hurdle": hurdle, "scenarios": out, "assumptions": assumptions, "flags": flags}


def main() -> None:
    try:
        result = run_returns(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
```

Then `chmod +x skills/valuation/scripts/returns.py`.

- [ ] **Step 4: Run the tests and check they pass**

Run: `pytest tests/test_scripts_valuation_deep.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/valuation/scripts/returns.py tests/test_scripts_valuation_deep.py
git commit -m "feat(valuation): returns.py annualized return per scenario at today's price"
```

### Task 4: `render_deep.py`

**Files:**
- Create: `skills/valuation/scripts/render_deep.py`
- Create: `docs/samples/valuation-deep.json` (a fixture used by the tests and the docs)
- Test: `tests/test_scripts_valuation_deep.py` (append)

**Interfaces:**
- Consumes: the `model.py` output (Task 1) and the `returns.py` output (Task 3).
- Produces: the CLI `render_deep.py [--in page.json] --out page.html`, printing `{"out","title","symbol","scenarios","blocks","flags"}`; `build(data) -> (title, markup, info)`.

- [ ] **Step 1: Write the fixture generator test and the failing tests**

The fixture is generated from the real scripts, so it never drifts from them. Add to the tests:

```python
from pathlib import Path

from scripts_util import PLUGIN_ROOT, run_json
from page_dom import assert_page_help, render_and_audit, requires_chrome

RENDER = "valuation/scripts/render_deep.py"
SAMPLE = PLUGIN_ROOT / "docs/samples/valuation-deep.json"


def page_input() -> dict:
    p = base_input(
        segments=[*base_input()["segments"], {"name": "HQ", "kind": "cost", "cost0": 10.0}],
        scenarios=[{"name": "Base", "summary": "Steady.", "must_be_true": ["Margin holds"]},
                   {"name": "Squeeze", "summary": "Pricing gives.", "must_be_true": ["Rivals cut price"],
                    "overrides": {"Core": {"margin": 0.10, "discount_premium": 0.02, "premium_reason": "guidance track record is poor"}}}],
        sensitivity={"a": {"segment": "Core", "field": "margin_shift", "values": [-0.02, 0, 0.02]},
                     "b": {"segment": "Core", "field": "discount_premium", "values": [0, 0.02]}})
    model = json.loads(json.dumps(load_script(MODEL).run_model(p)))
    rets = json.loads(json.dumps(load_script(RETURNS).run_returns(model["returns_input"])))
    ledger = [{"id": "B1", "belief": "Price increases stick", "holder": "management", "stakes": "high", "verdict": "doubtful",
               "for": [{"claim": "Q2 price up 4%", "source": "10-Q Item 2", "date": "2026-08-01"}],
               "against": [{"claim": "Volumes fell 6%", "source": "10-Q Item 2", "date": "2026-08-01"}],
               "consequence": {"segment": "Core", "field": "margin", "change": "10% in Squeeze"}, "thread": "threads/1-pricing.md"}]
    return {"symbol": "ACME", "price": 20.0, "as_of": "2026-10-05", "model": model, "returns": rets, "ledger": ledger,
            "blocks": [{"type": "segments", "scenario": "Base"}, {"type": "drivers", "segment": "Core", "field": "fcff"},
                       {"type": "ledger"}, {"type": "track_record", "rows": [{"period": "FY2025", "metric": "Revenue growth", "guided": "8%", "actual": "5%", "source": "8-K 2026-02-10"}]},
                       {"type": "forensics", "items": [{"finding": "Receivables up 20% vs revenue up 5%", "severity": "medium", "source": "10-K 2026-02-20"}]},
                       {"type": "skepticism"}, {"type": "sensitivity"},
                       {"type": "custom", "title": "Lease adjustment", "file": "custom/leases.py", "result": "12.3", "explanation": "Capitalized operating leases."},
                       {"type": "text", "title": "What the market may be missing", "markdown": "**Pricing** is the swing factor.\n\n- one\n- two"}],
            "missing_roles": ["industry"], "notes": ["Sample built from invented figures."]}


def test_render_deep_every_block(tmp_path, capsys, monkeypatch) -> None:
    data = page_input()
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 0, res
    assert res["scenarios"] == ["Base", "Squeeze"] and len(res["blocks"]) == 9 and res["flags"] >= 2
    html = (tmp_path / "p.html").read_text()
    assert "ACME" in html and "<script" in html


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["blocks"].append({"type": "chart3d"}), "chart3d"),
    (lambda d: d["blocks"].append({"type": "drivers", "segment": "Core"}), "field"),
    (lambda d: d["blocks"].append({"type": "drivers", "segment": "Nope", "field": "fcff"}), "Nope"),
    (lambda d: d.pop("model"), "model"),
])
def test_render_deep_rejects_bad_blocks(mutate, needle, tmp_path, capsys, monkeypatch) -> None:
    data = page_input()
    mutate(data)
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and needle in res["error"]


def test_render_deep_rejects_undated_claim(tmp_path, capsys, monkeypatch) -> None:
    data = page_input()
    del data["ledger"][0]["against"][0]["date"]
    src = tmp_path / "page.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 2 and "B1" in res["error"] and "date" in res["error"]


def test_render_deep_sample_is_current(capsys, monkeypatch) -> None:
    """docs/samples/valuation-deep.json is page_input() as committed; regenerate it when this fails."""
    assert json.loads(SAMPLE.read_text()) == page_input()


def test_render_deep_body_intros() -> None:
    import re
    body = load_script(RENDER).BODY
    for m in re.finditer(r'<section([^>]*)>\s*<h2[^>]*>(.*?)</h2>\s*(<p class="sub)?', body, re.S):
        assert m.group(3), f"section {m.group(2)!r} has no intro line"
    from second_opinion import page
    assert page.FLAGS_INTRO in body


@requires_chrome
def test_render_deep_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit(RENDER, ["--in", str(SAMPLE)], tmp_path, capsys)
    assert_page_help(a)
    shown = {c["h2"] for c in a["cards"] if not c["hidden"]}
    assert {"Scenarios", "Price against the scenarios", "Belief ledger"} <= shown
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `pytest tests/test_scripts_valuation_deep.py -k render -v`
Expected: FAIL (`render_deep.py` not found).

- [ ] **Step 3: Write `render_deep.py`**

```python
#!/usr/bin/env python3
"""Usage: render_deep.py [--in page.json] --out page.html

Turns a deep valuation (model.py output, returns.py output, the belief ledger and the blocks the
analyst picked) into one self-contained HTML page for the Artifact tool. Input::

    {"symbol": "ACME", "price": 50.0, "as_of": "2026-10-05",
     "model": <model.py output>, "returns": <returns.py output>,
     "ledger": [{"id", "belief", "holder", "stakes", "verdict", "for": [{"claim", "source", "date"}],
                 "against": [...], "consequence": {"segment", "field", "change"}, "thread"}],
     "blocks": [{"type": ...}, ...], "missing_roles": ["industry"], "notes": ["..."]}

Always shown first: the scenario table (value per share, upside, annualized return, total
multiple, what has to be true) and the price against each scenario's value. Then the blocks, in
order:

    segments {scenario}        value of each segment and the bridge to equity
    drivers {segment, field}   that segment's revenue | ebit | fcff by year, one line per scenario
    ledger                     the belief ledger with sourced evidence (needs "ledger")
    track_record {rows}        guidance against results: [{period, metric, guided, actual, source}]
    forensics {items}          accounting findings: [{finding, severity, source}]
    skepticism                 value with and without the discount-rate premiums, and their reasons
    sensitivity                model.py's two-way grid as a heatmap around the price
    custom {title, file, result, explanation}   a labelled calculation outside the engine
    text {title, markdown}     free text: paragraphs, "- " bullets and **bold** only

Every ledger claim needs a source and a date. Flags come from model.py, returns.py,
missing_roles and notes. Prints {"out", "title", "symbol", "scenarios", "blocks", "flags"}; exit 2
on a missing model, an unknown block, a block missing a field, or an undated claim. The page is a
fragment; nothing is fetched at runtime and every figure is the scripts' output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

BLOCK_FIELDS = {
    "segments": ("scenario",), "drivers": ("segment", "field"), "ledger": (), "track_record": ("rows",),
    "forensics": ("items",), "skepticism": (), "sensitivity": (), "custom": ("title", "file", "result", "explanation"),
    "text": ("title", "markdown"),
}
VERDICTS = ("supported", "doubtful", "contradicted", "unknowable", "open")

BODY = """
<style>
.verdict{font-size:11px;font-weight:600;letter-spacing:.04em;border-radius:4px;padding:2px 6px;border:1px solid var(--grid);text-transform:uppercase}
.verdict.supported{color:var(--ink);border-color:var(--ink2)}.verdict.doubtful,.verdict.contradicted{color:var(--warn);border-color:var(--warn)}
.verdict.unknowable,.verdict.open{color:var(--muted)}
.belief{border-bottom:1px solid var(--grid);padding:8px 0}.belief summary{cursor:pointer;display:flex;gap:10px;align-items:baseline;font-size:14px}
.belief .ev{display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;margin-top:8px}.belief .ev h3{font-size:12px;color:var(--muted);margin:0 0 4px}
.belief .src{color:var(--muted);font-size:12px}.belief .cq{font-size:13px;margin-top:6px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px;margin:0 0 10px}.kv dt{color:var(--muted)}.kv dd{margin:0}
.must{margin:0;padding-left:16px;font-size:12px;color:var(--muted)}
@media (max-width:640px){.belief .ev{grid-template-columns:1fr}}
</style>
<h1 id="h1">Deep valuation</h1>
<p class="sub" id="sub"></p>
<div id="intro"></div>
<section class="card" id="sc-card"><h2>Scenarios</h2><p class="sub">Each row is one possible future for the business, what a share is worth if it happens, and what buying at today’s price would earn a year.</p><div class="twrap" id="sc"></div></section>
<section class="card" id="strip-card"><h2>Price against the scenarios</h2><p class="sub">Where today’s price sits among the values the scenarios give.</p><div id="strip"></div></section>
<div id="blocks"></div>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Every value is the scripts’ output at the stated assumptions. Scenarios are possible futures, not forecasts, and carry no probabilities; the annualized return assumes the price reaches the scenario’s value at the horizon. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, M = D.model, R = D.returns || {scenarios: []};
  const g = id => document.getElementById(id), esc = F.esc, money = v => F.money(v), pct = v => F.pct(v, 1, true);
  const price = D.price, ret = Object.fromEntries((R.scenarios || []).map(s => [s.name, s]));
  const scs = M.scenarios;
  g('h1').textContent = `${D.symbol || ''} deep valuation`.trim();
  g('sub').textContent = `Price ${money(price)}${D.as_of ? ' · as of ' + D.as_of : ''} · ${scs.length} scenarios · ${M.horizon}-year horizon`;
  F.intro(g('intro'), {lead: `What one share of ${esc(D.symbol || 'this company')} could be worth under ${scs.length} different futures, built segment by segment from the company’s filings, and what buying at ${money(price)} would earn a year in each.`});

  F.table(g('sc'), [
    {key: 'name', label: 'Scenario', left: true, fmt: (v, r) => `<b>${esc(v)}</b><div class="muted" style="font-size:12px">${esc(r.summary)}</div>`},
    {key: 'value', label: 'Value / share', fmt: v => money(v)},
    {key: 'upside', label: 'vs price', fmt: v => F.isNum(v) ? pct(v) : '—'},
    {key: 'irr', label: `Return / yr (${M.horizon}y)`, fmt: v => F.isNum(v) ? pct(v) : '—'},
    {key: 'mult', label: 'Total multiple', fmt: v => F.isNum(v) ? F.num(v, 2) + '×' : '—'},
    {key: 'must', label: 'Has to be true', left: true, fmt: v => v.length ? `<ul class="must">${v.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '—'},
  ], scs.map(s => ({name: s.name, summary: s.summary, value: s.value_per_share, upside: s.upside, irr: (ret[s.name] || {}).irr, mult: (ret[s.name] || {}).total_multiple, must: s.must_be_true || []})), {sortKey: 'value'});
  F.help(g('sc-card'), {lead: 'One row per scenario: a named future for the business, the value of a share if it happens, and the yearly return from buying at today’s price and holding to the horizon.',
    sections: [{title: 'How the return is built', html: '<p>The return counts the cash paid to shareholders along the way (dividends and buybacks from the model’s free cash flow) and the value of a share at the horizon, against today’s price. The scenarios carry no probabilities: which future is likelier is the reader’s judgement.</p>'}]});

  // strip: one axis, a tick per scenario value and one for the price
  const vals = scs.map(s => s.value_per_share).concat([price]).filter(F.isNum);
  const lo = Math.min(...vals, 0), hi = Math.max(...vals) * 1.08, W = 960, H = 34 + 22 * scs.length;
  const X = v => 20 + (W - 160) * (v - lo) / ((hi - lo) || 1);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="price against scenario values"><line x1="20" x2="${W - 140}" y1="${H - 14}" y2="${H - 14}" stroke="var(--grid)"/>`;
  scs.forEach((s, i) => { const x = X(s.value_per_share), y = 14 + 22 * i; svg += `<line x1="${X(lo)}" x2="${x}" y1="${y}" y2="${y}" stroke="${F.S[i % 8]}" stroke-width="8" stroke-linecap="round" opacity=".8"/><text x="${x + 8}" y="${y + 4}" font-size="12" fill="var(--ink)">${esc(s.name)} ${esc(money(s.value_per_share))}</text>`; });
  svg += `<line x1="${X(price)}" x2="${X(price)}" y1="4" y2="${H - 8}" stroke="var(--ink)" stroke-dasharray="4 3"/><text x="${X(price)}" y="${H - 1}" font-size="11" text-anchor="middle" fill="var(--muted)">price ${esc(money(price))}</text></svg>`;
  g('strip').innerHTML = svg;
  F.help(g('strip-card'), {lead: 'Each bar runs to one scenario’s value per share; the dashed line is today’s price. Bars that end left of the line are futures in which the share is worth less than it costs.'});

  const card = (title, sub) => { const c = F.el('section', {class: 'card'}); c.innerHTML = `<h2>${esc(title)}</h2><p class="sub">${sub}</p>`; g('blocks').appendChild(c); const body = F.el('div'); c.appendChild(body); return [c, body]; };
  const byName = n => scs.find(s => s.name === n);
  const md = t => esc(t).split(/\n\s*\n/).map(p => { const ls = p.split('\n'); const b = s => s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    return ls.every(l => l.trim().startsWith('- ')) ? `<ul>${ls.map(l => `<li>${b(l.trim().slice(2))}</li>`).join('')}</ul>` : `<p>${b(p)}</p>`; }).join('');

  for (const b of D.blocks || []) {
    if (b.type === 'segments') {
      const s = byName(b.scenario); const [c, el] = card(`Value by segment — ${s.name}`, 'What each part of the business is worth on its own, and how the parts add up to the value of the shares.');
      const eq = s.equity_value || 1;
      F.bars(el, s.segments.map((x, i) => ({label: `${x.name}${x.kind === 'venture' ? ' (long shot)' : ''}`, share: x.value / Math.abs(eq), text: money(x.value), color: x.value < 0 ? 'var(--warn)' : F.S[i % 8]})));
      const br = s.bridge, rows = [['Business value', br.enterprise_value], ['Debt', -br.debt], ['Cash', br.cash], ['Leases', -br.leases], ['Other claims', -(br.minority_interest + br.pension_deficit + br.preferred + br.options)], ['Bank / insurer equity', br.residual_income_equity], ['Value of the shares', br.equity_value]];
      el.insertAdjacentHTML('beforeend', `<dl class="kv" style="margin-top:12px">${rows.filter(r => r[1]).map(r => `<dt>${r[0]}</dt><dd>${money(r[1])}</dd>`).join('')}</dl>`);
      F.help(c, {lead: 'Each part of the business valued on its own cash flows and discount rate; a cost centre such as head office counts against the total.'});
    } else if (b.type === 'drivers') {
      const label = {revenue: 'Revenue', ebit: 'Operating profit', fcff: 'Free cash flow'}[b.field];
      const [c, el] = card(`${label} — ${b.segment}`, `How ${label.toLowerCase()} for ${esc(b.segment)} develops year by year in each scenario.`);
      F.lines(el, {series: scs.map((s, i) => ({name: s.name, color: F.S[i % 8], points: (s.segments.find(x => x.name === b.segment) || {years: []}).years.map(r => [r.t, r[b.field]])})), xFmt: x => 'Y' + Math.round(x), yFmt: y => F.moneyC(y), zeroLine: true, height: 240, aria: `${label} by year`});
      F.help(c, {lead: `The ${label.toLowerCase()} each scenario assumes for this segment. The gap between the lines is the disagreement the scenarios are about.`});
    } else if (b.type === 'ledger') {
      const [c, el] = card('Belief ledger', 'The beliefs the value depends on, what the evidence says about each, and what that changed in the model.');
      const ev = xs => (xs || []).map(x => `<li>${esc(x.claim)} <span class="src">${esc(x.source)}, ${esc(x.date)}</span></li>`).join('') || '<li class="muted">none found</li>';
      el.innerHTML = (D.ledger || []).map(e => `<details class="belief"><summary><span class="verdict ${esc(e.verdict)}">${esc(e.verdict)}</span><span>${esc(e.belief)}</span><span class="muted" style="font-size:12px">${esc(e.holder || '')} · ${esc(e.stakes || '')} stakes</span></summary>
        <div class="ev"><div><h3>Evidence for</h3><ul>${ev(e.for)}</ul></div><div><h3>Evidence against</h3><ul>${ev(e.against)}</ul></div></div>
        ${e.consequence ? `<div class="cq"><b>In the model:</b> ${esc(e.consequence.segment || '')} ${esc(e.consequence.field || '')} — ${esc(e.consequence.change || '')}</div>` : ''}</details>`).join('');
      F.help(c, {lead: 'Each row is a belief someone holds about the company, usually management. The research weighed it against the filings and dated news and gave a verdict.',
        sections: [{title: 'Verdicts', html: '<p><b>Supported</b>: the evidence backs it. <b>Doubtful</b>: the evidence leans against it. <b>Contradicted</b>: the evidence says otherwise. <b>Unknowable</b>: nothing available settles it. <b>Open</b>: not yet researched.</p>'}]});
    } else if (b.type === 'track_record') {
      const [c, el] = card('Guidance against results', 'What management said it would deliver, and what it then reported.');
      F.table(el, [{key: 'period', label: 'Period', left: true}, {key: 'metric', label: 'Measure', left: true}, {key: 'guided', label: 'Guided'}, {key: 'actual', label: 'Actual'}, {key: 'source', label: 'Source', left: true}], b.rows, {sortKey: 'period'});
      F.help(c, {lead: 'A record of past promises against outcomes. A habit of missing guidance is one reason the model discounts management’s current plan more heavily.'});
    } else if (b.type === 'forensics') {
      const [c, el] = card('Accounting findings', 'Places where the reported numbers and the cash or the notes tell different stories.');
      F.table(el, [{key: 'finding', label: 'Finding', left: true}, {key: 'severity', label: 'Severity', left: true}, {key: 'source', label: 'Source', left: true}], b.items, {sortKey: 'severity'});
      F.help(c, {lead: 'Findings from reading the statements and notes against each other: profit running ahead of cash, balances growing faster than sales, changes in accounting choices.'});
    } else if (b.type === 'skepticism') {
      const [c, el] = card('Cost of skepticism', 'How much of each scenario’s value the extra discount for doubtful plans takes away, and why each extra discount is there.');
      F.table(el, [{key: 'name', label: 'Scenario', left: true}, {key: 'v', label: 'Value / share', fmt: v => money(v)}, {key: 'x', label: 'Without the extra discount', fmt: v => money(v)}, {key: 'd', label: 'Difference', fmt: v => money(v)}],
        scs.map(s => ({name: s.name, v: s.value_per_share, x: s.value_ex_premiums, d: s.value_per_share - s.value_ex_premiums})), {sortKey: 'name'});
      const prem = []; scs.forEach(s => s.segments.forEach(x => { if (x.premium) prem.push(`<li><b>${esc(s.name)} · ${esc(x.name)}</b>: +${F.num(x.premium * 100, 1)} points — ${esc(x.premium_reason || 'no reason given')}</li>`); }));
      el.insertAdjacentHTML('beforeend', prem.length ? `<ul style="font-size:13px;margin-top:10px">${prem.join('')}</ul>` : '<p class="muted">No extra discount was applied.</p>');
      F.help(c, {lead: 'Where a plan is vague or the evidence leans against it, the model discounts that part of the business at a higher rate. This card shows what that choice costs in value.'});
    } else if (b.type === 'sensitivity') {
      const S = M.sensitivity; const [c, el] = card(`What moves the value — ${S.scenario}`, `Value per share as ${esc(S.a.field.replace('_', ' '))} (rows) and ${esc(S.b.field.replace('_', ' '))} (columns) for ${esc(S.a.segment)} change.`);
      const lab = (ax, v) => /premium|growth|margin/.test(ax.field) ? F.pct(v, 1, ax.field.endsWith('shift')) : F.num(v, 2);
      F.heatmap(el, {rows: S.a.values.map(v => lab(S.a, v)), cols: S.b.values.map(v => lab(S.b, v)), values: S.value_per_share.map(r => r.map(v => F.isNum(v) ? v - price : null)), fmt: v => money(v + price), diverging: true});
      F.help(c, {lead: 'Each cell reruns the scenario with two inputs changed. Blue cells are values above today’s price, red below; an empty cell is a combination the model cannot value.'});
    } else if (b.type === 'custom') {
      const [c, el] = card(`Custom calculation — ${b.title}`, 'A calculation outside the standard engine, kept separate so it can be checked on its own.');
      el.innerHTML = `<dl class="kv"><dt>Result</dt><dd>${esc(b.result)}</dd><dt>File</dt><dd><code>${esc(b.file)}</code></dd></dl>${md(b.explanation)}`;
      F.help(c, {lead: 'The standard engine could not express this part of the business, so a separate calculation was written and rerun by an independent check.'});
    } else if (b.type === 'text') {
      const [c, el] = card(b.title, 'Notes from the research that the tables do not show.');
      el.innerHTML = md(b.markdown);
      F.help(c, {lead: 'A short write-up of something from the research that matters for the value.'});
    }
  }
  const flags = [...(M.flags || []), ...(R.flags || []), ...(D.missing_roles || []).map(r => ({code: 'RESEARCH_MISSING', message: `The ${r} research did not complete, so its findings are absent.`})), ...(D.notes || []).map(n => ({code: 'NOTE', message: n}))];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${esc(f.code)}</b>${esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: D401 - argparse hook
        raise InvalidInput(message)


def _validate(data: dict) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a JSON object")
    model = data.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("scenarios"), list) or not model["scenarios"]:
        raise InvalidInput("model (a model.py result with scenarios) is required")
    price = data.get("price", model.get("price"))
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        raise InvalidInput("price must be a positive number")
    data["price"] = price
    scen = {s["name"] for s in model["scenarios"]}
    segs = {x["name"] for s in model["scenarios"] for x in s["segments"]}
    for i, b in enumerate(data.get("blocks") or []):
        t = b.get("type") if isinstance(b, dict) else None
        if t not in BLOCK_FIELDS:
            raise InvalidInput(f"blocks[{i}]: unknown type {t!r}")
        missing = [f for f in BLOCK_FIELDS[t] if b.get(f) in (None, "")]
        if missing:
            raise InvalidInput(f"blocks[{i}] ({t}) is missing {', '.join(missing)}")
        if t == "segments" and b["scenario"] not in scen:
            raise InvalidInput(f"blocks[{i}]: no scenario {b['scenario']!r}")
        if t == "drivers":
            if b["segment"] not in segs:
                raise InvalidInput(f"blocks[{i}]: no segment {b['segment']!r}")
            if b["field"] not in ("revenue", "ebit", "fcff"):
                raise InvalidInput(f"blocks[{i}]: field must be revenue, ebit or fcff")
        if t == "sensitivity" and not model.get("sensitivity"):
            raise InvalidInput(f"blocks[{i}]: the model has no sensitivity grid")
        if t == "ledger" and not data.get("ledger"):
            raise InvalidInput(f"blocks[{i}]: a ledger block needs ledger entries")
    for e in data.get("ledger") or []:
        eid = e.get("id", "?")
        if not e.get("belief") or e.get("verdict") not in VERDICTS:
            raise InvalidInput(f"ledger {eid}: needs a belief and a verdict in {', '.join(VERDICTS)}")
        for side in ("for", "against"):
            for c in e.get(side) or []:
                for f in ("claim", "source", "date"):
                    if not c.get(f):
                        raise InvalidInput(f"ledger {eid}: a claim under {side!r} has no {f}")


def build(data: dict) -> tuple[str, str, dict]:
    _validate(data)
    symbol = str(data.get("symbol") or "")
    title = f"{symbol} Deep Valuation".strip()
    markup = page.render(title, data, BODY, SCRIPT)
    model, rets = data["model"], data.get("returns") or {}
    flags = len(model.get("flags") or []) + len(rets.get("flags") or []) + len(data.get("missing_roles") or []) + len(data.get("notes") or [])
    return title, markup, {"title": title, "symbol": symbol or None, "scenarios": [s["name"] for s in model["scenarios"]],
                           "blocks": [b["type"] for b in data.get("blocks") or []], "flags": flags}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render_deep.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read the deep valuation JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
```

Check `render.py`'s `_Parser` and copy its exact definition if it differs. Then run `chmod +x skills/valuation/scripts/render_deep.py`.

- [ ] **Step 4: Generate the sample fixture**

Run:

```bash
cd tests && python3 -c "import json, test_scripts_valuation_deep as t; open('../docs/samples/valuation-deep.json','w').write(json.dumps(t.page_input(), indent=1) + '\n')"
```

- [ ] **Step 5: Run the tests and check they pass**

Run: `pytest tests/test_scripts_valuation_deep.py tests/test_skills_structure.py -v`
Expected: all PASS. The Chrome-gated test runs locally if Chrome is installed.

- [ ] **Step 6: Commit**

```bash
git add skills/valuation/scripts/render_deep.py docs/samples/valuation-deep.json tests/test_scripts_valuation_deep.py
git commit -m "feat(valuation): render_deep.py block-based deep valuation page"
```

### Task 5: Quick mode gains returns tiles

**Files:**
- Modify: `skills/valuation/scripts/render.py` (docstring, `_normalize` accepted keys, the tiles code at about line 153–164)
- Test: `tests/test_scripts_valuation.py` (append)

**Interfaces:**
- Consumes: the `returns.py` output in `convergence` mode (Task 3), under the key `returns` of the `render.py` input.

- [ ] **Step 1: Write the failing test**

```python
def test_render_shows_returns_tiles(tmp_path, capsys) -> None:
    data = json.loads((PLUGIN_ROOT / "docs/samples/valuation.json").read_text())
    data["returns"] = {"mode": "convergence", "price": 100.0, "horizon": 5, "hurdle": 0.1, "assumptions": [], "flags": [],
                       "scenarios": [{"name": "bear", "irr": -0.02}, {"name": "base", "irr": 0.07}, {"name": "bull", "irr": 0.13}]}
    src = tmp_path / "v.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script("valuation/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "v.html")], capsys)
    assert rc == 0 and "returns" in res["methods"]
    assert '"irr": 0.13' in (tmp_path / "v.html").read_text()
```

- [ ] **Step 2: Run the test and check it fails**

Run: `pytest tests/test_scripts_valuation.py::test_render_shows_returns_tiles -v`
Expected: FAIL (`returns` not in `methods`).

- [ ] **Step 3: Implement**

1. Read `_normalize` and `_METHODS` in `render.py`.
2. Make sure the `returns` key is passed through.
3. Append `"returns"` to the `methods` list in `build` when `data.get("returns")` is a dict. Do not add it to `_METHODS`, because `_METHODS` decides whether there is something to show.
4. In `SCRIPT`, after the existing tiles are built (just before `g('tiles').innerHTML = ...`), add:

```javascript
  const RT = D.returns;
  if (RT && RT.scenarios && RT.scenarios.length) {
    const r = RT.scenarios.map(s => `${F.esc(s.name)} ${F.isNum(s.irr) ? F.pct(s.irr, 1, true) : '—'}`).join(' · ');
    tiles.push([`Return a year over ${RT.horizon} years`, r, 'at today’s price, if the price reaches each case’s value']);
  }
```

5. Update the docstring's input block with `"returns": <returns.py result, convergence mode>`.

- [ ] **Step 4: Run the valuation tests**

Run: `pytest tests/test_scripts_valuation.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/valuation/scripts/render.py tests/test_scripts_valuation.py
git commit -m "feat(valuation): quick-mode page shows bear/base/bull annualized returns"
```

### Task 6: Role briefs reference file

**Files:**
- Create: `skills/valuation/references/deep-roles.md`
- Modify: `tests/test_skills_structure.py:55-66` (`REFERENCE_FILES`)

**Interfaces:**
- Produces: these section headings, which `SKILL.md` (Task 7) names exactly: `## Shared rules`, `## Forensic accountant`, `## Management claims`, `## Industry and news`, `## Segment economics`, `## Thread deep-dive`, `## Red team`.

- [ ] **Step 1: Register the file and run the structure tests to see them fail**

Add `"valuation/references/deep-roles.md",` after `"valuation/references/value-investing.md",` in `REFERENCE_FILES`.

Run: `pytest tests/test_skills_structure.py -v`
Expected: FAIL (the registered file is missing).

- [ ] **Step 2: Write `deep-roles.md`**

```markdown
# Deep valuation role briefs

Each section is the brief for one research subagent in a deep valuation. The orchestrator hands a subagent the Shared rules section plus its own role section, the case folder path, the ticker and today's date.

## Contents
- Shared rules
- Forensic accountant
- Management claims
- Industry and news
- Segment economics
- Thread deep-dive
- Red team

## Shared rules

- Work only inside the case folder `DIR/deep-SYMBOL/`. Write your findings to the file your role names, and nothing else.
- Fetch filings with the fundamental-research skill's scripts:
  - `edgar.py SYMBOL` (financials, filing index, Form 4)
  - `filing.py SYMBOL --item ITEM` (one Item's text)
  - `filing.py SYMBOL --search TERM` (a passage)
  - `filing.py SYMBOL --item ITEM --diff` (what changed since the previous filing)
  - `filing.py --url URL` (an older filing from the index)
- Use web search and page fetching for 8-K exhibits, earnings-call coverage, competitors and news.
- Every claim carries its source and date:
  - A filing is its form, Item and filing date, e.g. "10-K Item 7, 2026-02-20".
  - An article is its outlet and the dateline printed on the page, e.g. "Reuters, 2026-09-14".
  - Search snippets blend years. Read the dateline on the page itself.
  - A claim without a source and a date stays out of the findings.
- Separate what a document says from what you infer. Write inference as "Inference:" on its own line.
- Quote the exact figure from the source. Do not round or restate it.
- End the findings file with a `## Candidate beliefs` list, except the Red team. Each entry has:
  - the belief in one sentence
  - who holds it (management, the market, analysts)
  - stakes (high, medium, low): how much of the value would move if it were wrong
  - the evidence for and against so far, with sources
  - the model field it would change (segment, and growth, margin, sales_to_capital, a discount premium, or a scenario failure)
- Return to the orchestrator one paragraph: the three findings that matter most, and the file path.
- Leave buy, sell and hold judgements out entirely. The output describes the business and the evidence.

## Forensic accountant

Output: `research/forensic.md`.

Look for places where the reported numbers and the cash, or the notes, disagree:

| Check | Where | What counts as a finding |
|---|---|---|
| Earnings against operating cash flow | `edgar.py` annual table | Net income above operating cash flow for two or more of the last three years |
| Receivables, inventory, deferred revenue against revenue | `edgar.py` annual and quarterly | A balance growing more than 1.5× revenue growth, or deferred revenue shrinking while revenue grows |
| Capitalized costs | `filing.py --search "capitalized"` on the 10-K | Software, contract or interest costs capitalized at a rising share of spending |
| Non-GAAP gap | 8-K Item 2.02 exhibit | Adjusted earnings above GAAP by a growing margin, or new adjustments each year |
| Stock pay | `edgar.py` | Stock-based compensation as a share of revenue and of operating cash flow, and its trend |
| Accounting changes | `filing.py --item 8 --diff`, `--search "change in accounting"` | A changed policy, estimate or segment definition |
| Auditor and controls | `--search "material weakness"`, `"restat"`, `"going concern"`, `--item 9A` | Any hit, and an auditor change |
| Related parties | `--search "related part"` | Dealings with officers, directors or their companies |
| One-offs that recur | Income statement and MD&A | "Restructuring" or "special" charges in three or more of five years |

State each finding with its size in figures and its source. Then say what it would mean for the model, e.g. "free cash flow margin is 3 points below the reported operating margin implies".

## Management claims

Output: `research/claims.md`.

1. List the strategy in management's own words, from 10-K Item 1 and Item 7, the latest 10-Q Item 2 and the latest earnings release.
2. List the current guidance: each figure, its period and its source.
3. Build the track record. For each of the last three to five years, take the guidance given at the start of the year (8-K Item 2.02 exhibits, earnings-call coverage) and what was then reported. Write it as a table: period | measure | guided | actual | source.
4. Name the beliefs the strategy rests on, e.g. "the new segment reaches breakeven by 2028" or "price increases will stick". For each, gather the evidence that bears on it: results so far, competitor moves, what similar efforts elsewhere achieved.
5. Note vagueness: targets with no date, no figure, or a changing definition from one year to the next. A vague plan is itself a finding.

## Industry and news

Output: `research/industry.md`.

1. Competitors: the three to six that matter, with their scale, growth and margins where public.
2. The market: its size and growth from a dated source, and who is gaining or losing share.
3. Pricing power and costs: input costs, pricing actions, substitutes.
4. Regulation and legal matters that change the economics.
5. News from the last twelve months, newest first, each with outlet and dateline, and with what it changes.
6. What the market appears to believe: the price against consensus estimates, short interest, and analyst actions with dates. These are background only. They never set a model input.

## Segment economics

Output: `research/segments.md`.

1. From the 10-K segment note (`filing.py --search "segment"`, and the Item 8 notes), take each reported segment's:
   - revenue, operating income, assets, capital spending, and depreciation and amortization
   - over three to five years
2. Compute from those figures, and show the arithmetic:
   - growth
   - operating margin
   - sales to capital (revenue / assets, as a proxy)
3. Say which segment carries most of the value, and which consumes capital.
4. Propose the segments for the model. Merge small ones, and split out a stake, a venture or a cost centre (unallocated corporate costs) when the filings let you. For each proposed segment give the starting revenue, a margin range, and a sales-to-capital range anchored on its history.
5. Note any segment whose definition changed. That breaks the history.

## Thread deep-dive

Output: `threads/<n>-<slug>.md`, the name given by the orchestrator.

You get one belief from the ledger. Take it to a verdict:

1. Restate the belief and why it matters to the value.
2. Gather the evidence on both sides. Go past the first source:
   - older filings
   - competitors' filings
   - industry data
   - what happened to others who tried the same thing
3. Give a verdict, with the two or three pieces of evidence that decide it:

   | Verdict | Meaning |
   |---|---|
   | supported | The evidence backs it |
   | doubtful | The evidence leans against it |
   | contradicted | The evidence says otherwise |
   | unknowable | Nothing available settles it |

4. Give the model consequence as a specific change, e.g. "Core margin path capped at 17% in Base; the Bull case keeps 20%", or "+3 points discount premium on New Markets: no dated target and two missed launches".
5. List any new beliefs you uncovered, in the Candidate beliefs format.

## Red team

Output: `research/redteam.md`.

You get the case folder after the model has run. Attack the central scenario (the one the orchestrator names):

1. The weakest input. Find the one the value is most sensitive to, with the least evidence behind it.
2. What is missing:
   - a risk in the ledger or the filings that no scenario reflects
   - a claim on the equity that is not in `claims` (leases, pensions, minority stakes, options)
3. Double counting:
   - a growth driver counted in two segments
   - cash counted both in `claims` and as an asset
   - a premium stacked on a failure that already reflects the same risk
4. Custom calculations. Rerun every `custom/*.py`. Check that its output matches the figure the page uses, and that its method is what its explanation says.
5. Consistency: the margins and reinvestment the scenarios imply, compared with the segment history and the competitors.

List the concrete changes you propose, each with its reason and the file and field it touches. List anything you checked and found sound, so the orchestrator knows it was covered.
```

- [ ] **Step 3: Check the banned verbs and run the structure tests**

Run: `grep -niE "\b(recommend\w*|advis\w*|should|suggest\w*)\b" skills/valuation/references/deep-roles.md; pytest tests/test_skills_structure.py -v`
Expected: the grep prints nothing; the tests PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/valuation/references/deep-roles.md tests/test_skills_structure.py
git commit -m "feat(valuation): role briefs for deep-valuation subagents"
```

### Task 7: `SKILL.md` — deep mode, quick-mode returns

**Files:**
- Modify: `skills/valuation/SKILL.md`

**Interfaces:**
- Consumes: the script names and fields from Tasks 1–5, and the `deep-roles.md` section names from Task 6.

- [ ] **Step 1: Edit the frontmatter description**

```yaml
description: Estimates fair value and the return at today's price with DCF, multiples, dividend discount, Graham/Buffett checks, or a deep dive that researches filings and values scenarios by segment. Use when asked what something is worth, a fair price or a deep dive.
```

Check its length with `python3 -c "import re;t=open('skills/valuation/SKILL.md').read();print(len(re.search(r'description: (.*)',t).group(1)))"`. It must print 260 or less. Shorten the wording if not.

- [ ] **Step 2: Change the opening line**

Replace it with:

```markdown
Estimates what a security is worth from its fundamentals, and what buying at today's price would earn a year. Quick mode runs a discounted-cash-flow range cross-checked against comparable multiples, dividend discounting and Graham/Buffett arithmetic. Deep mode sends research subagents through the filings and news, keeps a sourced ledger of the beliefs the value rests on, and values named scenarios segment by segment. It has no access to brokerage accounts.
```

- [ ] **Step 3: Add to Background, before `### Reference files`**

```markdown
### Two modes

| The person says | Mode |
|---|---|
| "what's X worth", "value check", "fair price", several tickers, the screener funnel's price check | Quick |
| "deep dive", "in depth", "full valuation", "dig into X", "what could go wrong with X's plan" | Deep |
| A single ticker, unclear which | Quick, ending with one line: a deep version is available and sends ten to fifteen research subagents |

### What `returns.py` adds

- The annualized return (IRR) from buying at today's price and holding to the horizon (5 years by default), with the total multiple and the exit value that would earn the hurdle (10% by default).
- `convergence` mode (quick): the price closes on a fair value by the horizon. Buying at fair value earns exactly the cost of equity.
- `paths` mode (deep): `model.py`'s `returns_input`, with its yearly distributions and exit value.
- `TOTAL_LOSS` fires when nothing comes back to the holder.

### What `model.py` does (deep mode)

- It values a company as a sum of segments under named scenarios. Its docstring is the full contract.
- Segment kinds:

  | `kind` | Use for |
  |---|---|
  | `operating` | A business line: revenue growth, EBIT margin and sales-to-capital by year, its own discount rate, and a Gordon or exit-multiple terminal value |
  | `cost` | Unallocated corporate cost, valued as a negative perpetuity |
  | `asset` | A stake, land or other item at a stated value |
  | `venture` | A long shot: probability × value if it works, less its cost |
  | `residual_income` | A bank or insurer: book value plus the present value of returns above the cost of equity |

- `discount_premium` with `premium_reason` raises one segment's discount rate for a doubtful or vague plan. `value_ex_premiums` shows the value without any premium.
- A scenario overrides named segment fields. `fails` ends a segment at a year with a salvage value.
- Each scenario's `path` and `exit` feed `returns_input`.
- Flags: `TERMINAL_HEAVY`, `NEGATIVE_EQUITY`, `MARGIN_ABOVE_HISTORY`, `REINVESTMENT_NEGATIVE`.

### The deep-mode case folder

Each deep run keeps its work in `DIR/deep-SYMBOL/`, where DIR is the session scratchpad:

| Path | Holds |
|---|---|
| `baseline/` | Quick-mode script output |
| `research/<role>.md` | One findings file per research role |
| `ledger.json` | The belief ledger: `id`, `belief`, `holder`, `stakes`, `verdict`, `for` and `against` (each `claim`, `source`, `date`), `consequence`, `thread` |
| `threads/<n>-<slug>.md` | One file per deep-dive |
| `model.json` | The `model.py` input |
| `custom/*.py` | Calculations the engine cannot express, each printing JSON |
| `page.json` | The `render_deep.py` input |

`render_deep.py` always opens with the scenario table and the price against the scenarios. After that it shows the blocks you list, in your order. `segments`, `drivers`, `ledger`, `track_record`, `forensics`, `skepticism`, `sensitivity`, `custom` and `text` are described in its docstring. A ledger claim without a source and a date is exit 2.
```

In `### Reference files`, add:

```markdown
- `references/deep-roles.md` holds the brief for each deep-mode research subagent. Hand a subagent its section and the Shared rules section, verbatim.
```

- [ ] **Step 4: Scripts section**

Add to the bash block:

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/returns.py" <<< '<input json>'
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/model.py" < DIR/deep-SYMBOL/model.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/render_deep.py" --in DIR/deep-SYMBOL/page.json --out DIR/deep-SYMBOL/page.html
```

Add these table rows:

```markdown
| `returns.py` | Annualized return at today's price per scenario, in `convergence` or `paths` mode. |
| `model.py` | Segment-by-segment, scenario-by-scenario valuation with the path to the horizon and `returns_input`. |
| `render_deep.py` | The deep-mode page: scenario table, price strip, then the chosen blocks. |
```

Change the exit-code row for 2 to: "Bad input. For `render.py`, no script result is present. For `render_deep.py`, a missing model, an unknown block, or an undated ledger claim."

- [ ] **Step 5: Steps — split into case lines**

Put `**Quick (one company or several)**` before the existing step 1, and keep the existing steps 1–14. Then:

- In step 7, add a sub-step: "Run `returns.py` in `convergence` mode on the three results: `fair_value` from each `fair_value_per_share`, `cost_of_equity` from `assumptions.cost_of_equity.value`, `dividend_yield` from `ddm_input.dividend0` / price (0 when null)."
- In step 13.1, add `returns` to the listed keys.
- Add a step 15: "With several companies, skip the page and reply with one row each: price, bear / base / bull value, and the base-case annualized return."

Then append:

```markdown
**Deep (one company)**

1. Run `edgar.py SYMBOL` from the fundamental-research skill. If it exits 4, stop. Say deep mode needs SEC EDGAR, and offer quick mode.
2. Make `DIR/deep-SYMBOL/` and its `baseline/`, `research/`, `threads/` and `custom/` folders. Write the output of `fundamentals.py`, `inputs.py`, `intrinsic-inputs.py` and `edgar.py` into `baseline/`.
3. Tell the person deep mode has started and roughly how many research tasks it will run.
4. Dispatch the four round-1 roles in parallel with the Agent tool (general-purpose type): Forensic accountant, Management claims, Industry and news, Segment economics.
   - Each prompt holds the Shared rules section and the role's section of `references/deep-roles.md` verbatim, plus the case folder path, the symbol and today's date.
   - If the Agent tool is unavailable, run the roles one after another yourself, and say so in the reply.
5. If a role failed or wrote no file, add its name to `missing_roles` and go on.
6. Merge the candidate beliefs into `ledger.json`. Combine duplicates. Set `verdict` to `open` where the evidence is thin. Rank by stakes, then by how evenly the evidence splits.
7. Write `model.json`:
   1. Take the segments from `research/segments.md`, plus a `cost` segment for unallocated corporate cost when it is reported.
   2. Anchor each driver on the segment's history. Move it only where a ledger entry gives a dated reason.
   3. Write three to five scenarios that differ in their story (what happens to the business), not just in a growth shift. Each has a `summary` and its `must_be_true` list.
   4. Give a `discount_premium` only where a ledger entry is doubtful, contradicted or vague. Put the entry's id in the `premium_reason`.
   5. Take `claims` from the latest balance sheet in `baseline/`, `base_discount_rate` from `inputs.py`'s `wacc`, and add `history` with each segment's best historical margin.
   6. Add a `sensitivity` on the two inputs the central scenario hangs on.
8. Run `model.py`, then `returns.py` on its `returns_input`. If `model.py` exits 2, fix `model.json` and rerun.
9. Thread rounds, at most three:
   1. Pick up to four `open` or contested beliefs with high or medium stakes.
   2. Dispatch one Thread deep-dive per belief, in parallel. Each gets the Shared rules and Thread deep-dive sections, the ledger entry, its output file name and the case folder.
   3. Write each verdict and its evidence into `ledger.json`, apply each model consequence to `model.json`, and add any new beliefs.
   4. Rerun `model.py` and `returns.py`.
   5. Stop when no scenario's `value_per_share` moved more than 5% in the round, or after round three.
10. Dispatch the Red team with its section and the name of the central scenario.
    - Apply each proposed change that holds up, and rerun.
    - Keep a list of the changes you rejected, each with one line on why.
11. If a case needs arithmetic the engine cannot express:
    1. Write it as `custom/<name>.py` printing JSON.
    2. Have the Red team rerun it.
    3. Show it as a `custom` block. Never fold it silently into a total.
12. Write `page.json`. Pick the blocks that tell this company's story, in the order a reader needs them. Run `render_deep.py --in DIR/deep-SYMBOL/page.json --out DIR/deep-SYMBOL/page.html`.
13. Publish with the Artifact tool: icon chart, description "Deep valuation: SYMBOL at PRICE". Republish the same path on later runs.
14. Reply in the deep format below. If the Artifact tool is unavailable, use the deep markdown fallback.
```

- [ ] **Step 6: Reply format — add the deep reply**

Append within `## Reply format`:

```markdown
**Deep mode, page published:** these parts, then stop.

1. The artifact link on its own line.
2. A table: scenario | value per share | return a year at today's price, from `model.py` and `returns.py`.
3. The two or three ledger verdicts that move value most, each with its source and date, and what it changed in the model.
4. One line on the cost of skepticism: the largest gap between `value_per_share` and `value_ex_premiums`, with its reason.
5. **Flags**: `model.py` and `returns.py` flags, missing research roles, and rejected red-team changes. Or "None".
6. One sentence, once: the figures are general information at the stated assumptions, not financial, tax, or legal advice.

**Deep mode, markdown fallback:** the same parts without the link, plus the full ledger as a list (belief, verdict, the deciding evidence with sources).
```

- [ ] **Step 7: Rules — amend**

- Replace "Every number comes from the scripts. Present the scripts' numbers; do not recompute them by hand or add figures." with:
  - "Every number comes from the scripts, or from a `custom/*.py` the Red team reran and the page labels. Present those numbers; do not recompute them by hand."
- Add after it:
  - "In deep mode, a belief without a dated source changes nothing in the model."
  - "Every discount-rate premium is stated with its reason and the ledger entry behind it."
  - "Scenarios carry no probabilities. Present them side by side and leave the weighing to the person."

- [ ] **Step 8: Verify the structure**

Run: `wc -l skills/valuation/SKILL.md && pytest tests/test_skills_structure.py -v`
Expected: at most 500 lines; PASS. If it is over 500 lines, shorten the deep Background tables first, never the Rules.

- [ ] **Step 9: Commit**

```bash
git add skills/valuation/SKILL.md
git commit -m "feat(valuation): deep mode procedure and quick-mode returns in SKILL.md"
```

### Task 8: Docs

**Files:**
- Modify: `docs/scripts.md` (the `## valuation` table), `CHANGELOG.md`, `docs/examples.md:37`

- [ ] **Step 1: `docs/scripts.md`**

Add rows under `## valuation`, following the style of the existing rows:

```markdown
| `model.py` | `python model.py < model.json` — segment-by-segment valuation (operating, cost, asset, venture and residual-income segments) under named scenarios, with discount-rate premiums, a path to the horizon, exit values, a two-way sensitivity grid and a ready `returns.py` input; contract in the docstring; exit 2 on invalid input |
| `returns.py` | `python returns.py < input.json` — annualized return at today's price per scenario (`paths` from `model.py`, or `convergence` on a fair value), total multiple and the exit value that earns the hurdle; exit 2 on invalid input |
| `render_deep.py` | `render_deep.py [--in page.json] --out page.html` — the deep valuation page: scenario table, price strip, then the chosen blocks (segments, drivers, belief ledger, guidance track record, accounting findings, cost of skepticism, sensitivity, custom calculation, text); prints `{"out","title","symbol","scenarios","blocks","flags"}`; exit 2 on a missing model, an unknown block or an undated ledger claim |
```

- [ ] **Step 2: `CHANGELOG.md`**

Read the top of the file for its format. Add, under an `Unreleased` heading (create it in the file's style if it is absent):

```markdown
- valuation: deep mode. Research subagents read the filings and news, keep a sourced belief ledger, chase the contested beliefs, and value three to five named scenarios segment by segment (`model.py`), with the annualized return at today's price for each (`returns.py`) on a new page (`render_deep.py`).
- valuation: quick mode shows the bear, base and bull annualized return at today's price.
```

- [ ] **Step 3: `docs/examples.md`**

Append to the valuation line: ` · "Do a deep dive on PHM: what has to go right, and what would I earn at today's price?"`

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all PASS, apart from Chrome-gated skips.

- [ ] **Step 5: Commit**

```bash
git add docs/scripts.md CHANGELOG.md docs/examples.md
git commit -m "docs: deep valuation mode"
```

### Task 9: Manual end-to-end deep run

**Files:**
- None committed, unless the run exposes a defect (then fix it with a test in the owning file).

- [ ] **Step 1:** Load the branch's skill (`skills/valuation/SKILL.md`) and follow the **Deep** steps for PHM, with the case folder in the session scratchpad.
- [ ] **Step 2:** Check the success criteria from the spec:
  - The page leads with the scenario table.
  - Every ledger claim has a dated source.
  - At least one thread round ran.
  - The scenarios differ in their story.
  - Returns are shown.
- [ ] **Step 3:** Publish the page (it is private by default) and note any procedure step that was unclear or failed. Fix the wording in `SKILL.md` or `deep-roles.md`, then rerun `pytest tests/test_skills_structure.py -q` and commit:

```bash
git add skills/valuation
git commit -m "fix(valuation): deep-mode procedure fixes from the PHM end-to-end run"
```
