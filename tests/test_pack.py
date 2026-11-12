from __future__ import annotations

import json
from pathlib import Path

import pytest

from second_opinion import pack
from second_opinion.errors import ConfigError, InvalidInput

RELEASE_TEXT = "Revenue of $100M, up 4%.\nGuidance: FY EPS $3.00 to $3.30 (non-GAAP)."
TERMS_CARD = ["going concern", "material weakness", "restat", "related part"]
TERMS_DEEP = TERMS_CARD + ["capitalized", "change in accounting"]
DEEP_FILES = [
    "edgar.json", "fundamentals.json", "inputs.json", "intrinsic-inputs.json", "intrinsic.json", "quick_value.json",
    "sentiment.json", "earnings.json", "releases/2026-08-26.txt", "releases/2026-05-28.txt", "redflags.json",
    "filings/10k-items.json", "filings/10k-item1.txt", "filings/10k-item1a.txt", "filings/10k-item7.txt",
    "filings/10k-item8.txt", "filings/10k-item9a.txt", "filings/10k-item1a-diff.txt", "filings/10k-item8-diff.txt",
    "filings/10q-item1.txt", "filings/10q-item2.txt", "filings/segment-note.txt", "forensic-checks.json",
]
CARD_FILES = DEEP_FILES[:11]


def _annual():
    rows = []
    for i, fy in enumerate(range(2021, 2026)):
        rev = 1000.0e6 * 1.05**i
        rows.append({"fiscal_year": fy, "revenue": rev, "gross_profit": rev * 0.4, "net_income": 100e6, "operating_cash_flow": 80e6 if fy >= 2024 else 130e6,
                     "dso": 40.0 + 6 * i, "dio": 60.0, "sbc": rev * 0.01, "sbc_pct_revenue": 0.01, "revenue_growth": 0.05 if i else None})
    return rows


def _inputs(flags=(), shares=200_000_000):
    dcf = {"fcf0": 150e6, "growth_rate": 0.05, "years": 5, "terminal_growth": 0.025, "wacc": 0.09, "net_debt": 300e6, "shares_outstanding": shares, "current_share_price": 20.0}
    scen = {n: {**{k: v for k, v in dcf.items() if k != "growth_rate"}, "stage1_growth": [g] * 5} for n, g in (("bear", 0.02), ("base", 0.05), ("bull", 0.08))}
    return {"symbol": "ACME", "as_of": "2026-11-10", "business_type": "industrial",
            "assumptions": {"cost_of_equity": {"value": 0.10, "source": "CAPM"}, "wacc": {"value": 0.09, "source": "w"}, "tax_rate": {"value": 0.21, "source": "t"},
                            "cost_of_debt": {"value": 0.06, "source": "d"}, "shares_outstanding": {"value": shares, "source": "Yahoo"}},
            "dcf_input": dcf, "dcf_scenarios": scen, "ddm_input": {"model": "gordon", "dividend0": 0.4, "required_return": 0.10, "terminal_growth": 0.025},
            "flags": [{"code": "ERP_DEFAULT", "message": "default premium"}, *({"code": c, "message": c} for c in flags)]}


def _intrinsic():
    return {"fiscal_year": 2025, "inputs": {"business_type": "industrial"},
            "buffett": {"book_value_tests": {"price_to_book": 1.6, "roe_latest": 0.21, "roe_10y_avg": 0.2, "price_to_book_x_roe_note": "P/B 1.60"},
                        "reit_tests": None, "utility_tests": None},
            "normalized": {"dcf_input_mid_cycle": {"fcf0": 120e6, "growth_rate": 0.02, "years": 10, "terminal_growth": 0.02, "wacc": 0.08, "net_debt": 300e6,
                                                   "shares_outstanding": 200e6, "current_share_price": 20.0}},
            "flags": [{"code": "MAINTENANCE_CAPEX_ESTIMATED", "message": "m"}]}


ITEMS = [{"item": i, "title": f"Title {i}", "words": 1000, "chars": 6000, "start": 10} for i in ("1", "1A", "7", "8", "9A")]
INDEX_ITEMS = [{"item": i, "title": "", "words": 5, "chars": 40, "start": 10} for i in ("1", "1A", "7", "8", "9A")] + [{"item": "16", "title": "", "words": 90000, "chars": 590000, "start": 99}]


