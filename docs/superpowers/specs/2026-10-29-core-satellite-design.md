# Core/satellite: manage index funds and individual picks as two sleeves

Date: 2026-10-29. Status: draft, pending the person's review.

## Intent

The person is index-first. Most of the money is in ETFs (the **core**), with a smaller set of individual stocks, each picked on a valuation (the **satellite**). Every request they have made to change the portfolio has been about the relationship between the two sleeves, not the portfolio as one pool:

- "Add $5k from cash to my individual holdings, split according to valuation, since we have valuations for everything."
- "Grow the individual-holdings sleeve by X%. Which ETFs do I pull from?"
- "I don't know what percentage to add. Make an opinionated proposal grounded in portfolio theory."
- "I have a new pick. How much should I grow the sleeve to add it? Or, with the amount fixed, how much goes to the new pick and how much to existing picks?"
- "What is my ETF vs individual-stock mix?"

They also want employer equity compensation handled: RSU vests, ESPP purchases and bonuses (for example AMZN or MSFT pay). Unvested stock is not part of the portfolio. Vests are known future deposits, and each one gets a hold-or-sell call from a valuation.

The existing skills (rebalancing, portfolio-analysis, tax-aware, risk-analysis) treat the portfolio as one pool. None of them sizes the satellite, weights picks within it, or plans known deposits.

### Goals
- One place to answer the five questions above, from today's holdings, with numbers from scripts.
- A satellite ceiling and pick weighting grounded in the research (below). The proposal is presented to the person to discuss, never imposed.
- Decisions the person makes (ceiling, weighting mode, short-term-gain policy, increase plan) are saved, and later runs reuse them and say so.
- Employer equity events planned ahead and routed through the same sleeve rules.

### Non-goals
- No new order path. Orders still go through the trading/portfolio-analysis protocol, with a human yes.
- No new tax engine. Lot selection reuses rebalancing's and tax-aware's logic.
- No new valuation work. Weights read the stock-screener pick store. The skill offers a deep valuation run; it does not run one itself.
- Not a replacement for the rebalancing skill. Rebalancing keeps its general target/drift job.

### Anti-goals (failure even if it technically works)
- Presenting valuation-weighted splits as more reliable than they are. The person's own testing found much of the evaluation model's apparent edge was look-ahead, and the research says expected-return estimates are where optimisers fail.
- Proposing a satellite above the ceiling, or silently changing a saved decision.
- Counting unvested RSUs as investable assets.
- Realising a short-term gain in a taxable account without the person deciding to.
- Using light valuations for the tilt without a visible flag.

## Research basis

Summarised from the research pass. Strong = peer-reviewed or mechanical; weak = practitioner rule of thumb.

- **Satellite size (weak).** No research-based optimum. Practice is 10–30%, with 80/20 the most cited split. A more principled method is a tracking-error budget, about 1–2% a year at the portfolio level: `TE ≈ w_sat × sqrt(σ_idio² / N_eff)`, with N_eff = 1/Σw_i² and σ_idio ≈ 30%. A 20% satellite of 15 equal-weight names gives about 1.5%.
- **Diversification (strong).** Single-stock returns are highly skewed (Bessembinder 2018: 4.3% of stocks created all net wealth above T-bills, 1926–2016). A small satellite's median outcome trails the index even with no negative skill. Warn when N_eff < 15.
- **Weighting (strong).** 1/N is very hard to beat out of sample (DeMiguel, Garlappi & Uppal 2009). Expected-return inputs should be shrunk heavily (Grinold & Kahn: realistic IC 0.05–0.10). Over-betting an estimated edge is asymmetrically costly (Kelly). Hence: small tilts, decayed by staleness, with hard caps.
- **Retail costs (strong).** Barber & Odean (2000): losses come mostly from turnover. This favours size-weighted, buy-only defaults.
- **Employer equity (strong mechanics, weak thresholds).** RSUs are ordinary income at vest with basis equal to FMV, so selling at vest adds almost no tax ("would I buy it with cash?"). ESPP §423: a 15% discount is a 17.6% return on cost at purchase; holding to qualify is usually a small benefit against 1–2 years of single-stock risk. Federal supplemental withholding of 22% often under-withholds. Employer stock above ~10% of net worth is the common warning line. Human capital is correlated with the employer, so the satellite should lean away from the employer's sector.

