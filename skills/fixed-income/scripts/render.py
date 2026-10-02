#!/usr/bin/env python3
"""Usage: render.py [--in analysis.json] --out page.html

Turns the fixed-income skill's script results (a file, or stdin when ``--in`` is omitted) into one
self-contained HTML page for the Artifact tool. The skill has no single combined script, so the
input is an object collecting whichever results ran; at least one of ``horizon``, ``rates`` or
``fund`` must be present::

    {"symbol": "BND",           # shown in the title
     "horizon": <horizon.py result>,
     "rates":   <rates.py result>,
     "fund":    <fund.py result>}

The page answers what a person holding a bond or a bond fund actually asks, in this order, each as a
picture first: what it earns a year if held (tiles), whether that beats cash (bars), what a rate
move does along the way (lines of $10,000 under rates down 1, unchanged, up 1), whether yields are
high or low against history (0-100 strips), and, for a fund, which of its three published yields is
which (bars). The market-implied rate path against the Fed's projection, the yield decomposition and
the durations sit in a collapsed "Go deeper" section. Teaching text is in a step-by-step walkthrough
("How to read this page"), and every disclosure the scripts emit is in the "Details and assumptions"
modal, verbatim. Prints ``{"out": path, "title": ..., "sections": [...]}``. Exit 2 on a missing or
malformed input.

**Only named fields reach the page.** ``view`` below picks each figure by name into a small object,
and that object -- never the payload -- is what the page embeds and draws. A key a result happens to
carry, an advisory one above all, has no route to the reader. The one exception is each result's own
``assumptions`` block, whose strings are copied verbatim into the details modal: those are the
upstream scripts' disclosures, pinned in their own tests, and a summary written here would silently
drop whatever a later fix adds. That exception is a trust boundary, not a filter.

**Every rate on the page is an effective annual rate**, so the bars compare like with like. Treasury
yields and a fund's yield to maturity are quoted bond-equivalent (compounding twice a year); the
horizon return is already effective. The fund's three published yields are the one place figures are
shown as the fund publishes them, and are labelled so.

Nothing here is a fair value, a target, or a view on whether a bond is cheap or expensive. Every
input is a market price, so a modelled value reproduces the market price by construction; the
circularity note that says so travels beside the calculated yield wherever it appears.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[2] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

SECTION_ANSWER = "The short answer"
SECTION_CASH = "Compared with cash"
SECTION_PATHS = "If rates move"
SECTION_HISTORY = "Are yields high right now?"
SECTION_YIELDS = "The fund's three yields"
SECTION_DEEPER = "Go deeper"

INVEST = 10_000
# Quoted Treasury and fund yields compound twice a year.
BOND_EQUIVALENT_FREQ = 2
# Far above any yield a bond fund quotes, and far below where (1 + y/f)^f overflows.
MAX_QUOTED_YIELD_PCT = 1000.0

# The history strips on the main page; the rest of rates.py's percentiles go under "Go deeper".
# Each label says what the figure is in words, and ``high`` says what a high rank means for a holder.
HISTORY_MAIN = {
    "treasury_10y": ("10-year Treasury yield", "what the government pays to borrow for 10 years"),
    "real_yield_10y": ("10-year yield after inflation", "the TIPS yield: what a Treasury pays above inflation"),
    "credit_spread_baa": (
        "Extra yield for lending to companies",
        "how much more medium-grade (Baa) corporate bonds pay than Treasuries",
    ),
}
HISTORY_DEEPER = {
    "breakeven_10y": ("Inflation the market is pricing in", "the 10-year breakeven: nominal minus TIPS yield"),
    "term_premium_10y": ("Extra pay for locking up money longer", "the 10-year term premium estimate"),
}

YIELDS = (
    ("Distribution yield", "distribution_yield_pct", "What it actually paid out lately. Trails rate changes."),
    ("SEC yield", "sec_yield_pct", "The standard 30-day figure after fees, the same basis for every fund."),
    ("Yield to maturity", "ytm_pct", "What its bonds pay if held to the end, before fees. This page's return is built on it."),
)

DURATIONS = (
    ("Macaulay duration", "duration_years", "The holding time at which a rate move's price loss and extra reinvestment income cancel."),
    ("Modified duration", "modified_duration_years", "Rough price change for a 1-point rate move, in percent."),
    ("Published effective duration", "published_effective_duration_years", "The fund's own figure for its real, rolling portfolio."),
)

FOOTER = (
    "Not a forecast and not a recommendation. Every figure comes from today's market prices; a fund is "
    "modelled as a single bond."
)

CLOSING_NOTE = (
    "This page ranks today against its own history and shows what today's prices already assume. A "
    "rank is not a valuation and not a call on any security: it says where a figure sits in its own "
    "record, not what the security is worth and not what happens next. No fair value and no price "
    "target appears anywhere here, because every input is a market price and anything modelled from "
    "them reproduces the market price by construction. The rate-move lines are a sensitivity to a move "
    "of a stated size, not a forecast that rates will move. General information at the stated "
    "assumptions, not financial, tax, or legal advice."
)

EFFECTIVE_RATE_NOTE = (
    "Every rate compared on this page is an effective annual rate: what a year of compounding gives. "
    "Treasury and fund yields are quoted compounding twice a year, so each is converted, (1 + y/2)² − 1. "
    "The fund's three yields are shown as the fund publishes them."
)

# The walkthrough. Each step outlines the section whose id it names; a step whose section is not on
# the page is skipped by FA.tour. Plain words, one idea per step.
TOUR = [
    {
        "target": "#fi-answer",
        "title": "The short answer",
        "html": (
            "<p>If you buy at today's price and hold for the period shown, reinvesting what it pays, this is "
            "what it works out to per year. It is the arithmetic of today's yield, not a forecast of prices.</p>"
            "<p>The middle tile compares it with cash; the last shows what a 1-point rise in rates would do, "
            "right away and by the end.</p>"
        ),
    },
    {
        "target": "#fi-cash",
        "title": "Compared with cash",
        "html": (
            "<p>A 3-month Treasury bill is the benchmark for cash: money funds and savings accounts track it. "
            "Cash rates can change any month. A bond sets its rate for years, which is the point of owning one "
            "and also its risk.</p>"
            "<p>All bars are yearly rates on the same basis, so they compare like with like.</p>"
        ),
    },
    {
        "target": "#fi-paths",
        "title": "What a rate move does to you",
        "html": (
            "<p>When rates rise, a bond's price falls at once, because new bonds pay more. But from then on "
            "everything it pays is reinvested at the higher rate, so it grows faster.</p>"
            "<p>Follow the lines: the rates-up line starts lower and catches up. Where they meet is roughly the "
            "bond's <b>duration</b>. Held past that point, a rate rise leaves you about where you were, or ahead. "
            "Sold before it, the dip is real.</p>"
        ),
    },
    {
        "target": "#fi-history",
        "title": "Is today unusual?",
        "html": (
            "<p>Each strip ranks today's figure against every day of its own history. The dot is today; the "
            "middle tick is the typical (median) day.</p>"
            "<p>Far right means higher than usual: for a yield, a holder is paid more than usual; for the "
            "corporate spread, a holder is paid more than usual for the risk that a company fails to pay. A "
            "rank describes the past. It does not predict where rates go next.</p>"
        ),
    },
    {
        "target": "#fi-yields",
        "title": "Why a fund shows three yields",
        "html": (
            "<p>They measure different things and can differ by a point or more with nothing wrong. The "
            "<b>distribution yield</b> looks back at what was paid. The <b>SEC yield</b> is a standard snapshot "
            "for comparing funds. The <b>yield to maturity</b> looks ahead at what the bonds now held will pay, "
            "and is the one this page's return comes from.</p>"
        ),
    },
    {
        "target": "#fi-deeper",
        "title": "Go deeper",
        "html": (
            "<p>For the curious: the path of short-term rates today's prices assume, next to the Federal "
            "Reserve's own projection; where the fund's yield comes from; and the three kinds of duration.</p>"
        ),
    },
    {
        "target": "#fi-footer",
        "title": "The fine print",
        "html": (
            "<p><b>Details and assumptions</b> lists every assumption behind these figures, word for word. "
            "The biggest one: a fund holds hundreds of bonds and keeps buying new ones, and this page models "
            "it as one bond with the fund's average coupon and life.</p>"
        ),
    },
]


def _num(value: Any) -> float | None:
    """A real number from JSON, else ``None``. ``True`` is an ``int`` in Python and is not one of these."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) != float("inf") else None


