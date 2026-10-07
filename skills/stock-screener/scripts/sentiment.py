#!/usr/bin/env python3
"""Usage: sentiment.py SYM[,SYM...] [--days 20 (max 60)] [--news-days 30] [--news 10]

Short-sale volume and dated news per symbol, with no web search. Up to 25 symbols.

short_volume: FINRA daily short-sale volume (latest short-volume ratio against its ``--days``
average; at most 60, one FINRA file per trading day). This is the share of each day's trading that was short sales, NOT short interest
(the open short position outstanding), which FINRA publishes only twice a month.
news: up to ``--news`` Yahoo headlines from the last ``--news-days`` days, newest first, each
with its publication date-time.

Output: {"as_of", "symbols": {SYM: {"short_volume": <summary entry or null>, "news": [...]}},
"flags": [{"code", "message"}]}. Flags: NO_SHORT_VOLUME (no FINRA rows for a symbol; its
short_volume is null), NEWS_UNAVAILABLE (the news fetch failed; its news is []).
Exit 2 on a bad symbol, an empty list, more than 25 symbols or --days above 60.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import brokerage, finra, flows, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

MAX_SYMBOLS = 25
MAX_DAYS = 60


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"sentiment.py: {message}")


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="sentiment.py", add_help=False)
    p.add_argument("symbols")
    p.add_argument("--days", type=int, default=20)
    p.add_argument("--news-days", type=int, default=30)
    p.add_argument("--news", type=int, default=10)
    return p


def run(args: list[str]) -> dict:
    ns = parser().parse_args(args)
    if ns.days < 1 or ns.news_days < 1 or ns.news < 1:
        raise InvalidInput("--days, --news-days and --news must be at least 1")
    if ns.days > MAX_DAYS:
        raise InvalidInput(f"--days is at most {MAX_DAYS} (one FINRA file is downloaded per trading day)")
    symbols: list[str] = []
    for raw in ns.symbols.split(","):
        if raw.strip():
            s = brokerage.validate_symbol(raw)
            if s not in symbols:
                symbols.append(s)
    if not symbols:
        raise InvalidInput("no symbols given")
    if len(symbols) > MAX_SYMBOLS:
        raise InvalidInput(f"at most {MAX_SYMBOLS} symbols, got {len(symbols)}")

    rows = finra.short_volume(symbols, days=ns.days)
    summary = {e["symbol"]: e for e in flows.short_volume_summary({s: rows.get(s) or [] for s in symbols})}
    flags: list[dict] = []
    out: dict[str, dict] = {}
    for s in symbols:
        entry = summary.get(s)
        if not entry or not entry.get("days"):
            entry = None
            flags.append({"code": "NO_SHORT_VOLUME", "message": f"{s}: no FINRA short-sale volume rows in the last {ns.days} days"})
        try:
            news = market.recent_news(s, days=ns.news_days, limit=ns.news)
        except Exception as e:  # noqa: BLE001 — news is best effort
            news = []
            flags.append({"code": "NEWS_UNAVAILABLE", "message": f"{s}: news fetch failed ({e.__class__.__name__}: {e})"})
        out[s] = {"short_volume": entry, "news": news}
    return {"as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbols": out, "flags": flags}


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
