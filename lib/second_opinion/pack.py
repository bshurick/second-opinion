"""The research pack: everything the scripts can fetch about one company, written to a folder
before any research subagent starts, so subagents read files instead of fetching.

``build(symbol, out_dir, level)`` runs the existing skill scripts as subprocesses of
``sys.executable`` and writes one file per result, then ``INDEX.md`` (what each file holds, the
headline figures, what is missing and the resolved script commands) and ``pack.json`` (what it
returns). Level ``card`` is the deep picker's quick read; ``deep`` adds the 10-K and 10-Q text and
the forensic checks for a deep valuation.

The 10-Q's statements (deep). ``filings/10q-item1.txt`` is Part I Item 1, the financial statements
and notes with the latest quarter-end balance sheet. A 10-Q has two Item 1s (Part II's is Legal
Proceedings) and ``filing.py --item 1`` returns the longer one, which is the statements in nearly
every filing. The pack checks the text for a "Total assets" or "Total liabilities" line; without
one it writes the passages around "total liabilities" from the same 10-Q instead and says so in
the index, and when there are none the file is in ``missing``.

Order and concurrency. Every EDGAR request in every process waits on one file lock
(``edgar._throttle``: 0.125 s apart, about 8 a second against the SEC's limit of 10), so any number
of script subprocesses at once stays inside the limit. The disk cache is not locked, though: two
processes that both miss the same URL download it twice, and one can read the other's half-written
file. So the pack fetches each shared document once before fanning out:

1. ``edgar.py`` alone (ticker list, filing index, company facts);
2. in parallel, the scripts that share nothing uncached: the Yahoo ones, ``intrinsic-inputs.py``,
   ``earnings.py``, the 10-Q reads (one after the other), and ONE read of the latest 10-K;
3. in parallel, every other read of that 10-K (now cached), with the two ``--diff`` reads one after
   the other because both fetch the previous 10-K.

Symbols. A dotted share class (``BRK.B``) is built as the dash form (``BRK-B``), which is what both
the SEC ticker list and Yahoo use; ``canonical_symbol`` is that rule, ``pack.json`` carries the dash
form as ``symbol`` and what was asked for as ``requested``.

Flags the pack raises or acts on (``summary.flags``; the message of each is in
``summary.flag_notes`` and at the top of ``INDEX.md``):

- ``CURRENCY_MISMATCH`` (inputs.py's): Yahoo's statements are in another currency than the quote
  (TSM: TWD and USD). The quick value then has ``basis`` null and no bear, base, bull or return.
- ``THIN_EDGAR_HISTORY`` (the pack's): ``edgar.json`` was built but has no annual rows, or its
  filing index has no 10-K. The filings may sit under a predecessor registrant (a holding-company
  reorganisation gives the successor a new CIK: XOM), or the company files a 20-F or 40-F. The
  quick value then rests on Yahoo's statements alone.

A source that fails is a named entry in ``missing`` and the rest of the pack is still built. Only
an unknown ticker (``InvalidInput``, exit 2) or a script exiting 4 (``ConfigError``: EDGAR or the
fundamental-research skill is not set up) stops it.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from second_opinion import brokerage
from second_opinion.errors import ConfigError, InvalidInput

SKILLS = Path(__file__).resolve().parents[2] / "skills"
_RESEARCH = SKILLS / "fundamental-research" / "scripts"
_VALUATION = SKILLS / "valuation" / "scripts"
SCRIPTS: dict[str, Path] = {
    "edgar.py": _RESEARCH / "edgar.py",
    "filing.py": _RESEARCH / "filing.py",
    "earnings.py": _RESEARCH / "earnings.py",
    "fundamentals.py": _VALUATION / "fundamentals.py",
    "inputs.py": _VALUATION / "inputs.py",
    "intrinsic-inputs.py": _VALUATION / "intrinsic-inputs.py",
    "intrinsic.py": _VALUATION / "intrinsic.py",
    "dcf.py": _VALUATION / "dcf.py",
    "returns.py": _VALUATION / "returns.py",
    "model.py": _VALUATION / "model.py",
    "sentiment.py": SKILLS / "stock-screener" / "scripts" / "sentiment.py",
}
LEVELS = ("card", "deep")
RED_FLAG_TERMS = {
    "card": ("going concern", "material weakness", "restat", "related part"),
    "deep": ("going concern", "material weakness", "restat", "related part", "capitalized", "change in accounting"),
}
ITEMS_10K = ("1", "1A", "7", "8", "9A")
DIFF_ITEMS = ("1A", "8")
ITEM_MAX_CHARS = 600_000
TENQ_MAX_CHARS = 200_000
SEGMENT_CONTEXT = 3000
SEGMENT_NOTE_MAX_CHARS = 60_000
RED_FLAG_HITS_KEPT = 10
MIN_ITEM_CHARS = 400  # a shorter Item 1, 1A, 7 or 8 is a parsing miss or "incorporated by reference"
MIN_SHORT_ITEM_CHARS = 200  # the same for Item 9A, which is short when real
FULL_TEXT = "filings/10k-full.txt"
TENQ_STATEMENTS = "filings/10q-item1.txt"
TENQ_STATEMENTS_TERM = "total liabilities"  # searched when Item 1 is not the statements
_BALANCE_SHEET = re.compile(r"total\s+(?:assets|liabilities)", re.IGNORECASE)
FULL_TEXT_MIN_CHARS = 100_000
_YAHOO_RETRY_WAIT = 12  # seconds, once, after an HTTP 429 from Yahoo
_TIMEOUT = 300
_EDGAR_SCRIPTS = ("edgar.py", "filing.py", "earnings.py", "intrinsic-inputs.py")
_YARDSTICKS = {"FINANCIALS": ("book_value", "book_value_tests"), "REITS": ("reit", "reit_tests"), "UTILITIES": ("utility", "utility_tests")}
_TYPE_SUFFIX = {"financial": "FINANCIALS", "reit": "REITS", "utility": "UTILITIES"}
_RECEIVABLE_MULTIPLE = 1.5  # references/deep-roles.md, Forensic table
_BALANCE_FLOOR = 0.02

CURRENCY_FLAG = "CURRENCY_MISMATCH"
THIN_FLAG = "THIN_EDGAR_HISTORY"

Runner = Callable[..., tuple[int, Any, str]]


def canonical_symbol(symbol: str) -> str:
    """The one form a ticker is matched and fetched by: upper case, a share-class dot as a dash
    (``BRK.B`` -> ``BRK-B``, as the SEC ticker list and Yahoo both write it). InvalidInput for a
    symbol that is not one."""
    return brokerage.validate_symbol(symbol).replace(".", "-")


def _run(script: str, args: list[str], stdin: str | None = None, timeout: int | None = None) -> tuple[int, Any, str]:
    """Run one skill script; returns (exit code, its stdout parsed as JSON or None, stderr tail)."""
    path = SCRIPTS[script]
    if not path.is_file():
        return 4, {"error": f"{script} is not installed ({path})", "code": "SKILL_MISSING"}, ""
    try:
        proc = subprocess.run([sys.executable, str(path), *args], input=stdin, capture_output=True, text=True, timeout=timeout or _TIMEOUT)  # noqa: S603
    except subprocess.TimeoutExpired:
        return 5, {"error": f"{script} did not finish in {timeout or _TIMEOUT} seconds", "code": "TIMEOUT"}, ""
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        data = None
    return proc.returncode, data, (proc.stderr or "")[-400:]


class _Stop(Exception):
    """A script exited 4: carried out of the worker threads and re-raised as ConfigError."""

    def __init__(self, script: str, data: Any) -> None:
        super().__init__(script)
        self.script, self.data = script, data


def _call(script: str, args: list[str], stdin: str | None = None) -> tuple[Any, str | None]:
    """(JSON, None) on success, (JSON or None, error text) on failure; exit 4 raises _Stop."""
    try:
        rc, data, err = _run(script, args, stdin=stdin, timeout=_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — a script that cannot even start is one missing file
        return None, f"{script} could not run ({exc.__class__.__name__}: {exc})"
    if rc == 4 and script in _EDGAR_SCRIPTS:
        raise _Stop(script, data)
    if rc == 0 and isinstance(data, dict) and "error" not in data:
        return data, None
    message = data.get("error") if isinstance(data, dict) else None
    return (data if isinstance(data, dict) else None), f"{script} exit {rc}: {message or (err.strip().splitlines() or ['no output'])[-1]}"


_yahoo_limited = threading.Event()  # set once a retry was also refused: later calls in this process do not wait


def _yahoo_call(script: str, args: list[str]) -> tuple[Any, str | None]:
    """_call for a script that reads Yahoo, with one retry after a rate-limit refusal."""
    def limited(obj: Any, err: str | None) -> bool:
        if err:
            return "Too Many Requests" in err or "Rate limit" in err
        return {"NEWS_UNAVAILABLE", "ANALYSTS_UNAVAILABLE"} <= set(_codes(obj)) and "Too Many Requests" in json.dumps(obj.get("flags"))

    obj, err = _call(script, args)
    if limited(obj, err) and not _yahoo_limited.is_set():
        time.sleep(_YAHOO_RETRY_WAIT)
        obj, err = _call(script, args)
        if limited(obj, err):
            _yahoo_limited.set()
    return obj, err


def _min_chars(item: str) -> int:
    return MIN_SHORT_ITEM_CHARS if item.upper() == "9A" else MIN_ITEM_CHARS


def _codes(*outputs: Any) -> list[str]:
    seen: list[str] = []
    for out in outputs:
        for flag in (out or {}).get("flags") or [] if isinstance(out, dict) else []:
            code = flag.get("code") if isinstance(flag, dict) else None
            if code and code not in seen:
                seen.append(code)
    return seen


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _dig(obj: Any, *keys: str) -> Any:
    for key in keys:
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj


# ── quick value ─────────────────────────────────────────────────────────────


def quick_value(inputs: dict | None, intrinsic: dict | None, run: Runner | None = None) -> dict:
    """The quick-mode value range (the valuation SKILL's Quick step 7) or, for a business a cash-flow
    DCF says little about, the yardstick to judge it on.

    {"basis": "dcf" | "normalized" | "book_value" | "reit" | "utility" | None,
     "bear", "base", "bull", "irr_5y", "note", ...detail}

    - ``DCF_NOT_MEANINGFUL_FOR_…`` (inputs.py's flag first, then intrinsic.py's): no value;
      ``basis`` names the yardstick and ``book_value_tests`` / ``reit_tests`` / ``utility_tests`` is
      copied from intrinsic.py.
    - ``CURRENCY_MISMATCH`` (inputs.py: the statements are in another currency than the price): no
      value and no return, basis None; dcf.py is not run. With a ``DCF_NOT_MEANINGFUL_FOR_…`` flag
      the yardstick basis stays and the note says both.
    - ``NEGATIVE_FCF``: no value, basis None.
    - ``CYCLICAL``: basis ``normalized``; ``base`` is dcf.py on intrinsic.py's
      ``normalized.dcf_input_mid_cycle`` (one value; bear and bull are None).
    - otherwise basis ``dcf``: dcf.py on the three ``dcf_scenarios``.

    ``irr_5y`` is returns.py's ``convergence`` return on ``base`` at today's price. Detail keys:
    ``price``, ``scenarios`` ({name: {fair_value_per_share, terminal_value_share_of_ev, implied,
    irr}}), ``cost_of_equity``, ``dividend_yield``, the copied tests and ``ddm_input``.
    """
    run = run or _run
    out: dict[str, Any] = {"basis": None, "bear": None, "base": None, "bull": None, "irr_5y": None, "note": None}
    in_codes, x_codes = _codes(inputs), _codes(intrinsic)
    tests = {key: block for key in ("book_value_tests", "reit_tests", "utility_tests") if (block := _dig(intrinsic, "buffett", key))}
    price = _num(_dig(inputs, "dcf_input", "current_share_price"))
    out["price"] = price

    special = next((c for c in [*in_codes, *x_codes] if c.startswith("DCF_NOT_MEANINGFUL_FOR_")), None)
    if special is None and inputs is None:
        suffix = _TYPE_SUFFIX.get(str(_dig(intrinsic, "inputs", "business_type")))
        special = f"DCF_NOT_MEANINGFUL_FOR_{suffix}" if suffix else None
    if special:
        basis, key = _YARDSTICKS.get(special.rsplit("_", 1)[-1], (None, None))
        out["basis"] = basis
        out.update(tests)
        if _dig(inputs, "ddm_input"):
            out["ddm_input"] = inputs["ddm_input"]
        out["note"] = f"{special}: no cash-flow DCF value for this kind of business. Judge it on {key} (from intrinsic.py), then P/E and P/B against peers."
        if key not in tests:
            out["note"] += f" {key} is absent: intrinsic.py did not run, or its SIC-code business type differs from Yahoo's sector; rerun intrinsic-inputs.py with --business-type."
        if CURRENCY_FLAG in in_codes:
            out["note"] += f" {_currency_note(inputs)}"
        return out
    if inputs is None:
        out["note"] = "inputs.py did not run, so there is no DCF input"
        return out
    if CURRENCY_FLAG in in_codes:
        out["note"] = _currency_note(inputs)
        return out
    if "NEGATIVE_FCF" in in_codes:
        out.update(tests)
        out["note"] = "NEGATIVE_FCF: free cash flow to the firm is not positive, so a DCF on it has no meaning. Value it in the deep model or on multiples."
        return out

    notes: list[str] = []

    def dcf(payload: Any) -> dict | None:
        if not isinstance(payload, dict) or any(payload.get(k) is None for k in ("fcf0", "wacc", "shares_outstanding", "net_debt")):
            return None
        data, err = _result(run("dcf.py", [], stdin=json.dumps(payload), timeout=_TIMEOUT))
        if err:
            notes.append(f"dcf.py rejected an input ({err})")
            return None
        return data

    scenarios: dict[str, dict] = {}
    for name in ("bear", "base", "bull"):
        res = dcf(_dig(inputs, "dcf_scenarios", name))
        if res is None and name == "base":
            res = dcf(inputs.get("dcf_input"))
        if res is not None:
            scenarios[name] = {k: res.get(k) for k in ("fair_value_per_share", "terminal_value_share_of_ev", "implied")}

    mid = None
    if "CYCLICAL" in in_codes:
        mid_input = _dig(intrinsic, "normalized", "dcf_input_mid_cycle")
        if isinstance(mid_input, dict) and (_num(mid_input.get("fcf0")) or 0) > 0:
            mid = dcf(mid_input)
        if mid is None:
            notes.append("CYCLICAL, but intrinsic.py gave no positive mid-cycle input; the values are on inputs.py's average-margin cash flow")
    if mid is not None:
        out["basis"] = "normalized"
        out["base"] = mid.get("fair_value_per_share")
        scenarios["mid_cycle"] = {k: mid.get(k) for k in ("fair_value_per_share", "terminal_value_share_of_ev", "implied")}
        notes.insert(0, "CYCLICAL: base is the mid-cycle value (dcf.py on intrinsic.py's ten-year average owner earnings, grown at terminal growth, "
                        "discounted at its floor rate); one value, so bear and bull are null. The bear/base/bull scenarios on inputs.py's average-margin cash flow are under scenarios.")
        if "CYCLE_BASE_SPLIT" in in_codes:
            notes.append("CYCLE_BASE_SPLIT: normalized and latest-year cash flow differ more than 2x; never present one base value alone")
    elif "base" in scenarios:
        out["basis"] = "dcf"
        for name in ("bear", "base", "bull"):
            out[name] = _dig(scenarios, name, "fair_value_per_share")
    else:
        notes.append("no DCF value: inputs.py could not fill fcf0, wacc, net debt or the share count")
    out["scenarios"] = scenarios

    cost = _num(_dig(inputs, "assumptions", "cost_of_equity", "value"))
    if cost is None:
        cost = _num(_dig(inputs, "dcf_input", "wacc"))
        if cost is not None:
            notes.append("cost of equity is null; the return uses the WACC instead")
    dividend0 = _num(_dig(inputs, "ddm_input", "dividend0"))
    dividend_yield = round(dividend0 / price, 4) if dividend0 and price else 0.0
    out["cost_of_equity"], out["dividend_yield"] = cost, dividend_yield
    names = ["mid_cycle", *("bear", "base", "bull")] if out["basis"] == "normalized" else ["bear", "base", "bull"]
    wanted = [{"name": n, "fair_value": scenarios[n]["fair_value_per_share"], "cost_of_equity": cost, "dividend_yield": dividend_yield}
              for n in names if _num(_dig(scenarios, n, "fair_value_per_share")) is not None]
    if out["basis"] and price and cost is not None and wanted:
        req = {"mode": "convergence", "price": price, "horizon": 5, "hurdle": 0.10, "scenarios": wanted}
        data, err = _result(run("returns.py", [], stdin=json.dumps(req), timeout=_TIMEOUT))
        if err:
            notes.append(f"returns.py gave no return ({err})")
        else:
            for row in data.get("scenarios") or []:
                if row.get("name") in scenarios:
                    scenarios[row["name"]]["irr"] = row.get("irr")
            out["irr_5y"] = _dig(scenarios, "mid_cycle" if out["basis"] == "normalized" else "base", "irr")
    elif out["basis"]:
        notes.append("no return at today's price: the price or the cost of equity is missing")
    if out["basis"] == "dcf":
        notes.insert(0, "dcf.py on inputs.py's three dcf_scenarios (growth fading to terminal growth from below, at and above the historical rate); "
                        "irr_5y is the annualized return if the price closes on base in 5 years (returns.py, convergence). Untested defaults: challenge them.")
    out["note"] = " ".join(notes) or None
    return out


def _flag_message(obj: Any, code: str) -> str | None:
    for flag in (obj or {}).get("flags") or [] if isinstance(obj, dict) else []:
        if isinstance(flag, dict) and flag.get("code") == code:
            return str(flag.get("message") or "") or None
    return None


def _currency_note(inputs: Any) -> str:
    detail = _flag_message(inputs, CURRENCY_FLAG) or "the statements are in another currency than the price"
    return (f"{CURRENCY_FLAG}: {detail.rstrip('.')}. No quick value and no return: a DCF on these cash flows is in the statements' currency "
            "(for an ADR, per ordinary share), not the price's.")


def thin_edgar_note(edgar_out: Any) -> str | None:
    """Why ``edgar.json`` is thin, or None when it has annual rows and a 10-K (or was not built)."""
    if not isinstance(edgar_out, dict):
        return None
    annual, filings = edgar_out.get("annual"), edgar_out.get("filings")
    lacks = []
    if not (isinstance(annual, list) and annual):
        lacks.append("no annual rows")
    if isinstance(filings, dict) and "latest_10k" in filings and not filings["latest_10k"]:
        lacks.append("no 10-K in the filing index")
    if not lacks:
        return None
    who = f"this registrant (CIK {edgar_out['cik']})" if edgar_out.get("cik") else "this registrant"
    return (f"edgar.json has {' and '.join(lacks)} for {who}. The filings may sit under a predecessor registrant (a holding-company reorganisation gives the successor a new CIK), "
            "or the company is a foreign filer with a 20-F or 40-F. The SEC annual table, the intrinsic checks, the red-flag passages and the 10-K text are missing or empty, "
            "and any quick value rests on Yahoo's statements alone, unchecked against SEC data. Find the earlier 10-K (the 8-K12B or the company's filing list names the predecessor) "
            "and read it with filing.py --url before relying on this pack.")


def _result(res: tuple[int, Any, str]) -> tuple[dict, str | None]:
    rc, data, err = res
    if rc == 0 and isinstance(data, dict) and "error" not in data:
        return data, None
    return {}, (data.get("error") if isinstance(data, dict) else None) or err.strip() or f"exit {rc}"


# ── forensic checks ─────────────────────────────────────────────────────────


def _growth(new: float | None, old: float | None) -> float | None:
    return round(new / old - 1, 4) if new is not None and old is not None and old > 0 else None


def _balance_check(rows: list[dict], days_key: str, label: str) -> dict:
    """A balance (receivables from DSO, inventory from DIO) growing against revenue."""
    def balance(row: dict) -> float | None:
        days, revenue = _num(row.get(days_key)), _num(row.get("revenue"))
        base = revenue
        if days_key == "dio" and revenue is not None and _num(row.get("gross_profit")) is not None:
            base = revenue - float(row["gross_profit"])
        return days * base / 365 if days is not None and base is not None else None

    by_year = []
    for prev, row in zip([None, *rows[:-1]], rows):
        by_year.append({"fiscal_year": row.get("fiscal_year"), days_key: _num(row.get(days_key)), "balance_estimate": (round(b, 2) if (b := balance(row)) is not None else None),
                        "balance_growth": _growth(balance(row), balance(prev)) if prev else None,
                        "revenue_growth": _growth(_num(row.get("revenue")), _num(prev.get("revenue"))) if prev else None})

    def trips(bal: float | None, rev: float | None) -> bool:
        return bal is not None and rev is not None and bal > max(_RECEIVABLE_MULTIPLE * rev, _BALANCE_FLOOR)

    latest = by_year[-1] if by_year else {}
    span = rows[-4:] if len(rows) >= 2 else []
    span_balance = _growth(balance(span[-1]), balance(span[0])) if span else None
    span_revenue = _growth(_num(span[-1].get("revenue")), _num(span[0].get("revenue"))) if span else None
    latest_trips, span_trips = trips(latest.get("balance_growth"), latest.get("revenue_growth")), trips(span_balance, span_revenue)
    return {
        "rule": f"finding when the {label} balance grew more than {_RECEIVABLE_MULTIPLE}x revenue growth (and more than {_BALANCE_FLOOR:.0%}) in the latest year or over the last "
                f"{max(len(span) - 1, 0)} years; the balance is rebuilt from {days_key.upper()} x {'cost of sales' if days_key == 'dio' else 'revenue'} / 365",
        "by_year": by_year,
        "span": {"years": max(len(span) - 1, 0), "balance_growth": span_balance, "revenue_growth": span_revenue},
        "finding": bool(latest_trips or span_trips),
        "detail": ("latest year" if latest_trips else "") + (" and " if latest_trips and span_trips else "") + (f"last {len(span) - 1} years" if span_trips else "") or None,
    }


def forensic_checks(annual: list[dict] | None) -> dict:
    """The Forensic accountant's arithmetic checks from edgar.py's annual table (oldest first), each
    with ``rule``, ``by_year`` and ``finding``. Thresholds follow the Forensic table in the valuation
    skill's ``references/deep-roles.md``; the stock-pay rule is this module's (the table asks only for
    the level and the trend). A check with no data has ``finding`` false and empty ``by_year``."""
    rows = [r for r in (annual or []) if isinstance(r, dict)][-6:]

    cash_rows = []
    for r in rows:
        ni, ocf = _num(r.get("net_income")), _num(r.get("operating_cash_flow"))
        cash_rows.append({"fiscal_year": r.get("fiscal_year"), "net_income": ni, "operating_cash_flow": ocf,
                          "net_income_above_cash": (ni > ocf) if ni is not None and ocf is not None else None})
    above = sum(1 for r in cash_rows[-3:] if r["net_income_above_cash"])
    earnings = {"rule": "finding when net income is above operating cash flow in two or more of the last three years",
                "by_year": cash_rows, "years_above_of_last_3": above, "finding": above >= 2}

    pay_rows = []
    for r in rows:
        sbc, rev, ocf = _num(r.get("sbc")), _num(r.get("revenue")), _num(r.get("operating_cash_flow"))
        pay_rows.append({"fiscal_year": r.get("fiscal_year"), "sbc": sbc,
                         "share_of_revenue": round(sbc / rev, 4) if sbc is not None and rev else None,
                         "share_of_operating_cash_flow": round(sbc / ocf, 4) if sbc is not None and ocf and ocf > 0 else None})
    span = [r for r in pay_rows[-4:] if r["share_of_revenue"] is not None]
    rev_rise = round(span[-1]["share_of_revenue"] - span[0]["share_of_revenue"], 4) if len(span) >= 2 else None
    ocf_span = [r for r in pay_rows[-4:] if r["share_of_operating_cash_flow"] is not None]
    ocf_rise = round(ocf_span[-1]["share_of_operating_cash_flow"] - ocf_span[0]["share_of_operating_cash_flow"], 4) if len(ocf_span) >= 2 else None
    stock_pay = {"rule": "level and trend of stock-based compensation; finding when its share of revenue rose more than 0.5 point or its share of operating cash flow more than 5 points over the last three years",
                 "by_year": pay_rows, "change_in_share_of_revenue": rev_rise, "change_in_share_of_operating_cash_flow": ocf_rise,
                 "finding": bool((rev_rise is not None and rev_rise > 0.005) or (ocf_rise is not None and ocf_rise > 0.05))}

    return {
        "source": "edgar.json annual table (SEC XBRL company facts)",
        "checks": {"earnings_vs_cash": earnings, "receivables": _balance_check(rows, "dso", "receivables"),
                   "inventory": _balance_check(rows, "dio", "inventory"), "stock_pay": stock_pay},
        "not_covered": [
            "deferred revenue against revenue: not in the annual table; read the balance sheet in filings/10k-item8.txt",
            "capitalized costs and accounting changes: redflags.json (capitalized, change in accounting) and filings/10k-item8-diff.txt",
            "non-GAAP gap: the releases/ files",
            "auditor, controls and related parties: redflags.json and filings/10k-item9a.txt",
            "one-offs that recur: filings/10k-item7.txt and filings/10k-item8.txt",
        ],
    }


# ── text files ──────────────────────────────────────────────────────────────


def _header(data: dict, what: str) -> str:
    return (f"{data.get('company') or data.get('symbol') or ''} {data.get('form') or ''} filed {data.get('filing_date') or 'unknown date'}: {what}\n"
            f"Source: {data.get('url') or 'unknown'}\n")


def _item_text(data: dict, max_chars: int) -> str:
    text = data.get("text") or ""
    cut = f"TRUNCATED at {max_chars} characters: the Item is longer. Read the rest with filing.py --search or --url." if data.get("truncated") else "complete"
    return f"{_header(data, 'Item ' + str(data.get('item')) + ' ' + str(data.get('title') or ''))}{len(text)} characters, {cut}\n{'-' * 72}\n{text}\n"


def _diff_text(data: dict) -> str:
    prev = data.get("previous") or {}
    added, removed = data.get("added_sentences") or [], data.get("removed_sentences") or []
    lines = [_header(data, f"Item {data.get('item')} {data.get('title') or ''} against the previous filing").rstrip("\n"),
             f"Previous filing: {prev.get('filing_date')} {prev.get('url') or ''}",
             f"Words: {data.get('previous_words')} before, {data.get('current_words')} now ({data.get('word_delta'):+} words); similarity {data.get('similarity')}"
             if isinstance(data.get("word_delta"), (int, float)) else f"Words: {data.get('previous_words')} before, {data.get('current_words')} now",
             f"Sentences added: {data.get('added_count', len(added))} ({len(added)} shown). Sentences removed: {data.get('removed_count', len(removed))} ({len(removed)} shown).",
             "-" * 72, "ADDED (in the latest filing, not in the previous one)"]
    lines += [f"+ {s}" for s in added] or ["(none)"]
    lines += ["", "REMOVED (in the previous filing, not in the latest one)"]
    lines += [f"- {s}" for s in removed] or ["(none)"]
    return "\n".join(lines) + "\n"


def _hits_text(data: dict, why: str, max_chars: int) -> str:
    """filing.py's search hits as text, in document order, cut at ``max_chars``."""
    hits = [h for h in data.get("hits") or [] if isinstance(h, dict) and h.get("snippet")]
    out = f"{_header(data, 'passages around ' + repr(str(data.get('query') or '')))}{why}\n{data.get('count')} hits in the filing, {len(hits)} below\n"
    for h in sorted(hits, key=lambda h: int(h.get("position") or 0)):
        block = f"{'-' * 72}\n[Item {h.get('item')}, position {h.get('position')}]\n{h['snippet']}\n"
        if len(out) + len(block) > max_chars:
            out += f"{'-' * 72}\n[cut at {max_chars} characters]\n"
            break
        out += block
    return out


def _windows(text: str, term: str, context: int) -> list[dict]:
    """Merged windows of ``context`` characters each side of every ``term`` in ``text``: [{start, end, hits}]."""
    out: list[dict] = []
    low, needle, at = text.lower(), term.lower(), 0
    while (at := low.find(needle, at)) != -1:
        a, b = max(0, at - context), min(len(text), at + len(needle) + context)
        if out and a <= out[-1]["end"]:
            out[-1]["end"], out[-1]["hits"] = b, out[-1]["hits"] + 1
        else:
            out.append({"start": a, "end": b, "hits": 1})
        at += len(needle)
    return out


def _passages_text(data: dict, max_chars: int, item8: str | None = None, label: str = "Item 8") -> str:
    """The passages around a search term as text, cut at ``max_chars``.

    filing.py returns only the first 20 hits in document order, which a long filing spends before it
    reaches the notes. So when the Item 8 text is at hand the passages are cut from it instead: the
    windows around every hit, overlapping ones merged, the densest kept first (the segment note says
    "segment" far more often than any other page) and printed in document order. Without Item 8 the
    script's own hits are printed, Item 8's first."""
    term = str(data.get("query") or "")
    by_item = ", ".join(f"Item {k}: {v}" for k, v in (data.get("by_item") or {}).items()) or "none"
    head = f"{_header(data, 'passages around ' + repr(term))}{data.get('count')} hits in the filing ({by_item})\n"
    blocks: list[tuple[int, str]] = []  # (rank, text)
    windows = _windows(item8, term, SEGMENT_CONTEXT) if item8 and term else []
    if windows:
        head += f"Passages below: {label} only, {len(windows)} merged windows, the densest kept first within {max_chars} characters, printed in document order\n"
        for w in windows:
            w["density"] = w["hits"] / max(1, w["end"] - w["start"])
        keep, used = [], len(head)
        for w in sorted(windows, key=lambda w: (-w["hits"], -w["density"], w["start"])):
            size = w["end"] - w["start"] + 120
            if used + size > max_chars:
                continue
            keep.append(w)
            used += size
        if not keep:  # one window larger than the limit: its head
            w = max(windows, key=lambda w: w["hits"])
            keep = [{**w, "end": w["start"] + max(0, max_chars - len(head) - 200)}]
        for w in sorted(keep, key=lambda w: w["start"]):
            blocks.append((w["start"], f"{'-' * 72}\n[{label}, characters {w['start']}-{w['end']}, {w['hits']} hits]\n{item8[w['start']:w['end']]}\n"))
        left = len(windows) - len(keep)
        tail = f"{'-' * 72}\n[{left} more windows left out: search the source file for the rest]\n" if left else ""
        return head + "".join(b for _, b in blocks) + tail
    hits = [h for h in data.get("hits") or [] if isinstance(h, dict) and h.get("snippet")]
    hits.sort(key=lambda h: (str(h.get("item")) != "8", str(h.get("item")), int(h.get("position") or 0)))
    head += f"Passages below: the first {len(hits)} hits filing.py returned, Item 8 first (overlapping windows merged)\n"
    body, used, prev = [], len(head), None
    for h in hits:
        pos, snippet = int(h.get("position") or 0), str(h["snippet"])
        start = max(0, pos - SEGMENT_CONTEXT)
        if prev and prev["item"] == h.get("item") and start < prev["end"]:
            snippet = snippet[prev["end"] - start:]
            block = snippet
        else:
            block = f"\n{'-' * 72}\n[Item {h.get('item')}, position {pos}]\n{snippet}"
        prev = {"item": h.get("item"), "end": max(start + len(str(h['snippet'])), prev["end"] if prev and prev["item"] == h.get("item") else 0)}
        if used + len(block) > max_chars:
            body.append(f"\n{'-' * 72}\n[cut at {max_chars} characters]")
            break
        body.append(block)
        used += len(block)
    return head + "".join(body).lstrip("\n") + "\n"


def _size(path: Path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return "-"
    return f"{n} B" if n < 1024 else (f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB")


_HOLDS = {
    "edgar.json": "SEC XBRL financials: 10-year annual table (margins, returns, DSO, DIO, stock pay), 12 quarters, TTM, growth, quality checklist, filing index with links, the last 5 Form 4s",
    "fundamentals.json": "Yahoo profile and statements (info: market cap, debt, cash, analyst count; statements in absolute currency)",
    "inputs.json": "inputs.py: filled dcf.py and ddm.py inputs, the three dcf_scenarios, every assumption with its source, flags",
    "intrinsic-inputs.json": "intrinsic-inputs.py: the EDGAR annual table, price, AAA and 10-year yields, business type from the SIC code",
    "intrinsic.json": "intrinsic.py: Graham and Buffett arithmetic, owner earnings, normalized (mid-cycle) earnings, book_value_tests / reit_tests / utility_tests",
    "quick_value.json": "Quick value range (dcf.py on the scenarios, returns.py convergence) or the business-type yardstick; see its basis and note",
    "sentiment.json": "Yahoo news with dates, FINRA short-sale volume, and analysts: price targets, rating counts, rating actions (180 days), EPS and revenue estimates. Analyst targets and consensus come from here, never a search",
    "earnings.json": "Index of the earnings releases (8-K Item 2.02): filing date, source URL and the releases/ file holding each text",
    "redflags.json": "10-K passages for each red-flag term: count, hits by Item and the first snippets. A hit is a passage to read (auditor boilerplate matches too), not a finding",
    "filings/10k-items.json": "The Items found in the latest 10-K with their sizes",
    "filings/10k-item1.txt": "10-K Item 1, Business",
    "filings/10k-item1a.txt": "10-K Item 1A, Risk Factors",
    "filings/10k-item7.txt": "10-K Item 7, MD&A",
    "filings/10k-item8.txt": "10-K Item 8, financial statements and notes (segment note, accounting policies, debt, leases)",
    "filings/10k-item9a.txt": "10-K Item 9A, Controls and Procedures",
    FULL_TEXT: "The part of the 10-K that the Items listed under Missing only point to (a cross-reference index, or statements placed after the exhibits), in one file",
    "filings/10k-item1a-diff.txt": "Risk-factor sentences added and removed since the previous 10-K",
    "filings/10k-item8-diff.txt": "Financial-statement and note sentences added and removed since the previous 10-K",
    TENQ_STATEMENTS: "Latest 10-Q Part I Item 1, financial statements and notes: the latest quarter-end balance sheet, for the claims",
    "filings/10q-item2.txt": "Latest 10-Q Item 2, MD&A",
    "filings/segment-note.txt": "10-K passages around 'segment' (3,000 characters each side), cut from Item 8 where the segment note sits, the densest first",
    "forensic-checks.json": "Computed checks: net income against operating cash flow, receivables and inventory against revenue, stock pay; each with finding true/false and its rule",
}


def _index(pack: dict, out_dir: Path, notes: dict[str, str]) -> str:
    s, qv = pack["summary"], pack["summary"]["quick_value"]
    fmt = lambda v, spec=",.2f": "n/a" if v is None else format(v, spec)  # noqa: E731
    lines = [f"# Research pack: {pack['symbol']} ({s.get('company') or 'company name unavailable'})", "",
             f"Level `{pack['level']}`, built {pack['as_of']}. Everything below is already fetched: read the file instead of running a script, "
             "and do not run `--help` (the commands are at the end). Run a script only for what the pack lacks: an older filing, a competitor, another search term.", "",
             *(line for code, message in (s.get("flag_notes") or {}).items() for line in (f"**Warning, `{code}`:** {message.removeprefix(code + ': ')}", "")),
             "## Headline figures", "",
             f"- Price {fmt(s.get('price'))}, market cap {fmt(s.get('market_cap'), ',.0f')}, business type {s.get('business_type') or 'n/a'}"]
    if qv.get("basis") in ("dcf", "normalized"):
        lines.append(f"- Quick value (basis `{qv['basis']}`): bear {fmt(qv.get('bear'))} / base {fmt(qv.get('base'))} / bull {fmt(qv.get('bull'))} per share; "
                     f"5-year annualized return at today's price {fmt(qv.get('irr_5y'), '.1%')}")
    else:
        lines.append(f"- Quick value: no cash-flow DCF value (basis `{qv.get('basis')}`); the yardstick is in `quick_value.json`")
    if qv.get("note"):
        lines.append(f"  - {qv['note']}")
    a, ins = s.get("analysts") or {}, s.get("insiders") or {}
    lines.append(f"- Analysts (Yahoo, in `sentiment.json`): mean target {fmt(a.get('target_mean'))}, {a.get('count') if a.get('count') is not None else 'n/a'} ratings this month")
    lines.append(f"- Insiders, last 5 Form 4 filings: {ins.get('buys')} open-market buys, {ins.get('sells')} open-market sales (transaction counts; grants and tax withholding left out)")
    hits = s.get("red_flag_hits") or {}
    lines.append("- Red-flag terms in the 10-K (passages to read, not findings): " + (", ".join(f"\"{t}\" {n}" for t, n in hits.items()) or "not searched"))
    lines.append("- Flags from inputs.py, intrinsic.py and the pack: " + (", ".join(f"`{c}`" for c in s.get("flags") or []) or "none"))
    lines += ["", "## Files", "", "| File | Size | Holds |", "|---|---|---|"]
    for name, entry in pack["files"].items():
        if not entry["ok"] and not Path(entry["path"]).is_file():
            continue
        holds = _HOLDS.get(name) or ("Earnings release (8-K Exhibit 99.1) filed " + Path(name).stem[:10] if name.startswith("releases/") else "")
        extra = f" **{notes[name]}**" if notes.get(name) else ""
        lines.append(f"| `{name}` | {_size(Path(entry['path']))} | {holds}{extra} |")
    lines += ["", "## Missing", ""]
    if pack["missing"]:
        lines += [f"- `{name}`: {pack['files'][name].get('error') or 'not built'}" for name in pack["missing"]]
        lines.append("")
        lines.append("Say in your findings which of these your role needed and could not replace.")
    else:
        lines.append("Nothing: every source answered.")
    py, sym = shlex.quote(sys.executable), pack["symbol"]
    q = lambda name: shlex.quote(str(SCRIPTS[name]))  # noqa: E731
    lines += ["", "## Script commands", "", "Resolved for this machine; copy them as they are.", "", "```bash",
              f"{py} {q('edgar.py')} {sym} [--years N] [--quarters N] [--form4 [N]] [--filings-only] [--as-of YYYY-MM-DD]",
              f"{py} {q('filing.py')} {sym} [--form 10-K|10-Q|8-K|DEF 14A]          # lists the Items found",
              f"{py} {q('filing.py')} {sym} [--form FORM] --item ITEM [--max-chars N]  # one Item's text (default cut 20000)",
              f"{py} {q('filing.py')} {sym} [--form FORM] --item ITEM --diff          # against the previous filing of the form",
              f"{py} {q('filing.py')} {sym} [--form FORM] --search TERM [--context N] # passages around a term (first 20 hits)",
              f"{py} {q('filing.py')} --url URL [--item ITEM | --search TERM]         # an older filing, by a URL from edgar.json's index",
              f"{py} {q('earnings.py')} {sym} [--last N] [--max-chars N]",
              f"{py} {q('fundamentals.py')} {sym} [--quarterly]",
              f"{py} {q('sentiment.py')} SYM[,SYM...] [--days 20] [--news-days 30] [--news 10]",
              f"{py} {q('inputs.py')} {sym} [--erp RATE --erp-date YYYY-MM-DD]",
              f"{py} {q('dcf.py')} < input.json",
              f"{py} {q('returns.py')} < input.json",
              f"{py} {q('model.py')} < model.json",
              "```", "",
              "SEC data comes only through these scripts. Other tickers work the same way: replace the symbol.", ""]
    return "\n".join(lines)


# ── build ───────────────────────────────────────────────────────────────────


def build(symbol: str, out_dir: Path, level: str = "card", workers: int = 4) -> dict:
    """Build the research pack for ``symbol`` into ``out_dir`` and return ``pack.json``'s content:

    {"symbol", "requested", "as_of", "level", "dir", "index": "<out_dir>/INDEX.md",
     "files": {"<name>": {"path", "ok", "error"?}}, "missing": ["<name>", ...],
     "summary": {"company", "price", "market_cap", "business_type", "flags": [codes],
                 "flag_notes": {"<code>": "<message>"},
                 "quick_value": {"basis", "bear", "base", "bull", "irr_5y", "note"},
                 "analysts": {"target_mean", "count"}, "red_flag_hits": {"<term>": n},
                 "insiders": {"buys", "sells"}}}

    ``symbol`` is the dash form every script was run with (``BRK-B``); ``requested`` is what was
    asked for (``BRK.B``). ``flags`` holds inputs.py's and intrinsic.py's codes and the pack's own
    ``THIN_EDGAR_HISTORY``; ``flag_notes`` gives the message of ``CURRENCY_MISMATCH`` and
    ``THIN_EDGAR_HISTORY`` when they fired (else it is empty).

    ``files`` names every file the level calls for, relative to ``out_dir`` (``releases/<filing
    date>.txt`` once per release that has text); ``missing`` lists those with ``ok`` false, in the
    same order. ``insiders`` counts open-market purchase (P) and sale (S) transactions in the last
    five Form 4 filings. Raises InvalidInput for a bad symbol or level or a ticker the SEC does not
    list, ConfigError when a script exits 4; anything else that fails is in ``missing``.
    """
    if level not in LEVELS:
        raise InvalidInput(f"level must be one of {', '.join(LEVELS)}, got {level!r}")
    requested = brokerage.validate_symbol(symbol)
    sym = canonical_symbol(requested)
    out_dir = Path(out_dir)
    deep = level == "deep"
    for sub in ("", "releases", *(("filings",) if deep else ())):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    files: dict[str, dict] = {}
    notes: dict[str, str] = {}
    data: dict[str, Any] = {}

    written: set[str] = set()

    def write(name: str, text: str) -> None:
        (out_dir / name).write_text(text)
        written.add(name)

    def record(name: str, error: str | None = None) -> None:
        if error and name not in written:  # a file left by an earlier build of this folder would pass for this one's
            (out_dir / name).unlink(missing_ok=True)
        files[name] = {"path": str(out_dir / name), "ok": error is None, **({"error": error} if error else {})}

    def save_json(name: str, obj: Any, error: str | None = None) -> None:
        if obj is not None and (error is None or name == "edgar.json"):
            write(name, json.dumps(obj, indent=2, default=str) + "\n")
        record(name, error)

    def json_job(name: str, script: str, args: list[str]) -> None:
        obj, err = _call(script, args)
        data[name] = None if err else obj
        save_json(name, obj, err)

    # 1. edgar.py alone: it validates the ticker and fills the cache the others read.
    try:
        obj, err = _call("edgar.py", [sym, "--years", "10", "--quarters", "12", "--form4", "5"])
        if err and "SEC ticker list" in err:
            raise InvalidInput(obj.get("error") if isinstance(obj, dict) and obj.get("error") else err)
        if err:  # e.g. a foreign filer with no us-gaap facts: keep the filing index
            fallback, err2 = _call("edgar.py", [sym, "--filings-only", "--form4", "5"])
            if err2 and "SEC ticker list" in err2:
                raise InvalidInput(err2)
            data["edgar.json"] = fallback if not err2 else None
            save_json("edgar.json", data["edgar.json"], f"{err}{'; filing index only' if not err2 else ''}")
        else:
            data["edgar.json"] = obj
            save_json("edgar.json", obj)
    except _Stop as stop:
        raise _config_error(stop) from None

    terms = RED_FLAG_TERMS[level]
    searches: dict[str, tuple[Any, str | None]] = {}
    warm: dict[str, str | None] = {"error": None}

    def intrinsic_job() -> None:
        obj, err = _call("intrinsic-inputs.py", [sym])
        data["intrinsic-inputs.json"] = None if err else obj
        save_json("intrinsic-inputs.json", obj, err)
        if err or not isinstance(obj.get("intrinsic_input"), dict):
            record("intrinsic.json", f"needs intrinsic-inputs.json ({err or 'no intrinsic_input in it'})")
            return
        res, err = _call("intrinsic.py", [], stdin=json.dumps(obj["intrinsic_input"]))
        data["intrinsic.json"] = None if err else res
        save_json("intrinsic.json", res, err)

    def earnings_job() -> None:
        args = [sym, "--last", "12", "--max-chars", "40000"] if deep else [sym, "--last", "8"]
        obj, err = _call("earnings.py", args)
        if err:
            record("earnings.json", err)
            return
        used: set[str] = set()
        rows = []
        for stale in (out_dir / "releases").glob("*.txt"):
            stale.unlink(missing_ok=True)
        for rel in obj.get("releases") or []:
            row = {k: v for k, v in rel.items() if k != "text"}
            text = rel.get("text")
            row["file"], row["chars"] = None, len(text) if text else 0
            if text:
                stem = str(rel.get("filing_date") or "undated")
                name, n = f"releases/{stem}.txt", 1
                while name in used:
                    n += 1
                    name = f"releases/{stem}-{n}.txt"
                used.add(name)
                cut = "; cut at the pack's character limit" if rel.get("truncated") else ""
                write(name, f"Earnings release, 8-K Item 2.02 filed {rel.get('filing_date')} (Exhibit {rel.get('exhibit')}){cut}\nSource: {rel.get('url')}\n{'-' * 72}\n{text}\n")
                row["file"] = name
            rows.append(row)
        index = {**{k: v for k, v in obj.items() if k != "releases"}, "releases": rows}
        data["earnings.json"] = index
        save_json("earnings.json", index)
        for row in rows:
            if row["file"]:
                record(row["file"])
                if row.get("truncated"):
                    notes[row["file"]] = "Cut at the character limit."

    def search_job(term: str) -> None:
        searches[term] = _call("filing.py", [sym, "--search", term])

    def items_job() -> None:
        obj, err = _call("filing.py", [sym])
        warm["error"] = err
        data["filings/10k-items.json"] = None if err else obj
        save_json("filings/10k-items.json", obj, err)

    def text_job(name: str, args: list[str], render: Callable[[dict], str], min_chars: int = 0) -> None:
        obj, err = _call("filing.py", args)
        if err:
            record(name, err)
            return
        write(name, render(obj))
        body = len(obj.get("text") or "") if "--item" in args and "--diff" not in args else None
        if body is not None and body < min_chars:
            record(name, f"only {body} characters: the Item is incorporated by reference or the filing did not parse; read the filing by its URL")
        elif "hits" in obj and not obj.get("hits"):
            record(name, f"no passage contains {obj.get('query')!r}")
        else:
            record(name)
            if obj.get("truncated") and "--diff" not in args:
                notes[name] = f"Cut at {args[args.index('--max-chars') + 1]} characters; the Item is longer."

    def diffs_job(items: list[str]) -> None:  # one after the other: both fetch the previous 10-K
        for item in items:
            text_job(f"filings/10k-item{item.lower()}-diff.txt", [sym, "--item", item, "--diff"], _diff_text)

    def first_search_job() -> None:
        search_job(terms[0])
        warm["error"] = searches[terms[0]][1]

    def quick_value_job() -> None:
        inputs, intrinsic = data.get("inputs.json"), data.get("intrinsic.json")
        if inputs is None and intrinsic is None:
            data["quick_value.json"] = quick_value(None, None)
            record("quick_value.json", "needs inputs.json or intrinsic.json, and neither was built")
            return
        qv = quick_value(inputs, intrinsic)
        data["quick_value.json"] = qv
        save_json("quick_value.json", {"symbol": sym, "as_of": date.today().isoformat(), **qv})

    def yahoo_job() -> None:  # one Yahoo script at a time: four at once draws HTTP 429
        for name, script in (("fundamentals.json", "fundamentals.py"), ("inputs.json", "inputs.py"), ("sentiment.json", "sentiment.py")):
            obj, err = _yahoo_call(script, [sym])
            data[name] = None if err else obj
            save_json(name, obj, err)
            down = [c for c in _codes(obj) if c in ("NEWS_UNAVAILABLE", "ANALYSTS_UNAVAILABLE")] if not err else []
            if down:
                notes[name] = f"Yahoo did not answer for part of it ({', '.join(down)}); see its flags."
        intrinsic_job()  # its quote is a Yahoo call too

    def tenq_job() -> None:  # one after the other: both read the latest 10-Q
        text_job("filings/10q-item2.txt", [sym, "--form", "10-Q", "--item", "2", "--max-chars", str(TENQ_MAX_CHARS)], lambda o: _item_text(o, TENQ_MAX_CHARS), MIN_ITEM_CHARS)
        obj, err = _call("filing.py", [sym, "--form", "10-Q", "--item", "1", "--max-chars", str(ITEM_MAX_CHARS)])
        if err:
            record(TENQ_STATEMENTS, err)
            return
        text = obj.get("text") or ""
        if len(text) >= MIN_ITEM_CHARS and _BALANCE_SHEET.search(text):
            write(TENQ_STATEMENTS, _item_text(obj, ITEM_MAX_CHARS))
            record(TENQ_STATEMENTS)
            if obj.get("truncated"):
                notes[TENQ_STATEMENTS] = f"Cut at {ITEM_MAX_CHARS} characters; the Item is longer."
            return
        # Part II's Item 1 (Legal Proceedings) won, or Item 1 is a pointer: look for the balance sheet itself.
        why = f"Item 1 parsed as {str(obj.get('title') or 'untitled')!r} ({len(text)} characters), not the financial statements"
        # The statements often parse under another Item (the text after the contents page's last line).
        listed, _ = _call("filing.py", [sym, "--form", "10-Q"])
        rows = [r for r in (_dig(listed, "items") or []) if isinstance(r, dict) and str(r.get("item")).upper() not in ("1", "2")]
        rows.sort(key=lambda r: int(r.get("chars") or 0), reverse=True)
        for row in rows[:2]:
            if int(row.get("chars") or 0) < MIN_ITEM_CHARS:
                break
            other, other_err = _call("filing.py", [sym, "--form", "10-Q", "--item", str(row["item"]), "--max-chars", str(ITEM_MAX_CHARS)])
            if not other_err and _BALANCE_SHEET.search(other.get("text") or ""):
                write(TENQ_STATEMENTS, _item_text(other, ITEM_MAX_CHARS))
                record(TENQ_STATEMENTS)
                notes[TENQ_STATEMENTS] = f"{why}: this file holds the statements, which parsed as Item {row['item']}."
                return
        found, err = _call("filing.py", [sym, "--form", "10-Q", "--search", TENQ_STATEMENTS_TERM, "--context", str(SEGMENT_CONTEXT)])
        if err or not (found or {}).get("hits"):
            record(TENQ_STATEMENTS, f"the 10-Q's {why}, and no passage contains {TENQ_STATEMENTS_TERM!r}; read the 10-Q by its URL (the filing index in edgar.json)")
            return
        write(TENQ_STATEMENTS, _hits_text(found, f"The 10-Q's {why}.", TENQ_MAX_CHARS))
        record(TENQ_STATEMENTS)
        notes[TENQ_STATEMENTS] = f"{why}: this file holds the passages around '{TENQ_STATEMENTS_TERM}' instead."

    second: list[Callable[[], None]] = [yahoo_job, earnings_job, items_job if deep else first_search_job]
    if deep:
        second.append(tenq_job)

    def run_all(jobs: list[Callable[[], None]]) -> None:
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            for future in [pool.submit(job) for job in jobs]:
                future.result()

    item_names = [f"filings/10k-item{i.lower()}.txt" for i in ITEMS_10K]
    diff_names = [f"filings/10k-item{i.lower()}-diff.txt" for i in DIFF_ITEMS]
    ten_k_names = [*item_names, FULL_TEXT, *diff_names, "filings/segment-note.txt"] if deep else []

    def segment_job(source: str, label: str) -> None:
        text_job("filings/segment-note.txt", [sym, "--search", "segment", "--context", str(SEGMENT_CONTEXT)], lambda o: _passages_text(o, SEGMENT_NOTE_MAX_CHARS, source, label))

    def item_job(item: str, with_segment: bool) -> None:
        kept = {"text": ""}

        def render(obj: dict) -> str:
            kept["text"] = obj.get("text") or ""
            return _item_text(obj, ITEM_MAX_CHARS)

        text_job(f"filings/10k-item{item.lower()}.txt", [sym, "--item", item, "--max-chars", str(ITEM_MAX_CHARS)], render, _min_chars(item))
        if with_segment:  # the segment note is cut from Item 8's text, so it follows it
            segment_job(kept["text"], "Item 8")

    def full_job(item: str) -> None:
        kept = {"text": ""}

        def render(obj: dict) -> str:
            kept["text"] = obj.get("text") or ""
            return _item_text(obj, ITEM_MAX_CHARS)

        text_job(FULL_TEXT, [sym, "--item", item, "--max-chars", str(ITEM_MAX_CHARS)], render, MIN_ITEM_CHARS)
        notes[FULL_TEXT] = (notes.get(FULL_TEXT, "") + " Large: search it (grep, or filing.py --search) and read the part you need, never the whole file.").strip()
        segment_job(kept["text"], f"the filing body (Item {item} as parsed)")

    def plan_10k() -> list[Callable[[], None]]:
        """The 10-K reads worth making, from the Item list already fetched. An Item the filing only
        points at (a bank's "Form 10-K cross-reference index": a title and a page range) is not
        fetched; when the main Items are such stubs and one parsed Item holds the body, that one is
        written as filings/10k-full.txt instead. The same when only Item 8 is a pointer and the
        statements sit after the exhibits."""
        jobs: list[Callable[[], None]] = [(lambda t=t: search_job(t)) for t in terms]
        sizes: dict[str, int] = {}
        for row in _dig(data.get("filings/10k-items.json"), "items") or []:
            if isinstance(row, dict) and row.get("item") is not None:
                key = str(row["item"]).upper()
                sizes[key] = max(sizes.get(key, 0), int(row.get("chars") or 0))
        stubs = [i for i in ITEMS_10K if sizes.get(i, 0) < _min_chars(i)]
        # The body is the largest Item outside the ones fetched by name: a long Item 1 must not hide
        # the statements that parsed under Item 15 or 16.
        tail = [k for k in sizes if k not in ITEMS_10K]
        body = max(tail, key=lambda k: sizes[k]) if tail else None
        main_stubs = [i for i in stubs if i != "9A"]
        whole = body is not None and body not in ITEMS_10K and sizes[body] >= FULL_TEXT_MIN_CHARS and ("8" in main_stubs or len(main_stubs) >= 2)
        if whole:
            notes[FULL_TEXT] = f"Holds the text behind Item {', '.join(stubs)} (parsed as Item {body})."
        for item in ITEMS_10K:
            name = f"filings/10k-item{item.lower()}.txt"
            if item in stubs:
                why = f"the 10-K has no Item {item} as parsed" if item not in sizes else f"Item {item} is {sizes[item]} characters: a pointer to another page, not the text"
                record(name, why + (f"; the text is in {FULL_TEXT}" if whole else "; read the filing by its URL (edgar.json filings.latest_10k)"))
            else:
                jobs.append(lambda item=item: item_job(item, with_segment=item == "8"))
        diffable = [i for i in DIFF_ITEMS if i not in stubs]
        for item in DIFF_ITEMS:
            if item in stubs:
                record(f"filings/10k-item{item.lower()}-diff.txt", f"Item {item} is not a separate section in this 10-K, so there is nothing to compare")
        if diffable:
            jobs.append(lambda: diffs_job(diffable))
        if whole:
            jobs.append(lambda: full_job(body))
        elif "8" in stubs:
            jobs.append(lambda: segment_job("", ""))
        return jobs

    try:
        run_all(second)
        if warm["error"]:  # the 10-K itself is unavailable: one clear reason, not fourteen failed fetches
            reason = f"the latest 10-K could not be read ({warm['error']})"
            for name in ten_k_names:
                if name != FULL_TEXT:
                    record(name, reason)
            for term in terms:
                searches.setdefault(term, (None, reason))
            run_all([quick_value_job])
        elif deep:
            run_all([quick_value_job, *plan_10k()])
        else:
            run_all([quick_value_job, *((lambda t=t: search_job(t)) for t in terms[1:])])
    except _Stop as stop:
        raise _config_error(stop) from None

    # redflags.json: one object for every term
    found = {t: r for t, (r, e) in searches.items() if e is None and isinstance(r, dict)}
    first = next(iter(found.values()), {})
    red = {"symbol": sym, "form": first.get("form"), "filing_date": first.get("filing_date"), "url": first.get("url"),
           "note": "A hit is a passage to read, not a finding: auditor and controls boilerplate uses these words too.",
           "terms": {t: ({"count": found[t].get("count"), "by_item": found[t].get("by_item") or {}, "hits": [{"item": h.get("item"), "snippet": h.get("snippet")} for h in (found[t].get("hits") or [])[:RED_FLAG_HITS_KEPT]]}
                         if t in found else {"error": searches.get(t, (None, "not searched"))[1]}) for t in terms}}
    save_json("redflags.json", red, None if found else f"no red-flag search ran ({searches.get(terms[0], (None, 'not searched'))[1]})")

    if deep:
        annual = _dig(data.get("edgar.json"), "annual")
        if isinstance(annual, list) and annual:
            save_json("forensic-checks.json", forensic_checks(annual))
        else:
            record("forensic-checks.json", "needs the annual table in edgar.json")

    order = ["edgar.json", "fundamentals.json", "inputs.json", "intrinsic-inputs.json", "intrinsic.json", "quick_value.json", "sentiment.json", "earnings.json",
             *sorted((n for n in files if n.startswith("releases/")), reverse=True), "redflags.json"]
    if deep:
        order += ["filings/10k-items.json", *item_names, FULL_TEXT, *diff_names, TENQ_STATEMENTS, "filings/10q-item2.txt", "filings/segment-note.txt", "forensic-checks.json"]
    files = {name: files[name] for name in order if name in files}

    edgar_out, fundamentals, inputs = data.get("edgar.json") or {}, data.get("fundamentals.json") or {}, data.get("inputs.json")
    qv = data.get("quick_value.json") or {}
    analysts = _dig(data.get("sentiment.json"), "symbols", sym, "analysts") or {}
    trades = [str(t.get("code")) for f in (_dig(edgar_out, "form4", "filings") or []) if isinstance(f, dict) for t in f.get("transactions") or [] if isinstance(t, dict)]
    price = _num(_dig(inputs, "dcf_input", "current_share_price"))
    if price is None:
        price = _num(_dig(fundamentals, "info", "current_price"))
    if price is None:
        price = _num(_dig(data.get("intrinsic-inputs.json"), "intrinsic_input", "price"))
    flag_codes = _codes(inputs, data.get("intrinsic-inputs.json"), data.get("intrinsic.json"))
    flag_notes: dict[str, str] = {}
    if CURRENCY_FLAG in flag_codes:
        flag_notes[CURRENCY_FLAG] = _currency_note(inputs)
    thin = thin_edgar_note(data.get("edgar.json"))
    if thin:
        flag_codes.append(THIN_FLAG)
        flag_notes[THIN_FLAG] = thin
    pack = {
        "symbol": sym, "requested": requested, "as_of": date.today().isoformat(), "level": level, "dir": str(out_dir), "index": str(out_dir / "INDEX.md"),
        "files": files, "missing": [name for name, entry in files.items() if not entry["ok"]],
        "summary": {
            "company": edgar_out.get("company") or _dig(fundamentals, "info", "name") or _dig(data.get("intrinsic-inputs.json"), "company"),
            "price": price, "market_cap": _num(_dig(fundamentals, "info", "market_cap")),
            "business_type": _dig(inputs, "business_type") or _dig(data.get("intrinsic-inputs.json"), "business_type"),
            "flags": flag_codes, "flag_notes": flag_notes,
            "quick_value": {k: qv.get(k) for k in ("basis", "bear", "base", "bull", "irr_5y", "note")},
            "analysts": {"target_mean": _dig(analysts, "targets", "mean"), "count": _dig(analysts, "recommendations", "count")},
            "red_flag_hits": {t: found[t].get("count") for t in terms if t in found},
            "insiders": {"buys": trades.count("P"), "sells": trades.count("S")},
        },
    }
    (out_dir / "INDEX.md").write_text(_index(pack, out_dir, notes))
    (out_dir / "pack.json").write_text(json.dumps(pack, indent=2, default=str) + "\n")
    return pack


def _config_error(stop: _Stop) -> ConfigError:
    body = stop.data if isinstance(stop.data, dict) else {}
    extra = {k: v for k, v in body.items() if k not in ("error", "code")}
    return ConfigError(str(body.get("error") or f"{stop.script} exited 4: SEC EDGAR is not set up"), code=str(body.get("code") or "CONFIG_MISSING"), **extra)
