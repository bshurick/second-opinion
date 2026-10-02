"""Market source: notable index moves, VIX, curve inversion, breadth, CFTC extremes, one-year-high money-fund cash."""
from __future__ import annotations

from second_opinion import headlines as H

SKILL = "market-analysis"
INDEX_MOVE_PCT = 1.0          # indices[].day_change_pct is in percent
VIX_PERCENTILE = 0.80         # vix_percentile_1y is a 0-1 fraction
BREADTH_WEAK = 0.30
BREADTH_STRONG = 0.80
CFTC_HIGH = 95.0              # classes[].percentile is 0-100 over the contract's own weeks window (flows.py --weeks defaults to 52; sources.py runs it with no --weeks)
CFTC_LOW = 5.0
CFTC_CLASS_LABEL = {"leveraged_funds": "Hedge funds", "asset_managers": "Institutions"}
CFTC_GROUPS = {"index", "rates", "fx", "volatility"}
CFTC_WEEKS_MIN = 26
CFTC_URL = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
ASK = "How is the market positioned this week?"
WHY = {
    "INDEX_MOVE": "A one-day move of 1% or more is unusual for a broad index.",
    "VIX_HIGH": "The VIX is the market's expected 30-day volatility; a high reading means options are pricing bigger swings.",
    "CURVE_INVERTED": "Short rates above long rates has preceded most US recessions, usually with a long lag.",
    "BREADTH_WEAK": "Breadth is how many sectors are trending up; narrow breadth means a few names carry the index.",
    "BREADTH_STRONG": "Breadth is how many sectors are trending up; narrow breadth means a few names carry the index.",
    "DAY": "",
    "CFTC_EXTREME": ("Weekly CFTC positioning of hedge funds (leveraged funds) and institutions (asset managers) in "
                      "futures; an extreme reading has more often preceded a reversal than a continuation."),
    "CASH_RECORD": "Cash parked in money-market funds; a high level is dry powder that has not been put into stocks or bonds.",
}


def _cash_unit_word(unit) -> str:
    u = str(unit or "").strip()
    lower = u.lower()
    if lower.startswith("billions"):
        return "billion"
    if lower.startswith("trillions"):
        return "trillion"
    return u


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _row(rows: list, symbol: str) -> dict | None:
    return next((r for r in rows or [] if isinstance(r, dict) and r.get("symbol") == symbol), None)


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _from_indices(res: dict, today: str) -> list[dict]:
    out: list[dict] = []
    idx = res.get("indices") or []
    spx, ndx, vix = _row(idx, "^GSPC"), _row(idx, "^IXIC"), _row(idx, "^VIX")
    for r, name in ((spx, "S&P 500"), (ndx, "Nasdaq")):
        chg = _num((r or {}).get("day_change_pct"))
        if chg is not None and abs(chg) >= INDEX_MOVE_PCT:
            verb = "rose" if chg > 0 else "fell"
            week = _num((r or {}).get("week_change_pct"))
            last = _num((r or {}).get("last"))
            answer = f"{name} {last:,.2f}, {week:+.1f}% on the week" if last is not None and week is not None else ""
            out.append(H.make(SKILL, "INDEX_MOVE", "notice", f"{name} {verb} {abs(chg):.1f}% today", discriminator=f"{name}:{today}",
                              detail=f"last {r.get('last')}", as_of=today, ask=ASK, answer=answer, why=WHY["INDEX_MOVE"]))
    pct = _num(res.get("vix_percentile_1y"))
    vix_last = _num((vix or {}).get("last"))
    if pct is not None and pct >= VIX_PERCENTILE:
        p = int(round(pct * 100))
        vix_answer = f"VIX {vix_last:.1f} versus a one-year range; above the 80th percentile" if vix_last is not None else ""
        out.append(H.make(SKILL, "VIX_HIGH", "notice", f"VIX {vix_last:.1f} is at the {_ordinal(p)} percentile of the last year" if vix_last is not None
                          else f"VIX is at the {_ordinal(p)} percentile of the last year", discriminator=today, as_of=today, ask=ASK,
                          answer=vix_answer, why=WHY["VIX_HIGH"]))
    spread = _num((res.get("spreads") or {}).get("10y_13w"))
    if spread is not None and spread < 0:
        irx = _num((_row(res.get("rates") or [], "^IRX") or {}).get("last"))
        tnx_for_curve = _num((_row(res.get("rates") or [], "^TNX") or {}).get("last"))
        curve_answer = f"3-month {irx:.2f}% vs 10-year {tnx_for_curve:.2f}%" if irx is not None and tnx_for_curve is not None else ""
        out.append(H.make(SKILL, "CURVE_INVERTED", "notice", f"Yield curve inverted: 10-year minus 3-month is {spread:.2f} points",
                          discriminator=today, as_of=today, ask=ASK, answer=curve_answer, why=WHY["CURVE_INVERTED"]))
    b = res.get("breadth") or {}
    above, total = _num(b.get("sectors_above_50sma")), _num(b.get("sectors_total"))
    rsp_spy = _num(b.get("rsp_spy_1m"))
    if above is not None and total:
        share = above / total
        breadth_answer = f"{int(above)} of {int(total)} sectors above their 50-day; RSP/SPY {rsp_spy:+.1f}% over one month" if rsp_spy is not None else ""
        if share < BREADTH_WEAK:
            out.append(H.make(SKILL, "BREADTH_WEAK", "notice", f"Only {int(above)} of {int(total)} sectors are above their 50-day average",
                              discriminator=today, as_of=today, ask=ASK, answer=breadth_answer, why=WHY["BREADTH_WEAK"]))
        elif share > BREADTH_STRONG:
            out.append(H.make(SKILL, "BREADTH_STRONG", "notice", f"{int(above)} of {int(total)} sectors are above their 50-day average",
                              discriminator=today, as_of=today, ask=ASK, answer=breadth_answer, why=WHY["BREADTH_STRONG"]))
    parts = []
    for r, name in ((spx, "S&P 500"), (ndx, "Nasdaq")):
        chg = _num((r or {}).get("day_change_pct"))
        if chg is not None:
            parts.append(f"{name} {chg:+.1f}%")
    tnx = _num((_row(res.get("rates") or [], "^TNX") or {}).get("last"))
    if tnx is not None:
        parts.append(f"10y {tnx:.2f}%")
    if vix_last is not None:
        parts.append(f"VIX {vix_last:.1f}")
    if parts:
        out.append(H.make(SKILL, "DAY", "info", " · ".join(parts), discriminator=today, as_of=today, ask=ASK, why=WHY["DAY"]))
    return out


