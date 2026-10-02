from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client, market
from second_opinion.brokers import router
from scripts_util import PLUGIN_ROOT
from page_dom import assert_page_help, render_and_audit, requires_chrome

POSITIONS = {
    "acc-1": [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 60, "price": 100.0, "average_purchase_price": 80.0}],
    "acc-2": [{"symbol": {"symbol": {"symbol": "BND"}}, "units": 30, "price": 50.0, "average_purchase_price": 52.0}],
}
BALANCES = {"acc-1": [{"currency": {"code": "USD"}, "cash": 300.0, "buying_power": 300.0}], "acc-2": [{"currency": {"code": "USD"}, "cash": 200.0, "buying_power": 200.0}]}


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=lambda account_id: POSITIONS[account_id], get_user_account_balance=lambda account_id: BALANCES[account_id])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {})
    return fake


def test_plan_with_inline_targets_across_accounts(sdk, capsys, tmp_path) -> None:
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1"], capsys)
    assert rc == 0, out
    assert out["total_value"] == 8000.0 and out["cash_after"] == 800.0
    assert [(t["symbol"], t["side"], t["value"]) for t in out["trades"]] == [("VTI", "SELL", 1200.0), ("BND", "BUY", 900.0)]
    assert out["sources"] == {"holdings": "snaptrade", "prices": "snaptrade", "targets": "inline", "lots": "snaptrade"}
    assert out["accounts"] == ["acc-1", "acc-2"] and not (tmp_path / "targets.json").exists()
    vti = next(t for t in out["trades"] if t["symbol"] == "VTI")
    assert vti["lots"] == [{"units": 12.0, "cost_per_unit": 80.0, "term": "unknown", "gain": 240.0}] and vti["est_tax"] == 57.6
    assert out["holdings_by_account"] == {"acc-1": ["VTI"], "acc-2": ["BND"]}
    # accounts are classified (acc-2 is a Roth) and the plan says so
    assert out["lot_sources"] == {"VTI": "snaptrade", "BND": "snaptrade"}
    assert out["routing"]["accounts"] == {"acc-1": "taxable", "acc-2": "tax_advantaged"}
    assert [(t["value"], t["account"]) for t in out["trades"]] == [(1200.0, "acc-1"), (900.0, "acc-2")]
    assert out["routing"]["est_tax"] == 57.6 and out["routing"]["est_tax_pro_rata"] == 57.6


def test_plan_saves_and_reuses_targets_file(sdk, capsys, tmp_path) -> None:
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1", "--save"], capsys)
    assert rc == 0 and json.loads((tmp_path / "targets.json").read_text()) == {"targets": {"VTI": 0.6, "BND": 0.3, "CASH": 0.1}, "classes": {}}
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--contribute", "2000", "--no-sells"], capsys)
    assert rc == 0 and out["sources"]["targets"] == str(tmp_path / "targets.json") and out["mode"] == "contribution"
    assert [(t["symbol"], t["side"], t["units"]) for t in out["trades"]] == [("BND", "BUY", 30.0)]


def test_plan_targets_file_with_classes(sdk, capsys, tmp_path) -> None:
    f = tmp_path / "my-targets.json"
    f.write_text(json.dumps({"targets": {"stocks": 0.7, "bonds": 0.3}, "classes": {"VTI": "stocks", "BND": "bonds"}}))
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--targets", str(f), "--whole-shares"], capsys)
    assert rc == 0 and {r["key"] for r in out["allocation"]} == {"stocks", "bonds", "CASH"}
    assert all(t["units"] == float(int(t["units"])) for t in out["trades"])


def test_plan_uses_yahoo_prices_when_available(sdk, monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {"VTI": {"price": 110.0, "previous_close": 100.0}, "BND": {"price": 50.0, "previous_close": 50.0}})
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1"], capsys)
    assert rc == 0 and out["total_value"] == 8600.0 and out["sources"]["prices"] == "yahoo"


def test_plan_errors(sdk, capsys, monkeypatch) -> None:
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), [], capsys)
    assert rc == 2 and "no targets" in out["error"]
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=1", "--account", "nope"], capsys)
    assert rc == 2 and "unknown account" in out["error"]
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.5"], capsys)
    assert rc == 2 and "sum to 1" in out["error"]


def test_rebalance_math_script_from_stdin(capsys, monkeypatch) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"positions": [{"symbol": "VTI", "units": 60, "price": 100}, {"symbol": "BND", "units": 30, "price": 50}], "cash": 500, "targets": {"VTI": 0.6, "BND": 0.3, "CASH": 0.1}})))
    load_script("rebalancing/scripts/rebalance.py").main()
    assert json.loads(capsys.readouterr().out)["cash_after"] == 800.0


