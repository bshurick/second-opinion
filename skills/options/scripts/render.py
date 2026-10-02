#!/usr/bin/env python3
"""Usage: render.py [--in options.json] --out page.html

Turns the options skill's script results (a file, or stdin when ``--in`` is omitted) into one
self-contained interactive HTML page for the Artifact tool. The input is either a bare ``chain.py``
result or an object with these keys::

    {"chain": <chain.py result>,                          # one expiry (required unless term_structure)
     "term_structure": <chain.py --term-structure result>,  # optional
     "greeks": <options.py action greeks result>,           # optional: the contract the user named
     "payoff": <options.py action payoff result>,           # optional: the strategy the user described
     "legs": [...the legs passed to payoff...]}             # optional: shown as the position table

Sections, in the skill template's order: stat tiles (spot, expiry and days, ATM strike and IV,
expected move, IV vs HV, put/call OI, max pain), the expected-move cone as a band, implied versus
realized volatility (the term structure as a line with HV30/HV90 reference lines when
``term_structure`` is present, otherwise bars), the chain as a sortable table with the ATM row
highlighted plus skew and top open interest, the term-structure table, the contract or strategy
(greeks, the legs, the payoff diagram with the zero line, spot and breakevens marked), the
assignment-risk candidates, and the risk notes the template's section 4 lists. Prints
``{"out": path, "title": ..., "symbol": ..., "strikes": n, "payoff": bool}``. Exit 2 on a missing
or malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown
comes from the scripts' JSON; the page formats, sorts and filters. Two curves are drawn from those
numbers rather than read from a series: the expected-move cone is spot × ATM IV × √(t/365) at
intermediate days (the scripts give only the expiry value), and when ``greeks`` is present without
``payoff`` the single-contract payoff is the long leg's intrinsic value minus its price; the page's
note says so. Nothing is fetched at runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

BODY = """
<style>
tr.atm td{background:color-mix(in srgb,var(--s1) 14%,transparent);font-weight:600}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px;margin:0}
.kv dt{color:var(--muted)}.kv dd{margin:0;font-variant-numeric:tabular-nums}
.pill{display:inline-block;border:1px solid var(--grid);border-radius:999px;padding:1px 8px;font-size:11px;color:var(--ink2);margin-left:6px}
.risks{list-style:none;padding:0;margin:0}
.risks li{padding:6px 10px;border-left:3px solid var(--warn);background:var(--surface);border-radius:0 4px 4px 0;margin-bottom:6px;font-size:13px}
.risks li b{font-weight:600;margin-right:6px}
</style>
<h1 id="h1">Options</h1>
<p class="sub" id="sub"></p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<div class="grid2">
  <div class="card" id="cone-card"><h2 id="cone-h">Expected move</h2><p class="sub" id="cone-sub"></p><div id="cone"></div></div>
  <div class="card" id="vol-card"><h2 id="vol-h">Implied vs realized volatility</h2><p class="sub" id="vol-sub"></p><div id="vol"></div></div>
</div>
<section class="card" id="chain-card" hidden><h2 id="chain-h">Chain</h2>
  <p class="sub" id="chain-sub"></p>
  <div class="controls">
    <input id="q" type="search" placeholder="Filter strikes" aria-label="Filter strikes">
    <span class="muted" id="count"></span>
  </div>
  <div class="twrap" id="chain"></div>
</section>
<section class="card" id="ts-card" hidden><h2 id="ts-h">Term structure</h2><p class="sub" id="ts-sub"></p><div class="twrap" id="ts"></div></section>
<section class="card" id="pos-card" hidden><h2 id="pos-h">Contract or strategy</h2><p class="sub">What the position you described makes or loses at expiry across a range of prices.</p>
  <div class="grid2" style="margin-bottom:8px">
    <div><div id="greeks"></div><div id="legs"></div><div id="strategy"></div></div>
    <div><div id="payoff"></div><p class="note" id="payoff-note" style="margin-top:6px"></p></div>
  </div>
