---
name: trade-journal
description: Keeps a pre-trade journal (thesis, entry, target, stop, horizon, conviction), closes entries and reviews plan adherence against the ledger. Use when the user says "journal this trade" or "am I following my plan". Trade statistics belong to trade-review.
---
Keeps the user's pre-trade journal and reviews it against what happened. The entry is theirs in their words; the review is mechanical; the reading is about process. Journaling does not place an order.

## Background

- **Storage.** The journal is `journal.json` in the plugin data directory.
- **What the journal is for.** It captures what the brokerage record cannot: the reason for the trade and the plan. The process (was the plan followed?) is judged separately from the outcome (did it make money?). A stopped-out trade that followed the plan is good process.
- **Invalidation.** `--invalidation` stores, as `invalidation`, a thesis-based condition in the user's words, for plans whose exit is a fact rather than a price. A plan may carry it instead of, or alongside, a price stop.
- **Planned add.** `--add-at P [--add-qty N]` stores a planned add as `add_rule`. The add price is below the entry for a long and above it for a short.
  - When the watchlist skill is installed, the script also creates or replaces a watchlist price rule for the symbol, with a note naming the journal id, so the watchlist's `check` reports when the level is reached. The output echoes it as `watchlist_rule`.
  - If that step fails, the output carries `watchlist_error`. The journal entry is saved either way.
- **Amendments.** `amend` changes an open entry's plan. It updates the entry's live fields and appends the change to the entry's `revisions` audit array, where `changes` records the old and new value.
- **What `review` does.** It builds round trips from `ledger.json` (statement-import) with the trade-review engine when the ledger exists. It fetches one batched Yahoo download of daily closes plus one batched live-quote call for open entries, then runs `journalreview.py`.
- **Review method.** The matching, classification, MFE/MAE and touch-order rules are in `journalreview.py`'s docstring.
- **The gate.** While this skill is installed, the trading skill's `gate.py` runs before every order preview. It appends its decision (GO / NO_GO / REVIEW, with reasons) to the matched entry's `gates` list.
  - A BUY whose entry has neither a stop nor an invalidation is NO_GO. With an invalidation and no stop it is REVIEW.
  - The gate allows a planned add's extra quantity only at or below the `add_rule` price.
