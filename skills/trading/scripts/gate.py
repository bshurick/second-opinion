#!/usr/bin/env python3
"""Usage: gate.py <symbol> <BUY|SELL> <qty> [--limit X | --price P] [--cooldown-days N] [--as-of YYYY-MM-DD]

Pre-trade discipline gate: checks an order against the written plan in the
trade-journal's ``journal.json`` and the realized losses in ``ledger.json``
(both under the plugin data dir; neither has to exist). It places nothing and
blocks nothing — it prints a decision the agent shows before preview-order.py.

Output: {decision, symbol, side, quantity, price, price_source, journal_id,
checks: [{rule, status, detail, ...}], reasons, recorded, as_of}.
``decision`` is GO, NO_GO (a written plan exists and the order violates it),
or REVIEW (something is missing: no plan, no size, no price, or a recent
loss). ``price`` is the limit price, ``--price``, or a live quote
(``price_source`` limit / given / quote); null when none is available.

BUY rules (checks ``written_plan``, ``stop_predefined``, ``size_within_plan``,
``risk_within_plan``, ``add_rule`` when the plan has one, ``recent_loss``):
an open journal entry for the symbol is the plan; none gives REVIEW, not
NO_GO. With a plan: no stop -> NO_GO, unless the entry carries a thesis-based
``invalidation`` text, which makes ``stop_predefined`` REVIEW ("thesis-based
invalidation recorded: ...") and skips ``risk_within_plan`` (no price stop to
size risk from); qty above the journaled size -> NO_GO (no size -> REVIEW);
actual risk qty x (price - stop) above planned size x (entry - stop) ->
NO_GO (no price -> REVIEW). Planned add (long entries with ``add_rule``
{price, qty}): when the order price is at or below the add price the
``add_rule`` check passes ("price within the planned add rule"), the allowed
size becomes size + add_rule.qty and the planned risk includes the add leg
qty x (add price - stop); above the add price the check is ``skip`` and the
plan is judged on the base size alone. A losing round trip whose sell date
is within --cooldown-days (calendar days, default 3) before as_of -> REVIEW;
no ledger -> skip.
SELL rules: never gated. With an open entry the ``exit_vs_plan`` check
annotates the exit (at_or_through_stop / at_or_through_target / between /
unknown), days held and whether that is within the horizon; without one the
``written_plan`` check is skipped.
When an entry matched, the decision is appended to that entry's ``gates``
list (``recorded`` true) so a later journal review can see it.
Without the trade-journal extra the gate checks nothing: the extra is on only when the trade-journal
skill is present AND the installer's record (installed.json in the data dir, else the plugin root)
turns it on; no record means off. After argument validation it prints ``decision: SKIP`` with the
reason "the trade-journal extra is not installed",
empty ``checks`` and ``recorded`` false, and never reads the journal or the ledger.
stdin is unused. Exit codes: 0, 2 (bad arguments), 5 (corrupt journal or
ledger), 6.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# The trade-journal skill is an optional extra; without it the gate has no plan to check and answers SKIP.
_JOURNAL_DIR = _HERE.parents[1] / "trade-journal"
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_JOURNAL_DIR / "scripts"))
sys.path.insert(0, str(_HERE.parents[1] / "trade-review" / "scripts"))

from second_opinion import brokerage, config, ledger, market, output  # noqa: E402
from second_opinion.brokers import router  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

DEFAULT_COOLDOWN_DAYS = 3


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"gate.py: {message}")


def _parse(argv: list[str]) -> argparse.Namespace:
    p = _Parser(prog="gate.py", add_help=False)
    p.add_argument("symbol")
    p.add_argument("side")
    p.add_argument("qty", type=float)
    p.add_argument("--limit", type=float, default=None)
    p.add_argument("--price", type=float, default=None)
    p.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    p.add_argument("--as-of", default=None)
    ns = p.parse_args(argv)
    ns.symbol = brokerage.validate_symbol(ns.symbol)
    ns.side = ns.side.upper()
    if ns.side not in ("BUY", "SELL"):
        raise InvalidInput("side must be BUY or SELL")
    if not ns.qty > 0:
        raise InvalidInput("qty must be above zero")
    if ns.cooldown_days < 0:
        raise InvalidInput("--cooldown-days must be zero or more")
    if ns.as_of is None:
        ns.as_of = date.today()
    else:
        try:
            ns.as_of = date.fromisoformat(ns.as_of)
        except ValueError as exc:
            raise InvalidInput("--as-of must be YYYY-MM-DD") from exc
    return ns


def _resolve_price(ns: argparse.Namespace) -> tuple[float | None, str | None]:
    if ns.limit is not None:
        return float(ns.limit), "limit"
    if ns.price is not None:
        return float(ns.price), "given"
    try:
        hub = router.try_load()
    except Exception:  # noqa: BLE001 — a broken broker config must not stop a checklist
        hub = None
    try:
        rows = market.quote([ns.symbol], hub=hub)
        price = rows[0].get("price") if rows else None
    except Exception:  # noqa: BLE001 — no quote is a REVIEW, not a failed run
        return None, None
    return (float(price), "quote") if price is not None else (None, None)


def _open_entry(book: dict, symbol: str) -> dict | None:
    matches = [e for e in book["entries"] if e.get("status") == "open" and str(e.get("symbol", "")).upper() == symbol]
    return matches[-1] if matches else None


def _check(rule: str, status: str, detail: str, **extra) -> dict:
    return {"rule": rule, "status": status, "detail": detail, **extra}


def _recent_losses(as_of: date, cooldown_days: int) -> tuple[str, str]:
    if not ledger.ledger_path().is_file():
        return "skip", "no ledger imported; recent losses unknown"
    rows = ledger.load()["transactions"]
    if not rows:
        return "skip", "ledger is empty; recent losses unknown"
    import review  # noqa: PLC0415 — trade-review's engine, only when a ledger exists

    trips = review.run_review({"as_of": as_of.isoformat(), "transactions": rows, "prices": {}})["round_trips"]
    recent = []
    for t in trips:
        pnl = t.get("realized_pnl")
        sold = t.get("sell_date")
        if pnl is None or sold is None or float(pnl) >= 0:
            continue
        days = (as_of - date.fromisoformat(str(sold))).days
        if 0 <= days <= cooldown_days:
            recent.append(f"{t.get('symbol')} sold {sold} for {float(pnl):.2f}")
    if recent:
        return "review", f"realized loss within the last {cooldown_days} days: " + "; ".join(recent)
    return "pass", f"no realized loss in the last {cooldown_days} days"


def _planned_add(entry: dict, price: float | None) -> dict | None:
    """{price, qty, active} for a long entry's add_rule; None when the plan has no usable add rule."""
    rule = entry.get("add_rule")
    if not isinstance(rule, dict) or rule.get("price") is None or str(entry.get("side") or "long").lower() != "long":
        return None
    add_price = float(rule["price"])
    qty = rule.get("qty")
    return {"price": add_price, "qty": None if qty is None else float(qty), "active": price is not None and price <= add_price}


