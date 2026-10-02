#!/usr/bin/env python3
"""Rebuilds docs/samples/portfolio-brief.json for the README screenshot.

The sample household (HOUSEHOLD.md) goes through the snapshot's real summary math and the rebalancing
headline through the real plan math and headline extractor. The rest of what brief.py adds from live
sources (quotes history, news, events, the other headlines, coverage) is invented by hand below.
No network, no user data.
"""
import importlib.util
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
spec = importlib.util.spec_from_file_location("summary", ROOT / "skills/portfolio-snapshot/scripts/summary.py")
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)

TODAY = date(2026, 9, 15)

# symbol: (name, price, day move, yearly drift, wiggle amplitude, wiggle period in sessions)
SEC = {
    "VTI": ("Vanguard Total Stock Market ETF", 312.00, 0.006, 0.14, 0.035, 70),
    "AAPL": ("Apple Inc.", 232.00, 0.018, 0.10, 0.07, 55),
    "MSFT": ("Microsoft Corp.", 505.00, -0.009, 0.16, 0.05, 60),
    "COST": ("Costco Wholesale Corp.", 915.00, 0.004, 0.08, 0.045, 80),
    "SCHD": ("Schwab US Dividend Equity ETF", 28.50, 0.003, 0.05, 0.03, 90),
    "VXUS": ("Vanguard Total International Stock ETF", 68.00, 0.002, 0.17, 0.03, 75),
    "JNJ": ("Johnson & Johnson", 165.00, -0.014, 0.09, 0.04, 65),
    "VNQ": ("Vanguard Real Estate ETF", 92.00, -0.007, 0.03, 0.04, 85),
    "BND": ("Vanguard Total Bond Market ETF", 74.00, 0.001, 0.02, 0.012, 100),
}

ACCOUNTS = [
    ("sample-brokerage", "Sample Brokerage", "Sample Securities", "Individual", True, 12215.0,
     [("VTI", 220, 52800), ("AAPL", 120, 19200), ("MSFT", 55, 18150), ("COST", 22, 15400), ("SCHD", 400, 10400)]),
    ("sample-roth", "Sample Roth IRA", "Sample Securities", "Roth IRA", False, 3400.0,
     [("VXUS", 600, 34200), ("JNJ", 100, 15800), ("VNQ", 150, 13050)]),
    ("sample-401k", "Sample 401(k)", "Sample Retirement Plan", "401(k)", False, 6100.0,
     [("VTI", 300, 66000), ("BND", 950, 72200)]),
]


def sessions(end: date, n_days: int = 366) -> list[date]:
    d, out = end - timedelta(days=n_days), []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DATES = sessions(TODAY)
N = len(DATES)


def closes(sym: str) -> list[float]:
    _, price, move, drift, amp, period = SEC[sym]
    amp = amp if sym in ("MSFT", "JNJ", "VNQ") else -amp
    prev = price / (1 + move)
    out = []
    for i in range(N - 1):
        k = N - 2 - i  # sessions before the previous close
        out.append(prev * math.exp(-drift * k / 252) * (1 + amp * math.sin(2 * math.pi * k / period)))
    out.append(price)
    return out


HIST = {s: closes(s) for s in SEC}

