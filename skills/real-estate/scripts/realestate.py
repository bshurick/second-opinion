"""Real-estate calculators: mortgage amortization, refinance breakeven, rent
versus buy, rental-property underwriting, affordability, and REIT multiples.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python realestate.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).
Rates are decimals (0.06 = 6%). The ``action`` field selects the calculator:

``mortgage``::

    {"action": "mortgage", "principal": 300000 | ("price": 375000, "down_payment": 75000),
     "rate": 0.06, "years": 30, "extra_payment": 200 (monthly, optional),
     "property_tax_rate": 0.012, "insurance_annual": 1500, "hoa_monthly": 100,
     "pmi_rate": 0.005 (annual, charged when down payment < 20%)}
    -> {principal, payment, months, total_interest, total_paid, piti, pmi_monthly,
        down_payment_pct, pmi_total, pmi_off_year,
        schedule: [{year, interest, principal, balance, pmi}],
        with_extra: {months, total_interest, months_saved, interest_saved}}

``refinance``::

    {"action": "refinance", "balance": 200000, "current_rate": 0.07,
     "remaining_months": 300, "new_rate": 0.055, "new_years": 30, "closing_costs": 4000}
    -> {current_payment, new_payment, monthly_savings, breakeven_months,
        current_remaining_interest, new_total_interest, lifetime_delta,
        term_extension_months, new_loan_at_current_payment: {months, interest},
        savings_path: [{year, cumulative_savings}]}

``rent_vs_buy`` (annual steps)::

    {"action": "rent_vs_buy", "price", "down_payment", "rate", "years", "horizon_years",
     "property_tax_rate", "maintenance_rate", "insurance_annual", "hoa_monthly",
     "buy_closing_rate", "sell_closing_rate", "appreciation",
     "rent", "rent_growth", "investment_return"}
    -> {by_year: [{year, buy_cost_cumulative, rent_cost_cumulative, home_equity,
                   renter_portfolio, buy_net_worth, rent_net_worth, advantage_buy}],
        breakeven_year, monthly_cost_year1: {buy, rent}, assumptions}

``rental``::

    {"action": "rental", "price", "down_payment", "rate", "years", "closing_costs",
     "rent" (monthly), "vacancy_rate", "property_tax_annual", "insurance_annual",
     "maintenance_rate" (of EGI), "management_rate" (of EGI), "hoa_monthly",
     "utilities_annual", "other_annual", "capex_reserve_rate" (of EGI, default 0),
     "leasing_rate" (of EGI, default 0; a realistic load is 4-8%),
     "hold_years", "rent_growth", "expense_growth", "appreciation", "sell_closing_rate",
     "tax_growth" (property_tax_annual's growth rate in the projection; default
     = appreciation), "scenarios": true (auto grid) | {"appreciation": [...],
     "rent_growth": [...]} (requires hold_years)}
    -> {gross_rent, effective_gross_income, operating_expenses, noi, cap_rate,
        debt_service, dscr, cash_flow, cash_invested, cash_on_cash, grm,
        rent_to_price, one_percent_rule, break_even_occupancy, expense_ratio,
        projection: {hold_years, cash_flows, sale_price, loan_balance_at_sale,
                     total_profit, equity_multiple, irr},   # when hold_years given
        scenarios: [{appreciation, rent_growth, irr, total_profit,
                     cash_on_cash}]}   # when "scenarios" given

``affordability``::

    {"action": "affordability", "annual_income", "monthly_debts", "down_payment",
     "rate", "years", "property_tax_rate", "insurance_annual",
     "front_end": 0.28, "back_end": 0.36}
    -> {max_housing_payment, binding_ratio, max_loan, max_price, piti_at_max}

``reit``::

    {"action": "reit", "price", "shares", "net_income", "depreciation",
     "gains_on_sale", "recurring_capex", "dividend_per_share", "nav_per_share"}
    -> {ffo, ffo_per_share, p_ffo, ffo_yield, affo, affo_per_share, p_affo,
        dividend_yield, ffo_payout, affo_payout, nav_premium}

Method notes: payments use the standard annuity formula with monthly
compounding, rounded to cents before amortizing (as lenders do); the
rent-vs-buy model has the renter invest the buyer's upfront cash and each
year's cost difference at ``investment_return``, and values the buyer's
position net of selling costs every year; the refinance ``savings_path`` is
the cash kept by the end of each year (current payments no longer owed,
less new payments made and closing costs) through the longer of the two
terms, so it crosses zero at ``breakeven_months`` and its last row equals
``lifetime_delta``; rental IRR is
the levered internal rate of return of the annual cash flows including sale
proceeds (bisection). FFO = net income + depreciation - gains on sale
(NAREIT); AFFO = FFO - recurring capex. Money 2 dp, ratios 4 dp.

PMI is modeled as a monthly charge until the balance crosses 80% LTV (the
borrower-requestable cancellation point); lenders auto-cancel at 78% by law
-- the 80% threshold used here is the conservative, borrower-actionable one.
PMI/LTV step-off requires ``price`` (with ``down_payment``) to establish the
loan-to-value basis; principal-only mortgage inputs never charge PMI.

In a rental projection, property tax grows with the assumed appreciation
unless ``tax_growth`` is given explicitly; the remainder of operating
expenses grows with ``expense_growth``.

The mortgage model is fixed-rate only: ARM and interest-only loans are not
modeled, and this skill should say so rather than approximate one with a
fixed-rate loan.
"""

