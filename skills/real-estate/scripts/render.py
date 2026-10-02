#!/usr/bin/env python3
"""Usage: render.py [--in result.json] --out page.html

Turns one ``realestate.py`` or ``reit.py`` result (a file, or stdin when ``--in`` is omitted) into a
self-contained interactive HTML page for the Artifact tool. One renderer handles every calculator: it
detects which output is present by its keys and draws only the matching sections — mortgage
(``schedule``: payment/PITI/interest tiles, a balance-vs-interest-vs-principal line chart by year,
the sortable amortization schedule, the extra-payment and PMI lines), refinance
(``current_payment``: breakeven-month tile and the cumulative-savings line from ``savings_path``),
rent vs buy (``by_year``: crossover line chart of buy vs rent net worth and the year table),
rental underwriting (``noi``: NOI / cap rate / DSCR / cash-on-cash / IRR tiles, the metrics table,
the projection cash-flow table and the appreciation × rent-growth scenario heatmap), affordability
(``max_housing_payment``: tiles) and REIT metrics (``ffo_per_share``: tiles, the multiples table,
``notes`` and ``inputs`` when reit.py supplied them). Flags last, then the skill's "not modelled"
note. Prints ``{"out": path, "title": ..., "calculators": [...], "flags": n}``. Exit 2 when the input
is missing, malformed, or matches no calculator.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the JSON; the page formats, sorts and filters, it never recomputes.
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Real Estate Calculator"
# (calculator, key that identifies its output, page heading)
DETECT = (
    ("mortgage", "schedule", "Mortgage and amortization"),
    ("refinance", "current_payment", "Refinance breakeven"),
    ("rent_vs_buy", "by_year", "Rent vs buy"),
    ("rental", "noi", "Rental underwriting"),
    ("affordability", "max_housing_payment", "Affordability"),
    ("reit", "ffo_per_share", "REIT metrics"),
)

BODY = """
<h1>{heading}</h1>
<p class="sub" id="headline">{headline}</p>
<div id="explain"></div>
<div class="controls" id="chips" aria-label="Assumptions"></div>
<div class="tiles" id="tiles"></div>
<section class="card" id="mortgage-chart" hidden><h2 id="h-mortgage-chart">Balance, interest and principal by year</h2><p class="sub" id="mortgage-sub"></p><div id="mortgage-lines"></div><p class="note" id="mortgage-extra"></p></section>
<section class="card" id="mortgage-card" hidden><h2 id="h-schedule">Amortization schedule</h2><p class="sub">Every year of the loan: payments, interest, principal and the balance left.</p><div class="twrap" id="schedule"></div></section>
<section class="card" id="refi-chart" hidden><h2 id="h-refi-chart">Cumulative savings</h2><p class="sub" id="refi-sub">Cash kept by the end of each year: current payments no longer owed, less new payments made and closing costs. It crosses zero at the breakeven month and ends at the lifetime delta.</p><div id="refi-lines"></div></section>
<section class="card" id="refi-card" hidden><h2 id="h-refi">Refinance figures</h2><p class="sub">The current and new loan side by side, and what changes over their full terms.</p><div class="twrap" id="refi"></div><p class="note" id="refi-note"></p></section>
<section class="card" id="rvb-chart" hidden><h2 id="h-rvb-chart">Net worth: buy vs rent</h2><p class="sub" id="rvb-sub"></p><div id="rvb-lines"></div></section>
<section class="card" id="rvb-card" hidden><h2 id="h-rvb">Year by year</h2><p class="sub">The buy-versus-rent comparison as a table, one row a year.</p><div class="twrap" id="rvb"></div></section>
<div class="grid2" id="rental-grid" hidden>
  <div class="card"><h2 id="h-rental">Underwriting</h2><p class="sub" id="rental-sub"></p><div class="twrap" id="rental"></div></div>
  <div class="card" id="proj-card" hidden><h2 id="h-proj">Hold-period projection</h2><p class="sub" id="proj-sub"></p><div class="twrap" id="proj"></div></div>