FUND_SECTORS = {
    "VTI": {"technology": 0.33, "financial_services": 0.13, "healthcare": 0.10, "consumer_cyclical": 0.11,
            "communication_services": 0.09, "industrials": 0.09, "consumer_defensive": 0.05, "energy": 0.03,
            "utilities": 0.025, "realestate": 0.025, "basic_materials": 0.02},
    "VXUS": {"technology": 0.14, "financial_services": 0.22, "healthcare": 0.09, "consumer_cyclical": 0.11,
             "communication_services": 0.06, "industrials": 0.15, "consumer_defensive": 0.07, "energy": 0.05,
             "utilities": 0.03, "realestate": 0.03, "basic_materials": 0.05},
    "SCHD": {"financial_services": 0.09, "healthcare": 0.16, "consumer_defensive": 0.19, "energy": 0.21,
             "industrials": 0.12, "technology": 0.08, "consumer_cyclical": 0.08, "communication_services": 0.05,
             "basic_materials": 0.02},
    "VNQ": {"realestate": 1.0},
    "BND": {},
}
FUND_CLASSES = {
    "VTI": {"stockPosition": 0.995, "cashPosition": 0.005, "bondPosition": 0.0, "otherPosition": 0.0},
    "VXUS": {"stockPosition": 0.98, "cashPosition": 0.015, "bondPosition": 0.0, "otherPosition": 0.005},
    "SCHD": {"stockPosition": 0.998, "cashPosition": 0.002, "bondPosition": 0.0, "otherPosition": 0.0},
    "VNQ": {"stockPosition": 0.98, "cashPosition": 0.02, "bondPosition": 0.0, "otherPosition": 0.0},
    "BND": {"stockPosition": 0.0, "cashPosition": 0.01, "bondPosition": 0.99, "otherPosition": 0.0},
}
INFO = {
    "VTI": ("ETF", "Large Blend", "United States", None,
            "Sample description: an index fund that holds nearly every publicly traded US company, large and small, in one ETF."),
    "AAPL": ("EQUITY", None, "United States", "Technology",
             "Sample description: designs and sells phones, computers, tablets, wearables and the services that run on them."),
    "MSFT": ("EQUITY", None, "United States", "Technology",
             "Sample description: makes operating systems, productivity software and cloud computing services."),
    "COST": ("EQUITY", None, "United States", "Consumer Defensive",
             "Sample description: runs membership warehouse stores selling groceries and general merchandise in bulk."),
    "SCHD": ("ETF", "Large Value", "United States", None,
             "Sample description: an index fund of about 100 US companies screened for a record of paying and growing dividends."),
    "VXUS": ("ETF", "Foreign Large Blend", "United States", None,
             "Sample description: an index fund holding stocks of companies outside the United States, developed and emerging markets."),
    "JNJ": ("EQUITY", None, "United States", "Healthcare",
            "Sample description: develops pharmaceuticals and medical devices."),
    "VNQ": ("ETF", "Real Estate", "United States", None,
            "Sample description: an index fund of US real estate investment trusts that own offices, apartments, warehouses and towers."),
    "BND": ("ETF", "Intermediate Core Bond", "United States", None,
            "Sample description: an index fund of investment-grade US bonds: Treasuries, mortgage-backed and corporate debt."),
}

params = {
    "accounts": [
        {"account_id": aid, "name": name, "institution_name": inst, "account_type": atype, "supports_trading": trade,
         "cash": cash,
         "positions": [{"symbol": {"symbol": s, "description": SEC[s][0]}, "units": u, "price": SEC[s][1],
                        "average_purchase_price": cost / u} for s, u, cost in pos]}
        for aid, name, inst, atype, trade, cash, pos in ACCOUNTS
    ],
    "quotes": {s: {"price": SEC[s][1], "previous_close": HIST[s][-2]} for s in SEC},
    "sectors": {s: (INFO[s][3] if INFO[s][0] == "EQUITY" else "ETF") for s in SEC},
    "events": {"SCHD": {"next_ex_dividend": "2026-09-21"}, "COST": {"next_earnings": "2026-09-22"}},
    "history": {s: [{"date": d.isoformat(), "close": round(c, 4)} for d, c in zip(DATES, HIST[s])] for s in SEC},
    "asset_info": {
        s: {"name": SEC[s][0], "quote_type": INFO[s][0], "category": INFO[s][1], "country": INFO[s][2],
            "sector": INFO[s][3], "fund_sectors": FUND_SECTORS.get(s), "fund_asset_classes": FUND_CLASSES.get(s),
            "summary": INFO[s][4], "website": None}
        for s in SEC
    },
}

res = summary.run_summary(params)

profiles = {}
for s, info in params["asset_info"].items():
    profiles[s] = {k: info.get(k) for k in ("name", "quote_type", "category", "country", "sector", "summary", "website")}
    profiles[s]["bucket"] = summary.asset_bucket(s, info)

price_history = {}
for s in SEC:
    rows = params["history"][s]
    keep = rows[::5]
    if keep[-1] is not rows[-1]:
        keep.append(rows[-1])
    price_history[s] = [{"date": r["date"], "close": round(r["close"], 4)} for r in keep]

