#!/usr/bin/env python3
"""Usage: dividends.py [--account ACCOUNT_ID ...] [--payout] [--yield-context] [--years N] [--as-of YYYY-MM-DD] [--partial]

Dividend income for every open connected account in one run: SnapTrade
accounts (one call) and positions (one call per account), then ONE batched
Yahoo download of dividend history, fed to income.py. A symbol with no dividends
in that history gets one quote, which sorts it into one of three groups: a money
market fund with a seven-day yield (E*Trade only, Yahoo's fund yields are
unreliable), a priced holding that pays nothing, or unknown income (no price
anywhere, a money market fund with no yield, or a failed quote). An unknown fund
whose name matches a tracking ETF earns that ETF's dividends scaled to its own
price (one more batched dividend download and one quote per ETF); a failed lookup
leaves it unknown. A cash placeholder such as FCASH is a non-payer. Output is income.py's contract (per-payer "safety" block included)
plus:

  sources  {"holdings": the broker that served the accounts ("snaptrade", a
            direct broker's name, or "mixed"), "dividends": "yahoo",
            "fundamentals": "yahoo"|null}

--account  restrict to the given account id(s); unknown id -> exit 2
--payout   also fetch payout ratio / trailing EPS per symbol (one Yahoo call
           per symbol, so slower) to power HIGH_PAYOUT / NEGATIVE_EARNINGS
--yield-context
           also pull ONE batched year of daily closes per payer (~370 days
           back) and add to each payer row: price_1y_change (last close vs
           the close on the first session at/after as_of - 365d), yield_1y_ago
           (TTM regular dividends as of ~1 year ago over that close) and
           yield_vs_1y_ago, all 4 dp with the same ~365-day window convention
           as income.py, plus a VALUE_TRAP_CAUTION flag per payer when the
           yield rose >= 1pp while the price fell >= 10%. A failed history
           download leaves the fields null and adds a YIELD_CONTEXT_UNAVAILABLE
           note instead of failing the run.
--years    years of dividend history to pull (default 5; growth_5y needs 6)
--as-of    pin the as-of date (default today); mainly for reproducible runs

Exit codes: 0, 2, 4, 5 (NO_ACCOUNTS when nothing is connected, API_ERROR when
Yahoo fails), 6. stdin is not read.

When a direct broker (E*Trade) only needs today's login, the script exits 4 with
code ETRADE_REAUTH, the login ``url`` and ``partial: "--partial"``; --partial runs
without that broker and adds a BROKER_UNAVAILABLE flag instead.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import income  # noqa: E402
from second_opinion import market, output, proxies  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

_YIELD_CONTEXT_DAYS = 370  # fetch a little more than the ~365d analysis window
_CASH_PLACEHOLDERS = {"FCASH", "CASH", "USD"}  # a broker's cash line, not a fund with a yield


def _closes(history: dict, symbol: str) -> list[tuple[date, float]]:
    """(date, close) pairs, oldest first, from a close_histories download."""
    out: list[tuple[date, float]] = []
    for row in history.get(symbol) or []:
        if not isinstance(row, dict) or not isinstance(row.get("close"), (int, float)) or isinstance(row.get("close"), bool):
            continue
        try:
            out.append((date.fromisoformat(str(row["date"])), float(row["close"])))
        except ValueError:
            continue
    return sorted(out)


def _yield_context(symbol: str, dividends: dict, history: dict, as_of: date) -> tuple[dict, list[dict]]:
    """1-year price/yield context for one payer; fields null when the close
    history is missing or too short to reach ~1 year back."""
    fields = {"price_1y_change": None, "yield_1y_ago": None, "yield_vs_1y_ago": None}
    closes = _closes(history, symbol)
    if len(closes) < 2:
        return fields, []
    base = next((c for d, c in closes if d >= as_of - timedelta(days=365)), None)
    if base is None or base <= 0:
        return fields, []
    last = closes[-1][1]
    change = last / base - 1
    hist = income._history(dividends.get(symbol) or [])  # noqa: SLF001
    regular, _ = income._split_specials(hist)  # noqa: SLF001
    ttm_now = sum(a for d, a in regular if as_of - timedelta(days=365) < d <= as_of)
    ttm_ago = sum(a for d, a in regular if as_of - timedelta(days=730) < d <= as_of - timedelta(days=365))
    ago_yield = ttm_ago / base
    vs = ttm_now / last - ago_yield if last > 0 else None
    fields = {
        "price_1y_change": round(change, 4),
        "yield_1y_ago": round(ago_yield, 4),
        "yield_vs_1y_ago": round(vs, 4) if vs is not None else None,
    }
    flags: list[dict] = []
    if vs is not None and vs >= 0.01 and change <= -0.10:
        flags.append(
            {
                "code": "VALUE_TRAP_CAUTION",
                "message": f"{symbol} yield rose {round(vs * 100, 2)}pp while price fell {round(-change * 100, 2)}%",
            }
        )
    return fields, flags


def _names(rows: list[dict]) -> dict[str, str]:
    """Each symbol's broker description; SnapTrade nests it, E*Trade has it on the position too."""
    names: dict[str, str] = {}
    for r in rows:
        for pos in r["positions"]:
            if not isinstance(pos, dict):
                continue
            node, found = pos.get("symbol"), pos.get("description")
            while isinstance(node, dict):
                found = node.get("description") or found
                node = node.get("symbol")
            if found:
                names.setdefault(income._symbol(pos), str(found))  # noqa: SLF001
    return names


