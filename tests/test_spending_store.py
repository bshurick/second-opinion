"""Spending store used by the spending skill."""
from __future__ import annotations

import json

import pytest
from second_opinion import spending
from second_opinion.errors import ApiError


def _tx(account: str, date: str, amount: float, merchant: str = "Costco", fitid: str | None = None, description: str | None = None) -> dict:
    return {"account_id": account, "date": date, "post_date": None, "amount": amount, "description": description or merchant.upper(),
            "merchant": merchant, "category": "Groceries", "category_source": "keyword", "issuer_category": None,
            "type": "purchase", "transfer": False, "fitid": fitid, "source_id": "x.csv:1"}


def test_paths_honour_plugin_data_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    assert spending.spending_path() == tmp_path / "spending.json"
    assert spending.rules_path() == tmp_path / "spending-rules.json"


def test_load_missing_files_are_empty(tmp_path) -> None:
    assert spending.load(tmp_path / "spending.json") == {"accounts": {}, "transactions": [], "imports": []}
    assert spending.load_rules(tmp_path / "spending-rules.json") == {"categories": [], "merchants": [], "transfers": [], "ignore": []}


def test_load_corrupt_store_and_rules_raise(tmp_path) -> None:
    (tmp_path / "spending.json").write_text("{oops")
    with pytest.raises(ApiError) as ei:
        spending.load(tmp_path / "spending.json")
    assert ei.value.code == "SPENDING_CORRUPT" and "spending.json" in ei.value.extra["hint"]
    (tmp_path / "spending-rules.json").write_text("[]")
    with pytest.raises(ApiError) as ei:
        spending.load_rules(tmp_path / "spending-rules.json")
    assert ei.value.code == "RULES_CORRUPT"


def test_load_rules_defaults_missing_lists(tmp_path) -> None:
    p = tmp_path / "spending-rules.json"
    p.write_text(json.dumps({"categories": [{"match": "costco", "category": "Groceries"}]}))
    rules = spending.load_rules(p)
    assert rules["categories"][0]["category"] == "Groceries" and rules["merchants"] == [] and rules["ignore"] == []


def test_key_and_txid_are_stable_and_prefer_fitid() -> None:
    a = _tx("c1", "2026-08-01", -12.5)
    assert spending.key(a) == "c1|2026-08-01|-12.50|COSTCO#1"
    assert spending.txid(a) == spending.txid(dict(a)) and spending.txid(a).startswith("t-") and len(spending.txid(a)) == 14
    b = _tx("c1", "2026-08-01", -12.5, fitid="FIT123")
    assert spending.key(b) == "c1|fitid:FIT123"
    assert spending.txid(a) != spending.txid(b)


def test_key_uses_description_not_merchant_so_different_stores_are_distinct(tmp_path) -> None:
    # Same merchant, same date, same amount, different raw description (two Costco
    # registers): the dedupe key must not collapse them into one collision.
    a = _tx("c1", "2026-08-14", -240.0, merchant="Costco", description="COSTCO WHSE #0684 SPRINGFIELD IL")
    b = _tx("c1", "2026-08-14", -240.0, merchant="Costco", description="COSTCO WHSE #0120 SPRINGFIELD IL")
    assert spending.key(a) != spending.key(b)
    book = spending.load(tmp_path / "spending.json")
    added, dupes = spending.merge(book, [a, b], {"file": "amex.csv", "account_id": "c1", "preset": "amex"})
    assert (added, dupes) == (2, 0)


def test_identical_twins_in_one_batch_both_merge_via_occurrence(tmp_path) -> None:
    # Two rows with the same account, date, amount and description (a genuine same-day
    # duplicate-looking charge) both survive on their first import via occurrence 1 and 2,
    # and re-merging the identical batch dedupes both rather than adding a third.
    path = tmp_path / "spending.json"
    twin_a = _tx("c1", "2026-08-14", -5.0, merchant="Starbucks", description="STARBUCKS STORE 12345")
    twin_b = _tx("c1", "2026-08-14", -5.0, merchant="Starbucks", description="STARBUCKS STORE 12345")
    book = spending.load(path)
    added, dupes = spending.merge(book, [twin_a, twin_b], {"file": "amex.csv", "account_id": "c1", "preset": "amex"})
    assert (added, dupes) == (2, 0)
    stored = [t for t in book["transactions"] if t["merchant"] == "Starbucks"]
    assert sorted(t["occurrence"] for t in stored) == [1, 2]
    assert len({t["id"] for t in stored}) == 2
    added, dupes = spending.merge(book, [dict(twin_a), dict(twin_b)], {"file": "amex.csv", "account_id": "c1", "preset": "amex"})
    assert (added, dupes) == (0, 2)


