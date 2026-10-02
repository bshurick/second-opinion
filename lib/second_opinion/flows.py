"""Pure market-flow math over rows the network modules already fetched.

Four summaries, none of which touch the network:

``cot_summary(rows_by_code)`` — CFTC Traders in Financial Futures rows
(newest first per contract) become one entry per contract with the net
position of each trader class (asset managers, leveraged funds, dealers,
other reportables, small traders), its week-over-week change, its share of
open interest, and the percentile of the latest net within the weeks
supplied (100 = most net-long of the window, 0 = most net-short).
``weeks_behind`` counts how many weeks older a contract's latest report is
than the newest report in the set: the CFTC omits a contract in weeks its
open interest falls below the reporting threshold, so thin sector futures
can sit months behind.

``etf_flow_summary(series)`` — daily ``{date, nav, aum_usd, shares}``
observations per ETF (oldest first) become creation/redemption flows:
``(shares_t - shares_prev) * nav_t`` between consecutive observations,
summed over the last 1, 5 and 20 observations. Observations, not calendar
days: ``flow_1d_span_days`` says how many calendar days the latest step
spans so a gap in the local series is visible.

``cash_summary(series, observations)`` — a weekly FRED level series (oldest
first) with changes 1, 4, 13 and 52 observations back (a week, a month, a
quarter, a year). WRMFNS is weekly data that the Fed's H.6 release publishes
monthly, so the latest observation can be six weeks old.

``short_volume_summary(rows_by_symbol)`` — FINRA daily short-sale rows
(oldest first) become the latest short-volume ratio and its average over
the days supplied.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from second_opinion.market import SECTOR_ETFS

# CFTC contract codes the overview tracks: code -> (label, group). Names come
# from the report itself; unknown codes keep the report name under "other".
CONTRACTS: dict[str, tuple[str, str]] = {
    "13874A": ("S&P 500 e-mini", "index"),
    "209742": ("Nasdaq 100 mini", "index"),
    "239742": ("Russell 2000 e-mini", "index"),
    "124603": ("Dow Jones ($5)", "index"),
    "13874I": ("Technology sector", "sector"),
    "13874C": ("Financials sector", "sector"),
    "138749": ("Energy sector", "sector"),
    "13874E": ("Health care sector", "sector"),
    "13874F": ("Industrials sector", "sector"),
    "138747": ("Consumer discretionary sector", "sector"),
    "138748": ("Consumer staples sector", "sector"),
    "13874J": ("Utilities sector", "sector"),
    "13874H": ("Materials sector", "sector"),
    "13874R": ("Real estate sector", "sector"),
    "13874P": ("Communication services sector", "sector"),
    "043602": ("10-year Treasury note", "rates"),
    "042601": ("2-year Treasury note", "rates"),
    "020604": ("Ultra Treasury bond", "rates"),
    "098662": ("US dollar index", "fx"),
    "1170E1": ("VIX futures", "volatility"),
    "133741": ("Bitcoin", "crypto"),
}
_GROUP_ORDER = {"index": 0, "sector": 1, "rates": 2, "fx": 3, "volatility": 4, "crypto": 5, "other": 9}

# trader class -> (long field, short field, long change field, short change field)
_CLASSES: dict[str, tuple[str, str, str, str]] = {
    "asset_managers": ("asset_mgr_positions_long", "asset_mgr_positions_short", "change_in_asset_mgr_long", "change_in_asset_mgr_short"),
    "leveraged_funds": ("lev_money_positions_long", "lev_money_positions_short", "change_in_lev_money_long", "change_in_lev_money_short"),
    "dealers": ("dealer_positions_long_all", "dealer_positions_short_all", "change_in_dealer_long_all", "change_in_dealer_short_all"),
    "other_reportables": ("other_rept_positions_long", "other_rept_positions_short", "change_in_other_rept_long", "change_in_other_rept_short"),
    "small_traders": ("nonrept_positions_long_all", "nonrept_positions_short_all", "change_in_nonrept_long_all", "change_in_nonrept_short_all"),
}

CASH_SERIES = {"WRMFNS": ("Retail Money Market Funds", "billions of dollars, weekly")}
_CASH_WINDOWS = (("1w", 1), ("4w", 4), ("13w", 13), ("52w", 52))


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _pct(part: float | None, whole: float | None, digits: int = 2) -> float | None:
    if part is None or not whole:
        return None
    return round(part / whole * 100, digits)


def _percentile(values: list[int], latest: int) -> float | None:
    """Share of the other values the latest one exceeds; None with fewer than two values."""
    others = values[1:]
    if not others:
        return None
    below = sum(1 for v in others if v < latest)
    ties = sum(1 for v in others if v == latest)
    return round((below + ties / 2) / len(others) * 100, 1)


def _report_date(row: dict[str, Any]) -> str:
    return str(row.get("report_date_as_yyyy_mm_dd") or "")[:10]


def _contract(code: str, rows: list[dict[str, Any]], history: bool = False) -> dict[str, Any]:
    rows = sorted(rows, key=_report_date, reverse=True)
    latest = rows[0]
    name = str(latest.get("contract_market_name") or code).strip()
    label, group = CONTRACTS.get(code, (name, "other"))
    oi = _int(latest.get("open_interest_all"))
    classes: dict[str, Any] = {}
    for cls, (f_long, f_short, f_dlong, f_dshort) in _CLASSES.items():
        nets = [(_int(r.get(f_long)) or 0) - (_int(r.get(f_short)) or 0) for r in rows]
        long_, short = _int(latest.get(f_long)), _int(latest.get(f_short))
        classes[cls] = {
            "long": long_,
            "short": short,
            "net": nets[0],
            "net_change": nets[0] - nets[1] if len(nets) > 1 else None,
            "net_pct_oi": _pct(nets[0], oi, 1),
            "percentile": _percentile(nets, nets[0]),
            "long_change": _int(latest.get(f_dlong)),
            "short_change": _int(latest.get(f_dshort)),
        }
    out = {
        "code": code,
        "name": name,
        "label": label,
        "group": group,
        "report_date": _report_date(latest),
        "open_interest": oi,
        "open_interest_change": _int(latest.get("change_in_open_interest_all")),
        "weeks": len(rows),
        "classes": classes,
    }
    if history:
        out["history"] = [
            {"date": _report_date(r), "open_interest": _int(r.get("open_interest_all")), **{cls: (_int(r.get(f[0])) or 0) - (_int(r.get(f[1])) or 0) for cls, f in _CLASSES.items()}}
            for r in reversed(rows)
        ]
    return out


def cot_summary(rows_by_code: dict[str, list[dict[str, Any]]], history: bool = False) -> list[dict[str, Any]]:
    """One entry per contract with rows, ordered index, sector, rates, fx, volatility, crypto, other, then by label.

    With ``history`` each contract also carries its weekly net position per trader class, oldest first."""
    out = [_contract(code, rows, history) for code, rows in rows_by_code.items() if rows]
    newest = max((c["report_date"] for c in out if c["report_date"]), default=None)
    for c in out:
        behind = _span_days(c["report_date"], newest) if newest and c["report_date"] else None
        c["weeks_behind"] = None if behind is None else behind // 7
    out.sort(key=lambda c: (_GROUP_ORDER.get(c["group"], 9), c["label"]))
    return out


def _flow_sum(obs: list[dict[str, Any]], steps: int) -> float | None:
    if len(obs) < 2:
        return None
    total = 0.0
    for i in range(len(obs) - 1, max(len(obs) - 1 - steps, 0), -1):
        total += (obs[i]["shares"] - obs[i - 1]["shares"]) * obs[i]["nav"]
    return round(total, 2)


def _span_days(a: str, b: str) -> int | None:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except ValueError:
        return None


def etf_flow_summary(series: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Flows per ETF from the local shares-outstanding series; ETFs with flows first, biggest 5-observation inflow first."""
    out = []
    for ticker, obs in series.items():
        obs = sorted((o for o in obs if o.get("shares") is not None and o.get("nav") is not None), key=lambda o: o["date"])
        if not obs:
            continue
        latest = obs[-1]
        aum = latest.get("aum_usd")
        f1, f5, f20 = _flow_sum(obs, 1), _flow_sum(obs, 5), _flow_sum(obs, 20)
        out.append({
            "ticker": ticker,
            "name": SECTOR_ETFS.get(ticker, "SPDR S&P 500 ETF" if ticker == "SPY" else ticker),
            "as_of": latest["date"],
            "nav": latest["nav"],
            "aum_usd": aum,
            "shares": latest["shares"],
            "observations": len(obs),
            "first_observation": obs[0]["date"],
            "flow_1d_usd": f1,
            "flow_1d_pct_aum": _pct(f1, aum),
            "flow_1d_span_days": _span_days(obs[-2]["date"], latest["date"]) if len(obs) > 1 else None,
            "flow_5d_usd": f5,
            "flow_5d_pct_aum": _pct(f5, aum),
            "flow_20d_usd": f20,
            "flow_20d_pct_aum": _pct(f20, aum),
        })
    out.sort(key=lambda r: (r["flow_5d_usd"] is None, -(r["flow_5d_usd"] or 0)))
    return out


