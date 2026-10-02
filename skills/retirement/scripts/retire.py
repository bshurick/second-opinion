#!/usr/bin/env python3
"""Usage: retire.py (--savings N | --from-accounts) [--age A --retirement-age R --end-age E --contribution N --contribution-growth R --return R --volatility R --inflation R --fees R --spending N --other-income N --other-income-start-age A --withdrawal-rate R --ret-return R --ret-vol R --guardrail-cut P --guardrail-trigger P --seed N --simulations N] | --goal TARGET (--years N | --monthly N) | --withdrawal [--years N] | --ss-benefit N --retirement-age R [--fra-age A] [--claim-age A ...] [--end-age E --return R --volatility R --inflation R --fees R --spending N --seed N --simulations N] [--partial]

Retirement and goal planning on top of retirement.py. --from-accounts sums
the total balance of every open connected SnapTrade account (one call) as
the starting savings; --savings takes a number instead. Default mode runs
the ``project`` action; --goal runs ``goal`` (target, years or monthly
contribution); --withdrawal runs the sustainable-withdrawal table with the
savings as the nest egg; --ss-benefit runs ``ss_claim``, comparing Social
Security claiming ages (default 62/67/70, override with repeatable
--claim-age) using the other project flags as the underlying simulation.
--ret-return/--ret-vol give the project action a second return/volatility
pair for retirement years (a two-block glide path). --guardrail-cut and
--guardrail-trigger (both required together) add a guardrail
variable-spending comparison to the project action. Output is
retirement.py's contract plus ``inputs`` and ``sources``. stdin is unused.
Exit codes: 0, 2, 4, 5, 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import retirement  # noqa: E402
from second_opinion import output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"retire.py: {message}")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="retire.py", add_help=False)
        p.add_argument("--savings", type=float, default=None)
        p.add_argument("--from-accounts", action="store_true")
        p.add_argument("--partial", action="store_true")
        p.add_argument("--goal", type=float, default=None)
        p.add_argument("--withdrawal", action="store_true")
        p.add_argument("--years", type=float, default=None)
        p.add_argument("--monthly", type=float, default=None)
        p.add_argument("--age", type=float, default=None)
        p.add_argument("--retirement-age", type=float, default=None)
        p.add_argument("--end-age", type=float, default=95)
        p.add_argument("--contribution", type=float, default=0.0)
        p.add_argument("--contribution-growth", type=float, default=0.02)
        p.add_argument("--return", dest="ret", type=float, default=0.06)
        p.add_argument("--volatility", type=float, default=0.12)
        p.add_argument("--inflation", type=float, default=0.025)
        p.add_argument("--fees", type=float, default=0.001)
        p.add_argument("--spending", type=float, default=0.0)
        p.add_argument("--other-income", type=float, default=0.0)
        p.add_argument("--other-income-start-age", type=float, default=None)
        p.add_argument("--withdrawal-rate", type=float, default=0.04)
        p.add_argument("--ret-return", type=float, default=None)
        p.add_argument("--ret-vol", type=float, default=None)
        p.add_argument("--guardrail-cut", type=float, default=None)
        p.add_argument("--guardrail-trigger", type=float, default=None)
        p.add_argument("--ss-benefit", type=float, default=None)
        p.add_argument("--fra-age", type=float, default=None)
        p.add_argument("--claim-age", type=int, action="append", default=None)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--simulations", type=int, default=2000)
        ns = p.parse_args(args)

        if (ns.guardrail_cut is None) != (ns.guardrail_trigger is None):
            missing = "--guardrail-trigger" if ns.guardrail_cut is not None else "--guardrail-cut"
            raise InvalidInput(f"{missing} is required when the other guardrail flag is set")

        sources = {"savings": "user", "accounts": []}
        savings = ns.savings
        account_flags: list[dict] = []
        if ns.from_accounts:
            hub = router.load()
            hub.partial = ns.partial
            accounts = hub.list_accounts()
            savings = sum(float(a.get("balance_total") or 0.0) for a in accounts)
            sources = {"savings": router.holdings_source(accounts), "accounts": [a["account_id"] for a in accounts]}
            account_flags = hub.unavailable_flags()
        if savings is None:
            raise InvalidInput("pass --savings N or --from-accounts to set the starting balance")

        if ns.goal is not None:
            params = {"action": "goal", "target": ns.goal, "current": savings, "return": ns.ret}
            if ns.monthly is not None:
                params["monthly_contribution"] = ns.monthly
            else:
                params["years"] = ns.years
        elif ns.withdrawal:
            params = {"action": "withdrawal", "nest_egg": savings, "years": ns.years or 30, "return": ns.ret, "fees": ns.fees, "volatility": ns.volatility, "inflation": ns.inflation, "simulations": ns.simulations, "seed": ns.seed}
            if ns.spending:
                params["spending"] = ns.spending
        elif ns.ss_benefit is not None:
            if ns.retirement_age is None:
                raise InvalidInput("--retirement-age is required for --ss-benefit")
            params = {
                "action": "ss_claim", "benefit_at_fra": ns.ss_benefit, "savings": savings,
                "retirement_age": ns.retirement_age, "end_age": ns.end_age, "return": ns.ret,
                "volatility": ns.volatility, "inflation": ns.inflation, "fees": ns.fees,
                "spending": ns.spending, "simulations": ns.simulations, "seed": ns.seed,
            }
            if ns.fra_age is not None:
                params["fra_age"] = ns.fra_age
            if ns.claim_age:
                params["claim_ages"] = ns.claim_age
        else:
            if ns.age is None or ns.retirement_age is None:
                raise InvalidInput("--age and --retirement-age are required for a projection")
            params = {
                "action": "project", "age": ns.age, "retirement_age": ns.retirement_age, "end_age": ns.end_age, "savings": savings,
                "annual_contribution": ns.contribution, "contribution_growth": ns.contribution_growth, "return": ns.ret, "volatility": ns.volatility,
                "inflation": ns.inflation, "fees": ns.fees, "spending": ns.spending, "other_income": ns.other_income,
                "other_income_start_age": ns.other_income_start_age if ns.other_income_start_age is not None else ns.retirement_age,
                "withdrawal_rate": ns.withdrawal_rate, "simulations": ns.simulations, "seed": ns.seed,
            }
            if ns.ret_return is not None:
                params["ret_return"] = ns.ret_return
            if ns.ret_vol is not None:
                params["ret_vol"] = ns.ret_vol
            if ns.guardrail_cut is not None and ns.guardrail_trigger is not None:
                params["guardrails"] = {"cut_pct": ns.guardrail_cut, "trigger_pct": ns.guardrail_trigger}
        try:
            result = retirement.run_retirement(params)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        inputs = {k: v for k, v in params.items() if k != "action"}
        inputs["savings"] = savings
        out = {"action": params["action"], "inputs": inputs, "sources": sources, **result}
        if account_flags:
            out["flags"] = list(out.get("flags") or []) + account_flags
        return out

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
