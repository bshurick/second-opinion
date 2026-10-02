"""scripts/horizon.py: the hold-to-horizon return, the duration split, and the
two input shapes it reads.

No test in this file touches the network: the fund payload below is a recorded
iShares/AGG fixture for BND, not a live fetch.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "skills" / "fixed-income" / "scripts"
HORIZON = SCRIPTS / "horizon.py"

sys.path.insert(0, str(SCRIPTS))


BONDS = [
    (0.0379, 8.2, 0.0531),   # a BND-like proxy
    (0.05, 10, 0.05),        # par bond
    (0.0, 7, 0.04),          # zero coupon
    (0.07, 20, 0.045),       # premium bond
    (0.02, 5, 0.06),         # deep discount
]

# The BND-like proxy as a dict, plus the durations the script must report for it.
BOND_PROXY = {"coupon_rate": 0.0379, "years": 8.2, "ytm": 0.0531}
PROXY_MACAULAY = 6.9085
PROXY_MODIFIED = 6.7298

# BND's published characteristics, recorded from fund.py on 2026-09-17. A
# fixture, not a live fetch: the published figures move daily. Only the input
# keys horizon.py reads are required, but the whole object is kept verbatim so
# the fixture is recognisably fund.py's output.
BND_CHARACTERISTICS = {
    "ytm_pct": 5.31,
    "coupon_pct": 3.785,
    "duration_years": 5.748,   # the PUBLISHED EFFECTIVE duration
    "wal_years": 8.27,
    "sec_yield_pct": 4.84,
    "distribution_yield_pct": 4.13,
    "expense_ratio_pct": 0.03,
    "source": "iShares AGG product page (index proxy for BND)",
}

# Every disclosure string the output carries, in full, keyed by the output path
# that emits it. Nothing here is derived from horizon.py, on purpose: an
# expectation built out of the module moves with the module, and an anchor on a
# phrase cannot see a sentence added beside intact wording. Both holes were
# demonstrated — prefixing _HEADLINE_NOTE with "BUY: this bond is cheap and the
# fund is a bargain at this price." left this file at 37 passed and added no
# failure suite-wide, because the identity assertion moved with the constant and
# every anchor was still intact. A trade signal is the one thing this skill may
# never emit, so the text is copied here word for word and the payload has to
# equal it. Same treatment as 1d54fb45 gave fund.py's ten strings.
#
# The cost is real and intended: a legitimate prose edit is made in two places,
# and this is the second one. A failure names the path that drifted.
DISCLOSURE_TEXTS = {
    "assumptions.headline_is_not_a_forecast": (
        "The locked-in return is implied by today's price and is not a forecast: at a matched "
        "horizon it reproduces the market's own yield because the price already reflects it. The "
        "scenarios show how far the outcome moves if rates CHANGE by up to 200 basis points — a "
        "sensitivity, not a prediction that they will. Nothing here is a fair value, and nothing "
        "here is a view on whether the bond or the fund is cheap or expensive."
    ),
    "assumptions.duration_meanings": (
        "Three durations appear in this output and only the first is the hold-to-horizon answer. "
        "duration_years is the MACAULAY duration of the cash flows above: the horizon at which the "
        "price loss from a rate move and the higher reinvestment rate cancel, so it is the figure "
        "the matched flag is measured against. modified_duration_years is price sensitivity per "
        "unit of yield — a first-order price change, not a holding-period return. A fund's "
        "published EFFECTIVE duration (reported as published_effective_duration_years when the "
        "input carries one) describes its actual portfolio and is not expected to equal the "
        "Macaulay figure."
    ),
    "assumptions.reinvestment": (
        "The shock lands immediately, is parallel across the curve, and every coupon received "
        "after it is reinvested at the shocked yield; whatever is left is sold at the horizon at "
        "the shocked price. No default, no credit migration, no change in the coupon."
    ),
    "assumptions.single_bond_approximation": (
        "The fund path models the whole fund as ONE bond: the average coupon as the coupon rate, "
        "the weighted average life as the maturity, and the published yield to maturity as the "
        "yield. That is an approximation — a fund is not a bond and a weighted average life is not "
        "a maturity, so the cash-flow timing here stands in for a portfolio that actually rolls."
    ),
}

# The paths as literals, NOT derived from DISCLOSURE_TEXTS. A parametrisation
# whose cases come from the dict it pins is a tautology one level up: deleting a
# key would drop its own case and leave the file green at 69 passed with that
# prose pinned only by identity, and the missing pin is invisible. The literals
# here shrink only if a person edits them, and
# test_the_disclosure_pin_sets_are_the_literal_ones holds them against the dict.
DISCLOSURE_PATHS = (
    "assumptions.headline_is_not_a_forecast",
    "assumptions.duration_meanings",
    "assumptions.reinvestment",
    "assumptions.single_bond_approximation",
)

# The three of the four a plain bond payload carries: single_bond_approximation is
# the fund path's, and claiming it on the bond path is its own test.
BOND_DISCLOSURE_PATHS = (
    "assumptions.headline_is_not_a_forecast",
    "assumptions.duration_meanings",
    "assumptions.reinvestment",
)

# Every key the output may carry, as literals, per path — measured from a real
# run, not derived from the script. Nothing else in this file would notice a new
# key: a payload could gain "recommendation": "buy" at the top level, or an
# advisory sentence in assumptions, and every other test here stays green. That
# is the one thing this skill may never emit, and it is the last of the three
# doors the pin designs leave open (an anchor misses an added sentence, identity
# misses an edited constant, and a set derived from the output misses an added
# key). Brittle on purpose: a legitimate new key means editing these tuples, and
# that edit is the reviewable event. Same trade as the full-text literals above.
BOND_TOP_KEYS = (
    "assumptions",
    "duration_years",
    "horizon_years",
    "locked_in_return_pct",
    "matched",
    "mismatch_cost_note",
    "modified_duration_years",
    "scenarios",
    "spread_pct",
    "value_paths",
)
FUND_TOP_KEYS = (
    "assumptions",
    "duration_years",
    "horizon_years",
    "locked_in_return_pct",
    "matched",
    "mismatch_cost_note",
    "modified_duration_years",
    "published_effective_duration_years",
    "scenarios",
    "spread_pct",
    "value_paths",
)
FUND_NOTE_TOP_KEYS = (
    "assumptions",
    "circularity_note",
    "duration_years",
    "horizon_years",
    "locked_in_return_pct",
    "matched",
    "mismatch_cost_note",
    "modified_duration_years",
    "published_effective_duration_years",
    "scenarios",
    "spread_pct",
    "value_paths",
)
BOND_ASSUMPTION_KEYS = (
    "duration_meanings",
    "frequency",
    "headline_is_not_a_forecast",
    "horizon_years",
    "input_shape",
    "match_tolerance",
    "reinvestment",
    "shock_grid_bp",
)
# The fund path with no duration_years in characteristics: the fund branch of
# assumptions() is taken, the published-duration branch is not.
FUND_ASSUMPTION_KEYS = (
    "duration_meanings",
    "frequency",
    "headline_is_not_a_forecast",
    "horizon_years",
    "input_shape",
    "match_tolerance",
    "reinvestment",
    "shock_grid_bp",
    "single_bond_approximation",
)
FUND_PUBLISHED_ASSUMPTION_KEYS = (
    "duration_meanings",
    "frequency",
    "headline_is_not_a_forecast",
    "horizon_years",
    "input_shape",
    "match_tolerance",
    "published_effective_duration_meaning",
    "reinvestment",
    "shock_grid_bp",
    "single_bond_approximation",
)
SCENARIO_ROW_KEYS = ("annualised_pct", "delta_yield_bp", "immediate_price_change_pct", "total_return_pct")
VALUE_PATH_KEYS = ("delta_yield_bp", "points")


@pytest.mark.parametrize("coupon,years,ytm", BONDS)
def test_macaulay_horizon_immunises_against_rate_moves(coupon, years, ytm):
    """The core claim of the skill, verified numerically on 2026-09-17.

    Hold a bond for its MACAULAY duration and the price loss from a rate rise
    is repaid by reinvesting coupons higher; the two cancel. Measured spread
    across +/-200 bp is under 0.1% for every bond above.

    Note it is Macaulay duration, NOT modified or effective duration, that is
    the immunisation horizon. Using BND's published effective duration of 5.75
    instead of its Macaulay 6.91 leaves an error of 58 bp and fails this test.
    """
    import horizon
    from second_opinion import bondmath
    d = bondmath.macaulay_duration(coupon, years, ytm)
    returns = [
        horizon.horizon_return(coupon, years, ytm, d, shock / 10000)
        for shock in (-200, -100, 0, 100, 200)
    ]
    for r in returns:
        assert r == pytest.approx(ytm, abs=0.004)


def test_a_short_horizon_is_much_more_sensitive_to_rates():
    import horizon
    from second_opinion import bondmath
    d = bondmath.macaulay_duration(0.0379, 8.2, 0.0531)
    short = [horizon.horizon_return(0.0379, 8.2, 0.0531, 1.0, s / 10000)
             for s in (-200, 200)]
    matched = [horizon.horizon_return(0.0379, 8.2, 0.0531, d, s / 10000)
               for s in (-200, 200)]
    assert (max(short) - min(short)) > (max(matched) - min(matched)) * 3


def test_spread_narrows_monotonically_toward_the_macaulay_point():
    import horizon
    spreads = []
    for h in (1.0, 3.0, 5.0, 6.91):
        rs = [horizon.horizon_return(0.0379, 8.2, 0.0531, h, s / 10000)
              for s in (-200, -100, 0, 100, 200)]
        spreads.append(max(rs) - min(rs))
    # measured 24.35%, 5.35%, 1.57%, 0.01%
    assert spreads == sorted(spreads, reverse=True)


@pytest.mark.parametrize("h", [0.25, 8.0, 8.2])
def test_horizons_near_or_past_the_last_coupon_do_not_crash(h):
    import horizon
    assert horizon.horizon_return(0.0379, 8.2, 0.0531, h, 0.0) == pytest.approx(0.0531, abs=0.002)


def _run(payload) -> dict:
    """Run the script as SKILL.md runs it and return its parsed stdout, or fail loudly."""
    out, code = _run_raw(payload)
    assert code == 0, out
    return out


def _run_raw(payload) -> tuple[dict, int]:
    proc = subprocess.run(
        [sys.executable, str(HORIZON)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout), proc.returncode


# --- the match duration is MACAULAY, and the three durations stay distinct ---


def test_the_reported_horizon_is_macaulay_duration_not_modified():
    """F35: the brief's own suite computes d itself, so it cannot see the
    script matching on modified or on a fund's published effective duration.
    6.9085 and 6.7298 are pinned literals for the BND-like proxy."""
    out = _run({**BOND_PROXY, "horizon_years": 8.2})
    assert out["duration_years"] == pytest.approx(PROXY_MACAULAY, abs=1e-3)
    assert out["duration_years"] != pytest.approx(PROXY_MODIFIED, abs=1e-3)
    assert out["modified_duration_years"] == pytest.approx(PROXY_MODIFIED, abs=1e-3)


def test_the_match_flag_is_measured_against_macaulay_not_the_alternatives():
    """The 20% windows overlap without nesting, so the flag can discriminate.

    For the proxy: Macaulay matches [5.527, 8.290], modified [5.384, 8.076],
    published effective [4.598, 6.898]. A horizon of 5.455 y is therefore
    matched by modified and NOT by Macaulay, and 5.0 y is matched by effective
    and by neither of the others.
    """
    assert _run({**BOND_PROXY, "horizon_years": 5.455})["matched"] is False
    assert _run({**BOND_PROXY, "horizon_years": 5.0})["matched"] is False
    assert _run({**BOND_PROXY, "horizon_years": PROXY_MACAULAY})["matched"] is True
    # The same 5.0 y horizon on the fund path: Macaulay is 7.268 there, so
    # 5.0 y is outside its window, but BND's published 5.748 would match it.
    assert _run({"characteristics": BND_CHARACTERISTICS, "horizon_years": 5.0})["matched"] is False


def test_the_two_meanings_of_duration_are_two_distinct_keys():
    """F42: fund.py's characteristics.duration_years is the PUBLISHED EFFECTIVE
    duration (5.748 here); the script's duration_years is the Macaulay of its
    single-bond approximation (7.268). Same key name one hop apart otherwise."""
    out = _run({"characteristics": BND_CHARACTERISTICS, "horizon_years": 6.91})
    assert out["duration_years"] == pytest.approx(7.268, abs=1e-3)
    assert out["published_effective_duration_years"] == pytest.approx(5.748, abs=1e-3)
    assert out["duration_years"] != pytest.approx(
        out["published_effective_duration_years"], abs=1e-3
    )
    assert out["modified_duration_years"] == pytest.approx(7.080, abs=1e-3)


def test_a_plain_bond_payload_carries_no_published_fund_duration():
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    assert "published_effective_duration_years" not in out
    assert "published_effective_duration_meaning" not in out["assumptions"]


# --- the input shapes ---


def test_a_fund_payload_is_read_as_percentages():
    """3.785% coupon and 5.31% yield must land as 0.03785 and 0.0531, not 3.785."""
    out = _run({"characteristics": BND_CHARACTERISTICS, "horizon_years": 6.91})
    assert out["assumptions"]["input_shape"] == "fund"
    # A yield read as 5.31 instead of 0.0531 would show up here as a wild
    # return; the locked-in figure is the market yield restated (5.3805%).
    assert out["locked_in_return_pct"] == pytest.approx(5.3805, abs=1e-3)


def test_a_bond_py_payload_names_the_parameters_it_does_not_echo_at_the_top_level():
    """F34: piping bond.py's output in must say which two parameters to pass
    alongside it, and must say where they already are.

    The message used to read "which does not echo the bond's own parameters",
    which sent the assistant to ask the user for figures it was already holding.
    Measured below against bond.py's real output rather than asserted in prose.
    """
    out, code = _run_raw(
        {"ytm": 0.0531, "macaulay_duration": 8.1, "price_map": [], "horizon_years": 6}
    )
    assert code == 2
    assert "bond.py" in out["error"]
    assert "coupon_rate, years" in out["error"]
    assert "assumptions" in out["error"]
    # The claim the message makes, checked against the script it is about: bond.py
    # DOES echo both, under assumptions, and neither is at the top level.
    bond_out = json.loads(
        subprocess.run(
            [sys.executable, str(SCRIPTS / "bond.py")],
            input=json.dumps({"coupon_rate": 0.045, "years": 10, "ytm": 0.0531}),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert bond_out["assumptions"]["coupon_rate"] == 0.045
    assert bond_out["assumptions"]["years"] == 10.0
    assert "coupon_rate" not in bond_out and "years" not in bond_out


def test_an_unrecognised_payload_is_rejected():
    out, code = _run_raw({"symbol": "BND", "horizon_years": 6})
    assert code == 2
    assert "coupon_rate" in out["error"] and "characteristics.coupon_pct" in out["error"]


def test_horizon_years_is_required_in_both_shapes():
    out, code = _run_raw(BOND_PROXY)
    assert code == 2
    assert "horizon_years" in out["error"] and "required" in out["error"]
    out, code = _run_raw({"characteristics": BND_CHARACTERISTICS})
    assert code == 2
    assert "horizon_years" in out["error"] and "required" in out["error"]


def test_a_non_positive_horizon_is_rejected():
    out, code = _run_raw({**BOND_PROXY, "horizon_years": 0})
    assert code == 2
    assert "horizon_years" in out["error"]


# --- valid JSON is not automatically valid input ---


@pytest.mark.parametrize("payload", [[1, 2, 3], None, 5, "abc"])
def test_a_valid_json_payload_that_is_not_an_object_is_rejected(payload):
    """A list, null, a number and a string all parse as JSON and none is an
    object, so payload.get() raised AttributeError: exit 1, traceback on stderr
    and stdout EMPTY — neither code 2 nor JSON, which is the one thing every exit
    here has to be. Rejected where input is validated, not by widening main's
    handler, which would also swallow a real attribute bug."""
    out, code = _run_raw(payload)
    assert code == 2
    assert "input must be a JSON object" in out["error"]


NON_FINITE_FIELDS = [
    ("bond", "coupon_rate"),
    ("bond", "years"),
    ("bond", "ytm"),
    ("bond", "horizon_years"),
    ("bond", "freq"),
    ("fund", "coupon_pct"),
    ("fund", "ytm_pct"),
    ("fund", "wal_years"),
]


@pytest.mark.parametrize("shape,field", NON_FINITE_FIELDS)
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_figure_is_rejected_rather_than_emitted(shape, field, bad):
    """json parses bare NaN/Infinity by default and json.dumps re-emits them, so
    stdout carried a token no strict parser accepts — with exit 0, which is worse
    than the rejection: the caller has no way to know the object is unusable."""
    if shape == "bond":
        payload = {**BOND_PROXY, "horizon_years": 6.91, "freq": 2, field: bad}
    else:
        payload = {
            "characteristics": {**BND_CHARACTERISTICS, field: bad},
            "horizon_years": 6.91,
        }
    out, code = _run_raw(payload)
    assert code == 2
    assert field in out["error"]
    assert "finite" in out["error"]


@pytest.mark.parametrize(
    "payload",
    [
        {"coupon_rate": 0.0, "years": 1.0, "ytm": 0.05, "horizon_years": 1e308},
        {"coupon_rate": 0.0, "years": 1e308, "ytm": 0.05, "horizon_years": 1.0},
        {"coupon_rate": 0.0379, "years": 8.2, "ytm": 1e300, "horizon_years": 6.91},
    ],
)
def test_an_absurd_but_finite_figure_is_rejected_with_json_not_a_traceback(payload):
    """Rejecting non-finite *inputs* does not cover this: every figure here is a
    finite JSON number. The compounding still overflows (exit 1, traceback, empty
    stdout) or computes a NaN ratio the renderer refuses — both of which are the
    same contract break as the non-object payload, and both must be JSON."""
    out, code = _run_raw(payload)
    assert code == 2
    assert "error" in out


@pytest.mark.parametrize(
    "shape,field,value",
    [
        ("bond", "ytm", 1e300),
        ("bond", "horizon_years", 1e6),
        ("fund", "ytm_pct", 1e300),
        ("fund", "horizon_years", 1e6),
    ],
)
def test_the_overflow_rejection_names_the_field_and_the_value(shape, field, value):
    """OverflowError alone reads "(34, 'Result too large')" — no field and no
    value, and in the fund shape not even which figure. The payload's own figures
    are named instead, as the caller wrote them: a fund's yield is
    characteristics.ytm_pct at 5.31, not the model's ytm at 0.0531."""
    if shape == "bond":
        payload = {**BOND_PROXY, "horizon_years": 6.91, field: value}
    elif field == "horizon_years":
        # horizon_years is a top-level field in both shapes; only the fund's
        # characteristics figures live under characteristics.
        payload = {"characteristics": BND_CHARACTERISTICS, "horizon_years": value}
    else:
        payload = {
            "characteristics": {**BND_CHARACTERISTICS, field: value},
            "horizon_years": 6.91,
        }
    out, code = _run_raw(payload)
    assert code == 2
    assert f"{field}={value:g}" in out["error"], out["error"]
    assert "no finite answer exists" in out["error"]


