from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json
from second_opinion import edgar

BASE = "https://www.sec.gov/Archives/edgar/data/320193/"


def _row(form, date, n, items):
    return {"form": form, "filingDate": date, "accessionNumber": f"0000320193-26-{n:06d}", "primaryDocument": f"d{n}.htm", "items": items}


FILINGS = [
    _row("8-K", "2026-01-30", 1, "2.02,9.01"),
    _row("8-K", "2026-03-01", 2, "5.02"),
    _row("10-Q", "2026-05-01", 3, ""),
    _row("8-K", "2026-05-02", 4, "2.02,9.01"),
    _row("8-K", "2025-10-30", 5, "2.02"),
    _row("8-K/A", "2026-06-01", 6, "2.02"),
]
INDEXES = {
    "000032019326000001": ["d1.htm", "EX-99.1.htm", "ex99-2.htm"],
    "000032019326000004": ["d4.htm", "ex991.htm"],
    "000032019326000005": ["d5.htm", "ex99-2.htm", "ex99_3.htm"],
}
BODY = "<html><body><p>Revenue was $100 million.</p><p>Guidance: $110 million.</p></body></html>"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setenv("EDGAR_USER_AGENT", "test-suite test@example.com")
    monkeypatch.setattr(edgar, "cik_for", lambda s: (320193, "Apple Inc."))
    monkeypatch.setattr(edgar, "submissions", lambda cik: {"cik": cik, "name": "Apple Inc.", "filings": FILINGS})
    calls: list[str] = []

    def archive(url):
        calls.append(url)
        if url.endswith("index.json"):
            acc = url.rsplit("/", 2)[1]
            return json.dumps({"directory": {"item": [{"name": n} for n in INDEXES.get(acc, ["d.htm"])]}})
        return BODY

    monkeypatch.setattr(edgar, "archive", archive)
    return calls


def _run(args, capsys):
    return run_json(load_script("fundamental-research/scripts/earnings.py"), args, capsys)


def test_picks_item_202_newest_first(fake, capsys) -> None:
    rc, out = _run(["AAPL"], capsys)
    assert rc == 0, out
    assert out["symbol"] == "AAPL" and out["cik"] == 320193 and out["as_of"]
    assert [r["filing_date"] for r in out["releases"]] == ["2026-05-02", "2026-01-30", "2025-10-30"]
    r = out["releases"][0]
    assert r["accession"] == "0000320193-26-000004" and r["exhibit"] == "ex991.htm"
    assert r["url"] == BASE + "000032019326000004/ex991.htm"
    assert r["text"] == "Revenue was $100 million.\nGuidance: $110 million." and r["truncated"] is False
    assert out["releases"][1]["exhibit"] == "EX-99.1.htm"


def test_last_and_fallback_exhibit_and_no_ex99(fake, capsys, monkeypatch) -> None:
    rc, out = _run(["AAPL", "--last", "1"], capsys)
    assert rc == 0 and len(out["releases"]) == 1
    rc, out = _run(["AAPL", "--last", "3"], capsys)
    assert out["releases"][2]["exhibit"] == "ex99-2.htm" and out["flags"] == []
    INDEXES["000032019326000004"] = ["d4.htm"]
    try:
        rc, out = _run(["AAPL", "--last", "1"], capsys)
    finally:
        INDEXES["000032019326000004"] = ["d4.htm", "ex991.htm"]
    r = out["releases"][0]
    assert r["exhibit"] is None and r["text"] is None and r["url"] is None and r["truncated"] is False
    assert {"code": "NO_EX99", "message": out["flags"][0]["message"]} == out["flags"][0] and "0000320193-26-000004" in out["flags"][0]["message"]


def test_max_chars_truncates(fake, capsys) -> None:
    rc, out = _run(["AAPL", "--last", "1", "--max-chars", "10"], capsys)
    r = out["releases"][0]
    assert rc == 0 and r["text"] == "Revenue wa" and r["truncated"] is True


def test_no_item_202_is_empty_not_error(fake, capsys, monkeypatch) -> None:
    monkeypatch.setattr(edgar, "submissions", lambda cik: {"cik": cik, "name": "X", "filings": [_row("8-K", "2026-03-01", 2, "5.02")]})
    rc, out = _run(["AAPL"], capsys)
    assert rc == 0 and out["releases"] == [] and out["flags"] == []


def test_errors(fake, capsys) -> None:
    assert _run(["not a symbol!"], capsys)[0] == 2
    assert _run([], capsys)[0] == 2
    assert _run(["AAPL", "--bogus"], capsys)[0] == 2
    assert _run(["AAPL", "--last", "0"], capsys)[0] == 2


