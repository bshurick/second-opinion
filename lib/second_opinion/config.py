"""Credentials and options from the process environment or a plaintext .env.

Precedence, per key: process env, then ``<data dir>/.env`` (written by install.js,
survives plugin updates), then ``<plugin root>/.env`` (older installs and checkouts).
The plugin root is the nearest ancestor directory containing ``.claude-plugin/``.
Nothing is ever written back. No python-dotenv: the parser below is the whole dependency.
"""
from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from second_opinion.errors import ConfigError, InvalidInput

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "second-opinion"
LEGACY_NAME = "finance-analyst"  # the plugin's name before 1.0; its data dir is read through until migrated
DATA_ENV_VARS = ("SECOND_OPINION_DATA", "FINANCE_ANALYST_DATA")  # new name first; the old one is a fallback
SNAPTRADE_KEYS = ("SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY")
ETRADE_KEYS = ("ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET")
ALL_KEYS = (*SNAPTRADE_KEYS, *ETRADE_KEYS, "ETRADE_SANDBOX", "BROKER_ACCOUNT_TYPES", "SNAPTRADE_ACCOUNT_TYPES")
REQUIRED = SNAPTRADE_KEYS  # kept for older imports
_KEYS_CMD = f"python3 {shlex.quote(str(PLUGIN_ROOT / 'skills' / 'get-started' / 'scripts' / 'configure.py'))} keys"
SETUP_HINT = (
    f"run {_KEYS_CMD} in your own terminal (or node install.js from a checkout) to enter SNAPTRADE_CLIENT_ID / "
    "SNAPTRADE_CONSUMER_KEY, a Personal API key from https://dashboard.snaptrade.com/api-key; they are "
    "kept in ~/.claude/plugins/data/second-opinion/.env"
)
ETRADE_SETUP_HINT = (
    f"run {_KEYS_CMD} --broker etrade in your own terminal to enter ETRADE_CONSUMER_KEY / ETRADE_CONSUMER_SECRET, "
    "the key from https://developer.etrade.com (set ETRADE_SANDBOX=1 in ~/.claude/plugins/data/second-opinion/.env "
    "for the sandbox)"
)
NO_BROKER_HINT = (
    f"no brokerage credentials: run {_KEYS_CMD} in your own terminal for a SnapTrade key "
    "(https://dashboard.snaptrade.com/api-key), or add --broker etrade for an E*Trade key "
    "(https://developer.etrade.com); keys are kept in ~/.claude/plugins/data/second-opinion/.env"
)
VALID_ACCOUNT_TYPES = {"cash", "margin"}
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SnapTradeSettings:
    client_id: str
    consumer_key: str


@dataclass(frozen=True)
class ETradeSettings:
    consumer_key: str
    consumer_secret: str
    sandbox: bool = False


@dataclass(frozen=True)
class Settings:
    snaptrade: SnapTradeSettings | None = None
    etrade: ETradeSettings | None = None
    account_types: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return self.snaptrade is not None or self.etrade is not None

    def require_snaptrade(self) -> SnapTradeSettings:
        if self.snaptrade is None:
            raise ConfigError("missing SNAPTRADE_CLIENT_ID, SNAPTRADE_CONSUMER_KEY", hint=SETUP_HINT)
        return self.snaptrade

    def require_etrade(self) -> ETradeSettings:
        if self.etrade is None:
            raise ConfigError("missing ETRADE_CONSUMER_KEY, ETRADE_CONSUMER_SECRET", hint=ETRADE_SETUP_HINT)
        return self.etrade

    # Compatibility for callers written against the SnapTrade-only Settings.
    @property
    def client_id(self) -> str:
        return self.require_snaptrade().client_id

    @property
    def consumer_key(self) -> str:
        return self.require_snaptrade().consumer_key


def _cache_only(path: Path) -> bool:
    """True when a directory holds nothing but regenerable caches (``*-cache``, ``*-cache.json``)."""
    try:
        return all(e.name.endswith(("-cache", "-cache.json")) or e.name == ".DS_Store" for e in path.iterdir())
    except OSError:
        return False