# One per path plus freq: the three fields whose product is a coupon count.
UNPRICEABLE_PERIOD_COUNTS = [
    # A maturity the list build would never finish: measured at 7efb0641 as a
    # wedge — no exit code, no JSON and empty stdout at any timeout.
    ({"coupon_rate": 0.04, "years": 1e8, "ytm": 0.05, "horizon_years": 8}, "years"),
    # The same through the fund shape's weighted average life.
    (
        {"characteristics": {**BND_CHARACTERISTICS, "wal_years": 1e8}, "horizon_years": 6.91},
        "characteristics.wal_years",
    ),
    # And through freq, which multiplies the count just as directly.
    (
        {"coupon_rate": 0.04, "years": 30, "ytm": 0.05, "horizon_years": 8, "freq": 10**9},
        "years",
    ),
    # One period over the bound, so the bound's own value is pinned rather than
    # whatever a rounded float happens to give: 1000 x 1001 = 1,001,000.
    (
        {
            "coupon_rate": 0.0379,
            "years": 1000,
            "ytm": 0.0531,
            "horizon_years": 6.91,
            "freq": 1001,
        },
        "years",
    ),
]


@pytest.mark.parametrize("payload,label", UNPRICEABLE_PERIOD_COUNTS)
def test_an_unpriceable_coupon_count_is_rejected_with_json(payload, label):
    """The one rejection this script could not deliver: it never returned.

    bondmath.cashflows materialises every period as a list entry before anything
    is discounted, so years x freq is allocated up front and a large enough
    figure allocates until the process is killed. A hang is worse than an
    overflow: it prints nothing and never returns a status, so a
    caller waits forever instead of reading an error. The bound is a RESOURCE
    bound, not a domain rule — a million payments is 500,000 years of
    semi-annual coupons — and every maturity above it already rejected by
    overflow, so nothing that answers today is refused by it.
    """
    out, code = _run_raw(payload)
    assert code == 2
    assert "error" in out and out["error"]
    assert f"{label} x freq" in out["error"], out["error"]
    assert "coupon periods" in out["error"], out["error"]
    # The message names both figures and the bound, not just the fact of refusal.
    assert f"freq ({payload.get('freq', 2)})" in out["error"], out["error"]
    assert "1,000,000" in out["error"], out["error"]


