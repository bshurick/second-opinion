"""cards.py: one card research pack and one data file per pool name. pack.build is a fake, so
nothing is fetched."""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path

import pytest
from scripts_util import load_script, run_json

from second_opinion.errors import ConfigError, InvalidInput

cards = load_script("stock-screener/scripts/cards.py")
TODAY = dt.date.today().isoformat()


def pool_row(ticker, **over) -> dict:
    row = {"ticker": ticker, "name": f"{ticker} Inc", "origin": "industry", "held": False, "industry": "Railroads", "sector": "Industrials",
           "industry_verdict": "favored", "contrarian": False, "market_cap": 2.1e9, "why": "FCF 4 of 4 years; a $100M buyback", "screens": [],
           "leader": False, "health": "passed", "failed_tests": []}
    row.update(over)
    return row


def make_run(tmp_path, tickers=("AAA", "BBB", "CCC")):
    run = tmp_path / "run"
    (run / "cards").mkdir(parents=True)
    (run / "pool.json").write_text(json.dumps({"names": [pool_row(t) for t in tickers], "dropped": [], "counts": {}, "batches": [list(tickers)]}))
    return run


def fake_build(irr=None, flags=(), hits=None, fail=None, calls=None, as_of=TODAY, file_errors=None, wait=0.0, running=None, news_down=()):
    irr, hits, fail, file_errors = irr or {}, hits or {}, fail or {}, file_errors or {}

    def build(symbol, out_dir, level="card", workers=4):
        if calls is not None:
            calls.append((symbol, level))
        if running is not None:
            with running["lock"]:
                running["now"] += 1
                running["most"] = max(running["most"], running["now"])
            time.sleep(wait)
            with running["lock"]:
                running["now"] -= 1
        if symbol in fail:
            raise fail[symbol]
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        rate = irr.get(symbol)
        qv = {"basis": "dcf" if rate is not None else None, "bear": 40.0, "base": 62.5, "bull": 80.0, "irr_5y": rate, "note": "Untested defaults; a $100M charge."}
        (out_dir / "quick_value.json").write_text(json.dumps({"symbol": symbol, "as_of": as_of, **qv, "price": 50.0, "scenarios": {"base": {"fair_value_per_share": 62.5}}}))
        yoy = [0.05, 0.04, -0.01, 0.03, 0.02, -0.02, 0.06, 0.07, 0.01]  # the last 8: 6 up
        (out_dir / "edgar.json").write_text(json.dumps({"quarterly": [{"revenue_yoy": y} for y in yoy], "ttm": {"revenue_ttm_yoy": 0.041}}))
        (out_dir / "INDEX.md").write_text("# index\n")
        if symbol in news_down:
            (out_dir / "sentiment.json").write_text(json.dumps({"symbols": {}, "flags": [{"code": "NEWS_UNAVAILABLE", "message": f"{symbol}: news fetch failed (Too Many Requests)"}]}))
        names = ("edgar.json", "inputs.json", "sentiment.json", "quick_value.json")
        errors = file_errors.get(symbol, {})
        files = {n: {"path": str(out_dir / n), "ok": n not in errors, **({"error": errors[n]} if n in errors else {})} for n in names}
        pack = {"symbol": symbol, "as_of": as_of, "level": level, "dir": str(out_dir), "index": str(out_dir / "INDEX.md"), "files": files,
                "missing": [n for n in names if n in errors],
                "summary": {"company": f"{symbol} Corp", "price": 50.0, "market_cap": 2.2e9, "business_type": "industrial",
                            "flags": [*flags, "ERP_DEFAULT"], "quick_value": qv, "analysts": {"target_mean": 61.0, "count": 7},
                            "red_flag_hits": hits, "insiders": {"buys": 2, "sells": 1}}}
        (out_dir / "pack.json").write_text(json.dumps(pack))
        return pack

    return build


@pytest.mark.parametrize("irr, hint", [(0.31, 5), (0.15, 5), (0.1499, 4), (0.10, 4), (0.0999, 3), (0.06, 3), (0.0599, 2), (0.0, 2), (-0.0001, 1), (-0.4, 1), (None, None)])
def test_value_hint_thresholds(irr, hint):
    assert cards.value_hint(irr) == hint


