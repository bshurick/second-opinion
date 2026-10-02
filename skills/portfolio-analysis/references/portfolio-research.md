# Portfolio Construction & Risk Management — Research Corpus

Read this file before answering a portfolio-construction question: start with
"Quick-Reference Decision Rules" and "Key Numbers", then the section for the
topic — e.g. which covariance estimator to use, how
rebalancing frequency and turnover interact, the momentum/contrarian
evidence, benchmark choice, performance-measurement pitfalls, short-selling
constraints, factor exposures, or how competition distorts managers.

## Contents

- Portfolio Weighting Schemes
- Covariance Estimation & Estimation Error
- Rebalancing Frequency & Turnover
- Momentum vs. Contrarian Strategies
- Benchmarking & Relative Performance
- Performance Measurement Pitfalls
- Portfolio Size / Number of Holdings
- Short-Selling Constraints
- Factor Exposure
- Individual Investor Advantages
- Risk Management & Drawdown Control
- Key Numbers
- Quick-Reference Decision Rules
- Glossary
- Concentration and Drift Formulas (fallback reference)
- Sources

## Portfolio Weighting Schemes
### Q: What are the main weighting schemes and how do they rank?
- **Inverse-cap 1/x²**: Overweight smallest stocks. Highest return, highest vol, highest turnover.
- **Inverse-cap 1/x**: Best Sharpe ratio (0.70). Very high return, high vol/turnover.
- **Equal-weight (1/N)**: No estimation error; hard-to-beat baseline. Moderate return/vol, lowest turnover.
- **Optimized min-variance**: Lowest vol but sensitive to estimation error. Turnover high.
- **Combination 1/N + optimizer**: 70-85% EW + 15-30% optimizer. Best practical risk-adjusted when data limited.
- **Cap-weight**: Widely available; underperforms EW/inverse long-run. Low vol, very low turnover.
- **Mega-cap (x²)**: Amplifies cap-weight concentration. Worst returns.

### Q: Equal-weight vs cap-weight?
- EW S&P500: 13.32% CAGR vs cap-weight 10.43% over 1958-2015
- EW avoids estimation error; strong default when history <20yr or assets >~25
- EW higher vol than min-var optimized (18.58% vs ~10-12% for 250 stocks)
- EW has lowest turnover of all schemes
- Rec: EW = safe default. Cap-weight = cheapest. For risk-min, use optimized + good cov estimator.

### Q: Inverse-cap weighting?
- 1/x best Sharpe (0.70) of 8 Tukey-ladder schemes; cap-weight = 0.59
- 1/x² highest raw return (18.00% CAGR) but Sharpe = 0.56 due to 39.5% vol
- Monthly rebalancing required; daily = bankruptcy from costs
- Capacity-constrained: niche/small investors only
- Operates within S&P500 large-cap universe

### Q: When to blend 1/N with optimizer?
- 120mo data, ~25 assets: optimal blend ~80% EW / 20% optimizer
- 240+mo: blend shifts toward ~50/50 or beyond
- Pure Markowitz with <240mo and >handful assets = unreliable
- Sophisticated rules alone (Jorion, MacKinlay-Pastor) produced negative risk-adj returns with limited data
- Rule: start 1/N, nudge toward optimizer, constrain no allocation >few pct pts from EW

## Covariance Estimation & Estimation Error

### Q: Why does naive covariance estimation fail?
- Sample cov has N(N+1)/2 params; 250 stocks = 31K+ entries from ~504 daily obs
- Concentration ratio N/T: when >~0.5, sample cov unreliable
- Beyond ~100 stocks, sample-cov min-var risk INCREASES (11.63% @ 100, 12.16% @ 250)
- Sample cov turnover: 2.09/mo (impractical)

