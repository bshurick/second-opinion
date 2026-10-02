from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fakes import FakeTransport, fixture
from second_opinion.brokers import etrade, etrade_auth as ea
from second_opinion.config import ETradeSettings
from second_opinion.errors import ApiError, ConfigError

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)
KEY1, KEY2 = "SampleAcctKey0000001", "SampleAcctKey0000002"


class NoNetAuth(ea.ETradeAuth):
    """Auth with a usable token and scripted renew results; never touches the network."""

    def __init__(self, sandbox=False, renew_results=()):
        super().__init__(ETradeSettings("ck", "cs", sandbox), now=lambda: NOW, session_factory=lambda **kw: (_ for _ in ()).throw(AssertionError("network")))
        self.renew_results = list(renew_results)
        self.reauths = 0

    def renew(self, token):
        return self.renew_results.pop(0) if self.renew_results else False

    def reauth_error(self):
        self.reauths += 1
        return ConfigError("E*Trade authorization required", code="ETRADE_REAUTH", url="https://us.etrade.com/x", hint=ea.REAUTH_HINT, sandbox=self.settings.sandbox)


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    ea.save_token(ea.Token("at", "ats", NOW, sandbox=False))
    return tmp_path


def broker(routes, **auth_kw):
    t = FakeTransport(routes)
    return etrade.ETradeBroker(NoNetAuth(**auth_kw), transport=t), t


def test_base_url_follows_sandbox_flag(data) -> None:
    assert etrade.ETradeBroker(NoNetAuth()).base_url == etrade.PROD_BASE
    ea.save_token(ea.Token("at", "ats", NOW, sandbox=True))
    assert etrade.ETradeBroker(NoNetAuth(sandbox=True)).base_url == etrade.SANDBOX_BASE


def test_list_accounts_maps_rows_and_fetches_balances(data) -> None:
    b, t = broker({
        "GET /v1/accounts/list": fixture("accounts.json"),
        f"GET /v1/accounts/{KEY1}/balance": fixture("balance_margin.json"),
        f"GET /v1/accounts/{KEY2}/balance": fixture("balance_cash.json"),
    })
    rows = b.list_accounts()
    assert [r["account_id"] for r in rows] == [KEY1, KEY2]  # closed account skipped
    r = rows[0]
    assert r == {
        "account_id": KEY1, "name": "Individual Brokerage", "account_number": "10000001", "institution_name": "E*TRADE",
        "brokerage_authorization": "etrade", "supports_trading": True, "raw_type": "INDIVIDUAL", "balance_total": 3001.55,
        "status": "open", "account_type": "margin", "broker": "etrade",
    }
    assert rows[1]["name"] == "IRA" and rows[1]["account_type"] == "cash"
    assert t.calls[1][2] == {"instType": "BROKERAGE", "realTimeNAV": "true"}
    closed = b.list_accounts(include_closed=True)
    assert closed[-1]["status"] == "closed" and closed[-1]["balance_total"] is None  # no balance call for closed


def test_list_accounts_takes_account_type_from_the_live_balance_mode(data) -> None:
    """The account list's accountMode lags a cash-to-margin conversion; the balance endpoint is live."""
    accounts = fixture("accounts.json")
    for a in accounts["AccountListResponse"]["Accounts"]["Account"]:
        if a["accountIdKey"] == KEY1:
            a["accountMode"] = "CASH"  # stale listing for an account the balance call reports as MARGIN
    b, _ = broker({
        "GET /v1/accounts/list": accounts,
        f"GET /v1/accounts/{KEY1}/balance": fixture("balance_margin.json"),
        f"GET /v1/accounts/{KEY2}/balance": fixture("balance_cash.json"),
    })
    rows = b.list_accounts()
    assert rows[0]["account_type"] == "margin" and rows[1]["account_type"] == "cash"


def test_list_accounts_keeps_account_when_balance_fails(data) -> None:
    b, _ = broker({
        "GET /v1/accounts/list": fixture("accounts.json"),
        f"GET /v1/accounts/{KEY1}/balance": (500, {"Error": {"code": 9, "message": "down"}}),
        f"GET /v1/accounts/{KEY2}/balance": fixture("balance_cash.json"),
    })
    rows = b.list_accounts()
    assert [r["account_id"] for r in rows] == [KEY1, KEY2]
    assert rows[0]["balance_total"] is None and rows[0]["account_type"] == "margin"
    assert rows[1]["balance_total"] == 5200.0


def test_get_balance_shape_margin_and_cash(data) -> None:
    # Margin shape: netCash == cashBuyingPower is withdrawable margin credit, not cash.
    # The cash is totalAccountValue minus netMv (0.80 here), even though cashBalance reads 0.
    b, _ = broker({f"GET /v1/accounts/{KEY1}/balance": fixture("balance_margin.json"), f"GET /v1/accounts/{KEY2}/balance": fixture("balance_cash.json")})
    m = b.get_balance(KEY1)
    assert m["account_id"] == KEY1 and m["balances"] == [{
        "currency": {"code": "USD"}, "cash": 0.8, "buying_power": 3001.0, "settled_cash": 0.0, "unsettled_cash": 0.0,
        "total_account_value": 3001.55, "account_mode": "MARGIN",
    }]
    c = b.get_balance(KEY2)["balances"][0]
    assert (c["cash"], c["buying_power"], c["account_mode"]) == (200.0, 200.0, "CASH")


