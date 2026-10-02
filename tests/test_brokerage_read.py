from __future__ import annotations

import pytest

from fakes import ACCOUNTS, ACCOUNTS_WITH_CLOSED, READ_AUTH, TRADE_AUTH, FakeSdk, SdkError
from second_opinion import brokerage
from second_opinion.errors import ApiError, InvalidInput


def test_list_accounts_marks_supports_trading_and_never_sends_user_creds() -> None:
    sdk = FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH])
    out = brokerage.list_accounts(sdk)
    assert [a["account_id"] for a in out] == ["acc-1", "acc-2"]
    assert out[0]["supports_trading"] is True and out[1]["supports_trading"] is False
    assert out[0]["balance_total"] == 100.0 and out[1]["balance_total"] is None
    assert out[0]["raw_type"] == "INDIVIDUAL"
    assert out[0]["status"] == "open" and out[1]["status"] == "open"
    for _, kw in sdk.calls:
        assert "user_id" not in kw and "user_secret" not in kw


def test_list_accounts_hides_closed_accounts_unless_include_closed() -> None:
    sdk = FakeSdk(list_user_accounts=ACCOUNTS_WITH_CLOSED, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH])
    default_out = brokerage.list_accounts(sdk)
    assert [a["account_id"] for a in default_out] == ["acc-1", "acc-2"]

    included_out = brokerage.list_accounts(sdk, include_closed=True)
    assert [a["account_id"] for a in included_out] == ["acc-1", "acc-2", "acc-3"]
    closed = next(a for a in included_out if a["account_id"] == "acc-3")
    assert closed["status"] == "closed"


