"""Rebuild daily portfolio value from the transaction ledger and chain a
time-weighted return, alongside index benchmarks.

This script reads a JSON object from stdin and writes a JSON object to
stdout. It is invoked as:

    python history.py < input.json

Exit code is 0 on success or 2 on invalid input (stdout is
``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "as_of": "YYYY-MM-DD",                        # required
      "accounts": [{"account_id": "...", "name": "...", "cash": 0.0,
                    "account_type": "margin",          # optional; only "margin" matters
                    "positions": [{"symbol": "AAPL", "units": 10.0,
                                   "price": 1.0,       # broker's price; optional, but
                                   "name": "..."}]}],  # needed to proxy-price a fund;
                                                       # name tells cash-like funds
      "transactions": [ ... ],     # ledger entries, normalize.py's contract
                                   # (amount = signed cash flow to the account,
                                   # units always positive); matched to an
                                   # account by account_id
      "prices": {"AAPL": [{"date": "...", "close": 1.0, "adj_close": 1.0}]},
      "splits": {"AAPL": [{"date": "...", "ratio": 2.0}]},  # optional, Yahoo's
      "aliases": {"<twin account_id>": "<live account_id>"},  # optional
      "proxies": {"ONN5": "VOO"},   # optional: unlisted fund -> public proxy ETF,
                                    # whose price rows must be in ``prices``
      "benchmarks": ["SPY", "QQQ", "DIA"]           # optional
    }

Account identity. Ledger rows are mapped through ``aliases`` (E*Trade-direct id
and its SnapTrade twin onto the live id). Rows duplicated across source ids
(same date, type, symbol, units, amount) are counted once: per live account the
source id with the most copies of each such row is kept, so repeats within one
id stay. Rows matching no account are ignored (UNASSIGNED_ROWS flag).

Cash-like and unlisted holdings. A symbol ``proxies.is_cash_like`` accepts
(money markets) is valued at $1.00 a unit and its BUY/SELL rows are not
rolled (sweeps are usually missing from the ledger); transfers are rolled and count
as external flows at $1.00 a unit. A held fund with a proxy,
a broker price and no price rows of its own gets a synthetic history: today's
broker price scaled back by the proxy's daily ``adj_close`` ratios. Accounts
holding one are ``estimated`` with a PROXY_PRICED flag. A real close is carried
forward over at most 5 trading days.

Output JSON contract (stdout)::

    {
      "as_of": "YYYY-MM-DD",
      "series": [
        {"key": "combined", "label": "All accounts", "start": "...",
         "estimated": false, "accounts": ["<account_id>"],   # accounts summed
         "points": [["YYYY-MM-DD", 1.0, 12345.67]],    # date, cumulative index, value
         "headline": {"range": "1Y", "start": "YYYY-MM-DD",  # "All" when shorter than a year
                      "portfolio_return": 0.082, "spy_return": 0.11,  # null when SPY is unavailable
                      "estimated": false}},
        {"key": "<account_id>", "label": "<account name>", "start": "...",
         "estimated": false, "points": [...], "headline": {...}}
      ],
      "benchmarks": [{"symbol": "SPY", "label": "S&P 500",
                      "points": [["YYYY-MM-DD", 1.0]]}],
      "excluded": [{"account_id": "...", "reason": "..."}],
      "flags": [{"code": "...", "message": "..."}]
    }

Method: starting from today's positions and cash, the ledger is walked from
newest to oldest and each transaction undone to give end-of-day holdings for
every earlier trading day:

    BUY                      units -= u; cash -= amount
    SELL                     units += u; cash -= amount
    DIVIDEND/INTEREST/FEE    cash -= amount
    DEPOSIT/WITHDRAWAL       cash -= amount; external flow of ``amount``
    TRANSFER_IN/OUT, symbol  units -/+= u; external flow of close x u
    TRANSFER_IN/OUT, cash    like DEPOSIT/WITHDRAWAL
    OTHER                    cash -= amount when present (flag OTHER_TYPES)

V(d) = cash(d) + sum units x close(d), the last close carried forward over
days without one. With F(d) the external flow (deposits positive, at end of
day), r(d) = (V(d) - F(d)) / V(d-1) - 1 and the index is the running product
of (1 + r). The combined line sums V and F across included accounts and
chains the sum, from the latest account start. Benchmarks are
adj_close(d) / adj_close(first day). The trading-day calendar is the union of
dates across all price rows, from the earliest ledger date to ``as_of``. A
transaction on a non-trading day lands on the next trading day. Each account's
own days start on the trading day its oldest ledger row lands on: before that
nothing is known about it.

Headline. Per series, ``headline`` is its return over the year to ``as_of``
(``range`` "1Y"), or over the whole series when it starts after ``as_of`` minus
one year ("All"; Feb 29 minus a year is Feb 28). The base is the last point on
or before that range start, or the series' first point for All; ``start`` is
the base day, ``portfolio_return`` is index(last) / index(base) - 1, and
``spy_return`` is the same on SPY's points from its last point on or before the
base day (null when SPY is unavailable or has no such point). The page rebases
every range the same way.

Splits. Units are kept in today's split terms, matching Yahoo's split-adjusted
``close``. Split events per account come from the ledger's SPLIT rows
(``split_ratio``, optional share delta in ``units``) merged with Yahoo's
``splits`` (a row within 7 days of a Yahoo split is that split; a null row
ratio falls back to Yahoo's). For each split, newest first, both readings of
the earlier trades are tried: as traded (units x later ratios) and already
adjusted (units as recorded). A reading fits when the symbol's units never go
negative beyond the tolerance below and, when the SPLIT row carries units, the
share change across the split (as traded: post x (1 - 1/ratio); adjusted: 0)
equals the row's units or units x ratio (reconcile.py's reading) within 1e-6
relative. If both fit, the one leaving zero units before the ledger's first
trade wins. Anything else, or a split with no ratio, is ambiguous: a break on
the split date.

Reconciliation ("never draw a guess"). Walking back from today, the first of
these ends the account's series, which then starts the day after the break
date, with a HISTORY_BREAK flag naming account, date, symbol and reason:
- negative units: units < 0 with |units| > 1e-6 and > 0.1% of the most held
  so far; the break date is the day whose transactions were undone
- no price: a symbol held with no close, unless a last trade price (ledger
  ``price``, in today's split terms) or the broker's ``price`` values it, with
  every other such holding that day, under 1% of the account, in which case it
  is carried with UNPRICED_HOLDING. That price is per quoted unit; it is scaled
  by the symbol's multiplier, the largest |amount| / (units x price) across its
  BUY/SELL rows (100 for an option quoted per share), or 1 without such a row.
  An OCC option symbol with no such row is a break ("no contract multiplier")
- trade without symbol (or units): a BUY/SELL that can't be undone (cash-like
  sweeps excepted); the break date is its day
- negative cash: cash < -5% of account value on an account whose
  ``account_type`` is not "margin"; break date as for negative units
- split: an ambiguous split, as above
Today's broker-reported units and cash are not tested. An account a break
leaves with no days is excluded ("history break"). An account whose series
spans under 30 calendar days keeps its own series but is left out of the
combined line (SHORT_HISTORY flag), unless every account is that short, in
which case all are combined and nothing is flagged.
"""

