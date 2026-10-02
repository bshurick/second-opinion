---
name: market-analysis
description: Summarizes market status, indices, sectors, news, earnings dates and market flows (CFTC positioning, ETF flows, money-fund cash). Use when the user asks about the overall market or macro, not their own holdings (portfolio-analysis) or fair value (valuation).
---
Reports the big picture: market status, index levels, sector trends, news, upcoming earnings, and who is moving money where. It covers market-wide conditions, not deep dives on single stocks, and it describes conditions without forecasting them.

## Background

**Which source answers what**

| Question | Source |
|---|---|
| Levels and day/week changes | `indices.py` |
| Where the yield curve and financial conditions sit against their own full history | `indicators.py` |
| Earnings and ex-dividend dates | `earnings.py` |
| Who is buying and selling | `flows.py` |
| News, and why things moved | Web search |
| A single stock's quote or history | The portfolio-analysis `quote.py` or trading `history.py` scripts |
| A named institution's holdings (13F) | The fundamental-research `holdings.py` script |
| Real yield, breakeven, term premium and Baa spread ranked against history | The fixed-income skill's `rates.py` |

**`indices.py`**

- One batched Yahoo download, delayed: indices, sector ETFs, Treasury yields and spreads, gold, the dollar, oil, bitcoin, VIX, and breadth proxies.
- Gold and oil are Yahoo spot proxies for the futures.
- Yields and spreads are in percentage points.
- Breadth and the RSP/SPY relative returns are proxies, not full market breadth.
- Missing data turns a row or field into null. It never fails the snapshot.

**`indicators.py`**

- It ranks the two things `indices.py` reports as bare levels: the yield curve (`T10Y3M` back to 1982 and `T10Y2Y` back to 1976) and the Chicago Fed's financial conditions index (`NFCI`, back to 1971).
- It also ranks the VIX against its whole history, where `indices.py` uses the trailing year.
- Each reading carries its percentile, its median, the date its history starts and the number of observations, so a rank can be read against the span it was computed over.
- The four spans differ, so the percentiles are not comparable with each other as numbers.
- It needs no key. Data comes from FRED.

**`flows.py`**

It answers "who is moving money where" from public reporting regimes, not from price and volume. With no flags it runs the first three blocks below. Each block carries its own as-of date.

| Block | Source and timing | What it holds |
|---|---|---|
| `positioning` | CFTC Traders in Financial Futures. Weekly: Tuesday's positions, released Friday. | Per contract and per trader class: the net position, its week-over-week change, its share of open interest, and its percentile within `--weeks`. |
| `etf_flows` | SPDR sector ETFs plus SPY, from State Street's daily NAV and AUM. Prior close. | Shares outstanding, appended to a local series. Flow = change in shares × NAV over the last 1, 5 and 20 observations. |
| `cash` | FRED `WRMFNS`, retail money market fund assets. Weekly data the Fed's H.6 release publishes monthly, so up to six weeks behind. | The latest level with 1-, 4-, 13- and 52-week changes. |
| `short_volume` | FINRA daily short-sale volume. Prior close. Only with `--short`. | Each symbol's latest short-volume ratio against its `--days` average. |

- **Trader classes:** asset managers, leveraged funds, dealers, other reportables, small traders.
- **Contracts covered:** the S&P 500, Nasdaq 100, Russell 2000 and Dow futures, all eleven S&P sector index futures, 2- and 10-year notes, the Ultra bond, the dollar index, VIX and bitcoin.
- **Stale contracts.** A contract's `weeks_behind` says how many weeks older its latest report is than the newest one. Thin sector futures drop out of the report for weeks at a time.
- **Short ETF history.** The local ETF series starts the first day `flows.py` runs. Flows are null until a second day has been recorded. `observations` and `first_observation` say how much history exists.
- **A dead source.** A block whose source fails becomes `{"error", "code"}` on its own. One dead source never fails the run.

**The page `render.py` builds**

One self-contained HTML page for the Artifact tool, light and dark themes, no external scripts. It holds:

- Stat tiles: S&P 500, VIX and its one-year percentile, the 10-year yield and 10y−13w spread, breadth, S&P futures net positioning for asset managers, leveraged funds and small traders, sector ETF five-observation flow, retail money-fund cash.
- An indices/rates/macro table.
- A crowdedness heatmap of every contract's percentile per trader class, with a sortable contracts table. Clicking a contract opens its weekly history chart and class table.
- A sectors table joining sector ETF moves, sector futures positioning and sector ETF flows.
- The ETF flow bars with a short-history note, the money-fund line, and the short-volume table when present.
- Flags and the notes.

