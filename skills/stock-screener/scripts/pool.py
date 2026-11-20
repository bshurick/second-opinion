#!/usr/bin/env python3
"""Usage: pool.py --run DIR [--held SYM,SYM] [--max 40]

The deep picker's merged candidate pool: every industry's prospects and every screen's survivors
in one deduplicated list, health-checked and split into quick-read batches. Writes
``DIR/pool.json`` and ``DIR/screen/health.json`` (screen.py's raw output).

Merge. Reads every ``industries/*.json`` that is a list of industry objects (the scanners' files;
anything else there is skipped and flagged) and every ``screen/*.json`` except ``health.json``.
A name enters as an industry's prospect, a theme's prospect (a growth run's theme scout writes
``context/themes.json``, ``{"as_of", "themes": [{"theme", "crowding", "prospects": [same shape as an
industry's], ...}]}``; a missing file is normal, a malformed one is skipped and flagged) or a
screen's survivor, whatever the industry's verdict.
A leader enters only when it is also a prospect or a survivor; a survivor that is some industry's
leader takes that industry's name, sector and verdict. Tickers are matched in one form, upper
case with a share-class dot written as a dash (a scanner's ``BRK.B`` and the screen's ``BRK-B``
are the same name, found both ways; ``--held BRK.B`` marks it), and the row carries that form
(``BRK-B``), which Yahoo, the SEC list and every later script accept. One row per ticker:

  {"ticker", "name", "origin": "industry"|"theme"|"screen"|"both", "held", "industry", "sector",
   "industry_verdict", "contrarian", "market_cap", "why": <the prospect's own line, unchanged>,
   "screens": [names of the screens it survived], "themes": [themes that named it], "leader": bool,
   "health", "failed_tests": [health criteria it failed]}

``origin`` is ``industry`` or ``theme`` for a name only a scan or only the theme scout found (an
industry's prospect stays ``industry`` when a theme also names it), ``screen`` for a screen
survivor alone, and ``both`` for a scan or theme name that a screen also found. ``themes`` lists
every theme that named the name, scan or not; a theme name no industry claims takes its ``why``
and ``market_cap`` from the theme.

``industry``, ``industry_verdict``, ``contrarian``, ``market_cap`` and ``why`` are null for a
screen name no scan covers (``sector`` is then Yahoo's, when the screen priced it). ``held`` is
true for a ``--held`` symbol or a survivor its screen marked held.

Trim. More than ``--max`` names (default 40) are cut to it, industry by industry: within each
industry (its scanned industry, else ``theme: <its first theme>``, else its sector) every ``both`` name comes first, then prospects
and screen survivors alternately, each in its own order (prospects -- industries' and themes' --
one list after another in turn, survivors one screen after another in turn by rank); the industries then take turns, one
name each, so a sector the screens favor cannot crowd out another's prospects. Never on the
verdict. The names cut are listed in ``trimmed`` and flagged ``POOL_TRIMMED``.

Health. ``screen.py --symbols <the pool> --preset health --no-price [--held ...]`` once (``health_growth``
when the run's ``run.json`` says ``growth``: ``growth.run_profile``, ``value`` without a ``run.json``), then
per name ``health`` is ``passed``, ``financial`` (a bank, lender or insurer the screen sets
aside), ``not_found`` (no SEC filer), ``incomplete`` (no four years of US-GAAP history),
``judge_in_quick_read`` (failed, but its sector is Financials, Utilities or Real Estate: the cash
and leverage tests misread an asset manager, broker, BDC, utility or REIT) or ``failed``. Only ``failed`` names leave the pool, into ``dropped``
with their tests. When the health screen itself fails every name stays, as ``unchecked``,
flagged ``HEALTH_CHECK_FAILED``.

Batches. The kept names five at a time for the quick readers, an industry's names together
(then names only a theme found, by their first theme, then names no scan or theme covers, by sector).

``pool.json``: {"as_of", "profile": "value"|"growth", "names": [kept rows], "dropped": [rows with health "failed"],
"trimmed": [tickers], "counts", "batches": [[tickers]]}. ``counts``: {"industries", "prospects",
"screen_survivors" (distinct), "candidates" (distinct names before the trim), "trimmed",
"merged" (names health-checked), "kept", "dropped", "held", "themes" (theme objects read),
"theme_prospects" (distinct), "origin": {"industry", "theme", "screen", "both"} and "health": {status: n} (both over the merged names)}.

Prints {"run", "profile", "pool": <path>, "counts", "batches", "dropped": [{"ticker", "failed_tests"}],
"flags": [{"code", "message"}]}. Other flags: PRICING_INCOMPLETE (a screen file carries
screen.py's flag of that name: Yahoo rate-limited it, so its survivors were not put through the
price stage; ``screens`` names them), INDUSTRY_FILE_SKIPPED, THEME_FILE_SKIPPED, SCREEN_FILE_SKIPPED (not JSON, or
not the expected shape), PROSPECT_SKIPPED (a prospect or survivor without a usable ticker).
Exit 2 on a bad argument, a run folder that does not exist, or nothing to merge (nothing is
written). stdin is unused.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

from second_opinion import brokerage, output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

import growth  # noqa: E402

SCREEN_SCRIPT = _HERE / "screen.py"
HEALTH_FILE = "health.json"
THEME_FILE = "context/themes.json"
HEALTH_TIMEOUT = 1500  # seconds; a cold frames cache is about 180 throttled EDGAR requests
DEFAULT_MAX = 40
BATCH = 5
FINANCIAL_SECTORS = {"financials", "financial services", "financial"}  # the scan's name and Yahoo's
# sectors whose capital spending and debt are the business model (a rate base, a property book):
# the health screen's cash and leverage tests misread them, as they misread financials
MISREAD_SECTORS = FINANCIAL_SECTORS | {"utilities", "real estate"}
HEALTH_ORDER = ("passed", "judge_in_quick_read", "financial", "not_found", "incomplete", "unchecked", "failed")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"pool.py: {message}")


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="pool.py", add_help=False)
    p.add_argument("--run", required=True)
    p.add_argument("--held", action="append", metavar="SYM,SYM")
    p.add_argument("--max", type=int, default=DEFAULT_MAX)
    return p


def run_health(symbols: list[str], held: list[str], preset: str = "health") -> tuple[int, dict]:
    """The health screen (``preset``) on a hand-picked list, as its own process: ``(exit code, its JSON)``."""
    cmd = [sys.executable, str(SCREEN_SCRIPT), "--symbols", ",".join(symbols), "--preset", preset, "--no-price"]
    if held:
        cmd += ["--held", ",".join(held)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=HEALTH_TIMEOUT)  # noqa: S603 — our own script
        data = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return 5, {"error": f"{exc.__class__.__name__}: {exc}"[:300]}
    return proc.returncode, data if isinstance(data, dict) else {"error": "output is not a JSON object"}


def canonical(symbol: str) -> str:
    """The form tickers are matched by: upper case, a share-class dot as a dash (BRK.B -> BRK-B),
    as the SEC ticker list and Yahoo write it. Same rule as ``second_opinion.pack.canonical_symbol``."""
    return brokerage.validate_symbol(symbol).replace(".", "-")


def _ticker(raw: Any) -> str | None:
    try:
        return canonical(raw) if isinstance(raw, str) else None
    except InvalidInput:
        return None


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _round_robin(queues: list[list[str]]) -> list[str]:
    """The first of each queue, then the second of each, and so on, without repeats."""
    out: list[str] = []
    for i in range(max((len(q) for q in queues), default=0)):
        for q in queues:
            if i < len(q) and q[i] not in out:
                out.append(q[i])
    return out


def merge(run_dir: Path, held: list[str], flags: list[dict]) -> tuple[dict[str, dict], list[list[str]], list[list[str]], dict]:
    """Every candidate by ticker, the prospect queue of each industry, the survivor queue of each
    screen, and the source counts."""
    rows: dict[str, dict] = {}
    leaders: dict[str, dict] = {}
    prospect_queues: list[list[str]] = []
    screen_queues: list[list[str]] = []
    skipped: list[str] = []
    industries = 0

    def row(ticker: str) -> dict:
        return rows.setdefault(ticker, {"ticker": ticker, "name": None, "origin": None, "held": ticker in held, "industry": None, "sector": None,
                                        "industry_verdict": None, "contrarian": None, "market_cap": None, "why": None, "screens": [],
                                        "themes": [], "leader": False, "health": None, "failed_tests": []})

    for path in sorted((run_dir / "industries").glob("*.json")):
        data = _read(path)
        if not isinstance(data, list) or not all(isinstance(i, dict) and i.get("industry") for i in data):
            flags.append({"code": "INDUSTRY_FILE_SKIPPED", "message": f"{path.name} is not a JSON list of industry objects; its prospects are not in the pool"})
            continue
        for ind in data:
            industries += 1
            for lead in ind.get("leaders") or []:
                t = _ticker(lead.get("ticker")) if isinstance(lead, dict) else None
                if t:
                    leaders.setdefault(t, ind)
            queue: list[str] = []
            for p in ind.get("prospects") or []:
                t = _ticker(p.get("ticker")) if isinstance(p, dict) else None
                if not t:
                    skipped.append(f"{ind['industry']}: {p.get('ticker') if isinstance(p, dict) else p!r}")
                    continue
                queue.append(t)
                if t in rows:  # a second industry naming the same company: the first keeps it
                    continue
                r = row(t)
                r.update(name=p.get("name"), origin="industry", industry=ind.get("industry"), sector=ind.get("sector"),
                         industry_verdict=ind.get("verdict"), contrarian=bool(ind.get("contrarian")), market_cap=p.get("market_cap"), why=p.get("why"))
            prospect_queues.append(queue)

    themes, theme_names = 0, set()
    theme_path = run_dir / THEME_FILE
    if theme_path.exists():
        data = _read(theme_path)
        objs = data.get("themes") if isinstance(data, dict) else None
        if not isinstance(objs, list) or not all(isinstance(t, dict) and t.get("theme") for t in objs):
            flags.append({"code": "THEME_FILE_SKIPPED", "message": f"{THEME_FILE} is not a JSON object with a list of themes; its prospects are not in the pool"})
            objs = []
        for th in objs:
            themes += 1
            queue = []
            for p in th.get("prospects") or []:
                t = _ticker(p.get("ticker")) if isinstance(p, dict) else None
                if not t:
                    skipped.append(f"theme {th['theme']}: {p.get('ticker') if isinstance(p, dict) else p!r}")
                    continue
                queue.append(t)
                theme_names.add(t)
                r = row(t)
                if th["theme"] not in r["themes"]:
                    r["themes"].append(th["theme"])
                if r["origin"] is None:  # a name no industry claims: the theme's line describes it
                    r.update(name=p.get("name"), origin="theme", market_cap=p.get("market_cap"), why=p.get("why"))
            prospect_queues.append(queue)

    limited: list[str] = []
    survivors: set[str] = set()
    for path in sorted((run_dir / "screen").glob("*.json")):
        if path.name == HEALTH_FILE:
            continue
        data = _read(path)
        if not isinstance(data, dict) or not isinstance(data.get("survivors"), list):
            flags.append({"code": "SCREEN_FILE_SKIPPED", "message": f"screen/{path.name} is not screen.py output; its survivors are not in the pool"})
            continue
        if any(isinstance(f, dict) and f.get("code") == "PRICING_INCOMPLETE" for f in data.get("flags") or []):
            limited.append(path.stem)
        queue = []
        for s in data["survivors"]:
            t = _ticker(s.get("ticker")) if isinstance(s, dict) else None
            if not t:
                skipped.append(f"{path.stem} screen: {s.get('name') if isinstance(s, dict) else s!r}")
                continue
            queue.append(t)
            survivors.add(t)
            r = row(t)
            r["origin"] = "both" if r["origin"] in ("industry", "theme", "both") else "screen"
            r["screens"].append(path.stem)
            r["name"] = r["name"] or s.get("name")
            r["held"] = r["held"] or bool(s.get("held"))
            r["sector"] = r["sector"] or (s.get("metrics") or {}).get("sector")
        screen_queues.append(queue)

    for t, r in rows.items():
        ind = leaders.get(t)
        if ind is not None:
            r["leader"] = True
            if r["industry"] is None:  # a screen name the scan knows as a leader
                r.update(industry=ind.get("industry"), sector=ind.get("sector") or r["sector"], industry_verdict=ind.get("verdict"), contrarian=bool(ind.get("contrarian")))
    if limited:
        flags.append({"code": "PRICING_INCOMPLETE", "screens": limited,
                      "message": f"Yahoo rate-limited the {', '.join(limited)} screen{'s' if len(limited) > 1 else ''}: the survivors were not put through the price stage, "
                                 "so they are not the preset's; wait a few minutes, run pick_prep.py again on this folder, then pool.py"})
    if skipped:
        flags.append({"code": "PROSPECT_SKIPPED", "message": f"left out for want of a usable ticker: {'; '.join(skipped[:10])}{' and more' if len(skipped) > 10 else ''}"})
    counts = {"industries": industries, "prospects": len({t for q in prospect_queues for t in q}), "screen_survivors": len(survivors),
              "themes": themes, "theme_prospects": len(theme_names)}
    return rows, prospect_queues, screen_queues, counts


def _industry_key(row: dict) -> str:
    """The group a name competes in when the pool is trimmed: its scanned industry, else its first
    theme, else its sector."""
    theme = f"theme: {row['themes'][0]}" if row.get("themes") else None
    return str(row.get("industry") or theme or row.get("sector") or "unclassified").strip().lower()


def trim(rows: dict[str, dict], prospect_queues: list[list[str]], screen_queues: list[list[str]], limit: int) -> tuple[list[str], list[str]]:
    """(kept tickers in priority order, tickers cut). Within each industry (``_industry_key``) the
    order is ``both`` names first, then prospects and screen survivors alternately by their order;
    the industries then take turns, one name each, in the order their first name appears, so no
    industry gets a second name before every industry has had its first."""
    order = [t for t in rows if rows[t]["origin"] == "both"]
    prospects = [t for t in _round_robin(prospect_queues) if rows[t]["origin"] in ("industry", "theme")]
    screened = [t for t in _round_robin(screen_queues) if rows[t]["origin"] == "screen"]
    for i in range(max(len(prospects), len(screened))):
        order += prospects[i:i + 1] + screened[i:i + 1]
    groups: dict[str, list[str]] = {}
    for t in order:
        groups.setdefault(_industry_key(rows[t]), []).append(t)
    order = _round_robin(list(groups.values()))
    return order[:limit], order[limit:]


def apply_health(names: list[dict], data: dict | None) -> None:
    def key(raw: Any) -> str:
        return str(raw).strip().upper().replace(".", "-")

    checked = {key(c.get("ticker")): c for c in (data or {}).get("checked") or [] if isinstance(c, dict)}
    not_found = {key(t) for t in (data or {}).get("not_found") or []}
    incomplete = {key(t) for t in (data or {}).get("incomplete") or []}
    for r in names:
        c = checked.get(r["ticker"])
        if data is None or (c is None and r["ticker"] not in not_found | incomplete):
            r["health"] = "unchecked"
        elif r["ticker"] in not_found:
            r["health"] = "not_found"
        elif c is None:
            r["health"] = "incomplete"
        elif c.get("passed"):
            r["health"] = "passed"
        elif c.get("financial"):
            r["health"] = "financial"
        else:
            r["failed_tests"] = [str(f) for f in c.get("failed") or []]
            r["health"] = "judge_in_quick_read" if str(r.get("sector") or "").strip().lower() in MISREAD_SECTORS else "failed"


def batches(names: list[dict]) -> list[list[str]]:
    groups: dict[tuple[int, str], list[str]] = {}
    for r in names:
        if r.get("industry"):
            key = (0, str(r["industry"]))
        elif r.get("themes"):
            key = (1, f"theme: {r['themes'][0]}")
        else:
            key = (2, str(r.get("sector") or ""))
        groups.setdefault(key, []).append(r["ticker"])
    flat = [t for key in sorted(groups, key=lambda k: k[0]) for t in groups[key]]  # stable: scanned industries first, each in first-seen order
    return [flat[i:i + BATCH] for i in range(0, len(flat), BATCH)]


def run(args: list[str]) -> dict:
    ns = parser().parse_args(args)
    if ns.max < 1:
        raise InvalidInput("--max must be at least 1")
    held: list[str] = []
    for item in ns.held or []:
        for raw in item.split(","):
            if raw.strip():
                s = canonical(raw)
                if s not in held:
                    held.append(s)
    run_dir = Path(ns.run).expanduser()
    if not run_dir.is_dir():
        raise InvalidInput(f"{run_dir} is not a run folder; run pick_prep.py --run first")
    profile = growth.run_profile(run_dir)
    flags: list[dict] = []
    rows, prospect_queues, screen_queues, counts = merge(run_dir, held, flags)
    if not rows:
        raise InvalidInput(f"nothing to merge: {run_dir} has no prospects in industries/*.json or {THEME_FILE} and no survivors in screen/*.json")
    kept, cut = trim(rows, prospect_queues, screen_queues, ns.max)
    if cut:
        flags.append({"code": "POOL_TRIMMED", "message": f"{len(rows)} candidates cut to {len(kept)} (--max {ns.max}): industries take turns, and within each, names found both ways first, then prospects and screen survivors alternately; the rest are in pool.json's trimmed"})
    names = [rows[t] for t in kept]

    try:
        rc, data = run_health(kept, held, preset="health_growth") if profile == "growth" else run_health(kept, held)
    except Exception as exc:  # noqa: BLE001 — a health screen that cannot run is a flag, not an exit
        rc, data = 5, {"error": f"{exc.__class__.__name__}: {exc}"}
    if rc != 0 or not isinstance(data.get("checked"), list):
        flags.append({"code": "HEALTH_CHECK_FAILED", "message": f"the health screen did not run ({data.get('error') or f'screen.py exited {rc}'}); every name is kept as unchecked: run pool.py again, or let the quick reads judge health"})
        data = None
    else:
        (run_dir / "screen").mkdir(exist_ok=True)
        (run_dir / "screen" / HEALTH_FILE).write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    apply_health(names, data)

    keep = [r for r in names if r["health"] != "failed"]
    dropped = [{k: r[k] for k in ("ticker", "name", "industry", "origin", "held", "health", "failed_tests")} for r in names if r["health"] == "failed"]
    counts.update(candidates=len(rows), trimmed=len(cut), merged=len(names), kept=len(keep), dropped=len(dropped), held=sum(1 for r in names if r["held"]),
                  origin={o: sum(1 for r in names if r["origin"] == o) for o in ("industry", "theme", "screen", "both")},
                  health={h: n for h in HEALTH_ORDER if (n := sum(1 for r in names if r["health"] == h))})
    result = {"as_of": dt.date.today().isoformat(), "profile": profile, "names": keep, "dropped": dropped, "trimmed": cut, "counts": counts, "batches": batches(keep)}
    dest = run_dir / "pool.json"
    dest.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return {"run": str(run_dir), "profile": profile, "pool": str(dest), "counts": counts, "batches": result["batches"],
            "dropped": [{"ticker": d["ticker"], "failed_tests": d["failed_tests"]} for d in dropped], "flags": flags}


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
