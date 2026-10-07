# Deep Picker Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deep picker mode to the stock-screener skill. It merges a top-down industry scan with the financial screen, health-checks the pool, ranks candidates with judgement, deep-values 3–5 finalists, and surfaces only those that pass downside gate B.

**Architecture:** The deterministic pieces are scripts:

- `screen.py --symbols` and the `health` preset
- `gate.py`
- `render_pick.py`

Agent orchestration lives in `SKILL.md`, with role briefs in `references/picker-roles.md`. Deep valuation is reused unchanged.

**Tech Stack:** Python 3 standard library; `second_opinion.page` / `output` / `errors`; pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-deep-picker-design.md`

## Global Constraints

- New scripts:
  - start with a docstring that describes stdin or starts with `Usage:`
  - have a main guard
  - are executable
  - exit 2 on bad input
- `SKILL.md`:
  - keeps the required headings and order
  - stays at or under 500 lines
  - has a description at or under 260 characters, with "Use when" and no ": "
  - has no prose line over 400 characters
- Commands start `"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/`.
- Reference files:
  - each new one is registered in `REFERENCE_FILES`
  - one over 100 lines starts with `## Contents`
- No "recommend", "advise", "should" or "suggest" in new prose, briefs or page text.
- Pages:
  - every visible card has authored `FA.help`
  - every section in BODY opens with `<p class="sub">`
  - Flags uses `page.FLAGS_INTRO`

## Review Focus

1. **A finalist whose `returns` lacks a scenario named in `model`** (name mismatch). Expected: that scenario counts as "return could not be computed", and the finalist fails. *Test: Task 2 `test_gate_unmatched_scenario_fails`.*
2. **Gate input with a scenario whose irr is −1 (TOTAL_LOSS)**. Expected: fail, with the loss stated. *Test: Task 2 `test_gate_total_loss_fails`.*
3. **`--symbols` names a ticker with too little filing history** (dropped as incomplete). Expected: it is listed in `incomplete`, not silently missing. *Test: Task 1 `test_symbols_reports_incomplete`.*
4. **`pick.json` with zero passes**. Expected: the page renders the "No finalist passed" card, and the near-misses list is populated. *Test: Task 3 `test_render_pick_no_passes`.*
5. **An industry evidence claim missing its date**. Expected: exit 2 naming the industry. *Test: Task 3 `test_render_pick_rejects_undated_evidence`.*

---

### Task 1: `health` preset and `screen.py --symbols`

**Files:**
- Modify: `skills/stock-screener/scripts/screen_math.py` (PRESETS, docstring)
- Modify: `skills/stock-screener/scripts/screen.py` (parser, `run`, docstring)
- Test: `tests/test_scripts_stock_screener.py` (append)

**Interfaces:**
- Produces: when `ns.symbols` is set, the output has `checked: [{"ticker","name","passed","failed","financial"}]`, `not_found: [str]` and `incomplete: [str]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_health_preset_is_a_floor(frames) -> None:
    out = _run(frames, "--preset", "health", "--no-price")
    assert {s["ticker"] for s in out["survivors"]} == {"GROW", "SLOW"}  # BANK is a financial filer
    assert out["rank_by"] == "f_score"


def test_health_preset_fails_heavy_dilution(frames) -> None:
    for y in YEARS:
        rows = frames.data[("WeightedAverageNumberOfDilutedSharesOutstanding", f"CY{y}")]
        for r in rows:
            if r["cik"] == 2:
                r["val"] = 100e6 * (1.10 ** (y - 2022))
    out = _run(frames, "--preset", "health", "--no-price")
    assert "SLOW" not in {s["ticker"] for s in out["survivors"]}


def test_symbols_restricts_and_reports(frames) -> None:
    out = _run(frames, "--preset", "health", "--no-price", "--symbols", "grow,bank", "--symbols", "NOPE")
    assert out["universe"] == 2
    checked = {c["ticker"]: c for c in out["checked"]}
    assert checked["GROW"]["passed"] is True and checked["GROW"]["failed"] == []
    assert checked["BANK"]["financial"] is True and checked["BANK"]["passed"] is False
    assert out["not_found"] == ["NOPE"] and out["incomplete"] == []


def test_symbols_reports_incomplete(frames) -> None:
    for y in (2022, 2023):
        for concept in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"):
            frames.data[(concept, f"CY{y}")] = [r for r in frames.data.get((concept, f"CY{y}"), []) if r["cik"] != 2]
    out = _run(frames, "--preset", "health", "--no-price", "--symbols", "SLOW,GROW")
    assert out["incomplete"] == ["SLOW"] and [c["ticker"] for c in out["checked"]] == ["GROW"]
```

- [ ] **Step 2: Run them and check they fail**

Run: `python3 -m pytest tests/test_scripts_stock_screener.py -q -k "health or symbols"`
Expected: FAIL (`health` is not a known preset; `--symbols` is unrecognized).

- [ ] **Step 3: Implement**

1. In `screen_math.PRESETS`, add after `payout`:

