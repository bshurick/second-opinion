from __future__ import annotations

import io
import json
import sys

import pytest
from scripts_util import load_script, run_json

SCRIPT = "debt-tracker/scripts/record-statement.py"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _run(monkeypatch, capsys, payload: dict | list, argv: list[str] | None = None):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return run_json(load_script(SCRIPT), argv or [], capsys)


CARD_ACCOUNT = {"id": "chase-sapphire-1234", "name": "Chase Sapphire", "issuer": "Chase", "kind": "card", "last4": "1234", "credit_limit": 15000}
CARD_STATEMENT = {
    "period_start": "2026-07-15", "period_end": "2026-08-14", "previous_balance": 2400.10, "payments": 2400.10,
    "credits": 35.00, "purchases": 1810.55, "interest": 0, "new_balance": 1775.55, "minimum_payment": 40.00,
    "due_date": "2026-09-09", "apr": 0.2424,
}
LOAN_ACCOUNT = {"id": "sample-mortgage-5678", "name": "Sample Mortgage", "issuer": "Sample Bank", "kind": "mortgage", "last4": "5678"}
LOAN_STATEMENT = {
    "period_end": "2026-08-31", "previous_balance": 420000.00, "principal_paid": 700.00, "interest_paid": 1662.50,
    "escrow": 500.00, "new_balance": 419300.00, "payment_due": 2862.50, "due_date": "2026-10-01", "apr": 0.0475,
    "remaining_term_months": 318,
}
HELOC_ACCOUNT = {"id": "home-line-0001", "name": "Home Line", "issuer": "Bank", "kind": "heloc", "last4": "0001", "credit_limit": 50000}
HELOC_STATEMENT = {
    # loan-shaped: previous - principal_paid = new_balance (52500 - 500 = 52000), over the 50000 limit.
    "period_end": "2026-08-31", "previous_balance": 52500.0, "principal_paid": 500.0, "interest_paid": 200.0,
    "new_balance": 52000.0, "payment_due": 300.0, "due_date": "2026-09-25", "apr": 0.08,
}


def _stored(data_dir) -> dict:
    return json.loads((data_dir / "statements.json").read_text())


