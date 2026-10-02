"""Trade decision review: FIFO round trips with dividends, outcome statistics,
the disposition effect (Odean 1998), post-sale drift, pre-trade context,
buy-and-hold and benchmark counterfactuals, open lots, a strategy-alignment
matrix, a research queue, and behavioural flags.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python review.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "as_of": "2025-12-31",                # optional, default today
      "transactions": [ ...ledger entries from statement-import (normalize.py):
                        date, type, symbol, units, price, amount, fee,
                        account_id ... ],   # BUY, SELL, DIVIDEND, SPLIT are used;
                                            # other types are ignored
      "prices": {"AAPL": [{"date": "YYYY-MM-DD", "close": 100.0,
                           "adj_close": 99.0}, ...]},   # optional per symbol;
                                            # adj_close optional (defaults to close)
      "benchmark": {"symbol": "SPY", "prices": [...same shape...]}   # optional
    }

Output JSON contract (stdout)::

    {
      "as_of", "missing_prices": [...],
      "summary": {round_trips, win_rate, realized_pnl, dividends_captured,
                  total_pnl, profit_factor, avg_return, median_return,
                  avg_holding_days, median_holding_days, buys, sells,
                  span_days, trades_per_year, sell_to_buy_ratio, symbols_traded},
      "round_trips": [{symbol, account_id, sell_date, sell_price, units, lots,
                       first_buy_date, holding_days, cost, avg_cost, proceeds,
                       dividends, realized_pnl, total_pnl, total_return,
                       pre_buy: {momentum_12_1, return_1m, drawdown_52w},
                       pre_sell: {return_1m, return_3m, from_52w_high},
                       drift: {"30","90","180","365"}, benchmark_drift, drift_vs_benchmark_90,
                       hold_value, hold_delta, proceeds_in_benchmark}],   # sell date order
      "open_lots": [{symbol, account_id, buy_date, units, cost, avg_cost, price,
                     value, dividends, unrealized_pnl, unrealized_return, holding_days}],
      "unmatched_sells": [{symbol, account_id, date, units}],
      "unattributed_dividends": 0.0,
      "disposition": {realized_gains, realized_losses, paper_gains, paper_losses,
                      pgr, plr, disposition, sell_days},
      "counterfactual": {proceeds, hold_value, hold_delta, proceeds_in_benchmark,
                         benchmark_symbol},
      "strategy_matrix": [{strategy, alignment: low|medium|high, evidence: {...}}],
      "research_queue": [{symbol, sell_date, first_buy_date, total_pnl, drift_90, why}],
      "streaks": {current: {kind: "win"|"loss"|null, length}, max_win, max_loss},
      "fees_total": 0.0,
      "reentries": [{symbol, sell_date, sell_price, rebuy_date, rebuy_price, delta_pct}],
      "yearly": [{year, round_trips, realized_pnl, dividends}],
      "flags": [{code, message}]    # DISPOSITION_EFFECT, OVERTRADING, LOSS_HOLDING,
                                    # SOLD_WINNERS_EARLY, CHASED_MOMENTUM, FEE_DRAG,
                                    # REENTERED_HIGHER
    }

Method:
- Lots are matched FIFO per (account, symbol). A sell that spans several lots
  is ONE round trip with the earliest lot's date as first_buy_date. Lot cost
  is -amount when present (fees included), else units x price. DIVIDEND rows
  are spread over the open lots of that account/symbol pro rata by units, so
  each round trip carries the dividends it actually earned; dividends with no
  open lot go to unattributed_dividends. SPLIT rows with units add shares to
  open lots pro rata (cost unchanged).
- Disposition (Odean 1998): on each sell day per account, every lot sold above
  its cost is a realized gain and below it a realized loss; every lot still
  open in that account at that day's close is a paper gain or loss. PGR =
  realized gains / (realized gains + paper gains), PLR likewise; disposition =
  PGR - PLR (positive: sells winners, keeps losers).
- Drift: price h days after the sale relative to the SELL PRICE, in the
  adjusted frame (adj_close ratio x close/sell_price), so dividends after the
  sale count. Benchmark drift is the adjusted benchmark ratio. Horizons past
  as_of are null.
- Pre-buy context at the first lot's buy date: momentum_12_1 = close(d-30) /
  close(d-365) - 1, return_1m = close(d)/close(d-30) - 1, drawdown_52w =
  close(d)/max(close over the prior 365d) - 1. Pre-sell context uses closes
  at the sell date the same way (return_1m, return_3m, from_52w_high).
- Counterfactuals: hold_value = units x adj(as_of) x close(sell)/adj(sell)
  (what the sold shares would be worth today, dividends included);
  proceeds_in_benchmark = proceeds x benchmark adj(as_of)/adj(sell).
  If a split happened after a sale, hold_value is understated.
- Strategy matrix thresholds: buy_and_hold high when median holding >= 365d
  and <= 6 trades/yr, medium when median >= 180d; momentum high when >= 60%
  of buys follow positive 12-1 momentum, medium >= 40%; contrarian high when
  >= 60% of buys are made >= 10% below the 52-week high, medium >= 40%;
  dividend_income high when dividends are >= 50% of total P&L, medium >= 20%;
  short_term_trading high when median holding < 30d or >= 52 trades/yr,
  medium when < 90d or >= 24 trades/yr.
- Flags: DISPOSITION_EFFECT when disposition >= 0.10; OVERTRADING when
  trades_per_year >= 24 (Barber & Odean 2000: the most active quintile
  underperformed by ~6.5%/yr); LOSS_HOLDING for open lots >= 365d at or
  below -20%; SOLD_WINNERS_EARLY when the median 90-day drift of winning
  sales is >= +10%; CHASED_MOMENTUM when > 50% of buys follow a 1-month
  return of >= +10%. Money 2 dp, ratios 4 dp.
- Streaks: round trips in sell-date order; a trip is a win when realized_pnl
  > 0 and a loss when it is < 0 (a flat trip breaks the run). The current
  streak counts consecutive trips of the last trip's kind backwards from the
  most recent; max_win/max_loss are the longest runs.
- Fees: fees_total sums every used transaction's fee field; FEE_DRAG flags
  when it reaches $100.
- Re-entries: for each SELL, the first later BUY of the same symbol+account
  strictly after the sell date and within 30 calendar days at a HIGHER price
  (lower re-buys are averaging-down and are not flagged); delta_pct is the
  rebuy premium over the sell price; REENTERED_HIGHER flags when any exist.
- Yearly: realized P&L and dividends grouped by each round trip's sell-date
  calendar year, ascending.
"""

