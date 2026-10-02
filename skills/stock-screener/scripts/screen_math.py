"""stock-screener: screen a universe of companies on fundamentals, then on price.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python screen_math.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {"years": [2022, 2023, 2024, 2025],        # oldest first; the last is the latest fiscal year
     "preset": "growth",                        # optional: see PRESETS
     "criteria": {"min_revenue_cagr": 0.25},    # optional overrides merged onto the preset
     "companies": [
       {"cik": 1, "ticker": "AAA", "name": "...",
        "financial": false,                     # optional: a bank, insurer or lender by its filings
        "held": false,                          # optional: passed through to the output row
        "annual": {"revenue": {"2022": 1.0e9, ...},     # one series per metric, keyed by year
                   "gross_profit": {...}, "cost_of_revenue": {...}, "operating_income": {...},
                   "net_income": {...}, "ocf": {...}, "capex": {...}, "sbc": {...},
                   "diluted_shares": {...}, "dividends": {...}, "acquisitions": {...},
                   "interest_expense": {...}, "income_tax": {...}, "buybacks": {...}},
        "balance": {"equity": 2.0e9, "debt": 2.0e8, "cash": 1.0e8, "assets": 4.0e9,   # optional,
                    "current_assets": 1.5e9, "current_liabilities": 1.0e9},            # latest year end
        "balance_prior": {"assets": ..., "debt": ..., "current_assets": ...,           # optional,
                          "current_liabilities": ...},                                  # a year earlier
        "quarter": {"revenue": 6.5e8, "revenue_year_ago": 5.0e8,       # optional, latest
                    "period": "CY2026Q2"},                                # reported quarter
        "market": {"market_cap": 3.0e9, "enterprise_value": 3.1e9,     # optional: its presence
                   "price": 30.0, "financial": false, "sector": "Technology",   # runs the price stage
                   "momentum": 0.12}}]}

Output JSON contract (stdout)::

    {"preset": "growth", "criteria": {...merged...}, "universe": N, "dropped_incomplete": N,
     "funnel": [{"stage": "universe", "remaining": N}, {"stage": "min_revenue", ...}, ...],
     "fail_counts": {"min_revenue_cagr": N, ...},
     "companies": [{"cik", "ticker", "name", "metrics": {...}, "failed": [...],
                    "not_reported": [...], "passes_fundamentals": bool,
                    "passes_price": bool | null, "flags": [...], "held": bool}],
     "survivors": [...companies passing every applied stage, ranked...],
     "near_misses": [...up to 15 failing exactly one fundamental criterion...],
     "rank_by": "growth_gap"}

Method. A company needs a revenue figure for every year in ``years`` or it is dropped
(``dropped_incomplete``). ``revenue_cagr`` spans first to last year; ``revenue_growth`` is each
year over the one before. Gross margin uses ``gross_profit``, else revenue minus
``cost_of_revenue``. Operating margins use ``operating_income``; when a company does not tag it
in both the first and last year, net income stands in and ``margin_basis`` is ``"net"``.
``ebit_latest`` is operating income, else net income plus income tax plus interest.

Free cash flow is ``ocf - capex`` and is null in a year with no capex figure: a missing capex is
unknown, not zero (``capex_reported`` false, flag ``CAPEX_NOT_REPORTED``), so the cash tests fail
for that company rather than pass on operating cash flow alone. ``fcf_after_sbc`` also subtracts
stock-based pay. ``fcf_norm`` / ``fcf_after_sbc_norm`` is the cash figure the price stage uses:
the LOWER of last year's and the average margin over the years reported applied to last year's
revenue, so one unusually good year (a cyclical peak, a working-capital swing) does not make a
company look cheap.

Share growth is the geometric mean of year-over-year diluted-share ratios, skipping any ratio
outside 0.67-1.5x as a split or a first year after listing (``split_detected``).

Leverage. ``net_debt`` is ``debt - cash`` when a debt figure is reported.
``max_net_debt_to_ebit`` passes on net cash, or on ``net_debt / ebit`` at or under the limit;
with no debt figure it falls back to ``interest_cover`` (ebit / interest) of at least 6, and a
company reporting neither debt nor interest is taken as debt-free. ``leverage_basis`` says which
applied (``net_debt``, ``interest_cover``, ``none_reported``). Debt with no positive ebit to
service it fails. ``debt_to_equity`` (``debt / equity``, null when equity is not positive) is
kept for ``max_debt_to_equity``.

``roce`` is ebit over capital employed (``assets - current_liabilities``). ``current_ratio`` is
current assets over current liabilities. ``f_score`` is Piotroski's nine year-over-year checks
(profit, cash flow, rising return on assets, cash above profit, falling debt/assets, rising
current ratio, no new shares, rising gross margin, rising asset turnover), one point each;
a check that cannot be computed scores nothing (``f_signals`` lists each as true, false or
null). ``acquisition_pct`` is cash paid for acquisitions over the period as a share of revenue;
above 10% the growth is partly bought (flag ``ACQUISITIVE``).

``expected_growth`` is the growth the screen credits the company with. It starts
(``start_growth``) from the LOWER of the multi-year growth rate and recent growth -- the latest
year, averaged with the latest quarter when one is reported, since a single quarter is noisy --
and moves in a straight line to ``terminal_growth`` over ten years; the figure is the average
annual rate along that path. Fast growth rarely lasts ten years and neither does a sharp fall,
so this is compared with what the price implies instead of the raw trailing rate.

Criteria (``None`` or absent = not applied), fundamental first, then price: ``min_revenue``,
``min_revenue_cagr``, ``min_growth_each_year``, ``min_latest_year_growth``,
``min_latest_quarter_growth``, ``min_gross_margin``, ``operating_margin_improving``,
``min_operating_margin``, ``min_roce``, ``min_fcf_margin``, ``fcf_positive_latest``,
``fcf_positive_all_years``, ``net_income_positive_all_years``, ``pays_dividend_all_years``,
``max_share_growth``, ``max_sbc_pct``, ``max_debt_to_equity``, ``max_net_debt_to_ebit``,
``min_current_ratio``, ``max_debt_to_working_capital``, ``min_f_score``, ``max_payout_to_fcf``;
then ``min_market_cap``, ``min_fcf_yield``, ``min_earnings_yield``, ``min_shareholder_yield``,
``max_pe``, ``max_ps``, ``max_pe_times_pb``, ``max_implied_growth``, ``min_growth_gap``,
``min_momentum``. A criterion whose metric is missing fails, except the ones companies often do
not tag -- ``min_gross_margin``, ``max_debt_to_equity``, ``min_latest_quarter_growth``,
``max_sbc_pct`` -- which are listed in ``not_reported`` instead (a missing latest quarter also
raises the flag ``LATEST_QUARTER_NOT_REPORTED``).

Financial companies (banks, insurers, lenders, brokers) are excluded by default because their
operating cash flow carries customer money and makes cash-based figures meaningless: a company
marked ``financial`` fails ``financial_filer`` before any other test, and one whose ``market``
block says ``financial`` fails ``financial_excluded`` at the price stage.
``include_financials: true`` keeps both. ``exclude_sectors`` (a list of ``market.sector`` names)
fails ``sector_excluded`` the same way; the cash-based presets leave out Real Estate, whose
property purchases are investment rather than upkeep, so free cash flow misstates them.

The price stage runs for companies with a ``market`` block. ``implied_growth`` is the flat
10-year cash growth that makes a DCF (``discount_rate`` 10%, ``terminal_growth`` 3%, both
criteria keys) equal the enterprise value (market cap when EV is missing); null when the cash
figure is not positive or no rate in -50%..150% reproduces the value. It and ``fcf_yield`` use
the normalized cash figure after stock pay unless ``fcf_basis`` is ``"fcf"``: stock pay is a
real cost to shareholders. ``growth_gap`` is ``expected_growth - implied_growth``.
``earnings_yield`` is ebit / enterprise value, ``pe`` market cap / net income (null when not
positive), ``ps`` market cap / revenue, ``pb`` market cap / equity, ``pe_times_pb`` their
product (Graham's 22.5 test), ``shareholder_yield`` dividends plus buybacks paid last year over
market cap, ``payout_to_fcf`` the same payout over free cash flow. ``momentum`` is passed
through from ``market`` (the 12-month price change skipping the latest month). ``magic_rank``
is the sum of a survivor's rank on earnings yield and its rank on ``roce`` (Greenblatt's
formula; lower is better).

Each company carries ``flags``: ``CASH_OUTRUNS_PROFIT`` when free cash flow after stock pay
exceeds the operating margin by more than 15 points (customer float or working-capital timing;
the cash-based price figures overstate the value), ``CASH_ABOVE_ITS_AVERAGE`` when last year's
cash margin is more than 10 points above the multi-year average (the average was used),
``PROFIT_ABOVE_OPERATING_PROFIT`` when net income exceeds operating income (a one-off gain;
the P/E flatters), ``CAPEX_NOT_REPORTED``, ``LATEST_QUARTER_NOT_REPORTED``, ``ACQUISITIVE``, ``PRICE_FALLING``
when momentum is below -20%, ``SPLIT_OR_LISTING_YEAR_SKIPPED`` when a share-count year was
left out, ``MISSCALED`` when a flow figure (named in ``metrics.misscaled``) sat below
1/100,000th of revenue -- a filer's unscaled tag -- and was dropped. A revenue series whose
years differ by more than 1,000x is dropped as incomplete. ``near_misses`` excludes companies
that failed only the revenue-size cutoff, financial filers, and companies with no ticker.

Survivors are ranked by the preset's ``rank_by`` when price data is present (lowest first for
``magic_rank``, ``pe``, ``pe_times_pb`` and ``ps``; highest first otherwise), else by
``revenue_cagr``. Money unrounded, ratios 4 dp.
"""

