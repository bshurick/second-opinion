# Core/satellite: one weighting strategy; adding money, new picks and rebalancing kept apart

Date: 2026-10-30. Status: draft, pending the person's review. Amends
`2026-10-29-core-satellite-design.md` and replaces
`2026-10-29-core-satellite-rebalance-design.md`; where they disagree, this one wins.

## Intent

The person changed their mind about making rebalance the default (commit 4e65767).
Growing the picks, opening a new pick and rebalancing are three separate decisions,
and a run should do only the one that was asked for. Today one run under valuation
weighting can place new money, open a stock and sell other picks together.

How money is divided is a separate choice again: an overall strategy the person
picks once, as a view on how a picks sleeve should be weighted. The person's words:
"opposing overall strategies", applied to "all rebalancing decisions", "my selection
would be valuation across the board".

### Goals
- A saved weighting strategy used by every action: `equal`, `market_cap`, `valuation`,
  plus `size` for adding money only.
- Adding money only buys. It never sells a pick.
- A new pick opens at the plain median of the existing picks and changes nothing else.
- Rebalancing is its own command, run only on request, that keeps the sleeve total.

### Non-goals
- Custom percentage weights. The person called them uncommon. A later fourth strategy
  should fit without changing the actions.
- Stock/bond/cash targets, or rebalancing core funds against each other.
- Changes to what counts as a pick or core, to account routing, or to the order path.

### Anti-goals (failure even if it technically works)
- A pick sold by `add`, `deposit`, `grow`, `plan-step` or `new-pick`.
- A rebalance that runs without being asked for, or that adds or withdraws money.
- A strategy swapped silently: a run that cannot apply the chosen strategy says so.
- A second rebalance on unchanged prices and data producing trades.
- Warning about or arguing against a strategy the person chose. Market cap and equal
  are legitimate strategies, not risks to flag.

## Decisions made with the person

- **Strategies:** equal (fixed spread, same dollars each), market cap (the company's
  market capitalisation), valuation. "Market value" means market cap.
- **Size stays as an option for adding money,** pro rata to current position value. It
  cannot rebalance: every pick already sits at its own size.
- **Their saved `weighting` stays `valuation`,** used across the board.
- **New pick:** the median of the other picks. No rebalance by default.
- **Rebalance after a new pick** is a second, separate request.
- **Custom percentages left out for now** (proposed in the conversation, not objected to).
- **Large picks can be trimmed.** There is no exemption for a pick above 5% that is not
  overvalued; the cap limits targets only. The person accepted that these may be the
  largest sales and tax bills in a rebalance.
- **Bands decide what is sold, not what can receive proceeds.** The person accepted more
  small buy orders in exchange.

## Behaviour

### Strategy weights

Each pick gets a raw weight; shares are raw weight over the sum across the picks taking
part.

| Strategy | Raw weight | Add money | Rebalance |
|---|---|---|---|
| `equal` | 1 | yes | yes |
| `market_cap` | the company's market cap | yes | yes |
| `valuation` | `weights.new_pick_multiplier` (rename it): the tilt, or the trim factor when priced above central x 1.05; 1.0 with no eligible valuation or confidence 0 | yes | yes |
| `size` | current position value | yes | exit 2 |

`--weighting` overrides the saved value for one run. With nothing saved, `equal` is used.

### Adding money (`add`, `deposit --satellite`, `grow`, `plan-step`)
- The money is split by the strategy's shares across the trading-account picks, whatever
  they already hold. Valuation therefore no longer multiplies by current size: two
  equally valued picks get the same dollars.
- Buys only. An overvalued pick gets a smaller share and is not trimmed.
- The 5% pick cap limits buys for `equal`, `market_cap` and `valuation`; the overflow
  goes to the other picks by their shares, and what no pick can take stays as cash
  (`unallocated_amount`). `size` keeps today's behaviour.
- Funding, the ceiling, `--sell`, the core-sale order and the short-term hold-back on
  core sales are unchanged.
- `IN_BAND` does not apply: bands never block new money.

### New pick (`new-pick SYM`)
- Opens at `weights.median_pick_value` of the trading-account picks, capped at 5% of total.
  The strategy does not change its size.
- Sells no pick. Funded from the account's cash, then core sales, in the account already
  chosen today.
- `--amount A`: the new pick takes min(median, A), and the rest is split across the
  existing picks as an add.
- With no picks yet, `--amount` is required, as today.
- `new_pick` output drops `size_needed` and `valuation_multiplier`.

### Rebalance (`run.py rebalance`, new)
- Moves the trading-account picks toward strategy share x the current sleeve total. Pick
  sells fund pick buys, in the same account. No cash is used, no core fund is sold, and
  the ceiling is not consulted.
- Bands decide what is sold: a pick is trimmed only when it is above target by at least
  max(25% of target, $250). Any pick below target can receive the proceeds, including one
  inside its band, furthest below target first. This is what the code does today; the old
  wording that an in-band pick is left alone is corrected in SKILL.md.
