#!/usr/bin/env python3
"""Usage: render.py [--in signals.json] [--prices history.json] --out page.html

Turns one ``signals.py`` result (a file, or stdin when ``--in`` is omitted) plus, optionally, the
``history.py`` output it was computed from (``--prices``) into a self-contained interactive HTML page
for the Artifact tool: stat tiles for the indicators as the script names them (last close, 12-1
momentum, annualized volatility, drawdowns, 52-week range, ATR, relative volume), a price line chart
with the moving-average series the script computes (``series.sma_50`` / ``series.sma_200``, present
when signals.py ran with ``"series": true``) on the same axis and the most recent swing pivots
(``pivots``) as horizontal support/resistance reference lines, a separate volume bar chart below it,
the trailing-window returns and the benchmark-relative block as bars, a signals table with every field
and its definition, the pivot list, and a closing note that this is timing analysis, not a
recommendation. Prints ``{"out": path, "title": ..., "symbol": ..., "observations": n}``. Exit 2 on
a missing or malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the two JSON files; the page formats and draws, it never recomputes an indicator.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Trading Signals"

BODY = """
<h1 id="title">Trading Signals</h1>
<p class="sub" id="asof">Price action and momentum statistics for one security.</p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<section class="card"><h2 id="chart-h">Price</h2><p class="sub" id="chart-sub"></p><div id="price"></div>
  <div id="volume" style="margin-top:10px"></div><p class="note" id="chart-note"></p></section>
<div class="grid2">
  <div class="card"><h2 id="h-ret">Trailing returns</h2><p class="sub">How much the price changed over the last week, month, quarter, half-year and year. Simple returns over trading-day windows: 1w = 5, 1m = 21, 3m = 63, 6m = 126, 12m = 252.</p><div id="returns"></div></div>
  <div class="card" id="rel-card"><h2 id="h-rel">Relative to benchmark</h2><p class="sub" id="rel-sub">Did this stock beat the market? Position return minus benchmark return over the same window, on the date-aligned series.</p><div id="relative"></div></div>
