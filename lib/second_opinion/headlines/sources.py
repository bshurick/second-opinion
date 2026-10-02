"""The brief's sources: which skill scripts run, when they are skipped, and the parallel runner.

Each :class:`Source` names a skill directory, a readiness check (a skip reason or None), a setup
hint, whether it touches a broker (then ``--partial`` is appended when the snapshot ran partial), a
``commands(ctx)`` builder returning ``(label, script, args)`` triples, and the extractor module under
``second_opinion.headlines`` whose ``extract(results, ctx)`` turns ``{label: json}`` into headlines.
:func:`run_all` runs every source's commands in a thread pool and never raises: a missing skill,
an unmet prerequisite, a timeout, a non-zero exit, bad JSON or an extractor bug all become a
coverage row. ``timeout`` is a deadline per source, not per command: a multi-command source (EDGAR,
market, journal, spending) spends the remaining time on each successive command and skips whatever
is left once the deadline passes, instead of getting ``timeout`` seconds for every command.
``run_all`` also stashes each source's raw ``{label: json}`` results under ``ctx["results"][source.name]``.

:func:`enrich` runs after ``run_all``, sequentially and never raising, and fills in ``answer`` on a
few headlines that need a cross-source lookup or one extra script call: EX_DIVIDEND from the
dividends source's own results already sitting in ``ctx["results"]`` (no call), EARNINGS from one
``options/scripts/chain.py`` call, and FILING (10-Q/10-K only) from one
``fundamental-research/scripts/filing.py --diff`` call. It caps itself at ``max_calls`` subprocess
calls per brief, skips a call outright when the skill it needs isn't installed, and treats
``timeout`` as one deadline for the whole phase (each call gets whatever of it remains, and once it
passes, later candidates are skipped rather than called).
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from second_opinion import config
from second_opinion import headlines as H

Runner = Callable[[list[str], float], tuple[int, str, str]]
Ready = Callable[[dict], Optional[str]]
Commands = Callable[[dict], list[tuple[str, str, list[str]]]]

NOT_INSTALLED_HINT = "install it with the setup skill"


@dataclass(frozen=True)
class Source:
    name: str
    skill: str
    module: str
    ready: Ready
    hint: str
    broker: bool
    commands: Commands


def needs_file(filename: str, reason: str) -> Ready:
    return lambda ctx: None if (Path(ctx["data_dir"]) / filename).is_file() else reason


def needs_entries(filename: str, field: str, reason: str) -> Ready:
    def check(ctx: dict) -> Optional[str]:
        path = Path(ctx["data_dir"]) / filename
        if not path.is_file():
            return reason
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return f"{filename} is not valid JSON"
        return None if isinstance(data, dict) and data.get(field) else reason

    return check


def needs_env(var: str, reason: str) -> Ready:
    return lambda ctx: None if config.env_value(var) else reason


def _no_check(ctx: dict) -> Optional[str]:
    return None


def _single(script: str, args: list[str]) -> Commands:
    return lambda ctx: [("main", script, list(args))]


EDGAR_MAX_SYMBOLS = 12


def _edgar_commands(ctx: dict) -> list[tuple[str, str, list[str]]]:
    symbols = (ctx.get("symbols") or [])[:EDGAR_MAX_SYMBOLS]
    return [(sym, "scripts/edgar.py", [sym]) for sym in symbols]


SOURCES: list[Source] = [
    Source("watchlist", "watchlist", "watchlist", needs_entries("watchlist.json", "watchlist", "the watchlist is empty"),
           "add symbols with the watchlist skill", False, _single("scripts/watchlist.py", ["check", "--events"])),
    Source("market", "market-analysis", "market", _no_check, "", False,
           lambda ctx: [("indices", "scripts/indices.py", []), ("flows", "scripts/flows.py", ["--cot", "--cash"])]),
    Source("events", "portfolio-snapshot", "events", _no_check, "", False, lambda ctx: []),
    Source("edgar", "fundamental-research", "edgar", needs_env("EDGAR_USER_AGENT", "EDGAR_USER_AGENT is not set"),
           "set EDGAR_USER_AGENT in .env", False, _edgar_commands),
    Source("rebalancing", "rebalancing", "rebalancing", needs_file("targets.json", "no targets.json"),
           "save targets with the rebalancing skill", True, _single("scripts/plan.py", ["--only-if-breached"])),
    Source("tax", "tax-aware", "tax", needs_entries("ledger.json", "transactions", "the ledger is empty"),
           "import statements with the statement-import skill", False, _single("scripts/tax-report.py", [])),
    Source("dividends", "dividend-income", "dividends", _no_check, "", True, _single("scripts/dividends.py", ["--yield-context"])),
    Source("risk", "risk-analysis", "risk", _no_check, "", True, _single("scripts/stress.py", [])),
    Source("journal", "trade-journal", "journal", needs_entries("journal.json", "entries", "the journal is empty"),
           "journal a trade with the trade-journal skill", False,
           lambda ctx: [("review", "scripts/journal.py", ["review"]), ("open", "scripts/journal.py", ["list", "--status", "open"])]),
    Source("debt", "debt-tracker", "debt", needs_file("statements.json", "no statements.json"),
           "record a statement with the debt-tracker skill", False, _single("scripts/debts.py", [])),
    Source("spending", "spending", "spending", needs_entries("spending.json", "transactions", "no spending imported"),
           "import a card export with the spending skill", False,
           lambda ctx: [("changes", "scripts/spend.py", ["changes"]), ("recurring", "scripts/spend.py", ["recurring"])]),
    Source("ledger", "statement-import", "ledger", needs_entries("ledger.json", "transactions", "the ledger is empty"),
           "import statements with the statement-import skill", False, _single("scripts/ledger.py", ["--summary"])),
]
SOURCE_ORDER = [s.skill for s in SOURCES]


def subprocess_runner(argv: list[str], timeout: float) -> tuple[int, str, str]:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=os.environ.copy())
    return p.returncode, p.stdout, p.stderr


def _reason_from(rc: int, out: str, err: str) -> str:
    try:
        data = json.loads(out)
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except ValueError:
        pass
    lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
    return lines[-1] if lines else f"exit {rc}"


def _run_command(source: Source, label: str, script: str, args: list[str], ctx: dict, runner: Runner, timeout: float) -> tuple[Optional[dict], Optional[str]]:
    path = Path(ctx["plugin_root"]) / "skills" / source.skill / script
    argv = [ctx["python"], str(path), *args]
    if source.broker and ctx.get("partial"):
        argv.append("--partial")
    try:
        rc, out, err = runner(argv, timeout)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:g}s"
    except Exception as exc:  # noqa: BLE001 — a runner crash is a failed row, never a failed brief
        return None, f"{exc.__class__.__name__}: {exc}"
    if rc != 0:
        return None, _reason_from(rc, out, err)
    try:
        data = json.loads(out)
    except ValueError:
        return None, "script printed no JSON"
    if not isinstance(data, dict):
        return None, "script printed no JSON object"
    return data, None


def _valid_headline(h: object) -> bool:
    return (
        isinstance(h, dict)
        and isinstance(h.get("key"), str)
        and h.get("severity") in H.SEVERITIES
        and bool(h.get("skill"))
    )


def _split_valid(headlines: list) -> tuple[list[dict], list]:
    valid = [h for h in headlines if _valid_headline(h)]
    malformed = [h for h in headlines if not _valid_headline(h)]
    return valid, malformed


def _run_source(source: Source, ctx: dict, runner: Runner, timeout: float) -> tuple[list[dict], dict]:
    started = time.monotonic()
    row = {"skill": source.skill, "script": "", "status": "ok", "reason": "",
           "hint": "", "seconds": 0.0, "headlines": 0}
    try:
        commands = source.commands(ctx)
        row["script"] = commands[0][1] if commands else ""
        if not (Path(ctx["plugin_root"]) / "skills" / source.skill).is_dir():
            return [], {**row, "status": "skipped", "reason": "skill not installed", "hint": NOT_INSTALLED_HINT}
        why = source.ready(ctx)
        if why:
            return [], {**row, "status": "skipped", "reason": why, "hint": source.hint}
        results: dict[str, dict] = {}
        failures: list[str] = []
        deadline = started + timeout
        for label, script, args in commands:
            now = time.monotonic()
            if now >= deadline:
                err = f"skipped: source deadline of {timeout:g}s reached"
                failures.append(f"{label}: {err}" if len(commands) > 1 else err)
                continue
            data, err = _run_command(source, label, script, args, ctx, runner, max(1.0, deadline - now))
            if data is None:
                failures.append(f"{label}: {err}" if len(commands) > 1 else str(err))
            else:
                results[label] = data
        if isinstance(ctx.get("results"), dict):
            ctx["results"][source.name] = results
        found: list[dict] = []
        if results or not commands:
            try:
                mod = importlib.import_module(f"second_opinion.headlines.{source.module}")
                extracted = list(mod.extract(results, ctx))
            except Exception as exc:  # noqa: BLE001 — an extractor bug is a failed row, never a failed brief
                failures.append(f"{exc.__class__.__name__}: {exc}")
                extracted = []
            valid, malformed = _split_valid(extracted)
            if malformed:
                failures.append("extractor returned a malformed headline")
            found = H.cap(valid)
        row["seconds"] = round(time.monotonic() - started, 1)
        row["headlines"] = len(found)
        if failures:
            row["status"] = "failed"
            row["reason"] = "; ".join(failures)
        elif source.name == "edgar" and len(ctx.get("symbols") or []) > EDGAR_MAX_SYMBOLS:
            row["reason"] = f"only the {EDGAR_MAX_SYMBOLS} largest single stocks were checked"
        return found, row
    except Exception as exc:  # noqa: BLE001 — nothing about one broken source may fail the whole brief
        return [], {**row, "seconds": round(time.monotonic() - started, 1), "status": "failed",
                    "reason": f"{exc.__class__.__name__}: {exc}"}


def run_all(ctx: dict, *, runner: Optional[Runner] = None, timeout: float = 90.0, workers: int = 6,
            sources: Optional[list[Source]] = None) -> tuple[list[dict], list[dict]]:
    """Run every source; return ``(headlines, coverage)`` with headlines capped, diffed and ordered."""
    runner = runner or subprocess_runner
    todo = SOURCES if sources is None else sources
    ctx["results"] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        outcomes = list(pool.map(lambda s: _run_source(s, ctx, runner, timeout), todo))
    headlines = [h for found, _ in outcomes for h in found]
    coverage = [row for _, row in outcomes]
    previous = ctx.get("previous") or {}
    try:
        headlines = H.apply_status(headlines, set(previous.get("keys") or []))
        headlines = H.order(headlines, [s.skill for s in todo])
    except Exception:  # noqa: BLE001 — every headline is validated per-source, but stay defensive
        pass
    return headlines, coverage


def _skill_dir_exists(ctx: dict, skill: str) -> bool:
    return (Path(ctx["plugin_root"]) / "skills" / skill).is_dir()


def _run_extra(ctx: dict, runner: Runner, timeout: float, skill: str, script: str,
                args: list[str]) -> tuple[Optional[dict], Optional[int]]:
    """Run one extra (non-source) script call; ``(None, None)`` on any runner failure, never raises."""
    path = Path(ctx["plugin_root"]) / "skills" / skill / script
    argv = [ctx["python"], str(path), *args]
    try:
        rc, out, _err = runner(argv, timeout)
    except Exception:  # noqa: BLE001 — a bad enrichment call must never fail the brief
        return None, None
    try:
        data = json.loads(out)
    except (ValueError, TypeError):
        data = None
    return (data if isinstance(data, dict) else None), rc


def _ex_dividend_answer(headline: dict, ctx: dict) -> str:
    sym = headline.get("symbol")
    if not sym:
        return ""
    res = ((ctx.get("results") or {}).get("dividends") or {}).get("main") or {}
    row = next((p for p in res.get("positions") or []
                if isinstance(p, dict) and str(p.get("symbol") or "").upper() == sym), None)
    if not row:
        return ""
    amount = row.get("next_ex_amount_est")
    if amount is None:
        return ""
    return f"About {H.money(amount)} for your {row.get('units'):g} shares (last ${row.get('last_dividend'):,.4f} per share)"


def _filing_form(key: str) -> str:
    """The filing form ('10-Q', '10-K', '8-K', ...) that ``key``'s discriminator starts with."""
    parts = key.split(":", 3)
    return parts[3].split(":", 1)[0] if len(parts) == 4 else ""


