# Deep picker role briefs

Each section is the brief for one deep-picker subagent. The coordinator hands a subagent the absolute path of this file and names two sections to follow: Shared rules, plus the agent's role. The prompt also carries:

- the run folder
- today's date
- the resolved script commands
- the role's assignment: a sector group for a scanner, or about five tickers for a quick reader

## Contents
- Shared rules
- Industry scanner
- Quick reader

## Shared rules

- **Where to write.**
  - Work only inside the run folder `DIR/pick-DATE/`, and write your findings to the file your role names.
  - Every other file you write goes inside the run folder too, including downloads and scratch files.
  - Name each file starting with your role and assignment, e.g. `industries/scan2-health-utilities-10k.txt`.
  - Never write to the folder above it. Other runs share that folder, and a generic name like `10k.txt` gets overwritten.
- **Fetch before search.** Before any search, read `primary-sources.md` (next to this file) and the run folder's `context/macro.md`. Fetch the catalog row that fits your question first, and note the date on the page.
- **SEC data only through the scripts.**
  - Use `edgar.py`, `filing.py`, `filing.py --url` and `earnings.py`. Never write an HTTP request to sec.gov.
  - Never put a person's name, email or other identifier in a request, a URL or a file.
- **Filings.** Fetch them with the fundamental-research skill's scripts:

  | Command | Returns |
  |---|---|
  | `edgar.py SYMBOL` | financials, filing index, Form 4 |
  | `filing.py SYMBOL --item ITEM` | one Item's text |
  | `filing.py SYMBOL --search TERM` | a passage |
  | `filing.py SYMBOL --item ITEM --diff` | what changed since the previous filing |
  | `filing.py --url URL` | an older filing from the index |
  | `earnings.py SYMBOL` | the earnings releases (8-K Item 2.02 exhibits) |

  - `filing.py` cuts an Item at 20,000 characters. Pass `--max-chars` with a larger number for long Items.
- **Web.** Use page fetching and web search for industry data, forecasts, earnings coverage and news, within your search cap below.
- **Sources.** Every claim carries its source and date:
  - A filing is its form, Item and filing date, e.g. "10-K Item 7, 2026-02-20".
  - An article is its outlet and the dateline printed on the page, e.g. "Reuters, 2026-09-14".
  - Search snippets blend years. Read the dateline on the page itself.
  - A claim without a source and a date stays out of the findings.
- **Skepticism.**
  - Search results rank by popularity and recency, so they cluster around the story everyone is telling now. Treat that story as one hypothesis to test, not as the frame for the research.
  - For each call you make, find at least one source that argues the other side. Prefer primary sources (filings, government statistics, regulator rulings, trade-body data) over coverage of them.
  - A threat reported as gone (a rule withdrawn, a program ended, a competitor retreating) is itself a belief. Write down what would bring it back, and how often that has happened before.
  - Look further back than the news: how the same kind of shock played out over the last five to ten years.
- **Web searches are a shared, limited allowance.** The whole session has one pool of web searches (about 200), and every subagent draws on it.
  - Your prompt gives your cap. Treat it as a hard limit and keep a count.
  - Fetch primary sources directly before searching: SEC filings through the scripts, and government data (EIA, Census, BLS, FRED), trade-body releases and company investor-relations pages by URL. A direct fetch does not spend a search.
  - Save searches for what needs them: news, sentiment, analyst actions and competitor coverage.
  - At the cap, stop searching, and say which claims you could not check.
  - Report the number of searches you used in your reply.
- A claim from memory alone stays out of the findings.
- **Inference.** Separate what a source says from what you infer. Write inference as "Inference:" on its own line.
- **Figures.** Quote the exact figure from the source. Do not round it or restate it.
- **Your reply.** Return to the coordinator one paragraph: the three findings that matter most, the file path, and the searches you used.
- **No verdicts on stocks.** Leave buy, sell and hold judgements out entirely. The output describes industries, businesses and evidence.

## Industry scanner

Search cap: 8, unless the prompt gives another. Output:

- `industries/<group>.json`: a list of industry objects, in the shape `render_pick.py` reads
- `industries/<group>.md`: the notes behind them

Your assignment is one sector group:

| Group | Sectors |
|---|---|
| 1 | Technology, Communication Services, Consumer Discretionary, Consumer Staples |
| 2 | Health Care, Financials, Real Estate, Utilities |
| 3 | Industrials, Energy, Materials |

For each industry with meaningful size in your sectors (roughly the Yahoo industry level; merge small ones), find:

1. **Temperature.**
   - The growth outlook from a dated forecast (a trade body, government data, a research house).
   - Where the industry is in its cycle.
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
   - **Trajectory.** Revenue and operating margin improving over the last 8 to 12 quarters, or share rising. Check with `edgar.py SYMBOL --quarters 12`.
   - **Cash.** Free cash flow positive in most of the last four years, and covering the dividend and buyback.
   - **Price.** Cheap against its own history or its peers, from `fundamentals.py SYMBOL` (P/E, EV, free cash flow) and the filings.
   - **Overlooked.** Few analysts (`analyst_count` in `fundamentals.py`), low institutional ownership (`institutional_ownership`), or a selloff the fundamentals do not explain.
   - Market value at least $300M. No other size rule: a large company qualifies on the same tests.
   - Find names from the filings and the trade press you already read, then check them with the scripts, which spend no searches. Spend at most two searches on finding names.
   - For each: `ticker`, `name`, `market_cap`, and a `why` naming the tests it passes with figures. A prospect that passes fewer than three of the four tests stays out.
   - An industry with no company that passes gets an empty list, and the notes say so.
5. **Verdict.** `favored`, `neutral` or `unfavored`, with the two or three reasons that decide it. It is your judgement of the fundamentals above, not of what the market or the media favour. It feeds the quick readers' `tailwind` score; it does not decide which prospects enter the pool.
6. **Contrarian mark.** Set `contrarian: true` when an industry is out of favour (weak sentiment, low valuation against its history) while its fundamentals improve. That is where value often hides.

Each object in `industries/<group>.json`:

```json
{"sector": "Industrials", "industry": "Railroads", "verdict": "favored", "contrarian": false,
 "temperature": "One sentence: the state of the industry now.",
 "growth": "The dated outlook, e.g. 'Carloads +3% in 2027 (AAR, 2026-09-30)'.",
 "sentiment": "One sentence on what the market believes and whether it looks stretched or gloomy.",
 "leaders": [{"ticker": "UNP", "name": "Union Pacific", "trend": "gaining"}],
 "prospects": [{"ticker": "GWR", "name": "Example Short Line", "market_cap": 2.1e9,
                "why": "Revenue up 10 of the last 12 quarters; FCF positive 4 of 4 years; P/E 11 vs 5-yr median 16; 3 analysts."}],
 "evidence": [{"claim": "...", "source": "...", "date": "2026-09-30"}]}
```

`trend` is one of `gaining`, `steady` or `losing`. Give each industry at least three evidence claims, including at least one against the verdict.

## Quick reader

Output: one `cards/<TICKER>.json` per company assigned to you, with notes in `cards/<TICKER>.md`. Search cap: 2 per company, unless the prompt gives another.

For each company:

1. **Competitive position.** What it sells, to whom, its share against the leaders named in the industry scan, and the evidence of a moat: pricing power, switching costs, scale, network or regulatory position.
2. **Direction.** Revenue, margin and cash-flow trend over the latest 8 to 12 quarters (`edgar.py SYMBOL --quarters 12`), and whether it is improving or worsening.
3. **Management record.** Guidance against results for the last two to three years. Start from `earnings.py SYMBOL` (the earnings releases), then add call coverage.
4. **Red flags.**
   - Run `filing.py SYMBOL --search` for "going concern", "material weakness", "restat" and "related part".
   - Check the gap between earnings and operating cash flow.
   - Note an auditor change.
5. **Insiders.** Form 4 buying and selling in the last year (`edgar.py SYMBOL --form4 5`).
6. **Sentiment** (background only). Short volume and dated news from `sentiment.py SYMBOL` (its short figure is FINRA daily short-sale volume, not short interest), then analyst actions and target changes with dates.
7. **Catalysts** in the next twelve months, with dates where known.
8. **Quick value.**
   - Run the valuation skill's `inputs.py SYMBOL`, then `dcf.py` on its three `dcf_scenarios`, then `returns.py` in `convergence` mode.
   - Check the `inputs.py` flags: `SHARE_CLASSES_COMBINED`, `CORPORATE_ACTION_SUSPECTED`, `LARGE_MINORITY_INTEREST`, `CYCLICAL` and `CYCLE_BASE_SPLIT`. Name each one that fired in `red_flags`.
   - For `CYCLICAL`, run the valuation skill's `intrinsic-inputs.py SYMBOL` piped into `intrinsic.py` and read the `normalized` block in its output; base the quick value on it, not on the latest year.
   - Report the base fair value and its five-year annual return at today's price.
   - For a bank, insurer or REIT, give the measures the valuation skill names for that kind of business instead.
9. **Financial-filer health.** For a bank, insurer or lender, which the health screen sets aside, judge health here: book value per share growth, return on equity over five years, capital ratios, and reserve or credit trends. Write the result in `health`.

Then score four parts from 1 to 5, each with a one-line reason:

| Score | 1 means | 5 means |
|---|---|---|
| `quality` | commodity business, no moat, weak returns | durable moat, high returns on capital, strong balance sheet |
| `direction` | revenue and margins falling, guidance cut | revenue and margins rising, guidance met or raised |
| `tailwind` | the industry scan's unfavored verdict with no contrarian mark, company losing share | favored industry, company gaining share |
| `value` | quick value well below the price | quick value well above the price, with a five-year return above 15% a year |

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

Scores are whole numbers. Keep `origin` and `health` as the coordinator gave them, except for a financial filer, where you write the health judgement.
