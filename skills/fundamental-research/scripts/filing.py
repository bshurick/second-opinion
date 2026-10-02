#!/usr/bin/env python3
"""Usage: filing.py [SYMBOL] [--url URL] [--form 10-K] [--item 1A] [--search TERM] [--diff] [--max-chars N] [--context N]

Read a 10-K / 10-Q from SEC EDGAR: resolves the latest filing of --form for
SYMBOL (or takes a document --url), downloads it (cached), and runs
filing_sections.py. With no --item or --search it lists the Items found;
--item returns that Item's text (truncated to --max-chars, default 20000);
--search returns passages around a term with context; --item plus --diff
compares the Item with the previous filing of the same form. Set
EDGAR_USER_AGENT to "app-name contact@email". stdin is unused.
Exit codes: 0, 2 (unknown ticker, no such filing, item not found),
5 (EDGAR_HTTP), 6.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import filing_sections  # noqa: E402
from second_opinion import brokerage, edgar, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"filing.py: {message}")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="filing.py", add_help=False)
        p.add_argument("symbol", nargs="?", default=None)
        p.add_argument("--url", default=None)
        p.add_argument("--form", default="10-K")
        p.add_argument("--item", default=None)
        p.add_argument("--search", default=None)
        p.add_argument("--diff", action="store_true")
        p.add_argument("--max-chars", dest="max_chars", type=int, default=20000)
        p.add_argument("--context", type=int, default=200)
        ns = p.parse_args(args)
        if not ns.symbol and not ns.url:
            raise InvalidInput("a symbol or --url is required")
        form = ns.form.strip().upper()
        base: dict = {"symbol": None, "cik": None, "company": None, "form": None, "filing_date": None, "url": ns.url}
        previous = None
        if ns.url:
            doc = edgar.document(ns.url)
        else:
            symbol = brokerage.validate_symbol(ns.symbol)
            cik, title = edgar.cik_for(symbol)
            subs = edgar.submissions(cik)
            matches = sorted((f for f in subs["filings"] if str(f.get("form", "")).upper() == form and f.get("primaryDocument")), key=lambda f: str(f["filingDate"]), reverse=True)
            if not matches:
                raise InvalidInput(f"no {form} filing for {symbol} on EDGAR")
            latest = matches[0]
            base.update({"symbol": symbol, "cik": cik, "company": subs.get("name") or title, "form": form, "filing_date": latest["filingDate"], "url": edgar.filing_url(cik, latest["accessionNumber"], latest["primaryDocument"])})
            doc = edgar.document(base["url"])
            if ns.diff and len(matches) > 1:
                prev = matches[1]
                previous = {"filing_date": prev["filingDate"], "url": edgar.filing_url(cik, prev["accessionNumber"], prev["primaryDocument"])}
        try:
            if ns.item and ns.diff:
                if previous is None:
                    raise InvalidInput("--diff needs a symbol with at least two filings of the form")
                result = filing_sections.run_filing_sections({"action": "diff", "document": doc, "previous": edgar.document(previous["url"]), "item": ns.item})
                result["previous"] = previous
            elif ns.item:
                result = filing_sections.run_filing_sections({"action": "item", "document": doc, "item": ns.item, "max_chars": ns.max_chars})
                result["available_items"] = [i["item"] for i in filing_sections.run_filing_sections({"action": "split", "document": doc})["items"]]
            elif ns.search:
                result = filing_sections.run_filing_sections({"action": "search", "document": doc, "query": ns.search, "context": ns.context})
            else:
                result = filing_sections.run_filing_sections({"action": "split", "document": doc})
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        return {**base, **result}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
