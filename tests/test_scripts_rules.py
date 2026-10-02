from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts_util import load_script, run_json

FIX = Path(__file__).resolve().parent / "fixtures" / "spending"


@pytest.fixture
def data_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = run_json(load_script("spending/scripts/import-spending.py"), [str(FIX / "chase-card.csv"), "--account", "chase-sapphire-1234"], capsys)
    assert rc == 0, out
    return tmp_path


def _rules(capsys, *argv):
    return run_json(load_script("spending/scripts/rules.py"), list(argv), capsys)


def _store(data_dir) -> dict:
    return json.loads((data_dir / "spending.json").read_text())


def test_add_category_rule_applies_and_reports(data_dir, capsys) -> None:
    rc, out = _rules(capsys, "add", "category", "--match", "netflix", "--category", "Subscriptions", "--note", "streaming")
    assert rc == 0, out
    assert out["added"] == {"match": "netflix", "category": "Subscriptions", "note": "streaming"} and out["changed"] == 1
    assert out["by_category"]["Subscriptions"] == 1
    rules = json.loads((data_dir / "spending-rules.json").read_text())
    assert rules["categories"] == [{"match": "netflix", "category": "Subscriptions", "note": "streaming"}]
    assert next(t for t in _store(data_dir)["transactions"] if t["merchant"] == "Netflix")["category"] == "Subscriptions"


def test_add_merchant_transfer_ignore_rules(data_dir, capsys) -> None:
    rc, out = _rules(capsys, "add", "merchant", "--match", "bella vista", "--merchant", "Bella Vista Restaurant")
    assert rc == 0 and out["changed"] == 1
    rc, out = _rules(capsys, "add", "transfer", "--match", "^target")
    assert rc == 0 and out["changed"] == 1
    assert next(t for t in _store(data_dir)["transactions"] if t["merchant"] == "Target")["transfer"] is True
    rc, out = _rules(capsys, "add", "ignore", "--match", "^interest charge")
    assert rc == 0 and out["removed_rows"] == 1 and len(_store(data_dir)["transactions"]) == 5


def test_add_rejects_bad_regex_unknown_category_and_missing_args(data_dir, capsys) -> None:
    rc, out = _rules(capsys, "add", "category", "--match", "(", "--category", "Pets")
    assert rc == 2 and "regex" in out["error"]
    rc, out = _rules(capsys, "add", "category", "--match", "dog", "--category", "Dogs")
    assert rc == 2 and "category" in out["error"]
    rc, out = _rules(capsys, "add", "merchant", "--match", "x")
    assert rc == 2 and "merchant" in out["error"]
    rc, out = _rules(capsys, "add", "wallet", "--match", "x")
    assert rc == 2


@pytest.mark.parametrize("category", ["Transfer", "Income", "Uncategorized"])
def test_add_category_rejects_non_spend_labels(data_dir, capsys, category) -> None:
    rc, out = _rules(capsys, "add", "category", "--match", "bella vista", "--category", category)
    assert rc == 2
    assert "add transfer" in out["error"] and "add ignore" in out["error"]
    rules_path = data_dir / "spending-rules.json"
    assert not rules_path.exists() or json.loads(rules_path.read_text())["categories"] == []


def test_list_and_remove(data_dir, capsys) -> None:
    _rules(capsys, "add", "category", "--match", "netflix", "--category", "Subscriptions")
    _rules(capsys, "add", "category", "--match", "costco", "--category", "Shopping")
    rc, out = _rules(capsys, "list")
    assert rc == 0 and [r["match"] for r in out["categories"]] == ["netflix", "costco"] and out["merchants"] == []
    rc, out = _rules(capsys, "remove", "category", "0")
    assert rc == 0 and out["removed"]["match"] == "netflix" and out["changed"] == 1
    assert out["removed_rows"] == 0
    assert next(t for t in _store(data_dir)["transactions"] if t["merchant"] == "Netflix")["category"] == "Utilities"
    rc, out = _rules(capsys, "remove", "category", "5")
    assert rc == 2


def test_apply_dry_run_lists_changes_without_writing(data_dir, capsys) -> None:
    (data_dir / "spending-rules.json").write_text(json.dumps({"categories": [{"match": "netflix", "category": "Subscriptions"}]}))
    rc, out = _rules(capsys, "apply", "--dry-run")
    assert rc == 0 and out["dry_run"] is True and out["changed"] == 1
    assert out["changes"][0]["merchant"] == "Netflix" and out["changes"][0]["category"] == {"from": "Utilities", "to": "Subscriptions"}
    assert next(t for t in _store(data_dir)["transactions"] if t["merchant"] == "Netflix")["category"] == "Utilities"
    rc, out = _rules(capsys, "apply")
    assert rc == 0 and out["changed"] == 1
    assert next(t for t in _store(data_dir)["transactions"] if t["merchant"] == "Netflix")["category"] == "Subscriptions"


def test_apply_with_no_store_exits_4(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    rc, out = _rules(capsys, "apply")
    assert rc == 4 and out["code"] == "CONFIG_MISSING"
    rc, out = _rules(capsys, "add", "category", "--match", "x", "--category", "Pets")
    assert rc == 0 and out["changed"] == 0   # rules can be added before any import


def test_add_category_rule_with_detail(data_dir, capsys) -> None:
    rc, out = _rules(capsys, "add", "category", "--match", "costco", "--category", "Groceries", "--detail", " Groceries / Costco ")
    assert rc == 0, out
    assert out["added"] == {"match": "costco", "category": "Groceries", "detail": "Groceries/Costco"} and out["changed"] == 1
    costco = next(t for t in _store(data_dir)["transactions"] if t["merchant"] == "Costco")
    assert costco["detail"] == "Groceries/Costco" and costco["detail_source"] == "rule"
    assert out["changes"][0]["detail"] == {"from": None, "to": "Groceries/Costco"}
    rc, out = _rules(capsys, "add", "category", "--match", "costco", "--category", "Groceries", "--detail", "a//b")
    assert rc == 2 and "detail" in out["error"]
    rc, out = _rules(capsys, "add", "merchant", "--match", "costco", "--merchant", "Costco", "--detail", "x")
    assert rc == 2 and "--detail" in out["error"]
