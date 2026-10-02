from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakes import ACCOUNTS, READ_AUTH, TRADE_AUTH, FakeSdk, fake_hub
from second_opinion import config
from second_opinion.brokers import registry, router
from second_opinion.brokers.snaptrade import SnapTradeBroker
from second_opinion.errors import ApiError, ConfigError, InvalidInput


class StubDirect:
    """A direct broker with two accounts; records calls."""

    name = "etrade"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_accounts(self, include_closed=False):
        return [
            {"account_id": "KEY1", "name": "Brokerage", "account_number": "1234", "institution_name": "E*TRADE", "brokerage_authorization": "etrade", "supports_trading": True, "raw_type": "INDIVIDUAL", "balance_total": 10.0, "status": "open", "account_type": "margin", "broker": "etrade"},
            {"account_id": "KEY2", "name": "IRA", "account_number": "9876", "institution_name": "E*TRADE", "brokerage_authorization": "etrade", "supports_trading": True, "raw_type": "IRA", "balance_total": 5.0, "status": "open", "account_type": "cash", "broker": "etrade"},
        ]

    def get_portfolio(self, account_id):
        self.calls.append(("portfolio", account_id))
        return {"account_id": account_id, "positions": [{"units": 2}]}

    def get_balance(self, account_id):
        return {"account_id": account_id, "balances": [{"cash": 1.0}]}

    def list_orders(self, account_id, status=None, symbol=None, count=25):
        return []

    def list_transactions(self, account_id, start=None, end=None, count=50):
        return {"account_id": account_id, "transactions": []}

    def preview_order(self, spec):
        return {"trade_id": "p1"}

    def place_order(self, spec):
        return {"order_id": "o1"}

    def cancel_order(self, account_id, order_id):
        return {"cancelled": True}

    def quote(self, symbols):
        self.calls.append(("quote", tuple(symbols)))
        return [{"symbol": s, "price": 1.0, "source": "etrade", "realtime": True} for s in symbols]

    def connection_status(self):
        return {"id": "etrade", "broker": "etrade", "type": "trade", "status": "usable"}


class FailingDirect(StubDirect):
    """A direct broker whose listing fails the way a missing E*Trade login does."""

    LOGIN_URL = "https://us.etrade.com/e/t/etws/authorize?key=k&token=t"

    def __init__(self, error=None, scoped_error=None, login_error=None) -> None:
        super().__init__()
        self.error = error or ConfigError("E*Trade login required (token expired)", code="ETRADE_REAUTH", hint="log in again", sandbox=False)
        self.scoped_error = scoped_error
        self.login_error = login_error
        self.login_starts = 0

    def list_accounts(self, include_closed=False):
        raise self.error

    def login_url(self):
        self.login_starts += 1
        if self.login_error is not None:
            raise self.login_error
        return self.LOGIN_URL

    def get_portfolio(self, account_id):
        if self.scoped_error is not None:
            raise self.scoped_error
        return super().get_portfolio(account_id)


@pytest.fixture
def sdk():
    return FakeSdk(list_user_accounts=ACCOUNTS, list_brokerage_authorizations=[TRADE_AUTH, READ_AUTH], get_user_account_positions=[{"units": 1}], get_user_account_balance=[{"cash": 1.0}])


def test_snaptrade_broker_tags_rows_and_delegates(sdk) -> None:
    b = SnapTradeBroker(sdk)
    rows = b.list_accounts()
    assert [r["broker"] for r in rows] == ["snaptrade", "snaptrade"]
    assert b.get_portfolio("acc-1")["positions"] == [{"units": 1}]
    assert b.quote(["AAPL"]) is None


def test_single_broker_hub_dispatches_without_registry(sdk) -> None:
    hub = fake_hub(sdk)
    assert hub.get_portfolio("acc-1")["positions"] == [{"units": 1}]
    assert sdk.kwargs_for("list_user_accounts") == []  # no account listing needed


