from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client, market
from second_opinion.brokers import router
from scripts_util import PLUGIN_ROOT
from page_dom import assert_page_help, render_and_audit, requires_chrome

POSITIONS = {
    "acc-1": [{"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": 100.0}],
    "acc-2": [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 5, "price": 200.0}],
}


def _series(n: int, step: float, volume: float | None = None) -> list[dict]:
    out, d, price = [], date(2023, 1, 2), 100.0
    while len(out) < n:
        if d.weekday() < 5:
            row = {"date": d.isoformat(), "close": round(price, 4), "adj_close": round(price, 4)}
            if volume is not None:
                row["volume"] = volume
            out.append(row)
            price *= 1 + (step if len(out) % 2 else -step)
        d += timedelta(days=1)
    return out


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=lambda account_id: POSITIONS[account_id], get_user_account_balance=lambda account_id: [{"cash": 500.0}])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


@pytest.fixture(autouse=True)
def no_sector_cache(monkeypatch):
    """The bucket lookup must never read the user's real sector cache or Yahoo; tests that need buckets stub it themselves."""
    monkeypatch.setattr(market, "sectors", lambda syms, cache_path=None: {})


@pytest.fixture
def yahoo(monkeypatch):
    calls: list[dict] = []

    def close_histories(symbols, start):
        calls.append({"symbols": list(symbols), "start": start})
        return {s: _series(700, 0.02 if s == "AAPL" else 0.01) for s in symbols}

    monkeypatch.setattr(market, "close_histories", close_histories)
    return calls


def test_stress_script_runs_builtin_scenarios(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["portfolio"]["total_value"] == 3000.0 and out["portfolio"]["cash_weight"] == 0.3333  # 500 cash in each of two accounts
    assert yahoo[0]["symbols"] == ["AAPL", "SPY", "VTI"] and yahoo[0]["start"] == "2023-09-05"  # 3 years back
    names = [s["name"] for s in out["scenarios"]]
    assert "2020 COVID crash" in names and "2022 rate shock" in names and "2008 financial crisis" in names
    modes = {s["name"]: s["mode"] for s in out["scenarios"]}
    assert modes["2008 financial crisis"] == "beta_scaled"  # history starts 2023
    assert out["sources"] == {"holdings": "snaptrade", "prices": "yahoo", "benchmark": "SPY", "factors": ["HYG", "IJR", "MTUM", "VLUE"], "proxies": {}, "cash_like": [], "tracking_references": {}}
    assert out["as_of"] == "2026-09-04"
    # one extra batched call for the factor proxies, same lookback start as the main fetch
    assert len(yahoo) == 2 and yahoo[1]["symbols"] == ["HYG", "IJR", "MTUM", "VLUE"] and yahoo[1]["start"] == yahoo[0]["start"]
    assert set(out["factors"]) == {"HYG", "IJR", "MTUM", "VLUE"}
    for name in ("HYG", "IJR", "MTUM", "VLUE"):
        assert "beta" in out["factors"][name] and "explained_variance" in out["factors"][name]
    # no volume in this fixture's series -> liquidity degrades to null, never fails the run
    liquidity = {r["symbol"]: r for r in out["liquidity"]}
    assert set(liquidity) == {"AAPL", "VTI"}
    assert liquidity["AAPL"]["position_value"] == 1000.0 and liquidity["AAPL"]["avg_dollar_volume"] is None
    assert liquidity["AAPL"]["pct_of_adv"] is None
    assert not [f for f in out["flags"] if f["code"] == "ILLIQUID_POSITION"]


def test_stress_script_liquidity_flags_illiquid_position(sdk, monkeypatch, capsys) -> None:
    calls: list[dict] = []

    def close_histories(symbols, start):
        calls.append({"symbols": list(symbols), "start": start})
        out = {}
        for s in symbols:
            if s == "AAPL":
                out[s] = _series(700, 0.02, volume=1_000_000)  # huge ADV: liquid
            elif s == "VTI":
                out[s] = _series(700, 0.01, volume=10)  # tiny ADV vs a $1000 position: illiquid
            else:
                out[s] = _series(700, 0.01, volume=1_000_000)
        return out

    monkeypatch.setattr(market, "close_histories", close_histories)
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), [], capsys)
    assert rc == 0, out
    liquidity = {r["symbol"]: r for r in out["liquidity"]}
    assert liquidity["AAPL"]["pct_of_adv"] < 0.01
    assert liquidity["VTI"]["pct_of_adv"] > 0.01
    codes = {f["code"] for f in out["flags"]}
    assert "ILLIQUID_POSITION" in codes
    messages = [f["message"] for f in out["flags"] if f["code"] == "ILLIQUID_POSITION"]
    assert any("VTI" in m for m in messages) and not any("AAPL" in m for m in messages)