from __future__ import annotations

import copy
import json
import math
import sys

FUNDAMENTAL = (
    "min_revenue",
    "min_revenue_cagr",
    "min_growth_each_year",
    "min_latest_year_growth",
    "min_latest_quarter_growth",
    "min_gross_margin",
    "operating_margin_improving",
    "min_operating_margin",
    "min_roce",
    "min_fcf_margin",
    "fcf_positive_latest",
    "fcf_positive_all_years",
    "net_income_positive_all_years",
    "pays_dividend_all_years",
    "max_share_growth",
    "max_sbc_pct",
    "max_debt_to_equity",
    "max_net_debt_to_ebit",
    "min_current_ratio",
    "max_debt_to_working_capital",
    "min_f_score",
    "max_payout_to_fcf",
)
PRICE = (
    "min_market_cap",
    "min_fcf_yield",
    "min_earnings_yield",
    "min_shareholder_yield",
    "max_pe",
    "max_ps",
    "max_pe_times_pb",
    "max_implied_growth",
    "min_growth_gap",
    "min_momentum",
)
SETTINGS = (
    "discount_rate",
    "terminal_growth",
    "include_financials",
    "exclude_sectors",
    "rank_by",
    "fcf_basis",
)
FCF_BASES = ("fcf_after_sbc", "fcf")
# Ranked lowest first; every other rank key is highest first.
RANK_ASCENDING = {"magic_rank", "pe", "pe_times_pb", "ps"}
# Rank keys that exist without a price, so an unpriced run can still use them.
RANK_UNPRICED = {"revenue_cagr", "roce", "f_score", "expected_growth"}
# Cash after stock pay this far above the operating margin usually means customer money or
# working-capital timing, not earnings: the cash-based price figures overstate the value.
CASH_OUTRUNS_PROFIT_PP = 0.15
# Last year's cash margin this far above the multi-year average: the average was used instead.
CASH_ABOVE_AVERAGE_PP = 0.10
# A flow figure below 1/100,000th of revenue is a filer's scale error (tagged in millions or
# thousands without the scale), not a real number: dropped and flagged MISSCALED.
MISSCALE_RATIO = 1e-5
# With no debt figure, operating profit must cover interest this many times to pass the
# leverage test: about three times ebit of debt at a 5-6% rate.
INTEREST_COVER_STAND_IN = 6.0
# Cash paid for acquisitions above this share of the period's revenue: growth partly bought.
ACQUISITIVE_PCT = 0.10
PRICE_FALLING = -0.20
FADE_YEARS = 10
# One-sided tolerance for "no new shares": stock pay alone moves a diluted count a little.
NO_NEW_SHARES_TOLERANCE = 1.005
FLOWS = (
    "gross_profit",
    "cost_of_revenue",
    "operating_income",
    "net_income",
    "ocf",
    "capex",
    "sbc",
)
LENIENT = {"min_gross_margin", "max_debt_to_equity", "min_latest_quarter_growth", "max_sbc_pct"}

