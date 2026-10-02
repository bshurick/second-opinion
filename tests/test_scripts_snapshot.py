from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client, market
from second_opinion.brokers import router
from scripts_util import PLUGIN_ROOT
from page_dom import assert_page_help, render_and_audit, requires_chrome

POSITIONS = {
    "acc-1": [
        {"symbol": {"symbol": {"symbol": "AAPL", "description": "Apple Inc."}}, "units": 10, "price": 100.0, "average_purchase_price": 80.0},
        {"symbol": {"symbol": {"symbol": "MSFT", "description": "Microsoft"}}, "units": 5, "price": 200.0, "average_purchase_price": 220.0},
    ],
    "acc-2": [{"symbol": {"symbol": {"symbol": "AAPL", "description": "Apple Inc."}}, "units": 10, "price": 100.0, "average_purchase_price": 120.0}],
}
BALANCES = {"acc-1": [{"currency": {"code": "USD"}, "cash": 500.0, "buying_power": 500.0}], "acc-2": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}]}


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: POSITIONS[account_id],
        get_user_account_balance=lambda account_id: BALANCES[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "c")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "k")
    monkeypatch.setenv("SNAPTRADE_ACCOUNT_TYPES", "acc-1=margin")
    return fake


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


@pytest.fixture
def yahoo(monkeypatch):
    calls: dict[str, list] = {"day_changes": [], "close_histories": [], "sectors": [], "next_events": []}

    def day_changes(symbols, hub=None):
        calls["day_changes"].append(list(symbols))
        return {"AAPL": {"price": 100.0, "previous_close": 98.0}}

    def close_histories(symbols, start):
        calls["close_histories"].append((list(symbols), start))
        return {
            "AAPL": [{"date": f"2026-08-{d:02d}", "close": 90.0 + d} for d in range(1, 25)],
            "MSFT": [{"date": "2026-08-20", "close": 200.0}],
        }

    def sectors(symbols, cache_path=None):
        calls["sectors"].append(list(symbols))
        return {
            s: {"sector": "Technology", "name": None, "quote_type": "EQUITY" if s.upper() == "AAPL" else "ETF",
                "category": None if s.upper() == "AAPL" else "Intermediate Core Bond", "country": "United States" if s.upper() == "AAPL" else None,
                "summary": "Apple designs phones." if s.upper() == "AAPL" else None, "website": "https://www.apple.com" if s.upper() == "AAPL" else None}
            for s in symbols
        }

    def next_events(symbol):
        calls["next_events"].append(symbol)
        return {"next_earnings": "2026-10-20", "next_ex_dividend": None}

    monkeypatch.setattr(market, "day_changes", day_changes)
    monkeypatch.setattr(market, "close_histories", close_histories)
    monkeypatch.setattr(market, "sectors", sectors)
    def recent_news(symbol, days=7, limit=3):
        calls.setdefault("recent_news", []).append(symbol)
        return [{"title": f"{symbol} story", "publisher": "Wire", "published": "2026-09-13T12:00+00:00", "url": "https://example.com/a", "summary": None}]

    monkeypatch.setattr(market, "next_events", next_events)
    monkeypatch.setattr(market, "recent_news", recent_news)
    return calls


def test_snapshot_aggregates_all_accounts_with_one_call_per_endpoint(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 0, out
    assert out["totals"]["total_value"] == 3500.0 and out["totals"]["cash"] == 500.0
    assert out["totals"]["day_change"] == 40.0
    assert [a["account_id"] for a in out["accounts"]] == ["acc-1", "acc-2"]
    assert out["accounts"][0]["account_type"] == "margin" and out["accounts"][0]["supports_trading"] is True
    assert out["accounts"][1]["account_type"] == "cash" and out["accounts"][1]["supports_trading"] is False
    assert out["positions"][0]["symbol"] == "AAPL" and out["positions"][0]["accounts"] == ["acc-1", "acc-2"]
    assert out["sector_weights"] == {"Technology": 1.0}
    assert out["events"] is None
    assert out["as_of"] and out["sources"] == {"holdings": "snaptrade", "quotes": "yahoo", "sectors": "yahoo", "events": None, "news": "yahoo"}
    assert len(sdk.kwargs_for("list_user_accounts")) == 1
    assert [k["account_id"] for k in sdk.kwargs_for("get_user_account_positions")] == ["acc-1", "acc-2"]
    assert [k["account_id"] for k in sdk.kwargs_for("get_user_account_balance")] == ["acc-1", "acc-2"]
    # exactly ONE batched day_changes call for prices/day changes, ONE sectors call
    assert yahoo["day_changes"] == [["AAPL", "MSFT"]] and yahoo["sectors"] == [["AAPL", "MSFT"]] and yahoo["next_events"] == []


def test_snapshot_stops_for_a_login_before_showing_anything_partial(sdk, yahoo, monkeypatch, capsys) -> None:
    from test_brokers_router import FailingDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(sdk, extra_brokers=(FailingDirect(),)))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 4 and out["code"] == "ETRADE_REAUTH", out
    assert out["url"] == FailingDirect.LOGIN_URL and out["hint"] == "log in again" and out["partial"] == "--partial"
    assert "accounts" not in out  # nothing partial is rendered before the login
    assert yahoo["day_changes"] == []  # and no quotes were fetched for it


def test_snapshot_flags_a_broker_that_could_not_be_listed(sdk, yahoo, monkeypatch, capsys) -> None:
    from test_brokers_router import FailingDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(sdk, extra_brokers=(FailingDirect(),)))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--partial"], capsys)
    assert rc == 0, out
    assert [a["account_id"] for a in out["accounts"]] == ["acc-1", "acc-2"]  # the run still happens
    assert {"code": "BROKER_UNAVAILABLE", "message": "etrade: E*Trade login required (token expired); its accounts are excluded from this run"} in out["flags"]
    assert out["sources"]["holdings"] == "snaptrade"  # never claims the broker that failed


def test_snapshot_targeting_a_failed_brokers_account_reports_that_broker(sdk, yahoo, monkeypatch, tmp_path, capsys) -> None:
    from second_opinion.brokers import registry
    from second_opinion.brokers.snaptrade import SnapTradeBroker
    from test_brokers_router import FailingDirect

    reg = registry.Registry(tmp_path / "brokers.json")
    reg.save([{"account_id": "KEY1", "broker": "etrade", "account_number": "1234"}])  # cached from a good day
    hub = router.Hub([FailingDirect(), SnapTradeBroker(sdk)], account_types={}, registry=reg)
    monkeypatch.setattr(router, "load", lambda settings=None: hub)
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--account", "KEY1", "--partial"], capsys)
    assert rc == 4 and out["code"] == "ETRADE_REAUTH"  # not "unknown account id"
    assert out["hint"] == "log in again" and "KEY1" in out["error"]


def test_snapshot_typo_stays_exit_2_when_a_broker_is_down(sdk, yahoo, monkeypatch, capsys) -> None:
    from test_brokers_router import FailingDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(sdk, extra_brokers=(FailingDirect(),)))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--account", "nope", "--partial"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
    assert "accounts.py" in out["error"] and "etrade is unavailable" in out["error"]


