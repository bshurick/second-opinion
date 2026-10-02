"""CFTC Commitments of Traders, Traders in Financial Futures (futures only).

The CFTC publishes the weekly report through a public Socrata endpoint that
needs no key: dataset ``gpe5-46if`` is the TFF futures-only report, one row
per contract per Tuesday, released the following Friday. Rows carry long,
short and spread positions plus week-over-week changes for dealers, asset
managers (pensions, insurers, mutual funds), leveraged funds (hedge funds and
CTAs), other reportables and non-reportable small traders. Field names are
the CFTC's own; ``second_opinion.flows.cot_summary`` reads them.

One request per ``positioning`` call, cached for a day under the plugin data
directory keyed by the exact query, so the overview can rerun without
hitting the endpoint again.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from second_opinion import config
from second_opinion.errors import ApiError

TFF_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
LIMIT_SLACK = 50
_TTL = 86400
_TIMEOUT = 30
_USER_AGENT = "second-opinion/1.0 (python-urllib)"
_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


def cache_dir() -> Path:
    return config.data_dir() / "cftc-cache"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — fixed https host
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(f"CFTC returned HTTP {exc.code} for {url}", code="CFTC_HTTP", http_status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"CFTC request failed for {url}: {exc.reason}", code="CFTC_HTTP") from exc
    except (OSError, TimeoutError) as exc:
        raise ApiError(f"CFTC request failed for {url}: {exc}", code="CFTC_HTTP") from exc


def _cached(url: str) -> Any:
    path = cache_dir() / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.json"  # noqa: S324 — cache key only
    if path.is_file() and time.time() - path.stat().st_mtime < _TTL:
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    raw = _fetch(url)
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ApiError(f"CFTC returned non-JSON for {url}", code="CFTC_HTTP") from exc
    if not isinstance(data, list):
        raise ApiError(f"CFTC returned an unexpected payload for {url}", code="CFTC_HTTP")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except OSError:
        pass
    return data


def positioning(codes: list[str], weeks: int = 52) -> dict[str, list[dict[str, Any]]]:
    """Report rows per contract code, newest first, at most ``weeks`` each; codes with no rows map to []."""
    codes = [c.strip() for c in codes]
    for code in codes:
        if not _CODE_RE.match(code):
            raise ValueError(f"invalid CFTC contract code {code!r}")
    weeks = max(1, int(weeks))
    where = "cftc_contract_market_code in(" + ",".join(f"'{c}'" for c in codes) + ")"
    limit = weeks * len(codes) + LIMIT_SLACK
    url = f"{TFF_URL}?$where={urllib.parse.quote(where)}&$order=report_date_as_yyyy_mm_dd%20DESC&$limit={limit}"
    rows = _cached(url)
    out: dict[str, list[dict[str, Any]]] = {c: [] for c in codes}
    for row in rows:
        code = str(row.get("cftc_contract_market_code") or "").strip()
        if code in out and len(out[code]) < weeks:
            out[code].append(row)
    for lst in out.values():
        lst.sort(key=lambda r: str(r.get("report_date_as_yyyy_mm_dd") or ""), reverse=True)
    return out
