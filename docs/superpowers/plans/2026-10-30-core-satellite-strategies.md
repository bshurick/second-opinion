# Core/satellite strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One saved weighting strategy (`equal`, `market_cap`, `valuation`, plus `size` for adding money) drives three separate actions: adding money only buys, a new pick opens at the median and touches nothing else, and rebalancing is its own on-request command.

**Architecture:** `weights.py` gains the pure strategy math. `sleeves.py` loses the rebalance-on-add path: one `_strategy_add` serves every money-adding mode, and `_valuation_rebalance` becomes `_rebalance`, reached only by the new `rebalance` mode with no cash and no core sales. `run.py` adds the command, reads market caps only when needed, and tells `sleeves.py` about unreadable pick data.

**Tech Stack:** Python 3.12, pytest. Tests run with `python3 -m pytest tests/test_scripts_core_satellite.py -q`.

**Spec:** `docs/superpowers/specs/2026-10-30-core-satellite-strategies-design.md`

## Global Constraints

- Work on a new branch `core-satellite-strategies`; `main` stays untouched.
- `docs/skill-style.md` wording rules; SKILL.md lines under 400 characters.
- Every number from the scripts; plans only, orders via portfolio-analysis.
- `sleeves.py` stays free of network calls. `run.py` reads market caps and passes them in, only when the effective strategy is `market_cap` and the mode can trade.
- Bands: `weights.band(target)` = max(25% of target, $250). Pick cap: `weights.PICK_CAP` = 5% of total value.
- Never warn about or argue against a strategy the person chose.
- `--no-rebalance`, `--same-size`, and the `rebalance` and `same_size` params are removed, not deprecated. This work replaces unreleased behaviour, so no compatibility shim.
- Match surrounding code: comment density, `_r2`/`_flag` helpers, `ValueError` for bad input (`run.py` turns it into exit 2).

## Review Focus

1. A rebalance with `whole_shares`: buys round so that no account spends more than its sale proceeds, and cash is unchanged. Test in Task 3.
2. A rebalance across two trading accounts where the overweight pick is in one and the underweight in the other: no sale is planned that its own account cannot spend, and no proceeds stay as cash. Test in Task 3.
3. Saved `weighting` of `size` and a plain `rebalance`: exit 2 naming `equal`, `market_cap` and `valuation`, while `mix` and `add` keep working. Test in Task 3.
4. Saved `market_cap` with Yahoo failing for one symbol or all of them, including `company_info` raising: one pick holds and is flagged, all stops the run, and `mix` or a `deposit` with no `--satellite` never asks for market caps. Test in Task 4.
5. A rebalance with one pick, or none: no trades and no crash. Test in Task 3.

---

### Task 1: Strategy math and the setting

**Files:**
- Modify: `skills/core-satellite/scripts/weights.py`
- Modify: `skills/core-satellite/scripts/settings.py:93-98`
- Modify: `skills/core-satellite/scripts/sleeves.py:284-286`
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Produces: `weights.tilt_factor(pick: dict) -> float`, the renamed `new_pick_multiplier` with its logic unchanged.
- Produces: `weights.strategy_weights(rows: list[dict], strategy: str, market_caps: dict[str, float] | None = None) -> dict[str, float]`. `rows` are `_pick_inputs`-shaped, with `symbol` and `value`. Raw weights: `equal` 1.0, `market_cap` the cap, `valuation` `tilt_factor`, `size` the value.
- Produces: `weights.split_capped(raw: dict[str, float], amount: float, room: dict[str, float] | None = None) -> dict[str, float]`. Splits `amount` by `raw`; a pick cannot exceed its `room`, and the overflow goes to the others by `raw`. Money no pick can take is left out of the result. All-zero `raw` splits equally. `room=None` means no limit.

- [ ] **Step 1: Create the branch and write the failing tests**

```bash
git checkout -b core-satellite-strategies
```

