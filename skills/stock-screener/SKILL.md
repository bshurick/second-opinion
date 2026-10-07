---
name: stock-screener
description: Screens US filers on growth, value, quality, GARP, magic-formula, Graham or payout presets, checks past picks, or runs a deep pick with industry news and deep valuation. Use when asked to find stocks, for growth or value ideas or best opportunities.
---
Takes a person from "no list" to one to three researched companies. It screens every US filer on a preset's tests, can check the same screen against history, and then walks a five-step research funnel whose later steps hand off to the fundamental-research and valuation skills.

Its deep picker mode adds an industry scan, quick reads of each candidate and deep valuation of the finalists, and surfaces only the finalists that pass a downside test.

## Background

### What the scripts do

- `screen.py` scans every US filer with XBRL financials, applies a preset's business tests, prices the survivors from Yahoo, and ranks them the way the preset says.
- The data is four fiscal years of revenue, margins, cash flow, capital spending, stock pay, share counts and payouts, two year-end balance sheets, and the latest reported quarter.
- It comes from SEC EDGAR "frames", where one request covers every company. A first run downloads about 180 frames (under a minute), cached a day.
- `screen.py` needs `EDGAR_USER_AGENT` set, like fundamental-research.
- `screen.py` prints the `funnel`, `fail_counts`, `survivors` (ranked), `near_misses`, `criteria`, `priced`, `coverage` and `flags`. `--all` adds every screened company.
- `lookback.py` runs the same screen as of an earlier year and shows what its survivors did since.
- `screen_math.py` is the shared math. Its docstring is the contract: every criterion, the presets, the missing-data rules, the flags.
- `screen.py --symbols SYM,SYM` screens only those tickers and reports each one in `checked` (`passed`, `failed`, `financial`), with `not_found` (no SEC filer) and `incomplete` (too little filing history).
- `gate.py` applies the deep picker's downside gate to the finalists' deep valuations.
- `render_pick.py` builds the deep picker's page.

### Presets (`screen_math.PRESETS`)

| Preset | Business tests | Price tests | Ranked by |
|---|---|---|---|
| `growth` | revenue ≥ $500M, 3-yr growth ≥ 20%, no year < 10%, last year ≥ 15%, latest quarter ≥ 10%, gross margin ≥ 40%, operating margin improving, FCF positive, share growth ≤ 5% | market value ≥ $1B | gap (expected growth − growth the price implies) |
| `value` | revenue ≥ $500M, not shrinking, latest quarter no worse than −5%, FCF margin ≥ 5%, FCF positive every year, share growth ≤ 2%, net debt ≤ 3× operating profit, Piotroski score ≥ 5 | market value ≥ $1B, cash yield ≥ 6%, P/E ≤ 15 | cash yield |
| `quality` | revenue ≥ $1B, growth ≥ 8%, latest quarter not shrinking, return on capital ≥ 15%, FCF every year, share growth ≤ 1%, net debt ≤ 3× operating profit | market value ≥ $2B, gap ≥ 0 | gap |
| `garp` | revenue ≥ $500M, growth ≥ 12%, latest quarter ≥ 8%, operating margin ≥ 10%, FCF every year, share growth ≤ 3% | market value ≥ $1B, P/E ≤ 25, gap ≥ 3 points | gap |
| `magic` | revenue ≥ $500M, return on capital ≥ 15%, FCF positive; utilities left out | market value ≥ $1B, earnings yield ≥ 0 | Greenblatt's magic formula: rank on earnings yield plus rank on return on capital, lowest sum first |
| `graham` | revenue ≥ $500M, not shrinking, profit and a dividend every year, current ratio ≥ 2, debt within working capital | market value ≥ $1B, P/E ≤ 15, P/E × P/B ≤ 22.5 | P/E × P/B, lowest first |
| `payout` | revenue ≥ $500M, not shrinking, FCF every year, share count not growing, net debt ≤ 3× operating profit, payout covered by FCF | market value ≥ $1B, dividends plus buybacks ≥ 4% of market value | payout yield |
| `health` | revenue ≥ $250M, shrinking no more than 5% a year, Piotroski score ≥ 4, share growth ≤ 5%, net debt ≤ 4× operating profit, average FCF margin ≥ 0 | none | Piotroski score |

- `value`, `quality`, `magic` and `payout` leave out real estate, where free cash flow misstates the business.
- `graham` is his defensive rule unchanged and often returns nothing in an expensive market. The funnel shows which test emptied it. The usual loosening is `--set min_current_ratio=1.5` or `--set max_pe_times_pb=none`.
- `magic` returns a long ranked list by design. Work from the top 20 to 30.
- `fcf_basis` defaults to free cash flow **after** stock pay. `--set fcf_basis=fcf` switches that off.

