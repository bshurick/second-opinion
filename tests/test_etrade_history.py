from __future__ import annotations

import pytest

from fakes import FakeTransport, fixture
from second_opinion.brokers import etrade, etrade_auth as ea
from test_etrade_read import KEY1, NOW, NoNetAuth


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    ea.save_token(ea.Token("at", "ats", NOW, sandbox=False))
    return tmp_path


def broker(routes):
    t = FakeTransport(routes)
    return etrade.ETradeBroker(NoNetAuth(), transport=t), t


def test_list_orders_maps_instruments(data) -> None:
    b, t = broker({f"GET /v1/accounts/{KEY1}/orders": fixture("orders.json")})
    rows = b.list_orders(KEY1, count=10)
    assert t.calls[0][2] == {"count": 10}
    assert rows[0] == {
        "brokerage_order_id": "529", "status": "EXECUTED", "universal_symbol": {"symbol": "AAPL", "raw_symbol": "AAPL"}, "action": "BUY",
        "total_quantity": 10.0, "filled_quantity": 10.0, "execution_price": 200.5, "order_type": "LIMIT", "time_in_force": "GOOD_FOR_DAY",
        "limit_price": 201.0, "stop_price": None, "time_placed": "2026-09-08T14:00:00+00:00", "time_executed": "2026-09-08T14:10:00+00:00", "broker": "etrade",
    }
    assert rows[1]["status"] == "OPEN" and rows[1]["stop_price"] == 245.0 and rows[1]["execution_price"] is None
    assert [r["brokerage_order_id"] for r in b.list_orders(KEY1, status="open")] == ["530"]
    assert [r["brokerage_order_id"] for r in b.list_orders(KEY1, symbol="aapl")] == ["529"]


def test_list_orders_sends_server_side_filters_uppercased(data) -> None:
    b, t = broker({f"GET /v1/accounts/{KEY1}/orders": fixture("orders.json")})
    b.list_orders(KEY1, status="open", symbol="tsla")
    assert t.calls[0][2] == {"count": 25, "status": "OPEN", "symbol": "TSLA"}


def test_list_orders_follows_the_marker(data) -> None:
    b, t = broker({f"GET /v1/accounts/{KEY1}/orders": [fixture("orders_p1.json"), fixture("orders_p2.json")]})
    rows = b.list_orders(KEY1, count=10)
    assert [r["brokerage_order_id"] for r in rows] == ["529", "530"]
    assert [c[2] for c in t.calls] == [{"count": 10}, {"count": 10, "marker": "m2"}]


def test_list_transactions_follows_marker_and_maps_types(data) -> None:
    b, t = broker({f"GET /v1/accounts/{KEY1}/transactions": [fixture("transactions_p1.json"), fixture("transactions_p2.json")]})
    out = b.list_transactions(KEY1, start="2026-08-01", end="2026-09-08", count=100)
    assert t.calls[0][2] == {"startDate": "08012026", "endDate": "09082026", "count": 50}
    assert t.calls[1][2]["marker"] == "m2"
    rows = out["transactions"]
    assert [r["type"] for r in rows] == ["BUY", "DIVIDEND", "CONTRIBUTION", "WITHDRAWAL", "INTEREST", "ADJUSTMENT"]
    buy = rows[0]
    assert buy == {
        "id": "9001", "account": {"id": KEY1}, "trade_date": "2026-09-08", "settlement_date": "2026-09-10", "type": "BUY", "units": 10.0, "price": 200.5,
        "amount": -2005.0, "fee": 0.0, "symbol": {"symbol": "AAPL", "raw_symbol": "AAPL", "description": "BUY AAPL"}, "currency": {"code": "USD"}, "description": "BUY AAPL",
    }
    assert rows[1]["symbol"]["symbol"] == "MSFT" and rows[2]["symbol"] is None and rows[5]["fee"] == 1.5


def test_list_transactions_defaults_to_90_day_window_and_count_cap(data) -> None:
    b, t = broker({f"GET /v1/accounts/{KEY1}/transactions": fixture("transactions_p2.json")})
    out = b.list_transactions(KEY1, count=2)
    assert t.calls[0][2]["startDate"] == "06102026" and t.calls[0][2]["endDate"] == "09082026"
    assert len(out["transactions"]) == 2


def test_quote_batches_and_omits_rejected_symbols(data) -> None:
    b, t = broker({"GET /v1/market/quote/AAPL,MSFT,BADSYM": fixture("quotes.json")})
    rows = b.quote(["aapl", "MSFT", "BADSYM"])
    assert t.calls[0][2] == {"detailFlag": "ALL"}
    assert rows == [
        {"symbol": "AAPL", "price": 201.25, "previous_close": 200.0, "change_pct": 0.625, "seven_day_yield": None, "currency": "USD", "source": "etrade", "realtime": True, "as_of": "2026-09-08T15:00:00+00:00"},
        {"symbol": "MSFT", "price": 500.0, "previous_close": 490.0, "change_pct": 2.0408, "seven_day_yield": None, "currency": "USD", "source": "etrade", "realtime": False, "as_of": "2026-09-08T15:00:00+00:00"},
    ]


def test_quote_splits_into_batches_of_25(data) -> None:
    syms = [f"S{i}" for i in range(30)]
    b, t = broker({f"GET /v1/market/quote/{','.join(syms[:25])}": {"QuoteResponse": {"QuoteData": []}}, f"GET /v1/market/quote/{','.join(syms[25:])}": {"QuoteResponse": {"QuoteData": []}}})
    assert b.quote(syms) == [] and len(t.calls) == 2


def test_quote_returns_none_without_usable_token_and_never_reauths(data) -> None:
    ea.save_token(ea.Token("at", "ats", NOW.replace(day=1), sandbox=False))
    b, t = broker({})
    assert b.quote(["AAPL"]) is None and t.calls == [] and b.auth.reauths == 0


def test_quote_returns_none_on_api_error(data) -> None:
    b, _ = broker({"GET /v1/market/quote/AAPL": (500, {"Error": {"code": 9, "message": "down"}})})
    assert b.quote(["AAPL"]) is None


def test_quote_401_with_failed_renew_never_starts_a_login(data) -> None:
    b, t = broker({"GET /v1/market/quote/AAPL": (401, fixture("error_401.json"))})
    assert b.quote(["AAPL"]) is None
    assert b.auth.reauths == 0 and len(t.calls) == 1 and not ea.pending_path().exists()


def test_malformed_transaction_dates_are_invalid_input(data) -> None:
    from second_opinion.errors import InvalidInput

    b, t = broker({f"GET /v1/accounts/{KEY1}/transactions": fixture("transactions_p2.json")})
    with pytest.raises(InvalidInput):
        b.list_transactions(KEY1, start="09/08/2026")
    with pytest.raises(InvalidInput):
        b.list_transactions(KEY1, end="not-a-date")
    assert t.calls == []
