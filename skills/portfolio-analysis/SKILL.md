---
name: portfolio-analysis
description: Examines the user's own holdings, allocation, concentration, cash and returns on connected accounts, and places orders. Use when the user asks "how diversified am I", "what's my allocation" or wants to buy or sell. Plain holdings list is portfolio-snapshot.
---
Examines the user's brokerage holdings for diversification, concentration, cash and return, and places or cancels orders through the trading skill's order scripts. It does not cover general market conditions, fair value, or a plain summary of everything held.

## Background

- **Where the data comes from.** Connected brokerage accounts, through SnapTrade or E*Trade direct. Every account row carries `broker` (`snaptrade` or `etrade`).
- **Account ids.** `accounts.py` lists them. Never ask the user for an account id.
- **Rate limit.** SnapTrade personal keys allow 10 calls/minute per account on holdings and balances. Call `accounts.py` once, fetch each account's portfolio once, and reuse the results. Never re-poll inside one answer.
- **Positions repeat across accounts.** `aggregate_report.py` merges them by symbol. Its `positions` array pipes straight into `allocation.py`. Do not aggregate by hand.
- **Quotes.** `quote.py` rows carry `source` and `realtime`: real-time from E*Trade when a direct session is live, otherwise delayed Yahoo. Say "real-time" only when `realtime` is true.
- **Stored targets.** The rebalancing skill's `plan.py --target KEY=WEIGHT ... --save` writes `targets.json` in the plugin data directory. When that file exists, drift versus the saved targets is the default allocation view. `plan.py` picks up `targets.json` automatically.
- **Research corpus.** `references/portfolio-research.md` holds the evidence behind portfolio-construction answers: quick-reference decision rules, key numbers, weighting schemes, covariance estimators, rebalancing, momentum versus contrarian, benchmarking, performance pitfalls, factor exposure, drawdown control, a glossary, and the fallback formulas for `allocation.py`.
- **Other skills.** General market conditions belong to market-analysis. Fair value belongs to valuation. A plain summary of everything held belongs to portfolio-snapshot. Linking a brokerage belongs to connect. Chart and timing questions belong to trading.

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

### Settlement rules (cash accounts)

Settlement rules — check `account_type` before sequencing any multi-leg trade.

- **`margin`** — no settlement constraint.
- **`cash`** — the settled-funds discipline applies. A purchase must be paid for in full by settlement. Stock settles **T+1** (one business day after the trade).
- Buying with the proceeds of a sale that has not yet settled is allowed — the restriction falls on what happens to the new position afterwards.
- The rules come from the Federal Reserve's Regulation T (12 CFR 220.8, the cash account). "Good faith violation" and "cash liquidation violation" are the names brokers give, in their own account policies, to the ways those rules get broken, so the exact penalties are each broker's and can differ.

The three violations:

- **Freeriding** — buying a security and then paying for it with proceeds from selling that same security. Reg T itself requires the broker to restrict the account for 90 days (purchases need settled cash up front) after a single occurrence. This is the one to never allow.
- **Good faith violation** — buying with unsettled sale proceeds is fine; the violation happens only if the newly bought position is sold before the funds used to buy it have settled. Most brokers restrict the account to settled cash for 90 days after three or four in 12 months.
- **Cash liquidation violation** — buying without enough cash to cover the purchase, then selling something else *after* the purchase date to raise it. Brokers typically restrict the account after three in 12 months.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/accounts.py" [--partial] [--include-closed] [--include-shadowed]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/portfolio.py" <account_id>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/balance.py" <account_id>
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/quote.py" <symbol>...
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/performance_report.py" <account_id> [--benchmark SPY] [--since YYYY-MM-DD] [--as-of YYYY-MM-DD] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/aggregate_report.py" <account_id>... [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/allocation.py" <<< '<input json>'
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

Orders and history use the trading skill's scripts: `gate.py`, `preview-order.py`, `place-order.py`, `cancel-order.py`, `orders.py`, `transactions.py`. Their commands are in the trading skill.

Every script prints JSON.

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Bad arguments or invalid input | Show `error`. |
| 3 | `place-order.py` or `cancel-order.py` ran without `--confirm` | That is the gate. Show the output and stop. |
| 4 | Credentials missing | Show the `hint` (credentials go in the plugin's `.env`). |
| 4 with code `ETRADE_REAUTH` | E*Trade needs today's authorization | Show the `url`, get the verifier code from the user, run the connect skill's `etrade-login.py --verifier CODE`, then rerun the command once. `--partial` on the listing scripts runs without E*Trade. |
| 5 | Broker or Yahoo error | Show the error. If it came from `accounts.py`, tell the user to run the connect skill. |
| 6 | Python dependencies missing | Show the error. |

## Steps

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

1. If `targets.json` exists, run the rebalancing skill's `plan.py` and lead with its drift and breach output. Ask the user for targets only when the file is absent.
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

**The user wants to place an order**

Before the protocol:

1. Pick the account. If exactly one account has `supports_trading` true, use it without asking. Ask the user to pick only when several accounts can trade.
2. If the user names an account where `supports_trading` is false, explain that the connection is read-only and list the accounts that can accept trades. Stop.
3. If `account_type` says `cash` and the user says the account is margin, point them to the `BROKER_ACCOUNT_TYPES` line (the connect skill documents it). Do not proceed on their word.
4. For a dollar-amount request ("buy $500 of AAPL"), run `quote.py <symbol>` for the price (web search if `quote.py` is unavailable) and work out the quantity:

   | Account `broker` | Quantity |
   |---|---|
   | `etrade` (connected directly) | dollar_amount / price rounded down to 3 decimals, within E*Trade's fractional rules in the trading skill; or floor(dollar_amount / price) |
   | `snaptrade` | floor(dollar_amount / price). Whole shares only. |

5. If the request has more than one leg, apply the cash-account case below first.

Then the protocol.

NEVER place an order without, in this exact order:
1. Only when the trade-journal skill is installed (it is an optional extra): running the trading skill's `gate.py <symbol> <BUY|SELL> <qty> [--limit X]` and showing its `decision` and `reasons`. A SKIP decision (the journal is not installed) is not shown. The gate never blocks and never replaces the steps below.
   - On NO_GO or REVIEW, state the reason in one sentence and ask whether to proceed anyway or journal the plan first (trade-journal skill); the user's answer in their own message decides.
2. Running the trading skill's `preview-order.py <account_id> <symbol> <BUY|SELL> <qty> [--type ... --limit ... --stop ... --term ...]`.
3. Showing the preview output (trade id, price, units, estimated cost, estimated commission, remaining cash, and any warnings) to the user.
4. Receiving explicit confirmation of that specific order in the user's own message.
5. Only then running `place-order.py` with the exact same arguments plus `--confirm`. Without `--confirm` the script prints the preview and exits 3 — that is the gate, not a bug to work around. `place-order.py` re-runs the preview itself before placing, so the trade id you saw may differ; that is expected.

If the preview carries `flags` with `UNSETTLED_CASH`, say so before asking for confirmation.

**The order has several legs, or settlement affects the answer**

1. Read the account's `account_type`. State which account type you are applying whenever settlement affects the answer, so a stale declaration is visible rather than silent.
2. If it is `margin`, sequence trades normally and say nothing more about settlement.
3. If it is `cash`, apply these four rules:
   1. Buying with proceeds from a sale made the same day or earlier is fine. The new position then must not be sold until the sale proceeds that paid for it settle (T+1 after that sale) — say this when the user may want to trade out quickly. If they want to keep that freedom, sell first and let the proceeds settle (T+1) before buying.
   2. Do not place a buy that only a *later* sale would pay for — sell first, then buy.
   3. Never fund a purchase by selling the security you just bought.
   4. Buying power reported by the broker may include unsettled proceeds. Do not treat it as settled cash; the balance script's `cash` figure is the number to check, and a preview carrying the `UNSETTLED_CASH` flag is the broker saying the same thing.
4. If a requested sequence would risk a violation, say so plainly, name which violation and its consequence, and offer the compliant alternative. Do not refuse the trade — the user may have context you lack, and a margin account may simply be undeclared.
5. Run the order protocol once per leg, each with its own confirmation.

**The user wants to cancel an order, or see orders and history**

1. Run the trading skill's `orders.py <account_id>` for open orders, or `transactions.py <account_id>` for history.
2. Cancelling requires the exact order id (`order_id` on each `orders.py` row) and the user's confirmation before running `cancel-order.py <account_id> <order_id> --confirm`.

**The user wants to link a brokerage**

Hand off to the connect skill.

## Reply format

No fixed template. For every analysis reply:

- Reference specific positions, values and gains from the script output so the analysis is concrete.
- Explain the reasoning behind each observation.
- Relate the findings to the user's risk tolerance and investment goals.
- Keep it concise.
- Answer the question fully yourself.

For an order preview, show: trade id, price, units, estimated cost, estimated commission, remaining cash, and any warnings.

## Rules

- Present the scripts' numbers. Do not recompute by hand what a script already computed.
- Do not ask the user for their account id. Look it up with `accounts.py`.
- Never re-poll an account's holdings or balances inside one answer.
- Reconcile cash against `balance_total` before reporting it, and never add a core fund to itself.

Safety rules:
1. Never run a script with `--confirm` until the preview output has been shown in the chat and the user has explicitly said yes in their own message.
2. One order per confirmation. Never chain a sell into a buy on a single yes.
3. Check the account's `supports_trading` flag from `accounts.py` before previewing.
4. If the account is cash or unknown, warn when the order size exceeds the balance script's `cash` figure, and never infer margin from buying power.
5. Do not place an order when `place-order.py` returned exit 3, 4, 5, or 6. Show the error and stop.

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
