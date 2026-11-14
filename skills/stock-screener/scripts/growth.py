#!/usr/bin/env python3
"""Shared helpers for the deep picker's growth mode: the run's profile and the growth thresholds.

Mostly a module: picker scripts load it by path or put its folder on ``sys.path``. Stdlib plus
``second_opinion.errors``; importing it has no side effects. Run as ``growth.py DIR`` it prints
the run's profile as ``{"profile": ...}`` (exit 2 on an unknown one). stdin is unused.

The profile lives in ``DIR/run.json`` as ``{"profile": "value" | "growth"}``, written by
``pick_prep.py``. A run folder without that file is a ``value`` run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion.errors import InvalidInput  # noqa: E402

PROFILES = ("value", "growth")
MIN_UPSIDE_DEFAULT = 2.0  # best-case multiple of today's price a growth pick must be able to reach
RUN_FILE = "run.json"


def run_profile(run_dir: Path) -> str:
    """The run's profile: ``value`` when ``run.json`` is missing; InvalidInput when it names another."""
    path = Path(run_dir) / RUN_FILE
    if not path.is_file():
        return "value"
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise InvalidInput(f"{path} is not valid JSON: {exc}") from exc
    profile = data.get("profile") if isinstance(data, dict) else None
    if profile not in PROFILES:
        raise InvalidInput(f"{path}: profile must be one of {', '.join(PROFILES)}, got {profile!r}")
    return profile


def write_profile(run_dir: Path, profile: str) -> Path:
    """Write ``run.json`` (replacing any earlier one) and return its path."""
    if profile not in PROFILES:
        raise InvalidInput(f"profile must be one of {', '.join(PROFILES)}, got {profile!r}")
    path = Path(run_dir) / RUN_FILE
    path.write_text(json.dumps({"profile": profile}) + "\n")
    return path


def best_irr_needed(min_upside: float, horizon: int) -> float:
    """The yearly return that reaches ``min_upside`` times today's price in ``horizon`` years."""
    if min_upside <= 1 or horizon < 1:
        raise ValueError("min_upside must be above 1 and horizon at least 1 year")
    return min_upside ** (1 / horizon) - 1


def upside_hint(quick: dict, price: float | None, fcf_latest: float | None) -> int | None:
    """A starting point for a growth card's ``upside`` score (1-5) from the quick value's bull and base.

    5: bull at least 2x the price and base above it; 4: bull at least 1.5x and base above the
    price; 3: bull at least 1.5x; 2: bull above the price; else 1. None when the quick value has
    no ``basis`` (no DCF), bull or price is missing, or the latest annual free cash flow is not
    positive (``fcf_latest`` None means the pack had none: not held against the name).
    """
    def num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None

    bull, base, px = num(quick.get("bull")), num(quick.get("base")), num(price)
    fcf = num(fcf_latest)
    if not quick.get("basis") or bull is None or px is None or px <= 0 or (fcf is not None and fcf <= 0):
        return None
    above = base is not None and base > px
    if bull / px >= 2 and above:
        return 5
    if bull / px >= 1.5 and above:
        return 4
    if bull / px >= 1.5:
        return 3
    return 2 if bull > px else 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: growth.py DIR", file=sys.stderr)
        return 2
    try:
        print(json.dumps({"profile": run_profile(Path(args[0]))}))
    except InvalidInput as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
