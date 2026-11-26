#!/usr/bin/env python3
"""Rebuilds docs/samples/market-indices.json and market-flows.json for the README screenshot.

Every figure is invented: seeded random walks shaped like indices.py and flows.py output, dated to the
sample household's as-of date (2026-09-15). Nothing is fetched. The trend statistics (gaps against the
50-, 100- and 200-week averages and their percentiles) are computed from the invented weekly history the
same way indices.py computes them from real closes, so the page reads as one consistent market.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
AS_OF = date(2026, 9, 15)       # a Tuesday: prices to its close
REPORT = date(2026, 9, 8)       # the CFTC report released the Friday before
ETF_AS_OF = date(2026, 9, 14)
CASH_DATE = date(2026, 8, 3)
rng = random.Random(20260915)


def business_days(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def walk(n: int, start: float, drift: float, vol: float, end: float | None = None) -> list[float]:
    xs = [start]
    for _ in range(n - 1):
        xs.append(xs[-1] * (1 + drift + rng.gauss(0, vol)))
    if end is not None:  # rescale so the walk finishes at the chosen level
        xs = [x * end / xs[-1] for x in xs]
    return xs


def level_walk(n: int, start: float, end: float, vol: float) -> list[float]:
    """An additive walk for yields and rates, bent to finish at end."""
    xs = [start]
    for _ in range(n - 1):
        xs.append(xs[-1] + rng.gauss(0, vol))
    return [round(x + (end - xs[-1]) * i / (n - 1), 3) for i, x in enumerate(xs)]


def pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 4)


DAYS = business_days(AS_OF, 253)
ISO = [d.isoformat() for d in DAYS]


def row(symbol: str, name: str, closes: list[float], dp: int = 2) -> dict:
    closes = [round(c, dp) for c in closes]
    return {"symbol": symbol, "name": name, "last": closes[-1], "day_change_pct": pct(closes[-1], closes[-2]),
            "week_change_pct": pct(closes[-1], closes[-6]), "history": [[d, c] for d, c in zip(ISO, closes)],
            "high_1y": max(closes), "low_1y": min(closes), "change_1y_pct": pct(closes[-1], closes[0])}


def tilt_week(closes: list[float], change: float) -> list[float]:
    """Bend the last five sessions so the week ends `change` (a fraction) from the close before them."""
    base = closes[-6]
    return closes[:-5] + [base * (1 + change * k / 5 + rng.gauss(0, 0.0015)) for k in range(1, 6)]


def sma(xs: list[float], n: int, i: int) -> float | None:
    return sum(xs[i - n + 1:i + 1]) / n if i >= n - 1 else None


# --- the S&P 500: weekly closes back far enough for 20 years of 200-week averages -------------------
# The first seeded history whose gaps look like an ordinary market: 200-week neutral near the upper
# middle of its range, 100- and 50-week neutral, so the sample page shows no extreme it would explain.
WEEKS = (AS_OF - date(1950, 1, 6)).days // 7 + 1  # weekly closes from the first week of 1950, as indices.py uses
END = 6612.4
week_ends = [AS_OF - timedelta(days=7 * (WEEKS - 1 - i)) for i in range(WEEKS)]


def gap_rank(xs: list[float], n: int) -> int:
    gaps = [xs[i] / sma(xs, n, i) - 1 for i in range(n - 1, len(xs))]
    return round(sum(1 for x in gaps if x < gaps[-1]) / len(gaps) * 100)


for seed in range(1, 5000):
    rng.seed(seed)
    weekly = walk(WEEKS, 17.0, 0.0017, 0.021, end=END)
    if 55 <= gap_rank(weekly, 200) <= 75 and 35 <= gap_rank(weekly, 100) <= 65 and 30 <= gap_rank(weekly, 50) <= 60:
        break
rng.seed(20260915)


def trend_block() -> dict:
    out = {"symbol": "^GSPC", "as_of": AS_OF.isoformat(), "last": weekly[-1], "history_from": week_ends[0].isoformat(), "weeks": WEEKS}
    for n in (50, 100, 200):
        gaps = [(weekly[i] / sma(weekly, n, i) - 1) * 100 for i in range(n - 1, WEEKS)]
        g = gaps[-1]
        s = sorted(gaps)
        p = round(sum(1 for x in gaps if x < g) / len(gaps) * 100)
        q = lambda f: round(s[int(f * (len(s) - 1))], 2)  # noqa: E731
        out[f"wma_{n}"] = {"average": round(sma(weekly, n, WEEKS - 1), 2), "gap_pct": round(g, 2), "percentile": p,
                           "level": "extended" if p >= 80 else "depressed" if p <= 20 else "neutral",
                           "median_gap_pct": q(0.5), "share_below_pct": round(sum(1 for x in gaps if x < 0) / len(gaps) * 100),
                           "band_low_pct": q(0.2), "band_high_pct": q(0.8), "gaps_from": week_ends[n - 1].isoformat()}
    out["series"] = [{"date": week_ends[i].isoformat(), "close": round(weekly[i], 2), **{f"wma_{n}": round(sma(weekly, n, i), 2) for n in (50, 100, 200)}}
                     for i in range(WEEKS - 1040, WEEKS)]
    return out


trend = trend_block()
# a year of daily closes that lands on the last weekly close; each day carries its week's averages
spx_daily = tilt_week(walk(len(DAYS), weekly[-53], 0.0004, 0.009, end=weekly[-1] / 1.0121), 0.0121)
spx_daily = [c * weekly[-1] / spx_daily[-1] for c in spx_daily]
trend["daily"] = []
for d, c in zip(DAYS, spx_daily):
    wk = next(i for i in range(WEEKS) if week_ends[i] >= d)
    trend["daily"].append({"date": d.isoformat(), "close": round(c, 2), **{f"wma_{n}": round(sma(weekly, n, wk), 2) for n in (50, 100, 200)}})
trend["levels"] = {"extended": "percentile >= 80", "neutral": "between 20 and 80", "depressed": "percentile <= 20"}
trend["note"] = "Sample data: invented weekly closes, ranked the way indices.py ranks real ones."

# the week's story in the sample: large caps up, led by the Nasdaq; small caps slightly down
vix = tilt_week([max(11.0, v) for v in level_walk(len(DAYS), 18.5, 16.8, 0.7)], -0.06)
indices = [row("^GSPC", "S&P 500", spx_daily), row("^DJI", "Dow Jones", tilt_week(walk(len(DAYS), 41000, 0.0003, 0.008, end=45210.6), 0.0042)),
           row("^IXIC", "Nasdaq Composite", tilt_week(walk(len(DAYS), 17800, 0.0005, 0.012, end=21980.3), 0.0194)),
           row("^RUT", "Russell 2000", tilt_week(walk(len(DAYS), 2150, 0.0003, 0.013, end=2391.7), -0.0063)), row("^VIX", "VIX", vix)]

SECTORS = [("XLK", "Technology", 250.0, [("AAPL", "Apple Inc", 14.2), ("MSFT", "Microsoft Corp", 13.1), ("NVDA", "NVIDIA Corp", 12.8)]),
           ("XLF", "Financials", 52.0, [("BRK-B", "Berkshire Hathaway Inc", 12.4), ("JPM", "JPMorgan Chase & Co", 10.2), ("V", "Visa Inc", 7.6)]),
           ("XLV", "Health Care", 146.0, [("LLY", "Eli Lilly and Co", 12.9), ("UNH", "UnitedHealth Group Inc", 7.8), ("JNJ", "Johnson & Johnson", 7.1)]),
           ("XLE", "Energy", 88.0, [("XOM", "Exxon Mobil Corp", 22.6), ("CVX", "Chevron Corp", 16.4), ("COP", "ConocoPhillips", 7.5)]),
           ("XLI", "Industrials", 140.0, [("GE", "GE Aerospace", 6.1), ("CAT", "Caterpillar Inc", 4.9), ("RTX", "RTX Corp", 4.6)]),
           ("XLY", "Consumer Discretionary", 215.0, [("AMZN", "Amazon.com Inc", 22.3), ("TSLA", "Tesla Inc", 15.8), ("HD", "Home Depot Inc", 6.7)]),
           ("XLP", "Consumer Staples", 81.0, [("COST", "Costco Wholesale Corp", 10.1), ("WMT", "Walmart Inc", 9.8), ("PG", "Procter & Gamble Co", 9.2)]),
           ("XLU", "Utilities", 79.0, [("NEE", "NextEra Energy Inc", 11.3), ("SO", "Southern Co", 7.9), ("DUK", "Duke Energy Corp", 7.2)]),
           ("XLB", "Materials", 90.0, [("LIN", "Linde PLC", 16.8), ("SHW", "Sherwin-Williams Co", 6.4), ("ECL", "Ecolab Inc", 5.2)]),
           ("XLRE", "Real Estate", 41.0, [("PLD", "Prologis Inc", 9.3), ("AMT", "American Tower Corp", 8.7), ("EQIX", "Equinix Inc", 7.4)]),
           ("XLC", "Communication Services", 98.0, [("META", "Meta Platforms Inc", 21.5), ("GOOGL", "Alphabet Inc", 11.9), ("NFLX", "Netflix Inc", 6.2)])]
# the week's story in the sample: technology and discretionary lead, energy and staples lag
WEEK_TILT = {"XLK": 0.030, "XLY": 0.022, "XLC": 0.012, "XLF": 0.006, "XLI": 0.004, "XLB": -0.002, "XLRE": -0.006, "XLU": -0.008, "XLV": -0.011, "XLP": -0.016, "XLE": -0.027}
sectors = []
for sym, name, end, top in SECTORS:
    r = row(sym, name, tilt_week(walk(len(DAYS), end * 0.86, 0.0004, 0.011, end=end), WEEK_TILT[sym]))
    r["top_holdings"] = [{"symbol": s, "name": n, "weight_pct": w} for s, n, w in top]
    sectors.append(r)

rates = [row("^IRX", "13-week T-bill", level_walk(len(DAYS), 4.30, 3.912, 0.01), 3), row("^FVX", "5-year Treasury", level_walk(len(DAYS), 3.95, 3.884, 0.03), 3),
         row("^TNX", "10-year Treasury", level_walk(len(DAYS), 4.25, 4.182, 0.03), 3), row("^TYX", "30-year Treasury", level_walk(len(DAYS), 4.55, 4.766, 0.03), 3)]
macro = {"gold": row("GC=F", "Gold", walk(len(DAYS), 2900, 0.0007, 0.01, end=3612.0)), "dollar": row("DX-Y.NYB", "US Dollar Index", walk(len(DAYS), 104, -0.0001, 0.003, end=97.84), 3),
         "oil": row("CL=F", "WTI Crude Oil", walk(len(DAYS), 70, 0.0, 0.018, end=63.41)), "bitcoin": row("BTC-USD", "Bitcoin", walk(len(DAYS), 72000, 0.0008, 0.03, end=112430.0)),
         "vix_3m": row("^VIX3M", "VIX 3-Month", walk(len(DAYS), 19.0, 0.0, 0.035, end=21.6))}
last = {r["symbol"]: r["last"] for r in rates}


def fred(series: str, label: str, start: float, end: float, vol: float) -> dict:
    weeks = [AS_OF - timedelta(days=7 * i) for i in range(1040, 52, -1)]
    pts = level_walk(len(weeks) + len(DAYS), start, end, vol)
    return {"series": series, "label": label, "points": [[d.isoformat(), v] for d, v in zip(weeks + DAYS, pts)]}


indices_out = {
    "as_of": f"{AS_OF.isoformat()}T21:10:00+00:00", "indices": indices, "sectors": sectors, "rates": rates, "macro": macro,
    "spreads": {"10y_13w": round(last["^TNX"] - last["^IRX"], 3), "5y_13w": round(last["^FVX"] - last["^IRX"], 3),
                "30y_5y": round(last["^TYX"] - last["^FVX"], 3), "30y_13w": round(last["^TYX"] - last["^IRX"], 3)},
    "breadth": {"rsp_spy_1m": -1.84, "rsp_spy_3m": -3.12, "sectors_above_50sma": 6, "sectors_total": 11, "note": "proxies, not full market breadth"},
    "vix_percentile_1y": round(sum(1 for v in vix if v < vix[-1]) / len(vix), 4), "trend": trend,
    "interest_rates": {"series": [fred("DFF", "Fed funds", 5.2, 4.33, 0.04), fred("DGS2", "2-yr Treasury", 4.8, 3.92, 0.05),
                                  fred("DGS10", "10-yr Treasury", 4.6, 4.18, 0.05), fred("MORTGAGE30US", "30-yr mortgage", 6.4, 6.35, 0.05)], "unavailable": []},
}

# --- flows: CFTC positioning by trader class, SPDR fund flows, retail money-fund cash -----------------
CONTRACTS = [("124603", "DJIA x $5", "Dow Jones ($5)", "index", 85000), ("209742", "NASDAQ MINI", "Nasdaq 100 mini", "index", 290000),
             ("239742", "RUSSELL E-MINI", "Russell 2000 e-mini", "index", 440000), ("13874A", "E-MINI S&P 500", "S&P 500 e-mini", "index", 2050000),
             ("13874P", "E-MINI S&P COMMUNICATION INDEX", "Communication services sector", "sector", 16000), ("138747", "E-MINI S&P CONSUMER DISC INDEX", "Consumer discretionary sector", "sector", 8000),
             ("138748", "E-MINI S&P CONSU STAPLES INDEX", "Consumer staples sector", "sector", 36000), ("138749", "E-MINI S&P ENERGY INDEX", "Energy sector", "sector", 29000),
             ("13874C", "E-MINI S&P FINANCIAL INDEX", "Financials sector", "sector", 64000), ("13874E", "E-MINI S&P HEALTH CARE INDEX", "Health care sector", "sector", 15000),
             ("13874F", "E-MINI S&P INDUSTRIAL INDEX", "Industrials sector", "sector", 13000), ("13874H", "E-MINI S&P MATERIALS INDEX", "Materials sector", "sector", 14000),
             ("13874I", "E-MINI S&P TECHNOLOGY INDEX", "Technology sector", "sector", 14000), ("13874J", "E-MINI S&P UTILITIES INDEX", "Utilities sector", "sector", 30000),
             ("043602", "UST 10Y NOTE", "10-year Treasury note", "rates", 6200000), ("042601", "UST 2Y NOTE", "2-year Treasury note", "rates", 4400000),
             ("020604", "ULTRA UST BOND", "Ultra Treasury bond", "rates", 1900000), ("098662", "USD INDEX", "US dollar index", "fx", 32000),
             ("1170E1", "VIX FUTURES", "VIX futures", "volatility", 360000), ("133741", "BITCOIN", "Bitcoin", "crypto", 26000)]
# structural lean of each class as a share of open interest: asset managers long, leveraged funds short
LEAN = {"asset_managers": 0.30, "leveraged_funds": -0.12, "dealers": -0.20, "other_reportables": 0.0, "small_traders": 0.04}
# the sample's crowded readings: [(code, class, where in the window)], 0 = the window's low, 1 = its high
CROWD = {("13874A", "leveraged_funds"): 1.0, ("13874A", "asset_managers"): 0.06, ("209742", "small_traders"): 0.98,
         ("043602", "asset_managers"): 1.0, ("043602", "leveraged_funds"): 0.0, ("13874I", "leveraged_funds"): 0.08, ("1170E1", "leveraged_funds"): 0.04}
report_weeks = [REPORT - timedelta(days=7 * (51 - i)) for i in range(52)]
contracts = []
for code, name, label, group, oi in CONTRACTS:
    hist = {k: [] for k in LEAN}
    for k, lean in LEAN.items():
        xs = level_walk(52, lean * oi, lean * oi, 0.012 * oi)
        if (code, k) in CROWD:  # set the last week where the sample wants it within the window's range
            lo, hi = min(xs[:-1]), max(xs[:-1])
            f = CROWD[(code, k)]
            xs[-1] = lo - 0.02 * abs(lo) if f <= 0.0 else hi + 0.02 * abs(hi) if f >= 1.0 else lo + f * (hi - lo)
        else:  # every other reading sits in the middle of its window, so only the planned ones are crowded
            lo, hi = min(xs[:-1]), max(xs[:-1])
            xs[-1] = lo + rng.uniform(0.3, 0.7) * (hi - lo)
        hist[k] = [round(x) for x in xs]
    classes = {}
    for k, xs in hist.items():
        net = xs[-1]
        long_ = round(abs(net) + 0.2 * oi * (abs(LEAN[k]) + 0.05)) if net >= 0 else round(0.2 * oi * (abs(LEAN[k]) + 0.05))
        short = long_ - net
        classes[k] = {"long": long_, "short": short, "net": net, "net_change": net - xs[-2], "net_pct_oi": round(net / oi * 100, 1),
                      "percentile": round(sum(1 for x in xs if x < net) / (len(xs) - 1) * 100, 1), "long_change": None, "short_change": None}
    contracts.append({"code": code, "name": name, "label": label, "group": group, "report_date": REPORT.isoformat(), "open_interest": oi,
                      "open_interest_change": round(rng.gauss(0, 0.01) * oi), "weeks": 52, "classes": classes, "weeks_behind": 0,
                      "history": [{"date": d.isoformat(), "open_interest": oi, **{k: hist[k][i] for k in hist}} for i, d in enumerate(report_weeks)]})

FUND_FLOW = {"SPY": (680e9, 4.1e9, 9.6e9), "XLK": (88e9, 1.9e9, 3.4e9), "XLF": (52e9, 0.4e9, -0.6e9), "XLV": (36e9, -0.5e9, -1.1e9), "XLE": (27e9, -0.9e9, -1.6e9),
             "XLI": (23e9, 0.2e9, 0.3e9), "XLY": (22e9, 0.6e9, 0.9e9), "XLP": (16e9, -0.3e9, -0.2e9), "XLU": (19e9, 0.1e9, 0.5e9), "XLB": (5.4e9, -0.1e9, 0.0),
             "XLRE": (7.6e9, 0.05e9, 0.1e9), "XLC": (24e9, 0.3e9, 0.8e9)}
nav = {"SPY": 661.5, **{s["symbol"]: s["last"] for s in sectors}}
names = {"SPY": "SPDR S&P 500 ETF", **{s["symbol"]: s["name"] for s in sectors}}
funds = []
for t, (aum, f5, f20) in FUND_FLOW.items():
    f1 = f5 * 0.3
    funds.append({"ticker": t, "name": names[t], "as_of": ETF_AS_OF.isoformat(), "nav": nav[t], "aum_usd": aum, "shares": round(aum / nav[t]),
                  "observations": 58, "first_observation": "2026-06-22",
                  "flow_1d_usd": f1, "flow_1d_pct_aum": round(f1 / aum * 100, 2), "flow_1d_from": "2026-09-11", "flow_1d_span_days": 3,
                  "flow_5d_usd": f5, "flow_5d_pct_aum": round(f5 / aum * 100, 2), "flow_5d_from": "2026-09-05", "flow_5d_span_days": 9,
                  "flow_20d_usd": f20, "flow_20d_pct_aum": round(f20 / aum * 100, 2), "flow_20d_from": "2026-08-15", "flow_20d_span_days": 30})

cash_obs = level_walk(53, 2930.0, 3009.0, 7.0)
cash_dates = [CASH_DATE - timedelta(days=7 * (52 - i)) for i in range(53)]
flows_out = {
    "as_of": "2026-09-15T21:12:00Z",
    "positioning": {"report_date": REPORT.isoformat(), "weeks": 52, "contracts": contracts, "missing": []},
    "etf_flows": {"as_of": ETF_AS_OF.isoformat(), "funds": funds, "unavailable": [], "series_file": "etf-shares.json"},
    "cash": {"series": "WRMFNS", "name": "Retail Money Market Funds", "unit": "billions of dollars, weekly", "latest": cash_obs[-1], "date": CASH_DATE.isoformat(),
             "change_1w": round(cash_obs[-1] - cash_obs[-2], 1), "change_4w": round(cash_obs[-1] - cash_obs[-5], 1), "change_13w": round(cash_obs[-1] - cash_obs[-14], 1),
             "change_52w": round(cash_obs[-1] - cash_obs[0], 1), "change_52w_pct": round((cash_obs[-1] / cash_obs[0] - 1) * 100, 2),
             "observations": [{"date": d.isoformat(), "value": round(v, 1)} for d, v in zip(cash_dates, cash_obs)]},
    "sources": {"positioning": "Sample data: invented positions shaped like the CFTC Traders in Financial Futures report",
                "etf_flows": "Sample data: invented flows shaped like State Street SPDR shares outstanding",
                "cash": "Sample data: invented balances shaped like FRED series WRMFNS"},
    "notes": ["Sample data: every figure on this page is invented for the README screenshot.",
              "Positioning is futures only: it shows how each trader class is positioned, not cash-equity ownership."],
}

(HERE / "market-indices.json").write_text(json.dumps(indices_out, indent=1) + "\n")
(HERE / "market-flows.json").write_text(json.dumps(flows_out, indent=1) + "\n")
