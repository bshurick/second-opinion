"""Build the first ``settings.json`` from the plugin's older scattered files.

Called by ``settings.load()`` while the migration has never run: when ``settings.json`` is absent, or
when it exists without ``meta.migrated_at`` and an old file still holds a setting (an installer wrote
its switches before the first session). The keys already in such a file win. Reads ``installed.json``,
``core-satellite.json``, ``targets.json`` and ``profile.json`` as raw JSON (never through the store
modules, which will import ``settings``), plus the account-type env vars for margin flags. Each value is
checked with the setting's own parser; one that fails is dropped and reported in
``meta.migration_warnings`` instead of aborting the migration. ``core-satellite.json`` and
``targets.json`` are renamed to ``.migrated`` after the save; ``installed.json``, ``profile.json`` and
``.env`` stay. A source that does not parse is left in place and reported.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from second_opinion import config, settings
from second_opinion.errors import ApiError, InvalidInput

_RENAMED = ("core-satellite.json", "targets.json")
_PICKS_FIELDS = ("ceiling", "weighting", "include_light", "increases")
_SLEEVE = "plan.sleeves"
# Schema-1 picks fields with no schema-2 key: parsed here, kept raw, then mapped by upgrade().
_LEGACY = {
    f"{_SLEEVE}.PICKS.ceiling": lambda raw: settings._ceiling(raw),
    f"{_SLEEVE}.PICKS.increases": lambda raw: settings._list(raw),
    f"{_SLEEVE}.PICKS.step_up": lambda raw: settings._step_up(raw),
}
_HISTORY_KEYS = {
    "ceiling": f"{_SLEEVE}.PICKS.ceiling",
    "weighting": f"{_SLEEVE}.PICKS.weighting",
    "include_light": f"{_SLEEVE}.PICKS.include_light",
    "increases": f"{_SLEEVE}.PICKS.increases",
    "plan": f"{_SLEEVE}.PICKS.step_up",
    "employer_symbol": f"{_SLEEVE}.EMPLOYER.members",
    "short_term_gain_policy": "taxes.short_term_gain_policy",
}


class _Build:
    def __init__(self) -> None:
        self.doc = copy.deepcopy(settings.DEFAULTS)
        self.warnings: list[str] = []
        self.contributed: set[str] = set()
        self.unreadable: set[str] = set()

    def warn(self, source: str, why: object) -> None:
        self.warnings.append(f"{source}: {why}")

    def read(self, data_dir: Path, name: str) -> dict[str, Any] | None:
        p = data_dir / name
        if not p.is_file():
            return None
        try:
            raw = json.loads(p.read_text())
        except (OSError, ValueError) as exc:
            self.unreadable.add(name)
            self.warn(name, f"not readable JSON ({exc}); left in place")
            return None
        if not isinstance(raw, dict):
            self.unreadable.add(name)
            self.warn(name, "not a JSON object; left in place")
            return None
        return raw

    def put(self, source: str, key: str, raw: Any) -> bool:
        """Parse ``raw`` as the setting ``key`` and store it; a refused value is reported and dropped."""
        try:
            value = _LEGACY[key](raw) if key in _LEGACY else settings.parse(key, raw)
        except (InvalidInput, ApiError, TypeError, ValueError) as exc:
            self.warn(source, f"{key} dropped ({exc})")
            return False
        node = self.doc
        parts = key.split(".")
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
        if value not in (None, [], {}):
            self.contributed.add(source)
        return True


def _installed(b: _Build, data_dir: Path) -> None:
    raw = b.read(data_dir, "installed.json")
    if raw is None and "installed.json" not in b.unreadable:
        raw = b.read(config.PLUGIN_ROOT, "installed.json")  # the plugin root's copy, as config.installed_record
    if raw is None:
        return
    extras = raw.get("extras")
    skills = raw.get("skills")
    if not isinstance(extras, dict) and not isinstance(skills, list):
        return
    # Only an extras map is a setting to move. A bare skills list is what the installer writes now,
    # just before its own switches; its values still fill in beside other old files, but it alone
    # never makes a migration (nor a "settings moved" notice).
    counted = isinstance(extras, dict)
    extras = extras if counted else {}
    # the old rule: a boolean extra decides; else a skill extra is on when the skills list names it
    for old, key in config.EXTRA_SETTINGS.items():
        if isinstance(extras.get(old), bool):
            b.put("installed.json", key, extras[old])
        elif old != "follow_ups":
            b.put("installed.json", key, isinstance(skills, list) and old in skills)
    if counted:
        b.contributed.add("installed.json")
    else:
        b.contributed.discard("installed.json")


def _core_satellite(b: _Build, data_dir: Path) -> None:
    name = "core-satellite.json"
    raw = b.read(data_dir, name)
    if raw is None:
        return
    for field in _PICKS_FIELDS:
        if field in raw:
            b.put(name, f"{_SLEEVE}.PICKS.{field}", raw[field])
    if "plan" in raw:
        b.put(name, f"{_SLEEVE}.PICKS.step_up", raw["plan"])
    if "short_term_gain_policy" in raw:
        b.put(name, "taxes.short_term_gain_policy", raw["short_term_gain_policy"])
    if raw.get("employer_symbol") is not None:
        b.put(name, f"{_SLEEVE}.EMPLOYER.members", _employer(raw["employer_symbol"]))
    decisions = raw.get("decisions")
    if not isinstance(decisions, list):
        return
    for entry in decisions:
        old = entry.get("key") if isinstance(entry, dict) else None
        if old not in _HISTORY_KEYS or "date" not in entry or "value" not in entry:
            b.warn(name, f"decision {entry!r} dropped (unrecognised)")
            continue
        value = entry["value"]
        key = _HISTORY_KEYS[old]
        if old == "employer_symbol":
            value = _employer(value)
        try:
            value = _LEGACY[key](value) if key in _LEGACY else settings.parse(key, value)
        except (InvalidInput, ApiError, TypeError, ValueError) as exc:
            b.warn(name, f"decision {old} dropped ({exc})")
            continue
        if old == "ceiling":  # schema 2: the ceiling became the sleeve's target (1.0: none)
            key, value = f"{_SLEEVE}.PICKS.target", (None if value is None or value >= 1 else value)
        elif key in _LEGACY:  # increases and step-up decisions are retired with their values
            continue
        b.doc["history"].append({"date": str(entry["date"]), "key": key, "value": value})
        b.contributed.add(name)


def _employer(symbol: Any) -> Any:
    if symbol is None:
        return None
    if isinstance(symbol, str) and symbol.strip().lower() == "none":
        return []
    return [symbol]


def _targets(b: _Build, data_dir: Path) -> None:
    name = "targets.json"
    raw = b.read(data_dir, name)
    if raw is None:
        return
    for field in ("targets", "classes"):
        if field in raw:
            b.put(name, f"plan.{field}", raw[field])


def _roles(b: _Build, data_dir: Path) -> None:
    raw = b.read(data_dir, "profile.json")
    fields = raw.get("fields") if raw else None
    roles = fields.get("account_roles") if isinstance(fields, dict) else None
    roles = roles.get("value") if isinstance(roles, dict) else None
    if not isinstance(roles, dict):
        return
    for account, role in roles.items():
        try:
            value = settings.parse("accounts.x.role", role)
        except (InvalidInput, ApiError, TypeError, ValueError) as exc:
            b.warn("profile.json", f"accounts.{account}.role dropped ({exc})")
            continue
        b.doc["accounts"].setdefault(str(account), {})["role"] = value
        b.contributed.add("profile.json")


def _margin(b: _Build, env: Mapping[str, str] | None) -> None:
    for var in ("BROKER_ACCOUNT_TYPES", "SNAPTRADE_ACCOUNT_TYPES"):
        text = config.env_value(var) if env is None else str(env.get(var, "")).strip()
        if not text:
            continue
        try:
            kinds = config.parse_account_types(text)
        except (InvalidInput, ApiError) as exc:
            b.warn(var, f"margin flags dropped ({exc})")
            continue
        for account, kind in kinds.items():
            if kind == "margin" and account:
                b.doc["accounts"].setdefault(account, {})["margin"] = True
                b.contributed.add(var)


def _read_quiet(p: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def pending(data_dir: Path) -> bool:
    """True when an old file still holds a setting the migration would move."""
    if any((data_dir / n).is_file() for n in _RENAMED):
        return True
    prof = _read_quiet(data_dir / "profile.json")
    if prof and isinstance(prof.get("fields"), dict) and "account_roles" in prof["fields"]:
        return True
    for d in (data_dir, config.PLUGIN_ROOT):
        rec = _read_quiet(d / "installed.json")
        if rec and isinstance(rec.get("extras"), dict):
            return True
    return False


def _over(doc: dict[str, Any], existing: Mapping[str, Any]) -> dict[str, Any]:
    """``existing`` over the migrated ``doc``: its keys win; history and the meta lists are combined."""
    out = settings._merge(doc, dict(existing))
    old_meta = existing.get("meta") if isinstance(existing.get("meta"), dict) else {}
    for field in ("migrated_from", "migration_warnings"):
        kept = old_meta.get(field) if isinstance(old_meta.get(field), list) else []
        out["meta"][field] = kept + [x for x in doc["meta"][field] if x not in kept]
    kept_history = existing.get("history") if isinstance(existing.get("history"), list) else []
    out["history"] = doc["history"] + kept_history
    return out


def upgrade(raw: Mapping[str, Any], *, note: bool = True) -> dict[str, Any]:
    """Schema 1 to 2: each sleeve's ``ceiling`` below 1 becomes its ``target`` (1 or none: no target),
    a ``step_up`` with ``target`` and ``by_date`` becomes ``glide``, and the schema-1 values
    (``ceiling``, ``increases``, ``step_up``) are kept in ``meta.retired`` under their old keys.
    History is kept verbatim. ``note`` adds "schema 1" to ``meta.migrated_from``."""
    doc = copy.deepcopy(dict(raw))
    if doc.get("schema", 1) != 1:
        return doc
    meta = doc.setdefault("meta", {})
    if not isinstance(meta, dict):
        return doc  # a malformed document stays as it is and fails validation as corrupt
    retired = meta.setdefault("retired", {})
    if not isinstance(retired, dict):
        return doc
    sleeves = ((doc.get("plan") or {}).get("sleeves") or {}) if isinstance(doc.get("plan"), dict) else {}
    for name, entry in (sleeves.items() if isinstance(sleeves, dict) else ()):
        if not isinstance(entry, dict):
            continue
        if "ceiling" in entry:
            ceiling = entry.pop("ceiling")
            if ceiling is not None:
                retired[f"{_SLEEVE}.{name}.ceiling"] = ceiling
                if isinstance(ceiling, (int, float)) and not isinstance(ceiling, bool) and 0 < ceiling < 1:
                    entry["target"] = ceiling
        if "increases" in entry:
            increases = entry.pop("increases")
            if increases:
                retired[f"{_SLEEVE}.{name}.increases"] = increases
        if "step_up" in entry:
            step = entry.pop("step_up")
            if step is not None:
                retired[f"{_SLEEVE}.{name}.step_up"] = step
                try:
                    if isinstance(step, dict) and step.get("target") is not None and step.get("by_date"):
                        entry["glide"] = settings._glide({"to": step["target"], "by": step["by_date"]})
                except InvalidInput:
                    pass
    doc["schema"] = 2
    listed = meta.get("migrated_from", [])
    if note and isinstance(listed, list) and "schema 1" not in listed:
        meta["migrated_from"] = [*listed, "schema 1"]
    return doc


def migrate(data_dir: Path, *, env: Mapping[str, str] | None = None,
            existing: Mapping[str, Any] | None = None) -> dict | None:
    """Save and return the first settings document, or None when no old file holds a setting.

    ``existing`` is the raw ``settings.json`` that is already there without the marker; its keys win.
    With no file there the save never clobbers one that another process created meanwhile: that
    file is returned instead and nothing is renamed.
    """
    b = _Build()
    _installed(b, data_dir)
    _core_satellite(b, data_dir)
    _targets(b, data_dir)
    _roles(b, data_dir)
    _margin(b, env)
    if not b.contributed and not b.unreadable:
        return None
    renamed = [n for n in _RENAMED if (data_dir / n).is_file() and n not in b.unreadable]
    b.doc["meta"]["migrated_from"] = [n for n in ("installed.json", "core-satellite.json", "targets.json", "profile.json")
                                      if n in b.contributed or n in renamed]
    b.doc["meta"]["migration_warnings"] = b.warnings
    b.doc["meta"]["migrated_at"] = date.today().isoformat()
    b.doc["schema"] = 1
    b.doc = upgrade(b.doc, note=False)
    b.doc["meta"]["migration_warnings"] = b.warnings  # the same list b.warn appends to
    if existing is not None:
        b.doc = _over(b.doc, existing)
        b.warnings = b.doc["meta"]["migration_warnings"]
    settings._validate(b.doc)
    # nothing is renamed until this has succeeded
    if existing is not None:
        settings.save(b.doc)
    elif settings.save(b.doc, exclusive=True) is None:
        return settings.load()
    failed = False
    for n in renamed:
        try:
            _rename_aside(data_dir, n)
        except OSError as exc:
            b.warn(n, f"could not be renamed ({exc}); left in place")
            failed = True
    if failed:
        try:
            settings.save(b.doc)
        except (OSError, ApiError):
            pass
    return b.doc


def _rename_aside(data_dir: Path, name: str) -> None:
    """Rename to ``<name>.migrated``, or ``.migrated.1``, ``.2`` ... so an earlier backup is never overwritten."""
    target = data_dir / f"{name}.migrated"
    n = 0
    while target.exists():
        n += 1
        target = data_dir / f"{name}.migrated.{n}"
    (data_dir / name).rename(target)
