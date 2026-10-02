---
name: statement-import
description: Builds the local transaction ledger by importing brokerage CSV exports and pulling two years of SnapTrade activity, and shows what was imported. Use when the user has statements, CSV files or history older than two years. Analysis belongs to trade-review.
---
Builds and maintains the user's transaction ledger: a local JSON file that other skills (trade-review, dividend-income) read. It imports and checks rows; it does not analyze trades.

## Background

- **Why CSV imports exist.** SnapTrade only serves two years of activity and cannot reach every account, so CSV exports fill the gaps.
- **Storage.** The ledger is `ledger.json` in the plugin data directory (`SECOND_OPINION_DATA`, default `~/.claude/plugins/data/second-opinion`). `ledger.py` prints its path.
- **The conversion.** `normalize.py` is the shared conversion. Its docstring is the contract for ledger entries, column aliases, type keywords and sign conventions.
- **Ledger entry fields.** date, type, symbol, units, price, amount, fee, reinvested, description, security_name, account_id, source_id.

  | Field | Meaning |
  |---|---|
  | `type` | One of BUY, SELL, DIVIDEND, INTEREST, FEE, DEPOSIT, WITHDRAWAL, SPLIT, TRANSFER_IN, TRANSFER_OUT, OTHER. |
  | `units` | Always positive. |
  | `amount` | Signed net cash to the account: buys and fees negative, sells and dividends positive. |
  | `split_ratio` | SPLIT entries only. Parsed from the action/description text ("2:1", "3-for-2", "1:10"); null when nothing parses. |

- **Dedupe key.** date + type + symbol + units + amount + account_id. Duplicates are expected when a sync or import is rerun.
- **Import labels.** `sync-broker.py` labels every import `snaptrade:<account_id>` whatever served it. The account id, not the label, says where a row came from.
- **Broker quirks in CSV exports.**

  | Broker | Quirk |
  |---|---|
  | Schwab | Exports arrive as two CSV sections (transactions and positions); import the transactions section. Dates may read "MM/DD/YYYY as of MM/DD/YYYY"; normalize keeps the first date. |
  | Fidelity | The "Action" column ("Bought", "Sold", "Reinvest Dividend", "Journal", "Wire") maps through the keyword classifier. |
  | Robinhood | Uses "Run Date" and often prints buys as positive amounts; the sign is forced by type. |

- **Other skills.** Analysis of the ledger belongs to trade-review or dividend-income. The E*Trade login belongs to the connect skill.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/statement-import/scripts/import-csv.py" <file.csv> [--account ID] [--mapping JSON] [--dry-run]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/statement-import/scripts/sync-broker.py" [--account ID ...] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/statement-import/scripts/reconcile.py" [--account ID ...] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/statement-import/scripts/ledger.py" [--symbol SYM] [--type TYPE] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--limit N] [--summary] [--verify]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/statement-import/scripts/normalize.py" < input.json
```

| Script | What it does |
|---|---|
| `import-csv.py` | Imports one CSV export into the ledger. Finds the header row, detects columns, deduplicates against the ledger. `--dry-run` writes nothing. |
| `sync-broker.py` | Pulls up to two years of activity for every open connected account into the ledger. `--start` defaults to 729 days ago. |
| `reconcile.py` | Compares the ledger's per-symbol units with live SnapTrade positions. It reads the broker; it changes nothing. |
| `ledger.py` | Shows what is in the ledger: summary counts plus matching rows (default limit 200). `--summary` omits the rows. `--verify` adds a read-only health check. |
| `normalize.py` | Pure conversion of rows you already have. No ledger write. |

Every script prints JSON.

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Bad input | Show `error`. |
| 4 | Credentials missing | Show the `hint`. |
| 4 with code `ETRADE_REAUTH` | An E*Trade login is needed | Follow the E*Trade login steps below. |
| 5 | SnapTrade error or a corrupt ledger | Show the error. Code `LEDGER_CORRUPT` carries a `hint`; show it. |
| 6 | Python dependencies missing | Show the error, and say the setup skill repairs it. |

## Steps

Pick the case that matches the request. After any import, finish with the "After any import" steps.

**The user has a CSV file**

1. Ask for the path only if the user has not given one.
2. Run `import-csv.py <file> --dry-run`.
3. Show: the header line found, the detected `columns`, the `types` counts, the `date_range`, and the first few `skipped` reasons.
4. If a column was mis-detected, rerun the dry run with `--mapping`. Its keys are date, action, symbol, description, units, price, amount, fee.
5. Choose the `--account` value:

   | The file belongs to | `--account` |
   |---|---|
   | a connected account | the SnapTrade account id, so broker and CSV rows for the same trade deduplicate |
   | any other account | a short label of the user's choosing |

6. Run `import-csv.py <file> --account ID` without `--dry-run`. One `--account` per import: never mix two accounts' rows in a single import call.

**The user has a PDF or image statement**

1. Read the document yourself.
2. Transcribe each transaction into CSV rows with the columns Date, Action, Symbol, Description, Quantity, Price, Amount, Fees.
3. Save that CSV in the plugin data directory.
4. Say that the rows were transcribed, and show them before importing.
5. Import the CSV with the CSV steps above.

**The user wants broker history, or asks to refresh it**

1. Run `sync-broker.py` with no arguments. It pulls up to two years for every connected account.
2. Rerun it whenever the user asks to refresh.

**After any import**

1. Run `ledger.py --summary`.
2. Report counts, date range, types and accounts.
3. If there are rows typed OTHER, say they were kept but not understood. List a few and ask the user what they are if they matter.
4. Run `reconcile.py` and report it as in the share-count steps below.
5. When the ledger is ready, hand off to trade-review or dividend-income.

**Share counts look off**

1. Run `reconcile.py`.
2. Show the matched, quantity-mismatched, ledger-only and broker-only symbols, with the likely cause of each mismatch (missing rows, unrecorded splits, transfers, CSV gaps).
3. Ask before importing anything to fix them.

**An account changed how it connects**

This applies when an account was synced through SnapTrade and is now served directly (E*Trade with the user's own key). Its history is keyed by a different account id, so syncing both files the same trades twice.

1. Run `ledger.py --verify`.
2. Look at `duplicate_across_accounts`.
3. Fix it by re-importing from a clean ledger or from a CSV. Do not sync both ids.

**A script exits 4 with code `ETRADE_REAUTH`**

1. Follow the session's broker-login rule: show the `url` and get the verifier code from the user.
2. Run the connect skill's `etrade-login.py --verifier CODE`.
3. Rerun the script once.
4. If the user prefers to go on without E*Trade, rerun with `--partial` instead.

## Rules

- Do not analyze trades here. Hand off to trade-review or dividend-income.
- One `--account` per import call.
- Always run the dry run and show its result before a real CSV import.
- Show transcribed rows before importing them.
- `reconcile.py` and `ledger.py --verify` change nothing. Ask the user before importing anything to fix a mismatch.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
