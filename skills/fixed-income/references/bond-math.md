# Bond math

The derivations behind `lib/second_opinion/bondmath.py`, and the conventions every function in it
assumes. The module is pure arithmetic: no network, no files, no printing. The skill's scripts fetch
the inputs and hand them over.

Read this when a figure looks wrong by a factor of 100, when a curve figure past thirty years looks
too good, or when two duration numbers disagree and it is not obvious which question each answers.

## Contents

- Conventions and units
- Cash flows
- Price from yield
- Yield from price
- Macaulay duration
- Modified duration
- Convexity and the second-order price change
- Accrued interest
- The par curve and the bootstrap
- Discount factors between and beyond the grid
- Zero rates and forward rates
- Pricing on a curve with a spread
- The horizon at which a rate move cancels out
- What this module does not do

## Conventions and units

Getting these wrong is the most expensive mistake available here, so they are listed before any
derivation.

| Quantity | Unit | Example |
|---|---|---|
| `coupon_rate`, `ytm`, `spread` | decimal fraction per year | `0.0531` is 5.31% |
| `years`, `t`, `t1`, `t2` | years | `8.2` |
| `freq` | coupon payments per year | `2` means semi-annual |
| `face` | currency, default `100.0` | prices come back per this face |
| `price`, `price_from_yield`, `price_on_curve` | currency per `face` | `90.1968` on a face of 100 |
| `macaulay_duration` | years | `6.9085` |
| `modified_duration` | fractional price change per unit of yield | `6.7298`, i.e. 6.73% per 100 bp |
| `convexity` | years squared | `52.9639` |
| `accrued_interest` | currency per `face` | `1.5` on a face of 100, not "1.5%" |
| `bootstrap`, `curve` | `{time_in_years: discount_factor}` | `{0.5: 0.9794, 1.0: 0.9568, ...}` |

Two of those rows carry the whole warning.

**Durations are never percentages.** `modified_duration(0.04, 10, 0.05)` returns `8.0542`. That is a
fraction of price per 1.00 of yield, and nobody moves a yield by 1.00, so the usable readings are the
scaled ones: a 100 bp move (`Δy = 0.01`) changes the price by `8.0542 × 0.01 = 8.05%`, and one basis
point changes it by `0.0805%`. Formatting the raw figure with a percent sign —
`f"{8.0542:.2%}"` renders `805.42%` — overstates the risk by a factor of 100 on a page a person
reads. `macaulay_duration` is in years and takes no percent sign either.

The three example figures in the table above are one bond: a 3.79% coupon maturing in 8.2 years at a
5.31% yield, semi-annual.

**`accrued_interest` is currency, not percent of par.** At 6% on a face of 100, halfway through a
semi-annual period, it returns `1.5` — one and a half currency units, half of the 3.0 coupon.

Everything below uses `per = ytm / freq` for the per-period yield and `n = round(years * freq)` for
the number of periods.

## Cash flows

`cashflows(coupon_rate, years, freq, face)` returns `[(time_in_years, amount)]` ascending, one entry
per period at `i / freq` for `i` in `1..n`, each carrying `face * coupon_rate / freq`, with `face`
added to the last.

Two consequences worth knowing before reading a result:

- `n = int(round(years * freq))`, so the period count is **rounded, not truncated**: `years = 8.2` at
  `freq = 2` gives 16 periods, i.e. 8.0 years of cash flows. A fractional period is absorbed, and the
  count cannot be inverted to recover `years`.
- `years * freq` above `MAX_PERIODS` (1 000 000) raises rather than allocating. That is a resource
  bound: the list is materialised before anything is discounted.

## Price from yield

`price_from_yield` discounts every cash flow at one flat yield:

```
P = Σ_i  CF_i / (1 + ytm/freq)^(t_i · freq)
```

A single rate for every maturity. That is the definition of a yield to maturity, and it is why a
yield is a summary of a price rather than an independent measurement of value: the price goes in, the
yield comes out, and pricing that yield back reproduces the price exactly.

## Yield from price

`yield_from_price` inverts the same relation by bisection, because there is no closed form for `ytm`
once `n > 2`. `price_from_yield` is continuous and strictly decreasing in `ytm` over the bracket the
module uses, so a bisection converges to the single root; `bisect` runs to a tolerance of `1e-12` or
300 iterations, whichever comes first.

Strict monotonicity is what makes the root unique. It holds because every cash flow is positive: each
term of the sum falls as the yield rises. A bond with a negative cash flow somewhere in the middle
would have no such guarantee, and this module does not build one.

## Macaulay duration

The cash-flow-weighted average time to payment, in years:

```
D_mac = Σ_i  t_i · PV(CF_i)  /  Σ_i PV(CF_i)
```

with the present values taken at the bond's own yield. It is a point on the time axis: a
zero-coupon bond's Macaulay duration is exactly its maturity, and any coupon pulls the average
earlier because some money arrives before the end.

## Modified duration

```
D_mod = D_mac / (1 + ytm/freq)
```

This is the first derivative of price with respect to yield, divided by price and signed positive:

```
-(1/P) · dP/d(ytm) = D_mod
```

The division by `(1 + ytm/freq)` is the chain rule for discrete compounding — differentiating
`(1 + per)^(-t·freq)` brings down a factor of `1/(1 + per)`. Under continuous compounding the two
durations coincide, which is why the distinction is easy to lose and why the units row above spells
it out.

## Convexity and the second-order price change

```
C = (1/P) · Σ_i  t_i · (t_i + 1/freq) · CF_i / (1 + per)^(t_i·freq + 2)
```

which is the second derivative of price with respect to yield, divided by price, in years squared.
`price_change(modified_dur, convexity_, delta_yield)` assembles the two-term Taylor expansion:

```
ΔP/P ≈ -D_mod · Δy + ½ · C · Δy²
```

Convexity is positive for an ordinary bond, so the approximation gives back more on a fall in yields
than it loses on an equal rise. The expansion is an approximation and the error grows with the cube
of the move; for a large shock this skill re-prices the cash flows outright rather than expanding.

## Accrued interest

```
AI = face · coupon_rate / freq · days_since_last / days_in_period
```

The coupon earned but not yet paid, straight-line across the period.

The function is **day-count agnostic**: the caller supplies `days_since_last` and `days_in_period`
and therefore chooses the convention. Supply the actual day counts of a regular coupon period and the
result is the ISMA actual/actual figure — 91 days of 182 at 6% on a face of 100 is exactly 1.5.
Supply 30/360 counts and it is the 30/360 figure.

`days_in_period <= 0` raises. `days_since_last` is **not** validated, and the caller owns
`0 <= days_since_last <= days_in_period`. Outside that range the function still returns a number:
`accrued_interest(0.06, -10, 182)` gives `-0.16484`, and `accrued_interest(0.06, 200, 182)` gives
`3.2967`, more than the whole 3.0 coupon. Neither is flagged.

## The par curve and the bootstrap

`interp_par` interpolates the quoted par yields linearly in maturity and holds them flat beyond the
first and last quoted tenors.

`bootstrap(tenors, pars, freq, max_years)` then walks a `1/freq` grid from the first point out to
`max_years`. At each grid point `t` the instrument is a par bond whose coupon `c` is the interpolated
par yield for that maturity, divided by `freq`. Its price is par by definition, so

```
1 = c · Σ_{j<i} df_j  +  (1 + c) · df_i
```

and the new factor solves out directly:

```
df_i = (1 - c · annuity) / (1 + c)
```

where `annuity` is the running sum of the discount factors already found. One unknown per step, one
equation per step, no iteration. The returned dictionary maps grid time to discount factor, and
grid times are rounded to ten decimal places so that floating-point accumulation does not produce two
keys for the same point.

## Discount factors between and beyond the grid

`discount_factor(curve, t)` is log-linear in `t` between grid points: it interpolates
`ln df` and exponentiates, which is equivalent to holding the zero rate constant across each segment.

The two ends are the part worth reading twice.

- **`t <= 0` returns `1.0`** by definition.
- **Below the first grid point** (`0 < t < 1/freq`) the factor is interpolated log-linearly from
  `(0, ln 1.0)` to the first grid point. That is the same thing as holding the first grid point's zero
  rate constant over that stretch, and it is continuous at `t = 0`. `df(0) = 1` is the only exactly
  known point down there, so it is the one anchor consistent with the module's log-linear convention.
  An earlier version extrapolated off the first *segment* instead; on a rising curve that bowed the
  interpolation above `df = 1` and produced zero rates as low as −200%. It was a bug and it is gone.
- **Beyond the last tenor `t` is clamped**, returning the last discount factor. This is deliberate
  flat extrapolation and it **silently misprices anything maturing past the curve's `max_years`** —
  no exception, no warning, just a number that is too high. A thirty-five-year cash flow on a
  thirty-year curve is discounted as though it arrived at thirty. The scripts in this skill cap their
  own inputs at `max_years` for exactly this reason.

## Zero rates and forward rates

```
zero_rate(curve, t, freq)     = freq · ((1/df(t))^(1/(t·freq)) - 1)
forward_rate(curve, t1, t2, freq) = freq · ((df(t1)/df(t2))^(1/((t2-t1)·freq)) - 1)
```

