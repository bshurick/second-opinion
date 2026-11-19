"""Tests for portfolio-analysis/scripts/history.py: ledger rebuild + time-weighted return."""

from __future__ import annotations

import io
import json

import pytest
from scripts_util import load_script

history = load_script("portfolio-analysis/scripts/history.py")

DAYS = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]


def _rows(closes, adj=None, days=DAYS):
    adj = adj or closes
    return [
        {"date": d, "close": c, "adj_close": a}
        for d, c, a in zip(days, closes, adj)
        if c is not None
    ]


def _txn(date, kind, symbol=None, units=None, amount=None, account="A"):
    return {"date": date, "type": kind, "symbol": symbol, "units": units, "amount": amount, "account_id": account}


def _acct(account_id="A", units=10.0, cash=0.0, name=None):
    positions = [{"symbol": "AAPL", "units": units}] if units else []
    return {"account_id": account_id, "name": name or account_id, "cash": cash, "positions": positions}


def _params(accounts, txns, prices, **extra):
    return {"as_of": "2026-01-09", "accounts": accounts, "transactions": txns, "prices": prices, **extra}


def _series(out, key="combined"):
    return next(s for s in out["series"] if s["key"] == key)


BASE = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-06", "BUY", "AAPL", 10.0, -1000.0)]


def test_buys_and_sells_only():
    prices = {"AAPL": _rows([100, 100, 110, 110, 121])}
    out = history.run_history(_params([_acct()], BASE, prices))
    last = _series(out)["points"][-1]
    assert last[0] == "2026-01-09"
    assert last[1] == pytest.approx(1.21)
    assert last[2] == 1210


def test_dividend_raises_return():
    prices = {"AAPL": _rows([100] * 5)}
    txns = BASE + [_txn("2026-01-08", "DIVIDEND", "AAPL", amount=10.0)]
    out = history.run_history(_params([_acct(cash=10.0)], txns, prices))
    assert _series(out)["points"][-1][1] == pytest.approx(1.01)


def test_deposit_does_not_move_return():
    prices = {"AAPL": _rows([100] * 5)}
    txns = BASE + [_txn("2026-01-07", "DEPOSIT", amount=500.0)]
    out = history.run_history(_params([_acct(cash=500.0)], txns, prices))
    pts = _series(out)["points"]
    assert pts[-1][2] == 1500
    assert all(p[1] == pytest.approx(1.0) for p in pts)


def test_withdrawal_does_not_move_return():
    prices = {"AAPL": _rows([100] * 5)}
    txns = BASE + [_txn("2026-01-07", "WITHDRAWAL", amount=-200.0)]
    acct = {**_acct(cash=-200.0), "account_type": "margin"}  # negative cash needs margin
    out = history.run_history(_params([acct], txns, prices))
    pts = _series(out)["points"]
    assert pts[-1][2] == 800
    assert all(p[1] == pytest.approx(1.0) for p in pts)


def test_deposit_same_day_as_drop():
    # 01-06 buys 5 of 10 shares' worth; stock is half of V(01-06)=1000, deposit 1000 on the drop day
    prices = {"AAPL": _rows([100, 100, 90, 90, 90])}
    txns = [
        _txn("2026-01-05", "DEPOSIT", amount=1000.0),
        _txn("2026-01-06", "BUY", "AAPL", 5.0, -500.0),
        _txn("2026-01-07", "DEPOSIT", amount=1000.0),
    ]
    out = history.run_history(_params([_acct(units=5.0, cash=1500.0)], txns, prices))
    pts = {p[0]: p for p in _series(out)["points"]}
    v_prev = 500.0 + 5 * 100  # cash + stock at 01-06 close
    share = 5 * 100 / v_prev
    assert pts["2026-01-07"][1] / pts["2026-01-06"][1] - 1 == pytest.approx(-0.10 * share)


def test_transfer_in_shares_is_external_flow():
    prices = {"AAPL": _rows([100] * 5)}
    txns = BASE + [_txn("2026-01-07", "TRANSFER_IN", "AAPL", 5.0, None)]
    out = history.run_history(_params([_acct(units=15.0)], txns, prices))
    pts = {p[0]: p for p in _series(out)["points"]}
    assert pts["2026-01-06"][2] == 1000
    assert pts["2026-01-07"][2] == 1500
    assert all(p[1] == pytest.approx(1.0) for p in pts.values())


def test_missing_close_carries_forward():
    prices = {"AAPL": _rows([100, None, 100, 100, 100]), "SPY": _rows([1, 1, 1, 1, 1])}
    out = history.run_history(_params([_acct()], BASE, prices))
    pts = {p[0]: p for p in _series(out)["points"]}
    assert pts["2026-01-06"][2] == 1000
    assert out["flags"] == []


