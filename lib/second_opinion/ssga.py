"""SPDR (State Street) fund finder: today's NAV and AUM per ETF, and the local shares series.

State Street publishes one JSON document listing every US SPDR ETF with its
NAV and assets under management as of the previous close. AUM divided by NAV
is shares outstanding; the day-over-day change in shares outstanding times
NAV is the fund's net creation (inflow) or redemption (outflow). Nobody
publishes that history for free, so ``record`` appends each day's snapshot to
``<plugin data dir>/etf-shares.json`` and ``second_opinion.flows`` turns the
accumulated series into flows. The finder document is cached for a day.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from second_opinion import config
from second_opinion.errors import ApiError

FINDER_URL = "https://www.ssga.com/bin/v1/ssmp/fund/fundfinder?country=us&language=en&role=intermediary&product=etfs&ui=fund-finder"
SERIES_FILE = "etf-shares.json"
_TTL = 86400
_TIMEOUT = 30
_USER_AGENT = "second-opinion/1.0 (python-urllib)"


def cache_dir() -> Path:
    return config.data_dir() / "ssga-cache"


def series_path() -> Path:
    return config.data_dir() / SERIES_FILE


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — fixed https host
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(f"SSGA returned HTTP {exc.code} for {url}", code="SSGA_HTTP", http_status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"SSGA request failed for {url}: {exc.reason}", code="SSGA_HTTP") from exc
    except (OSError, TimeoutError) as exc:
        raise ApiError(f"SSGA request failed for {url}: {exc}", code="SSGA_HTTP") from exc


def _finder() -> list[dict[str, Any]]:
    path = cache_dir() / "fundfinder.json"
    data: Any = None
    if path.is_file() and time.time() - path.stat().st_mtime < _TTL:
        try:
            data = json.loads(path.read_text())
        except ValueError:
            data = None
    if data is None:
        raw = _fetch(FINDER_URL)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ApiError("SSGA fund finder returned non-JSON", code="SSGA_HTTP") from exc
    try:
        rows = data["data"]["funds"]["etfs"]["datas"]
    except (KeyError, TypeError) as exc:
        raise ApiError("SSGA fund finder payload has no ETF table", code="SSGA_HTTP") from exc
    if not isinstance(rows, list):
        raise ApiError("SSGA fund finder payload has no ETF table", code="SSGA_HTTP")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except OSError:
        pass
    return rows


def _second(v: Any) -> Any:
    """Finder fields are ``[display, raw]`` pairs; take the raw value."""
    if isinstance(v, list):
        return v[1] if len(v) > 1 else None
    return v


def _ticker(row: dict[str, Any]) -> str:
    return str(row.get("fundTicker") or "").replace("®", "").strip().upper()


def snapshot(tickers: list[str]) -> dict[str, dict[str, Any] | None]:
    """``{ticker: {date, nav, aum_usd, shares}}``; None when the finder lacks the fund or its NAV."""
    wanted = {t.strip().upper() for t in tickers}
    out: dict[str, dict[str, Any] | None] = {t: None for t in wanted}
    for row in _finder():
        ticker = _ticker(row)
        if ticker not in wanted:
            continue
        nav, aum_m, as_of = _second(row.get("nav")), _second(row.get("aum")), _second(row.get("asOfDate"))
        try:
            nav_f, aum_usd = float(nav), float(aum_m) * 1_000_000
        except (TypeError, ValueError):
            continue
        if nav_f <= 0 or not as_of:
            continue
        out[ticker] = {"date": str(as_of)[:10], "nav": nav_f, "aum_usd": aum_usd, "shares": round(aum_usd / nav_f)}
    return out


def load_series() -> dict[str, list[dict[str, Any]]]:
    path = series_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def record(snap: dict[str, dict[str, Any] | None]) -> dict[str, list[dict[str, Any]]]:
    """Merge today's observations into the local series (one row per ticker per date) and return it."""
    series = load_series()
    for ticker, obs in snap.items():
        if not obs:
            continue
        rows = [r for r in series.get(ticker, []) if isinstance(r, dict) and r.get("date") != obs["date"]]
        rows.append(dict(obs))
        rows.sort(key=lambda r: str(r.get("date")))
        series[ticker] = rows
    path = series_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(series, indent=1))
    except OSError:
        pass
    return series
