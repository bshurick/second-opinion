#!/usr/bin/env python3
"""Usage: fundamentals.py <symbol> [--quarterly]

Company profile plus financial statements from Yahoo Finance for DCF/comps
inputs: {"info": {...company_info incl. market_cap, enterprise_value,
shares_outstanding, total_debt, total_cash, free_cash_flow}, "statements":
{income_statement, balance_sheet, cash_flow, shares_outstanding, quarterly}}.
Statement keys are ISO period-end dates; values are absolute currency units.
Exit codes: 0, 2, 5, 6.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        quarterly = "--quarterly" in args
        rest = [a for a in args if a != "--quarterly"]
        if len(rest) != 1:
            raise InvalidInput("usage: fundamentals.py <symbol> [--quarterly]")
        symbol = brokerage.validate_symbol(rest[0])
        return {"info": market.company_info(symbol), "statements": market.financials(symbol, quarterly=quarterly)}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