from __future__ import annotations

import json
import re
import sys
from bisect import bisect_right
from datetime import date, timedelta
from statistics import median

_HORIZONS = (30, 90, 180, 365)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _money(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


def _ratio(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _number(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    return float(v)


def _parse_date(raw: object, field: str) -> date:
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


class _Prices:
    """Sorted daily closes with last-on-or-before lookups."""

    def __init__(self, rows: object) -> None:
        self.dates: list[str] = []
        self.close: list[float] = []
        self.adj: list[float] = []
        if not isinstance(rows, list):
            raise ValueError("each price series must be a list")
        clean = []
        for r in rows:
            if not isinstance(r, dict) or not r.get("date") or r.get("close") is None:
                continue
            c = _number(r["close"], "close")
            a = _number(r.get("adj_close"), "adj_close")
            clean.append((str(r["date"])[:10], c, a if a is not None else c))
        for d, c, a in sorted(clean):
            self.dates.append(d)
            self.close.append(c)
            self.adj.append(a)

    def _idx(self, d: date) -> int:
        return bisect_right(self.dates, d.isoformat()) - 1

    def on(self, d: date) -> float | None:
        i = self._idx(d)
        return self.close[i] if i >= 0 else None

    def adj_on(self, d: date) -> float | None:
        i = self._idx(d)
        return self.adj[i] if i >= 0 else None

    def max_between(self, start: date, end: date) -> float | None:
        lo = bisect_right(self.dates, (start - timedelta(days=1)).isoformat())
        hi = bisect_right(self.dates, end.isoformat())
        window = self.close[lo:hi]
        return max(window) if window else None

    @property
    def empty(self) -> bool:
        return not self.dates


def _validate(params: dict) -> list[dict]:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    txs = params.get("transactions")
    if not isinstance(txs, list) or not txs:
        raise ValueError("at least one transaction is required")
    out = []
    for i, t in enumerate(txs):
        if not isinstance(t, dict) or not t.get("date") or not t.get("type"):
            raise ValueError(
                "each transaction requires date, type, symbol (symbol for BUY/SELL/DIVIDEND)"
            )
        kind = str(t["type"]).upper()
        if kind in ("BUY", "SELL", "DIVIDEND", "SPLIT") and not t.get("symbol"):
            raise ValueError(
                "each transaction requires date, type, symbol (symbol for BUY/SELL/DIVIDEND)"
            )
        if kind not in ("BUY", "SELL", "DIVIDEND", "SPLIT"):
            continue
        out.append(
            {
                "i": i,
                "date": _parse_date(t["date"], "transaction date"),
                "type": kind,
                "symbol": str(t["symbol"]).upper(),
                "account": str(t.get("account_id")),
                "units": _number(t.get("units"), "units"),
                "price": _number(t.get("price"), "price"),
                "amount": _number(t.get("amount"), "amount"),
                "fee": _number(t.get("fee"), "fee") or 0.0,
            }
        )
    if (
        "prices" in params
        and params["prices"] is not None
        and not isinstance(params["prices"], dict)
    ):
        raise ValueError("prices must be an object keyed by symbol")
    return sorted(out, key=lambda t: (t["date"], t["i"]))


def _ret(a: float | None, b: float | None) -> float | None:
    return None if a is None or not b else a / b - 1


def run_review(params: dict) -> dict:
    """Review the trades in ``params``; raises ValueError/TypeError on bad input."""
    events = _validate(params)
    as_of = (
        _parse_date(params["as_of"], "as_of") if params.get("as_of") is not None else date.today()
    )
    prices = {str(k).upper(): _Prices(v) for k, v in (params.get("prices") or {}).items()}
    bench_in = params.get("benchmark") if isinstance(params.get("benchmark"), dict) else None
    bench = _Prices(bench_in.get("prices") or []) if bench_in else None
    bench_symbol = (
        str(bench_in.get("symbol")).upper()
        if bench_in and bench_in.get("symbol") and bench and not bench.empty
        else None
    )
    if bench is not None and bench.empty:
        bench = None

    def px(sym: str) -> _Prices | None:
        p = prices.get(sym)
        return p if p is not None and not p.empty else None

    # --- lot engine -------------------------------------------------------------------
    lots: dict[tuple[str, str], list[dict]] = {}
    round_trips: list[dict] = []
    unmatched: list[dict] = []
    unattributed = 0.0
    realized = {"gains": 0, "losses": 0}
    paper = {"gains": 0, "losses": 0}
    sell_days: set[tuple[str, date]] = set()
    buy_context: list[dict] = []
    buys = sells = 0
    buy_cost_total = sell_proceeds_total = 0.0

    def pre_buy(sym: str, d: date) -> dict:
        p = px(sym)
        if p is None:
            return {"momentum_12_1": None, "return_1m": None, "drawdown_52w": None}
        now = p.on(d)
        return {
            "momentum_12_1": _ratio(
                _ret(p.on(d - timedelta(days=30)), p.on(d - timedelta(days=365)))
            ),
            "return_1m": _ratio(_ret(now, p.on(d - timedelta(days=30)))),
            "drawdown_52w": _ratio(_ret(now, p.max_between(d - timedelta(days=365), d))),
        }

    for e in events:
        key = (e["account"], e["symbol"])
        book = lots.setdefault(key, [])
        if e["type"] == "BUY":
            units = e["units"] or 0.0
            if units <= 0:
                continue
            cost = (
                -e["amount"] if e["amount"] is not None else units * (e["price"] or 0.0) + e["fee"]
            )
            book.append(
                {
                    "date": e["date"],
                    "units": units,
                    "cost": abs(cost),
                    "price": abs(cost) / units,
                    "dividends": 0.0,
                }
            )
            buys += 1
            buy_cost_total += abs(cost)
            buy_context.append(pre_buy(e["symbol"], e["date"]))
        elif e["type"] == "DIVIDEND":
            amount = abs(e["amount"] or 0.0)
            held = sum(lot["units"] for lot in book)
            if held > 0 and amount:
                for lot in book:
                    lot["dividends"] += amount * lot["units"] / held
            else:
                unattributed += amount
        elif e["type"] == "SPLIT":
            added = e["units"] or 0.0
            held = sum(lot["units"] for lot in book)
            if added > 0 and held > 0:
                for lot in book:
                    lot["units"] += added * lot["units"] / held
        elif e["type"] == "SELL":
            units = e["units"] or 0.0
            if units <= 0:
                continue
            sells += 1
            total_proceeds = (
                abs(e["amount"])
                if e["amount"] is not None
                else units * (e["price"] or 0.0) - e["fee"]
            )
            sell_price = e["price"] if e["price"] else total_proceeds / units
            remaining = units
            cost = dividends = 0.0
            consumed = 0
            first_date: date | None = None
            while remaining > 1e-12 and book:
                lot = book[0]
                take = min(lot["units"], remaining)
                frac = take / lot["units"]
                lot_cost = lot["cost"] * frac
                cost += lot_cost
                dividends += lot["dividends"] * frac
                if sell_price > lot["price"]:
                    realized["gains"] += 1
                elif sell_price < lot["price"]:
                    realized["losses"] += 1
                first_date = (
                    lot["date"] if first_date is None or lot["date"] < first_date else first_date
                )
                consumed += 1
                lot["units"] -= take
                lot["cost"] -= lot_cost
                lot["dividends"] -= lot["dividends"] * frac
                remaining -= take
                if lot["units"] <= 1e-12:
                    book.pop(0)
            matched = units - remaining
            if remaining > 1e-12:
                unmatched.append(
                    {
                        "symbol": e["symbol"],
                        "account_id": e["account"],
                        "date": e["date"].isoformat(),
                        "units": _ratio(remaining),
                    }
                )
            if matched <= 1e-12 or first_date is None:
                continue
            proceeds = total_proceeds * matched / units
            sell_proceeds_total += proceeds
            sell_days.add((e["account"], e["date"]))
            round_trips.append(
                {
                    "symbol": e["symbol"],
                    "account_id": e["account"],
                    "_sell_date": e["date"],
                    "_first": first_date,
                    "sell_date": e["date"].isoformat(),
                    "sell_price": _money(sell_price),
                    "units": _ratio(matched),
                    "lots": consumed,
                    "first_buy_date": first_date.isoformat(),
                    "holding_days": (e["date"] - first_date).days,
                    "cost": _money(cost),
                    "avg_cost": _ratio(cost / matched),
                    "proceeds": _money(proceeds),
                    "dividends": _money(dividends),
                    "realized_pnl": _money(proceeds - cost),
                    "total_pnl": _money(proceeds - cost + dividends),
                    "total_return": _ratio((proceeds - cost + dividends) / cost) if cost else None,
                    "_proceeds": proceeds,
                    "_cost": cost,
                    "_pnl": proceeds - cost + dividends,
                    "_div": dividends,
                    "_units": matched,
                }
            )
    # paper gains/losses: one evaluation per (account, sell day) over lots open at that close
    # (re-run the engine's state is not needed: evaluate from a second pass over events)
    open_by_day: dict[tuple[str, date], list[dict]] = {}
    state: dict[tuple[str, str], list[dict]] = {}
    day_events: dict[tuple[str, date], bool] = {}
    for e in events:
        key = (e["account"], e["symbol"])
        book = state.setdefault(key, [])
        if e["type"] == "BUY" and (e["units"] or 0) > 0:
            cost = (
                -e["amount"]
                if e["amount"] is not None
                else e["units"] * (e["price"] or 0.0) + e["fee"]
            )
            book.append(
                {"symbol": e["symbol"], "units": e["units"], "price": abs(cost) / e["units"]}
            )
        elif e["type"] == "SPLIT" and (e["units"] or 0) > 0:
            held = sum(lot["units"] for lot in book)
            for lot in book:
                lot["units"] += e["units"] * lot["units"] / held if held else 0
        elif e["type"] == "SELL" and (e["units"] or 0) > 0:
            remaining = e["units"]
            while remaining > 1e-12 and book:
                take = min(book[0]["units"], remaining)
                book[0]["units"] -= take
                remaining -= take
                if book[0]["units"] <= 1e-12:
                    book.pop(0)
            day_events[(e["account"], e["date"])] = True
        # snapshot open lots at the end of each event; the last snapshot of a day wins
        if (e["account"], e["date"]) in day_events:
            open_by_day[(e["account"], e["date"])] = [
                dict(lot) for k, ls in state.items() if k[0] == e["account"] for lot in ls
            ]
    for (account, d), open_lots_then in open_by_day.items():
        for lot in open_lots_then:
            p = px(lot["symbol"])
            close = p.on(d) if p else None
            if close is None:
                continue
            if close > lot["price"]:
                paper["gains"] += 1
            elif close < lot["price"]:
                paper["losses"] += 1

    # --- per round trip: context, drift, counterfactuals -------------------------------
    for r in round_trips:
        sym, sd, fd = r["symbol"], r["_sell_date"], r["_first"]
        p = px(sym)
        r["pre_buy"] = pre_buy(sym, fd)
        if p is None:
            r["pre_sell"] = {"return_1m": None, "return_3m": None, "from_52w_high": None}
            r["drift"] = {str(h): None for h in _HORIZONS}
            r["hold_value"] = r["hold_delta"] = None
        else:
            now = p.on(sd)
            r["pre_sell"] = {
                "return_1m": _ratio(_ret(now, p.on(sd - timedelta(days=30)))),
                "return_3m": _ratio(_ret(now, p.on(sd - timedelta(days=90)))),
                "from_52w_high": _ratio(_ret(now, p.max_between(sd - timedelta(days=365), sd))),
            }
            base_adj, base_close = p.adj_on(sd), p.on(sd)
            frame = (base_close / base_adj) if base_adj and base_close else None
            drift = {}
            for h in _HORIZONS:
                target = sd + timedelta(days=h)
                if target > as_of or frame is None or not r["sell_price"]:
                    drift[str(h)] = None
                    continue
                adj_t = p.adj_on(target)
                drift[str(h)] = (
                    _ratio(adj_t * frame / r["sell_price"] - 1) if adj_t is not None else None
                )
            r["drift"] = drift
            adj_now = p.adj_on(as_of)
            hold = r["_units"] * adj_now * frame if adj_now is not None and frame else None
            r["hold_value"] = _money(hold)
            r["hold_delta"] = _money(hold - r["_proceeds"]) if hold is not None else None
        if bench is not None:
            b0 = bench.adj_on(sd)
            bd = {}
            for h in _HORIZONS:
                target = sd + timedelta(days=h)
                bt = bench.adj_on(target) if target <= as_of else None
                bd[str(h)] = _ratio(_ret(bt, b0)) if bt is not None else None
            r["benchmark_drift"] = bd
            bn = bench.adj_on(as_of)
            r["proceeds_in_benchmark"] = (
                _money(r["_proceeds"] * bn / b0) if bn is not None and b0 else None
            )
        else:
            r["benchmark_drift"] = None
            r["proceeds_in_benchmark"] = None
        d90, b90 = r["drift"]["90"], (r["benchmark_drift"] or {}).get("90")
        r["drift_vs_benchmark_90"] = (
            _ratio(d90 - b90) if d90 is not None and b90 is not None else None
        )

    # --- open lots ---------------------------------------------------------------------
    open_lots = []
    for (account, sym), book in lots.items():
        p = px(sym)
        price = p.on(as_of) if p else None
        for lot in book:
            if lot["units"] <= 1e-12:
                continue
            value = lot["units"] * price if price is not None else None
            open_lots.append(
                {
                    "symbol": sym,
                    "account_id": account,
                    "buy_date": lot["date"].isoformat(),
                    "units": _ratio(lot["units"]),
                    "cost": _money(lot["cost"]),
                    "avg_cost": _ratio(lot["cost"] / lot["units"]),
                    "price": _money(price),
                    "value": _money(value),
                    "dividends": _money(lot["dividends"]),
                    "unrealized_pnl": _money(value - lot["cost"]) if value is not None else None,
                    "unrealized_return": _ratio((value - lot["cost"]) / lot["cost"])
                    if value is not None and lot["cost"]
                    else None,
                    "holding_days": (as_of - lot["date"]).days,
                }
            )
    open_lots.sort(key=lambda lot: (lot["symbol"], lot["account_id"], lot["buy_date"]))

    # --- summary -------------------------------------------------------------------------
    pnls = [r["_pnl"] for r in round_trips]
    rets = [r["total_return"] for r in round_trips if r["total_return"] is not None]
    holds = [r["holding_days"] for r in round_trips]
    gains = sum(x for x in pnls if x > 0)
    losses = -sum(x for x in pnls if x < 0)
    first_trade = events[0]["date"] if events else as_of
    span_days = max((as_of - first_trade).days, 0)
    years = span_days / 365.25 if span_days > 0 else None
    summary = {
        "round_trips": len(round_trips),
        "win_rate": _ratio(sum(1 for x in pnls if x > 0) / len(pnls)) if pnls else None,
        "realized_pnl": _money(sum(r["_proceeds"] - r["_cost"] for r in round_trips)),
        "dividends_captured": _money(sum(r["_div"] for r in round_trips)),
        "total_pnl": _money(sum(pnls)),
        "profit_factor": _ratio(gains / losses) if losses > 0 else None,
        "avg_return": _ratio(sum(rets) / len(rets)) if rets else None,
        "median_return": _ratio(median(rets)) if rets else None,
        "avg_holding_days": round(sum(holds) / len(holds), 1) if holds else None,
        "median_holding_days": float(median(holds)) if holds else None,
        "buys": buys,
        "sells": sells,
        "span_days": span_days,
        "trades_per_year": round((buys + sells) / years, 2) if years else None,
        "sell_to_buy_ratio": _ratio(sell_proceeds_total / buy_cost_total)
        if buy_cost_total > 0
        else None,
        "symbols_traded": sorted({e["symbol"] for e in events if e["type"] in ("BUY", "SELL")}),
    }

    rg, rl, pg, pl = realized["gains"], realized["losses"], paper["gains"], paper["losses"]
    pgr = rg / (rg + pg) if rg + pg else None
    plr = rl / (rl + pl) if rl + pl else None
    disposition = {
        "realized_gains": rg,
        "realized_losses": rl,
        "paper_gains": pg,
        "paper_losses": pl,
        "pgr": _ratio(pgr),
        "plr": _ratio(plr),
        "disposition": _ratio(pgr - plr) if pgr is not None and plr is not None else None,
        "sell_days": len(sell_days),
    }

    holds_known = [r for r in round_trips if r["hold_value"] is not None]
    counterfactual = {
        "proceeds": _money(sum(r["_proceeds"] for r in round_trips)),
        "hold_value": _money(sum(r["hold_value"] for r in holds_known)) if holds_known else None,
        "hold_delta": _money(sum(r["hold_value"] - r["_proceeds"] for r in holds_known))
        if holds_known
        else None,
        "proceeds_in_benchmark": _money(
            sum(
                r["proceeds_in_benchmark"]
                for r in round_trips
                if r["proceeds_in_benchmark"] is not None
            )
        )
        if bench is not None and round_trips
        else None,
        "benchmark_symbol": bench_symbol,
    }

    # --- strategy matrix -----------------------------------------------------------------
    mom_known = [c["momentum_12_1"] for c in buy_context if c["momentum_12_1"] is not None]
    dd_known = [c["drawdown_52w"] for c in buy_context if c["drawdown_52w"] is not None]
    r1m_known = [c["return_1m"] for c in buy_context if c["return_1m"] is not None]
    share_mom = (sum(1 for m in mom_known if m > 0) / len(mom_known)) if mom_known else None
    share_dd = (sum(1 for d in dd_known if d <= -0.10) / len(dd_known)) if dd_known else None
    share_chase = (sum(1 for r in r1m_known if r >= 0.10) / len(r1m_known)) if r1m_known else None
    med_hold = summary["median_holding_days"]
    tpy = summary["trades_per_year"]
    div_share = (
        (summary["dividends_captured"] / summary["total_pnl"]) if summary["total_pnl"] else None
    )
    div_events = sum(1 for e in events if e["type"] == "DIVIDEND")

    def level(value: float | None, high: float, medium: float, reverse: bool = False) -> str:
        if value is None:
            return "unknown"
        if reverse:
            return "high" if value <= high else "medium" if value <= medium else "low"
        return "high" if value >= high else "medium" if value >= medium else "low"

    bh = (
        "unknown"
        if med_hold is None
        else (
            "high"
            if med_hold >= 365 and (tpy or 0) <= 6
            else "medium"
            if med_hold >= 180
            else "low"
        )
    )
    st = (
        "unknown"
        if med_hold is None and tpy is None
        else (
            "high"
            if (med_hold is not None and med_hold < 30) or (tpy or 0) >= 52
            else "medium"
            if (med_hold is not None and med_hold < 90) or (tpy or 0) >= 24
            else "low"
        )
    )
    strategy_matrix = [
        {
            "strategy": "buy_and_hold",
            "alignment": bh,
            "evidence": {
                "median_holding_days": med_hold,
                "trades_per_year": tpy,
                "open_lots": len(open_lots),
            },
        },
        {
            "strategy": "momentum",
            "alignment": level(share_mom, 0.6, 0.4),
            "evidence": {
                "buys_after_positive_momentum": _ratio(share_mom),
                "buys_with_known_momentum": len(mom_known),
            },
        },
        {
            "strategy": "contrarian",
            "alignment": level(share_dd, 0.6, 0.4),
            "evidence": {
                "buys_at_least_10pct_below_52w_high": _ratio(share_dd),
                "avg_drawdown_at_buy": _ratio(sum(dd_known) / len(dd_known)) if dd_known else None,
            },
        },
        {
            "strategy": "dividend_income",
            "alignment": level(div_share, 0.5, 0.2),
            "evidence": {"dividend_share_of_pnl": _ratio(div_share), "dividend_events": div_events},
        },
        {
            "strategy": "short_term_trading",
            "alignment": st,
            "evidence": {"trades_per_year": tpy, "median_holding_days": med_hold},
        },
    ]

    # --- research queue ------------------------------------------------------------------
    def item(r: dict, why: str) -> dict:
        return {
            "symbol": r["symbol"],
            "sell_date": r["sell_date"],
            "first_buy_date": r["first_buy_date"],
            "total_pnl": r["total_pnl"],
            "drift_90": r["drift"]["90"],
            "why": why,
        }

    gains_sorted = sorted((r for r in round_trips if r["_pnl"] > 0), key=lambda r: -r["_pnl"])
    losses_sorted = sorted((r for r in round_trips if r["_pnl"] < 0), key=lambda r: r["_pnl"])
    drift_sorted = sorted(
        (r for r in round_trips if r["drift"]["90"] is not None),
        key=lambda r: -abs(r["drift"]["90"]),
    )
    queue: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for pair in zip(gains_sorted[:3] + [None] * 3, losses_sorted[:3] + [None] * 3):
        for r, why in ((pair[0], "largest gain"), (pair[1], "largest loss")):
            if r is not None and (r["symbol"], r["sell_date"]) not in seen:
                seen.add((r["symbol"], r["sell_date"]))
                queue.append(item(r, why))
    for r in drift_sorted[:3]:
        if (r["symbol"], r["sell_date"]) not in seen:
            seen.add((r["symbol"], r["sell_date"]))
            queue.append(item(r, "biggest move after the sale"))

    # --- streaks, fees, re-entries, yearly P&L ---------------------------------------------
    run_kind: str | None = None
    run_len = 0
    max_win = max_loss = 0
    for r in round_trips:
        pnl = r["_proceeds"] - r["_cost"]
        kind = "win" if pnl > 0 else "loss" if pnl < 0 else None
        if kind is None:
            run_kind, run_len = None, 0
        elif kind == run_kind:
            run_len += 1
        else:
            run_kind, run_len = kind, 1
        if run_kind == "win":
            max_win = max(max_win, run_len)
        elif run_kind == "loss":
            max_loss = max(max_loss, run_len)
    current_kind: str | None = None
    current_len = 0
    if round_trips:
        last = round_trips[-1]["_proceeds"] - round_trips[-1]["_cost"]
        current_kind = "win" if last > 0 else "loss" if last < 0 else None
        if current_kind is not None:
            for r in reversed(round_trips):
                pnl = r["_proceeds"] - r["_cost"]
                kind = "win" if pnl > 0 else "loss" if pnl < 0 else None
                if kind != current_kind:
                    break
                current_len += 1
    streaks = {
        "current": {"kind": current_kind, "length": current_len},
        "max_win": max_win,
        "max_loss": max_loss,
    }

    fees_total = _money(sum(e["fee"] for e in events))

    buys_by_key: dict[tuple[str, str], list[tuple[date, float]]] = {}
    for e in events:
        if e["type"] != "BUY" or (e["units"] or 0.0) <= 0:
            continue
        price = e["price"]
        if not price and e["amount"] is not None:
            price = abs(e["amount"]) / e["units"]
        if price:
            buys_by_key.setdefault((e["account"], e["symbol"]), []).append((e["date"], price))
    reentries: list[dict] = []
    for e in events:
        if e["type"] != "SELL" or (e["units"] or 0.0) <= 0:
            continue
        proceeds = (
            abs(e["amount"])
            if e["amount"] is not None
            else (e["units"] or 0.0) * (e["price"] or 0.0) - e["fee"]
        )
        sell_price = e["price"] or (proceeds / e["units"] if proceeds else None)
        if not sell_price:
            continue
        for buy_date, buy_price in buys_by_key.get((e["account"], e["symbol"]), []):
            if not (e["date"] < buy_date <= e["date"] + timedelta(days=30)):
                continue
            if buy_price > sell_price:
                reentries.append(
                    {
                        "symbol": e["symbol"],
                        "sell_date": e["date"].isoformat(),
                        "sell_price": _money(sell_price),
                        "rebuy_date": buy_date.isoformat(),
                        "rebuy_price": _money(buy_price),
                        "delta_pct": _ratio(buy_price / sell_price - 1),
                    }
                )
                break

    per_year: dict[int, dict] = {}
    for r in round_trips:
        y = r["_sell_date"].year
        row = per_year.setdefault(
            y, {"year": y, "round_trips": 0, "realized_pnl": 0.0, "dividends": 0.0}
        )
        row["round_trips"] += 1
        row["realized_pnl"] += r["_proceeds"] - r["_cost"]
        row["dividends"] += r["_div"]
    yearly = [
        {
            "year": y,
            "round_trips": row["round_trips"],
            "realized_pnl": _money(row["realized_pnl"]),
            "dividends": _money(row["dividends"]),
        }
        for y, row in sorted(per_year.items())
    ]

    # --- flags ---------------------------------------------------------------------------
    flags: list[dict] = []
    if disposition["disposition"] is not None and disposition["disposition"] >= 0.10:
        pgr_pct, plr_pct = round((pgr or 0) * 100, 1), round((plr or 0) * 100, 1)
        msg = (
            f"realized {pgr_pct}% of gains but only {plr_pct}% of losses "
            f"(PGR-PLR {disposition['disposition']}): winners are sold, losers kept"
        )
        flags.append({"code": "DISPOSITION_EFFECT", "message": msg})
    if tpy is not None and tpy >= 24:
        msg = (
            f"{tpy} trades per year; Barber & Odean (2000) found the most active households "
            "trailed the least active by about 6.5% a year"
        )
        flags.append({"code": "OVERTRADING", "message": msg})
    losers = [
        lot
        for lot in open_lots
        if lot["unrealized_return"] is not None
        and lot["unrealized_return"] <= -0.20
        and lot["holding_days"] >= 365
    ]
    if losers:
        flags.append(
            {
                "code": "LOSS_HOLDING",
                "message": "open for a year or more at 20%+ below cost: "
                + ", ".join(
                    f"{lot['symbol']} ({round(lot['unrealized_return'] * 100, 1)}%)"
                    for lot in losers
                ),
            }
        )
    win_drifts = [
        r["drift"]["90"] for r in round_trips if r["_pnl"] > 0 and r["drift"]["90"] is not None
    ]
    if win_drifts and median(win_drifts) >= 0.10:
        med = round(median(win_drifts) * 100, 1)
        msg = f"winning sales kept rising: median +{med}% in the 90 days after the sale"
        flags.append({"code": "SOLD_WINNERS_EARLY", "message": msg})
    if share_chase is not None and share_chase > 0.5 and len(r1m_known) >= 3:
        msg = f"{round(share_chase * 100, 1)}% of buys came after a 1-month gain of 10% or more"
        flags.append({"code": "CHASED_MOMENTUM", "message": msg})
    if fees_total is not None and fees_total >= 100:
        flags.append(
            {"code": "FEE_DRAG", "message": f"fees totalled ${fees_total:,.2f} over the span"}
        )
    if reentries:
        listed = "; ".join(
            f"{x['symbol']} on {x['rebuy_date']} at {x['rebuy_price']} "
            f"({x['delta_pct'] * 100:+.1f}%)"
            for x in reentries[:5]
        )
        if len(reentries) > 5:
            listed += f"; and {len(reentries) - 5} more"
        flags.append(
            {
                "code": "REENTERED_HIGHER",
                "message": f"bought back within 30 days at a higher price: {listed}",
            }
        )

    for r in round_trips:
        for k in [k for k in r if k.startswith("_")]:
            r.pop(k)
    return {
        "as_of": as_of.isoformat(),
        "missing_prices": sorted(
            {e["symbol"] for e in events if e["type"] in ("BUY", "SELL")}
            - {s for s in prices if not prices[s].empty}
        ),
        "summary": summary,
        "round_trips": round_trips,
        "open_lots": open_lots,
        "unmatched_sells": unmatched,
        "unattributed_dividends": _money(unattributed),
        "disposition": disposition,
        "counterfactual": counterfactual,
        "strategy_matrix": strategy_matrix,
        "research_queue": queue,
        "streaks": streaks,
        "fees_total": fees_total,
        "reentries": reentries,
        "yearly": yearly,
        "flags": flags,
    }


def main() -> None:
    """Read JSON params from stdin, write the review (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_review(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