def test_a_long_but_priceable_maturity_still_answers():
    """The bound must not become a domain rule: a 100-year bond prices.

    19.4012 is that bond's Macaulay duration, checked against exact Fraction
    arithmetic (19.401203…), and a century bond is 200 periods — far inside a
    bound chosen so that nothing real is refused.
    """
    out = _run({**BOND_PROXY, "years": 100, "horizon_years": 6.91})
    assert out["matched"] is False
    assert out["duration_years"] == pytest.approx(19.4012, abs=1e-3)


@pytest.mark.parametrize("field", ["coupon_pct", "ytm_pct", "wal_years"])
def test_a_null_fund_figure_is_named_as_missing_not_modelled(field):
    """F37: fund.py now emits null for a figure the page did not carry, so null
    must read as absent — not as a TypeError, and not as a confident zero."""
    characteristics = {**BND_CHARACTERISTICS, field: None}
    out, code = _run_raw({"characteristics": characteristics, "horizon_years": 6.91})
    assert code == 2
    assert f"characteristics.{field}" in out["error"]
    assert "missing" in out["error"]


def test_a_null_bond_parameter_is_named_as_missing_not_modelled():
    out, code = _run_raw({**BOND_PROXY, "coupon_rate": None, "horizon_years": 6.91})
    assert code == 2
    assert "coupon_rate" in out["error"]
    assert "missing" in out["error"]


