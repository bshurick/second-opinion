#!/usr/bin/env python3
"""Usage: cards.py --run DIR [--symbols SYM,SYM] [--workers 3] [--force]

The deep picker's quick-read material, fetched before any quick reader starts: for each name
kept in ``DIR/pool.json`` (or only ``--symbols``, which must be pool names; ``BRK.B`` matches the
pool's ``BRK-B``) the ``card`` research
pack is built into ``DIR/cards/<TICKER>/`` (``second_opinion.pack.build``: EDGAR financials,
Yahoo profile, valuation inputs, quick value, sentiment and analysts, earnings releases, red-flag
passages, and an ``INDEX.md`` of them) and ``DIR/cards/<TICKER>.data.json`` is written:

  {...the pool row unchanged (ticker, name, origin, held, industry, sector, industry_verdict,
      contrarian, market_cap, why, screens, leader, health, failed_tests)...,
   "company", "price", "business_type", "pack_as_of",
   "quick_value": <the pack's quick_value.json: basis, bear, base, bull, irr_5y, note, scenarios,
                   and the business-type tests for a bank, REIT or utility>,
   "value_hint": 5 | 4 | 3 | 2 | 1 | null,
   "leverage": {"net_debt", "ebitda", "net_debt_to_ebitda", "interest_coverage", "debt_now",
                "debt_at_annual", "ok": true | false | null, "why",
                "flags": [LEVERAGE_HIGH, DEBT_CHANGED_SINCE_ANNUAL when they fired]},
   "red_flags": {"inputs_flags": [those of SHARE_CLASSES_COMBINED, CORPORATE_ACTION_SUSPECTED,
                                  LARGE_MINORITY_INTEREST, CYCLICAL, CYCLE_BASE_SPLIT,
                                  CURRENCY_MISMATCH, THIN_EDGAR_HISTORY that fired],
                 "terms": {"<red-flag term>": hits in the 10-K, only terms with a hit}},
   "direction": {"quarters_up_of_8", "ttm_revenue_growth"},
   "analysts": {"target_mean", "count"}, "insiders": {"buys", "sells"},
   "flags": [every inputs.py and intrinsic.py flag code],
   "sentiment_flags": [sentiment.py's flag codes, e.g. NEWS_UNAVAILABLE, ANALYSTS_UNAVAILABLE:
                       the file was built but Yahoo did not answer for that part],
   "missing": [pack files not built],
   "index": "<DIR>/cards/<TICKER>/INDEX.md"}

``value_hint`` is a starting point for the card's ``value`` score from ``quick_value.irr_5y``
(the annual return if the price closes on the base value in five years): 5 at 15% or more, 4 at
10%, 3 at 6%, 2 at 0, else 1; null when there is no return (a bank, a negative cash flow), and
always null with ``CURRENCY_MISMATCH`` (statements in another currency than the price: a foreign
filer's ADR), whatever the pack on disk says. A name that fails the balance-sheet check
(``leverage.ok`` false; ``leverage()`` is the contract: net debt today over 2x the latest annual
EBITDA, or EBIT covering interest under 6x) starts from a hint of at most 3, since a cheap price on
a levered company is how the downside gate has failed. ``leverage.ok`` is null for a financial,
REIT or utility and when figures are missing. ``THIN_EDGAR_HISTORY`` (no annual SEC data or no
10-K under this registrant) leaves the hint as it is: it rests on Yahoo's statements alone.
``direction`` counts the last 8 quarters with revenue above the same quarter a year earlier
(null when EDGAR has none) and gives trailing-twelve-month revenue growth. A hit on a red-flag
term is a passage to read, not a finding.

Packs are built ``--workers`` at a time (default 3). Each pack runs its Yahoo scripts one after
another, so the worker count is the number of Yahoo-bound processes; more than three drew HTTP
429. Safe to run again: a name whose ``cards/<TICKER>/pack.json`` is from today is not fetched
again (its data file is rewritten from the pack on disk) unless ``--force``, so a second run
after a rate limit fetches only the names that failed. A part Yahoo refused is in that name's
``missing``; rebuild it with ``--symbols SYM --force``.

Prints {"run", "cards": [{"ticker", "status": "built"|"skipped", "seconds", "basis", "base",
"irr_5y", "value_hint", "leverage_ok", "net_debt_to_ebitda", "missing", "sentiment_flags", "data": <path>}]
in pool order, "failed": [{"ticker", "error"}], "counts": {"names", "built", "skipped", "failed"},
"flags": [{"code", "message"}]}. LEVERAGE_HIGH names (``tickers``) the cards that fail the
balance-sheet check.
A name whose pack fails entirely (an unknown ticker, EDGAR not set up, anything else) is in
``failed`` (flag PACK_FAILED) and never an exit. YAHOO_RATE_LIMITED names the tickers
(``tickers``) whose pack, sentiment flags or failure mention a rate limit. Exit 2 on a bad argument, no
``pool.json``, or a ``--symbols`` name that is not in the pool. stdin is unused.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import output, pack  # noqa: E402
from second_opinion.errors import InvalidInput, ScriptError  # noqa: E402

DEFAULT_WORKERS = 3  # each pack is one Yahoo-bound chain of scripts; four at once drew HTTP 429
INPUTS_FLAGS = ("SHARE_CLASSES_COMBINED", "CORPORATE_ACTION_SUSPECTED", "LARGE_MINORITY_INTEREST", "CYCLICAL", "CYCLE_BASE_SPLIT", "CURRENCY_MISMATCH", "THIN_EDGAR_HISTORY")
VALUE_HINTS = ((0.15, 5), (0.10, 4), (0.06, 3), (0.0, 2))  # irr_5y at or above -> hint; below all of them is 1
QUARTERS = 8
# The finalist balance-sheet check. Debt turns a revenue decline into a large loss for the shares,
# which is how most downside-gate failures happened, so a finalist needs room on both tests.
MAX_NET_DEBT_TO_EBITDA = 2.0
MIN_INTEREST_COVERAGE = 6.0
DEBT_CHANGED_RATIO = 1.5  # debt now over 1.5x the last annual balance sheet: a deal or refinancing since
LEVERAGE_HINT_CAP = 3  # the most value_hint a name that fails the check can start from
YARDSTICK_TYPES = {"financial", "reit", "utility"}  # leverage is their business model; judged on their yardstick
_RATE_LIMIT_WORDS = ("Too Many Requests", "Rate limit", "429")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"cards.py: {message}")


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="cards.py", add_help=False)
    p.add_argument("--run", required=True)
    p.add_argument("--symbols", action="append", metavar="SYM,SYM")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--force", action="store_true")
    return p


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def value_hint(irr: Any) -> int | None:
    rate = _num(irr)
    if rate is None:
        return None
    return next((hint for floor, hint in VALUE_HINTS if rate >= floor), 1)


def direction(report: Any) -> dict:
    """Revenue direction from an edgar.py report (None or {} when it was not built)."""
    report = report if isinstance(report, dict) else {}
    rows = [r for r in report.get("quarterly") or [] if isinstance(r, dict)][-QUARTERS:]
    known = [y for r in rows if (y := _num(r.get("revenue_yoy"))) is not None]
    return {"quarters_up_of_8": sum(1 for y in known if y > 0) if known else None,
            "ttm_revenue_growth": _num((report.get("ttm") or {}).get("revenue_ttm_yoy"))}


def _latest_annual(table: Any) -> dict:
    """The latest period's row of a Yahoo statement keyed by date ({} when there is none)."""
    if not isinstance(table, dict) or not table:
        return {}
    row = table[max(table)]
    return row if isinstance(row, dict) else {}