def _r(value: float | None, dp: int = 2) -> float | None:
    return None if value is None else round(value, dp)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def effective(quoted_pct: float | None, freq: int = BOND_EQUIVALENT_FREQ) -> float | None:
    """A yield quoted compounding ``freq`` times a year, as an effective annual rate, in percent."""
    if quoted_pct is None or abs(quoted_pct) > MAX_QUOTED_YIELD_PCT:
        return None
    return ((1.0 + quoted_pct / 100.0 / freq) ** freq - 1.0) * 100.0


def _scenario(hor: dict, bp: int) -> dict:
    for row in _list(hor.get("scenarios")):
        if isinstance(row, dict) and row.get("delta_yield_bp") == bp:
            return row
    return {}


def _paths(hor: dict) -> list[dict]:
    names = {-100: "Rates fall 1 point", 0: "Rates unchanged", 100: "Rates rise 1 point"}
    out = []
    for row in _list(hor.get("value_paths")):
        if not isinstance(row, dict) or row.get("delta_yield_bp") not in names:
            continue
        pts = []
        for pt in _list(row.get("points")):
            t, v = _num(_dict(pt).get("years")), _num(_dict(pt).get("value"))
            if t is not None and v is not None:
                pts.append([t, round(v * INVEST, 2)])
        if pts:
            out.append({"bp": row["delta_yield_bp"], "name": names[row["delta_yield_bp"]], "points": pts})
    return out


