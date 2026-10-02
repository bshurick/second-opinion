from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json
from second_opinion import edgar


def _fact(fy, val, form="10-K", fp="FY"):
    return {"fy": fy, "fp": fp, "form": form, "val": val, "end": f"{fy}-12-31", "filed": f"{fy + 1}-02-15"}


FACTS = {"entityName": "Apple Inc.", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [_fact(2024, 100.0), _fact(2025, 110.0)]}}, "NetIncomeLoss": {"units": {"USD": [_fact(2024, 10.0), _fact(2025, 12.0)]}}}}}
FILINGS = [{"form": "10-K", "filingDate": "2026-02-01", "accessionNumber": "0000320193-26-000001", "primaryDocument": "aapl.htm", "items": ""}, {"form": "4", "filingDate": "2026-08-01", "accessionNumber": "0000320193-26-000002", "primaryDocument": "f4.xml", "items": ""}]


@pytest.fixture
def fake_edgar(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setenv("EDGAR_USER_AGENT", "test-suite test@example.com")
    calls: list[str] = []
    monkeypatch.setattr(edgar, "cik_for", lambda s: (calls.append(f"cik:{s}"), (320193, "Apple Inc."))[1])
    monkeypatch.setattr(edgar, "submissions", lambda cik: (calls.append(f"subs:{cik}"), {"cik": cik, "name": "Apple Inc.", "filings": FILINGS})[1])
    monkeypatch.setattr(edgar, "company_facts", lambda cik: (calls.append(f"facts:{cik}"), FACTS)[1])
    return calls


def test_edgar_script_builds_fundamentals_and_filings(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["aapl", "--years", "2", "--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["symbol"] == "AAPL" and out["cik"] == 320193 and out["company"] == "Apple Inc."
    assert [r["fiscal_year"] for r in out["annual"]] == [2024, 2025] and out["annual"][-1]["revenue_growth"] == 0.1
    assert out["filings"]["latest_10k"]["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/aapl.htm"
    assert out["filings"]["insider_filings_90d"] == 1 and out["filings"]["as_of"] == "2026-09-04"
    assert out["sources"] == {"facts": "sec-edgar", "filings": "sec-edgar", "user_agent_is_default": False}
    assert fake_edgar == ["cik:AAPL", "subs:320193", "facts:320193"]


def test_edgar_script_filings_only(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["AAPL", "--filings-only"], capsys)
    assert rc == 0 and "annual" not in out and out["filings"]["counts"] == {"10-K": 1, "4": 1}
    assert fake_edgar == ["cik:AAPL", "subs:320193"]


def test_edgar_script_default_user_agent_flag(fake_edgar, monkeypatch, capsys) -> None:
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["AAPL", "--filings-only"], capsys)
    assert rc == 0 and out["sources"]["user_agent_is_default"] is True
    assert {"code": "DEFAULT_USER_AGENT", "message": "set EDGAR_USER_AGENT to 'app-name contact@email' as the SEC requires; the default placeholder may be blocked"} in out["flags"]


def test_fundamentals_math_script_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"facts": FACTS, "years": 2})))
    load_script("fundamental-research/scripts/fundamentals.py").main()
    assert json.loads(capsys.readouterr().out)["annual"][-1]["revenue"] == 110.0


# --- Growth flags use each series' own first/last
# available (non-null) values, not the table's fixed endpoints.


def test_fundamentals_receivables_building_uses_first_last_available_ar() -> None:
    years = [2021, 2022, 2023, 2024, 2025]
    rev = {y: 1000 * 1.1 ** (y - 2021) for y in years}
    facts = {
        "entityName": "Growth Co",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [_fact(y, v) for y, v in rev.items()]}},
                "NetIncomeLoss": {"units": {"USD": [_fact(y, v * 0.1) for y, v in rev.items()]}},
                # no AR fact at all for fy2021; present and growing 1.5x/yr afterwards,
                # far outpacing revenue's steady 10%/yr
                "AccountsReceivableNetCurrent": {
                    "units": {
                        "USD": [
                            _fact(2022, 100.0),
                            _fact(2023, 150.0),
                            _fact(2024, 225.0),
                            _fact(2025, 337.5),
                        ]
                    }
                },
            }
        },
    }
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    out = mod.run_fundamentals({"facts": facts, "years": 5})
    assert out["annual"][0]["dso"] is None  # fy2021: AR not tagged
    codes = {f["code"] for f in out["flags"]}
    assert "RECEIVABLES_BUILDING" in codes and "DSO_RISING" in codes