def make_runner(fail=(), inputs=None, calls=None, items=ITEMS):
    """A stand-in for pack._run: canned JSON per script, exit 5 for any script name in ``fail``."""
    inputs = inputs or _inputs()

    def run(script, args, stdin=None, timeout=None):
        if calls is not None:
            calls.append((script, list(args)))
        if script in fail:
            return 5, {"error": f"{script} is down", "code": "API_ERROR"}, ""
        if script == "edgar.py":
            return 0, {"symbol": "ACME", "company": "Acme Corp", "annual": _annual(), "growth": {"diluted_shares_cagr": -0.02},
                       "form4": {"filings": [{"filing_date": "2026-10-01", "transactions": [{"code": "P", "shares": 10}, {"code": "S", "shares": 5}, {"code": "S", "shares": 1}, {"code": "A", "shares": 9}]}]},
                       "flags": []}, ""
        if script == "fundamentals.py":
            return 0, {"info": {"name": "Acme Corp", "market_cap": 4.0e9, "current_price": 20.0}, "statements": {}}, ""
        if script == "inputs.py":
            return 0, inputs, ""
        if script == "intrinsic-inputs.py":
            return 0, {"symbol": "ACME", "business_type": "industrial", "intrinsic_input": {"annual": _annual(), "price": 20.0}, "flags": []}, ""
        if script == "intrinsic.py":
            assert json.loads(stdin)["annual"]
            return 0, _intrinsic(), ""
        if script == "dcf.py":
            fcf0 = json.loads(stdin)["fcf0"]
            growth = (json.loads(stdin).get("stage1_growth") or [0.03])[0]
            return 0, {"fair_value_per_share": round(fcf0 / 1e7 + growth * 100, 2), "terminal_value_share_of_ev": 0.7, "implied": {"stage1_growth": 0.04}}, ""
        if script == "returns.py":
            req = json.loads(stdin)
            assert req["mode"] == "convergence" and req["price"] == 20.0
            return 0, {"scenarios": [{"name": s["name"], "irr": round(s["fair_value"] / 100, 4)} for s in req["scenarios"]], "flags": []}, ""
        if script == "sentiment.py":
            return 0, {"symbols": {"ACME": {"short_volume": None, "news": [], "analysts": {"targets": {"mean": 24.5}, "recommendations": {"count": 7}, "actions": [], "estimates": None}}}, "flags": []}, ""
        if script == "earnings.py":
            return 0, {"symbol": "ACME", "releases": [
                {"filing_date": "2026-08-26", "accession": "a-1", "exhibit": "ex991.htm", "url": "https://www.sec.gov/Archives/edgar/data/1/a/ex991.htm", "text": RELEASE_TEXT, "truncated": False},
                {"filing_date": "2026-05-28", "accession": "a-2", "exhibit": "ex991.htm", "url": "https://www.sec.gov/Archives/edgar/data/1/b/ex991.htm", "text": "Q2 results.", "truncated": True},
                {"filing_date": "2026-02-27", "accession": "a-3", "exhibit": None, "url": None, "text": None, "truncated": False}], "flags": []}, ""
        if script == "filing.py":
            base = {"symbol": "ACME", "company": "Acme Corp", "form": "10-Q" if "10-Q" in args else "10-K", "filing_date": "2026-02-20", "url": "https://www.sec.gov/Archives/edgar/data/1/x/acme.htm"}
            if "--search" in args:
                term = args[args.index("--search") + 1]
                n = 2 if term in ("material weakness", "segment") else 0
                return 0, {**base, "query": term, "count": n, "by_item": {"9A": n} if n else {},
                           "hits": [{"item": "9A", "position": 100 * (i + 1), "snippet": f"passage {i} about {term} " + "x" * 600} for i in range(n)]}, ""
            if "--diff" in args:
                return 0, {**base, "item": args[args.index("--item") + 1], "title": "T", "text": "current", "previous_words": 10, "current_words": 12, "word_delta": 2, "similarity": 0.9,
                           "added_sentences": ["A new risk about tariffs."], "removed_sentences": ["An old risk."], "added_count": 1, "removed_count": 1,
                           "previous": {"filing_date": "2025-02-21", "url": "https://www.sec.gov/Archives/edgar/data/1/y/acme.htm"}}, ""
            if "--item" in args and "10-Q" in args and args[args.index("--item") + 1] == "1":
                return 0, {**base, "item": "1", "title": "Financial Statements", "text": "Condensed Consolidated Balance Sheets. Total assets 39,000. Total liabilities 40,300. " * 20,
                           "chars": 1640, "words": 220, "truncated": False}, ""
            if "--item" in args:
                item = args[args.index("--item") + 1]
                return 0, {**base, "item": item, "title": f"Title {item}", "text": f"Body of item {item}. " * 60 + "Our reportable segment data follows. ", "chars": 1200, "words": 300, "truncated": False}, ""
            return 0, {**base, "total_words": 5000, "items": items}, ""
        raise AssertionError(f"unexpected script {script}")

    return run


