#!/usr/bin/env python3
"""Usage: render.py [--in plan.json] --out page.html

Turns one ``plan.py`` (or ``rebalance.py``) result (a file, or stdin when ``--in`` is omitted) into a
self-contained interactive HTML page for the Artifact tool: stat tiles (total value, max drift,
trades, turnover, estimated tax, cash after), drift-vs-target bars centred on zero with the band
edges marked and breaches coloured, a sortable target-vs-current allocation table, the trade list as
a sortable table (account, reason, estimated gain and tax when the script priced the lots; lots on
hover), the contribution or withdrawal routing when the plan moves cash, the post-trade allocation,
tax-aware routing versus pro-rata, suggested bands when present, the flags, and the "a plan, not
orders" note. Prints ``{"out": path, "title": ..., "trades": n, "breaches": n, "flags": n}``.
Exit 2 on a missing or malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the plan JSON; the page formats, sorts and filters, it never recomputes a trade or a weight.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Rebalancing Plan"

BODY = """
<style>
.dbar{display:grid;grid-template-columns:minmax(90px,1fr) 4fr auto;gap:10px;align-items:center;font-size:13px;padding:3px 0}
.dbar .track{position:relative;height:14px;background:var(--grid);border-radius:3px;overflow:hidden}
.dbar .zero{position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--ink2)}
.dbar .band{position:absolute;top:0;bottom:0;width:1px;background:var(--muted);opacity:.7}
.dbar .fill{position:absolute;top:0;bottom:0;border-radius:2px}
.dbar .n{color:var(--ink2);font-variant-numeric:tabular-nums;min-width:110px;text-align:right}
.side{font-weight:600;letter-spacing:.03em}
</style>
<h1>Rebalancing Plan</h1>
<p class="sub" id="head">{{HEADLINE}}</p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<div class="grid2">
  <div class="card"><h2 id="drift-h">Drift vs target</h2><p class="sub" id="drift-sub"></p><div id="drift"></div><p class="note" id="frozen"></p></div>
  <div class="card" id="cash-card" hidden><h2 id="cash-title">Cash routing</h2><p class="sub" id="cash-line"></p><div id="cash-bars"></div></div>
  <div class="card" id="post-card"><h2>After trades</h2><p class="sub">How the portfolio would be split once every trade in the list is done.</p><div class="twrap" id="post"></div></div>
</div>
<section class="card"><h2 id="alloc-h">Allocation</h2><p class="sub" id="alloc-sub">Each key is a group of holdings (an asset class, or one symbol) with its own target weight. Drift is how far the group sits from that target today.</p><div class="twrap" id="allocation"></div></section>
<section class="card" id="trades-card"><h2>Trades</h2><p class="sub" id="trades-sub">Sells first, largest first. Hover a sell for the tax lots it would take.</p>
  <div class="controls"><input id="q" type="search" placeholder="Search symbol, account or reason" aria-label="Search trades"><span class="muted" id="count"></span></div>
  <div class="twrap" id="trades"></div>
  <p class="sub" id="totals" style="margin-top:10px"></p>
  <p class="note" id="routing"></p>