# Real exhibit names from live 8-K folders (public SEC filenames).
@pytest.mark.parametrize(
    "names, expected",
    [
        (["thc-20260202.htm", "thc-20260202exh991.htm", "tenethealthrgba.jpg"], "thc-20260202exh991.htm"),
        (["goog-20260428.htm", "googexhibit991q22026.htm"], "googexhibit991q22026.htm"),
        (["crm-20260528.htm", "crm-q2fy27xexhibit991.htm"], "crm-q2fy27xexhibit991.htm"),
        (["a1q26erf8-k.htm", "a1q26erfex992supplement.htm", "a1q26erfexhibit991narrative.htm"], "a1q26erfexhibit991narrative.htm"),
        (["x8k.htm", "ex99-10.htm", "ex99-1.htm"], "ex99-1.htm"),
        (["x8k.htm", "ex99-10.htm"], "ex99-10.htm"),  # only a generic ex99 name is left, via the fallback
        (["amph-20260507x8k.htm", "amph-20260507xex99d1001.jpg", "amph-20260507xex99d1.htm"], "amph-20260507xex99d1.htm"),
        (["amph-20260507xex99d1001.jpg", "amph-20260507xex99d1001.gif"], None),
        (["d112441dex991.htm", "d112441d8k.htm"], "d112441dex991.htm"),
        (["d1.htm", "EX-99.1.htm", "ex99-2.htm"], "EX-99.1.htm"),
        (["exhibit99q12026.htm", "d1.htm"], "exhibit99q12026.htm"),
        (["d1.htm"], None),
    ],
)
def test_filename_fallback_on_real_names(names, expected) -> None:
    mod = load_script("fundamental-research/scripts/earnings.py")
    assert mod._pick_exhibit(names) == expected


def test_ex99_10_does_not_match_99_1() -> None:
    mod = load_script("fundamental-research/scripts/earnings.py")
    assert not mod._EX991.search("ex99-10.htm") and not mod._EX991.search("exhibit9910.htm")
    assert mod._EX991.search("EX-99.01.htm") and mod._EX991.search("ex99_1.htm")


def _headers(*docs):
    out = "<html><body><pre>&lt;SEC-HEADER&gt;0001-26-000001\n"
    for i, (typ, name) in enumerate(docs, 1):
        out += f"&lt;DOCUMENT&gt;\n&lt;TYPE&gt;{typ}\n&lt;SEQUENCE&gt;{i}\n&lt;FILENAME&gt;{name}\n&lt;DESCRIPTION&gt;x\n&lt;/DOCUMENT&gt;\n"
    return out + "</pre></body></html>"


def test_headers_type_beats_filename(monkeypatch, capsys) -> None:
    mod = load_script("fundamental-research/scripts/earnings.py")
    names = ["a1q26erfex992supplement.htm", "a991unherq42025.htm", "x-index-headers.html"]
    hdr = _headers(("8-K", "x8k.htm"), ("EX-99.2", "a1q26erfex992supplement.htm"), ("EX-99.1", "a991unherq42025.htm"))
    assert mod._pick_exhibit(names, hdr) == "a991unherq42025.htm"
    # raw (unescaped) SGML works too, and the first EX-99.x is taken when there is no 99.1
    assert mod._pick_exhibit(names, "<DOCUMENT>\n<TYPE>EX-99.2\n<FILENAME>a1q26erfex992supplement.htm\n</DOCUMENT>") == "a1q26erfex992supplement.htm"
    # a typed document that is not in the folder listing, or an image, is ignored
    assert mod._pick_exhibit(["pic.jpg"], _headers(("EX-99.1", "pic.jpg"))) is None


def test_run_uses_index_headers_when_listed(fake, capsys, monkeypatch) -> None:
    acc = "000032019326000004"
    INDEXES[acc] = ["d4.htm", "0000320193-26-000004-index-headers.html", "ex992supplement.htm", "a991release.htm"]
    orig = edgar.archive

    def archive(url):
        if url.endswith("-index-headers.html"):
            return _headers(("8-K", "d4.htm"), ("EX-99.2", "ex992supplement.htm"), ("EX-99.1", "a991release.htm"))
        return orig(url)

    monkeypatch.setattr(edgar, "archive", archive)
    try:
        rc, out = _run(["AAPL", "--last", "1"], capsys)
    finally:
        INDEXES[acc] = ["d4.htm", "ex991.htm"]
    assert rc == 0 and out["releases"][0]["exhibit"] == "a991release.htm" and out["flags"] == []


def test_one_bad_filing_does_not_abort_the_run(fake, capsys, monkeypatch) -> None:
    from second_opinion.errors import ApiError

    orig = edgar.archive

    def archive(url):
        if "000032019326000004" in url and url.endswith("index.json"):
            raise ApiError("EDGAR_HTTP: 404")
        if "000032019326000001" in url and url.endswith("index.json"):
            return "<html>not json</html>"
        return orig(url)

    monkeypatch.setattr(edgar, "archive", archive)
    rc, out = _run(["AAPL"], capsys)
    assert rc == 0, out
    assert [r["accession"] for r in out["releases"]] == ["0000320193-26-000004", "0000320193-26-000001", "0000320193-26-000005"]
    assert [r["text"] is None for r in out["releases"]] == [True, True, False]
    failed = [f for f in out["flags"] if f["code"] == "FETCH_FAILED"]
    assert len(failed) == 2 and "0000320193-26-000004" in failed[0]["message"] and "0000320193-26-000001" in failed[1]["message"]


def test_exhibit_fetch_failure_is_per_filing(fake, capsys, monkeypatch) -> None:
    from second_opinion.errors import ApiError

    orig = edgar.archive

    def archive(url):
        if url.endswith("ex991.htm"):
            raise ApiError("EDGAR_HTTP: 404")
        return orig(url)

    monkeypatch.setattr(edgar, "archive", archive)
    rc, out = _run(["AAPL"], capsys)
    assert rc == 0 and out["releases"][0]["text"] is None and out["releases"][1]["text"]
    assert [f["code"] for f in out["flags"]] == ["FETCH_FAILED"]
