"""Graham and Buffett value-investing arithmetic over the fundamentals annual table.

This script reads a JSON object from stdin and writes a JSON object to
stdout. It is invoked as:

    python intrinsic.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "annual": [ ...rows of fundamentals.py's "annual" table, oldest first;
                  the fields used are fiscal_year, revenue, net_income,
                  eps_diluted, equity, operating_income, operating_cash_flow,
                  capex, free_cash_flow, depreciation_amortization,
                  current_assets, current_liabilities, total_assets,
                  total_liabilities, long_term_debt, cash, dividends_paid,
                  diluted_shares; any may be null ],                # required
      "price": 150.0,                # current share price; optional (see below)
      "shares_outstanding": 1.5e9,   # optional; default: latest diluted_shares
      "aaa_yield": 0.052,            # Moody's Aaa corporate yield, decimal; optional
      "treasury_10y": 0.042,         # 10-year Treasury yield, decimal; optional
      "discount_rate_floor": 0.08,   # optional, default 0.08
      "growth_rate": 0.06,           # optional; default: min(EPS CAGR, revenue CAGR)
                                     # over the table, clipped to [0, 0.08]; revenue
                                     # CAGR alone when EPS CAGR is unavailable
      "terminal_growth": 0.02,       # optional, default 0.02 (for the dcf handoff)
      "maintenance_capex": 25.0,     # optional override for every year
      "min_revenue": 7.0e8,          # optional, default 700,000,000 (Graham's
                                     # 1973 "$100M of sales" brought forward)
      "business_type": "industrial"  # optional: "industrial" (default), "financial"
                                     # (banks, brokers, insurers), or "reit"
    }

Output JSON contract (stdout)::

    {
      "fiscal_year": 2025, "years_covered": 5,
      "inputs": {price, shares_outstanding, aaa_yield, treasury_10y, business_type,
                 discount_rate: {value, source}, growth_rate: {value, source},
                 growth_alternatives: {eps_cagr, revenue_cagr, span_years,
                                       growth_formula_at: {"0.05", "0.10", "0.15"}}},
      "per_share": {eps_latest, eps_3y_avg, book_value, dividends, owner_earnings},
      "graham": {
        "graham_number",                     # sqrt(22.5 x eps_3y_avg x book_value);
                                             # null unless both > 0
        "growth_formula": {value, growth_used, aaa_yield},
                                             # eps_3y_avg x (8.5 + 2g) x 4.4 / Y, g and Y in percent
        "ncav_per_share",                    # (current_assets - total_liabilities) / shares;
                                             # null for financials
        "net_net": {two_thirds_ncav, price_below},
        "defensive_checklist": {score, out_of, years_covered,
                                checks: [{check, passed, value, threshold}]}
      },
      "buffett": {
        "owner_earnings": {net_income, depreciation_amortization, capex,
                           maintenance_capex, maintenance_capex_method,
                           estimates: {depreciation_amortization, average_capex,
                                       one_percent_of_revenue},
                           value, per_share, by_year: [{fiscal_year, value}]},
        "dcf_input": { ...a ready dcf.py input with owner earnings as fcf0... },
        "tenets": {score, out_of, checks: [{check, passed, value, threshold}]},
        "book_value_tests": {price_to_book, roe_latest, roe_10y_avg,
                             price_to_book_x_roe_note},        # financials only, else null
        "reit_tests": {affo_proxy_per_share, price_to_affo_proxy, dividend_yield,
                       payout_of_affo_proxy}                   # REITs only, else null
      },
      "normalized": {
        "years": {owner_earnings, eps},      # years present in each average
        "owner_earnings_10y_avg",            # mean of by_year over the last 10 rows;
                                             # null with fewer than 5 years present
        "owner_earnings_10y_avg_per_share",
        "eps_10y_avg",                       # same 5-year minimum
        "graham_number_10y",                 # sqrt(22.5 x eps_10y_avg x book_value)
        "dcf_input_mid_cycle"                # dcf_input with fcf0 = 10y avg owner
                                             # earnings and growth_rate = terminal_growth
      },
      "margin_of_safety": [{method, value, price_to_value, discount, band}],
      "flags": [{code, message}]
    }

Method. Graham (The Intelligent Investor, 1973 ed., ch. 14 and 20; the
growth formula from the 1974 revision): the Graham number uses the
three-year average diluted EPS and the latest book value per share; the
growth formula V = EPS x (8.5 + 2g) x 4.4 / Y takes g as the expected
growth in percentage points and Y as the current Aaa corporate yield in
percent; net current asset value is current assets minus ALL liabilities,
and the net-net test asks whether price is below two thirds of it. The
defensive-investor checklist scores seven tests: adequate size (revenue
>= min_revenue), financial condition (current ratio >= 2 and long-term
debt <= net current assets), earnings stability (positive net income
every year), dividend record (dividends every year), earnings growth
(three-year average EPS at the end of the table at least one third above
the start), moderate P/E (price <= 15 x eps_3y_avg), moderate P/B (price
<= 1.5 x book value, or P/E x P/B <= 22.5). Graham's tests span 10 to 20
years; the table is usually shorter, so years_covered and a SHORT_HISTORY
flag say how much history the stability, dividend, and growth tests saw.

Growth default. Graham distrusted extrapolated growth, so the default g is
the smaller of the EPS CAGR and revenue growth over the table, clipped to
[0, 8%], where revenue growth is itself the LOWER of the total and the
per-share CAGR: per share leaves out growth bought with newly issued shares
(acquisitions paid in stock, a REIT's yearly issuance), and total leaves out
per-share growth that is only buybacks shrinking the count. When EPS is not
positive at both ends the revenue figure stands alone. For a REIT the AFFO
proxy per share replaces EPS. growth_alternatives reports
both CAGRs and the growth-formula value at g = 5%, 10%, and 15% so the
sensitivity is visible without a rerun; growth_rate overrides the default.

Buffett (Berkshire letters, 1986 for owner earnings, 1992 for intrinsic
value): owner earnings = net income + depreciation and amortization -
maintenance capex. Maintenance capex is a judgment; the default takes the
larger of the latest D&A and the table's average capex (the conservative
choice), reports both, and yields to a maintenance_capex override. The
dcf_input hands owner earnings to dcf.py as fcf0 with a 10-year stage,
the given growth, and a discount rate of max(treasury_10y,
discount_rate_floor): Buffett discounts at the long bond, and the floor
keeps a low-rate regime from inflating the value. The tenets checklist is
seven quantifiable tests drawn from the letters: ROE >= 15% in at least
80% of years, debt/equity <= 0.5, net margin >= 10%, positive operating
income every year, positive owner earnings every year, FCF/net income >=
0.8, and diluted share count not above its first-year level.

Normalized earnings (Graham ch. 12 on average earnings; Security Analysis
Part VI): a cycle-peak year makes any earnings-based figure look cheap, so
the normalized block averages owner earnings and EPS over the last ten
rows (at least five must be present), restates the Graham number on the
ten-year EPS, and hands dcf.py a mid-cycle input: fcf0 at the ten-year
average owner earnings growing only at terminal_growth. Owner earnings are
averaged PER SHARE, each year on that year's share count, and put on today's
count (normalized.basis says so; total dollars only when share counts are
missing): a company that issued shares to grow, as every REIT does, is not
marked down for having been smaller. A CYCLE_PEAK flag fires when the latest
owner earnings exceed 1.5x that average. When owner earnings were not
positive in half or more of the years, OWNER_EARNINGS_MOSTLY_NEGATIVE fires
and the mid-cycle input is withheld (null).
The dcf_input's net_debt is always 0, with a net_debt_note saying why:
owner earnings start from net income, which is after interest, so they
are an equity cash flow and dcf.py's value is equity value directly;
subtracting the balance sheet's net debt as well would count the debt
twice. The note quotes the latest long-term debt less cash for context
when both are tagged.

Business type. "financial" (banks, brokers, insurers): a financial
balance sheet has no current/non-current split and its debt is the
business, so the current ratio, NCAV, and net-net test are null with a
NOT_APPLICABLE flag, the financial-condition test becomes equity /
total_assets >= 8% (a leverage-ratio floor in the spirit of Basel), the
"little debt" tenet is skipped, and the DCF handoff is still built but
flagged DCF_NOT_MEANINGFUL_FOR_FINANCIALS with net_debt set to 0 (deposits
and borrowings are operating liabilities). book_value_tests gives the
price-to-book against latest and ten-year ROE, the yardstick that fits.
"reit": GAAP EPS is after real-estate depreciation that rarely reflects
economic decay, so the Graham number and growth formula are flagged
GAAP_EPS_UNDERSTATES_REIT and left out of margin_of_safety; maintenance
capex defaults to 1% of revenue (the usual recurring-capex reserve) unless
overridden; a row's gain_on_property_sales is taken out of owner earnings,
as funds from operations do; and reit_tests reports owner earnings per share
as an AFFO proxy with price / AFFO proxy, its yield and per-share growth,
dividend yield and per-share dividend growth, the payout of the AFFO proxy,
net debt / EBITDA, the sale gains excluded, and a ddm_input for ddm.py.
"utility" (regulated electric, gas, water): spending above depreciation
grows the rate base the utility earns on, so maintenance capex is D&A and
owner earnings equal net income; growth is funded with new debt and shares,
so the DCF handoff is flagged DCF_NOT_MEANINGFUL_FOR_UTILITIES, and
utility_tests gives P/E, P/B, ROE (latest and ten-year), dividend yield,
payout of earnings, per-share dividend growth, and a ddm_input (Gordon:
latest dividend per share, the discount rate, growth at the dividend record
clipped to [0, 4%]).

Margin of safety: for every value estimate above zero, price / value and
the discount 1 - price / value, labeled "50%+", "33-50%", "25-33%",
"0-25%", or "premium" (price above value). Graham's own rule of thumb
was a third; the labels are data, not a verdict. Tests with no data are
excluded from out_of and reported with passed = null. Money 2 dp, ratios
4 dp.
"""