def test_deep_pack_writes_every_file_and_index(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(calls=calls))
    out = pack.build("acme", tmp_path / "p", level="deep")
    root = tmp_path / "p"
    assert out["symbol"] == "ACME" and out["level"] == "deep" and out["dir"] == str(root)
    assert out["missing"] == []
    for name in DEEP_FILES:
        assert out["files"][name]["ok"] is True, name
        assert Path(out["files"][name]["path"]).is_file(), name
    index = (root / "INDEX.md").read_text()
    for name in DEEP_FILES:
        assert name in index, name
    assert "## Script commands" in index
    for script in ("edgar.py", "filing.py", "earnings.py", "fundamentals.py", "sentiment.py", "inputs.py", "dcf.py", "returns.py", "model.py"):
        assert f"/{script}" in index, script
    assert json.loads((root / "pack.json").read_text()) == out
    s = out["summary"]
    assert s["company"] == "Acme Corp" and s["price"] == 20.0 and s["market_cap"] == 4.0e9 and s["business_type"] == "industrial"
    assert {"ERP_DEFAULT", "MAINTENANCE_CAPEX_ESTIMATED"} <= set(s["flags"])
    assert s["analysts"] == {"target_mean": 24.5, "count": 7}
    assert s["insiders"] == {"buys": 1, "sells": 2}
    assert s["red_flag_hits"] == {"going concern": 0, "material weakness": 2, "restat": 0, "related part": 0, "capitalized": 0, "change in accounting": 0}
    qv = s["quick_value"]
    assert qv["basis"] == "dcf" and qv["bear"] < qv["base"] < qv["bull"] and qv["irr_5y"] == round(qv["base"] / 100, 4)
    assert json.loads((root / "quick_value.json").read_text())["base"] == qv["base"]
    # plain text, not JSON, for the filing files
    item7 = (root / "filings/10k-item7.txt").read_text()
    assert "Body of item 7." in item7 and not item7.lstrip().startswith("{")
    assert "A new risk about tariffs." in (root / "filings/10k-item1a-diff.txt").read_text()
    note = (root / "filings/segment-note.txt").read_text()
    assert "Our reportable segment data follows." in note and "Item 8" in note  # cut from Item 8's text, not the first 20 hits
    assert "filings/10k-full.txt" not in out["files"]
    # commands match the plan's table
    by = {(sc, tuple(a)) for sc, a in calls}
    assert ("edgar.py", ("ACME", "--years", "10", "--quarters", "12", "--form4", "5")) in by
    assert ("earnings.py", ("ACME", "--last", "12", "--max-chars", "40000")) in by
    assert ("filing.py", ("ACME", "--item", "8", "--max-chars", "600000")) in by
    assert ("filing.py", ("ACME", "--form", "10-Q", "--item", "2", "--max-chars", "200000")) in by
    assert ("filing.py", ("ACME", "--search", "segment", "--context", "3000")) in by
    assert ("filing.py", ("ACME", "--form", "10-Q", "--item", "1", "--max-chars", "600000")) in by
    statements = (root / "filings/10q-item1.txt").read_text()
    assert "Total liabilities 40,300" in statements and "10-Q" in statements and not statements.lstrip().startswith("{")
    assert {a[2] for sc, a in calls if sc == "filing.py" and "--search" in a and "--context" not in a} == set(TERMS_DEEP)


