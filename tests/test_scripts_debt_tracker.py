from __future__ import annotations

import io
import json
import sys

import pytest
from scripts_util import load_script, run_json
from page_dom import assert_page_help, render_and_audit, requires_chrome

ACCOUNTS = {
    "chase-sapphire-1234": {"id": "chase-sapphire-1234", "name": "Chase Sapphire", "issuer": "Chase", "kind": "card", "last4": "1234", "credit_limit": 15000.0, "added": "2026-09-11"},
    "amex-gold-9876": {"id": "amex-gold-9876", "name": "Amex Gold", "issuer": "American Express", "kind": "card", "last4": "9876", "credit_limit": 10000.0, "added": "2026-09-11"},
    "sample-mortgage-5678": {"id": "sample-mortgage-5678", "name": "Sample Mortgage", "issuer": "Sample Bank", "kind": "mortgage", "last4": "5678", "credit_limit": None, "added": "2026-09-11"},
}


def _card(account, period_end, prev, payments, purchases, interest, new, minimum, due, apr=0.24, credits=0.0, limit=15000.0):
    return {"account_id": account, "period_start": None, "period_end": period_end, "previous_balance": prev, "payments": payments, "credits": credits, "purchases": purchases, "cash_advances": 0.0, "balance_transfers": 0.0, "fees": 0.0, "interest": interest, "new_balance": new, "minimum_payment": minimum, "due_date": due, "apr": apr, "credit_limit": limit, "note": None, "recorded_at": "2026-09-11T00:00:00+00:00"}


def _loan(account, period_end, prev, principal, interest, escrow, new, payment, due, apr=0.0475, term=None):
    return {"account_id": account, "period_start": None, "period_end": period_end, "previous_balance": prev, "principal_paid": principal, "interest_paid": interest, "escrow": escrow, "fees": 0.0, "new_balance": new, "payment_due": payment, "due_date": due, "apr": apr, "remaining_term_months": term, "note": None, "recorded_at": "2026-09-11T00:00:00+00:00"}


STATEMENTS = [
    _card("chase-sapphire-1234", "2026-06-14", 3000.0, 600.0, 1000.0, 50.0, 3450.0, 70.0, "2026-07-09"),
    _card("chase-sapphire-1234", "2026-07-14", 3450.0, 70.0, 500.0, 60.0, 3940.0, 80.0, "2026-08-08"),
    _card("chase-sapphire-1234", "2026-08-14", 3940.0, 80.0, 300.0, 70.0, 4230.0, 85.0, "2026-09-09"),
    _card("amex-gold-9876", "2026-08-20", 1200.0, 1200.0, 3525.0, 0.0, 3500.0, 105.0, "2026-09-15", apr=0.2899, credits=25.0, limit=10000.0),
    _loan("sample-mortgage-5678", "2026-06-25", 400000.0, 800.0, 1583.33, 600.0, 399200.0, 2983.33, "2026-08-01", term=300),
    _loan("sample-mortgage-5678", "2026-07-25", 399200.0, 802.08, 1580.17, 600.0, 398397.92, 2982.25, "2026-09-01", term=299),
]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _write(data_dir) -> None:
    (data_dir / "statements.json").write_text(json.dumps({"accounts": ACCOUNTS, "statements": STATEMENTS, "imports": []}))


def test_debts_picture_from_the_store(data_dir, capsys) -> None:
    _write(data_dir)
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), ["--as-of", "2026-09-11"], capsys)
    assert rc == 0, out
    assert out["as_of"] == "2026-09-11"
    assert out["totals"]["total_debt"] == 406127.92 and out["totals"]["weighted_apr"] == 0.0516
    assert out["totals"]["next_due"]["account_id"] == "amex-gold-9876"
    assert [r["id"] for r in out["accounts"]] == ["amex-gold-9876", "chase-sapphire-1234", "sample-mortgage-5678"]
    assert out["flags"][0] == "HIGH_UTILIZATION:amex-gold-9876"
    assert out["debt_input"]["debts"][0]["name"] == "Amex Gold"
    assert out["statements_path"].endswith("statements.json")


def test_debts_thresholds_pass_through(data_dir, capsys) -> None:
    _write(data_dir)
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), ["--as-of", "2026-09-11", "--stale-days", "60", "--utilization-warn", "0.5"], capsys)
    assert rc == 0, out
    assert out["assumptions"]["stale_days"] == 60 and out["assumptions"]["utilization_warn"] == 0.5
    assert "STALE:sample-mortgage-5678" not in out["flags"] and "HIGH_UTILIZATION:amex-gold-9876" not in out["flags"]


