#!/usr/bin/env python3
"""Usage: render_plans.py [--in page.json] --out page.html

Turns a tax-aware deep review into one self-contained HTML page for the Artifact tool. Input::

    {"as_of", "headline" (25 words at most), "summary", "plans": <tax_plans.py output>,
     "missing_roles": [...], "notes": [...]}

Sections: the disclaimer line, the headline, stat tiles, Plans compared, Year by year, What decides
it, Rules behind the math, Flags, Not modelled. Prints {"out", "title", "plans", "flags"}. Exit 2 on
a missing headline or plans, a headline over the limit, or one of the verbs the compliance rules
forbid in the headline, summary, notes or a plan's name or why. Every figure comes from tax_plans.py;
nothing is fetched at runtime.
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
.src{color:var(--muted);font-size:12px}.scroll{overflow-x:auto}.dis{font-size:13px;color:var(--ink2);margin:0 0 14px}
table.t{width:100%;border-collapse:collapse;font-size:13px}table.t th{font-weight:500;color:var(--muted);font-size:12px}
table.t td,table.t th{padding:4px 10px 4px 0;border-bottom:1px solid var(--grid);vertical-align:top;text-align:left;white-space:normal}table.t .r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{font-size:11px;padding:1px 6px;border:1px solid var(--grid);border-radius:10px;color:var(--ink2);white-space:nowrap}.tag.warn{color:var(--warn);border-color:var(--warn)}
h3.pl{font-size:13px;margin:12px 0 2px}.nm{font-size:13px;margin:4px 0 0;padding-left:18px}
</style>
<h1>Tax plan comparison</h1>
<p class="sub" id="sub"></p>
<p class="dis">Estimate for planning at the stated rates and assumptions; not tax advice or a return.</p>
<div class="lead"><p class="h" id="headline"></p><p class="s" id="summary"></p></div>
<div class="tiles" id="tiles"></div>
<section class="card" id="pl-card"><h2>Plans compared</h2><p class="sub">Each plan against doing nothing, by the same end date. Highest after-tax wealth first.</p><div class="scroll" id="pl"></div></section>
<section class="card" id="yr-card"><h2>Year by year</h2><p class="sub">The tax each plan runs up. Activity is the tax above what income and sales already made would owe, which every plan pays.</p><div class="scroll" id="yr"></div></section>
<section class="card" id="te-card"><h2>What decides it</h2><p class="sub" id="te-sub"></p><div class="scroll" id="te"></div></section>
<section class="card" id="ru-card"><h2>Rules behind the math</h2><p class="sub">Each rule and table the math uses, with its source and date. Tags mark a secondary source or a projected table.</p><div class="scroll" id="ru"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<section data-help="none"><h2>Not modelled</h2><ul class="nm"><li>AMT and the alternative minimum tax credit</li><li>State rules beyond a flat rate, and state treatment of conversions</li><li>Medicare premium surcharges (IRMAA) and ACA credits, which a conversion or a large gain can change</li><li>Required minimum distributions and early-withdrawal penalties</li><li>The qualified-dividend holding test, and REIT or bond-fund distributions</li><li>Stock-award vesting and withholding beyond the figures given, and any change in employment</li><li>Estimated-tax penalties and their safe harbors</li><li>Dividends paid along the way, and different growth for different holdings</li></ul></section>
<p class="note">Growth and exit rates are stated assumptions, not forecasts. Which plan to follow, if any, is for you and your tax professional. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, P = D.plans, F = FA, g = id => document.getElementById(id), esc = F.esc;
  const money = v => F.isNum(v) ? F.money(v, 0) : '—', signed = v => F.isNum(v) ? (v > 0 ? '+' : '') + F.money(v, 0) : '—', pct = v => F.pct(v, 2);
  const top = P.plans[0], base = P.plans.find(p => !p.actions.length), A = P.inputs.assumptions;
  g('sub').textContent = `As of ${D.as_of} · ${P.filing} · ${P.years[0]} to ${P.years[P.years.length - 1]} · growth ${pct(A.growth)} · exit rates ${pct(A.exit_long_term)} long-term, ${pct(A.exit_ordinary)} ordinary`;
  g('headline').textContent = D.headline; g('summary').textContent = D.summary || '';
  const tile = (k, v, d) => `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="d">${esc(d)}</div></div>`;
  const flips = P.deciding_assumptions.length;
  g('tiles').innerHTML = [
    tile('Highest on these assumptions', top.name, `${signed(top.wealth_vs_baseline)} against doing nothing`),
    tile('Tax it runs up', signed(top.tax_vs_baseline), 'against doing nothing, over the period'),
    tile('Assumptions that change the order', `${flips} of ${P.tests.length}`, flips ? P.deciding_assumptions.join(', ') : 'the order held in every test'),
  ].join('');

  const acts = p => p.actions.length ? p.actions.map(a => a.type === 'sell' ? `Sell ${F.num(a.units, a.units % 1 ? 2 : 0)} ${esc(a.symbol)} in ${a.year}` : `Convert ${money(a.amount)} in ${a.year}`).join('; ') : 'No actions';
  g('pl').innerHTML = `<table class="t"><tr><th>Plan</th><th class="r">After-tax wealth</th><th class="r">Against doing nothing</th><th class="r">Tax paid</th><th class="r">Against doing nothing</th><th class="r">Roth at the end</th></tr>${P.plans.map(p => `<tr><td><b>${esc(p.name)}</b><br><span class="src">${esc(p.why)} · ${acts(p)}</span></td><td class="r">${money(p.end.after_tax_wealth)}</td><td class="r">${signed(p.wealth_vs_baseline)}</td><td class="r">${money(p.total_tax)}</td><td class="r">${signed(p.tax_vs_baseline)}</td><td class="r">${money(p.end.roth)}</td></tr>`).join('')}</table>`;
  F.help(g('pl-card'), {lead: 'After-tax wealth is what the affected accounts would hold at the end date, less tax on what is still untaxed at the stated exit rates. Paying more tax can still leave more wealth, as a conversion is built to do, so tax paid alone does not compare plans. The first row is highest only on these assumptions.'});

  g('yr').innerHTML = P.plans.map(p => `<h3 class="pl">${esc(p.name)}</h3><table class="t"><tr><th>Year</th><th class="r">Taxable ordinary</th><th class="r">Short-term net</th><th class="r">Long-term net</th><th class="r">Loss deducted</th><th class="r">Conversion taxed</th><th class="r">Total tax</th><th class="r">Activity</th><th class="r">Due at filing</th></tr>${p.years.map(y => `<tr><td>${y.year}</td><td class="r">${money(y.taxable_ordinary)}</td><td class="r">${money(y.short_term_net)}</td><td class="r">${money(y.long_term_net)}</td><td class="r">${money(y.loss_deducted)}</td><td class="r">${money(y.conversion_taxable)}</td><td class="r">${money(y.total_tax)}</td><td class="r">${signed(y.activity_tax)}</td><td class="r">${money(y.balance_due)}</td></tr>`).join('')}</table>`).join('');
  F.help(g('yr-card'), {lead: 'Due at filing is total tax less the withholding given, and it is negative for a refund. A large balance can also bring an estimated-tax penalty, which is not modelled.'});

  g('te-sub').textContent = P.tests.length ? 'Every plan rerun with other assumptions. A flip means a different plan comes out highest.' : 'No assumption tests were run.';
  g('te').innerHTML = P.tests.length ? `<table class="t"><tr><th>Test</th><th>Highest</th>${P.plans.map(p => `<th class="r">${esc(p.name)}</th>`).join('')}</tr>${P.tests.map(t => `<tr><td><b>${esc(t.name)}</b> ${t.flips ? '<span class="tag warn">flips</span>' : ''}<br><span class="src">${esc(t.why)} · ${Object.entries(t.changes).map(([k, v]) => `${esc(k.replace(/_/g, ' '))} ${pct(v)}`).join(', ')}</span></td><td>${esc(t.leading)}</td>${P.plans.map(p => `<td class="r">${money(t.wealth[p.name])}</td>`).join('')}</tr>`).join('')}</table>` : '';
  F.help(g('te-card'), {lead: 'No one knows future growth or future tax rates. A comparison that flips across reasonable values depends on that guess more than on the math.'});

  const tag = (show, t) => show ? ` <span class="tag warn">${t}</span>` : '';
  g('ru').innerHTML = `<table class="t"><tr><th>Rule</th><th>What it says</th><th>Source</th></tr>${P.rules.map(r => `<tr><td>${esc(r.rule.replace(/_/g, ' '))}${tag(!r.primary, 'secondary')}</td><td>${esc(r.says)}</td><td>${esc(r.source)} <span class="src">${esc(r.date)}</span></td></tr>`).join('')}${Object.entries(P.rule_tables).map(([y, t]) => `<tr><td>${esc(y)} tables${tag(!t.primary, 'secondary')}${tag(t.status === 'projected', 'projected')}</td><td>Deduction ${money(t.standard_deduction)}, top ordinary rate ${pct(t.ordinary[t.ordinary.length - 1][1])}, loss limit ${money(t.loss_limit)}</td><td>${esc(t.source)} <span class="src">${esc(t.date)}</span></td></tr>`).join('')}</table>`;
  F.help(g('ru-card'), {lead: 'A primary source is the statute, a regulation or an IRS publication. Tax law changes, and a date shows when the rule was last confirmed, so a tax professional can check it for your situation.'});

  const flags = [...P.flags, ...(D.missing_roles || []).map(r => ({code: 'RESEARCH_MISSING', message: `The ${r} role did not complete, so its findings are absent.`})), ...(D.notes || []).map(n => ({code: 'NOTE', message: n}))];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${esc(f.code)}</b>${esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render_plans.py: {message}")


def _no_advice(text: object, what: str) -> None:
    found = FORBIDDEN_VERB_RE.search(text) if isinstance(text, str) else None
    if found:
        raise InvalidInput(f"{what} uses the forbidden word {found.group(0)!r}")


def _validate(data: object) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a JSON object")
    plans = data.get("plans")
    if not isinstance(plans, dict) or not plans.get("plans") or "inputs" not in plans:
        raise InvalidInput("plans (a tax_plans.py result) is required")
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
    for p in plans["plans"]:
        _no_advice(p.get("name"), "a plan name")
        _no_advice(p.get("why"), f"plan {p.get('name')} why")


def build(data: dict) -> tuple[str, str, dict]:
    _validate(data)
    title = "Tax Plan Comparison"
    markup = page.render(title, data, BODY, SCRIPT)
    plans = data["plans"]
    return title, markup, {"title": title, "plans": len(plans["plans"]),
                           "flags": len(plans.get("flags") or []) + len(data.get("missing_roles") or []) + len(data.get("notes") or [])}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render_plans.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read the plan JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
