#!/usr/bin/env python3
"""Usage: pick_prep.py --run DIR --profile value|growth [--held SYM,SYM] [--finalists 3|4|5]

The deep picker's mechanical first step: the run folder, a dated macro snapshot from FRED, the
preset screens and the search budget, in one call.

Makes ``DIR`` with ``context/``, ``screen/``, ``industries/`` and ``cards/``.

Macro. ``context/macro.json`` and ``context/macro.md`` (the run date on the first line, then one
dated line per series). Latest values: DGS10, DGS2, FEDFUNDS, BAMLC0A4CBBBEY, MORTGAGE30US,
UNRATE (percent), DCOILWTICO (dollars a barrel), DHHNGSP (dollars per million BTU). Change over
the year-earlier month: CPIAUCSL, RSAFS, IPMAN (for the newest month that has a reading a year
earlier; a newer month without one is named on the line). A series FRED does not return is left out of
both files, named in ``macro.missing`` and flagged ``MACRO_SERIES_UNAVAILABLE``.

Screens. ``--profile value`` runs the ``value`` and ``quality`` presets, ``growth`` runs
``garp``; both add ``smallcap``, the profile's first preset with ``--set min_revenue=1.5e8
--set min_market_cap=3e8``. Each is a ``screen.py`` subprocess whose whole output is written to
``screen/<name>.json``. They run strictly one after another, in that order (the macro fetch,
which is FRED only, runs beside them). The first fills the on-disk EDGAR frames cache every
preset reads, so the rest do not touch the SEC; and each prices up to 400 names from Yahoo,
which rate-limits two screens run at once (they came back ``PRICING_INCOMPLETE``).
``--held`` is passed to every screen, which marks
those names ``held``. A screen that fails writes no file and is flagged ``SCREEN_FAILED``; the
others are kept. A screen Yahoo rate-limited (its own ``PRICING_INCOMPLETE`` flag) is written but
flagged ``SCREEN_PRICING_INCOMPLETE``: its survivors were not put through the price stage, so
run again in a few minutes.

Budget. ``budget.py DIR init --plan picker-N`` (N = ``--finalists``, default 3). A run folder
that already has a budget keeps it (``BUDGET_KEPT``); a missing or failing ``budget.py`` is
flagged ``BUDGET_UNAVAILABLE`` and ``budget`` is null.

Output: {"run", "macro": {"as_of", "path", "lines": [the dated lines of macro.md],
"missing": [series]}, "screens": {name: {"survivors": count or null, "top": [first 15 tickers],
"flags": [codes], "path", "error"?}}, "budget": <budget.py output or null>,
"flags": [{"code", "message"}]}.
Exit codes: 0, 2 (bad argument), 4 (EDGAR_USER_AGENT is not set: nothing is created), 6.
stdin is unused.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import brokerage, edgar, fred, output  # noqa: E402
from second_opinion.errors import ConfigError, InvalidInput  # noqa: E402

SCREEN_SCRIPT = _HERE / "screen.py"
BUDGET_SCRIPT = _HERE.parents[1] / "valuation" / "scripts" / "budget.py"
FOLDERS = ("context", "screen", "industries", "cards")
PROFILES = {"value": ("value", "quality"), "growth": ("garp",)}
SMALLCAP = ("--set", "min_revenue=1.5e8", "--set", "min_market_cap=3e8")
# series -> (unit shown after the value, unit shown before it)
LATEST_SERIES = {
    "DGS10": ("%", ""), "DGS2": ("%", ""), "FEDFUNDS": ("%", ""), "BAMLC0A4CBBBEY": ("%", ""),
    "MORTGAGE30US": ("%", ""), "UNRATE": ("%", ""),
    "DCOILWTICO": (" a barrel", "$"), "DHHNGSP": (" per million BTU", "$"),
}
YOY_SERIES = ("CPIAUCSL", "RSAFS", "IPMAN")
YOY_OBSERVATIONS = 16  # monthly: the latest month and the same month a year earlier, with slack
YOY_LOOKBACK = 3  # newest observations tried for one that has a year-earlier reading
YOY_TOLERANCE_DAYS = 20
TOP = 15
SCREEN_TIMEOUT = 1500  # seconds; a cold frames cache is about 180 throttled EDGAR requests
BUDGET_TIMEOUT = 60


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"pick_prep.py: {message}")


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="pick_prep.py", add_help=False)
    p.add_argument("--run", required=True)
    p.add_argument("--profile", required=True, choices=sorted(PROFILES))
    p.add_argument("--held", action="append", metavar="SYM,SYM")
    p.add_argument("--finalists", type=int, default=3, choices=(3, 4, 5))
    return p


def _json_subprocess(cmd: list[str], timeout: int) -> tuple[int, dict]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603 — our own scripts
    except subprocess.TimeoutExpired:
        return 5, {"error": f"timed out after {timeout} s"}
    except OSError as exc:
        return 5, {"error": str(exc)}
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["no output"]
        return proc.returncode or 5, {"error": tail[0][:300]}
    return proc.returncode, data if isinstance(data, dict) else {"error": "output is not a JSON object"}


def run_screen(name: str, args: list[str]) -> tuple[int, dict]:
    """One ``screen.py`` run as its own process: ``(exit code, its JSON)``."""
    return _json_subprocess([sys.executable, str(SCREEN_SCRIPT), *args], SCREEN_TIMEOUT)


def run_budget(run_dir: Path, args: list[str]) -> tuple[int, dict] | None:
    """``budget.py DIR <args>``: ``(exit code, its JSON)``, or None when the script is not there."""
    if not BUDGET_SCRIPT.is_file():
        return None
    return _json_subprocess([sys.executable, str(BUDGET_SCRIPT), str(run_dir), *args], BUDGET_TIMEOUT)


def _number(v: float) -> str:
    return f"{v:,.2f}"


def _latest(series: str) -> dict:
    obs = fred.latest(series)
    suffix, prefix = LATEST_SERIES[series]
    name = fred.SERIES_NAMES.get(series, series)
    return {"series": series, "name": name, "kind": "latest", "date": obs["date"], "value": obs["value"],
            "unit": (prefix + suffix).strip() or None,
            "line": f"- {series} ({name}): {prefix}{_number(obs['value'])}{suffix}, observed {obs['date']}"}


def _yoy(series: str) -> dict:
    """Change over the year-earlier month for the newest observation that has one. FRED has
    holes (a month never published), so the latest month can lack its pair: the next newest
    is used and the line says which month was skipped."""
    rows = [(dt.date.fromisoformat(r["date"][:10]), r) for r in fred.observations(series, YOY_OBSERVATIONS)]
    for idx in range(len(rows) - 1, max(len(rows) - 1 - YOY_LOOKBACK, 0), -1):
        end, last = rows[idx]
        try:
            target = end.replace(year=end.year - 1)
        except ValueError:  # 29 February
            target = end - dt.timedelta(days=365)
        gap, prior = min(((abs((d - target).days), r) for d, r in rows[:idx]), key=lambda x: x[0], default=(None, None))
        if prior is None or gap > YOY_TOLERANCE_DAYS or not prior["value"]:
            continue
        change = last["value"] / prior["value"] - 1
        name = fred.SERIES_NAMES.get(series, series)
        skipped = [r["date"] for _, r in rows[idx + 1:]]
        note = f"; {', '.join(skipped)} has no reading a year earlier" if skipped else ""
        return {"series": series, "name": name, "kind": "yoy", "date": last["date"], "value": round(change, 4),
                "unit": "change over a year", "level": last["value"], "year_ago_date": prior["date"], "year_ago_level": prior["value"],
                "skipped": skipped,
                "line": f"- {series} ({name}): {change * 100:+.1f}% over the year to {last['date']} (against {prior['date']}{note})"}
    raise ValueError("no observation with a reading a year earlier")


def macro(today: dt.date) -> dict:
    """The macro snapshot: ``{"as_of", "series": [...], "missing": [...]}``; never raises for a series."""
    series, missing = [], []
    for sid, fetch in [(s, _latest) for s in LATEST_SERIES] + [(s, _yoy) for s in YOY_SERIES]:
        try:
            series.append(fetch(sid))
        except Exception:  # noqa: BLE001 — one series down must not sink the snapshot
            missing.append(sid)
    return {"as_of": today.isoformat(), "source": "FRED (fred.stlouisfed.org)", "series": series, "missing": missing}


def macro_markdown(snapshot: dict) -> str:
    lines = [f"# Macro snapshot as of {snapshot['as_of']}", "", "Source: FRED. Each line carries its own observation date.", ""]
    lines += [s["line"] for s in snapshot["series"]]
    return "\n".join(lines) + "\n"


def screen_plan(profile: str, held: list[str]) -> list[tuple[str, list[str]]]:
    presets = PROFILES[profile]
    extra = ["--held", ",".join(held)] if held else []
    plan = [(p, ["--preset", p, *extra]) for p in presets]
    plan.append(("smallcap", ["--preset", presets[0], *SMALLCAP, *extra]))
    return plan


def _screen(name: str, args: list[str], folder: Path) -> dict:
    try:
        rc, data = run_screen(name, args)
    except Exception as exc:  # noqa: BLE001 — a screen that fails is reported, not raised
        rc, data = 5, {"error": f"{exc.__class__.__name__}: {exc}"}
    path = folder / f"{name}.json"
    if rc != 0 or not isinstance(data.get("survivors"), list):
        return {"survivors": None, "top": [], "flags": ["SCREEN_FAILED"], "path": None,
                "error": str(data.get("error") or f"screen.py exited {rc}")}
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    tickers = [str(s["ticker"]) for s in data["survivors"] if isinstance(s, dict) and s.get("ticker")]
    return {"survivors": len(data["survivors"]), "top": tickers[:TOP], "path": str(path),
            "flags": [f["code"] for f in data.get("flags") or [] if isinstance(f, dict) and f.get("code")]}


def _budget(run_dir: Path, plan: str, flags: list[dict]) -> dict | None:
    try:
        res = run_budget(run_dir, ["init", "--plan", plan])
        if res is not None and res[0] == 2:  # a budget is already there: keep it and what it has used
            kept = run_budget(run_dir, [])
            if kept is not None and kept[0] == 0:
                flags.append({"code": "BUDGET_KEPT", "message": f"{run_dir} already has a budget; it was kept, not reset to {plan}"})
                return kept[1]
    except Exception as exc:  # noqa: BLE001
        res = (5, {"error": f"{exc.__class__.__name__}: {exc}"})
    if res is None:
        flags.append({"code": "BUDGET_UNAVAILABLE", "message": f"{BUDGET_SCRIPT} is not installed; no search budget was started"})
        return None
    if res[0] != 0:
        flags.append({"code": "BUDGET_UNAVAILABLE", "message": f"budget.py init --plan {plan} failed: {res[1].get('error') or f'exit {res[0]}'}"})
        return None
    return res[1]


def run(args: list[str], today: dt.date | None = None) -> dict:
    ns = parser().parse_args(args)
    held: list[str] = []
    for item in ns.held or []:
        for raw in item.split(","):
            if raw.strip():
                s = brokerage.validate_symbol(raw)
                if s not in held:
                    held.append(s)
    if edgar.user_agent_is_default():
        raise ConfigError("the deep picker needs SEC EDGAR: set EDGAR_USER_AGENT to 'app-name contact@email' in the plugin's .env",
                          code="EDGAR_NOT_CONFIGURED")
    today = today or dt.date.today()
    run_dir = Path(ns.run).expanduser().resolve()
    for sub in FOLDERS:
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    flags: list[dict] = []
    plan = screen_plan(ns.profile, held)
    screens: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=1) as ex:
        snapshot_job = ex.submit(macro, today)  # FRED only, beside the screens
        # One screen at a time: each prices up to 400 names from Yahoo eight at a time, and two
        # screens at once came back rate-limited (PRICING_INCOMPLETE). The first also fills the
        # EDGAR frames cache the others read.
        for name, screen_args in plan:
            screens[name] = _screen(name, screen_args, run_dir / "screen")
        snapshot = snapshot_job.result()

    (run_dir / "context" / "macro.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    md = run_dir / "context" / "macro.md"
    md.write_text(macro_markdown(snapshot))
    if snapshot["missing"]:
        flags.append({"code": "MACRO_SERIES_UNAVAILABLE", "message": f"FRED did not return {', '.join(snapshot['missing'])}; left out of macro.md"})
    for name, _ in plan:
        if "SCREEN_FAILED" in screens[name]["flags"]:
            flags.append({"code": "SCREEN_FAILED", "message": f"the {name} screen failed ({screens[name]['error']}); the other screens were kept"})
    thin = [name for name, _ in plan if "PRICING_INCOMPLETE" in screens[name]["flags"]]
    if thin:
        flags.append({"code": "SCREEN_PRICING_INCOMPLETE", "message": f"Yahoo rate-limited the {', '.join(thin)} screen{'s' if len(thin) > 1 else ''}: most names were not priced, so the survivors are not the preset's; wait a few minutes and run pick_prep.py again on the same folder"})
    budget = _budget(run_dir, f"picker-{ns.finalists}", flags)
    return {
        "run": str(run_dir),
        "macro": {"as_of": snapshot["as_of"], "path": str(md), "lines": [s["line"][2:] for s in snapshot["series"]], "missing": snapshot["missing"]},
        "screens": {name: screens[name] for name, _ in plan},
        "budget": budget,
        "flags": flags,
    }


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
