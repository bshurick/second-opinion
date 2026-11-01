#!/usr/bin/env python3
"""Usage: plan_store.py save --in page.json [--source URL] | check --report tax-report.json [--as-of YYYY-MM-DD] | list

Keeps tax plan comparisons in the plugin data directory, one file per review date, under
tax-plans/, and reruns the latest one on a newer tax-report.py result. It reads no web and no ledger.

save takes the page input of render_plans.py and prints {"saved", "as_of", "plans"}.

check reruns tax_plans.py on the saved inputs with the newer lots. It prints {"as_of", "review_as_of",
"review_age_days", "review_source", "headline", "plans": [{"name", "then", "now", "short"}],
"leading_then", "leading_now", "actions_due", "rerun_due", "rerun_reasons"}. then and now carry
after_tax_wealth and total_tax. short lists symbols a plan would sell that are no longer fully held.
actions_due lists this calendar year's actions, with units_sold_so_far from the report's realized
sales and days_left to year end. The rules stay as checked at the review, and no new research runs.

A comparison is due again when the calendar year has changed, after 180 days, or when a plan has
actions due within 60 days of year end.

list prints {"reviews": [{"as_of", "headline", "source", "plans"}]}, newest first.

Exit 2 with {"error"} on invalid input or when nothing has been saved.
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

import tax_plans  # noqa: E402
from second_opinion import config, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

PLAN_DIR = "tax-plans"
RERUN_DAYS = 180
YEAR_END_DAYS = 60


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"plan_store.py: {message}")


def plan_dir() -> Path:
    return config.data_dir() / PLAN_DIR


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
    if not plan_dir().is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(plan_dir().glob("*.json"), reverse=True)]


def _save(ns: argparse.Namespace) -> dict:
    page = _read(ns.inp, "plan page input")
    rows = (page.get("plans") or {}).get("plans") if isinstance(page.get("plans"), dict) else None
    if not isinstance(rows, list) or not rows or "inputs" not in page["plans"]:
        raise InvalidInput("plans (a tax_plans.py result) is required")
    as_of = _day(page.get("as_of"), "as_of")
    if ns.source and not ns.source.lower().startswith("https://"):
        raise InvalidInput("--source must be an https:// link")
    path = plan_dir() / f"{as_of}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**page, "source": ns.source or page.get("source")}, indent=1), encoding="utf-8")
    tmp.replace(path)
    return {"saved": str(path), "as_of": str(as_of), "plans": len(rows)}


def _figures(plan: dict) -> dict:
    return {"after_tax_wealth": plan["end"]["after_tax_wealth"], "total_tax": plan["total_tax"]}


def _check(ns: argparse.Namespace) -> dict:
    pages = _saved()
    if not pages:
        raise InvalidInput("no saved comparison; run a deep tax review first")
    page = pages[0]
    report = _read(ns.report, "tax-report.py result")
    if "open_lots" not in report:
        raise InvalidInput("--report must be a tax-report.py result")
    saved = page["plans"]
    today = _day(ns.as_of, "--as-of") if ns.as_of else date.today()
    base = _day(page["as_of"], "the review's as_of")
    if today < base:
        raise InvalidInput(f"--as-of {today} is before the review of {base}")
    try:
        now = tax_plans.run_plans({**saved["inputs"], "as_of": str(today), "book": report, "allow_short": True, "tests": []})
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        raise InvalidInput(str(exc)) from exc
    then = {p["name"]: p for p in saved["plans"]}
    rows = [{"name": p["name"], "then": _figures(then[p["name"]]), "now": _figures(p), "short": p["short"]} for p in now["plans"]]
    sold: dict[str, float] = {}
    for r in report.get("realized") or []:
        if str(r.get("sell_date"))[:4] == str(today.year):
            sold[str(r.get("symbol")).upper()] = sold.get(str(r.get("symbol")).upper(), 0.0) + float(r.get("units") or 0)
    days_left = (date(today.year, 12, 31) - today).days
    due = []
    for p in saved["inputs"]["plans"]:
        for a in p["actions"]:
            if a["year"] == today.year:
                row = {"plan": p["name"], "type": a["type"], "year": a["year"], "days_left": days_left}
                if a["type"] == "sell":
                    row.update(symbol=a["symbol"], units=a["units"], units_sold_so_far=sold.get(str(a["symbol"]).upper(), 0.0))
                else:
                    row["amount"] = a["amount"]
                due.append(row)
    reasons = []
    age = (today - base).days
    if today.year != base.year:
        reasons.append(f"the calendar year has changed since the review of {base}, so rules and income need another look")
    if age >= RERUN_DAYS:
        reasons.append(f"the review is {age} days old, past {RERUN_DAYS} days")
    if due and days_left <= YEAR_END_DAYS:
        reasons.append(f"{len(due)} planned {'action falls' if len(due) == 1 else 'actions fall'} in this tax year, {days_left} days from year end")
    return {"as_of": str(today), "review_as_of": str(base), "review_age_days": age, "review_source": page.get("source"), "headline": page.get("headline"), "plans": rows,
            "leading_then": saved["leading"], "leading_now": now["leading"], "actions_due": due, "rerun_due": bool(reasons), "rerun_reasons": reasons}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="plan_store.py", add_help=False)
        sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
        sv = sub.add_parser("save", add_help=False)
        sv.add_argument("--in", dest="inp", required=True)
        sv.add_argument("--source")
        ck = sub.add_parser("check", add_help=False)
        ck.add_argument("--report", required=True)
        ck.add_argument("--as-of")
        sub.add_parser("list", add_help=False)
        ns = p.parse_args(args)
        if ns.cmd == "save":
            return _save(ns)
        if ns.cmd == "check":
            return _check(ns)
        return {"reviews": [{"as_of": r["as_of"], "headline": r.get("headline"), "source": r.get("source"), "plans": len(r["plans"]["plans"])} for r in _saved()]}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
