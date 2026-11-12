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
- The deep picker's mechanical work is five scripts, run in this order: `pick_prep.py`, `pool.py`, `cards.py`, `pick_assemble.py`, with `prospects.py` run by the industry scanners. The coordinator writes none of their files by hand.
- `pick_prep.py` makes the run folder, writes the macro snapshot from FRED, runs the profile's screens one after another, and starts the search budget.
- `prospects.py` runs the scanner's four prospect tests on up to 25 tickers in one call.
- `pool.py` merges the scanners' prospects and the screens' survivors, trims to 40 names, health-checks them and splits them into quick-read batches.
- `cards.py` fetches each pool name's research pack before any quick reader starts, so quick readers read files instead of running scripts.
- `pick_assemble.py` applies the downside gate (`gate.py`'s own logic), builds `pick.json` and the page (`render_pick.py`'s own build), and prints the commands that save the picks.
- `budget.py` (a valuation script) is the only writer of `budget.json`.

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

### Depth

The saved depth decides the default; when it is deep, the session's depth rule says what changes (the deep picker, deep picks only, and a preset screen labelled as candidates). In standard depth the funnel answers "find stocks", "screen for value" and a preset by name. These words upgrade one request to the deep picker: "deep pick", "best opportunities", "find me the best stocks", "deep screen".

### The deep picker

- **Pipeline.**
  1. `pick_prep.py` writes the macro snapshot and runs the financial screens, including a small-cap pass.
  2. Three industry scanners research the sectors and name each industry's prospects.
  3. `pool.py` merges and health-checks the candidates, and `cards.py` fetches each one's research pack.
  4. Quick reads score each candidate, and three to five finalists get a deep valuation (the valuation skill's Deep steps).
  5. `pick_assemble.py` applies the gate and builds the page.
- **Where candidates come from.** Each industry contributes its prospects: companies chosen on trajectory over 8 quarters, free cash flow, price and how overlooked they are (the tests `prospects.py` runs), not on size. Prospects and screen survivors from every industry enter the pool; the industry verdict feeds the `tailwind` score and never removes a name.
- **Subagents read, they do not fetch.** Each tool call costs a subagent time. Everything a script can fetch is on disk before a subagent starts: `context/macro.md` for the scanners, and a research pack per company for the quick readers.
- **The research pack.** `cards.py` builds `cards/<TICKER>/` for every pool name: SEC financials, the Yahoo profile, valuation inputs, the quick value, sentiment with the analyst consensus, the latest eight earnings releases, red-flag passages, and an `INDEX.md` naming each file and the resolved script commands. `cards/<TICKER>.data.json` holds the headline fields.
- **The gate (`gate.py`).**
  - A finalist passes when no gated deep-valuation scenario loses money over five years, dividends included (`floor`, default 0%), and the central (first) scenario earns at least the hurdle (`hurdle`, default 10%) a year at today's price.
  - The worst scenario judged is the severest single story. The one scenario marked `"stress": true` (several risks at once) is reported as `stress` and named in `reasons` when it loses money, but it is not gated.
  - `pass_flagged` means it passed while every gated scenario sits above the price, so a downside case may be missing.
- **The balance-sheet check (`cards.py`).**
  - Each data file's `leverage` holds net debt today (Yahoo's total debt less cash, the latest quarter) against the latest annual EBITDA, and EBIT against interest.
  - `ok` is false over 2x net debt to EBITDA or under 6x interest coverage. A name that fails starts its `value_hint` at 3 at most, and is not a finalist.
  - Debt is how most gate failures happened: it turns a revenue decline into a large loss for the shares.
  - `ok` is null for a financial, REIT or utility, which is judged on its yardstick.
- **Size.** A run with three finalists (the default) dispatches about 25 to 35 subagents and plans 127 web searches, most of them inside deep valuation.
- **Search plans.** The session has one shared pool of about 200 web searches. `pick_prep.py --finalists N` starts the run's `budget.json` on `budget.py`'s plan `picker-N`:

  | Finalists | Plan | `scanners` | `quick_reads` | `valuations` | Total |
  |---|---|---|---|---|---|
  | 3 (default) | `picker-3` | 18 (6 each) | 40 (1 per company) | 69 (23 each) | 127 |
  | 4 | `picker-4` | 18 (6 each) | 40 (1 per company) | 92 (23 each) | 150 |
  | 5 | `picker-5` | 18 (6 each) | 40 (1 per company) | 95 (19 each, no second thread round) | 153 |

  - Each finalist's valuation keeps its own `budget.json` in `DIR/deep-SYMBOL/` on the plan `valuation-picker`: 23 searches, the valuation plan with `industry` at 4.
  - `pick_assemble.py` sums the finalists' own budgets into the `valuations` figure, so the run's `budget.json` records only `scanners` and `quick_reads`.
  - Every `budget.py` command prints `caps`, `used`, `used_total`, `remaining` and `flags` (`ROLE_OVER_CAP`, `OVER_BUDGET`).
  - `quick_reads` plans 40: one search for each name of a full pool, which `pool.py` trims to 40.
