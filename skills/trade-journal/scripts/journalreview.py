"""Trade-journal review: match pre-trade journal entries (thesis, entry,
target, stop, horizon, conviction, tags) to what actually happened, classify
each exit against the plan, and summarize process quality.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python journalreview.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {
      "as_of": "2026-09-04",                # optional, default today
      "entries": [{"id": "j1", "date": "2026-01-05", "symbol": "AAPL",
                   "side": "long"|"short", "thesis": "...", "entry_price": 100,
                   "target": 130, "stop": 90, "horizon_days": 90,
                   "conviction": 1-5, "tags": ["earnings"], "status": "open"|"closed",
                   "closed": {"date": "...", "price": 131, "notes": "..."} | null,
                   "revisions": [{"at": "...", "changes": {"stop": {"from": 90, "to": 85}}}]],
      "round_trips": [ ...trade-review's review.py round_trips (symbol,
                       first_buy_date, sell_date, sell_price, total_return ...) ]   # optional
      "prices": {"AAPL": [{"date": "2026-01-06", "close": 105.0}, ...]}   # optional;
                                          # ascending daily closes per symbol
    }

Output JSON contract (stdout)::

    {
      "as_of",
      "entries": [{id, date, symbol, side, conviction, tags, planned_rr, matched,
                   source: "ledger"|"journal"|null, round_trip: {first_buy_date, sell_date,
                   sell_price, total_return, holding_days} | null, exit: "target hit"|
                   "stopped"|"discretionary"|"open", exit_price, realized_return,
                   realized_rr, holding_days, days_open, plan_consistent, within_horizon,
                   mfe_pct, mae_pct, touch_order: "target first"|"stop first"|"neither"|null,
                   stop_drifted, original_stop}],
      "summary": {entries, open, closed, matched_to_ledger, plan_consistent_rate,
                  within_horizon_rate, avg_planned_rr, win_rate, avg_realized_return,
                  exits: {exit: count}},
      "by_conviction": [{conviction, closed, win_rate, avg_return}],
      "by_tag": [{tag, closed, win_rate, avg_return}],
      "flags": [{code, message}]     # OVERSTAYED, STALE_OPEN, LOW_PLANNED_RR,
                                     # MISSING_LEVELS, STOP_DRIFTED
    }

Method: an entry matches the round trip of the same symbol whose first buy
is within 7 days of the entry date and whose sale is after it (earliest
sale first; each round trip is used once). Closed entries without a match
use the journal's own close. Planned reward-to-risk = (target - entry) /
(entry - stop) for longs and the mirror for shorts. Exit is "target hit"
when the exit price reached the target, "stopped" when it reached the stop,
else "discretionary"; plan_consistent means one of the first two;
within_horizon means the holding period did not exceed horizon_days.
Realized reward-to-risk = (exit - entry) / (entry - stop). Rates and
returns 4 dp. This measures process against the plan, not skill.

When ``prices`` supplies ascending daily closes, each entry also gets, over
the window from its entry date to its exit (open entries: ``as_of``):
mfe_pct / mae_pct — the best and worst close relative to the entry price
(longs: max/min close/entry - 1; shorts mirrored so favorable is positive
and adverse negative), and touch_order — whether a close reached the target
before any close touched the stop ("target first" / "stop first" /
"neither"). Both are null when no closes cover the window. An entry whose
``revisions`` changed the stop and whose exit was "stopped" (against the
amended stop, not the original plan) is flagged STOP_DRIFTED; the row echoes
original_stop, the stop before the first stop revision, else null. Entries
without revisions are unamended.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MATCH_WINDOW_DAYS = 7
_LOW_RR = 1.5


def _r4(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


def _num(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise TypeError(f"{field} must be numeric")
    return float(v)


def _date(raw: object, field: str) -> date:
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    return date.fromisoformat(raw)


def _planned_rr(side: str, entry: float, target: float | None, stop: float | None) -> float | None:
    if target is None or stop is None:
        return None
    reward = (target - entry) if side == "long" else (entry - target)
    risk = (entry - stop) if side == "long" else (stop - entry)
    return reward / risk if risk > 0 else None


def _classify(side: str, price: float, target: float | None, stop: float | None) -> str:
    if side == "long":
        if target is not None and price >= target:
            return "target hit"
        if stop is not None and price <= stop:
            return "stopped"
    else:
        if target is not None and price <= target:
            return "target hit"
        if stop is not None and price >= stop:
            return "stopped"
    return "discretionary"


def _revisions(entry: dict) -> tuple[bool, float | None]:
    """(a revision changed the stop, the stop before the first stop revision)."""
    raw = entry.get("revisions")
    for rev in raw if isinstance(raw, list) else []:
        changes = rev.get("changes") if isinstance(rev, dict) else None
        if not isinstance(changes, dict) or "stop" not in changes:
            continue
        original = None
        val = changes["stop"]
        if isinstance(val, dict):
            try:
                original = _num(val.get("from"), "revisions stop from")
            except (TypeError, ValueError):
                original = None
        return True, original
    return False, None


def _window(prices: dict, sym: str, start: date, end: date) -> list[tuple[date, float]]:
    return [p for p in prices.get(sym, ()) if start <= p[0] <= end]


def run_journalreview(params: dict) -> dict:
    """Review the journal in ``params``; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    raw_entries = params.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("at least one journal entry is required")
    trips_in = params.get("round_trips") if params.get("round_trips") is not None else []
    if not isinstance(trips_in, list):
        raise ValueError("round_trips must be a list")
    prices_in = params.get("prices") if params.get("prices") is not None else {}
    if not isinstance(prices_in, dict):
        raise ValueError("prices must be an object")
    prices: dict[str, list[tuple[date, float]]] = {}
    for sym, series in prices_in.items():
        pts = []
        for p in series if isinstance(series, list) else []:
            if not isinstance(p, dict) or p.get("date") is None or p.get("close") is None:
                continue
            try:
                pts.append((_date(p["date"], "prices date"), float(p["close"])))
            except (TypeError, ValueError):
                continue
        if pts:
            pts.sort(key=lambda x: x[0])
            prices[str(sym).upper()] = pts
    as_of = _date(params["as_of"], "as_of") if params.get("as_of") else date.today()

    trips = []
    for t in trips_in:
        if (
            isinstance(t, dict)
            and t.get("symbol")
            and t.get("first_buy_date")
            and t.get("sell_date")
        ):
            trips.append(
                {
                    **t,
                    "_first": _date(t["first_buy_date"], "first_buy_date"),
                    "_sell": _date(t["sell_date"], "sell_date"),
                    "_used": False,
                }
            )

    rows = []
    missing_levels = []
    for e in raw_entries:
        if (
            not isinstance(e, dict)
            or not e.get("id")
            or not e.get("date")
            or not e.get("symbol")
            or e.get("entry_price") is None
        ):
            raise ValueError("each entry requires id, date, symbol and entry_price")
        eid, sym = str(e["id"]), str(e["symbol"]).upper()
        d = _date(e["date"], "entry date")
        side = str(e.get("side") or "long").lower()
        entry, target, stop = (
            _num(e["entry_price"], "entry_price"),
            _num(e.get("target"), "target"),
            _num(e.get("stop"), "stop"),
        )
        horizon = _num(e.get("horizon_days"), "horizon_days")
        planned = _planned_rr(side, entry, target, stop)
        if target is None or stop is None:
            missing_levels.append(f"{eid} ({sym})")
        # match a ledger round trip
        match = None
        candidates = [
            t
            for t in trips
            if not t["_used"]
            and str(t["symbol"]).upper() == sym
            and abs((t["_first"] - d).days) <= _MATCH_WINDOW_DAYS
            and t["_sell"] >= d
        ]
        if candidates:
            match = min(candidates, key=lambda t: t["_sell"])
            match["_used"] = True
        closed = e.get("closed") if isinstance(e.get("closed"), dict) else None
        stop_revised, original_stop = _revisions(e)
        row: dict = {
            "id": eid,
            "date": d.isoformat(),
            "symbol": sym,
            "side": side,
            "conviction": e.get("conviction"),
            "tags": list(e.get("tags") or []),
            "planned_rr": _r4(planned),
            "matched": match is not None,
            "source": None,
            "round_trip": None,
            "exit": "open",
            "exit_price": None,
            "realized_return": None,
            "realized_rr": None,
            "holding_days": None,
            "days_open": None,
            "plan_consistent": None,
            "within_horizon": None,
            "mfe_pct": None,
            "mae_pct": None,
            "touch_order": None,
            "stop_drifted": False,
            "original_stop": None if original_stop is None else _r4(original_stop),
        }
        end = as_of
        if match is not None:
            end = match["_sell"]
            price = _num(match.get("sell_price"), "sell_price")
            hold = (match["_sell"] - match["_first"]).days
            ret = _num(match.get("total_return"), "total_return")
            if ret is None and price is not None:
                ret = price / entry - 1 if side == "long" else entry / price - 1
            row.update(
                {
                    "source": "ledger",
                    "round_trip": {
                        "first_buy_date": match["first_buy_date"],
                        "sell_date": match["sell_date"],
                        "sell_price": _r4(price),
                        "total_return": _r4(ret),
                        "holding_days": hold,
                    },
                    "exit_price": _r4(price),
                    "realized_return": _r4(ret),
                    "holding_days": hold,
                }
            )
        elif (
            str(e.get("status") or "").lower() == "closed"
            and closed
            and closed.get("price") is not None
        ):
            price = _num(closed["price"], "closed.price")
            close_date = _date(closed["date"], "closed.date") if closed.get("date") else as_of
            end = close_date
            ret = price / entry - 1 if side == "long" else entry / price - 1
            row.update(
                {
                    "source": "journal",
                    "exit_price": _r4(price),
                    "realized_return": _r4(ret),
                    "holding_days": (close_date - d).days,
                }
            )
        if row["exit_price"] is not None:
            price = row["exit_price"]
            row["exit"] = _classify(side, price, target, stop)
            risk = (
                (entry - stop)
                if side == "long" and stop is not None
                else (stop - entry)
                if stop is not None
                else None
            )
            gain = (price - entry) if side == "long" else (entry - price)
            row["realized_rr"] = _r4(gain / risk) if risk else None
            row["plan_consistent"] = row["exit"] in ("target hit", "stopped")
            row["within_horizon"] = (
                (row["holding_days"] <= horizon) if horizon is not None else None
            )
        else:
            row["days_open"] = (as_of - d).days
        window = _window(prices, sym, d, end)
        if window and entry != 0:
            ratios = [close / entry for _, close in window]
            if side == "long":
                mfe, mae = max(ratios) - 1, min(ratios) - 1
            else:
                mfe, mae = 1 - min(ratios), 1 - max(ratios)
            row["mfe_pct"], row["mae_pct"] = _r4(mfe), _r4(mae)
        if target is not None and stop is not None and window:
            tgt = stp = None
            for pt_date, close in window:
                if tgt is None and (close >= target if side == "long" else close <= target):
                    tgt = pt_date
                if stp is None and (close <= stop if side == "long" else close >= stop):
                    stp = pt_date
                if tgt is not None and stp is not None:
                    break
            row["touch_order"] = (
                "target first"
                if (stp is None and tgt is not None) or (tgt is not None and tgt < stp)
                else "stop first"
                if (tgt is None and stp is not None) or (stp is not None and stp < tgt)
                else "neither"
            )
        row["stop_drifted"] = bool(stop_revised and row["exit"] == "stopped")
        rows.append(row)

    closed_rows = [r for r in rows if r["exit"] != "open"]
    open_rows = [r for r in rows if r["exit"] == "open"]
    consistent = [r for r in closed_rows if r["plan_consistent"] is not None]
    horizon_known = [r for r in closed_rows if r["within_horizon"] is not None]
    planned = [r["planned_rr"] for r in rows if r["planned_rr"] is not None]
    returns = [r["realized_return"] for r in closed_rows if r["realized_return"] is not None]
    exits: dict[str, int] = {}
    for r in rows:
        exits[r["exit"]] = exits.get(r["exit"], 0) + 1
    summary = {
        "entries": len(rows),
        "open": len(open_rows),
        "closed": len(closed_rows),
        "matched_to_ledger": sum(1 for r in rows if r["matched"]),
        "plan_consistent_rate": _r4(
            sum(1 for r in consistent if r["plan_consistent"]) / len(consistent)
        )
        if consistent
        else None,
        "within_horizon_rate": _r4(
            sum(1 for r in horizon_known if r["within_horizon"]) / len(horizon_known)
        )
        if horizon_known
        else None,
        "avg_planned_rr": _r4(sum(planned) / len(planned)) if planned else None,
        "win_rate": _r4(sum(1 for x in returns if x > 0) / len(returns)) if returns else None,
        "avg_realized_return": _r4(sum(returns) / len(returns)) if returns else None,
        "exits": exits,
    }

    def breakdown(key_fn, label: str) -> list[dict]:
        groups: dict = {}
        for r in closed_rows:
            if r["realized_return"] is None:
                continue
            for k in key_fn(r):
                groups.setdefault(k, []).append(r["realized_return"])
        out = []
        for k in sorted(groups, key=lambda x: (str(type(x)), x)):
            vals = groups[k]
            out.append(
                {
                    label: k,
                    "closed": len(vals),
                    "win_rate": _r4(sum(1 for v in vals if v > 0) / len(vals)),
                    "avg_return": _r4(sum(vals) / len(vals)),
                }
            )
        return out

    by_conviction = breakdown(
        lambda r: [r["conviction"]] if r["conviction"] is not None else [], "conviction"
    )
    by_tag = breakdown(lambda r: r["tags"], "tag")

    flags: list[dict] = []
    overstayed = [r["id"] for r in closed_rows if r["within_horizon"] is False]
    if overstayed:
        flags.append(
            {
                "code": "OVERSTAYED",
                "message": "held past the planned horizon: " + ", ".join(overstayed),
            }
        )
    stale = [
        r["id"]
        for r in open_rows
        if r["days_open"] is not None
        and any(
            e.get("id") == r["id"]
            and e.get("horizon_days")
            and r["days_open"] > float(e["horizon_days"])
            for e in raw_entries
        )
    ]
    if stale:
        flags.append(
            {
                "code": "STALE_OPEN",
                "message": "open past the planned horizon (close or re-journal): "
                + ", ".join(stale),
            }
        )
    if summary["avg_planned_rr"] is not None and summary["avg_planned_rr"] < _LOW_RR:
        flags.append(
            {
                "code": "LOW_PLANNED_RR",
                "message": f"average planned reward-to-risk is {summary['avg_planned_rr']} "
                f"(below {_LOW_RR}): plans risk more than they aim to make",
            }
        )
    if missing_levels:
        flags.append(
            {
                "code": "MISSING_LEVELS",
                "message": "entries without target or stop: " + ", ".join(missing_levels),
            }
        )
    drifted = [r for r in rows if r["stop_drifted"]]
    for r in drifted:
        flags.append(
            {
                "code": "STOP_DRIFTED",
                "message": f"{r['id']} ({r['symbol']}): the stop was revised and the exit "
                "honoured the revised stop",
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "entries": rows,
        "summary": summary,
        "by_conviction": by_conviction,
        "by_tag": by_tag,
        "flags": flags,
    }


def main() -> None:
    """Read JSON params from stdin, write the review (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_journalreview(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
