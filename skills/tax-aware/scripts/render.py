#!/usr/bin/env python3
"""Usage: render.py [--in tax-aware.json] --out page.html

Turns one ``tax-report.py`` (or ``tax.py``) result (a file, or stdin when ``--in`` is omitted) into a
self-contained interactive HTML page for the Artifact tool: the disclaimer line, stat tiles for the
realized short-term and long-term nets, the estimated liability and the loss carryforward; the realized
sales table with wash sales highlighted and the netting summary (plus the carryforward chain when prior
years carried a loss); a sortable open-lots table (symbol, date, gain, term, long-term date, days to
long-term, tax if sold) with search and a term filter; the harvesting candidates; one FIFO vs
highest-cost vs tax-minimal block per planned sale; the flags; and the "Not modelled" list. Prints
``{"out": path, "title": ..., "realized": n, "open_lots": n, "flags": n}``. Exit 2 on a missing or
malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the tax JSON; the page formats, sorts and filters, it never recomputes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Tax View"
DISCLAIMER = "Estimate for planning at the stated rates; not tax advice or a return."

BODY = f"""
<style>td.wash{{background:color-mix(in srgb,var(--warn) 14%,transparent)}}
.sale{{margin-bottom:18px}} .sale h3{{font-size:14px;font-weight:600;margin:0 0 6px}}
.notm{{margin:0;padding-left:18px;font-size:13px;color:var(--ink2)}} .notm li{{margin-bottom:3px}}</style>
<h1>Tax View</h1>
<p class="sub"><b>{DISCLAIMER}</b></p>
<p class="sub" id="asof">US federal view of the imported ledger; enable JavaScript to see the figures.</p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<section class="card"><h2 id="h-realized">Realized year to date</h2>
  <p class="sub">Shares already sold this year: what they fetched, what they cost, and whether the loss counts.</p>
  <div class="twrap" id="realized"></div><p class="note" id="realized-sum"></p>
  <div id="carry" hidden><h2 id="h-carry">Loss carryforward chain</h2><div class="twrap" id="carry-table"></div>
  <p class="note">Each year's net already includes the carry it absorbed from the year before. Prior years are replayed with raw gains (no wash-sale disallowance) at today's rates; an approximation for planning.</p></div>
</section>
<section class="card"><h2 id="h-lots">Open lots</h2>
  <p class="sub">Shares you still hold, one row per purchase, with the tax a sale would trigger today and when each becomes long-term.</p>
  <div class="controls">
    <input id="q" type="search" placeholder="Search symbol or account" aria-label="Search open lots">
    <select id="term" aria-label="Filter by term"><option value="">All terms</option><option value="short">Short-term</option><option value="long">Long-term</option></select>
    <span class="muted" id="count"></span>
  </div>
  <div class="twrap" id="lots"></div><p class="note" id="unreal"></p>
</section>
<section class="card"><h2 id="h-harvest">Harvesting candidates</h2>
  <p class="sub">Positions sitting at a loss large enough that selling them could offset gains elsewhere.</p>
  <div class="twrap" id="harvest"></div><p class="note" id="harvest-total"></p></section>
<section class="card" id="sales-card" hidden><h2 id="h-sales">Planned sales</h2>
  <p class="sub">For each sale you asked about: the tax under three ways of choosing which shares to sell.</p>
  <div id="sales"></div>
  <p class="note" id="sales-note">Specific-lot identification must be given to the broker at or before the sale; the default at most brokers is FIFO for stocks and average cost for mutual funds.</p></section>
<section data-help="none"><h2>Flags</h2>{page.FLAGS_INTRO}<ul class="flags" id="flags"></ul></section>
<section class="card" data-help="none"><h2>Not modelled</h2><p class="sub">Rules this estimate leaves out; any of them can change the real bill.</p><ul class="notm" id="notm">
  <li>Qualified-dividend holding-period test</li>
  <li>REIT and bond-fund distributions (ordinary)</li>
  <li>AMT</li>
  <li>State-specific rules</li>
  <li>Tax-lot methods already elected at the broker</li>
  <li>0% / 20% long-term brackets by income</li>
  <li>Foreign tax credits</li>
  <li>Crypto: the ledger has no crypto asset class; wash-sale rules do not currently apply to crypto under 2026 rules (verify current law) and basis tracking for crypto is entirely on the user</li>
