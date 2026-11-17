#!/usr/bin/env python3
"""Usage: render.py [--in flows.json] [--indices indices.json] --out page.html [--summary summary.json]

Turns a ``flows.py`` result and/or an ``indices.py`` result (at least one) into one self-contained
interactive HTML page for the Artifact tool: stat tiles (S&P 500 with its 200-week level, VIX and its one-year percentile,
the 10-year yield and the 10y-13w spread, breadth, and one S&P futures tile with each trader class's percentile; a tile whose source delivered nothing is
left out), a chart of the S&P 500's weekly close with its 50-, 100- and 200-week averages and a table of each gap's level, an indices/rates/macro table, the
positioning block (a crowdedness heatmap of every contract's percentile per trader class, a sortable
contracts table; clicking a contract opens its weekly net-position chart when flows.py ran with
``--history``, else its class table), a sectors table joining sector ETF moves, sector futures
positioning and sector ETF flows, the ETF flow bars with an observations note while the local series
is short, the money-fund line, the short-volume table when present, flags (dead blocks, contracts
missing from the report, funds missing from the finder) and the script's notes. Prints
``{"out", "title", "indices", "contracts", "funds", "flags"}``. Exit 2 on a missing or malformed
input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the two JSON files; the page formats and draws, it never recomputes a statistic. The one exception
is ``--summary``: the headline analysis card at the top is text the model wrote, which ``summary_card``
holds to its rules. A summary that breaks one is exit 2 and no page is written. Without the flag there is
no card. This page may be shared, so ``for_you`` (the person's holdings) is dropped unless
``portfolio-last-check.json`` shows a full read today; the render still succeeds and the printed JSON
gains ``for_you_dropped``.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page, summary_card  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Market Flows"

# The sections a headline analysis link may point to.
TARGETS = ("trend-card", "idx-card", "pos-card", "sec-card", "etf-card", "cash-card", "short-card", "flags-section")

BODY = """
<h1>Market Flows</h1>
<p class="sub" id="asof">{{HEADLINE}}</p>
<div id="explain"></div>
{{SUMMARY}}
<div class="tiles" id="tiles"></div>
<section class="card" id="trend-card"><h2>S&amp;P 500 against its weekly averages</h2><p class="sub" id="trend-sub">The weekly close over five years against its <span class="term" data-term="200-week average" tabindex="0">200-week moving average</span>. The shaded zone is where the 200-week gap is neutral: above it is extended, below it depressed. The 100- and 50-week averages are context; the 50-week is a momentum line. The table ranks today's gap to each average against every week since 1950.</p><div id="trend-chart"></div><div class="twrap" id="trend-table"></div><p class="note" id="trend-note"></p></section>
<section class="card" id="idx-card"><h2>Indices, rates and macro</h2><p class="sub">Where the market closed and how far it moved over the day and the week. Stock indexes and prices move in percent; Treasury yields move in basis points (1 bp = 0.01 percentage point).</p><div class="twrap" id="indices"></div><p class="note" id="idx-note"></p></section>
<section class="card" id="pos-card"><h2 id="pos-h">Positioning</h2><p class="sub" id="pos-sub">Who holds the futures: the net position of each trader class per contract, its change over the week, and where the latest reading sits within the window (0 = most net-short of the window, 100 = most net-long). Click a contract for its history.</p>
  <h3 id="crowd-h">Crowdedness</h3><p class="sub" id="crowd-sub">Percentile of each class's net position within the window. Deep red is the most net-long the class has been over the window, deep blue the most net-short; both are crowded readings.</p><div id="crowd"></div>
  <div class="twrap" id="positioning" style="margin-top:12px"></div><p class="note" id="pos-note"></p></section>