def test_freq_can_be_given_for_a_non_semi_annual_bond():
    """freq defaults to 2; an annual-pay bond has a longer Macaulay duration."""
    out = _run({**BOND_PROXY, "horizon_years": 6.91, "freq": 1})
    assert out["duration_years"] == pytest.approx(6.9898, abs=1e-3)
    assert out["assumptions"]["frequency"] == 1
    # At annual compounding the locked-in return IS the quoted yield, because
    # no compounding convention separates them.
    assert out["locked_in_return_pct"] == pytest.approx(5.31, abs=1e-3)


# --- the headline: what it is, and what it is not ---


def test_the_scenarios_sweep_the_shock_grid_and_the_spread_is_their_range():
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    assert [row["delta_yield_bp"] for row in out["scenarios"]] == [-200, -100, 0, 100, 200]
    assert out["spread_pct"] == pytest.approx(0.014, abs=1e-3)
    assert out["locked_in_return_pct"] == pytest.approx(5.3805, abs=1e-4)
    # The middle row is the headline: the +/- rows are the same return under a
    # rate move that has not happened.
    assert out["locked_in_return_pct"] == out["scenarios"][2]["annualised_pct"]


def test_the_scenario_returns_are_the_ones_the_arithmetic_gives():
    """Pinned for the -200 bp row, from a formulation the script does not use:
    compound the price AT the new yield forward at the new yield. 43.6392% over
    6.91 years is 5.3805% a year."""
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    middle = out["scenarios"][2]
    assert middle["total_return_pct"] == pytest.approx(43.6392, abs=1e-3)
    assert middle["annualised_pct"] == pytest.approx(5.3805, abs=1e-4)
    down_200 = out["scenarios"][0]
    assert down_200["annualised_pct"] == pytest.approx(5.3932, abs=1e-4)
    assert down_200["total_return_pct"] == pytest.approx(43.7594, abs=1e-3)