```python
def test_strategy_weights() -> None:
    w = load_script(W)
    rows = [dict(PICKS[0]), dict(PICKS[1], value=3000)]
    assert w.strategy_weights(rows, "equal") == {"A": 1.0, "B": 1.0}
    assert w.strategy_weights(rows, "size") == {"A": 1000.0, "B": 3000.0}
    assert w.strategy_weights(rows, "market_cap", {"A": 3e11, "B": 1e11}) == {"A": 3e11, "B": 1e11}
    assert w.strategy_weights(rows, "valuation")["A"] == pytest.approx(w.tilt_factor(PICKS[0]))
    assert w.strategy_weights([dict(PICKS[0], eligible=False)], "valuation") == {"A": 1.0}   # neutral


def test_split_capped() -> None:
    w = load_script(W)
    assert w.split_capped({"A": 1.0, "B": 3.0}, 400.0) == {"A": 100.0, "B": 300.0}
    assert w.split_capped({"A": 1.0, "B": 1.0}, 1000.0, {"A": 240.0, "B": 9999.0}) == pytest.approx({"A": 240.0, "B": 760.0})
    out = w.split_capped({"A": 1.0, "B": 1.0}, 1000.0, {"A": 100.0, "B": 200.0})
    assert out == pytest.approx({"A": 100.0, "B": 200.0})                                   # the rest is left out
    assert w.split_capped({"A": 0.0, "B": 0.0}, 100.0) == {"A": 50.0, "B": 50.0}


def test_default_weighting_is_equal_and_all_strategies_accepted() -> None:
    sl = load_script(SL)
    assert sl.run_sleeves(_params(settings={}))["settings_used"]["weighting"] == "equal"
    for name in ("equal", "market_cap", "valuation", "size"):
        assert sl.run_sleeves(_params(weighting=name))["settings_used"]["weighting"] == name
    with pytest.raises(ValueError, match="equal, market_cap, valuation or size"):
        sl.run_sleeves(_params(weighting="momentum"))
```

Also add `settings.py decide weighting` cases: `market_cap` and `equal` save; `momentum` is `InvalidInput` naming all four. Change `_params` so its default is `"settings": {"weighting": "size"}`, and rename `new_pick_multiplier` in `test_new_pick_multiplier_tilts_by_valuation`, so existing size-based tests keep their meaning.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -q -k "strategy_weights or split_capped or default_weighting"`
Expected: FAIL on the missing functions and the `size` default.

- [ ] **Step 3: Implement**

In `weights.py` add the two functions, rename `new_pick_multiplier` to `tilt_factor` at its definition and in its callers, and update the module docstring. In `sleeves._settings_used` default to `"equal"` and validate against the four names, with the error `weighting must be equal, market_cap, valuation or size`. Update `settings._parse_value` to match.

- [ ] **Step 4: Run the whole test file**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -q`
Expected: PASS. Any test that relied on the old default takes `weighting="size"` explicitly.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-10-30-core-satellite-strategies-design.md docs/superpowers/plans/2026-10-30-core-satellite-strategies.md skills/core-satellite/scripts/weights.py skills/core-satellite/scripts/settings.py skills/core-satellite/scripts/sleeves.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): weighting strategies and strategy math"
```

---

### Task 2: Adding money only buys; a new pick opens at the median

**Files:**
- Modify: `skills/core-satellite/scripts/sleeves.py` (`_pick_inputs`, `_hold` callers, `_splits`, `_valuation_add`, `_add`, the `satellite` and `funded` closures, the `new-pick` branch, the module docstring)
- Modify: `skills/core-satellite/scripts/weights.py` (delete `valuation_targets` and `_fallback`)
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: `weights.strategy_weights`, `weights.split_capped`, `weights.median_pick_value`.
- Produces: `sleeves._participants(sat, positions, params, used, flags, pick_flags) -> tuple[list[dict], dict[str, float], set[str]]` returning `(rows, raw, held)`. `held` holds the picks that take no money and do not move: `_hold` is true, the symbol is in `params["unreadable_picks"]`, or under `market_cap` the cap in `params["market_caps"]` is missing or not above 0 (flag `NO_MARKET_CAP`). `raw` covers only non-held picks. Under `market_cap`, non-held candidates with no cap at all raise `ValueError` naming the strategy. `_pick_inputs` runs only under `valuation`, so the other strategies raise no valuation flags.
- Produces: `sleeves._strategy_add(amount, ctx, positions, spare, params, used, flags, pick_flags, shorts) -> dict` returning `{"alloc", "unplaced"}`, and it never sells.
- Input and output: `params["market_caps"]: dict[str, float | None]`, `params["unreadable_picks"]: list[str]`. `splits[]` drops `size_target` and `valuation_target`. `new_pick` drops `size_needed` and `valuation_multiplier`. `settings_used` drops `rebalance` and `same_size`. `weighting_used` is the strategy applied, and `equal` when `valuation` found no eligible pick.

- [ ] **Step 1: Write the failing tests**

Use `_rb_params`, with `weighting=` passed to override `_RB_SETTINGS`.

```python
def test_add_equal_gives_same_dollars() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 4000, "CCC": 4000}, {}, cash=900, amount=900, weighting="equal"))
    assert _rb_trades(out) == pytest.approx({"AAA": 300.0, "BBB": 300.0, "CCC": 300.0}, abs=0.02)