# --- Task 15: edgar.py --quarters and --form4 ---

FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument xmlns="http://www.sec.gov/edgar/ownershipdocument">
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>DOE JANE</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>0</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>150.25</value></transactionPricePerShare>
      </transactionAmounts>
      <transactionDate><value>2026-07-30</value></transactionDate>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_edgar_script_form4_absent_no_key(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["aapl", "--years", "2"], capsys)
    assert rc == 0 and "form4" not in out


def test_edgar_script_quarters_flag_adds_quarterly_and_ttm(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["aapl", "--years", "2", "--quarters", "2"], capsys)
    assert rc == 0, out
    assert "quarterly" in out and "ttm" in out


def test_edgar_script_form4_parses_transactions(monkeypatch, fake_edgar, capsys) -> None:
    from second_opinion import edgar as edgar_lib

    filings_with_form4 = FILINGS + [
        {"form": "4", "filingDate": "2026-08-15", "accessionNumber": "0000320193-26-000003", "primaryDocument": "f4b.xml", "items": ""},
    ]
    monkeypatch.setattr(edgar_lib, "submissions", lambda cik: {"cik": cik, "name": "Apple Inc.", "filings": filings_with_form4})
    monkeypatch.setattr(edgar_lib, "document", lambda url: FORM4_XML)
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["aapl", "--filings-only", "--form4", "2"], capsys)
    assert rc == 0, out
    assert out["form4"]["note"] == "non-dispositions are grants/awards, not open-market purchases"
    filings = out["form4"]["filings"]
    assert len(filings) == 2
    f = filings[0]
    assert f["filing_date"] == "2026-08-15" and f["reporting_owner"] == "DOE JANE" and f["role"] == "director"
    assert f["transactions"][0] == {"code": "S", "shares": 1000.0, "price": 150.25, "date": "2026-07-30", "acquired": False}


def test_edgar_script_form4_default_count_is_five(monkeypatch, fake_edgar, capsys) -> None:
    from second_opinion import edgar as edgar_lib

    many = [
        {"form": "4", "filingDate": f"2026-08-{d:02d}", "accessionNumber": f"0000320193-26-0000{d}", "primaryDocument": "f4.xml", "items": ""}
        for d in range(1, 8)
    ]
    monkeypatch.setattr(edgar_lib, "submissions", lambda cik: {"cik": cik, "name": "Apple Inc.", "filings": many})
    monkeypatch.setattr(edgar_lib, "document", lambda url: FORM4_XML)
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["aapl", "--filings-only", "--form4"], capsys)
    assert rc == 0 and len(out["form4"]["filings"]) == 5  # default count, most recent first


def test_edgar_script_form4_count_capped_at_ten(monkeypatch, fake_edgar, capsys) -> None:
    from second_opinion import edgar as edgar_lib

    many = [
        {"form": "4", "filingDate": f"2026-01-{d:02d}", "accessionNumber": f"0000320193-26-00{d:02d}0", "primaryDocument": "f4.xml", "items": ""}
        for d in range(1, 21)
    ]
    monkeypatch.setattr(edgar_lib, "submissions", lambda cik: {"cik": cik, "name": "Apple Inc.", "filings": many})
    monkeypatch.setattr(edgar_lib, "document", lambda url: FORM4_XML)
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["aapl", "--filings-only", "--form4", "50"], capsys)
    assert rc == 0 and len(out["form4"]["filings"]) == 10


