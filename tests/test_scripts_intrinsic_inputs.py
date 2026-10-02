"""intrinsic-inputs.py: EDGAR annual table + price + FRED yields -> a filled intrinsic.py input."""

from __future__ import annotations

import pytest
from scripts_util import load_script, run_json
from second_opinion import edgar, fred, market
from second_opinion.errors import ApiError


def _fact(fy, val):
    return {"fy": fy, "fp": "FY", "form": "10-K", "val": val, "end": f"{fy}-12-31", "filed": f"{fy + 1}-02-15"}


FACTS = {"entityName": "Coca-Cola", "facts": {"us-gaap": {
    "Revenues": {"units": {"USD": [_fact(2024, 1000.0), _fact(2025, 1100.0)]}},
    "NetIncomeLoss": {"units": {"USD": [_fact(2024, 100.0), _fact(2025, 120.0)]}},
    "AssetsCurrent": {"units": {"USD": [_fact(2024, 300.0), _fact(2025, 340.0)]}},
}}}


@pytest.fixture
def fake_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setenv("EDGAR_USER_AGENT", "test-suite test@example.com")
    calls: list[str] = []
    monkeypatch.setattr(edgar, "cik_for", lambda s: (calls.append(f"cik:{s}"), (21344, "COCA COLA CO"))[1])
    monkeypatch.setattr(edgar, "company_facts", lambda cik: (calls.append(f"facts:{cik}"), FACTS)[1])
    monkeypatch.setattr(edgar, "submissions", lambda cik: (calls.append(f"submissions:{cik}"), {"cik": cik, "sic": "2080", "sic_description": "Beverages", "filings": []})[1])
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: (calls.append(f"quote:{','.join(symbols)}"), [{"symbol": "KO", "price": 62.5, "source": "yahoo"}])[1])
    series = {"AAA": {"series": "AAA", "date": "2026-08-01", "value": 5.12}, "DGS10": {"series": "DGS10", "date": "2026-09-09", "value": 4.18}}
    monkeypatch.setattr(fred, "latest", lambda sid: (calls.append(f"fred:{sid}"), series[sid])[1])
    return calls


def test_builds_intrinsic_input(fake_sources, capsys) -> None:
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), ["ko", "--years", "2"], capsys)
    assert rc == 0, out
    assert out["symbol"] == "KO" and out["cik"] == 21344 and out["company"] == "Coca-Cola"
    assert fake_sources == ["cik:KO", "facts:21344", "submissions:21344", "quote:KO", "fred:AAA", "fred:DGS10"]
    assert out["sic"] == "2080" and out["business_type"] == "industrial"
    assert out["assumptions"]["business_type"] == {"value": "industrial", "source": "SIC 2080 is not a bank, broker, insurer, REIT or utility code (Beverages) -> industrial"}
    inp = out["intrinsic_input"]
    assert [r["fiscal_year"] for r in inp["annual"]] == [2024, 2025]
    assert inp["annual"][-1]["current_assets"] == 340.0 and not any(k.startswith("_") for k in inp["annual"][-1])
    assert inp["price"] == 62.5 and inp["aaa_yield"] == 0.0512 and inp["treasury_10y"] == 0.0418
    assert inp["business_type"] == "industrial"
    assert out["assumptions"]["aaa_yield"] == {"value": 0.0512, "source": "FRED series AAA (Moody's Seasoned Aaa Corporate Bond Yield), 2026-08-01, divided by 100"}
    assert out["assumptions"]["treasury_10y"]["source"].startswith("FRED series DGS10")
    assert out["sources"] == {"financials": "sec-edgar", "price": "yahoo", "yields": "fred", "user_agent_is_default": False}
    assert out["flags"] == []


def test_degrades_when_price_or_fred_fail(fake_sources, monkeypatch, capsys) -> None:
    def boom(*a, **k):
        raise ApiError("down", code="FRED_HTTP")

    monkeypatch.setattr(fred, "latest", boom)
    monkeypatch.setattr(market, "quote", lambda symbols, hub=None: [{"symbol": "KO", "price": None}])
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), ["KO"], capsys)
    assert rc == 0, out
    inp = out["intrinsic_input"]
    assert inp["price"] is None and inp["aaa_yield"] is None and inp["treasury_10y"] is None
    assert {f["code"] for f in out["flags"]} == {"NO_PRICE", "FRED_UNAVAILABLE"}
    assert out["sources"]["yields"] is None


def test_missing_fundamental_research_skill_exits_4(fake_sources, monkeypatch, tmp_path, capsys) -> None:
    mod = load_script("valuation/scripts/intrinsic-inputs.py")
    monkeypatch.setattr(mod, "FUNDAMENTALS_SCRIPT", tmp_path / "missing" / "fundamentals.py")
    rc, out = run_json(mod, ["KO"], capsys)
    assert rc == 4 and out["code"] == "SKILL_MISSING" and "fundamental-research" in out["hint"]


def test_usage(capsys) -> None:
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), [], capsys)
    assert rc == 2
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), ["KO", "--business-type", "bank"], capsys)
    assert rc == 2 and "--business-type" in out["error"]