def test_add_size_is_pro_rata() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 3000}, {}, cash=400, amount=400, weighting="size"))
    assert _rb_trades(out) == pytest.approx({"AAA": 100.0, "BBB": 300.0}, abs=0.02)


def test_add_market_cap_splits_by_cap_and_holds_a_missing_one() -> None:
    caps = {"AAA": 3e11, "BBB": 1e11, "CCC": None}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000, "CCC": 1000}, {}, cash=400, amount=400,
                                                 weighting="market_cap", market_caps=caps))
    assert _rb_trades(out) == pytest.approx({"AAA": 300.0, "BBB": 100.0}, abs=0.02)
    assert "NO_MARKET_CAP" in {f["code"] for f in out["flags"]}


def test_add_market_cap_with_no_caps_is_bad_input() -> None:
    with pytest.raises(ValueError, match="market_cap"):
        load_script(SL).run_sleeves(_rb_params({"AAA": 1000}, {}, cash=400, amount=400, weighting="market_cap", market_caps={}))


def test_add_valuation_ignores_current_size() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 8000}, {"AAA": _GOOD, "BBB": _GOOD}, cash=1000, amount=1000))
    assert _rb_trades(out) == pytest.approx({"AAA": 500.0, "BBB": 500.0}, abs=0.02)


def test_add_never_sells_an_overvalued_pick() -> None:
    picks = {"AAA": _GOOD, "BBB": _deep(central=30.0, er=0.02)}             # BBB priced 50, well above central
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 2000}, picks, cash=1000, amount=1000))
    assert all(t["side"] == "BUY" for t in out["trades"])
    assert 0 < _rb_trades(out)["BBB"] < _rb_trades(out)["AAA"]


def test_add_valuation_no_eligible_splits_equal_and_says_so() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 3000}, {}, cash=400, amount=400))
    assert _rb_trades(out) == pytest.approx({"AAA": 200.0, "BBB": 200.0}, abs=0.02)
    assert out["weighting_used"] == "equal"
    assert "equal" in next(f["message"] for f in out["flags"] if f["code"] == "VALUATION_FALLBACK")


def test_add_cap_limits_buys_and_overflow_goes_to_others() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 14800, "BBB": 2000}, {}, cash=1000, core=283000, amount=1000, weighting="equal"))
    assert _rb_trades(out) == pytest.approx({"AAA": 240.0, "BBB": 760.0}, abs=0.02)        # total 300800, cap 15040


@pytest.mark.parametrize("name", ["equal", "market_cap", "valuation", "size"])
def test_add_holds_a_pick_due_for_recheck_under_every_strategy(name) -> None:
    picks = {"AAA": _deep(central=150.0, er=0.2, recheck_due=True), "BBB": _GOOD}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 1000}, picks, cash=400, amount=400, weighting=name,
                                                 market_caps={"AAA": 1e11, "BBB": 1e11}))
    assert _rb_trades(out) == pytest.approx({"BBB": 400.0}, abs=0.02)
    assert "HELD_FOR_RECHECK" in {f["code"] for f in out["flags"]}


@pytest.mark.parametrize("name", ["equal", "valuation"])
def test_new_pick_opens_at_median_and_touches_nothing_else(name) -> None:
    picks = {"NEW": _GOOD, "AAA": _GOOD, "BBB": _FAIR, "CCC": _FAIR}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 1000, "BBB": 2000, "CCC": 6000}, picks, cash=5000, mode="new-pick",
                                                 weighting=name, new_pick={"symbol": "NEW", "price": 40.0}))
    assert _rb_trades(out) == pytest.approx({"NEW": 2000.0}, abs=0.02)
    assert out["new_pick"]["needed"] == 2000.0 and "valuation_multiplier" not in out["new_pick"]