def _enrich_earnings(headline: dict, sym: str, ctx: dict, runner: Runner, timeout: float) -> None:
    data, rc = _run_extra(ctx, runner, timeout, "options", "scripts/chain.py", [sym, "--no-history"])
    if rc == 2:
        error = str((data or {}).get("error") or "")
        if "no listed options" in error.lower():
            headline["answer"] = "No listed options to price the move"
    elif rc == 0 and data is not None:
        headline["answer"] = (f"Options price a ±{H.money(data['expected_move_1sd'])} "
                              f"(±{data['expected_move_pct']:.1%}) move by {data['expiry']} "
                              f"(ATM IV {data['atm_iv']:.0%})")


def _enrich_filing(headline: dict, sym: str, form: str, ctx: dict, runner: Runner, timeout: float) -> None:
    data, rc = _run_extra(ctx, runner, timeout, "fundamental-research", "scripts/filing.py",
                           [sym, "--form", form, "--item", "1A", "--diff"])
    if rc == 2:
        headline["answer"] = f"No prior {form} risk factors to compare"
    elif rc == 0 and data is not None:
        headline["answer"] = (f"Risk factors vs the prior {form}: {data['added_count']} sentences added, "
                              f"{data['removed_count']} removed, similarity {data['similarity']:.0%}")