def leverage(folder: Path, business_type: Any) -> dict:
    """The finalist balance-sheet check from the pack on disk (nothing is fetched).

    Net debt is today's: Yahoo's total debt less total cash (the latest quarter, leases included).
    EBITDA, EBIT and interest are the latest annual income statement's (Yahoo, else EDGAR's
    operating income plus D&A). ``ok`` is False when net debt is over MAX_NET_DEBT_TO_EBITDA x
    EBITDA, when EBITDA is not positive while net debt is, or when EBIT covers interest fewer than
    MIN_INTEREST_COVERAGE times. When debt now is over DEBT_CHANGED_RATIO x the annual balance
    sheet's (a deal or refinancing since), the annual interest no longer fits the debt, so the
    coverage test is left out and DEBT_CHANGED_SINCE_ANNUAL is raised: the 10-K's leverage figures
    are stale. Net cash passes, with no flag. A financial, REIT or utility gets ``ok`` null (judged on its
    yardstick), as does a company whose figures are missing."""
    out: dict[str, Any] = {"net_debt": None, "ebitda": None, "net_debt_to_ebitda": None, "interest_coverage": None,
                           "debt_now": None, "debt_at_annual": None, "ok": None, "why": None, "flags": []}
    if business_type in YARDSTICK_TYPES:
        out["why"] = f"{business_type}: leverage is judged on its yardstick, not on net debt to EBITDA"
        return out
    fund = _read(folder / "fundamentals.json")
    fund = fund if isinstance(fund, dict) else {}
    info = fund.get("info") or {}
    stmts = fund.get("statements") or {}
    income = _latest_annual(stmts.get("income_statement"))
    balance = _latest_annual(stmts.get("balance_sheet"))
    edgar = _read(folder / "edgar.json")
    annual = [r for r in ((edgar or {}).get("annual") or []) if isinstance(r, dict)] if isinstance(edgar, dict) else []
    last = annual[-1] if annual else {}

    debt_now, cash_now = _num(info.get("total_debt")), _num(info.get("total_cash"))
    ebitda = _num(income.get("EBITDA"))
    if ebitda is None and _num(last.get("operating_income")) is not None:
        ebitda = _num(last.get("operating_income")) + (_num(last.get("depreciation_amortization")) or 0.0)
    ebit = _num(income.get("EBIT")) if _num(income.get("EBIT")) is not None else _num(last.get("operating_income"))
    interest = _num(income.get("Interest Expense"))
    interest = abs(interest) if interest is not None else None
    debt_annual = _num(balance.get("Total Debt"))
    if debt_annual is None:
        debt_annual = _num(last.get("long_term_debt"))
    out.update(debt_now=debt_now, debt_at_annual=debt_annual, ebitda=ebitda)
    if debt_now is None:
        out["why"] = "no current total debt in fundamentals.json"
        return out
    net_debt = debt_now - (cash_now or 0.0)
    out["net_debt"] = net_debt

    if net_debt <= 0:
        out.update(ok=True, why=f"net cash of {-net_debt / 1e6:,.0f}M")
        return out
    changed = debt_annual is not None and debt_annual > 0 and debt_now > DEBT_CHANGED_RATIO * debt_annual
    if changed:
        out["flags"].append("DEBT_CHANGED_SINCE_ANNUAL")
    elif ebit is not None and interest:
        out["interest_coverage"] = round(ebit / interest, 2)

    fails: list[str] = []
    if ebitda is None:
        out["why"] = "no EBITDA to measure net debt against"
        return out
    if ebitda <= 0:
        fails.append(f"net debt of {net_debt / 1e6:,.0f}M against EBITDA that is not positive")
    else:
        ratio = round(net_debt / ebitda, 2)
        out["net_debt_to_ebitda"] = ratio
        if ratio > MAX_NET_DEBT_TO_EBITDA:
            fails.append(f"net debt {ratio:.1f}x EBITDA, above {MAX_NET_DEBT_TO_EBITDA:g}x")
    cov = out["interest_coverage"]
    if cov is not None and cov < MIN_INTEREST_COVERAGE:
        fails.append(f"EBIT covers interest {cov:.1f}x, below {MIN_INTEREST_COVERAGE:g}x")
    note = (f"; debt is {debt_now / debt_annual:.1f}x the last annual balance sheet's, so the 10-K's leverage figures are stale"
            " and annual interest coverage is left out") if changed else ""
    if fails:
        out["flags"].append("LEVERAGE_HIGH")
        out.update(ok=False, why="; ".join(fails) + note)
    else:
        out.update(ok=True, why=f"net debt {out['net_debt_to_ebitda']:.1f}x EBITDA" + (f", interest covered {cov:.1f}x" if cov is not None else "") + note)
    return out


