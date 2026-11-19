# Performance vs. index chart on the portfolio summary — design

Date: 2026-11-18
Status: draft, awaiting approval

## Intent

Add a line chart to the portfolio summary page (`render_brief.py`) showing how the
portfolio has actually performed against the S&P 500, Nasdaq and Dow. "Actually"
means true total return: dividends, interest, realized gains and losses and price
moves all count; deposits and withdrawals do not (adding money is not a gain).
The user can view the combined portfolio or pick a single account.

## Goals

- One combined line for all connected accounts, plus an account picker that
  redraws the chart for one account.
- Benchmarks: SPY (priority), QQQ (Nasdaq-100 proxy), DIA (Dow proxy), each as
  total return with dividends reinvested.
- Range buttons: 1M, 3M, YTD, 1Y, All. Every line rebased to 0% at the start of
  the selected range, so lines are comparable.
- History from every connected broker: E*Trade direct where connected,
  SnapTrade for the rest, plus any CSV statements already imported.
- A headline number per range: portfolio return vs. SPY return, in percentage
  points.

## Non-goals

- No new data sources beyond what `statement-import` already uses. The chart
  only tops up the ledger with activity newer than its last sync (see
  "Ledger top-up"); a full history import is still `statement-import`'s job.
- No tax view, per-holding attribution, or risk metrics on this chart.
- No change to `brief.py` / the daily check-in path; it stays at its ~10 s budget.
- No on-disk cache of daily values (approach C was rejected).

## Anti-goals (would make this a failure even if it runs)

- A line that is quietly wrong. Where the rebuild cannot reconcile, the chart
  stops at that date, or the account is left out, with a flag. It never draws
  a guess.
- Counting deposits as performance, or comparing the portfolio's total return
  against price-only indexes.

## Constraints

