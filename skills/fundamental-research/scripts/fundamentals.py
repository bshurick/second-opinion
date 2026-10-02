"""Fundamental research from SEC XBRL company facts and the filing index:
annual financial table, margins and returns, growth rates, a quality
checklist, flags, the latest quarter, and a filings summary with links.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python fundamentals.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "facts": { ...the SEC "companyfacts" JSON for the company
                 (https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json):
                 entityName, facts: {"us-gaap": {Concept: {units: {UNIT: [facts]}}}} },
      "years": 5,                            # fiscal years to keep (default 5)
      "filings": [ ...rows from the SEC "submissions" JSON's filings.recent,
                   flattened: form, filingDate, accessionNumber, primaryDocument,
                   items ... ],               # optional
      "cik": 320193,                         # needed to build filing URLs
      "as_of": "YYYY-MM-DD",                 # optional, default: latest filing date
      "quarters": 8                          # optional; adds "quarterly" + "ttm" (see below)
    }

Output JSON contract (stdout)::

    {
      "company", "concepts_used": {metric: concept},
      "annual": [{fiscal_year, period_end, revenue, gross_profit, operating_income,
                  net_income, operating_cash_flow, capex, free_cash_flow,
                  total_assets, total_liabilities, equity, long_term_debt, cash,
                  net_debt, dividends_paid, eps_diluted, diluted_shares,
                  interest_expense, gross_margin, operating_margin, net_margin,
                  fcf_margin, cash_conversion, roe, roa, debt_to_equity,
                  interest_coverage, revenue_growth, eps_growth,
                  sbc, sbc_pct_revenue, sbc_vs_fcf, dso, dio,
                  goodwill_pct_assets, current_assets, current_liabilities,
                  current_ratio, depreciation_amortization}],   # oldest first
      "latest_quarter": {period, fiscal_period, fiscal_year, revenue?, net_income?,
                         eps_diluted?, derived?: true} | null,   # derived: a Q4 computed
                                                                 # as annual - 9-month YTD
      "growth": {years, revenue_cagr, net_income_cagr, fcf_cagr, eps_cagr, diluted_shares_cagr},
      "quality": {score, out_of, checks: [{check, passed, value}]},
      "filings": {as_of, counts, latest_10k, latest_10q, latest_proxy, recent_8k,
                  recent_form4, insider_filings_90d} | null,
      "flags": [{code, message}],    # MISSING_DATA, BANK_REVENUE_PROXY, REVENUE_DECLINE,
                                      # NEGATIVE_FCF, DILUTION, LEVERAGE, then (additive,
                                      # in this order) SBC_HEAVY, RECEIVABLES_BUILDING,
                                      # DSO_RISING, INVENTORY_BUILDING,
                                      # GOODWILL_HEAVY, ACCRUALS
      "quarterly": [{fiscal_year, period_end, revenue, net_income,
                     revenue_yoy, derived}],   # only when "quarters" was given; oldest first
      "ttm": {revenue, net_income, revenue_ttm_yoy}   # only when "quarters" was given
    }

Method: annual values are 10-K (or 20-F/40-F) facts with fiscal period FY,
one per fiscal year keyed by the SEC ``fy`` (the filing's fiscal year, so a
June year-end company's period ending 2026-06-30 is fiscal 2026). Every fact
in a 10-K carries ``fp="FY"`` — the embedded quarterly figures and the
prior-year comparatives too — so a duration fact (one with a ``start``) is
an annual candidate only when it spans 340..390 days; instants (balance
sheet, no ``start``) have no span test. Among a year's candidates the fact
whose period ends in that fiscal year wins, then the latest filed (so
restatements replace originals), then the longest duration. Several XBRL
concept names are tried per metric in a fixed order; for revenue the last
two are bank concepts — ``RevenuesNetOfInterestExpense`` and then
``InterestAndDividendIncomeOperating``, which is gross interest and dividend
income before interest expense, so when that alias is the one used the
BANK_REVENUE_PROXY flag says so (margins and DSO are then on that base;
``InterestIncomeExpenseNet`` is net interest income, not revenue, and is not
an alias). Capex aliases end with oil-and-gas development spend, capital
improvements and, last and only as a fallback, ``PaymentsToAcquireRealEstate``
(a REIT's acquisitions are growth capex, not maintenance).
Free cash flow = operating cash flow - capital expenditure. Growth
rates compare consecutive fiscal years; CAGRs span the table. The quality
checklist scores eight tests on the latest available values (revenue
growing, FCF/net income >= 0.8, share count not rising more than 2%/yr,
debt/equity < 1, ROE > 10%, operating margin not down more than 2 points
over the table, interest coverage > 5, positive FCF every year); tests with
no data are excluded from out_of. Filing URLs follow
https://www.sec.gov/Archives/edgar/data/<cik>/<accession-no-dashes>/<primaryDocument>.
Money as reported (usually USD), ratios 4 dp. Companies report their own
adjusted figures, which can differ from these XBRL-derived ones.

Red-flag screens (accounting-quality, additive, not part of ``_CORE`` so a
company that doesn't tag these concepts still gets the rest of the table):
``sbc`` is share-based compensation (cash-flow statement); ``dso`` = days
sales outstanding = accounts receivable / revenue x 365; ``dio`` = days
inventory outstanding = inventory / (revenue - gross_profit, a COGS proxy)
x 365; ``goodwill_pct_assets`` = goodwill / total assets. Flags (screens
with named thresholds, not judgments): SBC_HEAVY when the latest year's
SBC is >10% of revenue or exceeds free cash flow; RECEIVABLES_BUILDING /
INVENTORY_BUILDING when receivables/inventory grew more than 10 points/yr
faster than revenue (CAGR each over the first/last years each concept is
tagged, not the table's fixed endpoints — a concept can go untagged in the
earliest years); DSO_RISING when DSO widened more than 15 days from the
earliest to the latest available year; GOODWILL_HEAVY when goodwill is
>30% of total assets; ACCRUALS when net income's CAGR outpaces operating
cash flow's CAGR by more than 15 points/yr (same first/last-available
convention).

Quarterly table (``quarters: N`` input, N >= 2): discrete-quarter figures for
revenue and net income only, keyed by period-end date. A 10-Q carries
year-to-date facts (six and nine months) under the same ``fp=Q2``/``Q3`` as
the quarter itself, so a duration fact is a quarter only when it spans
80..100 days; the fourth quarter comes from the 10-K (an ``fp="Q4"`` fact, or
an ``fp="FY"`` fact with a ~90-day duration) and sits in sequence by period
end. For one period end a 10-Q fact wins over a 10-K one, then the latest
filed. Many 10-Ks tag no discrete Q4 at all; then Q4 is derived as the
~12-month annual fact minus the nine-month (255..285-day) year-to-date fact
that starts the same day and ends 80..100 days earlier, with ``period_end`` =
the annual end, ``fiscal_year`` = the annual fact's ``fy``, and the row marked
``derived: true`` (every other row carries ``derived: false``); a discrete
Q4 fact for that period end always takes precedence. ``latest_quarter``
becomes such a derived Q4 (revenue and net income only, ``derived: true``)
when it ends after the latest 10-Q quarter. ``fiscal_year`` is the SEC ``fy``
of the fact used. ``revenue_yoy``
compares the quarter ending 365 +/- 15 days earlier. ``ttm`` sums the four
most recent quarters per metric, null unless their period ends are 250..300
days apart (four consecutive quarters, no gap); ``revenue_ttm_yoy`` compares
that sum with the four quarters before it (null without a full extra year of
quarterly history). ``latest_quarter`` applies the same 80..100-day test.
Absent ``quarters``, none of this runs and the output is unchanged from before
this feature (additive-only contract).
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

_ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
_QUARTER_FORMS = {"10-Q", "10-Q/A"}
_ANNUAL_SPAN = (340, 390)  # days: a ~12-month duration fact
_QUARTER_SPAN = (80, 100)  # days: a ~3-month duration fact (not a 6/9-month year-to-date one)
_TTM_SPAN = (250, 300)  # days between the first and last period ends of four consecutive quarters
_YOY_TOLERANCE_DAYS = 15  # the prior-year quarter ends 365 +/- this many days earlier
_YTD9_SPAN = (255, 285)  # days: a nine-month year-to-date duration fact
_BANK_REVENUE_CONCEPT = "InterestAndDividendIncomeOperating"
_CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RevenuesNetOfInterestExpense",
        "InterestAndDividendIncomeOperating",  # banks: gross interest income (BANK_REVENUE_PROXY)
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireOilAndGasPropertyAndEquipment",
        "PaymentsToExploreAndDevelopOilAndGasProperties",
        "PaymentsForCapitalImprovements",
        "PaymentsToAcquireRealEstate",  # REIT acquisitions are growth capex: last, fallback only
    ],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfOrdinaryDividends",
        "DividendsCommonStockCash",
        "DividendsCommonStock",
    ],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating"],
    "share_based_compensation": ["ShareBasedCompensation"],
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
        "AccountsNotesAndLoansReceivableNetCurrent",
    ],
    "inventory": ["InventoryNet", "InventoryFinishedGoodsNetOfAllowances"],
    "goodwill": ["Goodwill"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    # REITs: gains on selling properties sit in net income and are taken out of funds from operations.
    "gain_on_property_sales": [
        "GainLossOnSaleOfProperties",
        "GainsLossesOnSalesOfInvestmentRealEstate",
        "GainLossOnDispositionOfRealEstateDiscontinuedOperations",
        "GainLossOnSaleOfPropertyPlantEquipment",
    ],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "Depreciation",
    ],
}
_CORE = [
    "net_income",
    "operating_cash_flow",
    "diluted_shares",
    "operating_income",
    "gross_profit",
    "capex",
    "total_assets",
    "total_liabilities",
    "equity",
    "long_term_debt",
    "cash",
]
_LABELS = {
    "net_income": "net income",
    "operating_cash_flow": "operating cash flow",
    "diluted_shares": "diluted shares",
    "operating_income": "operating income",
    "gross_profit": "gross profit",
    "capex": "capex",
    "total_assets": "total assets",
    "total_liabilities": "total liabilities",
    "equity": "equity",
    "long_term_debt": "long-term debt",
    "cash": "cash",
}


def _r2(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _div(a: float | None, b: float | None) -> float | None:
    return None if a is None or not b else a / b


def _growth(cur: float | None, prev: float | None) -> float | None:
    return None if cur is None or prev is None or prev <= 0 else cur / prev - 1


def _days(numerator: float | None, denominator: float | None) -> float | None:
    """``numerator / denominator * 365``; null unless both are present and denominator > 0."""
    return (
        None
        if numerator is None or denominator is None or denominator <= 0
        else numerator / denominator * 365
    )


def _cagr(first: float | None, last: float | None, years: int) -> float | None:
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1


def _windowed_cagr(
    rows: list[dict], key: str, other: str, *also_require: str
) -> tuple[float | None, float | None]:
    """CAGR of ``key`` and of ``other``, both over the same window: the first and last rows
    where ``key``, ``other`` and every name in ``also_require`` are all non-null (the "first/last
    available values" a screen needs, not the table's fixed endpoints — a concept can go
    untagged in the earliest years). ``(None, None)`` when fewer than two such rows exist or
    the span between them (in fiscal years) is non-positive.
    """
    idx = [
        i
        for i, r in enumerate(rows)
        if r.get(key) is not None
        and r.get(other) is not None
        and all(r.get(name) is not None for name in also_require)
    ]
    if len(idx) < 2:
        return None, None
    i0, i1 = idx[0], idx[-1]
    span = rows[i1]["fiscal_year"] - rows[i0]["fiscal_year"]
    if span <= 0:
        return None, None
    return (
        _cagr(rows[i0][key], rows[i1][key], span),
        _cagr(rows[i0][other], rows[i1][other], span),
    )


def _facts_for(gaap: dict, concept: str) -> list[dict]:
    node = gaap.get(concept)
    if not isinstance(node, dict):
        return []
    out = []
    for unit, rows in (node.get("units") or {}).items():
        for r in rows or []:
            if isinstance(r, dict) and r.get("val") is not None:
                out.append({**r, "unit": unit})
    return out


def _parse_date(text: object) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None


def _span_days(f: dict) -> int | None:
    """Days from ``start`` to ``end`` for a duration fact; None for instants (no ``start``)."""
    if not f.get("start"):
        return None
    start, end = _parse_date(f.get("start")), _parse_date(f.get("end"))
    return None if start is None or end is None else (end - start).days


def _is_annual_span(f: dict) -> bool:
    """True for instants and for durations of roughly one fiscal year (340..390 days).

    A 10-K's facts all carry ``fp="FY"``, the embedded quarterly figures
    included; the span test is what tells the 12-month value from a 3-month one.
    """
    span = _span_days(f)
    return span is None or _ANNUAL_SPAN[0] <= span <= _ANNUAL_SPAN[1]


def _is_quarter_span(f: dict) -> bool:
    """True for instants and for durations of roughly one quarter (80..100 days).

    10-Q facts include year-to-date durations (six and nine months) under the
    same ``fp``; only the ~90-day fact is the discrete quarter.
    """
    span = _span_days(f)
    return span is None or _QUARTER_SPAN[0] <= span <= _QUARTER_SPAN[1]


def _fiscal_year(f: dict) -> int | None:
    fy = f.get("fy")
    try:
        return int(fy) if fy is not None else int(str(f.get("end") or "")[:4])
    except ValueError:
        return None


def _annual(gaap: dict, metric: str) -> tuple[dict[int, dict], str | None]:
    """{fiscal_year: fact} using the first concept that has annual data for each year.

    Candidates are ``fp="FY"`` facts from annual forms whose duration (when
    they have one) is ~12 months. Per fiscal year the winner is the fact
    whose period ends in that year, then the latest filed (restatements
    replace originals), then the longest duration.
    """
    picked: dict[int, dict] = {}
    used = None
    for concept in _CONCEPTS[metric]:
        by_year: dict[int, dict] = {}
        for f in _facts_for(gaap, concept):
            if f.get("form") not in _ANNUAL_FORMS or f.get("fp") != "FY":
                continue
            if not _is_annual_span(f):
                continue
            fy = _fiscal_year(f)
            if fy is None:
                continue

            def rank(x: dict) -> tuple[bool, str, int]:
                return (
                    str(x.get("end") or "")[:4] == str(fy),
                    str(x.get("filed") or ""),
                    _span_days(x) or 0,
                )

            cur = by_year.get(fy)
            if cur is None or rank(f) > rank(cur):
                by_year[fy] = f
        if by_year:
            used = used or concept
            for fy, f in by_year.items():
                picked.setdefault(fy, f)
    return picked, used


def _latest_quarter(gaap: dict) -> dict | None:
    best: dict | None = None
    values: dict[str, float] = {}

    def is_quarter(f: dict) -> bool:
        return (
            f.get("form") in _QUARTER_FORMS
            and str(f.get("fp") or "").startswith("Q")
            and _is_quarter_span(f)
        )

    for metric in ("revenue", "net_income", "eps_diluted"):
        for concept in _CONCEPTS[metric]:
            for f in _facts_for(gaap, concept):
                if is_quarter(f) and (best is None or str(f.get("end")) > str(best.get("end"))):
                    best = f
    # A fourth quarter derived from the 10-K (annual minus nine-month YTD) that ends after
    # the latest 10-Q quarter is the latest quarter; revenue and net income only.
    derived = {m: _quarterly_series(gaap, m) for m in ("revenue", "net_income")}
    derived_ends = sorted(
        {end for s in derived.values() for end, f in s.items() if f.get("derived")}
    )
    if derived_ends and (best is None or derived_ends[-1] > str(best.get("end"))):
        end = derived_ends[-1]
        f = derived["revenue"].get(end) or derived["net_income"][end]
        return {
            "period": end,
            "fiscal_period": "Q4",
            "fiscal_year": f.get("fy"),
            **{m: _r2(float(s[end]["val"])) for m, s in derived.items() if end in s},
            "derived": True,
        }
    if best is None:
        return None
    for metric in ("revenue", "net_income", "eps_diluted"):
        for concept in _CONCEPTS[metric]:
            for f in _facts_for(gaap, concept):
                if (
                    is_quarter(f)
                    and f.get("end") == best.get("end")
                    and f.get("fp") == best.get("fp")
                ):
                    values.setdefault(metric, float(f["val"]))
    return {
        "period": best.get("end"),
        "fiscal_period": best.get("fp"),
        "fiscal_year": best.get("fy"),
        **{k: _r4(v) if k == "eps_diluted" else _r2(v) for k, v in values.items()},
    }


def _derived_q4(facts: list[dict]) -> dict[str, dict]:
    """{period_end: synthetic Q4 fact} = annual fact - nine-month year-to-date fact.

    For each ~12-month ``fp="FY"`` annual-form fact, a ~9-month duration fact
    (255..285 days) that starts on the same day (when both have a ``start``)
    and ends 80..100 days earlier gives Q4 = annual - YTD9. The synthetic fact
    carries the annual fact's ``fy``, ``form``, ``filed`` and ``end``, ``fp="Q4"``
    and ``derived: True``. Latest filed wins among annual and among YTD facts.
    """
    annual: dict[str, dict] = {}
    ytd9: dict[str, dict] = {}
    for f in facts:
        span = _span_days(f)
        if span is None or _parse_date(f.get("end")) is None:
            continue
        end = str(f.get("end"))[:10]
        if f.get("form") in _ANNUAL_FORMS and f.get("fp") == "FY" and _is_annual_span(f):
            bucket = annual
        elif _YTD9_SPAN[0] <= span <= _YTD9_SPAN[1]:
            bucket = ytd9
        else:
            continue
        cur = bucket.get(end)
        if cur is None or str(f.get("filed") or "") > str(cur.get("filed") or ""):
            bucket[end] = f
    out: dict[str, dict] = {}
    for end, a in annual.items():
        a_end = _parse_date(end)
        for y_end, y in ytd9.items():
            gap = (a_end - _parse_date(y_end)).days
            if not (_QUARTER_SPAN[0] <= gap <= _QUARTER_SPAN[1]):
                continue
            if a.get("start") and y.get("start") and a["start"] != y["start"]:
                continue
            out[end] = {
                **a,
                "fp": "Q4",
                "start": (_parse_date(y_end) + timedelta(days=1)).isoformat(),
                "val": float(a["val"]) - float(y["val"]),
                "derived": True,
            }
            break
    return out


def _quarterly_series(gaap: dict, metric: str) -> dict[str, dict]:
    """{period_end: fact} for discrete-quarter figures.

    Accepted: 10-Q/10-Q/A facts whose fiscal period starts with "Q" and whose
    duration (when present) is ~90 days — this drops the six- and nine-month
    year-to-date facts a 10-Q also carries under ``fp=Q2``/``Q3``; and 10-K
    (annual-form) facts that are a discrete ~90-day quarter (``fp="Q4"``, or
    ``fp="FY"`` with a ~90-day duration), which is how the fourth quarter
    usually reaches the series since no 10-Q covers it. Keyed by period end so
    a 10-K-derived Q4 sits in sequence; for one period end a 10-Q fact wins
    over a 10-K fact, then the latest filed. When no discrete fact covers a
    fiscal year's fourth quarter, ``_derived_q4`` (annual minus nine-month
    year-to-date) fills it with a fact marked ``derived: True``.
    """
    picked: dict[str, dict] = {}
    for concept in _CONCEPTS[metric]:
        by_end: dict[str, dict] = {}
        concept_facts = _facts_for(gaap, concept)
        for f in concept_facts:
            fp = str(f.get("fp") or "")
            form = f.get("form")
            if form in _QUARTER_FORMS:
                ok = fp.startswith("Q") and _is_quarter_span(f)
            elif form in _ANNUAL_FORMS:
                ok = (fp.startswith("Q") and _is_quarter_span(f)) or (
                    fp == "FY" and _span_days(f) is not None and _is_quarter_span(f)
                )
            else:
                ok = False
            end = str(f.get("end") or "")[:10]
            if not ok or _parse_date(end) is None or _fiscal_year(f) is None:
                continue
            cur = by_end.get(end)

            def rank(x: dict) -> tuple[bool, str]:
                return (x.get("form") in _QUARTER_FORMS, str(x.get("filed") or ""))

            if cur is None or rank(f) > rank(cur):
                by_end[end] = f
        for end, f in _derived_q4(concept_facts).items():
            by_end.setdefault(end, f)  # a discrete Q4 fact for that period end wins
        for end, f in by_end.items():
            picked.setdefault(end, f)
    return picked


def _year_earlier(series: dict[str, dict], end: str) -> dict | None:
    """The fact whose period ends about one year before ``end`` (365 +/- 15 days)."""
    d = _parse_date(end)
    if d is None:
        return None
    for other, f in series.items():
        o = _parse_date(other)
        if o is not None and abs((d - o).days - 365) <= _YOY_TOLERANCE_DAYS:
            return f
    return None


def _quarterly_table(gaap: dict, n: int) -> tuple[list[dict], dict]:
    """Most recent ``n`` quarters' revenue/net income (oldest first) plus TTM."""
    rev_series = _quarterly_series(gaap, "revenue")
    ni_series = _quarterly_series(gaap, "net_income")

    def ttm_sum(series: dict[str, dict], ends: list[str], end_idx: int) -> float | None:
        """Sum of the four quarters ending at ``ends[end_idx - 1]``; null unless they are
        four consecutive quarters (first and last period ends 250..300 days apart)."""
        if end_idx < 4:
            return None
        window = ends[end_idx - 4 : end_idx]
        first, last = _parse_date(window[0]), _parse_date(window[-1])
        if first is None or last is None:
            return None
        if not (_TTM_SPAN[0] <= (last - first).days <= _TTM_SPAN[1]):
            return None
        vals = [series[e].get("val") for e in window]
        return None if any(v is None for v in vals) else sum(float(v) for v in vals)

    rev_ends, ni_ends = sorted(rev_series), sorted(ni_series)
    ttm_rev = ttm_sum(rev_series, rev_ends, len(rev_ends))
    ttm_ni = ttm_sum(ni_series, ni_ends, len(ni_ends))
    prev_ttm_rev = ttm_sum(rev_series, rev_ends, len(rev_ends) - 4)
    ttm = {
        "revenue": _r2(ttm_rev),
        "net_income": _r2(ttm_ni),
        "revenue_ttm_yoy": _r4(_growth(ttm_rev, prev_ttm_rev)),
    }

    rows = []
    for end in sorted(set(rev_series) | set(ni_series))[-n:]:
        rf, nf = rev_series.get(end), ni_series.get(end)
        rev = float(rf["val"]) if rf else None
        ni = float(nf["val"]) if nf else None
        prev_rf = _year_earlier(rev_series, end)
        prev_rev = float(prev_rf["val"]) if prev_rf else None
        rows.append(
            {
                "fiscal_year": _fiscal_year(rf or nf),
                "period_end": (rf or nf).get("end"),
                "revenue": _r2(rev),
                "net_income": _r2(ni),
                "revenue_yoy": _r4(_growth(rev, prev_rev)),
                "derived": bool((rf or {}).get("derived") or (nf or {}).get("derived")),
            }
        )
    return rows, ttm


