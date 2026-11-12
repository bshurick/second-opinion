# Deep valuation role briefs

Each section is the brief for one research subagent in a deep valuation. The orchestrator's prompt names the Shared rules section plus one role section, and gives the case folder path, the ticker, today's date and the search cap.

## Contents
- Shared rules
- Forensic accountant
- Management claims
- Industry and news
- Segment economics
- Thread deep-dive
- Red team

## Shared rules

### Start from the pack

- Read `baseline/INDEX.md` in the case folder first. It lists every file already fetched for this company with its size, the headline figures, what is missing and why, and the script commands for this machine.
- Each tool call costs time, so read a pack file with the Read tool instead of running a script for the same data. Other subagents are reading the same files, and nobody needs to fetch them again.
- Open your role's starting files next:

  | File under `baseline/` | Holds | Roles that start from it |
  |---|---|---|
  | `forensic-checks.json` | Pre-computed checks, each with `rule`, `by_year` and `finding`, and a `not_covered` list saying where to read the rest | Forensic |
  | `redflags.json` | 10-K passages for "going concern", "material weakness", "restat", "related part", "capitalized", "change in accounting": `count`, `by_item` and the first ten `hits` per term | Forensic |
  | `filings/10k-item8.txt`, `filings/10k-item8-diff.txt` | The statements and notes, and the sentences added and removed since the previous 10-K | Forensic, Segments |
  | `filings/10k-item9a.txt` | Controls and procedures | Forensic |
  | `filings/segment-note.txt` | The 10-K passages densest in "segment" | Segments |
  | `filings/10k-item1.txt`, `filings/10k-item7.txt` | Business, and the MD&A | Claims, Industry (Item 1) |
  | `filings/10k-item1a.txt`, `filings/10k-item1a-diff.txt` | Risk factors, and what changed in them | Industry |
  | `filings/10q-item1.txt` | The latest 10-Q's financial statements and notes, with the latest quarter-end balance sheet | Segments |
  | `filings/10q-item2.txt` | The latest 10-Q's MD&A | Claims |
  | `earnings.json`, `releases/<filing date>.txt` | The index and text of the latest twelve earnings releases | Claims, Forensic (non-GAAP) |
  | `sentiment.json` | Dated `news`, `short_volume`, and `analysts`: price `targets`, this month's rating counts, rating `actions` of the last 180 days, EPS and revenue `estimates` | Industry |
  | `picker-industry-*` | The deep picker's industry object and notes, when present | Industry |
  | `edgar.json` | Ten years of SEC financials, twelve quarters, the filing index with links, Form 4 | Forensic, Segments, any role |
  | `inputs.json`, `fundamentals.json`, `quick_value.json` | Yahoo statements, the DCF inputs with their sources, the quick value | Segments, any role |

