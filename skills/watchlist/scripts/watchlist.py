#!/usr/bin/env python3
"""Usage: watchlist.py add SYMBOL [--note TEXT] [--above P] [--below P] [--day-move R] [--from-added R] [--drawdown R] [--near-52w-high R] [--ma-cross {1,-1}] [--volume-spike M] [--added-price P] [--date YYYY-MM-DD]
       watchlist.py remove SYMBOL
       watchlist.py list
       watchlist.py check [--as-of YYYY-MM-DD] [--no-history] [--events]
       watchlist.py summary
       watchlist.py install-cron [--hour H] [--minute M]
       watchlist.py ack SYMBOL [RULE_TYPE]
       watchlist.py snooze SYMBOL DAYS

Watchlist with alert rules, kept in ``watchlist.json`` under the plugin data
dir. ``add`` creates or extends an entry (rules of the same type are
replaced; the price when added is fetched unless --added-price is given);
``check`` fetches ONE batched Yahoo quote and one batched year of closes with
volumes (52-week highs and the series the rules need; skip with --no-history)
and runs alerts.py; ``--events`` also fetches each symbol's next earnings and
ex-dividend date and flags earnings within 5 trading days (approximated as
7 calendar days). Rates are decimals (0.05 = 5%). stdin is unused.

Suppression state: each entry may carry ``last_fired`` (per rule, written by
``check``), ``acked`` (per rule, written by ``ack``) and ``snooze_until``
(written by ``snooze``). Every triggered rule in ``check`` gets a ``state``:
``new`` (remind), ``still`` (already reported today), ``acknowledged`` (acked
today) or ``snoozed`` (inside the snooze window). ``check`` counts every
triggered rule as before and adds ``summary.newly_triggered_symbols``; rules
in state ``new`` stamp ``last_fired`` with the check date. ``ack SYMBOL
[RULE_TYPE]`` stamps ``acked`` for one rule (or every rule of the entry) and
clears its fire stamp, so the rule alerts again on a later day. ``snooze
SYMBOL DAYS`` defers alerts for the entry until today + DAYS.

Last check: ``check`` also writes its full result (with ``as_of`` and a
``checked_at`` UTC timestamp) to ``watchlist-last-check.json`` in the data
dir. ``summary`` is the ONE command that prints plain text, not JSON (it is
meant for the plugin's SessionStart hook and for cron logs): the as_of date and its age
in days, the newly triggered rules, one line per symbol (price, day move,
change since added, distance from the 52-week high, rules still waiting),
events when the check fetched them, and flags; with no saved check it prints
one line saying so. Exit code 0 always. ``install-cron`` prints (JSON) the
crontab line for a weekday-morning ``check --events`` (default 09:37 local,
``--hour``/``--minute`` to change), pointing at this plugin's data dir and
Python; it changes NOTHING itself -- the user installs it. (The plugin's own
SessionStart hook already shows ``summary`` when a session opens.)
Exit codes: 0, 2, 5, 6.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import alerts  # noqa: E402
from second_opinion import brokerage, ledger, market, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

WATCHLIST_FILE = "watchlist.json"
LAST_CHECK_FILE = "watchlist-last-check.json"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"watchlist.py: {message}")


def watchlist_path() -> Path:
    return ledger.ledger_path().parent / WATCHLIST_FILE


def load() -> dict:
    path = watchlist_path()
    if not path.is_file():
        return {"watchlist": []}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise ApiError(f"watchlist at {path} is not valid JSON", code="LEDGER_CORRUPT", hint=f"move or delete {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("watchlist"), list):
        raise ApiError(f"watchlist at {path} has an unexpected shape", code="LEDGER_CORRUPT", hint=f"move or delete {path}")
    return data


def last_check_path() -> Path:
    return ledger.ledger_path().parent / LAST_CHECK_FILE


def upsert_rule(symbol: str, rule_type: str, value: float, note: str | None = None, added_price: float | None = None) -> dict:
    """Create the entry if needed and replace its rule of ``rule_type`` (used by the trade-journal's planned adds)."""
    symbol = brokerage.validate_symbol(symbol)
    if rule_type not in alerts._TYPES:
        raise InvalidInput(f"rule type must be one of: {', '.join(alerts._TYPES)}")
    book = load()
    entry = next((w for w in book["watchlist"] if w.get("symbol") == symbol), None)
    if entry is None:
        entry = {"symbol": symbol, "note": note, "added": date.today().isoformat(), "added_price": added_price, "rules": []}
        book["watchlist"].append(entry)
    elif note:
        entry["note"] = note
    entry["rules"] = [x for x in entry.get("rules") or [] if x.get("type") != rule_type] + [{"type": rule_type, "value": float(value)}]
    path = save(book)
    return {"entry": entry, "count": len(book["watchlist"]), "watchlist_path": str(path)}


def save(book: dict) -> Path:
    path = watchlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1))
    return path


