# Streamline Phase 4: One Check-in

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Less steering for common moments. One inbox of at most six lines replaces the session's watchlist and picks notices. Money arriving between reads is detected. "Check in" runs one sequence, a plan's trades enter the order chain directly, unset decisions use a stated conservative default, and whole-share-only accounts are remembered.

**Architecture:** The snapshot's last-read record gains per-account cash and units and an `arrivals` list computed against the previous read. A new `skills/setup/scripts/inbox.py` (setup is always installed) builds the inbox from that record, the stock-screener pick store and the watchlist's last stored check. `hooks/inbox.sh` replaces `watchlist-summary.sh` and `picks-summary.sh`. The sleeve engine's `DECISION_NEEDED` becomes `STANDING_DEFAULT`. `accounts.<id>.whole_shares` is recorded by `preview-order.py` and read by the plan scripts.

**Spec:** `docs/superpowers/specs/2026-11-10-streamline-refactor-design.md` section 4 (and its answers).

## Global Constraints

- The inbox prints at most six lines after its header, `Second Opinion, N things:`. Nothing to report prints nothing. It never fails the session and never touches the network.
- Each inbox line ends with the sentence that handles it, in double quotes.
- An arrival is a cash rise of at least $100 in an account whose holdings sold nothing since the previous full read, or a rise in an employer member's units. Partial reads neither record nor compare.
- `STANDING_DEFAULT` replaces `DECISION_NEEDED` with the same conservative behaviour: an unset short-term policy holds gains back; an unset employer uses the vest-deposit candidate as employer stock when one is found, else none. The run continues, and one flag line says what was assumed.
- Version 1.4.0.

## Review Focus

1. Two reads on the same day, the second after the cash was invested: the arrival disappears (Task 1).
2. A sale that raised cash is not reported as an arrival (Task 1).
3. A corrupt or missing watchlist, pick store or last-read file: the inbox prints what it can and exits 0 (Task 2).
4. A saved `whole_shares` account plus a fractional-taking E*Trade account in the same plan run: whole shares apply (Task 4).
5. Employer unset with no vest deposits: no employer stock, and the run still plans (Task 3).

---

### Task 1: Arrivals between reads
- `snapshot.py` `_mark_checked`: the record gains `cash_by_account` {id: cash} and `units` {symbol: {id: units}}; with a previous full record it gains `arrivals`: `[{kind: "cash", account, amount, since}]` and `[{kind: "vest", account, symbol, units, since}]` for symbols in `plan.sleeves.EMPLOYER.members`. A cash rise counts only when no symbol's units fell in that account. Partial reads keep the previous record.
- Tests (`tests/test_scripts_snapshot.py`): `test_arrival_cash_rise_is_recorded`, `test_cash_from_a_sale_is_not_an_arrival`, `test_vest_units_are_recorded`, `test_partial_read_keeps_the_previous_record`, `test_invested_cash_clears_the_arrival`.

### Task 2: Inbox hook
- `skills/setup/scripts/inbox.py` (plain text, exit 0 always): lines for cash arrivals ("put the new cash to work"), vests ("my RSUs vested"), picks due ("re-check my picks", with the count awaiting 10-Qs), watchlist alerts ("what happened to SYM", or "show my watchlist alerts" for several). At most six lines.
- `hooks/inbox.sh` runs it; `hooks.json` drops `watchlist-summary.sh` and `picks-summary.sh` for it. The two old scripts are deleted; `watchlist.py summary` and `picks.py summary` stay for "show my watchlist".
- Tests (`tests/test_inbox.py`, `tests/test_hook.py`): empty state prints nothing; each source alone; caps at six; corrupt sources skipped; hooks.json registration.

### Task 3: Standing answers
- `sleeves.py`: `DECISION_NEEDED` becomes `STANDING_DEFAULT` with messages naming the assumption and the setting that changes it. `sleeve_run.py`: with no employer saved, the vest-deposit candidate (already computed) is used as the employer for the run, else none.
- Tests: existing flag assertions move to `STANDING_DEFAULT`; `test_unset_employer_uses_the_vest_candidate`, `test_unset_employer_without_vests_is_none`.

### Task 4: Whole-share accounts remembered
- `settings.py`: `accounts.<id>.whole_shares` (bool, default false). `brokerage.py` (the SnapTrade preview path): a `FRACTIONAL_NOT_SUPPORTED` refusal records it for that account before raising. `sleeve_run.py` and `global_plan.py`: `--whole-shares` defaults to on when any account in the run has it saved.
- Tests: `test_fractional_refusal_records_whole_shares`, `test_saved_whole_shares_applies_to_plans`.

### Task 5: Check-in sequence, plan-to-orders chain, skill text, version
- `portfolio-snapshot/SKILL.md`: "Check in" runs one sequence (E*Trade login if needed, the brief, `plan.py status`, arrivals, picks due, watchlist alerts), one section each in one reply. "Show my watchlist" points to the watchlist skill.
- `portfolio-plan/SKILL.md`: "put the new cash to work" and "my RSUs vested" (the employer policy: the sale first when `sell_on_arrival`, then the proceeds as a contribution) rows; the order chain (pick re-checks and the login happen at the start; the trade list goes straight to the pre-buy check, the preview and one `confirm`); `STANDING_DEFAULT` replaces the `DECISION_NEEDED` steps.
- `portfolio-analysis` and `trading` SKILL.md: a plan's trade list enters the protocol directly.
- CHANGELOG 1.4.0, version bump, docs.
- Tests: structure test `test_no_skill_text_asks_for_decision_needed`; version 1.4.0.
