"""EDGAR source: a fresh 10-K, 10-Q or 8-K is an alert; the quality screen's red flags are one notice per symbol."""
from __future__ import annotations

from datetime import date

from second_opinion import headlines as H

SKILL = "fundamental-research"
FILING_WINDOW_DAYS = 7
RED_FLAGS = {"NEGATIVE_FCF", "LEVERAGE", "REVENUE_DECLINE", "DILUTION", "SBC_HEAVY", "DSO_RISING",
             "INVENTORY_BUILDING", "GOODWILL_HEAVY", "ACCRUALS", "RECEIVABLES_BUILDING"}
_ASK = {"10-K": "What changed in {s}'s latest 10-K?", "10-Q": "What changed in {s}'s latest 10-Q?", "8-K": "What does {s}'s latest 8-K say?"}
WHY = {"FILING_10": "A 10-Q is the quarterly report; a 10-K the annual one. Its risk-factor section is where new problems appear first.",
       "FILING_8K": "An 8-K is a current report a company files within four business days of a material event.",
       "RED_FLAGS": "Screens on the company's own filings: cash flow, leverage, dilution and revenue trend."}
EIGHT_K_ITEMS = {
    "1.01": "Entry into a Material Agreement", "1.02": "Termination of a Material Agreement",
    "2.01": "Completion of Acquisition or Disposition", "2.02": "Results of Operations",
    "2.03": "Creation of a Direct Financial Obligation", "3.02": "Unregistered Sales of Equity",
    "5.02": "Departure or Appointment of Officers or Directors", "5.03": "Amendments to Articles or Bylaws",
    "5.07": "Submission of Matters to a Vote", "7.01": "Regulation FD Disclosure", "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}


def _eight_k_answer(items) -> str:
    codes = [c.strip() for c in str(items or "").split(",") if c.strip()]
    if not codes:
        return ""
    return "; ".join(EIGHT_K_ITEMS.get(c, f"Item {c}") for c in codes)


def _recent(when, today: date) -> date | None:
    try:
        d = date.fromisoformat(str(when)[:10])
    except (TypeError, ValueError):
        return None
    return d if 0 <= (today - d).days <= FILING_WINDOW_DAYS else None


def _symbol_headlines(sym: str, res: dict, today: date) -> list[dict]:
    out: list[dict] = []
    filings = res.get("filings") or {}
    candidates: list[tuple[str, str, str, str]] = []
    for key, form in (("latest_10k", "10-K"), ("latest_10q", "10-Q")):
        f = filings.get(key) or {}
        candidates.append((form, f.get("date"), f.get("url") or "", ""))
    for f in filings.get("recent_8k") or []:
        candidates.append(("8-K", f.get("date"), f.get("url") or "", f.get("items")))
    for form, when, url, items in candidates:
        d = _recent(when, today)
        if d is None:
            continue
        if form == "8-K":
            answer, why = _eight_k_answer(items), WHY["FILING_8K"]
        else:
            answer, why = f"Filed {d.isoformat()}; risk-factor comparison pending", WHY["FILING_10"]
        out.append(H.make(SKILL, "FILING", "alert", f"{sym} filed a {form} on {d.isoformat()}", symbol=sym, discriminator=f"{form}:{d.isoformat()}",
                          detail="", as_of=d.isoformat(), ask=_ASK[form].format(s=sym), url=url, answer=answer, why=why))
    flagged = sorted({str(f.get("code")): str(f.get("message") or "") for f in res.get("flags") or [] if f.get("code") in RED_FLAGS}.items())
    if flagged:
        codes = ",".join(c for c, _ in flagged)
        out.append(H.make(SKILL, "RED_FLAGS", "notice", f"{sym} fundamentals flag {', '.join(c for c, _ in flagged)}", symbol=sym, discriminator=codes,
                          detail="", as_of=str(today), ask=f"What does {sym}'s quality checklist show?",
                          url=H.edgar_url(sym), answer="; ".join(m for _, m in flagged), why=WHY["RED_FLAGS"]))
    return out


def extract(results: dict, ctx: dict) -> list[dict]:
    today: date = ctx["today"]
    out: list[dict] = []
    for sym in sorted(results):
        res = results[sym]
        if isinstance(res, dict):
            out.extend(_symbol_headlines(str(res.get("symbol") or sym).upper(), res, today))
    return out
