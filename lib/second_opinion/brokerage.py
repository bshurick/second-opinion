"""SnapTrade calls behind plain functions that take an injected ``sdk``.

Personal API key mode: no user_id / user_secret anywhere. Responses are
returned as plain dicts in the shape the SKILL.md field descriptions
rely on. One attempt per call; failures raise ApiError.
"""
from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from second_opinion.errors import ApiError, InvalidInput

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")
ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


# The SnapTrade user registered under the personal key. Kept as the plugin's
# original name on purpose: a personal key has exactly one user slot, and
# renaming this would orphan every brokerage connection made before the
# plugin was renamed to second-opinion.
PERSONAL_USER_ID = "snaptrade-finance-self"
NO_USER_CODE = "1083"  # "Invalid userID or userSecret provided"
NO_TRADE_TYPE_CODE = "1012"  # "<BROKER> does not have a trade type available"
_healed = False


def _error_code(exc: Exception) -> str | None:
    """SnapTrade's numeric error code from an SDK exception body, if any."""
    body = getattr(exc, "body", None)
    if isinstance(body, bytes):
        body = body.decode(errors="replace")
    if isinstance(body, dict):
        return str(body.get("code")) if body.get("code") is not None else None
    if isinstance(body, str):
        m = re.search(r'"code"\s*:\s*"?(\d+)"?', body)
        return m.group(1) if m else None
    return None


def _api_error(exc: Exception) -> ApiError:
    return ApiError(str(exc), http_status=getattr(exc, "status", None), snaptrade_code=_error_code(exc))


def ensure_personal_user() -> str:
    """Make sure the key has its single registered user.

    SnapTrade resolves a Personal API key to the one user registered under it.
    If that user was deleted (for example by a teardown script), every
    personal-mode call fails with code 1083 until a user exists again.
    Registration is idempotent: an existing user (code 1010) counts as success.
    """
    from second_opinion import client as _client  # local import: avoids a cycle

    comm = _client.get_commercial_client()
    try:
        comm.authentication.register_snap_trade_user(user_id=PERSONAL_USER_ID)
    except Exception as e:  # noqa: BLE001
        if _error_code(e) != "1010":
            raise _api_error(e) from e
    return PERSONAL_USER_ID


def _call(fn: Callable[..., Any], **kwargs: Any) -> Any:
    global _healed
    try:
        return fn(**kwargs).body
    except Exception as e:  # noqa: BLE001
        if _error_code(e) == NO_USER_CODE and not _healed:
            _healed = True
            ensure_personal_user()
            try:
                return fn(**kwargs).body
            except Exception as e2:  # noqa: BLE001
                raise _api_error(e2) from e2
        raise _api_error(e) from e


def validate_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not SYMBOL_RE.match(s):
        raise InvalidInput(f"invalid symbol {symbol!r}")
    return s


def validate_account_id(account_id: str) -> str:
    s = (account_id or "").strip()
    if not ACCOUNT_ID_RE.match(s):
        raise InvalidInput(f"invalid account id {account_id!r}")
    return s


# ── read ────────────────────────────────────────────────────────────────────

def list_authorizations(sdk: Any) -> list[dict[str, Any]]:
    return list(_call(sdk.connections.list_brokerage_authorizations) or [])


def _trade_auth_ids(auths: list[dict[str, Any]]) -> set[str]:
    return {a.get("id") for a in auths if (a.get("type") or "").lower() == "trade"}


def list_accounts(sdk: Any, include_closed: bool = False) -> list[dict[str, Any]]:
    raw = _call(sdk.account_information.list_user_accounts) or []
    trade_ids = _trade_auth_ids(list_authorizations(sdk))
    out = []
    for a in raw:
        status = a.get("status")
        if status and status != "open" and not include_closed:
            continue
        total = (a.get("balance") or {}).get("total") or {}
        out.append(
            {
                "account_id": a["id"],
                "name": a.get("name", ""),
                "account_number": a.get("number", ""),
                "institution_name": a.get("institution_name", ""),
                "brokerage_authorization": a.get("brokerage_authorization"),
                "supports_trading": a.get("brokerage_authorization") in trade_ids,
                "raw_type": a.get("raw_type") or (a.get("meta") or {}).get("type"),
                "balance_total": total.get("amount") if isinstance(total, dict) else None,
                "status": status,
            }
        )
    return out


