---
name: trade-review
description: Reviews past trades from the imported ledger with round trips, win rate, disposition effect, drift after sales, counterfactuals and a deep review of skill against luck. Use when the user says "review my trades", "was selling X wise" or asks for a deep review.
---
Reviews the user's past trades mechanically first, then adds the context a spreadsheet could not show. Numbers come from the script; context comes from the news of the week before each sale; the reading separates decision quality from outcome. It stops before what to do next with an open lot.

## Background

- **Data.** `run-review.py` reads `ledger.json` (built by the statement-import skill), fetches prices for every traded symbol plus the benchmark in one batched Yahoo download, and runs `review.py`.
- **Method.** FIFO lots with pro-rata dividends, Odean's PGR/PLR, drift measured from the sale price, the counterfactual definitions, the matrix thresholds and the flag thresholds are defined in `review.py`'s docstring.
- **Filters.** `--account`, `--symbol`, `--start` and `--end` filter the ledger before the review. Filtering out the buys behind a sale makes that sale "unmatched".
- **Without prices.** `--no-prices` skips Yahoo: round trips still work; drift, context and counterfactuals do not. If Yahoo fails, the review still runs and adds a `PRICES_UNAVAILABLE` flag.
- **Research queue.** `research_queue` lists the sales worth a news lookup: the largest gains, the largest losses and the biggest moves after the sale, each with a `why`. It can hold more than 5 rows. `--research-top N` truncates it to the N rows with the largest absolute `total_pnl`.
- **Largest buys.** `largest_buys` gives, per symbol, the two largest BUY rows by amount. They are the lots behind a "was buying X wise" question when the run is scoped with `--symbol X`.
- **The page.** `render.py` turns a saved `run-review.py` result into one self-contained HTML page for the Artifact tool, with light and dark themes and no external scripts. It carries:
  - stat tiles, and a sortable round-trips table with the buy-and-hold counterfactual and drift after the sale;
  - a drift-by-horizon bar chart, and counterfactual and disposition bars against Odean's reference values;
  - open lots, the research queue, the strategy matrix as a heat table, the per-year table, re-entries and flags.
- **Other skills.** The ledger belongs to statement-import. What to do next with an open lot belongs to portfolio-analysis or valuation.

**Established findings.** The reading leans on these. Cite them by name when they apply and do not extend them beyond what they say.

- Odean (1998), "Are investors reluctant to realize their losses?": investors realize gains at a higher rate than losses (PGR 0.148 vs PLR 0.098); the losers they keep go on to underperform the winners they sell. The script computes PGR, PLR and their difference the same way.
- Barber and Odean (2000), "Trading is hazardous to your wealth": the most active fifth of households turned over 250% a year and earned about 6.5 points a year less than the least active; trading costs, not stock picking, explain the gap.
- Barber and Odean (2008) on attention: individual investors are net buyers of stocks in the news and of stocks with extreme one-day moves. `CHASED_MOMENTUM` and the pre-buy context are the mechanical proxy.
- Jegadeesh and Titman (1993) momentum (12-1 winners keep winning for 3-12 months) and De Bondt and Thaler (1985) long-run reversal (3-5 year losers rebound) are the reason the matrix scores momentum and contrarian buying separately.
- Brinson, Hood and Beebower (1986) style attribution is out of scope: the ledger has no target policy, so the review attributes nothing to "allocation".

**Two distinctions the reading keeps.**

- Decision quality vs outcome: judge the process (what was known at the time, position sizing, holding period consistent with the stated reason) separately from the result. A sale followed by a rise is not automatically a mistake, and a sale followed by a fall is not automatically skill.
- Loss severity is not the disposition lens: a −50% position held for a year is not the same signal as a −5% disposition. The disposition effect is about which lots get sold relative to the alternatives held that day, not whether a large loss means the thesis broke. Large losses need the fundamental review, not the disposition lens.

**Deep review.** It asks which decisions were good on what could be known then. `references/deep-roles.md` holds the brief for each research subagent.