def test_first_use_creates_the_account_and_stores_the_card_snapshot(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    assert rc == 0, out
    assert out["account"]["id"] == "chase-sapphire-1234" and out["account"]["added"]
    snap = out["snapshot"]
    assert snap["account_id"] == "chase-sapphire-1234" and snap["period_end"] == "2026-08-14"
    assert snap["cash_advances"] == 0.0 and snap["balance_transfers"] == 0.0 and snap["fees"] == 0.0
    assert snap["credit_limit"] == 15000.0 and snap["note"] is None and snap["recorded_at"]
    assert snap["apr"] == 0.2424
    assert out["flags"] == [] and out["statements_for_account"] == 1 and out["previous_period_end"] is None
    book = _stored(data_dir)
    assert book["accounts"]["chase-sapphire-1234"]["credit_limit"] == 15000.0
    assert len(book["statements"]) == 1 and book["imports"][0]["replaced"] is False
    assert book["statements"][0]["apr"] == 0.2424


def test_loan_snapshot_identity_and_defaults(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": LOAN_ACCOUNT, "statement": {**LOAN_STATEMENT, "escrow": None}})
    assert rc == 0, out
    assert out["snapshot"]["escrow"] == 0.0 and out["snapshot"]["fees"] == 0.0
    assert out["snapshot"]["remaining_term_months"] == 318 and out["snapshot"]["credit_limit"] is None
    assert "minimum_payment" not in out["snapshot"] and out["snapshot"]["payment_due"] == 2862.5
    assert out["snapshot"]["apr"] == 0.0475
    book = _stored(data_dir)
    assert book["statements"][0]["apr"] == 0.0475


def test_bare_snapshot_accepted_once_account_exists(data_dir, monkeypatch, capsys) -> None:
    _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    nxt = {**CARD_STATEMENT, "account_id": "chase-sapphire-1234", "period_start": "2026-08-15", "period_end": "2026-09-14",
           "previous_balance": 1775.55, "payments": 1775.55, "credits": 0, "purchases": 900.00, "new_balance": 900.00,
           "due_date": "2026-10-09"}
    rc, out = _run(monkeypatch, capsys, nxt)
    assert rc == 0, out
    assert out["statements_for_account"] == 2 and out["previous_period_end"] == "2026-08-14" and out["flags"] == []


def test_unknown_account_without_block_is_rejected(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, {**CARD_STATEMENT, "account_id": "ghost-0000"})
    assert rc == 2 and out["code"] == "INVALID_ACCOUNT" and "ghost-0000" in out["error"]


@pytest.mark.parametrize("bad", [
    {"id": "Bad Slug!"},
    {"kind": "crypto"},
    {"last4": "12345"},
    {"last4": "12ab"},
])
def test_bad_account_block_is_rejected(data_dir, monkeypatch, capsys, bad) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": {**CARD_ACCOUNT, **bad}, "statement": CARD_STATEMENT})
    assert rc == 2 and out["code"] == "INVALID_ACCOUNT"


def test_kind_cannot_change_once_statements_exist(data_dir, monkeypatch, capsys) -> None:
    _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    rc, out = _run(monkeypatch, capsys, {"account": {**CARD_ACCOUNT, "kind": "heloc"}, "statement": {**CARD_STATEMENT, "period_end": "2026-09-14", "due_date": "2026-10-09"}})
    assert rc == 2 and out["code"] == "INVALID_ACCOUNT" and "kind" in out["error"]


def test_account_block_updates_name_and_limit_but_not_added(data_dir, monkeypatch, capsys) -> None:
    _, first = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    rc, out = _run(monkeypatch, capsys, {"account": {**CARD_ACCOUNT, "name": "Sapphire Preferred", "credit_limit": 20000},
                                         "statement": {**CARD_STATEMENT, "period_end": "2026-09-14", "due_date": "2026-10-09", "previous_balance": 1775.55, "payments": 1775.55, "credits": 0, "purchases": 10, "new_balance": 10}})
    assert rc == 0, out
    assert out["account"]["name"] == "Sapphire Preferred" and out["account"]["credit_limit"] == 20000.0
    assert out["account"]["added"] == first["account"]["added"]


def test_missing_required_field(data_dir, monkeypatch, capsys) -> None:
    stmt = {k: v for k, v in CARD_STATEMENT.items() if k != "minimum_payment"}
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": stmt})
    assert rc == 2 and out["code"] == "MISSING_FIELD" and "minimum_payment" in out["error"]


def test_card_balance_mismatch_reports_the_delta(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": {**CARD_STATEMENT, "new_balance": 1775.00}})
    assert rc == 2 and out["code"] == "BALANCE_MISMATCH"
    assert out["expected"] == 1775.55 and out["got"] == 1775.0 and out["delta"] == -0.55
    assert not (data_dir / "statements.json").exists()


def test_loan_balance_mismatch(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": LOAN_ACCOUNT, "statement": {**LOAN_STATEMENT, "principal_paid": 687.66}})
    assert rc == 2 and out["code"] == "BALANCE_MISMATCH" and out["expected"] == 419312.34 and out["delta"] == -12.34


def test_identity_tolerates_one_cent(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": {**CARD_STATEMENT, "new_balance": 1775.56}})
    assert rc == 0, out


def test_duplicate_period_rejected_and_replace_accepted(data_dir, monkeypatch, capsys) -> None:
    _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    assert rc == 2 and out["code"] == "DUPLICATE_STATEMENT" and out["existing"]["period_end"] == "2026-08-14"
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": {**CARD_STATEMENT, "minimum_payment": 45}}, ["--replace"])
    assert rc == 0, out
    assert out["replaced"] is True and out["snapshot"]["minimum_payment"] == 45.0
    book = _stored(data_dir)
    assert len(book["statements"]) == 1 and book["imports"][-1]["replaced"] is True


def test_duplicate_statement_is_reported_before_sanity_checks(data_dir, monkeypatch, capsys) -> None:
    _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": {**CARD_STATEMENT, "apr": 24.24}})
    assert rc == 2 and out["code"] == "DUPLICATE_STATEMENT"


def test_dry_run_validates_without_writing(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT}, ["--dry-run"])
    assert rc == 0 and out["dry_run"] is True and out["valid"] is True and out["snapshot"]["new_balance"] == 1775.55
    assert not (data_dir / "statements.json").exists()
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": {**CARD_STATEMENT, "new_balance": 1.0}}, ["--dry-run"])
    assert rc == 2 and out["code"] == "BALANCE_MISMATCH"


def test_chain_gap_and_over_limit_are_flags_not_rejections(data_dir, monkeypatch, capsys) -> None:
    _run(monkeypatch, capsys, {"account": {**CARD_ACCOUNT, "credit_limit": 2000}, "statement": CARD_STATEMENT})
    nxt = {**CARD_STATEMENT, "account_id": "chase-sapphire-1234", "period_end": "2026-09-14", "due_date": "2026-10-09",
           "previous_balance": 1700.00, "payments": 0, "credits": 0, "purchases": 400.00, "interest": 30.00, "new_balance": 2130.00}
    rc, out = _run(monkeypatch, capsys, nxt)
    assert rc == 0, out
    assert out["flags"] == [
        {"flag": "CHAIN_GAP", "previous_new_balance": 1775.55, "this_previous_balance": 1700.0, "previous_period_end": "2026-08-14"},
        {"flag": "OVER_LIMIT", "credit_limit": 2000.0, "new_balance": 2130.0},
    ]


@pytest.mark.parametrize("field,value,needle", [
    ("apr", 24.24, "apr"),
    ("minimum_payment", -1, "minimum_payment"),
    ("due_date", "2026-08-01", "due_date"),
    ("period_end", "08/14/2026", "period_end"),
])
def test_sanity_checks(data_dir, monkeypatch, capsys, field, value, needle) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": {**CARD_STATEMENT, field: value}})
    assert rc == 2 and needle in out["error"]


def test_heloc_over_limit_flag_keys_off_revolving_kind(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, {"account": HELOC_ACCOUNT, "statement": HELOC_STATEMENT})
    assert rc == 0, out
    assert out["flags"] == [{"flag": "OVER_LIMIT", "credit_limit": 50000.0, "new_balance": 52000.0}]


def test_card_credit_balance_is_allowed(data_dir, monkeypatch, capsys) -> None:
    stmt = {**CARD_STATEMENT, "payments": 2400.10, "credits": 100.00, "purchases": 0, "new_balance": -100.00}
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": stmt})
    assert rc == 0, out


def test_accounts_subcommand_lists_latest_balances(data_dir, monkeypatch, capsys) -> None:
    _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    _run(monkeypatch, capsys, {"account": LOAN_ACCOUNT, "statement": LOAN_STATEMENT})
    rc, out = run_json(load_script(SCRIPT), ["accounts"], capsys)
    assert rc == 0, out
    assert [(a["id"], a["kind"], a["latest_period_end"], a["latest_balance"], a["statements"]) for a in out["accounts"]] == [
        ("chase-sapphire-1234", "card", "2026-08-14", 1775.55, 1),
        ("sample-mortgage-5678", "mortgage", "2026-08-31", 419300.0, 1),
    ]
    assert out["statements_path"].endswith("statements.json")


def test_corrupt_store_exits_5(data_dir, monkeypatch, capsys) -> None:
    (data_dir / "statements.json").write_text("{nope")
    rc, out = _run(monkeypatch, capsys, {"account": CARD_ACCOUNT, "statement": CARD_STATEMENT})
    assert rc == 5 and out["code"] == "STATEMENTS_CORRUPT"


def test_non_object_stdin_exits_2(data_dir, monkeypatch, capsys) -> None:
    rc, out = _run(monkeypatch, capsys, [1, 2])
    assert rc == 2 and "object" in out["error"]
