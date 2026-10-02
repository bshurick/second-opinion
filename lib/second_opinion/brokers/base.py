"""The broker-agnostic surface every brokerage script talks to.

Each adapter returns exactly the dict shapes ``brokerage.py`` returns for
SnapTrade (positions, balances, orders, activities), plus a ``broker`` field on
account rows. ``quote`` returns None when the broker cannot serve quotes.
"""
from __future__ import annotations

from typing import Any, Protocol

from second_opinion.brokerage import OrderSpec

# Institution-name fragments (upper-cased) that identify a SnapTrade account as
# belonging to a brokerage that a direct adapter can also serve.
DIRECT_INSTITUTIONS: dict[str, tuple[str, ...]] = {"etrade": ("ETRADE", "E*TRADE", "E-TRADE"), "schwab": ("SCHWAB",)}


class Broker(Protocol):
    name: str

    def list_accounts(self, include_closed: bool = False) -> list[dict[str, Any]]: ...
    def get_portfolio(self, account_id: str) -> dict[str, Any]: ...
    def get_balance(self, account_id: str) -> dict[str, Any]: ...
    def list_orders(self, account_id: str, status: str | None = None, symbol: str | None = None, count: int = 25) -> list[dict[str, Any]]: ...
    def list_transactions(self, account_id: str, start: str | None = None, end: str | None = None, count: int = 50) -> dict[str, Any]: ...
    def preview_order(self, spec: OrderSpec) -> dict[str, Any]: ...
    def place_order(self, spec: OrderSpec) -> dict[str, Any]: ...
    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]: ...
    def quote(self, symbols: list[str]) -> list[dict[str, Any]] | None: ...
    def connection_status(self) -> dict[str, Any]: ...


def apply_account_types(rows: list[dict[str, Any]], overrides: dict[str, str]) -> list[dict[str, Any]]:
    """``BROKER_ACCOUNT_TYPES`` wins, then what the broker reported, then cash."""
    for r in rows:
        r["account_type"] = overrides.get(r["account_id"]) or r.get("account_type") or "cash"
    return rows