def crossover_years(paths: list[dict]) -> float | None:
    """When the rates-up line first catches the unchanged one, or ``None`` if it never does."""
    up = next((p["points"] for p in paths if p["bp"] == 100), None)
    base = next((p["points"] for p in paths if p["bp"] == 0), None)
    if not up or not base or len(up) != len(base):
        return None
    for (t, u), (_, b) in zip(up, base):
        if t > 0 and u >= b:
            return t
    return None


def _answer(hor: dict, rates: dict, symbol: str) -> dict | None:
    ret = _num(hor.get("locked_in_return_pct"))
    horizon = _num(hor.get("horizon_years"))
    if ret is None or horizon is None:
        return None
    cash = effective(_num(_dict(rates.get("benchmarks")).get("bill_3m_pct")))
    up = _scenario(hor, 100)
    paths = _paths(hor)
    name = symbol or "this bond"
    sentence = f"Held about {horizon:g} years, {name} works out to roughly {ret:.1f}% a year at today's prices"
    if cash is not None:
        diff = ret - cash
        if abs(diff) < 0.05:
            sentence += f", about the same as cash in a 3-month Treasury bill ({cash:.1f}%)."
        else:
            word = "more" if diff > 0 else "less"
            sentence += f", {abs(diff):.1f} points {word} a year than cash in a 3-month Treasury bill ({cash:.1f}%)."
    else:
        sentence += "."
    return {
        "sentence": sentence,
        "return_pct": _r(ret, 1),
        "horizon_years": horizon,
        "cash_pct": _r(cash, 1),
        "vs_cash_pp": _r(ret - cash, 1) if cash is not None else None,
        "up1_now_pct": _r(_num(up.get("immediate_price_change_pct")), 1),
        "up1_held_pct": _r(_num(up.get("annualised_pct")), 1),
        "crossover_years": crossover_years(paths),
        "paths": paths,
    }


def _compare(hor: dict, rates: dict, fund: dict, symbol: str) -> list[dict]:
    rows = []
    cash = effective(_num(_dict(rates.get("benchmarks")).get("bill_3m_pct")))
    if cash is not None:
        rows.append({"label": "Cash (3-month Treasury bill)", "pct": _r(cash), "kind": "cash"})
    par = _dict(rates.get("par_curve"))
    for key, label in (("2.0", "2-year Treasury"), ("10.0", "10-year Treasury")):
        v = effective(_num(par.get(key)))
        if v is not None:
            rows.append({"label": label, "pct": _r(v), "kind": "treasury"})
    ret = _num(hor.get("locked_in_return_pct"))
    horizon = _num(hor.get("horizon_years"))
    if ret is not None and horizon is not None:
        rows.append({"label": f"{symbol or 'This bond'}, held {horizon:g} years", "pct": _r(ret), "kind": "this"})
    elif fund:
        ytm = effective(_num(_dict(fund.get("characteristics")).get("ytm_pct")))
        if ytm is not None:
            rows.append({"label": f"{symbol or 'This fund'}, yield to maturity", "pct": _r(ytm), "kind": "this"})
    return rows


def _history(rates: dict, keys: dict) -> list[dict]:
    out = []
    pct = _dict(rates.get("percentiles"))
    for key, (label, what) in keys.items():
        e = _dict(pct.get(key))
        rank, value = _num(e.get("percentile")), _num(e.get("value"))
        if rank is None or value is None:
            continue
        since = str(e.get("history_from") or "")[:4]
        out.append(
            {
                "key": key,
                "label": label,
                "what": what,
                "value": _r(value),
                "percentile": round(rank),
                "median": _r(_num(e.get("median"))),
                "since": since,
                "rank_text": _rank_text(round(rank), since),
            }
        )
    return out


