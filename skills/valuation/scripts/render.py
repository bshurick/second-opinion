#!/usr/bin/env python3
"""Usage: render.py [--in valuation.json] --out page.html

Turns the valuation skill's script results (a file, or stdin when ``--in`` is omitted) into one
self-contained interactive HTML page for the Artifact tool. The skill has no single combined script,
so the input is an object that collects whichever results ran; every key is optional but at least one
of ``dcf``, ``intrinsic``, ``comps``, ``ddm`` must be present::

    {"symbol": "ACME",                    # shown in the title
     "price": 12.0,                       # current share price; falls back to intrinsic.inputs.price
                                          # or dcf.implied.current_share_price
     "dcf": <dcf.py result>,              # the base DCF (inputs.py-fed, or buffett.dcf_input)
     "dcf_owner_earnings": <dcf.py result on intrinsic's buffett.dcf_input>,
     "dcf_mid_cycle": <dcf.py result on intrinsic's normalized.dcf_input_mid_cycle>,
     "intrinsic": <intrinsic.py result>,
     "comps": <comps.py result>,
     "ddm": <ddm.py result>}

A bare ``dcf.py`` or ``intrinsic.py`` result is accepted and wrapped. Sections: stat tiles (price,
DCF fair value, Graham number, growth-formula value, mid-cycle DCF, owner-earnings DCF, comps
median, DDM value), the margin of safety per method as bars (discount to price, negative in the loss
colour), the DCF block with the WACC × terminal-growth sensitivity grid as a heatmap coloured around
the current price with the base case outlined, the Graham defensive checklist and Buffett tenets as
pass/fail lists with the per-share figures, owner earnings by year, the normalized (mid-cycle) block,
the comps table, the DDM table with its own sensitivity grid, the flags, and a closing note. Prints
``{"out": path, "title": ..., "symbol": ..., "methods": [...], "flags": n}``. Exit 2 on a missing or
malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every figure comes from
the scripts' JSON; the page formats and sorts. The one derived ratio is the discount to price for the
DCF, comps and DDM values (1 - price / value, the same arithmetic ``intrinsic.py`` prints for its own
margin_of_safety rows); the note says so. Nothing is fetched at runtime.
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
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px;margin:0 0 10px}
.kv dt{color:var(--muted)}.kv dd{margin:0;font-variant-numeric:tabular-nums}
.checks{list-style:none;padding:0;margin:0}
.checks li{display:grid;grid-template-columns:52px 1fr;gap:8px;padding:5px 0;border-bottom:1px solid var(--grid);font-size:13px;align-items:start}
.checks .st{font-size:11px;font-weight:600;letter-spacing:.04em;border-radius:4px;padding:2px 0;text-align:center;border:1px solid var(--grid)}
.checks .st.pass{color:var(--ink);border-color:var(--ink2)}.checks .st.fail{color:var(--warn);border-color:var(--warn)}.checks .st.na{color:var(--muted)}
.checks .t{color:var(--muted);font-size:12px}
.legend .sw{width:14px;height:10px;border-radius:2px;display:inline-block}
</style>
<h1 id="h1">Valuation</h1>
<p class="sub" id="sub"></p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<section class="card" id="mos-card"><h2 id="mos-h">Margin of safety by method</h2><p class="sub" id="mos-sub"></p><div id="mos"></div></section>
<section class="card" id="dcf-card" hidden><h2 id="dcf-h">Discounted cash flow</h2><p class="sub">What one share is worth if the business produces the cash in the forecast, counted in today’s money.</p>
  <div class="grid2" style="margin-bottom:8px"><div><dl class="kv" id="dcf-kv"></dl></div><div><p class="sub" id="dcf-grid-sub"></p><div id="dcf-grid"></div><div class="legend" id="dcf-legend"></div></div></div>
</section>
<div class="grid2" id="alt-dcf" hidden>
  <div class="card" id="oe-card" hidden><h2 id="oe-h">Owner-earnings DCF</h2><p class="sub">The same method starting from owner earnings: the cash an owner could take out without shrinking the business.</p><dl class="kv" id="oe-kv"></dl><div id="oe-grid"></div></div>
  <div class="card" id="mid-card" hidden><h2 id="mid-h">Mid-cycle DCF</h2><p class="sub">The same method starting from a ten-year average, so one unusual year does not set the value.</p><dl class="kv" id="mid-kv"></dl><div id="mid-grid"></div></div>
</div>
<div class="grid2" id="checklists" hidden>
  <div class="card"><h2 id="graham-h">Graham defensive checklist</h2><p class="sub" id="graham-sub"></p><ul class="checks" id="graham"></ul><dl class="kv" id="graham-kv" style="margin-top:12px"></dl></div>
  <div class="card"><h2 id="buffett-h">Buffett tenets</h2><p class="sub" id="buffett-sub"></p><ul class="checks" id="buffett"></ul><dl class="kv" id="buffett-kv" style="margin-top:12px"></dl></div>
</div>
<div class="grid2" id="oe-row" hidden>
  <div class="card"><h2 id="oe-chart-h">Owner earnings by year</h2><p class="sub" id="oe-sub"></p><div id="oe-chart"></div></div>
  <div class="card"><h2 id="norm-h">Normalized (mid-cycle) earnings</h2><p class="sub" id="norm-sub"></p><dl class="kv" id="norm"></dl></div>
</div>
<section class="card" id="type-card" hidden><h2 id="type-h"></h2><p class="sub">A yardstick that suits this kind of company better than the cash-flow value.</p><dl class="kv" id="type-kv"></dl></section>
<section class="card" id="comps-card" hidden><h2 id="comps-h">Comparable multiples</h2><p class="sub" id="comps-sub"></p><div class="twrap" id="comps"></div></section>
<section class="card" id="ddm-card" hidden><h2 id="ddm-h">Dividend discount model</h2><p class="sub">What a share is worth as the stream of future dividends, counted in today’s money.</p>
  <div class="grid2" style="margin-bottom:8px"><div><dl class="kv" id="ddm-kv"></dl></div><div><p class="sub" id="ddm-grid-sub"></p><div id="ddm-grid"></div></div></div>
</section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note" id="note">Every value is the scripts' output at the stated assumptions; a DCF reflects a set of assumptions about the future and is not a guarantee of market price convergence. The Graham number and growth formula are ceilings under their assumptions, margin-of-safety bands are description, not a signal. Discounts for the DCF, comps and DDM rows are 1 − price / value from the scripts' values. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, I = D.intrinsic || null, X = D.dcf || null, OE = D.dcf_owner_earnings || null, MID = D.dcf_mid_cycle || null, CO = D.comps || null, DD = D.ddm || null;
  const g = id => document.getElementById(id);
  const sym = D.symbol || '';
  const price = F.isNum(D.price) ? D.price : (I && F.isNum(I.inputs.price)) ? I.inputs.price : (X && X.implied && F.isNum(X.implied.current_share_price)) ? X.implied.current_share_price : null;
  const bigN = v => F.isNum(v) ? F.moneyC(v).replace('$', '') : '—';
  const money = v => F.money(v), pct1 = v => F.pct(v, 1), pct2 = v => F.pct(v, 2);
  const disc = v => (F.isNum(price) && F.isNum(v) && v > 0) ? 1 - price / v : null;
  // an estimate against the price in words: "15% below price", "price is 2.3× this", "40% above price"
  const gapText = v => !(F.isNum(price) && F.isNum(v) && v > 0) ? '' : v >= price ? `${F.pct(v / price - 1, 0)} above price` : (price / v >= 2 ? `price is ${F.num(price / v, 1)}× this` : `${F.pct(1 - v / price, 0)} below price`);
  const label = {graham_number: 'Graham number', graham_number_10y: 'Graham number (10y EPS)', graham_growth_formula: 'Graham growth formula', ncav: 'Net current asset value', dcf: 'DCF fair value', dcf_owner_earnings: 'Owner-earnings DCF', dcf_mid_cycle: 'Mid-cycle DCF', comps: 'Comps (median implied)', ddm: 'Dividend discount'};
  // glossary entries this page needs beyond the shared list (plain words + a link to more)
  Object.assign(F.glossary, {
    "fair value": ["An estimate of what a share is worth from its expected cash flows or comparable companies, as opposed to what it trades for today.", "https://www.investopedia.com/terms/f/fairvalue.asp"],
    "intrinsic value": ["What a business is worth on its own fundamentals, independent of its market price.", "https://www.investopedia.com/terms/i/intrinsicvalue.asp"],
    "enterprise value": ["What it would cost to buy the whole business: market value of the shares plus debt, minus cash.", "https://www.investopedia.com/terms/e/enterprisevalue.asp"],
    "net debt": ["Total borrowings minus cash on hand; subtracted from enterprise value to get what belongs to shareholders.", "https://www.investopedia.com/terms/n/netdebt.asp"],
    "shares outstanding": ["The number of shares investors hold; value per share is the equity value divided by this.", "https://www.investopedia.com/terms/o/outstandingshares.asp"],
    "eps": ["Earnings per share: annual profit divided by the share count.", "https://www.investopedia.com/terms/e/eps.asp"],
    "book value": ["Assets minus liabilities from the balance sheet, here per share; what accountants say the company is worth.", "https://www.investopedia.com/terms/b/bookvalue.asp"],
    "discount rate": ["The yearly return used to shrink future cash to today's value; a higher rate means future money counts for less.", "https://www.investopedia.com/terms/d/discountrate.asp"],
    "present value": ["What a future sum is worth today after shrinking it by the discount rate for each year of waiting.", "https://www.investopedia.com/terms/p/presentvalue.asp"],
    "sensitivity analysis": ["Re-running a valuation with slightly different assumptions to see how much the answer moves.", "https://www.investopedia.com/terms/s/sensitivityanalysis.asp"],
    "comparable company analysis": ["Valuing a company by applying the price multiples its peers trade at to its own earnings, sales or book value.", "https://www.investopedia.com/terms/c/comparable-company-analysis-cca.asp"],
    "multiple": ["A price ratio such as P/E or EV/EBITDA that says how many dollars the market pays per dollar of earnings, sales or assets.", "https://www.investopedia.com/terms/m/multiple.asp"],
    "p/s": ["Price divided by sales per share; useful when there is no profit to measure.", "https://www.investopedia.com/terms/p/price-to-salesratio.asp"],
    "ev/sales": ["Enterprise value divided by revenue, a debt-aware version of price-to-sales.", "https://www.investopedia.com/terms/e/enterprisevaluesales.asp"],
    "fcf yield": ["Free cash flow per share divided by the price; higher means more cash per dollar paid.", "https://www.investopedia.com/terms/f/freecashflowyield.asp"],
    "required rate of return": ["The yearly return an investor demands for holding the stock; in a dividend model it is the discount rate.", "https://www.investopedia.com/terms/r/requiredrateofreturn.asp"],
    "gordon growth model": ["The simplest dividend model: value = next year's dividend divided by (required return minus growth).", "https://www.investopedia.com/terms/g/gordongrowthmodel.asp"],
    "capital expenditure": ["Capex: money spent on buildings, equipment and other long-lived assets; the maintenance part keeps the business running as is.", "https://www.investopedia.com/terms/c/capitalexpenditure.asp"],
    "depreciation and amortization": ["D&A: the yearly accounting charge that spreads the cost of past purchases over their useful life; no cash leaves when it is booked.", "https://www.investopedia.com/terms/d/depreciation.asp"],
    "normalized earnings": ["Earnings averaged over a full business cycle (here up to ten years) so one unusually good or bad year does not set the value.", "https://www.investopedia.com/terms/n/normalizedearnings.asp"],
    "net-net": ["Graham's deep-value test: buying below two thirds of net current asset value, roughly what a liquidation would fetch.", "https://www.investopedia.com/terms/n/net-net.asp"],
    "graham growth formula": ["Benjamin Graham's shortcut: value = EPS × (8.5 + 2 × expected growth) × 4.4 ÷ the AAA bond yield.", "https://www.investopedia.com/terms/b/benjamin-method.asp"],
    "aaa yield": ["The interest rate on the safest corporate bonds; the Graham growth formula uses it to adjust for today's rates.", "https://www.investopedia.com/terms/a/aaa.asp"],
    "defensive investor": ["Graham's cautious investor, who buys only large, stable, long-dividend-paying companies at modest prices.", "https://www.investopedia.com/terms/d/defensiveinvestmentstrategy.asp"],
    "net income": ["Profit after all costs, interest and taxes; the bottom line of the income statement.", "https://www.investopedia.com/terms/n/netincome.asp"],
  });
  const T = (key, label) => FA.term(key, label);
  // swap plain labels that a toolkit helper escaped for their glossary-marked versions, then arm the tooltips
  const retag = (root, sel, map) => { root.querySelectorAll(sel).forEach(n => { const h = map[n.textContent.trim()]; if (h) { const sw = n.querySelector('i'); n.innerHTML = (sw ? sw.outerHTML : '') + h; } }); F.armTerms(root); };
  const DCF = T('dcf', 'DCF'), WACC = T('wacc', 'WACC'), TG = T('terminal growth', 'g'), FV = T('fair value', 'fair value'), EPS = T('eps', 'EPS');
  const termLabel = {graham_number: T('graham number', 'Graham number'), graham_number_10y: `${T('graham number', 'Graham number')} (10y ${EPS})`, graham_growth_formula: T('graham growth formula', 'Graham growth formula'), ncav: T('net current asset value', 'Net current asset value'),
    dcf: `${DCF} ${FV}`, dcf_owner_earnings: `${T('owner earnings', 'Owner-earnings')} ${DCF}`, dcf_mid_cycle: `${T('normalized earnings', 'Mid-cycle')} ${DCF}`, comps: T('comparable company analysis', 'Comps (median implied)'), ddm: T('ddm', 'Dividend discount')};
  g('h1').textContent = sym ? `Valuation: ${sym}` : 'Valuation';
  document.title = sym ? `${sym} Valuation` : 'Valuation';
  FA.explain(g('explain'), `<p>This page collects several estimates of what one share${sym ? ` of ${F.esc(sym)}` : ''} might be worth (its ${T('intrinsic value')}) and sets each against the current price. The figures come from the plugin's scripts fed with the company's own annual financials from SEC filings and the assumptions listed under each method; nothing is fetched live and nothing here is a price target.</p>
    <p>The first chart puts every estimate on one dollar scale with today's price as a line: a dot right of the line is an estimate above the price, the gap a ${T('margin of safety')}; a dot left of it is an estimate the price already exceeds. The ${DCF} block adds up the cash the business is expected to produce, shrunk to today's money at the ${WACC}; its grid is a ${T('sensitivity analysis')} showing how the answer moves when that rate or the long-run ${T('terminal growth', 'growth rate')} changes.</p>
    <p>That grid is the main caveat: small changes in those two assumptions swing the value a lot, so read every figure as a range rather than a point, and the Graham and Buffett checklists as descriptions of the business, not verdicts.</p>`);
  g('mos-h').innerHTML = `${T('margin of safety', 'Margin of safety')} by method`;
  g('dcf-h').innerHTML = T('dcf', 'Discounted cash flow');
  g('oe-h').innerHTML = `${T('owner earnings', 'Owner-earnings')} ${DCF}`;
  g('mid-h').innerHTML = `${T('normalized earnings', 'Mid-cycle')} ${DCF}`;
  g('graham-h').innerHTML = `Graham ${T('defensive investor', 'defensive')} checklist`;
  g('oe-chart-h').innerHTML = `${T('owner earnings', 'Owner earnings')} by year`;
  g('norm-h').innerHTML = `${T('normalized earnings', 'Normalized (mid-cycle) earnings')}`;
  g('comps-h').innerHTML = `${T('comparable company analysis', 'Comparable')} ${T('multiple', 'multiples')}`;
  g('ddm-h').innerHTML = T('ddm', 'Dividend discount model');
  F.armTerms(document);
  const parts = [];
  if (F.isNum(price)) parts.push(`Price ${money(price)}`);
  if (I) parts.push(`fiscal ${I.fiscal_year} · ${I.years_covered} years of annual data · ${I.inputs.business_type}`);
  parts.push('methods: ' + [X && 'DCF', OE && 'owner-earnings DCF', MID && 'mid-cycle DCF', I && 'Graham/Buffett', CO && 'comps', DD && 'DDM'].filter(Boolean).join(', '));
  g('sub').textContent = parts.join(' · ');
  // tiles: the three things a reader wants first -- the price, the spread of estimates, and where the price sits in it
  const est = [];
  if (I) for (const m of I.margin_of_safety || []) if (F.isNum(m.value) && m.value > 0) est.push({key: m.method, value: m.value});
  for (const [k, r] of [['dcf', X], ['dcf_owner_earnings', OE], ['dcf_mid_cycle', MID], ['ddm', DD]]) if (r && F.isNum(r.fair_value_per_share) && r.fair_value_per_share > 0) est.push({key: k, value: r.fair_value_per_share});
  if (CO && F.isNum(CO.summary.median) && CO.summary.median > 0) est.push({key: 'comps', value: CO.summary.median});
  const tiles = [];
  if (F.isNum(price)) tiles.push(['Price', money(price), F.esc(sym) || 'current share price']);
  if (est.length) { const vs = est.map(e => e.value); tiles.push(['Range of estimates', `${money(Math.min(...vs))} – ${money(Math.max(...vs))}`, `${est.length} estimates from the methods below`]); }
  if (est.length && F.isNum(price)) { const above = est.filter(e => e.value > price).length;
    tiles.push(['Estimates above the price', `${above} of ${est.length}`, above === 0 ? 'the price is above every estimate' : above === est.length ? 'every estimate is above the price' : 'the price sits inside the range']); }
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  F.armTerms(g('tiles'));
  // margin of safety
  const rows = [];
  if (I) for (const m of I.margin_of_safety || []) rows.push({key: m.method, value: m.value, discount: m.discount, band: m.band, src: 'intrinsic.py'});
  for (const [k, r] of [['dcf', X], ['dcf_owner_earnings', OE], ['dcf_mid_cycle', MID]]) if (r && F.isNum(r.fair_value_per_share)) rows.push({key: k, value: r.fair_value_per_share, discount: disc(r.fair_value_per_share), src: 'derived'});
  if (CO) rows.push({key: 'comps', value: CO.summary.median, discount: disc(CO.summary.median), src: 'derived'});
  if (DD) rows.push({key: 'ddm', value: DD.fair_value_per_share, discount: disc(DD.fair_value_per_share), src: 'derived'});
  const withDisc = rows.filter(r => F.isNum(r.value) && r.value > 0);
  if (withDisc.length && F.isNum(price)) {
    const vals = [...withDisc.map(r => r.value), price], ticks = F.niceTicks(Math.min(0, ...vals), Math.max(...vals) * 1.05), lo = ticks[0], hi = ticks[ticks.length - 1];
    const X0 = 230, W = 960, X1 = W - 170, RH = 30, H = withDisc.length * RH + 40, xs = v => X0 + (X1 - X0) * (v - lo) / (hi - lo);
    const gap = r => gapText(r.value);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Every estimate against the price">`;
    svg += ticks.filter(t => Math.abs(xs(t) - xs(price)) > 48).map(t => `<line x1="${xs(t)}" x2="${xs(t)}" y1="6" y2="${H - 26}" stroke="var(--grid)"/><text x="${xs(t)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${F.esc(F.moneyC(t))}</text>`).join('');
    withDisc.forEach((r, i) => { const y = 20 + i * RH, up = r.value >= price;
      svg += `<text x="${X0 - 12}" y="${y + 4}" text-anchor="end" font-size="12.5" fill="var(--ink)">${F.esc(label[r.key] || r.key)}</text>`;
      svg += `<line x1="${xs(Math.min(r.value, price))}" x2="${xs(Math.max(r.value, price))}" y1="${y}" y2="${y}" stroke="${up ? 'var(--up)' : 'var(--down)'}" stroke-width="2" opacity=".35"/>`;
      svg += `<circle cx="${xs(r.value)}" cy="${y}" r="6.5" fill="${up ? 'var(--up)' : 'var(--down)'}"><title>${F.esc(label[r.key] || r.key)}: ${F.esc(money(r.value))}</title></circle>`;
      svg += `<text x="${X1 + 14}" y="${y + 4}" font-size="12" fill="var(--ink2)">${F.esc(money(r.value))} · ${F.esc(gap(r))}</text>`; });
    svg += `<line x1="${xs(price)}" x2="${xs(price)}" y1="2" y2="${H - 26}" stroke="var(--ink)" stroke-width="2" stroke-dasharray="4 3"/><text x="${xs(price)}" y="${H - 8}" text-anchor="middle" font-size="11.5" font-weight="600" fill="var(--ink)">price ${F.esc(money(price))}</text></svg>`;
    g('mos').innerHTML = svg;
    g('mos-h').innerHTML = 'Every estimate against the price';
    g('mos-sub').innerHTML = `Each dot is one method's estimate of a share's worth; the dashed line is today's price. Green dots sit above the price, red below. Graham's rule of thumb for a ${T('margin of safety')} was an estimate a third above the price.`;
    F.armTerms(g('mos-sub'));
  } else { g('mos').innerHTML = '<span class="muted">' + (rows.length ? 'no price given; the comparison with price is skipped' : 'no value estimates') + '</span>'; }
  // heatmap around price with the base case outlined
  // rowName/colName are plain text (used in tooltips); rowHtml/colHtml are the glossary-marked versions for the header cell
  function heat(root, rowVals, colVals, values, base, rowName, colName, rowHtml, colHtml) {
    const flat = values.flat().filter(F.isNum);
    if (!flat.length) { root.innerHTML = '<span class="muted">no grid</span>'; return; }
    const center = F.isNum(price) ? price : (flat.reduce((a, b) => a + b, 0) / flat.length);
    const span = Math.max(...flat.map(v => Math.abs(v - center)), 1e-9);
    const color = v => { if (!F.isNum(v)) return 'var(--grid)'; const t = (v - center) / span; const k = Math.round(Math.min(1, Math.abs(t)) * 85 + 8); return t >= 0 ? `color-mix(in oklab, var(--s1) ${k}%, var(--surface))` : `color-mix(in oklab, var(--s8) ${k}%, var(--surface))`; };
    let h = `<div class="twrap"><table class="heat"><thead><tr><th class="l">${rowHtml || rowName} \\ ${colHtml || colName}</th>` + colVals.map(c => `<th>${pct1(c)}</th>`).join('') + '</tr></thead><tbody>';
    rowVals.forEach((r, i) => { h += `<tr><td class="l">${pct1(r)}</td>` + colVals.map((c, j) => { const v = values[i][j]; const isBase = Math.abs(r - base[0]) < 1e-9 && Math.abs(c - base[1]) < 1e-9; return `<td class="${isBase ? 'base' : ''}" style="background:${color(v)};text-align:center" data-r="${i}" data-c="${j}">${F.isNum(v) ? money(v) : '—'}</td>`; }).join('') + '</tr>'; });
    root.innerHTML = h + '</tbody></table></div>';
    F.armTerms(root);
    root.querySelectorAll('td[data-r]').forEach(td => { const v = values[+td.dataset.r][+td.dataset.c]; F.bindTip(td, `<b>${rowName} ${pct1(rowVals[+td.dataset.r])}</b> × <b>${colName} ${pct1(colVals[+td.dataset.c])}</b>: ${F.isNum(v) ? money(v) : '—'}` + (F.isNum(v) && F.isNum(price) ? `<br>vs price ${money(price)}: ${F.pct(1 - price / v, 1, true)}` : '')); });
  }
  const legendHtml = () => F.isNum(price) ? `<span><i class="sw" style="background:color-mix(in oklab, var(--s1) 60%, var(--surface))"></i>above price (discount)</span><span><i class="sw" style="background:color-mix(in oklab, var(--s8) 60%, var(--surface))"></i>below price (premium)</span><span><i class="sw" style="outline:2px solid var(--ink);outline-offset:-2px"></i>base case</span>` : '<span>shade: distance from the grid mean; outlined: base case</span>';
  function dcfKv(root, r) {
    const e = r.inputs_echo, imp = r.implied;
    root.innerHTML = `
      <dt>${FV} / share</dt><dd><b>${money(r.fair_value_per_share)}</b>${F.isNum(price) ? ` <span class="muted">vs price ${money(price)} · ${gapText(r.fair_value_per_share)}</span>` : ''}</dd>
      <dt>${T('enterprise value', 'Enterprise value')}</dt><dd>${F.moneyC(r.enterprise_value)} = ${T('present value', 'stage 1')} ${F.moneyC(r.pv_stage1)} + ${T('terminal value', 'terminal')} ${F.moneyC(r.pv_terminal)}</dd>
      <dt>${T('terminal value', 'Terminal')} share of ${T('enterprise value', 'EV')}</dt><dd style="${r.terminal_value_share_of_ev > 0.7 ? 'color:var(--warn)' : ''}">${pct1(r.terminal_value_share_of_ev)}${r.terminal_value_share_of_ev > 0.7 ? ' — above 70%: the value rests on the terminal assumptions' : ''}</dd>
      <dt>Equity value</dt><dd>${F.moneyC(r.equity_value)} after ${T('net debt')} ${F.moneyC(e.net_debt)} · ${bigN(e.shares_outstanding)} ${T('shares outstanding', 'shares')}</dd>
      <dt>Assumptions</dt><dd>${T('free cash flow', 'fcf0')} ${F.moneyC(e.fcf0)} · stage-1 growth ${Array.isArray(e.stage1_growth) ? e.stage1_growth.map(v => pct1(v)).join(' → ') : pct1(e.growth_rate)} for ${e.years}y · ${T('terminal growth', 'terminal g')} ${pct1(e.terminal_growth)} · ${WACC} ${pct1(e.wacc)}</dd>
      ${imp ? `<dt>Market-implied</dt><dd>the growth the current price ${money(imp.current_share_price)} already assumes: stage-1 ${F.isNum(imp.stage1_growth) ? pct1(imp.stage1_growth) : 'none admissible'} · terminal ${F.isNum(imp.terminal_growth) ? pct2(imp.terminal_growth) : 'none admissible'}</dd>` : ''}`;
    F.armTerms(root);
  }
  if (X) {
    g('dcf-card').hidden = false; dcfKv(g('dcf-kv'), X);
    const s = X.sensitivity_grid;
    heat(g('dcf-grid'), s.wacc_values, s.terminal_growth_values, s.fair_value_per_share, [X.inputs_echo.wacc, X.inputs_echo.terminal_growth], 'WACC', 'g', WACC, TG);
    g('dcf-grid-sub').innerHTML = `${T('sensitivity analysis', 'Sensitivity')}: ${FV} per share by ${WACC} (rows) and ${T('terminal growth')} (columns); blank where g ≥ WACC.`;
    F.armTerms(g('dcf-grid-sub'));
    g('dcf-legend').innerHTML = legendHtml();
  }
  if (OE || MID) {
    g('alt-dcf').hidden = false;
    const R = T('discount rate', 'r');
    if (OE) { g('oe-card').hidden = false; dcfKv(g('oe-kv'), OE); const s = OE.sensitivity_grid; heat(g('oe-grid'), s.wacc_values, s.terminal_growth_values, s.fair_value_per_share, [OE.inputs_echo.wacc, OE.inputs_echo.terminal_growth], 'r', 'g', R, TG); }
    if (MID) { g('mid-card').hidden = false; dcfKv(g('mid-kv'), MID); const s = MID.sensitivity_grid; heat(g('mid-grid'), s.wacc_values, s.terminal_growth_values, s.fair_value_per_share, [MID.inputs_echo.wacc, MID.inputs_echo.terminal_growth], 'r', 'g', R, TG); }
  }
  // Graham / Buffett
  const fmtVal = v => { if (v == null) return '—'; if (typeof v === 'number') return Math.abs(v) >= 1000 ? F.moneyC(v) : F.num(v, 2); if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k.replace(/_/g, ' ')} ${typeof x === 'number' ? (Math.abs(x) >= 1000 ? F.moneyC(x) : F.num(x, 2)) : x ?? '—'}`).join(', '); return String(v); };
  const checklist = (root, block) => { root.innerHTML = (block.checks || []).map(c => `<li><span class="st ${c.passed === true ? 'pass' : c.passed === false ? 'fail' : 'na'}">${c.passed === true ? '✓ pass' : c.passed === false ? '✗ fail' : 'n/a'}</span><span><b>${F.esc(c.check.replace(/_/g, ' '))}</b> ${F.esc(fmtVal(c.value))}<br><span class="t">${F.esc(c.threshold)}</span></span></li>`).join(''); };
  if (I) {
    g('checklists').hidden = false;
    const d = I.graham.defensive_checklist, t = I.buffett.tenets, ps = I.per_share, gr = I.graham, oe = I.buffett.owner_earnings;
    g('graham-sub').textContent = `${d.score} of ${d.out_of} tests passed over ${d.years_covered} years (Graham asked for 10 to 20).`;
    checklist(g('graham'), d);
    g('graham-kv').innerHTML = `<dt>${EPS}</dt><dd>latest ${F.num(ps.eps_latest, 2)} · 3y avg ${F.num(ps.eps_3y_avg, 2)}</dd><dt>${T('book value', 'Book value')} / share</dt><dd>${money(ps.book_value)}</dd><dt>Dividends / share</dt><dd>${money(ps.dividends)}</dd>
      <dt>${T('graham number', 'Graham number')}</dt><dd>${money(gr.graham_number)} <span class="muted">√(22.5 × EPS₃ × book)</span></dd><dt>${T('graham growth formula', 'Growth formula')}</dt><dd>${money(gr.growth_formula.value)} <span class="muted">g ${pct1(gr.growth_formula.growth_used)} (${F.esc(I.inputs.growth_rate.source)}); at 5/10/15%: ${['0.05', '0.10', '0.15'].map(k => money(I.inputs.growth_alternatives.growth_formula_at[k])).join(' / ')}</span></dd>
      <dt>${T('net current asset value', 'NCAV')} / share</dt><dd>${F.isNum(gr.ncav_per_share) ? money(gr.ncav_per_share) : '—'} · ${T('net-net')} ⅔ ${F.isNum(gr.net_net.two_thirds_ncav) ? money(gr.net_net.two_thirds_ncav) : '—'} (${gr.net_net.price_below ? 'price below' : 'price not below'})</dd>`;
    g('buffett-sub').textContent = `${t.score} of ${t.out_of} tenets passed.`;
    checklist(g('buffett'), t);
    g('buffett-kv').innerHTML = `<dt>${T('owner earnings', 'Owner earnings')}</dt><dd>${F.moneyC(oe.value)} (${money(oe.per_share)} / share) = ${T('net income')} ${F.moneyC(oe.net_income)} + ${T('depreciation and amortization', 'D&A')} ${F.moneyC(oe.depreciation_amortization)} − ${T('capital expenditure', 'maintenance capex')} ${F.moneyC(oe.maintenance_capex)}</dd>
      <dt>Maintenance ${T('capital expenditure', 'capex')}</dt><dd>${F.esc(oe.maintenance_capex_method)} <span class="muted">(D&amp;A ${F.moneyC(oe.estimates.depreciation_amortization)}, avg capex ${F.moneyC(oe.estimates.average_capex)}, 1% revenue ${F.moneyC(oe.estimates.one_percent_of_revenue)}; capex ${F.moneyC(oe.capex)})</span></dd>
      <dt>${T('discount rate', 'Discount rate')}</dt><dd>${pct1(I.inputs.discount_rate.value)} <span class="muted">${F.esc(I.inputs.discount_rate.source)}</span></dd>
      <dt>Inputs passed to the ${DCF}</dt><dd>${T('free cash flow', 'fcf0')} ${F.moneyC(I.buffett.dcf_input.fcf0)} · g ${pct1(I.buffett.dcf_input.growth_rate)} · ${I.buffett.dcf_input.years}y · ${T('terminal growth', 'terminal')} ${pct1(I.buffett.dcf_input.terminal_growth)} · ${T('net debt')} ${F.moneyC(I.buffett.dcf_input.net_debt)}</dd>`;
    F.armTerms(g('checklists'));
    // owner earnings by year + normalized
    g('oe-row').hidden = false;
    const by = (oe.by_year || []).filter(r => F.isNum(r.value) && r.fiscal_year != null);
    if (by.length) { F.lines(g('oe-chart'), {series: [{name: 'Owner earnings', points: by.map(r => [r.fiscal_year, r.value]), color: F.S[0], area: true}], xFmt: x => Math.abs(x - Math.round(x)) < 0.3 ? String(Math.round(x)) : '', yFmt: y => F.moneyC(y), zeroLine: true, height: 220, aria: 'owner earnings by fiscal year'}); }
    else g('oe-chart').innerHTML = '<span class="muted">no owner-earnings series</span>';
    const N = I.normalized;
    g('oe-sub').textContent = `${by.length} fiscal years; latest ${F.moneyC(oe.value)}` + (F.isNum(N.owner_earnings_10y_avg) ? ` vs ${N.years.owner_earnings}-year average ${F.moneyC(N.owner_earnings_10y_avg)} (${F.num(oe.value / N.owner_earnings_10y_avg, 2)}×).` : '.');
    g('norm-sub').innerHTML = `${T('normalized earnings', 'Averages')} over the last ten fiscal years (at least five present) so a cycle-peak year does not set the value.`;
    g('norm').innerHTML = `<dt>${T('owner earnings', 'Owner earnings')}, avg</dt><dd>${F.moneyC(N.owner_earnings_10y_avg)} (${F.isNum(N.owner_earnings_10y_avg_per_share) ? money(N.owner_earnings_10y_avg_per_share) : '—'} / share, ${N.years.owner_earnings} years)</dd>
      <dt>${EPS}, avg</dt><dd>${F.num(N.eps_10y_avg, 2)} (${N.years.eps} years)</dd>
      <dt>${T('graham number', 'Graham number')} on avg ${EPS}</dt><dd>${money(N.graham_number_10y)}</dd>
      <dt>Mid-cycle ${DCF} input</dt><dd>${N.dcf_input_mid_cycle ? `${T('free cash flow', 'fcf0')} ${F.moneyC(N.dcf_input_mid_cycle.fcf0)} growing at ${T('terminal growth', 'terminal g')} ${pct1(N.dcf_input_mid_cycle.growth_rate)} · ${T('discount rate', 'r')} ${pct1(N.dcf_input_mid_cycle.wacc)}` : 'not available (fewer than five years, or owner earnings mostly negative)'}${MID ? ` → <b>${money(MID.fair_value_per_share)}</b> / share` : ''}</dd>`;
    F.armTerms(g('oe-row'));
    // business-type yardsticks
    const bt = I.buffett.book_value_tests, rt = I.buffett.reit_tests, ut = I.buffett.utility_tests;
    if (bt || rt || ut) {
      g('type-card').hidden = false;
      if (bt) { g('type-h').innerHTML = `${T('book value', 'Book-value')} tests (financial)`; g('type-kv').innerHTML = `<dt>${T('p/b', 'Price / book')}</dt><dd>${F.num(bt.price_to_book, 2)}</dd><dt>${T('roe', 'ROE')}</dt><dd>latest ${pct1(bt.roe_latest)} · 10y avg ${pct1(bt.roe_10y_avg)}</dd><dt>Reading</dt><dd>${F.esc(bt.price_to_book_x_roe_note)}</dd>`; }
      else if (ut) { g('type-h').innerHTML = 'Utility tests'; g('type-kv').innerHTML = `<dt>${T('p/e', 'P/E')}</dt><dd>${F.num(ut.pe, 1)} (on 3-year average ${F.num(ut.pe_3y_avg_eps, 1)})</dd><dt>${T('p/b', 'Price / book')}</dt><dd>${F.num(ut.price_to_book, 2)}</dd><dt>${T('roe', 'ROE')}</dt><dd>latest ${pct1(ut.roe_latest)} · 10y avg ${pct1(ut.roe_10y_avg)}</dd><dt>${T('dividend yield', 'Dividend yield')}</dt><dd>${pct2(ut.dividend_yield)}</dd><dt>${T('payout ratio', 'Payout')} of earnings</dt><dd>${pct1(ut.payout_of_eps)}</dd><dt>Dividend growth / share</dt><dd>${pct1(ut.dividend_per_share_cagr)} a year</dd>`; }
      else { g('type-h').innerHTML = `${T('reit', 'REIT')} tests`; g('type-kv').innerHTML = `<dt>${T('affo', 'AFFO')} proxy / share</dt><dd>${money(rt.affo_proxy_per_share)}${F.isNum(rt.affo_proxy_per_share_cagr) ? ` (${pct1(rt.affo_proxy_per_share_cagr)} a year)` : ''}</dd><dt>Price / ${T('affo', 'AFFO')} proxy</dt><dd>${F.num(rt.price_to_affo_proxy, 2)}</dd><dt>${T('dividend yield', 'Dividend yield')}</dt><dd>${pct2(rt.dividend_yield)}${F.isNum(rt.dividend_per_share_cagr) ? ` (growing ${pct1(rt.dividend_per_share_cagr)} a year)` : ''}</dd><dt>${T('payout ratio', 'Payout')} of AFFO proxy</dt><dd>${pct1(rt.payout_of_affo_proxy)}</dd>${F.isNum(rt.net_debt_to_ebitda) ? `<dt>Net debt / EBITDA</dt><dd>${F.num(rt.net_debt_to_ebitda, 1)}×</dd>` : ''}${rt.property_sale_gains_excluded ? `<dt>Property-sale gains left out</dt><dd>${F.moneyC(rt.property_sale_gains_excluded)}</dd>` : ''}`; }
      F.armTerms(g('type-card'));
    }
  }
  // comps
  if (CO) {
    g('comps-card').hidden = false;
    const name = {pe: 'P/E', ev_ebitda: 'EV/EBITDA', ps: 'P/S', pb: 'P/B', ev_sales: 'EV/Sales', fcf_yield: 'FCF yield'};
    const metricTerm = {pe: T('p/e', 'P/E'), ev_ebitda: T('ev/ebitda', 'EV/EBITDA'), ps: T('p/s', 'P/S'), pb: T('p/b', 'P/B'), ev_sales: T('ev/sales', 'EV/Sales'), fcf_yield: T('fcf yield', 'FCF yield')};
    const rows = Object.entries(CO.metrics).map(([k, m]) => ({metric: name[k] || k, key: k, peer_median: m.peer_median, implied: m.implied_value_per_share, prem: m.premium_discount_vs_peers ?? null, discount: disc(m.implied_value_per_share)}));
    F.table(g('comps'), [
      {key: 'metric', label: 'Multiple', left: true, fmt: (v, r) => `<b>${metricTerm[r.key] || F.esc(v)}</b>`},
      {key: 'peer_median', label: 'Peer median', fmt: (v, r) => r.key === 'fcf_yield' ? pct2(v) : F.num(v, 2) + '×'},
      {key: 'implied', label: 'Implied value / share', fmt: money},
      {key: 'discount', label: 'vs price', fmt: v => F.pct(v, 1, true), cls: F.cls},
      {key: 'prem', label: 'Target vs peers', fmt: (v, r) => F.isNum(v) ? F.pct(v, 1, true) + (r.key === 'fcf_yield' ? ' (yield)' : '') : '—'},
    ], rows, {sortKey: 'implied', onDraw: () => F.armTerms(g('comps'))});
    retag(g('comps'), 'thead th', {'Multiple': T('multiple', 'Multiple'), 'Implied value / share': `Implied ${FV} / share`});
    g('comps-sub').innerHTML = `Implied value ${money(CO.summary.min)} – ${money(CO.summary.max)}, median ${money(CO.summary.median)}: what the share would be worth if it traded at the peer group's median ${T('multiple')}. "Target vs peers" is the target's multiple against the peer median (positive = pricier; for ${T('fcf yield', 'FCF yield')} positive = higher yield, i.e. cheaper).`;
    F.armTerms(g('comps-sub'));
  }
  // ddm
  if (DD) {
    g('ddm-card').hidden = false; const e = DD.inputs_echo;
    const modelT = DD.model === 'gordon' ? T('gordon growth model', 'gordon') : F.esc(DD.model);
    g('ddm-kv').innerHTML = `<dt>Model</dt><dd>${modelT}</dd><dt>${FV} / share</dt><dd><b>${money(DD.fair_value_per_share)}</b>${F.isNum(price) ? ` <span class="muted">vs price ${money(price)} · ${gapText(DD.fair_value_per_share)}</span>` : ''}</dd>
      <dt>Dividend (D0)</dt><dd>${money(e.dividend0)}</dd><dt>${T('required rate of return', 'Required return')}</dt><dd>${pct1(e.required_return)}</dd><dt>${T('terminal growth', 'Terminal growth')}</dt><dd>${pct1(e.terminal_growth)}</dd>
      ${DD.model === 'two_stage' ? `<dt>Stage 1</dt><dd>${pct1(e.growth_rate)} for ${e.years} years</dd>` : DD.model === 'h' ? `<dt>H-model</dt><dd>initial growth ${pct1(e.initial_growth)}, half-life ${F.num(e.h_years, 1)} years</dd>` : ''}`;
    const s = DD.sensitivity_grid;
    heat(g('ddm-grid'), s.required_return_values, s.terminal_growth_values, s.fair_value_per_share, [e.required_return, e.terminal_growth], 'k', 'g', T('required rate of return', 'k'), TG);
    g('ddm-grid-sub').innerHTML = `${T('sensitivity analysis', 'Sensitivity')}: value per share by ${T('required rate of return', 'required return')} (rows) and ${T('terminal growth')} (columns).`;
    F.armTerms(g('ddm-card'));
  }
  // card help: what each card answers, how its number is built, and how to read it
  const M = v => F.moneyC(v);
  const dcfFlow = r => F.flow([
    {label: "the forecast years' cash, in today's $", value: M(r.pv_stage1)},
    {op: '+', label: 'every year after, in today’s $', value: M(r.pv_terminal)},
    {op: '=', label: 'whole business', value: M(r.enterprise_value)},
    {op: '−', label: 'net debt', value: M(r.inputs_echo.net_debt)},
    {op: '÷', label: 'shares', value: bigN(r.inputs_echo.shares_outstanding)},
    {op: '=', label: 'per share', value: money(r.fair_value_per_share)}]);
  const tvNote = r => `<p>${F.pct(r.terminal_value_share_of_ev, 0)} of the total comes from the years after the forecast, so the long-run growth rate and the discount rate move this number the most.</p>`;
  const gridHelp = (row, col) => ({title: 'Reading the grid', html: F.readGrid({rowLabel: row, colLabel: col,
    highText: F.isNum(price) ? `Blue cells are values above today's price of ${money(price)}.` : 'Blue cells are values above the grid average.',
    lowText: F.isNum(price) ? 'Red cells are values below it.' : 'Red cells are values below it.',
    baseText: 'The outlined cell is the estimate shown above; its neighbours show how far it moves when either assumption shifts by half a point.'})});
  if (withDisc.length && F.isNum(price)) {
    const hi = withDisc.reduce((a, b) => (b.value > a.value ? b : a)), lo = withDisc.reduce((a, b) => (b.value < a.value ? b : a));
    F.help(g('mos-card'), {lead: 'Where each method’s estimate of a share’s worth sits against today’s price.',
      sections: [{title: 'Reading the dots', html: `<p>The dashed line is today's price, ${money(price)}. A green dot to its right is an estimate above the price; a red dot to its left is one the price already exceeds.</p>
        <p>The highest estimate here is ${F.esc(label[hi.key] || hi.key)} at ${money(hi.value)}; the lowest is ${F.esc(label[lo.key] || lo.key)} at ${money(lo.value)}. Methods disagree because each starts from different numbers: cash flow, earnings, book value or what peers trade at.</p>`}]});
  } else F.help(g('mos-card'), {lead: 'Where each method’s estimate of a share’s worth sits against today’s price.'});
  if (X) F.help(g('dcf-card'), {lead: 'What one share is worth if the business produces the cash in the forecast, counted in today’s money.',
    sections: [{title: 'How the number adds up', html: dcfFlow(X) + tvNote(X)}, gridHelp('discount rate (WACC)', 'long-run growth')]});
  if (OE) F.help(g('oe-card'), {lead: 'The same cash-flow method, starting from owner earnings: the cash an owner could take out without shrinking the business.',
    sections: [{title: 'How the number adds up', html: dcfFlow(OE) + `<p>It starts from the latest year's owner earnings of ${M(OE.inputs_echo.fcf0)} and discounts at ${pct1(OE.inputs_echo.wacc)}.</p>`}, gridHelp('discount rate', 'long-run growth')]});
  if (MID) F.help(g('mid-card'), {lead: 'The same cash-flow method, starting from a ten-year average instead of the latest year.',
    sections: [{title: 'How the number adds up', html: dcfFlow(MID) + `<p>It starts from average owner earnings of ${M(MID.inputs_echo.fcf0)}, so one unusually good or bad year does not set the value.</p>`}, gridHelp('discount rate', 'long-run growth')]});
  const scoreFlow = block => { const cs = block.checks || [], pass = cs.filter(c => c.passed === true).length, fail = cs.filter(c => c.passed === false).length, na = cs.length - pass - fail;
    return F.flow([{label: 'passed', value: String(pass)}, {op: '+', label: 'failed', value: String(fail)}, ...(na ? [{op: '+', label: 'not scored', value: String(na)}] : []), {op: '=', label: 'tests', value: String(cs.length)}]); };
  if (I) {
    const oe = I.buffett.owner_earnings, N = I.normalized;
    F.help(g('graham-h').parentElement, {lead: 'Seven tests Benjamin Graham used to pick large, steady companies at modest prices.',
      sections: [{title: 'Score', html: scoreFlow(I.graham.defensive_checklist) + '<p>Each test describes the business or its price; a failed test is a fact about the company, not a verdict on the stock.</p>'},
        {title: 'The two value figures', html: `<p>The Graham number, ${money(I.graham.graham_number)}, is the most Graham would pay given earnings and book value. The growth formula, ${money(I.graham.growth_formula.value)}, adds expected growth; at ${pct1(I.graham.growth_formula.growth_used)} growth it is the ${F.isNum(I.graham.growth_formula.value) && F.isNum(I.graham.graham_number) && I.graham.growth_formula.value > I.graham.graham_number ? 'higher' : 'lower'} of the two here.</p>`}]});
    F.help(g('buffett-h').parentElement, {lead: 'Checks drawn from Warren Buffett’s letters: steady high returns, little debt, and real cash behind the profit.',
      sections: [{title: 'Score', html: scoreFlow(I.buffett.tenets)}]});
    F.help(g('oe-chart-h').parentElement, {lead: 'The cash an owner could take out each year without shrinking the business.',
      sections: [{title: 'How the latest year adds up', html: F.flow([{label: 'net income', value: M(oe.net_income)}, {op: '+', label: 'D&A (no cash leaves)', value: M(oe.depreciation_amortization)},
        {op: '−', label: 'maintenance capex', value: M(oe.maintenance_capex)}, {op: '=', label: 'owner earnings', value: M(oe.value)}])}]});
    F.help(g('norm-h').parentElement, {lead: 'A ten-year average, so one unusually good or bad year does not set the value.',
      sections: [{title: 'Latest year against the average', html: F.isNum(N.owner_earnings_10y_avg) && N.owner_earnings_10y_avg ? F.flow([{label: 'latest owner earnings', value: M(oe.value)}, {op: '÷', label: `${N.years.owner_earnings}-year average`, value: M(N.owner_earnings_10y_avg)}, {op: '=', label: 'ratio', value: F.num(oe.value / N.owner_earnings_10y_avg, 2) + '×'}]) + '<p>Below 1× means the latest year earned less than the business usually does; well above 1× can mean a peak year.</p>' : '<p>Fewer than five years of data, so no average.</p>'}]});
    const bt = I.buffett.book_value_tests, rt = I.buffett.reit_tests, ut = I.buffett.utility_tests;
    if (ut) F.help(g('type-card'), {lead: 'For a regulated utility, earnings, book value and the dividend replace the cash-flow value: it funds its growth with new debt and shares, so free cash flow is usually negative by design.'});
    else if (bt) F.help(g('type-card'), {lead: 'For a bank or insurer, price against book value and returns on equity replace the cash-flow value, because debt is part of the business itself.'});
    else if (rt) F.help(g('type-card'), {lead: 'For a REIT, a cash-earnings proxy (AFFO) replaces reported earnings, which depreciation makes look smaller than the cash the properties produce.'});
  }
  if (CO) { const pe = CO.metrics && CO.metrics.pe;
    F.help(g('comps-card'), {lead: 'What a share would cost if it traded at its peers’ typical price ratios.',
      sections: pe && F.isNum(pe.peer_median) && F.isNum(pe.implied_value_per_share) && pe.peer_median ? [{title: 'One row worked through', html: F.flow([{label: 'peers’ median P/E', value: F.num(pe.peer_median, 2) + '×'}, {op: '×', label: 'this company’s earnings / share', value: money(pe.implied_value_per_share / pe.peer_median)}, {op: '=', label: 'implied price', value: money(pe.implied_value_per_share)}]) + '<p>Each row does the same with a different ratio; the median of the rows is the estimate on the chart above.</p>'}] : []}); }
  if (DD) { const e = DD.inputs_echo, gordon = DD.model === 'gordon' && F.isNum(e.dividend0) && e.required_return > e.terminal_growth;
    F.help(g('ddm-card'), {lead: 'What a share is worth as the stream of future dividends, counted in today’s money.',
      sections: [...(gordon ? [{title: 'How the number adds up', html: F.flow([{label: 'dividend this year', value: money(e.dividend0)}, {op: '×', label: `1 + growth ${pct1(e.terminal_growth)}`, value: F.num(1 + e.terminal_growth, 3)}, {op: '=', label: 'next year’s dividend', value: money(e.dividend0 * (1 + e.terminal_growth))},
        {op: '÷', label: `required return − growth`, value: pct1(e.required_return - e.terminal_growth)}, {op: '=', label: 'per share', value: money(DD.fair_value_per_share)}])}] : [{title: 'How it works', html: '<p>Each future dividend is shrunk to today’s money at the required return, faster growth first and steady growth after, and the results are added up.</p>'}]),
        gridHelp('required return', 'dividend growth')]}); }
  // flags
  const flags = [];
  if (I) for (const f of I.flags || []) flags.push(f);
  if (X && X.terminal_value_share_of_ev > 0.7) flags.push({code: 'TERMINAL_HEAVY', message: `terminal value is ${pct1(X.terminal_value_share_of_ev)} of the DCF enterprise value; small WACC or growth changes swing the result (see the grid)`});
  if (CO && CO.skipped_metrics) for (const [k, m] of Object.entries(CO.skipped_metrics)) flags.push({code: 'COMPS_SKIPPED', message: `${k}: ${m}`});
  if (!F.isNum(price) && !(I && (I.flags || []).some(f => f.code === 'NO_PRICE'))) flags.push({code: 'NO_PRICE', message: 'no price given; discounts to price are skipped'});
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""

_METHODS = ("dcf", "dcf_owner_earnings", "dcf_mid_cycle", "intrinsic", "comps", "ddm")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _normalize(data: object) -> dict:
    if not isinstance(data, dict):
        raise InvalidInput("input must be an object with at least one of dcf, intrinsic, comps, ddm")
    if "graham" in data and "buffett" in data:
        data = {"intrinsic": data, "price": (data.get("inputs") or {}).get("price")}
    elif "sensitivity_grid" in data and "pv_terminal" in data:
        data = {"dcf": data}
    elif "sensitivity_grid" in data and "model" in data:
        data = {"ddm": data}
    elif "metrics" in data and "summary" in data:
        data = {"comps": data}
    present = [k for k in ("dcf", "intrinsic", "comps", "ddm") if isinstance(data.get(k), dict)]
    if not present:
        raise InvalidInput("input must be an object with at least one of dcf, intrinsic, comps, ddm (each a script result), plus optional symbol, price, dcf_owner_earnings, dcf_mid_cycle")
    return data


def build(data: dict) -> tuple[str, str, dict]:
    data = _normalize(data)
    symbol = str(data.get("symbol") or "")
    title = f"{symbol} Valuation".strip()
    markup = page.render(title, data, BODY, SCRIPT)
    methods = [k for k in _METHODS if isinstance(data.get(k), dict)]
    flags = len((data.get("intrinsic") or {}).get("flags") or [])
    return title, markup, {"title": title, "symbol": symbol or None, "methods": methods, "flags": flags}


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
            raise InvalidInput(f"could not read valuation JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
