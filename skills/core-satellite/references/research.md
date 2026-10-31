# Research behind the core/satellite numbers

Where the default ceiling, the proposed size, the equal-weight default and the valuation tilt come from. Each item is graded: **strong** means peer-reviewed or mechanical (tax law, arithmetic); **practitioner rule of thumb** means common practice with no research-based optimum behind it. Verify current tax figures before quoting them.

## Contents
- Satellite size and the default ceiling
- Diversification and the effective number of picks
- Weighting picks within the satellite
- Retail trading costs
- Employer stock
- The constants in weights.py
- Formulas
- Sources

## Satellite size and the default ceiling

**Grade: practitioner rule of thumb.**

- No study finds an optimal satellite size. Core/satellite practice puts the satellite at 10–30% of the portfolio, and 80/20 is the split cited most often.
- The default ceiling of 20% comes from that practice range. It is a starting point the person decides on and saves; it is a limit, not a target.
- A more principled measure is a tracking-error budget: how far, in a typical year, the whole portfolio can drift from the core because of the picks. Practitioners use about 1–2% a year at the portfolio level.
- The estimate is `TE ≈ w_sat × σ_idio / sqrt(N_eff)`, with σ_idio, the stock-specific volatility of a typical single stock, about 30% a year.
- Worked example: a 20% satellite of 15 equal-weight picks gives 0.20 × 0.30 / sqrt(15) ≈ 1.5%.
- The proposed size inverts this: the satellite weight at which the estimate equals the 1.5% budget at today's N_eff, never above the ceiling.
- When 25% or more of the satellite sits in technology or the employer's sector, the proposed size is cut to 75%. A person's pay already depends on the employer's sector, so picks in it add to a risk they carry anyway. The 25% line and the 75% cut are rules of thumb.

## Diversification and the effective number of picks

**Grade: strong.**

- Single-stock returns are highly skewed. Bessembinder (2018) found that 4.3% of US stocks accounted for all the net wealth the stock market created above Treasury bills from 1926 to 2016; most single stocks returned less than one-month Treasury bills over their lifetimes.
- A consequence: a small set of stocks has a median outcome below the index, even when the person picking them has no negative skill, because the few big winners are easy to miss.
- N_eff = 1 / Σ w_i², with w_i each pick's share of the satellite. Ten picks with one holding half the money count as fewer than ten.
- `LOW_N_EFF` fires below 15. At 15 picks a 20% satellite's tracking-error estimate comes to about the 1.5% budget. The line is a rule of thumb built on the strong skewness result.

## Weighting picks within the satellite

**Grade: strong.**

- DeMiguel, Garlappi and Uppal (2009) compared 14 optimised portfolio rules with simple 1/N weighting on seven datasets. None beat 1/N consistently out of sample, because estimation error in the inputs swamps the gain from optimising.
- Expected-return estimates are the weakest input. Grinold's fundamental law of active management and Grinold and Kahn's book put a realistic information coefficient (correlation of forecast and outcome) at 0.05–0.10, so a forecast carries only a small share of the outcome.
- Kelly (1956) sizing shows the asymmetry: betting more than the true edge lowers long-run growth faster than betting less, so an estimated edge is shrunk before it is used.
- The person's own testing found that much of an earlier evaluation model's apparent edge came from look-ahead in filing dates. That is a local finding, not a published one, and it points the same way.
- What the skill does with this:
  - Four strategies: `equal`, `market_cap`, `valuation` and `size`. `equal` is the default, and adding money only buys. Market cap is a person's strategy choice, not a research finding.
  - Valuation weighting is opt-in, uses deep valuations only, and tilts by a shrunk score on an absolute scale (see Formulas). Two picks with nearly equal expected returns get nearly equal shares; a wide gap at full confidence tilts clearly. New money follows the tilt, and only a rebalance on request trims.
  - Confidence halves every 182 days and is 0 when a recheck is due, so a stale or pre-filing valuation gets no tilt. A pick with no next earnings date is due after 120 days, and one with no known age is due at once.
  - The 5% cap limits how high a pick's target can be.
  - A pick priced more than 5% above its central value gets a smaller share, by its confidence, and is not sold when adding money. A light valuation takes a neutral share unless the person includes light valuations, and stays flagged.
- The 182-day half-life, the shrink factor 0.5 and the tilt strength 0.5 are builder's choices inside the range the research describes (shrink factors of about 0.25–0.5); they are not fitted values.

## Retail trading costs

**Grade: strong.**

- Barber and Odean (2000) studied 66,465 households at a discount broker from 1991 to 1996. The households that traded most earned 11.4% a year against 17.9% for the market; the gap came mostly from turnover.
- This favours buy-only defaults: adding money only buys, and core sales fund picks only on request (`grow`, `new-pick`, a plan with `core` funding).

## Employer stock

**Grade: strong mechanics, practitioner thresholds.**

- RSUs are taxed as ordinary income when they vest, and the cost basis is the market value at vest (IRC §83). Selling at vest therefore adds almost no further tax. Keeping vested shares is economically the same as buying them with cash that day.
- Under an IRC §423 employee stock purchase plan, a 15% discount is a 17.6% return on cost at purchase (1 / 0.85 − 1). Holding the shares to a qualifying disposition changes the tax treatment, against one to two years of single-stock risk.
- Federal supplemental-wage withholding is a flat 22% up to $1 million (IRS Publication 15). A person in a higher bracket owes more at filing. Verify the current rate.
- Employer stock above about 10% of net worth is the common warning line (`EMPLOYER_CONCENTRATION`). It is a practitioner rule of thumb.
- Pay and the job already depend on the employer, so employer stock is kept out of the satellite, its ceiling, N_eff and tracking error, and never receives satellite money.

