"""Ledger store used by the statement-import and trade-review skills."""
from __future__ import annotations

import json

import pytest
from second_opinion import ledger
from second_opinion.errors import ApiError


def _e(date: str, kind: str = "BUY", symbol: str = "AAPL", units: float = 1.0, amount: float = -100.0, account: str = "a") -> dict:
    return {"date": date, "type": kind, "symbol": symbol, "units": units, "price": 100.0, "amount": amount, "fee": 0.0, "reinvested": False, "description": "x", "security_name": None, "account_id": account, "source_id": "row:1"}


def test_ledger_path_honours_plugin_data_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    assert ledger.ledger_path() == tmp_path / "ledger.json"


def test_load_missing_file_is_empty(tmp_path) -> None:
    assert ledger.load(tmp_path / "ledger.json") == {"transactions": [], "imports": []}


def test_load_corrupt_file_raises_with_hint(tmp_path) -> None:
    path = tmp_path / "ledger.json"
    path.write_text("{oops")
    with pytest.raises(ApiError) as ei:
        ledger.load(path)
    assert ei.value.code == "LEDGER_CORRUPT" and str(path) in ei.value.extra["hint"]


def test_merge_dedupes_and_records_import(tmp_path) -> None:
    book = ledger.load(tmp_path / "ledger.json")
    added, dupes = ledger.merge(book, [_e("2026-01-02"), _e("2026-01-01", "SELL", amount=100.0)], source="fid.csv")
    assert (added, dupes) == (2, 0)
    added, dupes = ledger.merge(book, [_e("2026-01-02"), _e("2026-01-03")], source="fid.csv")
    assert (added, dupes) == (1, 1)
    assert [t["date"] for t in book["transactions"]] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert [(i["source"], i["added"], i["duplicates"]) for i in book["imports"]] == [("fid.csv", 2, 0), ("fid.csv", 1, 1)]
    assert all("at" in i for i in book["imports"])


def test_merge_treats_same_trade_in_other_account_as_distinct(tmp_path) -> None:
    book = ledger.load(tmp_path / "ledger.json")
    added, _ = ledger.merge(book, [_e("2026-01-02", account="a"), _e("2026-01-02", account="b")], source="x")
    assert added == 2


def test_save_and_reload_roundtrip(tmp_path) -> None:
    path = tmp_path / "nested" / "ledger.json"
    book = ledger.load(path)
    ledger.merge(book, [_e("2026-01-02")], source="x")
    ledger.save(book, path)
    assert json.loads(path.read_text())["transactions"][0]["symbol"] == "AAPL"
    assert ledger.load(path) == book


def test_filter_by_symbol_type_and_dates() -> None:
    rows = [_e("2026-01-01"), _e("2026-02-01", "SELL", amount=100.0), _e("2026-03-01", symbol="VTI"), _e("2026-04-01", "DIVIDEND", units=None, amount=1.0)]
    assert [t["date"] for t in ledger.filter(rows, symbol="aapl")] == ["2026-01-01", "2026-02-01", "2026-04-01"]
    assert [t["date"] for t in ledger.filter(rows, kind="sell")] == ["2026-02-01"]
    assert [t["date"] for t in ledger.filter(rows, start="2026-02-01", end="2026-03-01")] == ["2026-02-01", "2026-03-01"]


def test_summary_counts() -> None:
    rows = [_e("2026-01-01"), _e("2026-02-01", "SELL", amount=100.0, account="b"), _e("2026-03-01", symbol="VTI")]
    assert ledger.summary(rows) == {
        "count": 3,
        "date_range": {"start": "2026-01-01", "end": "2026-03-01"},
        "types": {"BUY": 2, "SELL": 1},
        "accounts": {"a": 2, "b": 1},
        "symbols": ["AAPL", "VTI"],
    }
    assert ledger.summary([]) == {"count": 0, "date_range": None, "types": {}, "accounts": {}, "symbols": []}
