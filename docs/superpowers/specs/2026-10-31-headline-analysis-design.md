# Headline analysis on summary pages

## Why

Portfolio Snapshot and Market Flows show a lot of good data and leave the reader to work out what it means. The reader wants to open a page and learn, in under a minute, what matters today and where to look deeper.

The data also invites misreadings the page does not catch. On Market Flows on 2026-10-31, real estate looked crowded at the 0th percentile, but that contract had last reported 58 weeks earlier. A short written reading at the top would catch that.

## Goals

- A headline analysis card at the top of Portfolio Snapshot and Market Flows, above the tiles and the Headlines card.
- The card has a headline and two labeled paragraphs, "What stands out" and "What to look into", plus a folded "What this means for you" line.
- "What to look into" links jump to the section of the page they refer to.
- The card stays small. Its length is enforced by code, not by the writer's discipline.
- A shared component, so adding the card to another page later is a small change.

## Non-goals

- The other 17 page scripts. Risk, Fixed Income, Trade Review, Spending and Dividend Income are candidates for later and are not touched here. Deep valuation, deep picks and the screener already lead with a conclusion.
- Generating the text in a script. No templated prose and no LLM call from Python.
- Changing what the scripts compute.

## Anti-goals

The work has failed, even if it functions, if:

- The card overwhelms the page or grows into a report.
- It makes a buy, sell or hold call, or a forecast. The repo's compliance rules stand, and "What this means for you" says how a reading touches the person's holdings, not what to do.
- It states a number that is not in the script results.
- It reads a percentile as a signal to act. The market-analysis rule "Never read a rank or percentile as a signal to act" still applies.
- It reads stale data as current, such as a contract with a high `weeks_behind`.
- A missing or rejected summary blanks or breaks the rest of the page.

## How it works

The chosen layout is option C from the mockups (headline, two labeled paragraphs, a folded third section), with a left accent border on a `.card`.

### Who writes it

The model writes the summary after reading the script results, following the repo rule that scripts compute and the model explains. The page script validates and displays it.

### Input

Both `render.py` scripts take a new optional flag, `--summary FILE`, naming a JSON file:

```json
{
  "headline": "one sentence",
  "stands_out": "one paragraph",
  "look_into": "one paragraph with [Sectors](sec-card) style links",
  "for_you": "optional paragraph"
}
```

Without `--summary`, the page renders exactly as it does today, with no empty card.

### Validation (shared, in `lib/second_opinion/page.py`)

A summary that breaks a rule exits 2 with an `error` naming the rule, like other render input errors. The model then rewrites it and renders again.

| Rule | Limit |
|---|---|
| `headline` | Required, at most 20 words |
| `stands_out` | Required, at most 90 words |
| `look_into` | Required, at most 90 words |
| `for_you` | Optional, at most 70 words |
| Unknown keys, non-strings or empty strings | Rejected |
| Forbidden verbs in any field | Rejected, using the pattern in `tests/test_skills_structure.py` (`recommend`, `advis*`, `should`, `suggest*`), moved to `lib/` so the test and the validator share it |
| A link whose target is not a section that page declares | Rejected |

The 20, 90 and 70 limits are named constants, and they fit the mockup text with a little room.

All text is HTML-escaped. The only markup allowed is the `[label](target)` link form in `look_into`, where the target is a section id the page declares. Links scroll within the page with `scrollIntoView` from a click handler and do not change `location.hash`, because the artifact viewer restricts hash use. A section that is `hidden` on this run (for example `compare-card`) is treated as not declared for that render, if the render can tell; otherwise the click does nothing harmful.

### Section targets

Each page passes the shared helper the list of ids a link may point to.

- Portfolio Snapshot: `headlines-card`, `accounts-card`, `alloc-card`, `sector-card`, `movers-card`, `holdings-card`, `events-card`, `compare-card`, and a new id on the Flags section.
- Market Flows: `idx-card`, `pos-card`, `sec-card`, `etf-card`, `cash-card`, `short-card`, and a new id on the Flags section.

### "What this means for you"