</section>
<section class="card" id="bands-card" hidden><h2 id="bands-h">Suggested bands</h2><p class="sub" id="bands-sub">Band widths proposed from each group's past year of volatility: bumpier groups get wider bands so they are not traded on every wobble. The user chooses the bands; this is not advice.</p><div class="twrap" id="bands"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note"><b>This is a plan, not orders.</b> To place any of these orders, say which one; each goes through the preview-and-confirm protocol one at a time. Before any sell in a taxable account, the tax-aware skill gives exact lots and wash-sale checks. Tax estimates take the highest-cost lots first at the stated rates; a sale in a tax-advantaged account contributes gain but no tax, and the taxable / tax-advantaged split is a guess from each account's type. General information at the stated assumptions, not financial, tax, or legal advice.</p>
<noscript><p class="note">JavaScript is off: the charts and tables are not drawn. The headline figures are in the line under the title; the full plan is embedded in the page as JSON.</p></noscript>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, B = D.bands || {};
  const g = id => document.getElementById(id);
  const pct1 = v => F.pct(v, 1), pctS = v => F.pct(v, 1, true);
  // terms this page needs that the shared glossary lacks (page.py is frozen; add them here)
  Object.assign(F.glossary, {
    'target weight': ['The share of the portfolio you decided each group of holdings should be; the plan trades toward it.', 'https://www.investopedia.com/terms/a/assetallocation.asp'],
    'relative drift': ['Drift as a share of the target weight: 5 points off a 20% target is 25% relative drift; a breach is either the absolute or the relative band crossed.', 'https://www.investopedia.com/terms/r/rebalancing.asp'],
    'realized gain': ['Profit locked in by selling: sale proceeds minus what you paid; only realized gains are taxed.', 'https://www.investopedia.com/terms/c/capitalgain.asp'],
    'tax-advantaged account': ['An IRA, 401(k) or similar account where sales are not taxed in the year they happen.', 'https://www.investopedia.com/terms/t/tax-advantaged.asp'],
    'pro rata': ['Split in proportion: each account sells its share of the total rather than one account going first.', 'https://www.investopedia.com/terms/p/pro-rata.asp'],
  });
  // table headers come out escaped from FA.table; swap in the term markup once (thead is built once)
  const termHeads = (root, map) => { root.querySelectorAll('th[data-key]').forEach(th => { if (map[th.dataset.key]) th.innerHTML = map[th.dataset.key]; }); F.armTerms(root); };
  const setHtml = (id, html) => { const n = g(id); n.innerHTML = html; F.armTerms(n); };
  const whole = (D.trades || []).length > 0 && (D.trades || []).every(t => F.isNum(t.units) && t.units === Math.round(t.units));
  const units = v => F.isNum(v) ? F.num(v, whole ? 0 : 4) : '—';
  const A = D.allocation || [], T = D.trades || [];
  const breaches = A.filter(a => a.breach);
  // what am I looking at?
  FA.explain(g('explain'), `<p>This page compares how the portfolio is split today with the ${FA.term('target weight', 'target split')} you set, and lists the trades that would bring it back. Holdings and values come from the connected accounts at today's prices; targets and ${FA.term('rebalancing band', 'bands')} come from your settings.</p><p>Read the ${FA.term('drift')} bars first: each bar is how far a group sits from its target, and a red bar has crossed its band. The trades table is what it would take to close the gaps, sells first.</p><p>This is a plan, not orders; nothing is traded from this page. The caveat that matters most: the tax figures are estimates from the ${FA.term('tax lot', 'lots')} the broker or ledger reports and the stated rates, not a tax calculation.</p>`);
  // one colour per allocation key, by allocation order; a symbol borrows its key's colour
  const keyColor = {}; A.forEach((a, i) => { keyColor[a.key] = F.S[i % 8]; });
  const symKey = {}; A.forEach(a => (a.members || []).forEach(m => { symKey[m] = a.key; }));
  const colorOf = sym => keyColor[symKey[sym]] || keyColor[sym] || 'var(--muted)';
  // tiles
  const priced = T.some(t => F.isNum(t.est_tax));
  const tiles = [
    ['Total value', F.money(D.total_value), `${F.esc(D.mode || '—')} mode` + (F.isNum(D.frozen_value) && D.frozen_value > 0 ? ` · frozen (left untouched) ${F.money(D.frozen_value, 0)}` : '')],
    [FA.term('drift', 'Max drift'), `<span class="${breaches.length ? 'neg' : ''}">${pct1(D.max_drift)}</span>`, `${breaches.length} of ${A.length} groups outside the ${pct1(B.absolute)} / ${F.pct(B.relative, 0)} ${FA.term('rebalancing band', 'bands')}`],
    ['Trades', String(T.length), `buys ${F.money(D.buys_total, 0)} · sells ${F.money(D.sells_total, 0)}`],
    [FA.term('turnover', 'Turnover'), pct1(D.turnover), 'half of buys plus sells, as a share of total value'],
    ['Est. tax', priced || F.isNum(D.est_tax) ? F.money(D.est_tax) : '—', `est. ${FA.term('realized gain')} ${F.moneyS(D.est_realized_gain)}`],
    ['Cash after', F.money(D.cash_after), (F.isNum(D.contribution) && D.contribution > 0 ? `contribution ${F.money(D.contribution, 0)}` : F.isNum(D.withdrawal) && D.withdrawal > 0 ? `withdrawal ${F.money(D.withdrawal, 0)}` : 'no new cash')],
  ];
  setHtml('tiles', tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join(''));
  // headings and subtitles: the static text stays for readers without JS; with JS the jargon gets its term markup
  setHtml('drift-h', `${FA.term('drift', 'Drift')} vs target`);
  setHtml('alloc-h', FA.term('allocation', 'Allocation'));
  setHtml('alloc-sub', `Each key is a group of holdings (an asset class, or one symbol) with its own ${FA.term('target weight')}. ${FA.term('drift', 'Drift')} is how far the group sits from that target today.`);
  setHtml('trades-sub', `Sells first, largest first. Hover a sell for the ${FA.term('tax lot', 'tax lots')} it would take.`);
  setHtml('bands-h', `Suggested ${FA.term('rebalancing band', 'bands')}`);
  setHtml('bands-sub', `Band widths proposed from each group's past year of ${FA.term('volatility')}: bumpier groups get wider bands so they are not traded on every wobble. The user chooses the bands; this is not advice.`);
  // drift bars centred on zero, band edges marked; breaches in the loss colour
  setHtml('drift-sub', `Each bar is how far a group sits from its ${FA.term('target weight', 'target')}, in percentage points; the ticks mark the ±${pct1(B.absolute)} ${FA.term('rebalancing band', 'band')}. A group is a breach when it is ${pct1(B.absolute)} off its target, or ${F.pct(B.relative, 0)} of the target away (${FA.term('relative drift')}), whichever comes first.`);
  const root = g('drift'); root.innerHTML = '';
  const maxAbs = Math.max(...A.map(a => Math.abs(a.drift || 0)), B.absolute || 0, 1e-9) * 1.1;
  const X = v => 50 + 50 * v / maxAbs;
  for (const a of A) {
    const row = F.el('div', {class: 'dbar'});
    row.appendChild(F.el('span', {class: 'l'}, `<b>${F.esc(a.key)}</b>`));
    const track = F.el('div', {class: 'track'});
    track.appendChild(F.el('span', {class: 'zero'}));
    if (F.isNum(B.absolute)) { const l = F.el('span', {class: 'band'}); l.style.left = X(-B.absolute) + '%'; track.appendChild(l); const r = F.el('span', {class: 'band'}); r.style.left = X(B.absolute) + '%'; track.appendChild(r); }
    const fill = F.el('span', {class: 'fill'}); const d = a.drift || 0;
    fill.style.left = Math.min(50, X(d)) + '%'; fill.style.width = Math.abs(X(d) - 50) + '%'; fill.style.background = a.breach ? 'var(--down)' : keyColor[a.key];
    track.appendChild(fill); row.appendChild(track);
    row.appendChild(F.el('span', {class: 'n' + (a.breach ? ' neg' : '')}, `${pctS(a.drift)}${a.breach ? ' · breach' : ''}`));
    F.bindTip(row, `<b>${F.esc(a.key)}</b> ${F.esc((a.members || []).join(', '))}<br>${pct1(a.weight)} now · target ${pct1(a.target)}<br>drift ${pctS(a.drift)} (${pctS(a.relative_drift)} of target)<br>${F.money(a.value, 0)} → ${F.money(a.target_value, 0)} (${F.moneyS(a.delta_value)})`);
    root.appendChild(row);
  }
  if (!A.length) root.innerHTML = '<span class="muted">no allocation</span>';
  const fz = D.frozen || [];
  g('frozen').textContent = fz.length ? 'Frozen (not in any group, left untouched): ' + fz.map(f => `${f.symbol} ${F.money(f.value, 0)}`).join(' · ') : '';
  // contribution / withdrawal routing
  const contrib = F.isNum(D.contribution) && D.contribution > 0, withdraw = F.isNum(D.withdrawal) && D.withdrawal > 0;
  if (contrib || withdraw || D.mode === 'contribution') { g('cash-card').hidden = false;
    const side = withdraw ? 'SELL' : 'BUY'; const rows = T.filter(t => t.side === side);
    g('cash-title').textContent = withdraw ? 'Withdrawal routing' : 'Contribution routing';
    g('cash-line').textContent = withdraw ? `Where the withdrawal comes from: ${F.money(D.withdrawal)} raised from sells of ${F.money(D.sells_total)} · cash after ${F.money(D.cash_after)}` : `Where the new cash goes: contribution ${F.money(D.contribution)} → buys ${F.money(D.buys_total)} · cash after ${F.money(D.cash_after)}`;
    if (!rows.length) g('cash-bars').innerHTML = `<span class="muted">no ${side.toLowerCase()}s in the plan; the cash stays in cash</span>`;
    else F.bars(g('cash-bars'), rows.map(t => ({label: t.symbol + (t.account ? ` · ${t.account}` : ''), share: t.value, color: colorOf(t.symbol), text: F.money(t.value, 0), tip: `<b>${F.esc(t.symbol)}</b> ${F.esc(t.side)} ${units(t.units)} @ ${F.money(t.price)}<br>${F.esc(t.reason || '')}`}))); }
  // after trades
  const P = D.post_trade || [];
  setHtml('post', P.length ? '<table><thead><tr><th class="l">Key</th><th>Value</th><th>Weight</th><th>' + FA.term('target weight', 'Target') + '</th><th>' + FA.term('drift', 'Drift') + '</th></tr></thead><tbody>' + P.map(p => `<tr><td class="l"><span style="border-left:3px solid ${keyColor[p.key] || 'var(--muted)'};padding-left:6px">${F.esc(p.key)}</span></td><td>${F.money(p.value, 0)}</td><td>${pct1(p.weight)}</td><td>${pct1(p.target)}</td><td>${pctS(p.drift)}</td></tr>`).join('') + '</tbody></table>' : '<span class="muted">no trades</span>');
  // allocation table
  F.table(g('allocation'), [
    {key: 'key', label: 'Key', left: true, fmt: v => `<span style="border-left:3px solid ${keyColor[v] || 'var(--muted)'};padding-left:6px"><b>${F.esc(v)}</b></span>`},
    {key: 'members', label: 'Members', left: true, fmt: v => F.esc((v || []).join(', ')) || '<span class="muted">cash</span>'},
    {key: 'value', label: 'Value', fmt: v => F.money(v)},
    {key: 'weight', label: 'Weight', fmt: pct1},
    {key: 'target', label: 'Target', fmt: pct1},
    {key: 'drift', label: 'Drift', fmt: pctS, cls: (v, r) => r.breach ? 'neg' : ''},
    {key: 'relative_drift', label: 'Relative', fmt: pctS},
    {key: 'breach', label: 'Breach', fmt: v => v ? '<span class="neg">yes</span>' : 'no'},
    {key: 'delta_value', label: 'To target', fmt: v => F.moneyS(v)},
  ], A.map(a => ({...a, breach: !!a.breach})), {sortKey: 'value'});
  termHeads(g('allocation'), {target: FA.term('target weight', 'Target'), drift: FA.term('drift', 'Drift'), relative_drift: FA.term('relative drift', 'Relative'), breach: FA.term('rebalancing band', 'Breach')});
  // trades table (tax columns only when the script priced the lots)
  const cols = [
    {key: 'symbol', label: 'Symbol', left: true, fmt: v => `<span style="border-left:3px solid ${colorOf(v)};padding-left:6px"><b>${F.esc(v)}</b></span>`},
    {key: 'side', label: 'Side', left: true, fmt: v => `<span class="side">${F.esc(v)}</span>`},
    {key: 'units', label: 'Units', fmt: units},
    {key: 'price', label: 'Price', fmt: v => F.money(v)},
    {key: 'value', label: 'Value', fmt: v => F.money(v)},
    {key: 'account', label: 'Account', left: true, fmt: v => v ? F.esc(v) : '<span class="muted">—</span>'},
    {key: 'reason', label: 'Reason', left: true, fmt: v => F.esc(v || '')},
  ];
  if (priced) cols.push({key: 'est_gain', label: 'Est. gain', fmt: v => F.moneyS(v), cls: v => F.cls(v)}, {key: 'est_tax', label: 'Est. tax', fmt: v => F.isNum(v) ? F.money(v) : '—'});
  const lotTip = t => (t.lots || []).length ? `<b>${F.esc(t.symbol)}</b> lots, highest cost first<br>` + t.lots.map(l => `${units(l.units)} @ ${F.money(l.cost_per_unit)} · ${F.esc(l.term || 'unknown')} · gain ${F.moneyS(l.gain)}`).join('<br>') : '';
  if (!T.length) g('trades').innerHTML = '<span class="muted">No trades: ' + (breaches.length ? 'nothing to do at these settings' : 'every key is within its bands') + '</span>';
  else { const tbl = F.table(g('trades'), cols, T, {sortKey: 'value', onDraw: vis => { g('count').textContent = `${vis.length} of ${T.length}`; g('trades').querySelectorAll('tbody tr').forEach((tr, i) => { const tip = lotTip(vis[i]); if (tip) F.bindTip(tr, tip); }); }});
    termHeads(g('trades'), {est_gain: FA.term('realized gain', 'Est. gain')});
    g('q').addEventListener('input', e => tbl.setQuery(e.target.value)); }
  setHtml('totals', `Buys ${F.money(D.buys_total)} · sells ${F.money(D.sells_total)} · cash after ${F.money(D.cash_after)} · ${FA.term('turnover')} ${pct1(D.turnover)} · est. ${FA.term('realized gain')} ${F.moneyS(D.est_realized_gain)} · est. tax ${F.money(D.est_tax)}`);
  const R = D.routing;
  if (R && R.accounts) {
    const cls = Object.entries(R.accounts).map(([id, k]) => `${F.esc(id)}: ${F.esc(k === 'tax_advantaged' ? 'tax-advantaged' : k)}`).join(' · ');
    const differs = F.isNum(R.est_tax) && F.isNum(R.est_tax_pro_rata) && R.est_tax !== R.est_tax_pro_rata;
    setHtml('routing', (differs ? `Filling the sells from ${FA.term('tax-advantaged account', 'tax-advantaged accounts')} first changes the estimated tax from ${F.money(R.est_tax_pro_rata)} (${FA.term('pro rata')} across accounts) to ${F.money(R.est_tax)}. ` : `Sells fill from ${FA.term('tax-advantaged account', 'tax-advantaged accounts')} first; here that matches the ${FA.term('pro rata')} split. `) + `Account classification (a guess from account type): ${cls}.`);
  }
  // suggested bands
  const SB = D.suggested_bands;
  if (Array.isArray(SB) && SB.length) { g('bands-card').hidden = false;
    setHtml('bands', '<table><thead><tr><th class="l">Key</th><th>' + FA.term('volatility', 'Annualized volatility') + '</th><th>' + FA.term('rebalancing band', 'Absolute band') + '</th><th>' + FA.term('relative drift', 'Relative band') + '</th></tr></thead><tbody>' + SB.map(b => `<tr><td class="l">${F.esc(b.key)}</td><td>${pct1(b.vol_annual)}</td><td>${pct1(b.absolute)}</td><td>${F.pct(b.relative, 0)}</td></tr>`).join('') + '</tbody></table>'); }
  // card help
  const card = id => g(id).parentElement;
  const big = [...A].filter(a => F.isNum(a.drift)).sort((a, b) => Math.abs(b.drift) - Math.abs(a.drift))[0];
  const bandAbs = F.isNum(B.absolute) ? B.absolute : null, bandRel = F.isNum(B.relative) ? B.relative : null;
  F.help(card('drift-h'), {lead: 'How far each part of the portfolio has wandered from its target weight.',
    sections: [...(big ? [{title: `The biggest drift: ${big.key}`, html: F.flow([{label: 'weight now', value: pct1(big.weight)}, {op: '−', label: 'target', value: pct1(big.target)}, {op: '=', label: 'drift', value: F.pct(big.drift, 1, true)}])}] : []),
      {title: 'When a drift counts as a breach', html: `<p>A group breaches its band when it is off by more than ${bandAbs != null ? pct1(bandAbs).replace('%', ' percentage points') : 'the absolute band'}, or by more than ${bandRel != null ? F.pct(bandRel, 0) : 'the relative band'} of its own target, whichever comes first. The second rule keeps small targets from drifting far in proportion before anything shows.</p>`}]});
  const cashCard = g('cash-card');
  if (cashCard && !cashCard.hidden) F.help(cashCard, {lead: 'Where new money, or money taken out, would go so the mix moves toward its targets.',
    sections: [{title: 'How it is split', html: `<p>${F.isNum(D.contribution) && D.contribution > 0 ? `The ${F.money(D.contribution)} deposit goes first to the groups furthest below target.` : `The ${F.money(D.withdrawal)} withdrawal comes first from the groups furthest above target.`} Using cash this way moves the mix without selling anything.</p>`}]});
  const P0 = P.length ? [...P].sort((a, b) => Math.abs(b.drift || 0) - Math.abs(a.drift || 0))[0] : null;
  F.help(g('post-card'), {lead: 'How the portfolio would be split once every trade in the list is done.',
    sections: P0 ? [{title: 'What is left over', html: `<p>The largest remaining gap is ${F.esc(P0.key)} at ${F.pct(P0.drift, 1, true)} from target. Small gaps remain because trades are rounded and some holdings are left alone.</p>`}] : []});
  const bigA = [...A].filter(a => F.isNum(a.delta_value)).sort((a, b) => Math.abs(b.delta_value) - Math.abs(a.delta_value))[0];
  F.help(card('alloc-h'), {lead: 'Each group of holdings with its current weight, target and drift.',
    sections: bigA ? [{title: `Dollars to move: ${bigA.key}`, html: F.flow([{label: 'target value', value: F.money(bigA.target_value, 0)}, {op: '−', label: 'value now', value: F.money(bigA.value, 0)}, {op: '=', label: 'to move', value: F.moneyS(bigA.delta_value)}]) + '<p>Negative means sell down to target; positive means buy.</p>'}] : []});
  const RT = D.routing;
  F.help(g('trades-card'), {lead: 'The buys and sells that would bring each group back to target, sells first.',
    sections: RT && F.isNum(RT.est_tax) && F.isNum(RT.est_tax_pro_rata) ? [{title: 'Why sells come from retirement accounts first', html: F.flow([{label: 'tax if sells were spread evenly', value: F.money(RT.est_tax_pro_rata)}, {op: '−', label: 'tax with retirement accounts first', value: F.money(RT.est_tax)}, {op: '=', label: 'lower by', value: F.money(RT.est_tax_pro_rata - RT.est_tax)}]) +
      '<p>Selling inside a 401(k) or IRA triggers no tax, so the plan fills sells there before touching a taxable account. Hover a sell to see which purchase lots it would use.</p>'}] : []});
  if (Array.isArray(SB) && SB.length) { const hi = [...SB].sort((a, b) => (b.vol_annual || 0) - (a.vol_annual || 0))[0], lo = [...SB].sort((a, b) => (a.vol_annual || 0) - (b.vol_annual || 0))[0];
    F.help(g('bands-card'), {lead: 'Band widths sized to how bumpy each group has been over the past year.',
      sections: [{title: 'Wider for bumpier groups', html: `<p>${F.esc(hi.key)} swings about ${pct1(hi.vol_annual)} a year and gets a ${pct1(hi.absolute)} band; ${F.esc(lo.key)} swings ${pct1(lo.vol_annual)} and gets ${pct1(lo.absolute)}. A band that matches the swings flags real drift rather than ordinary noise.</p>`}]}); }
  // flags
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _money(v: object) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "—"
    v = float(v) + 0.0  # -0.0 -> 0.0 so a null withdrawal never prints as $-0.00
    return f"{'-' if v < 0 else ''}${abs(v):,.2f}"


