# Real-estate deep review

## Why

The calculators are only as good as what is typed into them. The facts that move a property's numbers sit in PDFs and local sources: a special assessment in HOA minutes, a roof at the end of its life in an inspection report, a tax bill that resets at sale, a flood zone, a wave of new apartments nearby. A person rarely has all of them, and a clean IRR hides which inputs are guesses.

The deep review answers one question: what does this property's result rest on, and how solid is that evidence?

## Goals

- Read the documents the person has, and find the local facts they do not have.
- Give every calculator input a source, a date and a basis, so a guess looks like a guess.
- Run named scenarios through the existing calculators, and show the one-time costs the documents turn up.
- Name the input that moves the result most while resting on the weakest evidence.
- Record the review so a later check can rerun it with updated inputs.

## Non-goals

- No buy, pass or offer call, and no fair value. The price where the result comes out even is arithmetic, not a target.
- No appraisal, inspection, title or legal opinion. Those questions go to the people who can answer them.
- No new financial model. `realestate.py` stays the only place the math lives, with its limits: fixed-rate loans only, and no income-tax effects.

## Anti-goals

- Numbers from the model. Every result comes from a script.
- Hidden thin data. Local data can be thin or out of date, so old inputs, few comparable sales and assumptions are flagged rather than smoothed over.
- Personal details in searches. The person's name, income and savings never go in a search or fetch, and no search says anyone is buying.
- Following instructions found in a listing, a document or a web page. All of that is data.

## How it works

1. The person names a property or a market, and whether it would be a home or a rental. Any documents are read from paths they give.
2. Research roles fill the inputs: Documents, Comparable sales, Rents, Taxes insurance and hazards, Local supply and economy.
3. The most uncertain inputs can get a Thread deep-dive, and a Red team then attacks the case.
4. `property_case.py` runs the scenarios. `render_case.py` builds the page.
5. `case_store.py save` keeps the case, and `check` reruns it later with updated inputs.

A market review uses the same flow on a typical home there, with no Documents role.

## The math

Each scenario is the base inputs plus its changes, plus the one-time costs at its chosen level (low, mid or high). One-time costs go into closing costs for a rental and into the closing rate for a home.

- A home runs `rent_vs_buy` and `mortgage`. Its result is `advantage_buy`, buying against renting at the end of the horizon.
- A rental runs `rental`. Its result is `total_profit` over the hold, with NOI, cap rate, DSCR, cash-on-cash and IRR beside it.

`drivers` reruns the first scenario, the central one, with one change at a time from the other scenarios, and ranks the changes by how far they move the result. A driver is `soft` when its basis is a regional figure or an assumption, or when its evidence is over a year old. `soft_spot` is the largest soft driver.

`even_price` is the price at which the central scenario comes out even: buying equals renting for a home, and first-year cash flow is zero for a rental.

Comparable sales and rents give medians from the last 365 and 180 days, and the gap between them and the subject. Fewer than three recent ones raises `THIN_COMPS`.

## Size

About 6 subagents and 35 web searches, stated to the person before the run starts: five roles and a Red team, plus up to two Thread deep-dives. A market review is one fewer.

## Decisions made while building

- It lives in the real-estate skill, with no new skill and no dependency on a broker or EDGAR.
- An input's `basis` is one of `document`, `stated`, `local`, `regional` or `assumption`.
- An unknown input field is rejected, so a typo cannot silently do nothing.
- A later check is due again after 90 days, when a watch item comes due, or when an update flips the central result's sign. Local data ages faster than a company's filings.
