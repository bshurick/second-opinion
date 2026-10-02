"""E*Trade OAuth 1.0a: request/authorize/access, daily expiry, renew, revoke.

Tokens die at midnight US/Eastern; an idle token (2 h) can be renewed without
the user. Files live in the plugin data dir, mode 0600:
  etrade-token.json    {"oauth_token", "oauth_token_secret", "created_at", "sandbox"}
  etrade-pending.json  {"request_token", "request_token_secret", "url", "created_at", "sandbox"}
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from second_opinion import config
from second_opinion.config import ETradeSettings
from second_opinion.errors import ApiError, ConfigError

EASTERN = ZoneInfo("America/New_York")
OAUTH_BASE = "https://api.etrade.com"
AUTHORIZE_URL = "https://us.etrade.com/e/t/etws/authorize?key={key}&token={token}"
PENDING_TTL_S = 300
REAUTH_HINT = (
    "E*Trade needs a fresh authorization (tokens expire at midnight Eastern). Open the URL, sign in, "
    "then run etrade-login.py --verifier CODE with the code E*Trade shows."
)


@dataclass(frozen=True)
class Token:
    oauth_token: str
    oauth_token_secret: str
    created_at: datetime
    sandbox: bool


def token_path() -> Path:
    return config.data_dir() / "etrade-token.json"


def pending_path() -> Path:
    return config.data_dir() / "etrade-pending.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _write_private(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_token() -> Token | None:
    d = _read(token_path())
    if not d or not d.get("oauth_token") or not d.get("oauth_token_secret") or not d.get("created_at"):
        return None
    try:
        return Token(str(d["oauth_token"]), str(d["oauth_token_secret"]), _parse(str(d["created_at"])), bool(d.get("sandbox", False)))
    except ValueError:
        return None


def save_token(t: Token) -> None:
    _write_private(token_path(), {"oauth_token": t.oauth_token, "oauth_token_secret": t.oauth_token_secret, "created_at": _iso(t.created_at), "sandbox": t.sandbox})


def delete_token() -> None:
    try:
        token_path().unlink()
    except FileNotFoundError:
        pass


def token_state(token: Token | None, sandbox: bool, now: datetime | None = None) -> str:
    if token is None:
        return "none"
    now = now or _utcnow()
    if token.sandbox != sandbox:
        return "expired"
    if token.created_at.astimezone(EASTERN).date() < now.astimezone(EASTERN).date():
        return "expired"
    return "usable"


class ETradeAuth:
    def __init__(self, settings: ETradeSettings, now: Callable[[], datetime] | None = None, session_factory: Callable[..., Any] | None = None) -> None:
        self.settings = settings
        self._now = now or _utcnow
        self._factory = session_factory

    # ── sessions ──────────────────────────────────────────────────────────
    def _session(self, **kw: Any) -> Any:
        if self._factory is not None:
            return self._factory(**kw)
        from requests_oauthlib import OAuth1Session  # lazy: missing package -> exit 6

        return OAuth1Session(self.settings.consumer_key, client_secret=self.settings.consumer_secret, **kw)

    # ── flow ──────────────────────────────────────────────────────────────
    def _pending(self) -> dict[str, Any] | None:
        d = _read(pending_path())
        if not d or d.get("sandbox") != self.settings.sandbox:
            return None
        try:
            age = (self._now() - _parse(str(d.get("created_at")))).total_seconds()
        except ValueError:
            return None
        return d if 0 <= age < PENDING_TTL_S else None

    def start(self) -> dict[str, Any]:
        """Fetch a request token (or reuse a fresh pending one); return {url, sandbox, created_at}."""
        pending = self._pending()
        if pending is None:
            session = self._session(callback_uri="oob")
            try:
                rt = session.fetch_request_token(OAUTH_BASE + "/oauth/request_token")
            except Exception as e:  # noqa: BLE001
                raise ApiError(f"E*Trade request token failed: {e}", http_status=getattr(getattr(e, "response", None), "status_code", None)) from e
            pending = {
                "request_token": rt["oauth_token"],
                "request_token_secret": rt["oauth_token_secret"],
                "url": AUTHORIZE_URL.format(key=self.settings.consumer_key, token=rt["oauth_token"]),
                "created_at": _iso(self._now()),
                "sandbox": self.settings.sandbox,
            }
            _write_private(pending_path(), pending)
        return {"url": pending["url"], "sandbox": self.settings.sandbox, "created_at": pending["created_at"]}

    def complete(self, verifier: str) -> Token:
        pending = self._pending()
        if pending is None:
            raise ConfigError("no pending E*Trade authorization (or it expired after 5 minutes); run etrade-login.py with no arguments first", code="ETRADE_NO_PENDING")
        s = self._session(resource_owner_key=pending["request_token"], resource_owner_secret=pending["request_token_secret"], verifier=verifier.strip())
        try:
            at = s.fetch_access_token(OAUTH_BASE + "/oauth/access_token")
        except Exception as e:  # noqa: BLE001
            raise ApiError(f"E*Trade access token failed (wrong or expired verifier?): {e}") from e
        token = Token(at["oauth_token"], at["oauth_token_secret"], self._now(), self.settings.sandbox)
        save_token(token)
        try:
            pending_path().unlink()
        except FileNotFoundError:
            pass
        return token

    def renew(self, token: Token) -> bool:
        s = self._session(resource_owner_key=token.oauth_token, resource_owner_secret=token.oauth_token_secret)
        try:
            r = s.get(OAUTH_BASE + "/oauth/renew_access_token", timeout=30)
        except Exception:  # noqa: BLE001
            return False
        return getattr(r, "status_code", 0) == 200

    def revoke(self) -> None:
        token = load_token()
        if token is not None:
            s = self._session(resource_owner_key=token.oauth_token, resource_owner_secret=token.oauth_token_secret)
            try:
                s.get(OAUTH_BASE + "/oauth/revoke_access_token", timeout=30)
            except Exception:  # noqa: BLE001 — revoking a dead token is fine
                pass
        delete_token()

    # ── state ─────────────────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        token = load_token()
        return {
            "configured": True,
            "token": token_state(token, self.settings.sandbox, self._now()),
            "created_at": _iso(token.created_at) if token else None,
            "sandbox": self.settings.sandbox,
        }

    def reauth_error(self) -> ConfigError:
        started = self.start()
        return ConfigError("E*Trade authorization required", code="ETRADE_REAUTH", url=started["url"], hint=REAUTH_HINT, sandbox=self.settings.sandbox)

    def usable_token(self) -> Token:
        token = load_token()
        if token_state(token, self.settings.sandbox, self._now()) != "usable":
            raise self.reauth_error()
        return token  # type: ignore[return-value]
