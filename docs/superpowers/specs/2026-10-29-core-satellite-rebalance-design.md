# Core/satellite: rebalance the picks by valuation on every add, grow and new pick

Date: 2026-10-29. Status: replaced by `2026-10-30-core-satellite-strategies-design.md`. Amends
`2026-10-29-core-satellite-design.md`; where the two disagree, this one wins.

## Intent

Adding money or a new stock to the picks should reshape the whole picks sleeve
around today's valuations, not only bolt new money onto it. The person's words:
"more weight to better buys, less weight to prices close to fair value", and
"rebalancing is always the default".

Today (`main` at 9383711):

- `add`, `grow`, `deposit --satellite` and `plan-step` split only the new money.
  Valuation weighting tilts that split, but no held pick is ever sold except one
  priced more than 5% above its central value.
- `new-pick` opens the new stock at the median pick times its own tilt
  (`valuation_multiplier`), funds it, and touches nothing else.
- There is no way to add a stock without growing the sleeve.

The first design chose "buy-only, never trims" from the turnover research
(Barber & Odean). The person has now chosen the other side of that trade:
rebalance by default, accept realised gains, and keep churn down with bands.

### Goals
- One default flow for `add`, `grow` (and so `plan-step`), the satellite part of
  `deposit`, and `new-pick`: seed, then rebalance every trading-account pick to
  valuation-weighted targets for the new sleeve total.
- A same-size variant of `new-pick`: the sleeve total stays put and the new stock
  is paid for by trimming other picks.
- An opt-out that keeps today's behaviour exactly.
- Picks due for a recheck get one before they are weighted; a pick whose recheck
  cannot finish yet holds its current value.

### Non-goals
- Stock/bond/cash targets and a before/after asset-class check. That is the next
  piece of work, after the person saves targets with the rebalancing skill.
- Rebalancing the core funds against each other.
- Any change to what counts as a pick vs core (beyond the employer change below),
  to account routing, or to the order path.

### Anti-goals (failure even if it technically works)
- A run that trades every pick by a few dollars: churn the bands exist to stop.
- Re-tilting a pick on a stale or awaiting-filing valuation.
- Selling anything in a retirement account, or moving money between accounts.
- A target that compounds: running the same rebalance twice on unchanged prices
  and valuations must give no trades the second time.
- Presenting the tilt as more reliable than it is (unchanged from the first design).

## Decisions made with the person

- **Rebalance is the default** for `add`, `grow`, `plan-step`, `deposit` (its
  satellite part) and `new-pick`.
- **Seed first.** A new pick enters at the median trading-account pick value; the
  sleeve grows by that amount, funded from the account's cash, then core sales in
  the existing order (or `--sell`). Then the rebalance runs with the new pick
  included, so it may end above or below the median.
- **Same-size variant** for a new stock without growing the sleeve.
- **Gains:** realised as needed. `short_term_gain_policy` is saved as `allow`.
  The `hold` path keeps working for anyone who saves it.
- **Bands:** a pick within max(25% of its target, $250) of its target is left
  alone.
- **Recheck before rebalance.** The skill runs the stock-screener re-check on every
  due pick before planning. A pick still due afterwards (for example its 10-Q is
  not filed yet and no earnings-release check is possible) **holds at its current
  value** until its recheck completes: not trimmed, not added to.
- **Weighting setting:** `weighting` is saved as `valuation` and `ceiling` as 1.0
  (no sleeve ceiling).
- **Targets start from equal weight, then the tilt.** Every rebalanced pick
  starts from the same share of the sleeve and its valuation moves it up or down.
  The person accepted that the first rebalance is large, because today's positions
  are uneven (small positions grow, and large ones are trimmed even when they are
  good values).
- **Bands apply only to moves between existing holdings.** New money is always
  placed, to the picks furthest below their targets first; the band only decides
  whether a held pick is trimmed or topped up from other picks' trims.
- **Tilt strength unchanged** (TILT_LAMBDA 0.5, SHRINK_K 0.5): the best value today
  gets about 1.35x the weight of a pick earning the market rate.
- **Employer stock can be a pick.** When the employer symbol has a saved deep
  valuation in the pick store, it can be opened with `new-pick` and is weighted
  like any pick. EMPLOYER_CONCENTRATION (above 10% of total) still fires.

## Behaviour

### Target total
- `add A`, `deposit --satellite A`: T = trading picks value + A.
- `grow`: T = the grow target's trading-picks value (as today, limited by the
  saved ceiling).
- `new-pick SYM`: T = trading picks value + seed, seed = median pick. With
  `--amount A`: T = trading picks value + A (the new pick seeds at min(median, A)).