def test_builds_a_pack_and_a_data_file_per_name(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path)
    calls: list = []
    monkeypatch.setattr(cards.pack, "build", fake_build(
        irr={"AAA": 0.17, "BBB": 0.03}, flags=("CYCLICAL", "LARGE_MINORITY_INTEREST", "NEGATIVE_FCF"),
        hits={"going concern": 0, "material weakness": 2, "restat": 5, "related part": 0}, calls=calls))
    rc, out = run_json(cards, ["--run", str(run)], capsys)
    assert rc == 0, out
    assert sorted(calls) == [("AAA", "card"), ("BBB", "card"), ("CCC", "card")]
    assert [c["ticker"] for c in out["cards"]] == ["AAA", "BBB", "CCC"] and out["failed"] == []
    assert [c["value_hint"] for c in out["cards"]] == [5, 2, None]
    assert all(c["status"] == "built" and c["missing"] == [] for c in out["cards"])
    assert out["cards"][0]["data"] == str(run / "cards" / "AAA.data.json")
    assert (run / "cards" / "AAA" / "pack.json").is_file()
    raw = (run / "cards" / "AAA.data.json").read_text()
    data = json.loads(raw)
    for key, value in pool_row("AAA").items():  # the pool row, unchanged
        assert data[key] == value
    assert "FCF 4 of 4 years; a $100M buyback" in raw and "Untested defaults; a $100M charge." in raw
    assert data["quick_value"]["base"] == 62.5 and data["quick_value"]["irr_5y"] == 0.17 and data["quick_value"]["scenarios"]["base"]["fair_value_per_share"] == 62.5
    assert data["value_hint"] == 5
    assert data["red_flags"] == {"inputs_flags": ["LARGE_MINORITY_INTEREST", "CYCLICAL"], "terms": {"material weakness": 2, "restat": 5}}
    assert data["direction"] == {"quarters_up_of_8": 6, "ttm_revenue_growth": 0.041}
    assert data["analysts"] == {"target_mean": 61.0, "count": 7} and data["insiders"] == {"buys": 2, "sells": 1}
    assert data["index"] == str(run / "cards" / "AAA" / "INDEX.md")
    assert data["price"] == 50.0 and data["missing"] == [] and data["pack_as_of"] == TODAY
    assert out["counts"] == {"names": 3, "built": 3, "skipped": 0, "failed": 0}


def test_failing_pack_is_listed_never_an_exit(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, ("AAA", "NOPE", "CFG", "BOOM"))
    monkeypatch.setattr(cards.pack, "build", fake_build(irr={"AAA": 0.12}, fail={
        "NOPE": InvalidInput("NOPE is not in the SEC ticker list"), "CFG": ConfigError("EDGAR_USER_AGENT is not set", code="EDGAR_NOT_CONFIGURED"),
        "BOOM": RuntimeError("disk full")}))
    rc, out = run_json(cards, ["--run", str(run)], capsys)
    assert rc == 0, out
    assert [c["ticker"] for c in out["cards"]] == ["AAA"]
    assert {f["ticker"]: f["error"] for f in out["failed"]} == {
        "NOPE": "NOPE is not in the SEC ticker list", "CFG": "EDGAR_USER_AGENT is not set", "BOOM": "RuntimeError: disk full"}
    assert not (run / "cards" / "NOPE.data.json").exists()
    assert out["counts"]["failed"] == 3 and [f["code"] for f in out["flags"]] == ["PACK_FAILED"]


def test_rerun_skips_todays_packs_and_fetches_only_what_is_missing(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path)
    calls: list = []
    monkeypatch.setattr(cards.pack, "build", fake_build(irr={"AAA": 0.2}, fail={"CCC": RuntimeError("Too Many Requests")}, calls=calls))
    rc, out = run_json(cards, ["--run", str(run)], capsys)
    assert rc == 0 and [f["ticker"] for f in out["failed"]] == ["CCC"]

    calls.clear()
    (run / "cards" / "AAA.data.json").unlink()  # the data file is rewritten from the pack on disk
    monkeypatch.setattr(cards.pack, "build", fake_build(irr={"CCC": 0.07}, calls=calls))
    rc, out = run_json(cards, ["--run", str(run)], capsys)
    assert rc == 0 and calls == [("CCC", "card")]
    assert [(c["ticker"], c["status"]) for c in out["cards"]] == [("AAA", "skipped"), ("BBB", "skipped"), ("CCC", "built")]
    assert out["cards"][0]["value_hint"] == 5 and json.loads((run / "cards" / "AAA.data.json").read_text())["value_hint"] == 5
    assert out["counts"] == {"names": 3, "built": 1, "skipped": 2, "failed": 0}

    calls.clear()
    rc, out = run_json(cards, ["--run", str(run), "--symbols", "bbb", "--force"], capsys)
    assert rc == 0 and calls == [("BBB", "card")] and [(c["ticker"], c["status"]) for c in out["cards"]] == [("BBB", "built")]

    calls.clear()  # a pack from another day is stale: built again
    stale = json.loads((run / "cards" / "AAA" / "pack.json").read_text())
    (run / "cards" / "AAA" / "pack.json").write_text(json.dumps({**stale, "as_of": "2026-01-02"}))
    (run / "cards" / "BBB" / "pack.json").write_text("{half")
    rc, out = run_json(cards, ["--run", str(run)], capsys)
    assert rc == 0 and sorted(calls) == [("AAA", "card"), ("BBB", "card")]


