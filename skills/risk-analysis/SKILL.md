---
name: risk-analysis
description: Measures risk and stress-tests connected holdings, covering volatility, beta, correlation, drawdown, VaR, risk contribution, crash replays (2008, 2018, 2020, 2022) and what-if shocks. Use when the user asks "how risky is my portfolio" or "what if X drops 30%".
---
Measures the risk of the connected accounts from price history and stresses it against named episodes and hypothetical shocks. Numbers come from the script; the reply describes exposure and the limits of the estimates. Changing the portfolio belongs to another skill.

## Background

**What the script does**

- **Fetch.** `stress.py` fetches holdings (one call per endpoint per account) and one batched Yahoo download of N years of closes, then runs `risk.py`.
- **Defaults.** 3 years of history, SPY benchmark, built-in scenarios.
- **Method.** Aligned simple returns, annualized sample statistics, nearest-rank VaR, constant-weight portfolio path, risk contributions, per-symbol replay vs beta-scaled scenarios. The detail is in `risk.py`'s docstring.
- **Returns are decimals.** `--shock NVDA=-0.3` means a 30% drop.

**Holdings that need special handling**

- **Cash-like holdings.** A money-market fund or cash placeholder (SPAXX, MVRXX, FDRXX, FCASH, or a name like "Government Money Market") counts as cash, not as an unpriced position. `sources.cash_like` lists them.
- **Institutional share classes.** A class Yahoo has no history for (a 401(k)'s "VANG INST 500 IDX TR") borrows its public twin's price history: VOO, VXUS, BND or VTI, matched by name, in one extra batched call.
  - `sources.proxies` maps each such symbol to its proxy, and a `PROXY_HISTORY` flag names them.
  - A failed proxy fetch leaves the class unpriced and adds `PROXY_HISTORY_UNAVAILABLE`.
  - Liquidity is null for a proxied class.

**Tracking error**

- Tracking error is measured per holding against its own category index, in `positions[].tracking_benchmark`:

  | Holding | Reference |
  |---|---|
  | Bonds | BND |
  | International equity | VXUS |
  | US equity | the benchmark |
  | Cash, gold and other holdings | null, not a misleading figure against SPY |

- The bucket is taken from the cached Yahoo description the snapshot uses. Any reference not already downloaded is fetched in the same extra batched call.
- `sources.tracking_references` maps each symbol to its reference.
- When buckets cannot be read, a `TRACKING_REFERENCES_UNAVAILABLE` flag says every position tracks the benchmark instead.
- Beta, correlation, capture, the portfolio's own tracking error and the scenarios stay against the one benchmark.

**Scenarios**

- Scenarios replay symbol by symbol. A position whose own history spans the window is replayed from its prices. Every other covered position is beta-scaled against the benchmark's own replayed return.
- A scenario's `mode` is `replay`, `mixed` or `beta_scaled`. Its `replayed` and `beta_scaled` lists say which symbols were which.
- Built-in scenarios use S&P 500 peak-to-trough closes:

  | Episode | Window | S&P 500 |
  |---|---|---|
  | 2008 crisis | 2007-10-09 to 2009-03-09 | -56.8% |
  | 2018 Q4 selloff | 2018-09-20 to 2018-12-24 | -19.8% |
  | 2020 COVID crash | 2020-02-19 to 2020-03-23 | -33.9% |
  | 2022 rate shock | 2022-01-03 to 2022-10-12 | -25.4% |

**Limits of the estimates**

- Volatility, beta and correlation are estimated from the window given. They rise in crises (correlations go to one), so beta-scaled scenario losses are a floor, not a ceiling.
- Historical VaR at 95% says the 1-day loss exceeded on about 1 day in 20 over the window. CVaR is the average of those days. Neither captures gaps or liquidity.
- Max drawdown is path-dependent. The portfolio figure assumes today's weights held throughout the window (daily rebalanced), which differs from what the account actually experienced.
- A diversification ratio of 1 means the positions move as one; higher is more diversification benefit.
- Risk contribution shows which positions drive variance, which differs from their weight when volatilities differ.

**The page**

`render.py` turns a saved `stress.py` result into one self-contained HTML page for the Artifact tool. The page carries the positions, risk contributions, correlation, scenarios, what-if, factor and liquidity sections:

- the SHORT_HISTORY / MISSING_PRICES warnings first
- stat tiles for volatility, beta, max drawdown, VaR, Sharpe and diversification ratio
- a sortable positions table and risk-contribution bars
- the correlation matrix as a diverging heatmap
- scenario losses as bars in dollars and percent, labelled replay, mixed or beta-scaled, with a click-through to each scenario's position returns, each marked replayed or beta-scaled
- what-if shocks, and factor betas and liquidity when present
- flags; light and dark themes; no external scripts

**Other skills**

Changing the portfolio in response belongs to the rebalancing or portfolio-analysis skills.

## Scripts

Run with the Bash tool. All three scripts print JSON.

```bash
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/risk-analysis/scripts/stress.py" [--account ID ...] [--years N] [--benchmark SPY] [--shock SYMBOL=RETURN ...] [--scenario NAME=BENCHMARK_RETURN ...] [--no-builtin] [--risk-free R] [--as-of YYYY-MM-DD] [--partial]
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/risk-analysis/scripts/risk.py" < input.json
"${SNAPTRADE_PY:-python3}" "${CLAUDE_PLUGIN_ROOT}/skills/risk-analysis/scripts/render.py" --in risk.json --out page.html
```

| Script | What it does |
|---|---|
| `stress.py` | Fetches holdings and price history, then runs `risk.py`. |
| `risk.py` | Pure math on holdings and prices you already have. |
| `render.py` | Interactive page from a `stress.py` result. Prints `{"out", "title", "positions", "scenarios", "flags"}`. |

| Flag | Effect |
|---|---|
| `--account ID` | Restrict to the named account or accounts. |
| `--years N` | Years of closes to download. Default 3. |
| `--benchmark SPY` | The benchmark symbol. Default SPY. |
| `--shock SYMBOL=RETURN` | A per-symbol what-if. Fills `what_if`. |
| `--scenario NAME=BENCHMARK_RETURN` | A custom beta-scaled market move. |
| `--no-builtin` | Leave out the four built-in scenarios. |
| `--risk-free R` | Risk-free rate for Sharpe. Default 0. |
| `--as-of YYYY-MM-DD` | Pins the as-of date. Default today. |
| `--partial` | Run without E*Trade when its login is pending. |

| Exit code | Meaning | What to do |
|---|---|---|
| 2 | Bad flags or no priced positions, or (`render.py`) the input is not a risk result | Show `error`. |
| 4 | Credentials missing | Show the `hint`. |
| 4, code `ETRADE_REAUTH` | An E*Trade login is needed | Follow the session's broker-login rule: show the `url`, get the verifier code, run the connect skill's `etrade-login.py --verifier CODE`, rerun once. `--partial` runs without E*Trade. |
| 5 | SnapTrade or Yahoo error | Show the error. |
| 6 | Python dependencies missing | Show the error. |

## Steps

1. Pick the flags for `stress.py`:

   | The request | Flags |
   |---|---|
   | "How risky is my portfolio" | none (the defaults) |
   | "What if X drops N%" | `--shock SYMBOL=RETURN`, for example `--shock X=-0.3` |
   | A hypothetical market move | `--scenario NAME=RETURN`, for example `--scenario crash=-0.3` |
   | The user asks about 2020 | `--years 5` or more, so the episode replays instead of scaling |
   | The user names an account | `--account ID` |

2. Run `stress.py` once, writing the output to a file: `> DIR/risk-analysis.json`. DIR is the session scratchpad.
3. If the run exits non-zero, follow the exit code table and stop.
4. If the Artifact tool is available in the session, deliver the page:
   1. Run `render.py --in DIR/risk-analysis.json --out DIR/risk-analysis.html`.
   2. Publish the HTML with the Artifact tool: icon shield, description "Portfolio risk and stress test as of DATE".
   3. On later runs republish the same file path, so the link stays stable.
   4. Reply with the page reply format below.
5. If the Artifact tool is not available (a headless or non-interactive host), reply with the markdown fallback format below instead.
6. In either reply, name which scenarios replayed and which were beta-scaled. The difference matters.
7. If the user wants to change the portfolio in response, finish the risk report first, then hand off to the skill named in Background.

## Reply format

### Page reply (the default, when the page was published)

In this order, then stop:

1. When `flags` includes SHORT_HISTORY or MISSING_PRICES, those messages first.
2. The artifact link on its own line.
3. One line: Volatility `portfolio.volatility` · beta `portfolio.beta` · max drawdown `portfolio.max_drawdown` · 1-day VaR 95% `portfolio.var_95` · worst scenario `name` `portfolio_loss` (`mode`)
4. **Flags** — one bullet per `flags[].message`, or "None".
5. **Reading:** as described under Reading below.

Do not repeat the sections the page carries. If the user asks for a number the page shows, read it from the script's JSON.

### Markdown fallback (only when the Artifact tool is unavailable)

Render in this order.

When `flags` includes SHORT_HISTORY or MISSING_PRICES, lead with those messages, before the headline numbers. The reader needs to know the statistics are noisy or partial before seeing them.

**Risk** — `portfolio.total_value` (cash `portfolio.cash_weight`), `portfolio.observations` trading days `portfolio.start` to `portfolio.end`, benchmark `portfolio.benchmark`, coverage `portfolio.coverage`

One line from `portfolio`: volatility `volatility` · beta `beta` · correlation to benchmark `correlation_to_benchmark` · tracking error `tracking_error` · Sharpe `sharpe` · max drawdown `max_drawdown` · 1-day VaR 95% `var_95` (CVaR `cvar_95`, parametric `parametric_var_95`) · diversification ratio `diversification_ratio` · avg pairwise correlation `avg_pairwise_correlation`

1. **Positions** — table from `positions`: Symbol · Weight · Volatility · Beta · Max drawdown · VaR 95% · Tracking error (with its `tracking_benchmark`, "—" when null). Then `risk_contributions` as Symbol · Share of portfolio variance, largest first.
2. **Correlation** — the `correlation.matrix` as a table when 8 symbols or fewer, otherwise the strongest `pairs`. Then `concentration` on one line (HHI, interpretation, largest position, top-5).
3. **Scenarios** — table from `scenarios`: Scenario · Window · Mode · Benchmark return · Portfolio return · Loss.
   - Mode is replay, mixed or beta-scaled. For mixed, name the `beta_scaled` symbols.
   - For the largest-loss scenario, name its top 3 `risk_contributions` (by `share`) and state each one's return from that scenario's `positions` map.
   - Note any `note`.
4. **What if** — only when `what_if` is present: the shocks and the resulting loss.
5. **Flags** — one bullet per `flags[].message`, or "None".

Then **Reading:** as described under Reading below.

### Reading

Two or three sentences:

- one on what the numbers say the portfolio is exposed to;
- one on what they cannot show: a replay is one path, and beta-scaled losses assume betas hold in a crash, which they usually understate.

### Number formats

| Value | Format |
|---|---|
| Money | 0 dp with thousands separators |
| Ratios and returns | percentages to 1 dp |
| Beta and Sharpe | 2 dp |

## Rules

- Every number comes from the script.
- Run `stress.py` once per answer. The one rerun after an E*Trade login is the only exception.
- Publish the page or write the markdown fallback, never both.
- No advice in the Reading or anywhere else in the reply.
- Never provide buy, sell, or hold recommendations. If a user asks whether they should buy, sell, or hold a security, state clearly that you cannot make investment recommendations, then present relevant analysis they can use to make their own decision.
- Never use the words "recommend", "advise", "should", or "suggest" when referring to financial actions. Use "the data shows", "analysis indicates", "one factor to consider" instead.
- Always present both bull and bear cases when analyzing a security or market condition.
- Always surface key risks alongside opportunities.
- When the answer is a figure the user could act on (a projection, valuation, trade preview, tax estimate, or allocation), say once that it is general information at the stated assumptions, not financial, tax, or legal advice.
- Only explain financial concepts when the user asks for an explanation.