```python
    # A floor for a hand-picked list, not a ranking: drops shrinking, cash-burning, heavily
    # diluting or over-borrowed businesses and keeps everything else.
    "health": {
        "min_revenue": 250e6,
        "min_revenue_cagr": -0.05,
        "min_f_score": 4,
        "max_share_growth": 0.05,
        "max_net_debt_to_ebit": 4.0,
        "min_fcf_margin": 0.0,
        "rank_by": "f_score",
    },
```

   Add `health` to the presets list in the `screen_math` docstring.

2. In `screen.py`:
   - In `parser()`, add `p.add_argument("--symbols", action="append", metavar="SYM,SYM")`.
   - In `run`, right after `companies = build_companies(...)`:

```python
    wanted = _held(ns.symbols) if getattr(ns, "symbols", None) else set()
    if wanted:
        companies = [c for c in companies if str(c.get("ticker") or "").upper() in wanted]
```

   - Just before `if not ns.all:`:

```python
    if wanted:
        rows = {str(r.get("ticker") or "").upper(): r for r in result.get("companies") or []}
        found = {str(c.get("ticker") or "").upper() for c in companies}
        result["checked"] = [
            {"ticker": t, "name": rows[t].get("name"), "passed": not rows[t]["failed"], "failed": rows[t]["failed"],
             "financial": "financial_filer" in rows[t]["failed"] or "financial_excluded" in rows[t]["failed"]}
            for t in sorted(rows)
        ]
        result["not_found"] = sorted(wanted - found)
        result["incomplete"] = sorted(found - set(rows))
```

   - Update the `screen.py` docstring's argument list and output paragraph with `--symbols`, `checked`, `not_found` and `incomplete`.

- [ ] **Step 4: Run the screener tests**

Run: `python3 -m pytest tests/test_scripts_stock_screener.py tests/test_screen_math.py -q`
Expected: all PASS. If a `screen_math` test pins the preset list, add `health` to it.

- [ ] **Step 5: Commit**

```bash
git add skills/stock-screener/scripts/screen_math.py skills/stock-screener/scripts/screen.py tests/test_scripts_stock_screener.py
git commit -m "feat(stock-screener): health preset and --symbols for checking a hand-picked list"
```

### Task 2: `gate.py`

**Files:**
- Create: `skills/stock-screener/scripts/gate.py`
- Test: `tests/test_scripts_stock_picker.py` (new)

**Interfaces:**
- Consumes: `model.py` output (`scenarios[].name`, `value_per_share`, and `implied`) and `returns.py` output (`scenarios[].name`, `irr`).
- Produces: `run_gate(params) -> dict` with `{"hurdle","floor","results":[...],"counts":{...}}`, per the spec.

- [ ] **Step 1: Write the failing tests**

```python
"""Deep picker: gate.py (the downside gate on deep valuations) and render_pick.py (the picks page)."""

from __future__ import annotations

import io
import json
import sys

import pytest
from page_dom import assert_page_help, render_and_audit, requires_chrome
from scripts_util import PLUGIN_ROOT, load_script, run_json

GATE = "stock-screener/scripts/gate.py"


def run_stdin(rel, payload, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script(rel).main()
    return json.loads(capsys.readouterr().out)


def run_stdin_error(rel, payload, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        load_script(rel).main()
    return exc.value.code, json.loads(capsys.readouterr().out)


def finalist(symbol, price, scen):
    """scen: [(name, value_per_share, irr)], first is central."""
    return {"symbol": symbol, "price": price, "page": f"https://example/{symbol}",
            "model": {"scenarios": [{"name": n, "value_per_share": v} for n, v, _ in scen], "implied": {"field": "margin_shift", "value": -0.01}},
            "returns": {"scenarios": [{"name": n, "irr": r} for n, _, r in scen]}}


def test_gate_verdicts_and_order(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"finalists": [
        finalist("LOSS", 50, [("Base", 60, 0.12), ("Bear", 40, -0.02)]),
        finalist("SAFE", 50, [("Base", 62, 0.11), ("Bear", 45, 0.03)]),
        finalist("ABOVE", 50, [("Base", 70, 0.15), ("Bear", 55, 0.08)]),
        finalist("LOW", 50, [("Base", 52, 0.08), ("Bear", 47, 0.02)]),
    ]}, capsys, monkeypatch)
    assert [r["symbol"] for r in out["results"]] == ["SAFE", "ABOVE", "LOSS", "LOW"]
    by = {r["symbol"]: r for r in out["results"]}
    assert by["SAFE"]["verdict"] == "pass" and by["ABOVE"]["verdict"] == "pass_flagged"
    assert by["LOSS"]["verdict"] == "fail" and "loses 2.0% a year" in by["LOSS"]["reasons"][0]
    assert by["LOW"]["verdict"] == "fail" and "below the 10.0% hurdle" in by["LOW"]["reasons"][0]
    assert by["ABOVE"]["reasons"] == ["Every scenario is worth more than the price; a downside case may be missing."]
    assert by["SAFE"]["worst"] == {"name": "Bear", "irr": 0.03, "value_per_share": 45}
    assert out["counts"] == {"pass": 1, "pass_flagged": 1, "fail": 2}
    assert by["SAFE"]["implied"] == {"field": "margin_shift", "value": -0.01}


def test_gate_custom_hurdle_and_floor(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"hurdle": 0.07, "floor": -0.01, "finalists": [finalist("LOW", 50, [("Base", 52, 0.08), ("Bear", 47, -0.005)])]}, capsys, monkeypatch)
    assert out["results"][0]["verdict"] == "pass"


def test_gate_null_irr_fails(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"finalists": [finalist("X", 50, [("Base", 60, 0.12), ("Bear", 45, None)])]}, capsys, monkeypatch)
    r = out["results"][0]
    assert r["verdict"] == "fail" and any("could not be computed" in s for s in r["reasons"])


def test_gate_unmatched_scenario_fails(capsys, monkeypatch) -> None:
    f = finalist("X", 50, [("Base", 60, 0.12), ("Bear", 45, 0.02)])
    f["returns"]["scenarios"] = [{"name": "Base", "irr": 0.12}]
    out = run_stdin(GATE, {"finalists": [f]}, capsys, monkeypatch)
    assert out["results"][0]["verdict"] == "fail" and "'Bear'" in out["results"][0]["reasons"][0]


def test_gate_total_loss_fails(capsys, monkeypatch) -> None:
    out = run_stdin(GATE, {"finalists": [finalist("X", 50, [("Base", 60, 0.12), ("Bust", 0, -1.0)])]}, capsys, monkeypatch)
    assert out["results"][0]["verdict"] == "fail" and "loses 100.0% a year" in out["results"][0]["reasons"][0]


@pytest.mark.parametrize("payload, needle", [
    ({"finalists": []}, "finalists"),
    ({"hurdle": "x", "finalists": [finalist("X", 50, [("B", 60, 0.1)])]}, "hurdle"),
    ({"finalists": [finalist("X", 0, [("B", 60, 0.1)])]}, "price"),
    ({"finalists": [{"symbol": "X", "price": 5}]}, "model"),
])
def test_gate_validation(payload, needle, capsys, monkeypatch) -> None:
    rc, out = run_stdin_error(GATE, payload, capsys, monkeypatch)
    assert rc == 2 and needle in out["error"]
```

