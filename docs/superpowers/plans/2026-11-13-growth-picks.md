# Growth Picks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A growth mode for the deep picker that admits finalists on best-case upside (2x or more) with the central case above the price, keeps cash-burning growers that are funded and not over-borrowed, and keeps saved growth picks apart from value picks in the picks sleeve.

**Architecture:** The run's profile (`value` | `growth`) is written once by `pick_prep.py` to `DIR/run.json` and read by every later picker script through a small shared module, `skills/stock-screener/scripts/growth.py`. Each script branches on the profile; with `value` every output is unchanged. Saved picks gain a `style` field that the pick store, re-checks and the portfolio-plan sleeve engine read.

**Tech Stack:** Python 3.12 standard library, pytest. Scripts are stdin/stdout JSON or argparse CLIs following the existing `output.run` pattern.

**Spec:** `docs/superpowers/specs/2026-11-13-growth-picks-design.md`

## Global Constraints

- With profile `value` (and with no `run.json`), every script's output is byte-for-byte what it is today: existing tests pass unchanged.
- `min_upside` default 2.0; best-case return threshold `min_upside ** (1 / horizon) - 1` (14.9% a year at 2x over 5 years).
- A pick with no `style` is `value`.
- Growth picks are never sold or trimmed by an automatic path; only buying respects the 5% pick cap.
- Money routed without a named group goes to value picks only. Growth group default weighting: `equal` (same dollars of new money to each).
- New settings key: `picker.growth.min_upside` (number > 1, default 2.0).
- Version 1.9.0 in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `tests/test_version.py`; CHANGELOG entry.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run tests with `python3 -m pytest`.

## Review Focus

1. A pick saved before this change (no `style` key) is treated as value everywhere: sizing, re-check levels, list grouping. Test in Task 10 and Task 11.
2. A run folder made before this change (no `run.json`) runs as value in `pool.py`, `cards.py` and `pick_assemble.py`. Test in Task 3.
3. A growth finalist whose best scenario has no computed return, or whose model has no `horizon`, fails the gate with a reason instead of raising. Test in Task 7.
4. "Add to my growth picks" with no growth pick held, or "add to my picks" with only growth picks held, leaves the money unallocated with a flag, never an exception. Test in Task 11.
5. A mix whose dollar parts do not sum to AMOUNT, or whose percentages do not sum to 100, is bad input (exit 2) naming the sums. Test in Task 12.

---

### Task 1: R&D and short-term investments in the fundamentals table

**Files:**
- Modify: `skills/fundamental-research/scripts/fundamentals.py` (concept map near line 145, annual row near line 729, docstring line 30)
- Test: `tests/test_scripts_fundamentals.py`

**Interfaces:**
- Produces: each `annual` row gains `research_and_development` (float or null) and `short_term_investments` (float or null).

