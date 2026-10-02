# How the brief's figures are built

Detail behind the fields `snapshot.py`, `summary.py` and `brief.py` print, and what `render.py` puts on the page. `SKILL.md` has the procedure; this file answers "how was that number computed" and "why is that headline there".

## What snapshot.py fetches

One run does the whole fetch:

- Accounts once.
- Positions and balances once per account. SnapTrade allows 10 calls/minute per account.
- One batched Yahoo download for prices and day changes.
- One batched Yahoo download for ~5 weeks of closes, which gives the 1w/1m change per position.
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
- risk stress
- journal review
- debt picture
- spending changes and recurring
- ledger summary

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

- a one-line intro with a "How to read this page" walkthrough
- hover explanations for every financial term, with links to more
- stat tiles
- accounts
- an allocation donut by bucket (bonds, US equities, international equities, cash, other), with sector exposure looked through ETFs and mutual funds
- a sortable holdings table with account filter and search; each row opens a detail panel (what the holding is, one-year price chart, links to the quote page, SEC filings and the company site)
- movers, events, the comparison block, flags
- a Headlines card with a collapsed coverage table when the input came from `brief.py`
- light and dark themes; no external scripts