- Brokers report current positions only; history comes from `ledger.json`
  (`<plugin data dir>/ledger.json`, normalize.py's transaction contract).
- SnapTrade and E*Trade both serve about 2 years of activity, so "All" usually
  means about 2 years, or longer for an account imported from older CSVs.
- Prices: `market.close_histories(symbols, start)` gives one batched Yahoo
  download with `close` (split-adjusted, not dividend-adjusted) and `adj_close`
  (split- and dividend-adjusted) per day.
- Follow the existing split: pure math script reading JSON on stdin; a fetching
  `_report` script; exit codes 0/2/4/5/6; ETRADE_REAUTH / `--partial` handling
  as in `performance_report.py`.

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| **A (chosen)** | Separate history step (`history.py` + `history_report.py`) whose output is passed to `render_brief.py --history`. Runs on a portfolio summary, not on check-in. | Summary takes a few seconds longer for the 2-year price download. Always fresh, testable, matches existing patterns. |
| B | Compute inside `brief.py` | Chart on every brief, but would roughly double the brief's ~10 s budget every day. |
| C | Store daily values on disk, append incrementally | Fastest after the first run, but re-imports and split fixes make the stored history stale, and invalidating it is a whole class of silent-error bugs. |

The user picked A.

## Design

### Method

**Ledger top-up (user-confirmed intent: no quietly wrong line).** Before
rebuilding, `history_report.py` pulls activity for every open account from the
day after its newest ledger entry to today, using `sync-broker.py`'s logic
(router: E*Trade direct where connected, SnapTrade otherwise), and merges it into
the ledger. This closes the gap where a recent buy or deposit the ledger hasn't
seen would carry back through history undetected. An account with no ledger
entries at all is never rebuilt; it is excluded with `NO_HISTORY` and the
`statement-import` command to run.

**Account identity (builder-check call).** Ledger rows are matched to live
accounts after folding ids: rows under an E*Trade-direct id and its SnapTrade twin
(`router.merge_accounts` / `_shadowed_by` / `_numbered_as`) are mapped onto the
live id, then deduplicated on (date, type, symbol, units, amount) ignoring
account_id. Rows matching no open account (e.g. CSV imports with a free-form or
null `--account`) are ignored and counted in an `UNASSIGNED_ROWS` flag.

**Cash-like and unlisted holdings.**
- Money-market funds the snapshot treats as cash-like (SPAXX, MVRXX, FDRXX,
  FCASH and whatever `snapshot.py`/`holdings.py` already classify that way) are
  valued as cash at $1.00/unit. Their units are not rolled through trades; sweep
  moves are usually absent from the ledger.
- Unlisted funds with a public proxy (the `day_change_proxy` mapping
  `snapshot.py` already uses, e.g. ONMZ→BND, ONN5→VOO, ONMY→VXUS in the
  Amazon 401(k)) get a synthetic price history: today's broker price scaled back
  by the proxy's daily `adj_close` returns. **The user chose this over excluding
  the 401(k).** Any series containing a proxied holding is marked
  `estimated: true`, and the page labels it "estimated via BND/VOO/VXUS".
- Any other symbol with no price on a day it is held (options, bonds, CDs) is a
  break as below, unless its value is under 1% of the account on that day, in
  which case it is carried at its last trade or broker price with an
  `UNPRICED_HOLDING` flag.

**Rebuild backward from today.** For each account, start from today's positions
(units per symbol) and cash (from `router.get_balance`, as `snapshot.py` reads it),
then walk the ledger from newest to oldest and undo each transaction to get
end-of-day holdings for every earlier trading day:

| Type | Undo (going back in time) |
|---|---|
| BUY | units −= u; cash −= amount (amount ≤ 0, so cash goes up) |
| SELL | units += u; cash −= amount |
| DIVIDEND, INTEREST, FEE | cash −= amount |
| DEPOSIT, WITHDRAWAL | cash −= amount; also recorded as an external flow |
| TRANSFER_IN/OUT with symbol | units ∓= u; external flow at that day's close × u |
| TRANSFER_IN/OUT cash only | treated like DEPOSIT/WITHDRAWAL |
| SPLIT | see below |
| OTHER | cash −= amount when present; counted in a flag |

Reinvested dividends appear as a DIVIDEND plus a BUY, so they need no special case.

**Splits (builder-check call: detect, don't assume).** Yahoo `close` is in
today's split terms, so units are kept in today's split terms throughout. Brokers
differ in how they record pre-split activity (as traded, or rewritten into
post-split terms), and SPLIT rows may carry a share delta in `units`
(`reconcile.py` reads them as adding `units × split_ratio`). Split ratios come
from the SPLIT row, falling back to Yahoo's split history (one `actions=True`
download) when the ratio is null or the row is missing. For each split, the
rebuild tries both readings of pre-split units (as traded → multiply by later
ratios; already adjusted → leave) and keeps the one under which units never go
negative and the share count across the split date is continuous (matching the
SPLIT row's delta when present). If neither or both fit ambiguously, that is a
`HISTORY_BREAK` at the split date. This catches reverse splits, where negative
units alone would not.

**Daily value.** V(d) = cash(d) + Σ units(d, s) × close(d, s). Days with no
close (holiday or listing gap) carry the last close forward. A symbol with no
price at all is a reconciliation failure (below).

**Return: time-weighted, chained daily.** For day d with external flow F(d)
(deposits +, assumed at end of day):
r(d) = (V(d) − F(d)) / V(d−1) − 1. Cumulative index I(d) = Π(1 + r). Combined
portfolio: sum V and F across included accounts per day, then chain the same
way (not an average of per-account returns). Time-weighted is the standard way
to compare against an index, because it removes the effect of when and how much
money was added.

**Benchmarks.** Cumulative from `adj_close`: I(d) = adj_close(d) / adj_close(start).

**Rebasing per range** happens on the page: divide each series by its value on
the first day of the range.

### Reconciliation (the "never draw a guess" rule)

Per account, while walking backward, any of these marks a break date:
- units for a symbol go negative by more than a rounding tolerance
  (|units| > 1e-6 and > 0.1 % of the max held), meaning a missing buy or transfer
- a symbol held on a day with no price available
- cash goes below −(5 % of account value) on an account not flagged as margin
- the oldest ledger entry is later than today minus the range (just shortens "All")

On a break, that account's series starts the day after the break, with a
`HISTORY_BREAK` flag naming the account, date, symbol and reason. The combined
line starts at the latest start among included accounts, so it always covers the
same accounts end to end, and the flag says so. If an account's history is
shorter than 30 days, it is left out of the combined line and listed in a flag.

### Scripts

`skills/portfolio-analysis/scripts/history.py`: pure math, stdin → stdout.

Input:
```json
{
  "as_of": "YYYY-MM-DD",
  "accounts": [{"account_id": "...", "name": "...", "cash": 0.0,
                "positions": [{"symbol": "AAPL", "units": 10.0}]}],
  "transactions": [ /* ledger entries, normalize.py contract */ ],
  "prices": {"AAPL": [{"date": "...", "close": 1.0, "adj_close": 1.0}]},
  "splits": {"AAPL": [{"date": "...", "ratio": 4.0}]},
  "benchmarks": ["SPY", "QQQ", "DIA"]
}
```

Output:
```json
{
  "as_of": "YYYY-MM-DD",
  "series": [
    {"key": "combined", "label": "All accounts", "start": "...",
     "points": [["YYYY-MM-DD", 1.0, 12345.67]]},   // date, cumulative index, value
    {"key": "<account_id>", "label": "<account name>", "start": "...", "points": [...]}
  ],
  "benchmarks": [{"symbol": "SPY", "label": "S&P 500", "points": [["YYYY-MM-DD", 1.0]]}],
  "excluded": [{"account_id": "...", "reason": "..."}],
  "flags": [{"code": "HISTORY_BREAK|SHORT_HISTORY|LEDGER_EMPTY|NO_HISTORY|UNASSIGNED_ROWS|UNPRICED_HOLDING|PROXY_PRICED|BROKER_UNAVAILABLE|BENCHMARK_UNAVAILABLE|OTHER_TYPES", "message": "..."}]
}
```

`skills/portfolio-analysis/scripts/history_report.py [--since YYYY-MM-DD] [--partial]`:
loads the ledger, reads positions and cash for every open account through the
router (E*Trade direct / SnapTrade), works out the symbol set (held today plus any
symbol in the ledger within the window), does one `close_histories` call for
those symbols plus SPY/QQQ/DIA from the oldest ledger date, plus the split
lookup, pipes everything into `history.py`'s logic, and prints the result with
`sources`. An empty ledger exits 0 with `LEDGER_EMPTY` and the
`statement-import` command to run. The top-up runs first; if it cannot reach a
broker (`--partial`, or a sync error), that broker's accounts are excluded with
`BROKER_UNAVAILABLE` rather than drawn from a possibly stale ledger.

### Page (`render_brief.py`)

- New optional `--history history.json`. Without it the page is unchanged.
- New card "Performance vs. the market" placed directly after the headline tiles.
  - Account picker: "All accounts" plus one entry per series (excluded accounts
    shown disabled, with the reason as a tooltip).
  - Range buttons 1M · 3M · YTD · 1Y · All (buttons beyond the data's span disabled).
  - Lines drawn with the existing `F.lines` helper: portfolio solid in the first
    series colour, SPY, QQQ and DIA in the next three, y-axis as % return
    from the range start, x as dates.
  - A line above the chart: "Your portfolio +8.2% · S&P 500 +11.0% · −2.8 pts"
    for the selected account and range.
  - Flags from `history.json` join the page's existing flags section.

Text sketch:
```
Performance vs. the market          [All accounts ▾]  1M 3M YTD [1Y] All
Your portfolio +8.2%   S&P 500 +11.0%   Nasdaq +14.1%   Dow +7.5%
  %|                                   ___Nasdaq
   |                          ___/‾‾‾‾
   |           ___/‾‾‾\__/‾‾‾ ___S&P
   |  ___/‾‾‾‾/   ___/‾‾‾‾‾‾‾  ___You
   |_/___/‾‾‾‾‾‾‾‾                ___Dow
   +-------------------------------------- date
```

### Skill docs (`SKILL.md`)

- Scripts table: add `history_report.py` and `history.py`.
- "How is my portfolio / summary" steps: run `history_report.py` alongside
  `snapshot.py`, write `DIR/history.json`, pass `--history` to `render_brief.py`.
  If it exits 4 (ETRADE_REAUTH), follow the existing login handoff. If it fails
  otherwise, render without the chart and list the reason in flags.
- Check-in and the daily brief do not run it.
- Reply format: one line with the 1Y (or All, when history is shorter)
  portfolio-vs-SPY figure.

### Tests

- `history.py` unit tests with hand-built fixtures: buys/sells only; dividend and
  interest income raising the return; a deposit that must not move the return;
  a withdrawal; a split with and without a ledger ratio; a transfer-in of shares;
  a missing buy that triggers `HISTORY_BREAK`; combined line over two accounts
  with different start dates; benchmark rebasing from `adj_close`; a reverse
  split recorded each way; a proxied unlisted fund marking the series
  estimated; money-market units treated as cash; twin account ids folded and
  deduplicated.
- `history_report.py` top-up test: activity newer than the ledger is merged
  before the rebuild.
- `history_report.py` tests using the existing fakes (`tests/fakes.py`) for broker
  and market, including the `--partial` E*Trade path.
- A render test (`tests/page_dom.py`) that the card, picker and range buttons
  appear with `--history`, and the page is byte-identical without it.

## Calls made in design (flagged for the user's review)

- Ledger top-up before every rebuild (writes to the ledger).
- Twin-id folding and cross-id dedupe; unassigned CSV rows ignored with a flag.
- Money-market funds valued as cash.
- Split convention detected per split; ambiguity is a break.
- Small (<1%) unpriced holdings carried with a flag; larger ones break.

## Calls left to the builder

- Exact tolerances above may be tuned if the user's real ledger trips them falsely.
- Colour order and chart height, using the existing palette.
- Whether the split lookup reuses `dividend_histories`-style `actions=True` or a
  new helper.
