#!/usr/bin/env python3
"""Usage: render.py [--in risk.json] --out page.html

Turns one ``stress.py`` (or ``risk.py``) result (a file, or stdin when ``--in`` is omitted) into a
self-contained interactive HTML page for the Artifact tool: the SHORT_HISTORY / MISSING_PRICES
warnings first, stat tiles for the headline figures (volatility, beta, max drawdown, 1-day VaR 95%,
Sharpe, diversification ratio), a sortable positions table, risk-contribution bars, the correlation
matrix as a diverging heatmap (or the strongest pairs when the script returned pairs), concentration,
the scenarios as loss bars in dollars and percent (replay, mixed or beta-scaled labelled) with a click-through
to each scenario's per-position returns, the what-if shocks, factor betas and liquidity when present,
the flags and a closing caveat. Prints ``{"out": path, "title": ..., "positions": n, "scenarios": n,
"flags": n}``. Exit 2 on a missing or malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the risk JSON; the page formats, sorts and filters, it never recomputes a statistic.
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

TITLE = "Portfolio Risk"

BODY = """
<h1>Portfolio Risk</h1>
<p class="sub" id="asof">{{HEADLINE}}</p>
<div id="explain"></div>
<ul class="flags" id="lead" hidden></ul>
<div class="tiles" id="tiles"></div>
<div class="grid2">
  <div class="card"><h2 id="contrib-h">Risk contribution</h2><p class="sub" id="contrib-sub">How much of the portfolio's day-to-day swing each holding causes, counting how it moves with the others. A holding can cause more of the risk than its weight alone would indicate.</p><div id="contrib"></div></div>
  <div class="card"><h2 id="corr-h">Correlation</h2><p class="sub" id="corr-sub"></p><div id="corr"></div><p class="note" id="conc"></p></div>
</div>
<section class="card" id="positions-card"><h2>Positions</h2><p class="sub">Each holding's own risk figures over the same window. Click a column header to sort.</p>
  <div class="controls"><input id="q" type="search" placeholder="Search symbol" aria-label="Search positions"><span class="muted" id="count"></span></div>
  <div class="twrap" id="positions"></div>
</section>
<section class="card"><h2 id="scen-h">Scenarios</h2><p class="sub" id="scen-sub">What today's portfolio would have lost in past crashes. Replay uses each holding's own prices over that window; beta-scaled multiplies the portfolio's beta by the benchmark's fall when the window is older than the price history. Click a scenario for its position returns.</p>
  <div id="scen-bars"></div>
  <div class="twrap" id="scenarios" style="margin-top:12px"></div>
  <div id="scen-detail" style="margin-top:12px"></div>
</section>
<section class="card" id="whatif-card" hidden><h2>What if</h2><p class="sub" id="whatif-line"></p><div class="twrap" id="whatif"></div></section>
<div class="grid2">
  <div class="card" id="factors-card" hidden><h2 id="factors-h">Factor exposure</h2><p class="sub" id="factors-sub">How much the portfolio moves with each broad market style, measured one style at a time against a proxy ETF. A beta of 0.5 means the portfolio moved about half as much as that style did; explained variance says how much of the portfolio's movement that style accounts for.</p><div class="twrap" id="factors"></div><p class="note" id="factors-note"></p></div>
  <div class="card" id="liq-card" hidden><h2 id="liq-h">Liquidity</h2><p class="sub" id="liq-sub">How big each position is next to the dollar value of that stock that trades on a typical day (the 20-day average). A position that is a large share of a day's volume is slow or costly to sell.</p><div class="twrap" id="liquidity"></div></div>