def card_data(row: dict, built: dict, folder: Path) -> dict:
    """The data file for one pool row from its pack (``pack.json``'s content) in ``folder``."""
    summary = built.get("summary") or {}
    quick = _read(folder / "quick_value.json")
    if not isinstance(quick, dict):
        quick = dict(summary.get("quick_value") or {})
    quick = {k: v for k, v in quick.items() if k not in ("symbol", "as_of")}
    codes = [str(c) for c in summary.get("flags") or []]
    hits = summary.get("red_flag_hits") or {}
    lev = leverage(folder, summary.get("business_type"))
    hint = None if "CURRENCY_MISMATCH" in codes else value_hint(quick.get("irr_5y"))
    if hint is not None and lev["ok"] is False and hint > LEVERAGE_HINT_CAP:
        hint = LEVERAGE_HINT_CAP
    return {
        **row,
        "company": summary.get("company"), "price": summary.get("price"), "business_type": summary.get("business_type"),
        "pack_as_of": built.get("as_of"),
        "quick_value": quick,
        "value_hint": hint,
        "leverage": lev,
        "red_flags": {"inputs_flags": [c for c in INPUTS_FLAGS if c in codes], "terms": {t: n for t, n in hits.items() if n}},
        "direction": direction(_read(folder / "edgar.json")),
        "analysts": summary.get("analysts") or {"target_mean": None, "count": None},
        "insiders": summary.get("insiders") or {"buys": None, "sells": None},
        "flags": codes,
        "sentiment_flags": [f["code"] for f in _sentiment_flags(folder)],
        "missing": list(built.get("missing") or []),
        "index": built.get("index") or str(folder / "INDEX.md"),
    }


def _sentiment_flags(folder: Path) -> list[dict]:
    data = _read(folder / "sentiment.json")
    return [f for f in (data.get("flags") or [] if isinstance(data, dict) else []) if isinstance(f, dict) and f.get("code")]


