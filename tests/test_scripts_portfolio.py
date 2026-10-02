from __future__ import annotations

import json

import pytest

from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client, market
from second_opinion.brokers import router


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=[{"units": 1}], get_user_account_balance=[{"cash": 1.0}])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


def test_accounts_rows_carry_broker_and_shadowed_list(sdk, capsys) -> None:
    rc, out = run_json(load_script("portfolio-analysis/scripts/accounts.py"), [], capsys)
    assert rc == 0 and {a["broker"] for a in out["accounts"]} == {"snaptrade"} and out["shadowed"] == []


def test_accounts_include_shadowed_flag_is_accepted(sdk, capsys) -> None:
    rc, out = run_json(load_script("portfolio-analysis/scripts/accounts.py"), ["--include-shadowed"], capsys)
    assert rc == 0 and len(out["accounts"]) == 2


def test_accounts_asks_for_the_missing_login_by_default(sdk, monkeypatch, capsys) -> None:
    from test_brokers_router import FailingDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(sdk, extra_brokers=(FailingDirect(),)))
    rc, out = run_json(load_script("portfolio-analysis/scripts/accounts.py"), [], capsys)
    assert rc == 4 and out["code"] == "ETRADE_REAUTH" and out["url"] == FailingDirect.LOGIN_URL and out["partial"] == "--partial"


def test_accounts_reports_a_broker_that_could_not_be_listed(sdk, monkeypatch, capsys) -> None:
    from test_brokers_router import FailingDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(sdk, extra_brokers=(FailingDirect(),)))
    rc, out = run_json(load_script("portfolio-analysis/scripts/accounts.py"), ["--partial"], capsys)
    assert rc == 0 and [a["account_id"] for a in out["accounts"]] == ["acc-1", "acc-2"]  # SnapTrade rows survive
    assert out["broker_errors"] == [{"broker": "etrade", "code": "ETRADE_REAUTH", "message": "E*Trade login required (token expired)", "hint": "log in again", "sandbox": False}]
    assert out["warnings"] == []


def test_accounts_script(sdk, capsys) -> None:
    rc, out = run_json(load_script("portfolio-analysis/scripts/accounts.py"), [], capsys)
    assert rc == 0 and [a["account_id"] for a in out["accounts"]] == ["acc-1", "acc-2"]
    assert out["accounts"][0]["account_type"] == "cash"  # unknown defaults to cash


def test_accounts_script_applies_account_types(sdk, capsys, monkeypatch) -> None:
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "c")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "k")
    monkeypatch.setenv("SNAPTRADE_ACCOUNT_TYPES", "acc-1=margin")
    rc, out = run_json(load_script("portfolio-analysis/scripts/accounts.py"), [], capsys)
    assert out["accounts"][0]["account_type"] == "margin" and out["accounts"][1]["account_type"] == "cash"


def test_portfolio_and_balance_scripts(sdk, capsys) -> None:
    rc, out = run_json(load_script("portfolio-analysis/scripts/portfolio.py"), ["acc-1"], capsys)
    assert rc == 0 and out["positions"] == [{"units": 1}]
    rc, out = run_json(load_script("portfolio-analysis/scripts/balance.py"), ["acc-1"], capsys)
    assert rc == 0 and out["balances"] == [{"cash": 1.0}]


