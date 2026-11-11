---
name: personal-finance
description: Budgeting, saving, debt (statements recorded, balances, APRs, interest paid, payoff order), cash-flow planning, account rules and reminders. Use when the user says "what do I owe", "record this statement" or asks a money question not tied to securities.
---
Answers general personal-finance questions: banking and savings products, debt payoff, emergency funds, budgeting, tax-advantaged account rules and insurance basics. It runs the loan, debt-payoff and compound-growth math with a script and looks up current rates on the web.

It also keeps the debt register: one snapshot per account per statement period, transcribed from the statement PDF and validated before it is stored. It is not a stock or portfolio skill.

## Background

- **`finance.py` is the shared math.** Its docstring is the contract for every action. Rates are decimals (0.06 is 6%).

  | `action` | Use it for |
  |---|---|
  | `amortize` | A loan's payment or payoff term, total interest, the effect of an extra monthly payment, and APR against APY. |
  | `debt` | Several debts paid off in avalanche order and in snowball order, with the interest difference. |
  | `compound` | Growth of a balance with monthly contributions, net of fees. |

- **`cashflow.py` reads only the local ledger.** The ledger is `ledger.json`, populated by the statement-import skill. The script never calls SnapTrade or Yahoo and takes no arguments.
- **Current rates and product terms come from web search.** Rates change often. Never guess one or quote one from memory.
- **Illustrative math comes from `finance.py`.** Never use web search for it and never do it by hand.
- **Account rules.** `references/account-rules.md` holds the 401(k), IRA, Roth, HSA, FSA and 529 contribution limits and deduction rules. Each figure there is marked with its tax year, and most are inflation-indexed and change every year.
- **Other skills.** Recorded statements supply `debt_input` (from `debts.py`, below), which is ready-made stdin for the `debt` action. The spending skill supplies `avg_monthly_outflow` from its own cash-flow report for emergency-fund sizing. Individual stocks, ETFs and brokerage portfolios belong to the investing skills.

### The debt register

- **Why the statement PDF.** Card CSV exports carry no balance, minimum, due date or APR, so the source here is the statement itself.
- **Storage.** Snapshots live in `statements.json` under the plugin data directory (`SECOND_OPINION_DATA`, default `~/.claude/plugins/data/second-opinion`).
- **Contracts.** The docstring of `record-statement.py` is the input contract. `debtpicture.py` is the shared math and its docstring is the output contract, which includes `history`, the per-statement series behind every account.
- **Statement input.** stdin to `record-statement.py` is one JSON object. The first use of an account wraps the snapshot with an account block. Later snapshots may be bare with `account_id`.

  ```json
  {"account": {"id": "chase-sapphire-1234", "name": "Chase Sapphire", "issuer": "Chase", "kind": "card", "last4": "1234", "credit_limit": 15000},
   "statement": {"period_start": "2026-07-15", "period_end": "2026-08-14", "previous_balance": 2400.10, "payments": 2400.10,
                 "credits": 35.00, "purchases": 1810.55, "cash_advances": 0, "balance_transfers": 0, "fees": 0, "interest": 0,
                 "new_balance": 1775.55, "minimum_payment": 40.00, "due_date": "2026-09-09", "apr": 0.2424, "note": null}}
  ```

- **Loan kinds.** mortgage, auto, student, heloc and other use these fields instead: previous_balance, principal_paid, interest_paid, escrow, fees, new_balance, payment_due, due_date, apr, remaining_term_months.
- **Rates are decimals.** 24.24% is 0.2424.
- **Account id.** `id` is issuer-product-last4 in kebab case. Record `last4` only, never the account number.
- **Flags from `record-statement.py`.** Returned in `flags`; they never reject a statement.

  | Flag | Meaning |
  |---|---|
  | `CHAIN_GAP` | The previous statement's closing balance does not match this opening balance. Usually a missed statement. |
  | `OVER_LIMIT` | The balance is above the credit limit. |