from __future__ import annotations

import json
import sys

_ACTIONS = ("affordability", "mortgage", "refinance", "reit", "rent_vs_buy", "rental")


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _num(
    params: dict, field: str, default: float | None = None, required: bool = False
) -> float | None:
    v = params.get(field)
    if v is None:
        if required:
            raise ValueError(f"{field} is required")
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    try:
        return float(v)
    except ValueError as exc:
        raise TypeError(f"{field} must be numeric") from exc


def _rate(
    params: dict, field: str, default: float | None = None, required: bool = False
) -> float | None:
    v = _num(params, field, default, required)
    if v is not None and not 0 <= v < 1:
        raise ValueError(f"{field} must be between 0 and 1 (a decimal such as 0.06)")
    return v


def payment(principal: float, annual_rate: float, months: int) -> float:
    if months <= 0:
        raise ValueError("term must be positive")
    r = annual_rate / 12
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** (-months))


def amortize(
    principal: float,
    annual_rate: float,
    pay: float,
    max_months: int = 1200,
    final_month: int | None = None,
    pmi_monthly: float = 0.0,
    pmi_threshold: float | None = None,
) -> tuple[int, float, list[dict]]:
    """(months to payoff, total interest, yearly schedule) paying ``pay`` per month.

    ``final_month`` is the scheduled term: any residual cents left by the
    rounded payment are folded into that last payment, as lenders do.

    ``pmi_monthly``/``pmi_threshold`` (optional) add a per-year ``pmi`` figure
    to each schedule row: ``pmi_monthly`` is charged for a given month only
    while that month's starting balance exceeds ``pmi_threshold``; once the
    balance crosses to or below it, PMI stops for good (no repricing). The
    loan amortization itself (interest/principal/balance) is unaffected by
    these parameters -- PMI is not part of the loan payment.
    """
    r = annual_rate / 12
    balance, total_interest, month = principal, 0.0, 0
    years: list[dict] = []
    y_int = y_pri = y_pmi = 0.0
    while balance > 1e-6 and month < max_months:
        month += 1
        interest = balance * r
        principal_paid = (
            balance
            if final_month is not None and month >= final_month
            else min(pay - interest, balance)
        )
        if principal_paid <= 0:
            raise ValueError("payment does not cover interest; the loan never amortizes")
        if pmi_monthly and pmi_threshold is not None and balance > pmi_threshold:
            y_pmi += pmi_monthly
        balance -= principal_paid
        total_interest += interest
        y_int += interest
        y_pri += principal_paid
        if month % 12 == 0 or balance <= 1e-6:
            years.append(
                {
                    "year": (month + 11) // 12,
                    "interest": _r2(y_int),
                    "principal": _r2(y_pri),
                    "balance": _r2(max(balance, 0.0)),
                    "pmi": _r2(y_pmi),
                }
            )
            y_int = y_pri = y_pmi = 0.0
    return month, total_interest, years


def _balance_after(principal: float, annual_rate: float, pay: float, months: int) -> float:
    r = annual_rate / 12
    if r == 0:
        return max(principal - pay * months, 0.0)
    return max(principal * (1 + r) ** months - pay * (((1 + r) ** months - 1) / r), 0.0)


# --- mortgage -------------------------------------------------------------------------


