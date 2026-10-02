#!/usr/bin/env python3
"""Usage: render.py [--in retire.json] --out page.html

Turns one ``retire.py`` result (a file, or stdin when ``--in`` is omitted; a bare ``retirement.py``
result works too) into a self-contained interactive HTML page for the Artifact tool. The page opens
with the assumptions as chips (return, fees, volatility, inflation, contribution growth, withdrawal
rate, simulations, seed — each marked "default" when it equals retire.py's default), then renders the
action that ran: for ``project`` the stat tiles (success odds, nest egg required, balance at
retirement, contribution to close the gap), the deterministic path as a line with the Monte Carlo
10th-90th and 25th-75th percentile bands from ``monte_carlo.percentile_path`` (an older result without
that key gets the line plus a percentile table and a note saying so), the gap table, the Monte Carlo
figures, guardrails when present and the sortable year-by-year path; for ``goal`` the goal tiles;
for ``withdrawal`` the sustainable-withdrawal table with the requested rate; for ``ss_claim`` the
claiming-age table and break-even ages. Flags last, then the skill's "not modelled" note. Prints
``{"out": path, "title": ..., "action": ..., "flags": n}``. Exit 2 on a missing or malformed input.

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

TITLE = "Retirement Plan"
_ACTIONS = ("project", "goal", "withdrawal", "ss_claim")

BODY = """
<h1>Retirement Plan</h1>
<p class="sub" id="headline">{headline}</p>
<div id="explain"></div>
<div class="controls" id="chips" aria-label="Assumptions"></div>
<div class="tiles" id="tiles"></div>
<section class="card" id="chart-card" hidden><h2 id="h-chart">Projected balance</h2><p class="sub" id="chart-sub"></p><div id="chart"></div><p class="note" id="chart-note"></p></section>
<div class="grid2" id="project-grid" hidden>
  <div class="card"><h2 id="h-gap">Gap at retirement</h2><p class="sub">Whether the projected balance covers the spending you described, on the steady-return path.</p><div class="twrap" id="gap"></div></div>
  <div class="card"><h2 id="h-mc">Monte Carlo</h2><p class="sub" id="mc-sub"></p><div class="twrap" id="mc"></div><div id="guardrails"></div></div>
</div>
<section class="card" id="path-card" hidden><h2 id="h-path">Year by year (steady returns)</h2><p class="sub" id="path-sub"></p>
  <div class="controls"><input id="q" type="search" placeholder="Filter by age" aria-label="Filter path by age"><span class="muted" id="count"></span></div>
  <div class="twrap" id="path"></div></section>
