from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _write_ledger(data_dir, rows) -> None:
    (data_dir / "ledger.json").write_text(json.dumps({"transactions": rows, "imports": []}))


ROWS = [
    {"date": "2026-01-05", "type": "DEPOSIT", "symbol": None, "units": 0, "amount": 3000.0, "account_id": "acc-1"},
    {"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 10, "amount": -1000.0, "account_id": "acc-1"},
    {"date": "2026-01-20", "type": "FEE", "symbol": None, "units": 0, "amount": -5.0, "account_id": "acc-1"},
    {"date": "2026-02-01", "type": "DIVIDEND", "symbol": "AAPL", "units": 0, "amount": 12.5, "account_id": "acc-1"},
    {"date": "2026-02-15", "type": "WITHDRAWAL", "symbol": None, "units": 0, "amount": -500.0, "account_id": "acc-1"},
    {"date": "2026-02-20", "type": "INTEREST", "symbol": None, "units": 0, "amount": 1.5, "account_id": "acc-1"},
]


def test_cashflow_classifies_inflows_and_outflows_by_month(data_dir, capsys) -> None:
    _write_ledger(data_dir, ROWS)
    rc, out = run_json(load_script("personal-finance/scripts/cashflow.py"), [], capsys)
    assert rc == 0, out
    assert out["months"] == [
        {"month": "2026-01", "inflow": 3000.0, "outflow": 5.0, "net": 2995.0},
        {"month": "2026-02", "inflow": 14.0, "outflow": 500.0, "net": -486.0},
    ]
    assert out["avg_monthly_inflow"] == 1507.0
    assert out["avg_monthly_outflow"] == 252.5
    # total inflow 3014.0, total outflow 505.0 -> savings_rate = 2509 / 3014
    assert out["savings_rate"] == round((3014.0 - 505.0) / 3014.0, 4)


def test_cashflow_avg_balance_is_mean_of_monthly_ending_running_balance(data_dir, capsys) -> None:
    _write_ledger(data_dir, ROWS)
    rc, out = run_json(load_script("personal-finance/scripts/cashflow.py"), [], capsys)
    assert rc == 0, out
    # running balance: after Jan (3000 - 5 = 2995), after Feb (2995 + 12.5 - 500 + 1.5 = 2509.0)
    assert out["cash"]["avg_balance"] == round((2995.0 + 2509.0) / 2, 2)
    assert "investment gains" in out["cash"]["note"]


def test_cashflow_no_cash_rows_gives_null_cash_without_failing(data_dir, capsys) -> None:
    _write_ledger(
        data_dir,
        [{"date": "2026-01-10", "type": "BUY", "symbol": "AAPL", "units": 10, "amount": -1000.0, "account_id": "acc-1"}],
    )
    rc, out = run_json(load_script("personal-finance/scripts/cashflow.py"), [], capsys)
    assert rc == 0, out
    assert out["cash"] is None
    assert out["months"] == [] and out["avg_monthly_inflow"] is None and out["savings_rate"] is None


def test_cashflow_missing_ledger_file_exits_4_with_setup_hint(data_dir, capsys) -> None:
    rc, out = run_json(load_script("personal-finance/scripts/cashflow.py"), [], capsys)
    assert rc == 4 and out["code"] == "CONFIG_MISSING"
    assert "import-csv.py" in out["hint"]


def test_cashflow_empty_ledger_exits_5_ledger_empty(data_dir, capsys) -> None:
    _write_ledger(data_dir, [])
    rc, out = run_json(load_script("personal-finance/scripts/cashflow.py"), [], capsys)
    assert rc == 5 and out["code"] == "LEDGER_EMPTY"
    assert "import-csv.py" in out["hint"]


def test_cashflow_corrupt_ledger_exits_5_ledger_corrupt(data_dir, capsys) -> None:
    (data_dir / "ledger.json").write_text("{not json")
    rc, out = run_json(load_script("personal-finance/scripts/cashflow.py"), [], capsys)
    assert rc == 5 and out["code"] == "LEDGER_CORRUPT"


def test_cashflow_rejects_unexpected_arguments(data_dir, capsys) -> None:
    _write_ledger(data_dir, ROWS)
    rc, out = run_json(load_script("personal-finance/scripts/cashflow.py"), ["--bogus"], capsys)
    assert rc == 2 and out["code"] == "INVALID_INPUT"