def test_snapshot_passes_quote_types_and_history_to_summary(sdk, yahoo, data_dir, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 0, out
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    msft = next(p for p in out["positions"] if p["symbol"] == "MSFT")
    # 24 closes 91..114: week base = close 5 back (109), month base = close 21 back (93)
    assert aapl["week_change_pct"] == round(114 / 109 - 1, 4)
    assert aapl["month_change_pct"] == round(114 / 93 - 1, 4)
    assert msft["week_change_pct"] is None and msft["month_change_pct"] is None
    assert out["asset_classes"] == {
        "stock": {"value": 2000.0, "weight": 0.6667, "count": 1},
        "fund": {"value": 1000.0, "weight": 0.3333, "count": 1},
        "other": {"value": 0.0, "weight": 0.0, "count": 0},
    }
    assert out["totals"]["no_cost_basis_value"] == 0.0 and out["totals"]["no_cost_basis_pct"] == 0.0
    expected_start = (datetime.now(timezone.utc) - timedelta(days=370)).date().isoformat()  # one year for the page
    assert yahoo["close_histories"] == [(["AAPL", "MSFT"], expected_start)]
    assert yahoo["day_changes"] == [["AAPL", "MSFT"]]  # one batched call yields prices/day changes
    assert yahoo["sectors"] == [["AAPL", "MSFT"]]  # one call yields sectors and quote types


def test_snapshot_account_filter(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--account", "acc-2"], capsys)
    assert rc == 0 and [a["account_id"] for a in out["accounts"]] == ["acc-2"]
    assert out["totals"]["total_value"] == 1000.0
    assert [k["account_id"] for k in sdk.kwargs_for("get_user_account_positions")] == ["acc-2"]


def test_snapshot_unknown_account_exit_2(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--account", "nope"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT" and "nope" in out["error"]


def test_snapshot_events_flag(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--events"], capsys)
    assert rc == 0
    assert out["events"] == [{"symbol": "AAPL", "type": "earnings", "date": "2026-10-20"}, {"symbol": "MSFT", "type": "earnings", "date": "2026-10-20"}]
    assert sorted(yahoo["next_events"]) == ["AAPL", "MSFT"] and out["sources"]["events"] == "yahoo"


def test_snapshot_no_quotes_flag_skips_yahoo_quotes(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-quotes"], capsys)
    assert rc == 0 and out["totals"]["day_change"] is None and yahoo["day_changes"] == []
    assert out["sources"]["quotes"] == "snaptrade"
    # --no-quotes only skips the quote/history fetch; the always-on sectors call still
    # supplies sector_weights and quote_types (so asset_classes is still present)
    assert "week_change_pct" not in out["positions"][0] and "asset_classes" in out


def test_snapshot_sources_quotes_reflects_direct_rows(sdk, data_dir, capsys, monkeypatch) -> None:
    monkeypatch.setattr(market, "day_changes", lambda syms, hub=None: {s: {"price": 1.0, "previous_close": 1.0, "source": "etrade"} for s in syms})
    monkeypatch.setattr(market, "sectors", lambda syms, cache_path=None: {})
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 0 and out["sources"]["quotes"] == "etrade" and out["sources"]["holdings"] == "snaptrade"


def test_snapshot_history_failure_degrades_with_note_flag(sdk, yahoo, monkeypatch, capsys) -> None:
    def boom(symbols, start):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "close_histories", boom)
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 0 and "week_change_pct" not in out["positions"][0]
    assert {"code": "HISTORY_UNAVAILABLE", "message": "Yahoo price history failed (yahoo down); 1w/1m changes omitted"} in out["flags"]
    assert "asset_classes" in out  # quote types still come through


def test_snapshot_history_rows_out_of_order_still_computes_correct_changes(sdk, yahoo, monkeypatch, capsys) -> None:
    def close_histories(symbols, start):
        # same 24 AAPL closes as the `yahoo` fixture, but shuffled (not oldest-first)
        rows = [{"date": f"2026-08-{d:02d}", "close": 90.0 + d} for d in range(1, 25)]
        shuffled = list(reversed(rows))
        shuffled.insert(3, shuffled.pop(0))
        return {"AAPL": shuffled, "MSFT": [{"date": "2026-08-20", "close": 200.0}]}

    monkeypatch.setattr(market, "close_histories", close_histories)
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 0
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    # same result as ascending input: last close 114, week base 109, month base 93
    assert aapl["week_change_pct"] == round(114 / 109 - 1, 4)
    assert aapl["month_change_pct"] == round(114 / 93 - 1, 4)


def test_snapshot_yahoo_failure_degrades_to_broker_prices(sdk, yahoo, monkeypatch, capsys) -> None:
    def boom(symbols, hub=None):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market, "day_changes", boom)
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 0 and out["totals"]["total_value"] == 3500.0 and out["totals"]["day_change"] is None
    assert out["sources"]["quotes"] == "snaptrade"
    assert {"code": "QUOTES_UNAVAILABLE", "message": "Yahoo quotes failed (yahoo down); prices are the broker's last values"} in out["flags"]
    # history is a separate fetch: it still succeeds when quotes fail
    aapl = next(p for p in out["positions"] if p["symbol"] == "AAPL")
    assert aapl["week_change_pct"] == round(114 / 109 - 1, 4)


def test_snapshot_no_accounts_exit_5(monkeypatch, yahoo, capsys) -> None:
    fake = FakeSdk(list_user_accounts=[], list_brokerage_authorizations=[])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 5 and out["code"] == "NO_ACCOUNTS"


def test_snapshot_config_missing_exit_4(monkeypatch, capsys) -> None:
    from second_opinion import config
    from second_opinion.errors import ConfigError

    def boom(settings=None):
        raise ConfigError("missing SNAPTRADE_CLIENT_ID", hint=config.SETUP_HINT)

    monkeypatch.setattr(client, "get_client", boom)
    monkeypatch.setattr(router, "load", boom)
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 4 and out["code"] == "CONFIG_MISSING"


# ---------------------------------------------------------------------------
# --save / --compare against snapshots.json in the plugin data dir
# ---------------------------------------------------------------------------


def test_snapshot_save_appends_a_dated_record(sdk, yahoo, data_dir, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--save"], capsys)
    assert rc == 0
    data = json.loads((data_dir / "snapshots.json").read_text())
    assert len(data["snapshots"]) == 1
    rec = data["snapshots"][0]
    assert rec["as_of"] == out["as_of"]
    assert rec["total_value"] == 3500.0 and rec["cash"] == 500.0
    assert rec["symbols"] == {"AAPL": 2000.0, "MSFT": 1000.0}
    # saving never changes the snapshot output itself
    assert "comparison" not in out


def test_snapshot_save_updates_an_existing_file(sdk, yahoo, data_dir, capsys) -> None:
    (data_dir / "snapshots.json").write_text(json.dumps({"snapshots": [{"as_of": "2026-09-01T00:00:00+00:00", "total_value": 3400.0, "cash": 500.0, "symbols": {}}]}))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--save"], capsys)
    assert rc == 0
    data = json.loads((data_dir / "snapshots.json").read_text())
    assert len(data["snapshots"]) == 2 and data["snapshots"][1]["as_of"] == out["as_of"]


def test_snapshot_compare_against_the_most_recent_earlier_snapshot(sdk, yahoo, data_dir, capsys) -> None:
    (data_dir / "snapshots.json").write_text(json.dumps({"snapshots": [
        {"as_of": "2026-08-01T00:00:00+00:00", "total_value": 3300.0, "cash": 500.0, "symbols": {"AAPL": 2000.0, "MSFT": 800.0, "OLD": 500.0}},
        {"as_of": "2026-09-01T00:00:00+00:00", "total_value": 3400.0, "cash": 500.0, "symbols": {"AAPL": 2000.0, "MSFT": 900.0, "OLD": 500.0}},
    ]}))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--compare"], capsys)
    assert rc == 0
    cmp = out["comparison"]
    assert cmp["since"] == "2026-09-01T00:00:00+00:00"  # most recent strictly earlier
    expected_days = (datetime.now(timezone.utc) - datetime.fromisoformat("2026-09-01T00:00:00+00:00")).days
    assert cmp["days"] == expected_days
    assert cmp["total_value"] == {"before": 3400.0, "after": 3500.0, "delta": 100.0, "delta_pct": round(100 / 3400, 4)}
    # |delta| desc: OLD -500, MSFT +100, AAPL 0 (dropped symbol -> before kept, after null)
    assert [s["symbol"] for s in cmp["symbols"]] == ["OLD", "MSFT", "AAPL"]
    assert cmp["symbols"][0] == {"symbol": "OLD", "before": 500.0, "after": None, "delta": -500.0, "delta_pct": -1.0}
    assert cmp["symbols"][1] == {"symbol": "MSFT", "before": 900.0, "after": 1000.0, "delta": 100.0, "delta_pct": round(100 / 900, 4)}
    assert cmp["symbols"][2] == {"symbol": "AAPL", "before": 2000.0, "after": 2000.0, "delta": 0.0, "delta_pct": 0.0}
    assert cmp["n_more"] == 0


def test_snapshot_compare_without_any_prior_snapshot(sdk, yahoo, data_dir, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--compare"], capsys)
    assert rc == 0 and out["comparison"] is None
    assert {"code": "NO_SNAPSHOT", "message": "no earlier saved snapshot; run snapshot.py --save to store one"} in out["flags"]


def test_snapshot_compare_ignores_later_snapshots(sdk, yahoo, data_dir, capsys) -> None:
    (data_dir / "snapshots.json").write_text(json.dumps({"snapshots": [{"as_of": "2999-01-01T00:00:00+00:00", "total_value": 1.0, "cash": 0.0, "symbols": {}}]}))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--compare"], capsys)
    assert rc == 0 and out["comparison"] is None
    assert any(f["code"] == "NO_SNAPSHOT" for f in out["flags"])


def test_snapshot_save_and_compare_in_one_run(sdk, yahoo, data_dir, capsys) -> None:
    (data_dir / "snapshots.json").write_text(json.dumps({"snapshots": [{"as_of": "2026-09-01T00:00:00+00:00", "total_value": 3400.0, "cash": 500.0, "symbols": {"AAPL": 2000.0, "MSFT": 900.0}}]}))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--save", "--compare"], capsys)
    assert rc == 0 and out["comparison"]["since"] == "2026-09-01T00:00:00+00:00"
    data = json.loads((data_dir / "snapshots.json").read_text())
    assert len(data["snapshots"]) == 2
    assert data["snapshots"][1]["as_of"] == out["as_of"] and data["snapshots"][1]["total_value"] == 3500.0


def test_snapshot_corrupt_snapshots_file_exit_5(sdk, yahoo, data_dir, capsys) -> None:
    (data_dir / "snapshots.json").write_text("{not json")
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--compare"], capsys)
    assert rc == 5 and out["code"] == "SNAPSHOTS_CORRUPT" and "snapshots.json" in out["hint"]


def test_snapshot_save_with_unexpected_shape_exit_5(sdk, yahoo, data_dir, capsys) -> None:
    (data_dir / "snapshots.json").write_text(json.dumps({"snapshots": 5}))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--save"], capsys)
    assert rc == 5 and out["code"] == "SNAPSHOTS_CORRUPT"


def test_snapshot_compare_caps_symbols_at_25(monkeypatch, yahoo, data_dir, capsys) -> None:
    positions = [
        {"symbol": {"symbol": {"symbol": f"S{i:02d}", "description": None}}, "units": 1, "price": float(i), "average_purchase_price": 1.0}
        for i in range(30)
    ]
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: positions,
        get_user_account_balance=lambda account_id: BALANCES[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    (data_dir / "snapshots.json").write_text(json.dumps({"snapshots": [
        {"as_of": "2026-08-01T00:00:00+00:00", "total_value": 0.0, "cash": 500.0, "symbols": {f"S{i:02d}": 0.0 for i in range(30)}}
    ]}))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-quotes", "--compare"], capsys)
    assert rc == 0
    cmp = out["comparison"]
    assert len(cmp["symbols"]) == 25 and cmp["n_more"] == 5
    assert [s["symbol"] for s in cmp["symbols"]][:3] == ["S29", "S28", "S27"]
    assert cmp["symbols"][0]["delta_pct"] is None  # before is 0 -> no percentage


def test_snapshot_compare_excludes_null_priced_positions_from_after(monkeypatch, yahoo, data_dir, capsys) -> None:
    positions = {
        "acc-1": [
            {"symbol": "AAPL", "units": 10, "price": 100.0, "average_purchase_price": 80.0},
            {"symbol": "ZZZZ", "units": 5, "price": None, "average_purchase_price": 10.0},
        ],
    }
    balances = {"acc-1": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}]}
    fake = FakeSdk(
        list_user_accounts=[ACCOUNTS[0]],
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: positions[account_id],
        get_user_account_balance=lambda account_id: balances[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    # ZZZZ was priced (800.0) in the saved snapshot but is unpriced (null market_value)
    # in the current run; a brand-new unpriced symbol (never saved) must not appear at all.
    (data_dir / "snapshots.json").write_text(json.dumps({"snapshots": [
        {"as_of": "2026-08-01T00:00:00+00:00", "total_value": 1800.0, "cash": 0.0, "symbols": {"AAPL": 1000.0, "ZZZZ": 800.0}},
    ]}))
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-quotes", "--compare"], capsys)
    assert rc == 0
    symbols = {s["symbol"]: s for s in out["comparison"]["symbols"]}
    assert symbols["ZZZZ"] == {"symbol": "ZZZZ", "before": 800.0, "after": None, "delta": -800.0, "delta_pct": -1.0}
    assert "AAPL" in symbols


def test_summary_accepts_a_margin_debit_and_flags_it(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    from scripts_util import load_script

    payload = {
        "accounts": [
            {"account_id": "m-1", "name": "Margin", "cash": -0.8, "positions": [{"symbol": "AAA", "units": 10, "price": 10.0, "average_purchase_price": 9.0}]},
            {"account_id": "c-1", "name": "Cash", "cash": 50.0, "positions": []},
        ],
        "prices": {"AAA": {"price": 10.0, "previous_close": 10.0}},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    assert out["totals"]["cash"] == 49.2 and out["totals"]["total_value"] == 149.2
    assert any(f["code"] == "MARGIN_DEBIT" and "Margin" in f["message"] for f in out["flags"])


def test_summary_counts_a_money_market_core_position_once(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    from scripts_util import load_script

    payload = {
        "accounts": [
            {
                "account_id": "fido-1",
                "name": "Fidelity",
                "cash": 1250.40,
                "positions": [{"symbol": "SPAXX", "units": 1250.40, "price": 1.0}],
            },
            {
                "account_id": "etrade-1",
                "name": "E*Trade",
                "cash": -0.8,
                "positions": [{"symbol": "MVRXX", "units": 12000.55, "price": 1.0}],
            },
        ],
        "asset_info": {
            "SPAXX": {"quote_type": "MONEYMARKET", "name": "Government Money Market"},
            "MVRXX": {"quote_type": "MONEYMARKET", "name": "Government Money Market"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    totals = out["totals"]
    assert totals["market_value"] == round(1250.40 + 12000.55, 2)
    assert totals["cash"] == -0.8  # Fidelity's SPAXX cash is backed out; E*Trade keeps its -0.8
    assert totals["total_value"] == round(1250.40 + 12000.55 - 0.8, 2)
    # cash_like floors the settled-cash total at 0.0 (like the allocation bucket) before adding
    # the money-market fund positions back, so the E*Trade debit does not offset them.
    assert totals["cash_like"] == round(1250.40 + 12000.55, 2)
    assert totals["cash_like_pct"] == round((1250.40 + 12000.55) / (1250.40 + 12000.55 - 0.8), 4)
    accounts_by_id = {a["account_id"]: a for a in out["accounts"]}
    assert accounts_by_id["fido-1"]["cash"] == 0.0
    assert accounts_by_id["fido-1"]["cash_adjusted_for_money_market"] == 1250.40
    assert accounts_by_id["etrade-1"]["cash"] == -0.8
    assert accounts_by_id["etrade-1"]["cash_adjusted_for_money_market"] == 0.0
    assert any(f["code"] == "CASH_DRAG" and "cash and money-market funds" in f["message"] for f in out["flags"])
    assert out["allocation"]["buckets"]["cash"]["value"] == totals["cash_like"]


def test_summary_leaves_real_settled_cash_beside_a_money_market_fund_alone(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    from scripts_util import load_script

    payload = {
        "accounts": [
            {
                "account_id": "a-1",
                "cash": 5000.0,
                "positions": [{"symbol": "SPAXX", "units": 1250.40, "price": 1.0}],
            }
        ],
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    totals = out["totals"]
    # reported cash (5000) is nowhere near the money-market position's value (1250.40), so a
    # broker did not report the same dollars on both sides: nothing is subtracted.
    assert totals["cash"] == 5000.0
    assert totals["total_value"] == round(5000.0 + 1250.40, 2)
    assert out["accounts"][0]["cash_adjusted_for_money_market"] == 0.0


def test_summary_matches_a_single_core_fund_beside_a_second_money_market_position(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    from scripts_util import load_script

    payload = {
        "accounts": [
            {
                "account_id": "fido-1",
                "name": "Fidelity",
                "cash": 1250.40,
                "positions": [
                    {"symbol": "SPAXX", "units": 1250.40, "price": 1.0},
                    {"symbol": "FDRXX", "units": 10000.0, "price": 1.0},
                ],
            },
        ],
        "asset_info": {
            "SPAXX": {"quote_type": "MONEYMARKET", "name": "Government Money Market"},
            "FDRXX": {"quote_type": "MONEYMARKET", "name": "Government Cash Reserves"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    totals = out["totals"]
    # Only SPAXX (1250.40) matches the reported cash; FDRXX (10,000) is a separate holding and is
    # never folded into the match, so both positions are counted once each.
    assert totals["market_value"] == round(1250.40 + 10000.0, 2)
    assert totals["cash"] == 0.0
    assert totals["cash_like"] == round(1250.40 + 10000.0, 2)
    account = out["accounts"][0]
    assert account["cash"] == 0.0
    assert account["cash_adjusted_for_money_market"] == 1250.40


def test_summary_sub_dollar_money_market_never_zeroes_a_margin_debit(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    from scripts_util import load_script

    payload = {
        "accounts": [
            {
                "account_id": "a-1",
                "cash": -0.40,
                "positions": [{"symbol": "SPAXX", "units": 0.50, "price": 1.0}],
            }
        ],
        "asset_info": {"SPAXX": {"quote_type": "MONEYMARKET", "name": "Government Money Market"}},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    assert out["totals"]["cash"] == -0.40
    assert out["accounts"][0]["cash"] == -0.40
    assert out["accounts"][0]["cash_adjusted_for_money_market"] == 0.0


def test_render_builds_a_self_contained_page(tmp_path, capsys) -> None:
    import json

    snapshot = {
        "as_of": "2026-09-14T18:28:32+00:00",
        "sources": {"holdings": "mixed", "quotes": "mixed"},
        "totals": {"total_value": 149.2, "cash": 49.2, "cash_pct": 0.33, "day_change": 1.0, "day_change_pct": 0.0067, "day_change_coverage": 1.0, "unrealized_pnl": 10.0, "no_cost_basis_pct": 0.0},
        "accounts": [{"account_id": "m-1", "name": "Margin", "institution_name": "X", "account_type": "margin", "supports_trading": True, "total_value": 99.2, "cash": -0.8, "weight": 0.66, "position_count": 1}],
        "positions": [{"symbol": "AAA", "name": "Aaa <Co>", "units": 10, "price": 10.0, "market_value": 100.0, "weight": 0.67, "unrealized_pnl": 10.0, "day_change_pct": 0.01, "sector": "Tech", "accounts": ["m-1"]}],
        "top_holdings": [], "concentration": {"hhi": 0.5, "hhi_interpretation": "concentrated", "top_5_concentration": 1.0, "position_count": 1},
        "sector_weights": {"Tech": 1.0}, "asset_classes": {"stock": {"value": 100.0, "weight": 0.67, "count": 1}},
        "movers": {"up": [{"symbol": "AAA", "day_change_pct": 0.01, "day_change": 1.0}], "down": []}, "events": None, "comparison": None,
        "flags": [{"code": "MARGIN_DEBIT", "message": "Margin has a negative cash balance (-0.8)"}],
    }
    src = tmp_path / "snap.json"
    src.write_text(json.dumps(snapshot))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res["out"] == str(out) and res["positions"] == 1 and res["flags"] == 1
    html = out.read_text()
    assert html.startswith("<title>Portfolio Snapshot</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"MARGIN_DEBIT"' in html and "Aaa <\\/Co>" not in html  # data is JSON, tags stay escaped at render time
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html


def test_render_rejects_non_snapshot_input(tmp_path, capsys) -> None:
    src = tmp_path / "bad.json"
    src.write_text('{"hello": 1}')
    rc, res = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "snapshot.py result" in res["error"]



def test_snapshot_attaches_dated_news_to_movers(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), [], capsys)
    assert rc == 0, out
    movers = [m["symbol"] for m in out["movers"]["up"] + out["movers"]["down"]]
    assert movers and set(out["news"]) == set(movers) and out["sources"]["news"] == "yahoo"
    assert out["news"][movers[0]][0]["title"] == f"{movers[0]} story"
    assert yahoo["recent_news"] == movers


def test_snapshot_no_news_flag_skips_headlines(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-news"], capsys)
    assert rc == 0 and out["news"] is None and out["sources"]["news"] is None and "recent_news" not in yahoo


def test_summary_concentration_ignores_funds_when_classes_known(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    from scripts_util import load_script

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "BND", "units": 100, "price": 10.0},
            {"symbol": "AAA", "units": 1, "price": 10.0},
            {"symbol": "BBB", "units": 1, "price": 5.0},
        ]}],
        "prices": {"BND": {"price": 10.0}, "AAA": {"price": 10.0}, "BBB": {"price": 5.0}},
        "quote_types": {"BND": "ETF", "AAA": "EQUITY", "BBB": "EQUITY"},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    c = out["concentration"]
    assert c["hhi"] > 0.18 and c["largest_position"] == {"symbol": "BND", "weight": round(1000 / 1015, 4), "asset_class": "fund"}
    ss = c["single_stock"]
    assert ss["count"] == 2 and ss["largest"]["symbol"] == "AAA" and ss["hhi"] < 0.01 and ss["hhi_interpretation"] == "diversified"
    assert not any(f["code"] == "CONCENTRATED" for f in out["flags"])
    payload["accounts"][0]["positions"][1]["units"] = 40  # AAA becomes 400 of 1405 = 28%
    payload["prices"]["AAA"] = {"price": 10.0}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    flag = next(f for f in out["flags"] if f["code"] == "CONCENTRATED")
    assert "single-stock HHI" in flag["message"] and "AAA" in flag["message"]



def test_snapshot_allocation_buckets_from_category_and_name(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-news"], capsys)
    assert rc == 0, out
    b = out["allocation"]["buckets"]
    assert set(b) == {"us_equity", "intl_equity", "bonds", "cash", "other"}
    assert "AAPL" in b["us_equity"]["symbols"] and "MSFT" in b["bonds"]["symbols"]
    assert abs(sum(v["weight"] for v in b.values()) - 1.0) < 0.01
    assert out["allocation"]["unclassified"] == []


def test_asset_bucket_rules() -> None:
    m = load_script("portfolio-snapshot/scripts/summary.py")
    ab = m.asset_bucket
    assert ab("BND", {"quote_type": "ETF", "category": "Intermediate Core Bond", "name": "Vanguard Total Bond"}) == "bonds"
    assert ab("QBMZ", {"name": "VG IS TOT BD MKT IDX"}) == "bonds"
    assert ab("QBN5", {"name": "VANG INST 500 IDX TR"}) == "us_equity"
    assert ab("ONMY", {"name": "VG IS TL INTL STK MK"}) == "intl_equity"
    assert ab("VEA", {"quote_type": "ETF", "category": "Foreign Large Blend", "name": "Vanguard FTSE Developed Markets"}) == "intl_equity"
    assert ab("GLD", {"quote_type": "ETF", "category": "Commodities Focused", "name": "SPDR Gold Shares"}) == "other"
    assert ab("MVRXX", {"quote_type": "MONEYMARKET", "name": "Government Portfolio"}) == "cash"
    assert ab("FCASH", {"name": "CASH"}) == "cash"
    assert ab("PEP", {"quote_type": "EQUITY", "country": "United States", "name": "PepsiCo"}) == "us_equity"
    assert ab("TSM", {"quote_type": "EQUITY", "country": "Taiwan", "name": "Taiwan Semiconductor"}) == "intl_equity"
    assert ab("XYZ", {"name": "Some Trust"}) is None


def test_summary_allocation_counts_account_cash_and_flags_unclassified(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 100.0, "positions": [
            {"symbol": "BND", "units": 10, "price": 10.0}, {"symbol": "XYZ", "units": 1, "price": 100.0}]}],
        "prices": {"BND": {"price": 10.0}, "XYZ": {"price": 100.0}},
        "asset_info": {"BND": {"quote_type": "ETF", "category": "Intermediate Core Bond", "name": "Vanguard Total Bond"}, "XYZ": {"name": "Mystery Trust"}},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    b = out["allocation"]["buckets"]
    assert b["bonds"]["value"] == 100.0 and b["cash"]["value"] == 100.0 and b["other"]["symbols"] == ["XYZ"]
    assert out["allocation"]["unclassified"] == ["XYZ"]
    assert any(f["code"] == "ASSET_BUCKET_UNKNOWN" and "XYZ" in f["message"] for f in out["flags"])
    assert out["asset_classes"]["fund"]["count"] == 1  # asset_info stands in for quote_types


def test_summary_sector_exposure_looks_through_funds(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    # VTI's sector fractions are of its EQUITY SLEEVE and sum to ~1.0 on their own (Yahoo's real
    # behaviour, checked against a sector-cache.json), independent of stockPosition -- a
    # realistic, complete 11-sector breakdown summing to exactly 1.0 so the reconciliation below
    # holds with no slack term.
    vti_sectors = {
        "technology": 0.30, "healthcare": 0.10, "financial_services": 0.13,
        "consumer_cyclical": 0.11, "industrials": 0.10, "communication_services": 0.08,
        "consumer_defensive": 0.06, "energy": 0.04, "utilities": 0.03,
        "realestate": 0.03, "basic_materials": 0.02,
    }
    assert round(sum(vti_sectors.values()), 4) == 1.0
    payload = {
        "accounts": [{"account_id": "a", "cash": 500.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 1000.0},
            {"symbol": "VTI", "units": 1, "price": 2000.0},
            {"symbol": "BND", "units": 1, "price": 1000.0},
            {"symbol": "VINIX", "units": 1, "price": 10000.0},
        ]}],
        "prices": {"AAPL": {"price": 1000.0}, "VTI": {"price": 2000.0}, "BND": {"price": 1000.0}, "VINIX": {"price": 10000.0}},
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY", "sector": "Technology", "name": "Apple Inc."},
            "VTI": {"quote_type": "ETF", "name": "Vanguard Total Stock Market ETF",
                    "fund_sectors": vti_sectors,
                    "fund_asset_classes": {"stockPosition": 0.99, "cashPosition": 0.01}},
            "BND": {"quote_type": "ETF", "category": "Intermediate Core Bond", "name": "Vanguard Total Bond Market ETF",
                    "fund_sectors": None, "fund_asset_classes": {"bondPosition": 0.98, "cashPosition": 0.02}},
            # a 401(k) plan's institutional share class: Yahoo has no info for it at all, so
            # quote_type is None (not ETF/MUTUALFUND); asset_bucket still classifies it us_equity
            # from its name, and that bucket must decide where it lands;
            # its name has no "500" in it, so it does not match a look-through proxy either.
            "VINIX": {"quote_type": None, "name": "Vanguard Institutional Index Fund"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    # total_value = 1000 (AAPL) + 2000 (VTI) + 1000 (BND) + 10000 (VINIX) + 500 (cash) = 14500
    total = 14500.0
    tech = se["sectors"]["Technology"]
    # Technology: direct 1000 (AAPL) + via_funds 2000*0.99*0.30=594 (VTI, scaled by VTI's own
    # equity_frac 0.99 -- Yahoo's 0.30 is a fraction of VTI's equity sleeve, not of the whole fund)
    assert tech["direct"] == round(1000 / total, 4) == 0.069
    assert tech["via_funds"] == round(594 / total, 4) == 0.041
    assert tech["weight"] == round(tech["direct"] + tech["via_funds"], 4) == 0.11
    assert tech["funds"] == [{"symbol": "VTI", "weight": round(594 / total, 4)}]
    health = se["sectors"]["Healthcare"]
    # Healthcare: via_funds only, 2000*0.99*0.10=198
    assert health["direct"] == 0.0 and health["via_funds"] == round(198 / total, 4) == 0.0137
    # equity_share: AAPL 1000 (direct, known sector) + VTI's own equity share 2000*0.99=1980 (its
    # fund_asset_classes stockPosition); VINIX contributes nothing since it has no sector data
    assert se["equity_share"] == round((1000 + 2000 * 0.99) / total, 4) == 0.2055
    ns = se["not_sectorized"]
    # bonds_and_cash: settled cash 500 + VTI's own non-equity share 2000*(1-0.99)=20 + BND's
    # whole value 1000 (no sector data and its asset bucket is "bonds") = 1520
    assert ns["bonds_and_cash"] == round((500 + 20 + 1000) / total, 4) == 0.1048
    # funds_without_data: VINIX's whole $10,000 -- no sector data, and its asset bucket
    # (us_equity, from its name) is neither "bonds" nor "cash", so it is not silently dropped
    assert ns["funds_without_data"] == round(10000 / total, 4) == 0.6897
    assert ns["unknown_stocks"] == 0.0
    assert se["looked_through"] == ["VTI"] and se["missing_data"] == ["VINIX"]
    assert set(se["looked_through"]).isdisjoint(se["missing_data"])
    flag = next(f for f in out["flags"] if f["code"] == "SECTOR_LOOKTHROUGH_PARTIAL")
    assert "VINIX" in flag["message"] and flag["message"].startswith("no sector data (not looked through): ")

    # SECTOR_EXPOSURE_TOTAL sanity: with a complete, realistic sector breakdown every priced
    # position lands in exactly one place, so the sectorized weights plus the three
    # not_sectorized shares reconcile to 1.0 -- no slack/"untracked slice" term needed.
    total_frac = (
        sum(v["weight"] for v in se["sectors"].values())
        + ns["bonds_and_cash"] + ns["funds_without_data"] + ns["unknown_stocks"]
    )
    assert abs(total_frac - 1.0) < 0.001


def test_summary_sector_exposure_flags_funds_without_data(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 9700.0},
            {"symbol": "XYZ", "units": 1, "price": 300.0},
        ]}],
        "prices": {"AAPL": {"price": 9700.0}, "XYZ": {"price": 300.0}},
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY", "sector": "Technology"},
            "XYZ": {"quote_type": "ETF", "name": "Some Equity ETF"},  # no fund_sectors: a fetch failure
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    # total_value = 9700 + 300 = 10000; XYZ is exactly 3% of value and has no sector data
    assert se["not_sectorized"]["funds_without_data"] == round(300 / 10000, 4) == 0.03
    assert se["missing_data"] == ["XYZ"] and se["looked_through"] == []
    flag = next(f for f in out["flags"] if f["code"] == "SECTOR_LOOKTHROUGH_PARTIAL")
    assert flag["message"] == "no sector data (not looked through): XYZ (3.0% of value)"


def test_summary_sector_exposure_bond_heavy_fund_without_bond_in_its_name(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 9000.0},
            {"symbol": "XBND", "units": 1, "price": 1000.0},
        ]}],
        "prices": {"AAPL": {"price": 9000.0}, "XBND": {"price": 1000.0}},
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY", "sector": "Technology"},
            # name deliberately misses every word the bond regex looks for, but the fund's own
            # asset split says it is mostly bonds -- bondPosition must still route it correctly
            "XBND": {"quote_type": "ETF", "name": "XYZ Total Return Fund",
                     "fund_sectors": None, "fund_asset_classes": {"bondPosition": 0.85, "cashPosition": 0.05}},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    # asset_bucket("XBND", ...) would say "us_equity" (a plain ETF, no bond/commodity keyword in
    # its name), but bondPosition 0.85 >= 0.5 overrides that -- the whole position lands in
    # bonds_and_cash, not funds_without_data
    assert se["not_sectorized"]["bonds_and_cash"] == round(1000 / 10000, 4)
    assert se["not_sectorized"]["funds_without_data"] == 0.0
    assert se["missing_data"] == []
    assert not any(f["code"] == "SECTOR_LOOKTHROUGH_PARTIAL" for f in out["flags"])


def test_summary_sector_exposure_stock_sector_prefers_sectors_param(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 1000.0},
            {"symbol": "MSFT", "units": 1, "price": 500.0},
        ]}],
        "prices": {"AAPL": {"price": 1000.0}, "MSFT": {"price": 500.0}},
        "sectors": {"AAPL": "Technology"},  # MSFT is not covered by "sectors" at all
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY"},  # no "sector" key at all: "sectors" must be used
            "MSFT": {"quote_type": "EQUITY", "sector": "Technology"},  # falls back to this
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    assert se["sectors"]["Technology"]["direct"] == round(1500 / 1500, 4) == 1.0
    assert se["not_sectorized"]["unknown_stocks"] == 0.0


def test_summary_sector_exposure_null_when_no_position_has_a_quote_type(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "QBN5", "units": 1, "price": 1000.0},
        ]}],
        "prices": {"QBN5": {"price": 1000.0}},
        # a fully degraded Yahoo lookup: asset_info exists (so allocation/asset_classes still
        # render) but not one position has a quote_type at all
        "asset_info": {"QBN5": {"name": "Some 401(k) fund"}},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    assert out["sector_exposure"] is None


def test_summary_sector_exposure_proxied_institutional_fund(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 1000.0},
            {"symbol": "QBN5", "units": 1, "price": 4000.0},
        ]}],
        "prices": {"AAPL": {"price": 1000.0}, "QBN5": {"price": 4000.0}},
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY", "sector": "Technology"},
            # a 401(k) institutional S&P 500 share class Yahoo has no quote type for; snapshot.py
            # already borrowed VOO's fund data for it and marked it "proxy": "VOO"
            "QBN5": {"quote_type": None, "name": "VANG INST 500 IDX TR",
                     "fund_sectors": {"technology": 0.30, "financial_services": 0.70},
                     "fund_asset_classes": {"stockPosition": 1.0}, "proxy": "VOO"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    # total_value = 1000 (AAPL) + 4000 (QBN5) = 5000
    total = 5000.0
    assert se["looked_through"] == ["QBN5 (via VOO)"]
    tech = se["sectors"]["Technology"]
    assert tech["via_funds"] == round(4000 * 1.0 * 0.30 / total, 4) == 0.24
    assert tech["funds"] == [{"symbol": "QBN5 (via VOO)", "weight": round(1200 / total, 4)}]
    fin = se["sectors"]["Financial Services"]
    assert fin["via_funds"] == round(4000 * 1.0 * 0.70 / total, 4) == 0.56
    assert se["equity_share"] == round((1000 + 4000 * 1.0) / total, 4) == 1.0
    assert se["missing_data"] == []
    assert not any(f["code"] == "SECTOR_LOOKTHROUGH_PARTIAL" for f in out["flags"])


def test_summary_sector_exposure_proxied_equity_is_looked_through_not_unknown(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 1000.0},
            {"symbol": "SPYM", "units": 1, "price": 4000.0},
        ]}],
        "prices": {"AAPL": {"price": 1000.0}, "SPYM": {"price": 4000.0}},
        "sectors": {"AAPL": "Technology"},  # SPYM has no entry: Yahoo could not give it a sector
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY", "sector": "Technology"},
            # SPYM: Yahoo calls it a plain EQUITY with no sector and funds_data raises "No Fund
            # data found" for it; snapshot.py already proxied it to VOO and copied VOO's own
            # fund_sectors/fund_asset_classes here
            "SPYM": {"quote_type": "EQUITY", "sector": None, "name": "State Street SPDR Portfolio S&P 500 ETF",
                     "fund_sectors": {"technology": 0.30, "financial_services": 0.70},
                     "fund_asset_classes": {"stockPosition": 1.0}, "proxy": "VOO"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    # total_value = 1000 (AAPL) + 4000 (SPYM) = 5000
    total = 5000.0
    assert se["looked_through"] == ["SPYM (via VOO)"]
    tech = se["sectors"]["Technology"]
    assert tech["direct"] == round(1000 / total, 4) == 0.2
    assert tech["via_funds"] == round(4000 * 1.0 * 0.30 / total, 4) == 0.24
    fin = se["sectors"]["Financial Services"]
    assert fin["via_funds"] == round(4000 * 1.0 * 0.70 / total, 4) == 0.56
    assert se["not_sectorized"]["unknown_stocks"] == 0.0  # SPYM did NOT land here
    assert se["missing_data"] == []
    assert not any(f["code"] == "SECTOR_LOOKTHROUGH_PARTIAL" for f in out["flags"])
    # the legacy sector_weights view is stock-only: SPYM (looked through via a proxy) is left out
    # of it entirely rather than falling into "Unknown" -- only AAPL remains, under its own
    # sector; its weight (1000/5000) is still against the whole market value, SPYM included
    assert out["sector_weights"] == {"Technology": 0.2}
    assert not any(f["code"] == "MISSING_SECTOR" and "SPYM" in f["message"] for f in out["flags"])


def test_summary_sector_exposure_survives_when_every_holding_is_proxied(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "QBN5", "units": 1, "price": 6000.0},
            {"symbol": "QBMZ", "units": 1, "price": 4000.0},
        ]}],
        "prices": {"QBN5": {"price": 6000.0}, "QBMZ": {"price": 4000.0}},
        "asset_info": {
            # a 401(k)-only book: both institutional share classes have no quote_type of their
            # own -- the ONLY thing that makes them sectorizable is the borrowed proxy data --
            # so the old has_any_quote_type gate would have nulled sector_exposure entirely
            "QBN5": {"quote_type": None, "name": "VANG INST 500 IDX TR",
                     "fund_sectors": {"technology": 1.0}, "fund_asset_classes": {"stockPosition": 1.0}, "proxy": "VOO"},
            "QBMZ": {"quote_type": None, "name": "VG IS TOT BD MKT IDX",
                     "fund_sectors": {}, "fund_asset_classes": {"bondPosition": 0.98}, "proxy": "BND"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    assert se is not None
    # total_value = 6000 (QBN5) + 4000 (QBMZ) = 10000
    total = 10000.0
    assert se["looked_through"] == ["QBN5 (via VOO)"]  # QBMZ's proxy (BND) has empty sectors: not "looked through"
    assert se["sectors"]["Technology"]["via_funds"] == round(6000 / total, 4) == 0.6
    assert se["not_sectorized"]["bonds_and_cash"] == round(4000 / total, 4) == 0.4  # QBMZ: bondPosition >= 0.5
    assert se["equity_share"] == round(6000 / total, 4) == 0.6


def test_summary_sector_exposure_normalizes_fund_fractions_off_by_a_little(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "VWO", "units": 1, "price": 1000.0},
        ]}],
        "prices": {"VWO": {"price": 1000.0}},
        "asset_info": {
            # Yahoo's own fractions occasionally drift from 1.0 (VWO's has summed to
            # 1.0001); here deliberately 0.99 to exercise the normalization path
            "VWO": {"quote_type": "ETF", "name": "Vanguard Emerging Markets ETF",
                    "fund_sectors": {"technology": 0.60, "financial_services": 0.39},
                    "fund_asset_classes": {"stockPosition": 1.0}},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    # normalized (0.60/0.99, 0.39/0.99, summing to exactly 1.0) rather than left at 0.99: the two
    # sectors' weights still add up to the whole position, with nothing left over
    tech = se["sectors"]["Technology"]["weight"]
    fin = se["sectors"]["Financial Services"]["weight"]
    assert round(tech + fin, 4) == 1.0
    assert se["not_sectorized"]["bonds_and_cash"] == 0.0
    assert se["equity_share"] == 1.0


def test_summary_sector_exposure_in_band_negligible_drift_is_never_partial(capsys, monkeypatch) -> None:
    """Regression: fractions summing to 0.9999 -- in-band, but too close to
    1.0 to trigger the rescale (diff 0.0001 is not > 0.001) -- must not be treated as a
    partial fund. An earlier version wrongly used the un-rescaled 0.9999 as "attributed_frac" in that
    case, flagging a materially-complete fund as missing 0.01% of its equity."""
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "FXAIX", "units": 1, "price": 1000.0},
        ]}],
        "prices": {"FXAIX": {"price": 1000.0}},
        "asset_info": {
            "FXAIX": {"quote_type": "MUTUALFUND", "name": "Fidelity 500 Index Fund",
                      "fund_sectors": {"technology": 0.60, "financial_services": 0.3999},
                      "fund_asset_classes": {"stockPosition": 1.0}},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    assert round(sum(v["weight"] for v in se["sectors"].values()), 4) == 1.0
    assert se["equity_share"] == 1.0
    assert se["not_sectorized"]["funds_without_data"] == 0.0
    assert se["missing_data"] == []
    assert se["looked_through"] == ["FXAIX"]
    assert not any(f["code"] == "SECTOR_LOOKTHROUGH_PARTIAL" for f in out["flags"])


def test_summary_sector_exposure_does_not_normalize_a_genuinely_partial_sector_set(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "VTI", "units": 1, "price": 1000.0},
        ]}],
        "prices": {"VTI": {"price": 1000.0}},
        "asset_info": {
            # a genuinely partial sector set (only 2 of VTI's ~11 real sectors, summing to 0.40)
            # is outside the [0.9, 1.1] normalization band -- real missing data, left as reported
            "VTI": {"quote_type": "ETF", "name": "Vanguard Total Stock Market ETF",
                    "fund_sectors": {"technology": 0.30, "healthcare": 0.10},
                    "fund_asset_classes": {"stockPosition": 0.99}},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    se = out["sector_exposure"]
    # NOT rescaled: technology = 1000 * 0.99 * 0.30 = 297.0, healthcare = 1000 * 0.99 * 0.10 = 99.0
    assert se["sectors"]["Technology"]["via_funds"] == round(297.0 / 1000, 4) == 0.297
    assert se["sectors"]["Healthcare"]["via_funds"] == round(99.0 / 1000, 4) == 0.099
    sector_total = se["sectors"]["Technology"]["via_funds"] + se["sectors"]["Healthcare"]["via_funds"]
    # equity_share holds the identity by construction: it counts only the ATTRIBUTED equity share
    # (1000 * 0.99 * 0.40 = 396), not VTI's whole 0.99 equity_frac, so it exactly equals the sum
    # of the sector weights above rather than overcounting by the ungoverned residual.
    assert se["equity_share"] == round(sector_total, 4) == 0.396
    # the unattributed slice (1000 * 0.99 * (1 - 0.40) = 594, real Yahoo data VTI just didn't
    # itemize by sector) is not lost: it lands in funds_without_data -- but VTI itself is named
    # only in the flag's "partial: ..." clause, never in missing_data, since it WAS looked
    # through (missing_data is reserved for holdings with no sector data at all)
    assert se["not_sectorized"]["funds_without_data"] == round(594.0 / 1000, 4) == 0.594
    assert se["looked_through"] == ["VTI"]
    assert se["missing_data"] == []  # disjoint from looked_through: a partial fund never lands here
    assert set(se["looked_through"]).isdisjoint(se["missing_data"])
    total_frac = sector_total + sum(se["not_sectorized"].values())
    assert abs(total_frac - 1.0) < 0.001
    flag = next(f for f in out["flags"] if f["code"] == "SECTOR_LOOKTHROUGH_PARTIAL")
    assert "partial: VTI (60.0% of its equity unattributed)" in flag["message"]
    assert "no sector data" not in flag["message"]  # no true missing_data in this fixture


def test_summary_sector_exposure_null_when_proxy_data_is_null(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "QBN5", "units": 1, "price": 6000.0},
        ]}],
        "prices": {"QBN5": {"price": 6000.0}},
        "asset_info": {
            # "proxy" is set, but the proxy fetch itself produced nothing usable: fund_sectors is
            # still null. A bare "proxy" marker must not count as sectorizable on its own.
            "QBN5": {"quote_type": None, "name": "VANG INST 500 IDX TR",
                     "fund_sectors": None, "fund_asset_classes": None, "proxy": "VOO"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    assert out["sector_exposure"] is None


def test_summary_missing_sector_names_a_proxied_position_whose_proxy_data_is_null(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 1000.0},
            {"symbol": "SPYM", "units": 1, "price": 4000.0},
        ]}],
        "prices": {"AAPL": {"price": 1000.0}, "SPYM": {"price": 4000.0}},
        "sectors": {"AAPL": "Technology"},
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY", "sector": "Technology"},
            # SPYM: quote type EQUITY, no sector, "proxy" set but the proxy fetch itself came
            # back with nothing usable. MISSING_SECTOR keys on fund_sectors only (narrow), so it
            # must still be named -- but _is_looked_through_as_fund keys on fund_sectors OR a
            # bare proxy marker (broad, a name match is already good evidence it's a fund), so it
            # is excluded from single_stock/sector_weights/asset_classes's "stock" bucket anyway.
            "SPYM": {"quote_type": "EQUITY", "sector": None, "name": "State Street SPDR Portfolio S&P 500 ETF",
                     "fund_sectors": None, "fund_asset_classes": None, "proxy": "VOO"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    flag = next((f for f in out["flags"] if f["code"] == "MISSING_SECTOR"), None)
    assert flag is not None and flag["message"] == "no sector for: SPYM"
    # yet it is not a single stock, and asset_classes calls it a "fund" -- the bare proxy marker
    # is enough evidence, even with no real fund_sectors data behind it
    single = out["concentration"]["single_stock"]
    assert single["count"] == 1 and single["largest"]["symbol"] == "AAPL"
    assert out["asset_classes"]["fund"]["count"] == 1
    assert out["asset_classes"]["stock"]["count"] == 1
    assert "Unknown" not in out["sector_weights"]  # excluded from sector_weights too


def test_summary_missing_sector_names_only_single_stocks(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 1000.0},  # EQUITY, no sector: real gap
            {"symbol": "FXAIX", "units": 1, "price": 2000.0},  # MUTUALFUND, no sector: not a stock
            {"symbol": "SPAXX", "units": 1, "price": 500.0},  # MONEYMARKET, no sector: cash-like
        ]}],
        "prices": {"AAPL": {"price": 1000.0}, "FXAIX": {"price": 2000.0}, "SPAXX": {"price": 500.0}},
        "sectors": {},  # Yahoo gave none of them a sector, a common real-world shape
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY"},
            "FXAIX": {"quote_type": "MUTUALFUND", "name": "Fidelity 500 Index Fund"},
            "SPAXX": {"quote_type": "MONEYMARKET", "name": "Government Money Market"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    # sector_weights is untouched: all three still land in the Unknown bucket
    assert out["sector_weights"]["Unknown"] == 1.0
    flag = next((f for f in out["flags"] if f["code"] == "MISSING_SECTOR"), None)
    assert flag is not None and flag["message"] == "no sector for: AAPL"


def test_summary_a_looked_through_fund_is_never_a_single_stock(capsys, monkeypatch) -> None:
    import io
    import json
    import sys

    payload = {
        "accounts": [{"account_id": "a", "cash": 0.0, "positions": [
            {"symbol": "AAPL", "units": 1, "price": 1000.0},
            {"symbol": "MSFT", "units": 1, "price": 500.0},
            # SPYM: Yahoo calls it EQUITY (like a stock) but it's an S&P 500 ETF looked through
            # via a proxy; worth more than either real stock, it would otherwise dominate
            # single_stock and be reported as the largest single stock
            {"symbol": "SPYM", "units": 1, "price": 5000.0},
        ]}],
        "prices": {"AAPL": {"price": 1000.0}, "MSFT": {"price": 500.0}, "SPYM": {"price": 5000.0}},
        "sectors": {"AAPL": "Technology", "MSFT": "Technology"},
        "quote_types": {"AAPL": "EQUITY", "MSFT": "EQUITY", "SPYM": "EQUITY"},
        "asset_info": {
            "AAPL": {"quote_type": "EQUITY", "sector": "Technology"},
            "MSFT": {"quote_type": "EQUITY", "sector": "Technology"},
            "SPYM": {"quote_type": "EQUITY", "sector": None, "name": "State Street SPDR Portfolio S&P 500 ETF",
                     "fund_sectors": {"technology": 0.30, "financial_services": 0.70},
                     "fund_asset_classes": {"stockPosition": 1.0}, "proxy": "VOO"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("portfolio-snapshot/scripts/summary.py").main()
    out = json.loads(capsys.readouterr().out)
    single = out["concentration"]["single_stock"]
    # total_value = 1000 + 500 + 5000 = 6500
    total = 6500.0
    assert single["count"] == 2  # AAPL and MSFT only -- SPYM excluded
    assert single["weight"] == round((1000 + 500) / total, 4)
    assert single["largest"]["symbol"] == "AAPL"  # not SPYM, despite SPYM being 5x AAPL's value
    assert single["largest"]["weight"] == round(1000 / total, 4)
    # the overall (not single-stock) largest_position may still call SPYM a "stock" -- unchanged
    assert out["concentration"]["largest_position"]["symbol"] == "SPYM"
    assert out["concentration"]["largest_position"]["asset_class"] == "stock"
    # sector_weights (stock-only) excludes SPYM entirely, not even under "Unknown"
    assert "Unknown" not in out["sector_weights"]
    assert out["sector_weights"]["Technology"] == round((1000 + 500) / total, 4)
    # asset_classes: SPYM counts as "fund" (looked through), not "stock", despite Yahoo's own EQUITY
    assert out["asset_classes"]["fund"]["count"] == 1
    assert out["asset_classes"]["stock"]["count"] == 2  # AAPL and MSFT only


def test_snapshot_looks_through_a_proxied_institutional_fund(monkeypatch, capsys) -> None:
    """snapshot.py itself: a no-quote-type position named like an institutional S&P 500 share
    class triggers a market.sectors(["VOO"]) call after the main sector lookup, and the result
    carries fund_sectors/fund_asset_classes/proxy through to sector_exposure."""
    from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
    from second_opinion import client
    from second_opinion.brokers import router

    positions = {
        "acc-1": [
            {"symbol": {"symbol": {"symbol": "AAPL", "description": "Apple Inc."}}, "units": 1, "price": 1000.0},
            # a 401(k) institutional S&P 500 share class: the broker reports it by its
            # institutional ticker and description; Yahoo has no quote type for it at all
            {"symbol": {"symbol": {"symbol": "QBN5", "description": "VANG INST 500 IDX TR"}}, "units": 1, "price": 4000.0},
        ],
        "acc-2": [],
    }
    balances = {
        "acc-1": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}],
        "acc-2": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}],
    }
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: positions[account_id],
        get_user_account_balance=lambda account_id: balances[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "c")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "k")

    calls: list[list[str]] = []

    def sectors(symbols, cache_path=None):
        calls.append(list(symbols))
        out = {}
        for s in symbols:
            su = s.upper()
            base = {"sector": None, "name": None, "quote_type": None, "category": None, "country": None,
                    "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None}
            if su == "AAPL":
                out[su] = {**base, "sector": "Technology", "name": "Apple Inc.", "quote_type": "EQUITY", "country": "United States"}
            elif su == "VOO":
                out[su] = {**base, "sector": "ETF", "name": "Vanguard S&P 500 ETF", "quote_type": "ETF",
                           "fund_sectors": {"technology": 0.30, "financial_services": 0.70},
                           "fund_asset_classes": {"stockPosition": 1.0}, "fund_fetched": "2026-09-14"}
            else:
                out[su] = base  # QBN5: Yahoo has no info for it at all
        return out

    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {})
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    monkeypatch.setattr(market, "sectors", sectors)

    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-news"], capsys)
    assert rc == 0, out
    assert calls[0] == ["AAPL", "QBN5"]  # the main, batched sector lookup
    assert calls[1] == ["VOO"]  # the proxy fetch triggered by QBN5's name, after the main lookup
    se = out["sector_exposure"]
    assert se is not None and se["looked_through"] == ["QBN5 (via VOO)"]
    assert out["profiles"]["QBN5"]["name"] == "VANG INST 500 IDX TR"  # the broker description, unproxied


