---
name: spending
description: Tracks spending from card or bank exports (CSV, OFX, xlsx) or transcribed receipts, with category drill-down, merchants, recurring charges and cash flow. Use when the user asks "where did my money go", about subscriptions, or to import a card CSV.
---
Keeps the user's spending history the way expense software does: imports card and bank rows, attaches itemized detail beneath a charge, and reports by month, category, merchant and recurring series. It stops at spending: statement PDFs as liabilities belong to debt-tracker and brokerage CSVs to statement-import.

## Background

- **Two layers.** Every card or bank charge is a top-level transaction. Itemized sources (receipts, order histories, invoices) supply the items beneath a charge. The user drills from a category down to the items.
- **Where rows come from.** Supported exports go through presets. Everything else is transcribed by you into one canonical row shape and imported with `--rows`.
- **Storage.** Transactions live in `spending.json` and rules in `spending-rules.json` under the plugin data directory (`SECOND_OPINION_DATA`, default `~/.claude/plugins/data/second-opinion`).
- **Presets.** amex, chase-card, chase-checking, citi, capital-one, discover, bofa-card, apple-card. OFX, QFX and xlsx files are recognised by extension. Anything else takes `--mapping` or `--rows`.
- **Amount sign.** Spend is negative.
- **Categories are fixed.** Groceries, Dining, Coffee, Transport, Fuel, Auto, Housing, Utilities, Subscriptions, Shopping, Amazon, Health, Insurance, Travel, Entertainment, Education, Kids, Pets, Gifts and Charity, Personal Care, Fees and Interest, Taxes and Government, plus Income, Transfer, Uncategorized.
- **Detail.** A slash path under the category (`Groceries/Costco`, `Health/Supplements`, `Home/Repairs/Caulk`). It sits on items, on transcribed rows, or is set by a category rule.
- **Source.** Every row carries `source`: `preset:<name>`, `ofx`, `mapping`, or `transcribed:<kind>`.
- **Canonical row for `--rows`.**

  ```json
  {"date": "...", "description": "...", "amount": -12.34, "merchant": "...", "category": "...", "detail": "...", "post_date": "...",
   "items": [{"name": "...", "amount": -5.00, "category": "...", "detail": "...", "quantity": 1}]}
  ```

  `date`, `description` and `amount` are required. `merchant`, `category`, `detail`, `post_date` and `items` are optional, as are an item's `detail` and `quantity`.
- **Transfers.** Issuer-named card payments, "payment thank you", transfers and Zelle/Venmo always mark a row as a transfer. A bare AUTOPAY, ONLINE PAYMENT and similar weak payment keywords do not when the merchant is a known spend merchant.
- **Row type.** A row's type (purchase, refund, fee, interest, other) is fixed at import. Category rules change category and detail, not type, and never overwrite a transcribed category or detail.
- **Transcribed merchants.** A merchant rule never re-maps a merchant that came from a transcribed row (`merchant_source: transcribed`).
- **What a `month` result carries.** Besides the totals: `transactions` (the month's spend rows, item rows when `--items`), `months` (per-month income, spend and net for up to twelve months) and `recurring` (the series detected through the month's end).
- **Flags.**

  | Flag | Meaning |
  |---|---|
  | `PARTIAL_MONTH` | The month is not over or the export stops early. |
  | `NO_INCOME_DATA` | No checking export, so income and savings rate are unknown. |
  | `UNCATEGORIZED_HIGH` | Over 10% of spend has no category. Offer rules. |
  | `SINGLE_ACCOUNT` | Transfers cannot be matched across accounts yet. |

