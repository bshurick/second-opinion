---
name: core-satellite
description: Sizes and funds the stock-picks satellite against the index-fund core, with the mix, a ceiling, four split strategies, new picks, step-ups and on-request rebalancing. Use when the user says "add $5k to my picks", "grow my picks" or asks their ETF vs stock mix.
---
Treats the connected accounts as two sleeves, index funds (the core) and individual stocks the person picked (the satellite), and plans how money moves into the picks without crossing a ceiling. The scripts size, split and route; the reply presents the plan. This skill never places orders.

## Background

**Buckets**

| Bucket | What is in it |
|---|---|
| core | ETFs, mutual funds and other fund holdings, including a fund Yahoo labels a plain stock with no sector when its name is fund-shaped (SPYM) |
| satellite | individual stocks (plain equities) other than the employer stock |
| employer | the saved `employer_symbol`, in every account, unless it has a saved deep pick (then it is a satellite pick) |
| cash | account cash and money market funds; a sweep fund the broker also reports as the account's cash (Fidelity's SPAXX) is counted once |

- **Employer stock is its own bucket.** It is outside the satellite, the ceiling, `n_eff` and `tracking_error`, and never receives satellite money, unless the pick store holds a deep pick for it: then it is a pick like any other (`new-pick` takes it). `mix.single_stock_total` adds it to the satellite. `EMPLOYER_CONCENTRATION` fires when it is above 10% of total value, held as a pick or not.
- **Picks live in trading accounts only.** Retirement accounts hold core. A stock already held in a retirement account counts toward the satellite, gets `PICK_IN_RETIREMENT` and no trades.
- **Each sale and buy stay in the same account.** A trading account funds its pick buys from its own cash, then by selling its own core funds: any funds named with `--sell` first, in that order, then US equity funds, then international, other, and bond funds last (`BOND_FUND_SOLD`), smallest gain first within each. Retirement core is never sold.
- **Account roles.** The profile's `account_roles` (set in onboarding) decides trading vs retirement. Without one, the raw account type decides.
- **Live read.** Every `run.py` call reads positions, cash, prices and tax lots from the brokerage, so each case starts from today's holdings.

**Saved settings** (`core-satellite.json` in the plugin data directory; `settings.py show` prints them)

| Key | Meaning | When `null` |
|---|---|---|
| `ceiling` | Highest satellite weight of total value, as a fraction (0.20 = 20%) | The default ceiling 0.20 is used and `DECISION_NEEDED` is raised |
| `weighting` | `equal`, `market_cap`, `valuation` or `size` | `equal` |
| `include_light` | `true` lets light valuations into the tilt; they stay flagged, and their expected return is a 3-year convergence estimate from the light fair value | `false` |
| `short_term_gain_policy` | `hold` keeps short-term and unknown-term gains in taxable accounts unsold; `allow` sells them | Held back as under `hold`, and `DECISION_NEEDED` is raised the first time it applies |
| `employer_symbol` | Ticker of the person's employer stock, or `none` | No employer bucket, and `DECISION_NEEDED` is raised on every run |
| `increases` | Past satellite increases: date, amount, weight before and after, funding | `grow` has no `similar_to_last` |
| `plan` | A step-up plan: target weight, end date, cadence, funding, status, `next_due` | `plan-step` is bad input |

- **The default ceiling.** 0.20 of total value is a starting point the person decides on, not a target. `mix.proposed_size` is the size the tracking-error budget gives at the current `n_eff`, cut when `SECTOR_HEAVY`. Where both come from is in `references/research.md`.
- **Four strategies.** The saved or per-run `weighting` sets how money is split between picks.

  | Strategy | Share of a pick | Adds money | Rebalance |
  |---|---|---|---|
  | `equal` | the same for every pick | yes | yes |
  | `market_cap` | the company's market cap | yes | yes |
  | `valuation` | tilted toward higher `expected_return` | yes | yes |
  | `size` | the pick's current value | yes | exit 2 |