def test_edgar_script_form4_degrades_on_bad_xml_and_fetch_failure(monkeypatch, fake_edgar, capsys) -> None:
    from second_opinion import edgar as edgar_lib
    from second_opinion.errors import ApiError

    filings_with_form4 = FILINGS + [
        {"form": "4", "filingDate": "2026-08-10", "accessionNumber": "0000320193-26-000004", "primaryDocument": "bad.xml", "items": ""},
        {"form": "4", "filingDate": "2026-08-05", "accessionNumber": "0000320193-26-000005", "primaryDocument": "gone.xml", "items": ""},
    ]
    monkeypatch.setattr(edgar_lib, "submissions", lambda cik: {"cik": cik, "name": "Apple Inc.", "filings": filings_with_form4})

    def fake_document(url: str) -> str:
        if "gone.xml" in url:
            raise ApiError("HTTP 404", code="EDGAR_HTTP", http_status=404)
        if "bad.xml" in url:
            return "<not-xml"
        return FORM4_XML

    monkeypatch.setattr(edgar_lib, "document", fake_document)
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["aapl", "--filings-only", "--form4", "5"], capsys)
    assert rc == 0, out
    filings = out["form4"]["filings"]
    dates = [f["filing_date"] for f in filings]
    assert "2026-08-05" not in dates  # fetch failure: skipped, run continues
    bad = next(f for f in filings if f["filing_date"] == "2026-08-10")
    assert bad == {"filing_date": "2026-08-10", "error": "unparseable", "snippet": "<not-xml"}


def test_fundamentals_balance_sheet_liquidity_and_da_columns() -> None:
    """Graham's tests need current assets/liabilities; owner earnings need D&A."""
    facts = {
        "entityName": "X",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [_fact(2024, 100.0), _fact(2025, 110.0)]}},
                "NetIncomeLoss": {"units": {"USD": [_fact(2024, 10.0), _fact(2025, 12.0)]}},
                "AssetsCurrent": {"units": {"USD": [_fact(2024, 50.0), _fact(2025, 60.0)]}},
                "LiabilitiesCurrent": {"units": {"USD": [_fact(2024, 25.0), _fact(2025, 20.0)]}},
                "DepreciationDepletionAndAmortization": {"units": {"USD": [_fact(2024, 4.0), _fact(2025, 4.5)]}},
            }
        },
    }
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    rows = mod.run_fundamentals({"facts": facts, "years": 2})["annual"]
    assert [(r["current_assets"], r["current_liabilities"], r["current_ratio"], r["depreciation_amortization"]) for r in rows] == [
        (50.0, 25.0, 2.0, 4.0),
        (60.0, 20.0, 3.0, 4.5),
    ]
    # Missing concepts stay null instead of failing the table.
    bare = mod.run_fundamentals({"facts": FACTS, "years": 2})["annual"][-1]
    assert (bare["current_assets"], bare["current_ratio"], bare["depreciation_amortization"]) == (None, None, None)


def test_total_liabilities_derived_from_assets_minus_equity_when_untagged() -> None:
    """Many filers (Coca-Cola among them) never tag `Liabilities`; assets minus equity is the standard derivation."""
    facts = {
        "entityName": "X",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [_fact(2024, 100.0), _fact(2025, 110.0)]}},
                "NetIncomeLoss": {"units": {"USD": [_fact(2024, 10.0), _fact(2025, 12.0)]}},
                "Assets": {"units": {"USD": [_fact(2024, 500.0), _fact(2025, 560.0)]}},
                "StockholdersEquity": {"units": {"USD": [_fact(2024, 200.0), _fact(2025, 230.0)]}},
            }
        },
    }
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    out = mod.run_fundamentals({"facts": facts, "years": 2})
    assert [r["total_liabilities"] for r in out["annual"]] == [300.0, 330.0]
    assert out["concepts_used"]["total_liabilities"] == "Assets - StockholdersEquity (derived)"
    # A tagged Liabilities concept still wins over the derivation.
    facts["facts"]["us-gaap"]["Liabilities"] = {"units": {"USD": [_fact(2024, 290.0), _fact(2025, 320.0)]}}
    out = mod.run_fundamentals({"facts": facts, "years": 2})
    assert [r["total_liabilities"] for r in out["annual"]] == [290.0, 320.0] and out["concepts_used"]["total_liabilities"] == "Liabilities"


