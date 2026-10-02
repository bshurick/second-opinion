#!/usr/bin/env python3
"""Usage: progress.py add --level L --concept NAME [--concept NAME ...] [--missed QUIZ_ID ...] [--date YYYY-MM-DD]
       progress.py place --level L
       progress.py list

Learner progress kept in ``learner.json`` under the plugin data dir.
``add`` records one teaching session (level placed at or taught, concepts
covered, quiz ids the learner missed) and prints the session; ``place``
marks the most recent session at a level as the level the learner was
placed at (``placed: true``) and prints it; ``list`` summarizes every
session for the spaced-review protocol in SKILL.md: concepts covered
(sorted union across all sessions), a missed-question history (quiz ids
sorted by how often they were missed, most first) and the learner's
current level (the latest placed session's level, else the latest
session's level, else null when no sessions exist). Sessions in ``list``
are ascending by date (insertion order breaks ties). stdin is unused.
Exit codes: 0, 2, 5 (LEARNER_STATE_CORRUPT -- unreadable/malformed
learner.json; a missing file is not corrupt, it is just an empty state).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import ledger, output  # noqa: E402
from second_opinion.errors import ApiError, InvalidInput  # noqa: E402

LEARNER_FILE = "learner.json"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"progress.py: {message}")


def learner_path() -> Path:
    return ledger.ledger_path().parent / LEARNER_FILE


def load_state() -> dict:
    path = learner_path()
    if not path.is_file():
        return {"sessions": []}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise ApiError(
            f"learner state at {path} is not valid JSON", code="LEARNER_STATE_CORRUPT", hint=f"move or delete {path}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        raise ApiError(
            f"learner state at {path} has an unexpected shape", code="LEARNER_STATE_CORRUPT", hint=f"move or delete {path}"
        )
    return data


def save_state(state: dict) -> Path:
    path = learner_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))
    return path


def _iso(raw: str | None, flag: str) -> str:
    if raw is None:
        return date.today().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise InvalidInput(f"{flag} must be YYYY-MM-DD") from exc


def _add(ns: argparse.Namespace) -> dict:
    level = ns.level.strip().lower()
    if not level:
        raise InvalidInput("--level is required")
    concepts = sorted({c.strip() for c in ns.concept if c.strip()})
    if not concepts:
        raise InvalidInput("--concept is required: name at least one concept covered this session")
    missed = sorted({m.strip() for m in ns.missed if m.strip()})
    when = _iso(ns.date, "--date")
    state = load_state()
    session = {"date": when, "level": level, "concepts": concepts, "missed": missed, "placed": False}
    state["sessions"].append(session)
    path = save_state(state)
    return {"added": session, "learner_path": str(path), "count": len(state["sessions"])}


def _place(ns: argparse.Namespace) -> dict:
    level = ns.level.strip().lower()
    if not level:
        raise InvalidInput("--level is required")
    state = load_state()
    matches = [s for s in state["sessions"] if s.get("level") == level]
    if not matches:
        raise InvalidInput(f"no session recorded at level {level!r}; run progress.py add --level {level} --concept ...")
    matches[-1]["placed"] = True
    path = save_state(state)
    return {"placed": matches[-1], "learner_path": str(path)}


def _list(ns: argparse.Namespace) -> dict:
    state = load_state()
    sessions = sorted(enumerate(state["sessions"]), key=lambda p: (p[1]["date"], p[0]))
    sessions = [s for _, s in sessions]
    concepts_covered = sorted({c for s in sessions for c in s.get("concepts") or []})
    missed_counts: dict[str, int] = {}
    for s in sessions:
        for quiz_id in s.get("missed") or []:
            missed_counts[quiz_id] = missed_counts.get(quiz_id, 0) + 1
    missed_history = [
        {"quiz_id": quiz_id, "count": count}
        for quiz_id, count in sorted(missed_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    placed = [s for s in sessions if s.get("placed")]
    if placed:
        level = placed[-1]["level"]
    elif sessions:
        level = sessions[-1]["level"]
    else:
        level = None
    return {
        "learner_path": str(learner_path()),
        "sessions": sessions,
        "concepts_covered": concepts_covered,
        "missed_history": missed_history,
        "level": level,
    }


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="progress.py", add_help=False)
        sub = p.add_subparsers(dest="command")
        a = sub.add_parser("add", add_help=False)
        a.add_argument("--level", required=True)
        a.add_argument("--concept", action="append", default=[])
        a.add_argument("--missed", action="append", default=[])
        a.add_argument("--date", default=None)
        pl = sub.add_parser("place", add_help=False)
        pl.add_argument("--level", required=True)
        sub.add_parser("list", add_help=False)
        ns = p.parse_args(args)
        if ns.command == "add":
            return _add(ns)
        if ns.command == "place":
            return _place(ns)
        if ns.command == "list":
            return _list(ns)
        raise InvalidInput("command must be add, place, or list")

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