def test_combined_sums_values_and_flows():
    prices = {"AAPL": _rows([100, 100, 110, 110, 110]), "FLAT": _rows([100] * 5)}
    a_txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0)]
    b_txns = [
        _txn("2026-01-06", "DEPOSIT", amount=1000.0, account="B"),
        _txn("2026-01-06", "BUY", "FLAT", 10.0, -1000.0, account="B"),
    ]
    b = {"account_id": "B", "name": "B", "cash": 0.0, "positions": [{"symbol": "FLAT", "units": 10.0}]}
    out = history.run_history(_params([_acct(), b], a_txns + b_txns, prices))
    combined = _series(out)
    assert combined["start"] == "2026-01-06"
    assert combined["points"][0][1] == 1.0
    assert _series(out, "A")["start"] == "2026-01-05"
    assert _series(out, "B")["start"] == "2026-01-06"
    # from 01-06: A is 1000 -> 1100 (+10%), B flat; equal size -> +5%
    assert combined["points"][-1][1] == pytest.approx(1.05)
    assert combined["points"][-1][2] == 2100


def test_benchmark_from_adj_close():
    prices = {
        "AAPL": _rows([100] * 5),
        "SPY": _rows([1] * 5, adj=[400, 410, 420, 430, 440]),
        "QQQ": _rows([1] * 5, adj=[100, 100, 100, 100, 100]),
        "DIA": _rows([1] * 5, adj=[10, 10, 10, 10, 11]),
    }
    out = history.run_history(_params([_acct()], BASE, prices, benchmarks=["SPY", "QQQ", "DIA"]))
    by = {b["symbol"]: b for b in out["benchmarks"]}
    assert by["SPY"]["label"] == "S&P 500"
    assert by["QQQ"]["label"] == "Nasdaq"
    assert by["DIA"]["label"] == "Dow"
    assert by["SPY"]["points"][0] == ["2026-01-05", 1.0]
    assert by["SPY"]["points"][-1][1] == pytest.approx(1.10)
    assert by["DIA"]["points"][-1][1] == pytest.approx(1.10)


def test_series_carry_estimated_false_and_label():
    prices = {"AAPL": _rows([100] * 5)}
    out = history.run_history(_params([_acct(name="Brokerage")], BASE, prices))
    assert _series(out)["label"] == "All accounts"
    assert _series(out, "A")["label"] == "Brokerage"
    assert all(s["estimated"] is False for s in out["series"])


def test_later_task_keys_are_ignored():
    prices = {"AAPL": _rows([100] * 5)}
    acct = {**_acct(), "account_type": "taxable"}
    acct["positions"][0].update(name="Apple", price=100.0)
    out = history.run_history(
        _params([acct], BASE, prices, aliases={"x": "A"}, proxies={}, splits={})
    )
    assert _series(out)["points"][-1][1] == pytest.approx(1.0)


def test_other_row_counted_in_flag():
    prices = {"AAPL": _rows([100] * 5)}
    txns = BASE + [_txn("2026-01-08", "OTHER", amount=5.0)]
    out = history.run_history(_params([_acct(cash=5.0)], txns, prices))
    assert [f["code"] for f in out["flags"]] == ["OTHER_TYPES"]
    assert _series(out)["points"][-1][1] == pytest.approx(1.005)


def test_account_without_ledger_rows_is_excluded():
    prices = {"AAPL": _rows([100] * 5)}
    out = history.run_history(_params([_acct(), _acct("Z")], BASE, prices))
    assert [e["account_id"] for e in out["excluded"]] == ["Z"]
    assert "NO_HISTORY" in [f["code"] for f in out["flags"]]
    assert "statement-import" in next(f["message"] for f in out["flags"] if f["code"] == "NO_HISTORY")