def test_portfolio_script_usage_error(sdk, capsys) -> None:
    rc, out = run_json(load_script("portfolio-analysis/scripts/portfolio.py"), [], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_quote_script_passes_hub_and_reports_source(monkeypatch, capsys) -> None:
    seen = {}

    def fake_quote(syms, hub=None):
        seen["hub"] = hub
        return [{"symbol": s, "price": 1.0, "source": "yahoo", "realtime": False} for s in syms]

    monkeypatch.setattr(market, "quote", fake_quote)
    monkeypatch.setattr(router, "try_load", lambda: "HUB")
    rc, out = run_json(load_script("portfolio-analysis/scripts/quote.py"), ["aapl", "msft"], capsys)
    assert rc == 0 and seen["hub"] == "HUB" and out["quotes"][0]["symbol"] == "AAPL" and out["source"] == "yahoo"


def test_config_missing_exit_4(monkeypatch, capsys) -> None:
    from second_opinion import config
    from second_opinion.errors import ConfigError

    def boom(settings=None):
        raise ConfigError("no brokerage credentials configured", hint=config.NO_BROKER_HINT)

    monkeypatch.setattr(router, "load", boom)
    rc, out = run_json(load_script("portfolio-analysis/scripts/accounts.py"), [], capsys)
    assert rc == 4 and out["code"] == "CONFIG_MISSING" and out["hint"] == config.NO_BROKER_HINT


# ---------------------------------------------------------------------------
# performance.py / aggregate.py (shared math, stdin contract)
# ---------------------------------------------------------------------------


def test_performance_math_script_from_stdin(monkeypatch, capsys) -> None:
    import io
    import sys

    payload = {
        "flows": [{"date": "2024-09-05", "amount": 1000.0}, {"date": "2025-09-05", "amount": -1050.0}],
        "current_value": 0.0,
        "as_of": "2026-09-05",
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-analysis/scripts/performance.py").main()
    out = json.loads(capsys.readouterr().out)
    assert out["mwrr"] == pytest.approx(0.05, abs=1e-4)
    assert out["window"] == {"start": "2024-09-05", "end": "2026-09-05", "days": 730}


def test_aggregate_math_script_from_stdin(monkeypatch, capsys) -> None:
    import io
    import sys

    payload = {
        "portfolios": [
            {"account_id": "acc-1", "positions": [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 60, "price": 100.0}]},
            {"account_id": "acc-2", "positions": [{"symbol": {"symbol": "VTI"}, "units": 40, "price": 102.0}]},
        ]
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-analysis/scripts/aggregate.py").main()
    out = json.loads(capsys.readouterr().out)
    assert out["positions"] == [{"symbol": "VTI", "units": 100.0, "price": 100.8, "value": 10080.0}]
    assert out["total_value"] == 10080.0


def test_aggregate_imputes_unpriced_units_at_the_value_weighted_average(monkeypatch, capsys) -> None:
    import io
    import sys

    payload = {
        "portfolios": [
            {"account_id": "acc-a", "positions": [{"symbol": "VTI", "units": 100, "price": 100.0}]},
            {"account_id": "acc-b", "positions": [{"symbol": "VTI", "units": 50, "price": None}]},
        ]
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-analysis/scripts/aggregate.py").main()
    out = json.loads(capsys.readouterr().out)
    vti = out["positions"][0]
    assert vti["symbol"] == "VTI" and vti["units"] == 150.0 and vti["value"] == 15000.0
    assert out["flags"] == [
        {
            "code": "UNPRICED_SKIPPED",
            "message": "1 position row(s) without a price were valued at the symbol's value-weighted average price",
        }
    ]


def test_allocation_output_shape_is_the_old_contract_plus_effective_n(monkeypatch, capsys) -> None:
    import io
    import sys

    payload = {"positions": [{"symbol": "AAPL", "value": 1000, "sector": "Technology"}], "cash": 0}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-analysis/scripts/allocation.py").main()
    out = json.loads(capsys.readouterr().out)
    # no "targets" -> no "drift" key: exactly the old contract plus effective_n
    assert set(out) == {
        "total_value",
        "weights",
        "sector_weights",
        "hhi",
        "hhi_interpretation",
        "effective_n",
        "effective_n_interpretation",
        "top_5_concentration",
    }


# ---------------------------------------------------------------------------
# performance_report.py (fetch wiring)
# ---------------------------------------------------------------------------

_PERF_POSITIONS = {
    "acc-1": [{"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": 140.0}],
    "acc-2": [{"symbol": {"symbol": {"symbol": "MSFT"}}, "units": 5, "price": 200.0}],
}
_PERF_BALANCES = {
    "acc-1": [{"currency": {"code": "USD"}, "cash": 500.0, "buying_power": 500.0}],
    "acc-2": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}],
}
_SPY_HISTORY = {
    "SPY": [
        {"date": "2025-09-05", "close": 100.0, "adj_close": 100.0},
        {"date": "2026-06-01", "close": 105.0, "adj_close": 105.0},
        {"date": "2026-09-05", "close": 110.0, "adj_close": 110.0},
    ]
}


@pytest.fixture
def perf_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: _PERF_POSITIONS[account_id],
        get_user_account_balance=lambda account_id: _PERF_BALANCES[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {"AAPL": {"price": 150.0, "previous_close": 148.0}})
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: _SPY_HISTORY)
    return fake