- **The run folder `DIR/pick-DATE/`** (DIR is the session scratchpad):

  | Path | Written by | Holds |
  |---|---|---|
  | `context/macro.md`, `context/macro.json` | `pick_prep.py` | The run date, then one dated line per FRED series: rates, unemployment, oil and gas prices, and the change over a year in CPI, retail sales and manufacturing output |
  | `screen/<name>.json` | `pick_prep.py` | `screen.py`'s output per screen: `value`, `quality` and `smallcap` for the value profile, `garp` and `smallcap` for growth |
  | `budget.json` | `budget.py` | The search plan and what each stage has used |
  | `industries/group<N>.json`, `.md` | Industry scanners | The industry objects, and the notes behind them |
  | `screen/health.json` | `pool.py` | `screen.py`'s health check of the pool |
  | `pool.json` | `pool.py` | `names` (the kept rows, each with `origin`, `held`, `industry`, `industry_verdict`, `health`), `dropped`, `trimmed`, `counts`, `batches` |
  | `cards/<TICKER>/` | `cards.py` | The company's research pack, with its `INDEX.md` |
  | `cards/<TICKER>.data.json` | `cards.py` | The pool row plus `quick_value`, `value_hint`, `red_flags`, `direction`, `analysts`, `insiders`, `flags`, `sentiment_flags`, `missing`, `index` |
  | `cards/<TICKER>.json`, `.md` | Quick readers | The scored card, and its notes |
  | `picks-notes.json` | The coordinator | A thesis and a "bad pick" sentence per finalist, `missing_roles`, `notes`, `profile` |
  | `gate.json`, `gate.out.json`, `pick.json`, `page.html` | `pick_assemble.py` | The gate's input and output, the page's input, and the page |

  - Each finalist's deep valuation keeps its own `DIR/deep-SYMBOL/` folder and page, beside the run folder.
  - `<TICKER>` is the dash form. The scripts take `BRK.B` or `BRK-B` and write `BRK-B` in `pool.json`, the cards and the pack folders.
  - The page's funnel counts "Health check passed" (only `passed` names) apart from "Kept for quick read" (`counts.kept`, which also holds the names the quick read judges).
- **`health` in `pool.json`.** Only `failed` names leave the pool, into `dropped` with their `failed_tests`. The others stay, and the quick read judges them:

  | `health` | Meaning |
  |---|---|
  | `passed` | Passed the health screen |
  | `financial` | A bank, lender or insurer, which the screen sets aside |
  | `judge_in_quick_read` | Failed, but its sector is Financials: the cash tests misread an asset manager, broker or BDC |
  | `not_found` | No SEC filer under that ticker |
  | `incomplete` | No four years of US-GAAP history: too new, or files IFRS, like many foreign leaders |
  | `unchecked` | The health screen itself failed (`HEALTH_CHECK_FAILED`) |

