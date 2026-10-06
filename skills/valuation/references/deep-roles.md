# Deep valuation role briefs

Each section is the brief for one research subagent in a deep valuation. The orchestrator hands a subagent the Shared rules section plus its own role section, the case folder path, the ticker and today's date.

## Contents
- Shared rules
- Forensic accountant
- Management claims
- Industry and news
- Segment economics
- Thread deep-dive
- Red team

## Shared rules

- Work only inside the case folder `DIR/deep-SYMBOL/`. Write your findings to the file your role names.
- Every other file you write goes inside the case folder too, including downloads and scratch files, under a name that starts with your role or thread, e.g. `research/forensic-10k-2025.txt`. Never write to the folder above it: other deep runs share that folder, and a generic name like `10k.txt` gets overwritten by another company's filing.
- Fetch filings with the fundamental-research skill's scripts:
  - `edgar.py SYMBOL` (financials, filing index, Form 4)
  - `filing.py SYMBOL --item ITEM` (one Item's text)
  - `filing.py SYMBOL --search TERM` (a passage)
  - `filing.py SYMBOL --item ITEM --diff` (what changed since the previous filing)
  - `filing.py --url URL` (an older filing from the index)
  - `filing.py` cuts an Item at 20,000 characters. Pass `--max-chars` with a larger number for long Items such as the MD&A or the notes.
- Use web search and page fetching for 8-K exhibits, earnings-call coverage, competitors and news.
- Every claim carries its source and date:
  - A filing is its form, Item and filing date, e.g. "10-K Item 7, 2026-02-20".
  - An article is its outlet and the dateline printed on the page, e.g. "Reuters, 2026-09-14".
  - Search snippets blend years. Read the dateline on the page itself.
  - A claim without a source and a date stays out of the findings.
- Search results rank by popularity and recency, so they cluster around the story everyone is telling now. Treat that story as one hypothesis to test, not as the frame for the research.
- For each belief, find at least one source that argues the other side. Prefer primary sources (filings, regulator dockets and rulings, government statistics, court records) over coverage of them.
- A threat reported as gone (a rule withdrawn, a program ended, a competitor retreating) is itself a belief. Write down what would bring it back, and how often that has happened before.
- Look further back than the news: how the same kind of shock played out at this company and its peers over the last five to ten years.
- If your web-search budget runs out, say so, and say which claims rest on what you had. A claim from memory alone stays out of the findings.
- Separate what a document says from what you infer. Write inference as "Inference:" on its own line.
- Quote the exact figure from the source. Do not round or restate it.
- End the findings file with a `## Candidate beliefs` list, except the Red team. Each entry has:
  - the belief in one sentence
  - who holds it (management, the market, analysts)
  - stakes (high, medium, low): how much of the value would move if it were wrong
  - which way it cuts: whether the value goes up or down if the belief is true
  - the evidence for and against so far, with sources
  - the model field it would change (segment, and growth, margin, sales_to_capital, a discount premium, or a scenario failure)
- Return to the orchestrator one paragraph: the three findings that matter most, and the file path.
- Leave buy, sell and hold judgements out entirely. The output describes the business and the evidence.

## Forensic accountant

Output: `research/forensic.md`.

Look for places where the reported numbers and the cash, or the notes, disagree:

| Check | Where | What counts as a finding |
|---|---|---|
| Earnings against operating cash flow | `edgar.py` annual table | Net income above operating cash flow for two or more of the last three years |
| Receivables, inventory, deferred revenue against revenue | `edgar.py` annual and quarterly | A balance growing more than 1.5× revenue growth, or deferred revenue shrinking while revenue grows |
| Capitalized costs | `filing.py --search "capitalized"` on the 10-K | Software, contract or interest costs capitalized at a rising share of spending |
| Non-GAAP gap | 8-K Item 2.02 exhibit | Adjusted earnings above GAAP by a growing margin, or new adjustments each year |
| Stock pay | `edgar.py` | Stock-based compensation as a share of revenue and of operating cash flow, and its trend |
| Accounting changes | `filing.py --item 8 --diff`, `--search "change in accounting"` | A changed policy, estimate or segment definition |
| Auditor and controls | `--search "material weakness"`, `"restat"`, `"going concern"`, `--item 9A` | Any hit, and an auditor change |
| Related parties | `--search "related part"` | Dealings with officers, directors or their companies |
| One-offs that recur | Income statement and MD&A | "Restructuring" or "special" charges in three or more of five years |

State each finding with its size in figures and its source. Then say what it would mean for the model, e.g. "free cash flow margin is 3 points below the reported operating margin implies".

## Management claims

Output: `research/claims.md`.

1. List the strategy in management's own words, from 10-K Item 1 and Item 7, the latest 10-Q Item 2 and the latest earnings release.
2. List the current guidance: each figure, its period and its source.
3. Build the track record. For each of the last three to five years, take the guidance given at the start of the year (8-K Item 2.02 exhibits, earnings-call coverage) and what was then reported. Write it as a table: period | measure | guided | actual | source.
4. Name the beliefs the strategy rests on, e.g. "the new segment reaches breakeven by 2028" or "price increases will stick". For each, gather the evidence that bears on it: results so far, competitor moves, what similar efforts elsewhere achieved.
5. Note vagueness: targets with no date, no figure, or a changing definition from one year to the next. A vague plan is itself a finding.

## Industry and news

Output: `research/industry.md`.

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
7. What the market appears to believe: the price against consensus estimates, short interest, and analyst actions with dates. These are background only. They never set a model input.

## Segment economics

Output: `research/segments.md`.

1. From the 10-K segment note (`filing.py --search "segment"`, and the Item 8 notes), take each reported segment's:
   - revenue, operating income, assets, capital spending, and depreciation and amortization
   - over three to five years
2. Compute from those figures, and show the arithmetic:
   - growth
   - operating margin
   - sales to capital (revenue / assets, as a proxy)
3. Say which segment carries most of the value, and which consumes capital.
4. Propose the segments for the model. Merge small ones, and split out a stake, a venture or a cost centre (unallocated corporate costs) when the filings let you. For each proposed segment give the starting revenue, a margin range, and a sales-to-capital range anchored on its history.
5. For a bank, an insurer or a regulated utility valued on book value (a `residual_income` segment), debt and cash already sit inside book value, so give the book value, ROE history and retention instead of claims. Otherwise give the balance-sheet claims at the latest quarter end, in a table with their sources. Include notes payable, leases, cash, minority interests, preferred stock, pension shortfall, and debt-like land or inventory financing. Keep a finance arm's warehouse or repurchase debt with the loans it funds, not in corporate debt.
6. Note any segment whose definition changed. That breaks the history.

## Thread deep-dive

Output: `threads/<n>-<slug>.md`, the name given by the orchestrator.

You get one belief from the ledger. Take it to a verdict:

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

Output: `research/redteam.md`.

You get the case folder after the model has run. Attack the central scenario (the one the orchestrator names):

1. The weakest input. Find the one the value is most sensitive to, with the least evidence behind it.
2. What is missing:
   - a risk in the ledger or the filings that no scenario reflects
   - a claim on the equity that is not in `claims` (leases, pensions, minority stakes, options)
3. Double counting:
   - a growth driver counted in two segments
   - cash counted both in `claims` and as an asset
   - a premium stacked on a failure that already reflects the same risk
4. Custom calculations. Rerun every `custom/*.py`. Check that its output matches the figure the page uses, and that its method is what its explanation says.
5. Consistency: the margins and reinvestment the scenarios imply, compared with the segment history and the competitors.
6. Blind spots:
   - each row of the structural-threats table in `research/industry.md` that no scenario reflects
   - each threat marked as gone that could come back
   - the strongest argument against the story the research leans on
7. The price. `model.py`'s `implied` gives the margin or ROE shift that makes the first scenario worth today's price. Explain the gap: name the beliefs the market would have to hold to pay this price, and say whether any scenario covers them. When every scenario sits above the price, or every one below, treat that as a sign a scenario is missing.

List the concrete changes you propose, each with its reason and the file and field it touches. List anything you checked and found sound, so the orchestrator knows it was covered.