PRESETS = {
    # Fast, steady, still-growing businesses that earn cash and do not dilute much.
    "growth": {
        "min_revenue": 500e6,
        "min_revenue_cagr": 0.20,
        "min_growth_each_year": 0.10,
        "min_latest_year_growth": 0.15,
        "min_latest_quarter_growth": 0.10,
        "min_gross_margin": 0.40,
        "operating_margin_improving": True,
        "fcf_positive_latest": True,
        "max_share_growth": 0.05,
        "min_market_cap": 1e9,
        "rank_by": "growth_gap",
    },
    # Graham/Buffett-style: steady cash, serviceable debt, no dilution, improving year over
    # year (Piotroski), cheap on earnings and on normalized cash.
    "value": {
        "min_revenue": 500e6,
        "min_revenue_cagr": 0.0,
        # A cheap company whose latest quarter is already falling fast is the usual trap.
        "min_latest_quarter_growth": -0.05,
        "min_fcf_margin": 0.05,
        "fcf_positive_all_years": True,
        "max_share_growth": 0.02,
        "max_net_debt_to_ebit": 3.0,
        "min_f_score": 5,
        "min_market_cap": 1e9,
        "min_fcf_yield": 0.06,
        "max_pe": 15,
        "exclude_sectors": ["Real Estate"],
        "rank_by": "fcf_yield",
    },
    # Durable compounders: high returns on the capital employed, cash every year, no dilution,
    # serviceable debt; price assumes less growth than the screen credits them with.
    "quality": {
        "min_revenue": 1e9,
        "min_revenue_cagr": 0.08,
        # Annual figures lag: a quality company whose latest quarter already shrank is the
        # most common survivor that fails on reading.
        "min_latest_quarter_growth": 0.0,
        "min_roce": 0.15,
        "fcf_positive_all_years": True,
        "max_share_growth": 0.01,
        "max_net_debt_to_ebit": 3.0,
        "min_market_cap": 2e9,
        "min_growth_gap": 0.0,
        "exclude_sectors": ["Real Estate"],
        "rank_by": "growth_gap",
    },
    # Growth at a reasonable price.
    "garp": {
        "min_revenue": 500e6,
        "min_revenue_cagr": 0.12,
        "min_latest_quarter_growth": 0.08,
        "min_operating_margin": 0.10,
        "fcf_positive_all_years": True,
        "max_share_growth": 0.03,
        "min_market_cap": 1e9,
        "max_pe": 25,
        "min_growth_gap": 0.03,
        "rank_by": "growth_gap",
    },
    # Greenblatt's magic formula: good businesses (return on capital) at cheap prices
    # (earnings yield), ranked on the two together. He leaves out financials and utilities.
    # The 15% floor keeps the list of companies to price short; the ranking does the rest.
    "magic": {
        "min_revenue": 500e6,
        "min_roce": 0.15,
        # Not in Greenblatt's rule: keeps out companies whose operating profit is a one-off.
        "fcf_positive_latest": True,
        "min_market_cap": 1e9,
        "min_earnings_yield": 0.0,
        "exclude_sectors": ["Utilities", "Real Estate"],
        "rank_by": "magic_rank",
    },
    # Graham's defensive investor: large, liquid balance sheet, profit and a dividend every
    # year, growing, and a price under 15x earnings with P/E x P/B under 22.5.
    "graham": {
        "min_revenue": 500e6,
        "min_revenue_cagr": 0.0,
        "net_income_positive_all_years": True,
        "pays_dividend_all_years": True,
        "min_current_ratio": 2.0,
        "max_debt_to_working_capital": 1.0,
        "min_market_cap": 1e9,
        "max_pe": 15,
        "max_pe_times_pb": 22.5,
        "rank_by": "pe_times_pb",
    },
    # Cash returned to owners: dividends plus buybacks, paid out of free cash flow, with a
    # share count that is not growing and debt that is serviceable.
    "payout": {
        "min_revenue": 500e6,
        "min_revenue_cagr": 0.0,
        "fcf_positive_all_years": True,
        "max_share_growth": 0.0,
        "max_net_debt_to_ebit": 3.0,
        "max_payout_to_fcf": 1.0,
        "min_market_cap": 1e9,
        "min_shareholder_yield": 0.04,
        "exclude_sectors": ["Real Estate"],
        "rank_by": "shareholder_yield",
    },
}