### How the price figures are built

- **Cash figure.** The lower of last year's free cash flow and the four-year average margin applied to last year's revenue, so one peak year does not make a company look cheap.
- **Expected growth.** It starts from the lower of the three-year rate and recent growth (latest year, averaged with the latest quarter) and fades to 3% over ten years.
- **Gap.** Expected growth minus the growth the price implies.
- **No capital-spending figure.** The company has no free cash flow and fails the cash tests. It does not pass on operating cash flow.

### What `lookback.py` reports

- It dates the screen 1 July after `--year` (default three years back) and prices it as of that day.
- It reports each survivor's total return since against the benchmark, the share that beat it, top-half against bottom-half of the ranking, and the rank correlation.
- Its caveats: it is one period, companies delisted since are missing, and past value is approximated.

### Company flags

| Flag | Meaning |
|---|---|
| `CASH_OUTRUNS_PROFIT` | Free cash flow after stock pay runs more than 15 points above the operating margin (customer float or working-capital timing). The price figures are meaningless. |
| `LARGE_MINORITY_INTEREST` | More than 10% of net income belongs to minority partners, so consolidated cash yield overstates the shareholders' share. Informational; name it. |
| `CORPORATE_ACTION` | The priced share count differs from the latest filed diluted count by more than a quarter to a third (spin-off or reverse split) with no split detected. The price figures are meaningless. |
| `MISSCALED` | The filer tagged a figure with the wrong scale; it was dropped. The price figures are meaningless. |
| `PROFIT_ABOVE_OPERATING_PROFIT` | A one-off gain flatters the P/E. |
| `CASH_ABOVE_ITS_AVERAGE` | Last year's cash margin is more than 10 points above the multi-year average; the average was used. |
| `ACQUISITIVE` | Growth partly bought. |
| `PRICE_FALLING` | The 12-month price change is below −20%. |
| `LATEST_QUARTER_NOT_REPORTED` | The most important test was not applied. |

### Two modes

| The person says | Mode |
|---|---|
| "find stocks", "screen for value", a preset by name | The funnel |
| "deep pick", "best opportunities", "find me the best stocks", "deep screen" | The deep picker |

### The deep picker