def _to_float(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _normalize_position(p: dict[str, Any]) -> dict[str, Any]:
    """Map an SDK >= 13 ``/positions/all`` row onto the legacy position shape
    ({"symbol": {"symbol": {...}}, "units", "price", "average_purchase_price",
    "open_pnl", "currency", "cash_equivalent"}) that every skill script walks.

    v13 sends decimal strings and a per-unit ``cost_basis``; legacy sent floats
    and ``average_purchase_price`` plus a broker-computed ``open_pnl``. Both
    endpoints return the same rows for the same account (money-market sweeps
    included, flagged ``cash_equivalent``). Legacy rows pass through untouched.
    """
    if "instrument" not in p:
        return p
    inst = p.get("instrument") or {}
    units = _to_float(p.get("units"))
    price = _to_float(p.get("price"))
    cost = _to_float(p.get("cost_basis"))
    open_pnl = None
    if units is not None and price is not None and cost is not None:
        open_pnl = (price - cost) * units
    sym = {
        "symbol": inst.get("symbol") or inst.get("raw_symbol"),
        "raw_symbol": inst.get("raw_symbol"),
        "description": inst.get("description"),
        "currency": inst.get("currency"),
        "exchange": inst.get("exchange"),
        "type": inst.get("kind"),
    }
    out: dict[str, Any] = {
        "symbol": {"id": inst.get("id"), "symbol": sym, "description": inst.get("description")},
        "units": units,
        "price": price,
        "average_purchase_price": cost,
        "open_pnl": open_pnl,
        "currency": p.get("currency") or inst.get("currency"),
    }
    if "cash_equivalent" in p:
        out["cash_equivalent"] = p["cash_equivalent"]
    return out


def list_brokerages(sdk: Any) -> list[dict[str, Any]]:
    raw = _call(sdk.reference_data.list_all_brokerages) or []
    out = [
        {
            "name": b.get("name"),
            "slug": b.get("slug"),
            "supports_trade": b.get("allows_trading"),
            "supports_read": b.get("enabled"),
            "maintenance_mode": b.get("maintenance_mode"),
        }
        for b in raw
    ]
    out.sort(key=lambda b: (b.get("name") or ""))
    return out


def get_portfolio(sdk: Any, account_id: str) -> dict[str, Any]:
    account_id = validate_account_id(account_id)
    api = sdk.account_information
    # SDK >= 13 renamed get_user_account_positions -> get_all_account_positions and
    # returns {"results": [...], "data_freshness": {...}} instead of a bare list.
    fn = getattr(api, "get_all_account_positions", None) or api.get_user_account_positions
    raw = _call(fn, account_id=account_id)
    rows = raw.get("results") if isinstance(raw, dict) else raw
    positions = [_normalize_position(dict(r)) for r in (rows or []) if isinstance(r, dict)]
    return {"account_id": account_id, "positions": positions}


def get_balance(sdk: Any, account_id: str) -> dict[str, Any]:
    account_id = validate_account_id(account_id)
    balances = _call(sdk.account_information.get_user_account_balance, account_id=account_id)
    return {"account_id": account_id, "balances": balances}


def list_orders(sdk: Any, account_id: str, status: str | None = None, symbol: str | None = None, count: int = 25) -> list[dict[str, Any]]:
    account_id = validate_account_id(account_id)
    orders = list(_call(sdk.account_information.get_user_account_orders, account_id=account_id) or [])
    if status:
        orders = [o for o in orders if (o.get("status") or "").upper() == status.upper()]
    if symbol:
        want = symbol.upper()
        orders = [
            o
            for o in orders
            if (
                (o.get("universal_symbol") or {}).get("raw_symbol")
                or (o.get("universal_symbol") or {}).get("symbol")
                or ""
            ).upper()
            == want
        ]
    return orders[:count]


def list_transactions(sdk: Any, account_id: str, start: str | None = None, end: str | None = None, count: int = 50) -> dict[str, Any]:
    account_id = validate_account_id(account_id)
    kwargs: dict[str, Any] = {}
    if start:
        kwargs["start_date"] = start
    if end:
        kwargs["end_date"] = end
    # SDK >= 13 dropped transactions_and_reporting.get_activities(accounts=...) for the
    # account-scoped account_information.get_account_activities(account_id=...), which
    # returns {"data": [...], "pagination": {...}} instead of a bare list.
    fn = getattr(sdk.account_information, "get_account_activities", None)
    if fn is not None:
        raw = _call(fn, account_id=account_id, **kwargs)
        items = raw.get("data") if isinstance(raw, dict) else raw
    else:
        items = _call(sdk.transactions_and_reporting.get_activities, accounts=account_id, **kwargs)
    items = list(items)[:count] if isinstance(items, (list, tuple)) else []
    return {"account_id": account_id, "transactions": items}


# ── trade ───────────────────────────────────────────────────────────────────

TIME_IN_FORCE = {"GOOD_FOR_DAY": "Day", "GOOD_UNTIL_CANCEL": "GTC", "IMMEDIATE_OR_CANCEL": "IOC", "FILL_OR_KILL": "FOK"}
ORDER_TYPES = {"MARKET": "Market", "LIMIT": "Limit", "STOP": "Stop", "STOP_LIMIT": "StopLimit"}
SIDES = {"BUY": "BUY", "SELL": "SELL", "BUY_TO_COVER": "BUY_COVER", "SELL_SHORT": "SELL_SHORT"}


@dataclass(frozen=True)
class OrderSpec:
    account_id: str
    symbol: str
    side: str
    quantity: int | float  # a fraction only where the broker takes one (validate_order's ``fractional``)
    order_type: str = "MARKET"
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "GOOD_FOR_DAY"


def validate_quantity(quantity: Any, fractional: bool = False) -> int | float:
    """A positive, finite share count; a whole-number float comes back as an int.

    A fraction is refused with FRACTIONAL_NOT_SUPPORTED unless ``fractional``: SnapTrade
    reports ``allows_fractional_units: False`` for E*Trade, so only the direct E*Trade
    adapter passes it (E*Trade's own order preview accepts fractional quantities).
    """
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity) or quantity <= 0:
        raise InvalidInput(f"quantity must be a positive number, got {quantity!r}")
    if float(quantity).is_integer():
        return int(quantity)
    if not fractional:
        raise InvalidInput(
            f"fractional quantity {quantity} is only supported on accounts connected directly to E*Trade; "
            "this account's broker takes whole shares",
            code="FRACTIONAL_NOT_SUPPORTED",
        )
    return float(quantity)