## Decisions made with the person

### Sleeves
- Core = funds (ETF, mutual fund, fund look-through as the snapshot already classifies them). Satellite = individual stocks the person picked.
- **Employer stock is its own bucket** (the person's decision). Vested employer shares do not count toward the satellite or its ceiling, and never receive satellite money. They are reported separately and measured against the ~10%-of-net-worth concentration check (including look-through in index funds). A sale is raised there, in `equity-comp`, not as a satellite trim. They are excluded from N_eff and the satellite tracking-error estimate; the `mix` view shows total single-stock exposure (satellite + employer) alongside.
- Unvested RSUs and unpurchased ESPP shares are not in the portfolio.

### Satellite ceiling
- A **suggested ceiling of 20% of total investable value**. It is a ceiling, not a target. The skill raises it with the person the first time, explains where it comes from (practice range, tracking-error estimate at their current pick count), and records what they agree. It never proposes a satellite above the saved ceiling unless the person says they want it larger.
- Below the ceiling, *builder's call*, the proposal is lowered when N_eff < 15 or when the person's tech/employer-sector exposure is already high. The estimated tracking error is shown with each size.

### Splitting satellite money across picks
- **Default: by current size.** New money goes to existing picks pro rata to current value. Buy-only, never trims.
- **Optional: by valuation**, only when the person asks for it or has saved it as their mode:
  1. Start from current-size weights.
  2. Tilt toward higher expected return at today's price, from the pick store's deep baselines (`_irrs` at today's price).
  3. Shrink the tilt as the valuation ages, and to zero after a new filing until the pick is re-checked (pick store `_due` reasons).
  4. Picks trading above fair value (central scenario) are **trimmed**, and the proceeds plus new money go toward the top expected-return picks.
  5. Cap any one pick at 5% of total portfolio value.
  6. Show the size-based split next to the valuation split.
- **Deep valuations only.** A light-valuation pick is flagged and keeps its size-based share, and the reply offers a deep valuation run. If the person explicitly asks to include light valuations, they are used and the flag stays visible.
- **Who can receive money** (*builder's call*). Only satellite stocks currently held. Saved picks that are not held receive money only through `new-pick`, so no mode opens a position silently. A held stock with no pick-store entry is treated like a light-valuation pick: it keeps its size-based share and is flagged "no saved valuation".
- **"Grow by X%"** (*builder's call*). When a request is ambiguous between percentage points of the portfolio and relative growth of the sleeve, the reply shows the dollar amount for both readings and asks. `increases` records dollars and the sleeve weight before and after.
- **New pick.** It starts at the median weight of existing picks. That gives the dollar amount for "how much would I need to add". With a fixed amount, the remainder goes to existing picks by the active rule.

### Taxes on trims and core sales
- **Short-term gains in taxable accounts.** The default is to hold back any trim that would realise one, showing the estimated tax and the date the lot turns long-term. The skill asks the person to confirm or change this default the first time it applies, and saves the decision.
- **Picks live in trading (taxable) accounts only** (the person's decision). Retirement accounts hold only core. Every satellite buy is funded inside a trading account, and each sale and buy stay in the same account. Holdings already in a retirement account that are individual stocks are reported, flagged `PICK_IN_RETIREMENT`, and never receive new money.
- Funding the satellite from the core: trading-account cash first, then trading-account core lots with the smallest gain (losses first), drawing from the core fund that overlaps the satellite most (US large-cap before international or bonds). Retirement-account core is not a funding source. Wash-sale flags from tax-aware apply, including against core funds bought in retirement accounts.

### Growing the satellite over time
Not necessarily a schedule. Three paths:
- **Off-schedule request** ("put more into picks"). The skill reads past satellite increases and offers a similar dollar increase as one option, alongside the person's own amount.
- **Proposed plan.** The skill can propose a plan to reach the ceiling (or a lower target the person names) by a target date. It gives step size and cadence, and names the funding source.
- **Saved plan.** If the person accepts a plan, it is saved, each step is computed fresh from that day's holdings and valuations, and a session-start line says when a step is due. The person can pause, change or cancel it.

### Deposits
- **Ask each time** (the person's decision). For any deposit with no destination given (vest or ESPP proceeds, bonus, new cash), the skill shows the current core/satellite split and the room left under the ceiling, proposes a split, and the person chooses. The satellite share is recorded in `increases`, and is then split across picks by the active weighting mode. A saved increase plan supplies the proposed split when one is active; the person still confirms.
- There is no standing core/satellite target; the ceiling is the only sleeve limit.

### Employer equity
- The skill asks for the vest schedule (dates, share counts), ESPP terms (offering/purchase dates, discount, lookback) and expected bonuses once, and stores them.
- For each upcoming event it shows: the expected value and date, the hold-or-sell picture (deep valuation of the employer stock if one exists, plus a concentration check against ~10% of net worth including look-through in index funds), withholding shortfall at 22%, and for ESPP the sell-at-purchase vs qualifying-hold trade-off.
- The person's policy per event type (e.g. "sell RSUs at vest") is saved.
- Proceeds become planned deposits handled like any other deposit (below).

## Components

Three pieces. *Builder's call on names:* `core-satellite` and `equity-comp`.

1. **New skill `core-satellite`.** It owns the sleeve model: classification, ceiling, weighting, increases, saved decisions. Its output is per-symbol targets plus a cash-flow amount, handed to rebalancing's engine for trades and tax routing. Modes:
   - `mix`: current core/satellite/employer/cash split, N_eff, tracking-error estimate, ceiling status.
   - `add`: deploy an amount into the satellite (split by the active mode).
   - `grow`: raise the satellite to a % or $; picks the core sources and lots.
   - `new-pick`: size a new pick, either for a needed increase or within a fixed amount.
   - `plan`: propose, save, show, pause or cancel an increase plan; due-step check for the hook.
2. **New skill `equity-comp`.** It owns the employer equity store and event analysis, and produces planned deposits that `core-satellite` reads.
3. **Changes to `rebalancing`.**
   - Accept a target for a symbol not currently held (today a class with no members raises `NO_HOLDINGS`; check the same for symbol keys).
   - Option to fill sells within a class by smallest-gain lots across members instead of pro rata to value.
   - No change to its default behaviour.

### Stores (plugin data dir)
- `core-satellite.json`: `{ceiling, ceiling_agreed_on, weighting: "size"|"valuation", include_light, short_term_gain_policy, decisions: [{date, key, value}], increases: [{date, amount, funded_from}], plan: {target, by_date, cadence, step_amount, funding, status, next_due}}`.
- `equity-comp.json`: `{employer_symbol, rsu: [{grant, vests: [{date, shares}]}], espp: {offering_start, purchase_dates, discount, lookback, contribution}, bonuses: [{date, amount}], policies: {rsu, espp}}`.

### Reused pieces
- Holdings: a same-day snapshot (`portfolio-snapshot/scripts/snapshot.py build()`) or a live read; `summary.py _asset_class` / `market.sectors` for fund vs stock.
- Account taxability: rebalancing's `_is_tax_advantaged` plus the profile's `account_roles`.
- Lots: rebalancing's `_replay_lots` / `fill_lots`; tax-aware's `run_tax(planned_sales)` for tax estimates and wash-sale flags.
- Valuations: stock-screener `picks.py` store, `track_math._irrs`, `pick_levels`, `_due`.
- Orders: trading `gate.py` / `preview-order.py` / `place-order.py --confirm`, via portfolio-analysis.
- Hooks: a summary line in the style of `picks-summary.sh` for a due plan step or an upcoming vest.

## Constraints from the repo
- `docs/skill-style.md`: fixed headings (Background, Scripts, Steps, Reply format, Rules), description ≤260 chars with "Use when", no recommend/advise/should/suggest in skill text. The "suggested ceiling" is worded as a default the person can change, with its reasoning.
- `CONTRIBUTING.md`: numbers from scripts; one JSON object per script; exit codes per `docs/scripts.md`; orders need a human yes.
- Register in `skills.json`, `tests/test_skills_structure.py`, README skills table, `docs/scripts.md`, `docs/examples.md`.
- Portfolio check rule: every mode starts from a same-day holdings read.

## Left to the builder
- Exact tilt formula and staleness half-life (research suggests: tilt = k × confidence × α, k ≈ 0.25–0.5, half-life ~6 months or next filing).
- Script split (pure-math stdin script + fetching wrapper, as in rebalancing).
- Whether an HTML page is worth adding; chat tables are enough for v1.
- Test fixtures and the order in which the three pieces are built (rebalancing changes first is the natural order).
