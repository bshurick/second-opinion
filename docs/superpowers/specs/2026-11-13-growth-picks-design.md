# Growth picks: a second mode for the deep picker

Date: 2026-11-13. Status: draft for approval.

Lines marked **(call)** are the designer's choices, not the owner's. Everything else is what the
owner said.

## Intent

The deep picker finds value picks. Its gate asks "how bad is the bad case" and admits a finalist
only when no gated scenario loses money over five years. That is the right test for value, and it
rules out the names the owner also wants to find: companies whose bad case is ugly and whose good
case is very large. The examples given were NVDA ahead of its run and AMZN in the early 2000s.

Growth mode asks the opposite question: "how good is the good case". A growth pick has a best case
worth at least double the money, a central case worth more than today's price, and a business that
is not broken. Its downside is shown and never used to exclude it.

## Goals

1. A deep picker run in growth mode surfaces finalists by upside, with the downside reported.
2. Growth candidates reach the gate. Today's scanners, health check and quick reads all prefer
   cheap, cash-generating companies, so the candidate source changes with the mode, not only the gate.
3. The best case stays tied to the same valuation rules as every other scenario: a story the
   company could plausibly reach, valued segment by segment from forecast earnings.
4. A cash-burning company stays in when the cash funds growth, debt is low and revenue is climbing.
5. Saved growth picks are kept apart from value picks inside the one picks sleeve, and money
   reaches them only when the person asks.

## Non-goals

- No second sleeve and no target or cap for growth's share of the picks sleeve. The owner sizes
  growth picks ad hoc.
- No change to the valuation arithmetic (`model.py`, `returns.py`).
- No sector steering in either direction. Growth mode does not avoid tech. (The skills never
  steered by sector; that was one person's saved preference.)
- No backtest of the growth gate in this change.
- Light (standard-depth) picks have no growth mode.

## Anti-goals

- A growth pick shown without its worst case and the loss it implies. The downside is not a test
  here, so it must be more visible, not less.
- A best case that is a hopeful story: a number with no dated evidence behind what must be true.
- A value run changing behaviour. With the value profile every script's output stays as it is today.
- Money flowing into growth picks automatically because their central return is the largest.

## How a run is chosen

- The picker already takes `--profile value|growth` in `pick_prep.py`; today `growth` only swaps
  the screens. **(call)** Growth mode is that profile, carried through every later step. The old
  behaviour of the growth profile (growth screens, value gate) goes away.
- The value profile stays the default. Words that choose growth: "growth picks", "high upside",
  "2x", "the next NVDA", "moonshot". **(call)**
- `pick_prep.py` records the profile in the run folder, and the later scripts (`prospects.py` via
  the scanner prompt, `pool.py`, `cards.py`, `pick_assemble.py`) read it from there, so the
  coordinator passes it once. **(call)**

## The picker in growth mode

### Screens (`pick_prep.py`)

The screens must be able to surface the cash burner of goal 4. Today's `growth` preset requires
positive free cash flow in the latest year and share growth of at most 5%, and `garp` requires
free cash flow every year, a 10% operating margin, share growth of at most 3% and a P/E of at
most 25. **(call)** The growth profile runs the `growth` preset with `fcf_positive_latest` and
`max_share_growth` switched off (the `--set KEY=none` overrides `pick_prep.py` already uses for
the small-cap variant), plus the small-cap variant of the same. `garp` leaves the growth profile:
its tests are the ones this mode exists to drop. `operating_margin_improving` and the $1B market
value test stay. No new preset.

### Prospect tests (`prospects.py`, Industry scanner brief)

The scanner's four tests today are trajectory, cash, price and overlooked. Price (free-cash-flow
yield of 6% or a P/E of 15) and overlooked are value tests. In growth mode the four are **(call)**:

| Test | Passes when |
|---|---|
| `trajectory` | Revenue above the same quarter a year earlier in at least 6 of the last 8 quarters, and trailing-twelve-month revenue growth of at least 15% |
| `funded` | Free cash flow positive in the latest year, or cash and short-term investments cover at least two years of the latest year's burn; and net debt no more than 4 times operating profit (net cash always passes) |
| `reinvestment` | R&D plus capital spending is at least 10% of revenue, or grew faster than revenue over the last three years |
| `scale` | Gross margin of at least 40%, or rising over the last three years: growth can turn into profit |