def test_new_pick_amount_sends_the_rest_to_existing_picks() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000, "BBB": 2000, "CCC": 2000}, {}, cash=5000, mode="new-pick", weighting="equal",
                                                 new_pick={"symbol": "NEW", "price": 40.0, "amount": 2300}))
    assert _rb_trades(out) == pytest.approx({"NEW": 2000.0, "AAA": 100.0, "BBB": 100.0, "CCC": 100.0}, abs=0.02)


def test_new_pick_capped_at_five_percent() -> None:
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 8000, "BBB": 8000}, {}, cash=9000, core=75000, mode="new-pick", weighting="equal",
                                                 new_pick={"symbol": "NEW", "price": 40.0}))
    assert out["new_pick"]["needed"] == 5000.0                              # total 100000


@pytest.mark.parametrize("extra,code", [({"recheck_due": True}, "RECHECK_DUE"),
                                        ({"recheck_due": True, "needs_valuation": True}, "DEEP_VALUATION_NEEDED")])
def test_new_pick_with_open_question_still_opens_and_flags(extra, code) -> None:
    picks = {"NEW": {**_GOOD, **extra}}
    out = load_script(SL).run_sleeves(_rb_params({"AAA": 2000}, picks, cash=5000, mode="new-pick", new_pick={"symbol": "NEW", "price": 40.0}))
    assert _rb_trades(out) == pytest.approx({"NEW": 2000.0}, abs=0.02)
    assert code in {f["code"] for f in out["flags"]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -q -k "test_add_ or test_new_pick_"`
Expected: FAIL, because today's path rebalances and tilts by size.

- [ ] **Step 3: Implement**

- `_participants` and `_strategy_add`: `room` is `None` under `size`, otherwise `max(0, PICK_CAP x ctx["total"] - current)` per pick. Hand `weights.split_capped` output to `_fund`. With no trusted pick under `valuation`, raise `VALUATION_FALLBACK` with a message naming equal, and record `equal` for `weighting_used`.
- `_pick_inputs` messages change from "keeps its size share" to "gets the neutral weight".
- `satellite()` calls `_strategy_add` for every strategy. Delete `_valuation_add`, `_add`, `rebalancing`, `rb_fell_back`, `new_sized`, `same_size`, the `rebalance` param and the `fallback_why` flag, so `mix` no longer raises `VALUATION_FALLBACK`.
- `new-pick` branch: `needed = min(median, PICK_CAP x ctx["total"])` when picks exist. Remove `_pick_inputs` there and the seed logic in `funded`. Keep the account choice, the `--amount` split and the no-picks rule. When the new symbol's saved pick has `recheck_due` or no age, flag `DEEP_VALUATION_NEEDED` if `needs_valuation`, else `RECHECK_DUE`, saying it still opens at the median.
- `_splits(sat, alloc, targets=None, pick_flags=None)`: `target` is `targets[sym]` when given, else current + delta.
- Delete `weights.valuation_targets` and `_fallback`. `_valuation_rebalance` stays, uncalled, until Task 3 reshapes it.
- Delete or rewrite tests for removed behaviour: `valuation_targets` tests, `test_same_size_*`, `test_no_rebalance_*`, `test_new_pick_sized_by_its_valuation_*`, `test_new_pick_rebalance_*`, and every other test under the "rebalance by valuation" heading that runs `add`, `grow` or `new-pick` and expects a sale or a rebalance target. Tests of the math in `rebalance_targets` stay. In the seeded generator drop `rebalance` and `same_size`, and add `equal` and `market_cap` (with `market_caps`) to the strategy choice. Replace invariant 6 with one rule: no satellite symbol is ever sold in these modes, and a pick due for a recheck is never traded.
- Update the `sleeves.py` module docstring.

- [ ] **Step 4: Run the whole test file**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -q`
Expected: PASS, including the seeded invariant test. Tests of `run.py` flags that still pass `--no-rebalance` or `--same-size` are removed in Task 4; if they fail here, delete them now.

- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/sleeves.py skills/core-satellite/scripts/weights.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): adding money only buys; a new pick opens at the median"
```

---

### Task 3: The rebalance mode

**Files:**
- Modify: `skills/core-satellite/scripts/sleeves.py` (`_MODES`, `_valuation_rebalance` becomes `_rebalance`, `run_sleeves`)
- Modify: `skills/core-satellite/scripts/weights.py` (`rebalance_targets`)
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: `sleeves._participants`, `weights.band`, `sleeves._apply_trims`, `sleeves._trim_split`, `sleeves._fund`.
- Produces: `weights.rebalance_targets(rows, raw, fixed, target_total, portfolio_total, closed=frozenset()) -> dict` with `{"targets", "capped"}`. `hi` is the cap for every pick, no longer `max(cap, value)`. Overflow goes by `raw`, and never to a symbol in `closed`, the picks overvalued under `valuation`.
- Produces: `sleeves._rebalance(ctx, positions, spare, params, used, flags, pick_flags) -> dict` returning `{"alloc", "held_back", "lot_override", "targets"}`.
- Input: mode `"rebalance"`, `params["pick_store_unreadable"]: bool`.

- [ ] **Step 1: Write the failing tests**

```python
def _rb_mode(sat, picks=None, **over):
    return load_script(SL).run_sleeves(_rb_params(sat, picks or {}, mode="rebalance", **{"weighting": "equal", **over}))