def _one_quote(symbol: str, hub: object) -> dict:
    """One quote row; empty when the quote fails, so the caller reads it as no data."""
    try:
        rows = market.quote([symbol], hub=hub)
    except Exception:  # noqa: BLE001 — a failed quote means unknown income, never a failed run
        return {}
    return rows[0] if rows else {}


def _sort_no_history(symbols: list[str], dividends: dict, names: dict[str, str], hub: object) -> tuple[dict, list[str]]:
    """Quote each symbol with no dividends. Returns the money market yields and the unknown symbols."""
    money_market: dict[str, dict] = {}
    unknown: list[str] = []
    for sym in symbols:
        if dividends.get(sym) or sym in _CASH_PLACEHOLDERS:
            continue
        quote = _one_quote(sym, hub)
        seven_day = quote.get("seven_day_yield")
        if seven_day is not None:
            money_market[sym] = {"yield": float(seven_day) / 100, "source": quote.get("source")}
        elif quote.get("price") is None or quote.get("quote_type") == "MONEYMARKET" or proxies.is_cash_like(sym, names.get(sym)):
            unknown.append(sym)
    return money_market, unknown


def _lookthrough(unknown: list[str], names: dict[str, str], hub: object, years: int) -> dict[str, dict]:
    """The dividend history and price of the ETF tracking each unknown fund's index, where one matches."""
    wanted = {sym: proxies.lookthrough_proxy_for(names.get(sym)) for sym in unknown}
    wanted = {sym: proxy for sym, proxy in wanted.items() if proxy}
    if not wanted:
        return {}
    try:
        histories = market.dividend_histories(sorted(set(wanted.values())), years=years)
    except Exception:  # noqa: BLE001 — without it the fund stays unknown, never a failed run
        return {}
    prices = {proxy: _one_quote(proxy, hub).get("price") for proxy in sorted(set(wanted.values()))}
    return {sym: {"proxy": proxy, "price": prices[proxy], "dividends": histories.get(proxy) or []} for sym, proxy in wanted.items() if prices[proxy]}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"dividends.py: {message}")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="dividends.py", add_help=False)
        p.add_argument("--account", action="append", default=None)
        p.add_argument("--partial", action="store_true")
        p.add_argument("--payout", action="store_true")
        p.add_argument("--yield-context", dest="yield_context", action="store_true")
        p.add_argument("--years", type=int, default=5)
        p.add_argument("--as-of", dest="as_of", default=None)
        ns = p.parse_args(args)
        if ns.years < 1 or ns.years > 20:
            raise InvalidInput("--years must be between 1 and 20")

        hub = router.load()
        hub.partial = ns.partial
        accounts = hub.list_accounts()
        if not accounts:
            raise ApiError("no open brokerage accounts are connected; use the connect skill", code="NO_ACCOUNTS")
        if ns.account:
            known = {a["account_id"] for a in accounts}
            unknown = [w for w in ns.account if w not in known]
            if unknown:
                raise hub.unknown_account_error(unknown)
            accounts = [a for a in accounts if a["account_id"] in set(ns.account)]

        rows = [{"account_id": a["account_id"], "positions": hub.get_portfolio(a["account_id"])["positions"] or []} for a in accounts]
        symbols = sorted({income._symbol(pos) for r in rows for pos in r["positions"] if isinstance(pos, dict)})  # noqa: SLF001

        sources = {"holdings": router.holdings_source(accounts), "dividends": "yahoo", "fundamentals": None}
        dividends = market.dividend_histories(symbols, years=ns.years) if symbols else {}
        fundamentals = None
        if ns.payout and symbols:
            fundamentals = market.payout_info(symbols)
            sources["fundamentals"] = "yahoo"

        names = _names(rows)
        money_market, unknown = _sort_no_history(symbols, dividends, names, hub)
        params = {
            "accounts": rows,
            "dividends": {s: h for s, h in dividends.items() if s not in unknown},
            "fundamentals": fundamentals or {},
            "money_market": money_market,
            "lookthrough": _lookthrough(unknown, names, hub, ns.years),
        }
        if ns.as_of:
            params["as_of"] = ns.as_of
        result = income.run_income(params)

        if ns.yield_context:
            as_of = date.fromisoformat(result["as_of"])
            payers = sorted(r["symbol"] for r in result["positions"] if r["income_status"] == "dividends" and (r.get("annual_income") or 0.0) > 0)
            if payers:
                history: dict = {}
                try:
                    history = market.close_histories(payers, (as_of - timedelta(days=_YIELD_CONTEXT_DAYS)).isoformat())
                except Exception as e:  # noqa: BLE001 — yield context is additive, never a failed run
                    result["flags"].append(
                        {
                            "code": "YIELD_CONTEXT_UNAVAILABLE",
                            "message": f"Yahoo price history failed ({e}); yield context omitted",
                        }
                    )
                trap_flags: list[dict] = []
                for row in result["positions"]:
                    if row["symbol"] not in payers:
                        continue
                    fields, flags = _yield_context(row["symbol"], dividends, history, as_of)
                    row.update(fields)
                    trap_flags.extend(flags)
                result["flags"].extend(sorted(trap_flags, key=lambda f: f["message"]))

        result["flags"].extend(hub.unavailable_flags())
        return {"sources": sources, **result}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