def _r4(v):
    return None if v is None else round(v, 4)


def _num(v):
    return (
        v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
    )


def _series(annual: dict, key: str, years: list[int]) -> list:
    s = annual.get(key) or {}
    return [_num(s.get(str(y), s.get(y))) for y in years]


def implied_growth(fcf, value, discount_rate=0.10, terminal_growth=0.03, years=10):
    """Flat stage-1 FCF growth whose DCF equals ``value``; None when none does."""
    if not fcf or fcf <= 0 or not value or value <= 0 or discount_rate <= terminal_growth:
        return None

    def pv(g: float) -> float:
        total, f = 0.0, fcf
        for t in range(1, years + 1):
            f *= 1 + g
            total += f / (1 + discount_rate) ** t
        return (
            total
            + f
            * (1 + terminal_growth)
            / (discount_rate - terminal_growth)
            / (1 + discount_rate) ** years
        )

    lo, hi = -0.5, 1.5
    if pv(lo) > value or pv(hi) < value:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if pv(mid) < value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def expected_growth(start, terminal_growth=0.03, years=FADE_YEARS):
    """Average annual growth along a straight line from ``start`` to ``terminal_growth``."""
    if start is None:
        return None
    start = max(start, -0.9)  # revenue cannot fall by more than all of it
    total = 1.0
    for t in range(years):
        total *= 1 + terminal_growth + (start - terminal_growth) * (1 - t / years)
    return total ** (1 / years) - 1


def _normalized(cash: list, rev: list):
    """The lower of last year's cash and the average margin applied to last year's revenue."""
    if cash[-1] is None:
        return None, None
    margins = [c / r for c, r in zip(cash, rev) if c is not None]
    avg = sum(margins) / len(margins)
    return min(cash[-1], avg * rev[-1]), avg


def _f_score(rev, ni, ocf, gm, shares, bal, prior) -> tuple[int, dict]:
    """Piotroski's nine checks, latest year against the one before; unknown scores nothing."""
    a1, a0 = _num(bal.get("assets")), _num(prior.get("assets"))
    d1, d0 = _num(bal.get("debt")), _num(prior.get("debt"))
    ca1, cl1 = _num(bal.get("current_assets")), _num(bal.get("current_liabilities"))
    ca0, cl0 = _num(prior.get("current_assets")), _num(prior.get("current_liabilities"))

    def ratio(x, y):
        return x / y if x is not None and y else None

    def up(x, y):
        return None if x is None or y is None else x > y

    sig = {
        "profit": None if ni[-1] is None else ni[-1] > 0,
        "cash_flow": None if ocf[-1] is None else ocf[-1] > 0,
        "return_on_assets_up": up(ratio(ni[-1], a1), ratio(ni[-2], a0)),
        "cash_above_profit": up(ocf[-1], ni[-1]),
        # No debt reported in either year counts as debt not having risen.
        "debt_to_assets_down": None
        if not a1 or not a0
        else (d1 or 0) / a1 <= (d0 or 0) / a0,
        "current_ratio_up": up(ratio(ca1, cl1), ratio(ca0, cl0)),
        "no_new_shares": None
        if not shares[-1] or not shares[-2] or not 0.67 < shares[-1] / shares[-2] < 1.5
        else shares[-1] / shares[-2] <= NO_NEW_SHARES_TOLERANCE,
        "gross_margin_up": up(gm[-1], gm[-2]),
        "asset_turnover_up": up(ratio(rev[-1], a1), ratio(rev[-2], a0)),
    }
    return sum(1 for v in sig.values() if v), sig


