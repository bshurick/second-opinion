# Deep picker role briefs

Each section is the brief for one deep-picker subagent. The coordinator hands a subagent the absolute path of this file and names two sections to follow: Shared rules, plus the agent's role. The prompt also carries:

- the run folder
- today's date
- the role's assignment: a sector group for a scanner, or about five tickers for a quick reader
- the search cap
- for a scanner, the resolved command lines of `prospects.py`, `filing.py` and `earnings.py`

## Contents
- Shared rules
- Industry scanner
- Quick reader

## Shared rules

### Read the data first

- Each tool call costs time. The scripts have already fetched what they can, so read a file with the Read tool instead of running a script for the same data.
- Read the run folder's `context/macro.md` first. It is the dated macro picture from FRED: rates, unemployment, oil and gas prices, and the change over a year in consumer prices, retail sales and manufacturing output. Never spend a search or a fetch on a figure it holds.
- A quick reader then reads each company's `cards/<TICKER>.data.json` and the `INDEX.md` that file names in `index`. The index lists every file already fetched for the company and the script commands for this machine.
- Do not run `--help`, and do not open a script to learn its flags. A quick reader's commands are in the pack's `INDEX.md` under Script commands, ready to copy. A scanner's commands are in its prompt.
- Run a script only for what the files lack: another filing Item, an older filing, a competitor, another search term.
- Analyst targets, ratings, rating actions and consensus estimates come from the data, never from a web search:
  - a quick reader takes them from `analysts` in the data file and in the pack's `sentiment.json`
  - a scanner takes `analyst_count` from `prospects.py`
  - If `sentiment_flags` carries `ANALYSTS_UNAVAILABLE`, write that the consensus was unavailable and go on.
- Search a file over about 100 KB with the Grep tool and read the part you need.

### Where you write

- Work only inside the run folder `DIR/pick-DATE/`, and write your findings to the files your role names.
- Every other file you write goes inside the run folder too, including downloads and scratch files.
- Name each scratch file starting with your role and assignment, e.g. `industries/scan2-utilities-10k.txt`.
- Inside `industries/` and `cards/`, only your role's output files end in `.json`; a scratch file there ends in `.txt` or `.md`. The scripts read every `.json` file there as an industry file or a card.
- Never change `cards/<TICKER>.data.json` or a file inside a pack folder `cards/<TICKER>/`.
- `<TICKER>` in a file name is the dash form of a dotted ticker: `cards/BRK-B.json`, not `cards/BRK.B.json`.
- Never write to the folder above the run folder. Other runs share it, and a generic name like `10k.txt` gets overwritten.

### SEC data and filings

- SEC data comes only through the scripts: `edgar.py`, `filing.py`, `filing.py --url` and `earnings.py`. Never write an HTTP request to sec.gov.
- Never put a person's name, email or other identifier in a request, a URL or a file.
- The fundamental-research skill's scripts, for what the files lack:

  | Command | Returns |
  |---|---|
  | `filing.py SYMBOL --item ITEM` | one Item's text |
  | `filing.py SYMBOL --search TERM` | a passage |
  | `filing.py SYMBOL --item ITEM --diff` | what changed since the previous filing |
  | `filing.py --url URL` | an older filing from the index |
  | `earnings.py SYMBOL` | the earnings releases (8-K Item 2.02 exhibits) |
  | `edgar.py SYMBOL` | financials, filing index, Form 4 |

- `filing.py` cuts an Item at 20,000 characters. Pass `--max-chars` with a larger number for long Items.
- A scanner's prompt gives the `filing.py` and `earnings.py` commands; `edgar.py` sits in the same folder as `filing.py`.

### Sources and evidence

- **Fetch before search.** Before any search, read `primary-sources.md` (next to this file). Fetch the catalog row that fits your question first, and note the date on the page.
- **Sources.** Every claim carries its source and date:
  - A filing is its form, Item and filing date, e.g. "10-K Item 7, 2026-02-20".
  - An article is its outlet and the dateline printed on the page, e.g. "Reuters, 2026-09-14".
  - A figure from a pack file is its origin and the pack's date, e.g. "SEC XBRL via edgar.py, 2026-11-10".
  - Search snippets blend years. Read the dateline on the page itself.
  - A claim without a source and a date stays out of the findings.
