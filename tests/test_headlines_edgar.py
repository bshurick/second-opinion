from __future__ import annotations

from datetime import date

from second_opinion.headlines import edgar as E

CTX = {"today": date(2026, 9, 14)}


def _res(sym="KO", k="2026-02-20", q="2026-09-10", eights=(), flags=(), items="2.02"):
    return {"symbol": sym, "company": f"{sym} Corp", "filings": {"latest_10k": {"form": "10-K", "date": k, "url": "u1"},
            "latest_10q": {"form": "10-Q", "date": q, "url": "u2"}, "recent_8k": [{"date": d, "items": items, "url": "u3"} for d in eights]},
            "flags": [{"code": c, "message": f"{c} msg"} for c in flags]}


def test_recent_filings_are_alerts_and_old_ones_are_not() -> None:
    hs = E.extract({"KO": _res(eights=("2026-09-12", "2026-08-01"), items="2.02,9.01")}, CTX)
    assert [h["key"] for h in hs] == ["fundamental-research:FILING:KO:10-Q:2026-09-10", "fundamental-research:FILING:KO:8-K:2026-09-12"]
    assert hs[0]["title"] == "KO filed a 10-Q on 2026-09-10" and hs[0]["severity"] == "alert" and hs[0]["detail"] == ""
    assert hs[0]["ask"] == "What changed in KO's latest 10-Q?"
    assert hs[1]["ask"] == "What does KO's latest 8-K say?"
    assert hs[0]["url"] == "u2" and hs[0]["answer"] == "Filed 2026-09-10; risk-factor comparison pending"
    assert hs[0]["why"] == ("A 10-Q is the quarterly report; a 10-K the annual one. "
                             "Its risk-factor section is where new problems appear first.")
    assert hs[1]["url"] == "u3" and hs[1]["answer"] == "Results of Operations; Financial Statements and Exhibits"
    assert hs[1]["why"] == "An 8-K is a current report a company files within four business days of a material event."


def test_eight_k_unknown_item_codes_render_generically() -> None:
    hs = E.extract({"KO": _res(eights=("2026-09-12",), items="2.02,4.99")}, CTX)
    eight = [h for h in hs if h["title"].endswith("8-K on 2026-09-12")][0]
    assert eight["answer"] == "Results of Operations; Item 4.99"


def test_eight_k_with_no_items_has_an_empty_answer() -> None:
    hs = E.extract({"KO": _res(eights=("2026-09-12",), items=None)}, CTX)
    eight = [h for h in hs if h["title"].endswith("8-K on 2026-09-12")][0]
    assert eight["answer"] == ""


def test_red_flags_become_one_notice_per_symbol() -> None:
    hs = E.extract({"PEP": _res("PEP", q="2026-06-01", flags=("NEGATIVE_FCF", "LEVERAGE", "DEFAULT_USER_AGENT", "MISSING_DATA"))}, CTX)
    assert len(hs) == 1
    assert hs[0]["key"] == "fundamental-research:RED_FLAGS:PEP:LEVERAGE,NEGATIVE_FCF" and hs[0]["severity"] == "notice"
    assert hs[0]["title"] == "PEP fundamentals flag LEVERAGE, NEGATIVE_FCF" and hs[0]["detail"] == ""
    assert hs[0]["answer"] == "LEVERAGE msg; NEGATIVE_FCF msg"
    assert hs[0]["ask"] == "What does PEP's quality checklist show?"
    assert hs[0]["url"] == "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=PEP&type=10-K&owner=include&count=10"
    assert hs[0]["why"] == "Screens on the company's own filings: cash flow, leverage, dilution and revenue trend."


def test_null_filings_and_no_flags_is_empty() -> None:
    assert E.extract({"X": {"symbol": "X", "filings": None, "flags": []}}, CTX) == []