def test_the_short_horizon_spread_is_the_wide_one():
    out = _run({**BOND_PROXY, "horizon_years": 1.0})
    assert out["spread_pct"] == pytest.approx(24.3481, abs=1e-3)
    assert out["matched"] is False


def test_the_spread_ladder_is_the_measured_one():
    """The brief's ladder test asserts only that the rungs descend, and every
    mis-scaled per-period rate I tried keeps them descending. Pin the rungs:
    measured 24.35%, 5.35%, 1.57%, 0.01% at 1, 3, 5 and 6.91 years."""
    ladder = [
        _run({**BOND_PROXY, "horizon_years": h})["spread_pct"]
        for h in (1.0, 3.0, 5.0, 6.91)
    ]
    assert ladder == pytest.approx([24.3481, 5.3517, 1.5671, 0.014], abs=2e-3)


def test_the_output_says_the_headline_is_the_market_yield_restated():
    """F40: the headline is implied by today's price, and must say so."""
    import horizon
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    note = out["assumptions"]["headline_is_not_a_forecast"]
    assert note == horizon._HEADLINE_NOTE
    assert "implied by today's price" in note
    assert "not a forecast" in note


def test_a_fund_payloads_circularity_note_is_carried_through_unchanged():
    """F40: pass fund.py's own note through so the page keeps one voice."""
    out = _run(
        {
            "characteristics": BND_CHARACTERISTICS,
            "horizon_years": 6.91,
            "circularity_note": "PINNED: reproduces the published yield by construction.",
        }
    )
    assert out["circularity_note"] == "PINNED: reproduces the published yield by construction."


def test_a_bond_payload_gets_no_invented_circularity_note():
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    assert "circularity_note" not in out


def test_the_fund_path_discloses_the_single_bond_approximation():
    """F36: a fund is not a bond and a weighted average life is not a maturity."""
    import horizon
    out = _run({"characteristics": BND_CHARACTERISTICS, "horizon_years": 6.91})
    note = out["assumptions"]["single_bond_approximation"]
    assert note == horizon._APPROXIMATION_NOTE
    assert "whole fund as ONE bond" in note
    assert "weighted average life as the maturity" in note
    assert "approximation" in note