- `new-pick SYM --same-size`: T = trading picks value; the new pick seeds at the
  median and every other target shrinks to pay for it.

### Targets
Valuation targets over every trading-account pick, the new one included:
raw weight = 1 x max(0, 1 + TILT_LAMBDA x a / TILT_SCALE) for an eligible pick
(a pick without an eligible valuation keeps its size share instead), times the trim factor
(1 - confidence x (1 - central / price)) instead when overvalued, then scaled to
T. Equal weight is the base, not current value, so a second run on unchanged
prices and valuations gives the same targets and no trades. Also:
- held-for-recheck picks fixed at current value (T for the rest is reduced by them);
- picks with no saved valuation, or a light one without `include_light`, at their
  size share (unchanged rule);
- the overvalued trim rule (price above central × 1.05) unchanged;
- the 5% pick cap unchanged; in rebalance mode a capped pick above 5% may be
  trimmed back toward the cap only when it is also overvalued (unchanged rule:
  never trimmed for size alone).
- No floor at current value for an eligible pick: its target may be below what it
  holds, which is what makes this a rebalance.

### Bands and trades
- New money (the add amount, the grow gap, the seed) is always placed: first to
  the new pick's target, then to the picks furthest below their targets, in
  order of the shortfall, until spent. No band applies to it.
- Moves between existing holdings (a trim of one pick to top up another) happen
  only for a pick whose |target − current| is at least max(0.25 x target, $250),
  after new money is placed. A pick inside its band is neither trimmed nor topped
  up from trims.
- The new pick always trades.
- Pick sells fund pick buys in the same account first; only the account's net
  need is funded from cash, then core sales.

### Opt-out and variants
- `--no-rebalance`: today's behaviour, exactly (new money only, current-value
  tilt; new pick sized by median x multiplier).
- `--same-size`: `new-pick` only.
- Size weighting with rebalance on: targets are current size shares, so it only
  differs from `--no-rebalance` by the bands; that is acceptable.

### Recheck step (skill, not script)
- Before any planning run, the skill lists due picks (stock-screener re-check list)
  and runs their re-check; a reported quarter without a 10-Q uses
  `picks.py check --release FILE` when the release can be found.
- `run.py` already marks a pick `recheck_due`; in rebalance mode sleeves treats a
  due pick as held at current value and flags it `HELD_FOR_RECHECK` with the
  reason.

### Employer as a pick
- `new-pick EMPLOYER` is allowed when the pick store has a deep pick for it;
  otherwise it stays bad input.
- A held employer symbol with a saved deep pick is classified satellite, not
  employer. Without one it stays in the employer bucket.

## Output additions
- `splits[].flags`: `HELD_FOR_RECHECK`, `IN_BAND` (no trade, within band).
- `splits[].current`, `target`, `delta` as today; `trades` now include pick SELLs.
- `rebalance: true|false` and `same_size: true|false` echoed in `settings_used`.
- `satellite_net` unchanged in meaning (pick buys less pick sells), so
  `record-increase` keeps working.

## Constraints
- `docs/skill-style.md` wording rules; SKILL.md lines under 400 characters.
- Every number from the scripts; plans only, orders via portfolio-analysis.
- The randomized money-invariant test (seeded) must keep passing with rebalance on.

## Calls made by the designer (not the person)
- **Same-size trims ignore the bands.** The trims that pay for the new pick's
  seed are taken from the picks furthest above their targets first and are not
  skipped for being inside a band; otherwise the variant would place nothing.
- **Sleeve-wide targets, routed per account as today.** With one trading account,
  stranded cash between accounts does not arise. With several, buys route to the
  account holding more of the pick, trims are taken where those buys land, and a
  sale's proceeds buy picks in its own account only; a shortfall scales buys down
  (ACCOUNT_SHORT).
- **"Held" means re-check pending, not "valuation needs a redo".** A pick whose
  last check says the deep valuation must be rerun (status `outside`), or that is
  stale with no earnings date, is also held at current value, but flagged
  `DEEP_VALUATION_NEEDED` instead of `HELD_FOR_RECHECK`, and the reply offers the
  deep valuation run. It stays held until one is saved.

## Left to the builder
- Where the bands are applied (inside `weights.valuation_targets` or after it in
  `sleeves.py`) and the exact funding order between pick sells and core sells
  inside one account.
- Whether `--no-rebalance` is also a saved setting, or only a flag (flag is enough
  for v1).
- Test fixtures; reuse `_params` and the randomized invariant test.
