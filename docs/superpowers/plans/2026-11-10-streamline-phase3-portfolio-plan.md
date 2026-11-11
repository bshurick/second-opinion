# Streamline Phase 3: Picks as a Sleeve of One Portfolio Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** One portfolio plan with sleeves. The `rebalancing` skill becomes `portfolio-plan` and absorbs `core-satellite`. The picks sleeve keeps its inside rules, and the global plan treats a sleeve as one line.

**Architecture:** Both engines are kept, not rewritten. `rebalance.py` stays the global engine. `sleeves.py` and `weights.py` become the picks sleeve's inside engine. The ceiling, grow, plan-step, deposit-proposal and increases paths are deleted. Holding classification moves to the shared library. A new `plan.py` dispatcher (`status | contribute | withdraw | rebalance [--sleeve] | open`) is the one entry point. The old `plan.py` becomes `global_plan.py`, and `core-satellite/run.py` becomes `sleeve_run.py`. Settings move to schema 2.

**Spec:** `docs/superpowers/specs/2026-11-10-streamline-refactor-design.md` section 3 and its answers (rename to `portfolio-plan`; step-up plans become a target with a date).

## Global Constraints

- Golden rule: `plan.py contribute X --sleeve PICKS`, `plan.py open SYM` and `plan.py rebalance --sleeve PICKS` return the same trades, splits and flags as the sleeve engine's `add`, `new-pick` and `rebalance` did on the same input. Only the dropped ceiling flags and fields differ.
- No saved decision is lost. Retired values (`ceiling`, `increases`, `step_up`) are carried into schema 2 (`target`, `glide`) or into `meta.retired`, never dropped.
- `settings.json` schema 2. A schema-1 file migrates in place, and the migration is recorded in `meta.migrated_from` as `"schema 1"`.
- The sleeve's target weight is `plan.targets.PICKS` when the global targets are saved. Otherwise it is `plan.sleeves.PICKS.target`, or null, which means the sleeve's size is unmanaged (the old `ceiling: 1.0`).
- An account's role decides taxability: trading and savings are taxable, retirement is tax-advantaged. Accounts with no role keep the raw-type guess.
- `plan.py contribute AMOUNT` treats AMOUNT as cash already in the accounts. The global part routes exactly AMOUNT (`cash` 0, `contribution` AMOUNT, no sells).
- Exit codes are unchanged: 0, 2, 4 (`ETRADE_REAUTH` included), 5, 6.
- Version 1.3.0.

## Review Focus

1. A schema-1 `settings.json` with `ceiling: 0.2` and a step-up plan migrates to `target 0.2` and `glide`, with `increases` kept in `meta.retired` (Task 1).
2. A previous install whose `installed.json` lists `rebalancing` and `core-satellite` re-runs the guided installer and gets `portfolio-plan`, not nothing (Task 3).
3. Contribute with no targets and no sleeve target: buys existing core funds pro rata and nothing in the picks sleeve (Task 5).
4. Global targets that include `PICKS` with no picks held: the PICKS line flags NO_HOLDINGS and contributions skip it; nothing crashes (Tasks 4 and 5).
5. A `withdraw` with no targets: draws pro rata from current weights, tax-advantaged first (Task 5).

---

