from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from scripts_util import load_script, run_json

FIX = Path(__file__).resolve().parent / "fixtures" / "spending"
ITEMS = [{"name": "Food", "amount": -200, "category": "Groceries", "detail": "Groceries/Costco"}, {"name": "Paper towels", "amount": -40, "category": "Shopping", "detail": "Household/Paper", "quantity": 2}]


@pytest.fixture
def data_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    imp = load_script("spending/scripts/import-spending.py")
    for file, account in (("chase-card.csv", "chase-sapphire-1234"), ("amex.csv", "amex-gold-9876")):
        rc, out = run_json(imp, [str(FIX / file), "--account", account], capsys)
        assert rc == 0, out
    return tmp_path


def _items(capsys, *argv, stdin=None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(stdin)))
    return run_json(load_script("spending/scripts/items.py"), list(argv), capsys)


def _store(data_dir) -> dict:
    return json.loads((data_dir / "spending.json").read_text())


def test_attach_by_date_and_amount_is_ambiguous_across_two_cards(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-08-12", "--amount", "-240")
    assert rc == 2 and out["code"] == "AMBIGUOUS_MATCH" and len(out["candidates"]) == 2
    assert {c["merchant"] for c in out["candidates"]} == {"Costco"} and all({"id", "date", "amount", "account_id"} <= set(c) for c in out["candidates"])


def test_attach_by_date_amount_and_merchant_or_by_id(data_dir, capsys, tmp_path, monkeypatch) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-08-15", "--amount", "-240", "--merchant", "costco", "--source", "receipt")
    assert rc == 0, out
    assert out["matched_by"] == "date+amount+merchant" and out["items_total"] == -240.0 and out["remainder"] == 0.0 and out["replaced"] is False
    assert out["transaction"]["date"] == "2026-08-15" and out["transaction"]["account_id"] == "amex-gold-9876"
    tx = next(t for t in _store(data_dir)["transactions"] if t["id"] == out["transaction"]["id"])
    assert [i["name"] for i in tx["items"]] == ["Food", "Paper towels"] and tx["items"][0]["source"] == "receipt" and tx["items"][1]["quantity"] == 2
    rc, out = _items(capsys, "attach", "--items", "-", "--id", tx["id"], stdin=ITEMS[:1], monkeypatch=monkeypatch)
    assert rc == 0 and out["replaced"] is True and out["remainder"] == -40.0 and out["matched_by"] == "id"
    assert len(next(t for t in _store(data_dir)["transactions"] if t["id"] == tx["id"])["items"]) == 1


def test_attach_guards(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps([{"name": "x", "amount": -300, "category": "Groceries"}]))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-08-15", "--amount", "-240", "--merchant", "costco")
    assert rc == 2 and out["code"] == "INVALID_ITEMS" and "exceed" in out["error"] and out["items_total"] == -300.0 and out["transaction_amount"] == -240.0
    f.write_text(json.dumps([{"name": "x", "amount": -1, "category": "Snacks"}]))
    rc, out = _items(capsys, "attach", "--items", str(f), "--id", "t-nope")
    assert rc == 2 and out["code"] == "INVALID_ITEMS"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--id", "t-nope")
    assert rc == 2 and out["code"] == "NO_MATCH"
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240")
    assert rc == 2 and out["code"] == "NO_MATCH" and "--create" in out["error"]
    rc, out = _items(capsys, "attach", "--items", str(f))
    assert rc == 2 and "--id" in out["error"]


def test_attach_create_makes_a_transcribed_transaction(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240", "--create", "--account", "amex-gold-9876", "--description", "Costco receipt", "--merchant", "Costco", "--source", "receipt", "--dry-run")
    assert rc == 0 and out["dry_run"] is True and out["created"] is True and out["transaction"]["source"] == "transcribed:receipt"
    assert len(_store(data_dir)["transactions"]) == 11
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240", "--create", "--account", "amex-gold-9876", "--description", "Costco receipt", "--merchant", "Costco", "--source", "receipt")
    assert rc == 0 and out["created"] is True
    tx = next(t for t in _store(data_dir)["transactions"] if t["description"] == "Costco receipt")
    assert tx["merchant"] == "Costco" and tx["category"] == "Groceries" and tx["source"] == "transcribed:receipt" and len(tx["items"]) == 2
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240", "--create")
    assert rc == 2 and "--account" in out["error"]


def test_list_and_detach(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    _items(capsys, "attach", "--items", str(f), "--date", "2026-08-15", "--amount", "-240", "--merchant", "costco")
    rc, out = _items(capsys, "list")
    assert rc == 0 and out["count"] == 1 and out["transactions"][0]["merchant"] == "Costco" and out["transactions"][0]["items_total"] == -240.0 and out["transactions"][0]["source"] == "preset:amex"
    rc, out = _items(capsys, "list", "--date", "2026-08-15")
    assert rc == 0 and out["count"] == 1
    txid = out["transactions"][0]["id"]
    rc, out = _items(capsys, "list", "--id", txid)
    assert rc == 0 and [i["name"] for i in out["transactions"][0]["items"]] == ["Food", "Paper towels"]
    rc, out = _items(capsys, "detach", "--id", txid)
    assert rc == 0 and out["detached"] == 2
    assert "items" not in next(t for t in _store(data_dir)["transactions"] if t["id"] == txid)
    rc, out = _items(capsys, "detach", "--id", txid)
    assert rc == 2 and out["code"] == "NO_MATCH"


def test_no_store_exits_4(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = _items(capsys, "list")
    assert rc == 4 and out["code"] == "CONFIG_MISSING"


def test_attach_missing_items_file_is_invalid_items(data_dir, capsys, tmp_path) -> None:
    rc, out = _items(capsys, "attach", "--items", str(tmp_path / "nope.json"), "--id", "t-nope")
    assert rc == 2 and out["code"] == "INVALID_ITEMS" and "not found" in out["error"]


def test_attach_unreadable_items_file_is_invalid_items(data_dir, capsys, tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe\x00")
    rc, out = _items(capsys, "attach", "--items", str(bad), "--id", "t-nope")
    assert rc == 2 and out["code"] == "INVALID_ITEMS"


def test_attach_create_needs_account_is_invalid_input(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240", "--create")
    assert rc == 2 and out["code"] == "INVALID_INPUT" and "--account" in out["error"]


def test_attach_create_with_id_is_rejected(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--id", "t-nope", "--create", "--account", "amex-gold-9876")
    assert rc == 2 and "--create" in out["error"] and "--id" in out["error"]


def test_list_date_validates(data_dir, capsys) -> None:
    rc, out = _items(capsys, "list", "--date", "07/01/2026")
    assert rc == 2 and "--date" in out["error"]


def test_attach_create_honors_merge_dedupe_against_a_hidden_transcribed_row(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240", "--create", "--account", "amex-gold-9876", "--description", "Costco receipt", "--merchant", "Costco", "--source", "receipt")
    assert rc == 0 and out["created"] is True, out
    original_id = out["transaction"]["id"]
    before = _store(data_dir)
    tx_count_before, imports_before = len(before["transactions"]), len(before["imports"])

    f2 = tmp_path / "items2.json"
    f2.write_text(json.dumps(ITEMS[:1]))
    rc, out = _items(capsys, "attach", "--items", str(f2), "--date", "2026-07-01", "--amount", "-240", "--create", "--account", "amex-gold-9876", "--description", "Costco receipt", "--merchant", "Zzz")
    assert rc == 0, out
    assert out["created"] is False and out["matched_by"] == "existing" and out["transaction"]["id"] == original_id

    after = _store(data_dir)
    assert len(after["transactions"]) == tx_count_before
    assert len(after["imports"]) == imports_before
    tx = next(t for t in after["transactions"] if t["id"] == original_id)
    assert [i["name"] for i in tx["items"]] == ["Food"]


def test_attach_create_dry_run_previews_a_collision_as_existing(data_dir, capsys, tmp_path) -> None:
    # Finding 4: a --create --dry-run whose candidate row collides with a row already in the
    # store (same account/date/amount/description) previewed created: true, matched_by
    # "created" even though the real (non-dry) run attaches to the existing row instead.
    csv_tx_description = "COSTCO WHSE #0684 SPRINGFIELD IL"
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    before = _store(data_dir)
    csv_tx = next(t for t in before["transactions"] if t["description"] == csv_tx_description and t["date"] == "2026-08-15")
    rc, out = _items(
        capsys, "attach", "--items", str(f), "--date", "2026-08-15", "--amount", "-240", "--create", "--account", "amex-gold-9876",
        "--description", csv_tx_description, "--merchant", "Zzz", "--dry-run",
    )
    assert rc == 0, out
    assert out["created"] is False and out["matched_by"] == "existing" and out["replaced"] is False
    assert out["transaction"]["id"] == csv_tx["id"]
    assert not (data_dir / "spending.json").exists() or _store(data_dir) == before  # dry-run wrote nothing


def test_attach_create_default_description_is_the_source_kind(data_dir, capsys, tmp_path) -> None:
    # Finding 5: with neither --description nor --merchant, the description used to be built
    # as "<merchant> receipt" with merchant defaulting to the literal "Receipt", producing the
    # doubled "Receipt receipt" description and "Receipt Receipt" merchant.
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240", "--create", "--account", "amex-gold-9876")
    assert rc == 0, out
    assert out["transaction"]["description"] == "Receipt"
    assert out["transaction"]["merchant"] == "Receipt"


def test_attach_create_default_description_uses_the_given_source_kind(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240", "--create", "--account", "amex-gold-9876", "--source", "amazon-chat")
    assert rc == 0, out
    assert out["transaction"]["description"] == "Amazon-chat"


def test_attach_without_create_on_empty_store_still_exits_4(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240")
    assert rc == 4 and out["code"] == "CONFIG_MISSING"
    assert not (tmp_path / "spending.json").exists()


def test_attach_create_initializes_an_empty_store(tmp_path, monkeypatch, capsys) -> None:
    # Finding 6: --create on an empty store used to exit 4 CONFIG_MISSING; it should
    # initialize a fresh store the same way import-spending.py does.
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    assert not (tmp_path / "spending.json").exists()
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    rc, out = _items(
        capsys, "attach", "--items", str(f), "--date", "2026-07-01", "--amount", "-240", "--create", "--account", "new-account",
        "--description", "Costco receipt", "--merchant", "Costco",
    )
    assert rc == 0, out
    assert out["created"] is True
    book = json.loads((tmp_path / "spending.json").read_text())
    assert book["accounts"]["new-account"]["kind"] == "card"
    assert len(book["transactions"]) == 1


def test_attach_create_honors_merge_dedupe_against_an_imported_csv_row(data_dir, capsys, tmp_path) -> None:
    f = tmp_path / "items.json"
    f.write_text(json.dumps(ITEMS))
    before = _store(data_dir)
    tx_count_before, imports_before = len(before["transactions"]), len(before["imports"])
    csv_tx = next(t for t in before["transactions"] if t["description"] == "COSTCO WHSE #0684 SPRINGFIELD IL" and t["date"] == "2026-08-15")

    rc, out = _items(capsys, "attach", "--items", str(f), "--date", "2026-08-15", "--amount", "-240", "--create", "--account", "amex-gold-9876", "--description", "COSTCO WHSE #0684 SPRINGFIELD IL", "--merchant", "Zzz")
    assert rc == 0, out
    assert out["created"] is False and out["matched_by"] == "existing" and out["transaction"]["id"] == csv_tx["id"]

    after = _store(data_dir)
    assert len(after["transactions"]) == tx_count_before
    assert len(after["imports"]) == imports_before