def test_map_balance_counts_sweep_cash_that_cash_balance_leaves_out() -> None:
    # Cash sits in the sweep money market (Cash.moneyMktBalance 4000.00) less a small margin
    # debit (marginBalance -250.00). Computed.cashBalance reports 0, so without this the
    # $3,750.00 would go missing from the account total. The account's real-time value beyond
    # its positions is the cash, and it matches the portfolio endpoint's own Totals.cashBalance.
    computed = {
        "cashBalance": 0, "netCash": 15000.00, "cashBuyingPower": 15000.00, "marginBuyingPower": 30000.00,
        "cashAvailableForInvestment": 3750.00, "marginBalance": -250.00,
        "RealTimeValues": {"totalAccountValue": 103750.12345, "netMv": 100000.12345, "netMvLong": 100000.12345, "netMvShort": 0},
    }
    out = etrade.map_balance({"BalanceResponse": {"accountMode": "MARGIN", "Computed": computed, "Cash": {"moneyMktBalance": 4000.00}}})
    assert out["cash"] == pytest.approx(3750.00)
    assert out["total_account_value"] == pytest.approx(103750.12345)


def test_map_balance_never_reports_net_cash_as_cash() -> None:
    computed = {"netCash": 50000.00, "cashBuyingPower": 50000.00, "marginBuyingPower": 100000.00, "RealTimeValues": {"totalAccountValue": 120000.80, "netMv": 120000.00}}
    # cashBalance missing: fall back to what the account is worth beyond its positions.
    out = etrade.map_balance({"BalanceResponse": {"accountMode": "MARGIN", "Computed": computed}})
    assert out["cash"] == pytest.approx(0.80) and out["buying_power"] == 100000.00
    # Neither cashBalance nor real-time values: cash is unknown, not the margin credit line.
    out = etrade.map_balance({"BalanceResponse": {"accountMode": "MARGIN", "Computed": {"netCash": 50000.00}}})
    assert out["cash"] is None


def test_get_portfolio_follows_pages_and_maps_legacy_shape(data) -> None:
    b, t = broker({f"GET /v1/accounts/{KEY1}/portfolio": [fixture("portfolio_p1.json"), fixture("portfolio_p2.json")]})
    out = b.get_portfolio(KEY1)
    syms = [p["symbol"]["symbol"]["symbol"] for p in out["positions"]]
    assert syms == ["AAPL", "TSLA", "VFIAX"]
    aapl = out["positions"][0]
    assert aapl == {
        "symbol": {"id": "AAPL", "symbol": {"symbol": "AAPL", "raw_symbol": "AAPL", "description": "APPLE INC", "currency": "USD", "exchange": None, "type": {"code": "cs", "description": "EQ"}}, "description": "APPLE INC"},
        "units": 10.0, "price": 200.0, "average_purchase_price": 150.0, "open_pnl": 500.0, "currency": "USD", "cash_equivalent": False,
    }
    assert out["positions"][1]["units"] == -5.0  # SHORT
    assert out["positions"][2]["symbol"]["symbol"]["type"]["code"] == "mf"
    assert [c[2] for c in t.calls] == [{"view": "QUICK", "count": 200}, {"view": "QUICK", "count": 200, "pageNumber": "2"}]


def test_empty_portfolio_204(data) -> None:
    b, _ = broker({f"GET /v1/accounts/{KEY1}/portfolio": (204, {})})
    assert b.get_portfolio(KEY1) == {"account_id": KEY1, "positions": []}


def test_401_renews_once_then_retries(data) -> None:
    b, t = broker({f"GET /v1/accounts/{KEY1}/balance": [(401, fixture("error_401.json")), fixture("balance_cash.json")]}, renew_results=[True])
    assert b.get_balance(KEY1)["balances"][0]["cash"] == 200.0 and len(t.calls) == 2


def test_401_with_failed_renew_raises_reauth(data) -> None:
    b, _ = broker({f"GET /v1/accounts/{KEY1}/balance": (401, fixture("error_401.json"))}, renew_results=[False])
    with pytest.raises(ConfigError) as ei:
        b.get_balance(KEY1)
    assert ei.value.code == "ETRADE_REAUTH" and b.auth.reauths == 1


def test_expired_token_raises_reauth_before_any_call(data) -> None:
    ea.save_token(ea.Token("at", "ats", NOW.replace(day=1), sandbox=False))
    b, t = broker({})
    with pytest.raises(ConfigError) as ei:
        b.list_accounts()
    assert t.calls == []
    # no network, no pending file: a listing reports the missing login, it does not start one
    assert ei.value.code == "ETRADE_REAUTH" and b.auth.reauths == 0
    assert "expired" in str(ei.value) and ei.value.extra["hint"] == ea.REAUTH_HINT and "url" not in ei.value.extra
    assert not ea.pending_path().exists()


