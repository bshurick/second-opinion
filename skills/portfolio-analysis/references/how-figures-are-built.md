# How the brief's figures are built

Detail behind the fields `snapshot.py`, `summary.py` and `brief.py` print, and what `render.py` puts on the page. `SKILL.md` has the procedure; this file answers "how was that number computed" and "why is that headline there".

## What snapshot.py fetches

One run does the whole fetch:

- Accounts once.
- Positions and balances once per account. SnapTrade allows 10 calls/minute per account.
- One batched Yahoo download for prices and day changes.
- One batched Yahoo download for ~5 weeks of closes, which gives the 1w/1m change per position.
- A holding with no public quote (such as a 401(k) trust) borrows its day, 1w and 1m moves from the retail ETF tracking the same index, matched by name in `summary.LOOKTHROUGH_PROXIES`. These are estimates: the position carries `day_change_proxy`, `DAY_CHANGE_ESTIMATED` names them, and they stay out of the movers. A holding nothing matches stays uncovered and appears in `PARTIAL_QUOTES`.
- A sector lookup served from a cache under the plugin data directory. The same cache supplies each symbol's quote type.
- `news`: up to three dated Yahoo headlines from the last 7 days for each of the day's movers, at most six symbols. `--no-news` skips them.

Its output is `summary.py`'s contract plus `as_of`, `sources` and `news`. The input and output contracts of `summary.py` are in its docstring.

## Cash and money-market funds

- Some brokers report a money-market core position (for example Fidelity's SPAXX) both as a holding and as account cash.
- `summary.py` counts it once by backing that value out of the account's cash.
- `totals.cash` stays settled cash.
- The amount backed out is on each account row as `cash_adjusted_for_money_market`.
- `totals.cash_like` is cash plus money-market fund positions. It is the number the Cash tile and the allocation cash bucket agree on.

## Concentration

- `concentration` carries a position-level HHI.
- When asset classes are known it also carries a `single_stock` view over stock positions alone, because a large position in a diversified fund is an allocation, not a concentration.
- The CONCENTRATED flag keys off the single-stock view.

## Sector look-through

- `sector_exposure` looks through ETF and mutual-fund holdings to their underlying sectors (Yahoo `funds_data.sector_weightings`, weighted by each fund's market value), alongside individual stocks.
- The stock-only `sector_weights` sits beside it, kept for backward compatibility.
- A fund's bond, cash and other share, and every money-market position, land in `not_sectorized.bonds_and_cash`.
- A holding with no sector data and no recognizable bucket (unbucketed by `asset_bucket`) lands in `not_sectorized.funds_without_data`, the same as a fund the bucket cannot place, so nothing is silently dropped.
- `SECTOR_LOOKTHROUGH_PARTIAL` fires when holdings with no sector data (institutional share classes, commodities, unknown quote types) plus the unattributed slices of partially described funds together exceed 2% of value. The flag message names each.
- An institutional index-fund share class Yahoo cannot identify at all (no quote type) is matched by name to a public proxy ETF (VOO, VXUS, BND or VTI) and looked through using that proxy's sector data. It is labelled `"SYM (via VOO)"` in `looked_through`.
- A failure fetching a proxy leaves the holding's own base sector data alone and adds `PROXY_LOOKTHROUGH_UNAVAILABLE`.

## Headline sources

`brief.py` runs `snapshot.py` in-process, then runs the other installed skills' scripts in parallel:

- watchlist check
- market indices and flows
- `edgar.py` per single-stock holding
- rebalancing breach check
- tax report
- dividends with yield context
- risk stress, and the journal review
- expected fund ex-dividend dates: Yahoo's calendar has no ex-dividend date for an ETF or mutual fund, so `snapshot.py --events` asks one batched dividend history for those funds and expects the next ex-date a year after the first payment on or after this day last year. A fund whose last payment is over 400 days old gets none. The row carries `projected: true` and the label "ex-dividend (expected, from last year's date)", and a 7-day headline reads "is expected to go ex-dividend around". Money-market funds are left out.
- debt picture: the next payment on each recorded loan or card. Statements are typed in by hand and often weeks old, so the statement's due date rolls forward a month at a time to the next date on or after today. No payment shows as past due. A payment due within 3 days is an alert and within 7 days a notice, and every account's next payment joins `events` as a `payment` row whose `label` gives the minimum and says when the date came from the monthly schedule.
- spending changes and recurring charges, and the ledger summary

Severity follows one rule. An alert needs a decision within days or marks a real loss or risk: a watchlist rule or journal stop that fired, a dividend cut, a band breach, a payment due within 3 days, a wash sale from the last 30 days that disallows $10 or more (lots sold the same day count as one sale), an index move of 2% or more, a VIX at or above the 95th percentile of its year. A notice is news that changes the picture: earnings within 7 days, a new filing, other market readings, risk, dividend and spending changes. Info is routine or standing: ex-dividend dates (the dividend arrives on its own), fundamentals flags, smaller or older wash sales, the day's market line.

Source-specific limits:

- Market's CFTC positioning headline only fires for index, rates, fx or volatility contracts with at least 26 weeks of history, with a plain-language contract title.
- Spending's new-recurring headline skips everyday categories (Groceries, Dining, Coffee, Transport, Fuel).

A source becomes a `coverage` row, and never fails the brief, when its skill is:

| Case | Examples |
|---|---|
| not installed | the skill directory is absent |
| not set up | no targets, empty ledger, no statements, `EDGAR_USER_AGENT` unset |
| slow | over `--timeout` (default 90 s per source) |
| broken | the script failed |

## Headline answers (enrichment)

After the sources run, an enrichment phase fills in `answer`:

| Headline | Where the answer comes from | Extra call |
|---|---|---|
| EX_DIVIDEND | the dividends result already fetched | none |
| EARNINGS | options expected move | one `chain.py` call |
| 10-Q/10-K FILING | risk-factor diff | one `filing.py` call |

- At most 6 calls in total, against one phase deadline equal to the per-source timeout.
- A call that fails or times out, or the deadline passing, leaves the answer as the extractor set it.
- Enrichment never touches flags or coverage.

## What the page shows

`render.py` turns a saved `snapshot.py` or `brief.py` result into one self-contained HTML page for the Artifact tool:

- a one-line intro with a "How to read this page" walkthrough, and hover explanations for every financial term
- stat tiles for the totals, at the top
- a headline analysis card under the tiles when `--summary` is given: text the model wrote, limited to 20 words for the headline, 90 for each of the two paragraphs and 70 for the fold (`second_opinion/summary_card.py`). It is the one part of the page whose numbers are not rendered from the JSON. When the summary names a `chart`, the chart sits to the right of the text (below it on a narrow screen), drawn from the snapshot: `day_split` (the single stocks' summed day change, `concentration.single_stock.day_change`, against the rest of the day), `top_movers` (the four largest dollar gains and losses), `vs_market` (the day's percent move against SPY, QQQ and DIA from the history's last two closes; needs `--history`) or `mix` (the allocation buckets as one bar)
- accounts
- an allocation donut by bucket (bonds, US equities, international equities, cash, other), with sector exposure looked through ETFs and mutual funds
- a sortable holdings table with account filter and search; each row opens a detail panel (what the holding is, one-year price chart, links to the quote page, SEC filings and the company site)
- movers on one scale from the largest gain to the largest loss, then events, the comparison block and flags
- a Headlines card with a collapsed coverage table when the input came from `brief.py`
- light and dark themes; no external scripts