### Task 1: Settings schema 2
- Modify `lib/second_opinion/settings.py`: `SCHEMA = 2`. PICKS fields are `target` (fraction 0–1, or null), `glide` (`{to, by}` or null), `weighting`, `include_light`, `max_position` (default 0.05) and `band` (`{relative: 0.25, floor: 250}`). EMPLOYER fields are `members` and `policy` (`sell_on_arrival` | `hold` | null). Remove `ceiling`, `increases` and `step_up` from `KEYS`/`_SLEEVE_FIELDS`/`DEFAULTS`. `plan.targets` accepts sleeve keys. Add `meta.retired` (dict) and `sleeve_target(doc, name) -> float | None` (targets first, then the sleeve's `target`). `glide_target(doc, name, today) -> float | None` gives the target in force: `glide.to` while `by` is in the future, then the same.
- Modify `lib/second_opinion/settings_migrate.py`: add an `upgrade(doc) -> doc` step from 1 to 2, called by `load()` when `schema == 1`. It maps `ceiling` below 1 to `target`, `ceiling` of 1 or null to no target, and `step_up` `{target, by_date}` to `glide {to, by}`. `increases`, the rest of `step_up` and `ceiling` go to `meta.retired`. Saved with history entries. The old-file migration writes schema 2 directly.
- Tests (`tests/test_settings.py`, `tests/test_settings_migrate.py`): `test_schema1_upgrades_ceiling_to_target`, `test_schema1_ceiling_one_is_no_target`, `test_schema1_step_up_becomes_glide`, `test_retired_values_kept`, `test_sleeve_target_prefers_global_targets`, `test_glide_target`, plus existing tests updated for the removed keys.

### Task 2: Shared holding classification
- Create `lib/second_opinion/holdings.py` with `classify`, `drop_sweep_copies`, `core_rank` and `employer_candidate`, plus the helpers they need, moved verbatim from `core-satellite/scripts/run.py`. `run.py` imports and re-exports them under its old private names, so its tests still pass.
- Test: the existing core-satellite suite passes unchanged, and a new `tests/test_holdings.py` imports the four functions.

### Task 3: One skill directory
- `git mv skills/rebalancing skills/portfolio-plan`, `plan.py` → `global_plan.py`, and core-satellite `run.py` → `skills/portfolio-plan/scripts/sleeve_run.py`, with `sleeves.py` and `weights.py` alongside. `references/research.md` moves too. Fold the store adapter from core-satellite `settings.py` into `sleeve_run._store()`. `ceiling` = `glide_target`/`sleeve_target`, or 1.0 when null. Delete the old settings CLI, `hooks/core-satellite-summary.sh` and its `hooks.json` entry, and `skills/core-satellite`.
- `skills.json`: one `portfolio-plan` entry (Planning, requires brokerage). Installer: add `RENAMED_SKILLS = {rebalancing: "portfolio-plan", "core-satellite": "portfolio-plan"}` in `installer/src/engine/catalog.ts`, applied to `previous.skills`, `--skills` and `--without`. Add a vitest test, then rebuild `install.js`.
- Update the imports and paths in `lib/second_opinion/headlines/*`, `lib/second_opinion/profile.py`, `docs/samples/*` and the tests. `tests/test_scripts_core_satellite.py` becomes `tests/test_scripts_sleeves.py`.
- Delete the `grow`, `deposit`, `plan-step` modes, `increases`, `similar_to_last`, `readings`, `proposal` and `step` from `sleeves.py`/`sleeve_run.py`, together with their tests. Remove the ceiling's DECISION_NEEDED ("ceiling is unset"). The ceiling is always the sleeve target or 1.0.
- Tests: the full suite is green. `test_installer_maps_renamed_skills` (vitest). `test_hook_json_registers_the_watchlist_summary` is updated to drop `core-satellite-summary.sh`.

### Task 4: Global plan knows sleeves and roles
- `global_plan.py`: taxability comes from `settings.account_role`, falling back to the raw type. When the targets hold a sleeve key (`PICKS`, `EMPLOYER`), classify holdings (`holdings.classify` with `market.sectors`) and add classes: picks in trading accounts → `PICKS`, employer members → `EMPLOYER`. Explicit `--class` mappings win.
- New `run(args, *, overrides=None) -> dict` (the old `go`). `overrides` may set `cash`, `contribution` and `targets`, for the dispatcher.
- Tests: `test_role_decides_taxability`, `test_picks_sleeve_is_one_line`, `test_sleeve_key_with_no_members_flags_no_holdings`.

### Task 5: `plan.py` dispatcher
- `plan.py status [--partial]`: `{"sleeves": <sleeve mix>, "global": <global plan with no trades> | null, "targets_saved": bool, "sleeve_target", "glide": {to, by, monthly} | null}`, where `monthly` is the gap to the glide target divided by the whole months left.
- `plan.py contribute AMOUNT [--sleeve NAME] [common]`:
  - With `--sleeve PICKS`, it runs the sleeve `add`.
  - Otherwise, when the sleeve target in force T is set and picks are below it, the sleeve takes `min(AMOUNT, T*total − picks)` first through `add`. The rest goes to the global plan: targets without sleeve keys, renormalized, `--no-sells`, `cash` 0, `contribution` = the rest.
  - With no global targets, the rest buys the core funds held, pro rata to their value.
  - Output: `{"command", "amount", "sleeve", "global", "trades", "flags"}`, with the trades of both parts.
- `plan.py withdraw AMOUNT`: the global plan with `--withdraw`. With no targets, the targets are today's weights of every holding.
- `plan.py rebalance [--sleeve PICKS]`: the sleeve rebalance, or the global plan. With no targets: `{"no_targets": true, "derived_targets": {...}}`, and no trades.
- `plan.py open SYMBOL [--amount A]`: the sleeve `new-pick`.
- Golden tests: `test_contribute_sleeve_equals_sleeve_add`, `test_open_equals_new_pick`, `test_rebalance_sleeve_equals_sleeve_rebalance`. Also `test_contribute_no_targets_buys_core_pro_rata`, `test_contribute_sleeve_below_target_first`, `test_withdraw_no_targets_pro_rata` and `test_rebalance_no_targets_offers_derived`.

### Task 6: Skill text, docs, version
- `skills/portfolio-plan/SKILL.md`: one skill.
  - Its description carries the old triggers ("rebalance", "am I off target", "where does this deposit go", "add $5k to my picks", "my ETF vs stock mix").
  - Background: the global plan, sleeves, the inside rules table from the spec, and no-targets behaviour.
  - Steps by request: status, contribute, add to picks, withdraw, rebalance, rebalance picks, open a pick, change the plan (`settings.py set plan.targets|plan.sleeves.PICKS.target|plan.sleeves.PICKS.glide|...` from the setup skill), then after-run checks and the hand-off.
- Update `portfolio-analysis`, `setup` and any other skill naming `core-satellite` or `rebalancing`. Update README, `docs/scripts.md`, `docs/examples.md`, `docs/configuration.md`, and CHANGELOG 1.3.0, which names every renamed command. Bump the version.
- Tests: the structure tests (catalog matches the directories), `test_no_skill_names_retired_skills` (no SKILL.md says `core-satellite` or `skills/rebalancing`), and the version test at 1.3.0.
