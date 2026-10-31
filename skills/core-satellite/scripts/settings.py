#!/usr/bin/env python3
"""Usage: settings.py show
       settings.py decide KEY VALUE
       settings.py record-increase --amount A --before W --after W --funded-from TEXT [--date YYYY-MM-DD]
       settings.py plan-set --target W --by YYYY-MM-DD --cadence monthly|quarterly --funding cash|core
       settings.py plan-pause | plan-resume | plan-cancel | plan-advance
       settings.py summary

The core/satellite settings, kept in ``core-satellite.json`` under the plugin data dir: the saved
decisions, the satellite increases made so far and the step-up plan. Unset keys are null; readers
treat a null ceiling as the default ceiling and ask the person once.

``decide`` keys: ceiling (0 < x <= 1; also stamps ceiling_agreed_on), weighting (size|valuation),
include_light (true|false), short_term_gain_policy (hold|allow), employer_symbol (ticker or none).
Each call appends to ``decisions``. ``plan-set`` starts a plan due today (--by before today is bad
input); ``plan-advance`` (active plans only) moves next_due one cadence on (same day, clamped to
month end) and sets status done once past the end date; ``plan-resume`` works only on a paused
plan. ``summary`` (no network; for the SessionStart hook) prints plain text when an active plan
step is due, nothing otherwise, and always exits 0.

Every subcommand takes a hidden --today YYYY-MM-DD for tests. Output (JSON, except summary): the
whole store after the change. Exit codes: 0, 2 (bad input), 5 (unreadable store).
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

from second_opinion import brokerage, ledger, output  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

STORE_FILE = "core-satellite.json"
CADENCE_MONTHS = {"monthly": 1, "quarterly": 3}
EMPTY = {
    "ceiling": None,
    "ceiling_agreed_on": None,
    "weighting": None,
    "include_light": None,
    "short_term_gain_policy": None,
    "employer_symbol": None,
    "decisions": [],
    "increases": [],
    "plan": None,
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"settings.py: {message}")


def store_path() -> Path:
    return ledger.ledger_path().parent / STORE_FILE


def load() -> dict:
    path = store_path()
    store = {k: (list(v) if isinstance(v, list) else v) for k, v in EMPTY.items()}
    if not path.is_file():
        return store
    try:
        raw = json.loads(path.read_text())
    except ValueError as exc:
        raise ApiError(f"settings at {path} is not valid JSON", code="LEDGER_CORRUPT", hint=f"move or delete {path}") from exc
    if not isinstance(raw, dict):
        raise ApiError(f"settings at {path} has an unexpected shape", code="LEDGER_CORRUPT", hint=f"move or delete {path}")
    store.update(raw)
    return store


def save(store: dict) -> Path:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=1))
    return path


def _day(text: str, what: str) -> date:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise InvalidInput(f"{what} must be YYYY-MM-DD, got {text!r}") from exc


def _parse_value(key: str, raw: str):
    if key == "ceiling":
        try:
            x = float(raw)
        except ValueError as exc:
            raise InvalidInput(f"ceiling must be a number above 0 and at most 1, got {raw!r}") from exc
        if not 0 < x <= 1:
            raise InvalidInput(f"ceiling must be above 0 and at most 1, got {raw}")
        return x
    if key == "weighting":
        if raw not in ("equal", "market_cap", "valuation", "size"):
            raise InvalidInput(f"weighting must be equal, market_cap, valuation or size, got {raw!r}")
        return raw
    if key == "include_light":
        if raw.lower() not in ("true", "false"):
            raise InvalidInput(f"include_light must be true or false, got {raw!r}")
        return raw.lower() == "true"
    if key == "short_term_gain_policy":
        if raw not in ("hold", "allow"):
            raise InvalidInput(f"short_term_gain_policy must be hold or allow, got {raw!r}")
        return raw
    if key == "employer_symbol":
        return "none" if raw.lower() == "none" else brokerage.validate_symbol(raw)
    raise InvalidInput(f"unknown key {key!r}; keys are ceiling, weighting, include_light, short_term_gain_policy, employer_symbol")


def decide(store: dict, key: str, raw: str, today: date) -> dict:
    value = _parse_value(key, raw)
    store[key] = value
    if key == "ceiling":
        store["ceiling_agreed_on"] = today.isoformat()
    store["decisions"].append({"date": today.isoformat(), "key": key, "value": value})
    return store


def record_increase(store: dict, row: dict) -> dict:
    store["increases"].append({k: row.get(k) for k in ("date", "amount", "weight_before", "weight_after", "funded_from")})
    return store


def _add_months(d: date, months: int) -> date:
    idx = d.year * 12 + d.month - 1 + months
    year, month = divmod(idx, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _need_plan(store: dict) -> dict:
    if not store.get("plan"):
        raise InvalidInput("no plan is set; plan-set creates one")
    return store["plan"]


def _need_status(plan: dict, status: str, cmd: str) -> None:
    if plan.get("status") != status:
        raise InvalidInput(f"{cmd} needs a {status} plan; the plan is {plan.get('status')}")


def plan_advance(store: dict) -> dict:
    plan = _need_plan(store)
    _need_status(plan, "active", "plan-advance")
    nxt = _add_months(_day(plan["next_due"], "next_due"), CADENCE_MONTHS[plan["cadence"]])
    plan["next_due"] = nxt.isoformat()
    if nxt > _day(plan["by_date"], "by_date"):
        plan["status"] = "done"
    return store


def summary_lines(today: date | None = None) -> list[str]:
    today = today or date.today()
    plan = load().get("plan")
    if not isinstance(plan, dict) or plan.get("status") != "active" or not plan.get("next_due"):
        return []
    if plan["next_due"] > today.isoformat():
        return []
    return [f"Core/satellite: plan step due since {plan['next_due']} (target {float(plan['target']) * 100:.1f}% by {plan['by_date']}); ask Claude to run it."]


def _today(ns) -> date:
    return _day(ns.today, "--today") if ns.today else date.today()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["summary"]:
        try:
            today = date.fromisoformat(args[args.index("--today") + 1]) if "--today" in args else None
            lines = summary_lines(today)
        except Exception:  # noqa: BLE001 - the hook never fails the session
            lines = []
        if lines:
            print("\n".join(lines))
        return 0

    def go(a: list[str]):
        p = _Parser(prog="settings.py", add_help=False)
        sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)

        def add(name: str) -> argparse.ArgumentParser:
            sp = sub.add_parser(name, add_help=False)
            sp.add_argument("--today", help=argparse.SUPPRESS)
            return sp

        add("show")
        d = add("decide")
        d.add_argument("key")
        d.add_argument("value")
        ri = add("record-increase")
        ri.add_argument("--amount", type=float, required=True)
        ri.add_argument("--before", type=float, required=True)
        ri.add_argument("--after", type=float, required=True)
        ri.add_argument("--funded-from", required=True)
        ri.add_argument("--date")
        ps = add("plan-set")
        ps.add_argument("--target", type=float, required=True)
        ps.add_argument("--by", required=True)
        ps.add_argument("--cadence", choices=sorted(CADENCE_MONTHS), required=True)
        ps.add_argument("--funding", choices=("cash", "core"), required=True)
        for name in ("plan-pause", "plan-resume", "plan-cancel", "plan-advance"):
            add(name)
        ns = p.parse_args(a)
        today = _today(ns)
        store = load()
        if ns.cmd == "show":
            return store
        if ns.cmd == "decide":
            decide(store, ns.key, ns.value, today)
        elif ns.cmd == "record-increase":
            when = _day(ns.date, "--date") if ns.date else today
            record_increase(store, {"date": when.isoformat(), "amount": round(ns.amount, 2), "weight_before": round(ns.before, 4), "weight_after": round(ns.after, 4), "funded_from": ns.funded_from})
        elif ns.cmd == "plan-set":
            if not 0 < ns.target <= 1:
                raise InvalidInput(f"--target must be above 0 and at most 1, got {ns.target}")
            if _day(ns.by, "--by") < today:
                raise InvalidInput(f"--by {ns.by} is before today ({today.isoformat()})")
            store["plan"] = {"target": ns.target, "by_date": ns.by, "cadence": ns.cadence, "step_amount": None, "funding": ns.funding, "status": "active", "next_due": today.isoformat(), "created": today.isoformat()}
        elif ns.cmd == "plan-pause":
            _need_plan(store)["status"] = "paused"
        elif ns.cmd == "plan-resume":
            plan = _need_plan(store)
            _need_status(plan, "paused", "plan-resume")
            plan["status"] = "active"
        elif ns.cmd == "plan-cancel":
            _need_plan(store)["status"] = "cancelled"
        else:
            plan_advance(store)
        save(store)
        return store

    return output.run(go, args)


if __name__ == "__main__":
    sys.exit(main())