- **Skepticism.**
  - Search results rank by popularity and recency, so they cluster around the story everyone is telling now. Treat that story as one hypothesis to test, not as the frame for the research.
  - For each call you make, find at least one source that argues the other side. Prefer primary sources (filings, government statistics, regulator rulings, trade-body data) over coverage of them.
  - A threat reported as gone (a rule withdrawn, a program ended, a competitor retreating) is itself a belief. Write down what would bring it back, and how often that has happened before.
  - Look further back than the news: how the same kind of shock played out over the last five to ten years.
- A claim from memory alone stays out of the findings.
- **Inference.** Separate what a source says from what you infer. Write inference as "Inference:" on its own line.
- **Figures.** Quote the exact figure from the source. Do not round it or restate it.

### Web searches

- **Web searches are a shared, limited allowance.** The whole session has one pool of web searches (about 200), and every subagent draws on it.
- Your prompt gives your cap. Treat it as a hard limit and keep a count.

  | Role | Cap |
  |---|---|
  | Industry scanner | 6 |
  | Quick reader | 1 per company |

- Never spend a search on what the files hold: macro figures (`context/macro.md`), the company's own results and guidance (the pack's `releases/`), analyst targets and consensus (`sentiment.json`), or the text of its filings.
- Fetch primary sources directly before searching: government data (EIA, Census, BLS, FRED), trade-body releases and company investor-relations pages by URL. A direct fetch does not spend a search.
- Save searches for what needs them: news, earnings-call coverage and competitor coverage.
- At the cap, stop searching, and say which claims you could not check.

### What you hand back

- Return to the coordinator one paragraph: the three findings that matter most, the file paths, and the number of searches you used.
- **No verdicts on stocks.** Leave buy, sell and hold judgements out entirely. The output describes industries, businesses and evidence.

## Industry scanner

Search cap: 6, unless the prompt gives another. Output:

- `industries/group<N>.json`: a list of industry objects, in the shape `render_pick.py` reads
- `industries/group<N>.md`: the notes behind them

Your assignment is one sector group:

| Group | Sectors |
|---|---|
| 1 | Technology, Communication Services, Consumer Discretionary, Consumer Staples |
| 2 | Health Care, Financials, Real Estate, Utilities |
| 3 | Industrials, Energy, Materials |

For each industry with meaningful size in your sectors (roughly the Yahoo industry level; merge small ones), find:

1. **Temperature.**
   - The growth outlook from a dated forecast (a trade body, government data, a research house).
   - Where the industry is in its cycle. Start from `context/macro.md`.
   - Pricing power and input costs.
   - Policy and regulation.
   - The structural threats: technology substitutes, government or regulatory substitutes, new and adjacent competitors, customers' bargaining power, suppliers, law and tax. A quiet threat gets the same attention as a newsworthy one.
2. **Sentiment and valuation.**
   - What the market believes now: the sector's price performance, valuation against its own five-to-ten-year range, and fund flows where available.
   - Whether that belief looks stretched or overly gloomy against the fundamentals you found. Background only.
3. **Leaders.** Context only; they do not enter the candidate pool.
   - The top three to five US-listed companies, by revenue or share.
   - For each, whether it is gaining, steady or losing share, and the evidence for that.