Both are annualised and compounded `freq` times a year. **Both default to `freq = 2` regardless of the
grid the curve was bootstrapped on**, as does `price_on_curve`; pass it explicitly unless the curve
really was built at 2, or the number that comes back is quoted in a convention the curve does not use.

Because the short end now anchors at the origin, `forward_rate(curve, 0, t)` is well defined and
equals `zero_rate(curve, t_first_grid_point)` for `t` inside the first segment. It is a constant-rate
extension of the curve rather than an observed market forward, which is why this skill's published
short-rate path starts at the first grid point instead of at zero. When reading a path, check which
of the two is in front of you.

## Pricing on a curve with a spread

`price_on_curve(cf, curve, spread, freq)` discounts each cash flow on the curve and then divides by a
spread factor:

```
P = Σ_i  CF_i · df(t_i) / (1 + spread/freq)^(t_i · freq)
```

The docstring calls the spread "added"; the arithmetic **divides**, so the right name for it is a
**discount margin over the curve, quoted annualised**. Its `freq` governs only the spread's own
compounding, not the curve's grid.

Dividing is not identical to shifting every zero rate up by `spread`. The two agree to first order and
differ by the cross term `curve_rate · spread / freq` — roughly 2 bp at a 4% curve and a 1% spread — so
the margin discounts slightly harder than a parallel shift of the curve would.

## The horizon at which a rate move cancels out

A holder of a bond faces two effects when yields move, and they point in opposite directions. A rise
in yields lowers the price of whatever is still held; it also raises the rate at which every coupon
received afterwards is reinvested. Price risk falls as the holding period lengthens, reinvestment
gain rises with it, and there is a horizon where the two cancel to first order.

That horizon is the **Macaulay duration**. The standard derivation: the value at horizon `H` of a
position whose coupons are reinvested at the yield is `P(y) · (1 + y/freq)^(H·freq)`. Differentiating
with respect to `y` and setting the derivative to zero gives

```
dP/dy · (1 + y/freq)^(H·freq)  +  P · H · (1 + y/freq)^(H·freq - 1) / freq  =  0
```

and substituting `dP/dy = -P · D_mod = -P · D_mac / (1 + y/freq)` leaves `H = D_mac`. First order
only: the cancellation is exact for an infinitesimal move and approximate for a real one.

**How approximate is a question with no universal answer.** The residual at the Macaulay horizon grows
with maturity, with convexity and with the size of the shock. Measured on this skill's own script:
a 3.79% coupon, 8.2-year bond at a 5.31% yield spans 0.014 percentage points across ±200 bp at its
Macaulay horizon; a 4.5% coupon, 30-year bond at 4.75% spans 0.139 — ten times as much, at the same
kind of horizon. There is no figure that bounds this in general, so the scripts emit the computed
spread for the input in front of them and this file quotes none as a rule.

`matched` in the script output means the requested horizon is **within 20% of the Macaulay duration**.
That is a tolerance, not immunity. Inside that same band, for the 8.2-year bond above, the ±200 bp
spread runs from 0.0136 percentage points at its centre (H = 6.9085, the Macaulay duration itself)
to 1.0262 at its lower edge (H = 5.5269) — a factor of roughly seventy-five, `matched` true at
both. The band is not symmetric about its centre: at its upper edge (H = 8.2902) the spread is
0.6847, so the worst case inside the band is the short horizon, not the long one. Every figure in
this paragraph was measured by running `horizon.py` at those horizons, not written by hand. The
flag says the horizon is near the cancelling point; the spread figure says how near, and only the
spread figure is quantitative.

## What this module does not do

- **No fair value.** Every input is a market price — a quoted yield, a par curve, a published spread —
  so anything priced from them reproduces the market by construction. A calculated yield that lands
  near a published one is arithmetic agreeing with itself, not evidence about whether a bond is cheap
  or expensive, and this skill never presents one as a valuation.
- **No credit.** No default probability, no recovery, no rating migration. A spread is an input the
  caller supplies; nothing here asks whether it is enough.
- **No options.** No call or put schedule, no prepayment model, so a callable bond, a mortgage pool
  and a putable note are all priced as though their cash flows were certain. For a mortgage-backed
  index the effective duration a fund publishes accounts for prepayment and the Macaulay duration
  computed here does not, which is one reason the two figures differ.
- **No taxes, no transaction costs, no accrual calendar.** Cash flows land on an idealised `1/freq`
  grid from today, not on the bond's actual payment dates.
- **No forecast.** A shocked scenario answers "what if yields moved by this much", never "yields will
  move".
