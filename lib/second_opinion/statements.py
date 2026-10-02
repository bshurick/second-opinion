"""On-disk statement store used by the debt-tracker skill.

``<plugin data dir>/statements.json`` holds ``{"accounts": {id: {...}}, "statements": [...],
"imports": [...]}``. Snapshots are keyed on (account_id, period_end); ``put`` keeps the list
sorted by that key and logs every write to ``imports``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from second_opinion import config as _config
from second_opinion.errors import ApiError

STATEMENTS_FILE = "statements.json"
KINDS = ("card", "mortgage", "auto", "student", "heloc", "other")
REVOLVING_KINDS = ("card", "heloc")


def statements_path() -> Path:
    base = str(_config.data_dir())
    return Path(base) / STATEMENTS_FILE


def empty() -> dict[str, Any]:
    return {"accounts": {}, "statements": [], "imports": []}


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or statements_path()
    if not path.is_file():
        return empty()
    hint = f"move or delete {path} and record the statements again"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ApiError(f"statements at {path} are not valid JSON: {exc}", code="STATEMENTS_CORRUPT", hint=hint) from exc
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict) or not isinstance(data.get("statements"), list):
        raise ApiError(f"statements at {path} have an unexpected shape", code="STATEMENTS_CORRUPT", hint=hint)
    data.setdefault("imports", [])
    return data


def save(book: dict[str, Any], path: Path | None = None) -> Path:
    path = path or statements_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1))
    return path


def key(snapshot: dict[str, Any]) -> str:
    return f"{snapshot.get('account_id')}|{snapshot.get('period_end')}"


def find(book: dict[str, Any], account_id: str, period_end: str) -> dict[str, Any] | None:
    wanted = f"{account_id}|{period_end}"
    return next((s for s in book["statements"] if key(s) == wanted), None)


def put(book: dict[str, Any], snapshot: dict[str, Any], *, replace: bool = False) -> bool:
    """Insert one snapshot. Returns True when an existing one was replaced; KeyError on a duplicate."""
    k = key(snapshot)
    existing = [s for s in book["statements"] if key(s) == k]
    if existing and not replace:
        raise KeyError(k)
    book["statements"] = [s for s in book["statements"] if key(s) != k] + [snapshot]
    book["statements"].sort(key=lambda s: (str(s.get("account_id")), str(s.get("period_end"))))
    book["imports"].append({
        "account_id": snapshot.get("account_id"),
        "period_end": snapshot.get("period_end"),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "replaced": bool(existing),
    })
    return bool(existing)


def latest(book: dict[str, Any], account_id: str) -> dict[str, Any] | None:
    rows = [s for s in book["statements"] if s.get("account_id") == account_id]
    return max(rows, key=lambda s: str(s.get("period_end"))) if rows else None