def _write_ledger(tmp_path, transactions: list[dict]) -> None:
    (tmp_path / "ledger.json").write_text(json.dumps({"transactions": transactions, "imports": []}))


def test_performance_report_end_to_end(perf_sdk, capsys, tmp_path) -> None:
    _write_ledger(
        tmp_path,
        [
            {"date": "2025-09-05", "type": "DEPOSIT", "amount": 1000.0, "account_id": "acc-1"},
            {"date": "2025-12-05", "type": "WITHDRAWAL", "amount": -100.0, "account_id": "acc-1"},
            {"date": "2025-09-05", "type": "DEPOSIT", "amount": 999.0, "account_id": "acc-2"},  # other account
            {"date": "2025-10-05", "type": "DIVIDEND", "amount": 5.0, "account_id": "acc-1"},  # not a flow
        ],
    )
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1", "--as-of", "2026-09-05"], capsys)
    assert rc == 0, out
    # current value = 10 * 150 (Yahoo refresh) + 500 cash
    assert out["current_value"] == 2000.0
    assert out["net_flows"] == 900.0 and out["flow_count"] == 2
    assert out["window"]["start"] == "2025-09-05"
    assert out["mwrr"] is not None
    assert out["benchmark_total_return"] == pytest.approx(0.10, abs=1e-4)
    assert out["benchmark"] == "SPY" and out["account_id"] == "acc-1"
    assert out["sources"] == {"flows": "ledger", "balances": "snaptrade", "prices": "yahoo", "benchmark": "yahoo"}


def test_performance_report_passes_the_window_to_yahoo(perf_sdk, monkeypatch, capsys, tmp_path) -> None:
    _write_ledger(
        tmp_path,
        [
            {"date": "2025-09-05", "type": "DEPOSIT", "amount": 1000.0, "account_id": "acc-1"},
            {"date": "2025-12-05", "type": "WITHDRAWAL", "amount": -100.0, "account_id": "acc-1"},
        ],
    )
    calls = []
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: calls.append((symbols, start)) or _SPY_HISTORY)
    run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1", "--as-of", "2026-09-05"], capsys)
    assert calls == [(["SPY"], "2025-09-05")]  # first flow date is the start


def test_performance_report_since_filters_flows(perf_sdk, monkeypatch, capsys, tmp_path) -> None:
    _write_ledger(
        tmp_path,
        [
            {"date": "2025-09-05", "type": "DEPOSIT", "amount": 1000.0, "account_id": "acc-1"},
            {"date": "2025-12-05", "type": "WITHDRAWAL", "amount": -100.0, "account_id": "acc-1"},
        ],
    )
    calls = []
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: calls.append(start) or _SPY_HISTORY)
    rc, out = run_json(
        load_script("portfolio-analysis/scripts/performance_report.py"),
        ["acc-1", "--since", "2025-12-01", "--as-of", "2026-09-05"],
        capsys,
    )
    assert rc == 0, out
    assert out["flow_count"] == 1 and out["net_flows"] == -100.0
    assert out["window"]["start"] == "2025-12-05"
    assert out["mwrr"] is None  # a single flow in the window
    assert [f["code"] for f in out["flags"]] == ["TOO_FEW_FLOWS"]
    assert calls == ["2025-12-05"]  # the first (filtered) flow date is the benchmark start


def test_performance_report_since_is_the_start_without_flows(perf_sdk, monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: calls.append(start) or _SPY_HISTORY)
    rc, out = run_json(
        load_script("portfolio-analysis/scripts/performance_report.py"),
        ["acc-1", "--since", "2025-06-01", "--as-of", "2026-09-05"],
        capsys,
    )
    assert rc == 0, out
    assert out["flow_count"] == 0 and out["mwrr"] is None
    assert [f["code"] for f in out["flags"]] == ["TOO_FEW_FLOWS"]
    assert calls == ["2025-06-01"]  # --since stands in when the ledger has no flows