def test_bad_input_exits_2(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    with pytest.raises(SystemExit) as exc:
        history.main()
    assert exc.value.code == 2
    assert "error" in json.loads(capsys.readouterr().out)


# --- Task 1 review coverage: SELL sign, share TRANSFER_OUT, FEE -------------------------


def test_sell_undo_restores_units_and_cash():
    prices = {"AAPL": _rows([100, 100, 100, 120, 120])}
    txns = BASE + [_txn("2026-01-07", "SELL", "AAPL", 4.0, 400.0)]
    out = history.run_history(_params([_acct(units=6.0, cash=400.0)], txns, prices))
    pts = {p[0]: p for p in _series(out)["points"]}
    assert pts["2026-01-06"][2] == 1000  # 10 units, no cash
    assert pts["2026-01-07"][2] == 1000  # 6 units + 400 cash
    assert pts["2026-01-08"][2] == 1120  # 6 x 120 + 400
    assert pts["2026-01-09"][1] == pytest.approx(1.12)


def test_transfer_out_shares_is_external_flow():
    prices = {"AAPL": _rows([100] * 5)}
    txns = BASE + [_txn("2026-01-07", "TRANSFER_OUT", "AAPL", 4.0, None)]
    out = history.run_history(_params([_acct(units=6.0)], txns, prices))
    pts = {p[0]: p for p in _series(out)["points"]}
    assert pts["2026-01-06"][2] == 1000
    assert pts["2026-01-07"][2] == 600
    assert all(p[1] == pytest.approx(1.0) for p in pts.values())


def test_fee_lowers_return():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [
        _txn("2026-01-05", "DEPOSIT", amount=1010.0),
        _txn("2026-01-06", "BUY", "AAPL", 10.0, -1000.0),
        _txn("2026-01-08", "FEE", amount=-10.0),
    ]
    out = history.run_history(_params([_acct(cash=0.0)], txns, prices))
    pts = {p[0]: p for p in _series(out)["points"]}
    assert pts["2026-01-07"][2] == 1010
    assert pts["2026-01-09"][1] == pytest.approx(1000 / 1010)


# --- splits ---------------------------------------------------------------------------

SPLIT_DAY = "2026-01-07"
FLAT50 = {"AAPL": _rows([50] * 5)}  # Yahoo close is already in post-split terms


def _split_row(ratio, units=None, date=SPLIT_DAY):
    return {**_txn(date, "SPLIT", "AAPL", units, None), "split_ratio": ratio}


def _codes(out):
    return [f["code"] for f in out["flags"]]


def test_split_factor_multiplies_later_ratios():
    splits = {"AAPL": [{"date": "2026-01-07", "ratio": 2.0}, {"date": "2026-03-02", "ratio": 3.0}]}
    assert history._split_factor("AAPL", "2026-01-05", splits) == 6.0
    assert history._split_factor("AAPL", "2026-01-07", splits) == 3.0  # trades on the split day are post-split
    assert history._split_factor("AAPL", "2026-04-01", splits) == 1.0
    assert history._split_factor("MSFT", "2026-01-05", splits) == 1.0


def test_forward_split_as_traded():
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
            _split_row(2.0)]
    out = history.run_history(_params([_acct(units=20.0)], txns, FLAT50))
    assert "HISTORY_BREAK" not in _codes(out)
    pts = _series(out, "A")["points"]
    assert pts[0][0] == "2026-01-05"
    assert all(p[1] == pytest.approx(1.0) and p[2] == 1000 for p in pts)
    splits = {"AAPL": [{"date": SPLIT_DAY, "ratio": 2.0}]}
    assert history._detect_split_convention("AAPL", txns, splits, 20.0) == "as_traded"


def test_forward_split_already_adjusted():
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 20.0, -1000.0),
            _split_row(2.0)]
    splits = {"AAPL": [{"date": SPLIT_DAY, "ratio": 2.0}]}
    assert history._detect_split_convention("AAPL", txns, splits, 20.0) == "adjusted"
    out = history.run_history(_params([_acct(units=20.0)], txns, FLAT50))
    assert "HISTORY_BREAK" not in _codes(out)
    pts = _series(out, "A")["points"]
    assert pts[0][0] == "2026-01-05"
    assert all(p[1] == pytest.approx(1.0) and p[2] == 1000 for p in pts)


@pytest.mark.parametrize("bought, convention", [(100.0, "as_traded"), (10.0, "adjusted")])
def test_reverse_split_detected_each_way(bought, convention):
    # 1:10 reverse split; Yahoo close is in post-split terms ($100 a share)
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", bought, -1000.0),
            _split_row(0.1)]
    splits = {"AAPL": [{"date": SPLIT_DAY, "ratio": 0.1}]}
    assert history._detect_split_convention("AAPL", txns, splits, 10.0) == convention
    out = history.run_history(_params([_acct(units=10.0)], txns, {"AAPL": _rows([100] * 5)}))
    assert "HISTORY_BREAK" not in _codes(out)
    pts = _series(out, "A")["points"]
    assert pts[0][0] == "2026-01-05"
    assert [p[2] for p in pts] == [1000] * 5  # continuous across the split date


def test_split_ratio_from_yahoo_when_row_missing():
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0)]
    splits = {"AAPL": [{"date": SPLIT_DAY, "ratio": 2.0}]}
    out = history.run_history(_params([_acct(units=20.0)], txns, FLAT50, splits=splits))
    assert "HISTORY_BREAK" not in _codes(out)
    pts = _series(out, "A")["points"]
    assert pts[0][0] == "2026-01-05"
    assert all(p[2] == 1000 for p in pts)


def test_split_ratio_from_yahoo_when_row_ratio_null():
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
            _split_row(None, date="2026-01-08")]  # broker dated it a day late, no ratio
    splits = {"AAPL": [{"date": SPLIT_DAY, "ratio": 2.0}]}
    out = history.run_history(_params([_acct(units=20.0)], txns, FLAT50, splits=splits))
    assert "HISTORY_BREAK" not in _codes(out)
    assert _series(out, "A")["start"] == "2026-01-05"


def test_split_row_units_pick_the_reading():
    # SPLIT row says 10 new shares: as traded (10 -> 20) fits, adjusted would add none
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
            _split_row(2.0, units=10.0)]
    splits = {"AAPL": [{"date": SPLIT_DAY, "ratio": 2.0, "units": 10.0}]}
    assert history._detect_split_convention("AAPL", txns, splits, 20.0) == "as_traded"


def test_ambiguous_split_breaks():
    # the SPLIT row's 7 new shares match neither reading of 10 -> 20
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
            _split_row(2.0, units=7.0)]
    out = history.run_history(_params([_acct(units=20.0)], txns, FLAT50))
    assert _series(out, "A")["start"] == "2026-01-08"
    brk = [f for f in out["flags"] if f["code"] == "HISTORY_BREAK"]
    assert len(brk) == 1
    msg = brk[0]["message"]
    assert msg.startswith("A:") and SPLIT_DAY in msg and "AAPL" in msg and "split" in msg