def test_card_pack_has_no_deep_files(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(calls=calls))
    out = pack.build("ACME", tmp_path / "c")
    assert out["level"] == "card" and out["missing"] == []
    assert sorted(out["files"]) == sorted(CARD_FILES)
    assert not (tmp_path / "c" / "filings").exists() and not (tmp_path / "c" / "forensic-checks.json").exists()
    assert ("earnings.py", ["ACME", "--last", "8"]) in calls
    assert list(out["summary"]["red_flag_hits"]) == TERMS_CARD
    assert "INDEX.md" in (tmp_path / "c" / "INDEX.md").read_text() or (tmp_path / "c" / "INDEX.md").is_file()


def test_failed_source_is_named_missing_and_index_still_written(monkeypatch, tmp_path):
    monkeypatch.setattr(pack, "_run", make_runner(fail=("earnings.py",)))
    out = pack.build("ACME", tmp_path / "p", level="deep")
    assert out["missing"] == ["earnings.json"]
    assert out["files"]["earnings.json"]["ok"] is False and "down" in out["files"]["earnings.json"]["error"]
    index = (tmp_path / "p" / "INDEX.md").read_text()
    assert "## Missing" in index and "earnings.json" in index
    assert out["summary"]["quick_value"]["basis"] == "dcf"


def test_financial_gets_the_book_value_yardstick_never_a_dcf(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(inputs=_inputs(flags=("DCF_NOT_MEANINGFUL_FOR_FINANCIALS",)), calls=calls))
    out = pack.build("ACME", tmp_path / "p")
    qv = out["summary"]["quick_value"]
    assert qv["basis"] == "book_value" and qv["base"] is None and qv["bear"] is None and qv["bull"] is None and qv["irr_5y"] is None
    assert qv["note"]
    assert json.loads((tmp_path / "p" / "quick_value.json").read_text())["book_value_tests"]["price_to_book"] == 1.6
    assert not [c for c in calls if c[0] in ("dcf.py", "returns.py")]
    assert "book_value" in (tmp_path / "p" / "INDEX.md").read_text()


def test_negative_fcf_gives_no_value(monkeypatch, tmp_path):
    monkeypatch.setattr(pack, "_run", make_runner(inputs=_inputs(flags=("NEGATIVE_FCF", "CYCLICAL"))))
    qv = pack.build("ACME", tmp_path / "p")["summary"]["quick_value"]
    assert qv["basis"] is None and qv["base"] is None and "NEGATIVE_FCF" in qv["note"]


def test_cyclical_uses_the_mid_cycle_input(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(inputs=_inputs(flags=("CYCLICAL",)), calls=calls))
    qv = pack.build("ACME", tmp_path / "p")["summary"]["quick_value"]
    assert qv["basis"] == "normalized"
    assert qv["base"] == round(120e6 / 1e7 + 3.0, 2)  # the mid-cycle fcf0, not the scenario's
    assert qv["irr_5y"] == round(qv["base"] / 100, 4)


def test_release_text_is_written_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(pack, "_run", make_runner())
    out = pack.build("ACME", tmp_path / "p")
    text = (tmp_path / "p" / "releases" / "2026-08-26.txt").read_text()
    assert RELEASE_TEXT in text and "$100M" in text
    meta = json.loads((tmp_path / "p" / "earnings.json").read_text())["releases"]
    assert meta[0]["file"] == "releases/2026-08-26.txt" and "text" not in meta[0]
    assert meta[2]["file"] is None  # the 8-K with no exhibit keeps its row
    assert "releases/2026-02-27.txt" not in out["files"]


def test_everything_but_edgar_down_still_builds(monkeypatch, tmp_path):
    down = ("fundamentals.py", "inputs.py", "intrinsic-inputs.py", "sentiment.py", "earnings.py", "filing.py")
    monkeypatch.setattr(pack, "_run", make_runner(fail=down))
    out = pack.build("ACME", tmp_path / "p", level="deep")
    assert (tmp_path / "p" / "INDEX.md").is_file()
    assert "inputs.json" in out["missing"] and "filings/10k-item8.txt" in out["missing"] and "quick_value.json" in out["missing"]
    assert out["files"]["forensic-checks.json"]["ok"] is True
    assert out["summary"]["quick_value"]["basis"] is None and out["summary"]["price"] is None


