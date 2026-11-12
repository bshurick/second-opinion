"""pool.py: the deep picker's merged candidate pool and its health check. No network: the health
screen is a fake."""

from __future__ import annotations

import json

from scripts_util import load_script, run_json

pool = load_script("stock-screener/scripts/pool.py")


def industry(name, sector, prospects, leaders=(), verdict="neutral", contrarian=False) -> dict:
    return {"sector": sector, "industry": name, "verdict": verdict, "contrarian": contrarian,
            "temperature": "t", "growth": "g", "sentiment": "s",
            "leaders": [{"ticker": t, "name": f"{t} Corp", "trend": "steady"} for t in leaders],
            "prospects": [{"ticker": t, "name": f"{t} Inc", "market_cap": 2.0e9, "why": f"{t} passes; a $100M buyback"} for t in prospects],
            "evidence": [{"claim": "c", "source": "s", "date": "2026-09-30"}]}


def screen(tickers, flags=(), held=(), sector=None) -> dict:
    return {"preset": "value", "flags": [{"code": c, "message": "m"} for c in flags],
            "survivors": [{"ticker": t, "name": f"{t} CO", "metrics": {"sector": sector} if sector else {}, "held": t in held} for t in tickers]}


def make_run(tmp_path, industries: dict, screens: dict):
    run = tmp_path / "run"
    for sub in ("industries", "screen", "cards", "context"):
        (run / sub).mkdir(parents=True)
    for name, objs in industries.items():
        (run / "industries" / f"{name}.json").write_text(json.dumps(objs))
    for name, data in screens.items():
        (run / "screen" / f"{name}.json").write_text(json.dumps(data))
    return run


def fake_health(monkeypatch, failed=None, financial=(), not_found=(), incomplete=(), seen=None, rc=0):
    failed = failed or {}

    def run_health(symbols, held):
        if seen is not None:
            seen.append((list(symbols), list(held)))
        if rc:
            return rc, {"error": "EDGAR returned HTTP 503", "code": "EDGAR_HTTP"}
        checked = [{"ticker": s, "primary": s, "name": f"{s} CO", "passed": s not in failed and s not in financial,
                    "failed": failed.get(s, ["financial_filer"] if s in financial else []), "financial": s in financial}
                   for s in sorted(symbols) if s not in not_found and s not in incomplete]
        return 0, {"preset": "health", "checked": checked, "not_found": sorted(not_found), "incomplete": sorted(incomplete), "survivors": [], "flags": []}

    monkeypatch.setattr(pool, "run_health", run_health)