def _rank_text(rank: int, since: str) -> str:
    """Plain words for a rank. The rank is the share of days strictly below today, rounded, so 100
    and 0 mean "at or within half a percent of the record", not "above every day"."""
    span = f"since {since}" if since else "in its history"
    if rank >= 100:
        return f"At or near the highest on record {span}"
    if rank <= 0:
        return f"At or near the lowest on record {span}"
    if rank >= 50:
        return f"Higher than {rank}% of days {span}"
    return f"Lower than {100 - rank}% of days {span}"


def _yields(fund: dict) -> list[dict]:
    chars = _dict(fund.get("characteristics"))
    return [
        {"label": label, "pct": _r(_num(chars.get(key)), 2), "what": what}
        for label, key, what in YIELDS
    ]


def _deeper(hor: dict, rates: dict, fund: dict) -> dict:
    out: dict[str, Any] = {}
    as_of = str(_dict(rates.get("as_of")).get("curve") or "")[:4]
    base_year = int(as_of) if as_of.isdigit() else None
    if base_year is not None:
        market = []
        for row in _list(rates.get("implied_short_rate_path")):
            s, v = _num(_dict(row).get("start")), _num(_dict(row).get("rate_pct"))
            if s is not None and v is not None:
                market.append([base_year + s, _r(v)])
        fomc = []
        proj = _dict(rates.get("fomc_projection"))
        for row in _list(proj.get("path")):
            y, v = str(_dict(row).get("year") or ""), _num(_dict(row).get("median_pct"))
            if y.isdigit() and v is not None:
                fomc.append([int(y), _r(v)])
        if market or fomc:
            out["rate_path"] = {
                "market": market,
                "fomc": fomc,
                "longer_run_pct": _r(_num(proj.get("longer_run_pct"))),
                "fed_funds_pct": _r(_num(_dict(rates.get("benchmarks")).get("fed_funds_pct"))),
            }
    dec = _dict(fund.get("yield_decomposition"))
    if dec:
        rows = [
            ("Treasury yield on the same cash flows", _r(_num(dec.get("treasury_equivalent_pct"))), "%"),
            ("Extra for credit risk (blended spread)", _r(_num(dec.get("blended_spread_bp")), 1), "bp"),
            ("Fund fees (expense ratio)", _r(_num(dec.get("expense_pct")), 3), "%"),
        ]
        calc = _num(dec.get("calculated_ytm_pct"))
        if calc is not None and _num(dec.get("gap_bp")) is not None:
            rows += [
                ("Calculated yield to maturity, after fees", _r(calc), "%"),
                ("Published yield to maturity, before fees", _r(_num(dec.get("published_ytm_pct"))), "%"),
                ("Difference", _r(_num(dec.get("gap_bp")), 1), "bp"),
            ]
        note = fund.get("circularity_note")
        out["decomposition"] = {
            "rows": [{"label": a, "value": b, "unit": c} for a, b, c in rows],
            # The note that says the calculated yield is no evidence of mispricing goes wherever that
            # yield goes, and only there.
            "circularity_note": note if isinstance(note, str) and calc is not None else None,
        }
    durations = [
        {"label": label, "years": _r(_num(hor.get(key))), "what": what}
        for label, key, what in DURATIONS
        if _num(hor.get(key)) is not None
    ]
    if durations:
        out["durations"] = durations
    history = _history(rates, HISTORY_DEEPER)
    if history:
        out["history"] = history
    return out


def _disclosures(payload: dict) -> list[dict]:
    """Every string in every result's ``assumptions`` block, verbatim, plus the notes each result
    carries at its top level. Scalars become short chips; structural lists are model inputs already
    reflected in the figures and are not reprinted."""
    groups = []
    for part, heading in (("horizon", "Holding to the horizon"), ("fund", "The fund's yield model"), ("rates", "The rate environment")):
        block = _dict(payload.get(part))
        if not block:
            continue
        prose: list[dict] = []
        chips: list[str] = []
        for note_key in ("mismatch_cost_note", "circularity_note", "note"):
            if isinstance(block.get(note_key), str):
                prose.append({"label": _label(note_key), "text": block[note_key]})
        for key, value in _dict(block.get("assumptions")).items():
            if isinstance(value, str):
                prose.append({"label": _label(key), "text": value})
            elif isinstance(value, bool):
                chips.append(f"{_label(key)}: {'yes' if value else 'no'}")
            elif _num(value) is not None:
                chips.append(f"{_label(key)}: {value:g}")
            elif isinstance(value, dict) and value and all(_num(v) is not None for v in value.values()):
                chips.append(f"{_label(key)}: " + ", ".join(f"{k} {v:g}" for k, v in value.items()))
        if prose or chips:
            groups.append({"heading": heading, "prose": prose, "chips": chips})
    return groups


