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
| How far the S&P 500 sits from its 50-, 100- and 200-week averages, against history | `indices.py` `trend` |
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
- `trend` comes from a second download of the S&P 500's daily closes back to 1950, grouped into weeks. The week in progress counts at today's close. A failed download makes `trend` null.
- For each of `wma_200`, `wma_100` and `wma_50` it gives `gap_pct` (last weekly close against the simple average, in percent), `percentile` (share of all weeks since the window filled with a smaller gap), `level`, `median_gap_pct` and `share_below_pct` (how often the index has closed under that average).
- `band_low_pct` and `band_high_pct` are the gaps at the 20th and 80th percentiles, which bound the neutral zone. `series` holds the last five years of weekly closes and averages for the page's chart.
- `--history` adds each row's daily closes over the trailing year (`history`, with `high_1y`, `low_1y` and `change_1y_pct`) and `trend.daily`, a year of daily S&P 500 closes. It also lengthens `trend.series` from five years of weeks to twenty. Each day in `trend.daily` carries the three averages with that day's close counted as its week's close.
- `--holdings` adds `top_holdings` to each sector row: Yahoo's ten largest holdings of the sector fund with each one's share of the fund. Yahoo gives the list no date. A failed lookup makes that row's list null.
- `--history` also adds `interest_rates` from FRED: the fed funds rate (DFF), the 2- and 10-year Treasury yields (DGS2, DGS10) and the 30-year mortgage rate (MORTGAGE30US) over twenty years, every observation in the latest year and the last of each week before it. A series FRED can't serve goes to `unavailable`.
- Both flags feed the page. Leave them off when reading the levels, because they add about 400 KB of output.
- `level` is `extended` at a percentile of 80 or more, `depressed` at 20 or less, and `neutral` between. The cut-offs sit on the gap's own history because the index drifts up, so the average lags below it and the typical gap is positive (about +17% for the 200-week, +9% for the 100-week, +5% for the 50-week).

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
- **Flow windows count readings, not days.** Each flow carries the date it starts from (`flow_5d_from`) and the calendar days it spans (`flow_5d_span_days`); the 1- and 20-observation flows carry the same pair. Quote a flow with its dates.
- **A dead source.** A block whose source fails becomes `{"error", "code"}` on its own. One dead source never fails the run.

**The page `render.py` builds**

One self-contained HTML page for the Artifact tool, light and dark themes, no external scripts. It holds:

- Five stat tiles: the S&P 500 with its 200-week level, the VIX and its one-year percentile, the 10-year yield and 10y−13w spread, breadth, and S&P futures positioning as each trader class's percentile (asset managers, leveraged funds, small traders).
- A line chart of the S&P 500's weekly close over five years against its 200-week average, with the 200-week neutral zone shaded and the 100- and 50-week averages drawn faint as context, and a table of each gap's level, percentile and typical gap.
- Range buttons on that chart, with `--history` data: daily closes over the latest week, month, three months or year, and weekly closes over 5, 10 or 20 years. The three shorter ranges scale to the close and name any average that falls off the scale.
- An interest rates chart right after it, with `--history` data: fed funds, 2- and 10-year Treasury and 30-year mortgage, each with its level and change in points over the range, and range buttons from a week to 20 years.
- An indices, rates and macro table grouped by kind: stocks and volatility, Treasury yields (moves in basis points), and commodities, currency and crypto, each value with its unit. With `--history` data, clicking a name opens its chart of daily closes with the same range buttons.
- A crowdedness heatmap of every contract's percentile per trader class, with a sortable contracts table. Clicking a contract opens its weekly history chart and class table.
- A sectors table joining sector ETF moves, sector futures positioning and sector ETF flows. Clicking a sector opens its fund's ten largest holdings (`--holdings`) and its price chart (`--history`).
- The fund flow bars, money in to the right of a centre line and money out to the left, with the dates the window covers, the money-fund line, and the short-volume table when present.
- Flags and the notes.
- With `--summary`, a headline analysis card under the tiles, with an optional chart beside its text. The model writes its text and picks the chart, and the script holds it to the limits.