def test_the_bond_path_claims_no_single_bond_approximation():
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    assert "single_bond_approximation" not in out["assumptions"]


def test_the_assumptions_state_the_reinvestment_rule():
    import horizon
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    note = out["assumptions"]["reinvestment"]
    assert note == horizon._REINVESTMENT_NOTE
    assert "reinvested at the shocked yield" in note
    assert "No default" in note


def _emitted(payload, path: str) -> str:
    """The string the payload carries at a dotted output path.

    Keyed by path rather than by constant name so a failure says where the text
    is emitted, and so a key dropped at the dict site fails here rather than
    passing as an absence.
    """
    node: object = payload
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            pytest.fail(f"{path} is no longer emitted")
        node = node[part]
    assert isinstance(node, str)
    return node


def test_the_disclosure_pin_sets_are_the_literal_ones():
    """The parametrisation must not be able to shrink with the dict it pins.

    With `parametrize("path", sorted(DISCLOSURE_TEXTS))` a deleted key dropped its
    own case: the file stayed green at 69 passed and that string was pinned by
    identity alone, which is exactly the hole the full texts close. The path
    tuples above are literals now, and this holds them against the dict, so the
    two can only move together and deliberately.
    """
    assert set(DISCLOSURE_PATHS) == set(DISCLOSURE_TEXTS)
    assert len(DISCLOSURE_PATHS) == 4
    assert set(BOND_DISCLOSURE_PATHS) == set(DISCLOSURE_PATHS) - {
        "assumptions.single_bond_approximation"
    }
    assert len(BOND_DISCLOSURE_PATHS) == 3


@pytest.mark.parametrize("path", DISCLOSURE_PATHS)
def test_every_disclosure_string_matches_its_pinned_full_text(path):
    """All four disclosure strings, word for word, against this file's own copies.

    Three pin designs, each leaving a site open: an anchor misses a sentence
    added beside intact wording, identity against the module constant moves with
    the constant, and the two together still missed the BUY sentence inserted
    into _HEADLINE_NOTE. The only expectation that cannot move with the code is a
    copy of the text, so there is one here — DISCLOSURE_TEXTS — and the payload
    has to equal it. Replacing, adding to, deleting or truncating any of the
    four, at the constant or at the emission site, fails below naming the path.
    """
    out = _run({"characteristics": BND_CHARACTERISTICS, "horizon_years": 6.91})
    assert _emitted(out, path) == DISCLOSURE_TEXTS[path], f"{path} is not the pinned text"


@pytest.mark.parametrize("path", BOND_DISCLOSURE_PATHS)
def test_the_bond_path_emits_the_same_disclosures(path):
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    assert _emitted(out, path) == DISCLOSURE_TEXTS[path], f"{path} is not the pinned text"


# --- the output carries exactly these keys, on each path ---


def test_the_output_carries_exactly_the_pinned_keys():
    """Every key, per path, against the literals above.

    The three pin designs in this file all pin VALUES, so the key set was the
    open door: an extra key survives all of them. What it may not survive is this
    — no advisory key in assumptions, and no recommendation beside the return.
    The bond, fund and fund-with-circularity-note paths legitimately differ
    (published_effective_duration_years, single_bond_approximation and
    published_effective_duration_meaning are the fund's; circularity_note is
    fund.py's own note passed through), so each is pinned separately, and the
    scenario rows are pinned too since they are built from a dict of their own.
    """
    bond = _run({**BOND_PROXY, "horizon_years": 6.91})
    fund = _run({"characteristics": BND_CHARACTERISTICS, "horizon_years": 6.91})
    noted = _run(
        {
            "characteristics": BND_CHARACTERISTICS,
            "horizon_years": 6.91,
            "circularity_note": "PASSED THROUGH",
        }
    )
    unpublished = _run(
        {
            "characteristics": {
                k: v for k, v in BND_CHARACTERISTICS.items() if k != "duration_years"
            },
            "horizon_years": 6.91,
        }
    )
    assert tuple(sorted(bond)) == BOND_TOP_KEYS
    assert tuple(sorted(fund)) == FUND_TOP_KEYS
    assert tuple(sorted(noted)) == FUND_NOTE_TOP_KEYS
    assert tuple(sorted(bond["assumptions"])) == BOND_ASSUMPTION_KEYS
    assert tuple(sorted(fund["assumptions"])) == FUND_PUBLISHED_ASSUMPTION_KEYS
    assert tuple(sorted(noted["assumptions"])) == FUND_PUBLISHED_ASSUMPTION_KEYS
    assert tuple(sorted(unpublished["assumptions"])) == FUND_ASSUMPTION_KEYS
    for out in (bond, fund, noted, unpublished):
        for row in out["scenarios"]:
            assert tuple(sorted(row)) == SCENARIO_ROW_KEYS


def test_the_mismatch_note_states_the_gap_and_its_direction():
    """The direction word is the sentence's whole content: 'short of' -> 'past'
    inverted what the note says and left the file at 37 passed.

    This is the short-of branch only. The past branch is its own test below, and
    until that existed the whole expression ``'past' if gap > 0 else 'short of'``
    could collapse to a single word with no test here or in the brief's suite
    failing — the inversion, mirrored, in a sentence a user reads.
    """
    out = _run({**BOND_PROXY, "horizon_years": 3.0})
    assert out["mismatch_cost_note"] == (
        "The horizon of 3 years is 3.91 years short of the Macaulay duration "
        "(6.91 years), so the return is not locked in: a parallel move of "
        "+/-200 bp moves the annualised outcome by 5.35 percentage points, "
        "and that spread is the cost of the mismatch."
    )


