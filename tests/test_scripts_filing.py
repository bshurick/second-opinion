from __future__ import annotations

import pytest
from scripts_util import load_script, run_json
from second_opinion import edgar

RISKS = "Our margins may decline. Competition is intense. " * 8
PREV = "Our margins may decline. Supply is stable. " * 8


def _doc(risks: str) -> str:
    return f"<html><body><p>FORM 10-K</p><p>Item 1A. Risk Factors 10</p><p>Item 7. MD&amp;A 30</p><p>Item 1A. Risk Factors</p><p>{risks}</p><p>Item 7. Management's Discussion and Analysis</p><p>{'Revenue grew. ' * 10}</p></body></html>"


FILINGS = [
    {"form": "10-K", "filingDate": "2026-02-01", "accessionNumber": "0000320193-26-000001", "primaryDocument": "aapl-2025.htm", "items": ""},
    {"form": "10-Q", "filingDate": "2026-05-01", "accessionNumber": "0000320193-26-000002", "primaryDocument": "aapl-q1.htm", "items": ""},
    {"form": "10-K", "filingDate": "2025-02-01", "accessionNumber": "0000320193-25-000001", "primaryDocument": "aapl-2024.htm", "items": ""},
]


@pytest.fixture
def fake_edgar(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setenv("EDGAR_USER_AGENT", "test-suite test@example.com")
    fetched: list[str] = []
    monkeypatch.setattr(edgar, "cik_for", lambda s: (320193, "Apple Inc."))
    monkeypatch.setattr(edgar, "submissions", lambda cik: {"cik": cik, "name": "Apple Inc.", "filings": FILINGS})

    def document(url):
        fetched.append(url)
        return _doc(PREV if "2024" in url else RISKS)

    monkeypatch.setattr(edgar, "document", document)
    return fetched


def test_filing_item_from_latest_10k(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/filing.py"), ["AAPL", "--item", "1A"], capsys)
    assert rc == 0, out
    assert out["symbol"] == "AAPL" and out["form"] == "10-K" and out["filing_date"] == "2026-02-01"
    assert out["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/aapl-2025.htm"
    assert out["item"] == "1A" and out["text"].startswith("Our margins may decline.") and out["truncated"] is False
    assert fake_edgar == [out["url"]]
    assert out["available_items"] == ["1A", "7"]


def test_filing_diff_search_and_split(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/filing.py"), ["AAPL", "--item", "1A", "--diff"], capsys)
    assert rc == 0 and out["previous"]["filing_date"] == "2025-02-01" and out["added_sentences"] == ["Competition is intense."] and out["removed_sentences"] == ["Supply is stable."]
    rc, out = run_json(load_script("fundamental-research/scripts/filing.py"), ["AAPL", "--search", "margins"], capsys)
    assert rc == 0 and out["count"] == 8 and out["hits"][0]["item"] == "1A"
    rc, out = run_json(load_script("fundamental-research/scripts/filing.py"), ["AAPL", "--form", "10-Q"], capsys)
    assert rc == 0 and out["form"] == "10-Q" and out["filing_date"] == "2026-05-01" and [i["item"] for i in out["items"]] == ["1A", "7"]


def test_filing_by_url_and_errors(fake_edgar, capsys) -> None:
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/aapl-2024.htm"
    rc, out = run_json(load_script("fundamental-research/scripts/filing.py"), ["--url", url, "--item", "1A"], capsys)
    assert rc == 0 and out["text"].startswith("Our margins may decline. Supply is stable.") and out["symbol"] is None
    rc, out = run_json(load_script("fundamental-research/scripts/filing.py"), ["AAPL", "--form", "20-F"], capsys)
    assert rc == 2 and "no 20-F filing" in out["error"]
    rc, out = run_json(load_script("fundamental-research/scripts/filing.py"), ["AAPL", "--item", "9"], capsys)
    assert rc == 2 and "item 9 not found" in out["error"]
    rc, out = run_json(load_script("fundamental-research/scripts/filing.py"), [], capsys)
    assert rc == 2 and "symbol or --url" in out["error"]