# --- 10-K fp=FY quarterlies, 10-Q year-to-date facts, aliases, Form 4 XSL paths ---


def _dfact(fy, start, end, val, form="10-K", fp="FY", filed=None):
    """A duration fact the way companyfacts serves it (start + end)."""
    return {"fy": fy, "fp": fp, "form": form, "val": val, "start": start, "end": end, "filed": filed or f"{fy + 1}-02-15"}


def _ctsh_shape() -> dict:
    """One 10-K (fy=2018) whose annual AND embedded quarterly facts all carry fp=FY with the same
    filed date, plus the prior-year comparative under the same fy label — the shape that made
    quarterly values land in the annual table."""
    tenk_2018 = dict(form="10-K", fp="FY", filed="2019-02-15")
    tenk_2017 = dict(form="10-K", fp="FY", filed="2018-02-15")
    rev = [
        _dfact(2018, "2018-01-01", "2018-03-31", 3.9e9, **tenk_2018),
        _dfact(2018, "2018-01-01", "2018-12-31", 16.1e9, **tenk_2018),
        _dfact(2018, "2018-04-01", "2018-06-30", 4.0e9, **tenk_2018),
        _dfact(2018, "2018-07-01", "2018-09-30", 4.1e9, **tenk_2018),
        _dfact(2018, "2018-10-01", "2018-12-31", 4.1e9, **tenk_2018),
        _dfact(2018, "2017-01-01", "2017-12-31", 14.8e9, **tenk_2018),  # comparative, fy label 2018
        _dfact(2017, "2017-01-01", "2017-12-31", 14.8e9, **tenk_2017),
        _dfact(2017, "2017-10-01", "2017-12-31", 3.8e9, **tenk_2017),
    ]
    ni = [
        _dfact(2018, "2018-01-01", "2018-03-31", 0.52e9, **tenk_2018),
        _dfact(2018, "2018-01-01", "2018-12-31", 2.1e9, **tenk_2018),
        _dfact(2018, "2018-10-01", "2018-12-31", 0.65e9, **tenk_2018),
        _dfact(2017, "2017-01-01", "2017-12-31", 1.5e9, **tenk_2017),
    ]
    eps = [
        _dfact(2018, "2018-01-01", "2018-03-31", 0.88, **tenk_2018),
        _dfact(2018, "2018-01-01", "2018-12-31", 3.60, **tenk_2018),
        _dfact(2017, "2017-01-01", "2017-12-31", 2.53, **tenk_2017),
    ]
    # balance-sheet instants: no start; the 10-K carries both year-ends under fy=2018
    assets = [
        {"fy": 2018, "fp": "FY", "form": "10-K", "val": 15.0e9, "end": "2018-12-31", "filed": "2019-02-15"},
        {"fy": 2018, "fp": "FY", "form": "10-K", "val": 13.0e9, "end": "2017-12-31", "filed": "2019-02-15"},
        {"fy": 2017, "fp": "FY", "form": "10-K", "val": 13.0e9, "end": "2017-12-31", "filed": "2018-02-15"},
    ]
    return {
        "entityName": "Ten-K Co",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": rev}},
                "NetIncomeLoss": {"units": {"USD": ni}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
                "Assets": {"units": {"USD": assets}},
            }
        },
    }