def test_three_packs_at_a_time_by_default(monkeypatch, capsys, tmp_path):
    assert cards.DEFAULT_WORKERS == 3
    run = make_run(tmp_path, tuple(f"T{i}" for i in range(8)))
    running = {"now": 0, "most": 0, "lock": threading.Lock()}
    monkeypatch.setattr(cards.pack, "build", fake_build(wait=0.03, running=running))
    rc, out = run_json(cards, ["--run", str(run)], capsys)
    assert rc == 0 and out["counts"]["built"] == 8 and 1 < running["most"] <= 3
    running.update(now=0, most=0)
    rc, out = run_json(cards, ["--run", str(run), "--force", "--workers", "1"], capsys)
    assert rc == 0 and running["most"] == 1


def test_rate_limited_parts_are_flagged_with_the_rerun(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path)
    monkeypatch.setattr(cards.pack, "build", fake_build(file_errors={"BBB": {"sentiment.json": "sentiment.py exit 5: Too Many Requests. Rate limited. Try after a while."}}, news_down=("CCC",)))
    rc, out = run_json(cards, ["--run", str(run)], capsys)
    assert rc == 0 and out["cards"][1]["missing"] == ["sentiment.json"]
    assert [c["sentiment_flags"] for c in out["cards"]] == [[], [], ["NEWS_UNAVAILABLE"]]  # built, but a part Yahoo refused
    assert json.loads((run / "cards" / "CCC.data.json").read_text())["sentiment_flags"] == ["NEWS_UNAVAILABLE"]
    flag = next(f for f in out["flags"] if f["code"] == "YAHOO_RATE_LIMITED")
    assert flag["tickers"] == ["BBB", "CCC"] and "--symbols BBB,CCC --force" in flag["message"]
    assert json.loads((run / "cards" / "BBB.data.json").read_text())["missing"] == ["sentiment.json"]


def test_bad_input_is_exit_2(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cards.pack, "build", fake_build())
    rc, out = run_json(cards, ["--run", str(tmp_path / "nope")], capsys)
    assert rc == 2 and "pool.json" in out["error"]
    run = make_run(tmp_path)
    for argv in (["--run", str(run), "--symbols", "ZZZ"], ["--run", str(run), "--workers", "0"], ["--run", str(run), "--symbols", "$$"], []):
        rc, out = run_json(cards, argv, capsys)
        assert rc == 2 and "error" in out
    assert not list((run / "cards").iterdir())


def test_currency_mismatch_never_gets_a_value_hint(monkeypatch, capsys, tmp_path):
    """TSM's 75% "return" (TWD cash flows on a USD price) read as value_hint 5."""
    run = make_run(tmp_path)
    monkeypatch.setattr(cards.pack, "build", fake_build(irr={"AAA": 0.75}, flags=("CURRENCY_MISMATCH", "THIN_EDGAR_HISTORY")))
    rc, out = run_json(cards, ["--run", str(run), "--symbols", "AAA"], capsys)
    assert rc == 0, out
    assert out["cards"][0]["value_hint"] is None
    data = json.loads((run / "cards" / "AAA.data.json").read_text())
    assert data["value_hint"] is None
    assert data["red_flags"]["inputs_flags"] == ["CURRENCY_MISMATCH", "THIN_EDGAR_HISTORY"]


def test_dotted_symbols_match_the_pool_dash_form(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, tickers=("BRK-B", "AAA"))
    calls: list = []
    monkeypatch.setattr(cards.pack, "build", fake_build(calls=calls))
    rc, out = run_json(cards, ["--run", str(run), "--symbols", "brk.b"], capsys)
    assert rc == 0, out
    assert calls == [("BRK-B", "card")] and out["cards"][0]["ticker"] == "BRK-B"


