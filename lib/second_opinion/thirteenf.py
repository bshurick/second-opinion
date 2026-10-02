"""Pure 13F work: the information table XML into holdings, and a quarter-over-quarter diff.

A 13F-HR lists every long position (shares, and options as separate PUT or
CALL rows) an institutional manager with over $100M held at quarter end,
filed within 45 days. The information table repeats a CUSIP once per
sub-manager, so ``parse_information_table`` sums shares and value by CUSIP
(options keyed ``CUSIP:PUT`` / ``CUSIP:CALL``). Values are whole dollars
since 2023. ``diff_holdings`` compares two quarters by share count: new,
exited, increased, trimmed, plus totals and concentration. Price moves change
value but not shares, which is why the classification uses shares.

``MANAGERS`` is a curated alias -> CIK list of large or widely followed
filers, each verified against EDGAR on 2026-09-14; ``resolve_manager``
accepts an alias fragment or a bare CIK.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

MANAGERS: dict[str, int] = {
    "berkshire": 1067983,
    "bridgewater": 1350694,
    "renaissance": 1037389,
    "citadel": 1423053,
    "millennium": 1273087,
    "two-sigma": 1179392,
    "de-shaw": 1009207,
    "pershing-square": 1336528,
    "soros": 1029160,
    "baupost": 1061768,
    "appaloosa": 1656456,
    "third-point": 1040273,
    "elliott": 1791786,
    "tiger-global": 1167483,
    "coatue": 1135730,
    "scion": 1649339,
    "ark": 1697748,
    "duquesne": 1536411,
    "lone-pine": 1061165,
    "viking": 1103804,
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(elem: ET.Element, *path: str) -> str | None:
    cur: ET.Element | None = elem
    for name in path:
        cur = next((c for c in cur if _local(c.tag) == name), None) if cur is not None else None
        if cur is None:
            return None
    return (cur.text or "").strip() if cur is not None else None


def _num(v: str | None) -> int:
    try:
        return int(float(v or 0))
    except ValueError:
        return 0


def parse_information_table(xml: bytes) -> dict[str, dict[str, Any]]:
    """Holdings keyed by CUSIP (``CUSIP:PUT`` / ``CUSIP:CALL`` for options), shares and value summed across sub-managers."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"not a 13F information table: {exc}") from exc
    if _local(root.tag) != "informationTable":
        raise ValueError(f"not a 13F information table (root element {_local(root.tag)!r})")
    out: dict[str, dict[str, Any]] = {}
    for entry in root.iter():
        if _local(entry.tag) != "infoTable":
            continue
        cusip = (_text(entry, "cusip") or "").upper()
        if not cusip:
            continue
        put_call = (_text(entry, "putCall") or "").strip().upper() or None
        key = f"{cusip}:{put_call}" if put_call else cusip
        row = out.setdefault(key, {"cusip": cusip, "issuer": _text(entry, "nameOfIssuer") or "", "class": _text(entry, "titleOfClass") or "", "value": 0, "shares": 0, "put_call": put_call})
        row["value"] += _num(_text(entry, "value"))
        row["shares"] += _num(_text(entry, "shrsOrPrnAmt", "sshPrnamt"))
    return out


def _pct(part: float, whole: float | None) -> float | None:
    return round(part / whole * 100, 2) if whole else None


def _ident(h: dict[str, Any]) -> dict[str, Any]:
    return {"cusip": h["cusip"], "issuer": h["issuer"], "class": h["class"], "put_call": h.get("put_call")}


def diff_holdings(current: dict[str, dict[str, Any]], previous: dict[str, dict[str, Any]], limit: int = 25) -> dict[str, Any]:
    total = sum(h["value"] for h in current.values())
    prev_total = sum(h["value"] for h in previous.values()) if previous else None
    new, exited, increased, trimmed = [], [], [], []
    unchanged = 0
    for key, h in current.items():
        p = previous.get(key)
        if p is None:
            new.append({**_ident(h), "shares": h["shares"], "value": h["value"], "weight_pct": _pct(h["value"], total)})
        elif h["shares"] == p["shares"]:
            unchanged += 1
        else:
            row = {**_ident(h), "shares": h["shares"], "previous_shares": p["shares"], "shares_change_pct": _pct(h["shares"] - p["shares"], p["shares"]), "value": h["value"], "weight_pct": _pct(h["value"], total)}
            (increased if h["shares"] > p["shares"] else trimmed).append(row)
    for key, p in previous.items():
        if key not in current:
            exited.append({**_ident(p), "previous_shares": p["shares"], "previous_value": p["value"]})
    new.sort(key=lambda r: -r["value"])
    increased.sort(key=lambda r: -r["value"])
    trimmed.sort(key=lambda r: -r["value"])
    exited.sort(key=lambda r: -r["previous_value"])
    ranked = sorted(current.values(), key=lambda h: -h["value"])
    top = [{**_ident(h), "shares": h["shares"], "value": h["value"], "weight_pct": _pct(h["value"], total)} for h in ranked[:limit]]
    lists = {"new": new, "exited": exited, "increased": increased, "trimmed": trimmed}
    truncated = {k: len(v) - limit for k, v in lists.items() if len(v) > limit}
    return {
        "totals": {"value": total, "previous_value": prev_total, "positions": len(current), "previous_positions": len(previous) if previous else None, "value_change_pct": round((total / prev_total - 1) * 100, 2) if prev_total else None},
        **{k: v[:limit] for k, v in lists.items()},
        "unchanged": unchanged,
        "top": top,
        "concentration": {"top_5_pct": _pct(sum(h["value"] for h in ranked[:5]), total), "top_10_pct": _pct(sum(h["value"] for h in ranked[:10]), total)},
        "truncated": truncated,
    }


def resolve_manager(text: str) -> tuple[int, str | None] | None:
    """(CIK, alias) for an alias fragment or a bare CIK; None when nothing matches."""
    key = text.strip().lower().replace(" ", "-").replace("_", "-")
    if key.isdigit():
        cik = int(key)
        return (cik, next((a for a, c in MANAGERS.items() if c == cik), None))
    if key in MANAGERS:
        return (MANAGERS[key], key)
    matches = [a for a in MANAGERS if key in a]
    return (MANAGERS[matches[0]], matches[0]) if len(matches) == 1 else None