- [ ] **Step 1: Write the failing test** `test_annual_row_has_rd_and_short_term_investments`: a company-facts fixture (build it with the file's existing helper) tagging `ResearchAndDevelopmentExpense` 120e6 and `ShortTermInvestments` 300e6 for the latest year; assert the latest annual row has `research_and_development == 120e6` and `short_term_investments == 300e6`, and that a fixture without those tags gives `None` for both.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_fundamentals.py -k rd_and_short -v`. Expected: FAIL (KeyError).
- [ ] **Step 3: Implement.** Concepts: `"research_and_development": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"]`, `"short_term_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]` (the tags `screen.py` already uses). R&D is a flow, investments a balance; read each the way the neighbouring flow and balance fields are read. Add both to the docstring row list.
- [ ] **Step 4: Run** `python3 -m pytest tests/test_scripts_fundamentals.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(fundamentals): R&D and short-term investments in the annual table`.

### Task 2: Growth health preset

**Files:**
- Modify: `skills/stock-screener/scripts/screen_math.py` (criteria list near line 160, `metrics()`, `_fundamental_test()`, `PRESETS`, docstring)
- Test: `tests/test_screen_math.py`

**Interfaces:**
- Produces: criterion `min_runway_years`; metric `runway_years`; preset `health_growth`.

- [ ] **Step 1: Write the failing tests.**
  - `test_runway_passes_with_positive_fcf`: latest free cash flow > 0, `min_runway_years: 2` → passes, `metrics["runway_years"] is None`.
  - `test_runway_from_cash_over_burn`: latest fcf −50e6, `balance.cash` 120e6 → `runway_years == 2.4`, passes at 2; cash 80e6 → 1.6, fails with `"min_runway_years"` in `failed`.
  - `test_runway_missing_cash_fails`: fcf −50e6, no cash figure → fails.
  - `test_health_growth_preset`: `PRESETS["health_growth"] == {"min_revenue": 100e6, "min_revenue_cagr": 0.10, "min_f_score": 3, "max_net_debt_to_ebit": 4.0, "min_runway_years": 2.0, "rank_by": "f_score"}`.
  - `test_health_growth_keeps_cash_burner`: revenue 150→300e6 over four years, fcf negative every year, shares +8%/yr, net cash, runway 3 years, f_score 3 → in `survivors` under `health_growth`, and NOT a survivor under `health`.
  - `test_health_growth_drops_levered_loss_maker`: operating loss with net debt > 0 → fails `max_net_debt_to_ebit` (existing `_leverage_ok` behaviour; pins it).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_screen_math.py -k "runway or health_growth" -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `runway_years = cash / -fcf_latest` (2 dp via `_r4`) when latest fcf < 0, else None. `min_runway_years` passes when latest fcf is not None and ≥ 0, or `runway_years >= want`; missing fcf or missing cash with negative fcf fails. Not in `LENIENT`. Document criterion, metric and preset in the docstring.
- [ ] **Step 4: Run** `python3 -m pytest tests/test_screen_math.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(screener): growth health preset with a cash-runway test`.

### Task 3: Run profile, shared growth module, growth screens

**Files:**
- Create: `skills/stock-screener/scripts/growth.py`
- Modify: `skills/stock-screener/scripts/pick_prep.py` (`PROFILES`, `screen_plan`, `run`, docstring)
- Test: `tests/test_scripts_pick_prep.py`, Create: `tests/test_growth_module.py`

**Interfaces:**
- Produces, in `growth.py`:
  - `PROFILES = ("value", "growth")`
  - `MIN_UPSIDE_DEFAULT = 2.0`
  - `run_profile(run_dir: Path) -> str` — `run.json`'s `profile`; `"value"` when the file is missing; `InvalidInput` when present but not one of `PROFILES`.
  - `write_profile(run_dir: Path, profile: str) -> Path`
  - `best_irr_needed(min_upside: float, horizon: int) -> float` — `min_upside ** (1 / horizon) - 1`.
  - `upside_hint(quick: dict, price: float | None, fcf_latest: float | None) -> int | None` (body in Task 6).
- `pick_prep.py` writes `DIR/run.json` = `{"profile": <profile>}` and prints `profile`.

- [ ] **Step 1: Write the failing tests.**
  - `test_run_profile_defaults_to_value` (no `run.json` → `"value"`), `test_run_profile_rejects_unknown` (`{"profile": "momentum"}` → `InvalidInput`), `test_best_irr_needed`: `round(best_irr_needed(2.0, 5), 4) == 0.1487`.
  - `test_growth_screen_plan`: `screen_plan("growth", [])` == `[("growth", ["--preset", "growth", "--set", "fcf_positive_latest=none", "--set", "max_share_growth=none"]), ("smallcap", ["--preset", "growth", "--set", "fcf_positive_latest=none", "--set", "max_share_growth=none", "--set", "min_revenue=1.5e8", "--set", "min_market_cap=3e8"])]`.
  - `test_value_screen_plan_unchanged`: `screen_plan("value", [])` equals today's output.
  - `test_pick_prep_writes_run_json`: with the file's existing fakes for screens and budget, `--profile growth` leaves `run.json` with `{"profile": "growth"}`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_growth_module.py tests/test_scripts_pick_prep.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `PROFILES = {"value": (("value", ()), ("quality", ())), "growth": (("growth", GROWTH_OFF),)}` with `GROWTH_OFF = ("--set", "fcf_positive_latest=none", "--set", "max_share_growth=none")`; smallcap reuses the first preset's overrides plus `SMALLCAP`. `garp` leaves the growth profile. Update the docstring's Screens paragraph.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(picker): run profile in run.json; growth profile screens drop the cash and dilution tests`.

### Task 4: Growth prospect tests

**Files:**
- Modify: `skills/stock-screener/scripts/prospects.py` (parser, `prospect()`, new test functions, docstring)
- Modify: `skills/stock-screener/references/picker-roles.md` (Industry scanner step 4: a growth variant)
- Test: `tests/test_scripts_prospects.py`

**Interfaces:**
- Consumes: Task 1's annual fields.
- Produces: `prospects.py SYM,... --profile growth`; `prospect(symbol, report, info, change, profile="value")`. Growth rows have `tests` keys `trajectory`, `funded`, `reinvestment`, `scale`; the rest of the row shape is unchanged.

- [ ] **Step 1: Write the failing tests** (build reports with the file's existing helpers):
  - `test_growth_trajectory`: 6 of 8 quarters up and `revenue_ttm_yoy` 0.15 → true; 5 of 8 → false; 7 of 8 with growth 0.12 → false.
  - `test_growth_funded`: latest fcf > 0 and net cash → true; fcf −40e6 with cash+short-term investments 100e6 and no debt → true (2.5 years); 60e6 → false; net debt 5× positive operating income → false; operating loss with net debt > 0 → false.
  - `test_growth_reinvestment`: (R&D + capex)/revenue = 0.12 → true; 0.06 but R&D+capex 3-year growth above revenue's → true; 0.06 and slower → false; R&D and capex both null → null.
  - `test_growth_scale`: gross margin 0.45 → true; 0.30 rising each of the last three years → true; 0.30 flat → false; no gross profit → null.
  - `test_value_profile_rows_unchanged`: default call returns today's four test keys.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_prospects.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `_trajectory_growth`, `_funded`, `_reinvestment`, `_scale(report) -> tuple[dict, str]`, each returning `{"pass", "figures"}` and a `why` fragment in the existing style, three-valued with `_all`. Constants: `GROWTH_QUARTERS_UP_MIN = 6`, `GROWTH_TTM_MIN = 0.15`, `RUNWAY_YEARS = 2.0`, `MAX_NET_DEBT_TO_EBIT = 4.0`, `REINVEST_MIN = 0.10`, `GROSS_MARGIN_MIN = 0.40`. Net debt here is `long_term_debt - cash - short_term_investments` from the latest annual row.
- [ ] **Step 4: Write the brief.** In `picker-roles.md`, Industry scanner step 4 gains "When the run's profile is growth" sub-steps: run `prospects.py ... --profile growth`; the four tests are the table in the spec's "Prospect tests"; look for companies whose largest opportunity is a business still small in the numbers and name it in `why`; three of four and `size_ok` still decide entry.
- [ ] **Step 5: Run** `python3 -m pytest tests/test_scripts_prospects.py -v`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(picker): growth prospect tests (trajectory, funded, reinvestment, scale)`.

### Task 5: Pool health check by profile

**Files:**
- Modify: `skills/stock-screener/scripts/pool.py` (`run_health`, `run`, docstring)
- Test: `tests/test_scripts_pick_pool.py`

**Interfaces:**
- Consumes: `growth.run_profile`, preset `health_growth`.
- Produces: `run_health(symbols, held, preset="health")`; `pool.json` gains `"profile"`.

- [ ] **Step 1: Write the failing test** `test_growth_run_uses_health_growth`: run folder with `run.json` `{"profile": "growth"}`; patch `run_health` (as the file's existing tests do) and assert it was called with `preset="health_growth"`; `pool.json["profile"] == "growth"`. And `test_value_run_uses_health` without `run.json`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_pick_pool.py -k health -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** The screen command's `--preset` takes the argument.
- [ ] **Step 4: Run** `python3 -m pytest tests/test_scripts_pick_pool.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(picker): growth runs health-check the pool with health_growth`.

### Task 6: Upside hint and the growth quick read

**Files:**
- Modify: `skills/stock-screener/scripts/growth.py` (`upside_hint` body), `skills/stock-screener/scripts/cards.py` (`card_data`, `_one`, docstring)
- Modify: `skills/stock-screener/references/picker-roles.md` (Quick reader: health table growth wording, the card's fourth score)
- Modify: `skills/stock-screener/scripts/pick_assemble.py` only if its card validation names the four score keys: accept `upside` in place of `value` for a growth run.
- Test: `tests/test_growth_module.py`, `tests/test_scripts_pick_cards.py`, `tests/test_scripts_pick_assemble.py`

**Interfaces:**
- Produces: growth cards' data files carry `upside_hint` (and no `value_hint`); growth cards score `quality`, `direction`, `tailwind`, `upside`.

- [ ] **Step 1: Write the failing tests.** `upside_hint(quick, price, fcf_latest)`:
  - `{"basis": "dcf", "bull": 220, "base": 120}`, price 100, fcf 10 → 5
  - bull 160, base 110 → 4; bull 160, base 90 → 3; bull 120, base 90 → 2; bull 90 → 1
  - `basis` None → None; fcf_latest −5 → None; price None → None; bull missing → None
  - `test_growth_card_has_upside_hint`: growth run folder, card data has `upside_hint` and no `value_hint`.
  - `test_assemble_accepts_upside_score` (only if Step 3's validation change applies): a growth run's card with `scores.upside` passes; with `scores.value` and no `upside` is exit 2.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_growth_module.py tests/test_scripts_pick_cards.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Rungs, first match wins: `bull/price >= 2 and base > price` → 5; `bull/price >= 1.5 and base > price` → 4; `bull/price >= 1.5` → 3; `bull > price` → 2; else 1. `fcf_latest` is the pack's latest annual free cash flow. Cards in a growth run keep `leverage` unchanged (`leverage.ok` false is never a finalist).
- [ ] **Step 4: Write the brief.** Quick reader: in a growth run the fourth score is `upside` (1: bull case below the price; 5: bull at least twice the price and base above it); `upside_hint` is a starting point; when it is null, score from the growth yardstick (the revenue needed for the price to double at a mature margin for the industry, against current revenue, growth rate and market size; EV/sales against growing peers) and name it in the reason. Health table: negative free cash flow and a rising share count are not marks against a growth company; a runway under two years is.
- [ ] **Step 5: Run** `python3 -m pytest tests/test_growth_module.py tests/test_scripts_pick_cards.py tests/test_scripts_pick_assemble.py -v`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(picker): upside score and hint for growth quick reads`.

### Task 7: The growth gate

**Files:**
- Modify: `skills/stock-screener/scripts/gate.py` (`run_gate`, docstring)
- Test: `tests/test_scripts_gate.py`

**Interfaces:**
- Consumes: `growth.best_irr_needed` (load `growth.py` by path, as `pick_assemble.py` loads `gate.py`).
- Produces: input keys `profile` (`"value"` default) and `min_upside` (default 2.0). Growth output adds top-level `profile`, `min_upside`; per result `best` (`{"name", "irr", "value_per_share"}`), `best_multiple` (`(1 + best.irr) ** horizon`, 2 dp, or null), `checks: {"best_ok", "central_above_price", "all_above_price"}`. Value output unchanged except `profile: "value"` is NOT added (keeps byte-for-byte).

- [ ] **Step 1: Write the failing tests** (horizon 5, price 100):
  - `test_growth_pass`: scenarios central 130 (irr 0.06), bull 260 (irr 0.21), bear 40 (irr −0.17) → `pass`; `best.name == "bull"`; `best_multiple == round(1.21 ** 5, 2)`; worst reported, no worst reason.
  - `test_growth_fails_low_best`: bull irr 0.12 → `fail`, reason names 2.0x and 14.9%.
  - `test_growth_fails_central_below_price`: central value 95 → `fail`.
  - `test_growth_best_irr_missing_fails` and `test_growth_no_horizon_fails`: `fail` with a reason, no exception.
  - `test_growth_stress_not_best`: a stress scenario with the highest irr is not chosen as `best`.
  - `test_growth_order_by_best`: two passes sort by `best.irr` descending.
  - `test_growth_flagged`: every gated value above price → `pass_flagged`.
  - `test_growth_rejects_hurdle_floor`: `profile: "growth"` with `hurdle` or `floor` → `ValueError`.
  - `test_min_upside_three`: `min_upside: 3.0` turns the first test's pass into a fail (1.21^5 = 2.59).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_gate.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** a `_growth_result(f, price, rows, stress, min_upside, horizon) -> dict` beside the value logic; `horizon` from `model.horizon`. `min_upside` must be > 1.
- [ ] **Step 4: Run** `python3 -m pytest tests/test_scripts_gate.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(picker): growth gate on best-case upside`.

### Task 8: Assemble, page and the min-upside setting

**Files:**
- Modify: `lib/second_opinion/settings.py` (`DEFAULTS` gains `"picker": {"growth": {"min_upside": 2.0}}`; `KEYS["picker.growth.min_upside"]`; the sections list near line 325)
- Modify: `skills/stock-screener/scripts/pick_assemble.py` (`--min-upside`, profile, save commands, docstring)
- Modify: `skills/stock-screener/scripts/render_pick.py` (growth wording and columns)
- Modify: `skills/stock-screener/SKILL.md` (deep picker: growth trigger words, profile in step 2/4, step 14 flags, reply format, Background gate bullet)
- Test: `tests/test_settings.py`, `tests/test_scripts_pick_assemble.py`, `tests/test_scripts_stock_picker.py` (or wherever `render_pick` is tested)

**Interfaces:**
- Consumes: Task 3 `run_profile`, Task 7 gate.
- Produces: save commands carry `--style growth` or `--style value`; `pick.json` and the page carry `profile`.

- [ ] **Step 1: Write the failing tests.**
  - `test_min_upside_setting`: default 2.0; `set picker.growth.min_upside 3` saves 3.0; `1` and `abc` are rejected.
  - `test_assemble_growth_passes_profile`: run folder with `run.json` growth → `gate.json` has `profile: "growth"` and `min_upside` from settings; `--min-upside 2.5` wins.
  - `test_assemble_growth_rejects_hurdle`: growth run with `--hurdle 0.12` → exit 2, nothing written.
  - `test_save_commands_carry_style`: growth → every save command contains `--style growth`; value run → `--style value`.
  - `test_render_growth_page`: a growth `pick.json` renders the text "best case" and "not gated" beside the worst case, and does not render "hurdle".
- [ ] **Step 2: Run** `python3 -m pytest tests/test_settings.py tests/test_scripts_pick_assemble.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Profile: `run.json` first, the notes file's `profile` only when `run.json` is missing. Page (growth): subtitle `As of DATE · growth · best case at least {min_upside}x`; intro "N of M finalists passed the growth gate: a best case worth at least {min_upside}x the price over five years and a central case above today's price. The worst case is shown and was not a test."; per pick: best-case multiple and return, central value vs price, worst case with its return labelled "not gated".
- [ ] **Step 4: Write SKILL.md.** Growth words ("growth picks", "high upside", "2x", "the next NVDA", "moonshot") choose `--profile growth`; value stays the default. Step 14 adds `--min-upside R` when the person gave one. Reply table for growth: ticker, best-case multiple and return, central value vs price, worst return (not gated), thesis, link. Publish description "Deep growth picks as of DATE".
- [ ] **Step 5: Run** `python3 -m pytest tests/test_settings.py tests/test_scripts_pick_assemble.py tests/test_scripts_stock_picker.py -v`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(picker): growth runs assemble, render and save with their style`.

### Task 9: A best case in every deep valuation

**Files:**
- Modify: `skills/valuation/scripts/deep_run.py` (`summarize`, docstring)
- Modify: `skills/valuation/SKILL.md` (Deep step 4; `NO_BEST_CASE` in the flags it acts on; `MARGIN_ABOVE_HISTORY` expected in a best case)
- Modify: `skills/valuation/references/deep-roles.md` (Red team: new step attacking the best case; cap stays 2)
- Test: `tests/test_scripts_deep_run.py`

**Interfaces:**
- Produces: flag `NO_BEST_CASE` when no non-stress scenario other than the first has `value_per_share` above the first's.

- [ ] **Step 1: Write the failing tests** `test_no_best_case_flag` (scenarios 100 central, 80, 60 → flag present) and `test_best_case_present` (100, 140, 60 → absent; a stress scenario at 150 alone does not count).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_deep_run.py -k best_case -v`. Expected: FAIL.
- [ ] **Step 3: Implement** in `summarize`, appended to `extra_flags` with message "No scenario is better than the central one; add a best case backed by dated ledger claims and rerun."
- [ ] **Step 4: Write the briefs.** SKILL.md Deep step 4: at least one scenario better than the central one; each of its `must_be_true` points to a ledger claim with a source and a date; on `NO_BEST_CASE`, add it and rerun before the threads. Red team: attack the best case like the central one (each `must_be_true` backed by a dated record; margins and reinvestment consistent with segment history and comparable companies; one story, not several good things stacked); a best case it cannot support is cut back and the model rerun.
- [ ] **Step 5: Run** `python3 -m pytest tests/test_scripts_deep_run.py -v`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(valuation): every deep valuation carries a best case; red team attacks it`.

### Task 10: Pick style and growth re-check levels

**Files:**
- Modify: `skills/stock-screener/scripts/picks.py` (`_upsert`, `_save_deep`, parser, `list`, `_due`, `summary_data`/`summary_lines`, `pick_levels`, docstring)
- Modify: `skills/stock-screener/scripts/track_math.py` (`price_levels`, `price_level`, `LEVELS`, docstring)
- Modify: `skills/stock-screener/SKILL.md` (re-check reply: growth levels; restyle only on request)
- Test: `tests/test_scripts_picks.py`, `tests/test_scripts_track_math.py`

**Interfaces:**
- Produces: picks carry `style`; `save-deep --style value|growth [--restyle]`; flag `STYLE_KEPT`; `price_levels(model, style="value", min_upside=2.0)` returns, for growth, `upside` in place of `hurdle`; `price_level` returns `"upside"` in place of `"hurdle"` for growth (`GROWTH_LEVELS = ("below_worst", "normal", "upside", "above_central", "above_all")`).

- [ ] **Step 1: Write the failing tests.**
  - `test_old_pick_is_value`: a store entry with no `style` lists as `value`.
  - `test_save_deep_style_growth`: new pick with `--style growth` → `style == "growth"`.
  - `test_style_kept_without_restyle`: saved value pick, `save-deep --style growth` → baseline replaced, `style` still `value`, output flags contain `STYLE_KEPT`; with `--restyle` → `growth`, no flag.
  - `test_list_groups_by_style`: `list` output has picks ordered value first, then growth, each with `style`.
  - `test_growth_upside_level`: best scenario distributions `[0,0,0,0]`, exit 300, horizon 5 → `levels["upside"] == round(300 / 2.0, 2)` (i.e. 150.0) at `min_upside` 2; price 160 with central 140 → `above_central`; price 145 with central 200 → `upside`; `"hurdle" not in levels`.
  - `test_value_levels_unchanged`: existing expectations hold with the default `style`.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_picks.py tests/test_scripts_track_math.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** The upside price discounts the best scenario's distributions and exit value at `best_irr_needed(min_upside, len(dists))`, as `hurdle` does for the central one. `pick_levels` passes the pick's style and the saved `picker.growth.min_upside`. `due` and `summary` lines name the style for growth picks ("growth pick").
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(picks): value/growth style on saved picks; growth re-checks watch the upside price`.

### Task 11: Sleeve engine groups

**Files:**
- Modify: `skills/portfolio-plan/scripts/sleeves.py` (input contract, `_participants`, `_hold`, `_strategy_deltas`, new-pick sizing, rebalance, `mix` output, docstring)
- Test: `tests/test_scripts_sleeves.py`

**Interfaces:**
- Consumes: `picks[SYM]["style"]` (absent → `"value"`); `new_pick["style"]`.
- Produces: input `"group": "value" | "growth"` (default `"value"`) and `"group_amounts": {"value": float, "growth": float}` (add only; when present, `amount` must equal their sum). Output `mix` gains `groups: {"value": {"value", "weight", "count"}, "growth": {...}}`; `splits` rows gain `style`. Flags: `GROWTH_HELD` (a growth pick not in the group taking money, or in rebalance), `GROWTH_BY_REQUEST_ONLY` (group value, no value pick can take money: the amount stays unallocated), `NO_GROWTH_PICKS` (group growth, none held), `GROWTH_OVER_CAP` (a growth pick above the 5% cap: held, not trimmed).

- [ ] **Step 1: Write the failing tests** (existing builders):
  - `test_add_defaults_to_value_picks`: picks A (value), B (value), G (growth); `add` 3000 → G gets 0 and carries `GROWTH_HELD`; A+B get 3000.
  - `test_add_growth_group_equal`: `group: "growth"`, growth picks G1 $1000, G2 $5000, saved weighting `valuation` → each gets 1500 (equal is the growth default; `fill` does not apply to the growth group's default).
  - `test_add_growth_group_weighting_override`: `group: "growth"`, `weighting: "market_cap"` → split by market cap.
  - `test_add_mix`: `group_amounts {"value": 3000, "growth": 2000}`, `amount` 5000 → value picks get 3000 by the saved rule, growth picks 2000 equally.
  - `test_add_mix_sum_mismatch`: `amount` 5000, parts 3000+1000 → `ValueError` naming both sums.
  - `test_add_value_only_growth_held_unallocated`: only growth picks held, `add` 2000 → `unallocated_amount == 2000`, flag `GROWTH_BY_REQUEST_ONLY`.
  - `test_add_growth_none_held`: `group: "growth"`, no growth picks → unallocated, `NO_GROWTH_PICKS`.
  - `test_growth_pick_cap_limits_buys`: growth pick at 4.9% of total, `group: "growth"` add pushing past 5% → it stops at 5%, rest unallocated with `PICK_CAP`.
  - `test_rebalance_never_trims_growth`: growth pick at 9% of total, value picks off target → no trade on the growth pick, flags `GROWTH_HELD` and `GROWTH_OVER_CAP`; value picks rebalance among themselves.
  - `test_new_growth_pick_with_amount`: `new_pick {"symbol": "G3", "style": "growth", "amount": 4000}` → G3 gets 4000 (or the cap), no other pick trades.
  - `test_new_growth_pick_no_amount`: growth picks held at 2000 and 6000 → `needed == 4000`; with no growth pick held → median of all picks.
  - `test_new_value_pick_unchanged`: value new-pick with amount fills value picks only with the remainder.
  - `test_mix_groups`: `mix` reports each group's value, weight and count.
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_sleeves.py -v`. Expected: FAIL (new tests only).
- [ ] **Step 3: Implement.** Out-of-group picks are held like `_hold` picks (value kept, no money, never trimmed). Rebalance treats every growth pick as held. A growth group's default weighting is `equal` with allocation `split` (same dollars each); an explicit `weighting` input applies its normal rule.
- [ ] **Step 4: Run** `python3 -m pytest tests/test_scripts_sleeves.py -v`. Expected: PASS, including every existing test.
- [ ] **Step 5: Commit** `feat(plan): picks sleeve keeps growth picks apart; money reaches them only by request`.

### Task 12: Plan commands and the global plan hold

**Files:**
- Modify: `skills/portfolio-plan/scripts/sleeve_run.py` (read `style` from the pick store into `picks` and `new_pick`; flags `--group value|growth`, `--mix VALUE,GROWTH`; docstring)
- Modify: `skills/portfolio-plan/scripts/plan.py` (pass `--group`/`--mix` through for `contribute --sleeve PICKS`; `open` passes nothing new)
- Modify: `skills/portfolio-plan/scripts/global_plan.py` (`sleeve_positions`, PICKS target)
- Modify: `skills/portfolio-plan/SKILL.md` (the money table from the spec; a mix with no split given: ask)
- Test: `tests/test_scripts_plan.py`, `tests/test_scripts_sleeves.py` (sleeve_run parts), the global plan's test file

**Interfaces:**
- Consumes: Task 10 `style`, Task 11 `group`/`group_amounts`.
- Produces: `--mix` takes two dollar amounts (`3000,2000`) or two percentages (`70%,30%`) of AMOUNT; `sleeve_positions(..., growth: set[str] = frozenset())` leaves growth symbols without a key and frozen; PICKS line target value `max(T - G, min(V, T))`.

- [ ] **Step 1: Write the failing tests.**
  - `test_sleeve_run_reads_style`: a store pick with `style: growth` reaches `sleeves.py` input as `picks[SYM]["style"] == "growth"`; a pick without one as `"value"`.
  - `test_mix_percent`: `add 5000 --mix 70%,30%` → `group_amounts {"value": 3500, "growth": 1500}`.
  - `test_mix_bad_sums`: `--mix 3000,1000` with AMOUNT 5000 → exit 2 naming 4000 and 5000; `--mix 60%,30%` → exit 2 naming 90%.
  - `test_mix_and_group_exclusive`: both given → exit 2.
  - `test_plan_contribute_passes_group`: `plan.py contribute 2000 --sleeve PICKS --group growth` reaches `sleeve_run` with `--group growth`.
  - Global plan, total 100, T = 10%: `test_picks_line_growth_over` (V 8, G 6 → no PICKS sells, flag `GROWTH_PICKS_OVER`); `test_picks_line_value_over` (V 12, G 3 → value picks sell 2); `test_picks_line_under` (V 4, G 3 → value picks buy 3); `test_withdraw_skips_growth` (withdraw draws nothing from a growth pick).
- [ ] **Step 2: Run** `python3 -m pytest tests/test_scripts_plan.py tests/test_scripts_sleeves.py -v` and the global plan's file. Expected: FAIL.
- [ ] **Step 3: Implement.** In `global_plan.run`, growth symbols come from the pick store through the same reader `sleeve_run` uses; frozen positions are the existing unmapped-freeze path in `rebalance.py`. The PICKS target weight passed to `run_rebalance` is `max(T - G, min(V, T)) / total`; flag `GROWTH_PICKS_OVER` when `V + G > T` and `G > 0`.
- [ ] **Step 4: Write SKILL.md** for portfolio-plan: the four rows of the spec's money table, the mix forms, "a mix with no split given: ask for it", growth picks left to run with a flag.
- [ ] **Step 5: Run** the same commands. Expected: PASS.
- [ ] **Step 6: Commit** `feat(plan): --group and --mix for picks money; global plan never sells growth picks`.

### Task 13: Release

**Files:**
- Modify: `docs/deep-research.md`, `docs/scripts.md`, `docs/configuration.md` (growth mode, new flags, `picker.growth.min_upside`)
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `tests/test_version.py` (1.9.0)

- [ ] **Step 1: Update** `tests/test_version.py` to expect 1.9.0 and run `python3 -m pytest tests/test_version.py -v`. Expected: FAIL.
- [ ] **Step 2: Bump** both plugin files to 1.9.0; add the CHANGELOG entry (growth picks: profile, gate, health, prospects, upside score, best case in deep valuations, pick style, sleeve groups); update the three docs.
- [ ] **Step 3: Run the whole suite** `python3 -m pytest -q`. Expected: all pass.
- [ ] **Step 4: Commit** `Growth picks: a second deep-picker mode on best-case upside; growth picks kept apart in the sleeve (1.9.0)`.
