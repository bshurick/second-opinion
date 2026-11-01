#!/usr/bin/env python3
"""The math of the portfolio deep review (stdin -> stdout JSON).

    python exposure.py < bets.json

Input: {"as_of", "book": <portfolio-snapshot snapshot.py output>, "risk": <risk-analysis stress.py
output, optional>, "income": [{"id", "name", "annual"}] (optional), "bets": [{"id", "name", "belief",
"verdict": "holding"|"contested"|"weakening"|"open",
"links": [{"symbol", "share": above 0 to 1, "shock": -1 to 1, "why", "source", "date"}],
"income_links": [{"income", "share", "shock", "why", "source", "date"}],
"for": [{"claim", "source", "date"}], "against": [{"claim", "source", "date"}],
"watch": [{"what", "breaks_if", "check_by"}]}]}.

For each link, exposed_value = market value x share and loss_if_wrong = exposed_value x shock. For
each income link, income_at_risk = -(annual x share x shock), one year of income. A bet's at_stake
is its net loss plus its income at risk (a net gain counts as nothing at stake), and bets run
largest at_stake first. Bets overlap, so no total of their losses is ever given.

history compares the average pairwise correlation of a bet's holdings with the average across all
holdings in the stress result. A bet whose holdings move together no more than the portfolio does
reads not_visible_in_prices. It is null without a full stress matrix (stress.py --full-correlation;
the strongest-pairs form would bias the average) or without two priced holdings.

Output: {"as_of", "bets": [input fields plus holdings, exposed_value, exposed_pct, loss_if_wrong,
loss_pct, income_at_risk, at_stake, gone, history, with exposed_value and loss_if_wrong on each
link], "largest", "overlaps": [{"a", "b", "shared_value", "symbols"}], "unmapped": [{"symbol",
"name", "value", "weight"}], "held", "income", "totals": {"total_value", "invested_value",
"cash_like_value", "mapped_value", "coverage", "income_included", "income_annual"},
"small_unmapped": {"count", "value"}, "flags"}.
shared_value sums the smaller exposure of each holding two bets share. unmapped lists holdings of
at least 1% of the portfolio that no bet touches, cash-like funds left out; small_unmapped counts
the rest. coverage is mapped value over invested value, both without cash-like funds.

Exit 2 with {"error"} on a link to a holding not held, a link or claim with no source or date, a
date after as_of, a share or shock out of range, an unknown verdict or income id, a bet with no
links, or a holding linked twice in one bet. With "allow_missing": true (review_store.py check), a
holding no longer held counts as zero and is listed in the bet's gone.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import proxies  # noqa: E402

VERDICTS = ("holding", "contested", "weakening", "open")
MIN_UNMAPPED_WEIGHT = 0.01
STALE_DAYS = 365


def _num(v: object, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


def _day(v: object, field: str) -> date:
    if not isinstance(v, str) or not v:
        raise ValueError(f"{field}: date is required")
    try:
        return date.fromisoformat(v[:10])
    except ValueError as exc:
        raise ValueError(f"{field}: date {v!r} is not YYYY-MM-DD") from exc


def _sourced(item: object, what: str, text_field: str, as_of: date) -> date:
    """Check that one piece of evidence names its source and a date no later than as_of."""
    if not isinstance(item, dict):
        raise ValueError(f"{what} must be an object")
    for field in (text_field, "source"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"{what} has no {field}")
    when = _day(item.get("date"), what)
    if when > as_of:
        raise ValueError(f"{what}: date {item['date']} is after as_of {as_of}")
    return when


def _share_shock(link: dict, what: str) -> tuple[float, float]:
    share = _num(link.get("share"), f"{what} share")
    shock = _num(link.get("shock"), f"{what} shock")
    if not 0 < share <= 1:
        raise ValueError(f"{what} share must be above 0 and at most 1")
    if not -1 <= shock <= 1:
        raise ValueError(f"{what} shock must be from -1 to 1")
    return share, shock


def _list(v: object, what: str) -> list:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError(f"{what} must be a list")
    return v


def _book(book: object) -> tuple[dict, float]:
    if not isinstance(book, dict) or not isinstance(book.get("positions"), list):
        raise ValueError("book (a snapshot.py result) is required")
    held = {}
    for p in book["positions"]:
        sym = str(p.get("symbol") or "").strip().upper() if isinstance(p, dict) else ""
        if not sym:
            raise ValueError("every book position needs a symbol")
        held[sym] = {"symbol": sym, "name": p.get("name"), "value": _num(p.get("market_value") or 0, f"{sym} market_value")}
    total = (book.get("totals") or {}).get("total_value")
    total = _num(total, "totals.total_value") if total is not None else sum(h["value"] for h in held.values())
    if total <= 0:
        raise ValueError("the book's total value must be positive")
    return held, total


def _income(rows: object) -> dict:
    out = {}
    for r in _list(rows, "income"):
        if not isinstance(r, dict) or not r.get("id") or not r.get("name"):
            raise ValueError("every income entry needs an id and a name")
        annual = _num(r.get("annual"), f"income {r['id']} annual")
        if annual < 0:
            raise ValueError(f"income {r['id']} annual must not be negative")
        out[r["id"]] = {"id": r["id"], "name": r["name"], "annual": annual}
    return out


def _correlations(risk: object) -> dict | None:
    corr = risk.get("correlation") if isinstance(risk, dict) else None
    if not isinstance(corr, dict) or not corr.get("symbols") or not corr.get("matrix"):
        return None
    syms, matrix = corr["symbols"], corr["matrix"]
    pairs = {}
    for i, j in combinations(range(len(syms)), 2):
        value = matrix[i][j]
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            pairs[frozenset((str(syms[i]).upper(), str(syms[j]).upper()))] = float(value)
    return pairs or None


def _history(symbols: list[str], pairs: dict | None) -> dict | None:
    if not pairs:
        return None
    found = [pairs[frozenset(c)] for c in combinations(symbols, 2) if frozenset(c) in pairs]
    if not found:
        return None
    avg, overall = sum(found) / len(found), sum(pairs.values()) / len(pairs)
    return {"avg_correlation": round(avg, 4), "portfolio_avg_correlation": round(overall, 4), "pairs": len(found),
            "reading": "moves_together" if avg > overall else "not_visible_in_prices"}


def _measure_bet(bet: object, held: dict, total: float, income: dict, as_of: date, lenient: bool, pairs: dict | None) -> dict:
    if not isinstance(bet, dict) or not bet.get("id"):
        raise ValueError("every bet needs an id")
    bid = bet["id"]
    for field in ("name", "belief"):
        if not isinstance(bet.get(field), str) or not bet[field].strip():
            raise ValueError(f"bet {bid}: {field} is required")
    if bet.get("verdict") not in VERDICTS:
        raise ValueError(f"bet {bid}: verdict must be one of {', '.join(VERDICTS)}")
    raw_links, raw_income = _list(bet.get("links"), f"bet {bid} links"), _list(bet.get("income_links"), f"bet {bid} income_links")
    if not raw_links and not raw_income:
        raise ValueError(f"bet {bid} needs at least one link")

    links, gone, seen, dates = [], [], set(), []
    for link in raw_links:
        dates.append(_sourced(link, f"bet {bid} link", "why", as_of))
        sym = str(link.get("symbol") or "").strip().upper()
        share, shock = _share_shock(link, f"bet {bid} {sym}")
        if sym in seen:
            raise ValueError(f"bet {bid}: {sym} is linked twice")
        seen.add(sym)
        if sym not in held:
            if not lenient:
                raise ValueError(f"bet {bid}: {sym or 'a link'} is not held")
            gone.append(sym)
        exposed = held[sym]["value"] * share if sym in held else 0.0
        links.append({**link, "symbol": sym, "exposed_value": round(exposed, 2), "loss_if_wrong": round(exposed * shock, 2)})

    income_links, at_risk = [], 0.0
    for link in raw_income:
        dates.append(_sourced(link, f"bet {bid} income link", "why", as_of))
        source = income.get(link.get("income"))
        if source is None:
            raise ValueError(f"bet {bid}: income {link.get('income')!r} is not in the income list")
        share, shock = _share_shock(link, f"bet {bid} income {source['id']}")
        risk = -source["annual"] * share * shock
        at_risk += risk
        income_links.append({**link, "name": source["name"], "income_at_risk": round(risk, 2)})

    for side in ("for", "against"):
        for claim in _list(bet.get(side), f"bet {bid} {side}"):
            dates.append(_sourced(claim, f"bet {bid} {side} claim", "claim", as_of))
    for item in _list(bet.get("watch"), f"bet {bid} watch"):
        if not isinstance(item, dict) or not item.get("what") or not item.get("breaks_if"):
            raise ValueError(f"bet {bid}: a watch item needs what and breaks_if")
        _day(item.get("check_by"), f"bet {bid} watch check_by")

    exposed = sum(x["exposed_value"] for x in links)
    loss = sum(x["loss_if_wrong"] for x in links)
    return {**bet, "links": links, "income_links": income_links, "for": bet.get("for") or [], "against": bet.get("against") or [],
            "watch": bet.get("watch") or [], "holdings": len(links) - len(gone), "gone": gone,
            "exposed_value": round(exposed, 2), "exposed_pct": round(exposed / total, 4),
            "loss_if_wrong": round(loss, 2), "loss_pct": round(loss / total, 4), "income_at_risk": round(at_risk, 2),
            "at_stake": round(max(-loss, 0.0) + max(at_risk, 0.0), 2),
            "history": _history([x["symbol"] for x in links if x["symbol"] in held], pairs),
            "_stale": any((as_of - d).days > STALE_DAYS for d in dates)}


def _overlaps(bets: list[dict]) -> list[dict]:
    out = []
    for a, b in combinations(bets, 2):
        left = {x["symbol"]: x["exposed_value"] for x in a["links"] if x["exposed_value"] > 0}
        right = {x["symbol"]: x["exposed_value"] for x in b["links"] if x["exposed_value"] > 0}
        shared = sorted(set(left) & set(right))
        if shared:
            out.append({"a": a["id"], "b": b["id"], "shared_value": round(sum(min(left[s], right[s]) for s in shared), 2), "symbols": shared})
    return sorted(out, key=lambda o: -o["shared_value"])


def _names(bets: list[dict]) -> str:
    return "; ".join(dict.fromkeys(b["name"] for b in bets))


def _flags(bets: list[dict], unmapped: list[dict], pairs: dict | None) -> list[dict]:
    flags = []

    def add(code: str, hits: list[dict], text: str) -> None:
        if hits:
            flags.append({"code": code, "message": f"{_names(hits)}: {text}"})

    add("NO_OPPOSING_EVIDENCE", [b for b in bets if not b["against"]], "no evidence against this bet was found, so the view is one-sided.")
    add("SINGLE_HOLDING", [b for b in bets if len(b["links"]) == 1 and not b["income_links"]], "only one holding rests on this, so it is a single-name risk, not a shared bet.")
    add("STALE_EVIDENCE", [b for b in bets if b["_stale"]], f"some evidence is more than {STALE_DAYS} days old.")
    add("NOT_IN_PRICES", [b for b in bets if (b["history"] or {}).get("reading") == "not_visible_in_prices"], "these holdings have moved together no more than the portfolio has, so correlations would not show this bet.")
    if unmapped:
        flags.append({"code": "UNMAPPED_HOLDINGS", "message": f"No bet covers {', '.join(u['symbol'] for u in unmapped)}, so the review says nothing about them."})
    if pairs is None:
        flags.append({"code": "NO_RISK_DATA", "message": "No correlation data came with this run, so the review cannot say which bets prices already show."})
    return flags


def run_exposure(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    as_of = _day(params.get("as_of"), "as_of")
    held, total = _book(params.get("book"))
    income = _income(params.get("income"))
    pairs = _correlations(params.get("risk"))
    raw = params.get("bets")
    if not isinstance(raw, list) or not raw:
        raise ValueError("bets must be a non-empty list")
    lenient = params.get("allow_missing") is True
    ordered, ids = [], set()
    for bet in raw:
        row = _measure_bet(bet, held, total, income, as_of, lenient, pairs)
        if row["id"] in ids:
            raise ValueError(f"bet id {row['id']} appears twice")
        ids.add(row["id"])
        ordered.append(row)

    largest_link: dict[str, float] = {}  # bets overlap, so a holding counts once, at its largest exposure
    for bet in ordered:
        for link in bet["links"]:
            if link["exposed_value"] > 0:
                largest_link[link["symbol"]] = max(largest_link.get(link["symbol"], 0.0), link["exposed_value"])
    is_cash = {s: proxies.is_cash_like(s, h["name"]) for s, h in held.items()}
    invested = sum(h["value"] for s, h in held.items() if not is_cash[s])
    uncovered = [(s, h) for s, h in held.items() if s not in largest_link and not is_cash[s] and h["value"] > 0]
    unmapped = sorted(
        ({"symbol": s, "name": h["name"], "value": round(h["value"], 2), "weight": round(h["value"] / total, 4)}
         for s, h in uncovered if h["value"] / total >= MIN_UNMAPPED_WEIGHT),
        key=lambda u: -u["value"])
    small = [h["value"] for _, h in uncovered if h["value"] / total < MIN_UNMAPPED_WEIGHT]
    overlaps = _overlaps(ordered)
    bets = sorted(ordered, key=lambda b: (-b["at_stake"], str(b["id"])))
    flags = _flags(bets, unmapped, pairs)
    for bet in bets:
        del bet["_stale"]
    mapped_invested = sum(v for s, v in largest_link.items() if not is_cash[s])
    return {"as_of": str(as_of), "bets": bets, "largest": bets[0]["id"], "overlaps": overlaps, "unmapped": unmapped,
            "small_unmapped": {"count": len(small), "value": round(sum(small), 2)},
            "held": sorted(held), "income": list(income.values()),
            "totals": {"total_value": round(total, 2), "invested_value": round(invested, 2), "cash_like_value": round(total - invested, 2),
                       "mapped_value": round(sum(largest_link.values()), 2),
                       "coverage": round(mapped_invested / invested, 4) if invested > 0 else None,
                       "income_included": bool(income), "income_annual": round(sum(r["annual"] for r in income.values()), 2)},
            "flags": flags}


def main() -> None:
    try:
        result = run_exposure(json.loads(sys.stdin.read()))
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