def test_unknown_ticker_and_config_missing_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(pack, "_run", lambda script, args, stdin=None, timeout=None: (2, {"error": "ZZZZ is not in the SEC ticker list", "code": "INVALID_INPUT"}, ""))
    with pytest.raises(InvalidInput, match="SEC ticker list"):
        pack.build("ZZZZ", tmp_path / "p")
    monkeypatch.setattr(pack, "_run", lambda script, args, stdin=None, timeout=None: (4, {"error": "EDGAR is not configured", "code": "CONFIG_MISSING"}, ""))
    with pytest.raises(ConfigError) as exc:
        pack.build("ACME", tmp_path / "q")
    assert exc.value.code == "CONFIG_MISSING" and exc.value.exit_code == 4
    with pytest.raises(InvalidInput):
        pack.build("ACME", tmp_path / "r", level="full")


def test_forensic_checks_findings():
    out = pack.forensic_checks(_annual())
    checks = out["checks"]
    assert checks["earnings_vs_cash"]["finding"] is True  # net income above operating cash flow in 2024 and 2025
    assert [r["fiscal_year"] for r in checks["earnings_vs_cash"]["by_year"]][-1] == 2025
    assert checks["receivables"]["finding"] is True  # DSO climbing 6 days a year on 5% revenue growth
    assert checks["inventory"]["finding"] is False  # DIO flat
    pay = checks["stock_pay"]
    assert pay["by_year"][-1]["share_of_revenue"] == 0.01 and pay["change_in_share_of_revenue"] == 0.0
    assert pay["change_in_share_of_operating_cash_flow"] > 0.05 and pay["finding"] is True  # same pay, less cash
    steady = [{**r, "operating_cash_flow": 130e6} for r in _annual()]
    assert pack.forensic_checks(steady)["checks"]["stock_pay"]["finding"] is False
    empty = pack.forensic_checks([])
    assert all(c["finding"] is False for c in empty["checks"].values())


def test_cross_reference_index_10k_falls_back_to_the_full_text(monkeypatch, tmp_path):
    """A bank's 10-K whose Items are a page index: the stubs are not fetched; the body goes to 10k-full.txt."""
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(calls=calls, items=INDEX_ITEMS))
    out = pack.build("ACME", tmp_path / "p", level="deep")
    root = tmp_path / "p"
    stubs = ["filings/10k-item1.txt", "filings/10k-item1a.txt", "filings/10k-item7.txt", "filings/10k-item8.txt", "filings/10k-item9a.txt",
             "filings/10k-item1a-diff.txt", "filings/10k-item8-diff.txt"]
    assert out["missing"] == stubs
    assert "10k-full.txt" in out["files"]["filings/10k-item8.txt"]["error"]
    assert out["files"]["filings/10k-full.txt"]["ok"] is True
    assert "Body of item 16." in (root / "filings/10k-full.txt").read_text()
    assert "Our reportable segment data follows." in (root / "filings/segment-note.txt").read_text()
    fetched = [a for sc, a in calls if sc == "filing.py" and "--item" in a and "10-Q" not in a]
    assert fetched == [["ACME", "--item", "16", "--max-chars", "600000"]]
    index = (root / "INDEX.md").read_text()
    assert "filings/10k-full.txt" in index and "never the whole file" in index


def test_yahoo_rate_limit_is_retried_once(monkeypatch, tmp_path):
    base, seen, naps = make_runner(), [], []

    def run(script, args, stdin=None, timeout=None):
        if script == "inputs.py":
            seen.append(script)
            if len(seen) == 1:
                return 5, {"error": "Too Many Requests. Rate limited. Try after a while.", "code": "API_ERROR"}, ""
        return base(script, args, stdin, timeout)

    monkeypatch.setattr(pack, "_run", run)
    monkeypatch.setattr(pack.time, "sleep", naps.append)
    pack._yahoo_limited.clear()
    out = pack.build("ACME", tmp_path / "p")
    assert out["missing"] == [] and len(seen) == 2 and naps == [pack._YAHOO_RETRY_WAIT]
    assert not pack._yahoo_limited.is_set()