def test_merge_dedupes_sorts_and_logs(tmp_path) -> None:
    book = spending.load(tmp_path / "spending.json")
    added, dupes = spending.merge(book, [_tx("c1", "2026-08-02", -5.0), _tx("c1", "2026-08-01", -12.5)], {"file": "a.csv", "account_id": "c1", "preset": "amex"})
    assert (added, dupes) == (2, 0)
    added, dupes = spending.merge(book, [_tx("c1", "2026-08-01", -12.5), _tx("c1", "2026-08-03", -1.0)], {"file": "a.csv", "account_id": "c1", "preset": "amex"})
    assert (added, dupes) == (1, 1)
    assert [t["date"] for t in book["transactions"]] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert all(t["id"] == spending.txid(t) for t in book["transactions"])
    assert [(i["file"], i["added"], i["duplicates"]) for i in book["imports"]] == [("a.csv", 2, 0), ("a.csv", 1, 1)]
    assert all("at" in i and i["preset"] == "amex" for i in book["imports"])


def test_same_row_in_two_accounts_is_distinct(tmp_path) -> None:
    book = spending.load(tmp_path / "spending.json")
    added, _ = spending.merge(book, [_tx("c1", "2026-08-01", -12.5), _tx("c2", "2026-08-01", -12.5)], {"file": "x", "account_id": "c1", "preset": None})
    assert added == 2


def test_save_and_reload_roundtrip(tmp_path) -> None:
    path = tmp_path / "nested" / "spending.json"
    book = spending.load(path)
    book["accounts"]["c1"] = {"id": "c1", "name": "Card", "kind": "card", "preset": "amex", "added": "2026-09-11"}
    spending.merge(book, [_tx("c1", "2026-08-01", -12.5)], {"file": "x", "account_id": "c1", "preset": "amex"})
    assert spending.save(book, path) == path
    assert spending.load(path)["accounts"]["c1"]["kind"] == "card"
    rp = tmp_path / "nested" / "spending-rules.json"
    spending.save_rules({"categories": [{"match": "x", "category": "Pets"}]}, rp)
    assert spending.load_rules(rp)["categories"] == [{"match": "x", "category": "Pets"}]


def test_statement_account_name_reads_debt_tracker_register(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    assert spending.statement_account_name("chase-sapphire-1234") is None
    (tmp_path / "statements.json").write_text(json.dumps({"accounts": {"chase-sapphire-1234": {"id": "chase-sapphire-1234", "name": "Chase Sapphire", "kind": "card"}}, "statements": [], "imports": []}))
    assert spending.statement_account_name("chase-sapphire-1234") == "Chase Sapphire"


def test_find_and_match_transactions(tmp_path) -> None:
    book = spending.load(tmp_path / "spending.json")
    book["accounts"]["c1"] = {"id": "c1", "kind": "card", "preset": "amex"}
    spending.merge(book, [_tx("c1", "2026-09-05", -240.0, "Costco"), _tx("c1", "2026-09-07", -240.3, "Costco"), _tx("c1", "2026-09-05", -26.95, "Shell")], {"file": "x", "account_id": "c1", "preset": "amex"})
    first = book["transactions"][0]
    assert spending.find_transaction(book, first["id"]) is first and spending.find_transaction(book, "t-nope") is None
    hits = spending.match_transactions(book, "2026-09-06", -240.0)
    assert [(h["date"], h["amount"]) for h in hits] == [("2026-09-05", -240.0), ("2026-09-07", -240.3)]
    assert spending.match_transactions(book, "2026-09-06", -240.0, merchant="cost") == hits
    assert spending.match_transactions(book, "2026-09-06", -240.0, merchant="shell") == []
    assert spending.match_transactions(book, "2026-09-20", -240.0) == []
    assert spending.match_transactions(book, "2026-09-05", -241.0, tolerance=0.5) == []
    assert spending.source_of(book, first) == "preset:amex"
    assert spending.source_of(book, {**first, "source": "transcribed:receipt"}) == "transcribed:receipt"