**How to read the numbers.** These are context, not timing advice.

- An inverted (negative) 10y−13w spread has historically preceded recessions, with long and variable lags.
- VIX in the top quartile of its 1-year range signals elevated fear, and the bottom quartile complacency. Neither is a signal to trade.
- Equal-weight (RSP) underperforming cap-weight (SPY) means market breadth is narrow.
- Asset managers are the slow institutional money (pensions, insurers, mutual funds). They are structurally net long equity index futures.
- Leveraged funds (hedge funds, CTAs) are structurally net short, as a hedge against long stock books. So read each class against its own percentile, not against zero.
- A percentile near 0 or 100 marks a crowded position that has historically been prone to reversal. It does not mark a direction. A crowded reading is a percentile ≤ 10 or ≥ 90.
- Small traders (non-reportables) are the closest public proxy for retail.
- Positioning is futures only, not cash-equity ownership.
- ETF creations mix investor demand with authorized-participant arbitrage. A single large print is often a creation-unit rebalance, so a 5- or 20-observation sum is the number to quote.
- A rise in retail money-fund assets is cash leaving risk, or wages saved. A fall is cash deployed or spent.
- The money-fund series is weekly but published monthly, so its latest week can be six weeks old.

**Research notes on market dynamics.** Historical statistical patterns from specific samples, not predictions.

- **Index momentum is real at short horizons.** The equal-weighted US market index shows about +30% weekly autocorrelation, even though the average individual stock's is slightly negative (−3.4%). Broad-market trends persist week to week in a way single names do not [LoMacKinlay90].
- **Large caps lead small caps.** Last week's large-cap return correlates 27.6% with this week's small-cap return; the reverse is only 2.0%. After a broad large-cap move, delayed follow-through in small caps is the documented historical pattern. This is context for a divergence between the S&P 500 and the Russell 2000 [LoMacKinlay90].
- **Fund herding is modest and mechanical.** Only about 2.5 extra same-side funds per 100 trading a stock, a byproduct of shared momentum signals and not an independent force. Crowded buying is not, by itself, evidence a stock will keep rising or crash [GrinblattTitmanWermers95].
- **Relative-performance competition inflates risk-taking.** Managers judged against peers systematically over-allocate to risky assets versus what they would hold in isolation, bidding those assets above fundamental value. It is individually rational and systemically fragile [LackerZariphopoulou18].

## Scripts