def test_split_without_any_ratio_breaks():
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
            _split_row(None)]
    out = history.run_history(_params([_acct(units=20.0)], txns, FLAT50))
    assert _series(out, "A")["start"] == "2026-01-08"
    assert "HISTORY_BREAK" in _codes(out)


# --- reconciliation breaks ------------------------------------------------------------


def _break_messages(out):
    return [f["message"] for f in out["flags"] if f["code"] == "HISTORY_BREAK"]


def test_missing_sell_breaks():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-07", "BUY", "AAPL", 10.0, -1000.0)]
    out = history.run_history(_params([_acct(units=0.0, cash=1000.0)], txns, prices))
    assert _series(out, "A")["start"] == "2026-01-08"
    (msg,) = _break_messages(out)
    assert msg.startswith("A:") and "2026-01-07" in msg and "AAPL" in msg and "negative units" in msg


def test_rounding_negative_units_tolerated():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-06", "BUY", "AAPL", 10.0000005, -1000.0)]
    out = history.run_history(_params([_acct(units=10.0)], txns, prices))
    assert _break_messages(out) == []
    assert _series(out, "A")["start"] == "2026-01-05"


def _unpriced_case(xyz_units):
    prices = {"AAPL": _rows([100] * 5)}
    acct = _acct(units=10.0, cash=0.0)
    acct["positions"].append({"symbol": "XYZ", "units": xyz_units, "price": 5.0})
    txns = [
        _txn("2026-01-05", "DEPOSIT", amount=1000.0 + 5.0 * xyz_units),
        _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
        {**_txn("2026-01-06", "BUY", "XYZ", xyz_units, -5.0 * xyz_units), "price": 5.0},
    ]
    return history.run_history(_params([acct], txns, prices))


def test_unpriced_small_holding_carried():
    out = _unpriced_case(1.0)  # $5 of $1005: 0.5 %
    assert "UNPRICED_HOLDING" in _codes(out)
    assert _break_messages(out) == []
    s = _series(out, "A")
    assert s["start"] == "2026-01-05"
    assert s["points"][-1][2] == 1005
    assert all(p[1] == pytest.approx(1.0) for p in s["points"])


def test_unpriced_large_holding_breaks():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [
        _txn("2026-01-05", "DEPOSIT", amount=1000.0),
        _txn("2026-01-05", "BUY", "AAPL", 9.0, -900.0),
        {**_txn("2026-01-06", "BUY", "XYZ", 20.0, -100.0), "price": 5.0},
        {**_txn("2026-01-08", "SELL", "XYZ", 20.0, 100.0), "price": 5.0},
    ]
    out = history.run_history(_params([_acct(units=9.0, cash=100.0)], txns, prices))
    assert _series(out, "A")["start"] == "2026-01-08"  # XYZ ($100 of $1000) held unpriced through 01-07
    (msg,) = _break_messages(out)
    assert "2026-01-07" in msg and "XYZ" in msg and "no price" in msg


def test_unpriced_holding_today_excludes_account():
    out = _unpriced_case(20.0)  # $100 of $1100 held today with no price
    assert [e for e in out["excluded"] if e["account_id"] == "A"] == [{"account_id": "A", "reason": "history break"}]
    assert not [s for s in out["series"] if s["key"] == "A"]
    assert "HISTORY_BREAK" in _codes(out)


def _cash_case(account_type):
    prices = {"AAPL": _rows([100] * 5)}
    txns = [
        _txn("2026-01-05", "DEPOSIT", amount=500.0),
        _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
        _txn("2026-01-07", "DEPOSIT", amount=500.0),
    ]
    acct = {**_acct(units=10.0, cash=0.0), "account_type": account_type}
    return history.run_history(_params([acct], txns, prices))


def test_negative_cash_breaks_non_margin():
    out = _cash_case("taxable")
    assert _series(out, "A")["start"] == "2026-01-08"  # undoing 01-07 leaves cash -500 at the end of 01-06
    (msg,) = _break_messages(out)
    assert "2026-01-07" in msg and "negative cash" in msg


def test_negative_cash_ok_on_margin():
    out = _cash_case("margin")
    assert _break_messages(out) == []
    assert _series(out, "A")["start"] == "2026-01-05"


def test_break_in_one_account_keeps_the_other():
    prices = {"AAPL": _rows([100] * 5), "FLAT": _rows([100] * 5)}
    a_txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-07", "BUY", "AAPL", 10.0, -1000.0)]
    b_txns = [
        _txn("2026-01-05", "DEPOSIT", amount=1000.0, account="B"),
        _txn("2026-01-05", "BUY", "FLAT", 10.0, -1000.0, account="B"),
    ]
    b = {"account_id": "B", "name": "B", "cash": 0.0, "positions": [{"symbol": "FLAT", "units": 10.0}]}
    out = history.run_history(_params([_acct(units=0.0, cash=1000.0), b], a_txns + b_txns, prices))
    assert _series(out, "A")["start"] == "2026-01-08"
    assert _series(out, "B")["start"] == "2026-01-05"
    assert out["excluded"] == []