- [ ] **Step 2: Run them and check they fail**

Run: `python3 -m pytest tests/test_scripts_stock_picker.py -q`
Expected: FAIL (`gate.py` not found).

- [ ] **Step 3: Write `gate.py`**

```python
#!/usr/bin/env python3
"""The downside gate for deep picks (stdin -> stdout JSON).

    python gate.py < gate.json

Input: {"hurdle": 0.10, "floor": 0.0, "finalists": [{"symbol", "price", "page",
"model": <valuation model.py output>, "returns": <valuation returns.py output>}]}.

Rule B. Each finalist's scenarios are matched to their returns by name. It passes when every
scenario's annual return is at least ``floor`` (default 0: no scenario loses money over the
horizon, dividends included) and the central scenario (the first in ``model.scenarios``) earns
at least ``hurdle`` (default 10%). A scenario with no return (unmatched or null) fails. A
finalist that passes while every scenario's value sits above the price is ``pass_flagged``: a
downside case may be missing.

Output: {"hurdle", "floor", "results": [{"symbol", "price", "verdict": "pass"|"pass_flagged"|
"fail", "central": {"name", "irr", "value_per_share"}, "worst": {...}, "checks": {"worst_ok",
"central_ok", "all_above_price"}, "reasons": [str], "page", "implied"}], "counts": {"pass",
"pass_flagged", "fail"}}. Results run pass, pass_flagged, fail, each by central return, highest
first. Exit 2 with {"error"} on invalid input.
"""

from __future__ import annotations

import json
import math
import sys

ORDER = {"pass": 0, "pass_flagged": 1, "fail": 2}


def _num(v: object, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


def _pct(v: float) -> str:
    return f"{abs(v) * 100:.1f}%"


def run_gate(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    hurdle = _num(params.get("hurdle", 0.10), "hurdle")
    floor = _num(params.get("floor", 0.0), "floor")
    if hurdle <= -1 or floor <= -1:
        raise ValueError("hurdle and floor must be above -1")
    finalists = params.get("finalists")
    if not isinstance(finalists, list) or not finalists:
        raise ValueError("finalists must be a non-empty list")
    results = []
    for f in finalists:
        sym = f.get("symbol") if isinstance(f, dict) else None
        if not sym:
            raise ValueError("every finalist needs a symbol")
        price = _num(f.get("price"), f"{sym}.price")
        if price <= 0:
            raise ValueError(f"{sym}.price must be positive")
        scen = ((f.get("model") or {}).get("scenarios")) if isinstance(f.get("model"), dict) else None
        rets = ((f.get("returns") or {}).get("scenarios")) if isinstance(f.get("returns"), dict) else None
        if not isinstance(scen, list) or not scen or not isinstance(rets, list):
            raise ValueError(f"{sym}: needs model.scenarios and returns.scenarios")
        irr_by = {r.get("name"): r.get("irr") for r in rets if isinstance(r, dict)}
        rows = [{"name": s.get("name"), "irr": irr_by.get(s.get("name")), "value_per_share": s.get("value_per_share")} for s in scen]
        reasons = []
        missing = [r["name"] for r in rows if not isinstance(r["irr"], (int, float)) or isinstance(r["irr"], bool)]
        for name in missing:
            reasons.append(f"The return for scenario '{name}' could not be computed.")
        known = [r for r in rows if r["name"] not in missing]
        central = rows[0]
        worst = min(known, key=lambda r: r["irr"]) if known else None
        worst_ok = not missing and worst is not None and worst["irr"] >= floor
        central_ok = central["name"] not in missing and central["irr"] >= hurdle
        all_above = all(isinstance(r["value_per_share"], (int, float)) and r["value_per_share"] > price for r in rows)
        if worst is not None and worst["irr"] < floor:
            reasons.insert(0, f"Worst scenario '{worst['name']}' {'loses' if worst['irr'] < 0 else 'earns'} {_pct(worst['irr'])} a year, below the {floor * 100:.1f}% floor."
                           if worst["irr"] >= 0 else f"Worst scenario '{worst['name']}' loses {_pct(worst['irr'])} a year.")
        if central["name"] not in missing and central["irr"] < hurdle:
            reasons.append(f"Central scenario '{central['name']}' earns {central['irr'] * 100:.1f}% a year, below the {hurdle * 100:.1f}% hurdle.")
        if worst_ok and central_ok:
            verdict = "pass_flagged" if all_above else "pass"
            if all_above:
                reasons.append("Every scenario is worth more than the price; a downside case may be missing.")
        else:
            verdict = "fail"
        results.append({"symbol": sym, "price": price, "verdict": verdict,
                        "central": central, "worst": worst,
                        "checks": {"worst_ok": worst_ok, "central_ok": central_ok, "all_above_price": all_above},
                        "reasons": reasons, "page": f.get("page"), "implied": (f.get("model") or {}).get("implied")})
    results.sort(key=lambda r: (ORDER[r["verdict"]], -(r["central"]["irr"] if isinstance(r["central"]["irr"], (int, float)) else -9)))
    counts = {k: sum(1 for r in results if r["verdict"] == k) for k in ORDER}
    return {"hurdle": hurdle, "floor": floor, "results": results, "counts": counts}


def main() -> None:
    try:
        result = run_gate(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
```

