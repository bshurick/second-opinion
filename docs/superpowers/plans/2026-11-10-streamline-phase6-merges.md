# Streamline Phase 6: Skill Merges

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every question has one owner. Orders belong to `trading` (scripts and protocol). `portfolio-snapshot` merges into `portfolio-analysis`, whose first section is the brief. `debt-tracker` merges into `personal-finance`. 25 skills become 23, with no capability removed.

**Architecture:** Scripts move with `git mv`; the two colliding renderers are renamed (`portfolio-snapshot/scripts/render.py` → `portfolio-analysis/scripts/render_brief.py`, `debt-tracker/scripts/render.py` → `personal-finance/scripts/render_debts.py`). Headline sources name the new skill directories. `RENAMED_SKILLS` maps `portfolio-snapshot` → `portfolio-analysis` and `debt-tracker` → `personal-finance`; `install.js` is rebuilt. Data files (`debt-tracker.json`, `statements.json`, `portfolio-last-check.json`, snapshot files) keep their names.

**Tech Stack:** Python scripts and pytest; TypeScript installer and vitest; bash hooks.

**Spec:** `docs/superpowers/specs/2026-11-10-streamline-refactor-design.md` section 4 "Fewer skills, clearer owners" (answer 5: both optional merges are made).

## Global Constraints

- No capability removed: every script, page and trigger phrase of the merged skills keeps working under the new owner, and the old trigger phrases appear in the new owners' descriptions.
- Descriptions stay at most 260 characters, contain "Use when", no ": ".
- Data file names never change.
- Version 1.6.0.

## Review Focus

1. An install that listed `portfolio-snapshot` or `debt-tracker` updates to the merged owner with nothing lost (Task 2, Task 3).
2. The brief's headlines from the debt and events sources still appear, and their dismissals work after the rename (Task 2, Task 3).
3. The portfolio-freshness and inbox hooks still find the snapshot's last-read record and scripts (Task 2).
4. An order started from portfolio-plan, portfolio-analysis or trading reaches one protocol with one confirmation block (Task 1).
5. `render_brief.py` and `render_debts.py` are the only renderers under those names; nothing calls the old paths (Task 2, Task 3).

---

### Task 1: Orders have one owner
- `trading/SKILL.md` holds the whole order protocol (account choice, dollar amounts to quantities, the gate, preview, confirmation block, cash-account settlement rules, a plan's trade list). `portfolio-analysis/SKILL.md` keeps a one-line pointer for order requests; its description no longer claims orders. Every "portfolio-analysis's order protocol" reference names trading.
- Tests: structure test `test_orders_have_one_owner` (only trading's text has "NEVER place an order without"; portfolio-analysis's description has no "order"; no SKILL.md names "portfolio-analysis's order protocol").

### Task 2: portfolio-snapshot into portfolio-analysis
- `git mv` the five scripts (render as `render_brief.py`) and `references/how-figures-are-built.md`. One merged SKILL.md: the brief and "check in" first, then analysis. Headline source `events` names portfolio-analysis. Every path follows: hooks, lib, tests, docs, other skills. `skills.json` drops portfolio-snapshot; `RENAMED_SKILLS` gains it; `install.js` rebuilt.
- Tests: path updates; `test_no_skill_names_retired_skills` covers `portfolio-snapshot`; vitest `canonicalSkills(["portfolio-snapshot"])` is `["portfolio-analysis"]`.

### Task 3: debt-tracker into personal-finance
- `git mv` the four scripts (render as `render_debts.py`). One merged SKILL.md: recording statements and the debt picture beside payoff planning. Headline source `debt` names personal-finance. Same path, catalog and installer updates as Task 2.
- Tests: path updates; retired-name test covers `debt-tracker`; vitest `canonicalSkills(["debt-tracker"])` is `["personal-finance"]`.

### Task 4: Docs and version
- README skills table and count, `docs/scripts.md`, `docs/examples.md`, CHANGELOG 1.6.0, version bump.
- Tests: version 1.6.0.