# --- short history --------------------------------------------------------------------


def _weekdays(start, end):
    from datetime import date, timedelta

    d, out = date.fromisoformat(start), []
    while d <= date.fromisoformat(end):
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_short_history_excluded_from_combined():
    days = _weekdays("2025-11-24", "2026-01-09")
    prices = {"AAPL": _rows([100] * len(days), days=days), "FLAT": _rows([100] * len(days), days=days)}
    a_txns = [_txn("2025-11-24", "DEPOSIT", amount=1000.0), _txn("2025-11-24", "BUY", "AAPL", 10.0, -1000.0)]
    b_txns = [
        _txn("2025-12-22", "DEPOSIT", amount=1000.0, account="B"),  # 18 days before as_of
        _txn("2025-12-22", "BUY", "FLAT", 10.0, -1000.0, account="B"),
    ]
    b = {"account_id": "B", "name": "B", "cash": 0.0, "positions": [{"symbol": "FLAT", "units": 10.0}]}
    out = history.run_history(_params([_acct(), b], a_txns + b_txns, prices))
    combined = _series(out)
    assert combined["accounts"] == ["A"]
    assert combined["start"] == "2025-11-24"
    assert combined["points"][-1][2] == 1000
    assert _series(out, "B")["start"] == "2025-12-22"  # own series kept for the picker
    assert out["excluded"] == []
    short = [f["message"] for f in out["flags"] if f["code"] == "SHORT_HISTORY"]
    assert len(short) == 1 and "B" in short[0]


# --- cash-like, proxy-priced funds, aliases -------------------------------------------


def _mm_acct(units=1000.0, cash=0.0, extra=None):
    return {"account_id": "A", "name": "A", "cash": cash,
            "positions": [{"symbol": "SPAXX", "units": units, "name": "FIDELITY GOVERNMENT MONEY MARKET"}] + (extra or [])}


def test_money_market_valued_as_cash():
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0),
            _txn("2026-01-07", "DIVIDEND", "SPAXX", amount=0.0)]
    out = history.run_history(_params([_mm_acct()], txns, {"SPY": _rows([1] * 5)}))
    s = _series(out, "A")
    assert [p[2] for p in s["points"]] == [1000] * 5
    assert out["excluded"] == [] and _break_messages(out) == []


def test_money_market_sweep_rows_not_rolled():
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-06", "BUY", "SPAXX", 400.0, -400.0)]
    out = history.run_history(_params([_mm_acct()], txns, {"SPY": _rows([1] * 5)}))
    assert [p[2] for p in _series(out, "A")["points"]] == [1000] * 5


def _proxy_case(**extra):
    voo = _rows([400, 410, 420, 430, 440], adj=[400, 410, 420, 430, 440])
    acct = {"account_id": "A", "name": "A", "cash": 0.0,
            "positions": [{"symbol": "ONN5", "units": 10.0, "price": 113.48, "name": "VANG INST 500 IDX TR"}]}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "ONN5", 10.0, -1000.0)]
    return history.run_history(_params([acct], txns, {"VOO": voo}, proxies={"ONN5": "VOO"}, **extra))


def test_proxy_fund_synthetic_history():
    out = _proxy_case()
    s = _series(out, "A")
    assert s["estimated"] is True and _series(out)["estimated"] is True
    assert s["points"][0][2] == pytest.approx(10 * 113.48 / 1.10, abs=0.01)
    assert s["points"][-1][2] == pytest.approx(1134.8, abs=0.01)
    (flag,) = [f for f in out["flags"] if f["code"] == "PROXY_PRICED"]
    assert "ONN5" in flag["message"] and "VOO" in flag["message"]


def test_synthetic_prices_scale_by_adj_close_ratio():
    rows = [{"date": "2026-01-05", "close": 1, "adj_close": 50.0}, {"date": "2026-01-06", "close": 1, "adj_close": 100.0}]
    out = history._synthetic_prices(20.0, rows)
    assert [(r["date"], r["close"]) for r in out] == [("2026-01-05", 10.0), ("2026-01-06", 20.0)]


def test_listed_series_not_estimated_without_proxy():
    out = history.run_history(_params([_acct()], BASE, {"AAPL": _rows([100] * 5)}, proxies={"ONN5": "VOO"}))
    assert _series(out, "A")["estimated"] is False
    assert "PROXY_PRICED" not in _codes(out)


def test_aliases_fold_and_dedupe():
    prices = {"AAPL": _rows([100] * 5)}
    twin = [{**t, "account_id": "twin"} for t in BASE]
    out = history.run_history(_params([_acct()], BASE + twin, prices, aliases={"twin": "A"}))
    assert _break_messages(out) == []
    assert _series(out, "A")["points"][-1][2] == 1000
    assert "UNASSIGNED_ROWS" not in _codes(out)


