#!/usr/bin/env python3
"""Usage: render_case.py [--in page.json] --out page.html

Turns a real-estate deep review into one self-contained HTML page for the Artifact tool. Input::

    {"as_of", "headline" (25 words at most), "summary", "case": <property_case.py output>,
     "missing_roles": [...], "notes": [...]}

Sections: the headline, stat tiles, Scenarios, What moves the answer, Inputs and evidence, One-time
costs, Comparable sales and rents, Evidence on both sides, Open questions, What to watch, Flags. A
section with nothing in it stays hidden. Prints {"out", "title", "scenarios", "flags"}. Exit 2 on a
missing headline or case, a headline over the limit, or one of the verbs the compliance rules forbid
in the headline, summary, notes or a scenario's name or why. Sourced claims keep their own words.
Every figure comes from property_case.py; nothing is fetched at runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402
from second_opinion.summary_card import FORBIDDEN_VERB_RE  # noqa: E402

HEADLINE_WORDS = 25

BODY = """
<style>
.lead{border:1px solid var(--grid);border-radius:8px;padding:14px 16px;margin:0 0 20px}
.lead .h{font-size:18px;font-weight:600;margin:0 0 6px}.lead .s{font-size:14px;color:var(--ink2);margin:0}
.src{color:var(--muted);font-size:12px}.scroll{overflow-x:auto}.muted13{color:var(--muted);font-size:13px}
table.t{width:100%;border-collapse:collapse;font-size:13px}table.t th{font-weight:500;color:var(--muted);font-size:12px}
table.t td,table.t th{padding:4px 10px 4px 0;border-bottom:1px solid var(--grid);vertical-align:top;text-align:left;white-space:normal}table.t .r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.soft{font-size:11px;padding:1px 6px;border:1px solid var(--warn);border-radius:10px;color:var(--warn);white-space:nowrap}
.basis{font-size:11px;padding:1px 6px;border:1px solid var(--grid);border-radius:10px;color:var(--ink2);white-space:nowrap}
.side h3{font-size:13px;margin:10px 0 2px}.side ul,.qs{margin:4px 0 0;padding-left:18px;font-size:13px}
.item{border-bottom:1px solid var(--grid);padding:8px 0;font-size:13px}.item b{font-size:14px}
</style>
<h1 id="h1"></h1>
<p class="sub" id="sub"></p>
<div class="lead"><p class="h" id="headline"></p><p class="s" id="summary"></p></div>
<div class="tiles" id="tiles"></div>
<section class="card" id="sc-card"><h2>Scenarios</h2><p class="sub">Each runs the same calculators on the base inputs plus its own changes. The first is the central case.</p><div class="scroll" id="sc"></div></section>
<section class="card" id="dr-card"><h2>What moves the answer</h2><p class="sub">The central case rerun with one change at a time, largest swing first. Soft means the evidence is a regional figure, an assumption or over a year old.</p><div class="scroll" id="dr"></div></section>
<section class="card" id="in-card"><h2>Inputs and evidence</h2><p class="sub">Every number the calculators used, and what it rests on.</p><div class="scroll" id="in"></div></section>
<section class="card" id="co-card" hidden><h2>One-time costs</h2><p class="sub">Costs the documents and research turned up. Each scenario uses their low, middle or high total.</p><div class="scroll" id="co"></div></section>
<section class="card" id="cm-card" hidden><h2>Comparable sales and rents</h2><p class="sub" id="cm-sub"></p><div class="scroll" id="cm"></div></section>
<section class="card side" id="ev-card"><h2>Evidence on both sides</h2><div id="ev"></div></section>
<section class="card" id="qs-card" hidden><h2>Open questions</h2><p class="sub">What this review could not settle, and who can.</p><ul class="qs" id="qs"></ul></section>
<section class="card" id="wa-card" hidden><h2>What to watch</h2><p class="sub">What would break the central case, earliest check first.</p><div id="wa"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Scenarios are stated assumptions, not forecasts, and this is not an appraisal, inspection, or title or legal opinion. It makes no call on buying or on a price. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, C = D.case, g = id => document.getElementById(id), esc = F.esc;
  const rental = C.subject.use === 'rental', money = v => F.money(v, 0), pct = (v, dp = 2) => F.pct(v, dp), S = C.scenarios, mid = S[0];
  const LABEL = {price: 'Price', down_payment: 'Down payment', rate: 'Mortgage rate', years: 'Loan term (years)', horizon_years: 'Horizon (years)', hold_years: 'Hold (years)', closing_costs: 'Closing costs', rent: 'Rent (monthly)', vacancy_rate: 'Vacancy', property_tax_annual: 'Property tax (yearly)', property_tax_rate: 'Property tax rate', insurance_annual: 'Insurance (yearly)', maintenance_rate: 'Maintenance', management_rate: 'Management', hoa_monthly: 'HOA (monthly)', utilities_annual: 'Utilities (yearly)', other_annual: 'Other costs (yearly)', capex_reserve_rate: 'Capital reserve', leasing_rate: 'Leasing costs', rent_growth: 'Rent growth', expense_growth: 'Expense growth', tax_growth: 'Property tax growth', appreciation: 'Appreciation', sell_closing_rate: 'Selling costs', buy_closing_rate: 'Buying costs', investment_return: 'Investment return', pmi_rate: 'PMI', one_time_costs: 'One-time costs'};
  const label = f => LABEL[f] || f;
  const value = (f, v) => !F.isNum(v) ? '—' : /years$/.test(f) ? String(v) : /(rate|growth|appreciation|return)$/.test(f) ? pct(v) : money(v);
  const name = C.result_label === 'total_profit' ? 'Total profit over the hold' : 'Buying against renting at the horizon';
  const worst = S.reduce((a, b) => b.result < a.result ? b : a, mid);
  g('h1').textContent = C.subject.name;
  g('sub').textContent = `As of ${D.as_of} · ${C.subject.kind === 'market' ? 'market review of a typical home' : 'property review'} · ${rental ? 'as a rental' : 'as a home'}`;
  g('headline').textContent = D.headline; g('summary').textContent = D.summary || '';

  const tile = (k, v, d) => `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="d">${esc(d)}</div></div>`;
  const spot = C.soft_spot;
  g('tiles').innerHTML = [
    tile('Central result', money(mid.result), name.toLowerCase()),
    tile('Worst scenario', money(worst.result), worst.name),
    rental ? tile('First-year cash flow', money(mid.cash_flow), `DSCR ${F.num(mid.dscr)} · cap rate ${pct(mid.cap_rate)}`) : tile('Monthly cost', money(mid.monthly_buy), `year one, against ${money(mid.monthly_rent)} rent`),
    spot ? tile('Softest large input', label(spot.field), `moves the result ${money(spot.swing)}, on ${spot.basis || 'a scenario’s'} evidence`) : tile('Softest large input', 'None', 'no driver rests on soft evidence'),
    C.even_price ? tile('Comes out even at', money(C.even_price.price), `${F.pct(C.even_price.vs_price, 1, true)} from the price, on ${C.even_price.measure}`) : '',
  ].join('');

  const cols = rental ? [['Total profit', s => money(s.result)], ['IRR', s => pct(s.irr)], ['NOI', s => money(s.noi)], ['DSCR', s => F.num(s.dscr)], ['Cash flow', s => money(s.cash_flow)], ['Cash-on-cash', s => pct(s.cash_on_cash)]]
    : [['Buy vs rent', s => money(s.result)], ['Breakeven year', s => s.breakeven_year ?? 'none in horizon'], ['Monthly cost', s => money(s.monthly_buy)], ['Rent', s => money(s.monthly_rent)], ['PITI', s => money(s.piti)]];
  g('sc').innerHTML = `<table class="t"><tr><th>Scenario</th>${cols.map(c => `<th class="r">${esc(c[0])}</th>`).join('')}</tr>${S.map(s => `<tr><td><b>${esc(s.name)}</b><br><span class="src">${esc(s.why)}${Object.keys(s.changes).length ? ' · ' + Object.entries(s.changes).map(([f, c]) => `${esc(label(f))} ${esc(value(f, c.value))}`).join(', ') : ''}${C.costs.length ? ` · one-time costs ${money(s.one_time_cost)}` : ''}</span></td>${cols.map(c => `<td class="r">${esc(c[1](s))}</td>`).join('')}</tr>`).join('')}</table>`;
  F.help(g('sc-card'), {lead: rental ? 'Total profit is cash flow over the hold plus sale proceeds, less the cash put in, from the rental calculator. IRR is the same flows as a yearly rate. DSCR is NOI over the mortgage payments.' : 'Buy vs rent is the buyer’s net worth less the renter’s at the horizon, with the renter investing the upfront cash and the cost difference each year. Breakeven year is when buying first comes out ahead.'});

  g('dr').innerHTML = C.drivers.length ? `<table class="t"><tr><th>Input</th><th class="r">Central</th><th class="r">Tested</th><th class="r">Swing</th><th>Rests on</th></tr>${C.drivers.map(d => `<tr><td>${esc(label(d.field))} <span class="src">${esc(d.scenario)}</span></td><td class="r">${esc(value(d.field, d.central_value))}</td><td class="r">${esc(value(d.field, d.tested_value))}</td><td class="r">${esc((d.swing > 0 ? '+' : '') + money(d.swing))}</td><td>${d.soft ? '<span class="soft">soft</span> ' : ''}${esc(d.source || d.tested_source || '—')}${d.date ? ` <span class="src">${esc(d.date)}</span>` : ''}</td></tr>`).join('')}</table>` : '<p class="muted">No scenario changes an input.</p>';
  F.help(g('dr-card'), {lead: 'Each row reruns the central case with only that one change, so the swings overlap and do not add up. A large swing on soft evidence is the first thing worth pinning down.'});

  g('in').innerHTML = `<table class="t"><tr><th>Input</th><th class="r">Value</th><th>Basis</th><th>Source</th></tr>${Object.entries(C.inputs).map(([f, v]) => `<tr><td>${esc(label(f))}</td><td class="r">${esc(value(f, v.value))}</td><td><span class="basis">${esc(v.basis)}</span></td><td>${esc(v.source)} <span class="src">${esc(v.date)}</span></td></tr>`).join('')}</table>`;
  F.help(g('in-card'), {lead: 'Document means read from a document on this property. Stated means the person gave it. Local means a source for this area. Regional means a wider figure used in its place. Assumption means no evidence was found, and the source says why the number was chosen.'});

  if (C.costs.length) { g('co-card').hidden = false;
    g('co').innerHTML = `<table class="t"><tr><th>Item</th><th class="r">Low</th><th class="r">High</th><th>Source</th></tr>${C.costs.map(c => `<tr><td>${esc(c.item)}</td><td class="r">${money(c.low)}</td><td class="r">${money(c.high)}</td><td>${esc(c.source)} <span class="src">${esc(c.date)}</span></td></tr>`).join('')}</table>`;
    F.help(g('co-card'), {lead: 'One-time costs are added to closing costs for a rental and to the buying costs for a home. Repair estimates vary by contractor, so the range is itself uncertain.'}); }

  if (C.comps) { const A = C.comps.sales, R = C.comps.rents; g('cm-card').hidden = false;
    g('cm-sub').textContent = `Medians use the ${A.recent} sales from the last ${A.window_days} days and the ${R.recent} rents from the last ${R.window_days} days.`;
    const rows = (xs, key) => xs.map(c => `<tr><td>${esc(c.address || '—')}</td><td class="r">${money(c[key])}</td><td class="r">${c.sqft ?? '—'}</td><td>${esc(c.source)} <span class="src">${esc(c.date)}</span></td></tr>`).join('');
    const part = (t, st, key, med, imp) => `<h3 style="font-size:13px;margin:10px 0 2px">${t}</h3><p class="muted13">Median ${money(st[med])}${F.isNum(st.median_per_sqft) ? ` · ${F.money(st.median_per_sqft, 2)} per sq ft` : ''} · implies ${money(st[imp])} · subject ${F.isNum(st.gap) ? F.pct(st.gap, 1, true) : '—'} against that</p><table class="t"><tr><th>Address</th><th class="r">${key === 'price' ? 'Sold' : 'Rent'}</th><th class="r">Sq ft</th><th>Source</th></tr>${rows(st.rows, key)}</table>`;
    g('cm').innerHTML = part('Sales', A, 'price', 'median_price', 'implied_value') + part('Rents', R, 'rent', 'median_rent', 'implied_rent');
    F.help(g('cm-card'), {lead: 'The implied figure is the median per square foot times the subject’s size, or the plain median when sizes are missing. Few comparables, or ones that differ in condition or location, make the gap weak evidence.'}); }

  const claims = xs => xs.length ? `<ul>${xs.map(c => `<li>${esc(c.claim)} <span class="src">${esc(c.source)}, ${esc(c.date)}</span></li>`).join('')}</ul>` : '<p class="muted13">None found.</p>';
  g('ev').innerHTML = `<h3>In favor of the central case</h3>${claims(C.findings.filter(f => f.side === 'for'))}<h3>Against it</h3>${claims(C.findings.filter(f => f.side === 'against'))}`;
  F.help(g('ev-card'), {lead: 'Dated findings from the documents and local research, sorted by which way they cut against the central case.'});

  if (C.open_questions.length) { g('qs-card').hidden = false;
    g('qs').innerHTML = C.open_questions.map(q => `<li>${esc(q.question)}${q.who ? ` <span class="src">${esc(q.who)}</span>` : ''}</li>`).join('');
    F.help(g('qs-card'), {lead: 'Questions public sources and the documents could not answer. An answer can change an input, and a later check can rerun the case with it.'}); }

  if (C.watch.length) { g('wa-card').hidden = false;
    g('wa').innerHTML = [...C.watch].sort((a, b) => a.check_by < b.check_by ? -1 : 1).map(w => `<div class="item"><b>${esc(w.what)}</b> <span class="src">by ${esc(w.check_by)}</span><div>Breaks if: ${esc(w.breaks_if)}</div></div>`).join('');
    F.help(g('wa-card'), {lead: 'Each item names evidence to check by a date and what result would break the central case. A later check lists the items that have come due.'}); }

  const flags = [...C.flags, ...(D.missing_roles || []).map(r => ({code: 'RESEARCH_MISSING', message: `The ${r} role did not complete, so its findings are absent.`})), ...(D.notes || []).map(n => ({code: 'NOTE', message: n}))];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${esc(f.code)}</b>${esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render_case.py: {message}")


def _no_advice(text: object, what: str) -> None:
    found = FORBIDDEN_VERB_RE.search(text) if isinstance(text, str) else None
    if found:
        raise InvalidInput(f"{what} uses the forbidden word {found.group(0)!r}")


def _validate(data: object) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a JSON object")
    case = data.get("case")
    if not isinstance(case, dict) or not case.get("scenarios") or not isinstance(case.get("subject"), dict):
        raise InvalidInput("case (a property_case.py result) is required")
    headline = data.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        raise InvalidInput("headline is required")
    words = len(headline.split())
    if words > HEADLINE_WORDS:
        raise InvalidInput(f"headline is {words} words; the limit is {HEADLINE_WORDS} words")
    _no_advice(headline, "headline")
    _no_advice(data.get("summary"), "summary")
    for note in data.get("notes") or []:
        _no_advice(note, "a note")
    for s in case["scenarios"]:
        _no_advice(s.get("name"), "a scenario name")
        _no_advice(s.get("why"), f"scenario {s.get('name')} why")


def build(data: dict) -> tuple[str, str, dict]:
    _validate(data)
    title = "Property Deep Review"
    markup = page.render(title, data, BODY, SCRIPT)
    case = data["case"]
    return title, markup, {"title": title, "scenarios": len(case["scenarios"]),
                           "flags": len(case.get("flags") or []) + len(data.get("missing_roles") or []) + len(data.get("notes") or [])}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render_case.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read the case JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
