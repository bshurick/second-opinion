#!/usr/bin/env python3
"""Usage: render_deep.py [--in page.json] --out page.html

Turns a deep valuation (model.py output, returns.py output, the belief ledger and the blocks the
analyst picked) into one self-contained HTML page for the Artifact tool. Input::

    {"symbol": "ACME", "price": 50.0, "as_of": "2026-10-05",
     "model": <model.py output>, "returns": <returns.py output>,
     "ledger": [{"id", "belief", "holder", "stakes", "verdict", "if_true": "up"|"down", "headline"
                 (a short label, at most 60 characters), "takeaway" (the one-sentence conclusion),
                 "effect_per_share" (optional), "for": [{"claim", "source", "date"}],
                 "against": [...], "consequence": {"segment", "field", "change"}, "thread"}],
     "blocks": [{"type": ...}, ...], "missing_roles": ["industry"], "notes": ["..."]}

The first scenario in model.scenarios is the central case: the page labels it "Central", pins it first
in the scenario table and headlines its value and return. The other scenarios are alternatives and
nothing is averaged: scenarios carry no probabilities. The headline tiles show price, the central
value and return, the worst case (lowest value) and the range.

Always shown first: the headline tiles, the scenario table (value per share, upside, annualized return, total
multiple, what has to be true), a line on what today's price implies (model.py's ``implied``),
and the price against each scenario's value. Then the blocks, in
order:

    segments {scenario}        value of each segment and the bridge to equity
    drivers {segment, field}   by year, one line per scenario: revenue | ebit | fcff for an operating
                               segment; book_start | roe | earnings | residual_income | dividends for a
                               residual_income segment
    ledger                     the belief ledger with sourced evidence (needs "ledger"). When entries
                               carry if_true, rows are grouped by what they mean for the stock:
                               working against the value, working for it, still unsettled; each row
                               shows its headline, and opens to the takeaway, belief and evidence
    track_record {rows}        guidance against results: [{period, metric, guided, actual, source}]
    forensics {items}          accounting findings: [{finding, severity, source}]
    skepticism                 value with and without the discount-rate premiums, and their reasons
    sensitivity                model.py's two-way grid as a heatmap around the price
    custom {title, file, result, explanation}   a labelled calculation outside the engine; result is
                               the script's JSON. Display-ready form: {"answer": one sentence,
                               "table": {"columns": [str], "rows": [[str]]}}. Otherwise a scalar or
                               an object, with any list of records shown as a table
    text {title, markdown}     free text: paragraphs, "- " or "* " bullets (indent two spaces to
                               nest one level) and **bold** only

Every ledger claim needs a source and a date. Flags come from model.py, returns.py,
missing_roles and notes. Prints {"out", "title", "symbol", "scenarios", "blocks", "flags"}; exit 2
on a missing model, an unknown block, a block missing a field, an undated claim, an if_true other
than up or down, or a non-numeric effect_per_share. Also prints "ledger": counts of helps, hurts,
unsettled and unmarked entries. The page is a
fragment; nothing is fetched at runtime and every figure is the scripts' output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

BLOCK_FIELDS = {
    "segments": ("scenario",), "drivers": ("segment", "field"), "ledger": (), "track_record": ("rows",),
    "forensics": ("items",), "skepticism": (), "sensitivity": (), "custom": ("title", "file", "result", "explanation"),
    "text": ("title", "markdown"),
}
DRIVER_FIELDS = {"operating": ("revenue", "ebit", "fcff"), "residual_income": ("book_start", "roe", "earnings", "residual_income", "dividends")}
IF_TRUE = ("up", "down")
HEADLINE_MAX = 60  # a label a reader scans, e.g. "Questionable SMB growth"; the sentence goes in takeaway
VERDICTS = ("supported", "doubtful", "contradicted", "unknowable", "open")

BODY = """
<style>
.verdict{font-size:11px;font-weight:600;letter-spacing:.04em;border-radius:4px;padding:2px 6px;border:1px solid var(--grid);text-transform:uppercase}
.verdict.supported{color:var(--ink);border-color:var(--ink2)}.verdict.doubtful,.verdict.contradicted{color:var(--warn);border-color:var(--warn)}
.verdict.unknowable,.verdict.open{color:var(--muted)}
.belief{border-bottom:1px solid var(--grid);padding:8px 0}.belief summary{cursor:pointer;display:flex;gap:10px;align-items:baseline;font-size:14px}
.belief .ev{display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;margin-top:8px}.belief .ev h3{font-size:12px;color:var(--muted);margin:0 0 4px}
.belief .src{color:var(--muted);font-size:12px}
.belief .eff{font-size:13px;width:14px;flex:none}.eff.hurts,.lg.hurts{color:var(--warn)}.eff.helps,.lg.helps{color:var(--s1)}.eff.unsettled,.lg.unsettled,.eff.none{color:var(--muted)}
.belief .tk{flex:1;font-weight:500}.belief summary{list-style:none}.belief summary::-webkit-details-marker{display:none}
.belief summary::after{content:'›';color:var(--muted);font-size:16px;line-height:1;transition:transform .15s}.belief[open] summary::after{transform:rotate(90deg)}.belief .tw{font-size:14px;margin:8px 0 0}.belief .side{color:var(--muted);font-size:12px;white-space:nowrap}.belief .bl{font-size:13px;margin-top:8px}
.lg{font-size:13px;margin:14px 0 2px;letter-spacing:.02em}.belief .cq{font-size:13px;margin-top:6px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px;margin:0 0 10px}.kv dt{color:var(--muted)}.kv dd{margin:0}
.card ul li{margin:0 0 6px}
.heat td.mod{outline:2px solid var(--ink);outline-offset:-2px;font-weight:600}.heat thead th .ax{display:block;font-size:11px;color:var(--muted);text-align:left;white-space:nowrap}
.ans{font-size:15px;font-weight:600;margin:4px 0 10px}.sub3{font-size:13px;margin:12px 0 4px;color:var(--muted)}
table.plain{border-collapse:collapse;width:100%;font-size:13px}table.plain th,table.plain td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}table.plain th{color:var(--muted);font-weight:500}table.plain .l{text-align:left}li.sub{margin-left:18px;list-style:circle}
.pill-central{background:var(--ink);color:var(--surface);margin-left:0;margin-right:6px}
.must{margin:4px 0 0;padding-left:16px;font-size:12px;color:var(--muted)}
.wrap td.l{white-space:normal;min-width:180px}
@media (max-width:640px){.belief .ev{grid-template-columns:1fr}}
</style>
<h1 id="h1">Deep valuation</h1>
<p class="sub" id="sub"></p>
<div id="intro"></div>
<div class="tiles" id="headline"></div>
<section class="card wrap" id="sc-card"><h2>Scenarios</h2><p class="sub">Each row is one possible future for the business, what a share is worth if it happens, and what buying at today’s price would earn a year.</p><div class="twrap" id="sc"></div><p class="sub" id="implied" style="margin-top:12px"></p></section>
<section class="card" id="strip-card"><h2>Price against the scenarios</h2><p class="sub">Where today’s price sits among the values the scenarios give.</p><div id="strip"></div></section>
<div id="blocks"></div>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Every value is the scripts’ output at the stated assumptions. Scenarios are possible futures, not forecasts, and carry no probabilities; the annualized return assumes the price reaches the scenario’s value at the horizon. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, M = D.model, R = D.returns || {scenarios: []};
  const g = id => document.getElementById(id), esc = F.esc, money = v => F.money(v), pct = v => F.pct(v, 1, true);
  const price = D.price, ret = Object.fromEntries((R.scenarios || []).map(s => [s.name, s]));
  const scs = M.scenarios;
  g('h1').textContent = `${D.symbol || ''} deep valuation`.trim();
  g('sub').textContent = `Price ${money(price)}${D.as_of ? ' · as of ' + D.as_of : ''} · ${scs.length} scenarios · ${M.horizon}-year horizon`;
  F.intro(g('intro'), {lead: `What one share of ${esc(D.symbol || 'this company')} could be worth under ${scs.length} different futures, built segment by segment from the company’s filings, and what buying at ${money(price)} would earn a year in each. The central case is the scenario the research found most consistent with the evidence; the others are alternatives and are not averaged.`});
  const C = scs[0], cr = ret[C.name] || {}, worst = scs.reduce((a, s) => s.value_per_share < a.value_per_share ? s : a, scs[0]), wr = ret[worst.name] || {};
  const allv = scs.map(s => s.value_per_share).filter(F.isNum), irrTxt = r => F.isNum(r.irr) ? pct(r.irr) : '—';
  const tile = (k, v, d) => `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;
  g('headline').innerHTML = tile('Price', esc(money(price)), D.as_of ? 'as of ' + esc(D.as_of) : '&nbsp;')
    + tile('Central value', esc(money(C.value_per_share)), `${esc(C.name)}${F.isNum(C.upside) ? ' · ' + esc(pct(C.upside)) + ' vs price' : ''}`)
    + tile('Central return / yr', esc(irrTxt(cr)), `${esc(C.name)} · ${M.horizon}-year horizon`)
    + tile('Worst case', esc(money(worst.value_per_share)), `${esc(worst.name)} · ${esc(irrTxt(wr))} a year`)
    + tile('Range', `${esc(money(Math.min(...allv)))} to ${esc(money(Math.max(...allv)))}`, 'scenarios not averaged');

  F.table(g('sc'), [
    {key: 'name', label: 'Scenario', left: true, fmt: (v, r) => `${r.central ? '<span class="pill pill-central">Central</span>' : ''}<b>${esc(v)}</b><div class="muted" style="font-size:12px">${esc(r.summary)}</div>${r.must.length ? `<ul class="must">${r.must.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}`},
    {key: 'value', label: 'Value / share', fmt: v => money(v)},
    {key: 'upside', label: 'vs price', fmt: v => F.isNum(v) ? pct(v) : '—'},
    {key: 'irr', label: `Return / yr (${M.horizon}y)`, fmt: v => F.isNum(v) ? pct(v) : '—'},
    {key: 'mult', label: 'Total multiple', fmt: v => F.isNum(v) ? F.num(v, 2) + '×' : '—'},
  ], scs.map((s, i) => ({central: i === 0, name: s.name, summary: s.summary, value: s.value_per_share, upside: s.upside, irr: (ret[s.name] || {}).irr, mult: (ret[s.name] || {}).total_multiple, must: s.must_be_true || []})), {sortKey: 'value', pin: r => r.central});
  const IM = M.implied;
  if (IM && F.isNum(IM.value)) {
    const what = IM.field === 'roe_shift' ? 'return on equity' : 'operating margin';
    g('implied').innerHTML = `<b>What today’s price implies:</b> the ${esc(IM.scenario)} scenario with every segment’s ${what} ${IM.value < 0 ? 'lower' : 'higher'} by ${F.num(Math.abs(IM.value) * 100, 1)} points each year.`;
  } else if (IM) {
    g('implied').innerHTML = `<b>What today’s price implies:</b> no shift of up to 50 points in ${IM.field === 'roe_shift' ? 'return on equity' : 'operating margin'} makes the ${esc(IM.scenario)} scenario worth the price.`;
  }
  F.help(g('sc-card'), {lead: 'One row per scenario: a named future for the business, the value of a share if it happens, and the yearly return from buying at today’s price and holding to the horizon.',
    sections: [{title: 'How the return is built', html: '<p>The return counts the cash paid to shareholders along the way (dividends and buybacks from the model’s free cash flow) and the value of a share at the horizon, against today’s price. The scenarios carry no probabilities: which future is likelier is the reader’s judgement.</p>'}]});

  // strip: one axis, a tick per scenario value and one for the price
  const vals = scs.map(s => s.value_per_share).concat([price]).filter(F.isNum);
  const lo = Math.min(...vals, 0), hi = Math.max(...vals) * 1.08, W = 960, H = 34 + 22 * scs.length;
  const X = v => 20 + (W - 160) * (v - lo) / ((hi - lo) || 1);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="price against scenario values"><line x1="20" x2="${W - 140}" y1="${H - 14}" y2="${H - 14}" stroke="var(--grid)"/>`;
  scs.forEach((s, i) => { const x = X(s.value_per_share), y = 14 + 22 * i; svg += `<line x1="${X(lo)}" x2="${x}" y1="${y}" y2="${y}" stroke="${F.S[i % 8]}" stroke-width="${i === 0 ? 12 : 8}" stroke-linecap="round" opacity=".8"/><text x="${x + 8}" y="${y + 4}" font-size="12" fill="var(--ink)">${esc(s.name)}${i === 0 ? ' (central)' : ''} ${esc(money(s.value_per_share))}</text>`; });
  svg += `<line x1="${X(price)}" x2="${X(price)}" y1="4" y2="${H - 8}" stroke="var(--ink)" stroke-dasharray="4 3"/><text x="${X(price)}" y="${H - 1}" font-size="11" text-anchor="middle" fill="var(--muted)">price ${esc(money(price))}</text></svg>`;
  g('strip').innerHTML = svg;
  F.help(g('strip-card'), {lead: 'Each bar runs to one scenario’s value per share; the dashed line is today’s price. Bars that end left of the line are futures in which the share is worth less than it costs.'});

  const card = (title, sub) => { const c = F.el('section', {class: 'card wrap'}); c.innerHTML = `<h2>${esc(title)}</h2><p class="sub">${sub}</p>`; g('blocks').appendChild(c); const body = F.el('div'); c.appendChild(body); return [c, body]; };
  const byName = n => scs.find(s => s.name === n);
  // axis-start: a sensitivity axis as a plain input name and the value each step produces
  const axis = (ax, rate, ctx = {}) => {  // ctx: {equityOnly, single} describe the discounted segments
    const of = t => ax.segment === '*' ? t : `${t} — ${ax.segment}`, pct = v => `${F.num(v * 100, 1)}%`;
    const pts = v => v === 0 ? 'as modeled' : `${v > 0 ? '+' : '−'}${F.num(Math.abs(v) * 100, 1)} pts`;
    const rated = v => (rate === null || rate === undefined) ? pts(v) : pct(rate + v);
    switch (ax.field) {
      case 'discount_premium': return {title: of('Discount rate'), label: rated};
      case 'discount_shift': return {title: ctx.equityOnly ? 'Cost of equity' : ctx.single ? 'Discount rate' : 'Discount rate, every segment', label: rated};
      case 'terminal_growth': return {title: of('Long-run growth'), label: pct};
      case 'margin_shift': return {title: of('Operating margin'), label: pts};
      case 'roe_shift': return {title: of('Return on equity'), label: pts};
      case 'growth_shift': return {title: of('Revenue growth a year'), label: pts};
      case 'terminal_multiple': return {title: of('Exit multiple'), label: v => `${F.num(v, 1)}×`};
      case 'sales_to_capital': return {title: of('Sales per $1 of capital'), label: v => F.num(v, 2)};
      default: return {title: of(String(ax.field).replace(/_/g, ' ')), label: v => F.num(v, 2)};
    }
  };
  // axis-end
  // md-start: paragraphs, "- " or "* " bullets (indented ones nest), wrapped lines, **bold**; everything escaped first
  const md = t => { const out = [], bold = x => x.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); let para = [], list = null;
    const endPara = () => { if (para.length) out.push(`<p>${bold(para.join(' '))}</p>`); para = []; };
    const endList = () => { if (list) out.push(`<ul>${list.map(i => `<li${i.sub ? ' class="sub"' : ''}>${bold(i.text)}</li>`).join('')}</ul>`); list = null; };
    for (const line of esc(t).split('\n')) { const m = line.match(/^(\s*)[-*]\s+(.*)$/);
      if (!line.trim()) { endPara(); endList(); }
      else if (m) { endPara(); (list = list || []).push({text: m[2].trim(), sub: m[1].length >= 2}); }
      else if (list && /^\s/.test(line)) list[list.length - 1].text += ' ' + line.trim();
      else { endList(); para.push(line.trim()); } }
    endPara(); endList(); return out.join(''); };
  // md-end

  for (const b of D.blocks || []) {
    if (b.type === 'segments') {
      const s = byName(b.scenario); const [c, el] = card(`Value by segment — ${s.name}`, 'What each part of the business is worth on its own, and how the parts add up to the value of the shares.');
      const eq = s.equity_value || 1;
      F.bars(el, s.segments.map((x, i) => ({label: `${x.name}${x.kind === 'venture' ? ' (long shot)' : ''}`, share: x.value / Math.abs(eq), text: money(x.value), color: x.value < 0 ? 'var(--warn)' : F.S[i % 8]})));
      const br = s.bridge, rows = [['Business value', br.enterprise_value], ['Debt', -br.debt], ['Cash', br.cash], ['Leases', -br.leases], ['Other claims', -(br.minority_interest + br.pension_deficit + br.preferred + br.options)], ['Bank / insurer equity', br.residual_income_equity], ['Value of the shares', br.equity_value]];
      el.insertAdjacentHTML('beforeend', `<dl class="kv" style="margin-top:12px">${rows.filter(r => r[1]).map(r => `<dt>${r[0]}</dt><dd>${money(r[1])}</dd>`).join('')}</dl>`);
      F.help(c, {lead: 'Each part of the business valued on its own cash flows and discount rate; a cost centre such as head office counts against the total.'});
    } else if (b.type === 'drivers') {
      const label = {revenue: 'Revenue', ebit: 'Operating profit', fcff: 'Free cash flow', book_start: 'Book value', roe: 'Return on equity', earnings: 'Earnings', residual_income: 'Earnings above the cost of equity', dividends: 'Dividends'}[b.field];
      const [c, el] = card(`${label} — ${b.segment}`, `How ${label.toLowerCase()} for ${esc(b.segment)} develops year by year in each scenario.`);
      F.lines(el, {series: scs.map((s, i) => ({name: s.name, color: F.S[i % 8], points: (s.segments.find(x => x.name === b.segment) || {years: []}).years.map(r => [r.t, r[b.field]])})), xTicks: ((scs[0].segments.find(x => x.name === b.segment) || {years: []}).years).map(r => r.t), xFmt: x => 'Y' + Math.round(x), yFmt: b.field === 'roe' ? (y => F.pct(y, 1)) : (y => F.moneyC(y)), zeroLine: b.field !== 'roe', endLabels: false, height: 240, aria: `${label} by year`});
      F.help(c, {lead: `The ${label.toLowerCase()} each scenario assumes for this segment. The gap between the lines is the disagreement the scenarios are about.`});
    } else if (b.type === 'ledger') {
      const L = D.ledger || [], marked = L.some(e => e.effect);
      const [c, el] = card('Belief ledger', marked ? 'The beliefs the value depends on, sorted by what the research means for the stock: working against the value, working for it, or still unsettled.' : 'The beliefs the value depends on, what the evidence says about each, and what that changed in the model.');
      const ev = xs => (xs || []).map(x => `<li>${esc(x.claim)} <span class="src">${esc(x.source)}, ${esc(x.date)}</span></li>`).join('') || '<li class="muted">none found</li>';
      const detail = e => `<div class="ev"><div><h3>Evidence for</h3><ul>${ev(e.for)}</ul></div><div><h3>Evidence against</h3><ul>${ev(e.against)}</ul></div></div>
        ${e.consequence ? `<div class="cq"><b>In the model:</b> ${esc(e.consequence.segment || '')} ${esc(e.consequence.field || '')} — ${esc(e.consequence.change || '')}</div>` : ''}`;
      if (!marked) {
        el.innerHTML = L.map(e => `<details class="belief"><summary><span class="verdict ${esc(e.verdict)}">${esc(e.verdict)}</span><span>${esc(e.belief)}</span><span class="muted" style="font-size:12px">${esc(e.holder || '')} · ${esc(e.stakes || '')} stakes</span></summary>${detail(e)}</details>`).join('');
      } else {
        const rank = {high: 0, medium: 1, low: 2}, mark = {hurts: '▼', helps: '▲', unsettled: '◆'};
        const groups = [['hurts', 'Working against the value'], ['helps', 'Working for the value'], ['unsettled', 'Still unsettled'], [null, 'Not yet marked']];
        const row = e => `<details class="belief"><summary><span class="tk">${esc(e.headline || e.takeaway || e.belief)}</span><span class="side">${F.isNum(e.effect_per_share) ? `<b>≈ ${e.effect_per_share < 0 ? '−' : '+'}${esc(F.money(Math.abs(e.effect_per_share)))}/share</b> · ` : ''}${esc(e.stakes || '')} stakes</span></summary>
          ${e.headline && e.takeaway ? `<p class="tw">${esc(e.takeaway)}</p>` : ''}<div class="bl"><span class="verdict ${esc(e.verdict)}">${esc(e.verdict)}</span> <b>Belief:</b> ${esc(e.belief)} <span class="muted">— held by ${esc(e.holder || 'not stated')}; ${e.if_true === 'up' ? 'would raise the value if true' : e.if_true === 'down' ? 'would lower the value if true' : 'direction not marked'}</span></div>${detail(e)}</details>`;
        el.innerHTML = groups.map(([k, title]) => { const xs = L.filter(e => (e.effect || null) === k).sort((a, b) => (rank[a.stakes] ?? 3) - (rank[b.stakes] ?? 3));
          return xs.length ? `<h3 class="lg ${esc(k || 'none')}">${mark[k] || '·'} ${title} <span class="muted">(${xs.length})</span></h3>${xs.map(row).join('')}` : ''; }).join('');
      }
      F.help(c, {lead: marked ? 'Each row is one belief the value rests on, grouped by what the research means for the stock: working against the value, working for it, or still unsettled. Open a row for what the research concluded, the belief itself, the verdict on it and the dated evidence.' : 'Each row is a belief someone holds about the company, usually management. The research weighed it against the filings and dated news and gave a verdict.',
        sections: [{title: 'How a row is marked', html: '<p>Two things decide the mark: which way the belief cuts if it is true, and whether the evidence backs it. A hopeful belief the evidence backs works for the value; a hopeful belief the evidence doubts works against it. A worrying belief the evidence backs works against the value; a worrying belief the evidence doubts works for it.</p>'},
                   {title: 'Verdicts', html: '<p><b>Supported</b>: the evidence backs it. <b>Doubtful</b>: the evidence leans against it. <b>Contradicted</b>: the evidence says otherwise. <b>Unknowable</b>: nothing available settles it. <b>Open</b>: not yet researched.</p>'}]});
    } else if (b.type === 'track_record') {
      const [c, el] = card('Guidance against results', 'What management said it would deliver, and what it then reported.');
      F.table(el, [{key: 'period', label: 'Period', left: true}, {key: 'metric', label: 'Measure', left: true}, {key: 'guided', label: 'Guided'}, {key: 'actual', label: 'Actual'}, {key: 'source', label: 'Source', left: true}], b.rows, {sortKey: 'period'});
      F.help(c, {lead: 'A record of past promises against outcomes. A habit of missing guidance is one reason the model discounts management’s current plan more heavily.'});
    } else if (b.type === 'forensics') {
      const [c, el] = card('Accounting findings', 'Places where the reported numbers and the cash or the notes tell different stories.');
      F.table(el, [{key: 'finding', label: 'Finding', left: true}, {key: 'severity', label: 'Severity', left: true}, {key: 'source', label: 'Source', left: true}], b.items, {sortKey: 'severity'});
      F.help(c, {lead: 'Findings from reading the statements and notes against each other: profit running ahead of cash, balances growing faster than sales, changes in accounting choices.'});
    } else if (b.type === 'skepticism') {
      const [c, el] = card('Cost of skepticism', 'How much of each scenario’s value the extra discount for doubtful plans takes away, and why each extra discount is there.');
      F.table(el, [{key: 'name', label: 'Scenario', left: true}, {key: 'v', label: 'Value / share', fmt: v => money(v)}, {key: 'x', label: 'Without the extra discount', fmt: v => money(v)}, {key: 'd', label: 'Difference', fmt: v => money(v)}],
        scs.map((s, i) => ({central: i === 0, name: s.name, v: s.value_per_share, x: s.value_ex_premiums, d: s.value_per_share - s.value_ex_premiums})), {sortKey: 'name'});
      const prem = []; scs.forEach(s => s.segments.forEach(x => { if (x.premium) prem.push(`<li><b>${esc(s.name)} · ${esc(x.name)}</b>: +${F.num(x.premium * 100, 1)} points — ${esc(x.premium_reason || 'no reason given')}</li>`); }));
      el.insertAdjacentHTML('beforeend', prem.length ? `<ul style="font-size:13px;margin-top:10px">${prem.join('')}</ul>` : '<p class="muted">No extra discount was applied.</p>');
      F.help(c, {lead: 'Where a plan is vague or the evidence leans against it, the model discounts that part of the business at a higher rate. This card shows what that choice costs in value.'});
    } else if (b.type === 'sensitivity') {
      const S = M.sensitivity, dr = S.discount_rate || {}, disc = ((scs.find(x => x.name === S.scenario) || scs[0]).segments || []).filter(x => ['operating', 'cost', 'residual_income'].includes(x.kind));
      const actx = {equityOnly: disc.length > 0 && disc.every(x => x.kind === 'residual_income'), single: disc.length === 1}, A = axis(S.a, dr.a, actx), B = axis(S.b, dr.b, actx);
      const [c, el] = card(`What moves the value — ${S.scenario}`, `Each cell is what a share is worth in the ${esc(S.scenario)} scenario when two inputs change: ${esc(A.title)} down the side, ${esc(B.title)} across the top. The outlined cell is the scenario as modeled. Blue cells are above today’s price of ${money(price)}, red cells below.`);
      F.heatmap(el, {rows: S.a.values.map(A.label), cols: S.b.values.map(B.label), values: S.value_per_share.map(r => r.map(v => F.isNum(v) ? price - v : null)), fmt: v => money(price - v), diverging: true});  // the toolkit colours negatives blue, so above the price is negative here
      const corner = el.querySelector('thead th'); if (corner) corner.innerHTML = `<span class="ax">${esc(A.title)} ↓</span><span class="ax">${esc(B.title)} →</span>`;
      const at = (vals, b0) => F.isNum(b0) ? vals.findIndex(v => Math.abs(v - b0) < 1e-9) : -1;
      const bi = at(S.a.values, (S.base || {}).a), bj = at(S.b.values, (S.base || {}).b), cell = bi >= 0 && bj >= 0 ? el.querySelector(`td[data-r="${bi}"][data-c="${bj}"]`) : null;
      if (cell) cell.classList.add('mod');
      F.help(c, {lead: 'Each cell reruns the scenario with the two inputs set to the values on its row and column, holding everything else as modeled. It shows how much the value depends on each input, and whether a modest change would put the value above or below today’s price. An empty cell is a combination the model cannot value.'});
    } else if (b.type === 'custom') {
      const [c, el] = card(`Custom calculation — ${b.title}`, 'A calculation the standard engine cannot express, kept separate so it can be checked on its own.');
      const R = b.result, tableHtml = (cols, rows) => `<div class="twrap"><table class="plain"><thead><tr>${cols.map((h, i) => `<th class="${i ? '' : 'l'}">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map((x, i) => `<td class="${i ? '' : 'l'}">${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
      const scalar = v => F.isNum(v) ? F.num(v, Math.abs(v) < 1 ? 4 : 2) : String(v);
      const records = v => Array.isArray(v) && v.length && v.every(r => r && typeof r === 'object' && !Array.isArray(r));
      const recTable = v => { const keys = [...new Set(v.flatMap(r => Object.keys(r)))]; return tableHtml(keys.map(k => k.replace(/_/g, ' ')), v.map(r => keys.map(k => Array.isArray(r[k]) ? r[k].map(scalar).join(', ') : r[k] == null ? '—' : typeof r[k] === 'object' ? JSON.stringify(r[k]) : scalar(r[k])))); };
      let html = '';
      if (R && typeof R === 'object' && !Array.isArray(R) && (R.answer || R.table)) {
        if (R.answer) html += `<p class="ans">${esc(R.answer)}</p>`;
        if (R.table) html += tableHtml(R.table.columns, R.table.rows);
      } else if (R && typeof R === 'object' && !Array.isArray(R)) {
        const simple = Object.entries(R).filter(([, v]) => !records(v) && !(v && typeof v === 'object' && !Array.isArray(v)));
        html += `<dl class="kv">${simple.map(([k, v]) => `<dt>${esc(k.replace(/_/g, ' '))}</dt><dd>${esc(Array.isArray(v) ? v.map(scalar).join(', ') : scalar(v))}</dd>`).join('')}</dl>`;
        Object.entries(R).filter(([, v]) => records(v)).forEach(([k, v]) => { html += `<h3 class="sub3">${esc(k.replace(/_/g, ' '))}</h3>${recTable(v)}`; });
      } else html += records(R) ? recTable(R) : `<p class="ans">${esc(scalar(R))}</p>`;
      el.innerHTML = html + md(b.explanation) + `<p class="muted" style="font-size:12px">Calculated by <code>${esc(b.file)}</code>, rerun by the red team.</p>`;
      F.help(c, {lead: 'The standard engine could not express this part of the business, so a separate calculation was written and rerun by an independent check.'});
    } else if (b.type === 'text') {
      const [c, el] = card(b.title, 'Notes from the research that the tables do not show.');
      el.innerHTML = md(b.markdown);
      F.help(c, {lead: 'A short write-up of something from the research that matters for the value.'});
    }
  }
  const flags = [...(M.flags || []), ...(R.flags || []), ...(D.missing_roles || []).map(r => ({code: 'RESEARCH_MISSING', message: `The ${r} research did not complete, so its findings are absent.`})), ...(D.notes || []).map(n => ({code: 'NOTE', message: n}))];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${esc(f.code)}</b>${esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render_deep.py: {message}")


def _validate(data: dict) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a JSON object")
    model = data.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("scenarios"), list) or not model["scenarios"]:
        raise InvalidInput("model (a model.py result with scenarios) is required")
    price = data.get("price", model.get("price"))
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        raise InvalidInput("price must be a positive number")
    data["price"] = price
    scen = {s["name"] for s in model["scenarios"]}
    segs = {x["name"] for s in model["scenarios"] for x in s["segments"]}
    kinds = {x["name"]: x["kind"] for s in model["scenarios"] for x in s["segments"] if x.get("kind") in DRIVER_FIELDS}
    for i, b in enumerate(data.get("blocks") or []):
        t = b.get("type") if isinstance(b, dict) else None
        if t not in BLOCK_FIELDS:
            raise InvalidInput(f"blocks[{i}]: unknown type {t!r}")
        missing = [f for f in BLOCK_FIELDS[t] if b.get(f) in (None, "")]
        if missing:
            raise InvalidInput(f"blocks[{i}] ({t}) is missing {', '.join(missing)}")
        if t == "segments" and b["scenario"] not in scen:
            raise InvalidInput(f"blocks[{i}]: no scenario {b['scenario']!r}")
        if t in ("track_record", "forensics"):
            key = "rows" if t == "track_record" else "items"
            if not isinstance(b[key], list) or not all(isinstance(r, dict) for r in b[key]):
                raise InvalidInput(f"blocks[{i}] ({t}): {key} must be a list of objects")
        if t == "drivers":
            if b["segment"] not in segs:
                raise InvalidInput(f"blocks[{i}]: no segment {b['segment']!r}")
            if b["segment"] not in kinds:
                raise InvalidInput(f"blocks[{i}]: drivers needs an operating or residual_income segment; {b['segment']!r} is not one")
            allowed = DRIVER_FIELDS[kinds[b["segment"]]]
            if b["field"] not in allowed:
                raise InvalidInput(f"blocks[{i}]: field for {b['segment']!r} must be one of {', '.join(allowed)}")
        if t == "custom" and isinstance(b.get("result"), dict) and "table" in b["result"]:
            tb = b["result"]["table"]
            cols = tb.get("columns") if isinstance(tb, dict) else None
            rows = tb.get("rows") if isinstance(tb, dict) else None
            if not isinstance(cols, list) or not all(isinstance(x, str) for x in cols) or not isinstance(rows, list) \
                    or not all(isinstance(r, list) and len(r) == len(cols) for r in rows):
                raise InvalidInput(f"blocks[{i}] (custom): table needs columns (a list of strings) and rows (lists as long as columns)")
        if t == "sensitivity" and not model.get("sensitivity"):
            raise InvalidInput(f"blocks[{i}]: the model has no sensitivity grid")
        if t == "ledger" and not data.get("ledger"):
            raise InvalidInput(f"blocks[{i}]: a ledger block needs ledger entries")
    for e in data.get("ledger") or []:
        eid = e.get("id", "?")
        if not e.get("belief") or e.get("verdict") not in VERDICTS:
            raise InvalidInput(f"ledger {eid}: needs a belief and a verdict in {', '.join(VERDICTS)}")
        if "if_true" in e and e["if_true"] not in IF_TRUE:
            raise InvalidInput(f"ledger {eid}: if_true must be up or down (what the belief does to the value if it is true)")
        if e.get("headline") is not None and (not isinstance(e["headline"], str) or len(e["headline"]) > HEADLINE_MAX):
            raise InvalidInput(f"ledger {eid}: headline must be a short label of at most {HEADLINE_MAX} characters; the full sentence belongs in takeaway")
        eps = e.get("effect_per_share")
        if eps is not None and (isinstance(eps, bool) or not isinstance(eps, (int, float))):
            raise InvalidInput(f"ledger {eid}: effect_per_share must be a number")
        for side in ("for", "against"):
            for c in e.get(side) or []:
                for f in ("claim", "source", "date"):
                    if not c.get(f):
                        raise InvalidInput(f"ledger {eid}: a claim under {side!r} has no {f}")


def ledger_effect(entry: dict) -> str | None:
    """What a ledger entry means for the stock: a belief that would raise the value ('if_true': 'up')
    helps when supported and hurts when doubted; one that would lower it ('down') does the reverse.
    Open or unknowable beliefs are unsettled. None when the entry does not say which way it cuts."""
    direction, verdict = entry.get("if_true"), entry.get("verdict")
    if direction not in IF_TRUE:
        return None
    if verdict in ("open", "unknowable"):
        return "unsettled"
    holds = verdict == "supported"
    return "helps" if holds == (direction == "up") else "hurts"


def build(data: dict) -> tuple[str, str, dict]:
    _validate(data)
    data["ledger"] = [{**e, "effect": ledger_effect(e)} for e in data.get("ledger") or []]
    symbol = str(data.get("symbol") or "")
    title = f"{symbol} Deep Valuation".strip()
    markup = page.render(title, data, BODY, SCRIPT)
    model, rets = data["model"], data.get("returns") or {}
    flags = len(model.get("flags") or []) + len(rets.get("flags") or []) + len(data.get("missing_roles") or []) + len(data.get("notes") or [])
    counts = {"helps": 0, "hurts": 0, "unsettled": 0, "unmarked": 0}
    for e in data["ledger"]:
        counts[e["effect"] or "unmarked"] += 1
    return title, markup, {"title": title, "symbol": symbol or None, "scenarios": [s["name"] for s in model["scenarios"]],
                           "blocks": [b["type"] for b in data.get("blocks") or []], "flags": flags, "ledger": counts}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render_deep.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read the deep valuation JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
