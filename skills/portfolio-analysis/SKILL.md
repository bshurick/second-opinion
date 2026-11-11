---
name: portfolio-analysis
description: Gives the daily brief of all connected accounts and examines holdings, allocation, concentration, cash and returns, with a deep review of shared bets. Use when asked "how is my portfolio", "check in", for a brief, "how diversified am I" or a deep review.
---
Two parts over the connected accounts.

- **The daily brief** is one script run with one fixed layout and no analysis of its own.
- **The analysis** examines the holdings for diversification, concentration, cash and return. A deep review sends research subagents to find the beliefs the holdings share.

Orders belong to the trading skill. General market conditions and fair value belong to other skills.

## Background

### The daily brief

- **The brief.** `brief.py` is the default run. It runs `snapshot.py` with `--events` always on, then adds one-line headlines gathered live from the other installed Second Opinion skills.
- **Headlines.** Every headline is a fact one of those skills already reports. Each is ranked alert, notice or info, and marked new when it was not in the last brief. New headlines lead the list whatever their rank, so what changed since the last brief is always at the top.
- **Headline fields.** Each row of `headlines` is `{key, code, skill, severity, symbol, title, detail, as_of, status, ask, url, answer, why}`:

  | Field | Meaning |
  |---|---|
  | `severity` | `alert`, `notice` or `info` |
  | `status` | `new` or `still` |
  | `url` | an https link to the item's page |
  | `answer` | one sentence of fact, pre-computed from data the brief already fetched, or from one extra call for earnings (options expected move) and 10-Q/10-K filings (risk-factor diff) |
  | `why` | one plain-language sentence saying what the item is and why it matters |
  | `ask` | a follow-up question, shown only when there is no answer. It is the handoff question for the headline's skill. |

- **Coverage.** `coverage` has one row per source: `skill, script, status, reason, hint, seconds, headlines`, with `status` one of `ok`, `skipped` or `failed`. A skill that is not installed, not set up, slow or broken becomes a coverage row and never fails the brief.
- **Other brief fields.** `brief_as_of` and `brief_seconds`.
- **Timing.** A brief takes 30 to 60 seconds. A slow source is bounded by `--timeout` (default 90 s) per source.
- **Files in the plugin data directory.** `brief-last.json` remembers the last run's keys. `--save` appends a dated record to `snapshots.json`.
- **Snapshot fields.** `snapshot.py` prints `summary.py`'s contract plus `as_of`, `sources` and `news`. `summary.py` is the shared math; its input and output contracts are in its docstring.
- **Cash.** `totals.cash` is settled cash. `totals.cash_like` is cash plus money-market fund positions, each counted once.
- **Quotes.** Quotes are delayed, not live, unless `sources.quotes` is `etrade`. If `sources.quotes` is `snaptrade` (Yahoo unavailable or `--no-quotes`), the Day column shows "—" and the QUOTES_UNAVAILABLE flag explains why.
- **The page.** `render_brief.py` turns the saved result into one self-contained HTML page for the Artifact tool. The page carries the accounts, holdings, allocation, movers, events and comparison sections.
- **More detail.** Read `references/how-figures-are-built.md` before answering how cash, concentration, sector exposure or a headline's `answer` was computed, why a source is missing from the headlines, or what the page contains.
- **Other skills.** Drift against targets and what to rebalance belong to portfolio-plan, a single holding's outlook to trading or valuation, and every order to trading. Follow-up questions about the numbers are answered under "The analysis" below.

### The analysis

