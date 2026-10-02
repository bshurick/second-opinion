#!/usr/bin/env python3
"""Usage: render.py [--in review.json] --out page.html

Turns one ``run-review.py`` (or ``review.py``) result — a file, or stdin when ``--in`` is omitted —
into a self-contained interactive HTML page for the Artifact tool: stat tiles for the headline figures
(round trips, win rate, average return, total P&L, disposition PGR-PLR, median hold), a sortable and
searchable round-trips table (symbol, entry/exit dates, held days, return including dividends, the
buy-and-hold counterfactual, drift after the sale), a drift-after-sale chart with one bar per horizon
the script measured (30/90/180/365 days) for every sale, the counterfactual and disposition blocks as
bars against Odean's reference values, the open lots, the research queue (the news context stays in
the reply), the strategy matrix as a low/medium/high heat table with its evidence, the per-year table,
streaks, fees and re-entries, and the flags. Prints ``{"out": path, "title": ..., "round_trips": n,
"flags": n}``. Exit 2 on a missing or malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the review JSON; the page formats, sorts and filters, it never recomputes a figure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Trade Review"

BODY = """
<h1>Trade Review</h1>
<p class="sub" id="asof">Trade review from the imported ledger.</p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<section class="card"><h2 id="h-trips">Round trips</h2>
  <p class="sub">One row per completed trade: a buy (or several) matched with the sale that closed it, with dividends collected while it was open.</p>
  <div class="controls">
    <input id="q" type="search" placeholder="Search symbol or account" aria-label="Search round trips">
    <span class="muted" id="count"></span>
  </div>
  <div class="twrap" id="trips"></div>
  <p class="note" id="trips-note"></p>
  <details id="buys-card" hidden><summary>Largest buys per symbol</summary><div class="twrap" id="buys"></div></details>
</section>
<section class="card"><h2 id="h-drift">Drift after sale</h2>
  <p class="sub" id="drift-sub"></p>
  <div class="twrap"><div id="drift"></div></div>
</section>
<div class="grid2">
  <div class="card"><h2 id="h-cf">Counterfactuals</h2><p class="sub">What if you had not sold: the cash you received, versus what those shares would be worth today, versus the same cash parked in the benchmark.</p><p class="sub" id="cf-line"></p><div id="cf"></div></div>
  <div class="card"><h2 id="h-disp">Disposition effect (Odean 1998)</h2><p class="sub">How readily you sell winners compared with losers, measured against a well-known study of 10,000 brokerage accounts.</p><p class="sub" id="disp-line"></p><div id="disp"></div>
    <p class="note" id="disp-note">Odean (1998) found PGR 0.148 vs PLR 0.098 across 10,000 accounts; a positive gap means winners are sold and losers kept. Loss severity is a different lens: a large loss needs the fundamental review, not the disposition lens.</p></div>
</div>
<section class="card"><h2 id="h-lots">Open lots</h2><p class="sub">Shares you still hold, one row per purchase batch, with today's paper gain or loss.</p><div class="twrap" id="lots"></div></section>
<section class="card" id="rq-card"><h2 id="h-rq">What was happening</h2><p class="sub">Sales queued for news research; the dated context and its classification are in the reply, not on this page.</p><div class="twrap" id="rq"></div></section>
<section class="card"><h2 id="h-matrix">Strategy matrix</h2><p class="sub">Each row is a common trading style; the shaded cell says how closely your ledger matches it, judged from the evidence figures on the right.</p><div id="matrix"></div></section>
<div class="grid2">
  <div class="card"><h2 id="h-year">By year</h2><p class="sub">Completed trades and the money they made or lost, grouped by the year of the sale.</p><div class="twrap" id="yearly"></div><p class="note" id="streaks"></p></div>
  <div class="card"><h2 id="h-re">Re-entries within 30 days</h2><p class="sub">Times you bought a stock back within a month of selling it, and how much more you paid than you had sold it for.</p><div class="twrap" id="reentries"></div></div>