def _from_flows(res: dict, today: str) -> list[dict]:
    out: list[dict] = []
    pos = res.get("positioning") or {}
    if isinstance(pos, dict) and not pos.get("error"):
        report = str(pos.get("report_date") or today)
        for c in pos.get("contracts") or []:
            weeks = c.get("weeks")
            if c.get("group") not in CFTC_GROUPS or not isinstance(weeks, (int, float)) or weeks < CFTC_WEEKS_MIN:
                continue
            label = c.get("label") or c.get("name") or c.get("code")
            for cls, class_label in CFTC_CLASS_LABEL.items():
                row = (c.get("classes") or {}).get(cls) or {}
                pct = _num(row.get("percentile"))
                if pct is None or not (pct >= CFTC_HIGH or pct <= CFTC_LOW):
                    continue
                net, net_change, net_pct_oi = row.get("net"), row.get("net_change"), row.get("net_pct_oi")
                net_num = _num(net)
                net_nonneg = net_num is None or net_num >= 0
                if pct <= CFTC_LOW:
                    phrase = "least net long" if net_nonneg else "most net short"
                else:
                    phrase = "most net long" if net_nonneg else "least net short"
                answer = (f"Net {net:+,} contracts, {net_pct_oi:.1f}% of open interest, {net_change:+,} on the week"
                          if all(isinstance(v, (int, float)) for v in (net, net_change, net_pct_oi)) else "")
                out.append(H.make(SKILL, "CFTC_EXTREME", "notice",
                                  f"{class_label} are the {phrase} {label} futures in {int(weeks)} weeks",
                                  discriminator=f"{c.get('code')}:{cls}:{report}", detail=f"net {row.get('net')} contracts", as_of=report, ask=ASK,
                                  url=CFTC_URL, answer=answer, why=WHY["CFTC_EXTREME"]))
    cash = res.get("cash") or {}
    if isinstance(cash, dict) and not cash.get("error"):
        latest, when = _num(cash.get("latest")), str(cash.get("date") or today)
        values = [_num(o.get("value")) for o in cash.get("observations") or [] if isinstance(o, dict)]
        values = [v for v in values if v is not None]
        if latest is not None and values and latest >= max(values):
            change_4w, change_52w_pct = _num(cash.get("change_4w")), _num(cash.get("change_52w_pct"))
            unit_word = _cash_unit_word(cash.get("unit"))
            answer = (f"{change_4w:+,.0f} {unit_word} over four weeks, {change_52w_pct:+.1f}% over a year".replace("  ", " ")
                      if change_4w is not None and change_52w_pct is not None else "")
            series = cash.get("series")
            url = f"https://fred.stlouisfed.org/series/{series}" if series else ""
            out.append(H.make(SKILL, "CASH_RECORD", "notice", f"Money-fund cash {latest:.2f} {cash.get('unit') or ''} is a one-year high ({when})".replace("  ", " "),
                              discriminator=when, detail=f"52-week change {cash.get('change_52w_pct')}", as_of=when, ask=ASK,
                              url=url, answer=answer, why=WHY["CASH_RECORD"]))
    return out


def extract(results: dict, ctx: dict) -> list[dict]:
    today = str(ctx["today"])
    indices = results.get("indices") or {}
    flows = results.get("flows") or {}
    notices = [h for h in _from_indices(indices, today) if h["severity"] == "notice"]
    info = [h for h in _from_indices(indices, today) if h["severity"] == "info"]
    return notices + _from_flows(flows, today) + info