def test_rebalance_in_band_picks_receive_proceeds() -> None:
    sat = {"AAA": 9000, **{f"S{i}": 3500 for i in range(10)}}
    out = _rb_mode(sat, cash=1000)
    assert _rb_trades(out) == pytest.approx({"AAA": -5000.0, **{f"S{i}": 500.0 for i in range(10)}}, abs=0.02)
    assert out["satellite_net"] == pytest.approx(0.0, abs=0.02)
    assert out["accounts"][0]["funding"]["cash"] == pytest.approx(0.0, abs=0.02)
    assert out["accounts"][0]["funding"]["core_sells"] == pytest.approx(0.0, abs=0.02)


def test_rebalance_is_idempotent() -> None:
    assert _rb_mode({"AAA": 4000, "BBB": 4000})["trades"] == []


@pytest.mark.parametrize("over", [{"weighting": "equal"},
                                  {"weighting": "valuation", "picks": {"AAA": _GOOD, "BBB": _GOOD}}])
def test_rebalance_trims_a_large_pick_that_is_not_overvalued(over) -> None:
    over = dict(over)
    picks = over.pop("picks", {})
    out = _rb_mode({"AAA": 30000, "BBB": 10000}, picks, core=460000, **over)        # total 500000, cap 25000
    assert _rb_trades(out) == pytest.approx({"AAA": -10000.0, "BBB": 10000.0}, abs=0.02)


def test_rebalance_cap_limits_targets_and_trims_go_no_further_than_others_take() -> None:
    out = _rb_mode({"AAA": 30000, "BBB": 1000, "CCC": 1000}, core=68000)            # total 100000, cap 5000
    assert _rb_trades(out) == pytest.approx({"AAA": -8000.0, "BBB": 4000.0, "CCC": 4000.0}, abs=0.02)


def test_rebalance_market_cap() -> None:
    out = _rb_mode({"AAA": 20000, "BBB": 20000}, core=1000000, weighting="market_cap", market_caps={"AAA": 3e11, "BBB": 1e11})
    assert _rb_trades(out) == pytest.approx({"AAA": 10000.0, "BBB": -10000.0}, abs=0.02)


def test_rebalance_unvalued_pick_gets_neutral_weight_and_can_trade() -> None:
    out = _rb_mode({"AAA": 2000, "BBB": 10000}, {"AAA": _FAIR}, weighting="valuation")
    assert _rb_trades(out)["BBB"] < 0


def test_rebalance_holds_recheck_unreadable_and_missing_cap() -> None:
    picks = {"HLD": _deep(central=150.0, er=0.2, recheck_due=True)}
    out = _rb_mode({"HLD": 9000, "BAD": 9000, "AAA": 1000, "BBB": 7000}, picks, unreadable_picks=["BAD"])
    assert not {"HLD", "BAD"} & set(_rb_trades(out))
    assert _rb_trades(out) == pytest.approx({"AAA": 3000.0, "BBB": -3000.0}, abs=0.02)
    out = _rb_mode({"AAA": 1000, "BBB": 7000, "CCC": 9000}, weighting="market_cap", market_caps={"AAA": 1e11, "BBB": 1e11})
    assert "CCC" not in _rb_trades(out) and "NO_MARKET_CAP" in {f["code"] for f in out["flags"]}


