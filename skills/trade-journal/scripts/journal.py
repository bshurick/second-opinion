#!/usr/bin/env python3
"""Usage: journal.py add SYMBOL --entry P --thesis TEXT [--side long|short] [--target P] [--stop P] [--invalidation TEXT] [--add-at P [--add-qty N]] [--horizon DAYS] [--conviction 1-5] [--tag T ...] [--size N] [--date YYYY-MM-DD]
       journal.py list [--status open|closed] [--symbol SYM]
       journal.py amend ID [--target P] [--stop P] [--invalidation TEXT] [--add-at P] [--add-qty N] [--thesis TEXT] [--size N]
       journal.py close ID --price P [--date YYYY-MM-DD] [--notes TEXT]
       journal.py review [--as-of YYYY-MM-DD]

Pre-trade journal kept in ``journal.json`` under the plugin data dir. ``add``
records the thesis and plan (entry, target, stop, horizon, conviction, tags)
and prints the entry with its planned reward-to-risk; ``list`` filters;
``amend`` changes the plan of an open entry (at least one of --target, --stop,
--invalidation, --add-at, --add-qty, --thesis, --size; a repeated value is
rejected) and appends the change to the entry's ``revisions`` audit array as
{"at": ISO timestamp now, "changes": {field: {"from": old, "to": new}}} --
never hand-edit journal.json; ``close`` records the exit; ``review`` matches
entries to the ledger's round trips (built with the trade-review skill's
review.py when ``ledger.json`` exists), fetches Yahoo close history and live
quotes for open entries, and runs journalreview.py: exit classification
against the plan, MFE/MAE and touch order, adherence rates, breakdowns by
conviction and tag, and for open entries the live unrealized R-multiple
(live_rr), live_price and days_left_in_horizon. Flags include SIZE_MISMATCH
when a recorded size disagrees with the matched round trip by more than one
unit or 1%.

Thesis-based invalidation: ``--invalidation TEXT`` stores the condition that
would prove the thesis wrong as ``invalidation`` (a plan may carry it instead
of, or alongside, a price stop; the trading skill's gate treats an entry with
an invalidation but no stop as REVIEW rather than NO_GO). Planned adds:
``--add-at P`` (with optional ``--add-qty N``) stores ``add_rule`` as
{"price": P, "qty": N|null}; the add price must be below the entry for a
long and above it for a short. When ``--add-at`` is given and the watchlist
skill is installed, a watchlist price rule for the symbol is created or
replaced (``price_below`` for a long, ``price_above`` for a short; the
watchlist note references the journal id) and echoed as ``watchlist_rule``;
a failing watchlist step never fails the journal write and is reported as
``watchlist_error``. stdin is unused. Exit codes: 0, 2, 5 (LEDGER_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "trade-review" / "scripts"))

import journalreview  # noqa: E402
from second_opinion import brokerage, ledger, market, output  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

JOURNAL_FILE = "journal.json"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"journal.py: {message}")


def journal_path() -> Path:
    return ledger.ledger_path().parent / JOURNAL_FILE


def load_journal() -> dict:
    path = journal_path()
    if not path.is_file():
        return {"entries": []}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise ApiError(f"journal at {path} is not valid JSON", code="LEDGER_CORRUPT", hint=f"move or delete {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ApiError(f"journal at {path} has an unexpected shape", code="LEDGER_CORRUPT", hint=f"move or delete {path}")
    return data


def save_journal(book: dict) -> Path:
    path = journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1))
    return path


def _iso(raw: str | None, flag: str) -> str:
    if raw is None:
        return date.today().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise InvalidInput(f"{flag} must be YYYY-MM-DD") from exc


def _clean_text(raw: str | None, flag: str) -> str | None:
    if raw is None:
        return None
    if not raw.strip():
        raise InvalidInput(f"{flag} cannot be empty")
    return raw.strip()


def _add_rule(side: str, entry: float, add_at: float | None, add_qty: float | None, current: dict | None = None) -> dict | None:
    """The planned add rule after applying --add-at / --add-qty on top of ``current`` (validated)."""
    if add_at is None and add_qty is None:
        return current
    if add_at is None:
        if not current or current.get("price") is None:
            raise InvalidInput("--add-qty needs --add-at (the entry has no planned add price)")
        add_at = float(current["price"])
    if not add_at > 0:
        raise InvalidInput("--add-at must be above zero")
    if side == "long" and not add_at < entry:
        raise InvalidInput("--add-at must be below the entry for a long (a planned add on weakness)")
    if side == "short" and not add_at > entry:
        raise InvalidInput("--add-at must be above the entry for a short (a planned add on strength)")
    if add_qty is None and current:
        add_qty = current.get("qty")  # a moved add price keeps its planned quantity
    if add_qty is not None and not add_qty > 0:
        raise InvalidInput("--add-qty must be above zero")
    return {"price": float(add_at), "qty": None if add_qty is None else float(add_qty)}


def _sync_watchlist(entry_row: dict) -> dict:
    """Create or replace the watchlist price rule for a planned add. Never raises."""
    rule = entry_row.get("add_rule") or {}
    if rule.get("price") is None:
        return {}
    watchlist_dir = _HERE.parents[1] / "watchlist" / "scripts"
    if not (watchlist_dir / "watchlist.py").is_file():
        return {"watchlist_error": "watchlist skill not installed; add the price rule by hand with watchlist.py add"}
    try:
        if str(watchlist_dir) not in sys.path:
            sys.path.insert(0, str(watchlist_dir))
        import watchlist  # noqa: PLC0415 — optional sibling skill

        rule_type = "price_below" if entry_row.get("side") == "long" else "price_above"
        qty = rule.get("qty")
        note = f"journal {entry_row['id']}: planned add at {float(rule['price']):g}" + (f" for {float(qty):g}" if qty is not None else "")
        saved = watchlist.upsert_rule(entry_row["symbol"], rule_type, float(rule["price"]), note=note, added_price=entry_row.get("entry_price"))
        return {"watchlist_rule": {"symbol": entry_row["symbol"], "type": rule_type, "value": float(rule["price"]), "note": note, "watchlist_path": saved["watchlist_path"]}}
    except Exception as exc:  # noqa: BLE001 — the journal write already succeeded
        return {"watchlist_error": f"{exc.__class__.__name__}: {exc}"}


def _add(ns: argparse.Namespace) -> dict:
    if not ns.thesis or not ns.thesis.strip():
        raise InvalidInput("--thesis is required: write why this trade, in one or two sentences")
    symbol = brokerage.validate_symbol(ns.symbol)
    side = ns.side.lower()
    if side not in ("long", "short"):
        raise InvalidInput("--side must be long or short")
    entry, target, stop = ns.entry, ns.target, ns.stop
    if target is not None and stop is not None:
        if side == "long" and not (target > entry > stop):
            raise InvalidInput("target must be above the entry and the stop below it for a long")
        if side == "short" and not (target < entry < stop):
            raise InvalidInput("target must be below the entry and the stop above it for a short")
    if ns.conviction is not None and not 1 <= ns.conviction <= 5:
        raise InvalidInput("--conviction must be between 1 and 5")
    invalidation = _clean_text(ns.invalidation, "--invalidation")
    add_rule = _add_rule(side, float(entry), ns.add_at, ns.add_qty)
    when = _iso(ns.date, "--date")
    book = load_journal()
    seq = sum(1 for e in book["entries"] if e.get("date") == when and e.get("symbol") == symbol) + 1
    entry_row = {
        "id": f"j-{when}-{symbol.lower()}-{seq}", "date": when, "symbol": symbol, "side": side, "thesis": ns.thesis.strip(),
        "entry_price": entry, "target": target, "stop": stop, "invalidation": invalidation, "add_rule": add_rule,
        "horizon_days": ns.horizon, "conviction": ns.conviction,
        "tags": sorted({t.strip().lower() for t in ns.tag if t.strip()}), "size": ns.size, "status": "open", "closed": None,
    }
    book["entries"].append(entry_row)
    path = save_journal(book)
    rr = journalreview._planned_rr(side, float(entry), target, stop)  # noqa: SLF001
    out = {"added": {**entry_row, "planned_rr": round(rr, 4) if rr is not None else None}, "journal_path": str(path), "count": len(book["entries"])}
    if ns.add_at is not None:
        out.update(_sync_watchlist(entry_row))
    return out


def _list(ns: argparse.Namespace) -> dict:
    book = load_journal()
    rows = book["entries"]
    if ns.status:
        rows = [e for e in rows if e.get("status") == ns.status]
    if ns.symbol:
        rows = [e for e in rows if e.get("symbol") == ns.symbol.upper()]
    return {"journal_path": str(journal_path()), "count": len(rows), "entries": rows}


def _amend(ns: argparse.Namespace) -> dict:
    given = [
        name
        for name, val in (
            ("--target", ns.target), ("--stop", ns.stop), ("--invalidation", ns.invalidation), ("--add-at", ns.add_at),
            ("--add-qty", ns.add_qty), ("--thesis", ns.thesis), ("--size", ns.size),
        )
        if val is not None
    ]
    if not given:
        raise InvalidInput("amend needs at least one of --target, --stop, --invalidation, --add-at, --add-qty, --thesis, --size")
    book = load_journal()
    entry = next((e for e in book["entries"] if e.get("id") == ns.id), None)
    if entry is None:
        raise InvalidInput(f"no journal entry with id {ns.id!r}; run journal.py list")
    if str(entry.get("status") or "open").lower() != "open":
        raise InvalidInput("only open entries can be amended; closed entries are history")
    side = str(entry.get("side") or "long").lower()
    entry_p = float(entry["entry_price"])
    if ns.thesis is not None and not ns.thesis.strip():
        raise InvalidInput("--thesis cannot be empty")
    target = ns.target if ns.target is not None else entry.get("target")
    stop = ns.stop if ns.stop is not None else entry.get("stop")
    if target is not None and stop is not None:
        if side == "long" and not (target > entry_p > stop):
            raise InvalidInput("target must be above the entry and the stop below it for a long")
        if side == "short" and not (target < entry_p < stop):
            raise InvalidInput("target must be below the entry and the stop above it for a short")
    elif ns.target is not None:
        if side == "long" and not target > entry_p:
            raise InvalidInput("--target must be above the entry for a long")
        if side == "short" and not target < entry_p:
            raise InvalidInput("--target must be below the entry for a short")
    elif ns.stop is not None:
        if side == "long" and not stop < entry_p:
            raise InvalidInput("--stop must be below the entry for a long")
        if side == "short" and not stop > entry_p:
            raise InvalidInput("--stop must be above the entry for a short")
    add_rule = _add_rule(side, entry_p, ns.add_at, ns.add_qty, entry.get("add_rule"))
    changes: dict = {}
    for field, new in (
        ("target", ns.target),
        ("stop", ns.stop),
        ("invalidation", _clean_text(ns.invalidation, "--invalidation")),
        ("add_rule", add_rule if (ns.add_at is not None or ns.add_qty is not None) else None),
        ("thesis", None if ns.thesis is None else ns.thesis.strip()),
        ("size", ns.size),
    ):
        if new is None:
            continue
        old = entry.get(field)
        old = float(old) if field in ("target", "stop", "size") and old is not None else old
        if old == new:
            continue
        changes[field] = {"from": old, "to": new}
        entry[field] = new
    if not changes:
        raise InvalidInput(f"nothing to amend: {', '.join(given)} already set")
    revision = {"at": datetime.now().isoformat(timespec="seconds"), "changes": changes}
    entry.setdefault("revisions", []).append(revision)
    path = save_journal(book)
    rr = journalreview._planned_rr(side, entry_p, target, stop)  # noqa: SLF001
    out = {
        "amended": {**entry, "planned_rr": round(rr, 4) if rr is not None else None},
        "revision": revision,
        "journal_path": str(path),
    }
    if ns.add_at is not None:
        out.update(_sync_watchlist(entry))
    return out


def _close(ns: argparse.Namespace) -> dict:
    book = load_journal()
    entry = next((e for e in book["entries"] if e.get("id") == ns.id), None)
    if entry is None:
        raise InvalidInput(f"no journal entry with id {ns.id!r}; run journal.py list")
    entry["status"] = "closed"
    entry["closed"] = {"date": _iso(ns.date, "--date"), "price": ns.price, "notes": ns.notes}
    save_journal(book)
    return {"closed": entry, "journal_path": str(journal_path())}


def _review(ns: argparse.Namespace) -> dict:
    book = load_journal()
    if not book["entries"]:
        raise InvalidInput("the journal is empty: record a plan with journal.py add SYMBOL --entry P --thesis TEXT ...")
    as_of = _iso(ns.as_of, "--as-of")
    trips: list = []
    ledger_src = None
    if ledger.ledger_path().is_file():
        rows = ledger.load()["transactions"]
        if rows:
            import review  # noqa: PLC0415 — trade-review's engine, only when a ledger exists

            trips = review.run_review({"as_of": as_of, "transactions": rows, "prices": {}})["round_trips"]
            ledger_src = str(ledger.ledger_path())
    symbols = sorted({str(e.get("symbol")).upper() for e in book["entries"]})
    prices: dict = {}
    starts = [str(e["date"]) for e in book["entries"] if e.get("date")]
    if symbols and starts:
        try:
            fetched = market.close_histories(symbols, min(starts))
            prices = {s: fetched.get(s, []) for s in symbols}
        except Exception:  # noqa: BLE001 — null MFE/MAE, not a failed run
            pass
    result = journalreview.run_journalreview(
        {"as_of": as_of, "entries": book["entries"], "round_trips": trips, "prices": prices}
    )
    by_id = {str(e.get("id")): e for e in book["entries"]}
    open_syms = sorted({r["symbol"] for r in result["entries"] if r["exit"] == "open"})
    quotes: dict = {}
    if open_syms:
        try:
            quotes = market.day_changes(open_syms)
        except Exception:  # noqa: BLE001 — live fields stay null on a quote outage
            pass
    trip_by_key = {
        (str(t.get("symbol") or "").upper(), t.get("first_buy_date"), t.get("sell_date")): t for t in trips
    }
    for r in result["entries"]:
        entry = by_id.get(str(r["id"]), {})
        if r["exit"] == "open":
            live = (quotes.get(r["symbol"]) or {}).get("price")
            entry_p, stop = float(entry.get("entry_price") or 0), entry.get("stop")
            r["live_price"] = round(float(live), 4) if live is not None else None
            if live is not None and stop is not None:
                risk = (entry_p - float(stop)) if r["side"] == "long" else (float(stop) - entry_p)
                gain = (float(live) - entry_p) if r["side"] == "long" else (entry_p - float(live))
                r["live_rr"] = round(gain / risk, 4) if risk else None
            else:
                r["live_rr"] = None
            horizon = entry.get("horizon_days")
            r["days_left_in_horizon"] = (
                max(0, int(horizon) - r["days_open"])
                if horizon and r["days_open"] is not None
                else None
            )
        size = entry.get("size")
        if r["matched"] and size is not None and r["round_trip"]:
            trip = trip_by_key.get(
                (r["symbol"], r["round_trip"]["first_buy_date"], r["round_trip"]["sell_date"])
            )
            units = trip.get("units") if trip else None
            if units is not None and abs(float(units) - float(size)) > max(1.0, 0.01 * abs(float(size))):
                result["flags"].append(
                    {
                        "code": "SIZE_MISMATCH",
                        "message": f"{r['id']} ({r['symbol']}): journal size {float(size):g} but the "
                        f"matched round trip traded {float(units):g} units",
                    }
                )
    return {"sources": {"journal": str(journal_path()), "ledger": ledger_src, "round_trips": len(trips)}, **result}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="journal.py", add_help=False)
        sub = p.add_subparsers(dest="command")
        a = sub.add_parser("add", add_help=False)
        a.add_argument("symbol")
        a.add_argument("--side", default="long")
        a.add_argument("--entry", type=float, required=True)
        a.add_argument("--target", type=float, default=None)
        a.add_argument("--stop", type=float, default=None)
        a.add_argument("--invalidation", default=None)
        a.add_argument("--add-at", dest="add_at", type=float, default=None)
        a.add_argument("--add-qty", dest="add_qty", type=float, default=None)
        a.add_argument("--horizon", type=int, default=None)
        a.add_argument("--conviction", type=int, default=None)
        a.add_argument("--tag", action="append", default=[])
        a.add_argument("--size", type=float, default=None)
        a.add_argument("--thesis", default=None)
        a.add_argument("--date", default=None)
        ls = sub.add_parser("list", add_help=False)
        ls.add_argument("--status", choices=["open", "closed"], default=None)
        ls.add_argument("--symbol", default=None)
        c = sub.add_parser("close", add_help=False)
        c.add_argument("id")
        c.add_argument("--price", type=float, required=True)
        c.add_argument("--date", default=None)
        c.add_argument("--notes", default=None)
        am = sub.add_parser("amend", add_help=False)
        am.add_argument("id")
        am.add_argument("--target", type=float, default=None)
        am.add_argument("--stop", type=float, default=None)
        am.add_argument("--invalidation", default=None)
        am.add_argument("--add-at", dest="add_at", type=float, default=None)
        am.add_argument("--add-qty", dest="add_qty", type=float, default=None)
        am.add_argument("--thesis", default=None)
        am.add_argument("--size", type=float, default=None)
        r = sub.add_parser("review", add_help=False)
        r.add_argument("--as-of", dest="as_of", default=None)
        ns = p.parse_args(args)
        if ns.command == "add":
            return _add(ns)
        if ns.command == "list":
            return _list(ns)
        if ns.command == "amend":
            return _amend(ns)
        if ns.command == "close":
            return _close(ns)
        if ns.command == "review":
            return _review(ns)
        raise InvalidInput("command must be add, list, amend, close, or review")

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