- **Where the data comes from.** Connected brokerage accounts, through SnapTrade or E*Trade direct. Every account row carries `broker` (`snaptrade` or `etrade`).
- **Account ids.** `accounts.py` lists them. Never ask the user for an account id.
- **Rate limit.** SnapTrade personal keys allow 10 calls/minute per account on holdings and balances. Call `accounts.py` once, fetch each account's portfolio once, and reuse the results. Never re-poll inside one answer.
- **Positions repeat across accounts.** `aggregate_report.py` merges them by symbol. Its `positions` array pipes straight into `allocation.py`. Do not aggregate by hand.
- **Quotes.** `quote.py` rows carry `source` and `realtime`: real-time from E*Trade when a direct session is live, otherwise delayed Yahoo. Say "real-time" only when `realtime` is true.
- **Stored targets.** The portfolio-plan skill saves the targets in settings.json (`plan.targets`). When saved targets exist, drift versus them is the default allocation view; its `plan.py status` reads them.
- **Research corpus.** `references/portfolio-research.md` holds the evidence behind portfolio-construction answers: quick-reference decision rules, key numbers, weighting schemes, covariance estimators, rebalancing, momentum versus contrarian, benchmarking, performance pitfalls, factor exposure, drawdown control, a glossary, and the fallback formulas for `allocation.py`.
- **Deep review.** It asks what single belief the person's financial life depends on most. `references/deep-review-roles.md` holds the brief for each research subagent.
  - For each link, `exposure.py` works out `exposed_value` (market value × `share`) and `loss_if_wrong` (`exposed_value` × `shock`). Each bet's `at_stake` adds one year of income at risk, and a net gain counts as nothing at stake.
  - Bets overlap, so their losses are never added together.
  - `history` shows whether a bet's holdings have moved together more than the portfolio has. `NOT_IN_PRICES` marks a bet that correlations would miss.
  - A share and a shock are stated assumptions with a source behind them, not forecasts.
  - It gives no buy, sell or hold call, no target weights and no fair value. Portfolio-plan and valuation own those.
- **Other skills.** General market conditions belong to market-analysis. Fair value belongs to valuation. Linking a brokerage belongs to connect. Chart and timing questions belong to trading.

### Account fields to trust

- **`supports_trading`** (boolean) is the authoritative signal for whether trades can be placed in that account. Do NOT guess from the broker name.
- **`account_type`** is `margin` or `cash`. Trust this field — it is DECLARED, not detected.
  - Order of precedence: a `BROKER_ACCOUNT_TYPES=<account_id>=margin` line in the plugin's `.env` wins, then what a direct broker adapter reports, and anything else defaults to `cash`.
  - Never infer it from the broker name, the account name, `raw_type`, or balances.
  - In particular do NOT conclude "margin" because buying power exceeds cash: a cash account holding unsettled sale proceeds reports exactly that, and that is precisely the state in which settlement violations occur.
- **`balance_total`** is the broker's own account total. Cash figures are reconciled against it.

### Cash is usually a money market fund

A brokerage "core" or "sweep" position is a fund (Fidelity `SPAXX`/`FDRXX`, E*Trade `MVRXX`, Vanguard `VMFXX`). It shows up in `portfolio.py` as a position priced at $1.00 and also in `balance.py`'s `cash`. Whether those are the same money differs by broker:

| Broker | What `cash` is | Account total equals | Illustrative figures |
|---|---|---|---|
| Fidelity | `cash` **is** the core fund | positions alone; adding `cash` double-counts it | positions $100,000 against a broker total of $100,030, while positions + cash gives $190,000 |
| E*Trade | the sweep and any money fund the user bought are **different** money | positions + cash; positions alone fall short by the sweep | $50,000 positions + $5,000 sweep = $55,000 against a broker total of $55,000 |

Treating a $90k core fund as cash on top of itself is the error this table exists to prevent.

**Money fund yield.** `quote.py SPAXX MVRXX` returns `seven_day_yield` for money market funds when the quote comes from E*Trade.

- It is a percentage already: `3.7745` means 3.7745%.
- It is `null` for equities, for non-money-market funds, and for any quote that fell back to Yahoo (Yahoo prices a money fund at its $1.00 NAV and carries no yield). A `null` means "not available from this source", not "no yield".
- Monthly income is `balance x seven_day_yield / 100 / 12`.
- A seven-day yield is an annualised rate that moves with the front end, not a locked coupon.

### Script output shapes

- **`portfolio.py` `symbol`** is sometimes a nested object, not a string. Read `p["symbol"]["symbol"]` when `p["symbol"]` is a dict.
- **`portfolio.py` `market_value`** comes back `0.00` from some brokers. Compute `units x price` when it does; do not report zero.
- **`performance_report.py`** computes the account's money-weighted return (annualized IRR by bisection) from `ledger.json`'s DEPOSIT/WITHDRAWAL entries and the live balance, and compares it with a benchmark over the same window. It needs at least two ledger flows. With fewer, `mwrr` is null and a `TOO_FEW_FLOWS` flag says so.
- **`allocation.py`** computes weights, `hhi`, `effective_n`, `top_5_concentration` and `drift`. Its input and output contract is in its docstring. Bands, applied to `hhi` rounded to 4 decimal places:

  | `hhi` | `effective_n` (1/`hhi`) | Label |
  |---|---|---|
  | < 0.10 | > 10 | diversified |
  | 0.10–0.18 (inclusive) | 5.6–10 | moderate |
  | > 0.18 | < 5.6 | concentrated |

