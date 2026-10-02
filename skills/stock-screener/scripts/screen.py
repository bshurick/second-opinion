#!/usr/bin/env python3
"""Usage: screen.py [--preset NAME] [--set KEY=VALUE ...] [--year YYYY] [--no-price]
                    [--price-limit N] [--held SYM,SYM ...] [--exclude-held] [--all]

Screens every US filer with XBRL financials. SEC EDGAR "frames" give one concept for every
company in a single request, so four years of revenue, margins, cash flow, capital spending,
stock pay, share counts and payouts, plus two year-end balance sheets, for the whole market
take about 180 requests (fetched four at a time, cached for a day under the plugin data
directory). ``screen_math.py`` applies the fundamental criteria; the survivors -- at most
``--price-limit`` of them (default 400), chosen by the figure the preset's price stage cares
about -- are then priced from Yahoo (market cap, enterprise value, sector, and the 12-month
price change skipping the latest month) and screened again on the price criteria, and ranked.

``--preset`` picks a criteria set (default ``growth``; see screen_math.PRESETS): growth, value,
quality, garp, magic, graham, payout. ``--set`` overrides one criterion, e.g.
``--set min_revenue_cagr=0.25 --set max_pe=20``; a value of ``none`` switches a criterion off.
``--year`` is the latest fiscal year (default: last calendar year); four years ending there are
used. ``--no-price`` stops after the fundamental stage. ``--held`` takes the symbols the person
already owns (comma-separated, repeatable): they are marked ``held`` in the output, and
``--exclude-held`` leaves them out of the survivors. ``--all`` includes every screened company
in the output, not only the survivors and near misses.

How the figures are assembled. Revenue comes from the concept that covers the most of the
years screened, with any missing year filled from the other revenue concepts. Capital spending
is the property-and-equipment tag (or the first of its stand-ins) plus oil-and-gas property
and capitalized software where a company tags those separately; a company with none of them
has no capex figure and fails the cash tests rather than passing on operating cash flow alone.
Debt is the largest of the total-debt tags (they overlap), plus short-term borrowings. A
company that reports deposits, loans or insurance premiums is marked a financial filer and set
aside before any test.

Output: screen_math's contract without ``companies`` (unless ``--all``), plus ``as_of``,
``latest_quarter_periods``, ``priced`` ``{"count", "of", "limit"}``, ``coverage`` (companies
with revenue in each year, so a thin latest year shows), ``held`` ``{"given", "matched",
"excluded"}`` when ``--held`` is used, ``sources`` and ``flags``. stdin is unused. Exit codes:
0, 2 (bad argument), 5 (EDGAR/Yahoo error), 6 (Python dependencies missing).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import screen_math  # noqa: E402
from second_opinion import edgar, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

# Revenue is tagged under several concepts; each company's series starts from the one that
# covers the most of the years screened (ties go to the first listed) and fills any missing
# year from the others, so a company that changed concepts is not lost.
REVENUE = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
# Annual flows: the first concept a company reports wins.
ANNUAL = {
    "gross_profit": ("GrossProfit",),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "ocf": ("NetCashProvidedByUsedInOperatingActivities",),
    "sbc": ("ShareBasedCompensation",),
    "dividends": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "PaymentsOfOrdinaryDividends"),
    "acquisitions": ("PaymentsToAcquireBusinessesNetOfCashAcquired",),
}
# Needed for the latest year only.
ANNUAL_LATEST = {
    "interest_expense": ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense", "InterestPaidNet", "InterestPaid"),
    "income_tax": ("IncomeTaxExpenseBenefit",),
    "buybacks": ("PaymentsForRepurchaseOfCommonStock",),
}
# Capital spending: the first base concept reported, plus the first of each add-on group.
# Oil-and-gas property and capitalized software are tagged beside (not inside) the base.
CAPEX_BASE = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForCapitalImprovements",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment",
    "PaymentsToAcquireRealEstate",
    "PaymentsToAcquireMachineryAndEquipment",
    "PaymentsForProceedsFromProductiveAssets",
)
CAPEX_ADD = (
    ("PaymentsToAcquireOilAndGasPropertyAndEquipment", "PaymentsToAcquireOilAndGasProperty", "PaymentsToExploreAndDevelopOilAndGasProperties"),
    ("PaymentsToDevelopSoftware", "PaymentsForSoftware"),
)
SHARES = "WeightedAverageNumberOfDilutedSharesOutstanding"
# Year-end balance sheet: the first concept reported wins.
BALANCE = {
    "equity": ("StockholdersEquity",),
    "assets": ("Assets",),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
}
BALANCE_PRIOR = ("assets", "current_assets", "current_liabilities")
CASH = ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash")
INVESTMENTS = ("ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent")
# Total-debt concepts overlap (with and without the current part, with and without leases), so
# the largest one reported is taken; a (noncurrent, current) pair is summed first.
DEBT_TOTAL = (
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
    "DebtLongtermAndShorttermCombinedAmount",
    "DebtAndCapitalLeaseObligations",
    "DebtInstrumentCarryingAmount",
)
DEBT_PAIRS = (
    ("LongTermDebtNoncurrent", "LongTermDebtCurrent"),
    ("LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
)
# Used only when none of the above is reported.
DEBT_FALLBACK = ("LongTermNotesPayable", "SeniorNotes", "NotesPayable", "ConvertibleDebtNoncurrent", "LongTermLineOfCredit", "LineOfCredit", "SecuredDebt", "UnsecuredDebt")
DEBT_SHORT = ("ShortTermBorrowings",)
DEBT_INCLUDES_SHORT = "DebtLongtermAndShorttermCombinedAmount"
# A company reporting any of these is a bank, lender or insurer: (concept, instant?).
FINANCIAL_MARKERS = (
    ("Deposits", True),
    ("LoansAndLeasesReceivableNetReportedAmount", True),
    ("InterestExpenseDeposits", False),
    ("PremiumsEarnedNet", False),
)
FINANCIAL_SECTORS = {"Financial Services"}
# Which fundamental survivors get priced first when there are more than --price-limit: the
# ones the preset's price stage is most likely to keep.
PRICE_POOL_BY = {
    "value": "fcf_after_sbc_margin_avg",
    "quality": "roce",
    "magic": "roce",
    "graham": "revenue_latest",
    "payout": "revenue_latest",
}
DEFAULT_PRICE_LIMIT = 400
YEARS_SCREENED = 4
FETCH_WORKERS = 4  # the SEC asks for at most 10 requests a second
MOMENTUM_LOOKBACK_DAYS = 400  # calendar days of closes fetched for the 12-month figure
MOMENTUM_BARS, MOMENTUM_SKIP = 252, 21
# The latest year normally has fewer filers than the year before (late filers, new fiscal
# calendars); below this share of the prior year's count the year is not fully reported yet.
THIN_YEAR_RATIO = 0.75

Frame = Callable[..., list]


def quarter_periods(today: dt.date) -> list[tuple[str, str]]:
    """The two most recent quarters likely reported by ``today`` (45-day filing lag), newest
    first, each paired with the same quarter a year earlier."""
    lagged = today - dt.timedelta(days=45)
    y, q = lagged.year, (lagged.month - 1) // 3  # the quarter before the lagged date's own
    if q == 0:
        y, q = y - 1, 4
    out = []
    for _ in range(2):
        out.append((f"CY{y}Q{q}", f"CY{y - 1}Q{q}"))
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out


def _by_cik(rows: list) -> dict[int, float]:
    return {r["cik"]: r["val"] for r in rows if isinstance(r, dict) and isinstance(r.get("val"), (int, float))}


class _Frames:
    """Every frame the screen needs, fetched a few at a time and read as ``{cik: value}``."""

    def __init__(self, frame: Frame, keys: list[tuple[str, str, str]]):
        keys = list(dict.fromkeys(keys))
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
            rows = list(ex.map(lambda k: frame(k[0], k[1], unit=k[2]), keys))
        self._data = {k[:2]: _by_cik(r) for k, r in zip(keys, rows)}

    def get(self, concept: str, period: str) -> dict[int, float]:
        return self._data.get((concept, period), {})

    def first(self, concepts: tuple[str, ...], period: str, cik: int) -> float | None:
        return next((self.get(c, period)[cik] for c in concepts if cik in self.get(c, period)), None)


def _frame_keys(years: list[int], quarters: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    latest = years[-1]
    ends = [f"CY{latest}Q4I", f"CY{latest - 1}Q4I"]
    debt = DEBT_TOTAL + tuple(c for pair in DEBT_PAIRS for c in pair) + DEBT_FALLBACK + DEBT_SHORT
    keys = []
    for y in years:
        annual = REVENUE + tuple(c for cs in ANNUAL.values() for c in cs) + CAPEX_BASE + tuple(c for g in CAPEX_ADD for c in g)
        keys += [(c, f"CY{y}", "USD") for c in annual]
        keys.append((SHARES, f"CY{y}", "shares"))
    keys += [(c, f"CY{latest}", "USD") for cs in ANNUAL_LATEST.values() for c in cs]
    for end in ends:
        keys += [(c, end, "USD") for cs in BALANCE.values() for c in cs]
        keys += [(c, end, "USD") for c in debt]
    keys += [(c, ends[0], "USD") for c in CASH + INVESTMENTS]
    keys += [(c, p, "USD") for pair in quarters for p in pair for c in REVENUE]
    keys += [(c, ends[0] if instant else f"CY{latest}", "USD") for c, instant in FINANCIAL_MARKERS]
    return keys


def _capex(fr: _Frames, period: str, cik: int) -> float | None:
    parts = [fr.first(CAPEX_BASE, period, cik)] + [fr.first(group, period, cik) for group in CAPEX_ADD]
    found = [abs(p) for p in parts if p is not None]
    return sum(found) if found else None


def _debt(fr: _Frames, period: str, cik: int) -> float | None:
    totals = {c: fr.get(c, period)[cik] for c in DEBT_TOTAL if cik in fr.get(c, period)}
    for noncurrent, current in DEBT_PAIRS:
        if cik in fr.get(noncurrent, period):
            totals[noncurrent] = fr.get(noncurrent, period)[cik] + fr.get(current, period).get(cik, 0)
    short = fr.first(DEBT_SHORT, period, cik)
    if totals:
        top = max(totals, key=lambda c: totals[c])
        return totals[top] + ((short or 0) if top != DEBT_INCLUDES_SHORT else 0)
    fallback = [fr.get(c, period)[cik] for c in DEBT_FALLBACK if cik in fr.get(c, period)]
    if fallback:
        return max(fallback) + (short or 0)
    return short


def build_companies(frame: Frame, years: list[int], quarters: list[tuple[str, str]], names: dict[int, dict]) -> list[dict]:
    """Assemble screen_math's ``companies`` from EDGAR frames (``frame(concept, period, unit=)``)."""
    fr = _Frames(frame, _frame_keys(years, quarters))
    latest = years[-1]
    end, prior_end = f"CY{latest}Q4I", f"CY{latest - 1}Q4I"
    financial = set().union(*(set(fr.get(c, end if instant else f"CY{latest}")) for c, instant in FINANCIAL_MARKERS))
    ciks = set().union(*(set(fr.get(c, f"CY{y}")) for c in REVENUE for y in years))
    companies = []
    for cik in ciks:
        best = max(REVENUE, key=lambda c: sum(1 for y in years if cik in fr.get(c, f"CY{y}")))
        order = (best,) + tuple(c for c in REVENUE if c != best)
        revenue = {str(y): fr.first(order, f"CY{y}", cik) for y in years}
        if any(v is None for v in revenue.values()):
            continue
        rec: dict[str, Any] = {
            "cik": cik,
            "ticker": (names.get(cik) or {}).get("ticker"),
            "name": (names.get(cik) or {}).get("title"),
            "financial": cik in financial,
            "annual": {"revenue": revenue},
        }

        def series(pick: Callable[[str], float | None], only: list[int] = years) -> dict[str, float]:
            return {str(y): v for y in only if (v := pick(f"CY{y}")) is not None}

        for k, concepts in ANNUAL.items():
            rec["annual"][k] = series(lambda p, cs=concepts: fr.first(cs, p, cik))
        for k, concepts in ANNUAL_LATEST.items():
            rec["annual"][k] = series(lambda p, cs=concepts: fr.first(cs, p, cik), [latest])
        rec["annual"]["capex"] = series(lambda p: _capex(fr, p, cik))
        rec["annual"]["diluted_shares"] = series(lambda p: fr.get(SHARES, p).get(cik))
        cash, invested = fr.first(CASH, end, cik), fr.first(INVESTMENTS, end, cik)
        rec["balance"] = {k: fr.first(cs, end, cik) for k, cs in BALANCE.items()}
        rec["balance"]["debt"] = _debt(fr, end, cik)
        rec["balance"]["cash"] = None if cash is None and invested is None else (cash or 0) + (invested or 0)
        rec["balance_prior"] = {k: fr.first(BALANCE[k], prior_end, cik) for k in BALANCE_PRIOR}
        rec["balance_prior"]["debt"] = _debt(fr, prior_end, cik)
        for now, ago in quarters:
            hit = next(((fr.get(c, now)[cik], fr.get(c, ago)[cik]) for c in order if cik in fr.get(c, now) and cik in fr.get(c, ago)), None)
            if hit:
                rec["quarter"] = {"revenue": hit[0], "revenue_year_ago": hit[1], "period": now}
                break
        companies.append(rec)
    return companies