def test_performance_report_benchmark_failure_degrades(perf_sdk, monkeypatch, capsys, tmp_path) -> None:
    _write_ledger(tmp_path, [{"date": "2025-09-05", "type": "DEPOSIT", "amount": 1000.0, "account_id": "acc-1"}, {"date": "2025-12-05", "type": "DEPOSIT", "amount": 100.0, "account_id": "acc-1"}])

    def boom(symbols, start):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "close_histories", boom)
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1", "--as-of", "2026-09-05"], capsys)
    assert rc == 0, out
    assert out["mwrr"] is not None  # the return still computes
    assert out["benchmark_total_return"] is None and out["benchmark_annualized"] is None
    assert [f["code"] for f in out["flags"]] == ["BENCHMARK_UNAVAILABLE"]
    assert out["sources"]["benchmark"] is None


def test_performance_report_position_price_fallback(perf_sdk, monkeypatch, capsys) -> None:
    def boom(symbols, hub=None):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "day_changes", boom)
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1", "--as-of", "2026-09-05"], capsys)
    assert rc == 0, out
    assert out["current_value"] == 10 * 140.0 + 500.0  # broker price fallback
    assert out["sources"]["prices"] == "snaptrade"


def test_performance_report_falls_through_to_yahoo_when_broker_price_missing(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    positions = {"acc-1": [{"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": None}]}
    balances = {"acc-1": [{"currency": {"code": "USD"}, "cash": 500.0, "buying_power": 500.0}]}
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: positions[account_id],
        get_user_account_balance=lambda account_id: balances[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    calls = []
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: calls.append(list(symbols)) or {"AAPL": {"price": 150.0, "previous_close": 148.0}})
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1", "--as-of", "2026-09-05"], capsys)
    assert rc == 0, out
    # the symbol is still sent to Yahoo (and priced from it) despite having no broker price
    assert calls == [["AAPL"]]
    assert out["current_value"] == 10 * 150.0 + 500.0
    assert out["sources"]["prices"] == "yahoo"


def test_performance_report_skips_non_positive_units(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    positions = {
        "acc-1": [
            {"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 10, "price": 140.0},
            {"symbol": {"symbol": {"symbol": "OLD"}}, "units": 0, "price": 50.0},
            {"symbol": {"symbol": {"symbol": "SHORT"}}, "units": -3, "price": 50.0},
        ]
    }
    balances = {"acc-1": [{"currency": {"code": "USD"}, "cash": 500.0, "buying_power": 500.0}]}
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: positions[account_id],
        get_user_account_balance=lambda account_id: balances[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    calls = []
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: calls.append(list(symbols)) or {})
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1", "--as-of", "2026-09-05"], capsys)
    assert rc == 0, out
    # OLD (zero units) and SHORT (negative units) are excluded, like aggregate.py
    assert calls == [["AAPL"]]
    assert out["current_value"] == 10 * 140.0 + 500.0


def test_performance_report_errors(perf_sdk, monkeypatch, capsys, tmp_path) -> None:
    (tmp_path / "ledger.json").write_text("not json{{{")
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1"], capsys)
    assert rc == 5 and out["code"] == "LEDGER_CORRUPT"  # corrupt store surfaces, exit 5
    (tmp_path / "ledger.json").unlink()

    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["nope"], capsys)
    assert rc == 2 and "unknown account" in out["error"]
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), [], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1", "--since", "09/05/2025"], capsys)
    assert rc == 2 and "--since" in out["error"]
    rc, out = run_json(load_script("portfolio-analysis/scripts/performance_report.py"), ["acc-1", "--benchmark", "NOT VALID!"], capsys)
    assert rc == 2 and "invalid symbol" in out["error"]


# ---------------------------------------------------------------------------
# aggregate_report.py (fetch wiring)
# ---------------------------------------------------------------------------

_AGG_POSITIONS = {
    "acc-1": [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 60, "price": 100.0}],
    "acc-2": [
        {"symbol": {"symbol": {"symbol": "VTI"}}, "units": 40, "price": 102.0},
        {"symbol": {"symbol": {"symbol": "BND"}}, "units": 30, "price": 50.0},
    ],
}