def test_item_8_pointer_alone_takes_the_statements_from_the_tail_item(monkeypatch, tmp_path):
    items = [{"item": i, "title": "T", "words": 1000, "chars": 124 if i == "8" else 6000, "start": 1} for i in ("1", "1A", "7", "8", "9A")]
    items.append({"item": "16", "title": "Form 10-K Summary", "words": 30000, "chars": 173694, "start": 9})
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(calls=calls, items=items))
    out = pack.build("ACME", tmp_path / "p", level="deep")
    assert out["missing"] == ["filings/10k-item8.txt", "filings/10k-item8-diff.txt"]
    assert out["files"]["filings/10k-full.txt"]["ok"] and out["files"]["filings/10k-item1a-diff.txt"]["ok"]
    assert ("filing.py", ["ACME", "--item", "8", "--max-chars", "600000"]) not in calls
    assert "Item 16" in (tmp_path / "p" / "filings/segment-note.txt").read_text()


def _legal_item_1(search_hits: int):
    """A 10-Q whose Item 1 parses as Part II's Legal Proceedings, with ``search_hits`` passages around "total liabilities"."""
    base = make_runner()

    def run(script, args, stdin=None, timeout=None):
        if script == "filing.py" and "10-Q" in args:
            head = {"symbol": "ACME", "company": "Acme Corp", "form": "10-Q", "filing_date": "2026-08-27", "url": "https://www.sec.gov/Archives/edgar/data/1/q/acme.htm"}
            if "--item" in args and args[args.index("--item") + 1] == "1":
                return 0, {**head, "item": "1", "title": "Legal Proceedings", "text": "See Note 11, Litigation and Contingencies. " * 40, "chars": 1720, "words": 240, "truncated": False}, ""
            if "--search" in args:
                assert args[args.index("--search") + 1] == "total liabilities"
                return 0, {**head, "query": "total liabilities", "count": search_hits, "by_item": {"2": search_hits} if search_hits else {},
                           "hits": [{"item": "2", "position": 900, "snippet": "Total assets 39,000 Total liabilities 40,300 Total stockholders' deficit (1,300)"}] * search_hits}, ""
        return base(script, args, stdin, timeout)

    return run


def test_10q_item_1_that_is_legal_proceedings_is_replaced_by_the_balance_sheet_passages(monkeypatch, tmp_path):
    monkeypatch.setattr(pack, "_run", _legal_item_1(1))
    out = pack.build("ACME", tmp_path / "p", level="deep")
    assert out["missing"] == [] and out["files"]["filings/10q-item1.txt"]["ok"] is True
    text = (tmp_path / "p" / "filings/10q-item1.txt").read_text()
    assert "Total liabilities 40,300" in text and "See Note 11" not in text
    row = next(ln for ln in (tmp_path / "p" / "INDEX.md").read_text().splitlines() if "filings/10q-item1.txt" in ln)
    assert "Legal Proceedings" in row and "total liabilities" in row


def test_10q_item_1_without_statements_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(pack, "_run", _legal_item_1(0))
    out = pack.build("ACME", tmp_path / "p", level="deep")
    assert out["missing"] == ["filings/10q-item1.txt"]
    assert "Legal Proceedings" in out["files"]["filings/10q-item1.txt"]["error"]
    assert not (tmp_path / "p" / "filings/10q-item1.txt").exists()
    assert out["files"]["filings/10q-item2.txt"]["ok"] is True


def test_card_pack_never_reads_the_10q(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(calls=calls))
    out = pack.build("ACME", tmp_path / "c")
    assert "filings/10q-item1.txt" not in out["files"] and not [a for sc, a in calls if "10-Q" in a]