def test_annual_row_picks_the_twelve_month_fact_not_an_embedded_quarter() -> None:
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    out = mod.run_fundamentals({"facts": _ctsh_shape(), "years": 2})
    rows = {r["fiscal_year"]: r for r in out["annual"]}
    assert set(rows) == {2017, 2018}
    r18 = rows[2018]
    assert (r18["revenue"], r18["net_income"], r18["eps_diluted"]) == (16.1e9, 2.1e9, 3.6)
    assert r18["period_end"] == "2018-12-31" and r18["total_assets"] == 15.0e9
    r17 = rows[2017]
    assert (r17["revenue"], r17["net_income"], r17["eps_diluted"], r17["total_assets"]) == (14.8e9, 1.5e9, 2.53, 13.0e9)
    assert r18["revenue_growth"] == round(16.1 / 14.8 - 1, 4)


def test_annual_selection_prefers_latest_filed_then_longest_span() -> None:
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    facts = _ctsh_shape()
    g = facts["facts"]["us-gaap"]
    # a 10-K/A restates 2018 revenue later; a 53-week (371-day) year still counts as annual
    g["Revenues"]["units"]["USD"].append(_dfact(2018, "2018-01-01", "2018-12-31", 16.3e9, form="10-K/A", filed="2019-05-01"))
    out = mod.run_fundamentals({"facts": facts, "years": 2})
    assert out["annual"][-1]["revenue"] == 16.3e9
    for order in (1, -1):  # same end year and filed date: the longer duration wins regardless of order
        rows = [
            _dfact(2024, "2024-01-01", "2024-12-28", 100.0, filed="2025-02-20"),  # 362 days
            _dfact(2024, "2023-12-24", "2024-12-28", 101.0, filed="2025-02-20"),  # 370 days (53-week year)
        ][::order]
        picked, _ = mod._annual({"Revenues": {"units": {"USD": rows}}}, "revenue")
        assert picked[2024]["val"] == 101.0
    picked, _ = mod._annual({"Revenues": {"units": {"USD": [
        _dfact(2024, "2024-07-01", "2024-12-31", 50.0, filed="2025-02-20"),  # 6-month: not annual
        _dfact(2024, "2024-01-01", "2024-12-31", 100.0, filed="2025-02-20"),
    ]}}}, "revenue")
    assert picked[2024]["val"] == 100.0


def _ytd_shape() -> dict:
    """Two fiscal years of 10-Qs that carry year-to-date facts under fp=Q2/Q3 alongside the
    discrete quarter, and a 10-K whose ~90-day fp=FY fact is the discrete Q4."""
    rev, ni = [], []

    def add(fy, start, end, val, form, fp, filed):
        rev.append(_dfact(fy, start, end, val, form=form, fp=fp, filed=filed))
        ni.append(_dfact(fy, start, end, val / 10, form=form, fp=fp, filed=filed))

    for fy, base in ((2024, 100.0), (2025, 110.0)):
        q = [base, base + 2, base + 4, base + 6]
        y = str(fy)
        add(fy, f"{y}-01-01", f"{y}-03-31", q[0], "10-Q", "Q1", f"{y}-05-05")
        add(fy, f"{y}-04-01", f"{y}-06-30", q[1], "10-Q", "Q2", f"{y}-08-05")
        add(fy, f"{y}-01-01", f"{y}-06-30", q[0] + q[1], "10-Q", "Q2", f"{y}-08-05")  # YTD 6 months
        add(fy, f"{y}-07-01", f"{y}-09-30", q[2], "10-Q", "Q3", f"{y}-11-05")
        add(fy, f"{y}-01-01", f"{y}-09-30", q[0] + q[1] + q[2], "10-Q", "Q3", f"{y}-11-05")  # YTD 9 months
        add(fy, f"{y}-10-01", f"{y}-12-31", q[3], "10-K", "FY", f"{fy + 1}-02-20")  # discrete Q4, fp=FY
        add(fy, f"{y}-01-01", f"{y}-12-31", sum(q), "10-K", "FY", f"{fy + 1}-02-20")  # annual
    return {"entityName": "YTD Co", "facts": {"us-gaap": {"Revenues": {"units": {"USD": rev}}, "NetIncomeLoss": {"units": {"USD": ni}}}}}


