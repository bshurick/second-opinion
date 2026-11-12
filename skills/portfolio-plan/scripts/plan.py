#!/usr/bin/env python3
"""Usage: plan.py status
       plan.py contribute AMOUNT [--sleeve PICKS]
       plan.py withdraw AMOUNT
       plan.py rebalance [--sleeve PICKS]
       plan.py open SYMBOL [--amount A]
       common: [--weighting equal|market_cap|valuation|size] [--include-light] [--split] [--over-ceiling]
               [--whole-shares] [--sell SYM[,SYM]] [--short-term R] [--long-term R]
               [--min-trade N] [--band-abs R] [--band-rel R] [--partial]

The one entry point of the portfolio plan. It runs the global plan (global_plan.py) and the picks
sleeve (sleeve_run.py) and adds no math of its own: every trade comes from one of them.

- ``status``: the sleeve mix, the global plan without its trades (null with no saved targets),
  ``targets_saved``, ``sleeve_target`` (the target in force, settings.glide_target) and ``glide``: {to, by,
  months_left, monthly} with ``monthly`` the gap to ``to`` spread over the whole months left
  (at least one), or null with no glide saved.
- ``contribute AMOUNT``: AMOUNT is cash already in the accounts. With ``--sleeve PICKS`` it is the
  sleeve's ``add``. Otherwise, when the sleeve has a target in force and sits below it, the sleeve
  takes min(AMOUNT, the room under its target, the trading-account cash) first through ``add``; the
  rest goes to the global plan with no sells, ``cash`` 0 and ``contribution`` the rest. With saved
  targets that is them without the sleeve keys, renormalized; with none, the core funds held, pro
  rata to their value. Picks and employer stock are left untouched by the global part, and its buys
  land in the accounts holding the cash the sleeve left (BUY_CASH_SHORT for what none covers).
- ``withdraw AMOUNT``: the global plan with --withdraw; with no saved targets the targets are today's
  weights of every holding and the cash, so the draw is pro rata (tax-advantaged accounts first).
- ``rebalance``: the global plan against the saved targets, or with ``--sleeve PICKS`` the sleeve's
  ``rebalance``. With no saved targets: {"no_targets": true, "derived_targets": today's weights}
  and no trades.
- ``open SYMBOL``: the sleeve's ``new-pick``.

Output: {"command", "amount"?, "sleeve": <sleeve_run output> | null, "global": <global_plan output>
| null, "trades": [sleeve trades, then global trades], "flags": [sleeve flags, then global flags, exact repeats dropped]}.
This is a plan; orders go through the portfolio-analysis trading protocol.

Exit codes: 0, 2 (bad input), 4 (ETRADE_REAUTH included), 5, 6.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import global_plan  # noqa: E402
import sleeve_run  # noqa: E402
from second_opinion import output, settings  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

_EPS = 0.005
_SLEEVE_FLAGS = ("weighting", "sell", "short_term", "long_term", "today")
_SLEEVE_SWITCHES = ("include_light", "over_ceiling", "whole_shares", "split", "partial")
_GLOBAL_FLAGS = ("short_term", "long_term", "min_trade", "band_abs", "band_rel")
_GLOBAL_SWITCHES = ("whole_shares", "partial")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"plan.py: {message}")


def _parser() -> _Parser:
    common = _Parser(add_help=False)
    common.add_argument("--weighting", choices=("equal", "market_cap", "valuation", "size"), default=None)
    common.add_argument("--sell", default=None)
    for name in ("--short-term", "--long-term", "--min-trade", "--band-abs", "--band-rel"):
        common.add_argument(name, type=float, default=None)
    for name in ("--include-light", "--over-ceiling", "--whole-shares", "--split", "--partial"):
        common.add_argument(name, action="store_true")
    common.add_argument("--today", help=argparse.SUPPRESS)
    p = _Parser(prog="plan.py", add_help=False)
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sub.add_parser("status", add_help=False, parents=[common])
    c = sub.add_parser("contribute", add_help=False, parents=[common])
    c.add_argument("amount", type=float)
    c.add_argument("--sleeve", default=None)
    sub.add_parser("withdraw", add_help=False, parents=[common]).add_argument("amount", type=float)
    r = sub.add_parser("rebalance", add_help=False, parents=[common])
    r.add_argument("--sleeve", default=None)
    o = sub.add_parser("open", add_help=False, parents=[common])
    o.add_argument("symbol")
    o.add_argument("--amount", type=float, default=None)
    return p


def _argv(ns: argparse.Namespace, flags: tuple[str, ...], switches: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for name in flags:
        value = getattr(ns, name)
        if value is not None:
            out += ["--" + name.replace("_", "-"), str(value)]
    out += ["--" + name.replace("_", "-") for name in switches if getattr(ns, name)]
    return out


def _sleeve_name(ns: argparse.Namespace) -> str | None:
    name = getattr(ns, "sleeve", None)
    if name is None:
        return None
    if name.upper() != "PICKS":
        raise InvalidInput(f"--sleeve takes PICKS (the picks sleeve), not {name}")
    return "PICKS"


def _amount(value: float) -> float:
    if not value > 0:
        raise InvalidInput("AMOUNT must be a positive number")
    return float(value)


def _envelope(command: str, sleeve: dict | None, glob: dict | None, **extra) -> dict:
    return {"command": command, **extra, "sleeve": sleeve, "global": glob,
            "trades": [*((sleeve or {}).get("trades") or []), *((glob or {}).get("trades") or [])],
            "flags": _unique([*((sleeve or {}).get("flags") or []), *((glob or {}).get("flags") or [])])}


def _unique(flags: list[dict]) -> list[dict]:
    """``flags`` without exact repeats (both engines state the same employer default)."""
    seen: list[dict] = []
    for f in flags:
        if f not in seen:
            seen.append(f)
    return seen


def _rest_targets(saved: dict) -> dict | None:
    """Saved targets without the sleeve keys, renormalized; None when nothing is left."""
    rest = {k: float(v) for k, v in saved.items() if k not in global_plan.SLEEVE_KEYS}
    total = sum(rest.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in rest.items()}


def _months_left(today: date, by: date) -> int:
    months = (by.year - today.year) * 12 + by.month - today.month - (1 if by.day < today.day else 0)
    return max(months, 0)


def _contribute(ns: argparse.Namespace, sc: list[str], gc: list[str]) -> dict:
    amount = _amount(ns.amount)
    if _sleeve_name(ns):
        return _envelope("contribute", sleeve_run.run(["add", str(amount), *sc]), None, amount=amount)
    mix = sleeve_run.run(["mix", *sc])["mix"]
    cash = float(mix["cash"]["value"])
    if amount > cash + _EPS:
        raise InvalidInput(f"only {cash:.2f} cash in the accounts; contribute counts money already deposited")
    sleeve = None
    if mix["ceiling_source"] == "target":
        take = min(amount, float(mix["room_under_ceiling"]), float(mix["trading_cash"]))
        if take > _EPS:
            sleeve = sleeve_run.run(["add", f"{take:.2f}", *sc])
    rest = round(amount - float((sleeve or {}).get("satellite_net") or 0.0), 2)
    glob = None
    if rest > _EPS:
        targets = _rest_targets(settings.get("plan.targets") or {})
        spent = {a["account"]: float((a.get("funding") or {}).get("cash") or 0.0) for a in (sleeve or {}).get("accounts") or []}
        overrides: dict = {"cash": 0.0, "contribution": rest, "freeze_sleeves": True, "buy_cash_spent": spent}
        overrides.update({"targets": targets} if targets else {"derive": "core"})
        glob = global_plan.run(["--no-sells", *gc], overrides=overrides)
    return _envelope("contribute", sleeve, glob, amount=amount)


def _status(ns: argparse.Namespace, sc: list[str], gc: list[str]) -> dict:
    sleeves = sleeve_run.run(["mix", *sc])
    doc = settings.load()
    saved = bool(doc["plan"].get("targets"))
    glob = None
    if saved:
        glob = global_plan.run(gc, overrides={"freeze_sleeves": True})
        for key in ("trades", "post_trade", "routing"):
            glob.pop(key, None)
    glide = ((doc["plan"].get("sleeves") or {}).get("PICKS") or {}).get("glide")
    glide_out = None
    if glide:
        today = date.fromisoformat(ns.today) if ns.today else date.today()
        months = _months_left(today, date.fromisoformat(glide["by"]))
        gap = max(0.0, float(glide["to"]) * sleeves["mix"]["total"]["value"] - sleeves["mix"]["satellite"]["value"])
        glide_out = {"to": glide["to"], "by": glide["by"], "months_left": months, "monthly": round(gap / max(months, 1), 2)}
    return {"command": "status", "sleeves": sleeves, "global": glob, "targets_saved": saved,
            "sleeve_target": settings.glide_target(doc, "PICKS"), "glide": glide_out}


def run(args: list[str]) -> dict:
    """One dispatcher command: parse ``args`` (the usage above) and run the engines; raises ScriptError."""
    ns = _parser().parse_args(args)
    if ns.today:
        try:
            date.fromisoformat(ns.today)
        except ValueError as exc:
            raise InvalidInput("--today must be YYYY-MM-DD") from exc
    sc = _argv(ns, _SLEEVE_FLAGS, _SLEEVE_SWITCHES)
    gc = _argv(ns, _GLOBAL_FLAGS, _GLOBAL_SWITCHES)
    if ns.command == "status":
        return _status(ns, sc, gc)
    if ns.command == "contribute":
        return _contribute(ns, sc, gc)
    if ns.command == "open":
        extra = ["--amount", str(ns.amount)] if ns.amount is not None else []
        return _envelope("open", sleeve_run.run(["new-pick", ns.symbol, *extra, *sc]), None)
    if ns.command == "withdraw":
        amount = _amount(ns.amount)
        saved = bool(settings.get("plan.targets"))
        glob = global_plan.run(["--withdraw", str(amount), *gc],
                               overrides={"freeze_sleeves": True} if saved else {"derive": "all"})
        return _envelope("withdraw", None, glob, amount=amount)
    if _sleeve_name(ns):
        return _envelope("rebalance", sleeve_run.run(["rebalance", *sc]), None)
    if not settings.get("plan.targets"):
        derived = global_plan.run(gc, overrides={"derive": "all"})
        return {"command": "rebalance", "no_targets": True, "derived_targets": derived["targets_used"],
                "sleeve": None, "global": None, "trades": [], "flags": []}
    return _envelope("rebalance", None, global_plan.run(gc, overrides={"freeze_sleeves": True}))


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
