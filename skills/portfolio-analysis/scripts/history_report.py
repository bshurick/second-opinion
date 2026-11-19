#!/usr/bin/env python3
"""Usage: history_report.py [--since YYYY-MM-DD] [--partial]

Daily portfolio value rebuilt from the ledger, chained into a time-weighted
return per account and combined, beside SPY, QQQ and DIA (history.py's output
contract) plus ``sources``. stdin is unused. Order of work: connected accounts
are listed through the router (E*Trade direct where logged in, SnapTrade
otherwise); each account is topped up with broker activity from 7 days before
its newest ledger row, so activity a broker posts late is still picked up, or
from two years back (the brokers' limit) when it has no rows yet (twin ids
folded onto the live id; ledger.merge drops exact
duplicates), normalized as sync-broker.py does, and the ledger is saved only
when at least one row was added; today's positions and cash are read as
snapshot.py and summary.py read them (a cash-like fund with no price counts at
$1.00 there too, as history.py values it); then ONE batched Yahoo download covers every symbol held
today, every ledger symbol in the window, the proxy ETFs of unlisted funds
(``proxies.lookthrough_proxy_for`` on the holding's name, or on the ledger
text of a fund no longer held) and the benchmarks,
from the oldest ledger date (or --since), plus one split lookup. When the
brokers return nothing and the ledger is empty it exits 0 with a LEDGER_EMPTY
flag naming the statement-import skill for older CSV history. A
failed split lookup continues without it (SPLITS_UNAVAILABLE; ledger SPLIT rows
still apply); a benchmark with no prices degrades to BENCHMARK_UNAVAILABLE.
This is a historical record, not advice. Exit codes: 0, 2, 4, 5, 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker: its accounts go to ``excluded`` with a BROKER_UNAVAILABLE
flag and are never drawn from a possibly stale ledger. Their SnapTrade twins
(matched by ``router.merge_accounts`` against the broker's rows cached in the
registry, or by an account_number equal to a direct id) are neither drawn nor
topped up. A SnapTrade row numbered as a live direct account id is folded onto
it. When a broker's activity can't be fetched for the top-up, that broker's
accounts are excluded the same way (BROKER_UNAVAILABLE), except that a login
error without --partial exits 4 as above.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "statement-import" / "scripts"))

import history  # noqa: E402
import normalize  # noqa: E402
import summary  # noqa: E402
from second_opinion import ledger, market, output  # noqa: E402
from second_opinion import proxies as proxy_lib  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, ConfigError, InvalidInput  # noqa: E402

BENCHMARKS = ["SPY", "QQQ", "DIA"]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"history_report.py: {message}")


def _iso(value: object) -> str:
    return str(value or "")[:10]


TOP_UP_OVERLAP_DAYS = 7  # re-fetch a week before the newest row: brokers post some activity late
FULL_HISTORY_DAYS = 729  # an account with no ledger rows gets the brokers' two-year limit, as sync-broker.py


def _broker(row: dict) -> str:
    return str(row.get("broker") or "snaptrade")


def _top_up(hub, accounts: list[dict], book: dict, aliases: dict[str, str], today: str, partial: bool) -> dict[str, str]:
    """Merge broker activity from a week before each account's newest ledger row, or the
    last two years for an account with no rows yet, into ``book`` (``ledger.merge``
    drops exact duplicates). Returns {broker: error message}
    for brokers whose activity could not be fetched; a login error without
    ``partial`` raises with the way to skip it."""
    live = {a["account_id"] for a in accounts}
    broker_of = {a["account_id"]: _broker(a) for a in accounts}
    failed: dict[str, str] = {}
    newest: dict[str, str] = {}
    for t in book["transactions"]:
        aid = aliases.get(str(t.get("account_id")), str(t.get("account_id")))
        if aid in live and _iso(t.get("date")) > newest.get(aid, ""):
            newest[aid] = _iso(t.get("date"))
    added_total = 0
    full_start = (date.fromisoformat(today) - timedelta(days=FULL_HISTORY_DAYS)).isoformat()
    for aid in sorted(live):
        if aid in newest:
            start = (date.fromisoformat(newest[aid]) - timedelta(days=TOP_UP_OVERLAP_DAYS)).isoformat()
        else:
            start = full_start
        if start > today or broker_of[aid] in failed:
            continue
        try:
            items = hub.list_transactions(aid, start=start, end=None, count=10**6)["transactions"]
        except (ConfigError, ApiError) as exc:
            if str(exc.code or "").endswith("_REAUTH") and not partial:
                raise ConfigError(str(exc), code=exc.code, **{**exc.extra, "partial": router.PARTIAL_FLAG}) from exc
            failed[broker_of[aid]] = str(exc)
            continue
        if not items:
            continue
        result = normalize.run_normalize({"source": "snaptrade", "account_id": aid, "rows": items})
        added, _ = ledger.merge(book, result["transactions"], source=f"snaptrade:{aid}")
        added_total += added
    if added_total:
        ledger.save(book)
    return failed


def _num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _priced_cash(pos: dict, symbol: str, name: str | None) -> dict:
    """The position as summary sees it: a cash-like fund with no price gets $1.00, as
    history.py values it, so summary backs it out of cash just the same."""
    item = {**pos, "symbol": symbol, "name": name}
    if pos.get("price") is None and proxy_lib.is_cash_like(symbol, name):
        item["price"] = 1.0
    return item


def _read_accounts(hub, rows: list[dict]) -> list[dict]:
    """Today's positions and settled cash per account, as snapshot.py reads them.

    summary.run_summary backs a money-market core fund the broker reports both as a
    position and inside cash out of cash (``cash``), so history.py, which values the
    fund at $1.00 a unit itself, does not count it twice. run_summary is strict, so it
    sees a filtered copy (symbol present, numeric units >= 0: a core fund is never
    short); history.py gets every position with a symbol and numeric units, shorts too."""
    read, seen = [], set()
    for r in rows:
        aid = r["account_id"]
        if aid in seen:
            continue
        seen.add(aid)
        positions = []
        for pos in hub.get_portfolio(aid)["positions"] or []:
            if not isinstance(pos, dict):
                continue
            try:
                symbol, name = summary._symbol_and_name(pos)
            except ValueError:
                continue
            if not _num(pos.get("units")):
                continue
            positions.append((pos, symbol, name))
        balances = [b for b in hub.get_balance(aid)["balances"] or [] if isinstance(b, dict) and _num(b.get("cash"))]
        read.append((r, positions, balances))
    if not read:
        return []
    raw = [
        {"account_id": r["account_id"], "name": r.get("name"), "account_type": r.get("account_type", "cash"),
         "balance_total": r.get("balance_total") if _num(r.get("balance_total")) else None,
         "positions": [_priced_cash(pos, symbol, name) for pos, symbol, name in positions
                       if pos["units"] >= 0 and (pos.get("price") is None or _num(pos.get("price")))],
         "balances": balances}
        for r, positions, balances in read
    ]
    try:
        settled = {a["account_id"]: a["cash"] for a in summary.run_summary({"accounts": raw})["accounts"]}
    except (ValueError, TypeError) as exc:
        raise InvalidInput(f"cannot read today's holdings: {exc}") from exc
    accounts = []
    for r, positions, _ in read:
        items = []
        for pos, symbol, name in positions:
            item = {"symbol": symbol, "units": float(pos["units"]), "name": name}
            if _num(pos.get("price")):
                item["price"] = float(pos["price"])
            items.append(item)
        accounts.append({"account_id": r["account_id"], "name": r.get("name") or r["account_id"],
                         "account_type": r.get("account_type"), "cash": float(settled[r["account_id"]]),
                         "positions": items})
    return accounts


def _unavailable_accounts(hub) -> list[dict]:
    """Cached accounts of brokers that could not be listed (registry rows by broker)."""
    failed = {e.get("broker") for e in getattr(hub, "broker_errors", []) or []}
    registry = getattr(hub, "registry", None)
    if not failed or registry is None:
        return []
    return [
        {"account_id": aid, "reason": f"{row.get('broker')} unavailable; not drawn from a possibly stale ledger"}
        for aid, row in sorted(registry.load().items())
        if isinstance(row, dict) and row.get("broker") in failed
    ]


def _twins(hub, rows: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """SnapTrade rows the router left listed that are another door to a direct account:
    ({twin: live direct id}, {twin: direct id of a broker that could not be listed}).

    With the direct broker down, ``router.merge_accounts`` has nothing to shadow
    against, so it is run again on that broker's rows cached in the registry. A
    SnapTrade ``account_number`` equal to a direct account id (E*Trade's accountIdKey,
    the router's ``_numbered_as`` reading) is a twin as well."""
    failed = {e.get("broker") for e in getattr(hub, "broker_errors", []) or []}
    registry = getattr(hub, "registry", None)
    cached = registry.load() if registry is not None and failed else {}
    down = {aid: row for aid, row in cached.items()
            if isinstance(row, dict) and row.get("broker") in failed and row.get("broker") != "snaptrade"}
    snap = [r for r in rows if _broker(r) == "snaptrade"]
    direct_live = {r["account_id"] for r in rows if _broker(r) != "snaptrade"}
    _, shadowed, _ = router.merge_accounts([{**row, "account_id": aid} for aid, row in down.items()], snap)
    to_down = {str(s["snaptrade_account_id"]): str(s["direct_account_id"]) for s in shadowed}
    to_live: dict[str, str] = {}
    for r in snap:
        number = str(r.get("account_number") or "").strip()
        if not number or number == r["account_id"] or r["account_id"] in to_down:
            continue
        if number in direct_live:
            to_live[r["account_id"]] = number
        elif number in down:
            to_down[r["account_id"]] = number
    return to_live, to_down


def build(ns: argparse.Namespace) -> dict:
    since = ns.since
    if since:
        try:
            date.fromisoformat(since)
        except ValueError as exc:
            raise InvalidInput(f"--since must be YYYY-MM-DD, got {since!r}") from exc
    today = date.today().isoformat()

    hub = router.load()
    hub.partial = ns.partial
    rows = hub.list_accounts()
    aliases = {str(s["snaptrade_account_id"]): str(s["direct_account_id"]) for s in hub.shadowed}
    to_live, to_down = _twins(hub, rows)
    aliases.update(to_live)
    skipped = _unavailable_accounts(hub)
    skipped_ids = {s["account_id"] for s in skipped} | set(to_down)
    rows = [r for r in rows if r["account_id"] not in to_live and r["account_id"] not in skipped_ids]

    book = ledger.load()
    failed = _top_up(hub, rows, book, aliases, today, ns.partial)
    flags: list[dict] = []
    for broker, message in sorted(failed.items()):
        flags.append({"code": "BROKER_UNAVAILABLE",
                      "message": f"{broker}: recent activity could not be fetched ({message}); its accounts are excluded from this run"})
        for r in rows:
            if _broker(r) == broker:
                skipped.append({"account_id": r["account_id"], "reason": f"{broker} unavailable; not drawn from a possibly stale ledger"})
                skipped_ids.add(r["account_id"])
    rows = [r for r in rows if r["account_id"] not in skipped_ids]
    accounts = _read_accounts(hub, rows)

    live = {a["account_id"] for a in accounts}
    txns = [
        t for t in book["transactions"]
        if str(t.get("account_id")) not in skipped_ids
        and aliases.get(str(t.get("account_id")), str(t.get("account_id"))) not in skipped_ids
        and (not since or _iso(t.get("date")) >= since)
    ]
    held = {p["symbol"] for a in accounts for p in a["positions"]}
    proxies: dict[str, str] = {}
    for a in accounts:
        for p in a["positions"]:
            proxy = proxy_lib.lookthrough_proxy_for(p.get("name"))
            if proxy:
                proxies[p["symbol"]] = proxy
    mine = [t for t in txns if aliases.get(str(t.get("account_id")), str(t.get("account_id"))) in live]
    for t in mine:  # a fund no longer held: its ledger text names it ("exchangeOut - SSGA LG CAP VALUE")
        symbol = str(t.get("symbol") or "").upper()
        if symbol and symbol not in proxies:
            proxy = proxy_lib.lookthrough_proxy_for(t.get("security_name")) or proxy_lib.lookthrough_proxy_for(t.get("description"))
            if proxy and proxy != symbol:
                proxies[symbol] = proxy
    window_start = min((_iso(t.get("date")) for t in mine), default=None)

    prices: dict = {}
    splits: dict = {}
    if window_start:
        symbols = sorted(held | {t["symbol"].upper() for t in mine if t.get("symbol")} | set(proxies.values()) | set(BENCHMARKS))
        try:
            prices = market.close_histories(symbols, start=window_start)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(f"price download failed: {exc}", code="API_ERROR") from exc
        try:
            splits = market.split_histories(symbols, start=window_start)
        except Exception as exc:  # noqa: BLE001 — ledger SPLIT rows still apply
            flags.append({"code": "SPLITS_UNAVAILABLE", "message": f"split lookup failed ({exc}); only ledger SPLIT rows were applied"})

    try:
        result = history.run_history({
            "as_of": today, "accounts": accounts, "transactions": txns, "prices": prices,
            "splits": splits, "proxies": proxies, "aliases": aliases, "benchmarks": BENCHMARKS,
        })
    except (ValueError, TypeError) as exc:
        raise InvalidInput(str(exc)) from exc

    for f in result["flags"]:
        if f["code"] == "LEDGER_EMPTY":
            f["message"] = ("the brokers returned no transactions for the last two years; for older history, "
                            "import statement CSVs with the statement-import skill")
    result["flags"] = [*result["flags"], *flags, *hub.unavailable_flags()]
    result["excluded"] = [*result["excluded"], *skipped]
    result["sources"] = {"flows": "ledger", "balances": router.holdings_source(rows), "prices": "yahoo" if prices else None}
    return result


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="history_report.py", add_help=False)
        p.add_argument("--since", default=None)
        p.add_argument("--partial", action="store_true")
        return build(p.parse_args(args))

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
