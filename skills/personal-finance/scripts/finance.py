"""Personal-finance calculators: loan/debt amortization, multi-debt payoff
ordering (avalanche vs snowball), and fee-adjusted compound-growth
projections.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python finance.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).
Rates are decimals (0.06 = 6%). The ``action`` field selects the calculator:

``amortize``::

    {"action": "amortize", "balance": 20000, "apr": 0.07,
     "months": 60 | "payment": 450, "extra_payment": 100 (monthly, optional)}
    -> {payment,                       # when months given
        payoff_months,                 # when payment given
        total_interest,
        schedule: [{year, interest, principal, balance}],
        with_extra: {months, total_interest, interest_saved, months_saved}
            | null,                    # when extra_payment given
        apr_vs_apy: {apy_monthly, apy_daily}}

Exactly one of ``months``/``payment`` is required: both raises ValueError,
neither raises ValueError. With ``months`` the payment is solved from the
standard annuity formula and rounded to cents before amortizing (as
lenders do, same idiom as realestate.py); with ``payment`` the payoff term
is solved by amortizing that fixed payment until the balance clears.
``apr_vs_apy`` converts the nominal ``apr`` to its monthly- and
daily-compounding effective annual yields: ``apy_monthly = (1+apr/12)^12-1``,
``apy_daily = (1+apr/365)^365-1``, both 4 dp.

``debt``::

    {"action": "debt", "debts": [{"name": "Card A", "balance": 4000,
     "apr": 0.24, "min_payment": 120}, ...], "extra_monthly": 200 (optional),
     "as_of": "2026-09-01" (optional, default today)}
    -> {avalanche: {order: [names...], months, total_interest,
                    payoff_dates: {name: "YYYY-MM-01", ...}},
        snowball: {order, months, total_interest, payoff_dates},
        interest_saved_avalanche_vs_snowball, assumptions}

Avalanche orders debts by APR descending (ties broken by name); snowball
orders by balance ascending (ties broken by name). Every debt gets its
fixed ``min_payment`` every month; ``extra_monthly`` (plus the freed
minimum payments of any already-paid-off debts) is piled onto whichever
debt is first in that method's order that still has a balance -- the
standard "debt snowball rolling" simulation. ``min_payment`` is a fixed
dollar amount for the life of the simulation, not a percent-of-balance
calculation -- a documented simplification (real card minimums usually
fall as the balance falls, so this overstates months-to-payoff somewhat).
``payoff_dates`` approximates each month as 30 days from ``as_of`` (or
today) and reports the first of that calendar month. Money 2 dp.

``compound``::

    {"action": "compound", "start_balance": 10000 (default 0),
     "monthly_contribution": 500 (default 0), "annual_return": 0.07,
     "fee_rate": 0.005 (optional, annual, default 0),
     "contribution_growth": 0.02 (optional, annual, default 0), "years": 20}
    -> {years, final_balance, total_contributions, growth,
        schedule: [{year, balance, contributions_to_date}]}

Fees are applied multiplicatively to the annual return before compounding:
``net_annual = (1+annual_return)*(1-fee_rate)-1``, rounded to 4 dp. That
net annual (effective) rate is converted to its equivalent monthly rate,
``monthly_rate = (1+net_annual)^(1/12)-1``, and both the running balance
and the (optionally growing) monthly contribution compound monthly, with
each month's contribution added at month-end (an ordinary-annuity
convention, matching the amortization formula used elsewhere in this
skill set). ``contribution_growth`` compounds annually: each of the 12
months in year N uses the same contribution amount, then it grows by
``contribution_growth`` before year N+1 starts. Money 2 dp.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

_ACTIONS = ("amortize", "debt", "compound")

_DAYS_PER_MONTH = 30
_MAX_MONTHS = 1200


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


def _amortize_schedule(
    balance: float,
    annual_rate: float,
    pay: float,
    max_months: int = _MAX_MONTHS,
    final_month: int | None = None,
) -> tuple[int, float, list[dict]]:
    """(months to payoff, total interest, yearly schedule) paying ``pay`` per month.

    ``final_month`` is the scheduled term: any residual cents left by the
    rounded payment are folded into that last payment, as lenders do.
    """
    r = annual_rate / 12
    bal, total_interest, month = balance, 0.0, 0
    years: list[dict] = []
    y_int = y_pri = 0.0
    while bal > 1e-6 and month < max_months:
        month += 1
        interest = bal * r
        principal_paid = (
            bal if final_month is not None and month >= final_month else min(pay - interest, bal)
        )
        if principal_paid <= 0:
            raise ValueError("payment does not cover interest; the loan never amortizes")
        bal -= principal_paid
        total_interest += interest
        y_int += interest
        y_pri += principal_paid
        if month % 12 == 0 or bal <= 1e-6:
            years.append(
                {
                    "year": (month + 11) // 12,
                    "interest": _r2(y_int),
                    "principal": _r2(y_pri),
                    "balance": _r2(max(bal, 0.0)),
                }
            )
            y_int = y_pri = 0.0
    return month, total_interest, years


# --- amortize ---------------------------------------------------------------


def _amortize(p: dict) -> dict:
    balance = _num(p, "balance", required=True)
    if balance <= 0:
        raise ValueError("balance must be positive")
    apr = _rate(p, "apr", required=True)
    months_in = p.get("months")
    payment_in = p.get("payment")
    if months_in is not None and payment_in is not None:
        raise ValueError("provide exactly one of months or payment, not both")
    if months_in is None and payment_in is None:
        raise ValueError("provide exactly one of months or payment")
    extra = _num(p, "extra_payment", 0.0)

    out: dict = {}
    if months_in is not None:
        months = int(round(_num(p, "months")))
        if months <= 0:
            raise ValueError("months must be positive")
        pay = round(payment(balance, apr, months), 2)
        base_months, total_interest, schedule = _amortize_schedule(
            balance, apr, pay, final_month=months
        )
        out["payment"] = _r2(pay)
    else:
        pay = round(_num(p, "payment"), 2)
        base_months, total_interest, schedule = _amortize_schedule(balance, apr, pay)
        out["payoff_months"] = base_months

    out["total_interest"] = _r2(total_interest)
    out["schedule"] = schedule
    out["with_extra"] = None
    if extra and extra > 0:
        months2, interest2, _schedule2 = _amortize_schedule(balance, apr, pay + extra)
        out["with_extra"] = {
            "months": months2,
            "total_interest": _r2(interest2),
            "interest_saved": _r2(total_interest - interest2),
            "months_saved": base_months - months2,
        }
    out["apr_vs_apy"] = {
        "apy_monthly": _r4((1 + apr / 12) ** 12 - 1),
        "apy_daily": _r4((1 + apr / 365) ** 365 - 1),
    }
    return out


# --- debt --------------------------------------------------------------------


def _payoff_date(base: date, months: int) -> str:
    d = base + timedelta(days=_DAYS_PER_MONTH * months)
    return f"{d.year:04d}-{d.month:02d}-01"


def _simulate_debts(
    debts: dict[str, dict], order: list[str], extra_monthly: float
) -> tuple[int, float, dict[str, int]]:
    """Simulate paying ``order`` in priority order; returns (months, total
    interest, {name: month paid off}).

    Every debt gets its own fixed ``min_payment`` each month it is still
    open; ``extra_monthly`` plus the minimums freed by already-paid-off
    debts is piled onto the first still-open debt in ``order``.
    """
    balance = {n: debts[n]["balance"] for n in order}
    total_interest = 0.0
    payoff_month: dict[str, int] = {}
    month = 0
    while any(balance[n] > 1e-6 for n in order) and month < _MAX_MONTHS:
        month += 1
        active = [n for n in order if balance[n] > 1e-6]
        freed = extra_monthly + sum(debts[n]["min_payment"] for n in order if balance[n] <= 1e-6)
        target = active[0]
        for n in active:
            interest = balance[n] * debts[n]["apr"] / 12
            total_interest += interest
            pay_amt = debts[n]["min_payment"] + freed if n == target else debts[n]["min_payment"]
            principal_paid = pay_amt - interest
            if principal_paid <= 0:
                raise ValueError(
                    f"min_payment for {n!r} does not cover interest; the debt never amortizes"
                )
            principal_paid = min(principal_paid, balance[n])
            balance[n] -= principal_paid
            if balance[n] <= 1e-6 and n not in payoff_month:
                payoff_month[n] = month
    return month, total_interest, payoff_month


def _debt(p: dict) -> dict:
    debts_in = p.get("debts")
    if not isinstance(debts_in, list) or not debts_in:
        raise ValueError("debts must be a non-empty list")
    debts: dict[str, dict] = {}
    for entry in debts_in:
        if not isinstance(entry, dict):
            raise TypeError("each debt must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("each debt requires a name")
        if name in debts:
            raise ValueError(f"duplicate debt name: {name!r}")
        balance = _num(entry, "balance", required=True)
        apr = _rate(entry, "apr", required=True)
        min_payment = _num(entry, "min_payment", required=True)
        if balance <= 0:
            raise ValueError(f"{name}: balance must be positive")
        if min_payment <= 0:
            raise ValueError(f"{name}: min_payment must be positive")
        debts[name] = {"balance": balance, "apr": apr, "min_payment": min_payment}

    extra_monthly = _num(p, "extra_monthly", 0.0)
    as_of_raw = p.get("as_of")
    if as_of_raw is not None:
        try:
            base = date.fromisoformat(str(as_of_raw))
        except ValueError as exc:
            raise ValueError("as_of must be YYYY-MM-DD") from exc
    else:
        base = date.today()

    names = list(debts.keys())
    avalanche_order = sorted(names, key=lambda n: (-debts[n]["apr"], n))
    snowball_order = sorted(names, key=lambda n: (debts[n]["balance"], n))

    def _run(order: list[str]) -> dict:
        months, total_interest, payoff_month = _simulate_debts(debts, order, extra_monthly)
        return {
            "order": order,
            "months": months,
            "total_interest": _r2(total_interest),
            "payoff_dates": {n: _payoff_date(base, payoff_month[n]) for n in order},
        }

    avalanche = _run(avalanche_order)
    snowball = _run(snowball_order)
    return {
        "avalanche": avalanche,
        "snowball": snowball,
        "interest_saved_avalanche_vs_snowball": _r2(
            snowball["total_interest"] - avalanche["total_interest"]
        ),
        "assumptions": {
            "min_payments": "fixed dollar amounts for the life of the simulation, "
            "not percent-of-balance",
            "extra_monthly": _r2(extra_monthly),
            "as_of": base.isoformat(),
            "month_length_days": _DAYS_PER_MONTH,
        },
    }


# --- compound ----------------------------------------------------------------


def _compound(p: dict) -> dict:
    start = _num(p, "start_balance", 0.0)
    monthly_contribution = _num(p, "monthly_contribution", 0.0)
    annual_return = _rate(p, "annual_return", required=True)
    fee_rate = _rate(p, "fee_rate", 0.0)
    contribution_growth = _rate(p, "contribution_growth", 0.0)
    years = _num(p, "years", required=True)
    years_int = int(round(years))
    if years_int <= 0:
        raise ValueError("years must be positive")

    net_annual = round((1 + annual_return) * (1 - fee_rate) - 1, 4)
    monthly_rate = (1 + net_annual) ** (1 / 12) - 1

    balance = start
    total_contributions = 0.0
    contribution = monthly_contribution
    schedule: list[dict] = []
    for year in range(1, years_int + 1):
        for _month in range(12):
            balance *= 1 + monthly_rate
            balance += contribution
            total_contributions += contribution
        schedule.append(
            {
                "year": year,
                "balance": _r2(balance),
                "contributions_to_date": _r2(total_contributions),
            }
        )
        contribution *= 1 + contribution_growth

    growth = balance - start - total_contributions
    return {
        "years": years_int,
        "final_balance": _r2(balance),
        "total_contributions": _r2(total_contributions),
        "growth": _r2(growth),
        "schedule": schedule,
    }


def run_finance(params: dict) -> dict:
    """Dispatch on ``params['action']``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    action = params.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(_ACTIONS)}")
    return {"amortize": _amortize, "debt": _debt, "compound": _compound}[action](params)


def main() -> None:
    """Read JSON params from stdin, write the result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_finance(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
