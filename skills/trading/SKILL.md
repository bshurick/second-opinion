---
name: trading
description: Reads price action, technicals and momentum for short-horizon timing on one security, and holds the order scripts (preview, place, cancel, list). Use when the user asks about a chart, trend, entry or exit timing, or orders. Fair value is valuation.
---
Analyzes one security's price history for trend, momentum and timing, compares securities, sizes a position from a stated risk budget, and previews, places, lists and cancels orders. It describes historical patterns; it does not predict prices or say whether to trade.

## Background

- **Data.** Market data comes from Yahoo Finance and needs no credentials. Order placement needs a connected brokerage, through SnapTrade or E*Trade direct (connect skill).
- **Account ids** come from the portfolio-analysis skill's `accounts.py`.
- **`broker`.** Every account row and every order or preview result carries `broker` (`snaptrade` or `etrade`).
- **Quotes** from the portfolio-analysis skill's `quote.py` carry `source` and `realtime`. Say "real-time" only when `realtime` is true.
- **Other skills.** Fundamentals come from the valuation skill's `fundamentals.py`. News and analyst commentary come from web search. Long-term fair value belongs to valuation. Holdings and allocation belong to portfolio-analysis. Written trade plans belong to trade-journal.

### What `signals.py` returns

- **Windows are trading days** counted back from the last close: 1w=5, 1m=21, 3m=63, 6m=126, 12m=252. A statistic is null when the series is too short for it.
- **Always present:** `as_of`, `last_close`, `returns` (`1w`, `1m`, `3m`, `6m`, `12m`), `momentum_12_1`, `annualized_volatility`, `max_drawdown`, `current_drawdown`, `sma_50`, `sma_200`, `price_vs_sma_50`, `price_vs_sma_200`, `high_52w`, `low_52w`, `pct_from_52w_high`, `pct_from_52w_low`.
- **Optional blocks** appear only when the input carries what they need:

  | Input | Adds to the output |
  |---|---|
  | `prices` rows with `high`, `low`, `volume` (the full `history.py` rows) | `atr_14_pct`, `gap_stats`, `relative_volume_20_252`, `avg_dollar_volume_20`. Closes alone still work; these fields simply do not appear. |
  | `"benchmark": [...]` (date + close rows) | the `relative` block: `1m`, `3m`, `12m`, `momentum_12_1`, `relative_12_1`, all position minus benchmark |
  | `"pivots": k` (an integer >= 2) | the `pivots` block: close-based k-bar swing pivot highs and lows |
  | `"series": true` | the `series` block: the trailing SMA 50 and SMA 200 values on every date, the lines behind `sma_50` and `sma_200`, which `render.py` draws. The scalar fields are unchanged. |

### What `render.py` builds

One self-contained HTML page for the Artifact tool, from a saved `signals.py` result plus the `history.py` output it came from. Light and dark themes, no external scripts. It holds:

- stat tiles for the indicators as the script names them;
- the closes with the moving-average series on one axis, and the most recent swing pivots as dashed support and resistance lines;
- volume as its own small chart below;
- trailing and benchmark-relative returns as bars;
- a signals table with every field and its definition, and the pivot list;
- the note that this is timing analysis, not a recommendation.

It prints `{"out", "title", "symbol", "observations"}`.

### What `gate.py` decides

`gate.py` is the pre-trade discipline gate. It places nothing and blocks nothing. It reads the trade-journal's `journal.json` and the statement-import ledger when they exist, and needs neither.

| Situation | `decision` |
|---|---|
| The trade-journal skill is not installed | `SKIP`, reason "the trade-journal extra is not installed". It reads nothing. |
| BUY with no open journal entry | `REVIEW` ("no written plan") |
| BUY that breaks its plan: no stop, quantity above the journaled size, or actual risk above planned risk | `NO_GO` |
| BUY whose entry has no price stop but a recorded thesis-based `invalidation` | `REVIEW`, not `NO_GO`. `stop_predefined` says "thesis-based invalidation recorded: ..." and `risk_within_plan` is skipped. |
| A realized loss inside the cooldown (`--cooldown-days`, default 3) | `REVIEW` |
| SELL | always `GO`, annotated against the plan when one exists |
| Otherwise | `GO` |