### Q: Which covariance estimators to recommend?
1. **GLASSO-CV2** (10.08% vol, 0.42/mo turnover) — Graphical Lasso cross-validated for min portfolio variance. Overall winner.
2. **POET** (9.74% vol) — Factor-based. Captures known factor structure. Best in sparse-portfolio tests.
3. **Nonlinear shrinkage** (10.20% vol, 0.73/mo turnover) — Adjusts each eigenvalue individually.
4. **Linear shrinkage** (~10.5% vol) — Blends sample toward simple target. Easy to implement. With CV2 tuning, competitive with nonlinear.
5. **Sample covariance** (12.16% vol, 2.09/mo turnover) — Worst. Avoid for >~50 stocks.

Key insight: a simple method with well-tuned parameters (via CV) can match a complex method with default parameters. Optimize tuning for the actual goal — CV1 (forecast error) does NOT minimize portfolio risk; CV2 (portfolio variance) does.

### Q: What is shrinkage?
- Blend noisy sample estimate with simpler, stabler target; trades small bias for large variance reduction
- Always needed when N/T > ~0.2
- Linear targets: identity matrix (all corr=0) or constant-correlation (all corr=avg)
- Nonlinear: individually adjusts each eigenvalue
- No-short-sale constraints act as implicit shrinkage

## Rebalancing Frequency & Turnover

### Q: How often to rebalance?
- Constant-mix rebalancing is mathematically optimal for beating a stochastic benchmark (sell winners, buy losers to restore weights)
- Inverse-cap: monthly optimal. Daily = bankruptcy. Annual loses ~30% returns vs monthly for aggressive strategies
- Mild tilts (sqrt(x), EW): frequency matters little
- Min-var studies used monthly rebalancing with daily estimation data

### Q: How to control turnover?
- LASSO sparsity alone does NOT reduce turnover when tuning param re-optimized each period
- Must add explicit turnover constraint (cap max weight change/position/period). Cuts turnover <50% of unconstrained, no meaningful risk increase
- GLASSO-CV2 naturally produces most stable weights (0.42/mo vs 0.73 nonlinear, 2.09 sample)
- Practical: set threshold (rebalance only when position drifts >2-5 pct pts from target)
- Cap-weight has lowest natural turnover (weights adjust with prices)

## Momentum vs. Contrarian Strategies

### Q: Does momentum work?
- Yes historically. 77% of 155 funds (1975-84) were momentum investors
- Momentum funds: ~2.6%/yr risk-adj excess return vs ~0.1% contrarian
- Effect = buying winners, NOT selling losers (sell-side insignificant)
- Concentrated in large-cap past winners
- Aggressive-growth/growth funds: strongest momentum AND best performance
- Cap-weight indexing is inherently momentum (rising stocks gain weight); inverse-cap is contrarian

### Q: Do contrarian strategies work?
- Gross profits real but source misunderstood
- Weekly: >50% profits from cross-autocovariances (stock A predicts stock B), NOT individual reversal
- Individual stock weekly autocorr: -3.4% (trivial). Index autocorr: +30% (strong). Difference = cross-stock lead-lag
- Lead-lag: large stocks lead small; large-to-small corr = 27.6%, reverse = 2.0%
- Long-horizon (3-5yr): the often-cited 91% winner/loser gap is fragile — driven by penny stocks, calendar-sensitive, subperiod-unstable

### Q: Contrarian pitfalls?
- Loser stocks: avg price $10.49, median $5.00, cheapest quartile $1.04
- $0.125 added to loser purchase price reduces 5yr return by 25 pct pts; cheapest quartile by 86 pct pts
- Dec vs Jun formation: advantage drops 91% to 57%; turn-of-year microstructure, not alpha
- Jun-end risk-adj return: -2.5%/yr
- Median gap: 14% vs 91% mean; extreme right skew from penny recoveries
- 15% losers delist (distress) vs <2% winners
- Weekly: 0.40% one-way cost eliminates ~half of profits

### Q: How do momentum and contrarian interact?
Research shows apparent tension between momentum and contrarian strategies:
- Momentum funds outperform contrarian by ~2.5 pct/yr at stock level
- Weekly contrarian profits real but driven by lead-lag, not overreaction
- Long-horizon contrarian profits largely measurement artifacts
- Yet inverse-cap (contrarian by nature) outperforms cap-weight (momentum) over 58yr
- And constant-mix rebalancing (sell winners, buy losers) is mathematically optimal