- **Reward-to-risk.** A planned reward-to-risk below 1.5 needs a win rate above 40% just to break even before costs. The review flags it.
- **Conviction.** Conviction predicts results when the judgment behind it is sound. If 5s do no better than 2s, sizing by conviction adds risk without return.
- **Overstayed entries.** Overstayed and stale-open entries are the disposition effect in plan form: the loser that was going to be sold at the stop and was not.
- **Other skills.** Placing the order is portfolio-analysis's protocol. The trade-review skill supplies the round trips (with dividends) and the news context; this skill supplies the intent. Together they answer "was this a good decision at the time?"
- **Optional extra.** This skill, and the pre-buy check that comes with it, is an optional extra. The setup skill turns it off with `--extras trade-journal=off`. The journal file stays in the data directory, so turning it back on restores the entries.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-journal/scripts/journal.py" add SYMBOL --entry P --thesis "..." [--side long|short] [--target P] [--stop P] [--invalidation "..."] [--add-at P [--add-qty N]] [--horizon DAYS] [--conviction 1-5] [--tag T ...] [--size N] [--date YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-journal/scripts/journal.py" list [--status open|closed] [--symbol SYM]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-journal/scripts/journal.py" amend ID [--target P] [--stop P] [--invalidation "..."] [--add-at P] [--add-qty N] [--thesis "..."] [--size N]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-journal/scripts/journal.py" close ID --price P [--date YYYY-MM-DD] [--notes "..."]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-journal/scripts/journal.py" review [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-journal/scripts/journalreview.py" < input.json
```

| Command | What it does |
|---|---|
| `add` | Records the thesis and plan and prints the entry with its planned reward-to-risk. |
| `list` | Prints the entries, filtered by status or symbol. |
| `amend` | Changes the plan of an open entry. Needs at least one flag; a value equal to the current one is rejected. |
| `close` | Records the exit. |
| `review` | Matches entries to the ledger's round trips and measures each exit against the plan. |
| `journalreview.py` | Pure math on entries and round trips you already have. |

All commands print JSON.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Missing thesis, inconsistent levels, unknown id, or empty journal | `error` |
| 5 | Corrupt journal or ledger | `hint` |
| 6 | Python dependencies missing | the error, and say the setup skill repairs it |

## Steps

Pick the case that matches the request.

**The user is about to place a trade, or asks to log one**

1. Ask for what is missing among: thesis in their own words, entry, target, stop, horizon, conviction 1-5, tags.
2. If the user has no price stop, ask what would prove the thesis wrong. Record the answer verbatim with `--invalidation`.
3. If they plan to add on a pullback, record it with `--add-at P --add-qty N`.
4. Run `add` with exactly what they said.
5. Reply with the add format below, including the planned reward-to-risk.
6. If they want the order placed, hand off to portfolio-analysis.

**The user revises an open entry's plan**

This covers moving the stop or target, changing the invalidation or the planned add, resizing, and rethinking the thesis.

1. Run `amend ID` with the new values.
2. If the stop changes, ask why and pass the reason as `--thesis` in the same call. A new stop is a new decision.

The review flags stop drift (`STOP_DRIFTED`, with `original_stop` echoed), so the original plan stays auditable.

**The user reports an exit**

1. Run `close ID --price P`.

If the ledger is imported, `review` matches the trade anyway.

**The user asks to see the journal**

1. Run `list`, with `--status` or `--symbol` when they scope it.
2. Reply with the list format below.

**The user asks whether they are following their plan**

1. Run `review` once.
2. Reply with the review format below. Keep the reading about process.
3. If they want the outcome side (dividends, drift, news), hand off to trade-review.

**In any case: gate records**

- If an entry you list or review carries a NO_GO or REVIEW in `gates`, say so in one line. It is the record of an order placed against the plan, which the review's process reading is about.

**In any case: the optional-extra line**

- The first time in a session that the pre-buy check shows a REVIEW or NO_GO, or that a journal entry is recorded, add one line: "(The trade plan and pre-buy check is an optional extra; say 'turn off the trade plan check' to disable it.)"
- Say it once per session, and never during an order preview or confirmation.
- If the user asks to turn it off, use the setup skill (`--extras trade-journal=off`).

## Reply format

**For `add`:** one line confirming the entry.

- Fields: id, symbol, side, entry, target, stop or invalidation, planned reward-to-risk `planned_rr` (null without a price stop), planned add (`add_rule` price and quantity, and the `watchlist_rule` created), horizon, conviction, tags, thesis.
- If `planned_rr` is below 1.5 or a level is missing, say so in one sentence, as a fact about the plan.
- If `watchlist_error` is present, say the journal entry is saved and the watchlist rule is not.

**For `list`:** a table.

Id · Date · Symbol · Side · Entry · Target · Stop / Invalidation · Add · Horizon · Conviction · Status · Thesis (first 60 characters)

**For `review`:** these sections, in this order.

1. **Summary** — `summary.entries` entries (`open` open, `closed` closed, `matched_to_ledger` matched to the ledger): plan-consistent exits `plan_consistent_rate`, within horizon `within_horizon_rate`, average planned R:R `avg_planned_rr`, win rate `win_rate`, average realized return `avg_realized_return`; exits `exits`.
2. **Entries** — table from `entries`: Id · Symbol · Entered · Planned R:R · Exit (`exit`) · Exit price · Realized return · Realized R:R · Held (days) · Plan-consistent · Within horizon · Source.
   - Open entries also show days open, `days_left_in_horizon`, and the live quote `live_price` with the unrealized `live_rr` (null when the quote or the stop is missing).
   - Closed entries also show `mfe_pct` / `mae_pct` (best and worst close vs the entry, which show whether the plan's levels were reachable) and `touch_order`.
   - A `STOP_DRIFTED` flag means the exit honoured a revised stop; show `original_stop` from the row.
3. **By conviction** and **By tag** — two small tables: level or tag · closed · win rate · average return. Say when a group has fewer than five trades.
4. **Flags** — one bullet per `flags[].message`, or "None".
5. **Reading** — two or three sentences on process, not outcome: whether exits follow the plan, whether conviction predicts results, which tags carry the losses. No advice.

Returns and rates as percentages to 1 decimal place. Prices to 2 decimal places.

## Rules

- Every number comes from the script.
- Record exactly what the user said. Never invent levels or conditions.
- Never edit `journal.json` by hand. Every plan change goes through `amend`, so ids, dates and the audit trail stay consistent.
- Journaling does not place the order.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
