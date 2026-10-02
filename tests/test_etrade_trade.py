from __future__ import annotations

import pytest

from fakes import FakeTransport, fixture
from second_opinion.brokerage import OrderSpec
from second_opinion.brokers import etrade, etrade_auth as ea
from second_opinion.errors import ApiError
from test_etrade_read import KEY1, KEY2, NOW, NoNetAuth

BUY = OrderSpec(account_id=KEY1, symbol="AAPL", side="BUY", quantity=10, order_type="LIMIT", limit_price=201.0, stop_price=None, time_in_force="GOOD_FOR_DAY")


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    ea.save_token(ea.Token("at", "ats", NOW, sandbox=False))
    return tmp_path


def broker(routes):
    t = FakeTransport(routes)
    return etrade.ETradeBroker(NoNetAuth(), transport=t), t


def routes_for(key=KEY1, balance="balance_margin.json"):
    return {
        f"GET /v1/accounts/{key}/balance": fixture(balance),
        f"POST /v1/accounts/{key}/orders/preview": fixture("preview.json"),
        f"POST /v1/accounts/{key}/orders/place": fixture("place.json"),
        f"PUT /v1/accounts/{key}/orders/cancel": fixture("cancel.json"),
    }


def test_order_body_matches_etrade_contract() -> None:
    body = etrade.order_body(BUY, "ABC123", preview_ids=[1234567890])
    assert body == {"PlaceOrderRequest": {"orderType": "EQ", "clientOrderId": "ABC123", "PreviewIds": [{"previewId": 1234567890}], "Order": [{
        "allOrNone": False, "priceType": "LIMIT", "orderTerm": "GOOD_FOR_DAY", "marketSession": "REGULAR", "limitPrice": 201.0,
        "Instrument": [{"Product": {"securityType": "EQ", "symbol": "AAPL"}, "orderAction": "BUY", "quantityType": "QUANTITY", "quantity": 10}]}]}}
    prev = etrade.order_body(BUY, "ABC123")
    assert "PreviewIds" not in prev["PreviewOrderRequest"] and "stopPrice" not in prev["PreviewOrderRequest"]["Order"][0]


def test_new_client_order_id_is_10_digits() -> None:
    cid = etrade.new_client_order_id()
    assert len(cid) == 10 and cid.isdigit() and cid != etrade.new_client_order_id()


def test_preview_maps_shape_and_remaining_cash(data) -> None:
    b, t = broker(routes_for())
    p = b.preview_order(BUY)
    assert t.calls[0][1].endswith("/balance") and t.calls[1][0] == "POST"
    assert p["trade_id"] == "1234567890" and p["price"] == 201.0 and p["units"] == 10 and p["estimated_cost"] == 2010.0
    assert p["estimated_commission"] == 0.0 and p["remaining_cash"] == pytest.approx(0.8 - 2010.0) and p["currency"]  # real cash (total - positions), not the margin credit line == "USD"
    assert (p["account_id"], p["symbol"], p["side"], p["quantity"], p["order_type"], p["limit_price"], p["stop_price"], p["time_in_force"]) == (KEY1, "AAPL", "BUY", 10, "LIMIT", 201.0, None, "GOOD_FOR_DAY")
    assert p["broker"] == "etrade" and len(p["client_order_id"]) == 10 and p["client_order_id"].isdigit() and p["raw"] == fixture("preview.json")
    assert p["flags"] == []  # margin account: no unsettled-cash flag


def test_preview_flags_unsettled_cash_on_cash_account(data) -> None:
    b, _ = broker(routes_for(KEY2, "balance_cash.json"))
    p = b.preview_order(OrderSpec(account_id=KEY2, symbol="AAPL", side="BUY", quantity=10, order_type="LIMIT", limit_price=201.0, stop_price=None, time_in_force="GOOD_FOR_DAY"))
    assert p["flags"][0]["code"] == "UNSETTLED_CASH" and "150.0" in p["flags"][0]["message"]


def test_preview_without_preview_id_raises_and_place_never_posts(data) -> None:
    routes = routes_for()
    routes[f"POST /v1/accounts/{KEY1}/orders/preview"] = {"PreviewOrderResponse": {"PreviewIds": [], "Order": []}}
    b, t = broker(routes)
    with pytest.raises(ApiError):
        b.place_order(BUY)
    assert not any(c[1].endswith("/orders/place") for c in t.calls)


def test_place_reuses_preview_id_and_client_order_id(data) -> None:
    b, t = broker(routes_for())
    out = b.place_order(BUY)
    place_call = next(c for c in t.calls if c[1].endswith("/orders/place"))
    req = place_call[3]["PlaceOrderRequest"]
    assert req["PreviewIds"] == [{"previewId": 1234567890}] and req["clientOrderId"] == out["preview"]["client_order_id"]
    assert out["order_id"] == "531" and out["status"] == "OPEN" and out["state"] == "OPEN" and out["broker"] == "etrade" and out["raw"] == fixture("place.json")


def test_place_without_an_order_id_is_an_api_error(data) -> None:
    routes = routes_for()
    routes[f"POST /v1/accounts/{KEY1}/orders/place"] = {"PlaceOrderResponse": {"OrderIds": [], "Order": [{"status": "OPEN"}]}}
    b, _ = broker(routes)
    with pytest.raises(ApiError) as ei:
        b.place_order(BUY)
    assert "no order id" in str(ei.value)


