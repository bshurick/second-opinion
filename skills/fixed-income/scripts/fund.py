#!/usr/bin/env python3
"""Usage: fund.py <symbol> — decompose a bond fund's yield into curve plus spread.

Takes one positional argument, a fund symbol, and writes one JSON object to
stdout: the fund's published yield to maturity split into the part the Treasury
curve pays, the part the fund's sector mix adds as credit spread, and the part
the expense ratio takes back.

Reads nothing from stdin.

Vanguard's product pages are JS-rendered and its JSON API carries no yield
data, so the four volatile figures — yield to maturity, average coupon,
effective duration and SEC yield — are read live from the iShares page of the
fund's index proxy (BND's proxy is AGG: same index, same figures). Only the
slow-moving structure is static: the proxy symbol, the sector weights, the
per-sector spread assumptions and the maturity buckets. A symbol outside the
map exits 2 asking the caller for the figures.

Output JSON contract (stdout)::

    {
      "symbol": "BND",
      "as_of": {"fund": "2026-09-16", "curve": "2026-09-16", "nav": "2026-09-17",
                "retrieved": "..."},
      "characteristics": {"ytm_pct": 5.31, "coupon_pct": 3.785, "wal_years": 8.27, ...},
      "yield_decomposition": {"treasury_equivalent_pct": ..., "blended_spread_bp": ...,
                              "expense_pct": ..., "calculated_ytm_pct": ...,
                              "published_ytm_pct": ..., "gap_bp": ...},
      "par_per_share": 105.74,
      "price_map": [{"ytm": 0.0281, "price": 106.63}, ...],
      "assumptions": {...},
      "warnings": ["nav: ..."],
      "circularity_note": "..."
    }

An input the model needs but the page did not carry — the NAV, the expense
ratio — makes every field derived from it null and adds a ``warnings`` entry
naming it, so a broken page can never render as a plausible zero. A record
that did not fully parse is not written to the cache.

Exit codes follow the plugin convention (0 ok, 2 when the caller must supply
the figures, 5 on an upstream API error).
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
# The plugin's shared math package lives in lib/ at the plugin root.
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))  # keep — fund.py imports the sibling rates.py

import rates  # noqa: E402
from second_opinion import bondmath, config, output  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

# Coupons and the curve's own compounding. The curve is bootstrapped on the
# same grid, so pricing the cash flows on it never mixes conventions.
FREQ = 2

# Nothing is queried past the bootstrap grid: `discount_factor` flat-extrapolates
# beyond the last point, which would silently misprice a longer bucket.
MAX_YEARS = 30.0

_TTL = 86400
_TIMEOUT = 30
_USER_AGENT = "second-opinion/1.0 (python-urllib)"  # browser strings get a 403
_CACHE_DIR = "ishares-cache"

# The cache record's shape. Bump when the record gains a field the reader uses:
# a record from an older build is then re-fetched instead of served short.
_CACHE_VERSION = 2

NEEDED_FIELDS = ("ytm_pct", "coupon_pct", "duration_years", "sec_yield_pct")

CIRCULARITY_NOTE = (
    "The calculated yield is built from today's Treasury curve and today's "
    "credit spreads, which are themselves market prices. It reproduces the "
    "published yield by construction and is NOT evidence of mispricing. Use "
    "it to check the arithmetic, not to disagree with the market."
)

# Every disclosure string below is a module-level constant and is emitted from
# that constant, never rebuilt at the dict site: a test can then assert the
# emitted text *is* the constant, which is the only pin that sees a sentence
# added beside intact wording — the shape of claim ("no row is a fair value"
# with "this row's fair value" prepended) that anchor substrings cannot catch.
# `{proxy}`, `{symbol}` and `{clause}` are the only placeholders; the function
# fills them with str.format.
_MODEL_NOTE = (
    "The bucket model prices one par bond per maturity band, weighted by the band's "
    "share of the index. It is an approximation of a real portfolio's cash flows, "
    "which is why the reproduced yield is compared with a tolerance rather than "
    "asserted equal. Buckets and sector weights are static structural inputs, not "
    "live holdings: they are refreshed with the skill, not with every run."
)

_SPREAD_CONVENTION = (
    "The blended spread is a discount margin over the Treasury zero curve, quoted "
    "as an annualised rate: each cash flow is divided by (1 + spread/freq)^(t*freq), "
    "not shifted along the curve. The two agree to first order, the residual being "
    "the cross term curve_rate * spread / freq — about 2 bp at a 4% curve and a 1% "
    "spread — so the spread discounts a little harder than the parallel shift a "
    "reader may expect."
)

_COMPARISON = (
    "treasury_equivalent_pct is the flat yield of these same cash flows priced on "
    "the Treasury curve alone. calculated_ytm_pct adds the blended spread and "
    "subtracts the expense ratio, so it is net of fees while the published yield to "
    "maturity is gross. The expense ratio is therefore one component of the gap "
    "between them — but only one, and on its own it is not what the gap should be: "
    "the bucket model reproduces a published yield to maturity to roughly ±25 bp, "
    "and that residual is model error, not the fee. See gap_expectation for what a "
    "gap of a given size means."
)

# Re-measure this date, the -23.9/+22.6 bp bounds and the +0.57 bp centre together:
# one sweep produced all three (2026-09-17), so updating one alone mixes two passes.
_GAP_EXPECTATION = (
    "gap_bp is signed calculated_ytm_pct minus published_ytm_pct, in basis points: "
    "negative means the model produced less yield than the fund publishes, positive "
    "means more. The part of it with a reason is the fee — calculated is net of it, "
    "published is gross — and that is 3 to 7 bp. The rest is the bucket model's own "
    "error: measured over the seven funds this skill covers on 2026-09-17, the gap "
    "ran from -23.9 bp to +22.6 bp. So the bucket model reproduces a published YTM "
    "to roughly ±25 bp, and a gap of that size is model error, not the fee, and not "
    "a discrepancy — which is not to say the model is right. The model's own "
    "construction implies a centre of about minus the expense ratio, not a boundary, "
    "and that is a statement about the construction rather than about the data: over "
    "those same seven funds the measured gaps centred on +0.57 bp, so read the "
    "construction's centre as where the model would sit if it were exact, not as "
    "where yields are. A gap outside that ±25 bp band is where the model stops "
    "explaining it, which still does not make it the market's error."
)

_EXPENSE_SOURCE = (
    "The expense ratio is the proxy's ({proxy}) published figure, read "
    "from the page's fund header. Unlike the NAV and the daily figures, that field "
    "carries no as-of date on the page, so it cannot be dated: it is the current "
    "prospectus fee, which changes when the fund reprices rather than daily."
)

_NAV_SOURCE = (
    "The NAV is the proxy's ({proxy}), not the fund's own: iShares is the "
    "only publisher whose figures are fetchable, and the two funds' share prices "
    "differ. It carries its own as-of date (as_of.nav), which is often a day newer "
    "than the figures it is paired with (as_of.fund). par_per_share scales with the "
    "proxy's NAV, and that scaling is exact only where the fund tracks the proxy's "
    "index (BND); elsewhere it is the proxy's share price applied to the proxy's "
    "cash flows, so read par_per_share as an approximation of the same kind."
)

_INDEX_PROXY = (
    "The iShares {proxy} page is the index proxy this skill fetches for {symbol}, and "
    "the figures characteristics carries from it are the page's: its yield to maturity, "
    "average coupon, published duration and SEC yield — index figures, not the fund's "
    "own holding-level figures. characteristics.wal_years is not one of them: it is the "
    "bucket model's own weighted average of the static index bands, as "
    "characteristics.wal_source says, which is why assumptions.wal_check sets it beside "
    "the page's published figure. Everything else the model reports is this script's own "
    "arithmetic on the proxy's figures — the treasury-equivalent yield, the blended "
    "spread, the calculated yield, the gap, par_per_share and price_map — and "
    "as_of.curve is the Treasury curve, not the page's. {clause}"
)

_PRICE_MAP_NOTE = (
    "price_map re-prices the same model cash flows at 21 flat yields 25 bp apart, "
    "centred on the published yield to maturity, so there is one row per 25 bp of "
    "yield from -250 bp to +250 bp. The price is per 100 of par of the model "
    "portfolio, not per share and not the fund's share price: only on the row "
    "centred on the published yield does par_per_share times that row over 100 come "
    "back to the fund's NAV per share, and even there only to the model's own error "
    "and rounding. On the other twenty rows the relation does not hold at all, so a "
    "NAV recomputed from one of them is simply wrong. The rows come from the same "
    "circular construction as calculated_ytm_pct — today's curve and today's "
    "spreads — so no row is a fair value, a target or a forecast; each is what "
    "these cash flows would be worth if the whole portfolio yielded that much."
)

_WAL_SOURCE = (
    "wal_years is the bucket model's weighted average of the index's static "
    "maturity bands, the static weights assumptions.maturity_buckets lists, not "
    "the fund's own portfolio's weighted average life; it is the model's input, "
    "so read it as the assumption behind the yield, and assumptions.wal_check "
    "for how it compares with the published figure."
)

# iShares data-point names for the figures that move every day, in preference
# order: the first name the page carries wins. `fxHedgedYield` is the USD-
# hedged figure iShares labels "Average Yield to Maturity" on a hedged fund's
# page; it is the same number only while the fund is dollar-hedged, so the
# unhedged `yieldToMaturity` is preferred wherever a page publishes both.
_FIGURE_NAMES: dict[str, tuple[str, ...]] = {
    "ytm_pct": ("yieldToMaturity", "fxHedgedYield"),
    "coupon_pct": ("weightedAvgCouponFi", "weightedAvgCoupon"),
    "duration_years": ("modelOad", "effectiveDuration"),
    "sec_yield_pct": ("thirtyDaySecYield", "secYield"),
    "wal_years": ("weightedAvgLife", "weightedAvgMaturity"),
    "distribution_yield_pct": ("twelveMonTrlYld", "trailing12MonthYield"),
}

# Structural, slow-moving: the proxy symbol and page, each sector's weight in
# the index and the spread its bonds pay over Treasuries in basis points, and
# the published maturity distribution as (weight_pct, midpoint_years). The four
# figures that move daily are fetched, never stored here. One structure per
# proxy: the funds that share a proxy share this block.
_AGG_STRUCTURE: dict[str, Any] = {
    "proxy": "AGG",
    "url": "https://www.ishares.com/us/products/239458/ishares-core-total-us-bond-market-etf",
    "sectors": {
        "Treasury/Agency": (49.2, 0.0),
        "Gov Mortgage-Backed": (19.3, 35.0),
        "Industrial": (14.8, 78.0),
        "Finance": (8.1, 78.0),
        "Foreign": (3.5, 78.0),
        "Utilities": (2.6, 78.0),
        "CMBS": (1.5, 80.0),
        "ABS": (0.5, 60.0),
        "Other": (0.5, 60.0),
    },
    "buckets": [
        (0.2, 0.5),
        (44.8, 3.0),
        (34.5, 7.5),
        (3.7, 12.5),
        (5.5, 17.5),
        (4.3, 22.5),
        (6.9, 28.0),
    ],
}

KNOWN_FUNDS: dict[str, dict[str, Any]] = {
    "BND": _AGG_STRUCTURE,
    "BIV": _AGG_STRUCTURE,
    "BNDX": {
        "proxy": "IAGG",
        "url": "https://www.ishares.com/us/products/279626/ishares-core-international-aggregate-bond-etf",
        "sectors": {
            "Treasury/Agency": (74.1, 0.0),
            "Industrial": (5.4, 78.0),
            "Finance": (5.1, 78.0),
            "Other": (5.8, 60.0),
            "Foreign": (8.5, 78.0),
            "Utilities": (1.2, 78.0),
        },
        "buckets": [
            (2.6, 0.5),
            (11.41, 1.5),
            (11.97, 2.5),
            (20.88, 4.0),
            (14.31, 6.0),
            (18.52, 8.5),
            (7.22, 12.5),
            (4.22, 17.5),
            (8.86, 25.0),
        ],
    },
    "BSV": {
        "proxy": "ISTB",
        "url": "https://www.ishares.com/us/products/244051/ishares-core-1-5-year-usd-bond-etf",
        "sectors": {
            "Treasury/Agency": (56.1, 0.0),
            "Industrial": (17.9, 78.0),
            "Finance": (12.7, 78.0),
            "Gov Mortgage-Backed": (2.8, 35.0),
            "Foreign": (4.7, 78.0),
            "CMBS": (2.0, 80.0),
            "Utilities": (2.0, 78.0),
            "ABS": (0.7, 60.0),
            "Other": (1.2, 60.0),
        },
        "buckets": [
            (1.96, 0.5),
            (28.54, 1.5),
            (24.81, 2.5),
            (43.05, 4.0),
            (1.61, 6.0),
            (0.02, 8.5),
            (0.02, 25.0),
        ],
    },
    "BLV": {
        "proxy": "IGLB",
        "url": "https://www.ishares.com/us/products/239423/ishares-10-plus-year-investment-grade-corporate-bond-etf",
        "sectors": {
            "Utilities": (14.0, 78.0),
            "Industrial": (55.3, 78.0),
            "Finance": (20.5, 78.0),
            "Other": (10.2, 60.0),
        },
        "buckets": [
            (0.52, 0.5),
            (0.08, 6.0),
            (0.25, 8.5),
            (20.31, 12.5),
            (21.5, 17.5),
            (57.34, 25.0),
        ],
    },
    "VCIT": {
        "proxy": "IGIB",
        "url": "https://www.ishares.com/us/products/239463/ishares-5-10-year-investment-grade-corporate-bond-etf",
        "sectors": {
            "Finance": (35.4, 78.0),
            "Utilities": (10.0, 78.0),
            "Industrial": (44.8, 78.0),
            "Other": (9.8, 60.0),
        },
        "buckets": [
            (0.27, 0.5),
            (0.04, 2.5),
            (0.53, 4.0),
            (40.21, 6.0),
            (54.87, 8.5),
            (3.95, 12.5),
            (0.13, 25.0),
        ],
    },
    "VCSH": {
        "proxy": "IGSB",
        "url": "https://www.ishares.com/us/products/239451/ishares-1-5-year-investment-grade-corporate-bond-etf",
        "sectors": {
            "Finance": (42.4, 78.0),
            "Industrial": (41.9, 78.0),
            "Utilities": (6.7, 78.0),
            "Foreign": (0.3, 78.0),
            "Treasury/Agency": (0.1, 0.0),
            "Other": (8.7, 60.0),
        },
        "buckets": [
            (1.32, 0.5),
            (22.49, 1.5),
            (25.12, 2.5),
            (46.23, 4.0),
            (4.79, 6.0),
            (0.04, 8.5),
            (0.02, 25.0),
        ],
    },
}


# Whose index the fetched figures are. A proxy is the closest page this skill
# can fetch, not necessarily the fund's own index, and the two are not
# interchangeable: BIV is the case that matters, mapped to AGG's aggregate page
# while it tracks the five to ten year government and credit slice of it.
_INDEX_CLAUSES = {
    "BND": (
        "BND tracks the same Bloomberg US Aggregate index as AGG, so the figures are the "
        "fund's index's own."
    ),
    "BIV": (
        "For BIV the figures are the proxy's and not the fund's index's: AGG tracks the "
        "broad Bloomberg US Aggregate — Treasury, government mortgage-backed, credit and "
        "securitised, roughly one to ten years — while BIV tracks the five to ten year "
        "government and credit part of that market. Every figure here is the aggregate's, "
        "so they approximate the intermediate-term market BIV sits in rather than BIV's own "
        "portfolio, and the maturity distribution assumptions.maturity_buckets lists is the "
        "aggregate's, not BIV's."
    ),
}
_INDEX_CLAUSE_DEFAULT = (
    "Check the index the proxy names in assumptions.proxy_url against the fund's own before "
    "treating these as the fund's figures: where the two differ, these describe the proxy's "
    "index and the market segment around it."
)


def weighted_average_life(buckets: list[tuple[float, float]]) -> float:
    """Weight-averaged maturity from (weight_pct, midpoint_years) pairs."""
    total = sum(w for w, _ in buckets)
    return sum(w * m for w, m in buckets) / total


def blended_spread_bp(sectors: dict[str, tuple[float, float]]) -> float:
    """Weight-average the per-sector spreads. Values are (weight_pct, spread_bp)."""
    total = sum(w for w, _ in sectors.values())
    return sum(w * s for w, s in sectors.values()) / total


def longest_bucket_years(buckets: list[tuple[float, float]]) -> float:
    """The furthest a bucket reaches, refused past the bootstrap grid.

    A midpoint beyond ``MAX_YEARS`` would be priced off a flat-extrapolated
    curve, so it is an input error rather than something to approximate.
    """
    longest = max(maturity for _, maturity in buckets)
    if longest > MAX_YEARS:
        raise InvalidInput(
            f"bucket midpoint {longest:g}y is past the {MAX_YEARS:g}-year bootstrap grid, "
            "where the curve flat-extrapolates"
        )
    return longest


def check_curve_covers(tenors: list[float], longest: float) -> None:
    """Refuse when the par curve stops short of the longest bucket.

    ``bondmath.bootstrap`` fills its grid out to ``max_years`` whatever the par
    curve's own span, so a curve ending at 10y is flat-extrapolated to 30y and
    priced as if those years were quoted. The span has to be checked here: the
    curve object itself can never show the gap.
    """
    span = max(tenors) if tenors else 0.0
    if span < longest:
        raise ApiError(
            f"the Treasury par curve stops at {span:g}y but a bucket reaches {longest:g}y, "
            "which the bootstrap would flat-extrapolate",
            code="CURVE_TOO_SHORT",
        )


def bucket_cashflows(
    buckets: list[tuple[float, float]], coupon_rate: float, freq: int = FREQ
) -> list[tuple[float, float]]:
    """Cash flows for the whole portfolio per 100 of par, bucket by bucket.

    Each bucket is a par bond maturing at its band's midpoint, scaled to its
    share of the portfolio; payments landing on the same date are merged, so
    the result is one portfolio, not seven bonds.
    """
    total_w = sum(w for w, _ in buckets)
    merged: dict[float, float] = {}
    for weight, maturity in buckets:
        w = weight / total_w
        for t, amt in bondmath.cashflows(coupon_rate, maturity, freq, 100.0 * w):
            merged[t] = merged.get(t, 0.0) + amt
    return sorted(merged.items())


def _price_at_flat_yield(
    cashflows: list[tuple[float, float]], ytm: float, freq: int = FREQ
) -> float:
    """Price per 100 of par when every cash flow is discounted at ``ytm``."""
    per = ytm / freq
    return sum(amount / ((1.0 + per) ** (t * freq)) for t, amount in cashflows)


def par_per_share(
    nav: float,
    coupon_rate: float,
    ytm: float,
    buckets: list[tuple[float, float]],
    freq: int = FREQ,
) -> float:
    """Face value a share owns, from the fund's coupon, yield and NAV.

    A fund trading below par owns more face value than its NAV: it paid less
    than 100 per 100 of face, and the coupon is quoted on face, so the coupon
    a share earns is the coupon rate times this number.
    """
    cashflows = bucket_cashflows(buckets, coupon_rate, freq)
    return nav / (_price_at_flat_yield(cashflows, ytm, freq) / 100.0)


def _yield_from_cashflows(
    cashflows: list[tuple[float, float]], price: float, freq: int = FREQ
) -> float:
    """Flat yield that reproduces ``price`` for ``cashflows``.

    Bracket is ``(-0.99 * freq, 1.0)``: the low end is the deepest discount a
    ``freq``-compounded yield can express without the period rate reaching
    -100%, the high end a 100% yield. Between them the price is monotone, so
    bisection cannot miss.
    """
    return bondmath.bisect(
        lambda y: _price_at_flat_yield(cashflows, y, freq) - price,
        -0.99 * freq + 1e-9,
        1.0,
    )


def _price_map(
    cashflows: list[tuple[float, float]], ytm: float, freq: int = FREQ
) -> list[dict[str, float]]:
    """21 flat-yield prices, 25 bp apart, centred on the published yield."""
    step = 0.0025
    lo = max(ytm - 10 * step, 0.0001)
    return [
        {
            "ytm": round(lo + i * step, 6),
            "price": round(_price_at_flat_yield(cashflows, lo + i * step, freq), 4),
        }
        for i in range(21)
    ]


def _cache_path(proxy: str) -> Path:
    return config.data_dir() / _CACHE_DIR / f"{proxy}.json"


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — fixed https host
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ApiError(
            f"iShares returned HTTP {exc.code} for {url}",
            code="ISHARES_HTTP",
            http_status=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiError(
            f"iShares request failed for {url}: {exc.reason}", code="ISHARES_HTTP"
        ) from exc
    except (OSError, TimeoutError) as exc:
        raise ApiError(f"iShares request failed for {url}: {exc}", code="ISHARES_HTTP") from exc


class _Absent:
    """Why a lookup found nothing, carried instead of an empty dict.

    "The page does not carry this" and "the page carries it but it no longer
    parses" are different faults — the first is a figure iShares stopped
    publishing, the second is a page this script can no longer read — and
    collapsing both into ``{}`` is what let a missing NAV reach the output as a
    plausible ``0.0``.
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"<{self.reason}>"