**How to read the numbers.** These are context, not timing advice.

- The 200-, 100- and 50-week gaps measure how far price has run from its own trend. They are not a valuation, so `extended` is never "overvalued" and `depressed` is never "undervalued": earnings, rates and multiples are not in the number.
- Since 1950 none of the three gaps has said much about the next five years: rank correlations are near zero.
- Over the next year the windows split. For the 100- and 200-week, `extended` readings were followed by a down year about one time in three, `depressed` ones about one in five, with similar average returns.
- The 50-week runs the other way. It is close to the 200-day average traders watch, and an `extended` 50-week gap was followed by a down year less often (about one in five) than a `depressed` one (about one in four). That reads as momentum, as the 200-day studies also find.
- Closes below the 200-week average itself are rare, about one week in six since 1950, and have mostly come in bear markets: long stretches in 1969–71, 1973–76, 2001–04 and 2008–10, brief ones in 1962, 1966, 1982, 2011, 2020 and 2022. The 1987 crash never closed a week below it.
- The 200-week average is known from a line attributed to Charlie Munger about buying quality stocks near it. That line concerned single stocks, not the index.
- When the windows disagree, the 200-week reflects the run over about four years, the 100-week about two and the 50-week about one. A `neutral` 50- or 100-week beside an `extended` 200-week means most of the distance was covered earlier.

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
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/indices.py" [--history] [--holdings]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/indicators.py"
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/earnings.py" SYMBOL [SYMBOL ...]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/flows.py" [--cot] [--etf] [--cash] [--short SYM ...] [--weeks N] [--days N] [--history]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/market-analysis/scripts/render.py" --in flows.json --indices indices.json --out page.html [--summary summary.json]
```

| Script | What it does |
|---|---|
| `indices.py` | Indices, sector ETFs, Treasury yields and spreads, gold, dollar, oil, bitcoin, VIX, breadth proxies, and the S&P 500's 50-, 100- and 200-week trend. `--history` adds daily closes per row and for the trend. `--holdings` adds each sector fund's ten largest holdings. |
| `indicators.py` | The yield curve, financial conditions and the VIX, each ranked against its whole history. Takes no arguments. |
| `earnings.py` | Next earnings date and next ex-dividend date per symbol. Takes 1-20 symbols. |
| `flows.py` | CFTC positioning by trader class, sector ETF flows, retail money-fund cash, and FINRA short volume. |
| `render.py` | Turns a saved `flows.py` result (`--in`) and/or a saved `indices.py` result (`--indices`) into the page. At least one is required. `--summary` adds the headline analysis card. Prints `{"out", "title", "indices", "contracts", "funds", "flags"}`, plus `for_you_dropped` when `for_you` was dropped because `portfolio-last-check.json` shows no full read today. |

| `flows.py` flag | Effect |
|---|---|
| `--cot`, `--etf`, `--cash` | Run only the named blocks (`positioning`, `etf_flows`, `cash`). |
| `--short SYM ...` | Adds FINRA short-volume ratios for up to 20 symbols to whichever blocks run. |
| `--weeks N` | The percentile window for positioning. Default 52. |
| `--days N` | The averaging window for short volume. Default 20. |
| `--history` | Adds each contract's weekly net position per trader class over the window. `render.py` charts it when a contract is clicked. |

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad arguments. For `earnings.py`: no symbols, an invalid symbol, or more than 20. For `render.py`: an input is missing, malformed, or not the matching script's result, or the summary file breaks a rule. | `error` |
| 5 | Upstream data source error | `error`, and answer what the other sources allow |
| 6 | Python dependencies missing | `error`, and say the get-started skill repairs it |

## Steps

Pick the case that matches the request. If a question touches individual stocks or portfolio topics, still answer it with the tools available here.

A call with no question (the skill invoked on its own, or "how's the market") runs **Flows and positioning**, so the page is the default answer.

**Market overview**

1. Check market status: open or closed, and session times.
2. Run `indices.py` for the key indicators: S&P, Dow, Russell, Nasdaq, VIX, Treasury yields and spreads, gold, the dollar, oil and bitcoin.
3. Quote the S&P 500's trend among the headline numbers: for the 200-, 100- and 50-week averages in that order, give the `level`, `gap_pct`, `percentile` and `median_gap_pct`, e.g. "200-week: extended, +28.9% (81st percentile since 1950; median +16.6%)". Use the level words only, never "overvalued" or "undervalued". If `trend` is null, say the trend could not be read.
4. If the question is where the curve, financial conditions or the VIX sit against history, run `indicators.py`. Quote each reading against its own median, and report the rank and what the indicator is.
5. Summarize the current market tone: risk-on or risk-off, and the notable moves.

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

1. Run `indices.py --history --holdings` and write its output to `DIR/indices.json`. DIR is the session scratchpad. Read the levels from the file with the `history`, `series` and `daily` lists left out.
2. Run `flows.py --history` once and write its output to `DIR/flows.json`. Add `--short SYM` when the question names a stock.
3. Read the accounts: run the portfolio-analysis skill's `brief.py --no-headlines` (`"${CLAUDE_PLUGIN_ROOT}/skills/portfolio-analysis/scripts/brief.py" --no-headlines > DIR/portfolio.json`, about 10 seconds). If it fails for any reason, including an expired E*Trade login or that skill not being installed, go on without `for_you`, and do not raise the login prompt for this section alone.
4. If an earlier Market Flows page exists, check it with `get_artifact`. Leave `for_you` out unless its read mode is `owner` or the page is new. An artifact keeps its link across republishes, and the fold only hides text that is still in the HTML. If the check fails, leave `for_you` out.
5. Write the headline analysis to `DIR/summary.json`, following the section below. Include `for_you` only when steps 3 and 4 both allow it.
6. Run `render.py --in DIR/flows.json --indices DIR/indices.json --out DIR/market.html --summary DIR/summary.json`. If the output holds `for_you_dropped`, the accounts read did not count as a full read today and the card went out without that section.
7. Publish the HTML with the Artifact tool: icon chart, description "Market flows and positioning as of DATE". On later runs republish the same file path so the link stays stable.
8. Reply with the flows page format below.
9. If the Artifact tool is not available in the session, follow the "No Artifact tool" rule: save the page with `local_page.py` and reply with the page format. The markdown fallback is the last resort.
10. If the user asks about a named institution's quarter-over-quarter holdings, hand off to the fundamental-research 13F holdings script.

**The headline analysis**

A small card under the stat tiles: a headline, "What stands out", "What to look into", a folded "What this means for you" and an optional chart to the right. The file is `{"headline", "stands_out", "look_into", "for_you", "chart", "chart_note"}`, where `for_you` is a list such as `[{"topic": "Cash", "text": "..."}]`.

- Limits, which `render.py` enforces: `headline` 20 words, `stands_out` 90 and `look_into` 90. `for_you` is up to five `{"topic", "text"}` points, each `topic` up to 4 words and each `text` up to 70. `for_you` is optional and the rest are required.
- `chart` is optional, the one chart beside the text, picked to show the headline's point. Leave it out when none fits.
- `chart_note` is optional and needs `chart`: one line of up to 25 words saying why this chart shows the headline's point, such as "Three of the four trader classes sit at the edge of their year." The chart adds its own line reading the figures.

| `chart` | What it draws | Fits a headline about |
|---|---|---|
| `index_moves` | The week's change in the S&P 500, Nasdaq, Dow and Russell 2000 | A broad move, or large caps against small caps |
| `sector_moves` | Each sector fund's week change, largest gain to largest loss | A rotation, or one sector leading or lagging |
| `crowding` | Each trader class's S&P 500 futures percentile on a 0-100 scale, crowded ends shaded | Crowded positioning |
| `trend_gaps` | The 200-, 100- and 50-week gaps, each with its neutral zone and median | Where the index sits against its trend |
| `yield_moves` | The week's change in the 13-week, 5-, 10- and 30-year Treasury yields, in basis points | A move in rates |
- Links take the form `[Sectors](sec-card)`, in `look_into` only, to these ids: `trend-card`, `rates-card`, `idx-card`, `pos-card`, `sec-card`, `etf-card`, `cash-card`, `short-card`, `flags-section`.
- Every number comes from this run's script output, quoted as the script gives it.
- Lead with what is unusual today, not a tour of the page. Say plainly when nothing stands out.
- Separate data from inference, using words like "may" for inference.
- Carry dates when a reading is older than the page's prices.
- Name the bull and the bear side when reading a market condition or a security.
- No buy, sell or hold call, and no forecast. `for_you` says what a reading does to the person's holdings, not what to do. The forbidden verbs are rejected in every field.
- `for_you` takes portfolio numbers only from a read taken on this run or today, never from memory. Non-numeric context from memory or the profile is allowed, such as a paycheck and stock awards both depending on one employer.
- A file that breaks a rule exits 2 with `error` naming the rule and writes no page. Rewrite the file and render again.

"What this means for you" is the deep part of the card. The other three fields describe the page. This one works out what the readings do to this person's accounts, and it sits folded, so it has room.

- Write one point per asset class the person owns, largest first by value, up to five. A class no reading touches gets no point.
- Build each point from two results: this run's market output and today's accounts read (`DIR/portfolio.json`: `allocation`, `sector_weights`, `positions`).
- Each point carries four things: the reading with its number and date, the holding with its value and weight, the mechanism that links the two, and the side that helps and the side that hurts.
- Do the arithmetic when the outputs give both numbers, and show both: a weight times a move is a contribution to the day, and a cash balance times a rate is a year of interest at today's rate. Label the result as arithmetic at today's figures.
- Say where the data stops. A fund is not looked through, so a sector reading reaches an index fund only through the index.
- A point that restates a weight or a day change with no market reading beside it is a recap. Cut it or finish it.

Readings to trace for each asset class:

| The person owns | Readings to trace |
|---|---|
| Cash and money-market funds | The 13-week bill yield and the fed funds rate set what the cash earns. Their change over the week and the year says which way that income is heading. Retail money-fund assets, with their date, show whether households are adding to cash. |
| Bonds and bond funds | The 2-, 10- and 30-year yield changes in basis points: a bond fund's price moves against yields. The 10-year against the 13-week spread, for what longer bonds pay over cash. Asset-manager and leveraged-fund positioning in Treasury futures, with the report date. |
| Stock index funds | The S&P 500's move, the three trend gaps in the order 200-, 100- and 50-week, and equal-weight against cap-weight returns for a cap-weighted fund. S&P 500 futures positioning per trader class and SPY flows with their dates. |
| Single stocks and sector tilts | The person's sector weights against each sector fund's day and week move. That sector's fund flow and futures positioning, and a holding that appears in a sector fund's `top_holdings`. |
| International stocks | The dollar index and its week change: a rising dollar cuts the dollar value of foreign shares. Dollar index futures positioning. |
| Pay and stock awards from one employer | The employer's sector move, as non-numeric context from memory or the profile. |

Before: "Cash and money-market funds are 51.5% and bonds 26.5%, so US stocks (19.4%) carry most of the move."

After: `{"topic": "Cash", "text": "Cash and money-market funds are $298,340, 51.5% of the accounts. They earn close to the 13-week bill yield of 4.122%, about $12,300 a year at today's rate. The fed funds rate sets that income, and it has not moved this week. The helping side: this half of the accounts sat out the S&P 500's 8.05% week. The hurting side: it also sits out any rebound."}`

What to look for on this page:

- Crowded readings (percentile at or below 10, or at or above 90), read only for contracts with `weeks_behind` of 0. Name stale ones as stale.
- Sectors where futures positioning and ETF flows agree or disagree, and how few ETF observations exist.
- A long in one trader class mirrored by a short in another.
- Whether positioning (Tuesday) predates a large price move.

## Reply format

**For every reply**

- Lead with the most important information: market status, biggest movers, key events.
- Cite the source of every news item and piece of analysis.
- Distinguish data (prices, estimates) from interpretation (your analysis).
- Note data limitations: delayed quotes, pre-market versus regular session.
- News items appear newest first with the date inline.

**Flows page reply:** these, in this order.

1. The artifact link, or the saved page's `path`, on its own line.
2. The summary's `headline`, on one line. "What stands out" on the page carries the reading the compliance rules require.
3. One line: S&P 500 `last` (`day_change_pct`) · 200-week `trend.wma_200.level` (`gap_pct`) · VIX `last` (1y percentile) · 10y `last` · positioning as of `positioning.report_date` · ETF flows as of `etf_flows.as_of` · retail money funds `cash.latest`B.
4. One sentence on what the picture cannot show.
5. One line when `for_you` was left out, saying why: the accounts could not be read today, or the page is shared. Old holdings are never presented as current.

The page carries the tables and charts. Do not repeat them in the reply.

**Markdown fallback (only when no page could be published or saved):** prose and tables, in this order.

Open with the whole headline analysis as text: the headline, "What stands out", "What to look into" without its links, and "What this means for you" when written, one short paragraph per point led by its topic. `render.py` does not run here, so nothing enforces the limits and rules in the headline analysis section. Keep to them.

1. Then the newest report dates. CFTC data is Tuesday's positions released Friday. SPDR and FINRA are the prior close. FRED money funds are weekly data published monthly and up to six weeks behind.
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

- **No Artifact tool.** When the session has no Artifact tool, still render the page and skip only the publish step. Then run `"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/get-started/scripts/local_page.py" --in PAGE.html` on the rendered file. It saves a standalone copy and opens it in the browser.
- After `local_page.py`, reply with the page format and give its `path` where the artifact link goes. Write the markdown fallback only when no page was rendered or `local_page.py` exits non-zero.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.

**Writing** (every reply, page and saved file):

- Spell out every acronym and shorthand at its first use, as in "comparable-store sales (comps)". A label is a first use: a scenario name, headline or column header uses the plain words or defines its shorthand. Tickers, $ and % are exempt. Spelling out a term is not explaining a concept.
- Cut adjectives and adverbs that carry no fact. A word like "sharp" or "severe" stays only beside the number that shows it.
- Use the active voice: name who did what. "Management cut prices", not "prices were cut".
- Keep sentences short, one idea each, under about 25 words.
- Give every bulleted or numbered list a heading or lead-in that says what it lists. Otherwise write the items as prose, or as a table with column or row headers when they share fields.
- Lead with the answer. The first sentence gives the result or answers the question asked; the reasons and the detail follow. Each paragraph opens with its point.
- Put a figure, a date or a source where a vague word would go. "Often", "soon", "many" and "significant" say nothing until a number stands beside them, as in "in 7 of the last 10 years".
- State a doubt once, where it applies, and say what causes it. Write the rest plainly. Give each side the weight its evidence has, and never pad the weaker side to make the two look even.
- Cut every sentence the reader would not miss: an opening that announces what the reply will do, a closing that repeats it, a restatement of the sentence before, and a claim that something matters with no reason given.
- Say what is, in plain words: "the data is inconclusive", not "the data does not conclusively show"; "use", not "utilize". Drop build-ups such as "not just X but Y", and keep a series of items in one sentence.
