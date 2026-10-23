#!/usr/bin/env python3
"""Usage: picks.py save-deep SYMBOL (--case DIR | --page FILE) [--thesis TEXT] [--source URL] [--added-price P] [--date YYYY-MM-DD] [--base-end YYYY-MM-DD]
       picks.py save-light SYMBOL --in FILE [--date YYYY-MM-DD]
       picks.py list
       picks.py remove SYMBOL
       picks.py check SYMBOL [--release FILE] [--segments FILE] [--evidence FILE] [--exclude SEG,SEG] [--record]
       picks.py due [--move R]
       picks.py summary

Picks kept for re-checking, in ``picks.json`` under the plugin data dir, with each pick's baseline
in ``picks/SYMBOL-DATE.json`` beside it, so they outlive the session scratchpad.

``save-deep`` stores a deep valuation as the baseline: ``--case`` reads the case folder's
``page.json`` (and ``model.json`` when present, which pins the base-year revenue); ``--page`` reads
a rendered deep page's HTML and takes its embedded ``window.DATA`` (how a pick is recovered from its
published page once the folder is gone). ``added_price`` defaults to the valuation's price. Saving a
new valuation over an existing pick keeps its ``added`` date and ``added_price`` unless ``--date`` or
``--added-price`` is given, so "since added" still measures from the original pick.
``save-light`` stores a funnel pick: the input file holds {"thesis", "preset", "fair_values":
{"bear", "base", "bull"}, "added_price"?}; the script measures ``metrics_at_pick`` (TTM revenue
growth and operating margin) from EDGAR. Saving again replaces the baseline and keeps the checks.
Both saves fetch the next earnings date (best effort).

``check`` gathers the actuals from SEC EDGAR company facts (through the fundamental-research
skill's fundamentals.py) and today's price, and runs track_math.py: every reported fiscal year
(keyed by period end, with when it was first filed), the four latest discrete quarters as the TTM
(the latest fiscal year when no quarterly figures exist), and the latest quarter already reported on
the valuation date (``known_at_baseline``). track_math.py tells from them which year the model
started from. ``--base-end`` on save-deep sets that year's end outright, and ``--exclude`` leaves
out segments not in reported results yet (an acquisition that has not closed); with ``--record``
the exclusion is kept on the pick for later checks (``--exclude ""`` clears it). ``--segments`` adds
segment actuals read from the 10-Q segment note, ``--evidence`` dated findings on the watch items
(both JSON files in track_math.py's shapes). ``--record`` appends the check to the pick and moves
``next_earnings`` on, unless the quarter that earnings date reported is not in EDGAR yet
(``awaiting_filing``).

``--release`` rolls the TTM forward one quarter from an earnings release (8-K Exhibit 99.1) before
the 10-Q reaches EDGAR. The file holds the quarter after EDGAR's latest, in the company's dollars:
{"period_end", "date", "source", "revenue", "revenue_year_ago", "operating_income"?,
"operating_income_year_ago"?, "net_income"?, "net_income_year_ago"?, "equity_year_ago"?}. The new
TTM is EDGAR's TTM less the year-ago quarter plus the released one; operating income (and net
income) roll only when both quarters are given, else they are left out; ``equity_year_ago`` is
equity at the year-ago quarter end, the base for ROE. The result carries PRESS_RELEASE_FIGURES and
``actuals.ttm.basis`` "press_release"; a recorded check keeps ``basis`` and stays
``awaiting_filing``, so the 10-Q re-check is still due. A release for a quarter EDGAR already has
is ignored (RELEASE_IN_EDGAR); one that is not the next quarter is bad input. Deep picks only.

``due`` (network) lists the picks with a 10-Q or 10-K filed after their last check (or since they
were added), or whose price moved ``--move`` (default 0.15) or more since then. ``summary`` (no
network; for the SessionStart hook) prints plain text: the picks whose stored earnings date has
passed since their last check, those still awaiting the 10-Q, those whose price in the watchlist's
last check moved 15% or more since their last check, and those whose price crossed into a new price
level (track_math.py's ``price_level``: past the hurdle price, above the central value, above every
scenario, or below every scenario) since their last check or, before any check, since the added
price. ``due`` adds the same crossing (PRICE_LEVEL) at live prices, and each recorded check keeps
its ``price_level``. It prints nothing when no pick is
saved, and always exits 0.

Output (JSON, except summary): save-* {"pick", "baseline_path"}; list {"picks"}; check {"symbol",
"kind", "pick", "since_added", "actuals", "result", "recorded"}; due {"due": [{"symbol",
"reasons"}], "not_due", "flags"}. Exit codes: 0, 2 (bad input, unknown pick, a page without
window.DATA), 4 (SKILL_MISSING: fundamental-research not installed), 5 (EDGAR or Yahoo), 6.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))
sys.path.insert(0, str(_HERE))

import track_math  # noqa: E402
from second_opinion import brokerage, edgar, ledger, market, output  # noqa: E402
from second_opinion.errors import ApiError, ConfigError, InvalidInput  # noqa: E402

PICKS_FILE = "picks.json"
BASELINE_DIR = "picks"
WATCHLIST_LAST_CHECK = "watchlist-last-check.json"
FUNDAMENTALS_SCRIPT = _HERE.parents[1] / "fundamental-research" / "scripts" / "fundamentals.py"
DEFAULT_MOVE = 0.15
TTM_SPAN = (250, 300)  # days between the first and last period ends of four consecutive quarters
YEAR_TOLERANCE = 15
REPORT_LAG_DAYS = 100  # a quarter reported on an earnings date ended no more than this long before it
NEXT_QUARTER_DAYS = (80, 100)  # a release's quarter end after EDGAR's latest one


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"picks.py: {message}")


# --- store ---------------------------------------------------------------------------------


def data_dir() -> Path:
    return ledger.ledger_path().parent


def picks_path() -> Path:
    return data_dir() / PICKS_FILE


def load() -> dict:
    path = picks_path()
    if not path.is_file():
        return {"picks": []}
    try:
        book = json.loads(path.read_text())
    except ValueError as exc:
        raise ApiError(f"picks at {path} is not valid JSON", code="LEDGER_CORRUPT", hint=f"move or delete {path}") from exc
    if not isinstance(book, dict) or not isinstance(book.get("picks"), list):
        raise ApiError(f"picks at {path} has an unexpected shape", code="LEDGER_CORRUPT", hint=f"move or delete {path}")
    return book


def save(book: dict) -> Path:
    path = picks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, indent=1))
    return path


def find(book: dict, symbol: str) -> dict | None:
    return next((p for p in book["picks"] if p.get("symbol") == symbol), None)


def get(book: dict, symbol: str) -> dict:
    pick = find(book, symbol)
    if pick is None:
        raise InvalidInput(f"{symbol} is not a saved pick; picks.py list shows them")
    return pick


def load_baseline(pick: dict) -> dict:
    path = data_dir() / pick["baseline"]
    if not path.is_file():
        raise InvalidInput(f"{pick['symbol']}: baseline {path} is missing; save the pick again")
    return _read_json(str(path), "baseline")


LEVEL_TEXT = {
    "above_all": "price {p:.2f} is above every scenario (best {best:.2f})",
    "above_central": "price {p:.2f} is above the central value ({central:.2f})",
    "hurdle": "price {p:.2f} is past {hurdle:.2f}, where the central case stops earning the hurdle a year",
    "below_worst": "price {p:.2f} is below every scenario (worst {worst:.2f})",
}


def pick_levels(baseline: dict) -> dict:
    """The price thresholds of a pick's baseline (track_math.price_levels or light_levels)."""
    if isinstance(baseline.get("model"), dict):
        return track_math.price_levels(baseline["model"])
    return track_math.light_levels(baseline["fair_values"])


