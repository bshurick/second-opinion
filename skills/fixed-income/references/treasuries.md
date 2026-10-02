# US Treasury securities: what they are and how they are quoted

The scripts in this skill price **one fixed-coupon bond** and curves built from fixed-coupon par
yields. Several Treasury instruments do not fit that model, and two of them are quoted in a
convention that is not a yield at all. This reference is the vocabulary: what the Treasury issues,
how each one is quoted, and which of them this skill can and cannot price.

Every worked number below was computed, not estimated.

## Contents

- The instruments
- Bills are quoted on a discount basis
- TIPS: principal that moves with the index
- Real, nominal, and the breakeven between them
- Phantom income
- State and local tax exemption
- Floating rate notes
- STRIPS
- What this skill does not price

## The instruments

| Instrument | Maturity at issue | Coupon | Quoted as |
|---|---|---|---|
| Bill | 4, 8, 13, 17, 26, 52 weeks | none — sold at a discount | **discount rate**, not a yield |
| Note | 2, 3, 5, 7, 10 years | fixed, semi-annual | yield to maturity |
| Bond | 20, 30 years | fixed, semi-annual | yield to maturity |
| TIPS | 5, 10, 30 years | fixed **real** rate on accreting principal | **real** yield |
| FRN | 2 years | resets **weekly** off the 13-week bill, paid quarterly | discount margin |
| STRIPS | any, stripped from notes/bonds | none — a single cash flow | yield to maturity |

The par curve this skill bootstraps (`DGS1MO` through `DGS30`) is built from the **nominal** coupon
curve. Bills enter it at the short end already converted by FRED to a coupon-equivalent basis, so the
curve is internally consistent; a bill quote you read anywhere else is probably not.

## Bills are quoted on a discount basis

A bill has no coupon. It is sold below face and repays face, and the quoted number is the **bank
discount rate** — the gain expressed as a fraction of **face**, on a **360-day** year:

    d = (F - P) / F x 360 / t

Both choices understate the return. The gain is divided by face rather than by the smaller amount
actually invested, and the year is 360 days rather than 365. Converting to a bond-equivalent yield
reverses both:

    P   = F x (1 - d x t / 360)
    BEY = (F - P) / P x 365 / t

A 13-week bill quoted at a **4.00% discount rate**:

    price = 100 x (1 - 0.0400 x 91/360) = 98.9889
    BEY   = (100 - 98.9889) / 98.9889 x 365/91 = 4.097%

**A 4.00% bill yields 4.10%.** The gap widens with the rate and with maturity. Comparing a quoted bill
discount rate against a note's yield to maturity, a CD's APY, or a fund's SEC yield compares two
different quantities, and always in the bill's disfavour.

(The formula above is the standard short-bill conversion. For bills longer than six months the exact
coupon-equivalent calculation carries a compounding term; the difference is small but it exists.)

That conversion is the whole of what this skill can do with a bill. Do not hand the result to
`bond.py` or `horizon.py` — see "What this skill does not price" for why a bill has no period for
them to model.

## TIPS: principal that moves with the index

A TIPS carries a fixed **real** coupon rate, but the principal it is paid on moves with CPI-U through
an **index ratio** — the reference CPI for the settlement date over the CPI at issue:

    accreted principal = original principal x index ratio
    semi-annual coupon = accreted principal x real coupon rate / 2

A $1,000 TIPS with a 1.25% real coupon, after 12% cumulative inflation since issue:

    accreted principal  = 1,000 x 1.12 = 1,120.00
    semi-annual coupon  = 1,120.00 x 0.0125 / 2 = 7.00

**The deflation floor is narrower than it is usually described.** If the index ratio falls below 1.0,
principal accretes downward and the coupon shrinks with it. At maturity the Treasury repays
`max(accreted, original)` — but that floor applies to the **principal repayment only**, not to the
coupons paid along the way. With an index ratio of 0.94:

    accreted principal  = 940.00       (coupon is paid on this)
    semi-annual coupon  = 940.00 x 0.0125 / 2 = 5.88
    repaid at maturity  = max(940, 1000) = 1,000.00

So deflation does cost a holder real money in coupons even though principal is protected. A TIPS
bought **in the secondary market above its accreted value** can also lose more than the floor implies,
since the floor protects the original principal, not what you paid.

## Real, nominal, and the breakeven between them

A nominal Treasury yield compensates for expected inflation; a TIPS real yield does not have to. The
difference is the **breakeven inflation rate**:

    breakeven ~= nominal yield - real yield

It is the inflation rate at which the two come out even. Realised inflation above it favours the TIPS;
below it favours the nominal. `rates.py` reports both sides against their own history —
`percentiles.real_yield_10y` from `DFII10` and `percentiles.breakeven_10y` from `T10YIE`.

**The breakeven is a market price, not a forecast.** It is where the two instruments clear today, and
it carries an inflation risk premium as well as an expectation, so it is not the market's central
estimate of inflation. Treat it as the level at which the choice is a wash, and say so.