def _label(key: str) -> str:
    return key.replace("_", " ").replace(" pct", " (%)").replace(" bp", " (bp)").strip().capitalize()


def _warnings(payload: dict) -> list[str]:
    found: list[str] = []
    for part in ("fund", "rates", "horizon"):
        for entry in _list(_dict(payload.get(part)).get("warnings")):
            if isinstance(entry, str) and entry not in found:
                found.append(entry)
    return found


def _as_of(fund: dict, rates: dict) -> str:
    for block, key in ((fund, "fund"), (rates, "curve")):
        v = _dict(block.get("as_of")).get(key)
        if isinstance(v, str) and v:
            try:
                return dt.date.fromisoformat(v[:10]).strftime("%b %-d, %Y")
            except ValueError:
                return v
    return ""


def view(payload: dict, symbol: str) -> tuple[dict, list[str]]:
    """The page's whole data: every figure picked by name, rounded to what a reader needs."""
    hor, rates, fund = (_dict(payload.get(k)) for k in ("horizon", "rates", "fund"))
    v: dict[str, Any] = {"symbol": symbol, "as_of": _as_of(fund, rates)}
    sections: list[str] = []
    answer = _answer(hor, rates, symbol) if hor else None
    if answer:
        v["answer"] = answer
        sections.append(SECTION_ANSWER)
    compare = _compare(hor, rates, fund, symbol)
    if len(compare) >= 2:
        v["compare"] = compare
        sections.append(SECTION_CASH)
    if answer and answer["paths"]:
        sections.append(SECTION_PATHS)
    history = _history(rates, HISTORY_MAIN)
    if history:
        v["history"] = history
        sections.append(SECTION_HISTORY)
    if fund and _dict(fund.get("characteristics")):
        v["yields"] = _yields(fund)
        ytm = _num(_dict(fund.get("characteristics")).get("ytm_pct"))
        ear = effective(ytm)
        if ytm is not None and ear is not None:
            v["yields_note"] = (
                f"The yield to maturity is quoted the bond way, compounding twice a year: {ytm:g}% quoted is "
                f"{ear:.2f}% as a plain yearly rate, the basis every other rate on this page uses."
            )
        sections.append(SECTION_YIELDS)
    deeper = _deeper(hor, rates, fund)
    if deeper:
        v["deeper"] = deeper
        sections.append(SECTION_DEEPER)
    v["warnings"] = _warnings(payload)
    v["disclosures"] = _disclosures(payload)
    v["closing_note"] = CLOSING_NOTE
    v["effective_rate_note"] = EFFECTIVE_RATE_NOTE
    v["footer"] = FOOTER
    v["tour"] = TOUR
    return v, sections


BODY = """
<h1 id="fi-title"></h1>
<div id="fi-intro"></div>
<section class="card" id="fi-warn" data-help="none" hidden><h2>Missing inputs</h2><p class="sub">These figures were missing from the source, so anything built on them is left out rather than shown as zero.</p><ul id="fi-warn-list"></ul></section>
<div id="fi-answer" class="tiles"></div>
<section class="card" id="fi-cash" hidden><h2>Compared with cash</h2><p class="sub">Yearly return at today's prices. Cash rates can change any month; a bond sets its rate for years.</p><div id="fi-cash-bars"></div></section>
<section class="card" id="fi-paths" hidden><h2>If rates move</h2><p class="sub" id="fi-paths-sub"></p><div id="fi-paths-chart"></div></section>
<section class="card" id="fi-history" hidden><h2>Are yields high right now?</h2><p class="sub">Where today ranks against every day on record. The dot is today; the tick is a typical day.</p><div id="fi-history-strips"></div></section>
<section class="card" id="fi-yields" hidden><h2>The fund's three yields</h2><p class="sub">As the fund publishes them. They measure different things, so they differ.</p><div id="fi-yields-bars"></div><p class="note" id="fi-yields-note"></p></section>
<details class="card" id="fi-deeper" hidden><summary><b>Go deeper</b>: the rate path prices assume, where the yield comes from, duration</summary><div id="fi-deeper-body"></div></details>
<p class="note" id="fi-footer"></p>
"""