def test_merge_origin_leaders_and_held(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, {
        "group3": [industry("Railroads", "Industrials", ["GWR", "BOTH"], leaders=["UNP", "LEAD"], verdict="favored"),
                   industry("Steel", "Materials", ["STL"], verdict="unfavored", contrarian=True)],
        "group2": [industry("Banks", "Financials", ["BNK"])],
    }, {"value": screen(["BOTH", "SCR", "LEAD"], held=["SCR"]), "quality": screen(["SCR", "QQ"], sector="Technology")})
    (run / "industries" / "group3.md").write_text("notes")
    seen: list = []
    fake_health(monkeypatch, seen=seen)
    rc, out = run_json(pool, ["--run", str(run), "--held", "gwr,ZZZ"], capsys)
    assert rc == 0, out
    saved = json.loads((run / "pool.json").read_text())
    by = {n["ticker"]: n for n in saved["names"]}
    assert set(by) == {"GWR", "BOTH", "STL", "BNK", "SCR", "LEAD", "QQ"}  # UNP is a leader only
    assert by["BOTH"]["origin"] == "both" and by["GWR"]["origin"] == "industry" and by["SCR"]["origin"] == "screen"
    assert by["BOTH"]["industry"] == "Railroads" and by["BOTH"]["sector"] == "Industrials"
    assert by["BOTH"]["industry_verdict"] == "favored" and by["BOTH"]["contrarian"] is False
    assert by["STL"]["industry_verdict"] == "unfavored" and by["STL"]["contrarian"] is True
    assert by["GWR"]["why"] == "GWR passes; a $100M buyback"
    assert "GWR passes; a $100M buyback" in (run / "pool.json").read_text()
    assert by["SCR"]["screens"] == ["quality", "value"] and by["BOTH"]["screens"] == ["value"]
    # a leader that a screen found enters as a screen name and takes its industry from the scan
    assert by["LEAD"]["origin"] == "screen" and by["LEAD"]["industry"] == "Railroads" and by["LEAD"]["industry_verdict"] == "favored"
    assert by["QQ"]["industry"] is None and by["QQ"]["sector"] == "Technology" and by["QQ"]["industry_verdict"] is None
    assert by["GWR"]["held"] is True and by["SCR"]["held"] is True and by["BOTH"]["held"] is False
    assert all(n["health"] == "passed" and n["failed_tests"] == [] for n in saved["names"])
    assert sorted(seen[0][0]) == sorted(by) and seen[0][1] == ["GWR", "ZZZ"]
    assert json.loads((run / "screen" / "health.json").read_text())["preset"] == "health"
    assert saved["counts"]["industries"] == 3 and saved["counts"]["prospects"] == 4 and saved["counts"]["screen_survivors"] == 4
    assert saved["counts"]["merged"] == 7 and saved["counts"]["kept"] == 7 and saved["counts"]["dropped"] == 0
    assert saved["counts"]["origin"] == {"industry": 3, "screen": 3, "both": 1}
    assert out["counts"] == saved["counts"] and out["batches"] == saved["batches"] and out["pool"] == str(run / "pool.json")
    assert out["flags"] == []


def test_rerun_does_not_read_health_as_a_screen(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, {"group1": [industry("Retail", "Consumer Discretionary", ["AAA"])]}, {"value": screen(["BBB"])})
    (run / "screen" / "health.json").write_text(json.dumps(screen(["GHOST"])))
    fake_health(monkeypatch)
    rc, out = run_json(pool, ["--run", str(run)], capsys)
    assert rc == 0 and [n["ticker"] for n in json.loads((run / "pool.json").read_text())["names"]] == ["AAA", "BBB"]


def test_trim_keeps_every_both_and_alternates(monkeypatch, capsys, tmp_path):
    prospects = [f"P{i:02d}" for i in range(20)] + ["B1", "B2", "B3"]
    survivors = ["B1", "B2", "B3"] + [f"S{i:02d}" for i in range(27)]
    run = make_run(tmp_path, {"group1": [industry("Retail", "Consumer Discretionary", prospects[:12], verdict="unfavored"),
                                         industry("Media", "Communication Services", prospects[12:], verdict="favored")]},
                   {"value": screen(survivors)})
    fake_health(monkeypatch)
    rc, out = run_json(pool, ["--run", str(run)], capsys)
    assert rc == 0, out
    saved = json.loads((run / "pool.json").read_text())
    names = [n["ticker"] for n in saved["names"]]
    assert len(names) == 40 and {"B1", "B2", "B3"} <= set(names)
    kept_p, kept_s = [t for t in names if t.startswith("P")], [t for t in names if t.startswith("S")]
    assert abs(len(kept_p) - len(kept_s)) <= 1  # prospects and survivors alternately
    assert kept_s == [f"S{i:02d}" for i in range(len(kept_s))]  # the screen's own order
    assert {"P00", "P12"} <= set(kept_p)  # never on the verdict: both industries keep their first prospects
    assert saved["counts"]["candidates"] == 50 and saved["counts"]["merged"] == 40 and saved["counts"]["trimmed"] == 10
    assert len(saved["trimmed"]) == 10 and not set(saved["trimmed"]) & set(names)
    assert [f["code"] for f in out["flags"]] == ["POOL_TRIMMED"]
    assert all(len(b) <= 5 for b in out["batches"]) and sorted(t for b in out["batches"] for t in b) == sorted(names)

    rc, out = run_json(pool, ["--run", str(run), "--max", "12"], capsys)
    assert rc == 0 and out["counts"]["merged"] == 12 and len(out["batches"]) == 3


