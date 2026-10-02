"""market-analysis/scripts/flows.py: the market-flows overview, each block degrading on its own."""
from __future__ import annotations

import pytest
from second_opinion import cftc, finra, flows, fred, ssga
from second_opinion.errors import ApiError
from scripts_util import load_script, run_json

COT_ROW = {"report_date_as_yyyy_mm_dd": "2026-09-08T00:00:00.000", "cftc_contract_market_code": "13874A", "contract_market_name": "E-MINI S&P 500", "open_interest_all": "2000", "asset_mgr_positions_long": "1100", "asset_mgr_positions_short": "200", "lev_money_positions_long": "150", "lev_money_positions_short": "500"}
SNAP = {"XLK": {"date": "2026-09-11", "nav": 187.73, "aum_usd": 121_839_350_000.0, "shares": 649_013_000}, "SPY": None}
SERIES = {"XLK": [{"date": "2026-09-10", "nav": 186.0, "aum_usd": 120_000_000_000.0, "shares": 645_000_000}, SNAP["XLK"]]}
OBS = [{"date": "2026-07-27", "value": 3009.1}, {"date": "2026-08-03", "value": 3020.5}]


@pytest.fixture
def fake_sources(monkeypatch):
    calls: dict[str, list] = {"cot": [], "snapshot": [], "record": [], "fred": [], "finra": []}
    monkeypatch.setattr(cftc, "positioning", lambda codes, weeks=52: (calls["cot"].append((list(codes), weeks)), {c: ([COT_ROW] if c == "13874A" else []) for c in codes})[1])
    monkeypatch.setattr(ssga, "snapshot", lambda tickers: (calls["snapshot"].append(list(tickers)), SNAP)[1])
    monkeypatch.setattr(ssga, "record", lambda snap: (calls["record"].append(snap), SERIES)[1])
    monkeypatch.setattr(ssga, "series_path", lambda: "/data/etf-shares.json")
    monkeypatch.setattr(fred, "observations", lambda series, n: (calls["fred"].append((series, n)), OBS)[1])
    monkeypatch.setattr(finra, "short_volume", lambda symbols, days=20, today=None: (calls["finra"].append((list(symbols), days)), {s: [{"date": "2026-09-11", "short": 40.0, "total": 100.0}] for s in symbols})[1])
    return calls


def test_default_run_delivers_positioning_etf_flows_and_cash(fake_sources, capsys) -> None:
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), [], capsys)
    assert rc == 0 and out["as_of"]
    assert fake_sources["cot"] == [(list(flows.CONTRACTS), 52)]
    assert out["positioning"]["report_date"] == "2026-09-08" and [c["code"] for c in out["positioning"]["contracts"]] == ["13874A"]
    assert out["positioning"]["contracts"][0]["classes"]["asset_managers"]["net"] == 900 and out["positioning"]["weeks"] == 52
    assert out["positioning"]["missing"] == [c for c in flows.CONTRACTS if c != "13874A"]
    assert fake_sources["snapshot"] == [["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "SPY"]] and fake_sources["record"] == [SNAP]
    assert out["etf_flows"]["funds"][0]["ticker"] == "XLK" and out["etf_flows"]["funds"][0]["flow_1d_usd"] == round(4_013_000 * 187.73, 2)
    assert out["etf_flows"]["series_file"] == "/data/etf-shares.json" and out["etf_flows"]["as_of"] == "2026-09-11"
    assert fake_sources["fred"] == [("WRMFNS", 53)] and out["cash"]["latest"] == 3020.5 and out["cash"]["change_1w"] == 11.4
    assert "short_volume" not in out and fake_sources["finra"] == []
    assert set(out["sources"]) == {"positioning", "etf_flows", "cash"}


def test_a_failing_block_degrades_without_failing_the_run(fake_sources, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cftc, "positioning", lambda codes, weeks=52: (_ for _ in ()).throw(ApiError("CFTC returned HTTP 503", code="CFTC_HTTP", http_status=503)))
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), [], capsys)
    assert rc == 0
    assert out["positioning"] == {"error": "CFTC returned HTTP 503", "code": "CFTC_HTTP"}
    assert out["etf_flows"]["funds"] and out["cash"]["latest"] == 3020.5


def test_block_flags_select_blocks_and_short_adds_finra(fake_sources, capsys) -> None:
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), ["--cot", "--weeks", "26", "--short", "aapl", "nvda", "--days", "5"], capsys)
    assert rc == 0 and fake_sources["cot"] == [(list(flows.CONTRACTS), 26)]
    assert "etf_flows" not in out and "cash" not in out
    assert fake_sources["finra"] == [(["AAPL", "NVDA"], 5)]
    assert [s["symbol"] for s in out["short_volume"]["symbols"]] == ["AAPL", "NVDA"] and out["short_volume"]["symbols"][0]["short_ratio"] == 40.0 and out["short_volume"]["days"] == 5


def test_short_alone_adds_to_the_default_blocks(fake_sources, capsys) -> None:
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), ["--short", "AAPL"], capsys)
    assert rc == 0 and set(out) == {"as_of", "positioning", "etf_flows", "cash", "short_volume", "sources", "notes"}


def test_invalid_arguments_exit_2(fake_sources, capsys) -> None:
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), ["--short", "AA PL"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), ["--weeks", "0"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), ["--short"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_history_flag_adds_weekly_nets_per_contract(fake_sources, capsys) -> None:
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), ["--cot", "--history"], capsys)
    assert rc == 0 and out["positioning"]["contracts"][0]["history"][0]["date"] == "2026-09-08"
    rc, out = run_json(load_script("market-analysis/scripts/flows.py"), ["--cot"], capsys)
    assert "history" not in out["positioning"]["contracts"][0]
