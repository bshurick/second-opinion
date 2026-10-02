from __future__ import annotations

import json

import pytest

from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import brokerage, client, market
from second_opinion.brokers import router
from page_dom import assert_page_help, render_and_audit, requires_chrome

IMPACT = {
    "trade": {"id": "trade-9", "account": "acc-1", "order_type": "Limit", "time_in_force": "Day", "action": "BUY", "units": 2, "price": 150.0},
    "trade_impacts": [{"account": "acc-1", "currency": "USD", "remaining_cash": 900.0, "estimated_commission": 1.0, "forex_fees": 0.0}],
}


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSdk(
        list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH],
        symbol_search_user_account=[{"id": "uid", "symbol": "AAPL"}], get_order_impact=IMPACT,
        place_order={"brokerage_order_id": "ord-1", "status": "PENDING"}, cancel_user_account_order={},
        get_user_account_orders=[{"status": "PENDING"}], get_activities=[{"id": 1}],
    )
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setattr(brokerage, "_manual_trade_form", lambda b: b)
    return fake


def test_preview_script(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/preview-order.py"), ["acc-1", "aapl", "buy", "2", "--type", "LIMIT", "--limit", "150"], capsys)
    assert rc == 0 and out["trade_id"] == "trade-9" and out["order_type"] == "LIMIT" and out["limit_price"] == 150.0
    assert not sdk.kwargs_for("place_order")


def test_preview_script_bad_args_exit_2(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/preview-order.py"), ["acc-1", "aapl", "buy", "two"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"


def test_preview_script_parses_fractional_quantity_and_snaptrade_refuses_it(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/preview-order.py"), ["acc-1", "aapl", "buy", "0.5"], capsys)
    assert rc == 2 and out["code"] == "FRACTIONAL_NOT_SUPPORTED" and not sdk.kwargs_for("get_order_impact")


def test_preview_script_whole_number_quantity_stays_an_int(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/preview-order.py"), ["acc-1", "aapl", "buy", "2.0"], capsys)
    assert rc == 0 and out["quantity"] == 2 and isinstance(out["quantity"], int)


def test_preview_script_rejects_non_positive_quantity(sdk, capsys) -> None:
    for q in ("0", "-1", "nan"):
        rc, out = run_json(load_script("trading/scripts/preview-order.py"), ["acc-1", "aapl", "buy", q], capsys)
        assert rc == 2 and out["code"] == "INVALID_INPUT", q


def test_place_without_confirm_previews_and_exits_3(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/place-order.py"), ["acc-1", "aapl", "buy", "2"], capsys)
    assert rc == 3 and out["code"] == "NOT_CONFIRMED" and out["preview"]["trade_id"] == "trade-9"
    assert not sdk.kwargs_for("place_order")


def test_place_with_confirm_places(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/place-order.py"), ["acc-1", "aapl", "buy", "2", "--confirm"], capsys)
    assert rc == 0 and out["order_id"] == "ord-1" and out["preview"]["trade_id"] == "trade-9"
    assert sdk.kwargs_for("place_order") == [{"trade_id": "trade-9"}]


def test_place_read_only_account_exit_2(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/place-order.py"), ["acc-2", "aapl", "buy", "2", "--confirm"], capsys)
    assert rc == 2 and out["code"] == "READ_ONLY_ACCOUNT" and not sdk.kwargs_for("place_order")


def test_cancel_requires_confirm(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/cancel-order.py"), ["acc-1", "ord-1"], capsys)
    assert rc == 3 and out["code"] == "NOT_CONFIRMED" and not sdk.kwargs_for("cancel_user_account_order")
    rc, out = run_json(load_script("trading/scripts/cancel-order.py"), ["acc-1", "ord-1", "--confirm"], capsys)
    assert rc == 0 and out["cancelled"] is True


def test_orders_and_transactions_scripts(sdk, capsys) -> None:
    rc, out = run_json(load_script("trading/scripts/orders.py"), ["acc-1", "--status", "pending"], capsys)
    assert rc == 0 and out == {"account_id": "acc-1", "orders": [{"status": "PENDING", "order_id": None, "symbol": None, "side": None, "quantity": None}]}
    rc, out = run_json(load_script("trading/scripts/transactions.py"), ["acc-1", "--start", "2026-01-01"], capsys)
    assert rc == 0 and out["transactions"] == [{"id": 1}]


def test_transactions_rejects_a_malformed_date_before_calling_the_broker(sdk, capsys) -> None:
    for args in (["acc-1", "--start", "01/01/2026"], ["acc-1", "--end", "yesterday"]):
        rc, out = run_json(load_script("trading/scripts/transactions.py"), args, capsys)
        assert rc == 2 and out["code"] == "INVALID_INPUT"
    assert sdk.kwargs_for("get_activities") == []


def test_history_script(monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setattr(market, "price_history", lambda symbol, **kw: calls.append((symbol, kw)) or {"symbol": symbol, "prices": []})
    rc, out = run_json(load_script("trading/scripts/history.py"), ["aapl", "--period", "2y"], capsys)
    assert rc == 0 and calls == [("AAPL", {"period": "2y", "start": None, "end": None, "interval": "1d"})]
    rc, _ = run_json(load_script("trading/scripts/history.py"), ["aapl", "--start", "2026-01-01", "--end", "2026-02-01"], capsys)
    assert calls[-1] == ("AAPL", {"period": "1y", "start": "2026-01-01", "end": "2026-02-01", "interval": "1d"})


def _dates(n: int) -> list[str]:
    import datetime

    start = datetime.date(2024, 1, 1)
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _run_signals_stdin(payload: dict, monkeypatch, capsys) -> dict:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    load_script("trading/scripts/signals.py").main()
    return json.loads(capsys.readouterr().out)


def test_signals_script_closes_only_adds_no_new_keys(monkeypatch, capsys) -> None:
    dates = _dates(10)
    payload = {"prices": [{"date": d, "close": 100.0 + i} for i, d in enumerate(dates)]}
    out = _run_signals_stdin(payload, monkeypatch, capsys)
    assert "atr_14_pct" not in out and "relative" not in out and "pivots" not in out


def test_signals_script_wires_high_low_volume(monkeypatch, capsys) -> None:
    n = 70
    dates = _dates(n)
    closes = [100.0 + i for i in range(n)]
    payload = {
        "prices": [
            {"date": d, "close": c, "high": c + 1, "low": c - 1, "volume": 1000.0 + i}
            for i, (d, c) in enumerate(zip(dates, closes))
        ]
    }
    out = _run_signals_stdin(payload, monkeypatch, capsys)
    assert out["atr_14_pct"] is not None
    assert out["gap_stats"] is not None
    assert out["relative_volume_20_252"] is not None
    assert out["avg_dollar_volume_20"] is not None


def test_signals_script_wires_benchmark_and_pivots(monkeypatch, capsys) -> None:
    n = 260
    dates = _dates(n)
    payload = {
        "prices": [{"date": d, "close": 100.0 + 0.5 * i} for i, d in enumerate(dates)],
        "benchmark": [{"date": d, "close": 200.0 + 0.25 * i} for i, d in enumerate(dates)],
        "pivots": 3,
    }
    out = _run_signals_stdin(payload, monkeypatch, capsys)
    assert set(out["relative"].keys()) == {"1m", "3m", "12m", "momentum_12_1", "relative_12_1"}
    assert out["pivots"]["k"] == 3
    assert "highs" in out["pivots"] and "lows" in out["pivots"]


def test_signals_script_invalid_pivots_exit_2(monkeypatch, capsys) -> None:
    import io
    import sys

    dates = _dates(10)
    payload = {"prices": [{"date": d, "close": 100.0 + i} for i, d in enumerate(dates)], "pivots": 1}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    mod = load_script("trading/scripts/signals.py")
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    assert "error" in json.loads(capsys.readouterr().out)


def test_preview_passes_through_etrade_reauth(capsys, monkeypatch) -> None:
    from second_opinion.brokers import router
    from second_opinion.errors import ConfigError

    class Reauth:
        def preview_order(self, spec):
            raise ConfigError("E*Trade authorization required", code="ETRADE_REAUTH", url="https://us.etrade.com/x", hint="h", sandbox=False)

    monkeypatch.setattr(router, "load", lambda settings=None: Reauth())
    rc, out = run_json(load_script("trading/scripts/preview-order.py"), ["KEY1", "AAPL", "BUY", "1"], capsys)
    assert rc == 4 and out["code"] == "ETRADE_REAUTH" and out["url"] == "https://us.etrade.com/x"


def test_orders_rows_are_flattened_for_the_caller(sdk, capsys) -> None:
    sdk.bodies["get_user_account_orders"] = [
        {
            "brokerage_order_id": "ord-7", "status": "PENDING", "action": "BUY", "total_quantity": 5.0, "filled_quantity": 0.0,
            "universal_symbol": {"id": "uid", "symbol": "AAPL", "raw_symbol": "AAPL"}, "limit_price": 150.0, "broker": "snaptrade",
        },
        {"brokerage_order_id": "ord-8", "status": "EXECUTED", "action": "SELL", "total_quantity": 2, "universal_symbol": None, "symbol": "MSFT"},
    ]
    rc, out = run_json(load_script("trading/scripts/orders.py"), ["acc-1"], capsys)
    assert rc == 0, out
    first, second = out["orders"]
    assert first["order_id"] == "ord-7" and first["symbol"] == "AAPL" and first["side"] == "BUY" and first["quantity"] == 5.0
    # every adapter key survives next to the aliases
    assert first["brokerage_order_id"] == "ord-7" and first["universal_symbol"]["symbol"] == "AAPL" and first["action"] == "BUY" and first["total_quantity"] == 5.0 and first["limit_price"] == 150.0 and first["broker"] == "snaptrade"
    # a value the adapter already set under an alias key is kept
    assert second == {"brokerage_order_id": "ord-8", "status": "EXECUTED", "action": "SELL", "total_quantity": 2, "universal_symbol": None, "symbol": "MSFT", "order_id": "ord-8", "side": "SELL", "quantity": 2}


# ---------------------------------------------------------------------------
# signals.py "series" input and render.py: the interactive page
# ---------------------------------------------------------------------------


def _history(n: int, symbol: str = "ACME") -> dict:
    dates = _dates(n)
    rows = [{"date": d, "open": 100.0 + i, "high": 101.5 + i, "low": 99.0 + i, "close": 100.0 + i, "volume": 1000.0 + i} for i, d in enumerate(dates)]
    return {"symbol": symbol, "period": "1y", "interval": "1d", "count": n, "prices": rows}


def test_signals_series_is_opt_in_and_matches_the_scalar_smas(monkeypatch, capsys) -> None:
    hist = _history(260)
    out = _run_signals_stdin({"prices": hist["prices"]}, monkeypatch, capsys)
    assert "series" not in out
    out = _run_signals_stdin({"prices": hist["prices"], "series": False}, monkeypatch, capsys)
    assert "series" not in out
    out = _run_signals_stdin({"prices": hist["prices"], "series": True}, monkeypatch, capsys)
    s50, s200 = out["series"]["sma_50"], out["series"]["sma_200"]
    assert len(s50) == 260 - 49 and len(s200) == 260 - 199
    assert s50[0] == {"date": hist["prices"][49]["date"], "value": 124.5} and s50[-1]["value"] == out["sma_50"]
    assert s200[0]["date"] == hist["prices"][199]["date"] and s200[-1]["value"] == out["sma_200"]
    assert [p["date"] for p in s50] == [r["date"] for r in hist["prices"][49:]]  # oldest first, one row per close
    # too short for the window: an empty list, never extrapolated
    out = _run_signals_stdin({"prices": hist["prices"][:30], "series": True}, monkeypatch, capsys)
    assert out["series"] == {"sma_50": [], "sma_200": []}


def test_signals_series_must_be_boolean(monkeypatch, capsys) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prices": _history(10)["prices"], "series": "yes"})))
    with pytest.raises(SystemExit) as exc:
        load_script("trading/scripts/signals.py").main()
    assert exc.value.code == 2 and "series must be a boolean" in json.loads(capsys.readouterr().out)["error"]


def test_render_builds_a_self_contained_page(tmp_path, capsys, monkeypatch) -> None:
    hist = _history(260)
    hist["symbol"] = "AC<ME"
    signals = _run_signals_stdin({"prices": hist["prices"], "benchmark": [{"date": r["date"], "close": 50.0 + i * 0.1} for i, r in enumerate(hist["prices"])], "pivots": 3, "series": True}, monkeypatch, capsys)
    assert "relative" in signals and "pivots" in signals and signals["series"]["sma_200"]
    sig, prices, out = tmp_path / "signals.json", tmp_path / "history.json", tmp_path / "page.html"
    sig.write_text(json.dumps(signals)), prices.write_text(json.dumps(hist))
    rc, res = run_json(load_script("trading/scripts/render.py"), ["--in", str(sig), "--prices", str(prices), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "Trading Signals", "symbol": "AC<ME", "observations": 260}
    html = out.read_text()
    assert html.startswith("<title>Trading Signals</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"sma_200"' in html and '"pivots"' in html and '"volume"' in html and '"symbol":"AC<ME"' in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html
    for section in ("Price", "Trailing returns", "Relative to benchmark", "Signals", "Swing pivots", "not a recommendation"):
        assert section in html
    assert "http" not in html.split("window.DATA")[0]  # nothing fetched at runtime
    # plain-language layer: the explain box and glossary terms are built by the page script at runtime
    script = html.split("const FA")[1]
    assert '<div id="explain"></div>' in html and "FA.explain(" in script and "FA.term(" in script and "FA.armTerms(" in script and 'class="explain"' in script
    assert "What am I looking at?" in html and 'data-term=' in script
    for local_term in ('"sma"', '"swing high"', '"swing low"', '"gap"', '"benchmark"'):
        assert local_term in script.split("Object.assign(FA.glossary")[1]


def test_render_works_from_signals_alone_and_takes_a_symbol(tmp_path, capsys, monkeypatch) -> None:
    signals = _run_signals_stdin({"prices": _history(30)["prices"]}, monkeypatch, capsys)
    sig, out = tmp_path / "signals.json", tmp_path / "page.html"
    sig.write_text(json.dumps(signals))
    rc, res = run_json(load_script("trading/scripts/render.py"), ["--in", str(sig), "--symbol", "acme", "--out", str(out)], capsys)
    assert rc == 0 and res["symbol"] == "acme" and res["observations"] == 30
    assert '"history":null' in out.read_text()


def test_render_rejects_wrong_input(tmp_path, capsys, monkeypatch) -> None:
    bad, out = tmp_path / "bad.json", tmp_path / "page.html"
    bad.write_text('{"summary": {}}')
    rc, res = run_json(load_script("trading/scripts/render.py"), ["--in", str(bad), "--out", str(out)], capsys)
    assert rc == 2 and "signals.py result" in res["error"]
    signals = _run_signals_stdin({"prices": _history(30)["prices"]}, monkeypatch, capsys)
    sig = tmp_path / "signals.json"
    sig.write_text(json.dumps(signals))
    rc, res = run_json(load_script("trading/scripts/render.py"), ["--in", str(sig), "--prices", str(bad), "--out", str(out)], capsys)
    assert rc == 2 and "history.py result" in res["error"]
    rc, res = run_json(load_script("trading/scripts/render.py"), ["--in", str(tmp_path / "nope.json"), "--out", str(out)], capsys)
    assert rc == 2 and "could not read signals JSON" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys, monkeypatch) -> None:
    hist = _history(260)
    hist["symbol"] = "ACME"
    signals = _run_signals_stdin({"prices": hist["prices"], "benchmark": [{"date": r["date"], "close": 50.0 + i * 0.1} for i, r in enumerate(hist["prices"])], "pivots": 3, "series": True}, monkeypatch, capsys)
    sig, prices = tmp_path / "signals.json", tmp_path / "history.json"
    sig.write_text(json.dumps(signals)), prices.write_text(json.dumps(hist))
    assert_page_help(render_and_audit("trading/scripts/render.py", ["--in", str(sig), "--prices", str(prices)], tmp_path, capsys))


@requires_chrome
def test_price_lead_escapes_the_symbol(tmp_path, capsys, monkeypatch) -> None:
    hist = _history(60)
    hist["symbol"] = "AC<ME"
    signals = _run_signals_stdin({"prices": hist["prices"]}, monkeypatch, capsys)
    sig, prices = tmp_path / "signals.json", tmp_path / "history.json"
    sig.write_text(json.dumps(signals)), prices.write_text(json.dumps(hist))
    a = render_and_audit("trading/scripts/render.py", ["--in", str(sig), "--prices", str(prices)], tmp_path, capsys)
    assert next(c for c in a["cards"] if c["h2"].endswith("price"))["modal"]["lead"].startswith("AC<ME")