def level_crossing(pick: dict, baseline: dict, price: float) -> tuple[str, str] | None:
    """(level, text) when the price sits at a level other than normal and other than the one at the
    last check (or, before any check, the one at the added price); else None."""
    levels = pick_levels(baseline)
    now = track_math.price_level(price, levels)
    last = (pick.get("checks") or [None])[-1]
    if last and last.get("price_level"):
        before = last["price_level"]
    elif pick.get("added_price"):
        before = track_math.price_level(float(pick["added_price"]), levels)
    else:
        before = "normal"
    if now == "normal" or now == before:
        return None
    return now, LEVEL_TEXT[now].format(p=price, **{k: (v if v is not None else float("nan")) for k, v in levels.items()})


def _upsert(symbol: str, kind: str, baseline: dict, as_of: str, fields: dict) -> dict:
    rel = f"{BASELINE_DIR}/{symbol}-{as_of}.json"
    path = data_dir() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline))
    book = load()
    pick = find(book, symbol)
    if pick is None:
        pick = {"symbol": symbol, "checks": []}
        book["picks"].append(pick)
    pick.update({"kind": kind, "baseline": rel, "baseline_as_of": as_of, **fields})
    try:
        pick["next_earnings"] = market.next_events(symbol).get("next_earnings")
    except Exception:  # noqa: BLE001 - the earnings date is a convenience for the hook
        pick.setdefault("next_earnings", None)
    pick.pop("awaiting_filing", None)
    save(book)
    return {"pick": pick, "baseline_path": str(path)}


