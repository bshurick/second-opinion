# Core/satellite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `core-satellite` skill that measures the ETF-core / individual-pick-satellite split, sizes the satellite under a ceiling the person agreed, splits money across picks by current size or (on request) by deep valuation, sizes new picks, plans gradual increases, and hands the resulting trades to rebalancing's engine for lots and tax.

**Architecture:** Pure math lives in two stdin→stdout-style modules (`weights.py` for sizing and weighting, `sleeves.py` for modes and per-account trade plans), which call `rebalance.run_rebalance` once per trading account so lot picking and tax estimates are not duplicated. A fetching wrapper `run.py` reads holdings live (shared reader extracted from rebalancing's `plan.py`), classifies holdings, reads the pick store and the saved settings. A small store CLI `settings.py` keeps the person's decisions, increases and plan, and prints a SessionStart line when a plan step is due.

**Tech Stack:** Python 3 stdlib, the repo's `lib/second_opinion` (router, market, ledger, output, profile), pytest with `tests/fakes.py` and `tests/scripts_util.py`.

**Spec:** `docs/superpowers/specs/2026-10-29-core-satellite-design.md`

**Scope:** This plan covers the spec's rebalancing changes and the `core-satellite` skill. The `equity-comp` skill is a second plan, written after this one ships; it feeds deposits into `run.py deposit`. Until then the employer bucket is driven by the saved `employer_symbol` setting.

**Baseline:** `python3 -m pytest tests -q` → 2586 passed, 1 failed (`tests/test_market_snapshot.py::test_next_events_from_calendar_dict`, pre-existing, unrelated). "Full suite passes" below means no new failures beyond that one.

## Global Constraints

- Skill text follows `docs/skill-style.md`: `##` headings exactly Background, Scripts, Steps, Reply format, Rules (Rules last, ending with the shared compliance bullets copied verbatim from `skills/watchlist/SKILL.md`); description ≤260 chars, contains "Use when", no ": ".
- No "recommend", "advise", "should", "suggest" (any form) in SKILL.md, references, script docstrings or script output text. The spec's "suggested ceiling" is worded "default ceiling" / "proposed size".
- Numbers come from scripts; each script prints one JSON object (except `summary`, plain text); exit codes 0, 2 bad input, 4 credentials/ETRADE_REAUTH (with `--partial`), 5 API error, 6 missing deps.
- New scripts are executable, have a `__main__` guard, and a docstring starting "Usage:".
- Orders are never placed by this skill; trades go through portfolio-analysis's protocol with a human yes.
- Picks live in trading accounts only; retirement accounts hold only core. Each sale and buy stay in the same account.
- Employer stock is its own bucket: not satellite, not in the ceiling, N_eff or tracking error, never receives satellite money. `EMPLOYER_CONCENTRATION` when it is >10% of total value.
- Default ceiling 0.20 of total investable value; never exceeded unless the person passes `--over-ceiling`.
- Default weighting `size`. Valuation tilt uses deep picks only; light picks are used only with `include_light` true and stay flagged.
- Short-term gains in taxable accounts: default policy `hold`, raised with the person once (`DECISION_NEEDED`), saved.
- Constants (in `weights.py`): `DEFAULT_CEILING = 0.20`, `SIGMA_IDIO = 0.30`, `TE_BUDGET = 0.015`, `MIN_N_EFF = 15`, `SECTOR_HEAVY = 0.25`, `SECTOR_HAIRCUT = 0.75`, `PICK_CAP = 0.05`, `MARKET_RETURN = 0.07`, `SHRINK_K = 0.5`, `TILT_LAMBDA = 0.5`, `HALF_LIFE_DAYS = 182`.
- Money 2 dp, weights 4 dp (same `_r2`/`_r4` rounding as `rebalance.py`).

## Review Focus

1. A pick held in two trading accounts and also in a retirement account: buys go to the trading account holding the larger value of it; the retirement copy is flagged `PICK_IN_RETIREMENT` and untouched. (Task 5 test `test_add_routes_to_larger_trading_holding`.)
2. `add` for more than the trading accounts' cash: exit 2 with the available cash in the message, no partial plan. (Task 5 test `test_add_more_than_trading_cash_is_bad_input`.)
3. Valuation mode where no pick is eligible (all light, stale or re-check due): falls back to size weights with `VALUATION_FALLBACK`, never divides by zero. (Task 6 test `test_valuation_with_no_eligible_picks_falls_back`.)
4. A holding with no price (quote and broker price both missing): left out with `NO_PRICE`, the rest of the plan still runs. (Task 8 test `test_run_skips_holding_without_price`.)
5. An overvalued pick whose only lots are short-term gains under policy `hold`: trim is 0, a `held_back` row carries the value and `long_term_date`; freed money does not appear in buys. (Task 6 test `test_overvalued_short_term_lots_are_held_back`.)

---

### Task 1: rebalance.py — buy unheld symbols, sell a class by smallest gain

**Files:**
- Modify: `skills/rebalancing/scripts/rebalance.py` (docstring contract; input parsing near :175-213; full-mode class loop :295-362; contribution loop :363-405)
- Test: `tests/test_scripts_rebalancing.py`

**Interfaces:**
- Produces: `run_rebalance(params)` accepts two new optional inputs:
  - `"new_positions": [{"symbol", "price", "account"?}]` — symbols with a target (or a class) but no holding; each becomes a zero-unit member so buys can reach it. A symbol also in `positions` is bad input.
  - `"class_sells": "pro_rata" | "smallest_gain"` (default `"pro_rata"`). With `smallest_gain`, a class's sell amount is filled member by member in ascending order of unrealized gain ratio `(price − avg cost) / price` (avg cost from that symbol's `lots`, members without lots last), losses first, instead of pro rata. Buys are unchanged.
  - Lots may carry `"acquired": "YYYY-MM-DD"`; it is echoed in each picked lot row.

