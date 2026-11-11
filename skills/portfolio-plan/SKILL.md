---
name: portfolio-plan
description: Plans the portfolio against targets with the picks sleeve as one line. Use when the user says "rebalance", "am I off target", "where does this deposit go", "add $5k to my picks", "open a pick" or asks their ETF vs stock mix.
---
One portfolio plan over the connected accounts. The global plan rebalances classes, funds and the picks sleeve as one line, and the sleeve has its own rules for the picks inside it. The scripts decide every trade; the reply presents them, their tax cost and where each order would land. This skill never places orders.

## Background

**The plan**

- **Targets.** `plan.targets` in settings.json, summing to 100%. A key is a symbol, a class (`plan.classes` maps symbols to it), `CASH`, or a sleeve: `PICKS` (the stocks the person picked, in trading accounts) or `EMPLOYER` (the saved `plan.sleeves.EMPLOYER.members`).
- **A sleeve is one line.** The global plan measures the sleeve's total against its target and buys or sells the sleeve as a whole. A holding no key reaches (a pick in a retirement account, a stock with no class) is left untouched and listed under `UNMAPPED`.
- **The picks sleeve's size.** Its target is `plan.targets.PICKS` when targets are saved, else `plan.sleeves.PICKS.target`. A glide (`plan.sleeves.PICKS.glide`, `{to, by}`) is a target with a date: new money goes to the sleeve first until it reaches `to`, and `status` shows the monthly pace to get there by `by`. No target means the sleeve's size is unmanaged.

| Question | Global plan | Inside the picks sleeve |
|---|---|---|
| What is rebalanced | Classes, funds and the sleeve as one line | The individual picks |
| Target | The saved weights | The sleeve's weighting: equal, market cap, valuation tilt or current size |
| When it trades | A band breach or the person's calendar | Only on request |
| Bands | 5/25 | 25% of target or $250, whichever is larger |
| Where sells land | Tax-advantaged accounts first | Same account only; proceeds buy other picks |
| What holds a position still | Nothing | Re-check due, deep valuation needed, no market cap |
| Tax | Highest-cost lots, short-term policy | The same |

**No targets saved** is a supported state, and the common one.

- A contribution buys the core funds already held, pro rata to their value. The picks sleeve takes money only when it has a target in force and sits below it, or when the person asks to add to their picks.
- A withdrawal draws pro rata from today's weights of every holding and the cash, tax-advantaged accounts first.
- "Rebalance" reports that no targets exist and offers today's weights (`derived_targets`) as a starting point, with no trades.

**Bands and when to rebalance**

- The 5/25 rule (Swedroe) triggers when an allocation is 5 percentage points off, or 25% of its own target off, whichever comes first. These are the default `bands.absolute` and `bands.relative`.
- Calendar rebalancing (annual or semi-annual) is the simpler alternative. Evidence favours rebalancing for risk control, not for return.
- Drift between scheduled checks is normal. The plan is for a breach, or for the calendar the user picked, not for every price move, unless the user asks.
- Cash-flow rebalancing (routing contributions to underweights, taking withdrawals from overweights) avoids realized gains and is the first tool in taxable accounts.

**The picks sleeve**

| Bucket | What is in it |
|---|---|
| core | ETFs, mutual funds and other fund holdings, including a fund Yahoo labels a plain stock with no sector when its name is fund-shaped (SPYM) |
| picks | individual stocks (plain equities) other than the employer stock |
| employer | the saved employer member, in every account, unless it has a saved deep pick (then it is a pick) |
| cash | account cash and money market funds; a sweep fund the broker also reports as the account's cash (Fidelity's SPAXX) is counted once |

- **Employer stock is its own bucket.** It is outside the picks sleeve, `n_eff` and `tracking_error`, and never receives sleeve money unless the pick store holds a deep pick for it. `EMPLOYER_CONCENTRATION` fires above 10% of total value.
- **Picks live in trading accounts.** A stock held in a retirement account counts toward the sleeve's mix, gets `PICK_IN_RETIREMENT` and no trades.
- **Each sale and buy stay in the same account.** A trading account funds a new pick from its own cash, then by selling its own core funds: funds named with `--sell` first, then US equity, international, other, and bond funds last (`BOND_FUND_SOLD`), smallest gain first within each. Retirement core is never sold.
- **Four strategies.** `plan.sleeves.PICKS.weighting`, or `--weighting` for one run, sets how money is split between picks.

  | Strategy | Share of a pick | Adds money | Rebalance |
  |---|---|---|---|
  | `equal` | the same for every pick | yes | yes |
  | `market_cap` | the company's market cap | yes | yes |
  | `valuation` | tilted toward higher `expected_return` | yes | yes |
  | `size` | the pick's current value | yes | exit 2 |

