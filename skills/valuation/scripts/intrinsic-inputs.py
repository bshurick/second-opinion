#!/usr/bin/env python3
"""Usage: intrinsic-inputs.py <symbol> [--years N] [--business-type industrial|financial|reit|utility]

A filled `intrinsic.py` input: the fundamentals annual table from SEC EDGAR
company facts (through the fundamental-research skill's fundamentals.py,
default 10 fiscal years so Graham's tests see real history), the current
price, the two yields the Graham and Buffett arithmetic wants from FRED's
keyless CSV endpoint: AAA (Moody's Aaa corporate) and DGS10 (10-year
Treasury), and the business type read off the SEC SIC code in the EDGAR
submissions index: 6020-6199 (banks, savings institutions, credit),
6200-6299 (brokers, dealers, asset managers) and 6311-6411 (insurance) are
"financial", 6798 is "reit", 4910-4941 (electric, gas and water utilities) is
"utility", everything else "industrial". A SIC-6798 company with no revenue
line, or whose interest expense is more than half its revenue, is a mortgage
REIT: it lends rather than owns property, so it is typed "financial".
`--business-type` overrides all of it. Output:

  {"symbol", "cik", "company", "sic", "business_type", "as_of", "sources": {...},
   "assumptions": {"aaa_yield": {"value", "source"}, "treasury_10y": {...}, "price": {...},
                   "business_type": {"value", "source"}, "years": {...}},
   "intrinsic_input": {...ready to pipe into intrinsic.py, business_type included...},
   "flags": [...]}

Price and yields degrade to null with a flag when their source is down;
intrinsic.py then skips the figures that need them. When the submissions
index is unavailable the SIC is null, business_type falls back to
"industrial", and a SIC_UNAVAILABLE flag says so. Exit codes: 0, 2, 4
(SKILL_MISSING: fundamental-research is not installed; CONFIG_MISSING as for
EDGAR), 5, 6. stdin is not read.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, edgar, fred, market, output  # noqa: E402
from second_opinion.errors import ConfigError, InvalidInput, ScriptError  # noqa: E402

FUNDAMENTALS_SCRIPT = Path(__file__).resolve().parents[2] / "fundamental-research" / "scripts" / "fundamentals.py"
_DEFAULT_YEARS = 10
_BUSINESS_TYPES = ("industrial", "financial", "reit", "utility")
_UTILITY_SIC_RANGE = (4910, 4941)
_MORTGAGE_REIT_INTEREST_SHARE = 0.5
_REIT_SIC = 6798
_FINANCIAL_SIC_RANGES = (
    (6020, 6199, "banks, savings institutions and credit"),
    (6200, 6299, "brokers, dealers and asset managers"),
    (6311, 6411, "insurance"),
)
_UA_FLAG = {"code": "DEFAULT_USER_AGENT", "message": "set EDGAR_USER_AGENT to 'app-name contact@email' as the SEC requires; the default placeholder may be blocked"}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"usage: intrinsic-inputs.py <symbol> [--years N] [--business-type industrial|financial|reit|utility] ({message})")


def business_type_for_sic(sic: object) -> tuple[str, str]:
    """Map an SEC SIC code to intrinsic.py's business_type; returns (type, reason)."""
    try:
        code = int(str(sic).strip())
    except (TypeError, ValueError):
        return "industrial", "no SIC code"
    if code == _REIT_SIC:
        return "reit", f"SIC {code} is real estate investment trusts"
    for lo, hi, label in _FINANCIAL_SIC_RANGES:
        if lo <= code <= hi:
            return "financial", f"SIC {code} is in {lo}-{hi} ({label})"
    lo, hi = _UTILITY_SIC_RANGE
    if lo <= code <= hi:
        return "utility", f"SIC {code} is in {lo}-{hi} (electric, gas and water utilities)"
    return "industrial", f"SIC {code} is not a bank, broker, insurer, REIT or utility code"


def mortgage_reit_reason(annual: list[dict]) -> str | None:
    """Why a SIC-6798 company is a lender rather than a property owner, or None when it is not."""
    if not annual:
        return None
    latest = annual[-1]
    revenue, interest = latest.get("revenue"), latest.get("interest_expense")
    if revenue is None:
        return "no revenue line in its latest fiscal year"
    if interest is not None and revenue > 0 and interest > _MORTGAGE_REIT_INTEREST_SHARE * revenue:
        return f"interest expense is {interest / revenue:.0%} of revenue"
    return None