def validate_order(spec: OrderSpec, fractional: bool = False) -> OrderSpec:
    side, otype, tif = spec.side.upper(), spec.order_type.upper(), spec.time_in_force.upper()
    if side not in SIDES:
        raise InvalidInput(f"side must be one of {sorted(SIDES)}, got {spec.side!r}")
    if otype not in ORDER_TYPES:
        raise InvalidInput(f"order_type must be one of {sorted(ORDER_TYPES)}, got {spec.order_type!r}")
    if tif not in TIME_IN_FORCE:
        raise InvalidInput(f"time_in_force must be one of {sorted(TIME_IN_FORCE)}, got {spec.time_in_force!r}")
    quantity = validate_quantity(spec.quantity, fractional)
    if otype in ("LIMIT", "STOP_LIMIT") and spec.limit_price is None:
        raise InvalidInput(f"limit_price is required for {otype} orders")
    if otype in ("STOP", "STOP_LIMIT") and spec.stop_price is None:
        raise InvalidInput(f"stop_price is required for {otype} orders")
    return replace(spec, account_id=validate_account_id(spec.account_id), symbol=validate_symbol(spec.symbol), side=side, quantity=quantity, order_type=otype, time_in_force=tif)


def resolve_universal_symbol_id(sdk: Any, account_id: str, ticker: str) -> str:
    ticker = validate_symbol(ticker)
    results = _call(sdk.reference_data.symbol_search_user_account, account_id=account_id, substring=ticker) or []
    if not results:
        raise InvalidInput(f"SnapTrade returned no symbols for {ticker!r} on account {account_id}", code="SYMBOL_NOT_FOUND")
    for sym in results:
        if (sym.get("symbol") or "").upper() == ticker:
            return sym["id"]
    candidates = [sym.get("symbol") for sym in results[:5]]
    raise InvalidInput(f"SnapTrade returned no exact match for {ticker!r} on account {account_id}; candidates: {candidates}", code="SYMBOL_NOT_FOUND")


def require_trading(sdk: Any, account_id: str) -> dict[str, Any]:
    account_id = validate_account_id(account_id)
    for acct in list_accounts(sdk):
        if acct["account_id"] == account_id:
            if not acct["supports_trading"]:
                raise InvalidInput(
                    f"Account {account_id} ({acct['institution_name']}) is read-only: its SnapTrade connection was made "
                    "with 'read' permission. Reconnect choosing trade permission to place orders.",
                    code="READ_ONLY_ACCOUNT",
                )
            return acct
    raise InvalidInput(f"account {account_id} not found", code="ACCOUNT_NOT_FOUND")


def _manual_trade_form(body: dict[str, Any]) -> Any:
    from snaptrade_client.type.manual_trade_form import ManualTradeForm  # SDK import kept lazy for tests

    return ManualTradeForm(**body)


def _order_body(sdk: Any, spec: OrderSpec) -> dict[str, Any]:
    body: dict[str, Any] = {
        "account_id": spec.account_id,
        "action": SIDES[spec.side],
        "universal_symbol_id": resolve_universal_symbol_id(sdk, spec.account_id, spec.symbol),
        "order_type": ORDER_TYPES[spec.order_type],
        "time_in_force": TIME_IN_FORCE[spec.time_in_force],
        "units": Decimal(str(spec.quantity)),  # SDK validators require Decimal here
    }
    if spec.limit_price is not None:
        body["price"] = Decimal(str(spec.limit_price))
    if spec.stop_price is not None:
        body["stop"] = Decimal(str(spec.stop_price))
    return body