def test_rebalance_respects_short_term_hold() -> None:
    sat = {"AAA": 10000, "BBB": 2000}
    p = _rb_params(sat, {}, mode="rebalance", weighting="equal", settings={**_RB_SETTINGS, "short_term_gain_policy": "hold"},
                   lots={"AAA": [{"units": 200, "cost_per_unit": 10.0, "term": "short", "acquired": "2026-06-01", "account": "t1"}]})
    out = load_script(SL).run_sleeves(p)
    assert "AAA" not in _rb_trades(out) and "TRIM_HELD_BACK" in {f["code"] for f in out["flags"]}


@pytest.mark.parametrize("over,match", [
    ({"weighting": "size"}, "equal, market_cap or valuation"),
    ({"sell_first": ["VTI"]}, "sell"),
    ({"over_ceiling": True}, "over_ceiling"),
    ({"weighting": "valuation"}, "eligible"),                                # no pick has a valuation
    ({"pick_store_unreadable": True}, "pick store"),
    ({"weighting": "market_cap", "market_caps": {}}, "market_cap"),
])
def test_rebalance_bad_input(over, match) -> None:
    with pytest.raises(ValueError, match=match):
        _rb_mode({"AAA": 1000, "BBB": 5000}, **over)


def test_add_and_mix_still_work_with_saved_size() -> None:
    p = _rb_params({"AAA": 1000, "BBB": 3000}, {}, cash=400, amount=400, settings={**_RB_SETTINGS, "weighting": "size"})
    assert _rb_trades(load_script(SL).run_sleeves(p)) == pytest.approx({"AAA": 100.0, "BBB": 300.0}, abs=0.02)
    assert load_script(SL).run_sleeves({**p, "mode": "mix"})["trades"] == []


@pytest.mark.parametrize("sat", [{}, {"AAA": 5000}])
def test_rebalance_one_pick_or_none_has_no_trades(sat) -> None:
    assert _rb_mode(sat)["trades"] == []


def test_rebalance_whole_shares_spend_no_more_than_proceeds() -> None:
    out = _rb_mode({"AAA": 10025, "BBB": 1010, "CCC": 1030}, cash=500, whole_shares=True)
    assert all(float(t["units"]).is_integer() for t in out["trades"])
    bought = sum(t["value"] for t in out["trades"] if t["side"] == "BUY")
    sold = sum(t["value"] for t in out["trades"] if t["side"] == "SELL")
    assert sold > 0 and bought <= sold + 0.01


def test_rebalance_across_accounts_leaves_no_proceeds_as_cash() -> None:
    positions = [{"symbol": "AAA", "units": 200, "price": 50.0, "account": "t1", "bucket": "satellite"},
                 {"symbol": "BBB", "units": 20, "price": 50.0, "account": "t2", "bucket": "satellite"},
                 _pos("VTI", 3000, "t1", "core"), _pos("VTI", 3000, "t2", "core")]
    p = _rb_params({}, {}, mode="rebalance", weighting="equal", positions=positions,
                   accounts={"t1": {"role": "trading"}, "t2": {"role": "trading"}}, cash_by_account={"t1": 0.0, "t2": 0.0})
    assert load_script(SL).run_sleeves(p)["trades"] == []                    # t1's proceeds cannot buy BBB in t2
```

Add a seeded generator case for `mode="rebalance"` with the strategies `equal`, `market_cap` and `valuation`, and invariants: no core-fund trade, per-account buys at most sells plus $0.01, `satellite_net` within $0.01 per trade, and no recheck-due pick traded. Catch the expected `ValueError`s from valuation with no eligible pick or no market caps. Update `test_rebalance_targets_*` and `test_cap_binding_rebalance_does_not_ratchet` to the new signature and the `mode="rebalance"` path.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -q -k "rebalance"`
Expected: FAIL with `mode must be ...`.

- [ ] **Step 3: Implement**