- **Flags from `debts.py`.**

  | Flag | Meaning |
  |---|---|
  | `NO_STATEMENTS` | The account has no statement recorded. |
  | `STALE` | The statement is older than `assumptions.stale_days` days. |
  | `PAST_DUE` | The due date on the latest statement has passed. Ask whether the payment was made; never assume. |
  | `OVER_LIMIT` | The balance is above the credit limit. |
  | `HIGH_UTILIZATION` | Utilization is above `assumptions.utilization_warn`. |
  | `MINIMUM_ONLY` | The last two payments were the minimum. |
  | `MINIMUM_BELOW_INTEREST` | The minimum does not cover a month's interest. The account is left out of the payoff input. |

- **Other skills.** Payoff order and extra-payment math belong to personal-finance; this skill supplies its input. Transactions and spend by category belong to spending.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/personal-finance/scripts/finance.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/personal-finance/scripts/cashflow.py"
```

| Command | What it does |
|---|---|
| `finance.py` | Reads one JSON object with an `action` of `amortize`, `debt` or `compound` and prints the result. |
| `cashflow.py` | Prints monthly inflow, outflow and net from the local ledger, with `avg_monthly_inflow`, `avg_monthly_outflow`, `savings_rate` and `cash`. |

Both scripts print JSON.

| Exit code | Script | Meaning | What to show |
|---|---|---|---|
| 2 | `finance.py`, `cashflow.py` | Bad input, or unexpected arguments | `error` |
| 4 | `cashflow.py` | No ledger yet | `hint` |
| 5 | `cashflow.py` | Ledger empty or corrupt | `hint` or `error` |
| 6 | `cashflow.py` | Python dependencies missing | the error |

The debt register:

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/personal-finance/scripts/record-statement.py" [--dry-run] [--replace] < statement.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/personal-finance/scripts/record-statement.py" accounts
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/personal-finance/scripts/debts.py" [--as-of YYYY-MM-DD] [--stale-days N] [--utilization-warn 0.30]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/personal-finance/scripts/debts.py" --history ACCOUNT_ID
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/personal-finance/scripts/debtpicture.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/personal-finance/scripts/render_debts.py" --in debts.json --out page.html
```

| Command | What it does |
|---|---|
| `record-statement.py` | Validates one statement snapshot and stores it. `--dry-run` runs every check and writes nothing. `--replace` overwrites the snapshot for the same account and period. |
| `record-statement.py accounts` | Lists the register with each account's latest period and balance. |
| `debts.py` | The debt picture: per-account rows, `totals`, `flags`, `history` and `debt_input`. |
| `debts.py --history` | One account's snapshots in period order. |
| `debtpicture.py` | The shared pure math behind `debts.py`. |
| `render_debts.py` | Turns a saved `debts.py` result into one self-contained HTML page for the Artifact tool. Prints `{"out", "title", "accounts", "flags"}`. |

The page `render_debts.py` builds has a banner for STALE and PAST_DUE, stat tiles, the register sortable by balance, APR and due date with past-due and stale rows highlighted, balance and utilization bars, an interest-paid trend from `history`, and flags. It has light and dark themes and no external scripts.

Every script prints JSON.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad input. Codes `INVALID_ACCOUNT`, `MISSING_FIELD`, `BALANCE_MISMATCH` (with `expected`, `got`, `delta`), `DUPLICATE_STATEMENT` (with `existing`). From `render_debts.py`: the input is not a `debts.py` result. | `error` |
| 4 | `debts.py` found nothing recorded yet, code `CONFIG_MISSING` | `hint` |
| 5 | The statements file is unreadable (`STATEMENTS_CORRUPT`) | `hint` |
| 6 | Python dependencies missing | the error |

## Steps

Pick the case that matches the request.

**The user asks about current rates or products**

1. Search the web for the current figure. Use reputable sources: Bankrate, NerdWallet, FDIC, TreasuryDirect, or the bank's own site.
2. Present the findings with the source and its date, so the user knows how current the data is.
3. Compare several options when that is relevant.

**The user asks to compare financial products**

1. For each product, take the terms from what the user pasted or from a web search you just ran for that specific product. Never from memory.
2. Reply with the product table below.

**The user asks about a loan payment, a payoff, or compound growth**

