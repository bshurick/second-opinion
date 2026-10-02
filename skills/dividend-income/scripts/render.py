#!/usr/bin/env python3
"""Usage: render.py [--in dividend-income.json] --out page.html

Turns one ``dividends.py`` (or ``income.py``) result (a file, or stdin when ``--in`` is omitted) into a
self-contained interactive HTML page for the Artifact tool: stat tiles for projected annual income,
portfolio yield, yield on cost and trailing 12 months; income by month as bars (the payers of each month
in the tooltip); the upcoming ex-date list sorted by estimated date; a sortable holdings table (income,
yields, growth, payout, safety, dividend cuts marked) with search and a payers-only toggle, the
yield-context columns when the run included them; and the flags. Prints
``{"out": path, "title": ..., "positions": n, "payers": n, "flags": n}``. Exit 2 on a missing or
malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the income JSON; the page formats, sorts and filters, it never recomputes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Dividend Income"

BODY = """
<h1>Dividend Income</h1>
<p class="sub" id="asof">Dividend income report; enable JavaScript to see the figures.</p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<div class="grid2">
  <div class="card"><h2 id="h-monthly">Income by month</h2><p class="sub" id="monthly-sub"></p><div id="monthly"></div></div>
  <div class="card"><h2 id="h-exdates">Upcoming ex-dates</h2><p class="sub">The next estimated cutoff date for each payer: own the shares before it to receive that dividend.</p><div class="twrap" id="exdates"></div>
    <p class="note">Dates are estimates: the last regular ex-date plus the usual interval. Amounts are the last regular dividend times the units held.</p></div>
</div>
<section class="card"><h2 id="h-holdings">Holdings</h2>
  <p class="sub" id="holdings-sub">One row per position: what it paid last, what it is on track to pay over the next year, and how secure that looks.</p>
  <div class="controls">
    <input id="q" type="search" placeholder="Search symbol" aria-label="Search holdings">
    <button class="chip" id="payers-only" type="button" aria-pressed="false">Payers only</button>
    <span class="muted" id="count"></span>
  </div>
  <div class="twrap" id="holdings"></div>
  <p class="note" id="nonpayers"></p>
  <p class="note" id="safety-note">Safety is a heuristic screen built only from the dividend history, not a rating. A <span class="neg">cut</span> mark means the regular dividend fell in a full calendar year of the history.</p>
