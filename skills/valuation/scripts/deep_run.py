#!/usr/bin/env python3
"""Usage: deep_run.py --case DIR [--label TEXT] [--compare-to N]

One pass of the deep valuation's arithmetic over a case folder. Reads ``DIR/model.json`` (model.py's
input; top-level keys starting with ``_``, such as the skeleton's ``_notes``, are dropped and the file
is left as it is), runs model.py and then returns.py on the model's ``returns_input``, and writes:

    model.out.json     model.py's output, unchanged
    returns.out.json   returns.py's output, unchanged
    runs.json          a list with one entry per run: what this script printed, plus "at" (UTC time)

Prints::

    {"run": n, "label", "price",
     "scenarios": [{"name", "value_per_share", "value_ex_premiums", "upside", "irr", "change_vs_prev", "stress"}],
     "compared_to", "max_move", "round2_due", "unmatched": [{"name", "run", "value_per_share"}],
     "position", "implied", "flags": [{"code", "message"}]}

``run`` counts from 1. ``irr`` is returns.py's annualized return at today's price. ``compared_to``
is the run the move is measured against: ``--compare-to N`` (a ``run`` number in runs.json), by
default the previous run; null on the first run. Pass the number of the last run before a thread
round when the model is rerun more than once inside the round, or the round's total move is hidden
from ``round2_due``. ``change_vs_prev`` is value_per_share against the same-named scenario in that
run, as a fraction of that run's value's size (0.12 is 12% higher); null on the first run, for a
scenario that run did not have, and when its value was 0. ``max_move`` is the largest absolute
change_vs_prev, null when there is none. ``round2_due`` is true when max_move is above 0.10: a
scenario moved more than 10%, so a second thread round is worth running.

Renamed, added or dropped scenarios. ``unmatched`` lists every scenario with no namesake on the
other side: this run's (``run`` is this run's number) first, then the compared run's (``run`` is
its number), each with its value; empty when the names agree and on the first run. Any entry
raises the flag SCENARIOS_CHANGED, which names them. The central scenario is the first one: when
it has no namesake in the compared run ("Base" renamed "Base case"), it is measured against that
run's first scenario instead, and that move counts in ``max_move`` and so in ``round2_due`` (its
own ``change_vs_prev`` stays null, and the flag's message gives the figure). Keep scenario names
the same between runs and nothing here fires.

``position`` says where the price sits among the
scenario values: ``all_above_price`` (every value is above the price), ``all_below_price``, or
``brackets_price``; null without a price. ``implied`` is model.py's (what the price implies).
``flags`` are model.py's followed by returns.py's.

Exit 2 with ``{"error", "code"}`` and nothing written when model.json is missing or not a JSON
object, when ``--compare-to`` names a run runs.json does not have, when model.py rejects it (its ``error`` text passes through), or when returns.py rejects the
model's returns_input (a model without a price, for one). The outputs of an earlier run stay as they
were. Pure arithmetic: nothing is fetched.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

HERE = Path(__file__).resolve().parent
ROUND2_MOVE = 0.10  # a scenario value moving more than this against the compared run calls a second thread round


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"deep_run.py: {message}")


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"deep_run_{name}", HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run_script(name: str, payload: dict) -> dict:
    """Run a stdin -> stdout script's own main() in this process and return its JSON. Its exit 2
    becomes InvalidInput carrying its error text."""
    mod = _load(name)
    stdin, buf, code = sys.stdin, io.StringIO(), 0
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(buf):
            try:
                mod.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.stdin = stdin
    try:
        result = json.loads(buf.getvalue())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name}.py printed no JSON (exit {code})") from exc
    if code != 0:
        raise InvalidInput(str(result.get("error") or f"{name}.py exit {code}") if isinstance(result, dict) else f"{name}.py exit {code}", script=f"{name}.py")
    return result


def _read_runs(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        runs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"could not read {path}: {exc}") from exc
    if not isinstance(runs, list) or not all(isinstance(r, dict) for r in runs):
        raise InvalidInput(f"{path} must be a JSON list of runs")
    return runs


def _position(values: list[float], price: object) -> str | None:
    if not values or isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    if all(v > price for v in values):
        return "all_above_price"
    if all(v < price for v in values):
        return "all_below_price"
    return "brackets_price"


def _compared(runs: list[dict], number: int | None) -> dict | None:
    """The run the move is measured against: run ``number``, or the previous run when it is None."""
    if number is None:
        return runs[-1] if runs else None
    for entry in runs:
        if entry.get("run") == number and not isinstance(entry.get("run"), bool):
            return entry
    have = ", ".join(str(r.get("run")) for r in runs) or "none yet"
    raise InvalidInput(f"--compare-to {number}: runs.json has no run {number} (runs: {have})")


def summarize(model: dict, rets: dict, runs: list[dict], label: str | None, against: dict | None = None) -> dict:
    """What the script prints. ``against`` is the run to measure the move from (default the last of ``runs``)."""
    against = against if against is not None else (runs[-1] if runs else None)
    prev = {s.get("name"): s.get("value_per_share") for s in (against.get("scenarios") or [])} if against else {}
    irr = {s["name"]: s.get("irr") for s in rets.get("scenarios") or []}
    scenarios = []
    for s in model["scenarios"]:
        before = prev.get(s["name"])
        change = round((s["value_per_share"] - before) / abs(before), 4) if isinstance(before, (int, float)) and before else None
        scenarios.append({"name": s["name"], "value_per_share": s["value_per_share"], "value_ex_premiums": s["value_ex_premiums"],
                          "upside": s["upside"], "irr": irr.get(s["name"]), "change_vs_prev": change, "stress": bool(s.get("stress"))})
    moves = [abs(s["change_vs_prev"]) for s in scenarios if s["change_vs_prev"] is not None]

    number = len(runs) + 1
    before_rows = [s for s in (against.get("scenarios") or []) if isinstance(s, dict)] if against else []
    names = {s["name"] for s in scenarios}
    unmatched = [{"name": s["name"], "run": number, "value_per_share": s["value_per_share"]} for s in scenarios if s["name"] not in prev] if against else []
    unmatched += [{"name": s.get("name"), "run": against.get("run"), "value_per_share": s.get("value_per_share")} for s in before_rows if s.get("name") not in names]
    extra_flags: list[dict] = []
    if unmatched:
        new = [repr(u["name"]) for u in unmatched if u["run"] == number]
        gone = [repr(u["name"]) for u in unmatched if u["run"] != number]
        message = (f"the scenario names differ from run {against.get('run')}: " + "; ".join(part for part in (
            f"new in this run: {', '.join(new)}" if new else "", f"only in run {against.get('run')}: {', '.join(gone)}" if gone else "") if part)
            + ". A scenario without a namesake has no change_vs_prev")
        central, was = (scenarios[0] if scenarios else None), (before_rows[0] if before_rows else None)
        if central is not None and central["name"] not in prev and was is not None:
            old = was.get("value_per_share")
            if isinstance(old, (int, float)) and not isinstance(old, bool) and old:
                central_move = round((central["value_per_share"] - old) / abs(old), 4)
                moves.append(abs(central_move))
                message += (f". The central (first) scenario {central['name']!r} was measured against that run's first scenario {was.get('name')!r} instead: "
                            f"{old} to {central['value_per_share']}, {central_move:+.1%}, which counts in max_move and round2_due")
            else:
                message += f". The central (first) scenario {central['name']!r} could not be measured against that run's first scenario {was.get('name')!r} (no value there)"
        extra_flags.append({"code": "SCENARIOS_CHANGED", "message": message + ". Keep the names the same between runs."})
    max_move = max(moves) if moves else None
    return {"run": number, "label": label, "price": model.get("price"), "scenarios": scenarios,
            "compared_to": against.get("run") if against else None, "max_move": max_move, "round2_due": max_move is not None and max_move > ROUND2_MOVE,
            "unmatched": unmatched,
            "position": _position([s["value_per_share"] for s in scenarios], model.get("price")),
            "implied": model.get("implied"), "flags": [*(model.get("flags") or []), *(rets.get("flags") or []), *extra_flags]}


def _go(args: list[str]) -> dict:
    p = _Parser(prog="deep_run.py", add_help=False)
    p.add_argument("--case", required=True)
    p.add_argument("--label", default=None)
    p.add_argument("--compare-to", dest="compare_to", type=int, default=None)
    ns = p.parse_args(args)
    case = Path(ns.case).expanduser()
    src = case / "model.json"
    if not src.is_file():
        raise InvalidInput(f"{case} has no model.json; fill model.skeleton.json into model.json first")
    try:
        params = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"could not read {src}: {exc}") from exc
    if not isinstance(params, dict):
        raise InvalidInput(f"{src} (model.json) must be a JSON object")
    runs = _read_runs(case / "runs.json")
    against = _compared(runs, ns.compare_to)
    model = _run_script("model", {k: v for k, v in params.items() if not str(k).startswith("_")})
    rets = _run_script("returns", model["returns_input"])
    result = summarize(model, rets, runs, ns.label, against)
    (case / "model.out.json").write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    (case / "returns.out.json").write_text(json.dumps(rets, indent=2) + "\n", encoding="utf-8")
    runs.append({**result, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    (case / "runs.json").write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    return output.run(_go, argv)


if __name__ == "__main__":
    sys.exit(main())
