#!/usr/bin/env python3
"""Usage: profile.py set FIELD VALUE...        # declared; lists are comma-separated
       profile.py unset FIELD
       profile.py show
       profile.py skip | complete              # create the profile (onboarding skipped / complete)
       profile.py learning on|off
       profile.py next-steps [--offline]       # setup actions + starter questions
       profile.py context                      # ONE plain-text line for the session-start hook
       profile.py delete --confirm

The user's Second Opinion profile, kept in ``profile.json`` under the plugin
data dir (see lib/second_opinion/profile.py for the format). ``set`` creates
the file with onboarding status "skipped" when it does not exist, so an
interview that stops halfway still keeps its answers. ``complete`` marks the
interview finished. Fields: approach
(value, growth, dividend, index, technical, unsure; several allowed),
horizon (years, months, weeks, mixed), risk_appetite (low, moderate, high),
experience (beginner, intermediate, experienced), goals (free text list),
pre_trade_check (valuation, fundamentals, chart, none), account_roles
(id=trading|retirement|savings, comma-separated), trades_actively and
uses_options (yes/no). ``next-steps`` reads which skills are installed from
the plugin's skills directory, whether a brokerage key is configured, how
many accounts are connected (skipped with --offline or when no key is set),
and whether EDGAR_USER_AGENT is set. Every command prints JSON except
``context``, which prints one line of text. Exit codes: 0, 2, 3 (delete
without --confirm), 4 (NO_PROFILE for show/unset/learning/next-steps before
onboarding), 5 (PROFILE_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import config, output  # noqa: E402
from second_opinion import profile as lib  # noqa: E402
from second_opinion.errors import ConfigError, InvalidInput, NotConfirmed  # noqa: E402

_HINT = "say 'get started with Second Opinion' to answer the onboarding questions, or 'skip for now'"
_DAMAGED_LINE = "Second Opinion profile file could not be read; say 'show my profile' to see the error and the fix."


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"usage: profile.py set|unset|show|skip|complete|learning|next-steps|context|delete ({message})")


def _require() -> dict:
    p = lib.load()
    if p is None:
        raise ConfigError("no Second Opinion profile exists yet", code="NO_PROFILE", hint=_HINT)
    return p


def _show(p: dict) -> dict:
    pending = [x for x in p.get("proposals", []) if x.get("status") == "pending"]
    return {**p, "summary": lib.summary(p), "pending_proposals": pending, "path": str(lib.profile_path())}


def _installed_skills() -> set[str]:
    root = config.PLUGIN_ROOT / "skills"
    return {d.name for d in root.iterdir() if (d / "SKILL.md").is_file()} if root.is_dir() else set()


def _connection_state(offline: bool) -> tuple[bool, int]:
    settings = config.load_settings()
    configured = settings.snaptrade is not None or settings.etrade is not None
    if offline or not configured:
        return configured, 0
    from second_opinion.brokers import router  # noqa: PLC0415 — needs the venv; only on the online path

    hub = router.try_load()
    if hub is None:
        return configured, 0
    hub.partial = True  # background count: never start a login here
    try:
        return configured, len(hub.list_accounts())
    except Exception:  # noqa: BLE001 — a brokerage hiccup must not break next-steps
        return configured, 0


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict | None:
        p = _Parser(prog="profile.py", add_help=False)
        sub = p.add_subparsers(dest="command")
        s = sub.add_parser("set", add_help=False)
        s.add_argument("field")
        s.add_argument("value", nargs="+")
        u = sub.add_parser("unset", add_help=False)
        u.add_argument("field")
        sub.add_parser("show", add_help=False)
        sub.add_parser("skip", add_help=False)
        sub.add_parser("complete", add_help=False)
        le = sub.add_parser("learning", add_help=False)
        le.add_argument("state", choices=["on", "off"])
        ns_ = sub.add_parser("next-steps", add_help=False)
        ns_.add_argument("--offline", action="store_true")
        sub.add_parser("context", add_help=False)
        d = sub.add_parser("delete", add_help=False)
        d.add_argument("--confirm", action="store_true")
        ns = p.parse_args(args)

        if ns.command == "set":
            prof = lib.load() or lib.new_profile("skipped")
            lib.set_field(prof, ns.field, " ".join(ns.value))
            lib.save(prof)
            f = prof["fields"][ns.field]
            return {"field": ns.field, "value": f["value"], "source": f["source"], "at": f["at"], "path": str(lib.profile_path())}
        if ns.command == "unset":
            prof = _require()
            lib.unset_field(prof, ns.field)
            lib.save(prof)
            return _show(prof)
        if ns.command == "show":
            return _show(_require())
        if ns.command in ("skip", "complete"):
            prof = lib.load() or lib.new_profile("skipped" if ns.command == "skip" else "complete")
            if ns.command == "complete" and prof["onboarding"]["status"] != "complete":
                prof["onboarding"] = {"status": "complete", "at": lib._today(None), "version": lib.INTERVIEW_VERSION}
                prof["updated"] = lib._today(None)
            lib.save(prof)
            return _show(prof)
        if ns.command == "learning":
            prof = _require()
            prof["learning"] = ns.state == "on"
            if not prof["learning"]:
                prof["proposals"] = [x for x in prof.get("proposals", []) if x.get("status") != "pending"]
            prof["updated"] = lib._today(None)
            lib.save(prof)
            return _show(prof)
        if ns.command == "next-steps":
            prof = _require()
            installed = _installed_skills()
            configured, accounts = _connection_state(ns.offline)
            from second_opinion import edgar  # noqa: PLC0415

            steps = lib.next_steps(
                prof,
                installed=installed,
                brokerage_configured=configured,
                connected_accounts=accounts,
                edgar_configured=not edgar.user_agent_is_default(),
            )
            return {**steps, "installed_skills": sorted(installed), "brokerage_configured": configured, "connected_accounts": accounts}
        if ns.command == "context":
            try:
                line = lib.context_line(lib.load())
            except Exception:  # noqa: BLE001 — session start must get one line, whatever the file holds
                line = _DAMAGED_LINE
            print(line)
            return None
        if ns.command == "delete":
            if not ns.confirm:
                raise NotConfirmed("delete needs --confirm; it removes profile.json and usage.jsonl")
            deleted = []
            for path in (lib.profile_path(), lib.usage_path()):
                if path.exists():
                    path.unlink()
                    deleted.append(path.name)
            return {"deleted": deleted}
        raise InvalidInput("usage: profile.py set|unset|show|skip|complete|learning|next-steps|context|delete")

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