def test_aliases_keep_genuine_repeat_trades_in_one_id():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-06", "BUY", "AAPL", 5.0, -500.0),
            _txn("2026-01-06", "BUY", "AAPL", 5.0, -500.0)]
    out = history.run_history(_params([_acct()], txns, prices, aliases={"twin": "A"}))
    assert _series(out, "A")["points"][-1][2] == 1000
    assert _break_messages(out) == []


def test_twin_only_rows_count_for_live_account():
    prices = {"AAPL": _rows([100] * 5)}
    twin = [{**t, "account_id": "twin"} for t in BASE]
    out = history.run_history(_params([_acct()], twin, prices, aliases={"twin": "A"}))
    assert _series(out, "A")["start"] == "2026-01-05"


def test_unassigned_rows_flagged_and_ignored():
    prices = {"AAPL": _rows([100] * 5)}
    stray = [_txn("2026-01-06", "BUY", "AAPL", 3.0, -300.0, account="my-csv"),
             _txn("2026-01-07", "DEPOSIT", amount=50.0, account="my-csv")]
    out = history.run_history(_params([_acct()], BASE + stray, prices))
    assert _series(out, "A")["points"][-1][2] == 1000
    (flag,) = [f for f in out["flags"] if f["code"] == "UNASSIGNED_ROWS"]
    assert "2" in flag["message"]


def test_account_without_ledger_rows_no_history():
    out = history.run_history(_params([_acct(), _acct("Z")], BASE, {"AAPL": _rows([100] * 5)}))
    (flag,) = [f for f in out["flags"] if f["code"] == "NO_HISTORY"]
    assert "statement-import" in flag["message"] and flag["message"].startswith("Z:")


# --- review follow-ups ------------------------------------------------------------------


def test_short_position_today_does_not_break():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-06", "SELL", "AAPL", 5.0, 500.0)]
    out = history.run_history(_params([_acct(units=-5.0, cash=1500.0)], txns, prices))
    assert _break_messages(out) == []
    assert _series(out, "A")["start"] == "2026-01-05"


def test_units_below_todays_short_still_break():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-06", "SELL", "AAPL", 5.0, 500.0),
            _txn("2026-01-07", "BUY", "AAPL", 20.0, -2000.0)]
    acct = {**_acct(units=-5.0, cash=-500.0), "account_type": "margin"}
    out = history.run_history(_params([acct], txns, prices))
    assert any("negative units" in m for m in _break_messages(out))


def test_relative_tolerance_branch():
    prices = {"AAPL": _rows([100] * 5)}

    def run(buy):
        txns = [_txn("2026-01-05", "DEPOSIT", amount=2000.0), _txn("2026-01-06", "BUY", "AAPL", buy, -1000.0)]
        return history.run_history(_params([_acct(units=10.0)], txns, prices))

    # peak 10 held today: -0.005 is under 0.1% of 10 (0.01); -0.02 is over
    assert _break_messages(run(10.005)) == []
    assert any("negative units" in m for m in _break_messages(run(10.02)))


def test_carry_forward_limited_to_five_trading_days():
    days = _weekdays("2026-01-05", "2026-01-23")
    closes = [100.0] * 2 + [None] * (len(days) - 2)
    prices = {"AAPL": _rows(closes, days=days), "FLAT": _rows([1.0] * len(days), days=days)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0)]
    p = _params([_acct(units=10.0)], txns, prices)
    p["as_of"] = days[-1]
    out = history.run_history(p)
    assert [e["account_id"] for e in out["excluded"]] == ["A"]  # no close for AAPL today
    assert any("no price for AAPL" in m for m in _break_messages(out))


def test_carry_within_five_days_still_works():
    days = _weekdays("2026-01-05", "2026-01-13")
    closes = [100.0, 100.0] + [None] * (len(days) - 2)  # 01-07..01-13: 5 days carried
    prices = {"AAPL": _rows(closes, days=days), "FLAT": _rows([1.0] * len(days), days=days)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0)]
    p = _params([_acct(units=10.0)], txns, prices)
    p["as_of"] = days[-1]
    out = history.run_history(p)
    assert _break_messages(out) == []


def test_bad_yahoo_split_row_dropped():
    prices = {"AAPL": _rows([100] * 5)}
    splits = {"AAPL": [{"date": SPLIT_DAY, "ratio": 0}, {"date": SPLIT_DAY}, {"date": "2026-01-08", "ratio": -2}]}
    out = history.run_history(_params([_acct()], BASE, prices, splits=splits))
    assert _break_messages(out) == []
    assert _series(out, "A")["points"][-1][2] == 1000


def test_cash_like_transfer_is_external_flow():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
            _txn("2026-01-07", "TRANSFER_IN", "SPAXX", 9000.0, None)]
    acct = {"account_id": "A", "name": "A", "cash": 0.0,
            "positions": [{"symbol": "AAPL", "units": 10.0}, {"symbol": "SPAXX", "units": 9000.0,
                                                               "name": "FIDELITY GOVERNMENT MONEY MARKET"}]}
    out = history.run_history(_params([acct], txns, prices))
    pts = {p[0]: p for p in _series(out, "A")["points"]}
    assert pts["2026-01-06"][2] == 1000  # pre-transfer value excludes the rollover
    assert pts["2026-01-07"][2] == 10000
    assert all(p[1] == pytest.approx(1.0) for p in pts.values())  # transfer day has zero return