def _mortgage(p: dict) -> dict:
    principal = _num(p, "principal")
    price = _num(p, "price")
    down = _num(p, "down_payment", 0.0)
    if principal is None:
        if price is None:
            raise ValueError("principal or price is required")
        principal = price - down
    if principal <= 0:
        raise ValueError("principal must be positive")
    rate = _rate(p, "rate", required=True)
    years = _num(p, "years", required=True)
    months = int(round(years * 12))
    pay = round(payment(principal, rate, months), 2)
    # home_value anchors the 80% LTV threshold and requires price: without it
    # there is no basis for down_payment_pct, so PMI never applies (a
    # principal-only input never charges PMI, matching down_payment_pct's
    # pre-existing null in that case).
    down_pct = (down / price) if price else None
    pmi_rate = _rate(p, "pmi_rate", 0.0)
    pmi_applies = down_pct is not None and down_pct < 0.2 and pmi_rate
    pmi_monthly = round(principal * pmi_rate / 12, 2) if pmi_applies else 0.0
    pmi_threshold = 0.8 * price if pmi_applies else None
    n, total_interest, schedule = amortize(
        principal,
        rate,
        pay,
        final_month=months,
        pmi_monthly=pmi_monthly,
        pmi_threshold=pmi_threshold,
    )
    pmi_total = _r2(sum(row["pmi"] for row in schedule))
    pmi_off_year = None
    if pmi_monthly and pmi_threshold is not None:
        for row in schedule:
            if row["balance"] <= pmi_threshold + 1e-6:
                pmi_off_year = row["year"]
                break
    tax_monthly = (price or principal) * _rate(p, "property_tax_rate", 0.0) / 12
    ins_monthly = _num(p, "insurance_annual", 0.0) / 12
    hoa = _num(p, "hoa_monthly", 0.0)
    out = {
        "principal": _r2(principal),
        "rate": rate,
        "months": n,
        "payment": _r2(pay),
        "total_interest": _r2(total_interest),
        "total_paid": _r2(principal + total_interest),
        "down_payment_pct": _r4(down_pct),
        "pmi_monthly": _r2(pmi_monthly),
        "pmi_total": pmi_total,
        "pmi_off_year": pmi_off_year,
        "tax_monthly": _r2(tax_monthly),
        "insurance_monthly": _r2(ins_monthly),
        "hoa_monthly": _r2(hoa),
        "piti": _r2(pay + tax_monthly + ins_monthly + hoa + pmi_monthly),
        "schedule": schedule,
        "with_extra": None,
    }
    extra = _num(p, "extra_payment", 0.0)
    if extra and extra > 0:
        n2, int2, _ = amortize(principal, rate, pay + extra)
        out["with_extra"] = {
            "extra_payment": _r2(extra),
            "months": n2,
            "total_interest": _r2(int2),
            "months_saved": n - n2,
            "interest_saved": _r2(total_interest - int2),
        }
    return out


# --- refinance ------------------------------------------------------------------------