def metrics(company: dict, years: list[int]) -> dict | None:
    annual = company.get("annual") or {}
    rev = _series(annual, "revenue", years)
    if any(v is None or v <= 0 for v in rev) or max(rev) / min(rev) > 1000:
        return None
    misscaled = []
    annual = dict(annual)
    for key in FLOWS:
        vals = _series(annual, key, years)
        if any(v is not None and v != 0 and abs(v) < r * MISSCALE_RATIO for v, r in zip(vals, rev)):
            misscaled.append(key)
            annual[key] = {}
    n = len(years) - 1
    first, last = rev[0], rev[-1]
    gp_s, cor_s = _series(annual, "gross_profit", years), _series(annual, "cost_of_revenue", years)
    gm = [
        (g / r) if g is not None else ((r - c) / r if c is not None else None)
        for g, c, r in zip(gp_s, cor_s, rev)
    ]
    op = _series(annual, "operating_income", years)
    ni = _series(annual, "net_income", years)
    interest = _series(annual, "interest_expense", years)[-1]
    interest = abs(interest) if interest is not None else None
    tax = _series(annual, "income_tax", years)[-1]
    ebit, ebit_basis = op[-1], "operating"
    if ebit is None and ni[-1] is not None and tax is not None:
        ebit, ebit_basis = ni[-1] + tax + (interest or 0), "net_plus_tax_and_interest"
    basis = "operating"
    if op[0] is None or op[-1] is None:
        op, basis = ni, "net"
    ocf, capex = _series(annual, "ocf", years), _series(annual, "capex", years)
    fcf = [(o - abs(c)) if o is not None and c is not None else None for o, c in zip(ocf, capex)]
    sbc_s = _series(annual, "sbc", years)
    after = [(f - (s or 0)) if f is not None else None for f, s in zip(fcf, sbc_s)]
    fcf_norm, fcf_avg_margin = _normalized(fcf, rev)
    after_norm, after_avg_margin = _normalized(after, rev)
    shares = _series(annual, "diluted_shares", years)
    ratios = [b / a for a, b in zip(shares, shares[1:]) if a and b and a > 0]
    normal = [q for q in ratios if 0.67 < q < 1.5]
    share_growth = math.prod(normal) ** (1 / len(normal)) - 1 if normal else None
    sbc = sbc_s[-1]
    bal = dict(company.get("balance") or {})
    if bal.get("debt") is None and bal.get("long_term_debt") is not None:
        bal["debt"] = bal["long_term_debt"]
    prior = company.get("balance_prior") or {}
    eq, debt, cash = _num(bal.get("equity")), _num(bal.get("debt")), _num(bal.get("cash"))
    assets = _num(bal.get("assets"))
    ca, cl = _num(bal.get("current_assets")), _num(bal.get("current_liabilities"))
    net_debt = debt - (cash or 0) if debt is not None else None
    cover = ebit / interest if ebit is not None and interest else None
    if net_debt is not None:
        leverage_basis = "net_debt"
    elif cover is not None:
        leverage_basis = "interest_cover"
    else:
        leverage_basis = "none_reported"
    employed = assets - cl if assets is not None and cl is not None else None
    div = _series(annual, "dividends", years)
    buy = _series(annual, "buybacks", years)[-1]
    payout = None
    if div[-1] is not None or buy is not None:
        payout = abs(div[-1] or 0) + abs(buy or 0)
    acq = [abs(a) for a in _series(annual, "acquisitions", years) if a is not None]
    q = company.get("quarter") or {}
    qr, qa = _num(q.get("revenue")), _num(q.get("revenue_year_ago"))
    growth = [b / a - 1 for a, b in zip(rev, rev[1:])]
    cagr = (last / first) ** (1 / n) - 1
    lq = qr / qa - 1 if qr and qa and qa > 0 else None
    f_score, f_signals = _f_score(rev, ni, ocf, gm, shares, bal, prior)
    return {
        "revenue_latest": last,
        "misscaled": misscaled,
        "revenue_cagr": _r4(cagr),
        "revenue_growth": [_r4(g) for g in growth],
        "latest_quarter_growth": _r4(lq),
        "latest_quarter": q.get("period"),
        "start_growth": _r4(min(cagr, growth[-1] if lq is None else (growth[-1] + lq) / 2)),
        "gross_margin": _r4(gm[-1]),
        "operating_margin_first": _r4(op[0] / first) if op[0] is not None else None,
        "operating_margin_latest": _r4(op[-1] / last) if op[-1] is not None else None,
        "margin_basis": basis,
        "net_income_latest": ni[-1],
        "operating_income_latest": _series(annual, "operating_income", years)[-1],
        "net_income_positive_years": sum(1 for v in ni if v is not None and v > 0),
        "ebit_latest": ebit,
        "ebit_basis": ebit_basis if ebit is not None else None,
        "capex_reported": capex[-1] is not None,
        "fcf_latest": fcf[-1],
        "fcf_margin": _r4(fcf[-1] / last) if fcf[-1] is not None else None,
        "fcf_after_sbc_latest": after[-1],
        "fcf_after_sbc_margin": _r4(after[-1] / last) if after[-1] is not None else None,
        "fcf_norm": fcf_norm,
        "fcf_after_sbc_norm": after_norm,
        "fcf_after_sbc_margin_avg": _r4(after_avg_margin),
        "fcf_positive_years": sum(1 for f in fcf if f is not None and f > 0),
        "fcf_years": sum(1 for f in fcf if f is not None),
        "share_growth": _r4(share_growth),
        "split_detected": len(normal) < len(ratios),
        "sbc_pct": _r4(sbc / last) if sbc is not None else None,
        "equity": eq,
        "debt": debt,
        "net_debt": net_debt,
        "net_debt_to_ebit": _r4(net_debt / ebit) if net_debt is not None and ebit and ebit > 0 else None,
        "interest_cover": _r4(cover),
        "leverage_basis": leverage_basis,
        "debt_to_equity": _r4(debt / eq) if debt is not None and eq and eq > 0 else None,
        "roce": _r4(ebit / employed) if ebit is not None and employed and employed > 0 else None,
        "current_ratio": _r4(ca / cl) if ca is not None and cl and cl > 0 else None,
        "working_capital": ca - cl if ca is not None and cl is not None else None,
        "dividend_years": sum(1 for d in div if d),
        "payout_latest": payout,
        "payout_to_fcf": _r4(payout / fcf[-1]) if payout is not None and fcf[-1] and fcf[-1] > 0 else None,
        "acquisition_pct": _r4(sum(acq) / sum(rev)) if acq else None,
        "f_score": f_score,
        "f_signals": f_signals,
    }


