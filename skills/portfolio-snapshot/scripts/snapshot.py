#!/usr/bin/env python3
"""Usage: snapshot.py [--account ACCOUNT_ID ...] [--events] [--no-quotes] [--no-news] [--save] [--compare] [--partial]

One canonical, read-only summary of every open connected account in a single
run: SnapTrade accounts (one call), then positions and balances (one call each
per account), then one batched Yahoo download for prices and day changes, one
batched Yahoo download for ~5-week close histories, and a cached sector lookup
that also supplies each symbol's quote type (Yahoo ``info`` call per symbol on
a cache miss). Everything is fed to summary.py, whose output contract this
script extends with:

  as_of    ISO timestamp of the run
  sources  {"holdings": the broker that served the accounts ("snaptrade",
            a direct broker's name, or "mixed"), "quotes": "yahoo"|"etrade"|
            "mixed", "sectors": "yahoo"|null, "events": "yahoo"|null}

--account    restrict to the given account id(s); unknown id -> exit 2
Output also carries ``price_history`` ({SYMBOL: [{date, close}]}, one year sampled weekly)
and ``profiles`` ({SYMBOL: {name, quote_type, category, country, sector, summary, website,
bucket}}) for the page's per-holding detail panel.
--no-news    skip the headlines for the day's movers (by default one Yahoo news call
             per mover, at most six symbols, three dated stories each from the last 7 days,
             under ``news``; ``sources.news`` is "yahoo"; a failure adds NEWS_UNAVAILABLE).
--events     also fetch next earnings / ex-dividend date per symbol (one Yahoo
             call per symbol, so slower)
--no-quotes  skip the Yahoo quote and history fetches; prices are the broker's
             last values and the 1w/1m change columns are omitted
--save       append a dated record to ``snapshots.json`` in the plugin data
             dir: {"as_of", "total_value", "cash", "symbols": {symbol:
             market_value}}, all values 2 dp
--compare    compare against the most recent saved snapshot taken strictly
             earlier than this run and add a top-level "comparison": {"since",
             "days", "total_value": {before, after, delta, delta_pct},
             "symbols": [{symbol, before, after, delta, delta_pct} sorted by
             |delta| desc, capped at 25 with "n_more"}; delta_pct is null when
             the "before" value is 0 or missing. With nothing earlier saved,
             "comparison" is null and a NO_SNAPSHOT flag is added. --save and
             --compare combine: the comparison is against the previous
             snapshot, then the new one is saved.

If Yahoo quotes fail the snapshot still succeeds on broker prices and adds a
QUOTES_UNAVAILABLE flag; if the close-history download fails the 1w/1m change
columns are simply omitted and a HISTORY_UNAVAILABLE flag is added. A corrupt
snapshots.json fails --save/--compare with exit 5 SNAPSHOTS_CORRUPT (the file
is only read when one of those flags is given). Exit codes: 0, 2, 4, 5
(NO_ACCOUNTS when nothing is connected, SNAPSHOTS_CORRUPT), 6.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import summary  # noqa: E402
from second_opinion import ledger, market, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

SNAPSHOTS_FILE = "snapshots.json"
_HISTORY_DAYS = 370  # one year: 1w/1m changes for summary.py and the per-holding price history
_COMPARE_CAP = 25


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"snapshot.py: {message}")


def _select_accounts(hub, accounts: list[dict], wanted: list[str] | None) -> list[dict]:
    if not wanted:
        return accounts
    known = {a["account_id"] for a in accounts}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise hub.unknown_account_error(unknown)
    keep = set(wanted)
    return [a for a in accounts if a["account_id"] in keep]


def _sample_history(rows: list[dict], step: int = 5) -> list[dict]:
    """Every ``step``-th close plus the last one, as {date, close}; keeps the page small."""
    pts = [r for r in rows if isinstance(r, dict) and r.get("date") and r.get("close") is not None]
    if not pts:
        return []
    keep = pts[::step]
    if keep[-1] is not pts[-1]:
        keep.append(pts[-1])
    return [{"date": str(r["date"])[:10], "close": round(float(r["close"]), 4)} for r in keep]


def _snapshots_path() -> Path:
    return ledger.ledger_path().parent / SNAPSHOTS_FILE


def _load_snapshots() -> dict:
    path = _snapshots_path()
    if not path.is_file():
        return {"snapshots": []}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ApiError(
            f"snapshots file at {path} is not valid JSON: {exc}",
            code="SNAPSHOTS_CORRUPT",
            hint=f"move or delete {path} and run snapshot.py --save again",
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("snapshots"), list):
        raise ApiError(
            f"snapshots file at {path} has an unexpected shape",
            code="SNAPSHOTS_CORRUPT",
            hint=f"move or delete {path} and run snapshot.py --save again",
        )
    return data


def _compare(result: dict, now: datetime) -> tuple[dict | None, list[dict]]:
    """Delta of the current run against the most recent strictly earlier snapshot."""
    prior = None
    as_of = result["as_of"]
    candidates = [
        r for r in _load_snapshots()["snapshots"] if isinstance(r, dict) and str(r.get("as_of") or "") < as_of
    ]
    if candidates:
        prior = max(candidates, key=lambda r: str(r.get("as_of") or ""))
    if prior is None:
        return None, [{"code": "NO_SNAPSHOT", "message": "no earlier saved snapshot; run snapshot.py --save to store one"}]

    old_total = round(float(prior.get("total_value") or 0), 2)
    new_total = result["totals"]["total_value"]
    delta = round((new_total or 0) - old_total, 2)
    old_as_of = str(prior.get("as_of") or "")
    try:
        days = (now - datetime.fromisoformat(old_as_of)).days
    except ValueError:
        days = None
    old_symbols = prior.get("symbols") if isinstance(prior.get("symbols"), dict) else {}
    new_symbols = {
        p["symbol"]: p["market_value"] for p in result["positions"] if p["market_value"] is not None
    }

    rows = []
    for symbol in sorted(set(old_symbols) | set(new_symbols)):
        before = old_symbols.get(symbol)
        before = round(float(before), 2) if before is not None else None
        after = new_symbols.get(symbol)
        if before is None and after is None:
            continue
        d = round((after or 0) - (before or 0), 2)
        rows.append(
            {
                "symbol": symbol,
                "before": before,
                "after": after,
                "delta": d,
                "delta_pct": round(d / before, 4) if before else None,
            }
        )
    rows.sort(key=lambda r: (-abs(r["delta"]), r["symbol"]))
    return (
        {
            "since": old_as_of,
            "days": days,
            "total_value": {
                "before": old_total,
                "after": new_total,
                "delta": delta,
                "delta_pct": round(delta / old_total, 4) if old_total else None,
            },
            "symbols": rows[:_COMPARE_CAP],
            "n_more": max(0, len(rows) - _COMPARE_CAP),
        },
        [],
    )


def _save(result: dict) -> None:
    book = _load_snapshots()
    book["snapshots"].append(
        {
            "as_of": result["as_of"],
            "total_value": result["totals"]["total_value"],
            "cash": result["totals"]["cash"],
            "symbols": {
                p["symbol"]: p["market_value"] for p in result["positions"] if p["market_value"] is not None
            },
        }
    )
    path = _snapshots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1))


def _lacks_sector_data(info: dict) -> bool:
    """Eligible for look-through proxying: no quote type at all (a 401(k) institutional share
    class), or a plain EQUITY Yahoo gave no sector for and no fund_sectors for either (e.g. SPYM,
    whose funds_data raises "No Fund data found" -- an S&P 500 index ETF Yahoo cannot describe as
    either a stock or a fund). A position with a real sector, or its own fund_sectors, is never a
    candidate."""
    if info.get("fund_sectors") is not None:
        return False
    qt = info.get("quote_type")
    if qt is None:
        return True
    return str(qt).upper() == "EQUITY" and not info.get("sector")


def _apply_lookthrough_proxies(asset_info: dict) -> None:
    """For a holding Yahoo cannot describe with usable sector data (no quote type at all, or a
    plain EQUITY with no sector and no fund_sectors), match its name against
    ``summary.LOOKTHROUGH_PROXIES`` and borrow that retail ETF's sector look-through data,
    mutating ``asset_info`` in place, so the sector card does not drop it. Never proxies a holding
    that already has its own fund data or a real sector, and never proxies a symbol to itself
    (e.g. a real "BND" row that somehow has no quote type, or VOO's own "Vanguard S&P 500 ETF"
    entry). One batched ``market.sectors()`` call covers every distinct proxy actually needed."""
    needed: dict[str, str] = {}
    for sym, info in asset_info.items():
        if not _lacks_sector_data(info):
            continue
        proxy = summary.lookthrough_proxy_for(info.get("name"))
        if proxy and proxy != sym:
            needed[sym] = proxy
    if not needed:
        return
    proxy_data = market.sectors(sorted(set(needed.values())))
    for sym, proxy in needed.items():
        pdata = proxy_data.get(proxy) or {}
        asset_info[sym] = {
            **asset_info[sym],
            "fund_sectors": pdata.get("fund_sectors"),
            "fund_asset_classes": pdata.get("fund_asset_classes"),
            "proxy": proxy,
        }


def build(args: list[str]) -> dict:
    """The whole snapshot for the given CLI args; raises ScriptError subclasses the way main() reports them."""
    p = _Parser(prog="snapshot.py", add_help=False)
    p.add_argument("--account", action="append", default=None)
    p.add_argument("--partial", action="store_true")
    p.add_argument("--events", action="store_true")
    p.add_argument("--no-quotes", action="store_true")
    p.add_argument("--no-news", action="store_true")
    p.add_argument("--save", action="store_true")
    p.add_argument("--compare", action="store_true")
    ns = p.parse_args(args)

    hub = router.load()
    hub.partial = ns.partial
    accounts = hub.list_accounts()
    if not accounts:
        raise ApiError("no open brokerage accounts are connected; use the connect skill", code="NO_ACCOUNTS")
    accounts = _select_accounts(hub, accounts, ns.account)

    rows = []
    for a in accounts:
        aid = a["account_id"]
        rows.append(
            {
                "account_id": aid,
                "name": a.get("name"),
                "institution_name": a.get("institution_name"),
                "account_type": a.get("account_type", "cash"),
                "supports_trading": a.get("supports_trading"),
                "positions": hub.get_portfolio(aid)["positions"] or [],
                "balances": hub.get_balance(aid)["balances"] or [],
            }
        )
    symbols = summary.symbols_in(rows)

    sources = {"holdings": router.holdings_source(accounts), "quotes": "snaptrade", "sectors": None, "events": None, "news": None}
    extra_flags: list[dict] = []
    quotes: dict = {}
    history: dict = {}
    now = datetime.now(timezone.utc)
    if not ns.no_quotes and symbols:
        try:
            quotes = market.day_changes(symbols, hub=hub)
            sources["quotes"] = market.quote_sources(list(quotes.values())) or "yahoo"
        except Exception as e:  # noqa: BLE001 — a quote outage must not sink the snapshot
            extra_flags.append({"code": "QUOTES_UNAVAILABLE", "message": f"Yahoo quotes failed ({e}); prices are the broker's last values"})
        try:
            history = market.close_histories(symbols, (now - timedelta(days=_HISTORY_DAYS)).date().isoformat())
        except Exception as e:  # noqa: BLE001 — history is additive; omit it on failure
            extra_flags.append({"code": "HISTORY_UNAVAILABLE", "message": f"Yahoo price history failed ({e}); 1w/1m changes omitted"})

    sectors = None
    quote_types: dict = {}
    asset_info: dict = {}
    descriptions: dict[str, str] = {}
    for r in rows:
        for pos in r["positions"]:
            if not isinstance(pos, dict):
                continue
            try:
                code, desc = summary._symbol_and_name(pos)  # noqa: SLF001 — shared parser
            except (ValueError, TypeError):
                continue
            if code and desc and desc.upper() != code:
                descriptions.setdefault(code, str(desc))
    if symbols:
        try:
            sector_info = market.sectors(symbols)
            sectors = {s: v.get("sector") for s, v in sector_info.items()}
            quote_types = {s: v.get("quote_type") for s, v in sector_info.items()}
            asset_info = {
                s: {**v, "name": v.get("name") or descriptions.get(s)} for s, v in sector_info.items()
            }
            sources["sectors"] = "yahoo"
        except Exception:  # noqa: BLE001 — quote_types degrade with sectors
            sectors = None
            quote_types = {}
            asset_info = {s: {"name": descriptions.get(s)} for s in symbols}
        else:
            try:
                _apply_lookthrough_proxies(asset_info)
            except Exception as e:  # noqa: BLE001 — additive: a proxy-fetch failure must not blank the base sector data already fetched above
                extra_flags.append(
                    {
                        "code": "PROXY_LOOKTHROUGH_UNAVAILABLE",
                        "message": f"look-through proxy fetch failed ({e}); institutional share classes keep their base sector data",
                    }
                )

    events = None
    if ns.events and symbols:
        events = {s: market.next_events(s) for s in symbols}
        sources["events"] = "yahoo"

    params: dict = {"accounts": rows, "quotes": quotes, "sectors": sectors, "events": events}
    if quote_types:
        params["quote_types"] = quote_types
    if asset_info:
        params["asset_info"] = asset_info
    if history:
        params["history"] = history
    result = summary.run_summary(params)
    news: dict | None = None
    if not ns.no_news:
        movers = result.get("movers") or {}
        mover_symbols = [m["symbol"] for m in (movers.get("up") or []) + (movers.get("down") or [])][:6]
        if mover_symbols:
            news = {}
            for sym in mover_symbols:
                try:
                    news[sym] = market.recent_news(sym)
                except Exception as e:  # noqa: BLE001 — headlines are additive; omit them on failure
                    extra_flags.append({"code": "NEWS_UNAVAILABLE", "message": f"Yahoo news failed for {sym} ({e})"})
                    news[sym] = []
            sources["news"] = "yahoo"
    result["news"] = news
    # per-holding detail for the page: a weekly-sampled one-year close series and a profile
    result["price_history"] = {
        s: _sample_history(rows_h) for s, rows_h in (history or {}).items() if rows_h
    }
    result["profiles"] = {
        s: {
            **{k: v.get(k) for k in ("name", "quote_type", "category", "country", "sector", "summary", "website")},
            "bucket": summary.asset_bucket(s, v),
        }
        for s, v in asset_info.items()
    } if asset_info else {}
    result["flags"].extend(extra_flags)
    result["flags"].extend(hub.unavailable_flags() + hub.duplicate_flags())
    out = {"as_of": now.isoformat(timespec="seconds"), "sources": sources, **result}

    if ns.compare:
        comparison, compare_flags = _compare(out, now)
        out["flags"].extend(compare_flags)
        out["comparison"] = comparison
    if ns.save:
        _save(out)
    return out


def main(argv: list[str] | None = None) -> int:
    return output.run(build, argv)


if __name__ == "__main__":
    sys.exit(main())
