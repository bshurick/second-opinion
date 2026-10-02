"""E*Trade REST API behind the Broker protocol, emitting SnapTrade-shaped dicts.

Endpoints (all suffixed .json): /v1/accounts/list, /v1/accounts/{key}/balance,
/v1/accounts/{key}/portfolio, /v1/accounts/{key}/orders[/preview|/place|/cancel],
/v1/accounts/{key}/transactions, /v1/market/quote/{symbols}.
"""
from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from second_opinion.brokerage import OrderSpec, validate_account_id, validate_order
from second_opinion.brokers.etrade_auth import REAUTH_HINT, ETradeAuth, Token, load_token, token_state
from second_opinion.errors import ApiError, ConfigError, InvalidInput

PROD_BASE = "https://api.etrade.com"
SANDBOX_BASE = "https://apisb.etrade.com"
MAX_PAGES = 20
QUOTE_BATCH = 25
# E*Trade's fractional-share rules (its help center, 2026): up to 3 decimals, buys at least
# $5.00, under one share market orders only, no good-till-cancelled; no fractional shorts.
FRACTION_DECIMALS = 3
FRACTION_MIN_NOTIONAL = 5.0
SECURITY_TYPE_CODES = {"EQ": "cs", "MF": "mf", "OPTN": "op", "BOND": "bnd"}

Transport = Callable[[str, str, dict[str, Any] | None, dict[str, Any] | None, Token], tuple[int, Any]]