- **`equal` is the default** when nothing is saved. Research finds equal or size weights hard to beat and estimated returns the weakest input, so `valuation` runs only when the person asks for it or has saved it (`references/research.md`). The person chooses the strategy; never question the choice.
- **Adding money only buys.** `add`, `grow`, `plan-step`, the picks part of `deposit` and the rest of `new-pick` with `--amount` never sell a pick.
- **Valuation weighting** uses deep picks from the stock-screener pick store only. It shrinks the tilt as the valuation ages (half-life 182 days) and gives no tilt to a pick due for a recheck. Light picks and held stocks with no saved valuation take a neutral share. With no eligible pick, when adding money, the run splits equally and `weighting_used` is `equal`; a rebalance exits 2.
- **Held picks, under every strategy.** A pick due for a recheck holds its value and takes no money (`HELD_FOR_RECHECK`). A pick whose deep valuation needs a rerun holds the same way (`DEEP_VALUATION_NEEDED`). Under `market_cap`, a pick with no market cap holds too (`NO_MARKET_CAP`).
- **A new pick** opens at the median of the existing picks, capped at 5% of total value. The strategy does not change its size. With an open re-check or a needed valuation rerun it still opens, and carries the flag.
- **Rebalancing happens only on request** (`run.py rebalance`). It moves money between picks and keeps the sleeve total. It uses no cash and sells no core fund.
  - **Bands decide what is sold.** A pick is trimmed only when it is above target by at least max(25% of its target, $250). Any pick below target can receive proceeds, furthest below target first, including one inside its band (`IN_BAND` means it is inside its band and did not trade).
  - **Trims stay placeable.** Each account trims no further than the picks in that account can take. A sale's proceeds buy picks in the same account only. Proceeds never stay as cash; with whole shares, under one share's worth can remain (`UNALLOCATED`).
  - No pick is exempt from trimming for being large.
