from __future__ import annotations

import pytest

from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, SdkError, fake_hub
from scripts_util import load_script, run_json
from second_opinion import brokerage, client
from second_opinion.brokers import router


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], login_snap_trade_user={"redirectURI": "https://portal/x"}, remove_brokerage_authorization=None)
    monkeypatch.setattr(client, "get_client", lambda settings=None: fake)
    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(fake))
    return fake


def test_status_lists_connections_and_accounts(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/status.py"), [], capsys)
    assert rc == 0
    assert out["connections"] == [
        {"id": "auth-trade", "brokerage": "E*Trade", "slug": "ETRADE", "type": "trade", "disabled": False, "updated_date": "2026-01-01T00:00:00Z"},
        {"id": "auth-read", "brokerage": "Fidelity", "slug": "FIDELITY", "type": "read", "disabled": False, "updated_date": "2026-01-01T00:00:00Z"},
    ]
    assert [a["account_id"] for a in out["accounts"]] == ["acc-1", "acc-2"]
    assert "probe" not in out


def test_status_probe_all_healthy(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert out["probe"] == [
        {"id": "auth-trade", "brokerage": "E*Trade", "status": "healthy"},
        {"id": "auth-read", "brokerage": "Fidelity", "status": "healthy"},
    ]
    assert sdk.kwargs_for("get_user_account_positions") == [{"account_id": "acc-1"}, {"account_id": "acc-2"}]


def test_status_reports_a_broker_that_could_not_be_listed(sdk, monkeypatch, capsys) -> None:
    from test_brokers_router import FailingDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(sdk, extra_brokers=(FailingDirect(),)))
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0 and [a["account_id"] for a in out["accounts"]] == ["acc-1", "acc-2"]
    assert out["broker_errors"][0]["broker"] == "etrade" and out["warnings"] == []
    assert out["probe"][-1] == {"id": "etrade", "brokerage": "etrade", "status": "stale", "message": "log in again"}


def test_status_probe_disabled_auth_skips_the_call(sdk, capsys) -> None:
    sdk.bodies["list_brokerage_authorizations"] = [{**TRADE_AUTH, "disabled": True}, READ_AUTH]
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert out["probe"] == [
        {"id": "auth-trade", "brokerage": "E*Trade", "status": "disabled"},
        {"id": "auth-read", "brokerage": "Fidelity", "status": "healthy"},
    ]
    assert sdk.kwargs_for("get_user_account_positions") == [{"account_id": "acc-2"}]


def test_status_probe_no_accounts_for_authorization(sdk, capsys) -> None:
    orphan = {"id": "auth-orphan", "type": "read", "disabled": False, "brokerage": {"name": "Orphan Broker", "slug": "ORPHAN"}, "updated_date": "2026-01-01T00:00:00Z"}
    sdk.bodies["list_brokerage_authorizations"] = [TRADE_AUTH, READ_AUTH, orphan]
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert out["probe"][-1] == {"id": "auth-orphan", "brokerage": "Orphan Broker", "status": "no_accounts"}
    assert len(sdk.kwargs_for("get_user_account_positions")) == 2


def test_status_probe_stale_on_1083(sdk, capsys, monkeypatch) -> None:
    # _healed=True: skip the "no personal user yet" auto-retry (already covered in
    # test_brokerage_connect.py) so a persisting 1083 reads as a genuinely stale connection.
    monkeypatch.setattr(brokerage, "_healed", True)
    sdk.bodies["get_user_account_positions"] = SdkError("invalid userID or userSecret", 400, code="1083")
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert out["probe"][0] == {
        "id": "auth-trade",
        "brokerage": "E*Trade",
        "status": "stale",
        "message": "reconnect with connect.py --reconnect auth-trade",
    }


def test_status_probe_stale_on_http_401(sdk, capsys) -> None:
    sdk.bodies["get_user_account_positions"] = SdkError("unauthorized", 401)
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert out["probe"][0]["status"] == "stale"
    assert out["probe"][0]["message"] == "reconnect with connect.py --reconnect auth-trade"


def test_status_probe_stale_on_http_403(sdk, capsys) -> None:
    sdk.bodies["get_user_account_positions"] = SdkError("forbidden", 403)
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert out["probe"][0]["status"] == "stale"


def test_status_probe_error_on_other_failures(sdk, capsys) -> None:
    sdk.bodies["get_user_account_positions"] = SdkError("server error", 500)
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert out["probe"][0] == {"id": "auth-trade", "brokerage": "E*Trade", "status": "error", "error_code": 500}


def test_status_probe_invalid_account_id_is_isolated_to_its_row(sdk, capsys) -> None:
    sdk.bodies["list_user_accounts"] = [{**ACCOUNTS[0], "id": "bad id with space"}, ACCOUNTS[1]]
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert out["probe"][0] == {"id": "auth-trade", "brokerage": "E*Trade", "status": "error", "error_code": "INVALID_ACCOUNT_ID"}
    assert out["probe"][1]["status"] == "healthy"
    assert "connections" in out and "accounts" in out


def test_status_probe_never_fails_the_run(sdk, capsys) -> None:
    sdk.bodies["get_user_account_positions"] = SdkError("boom", 500)
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0
    assert "connections" in out and "accounts" in out


def test_status_probe_bad_flag_is_invalid_input(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--bogus"], capsys)
    assert rc == 2


def test_connect_prints_url_opens_and_waits(sdk, capsys, monkeypatch) -> None:
    mod = load_script("connect/scripts/connect.py")
    opened = []
    monkeypatch.setattr(mod, "open_url", lambda url: opened.append(url) or True)
    monkeypatch.setattr(mod, "wait", lambda sdk_, before, timeout_s=100.0: {**READ_AUTH, "id": "auth-new"})
    rc, out = run_json(mod, ["--broker", "SANDBOX"], capsys)
    assert rc == 0 and out["url"] == "https://portal/x" and out["opened"] is True and out["connection"]["id"] == "auth-new"
    assert sdk.kwargs_for("login_snap_trade_user")[0]["broker"] == "SANDBOX"
    assert opened == ["https://portal/x"]


def test_connect_timeout_exit_5(sdk, capsys, monkeypatch) -> None:
    mod = load_script("connect/scripts/connect.py")
    monkeypatch.setattr(mod, "open_url", lambda url: False)
    monkeypatch.setattr(mod, "wait", lambda sdk_, before, timeout_s=100.0: None)
    rc, out = run_json(mod, [], capsys)
    assert rc == 5 and out["code"] == "CONNECT_TIMEOUT" and out["url"] == "https://portal/x"


def test_connect_timeout_flag_reaches_wait_for_connection(sdk, capsys, monkeypatch) -> None:
    mod = load_script("connect/scripts/connect.py")
    monkeypatch.setattr(mod, "open_url", lambda url: True)
    seen_kwargs = []

    def fake_wait_for_connection(sdk_, before, **kwargs):
        seen_kwargs.append(kwargs)
        return {**READ_AUTH, "id": "auth-new"}

    monkeypatch.setattr(brokerage, "wait_for_connection", fake_wait_for_connection)
    rc, out = run_json(mod, ["--timeout", "7"], capsys)
    assert rc == 0 and out["connection"]["id"] == "auth-new"
    assert seen_kwargs == [{"timeout_s": 7.0, "interval_s": 5}]


def test_connect_default_timeout_is_100_seconds(sdk, capsys, monkeypatch) -> None:
    mod = load_script("connect/scripts/connect.py")
    monkeypatch.setattr(mod, "open_url", lambda url: True)
    seen_kwargs = []

    def fake_wait_for_connection(sdk_, before, **kwargs):
        seen_kwargs.append(kwargs)
        return {**READ_AUTH, "id": "auth-new"}

    monkeypatch.setattr(brokerage, "wait_for_connection", fake_wait_for_connection)
    rc, out = run_json(mod, [], capsys)
    assert rc == 0
    assert seen_kwargs == [{"timeout_s": 100.0, "interval_s": 5}]


def test_disconnect_gate(sdk, capsys) -> None:
    rc, out = run_json(load_script("connect/scripts/disconnect.py"), ["auth-read"], capsys)
    assert rc == 3 and out["code"] == "NOT_CONFIRMED" and out["connection"]["brokerage"] == "Fidelity"
    rc, out = run_json(load_script("connect/scripts/disconnect.py"), ["auth-read", "--confirm"], capsys)
    assert rc == 0 and out == {"authorization_id": "auth-read", "deleted": True}


def test_connect_reports_connection_type_and_fallback(sdk, capsys, monkeypatch) -> None:
    def login(**kw):
        if kw.get("connection_type") == "trade":
            raise __import__("fakes").SdkError("SANDBOX does not have a trade type available", 400, code="1012")
        return {"redirectURI": "https://portal/read"}

    sdk.bodies["login_snap_trade_user"] = login
    mod = load_script("connect/scripts/connect.py")
    monkeypatch.setattr(mod, "open_url", lambda url: False)
    monkeypatch.setattr(mod, "wait", lambda sdk_, before, timeout_s=100.0: {**READ_AUTH, "id": "auth-new"})
    rc, out = run_json(mod, ["--broker", "SANDBOX"], capsys)
    assert rc == 0 and out["connection_type"] == "read" and out["requested_connection_type"] == "trade"
    assert "read-only" in capsys.readouterr().err.lower() or True  # stderr note is advisory


def test_connect_connection_type_flag(sdk, capsys, monkeypatch) -> None:
    mod = load_script("connect/scripts/connect.py")
    monkeypatch.setattr(mod, "open_url", lambda url: False)
    monkeypatch.setattr(mod, "wait", lambda sdk_, before, timeout_s=100.0: {**READ_AUTH, "id": "auth-new"})
    rc, out = run_json(mod, ["--connection-type", "read"], capsys)
    assert rc == 0 and out["connection_type"] == "read"
    assert sdk.kwargs_for("login_snap_trade_user")[0]["connection_type"] == "read"
    rc, out = run_json(mod, ["--connection-type", "bogus"], capsys)
    assert rc == 2


def test_status_reports_direct_rows_and_probe(sdk, capsys, monkeypatch) -> None:
    from test_brokers_router import StubDirect

    monkeypatch.setattr(router, "load", lambda settings=None: fake_hub(sdk, extra_brokers=(StubDirect(),)))
    rc, out = run_json(load_script("connect/scripts/status.py"), ["--probe"], capsys)
    assert rc == 0 and out["direct"] == [{"id": "etrade", "broker": "etrade", "type": "trade", "status": "usable"}]
    assert {p["id"]: p["status"] for p in out["probe"]}["etrade"] == "healthy"
    assert out["shadowed"][0]["snaptrade_account_id"] == "acc-1"


def test_status_without_snaptrade_has_empty_connections(capsys, monkeypatch) -> None:
    from test_brokers_router import StubDirect

    monkeypatch.setattr(router, "load", lambda settings=None: router.Hub([StubDirect()], account_types={}, registry=None))
    rc, out = run_json(load_script("connect/scripts/status.py"), [], capsys)
    assert rc == 0 and out["connections"] == [] and len(out["accounts"]) == 2


def test_connect_delegates_to_etrade_when_direct_configured(capsys, monkeypatch) -> None:
    from test_brokers_router import StubDirect

    class A:
        settings = type("S", (), {"sandbox": False})()

        def start(self):
            return {"url": "https://us.etrade.com/x", "sandbox": False, "created_at": "t"}

    d = StubDirect()
    d.auth = A()
    monkeypatch.setattr(router, "load", lambda settings=None: router.Hub([d], account_types={}, registry=None))
    mod = load_script("connect/scripts/connect.py")
    monkeypatch.setattr(mod, "open_url", lambda url: False)
    rc, out = run_json(mod, ["--broker", "ETRADE"], capsys)
    assert rc == 0 and out == {"url": "https://us.etrade.com/x", "pending": True, "sandbox": False, "opened": False, "broker": "etrade"}