A prospect still passes three of four, and the $300M size floor stays. The scanner brief gets a
growth variant of step 4 that tells it to look for companies whose largest opportunity is a
business that is still small in the numbers, and to say which one in `why`.

### Health check (`pool.py`, the `health` preset)

What the owner asked for: exclude the clearly mismanaged and the sinking, with heavy debt named;
keep the cash burner. In growth mode the health preset runs with these changes:

| Test | Value (today) | Growth |
|---|---|---|
| Net debt to operating profit | at most 4 | at most 4; a company with an operating loss passes only with net cash **(call)** |
| Free-cash-flow margin | at least 0 | dropped |
| Share count growth | at most 5% a year | dropped |
| Revenue growth, 3-year | at least −5% | at least +10% **(call)** |
| Financial-strength score | at least 4 | at least 3, since the score counts negative cash flow and new shares against a company **(call)** |
| Minimum revenue | $250M | $100M **(call)** |
| Cash runway | none | when free cash flow is negative, cash and short-term investments cover two years of it **(call)** |

The runway test is the one guard on "burning cash is fine": low debt and a cash burn also
describes a company about to run out of money.

### Quick reads (Quick reader brief, `cards.py`)

- The fourth score, `value`, becomes `upside` in growth mode **(call)**: 1 when the quick value's
  bull case is below the price, 5 when the bull case is at least twice the price and the base case
  is above it. `cards.py` writes an `upside_hint` from those two ratios the way it writes
  `value_hint` today.
- A cash burner often has no usable quick value (a null `basis`, or a cash-flow value built on
  negative cash flow). **(call)** Then `upside_hint` is null, never 1, and the reader scores
  `upside` from a growth yardstick the brief gives: the revenue the company would need for the
  price to double at a mature margin for its industry, against its current revenue and growth
  rate and the size of the market it sells into; and its enterprise value to sales against
  growing peers. The reason names the yardstick used.
- The health-status table in the brief gets growth wording: negative free cash flow and a rising
  share count are not marks against the company; a short runway is.
- Finalist rules stay: `leverage.ok` false is never a finalist, no more than two from one
  industry, held names allowed and marked, at least one contrarian when one survives.

### The gate (`gate.py`, `pick_assemble.py`)

A second rule beside Rule B, chosen by the profile. Stress scenarios are left out as today.

- **Best case.** The gated scenario with the highest annual return must at least double the money
  over the model's horizon, dividends included: its return is at least
  `min_upside ** (1 / horizon) − 1`, which is 14.9% a year for 2x over five years.
- **Central case.** The first scenario's value per share is above today's price.
- **Worst case.** Reported with its return, never a reason to fail.
- A best or central scenario with no computed return or value fails, as a missing return does today.
- `pass_flagged` keeps its meaning: passed, and every gated scenario sits above the price, so a
  downside case may be missing.
- `min_upside` defaults to 2.0. The owner called 2x "the minimum for growth picks" and may raise
  it: it is a saved setting **(call: `picker.growth.min_upside`)** with a per-run flag
  `--min-upside` on `pick_assemble.py`. `--hurdle` and `--floor` are bad input in growth mode.
- Results run pass, pass_flagged, fail, each by best-case return, highest first.
- The output carries `best` beside `central` and `worst`, the money multiple the best case
  reaches, and `profile`.

### Page and reply (`render_pick.py`, SKILL.md)

- The page is titled as growth picks and says in one line what the test was and that the worst
  case was not a test.
- Per pick: best-case multiple and return, central value against the price, and the worst case
  with its return, labelled "not gated". Near misses name the test they failed.
- The reply table has the same columns. Published description: "Deep growth picks as of DATE".
- The size line before a run is unchanged: the search plans and subagent counts are the same.

## Valuation

The owner's view: the best case can use the rules already in place. The check of the code agrees
with two gaps. Nothing caps an upside scenario, but nothing requires one either, and the red team
only attacks the central and downside cases. Changes, to the briefs only:

- **Deep step 4 (scenarios).** At least one scenario is better than the central one. Its
  `must_be_true` items each point to a ledger claim with a source and a date: what the company
  has already shown that makes the story reachable. **(call)** This applies to every deep
  valuation, not only growth runs, so valuation needs no mode of its own.