- **Planned add.** An entry with `add_rule` gets an `add_rule` check. At or below the add price it passes, and the allowed quantity is the journaled size plus the add quantity. Above the add price the order is judged on the base plan.
- **Record.** It appends each decision to the matched entry's `gates` list.

### Order facts

- **Order statuses differ by broker.** Pass `--status` the vocabulary that matches the account's `broker`:

  | `broker` | Statuses |
  |---|---|
  | `etrade` | OPEN, EXECUTED, CANCELLED, CANCEL_REQUESTED, PARTIAL, EXPIRED, REJECTED |
  | `snaptrade` | PENDING, ACCEPTED, EXECUTED, CANCELED, REJECTED, ... |

- **`orders.py` rows** carry flat `order_id`, `symbol`, `side` and `quantity` next to the broker's own keys. `order_id` is the id `cancel-order.py` takes.
- **Preview flags.** A preview may carry `flags` with `UNSETTLED_CASH`.
- **Fractional quantities.** `<qty>` may be fractional (e.g. `0.5`) only on an account whose `broker` is `etrade`. A refusal exits 2 with one of these codes:

  | Rule | Refusal code |
  |---|---|
  | Up to 3 decimals | `FRACTIONAL_PRECISION` |
  | A buy of at least $5.00 | `FRACTIONAL_MINIMUM` |
  | MARKET only under one share | `FRACTIONAL_MARKET_ONLY` |
  | No GOOD_UNTIL_CANCEL | `FRACTIONAL_TERM` |
  | No fractional SELL_SHORT | `FRACTIONAL_SHORT` |
  | SnapTrade accounts take whole shares only | `FRACTIONAL_NOT_SUPPORTED` |

### The horizon map

The sign of the effect flips with the lookback window. These are historical statistical patterns, not predictions.

| Lookback | Historical pattern | What limits it |
|---|---|---|
| Days–weeks | Weak mean reversion, mostly illusory for single names. Last week's move says almost nothing about next week's. | Bid-ask bounce inflates it; a one-way cost of 0.40% erases roughly half of gross weekly contrarian profits. |
| 3–12 months | Continuation (momentum). The edge came from buying recent winners, concentrated in large caps; selling losers added nothing significant. | Figures are gross of costs; momentum is high-turnover and prone to sharp "momentum crashes". |
| 3–5 years | Reversal, and fragile. | It depends on the formation month, and is driven by low-price distressed stocks where tiny price errors move the result. |

- **Index patterns are not stock patterns.** The equal-weighted index has strongly positive weekly autocorrelation while the average single stock is slightly negative. Never infer single-name behavior from index trends, or the reverse.
- **Lead-lag.** Large caps lead small caps. A small cap that "hasn't moved yet" after a large-cap peer move is a documented pattern, but the profits concentrate in the stocks with the widest spreads and least liquidity.
- **Relative strength.** Strong 3–12-month relative strength is a documented continuation signal. A bad week alone is not a reversal signal. `momentum_12_1` relates to the 3–12 month row; the `1w` return is dominated by microstructure noise.
- **Herding.** "Everyone is piling in" is not an independent signal: fund herding is modest and adds no explanatory power once the momentum tilt is controlled for.
- **Costs.** Round-trip costs and turnover dominate short-horizon effects at retail scale.
- **Samples.** All figures come from specific historical samples; regimes change, and none of this guarantees future behavior.