def _leverage_ok(m: dict, want: float):
    """True / False for ``max_net_debt_to_ebit``, or None when nothing can be judged."""
    net_debt, ebit = m["net_debt"], m["ebit_latest"]
    if net_debt is not None:
        if net_debt <= 0:
            return True
        if ebit is None:
            return None
        return ebit > 0 and net_debt / ebit <= want
    if m["interest_cover"] is not None:
        return m["interest_cover"] >= INTEREST_COVER_STAND_IN
    return True  # neither debt nor interest reported: taken as debt-free


def _fundamental_test(name: str, m: dict, want, n_years: int):
    """True / False, or None when the metric is missing."""

    def at_least(key):
        return None if m[key] is None else m[key] >= want

    def at_most(key):
        return None if m[key] is None else m[key] <= want

    if name == "min_revenue":
        return m["revenue_latest"] >= want
    if name == "min_revenue_cagr":
        return m["revenue_cagr"] >= want
    if name == "min_growth_each_year":
        return min(m["revenue_growth"]) >= want
    if name == "min_latest_year_growth":
        return m["revenue_growth"][-1] >= want
    if name == "min_latest_quarter_growth":
        return at_least("latest_quarter_growth")
    if name == "min_gross_margin":
        return at_least("gross_margin")
    if name == "operating_margin_improving":
        if not want:
            return True
        a, b = m["operating_margin_first"], m["operating_margin_latest"]
        return None if a is None or b is None else b > a
    if name == "min_operating_margin":
        return at_least("operating_margin_latest")
    if name == "min_roce":
        return at_least("roce")
    if name == "min_fcf_margin":
        return at_least("fcf_margin")
    if name == "fcf_positive_latest":
        return True if not want else (m["fcf_latest"] is not None and m["fcf_latest"] > 0)
    if name == "fcf_positive_all_years":
        return (
            True if not want else (m["fcf_years"] == n_years and m["fcf_positive_years"] == n_years)
        )
    if name == "net_income_positive_all_years":
        return True if not want else m["net_income_positive_years"] == n_years
    if name == "pays_dividend_all_years":
        return True if not want else m["dividend_years"] == n_years
    if name == "max_share_growth":
        return at_most("share_growth")
    if name == "max_sbc_pct":
        return at_most("sbc_pct")
    if name == "max_debt_to_equity":
        return at_most("debt_to_equity")
    if name == "max_net_debt_to_ebit":
        return _leverage_ok(m, want)
    if name == "min_current_ratio":
        return at_least("current_ratio")
    if name == "max_debt_to_working_capital":
        wc = m["working_capital"]
        return None if wc is None else (m["debt"] or 0) <= want * wc
    if name == "min_f_score":
        return m["f_score"] >= want
    if name == "max_payout_to_fcf":
        # Paying nothing passes; a payout with no positive free cash flow behind it does not.
        if not m["payout_latest"]:
            return True
        return m["payout_to_fcf"] is not None and m["payout_to_fcf"] <= want
    raise ValueError(f"unknown criterion {name}")


