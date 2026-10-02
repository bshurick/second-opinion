---
name: dividend-income
description: Reports dividend income from connected holdings, with projected annual income, yield on cost, trailing 12 months, income by month, next ex-dates, cuts and payout ratios. Use when the user asks "how much do I earn in dividends" or for a dividend calendar.
---
Reports the dividend income the user's holdings generate: one script run, one fixed layout, numbers only. Whether to change a holding belongs to another skill.

## Background

- **What `dividends.py` fetches.** Accounts once, positions once per account, and ONE batched Yahoo download of dividend history. It then runs `income.py`.
- **The math.** `income.py` is the shared math. The method (special-dividend filter, frequency inference, trailing windows, growth, monthly schedule, safety screen) and both contracts are in its docstring.
- **Forward figures.** The last regular dividend times the inferred payments per year. They assume the payer keeps paying.
- **Trailing figures.** What was actually declared by ex-date in the last 12 months.
- **Ex-dates.** `next_ex_date_est` and `next_ex_amount_est` are estimates from the last ex-date plus the usual interval.
- **Safety.** `safety.score` is a heuristic screen, not a rating.
- **Yield on cost.** Yield on cost that exceeds the current yield means the holding was bought cheaper, not that it is a better investment.
- **The page.** `render.py` turns a saved `dividends.py` result into one self-contained HTML page for the Artifact tool. The page carries the payers table, the monthly schedule and the ex-date list:
  - stat tiles for annual income, yield, yield on cost and trailing 12 months
  - income by month, with the payers in the tooltip
  - the upcoming ex-date list
  - a sortable holdings table with search, a payers-only toggle and dividend cuts marked
  - flags; light and dark themes; no external scripts
- **Other skills.** Whether to add, trim, or replace a dividend payer, or whether a stock is a good buy, belongs to portfolio-analysis or valuation.

## Scripts

