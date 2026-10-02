---
name: options
description: Analyzes options on a specific security — chain, implied volatility, expected move, term structure, greeks, payoff and breakevens for calls, puts, spreads and straddles, max pain, assignment risk. Use when the user asks about calls, puts, strikes or premiums.
---
Analyzes listed options: what the chain is pricing, what a contract's greeks are, and what a strategy makes or loses at expiry. Numbers come from the scripts; the reply describes them and their risks. Options orders are not placed here.

## Background

- **Data source.** `chain.py` fetches one expiry from Yahoo and summarizes it: ATM IV, expected move, put/call ratios, max pain, skew, a strike table with deltas, HV and IV/HV.
- **Default expiry.** Without `--expiry`, the first expiry at least a week out is used. The JSON lists `expiries` so you can offer others.
- **Rates.** The risk-free rate is the ^IRX 13-week T-bill yield. The dividend yield is Yahoo's stated profile yield. Both appear under `sources` and degrade to defaults when Yahoo cannot fill them.
- **Events.** `next_earnings` and `next_ex_dividend` are reported with whether each falls inside the expiry (`earnings_in_expiry`, `ex_dividend_in_expiry`).
- **Term structure.** `--term-structure` summarizes about six expiries spread front to back instead: per-expiry ATM IV, ATM straddle and put skew, with IV and skew slopes between front and back.
- **Shared math.** `options.py` is the shared math. Its docstring is the contract for every action, including the leg format for payoff diagrams.
- **Model limits.** Black-Scholes assumes European exercise, lognormal prices, constant volatility and rates. American equity options can be exercised early (mostly deep ITM puts, and calls just before an ex-dividend date). Use its greeks as a map, not the territory.
- **Assignment screen.** `assignment_candidates` flags deep-ITM contracts where early exercise is plausible. It is a rule of thumb, not a boundary solve: |delta| ≥ 0.90 plus a dividend (calls) or strike interest (puts) bigger than the remaining time value.
- **Expected move.** Spot × IV × √(days/365), the one-standard-deviation range the market is pricing. The ATM straddle × 0.85 is the trader rule of thumb for the same thing. About a third of the time the stock ends outside the 1σ range.
- **IV/HV.** Above 1.2 means options are priced richer than recent realized movement; below 0.8 cheaper. Neither is a signal on its own: earnings, events and index volatility change both.
- **Max pain.** The expiry price minimizing option holders' intrinsic value. Evidence for pinning near it is weak and mostly affects the last day. Mention it as context, never as a target.
- **Probabilities.** Probability ITM and probability of profit are risk-neutral lognormal estimates. They ignore drift and fat tails and are optimistic for far-OTM short options.
- **The page.** `render.py` builds one self-contained HTML page for the Artifact tool. Light and dark themes; no external scripts. It holds:
  - stat tiles and the expected-move cone as a band
  - implied versus realized volatility
  - the chain as a sortable table with the ATM row highlighted, and the term-structure table
  - the contract's greeks and the strategy's payoff diagram with breakevens marked
  - the assignment candidates and the risk notes
- **Curves the page draws itself.** `render.py`'s docstring names the two curves drawn from the scripts' numbers: the cone between today and expiry, and a single contract's payoff when only `greeks` ran.
- **Other skills.** The plugin trades equities only, through portfolio-analysis. Options orders are not implemented.

## Scripts