def test_core_sweep_stock_sale_no_false_negative_cash_break():
    prices = {"AAPL": _rows([100] * 5)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
            _txn("2026-01-07", "SELL", "AAPL", 10.0, 1000.0)]
    acct = {"account_id": "A", "name": "A", "cash": 0.0, "account_type": "taxable",
            "positions": [{"symbol": "SPAXX", "units": 1000.0, "name": "FIDELITY GOVERNMENT MONEY MARKET"}]}
    out = history.run_history(_params([acct], txns, prices))
    assert _break_messages(out) == []
    assert _series(out, "A")["start"] == "2026-01-05"
    assert _series(out, "A")["points"][-1][2] == 1000


def _boundary(extra_days):
    days = _weekdays("2026-01-05", "2026-01-30")
    closes = [100.0] + [None] * (len(days) - 1)
    prices = {"AAPL": _rows(closes, days=days), "FLAT": _rows([1.0] * len(days), days=days)}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1000.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0)]
    acct = {**_acct(units=10.0), "positions": [{"symbol": "AAPL", "units": 10.0, "price": 100.0}]}
    p = _params([acct], txns, prices)
    p["as_of"] = days[extra_days]  # last real close is day 0, carried extra_days
    return history.run_history(p)


def test_carry_boundary_five_ok_six_breaks():
    ok = _boundary(5)
    assert _break_messages(ok) == [] and _series(ok, "A")["start"] == "2026-01-05"
    six = _boundary(6)  # day 6 has no close; broker price fallback makes it a >1% unpriced break
    assert any("no price for AAPL" in m for m in _break_messages(six))


# --- final review fixes ---------------------------------------------------------------


def _breaks(out):
    return [f["message"] for f in out["flags"] if f["code"] == "HISTORY_BREAK"]


SPARSE = ["2024-01-02", "2024-06-03", "2025-01-02", "2026-01-05", "2026-01-06"]


def _two_accounts(b_first):
    prices = {"AAPL": _rows([100] * 5, days=SPARSE), "VOO": _rows([50, 60, 70, 100, 100], days=SPARSE),
              "SPY": _rows([1] * 5, days=SPARSE)}
    txns = [_txn("2024-01-02", "DEPOSIT", amount=1000), _txn("2024-01-02", "BUY", "AAPL", 10, -1000),
            _txn(b_first, "DIVIDEND", "VOO", amount=5, account="B")]
    acc = [_acct(), {"account_id": "B", "name": "B", "cash": 5, "positions": [{"symbol": "VOO", "units": 10}]}]
    return history.run_history({"as_of": "2026-01-06", "accounts": acc, "transactions": txns, "prices": prices})


def test_account_series_starts_at_its_own_oldest_row():
    # reviewer's t1.py: B's only row is a 2026-01-05 dividend; it must not be drawn back to 2024 on today's units
    out = _two_accounts("2026-01-05")
    assert _series(out, "B")["start"] == "2026-01-05"
    assert _series(out)["accounts"] == ["A"]  # one day of B: short, left out of combined
    assert _series(out)["start"] == "2024-01-02"


def test_combined_start_follows_latest_own_start():
    out = _two_accounts("2025-01-02")
    assert _series(out, "B")["start"] == "2025-01-02"
    assert _series(out)["accounts"] == ["A", "B"] and _series(out)["start"] == "2025-01-02"


OPT = "AAPL260220C00200000"


def _option_case(opt_rows, cash=250.0, positions=None):
    prices = {"AAPL": _rows([100] * 4, days=DAYS[:4])}
    txns = [_txn("2026-01-05", "DEPOSIT", amount=10000), _txn("2026-01-05", "BUY", "AAPL", 97.5, -9750), *opt_rows]
    acc = [{"account_id": "A", "cash": cash, "positions": positions or [{"symbol": "AAPL", "units": 97.5}]}]
    return history.run_history({"as_of": "2026-01-08", "accounts": acc, "transactions": txns, "prices": prices})


def test_unpriced_option_valued_with_contract_multiplier():
    # reviewer's t2.py: $250 of option (2.5 %) was carried at $2.50 a contract and slipped under the 1 % rule
    out = _option_case([{**_txn("2026-01-06", "BUY", OPT, 1, -250), "price": 2.5},
                        {**_txn("2026-01-08", "SELL", OPT, 1, 250), "price": 2.5}])
    (msg,) = _breaks(out)
    assert OPT in msg and "2026-01-07" in msg and "no price" in msg
    assert _series(out, "A")["start"] == "2026-01-08"
    assert "UNPRICED_HOLDING" not in _codes(out)


