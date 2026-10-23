---
name: stock-screener
description: Screens US filers on growth, value, quality, GARP, magic, Graham or payout presets, runs a deep pick with deep valuation, and re-checks saved picks against their valuation. Use when asked to find stocks, for best opportunities, or how picks are doing.
---
Takes a person from "no list" to one to three researched companies. It screens every US filer on a preset's tests, can check the same screen against history, and then walks a five-step research funnel whose later steps hand off to the fundamental-research and valuation skills.

Its deep picker mode adds an industry scan, quick reads of each candidate and deep valuation of the finalists, and surfaces only the finalists that pass a downside test.

Saved picks are re-checked later against the valuation they were picked on, without rerunning it.

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

- **Pipeline.** An industry scan and the financial screens (including a small-cap pass) run side by side. Their candidates are merged and health-checked, quick reads score each one, and three to five finalists get a deep valuation (the valuation skill's deep mode).
- **Where candidates come from.** Each industry contributes its prospects: companies chosen on trajectory over 8 to 12 quarters, free cash flow, price and how overlooked they are, not on size. Prospects and screen survivors from every industry enter the pool; the industry verdict feeds the `tailwind` score and never removes a name.
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

### Re-checking picks

- **The store.** `picks.py` keeps each pick in `picks.json` in the plugin data dir, with its baseline in `picks/`. The session scratchpad is cleared, so a pick is only re-checkable once saved.
  - A deep pick's baseline is its deep valuation: `page.json` and `model.json` from the case folder.
  - A deep page published earlier embeds the same data, so `save-deep --page` recovers a pick whose folder is gone.
  - A light pick's baseline is its thesis, the bear / base / bull fair values from the funnel's price check, and the TTM revenue growth and operating margin on the day it was picked.
- **What `check` measures (deep).** From SEC EDGAR company facts:
  - the base year: the fiscal year the valuation started from
  - the latest four reported quarters (TTM)
  - Each scenario's yearly path gives an expected TTM revenue growth and operating margin (ROE for a bank or insurer). `nearest` is the scenario the actuals sit closest to.

  | `status` | Meaning |
  |---|---|
  | `on_track` | The actuals sit nearest the central (first) scenario |
  | `shifting` | They sit clearly nearer another scenario: the story is moving toward it |
  | `outside` | Below or above every scenario: the valuation no longer brackets what is happening |
  | `no_new_data` | No quarter reported since the base year |

- **`rerun_deep`** is true when `outside`, when the valuation is over 15 months old, or when dated evidence contradicts a high-stakes belief or a condition of the central scenario. It means the deep valuation is due again, not that anything about the holding changed.
- **The watch list.** `result.watch` names the central and nearest scenarios' must-be-true conditions and the ledger beliefs still in play. Evidence on them is what `--evidence` takes.
- **The price level.** Every check also places today's price against the valuation, apart from `status`. `result.price.levels` gives each threshold price.

  | `level` | Meaning |
  |---|---|
  | `above_all` | Above the best scenario's value |
  | `above_central` | Above the central scenario's value |
  | `hurdle` | Above the price at which the central scenario earns the hurdle (10%) a year, the test the deep picker admitted the pick on |
  | `normal` | Between the worst scenario's value and the hurdle price |
  | `below_worst` | Below the worst scenario's value |

  A light pick uses its bear / base / bull values as worst / central / best, with no hurdle level.
- **What `check` measures (light).** Growth and margin now against the day of the pick, and the price against the fair values. `weakening` (growth down over 5 points or margin over 2) sets `deep_review`: a deep valuation is the next step.
- **Before the 10-Q.** The earnings release (8-K Exhibit 99.1) comes out days to weeks before the 10-Q reaches EDGAR.
  - `check --release FILE` rolls the TTM forward one quarter with the release's GAAP income statement, and the result carries `PRESS_RELEASE_FIGURES`.
  - A recorded release check stays `awaiting_filing`, so the 10-Q check is still due; the 10-Q's figures replace the release's.
- **A new deep valuation over a saved pick** keeps the pick's `added` date and `added_price`, so "since added" still measures from the original pick. `--date` and `--added-price` override them.
- **When a pick is due.** A 10-Q or 10-K is filed after its last check, the price moved 15% or more since then, or the price crossed into a new level other than `normal` (PRICE_LEVEL). The SessionStart hook prints the due picks from the stored earnings date and the watchlist's last prices, with no network. `due` checks EDGAR and live prices.
- **Limits.**
  - Company totals are compared, since segment figures are not in XBRL. Segment actuals from the 10-Q segment note go in with `--segments`, in the model's units.
  - `NO_OPERATING_INCOME` means the filer does not tag operating income, so only revenue is compared.
  - `APPROX_BASE` means no `model.json` was saved, so the model's starting revenue is backed out of its yearly path.
  - `FORWARD_BASE` means the model started from an estimate of the year in progress (a guidance midpoint, say), so that year is compared with the estimate. `save-deep --base-end` sets the starting year's end when the guess is wrong.
  - A segment that is not in reported results yet, such as an acquisition that has not closed, makes every scenario look high. `check --exclude SEGMENT --record` leaves it out of this and later checks.
  - `ROE_DEFINITION` means reported ROE runs on another basis than the model's (GAAP equity with unrealized losses, against an ex-AOCI model), so the scenarios are shifted by the base-year gap.

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
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/picks.py" save-deep SYM (--case DIR/deep-SYM | --page FILE) [--thesis TEXT] [--source URL] [--added-price P] [--base-end YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/picks.py" save-light SYM --in DIR/light-SYM.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/picks.py" list | remove SYM | due [--move 0.15]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/picks.py" check SYM [--release FILE] [--segments FILE] [--evidence FILE] [--exclude SEG,SEG] [--record]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/track_math.py" < track.json
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
| `picks.py` | The saved picks: save a deep or light baseline, list, remove, `check` one against its baseline (`--record` keeps the result; `--release` uses an earnings release before the 10-Q), and `due`. |
| `track_math.py` | The re-check arithmetic `picks.py check` runs. Its docstring is the contract. |

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad input; for `picks.py`, also an unknown pick or a page without embedded data | `error` |
| 4 | `picks.py` only. `SKILL_MISSING`: the fundamental-research skill is not installed | `error` |
| 5 | EDGAR or Yahoo error | `hint` |
| 6 | Python deps missing | the error |

## Steps

Pick the case that matches the request.

**The user wants companies to look at (the funnel)**

The funnel has five steps, in order. Say which step you are on.

1. **Screen** (this skill).
   1. If a brokerage is connected, read today's holdings first: portfolio-snapshot's `brief.py --no-headlines`, unless a read from today is already in the conversation. Pass the held symbols as `--held SYM,SYM`. Survivors already owned are marked. Add `--exclude-held` when the person wants new names only.
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
6. **Keep it for re-checks.** Offer to save each company the person picks. On yes, write `DIR/light-SYM.json` with `thesis`, `preset` and `fair_values` (`bear`, `base`, `bull` from step 4), then run `picks.py save-light SYM --in DIR/light-SYM.json`.

**The user wants the best opportunities (the deep picker)**

1. Run `edgar.py` from the fundamental-research skill on any ticker. If it exits 4, stop, say the deep picker needs SEC EDGAR, and offer the funnel.
2. Make `DIR/pick-DATE/` and its `context/`, `screen/`, `industries/` and `cards/` folders.
   - When a brokerage is connected, take held symbols and sector weights from a portfolio-snapshot read taken today (`brief.py --no-headlines` when there is none yet). The person buys outside these sessions, so the pick store and the watchlist are not a list of holdings.
   - Note the profile, and any theme or sector limit the person gives.
3. Tell the person the run has started, and its size from Background.
   - Write `budget.json` in the run folder. The session has one shared pool of about 200 web searches, so plan at most 160 and keep 40 in reserve. Every plan below sums to 160 or less:

     | Finalists | Industry scanners | Quick reads | Each deep valuation |
     |---|---|---|---|
     | 3 (default) | 8 each, 24 | 46, split over the pool (2 per company up to 23 names, else 1) | 30 (Industry and news 4), 90 |
     | 4 | 8 each, 24 | 46, as above | 22: round-1 roles only, threads from what is left (88) |
     | 5 | 8 each, 24 | 1 per company, at most 30 | 18 (90) |

   - The 3-finalist row totals 160 (24 + 46 + 90) with 40 in reserve. The 4-finalist row totals 158 and the 5-finalist row 144, so each stays within 160 with 40 in reserve.
   - Scanners need fewer searches than quick reads: their prospect tests run on the scripts (`edgar.py --quarters 12`, `fundamentals.py`), which spend none. The pool is wider than when only favored industries fed it, so the quick reads take the difference.
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
   - Run the same first preset again as a small-cap pass, `--set min_revenue=1.5e8 --set min_market_cap=3e8`, into `screen/smallcap.json`. The presets' revenue floors otherwise keep most companies under about $2B in market value out.
6. Merge into `pool.json`:
   - the prospects of every industry, whatever its verdict
   - the survivors of every screen, whatever their industry's verdict
   - leaders only when they are also prospects or screen survivors
   - drop duplicates, aiming for 25 to 35 names, at most 40. When there are more, keep prospects that pass all four tests and the top-ranked screen survivors first, and never trim on the industry verdict
   - mark held names, and each name's `origin` (`industry`, `screen` or `both`)
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
13. Run `render_pick.py`. Publish with the Artifact tool (icon search, description "Deep picks as of DATE").
14. Save each pick for re-checks: `picks.py save-deep SYM --case DIR/deep-SYM --thesis "<its thesis>" --source <its deep page link>`.
15. Reply in the deep-picker format.

**The person asks how their picks are doing, or the session says a pick is due**

1. Run `picks.py list`. When it is empty, say re-checks start from a saved pick, and stop.
   - When a brokerage is connected, compare the list with today's holdings (portfolio-snapshot's `brief.py --no-headlines` when there is no read from today). Name held single stocks that are not saved picks, and offer to save the ones with a published deep page.
   - When the person names a pick that is not saved and its deep page was published, read the page with the Artifact tool and save its HTML to `DIR/deep-SYM.html`.
   - Then run `picks.py save-deep SYM --page DIR/deep-SYM.html --source <link>`, with `--added-price` from their cost when they hold it.