def test_stress_script_factor_fetch_failure_degrades_not_fails(sdk, monkeypatch, capsys) -> None:
    def close_histories(symbols, start):
        if set(symbols) & {"IJR", "MTUM", "VLUE", "HYG"}:
            raise RuntimeError("factor proxies unavailable")
        return {s: _series(700, 0.01) for s in symbols}

    monkeypatch.setattr(market, "close_histories", close_histories)
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), [], capsys)
    assert rc == 0, out
    assert "factors" not in out
    assert out["sources"]["factors"] == []


def test_stress_script_custom_shock_and_scenario(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), ["--shock", "AAPL=-0.3", "--scenario", "custom=-0.25", "--years", "1", "--no-builtin"], capsys)
    assert rc == 0 and out["what_if"]["shocks"] == {"AAPL": -0.3}
    assert [s["name"] for s in out["scenarios"]] == ["custom"] and out["scenarios"][0]["mode"] == "beta_scaled"
    assert yahoo[0]["start"] == (date.today() - timedelta(days=365)).isoformat()


def test_stress_script_errors(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), ["--shock", "AAPL"], capsys)
    assert rc == 2 and "SYMBOL=RETURN" in out["error"]
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), ["--account", "nope"], capsys)
    assert rc == 2 and "unknown account" in out["error"]


def test_stress_script_yahoo_failure_exit_5(sdk, monkeypatch, capsys) -> None:
    def boom(symbols, start):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "close_histories", boom)
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), [], capsys)
    assert rc == 5 and "yahoo down" in out["error"]


def test_risk_math_script_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    params = {"positions": [{"symbol": "A", "value": 100}], "prices": {"A": _series(300, 0.01)}, "benchmark": {"symbol": "SPY", "prices": _series(300, 0.01)}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(params)))
    load_script("risk-analysis/scripts/risk.py").main()
    assert json.loads(capsys.readouterr().out)["portfolio"]["beta"] == 1.0