- `rebalance_targets`: new signature and `hi`, as above.
- `_rebalance` from `_valuation_rebalance`, with `new`, `amount` and `same_size` gone. `total_t` is the sleeve value. `fixed` holds only `held` picks at current value; the size-share and above-cap-not-overvalued branches go. `closed` is non-empty only under `valuation`. Keep the band, `absorb`, `_trim_split`, `_apply_trims`, proceeds placement, `IN_BAND` and idle-proceeds code.
- Guard against the `valuation` case with no trusted pick: raise `ValueError` naming "eligible" and that a rebalance would sell toward a strategy not chosen.
- `run_sleeves`, mode `"rebalance"`, in this order: reject `size` naming `equal, market_cap or valuation`; reject `sell_first` and `over_ceiling`; reject `pick_store_unreadable`. Then set `spare = {a: 0.0}` for trading accounts so buys spend proceeds only, call `_rebalance`, pass its `targets` to `_splits`, and use no ceiling or core funding. With fewer than two trading picks, skip to no trades.
- If the whole-shares test finds a buy that rounds above proceeds, fix it by rounding buys down in this mode, not by loosening the test.

- [ ] **Step 4: Run the whole test file**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/sleeves.py skills/core-satellite/scripts/weights.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): rebalance as its own on-request mode"
```

---

### Task 4: The command line and market caps

**Files:**
- Modify: `skills/core-satellite/scripts/run.py` (usage docstring, `_picks`, `_parser`, `main`)
- Test: `tests/test_scripts_core_satellite.py`

**Interfaces:**
- Consumes: `params["market_caps"]`, `params["unreadable_picks"]`, `params["pick_store_unreadable"]`, mode `"rebalance"`.
- Produces: `run._market_caps(symbols: list[str]) -> dict[str, float | None]`, built on `market.company_info(sym)["market_cap"]`. Any failure for one symbol gives `None` for it.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_rebalance_command_and_removed_flags(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    assert run_json(r, ["rebalance", "--weighting", "equal"], capsys)[0] == 0
    assert seen["p"]["mode"] == "rebalance" and "rebalance" not in seen["p"]
    for bad in (["add", "100", "--no-rebalance"], ["new-pick", "ZZZ", "--same-size"]):
        with pytest.raises(SystemExit):
            r._parser().parse_args(bad)


def test_run_reads_market_caps_only_when_needed(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    calls = []
    monkeypatch.setattr(market, "company_info", lambda s: calls.append(s) or {"market_cap": 1e11})
    assert run_json(r, ["mix", "--weighting", "market_cap"], capsys)[0] == 0
    assert run_json(r, ["deposit", "100", "--weighting", "market_cap"], capsys)[0] == 0
    assert run_json(r, ["add", "100", "--weighting", "equal"], capsys)[0] == 0
    assert calls == []
    assert run_json(r, ["add", "100", "--weighting", "market_cap"], capsys)[0] == 0
    assert calls and all(v == 1e11 for v in seen["p"]["market_caps"].values())


def test_run_market_cap_failures(cs_sdk, capsys, monkeypatch) -> None:
    r = load_script(R)
    def boom(_s):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(market, "company_info", boom)
    rc, out = run_json(r, ["add", "100", "--weighting", "market_cap"], capsys)
    assert rc == 2 and "market_cap" in out["error"]
    assert run_json(r, ["mix", "--weighting", "market_cap"], capsys)[0] == 0


def test_run_unreadable_pick_data_reaches_the_plan(cs_sdk, capsys, tmp_path, monkeypatch) -> None:
    r = load_script(R)
    seen = _captured_params(r, monkeypatch)
    # corrupt the store as test_run_survives_corrupt_pick_store does; then:
    rc, out = run_json(r, ["rebalance", "--weighting", "equal"], capsys)
    assert rc == 2 and "pick store" in out["error"]
```

