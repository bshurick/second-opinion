#!/usr/bin/env python3
"""Usage: local_page.py --in PAGE.html [--name NAME] [--no-open]

Saves a rendered report page where the person can open it, for a session with no Artifact tool
(a model from another provider, or a headless host). PAGE.html is the fragment a skill's render
script wrote. This script wraps it into a whole HTML document, writes it to ``pages/NAME.html``
in the plugin data directory (NAME defaults to the input file's name, so a later run of the same
report replaces the same file) and opens it in the default browser.

Prints {"path", "url", "opened", "title"}. ``opened`` is false with --no-open or when no browser
could be started; the file is saved either way. Nothing leaves the machine.

Exit codes: 0, 2 (no --in, an unreadable or empty file, or a NAME with a path separator), 6.
"""
from __future__ import annotations

import argparse
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import config, output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

USAGE = "usage: local_page.py --in PAGE.html [--name NAME] [--no-open]"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"{USAGE} ({message})")


def run(args: list[str]) -> dict:
    p = _Parser(prog="local_page.py", add_help=False)
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--no-open", action="store_true")
    ns = p.parse_args(args)

    src = Path(ns.inp).expanduser()
    try:
        fragment = src.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidInput(f"could not read the page {src}: {exc}") from exc
    if not fragment.strip():
        raise InvalidInput(f"the page {src} is empty")
    name = ns.name or src.stem
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise InvalidInput("NAME takes letters, digits, dots, dashes and underscores only")
    if name.lower().endswith(".html"):
        name = name[:-5]

    out = page.write(config.data_dir() / "pages" / f"{name}.html", page.standalone(fragment))
    url = out.resolve().as_uri()
    opened = False
    if not ns.no_open:
        try:
            opened = bool(webbrowser.open(url))
        except Exception:  # noqa: BLE001 — a host with no browser still gets the saved file
            opened = False
    found = re.search(r"<title>(.*?)</title>", fragment, re.S)
    return {"path": str(out), "url": url, "opened": opened, "title": found.group(1) if found else None}


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