def test_quarterly_ttm_ignores_year_to_date_facts_and_takes_q4_from_the_10k() -> None:
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    out = mod.run_fundamentals({"facts": _ytd_shape(), "years": 2, "quarters": 8})
    q = out["quarterly"]
    assert [(r["fiscal_year"], r["period_end"], r["revenue"]) for r in q] == [
        (2024, "2024-03-31", 100.0),
        (2024, "2024-06-30", 102.0),
        (2024, "2024-09-30", 104.0),
        (2024, "2024-12-31", 106.0),
        (2025, "2025-03-31", 110.0),
        (2025, "2025-06-30", 112.0),
        (2025, "2025-09-30", 114.0),
        (2025, "2025-12-31", 116.0),
    ]
    assert out["ttm"]["revenue"] == 110.0 + 112.0 + 114.0 + 116.0  # four discrete quarters, no YTD double count
    assert out["ttm"]["net_income"] == round((110.0 + 112.0 + 114.0 + 116.0) / 10, 2)
    assert out["ttm"]["revenue_ttm_yoy"] == round(452.0 / 412.0 - 1, 4)
    assert q[5]["revenue_yoy"] == round(112.0 / 102.0 - 1, 4)  # vs the quarter ending 2024-06-30
    assert q[1]["revenue_yoy"] is None
    # the annual table is untouched by the quarterly facts
    assert [r["revenue"] for r in out["annual"]] == [412.0, 452.0]
    assert out["latest_quarter"] == {"period": "2025-09-30", "fiscal_period": "Q3", "fiscal_year": 2025, "revenue": 114.0, "net_income": 11.4}


def test_quarterly_ttm_null_when_a_quarter_is_missing() -> None:
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    facts = _ytd_shape()
    for concept in ("Revenues", "NetIncomeLoss"):
        rows = facts["facts"]["us-gaap"][concept]["units"]["USD"]
        rows[:] = [f for f in rows if f["end"] != "2025-06-30"]
    out = mod.run_fundamentals({"facts": facts, "years": 2, "quarters": 4})
    assert out["ttm"]["revenue"] is None  # the last four ends span 15 months, not four consecutive quarters


def test_capex_and_bank_revenue_aliases() -> None:
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    assert mod._CONCEPTS["capex"][-1] == "PaymentsToAcquireRealEstate"
    assert {"PaymentsToAcquireOilAndGasPropertyAndEquipment", "PaymentsToExploreAndDevelopOilAndGasProperties", "PaymentsForCapitalImprovements"} <= set(mod._CONCEPTS["capex"])
    assert "InterestIncomeExpenseNet" not in mod._CONCEPTS["revenue"]
    usd = lambda a, b: {"units": {"USD": [_fact(2024, a), _fact(2025, b)]}}  # noqa: E731
    reit = {"entityName": "REIT", "facts": {"us-gaap": {
        "Revenues": usd(100.0, 110.0), "NetIncomeLoss": usd(10.0, 12.0),
        "NetCashProvidedByUsedInOperatingActivities": usd(30.0, 33.0),
        "PaymentsToAcquireRealEstate": usd(50.0, 55.0),
    }}}
    out = mod.run_fundamentals({"facts": reit, "years": 2})
    assert out["concepts_used"]["capex"] == "PaymentsToAcquireRealEstate" and out["annual"][-1]["free_cash_flow"] == -22.0
    reit["facts"]["us-gaap"]["PaymentsForCapitalImprovements"] = usd(5.0, 6.0)
    assert mod.run_fundamentals({"facts": reit, "years": 2})["concepts_used"]["capex"] == "PaymentsForCapitalImprovements"
    bank = {"entityName": "Bank", "facts": {"us-gaap": {
        "InterestAndDividendIncomeOperating": usd(400.0, 480.0), "NetIncomeLoss": usd(90.0, 100.0),
    }}}
    out = mod.run_fundamentals({"facts": bank, "years": 2})
    assert out["concepts_used"]["revenue"] == "InterestAndDividendIncomeOperating" and out["annual"][-1]["revenue"] == 480.0
    assert [f["code"] for f in out["flags"]][:2] == ["MISSING_DATA", "BANK_REVENUE_PROXY"]
    bank["facts"]["us-gaap"]["RevenuesNetOfInterestExpense"] = usd(300.0, 330.0)
    out = mod.run_fundamentals({"facts": bank, "years": 2})
    assert out["concepts_used"]["revenue"] == "RevenuesNetOfInterestExpense"
    assert "BANK_REVENUE_PROXY" not in {f["code"] for f in out["flags"]}