2. Without a named pick, run `picks.py due` and re-check the due ones. Re-check every pick when the person asks for all of them.
3. For each pick, run `picks.py check SYM`.
   - When every metric sits far from every scenario in the same direction, look at the model's segments first. Leave out a segment the company does not report yet (`--exclude`).
   - When the pick has reported but the quarter is not in EDGAR yet (`no_new_data`, or `awaiting_filing` on the pick), read the release instead of waiting:
     1. Run the fundamental-research skill's `earnings.py SYM --last 1 --max-chars 80000`.
     2. From its GAAP income statement, write `DIR/release-SYM.json` in the shape `picks.py`'s docstring gives. Take `equity_year_ago` from its balance-sheet or book-value table when it shows one.
     3. Pass it as `--release DIR/release-SYM.json` here and in step 6.
   - Take figures from the GAAP statement, not the headline or adjusted figures. A one-off the release names (a refund, a remeasurement gain) stays in; name it in the reply.
4. For a deep pick whose status is not `no_new_data`, or that has a release from step 3, look for dated evidence on its `result.watch` items:
   - Read the latest 10-Q's MD&A with the fundamental-research skill's `filing.py`, or the release and its guidance before the 10-Q, and use at most 4 web searches per pick.
   - Write what you find to `DIR/evidence-SYM.json` in `track_math.py`'s evidence shape. Every item needs a source and a date. An item without one is left out.