## Phantom income

Each year's upward principal accretion is **federally taxable in the year it accrues**, even though no
cash is received until maturity. A holder in a taxable account can therefore owe tax on money they have
not been paid — the same arithmetic applies to STRIPS, whose entire return is accretion.

This is a mechanical fact about the instrument, not a view on which account anyone holds one in. It is
the reason TIPS and STRIPS are commonly discussed in the context of tax-deferred accounts.

## State and local tax exemption

Interest on Treasury securities is **exempt from state and local income tax** (it remains federally
taxable). A CD or corporate bond is taxed by both. To compare like with like, gross the Treasury up by
the state marginal rate:

    taxable-equivalent yield = treasury yield / (1 - state marginal rate)

A 4.00% Treasury, against a fully taxable alternative:

| State marginal rate | A CD must yield |
|---|---|
| 9.3% | 4.410% |
| 6.85% | 4.294% |
| 0% (WA, TX, FL, NV, ...) | 4.000% |

**The benefit is zero in a state with no income tax**, and it is zero inside an IRA or 401(k), where
neither instrument is taxed currently. Both facts matter more than the formula: the exemption is
routinely quoted as though it always applies.

(Treasury *money market funds* pass the exemption through only in proportion to their Treasury
holdings, and a few states impose a minimum-holding threshold before any of it passes through.)

**The formula already assumes the best case, so read it as a floor.** `T / (1 - s)` is exactly the
breakeven when state income tax is fully deductible on the federal return: the CD's after-tax return
is then `C(1 - s)(1 - f)`, which equals the Treasury's `T(1 - f)` at `C = T / (1 - s)`. When the
deduction is unavailable — the SALT cap, or not itemising — the CD is taxed by both at once,
`C(1 - f - s)`, and the breakeven rises to `T(1 - f) / (1 - f - s)`: **4.54% at a 22% federal rate,
4.63% at 32%, 4.69% at 37%**, against the same 4.410%.

So 4.410% is a **lower** bound on what the CD must yield, not an upper one, and the SALT cap moves
the requirement **up** rather than down. At a 37% federal rate, per $100: the Treasury nets $2.520,
a 4.4101% CD with the deduction nets $2.520 — a tie — and the same CD without it nets $2.368, a
loss. The figure is called out because the worked numbers here are meant to be used.

## Floating rate notes

A two-year FRN pays a coupon that resets **weekly** off the 13-week bill auction, plus a spread fixed
at its own auction. Its price barely moves with the level of rates, because the coupon follows them —
so its duration is near zero and the duration arithmetic in `bond-math.md` does not describe it. What
an FRN holder is exposed to is the **spread**, not the curve.

## STRIPS

A STRIP is one cash flow: a coupon or principal payment sold separately. With no coupons to reinvest,
its **Macaulay duration equals its maturity exactly** — it is the one instrument for which the
horizon-immunisation result in `bond-math.md` is trivially true, because there is nothing to reinvest.
Its entire return is accretion, so the phantom-income note above applies in full.

## What this skill does not price

The scripts model a **fixed-coupon bond with certain cash flows**, over **whole semi-annual coupon
periods**. Two different boundaries, and the second one catches an instrument whose cash flows are
perfectly certain. Specifically not modelled:

- **Bills.** Not an uncertainty problem, a period-count one: `bond.py` and `horizon.py` model
  `int(round(years x freq))` whole coupon periods, and at the semi-annual `freq` of 2 they assume, a
  4-, 8- or 13-week bill has none — both exit 2 with `years x freq must round to at least one
  period`. A **17-week bill is worse than an error**: 0.327 x 2 rounds *up* to one, so the scripts
  price it as though it matured in six months and say nothing. Only the 26- and 52-week bills land
  on a whole number of semi-annual periods. Raising `freq` is not the workaround — a bill pays no
  coupon at all, so any period count for one is a fiction, and every other figure in this skill is
  semi-annual. Convert a bill quote to a bond-equivalent yield with the arithmetic above and compare
  that against the curve; do not hand a bill to either script. (A STRIP is zero-coupon too and **is**
  in scope, because a 10-year STRIP still spans 20 periods — the line here is the period count, not
  the missing coupon.)
- **TIPS real cash flows.** `bond.py` and `horizon.py` given a TIPS real yield will produce arithmetic
  in real terms, and the accretion is absent from it. The real/breakeven percentiles in `rates.py` are
  the supported TIPS view.
- **FRN resets.** A floater's coupon is unknown beyond the next reset, so fixed-coupon duration and the
  horizon result do not apply.
- **Embedded options.** As `bond-math.md` already states for callables, putables and mortgage-backed
  bonds: their cash flows are not certain, and pricing them as though they were overstates duration and
  understates the risk.

When a question is about one of these, say which part of it the scripts can answer and which part they
cannot, rather than returning a number that quietly assumes the instrument is something it is not.
