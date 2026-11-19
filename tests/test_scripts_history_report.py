from __future__ import annotations


import pytest
from second_opinion import ledger, market
from second_opinion.brokers import router
from second_opinion.errors import ConfigError
from scripts_util import load_script, run_json

TODAY = "2026-01-20"


class StubRegistry:
    def __init__(self, rows):
        self.rows = rows

    def load(self):
        return self.rows


class StubHub:
    def __init__(self, accounts, positions=None, balances=None, txns=None, shadowed=None, error=None, registry=None, tx_errors=None):
        self._accounts, self._positions, self._balances = accounts, positions or {}, balances or {}
        self._txns, self.shadowed, self.error = txns or {}, shadowed or [], error
        self.partial = False
        self.broker_errors = []
        self.registry = registry
        self.tx_calls: list[dict] = []
        self.tx_errors = tx_errors or {}

    def list_accounts(self, **_kw):
        if self.error is not None:
            if not self.partial:
                raise self.error
            self.broker_errors = [{"broker": "etrade", "code": "ETRADE_REAUTH", "message": "login needed"}]
        return self._accounts

    def get_portfolio(self, aid):
        return {"positions": self._positions.get(aid, [])}

    def get_balance(self, aid):
        return {"balances": [{"cash": self._balances.get(aid, 0.0)}]}

    def list_transactions(self, aid, start=None, end=None, count=None):
        self.tx_calls.append({"aid": aid, "start": start, "end": end})
        if aid in self.tx_errors:
            raise self.tx_errors[aid]
        return {"transactions": self._txns.get(aid, [])}

    def unavailable_flags(self):
        return [{"code": "BROKER_UNAVAILABLE", "message": f"{e['broker']}: {e['message']}"} for e in self.broker_errors]


def _closes(sym, dates, close=100.0):
    return [{"date": d, "close": close, "adj_close": close} for d in dates]


DATES = ["2026-01-02", "2026-01-05", "2026-01-08", "2026-01-12", "2026-01-20"]


@pytest.fixture
def rep(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    mod = load_script("portfolio-analysis/scripts/history_report.py")
    mod.date = type("D", (), {"today": staticmethod(lambda: __import__("datetime").date.fromisoformat(TODAY)),
                              "fromisoformat": staticmethod(__import__("datetime").date.fromisoformat)})
    calls = {"close": [], "splits": []}

    def close_histories(symbols, start):
        calls["close"].append((sorted(symbols), start))
        return {s: _closes(s, DATES) for s in symbols if s not in calls.get("missing", ())}

    def split_histories(symbols, start):
        calls["splits"].append((sorted(symbols), start))
        return {s: [] for s in symbols}

    monkeypatch.setattr(market, "close_histories", close_histories)
    monkeypatch.setattr(market, "split_histories", split_histories)
    mod.calls = calls
    mod.tmp_path = tmp_path
    return mod


def _hub(monkeypatch, hub):
    monkeypatch.setattr(router, "load", lambda: hub)
    return hub


def _book(rows):
    book = {"transactions": [], "imports": []}
    ledger.merge(book, rows, source="test")
    ledger.save(book)


def _row(d, typ, aid="a1", symbol=None, units=None, amount=0.0):
    return {"date": d, "type": typ, "symbol": symbol, "units": units, "amount": amount, "account_id": aid}


ACC = [{"account_id": "a1", "name": "Brokerage", "account_type": "cash", "broker": "snaptrade"}]
POS = {"a1": [{"symbol": "AAPL", "units": 10, "price": 100.0}]}


def test_top_up_merges_new_activity_before_rebuild(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0), _row("2026-01-05", "DEPOSIT", amount=0.0)])
    raw = {"id": "t1", "type": "BUY", "trade_date": "2026-01-08", "symbol": {"symbol": "AAPL"}, "units": 5, "price": 100.0, "amount": -500.0}
    hub = _hub(monkeypatch, StubHub(ACC, POS, {"a1": 0.0}, txns={"a1": [raw]}))
    rc, out = run_json(rep, ["--partial"], capsys)
    assert rc == 0, out
    assert hub.tx_calls[0]["start"] == "2025-12-29"  # a week before the newest row: late-posted activity
    saved = ledger.load()["transactions"]
    assert any(t["date"] == "2026-01-08" and t["type"] == "BUY" for t in saved)


