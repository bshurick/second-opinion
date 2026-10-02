"""Retirement and goal planning: savings-goal arithmetic, a deterministic
accumulation-and-drawdown projection with a seeded Monte Carlo overlay, a
sustainable-withdrawal-rate table, and a Social Security claiming comparison.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python retirement.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).
Rates are decimals. The ``action`` field selects the calculation:

``goal``::

    {"action": "goal", "target": 1000000, "current": 100000, "return": 0.07,
     "years": 30 | "monthly_contribution": 500}
    -> {future_value_of_current, remaining, monthly_contribution_needed,
        annual_contribution_needed, already_funded}          # with years
    -> {months_to_reach, years_to_reach}                     # with monthly_contribution

``project``::

    {"action": "project", "age": 40, "retirement_age": 65, "end_age": 95,
     "savings": 200000, "annual_contribution": 20000, "contribution_growth": 0.02,
     "return": 0.06, "volatility": 0.12, "inflation": 0.025, "fees": 0.002,
     "spending": 80000 (today's dollars, per year), "other_income": 24000,
     "other_income_start_age": 67, "withdrawal_rate": 0.04,
     "ret_return": 0.04, "ret_vol": 0.10 (optional two-block glide path),
     "guardrails": {"cut_pct": 0.10, "trigger_pct": 0.20} (optional),
     "simulations": 2000, "seed": 42}
    -> {years_to_retirement, years_in_retirement,
        deterministic: {net_return, balance_at_retirement, balance_at_retirement_real,
                        spending_at_retirement, required_nest_egg, gap,
                        extra_annual_contribution_needed, depletes_at_age, ending_balance,
                        path: [{age, balance, flow, real_balance}],
                        guardrail_path: [{age, spending_after_cut}]  # with guardrails},
        monte_carlo: {simulations, success_probability, balance_at_retirement: {p10,p50,p90},
                      ending_balance: {p10,p50,p90}, median_depletion_age,
                      worst_decile_years_funded,
                      percentile_path: [{age, p10, p25, p50, p75, p90}],
                      guardrails: {constant_success_probability,
                                   guardrail_success_probability,
                                   success_probability_gain,
                                   median_fraction_of_years_cut}}  # with guardrails}

``ss_claim``::

    {"action": "ss_claim", "benefit_at_fra": 30000 (annual benefit at FRA,
     today's dollars), "fra_age": 67, "claim_ages": [62, 67, 70],
     "savings": 1000000, "retirement_age": 65, "end_age": 95, "return": 0.05,
     "volatility": 0.12, "inflation": 0.025, "fees": 0.0, "spending": 60000,
     "simulations": 2000, "seed": 42}
    -> {claiming: [{age, factor, first_year_benefit, success_probability,
                    median_ending_balance, median_depletion_age}],
        break_even: {"62_vs_67": age|null, ...}, inputs: {...}}

``withdrawal``::

    {"action": "withdrawal", "nest_egg": 1000000, "years": 30, "return": 0.05,
     "volatility": 0.12, "inflation": 0.025, "spending": 60000 (optional),
     "simulations": 2000, "seed": 42}
    -> {table: [{rate, annual_spending, success_probability, median_ending_balance,
                 worst_decile_years_funded, deterministic_years}],
        deterministic_years_at_4pct, requested: {rate, spending, success_probability,
        deterministic_years} | null}

Method: monthly compounding for the goal action; annual steps elsewhere.
Contributions grow at contribution_growth; spending and other income are
indexed to inflation from today; withdrawals are spending minus other
income once it starts. The net return is return minus fees. The Monte
Carlo draws lognormal annual returns (mean net return, given volatility)
from a seeded generator so runs are reproducible, and the withdrawal table
evaluates every rate on the same return paths so results are comparable.
required_nest_egg = (spending - other_income) at retirement / withdrawal_rate
(the 4% rule inverted). Percentiles are nearest-rank. Money 2 dp. This is
a model with stated assumptions, not a forecast. percentile_path holds, for
every age from today to end_age, the percentiles of the simulated balances
at that age taken independently (a fan chart's bands, not five single
paths); its p50 at retirement_age equals balance_at_retirement.p50.

ret_return/ret_vol is a two-block glide path, not a year-by-year schedule:
accumulation years compound at return/volatility, retirement years at
ret_return/ret_vol (a missing block keeps the other pair). With guardrails
the simulations run twice on the same return paths — constant spending and
guardrail spending, where the withdrawal is cut by cut_pct in any year the
balance sits more than trigger_pct below its running maximum since
retirement and restores when it recovers (no spending increases are
modeled) — and the guardrails block reports the success-probability gain.

ss_claim: claim ages are clamped to [62, 70]; the factor is 1 - 5/9% x
months early (first 36) - 5/12% x months beyond, or 1 + 8% x years past FRA
(4 dp). Benefits are modeled as inflation-indexed annuity income on the
portfolio's return paths — not an SS-specific model: each claim age runs
the projection from retirement_age with the benefit as other income, every
scenario on the same seeded return paths so they are comparable. break_even
is the age at which the later claim's cumulative real benefits first exceed
the earlier claim's (null when that never happens before end_age).
"""

