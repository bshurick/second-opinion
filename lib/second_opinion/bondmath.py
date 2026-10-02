"""Bond cash-flow mathematics — pricing, risk measures and curve construction.

Pure functions only. No network, no file I/O, no printing, so every result
here is unit-testable without fixtures. Scripts in ``skills/fixed-income``
do the fetching and hand values to these functions.

Rates and yields are decimals (0.0531 is 5.31%), times are in years, and
prices are per ``face`` (default 100) unless stated otherwise.
"""
from __future__ import annotations

import math
from typing import Callable

# The most coupon periods any function here will build. A resource bound, not a
# domain one: ``cashflows`` materialises every period as a list entry before
# anything is discounted, so ``years * freq`` is allocated up front and an
# unbounded figure does not fail — it allocates until the process is killed
# (measured: years=1e8 at freq=2 is 200 million tuples, about 14 GB). A million
# payments is 500,000 years of semi-annual coupons and no instrument approaches
# it: a 100-year bond is 200 periods.
MAX_PERIODS = 1_000_000


def bisect(
    fn: Callable[[float], float],
    lo: float,
    hi: float,
    tol: float = 1e-12,
    max_iter: int = 300,
) -> float:
    """Root of ``fn`` bracketed by ``lo`` and ``hi``.

    Bisection rather than Newton or scipy.optimize so the library keeps to
    the standard library and never fails to converge on a bracketed root.
    """
    f_lo = fn(lo)
    f_hi = fn(hi)
    if f_lo * f_hi > 0:
        raise ValueError(f"root not bracketed: f({lo})={f_lo}, f({hi})={f_hi}")
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = fn(mid)
        if hi - lo < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def cashflows(
    coupon_rate: float,
    years: float,
    freq: int = 2,
    face: float = 100.0,
) -> list[tuple[float, float]]:
    """``[(time_in_years, amount)]`` ascending; the last payment carries face."""
    if freq < 1:
        raise ValueError("freq must be at least 1")
    if years <= 0:
        raise ValueError("years must be positive")
    n = int(round(years * freq))
    if n < 1:
        raise ValueError("years x freq must round to at least one period")
    if n > MAX_PERIODS:
        raise ValueError(
            f"years x freq is {n:,} coupon periods, above the "
            f"{MAX_PERIODS:,} this module will build"
        )
    coupon = face * coupon_rate / freq
    out = [((i / freq), coupon) for i in range(1, n + 1)]
    last_t, last_amt = out[-1]
    out[-1] = (last_t, last_amt + face)
    return out


def price_from_yield(
    coupon_rate: float,
    years: float,
    ytm: float,
    freq: int = 2,
    face: float = 100.0,
) -> float:
    """Present value of the bond's cash flows at a flat yield ``ytm``."""
    per = ytm / freq
    return sum(
        amt / ((1.0 + per) ** (t * freq))
        for t, amt in cashflows(coupon_rate, years, freq, face)
    )


def yield_from_price(
    price: float,
    coupon_rate: float,
    years: float,
    freq: int = 2,
    face: float = 100.0,
) -> float:
    """The flat yield that reprices the bond to ``price``."""
    if price <= 0:
        raise ValueError("price must be positive")
    return bisect(
        lambda y: price_from_yield(coupon_rate, years, y, freq, face) - price,
        -0.99 * freq + 1e-9,
        1.0,
    )


def macaulay_duration(
    coupon_rate: float,
    years: float,
    ytm: float,
    freq: int = 2,
    face: float = 100.0,
) -> float:
    """Cash-flow-weighted average time to payment, in years."""
    per = ytm / freq
    cf = cashflows(coupon_rate, years, freq, face)
    price = sum(amt / ((1.0 + per) ** (t * freq)) for t, amt in cf)
    weighted = sum(t * amt / ((1.0 + per) ** (t * freq)) for t, amt in cf)
    return weighted / price


def modified_duration(
    coupon_rate: float,
    years: float,
    ytm: float,
    freq: int = 2,
    face: float = 100.0,
) -> float:
    """Percentage price change per unit change in yield."""
    return macaulay_duration(coupon_rate, years, ytm, freq, face) / (1.0 + ytm / freq)


def convexity(
    coupon_rate: float,
    years: float,
    ytm: float,
    freq: int = 2,
    face: float = 100.0,
) -> float:
    """Second derivative of price with respect to yield, divided by price."""
    per = ytm / freq
    cf = cashflows(coupon_rate, years, freq, face)
    price = sum(amt / ((1.0 + per) ** (t * freq)) for t, amt in cf)
    second = sum(
        t * (t + 1.0 / freq) * amt / ((1.0 + per) ** (t * freq + 2))
        for t, amt in cf
    )
    return second / price


def price_change(modified_dur: float, convexity_: float, delta_yield: float) -> float:
    """Fractional price change for ``delta_yield``, to second order."""
    return -modified_dur * delta_yield + 0.5 * convexity_ * delta_yield ** 2