def test_debts_history_for_one_account(data_dir, capsys) -> None:
    _write(data_dir)
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), ["--history", "chase-sapphire-1234"], capsys)
    assert rc == 0, out
    assert out["account"]["name"] == "Chase Sapphire"
    assert [(s["period_end"], s["balance"], s["interest"], s["fees"], s["payments"], s["purchases"], s["change"]) for s in out["statements"]] == [
        ("2026-06-14", 3450.0, 50.0, 0.0, 600.0, 1000.0, None),
        ("2026-07-14", 3940.0, 60.0, 0.0, 70.0, 500.0, 490.0),
        ("2026-08-14", 4230.0, 70.0, 0.0, 80.0, 300.0, 290.0),
    ]


def test_debts_history_for_a_loan_reports_interest_paid_and_full_payment(data_dir, capsys) -> None:
    _write(data_dir)
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), ["--history", "sample-mortgage-5678"], capsys)
    assert rc == 0, out
    assert [(s["period_end"], s["balance"], s["interest"], s["payments"], s["purchases"], s["change"]) for s in out["statements"]] == [
        ("2026-06-25", 399200.0, 1583.33, 2983.33, None, None),
        ("2026-07-25", 398397.92, 1580.17, 2982.25, None, -802.08),
    ]


def test_debts_history_unknown_account_exits_2(data_dir, capsys) -> None:
    _write(data_dir)
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), ["--history", "nope"], capsys)
    assert rc == 2 and "nope" in out["error"]


def test_debts_missing_store_exits_4_with_hint(data_dir, capsys) -> None:
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), [], capsys)
    assert rc == 4 and out["code"] == "CONFIG_MISSING" and "record-statement.py" in out["hint"]


def test_debts_corrupt_store_exits_5(data_dir, capsys) -> None:
    (data_dir / "statements.json").write_text("{nope")
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), [], capsys)
    assert rc == 5 and out["code"] == "STATEMENTS_CORRUPT"


def test_debts_bad_as_of_exits_2(data_dir, capsys) -> None:
    _write(data_dir)
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), ["--as-of", "yesterday"], capsys)
    assert rc == 2 and "as_of" in out["error"]


def test_record_then_picture_end_to_end(data_dir, monkeypatch, capsys) -> None:
    """Record two card statements and one loan statement through record-statement.py, then read
    the resulting store back through debts.py -> debtpicture.py."""
    # Card A: previous 1000 - payments 1000 + purchases 500 + interest 20 = new_balance 520
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "account": {"id": "card-a", "name": "Card A", "issuer": "Bank A", "kind": "card", "last4": "1111", "credit_limit": 5000},
        "statement": {"period_end": "2026-09-01", "previous_balance": 1000.0, "payments": 1000.0, "purchases": 500.0,
                      "interest": 20.0, "new_balance": 520.0, "minimum_payment": 50.0, "due_date": "2026-09-20", "apr": 0.20},
    })))
    rc, out = run_json(load_script("debt-tracker/scripts/record-statement.py"), [], capsys)
    assert rc == 0, out

    # Card B: previous 2000 - payments 2000 + purchases 800 + interest 30 = new_balance 830
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "account": {"id": "card-b", "name": "Card B", "issuer": "Bank B", "kind": "card", "last4": "2222", "credit_limit": 8000},
        "statement": {"period_end": "2026-09-01", "previous_balance": 2000.0, "payments": 2000.0, "purchases": 800.0,
                      "interest": 30.0, "new_balance": 830.0, "minimum_payment": 60.0, "due_date": "2026-09-20", "apr": 0.22},
    })))
    rc, out = run_json(load_script("debt-tracker/scripts/record-statement.py"), [], capsys)
    assert rc == 0, out

    # Loan C: previous 10000 - principal_paid 200 = new_balance 9800; payment_due 350 includes
    # escrow 100, so debtpicture's escrow-excluded min_payment is 350 - 100 = 250.
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "account": {"id": "loan-c", "name": "Loan C", "issuer": "Lender C", "kind": "auto"},
        "statement": {"period_end": "2026-09-01", "previous_balance": 10000.0, "principal_paid": 200.0, "interest_paid": 50.0,
                      "escrow": 100.0, "new_balance": 9800.0, "payment_due": 350.0, "due_date": "2026-09-20", "apr": 0.06},
    })))
    rc, out = run_json(load_script("debt-tracker/scripts/record-statement.py"), [], capsys)
    assert rc == 0, out

    # as_of is after every due date (2026-09-20); total_debt = 520 + 830 + 9800 = 11150.0
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), ["--as-of", "2026-10-01"], capsys)
    assert rc == 0, out
    assert out["totals"]["total_debt"] == 11150.0
    assert [r["id"] for r in out["accounts"]] == ["card-a", "card-b", "loan-c"]
    debts = {d["name"]: d for d in out["debt_input"]["debts"]}
    assert len(debts) == 3
    assert debts["Loan C"]["min_payment"] == 250.0  # payment_due 350 minus escrow 100


