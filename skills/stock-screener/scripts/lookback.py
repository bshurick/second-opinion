#!/usr/bin/env python3
"""Usage: lookback.py [--preset NAME] [--set KEY=VALUE ...] [--year YYYY] [--price-limit N]
                      [--benchmark SYMBOL]

Runs a screen as it would have looked in the past and reports what its survivors did
afterwards, so a preset's ranking can be checked against results before it is relied on.

``--year`` is the latest fiscal year the past screen could see (default: three years before
this one). The screen is dated 1 July of the following year, when those annual reports were
on file. The fundamentals are that period's SEC figures (the four fiscal years ending
``--year``, and the quarters reported by the screen date); the price stage uses each company's
market value on the screen date. Every survivor's total return (dividends reinvested) from
the screen date to today is then set beside ``--benchmark`` (default SPY).

Output: ``screen_date``, ``years``, ``years_held``, ``preset``, ``criteria``, ``funnel``,
``survivors`` (ranked as the screen ranked them, each with ``rank``, ``forward_return`` and
``beat_benchmark``), ``benchmark`` ``{"symbol", "return"}``, ``summary`` ``{"survivors",
"median_return", "mean_return", "beat_benchmark_share", "top_half_median",
"bottom_half_median", "rank_correlation", "passed_fundamentals_median"}``, ``priced`` and
``flags``. ``rank_correlation`` is Spearman's, between the screen's rank and the return rank:
positive means better-ranked survivors did better. ``passed_fundamentals_median`` is the
median return of every priced company that passed the business tests, the baseline the price
stage has to beat.

What this cannot tell you, each raised as a flag: it is one period, not a test over many;
companies delisted or acquired since have no ticker today and are left out
(``SURVIVORSHIP``), which flatters the result; market value on the screen date is today's
value scaled by the split-adjusted price change, so share issuance and buybacks since are
ignored, and net debt is taken as unchanged (``APPROXIMATE_VALUE``); the SEC figures are as
last reported, including later restatements. stdin is unused. Exit codes: 0, 2 (bad
argument), 5 (EDGAR/Yahoo error), 6 (Python dependencies missing).
"""
from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import screen  # noqa: E402
import screen_math  # noqa: E402
from second_opinion import edgar, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

DEFAULT_YEARS_BACK = 3
MAX_START_GAP_DAYS = 10  # a first price later than this after the screen date: not listed then
SMALL_SAMPLE = 15

History = Callable[[list[str], str], dict[str, list[dict[str, Any]]]]


def history(tickers: list[str], start: str) -> dict[str, list[dict[str, Any]]]:
    from second_opinion import market

    return market.close_histories(tickers, start)


def _at(bars: list[dict], when: dt.date) -> int | None:
    """Index of the first bar on or after ``when``, if it is close enough to count."""
    for i, bar in enumerate(bars):
        day = dt.date.fromisoformat(str(bar["date"])[:10])
        if day >= when:
            return i if (day - when).days <= MAX_START_GAP_DAYS else None
    return None


def then_and_since(bars: list[dict], when: dt.date) -> dict | None:
    """Price change to the screen date's close and total return since, from daily bars."""
    i = _at(bars, when)
    if i is None or i >= len(bars) - 1:
        return None
    start, end = bars[i], bars[-1]
    if not start["close"] or not end["close"] or not start["adj_close"]:
        return None
    return {
        "price_ratio": start["close"] / end["close"],
        "forward_return": end["adj_close"] / start["adj_close"] - 1,
        "momentum": screen.momentum_from_closes([b["adj_close"] for b in bars[: i + 1]]),
    }


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def rank_correlation(returns_in_rank_order: list[float]) -> float | None:
    """Spearman's between screen rank (best first) and return (best first)."""
    n = len(returns_in_rank_order)
    if n < 5:
        return None
    by_return = sorted(range(n), key=lambda i: -returns_in_rank_order[i])
    return_rank = {i: r for r, i in enumerate(by_return)}
    d2 = sum((i - return_rank[i]) ** 2 for i in range(n))
    return round(1 - 6 * d2 / (n * (n * n - 1)), 4)