4. **Prospects.** Three to five US-listed companies chosen for promise, not size. They are what the industry contributes to the candidate pool, and a leader can be one only when it passes the same tests.
   1. Gather candidate names for all your industries from the filings and the trade press you already read. Spend at most two searches on finding names.
   2. Check them all with ONE call: `prospects.py SYM,SYM,…` (up to 25 tickers a call; a second call only for names found later). It spends no searches. Do not run `edgar.py` or `fundamentals.py` name by name.
      - To keep its output, add `--out` with a file in `context/`, e.g. `context/scan2-prospects.json`. Never put it in `industries/`.
   3. Read each row of `prospects`. `tests.<name>.pass` is true, false or null, and `tests.<name>.figures` holds the numbers:

      | Test | `pass` is true when | `figures` |
      |---|---|---|
      | `trajectory` | revenue is above the same quarter a year earlier in at least 5 of the last 8 quarters, and the trailing-twelve-month net margin is not below the twelve months before | `quarters_up_of_8`, `ttm_revenue_growth`, `net_margin_ttm`, `net_margin_prior_ttm` |
      | `cash` | free cash flow is positive in at least 3 of the last 4 fiscal years, and in the latest year is no smaller than dividends paid (nothing paid counts as covered) | `fcf_positive_years_of_4`, `dividends_covered` |
      | `price` | the free-cash-flow yield is at least 6%, or the trailing P/E is at most 15 | `pe`, `forward_pe`, `fcf_yield`, `change_12m`, `pct_of_52w_high` |
      | `overlooked` | at most 8 analysts, or institutions hold under 60%, or the 12-month price change is below −20% | `analyst_count`, `institutional_ownership`, `change_12m` |

   4. Judge what the script leaves open:
      - A `pass` of null means the script cannot decide from the figures it has. You judge that test from the figures and the filings.
      - `price.pass` is true or null, never false. When it is null, judge the price against the company's own history and its peers. It counts as passed only with the figure that shows it.
      - The `cash` test does not fit banks and REITs: a bank's cash flow includes customer money (row flag `BANK_REVENUE_PROXY`), and a REIT's free cash flow misstates the business. Judge a bank on book value growth and return on equity, and a REIT on dividend coverage from its filings.
      - Yahoo's `institutional_ownership` is unreliable above 1.0. Treat such a figure as unknown and do not pass `overlooked` on it.
      - A row flagged `EDGAR_UNAVAILABLE` has null EDGAR tests (often a foreign filer with no US-GAAP facts). Judge it from its filings, or leave it out.
      - A row flagged `MISSING_DATA` needs its cash and margin figures read with care.
   5. Decide who enters:
      - A prospect passes at least three of the four tests: `tests_passed`, plus each null test you judged as passed.
      - `size_ok` false (market value under $300M) stays out. No other size rule: a large company qualifies on the same tests.
      - A ticker in `not_found` is not in the SEC's list. Check the spelling once; otherwise it stays out.
   6. For each prospect write `ticker`, `name` and `market_cap` from its row, and a `why` naming the tests it passes with figures. Start from the row's `why` and add the tests you judged.
   - An industry with no company that passes gets an empty list, and the notes say so.
5. **Verdict.** `favored`, `neutral` or `unfavored`, with the two or three reasons that decide it. It is your judgement of the fundamentals above, not of what the market or the media favour. It feeds the quick readers' `tailwind` score; it does not decide which prospects enter the pool.
6. **Contrarian mark.** Set `contrarian: true` when an industry is out of favour (weak sentiment, low valuation against its history) while its fundamentals improve. That is where value often hides.

Each object in `industries/group<N>.json`:

```json
{"sector": "Industrials", "industry": "Railroads", "verdict": "favored", "contrarian": false,
 "temperature": "One sentence: the state of the industry now.",
 "growth": "The dated outlook, e.g. 'Carloads +3% in 2027 (AAR, 2026-09-30)'.",
 "sentiment": "One sentence on what the market believes and whether it looks stretched or gloomy.",
 "leaders": [{"ticker": "UNP", "name": "Union Pacific", "trend": "gaining"}],
 "prospects": [{"ticker": "GWR", "name": "Example Short Line", "market_cap": 2.1e9,
                "why": "trajectory: revenue up in 7 of 8 quarters; cash: free cash flow positive in 4 of 4 years; price: P/E 11.0; overlooked: 3 analysts."}],
 "evidence": [{"claim": "...", "source": "...", "date": "2026-09-30"}]}
```

`trend` is one of `gaining`, `steady` or `losing`. Give each industry at least three evidence claims, including at least one against the verdict. The file is one JSON list and nothing else; `pool.py` reads it.

## Quick reader

Output: one `cards/<TICKER>.json` per company assigned to you, with notes in `cards/<TICKER>.md`. Search cap: 1 per company, unless the prompt gives another.

The scripts have run already. Your work is to verify and interpret what they fetched, not to fetch it again. For most companies that is the data file, the index, three to five pack files and at most one `filing.py` call.

### What is on disk for each company

| File | Holds |
|---|---|
| `cards/<TICKER>.data.json` | The headline fields below, and `index`: the path of the pack's `INDEX.md` |
| `cards/<TICKER>/INDEX.md` | Every pack file with its size, the headline figures, what is missing and why, and the script commands |
| `cards/<TICKER>/edgar.json` | Ten years of SEC financials, twelve quarters, TTM, the filing index with links, the last five Form 4s |
| `cards/<TICKER>/releases/<filing date>.txt`, `earnings.json` | The text of the latest eight earnings releases, and their index |
| `cards/<TICKER>/redflags.json` | The 10-K passages around each red-flag term |
| `cards/<TICKER>/sentiment.json` | Dated `news`, `short_volume`, and `analysts`: price `targets`, rating counts, rating `actions` of the last 180 days, EPS and revenue `estimates` |
| `cards/<TICKER>/quick_value.json`, `inputs.json`, `intrinsic.json`, `fundamentals.json` | The quick value, the inputs behind it with their sources, the Graham and Buffett arithmetic, the Yahoo profile and statements |
| `industries/group<N>.json` | The industry scan: find the company's industry object by its `industry` name with the Grep tool |