def coverage(frame: Frame, years: list[int]) -> dict[str, int]:
    """Companies reporting revenue under any concept, per year (frames are cached by now)."""
    return {str(y): len(set().union(*(set(_by_cik(frame(c, f"CY{y}", unit="USD"))) for c in REVENUE))) for y in years}


def quote(ticker: str) -> dict | None:
    """Market cap, enterprise value, price and whether Yahoo files it under financials."""
    from second_opinion import market

    try:
        info = market.company_info(ticker)
    except Exception:  # noqa: BLE001 -- one missing quote must not sink the screen
        return None
    if not info.get("market_cap"):
        return None
    return {
        "market_cap": info.get("market_cap"),
        "enterprise_value": info.get("enterprise_value"),
        "price": info.get("current_price"),
        "sector": info.get("sector"),
        "financial": info.get("sector") in FINANCIAL_SECTORS,
    }


def momentum_from_closes(closes: list[float]) -> float | None:
    """The 12-month price change skipping the latest month, from daily (adjusted) closes."""
    if len(closes) <= MOMENTUM_BARS:
        return None
    then, recent = closes[-1 - MOMENTUM_BARS], closes[-1 - MOMENTUM_SKIP]
    return recent / then - 1 if then and then > 0 else None


def momentum(tickers: list[str], today: dt.date) -> dict[str, float | None]:
    """12-1 month momentum per ticker from ONE batched Yahoo download; {} when it fails."""
    from second_opinion import market

    try:
        start = (today - dt.timedelta(days=MOMENTUM_LOOKBACK_DAYS + MOMENTUM_SKIP + 10)).isoformat()
        hist = market.close_histories(tickers, start)
    except Exception:  # noqa: BLE001 -- momentum is an extra; the screen stands without it
        return {}
    return {t: momentum_from_closes([bar["adj_close"] for bar in bars]) for t, bars in hist.items()}