def _fundamentals_module():
    if not FUNDAMENTALS_SCRIPT.is_file():
        raise ConfigError(
            "the fundamental-research skill is not installed; intrinsic.py needs its EDGAR annual table",
            code="SKILL_MISSING",
            hint="re-run `node install.js` and select fundamental-research (it needs an EDGAR contact), or ask Claude to set up the finance plugin",
        )
    spec = importlib.util.spec_from_file_location("fundamentals", FUNDAMENTALS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _yield(series_id: str, flags: list[dict]) -> tuple[float | None, str]:
    try:
        obs = fred.latest(series_id)
    except ScriptError as exc:
        flags.append({"code": "FRED_UNAVAILABLE", "message": f"FRED series {series_id} unavailable ({exc}); set the yield by hand"})
        return None, f"FRED series {series_id} unavailable"
    name = fred.SERIES_NAMES.get(series_id, series_id)
    return round(obs["value"] / 100, 4), f"FRED series {series_id} ({name}), {obs['date']}, divided by 100"


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="intrinsic-inputs.py", add_help=False)
        p.add_argument("symbol")
        p.add_argument("--years", type=int, default=_DEFAULT_YEARS)
        p.add_argument("--business-type", choices=_BUSINESS_TYPES, default=None)
        ns = p.parse_args(args)
        symbol = brokerage.validate_symbol(ns.symbol)
        fundamentals = _fundamentals_module()

        cik, title = edgar.cik_for(symbol)
        facts = edgar.company_facts(cik)
        try:
            table = fundamentals.run_fundamentals({"facts": facts, "years": ns.years})
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        annual = [{k: v for k, v in row.items() if not k.startswith("_")} for row in table["annual"]]

        flags: list[dict] = []
        sic, sic_description = None, None
        try:
            subs = edgar.submissions(cik)
            sic, sic_description = subs.get("sic") or None, subs.get("sic_description") or None
        except ScriptError as exc:
            flags.append({"code": "SIC_UNAVAILABLE", "message": f"EDGAR submissions index unavailable ({exc}); business_type defaults to industrial, pass --business-type to set it"})
        if ns.business_type:
            business_type, business_type_source = ns.business_type, "--business-type override"
        else:
            business_type, reason = business_type_for_sic(sic)
            lender = mortgage_reit_reason(annual) if business_type == "reit" else None
            if lender:
                business_type, reason = "financial", f"{reason}, but {lender}: a mortgage REIT, judged as a lender"
            business_type_source = f"{reason}{f' ({sic_description})' if sic_description else ''} -> {business_type}"

        price, price_source = None, None
        try:
            rows = market.quote([symbol])
            price = rows[0].get("price") if rows else None
            price_source = rows[0].get("source") if rows and price is not None else None
        except Exception as exc:  # noqa: BLE001 — the quote is best-effort
            flags.append({"code": "QUOTE_FAILED", "message": f"quote failed ({exc})"})
        if price is None:
            flags.append({"code": "NO_PRICE", "message": "no current price; pass price to intrinsic.py by hand for P/E, P/B, and margin of safety"})

        fred_flags: list[dict] = []
        aaa, aaa_source = _yield("AAA", fred_flags)
        treasury, treasury_source = _yield("DGS10", fred_flags)
        if fred_flags:  # both series live at the same host: one outage is one flag
            flags.append(fred_flags[0])
        default_ua = edgar.user_agent_is_default()
        if default_ua:
            flags.append(_UA_FLAG)

        return {
            "symbol": symbol,
            "cik": cik,
            "company": table.get("company") or title,
            "sic": sic,
            "business_type": business_type,
            "as_of": date.today().isoformat(),
            "sources": {
                "financials": "sec-edgar",
                "price": price_source,
                "yields": "fred" if aaa is not None or treasury is not None else None,
                "user_agent_is_default": default_ua,
            },
            "assumptions": {
                "price": {"value": price, "source": f"{price_source} quote" if price_source else "unavailable"},
                "aaa_yield": {"value": aaa, "source": aaa_source},
                "treasury_10y": {"value": treasury, "source": treasury_source},
                "business_type": {"value": business_type, "source": business_type_source},
                "years": {"value": ns.years, "source": "fiscal years requested from EDGAR; Graham's tests want 10"},
            },
            "intrinsic_input": {"annual": annual, "price": price, "aaa_yield": aaa, "treasury_10y": treasury, "business_type": business_type},
            "flags": flags,
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
