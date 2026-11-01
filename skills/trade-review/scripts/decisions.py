#!/usr/bin/env python3
"""Pick and score the decisions of a trade-review deep review (stdin -> stdout JSON).

    python decisions.py --pick N < review.json
    python decisions.py < decisions.json

--pick reads a run-review.py result and lists the N largest decisions by money moved, for the
researchers. The list carries no results, so neither the choice nor the research leans on how a
decision turned out. Cash-like funds are left out. Prints {"decisions": [{"id", "symbol", "action",
"date", "amount"}], "total_decisions", "amount_covered"}.

Scoring input: {"as_of", "review": <run-review.py result>, "decisions": [{"id", "symbol", "action":
"sell"|"buy", "date", "catalyst": "earnings"|"guidance"|"macro"|"company_event"|"price_target"|
"tax_or_cash"|"none", "quality": "sound"|"mixed"|"weak"|"unknown", "grade_reason", "stated_reason"
(optional), "known": [{"claim", "cut": "for"|"against", "source", "date"}], "later": [{"claim",
"source", "date"}]}]}.

known holds what was public by the decision's date, and a claim dated later is rejected. later holds
what came out afterwards, and a claim dated by the decision is rejected there. A sound or weak grade
needs evidence, and a sound one needs a claim in favor.

A sale's result is its move against the benchmark in the 90 days after it (drift_vs_benchmark_90,
weighted by proceeds across lots sold that day). A buy's result is its return so far: total_return
for a closed lot, unrealized_return for an open one, not benchmark-adjusted. Score is positive when
the decision worked: minus the drift for a sale, the return for a buy. At 5% or more either way the
verdict is good or bad, and flat between. A sale with no drift yet, or a buy held under 90 days, is
too_soon. A buy with no lot left to measure, such as a later lot of a position already sold, is
unavailable.

cell: sound+good skill, sound+bad bad_luck, weak+good luck, weak+bad mistake, otherwise unclear.

Output: {"as_of", "decisions": [input fields plus outcome: {"verdict", "score", "measure", "basis",
"amount", "total_pnl"}, cell], "cells", "patterns": {"by_quality", "by_catalyst", "by_action":
[{"group", "n", "avg_score", "hit_rate", "thin"}], "process_gap"}, "flags"}. A group is thin under
three scored decisions. process_gap is sound's average score less weak's, with at least three of
each. Exit 2 with {"error"} on invalid input.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import proxies  # noqa: E402

ACTIONS = ("sell", "buy")
QUALITIES = ("sound", "mixed", "weak", "unknown")
CATALYSTS = ("earnings", "guidance", "macro", "company_event", "price_target", "tax_or_cash", "none")
THRESHOLD = 0.05
MIN_DAYS = 90
MIN_GROUP = 3
MIN_SAMPLE = 10
CELLS = {("sound", "good"): "skill", ("sound", "bad"): "bad_luck", ("weak", "good"): "luck", ("weak", "bad"): "mistake"}
CELL_NAMES = ("skill", "luck", "bad_luck", "mistake", "unclear")


def _day(v: object, what: str) -> date:
    if not isinstance(v, str) or not v:
        raise ValueError(f"{what}: date is required")
    try:
        return date.fromisoformat(v[:10])
    except ValueError as exc:
        raise ValueError(f"{what}: date {v!r} is not YYYY-MM-DD") from exc


def _sells(review: dict) -> dict:
    out: dict[str, dict] = {}
    for t in review.get("round_trips") or []:
        key = f"sell-{str(t.get('symbol')).upper()}-{str(t.get('sell_date'))[:10]}"
        out.setdefault(key, {"symbol": str(t.get("symbol")).upper(), "action": "sell", "date": str(t.get("sell_date"))[:10], "rows": []})["rows"].append(t)
    for row in out.values():
        row["amount"] = round(sum(float(t.get("proceeds") or 0) for t in row["rows"]), 2)
    return out


def _buys(review: dict) -> dict:
    out: dict[str, dict] = {}

    def add(symbol: object, day: object, amount: float, closed: dict | None, opened: dict | None) -> None:
        key = f"buy-{str(symbol).upper()}-{str(day)[:10]}"
        row = out.setdefault(key, {"symbol": str(symbol).upper(), "action": "buy", "date": str(day)[:10], "amount": 0.0, "closed": [], "opened": []})
        row["amount"] = max(row["amount"], round(amount, 2))
        if closed:
            row["closed"].append(closed)
        if opened:
            row["opened"].append(opened)

    for b in review.get("largest_buys") or []:
        if not proxies.is_cash_like(b.get("symbol"), b.get("name")):
            add(b.get("symbol"), b.get("date"), abs(float(b.get("amount") or 0)), None, None)
    for lot in review.get("open_lots") or []:
        if not proxies.is_cash_like(lot.get("symbol"), lot.get("name")):
            add(lot.get("symbol"), lot.get("buy_date"), abs(float(lot.get("cost") or 0)), None, lot)
    for t in review.get("round_trips") or []:
        key = f"buy-{str(t.get('symbol')).upper()}-{str(t.get('first_buy_date'))[:10]}"
        if key in out:
            out[key]["closed"].append(t)
    return out


def pick_decisions(review: dict, top: int) -> dict:
    if not isinstance(review, dict) or "round_trips" not in review:
        raise ValueError("a run-review.py result is required")
    if top < 1:
        raise ValueError("--pick must be at least 1")
    rows = [*_sells(review).items(), *_buys(review).items()]
    rows = [(k, r) for k, r in rows if not proxies.is_cash_like(r["symbol"])]
    rows.sort(key=lambda kv: (-kv[1]["amount"], kv[0]))
    total = sum(r["amount"] for _, r in rows)
    chosen = rows[:top]
    return {"decisions": [{"id": k, "symbol": r["symbol"], "action": r["action"], "date": r["date"], "amount": r["amount"]} for k, r in chosen],
            "total_decisions": len(rows), "amount_covered": round(sum(r["amount"] for _, r in chosen) / total, 4) if total else None}


def _verdict(score: float) -> str:
    return "good" if score >= THRESHOLD else "bad" if score <= -THRESHOLD else "flat"


def outcome_for(key: str, review: dict) -> dict | None:
    """The result of one decision in a run-review.py result, or None when the review does not hold it."""
    sells = _sells(review)
    if key in sells:
        row = sells[key]
        weighted = [(float(t["drift_vs_benchmark_90"]), float(t.get("proceeds") or 0)) for t in row["rows"] if isinstance(t.get("drift_vs_benchmark_90"), (int, float))]
        pnl = round(sum(float(t.get("total_pnl") or 0) for t in row["rows"]), 2)
        base = {"amount": row["amount"], "total_pnl": pnl, "basis": "against the benchmark, 90 days after the sale"}
        if not weighted or sum(w for _, w in weighted) <= 0:
            return {"verdict": "too_soon", "score": None, "measure": None, **base}
        measure = round(sum(d * w for d, w in weighted) / sum(w for _, w in weighted), 4)
        return {"verdict": _verdict(-measure), "score": round(-measure, 4), "measure": measure, **base}
    buys = _buys(review)
    if key not in buys:
        return None
    row = buys[key]
    parts = [(float(t["total_return"]), float(t.get("cost") or t.get("proceeds") or 1), t.get("holding_days"), t.get("total_pnl")) for t in row["closed"] if isinstance(t.get("total_return"), (int, float))]
    parts += [(float(t["unrealized_return"]), float(t.get("cost") or 1), t.get("holding_days"), t.get("unrealized_pnl")) for t in row["opened"] if isinstance(t.get("unrealized_return"), (int, float))]
    base = {"amount": row["amount"], "basis": "return so far, not benchmark-adjusted", "total_pnl": round(sum(float(p[3] or 0) for p in parts), 2)}
    if not parts:
        return {"verdict": "unavailable", "score": None, "measure": None, **base}
    measure = round(sum(p[0] * abs(p[1]) for p in parts) / sum(abs(p[1]) for p in parts), 4)
    if max(int(p[2] or 0) for p in parts) < MIN_DAYS:
        return {"verdict": "too_soon", "score": None, "measure": measure, **base}
    return {"verdict": _verdict(measure), "score": measure, "measure": measure, **base}


def cell_for(quality: str, verdict: str) -> str:
    return CELLS.get((quality, verdict), "unclear")


def _claim(item: object, what: str) -> date:
    if not isinstance(item, dict):
        raise ValueError(f"{what} must be an object")
    for field in ("claim", "source"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"{what} has no {field}")
    return _day(item.get("date"), what)


def _validate(d: object, as_of: date) -> None:
    if not isinstance(d, dict) or not d.get("id") or not d.get("symbol"):
        raise ValueError("every decision needs an id and a symbol")
    did = d["id"]
    if d.get("action") not in ACTIONS:
        raise ValueError(f"decision {did}: action must be sell or buy")
    when = _day(d.get("date"), f"decision {did}")
    if when > as_of:
        raise ValueError(f"decision {did}: date is after as_of")
    if d.get("quality") not in QUALITIES:
        raise ValueError(f"decision {did}: quality must be one of {', '.join(QUALITIES)}")
    if d.get("catalyst") not in CATALYSTS:
        raise ValueError(f"decision {did}: catalyst must be one of {', '.join(CATALYSTS)}")
    if not isinstance(d.get("grade_reason"), str) or not d["grade_reason"].strip():
        raise ValueError(f"decision {did}: grade_reason is required")
    known = d.get("known") or []
    for c in known:
        day = _claim(c, f"decision {did} known claim")
        if day > when:
            raise ValueError(f"decision {did}: a claim dated {c['date']} is after the decision, so it could not be known")
        if c.get("cut") not in ("for", "against"):
            raise ValueError(f"decision {did}: each known claim's cut must be for or against")
    for c in d.get("later") or []:
        if _claim(c, f"decision {did} later claim") <= when:
            raise ValueError(f"decision {did}: a later claim dated {c['date']} was public by the decision, so it belongs in known")
    if d["quality"] in ("sound", "weak", "mixed") and not known:
        raise ValueError(f"decision {did}: no evidence, so its quality can only be unknown")
    if d["quality"] == "sound" and not any(c["cut"] == "for" for c in known):
        raise ValueError(f"decision {did}: a sound grade needs a claim in favor")


def _group(rows: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[float]] = {}
    for r in rows:
        if isinstance(r["outcome"]["score"], (int, float)):
            groups.setdefault(str(r[key]), []).append(r["outcome"]["score"])
    return sorted(({"group": g, "n": len(v), "avg_score": round(sum(v) / len(v), 4), "hit_rate": round(sum(1 for x in v if x > 0) / len(v), 4), "thin": len(v) < MIN_GROUP}
                   for g, v in groups.items()), key=lambda r: -r["n"])


def _flags(rows: list[dict]) -> list[dict]:
    flags = []

    def add(code: str, hits: list[dict], text: str) -> None:
        if hits:
            flags.append({"code": code, "message": f"{', '.join(r['id'] for r in hits)}: {text}"})

    scored = sum(1 for r in rows if isinstance(r["outcome"]["score"], (int, float)))
    if scored < MIN_SAMPLE:
        flags.append({"code": "SMALL_SAMPLE", "message": f"Only {scored} decisions have a result, too few for a pattern to mean much."})
    add("SAME_DAY_EVIDENCE", [r for r in rows if any(c["date"][:10] == r["date"] for c in r.get("known") or [])], "some evidence is dated the day of the decision, and it may have come after the trade.")
    add("ONE_SIDED_EVIDENCE", [r for r in rows if r.get("known") and len({c["cut"] for c in r["known"]}) == 1], "the evidence found cuts only one way.")
    add("NO_PUBLIC_EVIDENCE", [r for r in rows if not r.get("known")], "no dated public evidence was found, so this cannot be graded.")
    add("RESULTS_TOO_SOON", [r for r in rows if r["outcome"]["verdict"] == "too_soon"], "too little time has passed to judge the result.")
    add("NO_RESULT", [r for r in rows if r["outcome"]["verdict"] == "unavailable"], "the review holds no lot to measure this buy against.")
    if any(r["action"] == "buy" for r in rows):
        flags.append({"code": "BUYS_NOT_ADJUSTED", "message": "A buy's result is its plain return, not measured against the benchmark, so a rising market flatters it."})
    return flags


def run_score(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    as_of = _day(params.get("as_of"), "as_of")
    review = params.get("review")
    if not isinstance(review, dict) or "round_trips" not in review:
        raise ValueError("review (a run-review.py result) is required")
    raw = params.get("decisions")
    if not isinstance(raw, list) or not raw:
        raise ValueError("decisions must be a non-empty list")
    rows, ids = [], set()
    for d in raw:
        _validate(d, as_of)
        if d["id"] in ids:
            raise ValueError(f"decision {d['id']} appears twice")
        ids.add(d["id"])
        key = f"{d['action']}-{str(d['symbol']).upper()}-{d['date'][:10]}"
        outcome = outcome_for(key, review)
        if outcome is None:
            raise ValueError(f"decision {d['id']}: {d['action']} of {d['symbol']} on {d['date']} is not in the review")
        rows.append({**d, "known": d.get("known") or [], "later": d.get("later") or [], "outcome": outcome, "cell": cell_for(d["quality"], outcome["verdict"])})
    cells = {name: sum(1 for r in rows if r["cell"] == name) for name in CELL_NAMES}
    by_quality = _group(rows, "quality")
    q = {r["group"]: r for r in by_quality}
    gap = None
    if q.get("sound", {}).get("n", 0) >= MIN_GROUP and q.get("weak", {}).get("n", 0) >= MIN_GROUP:
        gap = round(q["sound"]["avg_score"] - q["weak"]["avg_score"], 4)
    rows.sort(key=lambda r: -float(r["outcome"].get("amount") or 0))
    return {"as_of": str(as_of), "decisions": rows, "cells": cells,
            "patterns": {"by_quality": by_quality, "by_catalyst": _group(rows, "catalyst"), "by_action": _group(rows, "action"), "process_gap": gap},
            "flags": _flags(rows)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--pick", type=int, default=None)
    try:
        ns = p.parse_args(argv)
        data = json.loads(sys.stdin.read())
        result = pick_decisions(data, ns.pick) if ns.pick is not None else run_score(data)
    except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