def test_place_normalizes_account_id_and_symbol_consistently(data) -> None:
    b, t = broker(routes_for())
    spec = OrderSpec(account_id=f" {KEY1} ", symbol="aapl", side="BUY", quantity=10, order_type="LIMIT", limit_price=201.0, stop_price=None, time_in_force="GOOD_FOR_DAY")
    b.place_order(spec)
    balance_call = next(c for c in t.calls if c[1].endswith("/balance"))
    preview_call = next(c for c in t.calls if c[1].endswith("/orders/preview"))
    place_call = next(c for c in t.calls if c[1].endswith("/orders/place"))
    assert balance_call[1] == f"/v1/accounts/{KEY1}/balance"
    assert preview_call[1] == f"/v1/accounts/{KEY1}/orders/preview"
    assert place_call[1] == f"/v1/accounts/{KEY1}/orders/place"
    assert place_call[3]["PlaceOrderRequest"]["Order"][0]["Instrument"][0]["Product"]["symbol"] == "AAPL"


def test_cancel(data) -> None:
    b, t = broker(routes_for())
    out = b.cancel_order(KEY1, "531")
    assert t.calls[0][3] == {"CancelOrderRequest": {"orderId": 531}}
    assert out == {"account_id": KEY1, "order_id": "531", "cancelled": True, "raw": fixture("cancel.json")}


def test_cancel_rejects_non_numeric_order_id(data) -> None:
    b, _ = broker(routes_for())
    from second_opinion.errors import InvalidInput

    with pytest.raises(InvalidInput):
        b.cancel_order(KEY1, "abc")


def _frac_preview(total: float, qty: float) -> dict:
    return {"PreviewOrderResponse": {"orderType": "EQ", "PreviewIds": [{"previewId": 100000000001}], "Order": [{"estimatedCommission": 0, "estimatedTotalAmount": total, "priceType": "MARKET", "orderTerm": "GOOD_FOR_DAY",
        "Instrument": [{"Product": {"symbol": "VTI", "securityType": "EQ"}, "orderAction": "BUY", "quantity": qty, "quantityType": "QUANTITY"}]}]}}


def _frac(qty, **kw) -> OrderSpec:
    return OrderSpec(account_id=KEY1, symbol="VTI", side=kw.pop("side", "BUY"), quantity=qty, **kw)


def test_fractional_market_buy_previews_and_places(data) -> None:
    # E*Trade's preview accepts a fractional MARKET buy and echoes the fractional quantity back
    routes = routes_for()
    routes[f"POST /v1/accounts/{KEY1}/orders/preview"] = _frac_preview(44.96, 0.5)
    b, t = broker(routes)
    p = b.preview_order(_frac(0.5))
    assert p["quantity"] == 0.5 and p["units"] == 0.5 and p["estimated_cost"] == 44.96 and p["price"] == pytest.approx(89.92)
    sent = t.calls[1][3]["PreviewOrderRequest"]["Order"][0]["Instrument"][0]
    assert sent["quantity"] == 0.5 and sent["quantityType"] == "QUANTITY"
    out = b.place_order(_frac(0.5))
    place = next(c for c in t.calls if c[1].endswith("/orders/place"))
    assert place[3]["PlaceOrderRequest"]["Order"][0]["Instrument"][0]["quantity"] == 0.5 and out["order_id"]


def test_fractional_above_one_share_may_be_a_limit_order(data) -> None:
    routes = routes_for()
    routes[f"POST /v1/accounts/{KEY1}/orders/preview"] = _frac_preview(134.88, 1.5)
    b, _ = broker(routes)
    assert b.preview_order(_frac(1.5, order_type="LIMIT", limit_price=89.92))["quantity"] == 1.5


@pytest.mark.parametrize(("spec", "code"), [
    (_frac(0.1234), "FRACTIONAL_PRECISION"),
    (_frac(0.5, order_type="LIMIT", limit_price=89.0), "FRACTIONAL_MARKET_ONLY"),
    (_frac(1.5, time_in_force="GOOD_UNTIL_CANCEL", order_type="LIMIT", limit_price=89.0), "FRACTIONAL_TERM"),
    (_frac(0.5, side="SELL_SHORT"), "FRACTIONAL_SHORT"),
])
def test_fractional_rules_refuse_before_any_call(data, spec, code) -> None:
    from second_opinion.errors import InvalidInput

    b, t = broker(routes_for())
    with pytest.raises(InvalidInput) as e:
        b.preview_order(spec)
    assert e.value.code == code and t.calls == []


def test_fractional_buy_under_five_dollars_is_refused_and_never_placed(data) -> None:
    from second_opinion.errors import InvalidInput

    routes = routes_for()
    routes[f"POST /v1/accounts/{KEY1}/orders/preview"] = _frac_preview(4.5, 0.05)
    b, t = broker(routes)
    with pytest.raises(InvalidInput) as e:
        b.place_order(_frac(0.05))
    assert e.value.code == "FRACTIONAL_MINIMUM" and "5.00" in str(e.value)
    assert not any(c[1].endswith("/orders/place") for c in t.calls)


def test_fractional_sell_of_a_held_fraction_is_allowed_under_five_dollars(data) -> None:
    routes = routes_for()
    routes[f"POST /v1/accounts/{KEY1}/orders/preview"] = _frac_preview(4.5, 0.05)
    b, _ = broker(routes)
    assert b.preview_order(_frac(0.05, side="SELL"))["quantity"] == 0.05