# ---------------------------------------------------------------------------
# ledger lots, account routing overrides, suggested bands
# ---------------------------------------------------------------------------


def _write_ledger(tmp_path, transactions: list[dict]) -> None:
    (tmp_path / "ledger.json").write_text(json.dumps({"transactions": transactions, "imports": []}))


def test_plan_uses_ledger_lots_with_real_terms(sdk, capsys, tmp_path) -> None:
    long_ago = (date.today() - timedelta(days=400)).isoformat()  # always "long"
    recent = (date.today() - timedelta(days=30)).isoformat()  # always "short"
    _write_ledger(tmp_path, [
        {"date": long_ago, "type": "BUY", "symbol": "VTI", "units": 40, "price": 70.0, "amount": -2800.0, "account_id": "acc-1"},
        {"date": recent, "type": "BUY", "symbol": "VTI", "units": 20, "price": 95.0, "amount": -1900.0, "account_id": "acc-1"},
        {"date": recent, "type": "BUY", "symbol": "BND", "units": 30, "price": 51.0, "amount": -1530.0, "account_id": "acc-2"},
    ])
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1"], capsys)
    assert rc == 0, out
    assert out["sources"]["lots"] == "ledger" and out["lot_sources"] == {"VTI": "ledger", "BND": "ledger"}
    vti = next(t for t in out["trades"] if t["symbol"] == "VTI")
    # highest-cost lot first: the recent buy at 95 (short)
    assert vti["lots"] == [{"units": 12.0, "cost_per_unit": 95.0, "term": "short", "gain": 60.0}]
    assert vti["est_tax"] == 14.4 and out["est_tax"] == 14.4


def test_plan_split_entry_rescales_units_and_cost(sdk, capsys, tmp_path) -> None:
    _write_ledger(tmp_path, [
        {"date": "2024-06-01", "type": "BUY", "symbol": "VTI", "units": 30, "price": 100.0, "amount": -3000.0, "account_id": "acc-1"},
        {"date": "2024-07-01", "type": "SPLIT", "symbol": "VTI", "units": None, "amount": 0, "split_ratio": 2.0, "account_id": "acc-1"},
    ])
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1"], capsys)
    assert rc == 0, out
    # 30 units @100 -> 60 units @50: units match the broker, cost basis unchanged
    assert out["lot_sources"] == {"VTI": "ledger", "BND": "snaptrade"}
    vti = next(t for t in out["trades"] if t["symbol"] == "VTI")
    assert vti["lots"] == [{"units": 12.0, "cost_per_unit": 50.0, "term": "long", "gain": 600.0}]


def test_plan_falls_back_when_ledger_units_do_not_match(sdk, capsys, tmp_path) -> None:
    _write_ledger(tmp_path, [
        {"date": "2024-06-01", "type": "BUY", "symbol": "VTI", "units": 60, "price": 70.0, "amount": -4200.0, "account_id": "acc-1"},
        {"date": "2025-08-03", "type": "BUY", "symbol": "BND", "units": 10, "price": 51.0, "amount": -510.0, "account_id": "acc-2"},
    ])
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1"], capsys)
    assert rc == 0, out
    # VTI's replayed 60 units match the broker; BND's 10 do not
    assert out["sources"]["lots"] == "mixed" and out["lot_sources"] == {"VTI": "ledger", "BND": "snaptrade"}
    vti = next(t for t in out["trades"] if t["symbol"] == "VTI")
    assert vti["lots"] == [{"units": 12.0, "cost_per_unit": 70.0, "term": "long", "gain": 360.0}]
    assert vti["est_tax"] == 54.0


def test_plan_routing_prefers_the_roth_for_sells(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    positions = {
        "acc-1": [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 60, "price": 100.0, "average_purchase_price": 80.0}],
        "acc-2": [{"symbol": {"symbol": {"symbol": "VTI"}}, "units": 40, "price": 100.0, "average_purchase_price": 95.0}],
    }
    balances = {"acc-1": [{"currency": {"code": "USD"}, "cash": 500.0, "buying_power": 500.0}], "acc-2": [{"currency": {"code": "USD"}, "cash": 0.0, "buying_power": 0.0}]}
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=lambda account_id: positions[account_id], get_user_account_balance=lambda account_id: balances[account_id])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {})
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.5", "--target", "CASH=0.5"], capsys)
    assert rc == 0, out
    # total 10500, VTI target 5250 -> sell 4750: roth absorbs 4000, taxable 750
    assert [(t["value"], t["account"]) for t in out["trades"]] == [(4000.0, "acc-2"), (750.0, "acc-1")]
    assert out["routing"]["accounts"] == {"acc-1": "taxable", "acc-2": "tax_advantaged"}
    assert [(r["value"], r["account"]) for r in out["routing"]["neutral"]] == [(2850.0, "acc-1"), (1900.0, "acc-2")]
    # roth sale untaxed; the taxable sale is 7.5 units at a 20 gain
    assert out["est_realized_gain"] == 350.0 and out["est_tax"] == 36.0
    assert out["routing"]["est_tax"] == 36.0 and out["routing"]["est_tax_pro_rata"] == 136.8


