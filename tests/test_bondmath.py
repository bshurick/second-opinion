import pytest
from second_opinion import bondmath


def test_par_bond_prices_at_par():
    # A bond whose coupon equals its yield is worth exactly face value.
    assert bondmath.price_from_yield(0.05, 10, 0.05) == pytest.approx(100.0, abs=1e-9)


def test_zero_coupon_price_is_simple_discount():
    # 5y zero at 4%, semiannual compounding: 100 / 1.02^10
    expected = 100.0 / (1.02 ** 10)
    assert bondmath.price_from_yield(0.0, 5, 0.04) == pytest.approx(expected, abs=1e-9)


def test_discount_bond_prices_below_par():
    assert bondmath.price_from_yield(0.03, 10, 0.05) < 100.0


def test_premium_bond_prices_above_par():
    assert bondmath.price_from_yield(0.07, 10, 0.05) > 100.0


def test_yield_from_price_inverts_price_from_yield():
    price = bondmath.price_from_yield(0.035, 8, 0.0525)
    assert bondmath.yield_from_price(price, 0.035, 8) == pytest.approx(0.0525, abs=1e-9)


def test_cashflows_last_payment_includes_face():
    cf = bondmath.cashflows(0.06, 2)
    assert len(cf) == 4
    assert cf[0] == (0.5, 3.0)
    assert cf[-1] == (2.0, 103.0)


def test_zero_coupon_macaulay_duration_equals_maturity():
    assert bondmath.macaulay_duration(0.0, 7, 0.04) == pytest.approx(7.0, abs=1e-9)


def test_modified_duration_is_macaulay_discounted():
    mac = bondmath.macaulay_duration(0.05, 10, 0.06)
    mod = bondmath.modified_duration(0.05, 10, 0.06)
    assert mod == pytest.approx(mac / (1 + 0.06 / 2), abs=1e-9)


def test_coupon_bond_duration_is_less_than_maturity():
    assert bondmath.macaulay_duration(0.06, 10, 0.06) < 10.0


def test_convexity_is_positive_for_a_bullet_bond():
    assert bondmath.convexity(0.05, 10, 0.05) > 0


def test_price_change_matches_a_full_reprice_to_within_a_few_bp():
    # Duration + convexity should approximate an actual reprice closely
    # for a 50 bp move.
    base = bondmath.price_from_yield(0.04, 10, 0.05)
    exact = bondmath.price_from_yield(0.04, 10, 0.055)
    mod = bondmath.modified_duration(0.04, 10, 0.05)
    cvx = bondmath.convexity(0.04, 10, 0.05)
    approx = base * (1 + bondmath.price_change(mod, cvx, 0.005))
    assert approx == pytest.approx(exact, rel=1e-4)


def test_accrued_interest_half_way_through_a_period():
    # 6% annual coupon, semiannual, exactly half the period elapsed
    assert bondmath.accrued_interest(0.06, 91, 182) == pytest.approx(1.5, abs=1e-2)


FLAT_TENORS = [0.5, 1, 2, 3, 5, 7, 10, 20, 30]
FLAT_PARS = [0.04] * len(FLAT_TENORS)


def test_flat_par_curve_gives_flat_zero_rates():
    curve = bondmath.bootstrap(FLAT_TENORS, FLAT_PARS)
    for t in (1.0, 5.0, 10.0, 30.0):
        assert bondmath.zero_rate(curve, t) == pytest.approx(0.04, abs=1e-6)


def test_flat_curve_forwards_equal_the_spot_rate():
    curve = bondmath.bootstrap(FLAT_TENORS, FLAT_PARS)
    assert bondmath.forward_rate(curve, 5.0, 10.0) == pytest.approx(0.04, abs=1e-6)


def test_discount_factors_decrease_with_time():
    curve = bondmath.bootstrap(FLAT_TENORS, FLAT_PARS)
    assert bondmath.discount_factor(curve, 1.0) > bondmath.discount_factor(curve, 10.0)


def test_pricing_on_a_flat_curve_matches_pricing_at_that_flat_yield():
    curve = bondmath.bootstrap(FLAT_TENORS, FLAT_PARS)
    cf = bondmath.cashflows(0.05, 10)
    on_curve = bondmath.price_on_curve(cf, curve)
    at_yield = bondmath.price_from_yield(0.05, 10, 0.04)
    assert on_curve == pytest.approx(at_yield, rel=1e-6)


def test_a_rising_curve_is_not_one_number():
    tenors = [0.5, 1, 2, 5, 10, 30]
    pars = [0.03, 0.033, 0.036, 0.04, 0.045, 0.05]
    curve = bondmath.bootstrap(tenors, pars)
    # A par yield is a coupon average, not a spot rate: on a rising curve the
    # bootstrapped 10-year zero sits ABOVE the 10-year par yield (4.5893% vs
    # 4.5000% here), so the principal is discounted harder.
    assert bondmath.zero_rate(curve, 10.0) > 0.045
    # Pricing a 5% bond on the curve therefore lands about 6 bp above
    # discounting every flow at the flat 10-year rate.
    on_curve = bondmath.price_on_curve(bondmath.cashflows(0.05, 10), curve)
    flat_long = bondmath.price_from_yield(0.05, 10, 0.045)
    assert on_curve > flat_long
    assert on_curve - flat_long == pytest.approx(0.062, abs=0.005)