def test_the_mismatch_note_says_past_when_the_horizon_is_past_the_duration():
    """The other branch, word for word, at a reachable horizon that must say it.

    `matched` is False at 9.0 years (the Macaulay window ends at 8.29), so the
    branch runs and the direction is genuinely past. Collapsing the conditional
    to one word — {"short of" if gap > 0 else "short of"} — left the entire
    1515-test suite green and made this sentence mean its opposite.
    """
    out = _run({**BOND_PROXY, "horizon_years": 9.0})
    assert out["matched"] is False
    assert out["mismatch_cost_note"] == (
        "The horizon of 9 years is 2.09 years past the Macaulay duration "
        "(6.91 years), so the return is not locked in: a parallel move of "
        "+/-200 bp moves the annualised outcome by 0.95 percentage points, "
        "and that spread is the cost of the mismatch."
    )


def test_the_matched_mismatch_note_says_the_return_is_locked_in():
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    assert out["mismatch_cost_note"] == (
        "The horizon of 6.91 years is within 20% of the Macaulay duration "
        "(6.91 years), so the return is largely locked in: a parallel move of "
        "+/-200 bp moves the annualised outcome by only 0.01 percentage points."
    )


def test_the_docstring_example_is_the_output_the_script_actually_gives():
    """The docstring is the contract a reader copies, and no test saw it drift.

    It showed matched:true beside spread_pct 24.3481 — a pair that cannot occur,
    since 24.3481 is the 1-year spread and 1 year is not matched — and a -200 bp
    row showing a LOSS at a matched horizon, which is the opposite of the
    immunity the module exists to demonstrate. Every figure it quotes is checked
    against a real run here, so a stale example fails instead of shipping.
    """
    import horizon
    doc = horizon.__doc__
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    assert out["matched"] is True
    assert out["spread_pct"] == 0.014
    assert '"matched": true,' in doc
    assert f'"spread_pct": {out["spread_pct"]},' in doc
    for key in (
        "horizon_years",
        "duration_years",
        "modified_duration_years",
        "locked_in_return_pct",
    ):
        assert f'"{key}": {out[key]},' in doc, f"the docstring's {key} is not this run's"
    down_200 = out["scenarios"][0]
    assert f'"total_return_pct": {down_200["total_return_pct"]},' in doc
    assert f'"annualised_pct": {down_200["annualised_pct"]}' in doc


def test_the_assumptions_say_which_duration_immunises():
    import horizon
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    note = out["assumptions"]["duration_meanings"]
    assert note == horizon._DURATION_MEANINGS_NOTE
    assert "MACAULAY" in note
    assert "modified_duration_years" in note
    assert "published_effective_duration_years" in note


def test_the_fund_path_explains_the_two_meanings_of_duration_years():
    """F42: the input's characteristics.duration_years and the output's
    duration_years are different quantities and must not look interchangeable."""
    out = _run({"characteristics": BND_CHARACTERISTICS, "horizon_years": 6.91})
    note = out["assumptions"]["published_effective_duration_meaning"]
    assert "characteristics.duration_years" in note
    assert "published effective duration" in note
    assert "not expected to match" in note


def test_the_published_duration_prose_is_the_pinned_text():
    """The last prose leaf with no full-text pin of its own.

    Its three anchors above survive any sentence inserted beside them, and no
    identity assertion names it, so advice — "consider trimming the fund" —
    could be added to this string and the file stayed green. The rendered value
    is copied here for BND's recorded characteristics at a 6.91 year horizon:
    published effective 5.748, Macaulay 7.27, 26% apart by construction.
    """
    out = _run({"characteristics": BND_CHARACTERISTICS, "horizon_years": 6.91})
    assert out["assumptions"]["published_effective_duration_meaning"] == (
        "The input's characteristics.duration_years is the fund's published "
        "effective duration (5.748 years) and is passed through unchanged as "
        "published_effective_duration_years. This script's duration_years is the "
        "Macaulay duration of the single-bond approximation above (7.27 years). "
        "They are different quantities and are not expected to match: here they "
        "differ by 26% by design."
    )


# --- the production import path ---


def test_the_script_runs_under_a_bare_environment():
    """F19: SKILL.md runs a script with no PYTHONPATH from an unrelated cwd.
    Empty stdin is invalid input, so exit 2 with JSON on stdout is the pass —
    the assertion is that the process got far enough to run at all."""
    proc = subprocess.run(
        [sys.executable, str(HORIZON)],
        input="",
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},  # no PYTHONPATH — that is the point
        cwd="/",
    )
    assert "ModuleNotFoundError" not in proc.stderr
    assert proc.returncode == 2
    assert "error" in json.loads(proc.stdout)


def test_the_script_imports_second_opinion_with_no_pythonpath():
    # F19/F27: import the real file (its __main__ guard means nothing is read)
    # so a missing sys.path bootstrap fails here instead of on a user's machine.
    probe = (
        "import importlib.util; "
        f"spec = importlib.util.spec_from_file_location('horizon_probe', {str(HORIZON)!r}); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},  # no PYTHONPATH — that is the point
        cwd="/",
    )
    assert "No module named 'second_opinion'" not in proc.stderr
    assert proc.returncode == 0, proc.stderr