Run with the Bash tool. All three scripts print JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/dividend-income/scripts/dividends.py" [--account ID ...] [--payout] [--yield-context] [--years N] [--as-of YYYY-MM-DD] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/dividend-income/scripts/income.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/dividend-income/scripts/render.py" --in dividend-income.json --out page.html
```

| Script | What it does |
|---|---|
| `dividends.py` | Fetches holdings and dividend history, then runs `income.py`. |
| `income.py` | Pure math on data you already have. |
| `render.py` | Interactive page from a `dividends.py` result. Prints `{"out", "title", "positions", "payers", "flags"}`. |

| Flag | Effect | Cost |
|---|---|---|
| `--account ID` | Restrict to the named account or accounts. | |
| `--payout` | Adds payout ratio and trailing earnings per payer. | one Yahoo call per symbol |
| `--yield-context` | Adds `price_1y_change`, `yield_1y_ago` and `yield_vs_1y_ago` per payer. | one batched close-history call |
| `--years N` | Years of dividend history to pull. Default 5. | |
| `--as-of YYYY-MM-DD` | Pins the as-of date. Default today. | |
| `--partial` | Run without E*Trade when its login is pending. | |

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Unknown account id, or (`render.py`) the input is not an income result | Show `error`. |
| 4 | Credentials missing | Show the `hint`. |
| 4, code `ETRADE_REAUTH` | An E*Trade login is needed | Follow the session's broker-login rule: show the `url`, get the verifier code, run the connect skill's `etrade-login.py --verifier CODE`, rerun once. `--partial` runs without E*Trade. |
| 5 | SnapTrade or Yahoo error | Show the error. |
| 5, code `NO_ACCOUNTS` | Nothing is connected | Point to the connect skill. |
| 6 | Python dependencies missing | Show `requirements` / `install_log`. |

## Steps

1. Pick the flags for `dividends.py`:

   | The request | Flags |
   |---|---|
   | Dividend income, yield, calendar | none |
   | Dividend safety, payout, or coverage | `--payout` |
   | Whether a payer's yield is elevated because the price fell | `--yield-context` |
   | The user names an account | `--account ID` |

2. Run `dividends.py` once, writing the output to a file: `> DIR/dividend-income.json`. DIR is the session scratchpad.
3. If the run exits non-zero, follow the exit code table and stop.
4. If the Artifact tool is available in the session, deliver the page:
   1. Run `render.py --in DIR/dividend-income.json --out DIR/dividend-income.html`.
   2. Publish the HTML with the Artifact tool: icon income, description "Dividend income as of DATE".
   3. On later runs republish the same file path, so the link stays stable.
   4. Reply with the page reply format below.
5. If the Artifact tool is not available (a headless or non-interactive host), reply with the markdown fallback format below instead.
6. If the user states a monthly spending target, add the coverage arithmetic from the report's annual income: annual income ÷ (monthly spending × 12). Present the coverage number and the gap against 1.0.
7. If the user asks whether to add, trim or replace a payer, or whether a stock is a good buy, finish the income report first, then hand off to the skill named in Background.

## Reply format

### Page reply (the default, when the page was published)

In this order, then stop:

1. The artifact link on its own line.
2. One line: Projected annual income `totals.annual_income` · Portfolio yield `totals.portfolio_yield` · Yield on cost `totals.yield_on_cost` · Trailing 12m received `totals.ttm_income` · `totals.payer_count` of `totals.position_count` positions pay
3. **Flags** — one bullet per `flags[].message`, or "None".

Do not repeat the sections the page carries. If the user asks for a number the page shows, read it from the script's JSON.

### Markdown fallback (only when the Artifact tool is unavailable)

Render the script's JSON in exactly this order, then stop.

**Dividend income** — as of `as_of`

One line: Projected annual income `totals.annual_income` · Portfolio yield `totals.portfolio_yield` · Yield on cost `totals.yield_on_cost` · Trailing 12m received `totals.ttm_income` · `totals.payer_count` of `totals.position_count` positions pay

1. **Payers** — table from `positions` where `annual_income` > 0: Symbol · Units · Frequency · Last dividend (ex-date) · Forward rate · Yield · Yield on cost · Annual income · Share · TTM change · 3y growth · Payout · Safety.
   - The Safety cell is `safety.score`/10, plus the `safety.flags` codes. Say once that the Safety column is a heuristic screen, not a rating.
   - When rows carry yield-context fields, add a line under the table: Symbol · `price_1y_change` · `yield_1y_ago` · `yield_vs_1y_ago`.
   - Then one line listing non-payers (`annual_income` 0 or null).
2. **Next 12 months** — table from `monthly`: Month · Income · Payers. Skip zero months only if more than half the months are zero, then say "other months: 0".
3. **Upcoming ex-dates** — payers sorted by `next_ex_date_est`: Symbol · Est. ex-date · Est. amount (`next_ex_amount_est`). Note that dates are estimates from the last ex-date plus the usual interval.
4. **Flags** — one bullet per `flags[].message`, or "None".

### Number formats

| Value | Format |
|---|---|
| Money | 2 dp with thousands separators |
| Per-share amounts | 4 dp |
| Ratios (`*_yield`, `income_share`, `ttm_change`, `growth_*`, `payout_ratio`, `price_1y_change`, `yield_1y_ago`, `yield_vs_1y_ago`) | percentages to 2 dp |
| `payment_cv` | a coefficient of variation, shown as a plain ratio, not a percentage |
| null | "—" |

## Rules

- Every number comes from the script. Do not recompute or add figures. The spending-coverage arithmetic in the steps is the one exception, and it uses the report's own figures.
- Never run `dividends.py` twice in one answer. The one rerun after an E*Trade login is the only exception.
- Publish the page or write the markdown fallback, never both.
- No commentary or opinions outside the Flags section.
- Say once when a figure is a projection: forward figures assume the payer keeps paying.
- When the user asks, say whether a number is forward or trailing.
- Present spending coverage as arithmetic on the report's own figures, never as advice on how to close the gap.
- Say nothing about yield on cost versus current yield unless asked.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