def test_form4_fetch_strips_xsl_directory_from_primary_document(monkeypatch, fake_edgar, capsys) -> None:
    from second_opinion import edgar as edgar_lib

    mod = load_script("fundamental-research/scripts/edgar.py")
    assert mod._raw_document_name("xslF345X06/wk-form4_1788552205.xml") == "wk-form4_1788552205.xml"
    assert mod._raw_document_name("xslF345X05/form4.xml") == "form4.xml"
    assert mod._raw_document_name("f4.xml") == "f4.xml"
    assert mod._raw_document_name("sub/dir/f4.xml") == "sub/dir/f4.xml"  # only an xsl... first segment is dropped
    filings = [{"form": "4", "filingDate": "2026-08-15", "accessionNumber": "0000320193-26-000003", "primaryDocument": "xslF345X06/wk-form4_1788552205.xml", "items": ""}]
    monkeypatch.setattr(edgar_lib, "submissions", lambda cik: {"cik": cik, "name": "Apple Inc.", "filings": filings})
    seen: list[str] = []
    monkeypatch.setattr(edgar_lib, "document", lambda url: (seen.append(url), FORM4_XML)[1])
    rc, out = run_json(mod, ["aapl", "--filings-only", "--form4", "1"], capsys)
    assert rc == 0, out
    assert seen == ["https://www.sec.gov/Archives/edgar/data/320193/000032019326000003/wk-form4_1788552205.xml"]
    assert out["form4"]["filings"][0]["reporting_owner"] == "DOE JANE"
    # the filings index link keeps the rendered (human-readable) path
    assert out["filings"]["recent_form4"][0]["url"].endswith("/xslF345X06/wk-form4_1788552205.xml")


def test_form4_unparseable_record_carries_a_response_snippet(monkeypatch, fake_edgar, capsys) -> None:
    from second_opinion import edgar as edgar_lib

    html = "<!DOCTYPE html><html><head><title>Form 4</title></head><body>" + "x" * 200 + "</body></html>"
    monkeypatch.setattr(edgar_lib, "document", lambda url: html)
    rc, out = run_json(load_script("fundamental-research/scripts/edgar.py"), ["aapl", "--filings-only", "--form4", "1"], capsys)
    assert rc == 0, out
    rec = out["form4"]["filings"][0]
    assert rec["error"] == "unparseable" and rec["snippet"] == html[:80] and len(rec["snippet"]) == 80


def _next_day(iso: str) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(iso) + timedelta(days=1)).isoformat()