Fields of `cards/<TICKER>.data.json`:

| Field | Meaning |
|---|---|
| `ticker`, `name`, `origin`, `held`, `industry`, `sector`, `industry_verdict`, `contrarian`, `why`, `health`, `failed_tests` | The pool row. `industry`, `industry_verdict` and `why` are null for a screen name no scan covers. |
| `direction` | `quarters_up_of_8` (quarters with revenue above a year earlier) and `ttm_revenue_growth` |
| `quick_value` | `basis`, `bear`, `base`, `bull`, `irr_5y`, `note`, `scenarios`, and the yardstick tests for a financial, REIT or utility |
| `value_hint` | A starting point for the `value` score, 1 to 5, or null |
| `leverage` | The balance-sheet check: `net_debt` (today's), `ebitda`, `net_debt_to_ebitda`, `interest_coverage`, `ok` (false over 2x or under 6x coverage; null for a financial, REIT or utility, or missing figures), `why`, and `flags` (`LEVERAGE_HIGH`, `DEBT_CHANGED_SINCE_ANNUAL`) |
| `red_flags` | `inputs_flags` that fired, and `terms`: each red-flag term with its count of hits in the 10-K |
| `analysts` | `target_mean` and `count` |
| `insiders` | `buys` and `sells`: open-market transaction counts in the last five Form 4 filings |
| `flags` | Every `inputs.py` and `intrinsic.py` flag code |
| `sentiment_flags` | `NEWS_UNAVAILABLE`, `ANALYSTS_UNAVAILABLE`, `NO_SHORT_VOLUME`: the part Yahoo or FINRA did not answer for |
| `missing` | Pack files that were not built. The index says why. |

### For each company

1. **Competitive position.** What it sells, to whom, its share against the leaders named in the industry scan, and the evidence of a moat: pricing power, switching costs, scale, network or regulatory position. The pack has no 10-K text, so this is the one place a `filing.py SYMBOL --item 1` call is expected.
2. **Direction.** Start from `direction`, then read the quarterly table in `edgar.json` for the margin and cash-flow trend over the latest 8 to 12 quarters. Say whether it is improving or worsening.
   - If `red_flags.inputs_flags` carries `THIN_EDGAR_HISTORY`, `edgar.json` has no annual rows or no 10-K was found: a foreign filer, or filings under a predecessor registrant. Health and direction then rest on fewer figures (Yahoo's statements in `fundamentals.json`). Say so in the card.
3. **Management record.** Guidance against results for the last two to three years, from the files in `releases/`. Add call coverage only when your search is not needed elsewhere.
4. **Red flags.**
   - For each term in `red_flags.terms`, read its passages in `redflags.json`. A hit is a passage to read, not a finding: auditor boilerplate uses the same words.
   - Check the gap between earnings and operating cash flow in `edgar.json`'s annual table.
   - Note an auditor change when a passage or a release shows one.
   - Name each code in `red_flags.inputs_flags` in the card's `red_flags`.
   - If `missing` lists `redflags.json`, say the red-flag search did not run (often a foreign filer with no 10-K).
5. **Insiders.** `insiders` gives the counts; the Form 4 rows in `edgar.json` give the dates and sizes. Grants and tax withholding are left out.
6. **Sentiment** (background only). From `sentiment.json`: the dated `news`, the `short_volume` figure (FINRA daily short-sale volume, not short interest), and the `analysts` targets and rating actions with their dates.
   - If `sentiment_flags` carries `NEWS_UNAVAILABLE`, the company's one search goes to news.
   - A `news` item can be a roundup of several companies. Check that the article is about this company before using it.
7. **Catalysts** in the next twelve months, with dates where known, from the releases and the news.
8. **Quick value.** Read `quick_value`. Its `basis` names what the figures are, and `note` says how they were built:

   | `basis` | What `quick_value` holds | How to use it |
   |---|---|---|
   | `dcf` | `bear`, `base`, `bull` per share, and `irr_5y`: the annual return if the price closes on `base` in five years | The base fair value and its return at today's price |
   | `normalized` | A cyclical company (`CYCLICAL`): `base` is the mid-cycle value, and `bear` and `bull` are null | Use `base`. The latest-year values under `scenarios` are not the quick value. |
   | `book_value` | A bank, insurer or lender: `book_value_tests`, with no `base` and no `irr_5y` | Judge value on price to book against return on equity, and against peers |
   | `reit` | A REIT: `reit_tests`, with no `base` and no `irr_5y` | Judge value on price to the AFFO proxy, the dividend yield and its coverage |
   | `utility` | A utility: `utility_tests`, with no `base` and no `irr_5y` | Judge value on P/E, P/B, return on equity and the dividend yield |
   | null | No value: free cash flow is not positive, the statements are in another currency than the price (`CURRENCY_MISMATCH`), or the inputs did not run | Say so, and judge value on multiples from `fundamentals.json` |

   - If `basis` is null and `red_flags.inputs_flags` carries `CURRENCY_MISMATCH`, say the quick value could not be computed, score `value` from multiples in the price currency, and name the flag in the card's `red_flags`.
   - The figures rest on untested defaults. Check the growth and discount rate in `inputs.json` against what you read in steps 2 and 3.
   - A `base` several times the price, or far from the analysts' `target_mean`, is more often a data problem than a bargain: an ADR share ratio, a foreign filer's reporting currency, `SHARE_CLASSES_COMBINED`, or one unusual year. Say which, and score `value` on what you can verify.
   - `value_hint` is a starting point for the `value` score, not the score. It comes from `irr_5y`: 5 at 15% a year or more, 4 at 10%, 3 at 6%, 2 at 0, else 1, and at most 3 when `leverage.ok` is false. Move it for what steps 2 to 7 found, and give the reason. When it is null, score from the yardstick.
   - Take debt and interest coverage from `leverage`, not from `edgar.json`'s annual table or quality checklist: those are the last 10-K's, and `DEBT_CHANGED_SINCE_ANNUAL` means debt has moved a lot since. Name `leverage.why` in the card's `value` reason when `ok` is false.
   - In the card, `quick_value` is `{"fair_value": <base>, "irr_5y": <irr_5y>}`. Both are null when `basis` is a yardstick or null; the `value` reason then names the yardstick and its figures.
9. **Health the screen did not settle.** `health` of `passed` stays as it is. For any other value, judge health here and write the result in the card's `health`, starting with the original value, e.g. "financial: return on equity 12% over five years, equity 9.8% of assets".

   | `health` | What to judge |
   |---|---|
   | `financial`, `judge_in_quick_read` | Book value per share growth, return on equity over five years, capital ratios, and reserve or credit trends |
   | `incomplete`, `not_found` | Whether the filings that exist show a going business with positive cash flow and a sound balance sheet. Say what could not be checked. |
   | `unchecked` | The health screen did not run: check revenue trend, free cash flow, share count and net debt in `edgar.json` |

### The card

Score four parts from 1 to 5, each with a one-line reason:

| Score | 1 means | 5 means |
|---|---|---|
| `quality` | commodity business, no moat, weak returns | durable moat, high returns on capital, strong balance sheet |
| `direction` | revenue and margins falling, guidance cut | revenue and margins rising, guidance met or raised |
| `tailwind` | the industry scan's unfavored verdict with no contrarian mark, company losing share | favored industry, company gaining share |
| `value` | quick value well below the price | quick value well above the price, with a five-year return above 15% a year |

- When `industry_verdict` is null, no scan covers the company. Score `tailwind` from `context/macro.md` and the company's own filings, and say so in the reason.

Finish each card with:

- `missing`: what the market may be missing, in one sentence
- `bad_pick`: what would make this a bad pick, in one sentence

Each `cards/<TICKER>.json`:

```json
{"ticker": "UNP", "name": "Union Pacific", "industry": "Railroads", "origin": "industry",
 "scores": {"quality": 4, "direction": 3, "tailwind": 4, "value": 3},
 "reasons": {"quality": "...", "direction": "...", "tailwind": "...", "value": "..."},
 "missing": "...", "bad_pick": "...", "health": "passed",
 "quick_value": {"fair_value": 0.0, "irr_5y": 0.0}, "red_flags": ["..."],
 "evidence": [{"claim": "...", "source": "...", "date": "..."}]}
```

- Scores are whole numbers from 1 to 5.
- Copy `ticker`, `name`, `origin` and `industry` from the data file. When `industry` is null there, write the Yahoo industry from `fundamentals.json`.
- Keep `health` as the data file gives it, except where step 9 has you write the judgement.
- Every evidence claim has a `source` and a `date`. `pick_assemble.py` rejects a card with a score outside 1 to 5 or an evidence claim without them.