news = {
    "AAPL": [
        {"title": "Sample story: Apple shares climb as early reviews of the fall lineup land", "publisher": "Sample Wire",
         "published": "2026-09-15T14:32:00+00:00", "url": "https://example.com/news/apple-fall-lineup-reviews", "summary": ""},
        {"title": "Sample story: What analysts are watching in Apple's services growth", "publisher": "Sample Wire",
         "published": "2026-09-12T11:05:00+00:00", "url": "https://example.com/news/apple-services-watch", "summary": ""},
    ],
    "VTI": [
        {"title": "Sample story: Broad US stocks edge higher ahead of next week's rate decision", "publisher": "Sample Wire",
         "published": "2026-09-15T20:10:00+00:00", "url": "https://example.com/news/us-stocks-edge-higher", "summary": ""},
    ],
    "COST": [
        {"title": "Sample story: Costco August sales preview ahead of fiscal fourth-quarter results", "publisher": "Sample Wire",
         "published": "2026-09-14T16:45:00+00:00", "url": "https://example.com/news/costco-results-preview", "summary": ""},
    ],
    "JNJ": [
        {"title": "Sample story: Johnson & Johnson slips as a drug trial readout is pushed to next year", "publisher": "Sample Wire",
         "published": "2026-09-15T15:20:00+00:00", "url": "https://example.com/news/jnj-trial-readout-delay", "summary": ""},
        {"title": "Sample story: Health-care stocks lag the market for a third session", "publisher": "Sample Wire",
         "published": "2026-09-13T13:00:00+00:00", "url": "https://example.com/news/healthcare-lags", "summary": ""},
    ],
    "MSFT": [
        {"title": "Sample story: Microsoft dips as cloud spending questions resurface", "publisher": "Sample Wire",
         "published": "2026-09-15T17:02:00+00:00", "url": "https://example.com/news/microsoft-cloud-spending", "summary": ""},
    ],
    "VNQ": [],
}
news = {m["symbol"]: news[m["symbol"]] for m in res["movers"]["up"] + res["movers"]["down"]}

# comparison against a saved snapshot on 2026-09-08 (5 sessions back on the same invented series)
idx_before = DATES.index(date(2026, 9, 8))
cash_total = res["totals"]["cash"]
units = {p["symbol"]: p["units"] for p in res["positions"]}
before_syms = {s: round(units[s] * HIST[s][idx_before], 2) for s in SEC}
after_syms = {p["symbol"]: p["market_value"] for p in res["positions"]}
tv_before = round(sum(before_syms.values()) + cash_total, 2)
tv_after = res["totals"]["total_value"]
sym_rows = [{"symbol": s, "before": before_syms[s], "after": after_syms[s], "delta": round(after_syms[s] - before_syms[s], 2),
             "delta_pct": round(after_syms[s] / before_syms[s] - 1, 4)} for s in SEC]
sym_rows.sort(key=lambda r: (-abs(r["delta"]), r["symbol"]))
comparison = {"since": "2026-09-08T21:02:11+00:00", "days": 7,
              "total_value": {"before": tv_before, "after": tv_after, "delta": round(tv_after - tv_before, 2),
                              "delta_pct": round(tv_after / tv_before - 1, 4)},
              "symbols": sym_rows}

# the brief runs plan.py --only-if-breached with the saved targets; same math, same extractor
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_rebalancing  # noqa: E402
from second_opinion.headlines import rebalancing as rebalancing_headlines  # noqa: E402

rebalancing_headline = rebalancing_headlines.extract({"main": gen_rebalancing.plan(0.0, True)}, {"today": TODAY})[0]
rebalancing_headline["status"] = "still"

TODAY_S = TODAY.isoformat()
headlines = [
    {"key": "watchlist:price_below:MSFT:2026-09-15", "code": "price_below", "skill": "watchlist", "severity": "alert", "symbol": "MSFT",
     "title": "MSFT 505.00 is below 510.00", "detail": "", "as_of": TODAY_S, "status": "new",
     "ask": "What on my watchlist moved?", "url": "https://finance.yahoo.com/quote/MSFT",
     "answer": "Now 505.00; rule price_below at 510.0; -3.2% since added, 8.4% below the 52-week high",
     "why": "A price rule you set on your watchlist fired on today's quote."},
    {"key": "portfolio-snapshot:EARNINGS:COST:2026-09-22", "code": "EARNINGS", "skill": "portfolio-snapshot", "severity": "alert", "symbol": "COST",
     "title": "COST reports earnings on 2026-09-22", "detail": "", "as_of": TODAY_S, "status": "new",
     "ask": "What is COST's expected move through earnings?", "url": "https://finance.yahoo.com/quote/COST",
     "answer": "Options price a ±$38.43 (±4.2%) move by 2026-09-25 (ATM IV 27%)",
     "why": "Earnings days bring the largest single-day moves; the options market prices how large."},
    {"key": "market-analysis:CASH_RECORD:-:2026-09-10", "code": "CASH_RECORD", "skill": "market-analysis", "severity": "notice", "symbol": None,
     "title": "Money-fund cash 7412.35 Billions of Dollars is a one-year high (2026-09-10)", "detail": "52-week change 11.4", "as_of": "2026-09-10",
     "status": "new", "ask": "How is the market positioned this week?", "url": "https://fred.stlouisfed.org/series/WRMFNS",
     "answer": "+62 billion over four weeks, +11.4% over a year",
     "why": "Cash parked in money-market funds; a high level is dry powder that has not been put into stocks or bonds."},
    {"key": "market-analysis:DAY:-:2026-09-15", "code": "DAY", "skill": "market-analysis", "severity": "info", "symbol": None,
     "title": "S&P 500 +0.5% · Nasdaq +0.8% · 10y 4.12% · VIX 15.8", "detail": "", "as_of": TODAY_S, "status": "new",
     "ask": "How is the market positioned this week?", "url": "", "answer": "", "why": ""},
    {"key": "portfolio-snapshot:EX_DIVIDEND:SCHD:2026-09-21", "code": "EX_DIVIDEND", "skill": "portfolio-snapshot", "severity": "alert", "symbol": "SCHD",
     "title": "SCHD goes ex-dividend on 2026-09-21", "detail": "", "as_of": TODAY_S, "status": "still",
     "ask": "What is SCHD's next dividend worth to me?", "url": "https://finance.yahoo.com/quote/SCHD",
     "answer": "About $104.00 for your 400 shares (last $0.2600 per share)",
     "why": "You must hold the shares before the ex-dividend date to receive the next payment."},
    rebalancing_headline,
]