def test_get_portfolio_and_balance_shapes() -> None:
    sdk = FakeSdk(get_user_account_positions=[{"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 3}], get_user_account_balance=[{"cash": 5.0}])
    assert brokerage.get_portfolio(sdk, "acc-1") == {"account_id": "acc-1", "positions": [{"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 3}]}
    assert brokerage.get_balance(sdk, "acc-1") == {"account_id": "acc-1", "balances": [{"cash": 5.0}]}
    assert sdk.kwargs_for("get_user_account_positions") == [{"account_id": "acc-1"}]


def test_list_orders_filters_client_side() -> None:
    orders = [
        {"status": "EXECUTED", "universal_symbol": {"symbol": "AAPL", "raw_symbol": "AAPL"}},
        {"status": "PENDING", "universal_symbol": {"symbol": "MSFT", "raw_symbol": "MSFT"}},
        {"status": "pending", "universal_symbol": {"symbol": "AAPL", "raw_symbol": "AAPL"}},
    ]
    sdk = FakeSdk(get_user_account_orders=orders)
    assert len(brokerage.list_orders(sdk, "acc-1")) == 3
    assert len(brokerage.list_orders(sdk, "acc-1", status="pending")) == 2
    assert len(brokerage.list_orders(sdk, "acc-1", status="pending", symbol="aapl")) == 1
    assert len(brokerage.list_orders(sdk, "acc-1", count=1)) == 1


def test_list_orders_symbol_filter_ignores_deprecated_top_level_symbol() -> None:
    # `symbol` on AccountOrderRecord is a deprecated legacy id string (not a
    # ticker) per the SDK schema; the ticker lives on universal_symbol.
    orders = [
        {"status": "EXECUTED", "symbol": "legacy-id-1", "universal_symbol": {"symbol": "AAPL", "raw_symbol": "AAPL"}},
        {"status": "EXECUTED", "symbol": "legacy-id-2", "universal_symbol": {"symbol": "MSFT", "raw_symbol": "MSFT"}},
    ]
    sdk = FakeSdk(get_user_account_orders=orders)
    out = brokerage.list_orders(sdk, "acc-1", symbol="aapl")
    assert len(out) == 1 and out[0]["universal_symbol"]["raw_symbol"] == "AAPL"


def test_list_transactions_only_sends_given_dates() -> None:
    sdk = FakeSdk(get_activities=[{"id": 1}, {"id": 2}])
    out = brokerage.list_transactions(sdk, "acc-1", start="2026-01-01")
    assert out == {"account_id": "acc-1", "transactions": [{"id": 1}, {"id": 2}]}
    assert sdk.kwargs_for("get_activities") == [{"accounts": "acc-1", "start_date": "2026-01-01"}]


def test_sdk_exception_becomes_api_error_with_status() -> None:
    sdk = FakeSdk(list_user_accounts=SdkError("Too many requests", 429), list_brokerage_authorizations=[])
    with pytest.raises(ApiError) as ei:
        brokerage.list_accounts(sdk)
    assert ei.value.exit_code == 5 and ei.value.extra["http_status"] == 429


@pytest.mark.parametrize("bad", ["", "  ", "AAPL; rm", "toolongsymbolxxxxxxxxx"])
def test_validate_symbol_rejects(bad: str) -> None:
    with pytest.raises(InvalidInput):
        brokerage.validate_symbol(bad)


def test_validate_symbol_normalizes() -> None:
    assert brokerage.validate_symbol(" brk.b ") == "BRK.B"


def test_validate_account_id_rejects_shell_chars() -> None:
    assert brokerage.validate_account_id("6a3b-4c") == "6a3b-4c"
    assert brokerage.validate_account_id("Sample_AcctKey0001") == "Sample_AcctKey0001"  # E*Trade keys carry _
    with pytest.raises(InvalidInput):
        brokerage.validate_account_id("x; ls")


# ── SDK >= 13: /positions/all rows are normalized back to the legacy shape ──

V13_ETF = {
    "instrument": {"kind": "etf", "id": "inst-bnd", "symbol": "BND", "raw_symbol": "BND", "description": "Vanguard Total Bond Market ETF", "currency": "USD", "exchange": "XNAS"},
    "units": "50.125", "price": "72.40", "cost_basis": "70.125", "currency": "USD",
}
V13_CASH = {
    "instrument": {"kind": "mutualfund", "id": "inst-spaxx", "symbol": "SPAXX", "raw_symbol": "SPAXX", "description": "Fidelity Government Money Market Fund", "currency": "USD", "exchange": "XNAS"},
    "units": "0.10", "price": "1", "cost_basis": "1", "currency": "USD", "cash_equivalent": True,
}
V13_NO_COST = {  # 401(k) plan funds come back without cost_basis
    "instrument": {"kind": "other", "id": "inst-qbmz", "symbol": "QBMZ", "raw_symbol": "QBMZ", "description": "VG IS TOT BD MKT IDX", "currency": "USD"},
    "units": "250.0", "price": "100.25", "currency": "USD",
}
V13_BODY = {"results": [V13_ETF, V13_CASH, V13_NO_COST], "data_freshness": {"as_of": "2026-09-05T17:15:40Z"}}


def test_get_portfolio_prefers_v13_endpoint_and_normalizes_rows() -> None:
    sdk = FakeSdk(get_all_account_positions=V13_BODY, get_user_account_positions=SdkError("gone", 404))
    out = brokerage.get_portfolio(sdk, "acc-1")
    assert sdk.kwargs_for("get_all_account_positions") == [{"account_id": "acc-1"}]
    assert sdk.kwargs_for("get_user_account_positions") == []
    assert out["account_id"] == "acc-1"
    bnd, spaxx, qbmz = out["positions"]

    # legacy nesting every script walks: symbol.symbol.symbol / .description
    assert bnd["symbol"]["symbol"]["symbol"] == "BND"
    assert bnd["symbol"]["symbol"]["description"] == "Vanguard Total Bond Market ETF"
    assert bnd["symbol"]["id"] == "inst-bnd"
    # decimal strings become floats so units * price works downstream
    assert bnd["units"] == pytest.approx(50.125)
    assert bnd["price"] == pytest.approx(72.40)
    assert bnd["average_purchase_price"] == pytest.approx(70.125)
    assert bnd["open_pnl"] == pytest.approx((72.40 - 70.125) * 50.125)
    assert bnd["currency"] == "USD"
    assert "raw" not in bnd

    # cash_equivalent carried through (legacy rows had it too); absent stays absent
    assert spaxx["cash_equivalent"] is True
    assert "cash_equivalent" not in bnd

    # no cost basis -> no average price and no P&L, never a crash
    assert qbmz["symbol"]["symbol"]["symbol"] == "QBMZ"
    assert qbmz["average_purchase_price"] is None
    assert qbmz["open_pnl"] is None


def test_get_portfolio_v13_empty_and_none_results() -> None:
    assert brokerage.get_portfolio(FakeSdk(get_all_account_positions={"results": [], "data_freshness": {}}), "acc-1")["positions"] == []
    assert brokerage.get_portfolio(FakeSdk(get_all_account_positions={"results": None, "data_freshness": {}}), "acc-1")["positions"] == []
    assert brokerage.get_portfolio(FakeSdk(get_all_account_positions=None), "acc-1")["positions"] == []


def test_get_portfolio_legacy_sdk_rows_pass_through_untouched() -> None:
    legacy = {"symbol": {"symbol": {"symbol": "AAPL"}}, "units": 3, "price": 10.0, "open_pnl": 1.0, "average_purchase_price": 9.0}
    sdk = FakeSdk(get_user_account_positions=[legacy])
    assert brokerage.get_portfolio(sdk, "acc-1")["positions"] == [legacy]


def test_list_transactions_uses_sdk13_account_activities_when_present() -> None:
    # SDK >= 13 removed transactions_and_reporting.get_activities; the account-scoped
    # get_account_activities returns {"data": [...], "pagination": {...}}.
    page = {"data": [{"id": 1}, {"id": 2}], "pagination": {"offset": 0, "limit": 1000, "total": 2}}
    sdk = FakeSdk(get_account_activities=page)
    out = brokerage.list_transactions(sdk, "acc-1", start="2026-01-01", end="2026-02-01")
    assert out == {"account_id": "acc-1", "transactions": [{"id": 1}, {"id": 2}]}
    assert sdk.kwargs_for("get_account_activities") == [{"account_id": "acc-1", "start_date": "2026-01-01", "end_date": "2026-02-01"}]