Then run `chmod +x skills/stock-screener/scripts/gate.py`.

- [ ] **Step 4: Run the tests and check they pass**

Run: `python3 -m pytest tests/test_scripts_stock_picker.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/stock-screener/scripts/gate.py tests/test_scripts_stock_picker.py
git commit -m "feat(stock-screener): gate.py, the downside gate for deep picks"
```

### Task 3: `render_pick.py`

**Files:**
- Create: `skills/stock-screener/scripts/render_pick.py`
- Create: `docs/samples/stock-picker.json` (generated by the test helper)
- Test: `tests/test_scripts_stock_picker.py` (append)

**Interfaces:**
- Consumes: the `gate.py` output, and `pick.json` per the spec.
- Produces: the CLI `render_pick.py [--in pick.json] --out page.html`, printing `{"out","title","picks","near_misses","industries","candidates","flags"}`.

- [ ] **Step 1: Write the failing tests**

```python
RENDER = "stock-screener/scripts/render_pick.py"
SAMPLE = PLUGIN_ROOT / "docs/samples/stock-picker.json"


def pick_input() -> dict:
    gate = load_script(GATE).run_gate({"finalists": [
        finalist("SAFE", 50, [("Base", 62, 0.11), ("Bear", 45, 0.03)]),
        finalist("ABOVE", 50, [("Base", 70, 0.15), ("Bear", 55, 0.08)]),
        finalist("LOSS", 50, [("Base", 60, 0.12), ("Bear", 40, -0.02)]),
    ]})
    ev = [{"claim": "Orders up 6%", "source": "10-Q Item 2", "date": "2026-08-01"}]
    return {
        "as_of": "2026-10-05", "profile": "value · years · moderate risk", "gate": json.loads(json.dumps(gate)),
        "funnel": [{"stage": "Industries scanned", "count": 40}, {"stage": "Merged pool", "count": 24}, {"stage": "Finalists", "count": 3}, {"stage": "Picks", "count": 2}],
        "industries": [
            {"sector": "Industrials", "industry": "Railroads", "verdict": "favored", "contrarian": False, "temperature": "Volumes recovering.",
             "growth": "Carloads +3% (AAR, 2026-09-30)", "sentiment": "Neutral.", "leaders": [{"ticker": "SAFE", "name": "Safe Rail", "trend": "gaining"}], "evidence": ev},
            {"sector": "Consumer Discretionary", "industry": "Homebuilders", "verdict": "unfavored", "contrarian": True, "temperature": "Rates bite.",
             "growth": "Starts -2% (Census, 2026-09-17)", "sentiment": "Gloomy.", "leaders": [{"ticker": "ABOVE", "name": "Above Homes", "trend": "steady"}], "evidence": ev},
        ],
        "candidates": [
            {"ticker": t, "name": f"{t} Inc", "industry": "Railroads", "origin": o, "held": t == "LOSS",
             "scores": {"quality": 4, "direction": 3, "tailwind": 4, "value": 3}, "reasons": {k: f"{k} reason" for k in ("quality", "direction", "tailwind", "value")},
             "missing": "Market misses X.", "bad_pick": "If Y.", "health": "passed", "finalist": t in ("SAFE", "ABOVE", "LOSS")}
            for t, o in (("SAFE", "both"), ("ABOVE", "industry"), ("LOSS", "screen"), ("OTHER", "screen"))
        ],
        "picks": {"SAFE": {"thesis": "Steady rail volumes at a fair price.", "bad_pick": "A freight recession."},
                  "ABOVE": {"thesis": "Cheap builder.", "bad_pick": "Rates to 8%."}},
        "missing_roles": [], "notes": ["Sample built from invented figures."],
    }


def _render(data, tmp_path, capsys):
    src = tmp_path / "pick.json"
    src.write_text(json.dumps(data))
    return run_json(load_script(RENDER), ["--in", str(src), "--out", str(tmp_path / "p.html")], capsys)


def test_render_pick_every_section(tmp_path, capsys) -> None:
    rc, res = _render(pick_input(), tmp_path, capsys)
    assert rc == 0, res
    assert res["picks"] == ["SAFE", "ABOVE"] and res["near_misses"] == ["LOSS"] and res["industries"] == 2 and res["candidates"] == 4
    assert "SAFE" in (tmp_path / "p.html").read_text()


def test_render_pick_no_passes(tmp_path, capsys) -> None:
    data = pick_input()
    data["gate"] = json.loads(json.dumps(load_script(GATE).run_gate({"finalists": [finalist("LOSS", 50, [("Base", 60, 0.12), ("Bear", 40, -0.02)])]})))
    data["picks"] = {}
    rc, res = _render(data, tmp_path, capsys)
    assert rc == 0 and res["picks"] == [] and res["near_misses"] == ["LOSS"]


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.pop("gate"), "gate"),
    (lambda d: d["industries"][0].update(verdict="great"), "verdict"),
    (lambda d: d["candidates"][0]["scores"].update(quality=6), "score"),
    (lambda d: d["picks"].update(LOSS={"thesis": "x", "bad_pick": "y"}), "LOSS"),
])
def test_render_pick_validation(mutate, needle, tmp_path, capsys) -> None:
    data = pick_input()
    mutate(data)
    rc, res = _render(data, tmp_path, capsys)
    assert rc == 2 and needle in res["error"]


def test_render_pick_rejects_undated_evidence(tmp_path, capsys) -> None:
    data = pick_input()
    del data["industries"][0]["evidence"][0]["date"]
    rc, res = _render(data, tmp_path, capsys)
    assert rc == 2 and "Railroads" in res["error"] and "date" in res["error"]


def test_render_pick_sample_is_current() -> None:
    """docs/samples/stock-picker.json is pick_input() as committed; regenerate it when this fails."""
    assert json.loads(SAMPLE.read_text()) == pick_input()


def test_render_pick_body_intros() -> None:
    import re
    from second_opinion import page
    body = load_script(RENDER).BODY
    for m in re.finditer(r'<section([^>]*)>\s*<h2[^>]*>(.*?)</h2>\s*(<p class="sub)?', body, re.S):
        assert m.group(3), f"section {m.group(2)!r} has no intro line"
    assert page.FLAGS_INTRO in body


@requires_chrome
def test_render_pick_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit(RENDER, ["--in", str(SAMPLE)], tmp_path, capsys)
    assert_page_help(a)
    assert {"Picks", "Near misses", "Industry map", "Candidates"} <= {c["h2"] for c in a["cards"] if not c["hidden"]}
```

