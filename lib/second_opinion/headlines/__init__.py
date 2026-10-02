"""Headlines: the one schema every brief source produces, plus ordering and the last-brief diff.

A headline is ``{key, code, skill, severity, symbol, title, detail, as_of, status, ask}``. ``key`` is
``<skill>:<code>:<symbol or ->:<discriminator>`` and stays stable across runs so the next brief can
mark it ``still``. Extractors build headlines with :func:`make`; the orchestrator caps, orders and
diffs them. ``brief-last.json`` in the plugin data dir remembers the keys of the last run and the
risk figures the next run compares against.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from second_opinion import config

SEVERITIES = ("alert", "notice", "info")
PER_SOURCE_CAP = 3
LAST_FILE = "brief-last.json"
_RANK = {s: i for i, s in enumerate(SEVERITIES)}
_STATUS_RANK = {"new": 0, "still": 1}


def make(skill: str, code: str, severity: str, title: str, *, symbol: str | None = None, discriminator: str = "",
         detail: str = "", as_of: str | None = None, ask: str = "", url: str = "", answer: str = "", why: str = "") -> dict:
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}, not {severity!r}")
    sym = (symbol or "").upper() or None
    return {
        "key": f"{skill}:{code}:{sym or '-'}:{discriminator}",
        "code": code,
        "skill": skill,
        "severity": severity,
        "symbol": sym,
        "title": title,
        "detail": detail,
        "as_of": as_of,
        "status": "new",
        "ask": ask,
        "url": url,
        "answer": answer,
        "why": why,
    }


def symbol_from_message(message: str) -> str | None:
    """Extract a ticker symbol from the first whitespace token if it looks like one."""
    first_token = message.split()[0] if message else ""
    if 1 <= len(first_token) <= 10 and all(c.isalnum() or c in ".-" for c in first_token):
        return first_token.upper()
    return None


def money(v: float) -> str:
    return f"${abs(v):,.2f}"


def yahoo_url(symbol: str) -> str:
    return f"https://finance.yahoo.com/quote/{symbol}"


def edgar_url(symbol: str) -> str:
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={symbol}&type=10-K&owner=include&count=10"


def pct(v: float, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%"


def cap(headlines: list[dict], limit: int = PER_SOURCE_CAP) -> list[dict]:
    """At most ``limit`` per source: alerts first, then notices, then info, keeping input order within a severity."""
    ranked = sorted(enumerate(headlines), key=lambda ih: (_RANK[ih[1]["severity"]], ih[0]))
    return [h for _, h in ranked[:limit]]


def order(headlines: list[dict], source_order: list[str]) -> list[dict]:
    """New headlines first regardless of severity; then alerts, notices, info; then source order; then key."""
    pos = {s: i for i, s in enumerate(source_order)}
    return sorted(
        headlines,
        key=lambda h: (_STATUS_RANK.get(h["status"], 0), _RANK[h["severity"]], pos.get(h["skill"], len(pos)), h["key"]),
    )


def apply_status(headlines: list[dict], previous_keys: set[str]) -> list[dict]:
    return [{**h, "status": "still" if h["key"] in previous_keys else "new"} for h in headlines]


def last_path() -> Path:
    return config.data_dir() / LAST_FILE


def load_last() -> dict:
    empty = {"as_of": None, "keys": [], "risk": {}}
    path = last_path()
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    return {"as_of": data.get("as_of"), "keys": [k for k in data.get("keys") or [] if isinstance(k, str)],
            "risk": data.get("risk") if isinstance(data.get("risk"), dict) else {}}


def save_last(as_of: str, headlines: list[dict], risk: dict, extra_keys: list[str] | None = None) -> Path:
    keys = [h["key"] for h in headlines]
    seen = set(keys)
    for k in extra_keys or []:
        if k not in seen:
            seen.add(k)
            keys.append(k)
    path = last_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"as_of": as_of, "keys": keys, "risk": risk}, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path