def _price_metrics(m: dict, market: dict, crit: dict) -> None:
    mc, ev = _num(market.get("market_cap")), _num(market.get("enterprise_value"))
    value = ev if ev and ev > 0 else mc
    fin = bool(market.get("financial"))
    m["market_cap"] = mc
    m["enterprise_value"] = ev
    m["price"] = _num(market.get("price"))
    m["sector"] = market.get("sector")
    m["financial"] = fin
    m["momentum"] = _r4(_num(market.get("momentum")))
    ok = mc and mc > 0 and not fin
    after_sbc = crit.get("fcf_basis", "fcf_after_sbc") == "fcf_after_sbc"
    cash = m["fcf_after_sbc_norm"] if after_sbc else m["fcf_norm"]
    m["fcf_yield"] = _r4(cash / mc) if ok and cash is not None else None
    ni, eq, ebit = m["net_income_latest"], m["equity"], m["ebit_latest"]
    m["pe"] = _r4(mc / ni) if ok and ni and ni > 0 else None
    m["ps"] = _r4(mc / m["revenue_latest"]) if mc and mc > 0 else None
    m["pb"] = _r4(mc / eq) if ok and eq and eq > 0 else None
    m["pe_times_pb"] = _r4(m["pe"] * m["pb"]) if m["pe"] is not None and m["pb"] is not None else None
    m["earnings_yield"] = _r4(ebit / value) if ok and ebit is not None and value and value > 0 else None
    payout = m["payout_latest"]
    m["shareholder_yield"] = _r4(payout / mc) if ok and payout is not None else None
    g = (
        implied_growth(
            cash, value, crit.get("discount_rate", 0.10), crit.get("terminal_growth", 0.03)
        )
        if ok
        else None
    )
    m["implied_growth"] = _r4(g)
    m["growth_gap"] = (
        _r4(m["expected_growth"] - g) if g is not None and m["expected_growth"] is not None else None
    )


def _price_test(name: str, m: dict, want):
    def at_least(key):
        return m[key] is not None and m[key] >= want

    def at_most(key):
        return m[key] is not None and m[key] <= want

    if name == "min_market_cap":
        return at_least("market_cap")
    if name == "min_fcf_yield":
        return at_least("fcf_yield")
    if name == "min_earnings_yield":
        return at_least("earnings_yield")
    if name == "min_shareholder_yield":
        return at_least("shareholder_yield")
    if name == "max_pe":
        return at_most("pe")
    if name == "max_ps":
        return at_most("ps")
    if name == "max_pe_times_pb":
        return at_most("pe_times_pb")
    if name == "max_implied_growth":
        return at_most("implied_growth")
    if name == "min_growth_gap":
        return at_least("growth_gap")
    if name == "min_momentum":
        return at_least("momentum")
    raise ValueError(f"unknown criterion {name}")


def _merge(params: dict) -> tuple[str | None, dict]:
    preset = params.get("preset")
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; one of {', '.join(PRESETS)}")
    crit = copy.deepcopy(PRESETS.get(preset, {}))
    overrides = params.get("criteria") or {}
    if not isinstance(overrides, dict):
        raise ValueError("criteria must be an object")
    for k, v in overrides.items():
        if k not in FUNDAMENTAL + PRICE + SETTINGS:
            raise ValueError(f"unknown criterion {k!r}")
        crit[k] = v
    sectors = crit.get("exclude_sectors")
    if isinstance(sectors, str):
        crit["exclude_sectors"] = [s.strip() for s in sectors.split(",") if s.strip()]
    elif sectors is not None and not isinstance(sectors, list):
        raise ValueError("exclude_sectors must be a list of sector names")
    return preset, crit


def _flags(m: dict, missing: list[str]) -> list[str]:
    flags = []
    cash_m, op_m, avg_m = m["fcf_after_sbc_margin"], m["operating_margin_latest"], m["fcf_after_sbc_margin_avg"]
    if cash_m is not None and op_m is not None and cash_m - op_m > CASH_OUTRUNS_PROFIT_PP:
        flags.append("CASH_OUTRUNS_PROFIT")
    if cash_m is not None and avg_m is not None and cash_m - avg_m > CASH_ABOVE_AVERAGE_PP:
        flags.append("CASH_ABOVE_ITS_AVERAGE")
    ni, oi = m["net_income_latest"], m["operating_income_latest"]
    if ni is not None and oi is not None and oi > 0 and ni > oi:
        flags.append("PROFIT_ABOVE_OPERATING_PROFIT")
    if not m["capex_reported"]:
        flags.append("CAPEX_NOT_REPORTED")
    if "min_latest_quarter_growth" in missing:
        flags.append("LATEST_QUARTER_NOT_REPORTED")
    if m["acquisition_pct"] is not None and m["acquisition_pct"] > ACQUISITIVE_PCT:
        flags.append("ACQUISITIVE")
    if m["split_detected"]:
        flags.append("SPLIT_OR_LISTING_YEAR_SKIPPED")
    if m["misscaled"]:
        flags.append("MISSCALED")
    return flags


def _magic_ranks(rows: list[dict]) -> None:
    """Greenblatt: rank on earnings yield and on return on capital, add the two ranks."""
    for key in ("earnings_yield", "roce"):
        ordered = sorted(rows, key=lambda r: (r["metrics"].get(key) is None, -(r["metrics"].get(key) or 0)))
        for i, r in enumerate(ordered, start=1):
            r["metrics"]["magic_rank"] = r["metrics"].get("magic_rank", 0) + i