def _gate_buy(ns: argparse.Namespace, entry: dict | None, price: float | None) -> list[dict]:
    checks: list[dict] = []
    if entry is None:
        checks.append(_check("written_plan", "review", f"no written plan for {ns.symbol}: no open journal entry"))
        for rule in ("stop_predefined", "size_within_plan", "risk_within_plan"):
            checks.append(_check(rule, "skip", "no plan to check against"))
    else:
        checks.append(_check("written_plan", "pass", f"open journal entry {entry['id']}: {entry.get('thesis', '')}"))
        stop = entry.get("stop")
        size = entry.get("size")
        entry_price = entry.get("entry_price")
        invalidation = entry.get("invalidation")
        thesis_only = stop is None and isinstance(invalidation, str) and bool(invalidation.strip())
        add_rule = _planned_add(entry, price)
        add_qty = add_rule["qty"] if add_rule and add_rule["active"] else None
        if thesis_only:
            checks.append(_check("stop_predefined", "review", f"thesis-based invalidation recorded: {invalidation.strip()[:120]}"))
        elif stop is None:
            checks.append(_check("stop_predefined", "fail", "the plan has no stop; amend the entry with --stop before buying"))
        else:
            checks.append(_check("stop_predefined", "pass", f"stop {float(stop):g}"))
        if size is None:
            checks.append(_check("size_within_plan", "review", "the plan has no size; amend the entry with --size or confirm the quantity"))
        else:
            allowed = float(size) + (add_qty or 0.0)
            label = f"a planned {float(size):g}" + (f" plus a planned add of {add_qty:g}" if add_qty else "")
            if ns.qty <= allowed:
                checks.append(_check("size_within_plan", "pass", f"{ns.qty:g} of {label}"))
            else:
                checks.append(_check("size_within_plan", "fail", f"{ns.qty:g} exceeds {label} ({allowed:g})"))
        if thesis_only:
            checks.append(_check("risk_within_plan", "skip", "no price stop (thesis-based invalidation)"))
        elif stop is None or size is None or entry_price is None:
            checks.append(_check("risk_within_plan", "skip", "planned risk needs a stop, a size and an entry price"))
        elif price is None:
            checks.append(_check("risk_within_plan", "review", "no price available to compute actual risk"))
        else:
            planned = float(size) * (float(entry_price) - float(stop))
            if add_qty:
                planned += add_qty * (add_rule["price"] - float(stop))
            planned = round(planned, 2)
            actual = round(ns.qty * (price - float(stop)), 2)
            status = "pass" if actual <= planned else "fail"
            checks.append(_check("risk_within_plan", status, f"actual risk {actual:.2f} vs planned {planned:.2f}", actual_risk=actual, planned_risk=planned))
        if add_rule is not None:
            for_qty = f"{add_rule['qty']:g}" if add_rule["qty"] is not None else "an unsized add"
            if add_rule["active"]:
                checks.append(_check("add_rule", "pass", f"price within the planned add rule (add at {add_rule['price']:g} for {for_qty})", add_price=add_rule["price"], add_qty=add_rule["qty"]))
            else:
                detail = "no price available to compare with the planned add" if price is None else f"price {price:g} is above the planned add price {add_rule['price']:g}"
                checks.append(_check("add_rule", "skip", detail, add_price=add_rule["price"], add_qty=add_rule["qty"]))
    status, detail = _recent_losses(ns.as_of, ns.cooldown_days)
    checks.append(_check("recent_loss", status, detail))
    return checks