def test_snapshot_proxies_a_sector_less_equity_etf_yahoo_cannot_describe(monkeypatch, capsys) -> None:
    """snapshot.py itself: a plain EQUITY position (Yahoo's own quote type for it) with no
    sector and no fund_sectors of its own -- SPYM's real shape, whose funds_data raises "No Fund
    data found" -- still triggers a market.sectors(["VOO"]) proxy fetch by name."""
    from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
    from second_opinion import client
    from second_opinion.brokers import router

    positions = {
        "acc-1": [
            {"symbol": {"symbol": {"symbol": "AAPL", "description": "Apple Inc."}}, "units": 1, "price": 1000.0},
            {"symbol": {"symbol": {"symbol": "SPYM", "description": "SPDR Portfolio S&P 500 ETF"}}, "units": 1, "price": 4000.0},
        ],
        "acc-2": [],
    }
    balances = {
        "acc-1": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}],
        "acc-2": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}],
    }
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: positions[account_id],
        get_user_account_balance=lambda account_id: balances[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "c")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "k")

    calls: list[list[str]] = []

    def sectors(symbols, cache_path=None):
        calls.append(list(symbols))
        out = {}
        for s in symbols:
            su = s.upper()
            base = {"sector": None, "name": None, "quote_type": None, "category": None, "country": None,
                    "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None}
            if su == "AAPL":
                out[su] = {**base, "sector": "Technology", "name": "Apple Inc.", "quote_type": "EQUITY", "country": "United States"}
            elif su == "VOO":
                out[su] = {**base, "sector": "ETF", "name": "Vanguard S&P 500 ETF", "quote_type": "ETF",
                           "fund_sectors": {"technology": 0.30, "financial_services": 0.70},
                           "fund_asset_classes": {"stockPosition": 1.0}, "fund_fetched": "2026-09-14"}
            else:
                # SPYM: Yahoo calls it EQUITY, gives it no sector, and its own funds_data raises
                # "No Fund data found" -- market.sectors() already tried and failed to relabel it
                out[su] = {**base, "quote_type": "EQUITY", "name": "State Street SPDR Portfolio S&P 500 ETF",
                           "country": "United States", "fund_fetched": "2026-09-14"}
        return out

    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {})
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    monkeypatch.setattr(market, "sectors", sectors)

    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-news"], capsys)
    assert rc == 0, out
    assert calls[0] == ["AAPL", "SPYM"]  # the main, batched sector lookup
    assert calls[1] == ["VOO"]  # the proxy fetch triggered by SPYM's name, after the main lookup
    se = out["sector_exposure"]
    assert se is not None and se["looked_through"] == ["SPYM (via VOO)"]
    assert se["not_sectorized"]["unknown_stocks"] == 0.0
    assert not any(f["code"] == "MISSING_SECTOR" and "SPYM" in f["message"] for f in out["flags"])


