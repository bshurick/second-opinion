#!/usr/bin/env python3
"""Usage: configure.py keys [--broker snaptrade|etrade]

Brokerage key entry without Node, for the person to run in their own terminal. Each key is read
with hidden input; a blank answer keeps the saved value. The keys go to ``<data dir>/.env``
(``~/.claude/plugins/data/second-opinion/.env`` by default), written atomically at mode 0600.
Every other line in the file (comments, other keys) is kept as it was.

  snaptrade (default)  SNAPTRADE_CLIENT_ID, SNAPTRADE_CONSUMER_KEY
  etrade               ETRADE_CONSUMER_KEY, ETRADE_CONSUMER_SECRET

Prints which keys were saved and which were kept, never a key's value. Exit codes: 0; 2 for bad
arguments or when stdin is not a terminal (keys are never typed into a chat or a pipe).
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import config  # noqa: E402

KEYS = {
    "snaptrade": ("SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY"),
    "etrade": ("ETRADE_CONSUMER_KEY", "ETRADE_CONSUMER_SECRET"),
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # exit 2 with one line, no usage dump
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)


def _quote(value: str) -> str:
    """The value as written on a KEY=VALUE line, as install.js writes it."""
    if not re.search(r"[\s\"']", value):
        return value
    return f"'{value}'" if '"' in value and "'" not in value else f'"{value}"'


def _key_of(line: str) -> str | None:
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    if s.startswith("export "):
        s = s[len("export "):].lstrip()
    return s.partition("=")[0].strip() or None


def _write(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text().splitlines() if path.is_file() else []
    done: set[str] = set()
    out = []
    for line in lines:
        key = _key_of(line)
        if key in updates:
            out.append(f"{key}={_quote(updates[key])}")
            done.add(key)
        else:
            out.append(line)
    out += [f"{k}={_quote(v)}" for k, v in updates.items() if k not in done]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(out) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    path.chmod(0o600)


def _mask(value: str) -> str:
    return f"…{value[-4:]}" if len(value) > 8 else "…"


def main(argv: list[str] | None = None) -> int:
    p = _Parser(prog="configure.py", add_help=False)
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sub.add_parser("keys", add_help=False).add_argument("--broker", choices=sorted(KEYS), default="snaptrade")
    try:
        ns = p.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    if not sys.stdin.isatty():
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} keys"
        print(f"error: key entry needs a terminal. Run this in your own terminal, not in the chat:\n  {command}",
              file=sys.stderr)
        return 2
    path = config.data_dir() / ".env"
    saved = config.parse_env_file(path) if path.is_file() else {}
    updates: dict[str, str] = {}
    report = []
    for key in KEYS[ns.broker]:
        hint = ", Enter keeps the saved one" if saved.get(key) else ""
        value = getpass.getpass(f"{key} (hidden{hint}): ").strip()
        if value:
            updates[key] = value
            report.append(f"saved {key} ({_mask(value)})")
        elif saved.get(key):
            report.append(f"kept {key}")
        else:
            report.append(f"{key} not set")
    if updates:
        _write(path, updates)
    print(f"{path}: " + "; ".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