- **`equal` is the default.** Research finds equal or size weights hard to beat and estimated returns the weakest input, so `valuation` runs only when the person asks for it or has saved it. The person chooses the strategy; never question the choice.
- **Adding money only buys.** Adding to picks, a contribution and the rest of an opened pick with `--amount` never sell a pick.
- **Valuation weighting** uses deep picks from the stock-screener pick store. The tilt shrinks as the valuation ages (half-life 182 days) and a pick due for a recheck gets none. Light picks and stocks with no saved valuation take a neutral share. With no eligible pick, adding money splits equally (`weighting_used` is `equal`); a rebalance exits 2.
- **Deep depth.** Light picks are held (`DEEP_VALUATION_NEEDED`), `--include-light` and opening a light pick are refused (exit 2), and a saved `include_light` is ignored.
- **Held picks, under every strategy.** A pick due for a recheck holds its value (`HELD_FOR_RECHECK`); so does one whose deep valuation needs a rerun (`DEEP_VALUATION_NEEDED`), and under `market_cap` one with no market cap (`NO_MARKET_CAP`).
- **Opening a pick.** A new pick opens at the median of the existing picks, capped at 5% of total value, in the trading account holding the most pick value (with no picks yet, the one with the most cash plus core). With an open re-check or a needed valuation rerun it still opens, and carries the flag.
- **Rebalancing the picks happens only on request.** It moves money between picks and keeps the sleeve total, using no cash and selling no core fund.
  - A pick is trimmed only when it is above target by at least max(25% of its target, $250). Any pick below target can receive proceeds, furthest below first (`IN_BAND` means it is inside its band and did not trade).
  - Each account trims no further than the picks in that account can take, and proceeds buy picks in the same account only. With whole shares, under one share's worth can remain (`UNALLOCATED`).
- **The 5% cap** limits a pick's target under every strategy except `size`.
- **The research.** Read `references/research.md` before explaining where the sleeve's proposed size, its tracking error or its weighting come from.

**Accounts and tax**

- **Account roles** decide taxability: trading and savings accounts are taxable, retirement accounts are tax-advantaged. An account with no saved role (`accounts.<id>.role`) is classified from its raw type, a guess echoed in `routing.accounts`; `--taxable` and `--tax-advantaged` correct it for one run.
- Global sells are filled from tax-advantaged accounts first; routing is skipped when every account is taxable.
- Asset location: holding the same target mix, it is generally more tax-efficient to sell from tax-advantaged accounts first and to place buys in taxable accounts first. Present this as guidance only; the user decides what to hold where.
- The tax estimate uses the highest-cost lots first. When `ledger.json` holds BUY/SELL history, lots are replayed FIFO per (symbol, account) with real long/short terms; otherwise the broker's average price is used, the term is unknown and the short-term rate applies. `lot_sources` says which.
- `taxes.short_term_gain_policy`: `hold` keeps short-term and unknown-term gains in taxable accounts unsold, `allow` sells them. Unset runs as hold and raises `STANDING_DEFAULT` the first time it applies.
- Every SnapTrade-connected account takes whole shares only; a directly connected E*Trade account takes fractions. A broker's fractional refusal saves `accounts.<id>.whole_shares`, and every plan run touching that account then sizes in whole shares.

**The page**

`render.py` turns a saved `rebalance` or `withdraw` result (its global plan) into one self-contained HTML page for the Artifact tool: stat tiles, drift-vs-target bars with the band edges, a sortable allocation table, the trade list with account, reason, estimated gain and tax and the lots on hover, routing, post-trade weights, suggested bands when present, flags, and the "a plan, not orders" note.

**Other skills.** Orders go through the trading skill's order protocol. Exact lots and wash sales belong to tax-aware. Deep valuations belong to valuation, saved through stock-screener. Saved settings change through the get-started skill's `settings.py set`.

## Scripts