from __future__ import annotations

import json
import math
import random
import sys

_ACTIONS = ("goal", "project", "ss_claim", "withdrawal")
_TABLE_RATES = (0.03, 0.035, 0.04, 0.045, 0.05, 0.06)


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _num(p: dict, field: str, default: float | None = None, required: bool = False) -> float | None:
    v = p.get(field)
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
    p: dict, field: str, default: float | None = None, required: bool = False
) -> float | None:
    v = _num(p, field, default, required)
    if v is not None and not -0.5 <= v < 1:
        raise ValueError(f"rates must be decimals (0.06 for 6%); {field} is {v}")
    return v


def _pct(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(max(int(round(q * (len(sorted_values) - 1))), 0), len(sorted_values) - 1)
    return sorted_values[idx]


# --- goal ------------------------------------------------------------------------------


def _goal(p: dict) -> dict:
    target = _num(p, "target", required=True)
    current = _num(p, "current", 0.0)
    r = _rate(p, "return", required=True)
    i = r / 12
    monthly = _num(p, "monthly_contribution")
    years = _num(p, "years")
    if years is None and monthly is None:
        raise ValueError("years or monthly_contribution is required")
    if years is not None:
        n = int(round(years * 12))
        growth = (1 + i) ** n
        fv = current * growth
        remaining = target - fv
        if remaining <= 0:
            need = 0.0
        elif i == 0:
            need = remaining / n
        else:
            need = remaining * i / (growth - 1)
        return {
            "target": target,
            "current": current,
            "years": years,
            "return": r,
            "future_value_of_current": _r2(fv),
            "remaining": _r2(max(remaining, 0.0)),
            "monthly_contribution_needed": _r2(need),
            "annual_contribution_needed": _r2(need * 12),
            "already_funded": remaining <= 0,
        }
    if current >= target:
        return {
            "target": target,
            "current": current,
            "return": r,
            "monthly_contribution": monthly,
            "months_to_reach": 0,
            "years_to_reach": 0.0,
            "already_funded": True,
        }
    if i == 0:
        if monthly <= 0:
            raise ValueError("target can never be reached with no return and no contribution")
        months = (target - current) / monthly
    else:
        base = current + monthly / i
        if base <= 0:
            raise ValueError("target can never be reached with these contributions")
        ratio = (target + monthly / i) / base
        if ratio <= 1:
            raise ValueError("target can never be reached with these contributions")
        months = math.log(ratio) / math.log(1 + i)
    return {
        "target": target,
        "current": current,
        "return": r,
        "monthly_contribution": monthly,
        "months_to_reach": math.ceil(months),
        "years_to_reach": round(months / 12, 1),
        "already_funded": False,
    }


# --- projection ------------------------------------------------------------------------


def _simulate(p: dict, returns: list[float] | None) -> dict:
    """One path. ``returns`` is a per-year list (None -> constant net return).

    Guardrails (``cut_pct``/``trigger_pct`` present) cut that year's
    withdrawal by ``cut_pct`` whenever the balance sits more than
    ``trigger_pct`` below its running maximum since retirement.
    """
    age, ret_age, end_age = int(p["age"]), int(p["retirement_age"]), int(p["end_age"])
    net = p["net"]
    net_ret = p.get("net_ret")
    cut = p.get("cut_pct")
    trigger = p.get("trigger_pct")
    guardrails = cut is not None and trigger is not None
    balance = p["savings"]
    contribution = p["annual_contribution"]
    path = [{"age": age, "balance": balance, "flow": 0.0}]
    guardrail_path = [{"age": age, "spending_after_cut": 0.0}] if guardrails else None
    peak = None
    cuts = 0
    retirement_years = 0
    depletion = None
    balance_at_ret = None
    for k, a in enumerate(range(age, end_age)):
        if returns is not None:
            r = returns[k]
        elif net_ret is not None and a >= ret_age:
            r = net_ret
        else:
            r = net
        t = k + 1  # years from today at the end of this step
        if a < ret_age:
            flow = contribution
            contribution *= 1 + p["contribution_growth"]
            if guardrails:
                guardrail_path.append({"age": a + 1, "spending_after_cut": 0.0})
        else:
            spending = p["spending"] * (1 + p["inflation"]) ** t
            income = (
                p["other_income"] * (1 + p["inflation"]) ** t
                if a >= p["other_income_start_age"]
                else 0.0
            )
            withdrawal = max(spending - income, 0.0)
            spending_after = spending
            if guardrails:
                if peak is None:
                    peak = balance
                cut_active = balance < peak * (1 - trigger)
                if cut_active and withdrawal > 0:
                    withdrawal *= 1 - cut
                    spending_after = spending - (spending - income) * cut
                cuts += 1 if cut_active else 0
                retirement_years += 1
                guardrail_path.append({"age": a + 1, "spending_after_cut": spending_after})
            flow = -withdrawal
        balance = balance * (1 + r) + flow
        if balance <= 0:
            balance = 0.0
            if depletion is None and a >= ret_age:
                depletion = a + 1
        elif guardrails and a >= ret_age:
            peak = max(peak, balance)
        path.append({"age": a + 1, "balance": balance, "flow": flow})
        if a + 1 == ret_age:
            balance_at_ret = balance
    return {
        "path": path,
        "guardrail_path": guardrail_path,
        "fraction_cut": cuts / retirement_years if guardrails and retirement_years else 0.0,
        "balance_at_retirement": balance_at_ret if balance_at_ret is not None else balance,
        "ending": balance,
        "depletion": depletion,
    }


def _project(p: dict) -> dict:
    age = _num(p, "age", required=True)
    ret_age = _num(p, "retirement_age", required=True)
    end_age = _num(p, "end_age", required=True)
    if ret_age <= age:
        raise ValueError("retirement_age must be greater than age")
    if end_age <= ret_age:
        raise ValueError("end_age must be greater than retirement_age")
    cfg = {
        "age": age,
        "retirement_age": ret_age,
        "end_age": end_age,
        "savings": _num(p, "savings", 0.0),
        "annual_contribution": _num(p, "annual_contribution", 0.0),
        "contribution_growth": _rate(p, "contribution_growth", 0.0),
        "inflation": _rate(p, "inflation", 0.0),
        "spending": _num(p, "spending", 0.0),
        "other_income": _num(p, "other_income", 0.0),
        "other_income_start_age": _num(p, "other_income_start_age", ret_age),
    }
    ret = _rate(p, "return", required=True)
    fees = _rate(p, "fees", 0.0)
    vol = _rate(p, "volatility", 0.0)
    ret_return = _rate(p, "ret_return")
    ret_vol = _rate(p, "ret_vol")
    wr = _rate(p, "withdrawal_rate", 0.04)
    cfg["net"] = ret - fees
    glide = ret_return is not None or ret_vol is not None
    net_ret = (ret_return if ret_return is not None else ret) - fees
    vol_ret = ret_vol if ret_vol is not None else vol
    if glide:
        cfg["net_ret"] = net_ret
    guardrails_in = p.get("guardrails")
    cut = trigger = None
    if guardrails_in is not None:
        if not isinstance(guardrails_in, dict):
            raise ValueError("guardrails must be an object: {cut_pct, trigger_pct}")
        cut = _rate(guardrails_in, "cut_pct", required=True)
        trigger = _rate(guardrails_in, "trigger_pct", required=True)
    cfg_g = {**cfg, "cut_pct": cut, "trigger_pct": trigger} if cut is not None else None
    n_pre = int(ret_age - age)
    n_ret = int(end_age - ret_age)
    sims = int(_num(p, "simulations", 2000))
    seed = int(_num(p, "seed", 42))

    det = _simulate(cfg, None)
    if cfg_g is not None:
        det_g = _simulate(cfg_g, None)
    infl_factor = (1 + cfg["inflation"]) ** n_pre
    spending_ret = cfg["spending"] * infl_factor
    required = (
        max(cfg["spending"] - cfg["other_income"], 0.0) * infl_factor / wr if wr > 0 else None
    )
    # difference of the REPORTED (rounded) figures so the table adds up to the cent
    balance_ret = round(det["balance_at_retirement"], 2)
    gap = round(required, 2) - balance_ret if required is not None else None
    net = cfg["net"]
    if gap is not None and gap > 0 and n_pre > 0:
        extra = gap * net / ((1 + net) ** n_pre - 1) if net != 0 else gap / n_pre
    else:
        extra = 0.0
    path = [
        {
            "age": row["age"],
            "balance": _r2(row["balance"]),
            "flow": _r2(row["flow"]),
            "real_balance": _r2(row["balance"] / (1 + cfg["inflation"]) ** (row["age"] - age)),
        }
        for row in det["path"]
    ]
    deterministic = {
        "net_return": _r4(net),
        "balance_at_retirement": _r2(det["balance_at_retirement"]),
        "balance_at_retirement_real": _r2(det["balance_at_retirement"] / infl_factor),
        "spending_at_retirement": _r2(spending_ret),
        "required_nest_egg": _r2(required),
        "gap": _r2(gap),
        "extra_annual_contribution_needed": _r2(max(extra, 0.0)),
        "depletes_at_age": det["depletion"],
        "ending_balance": _r2(det["ending"]),
        "path": path,
    }
    if cfg_g is not None:
        deterministic["guardrail_path"] = [
            {"age": row["age"], "spending_after_cut": _r2(row["spending_after_cut"])}
            for row in det_g["guardrail_path"]
        ]

    rng = random.Random(seed)
    mu = math.log(1 + net) - 0.5 * vol * vol if net > -1 else -1.0
    if glide:
        mu_ret = math.log(1 + net_ret) - 0.5 * vol_ret * vol_ret if net_ret > -1 else -1.0
    else:
        mu_ret, vol_ret = mu, vol
    years_total = int(end_age - age)
    at_ret, endings, depletions, funded = [], [], [], []
    g_endings, g_fractions = [], []
    by_year: list[list[float]] = [[] for _ in range(years_total + 1)]
    for _ in range(max(sims, 1)):
        rets = (
            [
                math.exp(
                    (mu if k < n_pre else mu_ret)
                    + (vol if k < n_pre else vol_ret) * rng.gauss(0.0, 1.0)
                )
                - 1
                for k in range(years_total)
            ]
            if (vol > 0 or (glide and vol_ret > 0))
            else None
        )
        s = _simulate(cfg, rets)
        at_ret.append(s["balance_at_retirement"])
        endings.append(s["ending"])
        for k, row in enumerate(s["path"]):
            by_year[k].append(row["balance"])
        if s["depletion"] is not None:
            depletions.append(s["depletion"])
            funded.append(s["depletion"] - ret_age)
        else:
            funded.append(n_ret)
        if cfg_g is not None:
            sg = _simulate(cfg_g, rets)
            g_endings.append(sg["ending"])
            g_fractions.append(sg["fraction_cut"])
    at_ret.sort()
    endings.sort()
    funded.sort()
    depletions.sort()
    sims_n = max(sims, 1)
    successes = sum(1 for e in endings if e > 0)
    monte_carlo = {
        "simulations": sims_n,
        "volatility": vol,
        "success_probability": _r4(successes / sims_n),
        "balance_at_retirement": {
            "p10": _r2(_pct(at_ret, 0.1)),
            "p50": _r2(_pct(at_ret, 0.5)),
            "p90": _r2(_pct(at_ret, 0.9)),
        },
        "ending_balance": {
            "p10": _r2(_pct(endings, 0.1)),
            "p50": _r2(_pct(endings, 0.5)),
            "p90": _r2(_pct(endings, 0.9)),
        },
        "median_depletion_age": int(_pct(depletions, 0.5)) if depletions else None,
        "worst_decile_years_funded": _pct(funded, 0.1),
        "percentile_path": [
            {
                "age": int(age) + k,
                **{f"p{q}": _r2(_pct(vals, q / 100)) for q in (10, 25, 50, 75, 90)},
            }
            for k, vals in enumerate(sorted(v) for v in by_year)
        ],
    }
    if cfg_g is not None:
        g_successes = sum(1 for e in g_endings if e > 0)
        g_fractions.sort()
        monte_carlo["guardrails"] = {
            "constant_success_probability": monte_carlo["success_probability"],
            "guardrail_success_probability": _r4(g_successes / sims_n),
            "success_probability_gain": _r4(
                _r4(g_successes / sims_n) - monte_carlo["success_probability"]
            ),
            "median_fraction_of_years_cut": _r4(_pct(g_fractions, 0.5)),
        }
    assumptions = {
        **{k: v for k, v in cfg.items() if k not in ("net", "net_ret")},
        "return": ret,
        "fees": fees,
        "withdrawal_rate": wr,
    }
    if ret_return is not None:
        assumptions["ret_return"] = ret_return
    if ret_vol is not None:
        assumptions["ret_vol"] = ret_vol
    if cut is not None:
        assumptions["guardrails"] = {"cut_pct": cut, "trigger_pct": trigger}
    return {
        "years_to_retirement": n_pre,
        "years_in_retirement": n_ret,
        "assumptions": assumptions,
        "deterministic": deterministic,
        "monte_carlo": monte_carlo,
    }


# --- Social Security claiming ----------------------------------------------------------


def _ss_factor(claim_age: int, fra_age: float) -> float:
    """Benefit factor from months relative to full retirement age (4 dp).

    Early claiming is capped at 60 months before FRA: a claim age more than
    60 months early (reachable when ``fra_age`` is high, e.g. fra 70 / claim
    62 = 96 months early) gets the same factor as exactly 60 months early,
    matching SSA's reduction schedule (which does not extend past 60 months).
    """
    if claim_age < fra_age:
        months = min((fra_age - claim_age) * 12, 60)
        factor = 1 - 0.05 / 9 * min(months, 36) - 0.05 / 12 * max(months - 36, 0.0)
    else:
        factor = 1 + 0.08 * min(claim_age - fra_age, 70 - fra_age)
    return round(factor, 4)


def _ss_claim(p: dict) -> dict:
    """Compare claiming ages: each claim age is other income on the same paths."""
    benefit = _num(p, "benefit_at_fra", required=True)
    if benefit <= 0:
        raise ValueError("benefit_at_fra must be positive")
    fra = _num(p, "fra_age", 67)
    if not 62 <= fra <= 70:
        raise ValueError("fra_age must be between 62 and 70")
    ret_age = _num(p, "retirement_age", required=True)
    end_age = _num(p, "end_age", required=True)
    if end_age <= ret_age:
        raise ValueError("end_age must be greater than retirement_age")
    claims_in = p.get("claim_ages")
    if claims_in is None:
        claims = [62, 67, 70]
    else:
        if not isinstance(claims_in, (list, tuple)) or not claims_in:
            raise ValueError("claim_ages must be a non-empty list of ages")
        ages = []
        for v in claims_in:
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                raise ValueError("claim_ages must be a list of ages")
            a = int(float(v))
            ages.append(min(max(a, 62), 70))
        claims = sorted(set(ages))
    savings = _num(p, "savings", required=True)
    ret = _rate(p, "return", required=True)
    fees = _rate(p, "fees", 0.0)
    vol = _rate(p, "volatility", 0.0)
    infl = _rate(p, "inflation", 0.0)
    spending = _num(p, "spending", 0.0)
    sims = max(int(_num(p, "simulations", 2000)), 1)
    seed = int(_num(p, "seed", 42))
    net = ret - fees

    # seed once, reuse every path across claim ages so scenarios are comparable
    rng = random.Random(seed)
    mu = math.log(1 + net) - 0.5 * vol * vol if net > -1 else -1.0
    years_total = int(end_age - ret_age)
    paths = (
        [
            [math.exp(mu + vol * rng.gauss(0.0, 1.0)) - 1 for _ in range(years_total)]
            for _ in range(sims)
        ]
        if vol > 0
        else [None] * sims
    )

    factors = {a: _ss_factor(a, fra) for a in claims}
    claiming = []
    for a in claims:
        cfg = {
            "age": ret_age,
            "retirement_age": ret_age,
            "end_age": end_age,
            "savings": savings,
            "annual_contribution": 0.0,
            "contribution_growth": 0.0,
            "inflation": infl,
            "spending": spending,
            "other_income": benefit * factors[a],
            "other_income_start_age": a,
            "net": net,
        }
        endings, depletions = [], []
        for rets in paths:
            s = _simulate(cfg, rets)
            endings.append(s["ending"])
            if s["depletion"] is not None:
                depletions.append(s["depletion"])
        endings.sort()
        depletions.sort()
        claiming.append(
            {
                "age": a,
                "factor": factors[a],
                "first_year_benefit": _r2(benefit * factors[a]),
                "success_probability": _r4(sum(1 for e in endings if e > 0) / sims),
                "median_ending_balance": _r2(_pct(endings, 0.5)),
                "median_depletion_age": int(_pct(depletions, 0.5)) if depletions else None,
            }
        )

    # break-even on real terms: later claim's cumulative real benefits first exceed
    break_even = {}
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a1, a2 = claims[i], claims[j]
            f1, f2 = factors[a1], factors[a2]
            be = None
            for x in range(a2, int(end_age) + 1):
                if f2 * (x - a2 + 1) > f1 * (x - a1 + 1):
                    be = x
                    break
            break_even[f"{a1}_vs_{a2}"] = be
    return {
        "claiming": claiming,
        "break_even": break_even,
        "inputs": {
            "benefit_at_fra": benefit,
            "fra_age": fra,
            "claim_ages": claims,
            "savings": savings,
            "retirement_age": ret_age,
            "end_age": end_age,
            "return": ret,
            "volatility": vol,
            "inflation": infl,
            "fees": fees,
            "spending": spending,
            "simulations": sims,
            "seed": seed,
        },
    }


# --- withdrawal ------------------------------------------------------------------------


def _years_funded(
    nest: float, spending: float, years: int, returns: list[float] | None, net: float, infl: float
) -> tuple[int | None, float]:
    """(years until depletion or None, ending balance) drawing inflation-indexed spending."""
    balance = nest
    for k in range(years):
        r = returns[k] if returns is not None else net
        balance = balance * (1 + r) - spending * (1 + infl) ** k
        if balance <= 0:
            return k + 1, 0.0
    return None, balance


def _withdrawal(p: dict) -> dict:
    nest = _num(p, "nest_egg", required=True)
    years = int(_num(p, "years", 30))
    net = _rate(p, "return", required=True) - _rate(p, "fees", 0.0)
    vol = _rate(p, "volatility", 0.0)
    infl = _rate(p, "inflation", 0.0)
    sims = int(_num(p, "simulations", 2000))
    seed = int(_num(p, "seed", 42))
    spending_in = _num(p, "spending")
    rng = random.Random(seed)
    mu = math.log(1 + net) - 0.5 * vol * vol
    paths = (
        [
            [math.exp(mu + vol * rng.gauss(0.0, 1.0)) - 1 for _ in range(years)]
            for _ in range(max(sims, 1))
        ]
        if vol > 0
        else [None] * max(sims, 1)
    )

    def evaluate(rate: float) -> dict:
        spending = rate * nest
        endings, funded = [], []
        for rets in paths:
            dep, end = _years_funded(nest, spending, years, rets, net, infl)
            endings.append(end)
            funded.append(dep if dep is not None else years)
        endings.sort()
        funded.sort()
        det_dep, _ = _years_funded(nest, spending, 500, None, net, infl)
        return {
            "rate": rate,
            "annual_spending": _r2(spending),
            "success_probability": _r4(sum(1 for e in endings if e > 0) / len(endings)),
            "median_ending_balance": _r2(_pct(endings, 0.5)),
            "worst_decile_years_funded": _pct(funded, 0.1),
            "deterministic_years": det_dep,
        }

    table = [evaluate(r) for r in _TABLE_RATES]
    requested = None
    if spending_in is not None and nest > 0:
        row = evaluate(spending_in / nest)
        requested = {
            "rate": _r4(spending_in / nest),
            "spending": _r2(spending_in),
            "success_probability": row["success_probability"],
            "deterministic_years": row["deterministic_years"],
            "median_ending_balance": row["median_ending_balance"],
        }
    four = next(row for row in table if row["rate"] == 0.04)
    return {
        "nest_egg": nest,
        "years": years,
        "net_return": _r4(net),
        "volatility": vol,
        "inflation": infl,
        "simulations": max(sims, 1),
        "table": table,
        "deterministic_years_at_4pct": four["deterministic_years"],
        "requested": requested,
    }


def run_retirement(params: dict) -> dict:
    """Dispatch on ``params['action']``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    action = params.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(_ACTIONS)}")
    return {"goal": _goal, "project": _project, "ss_claim": _ss_claim, "withdrawal": _withdrawal}[
        action
    ](params)


def main() -> None:
    """Read JSON params from stdin, write the result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_retirement(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