def _filings(rows: list, cik: object, as_of: str | None) -> dict | None:
    if not rows:
        return None
    clean = [r for r in rows if isinstance(r, dict) and r.get("form") and r.get("filingDate")]
    clean.sort(key=lambda r: str(r["filingDate"]), reverse=True)
    as_of_date = (
        date.fromisoformat(as_of) if as_of else date.fromisoformat(str(clean[0]["filingDate"])[:10])
    )
    cik_num = int(cik) if cik is not None else None

    def url(r: dict) -> str | None:
        acc = str(r.get("accessionNumber") or "").replace("-", "")
        if cik_num is None or not acc or not r.get("primaryDocument"):
            return None
        return f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc}/{r['primaryDocument']}"

    def latest(forms: set[str]) -> dict | None:
        r = next((x for x in clean if x["form"] in forms), None)
        return {"form": r["form"], "date": r["filingDate"], "url": url(r)} if r else None

    counts: dict[str, int] = {}
    for r in clean:
        counts[r["form"]] = counts.get(r["form"], 0) + 1
    form4 = [r for r in clean if r["form"] in ("4", "4/A")]
    floor = (as_of_date - timedelta(days=90)).isoformat()
    return {
        "as_of": as_of_date.isoformat(),
        "counts": counts,
        "latest_10k": latest({"10-K", "10-K/A", "20-F", "40-F"}),
        "latest_10q": latest({"10-Q", "10-Q/A"}),
        "latest_proxy": latest({"DEF 14A", "DEFA14A"}),
        "recent_8k": [
            {"date": r["filingDate"], "items": r.get("items"), "url": url(r)}
            for r in clean
            if r["form"] == "8-K"
        ][:5],
        "recent_form4": [{"date": r["filingDate"], "url": url(r)} for r in form4][:10],
        "insider_filings_90d": sum(1 for r in form4 if str(r["filingDate"]) >= floor),
    }