def test_snapshot_proxy_fetch_failure_keeps_base_sector_data_and_flags(monkeypatch, capsys) -> None:
    """A failure in the proxy-only market.sectors() call must not wipe out the base sector lookup
    that already succeeded -- it degrades additively, with its own flag."""
    from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
    from second_opinion import client
    from second_opinion.brokers import router

    positions = {
        "acc-1": [
            {"symbol": {"symbol": {"symbol": "AAPL", "description": "Apple Inc."}}, "units": 1, "price": 1000.0},
            {"symbol": {"symbol": {"symbol": "QBN5", "description": "VANG INST 500 IDX TR"}}, "units": 1, "price": 4000.0},
        ],
        "acc-2": [],
    }
    balances = {
        "acc-1": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}],
        "acc-2": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}],
    }
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS,
        list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        get_user_account_positions=lambda account_id: positions[account_id],
        get_user_account_balance=lambda account_id: balances[account_id],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "c")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "k")

    calls: list[list[str]] = []

    def sectors(symbols, cache_path=None):
        calls.append(list(symbols))
        if symbols == ["VOO"]:
            raise RuntimeError("yahoo down")
        out = {}
        for s in symbols:
            su = s.upper()
            base = {"sector": None, "name": None, "quote_type": None, "category": None, "country": None,
                    "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None}
            if su == "AAPL":
                out[su] = {**base, "sector": "Technology", "name": "Apple Inc.", "quote_type": "EQUITY", "country": "United States"}
            else:
                out[su] = base  # QBN5: Yahoo has no info for it at all
        return out

    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {})
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    monkeypatch.setattr(market, "sectors", sectors)

    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-news"], capsys)
    assert rc == 0, out
    assert calls[0] == ["AAPL", "QBN5"]
    assert calls[1] == ["VOO"]  # the proxy-only call, which raised
    assert out["sources"]["sectors"] == "yahoo"  # the base lookup still succeeded
    assert out["profiles"]["AAPL"]["sector"] == "Technology"  # base sector data intact
    flag = next(f for f in out["flags"] if f["code"] == "PROXY_LOOKTHROUGH_UNAVAILABLE")
    assert "yahoo down" in flag["message"]