- [ ] **Step 1: Write the failing tests**

```python
REB = "rebalancing/scripts/rebalance.py"

def test_new_position_gets_a_buy() -> None:
    out = load_script(REB).run_rebalance({
        "positions": [{"symbol": "VTI", "units": 90, "price": 100.0}], "cash": 1000,
        "targets": {"VTI": 0.9, "NEW": 0.1}, "new_positions": [{"symbol": "NEW", "price": 50.0}]})
    assert [(t["symbol"], t["side"], t["value"]) for t in out["trades"]] == [("NEW", "BUY", 1000.0)]
    assert not any(f["code"] == "NO_HOLDINGS" for f in out["flags"])

def test_new_position_already_held_is_bad_input() -> None:
    with pytest.raises(ValueError, match="already held"):
        load_script(REB).run_rebalance({"positions": [{"symbol": "VTI", "units": 1, "price": 1.0}],
            "targets": {"VTI": 1.0}, "new_positions": [{"symbol": "VTI", "price": 1.0}]})

def test_class_sells_smallest_gain_sells_loss_member_first() -> None:
    params = {"positions": [{"symbol": "VTI", "units": 50, "price": 100.0}, {"symbol": "VXUS", "units": 50, "price": 100.0}],
              "new_positions": [{"symbol": "AAA", "price": 100.0}],
              "cash": 0, "targets": {"core": 0.8, "AAA": 0.2}, "classes": {"VTI": "core", "VXUS": "core"},
              "lots": {"VTI": [{"units": 50, "cost_per_unit": 60.0, "term": "long"}],
                       "VXUS": [{"units": 50, "cost_per_unit": 110.0, "term": "long", "acquired": "2024-01-02"}]},
              "class_sells": "smallest_gain"}
    out = load_script(REB).run_rebalance(params)
    sells = [(t["symbol"], t["value"]) for t in out["trades"] if t["side"] == "SELL"]
    assert sells == [("VXUS", 2000.0)]
    assert out["trades"][0]["lots"][0]["acquired"] == "2024-01-02"

def test_class_sells_default_is_still_pro_rata() -> None:
    # same params without class_sells -> VTI and VXUS each sell 1000.0
    ...
```