def _add(ns: argparse.Namespace) -> dict:
    symbol = brokerage.validate_symbol(ns.symbol)
    rules = []
    if ns.below is not None:
        rules.append({"type": "price_below", "value": ns.below})
    if ns.day_move is not None:
        if ns.day_move <= 0:
            raise InvalidInput("--day-move must be positive (a decimal such as 0.05)")
        rules.append({"type": "day_move", "value": ns.day_move})
    if ns.from_added is not None:
        rules.append({"type": "from_added", "value": ns.from_added})
    if ns.above is not None:
        rules.append({"type": "price_above", "value": ns.above})
    if ns.drawdown is not None:
        if ns.drawdown <= 0:
            raise InvalidInput("--drawdown must be positive (a decimal such as 0.15)")
        rules.append({"type": "drawdown", "value": ns.drawdown})
    if ns.near_52w_high is not None:
        if ns.near_52w_high <= 0:
            raise InvalidInput("--near-52w-high must be positive (a decimal such as 0.05)")
        rules.append({"type": "near_52w_high", "value": ns.near_52w_high})
    if ns.ma_cross is not None:
        if ns.ma_cross not in (1, -1):
            raise InvalidInput("--ma-cross must be +1 (golden cross) or -1 (death cross)")
        rules.append({"type": "ma_cross", "value": ns.ma_cross})
    if ns.volume_spike is not None:
        if ns.volume_spike <= 0:
            raise InvalidInput("--volume-spike must be positive (a multiple such as 2.0)")
        rules.append({"type": "volume_spike", "value": ns.volume_spike})
    if not rules and not ns.note:
        raise InvalidInput(
            "at least one rule or --note is required (--above, --below, --day-move, "
            "--from-added, --drawdown, --near-52w-high, --ma-cross, --volume-spike)"
        )
    book = load()
    entry = next((w for w in book["watchlist"] if w.get("symbol") == symbol), None)
    if entry is None:
        when = ns.date or date.today().isoformat()
        added_price = ns.added_price
        if added_price is None:
            try:
                added_price = (market.day_changes([symbol], hub=router.try_load()).get(symbol) or {}).get("price")
            except Exception:  # noqa: BLE001 — the price when added is a convenience
                added_price = None
        entry = {"symbol": symbol, "note": ns.note, "added": when, "added_price": added_price, "rules": []}
        book["watchlist"].append(entry)
    elif ns.note:
        entry["note"] = ns.note
    if ns.added_price is not None:
        entry["added_price"] = ns.added_price
    for r in rules:
        entry["rules"] = [x for x in entry["rules"] if x.get("type") != r["type"]] + [r]
    path = save(book)
    return {"added": entry, "count": len(book["watchlist"]), "watchlist_path": str(path)}


def _remove(ns: argparse.Namespace) -> dict:
    symbol = brokerage.validate_symbol(ns.symbol)
    book = load()
    before = len(book["watchlist"])
    book["watchlist"] = [w for w in book["watchlist"] if w.get("symbol") != symbol]
    if len(book["watchlist"]) == before:
        raise InvalidInput(f"{symbol} is not on the watchlist")
    save(book)
    return {"removed": symbol, "count": len(book["watchlist"])}


