#!/usr/bin/env python3
"""Usage: inputs.py <symbol> [--erp RATE --erp-date YYYY-MM-DD]

Filled `dcf.py` and `ddm.py` input JSONs from Yahoo. Output:

  {"symbol": ..., "as_of": "...", "business_type": ..., "sources": {...},
   "assumptions": {"risk_free": {"value": ..., "source": "..."}, ...},
   "dcf_input": {...ready to pipe into dcf.py...},
   "dcf_input_latest": {...same, on the latest year's cash flow; cyclicals only...},
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
- Cyclicals: flag CYCLICAL fires when any annual FCF margin is zero or
  negative while the latest is positive, or the largest margin is more than 3x
  the smallest (smallest positive). The normalized fcf0 stays the base, but
  assumptions.fcf0_latest {"value", "source"} (always present, null without
  statements) holds the latest year's free cash flow to the firm (after-tax
  interest added, minority share scaled the same way), and the output carries
  dcf_input_latest: a copy of dcf_input with fcf0 replaced by that figure, only
  when CYCLICAL fires. When the two figures differ by more than 2x, flag
  CYCLE_BASE_SPLIT: present both, never one base value. A mid-cycle view comes
  from intrinsic.py's normalized block.
- wacc is a real weighted cost of capital: cost of equity = risk-free +
  adjusted beta x equity risk premium (a dated default, flagged ERP_DEFAULT,
  or --erp RATE --erp-date YYYY-MM-DD within 2%-10%; ERP_STALE when the default
  is over 180 days old); cost of debt = interest expense / total
  debt, kept within [risk-free, risk-free + 6%]; weights from market value of
  equity and net debt (total debt less cash, floored at zero, so a company
  holding more cash than debt carries no debt weight; gross debt when cash is
  unknown, and the source says so). dcf.py subtracts net_debt from enterprise
  value, so weighting net debt keeps the two consistent. Debt after tax. The risk-free rate is the 10-year
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
- shares_outstanding is Yahoo's `impliedSharesOutstanding` (every share class)
  when present, else `sharesOutstanding`, else the statement figure. Yahoo's
  `sharesOutstanding` can hold one class of a dual-class company; when the
  implied count is more than 5% above it, flag SHARE_CLASSES_COMBINED names both.
- A corporate-action check compares the latest annual income statement's
  Diluted Average Shares with today's share count; a ratio below 0.75 or above
  1.33 raises CORPORATE_ACTION_SUSPECTED (a split, reverse split or spin-off may
  separate the statements from today's share count, so per-share DCF values are
  not meaningful until a post-action year is reported). Yahoo restates share history
  for splits and spin-offs, so the same flag also fires when its split record shows an
  adjustment (spin-offs appear as fractional ratios) dated after the latest annual statement.
- nci_share is the share of net income that goes to noncontrolling interests
  (Yahoo's "Minority Interests", reported negative, over "Net Income Including
  Noncontrolling Interests"); null when the rows are absent. At 10% or more
  (and under 100%), flag LARGE_MINORITY_INTEREST: fcf0 is scaled by
  (1 - nci_share) to the parent's share, and the tax rate is recomputed as tax
  provision / (pretax income - minority interests), since the consolidated rate
  blends in partners' earnings. Book NCI understates the claim, so a deep model
  should value it from NCI earnings. Under 10% nothing is scaled. When the
  share is 100% or more, zero or negative, or the parent's net income is not
  positive while the partners' is, the parent's share cannot be derived:
  nci_share is null, fcf0 is NOT scaled (no sign flip) and the same flag says
  so. dcf.py subtracts consolidated net debt from a parent-share fcf0, an
  approximation that over-deducts when the partners' subsidiaries carry the
  debt; a deep model values the partners' claim explicitly.
- Order of operations: tax basis (consolidated, or the parent's when NCI is
  large) -> WACC -> FCFF (free cash flow plus after-tax interest) -> minority
  scaling -> cyclical comparison (normalized vs latest year, after scaling) ->
  scenarios.
- business_type comes from Yahoo's sector: Financial Services -> financial,
  Real Estate -> reit, Utilities -> utility, else industrial. For the three
  special types a cash-flow DCF says little and a flag names what to use
  instead (intrinsic-inputs.py | intrinsic.py, and ddm.py).

Stated defaults (challenge all of them): equity risk premium 4.2% dated 2026-10-01 (flagged ERP_DEFAULT), terminal
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

_DEFAULT_ERP = 0.042
_DEFAULT_ERP_AS_OF = "2026-10-01"
_ERP_STALE_DAYS = 180
_ERP_BOUNDS = (0.02, 0.10)
_DEFAULT_TERMINAL_GROWTH = 0.025
_DEFAULT_YEARS = 5
_DEFAULT_TAX_RATE = 0.21
_DEFAULT_DEBT_SPREAD = 0.02
_MAX_DEBT_SPREAD = 0.06
_MAX_TAX_RATE = 0.35
_NCI_FLAG = 0.10
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
        usage = "usage: inputs.py <symbol> [--erp RATE --erp-date YYYY-MM-DD]"
        if not args or args[0].startswith("--"):
            raise InvalidInput(usage)
        symbol = brokerage.validate_symbol(args[0])
        opts: dict[str, str] = {}
        rest = args[1:]
        while rest:
            if rest[0] not in ("--erp", "--erp-date") or len(rest) < 2 or rest[0] in opts:
                raise InvalidInput(usage)
            opts[rest[0]], rest = rest[1], rest[2:]
        if ("--erp" in opts) != ("--erp-date" in opts):
            raise InvalidInput("--erp and --erp-date go together: a premium needs the date of its source")
        as_of = date.today()
        if opts:
            try:
                erp = float(opts["--erp"])
                erp_as_of = date.fromisoformat(opts["--erp-date"]).isoformat()
            except ValueError:
                raise InvalidInput("--erp must be a number and --erp-date a YYYY-MM-DD date") from None
            if not _ERP_BOUNDS[0] <= erp <= _ERP_BOUNDS[1]:
                raise InvalidInput(f"--erp {erp:g} is outside {_ERP_BOUNDS[0]:g}-{_ERP_BOUNDS[1]:g}")
            erp_source = f"--erp argument, dated {erp_as_of}"
        else:
            erp, erp_as_of = _DEFAULT_ERP, _DEFAULT_ERP_AS_OF
            erp_source = f"Damodaran implied ERP, {erp_as_of} (stated default; pass --erp with a dated figure)"

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
        tax_source = "latest income statement" if tax_reported is not None else "stated default"

        # Noncontrolling interests: partners' share of earnings.
        net_income_total = _number(income, "Net Income Including Noncontrolling Interests")
        minority = _number(income, "Minority Interests")
        nci_share = None
        nci_unbounded = False
        if minority is not None and minority != 0:
            # Yahoo reports the partners' profit as a negative number.
            partners = -minority
            if net_income_total and net_income_total > 0 and 0 < partners < net_income_total:
                nci_share = round(partners / net_income_total, 4)
            else:
                nci_unbounded = True
        elif minority == 0 and net_income_total and net_income_total > 0:
            nci_share = 0.0
        nci_large = nci_share is not None and nci_share >= _NCI_FLAG
        if nci_large:
            provision, pretax = _number(income, "Tax Provision"), _number(income, "Pretax Income")
            parent_pretax = pretax + minority if pretax is not None else None
            if provision is not None and parent_pretax and parent_pretax > 0:
                tax_rate = _clip(provision / parent_pretax, (0.0, _MAX_TAX_RATE))
                tax_source = "tax provision / (pretax income - minority interests): the rate on income attributable to the parent"

        # Cost of equity: CAPM on a beta pulled a third of the way toward 1.
        beta = info.get("beta")
        adjusted_beta = round(0.67 * float(beta) + 0.33, 4) if beta is not None else None
        cost_of_equity = (
            round(risk_free + adjusted_beta * erp, 4)
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
            if total_cash is None:
                weighted_debt, basis = debt, "gross debt (cash unknown), market-value weights"
            else:
                weighted_debt = max(debt - float(total_cash), 0.0)
                basis = "debt net of cash, market-value weights" if weighted_debt else "net cash: no debt weight"
            weight_debt = weighted_debt / (weighted_debt + float(market_cap))
            wacc = round((1 - weight_debt) * cost_of_equity + weight_debt * (cost_of_debt or 0.0) * (1 - tax_rate), 4)
            wacc_source = f"{1 - weight_debt:.0%} equity at the cost of equity + {weight_debt:.0%} debt at the cost of debt after {tax_rate:.0%} tax ({basis})"
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
        if nci_unbounded:
            flags.append({"code": "LARGE_MINORITY_INTEREST", "message": "the parent's share of earnings cannot be derived (the partners' share of net income is 100% or more, or not positive, or the parent's net income is not positive); fcf0 is NOT scaled and stays on the consolidated basis. Value the partners' claim explicitly in a deep model."})
        if nci_large:
            if fcf0 is not None:
                fcf0 = round(fcf0 * (1 - nci_share), 2)
            flags.append({"code": "LARGE_MINORITY_INTEREST", "message": f"partners own {nci_share:.0%} of earnings; fcf0 is scaled to the parent's share. Book NCI understates the claim — value it from NCI earnings in a deep model."})
        fcf0_latest = None
        if fcf_series:
            fcf0_latest = round(float(fcf_series[-1][1]) + after_tax_interest, 2)
            if nci_large:
                fcf0_latest = round(fcf0_latest * (1 - nci_share), 2)
        nci_note = f", scaled by (1 - nci_share {nci_share}) to the parent's share (LARGE_MINORITY_INTEREST)" if nci_large else ""
        nci_note_latest = ", minority share scaled like fcf0" if nci_large else ""
        cyclical = bool(margins) and (
            (min(margins) <= 0 < margins[-1]) or (min(margins) > 0 and max(margins) / min(margins) > 3)
        )
        if cyclical:
            flags.append({"code": "CYCLICAL", "message": f"free-cash-flow margin ran from {min(margins):.0%} to {max(margins):.0%} over {len(margins)} annual statements; a single year's cash flow is a poor base. dcf_input holds the normalized figure and dcf_input_latest the latest year's."})
            if fcf0 is not None and fcf0_latest is not None and (min(fcf0, fcf0_latest) <= 0 or max(fcf0, fcf0_latest) / min(fcf0, fcf0_latest) > 2):
                flags.append({"code": "CYCLE_BASE_SPLIT", "message": "normalized and latest-year cash flow differ more than 2x; present both and do not report one base value; intrinsic.py's normalized block gives a mid-cycle view."})
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
        info_shares = info.get("shares_outstanding")
        implied_shares = info.get("implied_shares_outstanding")
        shares = implied_shares or info_shares or stmts.get("shares_outstanding")
        if implied_shares:
            shares_source = "Yahoo info.impliedSharesOutstanding (every share class)"
        elif info_shares:
            shares_source = "Yahoo info.sharesOutstanding"
        else:
            shares_source = "latest financial statements"
        if implied_shares and info_shares and float(implied_shares) > float(info_shares) * 1.05:
            flags.append({"code": "SHARE_CLASSES_COMBINED", "message": f"Yahoo sharesOutstanding {float(info_shares):.0f} counts one share class; the implied count of {float(implied_shares):.0f} (every class) is used"})
        statement_shares = _number(income, "Diluted Average Shares")
        if shares and statement_shares:
            ratio = float(shares) / statement_shares
            if ratio < 0.75 or ratio > 1.33:
                flags.append({"code": "CORPORATE_ACTION_SUSPECTED", "message": f"today's share count {float(shares):.0f} is {ratio:.2f}x the latest annual statement's diluted average shares {statement_shares:.0f}; a split, reverse split or spin-off may separate the statements from today's share count, and the DCF per-share values are not meaningful until a post-action year is reported"})
        # Yahoo restates past share counts for splits and spin-offs, which hides them from the ratio
        # above; its split record (spin-offs appear as fractional ratios) dated after the latest
        # annual statement still gives them away.
        annual_periods = sorted(str(p)[:10] for p, row in (stmts.get("income_statement") or {}).items() if isinstance(row, dict))
        if annual_periods and not any(f["code"] == "CORPORATE_ACTION_SUSPECTED" for f in flags):
            try:
                split_rows = (market.splits(symbol) or {}).get("splits") or []
            except Exception:  # noqa: BLE001 - the split record is a cross-check, never a failure
                split_rows = []
            later = [r for r in split_rows if str(r.get("date") or "")[:10] > annual_periods[-1]
                     and isinstance(r.get("split_ratio"), (int, float)) and abs(float(r["split_ratio"]) - 1) > 0.001]
            if later:
                events = ", ".join(f"{str(r['date'])[:10]} (ratio {float(r['split_ratio']):g})" for r in later)
                flags.append({"code": "CORPORATE_ACTION_SUSPECTED", "message": f"Yahoo records a split or spin-off adjustment after the latest annual statement ({annual_periods[-1]}): {events}; the statements may describe a business or share count that no longer exists, and the DCF per-share values are not meaningful until a post-action year is reported"})

        div_rows = market.dividend_histories([symbol], years=6).get(symbol) or []
        dividend0 = _ttm_dividend(div_rows, as_of)
        dividend_cagr = _dividend_cagr(div_rows, as_of)

        if not opts:
            flags.append({"code": "ERP_DEFAULT", "message": f"the equity risk premium is the stated default {_DEFAULT_ERP:g} dated {_DEFAULT_ERP_AS_OF}; pass --erp RATE --erp-date YYYY-MM-DD with a dated figure to replace it"})
            if (as_of - date.fromisoformat(_DEFAULT_ERP_AS_OF)).days > _ERP_STALE_DAYS:
                flags.append({"code": "ERP_STALE", "message": f"the default equity risk premium is dated {_DEFAULT_ERP_AS_OF}, over {_ERP_STALE_DAYS} days old; pass --erp with a current dated figure"})

        assumptions = {
            "risk_free": {"value": risk_free, "source": risk_free_source},
            "equity_risk_premium": {"value": erp, "source": erp_source, "as_of": erp_as_of},
            "beta": {"value": beta, "source": "Yahoo info.beta"},
            "adjusted_beta": {"value": adjusted_beta, "source": "0.67 x beta + 0.33 (the usual pull toward 1)"},
            "cost_of_equity": {"value": cost_of_equity, "source": "CAPM: risk_free + adjusted_beta * equity_risk_premium"},
            "cost_of_debt": {"value": cost_of_debt, "source": cost_of_debt_source},
            "tax_rate": {"value": round(tax_rate, 4), "source": tax_source},
            "nci_share": {"value": nci_share, "source": "minority interests / net income including noncontrolling interests, latest income statement" if nci_share is not None else ("the parent's share cannot be derived (partners' share of net income is 100% or more, or not positive, or the parent's net income is not positive); fcf0 not scaled" if nci_unbounded else "not reported")},
            "wacc": {"value": wacc, "source": wacc_source},
            "fcf0_latest": {"value": fcf0_latest, "source": f"latest annual statement free cash flow ({fcf_series[-1][0][:10]}) plus after-tax interest{nci_note_latest}" if fcf_series else "no annual statements"},
            "fcf0": {"value": fcf0, "source": f"{fcf_source} plus after-tax interest {round(after_tax_interest, 2)}: free cash flow to the firm{nci_note}"},
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
            "shares_outstanding": {"value": shares, "source": shares_source},
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
            **({"dcf_input_latest": {**dcf_input, "fcf0": fcf0_latest}} if cyclical else {}),
            "dcf_scenarios": dcf_scenarios,
            "ddm_input": ddm_input,
            "flags": flags,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())