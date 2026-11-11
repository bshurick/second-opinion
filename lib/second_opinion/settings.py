"""The user's settings: one ``settings.json`` under the plugin data directory.

    {"schema": 1, "depth", "deep", "accounts", "plan", "taxes", "guardrails",
     "replies", "lessons", "meta", "history": [{"date", "key", "value"}]}

``load`` fills ``DEFAULTS`` under the file's values (the file wins; unknown keys
are kept so a newer file round-trips). Every write goes through ``set_value``,
which validates, appends to ``history`` and saves atomically. A corrupt file is
never overwritten, and a file written by a newer schema is read-only. Stdlib
only apart from the sibling modules.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from second_opinion import config
from second_opinion.errors import ApiError, InvalidInput

SCHEMA = 2
FILE = "settings.json"

TAX_ADV_KEYWORDS = ("ira", "roth", "401", "403", "457", "hsa", "529", "pension", "tsp", "tfsa", "rrsp", "lira")
DEPTHS = ("standard", "deep")
ROLES = ("trading", "retirement", "savings")
WEIGHTINGS = ("equal", "market_cap", "valuation", "size")
GAIN_POLICIES = ("hold", "allow")
EMPLOYER_POLICIES = ("sell_on_arrival", "hold")
# Skills with a deep path, and what it is. With depth deep, the others answer as they always have.
DEEP_PATHS: dict[str, str] = {
    "valuation": "researched scenarios by segment",
    "stock-screener": "deep picker with the downside gate",
    "portfolio-analysis": "deep review of shared bets",
    "real-estate": "deep review of one property",
    "tax-aware": "multi-year plan comparison",
    "trade-review": "skill against luck review",
}

DEFAULTS: dict[str, Any] = {
    "schema": SCHEMA,
    "depth": "standard",
    "deep": {"ask_above": 3},
    "accounts": {},
    "plan": {
        "targets": {}, "classes": {}, "cash_reserve": None,
        "bands": {"absolute": 0.05, "relative": 0.25},
        "sleeves": {
            "PICKS": {"target": None, "glide": None, "weighting": None, "include_light": None},
            "EMPLOYER": {"members": None, "policy": None},
        },
    },
    "taxes": {"short_term_rate": 0.24, "long_term_rate": 0.15, "short_term_gain_policy": None},
    "guardrails": {"pre_buy_check": True},
    "replies": {"follow_ups": False, "pages": True},
    "lessons": False,
    "meta": {"seen_version": None, "migrated_from": [], "migration_warnings": [], "migrated_at": None, "retired": {}},
    "history": [],
}


def is_tax_advantaged(raw_type: object) -> bool:
    text = str(raw_type or "").lower()
    return any(k in text for k in TAX_ADV_KEYWORDS)


# ---- value parsers: each takes CLI text or an already-typed value, returns the validated value ----

_TRUE = {"true", "on", "yes"}
_FALSE = {"false", "off", "no"}


def _is_none(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip().lower() == "none")


def _bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise InvalidInput(f"expected on/off (true/false, yes/no), got {raw!r}")


def _number(raw: Any) -> float:
    if isinstance(raw, bool):
        raise InvalidInput(f"expected a number, got {raw!r}")
    try:
        num = float(raw) if isinstance(raw, str) else raw + 0
        if math.isfinite(num):
            return num
    except (ValueError, TypeError, OverflowError):
        pass
    raise InvalidInput(f"expected a finite number, got {raw!r}")


def _choice(options: tuple[str, ...], *, nullable: bool = False) -> Callable[[Any], Any]:
    def parse(raw: Any) -> Any:
        if nullable and _is_none(raw):
            return None
        text = str(raw).strip().lower()
        if text not in options:
            raise InvalidInput(f"expected one of {', '.join(options)}{' or none' if nullable else ''}, got {raw!r}")
        return text
    return parse


def _ask_above(raw: Any) -> int:
    num = _number(raw)
    if num != int(num) or num < 1:
        raise InvalidInput(f"expected a whole number of 1 or more, got {raw!r}")
    return int(num)


def _ceiling(raw: Any) -> float | None:
    """A share above 0 and up to 1, or none (a sleeve target; also the schema-1 ceiling)."""
    if _is_none(raw):
        return None
    num = _number(raw)
    if not 0 < num <= 1:
        raise InvalidInput(f"expected a share above 0 and up to 1, got {raw!r}")
    return num


def _glide(raw: Any) -> dict[str, Any] | None:
    """A target with a date: {"to": share, "by": "YYYY-MM-DD"}, or none."""
    if _is_none(raw):
        return None
    value = _json(raw)
    if not isinstance(value, dict) or set(value) != {"to", "by"}:
        raise InvalidInput('glide must be {"to": share, "by": "YYYY-MM-DD"} or none')
    try:
        by = date.fromisoformat(str(value["by"])).isoformat()
    except ValueError:
        raise InvalidInput(f"glide.by must be YYYY-MM-DD, got {value['by']!r}") from None
    to = _ceiling(value["to"])
    if to is None:
        raise InvalidInput("glide.to must be a share above 0 and up to 1")
    return {"to": to, "by": by}


def _rate(raw: Any) -> float:
    num = _number(raw)
    if not 0 <= num < 1:
        raise InvalidInput(f"expected a rate from 0 up to (not including) 1, got {raw!r}")
    return num


def _fraction(raw: Any) -> float:
    num = _number(raw)
    if not 0 < num <= 1:
        raise InvalidInput(f"expected a band above 0 and up to 1, got {raw!r}")
    return num


def _cash_reserve(raw: Any) -> float | None:
    if _is_none(raw):
        return None
    num = _number(raw)
    if num < 0:
        raise InvalidInput(f"expected an amount of 0 or more, got {raw!r}")
    return num


def _json(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        raise InvalidInput(f"expected JSON, got {raw!r}") from None


def _targets(raw: Any) -> dict[str, float]:
    value = _json(raw)
    if not isinstance(value, dict):
        raise InvalidInput("targets must be an object of symbol to weight")
    out = {str(k): _number(v) for k, v in value.items()}
    if any(w < 0 for w in out.values()):
        raise InvalidInput("target weights cannot be negative")
    if out and abs(sum(out.values()) - 1) > 0.001:
        raise InvalidInput(f"target weights must sum to 1 (+/- 0.001), they sum to {sum(out.values()):.4f}")
    return out


def _classes(raw: Any) -> dict[str, str]:
    value = _json(raw)
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        raise InvalidInput("classes must be an object of symbol to target key")
    return dict(value)


def _list(raw: Any) -> list[Any]:
    value = _json(raw)
    if not isinstance(value, list):
        raise InvalidInput("expected a list")
    return value


def _step_up(raw: Any) -> Any:
    if _is_none(raw):
        return None
    value = _json(raw)
    if not isinstance(value, dict):
        raise InvalidInput("expected an object or none")
    return value


def _members(raw: Any) -> list[str] | None:
    from second_opinion.brokerage import validate_symbol
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().lower() == "none":
        return []
    if isinstance(raw, str):
        raw = [s for s in re.split(r"[,\s]+", raw) if s]
    if not isinstance(raw, list):
        raise InvalidInput("expected a list of tickers")
    return [validate_symbol(s) for s in raw]


@dataclass(frozen=True)
class Key:
    default: Any
    label: str
    meaning: str
    parse: Callable[[Any], Any]


def _d(*path: str) -> Any:
    node: Any = DEFAULTS
    for part in path:
        node = node[part]
    return copy.deepcopy(node)


KEYS: dict[str, Key] = {
    "depth": Key(_d("depth"), "Depth", "standard answers once; deep runs the heavy multi-step research", _choice(DEPTHS)),
    "deep.ask_above": Key(_d("deep", "ask_above"), "Deep: ask above", "ask before a deep run touching more than this many items", _ask_above),
    "plan.targets": Key(_d("plan", "targets"), "Targets", "target weights by key, summing to 1", _targets),
    "plan.classes": Key(_d("plan", "classes"), "Classes", "symbol to target key", _classes),
    "plan.cash_reserve": Key(None, "Cash reserve", "cash to keep out of the plan", _cash_reserve),
    "plan.bands.absolute": Key(_d("plan", "bands", "absolute"), "Absolute band", "drift in weight that breaches", _fraction),
    "plan.bands.relative": Key(_d("plan", "bands", "relative"), "Relative band", "drift relative to target that breaches", _fraction),
    "plan.sleeves.PICKS.target": Key(None, "Picks target", "the picks sleeve's share of the portfolio (plan.targets.PICKS wins when targets are saved); none leaves its size unmanaged", _ceiling),
    "plan.sleeves.PICKS.glide": Key(None, "Picks glide", 'a target with a date, {"to": share, "by": "YYYY-MM-DD"}: new money goes to the sleeve first until it reaches "to"', _glide),
    "plan.sleeves.PICKS.weighting": Key(None, "Picks weighting", "how picks split the sleeve", _choice(WEIGHTINGS, nullable=True)),
    "plan.sleeves.PICKS.include_light": Key(None, "Include light picks", "size light picks into the sleeve", lambda r: None if _is_none(r) else _bool(r)),
    "plan.sleeves.EMPLOYER.members": Key(None, "Employer members", "tickers of employer exposure; none for no exposure", _members),
    "plan.sleeves.EMPLOYER.policy": Key(None, "Employer policy", "sell_on_arrival sells vested shares when they arrive; hold keeps them", _choice(EMPLOYER_POLICIES, nullable=True)),
    "taxes.short_term_rate": Key(_d("taxes", "short_term_rate"), "Short-term rate", "tax rate on short-term gains", _rate),
    "taxes.long_term_rate": Key(_d("taxes", "long_term_rate"), "Long-term rate", "tax rate on long-term gains", _rate),
    "taxes.short_term_gain_policy": Key(None, "Short-term gains", "hold or allow selling into short-term gains", _choice(GAIN_POLICIES, nullable=True)),
    "guardrails.pre_buy_check": Key(True, "Pre-buy check", "check a buy against the plan before ordering", _bool),
    "replies.follow_ups": Key(False, "Follow-ups", "end replies with follow-up suggestions", _bool),
    "replies.pages": Key(True, "Pages", "publish long answers as pages", _bool),
    "lessons": Key(False, "Lessons", "learn from reviewed outcomes", _bool),
}

_ACCOUNT_KEYS = {
    "role": Key(None, "Account role", "trading, retirement or savings; none uses the account-type heuristic", _choice(ROLES, nullable=True)),
    "margin": Key(False, "Account margin", "Recorded from BROKER_ACCOUNT_TYPES; brokerage scripts still read .env for now", _bool),
    "whole_shares": Key(False, "Whole shares only", "the broker refuses fractional orders here; plans that touch it size in whole shares", _bool),
}
_SLEEVE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SLEEVE_FIELDS = ("target", "glide", "weighting", "include_light", "members", "policy")
_EMPLOYER_FIELDS = ("members", "policy")


def _lookup(key: str) -> Key:
    if key in KEYS:
        return KEYS[key]
    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "accounts" and parts[1] and parts[2] in _ACCOUNT_KEYS:
        return _ACCOUNT_KEYS[parts[2]]
    if len(parts) == 4 and parts[:2] == ["plan", "sleeves"] and _SLEEVE_RE.match(parts[2]) and parts[3] in _SLEEVE_FIELDS:
        return KEYS[f"plan.sleeves.{'EMPLOYER' if parts[3] in _EMPLOYER_FIELDS else 'PICKS'}.{parts[3]}"]
    raise InvalidInput(f"unknown setting {key!r}; known: {', '.join(KEYS)}, accounts.<id>.role|margin|whole_shares, plan.sleeves.<NAME>.*")


def parse(key: str, raw: str) -> Any:
    return _lookup(key).parse(raw)


# ---- the file ----

def path() -> Path:
    return config.data_dir() / FILE


def _corrupt(why: str) -> ApiError:
    p = path()
    return ApiError(f"settings at {p} {why}", code="SETTINGS_CORRUPT", hint=f"fix {p} by hand, or move it aside to start from the defaults")


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else copy.deepcopy(v)
    return out


def _walk(doc: dict[str, Any], dotted: str) -> Any:
    node: Any = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    return node


def _validate(doc: dict[str, Any]) -> None:
    """Raise InvalidInput when a stored value fails its key's validation or the document's shape is wrong."""
    for dotted in ("deep", "plan", "plan.bands", "plan.sleeves", "taxes", "guardrails", "replies", "meta", "accounts"):
        if not isinstance(_walk(doc, dotted), dict):
            raise InvalidInput(f"{dotted} must be an object")
    if not isinstance(doc["history"], list):
        raise InvalidInput("history must be a list")
    for field in ("migrated_from", "migration_warnings"):
        if not isinstance(doc["meta"].get(field), list):
            raise InvalidInput(f"meta.{field} must be a list")
    if not isinstance(doc["meta"].get("retired"), dict):
        raise InvalidInput("meta.retired must be an object")
    for key, spec in KEYS.items():
        try:
            value = _walk(doc, key)
        except KeyError:
            continue
        spec.parse(value)
    for account, entry in doc["accounts"].items():
        if not isinstance(entry, dict):
            raise InvalidInput(f"accounts.{account} must be an object")
        for field, spec in _ACCOUNT_KEYS.items():
            if field in entry:
                spec.parse(entry[field])
    sleeves = doc["plan"]["sleeves"]
    for name, entry in sleeves.items():
        if not isinstance(entry, dict):
            raise InvalidInput(f"plan.sleeves.{name} must be an object")
        for field in entry:
            if field in _SLEEVE_FIELDS and _SLEEVE_RE.match(name):
                _lookup(f"plan.sleeves.{name}.{field}").parse(entry[field])


def load() -> dict[str, Any]:
    """The settings, migrating the older files first while that has never run (``meta.migrated_at`` unset).

    An absent file is built from the old files. A file that exists without the marker (an installer
    wrote its switches before any session ran) still takes the old files' values for the keys it
    does not hold, and is saved with the marker.
    """
    from second_opinion import settings_migrate  # imported here: it imports this module

    p = path()
    if not p.exists():
        migrated = settings_migrate.migrate(p.parent)
        return _merge(DEFAULTS, migrated or {})
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        raise _corrupt(f"is not readable JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise _corrupt("is not a JSON object")
    upgraded = raw.get("schema") == 1
    if upgraded:
        raw = settings_migrate.upgrade(raw)
    try:
        doc = _merge(DEFAULTS, raw)
        if not isinstance(doc["schema"], int) or isinstance(doc["schema"], bool):
            raise InvalidInput("schema must be a whole number")
        if doc["schema"] <= SCHEMA:
            _validate(doc)
    except (InvalidInput, TypeError, AttributeError, ValueError, OverflowError) as exc:
        raise _corrupt(f"holds an invalid value ({exc})") from exc
    if doc["schema"] <= SCHEMA and not doc["meta"].get("migrated_at") and settings_migrate.pending(p.parent):
        migrated = settings_migrate.migrate(p.parent, existing=raw)
        if migrated is not None:
            return _merge(DEFAULTS, migrated)
    if upgraded:
        save(doc)
    return doc


def get(key: str) -> Any:
    spec = _lookup(key)
    try:
        return _walk(load(), key)
    except KeyError:
        return copy.deepcopy(spec.default)


def _refuse_newer(doc: dict[str, Any]) -> None:
    if isinstance(doc.get("schema"), int) and doc["schema"] > SCHEMA:
        raise ApiError(
            f"settings were written by a newer plugin (schema {doc['schema']}, this one writes {SCHEMA})",
            code="SETTINGS_NEWER", hint="update the Second Opinion plugin; settings.json is left untouched",
        )


def save(doc: dict[str, Any], *, exclusive: bool = False) -> Path | None:
    """Write ``doc`` atomically (0600). Every save marks the migration done: callers ``load()`` first,
    and that has already migrated whatever was pending. ``exclusive`` creates the file only when it
    does not exist yet (the first migration) and returns None, writing nothing, when it does."""
    _refuse_newer(doc)
    meta = doc.setdefault("meta", {})
    if isinstance(meta, dict) and not meta.get("migrated_at"):
        meta["migrated_at"] = date.today().isoformat()
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(doc, indent=1) + "\n")
        os.chmod(tmp, 0o600)
        if not exclusive:
            os.replace(tmp, p)
            return p
        try:
            os.link(tmp, p)  # no-clobber: fails when another process created the file first
        except FileExistsError:
            return None
        except OSError:  # no hard links on this filesystem: a narrower check-then-replace
            if p.exists():
                return None
            os.replace(tmp, p)
        return p
    finally:
        Path(tmp).unlink(missing_ok=True)


def set_value(key: str, value: Any, *, today: date | None = None) -> dict[str, Any]:
    spec = _lookup(key)
    value = spec.parse(value)
    doc = load()
    _refuse_newer(doc)
    node = doc
    parts = key.split(".")
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value
    doc["history"].append({"date": (today or date.today()).isoformat(), "key": key, "value": value})
    save(doc)
    return doc


def sleeve_target(doc: dict[str, Any], name: str) -> float | None:
    """A sleeve's target weight: plan.targets[name] when saved targets name it, else the sleeve's own target."""
    targets = doc["plan"].get("targets") or {}
    if name in targets:
        return float(targets[name])
    entry = (doc["plan"].get("sleeves") or {}).get(name) or {}
    return entry.get("target")


def glide_target(doc: dict[str, Any], name: str, today: date | None = None) -> float | None:
    """The target in force: the glide's ``to`` when a glide is saved, else sleeve_target.

    The glide's date sets the pace (status reports the monthly amount); the target in force is ``to``."""
    entry = (doc["plan"].get("sleeves") or {}).get(name) or {}
    glide = entry.get("glide")
    if glide:
        return float(glide["to"])
    return sleeve_target(doc, name)


def depth() -> str:
    """The saved research depth, "standard" or "deep". Unreadable settings raise SETTINGS_CORRUPT."""
    return get("depth")


def is_deep() -> bool:
    return depth() == "deep"


def whole_shares(account_ids) -> bool:
    """True when any of ``account_ids`` is saved as whole-shares only."""
    return any(get(f"accounts.{a}.whole_shares") for a in account_ids if a)


def account_role(account_id: str, raw_type: str | None) -> str:
    saved = get(f"accounts.{account_id}.role") if account_id else None
    if saved:
        return saved
    return "retirement" if is_tax_advantaged(raw_type) else "trading"
