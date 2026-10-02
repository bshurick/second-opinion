#!/usr/bin/env python3
"""Usage: edgar.py <symbol> [--years N] [--filings-only] [--as-of YYYY-MM-DD]
                   [--quarters N] [--form4 [N]]

Fundamental research from SEC EDGAR: resolves the ticker to a CIK, pulls
the filing index and the XBRL company facts (cached on disk), and runs
fundamentals.py: annual table, margins and returns, growth, quality
checklist, red-flag screens, latest quarter, filings summary with links to
the latest 10-K, 10-Q, proxy, recent 8-Ks and Form 4s. --filings-only skips
the (large) company-facts download. --quarters N adds a quarterly
revenue/net-income table and TTM (needs company facts; ignored with
--filings-only). --form4 [N] (default 5, max 10) fetches and structurally
parses the N most recent Form 4 filings' primary XML document (transaction
code, shares, price, date per transaction). The index lists the XSL-rendered
path ("xslF345X06/<doc>.xml", served as HTML), so the leading xsl directory
is dropped to fetch the raw XML. A filing that fails to fetch is skipped, one
that fails to parse gets {"filing_date", "error": "unparseable", "snippet":
first 80 chars of the response} — never a failed run; allowed together with
--filings-only. Set
EDGAR_USER_AGENT to "app-name contact@email" as the SEC requires. stdin is
unused. Exit codes: 0, 2 (unknown ticker), 5 (EDGAR_HTTP), 6.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import fundamentals  # noqa: E402
from second_opinion import brokerage, edgar, output  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

_UA_FLAG = {"code": "DEFAULT_USER_AGENT", "message": "set EDGAR_USER_AGENT to 'app-name contact@email' as the SEC requires; the default placeholder may be blocked"}
_FORM4_NOTE = "non-dispositions are grants/awards, not open-market purchases"
_ACQUIRE_CODES = {"A", "M", "P", "G"}
_DISPOSE_CODES = {"S", "F", "D", "C"}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"edgar.py: {message}")


def _local(tag: str) -> str:
    """The tag's local name, stripping any ``{namespace}`` prefix."""
    return tag.rsplit("}", 1)[-1]


def _child(elem: ET.Element, *names: str) -> ET.Element | None:
    """Walk ``names`` as direct-child steps below ``elem``, matching by local tag name."""
    cur = elem
    for name in names:
        nxt = next((c for c in cur if _local(c.tag) == name), None)
        if nxt is None:
            return None
        cur = nxt
    return cur


def _text(elem: ET.Element, *names: str) -> str | None:
    node = _child(elem, *names)
    return node.text.strip() if node is not None and node.text else None


