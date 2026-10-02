"""fundamental-research/scripts/holdings.py: a manager's latest 13F against the prior quarter."""
from __future__ import annotations

import pytest
from second_opinion import edgar
from scripts_util import load_script, run_json
from page_dom import assert_page_help, render_and_audit, requires_chrome

FILINGS = [
    {"accession": "0001193125-26-352200", "filing_date": "2026-08-14", "report_date": "2026-06-30", "form": "13F-HR"},
    {"accession": "0001193125-26-352201", "filing_date": "2026-08-14", "report_date": "2026-06-30", "form": "13F-HR"},  # same period, second filing
    {"accession": "0001193125-26-226661", "filing_date": "2026-05-15", "report_date": "2026-03-31", "form": "13F-HR"},
]
CUR = b'<informationTable xmlns="x"><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>1000</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt></shrsOrPrnAmt></infoTable><infoTable><nameOfIssuer>ALLY</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>02005N100</cusip><value>200</value><shrsOrPrnAmt><sshPrnamt>20</sshPrnamt></shrsOrPrnAmt></infoTable></informationTable>'
PREV = b'<informationTable xmlns="x"><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>900</value><shrsOrPrnAmt><sshPrnamt>12</sshPrnamt></shrsOrPrnAmt></infoTable></informationTable>'


@pytest.fixture
def fake_edgar(monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", "test-suite test@example.com")
    calls: list = []
    monkeypatch.setattr(edgar, "thirteen_f_filings", lambda cik: (calls.append(("filings", cik)), list(FILINGS))[1])
    monkeypatch.setattr(edgar, "information_table", lambda cik, acc: (calls.append(("table", acc)), CUR if acc.endswith("352200") else PREV)[1])
    monkeypatch.setattr(edgar, "submissions", lambda cik: {"cik": cik, "name": "BERKSHIRE HATHAWAY INC", "filings": []})
    monkeypatch.setattr(edgar, "search_companies", lambda name: (calls.append(("search", name)), [{"cik": 1336528, "name": "Pershing Square Capital Management, L.P."}])[1])
    return calls


def test_alias_resolves_and_diffs_against_the_prior_quarter(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["Berkshire"], capsys)
    assert rc == 0 and out["manager"] == {"cik": 1067983, "alias": "berkshire", "name": "BERKSHIRE HATHAWAY INC"}
    assert out["current"] == {"accession": "0001193125-26-352200", "filing_date": "2026-08-14", "report_date": "2026-06-30", "url": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526352200/"}
    assert out["previous"]["accession"] == "0001193125-26-226661" and out["previous"]["report_date"] == "2026-03-31"
    assert ("table", "0001193125-26-352201") not in fake_edgar  # the same-period duplicate is not the prior quarter
    assert out["totals"] == {"value": 1200, "previous_value": 900, "positions": 2, "previous_positions": 1, "value_change_pct": 33.33}
    assert [n["issuer"] for n in out["new"]] == ["ALLY"] and out["trimmed"][0]["shares_change_pct"] == -16.67
    assert out["lag_days"] == 45 and out["as_of"]


def test_cik_flag_and_limit(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["--cik", "1067983", "--limit", "1"], capsys)
    assert rc == 0 and out["manager"]["alias"] == "berkshire" and len(out["top"]) == 1


def test_unknown_name_returns_edgar_candidates_with_exit_2(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["pershing square holdings ltd"], capsys)
    assert rc == 2 and out["code"] == "MANAGER_AMBIGUOUS"
    assert out["candidates"] == [{"cik": 1336528, "name": "Pershing Square Capital Management, L.P."}] and ("search", "pershing square holdings ltd") in fake_edgar


def test_search_flag_lists_filers_without_a_diff(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["--search", "pershing"], capsys)
    assert rc == 0 and out == {"query": "pershing", "candidates": [{"cik": 1336528, "name": "Pershing Square Capital Management, L.P."}]}


def test_list_flag_prints_the_curated_managers(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["--list"], capsys)
    assert rc == 0 and out["managers"]["berkshire"] == 1067983 and len(out["managers"]) >= 15


def test_single_filing_diffs_against_nothing(fake_edgar, monkeypatch, capsys) -> None:
    monkeypatch.setattr(edgar, "thirteen_f_filings", lambda cik: [FILINGS[0]])
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["berkshire"], capsys)
    assert rc == 0 and out["previous"] is None and out["totals"]["previous_value"] is None and len(out["new"]) == 2


def test_no_filings_and_unparseable_table_are_reported(fake_edgar, monkeypatch, capsys) -> None:
    monkeypatch.setattr(edgar, "thirteen_f_filings", lambda cik: [])
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["berkshire"], capsys)
    assert rc == 2 and out["code"] == "NO_13F"
    monkeypatch.setattr(edgar, "thirteen_f_filings", lambda cik: list(FILINGS))
    monkeypatch.setattr(edgar, "information_table", lambda cik, acc: b"<html>blocked</html>")
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["berkshire"], capsys)
    assert rc == 5 and out["code"] == "EDGAR_13F_TABLE"