def test_statements_in_another_currency_give_no_quick_value(monkeypatch, tmp_path):
    """TSM: cash flows in TWD against a USD price made a base of 3,757 and a 75% return."""
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(inputs=_inputs(flags=("CURRENCY_MISMATCH",)), calls=calls))
    out = pack.build("ACME", tmp_path / "p")
    qv = out["summary"]["quick_value"]
    assert qv["basis"] is None and qv["bear"] is None and qv["base"] is None and qv["bull"] is None and qv["irr_5y"] is None
    assert "CURRENCY_MISMATCH" in qv["note"]
    assert "CURRENCY_MISMATCH" in out["summary"]["flags"]
    assert "CURRENCY_MISMATCH" in out["summary"]["flag_notes"]
    assert not [c for c in calls if c[0] in ("dcf.py", "returns.py")]
    saved = json.loads((tmp_path / "p" / "quick_value.json").read_text())
    assert saved["base"] is None and saved["irr_5y"] is None and not saved.get("scenarios")
    head = (tmp_path / "p" / "INDEX.md").read_text().split("## Headline figures")[0]
    assert "CURRENCY_MISMATCH" in head


def test_a_financial_in_another_currency_keeps_its_yardstick_and_the_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(pack, "_run", make_runner(inputs=_inputs(flags=("DCF_NOT_MEANINGFUL_FOR_FINANCIALS", "CURRENCY_MISMATCH"))))
    out = pack.build("ACME", tmp_path / "p")
    qv = out["summary"]["quick_value"]
    assert qv["basis"] == "book_value" and qv["base"] is None and "CURRENCY_MISMATCH" in qv["note"]


def test_dotted_ticker_is_built_as_the_dash_form(monkeypatch, tmp_path):
    """BRK.B: the SEC list and Yahoo both write BRK-B, so every script gets that."""
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(calls=calls))
    out = pack.build("brk.b", tmp_path / "p")
    assert out["symbol"] == "BRK-B" and out["requested"] == "BRK.B"
    firsts = {a[0] for sc, a in calls if a and sc not in ("dcf.py", "returns.py", "intrinsic.py")}
    assert firsts == {"BRK-B"}
    assert pack.canonical_symbol("brk.b") == "BRK-B" and pack.canonical_symbol("BRK-B") == "BRK-B" and pack.canonical_symbol("hpq") == "HPQ"
    assert pack.build("ACME", tmp_path / "q")["requested"] == "ACME"


def _thin_runner(index):
    """XOM's successor registrant: no annual facts under the new CIK, so edgar.py exits 2 and only
    --filings-only answers; filing.py finds no 10-K."""
    base = make_runner()

    def run(script, args, stdin=None, timeout=None):
        if script == "edgar.py":
            if "--filings-only" in args:
                return 0, index, ""
            return 2, {"error": "no annual (10-K) facts found", "code": "INVALID_INPUT"}, ""
        if script == "intrinsic-inputs.py":
            return 2, {"error": "no annual (10-K) facts found", "code": "INVALID_INPUT"}, ""
        if script == "filing.py" and "10-Q" not in args:
            return 2, {"error": "no 10-K filing for ACME on EDGAR", "code": "INVALID_INPUT"}, ""
        return base(script, args, stdin=stdin, timeout=timeout)

    return run


THIN_INDEX = {"symbol": "ACME", "company": "Acme Holdings Corp", "filings": {"counts": {"10-Q": 2, "8-K12B": 1}, "latest_10k": None, "latest_10q": {"form": "10-Q", "date": "2026-11-02"}},
              "flags": [], "form4": {"filings": []}}


@pytest.mark.parametrize("level", ["card", "deep"])
def test_successor_registrant_is_flagged_thin(monkeypatch, tmp_path, level):
    monkeypatch.setattr(pack, "_run", _thin_runner(THIN_INDEX))
    out = pack.build("ACME", tmp_path / "p", level=level)
    s = out["summary"]
    assert "THIN_EDGAR_HISTORY" in s["flags"]
    note = s["flag_notes"]["THIN_EDGAR_HISTORY"]
    assert "predecessor" in note and "no annual" in note and "no 10-K" in note
    assert s["quick_value"]["basis"] == "dcf"  # Yahoo's figures still stand; the flag says what they are not checked against
    index = (tmp_path / "p" / "INDEX.md").read_text()
    head = index.split("## Headline figures")[0]
    assert "THIN_EDGAR_HISTORY" in head and "predecessor" in head
    assert json.loads((tmp_path / "p" / "pack.json").read_text())["summary"]["flags"] == s["flags"]


