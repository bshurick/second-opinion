#!/usr/bin/env python3
"""Usage: rules.py add category --match REGEX --category NAME [--detail PATH] [--note TEXT]
       rules.py add merchant --match REGEX --merchant NAME
       rules.py add transfer --match REGEX
       rules.py add ignore --match REGEX
       rules.py list
       rules.py remove KIND INDEX
       rules.py apply [--dry-run]

Category, merchant-alias, transfer and ignore rules kept in ``spending-rules.json`` under the
plugin data dir. ``match`` is a case-insensitive regex tested against the raw description and
the normalized merchant; first matching rule wins. ``add`` validates the regex and the
category (a spend taxonomy name; Transfer, Income and Uncategorized are rejected -- use
``add transfer`` or ``add ignore`` instead), appends, then re-applies every rule to the stored rows and
reports how many changed; ``--detail PATH`` on a category rule tags matching rows with a slash-separated
detail path such as Fuel/Shell; a row's own transcribed detail is never overwritten.
``remove`` deletes one rule by kind and 0-based index and re-applies;
``apply`` re-normalizes and re-categorizes every stored row (``--dry-run`` lists the rows that
would change, with from/to values, and writes nothing). Cross-account transfer pairs are kept.
Rules never touch amount, date or description. stdin is unused. Exit codes: 0, 2, 4
(CONFIG_MISSING: apply with nothing imported), 5 (SPENDING_CORRUPT, RULES_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import spendnormalize  # noqa: E402
from second_opinion import output, spending  # noqa: E402
from second_opinion.errors import ConfigError, InvalidInput  # noqa: E402

_KIND_TO_KEY = {"category": "categories", "merchant": "merchants", "transfer": "transfers", "ignore": "ignore"}
_FIELDS = ("merchant", "category", "category_source", "type", "transfer", "detail")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"rules.py: {message}")


def _apply(book: dict, rules: dict, *, write: bool) -> dict:
    before = {t["id"]: t for t in book["transactions"]}
    result = spendnormalize.apply_rules([dict(t) for t in book["transactions"]], rules, book["accounts"])
    changes = []
    for t in result["transactions"]:
        old = before.get(t["id"])
        if old is None:
            continue
        diff = {k: {"from": old.get(k), "to": t[k]} for k in _FIELDS if old.get(k) != t[k]}
        if diff:
            changes.append({"id": t["id"], "date": t["date"], "merchant": t["merchant"], "amount": t["amount"], **diff})
    if write:
        book["transactions"] = result["transactions"]
        spendnormalize.match_transfers(book["transactions"], book["accounts"])
        spending.save(book)
    return {"changed": result["changed"], "removed_rows": result["removed"], "by_category": result["by_category"], "changes": changes[:50]}


def _load_book(*, required: bool) -> dict:
    path = spending.spending_path()
    if not path.is_file():
        if required:
            raise ConfigError("nothing imported yet", hint="run import-spending.py <file> --account ID first", path=str(path))
        return spending.empty()
    return spending.load(path)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="rules.py", add_help=False)
        sub = p.add_subparsers(dest="command", required=True)
        add = sub.add_parser("add", add_help=False)
        add.add_argument("kind", choices=list(_KIND_TO_KEY))
        add.add_argument("--match", required=True)
        add.add_argument("--category", default=None)
        add.add_argument("--merchant", default=None)
        add.add_argument("--detail", default=None)
        add.add_argument("--note", default=None)
        sub.add_parser("list", add_help=False)
        rm = sub.add_parser("remove", add_help=False)
        rm.add_argument("kind", choices=list(_KIND_TO_KEY))
        rm.add_argument("index", type=int)
        ap = sub.add_parser("apply", add_help=False)
        ap.add_argument("--dry-run", action="store_true")
        ns = p.parse_args(args)
        rules = spending.load_rules()
        if ns.command == "list":
            return {**rules, "rules_path": str(spending.rules_path())}
        if ns.command == "apply":
            book = _load_book(required=True)
            result = _apply(book, rules, write=not ns.dry_run)
            return {"dry_run": True, **result} if ns.dry_run else {**result, "spending_path": str(spending.spending_path())}
        if ns.command == "add":
            try:
                re.compile(ns.match)
            except re.error as exc:
                raise InvalidInput(f"--match is not a valid regex: {exc}") from exc
            rule: dict = {"match": ns.match}
            if ns.kind == "category":
                if ns.category not in spendnormalize.TAXONOMY:
                    raise InvalidInput(f"--category must be one of the taxonomy names: {', '.join(spendnormalize.TAXONOMY)}")
                if ns.category in ("Transfer", "Income", "Uncategorized"):
                    raise InvalidInput(
                        f"--category cannot be {ns.category}: a category rule only assigns spend categories; "
                        "use `rules.py add transfer` to mark rows as transfers or `rules.py add ignore` to drop them"
                    )
                rule["category"] = ns.category
                if ns.detail is not None:
                    try:
                        detail = spendnormalize.validate_detail(ns.detail)
                    except ValueError as exc:
                        raise InvalidInput(str(exc)) from exc
                    if detail:
                        rule["detail"] = detail
                if ns.note:
                    rule["note"] = ns.note
            elif ns.kind == "merchant":
                if ns.detail is not None:
                    raise InvalidInput("--detail applies to category rules only")
                if not ns.merchant:
                    raise InvalidInput("--merchant is required for a merchant rule")
                rule["merchant"] = ns.merchant
            else:
                if ns.detail is not None:
                    raise InvalidInput("--detail applies to category rules only")
            rules[_KIND_TO_KEY[ns.kind]].append(rule)
            spending.save_rules(rules)
            book = _load_book(required=False)
            result = _apply(book, rules, write=bool(book["transactions"]))
            return {"added": rule, "kind": ns.kind, "index": len(rules[_KIND_TO_KEY[ns.kind]]) - 1, **result, "rules_path": str(spending.rules_path())}
        key = _KIND_TO_KEY[ns.kind]
        if not 0 <= ns.index < len(rules[key]):
            raise InvalidInput(f"no {ns.kind} rule at index {ns.index}; run `rules.py list`")
        removed = rules[key].pop(ns.index)
        spending.save_rules(rules)
        book = _load_book(required=False)
        result = _apply(book, rules, write=bool(book["transactions"]))
        return {"removed": removed, "kind": ns.kind, **result, "rules_path": str(spending.rules_path())}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
