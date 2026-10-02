#!/usr/bin/env python3
"""Usage: render.py [--in snapshot.json] --out page.html

Turns one ``snapshot.py`` result (a file, or stdin when ``--in`` is omitted) into a self-contained
interactive HTML page for the Artifact tool: a Headlines card with a collapsed Coverage table when the
input came from ``brief.py``, stat tiles for the totals, accounts as bars, an allocation
donut (bonds, US equities, international equities, cash, other) with the bucket bars, sector exposure
looked through ETF/mutual-fund holdings (falling back to single stocks only for an older snapshot
without ``sector_exposure``), a sortable holdings table with an account filter and search, movers,
upcoming events and the change since the last saved snapshot when present, dated headlines under each mover
(``news``), a per-holding detail panel (click a row: what it is from ``profiles``, a one-year price chart from
``price_history``, links to the quote page, SEC filings and the company site), a one-line intro with a
"How to read this page" walkthrough, glossary terms, and the flags. Prints
``{"out": path, "title": ..., "positions": n, "flags": n, "headlines": n}``. Exit 2 on a missing or malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the snapshot JSON; the page formats, sorts and filters, it never recomputes totals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Portfolio Snapshot"

BODY = """
<h1>Portfolio Snapshot</h1>
<p class="sub" id="asof"></p>
<div id="explain"></div>
<section class="card" id="headlines-card" hidden><h2>Headlines</h2>
  <p class="sub hl-totals" id="hl-totals"></p>
  <ul class="hl" id="headlines"></ul>
  <button type="button" class="chip" id="hl-more" hidden></button>
  <details class="cov"><summary id="cov-line"></summary><div class="twrap" id="coverage"></div></details></section>
<div class="tiles" id="tiles"></div>
<div class="grid2">
  <div class="card" id="accounts-card"><h2>Accounts</h2><p class="sub">Each connected account’s value and its share of the total.</p><div id="accounts"></div></div>
  <div class="card" id="alloc-card"><h2>Allocation</h2><p class="sub">How the money splits between US stocks, international stocks, bonds, cash and other.</p><div style="display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start">
    <div id="donut"></div><div style="flex:1;min-width:180px"><div id="buckets"></div></div></div>
    <p class="note" id="alloc-note"></p><p class="note" id="conc"></p></div>
</div>
<div class="grid2">
  <div class="card" id="sector-card"><h2>Sector exposure</h2><p class="sub" id="sector-sub"></p><div id="sectors"></div></div>
  <div class="card" id="movers-card"><h2>Movers today</h2><p class="sub">The holdings that moved most today, with the newest dated story for each.</p><div id="movers"></div></div>
</div>
<section class="card" id="holdings-card"><h2>Holdings</h2>
  <p class="sub">Click a row for what the holding is, its one-year price history and where it sits across accounts.</p>
  <div class="controls">
    <input id="q" type="search" placeholder="Search symbol or name" aria-label="Search holdings">
    <select id="acct" aria-label="Filter by account"><option value="">All accounts</option></select>
    <span class="muted" id="count"></span>
  </div>
  <div class="twrap" id="holdings"></div>