- Trim limits and routing are unchanged: trims go no further than the picks below target
  can take, and are taken where the buys land; a sale's proceeds buy in their own account
  only.
- No pick is exempt from trimming for being large. A pick above its target can be trimmed
  under every strategy, so the `fixed[sym] = current[sym]` branch for picks above 5% goes.
  The 5% cap only limits how high a target can be: a target never exceeds 5% of total, so
  a pick above 5% trims toward that limit when outside its band. The trim limit above still
  applies, so when every other pick is at its own target or cap the rest stays unsold: a
  rebalance cannot leave proceeds as cash.
- `valuation` here means equal base x tilt, as today, except that a pick with no eligible
  valuation now gets the neutral weight rather than its size share. It can be traded.
- `short_term_gain_policy` applies to the trims.
- `size` as the effective strategy, `--sell` or `--over-ceiling` is exit 2, and the `size`
  error names the strategies that can rebalance.
- `record-increase` is not run after a rebalance: the sleeve did not grow.

### Held picks (every strategy, every action)
A pick due for a recheck (`HELD_FOR_RECHECK`) or whose deep valuation needs a rerun
(`DEEP_VALUATION_NEEDED`) receives no money and is not sold. Its value is fixed in a
rebalance and its share goes to the others. The skill runs stock-screener's re-check
before any run that can trade, under every strategy.

### Missing data
- A pick with no market cap under `market_cap`: flagged `NO_MARKET_CAP`, gets no new
  money and holds in a rebalance.
- No market cap for any pick: exit 2 for a rebalance or an add. There is no fallback to
  another strategy.
- `valuation` with no eligible pick: an add's weights are all neutral, so the split comes
  out equal, and `VALUATION_FALLBACK` says so and names equal, not size. A rebalance exits
  2, because it would sell picks to reach a strategy the person did not choose.
- An unreadable pick store (`PICK_STORE_UNREADABLE`): a rebalance exits 2 under every
  strategy, because the holds cannot be known. An add stays flagged and continues, as today.
- No pick store at all (`NO_PICK_STORE`): nothing can be held, so `equal` and `market_cap`
  continue, flagged.
- One symbol's baseline unreadable (`PICK_BASELINE_MISSING`): that pick holds in a
  rebalance and gets no new money.

### Removed
- `--no-rebalance` and `--same-size`; `rebalance` and `same_size` in `settings_used`.
- The seed-then-rebalance path in `new-pick`, and trims inside `_valuation_add`.
- The Size target and Valuation target reply columns.

### Settings
`decide weighting` accepts `equal`, `market_cap`, `valuation` and `size`. An existing saved
value keeps working unchanged.

## Skill changes
- SKILL.md: strategies, the three actions, a "the user wants to rebalance" case, the
  `decide` table, and the reply format. Add runs show Current, Buy, After. Rebalance runs
  show Current, Target, Delta, Flags.
- New-pick reply: mention rebalancing only as something available afterwards, once.
- A rebalance after a new pick waits until the new position shows in the holdings the
  run reads; when it is not there yet, say so rather than planning without it.
- Update `references/research.md` (the buy-only default returns, and the size-default and
  valuation-trim lines change), the SKILL.md description, README line, `docs/scripts.md`,
  `docs/examples.md` and CHANGELOG.

## Constraints
- `docs/skill-style.md` wording rules; SKILL.md lines under 400 characters.
- Every number from the scripts; plans only, orders via portfolio-analysis.
- `sleeves.py` stays free of network calls: `run.py` reads market caps and passes them in,
  and only when the effective strategy is `market_cap`.
- The seeded randomized money-invariant test keeps passing, with `rebalance` added.

## Calls made by the designer (not the person)
- **`equal` is the default with nothing saved,** replacing `size`. It needs no outside data
  and works for every action. This was stated in the conversation and not objected to.
- **Holds apply under every strategy,** not only valuation, so nothing trades on a pick
  whose re-check is open, even when the strategy does not read valuations.
- **No market cap holds the pick** rather than guessing a weight.
- **The new pick stays capped at 5%,** as today.
- **The hold rule covers held picks, not the new one.** A new pick with an open re-check or
  a valuation needing a rerun still opens at the median, because the person named it, and
  the matching flag appears in the reply. Today's rebalance path also skips the hold for it.
- **A failed read never sells.** Rebalances stop on an unreadable pick store rather than
  trading without the holds; see Missing data.
- **`rebalance` rejects `--sell` and `--over-ceiling`** rather than ignoring them.

## Left to the builder
- How much of `_valuation_rebalance` and `_valuation_add` to reuse or merge.
- Reading market caps via `market.company_info` or a batched equivalent.
- Exact JSON for the add and rebalance tables, within the existing `splits` and `trades`.
- Test fixtures; reuse `_params` and the randomized invariant test.