def preview_order(sdk: Any, spec: OrderSpec) -> dict[str, Any]:
    spec = validate_order(spec)
    require_trading(sdk, spec.account_id)
    impact = _call(sdk.trading.get_order_impact, body=_manual_trade_form(_order_body(sdk, spec)))
    trade = impact.get("trade") or {}
    impacts = impact.get("trade_impacts") or [{}]
    first_impact = impacts[0] if impacts else {}
    price = trade.get("price")
    units = trade.get("units")
    estimated_cost = price * units if isinstance(price, (int, float, Decimal)) and isinstance(units, (int, float, Decimal)) else None
    return {
        "trade_id": trade.get("id"),
        "price": price,
        "units": units,
        "estimated_cost": estimated_cost,
        "remaining_cash": first_impact.get("remaining_cash"),
        "estimated_commission": first_impact.get("estimated_commission"),
        "currency": first_impact.get("currency"),
        # ManualTradeImpact has no `buying_power` field per the SDK schema; this
        # will typically be None. Kept for backward compatibility.
        "estimated_buying_power": first_impact.get("buying_power"),
        "account_id": spec.account_id,
        "symbol": spec.symbol,
        "side": spec.side,
        "quantity": spec.quantity,
        "order_type": spec.order_type,
        "limit_price": spec.limit_price,
        "stop_price": spec.stop_price,
        "time_in_force": spec.time_in_force,
        "raw": impact,
    }


def place_order(sdk: Any, spec: OrderSpec) -> dict[str, Any]:
    preview = preview_order(sdk, spec)  # always fresh; a stale preview can never execute
    if not preview["trade_id"]:
        raise ApiError("SnapTrade preview returned no trade id", http_status=None)
    confirmation = _call(sdk.trading.place_order, trade_id=preview["trade_id"])
    status = confirmation.get("status")
    return {
        "order_id": confirmation.get("brokerage_order_id"),
        "status": status,
        "state": status,  # compatibility alias for `status`
        "preview": preview,
        "raw": confirmation,
    }


def cancel_order(sdk: Any, account_id: str, order_id: str) -> dict[str, Any]:
    account_id = validate_account_id(account_id)
    result = _call(sdk.trading.cancel_user_account_order, account_id=account_id, brokerage_order_id=str(order_id))
    return {"account_id": account_id, "order_id": order_id, "cancelled": True, "raw": result}


# ── connect ─────────────────────────────────────────────────────────────────

def create_login_url(sdk: Any, broker: str | None = None, reconnect: str | None = None, connection_type: str = "trade") -> str:
    kwargs: dict[str, Any] = {"connection_type": connection_type, "immediate_redirect": False}
    if broker:
        kwargs["broker"] = broker
    if reconnect:
        kwargs["reconnect"] = reconnect
    body = _call(sdk.authentication.login_snap_trade_user, **kwargs)
    return body["redirectURI"]


def wait_for_connection(
    sdk: Any,
    before: list[dict[str, Any]],
    timeout_s: float = 300,
    interval_s: float = 5,
    sleep: Callable[[float], Any] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any] | None:
    """Poll authorizations until one is new, or an existing one's updated_date moves."""
    seen = {a.get("id"): a.get("updated_date") for a in before}
    start = clock()
    while True:
        try:
            auths = list_authorizations(sdk)
        except ApiError:
            # A transient blip (e.g. a 429) should not end the poll; the
            # timeout below still bounds how long we keep trying.
            auths = []
        for auth in auths:
            aid = auth.get("id")
            if aid not in seen or (auth.get("updated_date") or "") > (seen[aid] or ""):
                return auth
        if clock() - start >= timeout_s:
            return None
        sleep(interval_s)


def delete_authorization(sdk: Any, authorization_id: str) -> dict[str, Any]:
    _call(sdk.connections.remove_brokerage_authorization, authorization_id=authorization_id)
    return {"authorization_id": authorization_id, "deleted": True}


def open_connection(
    sdk: Any, broker: str | None = None, reconnect: str | None = None, connection_type: str = "trade"
) -> dict[str, Any]:
    """Portal URL for a new/relinked connection, downgrading to a read-only
    connection when the brokerage offers no trade type (SnapTrade code 1012,
    e.g. the SANDBOX brokerage)."""
    requested = connection_type
    try:
        url = create_login_url(sdk, broker=broker, reconnect=reconnect, connection_type=connection_type)
    except ApiError as e:
        if e.extra.get("snaptrade_code") != NO_TRADE_TYPE_CODE or connection_type == "read":
            raise
        connection_type = "read"
        url = create_login_url(sdk, broker=broker, reconnect=reconnect, connection_type="read")
    return {"url": url, "connection_type": connection_type, "requested_connection_type": requested}
