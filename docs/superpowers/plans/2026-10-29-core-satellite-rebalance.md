# Core/satellite rebalance-by-valuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under valuation weighting, `add`, `grow`, `plan-step`, `deposit --satellite` and `new-pick` rebalance every trading-account pick to equal-weight-times-tilt targets for the new sleeve total, with bands on moves between holdings only.

**Architecture:** A pure `weights.rebalance_targets` computes targets; `sleeves._valuation_rebalance` turns them into trims and buys (new money first, then band moves) and returns the same shape as `_valuation_add`, so `satellite()`/`funded()` and the per-account `run_rebalance` calls stay as they are. `run.py` adds flags and per-pick hold reasons.

**Tech Stack:** Python 3.12 stdlib, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-core-satellite-rebalance-design.md`

## Global Constraints

- Rebalance is on by default; `--no-rebalance` reproduces today's output exactly (new money only, current-value tilt).
- Size weighting is unchanged by rebalance (its targets are current size shares).
- Bands: a held pick moves between holdings only when |target − current| ≥ max(0.25 × target, 250.0). New money ignores bands. The new pick always trades.
- Base weight 1 per rebalanced pick (equal weight); tilt factor = `weights.new_pick_multiplier` (TILT_LAMBDA 0.5, SHRINK_K 0.5, TILT_SCALE 0.10, trim factor when price > central × 1.05).
- 5% pick cap (`weights.PICK_CAP`) unchanged; a pick already above the cap is never trimmed for size alone.
- No sale in a retirement account; trim proceeds fund buys in the same account only.
- SKILL.md: no "recommend/advise/should/suggest"; prose lines under 400 characters.
- Every number from scripts; plans only.

## Review Focus

- A second run on unchanged prices/valuations after the trades are placed: no SELLs and no band moves (Task 2 test `test_rebalance_is_idempotent`).
- `add` of a small amount (below every band): the whole amount is placed, not left as cash (Task 2 `test_small_add_is_fully_placed`).
- `new-pick --same-size` with 15+ picks: the new pick is funded by trims despite every trim being inside its band (Task 2 `test_same_size_funds_new_pick_from_trims`).
- A pick whose recheck is pending is neither sold nor bought (Task 2 `test_held_pick_never_trades`).
- `short_term_gain_policy` hold with rebalance on: trims that would realise short-term gains become held_back rows, buys shrink to match (Task 2 fuzz invariant 4 still holds with rebalance on).

---

### Task 1: `weights.rebalance_targets`

**Files:**
- Modify: `skills/core-satellite/scripts/weights.py`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Produces: `rebalance_targets(picks: list[dict], fixed: dict[str, float], target_total: float, portfolio_total: float) -> dict` returning `{"targets": {sym: float}, "capped": [sym]}`. `picks` rows are `_pick_inputs` rows (`symbol, value, price, central_value, expected_return, eligible, confidence`); `fixed` maps symbols whose target is set by the caller (held, ineligible size share, ineligible new pick) to that target. Every symbol in `picks` gets a target. Constants `BAND_REL = 0.25`, `BAND_MIN = 250.0`, and `band(target: float) -> float` = max(BAND_REL × target, BAND_MIN).

- [ ] **Step 1: Write the failing tests**

```python
def test_rebalance_targets_equal_weight_times_tilt() -> None:
    w = load_script(W)
    rows = [{"symbol": "A", "value": 5000, "price": 80, "central_value": 100, "expected_return": 0.15, "eligible": True, "confidence": 1.0},
            {"symbol": "B", "value": 1000, "price": 80, "central_value": 100, "expected_return": 0.07, "eligible": True, "confidence": 1.0},
            {"symbol": "C", "value": 2000, "price": 50, "central_value": 40, "expected_return": 0.0, "eligible": True, "confidence": 1.0}]
    out = w.rebalance_targets(rows, {"H": 1000.0}, 9000.0, 1_000_000.0)
    # base 1 each; tilt A 1.2, B 1.0, C trim factor 0.8 -> 8000 x [1.2, 1.0, 0.8] / 3.0
    assert out["targets"] == pytest.approx({"A": 3200.0, "B": 2666.67, "C": 2133.33, "H": 1000.0}, abs=0.01)
    assert out["capped"] == []
    assert w.band(400.0) == 250.0 and w.band(2000.0) == 500.0


def test_rebalance_targets_cap_redistributes() -> None:
    w = load_script(W)
    rows = [{"symbol": s, "value": 0, "price": 80, "central_value": 100, "expected_return": er, "eligible": True, "confidence": 1.0}
            for s, er in (("A", 0.30), ("B", 0.07), ("C", 0.07))]
    out = w.rebalance_targets(rows, {}, 3000.0, 20000.0)       # cap 1000 each
    assert out["targets"] == pytest.approx({"A": 1000.0, "B": 1000.0, "C": 1000.0})
    assert out["capped"] == ["A", "B", "C"]