Resolution: Momentum works at 3-12mo stock-level horizons. Mean-reversion works at portfolio-weighting level (rebalancing) and possibly very long horizons. Intermediate-horizon contrarian "anomaly" is largely a measurement artifact from penny stocks and microstructure.

## Benchmarking & Relative Performance

### Q: How to choose benchmarks?
- Track portfolio/benchmark value ratio: single sufficient statistic
- Unhedgeable benchmark risk matters: if investments uncorrelated with benchmark, game is structurally harder
- Choose benchmark correlated with investable universe
- Match benchmark to portfolio characteristics (size, style, risk). Small-cap-value vs S&P500 creates false alpha

### Q: Optimal strategy for beating a benchmark?
- Constant-proportion portfolio optimal across all objectives (max prob of beating, min time, max survival)
- Favorability parameter theta determines regime:
  - theta > 0 (favorable): be patient; growth-optimal minimizes time to beat; conservative play maximizes prob of success
  - theta < 0 (unfavorable): bold play maximizes prob of target; growth-optimal maximizes survival; cannot beat in finite expected time
- Growth-optimal (log-optimal / max geometric return) portfolio: central to both regimes

### Q: How does competition distort fund managers?
- Relative-performance pressure causes systematic over-investment in risky assets vs Merton-optimal
- CARA utility: competition ALWAYS increases risk-taking; self-reinforcing arms race
- CRRA utility: conservative mgrs take more risk; very aggressive may go contrarian/short
- Log-utility: immune to competition
- Distortion operates only through common/market risk, not idiosyncratic
- Aggregate: risky assets bid up beyond fundamental level; herd behavior individually rational but systemically fragile

## Performance Measurement Pitfalls

### Q: Biggest pitfalls in evaluating performance?
1. **Means vs medians** — Mean dominated by extreme winners (esp penny stocks). Contrarian gap: 91% mean vs 14% median.
2. **Calendar sensitivity** — Dec vs Jun start changed alpha from +4.3%/yr to -2.5%/yr.
3. **Benchmark model dependence** — Different models give different alphas for same portfolio.
4. **Microstructure bias** — Bid-ask bounce, year-end pricing inflate measured returns for low-priced stocks.
5. **Survivorship bias** — Excluding delisted/bankrupt overstates returns; 15% losers delist.
6. **Time-varying beta** — Stocks selected post-bear have high betas; recovery looks like alpha.
7. **Gross vs net** — Momentum higher turnover; gross outperformance may vanish after costs.
8. **Skewed distributions** — Right-skew makes mean poor summary of typical experience.
9. **Subperiod instability** — Dec-end contrarian lost money first half (-3.4%/yr), gained second (+9.3%/yr).

### Q: How to honestly evaluate performance?
1. Benchmark matched to size/style/risk of holdings
2. Account for ALL costs: commissions, bid-ask, impact, taxes
3. Report medians alongside means
4. Test robustness to measurement window
5. Distinguish risk compensation from alpha
6. Account for survivorship/delisting bias
7. Optimize for what you care about (CV2 not CV1)

## Portfolio Size / Number of Holdings

### Q: How many stocks to hold?
- With sample covariance, diversification benefit reverses beyond ~100 stocks
- Advanced estimators (GLASSO, POET, shrinkage): benefit restored at 200-250
- LASSO sparsity: 40-60% of available stocks = equal or better risk than holding all
- 100-stock universe: 60-85 names capture nearly full diversification
- Selection must be covariance-aware (drop redundant/correlated), not random
- Combination rules strongest with ~25 assets; very large N challenges even blended approaches

### Q: Does sparsity hurt performance?
- No. LASSO maintained or improved out-of-sample risk vs full portfolios
- LASSO halved short positions (~150 to ~45-78 of 319)
- Fewer holdings = lower monitoring, simpler taxes, fewer transactions
- Sparsity alone does NOT reduce turnover; must pair with turnover constraint