def _pct(v: object) -> str:
    return f"{100 * v:.1f}%" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _headline(plan: dict) -> str:
    """Static one-line summary so the page reads without JavaScript."""
    bands = plan.get("bands") or {}
    trades = plan.get("trades") or []
    breaches = sum(1 for a in plan.get("allocation") or [] if a.get("breach"))
    return (
        f"{plan.get('mode') or '—'} rebalance of {_money(plan.get('total_value'))} · contribution {_money(plan.get('contribution'))}"
        f" · withdrawal {_money(plan.get('withdrawal'))} · frozen {_money(plan.get('frozen_value'))}"
        f" · bands {_pct(bands.get('absolute'))} / {_pct(bands.get('relative'))} · max drift {_pct(plan.get('max_drift'))}"
        f" · {breaches} breach{'' if breaches == 1 else 'es'} · {len(trades)} trade{'' if len(trades) == 1 else 's'} · est. tax {_money(plan.get('est_tax'))}"
    )


def build(plan: dict) -> str:
    if not isinstance(plan, dict) or "allocation" not in plan or "trades" not in plan:
        raise InvalidInput("input must be a plan.py or rebalance.py result (a JSON object with allocation and trades)")
    body = BODY.replace("{{HEADLINE}}", html.escape(_headline(plan)))
    return page.render(TITLE, plan, body, SCRIPT)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            plan = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read plan JSON: {exc}") from exc
        out = page.write(ns.out, build(plan))
        return {
            "out": str(out),
            "title": TITLE,
            "trades": len(plan.get("trades") or []),
            "breaches": sum(1 for a in plan.get("allocation") or [] if a.get("breach")),
            "flags": len(plan.get("flags") or []),
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