def requests_transport(auth: ETradeAuth) -> Transport:
    def call(method: str, url: str, params: dict[str, Any] | None, body: dict[str, Any] | None, token: Token) -> tuple[int, Any]:
        import requests  # lazy: missing package -> exit 6
        from requests_oauthlib import OAuth1

        oauth = OAuth1(auth.settings.consumer_key, auth.settings.consumer_secret, token.oauth_token, token.oauth_token_secret)
        try:
            r = requests.request(method, url, params=params, json=body, auth=oauth, headers={"Accept": "application/json"}, timeout=30)
        except requests.RequestException as e:
            raise ApiError(f"E*Trade request failed: {e}", http_status=None) from e
        if not r.content:
            return r.status_code, {}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:500]}

    return call


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _ms_to_iso(ms: Any) -> str | None:
    f = _f(ms)
    return None if f is None else datetime.fromtimestamp(f / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _error(status: int, body: Any) -> ApiError:
    err = body.get("Error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        code = err.get("code")
        return ApiError(f"E*Trade error {code}: {err.get('message')}", http_status=status, etrade_code=str(code) if code is not None else None)
    return ApiError(f"E*Trade HTTP {status}", http_status=status, etrade_code=None)


# ── pure mappers ────────────────────────────────────────────────────────────

def map_account(raw: dict[str, Any], balance_total: float | None) -> dict[str, Any]:
    status = str(raw.get("accountStatus") or "").upper()
    return {
        "account_id": raw.get("accountIdKey"),
        "name": raw.get("accountName") or raw.get("accountDesc") or "",
        "account_number": str(raw.get("accountId") or ""),
        "institution_name": "E*TRADE",
        "brokerage_authorization": "etrade",
        "supports_trading": True,
        "raw_type": raw.get("accountType"),
        "balance_total": balance_total,
        "status": "open" if status == "ACTIVE" else status.lower() or None,
        "account_type": "margin" if str(raw.get("accountMode") or "").upper() == "MARGIN" else "cash",
        "broker": "etrade",
    }


def map_balance(raw: dict[str, Any]) -> dict[str, Any]:
    resp = raw.get("BalanceResponse") or raw
    computed = resp.get("Computed") or {}
    rt = computed.get("RealTimeValues") or {}
    mode = str(resp.get("accountMode") or "").upper()
    # netCash is deliberately NOT used: in a margin account it equals cashBuyingPower
    # (the withdrawable margin credit line), so reading it as cash double-counts the
    # positions it is borrowed against. The cash is what the account is worth beyond
    # its positions: that identity includes the sweep money market (Cash.moneyMktBalance)
    # net of any margin debit, which Computed.cashBalance leaves out -- an account
    # can report cashBalance 0 beside a sweep balance and a small margin debit, and reading
    # cashBalance would drop that net sweep cash from the account. cashBalance is only the fallback when the
    # real-time values are missing.
    total, net_mv = _f(rt.get("totalAccountValue")), _f(rt.get("netMv"))
    cash = round(total - net_mv, 2) if total is not None and net_mv is not None else _f(computed.get("cashBalance"))
    bp = _f(computed.get("marginBuyingPower")) if mode == "MARGIN" else _f(computed.get("cashBuyingPower"))
    return {
        "currency": {"code": "USD"},
        "cash": cash,
        "buying_power": bp,
        "settled_cash": _f(computed.get("settledCashForInvestment")),
        "unsettled_cash": _f(computed.get("unSettledCashForInvestment")),
        "total_account_value": _f(rt.get("totalAccountValue")),
        "account_mode": mode or None,
    }


def map_position(raw: dict[str, Any]) -> dict[str, Any]:
    product = raw.get("Product") or {}
    quick = raw.get("Quick") or {}
    sym = product.get("symbol")
    sec_type = str(product.get("securityType") or "EQ").upper()
    units = _f(raw.get("quantity"))
    if units is not None and str(raw.get("positionType") or "").upper() == "SHORT":
        units = -abs(units)
    desc = raw.get("symbolDescription")
    return {
        "symbol": {
            "id": sym,
            "symbol": {"symbol": sym, "raw_symbol": sym, "description": desc, "currency": "USD", "exchange": None, "type": {"code": SECURITY_TYPE_CODES.get(sec_type, "cs"), "description": sec_type}},
            "description": desc,
        },
        "units": units,
        "price": _f(quick.get("lastTrade")),
        "average_purchase_price": _f(raw.get("pricePaid")),
        "open_pnl": _f(raw.get("totalGain")),
        "currency": "USD",
        "cash_equivalent": False,
    }


DEFAULT_WINDOW_DAYS = 90
TRANSACTION_TYPES = {"BOUGHT": "BUY", "SOLD": "SELL", "DIVIDEND": "DIVIDEND", "INTEREST": "INTEREST", "FEE": "FEE", "REINVESTMENT": "REI"}
TRANSFER_TYPES = {"TRANSFER", "CONTRIBUTION", "DEPOSIT", "ONLINE TRANSFER", "WIRE", "ACH"}


def _mmddyyyy(iso: str | None, default: datetime) -> str:
    if not iso:
        return default.strftime("%m%d%Y")
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
    except ValueError as e:
        raise InvalidInput(f"invalid date {iso!r}: use YYYY-MM-DD") from e
    return d.strftime("%m%d%Y")


def _ms_to_date(ms: Any) -> str | None:
    iso = _ms_to_iso(ms)
    return iso[:10] if iso else None


def map_orders(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for order in (raw.get("OrdersResponse") or {}).get("Order") or []:
        for detail in order.get("OrderDetail") or []:
            for inst in detail.get("Instrument") or []:
                sym = (inst.get("Product") or {}).get("symbol")
                rows.append({
                    "brokerage_order_id": str(order.get("orderId")),
                    "status": str(detail.get("status") or "").upper() or None,
                    "universal_symbol": {"symbol": sym, "raw_symbol": sym},
                    "action": inst.get("orderAction"),
                    "total_quantity": _f(inst.get("orderedQuantity")),
                    "filled_quantity": _f(inst.get("filledQuantity")),
                    "execution_price": _f(inst.get("averageExecutionPrice")),
                    "order_type": detail.get("priceType"),
                    "time_in_force": detail.get("orderTerm"),
                    "limit_price": _f(detail.get("limitPrice")) or None,
                    "stop_price": _f(detail.get("stopPrice")) or None,
                    "time_placed": _ms_to_iso(detail.get("placedTime")),
                    "time_executed": _ms_to_iso(detail.get("executedTime")),
                    "broker": "etrade",
                })
    return rows


def map_transaction(raw: dict[str, Any], account_id: str) -> dict[str, Any]:
    brok = raw.get("brokerage") or {}
    product = brok.get("product") or {}
    sym = product.get("symbol") or None
    amount = _f(raw.get("amount"))
    kind_raw = str(raw.get("transactionType") or "").strip().upper()
    if kind_raw in TRANSACTION_TYPES:
        kind = TRANSACTION_TYPES[kind_raw]
    elif kind_raw in TRANSFER_TYPES:
        kind = "CONTRIBUTION" if (amount or 0) >= 0 else "WITHDRAWAL"
    else:
        kind = kind_raw.replace(" ", "_") or "UNKNOWN"
    units = _f(brok.get("quantity"))
    desc = raw.get("description")
    return {
        "id": str(raw.get("transactionId")),
        "account": {"id": account_id},
        "trade_date": _ms_to_date(raw.get("transactionDate")),
        "settlement_date": _ms_to_date(brok.get("settlementDate")),
        "type": kind,
        "units": abs(units) if units else None,
        "price": _f(brok.get("price")) or None,
        "amount": amount,
        "fee": abs(_f(brok.get("fee")) or 0.0),
        "symbol": {"symbol": sym, "raw_symbol": brok.get("displaySymbol") or sym, "description": desc} if sym else None,
        "currency": {"code": "USD"},
        "description": desc,
    }


def map_quotes(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Quotes from either block E*Trade answers with.

    A stock comes back under ``All`` with ``lastTrade``; a mutual fund comes back under
    ``MutualFund`` with ``navValue`` and, for a money market fund, ``sevenDayCurrentYield``.
    Reading only ``All`` dropped every fund, so ``quote.py`` fell through to Yahoo, which
    prices a money market fund at its $1.00 NAV and carries no yield at all — the figure
    the caller was asking for was already in the response.
    """
    out = []
    for q in (raw.get("QuoteResponse") or {}).get("QuoteData") or []:
        sym = (q.get("Product") or {}).get("symbol")
        if not sym:
            continue
        # A stock's fields arrive under "All", a fund's under "MutualFund", and the two
        # blocks share names: lastTrade, previousClose, changeClosePercentage. Only the
        # fund block carries netAssetValue and sevenDayCurrentYield. Field names match
        # E*Trade's actual responses -- a fund quote's price is netAssetValue or lastTrade,
        # and there is no "navValue".
        block = q.get("All") or q.get("MutualFund") or {}
        fund = q.get("MutualFund") or {}
        price = _f(block.get("lastTrade"))
        if price is None:
            price = _f(fund.get("netAssetValue"))
        if price is None:
            continue
        ts = _f(q.get("dateTimeUTC"))
        out.append({
            "symbol": str(sym).upper(),
            "price": price,
            "previous_close": _f(block.get("previousClose")),
            "change_pct": _f(block.get("changeClosePercentage")),
            # None for anything that is not a money market fund; E*Trade reports it as a
            # percentage already (3.7745 means 3.7745%).
            "seven_day_yield": _f(fund.get("sevenDayCurrentYield")),
            "currency": "USD",
            "source": "etrade",
            "realtime": str(q.get("quoteStatus") or "").upper() == "REALTIME",
            "as_of": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds") if ts else None,
        })
    return out


def validate_fraction(spec: OrderSpec) -> OrderSpec:
    """E*Trade's fractional-share rules that can be checked before any call; ``spec`` is validated."""
    q = spec.quantity
    if isinstance(q, int):
        return spec
    if round(q, FRACTION_DECIMALS) != q:
        raise InvalidInput(f"E*Trade takes fractional quantities to at most {FRACTION_DECIMALS} decimals, got {q}", code="FRACTIONAL_PRECISION")
    if spec.side == "SELL_SHORT":
        raise InvalidInput("E*Trade does not take fractional short sales", code="FRACTIONAL_SHORT")
    if q < 1 and spec.order_type != "MARKET":
        raise InvalidInput(f"E*Trade takes an order under one share ({q}) as a MARKET order only", code="FRACTIONAL_MARKET_ONLY")
    if spec.time_in_force == "GOOD_UNTIL_CANCEL":
        raise InvalidInput("E*Trade does not take good-till-cancelled orders for fractional quantities", code="FRACTIONAL_TERM")
    return spec


def new_client_order_id() -> str:
    """E*Trade only accepts a numeric client order id (<= 20 digits)."""
    return str(secrets.randbelow(9_000_000_000) + 1_000_000_000)


def order_body(spec: OrderSpec, client_order_id: str, preview_ids: list[int] | None = None) -> dict[str, Any]:
    order: dict[str, Any] = {
        "allOrNone": False,
        "priceType": spec.order_type,
        "orderTerm": spec.time_in_force,
        "marketSession": "REGULAR",
    }
    if spec.limit_price is not None:
        order["limitPrice"] = spec.limit_price
    if spec.stop_price is not None:
        order["stopPrice"] = spec.stop_price
    order["Instrument"] = [{"Product": {"securityType": "EQ", "symbol": spec.symbol}, "orderAction": spec.side, "quantityType": "QUANTITY", "quantity": spec.quantity}]
    req: dict[str, Any] = {"orderType": "EQ", "clientOrderId": client_order_id}
    if preview_ids is not None:
        req["PreviewIds"] = [{"previewId": p} for p in preview_ids]
    req["Order"] = [order]
    return {"PlaceOrderRequest" if preview_ids is not None else "PreviewOrderRequest": req}


# ── the broker ──────────────────────────────────────────────────────────────

class ETradeBroker:
    name = "etrade"

    def __init__(self, auth: ETradeAuth, transport: Transport | None = None) -> None:
        self.auth = auth
        self._transport = transport or requests_transport(auth)

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE if self.auth.settings.sandbox else PROD_BASE

    def _expired(self, reauth: bool) -> Exception:
        return self.auth.reauth_error() if reauth else ApiError("E*Trade token expired", http_status=401)

    def _token_state(self) -> str:
        return token_state(load_token(), self.auth.settings.sandbox, self.auth._now())

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None, reauth: bool = True) -> dict[str, Any]:
        """``reauth=False`` never starts a new authorization (no network, no pending file)."""
        if not reauth and self._token_state() != "usable":
            raise self._expired(False)  # usable_token() would issue a request token
        token = self.auth.usable_token()
        url = f"{self.base_url}{path}.json"
        status, body = self._transport(method, url, params, json, token)
        if status == 401:
            if not self.auth.renew(token):
                raise self._expired(reauth)
            status, body = self._transport(method, url, params, json, token)
            if status == 401:
                raise self._expired(reauth)  # renewed and still refused: the token is dead
        if status == 204:
            return {}
        if status >= 400:
            raise _error(status, body)
        return body if isinstance(body, dict) else {}

    # ── accounts ─────────────────────────────────────────────────────────
    def _raw_accounts(self) -> list[dict[str, Any]]:
        body = self._request("GET", "/v1/accounts/list")
        accounts = ((body.get("AccountListResponse") or {}).get("Accounts") or {}).get("Account") or []
        return [a for a in accounts if isinstance(a, dict) and a.get("accountIdKey")]

    def login_url(self) -> str:
        """Start (or reuse) today's authorization and return the URL the user signs in at."""
        return self.auth.start()["url"]

    def list_accounts(self, include_closed: bool = False) -> list[dict[str, Any]]:
        # A listing is a background call in every multi-broker script: report the
        # missing login without issuing a URL. The router decides whether to stop and
        # ask for a login (login_url) or run without this broker (--partial).
        state = self._token_state()
        if state != "usable":
            raise ConfigError(f"E*Trade login required (token {state})", code="ETRADE_REAUTH", hint=REAUTH_HINT, sandbox=self.auth.settings.sandbox)
        out = []
        for raw in self._raw_accounts():
            is_open = str(raw.get("accountStatus") or "").upper() == "ACTIVE"
            if not is_open and not include_closed:
                continue
            total = None
            mode = None
            if is_open:
                try:
                    bal = map_balance(self._request("GET", f"/v1/accounts/{raw['accountIdKey']}/balance", {"instType": "BROKERAGE", "realTimeNAV": "true"}))
                    total, mode = bal["total_account_value"], bal["account_mode"]
                except ApiError:
                    total = None  # a balance hiccup must not hide the account
            row = map_account(raw, total)
            # The account list's accountMode lags a cash-to-margin conversion; the balance
            # endpoint reports the live mode, so it wins whenever the balance call succeeded.
            if mode:
                row["account_type"] = "margin" if mode == "MARGIN" else "cash"
            out.append(row)
        return out

    def get_balance(self, account_id: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        body = self._request("GET", f"/v1/accounts/{account_id}/balance", {"instType": "BROKERAGE", "realTimeNAV": "true"})
        return {"account_id": account_id, "balances": [map_balance(body)]}

    def get_portfolio(self, account_id: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        positions: list[dict[str, Any]] = []
        params: dict[str, Any] = {"view": "QUICK", "count": 200}
        for _ in range(MAX_PAGES):
            body = self._request("GET", f"/v1/accounts/{account_id}/portfolio", params)
            portfolios = (body.get("PortfolioResponse") or {}).get("AccountPortfolio") or []
            next_page = None
            for ap in portfolios:
                positions.extend(map_position(p) for p in (ap.get("Position") or []) if isinstance(p, dict))
                next_page = ap.get("nextPageNo") or next_page
            if not next_page:
                break
            params = {**params, "pageNumber": str(next_page)}
        return {"account_id": account_id, "positions": positions}

    # ── status ───────────────────────────────────────────────────────────
    def connection_status(self) -> dict[str, Any]:
        return {"id": "etrade", "broker": "etrade", "type": "trade", "status": self._token_state(), "sandbox": self.auth.settings.sandbox}

    # ── orders, transactions, quotes ────────────────────────────────────────
    def list_orders(self, account_id: str, status: str | None = None, symbol: str | None = None, count: int = 25) -> list[dict[str, Any]]:
        account_id = validate_account_id(account_id)
        params: dict[str, Any] = {"count": count}
        if status:
            params["status"] = status.upper()
        if symbol:
            params["symbol"] = symbol.upper()
        rows: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            body = self._request("GET", f"/v1/accounts/{account_id}/orders", params)
            rows.extend(map_orders(body))
            marker = (body.get("OrdersResponse") or {}).get("marker")
            if len(rows) >= count or not marker:
                break
            params = {**params, "marker": marker}
        # belt and braces: the server-side filters above are advisory
        if status:
            rows = [r for r in rows if (r.get("status") or "") == status.upper()]
        if symbol:
            rows = [r for r in rows if (r["universal_symbol"].get("symbol") or "").upper() == symbol.upper()]
        return rows[:count]

    def list_transactions(self, account_id: str, start: str | None = None, end: str | None = None, count: int = 50) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        now = self.auth._now()
        params: dict[str, Any] = {"startDate": _mmddyyyy(start, now - timedelta(days=DEFAULT_WINDOW_DAYS)), "endDate": _mmddyyyy(end, now), "count": 50}
        items: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            body = self._request("GET", f"/v1/accounts/{account_id}/transactions", params)
            resp = body.get("TransactionListResponse") or {}
            items.extend(map_transaction(t, account_id) for t in (resp.get("Transaction") or []) if isinstance(t, dict))
            if len(items) >= count or not resp.get("moreTransactions") or not resp.get("marker"):
                break
            params = {**params, "marker": resp["marker"]}
        return {"account_id": account_id, "transactions": items[:count]}

    def quote(self, symbols: list[str]) -> list[dict[str, Any]] | None:
        if self._token_state() != "usable":
            return None
        syms = list(dict.fromkeys(s.upper() for s in symbols if s))
        out: list[dict[str, Any]] = []
        try:
            for i in range(0, len(syms), QUOTE_BATCH):
                batch = syms[i : i + QUOTE_BATCH]
                # quotes are best-effort: Yahoo is the fallback, so never start a login here
                out.extend(map_quotes(self._request("GET", f"/v1/market/quote/{','.join(batch)}", {"detailFlag": "ALL"}, reauth=False)))
        except (ApiError, ConfigError):
            return None
        return out

    # ── preview, place, cancel ───────────────────────────────────────────────
    def _preview(self, spec: OrderSpec, client_order_id: str) -> dict[str, Any]:
        spec = validate_fraction(validate_order(spec, fractional=True))
        balance = self.get_balance(spec.account_id)["balances"][0]
        raw = self._request("POST", f"/v1/accounts/{spec.account_id}/orders/preview", json=order_body(spec, client_order_id))
        resp = raw.get("PreviewOrderResponse") or {}
        ids = [p.get("previewId") for p in resp.get("PreviewIds") or [] if isinstance(p, dict) and p.get("previewId") is not None]
        order = (resp.get("Order") or [{}])[0]
        total = _f(order.get("estimatedTotalAmount"))
        if isinstance(spec.quantity, float) and spec.side in ("BUY", "BUY_TO_COVER") and total is not None and total < FRACTION_MIN_NOTIONAL:
            raise InvalidInput(f"E*Trade's minimum for a fractional buy is ${FRACTION_MIN_NOTIONAL:.2f}; this one is about ${total:.2f}", code="FRACTIONAL_MINIMUM")
        price = (total / spec.quantity) if total is not None and spec.quantity else (spec.limit_price if spec.limit_price is not None else None)
        cash = balance.get("cash")
        remaining = (cash - total) if spec.side in ("BUY", "BUY_TO_COVER") and cash is not None and total is not None else cash
        flags: list[dict[str, Any]] = []
        settled = balance.get("settled_cash")
        if spec.side in ("BUY", "BUY_TO_COVER") and balance.get("account_mode") != "MARGIN" and total is not None and settled is not None and total > settled:
            flags.append({"code": "UNSETTLED_CASH", "message": f"estimated cost {total} exceeds settled cash {settled}; buying with unsettled funds and selling before settlement is a good-faith violation"})
        return {
            "trade_id": str(ids[0]) if ids else None,
            "price": price,
            "units": spec.quantity,
            "estimated_cost": total,
            "remaining_cash": remaining,
            "estimated_commission": _f(order.get("estimatedCommission")),
            "currency": "USD",
            "estimated_buying_power": None,
            "account_id": spec.account_id,
            "symbol": spec.symbol,
            "side": spec.side,
            "quantity": spec.quantity,
            "order_type": spec.order_type,
            "limit_price": spec.limit_price,
            "stop_price": spec.stop_price,
            "time_in_force": spec.time_in_force,
            "broker": "etrade",
            "client_order_id": client_order_id,
            "flags": flags,
            "_preview_ids": ids,
            "raw": raw,
        }

    def preview_order(self, spec: OrderSpec) -> dict[str, Any]:
        out = self._preview(spec, new_client_order_id())
        out.pop("_preview_ids", None)
        return out

    def place_order(self, spec: OrderSpec) -> dict[str, Any]:
        spec = validate_fraction(validate_order(spec, fractional=True))
        client_order_id = new_client_order_id()
        preview = self._preview(spec, client_order_id)  # always fresh; a stale preview can never execute
        ids = preview.pop("_preview_ids", [])
        if not ids:
            raise ApiError("E*Trade preview returned no preview id", http_status=None)
        raw = self._request("POST", f"/v1/accounts/{spec.account_id}/orders/place", json=order_body(spec, client_order_id, preview_ids=ids))
        resp = raw.get("PlaceOrderResponse") or {}
        order_ids = [o.get("orderId") for o in resp.get("OrderIds") or [] if isinstance(o, dict) and o.get("orderId") is not None]
        if not order_ids:
            # the order may or may not exist at E*Trade: say so instead of returning a null id
            raise ApiError("E*Trade place returned no order id", http_status=None)
        status = ((resp.get("Order") or [{}])[0]).get("status") or "OPEN"
        return {"order_id": str(order_ids[0]), "status": status, "state": status, "preview": preview, "broker": "etrade", "raw": raw}

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        account_id = validate_account_id(account_id)
        if not str(order_id).isdigit():
            raise InvalidInput("E*Trade order ids are numeric")
        raw = self._request("PUT", f"/v1/accounts/{account_id}/orders/cancel", json={"CancelOrderRequest": {"orderId": int(order_id)}})
        return {"account_id": account_id, "order_id": str(order_id), "cancelled": True, "raw": raw}