- **Red team brief.** One added step: attack the best case as it attacks the central one. Is each
  `must_be_true` backed by a dated record, are its margins and reinvestment consistent with the
  segment history and with what comparable companies achieved, and is it one story, not several
  good things stacked. A best case it cannot support is cut back, and the model rerun. No added
  searches: the cap stays 2. **(call)**
- `MARGIN_ABOVE_HISTORY` stays a flag. In a best case it is expected; the page says so.

## Saved picks

- Each pick in the pick store carries `style`: `value` or `growth`. `save-deep` takes
  `--style`; `pick_assemble.py` puts it in the save commands. A pick saved before this change, or
  saved with no style, is `value`. **(call)**
- **(call)** A saved pick never changes group silently. When `save-deep --style` names a style
  other than the saved pick's, the new valuation is saved, the pick keeps its old style, and the
  output carries a flag saying so; the reply names it. Moving a pick between groups takes an
  explicit `--restyle`, run only when the person asks.
- `list`, `due` and `summary` show the style, and `list` groups by it.
- **Re-checks (`track_math.py`).** For a growth pick the price level `hurdle` is replaced by
  `upside`: the price above which the best case no longer reaches `min_upside`. The other levels
  stay, and `below_worst` is still reported. What makes a rerun due does not change. **(call)**

## Money (`sleeves.py`, `sleeve_run.py`, `plan.py`)

One picks sleeve, one target. The style decides who receives new money:

| The person says | Who gets it | How it is split |
|---|---|---|
| "add $5k to my picks" | value picks only | the saved weighting rule, as today |
| "add $5k to my growth picks" | growth picks only | equally: each growth pick gets the same dollar amount of the new money. It does not even out their current sizes. |
| a mix | both | the person gives each group's part as a percentage or a dollar amount; each group then splits its part by its own rule |
| opening a value pick | that pick | as today: sized at the median of the value picks, and the rest of an `--amount` joins the fill across value picks |
| opening a growth pick with an amount | that pick | the whole amount goes to it; nothing is spread to other picks **(call)** |
| opening a growth pick with no amount | that pick | proposed at the median value of the held growth picks, or of all picks when it is the first **(call)** |

- A mix with no split given is not guessed: the reply asks for it.
- Another weighting for the growth group can be asked for by name (`--weighting`), per run. **(call)**
- **(call)** Flags on `sleeve_run.py add`: `--growth` for the growth group, and `--value X
  --growth Y` for a mix, each a dollar amount or a share of AMOUNT.
- **(call)** Money that arrives without a named group goes to value picks everywhere it is routed
  automatically: the plan's fill toward the picks target, a deposit, the glide. With no value pick
  saved, that money stays unallocated with a flag saying growth picks take money only by request.
- **Growth picks are left to run.** No automatic path sells or trims one: not `rebalance`, not
  the per-pick cap, not the plan bringing an over-target picks sleeve back to its target, not a
  withdrawal that draws on picks. A growth pick over the cap, or a sleeve over its target because
  of growth picks, raises a flag on the plan page; selling one happens only when the person names
  it. The owner accepted that a large winner can then become a big share of the portfolio.
- `rebalance` moves money between value picks only.
- The sleeve's size against its target counts both groups. **(call)** When the sleeve is over
  target, value picks are not sold to make up for growth picks' excess: value picks are trimmed
  only down to the sleeve's target (only when they alone exceed it), and the rest is flagged.
  With sleeve target T, value picks V and growth picks G, the value picks' line aims at
  max(T − G, min(V, T)): it fills to T − G when the sleeve is under target, holds when only
  growth picks push it over, and sells down to T when value picks alone are over.
- The per-pick cap still limits buying: new money never takes a growth pick past it. The builder
  traces every path that sells picks (`sleeves.py`, `global_plan.py`, `plan.py withdraw`) and
  applies the hold in each.
- `mix` and the plan page show value picks and growth picks as two groups, each with its total.

## Left to the builder

- Where the run's profile is stored and how each script reads it.
- The exact figures behind the new prospect and health tests (which XBRL tags give cash and
  short-term investments, R&D, gross margin), and the null rules when a figure is missing,
  following `screen_math.py`'s existing missing-data rules.
- Names of new flags and output fields beyond those given here.
- Tests for every changed script, the docs (`docs/deep-research.md`, `docs/scripts.md`,
  `docs/configuration.md`), the CHANGELOG entry and the version (1.9.0).
