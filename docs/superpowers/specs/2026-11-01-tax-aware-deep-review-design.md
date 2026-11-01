# Tax-aware deep review

## Why

The tax view is a snapshot of one year. The expensive choices play out over several: when to sell appreciated stock awards, whether to harvest a loss now, how much to convert to a Roth before income changes, whether to push a gain into next year. Comparing them takes judgment, and a confident error is costly, because the rules are specific and they change.

The deep review answers one question: across these plans, what ends up in your pocket, and which assumption decides the comparison?

## Goals

- Compare several multi-year plans against doing nothing, on after-tax wealth at the same end date as well as tax paid.
- Check every rule the math uses against a primary source, with its date.
- Test whether the ranking survives other growth rates and future tax rates.
- Record the plans so a later check can see what has come due and what has changed.

## Non-goals

- No return, no filing position, and no call on which plan to take. That is for the person and their tax professional.
- No new per-lot tax logic for this year. `tax-report.py` stays the source for lots, wash sales and carryforward.
- No state detail beyond a flat rate, no AMT and no Medicare premium effects. They are named as not modelled.

## Anti-goals

- Rules from memory. Math rows without a source and date are rejected, a plan action needs its rule cited, and secondary sources and projected tables are flagged.
- Numbers from the model. Every dollar figure comes from `tax_plans.py`.
- Comparing plans on tax paid alone. A Roth conversion pays more now on purpose, so only wealth at a common end date compares fairly.
- Income or holdings in searches. The research roles look up law, and receive no figures.

## How it works

1. `tax-report.py` gives the open lots and carryforward. The person states income by year and filing status. Nothing is looked up or guessed.
2. Rule checkers confirm each rule against primary sources: capital gains and harvesting, retirement and conversions, stock awards and withholding.
3. A Plan designer, with no web access, proposes plans from the local figures.
4. `tax_plans.py` runs the plans and the assumption tests. A Red team attacks the rules and plans.
5. `render_plans.py` builds the page. `plan_store.py save` keeps it, and `check` reruns it later.

## The math

Each year: wages and other ordinary income, plus conversions, plus net short-term gains, less the deduction and any allowed capital loss, are taxed on the ordinary brackets. Net long-term gains and qualified dividends stack on top, on their own brackets. NIIT and a flat state rate are added.

Netting follows Schedule D: short-term and long-term separately, then against each other. A net loss offsets ordinary income up to the limit, short-term first, and the rest carries forward with its character.

Sales are lot by lot, at each lot's price grown to the sale date. A sale after the lot's long-term date is long-term. Proceeds and any tax due go through one reinvested pot, which grows at the same rate. Tax on wages alone is left out of it, since every plan pays that.

Wealth at the end is the unsold lots and pot less tax on their gains at `exit_long_term`, plus the Traditional balance less `exit_ordinary`, plus the Roth balance.

Assumption tests rerun every plan with other growth or exit rates, and say whether the leading plan changes.

## Size

About 5 subagents and 20 web searches, stated to the person before the run starts.

## Decisions made while building

- It lives in the tax-aware skill and needs an imported ledger. Income and filing status come only from what the person says in the session.
- The first plan must be `do nothing`, with no actions, since every comparison is against it.
- A rule row is `enacted` or `projected`. Projected rows, such as next year's brackets carried forward, raise a flag.
- Conversions follow the pro-rata rule when the Traditional balance has after-tax basis.
- A later check is due when the calendar year changes, after 180 days, or when a plan has actions due within 60 days of year end.

## Found while testing

- Sales already made in the report year count in that year for every plan, so a harvested loss offsets them. `summary.loss_carryforward` is the carry out of the report year, so the opening carry comes from the prior year's row in `carryforward_history`. Tax on those sales is not activity, since every plan pays it.