- [ ] **Step 2: Run them and check they fail**

Run: `python3 -m pytest tests/test_scripts_stock_picker.py -q -k render`
Expected: FAIL (`render_pick.py` not found).

- [ ] **Step 3: Write `render_pick.py`**

```python
#!/usr/bin/env python3
"""Usage: render_pick.py [--in pick.json] --out page.html

Turns a deep-picker run into one self-contained HTML page for the Artifact tool. Input::

    {"as_of", "profile", "gate": <gate.py output>,
     "funnel": [{"stage", "count"}],
     "industries": [{"sector", "industry", "verdict": "favored"|"neutral"|"unfavored", "contrarian",
                     "temperature", "growth", "sentiment", "leaders": [{"ticker", "name", "trend"}],
                     "evidence": [{"claim", "source", "date"}]}],
     "candidates": [{"ticker", "name", "industry", "origin": "industry"|"screen"|"both", "held",
                     "scores": {"quality", "direction", "tailwind", "value"} (1-5),
                     "reasons": {...}, "missing", "bad_pick", "health", "finalist"}],
     "picks": {"SYMBOL": {"thesis", "bad_pick"}}, "missing_roles": [...], "notes": [...]}

Sections: Picks (each gate pass or pass_flagged result, with central and worst annual return,
thesis, what would make it a bad pick, and a link to its deep valuation; a plain "none passed"
card otherwise), Near misses (each fail with its reasons), Funnel, Industry map (grouped favored,
contrarian, neutral, unfavored; rows open to growth, sentiment and dated evidence), Candidates
(scores, sortable; rows open to the reasons), Flags. Prints {"out", "title", "picks",
"near_misses", "industries", "candidates", "flags"}. Exit 2 on a missing gate, an unknown industry
verdict, a score outside 1-5, an evidence claim without a source or date, or a picks entry that is
not a passing gate result. Every figure comes from the scripts; nothing is fetched at runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

VERDICTS = ("favored", "neutral", "unfavored")
SCORES = ("quality", "direction", "tailwind", "value")

BODY = """
<style>
.pickc{border:1px solid var(--grid);border-radius:8px;padding:12px 14px;margin:0 0 10px}
.pickc h3{margin:0 0 4px;font-size:16px}.pickc .r{font-variant-numeric:tabular-nums;font-size:13px;color:var(--muted)}
.pickc .t{margin:8px 0 4px;font-size:14px}.pickc .b{font-size:13px;color:var(--muted)}.pickc .w{font-size:13px;color:var(--warn);margin-top:6px}
.row{border-bottom:1px solid var(--grid);padding:8px 0}.row summary{cursor:pointer;display:flex;gap:10px;align-items:baseline;list-style:none}
.row summary::-webkit-details-marker{display:none}.row summary::after{content:'›';color:var(--muted);margin-left:auto;transition:transform .15s}.row[open] summary::after{transform:rotate(90deg)}
.row .n{font-weight:600}.row .m{color:var(--muted);font-size:12px}.row .d{font-size:13px;margin-top:6px}.row ul{margin:6px 0 0;padding-left:18px;font-size:13px}
.lg{font-size:13px;margin:14px 0 2px}.lg.favored{color:var(--s1)}.lg.unfavored{color:var(--warn)}.lg.contrarian{color:var(--s3)}.lg.neutral{color:var(--muted)}
.src{color:var(--muted);font-size:12px}
</style>
<h1 id="h1">Deep picks</h1>
<p class="sub" id="sub"></p>
<div id="intro"></div>
<section class="card" id="picks-card"><h2>Picks</h2><p class="sub">Finalists whose deep valuation shows no scenario losing money over five years and a central case that clears the hurdle.</p><div id="picks"></div></section>
<section class="card" id="near-card"><h2>Near misses</h2><p class="sub">Finalists that were valued in depth but failed the downside gate, and why.</p><div id="near"></div></section>
<section class="card" id="funnel-card"><h2>Funnel</h2><p class="sub">How many companies were left after each stage of the search.</p><div id="funnel"></div></section>
<section class="card" id="ind-card"><h2>Industry map</h2><p class="sub">Each industry the scan covered, grouped by its verdict, with the leaders and the dated evidence behind the call.</p><div id="ind"></div></section>
<section class="card" id="cand-card"><h2>Candidates</h2><p class="sub">Every company in the merged pool, scored 1 to 5 on business quality, direction, industry tailwind and price against value.</p><div class="twrap" id="cand"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Industry verdicts and candidate scores are judgement backed by dated evidence, not forecasts. A pick passed a downside test on stated assumptions; it is not a recommendation. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, G = D.gate, g = id => document.getElementById(id), esc = F.esc;
  const pct = v => F.isNum(v) ? F.pct(v, 1, true) : '—', money = v => F.isNum(v) ? F.money(v) : '—';
  const passes = G.results.filter(r => r.verdict !== 'fail'), fails = G.results.filter(r => r.verdict === 'fail');
  g('sub').textContent = `As of ${D.as_of}${D.profile ? ' · ' + D.profile : ''} · hurdle ${F.pct(G.hurdle, 1)} · floor ${F.pct(G.floor, 1)}`;
  F.intro(g('intro'), {lead: `${passes.length} of ${G.results.length} finalists passed the downside gate: no scenario loses money over five years, and the central case earns at least ${F.pct(G.hurdle, 1)} a year at today’s price.`});

  g('picks').innerHTML = passes.length ? passes.map(r => { const p = (D.picks || {})[r.symbol] || {};
    return `<div class="pickc"><h3>${esc(r.symbol)}</h3><div class="r">Central ${esc(r.central.name)} ${pct(r.central.irr)} a year · worst ${esc(r.worst.name)} ${pct(r.worst.irr)} · price ${money(r.price)}</div>
      ${p.thesis ? `<div class="t">${esc(p.thesis)}</div>` : ''}${p.bad_pick ? `<div class="b"><b>What would make this a bad pick:</b> ${esc(p.bad_pick)}</div>` : ''}
      ${r.verdict === 'pass_flagged' ? `<div class="w">${esc(r.reasons[r.reasons.length - 1])}</div>` : ''}
      ${r.page ? `<div class="b" style="margin-top:6px"><a href="${esc(r.page)}" target="_blank" rel="noopener">Deep valuation →</a></div>` : ''}</div>`; }).join('')
    : '<p><b>No finalist passed the downside gate.</b> The near misses below show which test each failed.</p>';
  F.help(g('picks-card'), {lead: 'A pick is a finalist whose deep valuation passed two tests at today’s price: no scenario loses money over five years, dividends included, and the central scenario earns at least the hurdle. A warning line means every scenario sits above the price, which can mean a downside case is missing.'});

  g('near').innerHTML = fails.length ? fails.map(r => `<details class="row"><summary><span class="n">${esc(r.symbol)}</span><span class="m">central ${pct(r.central.irr)} · worst ${r.worst ? pct(r.worst.irr) : '—'}</span></summary>
      <ul>${r.reasons.map(x => `<li>${esc(x)}</li>`).join('')}</ul>${r.page ? `<div class="d"><a href="${esc(r.page)}" target="_blank" rel="noopener">Deep valuation →</a></div>` : ''}</details>`).join('')
    : '<p class="muted">None: every finalist passed.</p>';
  F.help(g('near-card'), {lead: 'Finalists that were valued in depth and failed: a scenario that loses money, a central case below the hurdle, or a return that could not be computed.'});

  const fmax = Math.max(1, ...(D.funnel || []).map(s => s.count || 0));
  F.bars(g('funnel'), (D.funnel || []).map((s, i) => ({label: s.stage, share: (s.count || 0) / fmax, text: String(s.count), color: F.S[i % 8]})));
  F.help(g('funnel-card'), {lead: 'The search narrows in stages: industries scanned, screen survivors, the merged pool, the health check, quick reads, finalists and picks.'});

  const groups = [['favored', 'Favored', i => i.verdict === 'favored' && !i.contrarian], ['contrarian', 'Contrarian: out of favour, fundamentals improving', i => i.contrarian],
                  ['neutral', 'Neutral', i => i.verdict === 'neutral' && !i.contrarian], ['unfavored', 'Unfavored', i => i.verdict === 'unfavored' && !i.contrarian]];
  const ev = xs => (xs || []).map(x => `<li>${esc(x.claim)} <span class="src">${esc(x.source)}, ${esc(x.date)}</span></li>`).join('');
  g('ind').innerHTML = groups.map(([k, t, f]) => { const xs = (D.industries || []).filter(f); return xs.length ? `<h3 class="lg ${k}">${esc(t)} <span class="muted">(${xs.length})</span></h3>` + xs.map(i =>
    `<details class="row"><summary><span class="n">${esc(i.industry)}</span><span class="m">${esc(i.sector)} · ${esc(i.temperature)}</span></summary>
      <div class="d"><b>Leaders:</b> ${(i.leaders || []).map(l => `${esc(l.ticker)} (${esc(l.trend)})`).join(', ') || '—'}</div>
      <div class="d"><b>Growth:</b> ${esc(i.growth || '—')}</div><div class="d"><b>Sentiment:</b> ${esc(i.sentiment || '—')}</div><ul>${ev(i.evidence)}</ul></details>`).join('') : ''; }).join('');
  F.help(g('ind-card'), {lead: 'The industry scan’s call on each industry, from dated growth forecasts, cycle position, pricing power, policy, structural threats, sentiment and valuation against its own history. Contrarian industries are out of favour while their fundamentals improve.'});

  const rows = (D.candidates || []).map(c => ({...c, total: SCORES.reduce((a, k) => a + (c.scores[k] || 0), 0), ...Object.fromEntries(SCORES.map(k => [k, c.scores[k]]))}));
  F.table(g('cand'), [
    {key: 'ticker', label: 'Ticker', left: true, fmt: (v, r) => `<b>${esc(v)}</b>${r.held ? ' <span class="muted">held</span>' : ''}${r.finalist ? ' ★' : ''}`},
    {key: 'industry', label: 'Industry', left: true}, {key: 'origin', label: 'Found by', left: true},
    ...SCORES.map(k => ({key: k, label: {quality: 'Quality', direction: 'Direction', tailwind: 'Tailwind', value: 'Value'}[k]})),
    {key: 'total', label: 'Total'}, {key: 'health', label: 'Health', left: true},
  ], rows, {sortKey: 'total'});
  F.help(g('cand-card'), {lead: 'Every company in the merged pool. Each score runs 1 to 5 and comes from a quick read of the filings and dated news; ★ marks a finalist.',
    sections: [{title: 'Reasons', html: rows.map(r => `<p><b>${esc(r.ticker)}</b>: ${SCORES.map(k => esc(r.reasons[k] || '')).join(' · ')}. <i>Missing:</i> ${esc(r.missing || '—')} <i>Bad pick if:</i> ${esc(r.bad_pick || '—')}</p>`).join('')}]});

  const flags = [...(D.missing_roles || []).map(r => ({code: 'RESEARCH_MISSING', message: `The ${r} did not complete, so its findings are absent.`})), ...(D.notes || []).map(n => ({code: 'NOTE', message: n}))];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${esc(f.code)}</b>${esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
""".replace("SCORES", '["quality","direction","tailwind","value"]')


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render_pick.py: {message}")


def _validate(data: dict) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a JSON object")
    gate = data.get("gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("results"), list):
        raise InvalidInput("gate (a gate.py result) is required")
    for i in data.get("industries") or []:
        name = i.get("industry", "?")
        if i.get("verdict") not in VERDICTS:
            raise InvalidInput(f"industry {name}: verdict must be one of {', '.join(VERDICTS)}")
        for e in i.get("evidence") or []:
            for f in ("claim", "source", "date"):
                if not e.get(f):
                    raise InvalidInput(f"industry {name}: an evidence claim has no {f}")
    for c in data.get("candidates") or []:
        for k in SCORES:
            v = (c.get("scores") or {}).get(k)
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5:
                raise InvalidInput(f"candidate {c.get('ticker', '?')}: score {k} must be a whole number from 1 to 5")
    passing = {r["symbol"] for r in gate["results"] if r.get("verdict") in ("pass", "pass_flagged")}
    for sym in data.get("picks") or {}:
        if sym not in passing:
            raise InvalidInput(f"picks has {sym}, which did not pass the gate")


def build(data: dict) -> tuple[str, str, dict]:
    _validate(data)
    title = "Deep Picks"
    markup = page.render(title, data, BODY, SCRIPT)
    res = data["gate"]["results"]
    info = {"title": title, "picks": [r["symbol"] for r in res if r["verdict"] != "fail"],
            "near_misses": [r["symbol"] for r in res if r["verdict"] == "fail"],
            "industries": len(data.get("industries") or []), "candidates": len(data.get("candidates") or []),
            "flags": len(data.get("missing_roles") or []) + len(data.get("notes") or [])}
    return title, markup, info


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render_pick.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read the deep-picker JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
```

