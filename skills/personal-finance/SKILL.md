---
name: personal-finance
description: Budgeting, saving, debt payoff, cash-flow planning, account rules and financial reminders. Use when the user asks a money-management question not tied to securities or markets. Investing questions go to the other skills.
---
Answers general personal-finance questions: banking and savings products, debt payoff, emergency funds, budgeting, tax-advantaged account rules and insurance basics. It runs the loan, debt-payoff and compound-growth math with a script and looks up current rates on the web. It is not a stock or portfolio skill.

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
- **Other skills.** The debt-tracker skill supplies `debt_input`, which is ready-made stdin for the `debt` action. The spending skill supplies `avg_monthly_outflow` from its own cash-flow report for emergency-fund sizing. Individual stocks, ETFs and brokerage portfolios belong to the investing skills.

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

1. If the debt-tracker skill has statements recorded, take `debt_input` from its `debts.py`. Otherwise ask for each debt's name, balance, APR and minimum payment.
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

## Reply format

**Product comparison.** A table with exactly these columns:

Product · APY · Fees · Minimum balance · Liquidity · Insurance coverage

Write "not stated" in any cell the source does not cover. Never leave a cell blank. Insurance coverage names FDIC or NCUA and the insured limit.

**Debt payoff.** `avalanche` and `snowball` side by side: `order`, `months`, `total_interest`, `payoff_dates`. Then `interest_saved_avalanche_vs_snowball` on one line.

**Rates.** Each rate with its source and date.

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