def test_annual_rows_without_a_10k_in_the_index_is_thin_and_a_full_pack_is_not(monkeypatch, tmp_path):
    base = make_runner()

    def run(script, args, stdin=None, timeout=None):
        rc, data, err = base(script, args, stdin=stdin, timeout=timeout)
        if script == "edgar.py":
            data = {**data, "filings": {"latest_10k": None}}
        return rc, data, err

    monkeypatch.setattr(pack, "_run", run)
    s = pack.build("ACME", tmp_path / "p")["summary"]
    assert "THIN_EDGAR_HISTORY" in s["flags"] and "no 10-K" in s["flag_notes"]["THIN_EDGAR_HISTORY"] and "no annual" not in s["flag_notes"]["THIN_EDGAR_HISTORY"]

    monkeypatch.setattr(pack, "_run", make_runner())
    full = pack.build("ACME", tmp_path / "q")
    assert "THIN_EDGAR_HISTORY" not in full["summary"]["flags"] and full["summary"]["flag_notes"] == {}
    assert "THIN_EDGAR_HISTORY" not in (tmp_path / "q" / "INDEX.md").read_text()


def test_edgar_down_entirely_is_not_called_thin(monkeypatch, tmp_path):
    monkeypatch.setattr(pack, "_run", make_runner(fail=("edgar.py",)))
    out = pack.build("ACME", tmp_path / "p")
    assert "edgar.json" in out["missing"] and "THIN_EDGAR_HISTORY" not in out["summary"]["flags"]


def test_item_8_pointer_with_a_longer_item_1_still_takes_the_tail_item(monkeypatch, tmp_path):
    """PRDO's 10-K: Item 1 (Business) is longer than the Item 16 that holds the statements."""
    items = [{"item": i, "title": "T", "words": 1000, "chars": {"8": 113, "1": 154482}.get(i, 6000), "start": 1} for i in ("1", "1A", "7", "8", "9A")]
    items.append({"item": "16", "title": "Form 10-K Summary", "words": 30000, "chars": 148258, "start": 9})
    calls: list = []
    monkeypatch.setattr(pack, "_run", make_runner(calls=calls, items=items))
    out = pack.build("ACME", tmp_path / "p", level="deep")
    assert out["files"]["filings/10k-full.txt"]["ok"] is True
    assert "10k-full.txt" in out["files"]["filings/10k-item8.txt"]["error"]
    assert ("filing.py", ["ACME", "--item", "1", "--max-chars", "600000"]) in calls


def test_10q_statements_that_parse_under_another_item_are_taken_whole(monkeypatch, tmp_path):
    """PRDO's 10-Q: Item 1 is a 389-character pointer and the statements parse as Item 6."""
    base = make_runner()

    def run(script, args, stdin=None, timeout=None):
        if script == "filing.py" and "10-Q" in args:
            head = {"symbol": "ACME", "company": "Acme Corp", "form": "10-Q", "filing_date": "2026-11-05", "url": "https://www.sec.gov/Archives/edgar/data/1/q/acme.htm"}
            if "--item" not in args and "--search" not in args:
                return 0, {**head, "items": [{"item": "1", "title": "", "chars": 389}, {"item": "6", "title": "", "chars": 64068}, {"item": "2", "title": "MD&A", "chars": 37332}]}, ""
            if "--item" in args and args[args.index("--item") + 1] == "1":
                return 0, {**head, "item": "1", "title": "", "text": "Financial Statements 1 " * 15, "chars": 389, "truncated": False}, ""
            if "--item" in args and args[args.index("--item") + 1] == "6":
                return 0, {**head, "item": "6", "title": "", "text": "CONDENSED CONSOLIDATED BALANCE SHEETS " + "Cash $188.5 " * 200 + "Total assets 1,300,000 Total liabilities 300,000", "chars": 64068, "truncated": False}, ""
        return base(script, args, stdin, timeout)

    monkeypatch.setattr(pack, "_run", run)
    out = pack.build("ACME", tmp_path / "p", level="deep")
    assert out["files"]["filings/10q-item1.txt"]["ok"] is True
    text = (tmp_path / "p" / "filings/10q-item1.txt").read_text()
    assert "Total liabilities 300,000" in text and "Cash $188.5" in text
    row = next(ln for ln in (tmp_path / "p" / "INDEX.md").read_text().splitlines() if "filings/10q-item1.txt" in ln)
    assert "Item 6" in row
