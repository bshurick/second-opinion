from __future__ import annotations

import io
import json
import sys

from scripts_util import load_script


def _run_math(payload: dict, capsys, monkeypatch) -> dict:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    try:
        load_script("personal-finance/scripts/finance.py").main()
    except SystemExit:
        pass
    return json.loads(capsys.readouterr().out)


def test_amortize_with_months_solves_payment(capsys, monkeypatch) -> None:
    out = _run_math(
        {"action": "amortize", "balance": 20000, "apr": 0.07, "months": 60}, capsys, monkeypatch
    )
    assert out["payment"] == 396.02 and out["total_interest"] == 3761.48
    assert out["schedule"][-1] == {"year": 5, "interest": 175.41, "principal": 4577.12, "balance": 0.0}
    assert out["apr_vs_apy"] == {"apy_monthly": 0.0723, "apy_daily": 0.0725}


def test_amortize_with_payment_solves_payoff_months(capsys, monkeypatch) -> None:
    out = _run_math(
        {"action": "amortize", "balance": 20000, "apr": 0.07, "payment": 500}, capsys, monkeypatch
    )
    assert out["payoff_months"] == 46 and out["total_interest"] == 2841.23


def test_amortize_requires_exactly_one_of_months_or_payment(capsys, monkeypatch) -> None:
    out = _run_math({"action": "amortize", "balance": 1000, "apr": 0.05}, capsys, monkeypatch)
    assert "error" in out and "exactly one" in out["error"]


_DEBTS = [
    {"name": "Card A", "balance": 4000, "apr": 0.24, "min_payment": 120},
    {"name": "Card B", "balance": 1500, "apr": 0.18, "min_payment": 50},
]


def test_debt_avalanche_vs_snowball_ordering_and_savings(capsys, monkeypatch) -> None:
    out = _run_math(
        {"action": "debt", "debts": _DEBTS, "extra_monthly": 200, "as_of": "2026-09-01"},
        capsys,
        monkeypatch,
    )
    assert out["avalanche"]["order"] == ["Card A", "Card B"]
    assert out["snowball"]["order"] == ["Card B", "Card A"]
    assert out["interest_saved_avalanche_vs_snowball"] == 125.72


def test_compound_applies_fees_multiplicatively(capsys, monkeypatch) -> None:
    out = _run_math(
        {
            "action": "compound",
            "start_balance": 10000,
            "monthly_contribution": 500,
            "annual_return": 0.07,
            "fee_rate": 0.005,
            "years": 3,
        },
        capsys,
        monkeypatch,
    )
    assert out["final_balance"] == 31821.62 and out["total_contributions"] == 18000.0


def test_unknown_action_rejected(capsys, monkeypatch) -> None:
    out = _run_math({"action": "nope"}, capsys, monkeypatch)
    assert "error" in out
