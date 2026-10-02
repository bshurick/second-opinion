#!/usr/bin/env python3
"""Usage: import-csv.py <file.csv> [--account ACCOUNT_ID] [--mapping JSON] [--dry-run]

Import a brokerage CSV export into the local ledger (``ledger.json`` under the
plugin data dir). The header row is found automatically (preamble lines such
as "Brokerage" and trailing disclaimers are skipped), columns are detected by
normalize.py's aliases (override with --mapping '{"date": "...", ...}'), and
rows are deduplicated against what is already in the ledger. stdin is unused.

Output: {file, header_line, account_id, columns, imported, duplicates,
skipped (first 10), skipped_count, types, date_range, ledger_path,
ledger_count}. With --dry-run: normalize.py's full output plus dry_run: true,
and nothing is written. Exit codes: 0, 2, 5 (LEDGER_CORRUPT), 6.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import normalize  # noqa: E402
from second_opinion import ledger, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"import-csv.py: {message}")


def _known_header(fields: list[str]) -> bool:
    known = set(normalize._FEE_ALIASES) | {a for aliases in normalize._ALIASES.values() for a in aliases}  # noqa: SLF001
    return sum(1 for f in fields if normalize._norm(f) in known) >= 2  # noqa: SLF001


def _mapped_header(fields: list[str], mapping: dict) -> bool:
    wanted = [v for k, v in mapping.items() if k != "fee" and isinstance(v, str)]
    fee = mapping.get("fee") or []
    wanted += [v for v in (fee if isinstance(fee, list) else [fee]) if isinstance(v, str)]
    return bool(wanted) and all(w in fields for w in wanted)


def read_rows(text: str, mapping: dict | None = None) -> tuple[int, list[dict]]:
    """(1-based header line number, data rows) from a CSV export with preamble/trailer lines."""
    lines = text.lstrip("﻿").splitlines()
    for i, line in enumerate(lines):
        try:
            fields = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            continue
        if fields and (_known_header(fields) or _mapped_header(fields, mapping or {})):
            reader = csv.DictReader(io.StringIO("\n".join(lines[i:])))
            rows = []
            for r in reader:
                clean = {k: (v or "") for k, v in r.items() if k is not None}
                rows.append(clean)
            return i + 1, rows
    raise InvalidInput("no header row with recognizable columns found; pass --mapping or check the file")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="import-csv.py", add_help=False)
        p.add_argument("file")
        p.add_argument("--account", default=None)
        p.add_argument("--mapping", default=None)
        p.add_argument("--dry-run", action="store_true")
        ns = p.parse_args(args)
        path = Path(ns.file).expanduser()
        if not path.is_file():
            raise InvalidInput(f"file not found: {path}")
        mapping = {}
        if ns.mapping:
            try:
                mapping = json.loads(ns.mapping)
            except ValueError as exc:
                raise InvalidInput(f"--mapping must be JSON: {exc}") from exc
        header_line, rows = read_rows(path.read_text(encoding="utf-8-sig", errors="replace"), mapping)
        if not rows:
            raise InvalidInput("no data rows found under the header")
        result = normalize.run_normalize({"source": "csv", "account_id": ns.account, "rows": rows, "mapping": mapping})
        if ns.dry_run:
            return {"dry_run": True, "file": str(path), "header_line": header_line, **result}
        book = ledger.load()
        added, dupes = ledger.merge(book, result["transactions"], source=path.name)
        saved = ledger.save(book)
        return {
            "file": str(path), "header_line": header_line, "account_id": ns.account, "columns": result["columns"],
            "imported": added, "duplicates": dupes, "skipped": result["skipped"][:10], "skipped_count": len(result["skipped"]),
            "types": result["types"], "date_range": result["date_range"],
            "ledger_path": str(saved), "ledger_count": len(book["transactions"]),
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
