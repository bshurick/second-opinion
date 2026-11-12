#!/usr/bin/env python3
"""Usage: pick_assemble.py --run DIR --finalists SYM=URL[,SYM=URL...] [--cases DIR] [--hurdle R]
                         [--floor R] [--notes FILE] [--as-of YYYY-MM-DD]

The deep picker's last mechanical step: the downside gate, ``pick.json`` and the picks page, from
the run folder and each finalist's deep-valuation folder. Nothing is fetched.

``--finalists`` pairs each finalist with the https link of its published deep valuation
(repeatable; the order given is kept in ``gate.json``). ``--cases`` is the folder holding the
``deep-SYM`` case folders (default: the run folder's parent). Reads, per finalist,
``deep-SYM/model.out.json`` and ``returns.out.json`` (deep_run.py's files), and from the run
folder ``industries/*.json``, ``cards/<TICKER>.json`` (the quick readers' cards; ``*.data.json``
is not a card), ``pool.json``, ``budget.json`` and the notes file (``--notes``, default
``DIR/picks-notes.json`` when it exists)::

    {"picks": {"SYM": {"thesis", "bad_pick"}}, "missing_roles": [...], "notes": [...], "profile"}

Writes into the run folder, all four or none:

    gate.json      gate.py's input: {"hurdle"?, "floor"?, "finalists": [{"symbol", "price", "page",
                   "model", "returns"}]}; the price is the one returns.py used
    gate.out.json  gate.py's output (its own run_gate), unchanged
    pick.json      render_pick.py's input (see its docstring)
    page.html      render_pick.py's page

``pick.json``: ``gate`` (gate.out.json); ``funnel`` (Industries scanned, Screen survivors, Merged
pool, Health check passed, Kept for quick read, Quick reads, Finalists, Picks: the pool stages
come from pool.json's counts and are left out without it. "Health check passed" counts only the
names whose health is ``passed`` (``counts.health.passed``, or the pool rows' own ``health`` when
the counts have none); "Kept for quick read" is ``counts.kept``, which also holds the financial,
incomplete, not-found and judge-in-quick-read names. When the health screen did not run (every
name ``unchecked``) or nothing says who passed, the "Health check passed" stage is left out, and
in the first case a note and the flag HEALTH_NOT_CHECKED say so); ``industries`` (every list in ``industries/*.json`` joined,
by file name); ``candidates`` (each card, plus ``held`` from the pool and ``finalist``);
``picks``, ``missing_roles``, ``notes`` and ``profile`` from the notes file; ``as_of`` (today
unless ``--as-of``). A ``picks`` entry for a finalist that failed the gate, or for a symbol that
is not a finalist, is dropped and named in ``notes``. One note is added with the searches used
against ``budget.json``; when the finalists' case folders have their own ``budget.json``, their
sum is the ``valuations`` figure (so the run budget need not repeat it). Text passes through
unchanged.

Prints {"out": <page.html>, "pick": <pick.json>, "gate": {"pass", "pass_flagged", "fail"},
"picks": [symbols], "near_misses": [symbols], "save_commands": ["<python> <picks.py> save-deep
SYM --case <deep-SYM> --thesis '<thesis>' --source URL", ...one per pick, shell-quoted...],
"flags": [{"code", "message"}]}. Flags: HEALTH_NOT_CHECKED, PICK_NOTE_DROPPED, THESIS_MISSING (a pick with no
thesis in the notes), POOL_MISSING, BUDGET_UNAVAILABLE, CARD_SKIPPED and INDUSTRY_FILE_SKIPPED
(a file that is not JSON or not the expected shape), FINALIST_WITHOUT_CARD, CASE_PAGE_MISSING
(a pick's case folder has no page.json, which ``save-deep --case`` reads).

Exit 2, before anything is written: a finalist with no (or an unreadable) ``model.out.json`` or
``returns.out.json`` (the message names the finalist), a link that is not https, a repeated or
malformed finalist, a notes file that is missing or not that shape, gate.py rejecting its input,
or render_pick.py rejecting pick.json (a card score outside 1-5, an unknown industry verdict, an
evidence claim without a source or date). stdin is unused.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import brokerage, output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

BUDGET_SCRIPT = _HERE.parents[1] / "valuation" / "scripts" / "budget.py"
PICKS_SCRIPT = _HERE / "picks.py"
NOTES_FILE = "picks-notes.json"
PASSING = ("pass", "pass_flagged")
_NEXT_FINALIST = re.compile(r",(?=[^,=]*=)")  # a comma that starts another SYM=URL, not one inside a link


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"pick_assemble.py: {message}")


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="pick_assemble.py", add_help=False)
    p.add_argument("--run", required=True)
    p.add_argument("--finalists", action="append", required=True, metavar="SYM=URL,SYM=URL")
    p.add_argument("--cases")
    p.add_argument("--hurdle", type=float)
    p.add_argument("--floor", type=float)
    p.add_argument("--notes")
    p.add_argument("--as-of", dest="as_of")
    return p


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"pick_assemble_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def parse_finalists(items: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in items:
        for part in _NEXT_FINALIST.split(item):
            if not part.strip():
                continue
            raw, sep, url = part.strip().partition("=")
            if not sep or not url.strip():
                raise InvalidInput(f"--finalists wants SYM=URL, got {part.strip()!r}")
            symbol, url = brokerage.validate_symbol(raw), url.strip()
            if not url.lower().startswith("https://"):
                raise InvalidInput(f"{symbol}: the deep valuation link must be an https:// link, got {url!r}")
            if symbol in (s for s, _ in out):
                raise InvalidInput(f"{symbol} is given twice in --finalists")
            out.append((symbol, url))
    if not out:
        raise InvalidInput("--finalists named no finalist")
    return out


def gate_input(finalists: list[tuple[str, str]], cases: Path, hurdle: float | None, floor: float | None) -> dict:
    rows = []
    for symbol, url in finalists:
        case = cases / f"deep-{symbol}"
        loaded = {}
        for name in ("model.out.json", "returns.out.json"):
            path = case / name
            if not path.is_file():
                raise InvalidInput(f"finalist {symbol} has no {name} in {case}; run deep_run.py --case {case} first")
            loaded[name] = _read(path)
            if not isinstance(loaded[name], dict):
                raise InvalidInput(f"finalist {symbol}: {path} is not a JSON object")
        model, rets = loaded["model.out.json"], loaded["returns.out.json"]
        price = rets.get("price") if rets.get("price") is not None else model.get("price")
        rows.append({"symbol": symbol, "price": price, "page": url, "model": model, "returns": rets})
    out: dict[str, Any] = {"finalists": rows}
    if hurdle is not None:
        out["hurdle"] = hurdle
    if floor is not None:
        out["floor"] = floor
    return out


def read_notes(path: Path | None) -> dict:
    if path is None:
        return {}
    data = _read(path)
    if not isinstance(data, dict):
        raise InvalidInput(f"notes file {path} is missing or not a JSON object")
    picks = data.get("picks") or {}
    if not isinstance(picks, dict) or not all(isinstance(v, dict) for v in picks.values()):
        raise InvalidInput(f"notes file {path}: picks must map each symbol to {{thesis, bad_pick}}")
    for key in ("missing_roles", "notes"):
        if not isinstance(data.get(key) or [], list):
            raise InvalidInput(f"notes file {path}: {key} must be a list")
    return data


def searches_note(run_dir: Path, case_dirs: list[Path], flags: list[dict]) -> str | None:
    """One line of searches used against the run's budget.json, or None (flagged) without one."""
    try:
        budget = _load(BUDGET_SCRIPT)
        status = budget.show(run_dir)
    except Exception as exc:  # noqa: BLE001 — the page stands without the line
        flags.append({"code": "BUDGET_UNAVAILABLE", "message": f"no searches line on the page: {exc}"})
        return None
    used = dict(status["used"])
    in_cases = []
    for case in case_dirs:
        try:
            in_cases.append(budget.show(case)["used_total"])
        except Exception:  # noqa: BLE001 — a case without its own budget
            continue
    if in_cases and "valuations" in used:
        used["valuations"] = sum(in_cases)
    parts = ", ".join(f"{role.replace('_', ' ')} {used[role]} of {cap}" for role, cap in status["caps"].items())
    return f"Searches: {sum(used.values())} used of {status['total']} planned ({parts})."


