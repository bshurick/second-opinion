---
name: stock-screener
description: Screens all US-listed companies from SEC filings on growth, value, quality, GARP, magic-formula, Graham or payout presets, checks how past picks did, and runs the research funnel. Use when asked to find stocks, for a stock screener, or growth or value ideas.
---
Takes a person from "no list" to one to three researched companies. It screens every US filer on a preset's tests, can check the same screen against history, and then walks a five-step research funnel whose later steps hand off to the fundamental-research and valuation skills.

## Background

### What the scripts do

- `screen.py` scans every US filer with XBRL financials, applies a preset's business tests, prices the survivors from Yahoo, and ranks them the way the preset says.
- The data is four fiscal years of revenue, margins, cash flow, capital spending, stock pay, share counts and payouts, two year-end balance sheets, and the latest reported quarter.
- It comes from SEC EDGAR "frames", where one request covers every company. A first run downloads about 180 frames (under a minute), cached a day.
- `screen.py` needs `EDGAR_USER_AGENT` set, like fundamental-research.
- `screen.py` prints the `funnel`, `fail_counts`, `survivors` (ranked), `near_misses`, `criteria`, `priced`, `coverage` and `flags`. `--all` adds every screened company.
- `lookback.py` runs the same screen as of an earlier year and shows what its survivors did since.
- `screen_math.py` is the shared math. Its docstring is the contract: every criterion, the presets, the missing-data rules, the flags.

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
| `MISSCALED` | The filer tagged a figure with the wrong scale; it was dropped. The price figures are meaningless. |
| `PROFIT_ABOVE_OPERATING_PROFIT` | A one-off gain flatters the P/E. |
| `CASH_ABOVE_ITS_AVERAGE` | Last year's cash margin is more than 10 points above the multi-year average; the average was used. |
| `ACQUISITIVE` | Growth partly bought. |
| `PRICE_FALLING` | The 12-month price change is below −20%. |
| `LATEST_QUARTER_NOT_REPORTED` | The most important test was not applied. |

### Limits

- Figures are XBRL tags computed one uniform way. Companies' own reported or adjusted figures can differ, and some filers tag with the wrong scale (dropped and flagged `MISSCALED`).
- Annual frames align fiscal years to calendar years. The latest quarter is the most recent of the two listed in `latest_quarter_periods` that the company reported.
- Foreign filers (20-F/6-K) usually have no quarterly XBRL, so their latest-quarter test is `not_reported`, not passed, and they carry `LATEST_QUARTER_NOT_REPORTED`.
- Early in the year most companies have not filed the latest fiscal year and are left out. The `LATEST_YEAR_THIN` flag says so and names the `--year` to use instead.
- Companies with fewer than four years of filings (recent listings) are never screened.
- Banks, insurers and lenders are set aside: their cash flow includes customer money.
- Balance-sheet figures (debt, cash, capital employed) are from the latest fiscal year end, so they can be most of a year old.
- Debt is the largest total-debt figure a company tags. A company tagging neither debt nor interest is taken as debt-free.
- P/E uses the latest fiscal year's reported net income, one-off gains included.
- "Price implies" is arithmetic on today's enterprise value at a 10% discount rate and 3% terminal growth, not a forecast. A large gap is a question (why does the market doubt the growth), not an answer.
- Yahoo limits how many quotes it serves. `PRICING_INCOMPLETE` means wait a few minutes and rerun.

## Scripts

Run with the Bash tool. Scripts print JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/screen.py" [--preset growth|value|quality|garp|magic|graham|payout] [--set KEY=VALUE ...] [--year YYYY] [--no-price] [--price-limit N] [--held SYM,SYM] [--exclude-held] [--all]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/lookback.py" [--preset NAME] [--set KEY=VALUE ...] [--year YYYY] [--price-limit N] [--benchmark SPY]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/screen_math.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/stock-screener/scripts/render.py" --in screen.json --out page.html
```

| Script | What it does |
|---|---|
| `screen.py` | Screens the whole market on a preset, prices the survivors and ranks them. `--set` overrides one criterion; a value of `none` switches it off. `--year` is the latest fiscal year. `--no-price` stops after the business tests. `--price-limit` caps how many survivors are priced. `--held` marks symbols already owned and `--exclude-held` leaves them out. `--all` adds every screened company. |
| `lookback.py` | Runs the screen as of an earlier year and reports what its survivors did since against `--benchmark`. |
| `screen_math.py` | Pure math on a JSON input. |
| `render.py` | Turns a `screen.py` result into one HTML page for the Artifact tool. |

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
   2. Drop a survivor from the shortlist when its flags make the price figures meaningless (`CASH_OUTRUNS_PROFIT`, `MISSCALED`), and say so.
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

**For a look-back:** in chat, every time.

1. A small table of the result.
2. Its flags.
3. The caveats: it is one period, companies delisted since are missing, and past value is approximated.

## Rules

- Every number comes from the script.
- Say the limits in Background when they bear on a result.
- A ranking that did not predict anything in the look-back is a reason to treat rank as a starting order, not a signal.
- A large gap between expected growth and the growth the price implies is a question, not an answer.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