## The constants in weights.py

| Constant | Value | Meaning | Grade |
|---|---|---|---|
| `DEFAULT_CEILING` | 0.20 | Default satellite ceiling, fraction of total value | practitioner rule of thumb |
| `SIGMA_IDIO` | 0.30 | Stock-specific annual volatility of a typical single stock | practitioner rule of thumb |
| `TE_BUDGET` | 0.015 | Tracking-error budget at the portfolio level, per year | practitioner rule of thumb |
| `MIN_N_EFF` | 15 | N_eff below which `LOW_N_EFF` fires | rule of thumb on a strong result |
| `SECTOR_HEAVY` | 0.25 | Share of the satellite in technology or the employer's sector that triggers `SECTOR_HEAVY` | practitioner rule of thumb |
| `SECTOR_HAIRCUT` | 0.75 | Factor applied to the proposed size when `SECTOR_HEAVY` | builder's choice |
| `PICK_CAP` | 0.05 | Highest target for one pick, fraction of total value; the cap limits how high a target can be | practitioner rule of thumb |
| `MARKET_RETURN` | 0.07 | Market return the expected return is measured against, per year | practitioner rule of thumb |
| `SHRINK_K` | 0.5 | Shrink factor on the excess expected return | builder's choice in the researched range |
| `TILT_LAMBDA` | 0.5 | Tilt strength per `TILT_SCALE` of score | builder's choice |
| `TILT_SCALE` | 0.10 | Score that moves a pick's raw weight by `TILT_LAMBDA` (0.10 = 10 points of shrunk excess return) | builder's choice |
| `TRIM_MIN_GAP` | 0.05 | How far price must be above central value before a pick counts as overvalued | builder's choice |
| `HALF_LIFE_DAYS` | 182 | Days for valuation confidence to halve | builder's choice |

The employer line (10% of total value) lives in `sleeves.py`, not `weights.py`.

## Formulas

- N_eff = 1 / Σ (v_i / V)², over per-symbol satellite values v_i, V their sum.
- Tracking error = w_sat × `SIGMA_IDIO` / sqrt(N_eff), with w_sat the satellite's share of total value.
- Proposed size = min(ceiling, `TE_BUDGET` × sqrt(N_eff) / `SIGMA_IDIO`), times `SECTOR_HAIRCUT` when `SECTOR_HEAVY`.
- Confidence = 0.5 ^ (age_days / `HALF_LIFE_DAYS`), or 0 when a recheck is due.
- Score a_i = `SHRINK_K` × confidence_i × (expected_return_i − `MARKET_RETURN`), on an absolute scale (not standardised across picks).
- Tilted weight of an eligible pick ∝ value_i × max(0, 1 + `TILT_LAMBDA` × a_i / `TILT_SCALE`), scaled to the target total, with no target above `PICK_CAP` × total. Money a capped pick cannot take goes to the other picks by their shares.
- An eligible pick with confidence above 0 priced above central value × (1 + `TRIM_MIN_GAP`) gets a share scaled by (1 − confidence_i × (1 − central_value / price)).
- A light pick has no scenario returns, so its expected return is the annual return if the price converges to the light base fair value in 3 years: (base / price)^(1/3) − 1. The 3-year horizon is a builder's choice.
- A new pick is sized at the median current pick value, capped at `PICK_CAP` × total.

## Sources

| Item | Year | Source |
|---|---|---|
| Single-stock skewness | 2018 | Bessembinder, H. "Do Stocks Outperform Treasury Bills?" *Journal of Financial Economics* 129(3). https://doi.org/10.1016/j.jfineco.2018.06.004 |
| 1/N out of sample | 2009 | DeMiguel, V., Garlappi, L. and Uppal, R. "Optimal Versus Naive Diversification: How Inefficient is the 1/N Portfolio Strategy?" *Review of Financial Studies* 22(5). https://doi.org/10.1093/rfs/hhm075 |
| Information coefficient | 1989 | Grinold, R. "The Fundamental Law of Active Management." *Journal of Portfolio Management* 15(3). https://doi.org/10.3905/jpm.1989.409211 |
| Information coefficient | 2000 | Grinold, R. and Kahn, R. *Active Portfolio Management*, 2nd ed. McGraw-Hill. https://search.worldcat.org/search?q=bn:0070248826 |
| Over-betting an edge | 1956 | Kelly, J. L. "A New Interpretation of Information Rate." *Bell System Technical Journal* 35(4). https://doi.org/10.1002/j.1538-7305.1956.tb03809.x |
| Retail turnover | 2000 | Barber, B. and Odean, T. "Trading Is Hazardous to Your Wealth." *Journal of Finance* 55(2). https://doi.org/10.1111/0022-1082.00226 |
| RSU taxation at vest | current law | 26 U.S.C. §83. https://www.law.cornell.edu/uscode/text/26/83 |
| ESPP §423 | current law | 26 U.S.C. §423. https://www.law.cornell.edu/uscode/text/26/423 |
| Supplemental withholding | current year | IRS Publication 15 (Circular E). https://www.irs.gov/publications/p15 |
| 10–30% satellite, 80/20, 1–2% tracking-error budget, 10% employer line | n/a | Practitioner rules of thumb with no single source |