def test_small_option_carried_per_contract():
    out = _option_case([{**_txn("2026-01-06", "BUY", OPT, 1, -20), "price": 0.2},
                        {**_txn("2026-01-08", "SELL", OPT, 1, 20), "price": 0.2}])
    assert _breaks(out) == []
    (msg,) = [f["message"] for f in out["flags"] if f["code"] == "UNPRICED_HOLDING"]
    assert "carried at 20 " in msg
    assert [p[2] for p in _series(out, "A")["points"]] == [10000, 10000, 10000, 10000]


def test_option_without_derivable_multiplier_breaks():
    # no price on the row, broker price per share only: the multiplier can't be derived, so never guess
    out = _option_case([_txn("2026-01-07", "BUY", OPT, 1, -20)], cash=230.0,
                       positions=[{"symbol": "AAPL", "units": 97.5}, {"symbol": OPT, "units": 1, "price": 0.2}])
    assert not [s for s in out["series"] if s["key"] == "A"]
    (msg,) = _breaks(out)
    assert OPT in msg and "contract multiplier" in msg


def test_trade_without_symbol_breaks():
    prices = {"AAPL": _rows([100] * 5)}
    txns = BASE + [_txn("2026-01-07", "SELL", None, 1.0, 100.0)]
    out = history.run_history(_params([_acct(cash=100.0)], txns, prices))
    (msg,) = _breaks(out)
    assert "trade without symbol" in msg and "2026-01-07" in msg
    assert _series(out, "A")["start"] == "2026-01-08"
    assert "OTHER_TYPES" not in _codes(out)


def test_unpriced_holdings_summed_for_the_one_percent_rule():
    # XYZ and QRS are each $6 of ~$1012 (0.6 %); together 1.2 %: a break
    prices = {"AAPL": _rows([100] * 5)}
    acct = _acct(units=10.0, cash=0.0)
    acct["positions"] += [{"symbol": "XYZ", "units": 1.0, "price": 6.0}, {"symbol": "QRS", "units": 1.0, "price": 6.0}]
    txns = [_txn("2026-01-05", "DEPOSIT", amount=1012.0), _txn("2026-01-05", "BUY", "AAPL", 10.0, -1000.0),
            {**_txn("2026-01-06", "BUY", "XYZ", 1.0, -6.0), "price": 6.0},
            {**_txn("2026-01-06", "BUY", "QRS", 1.0, -6.0), "price": 6.0}]
    out = history.run_history(_params([acct], txns, prices))
    assert not [s for s in out["series"] if s["key"] == "A"]
    assert any("no price" in m for m in _breaks(out))


def _daily(start, end):
    from datetime import date, timedelta

    d, out = date.fromisoformat(start), []
    while d <= date.fromisoformat(end):
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_headline_one_year_from_last_point_on_or_before():
    pts = [["2025-01-02", 1.0, 1], ["2025-11-17", 1.1, 1], ["2025-11-19", 1.2, 1], ["2026-11-18", 1.32, 1]]
    spy = [["2025-01-02", 1.0], ["2025-11-17", 2.0], ["2025-11-19", 2.2], ["2026-11-18", 2.5]]
    h = history._headline(pts, "2026-11-18", spy, True)
    assert h == {"range": "1Y", "start": "2025-11-17", "portfolio_return": pytest.approx(0.2),
                 "spy_return": pytest.approx(0.25), "estimated": True}


def test_headline_all_when_shorter_than_a_year_and_spy_missing():
    pts = [["2026-03-02", 1.0, 1], ["2026-11-18", 1.05, 1]]
    h = history._headline(pts, "2026-11-18", None, False)
    assert h == {"range": "All", "start": "2026-03-02", "portfolio_return": pytest.approx(0.05),
                 "spy_return": None, "estimated": False}
    # SPY with no point on or before the base day is unavailable, not re-based on a later day
    assert history._headline(pts, "2026-11-18", [["2026-03-03", 1.0], ["2026-11-18", 1.1]], False)["spy_return"] is None


def test_headline_leap_day_clamps_to_feb_28():
    pts = [["2027-02-27", 1.0, 1], ["2027-02-28", 1.1, 1], ["2027-03-01", 1.2, 1], ["2028-02-29", 1.21, 1]]
    h = history._headline(pts, "2028-02-29", None, False)
    assert h["range"] == "1Y" and h["start"] == "2027-02-28"


def test_run_history_emits_headline_per_series():
    days = _daily("2025-11-01", "2026-11-18")
    prices = {"AAPL": _rows([100.0] * len(days), days=days), "SPY": _rows([100.0 + i * 0.1 for i in range(len(days))], days=days)}
    txns = [_txn("2025-11-01", "DEPOSIT", amount=1000.0), _txn("2025-11-01", "BUY", "AAPL", 10.0, -1000.0)]
    out = history.run_history({"as_of": "2026-11-18", "accounts": [_acct()], "transactions": txns,
                               "prices": prices, "benchmarks": ["SPY"]})
    for s in out["series"]:
        h = s["headline"]
        assert h["range"] == "1Y" and h["start"] == "2025-11-18" and h["portfolio_return"] == pytest.approx(0.0)
        i = days.index("2025-11-18")
        assert h["spy_return"] == pytest.approx((100 + (len(days) - 1) * 0.1) / (100 + i * 0.1) - 1, abs=1e-5)