</div>
<section data-help="none"><h2 id="h-flags">Flags</h2><p class="sub">Things worth a second look, found automatically in the ledger.</p><ul class="flags" id="flags"></ul></section>
<p class="note">Lots are matched FIFO per account and symbol; dividends are spread over the open lots pro rata. Drift is the price h days after the sale relative to the sell price in the adjusted frame, so dividends after the sale count; horizons past the as-of date are blank. Buy-and-hold is what the sold shares would be worth at the as-of date, dividends included. The numbers separate outcome from decision quality: a sale followed by a rise is not automatically a mistake, and a sale followed by a fall is not automatically skill. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, S = D.summary || {}, F = FA;
  const g = id => document.getElementById(id);
  // terms this page needs that the shared glossary lacks (page.py is frozen; add them here)
  Object.assign(FA.glossary, {
    "profit factor": ["Total money made on winning trades divided by total money lost on losing trades; above 1 means the wins outweigh the losses.", "https://www.investopedia.com/terms/w/win-loss-ratio.asp"],
    "pgr": ["Proportion of gains realized: of the positions that were showing a gain on a sell day, the share you actually sold.", "https://www.investopedia.com/terms/d/disposition.asp"],
    "plr": ["Proportion of losses realized: of the positions that were showing a loss on a sell day, the share you actually sold.", "https://www.investopedia.com/terms/d/disposition.asp"],
    "p&l": ["Profit and loss: the money made or lost, here the realized gain on the sale plus dividends received while holding.", "https://www.investopedia.com/terms/r/realizedprofit.asp"],
    "realized p&l": ["The gain or loss locked in by a sale: sale proceeds minus what the shares cost.", "https://www.investopedia.com/terms/r/realizedprofit.asp"],
    "holding period": ["How long a position was held, from the first buy to the sale.", "https://www.investopedia.com/terms/h/holdingperiod.asp"],
    "median": ["The middle value when everything is lined up in order; unlike the average, one extreme trade does not pull it.", "https://www.investopedia.com/terms/m/median.asp"],
    "average cost": ["What you paid per share on average across the buys that make up a position.", "https://www.investopedia.com/terms/a/averagecostbasismethod.asp"],
    "dividend": ["Cash a company pays out to shareholders, usually every quarter.", "https://www.investopedia.com/terms/d/dividend.asp"],
    "benchmark": ["A reference investment (here an index fund such as SPY) that your result is compared with over the same dates.", "https://www.investopedia.com/terms/b/benchmark.asp"],
    "open lot": ["A batch of shares bought at one time and price that you still hold.", "https://www.investopedia.com/terms/o/open-position.asp"],
  });
  const T = (k, label) => FA.term(k, label);
  // FA.table and FA.bars escape their labels, so glossary marks go into the finished header cells / bar labels afterwards
  const termHeads = (root, map) => { root.querySelectorAll('th[data-key]').forEach(th => { const m = map[th.dataset.key]; if (m) th.innerHTML = T(m[0], m[1]); }); FA.armTerms(root); };
  const termBars = (root, labels) => { root.querySelectorAll('.bar > .l').forEach((s, i) => { if (labels[i]) s.innerHTML = labels[i]; }); FA.armTerms(root); };
  const dateFmt = d => d ? new Date(d + 'T00:00:00').toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'}) : '—';
  const L = D.ledger || {}, R = L.date_range || {};
  const bench = (D.counterfactual || {}).benchmark_symbol;
  g('asof').textContent = `As of ${dateFmt(D.as_of)}` + (L.transactions_used != null ? ` · ${L.transactions_used} ledger rows` : '') +
    (L.accounts ? ` · accounts ${L.accounts.join(', ')}` : '') + (R.start ? ` · ${R.start} to ${R.end}` : '') + (bench ? ` · benchmark ${bench}` : '');
  FA.explain(g('explain'), `<p>This page looks back at the trades in your imported ledger: every completed ${T('round trip')} (a purchase matched with the sale that closed it), what each one made or lost with ${T('dividend', 'dividends')} included, and what the price did after you sold.</p>
<p>Every number comes from your own transaction history plus daily prices${bench ? ` and the ${T('benchmark')} ${F.esc(bench)}` : ''}; nothing here is a forecast.</p>
<p>The bar chart shows the price change after each sale at several horizons (${T('drift after sale', 'drift after sale')}): bars above zero mean the price kept rising after you sold, bars below mean it fell. The ${T('disposition effect')} block compares how readily you sell winners versus losers with a large academic study.</p>
<p>The one caveat that matters most: a sale followed by a rise was not necessarily a mistake, and a sale followed by a fall was not necessarily skill. Outcome and decision quality are different things, and a few trades are a small sample.</p>`);
  g('h-trips').innerHTML = T('round trip', 'Round trips');
  g('h-drift').innerHTML = T('drift after sale', 'Drift after sale');
  g('h-cf').innerHTML = T('buy-and-hold counterfactual', 'Counterfactuals');
  g('h-disp').innerHTML = `${T('disposition effect', 'Disposition effect')} (Odean 1998)`;
  g('h-lots').innerHTML = T('open lot', 'Open lots');
  g('disp-note').innerHTML = `Odean (1998) found ${T('pgr', 'PGR')} 0.148 vs ${T('plr', 'PLR')} 0.098 across 10,000 accounts; a positive gap means winners are sold and losers kept. Loss severity is a different lens: a large loss needs the fundamental review, not the disposition lens.`;
  const DP = D.disposition || {};
  const tiles = [
    [T('round trip', 'Round trips'), F.num(S.round_trips, 0), `${S.buys ?? '—'} buys · ${S.sells ?? '—'} sells · ${F.num(S.trades_per_year, 1)} trades/yr`],
    [T('win rate', 'Win rate'), F.pct(S.win_rate), `${T('profit factor')} ${F.num(S.profit_factor)}`],
    ['Average return', `<span class="${F.cls(S.avg_return)}">${F.pct(S.avg_return, 1, true)}</span>`, `${T('median')} ${F.pct(S.median_return, 1, true)} · ${T('dividend', 'dividends')} included`],
    [T('p&l', 'Total P&L'), `<span class="${F.cls(S.total_pnl)}">${F.moneyS(S.total_pnl)}</span>`, `${T('realized p&l', 'realized')} ${F.moneyS(S.realized_pnl)} + dividends ${F.money(S.dividends_captured)}`],
    [`${T('disposition effect', 'Disposition')} ${T('pgr', 'PGR')}−${T('plr', 'PLR')}`, `<span class="${F.cls(DP.disposition)}">${F.pct(DP.disposition, 1, true)}</span>`, `PGR ${F.pct(DP.pgr)} vs PLR ${F.pct(DP.plr)} · Odean 14.8% vs 9.8%`],
    [T('holding period', 'Median hold'), F.isNum(S.median_holding_days) ? `${F.num(S.median_holding_days, 0)} d` : '—', `average ${F.num(S.avg_holding_days, 0)} d · span ${S.span_days ?? '—'} d`],
  ];
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  FA.armTerms(g('tiles'));
  // round trips
  const trips = (D.round_trips || []).map(t => ({...t, drift_90: (t.drift || {})['90'] ?? null, drift_365: (t.drift || {})['365'] ?? null}));
  const cols = [
    {key: 'symbol', label: 'Symbol', left: true, fmt: (v, r) => `<b>${F.esc(v)}</b>${r.lots > 1 ? `<span class="muted"> ${r.lots} lots</span>` : ''}`},
    {key: 'first_buy_date', label: 'Bought', left: true, fmt: v => F.esc(v || '—')},
    {key: 'sell_date', label: 'Sold', left: true, fmt: v => F.esc(v || '—')},
    {key: 'holding_days', label: 'Days', fmt: v => F.num(v, 0)},
    {key: 'units', label: 'Units', fmt: v => F.num(v, 2)},
    {key: 'avg_cost', label: 'Avg cost', fmt: v => F.money(v)},
    {key: 'sell_price', label: 'Sell price', fmt: v => F.money(v)},
    {key: 'dividends', label: 'Dividends', fmt: v => F.money(v)},
    {key: 'total_pnl', label: 'Total P&L', fmt: v => F.moneyS(v), cls: F.cls},
    {key: 'total_return', label: 'Return', fmt: v => F.pct(v, 1, true), cls: F.cls},
    {key: 'hold_delta', label: 'Buy & hold', fmt: (v, r) => F.isNum(v) ? `${F.moneyS(v)}<span class="muted"> (${F.money(r.hold_value, 0)})</span>` : '—', cls: F.cls},
    {key: 'drift_90', label: '90d after', fmt: v => F.pct(v, 1, true)},
    {key: 'drift_vs_benchmark_90', label: `vs ${bench || 'bench'} 90d`, fmt: v => F.pct(v, 1, true)},
    {key: 'account_id', label: 'Account', left: true, fmt: v => F.esc(v || '—')},
  ];
  const tripHeads = {holding_days: ['holding period', 'Days'], avg_cost: ['average cost', 'Avg cost'], dividends: ['dividend', 'Dividends'], total_pnl: ['p&l', 'Total P&L'],
    hold_delta: ['buy-and-hold counterfactual', 'Buy & hold'], drift_90: ['drift after sale', '90d after'], drift_vs_benchmark_90: ['benchmark', `vs ${bench || 'bench'} 90d`]};
  if (trips.length) {
    const tbl = F.table(g('trips'), cols, trips, {sortKey: 'sell_date', onDraw: vis => { g('count').textContent = `${vis.length} of ${trips.length}`; FA.armTerms(g('trips')); }});
    termHeads(g('trips'), tripHeads);
    g('q').addEventListener('input', e => tbl.setQuery(e.target.value));
  } else { g('trips').innerHTML = '<span class="muted">no completed round trips in the ledger</span>'; g('count').textContent = ''; }
  const notes = [];
  if ((D.unmatched_sells || []).length) notes.push('Unmatched sells: ' + D.unmatched_sells.map(u => `${F.esc(u.symbol)} ${u.date} (${F.num(u.units, 2)} units, ${F.esc(u.account_id)})`).join('; ') + '.');
  if ((D.missing_prices || []).length) notes.push('Symbols without prices: ' + D.missing_prices.map(F.esc).join(', ') + '.');
  if (F.isNum(D.unattributed_dividends) && D.unattributed_dividends > 0) notes.push(`Dividends with no open lot: ${F.money(D.unattributed_dividends)}.`);
  g('trips-note').innerHTML = notes.join(' ');
  const LB = D.largest_buys || [];
  if (LB.length) { g('buys-card').hidden = false;
    g('buys').innerHTML = '<table><thead><tr><th class="l">Symbol</th><th class="l">Date</th><th>Units</th><th>Price</th><th>Amount</th></tr></thead><tbody>' +
      LB.map(b => `<tr><td class="l"><b>${F.esc(b.symbol)}</b></td><td class="l">${F.esc(b.date)}</td><td>${F.num(b.units, 2)}</td><td>${F.money(b.price)}</td><td>${F.money(b.amount)}</td></tr>`).join('') + '</tbody></table>'; }
  // drift after sale: grouped bars, one group per sale, one bar per horizon
  const HZ = Object.keys((trips.find(t => t.drift) || {}).drift || {}).sort((a, b) => +a - +b);
  const withDrift = trips.filter(t => t.drift && HZ.some(h => F.isNum(t.drift[h])));
  const MAXG = 40, shown = withDrift.slice(-MAXG);
  if (!shown.length) { g('drift').innerHTML = '<span class="muted">no post-sale prices (run without --no-prices to measure drift)</span>'; g('drift-sub').textContent = ''; }
  else {
    g('drift-sub').textContent = `Price change after each sale, measured from the sell price, at ${HZ.join('/')} days` + (withDrift.length > MAXG ? ` · last ${MAXG} of ${withDrift.length} sales` : '') + '. Hover for the benchmark over the same window.';
    const bw = Math.max(12, Math.min(26, Math.floor((900 / shown.length - 12) / HZ.length))), gw = (bw + 2) * HZ.length + 12, m = {t: 14, r: 12, b: 42, l: 52}, ih = 220;
    const W = m.l + m.r + gw * shown.length, H = m.t + m.b + ih;
    const vals = shown.flatMap(t => HZ.map(h => t.drift[h])).filter(F.isNum);
    let y0 = Math.min(0, ...vals), y1 = Math.max(0, ...vals); if (y1 === y0) y1 = y0 + 0.1; const pad = (y1 - y0) * 0.06; y0 -= pad; y1 += pad;
    const Y = v => m.t + ih * (1 - (v - y0) / (y1 - y0));
    const ticks = []; for (let k = 0; k <= 4; k++) ticks.push(y0 + (y1 - y0) * k / 4);
    let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" style="min-width:${Math.min(W, 960)}px" role="img" aria-label="drift after sale by horizon">`;
    s += ticks.map(t => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="var(--grid)"/><text x="${m.l - 6}" y="${(Y(t) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${F.pct(t, 0)}</text>`).join('');
    s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="var(--muted)" stroke-dasharray="2 3"/>`;
    shown.forEach((t, i) => { const x0 = m.l + gw * i + 6;
      HZ.forEach((h, j) => { const v = t.drift[h]; if (!F.isNum(v)) return; const x = x0 + (bw + 2) * j; const yv = Y(v), yz = Y(0);
        s += `<rect data-i="${i}" data-h="${h}" x="${x}" y="${Math.min(yv, yz).toFixed(1)}" width="${bw}" height="${Math.max(1, Math.abs(yv - yz)).toFixed(1)}" fill="${F.S[j % 8]}" rx="1"/>`; });
      const cx = x0 + (bw + 2) * HZ.length / 2 - 1;
      s += `<text x="${cx.toFixed(1)}" y="${H - 26}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--ink)">${F.esc(t.symbol)}</text><text x="${cx.toFixed(1)}" y="${H - 12}" text-anchor="middle" font-size="10" fill="var(--muted)">${F.esc(t.sell_date)}</text>`; });
    s += '</svg>';
    g('drift').innerHTML = s;
    const lg = F.el('div', {class: 'legend'}); HZ.forEach((h, j) => lg.appendChild(F.el('span', {}, `<i style="background:${F.S[j % 8]}"></i>${h} days`))); g('drift').appendChild(lg);
    g('drift').querySelectorAll('rect[data-i]').forEach(r => { const t = shown[+r.dataset.i], h = r.dataset.h; const bd = (t.benchmark_drift || {})[h];
      F.bindTip(r, `<b>${F.esc(t.symbol)}</b> sold ${F.esc(t.sell_date)} at ${F.money(t.sell_price)}<br>${h} days after: <b>${F.pct(t.drift[h], 1, true)}</b>` + (F.isNum(bd) ? `<br>${F.esc(bench || 'benchmark')} same window: ${F.pct(bd, 1, true)}` : '')); });
  }
  // counterfactuals
  const C = D.counterfactual || {};
  if (F.isNum(C.proceeds)) {
    g('cf-line').textContent = `Sale proceeds ${F.money(C.proceeds)}; holding instead would be worth ${F.money(C.hold_value)} (${F.moneyS(C.hold_delta)}); proceeds in ${bench || 'the benchmark'} would be ${F.money(C.proceeds_in_benchmark)}.`;
    const rows = [['Proceeds received', C.proceeds, F.S[0], 'Proceeds received'], ['Held instead (as-of value)', C.hold_value, F.S[1], T('buy-and-hold counterfactual', 'Held instead (as-of value)')],
      [`Proceeds in ${bench || 'benchmark'}`, C.proceeds_in_benchmark, F.S[2], `Proceeds in ${T('benchmark', bench || 'benchmark')}`]].filter(r => F.isNum(r[1]));
    const max = Math.max(...rows.map(r => Math.abs(r[1])), 1e-9);
    F.bars(g('cf'), rows.map(([label, v, color]) => ({label, share: v / max, color, text: F.money(v, 0)})));
    termBars(g('cf'), rows.map(r => r[3]));
  } else { g('cf-line').textContent = 'No counterfactuals: prices were not available for the sold symbols.'; }
  // disposition
  if (F.isNum(DP.pgr) || F.isNum(DP.plr)) {
    g('disp-line').innerHTML = `Realized ${DP.realized_gains ?? '—'} gains vs ${DP.paper_gains ?? '—'} paper gains (${T('pgr', 'PGR')} ${F.pct(DP.pgr)}), ${DP.realized_losses ?? '—'} losses vs ${DP.paper_losses ?? '—'} paper losses (${T('plr', 'PLR')} ${F.pct(DP.plr)}), over ${DP.sell_days ?? '—'} sell days.`;
    const rows = [['Your PGR', DP.pgr, F.S[0]], ['Your PLR', DP.plr, F.S[1]], ['Odean PGR', 0.148, F.S[0]], ['Odean PLR', 0.098, F.S[1]]];
    F.bars(g('disp'), rows.map(([label, v, color]) => ({label, share: v, color, text: F.pct(v)})));
    termBars(g('disp'), [`Your ${T('pgr', 'PGR')}`, `Your ${T('plr', 'PLR')}`, `Odean ${T('pgr', 'PGR')}`, `Odean ${T('plr', 'PLR')}`]);
    g('disp').querySelectorAll('.bar').forEach((b, i) => { if (i >= 2) b.style.opacity = '.55'; });
  } else { g('disp-line').textContent = 'Not measurable: the disposition effect needs prices on each sell day.'; }
  // open lots
  const lots = D.open_lots || [];
  if (lots.length) F.table(g('lots'), [
    {key: 'symbol', label: 'Symbol', left: true, fmt: v => `<b>${F.esc(v)}</b>`},
    {key: 'buy_date', label: 'Bought', left: true, fmt: v => F.esc(v || '—')},
    {key: 'holding_days', label: 'Days', fmt: v => F.num(v, 0)},
    {key: 'units', label: 'Units', fmt: v => F.num(v, 2)},
    {key: 'avg_cost', label: 'Avg cost', fmt: v => F.money(v)},
    {key: 'price', label: 'Price', fmt: v => F.money(v)},
    {key: 'value', label: 'Value', fmt: v => F.money(v)},
    {key: 'dividends', label: 'Dividends', fmt: v => F.money(v)},
    {key: 'unrealized_pnl', label: 'Unrealized', fmt: v => F.moneyS(v), cls: F.cls},
    {key: 'unrealized_return', label: 'Return', fmt: v => F.pct(v, 1, true), cls: F.cls},
    {key: 'account_id', label: 'Account', left: true, fmt: v => F.esc(v || '—')},
  ], lots, {sortKey: 'value', onDraw: () => FA.armTerms(g('lots'))});
  else g('lots').innerHTML = '<span class="muted">no open lots</span>';
  if (lots.length) termHeads(g('lots'), {holding_days: ['holding period', 'Days'], avg_cost: ['average cost', 'Avg cost'], dividends: ['dividend', 'Dividends'], unrealized_pnl: ['unrealized p&l', 'Unrealized']});
  // research queue
  const RQ = D.research_queue || [];
  g('rq').innerHTML = RQ.length ? `<table><thead><tr><th class="l">Symbol</th><th class="l">Bought</th><th class="l">Sold</th><th class="l">Why</th><th>${T('p&l', 'Total P&L')}</th><th>${T('drift after sale', '90d after')}</th></tr></thead><tbody>` +
    RQ.map(q => `<tr><td class="l"><b>${F.esc(q.symbol)}</b></td><td class="l">${F.esc(q.first_buy_date || '—')}</td><td class="l">${F.esc(q.sell_date)}</td><td class="l">${F.esc(q.why)}</td><td class="${F.cls(q.total_pnl)}">${F.moneyS(q.total_pnl)}</td><td>${F.pct(q.drift_90, 1, true)}</td></tr>`).join('') + '</tbody></table>'
    : '<span class="muted">nothing queued</span>';
  // strategy matrix: rows = strategies, columns = alignment levels, plus the evidence verbatim
  const M = D.strategy_matrix || [], LV = ['low', 'medium', 'high'];
  const lvColor = i => `color-mix(in oklab, var(--s1) ${[30, 60, 100][i]}%, var(--surface))`;
  const evid = e => Object.entries(e || {}).map(([k, v]) => `<span style="white-space:nowrap">${F.esc(k)} = <b>${F.isNum(v) ? (Number.isInteger(v) ? v : F.num(v, 4)) : F.esc(v)}</b></span>`).join('<span class="muted"> · </span>');
  g('matrix').innerHTML = M.length ? '<div class="twrap"><table class="heat"><thead><tr><th class="l">Strategy</th>' + LV.map(l => `<th style="text-align:center">${l}</th>`).join('') + '<th class="l">Evidence</th></tr></thead><tbody>' +
    M.map(r => `<tr><td class="l"><b>${F.esc(String(r.strategy).replace(/_/g, ' '))}</b></td>` + LV.map((l, i) => r.alignment === l ? `<td style="background:${lvColor(i)};text-align:center;font-weight:600">${l}</td>` : '<td style="text-align:center;color:var(--muted)">·</td>').join('') + `<td class="l" style="white-space:normal;font-size:12px">${evid(r.evidence)}</td></tr>`).join('') + '</tbody></table></div>'
    : '<span class="muted">no matrix (needs at least one round trip)</span>';
  // yearly, streaks, fees, re-entries
  const Yr = D.yearly || [];
  g('yearly').innerHTML = Yr.length ? `<table><thead><tr><th class="l">Year</th><th>${T('round trip', 'Round trips')}</th><th>${T('realized p&l', 'Realized P&L')}</th><th>${T('dividend', 'Dividends')}</th></tr></thead><tbody>` +
    Yr.map(y => `<tr><td class="l">${F.esc(y.year)}</td><td>${F.num(y.round_trips, 0)}</td><td class="${F.cls(y.realized_pnl)}">${F.moneyS(y.realized_pnl)}</td><td>${F.money(y.dividends)}</td></tr>`).join('') + '</tbody></table>' : '<span class="muted">no completed years</span>';
  const ST = D.streaks || {}, cur = ST.current || {};
  g('streaks').textContent = `Current streak: ${cur.kind ? `${cur.length} ${cur.kind}${cur.length === 1 ? '' : cur.kind === 'loss' ? 'es' : 's'}` : 'none'} · longest win run ${ST.max_win ?? '—'} · longest loss run ${ST.max_loss ?? '—'}` + (F.isNum(D.fees_total) ? ` · fees ${F.money(D.fees_total)}` : '');
  const RE = D.reentries || [];
  g('reentries').innerHTML = RE.length ? '<table><thead><tr><th class="l">Symbol</th><th class="l">Sold</th><th>Sell price</th><th class="l">Re-bought</th><th>Re-buy price</th><th>Premium</th></tr></thead><tbody>' +
    RE.map(r => `<tr><td class="l"><b>${F.esc(r.symbol)}</b></td><td class="l">${F.esc(r.sell_date)}</td><td>${F.money(r.sell_price)}</td><td class="l">${F.esc(r.rebuy_date)}</td><td>${F.money(r.rebuy_price)}</td><td>${F.pct(r.delta_pct, 1, true)}</td></tr>`).join('') + '</tbody></table>'
    : '<span class="muted">none — no symbol was re-bought above its sale price within 30 days</span>';
  // card help
  const card = id => g(id).parentElement;
  const t0 = trips.slice().sort((a, b) => Math.abs(b.total_pnl || 0) - Math.abs(a.total_pnl || 0))[0];
  F.help(card('h-trips'), {lead: 'Each completed trade: a purchase matched with the sale that closed it, with dividends collected in between.',
    sections: t0 && F.isNum(t0.proceeds) && F.isNum(t0.cost) ? [{title: `The largest one: ${t0.symbol}`, html: F.flow([{label: 'sold for', value: F.money(t0.proceeds)}, {op: '−', label: 'paid', value: F.money(t0.cost)}, {op: '+', label: 'dividends', value: F.money(t0.dividends || 0)}, {op: '=', label: 'result', value: F.moneyS(t0.total_pnl)}])}] :
      [{title: 'Reading a row', html: '<p>Profit is what the sale brought in minus what the shares cost, plus any dividends received while holding them.</p>'}]});
  F.help(card('h-drift'), {lead: 'What the price did after you sold, at several horizons.',
    sections: [{title: 'Reading the bars', html: '<p>Each bar is one sale. Above zero, the price kept rising after you sold; below zero, it fell. Mostly above zero means the shares kept gaining after the sales; mostly below zero means the sales came before declines.</p>'}]});
  F.help(card('h-cf'), {lead: 'What if you had not sold: three ways the same money could have ended up.',
    sections: F.isNum(C.hold_value) && F.isNum(C.hold_delta) ? [{title: 'Held instead', html: F.flow([{label: 'shares kept, worth today', value: F.money(C.hold_value, 0)}, {op: '\u2212', label: 'cash received on those sales', value: F.money(C.hold_value - C.hold_delta, 0)}, {op: '=', label: 'difference', value: F.moneyS(C.hold_delta)}]) +
      `<p>The third bar puts the same cash into ${F.esc(bench || 'the benchmark')} on each sale date instead.</p>`}] : []});
  F.help(card('h-disp'), {lead: 'Whether you sell winners more readily than losers, a habit Terrance Odean measured across 10,000 brokerage accounts.',
    sections: [{title: 'PGR and PLR', html: `<p>On each day you sold something, every holding counts as either a gain or a loss on paper. PGR is the share of the gains you actually sold; PLR the share of the losses. In Odean’s study PGR was 14.8% and PLR 9.8%: people sold winners about half again as often as losers.</p>` +
      (F.isNum(DP.pgr) && F.isNum(DP.plr) ? F.flow([{label: 'your PGR', value: F.pct(DP.pgr)}, {op: '−', label: 'your PLR', value: F.pct(DP.plr)}, {op: '=', label: 'gap', value: F.pct(DP.pgr - DP.plr, 1, true)}]) : '')}]});
  F.help(card('h-lots'), {lead: 'Shares you still hold, one row per purchase batch, with today’s paper gain or loss.',
    sections: [{title: 'Paper, not realized', html: '<p>A paper gain or loss only becomes real, and taxable, when the shares are sold.</p>'}]});
  F.help(g('rq-card'), {lead: 'Sales lined up for a look at the news around them.',
    sections: [{title: 'How it is used', html: '<p>The dated stories behind each sale are gathered in the reply, not stored on this page; this list is what was looked up.</p>'}]});
  F.help(card('h-matrix'), {lead: 'How closely your trades match common trading styles, judged from the evidence figures on this page.',
    sections: [{title: 'Reading a row', html: '<p>Each row names a style, such as momentum or buy-and-hold; the shaded cell (low, medium, high) says how closely the ledger fits it, and the evidence column says why. It describes past trades, not which style to use.</p>'}]});
  const y0 = Yr[Yr.length - 1];
  F.help(card('h-year'), {lead: 'Completed trades and the money they made or lost, grouped by the year of the sale.',
    sections: y0 ? [{title: String(y0.year), html: F.flow([{label: 'realized profit or loss', value: F.moneyS(y0.realized_pnl)}, {op: '+', label: 'dividends', value: F.money(y0.dividends)}, {op: '=', label: 'total', value: F.moneyS((y0.realized_pnl || 0) + (y0.dividends || 0))}])}] : []});
  F.help(card('h-re'), {lead: 'Times you bought a stock back within a month of selling it, at a higher price.',
    sections: [{title: 'Why 30 days', html: '<p>Buying back within 30 days of selling at a loss is also the wash-sale window for taxes; here the list shows any quick re-buy above the sale price, which is the cost of having stepped out.</p>'}]});
  // flags
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
  FA.armTerms(document);
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def build(review: dict) -> str:
    if not isinstance(review, dict) or "summary" not in review or "round_trips" not in review:
        raise InvalidInput("input must be a run-review.py result (a JSON object with summary and round_trips)")
    return page.render(TITLE, review, BODY, SCRIPT)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            review = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read review JSON: {exc}") from exc
        out = page.write(ns.out, build(review))
        return {"out": str(out), "title": TITLE, "round_trips": len(review.get("round_trips") or []), "flags": len(review.get("flags") or [])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