def _as_float(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _parse_form4(xml_text: str, filing_date: str | None) -> dict:
    """Structured parse of a Form 4 primary document (namespace-agnostic)."""
    try:
        root = ET.fromstring(xml_text)  # noqa: S314 — SEC-served filing XML, not untrusted user input
    except ET.ParseError:
        return {"filing_date": filing_date, "error": "unparseable", "snippet": xml_text[:80]}
    if _local(root.tag) != "ownershipDocument":  # e.g. an XSL-rendered XHTML page (valid XML)
        return {"filing_date": filing_date, "error": "unparseable", "snippet": xml_text[:80]}
    owners = [e for e in root.iter() if _local(e.tag) == "reportingOwner"]
    owner_name = None
    role = "insider"
    if owners:
        owner_name = _text(owners[0], "reportingOwnerId", "rptOwnerName")
        rel = next((c for c in owners[0] if _local(c.tag) == "reportingOwnerRelationship"), None)
        roles = []
        if rel is not None:
            if _text(rel, "isDirector") == "1":
                roles.append("director")
            if _text(rel, "isOfficer") == "1":
                roles.append("officer")
            if _text(rel, "isTenPercentOwner") == "1":
                roles.append("10% owner")
        role = ", ".join(roles) if roles else "insider"
    transactions = []
    for name in ("nonDerivativeTransaction", "derivativeTransaction"):
        for t in [e for e in root.iter() if _local(e.tag) == name]:
            code = _text(t, "transactionCoding", "transactionCode")
            shares = _as_float(_text(t, "transactionAmounts", "transactionShares", "value"))
            price = _as_float(_text(t, "transactionAmounts", "transactionPricePerShare", "value"))
            date = _text(t, "transactionDate", "value")
            acquired = True if code in _ACQUIRE_CODES else False if code in _DISPOSE_CODES else None
            transactions.append(
                {"code": code, "shares": shares, "price": price, "date": date, "acquired": acquired}
            )
    return {
        "filing_date": filing_date,
        "reporting_owner": owner_name,
        "role": role,
        "transactions": transactions,
    }


def _raw_document_name(primary_document: str) -> str:
    """The raw XML document name behind a Form 4's ``primaryDocument``.

    The submissions index lists the XSL-rendered path ("xslF345X06/wk-form4_123.xml"),
    which the SEC serves as HTML; dropping the leading ``xsl...`` directory gives the
    raw XML at the same accession folder.
    """
    parts = str(primary_document).split("/")
    if len(parts) > 1 and parts[0].lower().startswith("xsl"):
        return parts[-1]
    return primary_document


def _fetch_form4(filings: list, cik: int, count: int) -> dict:
    n = max(1, min(int(count), 10))
    rows = [
        r
        for r in filings
        if str(r.get("form")) in ("4", "4/A") and r.get("accessionNumber") and r.get("primaryDocument")
    ]
    rows.sort(key=lambda r: str(r.get("filingDate") or ""), reverse=True)
    parsed = []
    for r in rows[:n]:
        url = edgar.filing_url(cik, r["accessionNumber"], _raw_document_name(r["primaryDocument"]))
        try:
            text = edgar.document(url)
        except ApiError:
            continue  # fetch failure: skip this filing, the run continues
        parsed.append(_parse_form4(text, r.get("filingDate")))
    return {"filings": parsed, "note": _FORM4_NOTE}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="edgar.py", add_help=False)
        p.add_argument("symbol")
        p.add_argument("--years", type=int, default=5)
        p.add_argument("--filings-only", action="store_true")
        p.add_argument("--as-of", dest="as_of", default=None)
        p.add_argument("--quarters", type=int, default=None)
        p.add_argument("--form4", type=int, nargs="?", const=5, default=None)
        ns = p.parse_args(args)
        symbol = brokerage.validate_symbol(ns.symbol)
        cik, title = edgar.cik_for(symbol)
        subs = edgar.submissions(cik)
        default_ua = edgar.user_agent_is_default()
        base = {"symbol": symbol, "cik": cik, "company": subs.get("name") or title, "sic": subs.get("sic_description"), "fiscal_year_end": subs.get("fiscal_year_end")}
        sources = {"facts": None, "filings": "sec-edgar", "user_agent_is_default": default_ua}
        if ns.filings_only:
            result = {"filings": fundamentals.summarize_filings(subs["filings"], cik, ns.as_of), "flags": []}
        else:
            facts = edgar.company_facts(cik)
            sources["facts"] = "sec-edgar"
            params = {"facts": facts, "years": ns.years, "filings": subs["filings"], "cik": cik, "as_of": ns.as_of}
            if ns.quarters is not None:
                params["quarters"] = ns.quarters
            try:
                result = fundamentals.run_fundamentals(params)
            except ValueError as exc:
                raise InvalidInput(str(exc)) from exc
            result.pop("company", None)
        if ns.form4 is not None:
            result["form4"] = _fetch_form4(subs["filings"], cik, ns.form4)
        if default_ua:
            result["flags"].append(_UA_FLAG)
        return {**base, "sources": sources, **result}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
