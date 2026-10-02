"""scripts/fund.py: the decomposition, its scrape layer and the import path."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FUND = PLUGIN_ROOT / "skills" / "fixed-income" / "scripts" / "fund.py"
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "fixed-income" / "scripts"))


def test_blended_spread_weights_sectors():
    import fund

    sectors = {
        "Treasury/Agency": (49.2, 0.0),
        "Gov Mortgage-Backed": (19.3, 35.0),
        "Industrial": (14.8, 78.0),
        "Finance": (8.1, 78.0),
        "Foreign": (3.5, 78.0),
        "Utilities": (2.6, 78.0),
        "CMBS": (1.5, 80.0),
        "ABS": (0.5, 60.0),
        "Other": (0.5, 60.0),
    }
    assert fund.blended_spread_bp(sectors) == pytest.approx(31.2, abs=0.5)
    # These weights happen to sum to 100, which hides whether the function
    # normalises. Halving every weight is the same portfolio, so it must still
    # give 31.2 bp; a version that skips the division reports 15.6.
    halved = {name: (w / 2.0, s) for name, (w, s) in sectors.items()}
    assert fund.blended_spread_bp(halved) == pytest.approx(31.2, abs=0.5)


def test_par_per_share_reproduces_the_distribution():
    """The BND regression case from 2026-09-17.

    Published coupon 3.79% and YTM 5.31% against a $71.43 NAV implies about
    $78.42 of face value per share, which at 3.79% throws off $2.97 a year —
    within 2% of the actual $3.035 of distributions.
    """
    import fund

    buckets = [(0.2, 0.5), (44.8, 3.0), (34.5, 7.5), (3.7, 12.5), (5.5, 17.5), (4.3, 22.5), (6.9, 28.0)]
    par = fund.par_per_share(nav=71.43, coupon_rate=0.0379, ytm=0.0531, buckets=buckets)
    assert par == pytest.approx(78.42, abs=0.5)
    assert 0.0379 * par == pytest.approx(3.035, rel=0.05)


def test_bucket_cashflows_reproduce_published_wal():
    """Vanguard publishes 8.2 years; the bucket model should land within 0.2."""
    import fund

    buckets = [(0.2, 0.5), (44.8, 3.0), (34.5, 7.5), (3.7, 12.5), (5.5, 17.5), (4.3, 22.5), (6.9, 28.0)]
    assert fund.weighted_average_life(buckets) == pytest.approx(8.2, abs=0.2)
    # A 0.2 band cannot see the normalisation: the weights sum to 99.9, and
    # dividing by a hard-coded 100 gives 8.257 — inside the band and wrong.
    # 825.7 / 99.9 = 8.265265... is the number the function must produce.
    assert fund.weighted_average_life(buckets) == pytest.approx(8.26527, abs=0.001)
    # The name of this test is about the cash flows, so pin them too: 28 years
    # semi-annual is 56 payments whatever the weights, and the portfolio's total
    # undiscounted payout is par (100) plus one coupon per period, weighted.
    # The published weights sum to 99.9, not 100, and the function normalises by
    # their actual total: the weighted period count is 1651.4/99.9 = 16.5305 and
    # the coupons 0.0379/2 x 16.5305 = 0.31325, for 131.3254 per 100 of par.
    # Assuming the weights summed to 100 gives 131.294; the 0.031 between them is
    # exactly what the normalisation does, so the tight tolerance below is what
    # stops a "divide by 100" mutant.
    cashflows = fund.bucket_cashflows(buckets, 0.0379)
    assert len(cashflows) == 56
    assert sum(amount for _, amount in cashflows) == pytest.approx(131.3254, abs=0.001)


# --------------------------------------------------------------- page fixtures
#
# A trimmed hand-built page in the shape the script reads: one JSON object per
# container, embedded in a script tag the way the product page embeds them. The
# figures are AGG's for 2026-09-16. `_DECOY` carries an unbalanced brace inside
# a *string* before its own anchor and the fundamentals block carries one inside
# a label, so the brace walk has something to get wrong; `_BROKEN` is a block
# whose anchor is there and whose JSON is not.

_DECOY = '{"label":"an unbalanced { inside a string","fullName":"decoy.block","value":1}'
_BROKEN = '{"fullName":"broken.block","value":}'
_FUNDAMENTALS = (
    '{"fullName":"fundamentalsAndRisk.default","dataPointsByNameMap":{'
    '"yieldToMaturity":{"value":5.31,"asOfDate":20260916},'
    '"fxHedgedYield":{"value":4.9,"asOfDate":20260916},'
    '"weightedAvgCouponFi":{"value":3.78523,"asOfDate":20260916},'
    '"modelOad":{"value":5.74831,"asOfDate":20260916},'
    '"thirtyDaySecYield":{"value":"n/a","asOfDate":20260916},'
    '"secYield":{"value":4.8403,"asOfDate":20260916},'
    '"weightedAvgLife":{"value":8.19,"asOfDate":20260916},'
    '"notes":{"value":1,"label":"a } brace and a \\" quote in a label"}}}'
)
_FEES = '{"fullName":"fundHeader.fees.expr","value":0.03}'
_NAV = '{"fullName":"fundHeader.fundNav.navAmount","value":96.287577,"asOfDate":20260917}'
# The same block with both names for the SEC yield gone: a page that parses and
# has simply stopped publishing a figure the model needs.
_FUNDAMENTALS_NO_SEC = (
    '{"fullName":"fundamentalsAndRisk.default","dataPointsByNameMap":{'
    '"yieldToMaturity":{"value":5.31,"asOfDate":20260916},'
    '"weightedAvgCouponFi":{"value":3.78523,"asOfDate":20260916},'
    '"modelOad":{"value":5.74831,"asOfDate":20260916},'
    '"weightedAvgLife":{"value":8.19,"asOfDate":20260916}}}'
)
# The fundamentals block itself cut off mid-object: the anchor is there, the
# JSON never closes.
_FUNDAMENTALS_BROKEN = '{"fullName":"fundamentalsAndRisk.default","dataPointsByNameMap":{'


def _page(*blocks: str) -> str:
    """The blocks as one document, the way the product page carries them."""
    return "<html><script>window.data = [" + ",".join(blocks) + "];</script></html>"


FULL_PAGE = _page(_DECOY, _BROKEN, _FUNDAMENTALS, _FEES, _NAV)
NO_NAV_PAGE = _page(_DECOY, _BROKEN, _FUNDAMENTALS, _FEES)
NO_FEE_PAGE = _page(_DECOY, _BROKEN, _FUNDAMENTALS, _NAV)

# Every disclosure string the payload carries, in full, keyed by the output path
# that emits it. Nothing here is derived from fund.py, on purpose: an expectation
# that is built out of the module moves with the module, and an anchor on a
# phrase cannot see a sentence added beside it. Hoisting these strings
# into module constants so that the dict site could be pinned by identity
# only moved the edit site to the constants, where four of them could be
# emptied and any of them could be added to with all 1441 tests still green. So
# the text itself lives here, word for word, and the payload has to match it.
#
# The cost is real and intended: a legitimate prose edit is made in two places,
# and this is the second one. The failure names the path that drifted and prints
# both texts. The three templates (`expense_source`, `nav_source`,
# `index_proxy`) are pinned as rendered for the BND payload, the same shape the
# anchor assertions use ("the proxy's (AGG) published figure").
DISCLOSURE_TEXTS = {
    "circularity_note": (
        "The calculated yield is built from today's Treasury curve and today's credit spreads, "
        "which are themselves market prices. It reproduces the published yield by construction "
        "and is NOT evidence of mispricing. Use it to check the arithmetic, not to disagree with "
        "the market."
    ),
    "characteristics.wal_source": (
        "wal_years is the bucket model's weighted average of the index's static maturity bands, "
        "the static weights assumptions.maturity_buckets lists, not the fund's own portfolio's "
        "weighted average life; it is the model's input, so read it as the assumption behind the "
        "yield, and assumptions.wal_check for how it compares with the published figure."
    ),
    "assumptions.note": (
        "The bucket model prices one par bond per maturity band, weighted by the band's share of "
        "the index. It is an approximation of a real portfolio's cash flows, which is why the "
        "reproduced yield is compared with a tolerance rather than asserted equal. Buckets and "
        "sector weights are static structural inputs, not live holdings: they are refreshed with "
        "the skill, not with every run."
    ),
    "assumptions.spread_convention": (
        "The blended spread is a discount margin over the Treasury zero curve, quoted as an "
        "annualised rate: each cash flow is divided by (1 + spread/freq)^(t*freq), not shifted "
        "along the curve. The two agree to first order, the residual being the cross term "
        "curve_rate * spread / freq — about 2 bp at a 4% curve and a 1% spread — so the spread "
        "discounts a little harder than the parallel shift a reader may expect."
    ),
    "assumptions.comparison": (
        "treasury_equivalent_pct is the flat yield of these same cash flows priced on the "
        "Treasury curve alone. calculated_ytm_pct adds the blended spread and subtracts the "
        "expense ratio, so it is net of fees while the published yield to maturity is gross. The "
        "expense ratio is therefore one component of the gap between them — but only one, and on "
        "its own it is not what the gap should be: the bucket model reproduces a published yield "
        "to maturity to roughly ±25 bp, and that residual is model error, not the fee. See "
        "gap_expectation for what a gap of a given size means."
    ),
    "assumptions.gap_expectation": (
        "gap_bp is signed calculated_ytm_pct minus published_ytm_pct, in basis points: negative "
        "means the model produced less yield than the fund publishes, positive means more. The "
        "part of it with a reason is the fee — calculated is net of it, published is gross — and "
        "that is 3 to 7 bp. The rest is the bucket model's own error: measured over the seven "
        "funds this skill covers on 2026-09-17, the gap ran from -23.9 bp to +22.6 bp. So the "
        "bucket model reproduces a published YTM to roughly ±25 bp, and a gap of that size is "
        "model error, not the fee, and not a discrepancy — which is not to say the model is "
        "right. The model's own construction implies a centre of about minus the expense ratio, "
        "not a boundary, and that is a statement about the construction rather than about the "
        "data: over those same seven funds the measured gaps centred on +0.57 bp, so read the "
        "construction's centre as where the model would sit if it were exact, not as where yields "
        "are. A gap outside that ±25 bp band is where the model stops explaining it, which still "
        "does not make it the market's error."
    ),
    "assumptions.expense_source": (
        "The expense ratio is the proxy's (AGG) published figure, read from the page's fund "
        "header. Unlike the NAV and the daily figures, that field carries no as-of date on the "
        "page, so it cannot be dated: it is the current prospectus fee, which changes when the "
        "fund reprices rather than daily."
    ),
    "assumptions.nav_source": (
        "The NAV is the proxy's (AGG), not the fund's own: iShares is the only publisher whose "
        "figures are fetchable, and the two funds' share prices differ. It carries its own as-of "
        "date (as_of.nav), which is often a day newer than the figures it is paired with "
        "(as_of.fund). par_per_share scales with the proxy's NAV, and that scaling is exact only "
        "where the fund tracks the proxy's index (BND); elsewhere it is the proxy's share price "
        "applied to the proxy's cash flows, so read par_per_share as an approximation of the same "
        "kind."
    ),
    "assumptions.index_proxy": (
        "The iShares AGG page is the index proxy this skill fetches for BND, and the figures "
        "characteristics carries from it are the page's: its yield to maturity, average coupon, "
        "published duration and SEC yield — index figures, not the fund's own holding-level "
        "figures. characteristics.wal_years is not one of them: it is the bucket model's own "
        "weighted average of the static index bands, as characteristics.wal_source says, which is "
        "why assumptions.wal_check sets it beside the page's published figure. Everything else "
        "the model reports is this script's own arithmetic on the proxy's figures — the "
        "treasury-equivalent yield, the blended spread, the calculated yield, the gap, "
        "par_per_share and price_map — and as_of.curve is the Treasury curve, not the page's. BND "
        "tracks the same Bloomberg US Aggregate index as AGG, so the figures are the fund's "
        "index's own."
    ),
    "assumptions.price_map_note": (
        "price_map re-prices the same model cash flows at 21 flat yields 25 bp apart, centred on "
        "the published yield to maturity, so there is one row per 25 bp of yield from -250 bp to "
        "+250 bp. The price is per 100 of par of the model portfolio, not per share and not the "
        "fund's share price: only on the row centred on the published yield does par_per_share "
        "times that row over 100 come back to the fund's NAV per share, and even there only to "
        "the model's own error and rounding. On the other twenty rows the relation does not hold "
        "at all, so a NAV recomputed from one of them is simply wrong. The rows come from the "
        "same circular construction as calculated_ytm_pct — today's curve and today's spreads — "
        "so no row is a fair value, a target or a forecast; each is what these cash flows would "
        "be worth if the whole portfolio yielded that much."
    ),
}

# index_proxy's fourth parameter is the index clause, and each clause is a
# disclosure in its own right — the BIV clause is what stops a reader taking the
# aggregate's figures for BIV's own. Pinned the same way, as the whole map, so a
# clause added for a third fund (which would change that fund's index_proxy) and
# a key dropped both fail here.
INDEX_CLAUSE_TEXTS = {
    "BND": (
        "BND tracks the same Bloomberg US Aggregate index as AGG, so the figures are the fund's "
        "index's own."
    ),
    "BIV": (
        "For BIV the figures are the proxy's and not the fund's index's: AGG tracks the broad "
        "Bloomberg US Aggregate — Treasury, government mortgage-backed, credit and securitised, "
        "roughly one to ten years — while BIV tracks the five to ten year government and credit "
        "part of that market. Every figure here is the aggregate's, so they approximate the "
        "intermediate-term market BIV sits in rather than BIV's own portfolio, and the maturity "
        "distribution assumptions.maturity_buckets lists is the aggregate's, not BIV's."
    ),
}
# The clause every fund without one of its own falls back to. Pinned in full for
# the same reason as the map above; the site that chooses between them is pinned
# by test_every_disclosure_string_matches_its_pinned_full_text.
INDEX_CLAUSE_DEFAULT_TEXT = (
    "Check the index the proxy names in assumptions.proxy_url against the fund's own before "
    "treating these as the fund's figures: where the two differ, these describe the proxy's "
    "index and the market segment around it."
)


# The Treasury par curve rates.build() returned on 2026-09-16 — the curve the
# live BND run of that day used. Stubbing it is what makes the assertions below
# that run's own numbers, offline; SHORT_CURVE is the same curve as it would be
# if the 20- and 30-year tenors were missing from the source.
CURVE_AS_OF = {"curve": "2026-09-16"}
PAR_CURVE = {
    "0.0833": 3.96,
    "0.25": 4.14,
    "0.5": 4.22,
    "1.0": 4.45,
    "2.0": 4.74,
    "3.0": 4.82,
    "5.0": 4.86,
    "7.0": 4.94,
    "10.0": 5.01,
    "20.0": 5.39,
    "30.0": 5.35,
}
SHORT_CURVE = {tenor: par for tenor, par in PAR_CURVE.items() if float(tenor) <= 10.0}


def _record() -> dict:
    """A proxy record in the shape fetch_characteristics returns."""
    return {
        "version": 2,
        "retrieved": "2026-09-17",
        "proxy": "AGG",
        "url": "https://example.invalid/ishares-core-total-us-bond-market-etf",
        "as_of": "2026-09-16",
        "nav_as_of": "2026-09-17",
        "figures": {
            "ytm_pct": 5.31,
            "coupon_pct": 3.78523,
            "duration_years": 5.74831,
            "sec_yield_pct": 4.8403,
            "wal_years": 8.19,
        },
        "expense_pct": 0.03,
        "nav": 96.287577,
        "warnings": [],
    }


def _stub_curve(monkeypatch, fund, curve=None):
    """That curve in place of rates.build(): the only outbound call in analyse."""
    monkeypatch.setattr(
        fund.rates,
        "build",
        lambda: {"par_curve": dict(PAR_CURVE if curve is None else curve), "as_of": CURVE_AS_OF},
    )


def test_the_scrape_layer_reads_the_page_and_tells_absence_from_breakage():
    import fund

    points = fund._points(FULL_PAGE, "fundamentalsAndRisk.default")
    assert len(points) == 8
    assert points["yieldToMaturity"]["value"] == 5.31

    # The walk has to reach the object the anchor sits in rather than the first
    # brace behind it: the decoy before it has an unbalanced brace inside a
    # string ahead of its own anchor, and the fundamentals block has one inside
    # a label. Either one corrupts a nearest-brace-and-match.
    assert fund._object(FULL_PAGE, "decoy.block")["value"] == 1

    # Every name in _FIGURE_NAMES is in preference order and the page carries
    # two yields: a hedged fund's page labels the hedged figure "average yield
    # to maturity", so the unhedged name has to win or a fund with both would
    # silently report the hedged number.
    assert fund._figure(points, fund._FIGURE_NAMES["ytm_pct"])["value"] == 5.31

    # thirtyDaySecYield is the first name for the SEC yield and is present with
    # a non-numeric value, so the numeric fallback has to win.
    sec = fund._figure(points, fund._FIGURE_NAMES["sec_yield_pct"])
    assert sec["value"] == 4.8403
    assert fund._figure(points, ("noSuchPoint", "weightedAvgLife"))["value"] == 8.19
    assert fund._figure(points, ("noSuchPoint",)) == {}

    nav = fund._leaf_point(FULL_PAGE, "fundHeader.fundNav.navAmount")
    assert fund._leaf_value(nav) == 96.287577
    assert fund._point_as_of(nav) == "2026-09-17"

    # A figure the page does not carry and a figure whose JSON no longer parses
    # are different faults, and the warning text says which one happened.
    assert fund._object(FULL_PAGE, "broken.block") is fund.UNPARSEABLE
    assert fund._object(FULL_PAGE, "no.such.block") is fund.MISSING
    assert fund._leaf_value(fund._leaf_point(NO_FEE_PAGE, "fundHeader.fees.expr")) is None
    assert (
        fund._why(fund._object(FULL_PAGE, "broken.block"), "broken.block")
        == "broken.block does not parse"
    )
    assert (
        fund._why(fund._object(FULL_PAGE, "no.such.block"), "no.such.block")
        == "no.such.block is missing"
    )


def test_the_output_carries_the_circularity_note_and_a_signed_gap(monkeypatch):
    import fund

    _stub_curve(monkeypatch, fund)
    monkeypatch.setattr(fund, "fetch_characteristics", lambda entry: _record())

    out = fund.analyse("BND")
    dec = out["yield_decomposition"]

    # The binding constraint: calculated may only sit beside published with this
    # note, so pin the plan's literal rather than a non-empty string. The literal
    # itself is this module's DISCLOSURE_TEXTS entry, asserted against the
    # payload here and against all ten strings by the full-text test below.
    assert out["circularity_note"] == DISCLOSURE_TEXTS["circularity_note"]
    assert len(out["circularity_note"]) == 271

    assert dec["published_ytm_pct"] == 5.31
    # Gross yield of the model's cash flows on that curve at the 31.2 bp blended
    # spread, less the 3 bp fee: 5.392 - 0.03, and the figure the whole script
    # exists to reproduce against the 5.31 the fund publishes.
    assert dec["calculated_ytm_pct"] == 5.362
    assert dec["treasury_equivalent_pct"] == 5.078
    # gap_bp is calculated minus published in basis points, and that relation is
    # the only sign this payload may carry: swapping the two yields, or flipping
    # the subtraction, breaks it.
    assert dec["gap_bp"] == round(
        (dec["calculated_ytm_pct"] - dec["published_ytm_pct"]) * 100.0, 1
    )
    assert dec["gap_bp"] == 5.2

    # Task 7 and Task 8 read these four by name: renaming one breaks them.
    assert out["characteristics"]["ytm_pct"] == 5.31
    assert out["characteristics"]["coupon_pct"] == 3.785
    assert out["characteristics"]["wal_years"] == 8.27
    assert out["characteristics"]["duration_years"] == 5.748

    # price_map is 21 rows centred on the published yield, 25 bp apart, per
    # assumptions.price_map_note.
    assert len(out["price_map"]) == 21
    assert out["price_map"][10]["ytm"] == 0.0531
    assert out["price_map"][0]["ytm"] == 0.0281
    assert out["price_map"][20]["ytm"] == 0.0781
    assert out["warnings"] == []


def test_each_disclosure_string_carries_what_it_has_to_say(monkeypatch):
    import fund

    _stub_curve(monkeypatch, fund)
    monkeypatch.setattr(fund, "fetch_characteristics", lambda entry: _record())

    out = fund.analyse("BND")
    assumptions = out["assumptions"]

    # Each of these strings is the only thing between a computed number and a
    # reader taking it for something it is not, so each is pinned by a phrase
    # that carries its meaning. "The key exists and is a non-empty string" would
    # pass a mutant that replaced the text with "x".
    note = assumptions["price_map_note"]
    assert "per 100 of par of the model" in note
    assert "not the fund's share price" in note
    # The NAV relation holds on the centre row and nowhere else. The first
    # version of this sentence claimed it for all 21 rows, and a reader who
    # recomputed the NAV from any other row got a wrong number.
    assert "only on the row centred on the published yield" in note
    assert "the relation does not hold at all" in note
    # The one thing this skill may never do: present a fair value.
    assert "no row is a fair value, a target or a forecast" in note

    gap = assumptions["gap_expectation"]
    assert "signed calculated_ytm_pct minus published_ytm_pct" in gap
    assert "roughly ±25 bp" in gap
    assert "-23.9 bp to +22.6 bp" in gap
    # Minus-the-fee is the centre the construction implies, labelled as that
    # rather than as where the measured gaps sat — they centred on +0.57 bp.
    assert "The model's own construction implies a centre of about minus the expense ratio" in gap
    assert "not a boundary" in gap
    # The closing sentence is anchored on the model's own band, not on the fee:
    # four of the seven funds' gaps are several times their fee and still sit
    # inside that band, so a fee-based diagnosis would call them the model
    # missing — and nothing here may suggest the market is wrong.
    assert "A gap outside that ±25 bp band is where the model stops explaining it" in gap
    assert "which still does not make it the market's error" in gap
    assert "centred on +0.57 bp" in gap

    proxy = assumptions["index_proxy"]
    # Scoped to what is genuinely the page's. The curve, the spread, the
    # calculated yield, the gap, par_per_share and price_map are this script's
    # arithmetic on the page's figures; wal_years is the model's own, and the
    # script reports the page's published 8.19 beside it as wal_check.
    assert "the figures characteristics carries from it are the page's" in proxy
    assert "characteristics.wal_years is not one of them" in proxy
    assert "index figures, not the fund's own holding-level figures" in proxy
    assert "as_of.curve is the Treasury curve, not the page's" in proxy
    assert "BND tracks the same Bloomberg US Aggregate index as AGG" in proxy

    wal = out["characteristics"]["wal_source"]
    # "static", not "published": the bands are the model's static input, the same
    # description index_proxy and assumptions.note use, so this sentence cannot be
    # read as claiming the fetched page publishes the maturity distribution.
    assert "the bucket model's weighted average of the index's static maturity bands" in wal
    assert "not the fund's own portfolio's weighted average life" in wal

    expense = assumptions["expense_source"]
    assert "is the proxy's (AGG) published figure" in expense
    assert "carries no as-of date on the page" in expense


def test_every_disclosure_string_is_the_constant_it_is_emitted_from(monkeypatch):
    """Identity, not presence: text added beside intact anchors fails here.

    An anchor pin proves meaning is present; it cannot prove that nothing
    contradictory was added. Prepending "price_map gives each row's fair value and
    a target to trade to." to price_map_note leaves every anchor verbatim and
    passed this whole suite before this test existed — a payload claiming a fair
    value and a trade target with a green suite. Emitting each string from a
    module-level constant and asserting the emitted text *is* that constant
    closes the addition, because the expectation does not move with the dict.
    """
    import fund

    _stub_curve(monkeypatch, fund)
    monkeypatch.setattr(fund, "fetch_characteristics", lambda entry: _record())

    out = fund.analyse("BND")
    assumptions = out["assumptions"]

    assert assumptions["price_map_note"] == fund._PRICE_MAP_NOTE
    assert assumptions["gap_expectation"] == fund._GAP_EXPECTATION
    assert assumptions["comparison"] == fund._COMPARISON
    assert assumptions["spread_convention"] == fund._SPREAD_CONVENTION
    assert assumptions["note"] == fund._MODEL_NOTE
    # The parameterised three are templates: the emitted text is the constant
    # rendered with this payload's own proxy and symbol, so a sentence added
    # where the dict is built fails just as it does for the fixed ones.
    assert assumptions["expense_source"] == fund._EXPENSE_SOURCE.format(proxy="AGG")
    assert assumptions["nav_source"] == fund._NAV_SOURCE.format(proxy="AGG")
    assert assumptions["index_proxy"] == fund._INDEX_PROXY.format(
        proxy="AGG", symbol="BND", clause=fund._INDEX_CLAUSES["BND"]
    )
    assert out["characteristics"]["wal_source"] == fund._WAL_SOURCE
    assert out["circularity_note"] == fund.CIRCULARITY_NOTE

    # Identity against a constant cannot see an edit to the constant itself —
    # the expectation moves with it. The full copy of each string, these two
    # included, is DISCLOSURE_TEXTS, asserted by the full-text test below.
    # This test stays because a failure here names the constant that stopped
    # being emitted rather than the text that drifted.


def _emitted(payload: dict, path: str) -> str:
    """The string the payload carries at a dotted output path.

    Keyed by path rather than by constant name so that a failure says where the
    text is emitted, and so that a key deleted at the dict site fails here
    rather than passing as an absence.
    """
    node: object = payload
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            pytest.fail(f"{path} is no longer emitted by analyse()")
        node = node[part]
    assert isinstance(node, str)
    return node


def test_every_disclosure_string_matches_its_pinned_full_text(monkeypatch):
    """All ten disclosure strings, word for word, against this file's own copies.

    The three pin designs before this one each left a site open. Anchors miss a
    sentence added beside intact wording, and only cover five of the ten. Identity
    against a module constant moves with the constant, so a constant emptied to
    "x" survives it. Hoisting the strings into constants moved the edit site to
    the constants, where four could be emptied and all ten added to with the
    suite still green. The only expectation that cannot move with the code is a
    copy of the text, so there is one here — DISCLOSURE_TEXTS — and the payload
    has to equal it. Replacing, adding to, deleting or truncating any of the ten,
    at the constant or at the dict site, fails below naming the path that drifted
    and printing both texts.
    """
    import fund

    _stub_curve(monkeypatch, fund)
    monkeypatch.setattr(fund, "fetch_characteristics", lambda entry: _record())

    out = fund.analyse("BND")
    for path, expected in DISCLOSURE_TEXTS.items():
        assert _emitted(out, path) == expected, f"{path} is not the pinned text"

    # index_proxy's clause is pinned one level down, because the one template
    # renders a different disclosure for each fund: the map is compared whole, so
    # a clause edited, dropped, or added for a third fund fails here.
    assert fund._INDEX_CLAUSES == INDEX_CLAUSE_TEXTS
    assert fund._INDEX_CLAUSE_DEFAULT == INDEX_CLAUSE_DEFAULT_TEXT

    # And the site that chooses between them: a fund with no clause of its own
    # gets the default. With _INDEX_PROXY pinned by the BND literal above and the
    # default clause pinned by its own, this equality pins VCIT's whole emitted
    # string too — a fallback to BND's or BIV's clause, a claim about an index
    # VCIT does not track, fails even though VCIT carries no literal of its own.
    other_assumptions = fund.analyse("VCIT")["assumptions"]
    other = other_assumptions["index_proxy"]
    assert other == fund._INDEX_PROXY.format(
        proxy="IGIB", symbol="VCIT", clause=fund._INDEX_CLAUSE_DEFAULT
    )
    assert INDEX_CLAUSE_DEFAULT_TEXT in other

    # The same property for the other two proxy-substituted templates. DISCLOSURE_TEXTS above
    # holds only the AGG rendering of each, and the identity pins that check it call
    # .format(proxy="AGG") — which a template with the {proxy} placeholder REMOVED satisfies just
    # as well. Hard-code AGG into either constant and VCIT's page would read "the proxy's (AGG)"
    # beside an IGIB URL with every one of those pins still green.
    #
    # An identity against .format(proxy="IGIB") does NOT close that: with the placeholder gone,
    # both sides are the same hard-coded string and the assertion passes. Measured, with AGG
    # hard-coded into _EXPENSE_SOURCE: the identity form survived, the two value assertions
    # below killed it. So both forms are kept — the identity for a template whose shape changes,
    # and the VALUE for a template that stopped substituting. The full-text AGG pins stay as they
    # are: they catch prose drift, a different job, and hard-coding IGIB fails them.
    for key, template in (
        ("expense_source", fund._EXPENSE_SOURCE),
        ("nav_source", fund._NAV_SOURCE),
    ):
        emitted = other_assumptions[key]
        assert emitted == template.format(proxy="IGIB"), key
        assert "IGIB" in emitted, key
        assert "AGG" not in emitted, key


def test_the_biv_payload_discloses_the_index_biv_does_not_track(monkeypatch):
    import fund

    _stub_curve(monkeypatch, fund)
    monkeypatch.setattr(fund, "fetch_characteristics", lambda entry: _record())

    out = fund.analyse("BIV")
    proxy = out["assumptions"]["index_proxy"]

    # BIV is fetched from AGG's aggregate page while tracking a slice of it, so
    # its numbers are not BIV's. The clause has to arrive through BIV's own
    # payload — falling back to the generic clause would leave a reader
    # believing the figures are the fund's.
    assert "AGG tracks the broad Bloomberg US Aggregate" in proxy
    assert "BIV tracks the five to ten year government and credit part of that market" in proxy
    assert "rather than BIV's own portfolio" in proxy
    # Identity as well as meaning: the clause has to be emitted from the BIV
    # entry of the map, not rebuilt or appended to where the dict is built.
    assert proxy == fund._INDEX_PROXY.format(
        proxy="AGG", symbol="BIV", clause=fund._INDEX_CLAUSES["BIV"]
    )
    assert fund._INDEX_CLAUSES["BIV"] in proxy
    assert fund._INDEX_CLAUSE_DEFAULT not in proxy


def test_a_page_without_the_nav_nulls_par_per_share_and_says_so(monkeypatch, tmp_path):
    import fund

    _stub_curve(monkeypatch, fund)
    monkeypatch.setattr(fund.config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(fund, "_fetch", lambda url: NO_NAV_PAGE)

    out = fund.analyse("BND")
    # Never 0.0: a share count of zero is a plausible-looking number nobody can
    # tell from a real one, which is what made the old behaviour dangerous.
    assert out["par_per_share"] is None
    assert out["as_of"]["nav"] is None
    assert out["warnings"] == [
        "nav: fundHeader.fundNav.navAmount is missing on the iShares AGG page — "
        "par_per_share is null"
    ]
    # The rest of the decomposition does not involve the NAV and still stands: a
    # NAV-less page is not the caller's fault, so this is not an exit-2 case.
    assert out["characteristics"]["expense_ratio_pct"] == 0.03
    assert out["yield_decomposition"]["calculated_ytm_pct"] == 5.362
    # And it must not be cached: 24 hours of par_per_share null is worse than
    # one run of it.
    assert not fund._cache_path("AGG").exists()


def test_a_page_without_the_expense_ratio_nulls_what_is_derived_from_it(monkeypatch, tmp_path):
    import fund

    _stub_curve(monkeypatch, fund)
    monkeypatch.setattr(fund.config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(fund, "_fetch", lambda url: NO_FEE_PAGE)

    out = fund.analyse("BND")
    # A missing fee is not a free fund: it is 3 bp of the calculated yield and
    # every number downstream of it.
    assert out["characteristics"]["expense_ratio_pct"] is None
    assert out["yield_decomposition"]["expense_pct"] is None
    assert out["yield_decomposition"]["calculated_ytm_pct"] is None
    assert out["yield_decomposition"]["gap_bp"] is None
    assert out["warnings"] == [
        "expense_pct: fundHeader.fees.expr is missing on the iShares AGG page — "
        "expense_ratio_pct, expense_pct, calculated_ytm_pct and gap_bp are null"
    ]
    # The curve half of the decomposition does not involve the fee and stands.
    assert out["yield_decomposition"]["treasury_equivalent_pct"] == 5.078
    assert out["yield_decomposition"]["published_ytm_pct"] == 5.31
    assert out["par_per_share"] == 105.74
    assert not fund._cache_path("AGG").exists()


def test_a_cache_record_that_did_not_fully_parse_is_not_served(monkeypatch, tmp_path):
    import fund

    _stub_curve(monkeypatch, fund)
    monkeypatch.setattr(fund.config, "data_dir", lambda: tmp_path)
    path = fund._cache_path("AGG")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exactly what the old code wrote from a NAV-less page: a record whose
    # required inputs are unset. Serving it is a day of confident nulls.
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "retrieved": "2026-09-17",
                "proxy": "AGG",
                "url": "https://example.invalid/agg",
                "as_of": "2026-09-16",
                "nav_as_of": "2026-09-17",
                "figures": {
                    "ytm_pct": 5.31,
                    "coupon_pct": 3.78523,
                    "duration_years": 5.74831,
                    "sec_yield_pct": 4.8403,
                },
                "expense_pct": None,
                "nav": None,
                "warnings": [],
            }
        )
    )
    monkeypatch.setattr(fund, "_fetch", lambda url: FULL_PAGE)

    out = fund.analyse("BND")
    assert out["par_per_share"] == 105.74  # refetched, not served
    assert out["warnings"] == []
    assert json.loads(path.read_text())["nav"] == 96.287577

    # A record from a build that did not write a field this one reads is refetched
    # too, rather than served with the field missing.
    stale = json.loads(path.read_text())
    del stale["version"]
    path.write_text(json.dumps(stale))
    monkeypatch.setattr(fund, "_fetch", lambda url: NO_NAV_PAGE)
    assert fund.analyse("BND")["par_per_share"] is None


def test_a_page_the_model_cannot_read_asks_the_caller_for_the_figures(monkeypatch, tmp_path):
    import fund

    monkeypatch.setattr(fund.config, "data_dir", lambda: tmp_path)

    # Nothing to read at all, and the exit-2 ask says which fault it was: the
    # reader's job is to fetch figures from the broker's page, not to guess
    # whether iShares moved a block or changed its JSON.
    monkeypatch.setattr(fund, "_fetch", lambda url: _page(_DECOY, _FUNDAMENTALS_BROKEN))
    with pytest.raises(fund.InvalidInput) as unparseable:
        fund.analyse("BND")
    assert unparseable.value.code == "INPUT_NEEDED"
    assert "fundamentalsAndRisk.default does not parse" in str(unparseable.value)

    monkeypatch.setattr(fund, "_fetch", lambda url: _page(_DECOY))
    with pytest.raises(fund.InvalidInput) as absent:
        fund.analyse("BND")
    assert "fundamentalsAndRisk.default is missing" in str(absent.value)

    # A page that parses but has stopped publishing a figure the model needs is
    # the same ask, naming the figure rather than the block.
    monkeypatch.setattr(
        fund, "_fetch", lambda url: _page(_DECOY, _FUNDAMENTALS_NO_SEC, _FEES, _NAV)
    )
    with pytest.raises(fund.InvalidInput) as gone:
        fund.analyse("BND")
    assert "published none of sec_yield_pct" in str(gone.value)


def test_the_curve_has_to_reach_the_longest_bucket(monkeypatch):
    import fund

    # The static guard: the shipped buckets stop at 28 years.
    assert fund.longest_bucket_years(fund.KNOWN_FUNDS["BND"]["buckets"]) == 28.0
    with pytest.raises(fund.InvalidInput) as static:
        fund.longest_bucket_years([(100.0, 40.0)])
    assert "flat-extrapolates" in str(static.value)

    # bondmath.bootstrap fills its grid out to MAX_YEARS whatever the par curve
    # covers, so a 10-year curve would be priced out to 28 years as if those
    # years were quoted. The span has to be checked, because the curve object
    # cannot show the gap.
    fund.check_curve_covers([1.0, 2.0, 5.0, 10.0, 30.0], 28.0)
    with pytest.raises(fund.ApiError) as span:
        fund.check_curve_covers([1.0, 2.0, 5.0, 10.0], 28.0)
    assert span.value.code == "CURVE_TOO_SHORT"
    with pytest.raises(fund.ApiError):
        fund.check_curve_covers([], 28.0)

    # And analyse has to run the check: stubbing a curve that stops at 10 years
    # must fail the fund rather than flat-extrapolate 18 years of it.
    _stub_curve(monkeypatch, fund, curve=SHORT_CURVE)
    monkeypatch.setattr(fund, "fetch_characteristics", lambda entry: _record())
    with pytest.raises(fund.ApiError) as short:
        fund.analyse("BND")
    assert short.value.code == "CURVE_TOO_SHORT"


def _probe(body: str) -> subprocess.CompletedProcess:
    """Run a `python -c` body with no PYTHONPATH, from an unrelated cwd."""
    return subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},  # no PYTHONPATH — that is the point
        cwd="/",
    )


def test_the_script_imports_second_opinion_with_no_pythonpath():
    # F19: SKILL.md runs a script with no PYTHONPATH from an unrelated cwd. Import
    # the real file (its __main__ guard means nothing is fetched) so a missing
    # sys.path bootstrap fails here instead of on a user's machine.
    import_body = (
        "import importlib.util; "
        f"spec = importlib.util.spec_from_file_location('fund_probe', {str(FUND)!r}); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod)"
    )
    proc = _probe(import_body)
    assert proc.returncode == 0, proc.stderr
    assert "No module named 'second_opinion'" not in proc.stderr

    # This first probe cannot see fund.py's OWN bootstrap: `import rates` runs
    # rates.py, which puts lib/ on sys.path itself, so deleting fund.py's insert
    # leaves the probe above green. Pre-stub the sibling and the only thing left
    # that can supply lib/ is fund.py's own line — the one F30 told us to keep.
    proc = _probe(
        "import importlib.util, sys, types; "
        "stub = types.ModuleType('rates'); stub.build = lambda *a, **k: {}; "
        "sys.modules['rates'] = stub; " + import_body
    )
    assert proc.returncode == 0, proc.stderr
    assert "No module named 'second_opinion'" not in proc.stderr