## Short-Selling Constraints

### Q: Impact of short-selling constraints?
- No-short-sale = implicit shrinkage; narrows gap between estimation methods
- Long-only can IMPROVE out-of-sample performance by preventing large shorts from imprecise estimates
- LASSO reduces shorts by ~50%
- For individuals: long-only is a feature, not a bug; protects against estimation-error losses
- Some theoretical models allow unlimited shorting/leverage (unrealistic for retail)
- Practical: most individual investors should operate long-only

## Factor Exposure

### Q: What factor exposures matter?
**Size factor:**
- Inverse-cap = systematic small-tilt within S&P500. Returns follow Tukey ladder exactly: more small-tilt = higher return, every subperiod
- Contrarian losers overwhelmingly small/low-priced; apparent alpha may be size-factor compensation
- Lead-lag: large lead small by ~1wk (corr 27.6%); reverse = 2.0%
- Stock price (not mktcap) better predicts microstructure biases

**Momentum factor:**
- 77% of funds are momentum investors; buying winners drives performance
- Momentum outperforms contrarian by ~2.5 pct/yr risk-adj
- Cap-weight indexing = implicit momentum

**Value / mean-reversion factor:**
- Constant-mix rebalancing (sell winners, buy losers) mathematically optimal
- Inverse-cap = implicitly contrarian/value-tilted
- Long-horizon contrarian "value" profits empirically fragile

Note — apparent tension in the size effect: research finds a strong within-S&P500 size effect across all subperiods including post-1980, while other work argues size/contrarian profits are driven by microstructure biases in low-priced stocks. The resolution is that within S&P500 (all large-caps, no penny stocks), there appears to be a relative size effect distinct from the traditional small-cap anomaly.

## Individual Investor Advantages

### Q: Structural advantages over institutions?
- No relative-performance pressure; invest at true personal risk tolerance
- No forced selling in downturns; can hold through drawdowns or buy dips
- Can be patient when crowd is aggressive; hold more cash/bonds without career risk
- Can take other side of crowded trades when professional consensus is extreme
- No herding pressure (institutional herding real but does not independently improve returns)
- Can exploit capacity-constrained strategies (inverse-cap only works for small players)
- Can define explicit win/loss thresholds; prevents vague risk-taking

## Risk Management & Drawdown Control

### Q: Managing risk relative to benchmark?
- Define win threshold (beat S&P500 by X%) and loss floor (never fall Y% behind)
- Favorable (edge): be conservative; patience maximizes prob of target
- Unfavorable (no edge): bold play maximizes prob; growth-optimal maximizes survival
- Focus on geometric (compound) returns, not arithmetic

### Q: Key risk metrics?
- **Annualized volatility** — Primary min-var risk metric
- **Turnover** — Transaction cost proxy; range 0.42 (GLASSO-CV2) to 2.09 (sample) for 250 stocks
- **VaR / CVaR** — 1/x has much more moderate downside than 1/x²
- **Sharpe ratio** — Range 0.56 (1/x²) to 0.70 (1/x) across Tukey schemes
- **Concentration ratio (N/T)** — If >~0.5, sample cov unreliable
- **Wealth-to-benchmark ratio** — Single sufficient statistic for relative performance

### Q: Time-varying volatility/correlations?
- The studies behind this FAQ assume constant covariance; real markets have regime shifts
- DCC-GARCH noted as future research direction, not tested
- Practical: shorter estimation windows in turbulent periods; factor-based estimators (POET) more robust

## Key Numbers

Weighting Performance (S&P500, 1958-2015):
| Scheme | CAGR | Vol | Sharpe | $1 Grew To |
| 1/x² | 18.00% | 39.5% | 0.56 | $1.477B |
| 1/x | 17.53% | ~25% | 0.70 | $1.169B |
| EW | 13.32% | ~20% | ~0.63 | $141.4M |
| Cap-wt | 10.43% | 17.0% | 0.59 | $31.5M |
| x² | 8.69% | ~15% | ~0.55 | $12.5M |