def price_pool(survivors: list[dict], preset: str | None, limit: int) -> tuple[list[dict], str]:
    """The fundamental survivors to price, best first by the preset's own measure."""
    key = PRICE_POOL_BY.get(preset or "", "revenue_cagr")
    ranked = sorted((s for s in survivors if s.get("ticker")), key=lambda s: -(s["metrics"].get(key) or 0))
    return ranked[:limit], key


def _parse_value(raw: str) -> Any:
    low = raw.strip().lower()
    if low in ("none", "null", "off"):
        return None
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(raw) if any(ch in raw for ch in ".eE") else int(raw)
    except ValueError:
        return raw


def parse_overrides(items: list[str] | None) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise InvalidInput(f"--set wants KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        overrides[k.strip()] = _parse_value(v)
    return overrides


def _held(items: list[str] | None) -> set[str]:
    return {s.strip().upper() for item in items or [] for s in item.split(",") if s.strip()}


def run(ns: argparse.Namespace, frame: Frame | None = None, quoter: Callable[[str], dict | None] = quote,
        today: dt.date | None = None, names: dict[int, dict] | None = None,
        momentum_of: Callable[[list[str], dt.date], dict] = momentum) -> dict:
    frame = frame or edgar.frame
    today = today or dt.date.today()
    latest = ns.year or today.year - 1
    years = list(range(latest - YEARS_SCREENED + 1, latest + 1))
    overrides = parse_overrides(ns.set)
    held = _held(ns.held)
    if ns.exclude_held and not held:
        raise InvalidInput("--exclude-held needs --held SYM,SYM (the symbols already owned)")
    try:  # a bad preset or criterion is reported before anything is fetched
        screen_math.run_screen_math({"years": years, "companies": [], "preset": ns.preset, "criteria": overrides})
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    quarters = quarter_periods(today)
    companies = build_companies(frame, years, quarters, names if names is not None else edgar.tickers())
    for c in companies:
        c["held"] = bool(c.get("ticker")) and str(c["ticker"]).upper() in held
    try:
        first = screen_math.run_screen_math({"years": years, "companies": companies, "preset": ns.preset, "criteria": overrides})
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    flags = []
    if edgar.user_agent_is_default():
        flags.append({"code": "EDGAR_USER_AGENT_DEFAULT", "message": "EDGAR_USER_AGENT is the placeholder; the SEC may throttle or block requests"})
    counts = coverage(frame, years)
    if counts[str(latest)] < THIN_YEAR_RATIO * counts[str(latest - 1)]:
        flags.append({"code": "LATEST_YEAR_THIN", "message": f"only {counts[str(latest)]} companies have reported fiscal {latest} against {counts[str(latest - 1)]} for {latest - 1}; the rest are left out until they file (or rerun with --year {latest - 1})"})
    result = first
    priced = {"count": 0, "of": len(first["survivors"]), "limit": ns.price_limit}
    has_price_criteria = any(first["criteria"].get(c) is not None for c in screen_math.PRICE)
    if not ns.no_price and first["survivors"]:
        pool, key = price_pool(first["survivors"], ns.preset, ns.price_limit)
        with ThreadPoolExecutor(max_workers=8) as ex:
            quotes = dict(zip([s["cik"] for s in pool], ex.map(lambda s: quoter(s["ticker"]), pool)))
        moves = momentum_of([s["ticker"] for s in pool if quotes.get(s["cik"])], today)
        by_cik = {c["cik"]: c for c in companies}
        for s in pool:
            q = quotes.get(s["cik"])
            if q:
                by_cik[s["cik"]]["market"] = {**q, "momentum": moves.get(str(s["ticker"]).upper())}
        priced["count"] = sum(1 for q in quotes.values() if q)
        unpriced = [s["ticker"] for s in pool if not quotes.get(s["cik"])]
        if unpriced:
            flags.append({"code": "UNPRICED", "message": f"no Yahoo quote for {', '.join(unpriced[:12])}{' and more' if len(unpriced) > 12 else ''}; left out of the price stage"})
        if len(pool) >= 20 and priced["count"] < len(pool) / 2:
            flags.append({"code": "PRICING_INCOMPLETE", "message": f"Yahoo returned a quote for only {priced['count']} of {len(pool)} companies, which usually means it is rate-limiting; wait a few minutes and run again"})
        with_ticker = sum(1 for s in first["survivors"] if s.get("ticker"))
        if with_ticker > ns.price_limit:
            flags.append({"code": "PRICE_LIMIT", "message": f"{with_ticker} companies passed the fundamentals; only the top {ns.price_limit} by {key.replace('_', ' ')} were priced (raise --price-limit)"})
        result = screen_math.run_screen_math({"years": years, "companies": companies, "preset": ns.preset, "criteria": overrides})
    elif has_price_criteria and ns.no_price:
        flags.append({"code": "PRICE_SKIPPED", "message": "--no-price: price criteria were not applied"})
    if held:
        matched = sorted(str(c["ticker"]).upper() for c in companies if c["held"])
        owned = [s for s in result["survivors"] if s["held"]]
        if ns.exclude_held:
            result["survivors"] = [s for s in result["survivors"] if not s["held"]]
        result["held"] = {"given": len(held), "matched": len(matched), "survivors_held": sorted(s["ticker"] for s in owned), "excluded": bool(ns.exclude_held)}
    if not ns.all:
        result.pop("companies", None)
    result.update(
        as_of=today.isoformat(),
        latest_quarter_periods=[now for now, _ in quarters],
        priced=priced,
        coverage=counts,
        sources={"fundamentals": "SEC EDGAR XBRL frames", "prices": "Yahoo (delayed)" if priced["count"] else None},
        flags=flags,
    )
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"screen.py: {message}")


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="screen.py", add_help=False)
    p.add_argument("--preset", default="growth", choices=sorted(screen_math.PRESETS))
    p.add_argument("--set", action="append", metavar="KEY=VALUE")
    p.add_argument("--year", type=int)
    p.add_argument("--no-price", action="store_true")
    p.add_argument("--price-limit", type=int, default=DEFAULT_PRICE_LIMIT)
    p.add_argument("--held", action="append", metavar="SYM,SYM")
    p.add_argument("--exclude-held", action="store_true")
    p.add_argument("--all", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    return output.run(lambda args: run(parser().parse_args(args)), argv)


if __name__ == "__main__":
    sys.exit(main())