<section class="card" id="sec-card"><h2>Sectors</h2><p class="sub" id="sec-sub">Each sector three ways: the sector ETF's price move, the sector futures positioning percentile per trader class, and the sector ETF's net creations as a share of its assets.</p><div class="twrap" id="sectors"></div></section>
<section class="card" id="etf-card"><h2>ETF flows</h2><p class="sub" id="etf-sub">Net creations (money in) or redemptions (money out) over the last five observations, as a share of each fund's assets.</p><div id="etf-bars"></div><p class="note" id="etf-note"></p></section>
<section class="card" id="cash-card"><h2>Cash on the sidelines</h2><p class="sub" id="cash-sub">Retail money market fund assets, weekly, over the past year. Rising means cash is leaving risk or being saved; falling means it is being deployed or spent.</p><div id="cash"></div><p class="note" id="cash-note"></p></section>
<section class="card" id="short-card" hidden><h2>Short volume</h2><p class="sub">The share of each day's volume that was sold short, against the symbol's own average over the window. Compare a symbol with itself, not with others.</p><div class="twrap" id="short"></div></section>
<section data-help="none" id="flags-section"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul><ul class="news" id="notes"></ul></section>
<p class="note">Positioning is futures only and shows how each trader class is positioned, not who owns the cash equities. Asset managers are structurally net long index futures and leveraged funds structurally net short, so each class is read against its own history, not against zero; a crowded reading has historically been prone to reversal but is not a direction. ETF creations mix investor demand with authorized-participant arbitrage. Nothing here is a forecast or a recommendation. General information at the stated sources and dates, not financial advice.</p>
<noscript><p class="note">JavaScript is off: the charts and tables are not drawn. The headline figures are in the line under the title; the full result is embedded in the page as JSON.</p></noscript>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, I = D.indices || null, W = D.flows || null;
  const g = id => document.getElementById(id);
  const isNum = F.isNum;
  const p1 = v => isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(1) + '%' : '—';   // values already in percent units
  const p0 = v => isNum(v) ? v.toFixed(0) : '—';
  const n0 = v => F.num(v, 0), n2 = v => F.num(v, 2);
  const sgn0 = v => isNum(v) ? (v > 0 ? '+' : '') + F.num(v, 0) : '—';
  const big = v => { if (!isNum(v)) return '—'; const a = Math.abs(v), s = v < 0 ? '-' : ''; return a >= 1e9 ? s + '$' + (a / 1e9).toFixed(2) + 'B' : a >= 1e6 ? s + '$' + (a / 1e6).toFixed(1) + 'M' : s + '$' + F.num(a, 0); };
  const setHtml = (id, html) => { const n = g(id); n.innerHTML = html; F.armTerms(n); };
  const hide = id => { g(id).hidden = true; };
  Object.assign(F.glossary, {
    'asset managers': ['Pensions, insurers, endowments and mutual funds: the slow institutional money, which is usually net long stock index futures.', 'https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm'],
    'leveraged funds': ['Hedge funds and commodity trading advisers, which are usually net short index futures as a hedge against the stocks they own.', 'https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm'],
    'dealers': ['Banks and broker-dealers that sell futures to clients and hedge the other side; their position is the mirror of everyone else.', 'https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm'],
    'other reportables': ['Large traders the CFTC requires to report who fit none of the other groups, such as corporate treasuries and proprietary trading firms; a small, mixed group with no structural lean.', 'https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm'],
    'small traders': ['Positions too small for the CFTC to require reporting; the closest public proxy for retail.', 'https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm'],
    'net position': ['Contracts held long minus contracts held short by a trader class.', 'https://www.investopedia.com/terms/n/net-position.asp'],
    'open interest': ['The number of futures contracts outstanding; every contract has one long and one short.', 'https://www.investopedia.com/terms/o/openinterest.asp'],
    'percentile': ['Where the latest reading sits within the window: 0 is the lowest of the window, 100 the highest.', 'https://www.investopedia.com/terms/p/percentile.asp'],
    'crowded': ['A position near the extreme of its own history, so many traders are on the same side; such readings have historically been prone to reversal.', 'https://www.investopedia.com/terms/c/crowdedtrade.asp'],
    'creation': ['Large investors exchange baskets of stocks for new ETF shares (creation) or hand shares back for the stocks (redemption); the change in shares outstanding is the fund\'s net flow.', 'https://www.investopedia.com/terms/c/creationunit.asp'],
    'money market fund': ['A fund that holds very short-term, safe debt and works like cash that earns interest.', 'https://www.investopedia.com/terms/m/money-marketfund.asp'],
    'short volume': ['The share of a day\'s trading that was a short sale; in ETFs it is mostly market makers hedging, so compare a symbol only with its own history.', 'https://www.investopedia.com/terms/s/shortsale.asp'],
    'yield spread': ['The difference between a long and a short Treasury yield; below zero (inverted) has historically preceded recessions, with long and variable lags.', 'https://www.investopedia.com/terms/y/yieldspread.asp'],
    'breadth': ['How many stocks or sectors are joining a move; a rise carried by few names is narrow.', 'https://www.investopedia.com/terms/m/market_breadth.asp'],
    'moving average': ['The average weekly close over the last 50, 100 or 200 weeks (about one, two and four years; 50 weeks is close to the 200-day average). The gap says how far price has run from its own trend; it is not a valuation and has said little about returns that followed.', 'https://www.investopedia.com/terms/m/movingaverage.asp'],
    '200-week average': ['The average weekly close over about four years, a long-term trend line. It is known from a line attributed to Charlie Munger, that quality stocks bought near it beat the market. The S&P 500 has closed below it about one week in six since 1950, mostly in bear markets. Read the gap against its typical size, not against zero.', 'https://www.investopedia.com/terms/m/movingaverage.asp'],
    'time below': ['The share of weeks since 1950 that the S&P 500 closed below this average. Closes below the long averages are rare and have mostly come in bear markets.', 'https://www.investopedia.com/terms/m/movingaverage.asp'],
    'vix': ['The market\'s expected volatility over the next 30 days, implied by S&P 500 option prices; high means fear.', 'https://www.investopedia.com/terms/v/vix.asp'],
  });
  const CLASSES = [['asset_managers', 'Asset managers', 'asset managers'], ['leveraged_funds', 'Leveraged funds', 'leveraged funds'], ['dealers', 'Dealers', 'dealers'], ['other_reportables', 'Other reportables', 'other reportables'], ['small_traders', 'Small traders', 'small traders']];
  const classLabel = ([, label, term]) => term ? F.term(term, label) : F.esc(label);
  const pos = W && W.positioning && !W.positioning.error ? W.positioning : null;
  const etf = W && W.etf_flows && !W.etf_flows.error ? W.etf_flows : null;
  const cash = W && W.cash && !W.cash.error ? W.cash : null;
  const shortv = W && W.short_volume && !W.short_volume.error ? W.short_volume : null;
  const contracts = pos ? pos.contracts || [] : [];
  const byCode = {}; contracts.forEach(c => { byCode[c.code] = c; });
  const find = (list, sym) => (list || []).find(r => r.symbol === sym);
  FA.explain(g('explain'), `<p>This page shows who is moving money where, from the public reporting regimes rather than price and volume. The tiles give the market's level and mood; the positioning block shows how ${FA.term('asset managers')}, ${FA.term('leveraged funds')} and ${FA.term('small traders')} are positioned in index, sector, rates, dollar and volatility futures and how ${FA.term('crowded')} each position is; the sector table pairs those futures with the sector ETFs' price moves and ${FA.term('creation', 'creations')}; the cash chart tracks retail ${FA.term('money market fund', 'money market fund')} balances.</p><p>Read each trader class against its own ${FA.term('percentile')}, not against zero: asset managers are always net long and leveraged funds always net short index futures. Every block carries its own date, because the sources lag by a day, a week or a month.</p>`);
  // tiles
  const tiles = [];
  if (I) {
    const spx = find(I.indices, '^GSPC'), vix = find(I.indices, '^VIX'), tnx = find(I.rates, '^TNX');
    const t200 = I.trend && I.trend.wma_200;
    if (spx) tiles.push(['S&P 500', n2(spx.last), `day ${p1(spx.day_change_pct)} · week ${p1(spx.week_change_pct)}${t200 && isNum(t200.gap_pct) ? ` · ${FA.term('200-week average', '200-week')} ${F.esc(t200.level)} (${t200.gap_pct >= 0 ? '+' : ''}${t200.gap_pct.toFixed(1)}%)` : ''}`]);
    if (vix) tiles.push([FA.term('vix', 'VIX'), n2(vix.last), `1-year ${FA.term('percentile')} ${isNum(I.vix_percentile_1y) ? p0(I.vix_percentile_1y * 100) : '—'} · day ${p1(vix.day_change_pct)}`]);
    if (tnx && isNum(tnx.last)) tiles.push(['10-year yield', n2(tnx.last) + '%', `10y−13w ${FA.term('yield spread', 'spread')} ${isNum((I.spreads || {})['10y_13w']) ? n2(I.spreads['10y_13w']) + ' pts' : '—'}`]);
    if (I.breadth) tiles.push([FA.term('breadth', 'Breadth'), `${I.breadth.sectors_above_50sma ?? '—'} of ${I.breadth.sectors_total ?? '—'}`, `sectors above 50-day average · RSP−SPY 1m ${p1(I.breadth.rsp_spy_1m)}`]);
  }
  const es = byCode['13874A'];
  // one positioning tile: where each class's S&P futures net position sits in its own year
  if (es) { const c = es.classes; tiles.push([`S&amp;P futures ${FA.term('percentile')}`, `${p0(c.asset_managers.percentile)} · ${p0(c.leveraged_funds.percentile)} · ${p0(c.small_traders.percentile)}`, `${FA.term('asset managers')} · ${FA.term('leveraged funds')} · ${FA.term('small traders')}, report of ${F.esc(es.report_date || '—')}`]); }
  setHtml('tiles', tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join(''));
  // indices table
  if (I) {
    // grouped by grain, each value carrying its own unit; yield moves in basis points
    const MACRO = [['gold', 'Gold', '$'], ['oil', 'WTI crude', '$'], ['dollar', 'US dollar index', ''], ['bitcoin', 'Bitcoin', '$'], ['vix_3m', 'VIX 3-month', '']];
    const bp = (last, pct) => isNum(last) && isNum(pct) ? last - last / (1 + pct / 100) : null;   // pct is the change of the yield itself
    const bpFmt = v => isNum(v) ? `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(1)} bp` : '—';
    const money = (v, cur) => isNum(v) ? cur + F.num(v, v >= 1000 ? 0 : 2) : '—';
    const row = (name, last, day, week, dayCls, weekCls) => `<tr><td class="l"><b>${F.esc(name)}</b></td><td>${last}</td><td class="${dayCls}">${day}</td><td class="${weekCls}">${week}</td></tr>`;
    const groups = [
      ['Stocks and volatility', (I.indices || []).map(r => row(r.name, n2(r.last), p1(r.day_change_pct), p1(r.week_change_pct), F.cls(r.day_change_pct), F.cls(r.week_change_pct)))],
      ['Treasury yields', (I.rates || []).map(r => { const d = bp(r.last, r.day_change_pct), w = bp(r.last, r.week_change_pct); return row(r.name, isNum(r.last) ? r.last.toFixed(2) + '%' : '—', bpFmt(d), bpFmt(w), F.cls(d), F.cls(w)); })],
      ['Commodities, currency and crypto', MACRO.filter(([k]) => (I.macro || {})[k]).map(([k, name, cur]) => { const r = I.macro[k]; return row(name, cur ? money(r.last, cur) : n2(r.last), p1(r.day_change_pct), p1(r.week_change_pct), F.cls(r.day_change_pct), F.cls(r.week_change_pct)); })]];
    setHtml('indices', '<table><thead><tr><th class="l">Name</th><th>Last</th><th>Day</th><th>Week</th></tr></thead>' +
      groups.filter(([, rs]) => rs.length).map(([label, rs]) => `<tbody><tr><th class="l" colspan="4" style="padding-top:14px;color:var(--ink2)">${F.esc(label)}</th></tr>${rs.join('')}</tbody>`).join('') + '</table>');
    const sp = I.spreads || {};
    setHtml('idx-note', `${FA.term('yield spread', 'Spreads')} (pts): 10y−13w ${n2(sp['10y_13w'])} · 5y−13w ${n2(sp['5y_13w'])} · 30y−5y ${n2(sp['30y_5y'])} · 30y−13w ${n2(sp['30y_13w'])}${I.breadth ? ` · ${FA.term('breadth', 'breadth')}: RSP−SPY 3m ${p1(I.breadth.rsp_spy_3m)}` : ''} · as of ${F.esc(I.as_of || '—')}`);
  } else hide('idx-card');
  // positioning
  if (contracts.length) {
    setHtml('pos-h', `${FA.term('net position', 'Positioning')} · report of ${F.esc(pos.report_date || '—')}`);
    setHtml('crowd-h', FA.term('crowded', 'Crowdedness'));
    F.heatmap(g('crowd'), {rows: contracts.map(c => c.label), cols: CLASSES.map(c => c[1]), values: contracts.map(c => CLASSES.map(([k]) => isNum(c.classes[k].percentile) ? c.classes[k].percentile - 50 : null)), diverging: true, min: -50, max: 50, fmt: v => (v + 50).toFixed(0)});
    g('crowd').querySelectorAll('thead th').forEach((th, i) => { const cl = CLASSES[i - 1]; if (cl) th.innerHTML = classLabel(cl); });
    F.armTerms(g('crowd'));
    const rows = contracts.map(c => ({code: c.code, label: c.label, group: c.group, report_date: c.report_date, weeks_behind: c.weeks_behind, open_interest: c.open_interest,
      am_net: c.classes.asset_managers.net, am_chg: c.classes.asset_managers.net_change, am_pct: c.classes.asset_managers.percentile,
      lev_net: c.classes.leveraged_funds.net, lev_chg: c.classes.leveraged_funds.net_change, lev_pct: c.classes.leveraged_funds.percentile,
      sm_net: c.classes.small_traders.net, sm_chg: c.classes.small_traders.net_change, sm_pct: c.classes.small_traders.percentile}));
    const pctCls = v => isNum(v) ? (v >= 90 || v <= 10 ? 'neg' : '') : '';
    const crowd = (v, r, k) => isNum(r[k]) && (r[k] >= 90 || r[k] <= 10) ? 'neg' : F.cls(v);   // crowded readings keep the warning colour
    const cols = [{key: 'label', label: 'Contract', left: true, fmt: (v, r) => `<b>${F.esc(v)}</b>${isNum(r.weeks_behind) && r.weeks_behind > 0 ? ` <span class="muted">(${r.weeks_behind}w behind)</span>` : ''}`}, {key: 'group', label: 'Group', fmt: F.esc}, {key: 'open_interest', label: 'Open interest', fmt: n0},
      {key: 'am_net', label: 'AM net', fmt: (v, r) => sgn0(v) + ` <span class="muted">p${p0(r.am_pct)}</span>`, cls: (v, r) => crowd(v, r, 'am_pct')}, {key: 'am_chg', label: 'AM week', fmt: sgn0, cls: F.cls},
      {key: 'lev_net', label: 'LEV net', fmt: (v, r) => sgn0(v) + ` <span class="muted">p${p0(r.lev_pct)}</span>`, cls: (v, r) => crowd(v, r, 'lev_pct')}, {key: 'lev_chg', label: 'LEV week', fmt: sgn0, cls: F.cls},
      {key: 'sm_net', label: 'Small net', fmt: (v, r) => sgn0(v) + ` <span class="muted">p${p0(r.sm_pct)}</span>`, cls: (v, r) => crowd(v, r, 'sm_pct')}, {key: 'sm_chg', label: 'Small week', fmt: sgn0, cls: F.cls}];
    const root = g('positioning');
    F.table(root, cols, rows, {sortKey: 'open_interest', onDraw: vis => { root.querySelectorAll('tbody tr').forEach((tr, i) => { tr.dataset.code = vis[i].code; tr.classList.add('clickable'); }); }});
    root.querySelectorAll('th[data-key]').forEach(th => { const m = {open_interest: FA.term('open interest', 'Open interest'), am_net: FA.term('asset managers', 'AM net'), lev_net: FA.term('leveraged funds', 'LEV net'), sm_net: FA.term('small traders', 'Small net')}; if (m[th.dataset.key]) th.innerHTML = m[th.dataset.key]; });
    F.armTerms(root);
    root.addEventListener('click', e => { const tr = e.target.closest('tr[data-code]'); if (!tr) return; const c = byCode[tr.dataset.code]; if (!c) return;
      const box = F.modal(`<h3>${F.esc(c.label)}</h3><p class="sub">${F.esc(c.name)} · report of ${F.esc(c.report_date)} · ${FA.term('open interest', 'open interest')} ${n0(c.open_interest)} (${sgn0(c.open_interest_change)} on the week) · ${c.weeks} weeks in window</p><div id="m-chart"></div><div class="twrap" id="m-table" style="margin-top:10px"></div>`);
      const hist = c.history || [];
      if (hist.length > 1) F.lines(box.querySelector('#m-chart'), {series: CLASSES.filter(k => k[0] !== 'other_reportables').map(([k, label], i) => ({name: label, color: F.S[i % 8], points: hist.map(h => [Date.parse(h.date), h[k]])})), xIsDate: true, zeroLine: true, height: 240, yFmt: v => n0(v), aria: `${c.label} net positioning by trader class`});
      else box.querySelector('#m-chart').innerHTML = '<p class="muted">Run flows.py with --history to chart the weekly series.</p>';
      box.querySelector('#m-table').innerHTML = '<table><thead><tr><th class="l">Class</th><th>Long</th><th>Short</th><th>Net</th><th>Week</th><th>% of OI</th><th>Percentile</th></tr></thead><tbody>' + CLASSES.map(cl => { const v = c.classes[cl[0]]; return `<tr><td class="l">${classLabel(cl)}</td><td>${n0(v.long)}</td><td>${n0(v.short)}</td><td class="${F.cls(v.net)}">${sgn0(v.net)}</td><td class="${F.cls(v.net_change)}">${sgn0(v.net_change)}</td><td>${isNum(v.net_pct_oi) ? v.net_pct_oi.toFixed(1) + '%' : '—'}</td><td class="${pctCls(v.percentile)}">${p0(v.percentile)}</td></tr>`; }).join('') + '</tbody></table>';
      F.armTerms(box); });
    setHtml('pos-note', `${contracts.length} contracts · window ${pos.weeks ?? '—'} weeks · "p" after a net position is its ${FA.term('percentile')} within the window; at or below 10 or at or above 90 it is shown in red as ${FA.term('crowded')} · "behind" marks a contract the CFTC last reported that many weeks before the newest report (thin sector futures drop out when open interest is small)`);
  } else { hide('pos-card'); }
  // sectors: ETF move (indices), futures positioning (flows), ETF flows (flows)
  const secRows = [];
  const secName = c => c.label.replace(/ sector$/, '').toLowerCase();
  const sectorFut = {}; contracts.filter(c => c.group === 'sector').forEach(c => { sectorFut[secName(c)] = c; });
  const fundBy = {}; (etf ? etf.funds || [] : []).forEach(f => { fundBy[String(f.name).toLowerCase()] = f; });
  const names = new Set([...(I ? (I.sectors || []).map(s => String(s.name).toLowerCase()) : []), ...Object.keys(sectorFut), ...Object.keys(fundBy).filter(n => n !== 'spdr s&p 500 etf')]);
  names.forEach(n => { const s = I ? (I.sectors || []).find(x => String(x.name).toLowerCase() === n) : null; const c = sectorFut[n]; const f = fundBy[n];
    secRows.push({sector: (s && s.name) || (f && f.name) || (c && c.label.replace(/ sector$/, '')), ticker: (s && s.symbol) || (f && f.ticker) || '—', day: s ? s.day_change_pct : null, week: s ? s.week_change_pct : null,
      am_pct: c ? c.classes.asset_managers.percentile : null, lev_pct: c ? c.classes.leveraged_funds.percentile : null, sm_pct: c ? c.classes.small_traders.percentile : null, behind: c ? c.weeks_behind : null,
      flow5: f ? f.flow_5d_pct_aum : null, flow20: f ? f.flow_20d_pct_aum : null, obs: f ? f.observations : null}); });
  if (secRows.length) {
    const pctCls = v => isNum(v) ? (v >= 90 || v <= 10 ? 'neg' : '') : '';
    F.table(g('sectors'), [{key: 'sector', label: 'Sector', left: true, fmt: (v, r) => `<b>${F.esc(v)}</b> <span class="muted">${F.esc(r.ticker)}</span>`}, {key: 'day', label: 'ETF day', fmt: p1, cls: F.cls}, {key: 'week', label: 'ETF week', fmt: p1, cls: F.cls},
      {key: 'am_pct', label: 'AM pct', fmt: (v, r) => p0(v) + (isNum(r.behind) && r.behind > 0 ? ` <span class="muted">(${r.behind}w)</span>` : ''), cls: pctCls}, {key: 'lev_pct', label: 'LEV pct', fmt: p0, cls: pctCls}, {key: 'sm_pct', label: 'Small pct', fmt: p0, cls: pctCls},
      {key: 'flow5', label: 'Flow 5 obs', fmt: (v, r) => isNum(v) ? p1(v) + ' of AUM' : (isNum(r.obs) ? `<span class="muted">${r.obs} obs</span>` : '—'), cls: F.cls}, {key: 'flow20', label: 'Flow 20 obs', fmt: (v, r) => isNum(v) ? p1(v) + ' of AUM' : (isNum(r.obs) ? `<span class="muted">${r.obs} obs</span>` : '—'), cls: F.cls}], secRows, {sortKey: 'week'});
    setHtml('sec-sub', `Each sector three ways: the sector ETF's price move, the sector futures ${FA.term('percentile')} per trader class (${FA.term('asset managers', 'AM')}, ${FA.term('leveraged funds', 'LEV')}, ${FA.term('small traders', 'Small')}), and the sector ETF's net ${FA.term('creation', 'creations')} as a share of its assets. "obs" counts the days recorded so far when a flow cannot be computed yet.`);
  } else hide('sec-card');
  // ETF flow bars
  if (etf) {
    const funds = etf.funds || [];
    const withFlow = funds.filter(f => isNum(f.flow_5d_pct_aum));
    if (withFlow.length) F.bars(g('etf-bars'), withFlow.map(f => ({label: `${f.ticker} ${f.name}`, share: f.flow_5d_pct_aum / 100, color: f.flow_5d_pct_aum >= 0 ? F.S[1] : F.S[7], text: `${p1(f.flow_5d_pct_aum)} · ${big(f.flow_5d_usd)}`,
      tip: `<b>${F.esc(f.ticker)}</b> ${F.esc(f.name)}<br>5 obs ${big(f.flow_5d_usd)} (${p1(f.flow_5d_pct_aum)} of AUM)<br>20 obs ${big(f.flow_20d_usd)} (${p1(f.flow_20d_pct_aum)})<br>1 obs ${big(f.flow_1d_usd)} over ${f.flow_1d_span_days ?? '—'} days<br>AUM ${big(f.aum_usd)} · ${n0(f.shares)} shares · ${F.esc(f.as_of)}`})));
    else g('etf-bars').innerHTML = '<p class="muted">No flows yet: the local shares series needs at least two recorded days.</p>';
    const short = funds.filter(f => !isNum(f.flow_5d_pct_aum) || f.observations < 6);
    const groups = {}; short.forEach(f => { const k = `${f.observations}|${f.first_observation}`; (groups[k] = groups[k] || []).push(f.ticker); });
    const shortNote = Object.entries(groups).map(([k, tickers]) => { const [n, since] = k.split('|'); const who = tickers.length === funds.length ? `all ${funds.length} funds` : tickers.map(F.esc).join(', '); return `${who}: ${n} observation${n === '1' ? '' : 's'} since ${F.esc(since)}`; }).join('; ');
    setHtml('etf-note', `Shares outstanding = AUM ÷ NAV from State Street's daily fund data, recorded locally each run; a flow is the change in shares × NAV, so sums cover observations, not calendar days.${shortNote ? ' Short history — ' + shortNote + '.' : ''}${(etf.unavailable || []).length ? ' Not in the finder: ' + etf.unavailable.map(F.esc).join(', ') + '.' : ''} As of ${F.esc(etf.as_of || '—')}.`);
  } else hide('etf-card');
  // cash line
  if (cash) {
    const obs = (cash.observations || []).filter(o => isNum(o.value));
    if (obs.length > 1) F.lines(g('cash'), {series: [{name: 'Retail money funds', color: F.S[2], area: true, points: obs.map(o => [Date.parse(o.date), o.value])}], xIsDate: true, height: 220, yFmt: v => '$' + n0(v) + 'B', aria: 'Retail money market fund assets'});
    else g('cash').innerHTML = `<p class="muted">Latest ${F.esc(cash.date || '—')}: $${n0(cash.latest)}B.</p>`;
    setHtml('cash-note', `${F.esc(cash.name || cash.series)} (${F.esc(cash.unit || '')}): $${n0(cash.latest)}B on ${F.esc(cash.date || '—')} · 1 week ${sgn0(cash.change_1w)}B · 4 weeks ${sgn0(cash.change_4w)}B · 13 weeks ${sgn0(cash.change_13w)}B · 52 weeks ${sgn0(cash.change_52w)}B (${p1(cash.change_52w_pct)}). Weekly data published monthly by the Fed's H.6 release, so the latest week can be six weeks old. Source FRED series ${F.esc(cash.series)}.`);
  } else hide('cash-card');
  // short volume
  if (shortv && (shortv.symbols || []).length) {
    g('short-card').hidden = false;
    F.table(g('short'), [{key: 'symbol', label: 'Symbol', left: true, fmt: v => `<b>${F.esc(v)}</b>`}, {key: 'date', label: 'Date', fmt: F.esc}, {key: 'short_ratio', label: 'Short ratio', fmt: v => isNum(v) ? v.toFixed(1) + '%' : '—'}, {key: 'short_ratio_avg', label: `Avg ${shortv.days ?? ''}d`, fmt: v => isNum(v) ? v.toFixed(1) + '%' : '—'}, {key: 'ratio_vs_avg', label: 'vs avg', fmt: v => isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(1) + ' pts' : '—', cls: F.cls}, {key: 'short_volume', label: 'Short volume', fmt: n0}, {key: 'total_volume', label: 'Total volume', fmt: n0}, {key: 'days', label: 'Days', fmt: v => String(v ?? '—')}], shortv.symbols, {sortKey: 'ratio_vs_avg'});
    const th = g('short').querySelector('th[data-key="short_ratio"]'); if (th) th.innerHTML = FA.term('short volume', 'Short ratio'); F.armTerms(g('short'));
  }
  // trend chart
  const T = I && I.trend;
  if (T && (T.series || []).length) {
    const WIN = [[50], [100], [200]];
    const pts = k => T.series.map(r => [Date.parse(r.date), r[k]]);
    const w200 = T.wma_200, bands = [];
    if (w200 && isNum(w200.band_low_pct) && isNum(w200.band_high_pct)) {
      const edge = pct => T.series.map(r => [Date.parse(r.date), isNum(r.wma_200) ? r.wma_200 * (1 + pct / 100) : null]);
      bands.push({lo: edge(w200.band_low_pct), hi: edge(w200.band_high_pct), color: F.S[1], opacity: 0.13, legend: '200-week neutral zone (20th–80th percentile gap)'});
    }
    // hierarchy: the 200-week and its zone carry the reading; the close is context; the 100- and 50-week recede
    F.lines(g('trend-chart'), {series: [
        {name: '50-week (momentum)', points: pts('wma_50'), color: 'var(--muted)', width: 1.25, dash: '1 4', opacity: 0.9, endLabel: false},
        {name: '100-week', points: pts('wma_100'), color: 'var(--muted)', width: 1.25, dash: '6 4', opacity: 0.9, endLabel: false},
        {name: 'S&P 500', points: pts('close'), color: 'var(--ink2)', width: 1.75, endLabel: false},
        {name: '200-week', points: pts('wma_200'), color: F.S[1], width: 3.5, endLabel: true}],
      bands, xIsDate: true, height: 320, yFmt: v => F.num(v, 0), aria: 'S&P 500 weekly close with its 200-week moving average and neutral zone, and its 100- and 50-week averages'});
    const sg = v => isNum(v) ? (v >= 0 ? '+' : '') + v.toFixed(1) + '%' : '—';
    const rows = WIN.map(([n]) => [n, T[`wma_${n}`]]).filter(([, w]) => w);
    setHtml('trend-table', '<table><thead><tr><th class="l">Average</th><th class="l">Level</th><th>Average value</th><th>Gap</th><th>' + FA.term('percentile', 'Percentile') + ' since ' + F.esc(String(T.history_from || '').slice(0, 4)) + '</th><th>Typical gap</th><th>' + FA.term('time below', 'Time below average') + '</th></tr></thead><tbody>' +
      rows.map(([n, w]) => `<tr><td class="l">${n === 200 ? FA.term('200-week average', '200-week') : n + '-week'}</td><td class="l"><b>${F.esc(w.level)}</b></td><td>${n0(w.average)}</td><td class="${F.cls(w.gap_pct)}">${sg(w.gap_pct)}</td><td>${p0(w.percentile)}</td><td>${sg(w.median_gap_pct)}</td><td>${isNum(w.share_below_pct) ? w.share_below_pct + '% of weeks' : '—'}</td></tr>`).join('') + '</tbody></table>');
    setHtml('trend-note', `Weekly closes as of ${F.esc(T.as_of || '—')}; the week in progress counts at its latest close. Levels: extended at or above the 80th percentile of the gap's own history, depressed at or below the 20th, neutral between. The gap measures distance from trend, not value, and since 1950 it has said little about the returns that followed.`);
  } else hide('trend-card');
  // card help
  const ord = v => { if (!isNum(v)) return '—'; const n = Math.round(v), t = n % 100; return n + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th'); };
  const help = (id, spec) => { const c = g(id); if (c && !c.hidden) F.help(c, spec); };
  const sp2 = I && I.spreads ? I.spreads['10y_13w'] : null;
  help('trend-card', {lead: 'How far the S&P 500 has run from its own trend over about one, two and four years.',
    sections: [{title: 'About the 200-week average', html: '<p>The 200-week average is the mean of the last 200 weekly closes, about four years. It is known to many investors from a line attributed to Charlie Munger: that buying high-quality stocks at their 200-week average would beat the S&P 500 by a wide margin. That line was about single stocks, not the index.</p><p>For the S&P 500 it has worked as a deep floor. Since 1950 the index has closed below it about one week in six, in long stretches during 1969–71, 1973–76, 2001–04 and 2008–10, and briefly in 1962, 1966, 1982, 2011, 2020 and 2022. The 1987 crash never closed a week below it.</p>'},
      {title: 'How to read it', html: '<p>The index drifts up, so it normally sits well above this line: the typical gap since 1950 is about +17%. The shaded zone is the middle 60% of that history. Above the zone is extended, inside it neutral, below it depressed; below the line itself is the rare case.</p><p>Since 1950, extended readings were followed by a down year about one time in three and depressed ones about one in five, with similar average returns, and the gap said almost nothing about the next five years. It shows how far price has run from its trend. It is not a valuation and not a timing signal.</p>'},
      {title: 'Reading the levels', html: '<p>The index drifts up over time, so it usually sits above these averages: the typical gap is the yardstick, not zero. Extended means the gap is in the top fifth of its history since 1950, depressed the bottom fifth.</p><p>This is not a valuation. Since 1950, extended 100- and 200-week gaps were followed by a down year somewhat more often, an extended 50-week gap less often, and none said much about the next five years.</p>'}]});
  help('idx-card', {lead: 'Where the main stock indexes, interest rates and a few macro prices closed, and how far they moved over the day and the week.',
    sections: [{title: 'The spread line', html: `<p>A spread is one yield minus another. The 10-year minus the 13-week Treasury yield${isNum(sp2) ? ` is ${n2(sp2)} points` : ''}: positive is the usual shape, with long loans paying more; negative (an inverted curve) has often come before recessions, with a variable lag.</p>`}]});
  const c0 = contracts[0], am0 = c0 && c0.classes && c0.classes.asset_managers;
  help('pos-card', {lead: 'How the big groups of futures traders are betting, compared with their own positions over the past year.',
    sections: [...(am0 && isNum(am0.long) && isNum(am0.short) ? [{title: `One reading: asset managers in ${c0.label}`, html: F.flow([{label: 'contracts long', value: F.num(am0.long, 0)}, {op: '−', label: 'contracts short', value: F.num(am0.short, 0)}, {op: '=', label: 'net', value: sgn0(am0.net)}]) +
        `<p>That net position sits at the ${ord(am0.percentile)} percentile of the window: 0 is the most short they have been, 100 the most long.</p>`}] : []),
      {title: 'Crowded readings', html: '<p>A percentile at or below 10, or at or above 90, is an extreme for that group. Extremes show where a lot of money already leans; they are not a forecast.</p>'}]});
  const br = I && I.breadth;
  help('sec-card', {lead: 'Which industries are leading or lagging, seen three ways: price, futures positioning and money flowing into each sector fund.',
    sections: br ? [{title: 'How broad the move is', html: `<p>${br.sectors_above_50sma ?? '—'} of ${br.sectors_total ?? '—'} sectors are above their 50-day average price. Few sectors above it means a market carried by a narrow group.</p>`}] : []});
  const f0 = etf && (etf.funds || []).find(f => isNum(f.flow_5d_usd));
  help('etf-card', {lead: 'Money moving into or out of large index funds, sized against each fund’s assets.',
    sections: [{title: 'Creations and redemptions', html: '<p>When investors put money into an ETF, new shares are created; when they take money out, shares are redeemed. Counting shares day to day shows the flow.</p>' +
      (f0 ? `<p>${F.esc(f0.ticker)} took in ${F.moneyC(f0.flow_5d_usd)} over the last five readings, ${isNum(f0.flow_5d_pct_aum) ? f0.flow_5d_pct_aum.toFixed(2) + '%' : '—'} of its assets.</p>` : '')}]});
  help('cash-card', {lead: 'Money-market fund assets, a gauge of cash waiting outside stocks and bonds.',
    sections: cash && isNum(cash.latest) ? [{title: 'Latest reading', html: F.flow([{label: `a year before ${cash.date}`, value: '$' + F.num(cash.latest - (cash.change_52w || 0), 1) + 'B'}, {op: '+', label: '52-week change', value: (cash.change_52w >= 0 ? '+' : '−') + '$' + F.num(Math.abs(cash.change_52w || 0), 1) + 'B'}, {op: '=', label: 'now', value: '$' + F.num(cash.latest, 1) + 'B'}]) +
      '<p>Rising balances mean cash is building up; falling means it is being spent or invested.</p>'}] : []});
  const s0 = shortv && (shortv.symbols || [])[0];
  help('short-card', {lead: 'The share of each day’s trading that was short selling, against the symbol’s own recent average.',
    sections: s0 && isNum(s0.short_volume) && isNum(s0.total_volume) ? [{title: `${s0.symbol} on ${s0.date}`, html: F.flow([{label: 'shares sold short', value: F.num(s0.short_volume, 0)}, {op: '÷', label: 'shares traded', value: F.num(s0.total_volume, 0)}, {op: '=', label: 'short ratio', value: isNum(s0.short_ratio) ? s0.short_ratio.toFixed(1) + '%' : '—'}]) +
      '<p>Market makers sell short all day to fill orders, so a large share is normal. Compare a symbol with its own average, not with other symbols.</p>'}] : []});
  // flags and notes
  const flags = [];
  if (W) { for (const k of ['positioning', 'etf_flows', 'cash', 'short_volume']) { const b = W[k]; if (b && b.error) flags.push([b.code || 'ERROR', `${k}: ${b.error}`]); }
    if (pos && (pos.missing || []).length) flags.push(['NOT_REPORTED', `no report within the window for ${pos.missing.length} contract${pos.missing.length > 1 ? 's' : ''}: ${pos.missing.join(', ')}`]);
    if (etf && (etf.unavailable || []).length) flags.push(['NOT_IN_FINDER', `no State Street data for ${etf.unavailable.join(', ')}`]); }
  g('flags').innerHTML = flags.length ? flags.map(([c, m]) => `<li><b>${F.esc(c)}</b>${F.esc(m)}</li>`).join('') : '<li class="muted" style="border-color:var(--grid)">None</li>';
  g('notes').innerHTML = (W && W.notes || []).map(n => `<li>${F.esc(n)}</li>`).join('');
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _num(v: object, dp: int = 2) -> str:
    return f"{v:,.{dp}f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _signed(v: object, dp: int = 1) -> str:
    return f"{v:+.{dp}f}%" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _pct100(v: object) -> object:
    """indices.py gives vix_percentile_1y as a 0-1 fraction; the page shows it on a 0-100 scale."""
    return v * 100 if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def _find(rows: object, symbol: str) -> dict:
    return next((r for r in (rows or []) if isinstance(r, dict) and r.get("symbol") == symbol), {}) if isinstance(rows, list) else {}


def _headline(indices: dict | None, flows: dict | None) -> str:
    """Static one-line summary so the page reads without JavaScript."""
    parts = []
    if indices:
        spx, vix, tnx = _find(indices.get("indices"), "^GSPC"), _find(indices.get("indices"), "^VIX"), _find(indices.get("rates"), "^TNX")
        if spx:
            parts.append(f"S&P 500 {_num(spx.get('last'))} ({_signed(spx.get('day_change_pct'))})")
        trend = indices.get("trend") or {}
        w200 = trend.get("wma_200") or {}
        if isinstance(w200.get("gap_pct"), (int, float)):
            parts.append(f"vs 200-week average {_signed(w200.get('gap_pct'))} ({w200.get('level')})")
        if vix:
            parts.append(f"VIX {_num(vix.get('last'), 1)} (1y percentile {_num(_pct100(indices.get('vix_percentile_1y')), 0)})")
        if isinstance(tnx.get("last"), (int, float)):
            parts.append(f"10y {_num(tnx.get('last'))}%")
    if flows:
        pos, etf, cash = flows.get("positioning") or {}, flows.get("etf_flows") or {}, flows.get("cash") or {}
        if pos.get("report_date"):
            parts.append(f"positioning as of {pos['report_date']}")
        if etf.get("as_of"):
            parts.append(f"ETF flows as of {etf['as_of']}")
        if isinstance(cash.get("latest"), (int, float)):
            parts.append(f"retail money funds ${cash['latest']:,.0f}B ({cash.get('date') or '—'})")
    return " · ".join(parts) or "no data"


def _load(path: str | None, what: str) -> dict | None:
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"could not read {what} JSON: {exc}") from exc
    return data


