"""A recording fake of the SnapTrade SDK surface brokerage.py touches."""
from __future__ import annotations

import json as _json
from pathlib import Path as _Path
from types import SimpleNamespace
from typing import Any


class SdkError(Exception):
    """Mimics snaptrade_client.exceptions.ApiException: ``status`` + JSON ``body``."""

    def __init__(self, msg: str, status: int, code: str | None = None) -> None:
        super().__init__(msg)
        self.status = status
        self.body = f'{{"detail": "{msg}", "status_code": {status}, "code": "{code}"}}' if code else None


class _Resp:
    def __init__(self, body: Any) -> None:
        self.body = body


class FakeSdk:
    """Each method returns a canned body and records kwargs in ``calls``."""

    def __init__(self, **bodies: Any) -> None:
        self.bodies = bodies
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.account_information = SimpleNamespace(
            list_user_accounts=self._m("list_user_accounts"),
            get_user_account_positions=self._m("get_user_account_positions"),
            get_user_account_balance=self._m("get_user_account_balance"),
            get_user_account_orders=self._m("get_user_account_orders"),
        )
        # SDK >= 13 dropped get_user_account_positions for get_all_account_positions.
        # Only expose the new method when a test supplies a body for it, so the
        # default fake still looks like SDK 12.
        if "get_all_account_positions" in bodies:
            self.account_information.get_all_account_positions = self._m("get_all_account_positions")
        self.connections = SimpleNamespace(
            list_brokerage_authorizations=self._m("list_brokerage_authorizations"),
            remove_brokerage_authorization=self._m("remove_brokerage_authorization"),
        )
        self.reference_data = SimpleNamespace(
            symbol_search_user_account=self._m("symbol_search_user_account"),
            list_all_brokerages=self._m("list_all_brokerages"),
        )
        self.trading = SimpleNamespace(
            get_order_impact=self._m("get_order_impact"),
            place_order=self._m("place_order"),
            cancel_user_account_order=self._m("cancel_user_account_order"),
        )
        # SDK >= 13 dropped transactions_and_reporting.get_activities for the
        # account-scoped account_information.get_account_activities. As with positions,
        # the fake only looks like SDK 13 when a test supplies the new method's body.
        if "get_account_activities" in bodies:
            self.account_information.get_account_activities = self._m("get_account_activities")
        else:
            self.transactions_and_reporting = SimpleNamespace(get_activities=self._m("get_activities"))
        self.authentication = SimpleNamespace(
            login_snap_trade_user=self._m("login_snap_trade_user"),
            register_snap_trade_user=self._m("register_snap_trade_user"),
        )

    def _m(self, name: str):
        def call(**kwargs: Any) -> _Resp:
            self.calls.append((name, kwargs))
            body = self.bodies.get(name)
            if isinstance(body, Exception):
                raise body
            if callable(body):
                body = body(**kwargs)
            return _Resp(body)

        return call

    def kwargs_for(self, name: str) -> list[dict[str, Any]]:
        return [kw for n, kw in self.calls if n == name]


TRADE_AUTH = {"id": "auth-trade", "type": "trade", "disabled": False, "brokerage": {"name": "E*Trade", "slug": "ETRADE"}, "updated_date": "2026-01-01T00:00:00Z"}
READ_AUTH = {"id": "auth-read", "type": "read", "disabled": False, "brokerage": {"name": "Fidelity", "slug": "FIDELITY"}, "updated_date": "2026-01-01T00:00:00Z"}
ACCOUNTS = [
    {"id": "acc-1", "name": "Individual", "number": "1234", "institution_name": "E*Trade", "brokerage_authorization": "auth-trade", "meta": {"type": "INDIVIDUAL"}, "raw_type": "INDIVIDUAL", "balance": {"total": {"amount": 100.0, "currency": "USD"}}, "status": "open"},
    {"id": "acc-2", "name": "Roth", "number": "5678", "institution_name": "Fidelity", "brokerage_authorization": "auth-read", "raw_type": "ROTH", "balance": {"total": None}, "status": "open"},
]

CLOSED_ACCOUNT = {"id": "acc-3", "name": "Old 401k", "number": "9999", "institution_name": "E*Trade", "brokerage_authorization": "auth-trade", "raw_type": "IRA", "balance": {"total": {"amount": 0.0, "currency": "USD"}}, "status": "closed"}

ACCOUNTS_WITH_CLOSED = [*ACCOUNTS, CLOSED_ACCOUNT]


def fake_hub(sdk: Any, extra_brokers: tuple = ()) -> Any:
    """A Hub over a FakeSdk (plus any stub direct brokers), registry kept in memory."""
    from second_opinion import config
    from second_opinion.brokers.router import Hub
    from second_opinion.brokers.snaptrade import SnapTradeBroker

    return Hub([*extra_brokers, SnapTradeBroker(sdk)], account_types=config.load_settings().account_types, registry=None)


FIXTURES = _Path(__file__).resolve().parent / "fixtures" / "etrade"


def fixture(name: str) -> Any:
    return _json.loads((FIXTURES / name).read_text())


class FakeTransport:
    """Callable transport for ETradeBroker: routes on (method, path suffix) and records calls.

    ``routes`` maps "GET /v1/accounts/list" (path without base URL or .json) to a
    body, a (status, body) tuple, or a list of such responses consumed in order.
    """

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = {k: (list(v) if isinstance(v, list) else [v]) for k, v in routes.items()}
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def __call__(self, method: str, url: str, params: dict | None, body: dict | None, token: Any) -> tuple[int, Any]:
        path = url.split("//", 1)[-1].split("/", 1)[1]
        path = "/" + path.removesuffix(".json")
        key = f"{method} {path}"
        self.calls.append((method, path, params, body))
        queue = self.routes.get(key)
        if not queue:
            return 404, {"Error": {"code": 0, "message": f"no fake route for {key}"}}
        resp = queue.pop(0) if len(queue) > 1 else queue[0]
        return resp if isinstance(resp, tuple) else (200, resp)
