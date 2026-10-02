"""FRED (Federal Reserve Bank of St. Louis) series via the keyless CSV endpoint.

``https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>`` needs no API
key and returns ``observation_date,<SERIES>`` rows, with ``.`` for days the
series was not observed. Only ``latest`` is offered: the most recent numeric
observation, cached for a day under the plugin data directory the same way
EDGAR responses are.

Series the skills use: ``AAA`` (Moody's Seasoned Aaa Corporate Bond Yield,
monthly, percent) and ``DGS10`` (10-Year Treasury Constant Maturity, daily,
percent). Values are returned as published, in percentage points.
"""
from __future__ import annotations

import csv
import io
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from second_opinion import config as _config
from second_opinion.errors import ApiError

_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
_TTL = 86400
_TIMEOUT = 20
_USER_AGENT = "second-opinion/1.0 (python-urllib)"
_SERIES_RE = re.compile(r"^[A-Z0-9_]{1,32}$")
SERIES_NAMES = {
    "AAA": "Moody's Seasoned Aaa Corporate Bond Yield",
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "WRMFNS": "Retail Money Market Funds",
}


def cache_dir() -> Path:
    base = str(_config.data_dir())
    return Path(base) / "fred-cache"


def _fetch(url: str) -> bytes:
    # FRED's edge stalls or drops requests whose User-Agent is a bare word or a
    # browser string, but serves product/version tokens (and urllib's default).
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — fixed https host
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(f"FRED returned HTTP {exc.code} for {url}", code="FRED_HTTP", http_status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"FRED request failed for {url}: {exc.reason}", code="FRED_HTTP") from exc
    except (OSError, TimeoutError) as exc:  # dropped socket, read timeout
        raise ApiError(f"FRED request failed for {url}: {exc}", code="FRED_HTTP") from exc


def _csv(series_id: str) -> str:
    path = cache_dir() / f"{series_id}.csv"
    if path.is_file() and time.time() - path.stat().st_mtime < _TTL:
        try:
            return path.read_text()
        except OSError:
            pass
    text = _fetch(_BASE + series_id).decode("utf-8", errors="replace")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    except OSError:
        pass
    return text


def latest(series_id: str) -> dict[str, Any]:
    """``{"series", "date", "value"}`` for the most recent numeric observation."""
    if not _SERIES_RE.match(series_id or ""):
        raise ValueError(f"invalid FRED series id {series_id!r}")
    rows = list(csv.reader(io.StringIO(_csv(series_id))))
    for row in reversed(rows[1:]):
        if len(row) < 2:
            continue
        try:
            return {"series": series_id, "date": row[0], "value": float(row[1])}
        except ValueError:
            continue
    raise ApiError(f"FRED series {series_id} has no numeric observations", code="FRED_HTTP")


def observations(series_id: str, n: int) -> list[dict[str, Any]]:
    """The last ``n`` numeric observations, oldest first, as ``[{"date", "value"}]``."""
    if not _SERIES_RE.match(series_id or ""):
        raise ValueError(f"invalid FRED series id {series_id!r}")
    rows = list(csv.reader(io.StringIO(_csv(series_id))))
    out: list[dict[str, Any]] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        try:
            out.append({"date": row[0], "value": float(row[1])})
        except ValueError:
            continue
    return out[-max(1, int(n)):]