Then run `chmod +x`.

- [ ] **Step 4: Generate the sample and run the tests**

```bash
cd tests && python3 -c "import json, test_scripts_stock_picker as t; open('../docs/samples/stock-picker.json','w').write(json.dumps(t.pick_input(), indent=1) + '\n')" && cd ..
python3 -m pytest tests/test_scripts_stock_picker.py -q
```

Expected: all PASS, with the Chrome test included when Chrome is present.

- [ ] **Step 5: Screenshot check, then commit**

Render the sample with headless Chrome and look at it. Fix any layout problem, then:

```bash
git add skills/stock-screener/scripts/render_pick.py docs/samples/stock-picker.json tests/test_scripts_stock_picker.py
git commit -m "feat(stock-screener): render_pick.py, the deep picks page"
```

### Task 4: Role briefs

**Files:**
- Create: `skills/stock-screener/references/picker-roles.md`
- Modify: `tests/test_skills_structure.py` (`REFERENCE_FILES`)

- [ ] **Step 1:** Register `"stock-screener/references/picker-roles.md",` in `REFERENCE_FILES`. Run the structure tests and check they fail (the file is missing).
- [ ] **Step 2:** Write `picker-roles.md`:
  - a `## Contents` list
  - `## Shared rules`: adapted from `valuation/references/deep-roles.md` Shared rules, with the run folder `DIR/pick-DATE/` and file names starting with the role
  - `## Industry scanner`
  - `## Quick reader`

  The content follows spec §4: the sector groups, the per-industry fields with the JSON shape that `render_pick.py` takes, the contrarian rule, the quick-read card fields, the four scores with what 1 and 5 mean for each, and the financial-filer health judgement. Use no banned words.