def _write_fundamentals(folder: Path, total_debt, total_cash, ebitda, ebit=None, interest=None, annual_debt=None, edgar_annual=None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    income = {"EBITDA": ebitda, "EBIT": ebit, "Interest Expense": interest}
    (folder / "fundamentals.json").write_text(json.dumps({
        "info": {"total_debt": total_debt, "total_cash": total_cash},
        "statements": {"income_statement": {"2025-03-31T00:00:00": {"EBITDA": 1.0}, "2026-03-31T00:00:00": income},
                       "balance_sheet": {"2026-03-31T00:00:00": {"Total Debt": annual_debt}}}}))
    if edgar_annual is not None:
        (folder / "edgar.json").write_text(json.dumps({"annual": edgar_annual}))


def test_leverage_passes_low_debt_with_good_coverage(tmp_path):
    _write_fundamentals(tmp_path, 300e6, 100e6, 200e6, ebit=150e6, interest=15e6, annual_debt=280e6)
    lev = cards.leverage(tmp_path, "industrial")
    assert lev["ok"] is True and lev["net_debt_to_ebitda"] == 1.0 and lev["interest_coverage"] == 10.0 and lev["flags"] == []


def test_leverage_fails_on_net_debt_to_ebitda(tmp_path):
    _write_fundamentals(tmp_path, 650e6, 50e6, 200e6, ebit=180e6, interest=20e6, annual_debt=600e6)
    lev = cards.leverage(tmp_path, "industrial")
    assert lev["ok"] is False and lev["net_debt_to_ebitda"] == 3.0 and lev["flags"] == ["LEVERAGE_HIGH"] and "3.0x EBITDA" in lev["why"]


def test_leverage_fails_on_interest_coverage(tmp_path):
    _write_fundamentals(tmp_path, 300e6, 0, 200e6, ebit=100e6, interest=25e6, annual_debt=300e6)
    lev = cards.leverage(tmp_path, "industrial")
    assert lev["ok"] is False and lev["interest_coverage"] == 4.0 and "covers interest 4.0x" in lev["why"]


def test_debt_raised_since_the_10k_uses_todays_debt_and_drops_stale_coverage(tmp_path):
    """PBH: a June deal doubled debt after the March 10-K, whose figures showed 187x coverage."""
    _write_fundamentals(tmp_path, 2127e6, 47e6, 331e6, ebit=300e6, interest=1.6e6, annual_debt=1045e6)
    lev = cards.leverage(tmp_path, "industrial")
    assert lev["ok"] is False and lev["interest_coverage"] is None
    assert lev["flags"] == ["DEBT_CHANGED_SINCE_ANNUAL", "LEVERAGE_HIGH"] and "stale" in lev["why"]


def test_net_cash_passes_with_no_flags(tmp_path):
    _write_fundamentals(tmp_path, 50e6, 400e6, 100e6, annual_debt=10e6)
    lev = cards.leverage(tmp_path, "industrial")
    assert lev["ok"] is True and lev["flags"] == [] and "net cash" in lev["why"]


def test_leverage_falls_back_to_edgar_ebitda(tmp_path):
    _write_fundamentals(tmp_path, 500e6, 0, None, edgar_annual=[{"operating_income": 80e6, "depreciation_amortization": 20e6, "long_term_debt": 500e6}])
    lev = cards.leverage(tmp_path, "industrial")
    assert lev["ebitda"] == 100e6 and lev["ok"] is False and lev["net_debt_to_ebitda"] == 5.0


@pytest.mark.parametrize("btype", ["financial", "reit", "utility"])
def test_yardstick_businesses_are_not_leverage_checked(tmp_path, btype):
    _write_fundamentals(tmp_path, 9e9, 0, 1e8)
    assert cards.leverage(tmp_path, btype)["ok"] is None


def test_missing_figures_leave_the_check_open(tmp_path):
    assert cards.leverage(tmp_path, "industrial")["ok"] is None


def test_a_levered_name_starts_from_value_hint_3_and_is_flagged(monkeypatch, capsys, tmp_path):
    run = make_run(tmp_path, ("AAA", "BBB"))
    inner = fake_build(irr={"AAA": 0.31, "BBB": 0.31})

    def build(symbol, out_dir, level="card", workers=4):
        pack = inner(symbol, out_dir, level, workers)
        if symbol == "AAA":
            _write_fundamentals(Path(out_dir), 900e6, 0, 100e6, ebit=80e6, interest=40e6, annual_debt=900e6)
        return pack

    monkeypatch.setattr(cards.pack, "build", build)
    rc, out = run_json(cards, ["--run", str(run)], capsys)
    assert rc == 0
    by = {c["ticker"]: c for c in out["cards"]}
    assert by["AAA"]["value_hint"] == 3 and by["AAA"]["leverage_ok"] is False and by["AAA"]["net_debt_to_ebitda"] == 9.0
    assert by["BBB"]["value_hint"] == 5 and by["BBB"]["leverage_ok"] is None
    lev_flag = next(f for f in out["flags"] if f["code"] == "LEVERAGE_HIGH")
    assert lev_flag["tickers"] == ["AAA"]
    data = json.loads((run / "cards" / "AAA.data.json").read_text())
    assert data["leverage"]["ok"] is False and data["value_hint"] == 3