Covariance Estimator Ranking (250 stocks, short-sales allowed):
| Method | Vol | Turnover |
| GLASSO-CV2 | 10.08% | 0.42/mo |
| GLASSO-orig | 10.17% | — |
| Nonlinear shrinkage | 10.20% | 0.73/mo |
| Linear shrinkage | ~10.5% | — |
| Sample cov | 12.16% | 2.09/mo |
| Equal-weight | 18.58% | lowest |

Min-Var Risk by Estimator (319 stocks):
| Method | Vol |
| POET | 9.74% |
| Nonlinear shrinkage | ~10.5% |
| Linear shrinkage | ~11.5% |
| Sample cov | 13.87% |

Momentum vs Contrarian: momentum funds excess 2.6%/yr, contrarian funds excess 0.1%/yr, diff 2.5 pct/yr, 77% of funds are momentum investors.

Contrarian Fragility: mean gap 91%, median gap 14%, $0.125 adj -25 pct pts, Dec alpha +4.3%/yr, Jun alpha -2.5%/yr, cheapest quartile adj -86 pct pts.

Contrarian Decomposition (weekly): cross-autocov >50% of profits, own-autocov <50%, stock autocorr -3.4%, index autocorr +30%, large-to-small lag 27.6%, small-to-large lag 2.0%.

Combination Portfolio (1/N + Optimizer): optimal optimizer weight at 120mo 16-21%, pure Markowitz utility -81%, pure 1/N utility +3.85%, best combo utility +5.79%.

Competition Effect on Risk-Taking: CARA utility always increases risk, CRRA depends on risk-aversion level, log utility zero effect.

## Quick-Reference Decision Rules
- **Limited data (<20yr), many assets** → Anchor to 1/N, blend 80/20 with optimizer
- **Min-var portfolio, >100 stocks** → Use GLASSO-CV2 or POET, NOT sample cov
- **Client wants to beat benchmark** → Constant-mix rebalancing; assess favorability first
- **Client asks about contrarian** → Caution: long-horizon profits fragile; short-horizon mostly lead-lag not overreaction
- **Client asks about momentum** → Evidence supports 3-12mo momentum (buying winners). Factor ETFs cheapest implementation
- **High turnover in optimized portfolio** → Add explicit turnover constraint; use GLASSO for stable weights
- **Client wants inverse-cap/small-tilt** → 1/x best Sharpe (0.70); monthly rebalancing; capacity-constrained
- **Client compares to fund managers** → Individual advantage: no peer pressure, no forced selling, can be patient
- **Portfolio >100 stocks, no advanced estimator** → Cap holdings ~60-85 via covariance-aware selection (LASSO)
- **Client uses raw historical correlations** → Warn: sample cov unreliable when N/T > 0.5; minimum use linear shrinkage
- **Evaluating strategy track record** → Check median vs mean, calendar sensitivity, benchmark match, costs, survivorship
- **Client cannot short sell** → Long-only is protective, not limiting; improves out-of-sample performance

## Glossary
- **1/N**: Equal-weight; equal $ per asset; no estimation
- **CAGR**: Compound annual growth rate
- **CARA**: Constant absolute risk aversion (exponential utility)
- **N/T**: Concentration ratio; assets / observations; >0.5 = unreliable sample cov
- **Constant-mix**: Fixed % weights via regular rebalancing
- **CRRA**: Constant relative risk aversion (power utility)
- **Cross-autocov**: Corr between stock A past return and stock B future return
- **CV**: Cross-validation; data-driven tuning param selection
- **CV1**: CV minimizing forecast error
- **CV2**: CV minimizing out-of-sample portfolio variance
- **Theta**: Favorability param; net edge over benchmark
- **GLASSO**: Graphical Lasso; sparse precision-matrix estimator
- **Growth-optimal**: Max expected geometric growth rate portfolio
- **Alpha**: Risk-adjusted excess return above benchmark model
- **LASSO**: Forces some weights to zero (sparsity)
- **Lead-lag**: Large-stock returns predict subsequent small-stock returns
- **Merton**: Classic optimal allocation ignoring competition
- **Mean-field**: Game where agents interact with population average
- **Min-var**: Lowest possible variance portfolio; ignores expected returns
- **POET**: Factor-based cov estimator (PCA + thresholding)
- **Precision matrix**: Inverse covariance; direct portfolio optimization input
- **Sharpe**: (Return - Rf) / StdDev
- **Shrinkage**: Blend noisy estimate toward stabler target
- **Turnover**: Fraction of portfolio traded per period; cost proxy
- **Tukey ladder**: Power transformations (1/x²..x..x²) applied to weights

