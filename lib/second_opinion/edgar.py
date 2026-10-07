"""SEC EDGAR client: ticker -> CIK, filing index, XBRL company facts.

EDGAR is free but requires a descriptive User-Agent with a contact address
(https://www.sec.gov/os/accessing-edgar-data). Set ``EDGAR_USER_AGENT`` to
"app-name contact@email"; the placeholder default may be blocked. Responses
are cached on disk under ``<plugin data dir>/edgar-cache`` (ticker list 7
days, everything else 1 day). urllib only, so no extra dependency.

Requests are spaced to about 8 per second across every process on the machine
(a file lock in the cache dir; the SEC limit is 10/s per IP), and HTTP 429/503
are retried with backoff. ``archive(url)`` fetches any file under the SEC
filing archive (an 8-K exhibit, an index.json) through the same cache.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from second_opinion import config as _config
from second_opinion.errors import ApiError, InvalidInput

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FRAME_URL = "https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{period}.json"
_DEFAULT_UA = "second-opinion-plugin (set EDGAR_USER_AGENT) contact@example.com"
_TTL = {"company_tickers.json": 7 * 86400}
_DEFAULT_TTL = 86400
_MIN_INTERVAL = 0.125  # SEC fair-access limit is 10 requests/second; stay at 8
_MAX_RETRIES = 4  # on HTTP 429 / 503
_BACKOFF = (2, 5, 10, 20)  # seconds
ARCHIVE_PREFIX = "https://www.sec.gov/Archives/edgar/data/"


def user_agent() -> str:
    return _config.env_value("EDGAR_USER_AGENT") or _DEFAULT_UA


def user_agent_is_default() -> bool:
    return user_agent() == _DEFAULT_UA


def cache_dir() -> Path:
    base = str(_config.data_dir())
    return Path(base) / "edgar-cache"


def _throttle() -> None:
    """Space EDGAR requests across every process on this machine (all agents share one IP)."""
    try:
        import fcntl

        lock = cache_dir() / ".throttle"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                last = float(fh.read() or 0)
            except ValueError:
                last = 0.0
            wait = last + _MIN_INTERVAL - time.time()
            if wait > 0:
                time.sleep(wait)
            fh.seek(0)
            fh.truncate()
            fh.write(repr(time.time()))
            fh.flush()
    except (OSError, ImportError):
        time.sleep(_MIN_INTERVAL)


def _fetch(url: str, user_agent: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Host": url.split("/")[2]})
    for attempt in range(_MAX_RETRIES + 1):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed https hosts
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip

                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF[attempt])
                continue
            raise ApiError(f"EDGAR returned HTTP {exc.code} for {url}", code="EDGAR_HTTP", http_status=exc.code, hint="set EDGAR_USER_AGENT to 'app-name contact@email'; the SEC blocks anonymous clients") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"EDGAR request failed for {url}: {exc.reason}", code="EDGAR_HTTP") from exc
    raise ApiError(f"EDGAR request failed for {url}", code="EDGAR_HTTP")  # unreachable


def _cached_json(url: str, name: str) -> Any:
    path = cache_dir() / name
    ttl = _TTL.get(name, _DEFAULT_TTL)
    if path.is_file() and time.time() - path.stat().st_mtime < ttl:
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    raw = _fetch(url, user_agent())
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ApiError(f"EDGAR returned non-JSON for {url}", code="EDGAR_HTTP") from exc
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except OSError:
        pass
    return data


def _cached_bytes(url: str, name: str) -> bytes:
    path = cache_dir() / name
    if path.is_file() and time.time() - path.stat().st_mtime < _DEFAULT_TTL:
        try:
            return path.read_bytes()
        except OSError:
            pass
    raw = _fetch(url, user_agent())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError:
        pass
    return raw


def frame(concept: str, period: str, unit: str = "USD", taxonomy: str = "us-gaap") -> list[dict[str, Any]]:
    """One XBRL concept for every filer at once: ``[{cik, entityName, val, accn, end, ...}]``.

    ``period`` is ``CY2025`` (annual), ``CY2026Q2`` (a quarter) or ``CY2025Q4I`` (an
    instant). A concept the SEC has no frame for returns ``[]`` rather than raising, so a
    caller can try aliases in turn. Cached for a day like every EDGAR read.
    """
    url = FRAME_URL.format(taxonomy=taxonomy, concept=concept, unit=unit, period=period)
    try:
        data = _cached_json(url, f"frames/{taxonomy}-{concept}-{unit}-{period}.json")
    except ApiError as exc:
        if exc.extra.get("http_status") == 404:
            return []
        raise
    rows = data.get("data") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def tickers() -> dict[int, dict[str, str]]:
    """``{cik: {"ticker", "title"}}`` from the SEC ticker list; a CIK's first listing is its primary one."""
    out: dict[int, dict[str, str]] = {}
    for row in (_cached_json(TICKERS_URL, "company_tickers.json") or {}).values():
        cik = row.get("cik_str")
        if isinstance(cik, int) and cik not in out:
            out[cik] = {"ticker": row.get("ticker"), "title": row.get("title")}
    return out