def test_health_statuses_drops_and_batches(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, {
        "group2": [industry("Asset Managers", "Financials", ["AMG", "BANK"]), industry("Utilities", "Utilities", ["UTL"])],
        "group3": [industry("Machinery", "Industrials", ["IND1", "IND2", "IND3", "IND4", "IND5", "IND6"])],
    }, {"value": screen(["FOREIGN", "NEWCO", "YFIN"]), "smallcap": screen(["YFIN"], sector="Financial Services")})
    fake_health(monkeypatch, failed={"AMG": ["max_net_debt_to_ebit"], "IND2": ["min_piotroski", "max_share_growth"], "YFIN": ["min_fcf_margin_avg"]},
                financial=("BANK",), not_found=("FOREIGN",), incomplete=("NEWCO",))
    rc, out = run_json(pool, ["--run", str(run)], capsys)
    assert rc == 0, out
    saved = json.loads((run / "pool.json").read_text())
    by = {n["ticker"]: n for n in saved["names"]}
    assert by["AMG"]["health"] == "judge_in_quick_read" and by["AMG"]["failed_tests"] == ["max_net_debt_to_ebit"]
    assert by["YFIN"]["health"] == "judge_in_quick_read"  # Yahoo's name for the sector counts too
    assert by["BANK"]["health"] == "financial" and by["FOREIGN"]["health"] == "not_found" and by["NEWCO"]["health"] == "incomplete"
    assert by["IND1"]["health"] == "passed" and "IND2" not in by
    assert saved["dropped"] == [{"ticker": "IND2", "name": "IND2 Inc", "industry": "Machinery", "origin": "industry", "held": False,
                                 "health": "failed", "failed_tests": ["min_piotroski", "max_share_growth"]}]
    assert out["dropped"] == [{"ticker": "IND2", "failed_tests": ["min_piotroski", "max_share_growth"]}]
    assert saved["counts"]["kept"] == 11 and saved["counts"]["dropped"] == 1
    assert saved["counts"]["health"] == {"passed": 6, "judge_in_quick_read": 2, "financial": 1, "not_found": 1, "incomplete": 1, "failed": 1}
    batches = saved["batches"]
    assert all(1 <= len(b) <= 5 for b in batches) and sorted(t for b in batches for t in b) == sorted(by)
    flat = [t for b in batches for t in b]
    machinery = [flat.index(t) for t in ("IND1", "IND3", "IND4", "IND5", "IND6")]
    assert machinery == list(range(machinery[0], machinery[0] + 5))  # one industry sits together
    assert abs(flat.index("AMG") - flat.index("BANK")) == 1


def test_rate_limited_screen_is_flagged_by_name(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, {"group1": [industry("Retail", "Consumer Discretionary", ["AAA"])]},
                   {"value": screen(["BBB"]), "quality": screen(["CCC"], flags=["UNPRICED", "PRICING_INCOMPLETE"])})
    fake_health(monkeypatch)
    rc, out = run_json(pool, ["--run", str(run)], capsys)
    assert rc == 0
    flag = next(f for f in out["flags"] if f["code"] == "PRICING_INCOMPLETE")
    assert "quality" in flag["message"] and "value" not in flag["message"]
    assert flag["screens"] == ["quality"]


def test_health_check_down_keeps_every_name_unchecked(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, {"group1": [industry("Retail", "Consumer Discretionary", ["AAA"])]}, {"value": screen(["BBB"])})
    fake_health(monkeypatch, rc=5)
    rc, out = run_json(pool, ["--run", str(run)], capsys)
    assert rc == 0
    saved = json.loads((run / "pool.json").read_text())
    assert [n["health"] for n in saved["names"]] == ["unchecked", "unchecked"] and saved["dropped"] == []
    assert [f["code"] for f in out["flags"]] == ["HEALTH_CHECK_FAILED"] and "503" in out["flags"][0]["message"]
    assert not (run / "screen" / "health.json").exists()