<section class="card" id="goal-card" hidden><h2 id="h-goal">Savings goal</h2><p class="sub">What it takes to reach the target from today’s savings.</p><div class="twrap" id="goal"></div></section>
<section class="card" id="wd-card" hidden><h2 id="h-wd">Sustainable withdrawal</h2><p class="sub" id="wd-sub"></p><div class="twrap" id="wd"></div><p class="note" id="wd-req"></p></section>
<section class="card" id="ss-card" hidden><h2 id="h-ss">Social Security claiming age</h2><p class="sub" id="ss-sub"></p><div class="twrap" id="ss"></div><p class="note" id="ss-be"></p></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Success probability is the share of seeded Monte Carlo paths (lognormal annual returns at the stated return and volatility) that end above zero; the withdrawal table is that Monte Carlo, not the historical 4% rule. Not modelled: taxes on withdrawals, account types, Social Security rules and claiming age unless given as other income, healthcare shocks, variable spending, required minimum distributions, and sequence risk beyond what the simulated paths show. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, g = id => document.getElementById(id);
  const I = D.inputs || D.assumptions || {};
  // terms this page needs that the shared glossary lacks (page.py is frozen)
  Object.assign(FA.glossary, {
    "inflation": ["The general rise in prices over time; it shrinks what a fixed dollar amount buys.", "https://www.investopedia.com/terms/i/inflation.asp"],
    "nominal": ["A dollar amount as it will appear at the time, not adjusted for inflation.", "https://www.investopedia.com/terms/n/nominal.asp"],
    "today's dollars": ["Adjusted for inflation, so the amount buys what that many dollars buy now.", "https://www.investopedia.com/terms/i/inflation.asp"],
    "expected return": ["The average yearly investment gain the plan assumes; actual years land above and below it.", "https://www.investopedia.com/terms/e/expectedreturn.asp"],
    "net return": ["The assumed yearly return after fees; the rate the steady path compounds at.", "https://www.investopedia.com/terms/e/expectedreturn.asp"],
    "expense ratio": ["Yearly fund and advice fees as a share of the balance; subtracted from the return each year.", "https://www.investopedia.com/terms/e/expenseratio.asp"],
    "median": ["The middle outcome: half the simulations end higher and half lower.", "https://www.investopedia.com/terms/m/median.asp"],
    "4% rule": ["Spend 4% of savings in the first retirement year, then the same amount adjusted for inflation; the classic rule of thumb for a 30-year retirement.", "https://www.investopedia.com/terms/f/four-percent-rule.asp"],
    "sequence risk": ["The danger that poor returns early in retirement, while you are withdrawing, do lasting damage.", "https://www.investopedia.com/terms/s/sequence-risk.asp"],
    "future value": ["What a sum grows to by a future date at the assumed return.", "https://www.investopedia.com/terms/f/futurevalue.asp"],
    "social security": ["The US government retirement benefit, paid monthly for life from the age you claim it.", "https://www.investopedia.com/terms/s/socialsecurity.asp"],
    "full retirement age": ["The age (66-67 for most people) at which Social Security pays the full benefit; claiming earlier pays less for life, later pays more.", "https://www.investopedia.com/terms/n/normal-retirement-age-nra.asp"],
  });
  const T = (key, label) => FA.term(key, label);
  const head = (id, html) => { const h = g(id); if (h) { h.innerHTML = html; F.armTerms(h); } };
  const sub = (id, html) => { const h = g(id); if (h) { h.innerHTML = html; F.armTerms(h); } };
  // FA.table and FA.lines escape their labels, so terms go into the header cells / legend after they are built
  const termHeads = (root, map) => { root.querySelectorAll('th').forEach(th => { const h = map[th.dataset.key]; if (h) th.innerHTML = h; });
    F.armTerms(root); };
  const termLegend = (root, map) => { root.querySelectorAll('.legend span').forEach(sp => { const h = map[sp.textContent.trim()]; if (h) { const i = sp.querySelector('i'); sp.innerHTML = (i ? i.outerHTML : '') + h; } }); F.armTerms(root); };
  const DEF = {return: 0.06, fees: 0.001, volatility: 0.12, inflation: 0.025, contribution_growth: 0.02, withdrawal_rate: 0.04, simulations: 2000, seed: 42, end_age: 95};
  // assumption chips: value from inputs/assumptions first, then the result's own echo of it
  const chips = [
    [T('expected return', 'Return'), 'return', v => F.pct(v)], [T('expense ratio', 'Fees'), 'fees', v => F.pct(v, 2)], [T('volatility', 'Volatility'), 'volatility', v => F.pct(v)],
    [T('inflation', 'Inflation'), 'inflation', v => F.pct(v)], ['Contribution growth', 'contribution_growth', v => F.pct(v)],
    [T('sustainable withdrawal rate', 'Withdrawal rate'), 'withdrawal_rate', v => F.pct(v)], [T('monte carlo', 'Simulations'), 'simulations', v => F.num(v, 0)], ['Seed', 'seed', v => String(v)],
  ];
  const cw = g('chips');
  for (const [label, key, fmt] of chips) {
    let v = I[key]; if (v == null) v = D[key]; if (v == null && key === 'simulations' && D.monte_carlo) v = D.monte_carlo.simulations; if (v == null && key === 'volatility' && D.monte_carlo) v = D.monte_carlo.volatility;
    if (v == null) continue;
    const isDef = DEF[key] != null && Math.abs(v - DEF[key]) < 1e-12;
    cw.appendChild(F.el('span', {class: 'chip', title: isDef ? 'retire.py default' : 'set by the user'}, `${label} <b>${F.esc(fmt(v))}</b>${isDef ? ' <span class="muted">default</span>' : ''}`));
  }
  F.armTerms(cw);
  const tile = (k, v, d) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d || ''}</div></div>`;
  const kv = rows => '<table><tbody>' + rows.map(([k, v]) => `<tr><td class="l">${k}</td><td>${v}</td></tr>`).join('') + '</tbody></table>';
  const m0 = v => F.money(v, 0);
  const A = D.action || (D.deterministic ? 'project' : D.table ? 'withdrawal' : D.claiming ? 'ss_claim' : 'goal');
  const EXPLAIN = {
    project: `<p>This page projects your savings year by year from now until age ${F.esc(I.end_age ?? DEF.end_age)}, using the assumptions in the chips above (hover a word with a dotted underline for a plain-words meaning). Every number comes from the retirement script; the page only formats it.</p>
      <p>Two calculations run side by side. The <b>steady path</b> assumes the same ${T('net return')} every year. The ${T('monte carlo')} run replays the same plan across thousands of random return sequences; ${T('success odds')} is the share of those futures in which the money lasts to the end.</p>
      <p>In the chart, the solid line is the steady path and the shaded bands show where most simulated paths fall: the lighter band holds the middle 80% and the darker band the middle 50%. The dashed line marks retirement. The ${T('nest egg')} tile is the balance the plan needs at retirement to fund the planned spending at the withdrawal rate shown.</p>
      <p>The main caveat: the simulation assumes returns are random and independent each year; taxes, account types and ${T('social security')} claiming rules are not modelled unless you supplied other income. Treat the bands as a range of plausible outcomes, not a forecast.</p>`,
    goal: `<p>This page works out what it takes to reach one savings target: either the monthly contribution needed to get there in the given number of years, or how long the given monthly contribution takes. Numbers come from the retirement script at the ${T('expected return')} shown; the page only formats them.</p>
      <p>The ${T('future value')} of current savings is what the money you already have grows to on its own; the remaining amount is what contributions must cover. Caveat: a single fixed return with no volatility, inflation, fees or taxes, so treat it as a planning figure rather than a promise.</p>`,
    withdrawal: `<p>This page shows how much can be spent each year from a fixed ${T('nest egg')} without running out. Each row is one withdrawal rate: the first-year spending it implies, and the ${T('success odds')} from a ${T('monte carlo')} run over ${F.esc(D.years)} years of random returns at the stated ${T('volatility')} and ${T('inflation')}.</p>
      <p>Read the table top to bottom: higher rates mean more spending but lower odds of lasting. The ${T('4% rule')} row is the classic benchmark. Deterministic years is how long the money lasts if every year earned exactly the net return, a single steady path with no randomness.</p>
      <p>Caveat: the odds come from simulated returns, not history; taxes, ${T('social security')} and spending changes are not modelled.</p>`,
    ss_claim: `<p>This page compares claiming ${T('social security')} at different ages. The benefit is scaled from its ${T('full retirement age')} amount (claiming early shrinks it for life, waiting grows it), then each claiming age is run through the same ${T('monte carlo')} retirement simulation to see how the choice changes the ${T('success odds')} for your savings.</p>
      <p>Factor is the multiplier applied to the full-age benefit. Break-even is the age from which the later claim has paid out more in total than the earlier one. Caveat: the simplified claiming factors ignore spousal, survivor and earnings-test rules, and taxes on benefits are not modelled.</p>`,
  };
  FA.explain(g('explain'), EXPLAIN[A] || EXPLAIN.project);

  if (A === 'project') {
    const R = D.deterministic || {}, M = D.monte_carlo || {}, ra = I.retirement_age ?? R.retirement_age;
    g('tiles').innerHTML = [
      tile(T('success odds', 'Success odds'), F.pct(M.success_probability, 0), `${F.num(M.simulations, 0)} ${T('monte carlo', 'simulations')} · retire at ${F.esc(ra)} in ${F.esc(D.years_to_retirement)} years, fund ${F.esc(D.years_in_retirement)}`),
      tile(T('nest egg', 'Nest egg required'), m0(R.required_nest_egg), `${T('sustainable withdrawal rate', F.pct(I.withdrawal_rate ?? 0.04) + ' rule')} · spending at retirement ${m0(R.spending_at_retirement)}`),
      tile('Balance at retirement', m0(R.balance_at_retirement), `${m0(R.balance_at_retirement_real)} in ${T("today's dollars")} · ${T('net return')} ${F.pct(R.net_return, 2)}`),
      tile('Contribution to close the gap', F.isNum(R.gap) && R.gap > 0 ? m0(R.extra_annual_contribution_needed) + '/yr' : '<span class="pos">none</span>', F.isNum(R.gap) ? (R.gap > 0 ? `gap ${m0(R.gap)}` : `surplus ${m0(-R.gap)}`) : 'no spending given'),
    ].join('');
    F.armTerms(g('tiles'));
    // chart: deterministic line + Monte Carlo bands
    const path = R.path || [], pp = M.percentile_path || [];
    g('chart-card').hidden = false;
    const series = [{name: 'Steady returns', color: F.S[0], points: path.map(r => [r.age, r.balance])}];
    const bands = [];
    if (pp.length) {
      bands.push({name: '10th-90th', color: F.S[1], lo: pp.map(r => [r.age, r.p10]), hi: pp.map(r => [r.age, r.p90])});
      bands.push({name: '25th-75th', color: F.S[1], lo: pp.map(r => [r.age, r.p25]), hi: pp.map(r => [r.age, r.p75])});
      series.push({name: 'Middle of simulations', color: F.S[1], points: pp.map(r => [r.age, r.p50])});
      sub('chart-sub', `${T('nominal', 'Nominal')} balance by age. Shaded: the 10th-90th (light) and 25th-75th (darker) ${T('percentile', 'percentiles')} of ${F.num(M.simulations, 0)} simulated paths; each age's percentile is taken on its own, so a band edge is not one path.`);
    } else {
      sub('chart-sub', `${T('nominal', 'Nominal')} balance by age, at steady returns.`);
      g('chart-note').textContent = 'This result predates per-year Monte Carlo percentiles (monte_carlo.percentile_path), so the fan bands are not drawn; the table alongside shows the terminal percentiles the script did output.';
    }
    F.lines(g('chart'), {series, bands, height: 300, yFmt: F.moneyC, xFmt: x => 'age ' + Math.round(x), zeroLine: true, aria: 'Projected balance by age'});
    termLegend(g('chart'), {'Steady returns': 'Steady returns (the same return every year)', 'Middle of simulations': `Middle (${T('median', 'median')}) of the ${T('monte carlo', 'simulations')}`});
    const svg = g('chart').querySelector('svg');
    if (svg && F.isNum(ra)) { // mark retirement age
      const line = svg.querySelector('#cx'), hit = svg.querySelector('#hit'); const hx = +hit.getAttribute('x'), hy = +hit.getAttribute('y'), hw = +hit.getAttribute('width'), hh = +hit.getAttribute('height');
      const xs = path.map(r => r.age); const x0 = Math.min(...xs), x1 = Math.max(...xs);
      const X = hx + hw * (ra - x0) / (x1 - x0 || 1);
      const mk = document.createElementNS('http://www.w3.org/2000/svg', 'line'); for (const [k, v] of Object.entries({x1: X, x2: X, y1: hy, y2: hy + hh, stroke: 'var(--muted)', 'stroke-dasharray': '4 4'})) mk.setAttribute(k, v);
      const tx = document.createElementNS('http://www.w3.org/2000/svg', 'text'); tx.setAttribute('x', X + 4); tx.setAttribute('y', hy + 12); tx.setAttribute('font-size', '11'); tx.setAttribute('fill', 'var(--muted)'); tx.textContent = 'retirement';
      svg.insertBefore(mk, line); svg.insertBefore(tx, line);
    }
    // gap + Monte Carlo tables
    g('project-grid').hidden = false;
    g('gap').innerHTML = kv([
      [`Balance at retirement (${T('nominal')})`, m0(R.balance_at_retirement)], [`Balance at retirement (${T("today's dollars", 'real, in today\'s dollars')})`, m0(R.balance_at_retirement_real)],
      ['Spending at retirement', m0(R.spending_at_retirement)], [`Required ${T('nest egg')} (${T('sustainable withdrawal rate', F.pct(I.withdrawal_rate ?? 0.04) + ' rule')})`, m0(R.required_nest_egg)],
      [F.isNum(R.gap) && R.gap <= 0 ? 'Surplus' : 'Shortfall', `<span class="${F.isNum(R.gap) ? (R.gap > 0 ? 'neg' : 'pos') : ''}">${F.isNum(R.gap) ? m0(Math.abs(R.gap)) : '—'}</span>`], ['Extra annual contribution to close it', m0(R.extra_annual_contribution_needed)],
      ['Depletes at age', R.depletes_at_age == null ? 'not within the horizon' : F.esc(R.depletes_at_age)], ['Ending balance (steady returns)', m0(R.ending_balance)],
    ]);
    F.armTerms(g('gap'));
    head('h-mc', T('monte carlo', 'Monte Carlo'));
    sub('mc-sub', `${F.num(M.simulations, 0)} simulated futures with random yearly returns. p10, p50 and p90 are ${T('percentile', 'percentiles')}: a poor, a middle and a good outcome.`);
    const B = M.balance_at_retirement || {}, E = M.ending_balance || {};
    g('mc').innerHTML = `<table><thead><tr><th class="l"></th><th>${T('percentile', 'p10')}</th><th>${T('median', 'p50')}</th><th>${T('percentile', 'p90')}</th></tr></thead><tbody>` +
      `<tr><td class="l">Balance at retirement</td><td>${m0(B.p10)}</td><td>${m0(B.p50)}</td><td>${m0(B.p90)}</td></tr>` +
      `<tr><td class="l">Ending balance</td><td>${m0(E.p10)}</td><td>${m0(E.p50)}</td><td>${m0(E.p90)}</td></tr></tbody></table>` +
      kv([[T('success odds', 'Success probability'), F.pct(M.success_probability, 0)], [`${T('median', 'Median')} depletion age`, M.median_depletion_age == null ? 'none in the median case' : F.esc(M.median_depletion_age)], [`${T('percentile', 'Worst-decile')} years funded`, F.num(M.worst_decile_years_funded, 0) + ` of ${F.esc(D.years_in_retirement)}`]]);
    F.armTerms(g('mc'));
    const G = M.guardrails;
    if (G) g('guardrails').innerHTML = '<h2 style="margin-top:12px">Guardrails</h2>' + `<p class="sub">A spending rule tested on the same simulations: whenever the balance sits more than ${F.pct((I.guardrails || {}).trigger_pct)} below its high since retirement, that year's spending is cut by ${F.pct((I.guardrails || {}).cut_pct)}, and restored when it recovers.</p>` + kv([
      ['Constant spending success', F.pct(G.constant_success_probability, 0)], ['Guardrail spending success', F.pct(G.guardrail_success_probability, 0)],
      ['Gain', `<span class="${F.cls(G.success_probability_gain)}">${F.pct(G.success_probability_gain, 0, true)}</span>`], ['Median share of years cut', F.pct(G.median_fraction_of_years_cut, 0)],
      ['Cut / trigger', `${F.pct((I.guardrails || {}).cut_pct)} / ${F.pct((I.guardrails || {}).trigger_pct)}`]]);
    if (G) F.armTerms(g('guardrails'));
    // path table
    if (path.length) {
      g('path-card').hidden = false;
      head('h-path', 'Year by year (steady path)');
      sub('path-sub', `One path at the same ${T('net return')} every year, no randomness. Balance is ${T('nominal')}; real balance is the same in ${T("today's dollars")}. Contributions are shown while saving, withdrawals (negative) once retired.`);
      const gp = R.guardrail_path || [];
      const rows = path.map((r, i) => ({...r, phase: r.age < ra ? 'saving' : r.age === ra ? 'retirement' : 'drawing', spending_after_cut: gp[i] ? gp[i].spending_after_cut : null}));
      const cols = [{key: 'age', label: 'Age', left: true, fmt: v => F.esc(v)}, {key: 'phase', label: 'Phase', left: true, fmt: v => F.esc(v)}, {key: 'balance', label: 'Balance', fmt: m0}, {key: 'real_balance', label: 'Real balance', fmt: m0}, {key: 'flow', label: 'Contribution / withdrawal', fmt: v => `<span class="${F.cls(v)}">${F.isNum(v) ? (v > 0 ? '+' : '') + m0(v) : '—'}</span>`}];
      if (gp.length) cols.push({key: 'spending_after_cut', label: 'Spending after cut', fmt: v => F.isNum(v) && v > 0 ? m0(v) : '—'});
      const tbl = F.table(g('path'), cols, rows, {sortKey: 'age', desc: false, onDraw: vis => { g('count').textContent = `${vis.length} of ${rows.length} years`; }});
      termHeads(g('path'), {balance: `${T('nominal', 'Balance')}`, real_balance: T("today's dollars", 'Real balance')});
      g('q').addEventListener('input', e => tbl.setQuery(e.target.value));
    }
  }

  if (A === 'goal') {
    g('goal-card').hidden = false;
    const tiles = [tile('Target', m0(D.target), `from ${m0(D.current)} at ${T('expected return', F.pct(D.return) + ' a year')}`)];
    const rows = [['Target', m0(D.target)], ['Current savings', m0(D.current)], [T('expected return', 'Return'), F.pct(D.return)]];
    if (D.monthly_contribution_needed != null) {
      tiles.push(tile('Monthly contribution needed', D.already_funded ? '<span class="pos">already funded</span>' : m0(D.monthly_contribution_needed), `${m0(D.annual_contribution_needed)} per year over ${F.esc(D.years)} years`));
      tiles.push(tile(T('future value', 'Future value of current savings'), m0(D.future_value_of_current), `remaining ${m0(D.remaining)}`));
      rows.push(['Years', F.esc(D.years)], [T('future value', 'Future value of current savings'), m0(D.future_value_of_current)], ['Remaining', m0(D.remaining)], ['Monthly contribution needed', m0(D.monthly_contribution_needed)], ['Annual contribution needed', m0(D.annual_contribution_needed)], ['Already funded', D.already_funded ? 'yes' : 'no']);
    } else {
      tiles.push(tile('Years to reach', D.already_funded ? '<span class="pos">already funded</span>' : F.num(D.years_to_reach, 1), `${F.num(D.months_to_reach, 0)} months at ${m0(D.monthly_contribution)} per month`));
      rows.push(['Monthly contribution', m0(D.monthly_contribution)], ['Months to reach', F.num(D.months_to_reach, 0)], ['Years to reach', F.num(D.years_to_reach, 1)], ['Already funded', D.already_funded ? 'yes' : 'no']);
    }
    g('tiles').innerHTML = tiles.join(''); g('goal').innerHTML = kv(rows); F.armTerms(g('tiles')); F.armTerms(g('goal'));
  }

  if (A === 'withdrawal' && Array.isArray(D.table)) {
    g('wd-card').hidden = false;
    const four = D.table.find(r => r.rate === 0.04) || {};
    head('h-wd', T('sustainable withdrawal rate', 'Sustainable withdrawal'));
    g('tiles').innerHTML = [tile(T('nest egg', 'Nest egg'), m0(D.nest_egg), `${F.esc(D.years)} years · ${T('net return')} ${F.pct(D.net_return, 2)}`), tile(T('4% rule', '4% rule success'), F.pct(four.success_probability, 0), `${m0(four.annual_spending)} per year · lasts ${D.deterministic_years_at_4pct == null ? 'past ' + F.esc(D.years) + ' years' : F.esc(D.deterministic_years_at_4pct) + ' years'} deterministically`),
      D.requested ? tile('Requested', F.pct(D.requested.rate, 2), `${m0(D.requested.spending)} per year · success ${F.pct(D.requested.success_probability, 0)}`) : ''].join('');
    F.armTerms(g('tiles'));
    sub('wd-sub', `Every rate is evaluated on the same ${F.num(D.simulations, 0)} seeded ${T('monte carlo', 'return paths')} (${T('volatility')} ${F.pct(D.volatility)}, ${T('inflation')} ${F.pct(D.inflation)}), so the rows are comparable. Deterministic years: how long the money lasts if every year earned exactly the ${T('net return')}.`);
    const cols = [{key: 'rate', label: 'Rate', left: true, fmt: v => F.pct(v, 1)}, {key: 'annual_spending', label: 'Annual spending', fmt: m0}, {key: 'success_probability', label: 'Success', fmt: v => F.pct(v, 0)}, {key: 'median_ending_balance', label: 'Median ending balance', fmt: m0}, {key: 'worst_decile_years_funded', label: 'Worst-decile years funded', fmt: v => F.num(v, 0)}, {key: 'deterministic_years', label: 'Deterministic years', fmt: v => v == null ? 'never depletes' : F.esc(v)}];
    F.table(g('wd'), cols, D.table, {sortKey: 'rate', desc: false});
    termHeads(g('wd'), {rate: T('sustainable withdrawal rate', 'Rate'), success_probability: T('success odds', 'Success'), median_ending_balance: `${T('median', 'Median')} ending balance`, worst_decile_years_funded: `${T('percentile', 'Worst-decile')} years funded`});
    const q = D.requested;
    g('wd-req').textContent = q ? `Requested ${m0(q.spending)} per year is a ${F.pct(q.rate, 2)} withdrawal rate: success ${F.pct(q.success_probability, 0)}, median ending balance ${m0(q.median_ending_balance)}, ${q.deterministic_years == null ? 'never depletes' : 'depletes after ' + q.deterministic_years + ' years'} at the constant net return.` : '';
  }

  if (A === 'ss_claim' && Array.isArray(D.claiming)) {
    g('ss-card').hidden = false;
    const SI = D.inputs || {};
    const best = D.claiming.slice().sort((a, b) => (b.success_probability || 0) - (a.success_probability || 0))[0] || {};
    head('h-ss', `${T('social security', 'Social Security')} claiming age`);
    sub('ss-sub', `Factor is the multiplier on the ${T('full retirement age')} benefit for claiming at that age (below 1 early, above 1 late). Each row runs the same ${T('monte carlo')} simulation with that benefit as income.`);
    g('tiles').innerHTML = [tile(T('full retirement age', 'Benefit at FRA'), m0(SI.benefit_at_fra) + '/yr', `full retirement age ${F.esc(SI.fra_age)}`), tile(T('success odds', 'Highest success odds'), F.pct(best.success_probability, 0), `claiming at ${F.esc(best.age)}`), tile('Savings', m0(SI.savings), `spending ${m0(SI.spending)} · retire at ${F.esc(SI.retirement_age)}`)].join('');
    F.armTerms(g('tiles'));
    const cols = [{key: 'age', label: 'Claim age', left: true, fmt: v => F.esc(v)}, {key: 'factor', label: 'Factor', fmt: v => F.num(v, 4)}, {key: 'first_year_benefit', label: 'First-year benefit', fmt: m0}, {key: 'success_probability', label: 'Success', fmt: v => F.pct(v, 0)}, {key: 'median_ending_balance', label: 'Median ending balance', fmt: m0}, {key: 'median_depletion_age', label: 'Median depletion age', fmt: v => v == null ? 'none' : F.esc(v)}];
    F.table(g('ss'), cols, D.claiming, {sortKey: 'age', desc: false});
    termHeads(g('ss'), {success_probability: T('success odds', 'Success'), median_ending_balance: `${T('median', 'Median')} ending balance`, median_depletion_age: `${T('median', 'Median')} depletion age`});
    g('ss-be').textContent = 'Break-even (the age from which the later claim has paid out more in total) · ' + Object.entries(D.break_even || {}).map(([k, v]) => `${k.replace('_vs_', ' vs ')}: ${v == null ? 'the later claim never catches up before ' + SI.end_age : 'later claim ahead from age ' + v}`).join(' · ');
  }

  // card help
  const card = id => g(id).parentElement;
  if (A === 'project') { const R = D.deterministic || {}, M = D.monte_carlo || {}, ra = I.retirement_age ?? R.retirement_age, wr = I.withdrawal_rate ?? 0.04;
    F.help(g('chart-card'), {lead: 'How the savings could grow until retirement and then be drawn down, with the range of outcomes from many simulated markets.',
      sections: [{title: 'Reading the chart', html: `<p>The solid line uses the same return every year. The shaded fan is the middle of ${F.num(M.simulations, 0)} simulated futures with random yearly returns: the darker band holds half of them, the lighter band eight in ten. The dashed line marks retirement at ${F.esc(ra)}.</p><p>Balances are in future dollars; prices rise too, so the same amount buys less later.</p>`}]});
    F.help(card('h-gap'), {lead: 'Whether the projected balance covers the spending you described, on the steady-return path.',
      sections: F.isNum(R.spending_at_retirement) && F.isNum(R.required_nest_egg) ? [{title: 'The nest egg needed', html: F.flow([{label: 'spending a year at retirement', value: m0(R.spending_at_retirement)}, {op: '÷', label: 'withdrawal rate', value: F.pct(wr)}, {op: '=', label: 'nest egg needed', value: m0(R.required_nest_egg)}]) +
        (F.isNum(R.balance_at_retirement) ? F.flow([{label: 'projected balance', value: m0(R.balance_at_retirement)}, {op: '−', label: 'nest egg needed', value: m0(R.required_nest_egg)}, {op: '=', label: R.balance_at_retirement >= R.required_nest_egg ? 'surplus' : 'shortfall', value: m0(Math.abs(R.balance_at_retirement - R.required_nest_egg))}]) : '')}] : []});
    F.help(card('h-mc'), {lead: 'The same plan run through many random markets, to show how often the money lasts.',
      sections: [{title: 'Success odds', html: `<p>In ${F.pct(M.success_probability, 0)} of ${F.num(M.simulations, 0)} simulated futures the money lasted to the end age. p10, p50 and p90 are a poor, a middle and a good outcome: one in ten did worse than p10.</p>`},
        ...(M.guardrails ? [{title: 'Guardrails', html: '<p>A spending rule tried on the same simulations: spending is cut for a year whenever the balance falls well below plan. The gain is how many more futures last with the cuts.</p>'}] : [])]});
    const p0 = (R.path || [])[1];
    if ((R.path || []).length) F.help(card('h-path'), {lead: 'One path, year by year, at the same return every year.',
      sections: p0 ? [{title: `How one year adds up (age ${p0.age})`, html: F.flow([{label: 'balance a year earlier', value: m0(R.path[0].balance)}, {op: '+', label: 'growth', value: m0(p0.balance - R.path[0].balance - (p0.flow || 0))}, {op: '+', label: 'contribution', value: m0(p0.flow || 0)}, {op: '=', label: 'balance', value: m0(p0.balance)}]) +
        '<p>The real balance column shows the same amount in today’s dollars.</p>'}] : []}); }
  if (A === 'goal') F.help(g('goal-card'), {lead: 'What it takes to reach the target from today’s savings.',
    sections: F.isNum(D.future_value_of_current) && F.isNum(D.target) ? [{title: 'How the gap is found', html: F.flow([{label: 'target', value: m0(D.target)}, {op: '−', label: 'today’s savings, grown', value: m0(D.future_value_of_current)}, {op: '=', label: 'still to save', value: m0(D.remaining)}]) +
      '<p>The monthly figure is the steady deposit that, growing at the same return, covers what is still to save.</p>'}] : [{title: 'How it works', html: '<p>Monthly deposits and today’s savings grow at the stated return until they reach the target.</p>'}]});
  if (A === 'withdrawal' && Array.isArray(D.table)) { const four = D.table.find(r => r.rate === 0.04);
    F.help(g('wd-card'), {lead: 'How much can be spent each year from the nest egg, and how often each rate lasts.',
      sections: four ? [{title: 'The 4% row', html: F.flow([{label: 'nest egg', value: m0(D.nest_egg)}, {op: '×', label: 'rate', value: '4%'}, {op: '=', label: 'first-year spending', value: m0(four.annual_spending)}]) +
        `<p>Spending then rises with inflation each year. Success is the share of simulated markets where the money lasted ${F.esc(D.years)} years: ${F.pct(four.success_probability, 0)} at 4%.</p>`}] : []}); }
  if (A === 'ss_claim' && Array.isArray(D.claiming)) F.help(g('ss-card'), {lead: 'How the age you claim Social Security changes the benefit and how long the savings last.',
    sections: [{title: 'Early, full and late', html: '<p>Claiming before full retirement age shrinks the benefit for life; waiting past it raises it, up to age 70. The factor column is that multiplier. Break-even is the age from which the later claim has paid out more in total.</p>'}]});
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _action(result: dict) -> str | None:
    action = result.get("action")
    if action in _ACTIONS:
        return action
    if "deterministic" in result and "monte_carlo" in result:
        return "project"
    if "table" in result and "nest_egg" in result:
        return "withdrawal"
    if "claiming" in result:
        return "ss_claim"
    if "monthly_contribution_needed" in result or "months_to_reach" in result:
        return "goal"
    return None


