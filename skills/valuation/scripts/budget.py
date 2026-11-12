#!/usr/bin/env python3
"""Usage: budget.py DIR init --plan NAME [--force]
       budget.py DIR add ROLE=N [ROLE=N ...]
       budget.py DIR

The web-search budget of one deep run, kept in ``DIR/budget.json`` (DIR is a deep valuation's case
folder or a deep picker's run folder). ``init`` writes the plan's caps with nothing used; ``add``
adds N searches to each named role's count (once per round, with what each subagent reported);
with no command it prints the status. Nothing is fetched.

Several coordinators may share one budget (the deep picker's valuations run two or three at a
time), so ``init`` and ``add`` hold an exclusive lock on ``DIR/.budget.json.lock`` across their
read, change and write, and the file is replaced in one step (a temporary file renamed over it):
adds made at the same moment are all counted, each prints the total as of its own write, and a
reader never sees a half-written file. The lock file stays in the folder; it is empty.

Plans and caps:

    valuation         forensic 1, claims 3, industry 6, segments 1, threads 8, threads_round2 4, red_team 2   (25)
    valuation-picker  the same with industry 4                                                             (23)
    picker-3          scanners 18, quick_reads 40, valuations 69                                           (127)
    picker-4          scanners 18, quick_reads 40, valuations 92                                           (150)
    picker-5          scanners 18, quick_reads 40, valuations 95                                           (153)

Every command prints::

    {"plan", "total", "caps": {role: cap}, "used": {role: n}, "used_total", "remaining",
     "threads_allowed", "round2_threads_allowed", "flags": [{"code", "message"}]}

``remaining`` is total less everything used (negative when overspent). A thread deep-dive may
spend 2 searches, and each thread round spends only its own role's cap, so the searches kept for
the second round and the red team stay unspent:

    threads_allowed         min(4, (caps.threads - used.threads) // 2, remaining // 2)
    round2_threads_allowed  min(2, (caps.threads_round2 - used.threads_round2) // 2, remaining // 2)

Neither goes below 0, and a plan without the role (the picker plans) prints 0. Flags:
ROLE_OVER_CAP (a role used more than its cap; the message names each), OVER_BUDGET (used more
than the total).

Exit 2: an unknown plan or role, ROLE=N that is not a whole number of 0 or more, ``init`` over an
existing budget.json without ``--force``, ``add`` or status with no budget.json, a budget.json that
is not this script's. A rejected command writes nothing.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

FILE = "budget.json"
LOCK_FILE = ".budget.json.lock"
_VALUATION = {"forensic": 1, "claims": 3, "industry": 6, "segments": 1, "threads": 8, "threads_round2": 4, "red_team": 2}
PLANS: dict[str, dict[str, int]] = {
    "valuation": _VALUATION,
    "valuation-picker": {**_VALUATION, "industry": 4},
    "picker-3": {"scanners": 18, "quick_reads": 40, "valuations": 69},
    "picker-4": {"scanners": 18, "quick_reads": 40, "valuations": 92},
    "picker-5": {"scanners": 18, "quick_reads": 40, "valuations": 95},
}
MAX_THREADS = 4
MAX_THREADS_ROUND2 = 2
SEARCHES_PER_THREAD = 2
_USAGE = "usage: budget.py DIR [init --plan NAME [--force] | add ROLE=N [ROLE=N ...]]"


def _read(folder: Path) -> dict:
    path = folder / FILE
    if not path.is_file():
        raise InvalidInput(f"no {FILE} in {folder}; run `budget.py DIR init --plan NAME` first")
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise InvalidInput(f"{path} is not JSON ({exc})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("caps"), dict) or not isinstance(data.get("used"), dict):
        raise InvalidInput(f"{path} is not a budget.py file (it needs plan, caps and used); `init --force` replaces it")
    return data


@contextlib.contextmanager
def _locked(folder: Path) -> Iterator[None]:
    """Hold the folder's budget lock: one read-change-write at a time across processes and threads."""
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / LOCK_FILE, "a+") as fh:
        try:
            import fcntl  # noqa: PLC0415 — POSIX only

            fcntl.flock(fh, fcntl.LOCK_EX)  # blocks until the holder is done; released when fh closes
            release = None
        except ImportError:  # Windows
            import msvcrt  # noqa: PLC0415

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

            def release() -> None:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        try:
            yield
        finally:
            if release is not None:
                release()