def accrued_interest(
    coupon_rate: float,
    days_since_last: int,
    days_in_period: int,
    freq: int = 2,
    face: float = 100.0,
) -> float:
    """Coupon earned but not yet paid, straight-line across the period."""
    if days_in_period <= 0:
        raise ValueError("days_in_period must be positive")
    return face * coupon_rate / freq * (days_since_last / days_in_period)


def interp_par(tenors: list[float], pars: list[float], t: float) -> float:
    """Linear interpolation along the par curve, flat beyond the ends."""
    if not tenors or len(tenors) != len(pars):
        raise ValueError("tenors and pars must be non-empty and the same length")
    pairs = sorted(zip(tenors, pars))
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    if t <= xs[0]:
        return ys[0]
    if t >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if t <= xs[i]:
            span = xs[i] - xs[i - 1]
            w = (t - xs[i - 1]) / span
            return ys[i - 1] + w * (ys[i] - ys[i - 1])
    return ys[-1]


def bootstrap(
    tenors: list[float],
    pars: list[float],
    freq: int = 2,
    max_years: float = 30.0,
) -> dict[float, float]:
    """Discount factors on a ``1/freq`` grid, bootstrapped from par yields.

    Each grid point is a par bond whose coupon is the interpolated par yield;
    its price is face, so the final discount factor solves out from the
    annuity of the earlier ones.

    ``max_years * freq`` sizes the loop and carries no ``MAX_PERIODS`` check,
    unlike ``cashflows``. Deliberate, and recorded rather than guarded: both
    callers pass module constants (``rates.py`` 2/30, ``fund.py`` ``FREQ``/
    ``MAX_YEARS``, 60 periods each), and ``tenors``/``pars`` come from FRED,
    not from a payload, so no caller-supplied value reaches either argument. A
    speculative bound here would be a guard against nothing this repo can
    build. Anything that first exposes ``freq`` or ``max_years`` to an input
    payload has to add one, and to decide what ``freq <= 0`` should do: it is
    a ``ZeroDivisionError`` today, and a negative ``freq`` returns a silently
    EMPTY curve that then flows on into ``zero_rate``/``price_on_curve``.
    """
    step = 1.0 / freq
    n = int(round(max_years * freq))
    curve: dict[float, float] = {}
    annuity = 0.0
    for i in range(1, n + 1):
        t = i * step
        c = interp_par(tenors, pars, t) / freq
        df = (1.0 - c * annuity) / (1.0 + c)
        curve[round(t, 10)] = df
        annuity += df
    return curve


def discount_factor(curve: dict[float, float], t: float) -> float:
    """Discount factor at ``t`` on ``curve`` (``{time_in_years: discount_factor}``).

    ``t <= 0`` returns ``1.0`` by definition. Below the first grid point the
    factor is interpolated log-linearly from ``df(0) = 1`` — equivalently,
    holding the first grid point's zero rate constant — so it is continuous at
    ``t = 0``. Beyond the last grid point ``t`` is clamped to the last discount
    factor, a deliberate flat-extrapolation convention, so anything maturing
    past the curve's ``max_years`` is mispriced.
    """
    if not curve:
        raise ValueError("curve is empty")
    if t <= 0:
        return 1.0
    ts = sorted(curve)
    hi = ts[-1]
    t = min(t, hi)
    if t in curve:
        return curve[t]
    if t < ts[0]:
        return math.exp((t / ts[0]) * math.log(curve[ts[0]]))
    for i in range(1, len(ts)):
        if t <= ts[i]:
            t0, t1 = ts[i - 1], ts[i]
            l0, l1 = math.log(curve[t0]), math.log(curve[t1])
            w = (t - t0) / (t1 - t0)
            return math.exp(l0 + w * (l1 - l0))
    return curve[hi]


def zero_rate(curve: dict[float, float], t: float, freq: int = 2) -> float:
    """Annualised zero-coupon rate at ``t``, compounded ``freq`` times a year."""
    if t <= 0:
        raise ValueError("t must be positive")
    df = discount_factor(curve, t)
    return freq * ((1.0 / df) ** (1.0 / (t * freq)) - 1.0)


def forward_rate(curve: dict[float, float], t1: float, t2: float, freq: int = 2) -> float:
    """Annualised forward rate between ``t1`` and ``t2``."""
    if t2 <= t1:
        raise ValueError("t2 must be greater than t1")
    df1 = discount_factor(curve, t1)
    df2 = discount_factor(curve, t2)
    periods = (t2 - t1) * freq
    return freq * ((df1 / df2) ** (1.0 / periods) - 1.0)


def price_on_curve(
    cf: list[tuple[float, float]],
    curve: dict[float, float],
    spread: float = 0.0,
    freq: int = 2,
) -> float:
    """Present value of ``cf`` on the zero curve, plus a flat ``spread``."""
    total = 0.0
    for t, amt in cf:
        df = discount_factor(curve, t)
        total += amt * df / ((1.0 + spread / freq) ** (t * freq))
    return total