## Scripts

The daily brief:

Run with the Bash tool. All four scripts print JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/brief.py" [snapshot.py flags...] [--no-headlines] [--timeout SECONDS] [--workers N]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/snapshot.py" [--account ID ...] [--events] [--no-quotes] [--no-news] [--save] [--compare] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/summary.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/render_brief.py" --in snapshot.json --out page.html [--summary summary.json]
```

| Script | What it does |
|---|---|
| `brief.py` | The default run. The snapshot plus `headlines`, `coverage`, `brief_as_of` and `brief_seconds`. Every `snapshot.py` flag passes through. |
| `snapshot.py` | The whole fetch in one go: accounts, positions, balances, prices, sectors, movers' news. |
| `summary.py` | Pure math on data you already have. |
| `render_brief.py` | Interactive page from a `snapshot.py` or `brief.py` result, with the headline analysis card when `--summary` is given. Prints `{"out", "title", "positions", "flags", "headlines"}`. |

| Flag | Effect |
|---|---|
| `--no-headlines` | The fast snapshot alone, with no headlines. Writes nothing to `brief-last.json`. |
| `--timeout SECONDS` | Limit per headline source. Default 90. |
| `--workers N` | How many headline sources run in parallel. |
| `--account ID` | Restrict to the named account or accounts. |
| `--events` | Next earnings and ex-dividend date per symbol. `brief.py` always turns it on. |
| `--no-quotes` | Skip the Yahoo fetches. Prices are the broker's last values. |
| `--no-news` | Skip the dated headlines for the day's movers. |
| `--save` | Append a dated record to `snapshots.json`. |
| `--compare` | Add a `comparison` block with the delta against the most recent earlier saved snapshot. |
| `--partial` | Run without E*Trade when its login is pending. |

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Unknown account id, or (`render_brief.py`) the input is not a snapshot result, or the summary file breaks a rule | Show `error`. |
| 4 | Credentials missing | Show the `hint`. |
| 4, code `ETRADE_REAUTH` | An E*Trade login is needed | Follow the session's broker-login rule: show the `url`, get the verifier code, run the connect skill's `etrade-login.py --verifier CODE`, rerun once. `--partial` runs without E*Trade. |
| 5 | SnapTrade or Yahoo error | Show the error. |
| 5, code `NO_ACCOUNTS` | Nothing is connected | Point to the connect skill. |
| 5, code `SNAPSHOTS_CORRUPT` | The saved-snapshots file is damaged | Show the `hint`. |
| 6 | Python dependencies missing | Show `requirements` / `install_log`. |

The analysis:

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/accounts.py" [--partial] [--include-closed] [--include-shadowed]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/portfolio.py" <account_id>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/balance.py" <account_id>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/quote.py" <symbol>...
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/performance_report.py" <account_id> [--benchmark SPY] [--since YYYY-MM-DD] [--as-of YYYY-MM-DD] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/aggregate_report.py" <account_id>... [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/allocation.py" <<< '<input json>'
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/exposure.py" < DIR/deep-review/bets.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/render_review.py" --in DIR/deep-review/page.json --out DIR/deep-review/page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/review_store.py" save --in DIR/deep-review/page.json [--source URL]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/review_store.py" check --book DIR/snapshot.json [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/review_store.py" list
```

| Script | What it does |
|---|---|
| `accounts.py` | Lists connected accounts with `account_id`, `supports_trading`, `account_type`, `balance_total` and `broker`. `shadowed` lists SnapTrade accounts hidden because a direct broker already serves them; `--include-shadowed` folds them back in. |
| `portfolio.py` | Positions for one account. |
| `balance.py` | `cash` and `buying_power` for one account. |
| `quote.py` | Quotes for one or more symbols, with `source`, `realtime` and, for money funds from E*Trade, `seven_day_yield`. |
| `performance_report.py` | Money-weighted return (`mwrr`) with `window` and `net_flows`, and the benchmark over the same window. |
| `aggregate_report.py` | Positions aggregated by symbol across the given accounts, ready for `allocation.py`. |
| `allocation.py` | Allocation, concentration and drift from a JSON object on stdin (`positions`, optional `cash`, optional `targets`). |
| `exposure.py` | Deep review math: dollars per bet, ranking, overlaps, uncovered holdings and flags. Its input and output contract is in its docstring. It rejects a link with no source or date. |
| `render_review.py` | Deep review page from `exposure.py` output, a headline of 25 words at most and a summary. |
| `review_store.py` | Keeps deep reviews between sessions. `check` re-measures the latest one against a later snapshot, with no new research. |