Run with the Bash tool. Every script prints JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-plan/scripts/plan.py" status [common]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-plan/scripts/plan.py" contribute AMOUNT [--sleeve PICKS] [common]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-plan/scripts/plan.py" withdraw AMOUNT [common]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-plan/scripts/plan.py" rebalance [--sleeve PICKS] [common]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-plan/scripts/plan.py" open SYMBOL [--amount A] [common]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-plan/scripts/global_plan.py" [--target KEY=WEIGHT ...] [--class SYMBOL=KEY ...] [--targets FILE] [--save] [--account ID ...] [--suggest-bands] [--only-if-breached] [--taxable ID ...] [--tax-advantaged ID ...] [common]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/portfolio-plan/scripts/render.py" --in plan.json --out page.html
```

Common flags: `[--weighting equal|market_cap|valuation|size] [--include-light] [--over-ceiling] [--whole-shares] [--sell SYM[,SYM]] [--short-term R] [--long-term R] [--min-trade N] [--band-abs R] [--band-rel R] [--partial]`. The sleeve flags reach the picks sleeve, the band and min-trade flags reach the global plan.

| Command | What it does |
|---|---|
| `plan.py status` | `sleeves` (the sleeve mix: buckets, `n_eff`, `tracking_error`, the target in force and the room under it), `global` (the global plan's allocation and drift without trades, or null with no saved targets), `targets_saved`, `sleeve_target`, `glide` (`to`, `by`, `months_left`, `monthly`). |
| `plan.py contribute AMOUNT` | AMOUNT is cash already in the accounts. The picks sleeve takes its share first when it sits below its target in force; the rest is routed by the global plan with no sells (no targets: the core funds held, pro rata). `sleeve` and `global` hold each part. |
| `plan.py contribute AMOUNT --sleeve PICKS` | Puts AMOUNT of trading-account cash into the held picks. |
| `plan.py withdraw AMOUNT` | Raises AMOUNT; with no targets, pro rata from today's weights. |
| `plan.py rebalance` | The global plan against the saved targets; with no targets, `no_targets` and `derived_targets`, no trades. |
| `plan.py rebalance --sleeve PICKS` | Only on request. Trims picks above their band and buys picks below target in the same account. No cash, no core sales, same sleeve total. |
| `plan.py open SYMBOL` | Sizes a stock not yet held at `new_pick.needed`; with `--amount`, the rest goes to the current picks. |
| `global_plan.py` | The global plan on its own, for inline targets (`--target`, `--class`, `--save`), one account (`--account`), suggested bands or a periodic check (`--only-if-breached`). |
| `render.py` | The page from a saved global plan. Prints `{"out", "title", "trades", "breaches", "flags"}`. |

Every `plan.py` output carries `command`, `sleeve` (the sleeve engine's output or null), `global` (the global plan's output or null), `trades` (sleeve trades, then global trades) and `flags`.

| Flag | Effect |
|---|---|
| `--weighting` | This run only; wins over the saved weighting. `size` works for adding money only. |
| `--include-light` | This run only, standard depth only; light valuations enter the tilt. |
| `--over-ceiling` | Lets the picks sleeve pass its target. Only when the person asked for that in their own words. |
| `--whole-shares` | Whole-share trades, when the broker does not take fractional orders or a preview rejects fractional units. |
| `--sell SYM[,SYM]` | Core funds sold first, in that order, when a new pick's account is short of cash. Each must be a core fund held in a trading account, else exit 2. |
| `--short-term R`, `--long-term R` | Tax rates behind `est_tax`. Defaults 0.24 and 0.15. |
| `--min-trade N`, `--band-abs R`, `--band-rel R` | Global plan: skip trades under N dollars; band widths as decimals (defaults 0.05 and 0.25). |
| `--partial` | Run without E*Trade when its login is pending. |

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Bad input: an amount above the cash; a symbol already held, the employer symbol, or anything but a single stock for `open`; weights not summing to 1; an unknown account; `--sleeve` other than PICKS; for `rebalance --sleeve PICKS`, weighting `size`, `--sell`, `--over-ceiling`, `valuation` with no eligible pick, an unreadable pick store, or a margin debit | Show `error`. |
| 4 | Credentials missing | Show the `hint`. |
| 4, code `ETRADE_REAUTH` | An E*Trade login is needed | Follow the session's broker-login rule: show the `url`, get the verifier code, run the connect skill's `etrade-login.py --verifier CODE`, rerun once. `--partial` runs without E*Trade. |
| 5 | SnapTrade error, or an unreadable `settings.json` | Show the error and the `hint`. |
| 6 | Python dependencies missing | Show the error, and say the get-started skill repairs it. |

## Steps

Every case starts with a script call, which is the same-day holdings read. After each call, apply **After every run** before showing any split or trades. DIR is the session scratchpad.

**Before adding to picks, opening a pick or rebalancing the picks, under every strategy:** run stock-screener's `picks.py due` and follow its re-check steps for each due pick, recording each check. A pick whose check cannot finish yet is held by the plan.

**"What's my ETF vs stock mix", "how am I doing against my plan"**

1. Run `plan.py status`.
2. Reply with the status format.

**"Where does this deposit go", "put the new cash to work", a deposit or vest proceeds landed**

1. Run `plan.py contribute AMOUNT`. For "put the new cash to work", AMOUNT is the cash in the session inbox's arrival line (the last-read record's `arrivals`); with no arrival recorded, ask how much.
2. Reply with the contribution format, then the hand-off under **After the person approves trades**.

**"My RSUs vested"**

Vested shares arrive as shares and show up as employer stock. The employer policy (`plan.sleeves.EMPLOYER.policy`) says what happens next:

| Policy | Steps |
|---|---|
| `sell_on_arrival` | 1. Offer the sale of the arrived units (the inbox's vest line) as the first row of the trade list. 2. Run `plan.py contribute PROCEEDS` with the sale's estimated proceeds and append its trades after the sale. 3. One hand-off for the whole list, sale first. |
| `hold` | Say the shares are kept under the saved policy, and run `plan.py status` for the employer weight. |
| unset | Run `plan.py status`, show the employer weight, and ask once whether to sell on arrival or hold. Save the answer with `settings.py set plan.sleeves.EMPLOYER.policy`. |

**"Add $X to my picks"**

1. Run `plan.py contribute X --sleeve PICKS`, with `--weighting` when the person names a strategy for this run and `--include-light` only when they ask.
2. Reply with the sleeve format, then the hand-off.

**"Raise $X", a withdrawal**

1. Run `plan.py withdraw X > DIR/portfolio-plan.json`.
2. Deliver the page (below), then the hand-off.

**"Rebalance", "am I off target"**

1. Run `plan.py rebalance > DIR/portfolio-plan.json`.
2. If `no_targets` is true, show `derived_targets` as a table (Key · Weight today), say no targets are saved, and ask whether to save these or other weights. Stop.
3. Deliver the page (below), then the hand-off.

**"Rebalance my picks"**

1. Run `plan.py rebalance --sleeve PICKS`, with `--weighting` only when the person names a strategy for this run.
2. If the person just placed a new pick and it is not in the holdings the run read, say so and wait for it to settle.
3. Reply with the sleeve format, then the hand-off.
   - `ABOVE_CEILING` can appear from the mix; a picks rebalance keeps the sleeve total, so the target does not limit it.
   - For a pick carrying `TRIM_UNPLACEABLE`, say it stays above target because no pick below target in its account can take the proceeds. For `TRIM_HELD_BACK`, say the short-term-gain policy keeps its `held_back` amount from selling.

**"I have a new pick"**

1. Run `plan.py open SYMBOL`, with `--amount A` when they fix the amount and `--sell SYM` when they name the fund that pays for it.
2. Show `sleeve.new_pick.needed`, `allocated` and `account`; with `--amount`, the rest is in `sleeve.splits`. A new pick carrying `RECHECK_DUE` or `DEEP_VALUATION_NEEDED` still opens; show the flag. Say once that a picks rebalance is available afterwards.
3. Reply with the sleeve format, then the hand-off.

**Changing the plan**

1. Run `plan.py status` so the change is shown against today's holdings.
2. Run the get-started skill's `settings.py set KEY VALUE` with the value from the person's own words, as fractions:

   | The person says | KEY VALUE |
   |---|---|
   | "my targets are 60% VTI, 30% BND, 10% picks" | `plan.targets '{"VTI": 0.6, "BND": 0.3, "PICKS": 0.1}'` |
   | "keep my picks at 15%" (no global targets) | `plan.sleeves.PICKS.target 0.15` |
   | "get my picks to 20% by June 2027" | `plan.sleeves.PICKS.glide '{"to": 0.2, "by": "2027-06-30"}'` |
   | "stop managing the size of my picks" | `plan.sleeves.PICKS.target none` and `plan.sleeves.PICKS.glide none` |
   | "always split by valuation" / "split equally" | `plan.sleeves.PICKS.weighting valuation` / `equal` |
   | "my employer stock is AMZN" / "I have no employer stock" | `plan.sleeves.EMPLOYER.members AMZN` / `none` |
   | "never sell short-term gains" / "short-term sales are fine" | `taxes.short_term_gain_policy hold` / `allow` |

3. Rerun `plan.py status`, and say what changed and what the next run uses.

**Delivering the page** (withdraw and global rebalance)

1. If the Artifact tool is available, run `render.py --in DIR/portfolio-plan.json --out DIR/portfolio-plan.html` (it renders the `global` part), publish it (icon scale, description "Portfolio plan as of DATE"), republish the same path on later runs, and reply with the page format.
2. Otherwise reply with the global markdown format.

### After every run

1. If a `STANDING_DEFAULT` flag is present, the run already used a conservative default; show the plan and give the flag's message as one line under Flags. Never stop the reply to ask.
   - "employer_symbol is unset": the run used `employer_candidate` (vest deposits in account history) as employer stock, or no employer stock when there is no candidate. Add "Say \"my employer stock is TICKER\" or \"I have no employer stock\" to save it."
   - "short_term_gain_policy is unset": the run held short-term gains back, listed in `held_back` (`symbol`, `value`, `account`, `long_term_date`). Add "Say \"short-term sales are fine\" to allow them."
2. Save a setting only after the person says it in their own words, then rerun the same command.
3. If `UNCLASSIFIED`, `NO_PRICE`, `PICK_STORE_UNREADABLE`, `PICK_BASELINE_MISSING`, `NO_PICK_STORE` or `NO_MARKET_CAP` is in `flags`, name the symbols from its `message` and continue. Never guess a classification.
4. If `LIGHT_VALUATION` or `NO_SAVED_VALUATION` is in `flags`, offer a deep valuation of those symbols in standard depth (the valuation skill's Deep steps, saved with stock-screener's `picks.py save-deep`); in deep depth run it under the session's depth rule. If `RECHECK_DUE`, offer the stock-screener re-check. Name each `HELD_FOR_RECHECK` and `DEEP_VALUATION_NEEDED` pick and why it is held.
5. If `NO_HOLDINGS` names `PICKS`, say the picks sleeve has a target and no picks to buy, and that `open` starts one.
6. If `UNMAPPED` is in `flags`, list the holdings it names as "not in the plan", one line each.

### After the person approves trades

The chain from plan to orders: the pick re-checks (before a picks run) and any E*Trade login happen at the start, before the plan. Once the person approves, nothing else is asked before the confirmation block.

1. Hand the rows of `trades` straight to the trading skill's order protocol as a plan's trade list, each in its `account`: the pre-buy check, then the preview of every row, then one confirmation block for them all. In a cash account, sells come before the buys they fund.
2. If a sell is in a taxable account, point to the tax-aware skill for exact lots and wash-sale checks before that sell.
   - For a picks-sleeve sell, say the order must use specific-lot identification for exactly those lots in `trades[].lots`, not the broker's default lot order.
   - If the person's broker cannot sell specific lots, say the plan's tax result does not hold (`est_gain`, `est_tax` and which gains were held back), and ask before going ahead.
3. When the orders are placed, run `plan.py status` again for the new mix.

## Reply format

The **Next step** line, used in every format, is: "This is a plan. To place these orders, say so; they go through the trading skill's preview-and-confirm protocol, where one `confirm` places the whole list." The session's standing "Next you could ask:" follow-ups block, when it applies, comes after it.

**Status format**

1. **Mix** — table from `sleeves.mix`: Bucket · Value · Weight for core, picks (`satellite`), employer, cash and total. Under it: `n_eff` picks (effective), tracking error `tracking_error`, single-stock total `single_stock_total`.
2. **Picks target** — `sleeve_target` (or "unmanaged" when null), room `sleeves.mix.room_under_ceiling`, proposed size `sleeves.mix.proposed_size`. With `glide`: to `glide.to` by `glide.by`, `glide.months_left` months left, about `glide.monthly` a month.
3. **Against targets** — only when `global` is present: table from `global.allocation`: Key · Value · Weight · Target · Drift · Breach.
4. **Flags** — one bullet per message from `sleeves.flags` and `global.flags`, or "None".

**Contribution format**

1. One line: AMOUNT, the picks part (`sleeve.satellite_net`, or none) and the rest routed by the plan, and whether the global part used saved targets or the core funds held (`global.sources.targets`).
2. **Trades** — table from `trades`: Account · Symbol · Side · Units · Price · Value. When `unallocated_amount` or `global.cash_after` is above 0, say it stays as cash.
3. **Flags**, then the **Next step** line.

**Sleeve format** (adding to picks, opening a pick, rebalancing the picks)

1. **Mix** — as in the status format, from `sleeve.mix`.
2. **Split** — table from `sleeve.splits`. Adding: Symbol · Current · Buy (`delta`) · After (`target`) · Account · Flags. Rebalance: Symbol · Current · Target · Delta · Account · Flags. Add the new pick as a row when `sleeve.new_pick` is present. State `weighting_used`; when it is `equal` and the weighting was `valuation`, say no pick had an eligible valuation.
3. **Held back** — only when `sleeve.held_back` is not empty: Symbol · Value · Account · Long-term date.
4. **Trades** — table from `trades`: Account · Symbol · Side · Units · Price · Value · Est. gain · Est. tax. Under it, for each SELL, its `trades[].lots`: acquired date, `units` and `term`, or "no lot record" when `lots` is `null`. Then one line per `sleeve.accounts[]`: funding `funding.cash` cash and `funding.core_sells` core sales. Write "No trades." when `trades` is empty.
5. **Flags**, then **Settings used** — one line from `sleeve.settings_used` (`ceiling` is the target in force; `employer_symbol` "unset" when `null`; `depth`), naming any flag passed for this run only. Then the **Next step** line.

**Page format** (when the page was published), in this order, then stop:

1. The artifact link on its own line.
2. One line: `mode` rebalance of `total_value` · max drift `max_drift` · N of M keys outside the bands · `trades` count (buys `buys_total`, sells `sells_total`) · est. tax `est_tax` (withdrawal `withdrawal` when non-zero).
3. **Flags** — one bullet per `flags[].message`, or "None".
4. The **Next step** line.

Do not repeat the sections the page carries. If the user asks for a number the page shows, read it from the JSON.

**Global markdown format** (only when the Artifact tool is unavailable)

1. **Allocation** — table from `global.allocation`: Key · Members · Value · Weight · Target · Drift · Relative · Breach.
2. **Trades** — table from `trades`: Account · Symbol · Side · Units · Price · Value · Reason · Est. gain · Est. tax. Then buys, sells, cash after, turnover, estimated realized gain and tax. When `global.routing` is present and `est_tax` differs from `routing.est_tax_pro_rata`, say filling sells from tax-advantaged accounts first changes the estimated tax from `est_tax_pro_rata` to `est_tax`.
3. **After trades** — table from `global.post_trade`: Key · Weight · Target · Drift.
4. **Flags**; **Suggested bands** only with `--suggest-bands` (proposals from one year of volatility, not advice); then the **Next step** line.

| Value | Format |
|---|---|
| Money | 2 dp with thousands separators |
| Weights, drifts, targets, tracking error | percentages to 1 dp |
| `n_eff` | 1 dp |
| Units | 4 dp; whole numbers with whole shares |

## Rules

- Never place orders from this skill. Orders go through the trading skill's order protocol after the person's yes.
- Every number comes from the scripts. The only arithmetic is converting the person's percentages to fractions or dollars.
- Run each script command once per answer. The exceptions are a rerun after a saved setting or an E*Trade login, and the `status` after orders are placed.
- Publish the page or write the markdown fallback, never both.
- Never plan the picks sleeve above its target. Pass `--over-ceiling` only when the person asked in their own words to go above it.
- Change a saved setting only after the person answers in their own words. Never change one silently.
- Never treat a light valuation as deep. A light pick in the tilt keeps its `LIGHT_VALUATION` flag in the reply.
- Never send picks money to a retirement account, or to the employer stock unless it has a saved deep pick.
- No advice about whether to rebalance. State what the bands say and what the trades would do. Present suggested bands as proposals.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