def test_apply_account_types_prefers_override_then_row() -> None:
    hub = router.Hub([StubDirect()], account_types={"KEY2": "margin"}, registry=None)
    rows = hub.list_accounts()
    assert {r["account_id"]: r["account_type"] for r in rows} == {"KEY1": "margin", "KEY2": "margin"}


def test_merge_puts_direct_first_and_shadows_matching_snaptrade_rows(sdk) -> None:
    hub = router.Hub([StubDirect(), SnapTradeBroker(sdk)], account_types={}, registry=None)
    rows = hub.list_accounts()
    assert [r["account_id"] for r in rows] == ["KEY1", "KEY2", "acc-2"]  # acc-1 is E*Trade #1234, shadowed by KEY1
    assert hub.shadowed == [{"snaptrade_account_id": "acc-1", "direct_account_id": "KEY1", "broker": "etrade"}]
    assert [r["account_id"] for r in hub.list_accounts(include_shadowed=True)] == ["KEY1", "KEY2", "acc-1", "acc-2"]


def test_login_required_broker_stops_the_listing_by_default(sdk) -> None:
    direct = FailingDirect()
    hub = router.Hub([direct, SnapTradeBroker(sdk)], account_types={}, registry=None)
    with pytest.raises(ConfigError) as ei:
        hub.list_accounts()
    err = ei.value
    assert err.code == "ETRADE_REAUTH" and str(err) == "E*Trade login required (token expired)"
    assert err.extra["url"] == FailingDirect.LOGIN_URL and err.extra["hint"] == "log in again" and err.extra["sandbox"] is False
    assert err.extra["partial"] == "--partial"  # how to run without that broker instead
    assert direct.login_starts == 1
    assert hub.broker_errors[0]["code"] == "ETRADE_REAUTH"  # still recorded for unknown_account_error


def test_login_url_failure_still_reports_the_missing_login(sdk) -> None:
    direct = FailingDirect(login_error=ApiError("E*Trade request token failed: 503", http_status=503))
    hub = router.Hub([direct, SnapTradeBroker(sdk)], account_types={}, registry=None)
    with pytest.raises(ConfigError) as ei:
        hub.list_accounts()
    assert ei.value.code == "ETRADE_REAUTH" and "url" not in ei.value.extra and ei.value.extra["partial"] == "--partial"


def test_non_login_outage_of_one_broker_stays_partial_by_default(sdk) -> None:
    down = FailingDirect(error=ApiError("E*Trade returned 503", http_status=503))
    hub = router.Hub([down, SnapTradeBroker(sdk)], account_types={}, registry=None)
    rows = hub.list_accounts()
    assert [r["account_id"] for r in rows] == ["acc-1", "acc-2"]
    assert hub.unavailable_flags() == [{"code": "BROKER_UNAVAILABLE", "message": "etrade: E*Trade returned 503; its accounts are excluded from this run"}]
    assert down.login_starts == 0


def test_one_failing_broker_never_hides_the_others_in_partial_mode(sdk, tmp_path: Path) -> None:
    reg = registry.Registry(tmp_path / "brokers.json")
    reg.save([{"account_id": "KEY1", "broker": "etrade", "account_number": "1234"}])
    scoped = ConfigError("E*Trade authorization required", code="ETRADE_REAUTH", url="https://us.etrade.com/x", hint="log in again")
    direct = FailingDirect(scoped_error=scoped)
    hub = router.Hub([direct, SnapTradeBroker(sdk)], account_types={}, registry=reg, partial=True)
    rows = hub.list_accounts()
    assert direct.login_starts == 0  # partial mode never starts an authorization
    assert [r["account_id"] for r in rows] == ["acc-1", "acc-2"]
    assert hub.broker_errors == [{"broker": "etrade", "code": "ETRADE_REAUTH", "message": "E*Trade login required (token expired)", "hint": "log in again", "sandbox": False}]
    assert hub.unavailable_flags() == [{"code": "BROKER_UNAVAILABLE", "message": "etrade: E*Trade login required (token expired); its accounts are excluded from this run"}]
    # dispatch is unchanged: a call that targets an E*Trade account still raises with the URL
    with pytest.raises(ConfigError) as ei:
        hub.get_portfolio("KEY1")
    assert ei.value.code == "ETRADE_REAUTH" and ei.value.extra["url"] == "https://us.etrade.com/x"