def _refinance(p: dict) -> dict:
    balance = _num(p, "balance", required=True)
    cur_rate = _rate(p, "current_rate", required=True)
    remaining = int(_num(p, "remaining_months", required=True))
    new_rate = _rate(p, "new_rate", required=True)
    new_months = int(round(_num(p, "new_years", required=True) * 12))
    closing = _num(p, "closing_costs", 0.0)
    cur_pay = round(payment(balance, cur_rate, remaining), 2)
    new_pay = round(payment(balance, new_rate, new_months), 2)
    savings = cur_pay - new_pay
    cur_int = cur_pay * remaining - balance
    new_int = new_pay * new_months - balance
    at_cur = amortize(balance, new_rate, cur_pay) if cur_pay > balance * new_rate / 12 else None
    horizon = max(remaining, new_months)
    savings_path, cum = [], -closing
    for m in range(1, horizon + 1):
        cum += (cur_pay if m <= remaining else 0.0) - (new_pay if m <= new_months else 0.0)
        if m % 12 == 0 or m == horizon:
            savings_path.append({"year": (m + 11) // 12, "cumulative_savings": _r2(cum)})
    return {
        "balance": _r2(balance),
        "current_payment": _r2(cur_pay),
        "new_payment": _r2(new_pay),
        "monthly_savings": _r2(savings),
        "breakeven_months": round(closing / savings, 1) if savings > 0 else None,
        "closing_costs": _r2(closing),
        "current_remaining_interest": _r2(cur_int),
        "new_total_interest": _r2(new_int),
        "lifetime_delta": _r2(cur_int - new_int - closing),
        "term_extension_months": new_months - remaining,
        "new_loan_at_current_payment": {"months": at_cur[0], "interest": _r2(at_cur[1])}
        if at_cur
        else None,
        "savings_path": savings_path,
    }


# --- rent vs buy ----------------------------------------------------------------------


def _rent_vs_buy(p: dict) -> dict:
    price = _num(p, "price", required=True)
    down = _num(p, "down_payment", required=True)
    rate = _rate(p, "rate", required=True)
    months = int(round(_num(p, "years", 30) * 12))
    horizon = int(_num(p, "horizon_years", 7))
    tax_rate = _rate(p, "property_tax_rate", 0.0)
    maint = _rate(p, "maintenance_rate", 0.0)
    ins = _num(p, "insurance_annual", 0.0)
    hoa = _num(p, "hoa_monthly", 0.0) * 12
    buy_close = _rate(p, "buy_closing_rate", 0.0)
    sell_close = _rate(p, "sell_closing_rate", 0.0)
    app = _rate(p, "appreciation", 0.0)
    rent = _num(p, "rent", required=True) * 12
    rent_growth = _rate(p, "rent_growth", 0.0)
    inv = _rate(p, "investment_return", 0.0)
    if horizon < 1:
        raise ValueError("horizon_years must be at least 1")
    principal = price - down
    pay = round(payment(principal, rate, months), 2) if principal > 0 else 0.0
    upfront = down + price * buy_close
    portfolio = upfront
    buy_cum, rent_cum = upfront, 0.0
    rows = []
    breakeven = None
    for y in range(1, horizon + 1):
        value = price * (1 + app) ** y
        owner_cost = pay * 12 + value * tax_rate + value * maint + ins + hoa
        rent_y = rent * (1 + rent_growth) ** (y - 1)
        buy_cum += owner_cost
        rent_cum += rent_y
        portfolio = portfolio * (1 + inv) + (owner_cost - rent_y)
        balance = (
            _balance_after(principal, rate, pay, min(12 * y, months)) if principal > 0 else 0.0
        )
        equity = value - balance
        buy_nw = equity - value * sell_close
        adv = buy_nw - portfolio
        if breakeven is None and adv >= 0:
            breakeven = y
        rows.append(
            {
                "year": y,
                "buy_cost_cumulative": _r2(buy_cum),
                "rent_cost_cumulative": _r2(rent_cum),
                "home_equity": _r2(equity),
                "renter_portfolio": _r2(portfolio),
                "buy_net_worth": _r2(buy_nw),
                "rent_net_worth": _r2(portfolio),
                "advantage_buy": _r2(adv),
            }
        )
    year1 = pay * 12 + price * (1 + app) * (tax_rate + maint) + ins + hoa
    return {
        "horizon_years": horizon,
        "by_year": rows,
        "breakeven_year": breakeven,
        "monthly_cost_year1": {"buy": _r2(year1 / 12), "rent": _r2(rent / 12)},
        "upfront_cash": _r2(upfront),
        "payment": _r2(pay),
        "assumptions": {
            "appreciation": app,
            "rent_growth": rent_growth,
            "investment_return": inv,
            "property_tax_rate": tax_rate,
            "maintenance_rate": maint,
            "buy_closing_rate": buy_close,
            "sell_closing_rate": sell_close,
        },
    }


# --- rental ---------------------------------------------------------------------------


def _irr(flows: list[float]) -> float | None:
    def npv(r: float) -> float:
        return sum(cf / (1 + r) ** i for i, cf in enumerate(flows))

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _rental_projection(
    invested: float,
    egi: float,
    tax_annual: float,
    opex_rest: float,
    debt: float,
    rg: float,
    tax_growth: float,
    eg: float,
    app: float,
    sell_close: float,
    hold: int,
    price: float,
    principal: float,
    rate: float,
    pay: float,
    months: int,
) -> tuple[dict, list[float]]:
    """One hold-period projection; returns (projection dict, pre-sale annual cash flows).

    Property tax grows with ``tax_growth``; the rest of opex grows with ``eg``.
    """
    flows = [-invested]
    operating: list[float] = []
    for y in range(1, hold + 1):
        tax_y = tax_annual * (1 + tax_growth) ** (y - 1)
        rest_y = opex_rest * (1 + eg) ** (y - 1)
        cf = egi * (1 + rg) ** (y - 1) - (tax_y + rest_y) - debt
        operating.append(cf)
        flows.append(cf)
    sale = price * (1 + app) ** hold
    bal = _balance_after(principal, rate, pay, min(12 * hold, months)) if principal > 0 else 0.0
    flows[-1] += sale * (1 - sell_close) - bal
    irr = _irr(flows)
    proj = {
        "hold_years": hold,
        "cash_flows": [_r2(f) for f in flows],
        "sale_price": _r2(sale),
        "loan_balance_at_sale": _r2(bal),
        "total_profit": _r2(sum(flows)),
        "equity_multiple": _r4(sum(flows[1:]) / invested) if invested else None,
        "irr": _r4(irr),
    }
    return proj, operating


def _scenario_grid(base: float) -> list[float]:
    lo = round(max(base - 0.02, -0.10), 6)
    hi = round(max(base + 0.02, -0.10), 6)
    return sorted({lo, round(base, 6), hi})


def _rental(p: dict) -> dict:
    price = _num(p, "price", required=True)
    down = _num(p, "down_payment", required=True)
    rate = _rate(p, "rate", 0.0)
    months = int(round(_num(p, "years", 30) * 12))
    closing = _num(p, "closing_costs", 0.0)
    rent = _num(p, "rent", required=True) * 12
    vacancy = _rate(p, "vacancy_rate", 0.0)
    egi = rent * (1 - vacancy)
    tax_annual = _num(p, "property_tax_annual", 0.0)
    capex_rate = _rate(p, "capex_reserve_rate", 0.0)
    leasing_rate = _rate(p, "leasing_rate", 0.0)
    opex = (
        tax_annual
        + _num(p, "insurance_annual", 0.0)
        + egi * _rate(p, "maintenance_rate", 0.0)
        + egi * _rate(p, "management_rate", 0.0)
        + _num(p, "hoa_monthly", 0.0) * 12
        + _num(p, "utilities_annual", 0.0)
        + _num(p, "other_annual", 0.0)
        + egi * capex_rate
        + egi * leasing_rate
    )
    noi = egi - opex
    principal = price - down
    pay = round(payment(principal, rate, months), 2) if principal > 0 else 0.0
    debt = pay * 12
    cash_flow = noi - debt
    invested = down + closing
    out = {
        "price": _r2(price),
        "loan": _r2(principal),
        "gross_rent": _r2(rent),
        "effective_gross_income": _r2(egi),
        "operating_expenses": _r2(opex),
        "noi": _r2(noi),
        "cap_rate": _r4(noi / price),
        "debt_service": _r2(debt),
        "dscr": _r4(noi / debt) if debt else None,
        "cash_flow": _r2(cash_flow),
        "cash_invested": _r2(invested),
        "cash_on_cash": _r4(cash_flow / invested) if invested else None,
        "grm": _r4(price / rent) if rent else None,
        "rent_to_price": _r4(rent / 12 / price),
        "one_percent_rule": rent / 12 / price >= 0.01,
        "break_even_occupancy": _r4((opex + debt) / rent) if rent else None,
        "expense_ratio": _r4(opex / egi) if egi else None,
        "projection": None,
    }
    hold_raw = p.get("hold_years")
    scenarios_in = p.get("scenarios")
    if scenarios_in and not hold_raw:
        raise ValueError("scenarios requires hold_years")
    if hold_raw:
        hold = int(_num(p, "hold_years"))
        rg = _rate(p, "rent_growth", 0.0)
        eg = _rate(p, "expense_growth", 0.0)
        app = _rate(p, "appreciation", 0.0)
        sell_close = _rate(p, "sell_closing_rate", 0.0)
        tax_growth_given = p.get("tax_growth") is not None
        tax_growth = _rate(p, "tax_growth", app)
        opex_rest = opex - tax_annual
        proj, _operating = _rental_projection(
            invested,
            egi,
            tax_annual,
            opex_rest,
            debt,
            rg,
            tax_growth,
            eg,
            app,
            sell_close,
            hold,
            price,
            principal,
            rate,
            pay,
            months,
        )
        out["projection"] = proj
        if scenarios_in:
            if scenarios_in is True:
                app_grid = _scenario_grid(app)
                rg_grid = _scenario_grid(rg)
            elif isinstance(scenarios_in, dict):
                app_grid = [float(v) for v in scenarios_in.get("appreciation", [app])]
                rg_grid = [float(v) for v in scenarios_in.get("rent_growth", [rg])]
            else:
                raise TypeError("scenarios must be true or an object with appreciation/rent_growth")
            rows = []
            for a in app_grid:
                for r in rg_grid:
                    tg = tax_growth if tax_growth_given else a
                    s_proj, s_operating = _rental_projection(
                        invested,
                        egi,
                        tax_annual,
                        opex_rest,
                        debt,
                        r,
                        tg,
                        eg,
                        a,
                        sell_close,
                        hold,
                        price,
                        principal,
                        rate,
                        pay,
                        months,
                    )
                    coc = (sum(s_operating) / hold / invested) if invested else None
                    rows.append(
                        {
                            "appreciation": _r4(a),
                            "rent_growth": _r4(r),
                            "irr": s_proj["irr"],
                            "total_profit": s_proj["total_profit"],
                            "cash_on_cash": _r4(coc),
                        }
                    )
            out["scenarios"] = rows
    return out


# --- affordability --------------------------------------------------------------------


def _affordability(p: dict) -> dict:
    income = _num(p, "annual_income", required=True) / 12
    debts = _num(p, "monthly_debts", 0.0)
    down = _num(p, "down_payment", 0.0)
    rate = _rate(p, "rate", required=True)
    months = int(round(_num(p, "years", 30) * 12))
    tax_rate = _rate(p, "property_tax_rate", 0.0)
    ins_m = _num(p, "insurance_annual", 0.0) / 12
    front, back = _rate(p, "front_end", 0.28), _rate(p, "back_end", 0.36)
    front_cap, back_cap = income * front, income * back - debts
    cap = min(front_cap, back_cap)
    binding = (
        f"front-end {int(front * 100)}%"
        if front_cap <= back_cap
        else f"back-end {int(back * 100)}%"
    )
    factor = payment(1.0, rate, months)
    # cap = loan*factor + (loan + down)*tax/12 + ins
    loan = max((cap - ins_m - down * tax_rate / 12) / (factor + tax_rate / 12), 0.0)
    price = loan + down
    piti = loan * factor + price * tax_rate / 12 + ins_m
    return {
        "max_housing_payment": _r2(cap),
        "binding_ratio": binding,
        "max_loan": _r2(loan),
        "max_price": _r2(price),
        "piti_at_max": _r2(piti),
        "front_end_cap": _r2(front_cap),
        "back_end_cap": _r2(back_cap),
    }


# --- REIT -----------------------------------------------------------------------------


def _reit(p: dict) -> dict:
    price = _num(p, "price", required=True)
    shares = _num(p, "shares", required=True)
    ffo = (
        _num(p, "net_income", required=True)
        + _num(p, "depreciation", 0.0)
        - _num(p, "gains_on_sale", 0.0)
    )
    affo = ffo - _num(p, "recurring_capex", 0.0)
    dps = _num(p, "dividend_per_share")
    nav = _num(p, "nav_per_share")
    ffo_ps, affo_ps = ffo / shares, affo / shares
    return {
        "ffo": _r2(ffo),
        "ffo_per_share": _r4(ffo_ps),
        "p_ffo": _r4(price / ffo_ps) if ffo_ps > 0 else None,
        "ffo_yield": _r4(ffo_ps / price),
        "affo": _r2(affo),
        "affo_per_share": _r4(affo_ps),
        "p_affo": _r4(price / affo_ps) if affo_ps > 0 else None,
        "dividend_yield": _r4(dps / price) if dps is not None else None,
        "ffo_payout": _r4(dps / ffo_ps) if dps is not None and ffo_ps > 0 else None,
        "affo_payout": _r4(dps / affo_ps) if dps is not None and affo_ps > 0 else None,
        "nav_premium": _r4(price / nav - 1) if nav else None,
    }


def run_realestate(params: dict) -> dict:
    """Dispatch on ``params['action']``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    action = params.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(_ACTIONS)}")
    return {
        "mortgage": _mortgage,
        "refinance": _refinance,
        "rent_vs_buy": _rent_vs_buy,
        "rental": _rental,
        "affordability": _affordability,
        "reit": _reit,
    }[action](params)


def main() -> None:
    """Read JSON params from stdin, write the result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_realestate(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