SCRIPT = r"""
(() => {
const V = window.DATA, $ = id => document.getElementById(id), E = FA.esc;
const p1 = v => FA.isNum(v) ? v.toFixed(1) + '%' : 'not available';
const p2 = v => FA.isNum(v) ? v.toFixed(2) + '%' : 'not available';
const sgn = (v, unit) => FA.isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + unit : 'not available';
$('fi-title').textContent = V.symbol ? 'Fixed Income — ' + V.symbol : 'Fixed Income';
const A = V.answer;
const lead = A ? E(A.sentence) : 'How today\'s bond yields compare with cash and with their own history.';
FA.intro($('fi-intro'), {lead: lead + (V.as_of ? ` <span class="muted">Prices as of ${E(V.as_of)}.</span>` : ''), steps: V.tour});
if (V.warnings.length) { $('fi-warn').hidden = false; $('fi-warn-list').innerHTML = V.warnings.map(w => `<li>${E(w)}</li>`).join(''); }
const tile = (k, v, d, cls = '') => `<div class="tile"><div class="k">${E(k)}</div><div class="v ${cls}">${E(v)}</div><div class="d">${d}</div></div>`;
if (A) {
  let t = tile(`Return a year, held ${A.horizon_years} years`, p1(A.return_pct), 'at today\'s price, reinvesting what it pays');
  if (FA.isNum(A.vs_cash_pp)) t += tile('Compared with cash', sgn(A.vs_cash_pp, ' pts'), `a 3-month Treasury bill pays ${E(p1(A.cash_pct))}`, FA.cls(A.vs_cash_pp));
  if (FA.isNum(A.up1_now_pct)) t += tile('If rates rise 1 point today', sgn(A.up1_now_pct, '%'),
    FA.isNum(A.up1_held_pct) ? `in price, at once. Held ${A.horizon_years} years: ${E(p1(A.up1_held_pct))} a year instead of ${E(p1(A.return_pct))}` : 'in price, at once', FA.cls(A.up1_now_pct));
  $('fi-answer').innerHTML = t;
} else $('fi-answer').remove();
if (V.compare) { $('fi-cash').hidden = false;
  const max = Math.max(...V.compare.map(r => r.pct));
  FA.bars($('fi-cash-bars'), V.compare.map(r => ({label: r.label, share: r.pct / max, text: p2(r.pct), color: r.kind === 'this' ? 'var(--s1)' : r.kind === 'cash' ? 'var(--s3)' : 'var(--muted)'})));
  $('fi-cash').querySelector('.sub').insertAdjacentHTML('beforeend', ' <span class="muted">All shown as yearly rates on the same basis.</span>'); }
if (A && A.paths.length) { $('fi-paths').hidden = false;
  const cross = A.crossover_years;
  $('fi-paths-sub').innerHTML = `What $10,000 grows to over ${A.horizon_years} years if rates move today and stay there. A rise cuts the price at once, then the higher rate is earned on everything reinvested` +
    (FA.isNum(cross) ? `, so the lines meet after about ${cross} years.` : `; within ${A.horizon_years} years that has not yet made up the drop.`);
  const col = {'-100': 'var(--s3)', '0': 'var(--s1)', '100': 'var(--s8)'};
  const H = A.horizon_years, step = H > 20 ? 5 : H > 10 ? 2 : 1, xt = []; for (let t = 0; t <= H + 1e-9; t += step) xt.push(t);
  FA.lines($('fi-paths-chart'), {series: A.paths.map(p => ({name: p.name, points: p.points, color: col[String(p.bp)]})), height: 300, aria: 'Value of $10,000 over time under three rate moves',
    xTicks: xt, endLabels: false, xFmt: x => (Math.round(x * 10) / 10) + (x === 1 ? ' year' : ' years'), yFmt: FA.moneyC}); }
const strip = h => `<div class="fi-strip"><div class="fi-strip-h"><span><b>${E(h.label)}</b> <span class="muted">— ${E(h.what)}</span></span><span class="fi-strip-v">${E(p2(h.value))}</span></div>` +
  `<div class="fi-track" role="img" aria-label="${E(h.rank_text)}"><i class="fi-mid"></i><i class="fi-dot" style="left:${Math.max(0, Math.min(100, h.percentile))}%"></i></div>` +
  `<div class="fi-strip-f"><span>lowest on record</span><span>${E(h.rank_text)}${FA.isNum(h.median) ? ` · typical ${E(p2(h.median))}` : ''}</span><span>highest</span></div></div>`;
if (V.history) { $('fi-history').hidden = false; $('fi-history-strips').innerHTML = V.history.map(strip).join(''); }
if (V.yields) { $('fi-yields').hidden = false;
  const ok = V.yields.filter(y => FA.isNum(y.pct)); const max = Math.max(...ok.map(y => y.pct), 1e-9);
  $('fi-yields-bars').innerHTML = V.yields.map(y => `<div class="fi-yield"><div class="bar"><span class="l"><b>${E(y.label)}</b></span><div class="track"><div class="fill" style="width:${FA.isNum(y.pct) ? 100 * y.pct / max : 0}%;background:var(--s2)"></div></div><span class="n">${E(p2(y.pct))}</span></div><div class="muted fi-what">${E(y.what)}</div></div>`).join('');
  $('fi-yields-note').textContent = V.yields_note || ''; }
const D = V.deeper;
if (D) { $('fi-deeper').hidden = false; let h = '';
  if (D.rate_path) { const R = D.rate_path;
    h += `<h3>Short-term rates: what prices assume vs the Fed's projection</h3><p class="sub">The line is the one-year rate today's Treasury prices imply for each coming year. The red line is the median Federal Reserve official's projection${FA.isNum(R.longer_run_pct) ? `, which settles at ${E(p1(R.longer_run_pct))} in the longer run` : ''}${FA.isNum(R.fed_funds_pct) ? `. The Fed's rate today is ${E(p2(R.fed_funds_pct))}` : ''}. A gap between them is what a holder is paid, or charged, for disagreeing with the Fed.</p><div id="fi-ratepath"></div>`; }
  if (D.history) h += `<h3>Two more rates against history</h3>` + D.history.map(strip).join('');
  if (D.decomposition) { const dd = D.decomposition;
    h += `<h3>Where the fund's yield comes from</h3><div class="twrap"><table><tbody>${dd.rows.map(r => `<tr><td class="l">${E(r.label)}</td><td>${FA.isNum(r.value) ? E(r.value + (r.unit === '%' ? '%' : ' bp')) : 'not available'}</td></tr>`).join('')}</tbody></table></div>` +
      (dd.circularity_note ? `<p class="note">${E(dd.circularity_note)}</p>` : ''); }
  if (D.durations) h += `<h3>Three kinds of duration</h3><div class="twrap"><table><tbody>${D.durations.map(r => `<tr><td class="l">${E(r.label)}</td><td>${E(r.years.toFixed(1))} years</td><td class="l muted" style="white-space:normal">${E(r.what)}</td></tr>`).join('')}</tbody></table></div>`;
  $('fi-deeper-body').innerHTML = h;
  if (D.rate_path) { const R = D.rate_path; const draw = () => { const s = [];
      if (R.market.length) s.push({name: 'Priced in', points: R.market, color: 'var(--s1)'});
      if (R.fomc.length) s.push({name: 'Fed projection', points: R.fomc, color: 'var(--s8)'});
      FA.lines($('fi-ratepath'), {series: s, height: 220, xFmt: x => String(Math.round(x)), yFmt: y => y.toFixed(1) + '%', aria: 'Implied short rate path against the FOMC projection'}); };
    $('fi-deeper').addEventListener('toggle', draw, {once: true}); } }
$('fi-footer').innerHTML = `${E(V.footer)} <button class="btn quiet" type="button" id="fi-details">Details and assumptions</button>`;
$('fi-details').addEventListener('click', () => {
  let h = `<h3>Details and assumptions</h3><p class="note">${E(V.effective_rate_note)}</p>`;
  for (const g of V.disclosures) { h += `<h4>${E(g.heading)}</h4>`; if (g.chips.length) h += `<p class="muted" style="font-size:12px">${g.chips.map(E).join(' · ')}</p>`;
    for (const p of g.prose) h += `<p style="font-size:13px"><b>${E(p.label)}</b> — ${E(p.text)}</p>`; }
  FA.modal(h + `<p class="note">${E(V.closing_note)}</p>`); });
// card help: what each card answers, with this page's own figures
if (V.compare) { const cashR = V.compare.find(r => r.kind === 'cash'), mine = V.compare.find(r => r.kind === 'this');
  FA.help($('fi-cash'), {lead: 'What this holding earns a year against cash and plain Treasuries, all on the same yearly basis.',
    sections: cashR && mine ? [{title: 'The gap with cash', html: FA.flow([{label: mine.label, value: p2(mine.pct)}, {op: '−', label: cashR.label, value: p2(cashR.pct)}, {op: '=', label: 'extra a year', value: sgn(mine.pct - cashR.pct, ' pts')}]) +
      '<p>Cash pays its rate only until the next reset, which can come any month; a bond fund’s rate is set for years by the bonds it holds, so the gap can widen or close as cash rates move.</p>'}] : []}); }
if (A && A.paths.length) FA.help($('fi-paths'), {lead: `What $10,000 grows to over ${A.horizon_years} years if rates jump once today and then stay put.`,
  sections: [{title: 'Why the lines cross', html: (FA.isNum(A.up1_now_pct) && FA.isNum(A.up1_held_pct) ? `<p><b>Today:</b> if rates rise 1 point, the price ${A.up1_now_pct < 0 ? 'falls' : 'moves'} ${E(p1(Math.abs(A.up1_now_pct)))} at once.</p><p><b>Over ${A.horizon_years} years:</b> every payment is reinvested at the higher rate, so the yearly return works out to ${E(p1(A.up1_held_pct))} instead of ${E(p1(A.return_pct))}.</p>` : '<p>A rise cuts the price at once, then everything reinvested earns the higher rate.</p>') +
    (FA.isNum(A.crossover_years) ? `<p>After about ${A.crossover_years} years the extra income has made up the drop, which is where the lines cross.</p>` : '')}]});
if (V.history) { const h0 = V.history[0];
  FA.help($('fi-history'), {lead: 'Where today’s yields rank against every day on record.',
    sections: [{title: 'Reading a strip', html: `<p>The dot is today; the tick in the middle is a typical day.${h0 ? ` ${E(h0.label)} is ${E(p2(h0.value))}: ${E(h0.rank_text.charAt(0).toLowerCase() + h0.rank_text.slice(1))}.` : ''}</p><p>A high rank says yields are high by historical standards; it does not say which way they go next.</p>`}]}); }
if (V.yields) FA.help($('fi-yields'), {lead: 'Three yields the fund publishes, each measuring something different.',
  sections: [{title: 'Which is which', html: V.yields.map(y => `<p><b>${E(y.label)}</b> ${E(p2(y.pct))}: ${E(y.what)}</p>`).join('')}]});
})();
"""