def ticker_ciks() -> dict[str, int]:
    """``{TICKER: cik}`` for every ticker in the SEC list, every share class included (GOOG and
    GOOGL, BRK-B), unlike ``tickers()``, which keeps a CIK's first listing only."""
    table = _cached_json(TICKERS_URL, "company_tickers.json") or {}
    rows = table.values() if isinstance(table, dict) else table
    return {str(r["ticker"]).upper(): int(r["cik_str"]) for r in rows
            if isinstance(r, dict) and r.get("ticker") and isinstance(r.get("cik_str"), int)}


def cik_for(symbol: str) -> tuple[int, str]:
    """(CIK, company title) for a ticker from the SEC's ticker list."""
    sym = symbol.strip().upper()
    table = _cached_json(TICKERS_URL, "company_tickers.json")
    rows = table.values() if isinstance(table, dict) else table
    for row in rows:
        if isinstance(row, dict) and str(row.get("ticker", "")).upper() == sym:
            return int(row["cik_str"]), str(row.get("title") or "")
    raise InvalidInput(f"{sym} is not in the SEC ticker list (foreign or unlisted issuers have no EDGAR filings)")


def submissions(cik: int) -> dict[str, Any]:
    """Filing index with the 'recent' columns flattened into one row per filing."""
    data = _cached_json(SUBMISSIONS_URL.format(cik=int(cik)), f"submissions-{int(cik)}.json")
    recent = (data.get("filings") or {}).get("recent") or {}
    keys = ["form", "filingDate", "accessionNumber", "primaryDocument", "items"]
    n = len(recent.get("form") or [])
    rows = [{k: (recent.get(k) or [None] * n)[i] for k in keys} for i in range(n)]
    return {"cik": int(cik), "name": data.get("name"), "sic": data.get("sic"), "sic_description": data.get("sicDescription"), "fiscal_year_end": data.get("fiscalYearEnd"), "filings": rows}


def company_facts(cik: int) -> dict[str, Any]:
    """The XBRL companyfacts JSON (large: every reported concept with history)."""
    return _cached_json(FACTS_URL.format(cik=int(cik)), f"companyfacts-{int(cik)}.json")


def filing_url(cik: int, accession: str, primary_document: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{primary_document}"


def document(url: str) -> str:
    """A filing document (HTML or text) by URL, cached on disk for a day."""
    import hashlib

    name = f"doc-{hashlib.sha1(url.encode()).hexdigest()[:16]}.html"  # noqa: S324 — cache key only
    path = cache_dir() / name
    if path.is_file() and time.time() - path.stat().st_mtime < _DEFAULT_TTL:
        return path.read_text(errors="replace")
    raw = _fetch(url, user_agent())
    text = raw.decode("utf-8", errors="replace")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    except OSError:
        pass
    return text


def archive(url: str) -> str:
    """Any file under the SEC filing archive (an 8-K exhibit, an index.json), cached for a day."""
    if not isinstance(url, str) or not url.startswith(ARCHIVE_PREFIX):
        raise InvalidInput(f"not an SEC archive URL: {url!r} (must start with {ARCHIVE_PREFIX})")
    return document(url)


def thirteen_f_filings(cik: int) -> list[dict[str, Any]]:
    """Original 13F-HR holdings reports (amendments excluded), newest first: accession, filing_date, report_date."""
    data = _cached_json(SUBMISSIONS_URL.format(cik=int(cik)), f"submissions-{int(cik)}.json")
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    n = len(forms)
    col = lambda key: recent.get(key) or [None] * n  # noqa: E731
    out = []
    for i, form in enumerate(forms):
        if form != "13F-HR":
            continue
        out.append({"accession": col("accessionNumber")[i], "filing_date": col("filingDate")[i], "report_date": col("reportDate")[i], "form": "13F-HR"})
    out.sort(key=lambda r: (r["filing_date"] or "", r["accession"]), reverse=True)
    return out


def information_table(cik: int, accession: str) -> bytes:
    """The raw information-table XML of a 13F filing: the one .xml in the filing folder that is not primary_doc.xml."""
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    index = _cached_json(f"{folder}/index.json", f"index-{accession}.json")
    items = ((index.get("directory") or {}).get("item") or []) if isinstance(index, dict) else []
    names = [str(i.get("name") or "") for i in items if isinstance(i, dict)]
    tables = [n for n in names if n.lower().endswith(".xml") and n.lower() != "primary_doc.xml"]
    if not tables:
        raise ApiError(f"13F filing {accession} has no information table XML (files: {', '.join(names) or 'none'})", code="EDGAR_13F_TABLE")
    return _cached_bytes(f"{folder}/{tables[0]}", f"13f-{accession}.xml")


def search_companies(name: str) -> list[dict[str, Any]]:
    """EDGAR company search restricted to 13F-HR filers: [{cik, name}] in EDGAR's order."""
    import re
    import urllib.parse

    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={urllib.parse.quote_plus(name.strip())}&type=13F-HR&output=atom"
    text = _cached_bytes(url, f"search-{urllib.parse.quote_plus(name.strip().lower())[:40]}.xml").decode("utf-8", errors="replace")
    out = []
    for title, cik in re.findall(r"<title>([^<]*?)\s*\((\d{4,10})\)</title>", text):
        out.append({"cik": int(cik), "name": title.strip()})
    return out
