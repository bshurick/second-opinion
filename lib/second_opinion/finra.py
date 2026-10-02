"""FINRA Reg SHO daily short-sale volume: one pipe-delimited file per trading day.

``https://cdn.finra.org/equity/regsho/daily/CNMSshvol<YYYYMMDD>.txt`` lists,
for every symbol traded on FINRA-reported venues, the day's short volume and
total volume. Files never change once published, so each one is cached
forever under the plugin data directory. A file that does not exist (weekend
holiday, or not yet published) answers 403 or 404 and is skipped; walking
back stops after ``days`` files or ``days + HOLIDAY_SLACK`` weekdays tried.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from second_opinion import config
from second_opinion.errors import ApiError

FILE_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day}.txt"
HOLIDAY_SLACK = 5
_TIMEOUT = 30
_USER_AGENT = "second-opinion/1.0 (python-urllib)"
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def cache_dir() -> Path:
    return config.data_dir() / "finra-cache"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — fixed https host
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(f"FINRA returned HTTP {exc.code} for {url}", code="FINRA_HTTP", http_status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"FINRA request failed for {url}: {exc.reason}", code="FINRA_HTTP") from exc
    except (OSError, TimeoutError) as exc:
        raise ApiError(f"FINRA request failed for {url}: {exc}", code="FINRA_HTTP") from exc


def _file(day: date) -> bytes | None:
    """The day's file from the cache or the network; None when FINRA has no file for that day."""
    stamp = day.strftime("%Y%m%d")
    path = cache_dir() / f"CNMSshvol{stamp}.txt"
    if path.is_file():
        try:
            return path.read_bytes()
        except OSError:
            pass
    try:
        raw = _fetch(FILE_URL.format(day=stamp))
    except ApiError as exc:
        if exc.extra.get("http_status") in (403, 404):
            return None
        raise
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError:
        pass
    return raw


def _parse(raw: bytes, wanted: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        parts = line.strip().split("|")
        if len(parts) < 5 or parts[0] == "Date":
            continue
        day, symbol = parts[0], parts[1].upper()
        if symbol not in wanted:
            continue
        try:
            out[symbol] = {"date": f"{day[:4]}-{day[4:6]}-{day[6:8]}", "short": float(parts[2]), "total": float(parts[4])}
        except ValueError:
            continue
    return out


def short_volume(symbols: list[str], days: int = 20, today: date | None = None) -> dict[str, list[dict[str, Any]]]:
    """Per symbol, ``[{date, short, total}]`` oldest first over the last ``days`` published files."""
    wanted = [s.strip().upper() for s in symbols]
    for s in wanted:
        if not _SYMBOL_RE.match(s):
            raise ValueError(f"invalid symbol {s!r}")
    days = max(1, int(days))
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in wanted}
    day = today or date.today()
    found = tried = 0
    while found < days and tried < days + HOLIDAY_SLACK:
        if day.weekday() < 5:
            tried += 1
            raw = _file(day)
            if raw is not None:
                found += 1
                for symbol, row in _parse(raw, set(wanted)).items():
                    out[symbol].append(row)
        day -= timedelta(days=1)
    for rows in out.values():
        rows.sort(key=lambda r: r["date"])
    return out