def _gate_sell(ns: argparse.Namespace, entry: dict | None, price: float | None) -> list[dict]:
    if entry is None:
        return [_check("written_plan", "skip", f"{ns.symbol} is not journaled; sells are not gated")]
    side = str(entry.get("side") or "long")
    stop, target = entry.get("stop"), entry.get("target")
    if price is None:
        exit_kind = "unknown"
    elif stop is not None and ((side == "long" and price <= float(stop)) or (side == "short" and price >= float(stop))):
        exit_kind = "at_or_through_stop"
    elif target is not None and ((side == "long" and price >= float(target)) or (side == "short" and price <= float(target))):
        exit_kind = "at_or_through_target"
    else:
        exit_kind = "between"
    entered = date.fromisoformat(str(entry.get("date")))
    days_held = (ns.as_of - entered).days
    horizon = entry.get("horizon_days")
    within = None if horizon is None else days_held <= int(horizon)
    detail = f"exit {exit_kind} (stop {stop}, target {target}); held {days_held} days" + ("" if horizon is None else f" of a {horizon}-day horizon")
    return [
        _check("written_plan", "pass", f"open journal entry {entry['id']}"),
        _check("exit_vs_plan", "pass", detail, exit=exit_kind, days_held=days_held, within_horizon=within),
    ]


def _decide(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    if "fail" in statuses:
        return "NO_GO"
    if "review" in statuses:
        return "REVIEW"
    return "GO"


def _skip(ns: argparse.Namespace) -> dict:
    return {
        "decision": "SKIP", "symbol": ns.symbol, "side": ns.side, "quantity": ns.qty, "price": None, "price_source": None,
        "journal_id": None, "checks": [], "reasons": ["the trade-journal extra is not installed"], "recorded": False, "as_of": ns.as_of.isoformat(),
    }


def run(argv: list[str]) -> dict:
    ns = _parse(argv)
    # Opt-in: a marketplace install ships every skill, so the directory alone is not consent.
    if not _JOURNAL_DIR.is_dir() or not config.extra_enabled("trade-journal"):
        return _skip(ns)
    import journal as journal_mod  # noqa: PLC0415 — trade-journal's store, present only with that extra

    book = journal_mod.load_journal()
    entry = _open_entry(book, ns.symbol)
    price, price_source = _resolve_price(ns)
    checks = _gate_buy(ns, entry, price) if ns.side == "BUY" else _gate_sell(ns, entry, price)
    decision = _decide(checks)
    reasons = [c["detail"] for c in checks if c["status"] in ("fail", "review")]
    recorded = False
    if entry is not None:
        entry.setdefault("gates", []).append({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "as_of": ns.as_of.isoformat(),
            "side": ns.side, "quantity": ns.qty, "price": price, "decision": decision, "reasons": reasons,
        })
        journal_mod.save_journal(book)
        recorded = True
    return {
        "decision": decision, "symbol": ns.symbol, "side": ns.side, "quantity": ns.qty, "price": price, "price_source": price_source,
        "journal_id": entry["id"] if entry else None, "checks": checks, "reasons": reasons, "recorded": recorded, "as_of": ns.as_of.isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    return output.run(run, argv)


if __name__ == "__main__":
    sys.exit(main())