</div>
<section class="card"><h2 id="h-sig">Signals</h2><p class="sub">Every statistic the script computed, with the formula behind it; the same numbers as the tiles above, in one place.</p><div class="twrap" id="signals"></div></section>
<section class="card" id="pivots-card" hidden><h2 id="h-piv">Swing pivots</h2><p class="sub" id="pivots-sub"></p><div class="grid2"><div class="twrap" id="pivot-highs"></div><div class="twrap" id="pivot-lows"></div></div></section>
<p class="note">Timing analysis of historical daily closes, not a recommendation to buy, sell, or hold. The horizon matters: 3-12 month relative strength is a documented continuation pattern, while a single bad week is mostly microstructure noise, and round-trip costs dominate short-horizon effects at retail scale. All figures are trailing statistics from a specific sample; regimes change, and none of this predicts future behaviour. Yahoo data is delayed. General information, not financial advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, S = D.signals || {}, H = D.history || null, F = FA;
  const g = id => document.getElementById(id);
  const sym = (H && H.symbol) || D.symbol || '';
  const rows = ((H && H.prices) || []).filter(r => r && r.date && F.isNum(r.close)).slice().sort((a, b) => a.date < b.date ? -1 : 1);
  const ts = d => +new Date(d + 'T00:00:00');
  const dayFmt = x => new Date(x).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
  const pctS = v => F.pct(v, 1, true);
  // terms this page needs that the shared glossary lacks (page.py is frozen; add them here)
  Object.assign(FA.glossary, {
    "sma": ["Simple moving average: the plain average of the last N closing prices, redrawn each day; price above it is read as an uptrend.", "https://www.investopedia.com/terms/s/sma.asp"],
    "closing price": ["The last price of the trading day; every statistic on this page is built from daily closes.", "https://www.investopedia.com/terms/c/closingprice.asp"],
    "benchmark": ["A reference investment, usually a broad index fund, that the stock's return is compared with over the same dates.", "https://www.investopedia.com/terms/b/benchmark.asp"],
    "swing pivot": ["A local turning point in price: a swing high is a close above its neighbours on both sides, a swing low is one below; recent ones often act as support or resistance.", "https://www.investopedia.com/terms/s/swinghigh.asp"],
    "swing high": ["A close higher than the closes on both sides of it; a recent rally's peak, often watched as resistance.", "https://www.investopedia.com/terms/s/swinghigh.asp"],
    "swing low": ["A close lower than the closes on both sides of it; a recent dip's bottom, often watched as support.", "https://www.investopedia.com/terms/s/swinglow.asp"],
    "gap": ["A day that opens above (gap up) or below (gap down) the previous close, leaving a hole on the chart.", "https://www.investopedia.com/terms/g/gap.asp"],
    "relative strength": ["How a stock's return compares with a benchmark's over the same period; 3-12 month leaders have tended to keep leading.", "https://www.investopedia.com/terms/r/relativestrength.asp"],
  });
  const T = (k, label) => FA.term(k, label);
  // FA.bars escapes its labels, so glossary marks go into the finished bar labels afterwards
  const termBars = (root, labels) => { root.querySelectorAll('.bar > .l').forEach((s, i) => { if (labels[i]) s.innerHTML = labels[i]; }); FA.armTerms(root); };
  g('title').textContent = sym ? `${sym} — Trading Signals` : 'Trading Signals';
  g('asof').textContent = `As of ${S.as_of || '—'} · ${S.observations ?? '—'} daily closes` + (H && H.period ? ` · ${H.period}` : '') + (S.relative ? ' · benchmark-relative block present' : '');
  FA.explain(g('explain'), `<p>This page describes how ${sym ? `<b>${F.esc(sym)}</b>` : 'one stock'} has been trading, for timing questions rather than "what is it worth": where the price sits against its ${T('moving average', 'moving averages')}, its recent trend (${T('momentum')}), how bumpy it has been (${T('volatility')}), and how far it is from its recent high (${T('drawdown')}).</p>
<p>Every figure is computed from daily ${T('closing price', 'closing prices')} from Yahoo Finance over the period shown; nothing is predicted or fetched live.</p>
<p>The chart draws the closing price with the 50- and 200-day ${T('sma', 'SMA')} lines; dashed lines mark recent ${T('swing high', 'swing highs')} and ${T('swing low', 'swing lows')}, prices where past rises stalled or falls stopped (${T('support and resistance')}). The bars below it are daily trading volume.</p>
<p>The one caveat that matters most: these are trailing statistics from one sample. A strong 12-month trend is a documented tendency, a bad week is mostly noise, and none of it is a recommendation to buy, sell or hold.</p>`);
  g('h-rel').innerHTML = `Relative to ${T('benchmark')}`;
  g('rel-sub').innerHTML = `Did this stock beat the market? Position return minus ${T('benchmark')} return over the same window, on the date-aligned series (${T('relative strength')}).`;
  g('h-piv').innerHTML = T('swing pivot', 'Swing pivots');
  // tiles
  const RT = S.returns || {}, GS = S.gap_stats;
  const tiles = [
    [T('closing price', 'Last close'), F.money(S.last_close), `12m ${pctS(RT['12m'])} · 1m ${pctS(RT['1m'])}`],
    [T('momentum', 'Momentum 12-1'), `<span class="${F.cls(S.momentum_12_1)}">${pctS(S.momentum_12_1)}</span>`, '12-month return skipping the latest month'],
    [T('volatility', 'Annualized volatility'), F.pct(S.annualized_volatility), 'daily returns, trailing 252 days'],
    [T('drawdown', 'Current drawdown'), `<span class="${F.cls(S.current_drawdown)}">${F.pct(S.current_drawdown)}</span>`, `${T('max drawdown')} ${F.pct(S.max_drawdown)} over the series`],
    [T('52-week high', 'From 52-week high'), `<span class="${F.cls(S.pct_from_52w_high)}">${pctS(S.pct_from_52w_high)}</span>`, `high ${F.money(S.high_52w)} · low ${F.money(S.low_52w)} (${pctS(S.pct_from_52w_low)} above)`],
    [`vs ${T('sma', 'SMA')} 50 / 200`, `<span class="${F.cls(S.price_vs_sma_50)}">${pctS(S.price_vs_sma_50)}</span> <span class="muted">/</span> <span class="${F.cls(S.price_vs_sma_200)}">${pctS(S.price_vs_sma_200)}</span>`, `SMA 50 ${F.money(S.sma_50)} · SMA 200 ${F.money(S.sma_200)}`],
  ];
  if ('atr_14_pct' in S) tiles.push([T('atr', 'ATR 14'), F.pct(S.atr_14_pct, 2), GS ? `${T('gap', 'gaps')} up ${GS.up_gap_count} · down ${GS.down_gap_count} (${F.pct(GS.up_gap_frequency)} of days gap up)` : 'of last close']);
  if ('relative_volume_20_252' in S) tiles.push([T('relative volume', 'Relative volume 20/252'), F.isNum(S.relative_volume_20_252) ? F.num(S.relative_volume_20_252) + '×' : '—', `${T('liquidity', 'avg $ volume')} 20d ${F.money(S.avg_dollar_volume_20, 0)}`]);
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  FA.armTerms(g('tiles'));
  // price chart: closes + moving-average series on one axis, pivot levels as dashed reference lines
  const SER = S.series || {};
  const series = [{name: 'Close', points: rows.map(r => [ts(r.date), r.close]), color: F.S[0]}];
  for (const [key, label, color] of [['sma_50', 'SMA 50', F.S[1]], ['sma_200', 'SMA 200', F.S[2]]]) {
    const pts = (SER[key] || []).filter(p => p && p.date && F.isNum(p.value)).map(p => [ts(p.date), p.value]);
    if (pts.length) series.push({name: label, points: pts, color});
  }
  const PV = S.pivots || null, NLEV = 3;
  const levels = PV ? [...(PV.highs || []).slice(0, NLEV).map(p => ({...p, kind: 'H', color: F.S[3]})), ...(PV.lows || []).slice(0, NLEV).map(p => ({...p, kind: 'L', color: F.S[4]}))].filter(p => F.isNum(p.close)) : [];
  g('chart-h').textContent = sym ? `${sym} price` : 'Price';
  if (!rows.length) {
    g('price').innerHTML = '<span class="muted">no price history supplied (render.py --prices history.json draws the chart)</span>';
    g('chart-sub').textContent = '';
  } else {
    g('chart-sub').textContent = `${dayFmt(ts(rows[0].date))} to ${dayFmt(ts(rows[rows.length - 1].date))}, ${rows.length} closes` + (series.length > 1 ? '; moving averages from signals.py' : '') + (levels.length ? `; dashed lines are the ${NLEV} most recent swing highs (H) and lows (L), k = ${PV.k}` : '') + '.';
    const W = 960, Hh = 300, m = {t: 14, r: 150, b: 30, l: 62}, iw = W - m.l - m.r, ih = Hh - m.t - m.b;
    const xs = rows.map(r => ts(r.date)); const x0 = xs[0], x1 = xs[xs.length - 1] === x0 ? x0 + 1 : xs[xs.length - 1];
    const ys = series.flatMap(s => s.points.map(p => p[1])).concat(levels.map(l => l.close));
    let y0 = Math.min(...ys), y1 = Math.max(...ys); if (y1 === y0) y1 = y0 + 1; const pad = (y1 - y0) * 0.05; y0 -= pad; y1 += pad;
    const X = x => m.l + iw * (x - x0) / (x1 - x0), Y = y => m.t + ih * (1 - (y - y0) / (y1 - y0));
    const yt = []; for (let k = 0; k <= 4; k++) yt.push(y0 + (y1 - y0) * k / 4);
    const xt = []; for (let k = 0; k <= 5; k++) xt.push(x0 + (x1 - x0) * k / 5);
    let s = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="${F.esc(sym)} closes with moving averages">`;
    s += yt.map(t => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="var(--grid)"/><text x="${m.l - 8}" y="${(Y(t) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${F.esc(F.money(t, 0))}</text>`).join('');
    s += xt.map(t => `<text x="${X(t).toFixed(1)}" y="${Hh - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${F.esc(new Date(t).toLocaleDateString('en-US', {month: 'short', year: '2-digit'}))}</text>`).join('');
    // reference levels (dashed) and the series paths
    levels.forEach(l => { const y = Y(l.close).toFixed(1); s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" stroke="${l.color}" stroke-dasharray="5 4" opacity=".8"/>`; });
    series.forEach(sr => { const d = sr.points.map((p, j) => (j ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('');
      s += `<path d="${d}" fill="none" stroke="${sr.color}" stroke-width="${sr.name === 'Close' ? 1.8 : 1.4}" stroke-linejoin="round"/>`; });
    // direct labels on the right: series names at their last value, level labels at their price, pushed apart so none overlap
    const labels = series.map(sr => ({text: sr.name, color: sr.color, y: Y(sr.points[sr.points.length - 1][1]), bold: true}))
      .concat(levels.map(l => ({text: `${l.kind} ${F.money(l.close)} · ${l.date}`, color: l.color, y: Y(l.close), bold: false}))).sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 12) labels[i].y = labels[i - 1].y + 12;
    const over = labels.length ? labels[labels.length - 1].y - (m.t + ih) : 0; if (over > 0) labels.forEach(l => { l.y -= over; });
    s += labels.map(l => `<text x="${W - m.r + 8}" y="${(l.y + 4).toFixed(1)}" font-size="${l.bold ? 11.5 : 10.5}" font-weight="${l.bold ? 600 : 400}" fill="${l.color}">${F.esc(l.text)}</text>`).join('');
    s += `<line id="cx" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="var(--muted)" stroke-dasharray="3 3" opacity="0"/><rect id="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
    g('price').innerHTML = s;
    const lg = F.el('div', {class: 'legend'}); series.forEach(sr => lg.appendChild(F.el('span', {}, `<i style="background:${sr.color}"></i>${sr.name === 'Close' ? T('closing price', 'Close') : sr.name.replace('SMA', T('sma', 'SMA'))}`)));
    if (levels.length) { lg.appendChild(F.el('span', {}, `<i style="background:${F.S[3]}"></i>${T('swing high')}`)); lg.appendChild(F.el('span', {}, `<i style="background:${F.S[4]}"></i>${T('swing low')}`)); }
    g('price').appendChild(lg); FA.armTerms(lg);
    const svg = g('price').querySelector('svg'), hit = svg.querySelector('#hit'), cx = svg.querySelector('#cx');
    const nearest = (pts, xv) => { let best = null; for (const p of pts) if (best === null || Math.abs(p[0] - xv) < Math.abs(best[0] - xv)) best = p; return best; };
    hit.addEventListener('mousemove', ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) * W / r.width; const xv = x0 + (px - m.l) / iw * (x1 - x0);
      cx.setAttribute('x1', px); cx.setAttribute('x2', px); cx.setAttribute('opacity', 1);
      const c = nearest(series[0].points, xv); const row = rows.find(rr => ts(rr.date) === c[0]) || {};
      const lines = series.map(sr => { const p = nearest(sr.points, xv); return p && Math.abs(p[0] - c[0]) < 864e5 * 4 ? `<div class="r"><span><i style="background:${sr.color};width:8px;height:8px;display:inline-block;border-radius:2px;margin-right:5px"></i>${F.esc(sr.name)}</span><b>${F.esc(F.money(p[1]))}</b></div>` : ''; }).join('');
      const ohl = F.isNum(row.high) && F.isNum(row.low) ? `<div class="r"><span>High / low</span><b>${F.esc(F.money(row.high))} / ${F.esc(F.money(row.low))}</b></div>` : '';
      const vol = F.isNum(row.volume) ? `<div class="r"><span>Volume</span><b>${F.esc(F.num(row.volume, 0))}</b></div>` : '';
      F.tip.show(ev, `<div style="color:var(--ink2);margin-bottom:3px">${F.esc(dayFmt(c[0]))}</div>${lines}${ohl}${vol}`); });
    hit.addEventListener('mouseleave', () => { cx.setAttribute('opacity', 0); F.tip.hide(); });
    // volume: its own small chart on the same x scale, never a second axis on the price chart
    const vrows = rows.filter(r => F.isNum(r.volume));
    if (vrows.length) {
      const Hv = 90, mv = {t: 6, r: m.r, b: 4, l: m.l}, ihv = Hv - mv.t - mv.b, vmax = Math.max(...vrows.map(r => r.volume), 1e-9);
      const bw = Math.max(1, iw / rows.length * 0.8);
      let v = `<svg viewBox="0 0 ${W} ${Hv}" role="img" aria-label="daily volume">`;
      v += `<line x1="${mv.l}" x2="${W - mv.r}" y1="${mv.t + ihv}" y2="${mv.t + ihv}" stroke="var(--grid)"/>`;
      v += `<text x="${mv.l - 8}" y="${mv.t + 10}" text-anchor="end" font-size="11" fill="var(--muted)">${F.esc(vmax >= 1e6 ? (vmax / 1e6).toFixed(1) + 'M' : F.num(vmax, 0))}</text>`;
      v += `<text x="${W - mv.r + 8}" y="${mv.t + ihv - 2}" font-size="11.5" font-weight="600" fill="var(--ink)">Volume</text>`;
      v += vrows.map((r, i) => { const h = ihv * r.volume / vmax; return `<rect data-i="${i}" x="${(X(ts(r.date)) - bw / 2).toFixed(1)}" y="${(mv.t + ihv - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${F.S[0]}" opacity=".55"/>`; }).join('');
      v += '</svg>';
      g('volume').innerHTML = v;
      g('volume').querySelectorAll('rect[data-i]').forEach(rc => { const r = vrows[+rc.dataset.i]; F.bindTip(rc, `<b>${F.esc(dayFmt(ts(r.date)))}</b><br>volume ${F.esc(F.num(r.volume, 0))} · close ${F.esc(F.money(r.close))}`); });
    }
    g('chart-note').textContent = (series.length > 1 ? '' : 'Moving-average lines need signals.py run with "series": true. ') + (PV ? '' : 'Swing pivots need signals.py run with "pivots": k. ') + 'Daily closes from Yahoo Finance; the last bar is the most recent completed session.';
  }
  // returns and relative bars: gains and losses, so the up/down colours apply
  const rbars = (root, obj, order) => { const rr = order.filter(k => k in obj);
    if (!rr.length) { root.innerHTML = '<span class="muted">not available</span>'; return; }
    F.bars(root, rr.map(k => ({label: k.replace('momentum_12_1', 'momentum 12-1').replace('relative_12_1', 'ratio 12-1'), share: obj[k], color: F.isNum(obj[k]) && obj[k] < 0 ? 'var(--down)' : 'var(--up)', text: pctS(obj[k])})));
    termBars(root, rr.map(k => k === 'momentum_12_1' ? T('momentum', 'momentum 12-1') : k === 'relative_12_1' ? T('relative strength', 'ratio 12-1') : null)); };
  rbars(g('returns'), RT, ['1w', '1m', '3m', '6m', '12m']);
  if (S.relative) rbars(g('relative'), S.relative, ['1m', '3m', '12m', 'momentum_12_1', 'relative_12_1']); else g('rel-card').hidden = true;
  // signals table: every field as the script names it
  const defs = [
    ['as_of', 'date of the last close', v => F.esc(v)], ['last_close', 'last close', F.money], ['observations', 'closes used', v => F.num(v, 0)],
    ['returns.1w', 'close[t] / close[t-5] - 1', pctS], ['returns.1m', 'close[t] / close[t-21] - 1', pctS], ['returns.3m', 'close[t] / close[t-63] - 1', pctS], ['returns.6m', 'close[t] / close[t-126] - 1', pctS], ['returns.12m', 'close[t] / close[t-252] - 1', pctS],
    ['momentum_12_1', 'close[t-21] / close[t-252] - 1 (Jegadeesh-Titman formation signal)', pctS],
    ['annualized_volatility', 'sample stdev of daily returns over trailing 252 days × √252', v => F.pct(v)],
    ['max_drawdown', 'largest peak-to-trough decline over the full series', v => F.pct(v)], ['current_drawdown', 'last close vs the full-series high', v => F.pct(v)],
    ['sma_50', 'mean of the last 50 closes', F.money], ['sma_200', 'mean of the last 200 closes', F.money],
    ['price_vs_sma_50', 'last / sma_50 - 1', pctS], ['price_vs_sma_200', 'last / sma_200 - 1', pctS],
    ['high_52w', 'highest close, trailing 252', F.money], ['low_52w', 'lowest close, trailing 252', F.money],
    ['pct_from_52w_high', 'last / high_52w - 1', pctS], ['pct_from_52w_low', 'last / low_52w - 1', pctS],
    ['atr_14_pct', "Wilder's 14-period average true range as a share of the last close", v => F.pct(v, 2)],
    ['gap_stats.up_gap_frequency', 'share of sessions opening above the prior close', v => F.pct(v)], ['gap_stats.up_gap_count', 'gap-up sessions', v => F.num(v, 0)], ['gap_stats.down_gap_count', 'gap-down sessions', v => F.num(v, 0)],
    ['relative_volume_20_252', 'mean volume last 20 / mean volume trailing 252', v => F.isNum(v) ? F.num(v) + '×' : '—'], ['avg_dollar_volume_20', 'mean of close × volume over the last 20 sessions', v => F.money(v, 0)],
    ['relative.1m', 'position 1m return minus benchmark', pctS], ['relative.3m', 'position 3m return minus benchmark', pctS], ['relative.12m', 'position 12m return minus benchmark', pctS],
    ['relative.momentum_12_1', 'position momentum_12_1 minus benchmark', pctS], ['relative.relative_12_1', 'momentum_12_1 of the position/benchmark ratio', pctS],
  ];
  const get = k => k.split('.').reduce((o, p) => (o && typeof o === 'object') ? o[p] : undefined, S);
  const present = defs.filter(([k]) => { const parts = k.split('.'); const parent = parts.length > 1 ? get(parts[0]) : S; return parent && typeof parent === 'object' && parts[parts.length - 1] in parent; });
  g('signals').innerHTML = '<table><thead><tr><th class="l">Field</th><th>Value</th><th class="l">Definition</th></tr></thead><tbody>' +
    present.map(([k, d, f]) => `<tr><td class="l"><code>${F.esc(k)}</code></td><td>${f(get(k))}</td><td class="l" style="white-space:normal;color:var(--ink2)">${F.esc(d)}</td></tr>`).join('') + '</tbody></table>';
  // pivots
  if (PV) { g('pivots-card').hidden = false;
    g('pivots-sub').innerHTML = `Recent turning points in the price, the levels traders watch as ${T('support and resistance')}. Close-based ${PV.k}-bar swing pivots: a pivot high is a close strictly above the ${PV.k} closes on each side (a low: strictly below); the most recent 10 of each, latest first.`;
    const tb = (title, list) => `<table><thead><tr><th class="l">${title}</th><th>${T('closing price', 'Close')}</th></tr></thead><tbody>` + ((list || []).length ? list.map(p => `<tr><td class="l">${F.esc(p.date)}</td><td>${F.money(p.close)}</td></tr>`).join('') : '<tr><td class="l muted" colspan="2">none</td></tr>') + '</tbody></table>';
    g('pivot-highs').innerHTML = tb(T('swing high', 'Swing highs'), PV.highs); g('pivot-lows').innerHTML = tb(T('swing low', 'Swing lows'), PV.lows); }
  // card help
  const card = id => g(id).parentElement;
  F.help(card('chart-h'), {lead: `${sym ? F.esc(sym) : 'The'} daily closing price with its moving averages and recent turning points.`,
    sections: [{title: 'Reading the lines', html: '<p>The 50-day and 200-day lines are the average close over those many trading days; they smooth out the daily noise. A price above a rising 200-day line is the usual picture of an uptrend.</p><p>Dashed lines mark recent swing highs and lows, levels where the price turned before.</p>'}]});
  const r12 = RT['12m'], hp = H && Array.isArray(H.prices) ? H.prices : [], now = hp[hp.length - 1], then = hp.length > 252 ? hp[hp.length - 1 - 252] : null;
  F.help(card('h-ret'), {lead: 'How much the price changed over the last week, month, quarter, half-year and year.',
    sections: [{title: 'How a return is worked out', html: (now && then && F.isNum(now.close) && F.isNum(then.close) ? F.flow([{label: `close ${now.date}`, value: F.money(now.close)}, {op: '\u00f7', label: `close ${then.date}`, value: F.money(then.close)}, {op: '\u2212', label: 'one', value: '1'}, {op: '=', label: '12-month return', value: F.pct(now.close / then.close - 1, 1, true)}])
      : '<p>The close today divided by the close at the start of the window, minus one.</p>') + '<p>Windows count trading days (about 21 a month, 252 a year). Dividends are not included; this is the price alone.</p>'}]});
  if (S.relative) { const rel = S.relative['12m'];
    F.help(g('rel-card'), {lead: 'Whether the stock beat the benchmark over the same windows.',
      sections: F.isNum(rel) && F.isNum(r12) ? [{title: 'The 12-month row', html: F.flow([{label: 'stock return', value: F.pct(r12, 1, true)}, {op: '−', label: 'benchmark return', value: F.pct(r12 - rel, 1, true)}, {op: '=', label: 'ahead or behind', value: F.pct(rel, 1, true)}]) +
        '<p>Momentum 12-1 skips the most recent month, which tends to reverse; it is the version most studies of momentum use.</p>'}] : []}); }
  F.help(card('h-sig'), {lead: 'Every statistic the script computed, with the formula behind it.',
    sections: [{title: 'Reading the table', html: '<p>These are descriptions of past prices: trend, volatility, volume and gaps. They are the same numbers as the tiles at the top, listed in one place with how each is calculated.</p>'}]});
  if (PV) F.help(g('pivots-card'), {lead: 'Recent turning points in the price, where it reversed before.',
    sections: [{title: 'What counts as a pivot', html: `<p>A swing high is a close higher than the ${PV.k} closes on each side of it; a swing low is lower than them. Traders watch these levels because buying or selling often clustered there.</p>`}]});
  FA.armTerms(document);
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _read(path: str | None, what: str) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"could not read {what} JSON: {exc}") from exc
    return data


def build(signals: dict, history: dict | None, symbol: str | None = None) -> str:
    if not isinstance(signals, dict) or "returns" not in signals or "last_close" not in signals:
        raise InvalidInput("input must be a signals.py result (a JSON object with returns and last_close)")
    if history is not None and (not isinstance(history, dict) or not isinstance(history.get("prices"), list)):
        raise InvalidInput("--prices must be a history.py result (a JSON object with a prices list)")
    data = {"signals": signals, "history": history, "symbol": symbol or (history or {}).get("symbol")}
    return page.render(TITLE, data, BODY, SCRIPT)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--prices", default=None)
        p.add_argument("--symbol", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        signals = _read(ns.inp, "signals")
        history = _read(ns.prices, "history") if ns.prices else None
        out = page.write(ns.out, build(signals, history, ns.symbol))
        symbol = ns.symbol or (history or {}).get("symbol")
        return {"out": str(out), "title": TITLE, "symbol": symbol, "observations": signals.get("observations")}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