def summarize_filings(filings: list, cik: object, as_of: str | None = None) -> dict | None:
    """Filings summary alone (counts, latest 10-K/10-Q/proxy, recent 8-K and Form 4 with URLs)."""
    return _filings(filings or [], cik, as_of)


def run_fundamentals(params: dict) -> dict:
    """Build the fundamentals view for ``params``; raises ValueError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    facts = params.get("facts")
    if not isinstance(facts, dict):
        raise ValueError("facts is required (the SEC companyfacts JSON)")
    gaap = (
        (facts.get("facts") or {}).get("us-gaap") if isinstance(facts.get("facts"), dict) else None
    )
    if not isinstance(gaap, dict) or not gaap:
        raise ValueError("no us-gaap facts in the companyfacts JSON")
    keep = int(params.get("years") or 5)

    series: dict[str, dict[int, dict]] = {}
    used: dict[str, str] = {}
    for metric in _CONCEPTS:
        series[metric], concept = _annual(gaap, metric)
        if concept:
            used[metric] = concept
    if not series["total_liabilities"] and series["total_assets"] and series["equity"]:
        # Many filers tag LiabilitiesAndStockholdersEquity but never Liabilities;
        # assets minus equity is the balance-sheet identity's answer.
        derived = {}
        for fy, a in series["total_assets"].items():
            e = series["equity"].get(fy)
            if e is not None:
                derived[fy] = {**a, "val": float(a["val"]) - float(e["val"])}
        if derived:
            series["total_liabilities"] = derived
            used["total_liabilities"] = f"{used['total_assets']} - {used['equity']} (derived)"
    years = sorted({fy for m in _CORE + ["revenue"] for fy in series[m]})[-keep:]
    if not years:
        raise ValueError("no annual (10-K) facts found")

    def val(metric: str, fy: int) -> float | None:
        f = series[metric].get(fy)
        return float(f["val"]) if f else None

    annual: list[dict] = []
    prev: dict | None = None
    for fy in years:
        rev, gp, oi, ni = (
            val("revenue", fy),
            val("gross_profit", fy),
            val("operating_income", fy),
            val("net_income", fy),
        )
        ocf, capex = val("operating_cash_flow", fy), val("capex", fy)
        fcf = (
            ocf - abs(capex)
            if ocf is not None and capex is not None
            else (ocf if ocf is not None and capex is None else None)
        )
        assets, liab, eq, ltd, cash = (
            val("total_assets", fy),
            val("total_liabilities", fy),
            val("equity", fy),
            val("long_term_debt", fy),
            val("cash", fy),
        )
        eps, shares, interest, divs = (
            val("eps_diluted", fy),
            val("diluted_shares", fy),
            val("interest_expense", fy),
            val("dividends_paid", fy),
        )
        sbc, ar, inv, gw = (
            val("share_based_compensation", fy),
            val("accounts_receivable", fy),
            val("inventory", fy),
            val("goodwill", fy),
        )
        cur_assets, cur_liab, da = (
            val("current_assets", fy),
            val("current_liabilities", fy),
            val("depreciation_amortization", fy),
        )
        cogs = rev - gp if rev is not None and gp is not None else None
        end_fact = series["revenue"].get(fy) or series["net_income"].get(fy) or {}
        row = {
            "fiscal_year": fy,
            "period_end": end_fact.get("end"),
            "revenue": _r2(rev),
            "gross_profit": _r2(gp),
            "operating_income": _r2(oi),
            "net_income": _r2(ni),
            "operating_cash_flow": _r2(ocf),
            "capex": _r2(abs(capex)) if capex is not None else None,
            "free_cash_flow": _r2(fcf),
            "total_assets": _r2(assets),
            "total_liabilities": _r2(liab),
            "equity": _r2(eq),
            "long_term_debt": _r2(ltd),
            "cash": _r2(cash),
            "net_debt": _r2(ltd - cash) if ltd is not None and cash is not None else None,
            "dividends_paid": _r2(abs(divs)) if divs is not None else None,
            "eps_diluted": _r4(eps),
            "diluted_shares": shares,
            "interest_expense": _r2(abs(interest)) if interest is not None else None,
            "gross_margin": _r4(_div(gp, rev)),
            "operating_margin": _r4(_div(oi, rev)),
            "net_margin": _r4(_div(ni, rev)),
            "fcf_margin": _r4(_div(fcf, rev)),
            "cash_conversion": _r4(_div(fcf, ni)) if ni and ni > 0 else None,
            "roe": _r4(_div(ni, eq)) if eq and eq > 0 else None,
            "roa": _r4(_div(ni, assets)),
            "debt_to_equity": _r4(_div(ltd, eq)) if eq and eq > 0 else None,
            "interest_coverage": _r4(_div(oi, abs(interest))) if interest else None,
            "revenue_growth": _r4(_growth(rev, prev["_rev"] if prev else None)),
            "eps_growth": _r4(_growth(eps, prev["_eps"] if prev else None)),
            "sbc": _r2(sbc),
            "sbc_pct_revenue": _r4(_div(sbc, rev)),
            "sbc_vs_fcf": _r2(sbc - fcf) if sbc is not None and fcf is not None else None,
            "dso": _r4(_days(ar, rev)),
            "dio": _r4(_days(inv, cogs)),
            "goodwill_pct_assets": _r4(_div(gw, assets)),
            "current_assets": _r2(cur_assets),
            "current_liabilities": _r2(cur_liab),
            "current_ratio": _r4(_div(cur_assets, cur_liab)) if cur_liab else None,
            "depreciation_amortization": _r2(abs(da)) if da is not None else None,
            "gain_on_property_sales": _r2(val("gain_on_property_sales", fy)),
            "_rev": rev,
            "_eps": eps,
            "_fcf": fcf,
            "_ni": ni,
            "_ocf": ocf,
            "_shares": shares,
            "_om": _div(oi, rev),
            "_ar": ar,
            "_inv": inv,
        }
        annual.append(row)
        prev = row

    first, last = annual[0], annual[-1]
    span = len(annual) - 1
    growth = {
        "years": span,
        "revenue_cagr": _r4(_cagr(first["_rev"], last["_rev"], span)),
        "net_income_cagr": _r4(_cagr(first["_ni"], last["_ni"], span)),
        "fcf_cagr": _r4(_cagr(first["_fcf"], last["_fcf"], span)),
        "eps_cagr": _r4(_cagr(first["_eps"], last["_eps"], span)),
        "diluted_shares_cagr": _r4(_cagr(first["_shares"], last["_shares"], span)),
    }

    def latest_value(key: str) -> float | None:
        return next((r[key] for r in reversed(annual) if r.get(key) is not None), None)

    share_growth = growth["diluted_shares_cagr"]
    om_first = next((r["_om"] for r in annual if r["_om"] is not None), None)
    om_last = latest_value("_om")
    fcfs = [r["_fcf"] for r in annual if r["_fcf"] is not None]
    checks_raw = [
        ("revenue growing", latest_value("revenue_growth"), lambda v: v > 0),
        ("fcf conversion above 0.8", latest_value("cash_conversion"), lambda v: v >= 0.8),
        ("share count not rising", share_growth, lambda v: v <= 0.02),
        ("debt to equity below 1", latest_value("debt_to_equity"), lambda v: v < 1),
        ("roe above 10%", latest_value("roe"), lambda v: v > 0.10),
        (
            "margins stable or rising",
            (om_last - om_first) if om_first is not None and om_last is not None else None,
            lambda v: v >= -0.02,
        ),
        ("interest coverage above 5", latest_value("interest_coverage"), lambda v: v > 5),
        ("positive free cash flow every year", min(fcfs) if fcfs else None, lambda v: v > 0),
    ]
    checks = [
        {"check": name, "passed": bool(test(v)), "value": _r4(v)}
        for name, v, test in checks_raw
        if v is not None
    ]
    quality = {
        "score": sum(1 for c in checks if c["passed"]),
        "out_of": len(checks),
        "checks": checks,
    }

    flags: list[dict] = []
    missing = [m for m in _CORE if not series[m]]
    if missing:
        labels = [_LABELS[m] for m in missing]
        shown = ", ".join(labels[:3]) + (
            f" (and {len(labels) - 3} more)" if len(labels) > 3 else ""
        )
        flags.append({"code": "MISSING_DATA", "message": f"no annual values for: {shown}"})
    if used.get("revenue") == _BANK_REVENUE_CONCEPT:
        flags.append(
            {
                "code": "BANK_REVENUE_PROXY",
                "message": f"revenue is {_BANK_REVENUE_CONCEPT} (gross interest and dividend "
                "income, before interest expense), not a net revenue figure; margins and "
                "DSO are computed on that base",
            }
        )
    if last["revenue_growth"] is not None and last["revenue_growth"] < -0.05:
        rev_drop = round(-last["revenue_growth"] * 100, 1)
        flags.append(
            {
                "code": "REVENUE_DECLINE",
                "message": f"revenue fell {rev_drop}% in fiscal {last['fiscal_year']}",
            }
        )
    if last["_fcf"] is not None and last["_fcf"] < 0:
        flags.append(
            {
                "code": "NEGATIVE_FCF",
                "message": f"free cash flow was negative in fiscal {last['fiscal_year']} "
                f"({last['free_cash_flow']})",
            }
        )
    dilution = (
        round((last["_shares"] / annual[-2]["_shares"] - 1) * 100, 1)
        if len(annual) > 1 and last["_shares"] and annual[-2]["_shares"]
        else None
    )
    if (
        len(annual) > 1
        and last["_shares"]
        and annual[-2]["_shares"]
        and last["_shares"] / annual[-2]["_shares"] - 1 > 0.05
    ):
        flags.append(
            {
                "code": "DILUTION",
                "message": f"diluted share count rose {dilution}% in fiscal {last['fiscal_year']}",
            }
        )
    if last["debt_to_equity"] is not None and last["debt_to_equity"] > 1:
        flags.append(
            {"code": "LEVERAGE", "message": f"long-term debt is {last['debt_to_equity']}x equity"}
        )

    # --- red-flag screens (additive; appended after the flags above) ---
    sbc_pct = last["sbc_pct_revenue"]
    sbc_over_fcf = last["sbc_vs_fcf"]
    pct_fired = sbc_pct is not None and sbc_pct > 0.10
    fcf_fired = sbc_over_fcf is not None and sbc_over_fcf > 0
    if pct_fired or fcf_fired:
        if pct_fired:
            sbc_msg = f"stock-based compensation is {round(sbc_pct * 100, 1)}% of revenue"
            if fcf_fired:
                sbc_msg += " (and exceeds free cash flow)"
        else:
            sbc_msg = "stock-based compensation exceeds free cash flow"
        flags.append({"code": "SBC_HEAVY", "message": sbc_msg})

    ar_cagr, rev_cagr_for_ar = _windowed_cagr(annual, "_ar", "_rev")
    if ar_cagr is not None and rev_cagr_for_ar is not None and ar_cagr > rev_cagr_for_ar + 0.10:
        flags.append(
            {
                "code": "RECEIVABLES_BUILDING",
                "message": f"receivables grew {round(ar_cagr * 100, 1)}%/yr vs revenue "
                f"{round(rev_cagr_for_ar * 100, 1)}%/yr",
            }
        )

    dso_first = next((r["dso"] for r in annual if r["dso"] is not None), None)
    dso_last = next((r["dso"] for r in reversed(annual) if r["dso"] is not None), None)
    if dso_first is not None and dso_last is not None and dso_last - dso_first > 15:
        flags.append(
            {
                "code": "DSO_RISING",
                "message": f"DSO widened from {round(dso_first, 1)} to {round(dso_last, 1)} days",
            }
        )

    inv_cagr, rev_cagr_for_inv = _windowed_cagr(annual, "_inv", "_rev", "dio")
    if inv_cagr is not None and rev_cagr_for_inv is not None and inv_cagr > rev_cagr_for_inv + 0.10:
        flags.append(
            {
                "code": "INVENTORY_BUILDING",
                "message": f"inventory grew {round(inv_cagr * 100, 1)}%/yr vs revenue "
                f"{round(rev_cagr_for_inv * 100, 1)}%/yr",
            }
        )

    if last["goodwill_pct_assets"] is not None and last["goodwill_pct_assets"] > 0.30:
        flags.append(
            {
                "code": "GOODWILL_HEAVY",
                "message": f"goodwill is {round(last['goodwill_pct_assets'] * 100, 1)}% "
                "of total assets",
            }
        )

    ni_cagr, ocf_cagr = _windowed_cagr(annual, "_ni", "_ocf")
    if ni_cagr is not None and ocf_cagr is not None and ni_cagr > ocf_cagr + 0.15:
        flags.append(
            {
                "code": "ACCRUALS",
                "message": "net income growth outpaced operating cash flow growth "
                f"({round(ni_cagr * 100, 1)}% vs {round(ocf_cagr * 100, 1)}%)",
            }
        )

    for r in annual:
        for k in [k for k in r if k.startswith("_")]:
            r.pop(k)

    result = {
        "company": facts.get("entityName"),
        "concepts_used": used,
        "annual": annual,
        "latest_quarter": _latest_quarter(gaap),
        "growth": growth,
        "quality": quality,
        "filings": _filings(params.get("filings") or [], params.get("cik"), params.get("as_of")),
        "flags": flags,
    }

    quarters_raw = params.get("quarters")
    if quarters_raw is not None:
        try:
            n = int(quarters_raw)
        except (TypeError, ValueError):
            raise ValueError("quarters must be an integer >= 2") from None
        if n < 2:
            raise ValueError("quarters must be an integer >= 2")
        rows, ttm = _quarterly_table(gaap, n)
        result["quarterly"] = rows
        result["ttm"] = ttm
    return result


def main() -> None:
    """Read JSON params from stdin, write the fundamentals view (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_fundamentals(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