def _write(folder: Path, data: dict) -> None:
    """Replace budget.json in one step, so no reader sees part of it."""
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=f".{FILE}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(data, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, folder / FILE)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def status(data: dict) -> dict:
    """What every command prints, from the stored {"plan", "caps", "used"}."""
    caps = {k: int(v) for k, v in data["caps"].items()}
    used = {k: int(data["used"].get(k) or 0) for k in caps}
    total, used_total = sum(caps.values()), sum(used.values())
    remaining = total - used_total
    flags: list[dict] = []
    over = [f"{role} used {used[role]} of {caps[role]}" for role in caps if used[role] > caps[role]]
    if over:
        flags.append({"code": "ROLE_OVER_CAP", "message": "; ".join(over)})
    if used_total > total:
        flags.append({"code": "OVER_BUDGET", "message": f"{used_total} searches used against a budget of {total}"})

    def threads(role: str, most: int) -> int:
        """Thread deep-dives the role's own cap and the whole budget still pay for; 0 for a plan without the role."""
        left = caps.get(role, 0) - used.get(role, 0)
        return max(0, min(most, left // SEARCHES_PER_THREAD, remaining // SEARCHES_PER_THREAD))

    return {"plan": data.get("plan"), "total": total, "caps": caps, "used": used, "used_total": used_total, "remaining": remaining,
            "threads_allowed": threads("threads", MAX_THREADS), "round2_threads_allowed": threads("threads_round2", MAX_THREADS_ROUND2), "flags": flags}


def init(folder: Path, plan: str, force: bool = False) -> dict:
    if plan not in PLANS:
        raise InvalidInput(f"unknown plan {plan!r}; one of {', '.join(PLANS)}")
    with _locked(folder):
        if (folder / FILE).exists() and not force:
            raise InvalidInput(f"{folder / FILE} already exists; pass --force to start it again with nothing used")
        data = {"plan": plan, "caps": dict(PLANS[plan]), "used": {role: 0 for role in PLANS[plan]}}
        _write(folder, data)
    return status(data)


def add(folder: Path, pairs: list[str]) -> dict:
    if not (folder / FILE).is_file():  # before the lock, which would create the folder
        _read(folder)
    with _locked(folder):  # read, change and write as one step: a second add waits and then sees this one
        data = _read(folder)
        if not pairs:
            raise InvalidInput(f"add needs at least one ROLE=N ({_USAGE})")
        amounts: dict[str, int] = {}
        for pair in pairs:
            role, sep, raw = pair.partition("=")
            role = role.strip()
            if not sep or not raw.strip().isdigit():
                raise InvalidInput(f"{pair!r} is not ROLE=N with N a whole number of 0 or more")
            if role not in data["caps"]:
                raise InvalidInput(f"unknown role {role!r} for plan {data.get('plan')}; one of {', '.join(data['caps'])}")
            amounts[role] = amounts.get(role, 0) + int(raw)
        for role, n in amounts.items():
            data["used"][role] = int(data["used"].get(role) or 0) + n
        _write(folder, data)
    return status(data)


def show(folder: Path) -> dict:
    return status(_read(folder))


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        if not args or args[0].startswith("-"):
            raise InvalidInput(_USAGE)
        folder, rest = Path(args[0]).expanduser(), args[1:]
        if not rest:
            return show(folder)
        if rest[0] == "add":
            return add(folder, rest[1:])
        if rest[0] == "init":
            opts = rest[1:]
            force = "--force" in opts
            opts = [o for o in opts if o != "--force"]
            if len(opts) != 2 or opts[0] != "--plan":
                raise InvalidInput(f"init needs --plan NAME ({_USAGE})")
            return init(folder, opts[1], force)
        raise InvalidInput(f"unknown command {rest[0]!r} ({_USAGE})")

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
