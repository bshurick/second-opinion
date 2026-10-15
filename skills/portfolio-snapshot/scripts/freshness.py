#!/usr/bin/env python3
"""Usage: freshness.py [--now YYYY-MM-DDTHH:MM:SS+HH:MM]

One plain-text line for the plugin's UserPromptSubmit hook (hooks/portfolio-freshness.sh) saying
when the portfolio was last read, so the model refreshes it before discussing changes to holdings.
No network; reads files in the plugin data dir only.

The last check is ``portfolio-last-check.json`` (written by snapshot.py on every run over all
accounts), else the newest of ``brief-last.json``'s and the last ``snapshots.json`` record's
``as_of``. Prints:

- nothing when the last check falls on today's local date;
- nothing when there is no check on record and no brokerage connected (no ``brokers.json``);
- otherwise one line with the local time now, the last check's local time and its age, and what
  to run.

``--now`` sets the current time (for tests). Exit code 0 always; any error prints nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

LAST_CHECK_FILE = "portfolio-last-check.json"
RUN = "portfolio-snapshot's brief.py --no-headlines"


def _data_dir() -> Path:
    from second_opinion import config

    return config.data_dir()


def _as_of(path: Path, records_key: str | None = None) -> datetime | None:
    try:
        data = json.loads(path.read_text())
        if records_key:
            data = (data.get(records_key) or [{}])[-1]
        value = datetime.fromisoformat(str(data["as_of"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return None
    return value if value.tzinfo else value.astimezone()


def last_check(data_dir: Path) -> tuple[datetime | None, bool]:
    """(when the portfolio was last read, whether that read left out a broker)."""
    marker = data_dir / LAST_CHECK_FILE
    when = _as_of(marker)
    if when is not None:
        try:
            partial = bool(json.loads(marker.read_text()).get("partial"))
        except (OSError, ValueError, AttributeError):
            partial = False
        return when, partial
    found = [t for t in (_as_of(data_dir / "brief-last.json"), _as_of(data_dir / "snapshots.json", "snapshots")) if t]
    return (max(found) if found else None), False


def _age(delta_hours: float) -> str:
    if delta_hours < 48:
        return f"{max(delta_hours, 0):.0f} hours ago"
    return f"{delta_hours / 24:.0f} days ago"


def line(data_dir: Path, now: datetime) -> str | None:
    when, partial = last_check(data_dir)
    now_local = now.astimezone()
    if when is None:
        if not (data_dir / "brokers.json").is_file():
            return None
        return (f"Second Opinion: it is {now_local:%Y-%m-%d %H:%M} local time and the portfolio has not been read "
                f"in Second Opinion yet. Before discussing any change to holdings, run {RUN} first.")
    local = when.astimezone()
    if local.date() == now_local.date():
        return None
    hours = (now_local - local).total_seconds() / 3600
    note = " (that read left out a broker)" if partial else ""
    return (f"Second Opinion: it is {now_local:%Y-%m-%d %H:%M} local time; the portfolio was last read "
            f"{local:%Y-%m-%d %H:%M} ({_age(hours)}){note}. Before discussing any change to holdings, "
            f"run {RUN} first.")


def main(argv: list[str] | None = None) -> int:
    try:
        p = argparse.ArgumentParser(prog="freshness.py", add_help=False)
        p.add_argument("--now")
        ns = p.parse_args(argv)
        now = datetime.fromisoformat(ns.now) if ns.now else datetime.now().astimezone()
        text = line(_data_dir(), now if now.tzinfo else now.astimezone())
    except Exception:  # noqa: BLE001 - a hook never fails the prompt
        return 0
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