1. Build the input for the matching `finance.py` action from the docstring.
2. Run `finance.py`.
3. Show its numbers, not just the concept.

**The user asks about payoff order across several debts**

1. If statements are recorded, take `debt_input` from `debts.py`. Otherwise ask for each debt's name, balance, APR and minimum payment.
2. Add `extra_monthly` when the user gave an extra amount.
3. Run `finance.py` with the `debt` action.
4. Reply with the debt payoff format below.

**The user asks how big an emergency fund to hold**

1. Run `cashflow.py` if it has not already run this turn.
2. If it returns a non-null `avg_monthly_outflow`, state the two standard targets as plain arithmetic on that number: "3 × avg_monthly_outflow ($X) = $Y" and "6 × avg_monthly_outflow ($X) = $Z".
3. If there is no ledger, the ledger is empty, or `avg_monthly_outflow` or `cash` comes back null, ask the user for a monthly essential-expenses estimate and use that instead of guessing.
4. Stop at the sizing. Where to hold the money is the product-comparison case.

**The user asks about a contribution limit or deduction rule (401(k), IRA, Roth, HSA, FSA, 529)**

1. Read `references/account-rules.md` before quoting anything.
2. If the current year is later than the tax year marked on the figure, verify the current-year limit with a web search and quote that.
3. Give the rule and the figure with its tax year.

**The question turns on the user's own tax or legal situation (a filing position, an estate or trust question, a contract)**

1. Answer the question fully with the general rules.
2. Then say that a tax professional (CPA or enrolled agent) or an attorney can confirm how they apply to the user.

**Part of the question is about individual stocks, ETFs or a brokerage portfolio**

1. Answer the part you can.
2. Do not explain what this skill can or cannot do, and do not tell the user to ask a different question.

Pick the case that matches the request.

**The user wants a statement recorded**

1. Ask for the PDF path only if the user has not given one.
2. Read the file.
3. Transcribe the summary box into the statement input in Background. The summary box is the "account summary" or "payment information" panel on page 1. The purchase APR is in the interest-charge table.
4. If this is the first use of the account, propose the id slug.
5. Show the transcribed numbers as a short table. On first use, confirm the id slug in that same message.
6. Run `record-statement.py --dry-run`.
7. If `BALANCE_MISMATCH` comes back, re-read the summary box once before asking anything. The usual causes are a credit netted into payments, a missed fee or interest line, a minus sign, or cash advances printed in a separate section.
8. If it still fails, show `expected`, `got` and `delta` and ask the user which line is off.
9. When the dry run is valid, run `record-statement.py` without `--dry-run`.
10. Report in one line each: account, period, new balance, minimum, due date, and every entry in `flags` with its meaning from Background.

**The user gives several statements at once**

1. Order them oldest period first, so `CHAIN_GAP` reads correctly.
2. Do the recording case once per statement, one `record-statement.py` call each.
3. Summarize all of them in one table at the end.

**The user asks "what do I owe", "my debts", "interest I'm paying" (the picture)**

1. Run `debts.py` and write its output to `DIR/debt-tracker.json` (DIR is the session scratchpad). Add `--as-of` only when the user asks about a past date.
2. If `debts.py` exits 4 with code `CONFIG_MISSING`, or `record-statement.py accounts` returns an empty `accounts` list, say nothing is recorded yet, offer to record the first statement, and stop.
3. Run `render_debts.py --in DIR/debt-tracker.json --out DIR/debt-tracker.html`.
4. Publish the HTML with the Artifact tool: icon ledger, description "Debt picture as of DATE". Republish the same file path on later runs so the link stays stable.
5. Reply with the published-page format below.
6. If the Artifact tool is not available in the session (a headless or non-interactive host), skip steps 3 and 4 and reply with the markdown fallback instead. Never send both.

**The user asks about payoff order, extra payments or interest saved**

1. Run `debts.py` and take `debt_input` from its output.
2. If the user gave an extra monthly amount, add it to `debt_input` as `extra_monthly`.
3. Run the personal-finance skill's `finance.py` with that object as stdin.
4. Present avalanche and snowball side by side with the interest difference, as that skill does. Present neither order as preferred.
5. Name every account flagged `MINIMUM_BELOW_INTEREST`. Those accounts are absent from `debt_input`.

