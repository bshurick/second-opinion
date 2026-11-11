#!/usr/bin/env python3
"""Usage: brief.py [snapshot.py flags...] [--no-headlines] [--timeout SECONDS] [--workers N]

The daily brief: the portfolio snapshot (``snapshot.py`` with ``--events`` always on) plus ranked headlines
from the other installed second-opinion skills. Every ``snapshot.py`` flag passes through (``--account``,
``--no-quotes``, ``--no-news``, ``--save``, ``--compare``, ``--partial``). Each source skill's script runs as a
subprocess in a thread pool; a missing skill, an unmet prerequisite, a timeout or a failure becomes a
``coverage`` row and never fails the brief. Afterward, an enrichment pass fills in ``answer`` on a few
headlines that need a cross-source lookup or one extra script call (EX_DIVIDEND, EARNINGS, FILING); it
too never fails the brief and never touches ``coverage``. ``brief-last.json`` in the plugin data dir
remembers the last run's headline keys (so this run marks each ``new`` or ``still``) and its risk
figures. A write failure there becomes a ``BRIEF_MEMORY_UNAVAILABLE`` flag rather than failing the run.

Output: the snapshot JSON plus ``headlines`` (ordered: every new headline first, whatever its severity; then alerts, notices, info), ``coverage``
(one row per source: skill, script, status ok/skipped/failed, reason, hint, seconds, headlines),
``brief_as_of`` and ``brief_seconds``. ``--no-headlines`` gives the plain snapshot and writes nothing.
Exit codes are the snapshot's own (0, 2, 4, 5, 6); source failures never change them.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import config, headlines, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402
from second_opinion.headlines import risk as risk_headlines  # noqa: E402
from second_opinion.headlines import sources  # noqa: E402


def _load_snapshot_module():
    path = Path(__file__).resolve().parent / "snapshot.py"
    spec = importlib.util.spec_from_file_location("snapshot", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


snapshot = _load_snapshot_module()


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"brief.py: {message}")


def _single_stock_symbols(snap: dict) -> list[str]:
    """Single-stock symbols, largest market value first (ties broken alphabetically) so a capped fan-out keeps the biggest holdings."""
    profiles = snap.get("profiles") or {}
    candidates = [p for p in snap.get("positions") or []
                  if p.get("symbol") and (profiles.get(str(p.get("symbol")).upper()) or {}).get("quote_type") == "EQUITY"]
    candidates.sort(key=lambda p: (-(p.get("market_value") or 0), str(p.get("symbol")).upper()))
    return [str(p.get("symbol")).upper() for p in candidates]


def build(args: list[str]) -> dict:
    p = _Parser(prog="brief.py", add_help=False)
    p.add_argument("--no-headlines", dest="no_headlines", action="store_true")
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--workers", type=int, default=6)
    ns, passthrough = p.parse_known_args(args)
    if ns.no_headlines:
        return snapshot.build(passthrough)
    started = time.monotonic()
    snap = snapshot.build([*passthrough, "--events"] if "--events" not in passthrough else passthrough)
    now = datetime.now(timezone.utc)
    ctx = {
        "today": now.date(),
        "now": now.isoformat(timespec="seconds"),
        "snapshot": snap,
        "previous": headlines.load_last(),
        "symbols": _single_stock_symbols(snap),
        "partial": "--partial" in passthrough,
        "data_dir": config.data_dir(),
        "plugin_root": config.PLUGIN_ROOT,
        "python": sys.executable,
        "risk_results": {},
    }
    found, coverage = sources.run_all(ctx, timeout=ns.timeout, workers=ns.workers)
    found = sources.enrich(found, ctx, timeout=ns.timeout)
    risk_memory = risk_headlines.snapshot_for_last(ctx["risk_results"]) or (ctx["previous"].get("risk") or {})
    failed_skills = {row["skill"] for row in coverage if row.get("status") != "ok"}
    extra_keys = [k for k in ctx["previous"].get("keys") or [] if k.split(":", 1)[0] in failed_skills]
    try:
        headlines.save_last(ctx["now"], found, risk_memory, extra_keys)
    except OSError as exc:
        snap.setdefault("flags", []).append({"code": "BRIEF_MEMORY_UNAVAILABLE", "message": f"could not write brief-last.json: {exc}"})
    return {**snap, "headlines": found, "coverage": coverage, "brief_as_of": ctx["now"], "brief_seconds": round(time.monotonic() - started, 1)}


def main(argv: list[str] | None = None) -> int:
    return output.run(build, argv)


if __name__ == "__main__":
    sys.exit(main())