def test_no_top_up_without_ledger_rows_and_no_file_created(rep, monkeypatch, capsys) -> None:
    hub = _hub(monkeypatch, StubHub(ACC, POS))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0 and hub.tx_calls == []
    assert not ledger.ledger_path().exists()


def test_empty_ledger_flags(rep, monkeypatch, capsys) -> None:
    _hub(monkeypatch, StubHub(ACC, POS))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0
    flag = next(f for f in out["flags"] if f["code"] == "LEDGER_EMPTY")
    assert "statement-import" in flag["message"]
    assert out["sources"]["flows"] == "ledger"


def test_aliases_built_from_shadowed(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", aid="d1", amount=1000.0)])
    seen = {}
    real = rep.history.run_history
    monkeypatch.setattr(rep.history, "run_history", lambda p: seen.update(p) or real(p))
    acc = [{"account_id": "d1", "name": "Direct", "account_type": "cash", "broker": "etrade"}]
    _hub(monkeypatch, StubHub(acc, {"d1": []}, {"d1": 1000.0}, shadowed=[{"snaptrade_account_id": "s1", "direct_account_id": "d1"}]))
    rc, _ = run_json(rep, [], capsys)
    assert rc == 0 and seen["aliases"] == {"s1": "d1"}


def test_proxy_map_resolved_from_names(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    seen = {}
    real = rep.history.run_history
    monkeypatch.setattr(rep.history, "run_history", lambda p: seen.update(p) or real(p))
    pos = {"a1": [{"symbol": "ONMZ", "units": 10, "price": 12.0, "name": "VG IS TOT BD MKT IDX"}]}
    _hub(monkeypatch, StubHub(ACC, pos))
    rc, _ = run_json(rep, [], capsys)
    assert rc == 0 and seen["proxies"] == {"ONMZ": "BND"}
    symbols, start = rep.calls["close"][0]
    assert "BND" in symbols and {"SPY", "QQQ", "DIA"} <= set(symbols) and start == "2026-01-02"
    assert len(rep.calls["close"]) == 1


def test_partial_excludes_etrade_accounts(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", aid="e1", amount=500.0), _row("2026-01-02", "DEPOSIT", amount=1000.0)])
    err = ConfigError("E*Trade authorization required", code="ETRADE_REAUTH", url="https://x", partial="--partial")
    reg = StubRegistry({"e1": {"broker": "etrade", "name": "E*Trade IRA"}, "a1": {"broker": "snaptrade"}})
    _hub(monkeypatch, StubHub(ACC, POS, {"a1": 1000.0}, error=err, registry=reg))
    rc, out = run_json(rep, [], capsys)
    assert rc == 4 and out["code"] == "ETRADE_REAUTH"
    _hub(monkeypatch, StubHub(ACC, POS, {"a1": 1000.0}, error=err, registry=reg))
    rc, out = run_json(rep, ["--partial"], capsys)
    assert rc == 0, out
    assert any(f["code"] == "BROKER_UNAVAILABLE" for f in out["flags"])
    assert [e["account_id"] for e in out["excluded"]] == ["e1"]
    assert not any(f["code"] == "UNASSIGNED_ROWS" for f in out["flags"])


def test_benchmark_fetch_failure_degrades(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    rep.calls["missing"] = ("SPY", "QQQ", "DIA")
    _hub(monkeypatch, StubHub(ACC, {"a1": []}, {"a1": 1000.0}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    assert any(f["code"] == "BENCHMARK_UNAVAILABLE" for f in out["flags"])
    assert any(s["key"] == "a1" for s in out["series"])


def test_split_lookup_failure_adds_flag(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    monkeypatch.setattr(market, "split_histories", lambda s, start: (_ for _ in ()).throw(RuntimeError("boom")))
    _hub(monkeypatch, StubHub(ACC, {"a1": []}, {"a1": 1000.0}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0 and any(f["code"] == "SPLITS_UNAVAILABLE" for f in out["flags"])


def test_bad_since_is_exit_2(rep, monkeypatch, capsys) -> None:
    _hub(monkeypatch, StubHub(ACC))
    rc, _ = run_json(rep, ["--since", "nope"], capsys)
    assert rc == 2


def test_split_histories_downloads_actions_once(monkeypatch) -> None:
    import pandas as pd

    idx = pd.to_datetime(["2026-01-02", "2026-01-05"])
    df = pd.DataFrame({("AAPL", "Stock Splits"): [0.0, 4.0], ("MSFT", "Stock Splits"): [0.0, 0.0]}, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    seen = []

    class Yf:
        @staticmethod
        def download(syms, **kw):
            seen.append((syms, kw))
            return df

    monkeypatch.setattr(market, "_yf", lambda: Yf)
    out = market.split_histories(["aapl", "MSFT"], "2025-01-01")
    assert out == {"AAPL": [{"date": "2026-01-05", "ratio": 4.0}], "MSFT": []}
    assert len(seen) == 1 and seen[0][1]["actions"] is True


def test_money_market_reported_as_cash_is_not_double_counted(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    seen = {}
    real = rep.history.run_history
    monkeypatch.setattr(rep.history, "run_history", lambda p: seen.update(p) or real(p))
    acc = [{"account_id": "a1", "name": "Fidelity", "account_type": "cash", "broker": "snaptrade", "balance_total": 1500.0}]
    pos = {"a1": [{"symbol": "SPAXX", "units": 1000.0, "price": 1.0, "name": "FIDELITY GOVERNMENT MONEY MARKET"},
                  {"symbol": "AAPL", "units": 5, "price": 100.0}]}
    _hub(monkeypatch, StubHub(acc, pos, {"a1": 1000.0}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    (account,) = seen["accounts"]
    assert account["cash"] == 0.0
    value = account["cash"] + sum(p["units"] * p["price"] for p in account["positions"])
    assert value == 1500.0


def test_twin_ledger_tops_up_from_twin_newest_row(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", aid="s1", amount=1000.0), _row("2026-01-05", "DEPOSIT", aid="s1", amount=1.0)])
    acc = [{"account_id": "d1", "name": "Direct", "account_type": "cash", "broker": "etrade"}]
    hub = _hub(monkeypatch, StubHub(acc, {"d1": []}, {"d1": 1001.0}, shadowed=[{"snaptrade_account_id": "s1", "direct_account_id": "d1"}]))
    rc, _ = run_json(rep, [], capsys)
    assert rc == 0
    assert [(c["aid"], c["start"]) for c in hub.tx_calls] == [("d1", "2025-12-29")]


def test_ledger_not_saved_when_top_up_adds_nothing(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    saves = []
    monkeypatch.setattr(rep.ledger, "save", lambda *a, **k: saves.append(1))
    hub = _hub(monkeypatch, StubHub(ACC, {"a1": []}, {"a1": 1000.0}))
    rc, _ = run_json(rep, [], capsys)
    assert rc == 0 and hub.tx_calls and saves == []


def _capture(rep, monkeypatch):
    seen = {}
    real = rep.history.run_history
    monkeypatch.setattr(rep.history, "run_history", lambda p: seen.update(p) or real(p))
    return seen


def test_short_position_reaches_history(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    seen = _capture(rep, monkeypatch)
    pos = {"a1": [{"symbol": "AAPL", "units": -2, "price": 100.0}, {"symbol": "MSFT", "units": 3, "price": 50.0}]}
    _hub(monkeypatch, StubHub(ACC, pos, {"a1": 1000.0}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    assert {p["symbol"]: p["units"] for p in seen["accounts"][0]["positions"]} == {"AAPL": -2.0, "MSFT": 3.0}


def test_symbolless_and_non_numeric_positions_are_skipped(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    seen = _capture(rep, monkeypatch)
    pos = {"a1": [{"units": 5, "price": 1.0}, {"symbol": "AAPL", "units": "x"}, {"symbol": "MSFT", "units": 3, "price": 50.0}]}
    _hub(monkeypatch, StubHub(ACC, pos, {"a1": 1000.0}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    assert [p["symbol"] for p in seen["accounts"][0]["positions"]] == ["MSFT"]


def test_empty_account_list_exits_0(rep, monkeypatch, capsys) -> None:
    _hub(monkeypatch, StubHub([]))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0 and any(f["code"] == "LEDGER_EMPTY" for f in out["flags"])


def test_duplicate_account_id_read_once(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    seen = _capture(rep, monkeypatch)
    _hub(monkeypatch, StubHub([*ACC, *ACC], {"a1": []}, {"a1": 1000.0}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    assert len(seen["accounts"]) == 1


# --- final review fixes ---------------------------------------------------------------


def test_top_up_picks_up_late_posted_activity_dated_before_newest_row(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0), _row("2026-01-08", "DEPOSIT", amount=0.0)])
    late = {"id": "t9", "type": "DIVIDEND", "trade_date": "2026-01-05", "symbol": {"symbol": "AAPL"}, "amount": 3.0}
    again = {"id": "t0", "type": "CONTRIBUTION", "trade_date": "2026-01-02", "amount": 1000.0}
    hub = _hub(monkeypatch, StubHub(ACC, POS, {"a1": 3.0}, txns={"a1": [late]}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    assert hub.tx_calls[0]["start"] == "2026-01-01"
    assert any(t["date"] == "2026-01-05" and t["type"] == "DIVIDEND" for t in ledger.load()["transactions"])
    # an exact duplicate fetched again is not added twice
    n = len(ledger.load()["transactions"])
    _hub(monkeypatch, StubHub(ACC, POS, {"a1": 3.0}, txns={"a1": [late, again]}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0 and len(ledger.load()["transactions"]) in (n, n + 1)
    assert sum(1 for t in ledger.load()["transactions"] if t["type"] == "DIVIDEND") == 1


def test_unpriced_money_market_not_double_counted(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0)])
    seen = _capture(rep, monkeypatch)
    acc = [{"account_id": "a1", "name": "Fidelity", "account_type": "cash", "broker": "snaptrade", "balance_total": 1500.0}]
    pos = {"a1": [{"symbol": "SPAXX", "units": 1000.0, "name": "FIDELITY GOVERNMENT MONEY MARKET"},
                  {"symbol": "AAPL", "units": 5, "price": 100.0}]}
    _hub(monkeypatch, StubHub(acc, pos, {"a1": 1000.0}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    (account,) = seen["accounts"]
    assert account["cash"] == 0.0  # SPAXX is valued at $1.00 by history.py; it must not stay in cash too
    assert "price" not in next(p for p in account["positions"] if p["symbol"] == "SPAXX")


class FakeBroker:
    """A broker adapter behind the real router.Hub."""

    def __init__(self, name, rows, error=None):
        self.name, self.rows, self.error = name, rows, error
        self.tx_calls: list[str] = []

    def list_accounts(self, include_closed=False):
        if self.error is not None:
            raise self.error
        return [dict(r) for r in self.rows]

    def get_portfolio(self, aid):
        return {"positions": []}

    def get_balance(self, aid):
        return {"balances": [{"cash": 1000.0}]}

    def list_transactions(self, aid, start=None, end=None, count=None):
        self.tx_calls.append(aid)
        return {"transactions": []}


E1 = {"account_id": "e1", "broker": "etrade", "account_number": "84150001", "institution_name": "E*TRADE", "name": "E*Trade IRA"}
S1 = {"account_id": "s1", "broker": "snaptrade", "account_number": "84150001", "institution_name": "E*Trade", "name": "IRA via SnapTrade"}
A1 = {"account_id": "a1", "broker": "snaptrade", "account_number": "Z1", "institution_name": "Fidelity", "name": "Brokerage"}


def test_partial_drops_snaptrade_twin_of_unavailable_direct_account(rep, monkeypatch, capsys) -> None:
    from second_opinion.brokers import registry as registry_mod

    _book([_row("2026-01-02", "DEPOSIT", aid="s1", amount=1000.0), _row("2026-01-02", "DEPOSIT", aid="e1", amount=1000.0),
           _row("2026-01-02", "DEPOSIT", amount=1000.0)])
    reg = registry_mod.Registry()
    # a run with E*Trade logged in: the router shadows the twin and the registry remembers e1
    snap = FakeBroker("snaptrade", [S1, A1])
    _hub(monkeypatch, router.Hub([FakeBroker("etrade", [E1]), snap], {}, reg))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    assert {s["key"] for s in out["series"]} == {"combined", "e1", "a1"}
    # E*Trade logged out, --partial: the twin is listed as live by the router; it must not be drawn or topped up
    err = ConfigError("E*Trade authorization required", code="ETRADE_REAUTH")
    for _ in range(2):  # twice: the second run sees the registry the first --partial run rewrote
        snap = FakeBroker("snaptrade", [S1, A1])
        _hub(monkeypatch, router.Hub([FakeBroker("etrade", [E1], error=err), snap], {}, reg))
        seen = _capture(rep, monkeypatch)
        rc, out = run_json(rep, ["--partial"], capsys)
        assert rc == 0, out
        assert {s["key"] for s in out["series"]} == {"combined", "a1"}
        assert [a["account_id"] for a in seen["accounts"]] == ["a1"]
        assert "s1" not in snap.tx_calls
        assert [e["account_id"] for e in out["excluded"]] == ["e1"]
        assert not any(t["account_id"] in ("s1", "e1") for t in seen["transactions"])
        assert any(f["code"] == "BROKER_UNAVAILABLE" for f in out["flags"])


def test_twin_numbered_as_direct_id_is_folded(rep, monkeypatch, capsys) -> None:
    # SnapTrade reports E*Trade's accountIdKey as the number; no institution name for merge_accounts to go on
    _book([_row("2026-01-02", "DEPOSIT", aid="s1", amount=1000.0), _row("2026-01-02", "DEPOSIT", aid="e1", amount=1000.0)])
    twin = {**S1, "account_number": "e1", "institution_name": ""}
    seen = _capture(rep, monkeypatch)
    _hub(monkeypatch, router.Hub([FakeBroker("etrade", [E1]), FakeBroker("snaptrade", [twin, A1])], {}, None))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    assert seen["aliases"] == {"s1": "e1"}
    assert [a["account_id"] for a in seen["accounts"]] == ["e1", "a1"]


ACC2 = [*ACC, {"account_id": "e1", "name": "E*Trade IRA", "account_type": "cash", "broker": "etrade"}]


def test_activity_fetch_failure_excludes_that_broker(rep, monkeypatch, capsys) -> None:
    from second_opinion.errors import ApiError

    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0), _row("2026-01-02", "DEPOSIT", aid="e1", amount=500.0)])
    hub = _hub(monkeypatch, StubHub(ACC2, {"a1": [], "e1": []}, {"a1": 1000.0, "e1": 500.0},
                                    tx_errors={"e1": ApiError("E*Trade is down")}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 0, out
    assert {s["key"] for s in out["series"]} == {"combined", "a1"}
    assert [e["account_id"] for e in out["excluded"]] == ["e1"]
    assert any(f["code"] == "BROKER_UNAVAILABLE" and "etrade" in f["message"] for f in out["flags"])
    assert {c["aid"] for c in hub.tx_calls} == {"a1", "e1"}


def test_activity_fetch_needing_login_exits_4_unless_partial(rep, monkeypatch, capsys) -> None:
    _book([_row("2026-01-02", "DEPOSIT", amount=1000.0), _row("2026-01-02", "DEPOSIT", aid="e1", amount=500.0)])
    err = ConfigError("E*Trade authorization required", code="ETRADE_REAUTH", url="https://x")
    _hub(monkeypatch, StubHub(ACC2, {"a1": [], "e1": []}, {"a1": 1000.0, "e1": 500.0}, tx_errors={"e1": err}))
    rc, out = run_json(rep, [], capsys)
    assert rc == 4 and out["code"] == "ETRADE_REAUTH" and out["partial"] == "--partial" and out["url"] == "https://x"
    _hub(monkeypatch, StubHub(ACC2, {"a1": [], "e1": []}, {"a1": 1000.0, "e1": 500.0}, tx_errors={"e1": err}))
    rc, out = run_json(rep, ["--partial"], capsys)
    assert rc == 0, out
    assert [e["account_id"] for e in out["excluded"]] == ["e1"]