MISSING = _Absent("is missing")
UNPARSEABLE = _Absent("does not parse")


def _why(outcome: Any, full_name: str) -> str:
    """Why ``full_name`` has no usable value, for a warning or an error."""
    if isinstance(outcome, _Absent):
        return f"{full_name} {outcome.reason}"
    return f"{full_name} carries no number"


def _enclosing_brace(text: str, at: int) -> int:
    """Index of the ``{`` opening the innermost object that contains ``at``.

    Walking back to the nearest ``{`` can land inside a string value that
    happens to contain one, and brace-match from there finds the wrong object.
    Tracking the brace stack in string-aware order from the start of the
    document finds the object the anchor is actually in.
    """
    stack: list[int] = []
    in_string = False
    escaped = False
    for i in range(at):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append(i)
        elif char == "}" and stack:
            stack.pop()
    return stack[-1] if stack else -1


def _object(text: str, full_name: str) -> dict[str, Any] | _Absent:
    """The JSON object carrying ``"fullName": "<full_name>"``.

    The product page embeds its data as JSON inside a script tag, so the value
    cannot be read with a regex: find the anchor, walk the brace stack back to
    the object it sits in, then brace-match to the close, skipping braces
    inside strings. Returns ``MISSING`` when the page carries no such anchor
    and ``UNPARSEABLE`` when it carries one that will not parse.
    """
    anchor = f'"fullName":"{full_name}"'
    at = text.find(anchor)
    if at < 0:
        return MISSING
    start = _enclosing_brace(text, at)
    if start < 0:
        return UNPARSEABLE
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    found = json.loads(text[start : i + 1])
                except ValueError:
                    return UNPARSEABLE
                return found if isinstance(found, dict) else UNPARSEABLE
    return UNPARSEABLE