def test_render_builds_a_self_contained_page(tmp_path, capsys) -> None:
    result = {
        "as_of": "2026-09-14",
        "sources": {"holdings": "snaptrade", "prices": "yahoo", "benchmark": "SPY", "factors": ["HYG"]},
        "portfolio": {"total_value": 11000.0, "cash_weight": 0.0636, "coverage": 1.0, "observations": 699, "start": "2023-01-03", "end": "2025-09-05", "benchmark": "SPY", "volatility": 0.1378, "beta": 0.0173, "correlation_to_benchmark": 0.0215, "tracking_error": 0.2175, "sharpe": -0.47, "max_drawdown": 0.2344, "var_95": 0.0148, "cvar_95": 0.0188, "parametric_var_95": 0.0143, "var_99": 0.0225, "diversification_ratio": 1.6172, "avg_pairwise_correlation": 0.006, "sortino": -0.46},
        "positions": [{"symbol": "AAPL", "value": 5000.0, "weight": 0.4545, "observations": 699, "volatility": 0.2737, "beta": -0.01, "max_drawdown": 0.5906, "var_95": 0.0301, "tracking_error": 0.3241, "sharpe": -0.91}, {"symbol": "BND", "value": 1500.0, "weight": 0.1364, "observations": 699, "volatility": 0.0643, "beta": 0.03, "max_drawdown": 0.0616, "var_95": 0.0061, "tracking_error": 0.1785, "sharpe": 1.79}],
        "risk_contributions": [{"symbol": "AAPL", "weight": 0.4545, "contribution": 0.0151, "share": 0.7936}, {"symbol": "BND", "weight": 0.1364, "contribution": 0.0001, "share": 0.007}],
        "correlation": {"symbols": ["AAPL", "BND"], "matrix": [[1.0, 0.0412], [0.0412, 1.0]]},
        "concentration": {"hhi": 0.3049, "hhi_interpretation": "concentrated", "top_5_concentration": 0.9364, "largest_position": 0.4545, "position_count": 2},
        "scenarios": [
            {"name": "2008 financial crisis", "start": "2007-10-09", "end": "2009-03-09", "mode": "beta_scaled", "benchmark_return": -0.5678, "positions": {"AAPL": 0.0073, "BND": -0.0154}, "portfolio_return": -0.0098, "portfolio_loss": -108.02, "note": "window is outside the price history; loss estimated as beta x benchmark return"},
            {"name": "custom </script> dip", "start": "2024-07-16", "end": "2024-08-05", "mode": "replay", "benchmark_return": -0.0148, "positions": {"AAPL": 0.0527, "BND": 0.0047}, "portfolio_return": 0.0042, "portfolio_loss": 46.68, "note": None},
        ],
        "what_if": {"shocks": {"AAPL": -0.3}, "positions": {"AAPL": -1500.0}, "portfolio_return": -0.1364, "portfolio_loss": -1500.0},
        "missing_prices": [],
        "flags": [{"code": "CONCENTRATED", "message": "largest position 45.5% of value, HHI 0.3049"}, {"code": "SHORT_HISTORY", "message": "AAPL has <2 years of prices"}],
        "factors": {"HYG": {"beta": -0.0209, "explained_variance": 0.0002}}, "factors_total_explained_variance": 0.0002,
        "liquidity": [{"symbol": "AAPL", "avg_dollar_volume": 1.2e10, "position_value": 5000.0, "pct_of_adv": 0.0}],
    }
    src = tmp_path / "risk.json"
    src.write_text(json.dumps(result))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("risk-analysis/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res["out"] == str(out) and res["positions"] == 2 and res["scenarios"] == 2 and res["flags"] == 2
    html = out.read_text()
    assert html.startswith("<title>Portfolio Risk</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"CONCENTRATED"' in html and "const FA" in html
    # the data is JSON: a tag inside a scenario name cannot close the script; the static headline is escaped text
    assert "custom </script> dip" not in html and 'custom <\\/script> dip' in html
    assert "AAPL has <2 years" not in html.split("<script>")[0]  # flag text is drawn by the script, escaped
    assert "volatility 13.8% · beta 0.02 · max drawdown 23.4% · 1-day VaR 95% 1.5%" in html  # readable without JS
    assert "label: 'Days'" not in html  # the window is one figure for every row; it lives in the header line only
    assert "r.tracking_benchmark" in html and "vs ${F.esc(r.tracking_benchmark)}" in html  # each row names what it tracks
    for section in ("Risk contribution", "Correlation", "Positions", "Scenarios", "What if", "Factor exposure", "Liquidity", "Flags", "not a ceiling"):
        assert section in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "http" not in html.split("</style>")[1].split("<script>")[0]
    # plain-language layer: the explain box slot is in the body, the script fills it and marks jargon with glossary terms (spans appear at runtime)
    assert 'id="explain"' in html.split("<script>")[0] and 'class="explain"' in html and "FA.explain(" in html and "FA.term(" in html and "data-term=" in html
    for term in ("'factor exposure'", "'explained variance'", "'liquidity'", "'adv'", "'tracking error'", "'var', 'VaR'", "'hhi', 'HHI'", "'cvar', 'CVaR'"):
        assert term in html


def test_render_rejects_non_risk_input(tmp_path, capsys) -> None:
    src = tmp_path / "bad.json"
    src.write_text('{"totals": 1}')
    rc, res = run_json(load_script("risk-analysis/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "risk.py result" in res["error"]
    rc, res = run_json(load_script("risk-analysis/scripts/render.py"), ["--in", str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


def _daily(start: str, end: str, first: float, last: float) -> list[dict]:
    """A straight-line daily close series from ``first`` on ``start`` to ``last`` on ``end`` (weekdays)."""
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    out = []
    for i, d in enumerate(days):
        price = first + (last - first) * i / max(len(days) - 1, 1)
        out.append({"date": d.isoformat(), "close": round(price, 4), "adj_close": round(price, 4)})
    return out


def test_risk_replays_each_symbol_with_its_own_history_and_beta_scales_the_rest() -> None:
    risk = load_script("risk-analysis/scripts/risk.py")
    long = _daily("2019-01-02", "2023-12-29", 100.0, 150.0)  # covers the 2020 and 2022 windows
    short = _daily("2023-01-02", "2023-12-29", 100.0, 120.0)  # starts after both windows
    bench = _daily("2019-01-02", "2023-12-29", 100.0, 200.0)
    scenarios = [
        {"name": "2022 rate shock", "start": "2022-01-03", "end": "2022-10-12", "benchmark_return": -0.2543},
        {"name": "2008 financial crisis", "start": "2007-10-09", "end": "2009-03-09", "benchmark_return": -0.5678},
    ]
    out = risk.run_risk({
        "positions": [{"symbol": "OLD", "value": 600}, {"symbol": "NEW", "value": 300}, {"symbol": "GONE", "value": 100}],
        "cash": 0, "prices": {"OLD": long, "NEW": short}, "benchmark": {"symbol": "SPY", "prices": bench},
        "scenarios": scenarios,
    })
    by = {s["name"]: s for s in out["scenarios"]}
    mixed = by["2022 rate shock"]
    assert mixed["mode"] == "mixed"
    assert mixed["replayed"] == ["OLD"] and mixed["beta_scaled"] == ["NEW"]
    # OLD is replayed from its own prices; NEW is beta x the benchmark's own replayed return
    p = risk._Series(long)  # noqa: SLF001
    b = risk._Series(bench)  # noqa: SLF001
    old_ret = p.on("2022-10-12") / p.on("2022-01-03") - 1
    bench_ret = b.on("2022-10-12") / b.on("2022-01-03") - 1
    assert mixed["positions"]["OLD"] == round(old_ret, 4)
    assert mixed["benchmark_return"] == round(bench_ret, 4)
    new_beta = next(r["beta"] for r in out["positions"] if r["symbol"] == "NEW")
    assert mixed["positions"]["NEW"] == round(new_beta * bench_ret, 4)
    assert mixed["portfolio_return"] == round(0.6 * old_ret + 0.3 * new_beta * bench_ret, 4)
    assert "beta x benchmark return for: NEW" in mixed["note"] and "assumed unchanged: GONE" in mixed["note"]
    # nothing covers 2008: pure beta-scaling, as before
    assert by["2008 financial crisis"]["mode"] == "beta_scaled"
    assert by["2008 financial crisis"]["replayed"] == [] and sorted(by["2008 financial crisis"]["beta_scaled"]) == ["NEW", "OLD"]


def test_risk_full_replay_keeps_mode_replay() -> None:
    risk = load_script("risk-analysis/scripts/risk.py")
    long = _daily("2019-01-02", "2023-12-29", 100.0, 150.0)
    bench = _daily("2019-01-02", "2023-12-29", 100.0, 200.0)
    out = risk.run_risk({
        "positions": [{"symbol": "A", "value": 600}, {"symbol": "B", "value": 400}], "cash": 0,
        "prices": {"A": long, "B": long}, "benchmark": {"symbol": "SPY", "prices": bench},
        "scenarios": [{"name": "2020 COVID crash", "start": "2020-02-19", "end": "2020-03-23", "benchmark_return": -0.3392}],
    })
    s = out["scenarios"][0]
    assert s["mode"] == "replay" and sorted(s["replayed"]) == ["A", "B"] and s["beta_scaled"] == [] and s["note"] is None


def _sdk_with(monkeypatch, positions: dict[str, list[dict]]) -> FakeSdk:
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=lambda account_id: positions[account_id], get_user_account_balance=lambda account_id: [{"cash": 500.0}])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


def test_stress_script_borrows_proxy_history_for_institutional_classes_and_treats_money_market_as_cash(monkeypatch, capsys) -> None:
    positions = {
        "acc-1": [
            {"symbol": {"symbol": {"symbol": "QBN5"}, "description": "VANG INST 500 IDX TR"}, "units": 10, "price": 300.0},
            {"symbol": {"symbol": {"symbol": "QBMZ"}, "description": "VG IS TOT BD MKT IDX"}, "units": 10, "price": 100.0},
            {"symbol": {"symbol": {"symbol": "BND"}, "description": "Vanguard Total Bond Market ETF"}, "units": 10, "price": 70.0},
            {"symbol": {"symbol": {"symbol": "MVRXX"}, "description": "Morgan Stanley Government Portfolio"}, "units": 500, "price": 1.0},
        ],
        "acc-2": [{"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": 100.0}],
    }
    _sdk_with(monkeypatch, positions)
    calls: list[list[str]] = []

    def close_histories(symbols, start):
        calls.append(sorted(symbols))
        # Yahoo has nothing for the institutional classes or the money-market fund
        return {s: ([] if s in ("QBN5", "QBMZ", "MVRXX") else _series(700, 0.01)) for s in symbols}

    monkeypatch.setattr(market, "close_histories", close_histories)
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    # one extra batched call for the proxies not already fetched (BND was): VOO only
    assert calls[0] == ["AAPL", "BND", "QBMZ", "QBN5", "SPY"] and calls[1] == ["VOO"]  # MVRXX is cash, never downloaded
    assert out["sources"]["proxies"] == {"QBMZ": "BND", "QBN5": "VOO"}
    assert out["sources"]["cash_like"] == ["MVRXX"]
    assert out["missing_prices"] == []
    assert out["portfolio"]["coverage"] == 1.0
    # the money-market fund counts as cash: 500 + 1000 of account cash over 3000 + 1000 + 700 + 1000 + 1500
    assert out["portfolio"]["cash_weight"] == round(1500 / 7200, 4)
    assert {r["symbol"] for r in out["positions"]} == {"AAPL", "BND", "QBMZ", "QBN5"}
    by = {r["symbol"]: r for r in out["positions"]}
    assert by["QBN5"]["beta"] is not None and by["QBMZ"]["beta"] == by["BND"]["beta"]
    flags = {f["code"]: f["message"] for f in out["flags"]}
    assert "MISSING_PRICES" not in flags
    assert flags["PROXY_HISTORY"] == "QBMZ uses BND's price history, QBN5 uses VOO's (institutional share classes Yahoo has no quotes for)"
    # liquidity has no meaning for a proxied class
    liq = {r["symbol"]: r for r in out["liquidity"]}
    assert liq["QBN5"]["avg_dollar_volume"] is None and liq["QBN5"]["pct_of_adv"] is None


def test_stress_script_proxy_fetch_failure_degrades_not_fails(monkeypatch, capsys) -> None:
    positions = {"acc-1": [{"symbol": {"symbol": {"symbol": "QBN5"}, "description": "VANG INST 500 IDX TR"}, "units": 10, "price": 300.0},
                           {"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": 100.0}], "acc-2": []}
    _sdk_with(monkeypatch, positions)
    n = {"calls": 0}

    def close_histories(symbols, start):
        n["calls"] += 1
        if n["calls"] == 2:
            raise RuntimeError("yahoo down")
        return {s: ([] if s == "QBN5" else _series(700, 0.01)) for s in symbols}

    monkeypatch.setattr(market, "close_histories", close_histories)
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    assert out["sources"]["proxies"] == {} and out["missing_prices"] == ["QBN5"]
    assert any(f["code"] == "PROXY_HISTORY_UNAVAILABLE" for f in out["flags"])
    assert any(f["code"] == "MISSING_PRICES" for f in out["flags"])


def test_risk_tracking_error_uses_each_positions_own_reference() -> None:
    risk = load_script("risk-analysis/scripts/risk.py")
    stock = _daily("2022-01-03", "2023-12-29", 100.0, 160.0)
    bond = _daily("2022-01-03", "2023-12-29", 100.0, 96.0)
    agg = _daily("2022-01-03", "2023-12-29", 100.0, 95.0)
    spy = _daily("2022-01-03", "2023-12-29", 100.0, 150.0)
    base = {"positions": [{"symbol": "AAPL", "value": 600}, {"symbol": "BSBIX", "value": 300}, {"symbol": "GLD", "value": 100}],
            "cash": 0, "prices": {"AAPL": stock, "BSBIX": bond, "GLD": stock}, "benchmark": {"symbol": "SPY", "prices": spy}}
    # without references: every covered position tracks the benchmark, as before
    plain = {r["symbol"]: r for r in risk.run_risk(base)["positions"]}
    assert plain["BSBIX"]["tracking_benchmark"] == "SPY" and plain["BSBIX"]["tracking_error"] is not None
    out = risk.run_risk({**base, "tracking_references": {"AAPL": "SPY", "BSBIX": "BND"}, "reference_prices": {"BND": agg}})
    rows = {r["symbol"]: r for r in out["positions"]}
    assert rows["AAPL"]["tracking_benchmark"] == "SPY" and rows["AAPL"]["tracking_error"] == plain["AAPL"]["tracking_error"]
    # BSBIX is measured against BND now, a much smaller number than against SPY
    assert rows["BSBIX"]["tracking_benchmark"] == "BND"
    assert rows["BSBIX"]["tracking_error"] is not None and rows["BSBIX"]["tracking_error"] < plain["BSBIX"]["tracking_error"]
    b, a = risk._Series(bond), risk._Series(agg)  # noqa: SLF001
    dates = sorted(set(b.returns) & set(a.returns))
    from statistics import stdev
    expected = stdev([b.returns[d] - a.returns[d] for d in dates]) * (252 ** 0.5)
    assert rows["BSBIX"]["tracking_error"] == round(expected, 4)
    # no reference for gold: no tracking error, not a misleading one against SPY
    assert rows["GLD"]["tracking_benchmark"] is None and rows["GLD"]["tracking_error"] is None
    # a reference with no prices anywhere leaves the position without a figure
    out2 = risk.run_risk({**base, "tracking_references": {"BSBIX": "AGG"}})
    r2 = {r["symbol"]: r for r in out2["positions"]}
    assert r2["BSBIX"]["tracking_benchmark"] is None and r2["BSBIX"]["tracking_error"] is None
    # the portfolio's own tracking error is still against the benchmark
    assert out["portfolio"]["tracking_error"] == risk.run_risk(base)["portfolio"]["tracking_error"]


def test_stress_script_measures_tracking_error_against_each_buckets_reference(monkeypatch, capsys) -> None:
    positions = {
        "acc-1": [
            {"symbol": {"symbol": {"symbol": "BSBIX"}, "description": "Baird Short-Term Bond Fund"}, "units": 10, "price": 100.0},
            {"symbol": {"symbol": {"symbol": "VEA"}, "description": "Vanguard FTSE Developed Markets ETF"}, "units": 10, "price": 70.0},
            {"symbol": {"symbol": {"symbol": "GLD"}, "description": "SPDR Gold Shares"}, "units": 5, "price": 300.0},
            {"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": 100.0},
        ],
        "acc-2": [],
    }
    _sdk_with(monkeypatch, positions)
    calls: list[list[str]] = []
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: (calls.append(sorted(symbols)) or {s: _series(700, 0.01 if s in ("BSBIX", "BND") else 0.02) for s in symbols}))
    info = {"BSBIX": {"quote_type": "MUTUALFUND", "category": "Short-Term Bond", "name": "Baird Short-Term Bond Fund"},
            "VEA": {"quote_type": "ETF", "category": "Foreign Large Blend", "name": "Vanguard FTSE Developed Markets ETF"},
            "GLD": {"quote_type": "ETF", "category": "Commodities Focused", "name": "SPDR Gold Shares"},
            "AAPL": {"quote_type": "EQUITY", "country": "United States", "name": "Apple Inc."}}
    monkeypatch.setattr(market, "sectors", lambda syms, cache_path=None: {s: info[s] for s in syms if s in info})
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    # the references not already downloaded come in the one extra batched call, beside any proxies
    assert calls[0] == ["AAPL", "BSBIX", "GLD", "SPY", "VEA"] and calls[1] == ["BND", "VXUS"]
    rows = {r["symbol"]: r for r in out["positions"]}
    assert rows["BSBIX"]["tracking_benchmark"] == "BND" and rows["VEA"]["tracking_benchmark"] == "VXUS"
    assert rows["AAPL"]["tracking_benchmark"] == "SPY"
    assert rows["GLD"]["tracking_benchmark"] is None and rows["GLD"]["tracking_error"] is None
    assert out["sources"]["tracking_references"] == {"AAPL": "SPY", "BSBIX": "BND", "VEA": "VXUS"}
    assert out["portfolio"]["tracking_error"] is not None  # the portfolio still tracks SPY


def test_stress_script_falls_back_to_the_benchmark_when_buckets_are_unavailable(monkeypatch, capsys) -> None:
    positions = {"acc-1": [{"symbol": {"symbol": {"symbol": "BSBIX"}, "description": "Baird Short-Term Bond Fund"}, "units": 10, "price": 100.0}], "acc-2": []}
    _sdk_with(monkeypatch, positions)
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {s: _series(700, 0.01) for s in symbols})

    def boom(syms, cache_path=None):
        raise RuntimeError("cache unreadable")

    monkeypatch.setattr(market, "sectors", boom)
    rc, out = run_json(load_script("risk-analysis/scripts/stress.py"), ["--as-of", "2026-09-04"], capsys)
    assert rc == 0, out
    rows = {r["symbol"]: r for r in out["positions"]}
    assert rows["BSBIX"]["tracking_benchmark"] == "SPY" and rows["BSBIX"]["tracking_error"] is not None
    assert out["sources"]["tracking_references"] == {}
    assert any(f["code"] == "TRACKING_REFERENCES_UNAVAILABLE" for f in out["flags"])


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit("risk-analysis/scripts/render.py", ["--in", str(PLUGIN_ROOT / "docs/samples/risk-analysis.json")], tmp_path, capsys)
    assert_page_help(a)