```

- [ ] **Step 2: Run** `python -m pytest tests/test_scripts_core_satellite.py -k rebalance_targets -q` — expect FAIL (`AttributeError: rebalance_targets`).
- [ ] **Step 3: Implement** in `weights.py`: budget = target_total − Σfixed; factor = `new_pick_multiplier(row)` (1.0 for ineligible); targets ∝ factor scaled to budget; clamp each at max(PICK_CAP × portfolio_total, row value) and hand the excess to uncapped rows pro rata to factor, iterating (≤100 rounds, as `valuation_targets` does); a budget no row can take stays unassigned. Add the docstring paragraph to the module docstring.
- [ ] **Step 4: Run** the same command — expect PASS.
- [ ] **Step 5: Commit** `feat(core-satellite): equal-weight valuation targets and bands`.

### Task 2: `sleeves._valuation_rebalance` and modes

**Files:**
- Modify: `skills/core-satellite/scripts/sleeves.py` (module docstring contract; `_valuation_add` trim loop factored into `_apply_trims`; new `_valuation_rebalance`; `satellite()`, `funded()`, new-pick block, output)
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: `weights.rebalance_targets`, `weights.band`.
- Produces (stdin params): `"rebalance": bool` (default true), `"same_size": bool` (new-pick only; default false). `picks[SYM].needs_valuation: bool` (optional). Output: `settings_used.rebalance`, `settings_used.same_size`; split flags `HELD_FOR_RECHECK`, `DEEP_VALUATION_NEEDED`, `IN_BAND`; flags of the same codes with the symbols.
- `_apply_trims(cuts: dict[str, float], sat, price: dict, positions, params, policy, spare, pick_flags, flags) -> tuple[trims, held_back, lot_override]` — the existing trim loop and TRIM_HELD_BACK flagging from `_valuation_add`, unchanged in behaviour.
- `_valuation_rebalance(amount: float, ctx, positions, spare, params, used, flags, pick_flags, shorts, new: dict | None = None, same_size: bool = False) -> dict | None` — same return shape as `_valuation_add` (`alloc, unplaced, held_back, lot_override, val`); None when no pick is eligible with confidence above 0 (falls back to size, as today). `new` is `{"symbol", "price", "account"}`.

Algorithm (`_valuation_rebalance`), the part the signature does not determine:
1. Rows = `_pick_inputs` over trading picks plus the new pick at value 0 (its sat entry `{account: 0.0}`).
2. Fixed: a pick with `recheck_due` or unknown age → current value, flag `DEEP_VALUATION_NEEDED` when `needs_valuation` else `HELD_FOR_RECHECK`; an ineligible held pick → current × (T / current sleeve) (its size share); an ineligible new pick → `seed` (median, or min(median, amount) with an amount).
3. T = current trading sleeve + amount (`same_size`: amount is 0). Targets from `rebalance_targets`.
4. New money N = amount. Pass A: the new pick takes min(its target, N) (same-size: 0). Pass B: remaining N goes to every pick below target (held excluded), largest shortfall first, up to each shortfall.
5. Pass C (band moves): cuts = current − target for each non-held pick above target with cut ≥ `band(target)`; with `same_size`, first add cuts (ignoring bands, furthest above target first) until the new pick's target is covered. `_apply_trims(cuts)`; proceeds go to picks still below target and outside their band (the new pick first), largest shortfall first.
6. In-band picks with no trade get `IN_BAND`. `_fund` places buys; trims subtract as in `_valuation_add`. `val = {"targets": targets, "size": _size_split(sat, amount)}`.

`satellite()` calls `_valuation_rebalance` when `used["weighting"] == "valuation"` and `params.get("rebalance", True)`; `funded()` with `new` in rebalance mode skips its own seeding and passes `new` into `satellite()` (new-pick `needed`, `size_needed` and `valuation_multiplier` still reported; `allocated` = the new pick's buy). New-pick refuses the employer symbol only when `picks` has no deep entry for it.

- [ ] **Step 1: Write the failing tests** (fixture `_params`, all picks via `_deep`; `settings={"weighting": "valuation", "short_term_gain_policy": "allow", "ceiling": 1.0}`)

```python
def test_rebalance_add_moves_toward_equal_weight_tilt()   # AAA 2000+BBB 2000 at t1/t2; AAA er 0.20, BBB er 0.07; add 500
    # AAA target > BBB target; satellite_net == 500; no pick SELL when every cut is inside its band
