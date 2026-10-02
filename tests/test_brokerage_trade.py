from __future__ import annotations

from decimal import Decimal

import pytest

from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk
from second_opinion import brokerage
from second_opinion.brokerage import OrderSpec
from second_opinion.errors import InvalidInput

# Shaped after snaptrade_client.type.manual_trade_and_impact.ManualTradeAndImpact:
# `trade` is a ManualTrade (id, account, order_type, time_in_force, symbol, action,
# units, price); `trade_impacts` is a list of ManualTradeImpact (account, currency,
# remaining_cash, estimated_commission, forex_fees) — no `buying_power` field.
IMPACT = {
    "trade": {"id": "trade-9", "account": "acc-1", "order_type": "Limit", "time_in_force": "GTC", "action": "BUY", "units": 2, "price": 150.25},
    "trade_impacts": [{"account": "acc-1", "currency": "USD", "remaining_cash": 900.0, "estimated_commission": 1.0, "forex_fees": 0.0}],
}
SYMBOLS = [{"id": "uid-aapl", "symbol": "AAPL"}, {"id": "uid-aap", "symbol": "AAP"}]


@pytest.fixture(autouse=True)
def _plain_form(monkeypatch):
    monkeypatch.setattr(brokerage, "_manual_trade_form", lambda body: body)


def _sdk(**extra):
    defaults = {
        "list_user_accounts": ACCOUNTS,
        "list_brokerage_authorizations": [TRADE_AUTH, READ_AUTH],
        "symbol_search_user_account": SYMBOLS,
        "get_order_impact": IMPACT,
        "place_order": {"brokerage_order_id": "ord-1", "status": "PENDING"},
        "cancel_user_account_order": {"ok": True},
    }
    defaults.update(extra)
    return FakeSdk(**defaults)


def test_validate_order_rules() -> None:
    ok = brokerage.validate_order(OrderSpec("acc-1", "aapl", "buy", 5))
    assert (ok.symbol, ok.side, ok.order_type) == ("AAPL", "BUY", "MARKET")
    with pytest.raises(InvalidInput):
        brokerage.validate_order(OrderSpec("acc-1", "AAPL", "hold", 5))
    with pytest.raises(InvalidInput):
        brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", 0))
    with pytest.raises(InvalidInput, match="limit_price"):
        brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", 1, order_type="LIMIT"))
    with pytest.raises(InvalidInput, match="stop_price"):
        brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", 1, order_type="STOP"))
    with pytest.raises(InvalidInput):
        brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", 1, time_in_force="FOREVER"))


def test_resolve_symbol_prefers_exact_match() -> None:
    sdk = _sdk(symbol_search_user_account=[{"id": "uid-aap", "symbol": "AAP"}, {"id": "uid-aapl", "symbol": "AAPL"}])
    assert brokerage.resolve_universal_symbol_id(sdk, "acc-1", "aapl") == "uid-aapl"
    assert sdk.kwargs_for("symbol_search_user_account") == [{"account_id": "acc-1", "substring": "AAPL"}]
    with pytest.raises(InvalidInput, match="no symbols"):
        brokerage.resolve_universal_symbol_id(_sdk(symbol_search_user_account=[]), "acc-1", "ZZZZ")


def test_resolve_symbol_rejects_no_exact_match() -> None:
    with pytest.raises(InvalidInput) as ei:
        brokerage.resolve_universal_symbol_id(_sdk(symbol_search_user_account=[{"id": "uid-aap", "symbol": "AAP"}]), "acc-1", "AAPL")
    assert ei.value.code == "SYMBOL_NOT_FOUND"
    assert "AAP" in str(ei.value)


def test_require_trading_rejects_read_only_account() -> None:
    with pytest.raises(InvalidInput) as ei:
        brokerage.require_trading(_sdk(), "acc-2")
    assert ei.value.code == "READ_ONLY_ACCOUNT"
    assert brokerage.require_trading(_sdk(), "acc-1")["account_id"] == "acc-1"


def test_preview_builds_snaptrade_body_and_returns_trade_id() -> None:
    sdk = _sdk()
    out = brokerage.preview_order(sdk, OrderSpec("acc-1", "AAPL", "buy", 2, order_type="LIMIT", limit_price=150.25, time_in_force="GOOD_UNTIL_CANCEL"))
    body = sdk.kwargs_for("get_order_impact")[0]["body"]
    assert body == {
        "account_id": "acc-1", "action": "BUY", "universal_symbol_id": "uid-aapl",
        "order_type": "Limit", "time_in_force": "GTC", "units": Decimal("2"), "price": Decimal("150.25"),
    }
    assert out["trade_id"] == "trade-9"
    assert out["price"] == 150.25 and out["units"] == 2
    assert out["estimated_cost"] == 150.25 * 2
    assert out["remaining_cash"] == 900.0
    assert out["estimated_commission"] == 1.0
    assert out["currency"] == "USD"
    assert out["estimated_buying_power"] is None  # ManualTradeImpact has no buying_power field
    assert (out["symbol"], out["side"], out["quantity"], out["order_type"]) == ("AAPL", "BUY", 2, "LIMIT")


def test_place_runs_fresh_preview_then_places_with_its_trade_id() -> None:
    sdk = _sdk()
    out = brokerage.place_order(sdk, OrderSpec("acc-1", "AAPL", "sell", 1))
    names = [n for n, _ in sdk.calls]
    assert names.index("get_order_impact") < names.index("place_order")
    assert sdk.kwargs_for("place_order") == [{"trade_id": "trade-9"}]
    assert out["order_id"] == "ord-1" and out["status"] == "PENDING" and out["state"] == "PENDING"
    assert out["preview"]["trade_id"] == "trade-9"


def test_place_refuses_read_only_before_any_trade_call() -> None:
    sdk = _sdk()
    with pytest.raises(InvalidInput):
        brokerage.place_order(sdk, OrderSpec("acc-2", "AAPL", "buy", 1))
    assert not sdk.kwargs_for("get_order_impact") and not sdk.kwargs_for("place_order") and not sdk.kwargs_for("symbol_search_user_account")


def test_cancel_order() -> None:
    sdk = _sdk()
    out = brokerage.cancel_order(sdk, "acc-1", "ord-1")
    assert sdk.kwargs_for("cancel_user_account_order") == [{"account_id": "acc-1", "brokerage_order_id": "ord-1"}]
    assert out == {"account_id": "acc-1", "order_id": "ord-1", "cancelled": True, "raw": {"ok": True}}


def test_validate_order_whole_number_quantities() -> None:
    # a float that is a whole number is the same order as the int
    assert brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", 2.0)).quantity == 2
    assert isinstance(brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", 2.0)).quantity, int)
    for bad in (True, float("nan"), float("inf"), -1.5, "2"):
        with pytest.raises(InvalidInput):
            brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", bad))


def test_validate_order_rejects_fractions_unless_allowed() -> None:
    with pytest.raises(InvalidInput) as e:
        brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", 0.5))
    assert e.value.code == "FRACTIONAL_NOT_SUPPORTED" and "E*Trade" in str(e.value)
    assert brokerage.validate_order(OrderSpec("acc-1", "AAPL", "BUY", 0.5), fractional=True).quantity == 0.5


def test_snaptrade_preview_refuses_fractions_before_any_call() -> None:
    sdk = _sdk()
    with pytest.raises(InvalidInput) as e:
        brokerage.preview_order(sdk, OrderSpec("acc-1", "AAPL", "BUY", 1.5))
    assert e.value.code == "FRACTIONAL_NOT_SUPPORTED"
    assert not sdk.kwargs_for("get_order_impact")
