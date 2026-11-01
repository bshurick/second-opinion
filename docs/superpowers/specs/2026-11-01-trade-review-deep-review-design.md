# Trade-review deep review

## Why

The trade review shows what each decision earned. It cannot say whether the decision was good, because a sale followed by a fall looks wise however thin the reason was. Judging a past decision by its result teaches the wrong lesson, and news searched today is full of what happened next.

The deep review answers one question: which of these decisions were good on what could be known then, and which were just lucky or unlucky?

## Goals

- Rebuild what was publicly known before each big decision.
- Grade each decision without showing the grader how it turned out.
- Set the grade against the result: skill, luck, bad luck or mistake.
- Look for patterns across decisions, and say when there are too few to mean anything.
- Freeze the grades, so later checks can test whether the process predicts the results.

## Non-goals

- No call on what to do with an open position. Portfolio-analysis and valuation own that.
- No claim about what the person knew or intended. Public evidence is what could have been known, and the person's own reason is included only if they give it.

## Anti-goals

- Hindsight. A claim dated after the decision cannot count as known: the script rejects it.
- Choosing decisions by how they turned out. They are picked by money moved, largest first, and the researchers and the grader never see the results.
- A story from a handful of trades. Patterns on fewer than three decisions are marked thin, and fewer than ten graded decisions raises a flag.

## How it works

1. `run-review.py` gives the ledger's round trips and outcomes.
2. `decisions.py --pick` lists the largest decisions by money moved, with no results in the list.
3. A Decision researcher per decision gathers dated evidence from before it.
4. A Blind grader, given only that evidence, grades each decision.
5. `decisions.py` joins the grades to the results. A Pattern reader and Red team, who may see results, look for patterns and test the grades.
6. `render_decisions.py` builds the page. `decision_store.py save` keeps it, and `check` re-measures results later with the grades frozen.

## The math

A sale's result is the stock's move against the benchmark in the 90 days after it: falling behind by 5% or more is `good`, pulling ahead by 5% or more is `bad`, and anything between is `flat`. Fewer than 90 days since the sale is `too_soon`.

A buy's result is its return so far, from the review. It is not benchmark-adjusted, because the review holds no benchmark series for a buy's holding period, and the page says so.

| Grade | Good result | Bad result |
|---|---|---|
| sound | skill | bad_luck |
| weak | luck | mistake |

Everything else, including `mixed` and `unknown` grades and flat results, is `unclear`.

`process_gap` is the average result of sound decisions less that of weak ones, shown only with at least three of each.

## Size

About 10 subagents and 30 web searches for eight decisions, stated to the person before the run starts.

## Decisions made while building

- It lives in the trade-review skill and needs an imported ledger with prices.
- A claim dated the same day as the decision counts as known, because the trade may have come after it, and raises `SAME_DAY_EVIDENCE`.
- A `sound` grade needs at least one claim in favor. A decision with no evidence can only be `unknown`.
- A later check is due after 180 days, or when new decisions as large as those reviewed appear.