Run with the Bash tool.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/options/scripts/chain.py" <symbol> [--expiry YYYY-MM-DD] [--around N] [--no-history] [--term-structure] [--as-of YYYY-MM-DD]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/options/scripts/options.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/options/scripts/render.py" --in options.json --out page.html
```

| Script | What it does |
|---|---|
| `chain.py` | Chain summary for one expiry. `--around N` sets the strikes shown each side of ATM (default 10). `--no-history` skips HV. `--term-structure` switches to the per-expiry summary. |
| `options.py` | Pure math on JSON from stdin. Actions: `greeks`, `payoff`, `expected_move`, `chain`, `hv`, `term_structure`. |
| `render.py` | Turns the collected results into the interactive page. Prints `{"out", "title", "symbol", "strikes", "payoff"}`. |

`render.py` input is either a bare `chain.py` result or this object. Every key beyond `chain` (or `term_structure`) is optional:

```json
{"chain": <chain.py result>, "term_structure": <chain.py --term-structure result>, "greeks": <options.py greeks result>, "payoff": <options.py payoff result>, "legs": [...]}
```

All scripts print JSON.

| Exit code | Meaning | What to show |
|---|---|---|
| 2 | Bad input or unknown expiry | `error`, which lists available expiries |
| 2 from `render.py` | The input is not a chain result | `error` |
| 5 | Yahoo error | the error |
| 6 | Python dependencies missing | the error, and say the setup skill repairs it |

## Steps

1. If the user asks to place an options trade, say options orders cannot be placed through this plugin and stop. Stock orders belong to portfolio-analysis.
2. Run `chain.py <symbol>` once. Add `--expiry` when the user names one.
3. If the user asks how IV, skew or the straddle varies by expiry, run `chain.py <symbol> --term-structure` instead.
4. If the user names a contract, run `options.py` with action `greeks`:
   - `spot` from the chain, the contract's strike and expiry.
   - Its mid price as `price`, so IV is solved from the market. Or its `implied_volatility` as `iv`.
   - `ex_dividend_date` from the chain output when one falls inside the expiry, so the `early_assignment` screen is fed.
5. If the user describes a strategy (covered call, cash-secured put, spread, straddle, strangle, condor), build the `legs` from chain mids and run action `payoff`. Pass the chain's `atm_iv` and `days` so probability of profit is included.
6. Write the results to one file, `DIR/options.json`, with only the keys that ran. DIR is the session scratchpad.
7. Run `render.py --in DIR/options.json --out DIR/options.html`.
8. Publish the HTML with the Artifact tool: icon chart, description "Options: SYMBOL, expiry DATE". Republish the same file path on later runs so the link stays stable.
9. Reply with the published-page format below.
10. If the Artifact tool is not available in the session (a headless or non-interactive host), skip steps 6 to 9 and reply with the markdown fallback instead.

## Reply format

Every number comes from the scripts.

**When the page was published (the default):**

1. The artifact link on its own line.
2. One line: **Options: SYMBOL** spot `spot` · expiry `expiry` (`days` days) · ATM IV `atm_iv` · expected move ±`expected_move_1sd` (`expected_move_pct`) · IV/HV `iv_hv_ratio`
3. When a contract or strategy was analyzed, one line with its price or net premium, breakevens and max profit / max loss (or prob profit).
4. "Reading:" as in fallback section 3, one bull and one bear sentence.
5. The **Risks** bullets as in fallback section 4. Then stop.

The page carries the chain, term structure, greeks, payoff diagram and assignment candidates, so do not repeat them in the reply. If the user asks for a number the page shows, read it from the scripts' JSON.

**Markdown fallback (only when the Artifact tool is unavailable):** render in this order.

**Options: SYMBOL** — spot `spot`, expiry `expiry` (`days` days), ATM `atm_strike` at IV `atm_iv`

One line: expected move ±`expected_move_1sd` (`expected_move_pct`) by expiry · HV30 `hv_30` / HV90 `hv_90` · IV/HV `iv_hv_ratio` · put/call OI `put_call_oi_ratio` · max pain `max_pain` · events inside the expiry: `earnings_in_expiry` / `ex_dividend_in_expiry` with dates from `next_earnings` / `next_ex_dividend`

1. **Chain** — table from `strikes` (ATM row marked): Strike · Call bid/ask · Call IV · Call Δ · Call OI · Put bid/ask · Put IV · Put Δ · Put OI. One line for `skew` and `top_open_interest`.
   - With `--term-structure`, this section is instead a table of `rows`: Expiry · Days · ATM IV · ATM straddle · straddle move % · put skew, and one line for `iv_slope_30d` / `iv_term_shape` / `skew_slope_30d`.
2. **Contract or strategy** — only when the user named one.
   - Single contract: the `greeks` output as Price · IV · Δ · Γ · Θ/day · Vega · Prob ITM · Breakeven, plus `early_assignment` when flagged.
   - Strategy: the `payoff` output as Strategy · Net premium · Collateral · Breakevens · Max profit · Max loss · Prob profit, then a 7-row slice of `grid` around spot.
3. **Reading** — two or three sentences labelled "Reading:", one bull and one bear, using only the numbers above: what the market-implied move is versus realized, where open interest sits, what the structure needs to happen to profit and what it loses.
4. **Risks** — one bullet for each that applies:
   - full premium loss
   - assignment on short options
   - unlimited loss on uncovered calls
   - early assignment on deep-ITM contracts flagged by `assignment_candidates` (call ex-dividend capture, put strike interest)
   - wide spreads (`spread_pct` above 10%)
   - low open interest
   - earnings inside the expiry

**Number formats**

- Prices to 2 decimal places.
- IV, deltas and probabilities as percentages to 1 decimal place.
- Theta as dollars per day per contract (×100).
- Null shows as "—".

## Rules

- Never run `chain.py` more than twice in one answer.
- The Risks section is mandatory whenever a strategy or contract is shown, in either reply form.
- Publish the page or use the markdown fallback, never both.
- Options orders cannot be placed through this plugin. If asked to trade, say so and stop.
- No advice; describe what the numbers show.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