</ul></section>
<p class="note">{DISCLAIMER} Lots are matched FIFO per account and symbol; long-term means held more than one year; a loss is a wash sale when substantially identical shares were bought within 30 days before or after the sale in any account, and the disallowed amount is added to the replacement lot's basis. Dividends are assumed qualified and interest ordinary. General information at the stated rates, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, S = D.summary || {}, R = D.rates || {}, F = FA;
  const g = id => document.getElementById(id);
  // glossary terms this page needs beyond the shared list (plain sentence, link to more)
  Object.assign(FA.glossary, {
    "short-term gain": ["A gain on something held one year or less, taxed at the same rates as wages, which are higher than long-term rates.", "https://www.investopedia.com/terms/s/short-term-gain.asp"],
    "realized gain": ["Profit or loss locked in by actually selling; only realized gains are taxed.", "https://www.investopedia.com/terms/r/realizedprofit.asp"],
    "capital gains tax": ["Tax on the profit from selling an investment; the rate depends on how long it was held.", "https://www.investopedia.com/terms/c/capital_gains_tax.asp"],
    "holding period": ["How long you have owned the shares; more than a year makes a sale long-term.", "https://www.investopedia.com/terms/h/holdingperiod.asp"],
    "qualified dividend": ["A dividend that meets IRS holding rules and is taxed at the lower long-term rate instead of as ordinary income.", "https://www.investopedia.com/terms/q/qualifieddividend.asp"],
    "ordinary income": ["Income taxed at the regular bracket rates: wages, interest and short-term gains.", "https://www.investopedia.com/terms/o/ordinaryincome.asp"],
    "niit": ["Net investment income tax: an extra 3.8% federal tax on investment income above an income threshold.", "https://www.investopedia.com/terms/n/netinvestmentincome.asp"],
    "capital loss deduction": ["Up to $3,000 of net capital losses a year can be subtracted from ordinary income; the rest carries forward.", "https://www.investopedia.com/terms/c/capital-loss-carryover.asp"],
    "specific lot identification": ["Telling the broker exactly which shares to sell, instead of the default oldest-first order.", "https://www.investopedia.com/terms/s/specific-share-identification.asp"],
    "highest cost": ["Selling the most expensive shares first, which gives the smallest gain (or largest loss) at today's price.", "https://www.investopedia.com/terms/h/hifo.asp"],
    "amt": ["Alternative minimum tax: a parallel federal tax calculation that can raise the bill for some taxpayers.", "https://www.investopedia.com/terms/a/alternativeminimumtax.asp"],
    "foreign tax credit": ["A credit for tax already paid to another country on foreign investment income.", "https://www.investopedia.com/terms/f/foreign-tax-credit.asp"],
  });
  // table headers built by FA.table are plain text; swap in the glossary markup after the table exists (the header is built once)
  const termHeads = (root, cols) => {
    root.querySelectorAll('th[data-key]').forEach(th => { const c = cols.find(x => x.key === th.dataset.key); if (c && c.term) th.innerHTML = FA.term(c.term, c.label); });
    FA.armTerms(root);
  };
  const L = D.ledger || {};
  let sub = `As of ${F.esc(D.as_of || '—')} · tax year ${F.esc(D.year ?? '—')} · rates: ${FA.term('short-term gain', 'short-term')} ${F.pct(R.short_term)} · ${FA.term('long-term gain', 'long-term')} ${F.pct(R.long_term)} · state ${F.pct(R.state)} · ${FA.term('niit', 'NIIT')} ${F.pct(R.niit)}`;
  if (L.transactions_used != null) sub += ` · ${F.esc(L.transactions_used)} ledger rows` + ((L.accounts || []).length ? ` across ${F.esc(L.accounts.join(', '))}` : '');
  if ((D.missing_prices || []).length) sub += ` · no price for ${F.esc(D.missing_prices.join(', '))}`;
  g('asof').innerHTML = sub;
  FA.explain(g('explain'), `<p>This page estimates the US federal tax picture of the trades in your imported ledger for tax year ${F.esc(D.year ?? '—')}. <b>Realized</b> gains come from shares you already sold this year, split into ${FA.term('short-term gain', 'short-term')} and ${FA.term('long-term gain', 'long-term')} because they are taxed at different rates; a ${FA.term('wash sale')} is a loss the IRS does not let you count yet.</p>` +
    `<p><b>Open lots</b> are the shares you still hold, one ${FA.term('tax lot', 'lot')} per purchase, with the tax each would cost if sold today. <b>Harvesting candidates</b> are losing positions whose sale could offset gains (${FA.term('tax-loss harvesting')}). Every number is worked out from the ledger and the rates shown above; nothing is fetched from the IRS or your broker.</p>` +
    `<p>The caveat that matters most: the flat rates above stand in for your real brackets, and state-specific rules and the items under Not modelled are left out, so read this as a planning estimate, not a return.</p>`);
  // section headings (static text stays for readers without JavaScript)
  g('h-realized').innerHTML = `${FA.term('realized gain', 'Realized')} year to date`;
  g('h-carry').innerHTML = `${FA.term('loss carryforward', 'Loss carryforward')} chain`;
  g('h-lots').innerHTML = `Open ${FA.term('tax lot', 'lots')}`;
  g('h-harvest').innerHTML = `${FA.term('tax-loss harvesting', 'Harvesting')} candidates`;
  g('notm').innerHTML = [
    `${FA.term('qualified dividend', 'Qualified-dividend')} ${FA.term('holding period', 'holding-period')} test`,
    `${FA.term('reit', 'REIT')} and bond-fund distributions (${FA.term('ordinary income', 'ordinary')})`,
    FA.term('amt', 'AMT'),
    'State-specific rules',
    `${FA.term('tax lot', 'Tax-lot')} methods already elected at the broker`,
    `0% / 20% ${FA.term('long-term gain', 'long-term')} brackets by income`,
    FA.term('foreign tax credit', 'Foreign tax credits'),
    `Crypto: the ledger has no crypto asset class; ${FA.term('wash sale', 'wash-sale')} rules do not currently apply to crypto under 2026 rules (verify current law) and basis tracking for crypto is entirely on the user`,
  ].map(t => `<li>${t}</li>`).join('');
  FA.armTerms(document);
  const term = t => t === 'long' ? 'Long' : t === 'short' ? 'Short' : F.esc(t || '—');
  // tiles
  const realized = D.realized || [];
  const n = t => realized.filter(r => r.term === t).length;
  const carryD = (S.deductible_against_income || 0) > 0 ? `${F.money(S.deductible_against_income)} deductible against income this year`
    : (S.prior_year_net_losses || 0) > 0 ? `prior-year net losses ${F.money(S.prior_year_net_losses)}` : 'no loss carried forward';
  const tiles = [
    [FA.term('short-term gain', 'Short-term net'), `<span class="${F.cls(S.short_term_net)}">${F.moneyS(S.short_term_net)}</span>`, `${n('short')} short-term sales`],
    [FA.term('long-term gain', 'Long-term net'), `<span class="${F.cls(S.long_term_net)}">${F.moneyS(S.long_term_net)}</span>`, `${n('long')} long-term sales`],
    ['Estimated tax', F.money(S.estimated_tax), `${FA.term('capital gains tax', 'capital gains')} ${F.money(S.capital_gains_tax)} · dividends ${F.money(S.dividend_tax)} · interest ${F.money(S.interest_tax)}`],
    [FA.term('loss carryforward', 'Loss carryforward'), F.money(S.loss_carryforward), carryD],
  ];
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  FA.armTerms(g('tiles'));
  // realized
  const wash = (v, r) => (r.wash_sale ? 'wash ' : '') + F.cls(v);
  const washTxt = (v, r) => (r.wash_sale ? 'wash ' : '');
  const realizedCols = [
    {key: 'symbol', label: 'Symbol', left: true, fmt: v => `<b>${F.esc(v)}</b>`, cls: washTxt},
    {key: 'account_id', label: 'Account', left: true, fmt: v => F.esc(v || '—'), cls: washTxt},
    {key: 'sell_date', label: 'Sold', left: true, fmt: v => F.esc(v), cls: washTxt},
    {key: 'units', label: 'Units', fmt: v => F.num(v, 3), cls: washTxt},
    {key: 'proceeds', label: 'Proceeds', fmt: v => F.money(v), cls: washTxt},
    {key: 'cost', label: 'Cost', term: 'cost basis', fmt: v => F.money(v), cls: washTxt},
    {key: 'gain', label: 'Gain', term: 'realized gain', fmt: v => F.moneyS(v), cls: wash},
    {key: 'holding_days', label: 'Held (days)', term: 'holding period', fmt: v => F.num(v, 0), cls: washTxt},
    {key: 'term', label: 'Term', term: 'long-term gain', left: true, fmt: term, cls: washTxt},
    {key: 'wash_sale', label: 'Wash sale', term: 'wash sale', left: true, fmt: (v, r) => v ? `yes<span class="muted"> · bought ${F.esc(r.wash_buy_date || '—')}</span>` : 'no', cls: washTxt},
    {key: 'disallowed', label: 'Disallowed', term: 'wash sale', fmt: v => F.money(v), cls: washTxt},
    {key: 'allowed_gain', label: 'Allowed gain', term: 'realized gain', fmt: v => F.moneyS(v), cls: wash},
  ];
  if (realized.length) { F.table(g('realized'), realizedCols, realized, {sortKey: 'sell_date', desc: false}); termHeads(g('realized'), realizedCols); }
  else g('realized').innerHTML = `<span class="muted">No sales in ${F.esc(D.year ?? 'this year')}.</span>`;
  let sum = `${FA.term('short-term gain', 'Short-term')} net ${F.moneyS(S.short_term_net)} · ${FA.term('long-term gain', 'long-term')} net ${F.moneyS(S.long_term_net)} · ${FA.term('wash sale', 'disallowed')} ${F.money(S.disallowed_losses)} · net capital gain ${F.moneyS(S.net_capital_gain)} taxed as ${F.esc(S.taxed_as || '—')} → estimated ${FA.term('capital gains tax', 'capital-gains tax')} ${F.money(S.capital_gains_tax)}. Dividends ${F.money(S.dividends)} (assumed ${FA.term('qualified dividend', 'qualified')}, tax ${F.money(S.dividend_tax)}) · interest ${F.money(S.interest)} (tax ${F.money(S.interest_tax)}). Estimated total ${F.money(S.estimated_tax)}.`;
  if ((S.loss_carryforward || 0) > 0 || (S.deductible_against_income || 0) > 0) sum += ` Net loss: ${F.money(S.deductible_against_income)} deductible against ${FA.term('ordinary income')} (saves ${F.money(S.ordinary_income_tax_saved)}), ${F.money(S.loss_carryforward)} ${FA.term('loss carryforward', 'carried forward')}.`;
  if (D.prior_year_sales_ignored) sum += ` ${F.esc(D.prior_year_sales_ignored)} earlier-year sale${D.prior_year_sales_ignored === 1 ? '' : 's'} not in this year's table.`;
  g('realized-sum').innerHTML = sum;
  FA.armTerms(g('realized-sum'));
  const hist = S.carryforward_history || [];
  if ((S.prior_year_net_losses || 0) > 0 && hist.length) { g('carry').hidden = false;
    g('carry-table').innerHTML = `<table><thead><tr><th class="l">Year</th><th>Net</th><th>${FA.term('capital loss deduction', 'Deduction')}</th><th>${FA.term('loss carryforward', 'Carryforward')}</th></tr></thead><tbody>` + hist.map(h => `<tr><td class="l">${F.esc(h.year)}</td><td class="${F.cls(h.net)}">${F.moneyS(h.net)}</td><td>${F.money(h.deductible)}</td><td>${F.money(h.carryforward)}</td></tr>`).join('') + '</tbody></table>';
    FA.armTerms(g('carry-table')); }
  // open lots
  const lots = D.open_lots || [];
  const lotCols = [
    {key: 'symbol', label: 'Symbol', left: true, fmt: v => `<b>${F.esc(v)}</b>`},
    {key: 'account_id', label: 'Account', left: true, fmt: v => F.esc(v || '—')},
    {key: 'buy_date', label: 'Bought', left: true, fmt: v => F.esc(v)},
    {key: 'units', label: 'Units', fmt: v => F.num(v, 3)},
    {key: 'cost', label: 'Cost', term: 'cost basis', fmt: (v, r) => F.money(v) + (r.basis_adjustment ? `<span class="muted"> incl. ${F.money(r.basis_adjustment)} wash adj.</span>` : '')},
    {key: 'price', label: 'Price', fmt: v => F.money(v)},
    {key: 'value', label: 'Value', fmt: v => F.money(v)},
    {key: 'unrealized', label: 'Unrealized', term: 'unrealized p&l', fmt: v => F.moneyS(v), cls: F.cls},
    {key: 'term', label: 'Term', term: 'holding period', left: true, fmt: term},
    {key: 'long_term_date', label: 'Long-term date', term: 'long-term gain', left: true, fmt: v => F.esc(v || '—')},
    {key: 'days_to_long_term', label: 'Days to long-term', term: 'long-term gain', fmt: (v, r) => r.term === 'long' ? '<span class="muted">—</span>' : F.num(v, 0)},
    {key: 'tax_if_sold', label: 'Tax if sold', term: 'capital gains tax', fmt: v => F.moneyS(v)},
    {key: 'tax_if_sold_long', label: 'Tax if long-term', term: 'long-term gain', fmt: v => F.moneyS(v)},
  ];
  if (lots.length) {
    const tbl = F.table(g('lots'), lotCols, lots, {sortKey: 'symbol', desc: false, onDraw: vis => { g('count').textContent = `${vis.length} of ${lots.length} lots`; FA.armTerms(g('lots')); }});
    termHeads(g('lots'), lotCols);
    const sel = g('term'); sel.addEventListener('change', () => tbl.setFilter(r => !sel.value || r.term === sel.value));
    g('q').addEventListener('input', e => tbl.setQuery(e.target.value));
  } else g('lots').innerHTML = '<span class="muted">No open lots.</span>';
  const U = D.unrealized || {};
  g('unreal').innerHTML = `${FA.term('unrealized p&l', 'Unrealized')}: short-term ${F.moneyS(U.short)} · long-term ${F.moneyS(U.long)} · total ${F.moneyS(U.total)} · tax if everything were sold now ${F.moneyS(U.tax_if_all_sold)}.`;
  FA.armTerms(g('unreal'));
  // harvesting
  const H = D.harvest_candidates || [], HT = D.harvest_total || {};
  const harvestCols = [
    {key: 'symbol', label: 'Symbol', left: true, fmt: v => `<b>${F.esc(v)}</b>`},
    {key: 'units', label: 'Units', fmt: v => F.num(v, 3)},
    {key: 'cost', label: 'Cost', term: 'cost basis', fmt: v => F.money(v)},
    {key: 'value', label: 'Value', fmt: v => F.money(v)},
    {key: 'unrealized', label: 'Unrealized', term: 'unrealized p&l', fmt: v => F.moneyS(v), cls: F.cls},
    {key: 'pct', label: '%', fmt: v => F.pct(v, 1, true), cls: F.cls},
    {key: 'term', label: 'Term', term: 'holding period', left: true, fmt: term},
    {key: 'tax_benefit', label: 'Est. benefit', term: 'tax-loss harvesting', fmt: v => F.money(v)},
    {key: 'last_buy_date', label: 'Last buy', left: true, fmt: v => F.esc(v || '—')},
    {key: 'warning', label: 'Wash-sale risk', term: 'wash sale', left: true, fmt: (v, r) => v ? F.esc(v) : r.recent_buy_within_30d ? 'bought within 30 days' : '<span class="muted">—</span>'},
  ];
  if (H.length) { F.table(g('harvest'), harvestCols, H, {sortKey: 'unrealized', desc: false}); termHeads(g('harvest'), harvestCols);
    g('harvest-total').innerHTML = `Total: losses ${F.moneyS(HT.losses)} · estimated tax benefit ${F.money(HT.tax_benefit)}. The benefit assumes there is a gain or the ${FA.term('capital loss deduction', '$3,000 deduction')} to offset.`;
    FA.armTerms(g('harvest-total'));
  } else { g('harvest').innerHTML = '<span class="muted">No positions meet the loss thresholds.</span>'; g('harvest-total').textContent = ''; }
  // planned sales
  const sels = (D.lot_selections || []).length ? D.lot_selections : (D.lot_selection ? [D.lot_selection] : []);
  if (sels.length) { g('sales-card').hidden = false; const root = g('sales'); root.innerHTML = '';
    const lotsTxt = m => (m.lots || []).map(l => `${F.esc(l.buy_date)} × ${F.num(l.units, 3)} @ ${F.money(l.cost)} (${F.moneyS(l.gain)}, ${l.term})`).join('; ');
    sels.forEach(s => {
      const methods = [['FIFO', s.fifo, F.S[0], FA.term('fifo', 'FIFO')], ['Highest cost', s.highest_cost, F.S[1], FA.term('highest cost', 'Highest cost')], ['Tax-minimal', s.minimal, F.S[2], 'Tax-minimal']].filter(m => m[1]);
      const box = F.el('div', {class: 'sale'});
      box.appendChild(F.el('h3', {}, `Sell ${F.num(s.units, 3)} ${F.esc(s.symbol)} at ${F.money(s.price)}`));
      const bars = F.el('div'); box.appendChild(bars);
      F.bars(bars, methods.map(([name, m, color]) => ({label: name, share: Math.abs(m.tax || 0), color, text: `tax ${F.moneyS(m.tax)}`, tip: `<b>${name}</b> gain ${F.moneyS(m.gain)} · tax ${F.moneyS(m.tax)}`})));
      const twrap = F.el('div', {class: 'twrap'});
      twrap.innerHTML = `<table><thead><tr><th class="l">Method</th><th class="l">${FA.term('tax lot', 'Lots')} (bought × units @ ${FA.term('cost basis', 'cost')})</th><th>Gain</th><th>Tax</th></tr></thead><tbody>` + methods.map(([name, m, color, label]) => `<tr><td class="l">${label}</td><td class="l" style="white-space:normal">${lotsTxt(m)}</td><td class="${F.cls(m.gain)}">${F.moneyS(m.gain)}</td><td>${F.moneyS(m.tax)}</td></tr>`).join('') + '</tbody></table>';
      box.appendChild(twrap);
      box.appendChild(F.el('p', {class: 'note'}, `${FA.term('highest cost', 'Highest-cost')} lots save ${F.money(s.tax_saved_vs_fifo)} vs ${FA.term('fifo', 'FIFO')}; the tax-minimal order saves ${F.money(s.tax_saved_vs_minimal)} vs FIFO.`));
      root.appendChild(box);
    });
    g('sales-note').innerHTML = `${FA.term('specific lot identification', 'Specific-lot identification')} must be given to the broker at or before the sale; the default at most brokers is ${FA.term('fifo', 'FIFO')} for stocks and average cost for mutual funds.`;
    FA.armTerms(g('sales-card')); }
  // card help
  const card = id => g(id).parentElement;
  const carryIn = (S.short_term_net || 0) + (S.long_term_net || 0) - (S.net_capital_gain || 0);
  const netLoss = (S.deductible_against_income || 0) > 0 || (S.loss_carryforward || 0) > 0;
  F.help(card('h-realized'), {lead: 'Gains and losses you have already locked in by selling this year, and the tax they add.',
    sections: [{title: 'How the year nets out', html: F.flow([{label: 'short-term net', value: F.moneyS(S.short_term_net)}, {op: '+', label: 'long-term net', value: F.moneyS(S.long_term_net)}, ...(Math.abs(carryIn) >= 0.005 ? [{op: '\u2212', label: 'loss carried in from earlier years', value: F.money(carryIn)}] : []), {op: '=', label: 'net capital gain', value: F.moneyS(S.net_capital_gain)}]) +
        `<p>Shares held a year or less are short-term and taxed like wages (${F.pct(R.short_term)} here); held longer, long-term at a lower rate (${F.pct(R.long_term)}). A loss from a wash sale is set aside, not lost: it is added to the cost of the shares bought back.</p>`},
      {title: 'When losses are bigger than gains', html: netLoss ? F.flow([{label: 'deducted from income this year', value: F.money(S.deductible_against_income)}, {op: '+', label: 'carried to next year', value: F.money(S.loss_carryforward)}, {op: '=', label: 'net loss', value: F.money((S.deductible_against_income || 0) + (S.loss_carryforward || 0))}]) + '<p>Up to $3,000 a year comes off ordinary income; the rest waits for future years.</p>'
        : '<p>Up to $3,000 of net loss a year comes off ordinary income, and the rest carries to later years. This year nets to a gain, so nothing is deducted.</p>'}]});
  const shortLots = lots.filter(l => l.term === 'short' && F.isNum(l.days_to_long_term) && l.days_to_long_term > 0).sort((a, b) => a.days_to_long_term - b.days_to_long_term);
  const soon = shortLots.find(l => F.isNum(l.tax_if_sold) && F.isNum(l.tax_if_sold_long) && l.tax_if_sold > 0) || shortLots[0];
  const gainLot = soon && F.isNum(soon.tax_if_sold) && F.isNum(soon.tax_if_sold_long) && soon.tax_if_sold > 0;
  F.help(card('h-lots'), {lead: 'The shares you still hold, one row per purchase, with the tax a sale would trigger today.',
    sections: soon ? [{title: `When ${soon.symbol} turns long-term`, html: `<p>The ${F.esc(soon.symbol)} shares bought ${F.esc(soon.buy_date)} become long-term on ${F.esc(soon.long_term_date)}, in ${F.num(soon.days_to_long_term, 0)} days.</p>` +
        (gainLot ? F.flow([{label: 'tax if sold today', value: F.money(soon.tax_if_sold)}, {op: '−', label: 'tax once long-term', value: F.money(soon.tax_if_sold_long)}, {op: '=', label: 'lower by', value: F.money(soon.tax_if_sold - soon.tax_if_sold_long)}])
          : '<p>This lot is at a loss, so selling it would lower the bill rather than add to it; a short-term loss offsets income taxed at the higher rate.</p>')}]
      : [{title: 'Short-term and long-term', html: '<p>A lot held more than one year is long-term and taxed at the lower rate; the Long-term date column shows when each crosses over.</p>'}]});
  const topH = H.length ? [...H].sort((a, b) => (a.unrealized || 0) - (b.unrealized || 0))[0] : null;
  F.help(card('h-harvest'), {lead: 'Holdings at a loss that, if sold, could offset gains elsewhere and lower the tax bill.',
    sections: [...(topH ? [{title: `The estimate, using ${topH.symbol}`, html: (topH.term === 'short' || topH.term === 'long' ? F.flow([{label: 'loss if sold', value: F.moneyS(topH.unrealized)}, {op: '\u00d7', label: `${topH.term}-term rate with state${R.niit ? ' and NIIT' : ''}`, value: F.pct((topH.term === 'long' ? R.long_term : R.short_term) + (R.state || 0) + (R.niit || 0))}, {op: '=', label: 'estimated tax saved', value: F.money(topH.tax_benefit)}])
        : `<p>Estimated tax saved: ${F.money(topH.tax_benefit)}, from lots held both short and long term.</p>`) + '<p>The saving only happens if there is a gain, or the $3,000 income deduction, for the loss to offset.</p>'}] : []),
      {title: 'The 30-day rule', html: '<p>Buying the same or a substantially identical security within 30 days before or after the sale makes it a wash sale: the loss is pushed into the new shares’ cost instead of counting now. The Wash-sale risk column marks recent purchases.</p>'}]});
  if (sels.length) { const s0 = sels[0];
    F.help(g('sales-card'), {lead: 'For each sale you asked about, the tax under different ways of choosing which shares to sell.',
      sections: [{title: `Selling ${F.num(s0.units, 3)} ${s0.symbol}`, html: (s0.fifo && s0.highest_cost ? F.flow([{label: 'oldest first (FIFO)', value: F.moneyS(s0.fifo.tax)}, {op: '−', label: 'most expensive first', value: F.moneyS(s0.highest_cost.tax)}, {op: '=', label: 'difference', value: F.money(s0.tax_saved_vs_fifo)}]) : '') +
        '<p>Same shares, same price: only the purchase lots counted as sold change, and with them the gain. The broker needs the lot choice at or before the sale.</p>'}]}); }
  // flags
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def build(report: dict) -> str:
    if not isinstance(report, dict) or not isinstance(report.get("summary"), dict) or "open_lots" not in report:
        raise InvalidInput("input must be a tax-report.py or tax.py result (a JSON object with summary and open_lots)")
    return page.render(TITLE, report, BODY, SCRIPT)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            report = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read tax JSON: {exc}") from exc
        out = page.write(ns.out, build(report))
        return {
            "out": str(out),
            "title": TITLE,
            "realized": len(report.get("realized") or []),
            "open_lots": len(report.get("open_lots") or []),
            "flags": len(report.get("flags") or []),
        }

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