- Folded by default with `<details>`, so it stays one click away.
- **Portfolio numbers come only from a read taken on this run or today**, never from memory. Non-numeric context from memory or the profile is allowed, such as a paycheck and RSUs being Amazon exposure.
- **Market Flows reads the accounts first.** Its steps add `brief.py --no-headlines` (about 10 seconds), which also satisfies the session's portfolio-check rule. If that read fails, for example an expired E*Trade login, the page still publishes without `for_you`, and the login prompt is not raised for this section alone.
- **Market Flows never adds holdings to a page others can see.** An artifact keeps its link across republishes, and `<details>` only folds text that is still in the HTML. Before rendering, the skill checks the artifact's read mode with `get_artifact`. Unless it is `owner`, or the artifact is new, the skill renders without `for_you`.
- `render.py` cannot see either condition, so the skill decides and simply omits `for_you`. As a backstop, Market Flows' `render.py` also drops `for_you` when `portfolio-last-check.json` in the plugin data directory does not show a full read (`partial` false) on today's local date, still succeeds, and reports `"for_you_dropped": "no full portfolio read today"` in its printed JSON.
- When `for_you` is left out for any of these reasons, the reply says so in one line, and old holdings are never presented as current.
- Portfolio Snapshot shows `for_you` whenever given, since the page itself is the read.

### Skill instructions

Each of the two `SKILL.md` files gains a step before render: write the summary, then pass `--summary`. It states the shared rules and what to look for on that page. `render.py`'s rule that a page's numbers come from its JSON still holds, and the docstrings change to say the summary text is the model's.

Shared rules for the writer:

- Every number comes from this run's script output, quoted as the script gives it.
- Lead with what is unusual today, not a tour of the page. Say plainly when nothing stands out.
- Separate data from inference, using words like "may" for inference.
- Carry dates when a reading is older than the page's prices.
- Name the bull and the bear side when reading a market condition or a security, as the compliance block requires.

Market Flows, what to look for:

- Crowded readings (percentile at or below 10, or at or above 90), read only for contracts with `weeks_behind` of 0. Name stale ones as stale.
- Sectors where futures positioning and ETF flows agree or disagree, and how few ETF observations exist.
- A long in one trader class mirrored by a short in another.
- Whether positioning (Tuesday) predates a large price move.

Portfolio Snapshot, what to look for:

- The day's move against the S&P 500, and how much of it is estimated (`DAY_CHANGE_ESTIMATED`).
- Concentration and flags that changed, cash share, and new alerts in `headlines`.
- Events in the next few days.

The Snapshot skill's current rule "No commentary, bull/bear framing, or opinions outside the Flags section" changes to allow this card, and only this card.

### Chat replies

The skill flow always writes a summary when it renders a page, so a reading always exists. `--summary` stays optional at the script level for other callers.

Page replies gain one line right after the artifact link: the summary's headline.

- **Market Flows:** the headline line replaces the two-to-four-sentence reading (item 3 of the flows page reply), because "What stands out" now carries it. The sentence on what the picture cannot show stays.
- **Portfolio Snapshot:** the Headlines bullets and Flags stay, since they are script facts rather than a reading.

The markdown fallback, used when no page is published, puts the whole summary first as text: headline, both paragraphs and, under the same rules, `for_you`. Validation does not run there, because the fallback skips `render.py`, so the skill text carries the limits and rules. Headless hosts are rare enough that a validate-only command is not worth adding.

## Constraints

- `render.py` output stays self-contained: no external scripts, and it works in light and dark themes through existing CSS variables.
- The page's existing tests and audit keep passing, including the help and glossary audit in `tests/page_dom.py`.
- `tests/test_skills_structure.py` compliance checks keep passing.
- The README screenshots come from `docs/samples/`; invented data only in fixtures and samples.

## Left to the builder

- Exact CSS for the card and the helper's function names.
- How the forbidden-verb pattern moves to `lib/` so it has one definition.
- Whether to update `docs/samples/` so the sample page shows a card.
- The CHANGELOG wording.

## Decisions made by the owner

- Market Flows reads the accounts first so `for_you` can carry real numbers, and leaves the section out if the read fails.
- Market Flows leaves `for_you` out unless the page is private to the owner.

## Decisions made by the designer, for the owner to check

- Word limits of 20, 90 and 70. Earlier discussion mentioned 15 and 120.
- A rejected summary exits 2 rather than rendering without it, so a bad summary is rewritten and not silently lost.
- Numbers in the prose are not machine-checked against the data. Formatting and rounding make that check brittle, so the skill rule carries it.
- `for_you` is dropped on Market Flows without a full read today, rather than failing the render.
- The chat reply gains the headline line, which replaces Market Flows' longer chat reading.
- The markdown fallback carries the whole summary, with its rules in the skill text and not enforced by code.
