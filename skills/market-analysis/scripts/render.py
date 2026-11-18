#!/usr/bin/env python3
"""Usage: render.py [--in flows.json] [--indices indices.json] --out page.html [--summary summary.json]

Turns a ``flows.py`` result and/or an ``indices.py`` result (at least one) into one self-contained
interactive HTML page for the Artifact tool: stat tiles (S&P 500 with its 200-week level, VIX and its one-year percentile,
the 10-year yield and the 10y-13w spread, breadth, and one S&P futures tile with each trader class's percentile; a tile whose source delivered nothing is
left out), a chart of the S&P 500's weekly close with its 50-, 100- and 200-week averages and a table of each gap's level (with ``indices.py --history`` data, range
buttons zoom it to daily closes over the latest week, month, three months or year, and out to weekly closes over 10 and 20 years), an indices/rates/macro table (each name opens its daily-close chart when the row
carries ``history``), the
positioning block (a crowdedness heatmap of every contract's percentile per trader class, a sortable
contracts table; clicking a contract opens its weekly net-position chart when flows.py ran with
``--history``, else its class table), a sectors table joining sector ETF moves, sector futures
positioning and sector ETF flows (a sector opens its fund's largest holdings from ``indices.py --holdings`` and its price chart), the ETF flow bars with an observations note while the local series
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
<section class="card" id="etf-card"><h2>Fund flows</h2><p class="sub" id="etf-sub">Money that went into or out of each sector's exchange-traded fund (ETF), as a share of the fund's size.</p><div id="etf-bars"></div><p class="note" id="etf-note"></p></section>
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
  // dates arrive as YYYY-MM-DD and parse as UTC midnight, so they are formatted in UTC to keep the day
  const dayFmt = x => new Date(x).toLocaleDateString('en-US', {month: 'short', day: 'numeric', timeZone: 'UTC'});
  const fullFmt = x => new Date(x).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
  const RANGES = [['1 week', 5], ['1 month', 21], ['3 months', 63], ['1 year', 0]];   // sessions of daily closes; 0 is all of them
  // range buttons over a chart: ranges = [[label, draw(box) -> note html]]; the one at `start` draws first
  const ranged = (root, ranges, start) => {
    root.innerHTML = '';
    const bar = F.el('div', {class: 'controls', role: 'group', 'aria-label': 'Chart range'}), box = F.el('div'), note = F.el('p', {class: 'note', style: 'margin-top:6px'});
    root.append(bar, box, note);
    const pick = i => { bar.querySelectorAll('button').forEach((b, j) => b.setAttribute('aria-pressed', j === i ? 'true' : 'false')); note.innerHTML = ranges[i][1](box) || ''; note.hidden = !note.innerHTML; };
    ranges.forEach(([label], i) => { const b = F.el('button', {class: 'chip', type: 'button'}, F.esc(label)); b.addEventListener('click', () => pick(i)); bar.appendChild(b); });
    pick(start);
  };
  // x labels on the dates that have a close, so a short range never labels a weekend
  const tickAt = xs => { const k = Math.min(6, xs.length); return Array.from({length: k}, (_, i) => xs[Math.round(i * (xs.length - 1) / Math.max(1, k - 1))]); };
  // one formatter for ticks and tooltip: it names the nearest date that has a close, not the cursor's date
  const snapFmt = (xs, fmt) => x => fmt(xs.reduce((b, v) => Math.abs(v - x) < Math.abs(b - x) ? v : b, xs[0]));
  const NAME_BTN = 'font:inherit;font-weight:600;color:inherit;background:none;border:0;padding:0;cursor:pointer;text-decoration:underline dotted var(--muted);text-underline-offset:3px';
  const nameBtn = (key, name) => `<button type="button" data-sym="${F.esc(key)}" style="${NAME_BTN}">${F.esc(name)}</button>`;
  // one row's daily closes with range buttons; h = {name, r (the indices.py row), axis (y format)}
  const priceChart = (root, h) => ranged(root, RANGES.map(([label, n]) => [label, el => { const rows = n ? h.r.history.slice(-n) : h.r.history, xs = rows.map(([d]) => Date.parse(d));
    F.lines(el, {series: [{name: h.name, points: rows.map(([d, c]) => [Date.parse(d), c]), color: F.S[0]}], xIsDate: true, xFmt: snapFmt(xs, n ? dayFmt : fullFmt), xTicks: tickAt(xs), endLabels: false, height: 260, yFmt: h.axis, aria: `${h.name} daily closes, ${label}`});
    return `Daily closes, ${F.esc(fullFmt(Date.parse(rows[0][0])))} to ${F.esc(fullFmt(Date.parse(rows[rows.length - 1][0])))}.`; }]), RANGES.length - 1);
  const hasHist = r => r && Array.isArray(r.history) && r.history.length > 1;
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
    // a row with daily closes (indices.py --history) gets a name button that opens its chart
    const HIST = {};
    const pctChg = (r, k) => [p1(r[k]), F.cls(r[k])], bpChg = (r, k) => { const v = bp(r.last, r[k]); return [bpFmt(v), F.cls(v)]; };
    const row = (r, name, val, chg) => { const key = r.symbol || name, [day, dayCls] = chg(r, 'day_change_pct'), [week, weekCls] = chg(r, 'week_change_pct');
      if (hasHist(r)) HIST[key] = {r, name, val, chg, axis: val === n2 && isNum(r.last) && Math.abs(r.last) >= 1000 ? n0 : val};
      return `<tr><td class="l">${HIST[key] ? nameBtn(key, name) : `<b>${F.esc(name)}</b>`}</td><td>${val(r.last)}</td><td class="${dayCls}">${day}</td><td class="${weekCls}">${week}</td></tr>`; };
    const groups = [
      ['Stocks and volatility', (I.indices || []).map(r => row(r, r.name, n2, pctChg))],
      ['Treasury yields', (I.rates || []).map(r => row(r, r.name, v => isNum(v) ? v.toFixed(2) + '%' : '—', bpChg))],
      ['Commodities, currency and crypto', MACRO.filter(([k]) => (I.macro || {})[k]).map(([k, name, cur]) => row(I.macro[k], name, cur ? v => money(v, cur) : n2, pctChg))]];
    setHtml('indices', '<table><thead><tr><th class="l">Name</th><th>Last</th><th>Day</th><th>Week</th></tr></thead>' +
      groups.filter(([, rs]) => rs.length).map(([label, rs]) => `<tbody><tr><th class="l" colspan="4" style="padding-top:14px;color:var(--ink2)">${F.esc(label)}</th></tr>${rs.join('')}</tbody>`).join('') + '</table>');
    const sp = I.spreads || {};
    setHtml('idx-note', `${FA.term('yield spread', 'Spreads')} (pts): 10y−13w ${n2(sp['10y_13w'])} · 5y−13w ${n2(sp['5y_13w'])} · 30y−5y ${n2(sp['30y_5y'])} · 30y−13w ${n2(sp['30y_13w'])}${I.breadth ? ` · ${FA.term('breadth', 'breadth')}: RSP−SPY 3m ${p1(I.breadth.rsp_spy_3m)}` : ''} · as of ${F.esc(I.as_of || '—')}`);
    if (Object.keys(HIST).length) {
      g('idx-card').querySelector('p.sub').append(' Click a name for its chart of daily closes over the past year.');
      g('indices').addEventListener('click', e => { const b = e.target.closest('button[data-sym]'), h = b && HIST[b.dataset.sym]; if (!h) return; const r = h.r;
        const [day] = h.chg(r, 'day_change_pct'), [week] = h.chg(r, 'week_change_pct'), [year] = h.chg(r, 'change_1y_pct');
        const box = F.modal(`<h3>${F.esc(h.name)}</h3><p class="sub">${r.symbol ? F.esc(r.symbol) + ' · ' : ''}last ${h.val(r.last)} · day ${day} · week ${week}</p><div id="i-chart"></div><dl class="kv"><dt>High over the period</dt><dd>${h.val(r.high_1y)}</dd><dt>Low over the period</dt><dd>${h.val(r.low_1y)}</dd><dt>Change over the period</dt><dd>${year}</dd><dt>Period</dt><dd>${r.history.length} daily closes, ${F.esc(fullFmt(Date.parse(r.history[0][0])))} to ${F.esc(fullFmt(Date.parse(r.history[r.history.length - 1][0])))}</dd></dl>`);
        priceChart(box.querySelector('#i-chart'), h); });
    }
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
      flow5: f ? f.flow_5d_pct_aum : null, flow20: f ? f.flow_20d_pct_aum : null, obs: f ? f.observations : null, src: s, more: !!s && (hasHist(s) || (s.top_holdings || []).length > 0)}); });
  if (secRows.length) {
    const pctCls = v => isNum(v) ? (v >= 90 || v <= 10 ? 'neg' : '') : '';
    F.table(g('sectors'), [{key: 'sector', label: 'Sector', left: true, fmt: (v, r) => `${r.more ? nameBtn(r.ticker, v) : `<b>${F.esc(v)}</b>`} <span class="muted">${F.esc(r.ticker)}</span>`}, {key: 'day', label: 'ETF day', fmt: p1, cls: F.cls}, {key: 'week', label: 'ETF week', fmt: p1, cls: F.cls},
      {key: 'am_pct', label: 'AM pct', fmt: (v, r) => p0(v) + (isNum(r.behind) && r.behind > 0 ? ` <span class="muted">(${r.behind}w)</span>` : ''), cls: pctCls}, {key: 'lev_pct', label: 'LEV pct', fmt: p0, cls: pctCls}, {key: 'sm_pct', label: 'Small pct', fmt: p0, cls: pctCls},
      {key: 'flow5', label: 'Flow, 5 readings', fmt: (v, r) => isNum(v) ? p1(v) + ' of fund' : (isNum(r.obs) ? `<span class="muted">${r.obs} recorded</span>` : '—'), cls: F.cls}, {key: 'flow20', label: 'Flow, 20 readings', fmt: (v, r) => isNum(v) ? p1(v) + ' of fund' : (isNum(r.obs) ? `<span class="muted">${r.obs} recorded</span>` : '—'), cls: F.cls}], secRows, {sortKey: 'week'});
    setHtml('sec-sub', `Each sector three ways: the sector ETF's price move, the sector futures ${FA.term('percentile')} per trader class (${FA.term('asset managers', 'AM')}, ${FA.term('leveraged funds', 'LEV')}, ${FA.term('small traders', 'Small')}), and the sector ETF's net ${FA.term('creation', 'creations')} as a share of the fund's size over its last 5 and 20 recorded readings (the Fund flows card gives the dates). A count of readings recorded stands in when a flow cannot be computed yet.${secRows.some(r => r.more) ? ' Click a sector for its fund\'s largest holdings and price chart.' : ''}`);
    g('sectors').addEventListener('click', e => { const b = e.target.closest('button[data-sym]'), sr = b && secRows.find(x => x.ticker === b.dataset.sym && x.more); if (!sr) return; const s = sr.src, top = s.top_holdings || [];
      const shown = top.reduce((a, t) => a + (isNum(t.weight_pct) ? t.weight_pct : 0), 0), wmax = Math.max(...top.map(t => t.weight_pct || 0), 1);
      const box = F.modal(`<h3>${F.esc(s.name)}</h3><p class="sub">${F.esc(s.symbol)}, the sector's exchange-traded fund · last ${n2(s.last)} · day ${p1(s.day_change_pct)} · week ${p1(s.week_change_pct)}</p>` +
        (top.length ? `<h4 style="margin:12px 0 4px;font-size:13px">Largest ${top.length} holdings</h4><div class="twrap"><table><thead><tr><th class="l">Holding</th><th class="l">Ticker</th><th>Share of fund</th><th class="l" style="width:35%"></th></tr></thead><tbody>` +
          top.map(t => `<tr><td class="l">${F.esc(t.name)}</td><td class="l muted">${F.esc(t.symbol)}</td><td>${isNum(t.weight_pct) ? t.weight_pct.toFixed(2) + '%' : '—'}</td><td class="l"><div style="height:8px;border-radius:2px;background:${F.S[0]};width:${isNum(t.weight_pct) ? Math.max(1, t.weight_pct / wmax * 100).toFixed(1) : 0}%"></div></td></tr>`).join('') +
          `</tbody></table></div><p class="note" style="margin-top:6px">These ${top.length} holdings make up ${shown.toFixed(1)}% of the fund. Source: Yahoo Finance, which gives the list no date.</p>` : '<p class="muted">No holdings list came with this run. Run indices.py with --holdings to add it.</p>') +
        (hasHist(s) ? '<h4 style="margin:14px 0 4px;font-size:13px">Fund price</h4><div id="s-chart"></div>' : ''));
      if (hasHist(s)) priceChart(box.querySelector('#s-chart'), {name: s.symbol, r: s, axis: n2}); });
  } else hide('sec-card');
  // fund flow bars: money in to the right of a centre line, money out to the left, sized by share of the fund
  if (etf) {
    const funds = etf.funds || [];
    const withFlow = funds.filter(f => isNum(f.flow_5d_pct_aum)).sort((x, y) => y.flow_5d_pct_aum - x.flow_5d_pct_aum);
    const IN = F.S[0], OUT = F.S[1];
    const day = d => F.esc(fullFmt(Date.parse(d)));
    const days = n => isNum(n) ? ` (${n} day${n === 1 ? '' : 's'})` : '';
    const inOut = v => isNum(v) ? `${big(Math.abs(v))} ${v >= 0 ? 'in' : 'out'}` : '—';
    const share = v => isNum(v) ? `${Math.abs(v).toFixed(1)}% of the fund` : '—';
    // the window a flow covers; a result from before the dates were carried falls back to the count of readings
    const span = (f, k) => f[`flow_${k}_from`] ? `${day(f[`flow_${k}_from`])} to ${day(f.as_of)}${days(f[`flow_${k}_span_days`])}` : null;
    const windows = [...new Set(withFlow.map(f => span(f, '5d')))];
    const common = windows.length === 1 ? windows[0] : null;
    if (withFlow.length) {
      const max = Math.max(...withFlow.map(f => Math.abs(f.flow_5d_pct_aum)), 1e-9);
      const COLS = 'display:grid;grid-template-columns:minmax(120px,1.4fr) 3fr 58px 78px;gap:10px;align-items:center;font-size:13px;padding:3px 0';
      const root = g('etf-bars'); root.innerHTML = '';
      root.appendChild(F.el('div', {style: COLS + ';color:var(--muted);font-size:11px;letter-spacing:.05em;text-transform:uppercase'},
        `<span>Fund</span><span style="display:flex;justify-content:space-between"><span>← money out</span><span>money in →</span></span><span style="text-align:right">Of fund</span><span style="text-align:right">Dollars</span>`));
      withFlow.forEach(f => { const v = f.flow_5d_pct_aum, w = (50 * Math.abs(v) / max).toFixed(1), tone = v >= 0 ? 'pos' : 'neg';
        const row = F.el('div', {style: COLS}, `<span><b>${F.esc(f.ticker)}</b> ${F.esc(f.name)}</span>` +
          `<div style="position:relative;height:14px;background:var(--grid);border-radius:3px"><div style="position:absolute;top:0;bottom:0;${v >= 0 ? 'left:50%' : 'right:50%'};width:${w}%;min-width:2px;background:${v >= 0 ? IN : OUT};border-radius:${v >= 0 ? '0 3px 3px 0' : '3px 0 0 3px'}"></div><div style="position:absolute;top:-3px;bottom:-3px;left:50%;width:1px;background:var(--muted)"></div></div>` +
          `<span class="${tone}" style="text-align:right;font-variant-numeric:tabular-nums">${p1(v)}</span><span style="text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)">${isNum(f.flow_5d_usd) ? (f.flow_5d_usd < 0 ? '−' : '+') + big(Math.abs(f.flow_5d_usd)) : '—'}</span>`);
        const w5 = span(f, '5d'), w20 = span(f, '20d'), w1 = span(f, '1d');
        F.bindTip(row, `<b>${F.esc(f.ticker)}</b> ${F.esc(f.name)}<br>${w5 || 'Last five readings'}: <b>${inOut(f.flow_5d_usd)}</b>, ${share(f.flow_5d_pct_aum)}` +
          (w20 && w20 !== w5 ? `<br>Longer window, ${w20}: ${inOut(f.flow_20d_usd)}, ${share(f.flow_20d_pct_aum)}` : '') +
          (isNum(f.flow_1d_usd) && w1 !== w5 ? `<br>Since the reading before${f.flow_1d_from ? `, ${day(f.flow_1d_from)}` : ''}${days(f.flow_1d_span_days)}: ${inOut(f.flow_1d_usd)}` : '') +
          `<br><span style="color:var(--ink2)">Fund size ${big(f.aum_usd)} on ${day(f.as_of)}</span>`);
        root.appendChild(row); });
      root.appendChild(F.el('div', {class: 'legend'}, `<span><i style="background:${IN}"></i>Money in: investors added to the fund</span><span><i style="background:${OUT}"></i>Money out: investors withdrew</span>`));
      setHtml('etf-sub', `Money that went into or out of each fund ${common ? `from ${common}` : 'over its last five recorded readings'}, as a share of the fund's size. The longest bar is the largest move, and funds are in order from most money in to most money out. Hover a row for the dates and dollars.`);
    } else g('etf-bars').innerHTML = '<p class="muted">No flows yet: a flow needs two recorded readings, and each run of this page records one per day.</p>';
    const groups = {}; funds.forEach(f => { const k = `${f.observations}|${f.first_observation}`; (groups[k] = groups[k] || []).push(f.ticker); });
    const history = Object.entries(groups).map(([k, tickers]) => { const [n, since] = k.split('|'); const who = tickers.length === funds.length ? '' : tickers.map(F.esc).join(', ') + ': '; return `${who}${n} reading${n === '1' ? '' : 's'} recorded since ${day(since)}`; }).join('; ');
    setHtml('etf-note', `How this is measured: each run of this page records every fund's share count from State Street. More shares means money came in (${FA.term('creation', 'a creation')}); fewer means money went out. The dollar figure is the change in shares times the share price. A window is the last five recorded readings, not five trading days, so its length depends on how often the page is run.${history ? ' ' + history[0].toUpperCase() + history.slice(1) + '.' : ''}${(etf.unavailable || []).length ? ' State Street listed no data for ' + etf.unavailable.map(F.esc).join(', ') + '.' : ''}`);
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
    const w200 = T.wma_200;
    const AVG = {50: {name: '50-week (momentum)', color: 'var(--muted)', width: 1.25, dash: '1 4', opacity: 0.9, endLabel: false}, 100: {name: '100-week', color: 'var(--muted)', width: 1.25, dash: '6 4', opacity: 0.9, endLabel: false}, 200: {name: '200-week', color: F.S[1], width: 3.5, endLabel: true}};
    // rows: weekly or daily {date, close, wma_*}. fit: scale the axis to the close and leave out an average
    // that sits off that scale, naming it in the note; otherwise the 200-week and its zone carry the reading.
    const drawTrend = (box, rows, {fit, daily, label}) => {
      const pts = k => rows.map(r => [Date.parse(r.date), r[k]]), xs = rows.map(r => Date.parse(r.date));
      const closes = rows.map(r => r.close).filter(isNum), lo = Math.min(...closes), hi = Math.max(...closes), span = Math.max(hi - lo, hi * 0.01);
      const onScale = n => !fit || rows.every(r => !isNum(r[`wma_${n}`]) || (r[`wma_${n}`] >= lo - span && r[`wma_${n}`] <= hi + span));
      const shown = [50, 100, 200].filter(onScale), off = [50, 100, 200].filter(n => !onScale(n)), bands = [];
      if (!fit && w200 && isNum(w200.band_low_pct) && isNum(w200.band_high_pct)) {
        const edge = pct => rows.map(r => [Date.parse(r.date), isNum(r.wma_200) ? r.wma_200 * (1 + pct / 100) : null]);
        bands.push({lo: edge(w200.band_low_pct), hi: edge(w200.band_high_pct), color: F.S[1], opacity: 0.13, legend: '200-week neutral zone (20th–80th percentile gap)'});
      }
      const avg = n => ({...AVG[n], points: pts(`wma_${n}`)});
      const close = {name: 'S&P 500', points: pts('close'), color: fit ? 'var(--ink)' : 'var(--ink2)', width: fit ? 2.5 : 1.75, endLabel: false};
      F.lines(box, {series: [...shown.filter(n => n !== 200).map(avg), close, ...shown.filter(n => n === 200).map(avg)],
        bands, xIsDate: true, xFmt: daily ? snapFmt(xs, fit ? dayFmt : fullFmt) : undefined, xTicks: daily ? tickAt(xs) : undefined, height: 320, yFmt: v => F.num(v, 0), aria: `S&P 500 ${daily ? 'daily' : 'weekly'} close over ${label} with its 50-, 100- and 200-week moving averages`});
      const last = rows[rows.length - 1];
      return (daily ? `Daily closes, ${F.esc(fullFmt(Date.parse(rows[0].date)))} to ${F.esc(fullFmt(Date.parse(last.date)))}. Each day's averages count that day's close as its week's close.` : '') +
        (off.length ? ` Off this scale: ${off.map(n => `${n}-week average ${n0(last[`wma_${n}`])}`).join(' · ')}.` : ''); };
    // with indices.py --history the chart zooms from five years of weeks down to the latest week of daily closes
    const DAILY = (T.daily || []).length > 1 ? T.daily : null;
    // the weekly series is five years, or twenty with --history; a longer range shows only when the weeks exist
    const YEARS = [[5, 260], [10, 520], [20, 1040]].filter(([, n], i, a) => !i || T.series.length > a[i - 1][1]);
    const trendRanges = [...(DAILY ? RANGES.map(([label, n]) => [label, box => drawTrend(box, n ? DAILY.slice(-n) : DAILY, {fit: !!n, daily: true, label})]) : []),
      ...YEARS.map(([y, n]) => [`${y} years`, box => drawTrend(box, T.series.slice(-n), {label: `${y} years`})])];
    if (trendRanges.length > 1) ranged(g('trend-chart'), trendRanges, trendRanges.length - YEARS.length);
    else drawTrend(g('trend-chart'), T.series, {label: '5 years'});
    const sg = v => isNum(v) ? (v >= 0 ? '+' : '') + v.toFixed(1) + '%' : '—';
    const rows = WIN.map(([n]) => [n, T[`wma_${n}`]]).filter(([, w]) => w);
    setHtml('trend-table', '<table><thead><tr><th class="l">Average</th><th class="l">Level</th><th>Average value</th><th>Gap</th><th>' + FA.term('percentile', 'Percentile') + ' since ' + F.esc(String(T.history_from || '').slice(0, 4)) + '</th><th>Typical gap</th><th>' + FA.term('time below', 'Time below average') + '</th></tr></thead><tbody>' +
      rows.map(([n, w]) => `<tr><td class="l">${n === 200 ? FA.term('200-week average', '200-week') : n + '-week'}</td><td class="l"><b>${F.esc(w.level)}</b></td><td>${n0(w.average)}</td><td class="${F.cls(w.gap_pct)}">${sg(w.gap_pct)}</td><td>${p0(w.percentile)}</td><td>${sg(w.median_gap_pct)}</td><td>${isNum(w.share_below_pct) ? w.share_below_pct + '% of weeks' : '—'}</td></tr>`).join('') + '</tbody></table>');
    setHtml('trend-note', `Closes as of ${F.esc(T.as_of || '—')}; the week in progress counts at its latest close.${DAILY ? ` The range buttons switch between weekly closes over ${YEARS.map(([y]) => y).join(', ').replace(/, (\d+)$/, ' or $1')} years and daily closes over the latest week, month, quarter or year.` : ''} Levels: extended at or above the 80th percentile of the gap's own history, depressed at or below the 20th, neutral between. The gap measures distance from trend, not value, and since 1950 it has said little about the returns that followed.`);
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
      (f0 ? `<p>${F.esc(f0.ticker)} ${f0.flow_5d_usd >= 0 ? 'took in' : 'lost'} ${F.moneyC(Math.abs(f0.flow_5d_usd))} ${f0.flow_5d_from ? `between ${F.esc(fullFmt(Date.parse(f0.flow_5d_from)))} and ${F.esc(fullFmt(Date.parse(f0.as_of)))}` : 'over the last five readings'}, ${isNum(f0.flow_5d_pct_aum) ? Math.abs(f0.flow_5d_pct_aum).toFixed(2) + '%' : '—'} of the fund's size.</p>` : '') +
      '<p>A reading is one recorded day. The page records one each day it runs, so five readings can span a week or several months. The dates under the title say which.</p>'}]});
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