Every script prints JSON.

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Bad arguments or invalid input | Show `error`. |
| 4 | Credentials missing | Show the `hint` (credentials go in the plugin's `.env`). |
| 4 with code `ETRADE_REAUTH` | E*Trade needs today's authorization | Show the `url`, get the verifier code from the user, run the connect skill's `etrade-login.py --verifier CODE`, then rerun the command once. `--partial` on the listing scripts runs without E*Trade. |
| 5 | Broker or Yahoo error | Show the error. If it came from `accounts.py`, tell the user to run the connect skill. |
| 6 | Python dependencies missing | Show the error. |

## Steps

**"How is my portfolio", a summary or a daily brief**

1. Pick the flags for `brief.py`:

   | The request | Flags |
   |---|---|
   | A snapshot, summary or daily brief | none |
   | A quick or plain snapshot | `--no-headlines` |
   | The user names an account | `--account ID` |
   | "The snapshot" again with no data change since the last one (no new trades, deposits or accounts) | `--compare` |
   | The first run after a material change (a trade, a deposit, a new account) | `--save`, so later comparisons have a baseline |

2. Run `brief.py` once, with a Bash timeout of at least 300 seconds, writing the output to a file: `> DIR/snapshot.json`. DIR is the session scratchpad.
3. If the run exits non-zero, follow the exit code table and stop. A `coverage` row with status `failed` or `skipped` is not an error: it is information for the page and the reply's sources line, never a chat error and never a reason to rerun.
4. If the Artifact tool is available in the session, deliver the page:
   1. Write the headline analysis to `DIR/summary.json`, following the section below.
   2. Run `render_brief.py --in DIR/snapshot.json --out DIR/portfolio-snapshot.html --summary DIR/summary.json`.
   3. Publish the HTML with the Artifact tool: icon dashboard, description "Portfolio brief as of DATE".
   4. On later runs republish the same file path, so the link stays stable.
   5. Reply with the page reply format below.
5. If the Artifact tool is not available (a headless or non-interactive host), reply with the markdown fallback format below instead.
6. For a `--compare` run, present the delta against the saved snapshot instead of re-rendering every section.
7. Offer the handoff. For each shown headline whose `ask` is non-empty, offer the `ask` verbatim. For anything else beyond the fixed layout, finish the brief first, then answer under "The analysis" below or hand off to the skill named in Background.

### **"Check in"**

"Check in", "catch me up" or "anything I should know" runs one sequence and gives one reply, one section per step:

1. If a script exits 4 with `ETRADE_REAUTH`, do the E*Trade login first, under the session's broker-login rule.
2. **Brief.** Run `brief.py --no-headlines > DIR/snapshot.json` and give the totals, the day's move and new flags in three lines or fewer. This run also records arrivals.
3. **Plan.** Run the portfolio-plan skill's `plan.py status` and give the mix against the picks target, and drift against saved targets when there are any.
4. **Since last time.** Run the get-started skill's `inbox.py`. It lists the cash and vested shares that arrived since an earlier read (the last-read record's `arrivals`), the picks due for a re-check and new watchlist alerts. Give each line with the sentence that handles it. Nothing printed means nothing new; say so in one line.
5. End with the handling sentences as the offer. Run none of them until the person picks one.

"Show my watchlist" belongs to the watchlist skill, not this one.

### The headline analysis

A small card at the top of the page: a headline, "What stands out", "What to look into", and a folded "What this means for you". The file is `{"headline", "stands_out", "look_into", "for_you"}`.