# I2: references/bond-math.md's matched-band paragraph said the +/-200 bp spread runs "to about
# 0.96 at the edge". 0.96 is an INTERIOR point (H ~ 5.60); both edges are worse than the figure
# the sentence gave as the worst case, which is the wrong direction for a sentence whose purpose
# is to show how bad a matched horizon can get. Re-measured below, so the prose cannot drift from
# the script again: each row is (horizon_years, spread_pct) for the 8.2-year bond in that file.
MATCHED_BAND = (
    (6.9085, 0.0136),  # the centre: the Macaulay duration itself
    (5.5269, 1.0262),  # the lower edge of the 20% band, and the worst case inside it
    (8.2902, 0.6847),  # the upper edge: the band is not symmetric about its centre
)


def test_the_matched_band_figures_the_reference_quotes_are_the_measured_ones():
    reference = (
        PLUGIN_ROOT / "skills" / "fixed-income" / "references" / "bond-math.md"
    ).read_text()
    for horizon_years, spread_pct in MATCHED_BAND:
        out = _run({**BOND_PROXY, "horizon_years": horizon_years})
        assert out["spread_pct"] == pytest.approx(spread_pct, abs=1e-4), horizon_years
        # ...and the reference quotes those same two numbers, not a remembered pair.
        assert f"H = {horizon_years:g}" in reference
        assert f"{spread_pct:g}" in reference or f"{spread_pct:.3f}" in reference
    # "`matched` true at both" is checked rather than asserted in prose. The band's real edges are
    # 0.8x and 1.2x the UNROUNDED Macaulay duration (6.908517184453038), so the four-decimal
    # horizons the reference quotes are the first rounded values inside it: 5.5268 falls 1.4e-5
    # years short of the lower edge and is NOT matched, which is why the reference says 5.5269.
    for horizon_years, _ in MATCHED_BAND:
        assert _run({**BOND_PROXY, "horizon_years": horizon_years})["matched"] is True
    assert _run({**BOND_PROXY, "horizon_years": 5.5268})["matched"] is False

    # SKILL.md quotes the same centre and lower-edge figures in its own sentence, and until this
    # line nothing pinned them: changing SKILL.md's 0.0136 to 0.014 left all 1592 tests green while
    # bond-math.md's twin died. A figure that appears in two artefacts needs checking in both, or
    # the unchecked copy is the one that drifts.
    skill_md = (PLUGIN_ROOT / "skills" / "fixed-income" / "SKILL.md").read_text()
    centre_pct, lower_edge_pct = MATCHED_BAND[0][1], MATCHED_BAND[1][1]
    assert f"{centre_pct:g} percentage points at the centre" in skill_md
    assert f"{lower_edge_pct:g} at the lower edge" in skill_md


# --- value paths: what $1 is worth along the way, under a rate move today ---


def test_value_paths_cover_down_one_point_unchanged_and_up_one_point():
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    assert [row["delta_yield_bp"] for row in out["value_paths"]] == [-100, 0, 100]
    for row in out["value_paths"]:
        assert tuple(sorted(row)) == VALUE_PATH_KEYS
        years = [pt["years"] for pt in row["points"]]
        assert years[0] == 0 and years[-1] == 6.91
        assert years == sorted(years) and len(set(years)) == len(years)


def test_a_value_path_starts_at_the_repriced_bond_and_ends_at_the_scenario_total():
    """Day 0 is the price change a rate move causes at once; the last point is the
    same total return the matching scenario row reports."""
    from second_opinion import bondmath

    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    by_shock = {row["delta_yield_bp"]: row for row in out["scenarios"]}
    base = bondmath.price_from_yield(0.0379, 8.2, 0.0531)
    for row in out["value_paths"]:
        shock = row["delta_yield_bp"]
        start, end = row["points"][0]["value"], row["points"][-1]["value"]
        moved = bondmath.price_from_yield(0.0379, 8.2, 0.0531 + shock / 10000.0)
        assert start == pytest.approx(moved / base, abs=1e-6)
        assert end == pytest.approx(1 + by_shock[shock]["total_return_pct"] / 100, abs=1e-5)
        assert by_shock[shock]["immediate_price_change_pct"] == pytest.approx((moved / base - 1) * 100, abs=1e-4)
    assert by_shock[0]["immediate_price_change_pct"] == 0


def test_the_paths_cross_near_a_matched_horizon():
    """The picture the page draws: a rise in rates costs at once and is earned back by
    the horizon, so the paths start far apart and end close together."""
    out = _run({**BOND_PROXY, "horizon_years": 6.91})
    starts = [row["points"][0]["value"] for row in out["value_paths"]]
    ends = [row["points"][-1]["value"] for row in out["value_paths"]]
    assert starts[0] > starts[1] > starts[2]
    assert max(ends) - min(ends) < (max(starts) - min(starts)) / 50


def test_value_paths_step_every_coupon_period():
    out = _run({**BOND_PROXY, "horizon_years": 3.2})
    years = [pt["years"] for pt in out["value_paths"][0]["points"]]
    assert years == [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.2]


def test_a_long_horizon_path_is_sampled_not_built_per_coupon():
    """500 years is 1,000 coupon dates; the path is capped, and still ends at the horizon."""
    out = _run({**BOND_PROXY, "horizon_years": 500})
    for row in out["value_paths"]:
        assert len(row["points"]) <= 122
        assert row["points"][-1]["years"] == 500
