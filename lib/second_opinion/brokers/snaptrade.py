"""SnapTrade behind the Broker protocol: a thin wrapper over brokerage.py."""
from __future__ import annotations

from typing import Any

from second_opinion import brokerage
from second_opinion.brokerage import OrderSpec


class SnapTradeBroker:
    name = "snaptrade"

    def __init__(self, sdk: Any = None) -> None:
        self._sdk = sdk

    @property
    def sdk(self) -> Any:
        if self._sdk is None:
            from second_opinion import client  # lazy: SDK import maps to exit 6 inside output.run

            self._sdk = client.get_client()
        return self._sdk

    def list_accounts(self, include_closed: bool = False) -> list[dict[str, Any]]:
        rows = brokerage.list_accounts(self.sdk, include_closed=include_closed)
        for r in rows:
            r["broker"] = self.name
        return rows

    def get_portfolio(self, account_id: str) -> dict[str, Any]:
        return brokerage.get_portfolio(self.sdk, account_id)

    def get_balance(self, account_id: str) -> dict[str, Any]:
        return brokerage.get_balance(self.sdk, account_id)

    def list_orders(self, account_id: str, status: str | None = None, symbol: str | None = None, count: int = 25) -> list[dict[str, Any]]:
        return brokerage.list_orders(self.sdk, account_id, status=status, symbol=symbol, count=count)

    def list_transactions(self, account_id: str, start: str | None = None, end: str | None = None, count: int = 50) -> dict[str, Any]:
        return brokerage.list_transactions(self.sdk, account_id, start=start, end=end, count=count)

    def preview_order(self, spec: OrderSpec) -> dict[str, Any]:
        out = brokerage.preview_order(self.sdk, spec)
        out["broker"] = self.name
        return out

    def place_order(self, spec: OrderSpec) -> dict[str, Any]:
        out = brokerage.place_order(self.sdk, spec)
        out["broker"] = self.name
        return out

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        return brokerage.cancel_order(self.sdk, account_id, order_id)

    def quote(self, symbols: list[str]) -> list[dict[str, Any]] | None:
        return None

    def connection_status(self) -> dict[str, Any]:
        return {"id": "snaptrade", "broker": self.name, "status": "configured"}