def test_unknown_account_error_blames_only_the_broker_that_owns_the_id(sdk, tmp_path: Path) -> None:
    reg = registry.Registry(tmp_path / "brokers.json")
    reg.save([{"account_id": "KEY1", "broker": "etrade", "account_number": "1234"}])
    hub = router.Hub([FailingDirect(), SnapTradeBroker(sdk)], account_types={}, registry=reg, partial=True)
    hub.list_accounts()

    # (a) an id the cache says belongs to the broker that is down
    err = hub.unknown_account_error(["KEY1"])
    assert isinstance(err, ConfigError) and err.code == "ETRADE_REAUTH" and err.extra["hint"] == "log in again"
    assert "KEY1" in str(err)

    # (b) a typo is still exit 2, with the down broker mentioned, not blamed
    typo = hub.unknown_account_error(["nope"])
    assert isinstance(typo, InvalidInput) and "accounts.py" in str(typo) and "etrade is unavailable" in str(typo)

    # (c) nothing failed: the plain unknown-id error
    clean = router.Hub([StubDirect(), SnapTradeBroker(sdk)], account_types={}, registry=reg)
    clean.list_accounts()
    plain = clean.unknown_account_error("KEY9")
    assert isinstance(plain, InvalidInput) and "unavailable" not in str(plain) and "accounts.py" in str(plain)


def test_unknown_account_error_names_the_account_whose_number_was_pasted(sdk) -> None:
    """A direct E*Trade id lands in a SnapTrade-only hub as acc-1's account_number, not as any account_id."""
    hub = fake_hub(sdk)  # SnapTrade only: acc-1 is E*Trade #1234
    hub.list_accounts()
    err = hub.unknown_account_error(["1234"])
    assert isinstance(err, InvalidInput) and str(err).startswith("unknown account id(s): 1234; run accounts.py")
    assert "1234 is the account_number of snaptrade account acc-1" in str(err) and "use acc-1" in str(err)
    assert "direct etrade adapter" in str(err) and "not configured" in str(err)

    both = router.Hub([StubDirect(), SnapTradeBroker(sdk)], account_types={}, registry=None)
    both.list_accounts()
    assert "not configured" not in str(both.unknown_account_error("1234"))  # etrade is configured: KEY1 owns #1234
    assert "use KEY1" in str(both.unknown_account_error("1234"))
    assert "account_number" not in str(both.unknown_account_error("nope"))  # a plain typo gets no twin note


def test_unknown_account_flags_are_per_id(sdk, tmp_path: Path) -> None:
    reg = registry.Registry(tmp_path / "brokers.json")
    reg.save([{"account_id": "KEY1", "broker": "etrade", "account_number": "1234"}])
    hub = router.Hub([FailingDirect(), SnapTradeBroker(sdk)], account_types={}, registry=reg, partial=True)
    hub.list_accounts()
    flags = hub.unknown_account_flags(["KEY1", "nope"])
    assert [f["code"] for f in flags] == ["UNKNOWN_ACCOUNT", "UNKNOWN_ACCOUNT"]
    assert flags[0]["message"].startswith("account id KEY1 could not be checked — etrade: E*Trade login required")
    assert flags[1]["message"].startswith("unknown account id nope; run accounts.py")
    assert all(f["message"].endswith("it is excluded from this run") for f in flags)
    assert hub.unknown_account_flags([]) == []