def _find(book: dict, symbol: str) -> dict:
    entry = next((w for w in book["watchlist"] if w.get("symbol") == symbol), None)
    if entry is None:
        raise InvalidInput(f"{symbol} is not on the watchlist")
    return entry


def _ack(ns: argparse.Namespace) -> dict:
    symbol = brokerage.validate_symbol(ns.symbol)
    if ns.rule_type is not None and ns.rule_type not in alerts._TYPES:
        raise InvalidInput(f"rule type must be one of: {', '.join(alerts._TYPES)}")
    book = load()
    entry = _find(book, symbol)
    types = [ns.rule_type] if ns.rule_type else [r["type"] for r in entry.get("rules") or []]
    today = date.today().isoformat()
    acked = entry.setdefault("acked", {})
    for rule_type in types:
        acked[rule_type] = today
        (entry.get("last_fired") or {}).pop(rule_type, None)
    if entry.get("last_fired") is not None and not entry["last_fired"]:
        entry.pop("last_fired", None)
    path = save(book)
    return {"symbol": symbol, "acked": types, "entry": entry, "watchlist_path": str(path)}


def _snooze(ns: argparse.Namespace) -> dict:
    symbol = brokerage.validate_symbol(ns.symbol)
    if ns.days < 1:
        raise InvalidInput("DAYS must be at least 1")
    book = load()
    entry = _find(book, symbol)
    until = (date.today() + timedelta(days=ns.days)).isoformat()
    entry["snooze_until"] = until
    path = save(book)
    return {"symbol": symbol, "snooze_until": until, "watchlist_path": str(path)}


def _state(entry: dict, rule_type: str, as_of: str) -> str:
    """new / still / acknowledged / snoozed for one triggered rule (ISO dates compare as strings)."""
    if (entry.get("acked") or {}).get(rule_type, "") >= as_of:
        return "acknowledged"
    if (entry.get("snooze_until") or "") >= as_of:
        return "snoozed"
    if (entry.get("last_fired") or {}).get(rule_type) == as_of:
        return "still"
    return "new"


def _events(symbols: list[str], as_of: date) -> list[dict]:
    out: list[dict] = []
    horizon = (as_of + timedelta(days=7)).isoformat()
    for symbol in symbols:
        try:
            ev = market.next_events(symbol)
        except Exception:  # noqa: BLE001 — degrade per symbol, never fail the check
            ev = {}
        earnings, ex_div = ev.get("next_earnings"), ev.get("next_ex_dividend")
        if not earnings and not ex_div:
            continue
        out.append(
            {
                "symbol": symbol,
                "next_earnings": earnings,
                "next_ex_dividend": ex_div,
                "earnings_in_5_days": bool(earnings and earnings <= horizon),
            }
        )
    return out


