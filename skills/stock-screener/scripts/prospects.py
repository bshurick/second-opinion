#!/usr/bin/env python3
"""Usage: prospects.py SYM[,SYM...] [--out FILE]

The industry scanner's four prospect tests for up to 25 tickers at once, from the
fundamental-research skill's ``edgar.py SYM --years 5 --quarters 12`` (one subprocess per
symbol, six at a time), Yahoo's company profile and one batched Yahoo price download.

Per symbol:

  {"ticker", "name", "market_cap", "tests_passed": n,
   "tests": {"trajectory": {"pass", "figures": {"quarters_up_of_8", "ttm_revenue_growth",
                                                "net_margin_ttm", "net_margin_prior_ttm"}},
             "cash": {"pass", "figures": {"fcf_positive_years_of_4", "dividends_covered"}},
             "price": {"pass", "figures": {"pe", "forward_pe", "fcf_yield", "change_12m",
                                           "pct_of_52w_high"}},
             "overlooked": {"pass", "figures": {"analyst_count", "institutional_ownership",
                                                "change_12m"}}},
   "size_ok": market_cap >= 3e8 (null without a market cap),
   "why": "<one line of the passing tests with their figures>", "flags": [codes]}

Rules. ``trajectory``: revenue above the same quarter a year earlier in at least 5 of the last 8
quarters, and the trailing-twelve-month net margin not below the twelve months before.
``cash``: free cash flow positive in at least 3 of the last 4 fiscal years and no smaller than
dividends paid in the latest (nothing paid counts as covered). ``price``: free-cash-flow yield
(latest fiscal year's free cash flow over market cap) at least 6%, or trailing P/E (Yahoo's,
else market cap over trailing net income) at most 15; otherwise ``pass`` is null, never false,
because the scanner judges price against history and peers. ``overlooked``: at most 8 analysts,
or institutions holding under 60%, or a 12-month price change below -20%. ``change_12m`` is the
last close against the close a year earlier (split-adjusted, dividends not added back). A figure
that cannot be computed is null; a test is true or false only when the figures it has settle
it, otherwise null. ``tests_passed`` counts the tests that are true. Ratios are fractions.

Output: {"as_of", "prospects": [...in the order given...], "not_found": [tickers not in the
SEC ticker list; BRK.B is looked up as BRK-B], "flags": [{"code", "message"}]}; ``--out FILE`` also writes it there (``"out"`` names
the file). Row flags: EDGAR_UNAVAILABLE (edgar.py failed for a reason other than an unknown
ticker, such as a foreign filer with no US-GAAP facts: the EDGAR figures and tests are null;
the top-level flag carries its error), BANK_REVENUE_PROXY and MISSING_DATA (passed on from
edgar.py: read the cash and margin tests with care), QUOTE_UNAVAILABLE (no Yahoo profile or market
cap), PRICE_HISTORY_UNAVAILABLE (no 12-month change). The top-level flags repeat each with the
tickers. Exit 2 on a bad symbol, an empty list or more than 25 symbols; 6 on missing
dependencies. stdin is unused.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import brokerage, market, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

EDGAR_SCRIPT = _HERE.parents[1] / "fundamental-research" / "scripts" / "edgar.py"
MAX_SYMBOLS = 25
# Every EDGAR request, in any process, waits on one file lock that spaces them 0.125 s apart
# (second_opinion.edgar._throttle), so the worker count cannot breach the SEC's limit; six is
# about what the throttle lets through (two or three requests a symbol) and is easy on Yahoo.
WORKERS = 6
EDGAR_TIMEOUT = 300
MIN_MARKET_CAP = 3e8
QUARTERS, QUARTERS_UP_MIN = 8, 5
FCF_YEARS, FCF_YEARS_MIN = 4, 3
MIN_FCF_YIELD, MAX_PE = 0.06, 15.0
MAX_ANALYSTS, MAX_INSTITUTIONAL, MAX_CHANGE = 8, 0.60, -0.20
TTM_SPAN = (250, 300)  # days from the first to the last period end of four consecutive quarters
YEAR_TOLERANCE_DAYS = 10
HISTORY_DAYS = 400
_NOT_LISTED = "SEC ticker list"  # edgar.cik_for's message; its other exit-2 errors are a filer without usable facts
PASSED_ON = ("BANK_REVENUE_PROXY", "MISSING_DATA")  # edgar.py flags a reader of the cash and margin tests needs
_FLAG_TEXT = {
    "EDGAR_UNAVAILABLE": "edgar.py failed; EDGAR figures and tests are null",
    "QUOTE_UNAVAILABLE": "no Yahoo profile or market cap; price and size figures are null",
    "PRICE_HISTORY_UNAVAILABLE": "no year of Yahoo closes; change_12m is null",
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"prospects.py: {message}")


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="prospects.py", add_help=False)
    p.add_argument("symbols")
    p.add_argument("--out")
    return p


def edgar_report(symbol: str) -> tuple[int, dict]:
    """``edgar.py SYM --years 5 --quarters 12`` as its own process: ``(exit code, its JSON)``."""
    cmd = [sys.executable, str(EDGAR_SCRIPT), symbol, "--years", "5", "--quarters", "12"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=EDGAR_TIMEOUT)  # noqa: S603 — our own script
        data = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return 5, {"error": f"{exc.__class__.__name__}: {exc}"[:300]}
    return proc.returncode, data if isinstance(data, dict) else {}


def change_12m(bars: list[dict]) -> float | None:
    """Last close against the close nearest one year before it (within ten days), as a fraction."""
    rows = []
    for b in bars or []:
        try:
            rows.append((dt.date.fromisoformat(str(b["date"])[:10]), float(b["close"])))
        except (KeyError, TypeError, ValueError):
            continue
    if len(rows) < 2:
        return None
    rows.sort()
    end, last = rows[-1]
    target = end - dt.timedelta(days=365)
    then_date, then = min(rows[:-1], key=lambda r: abs((r[0] - target).days))
    if abs((then_date - target).days) > YEAR_TOLERANCE_DAYS or then <= 0:
        return None
    return round(last / then - 1, 4)


def price_changes(symbols: list[str]) -> dict[str, float | None]:
    """12-month price change per symbol from ONE batched Yahoo download; all null when it fails."""
    start = (dt.date.today() - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    try:
        hist = market.close_histories([s.replace(".", "-") for s in symbols], start)
    except Exception:  # noqa: BLE001 — the change is one figure; the rest stands without it
        return {s: None for s in symbols}
    return {s: change_12m(hist.get(s.replace(".", "-").upper()) or []) for s in symbols}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _all(*parts: bool | None) -> bool | None:
    """Three-valued AND: false when any part is false, true when all are, else unknown."""
    if any(p is False for p in parts):
        return False
    return True if all(p is True for p in parts) else None


def _at_least(hits: int, unknown: int, need: int) -> bool | None:
    if hits >= need:
        return True
    return False if hits + unknown < need else None


def _r4(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _trajectory(report: dict) -> tuple[dict, str]:
    rows = [r for r in report.get("quarterly") or [] if isinstance(r, dict)]
    last = rows[-QUARTERS:]
    yoy = [_num(r.get("revenue_yoy")) for r in last]
    known = [y for y in yoy if y is not None]
    up = sum(1 for y in known if y > 0) if known else None
    up_ok = None if up is None else _at_least(up, QUARTERS - len(known), QUARTERS_UP_MIN)
    ttm = report.get("ttm") or {}
    rev, ni = _num(ttm.get("revenue")), _num(ttm.get("net_income"))
    margin = ni / rev if rev and ni is not None else None
    prior = None
    window = rows[-8:-4] if len(rows) >= 8 else []
    if window:
        try:
            span = (dt.date.fromisoformat(str(window[-1]["period_end"])[:10]) - dt.date.fromisoformat(str(window[0]["period_end"])[:10])).days
        except (KeyError, ValueError):
            span = None
        revs, nis = [_num(r.get("revenue")) for r in window], [_num(r.get("net_income")) for r in window]
        if span is not None and TTM_SPAN[0] <= span <= TTM_SPAN[1] and None not in revs and None not in nis and sum(revs):
            prior = sum(nis) / sum(revs)
    margin_ok = None if margin is None or prior is None else round(margin, 4) >= round(prior, 4)
    figures = {"quarters_up_of_8": up, "ttm_revenue_growth": _num(ttm.get("revenue_ttm_yoy")),
               "net_margin_ttm": _r4(margin), "net_margin_prior_ttm": _r4(prior)}
    passed = _all(up_ok, margin_ok)
    why = f"trajectory: revenue up in {up} of 8 quarters, TTM net margin {_pct(margin)} against {_pct(prior)} a year earlier" if passed else ""
    return {"pass": passed, "figures": figures}, why


def _cash(report: dict) -> tuple[dict, str, float | None]:
    annual = [r for r in report.get("annual") or [] if isinstance(r, dict)][-FCF_YEARS:]
    fcf = [_num(r.get("free_cash_flow")) for r in annual]
    known = [f for f in fcf if f is not None]
    positive = sum(1 for f in known if f > 0) if known else None
    years_ok = None if positive is None else _at_least(positive, FCF_YEARS - len(known), FCF_YEARS_MIN)
    latest = fcf[-1] if fcf else None
    paid = _num(annual[-1].get("dividends_paid")) if annual else None
    covered = None if latest is None else latest >= abs(paid or 0)
    passed = _all(years_ok, covered)
    why = ""
    if passed:
        why = f"cash: free cash flow positive in {positive} of 4 years" + (", dividends covered" if paid else ", no dividend to cover")
    return {"pass": passed, "figures": {"fcf_positive_years_of_4": positive, "dividends_covered": covered}}, why, latest


def _price(info: dict, report: dict, fcf_latest: float | None, change: float | None) -> tuple[dict, str]:
    cap = _num(info.get("market_cap"))
    pe = _num(info.get("pe_ratio"))
    ttm_ni = _num((report.get("ttm") or {}).get("net_income"))
    if pe is None and cap and ttm_ni and ttm_ni > 0:
        pe = cap / ttm_ni
    fcf_yield = fcf_latest / cap if cap and fcf_latest is not None else None
    price, high = _num(info.get("current_price")), _num(info.get("52_week_high"))
    reasons = []
    if pe is not None and 0 < pe <= MAX_PE:
        reasons.append(f"P/E {pe:.1f}")
    if fcf_yield is not None and fcf_yield >= MIN_FCF_YIELD:
        reasons.append(f"free-cash-flow yield {_pct(fcf_yield)}")
    figures = {"pe": None if pe is None else round(pe, 2), "forward_pe": None if _num(info.get("forward_pe")) is None else round(_num(info.get("forward_pe")), 2),
               "fcf_yield": _r4(fcf_yield), "change_12m": change, "pct_of_52w_high": _r4(price / high) if price and high else None}
    return {"pass": True if reasons else None, "figures": figures}, ("price: " + ", ".join(reasons)) if reasons else ""


def _overlooked(info: dict, change: float | None) -> tuple[dict, str]:
    analysts, held = _num(info.get("analyst_count")), _num(info.get("institutional_ownership"))
    reasons = []
    if analysts is not None and analysts <= MAX_ANALYSTS:
        reasons.append(f"{int(analysts)} analyst{'' if int(analysts) == 1 else 's'}")
    if held is not None and held < MAX_INSTITUTIONAL:
        reasons.append(f"institutions hold {_pct(held)}")
    if change is not None and change < MAX_CHANGE:
        reasons.append(f"down {_pct(-change)} in 12 months")
    passed: bool | None = True if reasons else (None if None in (analysts, held, change) else False)
    figures = {"analyst_count": None if analysts is None else int(analysts), "institutional_ownership": _r4(held), "change_12m": change}
    return {"pass": passed, "figures": figures}, ("overlooked: " + ", ".join(reasons)) if reasons else ""


def prospect(symbol: str, report: dict | None, info: dict | None, change: float | None) -> dict:
    """One row from an edgar.py report (None when it failed), a company profile and the 12-month change."""
    flags = []
    if report is None:
        flags.append("EDGAR_UNAVAILABLE")
    if not info or _num(info.get("market_cap")) is None:
        flags.append("QUOTE_UNAVAILABLE")
    if change is None:
        flags.append("PRICE_HISTORY_UNAVAILABLE")
    report, info = report or {}, info or {}
    flags += [f["code"] for f in report.get("flags") or [] if isinstance(f, dict) and f.get("code") in PASSED_ON]
    trajectory, why_t = _trajectory(report)
    cash, why_c, fcf_latest = _cash(report)
    price, why_p = _price(info, report, fcf_latest, change)
    overlooked, why_o = _overlooked(info, change)
    tests = {"trajectory": trajectory, "cash": cash, "price": price, "overlooked": overlooked}
    cap = _num(info.get("market_cap"))
    return {
        "ticker": symbol,
        "name": info.get("name") or report.get("company"),
        "market_cap": cap,
        "tests_passed": sum(1 for t in tests.values() if t["pass"] is True),
        "tests": tests,
        "size_ok": None if cap is None else cap >= MIN_MARKET_CAP,
        "why": "; ".join(w for w in (why_t, why_c, why_p, why_o) if w),
        "flags": flags,
    }


def _gather(symbol: str) -> tuple[int, dict, dict | None]:
    lookup = symbol.replace(".", "-")  # the SEC list and Yahoo both write BRK.B as BRK-B
    try:
        rc, report = edgar_report(lookup)
    except Exception as exc:  # noqa: BLE001 — one symbol must not sink the batch
        rc, report = 5, {"error": str(exc)}
    try:
        info = market.company_info(lookup)
    except Exception:  # noqa: BLE001 — Yahoo is best effort
        info = None
    return rc, report, info


def run(args: list[str]) -> dict:
    ns = parser().parse_args(args)
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
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        changes_job = ex.submit(price_changes, symbols)
        gathered = dict(zip(symbols, ex.map(_gather, symbols)))
        try:
            changes = changes_job.result()
        except Exception:  # noqa: BLE001
            changes = {}
    rows, not_found, errors = [], [], {}
    for s in symbols:
        rc, report, info = gathered[s]
        if rc == 2 and _NOT_LISTED in str(report.get("error") or ""):
            not_found.append(s)
            continue
        if rc != 0:  # EDGAR down, or a filer with no US-GAAP facts (a foreign issuer filing IFRS)
            errors[s] = str(report.get("error") or f"exit {rc}")
        rows.append(prospect(s, report if rc == 0 else None, info, changes.get(s)))
    flags = []
    for code, text in _FLAG_TEXT.items():
        hit = [r["ticker"] for r in rows if code in r["flags"]]
        if hit:
            detail = f" ({'; '.join(f'{t}: {errors[t]}' for t in hit if t in errors)})" if code == "EDGAR_UNAVAILABLE" else ""
            flags.append({"code": code, "message": f"{', '.join(hit)}: {text}{detail}"})
    result: dict[str, Any] = {"as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                              "prospects": rows, "not_found": not_found, "flags": flags}
    if ns.out:
        dest = Path(ns.out).expanduser()
        dest.parent.mkdir(parents=True, exist_ok=True)
        result["out"] = str(dest.resolve())
        dest.write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