def _fresh(folder: Path, today: str) -> dict | None:
    """Today's pack already in ``folder``, or None."""
    built = _read(folder / "pack.json")
    return built if isinstance(built, dict) and built.get("as_of") == today and isinstance(built.get("summary"), dict) else None


def _limited(text: Any) -> bool:
    return any(word in str(text) for word in _RATE_LIMIT_WORDS)


def _one(row: dict, cards_dir: Path, today: str, force: bool) -> dict:
    ticker = row["ticker"]
    folder = cards_dir / ticker
    start = time.monotonic()
    built = None if force else _fresh(folder, today)
    status = "skipped" if built is not None else "built"
    try:
        if built is None:
            built = pack.build(ticker, folder, level="card")
        data = card_data(row, built, folder)
        dest = cards_dir / f"{ticker}.data.json"
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    except ScriptError as exc:  # an unknown ticker (InvalidInput) or EDGAR not set up (ConfigError)
        return {"ticker": ticker, "failed": str(exc)}
    except Exception as exc:  # noqa: BLE001 — one name must not sink the batch
        return {"ticker": ticker, "failed": f"{exc.__class__.__name__}: {exc}"}
    errors = " ".join(str(f.get("error") or "") for f in (built.get("files") or {}).values() if isinstance(f, dict) and not f.get("ok"))
    errors += " " + " ".join(str(f.get("message") or "") for f in _sentiment_flags(folder))
    return {"ticker": ticker, "status": status, "seconds": round(time.monotonic() - start, 1),
            "basis": data["quick_value"].get("basis"), "base": data["quick_value"].get("base"), "irr_5y": data["quick_value"].get("irr_5y"),
            "value_hint": data["value_hint"], "leverage_ok": data["leverage"]["ok"], "net_debt_to_ebitda": data["leverage"]["net_debt_to_ebitda"],
            "missing": data["missing"], "sentiment_flags": data["sentiment_flags"], "data": str(dest), "_limited": _limited(errors)}


def run(args: list[str]) -> dict:
    ns = parser().parse_args(args)
    if ns.workers < 1:
        raise InvalidInput("--workers must be at least 1")
    wanted: list[str] = []
    for item in ns.symbols or []:
        for raw in item.split(","):
            if raw.strip():
                s = pack.canonical_symbol(raw)
                if s not in wanted:
                    wanted.append(s)
    if ns.symbols is not None and not wanted:
        raise InvalidInput("--symbols named no tickers")
    run_dir = Path(ns.run).expanduser()
    pool = _read(run_dir / "pool.json")
    if not isinstance(pool, dict) or not isinstance(pool.get("names"), list):
        raise InvalidInput(f"{run_dir / 'pool.json'} is missing or not pool.py's output; run pool.py --run first")
    rows = [r for r in pool["names"] if isinstance(r, dict) and r.get("ticker")]
    if wanted:
        known = {r["ticker"] for r in rows}
        unknown = [s for s in wanted if s not in known]
        if unknown:
            raise InvalidInput(f"not in pool.json's names: {', '.join(unknown)}")
        rows = [r for r in rows if r["ticker"] in wanted]
    cards_dir = run_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    with ThreadPoolExecutor(max_workers=ns.workers) as ex:
        results = list(ex.map(lambda r: _one(r, cards_dir, today, ns.force), rows))

    done = [r for r in results if "failed" not in r]
    failed = [{"ticker": r["ticker"], "error": r["failed"]} for r in results if "failed" in r]
    flags: list[dict] = []
    if failed:
        flags.append({"code": "PACK_FAILED", "message": f"no pack for {', '.join(f['ticker'] for f in failed)}; see failed. Run cards.py again to retry only these"})
    limited = [r["ticker"] for r in results if r.get("_limited") or _limited(r.get("failed") or "")]
    if limited:
        flags.append({"code": "YAHOO_RATE_LIMITED", "tickers": limited,
                      "message": f"Yahoo refused part of {', '.join(limited)} (rate limit). Wait a few minutes, then: cards.py --run {run_dir} --symbols {','.join(limited)} --force"})
    for r in done:
        r.pop("_limited", None)
    levered = [r["ticker"] for r in done if r.get("leverage_ok") is False]
    if levered:
        flags.append({"code": "LEVERAGE_HIGH", "tickers": levered,
                      "message": f"{', '.join(levered)} fail{'s' if len(levered) == 1 else ''} the finalist balance-sheet check (net debt over {MAX_NET_DEBT_TO_EBITDA:g}x EBITDA "
                                 f"or interest covered under {MIN_INTEREST_COVERAGE:g}x); each data file's leverage.why says which. They get quick reads but are not finalists"})
    return {"run": str(run_dir), "cards": done, "failed": failed,
            "counts": {"names": len(rows), "built": sum(1 for r in done if r["status"] == "built"),
                       "skipped": sum(1 for r in done if r["status"] == "skipped"), "failed": len(failed)},
            "flags": flags}


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