- Limits, which `render_brief.py` enforces: `headline` 20 words, `stands_out` 90, `look_into` 90, `for_you` 70. `for_you` is optional and the rest are required.
- Links take the form `[Sectors](sec-card)`, in `look_into` only, to these ids: `headlines-card`, `accounts-card`, `alloc-card`, `sector-card`, `movers-card`, `holdings-card`, `events-card`, `compare-card`, `flags-section`.
- Every number comes from this run's script output, quoted as the script gives it.
- Lead with what is unusual today, not a tour of the page. Say plainly when nothing stands out.
- Separate data from inference, using words like "may" for inference.
- Carry dates when a reading is older than the page's prices.
- Name the bull and the bear side when reading a market condition or a security.
- No buy, sell or hold call, and no forecast. `for_you` says how a reading touches the person's holdings, not what to do. The forbidden verbs are rejected in every field.
- `for_you` takes portfolio numbers only from a read taken on this run or today, never from memory. Non-numeric context from memory or the profile is allowed, such as a paycheck and stock awards both depending on one employer.
- A file that breaks a rule exits 2 with `error` naming the rule and writes no page. Rewrite the file and render again.

Write each field so a reader follows it on the first read:

- Each sentence makes one point, and the sentence after it starts a new one.
- A comparison and its likely cause share a sentence: what happened, then "likely because" and the reason.
- A caveat about a figure comes after the point it qualifies, in its own sentence: which figure, what is wrong with it, and why.
- Name a group by what it is to the reader: "your 401(k) funds", "cash and bonds".
- Write an estimated day change as "The 0.3% is partly an estimate, because your 401(k) funds have no public quote." The Flags section carries the share estimated.
- Write a flag as the plain fact: "Cash and money-market funds are 48.8%, above the 20% line the page flags."

Before: "The day's move was -$1,808.75 (-0.3%), against S&P 500 -1.8%; 25.55% of market value uses an estimated day change. Cash and money-market funds at 48.8% and bonds at 25.4% may explain the gap."

After: "You fell 0.3% while the S&P 500 fell 1.8%, likely because about 74% of the portfolio is in cash and bonds. The 0.3% is partly an estimate, because your 401(k) funds have no public quote."

What to look for on this page:

- The day's move against the S&P 500, and whether it is partly estimated (`DAY_CHANGE_ESTIMATED`).
- Concentration and flags that changed, cash share, and new alerts in `headlines`.
- Events in the next few days.

Start every request with step 0, then pick the case that matches.

0. Run `accounts.py` once. If it returns no accounts, tell the user to run the connect skill.

**The user asks about holdings, diversification or risk**

1. Run `portfolio.py` once for each account in scope. Run `balance.py` for cash and buying power, and use them in the analysis.
2. If more than one account is in scope, run `aggregate_report.py <account_id>...` to merge positions by symbol.
3. Assess diversification across sectors and asset classes.
4. Evaluate risk exposure relative to the user's goals and tolerance.
5. Identify concentration risks, underperforming positions, or rebalancing opportunities.
6. If the question touches a research topic (see the research case below), read the reference before answering.

**The user asks about allocation, concentration or drift**

1. If the saved targets in settings.json exist, run the portfolio-plan skill's `plan.py status` and lead with its drift and breach output (`global.allocation`). Ask the user for targets only when none are saved.
2. Otherwise run `aggregate_report.py <account_id>...`, then pipe its `positions` into `allocation.py`.
3. Present the script's numbers. Do not recompute them by hand.
4. If `allocation.py` cannot be run, use the formulas in the "Concentration and Drift Formulas" section of `references/portfolio-research.md` and say so.

**The user asks how an account has performed**

1. Run `performance_report.py <account_id>`. Add `--benchmark` or `--since` when the user names one.
2. Present `mwrr` with `window` and `net_flows`.
3. Disclose that positions are valued at delayed Yahoo prices (broker prices when Yahoo is unavailable).
4. If `mwrr` is null with a `TOO_FEW_FLOWS` flag, say the data does not support a money-weighted return. Do not present a different metric in its place.

**The user asks how much cash they have, or what it yields**

1. Run `balance.py` and `portfolio.py` for the account.
2. Find the core or sweep fund among the positions.
3. Reconcile against the account's `balance_total` from `accounts.py` using the broker table in Background before reporting a cash figure.
4. Say which convention you applied (Fidelity or E*Trade).
5. For yield, run `quote.py` on the fund symbol and report `seven_day_yield`. If it is `null`, say the yield is not available from this source.

**The question needs research evidence**

