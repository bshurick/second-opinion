#!/usr/bin/env python3
"""Usage: review_store.py save --in page.json [--source URL] | check --book snapshot.json [--as-of YYYY-MM-DD] | list

Keeps portfolio deep reviews in the plugin data directory, one file per review date, under
portfolio-reviews/, and re-measures the latest one against the holdings at a later date. It reads no
broker and no web: the book comes from a saved snapshot.py result.

save takes the page input of render_review.py and prints {"saved", "as_of", "bets"}. --source is the
https link of the published page.

check runs exposure.py on the saved bets and the given book, with no new research. It prints
{"as_of", "review_as_of", "review_age_days", "review_source", "headline", "bets": [{"id", "name",
"belief", "verdict", "then", "now", "moved", "gone"}], "watch_due", "new_uncovered", "rerun_due",
"rerun_reasons"}. then and now carry exposed_value, exposed_pct, loss_if_wrong, income_at_risk and
at_stake. moved is the change in exposed_value, null when the bet had none. A holding no longer held
is listed in gone and counts as zero. watch_due lists the watch items whose check_by has arrived.
new_uncovered lists holdings bought since the review that no bet covers. Shares, shocks and the
verdict are the review's own, so a later check says how much rests on each bet now, not whether the
bet still holds.

A review is due again when a bet's exposure moved by a quarter, after 180 days, or when new uncovered
holdings reach 10% of the portfolio.

list prints {"reviews": [{"as_of", "headline", "source", "bets"}]}, newest first.

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

import exposure  # noqa: E402
from second_opinion import config, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

REVIEW_DIR = "portfolio-reviews"
RERUN_DAYS = 180
RERUN_MOVE = 0.25
RERUN_UNCOVERED = 0.10
FIGURES = ("exposed_value", "exposed_pct", "loss_if_wrong", "income_at_risk", "at_stake")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"review_store.py: {message}")


def review_dir() -> Path:
    return config.data_dir() / REVIEW_DIR


def _read_json(path: str, what: str) -> dict:
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
    review = _read_json(ns.inp, "review page input")
    bets = (review.get("exposure") or {}).get("bets") if isinstance(review.get("exposure"), dict) else None
    if not isinstance(bets, list) or not bets:
        raise InvalidInput("exposure (an exposure.py result with bets) is required")
    as_of = _day(review.get("as_of"), "as_of")
    if ns.source and not ns.source.lower().startswith("https://"):
        raise InvalidInput("--source must be an https:// link")
    path = review_dir() / f"{as_of}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**review, "source": ns.source or review.get("source")}, indent=2), encoding="utf-8")
    tmp.replace(path)
    return {"saved": str(path), "as_of": str(as_of), "bets": len(bets)}


def _figures(bet: dict) -> dict:
    return {k: bet[k] for k in FIGURES}


def _check(ns: argparse.Namespace) -> dict:
    reviews = _saved()
    if not reviews:
        raise InvalidInput("no saved review; run a portfolio deep review first")
    review = reviews[0]
    saved = review["exposure"]
    today = _day(ns.as_of, "--as-of") if ns.as_of else date.today()
    base = _day(review["as_of"], "the review's as_of")
    if today < base:
        raise InvalidInput(f"--as-of {today} is before the review of {base}")
    try:
        now = exposure.run_exposure({"as_of": str(today), "book": _read_json(ns.book, "snapshot"), "bets": saved["bets"],
                                     "income": saved.get("income"), "allow_missing": True})
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InvalidInput(str(exc)) from exc

    then = {b["id"]: b for b in saved["bets"]}
    bets, reasons = [], []
    for bet in now["bets"]:
        old = then[bet["id"]]
        moved = round(bet["exposed_value"] / old["exposed_value"] - 1, 4) if old["exposed_value"] else None
        bets.append({"id": bet["id"], "name": bet["name"], "belief": bet["belief"], "verdict": bet["verdict"],
                     "then": _figures(old), "now": _figures(bet), "moved": moved, "gone": bet["gone"]})
        if moved is not None and abs(moved) >= RERUN_MOVE:
            reasons.append(f"exposure of {bet['name']} moved {abs(moved) * 100:.1f}%")
    age = (today - base).days
    if age >= RERUN_DAYS:
        reasons.append(f"the review is {age} days old, past {RERUN_DAYS} days")
    known = set(saved.get("held") or [])
    new = [u for u in now["unmapped"] if u["symbol"] not in known]
    share = sum(u["weight"] for u in new)
    if new and share >= RERUN_UNCOVERED:
        reasons.append(f"holdings added since the review and covered by no bet reach {share * 100:.1f}% of the portfolio: {', '.join(u['symbol'] for u in new)}")
    due = sorted(({"bet": b["id"], "name": b["name"], **{k: w[k] for k in ("what", "breaks_if", "check_by")}}
                  for b in now["bets"] for w in b["watch"] if _day(w["check_by"], "check_by") <= today), key=lambda w: w["check_by"])
    return {"as_of": str(today), "review_as_of": str(base), "review_age_days": age, "review_source": review.get("source"),
            "headline": review.get("headline"), "bets": bets, "watch_due": due, "new_uncovered": new,
            "rerun_due": bool(reasons), "rerun_reasons": reasons}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="review_store.py", add_help=False)
        sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
        sv = sub.add_parser("save", add_help=False)
        sv.add_argument("--in", dest="inp", required=True)
        sv.add_argument("--source")
        ck = sub.add_parser("check", add_help=False)
        ck.add_argument("--book", required=True)
        ck.add_argument("--as-of")
        sub.add_parser("list", add_help=False)
        ns = p.parse_args(args)
        if ns.cmd == "save":
            return _save(ns)
        if ns.cmd == "check":
            return _check(ns)
        return {"reviews": [{"as_of": r["as_of"], "headline": r.get("headline"), "source": r.get("source"), "bets": len(r["exposure"]["bets"])} for r in _saved()]}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