def data_dir() -> Path:
    """Plugin data directory (ledger, registry, tokens, caches, .env, installed.json).

    Override with SECOND_OPINION_DATA (FINANCE_ANALYST_DATA is still accepted). CLAUDE_PLUGIN_DATA is
    deliberately ignored: Claude Code sets it only in hook processes and names it after the load path
    (``second-opinion-skills-dir`` when the plugin is linked into ``~/.claude/skills``), so honouring it
    would put the hooks' data in one directory and the scripts' data in another.

    Without an override: ``~/.claude/plugins/data/second-opinion``, unless that is absent (or holds only
    caches) and the pre-1.0 ``~/.claude/plugins/data/finance-analyst`` exists, in which case the old
    directory is used until the session-start hook or the installer moves it.
    """
    for var in DATA_ENV_VARS:
        if os.environ.get(var):
            return Path(os.environ[var])
    base = Path.home() / ".claude" / "plugins" / "data"
    new, old = base / PLUGIN_NAME, base / LEGACY_NAME
    if old.is_dir() and (not new.exists() or (new.is_dir() and _cache_only(new))):
        return old
    return new


def installed_record() -> dict | None:
    """The installer's record (skills, extras): ``<data dir>/installed.json``, else the plugin root's copy."""
    for path in (data_dir() / "installed.json", PLUGIN_ROOT / "installed.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


# The old installer extras and the settings that now hold them (second_opinion.settings).
EXTRA_SETTINGS = {
    "follow_ups": "replies.follow_ups",
    "trade-journal": "guardrails.pre_buy_check",
    "financial-education": "lessons",
}


def extra_enabled(key: str) -> bool:
    """Whether an optional extra is on, read from its setting in ``settings.json`` (see EXTRA_SETTINGS).

    Nothing saved means the setting's default. Unreadable settings raise the store's ApiError
    (SETTINGS_CORRUPT); the caller decides its fail-safe.
    """
    from second_opinion import settings  # imported here: settings imports this module

    if key not in EXTRA_SETTINGS:
        raise InvalidInput(f"unknown extra {key!r}; extras are {', '.join(EXTRA_SETTINGS)}")
    return bool(settings.get(EXTRA_SETTINGS[key]))


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def find_env_file(start: Path | None = None) -> Path | None:
    here = (start or PLUGIN_ROOT).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".claude-plugin").is_dir():
            env = candidate / ".env"
            return env if env.is_file() else None
    return None


def env_files() -> list[Path]:
    """Existing .env files in precedence order: the data dir's, then the plugin root's."""
    out: list[Path] = []
    for path in (data_dir() / ".env", find_env_file()):
        if path is not None and path.is_file() and path not in out:
            out.append(path)
    return out


def env_value(key: str) -> str:
    """One setting by the same precedence as load_settings: process env, then each .env file."""
    value = os.environ.get(key, "").strip()
    if value:
        return value
    for path in env_files():
        value = parse_env_file(path).get(key, "").strip()
        if value:
            return value
    return ""


def parse_account_types(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        account_id, _, kind = item.partition("=")
        kind = kind.strip().lower()
        if kind not in VALID_ACCOUNT_TYPES:
            raise InvalidInput(f"BROKER_ACCOUNT_TYPES entry {item!r} must be <account_id>=cash or <account_id>=margin")
        result[account_id.strip()] = kind
    return result


def _pair(source: Mapping[str, str], keys: tuple[str, str], hint: str) -> tuple[str, str] | None:
    present = [k for k in keys if source.get(k)]
    if not present:
        return None
    if len(present) != len(keys):
        missing = [k for k in keys if not source.get(k)]
        raise ConfigError(f"{present[0]} is set but {', '.join(missing)} is missing", hint=hint)
    return source[keys[0]], source[keys[1]]


def load_settings(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> Settings:
    source: dict[str, str] = dict(os.environ if env is None else env)
    if not all(source.get(k) for k in ALL_KEYS):
        paths = [env_file] if env_file is not None else env_files()
        for path in paths:
            if path.is_file():
                for k, v in parse_env_file(path).items():
                    if v and not source.get(k):
                        source[k] = v
    snap = _pair(source, SNAPTRADE_KEYS, SETUP_HINT)
    etr = _pair(source, ETRADE_KEYS, ETRADE_SETUP_HINT)
    raw_types = source.get("BROKER_ACCOUNT_TYPES") or source.get("SNAPTRADE_ACCOUNT_TYPES", "")
    return Settings(
        snaptrade=SnapTradeSettings(*snap) if snap else None,
        etrade=ETradeSettings(etr[0], etr[1], sandbox=source.get("ETRADE_SANDBOX", "").strip().lower() in _TRUE) if etr else None,
        account_types=parse_account_types(raw_types),
    )