from __future__ import annotations

import json
import sys
from bisect import bisect_left, bisect_right
import re
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any, Literal

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import proxies as proxy_lib  # noqa: E402

DayHolding = dict[str, Any]  # {"units": {sym: u}, "cash": float, "flow": float, "transfers": {sym: u}}

BENCHMARK_LABELS = {"SPY": "S&P 500", "QQQ": "Nasdaq", "DIA": "Dow"}
_EPS = 1e-9
NEG_UNITS_ABS = 1e-6  # negative units below this are rounding
NEG_UNITS_REL = 0.001  # ... or below 0.1% of the most held
UNPRICED_LIMIT = 0.01  # unpriced holdings under 1% of the account are carried
CASH_LIMIT = 0.05  # cash below -5% of value breaks a non-margin account
CARRY_DAYS = 5  # a close is carried forward over at most this many trading days
SHORT_HISTORY_DAYS = 30
SPLIT_MATCH_DAYS = 7  # a ledger SPLIT row this close to a Yahoo split is that split
OPTION_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,5}\s*\d{6}[CP]\d{8}$")  # OCC option symbol
_UNDO_SIGN = {"BUY": -1.0, "SELL": 1.0, "TRANSFER_IN": -1.0, "TRANSFER_OUT": 1.0}


def _num(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be numeric")
    return float(value)


def _iso(value: object, what: str) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"{what} must be YYYY-MM-DD, got {value!r}") from exc