def test_request_without_reauth_never_starts_a_login(data) -> None:
    ea.save_token(ea.Token("at", "ats", NOW.replace(day=1), sandbox=False))
    b, t = broker({})
    with pytest.raises(ApiError) as ei:
        b._request("GET", "/v1/accounts/list", reauth=False)
    assert ei.value.extra["http_status"] == 401 and t.calls == []
    assert b.auth.reauths == 0 and not ea.pending_path().exists()


def test_401_twice_after_a_successful_renew_raises_reauth(data) -> None:
    b, t = broker({f"GET /v1/accounts/{KEY1}/balance": [(401, fixture("error_401.json")), (401, fixture("error_401.json"))]}, renew_results=[True])
    with pytest.raises(ConfigError) as ei:
        b.get_balance(KEY1)
    assert ei.value.code == "ETRADE_REAUTH" and b.auth.reauths == 1 and len(t.calls) == 2


def test_api_error_carries_etrade_code(data) -> None:
    b, _ = broker({f"GET /v1/accounts/{KEY1}/balance": (400, {"Error": {"code": 1023, "message": "bad account"}})})
    with pytest.raises(ApiError) as ei:
        b.get_balance(KEY1)
    assert ei.value.extra == {"http_status": 400, "etrade_code": "1023"} and "bad account" in str(ei.value)


def test_connection_status_and_quote_state(data) -> None:
    b, _ = broker({})
    assert b.connection_status() == {"id": "etrade", "broker": "etrade", "type": "trade", "status": "usable", "sandbox": False}


def test_login_url_starts_an_authorization(data) -> None:
    class StartAuth(NoNetAuth):
        def start(self):
            return {"url": "https://us.etrade.com/e/t/etws/authorize?key=ck&token=rt", "sandbox": False, "created_at": "x"}

    b = etrade.ETradeBroker(StartAuth())
    assert b.login_url() == "https://us.etrade.com/e/t/etws/authorize?key=ck&token=rt"


# --- mutual-fund quotes -------------------------------------------------------------
# E*Trade answers /market/quote with an "All" block for stocks and a "MutualFund" block
# for funds. map_quotes read only "All" and required lastTrade, so every fund quote was
# dropped, quote.py fell back to Yahoo, and Yahoo carries a $1.00 NAV with no yield —
# the seven-day yield the caller wanted was in the response we already had.
def _fund_quote(symbol: str, seven_day: float | None, nav: float | None = 1.0) -> dict:
    # Field names copied from a real E*Trade money-market fund quote, not invented: the fund block carries
    # netAssetValue and lastTrade (both 1.0 for a money market fund) plus
    # sevenDayCurrentYield. An earlier version of this fixture used "navValue", which does
    # not exist -- and because the code under test used the same invented name, the pair
    # agreed with each other and real quotes still fell through to Yahoo.
    mf: dict = {"netAssetValue": nav, "lastTrade": nav, "previousClose": nav}
    if seven_day is not None:
        mf["sevenDayCurrentYield"] = seven_day
    return {"QuoteResponse": {"QuoteData": [{
        "dateTimeUTC": 1790000000,
        "quoteStatus": "DELAYED",
        "Product": {"symbol": symbol, "securityType": "MF"},
        "MutualFund": mf,
    }]}}


def test_map_quotes_keeps_a_money_market_fund_and_its_seven_day_yield() -> None:
    rows = etrade.map_quotes(_fund_quote("VMFXX", 3.7745))
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "VMFXX"
    assert row["seven_day_yield"] == 3.7745
    assert row["price"] == 1.0
    assert row["source"] == "etrade"


def test_map_quotes_keeps_a_fund_without_a_yield() -> None:
    # A non-money-market fund has a NAV and no seven-day yield. It is still a quote.
    rows = etrade.map_quotes(_fund_quote("FXAIX", None, nav=201.34))
    assert len(rows) == 1 and rows[0]["price"] == 201.34
    assert rows[0]["seven_day_yield"] is None


def test_map_quotes_still_maps_an_equity_and_gives_it_no_yield() -> None:
    raw = {"QuoteResponse": {"QuoteData": [{
        "dateTimeUTC": 1790000000,
        "quoteStatus": "REALTIME",
        "Product": {"symbol": "AAPL"},
        "All": {"lastTrade": 254.43, "previousClose": 251.0, "changeClosePercentage": 1.37},
    }]}}
    rows = etrade.map_quotes(raw)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL" and rows[0]["price"] == 254.43
    assert rows[0]["seven_day_yield"] is None
    assert rows[0]["realtime"] is True


def test_map_quotes_drops_a_row_with_no_usable_price() -> None:
    raw = {"QuoteResponse": {"QuoteData": [
        {"Product": {"symbol": "NOPRICE"}, "All": {"lastTrade": None}},
        {"Product": {"symbol": "ALSONONE"}, "MutualFund": {"navValue": None}},
        {"All": {"lastTrade": 10.0}},  # no symbol
    ]}}
    assert etrade.map_quotes(raw) == []
