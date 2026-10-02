"""Canonical portfolio snapshot: totals, per-account and per-symbol figures,
concentration, movers, upcoming events, and flags.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python summary.py < input.json

Exit code is 0 on success (result JSON on stdout) or 2 on invalid input
(stdout is ``{"error": "..."}``). The script is deterministic: every list
has a fixed sort order, so two runs over the same data render the same.

Input JSON contract (stdin)::

    {
      "accounts": [                       # required, at least one
        {
          "account_id": "acc-1",          # required, unique
          "name": "Individual",           # optional
          "institution_name": "E*Trade",  # optional
          "account_type": "cash",         # optional ("cash" | "margin")
          "supports_trading": true,       # optional
          "cash": 500.0,                  # optional; OR "balances": [SnapTrade
                                          #   balance objects] whose "cash"
                                          #   fields are summed
          "positions": [                  # optional, default []
            {
              "symbol": "AAPL",           # str, OR the raw SnapTrade nested
                                          #   object {"symbol": {"symbol": "AAPL",
                                          #   "description": "Apple Inc."}}
              "units": 10,
              "price": 100.0,             # broker price; null -> MISSING_PRICE
              "average_purchase_price": 80.0,   # optional -> cost basis
              "open_pnl": 200.0           # optional fallback when no avg price
            }
          ]
        }
      ],
      "quotes":  {"AAPL": {"price": 101.0, "previous_close": 99.0}},  # optional;
                                          # "price" overrides the broker price,
                                          # "day_change_pct" may replace previous_close
      "sectors": {"AAPL": "Technology"},  # optional; missing symbol -> "Unknown"
      "events":  {"AAPL": {"next_earnings": "2026-10-01",
                           "next_ex_dividend": "2026-09-10"}},         # optional
      "history": {"AAPL": [{"date": "2026-08-01", "close": 90.0}, ...]},
                                          # optional; daily closes per symbol ->
                                          #   1w/1m change (symbol keys uppercased)
      "asset_info": {"AAPL": {name, quote_type, category, country, sector,
                              fund_sectors, fund_asset_classes, proxy}}
                                           # optional; drives "allocation" (bonds / US equity /
                                           # international equity / cash / other, see asset_bucket)
                                           # and stands in for "quote_types" when that is absent;
                                           # sector is a fallback stock sector used only for a
                                           # symbol "sectors" (above) doesn't cover; fund_sectors
                                           # (Yahoo funds_data.sector_weightings: a dict of sector
                                           # key -> fraction OF THE FUND'S EQUITY SLEEVE, summing to
                                           # ~1.0 regardless of stockPosition; {} for a bond fund,
                                           # or null when unknown) and fund_asset_classes
                                           # (funds_data.asset_classes: stockPosition/bondPosition/
                                           # cashPosition/otherPosition/... fractions, or null)
                                           # drive "sector_exposure"'s fund look-through; proxy
                                           # (a symbol, e.g. "VOO") marks fund_sectors/
                                           # fund_asset_classes as borrowed from that ETF for a
                                           # holding Yahoo has no fund data for at all
      "quote_types": {"AAPL": "EQUITY"}   # optional; "ETF" -> fund, "EQUITY" -> stock,
                                          #   anything else (or a missing symbol) -> other
    }

Output JSON contract (stdout)::

    {
      "totals": {market_value, cash, total_value, cash_pct, cash_like, cash_like_pct,
                 cost_basis, unrealized_pnl, unrealized_pnl_pct, day_change,
                 day_change_pct, day_change_coverage,
                 no_cost_basis_value, no_cost_basis_pct},
                                                       # the two no_cost_basis keys appear
                                                       # only when "history" or
                                                       # "quote_types" is given; cash/cash_pct
                                                       # are settled cash after backing out any
                                                       # money-market core position a broker also
                                                       # reports as cash (see cash_adjusted_for_
                                                       # money_market below); cash_like/_pct add
                                                       # those money-market fund positions back --
                                                       # cash-like holdings, not just settled cash
      "accounts": [{account_id, name, institution_name, account_type,
                    supports_trading, market_value, cash, cash_adjusted_for_money_market,
                    total_value, weight, position_count}],          # input order;
                                                       # cash_adjusted_for_money_market is the
                                                       # amount subtracted from this account's
                                                       # reported cash because it was already
                                                       # counted in a money-market position
                                                       # (0.0 when nothing was subtracted)
      "positions": [{symbol, name, units, price, market_value, weight,
                     cost_basis, unrealized_pnl, unrealized_pnl_pct,
                     day_change, day_change_pct, week_change_pct,
                     month_change_pct, sector, accounts}],
                                                       # market_value desc, symbol asc;
                                                       # week/month_change_pct (return of
                                                       # the close ~5/~21 sessions back to
                                                       # the last close, 4 dp, null when
                                                       # that symbol's history is missing
                                                       # or short) appear only when
                                                       # "history" is given
      "top_holdings": first 10 of "positions",
      "concentration": {hhi, hhi_interpretation, top_5_concentration, largest_position,
                        single_stock: {hhi, hhi_interpretation, weight, count, largest}
                                                       # single_stock only with "quote_types":
                                                       # HHI over stock positions alone (funds and
                                                       # cash weigh zero); a position known to be
                                                       # a fund -- its own fund_sectors, or a bare
                                                       # "proxy" marker, e.g. SPYM, quote type
                                                       # EQUITY but looked through via VOO -- is
                                                       # never counted here either, even though it
                                                       # stays "stock" in largest_position;
                                                       # CONCENTRATED then keys off single_stock,
                                                       # not the position-level hhi
                        position_count},               # same thresholds as
                                                       # allocation.py; CASH is a weight
      "sector_weights": {sector: weight} | null,       # null unless "sectors" given; single
                                                       # stocks that are not looked through,
                                                       # kept for backward compatibility -- any
                                                       # position known to be a fund (its own
                                                       # fund_sectors, or a bare "proxy" marker)
                                                       # is left out entirely rather than falling
                                                       # into "Unknown"; see "sector_exposure" for
                                                       # the look-through view
      "sector_exposure": {                             # null unless "asset_info" is given AND
                                                       # at least one priced position has fund
                                                       # data of its own (fund_sectors) or a
                                                       # quote_type (from asset_info or
                                                       # "quote_types") -- a fully degraded Yahoo
                                                       # lookup, where every position has neither,
                                                       # yields null rather than a page that looks
                                                       # sectorized but is not
        "sectors": {SectorName: {weight, direct, via_funds,
                                  funds: [{symbol, weight}]}},
                                                       # weights are fractions of total_value;
                                                       # "direct" and "via_funds" are rounded
                                                       # first and "weight" is their sum, so the
                                                       # identity weight == direct + via_funds
                                                       # always holds exactly; a stock
                                                       # contributes its whole market value to
                                                       # "direct"; a fund with fund_sectors data
                                                       # contributes market_value * equity_frac *
                                                       # fraction per sector to "via_funds" --
                                                       # Yahoo's fund_sectors fractions are of the
                                                       # fund's EQUITY SLEEVE, summing to ~1.0
                                                       # regardless of stockPosition, so they must
                                                       # be scaled by equity_frac (=
                                                       # fund_asset_classes.stockPosition when
                                                       # that split is present, else sum of the
                                                       # sector fractions themselves) to land as a
                                                       # share of the whole fund; the fractions are
                                                       # also always rescaled to sum to exactly
                                                       # 1.0 first when their own sum is within
                                                       # [0.9, 1.1] (rounding drift, not a real
                                                       # gap -- a sum outside that band is a
                                                       # genuinely partial sector set and is left
                                                       # as reported)
                                                       # (funds: top 3
                                                       # contributing funds by weight, labelled
                                                       # "SYM (via PROXY)" for a proxied holding)
        "equity_share": e,                             # fraction of total_value sectorized;
                                                       # equals the sum of every sector's
                                                       # "weight" within rounding, by
                                                       # construction, for a fund whose sector
                                                       # fractions sum to 1.1 or less (stocks
                                                       # with a known sector, plus each fund's
                                                       # own attributed equity share -- a fund
                                                       # whose fractions are a genuinely partial
                                                       # set, outside the normalization band,
                                                       # contributes only the attributed portion
                                                       # here; a MATERIAL rest -- over 0.5% of
                                                       # that fund's own value -- moves to
                                                       # not_sectorized.funds_without_data below;
                                                       # a negligible rest is simply not counted
                                                       # anywhere, in or out of the band; a fund
                                                       # whose fractions sum to MORE than 1.1 is
                                                       # a provider anomaly -- its attributed
                                                       # share is clamped to 1.0 for the
                                                       # accounting, not rescaled down, so the
                                                       # equity_share identity does not hold for
                                                       # that fund)
        "not_sectorized": {"bonds_and_cash": b, "funds_without_data": n, "unknown_stocks": u},
                                                       # fractions of total_value; bonds_and_cash
                                                       # is settled cash plus every money-market
                                                       # position (asset_bucket "cash", already
                                                       # counted once in totals.cash_like), each
                                                       # fund's own non-equity share
                                                       # (1 - equity_frac), and any other holding
                                                       # with no sector data whose asset_bucket is
                                                       # "bonds"/"cash" or whose
                                                       # fund_asset_classes.bondPosition is >= 0.5;
                                                       # a stock with no sector lands in
                                                       # unknown_stocks; everything else with NO
                                                       # sector data at all (a fund, a
                                                       # commodity/crypto holding, or anything
                                                       # with no Yahoo info at all -- e.g. a
                                                       # quote-type-less 401(k) institutional
                                                       # share class not matched by a
                                                       # look-through proxy) lands in
                                                       # funds_without_data (and "missing_data"),
                                                       # as does a looked-through fund's own
                                                       # MATERIAL unattributed equity slice
                                                       # (above) -- but that slice is reported
                                                       # only in the SECTOR_LOOKTHROUGH_PARTIAL
                                                       # flag's own "partial: ..." clause, never
                                                       # in "missing_data"
        "looked_through": ["VTI", "QBN5 (via VOO)", ...],  # funds with fund_sectors data,
                                                       # a proxied holding labelled "SYM (via
                                                       # PROXY)"
        "missing_data": ["BND", ...],                  # holdings with NO sector data at all,
                                                       # disjoint from "looked_through" -- a
                                                       # partially looked-through fund is never
                                                       # named here, only in the flag
      } | null,
      "allocation": {buckets: {<bucket>: {value, weight, count, symbols}},
                     unclassified: [symbols], note}       # only when "asset_info" is given;
                                                       # buckets: us_equity, intl_equity, bonds,
                                                       # cash, other
      "asset_classes": {stock: {value, weight, count},
                        fund: {...}, other: {...}} | absent,
                                                       # only when "quote_types" is given;
                                                       # priced positions; a position known to be
                                                       # a fund (own fund_sectors, or a bare
                                                       # "proxy" marker) counts as "fund" here
                                                       # even when its own quote type says
                                                       # EQUITY (e.g. SPYM)
      "movers": {"up": [...], "down": [...]},          # up to 3 each, by day_change_pct
      "events": [{symbol, type, date}] | null,         # date asc; null unless given
      "flags": [{code, message}]                       # EMPTY_PORTFOLIO, MISSING_PRICE,
                                                       # PARTIAL_QUOTES, CONCENTRATED,
                                                       # CASH_DRAG, MISSING_SECTOR (a single
                                                       # stock -- quote type EQUITY, or unknown
                                                       # when no quote_types/asset_info was
                                                       # given at all -- with no sector; also
                                                       # names a name-matched position whose
                                                       # proxy fetch returned no data, since it
                                                       # still needs a sector source even though
                                                       # it counts as a fund everywhere else;
                                                       # never a fund with real fund_sectors data
                                                       # or a cash-bucket position),
                                                       # NO_COST_BASIS, SECTOR_LOOKTHROUGH_PARTIAL
                                                       # (funds_without_data over 2% of value)
    }

Money is rounded to 2 dp, ratios to 4 dp. Cost basis is ``units * average
purchase price``; when any lot lacks an average price the position (and the
totals) report ``cost_basis: null`` and fall back to the broker's
``open_pnl`` for unrealized P&L. Day change needs a quote with
``previous_close`` (or ``day_change_pct``); ``day_change_coverage`` is the
share of market value that had one. ``no_cost_basis_value``/``_pct`` are the
market value (and its share) whose lots lack an average purchase price; the
``NO_COST_BASIS`` flag fires when that share is above zero. All extended output is opt-in:
callers that pass neither ``history`` nor ``quote_types`` get exactly the pre-history contract,
plus ``totals.cash_like``/``cash_like_pct`` and each account's ``cash_adjusted_for_money_market``,
which are always present.

A broker that reports its money-market core position (e.g. Fidelity's SPAXX, FDRXX or FCASH) as
both a holding and the account's cash balance would otherwise be double-counted: once in
``market_value`` and again in ``cash``. Per account, when the reported cash is positive, each of
that account's money-market/cash-bucket positions (by ``asset_bucket``) is checked on its own: a
position whose value is within a $1-or-1% tolerance for accrued interest of the reported cash
qualifies -- a broker that reports the core fund as cash reports the same number for both -- and
when more than one position qualifies the closest one is the match. Only that single position's
value is subtracted from the account's cash (floored at 0.0); the position itself stays in the
book, so a second money-market position in the same account is never folded into the match and is
counted once, as a holding. A reported cash of zero or a margin debit never gets an adjustment (a
sub-dollar money-market position can't zero out a debit), and real settled cash held beside a
money-market fund (reported cash well above any single position's value) is left alone, as is a
position worth more than the reported cash. The matched position's value is recorded on the
account row as ``cash_adjusted_for_money_market`` (0.0 when nothing matched -- e.g. E*Trade's
MVRXX, whose value is not close to E*Trade's reported cash). ``totals.cash``/``cash_pct`` are
this settled cash, signed (a margin debit stays negative); ``totals.cash_like``/``cash_like_pct``
add all of the account's money-market fund positions to the settled cash floored at 0.0 (matching
the allocation bucket's own treatment of a cash debit), so they mean cash-like holdings, and the
``CASH_DRAG`` flag is keyed off ``cash_like_pct``.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

_TOP_HOLDINGS = 10
_TOP_MOVERS = 3
_TOP_N = 5
_HHI_DIVERSIFIED_MAX = 0.10
_HHI_MODERATE_MAX = 0.18
_SINGLE_STOCK_MAX = 0.10  # one stock above 10% of total value is a concentration
_CASH_DRAG_PCT = 0.20
_WEEK_BARS = 5
_MONTH_BARS = 21
# funds_without_data share above this flags SECTOR_LOOKTHROUGH_PARTIAL
_SECTOR_LOOKTHROUGH_PARTIAL_PCT = 0.02
_TOP_FUNDS_PER_SECTOR = 3
_FUND_SECTOR_MAP = {
    "technology": "Technology",
    "financial_services": "Financial Services",
    "healthcare": "Healthcare",
    "consumer_cyclical": "Consumer Cyclical",
    "communication_services": "Communication Services",
    "industrials": "Industrials",
    "consumer_defensive": "Consumer Defensive",
    "energy": "Energy",
    "utilities": "Utilities",
    "realestate": "Real Estate",
    "basic_materials": "Basic Materials",
}
# fund_asset_classes.bondPosition at/above this makes a no-data fund a bond fund
_BOND_HEAVY_PCT = 0.5
# a fund's sector fractions are rescaled to sum to exactly 1.0 only within this band around 1.0
# (rounding drift, not a genuinely partial sector set, which is left alone as a real gap)
_FRACTION_SUM_NORMALIZE_MIN = 0.9
_FRACTION_SUM_NORMALIZE_MAX = 1.1
# an out-of-band fund's unattributed equity slice must exceed this share of the FUND'S OWN value
# (not the portfolio's) before it is reported at all -- and then only in the
# SECTOR_LOOKTHROUGH_PARTIAL flag's own "partial: ..." message, never in "missing_data"
_PARTIAL_LOOKTHROUGH_MIN_VALUE_FRAC = 0.005
# quote types MISSING_SECTOR never names -- they're funds, not single stocks
# Institutional index-fund share classes Yahoo has no quote type (or fund data) for at all: match
# by name and borrow a retail ETF's sector look-through instead of dropping the position. Order
# matters -- first match wins.
LOOKTHROUGH_PROXIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"INST(ITUTIONAL)?\b.*500 (IDX|INDEX)", re.I), "VOO"),
    (re.compile(r"500 INDEX TR", re.I), "VOO"),
    # A plain S&P 500 index ETF Yahoo has no fund data for at all (e.g. SPYM raises "No Fund data
    # found"). VOO's own name ("Vanguard S&P 500 ETF") matches this too, but VOO is never proxied
    # to itself: a symbol with its own fund_sectors is never a look-through candidate in the
    # first place (see the has-own-data guard in snapshot.py), and proxy == sym is guarded too.
    (re.compile(r"S&P 500 (ETF|INDEX)|500 INDEX (ETF|TR|TRUST)|PORTFOLIO S&P 500", re.I), "VOO"),
    (re.compile(r"T(OTA)?L INTL STK|TOTAL INTERNATIONAL STOCK", re.I), "VXUS"),
    (re.compile(r"TOT(AL)? BD MKT|TOTAL BOND MARKET", re.I), "BND"),
    (re.compile(r"TOT(AL)? STK MKT|TOTAL STOCK MARKET", re.I), "VTI"),
]


def lookthrough_proxy_for(name: str | None) -> str | None:
    """The look-through proxy ETF for a holding's name (e.g. "VANG INST 500 IDX TR" -> "VOO"), for
    an institutional share class Yahoo has no quote type for; None when nothing matches."""
    if not name:
        return None
    for pattern, proxy in LOOKTHROUGH_PROXIES:
        if pattern.search(name):
            return proxy
    return None


def _money(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _ratio(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _number(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int | float | str):
        raise TypeError(f"{field} must be numeric")
    return float(v)


def _symbol_and_name(position: dict) -> tuple[str, str | None]:
    sym = position.get("symbol")
    name = position.get("name")
    for _ in range(2):  # SnapTrade nests symbol.symbol.symbol
        if isinstance(sym, dict):
            name = sym.get("description") or name
            sym = sym.get("symbol")
    if not isinstance(sym, str) or not sym.strip():
        raise ValueError("each position requires a symbol")
    return sym.strip().upper(), name


def _account_cash(account: dict) -> float:
    if account.get("cash") is not None:
        cash = _number(account["cash"], "cash")
    else:
        cash = 0.0
        for b in account.get("balances") or []:
            if isinstance(b, dict) and b.get("cash") is not None:
                cash += _number(b["cash"], "cash") or 0.0
    # A margin account reports a debit balance as negative cash; keep it (it reduces total value)
    # and let run_summary flag it. Only a non-numeric value is an error.
    return cash


def _validate(params: dict) -> list[dict]:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    accounts = params.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("at least one account is required")
    seen: set[str] = set()
    for a in accounts:
        if not isinstance(a, dict) or not a.get("account_id"):
            raise ValueError("each account requires 'account_id'")
        if a["account_id"] in seen:
            raise ValueError(f"duplicate account_id {a['account_id']!r}")
        seen.add(a["account_id"])
        positions = a.get("positions") or []
        if not isinstance(positions, list):
            raise ValueError("positions must be a list")
        for p in positions:
            if not isinstance(p, dict):
                raise ValueError("each position must be an object")
            _symbol_and_name(p)
            units = _number(p.get("units"), "units")
            if units is not None and units < 0:
                raise ValueError("units must not be negative")
    return accounts


def _quote_for(quotes: dict, symbol: str) -> dict:
    q = quotes.get(symbol) if isinstance(quotes, dict) else None
    return q if isinstance(q, dict) else {}


def _asset_bucket_info(
    symbol: str, asset_info: dict | None, quote_types: dict | None
) -> dict | None:
    """Info dict for ``asset_bucket``: prefers ``asset_info``, falls back to a bare quote type."""
    if asset_info is not None:
        return asset_info.get(symbol)
    if quote_types is not None:
        qt = quote_types.get(symbol)
        return {"quote_type": qt} if qt is not None else None
    return None


_CASH_SYMBOLS = {"FCASH", "SPAXX", "FDRXX", "MVRXX", "CASH", "USD"}
_CASH_RE = re.compile(
    r"money market|liquidity fund|cash reserves|government portfolio|treasury only|cash mgmt", re.I
)
_BOND_RE = re.compile(
    r"\bbond|fixed income|treasur|\bmuni|municipal|\btips\b|inflation.protected|high yield"
    r"|bank loan|\bcredit\b|\bbd (mkt|idx|index)|aggregate|core.plus|short.term (bd|bond)"
    r"|government bond|mortgage.backed",
    re.I,
)
_INTL_RE = re.compile(
    r"foreign|international|\bintl\b|emerging|developed markets|\bex.?us\b|\bworld\b"
    r"|\bglobal\b|europe|pacific|japan|china|india|latin|\beafe\b|all.world|total intl|tl intl",
    re.I,
)
_OTHER_RE = re.compile(
    r"commodit|gold|silver|precious|bitcoin|crypto|currency|real estate|\breit\b|alternative"
    r"|managed futures|volatility",
    re.I,
)
_US_EQUITY_RE = re.compile(
    r"s&p|\b500\b|russell|total stock|total market|nasdaq|\bdow\b|mid.?cap|small.?cap"
    r"|large.?cap|blend|growth|value|\bidx\b|index (tr|fund)|equity|stock",
    re.I,
)


def asset_bucket(symbol: str, info: dict | None) -> str | None:
    """Bucket a holding as bonds, us_equity, intl_equity, cash or other; None when nothing fits.

    Uses, in order, the Yahoo quote type, the fund category, the issuer country and the name (the
    broker's description when Yahoo has nothing, e.g. institutional 401(k) share classes).
    """
    info = info or {}
    sym = str(symbol or "").upper()
    qt = str(info.get("quote_type") or "").upper()
    cat = str(info.get("category") or "")
    name = str(info.get("name") or "")
    text = f"{cat} {name}"
    if qt == "MONEYMARKET" or sym in _CASH_SYMBOLS or _CASH_RE.search(text):
        return "cash"
    if qt == "EQUITY":
        country = str(info.get("country") or "")
        if country and country not in ("United States", "USA", "US"):
            return "intl_equity"
        if _OTHER_RE.search(name) and "REIT" in name.upper():
            return "other"
        return "us_equity"
    if _OTHER_RE.search(text) and not _BOND_RE.search(text):
        return "other"
    if _BOND_RE.search(text):
        return "bonds"
    if _INTL_RE.search(text):
        return "intl_equity"
    if qt in ("ETF", "MUTUALFUND") or _US_EQUITY_RE.search(text):
        return "us_equity"
    return None


def _asset_class(quote_type: object) -> str:
    """Yahoo quote type -> stock | fund | other (ETFs and mutual funds are funds)."""
    qt = str(quote_type or "").upper()
    if qt in ("ETF", "MUTUALFUND"):
        return "fund"
    if qt == "EQUITY":
        return "stock"
    return "other"


def _hhi_label(hhi: float) -> str:
    if hhi < _HHI_DIVERSIFIED_MAX:
        return "diversified"
    if hhi <= _HHI_MODERATE_MAX:
        return "moderate"
    return "concentrated"


def symbols_in(accounts: list[dict]) -> list[str]:
    """Sorted unique symbols across ``accounts`` (input shape as for stdin)."""
    return sorted(
        {
            _symbol_and_name(p)[0]
            for a in accounts
            for p in (a.get("positions") or [])
            if isinstance(p, dict)
        }
    )


def _mover(p: dict) -> dict:
    return {
        "symbol": p["symbol"],
        "day_change_pct": p["day_change_pct"],
        "day_change": p["day_change"],
    }


def _hist_closes(history: dict[str, Any], symbol: str) -> list[float]:
    """Numeric daily closes for ``symbol``, sorted oldest first by ``date``,
    from a ``history`` input (rows may arrive in any order)."""
    rows: Any = history.get(symbol) or []
    valid = [
        h
        for h in rows
        if isinstance(h, dict)
        and isinstance(h.get("close"), (int, float))
        and not isinstance(h.get("close"), bool)
    ]
    valid.sort(key=lambda h: str(h.get("date") or ""))
    return [h["close"] for h in valid]


def _lookback_return(closes: list[float], bars: int) -> float | None:
    """Return of the close ``bars`` sessions back to the last close (4 dp, None when short)."""
    if len(closes) <= bars:
        return None
    base = closes[-1 - bars]
    if base <= 0:
        return None
    return round(closes[-1] / base - 1, 4)


def run_summary(params: dict) -> dict:
    """Build the snapshot described by ``params``; raises ValueError/TypeError on bad input."""
    accounts = _validate(params)
    quotes = params.get("quotes") or {}
    sectors = params.get("sectors")
    events_in = params.get("events")
    history = (
        {str(k).upper(): v for k, v in params["history"].items()}
        if isinstance(params.get("history"), dict)
        else None
    )
    quote_types = (
        {str(k).upper(): v for k, v in params["quote_types"].items()}
        if isinstance(params.get("quote_types"), dict)
        else None
    )
    asset_info = (
        {str(k).upper(): (v or {}) for k, v in params["asset_info"].items()}
        if isinstance(params.get("asset_info"), dict)
        else None
    )
    if asset_info is not None and quote_types is None:
        quote_types = {k: v.get("quote_type") for k, v in asset_info.items()}

    def _is_looked_through_as_fund(symbol: str) -> bool:
        """Whether a position is known to be a fund for classification purposes -- it has
        fund_sectors data of its own (direct or borrowed via a look-through proxy), OR it carries
        a "proxy" marker at all: a name matched against LOOKTHROUGH_PROXIES is already good
        evidence it's an index fund (e.g. SPYM, an S&P 500 ETF Yahoo labels EQUITY), even when
        that proxy's own data fetch came back with nothing usable. Regardless of what quote type
        Yahoo reported, such a position is never a single stock: not in
        concentration.single_stock, sector_weights, asset_classes, or CONCENTRATED's single-stock
        basis. MISSING_SECTOR uses a narrower, separate check (fund_sectors only) -- a
        proxy-marked position with no actual data is still a real sector-data gap worth naming."""
        info = (asset_info.get(symbol) if isinstance(asset_info, dict) else None) or {}
        return info.get("fund_sectors") is not None or info.get("proxy") is not None

    # Extended output (no-cost-basis totals, week/month changes, asset classes) is
    # opt-in: without any new input the result matches the pre-history contract.
    extended = history is not None or quote_types is not None

    # --- aggregate lots by symbol ------------------------------------------------
    book: dict[str, dict] = {}
    account_rows: list[dict] = []
    no_basis_mv = 0.0
    mm_value_total = 0.0
    for a in accounts:
        cash = _account_cash(a)
        acc_mv = 0.0
        mm_value = 0.0
        cash_bucket_values: list[float] = []
        count = 0
        for p in a.get("positions") or []:
            symbol, name = _symbol_and_name(p)
            units = _number(p.get("units"), "units") or 0.0
            q = _quote_for(quotes, symbol)
            price = _number(q.get("price"), "quote price")
            if price is None:
                price = _number(p.get("price"), "price")
            avg = _number(p.get("average_purchase_price"), "average_purchase_price")
            open_pnl = _number(p.get("open_pnl"), "open_pnl")
            row = book.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": name,
                    "units": 0.0,
                    "price": None,
                    "cost_basis": 0.0,
                    "has_cost": True,
                    "pnl": None,
                    "accounts": [],
                },
            )
            row["name"] = row["name"] or name
            row["units"] += units
            row["price"] = row["price"] if row["price"] is not None else price
            row["accounts"].append(a["account_id"])
            count += 1
            if price is not None:
                acc_mv += units * price
                bucket_info = _asset_bucket_info(symbol, asset_info, quote_types)
                if asset_bucket(symbol, bucket_info) == "cash":
                    position_value = units * price
                    mm_value += position_value
                    cash_bucket_values.append(position_value)
            if avg is not None:
                row["cost_basis"] += units * avg
                lot_pnl = units * (price - avg) if price is not None else None
            else:
                row["has_cost"] = False
                if price is not None:
                    no_basis_mv += units * price
                lot_pnl = open_pnl
            if lot_pnl is not None:
                row["pnl"] = (row["pnl"] or 0.0) + lot_pnl
        # A broker that reports a money-market core position (e.g. Fidelity's SPAXX) as both a
        # holding and part of account cash double-counts it; back it out of cash so the position
        # is counted once, leaving the position itself in the book. Match a single position, not
        # the account's summed cash-bucket value: among this account's cash-bucket positions, the
        # one whose own value is within a 1% or $1 tolerance for accrued interest of the reported
        # cash -- the closest one, when more than one qualifies -- is the core position a broker
        # reported on both sides; only its value is subtracted, so a second money-market position
        # in the same account is never folded in and is counted once, as a holding. Reported cash
        # must be positive for any adjustment (a sub-dollar money-market position can never zero
        # out a margin debit); real settled cash sitting beside a money-market fund (reported cash
        # far above any single position's value) is left alone.
        mm_value_total += mm_value
        cash_adjustment = 0.0
        if cash > 0 and cash_bucket_values:
            qualifying = [v for v in cash_bucket_values if abs(cash - v) <= max(1.0, 0.01 * v)]
            if qualifying:
                match_value = min(qualifying, key=lambda v: abs(cash - v))
                cash_adjustment = match_value
                cash = max(0.0, cash - match_value)
        account_rows.append(
            {
                "account_id": a["account_id"],
                "name": a.get("name"),
                "institution_name": a.get("institution_name"),
                "account_type": a.get("account_type"),
                "supports_trading": a.get("supports_trading"),
                "market_value": acc_mv,
                "cash": cash,
                "cash_adjusted_for_money_market": cash_adjustment,
                "total_value": acc_mv + cash,
                "weight": None,
                "position_count": count,
            }
        )

    priced = [r for r in book.values() if r["price"] is not None]
    market_value = sum(r["units"] * r["price"] for r in priced)
    cash_total = sum(r["cash"] for r in account_rows)
    total_value = market_value + cash_total

    # --- per-position figures ------------------------------------------------------
    positions: list[dict] = []
    covered_mv = 0.0
    day_change_total = 0.0
    any_quote = False
    for r in book.values():
        mv = r["units"] * r["price"] if r["price"] is not None else None
        q = _quote_for(quotes, r["symbol"])
        day_change = day_pct = None
        if mv is not None:
            prev = _number(q.get("previous_close"), "previous_close")
            pct_in = _number(q.get("day_change_pct"), "day_change_pct")
            if prev is not None and prev > 0:
                day_pct = r["price"] / prev - 1
                day_change = r["units"] * (r["price"] - prev)
            elif pct_in is not None and pct_in > -1:
                day_pct = pct_in
                day_change = mv - mv / (1 + pct_in)
            if day_change is not None:
                any_quote = True
                covered_mv += mv
                day_change_total += day_change
        cost = r["cost_basis"] if r["has_cost"] else None
        pnl = r["pnl"]
        entry = {
            "symbol": r["symbol"],
            "name": r["name"],
            "units": _ratio(r["units"]),
            "price": _money(r["price"]),
            "market_value": _money(mv),
            "weight": _ratio(mv / total_value) if mv is not None and total_value > 0 else None,
            "cost_basis": _money(cost),
            "unrealized_pnl": _money(pnl),
            "unrealized_pnl_pct": _ratio(pnl / cost) if cost and pnl is not None else None,
            "day_change": _money(day_change),
            "day_change_pct": _ratio(day_pct),
        }
        if history is not None:
            closes = _hist_closes(history, r["symbol"])
            entry["week_change_pct"] = _lookback_return(closes, _WEEK_BARS)
            entry["month_change_pct"] = _lookback_return(closes, _MONTH_BARS)
        entry["sector"] = sectors.get(r["symbol"]) if isinstance(sectors, dict) else None
        entry["accounts"] = r["accounts"]
        positions.append(entry)
    positions.sort(key=lambda p: (-(p["market_value"] or 0.0), p["symbol"]))

    # --- totals ----------------------------------------------------------------------
    cost_total = (
        sum(r["cost_basis"] for r in priced)
        if priced and all(r["has_cost"] for r in priced)
        else None
    )
    pnl_values = [r["pnl"] for r in book.values() if r["pnl"] is not None]
    pnl_total = sum(pnl_values) if pnl_values else None
    denom = covered_mv - day_change_total
    # Matches the allocation bucket's own "if cash_total > 0" rule: a margin debit is not
    # cash-like, so it does not offset money-market fund positions in either place.
    cash_like_total = max(cash_total, 0.0) + mm_value_total
    totals = {
        "market_value": _money(market_value),
        "cash": _money(cash_total),
        "total_value": _money(total_value),
        "cash_pct": _ratio(cash_total / total_value) if total_value > 0 else None,
        "cash_like": _money(cash_like_total),
        "cash_like_pct": _ratio(cash_like_total / total_value) if total_value > 0 else None,
        "cost_basis": _money(cost_total),
        "unrealized_pnl": _money(pnl_total),
        "unrealized_pnl_pct": _ratio(pnl_total / cost_total)
        if cost_total and pnl_total is not None
        else None,
        "day_change": _money(day_change_total) if any_quote else None,
        "day_change_pct": _ratio(day_change_total / denom) if any_quote and denom > 0 else None,
        "day_change_coverage": _ratio(covered_mv / market_value) if market_value > 0 else 0.0,
    }
    if extended:
        totals["no_cost_basis_value"] = _money(no_basis_mv)
        totals["no_cost_basis_pct"] = (
            _ratio(no_basis_mv / market_value) if market_value > 0 else 0.0
        )
    for row in account_rows:
        row["weight"] = _ratio(row["total_value"] / total_value) if total_value > 0 else None
        for key in ("market_value", "cash", "cash_adjusted_for_money_market", "total_value"):
            row[key] = _money(row[key])

    # --- concentration ---------------------------------------------------------------
    if total_value > 0:
        weights = [r["units"] * r["price"] / total_value for r in priced]
        if cash_total > 0:
            weights.append(cash_total / total_value)
        hhi = round(sum(w**2 for w in weights), 4)
        largest = max(priced, key=lambda r: r["units"] * r["price"], default=None)
        concentration = {
            "hhi": hhi,
            "hhi_interpretation": _hhi_label(hhi),
            "top_5_concentration": _ratio(sum(sorted(weights, reverse=True)[:_TOP_N])),
            "position_count": len(book),
            "largest_position": (
                {
                    "symbol": largest["symbol"],
                    "weight": _ratio(largest["units"] * largest["price"] / total_value),
                    "asset_class": _asset_class(quote_types.get(largest["symbol"]))
                    if quote_types is not None
                    else None,
                }
                if largest is not None
                else None
            ),
        }
        # Single-stock view: a diversified fund is not a concentration, so funds and cash
        # contribute nothing to this HHI while staying in the denominator. A position already
        # looked through as a fund (its own fund_sectors, or a proxy) is never a single stock
        # here either, even when Yahoo's own quote type calls it EQUITY.
        if quote_types is not None:
            stock_rows = [
                r
                for r in priced
                if _asset_class(quote_types.get(r["symbol"])) == "stock"
                and not _is_looked_through_as_fund(r["symbol"])
            ]
            stock_weights = [r["units"] * r["price"] / total_value for r in stock_rows]
            stock_hhi = round(sum(w**2 for w in stock_weights), 4)
            top_stock = max(stock_rows, key=lambda r: r["units"] * r["price"], default=None)
            concentration["single_stock"] = {
                "hhi": stock_hhi,
                "hhi_interpretation": _hhi_label(stock_hhi),
                "weight": _ratio(sum(stock_weights)),
                "count": len(stock_rows),
                "largest": (
                    {
                        "symbol": top_stock["symbol"],
                        "weight": _ratio(top_stock["units"] * top_stock["price"] / total_value),
                    }
                    if top_stock is not None
                    else None
                ),
            }
    else:
        concentration = {
            "hhi": None,
            "hhi_interpretation": None,
            "top_5_concentration": None,
            "position_count": len(book),
            "largest_position": None,
        }

    # --- sectors ---------------------------------------------------------------------
    sector_weights = None
    missing_sector: list[str] = []
    # MISSING_SECTOR is a data-quality flag about a single STOCK: Yahoo gives no "sector" to a
    # mutual fund or money-market fund either (only an ETF gets the "ETF" sentinel), so without
    # this check the flag would drown in fund tickers that were never expected to have a sector
    # in the first place -- a fund with no sector data is already reported by
    # SECTOR_LOOKTHROUGH_PARTIAL. Its exclusion is deliberately NARROWER than
    # _is_looked_through_as_fund: only a symbol with actual fund_sectors data of its own is not
    # "missing" -- a proxy-marked position whose proxy fetch came back empty is a real,
    # unresolved sector-data gap and must still be named, even though (below) it's excluded from
    # sector_weights/single_stock/asset_classes on the broader "known to be a fund" basis.
    have_quote_type_data = isinstance(quote_types, dict) or isinstance(asset_info, dict)

    def _eligible_for_missing_sector(symbol: str) -> bool:
        info = (asset_info.get(symbol) if isinstance(asset_info, dict) else None) or {}
        if info.get("fund_sectors") is not None:
            return False  # actually looked through: a real gap, but not a "missing" one
        qt = info.get("quote_type")
        if qt is None and isinstance(quote_types, dict):
            qt = quote_types.get(symbol)
        qt_upper = str(qt or "").upper()
        if qt_upper:
            if qt_upper != "EQUITY":
                return False  # ETF, MUTUALFUND, MONEYMARKET, or anything else non-equity: a fund
        elif have_quote_type_data:
            return False  # quote types were supplied for this run, just not for this symbol
        return asset_bucket(symbol, info) != "cash"

    if isinstance(sectors, dict):
        by_sector: dict[str, float] = {}
        for r in priced:
            symbol = r["symbol"]
            sector = sectors.get(symbol) or "Unknown"
            # sector_weights itself is stock-only: a position already known to be a fund (own
            # fund_sectors, or a proxy marker at all -- e.g. SPYM, quote type EQUITY but looked
            # through via VOO) is left out of the bucket entirely, the same as it's kept out of
            # concentration.single_stock -- independently of whether it also gets named below.
            if not _is_looked_through_as_fund(symbol):
                by_sector[sector] = by_sector.get(sector, 0.0) + r["units"] * r["price"]
            if sector == "Unknown" and _eligible_for_missing_sector(symbol):
                missing_sector.append(symbol)
        sector_weights = {
            s: (_ratio(v / market_value) if market_value > 0 else 0.0)
            for s, v in sorted(by_sector.items())
        }

    # --- sector exposure (looks through ETF/mutual-fund holdings) --------------------
    def _num(v: Any) -> float | None:
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _wt(v: float) -> float:
        return _ratio(v / total_value) if total_value > 0 else 0.0

    def _sector_entry(by_exposure: dict[str, dict[str, Any]], sector: str) -> dict[str, Any]:
        return by_exposure.setdefault(sector, {"direct": 0.0, "via_funds": 0.0, "funds": {}})

    def _is_sectorizable(symbol: str) -> bool:
        """Whether a symbol has enough data to ever land somewhere other than a generic
        no-sector-data bucket: a real quote type (from asset_info or quote_types), or
        fund_sectors data of its own -- a bare "proxy" marker doesn't count on its own, only
        whether that proxy fetch actually produced usable data (fund_sectors, possibly {} for a
        bond fund, but not null)."""
        info = asset_info.get(symbol) or {}
        if info.get("quote_type") is not None:
            return True
        if info.get("fund_sectors") is not None:
            return True
        return quote_types is not None and quote_types.get(symbol) is not None

    sector_exposure = None
    has_sectorizable_position = (
        any(_is_sectorizable(r["symbol"]) for r in priced) if asset_info is not None else False
    )
    if asset_info is not None and has_sectorizable_position:
        by_exposure: dict[str, dict[str, Any]] = {}
        bonds_and_cash_value = cash_like_total  # settled cash + every money-market position (below)
        funds_without_data_value = 0.0
        missing_data_value = 0.0  # the subset of funds_without_data_value with NO sector data
        unknown_stocks_value = 0.0
        equity_value = 0.0
        looked_through: list[str] = []
        missing_data: list[str] = []
        # (symbol, fraction of ITS OWN equity sleeve left unattributed)
        partial_lookthrough: list[tuple[str, float]] = []
        for r in priced:
            symbol = r["symbol"]
            mv = r["units"] * r["price"]
            info = asset_info.get(symbol) or {}
            bucket = asset_bucket(symbol, info)
            # A money-market/cash-bucket position (any quote type) is already inside
            # cash_like_total above -- counting it again here would double it.
            if bucket == "cash":
                continue
            qt = info.get("quote_type")
            if qt is None and quote_types is not None:
                qt = quote_types.get(symbol)
            cls = _asset_class(qt)
            proxy = info.get("proxy")
            # A proxied position (fund_sectors borrowed from a look-through proxy ETF) is looked
            # through as a fund below, even when Yahoo called it a plain EQUITY (e.g. SPYM, an
            # S&P 500 index ETF Yahoo could give neither a sector nor its own fund data for) --
            # it must not be classified as a sector-less stock here.
            if cls == "stock" and not proxy:
                sector = None
                if isinstance(sectors, dict) and symbol in sectors:
                    sector = sectors.get(symbol)
                if sector is None:
                    sector = info.get("sector")
                if sector and sector != "Unknown":
                    entry = _sector_entry(by_exposure, sector)
                    entry["direct"] += mv
                    equity_value += mv
                else:
                    unknown_stocks_value += mv
                continue
            # A fund with fund_sectors data, or a proxied holding -- both looked-through the same
            # way, regardless of what quote type Yahoo reported for the position itself.
            fund_sectors = info.get("fund_sectors") if (cls == "fund" or proxy) else None
            if isinstance(fund_sectors, dict) and fund_sectors:
                label = f"{symbol} (via {proxy})" if proxy else symbol
                looked_through.append(label)
                pairs: list[tuple[str, float]] = []
                for key, raw_frac in fund_sectors.items():
                    sector = _FUND_SECTOR_MAP.get(key)
                    frac = _num(raw_frac)
                    if sector is not None and frac is not None:
                        pairs.append((sector, frac))
                fraction_sum = sum(frac for _, frac in pairs)
                # Yahoo's sector fractions should sum to ~1.0 (of the fund's equity sleeve) but
                # occasionally drift a little (e.g. VWO summed to 1.0001); rescale that small
                # drift away so every sector's share sums to exactly 1.0. Only within a narrow
                # band around 1.0, though: a fund reporting a genuinely partial set of sectors
                # (e.g. 2 of ~11, summing to 0.40) is real missing data, not rounding noise, and
                # must stay a visible gap rather than being stretched up to look complete.
                in_band = _FRACTION_SUM_NORMALIZE_MIN <= fraction_sum <= _FRACTION_SUM_NORMALIZE_MAX
                if in_band:
                    # Within the band, ANY drift from 1.0 is rounding noise, not missing data:
                    # always rescale so the sectors sum to exactly the attributed 1.0 (dividing
                    # by a fraction_sum already close to 1.0 is a no-op in practice), keeping
                    # equity_share == sum(sector weights) exact even for a drift as small as
                    # 0.0001 -- not just the larger drifts that bothered rescaling before.
                    pairs = [(s, frac / fraction_sum) for s, frac in pairs]
                    attributed_frac = 1.0
                else:
                    attributed_frac = max(0.0, min(fraction_sum, 1.0))
                classes = info.get("fund_asset_classes")
                classes = classes if isinstance(classes, dict) and classes else None
                # Yahoo's sector fractions are of the fund's EQUITY SLEEVE (they sum to ~1.0
                # regardless of stockPosition), so each must be scaled by the fund's own equity
                # share to land as a share of the whole fund; the rest is the fund's own
                # non-equity share (bonds/cash/other), landing in bonds_and_cash below.
                equity_frac = _num(classes.get("stockPosition")) if classes else None
                if equity_frac is None:
                    equity_frac = fraction_sum  # the fund's own raw (un-normalized) equity estimate
                remainder_frac = max(0.0, 1.0 - equity_frac)
                for sector, frac in pairs:
                    amount = mv * equity_frac * frac
                    entry = _sector_entry(by_exposure, sector)
                    entry["via_funds"] += amount
                    entry["funds"][label] = entry["funds"].get(label, 0.0) + amount
                # A genuinely partial sector set (out of the normalization band, attributed_frac
                # < 1) leaves a real slice of the fund's own equity sleeve with nowhere named to
                # go; when that slice is more than a rounding artifact (over
                # _PARTIAL_LOOKTHROUGH_MIN_VALUE_FRAC of the fund's OWN value), route it into
                # funds_without_data (not equity_share, which must equal the sum of the sector
                # weights above by construction) and report it through the
                # SECTOR_LOOKTHROUGH_PARTIAL flag's own "partial: ..." clause -- NOT missing_data,
                # since the fund WAS looked through, just not completely; missing_data is
                # reserved for holdings with no sector data at all. A negligible or in-band
                # (already 1.0) leftover is simply folded into equity_value: it is not a real gap.
                unattributed_frac = 0.0 if in_band else max(0.0, 1.0 - attributed_frac)
                unattributed_value = mv * equity_frac * unattributed_frac
                # equity_value always gets exactly the attributed share -- matching the sectors
                # above dollar for dollar -- so equity_share == sum(sector weights) always holds,
                # whether or not the leftover (if any) turns out big enough to report.
                equity_value += mv * equity_frac * attributed_frac
                if not in_band and unattributed_value > _PARTIAL_LOOKTHROUGH_MIN_VALUE_FRAC * mv:
                    funds_without_data_value += unattributed_value
                    partial_lookthrough.append((symbol, unattributed_frac))
                bonds_and_cash_value += mv * remainder_frac
                continue
            # Not a sectorized stock and not a fund with sector data: a fund without data, a
            # commodity/crypto holding, or anything Yahoo has no info for at all (quote_type
            # None -- e.g. a 401(k) plan's institutional share class not matched by a
            # look-through proxy) is attributed by its asset bucket instead, so every position
            # lands somewhere. A fund whose own asset split says it's mostly bonds counts as a
            # bond fund even when its bucket (by category/name) misses that.
            classes = info.get("fund_asset_classes")
            bond_position = _num(classes.get("bondPosition")) if isinstance(classes, dict) else None
            is_bond_heavy = bond_position is not None and bond_position >= _BOND_HEAVY_PCT
            if bucket in ("bonds", "cash") or is_bond_heavy:
                bonds_and_cash_value += mv
            else:  # us_equity, intl_equity, other, or unbucketed (None)
                funds_without_data_value += mv
                missing_data_value += mv
                missing_data.append(symbol)
        sectors_out: dict[str, dict[str, Any]] = {}
        for name, v in sorted(by_exposure.items()):
            direct = _wt(v["direct"])
            via_funds = _wt(v["via_funds"])
            sectors_out[name] = {
                "weight": round(direct + via_funds, 4),
                "direct": direct,
                "via_funds": via_funds,
                "funds": [
                    {"symbol": sym, "weight": _wt(amt)}
                    for sym, amt in sorted(v["funds"].items(), key=lambda kv: (-kv[1], kv[0]))[
                        :_TOP_FUNDS_PER_SECTOR
                    ]
                ],
            }
        sector_exposure = {
            "sectors": sectors_out,
            "equity_share": _wt(equity_value),
            "not_sectorized": {
                "bonds_and_cash": _wt(bonds_and_cash_value),
                "funds_without_data": _wt(funds_without_data_value),
                "unknown_stocks": _wt(unknown_stocks_value),
            },
            "looked_through": sorted(looked_through),
            "missing_data": sorted(missing_data),
        }

    # --- asset classes ----------------------------------------------------------------
    asset_classes = None
    if quote_types is not None:
        values = {"stock": 0.0, "fund": 0.0, "other": 0.0}
        counts = {"stock": 0, "fund": 0, "other": 0}
        for r in priced:
            symbol = r["symbol"]
            cls = _asset_class(quote_types.get(symbol))
            if cls == "stock" and _is_looked_through_as_fund(symbol):
                cls = "fund"  # e.g. SPYM: Yahoo calls it EQUITY, but it's looked through via VOO
            values[cls] += r["units"] * r["price"]
            counts[cls] += 1
        asset_classes = {
            cls: {
                "value": _money(values[cls]),
                "weight": _ratio(values[cls] / market_value) if market_value > 0 else 0.0,
                "count": counts[cls],
            }
            for cls in ("stock", "fund", "other")
        }

    # --- allocation buckets (bonds / US equity / international equity / cash / other) -----
    allocation = None
    if asset_info is not None:
        order = ("us_equity", "intl_equity", "bonds", "cash", "other")
        bvalues = {b: 0.0 for b in order}
        bsyms: dict[str, list[str]] = {b: [] for b in order}
        unclassified: list[str] = []
        for r in priced:
            b = asset_bucket(r["symbol"], asset_info.get(r["symbol"]))
            if b is None:
                unclassified.append(r["symbol"])
                b = "other"
            bvalues[b] += r["units"] * r["price"]
            bsyms[b].append(r["symbol"])
        if cash_total > 0:
            bvalues["cash"] += cash_total
        allocation = {
            "buckets": {
                b: {
                    "value": _money(bvalues[b]),
                    "weight": _ratio(bvalues[b] / total_value) if total_value > 0 else 0.0,
                    "count": len(bsyms[b]),
                    "symbols": sorted(bsyms[b]),
                }
                for b in order
            },
            "unclassified": sorted(unclassified),
            "note": "funds are bucketed by category and name, not looked through; "
            "account cash counts as cash",
        }

    # --- movers ----------------------------------------------------------------------
    quoted = [p for p in positions if p["day_change_pct"] is not None]
    ups = sorted(
        (p for p in quoted if p["day_change_pct"] > 0),
        key=lambda p: (-p["day_change_pct"], p["symbol"]),
    )
    downs = sorted(
        (p for p in quoted if p["day_change_pct"] < 0),
        key=lambda p: (p["day_change_pct"], p["symbol"]),
    )
    movers = {
        "up": [_mover(p) for p in ups[:_TOP_MOVERS]],
        "down": [_mover(p) for p in downs[:_TOP_MOVERS]],
    }

    # --- events ----------------------------------------------------------------------
    events = None
    if isinstance(events_in, dict):
        events = []
        for symbol, ev in events_in.items():
            if not isinstance(ev, dict):
                continue
            for key, kind in (("next_earnings", "earnings"), ("next_ex_dividend", "ex_dividend")):
                if ev.get(key):
                    events.append(
                        {"symbol": str(symbol).upper(), "type": kind, "date": str(ev[key])}
                    )
        events.sort(key=lambda e: (e["date"], e["symbol"], e["type"]))

    # --- flags -----------------------------------------------------------------------
    flags: list[dict] = []
    if total_value == 0:
        flags.append(
            {
                "code": "EMPTY_PORTFOLIO",
                "message": "no positions and no cash in the selected accounts",
            }
        )
    unpriced = sorted(r["symbol"] for r in book.values() if r["price"] is None)
    if unpriced:
        flags.append({"code": "MISSING_PRICE", "message": f"no price for: {', '.join(unpriced)}"})
    if quotes and market_value > 0 and covered_mv < market_value:
        uncovered = sorted(
            p["symbol"]
            for p in positions
            if p["market_value"] is not None and p["day_change_pct"] is None
        )
        coverage = round(covered_mv / market_value * 100, 2)
        missing = ", ".join(uncovered)
        flags.append(
            {
                "code": "PARTIAL_QUOTES",
                "message": f"day change covers {coverage}% of market value (missing: {missing})",
            }
        )
    single = concentration.get("single_stock")
    if single is not None:
        # With asset classes known, only single-stock concentration is flagged: a large
        # position in a diversified fund is an allocation choice, not a concentration.
        largest = single.get("largest") or {}
        if single["hhi"] > _HHI_MODERATE_MAX or (largest.get("weight") or 0) > _SINGLE_STOCK_MAX:
            flags.append(
                {
                    "code": "CONCENTRATED",
                    "message": (
                        f"single-stock HHI {single['hhi']} ({single['hhi_interpretation']}); "
                        f"largest single stock {largest.get('symbol')} is "
                        f"{round(100 * (largest.get('weight') or 0), 1)}% of total value"
                    ),
                }
            )
    elif concentration["hhi"] is not None and concentration["hhi"] > _HHI_MODERATE_MAX:
        hhi = concentration["hhi"]
        flags.append(
            {
                "code": "CONCENTRATED",
                "message": f"HHI {hhi} is above {_HHI_MODERATE_MAX}: the book is concentrated "
                "(asset classes unknown, so funds count as positions)",
            }
        )
    debit = [a for a in account_rows if (a.get("cash") or 0) < 0]
    for a in debit:
        flags.append(
            {
                "code": "MARGIN_DEBIT",
                "message": f"{a.get('name') or a.get('account_id')} has a negative cash balance "
                f"({round(float(a['cash']), 2)}): a margin debit that reduces total value",
            }
        )
    if totals["cash_like_pct"] is not None and totals["cash_like_pct"] > _CASH_DRAG_PCT:
        cash_pct = round(totals["cash_like_pct"] * 100, 1)
        limit = int(_CASH_DRAG_PCT * 100)
        flags.append(
            {
                "code": "CASH_DRAG",
                "message": f"cash and money-market funds are {cash_pct}% of total value "
                f"(above {limit}%)",
            }
        )
    if missing_sector:
        flags.append(
            {
                "code": "MISSING_SECTOR",
                "message": f"no sector for: {', '.join(sorted(missing_sector))}",
            }
        )
    if sector_exposure is not None:
        funds_without_data_pct = sector_exposure["not_sectorized"]["funds_without_data"]
        if funds_without_data_pct and funds_without_data_pct > _SECTOR_LOOKTHROUGH_PARTIAL_PCT:
            # Two independent, optional clauses: holdings with NO sector data at all (a
            # portfolio-wide % of value, same as always), and funds that WERE looked through but
            # only partially (each fund's own % of ITS OWN equity sleeve left unattributed) --
            # the two never share a symbol (missing_data and partial_lookthrough are disjoint).
            clauses = []
            if sector_exposure["missing_data"]:
                missing_pct = (
                    round(missing_data_value / total_value * 100, 1) if total_value > 0 else 0.0
                )
                clauses.append(
                    "no sector data (not looked through): "
                    f"{', '.join(sector_exposure['missing_data'])} ({missing_pct}% of value)"
                )
            if partial_lookthrough:
                partial_desc = ", ".join(
                    f"{sym} ({round(frac * 100, 1)}% of its equity unattributed)"
                    for sym, frac in sorted(partial_lookthrough)
                )
                clauses.append(f"partial: {partial_desc}")
            flags.append({"code": "SECTOR_LOOKTHROUGH_PARTIAL", "message": "; ".join(clauses)})
    no_basis_pct = totals.get("no_cost_basis_pct") or 0.0
    if extended and no_basis_pct > 0:
        pct = round(no_basis_pct * 100, 1)
        flags.append(
            {
                "code": "NO_COST_BASIS",
                "message": f"{pct}% of market value has no cost basis; unrealized P&L excludes it",
            }
        )

    result = {
        "totals": totals,
        "accounts": account_rows,
        "positions": positions,
        "top_holdings": positions[:_TOP_HOLDINGS],
        "concentration": concentration,
        "sector_weights": sector_weights,
        "sector_exposure": sector_exposure,
    }
    if asset_classes is not None:
        result["asset_classes"] = asset_classes
    if allocation is not None:
        result["allocation"] = allocation
        if allocation["unclassified"]:
            flags.append(
                {
                    "code": "ASSET_BUCKET_UNKNOWN",
                    "message": "counted as other (no category, country or recognizable name): "
                    + ", ".join(allocation["unclassified"]),
                }
            )
    result.update({"movers": movers, "events": events, "flags": flags})
    return result


def main() -> None:
    """Read JSON params from stdin, write the snapshot (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_summary(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