def run_screen_math(params: dict) -> dict:
    """Screen ``params['companies']``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object with years and companies")
    params = copy.deepcopy(params)
    years = params.get("years")
    if not isinstance(years, list) or len(years) < 2 or not all(isinstance(y, int) for y in years):
        raise ValueError("years must be a list of at least two integer years, oldest first")
    companies = params.get("companies")
    if not isinstance(companies, list):
        raise ValueError("companies must be a list")
    preset, crit = _merge(params)
    if crit.get("fcf_basis", "fcf_after_sbc") not in FCF_BASES:
        raise ValueError(f"fcf_basis must be one of {', '.join(FCF_BASES)}")
    fund = [c for c in FUNDAMENTAL if crit.get(c) is not None]
    price = [c for c in PRICE if crit.get(c) is not None]
    n_years = len(years)
    keep_fin = bool(crit.get("include_financials"))
    barred = set(crit.get("exclude_sectors") or [])
    terminal = crit.get("terminal_growth", 0.03)

    rows, dropped = [], 0
    for c in companies:
        if not isinstance(c, dict):
            raise ValueError("each company must be an object")
        m = metrics(c, years)
        if m is None:
            dropped += 1
            continue
        m["expected_growth"] = _r4(expected_growth(m["start_growth"], terminal))
        failed, missing = [], []
        if c.get("financial") and not keep_fin:
            failed.append("financial_filer")
        else:
            for name in fund:
                ok = _fundamental_test(name, m, crit[name], n_years)
                if ok is None:
                    (missing if name in LENIENT else failed).append(name)
                elif not ok:
                    failed.append(name)
        row = {
            "cik": c.get("cik"),
            "ticker": c.get("ticker"),
            "name": c.get("name"),
            "metrics": m,
            "failed": failed,
            "not_reported": missing,
            "passes_fundamentals": not failed,
            "passes_price": None,
            "flags": _flags(m, missing),
            "held": bool(c.get("held")),
        }
        market = c.get("market")
        if isinstance(market, dict):
            _price_metrics(m, market, crit)
            if m["momentum"] is not None and m["momentum"] < PRICE_FALLING:
                row["flags"].append("PRICE_FALLING")
            if m["financial"] and not keep_fin:
                pf = ["financial_excluded"]
            elif m["sector"] in barred:
                pf = ["sector_excluded"]
            else:
                pf = [name for name in price if not _price_test(name, m, crit[name])]
            row["passes_price"] = not pf and not failed
            if not failed:
                row["failed"] = pf
        rows.append(row)

    fail_counts: dict[str, int] = {}
    for r in rows:
        for name in r["failed"]:
            fail_counts[name] = fail_counts.get(name, 0) + 1

    # Sequential funnel: each stage keeps the companies passing every criterion so far.
    funnel = [{"stage": "universe", "remaining": len(rows)}]
    alive = list(rows)
    if fail_counts.get("financial_filer"):
        alive = [r for r in alive if "financial_filer" not in r["failed"]]
        funnel.append({"stage": "financial_filer", "remaining": len(alive)})
    for name in fund:
        alive = [r for r in alive if name not in r["failed"]]
        funnel.append({"stage": name, "remaining": len(alive)})
    priced = [r for r in alive if r["passes_price"] is not None]
    if priced:
        alive = priced
        if not keep_fin:
            alive = [r for r in alive if "financial_excluded" not in r["failed"]]
            funnel.append({"stage": "financial_excluded", "remaining": len(alive)})
        if barred:
            alive = [r for r in alive if "sector_excluded" not in r["failed"]]
            funnel.append({"stage": "sector_excluded", "remaining": len(alive)})
        for name in price:
            alive = [r for r in alive if name not in r["failed"]]
            funnel.append({"stage": name, "remaining": len(alive)})
        _magic_ranks(alive)

    rank_by = crit.get("rank_by") or "growth_gap"
    key = rank_by if priced or rank_by in RANK_UNPRICED else "revenue_cagr"
    sign = 1 if key in RANK_ASCENDING else -1
    survivors = sorted(
        alive, key=lambda r: (r["metrics"].get(key) is None, sign * (r["metrics"].get(key) or 0))
    )
    # A near miss failed one quality of the business, not the size cutoff, and can be looked up.
    near = [
        r
        for r in rows
        if len(r["failed"]) == 1
        and r["failed"][0] in fund
        and r["failed"][0] != "min_revenue"
        and r.get("ticker")
    ]
    near.sort(key=lambda r: -r["metrics"]["revenue_cagr"])
    return {
        "preset": preset,
        "criteria": crit,
        "years": years,
        "universe": len(rows),
        "dropped_incomplete": dropped,
        "funnel": funnel,
        "fail_counts": fail_counts,
        "companies": rows,
        "survivors": survivors,
        "near_misses": near[:15],
        "rank_by": key,
    }


def main() -> None:
    try:
        result = run_screen_math(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
