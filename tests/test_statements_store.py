"""Statement store used by the debt-tracker skill."""
from __future__ import annotations

import pytest
from second_opinion import statements
from second_opinion.errors import ApiError


def _snap(account: str, period_end: str, balance: float = 100.0) -> dict:
    return {"account_id": account, "period_end": period_end, "new_balance": balance}


def test_statements_path_honours_plugin_data_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    assert statements.statements_path() == tmp_path / "statements.json"


def test_load_missing_file_is_empty(tmp_path) -> None:
    assert statements.load(tmp_path / "statements.json") == {"accounts": {}, "statements": [], "imports": []}


def test_load_corrupt_file_raises_with_hint(tmp_path) -> None:
    path = tmp_path / "statements.json"
    path.write_text("{oops")
    with pytest.raises(ApiError) as ei:
        statements.load(path)
    assert ei.value.code == "STATEMENTS_CORRUPT" and str(path) in ei.value.extra["hint"]


def test_load_wrong_shape_raises(tmp_path) -> None:
    path = tmp_path / "statements.json"
    path.write_text('{"accounts": [], "statements": {}}')
    with pytest.raises(ApiError) as ei:
        statements.load(path)
    assert ei.value.code == "STATEMENTS_CORRUPT"


def test_key_is_account_and_period_end() -> None:
    assert statements.key(_snap("a", "2026-08-31")) == "a|2026-08-31"


def test_put_sorts_records_import_and_rejects_duplicates(tmp_path) -> None:
    book = statements.load(tmp_path / "statements.json")
    assert statements.put(book, _snap("b", "2026-08-31")) is False
    assert statements.put(book, _snap("a", "2026-07-31")) is False
    assert statements.put(book, _snap("a", "2026-06-30")) is False
    assert [(s["account_id"], s["period_end"]) for s in book["statements"]] == [
        ("a", "2026-06-30"), ("a", "2026-07-31"), ("b", "2026-08-31"),
    ]
    with pytest.raises(KeyError):
        statements.put(book, _snap("a", "2026-07-31", 5.0))
    assert [i["replaced"] for i in book["imports"]] == [False, False, False]
    assert all("at" in i and i["account_id"] and i["period_end"] for i in book["imports"])


def test_put_replace_swaps_the_snapshot_and_logs_it(tmp_path) -> None:
    book = statements.load(tmp_path / "statements.json")
    statements.put(book, _snap("a", "2026-07-31", 100.0))
    assert statements.put(book, _snap("a", "2026-07-31", 5.0), replace=True) is True
    assert len(book["statements"]) == 1 and book["statements"][0]["new_balance"] == 5.0
    assert book["imports"][-1]["replaced"] is True


def test_find_and_latest(tmp_path) -> None:
    book = statements.load(tmp_path / "statements.json")
    statements.put(book, _snap("a", "2026-06-30", 1.0))
    statements.put(book, _snap("a", "2026-08-31", 3.0))
    statements.put(book, _snap("a", "2026-07-31", 2.0))
    assert statements.find(book, "a", "2026-07-31")["new_balance"] == 2.0
    assert statements.find(book, "a", "2026-09-30") is None
    assert statements.latest(book, "a")["new_balance"] == 3.0
    assert statements.latest(book, "zzz") is None


def test_save_and_reload_roundtrip(tmp_path) -> None:
    path = tmp_path / "nested" / "statements.json"
    book = statements.load(path)
    book["accounts"]["a"] = {"id": "a", "kind": "card"}
    statements.put(book, _snap("a", "2026-08-31"))
    assert statements.save(book, path) == path
    again = statements.load(path)
    assert again["accounts"] == {"a": {"id": "a", "kind": "card"}}
    assert again["statements"] == book["statements"]
