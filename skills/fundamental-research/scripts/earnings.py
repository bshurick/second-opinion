#!/usr/bin/env python3
"""Usage: earnings.py SYMBOL [--last N] [--max-chars N]

Earnings press releases from SEC EDGAR: the recent 8-K filings that carry Item
2.02 (Results of Operations), each with the text of its Exhibit 99.1 (the
press release), newest first, at most --last (default 8), each cut to
--max-chars (default 15000). The exhibit is the document the filing's own
index-headers file types EX-99.1, else the first EX-99.x; when that file is
missing, a filename pattern (ex/exh/exhibit + 99 + 1, not 99.10; images
skipped) and then any ex99 name. A filing with no ex99 exhibit has exhibit/text
null and a NO_EX99 flag. A filing whose index or exhibit cannot be fetched or
parsed keeps its row (text null) with a FETCH_FAILED flag naming the accession;
the other releases are kept. A company with no Item
2.02 filing returns releases [] and exit 0. Use for guidance-versus-results
track records instead of web search. Set EDGAR_USER_AGENT to "app-name
contact@email". stdin is unused.
Exit codes: 0, 2 (bad symbol or usage), 5 (EDGAR_HTTP), 6.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import filing_sections  # noqa: E402
from second_opinion import brokerage, edgar, output  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

_EX991 = re.compile(r"(?:ex|exh|exhibit)[-_.]?99(?:[-_.]?d)?[-_.]?0?1(?!\d)", re.IGNORECASE)
_EX99 = re.compile(r"(?:ex|exh|exhibit)[-_.]?99", re.IGNORECASE)
_TEXT_EXT = (".htm", ".html", ".txt")
_TYPE_99 = re.compile(r"EX-99(?:\.0*(\d+))?$", re.IGNORECASE)
_DOC = re.compile(r"<TYPE>\s*(\S+).*?<FILENAME>\s*(\S+)", re.IGNORECASE | re.DOTALL)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"earnings.py: {message}")


def _has_202(row: dict) -> bool:
    return "2.02" in [i.strip() for i in str(row.get("items") or "").split(",")]


def _pick_exhibit(names: list[str], headers: str | None = None) -> str | None:
    """Exhibit 99.1 by the filing's own document types when `headers` (the index-headers text) is given, else by filename."""
    names = [n for n in names if n.lower().endswith(_TEXT_EXT) and "index" not in n.lower()]
    if headers:
        typed = []
        for block in re.split(r"<DOCUMENT>", html.unescape(headers), flags=re.IGNORECASE)[1:]:
            m = _DOC.search(block)
            if m and m.group(2) in names and _TYPE_99.match(m.group(1)):
                typed.append((int(_TYPE_99.match(m.group(1)).group(1) or 0), m.group(2)))
        if typed:
            ones = [f for n, f in typed if n == 1]
            return ones[0] if ones else typed[0][1]
    for pattern in (_EX991, _EX99):
        for name in names:
            if pattern.search(name):
                return name
    return None


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="earnings.py", add_help=False)
        p.add_argument("symbol")
        p.add_argument("--last", type=int, default=8)
        p.add_argument("--max-chars", dest="max_chars", type=int, default=15000)
        ns = p.parse_args(args)
        if ns.last < 1 or ns.max_chars < 1:
            raise InvalidInput("--last and --max-chars must be at least 1")
        symbol = brokerage.validate_symbol(ns.symbol)
        cik, _title = edgar.cik_for(symbol)
        rows = [r for r in edgar.submissions(cik)["filings"] if str(r.get("form", "")).upper() == "8-K" and _has_202(r)]
        rows.sort(key=lambda r: str(r["filingDate"]), reverse=True)
        releases: list[dict] = []
        flags: list[dict] = []
        for row in rows[: ns.last]:
            acc = row["accessionNumber"]
            folder = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
            rel = {"filing_date": row["filingDate"], "accession": acc, "exhibit": None, "url": None, "text": None, "truncated": False}
            try:
                index = json.loads(edgar.archive(f"{folder}/index.json"))
                names = [str(i.get("name", "")) for i in (index.get("directory") or {}).get("item") or []]
                headers = None
                hname = f"{acc}-index-headers.html"
                if hname in names:
                    try:
                        headers = edgar.archive(f"{folder}/{hname}")
                    except (ApiError, ValueError, InvalidInput):
                        headers = None  # fall back to the filename pattern
                exhibit = _pick_exhibit(names, headers)
                if exhibit is None:
                    flags.append({"code": "NO_EX99", "message": f"8-K {acc} ({row['filingDate']}) lists no Exhibit 99 press release"})
                else:
                    url = f"{folder}/{exhibit}"
                    text = filing_sections.to_text(edgar.archive(url))
                    rel.update(exhibit=exhibit, url=url, truncated=len(text) > ns.max_chars, text=text[: ns.max_chars])
            except (ApiError, ValueError, InvalidInput, AttributeError, TypeError) as exc:
                flags.append({"code": "FETCH_FAILED", "message": f"8-K {acc} ({row['filingDate']}): could not read the filing ({exc})"})
            releases.append(rel)
        return {"symbol": symbol, "cik": cik, "as_of": date.today().isoformat(), "releases": releases, "flags": flags}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