</div>
<section class="card" id="scen-card" hidden><h2 id="h-scen">Scenarios: appreciation × rent growth</h2><p class="sub" id="scen-sub"></p><div class="controls" id="scen-metric"></div><div id="scen"></div></section>
<section class="card" id="afford-card" hidden><h2 id="h-afford">Affordability</h2><p class="sub" id="afford-sub"></p><div class="twrap" id="afford"></div></section>
<section class="card" id="reit-card" hidden><h2 id="h-reit">REIT multiples</h2><p class="sub" id="reit-sub"></p><div class="twrap" id="reit"></div><div class="twrap" id="reit-inputs"></div><ul class="news" id="reit-notes"></ul></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">The mortgage model is fixed-rate only: ARM and interest-only loans are not modelled. PMI is charged until the balance crosses 80% LTV (lenders auto-cancel at 78%). Not modelled: income-tax effects (mortgage-interest deduction, depreciation, capital-gains exclusion), transaction friction beyond the closing rates given, local rent control or tax reassessment rules unless supplied, and adjustable-rate or interest-only mortgages. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, g = id => document.getElementById(id);
  // terms this page needs that the shared glossary lacks (page.py is frozen)
  Object.assign(FA.glossary, {
    "principal": ["The amount borrowed, or the part of a payment that reduces it rather than paying interest.", "https://www.investopedia.com/terms/p/principal.asp"],
    "pmi": ["Private mortgage insurance: a monthly charge lenders add when the down payment is under 20%; it protects the lender, not you.", "https://www.investopedia.com/terms/m/mortgage-insurance.asp"],
    "ltv": ["Loan-to-value: the loan balance as a share of the home's value; PMI ends once it falls to 80%.", "https://www.investopedia.com/terms/l/loantovalue.asp"],
    "hoa": ["Homeowners association dues: a monthly fee for shared upkeep in a condo or planned community.", "https://www.investopedia.com/terms/h/hoa.asp"],
    "property tax": ["The yearly tax on the home's assessed value, paid to the local government.", "https://www.investopedia.com/terms/p/propertytax.asp"],
    "closing costs": ["One-off fees paid to complete a mortgage or sale: lender, title, appraisal and recording charges.", "https://www.investopedia.com/terms/c/closingcosts.asp"],
    "refinance": ["Replacing an existing mortgage with a new one, usually to get a lower rate or payment.", "https://www.investopedia.com/terms/r/refinance.asp"],
    "break-even point": ["The point where what you have saved equals what it cost to get the savings; past it you come out ahead.", "https://www.investopedia.com/terms/b/breakevenpoint.asp"],
    "home equity": ["The home's value minus what is still owed on it.", "https://www.investopedia.com/terms/h/home_equity.asp"],
    "net worth": ["What you own minus what you owe.", "https://www.investopedia.com/terms/n/networth.asp"],
    "appreciation": ["The yearly rise in the home's value assumed by the calculation.", "https://www.investopedia.com/terms/a/appreciation.asp"],
    "vacancy rate": ["The share of the year the property is assumed empty and earning no rent.", "https://www.investopedia.com/terms/v/vacancy-rate.asp"],
    "operating expenses": ["The running costs of owning a rental (tax, insurance, upkeep, management), before the mortgage.", "https://www.investopedia.com/terms/o/operating_expense.asp"],
    "operating expense ratio": ["Operating expenses divided by the rent collected; the share of income eaten by running costs.", "https://www.investopedia.com/terms/o/operating-expense-ratio.asp"],
    "debt service": ["The year's loan payments, principal and interest together.", "https://www.investopedia.com/terms/d/debtservice.asp"],
    "grm": ["Gross rent multiplier: price divided by a year's rent; a quick, expense-blind price check.", "https://www.investopedia.com/terms/g/gross-rent-multiplier.asp"],
    "1% rule": ["A rule of thumb that monthly rent should be at least 1% of the price for the numbers to work.", "https://www.investopedia.com/terms/o/one-percent-rule.asp"],
    "capital expenditure": ["Big-ticket replacements such as a roof or furnace, set aside as a yearly reserve.", "https://www.investopedia.com/terms/c/capitalexpenditure.asp"],
    "front-end ratio": ["The housing payment as a share of gross monthly income; lenders commonly cap it at 28%.", "https://www.investopedia.com/terms/f/front-endratio.asp"],
    "back-end ratio": ["Housing payment plus other debt payments as a share of gross income; lenders commonly cap it at 36%.", "https://www.investopedia.com/terms/b/back-endratio.asp"],
    "28/36 rule": ["Spend at most 28% of gross income on housing and 36% on all debt; the standard lender guideline.", "https://www.investopedia.com/terms/t/twenty-eight-thirty-six-rule.asp"],
    "depreciation": ["An accounting charge that spreads a building's cost over its life; not a cash cost, which is why REIT metrics add it back.", "https://www.investopedia.com/terms/d/depreciation.asp"],
  });
  const T = (key, label) => FA.term(key, label);
  const head = (id, html) => { const h = g(id); if (h) { h.innerHTML = html; F.armTerms(h); } };
  const sub = (id, html) => { const h = g(id); if (h) { h.innerHTML = html; F.armTerms(h); } };
  // FA.table and FA.lines escape their labels, so terms go into the header cells / legend after they are built
  const termHeads = (root, map) => { root.querySelectorAll('th').forEach(th => { const h = map[th.dataset.key]; if (h) th.innerHTML = h; });
    F.armTerms(root); };
  const termLegend = (root, map) => { root.querySelectorAll('.legend span').forEach(sp => { const h = map[sp.textContent.trim()]; if (h) { const i = sp.querySelector('i'); sp.innerHTML = (i ? i.outerHTML : '') + h; } }); F.armTerms(root); };
  const tile = (k, v, d) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d || ''}</div></div>`;
  const kv = rows => '<table><tbody>' + rows.map(([k, v]) => `<tr><td class="l">${k}</td><td>${v}</td></tr>`).join('') + '</tbody></table>';
  const chip = (label, v) => { if (v == null) return; const c = F.el('span', {class: 'chip'}, `${label} <b>${F.esc(v)}</b>`); g('chips').appendChild(c); F.armTerms(c); };
  const m = v => F.money(v, 2), m0 = v => F.money(v, 0), k$ = v => '$' + F.num(v / 1000, 0) + 'k';
  const yrFmt = x => 'yr ' + Math.round(x);
  const tiles = [], explain = [];
  const intro = '<p>Every number on this page comes from the real-estate calculator at the assumptions shown in the chips; the page only formats it. Hover or tap a word with a dotted underline for a plain-words meaning, and the ⓘ beside each card’s title explains how that card works.</p>';

  if ('schedule' in D && Array.isArray(D.schedule)) {
    explain.push(`<p>This is a fixed-rate mortgage of ${m0(D.principal)} over ${F.num(D.months, 0)} months. The monthly payment covers interest and ${T('principal')}; ${T('piti', 'PITI')} adds ${T('property tax')}, insurance${D.hoa_monthly > 0 ? ', ' + T('hoa', 'HOA dues') : ''}${D.pmi_monthly > 0 ? ' and ' + T('pmi', 'PMI') : ''} to show the full monthly housing cost.</p>
      <p>The chart shows ${T('amortization')}: early on most of each payment is interest and the balance falls slowly; later the split flips. The table below lists every year's interest, principal and remaining balance. Caveat: a fixed rate only; adjustable-rate and interest-only loans, and the tax deduction on mortgage interest, are not modelled.</p>`);
    chip('Rate', F.pct(D.rate, 2)); chip('Term', `${F.num(D.months, 0)} months`); chip(T('principal', 'Principal'), m0(D.principal)); if (D.down_payment_pct != null) chip('Down payment', F.pct(D.down_payment_pct, 1));
    tiles.push(tile('Monthly payment', m(D.payment), `${T('principal')} and interest`), tile(T('piti', 'PITI'), m(D.piti), `tax ${m(D.tax_monthly)} · insurance ${m(D.insurance_monthly)} · ${T('hoa', 'HOA')} ${m(D.hoa_monthly)}${D.pmi_monthly > 0 ? ' · ' + T('pmi', 'PMI') + ' ' + m(D.pmi_monthly) : ''}`),
      tile('Total interest', m0(D.total_interest), `total paid ${m0(D.total_paid)} over ${F.num(D.months, 0)} months`));
    if (D.pmi_monthly > 0) tiles.push(tile(T('pmi', 'PMI'), m(D.pmi_monthly) + '/mo', `drops off in year ${F.esc(D.pmi_off_year ?? '—')} · total ${m0(D.pmi_total)}`));
    g('mortgage-chart').hidden = false;
    sub('mortgage-sub', `Each year's interest paid and ${T('principal')} repaid, and the balance still owed at year end.`);
    F.lines(g('mortgage-lines'), {height: 280, xFmt: yrFmt, yFmt: k$, zeroLine: true, aria: 'Balance, interest and principal by year', series: [
      {name: 'Balance', color: F.S[0], points: D.schedule.map(r => [r.year, r.balance])},
      {name: 'Interest (year)', color: F.S[1], points: D.schedule.map(r => [r.year, r.interest])},
      {name: 'Principal (year)', color: F.S[2], points: D.schedule.map(r => [r.year, r.principal])}]});
    const X = D.with_extra, notes = [];
    if (X) notes.push(`+${m(X.extra_payment)}/month pays off in ${F.num(X.months, 0)} months (${F.num(X.months_saved, 0)} sooner) and saves ${m0(X.interest_saved)} interest (${m0(X.total_interest)} total).`);
    if (D.pmi_monthly > 0) notes.push(`${T('pmi', 'PMI')} drops off in year ${F.esc(D.pmi_off_year ?? '—')} (borrower-requestable at 80% ${T('ltv', 'LTV')}; lenders auto-cancel at 78%); total PMI paid ${m0(D.pmi_total)}.`);
    sub('mortgage-extra', notes.join(' '));
    termLegend(g('mortgage-lines'), {'Principal (year)': `${T('principal', 'Principal')} (year)`});
    g('mortgage-card').hidden = false;
    head('h-schedule', `${T('amortization', 'Amortization')} schedule`);
    F.table(g('schedule'), [{key: 'year', label: 'Year', left: true, fmt: v => F.esc(v)}, {key: 'interest', label: 'Interest', fmt: m}, {key: 'principal', label: 'Principal', fmt: m}, {key: 'balance', label: 'Balance', fmt: m}, {key: 'pmi', label: 'PMI', fmt: v => F.isNum(v) && v > 0 ? m(v) : '—'}], D.schedule, {sortKey: 'year', desc: false});
    termHeads(g('schedule'), {principal: T('principal', 'Principal'), pmi: T('pmi', 'PMI')});
  }

  if ('current_payment' in D) {
    explain.push(`<p>This compares keeping your current mortgage with a ${T('refinance')} at the new rate. The headline is the ${T('break-even point', 'breakeven')}: how many months of lower payments it takes to earn back the ${T('closing costs')}. The lifetime delta is the total interest saved over the whole new loan, less those costs.</p>
      <p>The chart adds up the cash kept year by year; it starts below zero (closing costs paid up front) and crosses zero at breakeven. Caveat: a longer new term can lower the payment while raising total interest, so read the term-extension tile alongside the monthly saving.</p>`);
    chip('Balance', m0(D.balance)); chip(T('closing costs', 'Closing costs'), m0(D.closing_costs));
    head('h-refi', `${T('refinance', 'Refinance')} figures`);
    tiles.push(tile(T('break-even point', 'Breakeven'), D.breakeven_months == null ? '<span class="neg">never</span>' : F.num(D.breakeven_months, 1) + ' months', D.breakeven_months == null ? 'the new payment is not lower' : `${T('closing costs')} ${m0(D.closing_costs)} ÷ savings ${m(D.monthly_savings)}/mo`),
      tile('Monthly savings', `<span class="${F.cls(D.monthly_savings)}">${F.moneyS(D.monthly_savings)}</span>`, `${m(D.current_payment)} → ${m(D.new_payment)}`),
      tile('Lifetime delta', `<span class="${F.cls(D.lifetime_delta)}">${F.moneyS(D.lifetime_delta)}</span>`, 'interest saved less closing costs, over the full new term'),
      tile('Term extension', `${F.num(D.term_extension_months, 0)} months`, D.term_extension_months > 0 ? 'the new loan runs longer' : 'no longer than today'));
    const SP = D.savings_path || [];
    if (SP.length) { g('refi-chart').hidden = false; F.lines(g('refi-lines'), {height: 240, xFmt: yrFmt, yFmt: k$, zeroLine: true, aria: 'Cumulative savings by year', series: [{name: 'Cumulative savings', color: F.S[0], area: true, points: SP.map(r => [r.year, r.cumulative_savings])}]}); }
    g('refi-card').hidden = false;
    g('refi').innerHTML = kv([['Current payment', m(D.current_payment)], ['New payment', m(D.new_payment)], ['Monthly savings', F.moneyS(D.monthly_savings)], [T('closing costs', 'Closing costs'), m(D.closing_costs)], [T('break-even point', 'Breakeven months'), D.breakeven_months == null ? '—' : F.num(D.breakeven_months, 1)],
      ['Remaining interest now', m(D.current_remaining_interest)], ['New total interest', m(D.new_total_interest)], ['Lifetime delta', F.moneyS(D.lifetime_delta)], ['Term extension', `${F.num(D.term_extension_months, 0)} months`]]);
    F.armTerms(g('refi'));
    const N = D.new_loan_at_current_payment;
    g('refi-note').textContent = N ? `Keeping the current payment of ${m(D.current_payment)} on the new rate pays the loan off in ${F.num(N.months, 0)} months with ${m0(N.interest)} interest.` : 'The current payment does not cover interest at the new rate, so no keep-the-payment comparison is shown.';
  }

  if (Array.isArray(D.by_year)) {
    const A = D.assumptions || {};
    explain.push(`<p>This asks whether buying or renting leaves you with more ${T('net worth')} after ${F.esc(D.horizon_years)} years. The buyer builds ${T('home equity')} (value after ${T('appreciation')}, minus the loan and selling costs); the renter invests the down payment and ${T('closing costs')} instead, plus any month the rent is cheaper than owning.</p>
      <p>In the chart the two lines are those net-worth paths; the year they cross is the ${T('break-even point', 'breakeven year')}. Caveat: the answer leans heavily on the assumed appreciation, rent growth and investment return in the chips, none of which is knowable in advance.</p>`);
    for (const [k, l] of [['appreciation', T('appreciation', 'Appreciation')], ['rent_growth', 'Rent growth'], ['investment_return', T('expected return', 'Investment return')], ['property_tax_rate', T('property tax', 'Property tax')], ['maintenance_rate', 'Maintenance'], ['buy_closing_rate', T('closing costs', 'Buy closing')], ['sell_closing_rate', T('closing costs', 'Sell closing')]]) if (A[k] != null) chip(l, F.pct(A[k], 2));
    const C = D.monthly_cost_year1 || {};
    head('h-rvb-chart', `${T('net worth', 'Net worth')}: buy vs rent`);
    tiles.push(tile(T('break-even point', 'Breakeven year'), D.breakeven_year == null ? '<span class="neg">not within horizon</span>' : `year ${F.esc(D.breakeven_year)}`, `over a ${F.esc(D.horizon_years)}-year horizon`),
      tile('Year-1 monthly cost: buy', m(C.buy), `payment ${m(D.payment)} plus tax, maintenance, insurance, ${T('hoa', 'HOA')}`), tile('Year-1 monthly cost: rent', m(C.rent), ''), tile('Upfront cash', m0(D.upfront_cash), `down payment plus buy ${T('closing costs')}, invested by the renter`));
    g('rvb-chart').hidden = false;
    sub('rvb-sub', `Buyer: ${T('home equity')} net of selling costs. Renter: the invested upfront cash plus each year's cost difference. Where the lines cross is the ${T('break-even point', 'breakeven year')}.`);
    F.lines(g('rvb-lines'), {height: 280, xFmt: yrFmt, yFmt: k$, zeroLine: true, aria: 'Buy vs rent net worth by year', series: [
      {name: 'Buy net worth', color: F.S[0], points: D.by_year.map(r => [r.year, r.buy_net_worth])}, {name: 'Rent net worth', color: F.S[1], points: D.by_year.map(r => [r.year, r.rent_net_worth])}]});
    termLegend(g('rvb-lines'), {'Buy net worth': `Buy ${T('net worth')}`, 'Rent net worth': `Rent ${T('net worth')}`});
    g('rvb-card').hidden = false;
    F.table(g('rvb'), [{key: 'year', label: 'Year', left: true, fmt: v => F.esc(v)}, {key: 'buy_cost_cumulative', label: 'Buy cost (cum.)', fmt: m0}, {key: 'rent_cost_cumulative', label: 'Rent cost (cum.)', fmt: m0}, {key: 'home_equity', label: 'Home equity', fmt: m0}, {key: 'renter_portfolio', label: 'Renter portfolio', fmt: m0},
      {key: 'buy_net_worth', label: 'Buy net worth', fmt: m0}, {key: 'rent_net_worth', label: 'Rent net worth', fmt: m0}, {key: 'advantage_buy', label: 'Advantage buy', cls: F.cls, fmt: F.moneyS}], D.by_year, {sortKey: 'year', desc: false});
    termHeads(g('rvb'), {home_equity: T('home equity', 'Home equity'), buy_net_worth: `Buy ${T('net worth')}`, rent_net_worth: `Rent ${T('net worth')}`});
  }

  if ('noi' in D) {
    const P = D.projection;
    explain.push(`<p>This underwrites a rental at ${m0(D.price)}: does the rent cover the costs and the loan, and what return does the cash you put in earn? Rent minus an allowance for empty months and ${T('operating expenses')} gives ${T('noi', 'NOI')}; NOI divided by price is the ${T('cap rate')}; NOI divided by the year's loan payments is ${T('dscr', 'DSCR')}, the lender's cushion; and what is left after the loan, divided by cash invested, is the ${T('cash-on-cash return')}.</p>
      <p>${P ? `The hold-period projection adds a sale after ${F.esc(P.hold_years)} years and reports the ${T('irr', 'IRR')}, the yearly return counting every cash flow and its timing. ` : ''}${Array.isArray(D.scenarios) && D.scenarios.length ? 'The scenario grid reruns that projection across different appreciation and rent-growth assumptions; blue cells beat zero, red fall below. ' : ''}Caveat: income-tax effects (depreciation, deductions) and big one-off repairs beyond the reserve rate are not modelled.</p>`);
    chip('Price', m0(D.price)); chip('Loan', m0(D.loan)); chip('Cash invested', m0(D.cash_invested));
    tiles.push(tile(T('noi', 'NOI'), m0(D.noi), `${T('cap rate')} ${F.pct(D.cap_rate, 2)}`), tile(T('dscr', 'DSCR'), D.dscr == null ? 'no debt' : F.num(D.dscr, 2), `${T('debt service')} ${m0(D.debt_service)}`),
      tile('Cash flow', `<span class="${F.cls(D.cash_flow)}">${F.moneyS(D.cash_flow)}</span>`, `${T('cash-on-cash return', 'cash-on-cash')} ${F.pct(D.cash_on_cash, 2)}`));
    if (P) tiles.push(tile(T('irr', 'IRR'), F.pct(P.irr, 2), `${F.esc(P.hold_years)}-year hold · equity multiple ${F.num(P.equity_multiple, 2)}x (total cash back ÷ cash in)`));
    g('rental-grid').hidden = false;
    sub('rental-sub', `Year-one figures. Effective gross income is rent after the ${T('vacancy rate', 'vacancy allowance')}; ${T('noi', 'NOI')} is that less ${T('operating expenses')}, before the loan.`);
    g('rental').innerHTML = kv([['Gross rent', m(D.gross_rent)], ['Effective gross income', m(D.effective_gross_income)], [T('operating expenses', 'Operating expenses'), m(D.operating_expenses)], [T('noi', 'NOI'), m(D.noi)], [T('cap rate', 'Cap rate'), F.pct(D.cap_rate, 2)], [T('debt service', 'Debt service'), m(D.debt_service)], [T('dscr', 'DSCR'), D.dscr == null ? '—' : F.num(D.dscr, 2)],
      ['Cash flow', F.moneyS(D.cash_flow)], ['Cash invested', m(D.cash_invested)], [T('cash-on-cash return', 'Cash-on-cash'), F.pct(D.cash_on_cash, 2)], [T('grm', 'GRM'), F.num(D.grm, 2)], ['Rent / price', F.pct(D.rent_to_price, 2) + (D.one_percent_rule ? ` (meets the ${T('1% rule')})` : ` (below the ${T('1% rule')})`)], ['Break-even occupancy (share of the year that must be rented to cover costs and the loan)', F.pct(D.break_even_occupancy, 2)], [T('operating expense ratio', 'Expense ratio'), F.pct(D.expense_ratio, 2)]]);
    F.armTerms(g('rental'));
    if (P) {
      g('proj-card').hidden = false;
      g('proj-sub').textContent = `Sale ${m0(P.sale_price)} after ${P.hold_years} years, loan balance ${m0(P.loan_balance_at_sale)} at sale, total profit ${F.moneyS(P.total_profit)}. Year 0 is the cash put in; later years are operating cash flow, the last one including the sale.`;
      const flows = (P.cash_flows || []).map((v, i) => ({year: i, cash_flow: v, label: i === 0 ? 'purchase' : i === P.cash_flows.length - 1 ? 'operating + sale' : 'operating'}));
      F.table(g('proj'), [{key: 'year', label: 'Year', left: true, fmt: v => F.esc(v)}, {key: 'label', label: '', left: true, fmt: v => F.esc(v)}, {key: 'cash_flow', label: 'Cash flow', cls: F.cls, fmt: F.moneyS}], flows, {sortKey: 'year', desc: false});
    }
    const SC = D.scenarios;
    if (Array.isArray(SC) && SC.length) {
      g('scen-card').hidden = false;
      head('h-scen', `Scenarios: ${T('appreciation')} × rent growth`);
      sub('scen-sub', `The same ${F.esc(P ? P.hold_years : '')}-year projection rerun for each pair of yearly ${T('appreciation')} (rows) and rent growth (columns). Pick the metric to colour by.`);
      const apps = [...new Set(SC.map(s => s.appreciation))].sort((a, b) => a - b), rgs = [...new Set(SC.map(s => s.rent_growth))].sort((a, b) => a - b);
      const metrics = [['irr', 'IRR', v => F.pct(v, 1), T('irr', 'IRR')], ['total_profit', 'Total profit', v => k$(v), 'Total profit'], ['cash_on_cash', 'Cash-on-cash', v => F.pct(v, 1), T('cash-on-cash return', 'Cash-on-cash')]];
      const draw = key => { const mt = metrics.find(x => x[0] === key);
        F.heatmap(g('scen'), {rows: apps.map(a => 'appreciation ' + F.pct(a, 1)), cols: rgs.map(r => 'rent growth ' + F.pct(r, 1)), fmt: mt[2], diverging: true,
          values: apps.map(a => rgs.map(r => { const s = SC.find(x => x.appreciation === a && x.rent_growth === r); return s ? s[key] : null; }))});
        g('scen-metric').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b.dataset.key === key ? 'true' : 'false')); };
      for (const [key, , , html] of metrics) { const b = F.el('button', {class: 'chip', 'data-key': key, 'aria-pressed': 'false'}, html); b.addEventListener('click', () => draw(key)); g('scen-metric').appendChild(b); }
      F.armTerms(g('scen-metric'));
      draw('irr');
    }
  }

  if ('max_housing_payment' in D) {
    explain.push(`<p>This estimates the most house a lender would let you buy on the given income, debts and down payment, using the ${T('28/36 rule')}: the ${T('front-end ratio')} caps the housing payment at a share of income, the ${T('back-end ratio')} caps housing plus other debt payments. Whichever cap is lower is the binding ratio, and it sets the maximum monthly ${T('piti', 'PITI')}, which is worked back to a maximum loan and price at the given rate.</p>
      <p>Caveat: this is the lender's ceiling, not a comfortable budget; it ignores savings goals, childcare and the rest of your spending.</p>`);
    tiles.push(tile('Max price', m0(D.max_price), 'with the given down payment'), tile('Max loan', m0(D.max_loan), ''), tile('Max housing payment', m(D.max_housing_payment), `binding ratio: ${F.esc(D.binding_ratio)}`), tile(`${T('piti', 'PITI')} at max`, m(D.piti_at_max), ''));
    g('afford-card').hidden = false;
    sub('afford-sub', `The binding ratio is whichever of the two lender caps is lower; it sets the payment ceiling.`);
    g('afford').innerHTML = kv([[`${T('front-end ratio', 'Front-end cap')} (28% rule by default)`, m(D.front_end_cap)], [`${T('back-end ratio', 'Back-end cap')} after debts (36% rule by default)`, m(D.back_end_cap)], ['Binding ratio', F.esc(D.binding_ratio)], ['Max housing payment', m(D.max_housing_payment)], ['Max loan', m(D.max_loan)], ['Max price', m(D.max_price)], [`${T('piti', 'PITI')} at max`, m(D.piti_at_max)]]);
    F.armTerms(g('afford'));
  }

  if ('ffo_per_share' in D) {
    explain.push(`<p>This values a ${T('reit', 'REIT')} the way property investors do. Ordinary earnings understate a landlord's cash because they deduct ${T('depreciation')}, a paper charge; ${T('ffo', 'FFO')} adds it back (and removes one-off gains on sales), and ${T('affo', 'AFFO')} then subtracts the upkeep spending needed to keep the buildings competitive. Price divided by each gives the P/FFO and P/AFFO multiples, the REIT equivalents of a ${T('p/e', 'P/E ratio')}.</p>
      <p>The ${T('payout ratio', 'payout')} rows show what share of FFO and AFFO goes out as dividends; above 100% of AFFO the dividend is being funded from somewhere else. ${T('nav', 'NAV')} premium compares the share price with the estimated value of the properties less debt. Caveat: FFO here is built from reported net income and depreciation, a proxy for the company's own FFO figure, and any NAV is only as good as the appraisal behind it.</p>`);
    if (D.symbol) chip('Symbol', D.symbol); if (D.fiscal_year) chip('Fiscal year', D.fiscal_year); if (D.is_reit === false) chip('Classification', 'not a REIT per Yahoo');
    tiles.push(tile(`Price / ${T('ffo', 'FFO')}`, D.p_ffo == null ? '—' : F.num(D.p_ffo, 1) + 'x', `FFO/share ${F.num(D.ffo_per_share, 2)} · yield ${F.pct(D.ffo_yield, 2)}`), tile(`Price / ${T('affo', 'AFFO')}`, D.p_affo == null ? '—' : F.num(D.p_affo, 1) + 'x', `AFFO/share ${F.num(D.affo_per_share, 2)}`),
      tile(T('dividend yield', 'Dividend yield'), F.pct(D.dividend_yield, 2), `FFO ${T('payout ratio', 'payout')} ${F.pct(D.ffo_payout, 0)} · AFFO payout ${F.pct(D.affo_payout, 0)}`), tile(`${T('nav', 'NAV')} premium`, F.pct(D.nav_premium, 1, true), D.nav_premium == null ? 'no NAV given' : D.nav_premium < 0 ? 'discount to NAV' : 'premium to NAV'));
    g('reit-card').hidden = false;
    head('h-reit', `${T('reit', 'REIT')} multiples`);
    sub('reit-sub', `Price relative to cash earnings. FFO and AFFO are per-share; a lower multiple means you pay less for each dollar of cash the properties generate.`);
    g('reit').innerHTML = kv([[T('ffo', 'FFO'), m0(D.ffo)], ['FFO / share', F.num(D.ffo_per_share, 4)], [`P/${T('ffo', 'FFO')}`, D.p_ffo == null ? '—' : F.num(D.p_ffo, 2)], ['FFO yield', F.pct(D.ffo_yield, 2)], [T('affo', 'AFFO'), m0(D.affo)], ['AFFO / share', F.num(D.affo_per_share, 4)], [`P/${T('affo', 'AFFO')}`, D.p_affo == null ? '—' : F.num(D.p_affo, 2)],
      [T('dividend yield', 'Dividend yield'), F.pct(D.dividend_yield, 2)], [`FFO ${T('payout ratio', 'payout')}`, F.pct(D.ffo_payout, 2)], [`AFFO ${T('payout ratio', 'payout')}`, F.pct(D.affo_payout, 2)], [`${T('nav', 'NAV')} premium`, F.pct(D.nav_premium, 2, true)]]);
    F.armTerms(g('reit'));
    const IN = D.inputs;
    if (IN) { g('reit-inputs').innerHTML = '<h2 style="margin-top:12px">Inputs</h2>' + kv([['Price', m(IN.price)], ['Shares', F.num(IN.shares, 0)], ['Net income', m0(IN.net_income)], [T('depreciation', 'Depreciation'), m0(IN.depreciation)], ['Gains on sale', m0(IN.gains_on_sale)], [`Recurring ${T('capital expenditure', 'capex')}`, m0(IN.recurring_capex)], [`Dividend / share (${T('trailing 12 months', 'TTM')})`, IN.dividend_per_share == null ? '—' : F.num(IN.dividend_per_share, 4)], [`${T('nav', 'NAV')} / share`, IN.nav_per_share == null ? '—' : m(IN.nav_per_share)]]); F.armTerms(g('reit-inputs')); }
    g('reit-notes').innerHTML = (D.notes || []).map(n => `<li>${F.esc(n)}</li>`).join('');
  }

  FA.explain(g('explain'), intro + explain.join(''));
  g('tiles').innerHTML = tiles.join(''); F.armTerms(g('tiles'));
  // card help: one explainer per calculator card, built from this result's own figures
  const help = (id, spec) => { const c = g(id); if (c && !c.hidden) F.help(c, spec); };
  const card = id => g(id).parentElement;
  if ('schedule' in D && Array.isArray(D.schedule)) {
    help('mortgage-chart', {lead: 'How each payment splits between interest and paying down the loan, year by year.',
      sections: [{title: 'The monthly payment', html: F.flow([{label: 'loan payment', value: m(D.payment)}, {op: '+', label: 'property tax', value: m(D.tax_monthly || 0)}, {op: '+', label: 'insurance', value: m(D.insurance_monthly || 0)}, ...(D.pmi_monthly > 0 ? [{op: '+', label: 'PMI', value: m(D.pmi_monthly)}] : []), ...(D.hoa_monthly > 0 ? [{op: '+', label: 'HOA', value: m(D.hoa_monthly)}] : []), {op: '=', label: 'monthly total', value: m(D.piti)}]) +
        '<p>Early payments are mostly interest; as the balance falls, more of each payment goes to principal.</p>'}]});
    help('mortgage-card', {lead: 'Every year of the loan: payments, interest, principal and the balance left.',
      sections: [{title: 'Over the whole loan', html: F.flow([{label: 'borrowed', value: m0(D.principal)}, {op: '+', label: 'interest', value: m0(D.total_interest)}, {op: '=', label: 'total paid', value: m0(D.total_paid)}])}]}); }
  if ('current_payment' in D) {
    help('refi-chart', {lead: 'Cash kept by the end of each year by switching loans, after the closing costs.',
      sections: [{title: 'Breakeven', html: F.flow([{label: 'closing costs', value: m0(D.closing_costs)}, {op: '÷', label: 'saved a month', value: m(D.monthly_savings)}, {op: '=', label: 'months to break even', value: F.num(D.breakeven_months, 1)}]) +
        '<p>Before the line crosses zero, the closing costs have not been earned back.</p>'}]});
    help('refi-card', {lead: 'The two loans side by side, and what changes over their full terms.',
      sections: [{title: 'The catch to check', html: `<p>A new 30-year loan can lower the payment partly by stretching the term${F.isNum(D.term_extension_months) && D.term_extension_months > 0 ? ` (${F.num(D.term_extension_months, 0)} months longer here)` : ''}; the lifetime figure compares total interest, not just the monthly payment.</p>`}]}); }
  if (Array.isArray(D.by_year)) {
    help('rvb-chart', {lead: 'Your net worth over time if you buy, against renting and investing the difference.',
      sections: [{title: 'What each line counts', html: '<p><b>Buy</b>: the home’s value minus the loan and selling costs. <b>Rent</b>: the down payment and any monthly savings from renting, invested at the stated return.</p>' + (D.breakeven_year ? `<p>Buying pulls ahead in year ${F.esc(D.breakeven_year)} under these assumptions.</p>` : '')}]});
    help('rvb-card', {lead: 'The same comparison as a table, one row a year.'}); }
  if ('noi' in D) {
    F.help(card('h-rental'), {lead: 'Whether the property’s rent covers its costs and its loan, and what it earns on the cash put in.',
      sections: [{title: 'From rent to cap rate', html: F.flow([{label: 'rent after vacancy', value: m0(D.effective_gross_income)}, {op: '−', label: 'operating costs', value: m0(D.operating_expenses)}, {op: '=', label: 'NOI', value: m0(D.noi)}, {op: '÷', label: 'price', value: m0(D.price)}, {op: '=', label: 'cap rate', value: F.pct(D.cap_rate, 2)}])},
        {title: 'Covering the loan', html: F.flow([{label: 'NOI', value: m0(D.noi)}, {op: '÷', label: 'loan payments a year', value: m0(D.debt_service)}, {op: '=', label: 'DSCR', value: F.num(D.dscr, 2) + '×'}]) + '<p>Lenders commonly look for 1.2× or more: the rent covers the loan with room to spare.</p>'}]});
    if (D.projection) help('proj-card', {lead: 'What the property returns over the whole hold, sale included.',
      sections: [{title: 'IRR', html: `<p>IRR is the yearly return that makes all the cash in and out, including the sale at the end, add up to zero. Here it is ${F.pct(D.projection.irr, 2)} over ${F.esc(D.projection.hold_years)} years.</p>`}]});
    if (Array.isArray(D.scenarios) && D.scenarios.length) help('scen-card', {lead: 'The same rental under different home-price and rent growth rates.',
      sections: [{title: 'Reading the grid', html: '<p>Rows are home-price growth and columns are rent growth; moving down or right raises both, so results improve toward the bottom-right. The colour runs from one side of zero to the other, deeper the further from zero, for the metric picked above.</p>'}]}); }
  if ('max_housing_payment' in D) help('afford-card', {lead: 'The most a lender would typically approve, from your income and debts.',
    sections: [{title: 'The 28/36 rule', html: `<p><b>Housing cap:</b> 28% of monthly income, ${m0(D.front_end_cap)}.</p><p><b>All-debts cap:</b> 36% of monthly income minus your other debt payments, ${m0(D.back_end_cap)}.</p><p>The lower of the two, ${m0(D.max_housing_payment)} (${F.esc(D.binding_ratio || '')}), is the most a lender would typically approve for the monthly payment; the price follows from that payment, the rate and the down payment.</p>`}]});
  if ('ffo_per_share' in D) help('reit-card', {lead: 'A REIT’s price against the cash its properties produce, which reported earnings understate.',
    sections: [{title: 'FFO', html: (D.inputs && F.isNum(D.inputs.net_income) && F.isNum(D.inputs.depreciation) ? F.flow([{label: 'net income', value: m0(D.inputs.net_income)}, {op: '+', label: 'depreciation', value: m0(D.inputs.depreciation)}, ...(F.isNum(D.inputs.gains_on_sale) && D.inputs.gains_on_sale ? [{op: '\u2212', label: 'gains on property sales', value: m0(D.inputs.gains_on_sale)}] : []), {op: '=', label: 'FFO', value: m0(D.ffo)}]) : '') +
      `<p>Depreciation is subtracted from earnings, but buildings often hold or gain value, so FFO (funds from operations) adds it back. Price \u00f7 FFO per share is ${F.num(D.p_ffo, 1)}.</p>`}]});
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _money(v: object) -> str:
    return f"${float(v):,.2f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _pct(v: object) -> str:
    return f"{float(v) * 100:.2f}%" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _headline(result: dict, calculators: list[str]) -> str:
    """Static one-liner (readable without JS); the script draws the rest."""
    parts = []
    for c in calculators:
        if c == "mortgage":
            parts.append(f"payment {_money(result.get('payment'))} · PITI {_money(result.get('piti'))} · total interest {_money(result.get('total_interest'))}")
        elif c == "refinance":
            be = result.get("breakeven_months")
            parts.append(f"monthly savings {_money(result.get('monthly_savings'))} · breakeven {be if be is not None else '—'} months · lifetime delta {_money(result.get('lifetime_delta'))}")
        elif c == "rent_vs_buy":
            be = result.get("breakeven_year")
            parts.append(f"breakeven {'year ' + str(be) if be is not None else 'not within the horizon'} · year-1 monthly buy {_money((result.get('monthly_cost_year1') or {}).get('buy'))} vs rent {_money((result.get('monthly_cost_year1') or {}).get('rent'))}")
        elif c == "rental":
            proj = result.get("projection") or {}
            parts.append(f"NOI {_money(result.get('noi'))} · cap rate {_pct(result.get('cap_rate'))} · DSCR {result.get('dscr') if result.get('dscr') is not None else '—'} · cash-on-cash {_pct(result.get('cash_on_cash'))}" + (f" · IRR {_pct(proj.get('irr'))}" if proj else ""))
        elif c == "affordability":
            parts.append(f"max price {_money(result.get('max_price'))} · max loan {_money(result.get('max_loan'))} · max housing payment {_money(result.get('max_housing_payment'))} ({result.get('binding_ratio')})")
        elif c == "reit":
            parts.append(f"P/FFO {result.get('p_ffo') if result.get('p_ffo') is not None else '—'} · P/AFFO {result.get('p_affo') if result.get('p_affo') is not None else '—'} · dividend yield {_pct(result.get('dividend_yield'))} · NAV premium {_pct(result.get('nav_premium'))}")
    return escape(" | ".join(parts))


def build(result: dict) -> tuple[list[str], str]:
    calculators = [c for c, key, _ in DETECT if isinstance(result, dict) and key in result] if isinstance(result, dict) else []
    if not calculators:
        raise InvalidInput("input must be a realestate.py or reit.py result (mortgage, refinance, rent_vs_buy, rental, affordability or reit output)")
    heading = ", ".join(h for c, _, h in DETECT if c in calculators)
    if result.get("symbol") and "reit" in calculators:
        heading += f" — {result['symbol']}"
    body = BODY.replace("{heading}", escape(heading)).replace("{headline}", _headline(result, calculators))
    return calculators, page.render(TITLE, result, body, SCRIPT)


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
            raise InvalidInput(f"could not read the calculator JSON: {exc}") from exc
        calculators, html = build(result)
        out = page.write(ns.out, html)
        return {"out": str(out), "title": TITLE, "calculators": calculators, "flags": len(result.get("flags") or [])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