Add a matching test that a symbol raising `PICK_BASELINE_MISSING` appears in `seen["p"]["unreadable_picks"]`. Copy the setup for both from the existing tests that assert `PICK_STORE_UNREADABLE` and `PICK_BASELINE_MISSING`. Delete `test_run_passes_rebalance_flags`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -q -k "test_run_"`
Expected: FAIL.

- [ ] **Step 3: Implement**

- `_parser`: `--weighting` choices become the four names. Add a `rebalance` subparser with `parents=[common]`. Drop `--no-rebalance`, `--same-size` and their params.
- `_picks` returns the same dict and appends unreadable symbols to a new `unreadable: list[str]` argument. `main` passes `params["unreadable_picks"]`, and sets `params["pick_store_unreadable"]` when the `PICK_STORE_UNREADABLE` flag was raised.
- Effective strategy is `ns.weighting or store.get("weighting") or "equal"`. Call `_market_caps(sorted(prices))` only when it is `market_cap` and the mode trades: `add`, `grow`, `plan-step`, `rebalance`, `new-pick` with `--amount`, or `deposit` with `--satellite`.
- Update the usage docstring.

- [ ] **Step 4: Run the whole test file**

Run: `python3 -m pytest tests/test_scripts_core_satellite.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/core-satellite/scripts/run.py tests/test_scripts_core_satellite.py
git commit -m "feat(core-satellite): rebalance command and market caps in run.py"
```

---

### Task 5: Skill instructions and docs

**Files:**
- Modify: `skills/core-satellite/SKILL.md`, `skills/core-satellite/references/research.md`, `README.md:183`, `docs/scripts.md:101-107`, `docs/examples.md:30`, `CHANGELOG.md:5-7`
- Test: `tests/test_skills_structure.py`

**Interfaces:**
- Consumes: the JSON from Tasks 2 to 4.

- [ ] **Step 1: Rewrite SKILL.md**

- Description: keep it under the existing length, and name strategies and on-request rebalancing.
- **Background:** replace the "Size weighting is the default", "Valuation weighting" and "Rebalance is the default" bullets with: the four strategies and what each can do; `equal` as the default with nothing saved; adding money only buys; a new pick opens at the median of the existing picks, capped at 5%; rebalancing only on request, keeping the sleeve total, using no cash and selling no core funds. Bands decide what is sold, and any pick below target can receive proceeds. Keep held picks, for every strategy. A pick with no market cap holds under `market_cap`.
- **Settings table:** `weighting` lists the four values; `null` means `equal`.
- **Commands and flags:** add `run.py rebalance`; `--weighting equal|market_cap|valuation|size`; remove `--no-rebalance` and `--same-size`. Exit 2 row adds a rebalance under `size`, with `--sell` or `--over-ceiling`, with no eligible valuation, no market caps at all, or an unreadable pick store.
- **Steps:** run the re-check before any run that can trade, under every strategy. Add case **The user wants to rebalance**: run `run.py rebalance`, and if the person just placed a new pick and it is not in the holdings the run read, say so and wait rather than planning without it. A rebalance runs no `record-increase`. New-pick case drops the multiplier wording and mentions once that a rebalance is available afterwards. `decide` table gains `equal` and `market_cap` lines. Flags step names `NO_MARKET_CAP`.
- **Reply format:** Split for add runs is Symbol · Current · Buy · After · Account · Flags. For a rebalance it is Symbol · Current · Target · Delta · Account · Flags. Remove the Size target and Valuation target columns.
- **Rules:** keep them; never warn about the chosen strategy.

- [ ] **Step 2: Update the other docs**

`research.md`: the buy-only default holds again for adds; the valuation section says new money follows the tilt and only a rebalance trims; `equal` is the default. Add one line that market cap is a person's strategy choice. `README.md` and `docs/scripts.md`: name the strategies and the `rebalance` command, and list the `run.py` usage. `docs/examples.md`: add "Rebalance my picks by valuation." `CHANGELOG.md`: replace the unreleased rebalance-default bullets and the `valuation_multiplier` sentence with the new behaviour, because they never shipped. Keep the unrelated parts of those bullets: new-pick account choice, `--sell`, SPYM, the sweep fund and the employer candidate.

- [ ] **Step 3: Run the checks**

Run: `python3 -m pytest tests -q`
Expected: PASS, including `tests/test_skills_structure.py`.

Run: `awk 'length > 400' skills/core-satellite/SKILL.md | wc -l` and `grep -n "no-rebalance\|same-size\|valuation_multiplier\|size_target\|valuation_target" -r skills/core-satellite README.md docs/scripts.md docs/examples.md CHANGELOG.md`
Expected: `0`, and no matches.

- [ ] **Step 4: Commit**

```bash
git add skills/core-satellite README.md docs/scripts.md docs/examples.md CHANGELOG.md
git commit -m "docs(core-satellite): strategies, on-request rebalance and median new picks"
```