Topics: the evidence behind a rule, weighting schemes, covariance or shrinkage choices, rebalancing cadence and turnover, momentum or contrarian strategy evidence, benchmark selection, evaluating a manager or fund's track record, short-selling constraints, factor tilts, competition or herding effects, portfolio size or number of holdings.

1. Read `references/portfolio-research.md` with the Read tool. This is required, even if you recognise the underlying papers.
2. Start from its "Quick-Reference Decision Rules" and "Key Numbers" sections, then the section for the topic.
3. Ground the answer in what the file says. Do not answer these from memory.
4. Present it in plain language ("research shows…"). Never cite internal reference codes, tags or source identifiers to the user.

**The user asks for a deep review, or what they really depend on**

Run this when the person asks for a deep review or for depth, or when the session's depth rule makes the deep review the default. Otherwise answer from the holdings case; in standard depth, end with one line: a deep review is available and sends about eight research subagents.

1. If the risk-analysis skill is not installed, say the deep review needs it, and stop.
2. Tell the person it has started: about 8 subagents and 40 web searches. If they have not mentioned income, ask once whether to include a paycheck or other income. Without an answer, cover holdings alone and say so. Income comes only from what they say in this session.
3. Make `DIR/deep-review/` and its `baseline/`, `research/` and `threads/` folders, where DIR is the session scratchpad.
   - Write `snapshot.py --no-news` to `baseline/snapshot.json` and `stress.py --full-correlation` to `baseline/stress.json`. If either exits non-zero, follow its skill's exit codes and stop.
   - Write `income.json` when income was given: `[{"id", "name", "annual"}]`.
   - Write `budget.json`: the searches this run may spend, each role's cap and the searches used so far. The session has one shared pool of about 200.
   - Run the stock-screener skill's `picks.py list` when it is installed. Note any held symbol with a saved deep valuation for Company links.
4. Dispatch Company links, Fund look-through and Macro sensitivity in parallel, with Income and employer when income was given. Use the Agent tool, general-purpose type.
   - Each prompt names the Shared rules section and the role's section of `references/deep-review-roles.md` by absolute path, plus the case folder, today's date and the role's search cap.
   - Subagents do not inherit `SNAPTRADE_PY` or `CLAUDE_PLUGIN_ROOT`. Resolve both to absolute paths in the prompt.
   - No figure about the person goes in a prompt beyond the file paths. They read the baseline themselves.
   - If a role fails or returns nothing, retry it once, then add it to `missing_roles` and go on.
5. Merge the candidate bets into `bets.json`, the `exposure.py` input. Combine bets that are one belief, keep at most eight, and leave out any claim with no source and date. Add `as_of`, `book`, `risk` and `income` from the baseline. Run `exposure.py`, and fix what it rejects by going back to the source, not by inventing a date.
6. Pick up to three bets, the largest `at_stake` and the most contested. Dispatch one Thread deep-dive per bet, in parallel, then apply each verdict and correction to `bets.json`.
7. Dispatch the Red team with `bets.json`. Apply its changes where its sources hold up, and keep each rejected change in `notes` with the reason.
8. Run `exposure.py` again and write its output to `exposure.json`. Write `page.json`: `as_of`, `headline`, `summary`, `exposure`, `missing_roles`, `notes`.
   - The headline names the largest belief and the share of the portfolio resting on it, in 25 words or fewer. The summary says in two or three sentences what would make it wrong and what the holdings have in common.
9. Run `render_review.py`. Publish the page with the Artifact tool: icon chart, description "Portfolio deep review as of DATE". If the Artifact tool is unavailable, use the markdown fallback.
10. Run `review_store.py save --in DIR/deep-review/page.json --source <page link>`.

**The user asks to re-check a deep review**

1. Write `snapshot.py --no-news` to `DIR/snapshot.json`, then run `review_store.py check --book DIR/snapshot.json`. Exit 2 with "no saved review" means none has been run: offer one.
2. Present each bet's then and now figures, `gone`, `watch_due` and `new_uncovered`.
3. Say that this re-measures dollars only. The shares, shocks and verdicts are the review's own, and no new research ran.
4. If `rerun_due` is true, give `rerun_reasons` and say a new deep review would refresh the evidence.

**The user wants to place, cancel or see orders**

Orders belong to the trading skill: its protocol, its scripts and its confirmation block. Hand off to it with the account and the order the person named.

**The user wants to link a brokerage**

Hand off to the connect skill.

## Reply format

**The daily brief**