def run(args: list[str]) -> dict:
    ns = parser().parse_args(args)
    finalists = parse_finalists(ns.finalists)
    run_dir = Path(ns.run).expanduser()
    if not run_dir.is_dir():
        raise InvalidInput(f"{run_dir} is not a run folder")
    cases = Path(ns.cases).expanduser() if ns.cases else run_dir.resolve().parent
    as_of = ns.as_of or dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(as_of)
    except ValueError as exc:
        raise InvalidInput(f"--as-of must be YYYY-MM-DD, got {as_of!r}") from exc
    notes_path = Path(ns.notes).expanduser() if ns.notes else (run_dir / NOTES_FILE if (run_dir / NOTES_FILE).is_file() else None)
    notes_in = read_notes(notes_path)
    flags: list[dict] = []

    # 1. the gate, by gate.py's own function
    gate_in = gate_input(finalists, cases, ns.hurdle, ns.floor)
    try:
        gate_out = json.loads(json.dumps(_load(_HERE / "gate.py").run_gate(gate_in)))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InvalidInput(f"gate.py rejected the finalists: {exc}") from exc
    symbols = [s for s, _ in finalists]
    passed = [r["symbol"] for r in gate_out["results"] if r["verdict"] in PASSING]
    failed = [r["symbol"] for r in gate_out["results"] if r["verdict"] not in PASSING]

    # 2. picks and notes
    picks: dict[str, dict] = {}
    notes = [str(n) for n in notes_in.get("notes") or []]
    for symbol, entry in (notes_in.get("picks") or {}).items():
        sym = str(symbol).strip().upper()
        if sym in passed:
            picks[sym] = entry
            continue
        why = "did not pass the gate" if sym in failed else "is not a finalist"
        notes.append(f"A pick thesis was written for {sym}, which {why}; it was left off the page.")
        flags.append({"code": "PICK_NOTE_DROPPED", "message": f"the notes file's picks entry for {sym} was dropped: it {why}"})
    bare = [s for s in passed if not (picks.get(s) or {}).get("thesis")]
    if bare:
        flags.append({"code": "THESIS_MISSING", "message": f"no thesis in the notes file for {', '.join(bare)}; the page shows the figures alone and save-deep gets no --thesis"})

    # 3. industries, candidates, funnel
    industries: list[dict] = []
    for path in sorted((run_dir / "industries").glob("*.json")):
        data = _read(path)
        if not isinstance(data, list):
            flags.append({"code": "INDUSTRY_FILE_SKIPPED", "message": f"industries/{path.name} is not a JSON list of industry objects; it is not on the page"})
            continue
        industries += data
    pool = _read(run_dir / "pool.json")
    if not isinstance(pool, dict):
        pool = None
        flags.append({"code": "POOL_MISSING", "message": "no pool.json: the funnel leaves out the pool stages and no candidate is marked held"})
    held = {_match(r.get("ticker")): bool(r.get("held")) for r in (pool or {}).get("names") or [] if isinstance(r, dict)}
    candidates: list[dict] = []
    for path in sorted((run_dir / "cards").glob("*.json")):
        if path.name.endswith(".data.json"):
            continue
        card = _read(path)
        if not isinstance(card, dict):
            flags.append({"code": "CARD_SKIPPED", "message": f"cards/{path.name} is not a JSON object; it is not among the candidates"})
            continue
        ticker = str(card.get("ticker") or path.stem).strip().upper()
        candidates.append({**card, "ticker": card.get("ticker") or ticker, "held": held.get(_match(ticker), bool(card.get("held"))), "finalist": ticker in symbols})
    carded = {str(c["ticker"]).upper() for c in candidates}
    uncarded = [s for s in symbols if s not in carded]
    if uncarded:
        flags.append({"code": "FINALIST_WITHOUT_CARD", "message": f"no cards/<TICKER>.json for {', '.join(uncarded)}; the Candidates table leaves them out"})
    counts = (pool or {}).get("counts") or {}
    funnel = [{"stage": "Industries scanned", "count": len(industries)}]
    whole = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
    for stage, key in (("Screen survivors", "screen_survivors"), ("Merged pool", "merged")):
        if whole(counts.get(key)):
            funnel.append({"stage": stage, "count": counts[key]})
    # "passed" is the health screen's verdict; "kept" also holds the names it set aside or could not check.
    health = counts.get("health") if isinstance(counts.get("health"), dict) else None
    if health is None:  # a pool.json without the tally: the rows' own health, kept and dropped
        seen = [str(r.get("health")) for key in ("names", "dropped") for r in (pool or {}).get(key) or [] if isinstance(r, dict) and r.get("health")]
        health = {h: seen.count(h) for h in dict.fromkeys(seen)} or None
    if health and set(health) <= {"unchecked"}:
        notes.append("The health check did not run, so no company was tested on it: every name went to the quick reads unchecked.")
        flags.append({"code": "HEALTH_NOT_CHECKED", "message": "pool.json has every name as unchecked (the health screen failed); the funnel leaves out the Health check passed stage"})
    elif health:
        passed_health = health.get("passed", 0)
        funnel.append({"stage": "Health check passed", "count": passed_health if whole(passed_health) else 0})
    if whole(counts.get("kept")):
        funnel.append({"stage": "Kept for quick read", "count": counts["kept"]})
    funnel += [{"stage": "Quick reads", "count": len(candidates)}, {"stage": "Finalists", "count": len(symbols)}, {"stage": "Picks", "count": len(passed)}]

    case_of = {s: cases / f"deep-{s}" for s in symbols}
    line = searches_note(run_dir, list(case_of.values()), flags)
    if line:
        notes.append(line)

    pick = {"as_of": as_of, "profile": notes_in.get("profile"), "gate": gate_out, "funnel": funnel, "industries": industries,
            "candidates": candidates, "picks": picks, "missing_roles": list(notes_in.get("missing_roles") or []), "notes": notes}

    # 4. the page, by render_pick.py's own build (it validates pick.json); nothing is written before it accepts
    _, markup, info = _load(_HERE / "render_pick.py").build(pick)

    (run_dir / "gate.json").write_text(_dump(gate_in), encoding="utf-8")
    (run_dir / "gate.out.json").write_text(_dump(gate_out), encoding="utf-8")
    (run_dir / "pick.json").write_text(_dump(pick), encoding="utf-8")
    out = page.write(run_dir / "page.html", markup)

    url_of = dict(finalists)
    commands = []
    no_page = []
    for s in info["picks"]:
        thesis = (picks.get(s) or {}).get("thesis")
        words = [sys.executable, str(PICKS_SCRIPT), "save-deep", s, "--case", str(case_of[s])]
        words += ["--thesis", str(thesis)] if thesis else []
        commands.append(" ".join(shlex.quote(w) for w in [*words, "--source", url_of[s]]))
        if not (case_of[s] / "page.json").is_file():
            no_page.append(s)
    if no_page:
        flags.append({"code": "CASE_PAGE_MISSING", "message": f"deep-{', deep-'.join(no_page)} has no page.json, which save-deep --case reads; run render_deep.py --case there first, or save with --page"})
    return {"out": str(out), "pick": str(run_dir / "pick.json"), "gate": gate_out["counts"], "picks": info["picks"], "near_misses": info["near_misses"],
            "save_commands": commands, "flags": flags}


def _match(ticker: object) -> str:
    """A ticker as pool.py writes it (BRK-B), so a card written as BRK.B finds its pool row."""
    return str(ticker or "").strip().upper().replace(".", "-")


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