- **Pipeline.** An industry scan and the financial screen run side by side. Their candidates are merged and health-checked, quick reads score each one, and three to five finalists get a deep valuation (the valuation skill's deep mode).
- **The gate (`gate.py`).**
  - A finalist passes when no deep-valuation scenario loses money over five years, dividends included (`floor`, default 0%), and the central (first) scenario earns at least the hurdle (`hurdle`, default 10%) a year at today's price.
  - `pass_flagged` means it passed while every scenario sits above the price, so a downside case may be missing.
- **Size.** A run with three finalists (the default) dispatches roughly 30 to 40 subagents and plans about 160 of the session's web searches, most of them inside deep valuation.
- **The run folder `DIR/pick-DATE/`:**

  | Path | Holds |
  |---|---|
  | `screen/` | `screen.py` output for each preset run and the health check |
  | `industries/<group>.json`, `.md` | The industry scanners' findings |
  | `context/macro.md` | The dated macro picture the coordinator writes before the scanners start |
  | `pool.json` | The merged candidate list with each one's origin and health |
  | `cards/<TICKER>.json`, `.md` | The quick reads |
  | `gate.json`, `pick.json`, `page.html` | `gate.py`'s input and output, and the page |

  - Each finalist's deep valuation keeps its own `DIR/deep-SYMBOL/` folder and page.

### Reference files

- `references/picker-roles.md` holds the brief for each deep-picker subagent: Shared rules, Industry scanner, Quick reader. Name its absolute path and the two sections in each prompt.
- `references/primary-sources.md` catalogs the dated government, trade-body and macro pages the subagents fetch before they search. A subagent reads it, and the coordinator reads it for `context/macro.md`.

### Limits

- Figures are XBRL tags computed one uniform way. Companies' own reported or adjusted figures can differ, and some filers tag with the wrong scale (dropped and flagged `MISSCALED`).
- Annual frames align fiscal years to calendar years. The latest quarter is the most recent of the two listed in `latest_quarter_periods` that the company reported.
- Foreign filers (20-F/6-K) usually have no quarterly XBRL, so their latest-quarter test is `not_reported`, not passed, and they carry `LATEST_QUARTER_NOT_REPORTED`.
- Early in the year most companies have not filed the latest fiscal year and are left out. The `LATEST_YEAR_THIN` flag says so and names the `--year` to use instead.
- Companies with fewer than four years of filings (recent listings) are never screened.
- Banks, insurers and lenders are set aside: their cash flow includes customer money.
- Under `--no-price`, only filers whose XBRL shows deposits, loans or premiums are set aside as financial. Asset managers, brokers and BDCs are recognized only once Yahoo prices them, so a `--no-price` health check tests them like any other company.
- Balance-sheet figures (debt, cash, capital employed) are from the latest fiscal year end, so they can be most of a year old.
- Debt is the largest total-debt figure a company tags. A company tagging neither debt nor interest is taken as debt-free.
- P/E uses the latest fiscal year's reported net income, one-off gains included.
- "Price implies" is arithmetic on today's enterprise value at a 10% discount rate and 3% terminal growth, not a forecast. A large gap is a question (why does the market doubt the growth), not an answer.
- Yahoo limits how many quotes it serves. `PRICING_INCOMPLETE` means wait a few minutes and rerun.

## Scripts

Run with the Bash tool. Scripts print JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/screen.py" [--preset growth|value|quality|garp|magic|graham|payout|health] [--set KEY=VALUE ...] [--year YYYY] [--no-price] [--price-limit N] [--held SYM,SYM] [--exclude-held] [--all] [--symbols SYM,SYM]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/lookback.py" [--preset NAME] [--set KEY=VALUE ...] [--year YYYY] [--price-limit N] [--benchmark SPY]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/screen_math.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/render.py" --in screen.json --out page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/gate.py" < DIR/pick-DATE/gate.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/render_pick.py" --in DIR/pick-DATE/pick.json --out DIR/pick-DATE/page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/sentiment.py" SYM[,SYM...] [--days 20] [--news-days 30] [--news 10]
```

| Script | What it does |
|---|---|
| `screen.py` | Screens the whole market on a preset, prices the survivors and ranks them. `--set` overrides one criterion; a value of `none` switches it off. `--year` is the latest fiscal year. `--no-price` stops after the business tests. `--price-limit` caps how many survivors are priced. `--held` marks symbols already owned and `--exclude-held` leaves them out. `--all` adds every screened company. |
| `lookback.py` | Runs the screen as of an earlier year and reports what its survivors did since against `--benchmark`. |
| `screen_math.py` | Pure math on a JSON input. |
| `render.py` | Turns a `screen.py` result into one HTML page for the Artifact tool. |
| `gate.py` | The deep picker's downside gate: `pass`, `pass_flagged` or `fail` per finalist, with reasons. |
| `render_pick.py` | The deep picker's page: picks, near misses, funnel, industry map, candidates. |
| `sentiment.py` | Per symbol, FINRA daily short-sale volume (not short interest) and dated Yahoo headlines, with flags when either is missing. |

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad input | `error` |
| 5 | EDGAR or Yahoo error | `hint` |
| 6 | Python deps missing | the error |

## Steps

Pick the case that matches the request.

**The user wants companies to look at (the funnel)**

The funnel has five steps, in order. Say which step you are on.

1. **Screen** (this skill).
   1. If a brokerage is connected and the portfolio-analysis skill is installed, get the held symbols first (its aggregate report) and pass `--held SYM,SYM`. Survivors already owned are marked. Add `--exclude-held` when the person wants new names only.
   2. Pick the preset that matches the ask. Translate the person's words into `--set` overrides; do not invent a preset:

      | The person says | Override |
      |---|---|
      | "bigger companies" | `--set min_revenue=2e9` |
      | "don't care about dilution" | `--set max_share_growth=none` |
      | "cheaper" | `--set max_pe=12` |
      | "nothing that is still falling" | `--set min_momentum=0` |
      | "no energy" | `--set exclude_sectors=Energy` |
      | "only improving businesses" | `--set min_f_score=7` |

   3. Run `screen.py` once.
   4. If the survivors number fewer than about 5 or more than about 60, loosen or tighten with `--set` and rerun. Name the test that did the most narrowing (the biggest drop in `funnel`).
   5. Write `screen.py`'s output to `DIR/screen.json` (DIR is the session scratchpad) and run `render.py --in DIR/screen.json --out DIR/screen.html`.
   6. Publish it with the Artifact tool: icon table, description "Stock screen: PRESET as of DATE". Republish the same path on later runs.
   7. Reply with the screen format below.
   8. In that reply, if the portfolio brief shows one sector above about a quarter of the portfolio, say which survivors would add to it. Each survivor carries its `sector`.
2. **Shortlist.**
   1. Pick 5 to 8 survivors for research with the person, or by the rank when they leave it to you.
   2. Drop a survivor from the shortlist when its flags make the price figures meaningless (`CASH_OUTRUNS_PROFIT`, `MISSCALED`, `CORPORATE_ACTION`), and say so.
   3. Name the other flags beside the company, with the meaning from the Company flags table.
3. **Read the story** (fundamental-research).
   1. For each shortlisted company run `edgar.py SYMBOL --quarters 6 --form4 5`.
   2. Read the 10-K risk-factor diff and the latest quarter's MD&A with `filing.py`.
   3. With several companies, research each in its own parallel task. Give every task its own output file names so none overwrites another.
   4. Each returns: revenue by year and latest-quarter growth, margin and stock-pay trend, share count, net cash, red-flag screens, and insider buys and sells.
   5. Each also returns: what is new in the risk factors, the quarter's growth drivers and guidance, a bull and a bear case, and one line on why the market may doubt the growth.
   6. Put the results side by side, **latest-quarter growth first**. Annual figures lag, and a quarter that has already turned is the most common reason a screen survivor fails here.
4. **Price check** (valuation).
   1. For the two to four that survive step 3, run `dcf.py` with a ten-year `stage1_growth` path for a bear, a base and a bull case, and `current_share_price` for the implied growth.
   2. Challenge `inputs.py`'s defaults: its discount rate can be too low for a concentrated or volatile company.
   3. A company whose price sits at or above its base case has no margin of safety on these assumptions. Say which ones pass on that test.
5. **Write it down** (trade-journal, when installed): thesis, what would prove it wrong, planned size, before any order.

**The user wants the best opportunities (the deep picker)**

1. Run `edgar.py` from the fundamental-research skill on any ticker. If it exits 4, stop, say the deep picker needs SEC EDGAR, and offer the funnel.
2. Make `DIR/pick-DATE/` and its `context/`, `screen/`, `industries/` and `cards/` folders.
   - When a brokerage is connected, take held symbols and sector weights from the portfolio-snapshot brief.
   - Note the profile, and any theme or sector limit the person gives.
3. Tell the person the run has started, and its size from Background.
   - Write `budget.json` in the run folder. The session has one shared pool of about 200 web searches, so plan at most 160 and keep 40 in reserve. Every plan below sums to 160 or less:

     | Finalists | Industry scanners | Quick reads | Each deep valuation |
     |---|---|---|---|
     | 3 (default) | 10 each, 30 | 40, split over the pool (2 per company up to 20 names, else 1) | 30 (Industry and news 4), 90 |
     | 4 | 10 each, 30 | 40, as above | 22: round-1 roles only, threads from what is left (88) |
     | 5 | 10 each, 30 | 1 per company, at most 25 | 18 (90) |

   - The 3-finalist row totals 160 (30 + 40 + 90) with 40 in reserve. The 4-finalist row totals 158 and the 5-finalist row 145, so each stays within 160 with 40 in reserve.
   - Ask before a plan above 160. Run the picker in a session that has not spent its searches on other work.
   - After each agent returns, add the searches it used. If the plan runs short, cut thread rounds first, then the number of finalists. Never let a stage start without its share.
4. Write `context/macro.md` in the run folder before dispatching the scanners. Fetch from the rows of `references/primary-sources.md`, and date each line:
   - the 10-year Treasury yield from FRED (DGS10)
   - the oil and gas outlook from EIA STEO
   - the retail sales and CPI headlines from Census and BLS
   - Write the file's own date at the top. Every scanner and quick reader reads it, so they start from one dated macro picture instead of spending searches on it.
5. In parallel:
   - Dispatch three Industry scanner agents (general-purpose), one per sector group in `references/picker-roles.md`. Each prompt names the brief's path and its two sections, the run folder, today's date, the group, its search cap, and the resolved script commands.
   - Run `screen.py` with the preset that matches the profile: `value` then `quality` for a value investor, `garp` for growth. Write each output into `screen/`.
6. Merge into `pool.json`:
   - the leaders of favored and contrarian industries
   - screen survivors whose industry is not unfavored
   - drop duplicates, aiming for 20 to 25 names (at most 40 when the person asks for a wider pool, with 1 quick-read search per company)
   - mark held names
7. Run `screen.py --symbols … --preset health --no-price --held …` on the pool.
   - Drop the names that fail, and keep each one's failed tests for the page.
   - Keep financial filers, `not_found` names and `incomplete` names (no US-GAAP history for the four years screened: too new, or files IFRS, like many foreign leaders). Their quick read judges their health, and the reply's Flags list them.
   - `checked` gives each ticker as requested with its `primary` ticker; a second share class or a dotted ticker (BRK.B) resolves to its filer.
   - Treat a health failure for an asset manager, broker or BDC (the industry scan's Financials names) as "judge in the quick read", not a drop: the cash tests misread their balance sheets.
8. Dispatch Quick reader agents with about five companies each, two or three agents at a time. Each prompt states the search cap per company from `budget.json`.
9. Rank the cards by their four scores with judgement, and choose three finalists, or up to five when the person asks and the budget table allows:
   - at least one contrarian when one survives
   - no more than two from one industry
   - held names allowed, and marked
10. Run the valuation skill's **Deep** steps on the finalists, two or three at a time, each with its share of `budget.json`. Each finalist gets its own `deep-SYMBOL` folder and a published page. Pass each finalist's industry object (from `industries/<group>.json`) and its `industries/<group>.md` notes into its deep valuation, for the Industry and news role.
11. Write `gate.json` with each finalist's `model.py` and `returns.py` output, its price (the same price `returns.py` used) and its https page link, plus `hurdle` and `floor` when the person changed them. Run `gate.py`.
12. Write `pick.json` in the shape `render_pick.py`'s docstring gives:
    - `gate`: `gate.py`'s output, unchanged
    - `funnel`: `[{"stage", "count"}]`, e.g. industries scanned, screen survivors, merged pool, health check passed, quick reads, finalists, picks. `screen.py`'s own funnel uses `remaining`, so copy the numbers, not the objects.
    - `industries`: the three `industries/<group>.json` lists joined together
    - `candidates`: each `cards/<TICKER>.json`, plus `held` from `pool.json` and `finalist: true` or `false`
    - `picks`: a thesis and a "bad pick" sentence for each passing finalist, from its deep valuation
    - `missing_roles` and `notes`, including searches used against the budget
13. Run `render_pick.py`. Publish with the Artifact tool (icon search, description "Deep picks as of DATE"). Reply in the deep-picker format.

**The user asks whether a screen works, or you are about to lean on a ranking**

1. Run `lookback.py` with the same preset and overrides as the screen.
2. Reply with the look-back format below.

## Reply format

**For a screen:** the artifact link on its own line, then these parts in this order.

1. One line: `universe` screened → survivors, and the test that did the most narrowing.
2. The top survivors (up to 10) as a table: Ticker · Company · 3-yr growth · Latest quarter · the ranking columns for the preset · Flags. Mark the ones already held.

   | Preset | Ranking columns |
   |---|---|
   | `growth`, `quality`, `garp` | Expected · Price implies · Gap |
   | `value` | Cash yield · P/E · Piotroski |
   | `magic` | Return on capital · Earnings yield |
   | `graham` | P/E · P/E × P/B |
   | `payout` | Payout yield |

3. One or two near misses worth knowing about, with the one test each failed.
4. **Flags** from `flags[].message`, or "None".
5. The next funnel step as an offer: which companies you would take into step 3 and why, in one sentence each.
6. One sentence, once: the list is general information, not a view on any security.

**For the deep picker:** the artifact link on its own line, then these parts in this order.

1. A table of the picks: ticker, central and worst return a year at today's price, a one-line thesis, and the deep-valuation link. Put the `pass_flagged` warning beside any flagged pick. When nothing passed, say so plainly.
2. The near misses, each with the test it failed.
3. One line on the industry picture: the favored and contrarian industries.
4. **Flags**: missing roles, searches used against `budget.json` and anything cut to stay within it, names the health check could not cover, and concentration against the person's portfolio. Or "None".
5. One sentence, once: the picks are general information at the stated assumptions, not financial, tax, or legal advice.

**For a look-back:** in chat, every time.

1. A small table of the result.
2. Its flags.
3. The caveats: it is one period, companies delisted since are missing, and past value is approximated.

## Rules

- Every number comes from the script.
- Say the limits in Background when they bear on a result.
- A ranking that did not predict anything in the look-back is a reason to treat rank as a starting order, not a signal.
- A large gap between expected growth and the growth the price implies is a question, not an answer.
- In the deep picker, industry verdicts and candidate scores are judgement backed by dated evidence. They are not forecasts.
- Surface only gate passes as picks, and never call a pick a recommendation.
- Name a `pass_flagged` warning beside the pick every time.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