def page_data(html: str) -> dict:
    """The ``window.DATA`` object a deep page embeds (render_deep.py's input)."""
    marker = "window.DATA"
    i = html.find(marker)
    if i < 0:
        raise InvalidInput("no window.DATA in the page: is it a deep-valuation page from render_deep.py?")
    j = html.find("=", i) + 1
    while j < len(html) and html[j].isspace():
        j += 1
    try:
        data, _ = json.JSONDecoder().raw_decode(html, j)
    except ValueError as exc:
        raise InvalidInput(f"window.DATA in the page is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("model"), dict):
        raise InvalidInput("window.DATA in the page has no model")
    return data


# --- EDGAR actuals -------------------------------------------------------------------------


def _fundamentals():
    if not FUNDAMENTALS_SCRIPT.is_file():
        raise ConfigError(
            "the fundamental-research skill is not installed; pick re-checks need its EDGAR tables",
            code="SKILL_MISSING",
            hint="re-run `node install.js` and select fundamental-research (it needs an EDGAR contact)",
        )
    spec = importlib.util.spec_from_file_location("fundamentals", FUNDAMENTALS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _d(s: object) -> date:
    return date.fromisoformat(str(s)[:10])


def _annual_by_end(fm, gaap: dict, metric: str) -> dict[str, dict]:
    """{period_end: fact} for full fiscal years keyed by period end, not by SEC ``fy`` (a 52/53-week
    year ending in early January carries the next calendar year), the latest filing winning, with
    ``first_filed``: when that year was first reported under any concept. The first concept that
    reports a year gives its value."""
    out: dict[str, dict] = {}
    first_any: dict[str, str] = {}
    for concept in fm._CONCEPTS[metric]:
        by_end: dict[str, dict] = {}
        for f in fm._facts_for(gaap, concept):
            if f.get("form") not in fm._ANNUAL_FORMS or f.get("fp") != "FY" or not fm._is_annual_span(f):
                continue
            end, filed = str(f.get("end"))[:10], str(f.get("filed") or "")
            cur = by_end.get(end)
            first = min(filed, cur["first_filed"]) if cur else filed
            if cur is None or filed > str(cur.get("filed") or ""):
                by_end[end] = {**f, "first_filed": first}
            else:
                cur["first_filed"] = first
        for end, f in by_end.items():
            out.setdefault(end, f)
            first_any[end] = min(first_any.get(end, f["first_filed"]), f["first_filed"])
    for end, f in out.items():
        f["first_filed"] = first_any[end]
    return out


def _first_filed_quarters(fm, gaap: dict) -> dict[str, str]:
    """{quarter period_end: the date it was first filed in a 10-Q}; later comparatives do not move it."""
    first: dict[str, str] = {}
    for concept in fm._CONCEPTS["revenue"]:
        for f in fm._facts_for(gaap, concept):
            if f.get("form") in fm._QUARTER_FORMS and str(f.get("fp") or "").startswith("Q") and fm._is_quarter_span(f):
                end, filed = str(f.get("end"))[:10], str(f.get("filed") or "")
                if filed and (end not in first or filed < first[end]):
                    first[end] = filed
    return first


def _ttm(series: dict[str, dict], before: str | None = None) -> tuple[str, float, list[str]] | None:
    """The latest four consecutive quarters (ending on or before ``before``): (end, sum, ends)."""
    ends = sorted(e for e in series if before is None or e <= before)
    for i in range(len(ends), 3, -1):
        window = ends[i - 4:i]
        if TTM_SPAN[0] <= (_d(window[-1]) - _d(window[0])).days <= TTM_SPAN[1]:
            return window[-1], sum(float(series[e]["val"]) for e in window), window
    return None


def _sum(series: dict[str, dict], ends: list[str]) -> float | None:
    vals = [series.get(e, {}).get("val") for e in ends]
    return None if any(v is None for v in vals) else sum(float(v) for v in vals)


def _near(series: dict[str, dict], end: str, days: int) -> dict | None:
    target = _d(end) - timedelta(days=days)
    best = min(series, key=lambda e: abs((_d(e) - target).days), default=None)
    return series[best] if best is not None and abs((_d(best) - target).days) <= YEAR_TOLERANCE else None


def edgar_actuals(symbol: str, base_as_of: str | None = None) -> dict:
    """Base fiscal year (first filed on or before ``base_as_of``), latest TTM and its year-earlier TTM."""
    fm = _fundamentals()
    cik, _title = edgar.cik_for(symbol)
    facts = edgar.company_facts(cik)
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    if not gaap:
        raise InvalidInput(f"{symbol}: no us-gaap facts in EDGAR (a foreign filer?)")
    a_rev = _annual_by_end(fm, gaap, "revenue")
    a_oi = _annual_by_end(fm, gaap, "operating_income")
    a_ni = _annual_by_end(fm, gaap, "net_income")
    a_eq = _annual_by_end(fm, gaap, "equity")
    q = {m: fm._quarterly_series(gaap, m) for m in ("revenue", "operating_income", "net_income", "equity")}
    if not a_rev:
        raise InvalidInput(f"{symbol}: EDGAR has no annual revenue")

    def annual(end: str) -> dict:
        ni, eq0 = a_ni.get(end, {}).get("val"), _near(a_eq, end, 365)
        return {"period_end": end, "revenue": float(a_rev[end]["val"]),
                "operating_income": None if end not in a_oi else float(a_oi[end]["val"]),
                "net_income": None if ni is None else float(ni),
                "roe": None if ni is None or not eq0 or not eq0.get("val") else float(ni) / float(eq0["val"])}

    ends = sorted(a_rev)
    eligible = [e for e in ends if base_as_of is None or a_rev[e]["first_filed"] <= base_as_of]
    base = annual(eligible[-1] if eligible else ends[0])
    latest_annual = annual(ends[-1])
    history = [{**annual(e), "first_filed": a_rev[e]["first_filed"]} for e in ends]
    known = [e for e, filed in _first_filed_quarters(fm, gaap).items() if base_as_of and filed <= base_as_of]
    known_at_baseline = max(known + ([eligible[-1]] if eligible and base_as_of else []), default=None)

    def ttm_at(before: str | None) -> dict | None:
        t = _ttm(q["revenue"], before)
        if t is None:
            return None
        end, rev, window = t
        eq = _near(q["equity"], end, 365) or _near(a_eq, end, 365)
        return {"period_end": end, "revenue": rev, "operating_income": _sum(q["operating_income"], window),
                "net_income": _sum(q["net_income"], window), "equity_start": None if not eq else float(eq["val"])}

    ttm = ttm_at(None)
    if ttm is None or ttm["period_end"] < latest_annual["period_end"]:
        eq = _near(a_eq, latest_annual["period_end"], 365)
        ttm = {**{k: latest_annual[k] for k in ("period_end", "revenue", "operating_income", "net_income")},
               "equity_start": None if not eq else float(eq["val"])}
    prior = ttm_at((_d(ttm["period_end"]) - timedelta(days=365 - YEAR_TOLERANCE)).isoformat())
    if prior is None or abs((_d(ttm["period_end"]) - _d(prior["period_end"])).days - 365) > YEAR_TOLERANCE:
        prior = next((annual(e) for e in reversed(ends) if abs((_d(ttm["period_end"]) - _d(e)).days - 365) <= YEAR_TOLERANCE), None)
    filed = [str(f.get("filed") or "") for s in q.values() for f in s.values()] + [f["first_filed"] for f in a_rev.values()]
    light = {"period_end": ttm["period_end"],
             "revenue_growth": None if not prior or not prior["revenue"] else ttm["revenue"] / prior["revenue"] - 1,
             "operating_margin": None if ttm["operating_income"] is None else ttm["operating_income"] / ttm["revenue"]}
    ttm_at_baseline = ttm_at(known_at_baseline) if known_at_baseline else None
    return {"base": base, "annual": history, "ttm": ttm, "known_at_baseline": known_at_baseline, "ttm_at_baseline": ttm_at_baseline,
            "light": light, "latest_filed": max(filed)}


# --- commands ------------------------------------------------------------------------------


def _price(symbol: str) -> float:
    rows = market.quote([symbol])
    p = rows[0].get("price") if rows else None
    if not isinstance(p, (int, float)) or p <= 0:
        raise ApiError(f"no price for {symbol}", code="QUOTE_MISSING")
    return float(p)


def _save_deep(ns: argparse.Namespace) -> dict:
    symbol = brokerage.validate_symbol(ns.symbol)
    model_input = None
    if ns.case:
        case = Path(ns.case)
        if not (case / "page.json").is_file():
            raise InvalidInput(f"{case} has no page.json; render the deep page first, or use --page")
        data = _read_json(str(case / "page.json"), "page.json")
        if (case / "model.json").is_file():
            model_input = _read_json(str(case / "model.json"), "model.json")
    else:
        try:
            html = Path(ns.page).read_text()
        except OSError as exc:
            raise InvalidInput(f"page file {ns.page}: {exc}") from exc
        data = page_data(html)
    if not isinstance(data, dict):
        raise InvalidInput("page.json must be a JSON object")
    if not isinstance(data.get("model"), dict):
        raise InvalidInput("the deep valuation has no model output")
    if str(data.get("symbol") or symbol).upper() != symbol:
        raise InvalidInput(f"the valuation is for {data.get('symbol')}, not {symbol}")
    as_of = str(data.get("as_of") or ns.date or date.today().isoformat())[:10]
    baseline = {"symbol": symbol, "as_of": as_of, "price": data.get("price"), "model": data["model"],
                "returns": data.get("returns"), "ledger": data.get("ledger") or [], "model_input": model_input}
    if ns.base_end:
        baseline["base_period_end"] = ns.base_end
    existing = find(load(), symbol)
    keep = existing is not None and existing.get("kind") == "deep" and ns.date is None and ns.added_price is None
    added = existing.get("added") if keep else ns.date or as_of
    added_price = existing.get("added_price") if keep else ns.added_price if ns.added_price is not None else data.get("price")
    fields = {"added": added, "added_price": added_price, "thesis": ns.thesis, "source": ns.source or str(ns.case or ns.page)}
    return _upsert(symbol, "deep", baseline, as_of, fields)


def _save_light(ns: argparse.Namespace) -> dict:
    symbol = brokerage.validate_symbol(ns.symbol)
    spec = _read_json(ns.input, "light pick")
    fv = spec.get("fair_values") if isinstance(spec, dict) else None
    if not isinstance(fv, dict) or any(not isinstance(fv.get(k), (int, float)) for k in ("bear", "base", "bull")):
        raise InvalidInput("the input needs fair_values with numeric bear, base and bull")
    as_of = ns.date or date.today().isoformat()
    actuals = edgar_actuals(symbol)
    if actuals["light"]["revenue_growth"] is None:
        raise InvalidInput(f"{symbol}: EDGAR has no year-earlier twelve months to measure growth against, so a light pick cannot be re-checked")
    added_price = spec.get("added_price") if spec.get("added_price") is not None else _price(symbol)
    baseline = {"symbol": symbol, "as_of": as_of, "preset": spec.get("preset"), "thesis": spec.get("thesis"),
                "fair_values": {k: float(fv[k]) for k in ("bear", "base", "bull")}, "metrics_at_pick": actuals["light"]}
    fields = {"added": as_of, "added_price": added_price, "thesis": spec.get("thesis"), "source": spec.get("source")}
    return _upsert(symbol, "light", baseline, as_of, fields)


def _read_json(path: str | None, what: str):
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise InvalidInput(f"{what} file {path}: {exc}") from exc


def roll_release(ttm: dict, rel: dict) -> tuple[dict, dict]:
    """EDGAR's TTM rolled forward by one released quarter, and the flag that says so.

    Returns ``ttm`` unchanged with RELEASE_IN_EDGAR when EDGAR already has the quarter."""
    if not isinstance(rel, dict):
        raise InvalidInput("the release file must be a JSON object")
    try:
        end = _d(rel.get("period_end"))
    except (TypeError, ValueError) as exc:
        raise InvalidInput("the release needs period_end as YYYY-MM-DD") from exc
    last = _d(ttm["period_end"])
    if end <= last:
        return ttm, {"code": "RELEASE_IN_EDGAR", "message": f"EDGAR already has the quarter to {end}; the release was not used"}
    lo, hi = NEXT_QUARTER_DAYS
    if not lo <= (end - last).days <= hi:
        raise InvalidInput(f"the release must be for the quarter after EDGAR's latest ({ttm['period_end']}), not {end}")

    def val(key: str) -> float | None:
        v = rel.get(key)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise InvalidInput(f"release {key} must be a number")
        return float(v)

    for key in ("revenue", "revenue_year_ago"):
        if val(key) is None:
            raise InvalidInput(f"the release needs {key}")

    def roll(key: str) -> float | None:
        cur, ago = val(key), val(f"{key}_year_ago")
        if ttm.get(key) is None or cur is None or ago is None:
            return None
        return ttm[key] - ago + cur

    out = dict(ttm, period_end=end.isoformat(), revenue=roll("revenue"), operating_income=roll("operating_income"),
               net_income=roll("net_income"), basis="press_release", release_source=rel.get("source"), release_date=rel.get("date"))
    if val("equity_year_ago") is not None:
        out["equity_start"] = val("equity_year_ago")
    flag = {"code": "PRESS_RELEASE_FIGURES",
            "message": f"TTM to {end} uses the earnings release of {rel.get('date') or 'unknown date'} ({rel.get('source') or 'no source'}); "
                       "the 10-Q replaces it once it is in EDGAR"}
    return out, flag


def _record(pick: dict, result: dict, actuals: dict, price: float, today: str) -> dict:
    ttm_end = actuals["ttm"]["period_end"] if pick["kind"] == "deep" else actuals["light"]["period_end"]
    entry = {"date": today, "price": price, "period_end": ttm_end, "status": result["status"],
             "nearest": result.get("nearest"), "rerun_deep": result.get("rerun_deep", result.get("deep_review", False)),
             "reasons": [r["code"] for r in result.get("reasons", [])], "price_level": result["price"].get("level")}
    if pick["kind"] == "deep" and actuals["ttm"].get("basis") == "press_release":
        entry["basis"] = "press_release"
        pick.setdefault("checks", []).append(entry)
        pick["awaiting_filing"] = True  # the figures are the release's: the 10-Q check is still due
        return entry
    pick.setdefault("checks", []).append(entry)
    old = pick.get("next_earnings")
    if old and old <= today and _d(ttm_end) < _d(old) - timedelta(days=REPORT_LAG_DAYS):
        pick["awaiting_filing"] = True  # earnings are out, the quarter is not in EDGAR yet: stay due
    else:
        pick.pop("awaiting_filing", None)
        try:
            pick["next_earnings"] = market.next_events(pick["symbol"]).get("next_earnings")
        except Exception:  # noqa: BLE001
            pass
    return entry


def _check(ns: argparse.Namespace) -> dict:
    symbol = brokerage.validate_symbol(ns.symbol)
    book = load()
    pick = get(book, symbol)
    baseline = load_baseline(pick)
    today = date.today().isoformat()
    price = _price(symbol)
    release = _read_json(ns.release, "release")
    if release is not None and pick["kind"] != "deep":
        raise InvalidInput(f"{symbol}: --release applies to deep picks only")
    release_flag = None
    if pick["kind"] == "deep":
        actuals = edgar_actuals(symbol, baseline["as_of"])
        if release is not None:
            actuals["ttm"], release_flag = roll_release(actuals["ttm"], release)
        params = {"mode": "deep", "as_of": today, "price": price, "baseline": baseline,
                  "actuals": {"annual": actuals["annual"], "ttm": actuals["ttm"], "known_at_baseline": actuals["known_at_baseline"],
                              "ttm_at_baseline": actuals.get("ttm_at_baseline")}}
        exclude = [x.strip() for x in ns.exclude.split(",") if x.strip()] if ns.exclude is not None else pick.get("exclude_segments") or []
        if exclude:
            params["exclude_segments"] = exclude
        if ns.record and ns.exclude is not None:
            pick["exclude_segments"] = exclude  # kept for later checks; --exclude "" clears it
        segs = _read_json(ns.segments, "segments")
        if segs:
            params["actuals"]["segments"] = segs
        ev = _read_json(ns.evidence, "evidence")
        if ev:
            params["evidence"] = ev
    else:
        actuals = edgar_actuals(symbol)
        params = {"mode": "light", "as_of": today, "price": price, "baseline": baseline, "actuals": actuals["light"]}
    try:
        result = track_math.run_track(params)
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidInput(f"{symbol}: {exc}") from exc
    if release_flag:
        result.setdefault("flags", []).append(release_flag)
    recorded = None
    if ns.record:
        recorded = _record(pick, result, actuals, price, today)
        save(book)
    added = pick.get("added_price")
    return {"symbol": symbol, "kind": pick["kind"],
            "pick": {k: pick.get(k) for k in ("added", "added_price", "baseline_as_of", "thesis", "source", "next_earnings")},
            "since_added": None if not added else round(price / float(added) - 1, 4),
            "actuals": actuals, "result": result, "recorded": recorded}


def _due(ns: argparse.Namespace) -> dict:
    book = load()
    if not book["picks"]:
        return {"due": [], "not_due": [], "flags": []}
    symbols = [p["symbol"] for p in book["picks"]]
    quotes = {r.get("symbol"): r.get("price") for r in market.quote(symbols)}
    due, not_due, flags = [], [], []
    refreshed = False
    for p in book["picks"]:
        last = (p.get("checks") or [None])[-1]
        since = last["date"] if last else p.get("added") or p.get("baseline_as_of")
        ref = last["price"] if last else p.get("added_price")
        reasons = []
        try:
            filed = edgar_actuals(p["symbol"])["latest_filed"]
            if filed > since:
                reasons.append({"code": "NEW_FILING", "message": f"a filing dated {filed} is newer than the last check ({since})"})
        except (ApiError, InvalidInput) as exc:
            flags.append({"code": "EDGAR_UNAVAILABLE", "message": f"{p['symbol']}: {exc}"})
        price = quotes.get(p["symbol"])
        if isinstance(price, (int, float)) and ref:
            move = price / float(ref) - 1
            if abs(move) >= ns.move:
                reasons.append({"code": "PRICE_MOVE", "message": f"price {move:+.1%} since {since}"})
        ne = p.get("next_earnings")
        if ne and ne < since and not p.get("awaiting_filing"):
            try:  # the stored date passed before the last check: learn the next one so the hook stays current
                p["next_earnings"] = market.next_events(p["symbol"]).get("next_earnings") or ne
                refreshed = True
            except Exception:  # noqa: BLE001
                pass
        if isinstance(price, (int, float)):
            try:
                crossed = level_crossing(p, load_baseline(p), float(price))
            except (InvalidInput, ValueError, KeyError, TypeError):
                crossed = None
            if crossed:
                reasons.append({"code": "PRICE_LEVEL", "level": crossed[0], "message": crossed[1]})
        if p.get("awaiting_filing"):
            reasons.append({"code": "AWAITING_FILING", "message": f"earnings were {p.get('next_earnings')}; the quarter was not in EDGAR at the last check"})
        (due if reasons else not_due).append({"symbol": p["symbol"], "kind": p["kind"], "since": since, "reasons": reasons})
    if refreshed:
        save(book)
    return {"due": due, "not_due": not_due, "flags": flags}


def summary_lines(today: date | None = None) -> list[str]:
    """Plain-text lines for the SessionStart hook; no network."""
    path = picks_path()
    if not path.is_file():
        return []
    try:
        book = load()
    except ApiError:
        return [f"Pick re-check: {path} could not be read."]
    if not book["picks"]:
        return []
    today_s = (today or date.today()).isoformat()
    prices = {}
    try:
        last_check = json.loads((data_dir() / WATCHLIST_LAST_CHECK).read_text())
        prices = {w.get("symbol"): w.get("price") for w in last_check.get("watchlist") or []}
    except (OSError, ValueError, AttributeError):
        pass
    lines = []
    for p in book["picks"]:
        last = (p.get("checks") or [None])[-1]
        since = last["date"] if last else p.get("added") or p.get("baseline_as_of") or ""
        ref = last["price"] if last else p.get("added_price")
        why = []
        ne = p.get("next_earnings")
        if p.get("awaiting_filing"):
            why.append(f"reported {ne}, 10-Q not in EDGAR at the last check")
        elif ne and since < ne <= today_s:
            why.append(f"reported {ne}")
        price = prices.get(p["symbol"])
        if isinstance(price, (int, float)) and ref:
            move = price / float(ref) - 1
            if abs(move) >= DEFAULT_MOVE:
                why.append(f"price {move:+.1%} since {since}")
        if isinstance(price, (int, float)):
            try:
                crossed = level_crossing(p, load_baseline(p), float(price))
            except Exception:  # noqa: BLE001 - the hook never fails on one pick
                crossed = None
            if crossed:
                why.append(crossed[1])
        if why:
            lines.append(f"  {p['symbol']} ({p.get('kind')}): {'; '.join(why)}")
    n = len(book["picks"])
    if not lines:
        nxt = sorted((p["next_earnings"], p["symbol"]) for p in book["picks"] if p.get("next_earnings") and p["next_earnings"] > today_s)
        tail = f"; next earnings {nxt[0][1]} {nxt[0][0]}" if nxt else ""
        return [f"Pick re-check: {n} picks tracked, none due{tail}."]
    return [f"Pick re-check: {len(lines)} of {n} picks due (ask Claude to re-check my picks):", *lines]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["summary"]:
        try:
            lines = summary_lines()
        except Exception:  # noqa: BLE001 - the hook never fails the session
            lines = []
        if lines:
            print("\n".join(lines))
        return 0

    def go(a: list[str]):
        p = _Parser(prog="picks.py", add_help=False)
        sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
        sd = sub.add_parser("save-deep", add_help=False)
        sd.add_argument("symbol")
        src = sd.add_mutually_exclusive_group(required=True)
        src.add_argument("--case")
        src.add_argument("--page")
        sd.add_argument("--thesis")
        sd.add_argument("--source")
        sd.add_argument("--added-price", type=float)
        sd.add_argument("--date")
        sd.add_argument("--base-end")
        sl = sub.add_parser("save-light", add_help=False)
        sl.add_argument("symbol")
        sl.add_argument("--in", dest="input", required=True)
        sl.add_argument("--date")
        sub.add_parser("list", add_help=False)
        rm = sub.add_parser("remove", add_help=False)
        rm.add_argument("symbol")
        ck = sub.add_parser("check", add_help=False)
        ck.add_argument("symbol")
        ck.add_argument("--release")
        ck.add_argument("--segments")
        ck.add_argument("--evidence")
        ck.add_argument("--exclude")
        ck.add_argument("--record", action="store_true")
        du = sub.add_parser("due", add_help=False)
        du.add_argument("--move", type=float, default=DEFAULT_MOVE)
        ns = p.parse_args(a)
        if ns.cmd == "save-deep":
            return _save_deep(ns)
        if ns.cmd == "save-light":
            return _save_light(ns)
        if ns.cmd == "list":
            return {"picks": load()["picks"], "picks_path": str(picks_path())}
        if ns.cmd == "remove":
            book = load()
            sym = brokerage.validate_symbol(ns.symbol)
            get(book, sym)
            book["picks"] = [x for x in book["picks"] if x.get("symbol") != sym]
            save(book)
            return {"removed": sym, "count": len(book["picks"])}
        if ns.cmd == "check":
            return _check(ns)
        return _due(ns)

    return output.run(go, args)


if __name__ == "__main__":
    sys.exit(main())