def test_snapshot_never_proxies_a_symbol_to_itself() -> None:
    mod = load_script("portfolio-snapshot/scripts/snapshot.py")
    # a real BND row that somehow came back from Yahoo with no quote type at all; its own name
    # would otherwise match the BND-mapped look-through pattern, proxying it to itself
    asset_info = {"BND": {"quote_type": None, "name": "Vanguard Total Bond Market ETF", "fund_sectors": None}}
    mod._apply_lookthrough_proxies(asset_info)  # noqa: SLF001 -- exercising the module's own helper
    assert "proxy" not in asset_info["BND"]
    assert asset_info["BND"]["fund_sectors"] is None


def test_snapshot_never_proxies_voo_to_itself_via_the_sp500_pattern() -> None:
    mod = load_script("portfolio-snapshot/scripts/snapshot.py")
    # VOO's own name ("Vanguard S&P 500 ETF") matches the new S&P 500 index-ETF pattern too; if it
    # somehow arrived here with no usable sector data of its own, it must never be proxied to itself
    asset_info = {"VOO": {"quote_type": None, "name": "Vanguard S&P 500 ETF", "fund_sectors": None}}
    mod._apply_lookthrough_proxies(asset_info)  # noqa: SLF001 -- exercising the module's own helper
    assert "proxy" not in asset_info["VOO"]
    assert asset_info["VOO"]["fund_sectors"] is None