from __future__ import annotations

import json
import math
import sys

_DEFAULT_DISCOUNT_FLOOR = 0.08
_DEFAULT_TERMINAL_GROWTH = 0.02
_DEFAULT_MIN_REVENUE = 7.0e8
_DCF_YEARS = 10
_GROWTH_CLIP = (0.0, 0.08)
_GROWTH_SENSITIVITY = (0.05, 0.10, 0.15)
_GRAHAM_BASE_PE = 8.5
_GRAHAM_YIELD_BASE = 4.4
_GRAHAM_PE_TIMES_PB = 22.5
_BANDS = ((0.5, "50%+"), (1 / 3, "33-50%"), (0.25, "25-33%"), (0.0, "0-25%"))
_BUSINESS_TYPES = ("industrial", "financial", "reit", "utility")
_FINANCIAL_EQUITY_TO_ASSETS = 0.08
_REIT_MAINTENANCE_CAPEX_SHARE = 0.01
_NORMALIZED_YEARS = 10
_NORMALIZED_MIN_YEARS = 5
_CYCLE_PEAK_RATIO = 1.5
# A Gordon model needs growth well under the discount rate; a dividend record above this is not
# carried into perpetuity.
_DDM_GROWTH_CLIP = (0.0, 0.04)


def _r2(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None


def _r4(v: float | None) -> float | None:
    return round(v, 4) if v is not None else None


def _num(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    raise ValueError(f"expected a number, got {v!r}")


def _opt(params: dict, key: str, default: float | None = None) -> float | None:
    v = params.get(key)
    return default if v is None else _num(v)


def _col(rows: list[dict], key: str) -> list[float | None]:
    return [_num(r.get(key)) for r in rows]


def _last(values: list[float | None]) -> float | None:
    return next((v for v in reversed(values) if v is not None), None)


def _mean(values: list[float | None], min_present: int = 1) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if len(present) >= max(min_present, 1) else None


def _present(values: list[float | None]) -> int:
    return sum(1 for v in values if v is not None)


def _div(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b else None


def _cagr(first: float | None, last: float | None, span: int) -> float | None:
    if first is None or last is None or span <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / span) - 1


def _all_positive(values: list[float | None]) -> bool | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return all(v > 0 for v in present)


def _check(name: str, passed: bool | None, value: object, threshold: str) -> dict:
    return {"check": name, "passed": passed, "value": value, "threshold": threshold}


def _score(checks: list[dict]) -> dict:
    scored = [c for c in checks if c["passed"] is not None]
    return {"score": sum(1 for c in scored if c["passed"]), "out_of": len(scored), "checks": checks}


def _band(discount: float) -> str:
    for floor, label in _BANDS:
        if discount >= floor:
            return label
    return "premium"


def _mos(method: str, value: float | None, price: float | None) -> dict | None:
    if value is None or value <= 0 or price is None:
        return None
    ratio = price / value
    return {
        "method": method,
        "value": _r2(value),
        "price_to_value": _r4(ratio),
        "discount": _r4(1 - ratio),
        "band": _band(1 - ratio),
    }


def _graham_number(eps_avg: float | None, book_value: float | None) -> float | None:
    if eps_avg is None or book_value is None or eps_avg <= 0 or book_value <= 0:
        return None
    return math.sqrt(_GRAHAM_PE_TIMES_PB * eps_avg * book_value)


def _growth_formula(eps_avg: float | None, g: float | None, aaa: float | None) -> float | None:
    """Graham's V = EPS x (8.5 + 2g) x 4.4 / Y with g and Y in percent."""
    if eps_avg is None or eps_avg <= 0 or g is None or not aaa:
        return None
    return eps_avg * (_GRAHAM_BASE_PE + 2 * g * 100) * _GRAHAM_YIELD_BASE / (aaa * 100)


def _default_growth(
    eps_cagr: float | None, rev_cagr: float | None, eps_label: str = "EPS", rev_label: str = "revenue"
) -> tuple[float | None, str]:
    lo, hi = _GROWTH_CLIP
    clip = f"clipped to [{lo:g}, {hi:g}]"
    if eps_cagr is not None and rev_cagr is not None:
        raw = min(eps_cagr, rev_cagr)
        source = f"min({eps_label} CAGR {eps_cagr:.4f}, {rev_label} CAGR {rev_cagr:.4f}) = {raw:.4f}, {clip}"
    elif rev_cagr is not None:
        raw = rev_cagr
        source = f"{rev_label} CAGR {rev_cagr:.4f} ({eps_label} CAGR unavailable), {clip}"
    elif eps_cagr is not None:
        raw = eps_cagr
        source = f"{eps_label} CAGR {eps_cagr:.4f} ({rev_label} CAGR unavailable), {clip}"
    else:
        return None, f"no positive {eps_label} or {rev_label} at both ends of the table; set growth_rate"
    return min(max(raw, lo), hi), source


def _revenue_growth(rev_cagr: float | None, rev_ps_cagr: float | None) -> tuple[float | None, str]:
    """The lower of total and per-share revenue growth, with its label.

    Per share takes out growth bought with new shares; total takes out per-share growth that
    is only buybacks shrinking the count. Neither is credited.
    """
    if rev_ps_cagr is not None and (rev_cagr is None or rev_ps_cagr < rev_cagr - 1e-9):
        return rev_ps_cagr, "revenue-per-share"
    return rev_cagr, "revenue"


def _span_cagr(values: list[float | None]) -> float | None:
    """CAGR from the first to the last value present, over the rows between them."""
    idx = [i for i, v in enumerate(values) if v is not None]
    if len(idx) < 2:
        return None
    return _cagr(values[idx[0]], values[idx[-1]], idx[-1] - idx[0])


def run_intrinsic(params: dict) -> dict:
    """Compute the Graham and Buffett view of ``params``; raises ValueError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    rows = params.get("annual")
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        raise ValueError("annual is required: a non-empty list of fundamentals.py annual rows")
    rows = sorted(rows, key=lambda r: r.get("fiscal_year") or 0)
    n = len(rows)
    flags: list[dict] = []

    business_type = params.get("business_type") or "industrial"
    if business_type not in _BUSINESS_TYPES:
        raise ValueError(f"business_type must be one of {', '.join(_BUSINESS_TYPES)}")
    financial = business_type == "financial"
    reit = business_type == "reit"
    utility = business_type == "utility"

    price = _opt(params, "price")
    aaa = _opt(params, "aaa_yield")
    treasury = _opt(params, "treasury_10y")
    floor = _opt(params, "discount_rate_floor", _DEFAULT_DISCOUNT_FLOOR)
    terminal_growth = _opt(params, "terminal_growth", _DEFAULT_TERMINAL_GROWTH)
    min_revenue = _opt(params, "min_revenue", _DEFAULT_MIN_REVENUE)
    override_maint = _opt(params, "maintenance_capex")
    if price is not None and price <= 0:
        raise ValueError("price must be > 0")

    revenue, net_income, eps = (
        _col(rows, "revenue"),
        _col(rows, "net_income"),
        _col(rows, "eps_diluted"),
    )
    equity, op_income = _col(rows, "equity"), _col(rows, "operating_income")
    capex, da = _col(rows, "capex"), _col(rows, "depreciation_amortization")
    fcf = _col(rows, "free_cash_flow")
    cur_assets, cur_liab = _col(rows, "current_assets"), _col(rows, "current_liabilities")
    total_assets, total_liab, ltd, cash = (
        _col(rows, "total_assets"),
        _col(rows, "total_liabilities"),
        _col(rows, "long_term_debt"),
        _col(rows, "cash"),
    )
    dividends, diluted = _col(rows, "dividends_paid"), _col(rows, "diluted_shares")
    sale_gains = _col(rows, "gain_on_property_sales")

    shares = _opt(params, "shares_outstanding", _last(diluted))
    if shares is not None and shares <= 0:
        raise ValueError("shares_outstanding must be > 0")

    # ── per-share building blocks ─────────────────────────────────────────
    eps_latest = _last(eps)
    eps_3y_avg = _mean(eps[-3:])
    book_value = _div(_last(equity), shares)
    dividends_ps = _div(_last(dividends), shares)

    # ── growth: given, else min(EPS CAGR, revenue-per-share CAGR) clipped to [0, 8%] ─
    # Revenue per share, not revenue: growth bought with new shares (acquisitions paid in stock,
    # a REIT issuing equity every year) is not growth for the holder of one share.
    eps_cagr = _cagr(eps[0], eps[-1], n - 1)
    rev_cagr = _cagr(revenue[0], revenue[-1], n - 1)
    rev_ps = [_div(r, d) if d and d > 0 else None for r, d in zip(revenue, diluted)]
    rev_ps_cagr = _cagr(rev_ps[0], rev_ps[-1], n - 1)
    growth_alternatives = {
        "eps_cagr": _r4(eps_cagr),
        "revenue_cagr": _r4(rev_cagr),
        "revenue_per_share_cagr": _r4(rev_ps_cagr),
        "span_years": n - 1,
        "growth_formula_at": {
            f"{g:.2f}": _r2(_growth_formula(eps_3y_avg, g, aaa)) for g in _GROWTH_SENSITIVITY
        },
    }
    growth = _opt(params, "growth_rate")
    growth_is_default = growth is None
    if not growth_is_default:
        growth_source = "input"
    else:
        rev_growth, rev_label = _revenue_growth(rev_cagr, rev_ps_cagr)
        growth, growth_source = _default_growth(eps_cagr, rev_growth, rev_label=rev_label)

    # ── Graham ────────────────────────────────────────────────────────────
    graham_number = _graham_number(eps_3y_avg, book_value)
    if eps_3y_avg is not None and eps_3y_avg <= 0:
        flags.append(
            {
                "code": "NEGATIVE_EPS",
                "message": "three-year average EPS is not positive; "
                "the Graham number and growth formula do not apply",
            }
        )
    growth_formula_value = _growth_formula(eps_3y_avg, growth, aaa)
    if aaa is None:
        flags.append(
            {
                "code": "NO_AAA_YIELD",
                "message": "no aaa_yield given; Graham's growth formula is skipped",
            }
        )
    if reit:
        flags.append(
            {
                "code": "GAAP_EPS_UNDERSTATES_REIT",
                "message": "business_type reit: GAAP EPS is after real-estate depreciation, "
                "so the Graham number and growth formula understate a REIT; see reit_tests",
            }
        )

    if financial:
        ncav = current_ratio = nca = None
        two_thirds = None
        net_net = {"two_thirds_ncav": None, "price_below": None}
        flags.append(
            {
                "code": "NOT_APPLICABLE",
                "message": "business_type financial: current ratio, net current asset value, "
                "and the net-net test are skipped (a financial balance sheet has no "
                "current/non-current split)",
            }
        )
    else:
        ncav = (
            (_last(cur_assets) - _last(total_liab)) / shares
            if _last(cur_assets) is not None and _last(total_liab) is not None and shares
            else None
        )
        if ncav is not None and ncav <= 0:
            flags.append(
                {
                    "code": "NEGATIVE_NCAV",
                    "message": "current assets do not cover total liabilities; "
                    "the net-net test does not apply",
                }
            )
        two_thirds = ncav * 2 / 3 if ncav is not None and ncav > 0 else None
        net_net = {
            "two_thirds_ncav": _r2(two_thirds),
            "price_below": bool(
                two_thirds is not None and price is not None and price < two_thirds
            ),
        }
        current_ratio = _div(_last(cur_assets), _last(cur_liab))
        nca = (
            (_last(cur_assets) - _last(cur_liab))
            if _last(cur_assets) is not None and _last(cur_liab) is not None
            else None
        )

    ltd_latest = _last(ltd)
    equity_latest, assets_latest = _last(equity), _last(total_assets)
    if financial:
        equity_to_assets = (
            equity_latest / assets_latest
            if equity_latest is not None and assets_latest is not None and assets_latest > 0
            else None
        )
        financial_condition = (
            equity_to_assets >= _FINANCIAL_EQUITY_TO_ASSETS
            if equity_to_assets is not None
            else None
        )
        financial_condition_value: dict = {
            "equity_to_assets": _r4(equity_to_assets),
            "equity": _r2(equity_latest),
            "total_assets": _r2(assets_latest),
        }
        financial_condition_threshold = (
            f"equity / total assets >= {_FINANCIAL_EQUITY_TO_ASSETS} (business_type financial; "
            "the current ratio and working-capital tests do not apply)"
        )
    else:
        financial_condition = (
            (current_ratio >= 2 and ltd_latest <= nca)
            if current_ratio is not None and nca is not None and ltd_latest is not None
            else None
        )
        financial_condition_value = {
            "current_ratio": _r4(current_ratio),
            "long_term_debt": _r2(ltd_latest),
            "net_current_assets": _r2(nca),
        }
        financial_condition_threshold = (
            "current ratio >= 2 and long-term debt <= net current assets"
        )
    eps_start_avg = _mean(eps[:3])
    eps_growth_total = (
        eps_3y_avg / eps_start_avg - 1
        if eps_start_avg is not None and eps_3y_avg is not None and eps_start_avg > 0
        else None
    )
    pe = _div(price, eps_3y_avg) if eps_3y_avg and eps_3y_avg > 0 else None
    pb = _div(price, book_value) if book_value and book_value > 0 else None
    pe_pb = pe * pb if pe is not None and pb is not None else None
    revenue_latest = _last(revenue)
    defensive = _score(
        [
            _check(
                "adequate_size",
                revenue_latest >= min_revenue if revenue_latest is not None else None,
                _r2(revenue_latest),
                f"revenue >= {min_revenue:,.0f}",
            ),
            _check(
                "financial_condition",
                financial_condition,
                financial_condition_value,
                financial_condition_threshold,
            ),
            _check(
                "earnings_stability",
                _all_positive(net_income),
                {
                    "years": n,
                    "positive_years": sum(1 for v in net_income if v is not None and v > 0),
                },
                "positive net income every year (Graham: 10 years)",
            ),
            _check(
                "dividend_record",
                _all_positive(dividends),
                {"years": n, "paying_years": sum(1 for v in dividends if v is not None and v > 0)},
                "dividends paid every year (Graham: 20 years)",
            ),
            _check(
                "earnings_growth",
                eps_growth_total >= 1 / 3 if eps_growth_total is not None else None,
                _r4(eps_growth_total),
                "three-year average EPS up at least one third across the table (Graham: 10 years)",
            ),
            _check(
                "moderate_pe",
                pe <= 15 if pe is not None else None,
                _r4(pe),
                "price <= 15 x three-year average EPS",
            ),
            _check(
                "moderate_pb",
                (pb <= 1.5 or pe_pb <= _GRAHAM_PE_TIMES_PB)
                if pb is not None and pe_pb is not None
                else None,
                {"price_to_book": _r4(pb), "pe_times_pb": _r4(pe_pb)},
                "price <= 1.5 x book value, or P/E x P/B <= 22.5",
            ),
        ]
    )
    defensive["years_covered"] = n
    if n < 10:
        flags.append(
            {
                "code": "SHORT_HISTORY",
                "message": f"{n} fiscal years in the table; "
                "Graham's stability, dividend, and growth tests want 10 to 20",
            }
        )
    if price is None:
        flags.append(
            {
                "code": "NO_PRICE",
                "message": "no price given; P/E, P/B, and margin-of-safety figures are skipped",
            }
        )

    # ── Buffett ───────────────────────────────────────────────────────────
    avg_capex = _mean(capex)
    da_latest = _last(da)
    one_pct_revenue = (
        revenue_latest * _REIT_MAINTENANCE_CAPEX_SHARE if revenue_latest is not None else None
    )

    def maintenance_capex_at(i: int) -> float | None:
        if override_maint is not None:
            return override_maint
        if reit:
            return revenue[i] * _REIT_MAINTENANCE_CAPEX_SHARE if revenue[i] is not None else None
        if utility:
            return da[i]
        candidates = [v for v in (da[i], avg_capex) if v is not None]
        return max(candidates) if candidates else None

    def owner_earnings_at(i: int) -> float | None:
        ni, m = net_income[i], maintenance_capex_at(i)
        if ni is None or m is None:
            return None
        # A REIT's net income carries gains on properties it sold; funds from operations leave
        # them out, and so does this (a loss is added back the same way).
        gain = (sale_gains[i] or 0.0) if reit else 0.0
        return ni + (da[i] or 0.0) - gain - m

    maint = maintenance_capex_at(n - 1)
    if override_maint is not None:
        maint_method = "override"
    elif maint is None:
        maint_method = "unavailable"
    elif reit:
        maint_method = "1% of revenue (business_type reit)"
        flags.append(
            {
                "code": "MAINTENANCE_CAPEX_ESTIMATED",
                "message": "maintenance capex is estimated as 1% of revenue, the usual REIT "
                "recurring-capex reserve; pass maintenance_capex to override",
            }
        )
    elif utility:
        maint_method = "depreciation_amortization (business_type utility)"
        flags.append(
            {
                "code": "MAINTENANCE_CAPEX_ESTIMATED",
                "message": "maintenance capex is taken as depreciation: a regulated utility's "
                "spending above that grows the rate base it earns on; pass maintenance_capex to override",
            }
        )
    else:
        maint_method = "max(depreciation_amortization, average_capex)"
        flags.append(
            {
                "code": "MAINTENANCE_CAPEX_ESTIMATED",
                "message": "maintenance capex is estimated as the larger of D&A and average capex; "
                "pass maintenance_capex to override",
            }
        )

    oe_series = [owner_earnings_at(i) for i in range(n)]
    by_year = [
        {"fiscal_year": r.get("fiscal_year"), "value": _r2(oe_series[i])}
        for i, r in enumerate(rows)
    ]
    oe_latest = oe_series[-1]
    oe_ps = _div(oe_latest, shares)
    # Per share, each year on that year's share count: the record a holder of one share lived.
    oe_ps_series = [
        _div(v, d) if d and d > 0 else None for v, d in zip(oe_series, diluted)
    ]
    dps_series = [_div(v, d) if d and d > 0 else None for v, d in zip(dividends, diluted)]
    dps_cagr = _span_cagr(dps_series)
    if reit and growth_is_default:
        # GAAP EPS is the wrong record for a REIT; its AFFO proxy per share is the right one.
        rev_growth, rev_label = _revenue_growth(rev_cagr, rev_ps_cagr)
        growth, growth_source = _default_growth(
            _span_cagr(oe_ps_series), rev_growth, eps_label="AFFO-proxy-per-share", rev_label=rev_label
        )
        growth_formula_value = _growth_formula(eps_3y_avg, growth, aaa)

    if treasury is not None:
        discount = max(treasury, floor)
        discount_source = f"max(treasury_10y {treasury}, discount_rate_floor {floor})"
    else:
        discount = floor
        discount_source = f"discount_rate_floor {floor} (no treasury_10y given)"
    # Owner earnings start from net income, which is after interest expense (and includes the
    # interest earned on cash), so they are an equity cash flow: their present value is equity
    # value directly. Subtracting net debt as well counted the debt twice (measured 2026-09-30:
    # VICI $32 instead of $47, Exelon $6 instead of $54). The balance-sheet figure is quoted in
    # the note for context only.
    debt_last, cash_last = _last(ltd), _last(cash)
    net_debt_note = (
        "0: owner earnings are net income plus D&A less maintenance capex, already after "
        "interest, so they are an equity cash flow and dcf.py's value is equity value directly"
    )
    if debt_last is not None and cash_last is not None:
        net_debt_note += (
            f"; subtracting the balance sheet's net debt (long-term debt {debt_last:.2f} less "
            f"cash {cash_last:.2f} = {debt_last - cash_last:.2f}) would count the debt twice"
        )
    else:
        net_debt_note += "; subtracting the balance sheet's net debt would count the debt twice"
    dcf_input: dict = {
        "fcf0": _r2(oe_latest),
        "growth_rate": _r4(growth),
        "years": _DCF_YEARS,
        "terminal_growth": terminal_growth,
        "wacc": _r4(discount),
        "net_debt": 0.0,
        "net_debt_note": net_debt_note,
        "shares_outstanding": shares,
        "current_share_price": price,
    }
    if financial:
        dcf_input["net_debt"] = 0.0
        dcf_input["net_debt_note"] = (
            "set to 0 for business_type financial: deposits and borrowings are operating "
            "liabilities, not net debt to subtract from an owner-earnings DCF"
        )
        flags.append(
            {
                "code": "DCF_NOT_MEANINGFUL_FOR_FINANCIALS",
                "message": "business_type financial: owner earnings and the dcf_input are "
                "computed for completeness, but capex and D&A do not describe a bank's "
                "reinvestment; weigh book_value_tests instead",
            }
        )

    if utility:
        flags.append(
            {
                "code": "DCF_NOT_MEANINGFUL_FOR_UTILITIES",
                "message": "business_type utility: a regulated utility funds its growth with new "
                "debt and shares, so a cash-flow DCF says little; weigh utility_tests (P/E, P/B "
                "against return on equity, the dividend) and run ddm.py on its ddm_input",
            }
        )
    oe_known = [v for v in oe_series if v is not None]
    if oe_known and sum(1 for v in oe_known if v <= 0) * 2 >= len(oe_known):
        flags.append(
            {
                "code": "OWNER_EARNINGS_MOSTLY_NEGATIVE",
                "message": f"owner earnings were not positive in {sum(1 for v in oe_known if v <= 0)} "
                f"of {len(oe_known)} years; a DCF on them is not meaningful, and the mid-cycle "
                "input is withheld",
            }
        )
        mostly_negative = True
    else:
        mostly_negative = False

    roe = [_div(ni, eq) if eq and eq > 0 else None for ni, eq in zip(net_income, equity)]
    roe_present = [v for v in roe if v is not None]
    roe_share = sum(1 for v in roe_present if v >= 0.15) / len(roe_present) if roe_present else None
    de = _div(_last(ltd), _last(equity)) if _last(equity) and _last(equity) > 0 else None
    net_margin = _div(net_income[-1], revenue[-1])
    conversion = _div(_last(fcf), net_income[-1]) if net_income[-1] and net_income[-1] > 0 else None
    first_shares, last_shares = next((v for v in diluted if v is not None), None), _last(diluted)
    if financial:
        low_leverage = _check(
            "low_leverage",
            None,
            None,
            "skipped for business_type financial (deposits and borrowings are the business)",
        )
    else:
        low_leverage = _check(
            "low_leverage",
            de <= 0.5 if de is not None else None,
            _r4(de),
            "long-term debt / equity <= 0.5",
        )
    tenets = _score(
        [
            _check(
                "consistent_high_roe",
                roe_share >= 0.8 if roe_share is not None else None,
                {"years_at_or_above_15pct": _r4(roe_share), "latest": _r4(_last(roe))},
                "ROE >= 15% in at least 80% of years",
            ),
            low_leverage,
            _check(
                "high_net_margin",
                net_margin >= 0.10 if net_margin is not None else None,
                _r4(net_margin),
                "net margin >= 10%",
            ),
            _check(
                "consistent_operating_profit",
                _all_positive(op_income),
                {
                    "years": n,
                    "positive_years": sum(1 for v in op_income if v is not None and v > 0),
                },
                "positive operating income every year",
            ),
            _check(
                "positive_owner_earnings",
                _all_positive(oe_series),
                {
                    "years": n,
                    "positive_years": sum(1 for v in oe_series if v is not None and v > 0),
                },
                "positive owner earnings every year",
            ),
            _check(
                "cash_conversion",
                conversion >= 0.8 if conversion is not None else None,
                _r4(conversion),
                "free cash flow / net income >= 0.8",
            ),
            _check(
                "share_count_not_rising",
                last_shares <= first_shares
                if first_shares is not None and last_shares is not None
                else None,
                {"first": first_shares, "latest": last_shares},
                "diluted shares not above the first year's",
            ),
        ]
    )

    # ── business-type yardsticks ──────────────────────────────────────────
    book_value_tests = None
    if financial:
        roe_latest = _last(roe)
        roe_10y = _mean(roe[-_NORMALIZED_YEARS:])
        if pb is None:
            note = "no price or no positive book value; price-to-book is unavailable"
        elif roe_10y is None:
            note = f"P/B {pb:.2f}; ROE unavailable, so the justified P/B cannot be computed"
        else:
            justified = (
                (roe_10y - terminal_growth) / (discount - terminal_growth)
                if discount > terminal_growth
                else None
            )
            note = (
                f"P/B {pb:.2f} against ROE {roe_latest:.1%} (10y avg {roe_10y:.1%}); "
                f"a P/B of 1.0 is fair when ROE equals the discount rate {discount:.1%}, "
                "and the justified P/B at the 10y ROE is (ROE - g) / (r - g)"
                + (f" = {justified:.2f}" if justified is not None else " (undefined: r <= g)")
            )
        book_value_tests = {
            "price_to_book": _r4(pb),
            "roe_latest": _r4(roe_latest),
            "roe_10y_avg": _r4(roe_10y),
            "price_to_book_x_roe_note": note,
        }
    ddm_growth = (
        min(max(dps_cagr, _DDM_GROWTH_CLIP[0]), _DDM_GROWTH_CLIP[1])
        if dps_cagr is not None
        else terminal_growth
    )
    ddm_input = (
        {
            "model": "gordon",
            "dividend0": _r4(dividends_ps),
            "required_return": _r4(discount),
            "terminal_growth": _r4(min(ddm_growth, discount - 0.01)),
            "terminal_growth_note": (
                f"dividend-per-share CAGR {dps_cagr:.4f} over the table, clipped to "
                f"[{_DDM_GROWTH_CLIP[0]:g}, {_DDM_GROWTH_CLIP[1]:g}]"
                if dps_cagr is not None
                else "no dividend-per-share record; the terminal growth default"
            ),
        }
        if dividends_ps is not None and dividends_ps > 0
        else None
    )
    reit_tests = None
    if reit:
        positive_oe_ps = oe_ps if oe_ps is not None and oe_ps > 0 else None
        ebitda = (
            op_income[-1] + (da_latest or 0.0) if op_income[-1] is not None else None
        )
        net_debt_latest = (
            _last(ltd) - (_last(cash) or 0.0) if _last(ltd) is not None else None
        )
        reit_tests = {
            "affo_proxy_per_share": _r4(oe_ps),
            "price_to_affo_proxy": _r4(_div(price, positive_oe_ps)),
            "affo_proxy_yield": _r4(_div(positive_oe_ps, price)),
            "affo_proxy_per_share_cagr": _r4(_span_cagr(oe_ps_series)),
            "dividend_yield": _r4(_div(dividends_ps, price)),
            "dividend_per_share_cagr": _r4(dps_cagr),
            "payout_of_affo_proxy": _r4(_div(dividends_ps, positive_oe_ps)),
            "net_debt_to_ebitda": _r4(_div(net_debt_latest, ebitda))
            if ebitda is not None and ebitda > 0
            else None,
            "property_sale_gains_excluded": _r2(sale_gains[-1]),
            "ddm_input": ddm_input,
        }
    utility_tests = None
    if utility:
        roe_latest_u = _last(roe)
        utility_tests = {
            "pe": _r4(_div(price, eps_latest)) if eps_latest and eps_latest > 0 else None,
            "pe_3y_avg_eps": _r4(pe),
            "price_to_book": _r4(pb),
            "roe_latest": _r4(roe_latest_u),
            "roe_10y_avg": _r4(_mean(roe[-_NORMALIZED_YEARS:])),
            "dividend_yield": _r4(_div(dividends_ps, price)),
            "payout_of_eps": _r4(_div(dividends_ps, eps_latest))
            if eps_latest and eps_latest > 0
            else None,
            "dividend_per_share_cagr": _r4(dps_cagr),
            "ddm_input": ddm_input,
        }

    # ── normalized (mid-cycle) earnings ───────────────────────────────────
    # Averaged per share (each year on its own share count), then put on today's count: a
    # company that issued shares to grow is not marked down for having been smaller, and one
    # that diluted its holders is not flattered by its larger totals.
    eps_recent = eps[-_NORMALIZED_YEARS:]
    oe_ps_recent = oe_ps_series[-_NORMALIZED_YEARS:]
    if _present(oe_ps_recent) >= _NORMALIZED_MIN_YEARS and shares:
        oe_recent = oe_ps_recent
        oe_10y_ps = _mean(oe_ps_recent, _NORMALIZED_MIN_YEARS)
        oe_10y = oe_10y_ps * shares
        normalized_basis = "per share, each year on its own share count"
    else:
        oe_recent = oe_series[-_NORMALIZED_YEARS:]
        oe_10y = _mean(oe_recent, _NORMALIZED_MIN_YEARS)
        oe_10y_ps = _div(oe_10y, shares)
        normalized_basis = "total dollars (share counts missing)"
    eps_10y = _mean(eps_recent, _NORMALIZED_MIN_YEARS)
    graham_number_10y = _graham_number(eps_10y, book_value)
    dcf_input_mid_cycle = (
        {**dcf_input, "fcf0": _r2(oe_10y), "growth_rate": _r4(terminal_growth)}
        if oe_10y is not None and not mostly_negative
        else None
    )
    normalized = {
        "years": {"owner_earnings": _present(oe_recent), "eps": _present(eps_recent)},
        "basis": normalized_basis,
        "owner_earnings_10y_avg": _r2(oe_10y),
        "owner_earnings_10y_avg_per_share": _r4(oe_10y_ps),
        "eps_10y_avg": _r4(eps_10y),
        "graham_number_10y": _r2(graham_number_10y),
        "dcf_input_mid_cycle": dcf_input_mid_cycle,
    }
    if oe_10y is not None and oe_10y > 0 and oe_latest is not None:
        if oe_latest > _CYCLE_PEAK_RATIO * oe_10y:
            flags.append(
                {
                    "code": "CYCLE_PEAK",
                    "message": f"latest owner earnings are {oe_latest / oe_10y:.2f}x the "
                    f"{_present(oe_recent)}-year average; earnings-based values may be "
                    "on peak earnings, see normalized",
                }
            )

    margin_of_safety = [
        m
        for m in (
            # GAAP EPS understates a REIT, so Graham's EPS-based values are not set against its price.
            None if reit else _mos("graham_number", graham_number, price),
            None if reit else _mos("graham_number_10y", graham_number_10y, price),
            None if reit else _mos("graham_growth_formula", growth_formula_value, price),
            _mos("ncav", ncav, price),
        )
        if m is not None
    ]

    return {
        "fiscal_year": rows[-1].get("fiscal_year"),
        "years_covered": n,
        "inputs": {
            "price": price,
            "shares_outstanding": shares,
            "aaa_yield": aaa,
            "treasury_10y": treasury,
            "business_type": business_type,
            "discount_rate": {"value": _r4(discount), "source": discount_source},
            "growth_rate": {"value": _r4(growth), "source": growth_source},
            "growth_alternatives": growth_alternatives,
        },
        "per_share": {
            "eps_latest": _r4(eps_latest),
            "eps_3y_avg": _r4(eps_3y_avg),
            "book_value": _r4(book_value),
            "dividends": _r4(dividends_ps),
            "owner_earnings": _r4(oe_ps),
        },
        "graham": {
            "graham_number": _r2(graham_number),
            "growth_formula": {
                "value": _r2(growth_formula_value),
                "growth_used": _r4(growth),
                "aaa_yield": aaa,
            },
            "ncav_per_share": _r4(ncav),
            "net_net": net_net,
            "defensive_checklist": defensive,
        },
        "buffett": {
            "owner_earnings": {
                "net_income": _r2(net_income[-1]),
                "depreciation_amortization": _r2(da_latest),
                "capex": _r2(_last(capex)),
                "maintenance_capex": _r2(maint),
                "maintenance_capex_method": maint_method,
                "estimates": {
                    "depreciation_amortization": _r2(da_latest),
                    "average_capex": _r2(avg_capex),
                    "one_percent_of_revenue": _r2(one_pct_revenue),
                },
                "value": _r2(oe_latest),
                "per_share": _r4(oe_ps),
                "by_year": by_year,
            },
            "dcf_input": dcf_input,
            "tenets": tenets,
            "book_value_tests": book_value_tests,
            "reit_tests": reit_tests,
            "utility_tests": utility_tests,
        },
        "normalized": normalized,
        "margin_of_safety": margin_of_safety,
        "flags": flags,
    }


def main() -> None:
    try:
        params = json.load(sys.stdin)
        result = run_intrinsic(params)
    except (ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