def test_plan_tax_flags_override_the_classification(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=lambda account_id: POSITIONS[account_id], get_user_account_balance=lambda account_id: BALANCES[account_id])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    monkeypatch.setattr(market, "day_changes", lambda symbols, hub=None: {})
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1", "--tax-advantaged", "acc-1"], capsys)
    assert rc == 0, out
    assert out["routing"]["accounts"] == {"acc-1": "tax_advantaged", "acc-2": "tax_advantaged"}
    vti = next(t for t in out["trades"] if t["side"] == "SELL")
    assert vti["est_gain"] == 240.0 and vti["est_tax"] == 0.0


_HIST = {
    "VTI": [
        {"date": "2025-09-01", "close": 100.0, "adj_close": 100.0},
        {"date": "2025-09-02", "close": 102.0, "adj_close": 102.0},
        {"date": "2025-09-03", "close": 104.04, "adj_close": 104.04},
    ],
    "BND": [
        {"date": "2025-09-01", "close": 100.0, "adj_close": 100.0},
        {"date": "2025-09-02", "close": 102.0, "adj_close": 102.0},
        {"date": "2025-09-03", "close": 99.96, "adj_close": 99.96},
        {"date": "2025-09-04", "close": 101.9592, "adj_close": 101.9592},
        {"date": "2025-09-05", "close": 99.920016, "adj_close": 99.920016},
    ],
}


def test_plan_suggest_bands_from_volatility(sdk, monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: _HIST)
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1", "--suggest-bands"], capsys)
    assert rc == 0, out
    bands = {b["key"]: b for b in out["suggested_bands"]}
    assert set(bands) == {"VTI", "BND"}  # CASH has no volatility
    sigma = statistics.stdev([0.02, -0.02, 0.02, -0.02])
    vol = round(sigma * math.sqrt(252), 4)
    assert bands["BND"] == {"key": "BND", "vol_annual": vol, "absolute": 0.09, "relative": 0.5}
    # identical daily returns -> zero volatility -> the floor bands
    assert bands["VTI"] == {"key": "VTI", "vol_annual": 0.0, "absolute": 0.01, "relative": 0.1}


def test_plan_suggest_bands_degrades_without_histories(sdk, monkeypatch, capsys) -> None:
    monkeypatch.setattr(market, "close_histories", lambda symbols, start: {})
    rc, out = run_json(load_script("rebalancing/scripts/plan.py"), ["--target", "VTI=0.6", "--target", "BND=0.3", "--target", "CASH=0.1", "--suggest-bands"], capsys)
    assert rc == 0 and out.get("suggested_bands") == []