def _money(v: object) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "—"
    return f"{'-' if v < 0 else ''}${abs(float(v)):,.0f}"


def _gap_words(gap: object) -> str:
    """``gap`` is required minus projected: positive is a shortfall, negative a surplus."""
    if not isinstance(gap, (int, float)) or isinstance(gap, bool):
        return "gap —"
    return f"shortfall {_money(gap)}" if gap > 0 else f"surplus {_money(-gap)}"


def _headline(result: dict, action: str) -> str:
    """Static one-liner (readable without JS); the script draws the rest."""
    if action == "project":
        d, m = result.get("deterministic") or {}, result.get("monte_carlo") or {}
        sp = m.get("success_probability")
        return escape(
            f"Success odds {sp * 100:.0f}% · required nest egg {_money(d.get('required_nest_egg'))} · "
            f"balance at retirement {_money(d.get('balance_at_retirement'))} · {_gap_words(d.get('gap'))}"
            if isinstance(sp, (int, float))
            else "Projection"
        )
    if action == "goal":
        if result.get("monthly_contribution_needed") is not None:
            return escape(f"Reach {_money(result.get('target'))} in {result.get('years')} years: {_money(result.get('monthly_contribution_needed'))} per month")
        return escape(f"Reach {_money(result.get('target'))} at {_money(result.get('monthly_contribution'))} per month: {result.get('years_to_reach')} years")
    if action == "withdrawal":
        return escape(f"Nest egg {_money(result.get('nest_egg'))} over {result.get('years')} years")
    return escape(f"Social Security benefit {_money((result.get('inputs') or {}).get('benefit_at_fra'))} at full retirement age")


def build(result: dict) -> tuple[str, str]:
    action = _action(result) if isinstance(result, dict) else None
    if action is None:
        raise InvalidInput("input must be a retire.py result (a JSON object with action project, goal, withdrawal or ss_claim)")
    body = BODY.replace("{headline}", _headline(result, action))
    return action, page.render(TITLE, result, body, SCRIPT)


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
            raise InvalidInput(f"could not read retire.py JSON: {exc}") from exc
        action, html = build(result)
        out = page.write(ns.out, html)
        return {"out": str(out), "title": TITLE, "action": action, "flags": len(result.get("flags") or [])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