@pytest.fixture
def agg_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: _AGG_POSITIONS[account_id],
        get_user_account_balance=lambda account_id: [{"cash": 0.0}],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {})
    return fake


def test_aggregate_report_end_to_end(agg_sdk, monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: calls.append(list(symbols)) or {"VTI": {"price": 110.0, "previous_close": 100.0}})
    rc, out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["acc-2", "acc-1"], capsys)
    assert rc == 0, out
    assert calls == [["BND", "VTI"]]  # exactly one batched call
    assert out["positions"] == [
        {"symbol": "VTI", "units": 100.0, "price": 110.0, "value": 11000.0},
        {"symbol": "BND", "units": 30.0, "price": 50.0, "value": 1500.0},
    ]
    assert out["accounts"] == ["acc-1", "acc-2"] and out["total_value"] == 12500.0
    assert out["sources"] == {"holdings": "snaptrade", "quotes": "yahoo"}


def test_aggregate_report_falls_back_to_broker_prices(agg_sdk, monkeypatch, capsys) -> None:
    rc, out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["acc-1", "acc-2"], capsys)
    assert rc == 0, out
    vti = next(p for p in out["positions"] if p["symbol"] == "VTI")
    assert vti["price"] == 100.8 and vti["value"] == 10080.0  # value-weighted broker price
    assert out["sources"] == {"holdings": "snaptrade", "quotes": "snaptrade"}


def test_aggregate_report_names_the_quote_source_it_actually_used(agg_sdk, monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {"VTI": {"price": 110.0, "previous_close": 100.0, "source": "etrade"}})
    rc, out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["acc-1"], capsys)
    assert rc == 0 and out["sources"]["quotes"] == "etrade"  # not a blanket "yahoo"


def test_aggregate_report_dedupes_repeated_account_ids(agg_sdk, capsys) -> None:
    dup_rc, dup_out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["acc-1", "acc-1"], capsys)
    single_rc, single_out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["acc-1"], capsys)
    assert dup_rc == 0 == single_rc
    assert dup_out["positions"] == single_out["positions"]
    assert dup_out["accounts"] == single_out["accounts"] == ["acc-1"]
    assert dup_out["total_value"] == single_out["total_value"]


def test_aggregate_report_day_changes_failure_degrades(agg_sdk, monkeypatch, capsys) -> None:
    def boom(symbols, hub=None):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "day_changes", boom)
    rc, out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["acc-1", "acc-2"], capsys)
    assert rc == 0, out
    assert out["sources"]["quotes"] == "snaptrade" and out["total_value"] == 11580.0


def test_aggregate_report_skips_unknown_ids_and_flags_them(agg_sdk, capsys) -> None:
    rc, out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["acc-1", "nope", "1234"], capsys)
    assert rc == 0, out
    assert out["accounts"] == ["acc-1"] and out["total_value"] == 6000.0
    assert out["sources"]["holdings"] == "snaptrade"
    codes = [f["code"] for f in out["flags"]]
    assert codes == ["UNKNOWN_ACCOUNT", "UNKNOWN_ACCOUNT"]
    assert out["flags"][0]["message"].startswith("unknown account id nope; run accounts.py")
    # a direct E*Trade id pasted into a SnapTrade-only setup is acc-1's account_number
    assert "1234 is the account_number of snaptrade account acc-1" in out["flags"][1]["message"]
    assert agg_sdk.kwargs_for("get_user_account_positions") == [{"account_id": "acc-1"}]  # unknown ids never fetched


def test_aggregate_report_errors(agg_sdk, monkeypatch, capsys) -> None:
    rc, out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["nope", "1234"], capsys)
    assert rc == 2 and out["error"].startswith("unknown account id(s): nope, 1234; run accounts.py")  # no known id: exit 2
    assert "1234 is the account_number of snaptrade account acc-1" in out["error"] and "direct etrade adapter" in out["error"]
    rc, out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), [], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
    rc, out = run_json(load_script("portfolio-analysis/scripts/aggregate_report.py"), ["acc-2", "--nope"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