</section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Forward figures are the last regular dividend times the inferred payments per year; they assume the payer keeps paying. Trailing figures are what was actually declared by ex-date in the last 12 months. Yield on cost that exceeds the current yield means the holding was bought cheaper, not that it is a better investment. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, T = D.totals || {}, F = FA;
  const g = id => document.getElementById(id);
  // glossary terms this page needs beyond the shared list (plain sentence, link to more)
  Object.assign(FA.glossary, {
    "dividend": ["Cash a company pays its shareholders out of its profits, usually every quarter or every month.", "https://www.investopedia.com/terms/d/dividend.asp"],
    "forward dividend rate": ["The last regular dividend times the payments per year: what one share would pay over the next twelve months if nothing changes.", "https://www.investopedia.com/terms/f/forward-dividend-yield.asp"],
    "dividend growth": ["How fast the dividend per share has risen (or fallen) per year over the period shown.", "https://www.investopedia.com/terms/d/dividendgrowthrate.asp"],
  });
  // table headers built by FA.table are plain text; swap in the glossary markup after the table exists (the header is built once)
  const termHeads = (root, cols) => {
    root.querySelectorAll('th[data-key]').forEach(th => { const c = cols.find(x => x.key === th.dataset.key); if (c && c.term) th.innerHTML = FA.term(c.term, c.label); });
    FA.armTerms(root);
  };
  const src = D.sources;
  g('asof').textContent = `As of ${D.as_of || '—'}` + (src ? ` · holdings ${src.holdings || '—'} · dividends ${src.dividends || '—'} · fundamentals ${src.fundamentals || 'not fetched'}` : '');
  FA.explain(g('explain'), `<p>This page adds up the ${FA.term('dividend', 'dividends')} your holdings pay. <b>Projected annual income</b> is each holding's ${FA.term('forward dividend rate')} times the units you own, so it assumes every payer keeps paying; <b>${FA.term('trailing 12 months')}</b> is what was actually declared over the past year.</p>` +
    `<p>The bars show the months the money is expected to arrive; the table lists each holding's ${FA.term('dividend yield', 'yield')}, ${FA.term('yield on cost')}, ${FA.term('dividend growth', 'growth')} and ${FA.term('payout ratio')}. The figures come from your connected holdings and each payer's dividend history, not from forecasts.</p>` +
    `<p>The caveat that matters most: dividends are never guaranteed. A <span class="neg">cut</span> mark or a high payout ratio means that income is less secure than the headline suggests.</p>`);
  const monthName = m => { const [y, mo] = String(m).split('-'); return new Date(+y, +mo - 1, 1).toLocaleDateString('en-US', {month: 'short', year: 'numeric'}); };
  // tiles
  const tiles = [
    [FA.term('forward dividend rate', 'Projected annual income'), F.money(T.annual_income), `${T.payer_count ?? '—'} of ${T.position_count ?? '—'} positions pay`],
    [FA.term('dividend yield', 'Portfolio yield'), F.pct(T.portfolio_yield, 2), F.isNum(T.market_value) ? `on ${F.money(T.market_value, 0)} market value` : ''],
    [FA.term('yield on cost', 'Yield on cost'), F.pct(T.yield_on_cost, 2), F.isNum(T.cost_basis) ? `on ${F.money(T.cost_basis, 0)} ${FA.term('cost basis')}` : 'cost basis unknown for a payer'],
    [FA.term('trailing 12 months', 'Trailing 12 months'), F.money(T.ttm_income), T.top_payer ? `top payer ${F.esc(T.top_payer)} · ${F.pct(T.top_payer_share)} of income` : ''],
  ];
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  FA.armTerms(g('tiles'));
  // section headings (static text stays for readers without JavaScript)
  g('h-monthly').innerHTML = `${FA.term('dividend', 'Income')} by month`;
  g('h-exdates').innerHTML = `Upcoming ${FA.term('ex-dividend date', 'ex-dates')}`;
  g('safety-note').innerHTML = `Safety is a heuristic screen built only from the ${FA.term('dividend')} history, not a rating. A <span class="neg">cut</span> mark means the regular dividend fell in a full calendar year of the history.`;
  FA.armTerms(document);
  // income by month
  const months = D.monthly || [];
  const total12 = months.reduce((a, m) => a + (m.income || 0), 0);
  g('monthly-sub').textContent = months.length ? `Next ${months.length} months · ${F.money(total12)} scheduled` : 'No schedule.';
  if (months.some(m => (m.income || 0) > 0)) F.bars(g('monthly'), months.map(m => ({label: monthName(m.month), share: m.income, color: 'var(--s1)', text: F.money(m.income),
    tip: `<b>${F.esc(monthName(m.month))}</b> ${F.money(m.income)}<br>${(m.payers || []).length ? F.esc(m.payers.join(', ')) : 'no payers'}`})));
  else g('monthly').innerHTML = '<span class="muted">no scheduled income</span>';
  // upcoming ex-dates
  const P = D.positions || [];
  const payers = P.filter(p => (p.annual_income || 0) > 0);
  const ex = payers.filter(p => p.next_ex_date_est).sort((a, b) => String(a.next_ex_date_est).localeCompare(String(b.next_ex_date_est)) || a.symbol.localeCompare(b.symbol));
  g('exdates').innerHTML = ex.length ? `<table><thead><tr><th class="l">Symbol</th><th class="l">${FA.term('ex-dividend date', 'Est. ex-date')}</th><th>${FA.term('dividend', 'Per share')}</th><th>Units</th><th>Est. amount</th></tr></thead><tbody>` + ex.map(p =>
    `<tr><td class="l"><b>${F.esc(p.symbol)}</b></td><td class="l">${F.esc(p.next_ex_date_est)}${p.next_ex_date_est < (D.as_of || '') ? ' <span class="muted">(passed)</span>' : ''}</td><td>${F.isNum(p.last_dividend) ? '$' + F.num(p.last_dividend, 4) : '—'}</td><td>${F.num(p.units, 3)}</td><td>${F.money(p.next_ex_amount_est)}</td></tr>`).join('') + '</tbody></table>'
    : '<span class="muted">no estimated ex-dates</span>';
  FA.armTerms(g('exdates'));
  // holdings
  const hasCtx = P.some(p => 'price_1y_change' in p);
  const rows = P.map(p => ({...p, safety_score: p.safety ? p.safety.score : null, safety_flags: p.safety ? (p.safety.flags || []).join(' ') : '',
    cut: !!(p.safety && (p.safety.flags || []).includes('DIVIDEND_CUT')), payer: (p.annual_income || 0) > 0}));
  const cols = [
    {key: 'symbol', label: 'Symbol', left: true, fmt: (v, r) => `<b>${F.esc(v)}</b>${r.cut ? ' <span class="neg">cut</span>' : ''}`},
    {key: 'units', label: 'Units', fmt: v => F.num(v, 3)},
    {key: 'frequency', label: 'Frequency', left: true, fmt: v => F.esc(v || '—')},
    {key: 'last_dividend', label: 'Last dividend', term: 'dividend', fmt: (v, r) => F.isNum(v) ? '$' + F.num(v, 4) + (r.last_ex_date ? `<span class="muted"> ${F.esc(r.last_ex_date)}</span>` : '') : '—'},
    {key: 'forward_rate', label: 'Forward rate', term: 'forward dividend rate', fmt: v => F.isNum(v) ? '$' + F.num(v, 4) : '—'},
    {key: 'forward_yield', label: 'Yield', term: 'dividend yield', fmt: v => F.pct(v, 2)},
    {key: 'yield_on_cost', label: 'Yield on cost', term: 'yield on cost', fmt: v => F.pct(v, 2)},
    {key: 'annual_income', label: 'Annual income', term: 'forward dividend rate', fmt: v => F.money(v)},
    {key: 'income_share', label: 'Share of income', fmt: v => F.pct(v, 2)},
    {key: 'ttm_income', label: 'TTM income', term: 'trailing 12 months', fmt: v => F.money(v)},
    {key: 'ttm_change', label: 'TTM change', term: 'trailing 12 months', fmt: v => F.pct(v, 2, true), cls: F.cls},
    {key: 'growth_3y', label: '3y growth', term: 'dividend growth', fmt: v => F.pct(v, 2, true), cls: F.cls},
    {key: 'payout_ratio', label: 'Payout', term: 'payout ratio', fmt: v => F.pct(v, 2)},
    {key: 'safety_score', label: 'Safety', fmt: (v, r) => F.isNum(v) ? `${F.num(v, 1)}/10${r.safety_flags ? `<span class="muted"> ${F.esc(r.safety_flags)}</span>` : ''}` : '—'},
  ];
  if (hasCtx) cols.push(
    {key: 'price_1y_change', label: '1y price', fmt: v => F.pct(v, 2, true), cls: F.cls},
    {key: 'yield_1y_ago', label: 'Yield 1y ago', term: 'dividend yield', fmt: v => F.pct(v, 2)},
    {key: 'yield_vs_1y_ago', label: 'Yield vs 1y ago', term: 'dividend yield', fmt: v => F.pct(v, 2, true)});
  const tbl = F.table(g('holdings'), cols, rows, {sortKey: 'annual_income', onDraw: vis => { g('count').textContent = `${vis.length} of ${rows.length}`; FA.armTerms(g('holdings')); }});
  termHeads(g('holdings'), cols);
  const chip = g('payers-only');
  chip.addEventListener('click', () => { const on = chip.getAttribute('aria-pressed') !== 'true'; chip.setAttribute('aria-pressed', String(on)); tbl.setFilter(r => !on || r.payer); });
  g('q').addEventListener('input', e => tbl.setQuery(e.target.value));
  const non = P.filter(p => !((p.annual_income || 0) > 0)).map(p => p.symbol);
  g('nonpayers').textContent = non.length ? `Non-payers: ${non.join(', ')}` : 'Every position pays a dividend.';
  // card help
  const card = id => g(id).parentElement;
  F.help(card('h-monthly'), {lead: 'When dividends are projected to arrive over the next year, month by month.',
    sections: [{title: 'Where the numbers come from', html: `<p>Each payer’s last regular dividend is repeated on its usual schedule (monthly, quarterly and so on), so ${F.money(total12)} assumes every payer keeps paying what it last paid. Hover a month for who pays in it.</p>`}]});
  const e0 = ex[0];
  F.help(card('h-exdates'), {lead: 'The next estimated cutoff date for each payer: own the shares before it to receive that dividend.',
    sections: e0 && F.isNum(e0.units) && F.isNum(e0.last_dividend) ? [{title: `${e0.symbol}’s next payment`, html: F.flow([{label: 'shares', value: F.num(e0.units, 3)}, {op: '×', label: 'per share', value: '$' + F.num(e0.last_dividend, 4)}, {op: '=', label: 'estimated amount', value: F.money(e0.units * e0.last_dividend)}]) +
      `<p>The date is an estimate: the last ex-date (${F.esc(e0.last_ex_date || '—')}) plus the usual gap between payments. The company announces the real one shortly before.</p>`}] : []});
  const top = payers.slice().sort((a, b) => (b.annual_income || 0) - (a.annual_income || 0))[0];
  F.help(card('h-holdings'), {lead: 'Each holding’s dividend rate, yield and projected income, largest income first.',
    sections: top ? [{title: `${top.symbol}’s projected income`, html: F.flow([{label: 'shares', value: F.num(top.units, 3)}, {op: '×', label: 'yearly dividend per share', value: '$' + F.num(top.forward_rate, 4)}, {op: '=', label: 'income a year', value: F.money(top.annual_income)}]) +
      `<p>Yield is that yearly dividend divided by today’s price (${F.pct(top.forward_yield, 2)}); yield on cost divides it by what you paid (${F.pct(top.yield_on_cost, 2)}).</p>`},
      {title: 'The safety score', html: '<p>A 0–10 screen built from the payout ratio, how steady payments have been, and any recent cuts. It is a quick filter over past payments, not a rating or a forecast.</p>'}] : []});
  // flags
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def build(report: dict) -> str:
    if not isinstance(report, dict) or not isinstance(report.get("totals"), dict) or "annual_income" not in report["totals"] or "monthly" not in report:
        raise InvalidInput("input must be a dividends.py or income.py result (a JSON object with totals.annual_income and monthly)")
    return page.render(TITLE, report, BODY, SCRIPT)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            report = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read dividend income JSON: {exc}") from exc
        out = page.write(ns.out, build(report))
        positions = report.get("positions") or []
        return {
            "out": str(out),
            "title": TITLE,
            "positions": len(positions),
            "payers": sum(1 for p in positions if isinstance(p, dict) and (p.get("annual_income") or 0) > 0),
            "flags": len(report.get("flags") or []),
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