def _aso_shape() -> dict:
    """Retailer with a fiscal year ending ~Feb 1: 10-Qs carry the discrete quarter plus the
    year-to-date fact; the 10-K tags only the ~12-month annual figure (no discrete Q4)."""
    rev, ni = [], []

    def add(fy, start, end, val, form, fp, filed):
        rev.append(_dfact(fy, start, end, val, form=form, fp=fp, filed=filed))
        ni.append(_dfact(fy, start, end, val / 20, form=form, fp=fp, filed=filed))

    # (fy, fiscal-year start, Q1 end, Q2 end, Q3 end, annual end, quarter revenues)
    years = [
        (2023, "2023-01-29", "2023-04-29", "2023-07-29", "2023-10-28", "2024-02-03", [1400.0, 1580.0, 1400.0, 1800.0]),
        (2024, "2024-02-04", "2024-05-04", "2024-08-03", "2024-11-02", "2025-02-01", [1360.0, 1550.0, 1340.0, 1680.0]),
    ]
    for fy, y0, q1, q2, q3, ye, q in years:
        add(fy, y0, q1, q[0], "10-Q", "Q1", f"{fy}-06-05")
        add(fy, _next_day(q1), q2, q[1], "10-Q", "Q2", f"{fy}-09-05")
        add(fy, y0, q2, q[0] + q[1], "10-Q", "Q2", f"{fy}-09-05")  # YTD 6 months
        add(fy, _next_day(q2), q3, q[2], "10-Q", "Q3", f"{fy}-12-05")
        add(fy, y0, q3, q[0] + q[1] + q[2], "10-Q", "Q3", f"{fy}-12-05")  # YTD 9 months
        add(fy, y0, ye, sum(q), "10-K", "FY", f"{fy + 1}-03-25")  # annual only: no discrete Q4
    return {"entityName": "Retail Co", "facts": {"us-gaap": {"Revenues": {"units": {"USD": rev}}, "NetIncomeLoss": {"units": {"USD": ni}}}}}


def test_quarterly_derives_q4_from_annual_minus_nine_month_ytd_when_the_10k_tags_none() -> None:
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    out = mod.run_fundamentals({"facts": _aso_shape(), "years": 2, "quarters": 8})
    q = out["quarterly"]
    assert [(r["fiscal_year"], r["period_end"], r["revenue"], r["derived"]) for r in q] == [
        (2023, "2023-04-29", 1400.0, False),
        (2023, "2023-07-29", 1580.0, False),
        (2023, "2023-10-28", 1400.0, False),
        (2023, "2024-02-03", 1800.0, True),
        (2024, "2024-05-04", 1360.0, False),
        (2024, "2024-08-03", 1550.0, False),
        (2024, "2024-11-02", 1340.0, False),
        (2024, "2025-02-01", 1680.0, True),
    ]
    assert q[-1]["net_income"] == 84.0 and q[-1]["revenue_yoy"] == round(1680.0 / 1800.0 - 1, 4)
    assert out["ttm"]["revenue"] == 5930.0 == out["annual"][-1]["revenue"]  # TTM at year end == the annual figure
    assert out["ttm"]["net_income"] == 296.5 and out["ttm"]["revenue_ttm_yoy"] == round(5930.0 / 6180.0 - 1, 4)
    assert out["latest_quarter"] == {"period": "2025-02-01", "fiscal_period": "Q4", "fiscal_year": 2024, "revenue": 1680.0, "net_income": 84.0, "derived": True}


def test_discrete_q4_fact_takes_precedence_over_the_derived_one() -> None:
    mod = load_script("fundamental-research/scripts/fundamentals.py")
    facts = _aso_shape()
    g = facts["facts"]["us-gaap"]
    g["Revenues"]["units"]["USD"].append(_dfact(2024, "2024-11-03", "2025-02-01", 1681.0, form="10-K", fp="FY", filed="2025-03-25"))
    out = mod.run_fundamentals({"facts": facts, "years": 2, "quarters": 4})
    last = out["quarterly"][-1]
    assert (last["revenue"], last["net_income"], last["derived"]) == (1681.0, 84.0, True)  # net income still derived
    g["NetIncomeLoss"]["units"]["USD"].append(_dfact(2024, "2024-11-03", "2025-02-01", 84.5, form="10-K", fp="FY", filed="2025-03-25"))
    last = mod.run_fundamentals({"facts": facts, "years": 2, "quarters": 4})["quarterly"][-1]
    assert (last["revenue"], last["net_income"], last["derived"]) == (1681.0, 84.5, False)
    assert "derived" not in mod.run_fundamentals({"facts": facts, "years": 2})["latest_quarter"]
