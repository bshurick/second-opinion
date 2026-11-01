# Portfolio deep review role briefs

Each section is the brief for one research subagent in a portfolio deep review. The orchestrator hands a subagent the Shared rules section plus its own role section, the case folder path and today's date.

## Contents
- Shared rules
- Company links
- Fund look-through
- Macro sensitivity
- Income and employer
- Thread deep-dive
- Red team

## Shared rules

- Work only inside the case folder `DIR/deep-review/`. Write your findings to the file your role names, and any download or scratch file under a name that starts with your role.
- The person's holdings are in `baseline/snapshot.json` and `baseline/stress.json`. Read them there.
- **Nothing personal leaves this machine.** A search, URL or fetch may name a company, fund, ticker, industry or policy. It never carries a holding's value, weight or share count, an income figure, an account name, or a person's name or other identifier. Never say or imply that anyone holds a security or works somewhere.
- SEC data comes only through the fundamental-research skill's scripts. Never write an HTTP request to sec.gov.
  - `edgar.py SYMBOL` (financials, filing index)
  - `filing.py SYMBOL --item ITEM` (one Item's text)
  - `filing.py SYMBOL --search TERM` (a passage)
- Every claim carries its source and date:
  - A filing is its form, Item and filing date, e.g. "10-K Item 1, 2026-02-20".
  - An article is its outlet and the dateline printed on the page, e.g. "Reuters, 2026-09-14".
  - Search snippets blend years. Read the dateline on the page itself.
  - A claim without a source and a date stays out of the findings. `exposure.py` rejects it.
- Search results cluster around the story everyone is telling now. Treat that story as one hypothesis to test. For each bet, find at least one source that argues the other side.
- Prefer primary sources (filings, regulator rulings, government statistics) over coverage of them.
- **Web searches are a shared, limited allowance.** The whole session has one pool of about 200.
  - Your prompt gives your cap. Treat it as a hard limit and keep a count.
  - Fetch filings, government data and company pages directly before searching. A direct fetch does not spend a search.
  - At the cap, stop searching and say which claims you could not check.
- A claim from memory alone stays out of the findings. Separate what a document says from what you infer, and write inference as "Inference:" on its own line.
- Quote the exact figure from the source. Compute no dollar exposure: `exposure.py` does that.
- End the findings file with a `## Candidate bets` list, except the Red team. Each entry has:
  - `name`: a few words
  - `belief`: one sentence that could turn out to be wrong, not a topic ("Short rates stay under 4% through next year", not "rate risk")
  - `links`: for each holding, `symbol`, `share`, `shock`, `why`, `source` and `date`
  - `for` and `against`: claims, each with `source` and `date`
  - `watch`: `what` to check, what result `breaks_if`, and a `check_by` date
- `share` is the part of the holding's value that depends on the belief, above 0 and at most 1. Tie it to a figure where one exists, such as the revenue from one customer in a 10-K. Mark any other share as inference.
- `shock` is the assumed change in that exposed value if the belief is wrong, from -1 to 1. Base it on how the same kind of shock played out before, name that precedent in `why`, and date it. A shock is an assumption, not a forecast.
- Return to the orchestrator one paragraph: the three findings that matter most, the file path and the searches you used.
- Leave buy, sell and hold judgements, target weights and fair values out entirely. Avoid the words "recommend", "advise", "should" and "suggest" in what you write.

## Company links

Output: `research/company-links.md`. Search cap: 12.

For the largest single-company holdings, up to 15:

- Read the 10-K's Item 1 and Item 1A, and the concentration notes. Record named customers and suppliers, geographic revenue, regulation, financing needs and contracts that depend on one budget or program.
- Look for what two or more holdings have in common. A single company's risk is not a shared bet unless income or a fund also rests on it.
- Where the prompt lists saved deep valuations from the pick store, read those ledgers first. Their dated beliefs count as evidence and save searches.

## Fund look-through

Output: `research/fund-look-through.md`. Search cap: 3.

For the largest funds:

- Fetch the top holdings and sector weights from the fund provider's page directly.
- A fund with no public page, such as a 401(k) trust, uses the holdings of the ETF named in its `day_change_proxy` in the snapshot. Say so in the claim.
- Report what the funds hold in common with each other and with the single-company holdings, such as the same few companies at the top of several funds.
- A fund's `share` for a bet is the part of the fund in the companies tied to that bet.

## Macro sensitivity

Output: `research/macro.md`. Search cap: 8.

Test the holdings against the forces that move many of them at once: interest rates, inflation, the dollar, oil, credit conditions, government budgets and consumer demand.

- Use government data (FRED, BLS, EIA, Treasury) and the Fed's own projections by direct fetch.
- For each force, look back at what the same kind of move did to these industries over the last five to ten years. Dated precedents set the `shock`.
- `baseline/stress.json` holds factor betas, correlations and crash replays. Use them to see which forces the prices already show. Report the ones they do not.

## Income and employer

Output: `research/income.md`. Search cap: 5. Dispatched only when the person named an income source.

- Your prompt lists each income source by `id`, type and, where given, employer or industry. Annual figures stay in `income.json`, which you have no need to read.
- Research the employer or industry as a company. Nothing in a search says anyone works there.
- Report what the income rests on: the employer's filings on headcount, restructuring and pay in stock; the industry's hiring cycle; a rental market's vacancy figures.
- Add `income_links` to the candidate bets: `income` (the id), `share`, `shock`, `why`, `source` and `date`. Link the income to any holdings that rest on the same belief. A paycheck and a stock of the same employer rest on one belief.

## Thread deep-dive

Output: the file the prompt names under `threads/`. Search cap: 3.

The prompt gives one bet, as the current `bets.json` entry.

- Find what would settle the belief or show it cannot be settled yet: the primary document, the number, the ruling, the date.
- Test the `share` and `shock` on each link against the evidence, and give corrected values with sources where they differ.
- Return a `verdict` with the reason:
  - `holding`: the evidence supports the belief
  - `contested`: serious evidence on both sides
  - `weakening`: recent evidence runs against it
  - `open`: nothing available can settle it yet
- Add at least one `watch` item that would break the bet, with a date.

## Red team

Output: `research/red-team.md`. Search cap: 5. Dispatched last, with the current `bets.json`.

- Argue that the bets are wrong or incomplete. Which belief does the whole portfolio rest on that nobody listed? Which link is a story with thin evidence? Which pair of bets is really one?
- Name holdings that the review left out of every bet and say whether they share a belief.
- Check that every bet has real evidence against it. A bet with none gets your search for one.
- End with `## Changes`: each bet to add, merge, weaken or drop, with sources and dates.
