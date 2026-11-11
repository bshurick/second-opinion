"""Holding classification shared by the portfolio plan and its picks sleeve.

Buckets: employer for the saved employer symbol (unless it has a deep pick); core for quote type ETF
or MUTUALFUND, a fund-marked sector entry (fund_sectors or a look-through proxy) or a sector-less
EQUITY with a fund-shaped name; cash for MONEYMARKET; satellite for a plain EQUITY. Anything else is
unclassified. Also: the sweep-copy rule (a money market reported both as a holding and as the
account's cash counts once), the core sale rank and the employer candidate read from vest deposits.
"""
from __future__ import annotations

import re
import statistics
from datetime import date, timedelta

from second_opinion import market, proxies
from second_opinion.errors import ApiError

_FUND_TYPES = {"ETF", "MUTUALFUND"}
VEST_HISTORY_DAYS = 730        # how far back the employer-candidate read looks
VEST_GAP_DAYS = 30             # deposits closer than this are one vest
_VEST_RE = re.compile(r"shareworks|stock plan|equity (award|edge)|\brsus?\b|\bvest|restricted stock|\bespp\b"
                      r"|computershare|at work|global shares|\bcarta\b", re.I)
_NOT_DEPOSITS = {"BUY", "SELL", "DIVIDEND", "REI", "SPLIT"}


def fund_marked(entry: dict) -> bool:
    """A fund by its sector entry: fund_sectors or a proxy, or a sector-less EQUITY with a
    fund-shaped name (Yahoo's label for SPYM when its fund data will not load)."""
    if entry.get("fund_sectors") is not None or entry.get("proxy") is not None:
        return True
    return (str(entry.get("quote_type") or "").upper() == "EQUITY" and not entry.get("sector")
            and market.looks_like_a_fund_name(entry.get("name")))


def drop_sweep_copies(positions: list[dict], cash_by_account: dict[str, float]) -> list[dict]:
    """Positions without the money-market position a broker also reports as the account's cash.

    Per account with cash above 0, the cash-bucket position whose value is within $1 or 1% of
    that cash (the closest, when more than one) is the same money counted twice; it is dropped
    and the account's cash stays, since cash is what funds buys."""
    drop: set[int] = set()
    for aid, cash in cash_by_account.items():
        if cash <= 0:
            continue
        near = [(abs(cash - p["units"] * p["price"]), i) for i, p in enumerate(positions)
                if p["account"] == aid and p["bucket"] == "cash"
                and abs(cash - p["units"] * p["price"]) <= max(1.0, 0.01 * p["units"] * p["price"])]
        if near:
            drop.add(min(near)[1])
    return [p for i, p in enumerate(positions) if i not in drop]


def employer_default_message(cand: dict) -> str:
    """The STANDING_DEFAULT message for an unset employer run on the vest candidate ``cand``."""
    sym = cand["symbol"]
    every = f", about every {cand['every_days']} days" if cand.get("every_days") else ""
    sold = f", sold within {cand['sold_within_days']} days" if cand.get("sold_within_days") is not None else ""
    return (f"employer_symbol is unset: {sym} is used as employer stock for this run; account history shows "
            f"{sym} shares deposited from an equity plan on {len(cand['vests'])} vest dates "
            f"({cand['vests'][0]} to {cand['vests'][-1]}{every}{sold}); save plan.sleeves.EMPLOYER.members "
            f"({sym} or none) to keep or change it")


def employer_candidate(hub, accounts: list[dict], roles: dict[str, dict], today: str) -> dict | None:
    """The stock deposited in kind most often from an equity-plan administrator in the trading
    accounts' last VEST_HISTORY_DAYS, with its vest dates, cadence and how soon it was sold."""
    start = (date.fromisoformat(today) - timedelta(days=VEST_HISTORY_DAYS)).isoformat()
    deposits: dict[str, list[str]] = {}
    sales: dict[str, list[str]] = {}
    for a in accounts:
        aid = a["account_id"]
        if roles[aid]["role"] != "trading":
            continue
        try:
            rows = hub.list_transactions(aid, start=start, end=today, count=1000).get("transactions") or []
        except ApiError:
            continue
        for t in rows:
            sym = str(((t.get("symbol") or {}).get("symbol")) or "").upper()
            day = str(t.get("trade_date") or "")[:10]
            kind = str(t.get("type") or "").upper()
            if not sym or not day:
                continue
            if kind == "SELL":
                sales.setdefault(sym, []).append(day)
            elif (kind not in _NOT_DEPOSITS and (t.get("units") or 0) > 0
                  and _VEST_RE.search(str(t.get("description") or ""))):
                deposits.setdefault(sym, []).append(day)
    if not deposits:
        return None
    sym = sorted(deposits, key=lambda s: (-len(deposits[s]), s))[0]
    days = sorted(set(deposits[sym]))
    vests = [d for i, d in enumerate(days)
             if i == 0 or (date.fromisoformat(d) - date.fromisoformat(days[i - 1])).days > VEST_GAP_DAYS]
    gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(vests, vests[1:])]
    sold = sorted(sales.get(sym) or [])
    waits = [(date.fromisoformat(next(s for s in sold if s >= d)) - date.fromisoformat(d)).days
             for d in days if any(s >= d for s in sold)]
    return {"symbol": sym, "deposits": days, "vests": vests,
            "every_days": round(statistics.median(gaps)) if gaps else None,
            "sold_within_days": round(statistics.median(waits)) if waits else None}


def classify(positions: list[dict], info: dict, employer: str | None,
              deep: set[str] | frozenset[str] = frozenset()) -> tuple[list[dict], list[str]]:
    """Each position with its bucket, plus the symbols of unknown type (left out).

    employer for the saved employer symbol; core for quote type ETF or MUTUALFUND or a
    fund-marked entry (fund_sectors or proxy); cash for MONEYMARKET; satellite only for a
    plain EQUITY. With no quote type at all, the broker's name decides: a 401(k) trust matching
    a tracking ETF is core and a cash line is cash. Anything else is unclassified."""
    out, unknown = [], set()
    for p in positions:
        sym = p["symbol"]
        entry = info.get(sym) or {}
        qt = str(entry.get("quote_type") or "").upper()
        name = p.get("name")
        if employer and sym == employer and sym not in deep:
            bucket = "employer"
        elif qt in _FUND_TYPES or fund_marked(entry) or (not qt and proxies.lookthrough_proxy_for(name)):
            bucket = "core"
        elif qt == "MONEYMARKET" or (not qt and proxies.is_cash_like(sym, name)):
            bucket = "cash"
        elif qt == "EQUITY":
            bucket = "satellite"
        else:
            unknown.add(sym)
            continue
        out.append({**p, "bucket": bucket})
    return out, sorted(unknown)


_CORE_RANK = {"us_equity": 0, "intl_equity": 1, "other": 2, "bonds": 3}


def core_rank(positions: list[dict], info: dict) -> dict[str, int]:
    """Each core symbol's sale rank from the shared asset_bucket (portfolio-analysis's buckets):
    US equity 0, international equity 1, other 2, bonds 3; unknown or cash 2."""
    out = {}
    for p in positions:
        if p["bucket"] == "core":
            entry = info.get(p["symbol"]) or {"name": p.get("name")}
            out[p["symbol"]] = _CORE_RANK.get(proxies.asset_bucket(p["symbol"], entry) or "", 2)
    return out