- **Other skills.** Payoff and budgeting math belongs to personal-finance. Balances, minimums and interest belong to debt-tracker. Statement PDFs as liabilities go to debt-tracker, though their transaction tables can still be transcribed here as rows. Brokerage CSVs go to statement-import.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/import-spending.py" <file.csv|.ofx|.qfx|.xlsx> --account ID [--name TEXT] [--kind card|checking|savings] [--preset NAME | --mapping JSON] [--sheet NAME] [--dry-run]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/import-spending.py" --rows FILE.json|- --account ID --source KIND [--kind card|checking|savings] [--name TEXT] [--dry-run]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/import-spending.py" presets
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/items.py" attach --items FILE.json|- [--date YYYY-MM-DD --amount N [--merchant TEXT] | --id TXID] [--source KIND] [--create --account ID [--description TEXT] [--merchant TEXT]] [--dry-run]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/items.py" list [--id TXID | --date YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/items.py" detach --id TXID
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/rules.py" add category|merchant|transfer|ignore --match REGEX [--category NAME] [--detail PATH] [--merchant NAME] [--note TEXT]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/rules.py" list
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/rules.py" remove KIND INDEX
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/rules.py" apply [--dry-run]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" month [YYYY-MM] [--compare-months N] [--as-of YYYY-MM-DD] [--items]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" changes [YYYY-MM] [--threshold 0.25] [--compare-months N] [--as-of YYYY-MM-DD] [--items]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" drill [PATH] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--no-items] [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" range --start YYYY-MM-DD --end YYYY-MM-DD [--by category|merchant|account|detail] [--items]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" recurring [--min-count 3]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" cashflow [--months 6] [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" uncategorized [--limit 25] [--items]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" search TEXT [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spend.py" merchants [--top 25] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--items]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spendnormalize.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/spendreport.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/spending/scripts/render.py" --in month.json [--changes changes.json] --out page.html
```

| Command | What it does |
|---|---|
| `import-spending.py <file>` | Imports one export file through a preset, `--mapping`, or by extension. `--sheet` picks an xlsx sheet. `--dry-run` writes nothing. |
| `import-spending.py --rows` | Imports canonical rows you transcribed, labelled with `--source`. |
| `import-spending.py presets` | Lists the presets. |
| `items.py attach` | Attaches items to one stored transaction, found by `--date` and `--amount` (plus `--merchant`) or by `--id`. `--create` stores a new transaction when no card row exists yet. Attaching again replaces the items. |
| `items.py list` / `detach` | Shows transactions that carry items / removes one transaction's items. |
| `rules.py add` | Adds a category, merchant, transfer or ignore rule and re-applies the rules to the stored rows. |
| `rules.py list` / `remove` / `apply` | Lists the rules / removes one / re-applies all of them (`--dry-run` shows what would change). |
| `spend.py month` | The month's totals, categories, merchants, recurring series and flags. `--items` counts attached items in their own categories. |
| `spend.py changes` | What moved against the prior months, with the charges behind each move. |
| `spend.py drill` | Walks the category and detail tree at `PATH`. Omit `PATH` for the root. |
| `spend.py range` | Spend over a date window, grouped with `--by`. |
| `spend.py recurring` | Subscriptions and other recurring series, with price creep. |
| `spend.py cashflow` | Income, spend, net and savings rate by month. |
| `spend.py uncategorized` | Uncategorized rows grouped by merchant. |
| `spend.py search` / `merchants` | Rows matching text / top merchants. |
| `spendnormalize.py`, `spendreport.py` | The shared pure math. Their docstrings are the contracts. |
| `render.py` | Turns a saved `month` result, plus the matching `changes` result when given, into one self-contained HTML page for the Artifact tool. Prints `{"out", "title", "month", "transactions", "flags"}`. |

The page `render.py` builds has a banner for `PARTIAL_MONTH` and `NO_INCOME_DATA`, stat tiles, category bars that drill down to merchants and then to a merchant's transactions, a monthly cash-flow line when several months are carried, what changed, top merchants, recurring charges and flags. It has light and dark themes and no external scripts.

Every script prints JSON.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad input. Codes `NO_HEADER`, `UNKNOWN_PRESET`, `INVALID_ACCOUNT`, `INVALID_ITEMS`, `INVALID_INPUT`, `AMBIGUOUS_MATCH` (with `candidates`), `NO_MATCH`. From `render.py`: the input is not a month result. | `error` |
| 4 | Nothing imported yet, code `CONFIG_MISSING` | `hint` |
| 5 | The store or rules file is unreadable (`SPENDING_CORRUPT`, `RULES_CORRUPT`) | `hint` |
| 6 | Python dependencies missing | the error |

## Steps

Pick the case that matches the request.

**The user has an export file (CSV, OFX, QFX, xlsx)**

1. Choose the account id: the debt-tracker register's id when the card is recorded there, otherwise issuer-product-last4 in kebab case.
2. Run `import-spending.py <file> --account ID --dry-run`.
3. If the preset is wrong or `NO_HEADER` comes back, rerun with `--preset`, `--mapping` or `--sheet`.
4. Run it again without `--dry-run`.
5. One file per call. Several files go oldest first.
6. If the result has `uncategorized > 0`, do the uncategorized case below.

**The user has anything else (a pasted list, a statement's transaction table, an invoice, a receipt, a photo)**

1. If the source explains a charge that is already in the store, do the itemize case below instead. Importing it as a second transaction would count it twice.
2. Transcribe it into canonical rows. Use `category` and `detail` when the source shows what was bought, `merchant` when you know it, and `items` when a row breaks down further.
3. Show the transcribed rows as a table and name the source kind.
4. Choose the account id as in the export case.
5. Run `import-spending.py --rows FILE.json --account ID --source KIND`. A `--rows` import defaults the account to `card`. The first `--rows` import into a checking or savings account needs `--kind checking|savings`; later imports to the same account remember it.
6. One transcribed batch per call. Several batches go oldest first.
7. For a photographed or scanned receipt, say once that a physical copy can be misread and that the total was checked against the card charge.
8. If the result has `uncategorized > 0`, do the uncategorized case below.

**A receipt, order history or invoice explains a charge already in the store (itemize)**

1. Transcribe the items: name, amount, category, and detail or quantity when shown.
2. Show the items, their total and the remainder before attaching.
3. If the items total is above the charge, stop and re-read the source. That is a transcription error, not something to force.
4. Run `items.py attach` with `--date` and `--amount`. Add `--merchant` to disambiguate.
5. If `AMBIGUOUS_MATCH` comes back, pick one of the listed `candidates` and rerun with `--id`.
6. If there is no card row yet, rerun with `--create --account ID`.

**After an import with `uncategorized > 0`**

1. Run `spend.py uncategorized`.
2. Propose one rule per merchant in one table: merchant, total, count, proposed category, proposed detail, and the regex.
3. For each rule the user confirms, run `rules.py add category`, with `--detail` when a path helps. Add no others.

**Month review ("where did my money go", "review August")**

1. Run `spend.py month` and write its output to `DIR/spending.json` (DIR is the session scratchpad). Add `--items` when items are attached so the breakdown reflects them.
2. Run `spend.py changes` for the same month, with the same `--items` choice, and write its output to `DIR/spending-changes.json`.
3. Run `render.py --in DIR/spending.json --changes DIR/spending-changes.json --out DIR/spending.html`.
4. Publish the HTML with the Artifact tool: icon receipt, description "Spending review for MONTH". Republish the same file path on later runs so the link stays stable.
5. Reply with the published-page format below.
6. If the Artifact tool is not available in the session (a headless or non-interactive host), skip steps 3 and 4 and reply with the markdown fallback instead. Never send both.
7. If Amazon, Costco, Target, a warehouse club, a grocery delivery or a pharmacy is a top merchant, say that an order history or receipt would break it down, and where it comes from. Offer once per merchant, not every time.

   | Merchant | Where the itemized source comes from |
   |---|---|
   | Amazon | Account, Manage your data, Request your data; or the order list from Amazon's own assistant |
   | Costco, Target | Order history online |
   | Grocery apps | Emailed receipts |

**Drill for savings ("where can I cut", "what is in Shopping", "break down groceries", "show me the items")**

1. Run `spend.py drill` from the root.
2. Run `spend.py drill PATH` into each bucket the user names, down to transactions and items. `Uncategorized` drills from the root like any category.
3. Reply with the drill format below.

**Recurring charges, cash flow and questions**

| The user asks about | Run |
|---|---|
| Subscriptions, price creep | `spend.py recurring` |
| Savings rate, income against spend | `spend.py cashflow`. With `NO_INCOME_DATA`, say income needs a checking export. |
| A merchant, a charge, "how much at X" | `spend.py search` or `spend.py merchants`, with `--items` when the answer is in the items |
| Emergency-fund sizing | `spend.py cashflow`, then hand its `avg_monthly_outflow` to personal-finance |

**Something is wrong in the store (corrections)**

| What is wrong | Fix |
|---|---|
| A category | `rules.py add category`, with `--detail` for a path |
| A mangled merchant name | `rules.py add merchant` |
| A merchant on a transcribed row | Re-import the rows, or attach items with the right merchant. A merchant rule does not change it. |
| An internal move counted as spend | `rules.py add transfer` |
| A row that is not a real transaction | `rules.py add ignore` |
| Wrong items | `items.py attach` again (it replaces), or `items.py detach` |

After a correction, report `changed` and `removed_rows`.

**The request is out of scope**

- Payoff or budgeting math: personal-finance.
- Balances, minimums, interest, or a statement PDF as a liability: debt-tracker.
- A brokerage CSV: statement-import.

## Reply format

**Month review, page published (the default).** In this order, then stop.

1. The artifact link on its own line.
2. One line: Spend `spend_total` · Income `income_total` (or "no checking data") · Net `net` · Savings rate `savings_rate`.
3. **Flags** — one bullet per flag in plain words, or "None".

The page carries the categories, drill-down, cash flow, what changed, merchants and recurring sections. Do not repeat them in the reply. If the user asks for a number the page shows, read it from the script's JSON.

**Month review, markdown fallback (only when the Artifact tool is unavailable).** In this order.

1. **Flags** — only when there are any. One line each in plain words, using the meanings in Background.
2. **Totals** — spend `spend_total`; income `income_total` (or "no checking data"); net `net`; savings rate `savings_rate`; transfer volume `transfers_total` (both sides of each matched pair are counted); refunds `refunds_total`; fees and interest `fees_and_interest`; uncategorized `uncategorized.amount` (`uncategorized.count` rows).
3. **Categories** — a table from `by_category`: Category · This month · Avg prior `compare_months` · Change (`delta`, `delta_pct`) · Share · Transactions. Say once whether items were exploded.
4. **What changed** — from `changes.categories` and `changes.merchants`. One bullet per entry, in words, with the charges in `explained_by`. A `new` entry reads "new this month".
5. **Top merchants** — a table from `top_merchants`: Merchant · Amount · Count · Categories.
6. **New this month** — `new_merchants`, or "none".
7. **Recurring due** — `missing_recurring` and `new_recurring`, or "none".
8. One sentence that the figures come from imported exports through the latest transaction date, general information not financial advice.

**Drill.** In markdown, in this order.

1. The path and `total`.
2. The `children` table: Key · Amount · Share · Count. Give the average per transaction.
3. The `merchants` table: Merchant · Amount · Count.
4. The largest `transactions`, with `has_items` marked and `in_node` shown when it differs from `amount`.
5. The `items` table at a leaf.
6. Any recurring series inside the bucket, by name.
7. One sentence naming where the bucket concentrates (one merchant or one detail carrying most of it).

Searches, recurring, cash-flow and the other reports stay in markdown.

## Rules

- Every number comes from the script.
- Run `--dry-run` before a real file import.
- Never write a guessed category into the store without a rule the user confirmed.
- Never edit `spending.json` by hand.
- Store only item names, amounts and categories. Never copy a receipt image or PDF into the data directory.
- Never import a receipt as a second transaction when the charge is already in the store. Attach items to it.
- Never force items whose total is above the charge.
- The user judges what to cut. Present the numbers and the trade-offs, and never say what to cut.
- Flags come first in a month review, in either reply form.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
