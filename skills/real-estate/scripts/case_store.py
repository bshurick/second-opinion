#!/usr/bin/env python3
"""Usage: case_store.py save --in page.json [--source URL] | check SLUG [--set FIELD=VALUE ...] [--as-of YYYY-MM-DD] | list

Keeps real-estate deep reviews in the plugin data directory, one file per property or market, under
property-reviews/, and reruns a saved case with updated inputs. It reads no web.

save takes the page input of render_case.py and prints {"saved", "slug", "as_of", "scenarios"}. Saving
the same name again replaces the earlier case. --source is the https link of the published page.

check reruns property_case.py on the saved inputs with each --set replacing that base input, as stated
by the person. A scenario that changes the same field keeps its own value. It prints {"slug", "name",
"as_of", "review_as_of", "review_age_days", "review_source", "headline", "result_label", "updated",
"scenarios": [{"name", "then", "now", "moved"}], "even_price", "watch_due", "open_questions",
"rerun_due", "rerun_reasons"}. No new research runs, so the evidence stays the review's own.

A case is due again after 90 days, when a watch item's check_by has arrived, or when an update flips
the sign of the central result.

list prints {"cases": [{"slug", "name", "use", "as_of", "headline", "source"}]}, newest first.

Exit 2 with {"error"} on invalid input or when no case has that slug.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import property_case  # noqa: E402
from second_opinion import config, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

CASE_DIR = "property-reviews"
RERUN_DAYS = 90
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"case_store.py: {message}")


def case_dir() -> Path:
    return config.data_dir() / CASE_DIR


def _day(value: object, what: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise InvalidInput(f"{what} must be YYYY-MM-DD") from exc


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise InvalidInput("the subject's name has no letters or digits to file it under")
    return slug


def _save(ns: argparse.Namespace) -> dict:
    try:
        page = json.loads(Path(ns.inp).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"could not read the case page input: {exc}") from exc
    case = page.get("case") if isinstance(page, dict) else None
    if not isinstance(case, dict) or not case.get("scenarios") or not (case.get("subject") or {}).get("name"):
        raise InvalidInput("case (a property_case.py result) is required")
    as_of = _day(page.get("as_of"), "as_of")
    if ns.source and not ns.source.lower().startswith("https://"):
        raise InvalidInput("--source must be an https:// link")
    slug = _slug(case["subject"]["name"])
    path = case_dir() / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**page, "source": ns.source or page.get("source")}, indent=1), encoding="utf-8")
    tmp.replace(path)
    return {"saved": str(path), "slug": slug, "as_of": str(as_of), "scenarios": len(case["scenarios"])}


def _updates(items: list[str], today: date) -> dict:
    out = {}
    for item in items:
        field, sep, raw = item.partition("=")
        try:
            value = float(raw)
        except ValueError as exc:
            raise InvalidInput(f"--set expects FIELD=VALUE with a number, got {item!r}") from exc
        if not sep or not field.strip():
            raise InvalidInput(f"--set expects FIELD=VALUE with a number, got {item!r}")
        out[field.strip()] = {"value": value, "basis": "stated", "source": "Stated by the person at this check", "date": str(today)}
    return out


def _check(ns: argparse.Namespace) -> dict:
    path = case_dir() / f"{ns.slug}.json"
    if not _SLUG.match(ns.slug) or not path.is_file():
        raise InvalidInput(f"no saved case named {ns.slug}; case_store.py list shows them")
    page = json.loads(path.read_text(encoding="utf-8"))
    saved = page["case"]
    today = _day(ns.as_of, "--as-of") if ns.as_of else date.today()
    base = _day(page["as_of"], "the review's as_of")
    if today < base:
        raise InvalidInput(f"--as-of {today} is before the review of {base}")
    updates = _updates(ns.set or [], today)
    try:
        now = property_case.run_case({"as_of": str(today), "subject": saved["subject"], "inputs": {**saved["inputs"], **updates},
                                      "scenarios": saved["scenarios"], "costs": saved["costs"]})
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        raise InvalidInput(str(exc)) from exc
    then_rows = {s["name"]: s["result"] for s in saved["scenarios"]}
    rows = [{"name": s["name"], "then": then_rows[s["name"]], "now": s["result"], "moved": round(s["result"] - then_rows[s["name"]], 2)} for s in now["scenarios"]]
    due = sorted((w for w in saved.get("watch") or [] if _day(w["check_by"], "check_by") <= today), key=lambda w: w["check_by"])
    age = (today - base).days
    reasons = []
    if age >= RERUN_DAYS:
        reasons.append(f"the review is {age} days old, past {RERUN_DAYS} days")
    if due:
        reasons.append(f"{len(due)} watch {'item has' if len(due) == 1 else 'items have'} come due")
    if rows[0]["then"] * rows[0]["now"] < 0:
        reasons.append("the central result changed sign")
    return {"slug": ns.slug, "name": saved["subject"]["name"], "as_of": str(today), "review_as_of": str(base), "review_age_days": age,
            "review_source": page.get("source"), "headline": page.get("headline"), "result_label": saved["result_label"],
            "updated": {k: {"then": (saved["inputs"].get(k) or {}).get("value"), "now": v["value"]} for k, v in updates.items()},
            "scenarios": rows, "even_price": now["even_price"], "watch_due": due, "open_questions": saved.get("open_questions") or [],
            "rerun_due": bool(reasons), "rerun_reasons": reasons}


def _list_cases() -> dict:
    rows = []
    if case_dir().is_dir():
        for p in case_dir().glob("*.json"):
            page = json.loads(p.read_text(encoding="utf-8"))
            subject = page["case"]["subject"]
            rows.append({"slug": p.stem, "name": subject["name"], "use": subject["use"], "as_of": page["as_of"], "headline": page.get("headline"), "source": page.get("source")})
    return {"cases": sorted(rows, key=lambda r: r["as_of"], reverse=True)}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="case_store.py", add_help=False)
        sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
        sv = sub.add_parser("save", add_help=False)
        sv.add_argument("--in", dest="inp", required=True)
        sv.add_argument("--source")
        ck = sub.add_parser("check", add_help=False)
        ck.add_argument("slug")
        ck.add_argument("--set", action="append", default=[])
        ck.add_argument("--as-of")
        sub.add_parser("list", add_help=False)
        ns = p.parse_args(args)
        if ns.cmd == "save":
            return _save(ns)
        if ns.cmd == "check":
            return _check(ns)
        return _list_cases()

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