@pytest.mark.parametrize(
    "sic,expected",
    [
        ("6021", "financial"),     # national commercial banks
        (6020, "financial"),       # range start, as an int
        ("6199", "financial"),     # finance services: range end
        ("6211", "financial"),     # security brokers and dealers
        ("6282", "financial"),     # investment advice
        ("6311", "financial"),     # life insurance
        ("6411", "financial"),     # insurance agents
        ("6798", "reit"),
        ("4911", "utility"),       # electric services
        ("4924", "utility"),       # natural gas distribution
        ("4941", "utility"),       # water supply
        ("4953", "industrial"),    # refuse systems: not a regulated utility
        ("4813", "industrial"),    # telephone
        ("6500", "industrial"),    # real estate operators: not a REIT
        ("6770", "industrial"),    # blank checks
        ("6019", "industrial"),    # just below the bank range
        ("6300", "industrial"),    # between brokers and insurers
        ("2080", "industrial"),
        (None, "industrial"),
        ("", "industrial"),
        ("n/a", "industrial"),
    ],
)
def test_business_type_for_sic(sic, expected) -> None:
    mod = load_script("valuation/scripts/intrinsic-inputs.py")
    business_type, reason = mod.business_type_for_sic(sic)
    assert business_type == expected
    assert reason.startswith("SIC") or reason == "no SIC code"


def test_bank_sic_sets_financial(fake_sources, monkeypatch, capsys) -> None:
    monkeypatch.setattr(edgar, "submissions", lambda cik: {"cik": cik, "sic": "6021", "sic_description": "National Commercial Banks", "filings": []})
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), ["JPM"], capsys)
    assert rc == 0, out
    assert out["sic"] == "6021" and out["business_type"] == "financial"
    assert out["intrinsic_input"]["business_type"] == "financial"
    assert out["assumptions"]["business_type"] == {
        "value": "financial",
        "source": "SIC 6021 is in 6020-6199 (banks, savings institutions and credit) (National Commercial Banks) -> financial",
    }


def test_business_type_override_beats_sic(fake_sources, monkeypatch, capsys) -> None:
    monkeypatch.setattr(edgar, "submissions", lambda cik: {"cik": cik, "sic": "6798", "sic_description": "Real Estate Investment Trusts", "filings": []})
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), ["O", "--business-type", "industrial"], capsys)
    assert rc == 0, out
    assert out["sic"] == "6798" and out["business_type"] == "industrial"
    assert out["assumptions"]["business_type"] == {"value": "industrial", "source": "--business-type override"}
    assert out["intrinsic_input"]["business_type"] == "industrial"


def test_submissions_failure_degrades_to_industrial(fake_sources, monkeypatch, capsys) -> None:
    def boom(cik):
        raise ApiError("down", code="EDGAR_HTTP")

    monkeypatch.setattr(edgar, "submissions", boom)
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), ["KO"], capsys)
    assert rc == 0, out
    assert out["sic"] is None and out["business_type"] == "industrial"
    assert {f["code"] for f in out["flags"]} == {"SIC_UNAVAILABLE"}
    assert out["assumptions"]["business_type"]["source"] == "no SIC code -> industrial"


def test_a_reit_that_lends_is_typed_financial(fake_sources, monkeypatch, capsys) -> None:
    mod = load_script("valuation/scripts/intrinsic-inputs.py")
    assert mod.mortgage_reit_reason([{"revenue": None, "interest_expense": 4800.0}]) == "no revenue line in its latest fiscal year"
    assert mod.mortgage_reit_reason([{"revenue": 1000.0, "interest_expense": 700.0}]) == "interest expense is 70% of revenue"
    assert mod.mortgage_reit_reason([{"revenue": 4000.0, "interest_expense": 840.0}]) is None   # a property REIT with ordinary debt
    assert mod.mortgage_reit_reason([{"revenue": 4000.0, "interest_expense": None}]) is None
    assert mod.mortgage_reit_reason([]) is None
    monkeypatch.setattr(edgar, "submissions", lambda cik: {"cik": cik, "sic": "6798", "sic_description": "Real Estate Investment Trusts", "filings": []})
    monkeypatch.setattr(mod, "mortgage_reit_reason", lambda annual: "interest expense is 70% of revenue")
    rc, out = run_json(mod, ["NLY"], capsys)
    assert rc == 0 and out["business_type"] == "financial"
    assert "a mortgage REIT, judged as a lender" in out["assumptions"]["business_type"]["source"]


def test_utility_sic_sets_utility_and_the_override_accepts_it(fake_sources, monkeypatch, capsys) -> None:
    monkeypatch.setattr(edgar, "submissions", lambda cik: {"cik": cik, "sic": "4911", "sic_description": "Electric Services", "filings": []})
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), ["ES"], capsys)
    assert rc == 0 and out["business_type"] == "utility" and out["intrinsic_input"]["business_type"] == "utility"
    rc, out = run_json(load_script("valuation/scripts/intrinsic-inputs.py"), ["KO", "--business-type", "utility"], capsys)
    assert rc == 0 and out["business_type"] == "utility"
