#!/usr/bin/env python3
"""Usage: holdings.py <manager> [--limit N]
       holdings.py --cik N [--limit N]
       holdings.py --search NAME
       holdings.py --list

Institutional holdings from SEC Form 13F: a manager's latest 13F-HR against
its prior quarter. <manager> is a curated alias (--list prints them: berkshire,
bridgewater, renaissance, citadel, millennium, two-sigma, de-shaw,
pershing-square, soros, baupost, appaloosa, third-point, elliott,
tiger-global, coatue, scion, ark, duquesne, lone-pine, viking), an alias
fragment, or a bare CIK; --cik N takes any filer. An unknown name is looked
up in EDGAR's company search restricted to 13F filers and returned as
`candidates` with exit 2 (code MANAGER_AMBIGUOUS) so the caller can pick a
CIK; --search NAME does only that lookup.

Holdings are summed by CUSIP across sub-managers (options kept apart as
PUT/CALL rows); the prior quarter is the newest earlier 13F-HR with a
different report_date (amendments are ignored). The diff classifies by share
count, so price moves do not masquerade as buying: new, exited, increased,
trimmed (each capped at --limit, default 25, with `truncated` counts), plus
totals, the top holdings by value with weights, and top-5/top-10
concentration. 13F covers US-listed long positions only, no shorts, no
bonds, no cash, and is filed up to 45 days after quarter end (`lag_days` is
filing date minus report date). Set EDGAR_USER_AGENT to "app-name
contact@email" as the SEC requires. stdin is unused. Exit codes: 0, 2
(bad arguments, unknown manager, no 13F filings), 5 (EDGAR_HTTP or an
unparseable table, EDGAR_13F_TABLE), 6.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import edgar, output, thirteenf  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

_UA_FLAG = {"code": "DEFAULT_USER_AGENT", "message": "set EDGAR_USER_AGENT to 'app-name contact@email' as the SEC requires; the default placeholder may be blocked"}
NOTES = [
    "13F reports US-listed long positions (and options) only: no shorts, bonds, cash or non-US holdings, so total value is not the fund's assets.",
    "Classification is by share count between report dates; value changes include price moves.",
    "Positions can be filed confidentially and appear later in an amendment, which this diff ignores.",
]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"holdings.py: {message}")


def _filing_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"


def _filing(cik: int, f: dict[str, Any]) -> dict[str, Any]:
    return {"accession": f["accession"], "filing_date": f.get("filing_date"), "report_date": f.get("report_date"), "url": _filing_url(cik, f["accession"])}


def _table(cik: int, f: dict[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        return thirteenf.parse_information_table(edgar.information_table(cik, f["accession"]))
    except ValueError as e:
        raise ApiError(f"13F filing {f['accession']} information table did not parse: {e}", code="EDGAR_13F_TABLE") from e


def _lag_days(f: dict[str, Any]) -> int | None:
    try:
        return (date.fromisoformat(f["filing_date"]) - date.fromisoformat(f["report_date"])).days
    except (KeyError, TypeError, ValueError):
        return None


def _resolve(ns: argparse.Namespace) -> tuple[int, str | None]:
    if ns.cik is not None:
        found = thirteenf.resolve_manager(str(ns.cik))
        return (ns.cik, found[1] if found else None)
    found = thirteenf.resolve_manager(ns.manager)
    if found:
        return found
    candidates = edgar.search_companies(ns.manager)
    raise InvalidInput(f"{ns.manager!r} is not a known manager alias; pick a CIK from candidates and rerun with --cik", code="MANAGER_AMBIGUOUS", candidates=candidates, query=ns.manager)


def _run(args: list[str]) -> dict[str, Any]:
    p = _Parser(prog="holdings.py", add_help=False)
    p.add_argument("manager", nargs="?")
    p.add_argument("--cik", type=int)
    p.add_argument("--search")
    p.add_argument("--list", action="store_true")
    p.add_argument("--limit", type=int, default=25)
    ns = p.parse_args(args)
    if ns.list:
        return {"managers": dict(thirteenf.MANAGERS)}
    if ns.search:
        return {"query": ns.search, "candidates": edgar.search_companies(ns.search)}
    if not ns.manager and ns.cik is None:
        raise InvalidInput("holdings.py: a manager alias, --cik N, --search NAME or --list is required")
    if not 1 <= ns.limit <= 200:
        raise InvalidInput("--limit must be between 1 and 200")
    cik, alias = _resolve(ns)
    filings = edgar.thirteen_f_filings(cik)
    if not filings:
        raise InvalidInput(f"CIK {cik} has no 13F-HR filings in its recent EDGAR index", code="NO_13F", cik=cik)
    current = filings[0]
    previous = next((f for f in filings[1:] if f.get("report_date") != current.get("report_date")), None)
    diff = thirteenf.diff_holdings(_table(cik, current), _table(cik, previous) if previous else {}, limit=ns.limit)
    flags = [_UA_FLAG] if edgar.user_agent_is_default() else []
    return {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manager": {"cik": cik, "alias": alias, "name": edgar.submissions(cik).get("name")},
        "current": _filing(cik, current),
        "previous": _filing(cik, previous) if previous else None,
        "lag_days": _lag_days(current),
        **diff,
        "flags": flags,
        "notes": NOTES,
    }


def main(argv: list[str] | None = None) -> int:
    return output.run(_run, argv)


if __name__ == "__main__":
    sys.exit(main())
