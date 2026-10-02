"""On-disk transaction ledger shared by statement-import and trade-review.

``<plugin data dir>/ledger.json`` holds ``{"transactions": [...], "imports": [...]}``
where each transaction follows normalize.py's output contract. Entries are
deduplicated on (date, type, symbol, units, amount, account_id).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from second_opinion import config as _config
from second_opinion.errors import ApiError

LEDGER_FILE = "ledger.json"


def ledger_path() -> Path:
    base = str(_config.data_dir())
    return Path(base) / LEDGER_FILE


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or ledger_path()
    if not path.is_file():
        return {"transactions": [], "imports": []}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ApiError(f"ledger at {path} is not valid JSON: {exc}", code="LEDGER_CORRUPT", hint=f"move or delete {path} and re-import") from exc
    if not isinstance(data, dict) or not isinstance(data.get("transactions"), list):
        raise ApiError(f"ledger at {path} has an unexpected shape", code="LEDGER_CORRUPT", hint=f"move or delete {path} and re-import")
    data.setdefault("imports", [])
    return data


def save(book: dict[str, Any], path: Path | None = None) -> Path:
    path = path or ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1))
    return path


def key(entry: dict[str, Any]) -> str:
    return "|".join(str(entry.get(k)) for k in ("date", "type", "symbol", "units", "amount", "account_id"))


def merge(book: dict[str, Any], entries: list[dict[str, Any]], source: str) -> tuple[int, int]:
    """Append new entries (deduplicated), keep the ledger date-sorted, record the import."""
    seen = {key(t) for t in book["transactions"]}
    added = dupes = 0
    for e in entries:
        k = key(e)
        if k in seen:
            dupes += 1
            continue
        seen.add(k)
        book["transactions"].append(e)
        added += 1
    book["transactions"] = sorted(enumerate(book["transactions"]), key=lambda p: (p[1]["date"], p[0]))
    book["transactions"] = [t for _, t in book["transactions"]]
    book["imports"].append({"source": source, "added": added, "duplicates": dupes, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return added, dupes


def filter(rows: list[dict[str, Any]], symbol: str | None = None, kind: str | None = None, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:  # noqa: A001
    out = rows
    if symbol:
        out = [t for t in out if (t.get("symbol") or "").upper() == symbol.upper()]
    if kind:
        out = [t for t in out if t.get("type") == kind.upper()]
    if start:
        out = [t for t in out if t["date"] >= start]
    if end:
        out = [t for t in out if t["date"] <= end]
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    types: dict[str, int] = {}
    accounts: dict[str, int] = {}
    symbols: set[str] = set()
    for t in rows:
        types[t["type"]] = types.get(t["type"], 0) + 1
        acct = str(t.get("account_id"))
        accounts[acct] = accounts.get(acct, 0) + 1
        if t.get("symbol"):
            symbols.add(t["symbol"])
    dates = sorted(t["date"] for t in rows)
    return {
        "count": len(rows),
        "date_range": {"start": dates[0], "end": dates[-1]} if dates else None,
        "types": dict(sorted(types.items())),
        "accounts": dict(sorted(accounts.items())),
        "symbols": sorted(symbols),
    }
