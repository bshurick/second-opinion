#!/usr/bin/env python3
"""Usage: inputs.py <symbol>

Filled `dcf.py` and `ddm.py` input JSONs from Yahoo. Output:

  {"symbol": ..., "as_of": "...", "business_type": ..., "sources": {...},
   "assumptions": {"risk_free": {"value": ..., "source": "..."}, ...},
   "dcf_input": {...ready to pipe into dcf.py...},
   "dcf_scenarios": {"bear": {...}, "base": {...}, "bull": {...}},
   "ddm_input": {...ready to pipe into ddm.py...},
   "flags": [...]}

How each figure is built (all of it echoed in "assumptions" with its source,
so every one can be challenged):

- fcf0 is free cash flow TO THE FIRM: the latest annual statement's free cash
  flow (operating cash flow less capital spending) plus after-tax interest, so
  it matches a WACC discount rate and a net-debt subtraction. Yahoo's
  `info.free_cash_flow` is used only when the statement has none.
- fcf0 is normalized: when at least three annual statements are there and the
  latest year's free cash flow is above the average margin applied to the
  latest revenue, the average is used, so one strong year does not set it.
- wacc is a real weighted cost of capital: cost of equity = risk-free +
  adjusted beta x equity risk premium; cost of debt = interest expense / total
  debt, kept within [risk-free, risk-free + 6%]; weights from market value of
  equity and total debt; debt after tax. The risk-free rate is the 10-year
  Treasury (^TNX; the 13-week ^IRX only when that is missing). Beta is the
  usual adjustment toward 1 (0.67 x raw + 0.33), so a very low raw beta does
  not produce a discount rate below what any equity earns. The result is
  never below risk-free + 2.5%.
- growth_rate is the lower of the revenue CAGR and the free-cash-flow CAGR
  over the annual statements, kept within [0, 15%].
- dcf_scenarios are three inputs that differ in the business assumption, not
  the discount rate: each fades growth in a straight line to terminal growth
  over the stage, starting from the hint (base), from below it (bear) and from
  above it (bull). The spread is the larger of 3 points and half the hint.
- ddm_input discounts at the cost of equity. dividend_cagr runs over complete
  calendar years only: the first year in the history window and the current
  year are partial and are left out.
- business_type comes from Yahoo's sector: Financial Services -> financial,
  Real Estate -> reit, Utilities -> utility, else industrial. For the three
  special types a cash-flow DCF says little and a flag names what to use
  instead (intrinsic-inputs.py | intrinsic.py, and ddm.py).

Stated defaults (challenge all of them): equity risk premium 5%, terminal
growth 2.5%, stage-1 years 5, tax rate 21% when the statement has none, cost
of debt risk-free + 2% when it cannot be measured, DDM model Gordon. Fields
the data cannot fill are null for the agent to set.

Exit codes: 0, 2, 5, 6. stdin is not read.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

_DEFAULT_ERP = 0.05
_DEFAULT_TERMINAL_GROWTH = 0.025
_DEFAULT_YEARS = 5
_DEFAULT_TAX_RATE = 0.21
_DEFAULT_DEBT_SPREAD = 0.02
_MAX_DEBT_SPREAD = 0.06
_MAX_TAX_RATE = 0.35
_GROWTH_CLIP = (0.0, 0.15)
_SCENARIO_MIN_SPREAD = 0.03
_SCENARIO_BOUNDS = (-0.05, 0.25)
_RISK_FREE_SYMBOLS = (("^TNX", "10-year Treasury yield"), ("^IRX", "13-week T-bill yield (no 10-year quote)"))
_BUSINESS_TYPES = {"Financial Services": "financial", "Real Estate": "reit", "Utilities": "utility"}
# A discount rate this close to the Treasury leaves no reward for owning a business.
_MIN_WACC_SPREAD = 0.025
_FLAG_SUFFIX = {"financial": "FINANCIALS", "reit": "REITS", "utility": "UTILITIES"}
_DCF_CAVEAT = {
    "financial": "a bank's or insurer's cash flow carries customer money and its debt is its raw material; use intrinsic.py's book_value_tests",
    "reit": "a REIT pays out most of its cash and grows by issuing shares and debt; use intrinsic.py's reit_tests (the AFFO proxy) and ddm.py",
    "utility": "a regulated utility funds its growth with new debt and shares, so free cash flow is usually negative; use intrinsic.py's utility_tests and ddm.py",
}


def _cagr(series: list[tuple[str, float]]) -> float | None:
    """CAGR of a statement series of (period_end_date, value), or None when
    there are fewer than 2 points, a non-positive endpoint, or a zero span."""
    if len(series) < 2:
        return None
    first_date, first = series[0]
    last_date, last = series[-1]
    try:
        # Statement keys are period ends, with or without a time part ("2025-12-31T00:00:00").
        span = (date.fromisoformat(last_date[:10]) - date.fromisoformat(first_date[:10])).days / 365.25
    except ValueError:
        return None
    if span <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / span) - 1


def _statement_series(statement: dict, field: str) -> list[tuple[str, float]]:
    """Sorted [(period_end, value)] for statement rows reporting ``field``."""
    rows = [
        (period, row[field])
        for period, row in statement.items()
        if isinstance(row, dict) and isinstance(row.get(field), (int, float))
    ]
    return sorted(rows)


def _ttm_dividend(rows: list[dict], as_of: date) -> float | None:
    """Sum of per-share dividends paid in the 365 days before as_of."""
    cutoff = (as_of - timedelta(days=365)).isoformat()
    recent = [r["dividend"] for r in rows if r.get("date") and r["date"] >= cutoff]
    return round(sum(recent), 4) if recent else None


def _dividend_cagr(rows: list[dict], as_of: date) -> float | None:
    """CAGR of calendar-year dividend totals over COMPLETE years only: the current year is
    partial, and so is the first year in the history (the window opens mid-year), and a
    partial year at either end would bias the rate."""
    annual: dict[int, float] = {}
    for r in rows:
        if r.get("date") and r.get("dividend"):
            year = int(r["date"][:4])
            annual[year] = annual.get(year, 0.0) + r["dividend"]
    complete = sorted(y for y in annual if y < as_of.year)[1:]
    if len(complete) < 2:
        return None
    span = complete[-1] - complete[0]
    first, last = annual[complete[0]], annual[complete[-1]]
    if span <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / span) - 1


def _clip(value: float, bounds: tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])


def _latest_row(statement: dict) -> dict:
    periods = sorted(p for p, row in statement.items() if isinstance(row, dict))
    return statement[periods[-1]] if periods else {}


def _number(row: dict, field: str) -> float | None:
    v = row.get(field)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _risk_free() -> tuple[float | None, str, str | None]:
    """(rate, source text, symbol used). Yahoo quotes both yields in percentage points."""
    for symbol, label in _RISK_FREE_SYMBOLS:
        quotes = market.quote([symbol])
        price = quotes[0].get("price") if quotes else None
        if price:
            return round(float(price) / 100, 4), f"Yahoo {symbol} {label}, divided by 100", symbol
    return None, "no Treasury quote from Yahoo; set it by hand", None


def fade(start: float, terminal: float, years: int) -> list[float]:
    """Growth per year in a straight line from ``start`` to ``terminal`` in the last year."""
    if years == 1:
        return [round(start, 4)]
    return [round(start + (terminal - start) * t / (years - 1), 4) for t in range(years)]


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        if len(args) != 1 or args[0].startswith("--"):
            raise InvalidInput("usage: inputs.py <symbol>")
        symbol = brokerage.validate_symbol(args[0])
        as_of = date.today()

        info = market.company_info(symbol)
        stmts = market.financials(symbol)
        risk_free, risk_free_source, risk_free_symbol = _risk_free()
        flags: list[dict] = []

        business_type = _BUSINESS_TYPES.get(info.get("sector") or "", "industrial")
        if business_type != "industrial":
            flags.append({"code": f"DCF_NOT_MEANINGFUL_FOR_{_FLAG_SUFFIX[business_type]}", "message": f"Yahoo sector {info.get('sector')}: {_DCF_CAVEAT[business_type]}"})

        income = _latest_row(stmts.get("income_statement") or {})
        interest = _number(income, "Interest Expense")
        interest = abs(interest) if interest is not None else None
        tax_reported = _number(income, "Tax Rate For Calcs")
        tax_rate = _clip(tax_reported, (0.0, _MAX_TAX_RATE)) if tax_reported is not None else _DEFAULT_TAX_RATE

        # Cost of equity: CAPM on a beta pulled a third of the way toward 1.
        beta = info.get("beta")
        adjusted_beta = round(0.67 * float(beta) + 0.33, 4) if beta is not None else None
        cost_of_equity = (
            round(risk_free + adjusted_beta * _DEFAULT_ERP, 4)
            if risk_free is not None and adjusted_beta is not None
            else None
        )

        total_debt, total_cash, market_cap = info.get("total_debt"), info.get("total_cash"), info.get("market_cap")
        if risk_free is None:
            cost_of_debt, cost_of_debt_source = None, "no risk-free rate"
        elif interest and total_debt and total_debt > 0:
            raw = interest / float(total_debt)
            cost_of_debt = round(_clip(raw, (risk_free, risk_free + _MAX_DEBT_SPREAD)), 4)
            cost_of_debt_source = f"interest expense / total debt = {raw:.4f}, kept within [risk-free, risk-free + {_MAX_DEBT_SPREAD:g}]"
        else:
            cost_of_debt = round(risk_free + _DEFAULT_DEBT_SPREAD, 4)
            cost_of_debt_source = f"stated default: risk-free + {_DEFAULT_DEBT_SPREAD:g} (no interest expense or debt to measure it)"

        debt = float(total_debt) if total_debt else 0.0
        if cost_of_equity is None:
            wacc, wacc_source = None, "needs a risk-free rate and a beta"
        elif not market_cap or market_cap <= 0:
            wacc, wacc_source = cost_of_equity, "cost of equity (no market value to weight debt against)"
        else:
            weight_debt = debt / (debt + float(market_cap))
            wacc = round((1 - weight_debt) * cost_of_equity + weight_debt * (cost_of_debt or 0.0) * (1 - tax_rate), 4)
            wacc_source = f"{1 - weight_debt:.0%} equity at the cost of equity + {weight_debt:.0%} debt at the cost of debt after {tax_rate:.0%} tax (market-value weights)"
        if wacc is not None and wacc < risk_free + _MIN_WACC_SPREAD:
            wacc_source += f"; that gave {wacc}, raised to the floor of risk-free + {_MIN_WACC_SPREAD:g}"
            wacc = round(risk_free + _MIN_WACC_SPREAD, 4)

        fcf_series = _statement_series(stmts.get("cash_flow") or {}, "Free Cash Flow")
        rev_series = _statement_series(stmts.get("income_statement") or {}, "Total Revenue")
        revenue_by_period = dict(rev_series)
        margins = [v / revenue_by_period[p] for p, v in fcf_series if revenue_by_period.get(p)]
        if fcf_series:
            fcf, fcf_source = fcf_series[-1][1], f"latest annual statement free cash flow ({fcf_series[-1][0][:10]})"
            latest_revenue = revenue_by_period.get(fcf_series[-1][0])
            if len(margins) >= 3 and latest_revenue:
                # One strong year (a cyclical peak, a working-capital swing) should not set the value.
                normal = sum(margins) / len(margins) * latest_revenue
                if normal < fcf:
                    fcf, fcf_source = normal, f"average free-cash-flow margin over {len(margins)} annual statements ({sum(margins) / len(margins):.4f}) x latest revenue, lower than the latest year's {fcf_series[-1][1]:.0f}"
        else:
            fcf, fcf_source = info.get("free_cash_flow"), "Yahoo info.free_cash_flow (no statement figure; Yahoo's own trailing estimate, often unreliable)"
        after_tax_interest = interest * (1 - tax_rate) if interest is not None else 0.0
        fcf0 = round(float(fcf) + after_tax_interest, 2) if fcf is not None else None
        if fcf0 is not None and fcf0 <= 0:
            flags.append({"code": "NEGATIVE_FCF", "message": "free cash flow to the firm is not positive; a DCF on it has no meaning, and the reverse-DCF block will be null"})

        fcf_cagr, rev_cagr = _cagr(fcf_series), _cagr(rev_series)
        candidates = [v for v in (rev_cagr, fcf_cagr) if v is not None]
        growth_hint = round(_clip(min(candidates), _GROWTH_CLIP), 4) if candidates else None
        growth_source = (
            f"lower of revenue CAGR {rev_cagr if rev_cagr is None else round(rev_cagr, 4)} and free-cash-flow CAGR "
            f"{fcf_cagr if fcf_cagr is None else round(fcf_cagr, 4)} over the annual statements, kept within [{_GROWTH_CLIP[0]:g}, {_GROWTH_CLIP[1]:g}]"
        )

        net_debt = (
            round(float(total_debt) - float(total_cash), 2)
            if total_debt is not None and total_cash is not None
            else None
        )
        shares = info.get("shares_outstanding") or stmts.get("shares_outstanding")

        div_rows = market.dividend_histories([symbol], years=6).get(symbol) or []
        dividend0 = _ttm_dividend(div_rows, as_of)
        dividend_cagr = _dividend_cagr(div_rows, as_of)

        assumptions = {
            "risk_free": {"value": risk_free, "source": risk_free_source},
            "equity_risk_premium": {"value": _DEFAULT_ERP, "source": "stated default; challenge it"},
            "beta": {"value": beta, "source": "Yahoo info.beta"},
            "adjusted_beta": {"value": adjusted_beta, "source": "0.67 x beta + 0.33 (the usual pull toward 1)"},
            "cost_of_equity": {"value": cost_of_equity, "source": "CAPM: risk_free + adjusted_beta * equity_risk_premium"},
            "cost_of_debt": {"value": cost_of_debt, "source": cost_of_debt_source},
            "tax_rate": {"value": round(tax_rate, 4), "source": "latest income statement" if tax_reported is not None else "stated default"},
            "wacc": {"value": wacc, "source": wacc_source},
            "fcf0": {"value": fcf0, "source": f"{fcf_source} plus after-tax interest {round(after_tax_interest, 2)}: free cash flow to the firm"},
            "growth_rate": {"value": growth_hint, "source": growth_source},
            "terminal_growth": {
                "value": _DEFAULT_TERMINAL_GROWTH,
                "source": "stated default; keep between 0% and 5%",
            },
            "years": {"value": _DEFAULT_YEARS, "source": "stated default; stage-1 length is your choice"},
            "dividend_cagr": {
                "value": round(dividend_cagr, 4) if dividend_cagr is not None else None,
                "source": "calendar-year dividend totals from Yahoo dividend history, complete years only",
            },
            "business_type": {"value": business_type, "source": f"Yahoo sector {info.get('sector')}"},
        }
        dcf_input = {
            "fcf0": fcf0,
            "growth_rate": growth_hint,
            "years": _DEFAULT_YEARS,
            "terminal_growth": _DEFAULT_TERMINAL_GROWTH,
            "wacc": wacc,
            "net_debt": net_debt,
            "shares_outstanding": shares,
            "current_share_price": info.get("current_price"),
        }
        dcf_scenarios = None
        if growth_hint is not None:
            spread = max(_SCENARIO_MIN_SPREAD, growth_hint / 2)
            starts = {
                "bear": _clip(growth_hint - spread, _SCENARIO_BOUNDS),
                "base": growth_hint,
                "bull": _clip(growth_hint + spread, _SCENARIO_BOUNDS),
            }
            dcf_scenarios = {
                name: {**{k: v for k, v in dcf_input.items() if k != "growth_rate"}, "stage1_growth": fade(start, _DEFAULT_TERMINAL_GROWTH, _DEFAULT_YEARS)}
                for name, start in starts.items()
            }
        ddm_input = {
            "model": "gordon",
            "dividend0": dividend0,
            "required_return": cost_of_equity,
            "terminal_growth": _DEFAULT_TERMINAL_GROWTH,
        }
        return {
            "symbol": symbol,
            "as_of": as_of.isoformat(),
            "business_type": business_type,
            "sources": {
                "info": "yahoo",
                "financials": "yahoo",
                "dividends": "yahoo",
                "risk_free": f"yahoo ({risk_free_symbol})" if risk_free_symbol else None,
            },
            "assumptions": assumptions,
            "dcf_input": dcf_input,
            "dcf_scenarios": dcf_scenarios,
            "ddm_input": ddm_input,
            "flags": flags,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())