CSS = """
<style>
.fi-strip{padding:10px 0;border-bottom:1px solid var(--grid)}.fi-strip:last-child{border-bottom:0}
.fi-strip-h{display:flex;justify-content:space-between;gap:12px;font-size:13.5px;flex-wrap:wrap}
.fi-strip-v{font-weight:600;font-variant-numeric:tabular-nums}
.fi-track{position:relative;height:10px;border-radius:5px;margin:8px 0 4px;background:linear-gradient(90deg,color-mix(in srgb,var(--s1) 8%,var(--grid)),color-mix(in srgb,var(--s1) 30%,var(--grid)))}
.fi-mid{position:absolute;left:50%;top:-3px;width:2px;height:16px;background:var(--muted);transform:translateX(-1px)}
.fi-dot{position:absolute;top:50%;width:16px;height:16px;border-radius:50%;background:var(--s1);border:2px solid var(--surface);box-shadow:0 0 0 1px var(--s1);transform:translate(-50%,-50%)}
.fi-strip-f{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;color:var(--muted)}
.fi-strip-f span:nth-child(2){color:var(--ink2);text-align:center}
.fi-yield{margin-bottom:8px}.fi-what{font-size:12px;margin:-2px 0 0}
#fi-deeper summary{font-size:14px;color:var(--ink)}#fi-deeper h3{font-size:14px;margin:18px 0 4px}
.modal h4{margin:16px 0 4px;font-size:14px}
#fi-footer{display:flex;gap:12px;align-items:center;flex-wrap:wrap;max-width:none}
</style>
"""


def build(payload: Any) -> tuple[str, str, list[str]]:
    if not isinstance(payload, dict):
        raise InvalidInput("input must be a JSON object collecting the fixed-income script results")
    if not any(isinstance(payload.get(k), dict) for k in ("horizon", "rates", "fund")):
        raise InvalidInput(
            "input must carry at least one of horizon (horizon.py), rates (rates.py) or fund (fund.py)"
        )
    symbol = payload.get("symbol")
    symbol = str(symbol) if isinstance(symbol, (str, int, float)) and not isinstance(symbol, bool) else ""
    title = f"Fixed Income — {symbol}" if symbol else "Fixed Income"
    data, sections = view(payload, symbol)
    return page.render(title, data, CSS + BODY, SCRIPT), title, sections


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read the fixed-income JSON: {exc}") from exc
        markup, title, sections = build(payload)
        out = page.write(ns.out, markup)
        return {"out": str(out), "title": title, "sections": sections}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