**The user asks "how has X moved" or "interest on X over time"**

1. Run `debts.py --history ID`.
2. Show a period table: Period end · Balance · Change · Interest · Fees · Payments · Purchases · Minimum · Due.

**A recorded snapshot is wrong**

1. Re-record the same period with `record-statement.py --replace`.

**The user asks about transactions, spend by category or a CSV export**

1. Say in one line that this skill does not read those, and stop.

## Reply format

**Product comparison.** A table with exactly these columns:

Product · APY · Fees · Minimum balance · Liquidity · Insurance coverage

Write "not stated" in any cell the source does not cover. Never leave a cell blank. Insurance coverage names FDIC or NCUA and the insured limit.

**Debt payoff.** `avalanche` and `snowball` side by side: `order`, `months`, `total_interest`, `payoff_dates`. Then `interest_saved_avalanche_vs_snowball` on one line.

**Rates.** Each rate with its source and date.

**The debt register**

**The picture, page published (the default).** In this order, then stop.

1. The artifact link on its own line.
2. One line: Total debt `totals.total_debt` (revolving `totals.revolving`, installment `totals.installment`) · Weighted APR `totals.weighted_apr` · Minimums `totals.minimum_payments_total` · Next due `totals.next_due` (account, date, amount).
3. **Flags** — one bullet per flag in plain words, or "None". `PAST_DUE` still asks whether the payment was made.

The page carries the register, balances, utilization and interest trend. Do not repeat them in the reply. If the user asks for a number the page shows, read it from the script's JSON.

**The picture, markdown fallback (only when the Artifact tool is unavailable).** In this order.

1. **Flags** — only when `flags` is non-empty. One line each in plain words, using the meanings in Background.
2. **Totals** — from `totals`:
   - total debt `totals.total_debt` (revolving `revolving`, installment `installment`)
   - weighted APR `weighted_apr` (revolving `revolving_weighted_apr`)
   - monthly interest run rate `monthly_interest_run_rate`
   - interest paid trailing twelve months `interest_ttm` (revolving `interest_ttm_revolving`) across the periods recorded
   - utilization `utilization` of `credit_limit_total`
   - minimum payments total `minimum_payments_total`
   - next due `next_due`
   - change since prior statements `change_vs_prior`
3. **Accounts** — a table from `accounts`: Account (`name`) · Kind · Balance · APR · Min/payment (`minimum_payment`) · Due (`due_date`, `days_to_due`) · Utilization · Interest this period · Change vs prior · Statement date (`period_end`). A card with `paid_in_full` true shows its run rate as the cost if the balance were carried.
4. One sentence that the figures are general information from the recorded statements as of `as_of`, not financial advice.

History tables and payoff comparisons stay in markdown, as described in Steps.

## Rules

- Never state a rate or product term from memory. Use a web search you just ran or terms the user pasted, and cite the source.
- Never do loan, payoff or compound-growth arithmetic by hand. Run `finance.py` and show its numbers.
- Never quote a contribution limit without reading `references/account-rules.md`, and verify the current-year figure when the marked tax year has passed.
- In emergency-fund sizing, state the 3× and 6× figures as arithmetic. Do not say which multiple is right for the user.
- Present neither payoff order as preferred. Show both with the interest difference.
- Give specific steps and concrete numbers, not general guidance.
- Always attempt to fully answer the question yourself. When a question turns on the user's specific tax or legal situation (a filing position, an estate or trust question, a contract), give the general rules, then say that a tax professional (CPA or enrolled agent) or an attorney can confirm how they apply to them.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
- Every number comes from the script.
- Never transcribe the full account number. `last4` only.
- Never hand-edit `statements.json`. A wrong snapshot is fixed by re-recording the same period with `--replace`.
- Always run `--dry-run` before recording a statement.
- One `record-statement.py` call per statement, oldest period first.
- Never assume a `PAST_DUE` payment was made or missed. Ask.
- Neither payoff order is presented as preferred. Both are shown with the interest difference.
