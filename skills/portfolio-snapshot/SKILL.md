---
name: portfolio-snapshot
description: Produces the daily brief of all connected accounts, with totals, top holdings, concentration, movers, flags and headlines from the other skills. Use when the user asks "how is my portfolio", for a summary or a daily brief. Analysis goes to portfolio-analysis.
---
Produces the standard portfolio snapshot as a daily brief: one script run, one fixed layout, no analysis of its own. Anything beyond the fixed layout belongs to another skill.

## Background

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
- **The page.** `render.py` turns the saved result into one self-contained HTML page for the Artifact tool. The page carries the accounts, holdings, allocation, movers, events and comparison sections.
- **More detail.** Read `references/how-figures-are-built.md` before answering how cash, concentration, sector exposure or a headline's `answer` was computed, why a source is missing from the headlines, or what the page contains.
- **Other skills.** Drift against targets, what to rebalance, a single holding's outlook and placing an order belong to the portfolio-analysis, trading or valuation skills. Follow-up questions about the numbers belong to portfolio-analysis.

## Scripts

Run with the Bash tool. All four scripts print JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-snapshot/scripts/brief.py" [snapshot.py flags...] [--no-headlines] [--timeout SECONDS] [--workers N]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-snapshot/scripts/snapshot.py" [--account ID ...] [--events] [--no-quotes] [--no-news] [--save] [--compare] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-snapshot/scripts/summary.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-snapshot/scripts/render.py" --in snapshot.json --out page.html
```

| Script | What it does |
|---|---|
| `brief.py` | The default run. The snapshot plus `headlines`, `coverage`, `brief_as_of` and `brief_seconds`. Every `snapshot.py` flag passes through. |
| `snapshot.py` | The whole fetch in one go: accounts, positions, balances, prices, sectors, movers' news. |
| `summary.py` | Pure math on data you already have. |
| `render.py` | Interactive page from a `snapshot.py` or `brief.py` result. Prints `{"out", "title", "positions", "flags", "headlines"}`. |

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
| 2 | Unknown account id, or (`render.py`) the input is not a snapshot result | Show `error`. |
| 4 | Credentials missing | Show the `hint`. |
| 4, code `ETRADE_REAUTH` | An E*Trade login is needed | Follow the session's broker-login rule: show the `url`, get the verifier code, run the connect skill's `etrade-login.py --verifier CODE`, rerun once. `--partial` runs without E*Trade. |
| 5 | SnapTrade or Yahoo error | Show the error. |
| 5, code `NO_ACCOUNTS` | Nothing is connected | Point to the connect skill. |
| 5, code `SNAPSHOTS_CORRUPT` | The saved-snapshots file is damaged | Show the `hint`. |
| 6 | Python dependencies missing | Show `requirements` / `install_log`. |

## Steps

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
   1. Run `render.py --in DIR/snapshot.json --out DIR/portfolio-snapshot.html`.
   2. Publish the HTML with the Artifact tool: icon dashboard, description "Portfolio brief as of DATE".
   3. On later runs republish the same file path, so the link stays stable.
   4. Reply with the page reply format below.
5. If the Artifact tool is not available (a headless or non-interactive host), reply with the markdown fallback format below instead.
6. For a `--compare` run, present the delta against the saved snapshot instead of re-rendering every section.
7. Offer the handoff. For each shown headline whose `ask` is non-empty, offer the `ask` verbatim. For anything else beyond the fixed layout, finish the snapshot first, then hand off to the skill named in Background.

## Reply format

### Page reply (the default, when the page was published)

In this order, then stop:

1. The artifact link on its own line.
2. One line: Total `totals.total_value` · Cash and money-market funds `totals.cash_like` (`totals.cash_like_pct`) · Day `totals.day_change` (`totals.day_change_pct`, covers `totals.day_change_coverage` of holdings) · Unrealized `totals.unrealized_pnl`
3. Headlines, only when `headlines` is present:
   - The line "Headlines (N new):", where N is the count of `status == "new"`. Write "Headlines: none today" when the list is empty.
   - At most five bullets, in the script's order.
   - Each bullet reads "SEVERITY title — answer". The prefix is the severity in caps for alerts, `NEW` for new notices, and nothing for the rest. Then the `title`. Then " — " and the `answer`, when it is non-empty.
4. One line "Sources: X of Y checked, Z skipped" from `coverage`, only when any source was skipped or failed. Do not list skipped or failed sources by name in chat; the page's coverage table has them.
5. **Flags** — one bullet per `flags[].message`, or "None".

The session's standing "Next you could ask:" block draws its questions first from the shown headlines whose `ask` is non-empty.

Do not repeat the sections the page carries. If the user asks for a number the page shows, read it from the script's JSON.

### Markdown fallback (only when the Artifact tool is unavailable)

Render the script's JSON in exactly this order, then stop.

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
2. **Top holdings** — table from `top_holdings`: Symbol · Name · Units · Price · Value · Weight · Unrealized P&L · Day % · 1w % · 1m %.
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

## Rules

- Every number and every headline comes from the script. Do not recompute or add figures.
- Never run `brief.py` or `snapshot.py` twice in one answer. The one rerun after an E*Trade login is the only exception.
- Do not run accounts.py, portfolio.py, or quote.py as well. The snapshot already contains that data.
- Publish the page or write the markdown fallback, never both.
- No commentary, bull/bear framing, or opinions outside the Flags section.
- Quotes are delayed, not live. Say so plainly if the user asks for "live" prices.
- A news story under a mover is dated context for the move, never stated as its cause.
- If the user asks a follow-up question about the numbers, switch to the portfolio-analysis skill.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