def test_unreadable_files_are_flagged_and_skipped(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, {"group1": [industry("Retail", "Consumer Discretionary", ["AAA", "not a ticker!"])], "scan1-scratch": {"not": "a list"}},
                   {"value": screen(["BBB"])})
    (run / "industries" / "group2.json").write_text("{broken")
    (run / "screen" / "quality.json").write_text("nope")
    fake_health(monkeypatch)
    rc, out = run_json(pool, ["--run", str(run)], capsys)
    assert rc == 0
    codes = [f["code"] for f in out["flags"]]
    assert codes.count("INDUSTRY_FILE_SKIPPED") == 2 and "SCREEN_FILE_SKIPPED" in codes and "PROSPECT_SKIPPED" in codes
    assert out["counts"]["merged"] == 2


def test_bad_input_is_exit_2(monkeypatch, capsys, tmp_path):
    fake_health(monkeypatch)
    rc, out = run_json(pool, ["--run", str(tmp_path / "nope")], capsys)
    assert rc == 2 and "error" in out
    run = make_run(tmp_path, {}, {})
    rc, out = run_json(pool, ["--run", str(run)], capsys)
    assert rc == 2 and "nothing to merge" in out["error"] and not (run / "pool.json").exists()
    run2 = make_run(tmp_path / "b", {"group1": [industry("Retail", "Consumer Discretionary", ["AAA"])]}, {})
    for argv in (["--run", str(run2), "--max", "0"], ["--run", str(run2), "--held", "$$"], []):
        rc, out = run_json(pool, argv, capsys)
        assert rc == 2 and "error" in out


def test_dotted_and_dashed_share_classes_are_one_name(monkeypatch, capsys, tmp_path):
    """A scanner writes BRK.B, the screen (the SEC list) BRK-B: one row found both ways, held either way."""
    run = make_run(tmp_path, {"group1": [industry("Insurance", "Financials", ["BRK.B", "AAA"], leaders=["BF.B"])]},
                   {"value": screen(["BRK-B", "BF-B"]), "quality": screen(["brk.b"])})
    seen: list = []
    fake_health(monkeypatch, seen=seen)
    rc, out = run_json(pool, ["--run", str(run), "--held", "BRK.B"], capsys)
    assert rc == 0, out
    saved = json.loads((run / "pool.json").read_text())
    by = {n["ticker"]: n for n in saved["names"]}
    assert set(by) == {"BRK-B", "AAA", "BF-B"}
    assert by["BRK-B"]["origin"] == "both" and by["BRK-B"]["held"] is True and by["BRK-B"]["screens"] == ["quality", "value"]
    assert by["BF-B"]["leader"] is True and by["BF-B"]["industry"] == "Insurance"
    assert saved["counts"]["candidates"] == 3 and saved["counts"]["origin"] == {"industry": 1, "screen": 1, "both": 1} and saved["counts"]["held"] == 1
    assert sorted(seen[0][0]) == ["AAA", "BF-B", "BRK-B"] and seen[0][1] == ["BRK-B"]
    assert by["BRK-B"]["health"] == "passed"

    run2 = make_run(tmp_path / "second", {"group1": [industry("Insurance", "Financials", ["BRK.B"])]}, {})
    fake_health(monkeypatch)
    rc, out = run_json(pool, ["--run", str(run2), "--held", "brk-b"], capsys)
    assert rc == 0 and json.loads((run2 / "pool.json").read_text())["names"][0]["held"] is True


def test_health_rows_in_the_dotted_form_still_match(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, {"group1": [industry("Insurance", "Industrials", ["BRK.B", "BF.B", "AAA"])]}, {})

    def run_health(symbols, held):
        return 0, {"checked": [{"ticker": "BRK.B", "passed": False, "failed": ["fcf_positive"], "financial": False}, {"ticker": "AAA", "passed": True, "failed": [], "financial": False}],
                   "not_found": ["BF.B"], "incomplete": []}

    monkeypatch.setattr(pool, "run_health", run_health)
    rc, out = run_json(pool, ["--run", str(run)], capsys)
    assert rc == 0, out
    assert out["counts"]["health"] == {"passed": 1, "not_found": 1, "failed": 1} and out["dropped"] == [{"ticker": "BRK-B", "failed_tests": ["fcf_positive"]}]
