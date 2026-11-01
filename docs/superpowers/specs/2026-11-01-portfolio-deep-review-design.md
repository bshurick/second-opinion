# Portfolio deep review

## Why

Allocation and correlation show how holdings are split and how their prices moved together. Neither says why they could fall together. Several companies can rest on one interest-rate path, customer or policy, and a paycheck can rest on the same thing. A person can look diversified and still depend on one belief.

The deep review answers one question: what single belief does this person's financial life depend on most?

## Goals

- Find shared bets across every holding, including what sits inside funds and the person's income if they give it.
- Say what each bet is worth in dollars, from code, with the evidence for and against it.
- Show where prices already reveal the bet and where they do not.
- Record the bets so a later check can re-measure them against the holdings at that time.

## Non-goals

- No buy, sell or hold call, no target weights and no trade list. Rebalancing and core-satellite own those.
- No forecast. A shock is a stated assumption, not a prediction.
- No fair value. Deep valuation owns that, and the review reuses saved deep valuations as evidence.

## Anti-goals

- Plausible stories about connections. A link with no source and date is rejected by the script.
- Numbers from the model. Every dollar figure comes from `exposure.py`.
- Sending personal figures out. Holding values, income and account names never go in a search or a fetch.

## How it works

1. The baseline is today's `snapshot.py` and `stress.py --full-correlation` results.
2. Research roles map holdings and income to candidate bets: Company links, Fund look-through, Macro sensitivity, and Income and employer.
3. The most contested or largest bets get thread deep-dives, and a Red team then looks for what was missed.
4. `exposure.py` measures the bets. `render_review.py` builds the page.
5. `review_store.py save` keeps the review, and `check` re-measures it later.

## The math

For each link between a holding and a bet:

- `exposed_value` = market value × `share`, the share of that holding's value that depends on the belief.
- `loss_if_wrong` = `exposed_value` × `shock`, the assumed change in that exposed value if the belief is wrong.

Bets are ranked by `at_stake`: the size of `loss_if_wrong` plus one year of income at risk, and a bet that would net a gain puts nothing at stake. Bets overlap, so their losses are never added together.

`history` compares the average pairwise correlation of a bet's holdings with the whole portfolio's. A bet whose holdings move together no more than the portfolio does is flagged `NOT_IN_PRICES`: correlations would not show it.

## Size

About 8 subagents and 40 web searches, stated to the person before the run starts.

## Decisions made while building

- It lives in portfolio-analysis, with no new skill. It needs portfolio-snapshot and risk-analysis, and stops with a plain message when either is missing.
- Income is optional and comes only from what the person says in the session. Without it the review covers holdings alone and says so.
- A sold holding does not break a later check. It shows as `gone` and its exposure counts as zero.
- A review is due again after 180 days, when holdings bought since the review that no bet covers reach 10% of the portfolio, or when a bet's exposure has moved by a quarter.
- `stress.py` gains `--full-correlation`. Above 15 holdings it otherwise reports only the 20 strongest pairs, which would bias the comparison, so a run without the full matrix gets `NO_RISK_DATA` and no `history`.
