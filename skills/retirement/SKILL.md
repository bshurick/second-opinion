---
name: retirement
description: Retirement and savings-goal planning with a projection through retirement, Monte Carlo success odds, nest egg required, contribution to close a gap, and sustainable withdrawal rates. Use when the user asks "am I on track" or "how much do I need to retire".
---
Runs retirement and goal projections with explicit assumptions, shows the range of outcomes, and says what moves them. Numbers come from the script; the reply describes them and what is not modelled.

## Background

- **`retirement.py` is the shared math.** Its docstring is the contract. Its actions are `goal`, `project`, `withdrawal` and `ss_claim`. Rates are decimals.
- **`retire.py` wraps it.** With `--from-accounts` it seeds the starting balance from the total of every connected account. With `--savings` it takes a number instead.
- **Defaults.**

  | Input | Default |
  |---|---|
  | Return | 6% |
  | Volatility | 12% |
  | Inflation | 2.5% |
  | Fees | 0.1% |
  | End age | 95 |
  | Withdrawal rate | 4% |
  | Contribution growth | 2% |
  | Simulations, seed | 2000, 42 |

- **Spending and contribution** are annual, and spending is in today's dollars.
- **The return assumption moves the result most.** One point of return over 25 years changes the balance at retirement by about 25%.
- **The withdrawal table is not the historical 4% rule.** The 4% rule (Bengen 1994; Cooley, Hubbard and Walz 1998) is a historical US stress test for a 30-year horizon with 50-75% stocks. The script's table is a Monte Carlo on stated return and volatility, so label it as such.
- **Sequence risk.** The same average return with bad early years in retirement depletes sooner. The worst-decile years-funded figure is the script's proxy.
- **Real balances.** Real (inflation-adjusted) balances are the ones that matter for spending. The projection reports both nominal and real.
- **Not modelled.** Contribution limits, employer matches and tax treatment; the personal-finance skill covers account rules.
- **Required minimum distributions are not modelled.** Past the RMD age the account owner must withdraw at least a mandated fraction of the balance each year regardless of `spending`, which complicates the script's `end_age` and `spending`/`withdrawal_rate` inputs.
- **Other skills.** "Which account should I withdraw from first" belongs to the tax-aware skill, which models withdrawal ordering and tax. This skill only projects total balances.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/retirement/scripts/retire.py" (--savings N | --from-accounts) --age A --retirement-age R [--end-age E] [--contribution N] [--contribution-growth R] [--spending N] [--other-income N --other-income-start-age A] [--return R --volatility R --inflation R --fees R] [--withdrawal-rate R] [--ret-return R --ret-vol R] [--guardrail-cut P --guardrail-trigger P] [--seed N --simulations N] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/retirement/scripts/retire.py" --goal TARGET (--years N | --monthly N) --savings N [--return R]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/retirement/scripts/retire.py" --withdrawal --savings N [--years N] [--spending N]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/retirement/scripts/retire.py" --ss-benefit N --retirement-age R (--savings N | --from-accounts) [--fra-age A] [--claim-age A ...] [--end-age E --return R --volatility R --inflation R --fees R --spending N --seed N --simulations N]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/retirement/scripts/retirement.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/retirement/scripts/render.py" --in retire.json --out page.html
```

| Command | What it does |
|---|---|
| `retire.py` (no mode flag) | The projection (`project`): a deterministic path to and through retirement with a Monte Carlo overlay. |
| `retire.py --goal` | What it takes to reach `TARGET`: the monthly contribution over `--years`, or the years at `--monthly`. |
| `retire.py --withdrawal` | The sustainable-withdrawal table, with the savings as the nest egg. |
| `retire.py --ss-benefit` | Compares Social Security claiming ages (62, 67 and 70 unless `--claim-age` is repeated) for an annual benefit at full retirement age. |
| `retirement.py` | The shared pure math. |
| `render.py` | Turns a saved `retire.py` result into one self-contained HTML page for the Artifact tool. Prints `{"out", "title", "action", "flags"}`. |

Optional projection flags:

| Flag | Effect |
|---|---|
| `--ret-return`, `--ret-vol` | A second return and volatility pair for the retirement years. |
| `--guardrail-cut`, `--guardrail-trigger` | Adds a guardrail variable-spending comparison. Both are required together. |
| `--partial` | With `--from-accounts`, runs without a broker that needs a login. |

The page `render.py` builds opens with assumption chips, defaults marked. It has light and dark themes and no external scripts.

| Action | What the page shows |
|---|---|
| Projection | Success-odds, nest-egg, balance-at-retirement and gap-closing tiles; the deterministic path with the Monte Carlo 10th-90th and 25th-75th percentile bands from `monte_carlo.percentile_path`; the gap and Monte Carlo tables; guardrails; the sortable year-by-year path |
| Goal | The goal tiles |
| Withdrawal | The sustainable-withdrawal table |
| Claiming | The claiming-age table |

Flags come last on every page.

All scripts print JSON.

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Missing or bad inputs. From `render.py`: the input is not a retirement result. | Show `error`. |
| 4 | Only with `--from-accounts`. Credentials missing. | Show the `hint`. |
| 4 with code `ETRADE_REAUTH` | An E*Trade login is needed. | Follow the session's broker-login rule: show the `url`, get the verifier code, run the connect skill's `etrade-login.py --verifier CODE`, rerun once. `--partial` runs without E*Trade. |
| 5 | SnapTrade error | Show the error. |
| 6 | Python dependencies missing | Show the error. |

## Steps

Pick the case that matches the request.

**The user asks "am I on track" or "how much do I need to retire" (projection)**

1. Collect age, retirement age, savings, annual contribution and annual spending in today's dollars. Ask only for what is missing. Offer `--from-accounts` to use connected balances for savings.
2. Apply the defaults in Background for anything the user did not give, and note which were defaults.
3. Run `retire.py` with the base assumptions and write its output to `DIR/retirement.json` (DIR is the session scratchpad).
4. Unless the user fixed the return, run it again with `--return` one point lower and keep that JSON too.
5. Deliver the page (below).

**The user asks "how much per month" to reach a target**

1. Run `retire.py --goal`, writing the output to `DIR/retirement.json`.
2. Deliver the page.

**The user asks "how long will it last" or "what rate is safe"**

1. Run `retire.py --withdrawal` with the nest egg as `--savings`, writing the output to `DIR/retirement.json`.
2. Deliver the page.

**The user asks when to claim Social Security**

1. Run `retire.py --ss-benefit` with the annual benefit at full retirement age, writing the output to `DIR/retirement.json`.
2. Deliver the page.

**The user asks about required minimum distributions**

1. Say that RMDs are not modelled and why, from Background.
2. Look up the current IRS RMD starting age with a web search before stating it. It has moved with recent legislation.
3. Link IRS Publication 590-B (irs.gov/publications/p590b) as the source.

**The user asks which account to withdraw from first**

1. Hand off to the tax-aware skill.

**Deliver the page**

1. Run `render.py --in DIR/retirement.json --out DIR/retirement.html`.
2. Publish the HTML with the Artifact tool: icon chart, description "Retirement projection at RETURN return, SPENDING spending" or the goal or withdrawal equivalent. Republish the same file path on later runs so the link stays stable.
3. Reply with the published-page format below.
4. If the Artifact tool is not available in the session (a headless or non-interactive host), skip steps 1 and 2 and reply with the markdown fallback instead. Never send both.

## Reply format

**Page published (the default).** In this order, then stop.

1. The artifact link on its own line.
2. One line of key figures:

   | Action | Key figures |
   |---|---|
   | Projection | Success odds `monte_carlo.success_probability` (and the lower-return run's probability when one ran) · Required nest egg `deterministic.required_nest_egg` · Balance at retirement `deterministic.balance_at_retirement` · Gap `deterministic.gap` (extra `deterministic.extra_annual_contribution_needed` per year to close it) |
   | Goal | `monthly_contribution_needed` per month to reach `target` in `years` years, or `years_to_reach` years at `monthly_contribution` |
   | Withdrawal | The 4% row's success probability, and `requested` when present |
   | Claiming | Each `claiming[]` age with its `first_year_benefit` and `success_probability` |

3. **Flags** — one bullet per `flags[].message`, or "None".
4. One sentence that it is general information at the stated assumptions, not financial, tax, or legal advice.

The page carries the assumptions, the fan chart, the Monte Carlo and gap tables, the year-by-year path and the withdrawal or claiming tables. Do not repeat them in the reply. If the user asks for a number the page shows, read it from the script's JSON.

**Markdown fallback (only when the Artifact tool is unavailable).** In this order.

1. The assumptions line: return, fees, volatility, inflation, contribution growth, withdrawal rate, simulations, seed. Say which were defaults.
2. The action that ran:
   - **Projection** — one line: retire at `retirement_age` in `years_to_retirement` years, fund `years_in_retirement` years.
     - A table from `deterministic`: Balance at retirement (nominal / real) · Spending at retirement · Required nest egg (`withdrawal_rate` rule) · Gap · Extra annual contribution to close it · Depletes at age.
     - Monte Carlo from `monte_carlo`: success probability, balance at retirement p10/p50/p90, ending balance p10/p50/p90, median depletion age, worst-decile years funded. Show the lower-return run's success probability beside the base one when it ran.
     - A 6-row slice of `deterministic.path` (now, retirement, every ten years, end) with age, balance, real balance.
   - **Goal** — one line: to reach `target` in `years` years from `current` at `return`: `monthly_contribution_needed` per month (`annual_contribution_needed` per year); or with `monthly_contribution`: `years_to_reach` years (`months_to_reach` months). Say "already funded" when the flag is set.
   - **Withdrawal** — a table from `table`: Rate · Annual spending · Success probability · Median ending balance · Worst-decile years funded · Deterministic years. Then `requested` on one line when present.
   - **Claiming** — a table from `claiming`: Age · Factor · First-year benefit · Success probability · Median ending balance · Median depletion age. Then the `break_even` ages.
3. **Reading:** two or three sentences, one favourable and one unfavourable, on what moves the result most (return assumption, spending, retirement age), using only the numbers above.
4. **Not modelled:** taxes on withdrawals, account types, Social Security rules and claiming age (unless given as other income), healthcare shocks, variable spending, and sequence risk beyond what the Monte Carlo draws show.

Money to 0 decimal places with thousands separators. Probabilities as percentages to 0 decimal places.

## Rules

- Every number comes from the script.
- State every default you applied.
- Always show a lower-return run when the user has not fixed the return, and show both success probabilities.
- Never present a success probability as a guarantee, or the gap as advice. Describe what closes it (contribution, age, spending) with the script's numbers.
- Label the withdrawal table as a Monte Carlo on stated return and volatility, not the historical result.
- Never state the RMD starting age from memory. Look it up and link the IRS source.
- When the answer turns on the user's own tax or legal situation (Roth conversions, required minimum distributions, early-withdrawal exceptions, beneficiary or estate questions), give the general rules, then say that a tax professional (CPA or enrolled agent) or an attorney can confirm how they apply to them.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