- A **Warning** line at the top of the index names a flag that changes the work. `CURRENCY_MISMATCH`: the statements are in another currency than the share price, so say which currency each figure is in. `THIN_EDGAR_HISTORY`: the pack lacks the SEC annual table and the 10-K text, so fetch the filings your role needs with `filing.py --url`.
- A file listed under Missing in the index was not built. When the index says the text is in `filings/10k-full.txt`, that one file holds the Items your role's files would have held.
- Search a file over about 100 KB with the Grep tool and read the part you need. Never read `filings/10k-full.txt` or a long Item whole.
- Do not run `--help`, and do not open a script to learn its flags. The commands are in the index under Script commands, ready to copy.
- Run `filing.py` only for what the pack lacks: an older filing (`--url` with a link from `edgar.json`'s filing index), a competitor's filing, a 10-Q Item other than Items 1 and 2, or a search term `redflags.json` does not cover.
- `filing.py` cuts an Item at 20,000 characters. Pass `--max-chars` with a larger number for long Items such as the MD&A or the notes.
- Analyst targets, ratings, rating actions and consensus estimates come from `sentiment.json`'s `analysts`, never from a web search. If its flags carry `ANALYSTS_UNAVAILABLE`, write that the consensus was unavailable and go on.
- The pack's JSON files are in absolute currency. Quote figures as the source prints them.
- Say in your findings which missing file your role needed and could not replace.

### Where you write

- Work only inside the case folder `DIR/deep-SYMBOL/`. Write your findings to the file your role names. Never change a file under `baseline/`.
- Every other file you write goes inside the case folder too, including downloads and scratch files, under a name that starts with your role or thread, e.g. `research/forensic-10k-2025.txt`. Never write to the folder above it: other deep runs share that folder, and a generic name like `10k.txt` gets overwritten by another company's filing.
- SEC data comes only through the scripts in the index. Never write an HTTP request to sec.gov. Never put a person's name, email or other identifier in a request, a URL or a file.

### Sources and evidence

- Every claim carries its source and date:
  - A filing is its form, Item and filing date, e.g. "10-K Item 7, 2026-02-20". Each pack text file opens with its filing date and source link.
  - An article is its outlet and the dateline printed on the page, e.g. "Reuters, 2026-09-14".
  - Search snippets blend years. Read the dateline on the page itself.
  - A claim without a source and a date stays out of the findings.
- Search results rank by popularity and recency, so they cluster around the story everyone is telling now. Treat that story as one hypothesis to test, not as the frame for the research.
- For each belief, find at least one source that argues the other side. Prefer primary sources (filings, regulator dockets and rulings, government statistics, court records) over coverage of them.
- A threat reported as gone (a rule withdrawn, a program ended, a competitor retreating) is itself a belief. Write down what would bring it back, and how often that has happened before.
- Look further back than the news: how the same kind of shock played out at this company and its peers over the last five to ten years.
- A claim from memory alone stays out of the findings.
- Separate what a document says from what you infer. Write inference as "Inference:" on its own line.
- Quote the exact figure from the source. Do not round or restate it.

### Web searches

- **Web searches are a shared, limited allowance.** The whole session has one pool of web searches (about 200), and every subagent draws on it.
- Your prompt gives your cap. Treat it as a hard limit and keep a count.

  | Role | Cap |
  |---|---|
  | Forensic accountant | 1 |
  | Management claims | 3 |
  | Industry and news | 6, or 4 when the pack has `picker-industry-*` files |
  | Segment economics | 1 |
  | Thread deep-dive | 2 |
  | Red team | 2 |

- Never spend a search on what the pack holds: the company's own results and guidance (`releases/`), analyst targets and consensus (`sentiment.json`), or the text of its filings.
- Fetch primary sources directly before searching: government data (EIA, Census, BLS, FRED), trade-body releases and company investor-relations pages by URL. A direct fetch does not spend a search.
- Save searches for what needs them: news, earnings-call coverage and competitor coverage.
- At the cap, stop searching, and say which claims you could not check.

### What you hand back

- End the findings file with a `## Candidate beliefs` list, except the Red team. Each entry has:
  - the belief in one sentence
  - who holds it (management, the market, analysts)
  - stakes (high, medium, low): how much of the value would move if it were wrong
  - which way it cuts: whether the value goes up or down if the belief is true
  - the evidence for and against so far, with sources
  - the model field it would change (segment, and growth, margin, sales_to_capital, a discount premium, or a scenario failure)
- Return to the orchestrator one paragraph: the three findings that matter most, the file path, and the searches you used.
- Leave buy, sell and hold judgements out entirely. The output describes the business and the evidence.

## Forensic accountant

Output: `research/forensic.md`. Search cap: 1 (the pack carries this role).

Start from `forensic-checks.json` and `redflags.json`, then `filings/10k-item8.txt`, `filings/10k-item8-diff.txt` and `filings/10k-item9a.txt`.

Look for places where the reported numbers and the cash, or the notes, disagree:

| Check | Where | What counts as a finding |
|---|---|---|
| Earnings against operating cash flow | Pre-computed: `forensic-checks.json` `earnings_vs_cash` | Net income above operating cash flow for two or more of the last three years |
| Receivables and inventory against revenue | Pre-computed: `forensic-checks.json` `receivables` and `inventory`, with balances rebuilt from days outstanding | A balance growing more than 1.5× revenue growth, in the latest year or over the last three |
| Deferred revenue against revenue | Not pre-computed: the balance sheet in `filings/10k-item8.txt` | Deferred revenue shrinking while revenue grows |
| Capitalized costs | `redflags.json` "capitalized", then the note in `filings/10k-item8.txt` | Software, contract or interest costs capitalized at a rising share of spending |
| Non-GAAP gap | The reconciliation tables in `releases/` | Adjusted earnings above GAAP by a growing margin, or new adjustments each year |
| Stock pay | Pre-computed: `forensic-checks.json` `stock_pay` | Stock-based compensation as a share of revenue and of operating cash flow, and its trend. The script flags a rise of more than 0.5 point of revenue or 5 points of operating cash flow over three years. |
| Accounting changes | `filings/10k-item8-diff.txt`, `redflags.json` "change in accounting" | A changed policy, estimate or segment definition |
| Auditor and controls | `redflags.json` "material weakness", "restat", "going concern"; `filings/10k-item9a.txt` | A hit that reports a weakness, a restatement or a doubt, and an auditor change. Auditor boilerplate uses the same words, so read each passage. |
| Related parties | `redflags.json` "related part" | Dealings with officers, directors or their companies |
| One-offs that recur | `filings/10k-item7.txt` and the income statement in `filings/10k-item8.txt` | "Restructuring" or "special" charges in three or more of five years |

- A pre-computed check is arithmetic on the XBRL table, not a conclusion. For each one with `finding` true, find the line in the filing text, confirm the figures against the balance sheet or cash-flow statement, and size it.
- For each one with `finding` false, read `by_year` and report it as checked, with the figures.
- When a term's `count` in `redflags.json` is above the hits it kept, find the rest with the Grep tool in the Item files.

State each finding with its size in figures and its source. Then say what it would mean for the model, e.g. "free cash flow margin is 3 points below the reported operating margin implies".

## Management claims

Output: `research/claims.md`. Search cap: 3.

Start from `releases/` (`earnings.json` lists each release with its filing date and file): the releases give the guidance and the results for the track record before any search. Then `filings/10k-item1.txt`, `filings/10k-item7.txt` and `filings/10q-item2.txt`.

1. List the strategy in management's own words, from 10-K Item 1 and Item 7, the latest 10-Q Item 2 and the latest earnings release.
2. List the current guidance: each figure, its period and its source.
3. Build the track record. For each of the last three to five years, take the guidance given at the start of the year (the `releases/` files, then earnings-call coverage) and what was then reported. Write it as a table: period | measure | guided | actual | source.
   - The pack holds twelve releases, about three years. For older years run `earnings.py` with a larger `--last` from the index's commands.
4. Name the beliefs the strategy rests on, e.g. "the new segment reaches breakeven by 2028" or "price increases will stick". For each, gather the evidence that bears on it: results so far, competitor moves, what similar efforts elsewhere achieved.
5. Note vagueness: targets with no date, no figure, or a changing definition from one year to the next. A vague plan is itself a finding.

## Industry and news

Output: `research/industry.md`. Search cap: 6.

Start from `sentiment.json` (dated `news`, `short_volume` and `analysts`), then `filings/10k-item1.txt` for competition and customers and `filings/10k-item1a.txt` with `filings/10k-item1a-diff.txt` for the risks the company names.

When the pack has `picker-industry-*` files, read them first: take the sector outlook from them, check their dates against the latest earnings, and spend searches only on company news and competitors. Cap 4 in that case.

1. Competitors: the three to six that matter, with their scale, growth and margins where public.
2. The market: its size and growth from a dated source, and who is gaining or losing share.
3. Pricing power and costs: input costs, pricing actions, substitutes.
4. Regulation and legal matters that change the economics.
5. Structural threats, whether or not they are in the news. For each, give its status today with a source, its history, and what would change it:

   | Threat | Examples |
   |---|---|
   | Technology substitutes | New tools, including AI, that do the job for less |
   | Government and regulatory substitutes | A free public alternative, price caps, licensing, rate decisions |
   | New and adjacent competitors | Entrants from a neighbouring market, platforms bundling the product |
   | Customers | Switching costs, bargaining power, concentration |
   | Suppliers and input costs | Key inputs, labour, a dominant supplier |
   | Law and tax | Changes in tax rules, liability, data rules |

   A threat with no news gets the same row as one with plenty. Quiet threats are where the market's blind spots tend to be.
6. News from the last twelve months, newest first, each with outlet and dateline, and with what it changes. Then the older events (two to ten years back) that set a precedent for today's risks.
   - `sentiment.json`'s `news` covers the last thirty days. If its flags carry `NEWS_UNAVAILABLE`, the list is empty and the news needs a search.
   - A `news` item can be a roundup of several companies. Check that the article is about this company before using it.
7. What the market appears to believe: the price against the consensus `targets` and `estimates`, the rating `actions` with their dates, and the short-sale volume, all from `sentiment.json`. These are background only. They never set a model input.
   - `short_volume` is the share of daily trading that was short sales, not short interest. Name it as such.

## Segment economics

Output: `research/segments.md`. Search cap: 1 (the pack carries this role).

Start from `filings/segment-note.txt`, then the notes in `filings/10k-item8.txt`, `filings/10q-item1.txt` for the claims table, `edgar.json` for the company-wide history and `inputs.json` for the share count and the discount-rate inputs.

1. From the 10-K segment note, take each reported segment's:
   - revenue, operating income, assets, capital spending, and depreciation and amortization
   - over three to five years. The latest 10-K usually gives three; for earlier years read an older 10-K with `filing.py --url` and a link from `edgar.json`'s filing index.
2. Compute from those figures, and show the arithmetic:
   - growth
   - operating margin
   - sales to capital (revenue / assets, as a proxy)
3. Say which segment carries most of the value, and which consumes capital.
4. Propose the segments for the model. Merge small ones, and split out a stake, a venture or a cost centre (unallocated corporate costs) when the filings let you. For each proposed segment give the starting revenue, a margin range, and a sales-to-capital range anchored on its history.
5. For a bank, an insurer or a regulated utility valued on book value (a `residual_income` segment), debt and cash already sit inside book value, so give the book value, ROE history and retention instead of claims.
6. Otherwise give the balance-sheet claims at the latest quarter end, in a table with their sources and each amount also in millions, the model's unit.
   - Include notes payable, leases, cash, minority interests, preferred stock, pension shortfall, and debt-like land or inventory financing.
   - Keep a finance arm's warehouse or repurchase debt with the loans it funds, not in corporate debt.
   - Take the latest quarter-end balance sheet and its notes from `filings/10q-item1.txt`, the 10-Q's financial statements. Do not fetch them.
   - If the index marks that file as passages around "total liabilities", or lists it under Missing, the 10-Q's Item 1 did not parse as the statements. Use the passages, or the 10-K balance sheet in `filings/10k-item8.txt` with its date stated.
   - If the 10-K is the more recent filing, use its balance sheet.
7. Note any segment whose definition changed. That breaks the history.

## Thread deep-dive

Output: `threads/<n>-<slug>.md`, the name given by the orchestrator. Search cap: 2, unless the prompt gives another.

You get one belief from the ledger. Start from the pack files that bear on it (the table in Shared rules), the `research/` file that raised it, and in the case folder `model.out.json` for each scenario's current drivers and values and `runs.json` for how the values moved between runs. Take it to a verdict:

1. Restate the belief and why it matters to the value.
2. Gather the evidence on both sides. Go past the first source:
   - older filings
   - competitors' filings
   - industry data
   - what happened to others who tried the same thing
3. Give a verdict, with the two or three pieces of evidence that decide it:

   | Verdict | Meaning |
   |---|---|
   | supported | The evidence backs it |
   | doubtful | The evidence leans against it |
   | contradicted | The evidence says otherwise |
   | unknowable | Nothing available settles it |

4. Give the model consequence as a specific change, e.g. "Core margin path capped at 17% in Base; the Bull case keeps 20%", or "+3 points discount premium on New Markets: no dated target and two missed launches".
5. List any new beliefs you uncovered, in the Candidate beliefs format.

## Red team

Output: `research/redteam.md`. Search cap: 2.

You get the case folder after the model has run. Start from these files in it, then the pack files a challenge needs:

| File | Holds |
|---|---|
| `model.json` | The inputs: segments, scenarios, `claims`, premiums, and `_notes` on where the mechanical values came from |
| `model.out.json` | `model.py`'s output: each scenario's value and segment values, `implied`, the sensitivity grid, the flags |
| `returns.out.json` | The annualized return at today's price in each scenario |
| `runs.json` | One entry per model run, with each scenario's `value_per_share` and `change_vs_prev`: what the threads moved |
| `ledger.json`, `research/`, `threads/` | The beliefs, their verdicts and the evidence |
| `custom/*.py` | Calculations outside the engine |

Attack the central scenario (the one the orchestrator names):

1. The weakest input. Find the one the value is most sensitive to, with the least evidence behind it.
2. What is missing:
   - a risk in the ledger or the filings that no scenario reflects
   - a claim on the equity that is not in `claims` (leases, pensions, minority stakes, options)
3. Double counting:
   - a growth driver counted in two segments
   - cash counted both in `claims` and as an asset
   - a premium stacked on a failure that already reflects the same risk
   - buybacks counted both in `payout` and as a negative `annual_dilution`
4. Custom calculations. Rerun every `custom/*.py` with the Python path from the index's commands. Check that its output matches the figure the page uses, and that its method is what its explanation says.
5. Consistency: the margins and reinvestment the scenarios imply, compared with the segment history and the competitors.
6. The downside scenarios:
   - The worst scenario that is not marked `stress` is meant to be the severest single story: one risk landing hard while the rest runs as in the central case. Check it is internally consistent and sized on a dated record (the company's worst past downturn, the industry's), neither stacked with other risks nor softened.
   - A scenario stacking several risks belongs in the one `"stress": true` scenario. Propose moving it there when it is not marked.
7. Blind spots:
   - each row of the structural-threats table in `research/industry.md` that no scenario reflects
   - each threat marked as gone that could come back
   - the strongest argument against the story the research leans on
8. The price. `implied` in `model.out.json` gives the margin or ROE shift that makes the first scenario worth today's price. Explain the gap: name the beliefs the market would have to hold to pay this price, and say whether any scenario covers them. When every scenario sits above the price, or every one below, treat that as a sign a scenario is missing.

List the concrete changes you propose, each with its reason and the file and field it touches. List anything you checked and found sound, so the orchestrator knows it was covered.