def test_a_spread_lowers_the_price():
    curve = bondmath.bootstrap(FLAT_TENORS, FLAT_PARS)
    cf = bondmath.cashflows(0.05, 10)
    assert bondmath.price_on_curve(cf, curve, spread=0.01) < bondmath.price_on_curve(cf, curve)


def test_the_short_end_is_not_clamped_to_the_first_grid_point():
    tenors = [0.5, 1, 2, 5, 10, 30]
    curve = bondmath.bootstrap(tenors, [0.04] * len(tenors))
    # df(0) is 1.0 by definition. The grid starts at 0.5, so clamping t to the
    # grid would return df(0.5) here and turn the short end into nonsense:
    # zero_rate(curve, 0.25) came back as 8.08% and forward_rate(curve, 0, 0.5)
    # as 0.00% on a curve whose every input was 4%.
    assert bondmath.discount_factor(curve, 0.0) == pytest.approx(1.0, abs=1e-12)
    assert bondmath.zero_rate(curve, 0.25) == pytest.approx(0.04, abs=1e-9)
    assert bondmath.forward_rate(curve, 0.0, 0.5) == pytest.approx(0.04, abs=1e-9)
    assert bondmath.forward_rate(curve, 0.0, 1.0) == pytest.approx(0.04, abs=1e-9)


def test_the_short_end_is_anchored_at_the_origin_on_a_rising_curve():
    tenors = [0.5, 1, 2, 5, 10, 30]
    pars = [0.03, 0.033, 0.036, 0.04, 0.045, 0.05]
    curve = bondmath.bootstrap(tenors, pars)
    # On a rising curve, extending the [0.5, 1.0] segment backwards never passes
    # through df(0) = 1: it bows above 1 below t ~ 0.083 and the 1/t in zero_rate
    # amplifies that into fabricated rates -- zero_rate(0.05) came back as -2.37%,
    # zero_rate(0.001) as -154% -- with a 0.30% jump at t = 0, where df(1e-5) was
    # 1.00298 against a df(0.0) of 1.0.
    assert bondmath.discount_factor(curve, 1e-5) < 1.0
    # Anchoring at (0, ln 1.0) is the same thing as holding the first grid point's
    # zero rate constant below it, so every short-end rate is the 0.5-year rate.
    assert bondmath.zero_rate(curve, 0.25) == pytest.approx(0.03, abs=1e-9)
    assert bondmath.zero_rate(curve, 0.05) == pytest.approx(0.03, abs=1e-9)
    assert bondmath.forward_rate(curve, 0.0, 0.25) == pytest.approx(0.03, abs=1e-9)
    # ...and df is continuous at the origin.
    assert bondmath.discount_factor(curve, 1e-9) == pytest.approx(1.0, abs=1e-9)


def test_cashflows_refuses_a_period_count_it_cannot_build():
    # A resource bound, not a domain rule. ``cashflows`` materialises every period
    # as a list entry before anything is discounted, so ``years * freq`` is
    # allocated up front: years=1e8 at freq=2 is 200 million tuples, about 14 GB,
    # and the process allocates until it is killed rather than raising. A caller
    # then gets no exit code, no JSON and no stdout -- the one outcome every
    # script here exists to prevent -- so the count is refused before it is built.
    with pytest.raises(ValueError, match="coupon periods"):
        bondmath.cashflows(0.04, 1e8, 2)
    # Reachable from freq just as easily as from years.
    with pytest.raises(ValueError, match="coupon periods"):
        bondmath.cashflows(0.04, 30, 1_000_000_000)
    # The message names both the count and the bound, so the caller can see which
    # figure to go and fix rather than reading "Result too large".
    with pytest.raises(
        ValueError, match=r"200,000,000 coupon periods, above the 1,000,000"
    ):
        bondmath.cashflows(0.04, 1e8, 2)


def test_cashflows_bound_refuses_nothing_real():
    # No instrument comes near the bound: a 100-year bond is 200 periods, and the
    # longest sovereign maturities are shorter still. Both ends of the accepted
    # range keep working, so the guard costs a real caller nothing.
    assert len(bondmath.cashflows(0.04, 100, 2)) == 200
    assert len(bondmath.cashflows(0.04, 0.5, 2)) == 1
    # Exactly at the bound is still built; one period past it is not.
    assert len(bondmath.cashflows(0.04, 500_000, 2)) == bondmath.MAX_PERIODS
    with pytest.raises(ValueError, match="coupon periods"):
        bondmath.cashflows(0.04, 500_000.5, 2)