def enrich(headlines: list[dict], ctx: dict, *, runner: Optional[Runner] = None, timeout: float = 90.0,
           max_calls: int = 6) -> list[dict]:
    """Fill in ``answer`` for EX_DIVIDEND, EARNINGS and FILING (10-Q/10-K) headlines, mutating and
    returning ``headlines`` unchanged in every other way. Runs sequentially, in headline order, after
    ``run_all``. EX_DIVIDEND needs no call; EARNINGS and FILING each cost one subprocess call, capped
    at ``max_calls`` total. ``timeout`` is a deadline for the whole phase, not per call: it is taken
    once at entry and each call gets whatever is left of it (at least 1s), so once the deadline has
    passed, remaining candidates are skipped rather than each getting a fresh ``timeout``. Never
    raises, and never touches flags or coverage: any failure (missing skill, non-zero exit other than
    the documented "nothing to compare" case, timeout, bad JSON, a runner exception, the phase
    deadline passing) just leaves the answer exactly as the extractor set it.
    """
    runner = runner or subprocess_runner
    deadline = time.monotonic() + timeout
    calls_made = 0
    for headline in headlines:
        try:
            skill, code = headline.get("skill"), headline.get("code")
            if skill == "portfolio-snapshot" and code == "EX_DIVIDEND":
                answer = _ex_dividend_answer(headline, ctx)
                if answer:
                    headline["answer"] = answer
                continue
            if calls_made >= max_calls:
                continue
            now = time.monotonic()
            if now >= deadline:
                continue
            call_timeout = max(1.0, deadline - now)
            sym = headline.get("symbol")
            if skill == "portfolio-snapshot" and code == "EARNINGS":
                if not sym or not _skill_dir_exists(ctx, "options"):
                    continue
                calls_made += 1
                _enrich_earnings(headline, sym, ctx, runner, call_timeout)
            elif skill == "fundamental-research" and code == "FILING":
                form = _filing_form(str(headline.get("key") or ""))
                if form not in ("10-Q", "10-K") or not sym or not _skill_dir_exists(ctx, "fundamental-research"):
                    continue
                calls_made += 1
                _enrich_filing(headline, sym, form, ctx, runner, call_timeout)
        except Exception:  # noqa: BLE001 — one broken headline may never break the brief
            continue
    return headlines