def test_debtpicture_math_script_from_stdin(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([])))
    try:
        load_script("debt-tracker/scripts/debtpicture.py").main()
    except SystemExit as exc:
        assert exc.code == 2
    assert "error" in json.loads(capsys.readouterr().out)


def test_debts_picture_carries_the_statement_history(data_dir, capsys) -> None:
    _write(data_dir)
    rc, out = run_json(load_script("debt-tracker/scripts/debts.py"), ["--as-of", "2026-09-11"], capsys)
    assert rc == 0, out
    h = out["history"]
    assert [(r["account_id"], r["period_end"]) for r in h] == [
        ("amex-gold-9876", "2026-08-20"),
        ("chase-sapphire-1234", "2026-06-14"), ("chase-sapphire-1234", "2026-07-14"), ("chase-sapphire-1234", "2026-08-14"),
        ("sample-mortgage-5678", "2026-06-25"), ("sample-mortgage-5678", "2026-07-25"),
    ]
    assert [(r["balance"], r["interest"], r["payments"], r["purchases"], r["minimum"], r["change"]) for r in h[1:4]] == [
        (3450.0, 50.0, 600.0, 1000.0, 70.0, None), (3940.0, 60.0, 70.0, 500.0, 80.0, 490.0), (4230.0, 70.0, 80.0, 300.0, 85.0, 290.0)]
    loan = h[-1]
    assert loan["interest"] == 1580.17 and loan["payments"] == 2982.25 and loan["purchases"] is None and loan["minimum"] == 2982.25 and loan["apr"] == 0.0475 and loan["change"] == -802.08


def test_render_builds_a_self_contained_page(data_dir, capsys, tmp_path) -> None:
    _write(data_dir)
    rc, picture = run_json(load_script("debt-tracker/scripts/debts.py"), ["--as-of", "2026-09-11"], capsys)
    assert rc == 0, picture
    picture["totals"]["next_due"]["account_id"] = "amex<gold>"   # printed by the static lede: must come out escaped
    src, out = tmp_path / "debts.json", tmp_path / "page.html"
    src.write_text(json.dumps(picture))
    rc, res = run_json(load_script("debt-tracker/scripts/render.py"), ["--in", str(src), "--out", str(out)], capsys)
    assert rc == 0 and res == {"out": str(out), "title": "Debt Picture", "accounts": 3, "flags": 5}
    html = out.read_text()
    assert html.startswith("<title>Debt Picture</title>") and "<html" not in html and "<body" not in html
    assert '<p class="sub" id="lede">as of 2026-09-11 · total debt $406,127.92 · revolving $7,730.00 · installment $398,397.92 · weighted APR 5.16% · minimums $3,172.25 · next due 2026-09-15 (amex&lt;gold&gt;)</p>' in html
    assert "window.DATA = " in html and '"history"' in html and '"debt_input"' in html and '"HIGH_UTILIZATION:amex-gold-9876"' in html
    assert 'id="register"' in html and 'id="balances"' in html and 'id="util"' in html and 'id="trend-card"' in html and 'id="banner"' in html
    assert "prefers-color-scheme: dark" in html and 'data-theme="dark"' in html and "const FA" in html and "not financial advice" in html
    # glossary: the explain box and the term markers are built by JS, so the markers live in the toolkit and the calls in the SCRIPT
    assert 'id="explain"' in html and 'class="explain"' in html and 'data-term=' in html
    assert "FA.explain(" in html and "FA.term('apr'" in html and "FA.term('utilization'" in html and "FA.term('trailing 12 months', 'TTM')" in html and "Object.assign(FA.glossary, {" in html


def test_render_rejects_non_debts_input(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"totals": {}, "accounts": []}')   # a snapshot-shaped object, not a debts.py result
    rc, res = run_json(load_script("debt-tracker/scripts/render.py"), ["--in", str(bad), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "debts.py result" in res["error"]
    rc, res = run_json(load_script("debt-tracker/scripts/render.py"), ["--in", str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.html")], capsys)
    assert rc == 2 and "could not read" in res["error"]


@requires_chrome
def test_every_card_explains_itself(data_dir, capsys, tmp_path) -> None:
    _write(data_dir)
    rc, picture = run_json(load_script("debt-tracker/scripts/debts.py"), ["--as-of", "2026-09-11"], capsys)
    assert rc == 0, picture
    src = tmp_path / "debts.json"
    src.write_text(json.dumps(picture))
    assert_page_help(render_and_audit("debt-tracker/scripts/render.py", ["--in", str(src)], tmp_path, capsys))