def _points(text: str, full_name: str) -> dict[str, Any]:
    """The ``dataPointsByNameMap`` of a container, name to data point."""
    container = _object(text, full_name)
    points = container.get("dataPointsByNameMap") if isinstance(container, dict) else None
    return points if isinstance(points, dict) else {}


def _figure(points: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    """The first of ``names`` present as a data point with a numeric value."""
    for name in names:
        point = points.get(name)
        if isinstance(point, dict) and isinstance(point.get("value"), (int, float)):
            return point
    return {}


def _leaf_point(text: str, full_name: str) -> dict[str, Any] | _Absent:
    """A leaf data point — one carrying ``value`` and its own ``asOfDate``."""
    return _object(text, full_name)


def _leaf_value(point: dict[str, Any] | _Absent) -> float | None:
    """The leaf's number, or None when it is absent, unparseable or not numeric."""
    if isinstance(point, dict) and isinstance(point.get("value"), (int, float)):
        return float(point["value"])
    return None


def _point_as_of(point: Any) -> str:
    """A data point's own ``asOfDate`` as ISO, or "" when it carries none."""
    if not isinstance(point, dict):
        return ""
    return _iso(point.get("asOfDate") or point.get("formattedAsOfDate"))


def _iso(as_of: Any) -> str:
    """An iShares ``asOfDate`` (20260916, or its formatted string) as ISO."""
    digits = "".join(ch for ch in str(as_of or "") if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return str(as_of or "")


def _complete(record: dict[str, Any]) -> bool:
    """Whether a record is as complete as a fresh fetch would be.

    The cache-hit guard and the cache-write guard are the same test on purpose:
    a partial page must not be served for the next 24 hours either. The version
    is part of it, so a record written before the reader gained a field is
    re-fetched once rather than served with that field missing.
    """
    if record.get("version") != _CACHE_VERSION:
        return False
    figures = record.get("figures")
    if not isinstance(figures, dict) or not all(field in figures for field in NEEDED_FIELDS):
        return False
    return record.get("expense_pct") is not None and record.get("nav") is not None


def fetch_characteristics(entry: dict[str, Any]) -> dict[str, Any]:
    """Fetch the proxy's published figures, cached for a day.

    Returns the figures as percentages, the expense ratio, the proxy's NAV with
    its own as-of date, and a ``warnings`` list. A figure the page did not carry
    comes back as ``None`` with a warning naming it, never as a plausible zero,
    and a record that did not fully parse is not written to the cache. Raises
    ``ApiError`` when the page is unreachable or has been restructured.

    Takes the structure, not the fund symbol: the cache is the proxy's, so the
    record is shared by every fund mapped to it and must not name one of them.
    """
    proxy = entry["proxy"]
    path = _cache_path(proxy)
    if path.is_file() and time.time() - path.stat().st_mtime < _TTL:
        try:
            cached = json.loads(path.read_text())
        except (OSError, ValueError):
            cached = None
        # Completeness, not mere presence: a cached record missing the NAV or
        # the fee is a record this run must re-fetch, not serve.
        if isinstance(cached, dict) and _complete(cached):
            return cached

    text = html.unescape(_fetch(entry["url"]))
    fundamentals = _points(text, "fundamentalsAndRisk.default")
    if not fundamentals:
        # Read the block once more to say why, on a path that is about to raise
        # anyway: the caller needs to know absent from unparseable here.
        block = _object(text, "fundamentalsAndRisk.default")
        raise ApiError(
            f"{entry['url']} no longer carries the fundamentals block "
            f"({_why(block, 'fundamentalsAndRisk.default')})",
            code="ISHARES_PARSE",
        )
    figures: dict[str, float] = {}
    as_of = ""
    for field, names in _FIGURE_NAMES.items():
        point = _figure(fundamentals, names)
        if not point:
            continue
        figures[field] = round(float(point["value"]), 6)
        as_of = max(as_of, _iso(point.get("asOfDate") or point.get("formattedAsOfDate")))
    missing = [field for field in NEEDED_FIELDS if field not in figures]
    if missing:
        raise ApiError(
            f"{entry['url']} published none of {', '.join(missing)}", code="ISHARES_PARSE"
        )

    warnings: list[str] = []
    expense_point = _leaf_point(text, "fundHeader.fees.expr")
    expense = _leaf_value(expense_point)
    if expense is None:
        warnings.append(
            f"expense_pct: {_why(expense_point, 'fundHeader.fees.expr')} on the iShares "
            f"{proxy} page — expense_ratio_pct, expense_pct, calculated_ytm_pct and gap_bp "
            "are null"
        )
    nav_point = _leaf_point(text, "fundHeader.fundNav.navAmount")
    nav = _leaf_value(nav_point)
    if nav is None:
        warnings.append(
            f"nav: {_why(nav_point, 'fundHeader.fundNav.navAmount')} on the iShares {proxy} "
            "page — par_per_share is null"
        )

    result = {
        "version": _CACHE_VERSION,
        "retrieved": date.today().isoformat(),
        "proxy": proxy,
        "url": entry["url"],
        "as_of": as_of,
        "nav_as_of": _point_as_of(nav_point),
        "figures": figures,
        "expense_pct": None if expense is None else round(expense, 3),
        "nav": nav,
        "warnings": warnings,
    }
    if _complete(result):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result))
        except OSError:
            pass
    return result


