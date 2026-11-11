# Streamline Phase 5: First Run

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** One first-run conversation, "get started with Second Opinion", replaces setup and onboarding. It checks the install, takes keys without Node, connects, confirms one role per account, picks depth, records the standing plan answers and asks three profile questions. The README leads with the marketplace route.

**Architecture:** `skills/setup` and `skills/onboarding` merge into `skills/get-started` (scripts moved with `git mv`: `settings.py`, `inbox.py`, `profile.py`). The installer's always-installed skill becomes `get-started`, and `RENAMED_SKILLS` maps `setup` and `onboarding` to it. Two new scripts: `roles.py` (the accounts table with a proposed role each) and `configure.py keys` (hidden-input key entry writing `<data dir>/.env` at mode 0600). The interactive installer drops its skill-picker screen; `--skills` and `--without` stay.

**Tech Stack:** Python 3.10+ scripts and pytest; TypeScript installer (Ink) and vitest; bash hooks.

**Spec:** `docs/superpowers/specs/2026-11-10-streamline-refactor-design.md` section 1 and section 4 "Fewer skills" (answers 4 and 6).

## Global Constraints

- Steps: 1 Check, 2 Keys (skippable), 3 Connect (skippable), 4 Accounts (with step 3), 5 Depth (defaults to Standard), 6 Portfolio plan (skippable), 7 About you (skippable). Each step is skipped when already done; the flow can stop and resume.
- Roles: trading (taxable, holds picks, core sold to fund picks), retirement (none of those), savings (taxable only). Margin stays a separate yes/no.
- Profile questions asked: `approach`, `horizon`, `pre_trade_check`. The other fields stay valid and optional, never asked.
- Keys never enter chat. `configure.py keys` reads with hidden input and writes `.env` at mode 0600, keeping every other line.
- `connect` stays its own skill.
- Version 1.5.0.

## Review Focus

1. An install that listed `setup` or `onboarding` in `installed.json` updates to `get-started` with nothing lost (Task 1).
2. The first-use gate still lets the first-run skill's own scripts through, and still blocks other skills until the profile exists (Task 1).
3. `configure.py keys` over an existing `.env` with comments and other keys: only the entered keys change, blank input keeps the old value, the mode ends 0600 (Task 3).
4. An account with a saved role: `roles.py` shows the saved role, never the proposal, and `--accept` never overwrites it (Task 2).
5. A non-interactive stdin (no TTY): `configure.py keys` exits 2 with the command to run in a terminal instead of hanging (Task 3).

---

### Task 1: get-started replaces setup and onboarding
- `git mv skills/setup/scripts/{settings,inbox}.py skills/onboarding/scripts/profile.py skills/get-started/scripts/`; one merged `skills/get-started/SKILL.md`; the two old skill directories are removed.
- Every path and name follows: `hooks/{common,inbox,session-start,gate}.sh`, `lib/second_opinion/profile.py` messages, `skills.json` (onboarding entry becomes get-started), `installer/src/engine/catalog.ts` (`ALWAYS_SKILLS = ["get-started"]`, `RENAMED_SKILLS` gains `setup` and `onboarding`), `materialize.ts`, every SKILL.md and doc naming "the setup skill" or "the onboarding skill". `install.js` rebuilt.
- Tests: existing path updates; `test_no_skill_names_retired_skills` covers setup and onboarding; vitest `canonicalSkills(["setup","onboarding"])` is `["get-started"]`; gate test for `get-started` scripts passing.

### Task 2: Account roles table
- `skills/get-started/scripts/roles.py [--accept] [--partial]`: `{"accounts": [{account_id, name, institution, raw_type, proposed_role, saved_role, role, margin}]}` where `proposed_role` is the account-type guess and `role` is saved else proposed. `--accept` saves `proposed_role` for each account with no saved role and returns the same table.
- Tests (`tests/test_scripts_roles.py`): `test_roles_table_proposes_from_type`, `test_saved_role_wins_and_is_never_overwritten`.

### Task 3: Python key entry
- `skills/get-started/scripts/configure.py keys [--broker snaptrade|etrade]`: prompts with `getpass` for SnapTrade `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY` (default) or E*Trade `ETRADE_CONSUMER_KEY`, `ETRADE_CONSUMER_SECRET`; blank keeps the saved value; writes `<data dir>/.env` atomically at 0600; prints which keys changed, masked. No TTY on stdin: exit 2 with the terminal command.
- Tests (`tests/test_scripts_configure.py`): `test_keys_written_at_0600_keeping_other_lines`, `test_blank_input_keeps_the_saved_key`, `test_no_tty_exits_2`.

### Task 4: The first-run flow and three questions
- `get-started/SKILL.md` Steps: the seven-step table and how each is detected as done (check: the smoke test; keys: config reports credentials; connect: accounts listed; accounts: every account has a saved role; depth: `depth` saved; plan: `plan.sleeves.EMPLOYER.members`, `plan.sleeves.PICKS.target` and `taxes.short_term_gain_policy` saved; about you: `profile.json` exists). Step 6 asks the standing answers once and saves each with `settings.py set`. Step 7 asks the three questions.
- `hooks/gate.sh` message names the three questions.
- Tests: structure test `test_get_started_asks_three_profile_questions` (the SKILL text asks approach, horizon and pre_trade_check, and does not ask risk_appetite, experience, goals, trades_actively or uses_options); gate message test.

### Task 5: Docs, installer picker, version
- README leads with the marketplace install and its update command; the guided installer moves to `docs/install.md` under "From a checkout" with `git pull && node install.js` as its update; `configure.py keys` is documented for marketplace users.
- Installer: the interactive flow skips `SkillPickerScreen` (all skills, the extras screen still shown); `--skills` and `--without` unchanged. `install.js` rebuilt.
- CHANGELOG 1.5.0, version bump in both manifests and `tests/test_version.py`.
- Tests: vitest UI test that the picker screen is not shown in a fresh interactive install; version 1.5.0.