def test_small_add_is_fully_placed()                       # add 100 -> unallocated_amount == 0, satellite_net == 100
def test_rebalance_trims_outside_band()                    # a pick 3x its equal share and near fair value is sold (SELL row), proceeds buy the best pick in the same account
def test_rebalance_is_idempotent()                         # positions set to a first run's targets (units = target/price) -> second add of 1.0 has no SELL and no BUY over 1.0
def test_held_pick_never_trades()                          # BBB recheck_due -> no trade in BBB, flag HELD_FOR_RECHECK; needs_valuation=True -> DEEP_VALUATION_NEEDED
def test_same_size_funds_new_pick_from_trims()             # 16 picks of 2000 each in t1, cash 0, same_size -> NEW bought, Σ pick SELL ≈ NEW buy, no core sale
def test_no_rebalance_matches_previous_behaviour()        # rebalance False: output equals _valuation_add path (no SELL unless overvalued)
def test_new_pick_rebalance_includes_new_pick()            # new-pick under rebalance: NEW target from tilt, other picks may trim; settings_used.rebalance True
def test_employer_new_pick_allowed_with_deep_pick()        # settings employer AMZN, picks AMZN deep -> new-pick AMZN plans; without -> ValueError
```

Update the fuzz: `_fuzz_case` sets `p["rebalance"] = rng.random() < 0.6` and `same_size` for half the new-pick cases; invariant 6 applies only when `rebalance` is false or weighting is size; with rebalance on, a sold pick must not be `recheck_due`. Invariants 1–5 and 7 unchanged.

- [ ] **Step 2: Run** `python -m pytest tests/test_scripts_core_satellite.py -q` — expect the new tests to FAIL.
- [ ] **Step 3: Implement** as above; update the module docstring (input/output contract, method).
- [ ] **Step 4: Run** `python -m pytest tests/test_scripts_core_satellite.py -q` — expect PASS, including `test_randomized_plans_keep_the_money_invariants`.
- [ ] **Step 5: Commit** `feat(core-satellite): rebalance all picks by valuation on add, grow and new-pick`.

### Task 3: `run.py` flags, hold reasons, employer as a pick; SKILL.md; changelog

**Files:**
- Modify: `skills/core-satellite/scripts/run.py`, `skills/core-satellite/SKILL.md`, `CHANGELOG.md`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: Task 2 params `rebalance`, `same_size`, `picks[SYM].needs_valuation`.
- Produces: CLI `--no-rebalance` (common), `--same-size` (new-pick); `_needs_valuation(pick: dict, today: str, age_days: int | None) -> bool` (last check status `outside`, or no next earnings and older than STALE_NO_EARNINGS_DAYS); `_classify` puts a held employer symbol in `satellite` when the pick store has a deep pick for it (`run.py` reads the store once and passes its deep symbols in).

- [ ] **Step 1: Write the failing tests**

```python
def test_run_passes_rebalance_flags(cs_sdk, capsys, monkeypatch)   # default params["rebalance"] is True; --no-rebalance -> False; new-pick --same-size -> same_size True
def test_run_marks_needs_valuation(cs_sdk, capsys, tmp_path, monkeypatch)   # a pick whose last check status is "outside" -> picks[SYM]["needs_valuation"] True
def test_classify_employer_with_deep_pick_is_satellite()            # _classify(rows, info, "EMP", deep={"EMP"}) -> EMP bucket satellite
```

- [ ] **Step 2: Run** `python -m pytest tests/test_scripts_core_satellite.py -k "rebalance_flags or needs_valuation or employer_with_deep" -q` — expect FAIL.
- [ ] **Step 3: Implement** in `run.py`; update its docstring. SKILL.md: Background bullets for rebalance-by-default (equal weight × tilt, bands on moves between holdings, held picks), the `--no-rebalance` / `--same-size` flag rows, a step before every `add`/`grow`/`deposit`/`new-pick`/`plan-step` run under valuation weighting: run stock-screener's re-check steps for each pick `picks.py due` lists (recording each), then plan; reply shows `HELD_FOR_RECHECK` / `DEEP_VALUATION_NEEDED` picks and offers the deep valuation for the latter; employer row in Buckets updated. CHANGELOG Unreleased line.
- [ ] **Step 4: Run** `python -m pytest tests -q` — expect all PASS (including `tests/test_skills_structure.py`).
- [ ] **Step 5: Commit** `feat(core-satellite): rebalance flags, hold reasons and employer as a pick in run.py and the skill`.

### Task 4: Live verification

- [ ] **Step 1:** run `run.py new-pick SYMBOL --sell FUND` for a stock not yet held against the connected accounts — expect exit 0, `settings_used.rebalance` true, the new pick bought in the account holding the picks, pick SELLs only for picks outside their bands, and every due pick held with a hold flag.
- [ ] **Step 2:** rerun with `--no-rebalance` — expect the pre-rebalance plan (only the fund sale and the new pick's buy).
