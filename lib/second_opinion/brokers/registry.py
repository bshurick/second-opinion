"""brokers.json: which broker serves which account id. A cache, never authoritative."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from second_opinion import config

KEEP = ("broker", "account_number", "institution_name", "account_type", "supports_trading", "name", "shadowed_by")


def default_path() -> Path:
    return config.data_dir() / "brokers.json"


class Registry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        accounts = data.get("accounts") if isinstance(data, dict) else None
        return accounts if isinstance(accounts, dict) else {}

    def save(self, rows: list[dict[str, Any]], preserve_brokers: tuple[str, ...] = ()) -> None:
        """``preserve_brokers`` keeps the cached rows of brokers that could not be listed,
        so a broker that is merely logged out still dispatches to itself (and says so)."""
        accounts: dict[str, dict[str, Any]] = {}
        if preserve_brokers:
            accounts = {k: v for k, v in self.load().items() if isinstance(v, dict) and v.get("broker") in preserve_brokers}
        accounts.update({r["account_id"]: {k: r.get(k) for k in KEEP} for r in rows if r.get("account_id")})
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "accounts": accounts}
        tmp: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".brokers-", suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            # a cache write failure must never fail a script
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def broker_of(self, account_id: str) -> str | None:
        row = self.load().get(account_id)
        return row.get("broker") if isinstance(row, dict) else None