### Page reply (the default, when the page was published)

In this order, then stop:

1. The artifact link on its own line.
2. The summary's `headline`, on one line.
3. One line: Total `totals.total_value` · Cash and money-market funds `totals.cash_like` (`totals.cash_like_pct`) · Day `totals.day_change` (`totals.day_change_pct`, covers `totals.day_change_coverage` of holdings) · Unrealized `totals.unrealized_pnl`
4. Headlines, only when `headlines` is present:
   - The line "Headlines (N new):", where N is the count of `status == "new"`. Write "Headlines: none today" when the list is empty.
   - At most five bullets, in the script's order.
   - Each bullet reads "SEVERITY title — answer". The prefix is the severity in caps for alerts, `NEW` for new notices, and nothing for the rest. Then the `title`. Then " — " and the `answer`, when it is non-empty.
5. One line "Sources: X of Y checked, Z skipped" from `coverage`, only when any source was skipped or failed. Do not list skipped or failed sources by name in chat; the page's coverage table has them.
6. **Flags** — one bullet per `flags[].message`, or "None".

The session's standing "Next you could ask:" block draws its questions first from the shown headlines whose `ask` is non-empty.

Do not repeat the sections the page carries. If the user asks for a number the page shows, read it from the script's JSON.

### Markdown fallback (only when the Artifact tool is unavailable)

Open with the whole headline analysis as text: the headline, "What stands out", "What to look into" without its links, and "What this means for you" when written. `render_brief.py` does not run here, so nothing enforces the limits and rules in the headline analysis section. Keep to them.

Then render the script's JSON in exactly this order, then stop.

**Portfolio snapshot** — as of `as_of` (or the current time when `as_of` is missing)

One line: Total `totals.total_value` · Cash and money-market funds `totals.cash_like` (`totals.cash_like_pct`) · Day `totals.day_change` (`totals.day_change_pct`, covers `totals.day_change_coverage` of holdings) · Unrealized `totals.unrealized_pnl` (`totals.unrealized_pnl_pct`)

- If `sources.quotes` is `etrade`, label the Day column real-time.
- If `sources.quotes` is `mixed`, say which symbols are delayed only if asked.

Sections, numbered as shown:

0. **Headlines** — only when `headlines` is present.
   - One bullet per headline in the script's order: `severity` in caps, "NEW" when `status` is new, the `title`, then " — " and the `answer` when it is non-empty. When there is no `answer`, the `detail` in parentheses when present.
   - "none today" when the list is empty.
   - Then "Sources: X of Y checked, Z skipped, W failed" from `coverage`.
1. **Accounts** — table from `accounts`, in input order: Account · Institution · Type · Trading · Value · Cash · Weight.
2. **Top holdings** — table from `top_holdings`: Symbol · Name · Units · Price · Total · Weight · Unrealized P&L · Day % · 1w % · 1m %.
   - The 1w and 1m columns appear only when the run included them; "—" otherwise.
   - If `positions` is longer than `top_holdings`, add one line: "N more positions not shown."
3. **Allocation** — these parts, in order:
   - One line: positions HHI `concentration.hhi` (`concentration.hhi_interpretation`), top-5 `concentration.top_5_concentration`, `concentration.position_count` positions, largest `concentration.largest_position` (symbol, weight, asset class).
   - When `concentration.single_stock` is present, add: "single stocks `weight` of value in `count` names, HHI `hhi` (`hhi_interpretation`), largest `largest.symbol` `largest.weight`".
   - When `allocation` is present: a Bucket · Weight · Value · Holdings table from `allocation.buckets`, in the order US equities, international equities, bonds, cash, other. Name `allocation.unclassified` as counted in other.
   - When `sector_exposure` is present: a Sector · Weight · Direct · Via funds table from `sector_exposure.sectors`, sorted by weight.
   - Then one line: "`not_sectorized.bonds_and_cash` bonds and cash and `not_sectorized.funds_without_data` in no sector data or partial fund data (institutional share classes, commodities, unknown quote types), not sectorized". Add ", no data for `missing_data`" when `missing_data` is non-empty.
   - When `sector_exposure` is absent (an older snapshot): the `sector_weights` rows other than ETF and Unknown as a Sector · Weight table. Funds are not looked through.
   - Only when `allocation` is absent: the Asset class · Weight · Value table from `asset_classes`.