def test_snapshot_carries_sampled_price_history_and_profiles(sdk, yahoo, capsys) -> None:
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-news"], capsys)
    assert rc == 0, out
    # the fixture history has 24 AAPL closes: every 5th plus the last -> indexes 0,5,10,15,20,23
    aapl = out["price_history"]["AAPL"]
    assert [h["date"] for h in aapl] == ["2026-08-01", "2026-08-06", "2026-08-11", "2026-08-16", "2026-08-21", "2026-08-24"]
    assert aapl[-1]["close"] == 114.0 and out["price_history"]["MSFT"] == [{"date": "2026-08-20", "close": 200.0}]
    prof = out["profiles"]["AAPL"]
    assert prof["summary"] == "Apple designs phones." and prof["website"] == "https://www.apple.com" and prof["bucket"] == "us_equity"
    assert out["profiles"]["MSFT"]["bucket"] == "bonds"


def test_snapshot_passes_fund_sector_look_through_into_sector_exposure(sdk, yahoo, monkeypatch, capsys) -> None:
    # market.sectors carries fund_sectors/fund_asset_classes on a real cache hit; snapshot.py must
    # pass them through asset_info to summary.py untouched, since it only spreads **v.
    def sectors_with_fund_data(symbols, cache_path=None):
        return {
            "AAPL": {"sector": "Technology", "name": None, "quote_type": "EQUITY", "category": None, "country": "United States",
                     "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None},
            "MSFT": {"sector": "Technology", "name": None, "quote_type": "ETF", "category": None, "country": None,
                     "summary": None, "website": None, "fund_sectors": {"technology": 0.5}, "fund_asset_classes": {"stockPosition": 1.0}, "fund_fetched": "2026-09-01"},
        }

    monkeypatch.setattr(market, "sectors", sectors_with_fund_data)
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-news"], capsys)
    assert rc == 0, out
    se = out["sector_exposure"]
    assert se is not None and "MSFT" in se["looked_through"]
    assert se["sectors"]["Technology"]["funds"] == [{"symbol": "MSFT", "weight": se["sectors"]["Technology"]["via_funds"]}]


def test_snapshot_looks_through_an_equity_mislabeled_fund_from_market_sectors(sdk, yahoo, monkeypatch, capsys) -> None:
    # market.sectors() already corrects a Yahoo-mislabeled ETF (quoteType EQUITY, no sector, but a
    # fund name and real funds_data) to quote_type "ETF" with fund_sectors -- snapshot.py must not
    # need any change of its own to pass that through, since it already just spreads **v.
    def sectors_relabeled(symbols, cache_path=None):
        return {
            "AAPL": {"sector": "ETF", "name": "State Street SPDR Portfolio S&P 500 ETF", "quote_type": "ETF",
                     "category": None, "country": None, "summary": None, "website": None,
                     "fund_sectors": {"technology": 0.30, "financial_services": 0.70},
                     "fund_asset_classes": {"stockPosition": 0.99}, "fund_fetched": "2026-09-14"},
            "MSFT": {"sector": "Technology", "name": None, "quote_type": "EQUITY", "category": None, "country": "United States",
                     "summary": None, "website": None, "fund_sectors": None, "fund_asset_classes": None, "fund_fetched": None},
        }

    monkeypatch.setattr(market, "sectors", sectors_relabeled)
    rc, out = run_json(load_script("portfolio-snapshot/scripts/snapshot.py"), ["--no-news"], capsys)
    assert rc == 0, out
    se = out["sector_exposure"]
    assert se is not None and "AAPL" in se["looked_through"]
    assert not any(f["code"] == "MISSING_SECTOR" for f in out["flags"])


def test_render_has_explain_box_terms_and_detail_panel(tmp_path, capsys) -> None:
    import json

    snapshot = {"as_of": "2026-09-14T18:28:32+00:00", "sources": {}, "totals": {"total_value": 1.0, "cash": 0.0}, "accounts": [], "positions": [],
                "top_holdings": [], "concentration": {}, "sector_weights": {}, "movers": {"up": [], "down": []}, "flags": [],
                "price_history": {"AAA": [{"date": "2026-01-02", "close": 9.0}]}, "profiles": {"AAA": {"summary": "Makes widgets.", "bucket": "us_equity"}}}
    src = tmp_path / "s.json"; src.write_text(json.dumps(snapshot)); out = tmp_path / "p.html"
    rc, _ = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    html = out.read_text()
    assert rc == 0 and "FA.explain(" in html and "FA.term(" in html and "FA.modal(" in html and "window.GLOSSARY" in html
    assert "Makes widgets." in html and "One-year price history" in html


def test_render_shows_headlines_and_coverage(tmp_path, capsys) -> None:
    import json

    snapshot = {
        "as_of": "2026-09-14T18:28:32+00:00", "sources": {"holdings": "mixed", "quotes": "mixed"},
        "totals": {"total_value": 149.2, "cash": 49.2, "cash_pct": 0.33, "day_change": 1.0, "day_change_pct": 0.0067, "day_change_coverage": 1.0, "unrealized_pnl": 10.0, "no_cost_basis_pct": 0.0},
        "accounts": [], "positions": [], "top_holdings": [], "concentration": {"hhi": None, "top_5_concentration": 0, "position_count": 0},
        "sector_weights": {}, "movers": {"up": [], "down": []}, "events": None, "comparison": None, "flags": [],
        "headlines": [{"key": "watchlist:price_below:PEP:2026-09-14", "code": "price_below", "skill": "watchlist", "severity": "alert", "symbol": "PEP",
                       "title": "PEP 66.10 is below 70.25", "detail": "rule set 2026-09-01", "as_of": "2026-09-14", "status": "new", "ask": "What on my watchlist moved?",
                       "url": "https://finance.yahoo.com/quote/PEP", "answer": "PEP dropped below your 70.25 alert.", "why": "It fell 3.3% after a downgrade."},
                      {"key": "market-analysis:DAY:-:2026-09-14", "code": "DAY", "skill": "market-analysis", "severity": "info", "symbol": None,
                       "title": "S&P 500 +0.4% <b>", "detail": "", "as_of": "2026-09-14", "status": "still", "ask": "How is the market positioned this week?"}],
        "coverage": [{"skill": "watchlist", "script": "scripts/watchlist.py", "status": "ok", "reason": "", "hint": "", "seconds": 2.1, "headlines": 1},
                     {"skill": "rebalancing", "script": "scripts/plan.py", "status": "skipped", "reason": "no targets.json", "hint": "save targets with the rebalancing skill", "seconds": 0.0, "headlines": 0}],
        "brief_as_of": "2026-09-14T18:29:10+00:00", "brief_seconds": 38.4,
    }
    src = tmp_path / "snap.json"
    src.write_text(json.dumps(snapshot))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res["headlines"] == 2
    html = out.read_text()
    assert 'id="headlines-card"' in html and 'id="coverage"' in html and "sev-alert" in html
    assert 'id="hl-totals"' in html and 'id="hl-more"' in html
    assert "const HL_TOP = 3" in html
    assert 'class="more" hidden' in html and "Show all " in html
    assert "[hidden]{display:none!important}" in html
    assert "F.esc(h.title)" in html and "F.esc(c.reason || '')" in html  # every headline and coverage field is escaped when built
    assert '"no targets.json"' in html and "headline" in html.lower()
    assert 'class="hl-link"' in html and "stopPropagation" in html
    assert 'class="why"' in html and 'class="answer"' in html
    assert "!h.answer && h.ask" in html  # Ask: line only shown when there is no answer
    assert "closest('a')" in html  # Enter on the headline link does not also toggle the row
    assert "${newPill(h)}${F.esc(h.title)}" in html and "pill-lead" in html  # the new marker leads the title


def test_render_puts_the_account_column_beside_symbol(tmp_path, capsys) -> None:
    import json

    snapshot = {"as_of": "2026-09-14T18:28:32+00:00", "sources": {}, "totals": {"total_value": 1.0}, "accounts": [], "positions": [], "top_holdings": [],
                "concentration": {}, "sector_weights": {}, "movers": {"up": [], "down": []}, "events": None, "comparison": None, "flags": []}
    src = tmp_path / "snap.json"
    src.write_text(json.dumps(snapshot))
    out = tmp_path / "page.html"
    rc, _ = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0
    html = out.read_text()
    sym, acct, units = html.index("{key: 'symbol'"), html.index("{key: 'accounts_txt', label: 'Account'"), html.index("{key: 'units'")
    assert sym < acct < units


def test_render_cash_tile_shows_cash_like_holdings(tmp_path, capsys) -> None:
    import json

    snapshot = {
        "as_of": "2026-09-14T18:28:32+00:00",
        "sources": {},
        "totals": {"total_value": 100.0, "cash": 49.2, "cash_pct": 0.49, "cash_like": 59.2, "cash_like_pct": 0.59},
        "accounts": [], "positions": [], "top_holdings": [], "concentration": {}, "sector_weights": {},
        "movers": {"up": [], "down": []}, "events": None, "comparison": None, "flags": [],
    }
    src = tmp_path / "snap.json"
    src.write_text(json.dumps(snapshot))
    out = tmp_path / "page.html"
    rc, _ = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0
    html = out.read_text()
    # tile value falls back to totals.cash when cash_like is absent, and the sub-line carries
    # the share of total plus the settled/money-market breakdown
    assert "F.isNum(T.cash_like) ? T.cash_like : T.cash" in html
    assert "const cashPct = F.isNum(T.cash_like_pct) ? T.cash_like_pct : T.cash_pct;" in html
    assert "const cashParts = [`${F.pct(cashPct)} of total`, `settled ${F.money(T.cash)}`];" in html
    assert "cashParts.push(`money-market funds ${F.money(mmVal)}`)" in html
    assert "F.money(cashLikeVal)" in html
    # accounts bar tooltip notes a money-market fund held as cash when the account was adjusted
    assert "F.isNum(a.cash_adjusted_for_money_market) && a.cash_adjusted_for_money_market > 0" in html
    assert "held as a money-market fund" in html


def test_render_sector_exposure_subtitle_and_fallback(tmp_path, capsys) -> None:
    import json

    base = {"as_of": "2026-09-14T18:28:32+00:00", "sources": {}, "accounts": [], "positions": [], "top_holdings": [],
            "concentration": {}, "movers": {"up": [], "down": []}, "events": None, "comparison": None, "flags": []}

    with_exposure = {
        **base,
        "totals": {"total_value": 4500.0},
        "sector_weights": {"Technology": 1.0},
        "sector_exposure": {
            "sectors": {"Technology": {"weight": 0.3556, "direct": 0.2222, "via_funds": 0.1333, "funds": [{"symbol": "VTI", "weight": 0.1333}, {"symbol": "QBN5 (via VOO)", "weight": 0.01}]}},
            "equity_share": 0.6622,
            "not_sectorized": {"bonds_and_cash": 0.3378, "funds_without_data": 0.03, "unknown_stocks": 0.0},
            "looked_through": ["QBN5 (via VOO)", "VTI"],
            "missing_data": ["XYZ"],
        },
    }
    src = tmp_path / "with.json"
    src.write_text(json.dumps(with_exposure))
    out = tmp_path / "with.html"
    rc, _ = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    html = out.read_text()
    assert rc == 0
    assert "const SE = D.sector_exposure;" in html
    assert "let sub = `Looks through ${looked.length} funds`" in html
    assert "(proxied > 0 ? ` (${proxied} via proxy)` : '')" in html
    assert "const proxied = looked.filter(s => s.indexOf(' (via ') !== -1).length;" in html
    assert "of the portfolio sectorized) · ${F.pct(NS.bonds_and_cash)} bonds and cash, not sectorized" in html
    assert "if (missing.length) sub += `, no data for ${missing.join(', ')}`;" in html
    assert "${F.pct(v.weight)} · ${F.pct(v.direct)} direct" in html

    without_exposure = {**base, "totals": {"total_value": 100.0}, "sector_weights": {"Tech": 1.0}}
    without_exposure.pop("sector_exposure", None)
    src2 = tmp_path / "without.json"
    src2.write_text(json.dumps(without_exposure))
    out2 = tmp_path / "without.html"
    rc2, _ = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src2), "--out", str(out2)], capsys)
    html2 = out2.read_text()
    assert rc2 == 0
    # both branches ship in the same page; the fallback text confirms the old stock-only rendering is still present
    assert "Single stocks only (${stockSyms.size} names" in html2
    assert "funds are not looked through." in html2


def test_render_without_headlines_hides_the_card(tmp_path, capsys) -> None:
    import json

    snapshot = {"as_of": "2026-09-14T18:28:32+00:00", "sources": {}, "totals": {"total_value": 1.0}, "accounts": [], "positions": [], "top_holdings": [],
                "concentration": {}, "sector_weights": {}, "movers": {"up": [], "down": []}, "events": None, "comparison": None, "flags": []}
    src = tmp_path / "snap.json"
    src.write_text(json.dumps(snapshot))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("portfolio-snapshot/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res["headlines"] == 0
    assert "if (Array.isArray(D.headlines))" in out.read_text()


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit("portfolio-snapshot/scripts/render.py", ["--in", str(PLUGIN_ROOT / "docs/samples/portfolio-brief.json")], tmp_path, capsys)
    assert_page_help(a)
