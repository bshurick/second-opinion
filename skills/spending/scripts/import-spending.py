#!/usr/bin/env python3
"""Usage: import-spending.py <file.csv|.ofx|.qfx|.xlsx> --account ID [--name TEXT]
                         [--kind card|checking|savings] [--preset NAME | --mapping JSON]
                         [--sheet NAME] [--dry-run]
       import-spending.py --rows FILE.json|- --account ID --source KIND
                         [--kind card|checking|savings] [--name TEXT] [--dry-run]
       import-spending.py presets

Import one card or bank export into ``spending.json`` under the plugin data dir. CSV files
(any preamble lines; the header row is found by preset fingerprint or by the --mapping columns)
are parsed with a preset: amex, chase-card, chase-checking, citi, capital-one, discover,
bofa-card, apple-card, or an ad-hoc --mapping ('{"date": ..., "description": ..., "amount": ...
| "debit"/"credit": ..., "category": ..., "type": ..., "sign": "charges_negative" |
"charges_positive"}'). An .xlsx file is read with the standard library (first sheet, or
--sheet) and then handled like a CSV. OFX/QFX files are parsed directly (FITID drives dedupe). Every stored
amount is account-view signed: spend negative. Rows are normalized (merchant, category,
transfer) with the rules in ``spending-rules.json``, deduplicated against the store, and
after the merge card payments are matched against checking debits across accounts
(``transfer_pairs``). First use of an account needs --account; --name defaults to the
debt-tracker register's name for that id, else the id; --kind defaults to the preset's (or
the OFX file's); --rows and --mapping have no kind of their own, so without --kind they take
the stored kind of an existing account, else card. A kind that conflicts with rows already
on file fails (checking and savings may mix).
``presets`` lists the presets. stdin is unused unless --rows is ``-``.

``--rows`` takes a JSON list of canonical rows (or ``{"rows": [...]}``), each with ``date``,
``description``, ``amount`` and optional ``merchant``, ``category``, ``detail``, ``post_date``,
``items``; the model transcribes any source (pasted lists, receipts, statement tables) into
this shape and labels it with --source (receipt, amazon-chat, statement-pdf, ...). Every
stored row carries ``source``.
Output: {file, preset, account_id, header_line, imported, duplicates, skipped (first 10),
skipped_count, transfers_marked, transfer_pairs, date_range, categories, uncategorized,
spending_path, source}; --dry-run adds dry_run: true and sample (first 5 rows) and writes
nothing.
Exit codes: 0, 2 (INVALID_INPUT, NO_HEADER, UNKNOWN_PRESET, INVALID_ACCOUNT), 5
(SPENDING_CORRUPT, RULES_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import spendnormalize  # noqa: E402
from second_opinion import output, spending, xlsx  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"import-spending.py: {message}")


def _header_matches(fields: list[str], preset: str | None, mapping: dict | None) -> str | None:
    if mapping:
        wanted = {spendnormalize.norm_header(v) for k, v in mapping.items() if k != "sign" and isinstance(v, str) and v}
        have = {spendnormalize.norm_header(f) for f in fields}
        return "mapping" if wanted and wanted <= have else None
    if preset:
        # A forced --preset must never be stricter than auto-detection: it matches when
        # either its detection fingerprint or the columns it actually reads are present.
        # The fingerprint covers exports missing an optional read column (e.g. Amex's
        # "Category"); the columns set covers exports missing a fingerprint-only column
        # that isn't actually read (e.g. Capital One's "Card No.").
        have = {spendnormalize.norm_header(f) for f in fields}
        info = spendnormalize.PRESETS[preset]
        fp = set(info["fingerprint"])
        cols = set(info["columns"].values())
        return preset if fp <= have or cols <= have else None
    return spendnormalize.detect_preset(fields)


def read_csv(text: str, preset: str | None, mapping: dict | None) -> tuple[int, str, list[dict]]:
    """(1-based header line, preset name, data rows) from a CSV export with preamble or trailer lines."""
    lines = text.lstrip("﻿").splitlines()
    for i, line in enumerate(lines):
        try:
            fields = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            continue
        name = _header_matches(fields, preset, mapping) if fields else None
        if name:
            reader = csv.DictReader(io.StringIO("\n".join(lines[i:])))
            rows = [{k: (v or "") for k, v in r.items() if k is not None} for r in reader]
            return i + 1, name, rows
    if preset:
        expected = ", ".join(sorted(spendnormalize.PRESETS[preset]["fingerprint"]))
        raise InvalidInput(f"no header row matches preset {preset!r}; expected columns: {expected}", code="NO_HEADER")
    raise InvalidInput("no header row matches a preset; pass --preset or --mapping", code="NO_HEADER")


def _presets() -> dict:
    return {"presets": [{"name": n, "kind": p["kind"], "sign": p["sign"], "columns": p["columns"]} for n, p in spendnormalize.PRESETS.items()]}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        if args[:1] == ["presets"]:
            return _presets()
        p = _Parser(prog="import-spending.py", add_help=False)
        p.add_argument("file", nargs="?", default=None)
        p.add_argument("--account", required=True)
        p.add_argument("--name", default=None)
        p.add_argument("--kind", default=None, choices=list(spending.KINDS))
        p.add_argument("--preset", default=None)
        p.add_argument("--mapping", default=None)
        p.add_argument("--sheet", default=None)
        p.add_argument("--rows", default=None)
        p.add_argument("--source", default=None)
        p.add_argument("--dry-run", action="store_true")
        ns = p.parse_args(args)
        if bool(ns.file) == bool(ns.rows):
            raise InvalidInput("pass exactly one of a file or --rows")
        if ns.rows and not ns.source:
            raise InvalidInput("--source KIND is required with --rows (for example receipt or amazon-chat)")
        if ns.rows and (ns.preset or ns.mapping):
            raise InvalidInput("--preset and --mapping do not apply to --rows")
        if not _SLUG.match(ns.account):
            raise InvalidInput(f"account id must be a kebab-case slug, got {ns.account!r}", code="INVALID_ACCOUNT")
        if ns.preset and ns.preset not in spendnormalize.PRESETS:
            raise InvalidInput(f"unknown preset {ns.preset!r}; run `import-spending.py presets`", code="UNKNOWN_PRESET")
        mapping = None
        if ns.mapping:
            try:
                mapping = json.loads(ns.mapping)
            except ValueError as exc:
                raise InvalidInput(f"--mapping must be JSON: {exc}") from exc
        book = spending.load()
        rules = spending.load_rules()
        existing = book["accounts"].get(ns.account)
        if ns.rows:
            if ns.rows == "-":
                raw = sys.stdin.read()
            else:
                rows_path = Path(ns.rows).expanduser()
                if not rows_path.is_file():
                    raise InvalidInput(f"rows file not found: {rows_path}")
                try:
                    raw = rows_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    raise InvalidInput(f"could not read rows file: {exc}") from exc
            try:
                payload = json.loads(raw)
            except ValueError as exc:
                raise InvalidInput(f"--rows must be JSON: {exc}") from exc
            rows_in = payload.get("rows") if isinstance(payload, dict) else payload
            if not isinstance(rows_in, list) or not rows_in:
                raise InvalidInput("rows must be a non-empty JSON list of {date, description, amount, ...} objects")
            file_name = "stdin" if ns.rows == "-" else Path(ns.rows).name
            header_line = None
            params: dict = {
                "source": "rows", "rows": rows_in, "account_id": ns.account, "rules": rules,
                "source_name": file_name, "source_kind": ns.source,
            }
        else:
            path = Path(ns.file).expanduser()
            if not path.is_file():
                raise InvalidInput(f"file not found: {path}")
            file_name = path.name
            suffix = path.suffix.lower()
            params = {"account_id": ns.account, "rules": rules, "source_name": file_name}
            if suffix in (".ofx", ".qfx"):
                if ns.sheet:
                    raise InvalidInput("--sheet applies to .xlsx files only")
                if mapping:
                    raise InvalidInput("--mapping applies to csv and xlsx files only")
                header_line = None
                params.update({"source": "ofx", "ofx_text": path.read_text(encoding="utf-8-sig", errors="replace")})
            else:
                if suffix == ".xlsx":
                    try:
                        text = xlsx.to_csv_text(path, ns.sheet)
                    except ValueError as exc:
                        raise InvalidInput(str(exc)) from exc
                elif ns.sheet:
                    raise InvalidInput("--sheet applies to .xlsx files only")
                else:
                    text = path.read_text(encoding="utf-8-sig", errors="replace")
                header_line, _name, rows = read_csv(text, ns.preset, mapping)
                if not rows:
                    raise InvalidInput("no data rows found under the header")
                params.update({"source": "csv", "rows": rows, "preset": ns.preset, "mapping": mapping})
        no_kind_signal = bool(ns.rows) or bool(mapping)
        if ns.kind:
            params["account_kind"] = ns.kind
        elif existing and existing.get("kind") and no_kind_signal:
            # --rows and --mapping have no kind of their own (rows default to "card", a mapping
            # preset is hard-coded "card"), so without --kind keep typing them the way the
            # account is already stored. A csv preset or OFX file carries its own implied kind,
            # which must outrank the stored kind so a conflict is still caught below.
            params["account_kind"] = existing["kind"]
        try:
            result = spendnormalize.run_spendnormalize(params)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        kind = result["account_kind"]
        old_kind = (existing or {}).get("kind")
        if old_kind and old_kind != kind:
            if {old_kind, kind} == {"checking", "savings"} and not ns.kind:
                kind = old_kind  # a savings account imported through a checking preset keeps its kind
            elif any(t["account_id"] == ns.account for t in book["transactions"]):
                raise InvalidInput(f"account {ns.account} holds {old_kind} rows; kind cannot change to {kind}", code="INVALID_ACCOUNT")
        account = {
            "id": ns.account,
            "name": ns.name or (existing or {}).get("name") or spending.statement_account_name(ns.account) or ns.account,
            "kind": kind, "preset": result["preset"], "added": (existing or {}).get("added") or date.today().isoformat(),
        }
        base = {
            "file": file_name, "preset": result["preset"], "account_id": ns.account, "header_line": header_line,
            "skipped": result["skipped"][:10], "skipped_count": len(result["skipped"]), "transfers_marked": result["transfers_marked"],
            "date_range": result["date_range"], "categories": result["categories"], "uncategorized": result["uncategorized"],
            "source": result["transactions"][0]["source"] if result["transactions"] else None,
        }
        if ns.dry_run:
            return {"dry_run": True, "count": result["count"], "sample": result["transactions"][:5], **base}
        book["accounts"][ns.account] = account
        added, dupes = spending.merge(book, result["transactions"], {"file": file_name, "account_id": ns.account, "preset": result["preset"]})
        pairs = spendnormalize.match_transfers(book["transactions"], book["accounts"])
        saved = spending.save(book)
        return {**base, "imported": added, "duplicates": dupes, "transfer_pairs": pairs, "spending_path": str(saved), "store_count": len(book["transactions"])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
