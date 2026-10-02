---
name: rebalancing
description: Builds a rebalancing plan against targets, with drift, 5/25 band breaches, a trade list, tax-aware sell routing and contribution routing. Use when the user says "rebalance", "am I off target" or "where does this deposit go". Orders go to portfolio-analysis.
---
Turns target weights plus current holdings into a rebalancing plan. The script decides the trades mechanically; the reply presents them, their tax cost, and where each order would be placed. This skill never places orders.

## Background

**What the script does**

- **Fetch.** `plan.py` fetches accounts, positions and balances (one call each per account) and one batched Yahoo quote, then runs `rebalance.py`.
- **Method.** Universe, bands, full vs contribution mode, pro-rata class trades, whole shares, lot picking, routing. The detail is in `rebalance.py`'s docstring.
- **Targets.** Targets persist in `targets.json` under the plugin data directory when `--save` is used. Weights must sum to 100% (decimals summing to 1 on the command line). A key is a symbol, a class name, or `CASH` for a cash reserve.
- **Cross-account.** Targets are measured over all selected accounts together. The trade table shows the account each trade would land in, so orders route correctly and tax-advantaged accounts absorb the sells first.

**Bands and when to rebalance**

- The 5/25 rule (Swedroe) triggers when an allocation is 5 percentage points off, or 25% of its own target off, whichever comes first. These are the default `bands.absolute` and `bands.relative`.
- Calendar rebalancing (annual or semi-annual) is the simpler alternative.
- Evidence favours rebalancing for risk control, not for return.
- Drift between scheduled checks is normal: allocations wander as markets move, and the bands exist to catch it. The plan is for a breach, or for the calendar the user picked, not for every price move, unless the user asks.
- Cash-flow rebalancing (routing contributions to underweights, taking withdrawals from overweights) avoids realized gains and is the first tool in taxable accounts.

**Account classification and routing**

- Accounts are classified taxable vs tax-advantaged from their type. This is a guess, echoed in `routing.accounts`. `--taxable` and `--tax-advantaged` correct it.
- Sells are filled from tax-advantaged accounts first. Routing is skipped entirely when every account is taxable.
- Asset location: holding the same target mix, it is generally more tax-efficient to sell from tax-advantaged accounts first and, when both are possible, to place buys in taxable accounts first (they keep the growth and the loss-harvesting option). Present this as guidance only; the user decides what to hold where.

**Tax estimate**

- The estimate uses the highest-cost lots first.
- When `ledger.json` holds BUY/SELL history for a symbol, lots are replayed FIFO per (symbol, account) and carry real long/short terms from their holding periods.
- Symbols whose replayed units do not match the broker keep SnapTrade's average price. `lot_sources` and `sources.lots` say which source each symbol used.
- Without ledger lots the term is unknown and the short-term rate is applied (conservative).
- A sale in a tax-advantaged account contributes gain but no tax.
- `--short-term` and `--long-term` override the tax rates behind `est_tax`. Defaults 24% and 15%.

**Whole shares**

Every SnapTrade-connected account takes whole shares only. A directly connected E*Trade account takes fractions.

**The page**

`render.py` turns a saved `plan.py` result into one self-contained HTML page for the Artifact tool. The page carries the allocation, drift, trade, routing, post-trade and suggested-bands sections:

- stat tiles for total value, max drift, trades, turnover, estimated tax and cash after
- drift-vs-target bars centred on zero, with the band edges marked and breaches coloured
- a sortable allocation table
- the trade list as a sortable table with account, reason, estimated gain and tax, and the lots on hover
- contribution or withdrawal routing when the plan moves cash
- post-trade weights; tax-aware vs pro-rata routing; suggested bands when present
- flags; the "a plan, not orders" note; light and dark themes; no external scripts

**Other skills**

- Exact lots and wash-sale checks belong to the tax-aware skill.
- Placing an order belongs to the portfolio-analysis trading protocol.