def _input_needed(message: str, **extra: Any) -> InvalidInput:
    """The exit-2 error that asks the caller for the figures instead."""
    return InvalidInput(message, code="INPUT_NEEDED", needed=list(NEEDED_FIELDS), **extra)


def analyse(symbol: str) -> dict[str, Any]:
    """Decompose one fund's published yield into curve plus spread."""
    key = (symbol or "").strip().upper()
    entry = KNOWN_FUNDS.get(key)
    if entry is None:
        raise _input_needed(
            f"no index proxy for {key or symbol!r}: supply the figures from your broker's page",
            proxy=None,
            known=sorted(KNOWN_FUNDS),
        )
    try:
        fetched = fetch_characteristics(entry)
    except ApiError as exc:
        raise _input_needed(
            f"the iShares {entry['proxy']} page is unreadable ({exc}); "
            "supply the figures from your broker's page",
            proxy=entry["proxy"],
            source=entry["url"],
        ) from exc

    figures = fetched["figures"]
    buckets = entry["buckets"]
    coupon_rate = figures["coupon_pct"] / 100.0
    published_pct = round(figures["ytm_pct"], 3)
    # None, never 0.0: a fee the page did not carry must not be reported as a
    # free fund, and an absent NAV must not become a share count of zero. Both
    # arrive here as None from fetch_characteristics.
    expense_pct = fetched.get("expense_pct")
    nav = fetched.get("nav")

    longest = longest_bucket_years(buckets)
    built = rates.build()
    items = sorted((float(tenor), value) for tenor, value in built["par_curve"].items())
    check_curve_covers([tenor for tenor, _ in items], longest)
    curve = bondmath.bootstrap(
        [tenor for tenor, _ in items], [value / 100.0 for _, value in items], FREQ, MAX_YEARS
    )

    cashflows = bucket_cashflows(buckets, coupon_rate, FREQ)
    spread_bp = blended_spread_bp(entry["sectors"])
    treasury_equivalent_pct = round(
        _yield_from_cashflows(cashflows, bondmath.price_on_curve(cashflows, curve, 0.0, FREQ), FREQ)
        * 100.0,
        3,
    )
    gross_pct = round(
        _yield_from_cashflows(
            cashflows,
            bondmath.price_on_curve(cashflows, curve, spread_bp / 10000.0, FREQ),
            FREQ,
        )
        * 100.0,
        3,
    )
    # The published yield to maturity is gross of the fund's fee; the calculated
    # one is what a shareholder keeps, so the gap carries the expense ratio. No
    # fee, no calculated yield: null rather than a number the fee should move.
    calculated_pct = None if expense_pct is None else round(gross_pct - expense_pct, 3)
    # gap_bp = calculated - published in basis points; negative means the model
    # produced less yield than the fund publishes. See assumptions.gap_expectation.
    gap_bp = None if calculated_pct is None else round((calculated_pct - published_pct) * 100.0, 1)
    model_wal = round(weighted_average_life(buckets), 2)

    return {
        "symbol": key,
        "as_of": {
            "fund": fetched["as_of"],
            "curve": built["as_of"]["curve"],
            # The NAV is published on its own clock and can be a day newer than
            # the figures it is paired with; nav_source says what that means.
            "nav": fetched.get("nav_as_of") or None,
            "retrieved": fetched["retrieved"],
        },
        "characteristics": {
            "ytm_pct": published_pct,
            "coupon_pct": round(figures["coupon_pct"], 3),
            "duration_years": round(figures["duration_years"], 3),
            "wal_years": model_wal,
            "wal_source": _WAL_SOURCE,
            "sec_yield_pct": round(figures["sec_yield_pct"], 3),
            "distribution_yield_pct": (
                None
                if figures.get("distribution_yield_pct") is None
                else round(figures["distribution_yield_pct"], 3)
            ),
            "expense_ratio_pct": expense_pct,
            "source": f"iShares {entry['proxy']} product page (index proxy for {key})",
        },
        "yield_decomposition": {
            "treasury_equivalent_pct": treasury_equivalent_pct,
            "blended_spread_bp": round(spread_bp, 1),
            "expense_pct": expense_pct,
            "calculated_ytm_pct": calculated_pct,
            "published_ytm_pct": published_pct,
            "gap_bp": gap_bp,
        },
        "par_per_share": (
            None
            if nav is None
            else round(par_per_share(nav, coupon_rate, published_pct / 100.0, buckets, FREQ), 2)
        ),
        "price_map": _price_map(cashflows, published_pct / 100.0, FREQ),
        "assumptions": _assumptions(key, entry, buckets, figures, model_wal, spread_bp),
        "warnings": list(fetched.get("warnings") or []),
        "circularity_note": CIRCULARITY_NOTE,
    }