5. When the scenarios differ mainly by segment, read the segment note of that 10-Q and write `DIR/segments-SYM.json` (each segment's TTM revenue and EBIT, in the model's units).
6. Run `picks.py check SYM --record`, adding `--release`, `--evidence` and `--segments` when step 3, 4 or 5 wrote them.
7. If `rerun_deep` is true, say the deep valuation is due again and why, from `reasons`. Offer to run the valuation skill's Deep steps, which replace the baseline when saved. For a light pick with `deep_review`, offer a deep valuation the same way.
8. Reply with the re-check format below.

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

**For a re-check:** in chat.

1. One table, a row per pick: ticker · status · nearest scenario (deep) · price level · since added · central return a year at today's price against at the valuation (`irr` and `baseline_irr`) · next step (re-run the deep valuation, or none).
   - For a level other than `normal`, one line under the table per pick: the price against the threshold it crossed, from `result.price.levels`.
2. Per deep pick, two or three lines:
   - each metric's actual against the central scenario's expectation and the scenario range (`metrics`)
   - the evidence found, each item with its source and date
   - where the price sits against the scenario values
3. Per light pick, one line: growth and margin at pick against now, and the price against bear / base / bull.
4. **Flags**: `flags` and `reasons` messages, and picks skipped for missing data. Or "None". Name `PRESS_RELEASE_FIGURES` every time it appears: the figures are the release's until the 10-Q.
5. One sentence, once: the re-check is general information at the stated assumptions, not financial, tax, or legal advice.

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
- A price level states where the price sits against the valuation. Name the threshold and leave the decision to the person.
- A re-check status describes the valuation, not the holding. `outside` or `rerun_deep` says the scenarios need redoing; it is never a signal to buy or sell.
- In a re-check, evidence without a dated source changes nothing.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