</section>
<section class="card" id="events-card" hidden><h2>Upcoming events</h2><p class="sub">Earnings and dividend dates coming up for what you hold.</p><div class="twrap" id="events"></div></section>
<section class="card" id="compare-card" hidden><h2>Change since last snapshot</h2><p class="sub" id="compare-line"></p><div class="twrap" id="compare"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Headlines are the newest dated stories Yahoo lists for each mover in the last 7 days; the dateline is the publication date, and a story is context, not the cause of the move. Quotes are delayed. Weights are of total value across every connected account. Unrealized P&amp;L excludes positions with no cost basis. General information, not financial advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, T = D.totals || {}, F = FA;
  const g = id => document.getElementById(id);
  const when = D.as_of ? new Date(D.as_of).toLocaleString('en-US', {dateStyle: 'medium', timeStyle: 'short'}) : '';
  const src = D.sources || {};
  g('asof').textContent = `As of ${when} · holdings ${src.holdings || '—'} · quotes ${src.quotes || '—'}` + (src.quotes === 'etrade' ? ' (real-time)' : ' (delayed)');
  FA.explain(g('explain'), `<p>Everything you hold across every connected account, valued at the latest quotes. Headlines at the top are ${F.term('headline', 'headlines')} from the other skills, newest and most urgent first, with ${F.term('coverage')} showing which skills took part. The tiles give the totals; ${F.term('allocation')} splits the money into ${F.term('bonds')}, US and international stocks, cash and other; ${F.term('sector')} exposure uses ${F.term('look-through')} to add each fund's holdings into the sectors they belong to, alongside individual stocks; bonds, cash and funds without sector data sit outside the sector bars. The holdings table sorts by any column and filters by account; click a row for a plain-language description and a year of prices. ${F.term('unrealized p&l', 'Unrealized P&L')} is paper gain or loss versus what you paid. Movers are today's biggest percentage changes, with recent headlines as context. Flags at the bottom are data caveats, not judgments.</p>`, false);
  // tiles
  const cashLikeVal = F.isNum(T.cash_like) ? T.cash_like : T.cash;
  const cashFloor = F.isNum(T.cash) ? Math.max(T.cash, 0) : 0;
  const mmVal = F.isNum(T.cash_like) ? T.cash_like - cashFloor : 0;
  const cashPct = F.isNum(T.cash_like_pct) ? T.cash_like_pct : T.cash_pct;
  const cashParts = [`${F.pct(cashPct)} of total`, `settled ${F.money(T.cash)}`];
  if (mmVal) cashParts.push(`money-market funds ${F.money(mmVal)}`);
  const cashSub = cashParts.join(' · ');
  const tiles = [
    ['Total value', F.money(T.total_value), `${(D.accounts || []).length} accounts`],
    [F.term('money market fund', 'Cash'), F.money(cashLikeVal), cashSub],
    ['Day change', `<span class="${F.cls(T.day_change)}">${F.moneyS(T.day_change)}</span>`, `${F.pct(T.day_change_pct, 2, true)} · covers ${F.pct(T.day_change_coverage)} of holdings`],
    [F.term('unrealized p&l', 'Unrealized P&L'), `<span class="${F.cls(T.unrealized_pnl)}">${F.moneyS(T.unrealized_pnl)}</span>`, F.isNum(T.no_cost_basis_pct) && T.no_cost_basis_pct > 0 ? `excludes ${F.pct(T.no_cost_basis_pct)} with no cost basis` : ''],
  ];
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  // headlines + coverage
  const HL_TOP = 3;
  if (Array.isArray(D.headlines)) {
    const HL = D.headlines, CV = D.coverage || [];
    if (HL.length || CV.length) {
      g('headlines-card').hidden = false;
      const tot = (sev, n, singular, plural) => `<span class="tot sev-${sev}"><span class="dot"></span>${n} ${n === 1 ? singular : plural}</span>`;
      const nAlert = HL.filter(h => h.severity === 'alert').length, nNotice = HL.filter(h => h.severity === 'notice').length, nInfo = HL.filter(h => h.severity === 'info').length;
      const nNew = HL.filter(h => h.status === 'new').length;
      const newTxt = nNew === 0 ? 'none new since the last brief' : `${nNew} new since the last brief`;
      g('hl-totals').innerHTML = HL.length
        ? `${tot('alert', nAlert, 'alert', 'alerts')}${tot('notice', nNotice, 'notice', 'notices')}${tot('info', nInfo, 'info', 'info')} · ${newTxt}`
        : 'No headlines from the other skills today.';
      const label = h => `<span class="pill pill-skill">${F.esc(h.skill)}</span>`;
      const newPill = h => h.status === 'new' ? '<span class="pill pill-new pill-lead">new</span>' : '';
      const hlLink = h => {
        if (!h.url || h.url.indexOf('https://') !== 0) return '';
        let host = 'link';
        try { host = new URL(h.url).hostname.replace(/^www\./, ''); } catch (e) {}
        return `<a class="hl-link" href="${F.esc(h.url)}" target="_blank" rel="noopener">${F.esc(host)}</a>`;
      };
      g('headlines').innerHTML = HL.map((h, i) => {
        const hasMore = !!(h.why || h.answer || h.detail || h.ask);
        const showDetail = h.detail && h.detail !== h.answer;
        const more = hasMore ? `<div class="more" hidden>${h.why ? `<div class="why">${F.esc(h.why)}</div>` : ''}${h.answer ? `<div class="answer">${F.esc(h.answer)}</div>` : ''}${showDetail ? `<div class="d">${F.esc(h.detail)}</div>` : ''}${(!h.answer && h.ask) ? `<div class="d muted">Ask: ${F.esc(h.ask)}</div>` : ''}</div>` : '';
        return `<li class="sev-${F.esc(h.severity)}${hasMore ? ' toggle' : ''}" data-i="${i}"${hasMore ? ' tabindex="0"' : ''}${i >= HL_TOP ? ' hidden' : ''}><span class="dot" title="${F.esc(h.severity)}"></span><div class="body"><div class="t">${newPill(h)}${F.esc(h.title)}${label(h)}${hlLink(h)}</div>${more}</div></li>`;
      }).join('');
      g('headlines').querySelectorAll('li.toggle').forEach(li => {
        const toggle = () => { li.classList.toggle('open'); const more = li.querySelector('.more'); if (more) more.hidden = !more.hidden; };
        li.addEventListener('click', toggle);
        li.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.target.closest('a')) toggle(); });
      });
      g('headlines').querySelectorAll('a.hl-link').forEach(a => a.addEventListener('click', e => e.stopPropagation()));
      const moreBtn = g('hl-more');
      if (HL.length > HL_TOP) {
        moreBtn.hidden = false;
        let expanded = false;
        moreBtn.textContent = `Show all ${HL.length} headlines`;
        moreBtn.addEventListener('click', () => {
          expanded = !expanded;
          g('headlines').querySelectorAll('li').forEach((li, i) => {
            if (i >= HL_TOP) li.hidden = !expanded;
            if (!expanded && i >= HL_TOP && li.classList.contains('open')) {
              li.classList.remove('open');
              const more = li.querySelector('.more');
              if (more) more.hidden = true;
            }
          });
          moreBtn.textContent = expanded ? `Show top ${HL_TOP}` : `Show all ${HL.length} headlines`;
        });
      }
      const ok = CV.filter(c => c.status === 'ok').length, sk = CV.filter(c => c.status === 'skipped').length, fl = CV.filter(c => c.status === 'failed').length;
      g('cov-line').textContent = `${ok} of ${CV.length} sources checked in ${F.isNum(D.brief_seconds) ? D.brief_seconds : '—'}s · ${sk} skipped · ${fl} failed`;
      g('coverage').innerHTML = '<table><thead><tr><th class="l">Skill</th><th class="l">Status</th><th class="l">Reason</th><th class="l">Setup</th><th>Seconds</th><th>Headlines</th></tr></thead><tbody>' +
        CV.map(c => `<tr><td class="l">${F.esc(c.skill)}</td><td class="l ${F.esc(c.status)}">${F.esc(c.status)}</td><td class="l">${F.esc(c.reason || '')}</td><td class="l">${F.esc(c.hint || '')}</td><td>${F.isNum(c.seconds) ? c.seconds.toFixed(1) : '—'}</td><td>${c.headlines ?? 0}</td></tr>`).join('') + '</tbody></table>';
    }
  }
  // accounts
  const accts = D.accounts || [];
  F.bars(g('accounts'), accts.map((a, i) => ({label: a.name || a.account_id, share: a.weight, color: F.S[i % 8], text: F.money(a.total_value, 0) + ' · ' + F.pct(a.weight),
    tip: `<b>${F.esc(a.name)}</b> ${F.esc(a.institution_name || '')}<br>${F.esc(a.account_type || '')}${a.supports_trading ? ' · trading' : ' · read-only'}<br>cash ${F.money(a.cash)} · ${a.position_count ?? '—'} positions${F.isNum(a.cash_adjusted_for_money_market) && a.cash_adjusted_for_money_market > 0 ? ` · ${F.money(a.cash_adjusted_for_money_market)} held as a money-market fund` : ''}`})));
  // allocation: bonds / US equity / international equity / cash / other
  const AL = D.allocation, B = AL ? AL.buckets : null;
  const bucketLabel = {us_equity: 'US equities', intl_equity: 'International equities', bonds: 'Bonds', cash: 'Cash', other: 'Other'};
  const bucketColor = {us_equity: F.S[0], intl_equity: F.S[2], bonds: F.S[1], cash: F.S[3], other: F.S[4]};
  if (B) {
    const parts = Object.entries(B).filter(([, v]) => v.value > 0).map(([k, v]) => ({label: bucketLabel[k] || k, value: v.value, color: bucketColor[k]}));
    F.donut(g('donut'), parts, 'allocation');
    F.bars(g('buckets'), Object.entries(B).map(([k, v]) => ({label: bucketLabel[k] || k, share: v.weight, color: bucketColor[k], text: F.money(v.value, 0) + ' · ' + F.pct(v.weight),
      tip: `<b>${bucketLabel[k] || k}</b> ${v.count} holdings<br>${F.esc((v.symbols || []).join(', ') || '—')}`})));
    g('alloc-note').textContent = (AL.note || '') + (AL.unclassified && AL.unclassified.length ? ` Not classified (in Other): ${AL.unclassified.join(', ')}.` : '');
  } else {
    const AC = D.asset_classes || {}; const classColor = {fund: F.S[0], stock: F.S[1], other: F.S[2]};
    const parts = Object.entries(AC).map(([k, v]) => ({label: k, value: v.value, color: classColor[k] || F.S[4]}));
    if (parts.length) F.donut(g('donut'), parts, 'asset class'); else g('donut').innerHTML = '<span class="muted">no allocation data</span>';
    g('alloc-note').textContent = 'Asset buckets need fund categories; showing quote types only.';
  }
  // sector exposure: looks through ETF/mutual-fund holdings when sector_exposure is present
  const SE = D.sector_exposure;
  if (SE && SE.sectors) {
    const entries = Object.entries(SE.sectors).sort((a, b) => b[1].weight - a[1].weight);
    const NS = SE.not_sectorized || {};
    const missing = SE.missing_data || [];
    const looked = SE.looked_through || [];
    const proxied = looked.filter(s => s.indexOf(' (via ') !== -1).length;
    let sub = `Looks through ${looked.length} funds` + (proxied > 0 ? ` (${proxied} via proxy)` : '') + ` (${F.pct(SE.equity_share)} of the portfolio sectorized) · ${F.pct(NS.bonds_and_cash)} bonds and cash, not sectorized`;
    if (missing.length) sub += `, no data for ${missing.join(', ')}`;
    g('sector-sub').textContent = sub;
    F.bars(g('sectors'), entries.map(([k, v]) => ({label: k, share: v.weight, color: 'var(--s1)', text: `${F.pct(v.weight)} · ${F.pct(v.direct)} direct`,
      tip: `<b>${F.esc(k)}</b> direct: ${F.esc((D.positions || []).filter(p => p.sector === k).map(p => p.symbol).join(', ') || '—')}<br>via funds: ${F.esc((v.funds || []).map(f => `${f.symbol} ${F.pct(f.weight)}`).join(', ') || '—')}`})));
  } else {
    const SW = D.sector_weights || {};
    const stockSyms = new Set((D.positions || []).filter(p => p.sector && p.sector !== 'ETF' && p.sector !== 'Unknown').map(p => p.symbol));
    const sec = Object.entries(SW).filter(([k]) => k !== 'ETF' && k !== 'Unknown').sort((a, b) => b[1] - a[1]);
    const secTotal = sec.reduce((a, [, v]) => a + v, 0);
    g('sector-sub').textContent = sec.length ? `Single stocks only (${stockSyms.size} names, ${F.pct(secTotal)} of market value); funds are not looked through.` : 'No single-stock sector data.';
    F.bars(g('sectors'), sec.map(([k, v]) => ({label: k, share: v, color: 'var(--s1)', text: F.pct(v) + ' of value',
      tip: `<b>${F.esc(k)}</b> ${F.esc((D.positions || []).filter(p => p.sector === k).map(p => p.symbol).join(', '))}`})));
  }
  const C = D.concentration || {}, SS = C.single_stock, LP = C.largest_position;
  let conc = `${F.term('concentration', 'Concentration')} of positions: ${F.term('hhi', 'HHI')} ${F.isNum(C.hhi) ? C.hhi.toFixed(4) : '—'} (${C.hhi_interpretation || '—'}) · top-5 ${F.pct(C.top_5_concentration)} · ${C.position_count ?? '—'} positions`;
  if (LP) conc += ` · largest ${LP.symbol} ${F.pct(LP.weight)}${LP.asset_class ? ' (' + LP.asset_class + ')' : ''}`;
  if (SS) conc += `. Single stocks: ${F.pct(SS.weight)} of value in ${SS.count} names, HHI ${SS.hhi.toFixed(4)} (${SS.hhi_interpretation})` + (SS.largest ? `, largest ${SS.largest.symbol} ${F.pct(SS.largest.weight)}` : '') + '.';
  g('conc').innerHTML = conc; F.armTerms(g('conc'));
  // holdings
  const acctName = Object.fromEntries(accts.map(a => [a.account_id, a.name]));
  const rows = (D.positions || []).map(p => ({...p, accounts_txt: (p.accounts || []).map(id => acctName[id] || id).join(', ')}));
  const cols = [
    {key: 'symbol', label: 'Symbol', left: true, fmt: (v, r) => `<b>${F.esc(v)}</b>${r.name && r.name !== v ? `<span class="muted"> ${F.esc(r.name)}</span>` : ''}`},
    {key: 'accounts_txt', label: 'Account', left: true, fmt: v => F.esc(v)},
    {key: 'units', label: 'Units', fmt: v => F.num(v, 3)},
    {key: 'price', label: 'Price', fmt: v => F.money(v)},
    {key: 'market_value', label: 'Value', fmt: v => F.money(v)},
    {key: 'weight', label: 'Weight', fmt: v => F.pct(v)},
    {key: 'unrealized_pnl', label: 'Unrealized', fmt: v => F.moneyS(v), cls: F.cls},
    {key: 'day_change_pct', label: 'Day', fmt: v => F.pct(v, 2, true), cls: F.cls},
    {key: 'week_change_pct', label: '1w', fmt: v => F.pct(v, 1, true), cls: F.cls},
    {key: 'month_change_pct', label: '1m', fmt: v => F.pct(v, 1, true), cls: F.cls},
    {key: 'sector', label: 'Sector', left: true, fmt: v => F.esc(v || '—')},
  ];
  const PH = D.price_history || {}, PR = D.profiles || {};
  const bucketLabel2 = {us_equity: 'US equity', intl_equity: 'International equity', bucket_bonds: 'Bond', bonds: 'Bond', cash: 'Cash', other: 'Other'};
  const detail = r => {
    const p = PR[r.symbol] || {}; const hist = PH[r.symbol] || [];
    const closes = hist.map(h => h.close); const hi = closes.length ? Math.max(...closes) : null, lo = closes.length ? Math.min(...closes) : null;
    const first = closes.length ? closes[0] : null; const yr = (first && r.price) ? r.price / first - 1 : null;
    const perAcct = (r.accounts || []).map(id => acctName[id] || id).join(', ') || '—';
    const kind = p.quote_type === 'EQUITY' ? 'Stock' : p.quote_type === 'ETF' ? 'ETF' : p.quote_type === 'MUTUALFUND' ? 'Mutual fund' : p.quote_type === 'MONEYMARKET' ? 'Money market fund' : (p.quote_type || 'Holding');
    const links = [];
    links.push(`<a href="https://finance.yahoo.com/quote/${encodeURIComponent(r.symbol)}" target="_blank" rel="noopener">Yahoo Finance quote</a>`);
    if (p.quote_type === 'EQUITY') links.push(`<a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${encodeURIComponent(r.symbol)}&type=10-K&owner=include&count=10" target="_blank" rel="noopener">SEC filings</a>`);
    if (p.website) links.push(`<a href="${F.esc(p.website)}" target="_blank" rel="noopener">Company website</a>`);
    const box = F.modal(`<h3>${F.esc(r.symbol)} <span class="muted" style="font-weight:400">${F.esc(p.name || r.name || '')}</span></h3>
      <p class="sub" style="margin:0 0 8px">${F.esc(kind)}${p.bucket ? ' · ' + F.esc(bucketLabel2[p.bucket] || p.bucket) : ''}${p.sector && p.sector !== 'ETF' ? ' · ' + F.esc(p.sector) : ''}${p.category ? ' · ' + F.esc(p.category) : ''}${p.country ? ' · ' + F.esc(p.country) : ''}</p>
      ${p.summary ? `<p style="font-size:13px;color:var(--ink2);margin:0 0 10px">${F.esc(p.summary)}</p>` : '<p class="muted" style="font-size:13px">No description available for this holding.</p>'}
      <div class="kv"><dt>Units</dt><dd>${F.num(r.units, 3)}</dd><dt>Price</dt><dd>${F.money(r.price)}</dd><dt>Value</dt><dd>${F.money(r.market_value)} (${F.pct(r.weight)} of total)</dd>
        <dt>Cost basis</dt><dd>${F.isNum(r.cost_basis) ? F.money(r.cost_basis) : '—'}</dd><dt>Unrealized</dt><dd class="${F.cls(r.unrealized_pnl)}">${F.moneyS(r.unrealized_pnl)}${F.isNum(r.unrealized_pnl_pct) ? ' (' + F.pct(r.unrealized_pnl_pct, 1, true) + ')' : ''}</dd>
        <dt>Accounts</dt><dd>${F.esc(perAcct)}</dd>
        <dt>Past year</dt><dd>${yr !== null ? `<span class="${F.cls(yr)}">${F.pct(yr, 1, true)}</span>` : '—'}${hi !== null ? ` · range ${F.money(lo)} to ${F.money(hi)}` : ''}</dd></div>
      <h2 style="margin-top:8px">One-year price history</h2><div id="mchart"></div>
      <p class="note" style="margin-top:8px">${links.join(' · ')}</p>`);
    const chart = box.querySelector('#mchart');
    if (hist.length > 1) F.lines(chart, {series: [{name: r.symbol, points: hist.map(h => [Date.parse(h.date), h.close]), color: F.S[0], area: true}], xIsDate: true, yFmt: v => F.money(v, 2), height: 220, aria: `${r.symbol} one-year price history`});
    else chart.innerHTML = '<span class="muted">No price history available.</span>';
  };
  const tbl = F.table(g('holdings'), cols, rows, {sortKey: 'market_value', onDraw: vis => { g('count').textContent = `${vis.length} of ${rows.length}`;
    g('holdings').querySelectorAll('tbody tr').forEach((tr, i) => { tr.classList.add('clickable'); tr.tabIndex = 0; const open = () => detail(vis[i]); tr.addEventListener('click', open); tr.addEventListener('keydown', e => { if (e.key === 'Enter') open(); }); }); }});
  const sel = g('acct'); accts.forEach(a => { const o = document.createElement('option'); o.value = a.account_id; o.textContent = a.name || a.account_id; sel.appendChild(o); });
  sel.addEventListener('change', () => tbl.setFilter(r => !sel.value || (r.accounts || []).includes(sel.value)));
  g('q').addEventListener('input', e => tbl.setQuery(e.target.value));
  // movers
  const M = D.movers || {up: [], down: []};
  const mv = [...(M.up || []).map(m => ({...m, dir: 1})), ...(M.down || []).map(m => ({...m, dir: -1}))];
  const N = D.news || {};
  if (!mv.length) g('movers').innerHTML = '<span class="muted">no quote data</span>';
  else {
    const root = g('movers'); root.innerHTML = '';
    const max = Math.max(...mv.map(m => Math.abs(m.day_change_pct || 0)), 1e-9);
    for (const m of mv) {
      const row = F.el('div', {class: 'bar'});
      row.appendChild(F.el('span', {class: 'l'}, `<b>${F.esc(m.symbol)}</b>`));
      const track = F.el('div', {class: 'track'}); const fill = F.el('div', {class: 'fill'});
      fill.style.width = (100 * Math.abs(m.day_change_pct || 0) / max) + '%'; fill.style.background = m.day_change_pct >= 0 ? 'var(--up)' : 'var(--down)';
      track.appendChild(fill); row.appendChild(track);
      row.appendChild(F.el('span', {class: 'n ' + F.cls(m.day_change_pct)}, `${F.pct(m.day_change_pct, 2, true)} · ${F.moneyS(m.day_change)}`));
      root.appendChild(row);
      const items = N[m.symbol] || [];
      const ul = F.el('ul', {class: 'news'});
      if (D.news && !items.length) ul.appendChild(F.el('li', {class: 'muted'}, 'no dated story in the last 7 days'));
      for (const n of items) {
        const when = n.published ? new Date(n.published).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'}) : '';
        const title = n.url ? `<a href="${F.esc(n.url)}" target="_blank" rel="noopener">${F.esc(n.title)}</a>` : F.esc(n.title);
        ul.appendChild(F.el('li', {}, `<span class="muted">${F.esc(when)}${n.publisher ? ' · ' + F.esc(n.publisher) : ''}</span> ${title}`));
      }
      if (ul.childElementCount) root.appendChild(ul);
    }
  }
  // events
  if (Array.isArray(D.events) && D.events.length) { g('events-card').hidden = false;
    g('events').innerHTML = '<table><thead><tr><th class="l">Date</th><th class="l">Symbol</th><th class="l">Type</th></tr></thead><tbody>' + D.events.map(e => `<tr><td class="l">${F.esc(e.date)}</td><td class="l">${F.esc(e.symbol)}</td><td class="l">${F.esc(e.type)}</td></tr>`).join('') + '</tbody></table>'; }
  // comparison
  const K = D.comparison;
  if (K && K.total_value) { g('compare-card').hidden = false; const tv = K.total_value;
    g('compare-line').textContent = `Since ${K.since} (${K.days} days ago): ${F.money(tv.before)} → ${F.money(tv.after)} (${F.moneyS(tv.delta)}, ${F.pct(tv.delta_pct, 2, true)})`;
    const syms = K.symbols || [];
    g('compare').innerHTML = syms.length ? '<table><thead><tr><th class="l">Symbol</th><th>Before</th><th>After</th><th>Change</th><th>%</th></tr></thead><tbody>' + syms.map(s => `<tr><td class="l">${F.esc(s.symbol)}</td><td>${F.money(s.before)}</td><td>${F.money(s.after)}</td><td class="${F.cls(s.delta)}">${F.moneyS(s.delta)}</td><td class="${F.cls(s.delta_pct)}">${F.pct(s.delta_pct, 2, true)}</td></tr>`).join('') + '</tbody></table>' + (K.n_more ? `<p class="note">${K.n_more} more symbols not shown</p>` : '') : ''; }
  // card help: what each card answers and how its figures are built
  const dot = sev => `<span class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:var(${sev === 'alert' ? '--down' : sev === 'notice' ? '--warn' : '--s1'})"></span>`;
  F.help(g('headlines-card'), {lead: 'What changed since the last brief, gathered from your other finance skills, newest first.',
    sections: [{title: 'Reading a headline', html: `<p>${dot('alert')}Red is an alert: something with a date or a threshold that needs attention soon.</p><p>${dot('notice')}Amber is a notice: a change worth knowing about.</p><p>${dot('info')}Blue is information.</p><p>A NEW tag means it was not in the last brief. Click a headline for the answer behind it; the sources line at the bottom shows which skills took part.</p>`}]});
  const topA = [...accts].sort((a, b) => (b.total_value || 0) - (a.total_value || 0)), shownA = topA.slice(0, 3), restA = topA.slice(3).reduce((t, a) => t + (a.total_value || 0), 0);
  F.help(g('accounts-card'), {lead: 'Each connected account’s value and its share of everything you hold.',
    sections: accts.length ? [{title: 'How the total adds up', html: F.flow([...shownA.map((a, i) => ({op: i ? '+' : undefined, label: a.name || a.account_id, value: F.moneyC(a.total_value)})),
      ...(restA ? [{op: '+', label: `${topA.length - 3} more`, value: F.moneyC(restA)}] : []), {op: '=', label: 'total value', value: F.moneyC(T.total_value)}])}] : []});
  F.help(g('alloc-card'), {lead: 'How the money splits between US stocks, international stocks, bonds, cash and other.',
    sections: [{title: 'Cash', html: `<p>Money-market funds count as cash here, because they hold short-term government and bank debt and keep a steady $1 price. Cash and money-market funds together are ${F.pct(cashPct)} of the total.</p>`},
      {title: 'The concentration line', html: `<p>HHI adds up the square of every holding's weight: near 0 means many small holdings, 1 means a single holding. A large fund is spread across many companies, so the single-stock line below it is the one that measures concentration in individual names.</p>`}]});
  const SE2 = D.sector_exposure, topSec = SE2 && SE2.sectors ? Object.entries(SE2.sectors).sort((a, b) => b[1].weight - a[1].weight)[0] : null;
  F.help(g('sector-card'), {lead: 'Which industries your money is in, counting the companies inside your funds as well as stocks held directly.',
    sections: topSec && F.isNum(topSec[1].direct) ? [{title: `How ${topSec[0]} adds up`, html: F.flow([{label: 'stocks held directly', value: F.pct(topSec[1].direct)}, {op: '+', label: 'through funds', value: F.pct(topSec[1].weight - topSec[1].direct)}, {op: '=', label: topSec[0], value: F.pct(topSec[1].weight)}]) + '<p>Bonds, cash and funds without sector data are left out of the bars.</p>'}] : []});
  F.help(g('movers-card'), {lead: 'The holdings that moved most today, by percentage, with the dollar change beside each.',
    sections: [{title: 'The stories underneath', html: '<p>Each story is the newest one dated in the last seven days for that symbol. It is context for the move, not a statement of its cause.</p>'}]});
  const topH = rows.length ? [...rows].sort((a, b) => (b.market_value || 0) - (a.market_value || 0)).find(r => F.isNum(r.cost_basis) && F.isNum(r.market_value) && Math.abs(r.market_value - r.cost_basis) >= 1) : null;
  F.help(g('holdings-card'), {lead: 'Every position, largest first. Sort by any column, filter by account, and click a row for details.',
    sections: topH ? [{title: `Unrealized gain or loss, using ${topH.symbol}`, html: F.flow([{label: 'value today', value: F.money(topH.market_value)}, {op: '−', label: 'what you paid', value: F.money(topH.cost_basis)}, {op: '=', label: 'unrealized', value: F.moneyS(topH.market_value - topH.cost_basis)}]) + '<p>Unrealized means on paper: nothing is taxed or locked in until you sell.</p>'}] : []});
  F.help(g('events-card'), {lead: 'Upcoming earnings reports and dividend dates for what you hold.',
    sections: [{title: 'The two kinds of date', html: '<p>An earnings date is when the company reports results; prices often move more than usual around it. An ex-dividend date is the cutoff: own the shares before it to receive the next dividend.</p>'}]});
  if (K && K.total_value) F.help(g('compare-card'), {lead: 'How the total and each holding changed since the last saved snapshot.',
    sections: [{title: 'How the total moved', html: F.flow([{label: `on ${K.since}`, value: F.money(K.total_value.before)}, {op: '+', label: 'change', value: F.moneyS(K.total_value.delta)}, {op: '=', label: 'now', value: F.money(K.total_value.after)}]) + '<p>The change mixes market moves with any deposits, withdrawals or trades in between.</p>'}]});
  // flags
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def build(snapshot: dict) -> str:
    if not isinstance(snapshot, dict) or "totals" not in snapshot:
        raise InvalidInput("input must be a snapshot.py result (a JSON object with totals)")
    return page.render(TITLE, snapshot, BODY, SCRIPT)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            snapshot = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read snapshot JSON: {exc}") from exc
        out = page.write(ns.out, build(snapshot))
        return {"out": str(out), "title": TITLE, "positions": len(snapshot.get("positions") or []), "flags": len(snapshot.get("flags") or []),
                "headlines": len(snapshot.get("headlines") or [])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
