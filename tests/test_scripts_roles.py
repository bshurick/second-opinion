"""get-started/scripts/roles.py: one role per account, proposed from the account type."""
from __future__ import annotations

import pytest
from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from scripts_util import load_script, run_json
from second_opinion import client, settings
from second_opinion.brokers import router

R = "get-started/scripts/roles.py"


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH])
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


def _rows(out: dict) -> dict:
    return {r["account_id"]: r for r in out["accounts"]}


def test_roles_table_proposes_from_type(sdk, capsys) -> None:
    rc, out = run_json(load_script(R), [], capsys)
    assert rc == 0, out
    rows = _rows(out)
    assert rows["acc-1"]["proposed_role"] == "trading" and rows["acc-1"]["saved_role"] is None and rows["acc-1"]["role"] == "trading"
    assert rows["acc-2"]["proposed_role"] == "retirement" and rows["acc-2"]["role"] == "retirement"
    assert rows["acc-1"]["name"] == "Individual" and rows["acc-1"]["raw_type"] == "INDIVIDUAL"
    assert {"institution", "margin"} <= set(rows["acc-1"])
    assert settings.get("accounts.acc-1.role") is None  # showing saves nothing


def test_saved_role_wins_and_is_never_overwritten(sdk, capsys) -> None:
    settings.set_value("accounts.acc-1.role", "savings")
    rc, out = run_json(load_script(R), ["--accept"], capsys)
    assert rc == 0, out
    rows = _rows(out)
    assert rows["acc-1"]["saved_role"] == "savings" and rows["acc-1"]["role"] == "savings"
    assert settings.get("accounts.acc-1.role") == "savings"
    assert settings.get("accounts.acc-2.role") == "retirement" and rows["acc-2"]["saved_role"] == "retirement"


def test_bad_argument_exits_2(sdk, capsys) -> None:
    rc, out = run_json(load_script(R), ["--nope"], capsys)
    assert rc == 2