def cash_summary(series: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    obs = sorted((o for o in observations if o.get("value") is not None), key=lambda o: o["date"])
    name, unit = CASH_SERIES.get(series, (series, "as published"))
    out: dict[str, Any] = {"series": series, "name": name, "unit": unit, "latest": None, "date": None}
    for label, _ in _CASH_WINDOWS:
        out[f"change_{label}"] = None
    out["change_52w_pct"] = None
    out["observations"] = [{"date": o["date"], "value": o["value"]} for o in obs]
    if not obs:
        return out
    latest = obs[-1]["value"]
    out["latest"], out["date"] = latest, obs[-1]["date"]
    for label, n in _CASH_WINDOWS:
        if len(obs) > n:
            out[f"change_{label}"] = round(latest - obs[-1 - n]["value"], 2)
    if len(obs) > 52 and obs[-53]["value"]:
        out["change_52w_pct"] = round((latest / obs[-53]["value"] - 1) * 100, 2)
    return out


def short_volume_summary(rows_by_symbol: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out = []
    for symbol, rows in rows_by_symbol.items():
        rows = sorted((r for r in rows if r.get("total")), key=lambda r: r["date"])
        if not rows:
            out.append({"symbol": symbol, "date": None, "short_ratio": None, "short_ratio_avg": None, "ratio_vs_avg": None, "short_volume": None, "total_volume": None, "days": 0})
            continue
        ratios = [r["short"] / r["total"] * 100 for r in rows]
        latest, avg = round(ratios[-1], 2), round(sum(ratios) / len(ratios), 2)
        out.append({"symbol": symbol, "date": rows[-1]["date"], "short_ratio": latest, "short_ratio_avg": avg, "ratio_vs_avg": round(latest - avg, 2), "short_volume": rows[-1]["short"], "total_volume": rows[-1]["total"], "days": len(rows)})
    return out