- `decisions.py --pick` chooses decisions by money moved, never by result, and the list it prints carries no results.
- A claim dated after a decision cannot count as known: `decisions.py` rejects it. What came out later is kept apart.
- A sale's result is its move against the benchmark over the next 90 days. A buy's is its return so far, not benchmark-adjusted.
- Grade against result gives skill, luck, bad luck, mistake or unclear. Few decisions can land in any of these by chance.
- A grade rests on public evidence, not on what the person knew or intended.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/run-review.py" [--account ID ...] [--symbol SYM ...] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--benchmark SPY] [--as-of YYYY-MM-DD] [--no-prices] [--research-top N] [--save]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/review.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/render.py" --in review.json --out page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/decisions.py" --pick 8 < DIR/deep-trades/baseline/review.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/decisions.py" < DIR/deep-trades/decisions.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/render_decisions.py" --in DIR/deep-trades/page.json --out DIR/deep-trades/page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/decision_store.py" save --in DIR/deep-trades/page.json [--source URL]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/decision_store.py" check --review DIR/trade-review.json [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trade-review/scripts/decision_store.py" list
```

| Script | What it does |
|---|---|
| `run-review.py` | The review of the ledger. Prints JSON: `review.py`'s output plus `sources`, `ledger`, `largest_buys` and, with `--save`, `report_path` (a JSON copy in the plugin data directory). |
| `review.py` | Pure math on a ledger you already have. Its docstring is the method and the output contract. |
| `render.py` | Builds the interactive page from a saved `run-review.py` result. Prints `{"out", "title", "round_trips", "flags"}`. |
| `decisions.py` | Deep review: `--pick N` lists the largest decisions with no results. Without it, joins grades to results and reports cells, patterns and flags. Its contract is in its docstring. |
| `render_decisions.py` | Deep review page from `decisions.py` output, a headline of 25 words at most and a summary. |
| `decision_store.py` | Keeps deep reviews between sessions. `check` keeps every grade and re-measures the results against a newer `run-review.py` result. |

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Empty ledger, bad filter, bad dates or bad `--research-top`. For `render.py`: the input is not a review result. | `error` |
| 5 | Corrupt ledger | `hint` |
| 6 | Python dependencies missing | the error, and say the setup skill repairs it |

## Steps

**The user asks for a review of their trades**

When one question names a single big decision, end the reply with one line: a deep review is available and sends about ten research subagents.

1. Run `run-review.py --save` once, writing the output to a file: `> DIR/trade-review.json`. DIR is the session scratchpad. Add `--account` or `--symbol` only when the user scopes the question.
2. If it exits 2 with an empty-ledger message, the user has not imported history yet. Hand off to statement-import: `sync-broker.py` for the last two years, `import-csv.py` for older statements. Come back when `ledger.py --summary` shows BUY and SELL rows.
3. Research the first 5 items of `research_queue`, and no more. For each one:
   1. Use the WebSearch tool for "<company name or symbol> news", restricted to the seven days before `sell_date`.
   2. If the user asks about buys, also search the seven days before `first_buy_date`.
   3. Read at most two results per item, following the `<research_dating>` rules.
   4. Record the source.
   5. If nothing relevant is found, write "no public catalyst found". Do not invent one.
4. Run `render.py --in DIR/trade-review.json --out DIR/trade-review.html`.
5. Publish the HTML with the Artifact tool: icon `review`, description "Trade review as of DATE". On later runs republish the same file path so the link stays stable.
6. Reply with the published-page format below.
7. If the Artifact tool is not available in the session (a headless or non-interactive host), skip steps 4 to 6 and reply with the markdown fallback instead. Never send both.
8. If the user then asks what to do next with an open lot, finish the review first, then hand off to portfolio-analysis or valuation.

**The user asks for a deep review of their decisions, or skill against luck**

Run this only when the person asks for a deep review or for depth.

1. Make `DIR/deep-trades/` and its `baseline/`, `research/` and `threads/` folders, where DIR is the session scratchpad. Write `run-review.py --save` to `baseline/review.json`. If the ledger is empty, hand off to statement-import, as above. A run with `PRICES_UNAVAILABLE` has no results to compare, so say so and stop.
2. Run `decisions.py --pick 8 < baseline/review.json`, and write it to `picks.json`. Use a smaller number if the person scopes it, and name the share of money covered from `amount_covered`.
3. Tell the person it has started: about 10 subagents and 30 web searches. Ask once whether they want to give their own reason for any decision, and put each answer in `stated_reason`. With the trade-journal skill installed, the reason in a written plan counts too. These go on the page only, never to the Blind grader.
4. Write `budget.json`: the searches this run may spend, each role's cap and the searches used so far. The session has one shared pool of about 200.
5. Dispatch one Decision researcher per decision, up to five at a time. Use the Agent tool, general-purpose type.
   - Each prompt names the Shared rules section and the role's section of `references/deep-roles.md` by absolute path, plus the case folder, today's date, the symbol, the action and the date. Nothing else from the review goes in a prompt.
   - Subagents do not inherit `SNAPTRADE_PY` or `CLAUDE_PLUGIN_ROOT`. Resolve both to absolute paths in the prompt.
   - If a role fails or returns nothing, retry it once, then add it to `missing_roles` and go on.
6. Write `blind.json` from the findings: each decision's symbol, action, date and known claims, with no amounts, results or later claims. Dispatch the Blind grader with that one file.
7. Write `decisions.json`, the `decisions.py` input: `as_of`, `review` from the baseline, and each decision's known claims, later claims, catalyst, grade and reason. Run `decisions.py`. Fix what it rejects by going back to the source, and move a claim dated after the decision into `later`. Never change a date to fit.
8. Dispatch the Pattern reader, then the Red team, with the output. Apply a change only where its sources hold up, and keep each rejected change in `notes` with the reason. A grade changes only by sending the corrected evidence to a new Blind grader, never by editing it in light of the result.
9. Run `decisions.py` again. Write `page.json`: `as_of`, `headline`, `summary`, `review`, `missing_roles`, `notes`.
   - The headline says what the grades show against the results, in 25 words or fewer. The summary names the clearest case of luck or bad luck, and what the patterns can and cannot support.
10. Run `render_decisions.py`. Publish the page with the Artifact tool: icon `review`, description "Decision review as of DATE". If the Artifact tool is unavailable, use the markdown fallback.
11. Run `decision_store.py save --in DIR/deep-trades/page.json --source <page link>`.

**The user asks to re-check a deep review**

1. Run `run-review.py --save` once, writing to `DIR/trade-review.json`, then `decision_store.py check --review DIR/trade-review.json`. Exit 2 with "no saved review" means none has been run: offer one.
2. Present `changed`, each changed decision's grade with its then and now result and cell, and `cells`.
3. Say that the grades are frozen, and that this re-measures results only.
4. If `rerun_due` is true, give `rerun_reasons` and say a new deep review would cover them.

## Reply format

**Deep review, page published.** In this order, then stop.

1. The artifact link on its own line.
2. The headline.
3. One line from `cells`: skill · luck · bad luck · mistake · unclear, and `process_gap` when it is not null.
4. The clearest case of luck and of bad luck, if any: the decision, its grade, its result, and the evidence behind the grade with source and date.
5. What the patterns support, in one or two sentences. Say so when there are too few.
6. **Flags**: one bullet per `review.flags[].message` and per missing role, or "None".
7. One line: subagents dispatched and searches used.
8. One sentence: grades rest on public evidence, not on what the person knew, and this is general information, not financial, tax, or legal advice.

**Deep review, markdown fallback.** The same parts without the link, plus each decision with its grade, result and the known claims on both sides.

**The ordinary review.** The formats below.

Every number comes from the script. The only text you write yourself is the news context in **What was happening** and the **Reading**, both labelled as such.

**When the page was published (the default):**

1. The artifact link on its own line.
2. One line: `summary.round_trips` round trips · win rate `summary.win_rate` · total P&L `summary.total_pnl` (realized `summary.realized_pnl` + dividends `summary.dividends_captured`) · disposition `disposition.disposition` (PGR `disposition.pgr` vs PLR `disposition.plr`) · holding instead `counterfactual.hold_delta`.
3. **What was happening** — as section 5 of the fallback: one line per `research_queue` item with the dated news context and your classification, cited.
4. **Reading** — as section 7 of the fallback: two to four sentences.
5. **Flags** — one bullet per `flags[].message`, or "None".
6. Stop. The page carries the round trips, drift, counterfactuals, disposition, open lots, strategy matrix and yearly sections, so do not repeat them. If the user asks for a number the page shows, read it from the script's JSON.

**Markdown fallback (only when the Artifact tool is unavailable):** these parts in this order.

**Trade review** — as of `as_of`, `ledger.transactions_used` ledger rows, accounts `ledger.accounts`, `ledger.date_range`

One line: `summary.round_trips` round trips · win rate `summary.win_rate` · realized `summary.realized_pnl` + dividends `summary.dividends_captured` = `summary.total_pnl` · profit factor `summary.profit_factor` · median hold `summary.median_holding_days` days · `summary.trades_per_year` trades/yr

1. **Round trips** — table in sell date order: Symbol · Bought · Sold · Days · Units · Avg cost · Sell price · Dividends · Total P&L · Return · 90d after sale · vs benchmark 90d. Then:
   - "Unmatched sells: …" from `unmatched_sells` when it is not empty.
   - "Symbols without prices: …" from `missing_prices` when it is not empty.
2. **Counterfactuals** — one line from `counterfactual`: proceeds `proceeds`; holding instead would be worth `hold_value` (`hold_delta`); proceeds in `benchmark_symbol` would be `proceeds_in_benchmark`.
3. **Disposition effect (Odean 1998)** — one line from `disposition`: realized `realized_gains` gains vs `paper_gains` paper gains (PGR `pgr`), `realized_losses` losses vs `paper_losses` paper losses (PLR `plr`), disposition `disposition`.
   - State the reference values: Odean found PGR 0.148 vs PLR 0.098 across 10,000 accounts; a positive gap means winners are sold and losers kept.
4. **Open lots** — table from `open_lots`: Symbol · Bought · Days · Units · Avg cost · Price · Unrealized · Return.
5. **What was happening** — for each researched `research_queue` item (at most 5):
   - One line "SYMBOL sold DATE (`why`, P&L, 90d after: drift_90):" followed by the news context you found for the week before the sale.
   - Then your one-line classification: earnings/guidance, macro or sector move, company event, price target reached, tax or cash need, or "no public catalyst found".
   - Cite the source for each item.
6. **Strategy matrix** — table from `strategy_matrix`: Strategy · Alignment · Evidence (list the evidence key/values verbatim).
7. **Reading** — two to four sentences, labelled "Reading:", that separate decision quality from outcome (a good exit that was followed by a drop, a bad exit that was followed by a rise, and so on). Use only the numbers above and the established findings named in Background. No advice.
8. **Flags** — one bullet per `flags[].message`, or "None".

Money to 2 decimal places with thousands separators. Ratios (`*_return`, `win_rate`, `drift*`, `pgr`, `plr`, `disposition`) as percentages to 1 decimal place. Null shows as "—".

## Rules

- Every number comes from the script.
- Run `run-review.py` once. Never rerun to "refresh" within one answer.
- The reading references only the numbers in the script's JSON and the established findings in Background.
- Never invent a catalyst. When the search finds nothing relevant, write "no public catalyst found".
- In a deep review, a grade rests only on evidence dated by the decision. Decision researchers and the Blind grader never see a result or a trade's size.
- In a deep review, a trade's size, a gain or loss or a person's identifier never goes in a search, URL or fetch.
- A saved grade never changes because of how a decision turned out.

<research_dating>
Every news item, analyst action, data release, or calendar entry you present carries the publication date printed on the source page, the source, and what it says. Search-result snippets blend years; the dateline on the article is the date.
1. Fix the window first: today's date, then the period the question covers ("this week" is the five trading days ending today; a price move is the sessions in which it happened).
2. Read the dateline of each candidate before using it. A hit that matches the month and day but not the year is a different year's event: leave it out, or label it "background (DATE)".
3. A cause offered for a price move is dated inside the move window. When no dated item falls inside the window, write "no dated catalyst found for WINDOW" and describe the move from price and volume alone.
4. Calendar dates (CPI, FOMC, central-bank decisions, earnings, ex-dividend) are for the current year, confirmed against a script's `as_of` field or a dated source before being presented as upcoming.
5. Items appear newest first with the date inline, e.g. "(Sep 8, 2026, Reuters)".
</research_dating>

- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