Run with the Bash tool. Every script prints JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/indices.py"
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/indicators.py"
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/earnings.py" SYMBOL [SYMBOL ...]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/flows.py" [--cot] [--etf] [--cash] [--short SYM ...] [--weeks N] [--days N] [--history]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/render.py" --in flows.json --indices indices.json --out page.html
```

| Script | What it does |
|---|---|
| `indices.py` | Indices, sector ETFs, Treasury yields and spreads, gold, dollar, oil, bitcoin, VIX and breadth proxies. Takes no arguments. |
| `indicators.py` | The yield curve, financial conditions and the VIX, each ranked against its whole history. Takes no arguments. |
| `earnings.py` | Next earnings date and next ex-dividend date per symbol. Takes 1-20 symbols. |
| `flows.py` | CFTC positioning by trader class, sector ETF flows, retail money-fund cash, and FINRA short volume. |
| `render.py` | Turns a saved `flows.py` result (`--in`) and/or a saved `indices.py` result (`--indices`) into the page. At least one is required. Prints `{"out", "title", "indices", "contracts", "funds", "flags"}`. |

| `flows.py` flag | Effect |
|---|---|
| `--cot`, `--etf`, `--cash` | Run only the named blocks (`positioning`, `etf_flows`, `cash`). |
| `--short SYM ...` | Adds FINRA short-volume ratios for up to 20 symbols to whichever blocks run. |
| `--weeks N` | The percentile window for positioning. Default 52. |
| `--days N` | The averaging window for short volume. Default 20. |
| `--history` | Adds each contract's weekly net position per trader class over the window. `render.py` charts it when a contract is clicked. |

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad arguments. For `earnings.py`: no symbols, an invalid symbol, or more than 20. For `render.py`: an input is missing, malformed, or not the matching script's result. | `error` |
| 5 | Upstream data source error | `error`, and answer what the other sources allow |
| 6 | Python dependencies missing | `error`, and say the setup skill repairs it |

## Steps

Pick the case that matches the request. If a question touches individual stocks or portfolio topics, still answer it with the tools available here.

**Market overview**

1. Check market status: open or closed, and session times.
2. Run `indices.py` for the key indicators: S&P, Dow, Russell, Nasdaq, VIX, Treasury yields and spreads, gold, the dollar, oil and bitcoin.
3. If the question is where the curve, financial conditions or the VIX sit against history, run `indicators.py`. Quote each reading against its own median, and report the rank and what the indicator is.
4. Summarize the current market tone: risk-on or risk-off, and the notable moves.

**News and events**

1. Search for news on the specific tickers, sectors or themes.
2. Use web search for broader financial news and analysis.
3. Apply the dating rules in Rules to every item before using it.
4. Synthesize findings from multiple sources, citing where each came from.
5. Highlight market-moving events and their potential impact.

**Earnings calendar**

1. Run `earnings.py` with the stocks or watchlist symbols. It also reports the next ex-dividend date.
2. Identify upcoming high-impact earnings that could affect sectors or the market.
3. Summarize consensus estimates (EPS, revenue) from web search, noting any recent revisions.

**Sector and thematic trends**

1. Compare sector performance using index levels and related tickers.
2. Identify emerging themes, for example AI, energy transition, rate-sensitive sectors.
3. Use news and web search for context on why sectors are moving.

**Flows and positioning**

Use this case for "who is buying", "is money leaving equities", "are institutions or retail behind this move", "where is money rotating".

1. Run `indices.py` and write its output to `DIR/indices.json`. DIR is the session scratchpad.
2. Run `flows.py --history` once and write its output to `DIR/flows.json`. Add `--short SYM` when the question names a stock.
3. Run `render.py --in DIR/flows.json --indices DIR/indices.json --out DIR/market.html`.
4. Publish the HTML with the Artifact tool: icon chart, description "Market flows and positioning as of DATE". On later runs republish the same file path so the link stays stable.
5. Reply with the flows page format below.
6. If the Artifact tool is not available in the session, skip steps 3–4 and reply with the markdown fallback. Never both.
7. If the user asks about a named institution's quarter-over-quarter holdings, hand off to the fundamental-research 13F holdings script.

## Reply format

**For every reply**

- Lead with the most important information: market status, biggest movers, key events.
- Cite the source of every news item and piece of analysis.
- Distinguish data (prices, estimates) from interpretation (your analysis).
- Note data limitations: delayed quotes, pre-market versus regular session.
- News items appear newest first with the date inline.

**Flows page reply:** these, in this order.

1. The artifact link on its own line.
2. One line: S&P 500 `last` (`day_change_pct`) · VIX `last` (1y percentile) · 10y `last` · positioning as of `positioning.report_date` · ETF flows as of `etf_flows.as_of` · retail money funds `cash.latest`B.
3. The reading the compliance rules require, in two to four sentences. Name the crowded readings (percentile ≤ 10 or ≥ 90) and the sectors where futures positioning and ETF flows agree or disagree. Give each with what it has historically meant and its date, without forecasting.
4. One sentence on what the picture cannot show.

The page carries the tables and charts. Do not repeat them in the reply.

**Markdown fallback (only when the Artifact tool is not available):** prose and tables, in this order.

1. Lead with the newest report dates. CFTC data is Tuesday's positions released Friday. SPDR and FINRA are the prior close. FRED money funds are weekly data published monthly and up to six weeks behind.
2. Per contract, the net position and week-over-week change for asset managers, leveraged funds and small traders, with the percentile. Name crowded readings (percentile ≤ 10 or ≥ 90) and say what a crowded position has historically meant, without forecasting.
3. For sectors, pair the sector futures positioning with the sector ETF 5- and 20-observation flows. When the local ETF series is shorter than the window, say how many observations exist instead of quoting a flow.
4. What the picture cannot show: cash-equity ownership, who is on the other side of a trade, and retail flow at the stock level. Small-trader futures positioning and short-volume ratios are proxies.

## Rules

- Always attempt to answer the question yourself.
- Never read a rank or percentile as a signal to act, and never present one as a view on what anything is worth.
- Present the research notes and the reading rules in Background as context, never as forecasts.
- Remind users that market commentary is not financial advice.

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