def _opt(value: object) -> float | None:
    """``value`` as a float when it is a real number, else None."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _negative(units: float, max_held: float, floor: float = 0.0) -> bool:
    """True when ``units`` is below ``floor`` (min(0, today's units)) beyond rounding."""
    short = floor - units
    return short > NEG_UNITS_ABS and short > NEG_UNITS_REL * max(max_held, 0.0)


def _split_factor(symbol: str, txn_date: str, splits: dict[str, Any] | None) -> float:
    """Product of the ratios of ``symbol``'s splits dated after ``txn_date``: the
    multiplier taking an as-traded unit count into today's split terms. Splits
    whose ``convention`` is set to anything but "as_traded" count as 1."""
    factor = 1.0
    for event in (splits or {}).get(symbol) or []:
        ratio = _opt(event.get("ratio"))
        if (str(event["date"])[:10] > str(txn_date)[:10] and ratio and ratio > 0
                and event.get("convention", "as_traded") == "as_traded"):
            factor *= ratio
    return factor


def _detect_split_convention(
    symbol: str, txns: list[dict[str, Any]], splits: dict[str, Any], today_units: float
) -> Literal["as_traded", "adjusted", "ambiguous"]:
    """How the ledger recorded trades before ``symbol``'s newest split that has no
    ``convention`` yet (the target). Newer splits keep their set convention; the
    target and older undecided splits are tried together under each reading."""
    events = sorted((dict(e) for e in splits.get(symbol) or []), key=lambda e: str(e["date"])[:10])
    pending = [e for e in events if not e.get("convention")]
    if not pending:
        raise ValueError(f"{symbol}: no undecided split")
    target = pending[-1]
    split_day = str(target["date"])[:10]
    rows = sorted(
        (t for t in txns if t.get("symbol") == symbol and t.get("type") in _UNDO_SIGN and _opt(t.get("units"))),
        key=lambda t: str(t["date"])[:10],
    )
    if not any(str(t["date"])[:10] < split_day for t in rows):
        return "adjusted"  # nothing recorded before the split: either reading is the same
    ratio = _opt(target.get("ratio"))
    if not ratio or ratio <= 0:
        return "ambiguous"
    row_units = _opt(target.get("units"))
    outcomes: dict[str, tuple[bool, float, float]] = {}
    for reading in ("as_traded", "adjusted"):
        trial = {symbol: [{**e, "convention": e.get("convention") or reading} for e in events]}
        units = float(today_units)
        peak = max(units, 0.0)
        post: float | None = None
        fits = True
        for txn in reversed(rows):
            when = str(txn["date"])[:10]
            if post is None and when < split_day:
                post = units
            units += _UNDO_SIGN[txn["type"]] * float(txn["units"]) * _split_factor(symbol, when, trial)
            peak = max(peak, units)
            if _negative(units, peak, min(0.0, float(today_units))):
                fits = False
                break
        if fits and row_units:
            raw_post = (units if post is None else post) / _split_factor(symbol, split_day, trial)
            expected = abs(raw_post * (1.0 - 1.0 / ratio)) if reading == "as_traded" else 0.0
            fits = any(abs(expected - c) <= 1e-6 * max(1.0, c) for c in (abs(row_units), abs(row_units * ratio)))
        outcomes[reading] = (fits, units, peak)
    fitting = [r for r, (ok, _, _) in outcomes.items() if ok]
    if len(fitting) == 2:
        fitting = [r for r in fitting if abs(outcomes[r][1]) <= max(NEG_UNITS_ABS, NEG_UNITS_REL * outcomes[r][2])]
    return fitting[0] if len(fitting) == 1 else "ambiguous"  # type: ignore[return-value]


def _split_events(txns: list[dict[str, Any]], yahoo: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Split events per symbol: Yahoo's splits merged with this account's SPLIT rows."""
    events: dict[str, list[dict[str, Any]]] = {}
    for symbol, rows in yahoo.items():
        if not isinstance(rows, list):
            raise ValueError(f"splits[{symbol}] must be a list")
        for row in rows:
            ratio = _opt(row.get("ratio")) if isinstance(row, dict) else None
            if not ratio or ratio <= 0:
                continue  # a bad Yahoo row is dropped; the ledger's SPLIT row or a break decides
            try:
                when = _iso(row.get("date"), f"splits[{symbol}] date")
            except ValueError:
                continue
            events.setdefault(symbol, []).append({"date": when, "ratio": ratio, "units": None, "row": False})
    for txn in txns:
        symbol = txn.get("symbol")
        if txn.get("type") != "SPLIT" or not symbol:
            continue
        ratio = _opt(txn.get("split_ratio"))
        ratio = ratio if ratio and ratio > 0 else None
        units = _opt(txn.get("units"))
        when = date.fromisoformat(txn["date"])
        near = [e for e in events.get(symbol, [])
                if not e["row"] and abs((date.fromisoformat(e["date"]) - when).days) <= SPLIT_MATCH_DAYS]
        if near:
            match = min(near, key=lambda e: abs((date.fromisoformat(e["date"]) - when).days))
            match.update(row=True, units=units, ratio=ratio or match["ratio"])
        else:
            events.setdefault(symbol, []).append({"date": txn["date"], "ratio": ratio, "units": units, "row": True})
    for evs in events.values():
        evs.sort(key=lambda e: e["date"])
    return events


def _resolve_splits(
    txns: list[dict[str, Any]], yahoo: dict[str, Any], today_units: dict[str, float]
) -> tuple[dict[str, list[dict[str, Any]]], list[tuple[str, str]]]:
    """Split events with a ``convention`` each, plus (date, symbol) per ambiguous split."""
    events = _split_events(txns, yahoo)
    breaks: list[tuple[str, str]] = []
    for symbol, evs in events.items():
        for k in range(len(evs) - 1, -1, -1):
            convention = _detect_split_convention(symbol, txns, {symbol: evs}, today_units.get(symbol, 0.0))
            evs[k]["convention"] = convention
            if convention == "ambiguous":
                breaks.append((evs[k]["date"], symbol))
                for older in evs[:k]:  # days before this break are never drawn
                    older["convention"] = "adjusted"
                break
    return events, breaks


def _undo(txn: dict[str, Any], state: DayHolding, factor: float = 1.0) -> bool:
    """Undo one transaction in ``state`` (going back in time); True for an OTHER row.
    ``factor`` takes the row's units into today's split terms."""
    kind = txn.get("type")
    symbol = txn.get("symbol")
    units = _opt(txn.get("units"))
    units = None if units is None else units * factor
    amount = _opt(txn.get("amount"))
    held = state["units"]
    if kind in ("BUY", "SELL"):
        if symbol and units is not None:  # a trade without either is a break (``_bad_trade``)
            held[symbol] = held.get(symbol, 0.0) + (-units if kind == "BUY" else units)
        state["cash"] -= amount or 0.0
    elif kind in ("TRANSFER_IN", "TRANSFER_OUT") and symbol and units is not None:
        signed = units if kind == "TRANSFER_IN" else -units
        held[symbol] = held.get(symbol, 0.0) - signed
        state["transfers"][symbol] = state["transfers"].get(symbol, 0.0) + signed
    elif kind in ("DEPOSIT", "WITHDRAWAL", "TRANSFER_IN", "TRANSFER_OUT"):
        state["cash"] -= amount or 0.0
        state["flow"] += amount or 0.0
    elif kind in ("DIVIDEND", "INTEREST", "FEE"):
        state["cash"] -= amount or 0.0
    elif kind != "SPLIT":  # OTHER or unrecognised: undo the cash when present
        state["cash"] -= amount or 0.0
        return True
    return False


def _rollback(
    account: dict[str, Any],
    txns: list[dict[str, Any]],
    splits: dict[str, Any] | None,
    days: list[str],
    others: list[int] | None = None,
    skip: frozenset[str] = frozenset(),
) -> dict[str, DayHolding]:
    """End-of-day holdings for each day in ``days`` (ascending ISO dates, the last
    being ``as_of``), by undoing ``txns`` backward from the account's current state.
    BUY/SELL rows in a ``skip`` symbol (cash-like sweeps) are not undone; transfers are.

    ``splits`` holds split events with conventions (see ``_split_factor``). ``others``,
    when given, has its first element incremented per OTHER row undone.
    """
    state: DayHolding = {
        "units": {p["symbol"]: float(p.get("units") or 0.0) for p in account.get("positions") or [] if p.get("symbol")},
        "cash": float(account.get("cash") or 0.0),
        "flow": 0.0,
        "transfers": {},
    }
    buckets: dict[int, list[dict[str, Any]]] = {}
    for txn in txns:
        when = str(txn["date"])[:10]
        if when <= days[-1]:
            buckets.setdefault(min(bisect_left(days, when), len(days) - 1), []).append(txn)
    out: dict[str, DayHolding] = {}
    for i in range(len(days) - 1, -1, -1):
        # the day's end-of-day state, then undo its transactions for the day before
        out[days[i]] = {"units": dict(state["units"]), "cash": state["cash"], "flow": 0.0, "transfers": {}}
        for txn in reversed(buckets.get(i, [])):
            if txn.get("symbol") in skip and txn.get("type") in ("BUY", "SELL"):
                continue
            factor = _split_factor(txn["symbol"], txn["date"], splits) if txn.get("symbol") else 1.0
            if _undo(txn, state, factor) and others is not None:
                others[0] += 1
        out[days[i]]["flow"] = state["flow"]
        out[days[i]]["transfers"] = state["transfers"]
        state["flow"] = 0.0
        state["transfers"] = {}
    return out


def _value(day_holding: DayHolding, prices_on_day: dict[str, float]) -> float:
    """cash + sum units x close for one day's holdings."""
    total = float(day_holding["cash"])
    for symbol, units in day_holding["units"].items():
        if abs(units) < _EPS:
            continue
        if symbol not in prices_on_day:
            raise ValueError(f"no price for {symbol}")
        total += units * prices_on_day[symbol]
    return total


def _flow(day_holding: DayHolding, prices_on_day: dict[str, float]) -> float:
    """External flow for the day: cash flows plus share transfers at the close."""
    total = float(day_holding["flow"])
    for symbol, units in day_holding["transfers"].items():
        if symbol not in prices_on_day:
            raise ValueError(f"no price for {symbol}")
        total += units * prices_on_day[symbol]
    return total


def _chain(values: list[tuple[str, float, float]]) -> list[list]:
    """(date, value, flow) per day -> [[date, index, value]], index 1.0 on the first day."""
    out: list[list] = []
    index = 1.0
    prev: float | None = None
    for when, value, flow in values:
        if prev is not None and prev > 0:
            index *= (value - flow) / prev
        out.append([when, round(index, 6), round(value, 2)])
        prev = value
    return out


def _closes(
    rows: object, days: list[str], field: str, what: str, carry: int | None = None
) -> list[float | None]:
    """``field`` per calendar day, carrying the last known value forward, over at
    most ``carry`` days of ``days`` when given."""
    clean: list[tuple[str, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            raise ValueError(f"{what}: each price row must be an object")
        price = row.get(field)
        if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
            clean.append((_iso(row.get("date"), f"{what} date"), float(price)))
    clean.sort()
    out: list[float | None] = []
    last: float | None = None
    last_at = 0  # index in ``days`` of the day the last value was seen
    j = 0
    for i, day in enumerate(days):
        while j < len(clean) and clean[j][0] <= day:
            last = clean[j][1]
            last_at = bisect_right(days, clean[j][0]) - 1
            j += 1
        out.append(last if carry is None or i - last_at <= carry else None)
    return out


def _synthetic_prices(today_price: float, proxy_rows: object) -> list[dict[str, Any]]:
    """A fund's price history from its proxy: ``today_price`` scaled back by the
    proxy's ``adj_close`` ratios (each day's adj_close over the newest one)."""
    clean: list[tuple[str, float]] = []
    for row in proxy_rows or []:
        adj = _opt(row.get("adj_close")) if isinstance(row, dict) else None
        if adj and adj > 0 and row.get("date"):
            clean.append((str(row["date"])[:10], adj))
    clean.sort()
    if not clean:
        return []
    newest = clean[-1][1]
    return [{"date": when, "close": today_price * adj / newest} for when, adj in clean]

def _year_before(day: str) -> str:
    """``day`` one year earlier, Feb 29 clamped to Feb 28."""
    d = date.fromisoformat(day)
    return date(d.year - 1, d.month, min(d.day, monthrange(d.year - 1, d.month)[1])).isoformat()


def _headline(points: list[list], as_of: str, spy: list[list] | None, estimated: bool) -> dict[str, Any]:
    """The 1Y (or All, when the series starts after ``as_of`` minus a year) return of
    ``points`` against ``spy``'s, both based on their last point on or before the
    range start (the series' first point for All). SPY with no point on or before
    that base day is null rather than based on a later day."""
    target = _year_before(as_of)
    short = points[0][0] > target
    base = points[0] if short else points[bisect_right([p[0] for p in points], target) - 1]
    ret = points[-1][1] / base[1] - 1 if base[1] > 0 else None
    spy_ret = None
    before = [p for p in spy or [] if p[0] <= base[0]]
    if spy and before and before[-1][1] > 0:
        spy_ret = round(spy[-1][1] / before[-1][1] - 1, 6)
    return {"range": "All" if short else "1Y", "start": base[0],
            "portfolio_return": None if ret is None else round(ret, 6), "spy_return": spy_ret,
            "estimated": bool(estimated)}


def _bad_trade(txns: list[dict[str, Any]], days: list[str], cash_like: frozenset[str]) -> tuple[int, str, str] | None:
    """(day index, symbol label, reason) of the newest BUY/SELL that can't be undone:
    no symbol, or no units (cash-like sweeps excepted: their trades are not rolled)."""
    worst: tuple[int, str, str] | None = None
    for txn in txns:
        kind, symbol = txn.get("type"), txn.get("symbol")
        if kind not in ("BUY", "SELL") or symbol in cash_like or str(txn["date"])[:10] > days[-1]:
            continue
        if not symbol:
            found = (min(bisect_left(days, txn["date"]), len(days) - 1), f"a {kind} row", "trade without symbol")
        elif _opt(txn.get("units")) is None:
            found = (min(bisect_left(days, txn["date"]), len(days) - 1), str(symbol), "trade without units")
        else:
            continue
        if worst is None or found[0] > worst[0]:
            worst = found
    return worst


def _multipliers(txns: list[dict[str, Any]]) -> dict[str, float]:
    """Value per unit over the quoted price, per symbol, from BUY/SELL rows carrying
    units, price and amount: |amount| / (units x price). 100 for an option quoted per
    share, 0.01 for a bond quoted per 100 of face. The largest across a symbol's rows,
    so fees err toward valuing it higher (toward a break)."""
    out: dict[str, float] = {}
    for txn in txns:
        symbol = txn.get("symbol")
        units, price, amount = _opt(txn.get("units")), _opt(txn.get("price")), _opt(txn.get("amount"))
        if txn.get("type") in ("BUY", "SELL") and symbol and units and price and amount and units > 0 and price > 0:
            out[symbol] = max(out.get(symbol, 0.0), abs(amount) / (units * price))
    return out


def _account_rows(
    account: dict[str, Any],
    txns: list[dict[str, Any]],
    yahoo_splits: dict[str, Any],
    days: list[str],
    prices_on: Any,
    others: list[int],
    cash_like: frozenset[str] = frozenset(),
) -> tuple[list[tuple[str, float, float]], tuple[str, str, str] | None, dict[str, float]]:
    """(date, value, flow) per drawable day, the break as (date, symbol, reason)
    or None, and the carried unpriced symbols with their price."""
    positions = [p for p in account.get("positions") or [] if p.get("symbol")]
    today_units = {p["symbol"]: float(p.get("units") or 0.0) for p in positions}
    events, split_breaks = _resolve_splits(txns, yahoo_splits, today_units)
    holdings = _rollback(account, txns, events, days, others, cash_like)
    last = len(days) - 1
    split_at = {min(bisect_left(days, when), last): sym for when, sym in split_breaks if when <= days[-1]}

    broker = {p["symbol"]: _opt(p.get("price")) for p in positions}
    trades: dict[str, list[tuple[str, float]]] = {}
    for txn in txns:
        price = _opt(txn.get("price"))
        if txn.get("symbol") and price and price > 0 and txn.get("type") != "SPLIT":
            factor = _split_factor(txn["symbol"], txn["date"], events)
            trades.setdefault(txn["symbol"], []).append((txn["date"], price / factor))
    for rows in trades.values():
        rows.sort()

    multiplier = _multipliers(txns)

    def fallback(symbol: str, day: str) -> tuple[float | None, str]:
        """Value per unit from the last trade price or the broker's, with the reason when none."""
        earlier = [p for when, p in trades.get(symbol, []) if when <= day]
        price = earlier[-1] if earlier else broker.get(symbol)
        if not price or price <= 0:
            return None, "no price"
        if symbol not in multiplier and OPTION_RE.match(symbol):
            return None, "no contract multiplier"  # an option with no trade to derive it from: never guess
        return price * multiplier.get(symbol, 1.0), ""

    bad = _bad_trade(txns, days, cash_like)

    margin = account.get("account_type") == "margin"
    floor = {s: min(0.0, u) for s, u in today_units.items()}
    peak: dict[str, float] = {}
    rows: list[tuple[str, float, float]] = []
    carried: dict[str, float] = {}
    brk: tuple[str, str, str] | None = None
    start_idx = 0
    for i in range(last, -1, -1):
        day = days[i]
        held = holdings[day]
        if bad is not None and i < bad[0]:  # earlier days would need the trade undone
            brk, start_idx = (days[bad[0]], bad[1], bad[2]), bad[0] + 1
            break
        if i in split_at:
            brk, start_idx = (day, split_at[i], "split"), i + 1
            break
        for symbol, units in held["units"].items():
            peak[symbol] = max(peak.get(symbol, 0.0), units)
        if i < last:  # today's units are the broker's, not a reconstruction
            neg = next((s for s, u in sorted(held["units"].items())
                        if s not in cash_like and _negative(u, peak.get(s, 0.0), floor.get(s, 0.0))), None)
            if neg:
                brk, start_idx = (days[i + 1], neg, "negative units"), i + 2
                break
        on_day = prices_on(i)
        for symbol in cash_like:
            on_day[symbol] = 1.0
        unpriced: list[str] = []
        need = {s for s, u in held["units"].items() if abs(u) >= _EPS} | set(held["transfers"])
        for symbol in sorted(need - set(on_day)):
            price, why = fallback(symbol, day)
            if price is None:
                brk = (day, symbol, why)
                break
            on_day[symbol] = price
            if abs(held["units"].get(symbol, 0.0)) >= _EPS:
                unpriced.append(symbol)
        if brk:
            start_idx = i + 1
            break
        value = _value(held, on_day)
        # the unpriced holdings together must stay under the limit
        worth = {s: abs(held["units"][s] * on_day[s]) for s in unpriced}
        big = max(worth, key=lambda s: (worth[s], s)) if worth and (
            value <= 0 or sum(worth.values()) >= UNPRICED_LIMIT * value) else None
        if big:
            brk, start_idx = (day, big, "no price"), i + 1
            break
        # cash-like units are held at today's count, so they stand in for the cash that
        # sweeps moved; judge the cash test on cash plus those units at $1.00
        liquid = held["cash"] + sum(held["units"].get(s, 0.0) for s in cash_like)
        if i < last and not margin and liquid < -CASH_LIMIT * max(value, 0.0) - 0.005:
            brk, start_idx = (days[i + 1], "cash", "negative cash"), i + 2
            break
        for symbol in unpriced:
            carried.setdefault(symbol, on_day[symbol])
        rows.append((day, value, _flow(held, on_day)))
    rows.reverse()
    if brk:
        rows = [r for r in rows if start_idx <= last and r[0] >= days[start_idx]]
    return rows, brk, carried


def _assign_rows(
    txns: list[dict[str, Any]], aliases: dict[str, Any], live_ids: set[str]
) -> tuple[list[dict[str, Any]], int]:
    """Map rows onto live account ids through ``aliases``, drop rows matching no
    account (counted), and count rows duplicated across source ids once: per live
    account and row key, only the source id with the most copies is kept."""
    kept: dict[tuple, dict[str, list[dict[str, Any]]]] = {}
    unassigned = 0
    for txn in txns:
        source = txn.get("account_id")
        live = aliases.get(source, source)
        if live not in live_ids:
            unassigned += 1
            continue
        key = (live, txn["date"], txn.get("type"), txn.get("symbol"), txn.get("units"), txn.get("amount"))
        kept.setdefault(key, {}).setdefault(source, []).append({**txn, "account_id": live})
    out: list[dict[str, Any]] = []
    for by_source in kept.values():
        out.extend(max(by_source.values(), key=len))
    return out, unassigned


def run_history(params: dict[str, Any]) -> dict[str, Any]:
    """Run the rebuild described by ``params``; raises ValueError on invalid input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    if not params.get("as_of"):
        raise ValueError("as_of is required")
    as_of = _iso(params["as_of"], "as_of")
    accounts = params.get("accounts")
    if not isinstance(accounts, list) or not all(isinstance(a, dict) and a.get("account_id") for a in accounts):
        raise ValueError("accounts must be a list of objects with account_id")
    txns_in = params.get("transactions") or []
    prices = params.get("prices") or {}
    if not isinstance(txns_in, list) or not all(isinstance(t, dict) for t in txns_in):
        raise ValueError("transactions must be a list of objects")
    if not isinstance(prices, dict):
        raise ValueError("prices must be an object")
    benchmarks = params.get("benchmarks") or []
    if not isinstance(benchmarks, list):
        raise ValueError("benchmarks must be a list")
    yahoo_splits = params.get("splits") or {}
    if not isinstance(yahoo_splits, dict):
        raise ValueError("splits must be an object")

    aliases = params.get("aliases") or {}
    proxy_map = params.get("proxies") or {}
    if not isinstance(aliases, dict) or not isinstance(proxy_map, dict):
        raise ValueError("aliases and proxies must be objects")

    all_txns: list[dict[str, Any]] = []
    for txn in txns_in:
        when = _iso(txn.get("date"), "transaction date")
        if when <= as_of:
            all_txns.append({**txn, "date": when})

    flags: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    if not all_txns:
        return {
            "as_of": as_of, "series": [], "benchmarks": [], "excluded": [],
            "flags": [{"code": "LEDGER_EMPTY", "message": "the ledger has no transactions"}],
        }

    live_ids = {a["account_id"] for a in accounts}
    txns, unassigned = _assign_rows(all_txns, aliases, live_ids)
    if unassigned:
        flags.append({"code": "UNASSIGNED_ROWS",
                      "message": f"{unassigned} ledger rows match no connected account and were ignored"})

    first = min((t["date"] for t in txns), default=as_of)
    day_set = {as_of}
    for rows in prices.values():
        for row in rows or []:
            if isinstance(row, dict):
                when = _iso(row.get("date"), "price date")
                if first <= when <= as_of:
                    day_set.add(when)
    days = sorted(day_set)

    close_by_symbol = {sym: _closes(rows, days, "close", sym, CARRY_DAYS) for sym, rows in prices.items()}

    others = [0]
    estimated: dict[str, bool] = {}
    per_account: list[tuple[dict[str, Any], list[tuple[str, float, float]]]] = []
    for account in accounts:
        acc_id = account["account_id"]
        mine = [t for t in txns if t.get("account_id") == acc_id]
        if not mine:
            excluded.append({"account_id": acc_id, "reason": "no ledger history"})
            flags.append({"code": "NO_HISTORY",
                          "message": f"{acc_id}: no ledger entries to rebuild from; import statements with "
                                     "the statement-import skill"})
            continue
        closes, synthetic = dict(close_by_symbol), {}
        names = {p["symbol"]: p.get("name") for p in account.get("positions") or [] if p.get("symbol")}
        symbols = set(names) | {t["symbol"] for t in mine if t.get("symbol")}
        cash_like = frozenset(s for s in symbols if proxy_lib.is_cash_like(s, names.get(s)))
        for position in account.get("positions") or []:
            symbol, proxy = position.get("symbol"), proxy_map.get(position.get("symbol"))
            price = _opt(position.get("price"))
            if (not proxy or not price or price <= 0 or symbol in cash_like or abs(_opt(position.get("units")) or 0.0) < _EPS
                    or _closes(prices.get(symbol), days, "close", symbol, CARRY_DAYS)[-1] is not None):
                continue
            synth = _synthetic_prices(price, prices.get(proxy))
            if synth:
                closes[symbol] = _closes(synth, days, "close", symbol)
                synthetic[symbol] = proxy

        def prices_on(i: int, closes: dict[str, list[float | None]] = closes) -> dict[str, float]:
            return {s: c[i] for s, c in closes.items() if c[i] is not None}

        # the account's own days start where its ledger does: before its oldest row nothing is known
        lo = bisect_left(days, min(t["date"] for t in mine))

        def own_prices(i: int, lo: int = lo, prices_on: Any = prices_on) -> dict[str, float]:
            return prices_on(i + lo)

        rows, brk, unpriced = _account_rows(account, mine, yahoo_splits, days[lo:], own_prices, others, cash_like)
        for symbol, proxy in sorted(synthetic.items()):
            flags.append({"code": "PROXY_PRICED",
                          "message": f"{acc_id}: {symbol} has no public price; history estimated from {proxy}"})
        estimated[acc_id] = bool(synthetic)
        if brk:
            when, symbol, reason = brk
            flags.append({"code": "HISTORY_BREAK",
                          "message": f"{acc_id}: {reason} for {symbol} on {when}; its history starts the day after"})
        for symbol, price in unpriced.items():
            flags.append({"code": "UNPRICED_HOLDING",
                          "message": f"{acc_id}: {symbol} has no market price; carried at {price:g} "
                                     f"(under {UNPRICED_LIMIT:.0%} of the account)"})
        start = next((k for k, (_, v, _) in enumerate(rows) if v > 0), None)
        if start is None:
            reason = "history break" if brk else "never held a positive value"
            excluded.append({"account_id": acc_id, "reason": reason})
            continue
        per_account.append((account, rows[start:]))

    if others[0]:
        flags.append({"code": "OTHER_TYPES", "message": f"{others[0]} OTHER ledger rows counted by amount only"})

    as_of_day = date.fromisoformat(as_of)
    long_enough = [
        (account, rows) for account, rows in per_account
        if (as_of_day - date.fromisoformat(rows[0][0])).days >= SHORT_HISTORY_DAYS
    ]
    pool = long_enough or per_account  # every account short: combine them all rather than draw nothing
    for account, rows in per_account:
        if long_enough and account["account_id"] not in {a["account_id"] for a, _ in long_enough}:
            span = (as_of_day - date.fromisoformat(rows[0][0])).days
            flags.append({"code": "SHORT_HISTORY",
                          "message": f"{account['account_id']}: only {span} days of history; "
                                     "left out of the combined line"})

    series: list[dict[str, Any]] = []
    if per_account:
        combined_start = max(rows[0][0] for _, rows in pool)
        totals: dict[str, list[float]] = {}
        for _, rows in pool:
            for when, value, flow in rows:
                if when >= combined_start:
                    acc = totals.setdefault(when, [0.0, 0.0])
                    acc[0] += value
                    acc[1] += flow
        series.append({
            "key": "combined", "label": "All accounts", "start": combined_start,
            "estimated": any(estimated.get(account["account_id"]) for account, _ in pool),
            "accounts": [account["account_id"] for account, _ in pool],
            "points": _chain([(d, v, f) for d, (v, f) in sorted(totals.items())]),
        })
        for account, rows in per_account:
            series.append({
                "key": account["account_id"],
                "label": account.get("name") or account["account_id"],
                "start": rows[0][0], "estimated": estimated.get(account["account_id"], False),
                "points": _chain(rows),
            })

    bench_out: list[dict[str, Any]] = []
    for symbol in benchmarks:
        adj = _closes(prices.get(symbol), days, "adj_close", symbol)
        have = {r.get("date")[:10] for r in prices.get(symbol) or [] if isinstance(r, dict) and r.get("date")}
        pts = [(d, a) for d, a in zip(days, adj) if a is not None and d in have]
        if len(pts) < 2:
            flags.append({"code": "BENCHMARK_UNAVAILABLE", "message": f"{symbol}: no price history over the window"})
            continue
        base = pts[0][1]
        bench_out.append({
            "symbol": symbol, "label": BENCHMARK_LABELS.get(symbol, symbol),
            "points": [[d, round(a / base, 6)] for d, a in pts],
        })

    spy = next((b["points"] for b in bench_out if b["symbol"] == "SPY"), None)
    for s in series:
        s["headline"] = _headline(s["points"], as_of, spy, s["estimated"])
    return {"as_of": as_of, "series": series, "benchmarks": bench_out, "excluded": excluded, "flags": flags}


def main() -> None:
    """Read JSON params from stdin, write the history result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        params = json.loads(raw)
        result = run_history(params)
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
