#!/usr/bin/env python3
"""Usage: spend.py month [YYYY-MM] [--compare-months N] [--as-of YYYY-MM-DD] [--items]
       spend.py changes [YYYY-MM] [--threshold 0.25] [--compare-months N] [--as-of YYYY-MM-DD]
                        [--items]
       spend.py recurring [--min-count 3]
       spend.py cashflow [--months 6] [--as-of YYYY-MM-DD]
       spend.py uncategorized [--limit 25] [--items]
       spend.py search TEXT [--start YYYY-MM-DD] [--end YYYY-MM-DD]
       spend.py merchants [--top 25] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--items]
       spend.py range --start YYYY-MM-DD --end YYYY-MM-DD [--by category|merchant|account|detail]
                       [--items]
       spend.py drill [PATH] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--no-items]
                      [--as-of YYYY-MM-DD]

Reports over ``spending.json`` under the plugin data dir (populated by import-spending.py),
computed by spendreport.py; every result adds ``accounts`` (the register) and
``spending_path``. ``--items`` explodes itemized detail into its own rows before totaling
(month/changes/range/merchants/uncategorized). ``drill`` walks the category/detail tree at
PATH (omit for the root; e.g. ``Groceries`` or ``Groceries/Costco``; ``Uncategorized`` is a
valid path), items exploded by default (``--no-items`` to disable). No network, no stdin.
Exit codes: 0, 2 (bad month, missing text or window, bad drill path), 4 (CONFIG_MISSING:
nothing imported yet), 5 (SPENDING_CORRUPT), 6.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import spendreport  # noqa: E402
from second_opinion import output, spending  # noqa: E402
from second_opinion.errors import ConfigError, InvalidInput  # noqa: E402

_SETUP_HINT = "nothing imported yet: run import-spending.py <file> --account ID first"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"spend.py: {message}")


def _build_parser() -> _Parser:
    p = _Parser(prog="spend.py", add_help=False)
    sub = p.add_subparsers(dest="report", required=True)

    def add(name: str, **kw) -> argparse.ArgumentParser:
        s = sub.add_parser(name, add_help=False)
        for flag, opts in kw.items():
            s.add_argument(flag, **opts)
        return s

    month = add(
        "month",
        **{
            "--compare-months": {"type": int, "default": 3},
            "--as-of": {"default": None},
            "--items": {"action": "store_true"},
        },
    )
    month.add_argument("month", nargs="?", default=None)
    changes = add(
        "changes",
        **{
            "--threshold": {"type": float, "default": 0.25},
            "--compare-months": {"type": int, "default": 3},
            "--as-of": {"default": None},
            "--items": {"action": "store_true"},
        },
    )
    changes.add_argument("month", nargs="?", default=None)
    add("recurring", **{"--min-count": {"type": int, "default": 3}})
    add("cashflow", **{"--months": {"type": int, "default": 6}, "--as-of": {"default": None}})
    add(
        "uncategorized",
        **{"--limit": {"type": int, "default": 25}, "--items": {"action": "store_true"}},
    )
    search = add("search", **{"--start": {"default": None}, "--end": {"default": None}})
    search.add_argument("text")
    add(
        "merchants",
        **{
            "--top": {"type": int, "default": 25},
            "--start": {"default": None},
            "--end": {"default": None},
            "--items": {"action": "store_true"},
        },
    )
    add(
        "range",
        **{
            "--start": {"required": True},
            "--end": {"required": True},
            "--by": {
                "default": "category",
                "choices": ["category", "merchant", "account", "detail"],
            },
            "--items": {"action": "store_true"},
        },
    )
    drill = add(
        "drill",
        **{
            "--start": {"default": None},
            "--end": {"default": None},
            "--no-items": {"action": "store_true"},
            "--as-of": {"default": None},
        },
    )
    drill.add_argument("path", nargs="?", default="")
    return p


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        ns = _build_parser().parse_args(args)
        path = spending.spending_path()
        if not path.is_file():
            raise ConfigError("no spending file", hint=_SETUP_HINT, path=str(path))
        book = spending.load(path)
        params = {
            "accounts": book["accounts"],
            "transactions": book["transactions"],
            "report": ns.report,
        }
        opts = {
            k.replace("-", "_"): v for k, v in vars(ns).items() if k != "report" and v is not None
        }
        no_items = opts.pop("no_items", None)
        if opts.get("items") is False:
            opts.pop("items")
        params.update(opts)
        if ns.report == "drill":
            params["items"] = not no_items
        try:
            result = spendreport.run_spendreport(params)
        except (ValueError, TypeError) as exc:
            raise InvalidInput(str(exc)) from exc
        return {**result, "accounts": book["accounts"], "spending_path": str(path)}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