Read `references/momentum-research.md` before quoting a figure, a sample period or a source for any of these patterns.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/history.py" <symbol> [--period 1mo|3mo|6mo|1y|2y|5y|max] [--start YYYY-MM-DD --end YYYY-MM-DD] [--interval 1d|1wk|1mo]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/signals.py" <<< '{"prices": [...], "benchmark": [...], "pivots": 3, "series": true}'
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/render.py" --in signals.json --prices history.json --out page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/gate.py" <symbol> <BUY|SELL> <qty> [--limit X | --price P] [--cooldown-days 3] [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/orders.py" <account_id> [--status PENDING] [--symbol SYM] [--count N]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/transactions.py" <account_id> [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--count N]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/preview-order.py" <account_id> <symbol> <BUY|SELL> <qty> [--type MARKET|LIMIT|STOP|STOP_LIMIT] [--limit X] [--stop X] [--term GOOD_FOR_DAY|GOOD_UNTIL_CANCEL|IMMEDIATE_OR_CANCEL|FILL_OR_KILL]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/place-order.py" <same arguments> --confirm
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/trading/scripts/cancel-order.py" <account_id> <order_id> --confirm
```

| Script | What it does |
|---|---|
| `history.py` | Daily OHLCV from Yahoo. `--period` defaults to `1y`. Each `prices` row carries `date`, `open`, `high`, `low`, `close`, `volume`. |
| `signals.py` | Momentum and technical statistics from a JSON object on stdin. `benchmark`, `pivots` and `series` are optional. |
| `render.py` | Interactive page from a `signals.py` result and the `history.py` rows behind it. |
| `gate.py` | Pre-trade discipline gate. Prints `decision` (GO, NO_GO, REVIEW or SKIP) and `reasons`. Places nothing. |
| `orders.py` | Orders for one account, filtered by `--status` and `--symbol`. |
| `transactions.py` | Transactions for one account between `--start` and `--end`. |
| `preview-order.py` | Previews an order. Never places. |
| `place-order.py` | Without `--confirm`, prints the preview and exits 3. With `--confirm`, runs a fresh preview and places the order. |
| `cancel-order.py` | Cancels one order by `order_id`. Requires `--confirm`. |

Every script prints JSON.

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Bad arguments or invalid input. For `render.py`, the input is not a signals result. For order scripts, also a read-only or shadowed account, or a `FRACTIONAL_*` refusal. | Show `error`. |
| 3 | `place-order.py` or `cancel-order.py` ran without `--confirm` | That is the gate. Show the output and stop. |
| 4 | Credentials missing | Show the `hint`. |
| 4 with code `ETRADE_REAUTH` | E*Trade needs today's authorization | Show the `url`, get the verifier code from the user, run the connect skill's `etrade-login.py --verifier CODE`, then rerun the command once. |
| 5 | Broker or Yahoo error. For `gate.py`, a corrupt journal or ledger. | Show the error. |
| 6 | Python dependencies missing | Show the error. |

## Steps

Pick the case that matches the request.

**The user asks about a chart, trend, momentum, support or resistance, or entry and exit timing**

1. Run `history.py <symbol>` and write its output to `DIR/history.json` (DIR is the session scratchpad).
2. For relative performance, run `history.py` a second time for the benchmark over the same period. Use SPY unless the user names one.
3. Build the `signals.py` input: `prices` from the full `history.py` rows (not just date + close), `"series": true`, `"pivots": 3`, and `benchmark` from the benchmark rows when you fetched them.
4. Run `signals.py` and write the result to `DIR/signals.json`.
5. Run `render.py --in DIR/signals.json --prices DIR/history.json --out DIR/trading.html`.
6. Publish the HTML with the Artifact tool: icon chart, description "SYMBOL trading signals as of DATE". On later runs for the same symbol, republish the same file path so the link stays stable.
7. Reply with the page format below.
8. If the Artifact tool is not available in the session (a headless or non-interactive host), skip steps 5 and 6 and reply with the markdown fallback. Never both.

Read support and resistance from the `pivots` block. Note any notable trend change.

**The user asks to research one stock**

1. Run the timing case above for price history and current data.
2. Get company fundamentals and key financial metrics from the valuation skill's `fundamentals.py`.
3. Get analyst ratings, earnings estimates and news from web search, dated as the `<research_dating>` block in Rules requires.
4. Synthesize the findings into a clear summary.

**The user asks to compare securities**

1. Gather the same data points for every symbol requested.
2. Compare valuations, growth metrics and analyst sentiment side by side.
3. Highlight relative strengths, weaknesses and trade-offs.

**The user gives a risk budget and asks how many units it implies**

1. Take the entry price and stop price from the user. Never propose the entry or stop price yourself.
2. Pick the formula:

   | Sizing | Formula | Inputs |
   |---|---|---|
   | Stop-based | `units = risk_budget / (entry_price - stop_price)` | the entry and stop the user states as their plan |
   | Volatility-based | `units = risk_budget / (price × atr_14_pct × multiple)` | `atr_14_pct` is `signals.py`'s 14-day ATR as a fraction of the last close; `price` is the last close or the user's stated entry; `multiple` is the user's chosen ATR multiple (e.g. 1-3x) |

3. Show the inputs and the formula alongside the result.
4. Phrase it as "the arithmetic works out to N units".
5. Say this is arithmetic, not a recommendation to enter the trade.

**The user wants to place an order**

NEVER place an order without, in this exact order:
1. Only when the trade-journal skill is installed (it is an optional extra): running the trading skill's `gate.py <symbol> <BUY|SELL> <qty> [--limit X]` and showing its `decision` and `reasons`. A SKIP decision (the journal is not installed) is not shown. The gate never blocks and never replaces the steps below.
   - On NO_GO or REVIEW, state the reason in one sentence and ask whether to proceed anyway or journal the plan first (trade-journal skill); the user's answer in their own message decides.
2. Running the trading skill's `preview-order.py <account_id> <symbol> <BUY|SELL> <qty> [--type ... --limit ... --stop ... --term ...]`.
3. Showing the preview output (trade id, price, units, estimated cost, estimated commission, remaining cash, and any warnings) to the user.
4. Receiving explicit confirmation of that specific order in the user's own message.
5. Only then running `place-order.py` with the exact same arguments plus `--confirm`. Without `--confirm` the script prints the preview and exits 3 — that is the gate, not a bug to work around. `place-order.py` re-runs the preview itself before placing, so the trade id you saw may differ; that is expected.

If the preview carries `flags` with `UNSETTLED_CASH`, say so before asking for confirmation.

When `gate.py` runs:

- Show `decision` and `reasons` verbatim.
- Never describe a GO as approval of the trade.
- When the entry has a thesis-based `invalidation`, read the invalidation back to the user in their words.

**The user wants to see orders or transactions**

1. Run `orders.py <account_id>`, with `--status` in the vocabulary of the account's `broker`, or `transactions.py <account_id>` with the dates asked for.
2. Show the rows.

**The user wants to cancel an order**

Cancelling requires the exact order id (`order_id` on each `orders.py` row) and the user's confirmation before running `cancel-order.py <account_id> <order_id> --confirm`.

## Reply format

**When the page was published (the default):**

1. The artifact link on its own line.
2. One line: SYMBOL `last_close` as of `as_of` · 12-1 momentum `momentum_12_1` · 12m `returns.12m` · vs SMA 200 `price_vs_sma_200` · volatility `annualized_volatility` · from 52w high `pct_from_52w_high`. Add `relative.12m` vs the benchmark when present.
3. The bull and bear reading: two to four sentences that place the numbers on the horizon map, state the horizon each pattern applies to, and name the key risks (costs, momentum crashes, regime change). Then stop.

The page carries the chart, the returns, the full signals table and the pivots. Do not repeat them in the reply.

**Markdown fallback (only when the Artifact tool is unavailable):** the script's numbers in this order.

1. Last close and as-of.
2. Trailing returns (1w/1m/3m/6m/12m).
3. Momentum 12-1.
4. Volatility and drawdowns.
5. Price vs SMA 50/200.
6. The 52-week range.
7. ATR, gaps and volume, and the `relative` block, when present.
8. The pivot highs and lows.
9. The same bull and bear reading.
10. The reminder that market analysis is not financial advice.

**For an order preview:** trade id, price, units, estimated cost, estimated commission, remaining cash, and any warnings.

**In every reply:**

- Present data with context for what the numbers mean.
- Distinguish facts (data) from interpretation (your analysis).
- Note data limitations (e.g. delayed quotes, missing periods).
- Answer the question fully yourself.

## Rules

- Every indicator value comes from a script. Present the script's numbers; do not recompute them.
- Interpret the numbers with the horizon map. Always state the horizon when discussing momentum or reversal.
- Surface round-trip costs and turnover whenever a short-horizon strategy comes up.
- Position sizing is arithmetic on the user's own entry, stop and risk budget. Never present it as a reason to take the trade.
- Order previews, placements and cancellations never go through the page.
- Nothing here says whether to buy, sell, or hold.

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