def _assumptions(
    symbol: str,
    entry: dict[str, Any],
    buckets: list[tuple[float, float]],
    figures: dict[str, float],
    model_wal: float,
    spread_bp: float,
) -> dict[str, Any]:
    """What a reader has to know to use the decomposition correctly."""
    published_wal = figures.get("wal_years")
    return {
        "frequency": FREQ,
        "max_years": MAX_YEARS,
        "proxy": entry["proxy"],
        "proxy_url": entry["url"],
        "sector_spreads_bp": {name: spread for name, (_, spread) in entry["sectors"].items()},
        "maturity_buckets": [
            {"weight_pct": weight, "midpoint_years": maturity} for weight, maturity in buckets
        ],
        "spread_convention": _SPREAD_CONVENTION,
        "comparison": _COMPARISON,
        "gap_expectation": _GAP_EXPECTATION,
        "expense_source": _EXPENSE_SOURCE.format(proxy=entry["proxy"]),
        "nav_source": _NAV_SOURCE.format(proxy=entry["proxy"]),
        "index_proxy": _INDEX_PROXY.format(
            proxy=entry["proxy"],
            symbol=symbol,
            clause=_INDEX_CLAUSES.get(symbol, _INDEX_CLAUSE_DEFAULT),
        ),
        "price_map_note": _PRICE_MAP_NOTE,
        "wal_check": {
            "model_years": model_wal,
            "proxy_published_years": published_wal,
        },
        "note": _MODEL_NOTE,
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"fund.py: {message}")


def main(argv: list[str] | None = None) -> int:
    """Decompose the fund named on the command line, one JSON object to stdout."""

    def go(args: list[str]) -> dict[str, Any]:
        parser = _Parser(prog="fund.py", add_help=False)
        parser.add_argument("symbol", help="fund ticker, e.g. BND")
        return analyse(parser.parse_args(args).symbol)

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
