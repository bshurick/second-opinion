#!/usr/bin/env python3
"""Usage: settings.py show
       settings.py get KEY [--plain]
       settings.py set KEY VALUE
       settings.py version
       settings.py notice

The one command-line door to ``settings.json`` (the plugin data dir). ``show`` prints every setting
by group with its value, default, meaning and the date it last changed (saved per-account and
per-sleeve keys included), the skills that have a deep path (``deep_paths``), plus the migration warnings. ``get --plain`` prints the bare value
(on/off for booleans) for hooks. ``set`` validates, records history and prints the previous value.
``version`` reports the installed plugin version, the latest one found in the local marketplace
clone (no network), the version last announced, and the command that updates this install.
``notice`` (plain text, always exit 0, never fails) is for the SessionStart hook: the first time it
records the installed version and is silent on a fresh install, or says once that the settings moved
into settings.json (with the count of any that could not be moved) after an upgrade from 1.0.0;
after that, one line after each update, then silent again.

Every subcommand takes a hidden --today YYYY-MM-DD for tests. Test-only environment overrides:
SECOND_OPINION_PLUGIN_JSON (path of the installed plugin.json) and SECOND_OPINION_LATEST_PLUGIN_JSON
(path of the marketplace clone's plugin.json). Exit codes: 0, 2 (bad input), 5 (settings corrupt or
written by a newer plugin).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

from second_opinion import config, output, settings  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

GROUPS = ("Depth", "Accounts", "Portfolio plan", "Taxes", "Guardrails", "Replies", "Lessons")
_GROUP_OF = {"depth": "Depth", "deep": "Depth", "accounts": "Accounts", "plan": "Portfolio plan", "taxes": "Taxes",
             "guardrails": "Guardrails", "replies": "Replies", "lessons": "Lessons"}
MARKETPLACE_UPDATE = ("claude plugin marketplace update second-opinion && "
                      "claude plugin update second-opinion@second-opinion, then restart Claude Code")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"settings.py: {message}")


def _day(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise InvalidInput(f"--today must be YYYY-MM-DD, got {text!r}") from exc


def _dig(doc: dict, dotted: str) -> Any:
    try:
        return settings._walk(doc, dotted)
    except KeyError:
        return settings._lookup(dotted).default


def _dynamic(doc: dict) -> list[str]:
    keys: list[str] = []
    for acct, entry in sorted(doc["accounts"].items()):
        if isinstance(entry, dict):
            keys += [f"accounts.{acct}.{f}" for f in settings._ACCOUNT_KEYS if f in entry]
    for name, entry in sorted(doc["plan"]["sleeves"].items()):
        if isinstance(entry, dict) and settings._SLEEVE_RE.match(name):
            keys += [k for f in settings._SLEEVE_FIELDS if f in entry and (k := f"plan.sleeves.{name}.{f}") not in settings.KEYS]
    return keys


def show() -> dict:
    doc = settings.load()
    changed: dict[str, str] = {}
    for h in doc["history"]:
        if isinstance(h, dict) and "key" in h and "date" in h:
            changed[h["key"]] = max(changed.get(h["key"], ""), str(h["date"]))
    groups: dict[str, list] = {g: [] for g in GROUPS}
    for key in [*settings.KEYS, *_dynamic(doc)]:
        spec = settings._lookup(key)
        value = _dig(doc, key)
        groups[_GROUP_OF[key.split(".")[0]]].append({
            "key": key, "label": spec.label, "value": value, "default": spec.default,
            "is_default": value == spec.default, "meaning": spec.meaning, "changed_on": changed.get(key),
        })
    return {"groups": [{"group": g, "rows": groups[g]} for g in GROUPS],
            "deep_paths": [{"skill": k, "what": settings.DEEP_PATHS[k]} for k in sorted(settings.DEEP_PATHS)],
            "warnings": list(doc["meta"].get("migration_warnings") or [])}


def _plain(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "none"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _read_version(path: Path) -> str | None:
    try:
        v = json.loads(path.read_text()).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return v if isinstance(v, str) and v else None


def _installed_json() -> Path:
    env = os.environ.get("SECOND_OPINION_PLUGIN_JSON")
    return Path(env) if env else config.PLUGIN_ROOT / ".claude-plugin" / "plugin.json"


def _latest_json() -> Path:
    env = os.environ.get("SECOND_OPINION_LATEST_PLUGIN_JSON")
    return Path(env) if env else Path.home() / ".claude" / "plugins" / "marketplaces" / "second-opinion" / ".claude-plugin" / "plugin.json"


def update_command() -> str:
    root = str(config.PLUGIN_ROOT)
    plugins = Path.home() / ".claude" / "plugins"
    in_market = any(root.startswith(str(plugins / d) + os.sep) for d in ("marketplaces", "cache"))
    record = config.installed_record() or {}
    source = record.get("source_path")
    if in_market or not (isinstance(source, str) and source):
        return MARKETPLACE_UPDATE
    return f"cd {source} && git pull && node install.js"


def version_report() -> dict:
    installed = _read_version(_installed_json())
    seen = settings.load()["meta"].get("seen_version")
    return {"installed": installed, "latest": _read_version(_latest_json()), "seen": seen,
            "updated": seen is not None and seen != installed, "update_command": update_command()}


def _record_seen(version: str) -> None:
    doc = settings.load()
    doc["meta"]["seen_version"] = version
    settings.save(doc)


def notice() -> str:
    rep = version_report()
    installed, seen = rep["installed"], rep["seen"]
    if installed is None:
        return ""
    if seen is None:
        meta = settings.load()["meta"]
        _record_seen(installed)
        if not meta.get("migrated_from"):
            return ""  # a fresh install: nothing moved, nothing to announce
        text = (f"Second Opinion updated to {installed}: your settings moved into settings.json "
                f'(say "show my settings" to see them).')
        warnings = meta.get("migration_warnings") or []
        if warnings:
            text += f' {len(warnings)} setting(s) could not be moved; "show my settings" lists them.'
        return text
    if seen != installed:
        _record_seen(installed)
        return f"Second Opinion updated to {installed} (was {seen}). What changed: CHANGELOG.md in the plugin folder."
    return ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["notice"]:
        try:
            text = notice()
        except BaseException:  # noqa: BLE001 - the hook never fails the session
            text = ""
        if text:
            print(text)
        return 0

    def go(a: list[str]):
        p = _Parser(prog="settings.py", add_help=False)
        sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)

        def add(name: str) -> argparse.ArgumentParser:
            sp = sub.add_parser(name, add_help=False)
            sp.add_argument("--today", help=argparse.SUPPRESS)
            return sp

        add("show")
        add("version")
        g = add("get")
        g.add_argument("key")
        g.add_argument("--plain", action="store_true")
        s = add("set")
        s.add_argument("key")
        s.add_argument("value")
        ns = p.parse_args(a)
        today = _day(ns.today)
        if ns.cmd == "show":
            return show()
        if ns.cmd == "version":
            return version_report()
        if ns.cmd == "get":
            value = settings.get(ns.key)
            if ns.plain:
                print(_plain(value))
                return None
            return {"key": ns.key, "value": value}
        previous = settings.get(ns.key)
        doc = settings.set_value(ns.key, ns.value, today=today)
        return {"key": ns.key, "value": settings._walk(doc, ns.key), "previous": previous}

    return output.run(go, args)


if __name__ == "__main__":
    sys.exit(main())