def test_render_builds_a_self_contained_page(tmp_path, capsys) -> None:
    plan = {
        "mode": "full", "total_value": 11200.0, "frozen_value": 1000.0, "contribution": 0.0, "withdrawal": -0.0, "bands": {"absolute": 0.05, "relative": 0.25}, "max_drift": 0.1643,
        "allocation": [
            {"key": "stocks", "members": ["VTI"], "value": 8000.0, "weight": 0.7143, "target": 0.55, "drift": 0.1643, "relative_drift": 0.2987, "breach": True, "target_value": 6160.0, "delta_value": -1840.0},
            {"key": "bonds", "members": ["BND"], "value": 1500.0, "weight": 0.1339, "target": 0.2, "drift": -0.0661, "relative_drift": -0.3304, "breach": True, "target_value": 2240.0, "delta_value": 740.0},
            {"key": "CASH", "members": [], "value": 500.0, "weight": 0.0446, "target": 0.1, "drift": -0.0554, "relative_drift": -0.5536, "breach": False, "target_value": 1120.0, "delta_value": 620.0},
        ],
        "trades": [
            {"symbol": "VTI", "side": "SELL", "units": 18.4, "price": 100.0, "value": 1840.0, "reason": "overweight by 16.4%", "account": "acc-2", "lots": [{"units": 18.4, "cost_per_unit": 90.0, "term": "long", "gain": 184.0}], "est_gain": 184.0, "est_tax": 0.0},
            {"symbol": "BND", "side": "BUY", "units": 14.8, "price": 50.0, "value": 740.0, "reason": "underweight <b>6.6%</b>", "account": "acc-2", "lots": None, "est_gain": None, "est_tax": None},
        ],
        "post_trade": [{"key": "stocks", "value": 6160.0, "weight": 0.55, "target": 0.55, "drift": 0.0}, {"key": "bonds", "value": 2240.0, "weight": 0.2, "target": 0.2, "drift": 0.0}, {"key": "CASH", "value": 1120.0, "weight": 0.1, "target": 0.1, "drift": 0.0}],
        "cash_after": 1120.0, "buys_total": 740.0, "sells_total": 1840.0, "turnover": 0.1152, "est_realized_gain": 184.0, "est_tax": 0.0,
        "routing": {"accounts": {"acc-1": "taxable", "acc-2": "tax_advantaged"}, "neutral": [], "tax_preferred": [], "est_tax": 0.0, "est_tax_pro_rata": 16.56},
        "frozen": [{"symbol": "GLD", "value": 1000.0}],
        "flags": [{"code": "BAND_BREACH", "message": "outside the 5% / 25% bands: bonds (-6.6%), stocks (+16.4%)"}, {"code": "UNMAPPED", "message": "not in classes and left untouched: GLD (1000.00)"}],
        "sources": {"holdings": "snaptrade", "prices": "yahoo", "targets": "inline", "lots": "ledger"}, "accounts": ["acc-1", "acc-2"], "holdings_by_account": {"acc-1": ["VTI", "GLD"], "acc-2": ["VTI", "BND"]}, "lot_sources": {"VTI": "ledger", "BND": "snaptrade"},
        "suggested_bands": [{"key": "stocks", "vol_annual": 0.17, "absolute": 0.05, "relative": 0.25}],
    }
    src = tmp_path / "plan.json"
    src.write_text(json.dumps(plan))
    out = tmp_path / "page.html"
    rc, res = run_json(load_script("rebalancing/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res["out"] == str(out) and res["trades"] == 2 and res["breaches"] == 2 and res["flags"] == 2
    html = out.read_text()
    assert html.startswith("<title>Rebalancing Plan</title>") and "<html" not in html and "<body" not in html
    assert "window.DATA = " in html and '"BAND_BREACH"' in html and "const FA" in html
    # the reason's markup stays JSON data, never markup in the body; the static headline reads without JS and never shows $-0.00
    assert "underweight <b>6.6%</b>" not in html and '"underweight <b>6.6%<\\/b>"' in html
    assert "full rebalance of $11,200.00 · contribution $0.00 · withdrawal $0.00 · frozen $1,000.00 · bands 5.0% / 25.0% · max drift 16.4% · 2 breaches · 2 trades · est. tax $0.00" in html
    for section in ("Drift vs target", "Contribution routing", "After trades", "Allocation", "Trades", "Suggested bands", "Flags", "This is a plan, not orders", "var(--down)"):
        assert section in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html
    # plain-language layer: the explain box slot is in the body, the script fills it and marks jargon with glossary terms (spans appear at runtime)
    assert 'id="explain"' in html.split("<script>")[0] and 'class="explain"' in html and "FA.explain(" in html and "FA.term(" in html and "data-term=" in html
    for term in ("'drift'", "'rebalancing band'", "'turnover'", "'realized gain'", "'tax lot'", "'target weight'", "'relative drift'", "'pro rata'"):
        assert term in html
    assert "This is a plan, not orders; nothing is traded from this page" in html


def test_render_rejects_non_plan_input(tmp_path, capsys) -> None:
    src = tmp_path / "bad.json"
    src.write_text('{"portfolio": {}}')
    rc, res = run_json(load_script("rebalancing/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "rebalance.py result" in res["error"]
    src.write_text("not json")
    rc, res = run_json(load_script("rebalancing/scripts/render.py"), ["--in", str(src), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


@requires_chrome
def test_every_card_explains_itself(tmp_path, capsys) -> None:
    a = render_and_audit("rebalancing/scripts/render.py", ["--in", str(PLUGIN_ROOT / "docs/samples/rebalancing.json")], tmp_path, capsys)
    assert_page_help(a)


def test_term_is_long_only_after_the_one_year_anniversary() -> None:
    plan = load_script("rebalancing/scripts/plan.py")
    # 366 days across Feb 29 2024 is still the anniversary itself: short-term.
    assert plan._term("2023-03-01", date(2024, 3, 1)) == "short"
    assert plan._term("2023-03-01", date(2024, 3, 2)) == "long"
    assert plan._term("2024-02-29", date(2025, 2, 28)) == "short"
    assert plan._term("2024-02-29", date(2025, 3, 1)) == "long"
    assert plan._term("2024-06-10", date(2025, 6, 10)) == "short"
    assert plan._term("2024-06-10", date(2025, 6, 11)) == "long"