## Concentration and Drift Formulas (fallback reference)
### Q: How are the allocation script's metrics defined?
These are the formulas `scripts/allocation.py` implements — use them only as
the hand-computation fallback when the script cannot be run:
- **Weight**: w_i = position_value_i / total_value (total includes cash; cash
  is its own "CASH" position). Sector weights use the positions-only total
  (cash excluded from the denominator).
- **HHI (Herfindahl–Hirschman index)**: hhi = Σ w_i² over all position
  weights including CASH. Interpretation on the value rounded to 4dp:
  < 0.10 diversified; 0.10–0.18 (inclusive) moderate; > 0.18 concentrated.
- **Effective-N (inverse HHI)**: 1/hhi — the number of equally sized
  positions with the same concentration. Same bands as hhi, read as counts:
  > 10 diversified; 5.6–10 moderate; < 5.6 concentrated.
- **Top-5 concentration**: sum of the 5 largest position weights.
- **Drift**: sector_weight − target_weight per targeted sector (signed; a
  targeted sector absent from the portfolio drifts by −target).

## Sources

Every figure in this file comes from one of these nine papers; the text is a
paraphrase written for this skill, not the papers' prose.

- Browne, S. (1999). "Beating a moving target: Optimal portfolio strategies for outperforming a stochastic benchmark." *Finance and Stochastics*, 3, 275-294. Benchmarking, favorability regimes, growth-optimal strategy.
- Husmann, S., Shivarova, A. & Steinert, R. (2020). "Cross-validated covariance estimators for high-dimensional minimum-variance portfolios." *Financial Markets and Portfolio Management*. arXiv:1910.13960. GLASSO-CV2, CV1 vs CV2, the 250-stock estimator table.
- Husmann, S., Shivarova, A. & Steinert, R. (2019). "Sparsity and Stability for Minimum-Variance Portfolios." arXiv:1910.11840. LASSO sparsity, turnover constraints, POET, the 319-stock table.
- Tu, J. & Zhou, G. (2011). "Markowitz meets Talmud: A combination of sophisticated and naive diversification strategies." *Journal of Financial Economics*, 99(1), 204-215. Blending 1/N with an optimizer.
- Ernst, P.A., Thompson, J.R. & Miao, Y. (2017). "Tukey's transformational ladder for portfolio management." *Financial Markets and Portfolio Management*, 31, 317-355. arXiv:1603.06050. Weighting schemes and the 1958-2015 S&P 500 table.
- Grinblatt, M., Titman, S. & Wermers, R. (1995). "Momentum Investment Strategies, Portfolio Performance, and Herding: A Study of Mutual Fund Behavior." *American Economic Review*, 85(5), 1088-1105. Momentum vs contrarian funds, herding.
- Lo, A.W. & MacKinlay, A.C. (1990). "When Are Contrarian Profits Due to Stock Market Overreaction?" *Review of Financial Studies*, 3(2), 175-205. Weekly contrarian decomposition, lead-lag.
- Ball, R., Kothari, S.P. & Shanken, J. (1995). "Problems in measuring portfolio performance: An application to contrarian investment strategies." *Journal of Financial Economics*, 38(1), 79-107. Long-horizon contrarian fragility, measurement pitfalls.
- Lacker, D. & Zariphopoulou, T. (2019). "Mean field and n-agent games for optimal investment under relative performance criteria." *Mathematical Finance*, 29(4), 1003-1038. arXiv:1703.07685. Competition and risk-taking.