4. **Movers** — "Up:" and "Down:" lines listing symbol (day %, day $) from `movers`. Write "no quote data" when both are empty.
   - Under each mover that has `news[symbol]` entries, one line per story: `published` date, `publisher`, `title` (linked to `url`).
   - When `news` is present but the mover's list is empty, write "no dated story in the last 7 days".
5. **Upcoming events** — only when `events` is not null: table Date · Symbol · Type.
6. **Change since last snapshot** — only when `comparison` exists.
   - One line: "Since `comparison.since` (`comparison.days` days ago): Total `comparison.total_value.before` → `comparison.total_value.after` (`comparison.total_value.delta`, `comparison.total_value.delta_pct`)".
   - Then the first few `comparison.symbols` as a Symbol · Before · After · Change table ($ and %).
   - Add "N more symbols not shown" when `comparison.n_more` > 0.
   - When `comparison` is null and a NO_SNAPSHOT flag is present, write "no saved snapshot to compare against yet — run with --save to store one."
7. **Flags** — one bullet per `flags[].message`, or "None".

The only text after the Flags section is the session's standing "Next you could ask:" follow-ups block.

### Number formats

| Value | Format |
|---|---|
| Money | 2 dp with thousands separators |
| Ratios (`*_pct`, `weight`, coverage) | percentages to 1 dp |
| HHI (`hhi`) | a 4 dp ratio, not a percentage |
| null | "—" |

**The analysis**

No fixed template. For every analysis reply:

- Reference specific positions, values and gains from the script output so the analysis is concrete.
- Explain the reasoning behind each observation.
- Relate the findings to the user's risk tolerance and investment goals.
- Keep it concise.
- Answer the question fully yourself.

**Deep review, page published:** these parts, then stop.

1. The artifact link on its own line.
2. The headline.
3. The largest bet: its belief, `exposed_value`, `loss_if_wrong`, any `income_at_risk`, its verdict, and the strongest evidence on each side with source and date.
4. **Flags**: one bullet per `exposure.flags[].message` and per missing role, or "None".
5. One line: subagents dispatched and searches used.
6. One line: shares and shocks are stated assumptions, general information, not financial, tax, or legal advice.

**Deep review, markdown fallback:** the same parts without the link, plus each bet with its holdings and evidence on both sides, the overlaps and the unmapped holdings.

## Rules

- Every number and every headline comes from the script. Do not recompute or add figures.
- Never run `brief.py` or `snapshot.py` twice in one answer. The one rerun after an E*Trade login is the only exception.
- Do not run accounts.py, portfolio.py, or quote.py as well. The snapshot already contains that data.
- Publish the page or write the markdown fallback, never both.
- No commentary, bull/bear framing, or opinions outside the Flags section and the headline analysis card.
- Quotes are delayed, not live. Say so plainly if the user asks for "live" prices.
- A news story under a mover is dated context for the move, never stated as its cause.
- If the user asks a follow-up question about the numbers, switch to the portfolio-analysis skill.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
- Present the scripts' numbers. Do not recompute by hand what a script already computed.
- Do not ask the user for their account id. Look it up with `accounts.py`.
- Never re-poll an account's holdings or balances inside one answer.
- In a deep review, every dollar figure comes from `exposure.py`. A holding's value, income, an account name or a person's identifier never goes in a search, URL or fetch.
- A deep review describes what the holdings depend on. It never says what to do about it.
- Reconcile cash against `balance_total` before reporting it, and never add a core fund to itself.

<research_dating>
Every news item, analyst action, data release, or calendar entry you present carries the publication date printed on the source page, the source, and what it says. Search-result snippets blend years; the dateline on the article is the date.
1. Fix the window first: today's date, then the period the question covers ("this week" is the five trading days ending today; a price move is the sessions in which it happened).
2. Read the dateline of each candidate before using it. A hit that matches the month and day but not the year is a different year's event: leave it out, or label it "background (DATE)".
3. A cause offered for a price move is dated inside the move window. When no dated item falls inside the window, write "no dated catalyst found for WINDOW" and describe the move from price and volume alone.
4. Calendar dates (CPI, FOMC, central-bank decisions, earnings, ex-dividend) are for the current year, confirmed against a script's `as_of` field or a dated source before being presented as upcoming.
5. Items appear newest first with the date inline, e.g. "(Sep 8, 2026, Reuters)".
</research_dating>

