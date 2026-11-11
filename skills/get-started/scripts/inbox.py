#!/usr/bin/env python3
"""Usage: inbox.py

The session inbox: plain text for the SessionStart hook, at most six lines after the header
``Second Opinion, N things:``, each a thing that needs attention and, in double quotes, the
sentence that handles it. Nothing to report prints nothing. No network, always exit 0.

Sources, in this order, each skipped when missing or unreadable:

- the portfolio snapshot's last full read (``portfolio-last-check.json``, its ``arrivals``): cash
  that arrived since an earlier read ("put the new cash to work"), then vested employer shares
  ("my RSUs vested");
- the stock-screener pick store (``picks.summary_data``): picks due for a re-check and how many
  wait for a 10-Q, or light picks needing a deep valuation at deep depth ("re-check my picks");
- the watchlist's last stored check (``watchlist-last-check.json``): its new alerts ("what
  happened to SYM" for one, "show my watchlist alerts" for several).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import config  # noqa: E402

LIMIT = 6
PICKS_SCRIPT = _HERE.parents[1] / "stock-screener" / "scripts" / "picks.py"


def _read(name: str) -> dict | None:
    try:
        data = json.loads((config.data_dir() / name).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _day(iso: str) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{d:%b} {d.day}"


def _money(v: float) -> str:
    return f"${v:,.0f}"


def _units(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.4f}".rstrip("0")


def _arrival_lines() -> list[str]:
    rec = _read("portfolio-last-check.json") or {}
    arrivals = [a for a in rec.get("arrivals") or [] if isinstance(a, dict)]
    out = []
    cash = [a for a in arrivals if a.get("kind") == "cash" and isinstance(a.get("amount"), (int, float))]
    if cash:
        parts = [f"{_money(a['amount'])} arrived in {a.get('name') or a.get('account')} since {_day(a.get('since'))}" if i == 0
                 else f"{_money(a['amount'])} in {a.get('name') or a.get('account')} since {_day(a.get('since'))}"
                 for i, a in enumerate(cash)]
        out.append(f"- Cash: {' and '.join(parts)}.  \"put the new cash to work\"")
    vests = [a for a in arrivals if a.get("kind") == "vest" and isinstance(a.get("units"), (int, float))]
    if vests:
        parts = [f"{_units(a['units'])} {a.get('symbol')} arrived in {a.get('name') or a.get('account')} since {_day(a.get('since'))}"
                 for a in vests]
        out.append(f"- Vest: {' and '.join(parts)}.  \"my RSUs vested\"")
    return out


def _picks_module():
    if not PICKS_SCRIPT.is_file():
        return None
    if str(PICKS_SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(PICKS_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("inbox_picks", PICKS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _picks_lines(today: date) -> list[str]:
    try:
        mod = _picks_module()
        data = mod.summary_data(today) if mod else None
    except Exception:  # noqa: BLE001 - the inbox never fails the session
        return []
    if not data:
        return []
    out = []
    due = data["due"]
    if due:
        waiting = sum(1 for d in due if d.get("awaiting_filing"))
        tail = f" ({waiting} awaiting a 10-Q)" if waiting == 1 else f" ({waiting} awaiting 10-Qs)" if waiting else ""
        out.append(f"- Picks: {len(due)} of {data['n']} due for a re-check{tail}.  \"re-check my picks\"")
    needs = data.get("needs_deep_valuation") or []
    if needs:
        noun = "light pick needs" if len(needs) == 1 else "light picks need"
        out.append(f"- Picks: {len(needs)} {noun} a deep valuation ({', '.join(needs)}).  \"re-check my picks\"")
    return out


def _watchlist_lines() -> list[str]:
    saved = _read("watchlist-last-check.json")
    if not saved:
        return []
    new = [t for t in saved.get("triggered") or [] if isinstance(t, dict) and t.get("state") == "new"]
    if not new:
        return []
    when = f", as of {_day(saved.get('as_of'))}" if saved.get("as_of") else ""
    if len(new) == 1:
        sym = new[0].get("symbol")
        return [f"- Watchlist: {new[0].get('message') or sym}{when}.  \"what happened to {sym}\""]
    names = ", ".join(str(t.get("symbol")) for t in new)
    return [f"- Watchlist: {len(new)} new alerts ({names}){when}.  \"show my watchlist alerts\""]


def lines(today: date | None = None, limit: int = LIMIT) -> list[str]:
    """The inbox as lines (header first), or [] when nothing needs attention."""
    today = today or date.today()
    items: list[str] = []
    for source in (_arrival_lines, lambda: _picks_lines(today), _watchlist_lines):
        try:
            items.extend(source())
        except Exception:  # noqa: BLE001 - one bad source never hides the others
            continue
    items = items[:limit]
    if not items:
        return []
    return [f"Second Opinion, {len(items)} thing{'s' if len(items) != 1 else ''}:", *items]


def main(argv: list[str] | None = None) -> int:
    try:
        out = lines()
    except Exception:  # noqa: BLE001 - the hook never fails the session
        out = []
    if out:
        print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