- [ ] **Step 3:** Run `grep -niE "\b(recommend\w*|advis\w*|should|suggest\w*)\b"` on it (expect no output), then `python3 -m pytest tests/test_skills_structure.py -q`. Expect a FAIL only on "linked from SKILL.md"; Task 5 fixes that.
- [ ] **Step 4:** Commit: `feat(stock-screener): role briefs for the deep picker`.

### Task 5: `SKILL.md` and docs

**Files:**
- Modify: `skills/stock-screener/SKILL.md`, `docs/scripts.md`, `docs/examples.md`, `CHANGELOG.md`

- [ ] **Step 1:** Make the description mention deep picks and stay at or under 260 characters. Add to the opening line one sentence on the deep picker.
- [ ] **Step 2:** In Background, add:
  - `### Two modes`: the funnel, and the deep picker with its trigger words
  - `### Deep picker`: the run folder table, `gate.py` and `render_pick.py`, the health preset row in the Presets table, and `--symbols` in the screen.py notes
  - the link line for `references/picker-roles.md`
- [ ] **Step 3:** Under Scripts, add the `gate.py` and `render_pick.py` commands and table rows, `--symbols` in the `screen.py` command, and `health` in the preset list.
- [ ] **Step 4:** In Steps, add the `**Deep picker**` case: steps 1–11 from spec §5, written compactly.
- [ ] **Step 5:** In Reply format, add the deep-picker reply. In Rules, add the three deep-picker rules.
- [ ] **Step 6:** Run `wc -l skills/stock-screener/SKILL.md` (expect ≤ 500) and `python3 -m pytest tests/test_skills_structure.py -q` (expect PASS).
- [ ] **Step 7:** Docs:
  - `docs/scripts.md` rows for `gate.py` and `render_pick.py`
  - the `screen.py` row gains `--symbols` and `health`
  - a `CHANGELOG.md` Unreleased line
  - a `docs/examples.md` prompt: "Find me the best opportunities right now: deep picks."
- [ ] **Step 8:** Run `python3 -m pytest tests -q` (expect all PASS). Commit: `feat(stock-screener): deep picker procedure, reply and docs`.

### Task 6: Manual end-to-end deep-picker run

- [ ] Follow the `**Deep picker**` steps on real data with the person's profile, using 3 finalists to keep the run bounded.
- [ ] Check the spec's success criteria:
  - the page has picks, or says plainly that none passed
  - near-misses carry reasons
  - the industry map has dated evidence
  - candidates have scores
  - each finalist links to its deep page
- [ ] Fold any procedure defects back into `SKILL.md` or `picker-roles.md`, each with a commit. Code defects get a failing test first.
