---
name: tax-aware
description: Gives a US-federal tax view of the imported ledger with realized gains, wash sales, open lots, estimated tax, harvesting and a deep multi-year plan comparison. Use when the user asks "what tax do I owe", "wash sale", "harvest losses" or to compare plans.
---
Gives a mechanical, US-federal tax view of the user's ledger at rates they state, so they can plan with their tax professional. The numbers come from the script; the reply describes them, their assumptions, and what is not modelled. It stops before any decision to sell, harvest or wait. A deep review compares multi-year plans on after-tax wealth, with every rule checked against a primary source.

## Background

- **Data.** `tax-report.py` reads `ledger.json` (built by the statement-import skill), fetches one batched Yahoo quote for the symbols still held, and runs `tax.py`.
- **Method.** FIFO lots, the holding-period rule, the wash-sale window and basis adjustment, netting, the 3,000 deduction and carryforward, harvesting thresholds and lot selection are defined in `tax.py`'s docstring.
- **Rates are decimals.** Defaults: short-term 0.24, long-term 0.15, state 0, NIIT 0. State and NIIT are flat add-ons.
- **Holding period.** Long-term treatment needs more than one year of holding (IRS Pub 550: the holding period starts the day after the purchase).
  - A sale on the one-year anniversary of the buy date is still short-term. The first long-term day is the day after the anniversary.
  - A plain day count misfires when the year spans Feb 29, so the script compares calendar dates. A Feb 29 purchase turns long-term on Mar 1 of the next year.
  - The script flags lots within 60 days of crossing that have a gain, with the estimated saving.
- **Wash sale (IRS Pub 550).** A loss is disallowed when substantially identical shares are bought within 30 days before or after the sale, in any account, including IRAs and dividend reinvestment.
  - The disallowed amount is added to the replacement lot's basis, so it is deferred, not lost, unless the replacement was bought in an IRA.
- **Netting.** Short-term and long-term results are netted separately, then against each other. Up to 3,000 of net loss (1,500 for married filing separately) offsets ordinary income each year, and the rest carries forward indefinitely.
  - The script always applies 3,000.
  - The chain is replayed across every year in the ledger, so a loss from an earlier year reduces what this year's gains owe.
  - Prior years are replayed with raw gains and today's rates (an approximation).
- **Harvesting.** Harvesting a loss only helps when there is something to offset or the 3,000 deduction is unused. Swapping into a similar (not substantially identical) fund keeps market exposure.
- **Lot identification.** Specific-lot identification must be given to the broker at or before the sale. The default at most brokers is FIFO for stocks and average cost for mutual funds.
- **The page.** `render.py` turns a saved `tax-report.py` result into one self-contained HTML page for the Artifact tool, with light and dark themes and no external scripts. It carries:
  - the disclaimer line, and stat tiles for the short- and long-term nets, the estimated liability and the carryforward;
  - realized sales with wash sales highlighted, and the netting summary;
  - a sortable open-lots table with long-term dates and days to long-term;
  - harvesting candidates, and a FIFO vs highest-cost vs tax-minimal block per planned sale;
  - flags, and the "Not modelled" list.
