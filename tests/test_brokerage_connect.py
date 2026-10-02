from __future__ import annotations

import pytest

from fakes import READ_AUTH, TRADE_AUTH, FakeSdk, SdkError
from second_opinion import brokerage
from second_opinion.errors import ApiError


def test_create_login_url_sends_only_given_options() -> None:
    sdk = FakeSdk(login_snap_trade_user={"redirectURI": "https://app.snaptrade.com/x", "sessionId": "s"})
    assert brokerage.create_login_url(sdk) == "https://app.snaptrade.com/x"
    assert sdk.kwargs_for("login_snap_trade_user") == [{"connection_type": "trade", "immediate_redirect": False}]
    brokerage.create_login_url(sdk, broker="SANDBOX", reconnect="auth-1")
    assert sdk.kwargs_for("login_snap_trade_user")[1] == {"connection_type": "trade", "immediate_redirect": False, "broker": "SANDBOX", "reconnect": "auth-1"}


def test_wait_for_connection_returns_new_auth() -> None:
    new = {**READ_AUTH, "id": "auth-new"}
    responses = iter([[TRADE_AUTH], [TRADE_AUTH], [TRADE_AUTH, new]])
    sdk = FakeSdk(list_brokerage_authorizations=lambda **kw: next(responses))
    ticks = iter(range(0, 1000, 5))
    slept: list[float] = []
    found = brokerage.wait_for_connection(sdk, before=[TRADE_AUTH], sleep=slept.append, clock=lambda: next(ticks))
    assert found["id"] == "auth-new" and slept == [5, 5]


def test_wait_for_connection_detects_updated_existing_auth() -> None:
    updated = {**TRADE_AUTH, "updated_date": "2026-09-04T00:00:00Z"}
    sdk = FakeSdk(list_brokerage_authorizations=[updated])
    found = brokerage.wait_for_connection(sdk, before=[TRADE_AUTH], sleep=lambda s: None, clock=lambda: 0)
    assert found["id"] == "auth-trade"


def test_wait_for_connection_survives_transient_api_error() -> None:
    new = {**READ_AUTH, "id": "auth-new"}
    responses = iter([SdkError("Too many requests", 429), [TRADE_AUTH, new]])

    def flaky(**kwargs):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    sdk = FakeSdk(list_brokerage_authorizations=flaky)
    found = brokerage.wait_for_connection(sdk, before=[TRADE_AUTH], sleep=lambda s: None, clock=lambda: 0)
    assert found["id"] == "auth-new"


def test_wait_for_connection_times_out() -> None:
    sdk = FakeSdk(list_brokerage_authorizations=[TRADE_AUTH])
    ticks = iter([0, 100, 200, 301, 400])
    assert brokerage.wait_for_connection(sdk, before=[TRADE_AUTH], timeout_s=300, sleep=lambda s: None, clock=lambda: next(ticks)) is None


def test_delete_authorization() -> None:
    sdk = FakeSdk(remove_brokerage_authorization=None)
    assert brokerage.delete_authorization(sdk, "auth-1") == {"authorization_id": "auth-1", "deleted": True}
    assert sdk.kwargs_for("remove_brokerage_authorization") == [{"authorization_id": "auth-1"}]


# ── personal-key self-heal and connection-type fallback ──────────────────────


def test_call_registers_personal_user_once_on_1083_and_retries(monkeypatch) -> None:
    attempts = {"n": 0}

    def flaky(**kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise SdkError("Invalid userID or userSecret provided", 401, code="1083")
        return [TRADE_AUTH]

    sdk = FakeSdk(list_brokerage_authorizations=flaky)
    registered: list[str] = []
    monkeypatch.setattr(brokerage, "_healed", False)
    monkeypatch.setattr(brokerage, "ensure_personal_user", lambda: registered.append("x") or "snaptrade-finance-self")
    assert brokerage.list_authorizations(sdk) == [TRADE_AUTH]
    assert registered == ["x"] and attempts["n"] == 2


def test_call_does_not_loop_when_1083_persists(monkeypatch) -> None:
    sdk = FakeSdk(list_brokerage_authorizations=SdkError("Invalid userID or userSecret provided", 401, code="1083"))
    monkeypatch.setattr(brokerage, "_healed", False)
    calls: list[str] = []
    monkeypatch.setattr(brokerage, "ensure_personal_user", lambda: calls.append("x"))
    with pytest.raises(ApiError) as ei:
        brokerage.list_authorizations(sdk)
    assert ei.value.extra["snaptrade_code"] == "1083" and calls == ["x"]
    assert len(sdk.kwargs_for("list_brokerage_authorizations")) == 2


def test_ensure_personal_user_treats_duplicate_as_success(monkeypatch) -> None:
    from second_opinion import client as client_mod

    comm = FakeSdk(register_snap_trade_user=SdkError("User already exists", 400, code="1010"))
    monkeypatch.setattr(client_mod, "get_commercial_client", lambda settings=None: comm)
    assert brokerage.ensure_personal_user() == brokerage.PERSONAL_USER_ID
    assert comm.kwargs_for("register_snap_trade_user") == [{"user_id": brokerage.PERSONAL_USER_ID}]


def test_ensure_personal_user_raises_on_other_errors(monkeypatch) -> None:
    from second_opinion import client as client_mod

    comm = FakeSdk(register_snap_trade_user=SdkError("nope", 403, code="0000"))
    monkeypatch.setattr(client_mod, "get_commercial_client", lambda settings=None: comm)
    with pytest.raises(ApiError):
        brokerage.ensure_personal_user()


def test_open_connection_falls_back_to_read_when_broker_has_no_trade_type() -> None:
    def login(**kw):
        if kw.get("connection_type") == "trade":
            raise SdkError("SANDBOX does not have a trade type available", 400, code="1012")
        return {"redirectURI": "https://portal/read"}

    sdk = FakeSdk(login_snap_trade_user=login)
    out = brokerage.open_connection(sdk, broker="SANDBOX")
    assert out == {"url": "https://portal/read", "connection_type": "read", "requested_connection_type": "trade"}
    assert [kw["connection_type"] for kw in sdk.kwargs_for("login_snap_trade_user")] == ["trade", "read"]


def test_open_connection_respects_explicit_read() -> None:
    sdk = FakeSdk(login_snap_trade_user={"redirectURI": "https://portal/x"})
    out = brokerage.open_connection(sdk, connection_type="read")
    assert out["connection_type"] == "read" and sdk.kwargs_for("login_snap_trade_user")[0]["connection_type"] == "read"