def test_usage_without_arguments_exits_2(fake_edgar, capsys) -> None:
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), [], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_default_user_agent_is_flagged(fake_edgar, monkeypatch, capsys) -> None:
    monkeypatch.delenv("EDGAR_USER_AGENT")
    rc, out = run_json(load_script("fundamental-research/scripts/holdings.py"), ["berkshire"], capsys)
    assert rc == 0 and any(f["code"] == "DEFAULT_USER_AGENT" for f in out["flags"])


HOLDINGS = {
    "as_of": "2026-09-14T16:00:00Z",
    "manager": {"cik": 1067983, "alias": "berkshire", "name": "BERKSHIRE HATHAWAY INC"},
    "current": {"accession": "0001193125-26-352200", "filing_date": "2026-08-14", "report_date": "2026-06-30", "url": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526352200/"},
    "previous": {"accession": "0001193125-26-226661", "filing_date": "2026-05-15", "report_date": "2026-03-31", "url": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/"},
    "lag_days": 45,
    "totals": {"value": 299253556246, "previous_value": 263095703570, "positions": 29, "previous_positions": 29, "value_change_pct": 13.74},
    "new": [{"cusip": "23331A109", "issuer": "D R HORTON </script> INC", "class": "COM", "put_call": None, "shares": 3564, "value": 500000, "weight_pct": 0.0}],
    "exited": [{"cusip": "21036P108", "issuer": "CONSTELLATION BRANDS INC", "class": "COM", "put_call": None, "previous_shares": 632890, "previous_value": 100000000}],
    "increased": [{"cusip": "02079K305", "issuer": "ALPHABET INC", "class": "CAP STK CL A", "put_call": None, "shares": 78791167, "previous_shares": 54250000, "shares_change_pct": 45.24, "value": 28000000000, "weight_pct": 9.41}],
    "trimmed": [{"cusip": "060505104", "issuer": "BANK OF AMER CORP", "class": "COM", "put_call": None, "shares": 483394015, "previous_shares": 513650000, "shares_change_pct": -5.89, "value": 27500000000, "weight_pct": 9.2}],
    "unchanged": 15,
    "top": [{"cusip": "037833100", "issuer": "APPLE INC", "class": "COM", "put_call": None, "shares": 280000000, "value": 66000000000, "weight_pct": 22.04}, {"cusip": "025816109", "issuer": "AMERICAN EXPRESS CO", "class": "COM", "put_call": None, "shares": 151610700, "value": 51300000000, "weight_pct": 17.14}],
    "concentration": {"top_5_pct": 68.65, "top_10_pct": 88.47},
    "truncated": {"increased": 2},
    "flags": [{"code": "DEFAULT_USER_AGENT", "message": "set EDGAR_USER_AGENT"}],
    "notes": ["13F reports US-listed long positions only."],
}


def test_holdings_render_builds_a_page(tmp_path, capsys) -> None:
    import json

    src = tmp_path / "holdings.json"
    src.write_text(json.dumps(HOLDINGS))
    out = tmp_path / "holdings.html"
    rc, res = run_json(load_script("fundamental-research/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "13F Holdings", "manager": "BERKSHIRE HATHAWAY INC", "positions": 29, "changes": 6, "flags": 1}  # changes count truncated rows too
    html = out.read_text()
    assert html.startswith("<title>13F Holdings</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and "const FA" in html
    assert "</script> INC" not in html and "<\\/script> INC" in html
    assert "BERKSHIRE HATHAWAY INC (CIK 1067983) · quarter ended 2026-06-30, filed 2026-08-14 (45 days later) · $299.3B in 29 positions · +13.7% vs the quarter ended 2026-03-31 · 1 new · 1 exited · 3 increased · 1 trimmed · 15 unchanged" in html  # truncated rows are counted
    for section in ("Top holdings", "Concentration", "All reported holdings", "New", "Exited", "Increased", "Trimmed", "Flags", "not financial advice"):
        assert section in html
    assert "prefers-color-scheme: dark" in html and "http" not in html.split("</style>")[1].split("<script>")[0]
    assert 'id="explain"' in html and "FA.explain(" in html and "FA.term(" in html


def test_holdings_render_without_a_prior_quarter(tmp_path, capsys) -> None:
    import json

    data = {**HOLDINGS, "previous": None, "totals": {**HOLDINGS["totals"], "previous_value": None, "previous_positions": None, "value_change_pct": None}, "exited": [], "increased": [], "trimmed": [], "unchanged": 0, "truncated": {}}
    src = tmp_path / "h.json"
    src.write_text(json.dumps(data))
    rc, res = run_json(load_script("fundamental-research/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "h.html")], capsys)
    assert rc == 0 and res["changes"] == 1
    assert "no prior quarter" in (tmp_path / "h.html").read_text()


def test_holdings_render_rejects_wrong_input(tmp_path, capsys) -> None:
    (tmp_path / "bad.json").write_text('{"annual": []}')
    rc, res = run_json(load_script("fundamental-research/scripts/render.py"), ["--in", str(tmp_path / "bad.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "holdings.py result" in res["error"]
    rc, res = run_json(load_script("fundamental-research/scripts/render.py"), ["--in", str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    import json

    src = tmp_path / "holdings.json"
    src.write_text(json.dumps(HOLDINGS))
    assert_page_help(render_and_audit("fundamental-research/scripts/render.py", ["--in", str(src)], tmp_path, capsys))