- **Other skills.** The ledger belongs to statement-import. Orders belong to portfolio-analysis.
- **Deep review.** It asks what ends up in the person's pocket across several plans, and which assumption decides the comparison. `references/deep-roles.md` holds the brief for each research subagent.
  - `tax_plans.py` runs each plan year by year: brackets, stacking, Schedule D netting, carry with character, NIIT, the pro-rata conversion rule, and lots sold at their grown price. Sales already made this year count in every plan.
  - Plans compare on `after_tax_wealth` at one end date, not on tax paid, since a conversion pays more now on purpose. Its wealth figure depends on stated growth and exit rates.
  - `tests` rerun every plan with other assumptions. A flip means the assumption decides the comparison more than the math does.
  - It rejects a rule table with no source or date and a plan whose action has no rule cited. Secondary sources and projected tables are flagged.
  - It compares plans and names no plan to follow. It is not a return or tax advice.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/tax-aware/scripts/tax-report.py" [--account ID ...] [--as-of YYYY-MM-DD] [--short-term R] [--long-term R] [--state R] [--niit R] [--price SYMBOL=PRICE ...] [--sell SYMBOL UNITS] ... [--sell-after YYYY-MM-DD] [--min-loss N] [--min-loss-pct R]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/tax-aware/scripts/tax.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/tax-aware/scripts/render.py" --in tax-aware.json --out page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/tax-aware/scripts/tax_plans.py" < DIR/deep-tax/plans.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/tax-aware/scripts/render_plans.py" --in DIR/deep-tax/page.json --out DIR/deep-tax/page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/tax-aware/scripts/plan_store.py" save --in DIR/deep-tax/page.json [--source URL]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/tax-aware/scripts/plan_store.py" check --report DIR/tax-aware.json [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/tax-aware/scripts/plan_store.py" list
```

| Script | What it does |
|---|---|
| `tax-report.py` | The tax view of the ledger. Prints JSON: `tax.py`'s output plus `sources`, `ledger` and `missing_prices`. |
| `tax.py` | Pure math on a ledger you already have. Its docstring is the method and the output contract. |
| `render.py` | Builds the interactive page from a saved `tax-report.py` result. Prints `{"out", "title", "realized", "open_lots", "flags"}`. |
| `tax_plans.py` | Deep review math: multi-year plans, compared on after-tax wealth, with assumption tests and flags. Its contract is in its docstring. |
| `render_plans.py` | Deep review page from `tax_plans.py` output, a headline of 25 words at most and a summary. |
| `plan_store.py` | Keeps deep reviews between sessions. `check` reruns the saved plans on a newer `tax-report.py` result, with no new research. |

| `tax-report.py` flag | Use |
|---|---|
| `--account ID` | Scope to one account. Repeatable. |
| `--as-of YYYY-MM-DD` | Compute the view as of that date instead of today. |
| `--short-term R` `--long-term R` `--state R` `--niit R` | The user's marginal rates, as decimals. |
| `--price SYMBOL=PRICE` | Fill or override a price Yahoo could not quote. Repeatable. |
| `--sell SYMBOL UNITS` | Model a planned sale. Repeatable; each sale is modelled against the full open lots. |
| `--sell-after YYYY-MM-DD` | Model the planned sales as of a later date. Lots past their one-year anniversary by then are long-term. Needs at least one `--sell`. |
| `--min-loss N` `--min-loss-pct R` | Harvesting thresholds: the smallest loss in money and as a share of cost. |

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Empty ledger or bad flags. For `render.py`: the input is not a tax result. | `error` |
| 5 | Corrupt ledger | `hint` |
| 6 | Python dependencies missing | the error, and say the setup skill repairs it |

## Steps

**The user asks about their tax position, a sale, or harvesting**

When the question spans several years or plans, end the reply with one line: a deep review is available and sends about five research subagents.

1. Settle the rates.
   - If the user has stated their marginal rates, pass them with the rate flags.
   - If they have not, ask once. When they give none, run with the defaults (24% short-term, 15% long-term, no state, no NIIT) and say so on the disclaimer line.
   - Never look up or guess their bracket.
2. Run `tax-report.py` once, writing the output to a file: `> DIR/tax-aware.json`. DIR is the session scratchpad. Add flags by what the user asked:

   | The user | Flag |
   |---|---|
   | is weighing a specific sale | `--sell SYMBOL UNITS` (repeat it for several planned sales) |
   | wants those sales modelled at a later date | `--sell-after YYYY-MM-DD` |
   | scopes to one account | `--account ID` |
   | holds something Yahoo could not quote | `--price SYMBOL=PRICE` |

3. If it exits 2 because the ledger is empty, hand off to statement-import. Come back when the ledger holds BUY and SELL rows for the tax year.
4. Run `render.py --in DIR/tax-aware.json --out DIR/tax-aware.html`.
5. Publish the HTML with the Artifact tool: icon `tax`, description "Tax view for YEAR as of DATE at the stated rates". On later runs republish the same file path so the link stays stable.
6. Reply with the published-page format below.
7. If the Artifact tool is not available in the session (a headless or non-interactive host), skip steps 4 to 6 and reply with the markdown fallback instead. Never send both.
8. If the user is married filing separately, say the script applied 3,000 and that the deduction and carryforward figures would differ under the 1,500 cap.
9. Present the numbers for each path (sell, harvest, wait) and stop. If the user wants to place an order, hand off to portfolio-analysis.

**The user asks for a deep review, or to compare multi-year plans**

Run this only when the person asks for a deep review or for depth.

1. Make `DIR/deep-tax/` and its `baseline/` and `research/` folders, where DIR is the session scratchpad. Write `tax-report.py` to `baseline/tax-report.json`. If the ledger is empty, hand off to statement-import, as above.
2. Ask once for what only the person knows, and write it to `income.json`: filing status, expected ordinary income and withholding for each year, Traditional and Roth balances with any after-tax basis, the years to cover, and their exit-rate and growth assumptions. Never look up or guess a bracket or income. Without income for a year, stop and say the comparison needs it.
3. Tell the person it has started: about 5 subagents and 20 web searches. Write `budget.json`: the searches this run may spend, each role's cap and the searches used so far. The session has one shared pool of about 200.
4. Dispatch a Rule checker for each of the three areas in `references/deep-roles.md`, in parallel. Use the Agent tool, general-purpose type.
   - Each prompt names the Shared rules section and the role's section by absolute path, plus the case folder, today's date, the filing status, the tax years, the area and the search cap. No figure about the person goes in the prompt.
   - If a role fails or returns nothing, retry it once, then add it to `missing_roles` and go on. A plan whose rule is missing cannot run, so say which plans fell out.
5. Dispatch the Plan designer with the file paths. It has no web access and the only role that reads the income file.
6. Write `plans.json`, the `tax_plans.py` input, with `Do nothing` first. Run `tax_plans.py`. Fix what it rejects by going back to the source, not by inventing a citation.
7. Dispatch the Red team with the output. Apply its changes where its sources hold up, and keep each rejected change in `notes` with the reason.
8. Run `tax_plans.py` again. Write `page.json`: `as_of`, `headline`, `summary`, `plans`, `missing_roles`, `notes`.
   - The headline names what decides the comparison, in 25 words or fewer. It names no plan as the one to take. The summary says what each plan trades off and what could change the order.
9. Run `render_plans.py`. Publish the page with the Artifact tool: icon `tax`, description "Tax plan comparison as of DATE". If the Artifact tool is unavailable, use the markdown fallback.
10. Run `plan_store.py save --in DIR/deep-tax/page.json --source <page link>`.

**The user asks to re-check a tax plan comparison**

1. Run `tax-report.py` once, writing to `DIR/tax-aware.json`, then `plan_store.py check --report DIR/tax-aware.json`. Exit 2 with "no saved" means none has been run: offer one.
2. Present each plan's then and now figures, `leading_then` and `leading_now`, `short` and `actions_due` with `days_left`.
3. Say that this reruns the arithmetic only. The rules stay as checked at the review and no new research ran, so a change in law would not show.
4. If `rerun_due` is true, give `rerun_reasons` and say a new deep review would check the rules again.

## Reply format

**Deep review, page published.** In this order, then stop.

1. The artifact link on its own line.
2. The disclaimer line, with the growth and exit rates.
3. The headline.
4. One line per plan: `name` · `wealth_vs_baseline` · `tax_vs_baseline`, highest first, described as highest on these assumptions only.
5. `deciding_assumptions`: which assumptions change the order. If none do, say the order held in every test.
6. **Flags**: one bullet per `plans.flags[].message` and per missing role, or "None".
7. One line: subagents dispatched and searches used.
8. One line: which plan to follow, if any, is for the person and their tax professional.

**Deep review, markdown fallback.** The same parts without the link, plus each plan's actions and years, the rules with their sources, and the "Not modelled" list.

**The ordinary view.** The formats below.


Every number comes from the script. The disclaimer line is: "Estimate for planning at the stated rates; not tax advice or a return."

**When the page was published (the default):**

1. The artifact link on its own line.
2. The disclaimer line, with the rates from `rates`: short-term `short_term`, long-term `long_term`, state `state`, NIIT `niit`.
3. One line from `summary`: Short-term net `short_term_net` · Long-term net `long_term_net` · Estimated tax `estimated_tax` · Carryforward `loss_carryforward`. When `harvest_candidates` is not empty, add "harvestable losses `harvest_total.losses`".
4. **Flags** — one bullet per `flags[].message`, or "None".
5. Stop. The page carries the realized, open-lots, harvesting, planned-sale and "Not modelled" sections, so do not repeat them. If the user asks for a number the page shows, read it from the script's JSON.

**Markdown fallback (only when the Artifact tool is unavailable):** open with the disclaimer line, then these sections in this order.

**Tax view** — as of `as_of` (tax year `year`); from `rates`: short-term `short_term`, long-term `long_term`, state `state`, NIIT `niit`

1. **Realized year to date** — table from `realized`: Symbol · Sold · Held (days) · Term · Gain · Wash sale? · Allowed gain. Then:
   - One line from `summary`: short-term net `short_term_net`, long-term net `long_term_net`, disallowed `disallowed_losses`, net `net_capital_gain` taxed as `taxed_as` → estimated capital-gains tax `capital_gains_tax`; dividends `dividends` (assumed qualified) and interest `interest`; estimated total `estimated_tax`.
   - If `loss_carryforward` > 0, add the deduction and carryforward line.
   - If `prior_year_net_losses` > 0, add one line from `carryforward_history`: each earlier year's net loss, deduction and carryforward. Note the simplifications: prior years use raw gains and today's rates.
   - `prior_year_net_losses` is the sum of each prior year's negative net in `carryforward_history`. Each prior-year net already includes the carry it absorbed from the year before it.
2. **Open lots** — table from `open_lots`: Symbol · Bought · Units · Cost · Price · Unrealized · Term · Days to long-term · Tax if sold now. Then the `unrealized` totals on one line.
3. **Harvesting candidates** — table from `harvest_candidates`: Symbol · Units · Unrealized · % · Term · Est. benefit · Last buy · Warning. Then `harvest_total`. If empty: "No positions meet the loss thresholds."
4. **Planned sale** — only when `lot_selection` is present.
   - FIFO lots and tax vs highest-cost lots and tax vs the tax-minimal lots and tax, with `tax_saved_vs_fifo` and `tax_saved_vs_minimal`.
   - With several planned sales, render one such block per `lot_selections` row.
   - Note that the broker must be told which lots to sell before settlement.
5. **Flags** — one bullet per `flags[].message`, or "None".
6. **Not modelled** — always, all of these:
   - the qualified-dividend holding-period test;
   - REIT and bond-fund distributions (ordinary);
   - AMT;
   - state-specific rules;
   - tax-lot methods already elected at the broker;
   - the 0%/20% long-term brackets by income;
   - the 1,500 loss cap for married filing separately;
   - foreign tax credits;
   - crypto: the ledger has no crypto asset class; wash-sale rules do not currently apply to crypto (verify current law); basis tracking for crypto is entirely on the user.

Money to 2 decimal places with thousands separators. Rates and percentages to 1 decimal place. Null shows as "—".

## Rules

- Every number comes from the script. Describe what the numbers show.
- Run `tax-report.py` once per answer.
- Never look up or guess the user's tax bracket.
- In a deep review, every rule comes from a dated source, primary wherever one exists. A rule from memory stays out.
- In a deep review, income, holdings, an employer or a person's identifier never goes in a search, URL or fetch.
- A deep review never names a plan to take. "Highest" holds on the stated assumptions only.
- The "Not modelled" section is mandatory: the page carries it, and the markdown fallback renders it.
- Whether to sell, harvest, or wait is the user's decision with their tax professional.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