def test_holdings_source_of_no_rows_is_none() -> None:
    assert router.holdings_source([]) is None
    assert router.holdings_source([{"broker": "etrade"}]) == "etrade"
    assert router.holdings_source([{"broker": "etrade"}, {"broker": "snaptrade"}]) == "mixed"


def test_every_broker_failing_re_raises_the_first_error(sdk) -> None:
    class Snap(FailingDirect):
        name = "snaptrade"

    hub = router.Hub([FailingDirect(), Snap(ApiError("snaptrade down", http_status=500))], account_types={}, registry=None, partial=True)
    with pytest.raises(ConfigError) as ei:
        hub.list_accounts()
    assert ei.value.code == "ETRADE_REAUTH"  # a dead config never prints an empty account list


def test_broker_errors_reset_between_listings(sdk) -> None:
    hub = router.Hub([FailingDirect(), SnapTradeBroker(sdk)], account_types={}, registry=None, partial=True)
    hub.list_accounts()
    hub.brokers = [SnapTradeBroker(sdk)]
    hub.list_accounts()
    assert hub.broker_errors == []


def test_masked_snaptrade_number_shadows_the_direct_account(sdk) -> None:
    class Masked(StubDirect):
        def list_accounts(self, include_closed=False):
            rows = super().list_accounts(include_closed)
            rows[0]["account_number"] = "10000001"
            return rows

    snap = [
        {"account_id": "acc-1", "account_number": "****0001", "institution_name": "E*Trade", "broker": "snaptrade"},
        {"account_id": "acc-9", "account_number": "77770000", "institution_name": "E*Trade", "broker": "snaptrade"},
        {"account_id": "acc-2", "account_number": "5678", "institution_name": "Fidelity", "broker": "snaptrade"},
    ]
    kept, shadowed, warnings = router.merge_accounts(Masked().list_accounts(), snap)
    assert shadowed == [{"snaptrade_account_id": "acc-1", "direct_account_id": "KEY1", "broker": "etrade"}]
    assert [r["account_id"] for r in kept] == ["KEY1", "KEY2", "acc-9", "acc-2"]
    assert warnings == [{"snaptrade_account_id": "acc-9", "broker": "etrade", "code": "POSSIBLE_DUPLICATE"}]  # Fidelity untouched


def test_shadowed_snaptrade_account_cannot_trade(sdk, tmp_path: Path) -> None:
    from second_opinion.brokerage import OrderSpec

    reg = registry.Registry(tmp_path / "brokers.json")
    hub = router.Hub([StubDirect(), SnapTradeBroker(sdk)], account_types={}, registry=reg)
    hub.list_accounts()
    assert json.loads((tmp_path / "brokers.json").read_text())["accounts"]["acc-1"]["shadowed_by"] == "KEY1"
    spec = OrderSpec(account_id="acc-1", symbol="AAPL", side="BUY", quantity=1, order_type="MARKET", limit_price=None, stop_price=None, time_in_force="GOOD_FOR_DAY")
    for call in (lambda: hub.preview_order(spec), lambda: hub.place_order(spec), lambda: hub.cancel_order("acc-1", "1")):
        with pytest.raises(InvalidInput) as ei:
            call()
        assert ei.value.code == "SHADOWED_ACCOUNT" and ei.value.extra["hint"] == "use the direct account KEY1"
    # a fresh hub learns it from the registry alone
    fresh = router.Hub([StubDirect(), SnapTradeBroker(sdk)], account_types={}, registry=reg)
    with pytest.raises(InvalidInput):
        fresh.cancel_order("acc-1", "1")