def _check(ns: argparse.Namespace) -> dict:
    book = load()
    if not book["watchlist"]:
        raise InvalidInput("the watchlist is empty: run watchlist.py add SYMBOL --below P ... first")
    as_of = date.fromisoformat(ns.as_of) if ns.as_of else date.today()
    symbols = sorted({w["symbol"] for w in book["watchlist"]})
    hub = router.try_load()
    sources = {"watchlist": str(watchlist_path()), "quotes": None, "highs": None}
    quotes: dict = {}
    try:
        quotes = market.day_changes(symbols, hub=hub)
        sources["quotes"] = market.quote_sources(list(quotes.values())) or "yahoo"
    except Exception:  # noqa: BLE001 — rules that need a quote are skipped and flagged
        quotes = {}
    highs: dict = {}
    closes: dict = {}
    volumes: dict = {}
    if not ns.no_history:
        try:
            hist = market.close_histories(symbols, start=(as_of - timedelta(days=365)).isoformat())
            for symbol, rows in hist.items():
                if not rows:
                    continue
                # build closes and volumes from the SAME filtered rows so the two
                # series stay aligned (a row missing either field is dropped from both)
                usable = [p for p in rows if p.get("close") is not None and p.get("volume") is not None]
                if not usable:
                    continue
                prices = [p["close"] for p in usable]
                highs[symbol] = max(prices)
                closes[symbol] = prices
                volumes[symbol] = [p["volume"] for p in usable]
            sources["highs"] = "yahoo"
        except Exception:  # noqa: BLE001
            highs = {}
    result = alerts.run_alerts(
        {
            "as_of": as_of.isoformat(),
            "watchlist": book["watchlist"],
            "quotes": quotes,
            "highs_52w": highs,
            "closes": closes,
            "volumes": volumes,
        }
    )
    entries = {w.get("symbol"): w for w in book["watchlist"]}
    newly: set[str] = set()
    fired = False
    state_by: dict[tuple[str, str], str] = {}
    for row in result["watchlist"]:
        entry = entries.get(row["symbol"]) or {}
        for t in row["triggered"]:
            t["state"] = _state(entry, t["type"], as_of.isoformat())
            state_by[(row["symbol"], t["type"])] = t["state"]
            if t["state"] == "new":
                newly.add(row["symbol"])
                entry.setdefault("last_fired", {})[t["type"]] = as_of.isoformat()
                fired = True
    for item in result["triggered"]:
        item["state"] = state_by[(item["symbol"], item["type"])]
    result["summary"]["newly_triggered_symbols"] = len(newly)
    if fired:
        save(book)
    if ns.events:
        result["events"] = _events(symbols, as_of)
        sources["events"] = "yahoo"
    out = {"sources": sources, **result}
    try:
        last_check_path().write_text(json.dumps({**out, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=1))
    except OSError:  # noqa: S110 — the saved copy is a convenience for summary; the check itself succeeded
        pass
    return out


def _pct(value) -> str:
    return f"{100 * float(value):+.1f}%" if isinstance(value, (int, float)) else "n/a"


def summary_text(saved: dict | None, today: date | None = None) -> str:
    """Plain-text rendering of a saved check result (None = no check has run)."""
    if not saved:
        return "Watchlist: no check has run yet (run watchlist.py check)."
    today = today or date.today()
    as_of = str(saved.get("as_of") or "?")
    age = ""
    try:
        days = (today - date.fromisoformat(as_of)).days
        age = f" ({days}d old)" if days >= 1 else " (today)"
    except ValueError:
        pass
    lines = [f"Watchlist check as of {as_of}{age}:"]
    triggered = saved.get("triggered") or []
    new = [t for t in triggered if t.get("state") == "new"]
    other = [t for t in triggered if t.get("state") != "new"]
    if new:
        lines.extend(f"  ALERT {t.get('symbol')}: {t.get('message')}" for t in new)
    else:
        lines.append("  No new alerts.")
    if other:
        lines.append("  (" + "; ".join(f"{t.get('symbol')} {t.get('type')} {t.get('state')}" for t in other) + ")")
    for w in saved.get("watchlist") or []:
        waiting = ", ".join(f"{r.get('type')} {r.get('value')} (now {r.get('current')})" for r in w.get("untriggered") or [])
        lines.append(
            f"  {w.get('symbol')} {w.get('price')} day {_pct(w.get('day_change_pct'))}, since added {_pct(w.get('since_added_pct'))}, "
            f"from 52w high {_pct(w.get('from_52w_high'))}; waiting: {waiting or 'none'}"
        )
    for e in saved.get("events") or []:
        flag = " (within 5 trading days)" if e.get("earnings_in_5_days") else ""
        lines.append(f"  {e.get('symbol')} next earnings {e.get('next_earnings')}{flag}; next ex-dividend {e.get('next_ex_dividend')}")
    for f in saved.get("flags") or []:
        lines.append(f"  flag: {f.get('message')}")
    return "\n".join(lines)


def _summary() -> int:
    path = last_check_path()
    saved = None
    if path.is_file():
        try:
            saved = json.loads(path.read_text())
        except ValueError:
            print(f"Watchlist: the saved check at {path} is not valid JSON; run watchlist.py check again.")
            return 0
    print(summary_text(saved if isinstance(saved, dict) else None))
    return 0


def _install_cron(ns: argparse.Namespace) -> dict:
    if not 0 <= ns.hour <= 23:
        raise InvalidInput("--hour must be between 0 and 23")
    if not 0 <= ns.minute <= 59:
        raise InvalidInput("--minute must be between 0 and 59")
    data_dir = ledger.ledger_path().parent
    venv_py = data_dir / "venv" / "bin" / "python"
    python = os.environ.get("SNAPTRADE_PY") or (str(venv_py) if venv_py.is_file() else "python3")
    script = Path(__file__).resolve()
    log_dir = data_dir / "logs" / "watchlist"
    overridden = os.environ.get("SECOND_OPINION_DATA") or os.environ.get("FINANCE_ANALYST_DATA")
    env_prefix = f"SECOND_OPINION_DATA={shlex.quote(str(data_dir))} " if overridden else ""
    check_cmd = f"{env_prefix}{shlex.quote(python)} {shlex.quote(str(script))} check --events"
    crontab_line = f"{ns.minute} {ns.hour} * * 1-5 mkdir -p {shlex.quote(str(log_dir))} && {check_cmd} > {shlex.quote(str(log_dir / 'check.log'))} 2>&1"
    return {
        "schedule": f"weekdays at {ns.hour:02d}:{ns.minute:02d} local time",
        "python": python,
        "script": str(script),
        "data_dir": str(data_dir),
        "last_check_file": str(last_check_path()),
        "log_file": str(log_dir / "check.log"),
        "crontab_line": crontab_line,
        "instructions": [
            "Nothing was installed. To schedule the check: run `crontab -e` and paste crontab_line on its own line.",
            "The plugin already shows the latest result when a Claude Code session opens; no hook to add.",
            "The line points at this copy of the plugin: after a plugin update moves it, run install-cron again and replace the line.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="watchlist.py", add_help=False)
        sub = p.add_subparsers(dest="command")
        a = sub.add_parser("add", add_help=False)
        a.add_argument("symbol")
        a.add_argument("--note", default=None)
        a.add_argument("--above", type=float, default=None)
        a.add_argument("--below", type=float, default=None)
        a.add_argument("--day-move", dest="day_move", type=float, default=None)
        a.add_argument("--from-added", dest="from_added", type=float, default=None)
        a.add_argument("--drawdown", type=float, default=None)
        a.add_argument("--near-52w-high", dest="near_52w_high", type=float, default=None)
        a.add_argument("--ma-cross", dest="ma_cross", type=int, default=None)
        a.add_argument("--volume-spike", dest="volume_spike", type=float, default=None)
        a.add_argument("--added-price", dest="added_price", type=float, default=None)
        a.add_argument("--date", default=None)
        r = sub.add_parser("remove", add_help=False)
        r.add_argument("symbol")
        sub.add_parser("list", add_help=False)
        c = sub.add_parser("check", add_help=False)
        c.add_argument("--as-of", dest="as_of", default=None)
        c.add_argument("--no-history", action="store_true")
        c.add_argument("--events", action="store_true")
        sub.add_parser("summary", add_help=False)
        ic = sub.add_parser("install-cron", add_help=False)
        ic.add_argument("--hour", type=int, default=9)
        ic.add_argument("--minute", type=int, default=37)
        k = sub.add_parser("ack", add_help=False)
        k.add_argument("symbol")
        k.add_argument("rule_type", nargs="?", default=None)
        z = sub.add_parser("snooze", add_help=False)
        z.add_argument("symbol")
        z.add_argument("days", type=int)
        ns = p.parse_args(args)
        if ns.command == "add":
            return _add(ns)
        if ns.command == "remove":
            return _remove(ns)
        if ns.command == "list":
            book = load()
            return {"watchlist_path": str(watchlist_path()), "count": len(book["watchlist"]), "watchlist": book["watchlist"]}
        if ns.command == "check":
            return _check(ns)
        if ns.command == "summary":
            return _summary()  # plain text, exit 0 (see the docstring)
        if ns.command == "install-cron":
            return _install_cron(ns)
        if ns.command == "ack":
            return _ack(ns)
        if ns.command == "snooze":
            return _snooze(ns)
        raise InvalidInput("command must be add, remove, list, check, summary, install-cron, ack, or snooze")

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