def build(flows: dict | None, indices: dict | None, summary: dict | None = None) -> str:
    if flows is not None and not (isinstance(flows, dict) and "sources" in flows and any(k in flows for k in ("positioning", "etf_flows", "cash", "short_volume"))):
        raise InvalidInput("--in must be a flows.py result (a JSON object with sources and at least one of positioning, etf_flows, cash, short_volume)")
    if indices is not None and not (isinstance(indices, dict) and isinstance(indices.get("indices"), list)):
        raise InvalidInput("--indices must be an indices.py result (a JSON object with an indices list)")
    if flows is None and indices is None:
        raise InvalidInput("at least one of --in (a flows.py result) or --indices (an indices.py result) is required")
    body = BODY.replace("{{HEADLINE}}", html.escape(_headline(indices, flows)))
    body = body.replace("{{SUMMARY}}", summary_card.card_html(summary))
    return page.render(TITLE, {"flows": flows, "indices": indices}, body, SCRIPT)


def _count_flags(flows: dict | None) -> int:
    if not flows:
        return 0
    n = sum(1 for k in ("positioning", "etf_flows", "cash", "short_volume") if isinstance(flows.get(k), dict) and flows[k].get("error"))
    pos, etf = flows.get("positioning") or {}, flows.get("etf_flows") or {}
    return n + (1 if pos.get("missing") else 0) + (1 if etf.get("unavailable") else 0)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--indices", default=None)
        p.add_argument("--out", required=True)
        p.add_argument("--summary", default=None)
        ns = p.parse_args(args)
        flows, indices = _load(ns.inp, "flows"), _load(ns.indices, "indices")
        summary = summary_card.load(ns.summary, TARGETS) if ns.summary else None
        dropped = bool(summary and "for_you" in summary and not summary_card.full_read_today())
        if dropped:
            del summary["for_you"]
        out = page.write(ns.out, build(flows, indices, summary))
        pos = (flows or {}).get("positioning") or {}
        etf = (flows or {}).get("etf_flows") or {}
        result = {"out": str(out), "title": TITLE, "indices": len((indices or {}).get("indices") or []), "contracts": len(pos.get("contracts") or []), "funds": len(etf.get("funds") or []), "flags": _count_flags(flows)}
        if dropped:
            result["for_you_dropped"] = "no full portfolio read today"
        return result

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