def test_hub_dispatches_by_registry_and_refreshes_once(sdk, tmp_path: Path) -> None:
    reg = registry.Registry(tmp_path / "brokers.json")
    direct = StubDirect()
    hub = router.Hub([direct, SnapTradeBroker(sdk)], account_types={}, registry=reg)
    assert hub.get_portfolio("KEY2")["positions"] == [{"units": 2}]  # miss -> refresh -> direct
    assert json.loads((tmp_path / "brokers.json").read_text())["accounts"]["KEY2"]["broker"] == "etrade"
    assert hub.get_portfolio("acc-2")["positions"] == [{"units": 1}]  # snaptrade via registry
    with pytest.raises(InvalidInput) as ei:
        hub.get_portfolio("nope")
    assert ei.value.code == "UNKNOWN_ACCOUNT"


def test_hub_quote_returns_first_direct_answer_or_none(sdk) -> None:
    assert fake_hub(sdk).quote(["AAPL"]) is None
    hub = router.Hub([StubDirect(), SnapTradeBroker(sdk)], account_types={}, registry=None)
    assert hub.quote(["AAPL"])[0]["source"] == "etrade"


def test_hub_quote_swallows_broker_errors() -> None:
    class Boom(StubDirect):
        def quote(self, symbols):
            raise RuntimeError("down")

    assert router.Hub([Boom()], account_types={}, registry=None).quote(["AAPL"]) is None


def test_for_broker_raises_config_error_when_absent(sdk) -> None:
    with pytest.raises(ConfigError):
        fake_hub(sdk).for_broker("etrade")


def test_build_requires_some_credentials(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as ei:
        router.build(config.load_settings(env={}, env_file=tmp_path / "absent"))
    assert ei.value.extra["hint"] == config.NO_BROKER_HINT


def test_registry_roundtrip_and_missing_file(tmp_path: Path) -> None:
    reg = registry.Registry(tmp_path / "sub" / "brokers.json")
    assert reg.load() == {}
    reg.save([{"account_id": "a", "broker": "etrade", "account_number": "1", "institution_name": "E*TRADE", "account_type": "cash"}])
    assert reg.broker_of("a") == "etrade" and reg.broker_of("b") is None
    (tmp_path / "sub" / "brokers.json").write_text("{not json")
    assert registry.Registry(tmp_path / "sub" / "brokers.json").load() == {}


def test_registry_save_swallows_unwritable_parent_dir(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")  # so mkdir(parents=True) on a child raises OSError
    reg = registry.Registry(blocker / "brokers.json")
    reg.save([{"account_id": "a", "broker": "etrade", "account_number": "1", "institution_name": "E*TRADE", "account_type": "cash"}])  # must not raise
    assert reg.load() == {}


def test_snaptrade_etrade_row_keyed_by_account_key_is_shadowed() -> None:
    """Live SnapTrade names the brokerage "E-Trade" and reports E*Trade's accountIdKey as the number."""
    snap = [
        {"account_id": "acc-1", "account_number": "KEY1", "institution_name": "E-Trade", "broker": "snaptrade"},
        {"account_id": "acc-2", "account_number": "5678", "institution_name": "Fidelity", "broker": "snaptrade"},
    ]
    kept, shadowed, warnings = router.merge_accounts(StubDirect().list_accounts(), snap)
    assert shadowed == [{"snaptrade_account_id": "acc-1", "direct_account_id": "KEY1", "broker": "etrade"}]
    assert [r["account_id"] for r in kept] == ["KEY1", "KEY2", "acc-2"]
    assert warnings == []


def test_unmatched_snaptrade_row_at_a_hyphenated_direct_institution_is_flagged() -> None:
    snap = [{"account_id": "acc-7", "account_number": "OTHERKEY", "institution_name": "E-Trade", "broker": "snaptrade"}]
    kept, shadowed, warnings = router.merge_accounts(StubDirect().list_accounts(), snap)
    assert shadowed == []
    assert [r["account_id"] for r in kept] == ["KEY1", "KEY2", "acc-7"]
    assert warnings == [{"snaptrade_account_id": "acc-7", "broker": "etrade", "code": "POSSIBLE_DUPLICATE"}]
