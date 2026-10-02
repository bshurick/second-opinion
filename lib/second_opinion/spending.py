"""On-disk spending store and rules file used by the spending skill.

``<plugin data dir>/spending.json`` holds ``{"accounts": {id: {...}}, "transactions": [...],
"imports": [...]}``; ``spending-rules.json`` holds ``{"categories", "merchants", "transfers",
"ignore"}`` lists of regex rules. Transactions are deduplicated on ``key()``: the OFX
``fitid`` when present, else account, date, amount and the normalized (whitespace-collapsed,
upper-cased) raw description, plus an ``occurrence`` ordinal so two same-day, same-amount,
same-description rows (two registers of one chain both charged the same amount) both survive
instead of colliding on one key.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from second_opinion import config as _config
from second_opinion import statements
from second_opinion.errors import ApiError

SPENDING_FILE = "spending.json"
RULES_FILE = "spending-rules.json"
KINDS = ("card", "checking", "savings")
RULE_KINDS = ("categories", "merchants", "transfers", "ignore")


def _base() -> Path:
    return _config.data_dir()


def spending_path() -> Path:
    return _base() / SPENDING_FILE


def rules_path() -> Path:
    return _base() / RULES_FILE


def empty() -> dict[str, Any]:
    return {"accounts": {}, "transactions": [], "imports": []}


def empty_rules() -> dict[str, Any]:
    return {k: [] for k in RULE_KINDS}


def _read_json(path: Path, code: str) -> Any:
    hint = f"move or delete {path} and import again"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ApiError(f"{path.name} at {path} is not valid JSON: {exc}", code=code, hint=hint) from exc


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or spending_path()
    if not path.is_file():
        return empty()
    data = _read_json(path, "SPENDING_CORRUPT")
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict) or not isinstance(data.get("transactions"), list):
        raise ApiError(f"spending store at {path} has an unexpected shape", code="SPENDING_CORRUPT", hint=f"move or delete {path} and import again")
    data.setdefault("imports", [])
    return data


def save(book: dict[str, Any], path: Path | None = None) -> Path:
    path = path or spending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1))
    return path


def load_rules(path: Path | None = None) -> dict[str, Any]:
    path = path or rules_path()
    if not path.is_file():
        return empty_rules()
    data = _read_json(path, "RULES_CORRUPT")
    if not isinstance(data, dict) or any(not isinstance(data.get(k, []), list) for k in RULE_KINDS):
        raise ApiError(f"rules file at {path} has an unexpected shape", code="RULES_CORRUPT", hint=f"fix or delete {path}")
    for k in RULE_KINDS:
        data.setdefault(k, [])
    return data


def save_rules(rules: dict[str, Any], path: Path | None = None) -> Path:
    path = path or rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, indent=1))
    return path


def _normalized_description(tx: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(tx.get("description") or "")).strip().upper()


def base_key(tx: dict[str, Any]) -> str:
    """The dedupe key without its ``occurrence`` suffix: account, date, amount, description.

    Two rows sharing a base key (e.g. two same-day, same-amount charges at different
    registers of one chain) are distinguished by ``occurrence`` instead of colliding.
    """
    if tx.get("fitid"):
        return f"{tx.get('account_id')}|fitid:{tx['fitid']}"
    return f"{tx.get('account_id')}|{tx.get('date')}|{float(tx.get('amount') or 0.0):.2f}|{_normalized_description(tx)}"


def key(tx: dict[str, Any]) -> str:
    base = base_key(tx)
    if tx.get("fitid"):
        return base
    occurrence = tx.get("occurrence") or 1
    return f"{base}#{occurrence}"


def txid(tx: dict[str, Any]) -> str:
    return "t-" + hashlib.sha1(key(tx).encode("utf-8")).hexdigest()[:12]


def merge(book: dict[str, Any], txs: list[dict[str, Any]], source: dict[str, Any]) -> tuple[int, int]:
    """Append new rows (deduplicated on key), keep the store date-sorted, log the import.

    ``occurrence`` is assigned per incoming row as the ordinal of its base key within this
    batch, in import order: two exact same-day twins in one file get 1 and 2 and both
    survive, while re-importing the same file assigns the same ordinals and both dedupe.
    """
    seen = {key(t) for t in book["transactions"]}
    added = dupes = 0
    batch_counts: dict[str, int] = {}
    for t in txs:
        base = base_key(t)
        batch_counts[base] = batch_counts.get(base, 0) + 1
        occurrence = batch_counts[base]
        stamped = {**t, "occurrence": occurrence}
        k = key(stamped)
        if k in seen:
            dupes += 1
            continue
        seen.add(k)
        book["transactions"].append({**stamped, "id": txid(stamped)})
        added += 1
    book["transactions"].sort(key=lambda t: (str(t.get("date")), str(t.get("account_id")), str(t.get("id"))))
    book["imports"].append({**source, "added": added, "duplicates": dupes, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return added, dupes


def statement_account_name(account_id: str) -> str | None:
    path = statements.statements_path()
    if not path.is_file():
        return None
    try:
        book = statements.load(path)
    except ApiError:
        return None
    account = book["accounts"].get(account_id)
    return account.get("name") if isinstance(account, dict) else None


def find_transaction(book: dict[str, Any], txid_: str) -> dict[str, Any] | None:
    return next((t for t in book["transactions"] if t.get("id") == txid_), None)


def match_transactions(
    book: dict[str, Any], date_: str, amount: float, merchant: str | None = None, days: int = 3, tolerance: float = 0.5
) -> list[dict[str, Any]]:
    """Transactions within ``days`` of ``date_`` and ``tolerance`` of ``amount``, nearest first."""
    from datetime import date as _date

    target = _date.fromisoformat(date_)
    needle = (merchant or "").strip().lower()
    hits = []
    for t in book["transactions"]:
        try:
            delta = abs((_date.fromisoformat(str(t.get("date"))) - target).days)
        except ValueError:
            continue
        diff = abs(float(t.get("amount") or 0.0) - float(amount))
        if delta > days or diff > tolerance + 1e-9:
            continue
        if needle and needle not in str(t.get("merchant") or "").lower() and needle not in str(t.get("description") or "").lower():
            continue
        hits.append((delta, diff, t))
    hits.sort(key=lambda h: (h[0], h[1], str(h[2].get("id"))))
    return [t for _, _, t in hits]


def source_of(book: dict[str, Any], tx: dict[str, Any]) -> str:
    if tx.get("source"):
        return str(tx["source"])
    account = book["accounts"].get(tx.get("account_id")) or {}
    return f"preset:{account['preset']}" if account.get("preset") else "unknown"