(Fill the last test with the same params minus `class_sells`, asserting `sorted(sells) == [("VTI", 1000.0), ("VXUS", 1000.0)]`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_scripts_rebalancing.py -k "new_position or class_sells" -v`
Expected: FAIL (NO_HOLDINGS flag / KeyError on `acquired` / pro-rata sells).

- [ ] **Step 3: Implement in `rebalance.py`**

Append `new_positions` rows to `positions` with `units: 0.0`, `value: 0.0`, keyed like held symbols (symbol target, else class), after validating `symbol` and `price`. Member share for buys when a class's value is 0 already falls back to equal split; for a zero-value member inside a class with value, give buys to it only when it is a symbol-keyed target (class buys stay pro rata). Add the `smallest_gain` branch in both the routing and non-routing sell paths: compute each member's gain ratio, sort, and take `min(member value, remaining)` from each in turn (tax-advantaged-first routing still applies within a symbol). Update the docstring contract with both inputs and `acquired`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_scripts_rebalancing.py -v`
Expected: all PASS (old and new).

- [ ] **Step 5: Commit**

```bash
git add skills/rebalancing/scripts/rebalance.py tests/test_scripts_rebalancing.py
git commit -m "feat(rebalancing): buy unheld symbols and sell a class by smallest gain"
```

---

### Task 2: plan.py — shared holdings reader with per-account cash and lot dates

**Files:**
- Modify: `skills/rebalancing/scripts/plan.py` (`_replay_lots` :94; the book/lots block in `main` ~:270-340)
- Test: `tests/test_scripts_rebalancing.py`

**Interfaces:**
- Produces: `read_book(hub, accounts: list[dict], today: date) -> dict` returning
  `{"positions": [{"symbol", "units", "price", "account"}], "cash_by_account": {aid: float}, "lots": {SYM: [lot]}, "lot_sources": {SYM: "ledger"|"snaptrade"}, "sources": {"holdings", "prices", "lots"}, "holdings_by_account": {aid: [SYM]}, "no_price": [SYM]}`.
  Ledger-replayed lots carry `"acquired"` (the BUY date). `plan.py main` calls it and keeps its output byte-for-byte (cash = sum of `cash_by_account`).
- Produces: `is_tax_advantaged(raw_type) -> bool` (rename of `_is_tax_advantaged`; keep the old name as an alias).

- [ ] **Step 1: Write the failing test**

```python
def test_read_book_splits_cash_by_account(sdk) -> None:
    plan = load_script("rebalancing/scripts/plan.py")
    hub = router.load()
    book = plan.read_book(hub, hub.list_accounts(), date(2026, 10, 29))
    assert book["cash_by_account"] == {"acc-1": 300.0, "acc-2": 200.0}
    assert {(p["symbol"], p["account"]) for p in book["positions"]} == {("VTI", "acc-1"), ("BND", "acc-2")}
    assert book["no_price"] == []

def test_replayed_lots_carry_acquired_date() -> None:
    plan = load_script("rebalancing/scripts/plan.py")
    lots = plan._replay_lots([{"type": "BUY", "symbol": "VTI", "units": 5, "price": 10, "date": "2025-03-04", "account_id": "a"}], date(2026, 10, 29))
    assert lots["VTI"][0]["acquired"] == "2025-03-04"
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_scripts_rebalancing.py -k "read_book or acquired" -v`
Expected: FAIL (`read_book` not defined / no `acquired`).

- [ ] **Step 3: Implement** — move the positions/balances/quotes/lots block out of `main` into `read_book`; symbols with no price go to `no_price` instead of being silently skipped; `main` builds `params` from it.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_scripts_rebalancing.py -v`
Expected: all PASS, existing plan tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add skills/rebalancing/scripts/plan.py tests/test_scripts_rebalancing.py
git commit -m "refactor(rebalancing): shared holdings reader with per-account cash and lot dates"
```

---

### Task 3: weights.py — sizing and weighting math

**Files:**
- Create: `skills/core-satellite/scripts/weights.py`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Produces (all pure, no I/O; constants from Global Constraints):
  - `n_eff(values: dict[str, float]) -> float` — `1 / Σ w²` over the normalized values; 0 for empty.
  - `tracking_error(w_sat: float, n: float) -> float` — `w_sat * SIGMA_IDIO / sqrt(n)`; 0 when `n == 0`.
  - `proposed_size(ceiling: float, n: float, sector_heavy: bool) -> float` — `min(ceiling, TE_BUDGET * sqrt(n) / SIGMA_IDIO)`, times `SECTOR_HAIRCUT` when `sector_heavy`; 4 dp.
  - `size_split(current: dict[str, float], amount: float) -> dict[str, float]` — amount pro rata to current value (equal split when all zero).
  - `confidence(age_days: int, recheck_due: bool) -> float` — `0.0` if `recheck_due`, else `0.5 ** (age_days / HALF_LIFE_DAYS)`.
  - `valuation_targets(picks: list[dict], target_total: float, portfolio_total: float) -> dict` with each pick `{"symbol", "value", "price", "central_value", "expected_return", "eligible": bool, "confidence"}`; returns `{"targets": {SYM: value}, "scores": {SYM: shrunk_alpha|None}, "capped": [SYM], "fallback": bool}`.
  - `median_pick_value(current: dict[str, float]) -> float`.

`valuation_targets` algorithm (not determined by the signature):

```
eligible = picks with eligible and confidence > 0
if not eligible: return size_split targets with fallback True
a_i  = SHRINK_K * confidence_i * (expected_return_i - MARKET_RETURN)
z_i  = (a_i - mean(a)) / pstdev(a)   (z_i = 0 when pstdev is 0)
raw_i = value_i * max(0, 1 + TILT_LAMBDA * z_i)        for eligible, not overvalued
raw_i = value_i * central_value_i / price_i            for overvalued (price > central_value)
raw_i = value_i                                         for ineligible
overvalued targets are fixed at raw_i (not scaled);
scale the other raw_i so Σ(all targets) = target_total, then water-fill:
  - no pick below its current value unless overvalued (non-overvalued floor = current value)
  - no pick above PICK_CAP * portfolio_total (record in capped)
  - excess from floors/caps goes to uncapped, non-overvalued eligible picks with z_i > 0, pro rata
    to raw_i; if none, to all uncapped non-overvalued picks pro rata to raw_i
```

- [ ] **Step 1: Write the failing tests**

```python
W = "core-satellite/scripts/weights.py"

def test_n_eff_and_tracking_error() -> None:
    w = load_script(W)
    assert w.n_eff({f"S{i}": 1.0 for i in range(15)}) == pytest.approx(15.0)
    assert w.tracking_error(0.20, 15) == pytest.approx(0.0155, abs=1e-4)

def test_proposed_size_caps_by_ceiling_te_and_sector() -> None:
    w = load_script(W)
    assert w.proposed_size(0.20, 25, False) == 0.20
    assert w.proposed_size(0.20, 5, False) == 0.1118
    assert w.proposed_size(0.20, 25, True) == 0.15

def test_confidence_halves_every_half_life_and_zero_when_due() -> None:
    w = load_script(W)
    assert w.confidence(182, False) == pytest.approx(0.5)
    assert w.confidence(10, True) == 0.0

def test_valuation_tilts_toward_higher_return_and_trims_overvalued() -> None:
    w = load_script(W)
    picks = [
        {"symbol": "A", "value": 1000, "price": 50, "central_value": 80, "expected_return": 0.20, "eligible": True, "confidence": 1.0},
        {"symbol": "B", "value": 1000, "price": 50, "central_value": 60, "expected_return": 0.09, "eligible": True, "confidence": 1.0},
        {"symbol": "C", "value": 1000, "price": 50, "central_value": 40, "expected_return": 0.02, "eligible": True, "confidence": 1.0},
    ]
    out = w.valuation_targets(picks, target_total=4000, portfolio_total=100000)
    t = out["targets"]
    assert t["C"] == pytest.approx(800.0)          # trimmed to 40/50 of its value
    assert t["A"] > t["B"] >= 1000.0               # top end gets more, B not cut
    assert sum(t.values()) == pytest.approx(4000.0)

def test_valuation_respects_pick_cap() -> None:
    # A alone eligible-high; portfolio_total 30000 -> cap 1500
    ...
```

(Fill the cap test: same three picks, `portfolio_total=30000`, assert `t["A"] == 1500.0`, `"A" in out["capped"]`, total still 4000.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -k "n_eff or proposed or confidence or valuation_t" -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `weights.py`** with the signatures and algorithm above. Docstring starts "Usage: imported by sleeves.py; no command line." plus a `__main__` guard that prints a one-line usage error and exits 2.

- [ ] **Step 4: Run tests** — same command, expected PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/weights.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): sizing and weighting math"
```

---

### Task 4: settings.py — decisions, increases, plan and hook summary

**Files:**
- Create: `skills/core-satellite/scripts/settings.py`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Store: `<data_dir>/core-satellite.json` (`data_dir` = `ledger.ledger_path().parent`), shape from the spec:
  `{"ceiling", "ceiling_agreed_on", "weighting", "include_light", "short_term_gain_policy", "employer_symbol", "decisions": [{"date","key","value"}], "increases": [{"date","amount","weight_before","weight_after","funded_from"}], "plan": null | {"target","by_date","cadence","step_amount","funding","status","next_due","created"}}`.
  Unset keys are `null`; readers treat `null` ceiling as `DEFAULT_CEILING` with `DECISION_NEEDED`.
- Produces (importable): `load() -> dict`, `save(store) -> Path`, `decide(store, key, raw, today) -> dict`, `record_increase(store, row) -> dict`, `summary_lines(today) -> list[str]`.
- CLI:
  - `settings.py show`
  - `settings.py decide KEY VALUE` — keys and values: `ceiling` (0 < x ≤ 1), `weighting` (`size|valuation`), `include_light` (`true|false`), `short_term_gain_policy` (`hold|allow`), `employer_symbol` (ticker or `none`). Appends to `decisions`; `ceiling` also sets `ceiling_agreed_on`.
  - `settings.py record-increase --amount A --before W --after W --funded-from TEXT [--date D]`
  - `settings.py plan-set --target W --by YYYY-MM-DD --cadence monthly|quarterly --funding cash|core` — `next_due` = today; `step_amount` left null (computed per step by `run.py plan-step`).
  - `settings.py plan-pause | plan-resume | plan-cancel | plan-advance` (`plan-advance` moves `next_due` by one cadence; status `done` once past `by_date`).
  - `settings.py summary` — plain text, no network, always exit 0; prints `Core/satellite: plan step due since NEXT_DUE (target T by BY_DATE); ask Claude to run it.` when status `active` and `next_due <= today`; nothing otherwise.

- [ ] **Step 1: Write the failing tests**

```python
S = "core-satellite/scripts/settings.py"

def test_decide_records_and_validates(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = run_json(load_script(S), ["decide", "ceiling", "0.15"], capsys)
    assert rc == 0 and out["ceiling"] == 0.15 and out["decisions"][-1]["key"] == "ceiling"
    rc, out = run_json(load_script(S), ["decide", "weighting", "kelly"], capsys)
    assert rc == 2 and "size" in out["error"]

def test_summary_prints_due_plan_step(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    s = load_script(S)
    (tmp_path / "core-satellite.json").write_text(json.dumps({"plan": {"target": 0.18, "by_date": "2027-04-30", "cadence": "monthly", "status": "active", "next_due": "2026-10-28"}}))
    assert s.summary_lines(date(2026, 10, 29)) == ["Core/satellite: plan step due since 2026-10-28 (target 18.0% by 2027-04-30); ask Claude to run it."]
    assert s.summary_lines(date(2026, 10, 27)) == []

def test_plan_advance_moves_next_due_and_finishes(tmp_path, monkeypatch, capsys) -> None:
    # plan-set on 2026-10-29 monthly by 2026-12-15; advance twice -> next_due 2026-11-29 then status done
    ...
```

(Fill the last test with `--date`-free calls by monkeypatching `settings.date` or passing `--today` — add a hidden `--today YYYY-MM-DD` flag to every subcommand for tests.)

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_scripts_core_satellite.py -k "decide or summary or plan_advance" -v` → FAIL.
- [ ] **Step 3: Implement `settings.py`** using `second_opinion.output.run` for JSON subcommands (as `picks.py` does) and plain `print` for `summary`.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/settings.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): settings store, decisions, increase plan and hook summary"
```

---

### Task 5: sleeves.py — mix, add and deposit with per-account plans (size weighting)

**Files:**
- Create: `skills/core-satellite/scripts/sleeves.py`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: `weights.*` (Task 3); `rebalance.run_rebalance` with `new_positions`, `class_sells` (Task 1), imported via `sys.path` from `skills/rebalancing/scripts`.
- Produces: `run_sleeves(params: dict) -> dict`. Input:
  ```
  {"mode": "mix"|"add"|"deposit"|"grow"|"new-pick"|"plan-step",
   "positions": [{"symbol","units","price","account","bucket": "core"|"satellite"|"employer"|"cash"}],
   "accounts": {aid: {"role": "trading"|"retirement"|"savings"}},
   "cash_by_account": {aid: float},
   "settings": <settings.json content>,
   "picks": {SYM: {"kind","central_value","expected_return","age_days","recheck_due"}},
   "sectors": {SYM: str}, "employer_sector": str|None,
   "lots": {...}, "rates": {...}, "today": "YYYY-MM-DD",
   "amount": float?, "satellite_amount": float?, "over_ceiling": bool?, "whole_shares": bool?,
   "weighting": "size"|"valuation"?, "include_light": bool?}
  ```
  Output:
  ```
  {"mode", "mix": {"total","core","satellite","employer","cash" each {value, weight},
          "trading_value","retirement_value","n_eff","tracking_error","ceiling","ceiling_source": "saved"|"default",
          "proposed_size","room_under_ceiling","single_stock_total"},
   "weighting_used", "splits": [{"symbol","current","size_target","valuation_target"|None,"target","delta","account","flags"}],
   "held_back": [{"symbol","value","account","long_term_date"}],
   "accounts": [{"account", "funding": {"cash","core_sells"}, "rebalance": <run_rebalance output>}],
   "trades": [all accounts' trades, each with "account"],
   "readings": null | {...}, "similar_to_last": null | {...}, "over_ceiling_amount": float,
   "settings_used": {"ceiling","weighting","include_light","short_term_gain_policy"},
   "flags": [{code, message}]}
  ```
  Flag codes added here: `DECISION_NEEDED` (message names the key), `PICK_IN_RETIREMENT`, `EMPLOYER_CONCENTRATION`, `LOW_N_EFF` (N_eff < 15), `SECTOR_HEAVY`, `ABOVE_CEILING`, `NO_SATELLITE`.

Rules pinned for this task:
- Total = all positions in all accounts + all cash. Satellite = `bucket == "satellite"` in trading accounts; satellite-bucket holdings in retirement accounts count as satellite value but get `PICK_IN_RETIREMENT` and no trades.
- `sector_heavy` = satellite share in `employer_sector` or `"Technology"` ≥ `SECTOR_HEAVY`.
- `add`: satellite gets `amount` from trading cash; error (ValueError → exit 2) when `amount` > Σ trading cash, message `"only {cash:.2f} cash in trading accounts"`. If the result would exceed the ceiling (saved, or default when unset) and not `over_ceiling`, buys are limited to `room_under_ceiling` and the rest is `over_ceiling_amount` with `ABOVE_CEILING`. Each pick's delta goes to the trading account holding the larger value of it; a pick's buys in an account are funded by that account's cash; an account short of cash takes the shortfall from the other trading account's picks' deltas only if that account holds them, else the delta is scaled down and `ACCOUNT_SHORT` is flagged.
- Per trading account, call `run_rebalance` with that account's positions (core symbols mapped to class `core`, picks as symbol keys, employer and retirement rows excluded), targets computed so each pick lands on its target value, core keeps its value (add/deposit) and `CASH` takes the rest; `allow_sells` true, `class_sells` `smallest_gain`.
- `deposit`: `amount` is new cash already in trading accounts. Without `satellite_amount`, output is a proposal only (no trades): `proposal = {"satellite": clamp(proposed_size * (total) - satellite_value, 0, amount), "core": rest}` with plan step amount used instead when `settings.plan.status == "active"`. With `satellite_amount`, plan the satellite part as `add` and the core part as buys into core members pro rata in the same accounts.
- `mix`: no trades, `DECISION_NEEDED` for unset ceiling.

- [ ] **Step 1: Write the failing tests** (helper `_params(**over)` builds a two-trading-account + one-retirement fixture: trading `t1` VTI 10000 core, AAA 2000 sat, BBB 1000 sat, cash 3000; `t2` VXUS 5000 core, BBB 1000 sat, cash 500; retirement `r1` VTI 20000 core, CCC 500 sat; employer AMZN 4000 in `t1`; total 47000. Prices: every symbol 50.0 except VTI/VXUS 100.0.)

```python
SL = "core-satellite/scripts/sleeves.py"

def test_mix_reports_sleeves_and_flags() -> None:
    out = load_script(SL).run_sleeves(_params(mode="mix"))
    m = out["mix"]
    assert m["total"]["value"] == 47000.0 and m["satellite"]["value"] == 4500.0 and m["employer"]["value"] == 4000.0
    assert m["ceiling_source"] == "default"
    codes = {f["code"] for f in out["flags"]}
    assert {"DECISION_NEEDED", "PICK_IN_RETIREMENT", "LOW_N_EFF"} <= codes
    assert "EMPLOYER_CONCENTRATION" not in codes      # 4000/47000 < 10%
    assert out["trades"] == []

def test_add_splits_by_current_size() -> None:
    out = load_script(SL).run_sleeves(_params(mode="add", amount=1200))
    buys = {(t["symbol"], t["account"]): t["value"] for t in out["trades"] if t["side"] == "BUY"}
    assert buys == {("AAA", "t1"): 600.0, ("BBB", "t1"): 600.0}   # BBB pro rata to its 2000 total, routed to t1 (equal holding -> first by id)

def test_add_routes_to_larger_trading_holding() -> None:
    p = _params(mode="add", amount=900)
    # make t2's BBB larger: 1500 vs t1's 1000
    ...
    # assert every BBB buy has account "t2" and no trade touches r1

def test_add_more_than_trading_cash_is_bad_input() -> None:
    with pytest.raises(ValueError, match="only 3500.00 cash in trading accounts"):
        load_script(SL).run_sleeves(_params(mode="add", amount=5000))

def test_add_stops_at_ceiling() -> None:
    out = load_script(SL).run_sleeves(_params(mode="add", amount=3000, settings={"ceiling": 0.10}))
    assert out["over_ceiling_amount"] > 0 and any(f["code"] == "ABOVE_CEILING" for f in out["flags"])

def test_deposit_without_split_is_a_proposal() -> None:
    out = load_script(SL).run_sleeves(_params(mode="deposit", amount=2000))
    assert out["trades"] == [] and set(out["proposal"]) == {"satellite", "core"}
```

(Fill the routing test by editing the `t2` BBB units in the fixture; tie-break on equal holdings is the account id sort order.)

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_scripts_core_satellite.py -k "mix or add or deposit" -v` → FAIL.
- [ ] **Step 3: Implement `run_sleeves`** for `mix`, `add`, `deposit` with the rules above. Docstring: stdin JSON → stdout JSON contract (like `rebalance.py`), plus `main()` reading stdin, exit 2 on ValueError/TypeError.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/sleeves.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): sleeve mix and size-weighted add/deposit plans"
```

---

### Task 6: sleeves.py — valuation weighting, trims and short-term hold-back

**Files:**
- Modify: `skills/core-satellite/scripts/sleeves.py`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: `weights.valuation_targets`, `weights.confidence` (Task 3).
- Produces: when `weighting` (input, else `settings.weighting`) is `valuation`, `splits[].valuation_target` is filled, `target` uses it, and `weighting_used` is `"valuation"` (or `"size"` with `VALUATION_FALLBACK`). New flags: `LIGHT_VALUATION` (per light pick, "not used for the tilt" unless `include_light`), `NO_SAVED_VALUATION`, `RECHECK_DUE`, `VALUATION_FALLBACK`, `TRIM_HELD_BACK`.

Rules pinned:
- Eligible = held in a trading account, `picks[SYM].kind == "deep"` (or `"light"` with `include_light`), `central_value` and `expected_return` not null; `confidence = weights.confidence(age_days, recheck_due)`.
- Trims happen only for overvalued picks (price > `central_value`). Trim units come from lots in this order: losses, long-term gains, then short-term gains only when `short_term_gain_policy == "allow"`. Under `hold` (or unset → `DECISION_NEEDED` naming `short_term_gain_policy`), the short-term part becomes a `held_back` row with `long_term_date` = acquired + 1 year + 1 day (Feb 29 → Mar 1), and `target` is raised by that value so the freed money never appears in buys.
- A pick with no lots for an account has unknown term: trimmed only under `allow`; under `hold` it is held back with `long_term_date` null.
- Size mode never trims (Task 5 behaviour unchanged).

- [ ] **Step 1: Write the failing tests**

```python
def test_valuation_mode_tilts_and_trims() -> None:
    p = _params(mode="add", amount=1000, weighting="valuation", settings={"short_term_gain_policy": "allow"},
                picks={"AAA": _deep(central=150, er=0.20), "BBB": _deep(central=40, er=0.02)})   # BBB price 50 -> overvalued
    out = load_script(SL).run_sleeves(p)
    sides = {(t["symbol"], t["side"]) for t in out["trades"]}
    assert ("BBB", "SELL") in sides and ("AAA", "BUY") in sides
    assert out["weighting_used"] == "valuation"

def test_overvalued_short_term_lots_are_held_back() -> None:
    p = _params(mode="add", amount=1000, weighting="valuation",
                picks={"AAA": _deep(central=150, er=0.20), "BBB": _deep(central=40, er=0.02)},
                lots={"BBB": [{"units": 20, "cost_per_unit": 30.0, "term": "short", "acquired": "2026-03-01", "account": "t1"},
                              {"units": 20, "cost_per_unit": 30.0, "term": "short", "acquired": "2026-03-01", "account": "t2"}]})
    out = load_script(SL).run_sleeves(p)
    assert not any(t["symbol"] == "BBB" and t["side"] == "SELL" for t in out["trades"])
    assert out["held_back"][0]["long_term_date"] == "2027-03-02"
    assert {"TRIM_HELD_BACK", "DECISION_NEEDED"} <= {f["code"] for f in out["flags"]}
    assert sum(t["value"] for t in out["trades"] if t["side"] == "BUY") == pytest.approx(1000.0, abs=0.01)

def test_valuation_with_no_eligible_picks_falls_back() -> None:
    p = _params(mode="add", amount=1000, weighting="valuation", picks={"AAA": _light(), "BBB": _deep(central=60, er=0.1, recheck_due=True)})
    out = load_script(SL).run_sleeves(p)
    assert out["weighting_used"] == "size"
    assert {"VALUATION_FALLBACK", "LIGHT_VALUATION", "RECHECK_DUE"} <= {f["code"] for f in out["flags"]}

def test_size_mode_never_sells() -> None:
    p = _params(mode="add", amount=1000, picks={"BBB": _deep(central=40, er=0.02)})
    assert all(t["side"] == "BUY" for t in load_script(SL).run_sleeves(p)["trades"])
```

(`_deep(central, er, recheck_due=False, age_days=30)` and `_light()` are test helpers returning the `picks[SYM]` shape.)

- [ ] **Step 2: Run to verify failure** — `-k "valuation or held_back or never_sells"` → FAIL.
- [ ] **Step 3: Implement** the valuation branch and lot-ordered trims in `sleeves.py`.
- [ ] **Step 4: Run tests** → all core-satellite tests PASS.
- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/sleeves.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): valuation weighting with trims and short-term hold-back"
```

---

### Task 7: sleeves.py — grow, new-pick and plan-step

**Files:**
- Modify: `skills/core-satellite/scripts/sleeves.py`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: Task 5's per-account planning; `rebalance` `new_positions` (Task 1); `settings.increases`, `settings.plan`.
- Produces: input fields `"grow": {"to_weight"?|"by_points"?|"by_relative"?|"by_ambiguous"?|"amount"?}`, `"new_pick": {"symbol","price","amount"?}`. Output `readings`, `similar_to_last`, `new_pick: {"symbol","needed","allocated","account"}`, `step: {"amount","target","steps_left"}`.

Rules pinned:
- `grow` target satellite value: `to_weight × total`; `by_points` → `(w + p) × total`; `by_relative` → `w × (1 + r) × total`; `amount` → `satellite + amount`. `by_ambiguous X` returns `readings = {"points": {"amount","weight_after"}, "relative": {...}}`, no trades, flag `AMBIGUOUS_PERCENT`.
- With no grow field, output `similar_to_last = {"amount": median of the last 3 increases' amount, "dates": [...]}` (null when no increases) and no trades.
- Funding for grow: trading-account cash first, then trading-account core via `class_sells: smallest_gain`. Retirement core is never sold. Ceiling as in Task 5.
- `new-pick`: `needed = weights.median_pick_value(current satellite values)`; with `amount`, the new pick gets `min(amount, needed)` and the rest goes to existing picks by the active weighting; without `amount`, plan exactly `needed` for the new pick. Account = trading account with the most cash plus core. Symbol already held → ValueError `"{SYM} is already held; use add"`.
- `plan-step`: requires `settings.plan.status == "active"`; `steps_left = ceil(months between today and by_date / cadence months)` (min 1); `amount = (plan.target × total − satellite) / steps_left`, floored at 0; then plans as `grow` with `amount`, funded per `plan.funding` (`cash` → no core sells).

- [ ] **Step 1: Write the failing tests**

```python
def test_grow_by_ambiguous_percent_returns_both_readings() -> None:
    out = load_script(SL).run_sleeves(_params(mode="grow", grow={"by_ambiguous": 0.05}))
    r = out["readings"]
    assert r["points"]["amount"] == pytest.approx(0.05 * 47000, abs=0.01)
    assert r["relative"]["amount"] == pytest.approx(4500 * 0.05, abs=0.01)
    assert out["trades"] == []

def test_grow_sells_trading_core_never_retirement() -> None:
    out = load_script(SL).run_sleeves(_params(mode="grow", grow={"amount": 6000}, settings={"ceiling": 0.25}))
    sells = [t for t in out["trades"] if t["side"] == "SELL"]
    assert sells and all(t["account"] in {"t1", "t2"} and t["symbol"] in {"VTI", "VXUS"} for t in sells)

def test_grow_without_amount_offers_similar_to_last() -> None:
    s = {"increases": [{"date": "2026-08-01", "amount": 1000}, {"date": "2026-09-01", "amount": 1500}, {"date": "2026-10-01", "amount": 2000}]}
    out = load_script(SL).run_sleeves(_params(mode="grow", settings=s))
    assert out["similar_to_last"]["amount"] == 1500 and out["trades"] == []

def test_new_pick_needed_is_median_and_fixed_amount_splits() -> None:
    out = load_script(SL).run_sleeves(_params(mode="new-pick", new_pick={"symbol": "NEW", "price": 25.0}))
    assert out["new_pick"]["needed"] == 2000.0          # median of AAA 2000, BBB 2000 (CCC is retirement, excluded)
    out = load_script(SL).run_sleeves(_params(mode="new-pick", new_pick={"symbol": "NEW", "price": 25.0, "amount": 3000}))
    assert out["new_pick"]["allocated"] == 2000.0
    assert sum(t["value"] for t in out["trades"] if t["side"] == "BUY" and t["symbol"] != "NEW") == pytest.approx(1000.0, abs=0.01)

def test_plan_step_spreads_gap_over_remaining_steps() -> None:
    plan = {"target": 0.15, "by_date": "2027-01-29", "cadence": "monthly", "funding": "cash", "status": "active", "next_due": "2026-10-29"}
    out = load_script(SL).run_sleeves(_params(mode="plan-step", settings={"plan": plan, "ceiling": 0.20}))
    assert out["step"]["steps_left"] == 3
    assert out["step"]["amount"] == pytest.approx((0.15 * 47000 - 4500) / 3, abs=0.01)
```

- [ ] **Step 2: Run to verify failure** — `-k "grow or new_pick or plan_step"` → FAIL.
- [ ] **Step 3: Implement** the three modes.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/sleeves.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): grow, new-pick and plan-step modes"
```

---

### Task 8: run.py — live wrapper

**Files:**
- Create: `skills/core-satellite/scripts/run.py`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: `plan.read_book`, `plan.is_tax_advantaged` (Task 2); `sleeves.run_sleeves` (Tasks 5-7); `settings.load` (Task 4); `market.sectors`; `second_opinion.profile.load()["account_roles"]`; stock-screener `picks.load`, `picks.load_baseline`, `picks.pick_levels`, `track_math._irrs` (loaded with `importlib` from `skills/stock-screener/scripts`, as `track_math` loads `returns.py`).
- CLI:
  ```
  run.py mix
  run.py add AMOUNT
  run.py deposit AMOUNT [--satellite AMOUNT]
  run.py grow [--to-weight W | --by-points P | --by-relative R | --by X | --amount A]
  run.py new-pick SYMBOL [--amount A]
  run.py plan-step
  common: [--weighting size|valuation] [--include-light] [--over-ceiling] [--whole-shares] [--short-term R] [--long-term R] [--partial]
  ```
  Output: `run_sleeves` output plus `sources` (from `read_book`) and `no_price`.

Rules pinned:
- Account role: profile `account_roles[aid]` if set, else `retirement` when `is_tax_advantaged(raw_type)`, else `trading`.
- Bucket: `employer` if symbol == `settings.employer_symbol`; `core` if `market.sectors` quote_type is ETF/MUTUALFUND or the entry has `fund_sectors` or `proxy` (same rule as `summary._is_looked_through_as_fund`); `cash` for MONEYMARKET; else `satellite`.
- Picks: for each satellite symbol in the store: deep → `central_value = pick_levels(baseline)["central"]`, `expected_return = _irrs(model, price, flags)[first scenario name]`; light → `central_value = fair_values["base"]`, `expected_return = null`. `age_days` from `baseline_as_of`. `recheck_due` = `awaiting_filing`, or `next_earnings` ≤ today with no check on or after it, or last check `status == "outside"`.
- `new-pick` price from one `market.quote([SYMBOL])`; missing price → exit 2.
- Symbols in `no_price` get `NO_PRICE` and are left out.
- ETRADE_REAUTH / `--partial` behave as in `plan.py` (`hub.partial`, `hub.unavailable_flags()`).

- [ ] **Step 1: Write the failing tests** using `FakeSdk`/`fake_hub` with positions in a trading and a Roth account, `market.sectors` monkeypatched to return quote types, `market.day_changes` → `{}`, a `picks.json` + baseline written to `tmp_path`, and `track_math._irrs` monkeypatched to return `{"base": 0.15}`.

```python
def test_run_mix_classifies_and_reads_roles(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script("core-satellite/scripts/run.py"), ["mix"], capsys)
    assert rc == 0 and out["mix"]["satellite"]["value"] > 0 and out["mix"]["core"]["value"] > 0

def test_run_add_valuation_uses_pick_store(cs_sdk, capsys) -> None:
    rc, out = run_json(load_script("core-satellite/scripts/run.py"), ["add", "500", "--weighting", "valuation"], capsys)
    assert rc == 0 and out["weighting_used"] == "valuation"

def test_run_skips_holding_without_price(cs_sdk, capsys) -> None:
    # one satellite position with price None at the broker and no quote
    rc, out = run_json(load_script("core-satellite/scripts/run.py"), ["mix"], capsys)
    assert rc == 0 and any(f["code"] == "NO_PRICE" for f in out["flags"])

def test_run_new_pick_without_price_is_bad_input(cs_sdk, capsys, monkeypatch) -> None:
    monkeypatch.setattr(market, "quote", lambda syms: [])
    rc, out = run_json(load_script("core-satellite/scripts/run.py"), ["new-pick", "ZZZ"], capsys)
    assert rc == 2
```

- [ ] **Step 2: Run to verify failure** — `-k run_` → FAIL.
- [ ] **Step 3: Implement `run.py`** via `second_opinion.output.run(go, argv)`, mirroring `plan.py`'s parser class and error mapping.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/run.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): live wrapper reading holdings, picks and settings"
```

---

### Task 9: SessionStart hook

**Files:**
- Create: `hooks/core-satellite-summary.sh` (copy of `picks-summary.sh`'s shape: script `skills/core-satellite/scripts/settings.py summary`, silent unless `$DATA_DIR/core-satellite.json` exists)
- Modify: `hooks/hooks.json` (append after `picks-summary.sh`, timeout 15)
- Test: `tests/test_hook.py` (update the hook-order assertion at :46; add three tests mirroring `test_picks_summary_hook_*` :126-141)

**Interfaces:**
- Consumes: `settings.py summary` (Task 4).

- [ ] **Step 1: Write the failing tests** — order assertion becomes `[..., "picks-summary.sh", "core-satellite-summary.sh"]`; `test_core_satellite_hook_is_silent_without_store`, `test_core_satellite_hook_prints_due_step` (store with active plan, `next_due` in the past → stdout starts `Core/satellite: plan step due`), `test_core_satellite_hook_never_fails_the_session` (corrupt JSON → exit 0).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_hook.py -v` → FAIL.
- [ ] **Step 3: Implement** the hook and the `hooks.json` entry; `chmod +x`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit**

```bash
git add hooks/core-satellite-summary.sh hooks/hooks.json tests/test_hook.py
git commit -m "feat(hooks): session-start line when a core/satellite plan step is due"
```

---

### Task 10: SKILL.md, research reference, registration

**Files:**
- Create: `skills/core-satellite/SKILL.md`, `skills/core-satellite/references/research.md`
- Modify: `skills.json` (`{"name": "core-satellite", "family": "Planning", "requires": ["brokerage"], "depends_on": ["rebalancing"]}`), `tests/test_skills_structure.py` (`SKILL_NAMES`, `REFERENCE_FILES` += `core-satellite/references/research.md`, `VERB_GUARDED_REFERENCE_SKILLS` += `"core-satellite"`), `README.md` skills table (:182), `docs/scripts.md` (new `## core-satellite` section after `## rebalancing`), `docs/examples.md` (two example prompts)

**Content pinned:**
- Description (≤260, no ": "): `Sizes and funds the individual-stock satellite against the index-fund core, with the ETF-vs-picks mix, a ceiling, splits by size or deep valuation, new-pick sizing and gradual increases. Use when the user says "add $5k to my picks", "grow my picks" or asks their ETF vs stock mix.`
- Background: buckets and the employer rule; trading-accounts-only rule; what each saved setting means and that `null` triggers `DECISION_NEEDED`; that valuation weighting is opt-in and why size is the default (one sentence, pointing at `references/research.md`); that orders go through portfolio-analysis.
- Steps: case lines for "what's my mix", "add $X to picks", "a deposit / vest landed", "grow picks by X%", "new pick", "plan step due / set up a plan", "change a setting". Every case starts with `run.py` (a live read, satisfying the same-day portfolio check). On any `DECISION_NEEDED`, the reply raises that decision (ceiling with `proposed_size`, `tracking_error`, `n_eff`; or the short-term policy with the `held_back` rows) and runs `settings.py decide` only after the person answers. On `AMBIGUOUS_PERCENT`, show both `readings` and ask. After the person approves trades and they are placed via portfolio-analysis, run `settings.py record-increase`; after a plan step, `settings.py plan-advance`.
- Reply format: `Mix` table (bucket, value, weight), `Ceiling` line (saved/default, room), `Split` table (symbol, current, target, delta, account, flags; both size and valuation columns in valuation mode), `Held back` table when present, `Trades` table, `Flags`, then which saved settings were used.
- `references/research.md`: the spec's Research basis section expanded with sources and the constants table, with `## Contents`; no banned verbs.
- Rules: skill rules (never above the ceiling without `--over-ceiling` from the person's own words; never treat light valuations as deep; never send satellite money to retirement accounts or the employer symbol; never place orders), then the shared compliance bullets verbatim.

- [ ] **Step 1: Run the structure tests to see them fail** — after adding `core-satellite` to `SKILL_NAMES` and the reference to `REFERENCE_FILES`: `python3 -m pytest tests/test_skills_structure.py -q` → FAIL (missing SKILL.md / reference).
- [ ] **Step 2: Write SKILL.md, research.md, and the doc/catalog entries.**
- [ ] **Step 3: Run** `python3 -m pytest tests/test_skills_structure.py -q` → PASS.
- [ ] **Step 4: Run the full suite** `python3 -m pytest tests -q` → only the pre-existing `test_next_events_from_calendar_dict` failure.
- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite skills.json tests/test_skills_structure.py README.md docs/scripts.md docs/examples.md
git commit -m "feat(core-satellite): skill instructions, research reference and registration"
```