</section>
<section class="card" id="assign-card" hidden><h2 id="assign-h">Early-assignment candidates</h2><p class="sub">Short options the buyer might exercise before expiry, and why.</p><div class="twrap" id="assign"></div></section>
<section data-help="none"><h2>Risk notes</h2><p class="sub">Risks this position carries, picked out from the figures on this page.</p><ul class="risks" id="risks"></ul></section>
<p class="note" id="note">Chain quotes are delayed Yahoo data. Black-Scholes greeks, probabilities and the expected move assume European exercise, lognormal prices and constant volatility; the assignment screen is a rule of thumb, not a boundary solve. Max pain is context, never a target. The expected-move cone is drawn as spot × ATM IV × √(days/365) between today and expiry from the chain's spot, ATM IV and days. Options orders cannot be placed through this plugin. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, C = D.chain || null, TS = D.term_structure || null, G = D.greeks || null, P = D.payoff || null;
  const g = id => document.getElementById(id);
  const base = C || TS, sym = base.symbol || '';
  const pct1 = v => F.pct(v, 1), money = v => F.money(v);
  // glossary entries this page needs beyond the shared list (plain words + a link to more)
  Object.assign(F.glossary, {
    "at the money": ["An option whose strike sits closest to the current share price; its implied volatility is the market's headline estimate of movement.", "https://www.investopedia.com/terms/a/atthemoney.asp"],
    "historical volatility": ["How much the share price actually moved over the past 30 or 90 days, annualized; the realized counterpart to implied volatility.", "https://www.investopedia.com/terms/h/historicalvolatility.asp"],
    "put/call ratio": ["Put open interest (or volume) divided by call open interest; above 1 means more downside bets are outstanding than upside ones.", "https://www.investopedia.com/terms/p/putcallratio.asp"],
    "skew": ["How much more implied volatility the out-of-the-money puts carry than the calls; positive skew means downside protection is priced richer.", "https://www.investopedia.com/terms/v/volatility-skew.asp"],
    "straddle": ["A call and a put at the same strike bought together; its price is roughly the move the market expects by expiry.", "https://www.investopedia.com/terms/s/straddle.asp"],
    "strike": ["The price at which an option lets you buy (call) or sell (put) the shares.", "https://www.investopedia.com/terms/s/strikeprice.asp"],
    "bid-ask spread": ["The gap between the best buying and selling quotes; a wide spread is a cost paid on entry and again on exit.", "https://www.investopedia.com/terms/b/bid-askspread.asp"],
    "premium": ["The price of an option, quoted per share; one contract covers 100 shares.", "https://www.investopedia.com/terms/p/premium.asp"],
    "rho": ["How much an option's price changes when interest rates move one percentage point.", "https://www.investopedia.com/terms/r/rho.asp"],
    "in the money": ["An option that would be worth something if exercised now: a call below the share price or a put above it.", "https://www.investopedia.com/terms/i/inthemoney.asp"],
    "greeks": ["Delta, gamma, theta, vega and rho: how an option's price responds to the share price, time, volatility and rates.", "https://www.investopedia.com/terms/g/greeks.asp"],
    "call option": ["The right, not the obligation, to buy 100 shares at the strike until expiry; it gains when the stock rises.", "https://www.investopedia.com/terms/c/calloption.asp"],
    "put option": ["The right, not the obligation, to sell 100 shares at the strike until expiry; it gains when the stock falls.", "https://www.investopedia.com/terms/p/putoption.asp"],
    "time value": ["The part of an option's price above what exercising it now would bring; it shrinks to zero by expiry.", "https://www.investopedia.com/terms/t/timevalue.asp"],
    "intrinsic value": ["What an option would be worth if exercised right now: how far it is in the money, or zero.", "https://www.investopedia.com/terms/i/intrinsicvalue.asp"],
    "spot": ["The current share price.", "https://www.investopedia.com/terms/s/spotprice.asp"],
    "standard deviation": ["A unit of typical movement: prices stay within one standard deviation (1σ) about two thirds of the time and within two (2σ) about 95% of the time.", "https://www.investopedia.com/terms/s/standarddeviation.asp"],
    "expiration date": ["The last day an option can be exercised; after it the contract is settled or expires worthless.", "https://www.investopedia.com/terms/e/expirationdate.asp"],
    "option chain": ["The full list of calls and puts for one expiry, one row per strike, with each contract's quotes.", "https://www.investopedia.com/terms/o/optionchain.asp"],
    "black-scholes": ["The standard formula for pricing an option from the share price, strike, time to expiry, volatility and interest rates.", "https://www.investopedia.com/terms/b/blackscholes.asp"],
    "collateral": ["Cash or shares the broker holds against a short option so the obligation can be met.", "https://www.investopedia.com/terms/c/collateral.asp"],
    "risk-free rate": ["The interest rate on a safe government bill, used as the rate in option pricing.", "https://www.investopedia.com/terms/r/risk-freerate.asp"],
  });
  const T = (key, label) => FA.term(key, label);
  // swap plain labels that a toolkit helper escaped for their glossary-marked versions, then arm the tooltips
  const retag = (root, sel, map) => { root.querySelectorAll(sel).forEach(n => { const h = map[n.textContent.trim()]; if (h) { const sw = n.querySelector('i'); n.innerHTML = (sw ? sw.outerHTML : '') + h; } }); F.armTerms(root); };
  g('h1').textContent = `Options: ${sym}`;
  document.title = `${sym} Options`;
  FA.explain(g('explain'), `<p>This page reads one ${T('option chain')} for ${F.esc(sym)}: every ${T('call option', 'call')} and ${T('put option', 'put')} listed${C ? ` for the ${F.esc(C.expiry)} expiry` : ''}, with the quotes, ${T('implied volatility')} and ${T('open interest')} that Yahoo reports (delayed).</p>
    <p>Start with the tiles: the ${T('expected move')} is the size of price swing the options market is pricing in by expiry, and IV / HV30 says whether options are dear or cheap against how much the stock actually moved lately (${T('historical volatility')}). The cone chart shades the range the price is expected to stay in about two thirds of the time (1σ) and about 95% of the time (2σ); the chain table lists each ${T('strike')} with the ${T('at the money', 'at-the-money')} row highlighted.</p>
    <p>None of this is a forecast: implied volatility is what buyers and sellers are paying today, the ${T('greeks')} come from the ${T('black-scholes')} formula's simplifying assumptions, and a bought option can lose its whole ${T('premium')}.</p>`);
  const src = base.sources || {};
  let sub = C ? `Spot ${money(C.spot)} · expiry ${F.esc(C.expiry)} (${C.days} days)` : `Spot ${money(TS.spot)} · ${TS.rows.length} expiries` + (TS.as_of ? ` as of ${TS.as_of}` : '');
  sub += ` · chain ${src.chain || '—'}` + (C && src.rate ? ` · rate ${pct1(C.rate)} (${src.rate})` : '') + (C && F.isNum(C.dividend_yield) ? ` · dividend yield ${F.pct(C.dividend_yield, 2)}` : '');
  const exps = base.expiries || [];
  if (exps.length) sub += ` · listed expiries: ${exps.slice(0, 8).join(', ')}${exps.length > 8 ? ` +${exps.length - 8} more` : ''}`;
  g('sub').textContent = sub;
  // tiles
  const tiles = [];
  const IV = T('implied volatility', 'IV'), OI = T('open interest', 'OI'), ATM = T('at the money', 'ATM'), HV = n => T('historical volatility', 'HV' + n);
  if (C) {
    tiles.push([T('spot', 'Spot'), money(C.spot), sym]);
    tiles.push([T('expiration date', 'Expiry'), F.esc(C.expiry), `${C.days} days`]);
    tiles.push([`${ATM} ${T('strike')}`, money(C.atm_strike), `${IV} ${pct1(C.atm_iv)}`]);
    tiles.push([T('expected move', 'Expected move'), F.isNum(C.expected_move_1sd) ? '±' + money(C.expected_move_1sd) : '—', `${pct1(C.expected_move_pct)} · ${T('standard deviation', '1σ')} by expiry`]);
    tiles.push([`${IV} / ${HV(30)}`, F.isNum(C.iv_hv_ratio) ? F.num(C.iv_hv_ratio, 2) + '×' : '—', `${HV(30)} ${pct1(C.hv_30)} · ${HV(90)} ${pct1(C.hv_90)}`]);
    tiles.push([`${T('put/call ratio', 'Put/call')} ${OI}`, F.isNum(C.put_call_oi_ratio) ? F.num(C.put_call_oi_ratio, 2) : '—', `volume ${F.isNum(C.put_call_volume_ratio) ? F.num(C.put_call_volume_ratio, 2) : '—'}`]);
    if (F.isNum(C.max_pain)) tiles.push([T('max pain', 'Max pain'), money(C.max_pain), `${OI}-weighted, context only`]);
    const ev = [];
    if (C.next_earnings) ev.push(`earnings ${F.esc(C.next_earnings)}${C.earnings_in_expiry ? ' (inside expiry)' : ''}`);
    if (C.next_ex_dividend) ev.push(`${T('ex-dividend date', 'ex-dividend')} ${F.esc(C.next_ex_dividend)}${C.ex_dividend_in_expiry ? ' (inside expiry)' : ''}`);
    tiles.push(['Events', (C.earnings_in_expiry || C.ex_dividend_in_expiry) ? 'inside expiry' : 'none inside expiry', ev.join(' · ') || 'no dated events']);
  } else {
    tiles.push([T('spot', 'Spot'), money(TS.spot), sym]);
    tiles.push([`Front ${ATM} ${IV}`, pct1(TS.front.atm_iv), `${F.esc(TS.front.expiry)} (${TS.front.days} days)`]);
    tiles.push([`Back ${ATM} ${IV}`, pct1(TS.back.atm_iv), `${F.esc(TS.back.expiry)} (${TS.back.days} days)`]);
    tiles.push([`${IV} slope / 30d`, F.isNum(TS.iv_slope_30d) ? F.pct(TS.iv_slope_30d, 2, true) : '—', `${T('term structure')}: ${F.esc(TS.iv_term_shape || '—')}`]);
  }
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  F.armTerms(g('tiles'));
  g('cone-h').innerHTML = T('expected move', 'Expected move');
  g('vol-h').innerHTML = `${T('implied volatility', 'Implied')} vs ${T('historical volatility', 'realized volatility')}`;
  g('chain-h').innerHTML = T('option chain', 'Chain');
  g('ts-h').innerHTML = T('term structure', 'Term structure');
  g('assign-h').innerHTML = `Early-${T('assignment')} candidates`;
  F.armTerms(document);
  // expected-move cone (drawn from spot, ATM IV, days; see the note)
  if (C && F.isNum(C.atm_iv) && C.days > 0) {
    const n = 12, lo1 = [], hi1 = [], lo2 = [], hi2 = [];
    for (let k = 0; k <= n; k++) { const d = C.days * k / n, m = C.spot * C.atm_iv * Math.sqrt(d / 365); lo1.push([d, C.spot - m]); hi1.push([d, C.spot + m]); lo2.push([d, C.spot - 2 * m]); hi2.push([d, C.spot + 2 * m]); }
    const series = [{name: 'Spot', points: [[0, C.spot], [C.days, C.spot]], color: F.S[0]}];
    if (F.isNum(C.max_pain) && Math.abs(C.max_pain - C.spot) > 0.01 * C.spot) series.push({name: 'Max pain', points: [[0, C.max_pain], [C.days, C.max_pain]], color: F.S[1]});
    F.lines(g('cone'), {series, bands: [{name: '2σ', lo: lo2, hi: hi2, color: F.S[0]}, {name: '1σ', lo: lo1, hi: hi1, color: F.S[0]}], xFmt: x => `${Math.round(x)}d`, yFmt: y => F.money(y, 0), height: 240, aria: 'expected move cone'});
    retag(g('cone'), '.legend span', {'Spot': T('spot', 'Spot'), 'Max pain': T('max pain', 'Max pain')});
    g('cone-sub').innerHTML = `Shaded: ±1σ and ±2σ (one and two ${T('standard deviation', 'standard deviations')}) at ${ATM} ${IV} ${pct1(C.atm_iv)}. By expiry: 1σ ${money(C.spot - C.expected_move_1sd)} – ${money(C.spot + C.expected_move_1sd)}; about a third of the time the stock ends outside the 1σ range.` + (F.isNum(C.max_pain) && Math.abs(C.max_pain - C.spot) <= 0.01 * C.spot ? ` ${T('max pain', 'Max pain')} ${money(C.max_pain)} sits on spot.` : '');
    F.armTerms(g('cone-sub'));
  } else { g('cone-card').hidden = true; }
  // implied vs realized
  const hv30 = C ? C.hv_30 : null, hv90 = C ? C.hv_90 : null;
  if (TS && TS.rows.length) {
    const pts = TS.rows.filter(r => F.isNum(r.atm_iv)).map(r => [r.days, r.atm_iv]);
    const x0 = pts[0][0], x1 = pts[pts.length - 1][0];
    const series = [{name: 'ATM IV', points: pts, color: F.S[0]}];
    if (F.isNum(hv30)) series.push({name: 'HV30', points: [[x0, hv30], [x1, hv30]], color: F.S[2]});
    if (F.isNum(hv90)) series.push({name: 'HV90', points: [[x0, hv90], [x1, hv90]], color: F.S[3]});
    F.lines(g('vol'), {series, xFmt: x => `${Math.round(x)}d`, yFmt: y => F.pct(y, 0), height: 240, yMin: 0, aria: 'IV term structure vs realized volatility'});
    retag(g('vol'), '.legend span', {'ATM IV': `${ATM} ${IV}`, 'HV30': HV(30), 'HV90': HV(90)});
    g('vol-sub').innerHTML = `${ATM} ${IV} by days to expiry (${T('term structure')}: ${F.esc(TS.iv_term_shape || '—')}, ${F.isNum(TS.iv_slope_30d) ? F.pct(TS.iv_slope_30d, 2, true) : '—'} per 30 days)` + (F.isNum(hv30) ? `; realized ${HV(30)} ${pct1(hv30)}, ${HV(90)} ${pct1(hv90)} as flat reference lines.` : '; no price history for HV.');
    F.armTerms(g('vol-sub'));
  } else if (C) {
    const rows = [['ATM IV', C.atm_iv, F.S[0]], ['HV30', hv30, F.S[2]], ['HV90', hv90, F.S[3]]].filter(r => F.isNum(r[1]));
    if (rows.length) { F.bars(g('vol'), rows.map(([label, v, color]) => ({label, share: v, color, text: pct1(v)}))); retag(g('vol'), '.bar .l', {'ATM IV': `${ATM} ${IV}`, 'HV30': HV(30), 'HV90': HV(90)}); } else g('vol').innerHTML = '<span class="muted">no volatility data</span>';
    g('vol-sub').innerHTML = F.isNum(C.iv_hv_ratio) ? `${IV}/${T('historical volatility', 'HV')} ${F.num(C.iv_hv_ratio, 2)}: ${C.iv_hv_ratio > 1.2 ? 'options are priced richer than recent realized movement' : C.iv_hv_ratio < 0.8 ? 'options are priced below recent realized movement' : 'implied and realized are close'} (run --term-structure for IV by expiry).` : 'No price history: HV unavailable (run without --no-history).';
    F.armTerms(g('vol-sub'));
  } else { g('vol-card').hidden = true; }
  // chain table
  if (C && Array.isArray(C.strikes) && C.strikes.length) {
    g('chain-card').hidden = false;
    const rows = C.strikes.map(s => { const c = s.call || {}, p = s.put || {}; return {strike: s.strike, c_bid: c.bid, c_ask: c.ask, c_mid: c.mid, c_iv: c.iv, c_delta: c.delta, c_oi: c.open_interest, c_spread: c.spread_pct, p_bid: p.bid, p_ask: p.ask, p_mid: p.mid, p_iv: p.iv, p_delta: p.delta, p_oi: p.open_interest, p_spread: p.spread_pct}; });
    const cols = [
      {key: 'strike', label: 'Strike', left: true, fmt: (v, r) => `<b>${money(v)}</b>${v === C.atm_strike ? '<span class="pill">ATM</span>' : ''}`},
      {key: 'c_bid', label: 'Call bid', fmt: money}, {key: 'c_ask', label: 'Call ask', fmt: money},
      {key: 'c_iv', label: 'Call IV', fmt: pct1}, {key: 'c_delta', label: 'Call Δ', fmt: v => F.isNum(v) ? F.num(v, 2) : '—'}, {key: 'c_oi', label: 'Call OI', fmt: v => F.num(v, 0)},
      {key: 'p_bid', label: 'Put bid', fmt: money}, {key: 'p_ask', label: 'Put ask', fmt: money},
      {key: 'p_iv', label: 'Put IV', fmt: pct1}, {key: 'p_delta', label: 'Put Δ', fmt: v => F.isNum(v) ? F.num(v, 2) : '—'}, {key: 'p_oi', label: 'Put OI', fmt: v => F.num(v, 0)},
    ];
    const heads = {'Strike': T('strike', 'Strike'), 'Call bid': T('bid-ask spread', 'Call bid'), 'Call ask': T('bid-ask spread', 'Call ask'), 'Call IV': T('implied volatility', 'Call IV'), 'Call Δ': T('delta', 'Call Δ'), 'Call OI': T('open interest', 'Call OI'),
      'Put bid': T('bid-ask spread', 'Put bid'), 'Put ask': T('bid-ask spread', 'Put ask'), 'Put IV': T('implied volatility', 'Put IV'), 'Put Δ': T('delta', 'Put Δ'), 'Put OI': T('open interest', 'Put OI')};
    const tbl = F.table(g('chain'), cols, rows, {sortKey: 'strike', desc: false, onDraw: vis => {
      g('count').textContent = `${vis.length} of ${rows.length} strikes`;
      g('chain').querySelectorAll('tbody tr').forEach((tr, i) => { if (vis[i] && vis[i].strike === C.atm_strike) tr.classList.add('atm'); });
      F.armTerms(g('chain'));
    }});
    retag(g('chain'), 'thead th', heads);
    g('q').addEventListener('input', e => tbl.setQuery(e.target.value));
    const sk = C.skew, top = C.top_open_interest || [];
    let line = sk ? `${T('skew', 'Skew')}: put ${money(sk.otm_put_strike)} ${IV} ${pct1(sk.otm_put_iv)} vs call ${money(sk.otm_call_strike)} ${IV} ${pct1(sk.otm_call_iv)} (put − call ${F.isNum(sk.put_minus_call) ? F.pct(sk.put_minus_call, 1, true) : '—'}).` : `${T('skew', 'Skew')}: —.`;
    if (top.length) line += ` Top ${T('open interest')}: ${top.map(t => `${F.esc(t.type)} ${money(t.strike)} (${F.num(t.open_interest, 0)})`).join(', ')}.`;
    g('chain-sub').innerHTML = line;
    F.armTerms(g('chain-sub'));
  }
  // term-structure table
  if (TS && TS.rows.length) {
    g('ts-card').hidden = false;
    g('ts').innerHTML = `<table><thead><tr><th class="l">${T('expiration date', 'Expiry')}</th><th>Days</th><th>${ATM} ${T('strike')}</th><th>${ATM} ${IV}</th><th>${ATM} ${T('straddle')}</th><th>${IV} move %</th><th>${T('straddle', 'Straddle')} move %</th><th>Put ${T('skew')}</th></tr></thead><tbody>` +
      TS.rows.map(r => `<tr><td class="l">${F.esc(r.expiry)}</td><td>${r.days}</td><td>${money(r.atm_strike)}</td><td>${pct1(r.atm_iv)}</td><td>${money(r.atm_straddle)}</td><td>${pct1(r.iv_move_pct)}</td><td>${pct1(r.straddle_move_pct)}</td><td>${F.isNum(r.put_skew) ? F.pct(r.put_skew, 1, true) : '—'}</td></tr>`).join('') + '</tbody></table>';
    g('ts-sub').innerHTML = `How ${IV} changes with the expiry date: slope ${F.isNum(TS.iv_slope_30d) ? F.pct(TS.iv_slope_30d, 2, true) : '—'} per 30 days (${F.esc(TS.iv_term_shape || '—')}) · ${T('skew')} slope ${F.isNum(TS.skew_slope_30d) ? F.pct(TS.skew_slope_30d, 2, true) : '—'} per 30 days · the straddle move is 0.85 × the ${ATM} ${T('straddle')} price.`;
    F.armTerms(g('ts-card'));
  }
  // contract / strategy
  const legs = Array.isArray(D.legs) ? D.legs : [];
  if (G || P) {
    g('pos-card').hidden = false;
    const optT = t => t === 'call' ? T('call option', 'call') : t === 'put' ? T('put option', 'put') : F.esc(t);
    g('pos-h').innerHTML = P ? `Strategy: ${F.esc(P.strategy)}` : `Contract: ${F.esc(sym)} ${money(G.strike)} ${optT(G.type)}`;
    if (G) {
      const ea = G.early_assignment || {};
      g('greeks').innerHTML = `<dl class="kv">
        <dt>Contract</dt><dd>${optT(G.type)} ${money(G.strike)} ${T('strike')} · ${G.days} days</dd>
        <dt>${T('premium', 'Price')}</dt><dd>${money(G.price)} per share (${money(G.price * 100)} per contract)</dd>
        <dt>${IV}</dt><dd>${pct1(G.iv)} <span class="muted">(${F.esc(G.iv_source)})</span></dd>
        <dt>${T('delta', 'Δ')} · ${T('gamma', 'Γ')}</dt><dd>${F.num(G.delta, 3)} · ${F.num(G.gamma, 4)}</dd>
        <dt>${T('theta', 'Θ')} / day</dt><dd>${F.isNum(G.theta) ? F.moneyS(G.theta * 100) : '—'} per contract</dd>
        <dt>${T('vega', 'Vega')} · ${T('rho', 'Rho')}</dt><dd>${F.num(G.vega, 4)} · ${F.num(G.rho, 4)} per point</dd>
        <dt>Prob ${T('in the money', 'ITM')}</dt><dd>${pct1(G.prob_itm)}</dd>
        <dt>${T('breakeven', 'Breakeven')}</dt><dd>${money(G.breakeven)}</dd>
        <dt>Early ${T('assignment')}</dt><dd>${ea.plausible ? '<b>plausible</b> — ' + F.esc((ea.reasons || []).join('; ')) : (ea.deep_itm ? 'deep ITM, not plausible yet' : 'not plausible')} <span class="muted">(${T('time value')} ${F.num(ea.time_value, 2)}, exercise gain ${F.num(ea.exercise_gain, 2)})</span></dd>
      </dl>`;
    }
    if (legs.length) g('legs').innerHTML = `<div class="twrap" style="margin-top:10px"><table><thead><tr><th class="l">Leg</th><th>Side</th><th>${T('strike', 'Strike')}</th><th>${T('premium', 'Premium')}</th><th>Qty</th></tr></thead><tbody>` + legs.map(l => `<tr><td class="l">${optT(l.type)}</td><td>${F.esc(l.side || 'long')}</td><td>${l.type === 'stock' ? money(l.price) : money(l.strike)}</td><td>${l.type === 'stock' ? '—' : money(l.premium)}</td><td>${F.num(l.qty ?? (l.type === 'stock' ? 100 : 1), 0)}</td></tr>`).join('') + '</tbody></table></div>';
    if (P) {
      const be = (P.breakevens || []).map(money).join(', ') || '—';
      g('strategy').innerHTML = `<dl class="kv" style="margin-top:10px">
        <dt>Net ${T('premium')}</dt><dd class="${F.cls(P.net_premium)}">${F.moneyS(P.net_premium)} <span class="muted">(${P.net_premium > 0 ? 'credit: cash received' : P.net_premium < 0 ? 'debit: cash paid' : 'even'})</span></dd>
        <dt>${T('collateral', 'Collateral')}</dt><dd>${F.isNum(P.collateral) ? money(P.collateral) : '—'}</dd>
        <dt>${T('breakeven', 'Breakevens')}</dt><dd>${be}</dd>
        <dt>Max profit</dt><dd class="pos">${P.unlimited_profit ? 'unlimited' : F.moneyS(P.max_profit)}</dd>
        <dt>Max loss</dt><dd class="neg">${P.unlimited_loss ? 'unlimited' : F.moneyS(P.max_loss)}</dd>
        <dt>Prob profit</dt><dd>${pct1(P.prob_profit)}${F.isNum(P.expected_move_1sd) ? ` <span class="muted">(${T('standard deviation', '1σ')} move ±${money(P.expected_move_1sd)})</span>` : ''}</dd>
      </dl>`;
    }
    F.armTerms(g('pos-card'));
    // payoff diagram
    let grid = P ? (P.grid || []).map(r => [r.price, r.pnl]) : [], bes = P ? (P.breakevens || []) : [], spot = P ? P.spot : G.spot, note;
    if (P) note = 'Payoff at expiry from the payoff script’s grid (per position, contracts × 100).';
    else {
      const lo = Math.max(0, spot * 0.5), hi = spot * 1.5, pts = new Set([lo, hi, G.strike, spot, G.breakeven]);
      for (let x = lo; x <= hi; x += spot * 0.01) pts.add(Math.round(x * 100) / 100);
      grid = [...pts].sort((a, b) => a - b).map(s => [s, 100 * ((G.type === 'call' ? Math.max(s - G.strike, 0) : Math.max(G.strike - s, 0)) - G.price)]);
      bes = [G.breakeven];
      note = 'Payoff at expiry for one long contract, drawn on this page as intrinsic value minus the contract price (the greeks script gives no series); a short position is the mirror image.';
    }
    g('payoff-note').textContent = note;
    payoffChart(g('payoff'), grid, bes, spot);
  }
  function payoffChart(root, pts, bes, spot) {
    pts = pts.filter(p => F.isNum(p[0]) && F.isNum(p[1]));
    if (!pts.length) { root.innerHTML = '<span class="muted">no payoff grid</span>'; return; }
    const W = 960, H = 260, m = {t: 14, r: 24, b: 30, l: 64}, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs); let y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys); if (y1 === y0) y1 = y0 + 1; const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
    const X = x => m.l + iw * (x - x0) / (x1 - x0), Y = y => m.t + ih * (1 - (y - y0) / (y1 - y0));
    const path = pts.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('');
    const clip = (fn) => pts.map(p => [p[0], fn(p[1])]);
    const area = (arr, color) => `<path d="${arr.map((p, i) => (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('')}L${X(arr[arr.length - 1][0]).toFixed(1)} ${Y(0).toFixed(1)}L${X(arr[0][0]).toFixed(1)} ${Y(0).toFixed(1)}Z" fill="${color}" opacity="0.14"/>`;
    const ticks = []; for (let k = 0; k <= 4; k++) ticks.push(y0 + (y1 - y0) * k / 4);
    const xt = []; for (let k = 0; k <= 5; k++) xt.push(x0 + (x1 - x0) * k / 5);
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="payoff at expiry">`;
    s += ticks.map(t => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="var(--grid)"/><text x="${m.l - 8}" y="${(Y(t) + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${F.esc(F.money(t, 0))}</text>`).join('');
    s += xt.map(t => `<text x="${X(t).toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${F.esc(F.money(t, 0))}</text>`).join('');
    s += area(clip(v => Math.max(v, 0)), 'var(--up)') + area(clip(v => Math.min(v, 0)), 'var(--down)');
    s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="var(--ink2)" stroke-dasharray="2 3"/>`;
    if (F.isNum(spot) && spot >= x0 && spot <= x1) s += `<line x1="${X(spot).toFixed(1)}" x2="${X(spot).toFixed(1)}" y1="${m.t}" y2="${m.t + ih}" stroke="var(--s1)" stroke-dasharray="4 3"/><text x="${(X(spot) + 4).toFixed(1)}" y="${m.t + 12}" font-size="11" fill="var(--ink2)">spot ${F.esc(F.money(spot))}</text>`;
    bes.filter(b => F.isNum(b) && b >= x0 && b <= x1).forEach((b, i) => { s += `<line x1="${X(b).toFixed(1)}" x2="${X(b).toFixed(1)}" y1="${m.t}" y2="${m.t + ih}" stroke="var(--muted)"/><text x="${(X(b) + 4).toFixed(1)}" y="${m.t + ih - 6 - 14 * (i % 2)}" font-size="11" fill="var(--ink2)">BE ${F.esc(F.money(b))}</text>`; });
    s += `<path d="${path}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round"/>`;
    s += `<line id="pcx" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="var(--muted)" stroke-dasharray="3 3" opacity="0"/><rect id="phit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
    root.innerHTML = s;
    const svg = root.querySelector('svg'), hit = svg.querySelector('#phit'), cx = svg.querySelector('#pcx');
    hit.addEventListener('mousemove', ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) * W / r.width; const xv = x0 + (px - m.l) / iw * (x1 - x0);
      let best = pts[0]; for (const p of pts) if (Math.abs(p[0] - xv) < Math.abs(best[0] - xv)) best = p;
      cx.setAttribute('x1', px); cx.setAttribute('x2', px); cx.setAttribute('opacity', 1);
      F.tip.show(ev, `<div style="color:var(--ink2)">at ${F.esc(F.money(best[0]))}</div><b class="${F.cls(best[1])}">${F.esc(F.moneyS(best[1]))}</b>`); });
    hit.addEventListener('mouseleave', () => { cx.setAttribute('opacity', 0); F.tip.hide(); });
  }
  // assignment candidates
  const cands = C ? (C.assignment_candidates || []) : [];
  if (cands.length) {
    g('assign-card').hidden = false;
    g('assign').innerHTML = `<table><thead><tr><th class="l">Type</th><th>${T('strike', 'Strike')}</th><th>Mid</th><th>${T('time value', 'Time value')}</th><th>Exercise gain</th><th>${T('ex-dividend date', 'Ex-div')} in</th><th class="l">Reasons</th></tr></thead><tbody>` +
      cands.map(c => `<tr><td class="l">${F.esc(c.type)}</td><td>${money(c.strike)}</td><td>${money(c.mid)}</td><td>${F.num(c.time_value, 2)}</td><td>${F.num(c.exercise_gain, 2)}</td><td>${F.isNum(c.ex_dividend_days) ? c.ex_dividend_days + ' days' : '—'}</td><td class="l" style="white-space:normal;min-width:260px">${F.esc((c.reasons || []).join('; '))}</td></tr>`).join('') + '</tbody></table>';
    F.armTerms(g('assign'));
  }
  // risk notes (the template's section 4)
  const risks = [];
  const longOpt = legs.some(l => l.type !== 'stock' && (l.side || 'long') === 'long') || (G && !legs.length);
  const shortOpt = legs.filter(l => l.type !== 'stock' && l.side === 'short');
  if (longOpt) risks.push(['PREMIUM', 'A long option can expire worthless: the full premium paid is at risk.']);
  if (shortOpt.length) risks.push(['ASSIGNMENT', `Short options can be assigned at any time before expiry (${shortOpt.map(l => `${l.type} ${money(l.strike)}`).join(', ')}).`]);
  if (P && P.unlimited_loss) risks.push(['UNLIMITED_LOSS', 'The position loses without limit above the highest strike (uncovered short call exposure).']);
  if (cands.length) risks.push(['EARLY_ASSIGNMENT', `${cands.length} deep-ITM contract${cands.length > 1 ? 's' : ''} where early exercise is plausible: ${cands.map(c => `${c.type} ${money(c.strike)}`).join(', ')}.`]);
  if (G && G.early_assignment && G.early_assignment.plausible) risks.push(['EARLY_ASSIGNMENT', `The ${money(G.strike)} ${G.type} screens as plausible for early exercise: ${G.early_assignment.reasons.join('; ')}.`]);
  if (C) {
    const wide = [];
    for (const s of C.strikes || []) for (const k of ['call', 'put']) { const q = s[k]; if (q && F.isNum(q.spread_pct) && q.spread_pct > 0.10) wide.push(`${k} ${money(s.strike)} (${pct1(q.spread_pct)})`); }
    if (wide.length) risks.push(['WIDE_SPREADS', `Bid/ask wider than 10% of mid on ${wide.length} quote${wide.length > 1 ? 's' : ''}: ${wide.slice(0, 6).join(', ')}${wide.length > 6 ? ', …' : ''}.`]);
    if (C.earnings_in_expiry) risks.push(['EARNINGS', `Earnings ${C.next_earnings} fall inside the expiry; implied volatility usually drops after the report.`]);
    if (C.ex_dividend_in_expiry) risks.push(['EX_DIVIDEND', `Ex-dividend ${C.next_ex_dividend} falls inside the expiry (${C.ex_dividend_days ?? '—'} days); deep-ITM calls may be exercised the day before.`]);
  }
  // card help
  const help = (id, spec) => { const c = g(id); if (c && !c.hidden) F.help(c, spec); };
  if (C) {
    help('cone-card', {lead: 'How far the price could plausibly move by expiry, as the option prices themselves imply.',
      sections: F.isNum(C.atm_iv) && F.isNum(C.days) ? [{title: 'How the move is worked out', html: F.flow([{label: 'price', value: money(C.spot)}, {op: '×', label: 'implied volatility', value: pct1(C.atm_iv)}, {op: '×', label: `√(${C.days} days ÷ 365)`, value: F.num(Math.sqrt(C.days / 365), 3)}, {op: '=', label: 'one standard deviation', value: '±' + money(C.expected_move_1sd)}]) +
        '<p>About two times in three the price ends inside one standard deviation, and about 19 in 20 inside two, if moves follow a bell curve. Real prices jump more often than that.</p>'}] : []});
    help('vol-card', {lead: 'Whether options are priced for bigger or smaller swings than the stock has actually had lately.',
      sections: F.isNum(C.atm_iv) && F.isNum(C.hv_30) ? [{title: 'Implied against realized', html: F.flow([{label: 'implied (from option prices)', value: pct1(C.atm_iv)}, {op: '÷', label: 'realized, last 30 days', value: pct1(C.hv_30)}, {op: '=', label: 'ratio', value: F.num(C.iv_hv_ratio ?? C.atm_iv / C.hv_30, 2)}]) +
        '<p>Above 1 means options cost more than recent swings would justify; below 1, less. Ahead of earnings the ratio usually rises.</p>'}] : []});
    help('chain-card', {lead: 'Every call and put for one expiry, with prices, volume and open contracts at each strike.',
      sections: [{title: 'Reading it', html: `<p>A call pays when the price ends above its strike; a put when it ends below. Open interest is how many contracts are still open. Max pain (${money(C.max_pain)}) is the strike where option holders as a group would collect the least at expiry.</p>`}]});
    if ((C.assignment_candidates || []).length) help('assign-card', {lead: 'Short options at risk of being exercised early by the buyer.',
      sections: [{title: 'Why early exercise happens', html: '<p>An option deep in the money with almost no time value left is worth little more than exercising it now, and just before an ex-dividend date a call holder may exercise to collect the dividend.</p>'}]}); }
  if (TS) help('ts-card', {lead: 'Implied volatility across expiries, from the nearest to the farthest.',
    sections: [{title: 'Reading the shape', html: '<p>Rising with time is the usual shape. Falling, with the nearest expiry priced highest, usually means an event such as earnings sits inside it.</p>'}]});
  if (P) help('pos-card', {lead: 'What the position makes or loses at expiry across a range of prices.',
    sections: [{title: 'The key numbers', html: `<p><b>Most it can make:</b> ${P.unlimited_profit ? 'no limit' : money(P.max_profit)}. <b>Most it can lose:</b> ${P.unlimited_loss ? 'no limit' : money(P.max_loss)}. <b>Chance of a profit at expiry:</b> ${pct1(P.prob_profit)}.</p>` +
      '<p>The chance of profit comes from the implied volatility and assumes a bell curve; breakevens are where the line crosses zero.</p>'}]});
  g('risks').innerHTML = risks.length ? risks.map(([c, m]) => `<li><b>${c}</b>${F.esc(m)}</li>`).join('') : '<li class="muted">None flagged by the data shown</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _normalize(data: object) -> dict:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a chain.py result, or an object with chain and optional term_structure, greeks, payoff, legs")
    if "strikes" in data and "spot" in data:
        data = {"chain": data}
    elif "rows" in data and "iv_slope_30d" in data:
        data = {"term_structure": data}
    chain, ts = data.get("chain"), data.get("term_structure")
    has_chain = isinstance(chain, dict) and isinstance(chain.get("strikes"), list)
    has_ts = isinstance(ts, dict) and isinstance(ts.get("rows"), list)
    if not has_chain and not has_ts:
        raise InvalidInput("input must be a chain.py result, or an object with chain (a chain.py result) or term_structure (chain.py --term-structure) and optional greeks, payoff, legs")
    return data


def build(data: dict) -> tuple[str, str, dict]:
    data = _normalize(data)
    base = data.get("chain") or data.get("term_structure")
    symbol = str(base.get("symbol") or "")
    title = f"{symbol} Options".strip()
    markup = page.render(title, data, BODY, SCRIPT)
    info = {"title": title, "symbol": symbol or None, "strikes": len((data.get("chain") or {}).get("strikes") or []), "payoff": isinstance(data.get("payoff"), dict)}
    return title, markup, info


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read options JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
