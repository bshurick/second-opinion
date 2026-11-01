#!/usr/bin/env python3
"""Usage: decision_store.py save --in page.json [--source URL] | check --review review.json [--as-of YYYY-MM-DD] | list

Keeps trade-review deep reviews in the plugin data directory, one file per review date, under
decision-reviews/, and re-measures the latest one against a newer run-review.py result. It reads no
web and no ledger.

save takes the page input of render_decisions.py and prints {"saved", "as_of", "decisions"}.

check keeps every grade as saved and recomputes each decision's result, so a result that matures or
turns over can test the grade without moving it. It prints {"as_of", "review_as_of",
"review_age_days", "review_source", "headline", "decisions": [{"id", "symbol", "action", "date",
"quality", "then", "now", "then_cell", "now_cell"}], "changed", "cells", "new_large_decisions",
"rerun_due", "rerun_reasons"}. A decision the newer result no longer holds shows as unavailable, and
keeps its saved result in then.

A review is due again after 180 days, or when a decision not in it is as large as the smallest one
it holds.

list prints {"reviews": [{"as_of", "headline", "source", "decisions"}]}, newest first.

Exit 2 with {"error"} on invalid input or when no review has been saved.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import decisions as scorer  # noqa: E402
from second_opinion import config, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

REVIEW_DIR = "decision-reviews"
RERUN_DAYS = 180


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"decision_store.py: {message}")


def review_dir() -> Path:
    return config.data_dir() / REVIEW_DIR


def _read(path: str, what: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"could not read the {what}: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidInput(f"the {what} must be a JSON object")
    return data


def _day(value: object, what: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise InvalidInput(f"{what} must be YYYY-MM-DD") from exc


def _saved() -> list[dict]:
    if not review_dir().is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(review_dir().glob("*.json"), reverse=True)]


def _save(ns: argparse.Namespace) -> dict:
    page = _read(ns.inp, "review page input")
    rows = (page.get("review") or {}).get("decisions") if isinstance(page.get("review"), dict) else None
    if not isinstance(rows, list) or not rows:
        raise InvalidInput("review (a decisions.py result) is required")
    as_of = _day(page.get("as_of"), "as_of")
    if ns.source and not ns.source.lower().startswith("https://"):
        raise InvalidInput("--source must be an https:// link")
    path = review_dir() / f"{as_of}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**page, "source": ns.source or page.get("source")}, indent=1), encoding="utf-8")
    tmp.replace(path)
    return {"saved": str(path), "as_of": str(as_of), "decisions": len(rows)}


def _check(ns: argparse.Namespace) -> dict:
    reviews = _saved()
    if not reviews:
        raise InvalidInput("no saved review; run a deep trade review first")
    page = reviews[0]
    newer = _read(ns.review, "run-review.py result")
    if "round_trips" not in newer:
        raise InvalidInput("--review must be a run-review.py result")
    today = _day(ns.as_of, "--as-of") if ns.as_of else date.today()
    base = _day(page["as_of"], "the review's as_of")
    if today < base:
        raise InvalidInput(f"--as-of {today} is before the review of {base}")
    rows, changed = [], []
    for d in page["review"]["decisions"]:
        key = f"{d['action']}-{str(d['symbol']).upper()}-{d['date'][:10]}"
        now = scorer.outcome_for(key, newer) or {"verdict": "unavailable", "score": None, "measure": None}
        cell = scorer.cell_for(d["quality"], now["verdict"])
        rows.append({"id": d["id"], "symbol": d["symbol"], "action": d["action"], "date": d["date"], "quality": d["quality"], "then": d["outcome"], "now": now, "then_cell": d["cell"], "now_cell": cell})
        if now["verdict"] != d["outcome"]["verdict"]:
            changed.append(d["id"])
    held = {d["id"] for d in page["review"]["decisions"]}
    floor = min(float(d["outcome"].get("amount") or 0) for d in page["review"]["decisions"])
    picks = scorer.pick_decisions(newer, 10_000)["decisions"]
    new = [p for p in picks if p["id"] not in held and p["amount"] >= floor and p["date"] > page["as_of"][:10]]
    age = (today - base).days
    reasons = []
    if age >= RERUN_DAYS:
        reasons.append(f"the review is {age} days old, past {RERUN_DAYS} days")
    if new:
        reasons.append(f"new decisions as large as those reviewed: {', '.join(p['id'] for p in new)}")
    cells = {name: sum(1 for r in rows if r["now_cell"] == name) for name in scorer.CELL_NAMES}
    return {"as_of": str(today), "review_as_of": str(base), "review_age_days": age, "review_source": page.get("source"), "headline": page.get("headline"),
            "decisions": rows, "changed": changed, "cells": cells, "new_large_decisions": new, "rerun_due": bool(reasons), "rerun_reasons": reasons}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="decision_store.py", add_help=False)
        sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
        sv = sub.add_parser("save", add_help=False)
        sv.add_argument("--in", dest="inp", required=True)
        sv.add_argument("--source")
        ck = sub.add_parser("check", add_help=False)
        ck.add_argument("--review", required=True)
        ck.add_argument("--as-of")
        sub.add_parser("list", add_help=False)
        ns = p.parse_args(args)
        if ns.cmd == "save":
            return _save(ns)
        if ns.cmd == "check":
            return _check(ns)
        return {"reviews": [{"as_of": r["as_of"], "headline": r.get("headline"), "source": r.get("source"), "decisions": len(r["review"]["decisions"])} for r in _saved()]}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