- **Picker flags.** Each script prints `flags` as `{"code", "message"}`. What to do with each:

  | Flag or field | Printed by | What to do |
  |---|---|---|
  | `SCREEN_PRICING_INCOMPLETE` | `pick_prep.py` | Yahoo rate-limited a screen, so its survivors are not the preset's. Wait a few minutes and run the same `pick_prep.py` command on the same folder. |
  | `PRICING_INCOMPLETE` | `pool.py` | A screen file still carries the rate limit. Wait a few minutes, rerun `pick_prep.py` on the same folder, then `pool.py`. |
  | `SCREEN_FAILED` | `pick_prep.py` | One screen wrote no file and the others were kept. Go on, and name the screen in the reply's Flags. |
  | `MACRO_SERIES_UNAVAILABLE` | `pick_prep.py` | FRED did not return a series, and `macro.md` leaves it out. Go on. |
  | `BUDGET_KEPT` | `pick_prep.py` | The folder already had a budget, and its count carries on. Expected on a rerun. |
  | `BUDGET_UNAVAILABLE` | `pick_prep.py` | No budget was started. Run `budget.py DIR/pick-DATE init --plan picker-N`. If that fails, stop and show its `error`: the valuation skill is not installed. |
  | `POOL_TRIMMED` | `pool.py` | More than 40 candidates were cut to 40. Say how many in the reply's Flags (`counts.trimmed`). |
  | `HEALTH_CHECK_FAILED` | `pool.py` | Every name stayed, as `unchecked`. Rerun `pool.py` once. If it flags again, go on: the quick readers judge health, and the reply's Flags say the health check did not run. |
  | `INDUSTRY_FILE_SKIPPED`, `SCREEN_FILE_SKIPPED`, `PROSPECT_SKIPPED` | `pool.py`, `pick_assemble.py` | A file is not JSON or not the expected shape, or a prospect has no ticker. Repair a scanner's `industries/group<N>.json` from its `.md` notes and rerun the script; for a screen file, rerun `pick_prep.py`. |
  | `YAHOO_RATE_LIMITED` | `cards.py` | Wait a few minutes, then run the `cards.py --run … --symbols … --force` command its `message` prints. |
  | `PACK_FAILED` and `failed` | `cards.py` | Run `cards.py --run DIR/pick-DATE` once more; it fetches only the names without a pack from today. A name still in `failed` gets no quick read: leave it out of its batch and name it in the reply's Flags. |
  | `NEWS_UNAVAILABLE` in a card's `sentiment_flags` | `cards.py` | Nothing to rerun. That company's quick reader spends its one search on news, as its brief says. |
  | `CURRENCY_MISMATCH` in a card's `red_flags.inputs_flags` | `cards.py` | Nothing to rerun. The statements are in another currency than the share price (a foreign filer), so the pack's `quick_value.basis` and the card's `value_hint` are null. The quick reader scores `value` from multiples. |
  | `LEVERAGE_HIGH` | `cards.py` | Nothing to rerun. The named cards fail the balance-sheet check (`leverage.why` in each data file says which test). They get quick reads but are not finalists. Name them in the reply's Flags. |
  | `DEBT_CHANGED_SINCE_ANNUAL` in a card's `leverage.flags` | `cards.py` | Nothing to rerun. Debt is over 1.5x the last annual balance sheet's (a deal or refinancing since), so the 10-K's leverage figures in `edgar.json` are stale. The check uses today's debt. |
  | `THIN_EDGAR_HISTORY` in a card's `red_flags.inputs_flags` | `cards.py` | Nothing to rerun. `edgar.json` has no annual rows or no 10-K was found (a foreign filer, or filings under a predecessor registrant), so health and direction rest on fewer figures. The card says so. |
  | `HEALTH_NOT_CHECKED` | `pick_assemble.py` | The health screen did not run, so the page's funnel leaves out "Health check passed" and goes from the merged pool to "Kept for quick read". Say in the reply's Flags that the health check did not run. |
  | `THESIS_MISSING` | `pick_assemble.py` | Add the pick's `thesis` to `picks-notes.json` and rerun. |
  | `PICK_NOTE_DROPPED` | `pick_assemble.py` | Expected: the notes entry of a finalist that failed the gate was left off the page. |
  | `CARD_SKIPPED`, `FINALIST_WITHOUT_CARD` | `pick_assemble.py` | A `cards/<TICKER>.json` is not valid JSON, or a finalist has none. Repair or write the card from its `.md` notes and rerun. |
  | `CASE_PAGE_MISSING` | `pick_assemble.py` | Run the valuation skill's `render_deep.py --case DIR/deep-SYMBOL` for that pick before its save command. |

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
- `references/primary-sources.md` catalogs the dated government, trade-body and macro pages the subagents fetch before they search. The subagents read it; the coordinator does not need it, since `pick_prep.py` writes `context/macro.md`.

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
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/pick_prep.py" --run DIR/pick-DATE --profile value|growth [--held SYM,SYM] [--finalists 3|4|5]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/prospects.py" SYM[,SYM...] [--out FILE]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/budget.py" DIR/pick-DATE add scanners=N | quick_reads=N
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/pool.py" --run DIR/pick-DATE [--held SYM,SYM] [--max 40]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/cards.py" --run DIR/pick-DATE [--symbols SYM,SYM] [--workers 3] [--force]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/valuation/scripts/deep_prep.py" SYMBOL --case DIR/deep-SYMBOL --plan valuation-picker [--industry FILE ...]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/pick_assemble.py" --run DIR/pick-DATE --finalists SYM=URL[,SYM=URL...] [--cases DIR] [--hurdle R] [--floor R] [--notes FILE] [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/gate.py" < DIR/pick-DATE/gate.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/render_pick.py" --in DIR/pick-DATE/pick.json --out DIR/pick-DATE/page.html
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/sentiment.py" SYM[,SYM...] [--days 20] [--news-days 30] [--news 10]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/picks.py" save-deep SYM (--case DIR/deep-SYM | --page FILE) [--thesis TEXT] [--source URL] [--added-price P] [--base-end YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/picks.py" save-light SYM --in DIR/light-SYM.json   # standard depth only
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
| `pick_prep.py` | The deep picker's first step: the run folder, `context/macro.md`, the profile's screens into `screen/`, and `budget.json` on `picker-N`. Prints `run`, `macro`, `screens` (per screen `survivors`, `top`, `flags`, `path`), `budget` and `flags`. Safe to run again on the same folder. |
| `prospects.py` | The four prospect tests for up to 25 tickers in one call. Prints `prospects` (per ticker `tests_passed`, `tests`, `size_ok`, `why`, `flags`), `not_found` and `flags`. The industry scanners run it. |
| `budget.py` | The valuation skill's search budget script. `add` records the searches a stage used; with only the folder it prints the status. |
| `pool.py` | Merges `industries/*.json` prospects and `screen/*.json` survivors into `pool.json`, trims to `--max`, runs the health check and makes the quick-read `batches`. Prints `pool`, `counts`, `batches`, `dropped` and `flags`. |
| `cards.py` | Builds each pool name's research pack in `cards/<TICKER>/` and writes `cards/<TICKER>.data.json`. Prints `cards`, `failed`, `counts` and `flags`. A second run fetches only names without a pack from today; `--symbols SYM --force` rebuilds one. |
| `deep_prep.py` | The valuation skill's prep script, in the form the picker uses for a finalist: the plan `valuation-picker` and one `--industry` flag per industry file. |
| `pick_assemble.py` | The gate, `pick.json` and `page.html` from the run folder and each finalist's `deep-SYMBOL` folder. Prints `out`, `pick`, `gate` (counts), `picks`, `near_misses`, `save_commands` and `flags`. It writes all four files or none. |
| `gate.py` | The deep picker's downside gate: `pass`, `pass_flagged` or `fail` per finalist, with reasons. `pick_assemble.py` runs it. |
| `render_pick.py` | The deep picker's page: picks, near misses, funnel, industry map, candidates. `pick_assemble.py` runs it. |
| `sentiment.py` | Per symbol, FINRA daily short-sale volume (not short interest), dated Yahoo headlines and `analysts` (Yahoo's price targets, rating counts, rating actions and estimates), with flags when a part is missing. `cards.py` runs it into each pack. |
| `picks.py` | The saved picks: save a deep or light baseline, list, remove, `check` one against its baseline (`--record` keeps the result; `--release` uses an earnings release before the 10-Q), and `due`. |
| `track_math.py` | The re-check arithmetic `picks.py check` runs. Its docstring is the contract. |

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad input. For `picks.py`, also an unknown pick or a page without embedded data. For `pool.py`, a run folder that does not exist or nothing to merge. For `cards.py`, no `pool.json`. For `pick_assemble.py`, a finalist without `model.out.json` or `returns.out.json`, a link that is not https, a notes file that is not the expected shape, or a card or industry object `render_pick.py` rejects; nothing is written. For `budget.py`, an unknown role or no `budget.json`. | `error` |
| 4 | `pick_prep.py`: `EDGAR_USER_AGENT` is not set, and nothing is created. `picks.py`: `SKILL_MISSING`, the fundamental-research skill is not installed. | `error` |
| 5 | EDGAR or Yahoo error | `hint` |
| 6 | Python deps missing | the error |

## Steps

Pick the case that matches the request.

**The user wants companies to look at (the funnel; standard depth)**

The funnel has five steps, in order. Say which step you are on.

1. **Screen** (this skill).
   1. If a brokerage is connected, read today's holdings first: portfolio-analysis's `brief.py --no-headlines`, unless a read from today is already in the conversation. Pass the held symbols as `--held SYM,SYM`. Survivors already owned are marked. Add `--exclude-held` when the person wants new names only.
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
6. **Keep it for re-checks.** In standard depth only: offer to save each company the person picks. On yes, write `DIR/light-SYM.json` with `thesis`, `preset` and `fair_values` (`bear`, `base`, `bull` from step 4), then run `picks.py save-light SYM --in DIR/light-SYM.json` (standard depth only; it exits 2 with `DEPTH_DEEP` at deep depth).

**The user wants the best opportunities (the deep picker)**

The scripts do the fetching and the file assembly. Do not write `macro.md`, `pool.json`, `gate.json` or `pick.json` by hand, and do not run `screen.py` yourself.

1. Run `edgar.py` from the fundamental-research skill on any ticker. If it exits 4, stop, say the deep picker needs SEC EDGAR, and in standard depth offer the funnel.
2. Gather what the run needs from the person:
   - When a brokerage is connected, take held symbols and sector weights from a portfolio-analysis read taken today (`brief.py --no-headlines` when there is none yet). The person buys outside these sessions, so the pick store and the watchlist are not a list of holdings.
   - Note the profile (`value` or `growth`), and any theme or sector limit the person gives.
   - The run has three finalists unless the person asks for four or five.
3. Tell the person the run has started, and its size from Background: the subagent count and the planned searches of its plan.
   - Run the picker in a session that has not spent its searches on other work.
4. Run `pick_prep.py --run DIR/pick-DATE --profile PROFILE`, adding `--held SYM,SYM` for the held symbols and `--finalists N` for four or five finalists.
   - It makes the run folder, writes `context/macro.md`, runs the screens and starts `budget.json`.
   - The screens run one after another and can take several minutes. Give the Bash call its longest timeout, or run it in the background and wait for it.
   - If it exits 4, stop as in step 1.
   - Read `screens`, `budget` and `flags` from what it prints, not from the files.
   - If `flags` is not empty, do what the Picker flags table in Background says before going on. `SCREEN_PRICING_INCOMPLETE` means wait a few minutes and run the same command again.
5. Dispatch three Industry scanner agents (general-purpose) in one message, one per sector group in `references/picker-roles.md`. Keep each prompt to these items:
   - the absolute path of `references/picker-roles.md` and its two sections to read: Shared rules and Industry scanner
   - the run folder, today's date and the group number
   - the search cap of 6, as a hard limit
   - the resolved command lines of `prospects.py` and of the fundamental-research skill's `filing.py` and `earnings.py`
   - any theme or sector limit from step 2
6. Run `budget.py DIR/pick-DATE add scanners=N` once, with the total the three scanners reported. If a scanner failed or wrote no `industries/group<N>.json`, keep its name for `missing_roles` and go on.
7. Run `pool.py --run DIR/pick-DATE`, adding `--held SYM,SYM` for the held symbols.
   - It merges the prospects and the screen survivors, trims to 40 names, runs the health check and writes `pool.json`.
   - Read `counts`, `batches`, `dropped` and `flags` from what it prints.
   - If `flags` is not empty, do what the Picker flags table says.
   - Keep the `dropped` names and their `failed_tests` for the reply.
8. Run `cards.py --run DIR/pick-DATE`. It builds three packs at a time and takes several minutes for a full pool, so give the Bash call its longest timeout, or run it in the background and wait for it.
   - If `flags` carries `YAHOO_RATE_LIMITED`, wait a few minutes and run the command its `message` prints.
   - If `failed` is not empty, run `cards.py --run DIR/pick-DATE` once more. A name still in `failed` gets no quick read.
9. Dispatch every Quick reader agent (general-purpose) in ONE message: one agent for each list in `batches`. Do not send them in waves. Keep each prompt to these items:
   - the absolute path of `references/picker-roles.md` and its two sections to read: Shared rules and Quick reader
   - the run folder and today's date
   - the batch's tickers, without any name still in `failed`
   - the search cap of 1 per company, as a hard limit
   - the instruction to start from each company's `cards/<TICKER>.data.json` and the `INDEX.md` it names in `index`. The index holds the pack's files and the resolved script commands, so the prompt lists neither.
10. Run `budget.py DIR/pick-DATE add quick_reads=N` once, with the total the quick readers reported. If a quick reader failed, keep its name for `missing_roles`.
11. Rank the cards (`cards/<TICKER>.json`) by their four scores with judgement, and choose three finalists, or up to five when the person asks and the search plan from step 4 covers them:
    - only names whose `leverage.ok` in `cards/<TICKER>.data.json` is true or null. A null for missing figures needs the card to show the balance sheet is sound; a false is never a finalist
    - at least one contrarian when one survives
    - no more than two from one industry
    - held names allowed, and marked
12. Run the valuation skill's **Deep** steps on the finalists, two or three at a time. Each finalist gets its own `DIR/deep-SYMBOL/` folder, its own `budget.json` and a published page.
    - Give each finalist to its own agent (general-purpose) that follows those steps and dispatches the research roles itself.
    - When a subagent cannot dispatch its own, run the valuations yourself, one company's model and ledger at a time.
    - In its step 1, run `deep_prep.py SYMBOL --case DIR/deep-SYMBOL --plan valuation-picker` with one `--industry FILE` flag per file: the `industries/group<N>.json` that holds the finalist's industry, and its `industries/group<N>.md`. A finalist no scan covers (`industry` is null in `pool.json`) gets no `--industry` flag.
    - With five finalists, run no second thread round in any valuation. The `picker-5` plan counts 19 searches for each.
    - Stop each valuation after its page is published. The picker saves the picks and writes the one reply.
    - Keep each finalist's https page link for step 14.
    - If a valuation cannot finish (its `deep_prep.py` exits 5, or it never reaches a `deep_run.py` run), leave that finalist out of step 14 and say so in `notes`.
13. Write `DIR/pick-DATE/picks-notes.json`:
    - `picks`: for every finalist, `{"SYM": {"thesis": "...", "bad_pick": "..."}}`, both from its deep valuation. Write one for each finalist: the gate has not run yet, and `pick_assemble.py` drops the entry of a finalist that fails it.
    - `missing_roles`: a list of the scanners, quick readers and valuation roles that failed
    - `notes`: a list of anything cut to stay within the plan, and the finalists left out
    - `profile`: the profile from step 2
14. Run `pick_assemble.py --run DIR/pick-DATE --finalists SYM=URL,SYM=URL`, pairing each finalist with its deep-valuation page link. Add `--hurdle R` or `--floor R` when the person changed them.
    - It runs the gate, and writes `gate.json`, `gate.out.json`, `pick.json` and `page.html`.
    - If it exits 2, fix what the `error` names (a finalist without a finished valuation, or a card it rejects) and rerun. Nothing was written.
    - If `flags` is not empty, do what the Picker flags table says.
15. Publish `DIR/pick-DATE/page.html` (the `out` path) with the Artifact tool: icon search, description "Deep picks as of DATE".
16. Run each command in `save_commands` exactly as printed. Each saves one pick for re-checks.
17. Reply in the deep-picker format. Take the picks from `picks`, the near misses from `near_misses`, and each one's returns and failed test from `gate.out.json` (`central.irr`, `worst.irr`, `reasons`).

**The person asks how their picks are doing, or the session says a pick is due**

1. Run `picks.py list`. When it is empty, say re-checks start from a saved pick, and stop.
   - When a brokerage is connected, compare the list with today's holdings (portfolio-analysis's `brief.py --no-headlines` when there is no read from today). Name held single stocks that are not saved picks, and offer to save the ones with a published deep page.
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
   - In deep depth a light pick gets no light re-check: `check` exits 2 with `DEEP_VALUATION_NEEDED`, and `list` and `due` mark it `needs_deep_valuation`. Say it needs a deep valuation and run the Deep steps under the session's depth rule (its size line and ask threshold).
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

1. A table of the picks: ticker, central and worst return a year at today's price, the stress test's return when there is one, a one-line thesis, and the deep-valuation link. Put the `pass_flagged` warning beside any flagged pick. When nothing passed, say so plainly.
2. The near misses, each with the test it failed, and the stress test's return when a finalist has one (`stress.irr` in `gate.out.json`), labelled not gated.
3. One line on the industry picture: the favored and contrarian industries.
4. **Flags**: missing roles, the searches line from `pick.json`'s `notes` and anything cut to stay within the plan, script flags the Picker flags table says to name, names the health check could not cover, and concentration against the person's portfolio. Or "None".
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