- **The 5% cap.** The 5% cap limits how high a pick's target can be, under every strategy except `size`.
- **Who receives money.** Only satellite stocks already held in a trading account. A new position opens only through `new-pick`, in the trading account that holds the most pick value (where the picks are kept); with no picks yet, the one with the most cash plus core.
- **The research.** Read `references/research.md` before explaining where the default ceiling, the proposed size, the tracking error or the weighting come from.
- **Rates are fractions.** Every weight, ceiling and grow value on the command line is a fraction: "5%" is `0.05`, "20%" is `0.20`.
- **Other skills.** Orders go through portfolio-analysis's order protocol. Wash sales and lot choices outside this plan belong to tax-aware. Deep valuations belong to valuation, saved through stock-screener. General target/drift rebalancing belongs to rebalancing.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/run.py" mix [common flags]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/run.py" add AMOUNT [common flags]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/run.py" deposit AMOUNT [--satellite AMOUNT] [common flags]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/run.py" grow [--to-weight W | --by-points P | --by-relative R | --by X | --amount A] [common flags]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/run.py" new-pick SYMBOL [--amount A] [common flags]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/run.py" plan-step [common flags]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/run.py" rebalance [common flags]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/settings.py" show
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/settings.py" decide KEY VALUE
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/settings.py" record-increase --amount A --before W --after W --funded-from TEXT
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/settings.py" plan-set --target W --by YYYY-MM-DD --cadence monthly|quarterly --funding cash|core
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/settings.py" plan-pause | plan-resume | plan-cancel | plan-advance
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/core-satellite/scripts/settings.py" summary
```

Common flags: `[--weighting equal|market_cap|valuation|size] [--include-light] [--over-ceiling] [--whole-shares] [--sell SYM[,SYM]] [--short-term R] [--long-term R] [--partial]`.

| Command | What it does |
|---|---|
| `run.py mix` | The sleeve mix, `n_eff`, `tracking_error`, ceiling and room. No trades. |
| `run.py add` | Puts AMOUNT of trading-account cash into the held picks. |
| `run.py deposit` | Without `--satellite`, returns a `proposal` split of new cash and no trades. With it, plans that part into picks and the rest into core funds. |
| `run.py grow` | Raises the satellite, funded from trading cash, then trading-account core sales. |
| `run.py new-pick` | Sizes a stock not yet held at `new_pick.needed`, the median current pick capped at 5%; with `--amount`, the rest goes to the current picks. |
| `run.py plan-step` | One step of the saved active plan, planned as `grow`. |
| `run.py rebalance` | Only on request. Trims picks above their band and buys picks below target in the same account. No cash, no core sales, same sleeve total. |
| `settings.py show` | The saved settings. |
| `settings.py decide` | Saves one decision. KEY is `ceiling`, `weighting`, `include_light`, `short_term_gain_policy` or `employer_symbol`. |
| `settings.py record-increase` | Appends a placed satellite increase to `increases`. |
| `settings.py plan-set` | Saves a step-up plan, first step due today. |
| `settings.py plan-pause`, `plan-resume`, `plan-cancel`, `plan-advance` | Change the plan; `plan-advance` moves `next_due` one cadence on. |
| `settings.py summary` | Plain text for the session-start hook when a plan step is due; nothing otherwise. |

| Flag | Effect |
|---|---|
| `--weighting equal\|market_cap\|valuation\|size` | This run only; wins over the saved `weighting`. `size` works for adding money only. |
| `--include-light` | This run only; light valuations enter the tilt. |
| `--over-ceiling` | Lets the satellite pass the ceiling. Only when the person asked for that in their own words. |
| `--whole-shares` | Whole-share trades. Pass it when the person says their broker does not take fractional orders, or when an order preview rejects fractional units. |
| `--sell SYM[,SYM]` | Core funds sold first, in that order, when an account's cash falls short ("sell BND for it"). Each must be a core fund held in a trading account, else exit 2. Cash is still used first. |
| `--short-term R`, `--long-term R` | Tax rates behind `est_tax`. Defaults 0.24 and 0.15. |
| `--partial` | Run without E*Trade when its login is pending. |

All commands print JSON except `settings.py summary`. `add` and `deposit` amounts must already be cash in trading accounts.

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Bad input: an amount above trading cash; a symbol already held, the employer symbol, or anything other than a single stock (a fund, option or unknown type); no active plan for `plan-step`; an unknown settings key | Show `error`. |
| 2 | Bad input for `rebalance`: weighting `size`, `--sell`, `--over-ceiling`, `valuation` with no eligible pick, `market_cap` with no market caps at all, an unreadable pick store, or negative cash (a margin debit) in an account with trades | Show `error`. |
| 4 | Credentials missing | Show the `hint`. |
| 4, code `ETRADE_REAUTH` | An E*Trade login is needed | Follow the session's broker-login rule: show the `url`, get the verifier code, run the connect skill's `etrade-login.py --verifier CODE`, rerun once. `--partial` runs without E*Trade. |
| 5 | SnapTrade error, or an unreadable `core-satellite.json` | Show the error and the `hint`. |
| 6 | Python dependencies missing | Show the error, and say the setup skill repairs it. |

## Steps

Every case starts with a `run.py` call, which is the same-day holdings read. After each `run.py` call, apply the checks under **After every run**, in order, before showing any split or trades.

**Before `add`, `deposit --satellite`, `grow`, `plan-step`, `new-pick` or `rebalance`, under every strategy:** run stock-screener's `picks.py due`, and follow its re-check steps for each due pick, recording each check. Then run the plan. A pick whose check cannot finish yet (no 10-Q and no earnings release to check against) is held by the plan.

**The user asks their mix ("what's my ETF vs stock mix")**

1. Run `run.py mix`.
2. Reply with the reply format (Mix, Ceiling, Flags, Settings used).

**The user wants to add $X to their picks**

1. Run `run.py add X`. Add `--weighting` with the strategy the person names for this run; add `--include-light` only when they ask to include light valuations.
2. Reply with the reply format, then the hand-off under **After the person approves trades**.

**A deposit or vest landed and the person gives no destination**

- Vested RSU shares arrive as shares and show up as employer stock. Selling them is the person's own decision, made outside this skill. Once sold, the proceeds are handled as a deposit here.

1. Run `run.py deposit AMOUNT`.
2. Show `proposal.satellite` and `proposal.core` with `mix.room_under_ceiling`, and ask how much goes to picks.
3. If they answer with a percentage, `run.py` takes dollars: show the conversion (the percentage times AMOUNT), and use the `proposal` figures where they match their answer.
4. Run `run.py deposit AMOUNT --satellite S` with the dollar figure.
5. Reply with the reply format, then the hand-off.

**The user wants to grow their picks**

1. Translate the request into one flag:

   | The user says | Flag |
   |---|---|
   | "make picks 15% of the portfolio" | `--to-weight 0.15` |
   | "grow picks by 2 percentage points" | `--by-points 0.02` |
   | "grow the picks sleeve by 10% of itself" | `--by-relative 0.10` |
   | "grow picks by 5%" (unclear which) | `--by 0.05` |
   | "grow picks by $3,000" | `--amount 3000` |
   | "grow my picks" with no size | no flag |

2. Run `run.py grow` with that flag.
3. If `AMBIGUOUS_PERCENT` is in `flags`, show both `readings.points` and `readings.relative` (`amount`, `weight_after`), ask which one, and rerun with `--by-points` or `--by-relative`.
4. If no flag was given, show `similar_to_last` (`amount`, `dates`) as one option beside the person's own amount, ask, and rerun with their choice.
5. Reply with the reply format, then the hand-off.

**The user has a new pick**

1. Run `run.py new-pick SYMBOL`, with `--amount A` when they fix the amount and `--sell SYM` when they name the fund that pays for it.
2. Show `new_pick.needed` (the median current pick, capped at 5%), then `new_pick.allocated` and `new_pick.account`. With `--amount`, the rest of A is in `splits`.
   - If the new pick carries `RECHECK_DUE` or `DEEP_VALUATION_NEEDED`, it still opens; show the flag.
   - Say once that a rebalance of the picks is available afterwards.
3. Reply with the reply format, then the hand-off.

**The user wants to rebalance**

1. Run `run.py rebalance`, with `--weighting` only when the person names a strategy for this run.
2. If the person just placed a new pick and it is not in the holdings the run read, say so and wait for it to settle rather than planning without it.
3. Reply with the reply format, then the hand-off. A rebalance runs no `record-increase`, because the sleeve total is unchanged.
4. `ABOVE_CEILING` can still appear from the mix. Show it as information; a rebalance keeps the sleeve total, so the ceiling does not limit it.
5. If a pick in `splits` carries `TRIM_UNPLACEABLE`, say it stays above its target because no pick below target in its account can take the proceeds, with the amount from its `flags` message.
6. If a pick carries `TRIM_HELD_BACK`, say the short-term-gain policy keeps the amount in its `held_back` row from selling.

**A plan step is due, or the user wants a plan**

1. To set one up: run `run.py mix`, ask the target weight, the end date, the cadence (monthly or quarterly) and the funding (`cash` only, or `core` sales too).
2. Run `settings.py plan-set --target W --by DATE --cadence C --funding F` with their answers, as fractions. W is at most `mix.ceiling`, unless the person asked in their own words for a target above the ceiling.
3. To run a step: run `run.py plan-step`, adding `--over-ceiling` only when the saved plan target is above the ceiling at the person's own request. Show `step.amount`, `step.target` and `step.steps_left`.
4. Reply with the reply format, then the hand-off.
5. After the step's orders are placed, run `settings.py plan-advance`.
6. "Pause", "resume" or "cancel the plan" runs `plan-pause`, `plan-resume` or `plan-cancel`. `plan-resume` works only on a paused plan and `plan-advance` only on an active one; `plan-set` takes no end date before today. Each exits 2 otherwise.

**The user wants to change a setting**

1. Run `run.py mix` so the change is shown against today's holdings.
2. Run `settings.py decide KEY VALUE` with the value from their own words:

   | The user says | Command |
   |---|---|
   | "cap my picks at 15%" | `decide ceiling 0.15` |
   | "keep the default ceiling for now" | `decide ceiling 0.2` |
   | "always split by valuation" | `decide weighting valuation` |
   | "split equally" / "go back to the default" | `decide weighting equal` |
   | "split by company size" / "by market cap" | `decide weighting market_cap` |
   | "split by what I hold now" | `decide weighting size` |
   | "use light valuations too" | `decide include_light true` |
   | "never sell short-term gains" / "short-term sales are fine" | `decide short_term_gain_policy hold` / `allow` |
   | "my employer stock is AMZN" | `decide employer_symbol AMZN` |
   | "I have no employer stock" | `decide employer_symbol none` |

3. Rerun `run.py mix`, and say which setting changed and what the next run uses.

**After every run**

1. If a `DECISION_NEEDED` message starts with "employer_symbol is unset", settle the employer ticker before showing any split or trades, whether or not they have mentioned an employer. "none" is a valid answer.
   - When `employer_candidate` is present, account history already shows vest deposits: show its `symbol`, `vests`, `every_days` and `sold_within_days`, and ask the person to confirm that ticker rather than asking cold. Do the same when the person has already named their employer in this or an earlier conversation.
   - Run `settings.py decide employer_symbol TICKER` (or `none`) with their answer, then rerun the same `run.py` command.
   - Until then any employer stock counts as a pick and can receive satellite money.
2. If `DECISION_NEEDED` is in `flags`, raise that decision in the reply:

   | Flag message starts with | Show | Then |
   |---|---|---|
   | "ceiling is unset" | `mix.ceiling` (the default ceiling), `mix.proposed_size`, `mix.tracking_error`, `mix.n_eff` | Ask what ceiling they want. |
   | "short_term_gain_policy is unset" | each `held_back` row (`symbol`, `value`, `account`, `long_term_date`); the estimated tax on realising them comes from the tax-aware skill | Ask hold or allow. |

   Run `settings.py decide` only after the person answers in their own words.
3. After every `settings.py decide`, rerun the same `run.py` command before any trades are shown.
4. If `UNCLASSIFIED`, `NO_PRICE`, `PICK_STORE_UNREADABLE`, `PICK_BASELINE_MISSING` or `NO_PICK_STORE` is in `flags`, name the symbols from its `message` and continue. Never guess a classification. `PICK_BASELINE_MISSING` means that pick holds: no new money and no trade.
   - If `NO_MARKET_CAP` is in `flags`, name the picks with no market cap; they hold under `market_cap`.
5. If `LIGHT_VALUATION` or `NO_SAVED_VALUATION` is in `flags`, offer a deep valuation of those symbols (the valuation skill's Deep steps, saved with stock-screener's `picks.py save-deep`). If `RECHECK_DUE`, offer the stock-screener re-check.
   - Name each `HELD_FOR_RECHECK` and `DEEP_VALUATION_NEEDED` pick and why it is held, and offer the deep valuation rerun for the second.
   - A new pick carrying either flag still opened.

**After the person approves trades**

1. Hand each row of `trades` to portfolio-analysis's order protocol, in its `account`, one order at a time with its own confirmation. In a cash account, sells come before the buys they fund.
2. With each SELL, say the order must use specific-lot identification for exactly those lots in `trades[].lots`, not the broker's default lot order.
   - If the person's broker cannot sell specific lots, say the plan's tax result does not hold (`est_gain`, `est_tax` and which gains were held back), and ask before going ahead.
   - Wash sales belong to tax-aware.
3. When the orders are placed, run `run.py mix` again for the new `mix.satellite.weight`.
4. Run `settings.py record-increase --amount A --before W1 --after W2 --funded-from TEXT`:
   - A is `satellite_net` when every row of `trades` was placed. Only when the person placed some of them, A is the placed satellite BUY `value`s less placed satellite SELL `value`s (satellite symbols are those in `splits` plus `new_pick.symbol`). A rebalance skips this step.
   - W1 is `mix.satellite.weight` from the planning run; W2 from the new run.
   - TEXT is "deposit" when the money came in as a deposit, vest proceeds or a bonus (the deposit case); else "core sales (SYMBOLS)" when an `accounts[].funding.core_sells` is above 0; else "cash".

## Reply format

In this order:

1. **Mix** — table: Bucket · Value · Weight, one row each for `mix.core`, `mix.satellite`, `mix.employer`, `mix.cash` and `mix.total`. Under it one line: `n_eff` picks (effective), tracking error `tracking_error`, single-stock total `single_stock_total`.
2. **Ceiling** — one line: ceiling `mix.ceiling` (`ceiling_source` saved or default), room `mix.room_under_ceiling`, proposed size `mix.proposed_size`. When `over_ceiling_amount` is above 0, add that it was left out.
3. **Split** — table from `splits`. For an add run: Symbol · Current · Buy (`delta`) · After (`target`) · Account · Flags. For a rebalance: Symbol · Current · Target · Delta · Account · Flags. Add the new pick as a row when `new_pick` is present.
   - State `weighting_used`. When it is `equal` and the weighting was `valuation`, say no pick had an eligible valuation. `weighting_used` is the strategy in force; on `mix` or a plain `new-pick`, nothing was split.
4. **Held back** — only when `held_back` is not empty: Symbol · Value · Account · Long-term date.
5. **Trades** — table from `trades`: Account · Symbol · Side · Units · Price · Value · Est. gain · Est. tax.
   - Under it, for each SELL (trading accounts are taxable), list its `trades[].lots`: acquired date (`acquired`), `units` and `term`, or "no lot record" when `lots` is `null`.
   - Then one line per `accounts[]`: account, funding `funding.cash` cash and `funding.core_sells` core sales. Write "No trades." when `trades` is empty. When `unallocated_amount` is above 0, say it stays as cash.
6. **Flags** — one bullet per `flags[].message`, or "None".
7. **Settings used** — one line from `settings_used`: `ceiling` (saved or default, from `mix.ceiling_source`), `weighting`, `include_light`, `short_term_gain_policy`, `employer_symbol` (write "unset" when `null`). Name any `--weighting` or `--include-light` passed for this run only.
8. **Next step** — "This is a plan. To place any of these orders, say which; each goes through portfolio-analysis's preview-and-confirm protocol one at a time."

For `mix` alone, show sections 1, 2, 6 and 7.

| Value | Format |
|---|---|
| Money | 2 dp with thousands separators |
| Weights, ceiling, tracking error | percentages to 1 dp |
| `n_eff` | 1 dp |
| Units | 4 dp; whole numbers with `--whole-shares` |

## Rules

- Never place orders from this skill. Orders go through portfolio-analysis's order protocol after the person's yes.
- Never plan a satellite above the ceiling. Pass `--over-ceiling` only when the person asked in their own words to go above it.
- Run `settings.py decide` only after the person answers in their own words. Never change a saved setting silently.
- Never treat a light valuation as deep. A light pick in the tilt keeps its `LIGHT_VALUATION` flag in the reply.
- Never send satellite money to a retirement account, or to the employer symbol unless it has a saved deep pick.
- Every number comes from the scripts. The only arithmetic is converting the person's percentages to fractions or dollars, and summing placed trade values for `record-increase` when only some trades were placed.
- Run each `run.py` command once per answer. The exceptions are a rerun after a `decide`, a reading choice or an E*Trade login, and the `run.py mix` after orders are placed.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
