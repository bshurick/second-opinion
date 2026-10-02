"""SEC EDGAR client used by the fundamental-research skill: ticker lookup, submissions, company facts, disk cache."""
from __future__ import annotations

import json
import time

import pytest
from second_opinion import edgar
from second_opinion.errors import ApiError, InvalidInput

TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"}}
SUBMISSIONS = {"cik": "320193", "name": "Apple Inc.", "filings": {"recent": {"form": ["10-K", "4"], "filingDate": ["2025-11-01", "2026-08-01"], "accessionNumber": ["0000320193-25-000100", "0000320193-26-000200"], "primaryDocument": ["aapl-20250927.htm", "form4.xml"], "items": ["", ""]}}}
FACTS = {"cik": 320193, "entityName": "Apple Inc.", "facts": {"us-gaap": {"Revenues": {"units": {"USD": []}}}}}


@pytest.fixture
def fake_http(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setenv("EDGAR_USER_AGENT", "test-suite test@example.com")
    calls: list[tuple[str, str]] = []

    def fetch(url: str, user_agent: str) -> bytes:
        calls.append((url, user_agent))
        if url.endswith("company_tickers.json"):
            return json.dumps(TICKERS).encode()
        if "/submissions/CIK0000320193.json" in url:
            return json.dumps(SUBMISSIONS).encode()
        if "/companyfacts/CIK0000320193.json" in url:
            return json.dumps(FACTS).encode()
        raise ApiError(f"HTTP 404 for {url}", code="EDGAR_HTTP", http_status=404)

    monkeypatch.setattr(edgar, "_fetch", fetch)
    return calls


def test_cik_lookup_and_cache(fake_http, tmp_path) -> None:
    assert edgar.cik_for("aapl") == (320193, "Apple Inc.")
    assert edgar.cik_for("MSFT") == (789019, "MICROSOFT CORP")
    assert [u for u, _ in fake_http] == ["https://www.sec.gov/files/company_tickers.json"]  # second lookup served from cache
    assert fake_http[0][1] == "test-suite test@example.com"
    assert (tmp_path / "edgar-cache" / "company_tickers.json").exists()
    with pytest.raises(InvalidInput, match="ZZZZ is not in the SEC ticker list"):
        edgar.cik_for("ZZZZ")


def test_submissions_flattened_and_facts_cached(fake_http, tmp_path) -> None:
    subs = edgar.submissions(320193)
    assert subs["name"] == "Apple Inc." and subs["filings"][0] == {"form": "10-K", "filingDate": "2025-11-01", "accessionNumber": "0000320193-25-000100", "primaryDocument": "aapl-20250927.htm", "items": ""}
    facts = edgar.company_facts(320193)
    assert facts["entityName"] == "Apple Inc."
    edgar.company_facts(320193)
    assert sum(1 for u, _ in fake_http if "companyfacts" in u) == 1
    assert (tmp_path / "edgar-cache" / "companyfacts-320193.json").exists()


def test_cache_expiry(fake_http, tmp_path, monkeypatch) -> None:
    edgar.company_facts(320193)
    path = tmp_path / "edgar-cache" / "companyfacts-320193.json"
    old = time.time() - 3 * 86400
    import os

    os.utime(path, (old, old))
    edgar.company_facts(320193)
    assert sum(1 for u, _ in fake_http if "companyfacts" in u) == 2


def test_default_user_agent_warns(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    assert "example.com" in edgar.user_agent() and edgar.user_agent_is_default() is True


def test_http_error_becomes_api_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setattr(edgar, "_fetch", lambda url, ua: (_ for _ in ()).throw(ApiError("HTTP 403", code="EDGAR_HTTP", http_status=403)))
    with pytest.raises(ApiError) as ei:
        edgar.submissions(1)
    assert ei.value.code == "EDGAR_HTTP"


def test_document_fetch_and_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    calls = []
    monkeypatch.setattr(edgar, "_fetch", lambda url, ua: (calls.append(url), b"<html><p>Item 1A. Risks</p></html>")[1])
    url = edgar.filing_url(320193, "0000320193-26-000001", "a.htm")
    assert url == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/a.htm"
    assert edgar.document(url).startswith("<html>") and edgar.document(url).startswith("<html>")
    assert calls == [url] and list((tmp_path / "edgar-cache").glob("doc-*.html"))


THIRTEENF_SUBMISSIONS = {"cik": "1067983", "name": "BERKSHIRE HATHAWAY INC", "filings": {"recent": {
    "form": ["13F-HR", "8-K", "13F-HR/A", "13F-HR"], "filingDate": ["2026-08-14", "2026-08-01", "2026-06-01", "2026-05-15"],
    "accessionNumber": ["0001193125-26-352200", "0001193125-26-300000", "0001193125-26-250000", "0001193125-26-226661"],
    "primaryDocument": ["xslForm13F_X02/primary_doc.xml", "d8k.htm", "xslForm13F_X02/primary_doc.xml", "xslForm13F_X02/primary_doc.xml"],
    "reportDate": ["2026-06-30", "2026-08-01", "2026-03-31", "2026-03-31"], "items": ["", "", "", ""]}}}
INDEX = {"directory": {"item": [{"name": "0001193125-26-352200-index.html"}, {"name": "56757.xml"}, {"name": "primary_doc.xml"}]}}


@pytest.fixture
def fake_13f(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setenv("EDGAR_USER_AGENT", "test-suite test@example.com")
    calls: list[str] = []

    def fetch(url: str, user_agent: str) -> bytes:
        calls.append(url)
        if "/submissions/CIK0001067983.json" in url:
            return json.dumps(THIRTEENF_SUBMISSIONS).encode()
        if url.endswith("/000119312526352200/index.json"):
            return json.dumps(INDEX).encode()
        if url.endswith("/000119312526352200/56757.xml"):
            return b"<informationTable/>"
        if "browse-edgar" in url:
            return b'<feed><entry><title>Pershing Square Capital Management, L.P. (0001336528)</title><link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001336528&amp;type=13F-HR"/></entry><entry><title>PERSHING SQUARE HOLDINGS (0001600000)</title><link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001600000"/></entry></feed>'
        raise ApiError(f"HTTP 404 for {url}", code="EDGAR_HTTP", http_status=404)

    monkeypatch.setattr(edgar, "_fetch", fetch)
    return calls


def test_thirteen_f_filings_lists_original_holdings_reports_newest_first(fake_13f) -> None:
    out = edgar.thirteen_f_filings(1067983)
    assert [f["accession"] for f in out] == ["0001193125-26-352200", "0001193125-26-226661"]
    assert out[0] == {"accession": "0001193125-26-352200", "filing_date": "2026-08-14", "report_date": "2026-06-30", "form": "13F-HR"}


def test_information_table_finds_the_non_primary_xml_in_the_filing_index(fake_13f) -> None:
    assert edgar.information_table(1067983, "0001193125-26-352200") == b"<informationTable/>"
    assert fake_13f[-2:] == ["https://www.sec.gov/Archives/edgar/data/1067983/000119312526352200/index.json", "https://www.sec.gov/Archives/edgar/data/1067983/000119312526352200/56757.xml"]
    edgar.information_table(1067983, "0001193125-26-352200")
    assert len(fake_13f) == 2  # both cached


def test_information_table_without_a_table_file_is_an_api_error(fake_13f, monkeypatch) -> None:
    monkeypatch.setattr(edgar, "_fetch", lambda url, ua: json.dumps({"directory": {"item": [{"name": "primary_doc.xml"}]}}).encode())
    with pytest.raises(ApiError) as excinfo:
        edgar.information_table(1067983, "0001193125-26-000001")
    assert excinfo.value.code == "EDGAR_13F_TABLE"


def test_search_companies_parses_the_atom_feed(fake_13f) -> None:
    out = edgar.search_companies("pershing square")
    assert out == [{"cik": 1336528, "name": "Pershing Square Capital Management, L.P."}, {"cik": 1600000, "name": "PERSHING SQUARE HOLDINGS"}]
    assert "company=pershing+square" in fake_13f[-1] and "type=13F-HR" in fake_13f[-1]


def test_frame_returns_rows_caches_and_treats_404_as_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    calls: list[str] = []
    rows = [{"cik": 320193, "entityName": "Apple Inc.", "val": 391e9, "end": "2025-09-27"}]

    def fetch(url: str, user_agent: str) -> bytes:
        calls.append(url)
        if "/Revenues/USD/CY2025.json" in url:
            return json.dumps({"data": rows}).encode()
        raise ApiError(f"HTTP 404 for {url}", code="EDGAR_HTTP", http_status=404)

    monkeypatch.setattr(edgar, "_fetch", fetch)
    assert edgar.frame("Revenues", "CY2025") == rows
    assert edgar.frame("Revenues", "CY2025") == rows  # second read from the cache
    assert calls == ["https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2025.json"]
    assert edgar.frame("SalesRevenueNet", "CY2025") == []


def test_frame_raises_on_a_non_404_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))

    def fetch(url: str, user_agent: str) -> bytes:
        raise ApiError("HTTP 503", code="EDGAR_HTTP", http_status=503)

    monkeypatch.setattr(edgar, "_fetch", fetch)
    with pytest.raises(ApiError):
        edgar.frame("Revenues", "CY2025")


def test_tickers_keeps_the_first_listing_per_cik(fake_http) -> None:
    import second_opinion.edgar as e

    got = e.tickers()
    assert got[320193] == {"ticker": "AAPL", "title": "Apple Inc."}