def run(ns: argparse.Namespace, frame: screen.Frame | None = None, quoter: Callable[[str], dict | None] = screen.quote,
        today: dt.date | None = None, names: dict[int, dict] | None = None, history_of: History = history) -> dict:
    frame = frame or edgar.frame
    today = today or dt.date.today()
    latest = ns.year or today.year - DEFAULT_YEARS_BACK
    when = dt.date(latest + 1, 7, 1)
    if when >= today:
        raise InvalidInput(f"--year {latest} puts the screen date ({when}) in the future; pick an earlier year")
    years = list(range(latest - screen.YEARS_SCREENED + 1, latest + 1))
    overrides = screen.parse_overrides(ns.set)
    try:  # a bad preset or criterion is reported before anything is fetched
        screen_math.run_screen_math({"years": years, "companies": [], "preset": ns.preset, "criteria": overrides})
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    companies = screen.build_companies(frame, years, screen.quarter_periods(when), names if names is not None else edgar.tickers())
    payload = {"years": years, "companies": companies, "preset": ns.preset, "criteria": overrides}
    first = screen_math.run_screen_math(payload)
    pool, key = screen.price_pool(first["survivors"], ns.preset, ns.price_limit)
    with ThreadPoolExecutor(max_workers=8) as ex:
        quotes = dict(zip([s["cik"] for s in pool], ex.map(lambda s: quoter(s["ticker"]), pool)))
    tickers = [str(s["ticker"]).upper() for s in pool if quotes.get(s["cik"])]
    start = (when - dt.timedelta(days=screen.MOMENTUM_LOOKBACK_DAYS + screen.MOMENTUM_SKIP + 10)).isoformat()
    bars = history_of(tickers + [ns.benchmark], start)
    by_cik = {c["cik"]: c for c in companies}
    moves: dict[int, dict] = {}
    for s in pool:
        q, t = quotes.get(s["cik"]), str(s["ticker"]).upper()
        move = then_and_since(bars.get(t) or [], when) if q else None
        if not move:
            continue
        cap = q["market_cap"] * move["price_ratio"]
        ev = cap + (q["enterprise_value"] - q["market_cap"]) if q.get("enterprise_value") else None
        by_cik[s["cik"]]["market"] = {"market_cap": cap, "enterprise_value": ev if ev and ev > 0 else None, "price": None,
                                      "sector": q.get("sector"), "financial": q.get("financial"), "momentum": move["momentum"]}
        moves[s["cik"]] = move
    result = screen_math.run_screen_math(payload)
    bench = then_and_since(bars.get(ns.benchmark.upper()) or [], when)
    bench_return = round(bench["forward_return"], 4) if bench else None
    survivors = []
    # With nobody priced, screen_math returns the unpriced business-test survivors: not a result here.
    for rank, s in enumerate((s for s in result["survivors"] if s["cik"] in moves), start=1):
        ret = round(moves[s["cik"]]["forward_return"], 4)
        survivors.append({**s, "rank": rank, "forward_return": ret, "beat_benchmark": None if bench_return is None else ret > bench_return})
    returns = [s["forward_return"] for s in survivors]
    half = len(returns) // 2
    baseline = [round(m["forward_return"], 4) for m in moves.values()]
    summary = {
        "survivors": len(returns),
        "median_return": _median(returns),
        "mean_return": round(statistics.fmean(returns), 4) if returns else None,
        "beat_benchmark_share": round(sum(1 for s in survivors if s["beat_benchmark"]) / len(survivors), 4) if survivors and bench_return is not None else None,
        "top_half_median": _median(returns[:half]) if half else None,
        "bottom_half_median": _median(returns[half:]) if half else None,
        "rank_correlation": rank_correlation(returns),
        "passed_fundamentals_median": _median(baseline),
    }
    no_ticker = sum(1 for s in first["survivors"] if not s.get("ticker"))
    not_listed = len(pool) - len(moves)
    flags = [
        {"code": "ONE_PERIOD", "message": f"one screen date ({when}) and one stretch of market; a ranking that worked or failed here may not elsewhere"},
        {"code": "SURVIVORSHIP", "message": f"{no_ticker} companies that passed the business tests have no ticker today (delisted or acquired) and {not_listed} had no price on the screen date; leaving them out flatters the result"},
        {"code": "APPROXIMATE_VALUE", "message": "market value on the screen date is today's value scaled by the split-adjusted price change; share issuance, buybacks and debt changes since are ignored"},
    ]
    if len(returns) < SMALL_SAMPLE:
        flags.append({"code": "SMALL_SAMPLE", "message": f"{len(returns)} survivors: the medians and the rank correlation can turn on one or two companies"})
    if bench_return is None:
        flags.append({"code": "NO_BENCHMARK", "message": f"no price history for {ns.benchmark}; returns are shown without a benchmark"})
    if edgar.user_agent_is_default():
        flags.append({"code": "EDGAR_USER_AGENT_DEFAULT", "message": "EDGAR_USER_AGENT is the placeholder; the SEC may throttle or block requests"})
    return {
        "as_of": today.isoformat(),
        "screen_date": when.isoformat(),
        "years": years,
        "years_held": round((today - when).days / 365.25, 2),
        "preset": result["preset"],
        "criteria": result["criteria"],
        "rank_by": result["rank_by"],
        "universe": result["universe"],
        "funnel": result["funnel"],
        "survivors": survivors,
        "benchmark": {"symbol": ns.benchmark.upper(), "return": bench_return},
        "summary": summary,
        "priced": {"count": len(moves), "of": len(first["survivors"]), "limit": ns.price_limit, "pool_by": key},
        "sources": {"fundamentals": "SEC EDGAR XBRL frames", "prices": "Yahoo daily closes"},
        "flags": flags,
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"lookback.py: {message}")


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="lookback.py", add_help=False)
    p.add_argument("--preset", default="growth", choices=sorted(screen_math.PRESETS))
    p.add_argument("--set", action="append", metavar="KEY=VALUE")
    p.add_argument("--year", type=int)
    p.add_argument("--price-limit", type=int, default=screen.DEFAULT_PRICE_LIMIT)
    p.add_argument("--benchmark", default="SPY")
    return p


def main(argv: list[str] | None = None) -> int:
    return output.run(lambda args: run(parser().parse_args(args)), argv)


if __name__ == "__main__":
    sys.exit(main())