coverage = [
    {"skill": "watchlist", "script": "scripts/watchlist.py", "status": "ok", "reason": "", "hint": "", "seconds": 3.1, "headlines": 1},
    {"skill": "market-analysis", "script": "scripts/indices.py", "status": "ok", "reason": "", "hint": "", "seconds": 11.4, "headlines": 2},
    {"skill": "portfolio-snapshot", "script": "", "status": "ok", "reason": "", "hint": "", "seconds": 0.0, "headlines": 2},
    {"skill": "fundamental-research", "script": "scripts/edgar.py", "status": "ok", "reason": "", "hint": "", "seconds": 6.8, "headlines": 0},
    {"skill": "rebalancing", "script": "scripts/plan.py", "status": "ok", "reason": "", "hint": "", "seconds": 4.2, "headlines": 1},
    {"skill": "tax-aware", "script": "scripts/tax-report.py", "status": "skipped", "reason": "the ledger is empty",
     "hint": "import statements with the statement-import skill", "seconds": 0.0, "headlines": 0},
    {"skill": "dividend-income", "script": "scripts/dividends.py", "status": "ok", "reason": "", "hint": "", "seconds": 7.9, "headlines": 0},
    {"skill": "risk-analysis", "script": "scripts/stress.py", "status": "failed", "reason": "timed out after 90s", "hint": "", "seconds": 90.0, "headlines": 0},
    {"skill": "trade-journal", "script": "scripts/journal.py", "status": "skipped", "reason": "the journal is empty",
     "hint": "journal a trade with the trade-journal skill", "seconds": 0.0, "headlines": 0},
    {"skill": "debt-tracker", "script": "scripts/debts.py", "status": "skipped", "reason": "no statements.json",
     "hint": "record a statement with the debt-tracker skill", "seconds": 0.0, "headlines": 0},
    {"skill": "spending", "script": "scripts/spend.py", "status": "ok", "reason": "", "hint": "", "seconds": 1.6, "headlines": 0},
    {"skill": "statement-import", "script": "scripts/ledger.py", "status": "skipped", "reason": "the ledger is empty",
     "hint": "import statements with the statement-import skill", "seconds": 0.0, "headlines": 0},
]

res["flags"].append({"code": "NEWS_UNAVAILABLE", "message": "Yahoo news failed for VNQ (HTTPError: 429 Too Many Requests)"})

out = {
    "as_of": "2026-09-15T21:04:40+00:00",
    "sources": {"holdings": "snaptrade", "quotes": "yahoo", "sectors": "yahoo", "events": "yahoo", "news": "yahoo"},
    **res,
    "news": news,
    "price_history": price_history,
    "profiles": profiles,
    "comparison": comparison,
    "headlines": headlines,
    "coverage": coverage,
    "brief_as_of": "2026-09-15T21:05:12+00:00",
    "brief_seconds": 94.6,
}
# keep the documented key order: snapshot keys, then comparison, then the brief's additions
dest = ROOT / "docs/samples/portfolio-brief.json"
dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {dest}")