</div>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Volatility, beta and correlation are estimated from the window shown; they rise in crises (correlations go to one), so beta-scaled scenario losses are a floor, not a ceiling. Historical VaR at 95% is the 1-day loss exceeded on about 1 day in 20 over the window; CVaR is the average of those days. Neither captures gaps or liquidity. Max drawdown assumes today's weights held throughout the window, which differs from what the account experienced. A replay is one path. Past drawdowns and simulated shocks are not forecasts. General information at the stated assumptions, not financial advice.</p>
<noscript><p class="note">JavaScript is off: the charts and tables are not drawn. The headline figures are in the line under the title; the full result is embedded in the page as JSON.</p></noscript>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, P = D.portfolio || {}, F = FA;
  const g = id => document.getElementById(id);
  const pct1 = v => F.pct(v, 1), n2 = v => F.num(v, 2), money0 = v => F.money(v, 0);
  const negPct = v => F.isNum(v) ? '-' + pct1(v) : '—';
  // terms this page needs that the shared glossary lacks (page.py is frozen; add them here)
  Object.assign(F.glossary, {
    'tracking error': ['How much a holding\'s returns differ from those of the index it is meant to follow, annualized; 0% would mean it tracks that index exactly. Each holding is measured against its own category index (a bond fund against BND, an international fund against VXUS, US equity against the benchmark); the portfolio figure is against the benchmark.', 'https://www.investopedia.com/terms/t/trackingerror.asp'],
    'parametric var': ['VaR worked out by assuming daily returns follow a bell curve, instead of reading the loss off the actual history; the two differ when returns have fat tails.', 'https://www.investopedia.com/terms/v/var.asp'],
    'benchmark': ['The index fund the portfolio is compared with; beta, correlation, capture and the portfolio\'s tracking error are measured against it. Each holding\'s own tracking error uses its category index instead.', 'https://www.investopedia.com/terms/b/benchmark.asp'],
    'factor': ['A broad market style, such as small companies, momentum, value or credit, that many stocks move with together; each is measured here with a proxy ETF.', 'https://www.investopedia.com/terms/f/factor-investing.asp'],
    'adv': ['Average daily volume: the dollar value of a stock that trades on a typical day, here the 20-day average; a position that is a large share of it takes longer to sell.', 'https://www.investopedia.com/terms/a/averagedailytradingvolume.asp'],
  });
  // plain names for the proxy ETFs stress.py regresses on (FACTOR_PROXIES); unknown tickers show as-is
  const FACTOR_NAMES = {IJR: 'small companies (size)', MTUM: 'momentum', VLUE: 'value', HYG: 'credit (high-yield bonds)'};
  // table headers come out escaped from FA.table; swap in the term markup once (thead is built once)
  const termHeads = (root, map) => { root.querySelectorAll('th[data-key]').forEach(th => { if (map[th.dataset.key]) th.innerHTML = map[th.dataset.key]; }); F.armTerms(root); };
  const setHtml = (id, html) => { const n = g(id); n.innerHTML = html; F.armTerms(n); };
  // what am I looking at?
  FA.explain(g('explain'), `<p>This page measures how bumpy the portfolio has been and what it could lose. Every number is estimated from the daily prices of the holdings over the window in the line above, weighted the way the account is held today, and compared with a ${FA.term('benchmark')} index fund.</p><p>Read the tiles first: ${FA.term('volatility')} is the size of a typical swing, ${FA.term('max drawdown')} the worst fall from a high, and ${FA.term('var', 'VaR')} the loss a bad day can bring. The scenario bars replay past crashes at today's weights.</p><p>The caveat that matters most: these are estimates from recent history. In a real crisis holdings fall together and losses run larger than the past suggests, so treat the figures as a floor, not a ceiling.</p>`);
  // lead warnings: the reader needs to know the statistics are noisy or partial before the numbers
  const lead = (D.flags || []).filter(f => f.code === 'SHORT_HISTORY' || f.code === 'MISSING_PRICES');
  if (lead.length) { g('lead').hidden = false; g('lead').innerHTML = lead.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join(''); }
  // tiles
  // Plain-words labels on top; the technical name and its hover help sit in each tile's detail line.
  const tiles = [
    ['Typical yearly swing', pct1(P.volatility), `${FA.term('volatility', 'volatility')}, annualized`],
    ['Moves with the market', F.isNum(P.beta) ? n2(P.beta) + '×' : n2(P.beta), `per 1% move in ${FA.term('benchmark', P.benchmark || 'the benchmark')} (${FA.term('beta', 'beta')}) · ${FA.term('tracking error')} ${pct1(P.tracking_error)}`],
    ['Worst fall so far', `<span class="neg">${negPct(P.max_drawdown)}</span>`, `from a high, at today's weights (${FA.term('max drawdown', 'max drawdown')})`],
    ['A bad day', `<span class="neg">${negPct(P.var_95)}</span>`, `about 1 day in 20 loses this or more (${FA.term('var', 'VaR 95%')}); those days average ${negPct(P.cvar_95)} (${FA.term('cvar', 'CVaR')})`],
    ['Return for the risk', n2(P.sharpe), `${FA.term('sharpe ratio', 'Sharpe ratio')} over the window · ${FA.term('sortino ratio', 'Sortino')} ${n2(P.sortino)}`],
    ['Spreading benefit', n2(P.diversification_ratio), `${FA.term('diversification ratio', 'diversification ratio')}: 1 means none · avg ${FA.term('correlation', 'correlation')} ${n2(P.avg_pairwise_correlation)}`],
  ];
  setHtml('tiles', tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join(''));
  // section headings and subtitles: the static text stays for readers without JS; with JS the jargon gets its term markup
  setHtml('contrib-h', FA.term('risk contribution', 'Risk contribution'));
  setHtml('corr-h', FA.term('correlation', 'Correlation'));
  setHtml('scen-h', FA.term('stress test', 'Scenarios'));
  setHtml('scen-sub', `What today's portfolio would have lost in past crashes. Replay uses each holding's own prices over that window; beta-scaled multiplies the portfolio's ${FA.term('beta')} by the ${FA.term('benchmark', "benchmark's")} fall when the window is older than the price history. Click a scenario for its position returns.`);
  setHtml('factors-h', FA.term('factor exposure', 'Factor exposure'));
  setHtml('factors-sub', `How much the portfolio moves with each broad market style (a ${FA.term('factor')}), measured one style at a time against a proxy ${FA.term('etf', 'ETF')}. A ${FA.term('beta')} of 0.5 means the portfolio moved about half as much as that style did; ${FA.term('explained variance')} says how much of the portfolio's movement that style accounts for.`);
  setHtml('liq-h', FA.term('liquidity', 'Liquidity'));
  setHtml('liq-sub', `How big each position is next to the dollar value of that stock that trades on a typical day (the 20-day ${FA.term('adv', 'average daily volume')}). A position that is a large share of a day's volume is slow or costly to sell.`);
  // one colour per symbol, assigned by position order and never re-indexed
  const pos = D.positions || [];
  const colorOf = {}; pos.forEach((p, i) => { colorOf[p.symbol] = F.S[i % 8]; });
  const color = s => colorOf[s] || 'var(--muted)';
  // risk contribution bars
  const rc = (D.risk_contributions || []).slice().sort((a, b) => (b.share || 0) - (a.share || 0));
  if (!rc.length) g('contrib').innerHTML = '<span class="muted">no covered positions</span>';
  else F.bars(g('contrib'), rc.map(r => ({label: r.symbol, share: r.share, color: color(r.symbol), text: `${pct1(r.share)} · weight ${pct1(r.weight)}`,
    tip: `<b>${F.esc(r.symbol)}</b><br>share of variance ${pct1(r.share)}<br>weight ${pct1(r.weight)} · contribution ${F.num(r.contribution, 4)}`})));
  // correlation
  const C = D.correlation || {};
  if (Array.isArray(C.matrix) && Array.isArray(C.symbols) && C.symbols.length) {
    setHtml('corr-sub', `${FA.term('correlation', 'Correlation')} of daily returns over the window: +1 means two holdings move in lockstep, −1 opposite, 0 unrelated. Blue is negative, red positive.`);
    F.heatmap(g('corr'), {rows: C.symbols, cols: C.symbols, values: C.matrix, diverging: true, min: -1, max: 1, fmt: v => n2(v)});
  } else if (Array.isArray(C.pairs) && C.pairs.length) {
    setHtml('corr-sub', `Strongest pairs (too many symbols for the full matrix): +1 means two holdings move in lockstep, −1 opposite.`);
    setHtml('corr', '<div class="twrap"><table><thead><tr><th class="l">Pair</th><th>' + FA.term('correlation', 'Correlation') + '</th></tr></thead><tbody>' + C.pairs.map(p => `<tr><td class="l">${F.esc(p.a)} × ${F.esc(p.b)}</td><td>${n2(p.correlation)}</td></tr>`).join('') + '</tbody></table></div>');
  } else g('corr').innerHTML = '<span class="muted">not enough shared history</span>';
  const K = D.concentration || {};
  setHtml('conc', `${FA.term('concentration', 'Concentration')}: ${FA.term('hhi', 'HHI')} ${F.num(K.hhi, 4)} (${F.esc(K.hhi_interpretation || '—')}) · largest position ${pct1(K.largest_position)} · top-5 ${pct1(K.top_5_concentration)} · ${F.esc(K.position_count ?? '—')} positions`);
  // positions table
  const cols = [
    {key: 'symbol', label: 'Symbol', left: true, fmt: v => `<span style="border-left:3px solid ${color(v)};padding-left:6px"><b>${F.esc(v)}</b></span>`},
    {key: 'weight', label: 'Weight', fmt: pct1},
    {key: 'volatility', label: 'Volatility', fmt: pct1},
    {key: 'beta', label: 'Beta', fmt: n2},
    {key: 'max_drawdown', label: 'Max drawdown', fmt: negPct, cls: v => F.isNum(v) ? 'neg' : ''},
    {key: 'var_95', label: 'VaR 95%', fmt: negPct},
    {key: 'tracking_error', label: 'Tracking error', fmt: (v, r) => F.isNum(v) ? `${pct1(v)}${r.tracking_benchmark ? ` <span class="muted">vs ${F.esc(r.tracking_benchmark)}</span>` : ''}` : '—'},
    {key: 'sharpe', label: 'Sharpe', fmt: n2},
  ];
  const tbl = F.table(g('positions'), cols, pos, {sortKey: 'weight', onDraw: vis => { g('count').textContent = `${vis.length} of ${pos.length}`; }});
  termHeads(g('positions'), {volatility: FA.term('volatility', 'Volatility'), beta: FA.term('beta', 'Beta'), max_drawdown: FA.term('max drawdown', 'Max drawdown'), var_95: FA.term('var', 'VaR 95%'), tracking_error: FA.term('tracking error', 'Tracking error'), sharpe: FA.term('sharpe ratio', 'Sharpe')});
  g('q').addEventListener('input', e => tbl.setQuery(e.target.value));
  // scenarios: loss bars, table, per-scenario detail
  const sc = D.scenarios || [];
  const modeLabel = m => m === 'replay' ? 'replay' : m === 'beta_scaled' ? 'beta-scaled' : m === 'mixed' ? 'replay + beta-scaled' : (m || '—');
  const scRoot = g('scen-bars');
  if (!sc.length) scRoot.innerHTML = '<span class="muted">no scenarios</span>';
  else {
    F.bars(scRoot, sc.map(s => ({label: s.name, share: s.mode === 'skipped' ? 0 : s.portfolio_return, color: F.isNum(s.portfolio_return) && s.portfolio_return > 0 ? 'var(--up)' : 'var(--down)',
      text: s.mode === 'skipped' ? 'skipped' : `${F.moneyS(s.portfolio_loss)} · ${F.pct(s.portfolio_return, 1, true)}`,
      tip: `<b>${F.esc(s.name)}</b> ${F.esc(modeLabel(s.mode))}<br>${F.esc(s.start || '')} → ${F.esc(s.end || '')}<br>benchmark ${F.pct(s.benchmark_return, 1, true)} · portfolio ${F.pct(s.portfolio_return, 1, true)}`})));
    setHtml('scenarios', '<table><thead><tr><th class="l">Scenario</th><th class="l">Window</th><th class="l">Mode</th><th>' + FA.term('benchmark', 'Benchmark') + '</th><th>Portfolio</th><th>Loss</th></tr></thead><tbody>' + sc.map((s, i) => `<tr data-i="${i}" style="cursor:pointer"><td class="l">${F.esc(s.name)}</td><td class="l">${F.esc(s.start || '—')} → ${F.esc(s.end || '—')}</td><td class="l">${F.esc(modeLabel(s.mode))}</td><td class="${F.cls(s.benchmark_return)}">${F.pct(s.benchmark_return, 1, true)}</td><td class="${F.cls(s.portfolio_return)}">${F.pct(s.portfolio_return, 1, true)}</td><td class="${F.cls(s.portfolio_loss)}">${F.moneyS(s.portfolio_loss)}</td></tr>`).join('') + '</tbody></table>');
    const top3 = new Set(rc.slice(0, 3).map(r => r.symbol));
    const weightOf = {}; pos.forEach(p => { weightOf[p.symbol] = p.weight; });
    const showScenario = i => {
      const s = sc[i]; const scaled = new Set(s.beta_scaled || []); const rows = Object.entries(s.positions || {}).map(([sym, r]) => ({symbol: sym, weight: weightOf[sym], ret: r, scaled: scaled.has(sym)})).sort((a, b) => (a.ret ?? 0) - (b.ret ?? 0));
      let h = `<h2 style="margin-top:4px">${F.esc(s.name)} <span class="muted" style="font-weight:400">· ${F.esc(modeLabel(s.mode))} · portfolio ${F.pct(s.portfolio_return, 1, true)} (${F.moneyS(s.portfolio_loss)})</span></h2>`;
      if (s.note) h += `<p class="note" style="margin-top:0">${F.esc(s.note)}</p>`;
      h += rows.length ? '<div class="twrap"><table><thead><tr><th class="l">Symbol</th><th>Weight</th><th>Return in scenario</th><th class="l">How</th></tr></thead><tbody>' + rows.map(r => `<tr><td class="l"><span style="border-left:3px solid ${color(r.symbol)};padding-left:6px">${top3.has(r.symbol) ? '<b>' + F.esc(r.symbol) + '</b> <span class="muted">top-3 ' + FA.term('risk contribution', 'risk contributor') + '</span>' : F.esc(r.symbol)}</span></td><td>${pct1(r.weight)}</td><td class="${F.cls(r.ret)}">${F.pct(r.ret, 1, true)}</td><td class="l muted">${r.scaled ? 'beta-scaled' : (s.mode === 'beta_scaled' ? 'beta-scaled' : 'replayed')}</td></tr>`).join('') + '</tbody></table></div>' : '<span class="muted">no per-position returns</span>';
      setHtml('scen-detail', h);
      scRoot.querySelectorAll('.bar').forEach((b, j) => { b.style.background = j === i ? 'color-mix(in srgb, var(--s1) 8%, transparent)' : ''; });
    };
    scRoot.querySelectorAll('.bar').forEach((b, i) => { b.style.cursor = 'pointer'; b.addEventListener('click', () => showScenario(i)); });
    g('scenarios').querySelectorAll('tr[data-i]').forEach(tr => tr.addEventListener('click', () => showScenario(+tr.dataset.i)));
    let worst = 0; sc.forEach((s, i) => { if (F.isNum(s.portfolio_loss) && s.portfolio_loss < (sc[worst].portfolio_loss ?? 0)) worst = i; });
    showScenario(worst);
  }
  // what-if shocks
  const W = D.what_if;
  if (W && W.shocks) { g('whatif-card').hidden = false;
    g('whatif-line').textContent = `If each position below moved by its shock: portfolio ${F.pct(W.portfolio_return, 1, true)} · ${F.moneyS(W.portfolio_loss)}`;
    const L = W.positions || {};
    g('whatif').innerHTML = '<table><thead><tr><th class="l">Symbol</th><th>Shock</th><th>Loss</th></tr></thead><tbody>' + Object.entries(W.shocks).map(([sym, r]) => `<tr><td class="l">${F.esc(sym)}</td><td class="${F.cls(r)}">${F.pct(r, 1, true)}</td><td class="${F.cls(L[sym])}">${F.moneyS(L[sym])}</td></tr>`).join('') + '</tbody></table>'; }
  // factors (additive)
  if (D.factors && Object.keys(D.factors).length) { g('factors-card').hidden = false;
    setHtml('factors', '<table><thead><tr><th class="l">' + FA.term('factor', 'Factor') + '</th><th>' + FA.term('beta', 'Beta') + '</th><th>' + FA.term('explained variance', 'Explained variance') + '</th></tr></thead><tbody>' + Object.entries(D.factors).map(([k, f]) => `<tr><td class="l"><b>${F.esc(k)}</b>${FACTOR_NAMES[k] ? ` <span class="muted">${F.esc(FACTOR_NAMES[k])}</span>` : ''}</td><td>${n2(f.beta)}</td><td>${pct1(f.explained_variance)}</td></tr>`).join('') + '</tbody></table>');
    setHtml('factors-note', `Sum of single-factor ${FA.term('explained variance', 'R²')} ${pct1(D.factors_total_explained_variance)} — each style is measured on its own, so the sum can exceed 100% when styles overlap.`); }
  // liquidity (additive)
  if (Array.isArray(D.liquidity) && D.liquidity.length) { g('liq-card').hidden = false;
    setHtml('liquidity', '<table><thead><tr><th class="l">Symbol</th><th>Position</th><th>' + FA.term('adv', 'Avg daily $ volume') + '</th><th>' + FA.term('adv', '% of ADV') + '</th></tr></thead><tbody>' + D.liquidity.map(l => `<tr><td class="l">${F.esc(l.symbol)}</td><td>${money0(l.position_value)}</td><td>${money0(l.avg_dollar_volume)}</td><td>${F.isNum(l.pct_of_adv) ? F.pct(l.pct_of_adv, 2) : '—'}</td></tr>`).join('') + '</tbody></table>'); }
  // card help
  const card = id => g(id).parentElement;
  const loss0 = v => (F.isNum(v) && v < 0 ? '−' : '+') + F.money(Math.abs(v || 0), 0);
  const top = rc[0];
  F.help(card('contrib-h'), {lead: 'Which holdings drive the portfolio’s ups and downs, which is not always the same as which are biggest.',
    sections: top ? [{title: `${top.symbol}: weight against risk`, html: '<div data-bars></div><p>A holding that swings a lot, or moves with everything else, causes more of the risk than its weight; a steady bond fund causes less.</p>',
      render: el => { F.bars(el.querySelector('[data-bars]'), [{label: 'share of value', share: top.weight, color: 'var(--s2)', text: pct1(top.weight)}, {label: 'share of the swings', share: top.share, color: 'var(--s1)', text: pct1(top.share)}]); }}] : []});
  let pair = null;
  if (Array.isArray(C.matrix) && Array.isArray(C.symbols)) C.symbols.forEach((a, i) => C.symbols.forEach((b, j) => { if (j > i && F.isNum(C.matrix[i][j]) && (!pair || C.matrix[i][j] > pair.v)) pair = {a, b, v: C.matrix[i][j]}; }));
  else if (Array.isArray(C.pairs) && C.pairs.length) pair = {a: C.pairs[0].a, b: C.pairs[0].b, v: C.pairs[0].correlation};
  F.help(card('corr-h'), {lead: 'How closely each pair of holdings moves together, from −1 (opposite) to +1 (in lockstep).',
    sections: [{title: 'Reading a number', html: `<p><b>Near +1</b>: the two rise and fall together, so holding both adds little protection.</p><p><b>Near 0</b>: they move independently.</p><p><b>Below 0</b>: one tends to rise when the other falls.</p>` +
      (pair ? `<p>The closest pair here is ${F.esc(pair.a)} and ${F.esc(pair.b)} at ${n2(pair.v)}.</p>` : '')},
      {title: 'The concentration line', html: '<p>HHI adds up the square of every holding’s weight: near 0 means many small holdings, 1 means a single one.</p>'}]});
  const bigDD = pos.filter(p => F.isNum(p.max_drawdown)).sort((a, b) => b.max_drawdown - a.max_drawdown)[0];
  F.help(g('positions-card'), {lead: 'Each holding’s own risk figures over the same stretch of history.',
    sections: [{title: 'What the main columns say', html: `<p><b>Volatility</b>: how much the price usually swings in a year. <b>Beta</b>: how much it moves when the benchmark moves 1%. <b>Max drawdown</b>: the deepest fall from a peak.` +
      (bigDD ? ` The deepest here is ${F.esc(bigDD.symbol)}, ${pct1(bigDD.max_drawdown)} from its high.` : '') + ` <b>VaR 95%</b>: a daily loss worse than this happened on about 1 day in 20.</p>`}]});
  const worstS = sc.filter(s => F.isNum(s.portfolio_loss)).sort((a, b) => a.portfolio_loss - b.portfolio_loss)[0];
  F.help(card('scen-h'), {lead: 'What past market crashes would do to the holdings you have today.',
    sections: worstS ? [{title: `The worst one here: ${worstS.name}`, html: F.flow([{label: 'value today', value: F.money(P.total_value, 0)}, {op: '+', label: `${worstS.name}`, value: loss0(worstS.portfolio_loss)}, {op: '=', label: 'value after', value: F.money((P.total_value || 0) + worstS.portfolio_loss, 0)}]) +
      '<p>Replay uses each holding’s actual prices from that period. When a holding is too young to have them, its beta times the benchmark’s fall stands in (beta-scaled).</p>'}] : []});
  if (W && W.shocks) F.help(g('whatif-card'), {lead: 'The hit to the portfolio from the moves you described, holding everything else still.',
    sections: [{title: 'How it adds up', html: F.flow([{label: 'value today', value: F.money(P.total_value, 0)}, {op: '+', label: 'loss from the shocks', value: loss0(W.portfolio_loss)}, {op: '=', label: 'value after', value: F.money((P.total_value || 0) + (W.portfolio_loss || 0), 0)}])}]});
  if (D.factors && Object.keys(D.factors).length) F.help(card('factors-h'), {lead: 'How much the portfolio moves with broad market styles such as small companies, momentum, value and credit.',
    sections: [{title: 'Reading a row', html: '<p>A beta of 0.5 means the portfolio moved about half as much as that style did. Explained variance is how much of the portfolio’s movement that style alone accounts for.</p>'}]});
  if (Array.isArray(D.liquidity) && D.liquidity.length) { const lq = [...D.liquidity].sort((a, b) => (b.pct_of_adv || 0) - (a.pct_of_adv || 0))[0];
    F.help(card('liq-h'), {lead: 'How quickly each position could be sold without moving the price.',
      sections: [{title: 'Reading a row', html: `<p>The last column is the position as a share of the dollar value that trades on a typical day. A few percent sells within a day; a large share takes days and can push the price down.</p>` + (lq && F.isNum(lq.pct_of_adv) ? `<p>The largest here is ${F.esc(lq.symbol)} at ${F.pct(lq.pct_of_adv, 2)} of a day’s trading.</p>` : '')}]}); }
  // flags
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _pct(v: object) -> str:
    return f"{100 * v:.1f}%" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _num2(v: object) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _headline(result: dict) -> str:
    """Static one-line summary so the page reads without JavaScript."""
    p = result.get("portfolio") or {}
    total = p.get("total_value")
    total_s = f"${total:,.0f}" if isinstance(total, (int, float)) else "—"
    parts = [
        f"{total_s} · cash {_pct(p.get('cash_weight'))}",
        f"{p.get('observations', '—')} trading days {p.get('start') or '—'} to {p.get('end') or '—'}",
        f"benchmark {p.get('benchmark') or (result.get('sources') or {}).get('benchmark') or '—'}",
        f"coverage {_pct(p.get('coverage'))}",
        f"volatility {_pct(p.get('volatility'))} · beta {_num2(p.get('beta'))} · max drawdown {_pct(p.get('max_drawdown'))} · 1-day VaR 95% {_pct(p.get('var_95'))}",
    ]
    if result.get("as_of"):
        parts.append(f"as of {result['as_of']}")
    return " · ".join(parts)


def build(result: dict) -> str:
    if not isinstance(result, dict) or "portfolio" not in result or "scenarios" not in result:
        raise InvalidInput("input must be a stress.py or risk.py result (a JSON object with portfolio and scenarios)")
    body = BODY.replace("{{HEADLINE}}", html.escape(_headline(result)))
    return page.render(TITLE, result, body, SCRIPT)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            result = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read risk JSON: {exc}") from exc
        out = page.write(ns.out, build(result))
        return {"out": str(out), "title": TITLE, "positions": len(result.get("positions") or []), "scenarios": len(result.get("scenarios") or []), "flags": len(result.get("flags") or [])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