## Scripts

Run with the Bash tool. All three scripts print JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/rebalancing/scripts/plan.py" [--target KEY=WEIGHT ...] [--class SYMBOL=KEY ...] [--targets FILE] [--save] [--account ID ...] [--contribute AMOUNT] [--withdraw AMOUNT] [--no-sells] [--whole-shares] [--min-trade N] [--band-abs R] [--band-rel R] [--short-term R] [--long-term R] [--taxable ID ...] [--tax-advantaged ID ...] [--suggest-bands] [--only-if-breached] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/rebalancing/scripts/rebalance.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/rebalancing/scripts/render.py" --in plan.json --out page.html
```

| Script | What it does |
|---|---|
| `plan.py` | Fetches holdings and prices, then runs `rebalance.py`. |
| `rebalance.py` | Pure math on holdings you already have. |
| `render.py` | Interactive page from a `plan.py` result. Prints `{"out", "title", "trades", "breaches", "flags"}`. |

| Flag | Effect |
|---|---|
| `--target KEY=WEIGHT` | An inline target. KEY is a symbol, a class name, or `CASH`. |
| `--class SYMBOL=KEY` | Puts a symbol in a class named by a target key. |
| `--targets FILE` | Read targets from FILE instead of the saved `targets.json`. |
| `--save` | Keep the inline targets in `targets.json`. |
| `--account ID` | Restrict to the named account or accounts. |
| `--contribute AMOUNT` | Route a deposit. |
| `--withdraw AMOUNT` | Raise cash. |
| `--no-sells` | Buys only. |
| `--whole-shares` | Round trades to whole shares. |
| `--min-trade N` | Skip trades under N dollars. |
| `--band-abs R`, `--band-rel R` | Band widths as decimals. Defaults 0.05 and 0.25. |
| `--short-term R`, `--long-term R` | Tax rates behind `est_tax`. Defaults 0.24 and 0.15. |
| `--taxable ID`, `--tax-advantaged ID` | Correct the account classification. |
| `--suggest-bands` | Adds `suggested_bands`: per-key band widths from a year of volatility. |
| `--only-if-breached` | No trades unless a band is breached. |
| `--partial` | Run without E*Trade when its login is pending. |

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | No targets, weights not summing to 1, or unknown account; or (`render.py`) the input is not a plan result | Show `error`. |
| 4 | Credentials missing | Show the `hint`. |
| 4, code `ETRADE_REAUTH` | An E*Trade login is needed | Follow the session's broker-login rule: show the `url`, get the verifier code, run the connect skill's `etrade-login.py --verifier CODE`, rerun once. `--partial` runs without E*Trade. |
| 5 | SnapTrade error | Show the error. |
| 6 | Python dependencies missing | Show the error. |

## Steps

1. Settle the targets:

   | The situation | What to pass |
   |---|---|
   | A saved file exists and the user gives no new targets | nothing; the saved file is used |
   | The user states targets by symbol | `--target SYMBOL=WEIGHT` for each |
   | The user states targets by class | `--target CLASS=WEIGHT` for each, plus `--class SYMBOL=KEY` for each member |
   | The user says to keep the targets | add `--save` |
   | The user wants a cash reserve | include `--target CASH=WEIGHT` |

2. Pick the flags for the request:

   | The request | Flags |
   |---|---|
   | "Rebalance", "am I off target" | none |
   | "Where does this deposit go" | `--contribute AMOUNT --no-sells` |
   | Raising cash | `--withdraw AMOUNT` |
   | A periodic check | `--only-if-breached` |
   | The plan covers an account that takes whole shares only | `--whole-shares` |
   | The user is unsure where to set bands | `--suggest-bands` |
   | The user gives their own tax rates | `--short-term R` / `--long-term R` |
   | The account classification in `routing.accounts` is wrong | `--taxable ID` / `--tax-advantaged ID` |

3. Run `plan.py` once, writing the output to a file: `> DIR/rebalancing.json`. DIR is the session scratchpad.
4. If the run exits non-zero, follow the exit code table and stop.
5. If the Artifact tool is available in the session, deliver the page:
   1. Run `render.py --in DIR/rebalancing.json --out DIR/rebalancing.html`.
   2. Publish the HTML with the Artifact tool: icon scale, description "Rebalancing plan as of DATE".
   3. On later runs republish the same file path, so the link stays stable.
   4. Reply with the page reply format below.
6. If the Artifact tool is not available (a headless or non-interactive host), reply with the markdown fallback format below instead.
7. If the plan has a sell in a taxable account, point to the tax-aware skill for exact lots and wash-sale checks before that sell.
8. If the user then asks to place a trade, hand off to the portfolio-analysis trading protocol: one order at a time, preview first, explicit confirmation, in the account shown for that symbol.

## Reply format

The **Next step** line, used in both formats, is: "This is a plan. To place any of these orders, say which one; each goes through the preview-and-confirm protocol one at a time."

### Page reply (the default, when the page was published)

In this order, then stop:

1. The artifact link on its own line.
2. One line: `mode` rebalance of `total_value` · max drift `max_drift` · N of M keys outside the `bands.absolute` / `bands.relative` bands · `trades` count (buys `buys_total`, sells `sells_total`) · est. tax `est_tax` (contribution `contribution` or withdrawal `withdrawal` when non-zero)
3. **Flags** — one bullet per `flags[].message`, or "None".
4. The **Next step** line.

The session's standing "Next you could ask:" follow-ups block, when it applies, comes after the Next step line.

Do not repeat the sections the page carries. If the user asks for a number the page shows, read it from the script's JSON.

### Markdown fallback (only when the Artifact tool is unavailable)

Render in this order.

**Rebalancing plan** — `mode` rebalance of `total_value` (contribution `contribution`, withdrawal `withdrawal`; frozen `frozen_value`), bands `bands.absolute` / `bands.relative`

1. **Allocation** — table from `allocation`: Key · Members · Value · Weight · Target · Drift · Relative · Breach.
2. **Trades** — table from `trades`: Symbol · Side · Units · Price · Value · Reason · Est. gain · Est. tax, plus the account from `trades[].account` or `holdings_by_account`.
   - Then one line: buys `buys_total`, sells `sells_total`, cash after `cash_after`, turnover `turnover`, estimated realized gain `est_realized_gain` and tax `est_tax`.
   - If `trades` is empty, say so.
   - When `routing` is present and `est_tax` differs from `routing.est_tax_pro_rata`, add one line: filling the sells from tax-advantaged accounts first changes the estimated tax from `est_tax_pro_rata` to `est_tax`. List `routing.accounts`' classification and note it is a guess from account type.
3. **After trades** — table from `post_trade`: Key · Weight · Target · Drift.
4. **Flags** — one bullet per `flags[].message`, or "None".
5. **Suggested bands** — only with `--suggest-bands`. One line per `suggested_bands` row: key, annualized volatility, proposed absolute / relative widths. Say these are proposals from one year of volatility, not advice; the user chooses the bands.
6. **Next step** — the Next step line. The session's standing "Next you could ask:" follow-ups block, when it applies, comes after this line.

### Number formats

| Value | Format |
|---|---|
| Money | 2 dp with thousands separators |
| Weights and drifts | percentages to 1 dp |
| Units | 4 dp; whole numbers when whole shares |

## Rules

- Never place orders from this skill.
- Every number comes from the script.
- Run `plan.py` once per answer. The one rerun after an E*Trade login is the only exception.
- Publish the page or write the markdown fallback, never both.
- No advice about whether to rebalance. State what the bands say and what the trades would do.
- Present suggested bands as proposals, not advice.
- Before any sell in a taxable account, point to the tax-aware skill for exact lots and wash-sale checks.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
