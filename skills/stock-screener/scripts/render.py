#!/usr/bin/env python3
"""Usage: render.py [--in screen.json] --out page.html

Turns a ``screen.py`` result (a file, or stdin when ``--in`` is omitted) into one self-contained
HTML page for the Artifact tool: a one-line intro with a "How to read this page" walkthrough, stat
tiles (companies screened, passed the business tests, priced, survivors), the funnel as bars --
how many companies were left after each test, in plain words with its threshold -- the survivors as
a sortable table (revenue, three-year and latest-quarter growth, the growth the screen expects, cash
margin after stock pay, return on capital, market value, the growth the price implies and the gap,
cash yield, P/E, payout yield, the Piotroski score, 12-month price change, per-company flags, and a
mark on companies already held), the near
misses with the one test each failed, the criteria, and the flags. Prints
``{"out", "title", "survivors", "universe"}``; exit 2 when the input is not a screen result.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Nothing is fetched at
runtime. Every figure is the script's; the page formats and sorts.
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
<h1 id="h1">Stock Screener</h1>
<p class="sub" id="sub"></p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<section class="card" id="funnel-card"><h2>How the market narrowed</h2><p class="sub">Companies left after each test, in the order applied.</p><div id="funnel"></div></section>
<section class="card" id="surv-card"><h2 id="surv-h">Survivors</h2><p class="sub" id="surv-sub"></p><div class="controls"><input id="q" placeholder="Search ticker or name"></div><div class="twrap" id="surv"></div></section>
<section class="card" id="near-card" hidden><h2>Near misses</h2><p class="sub">Passed every business test but one. Worth a look if that one test matters less to you.</p><div class="twrap" id="near"></div></section>
<section class="card" id="crit-card"><h2>Criteria</h2><p class="sub">The tests and thresholds used for this run.</p><div id="crit" class="legend"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Figures come from each company's SEC XBRL filings, computed one uniform way; companies' own reported or adjusted figures can differ. Prices are delayed Yahoo quotes. "Price implies" is the flat ten-year free-cash-flow growth (after stock pay unless stated) that makes a discounted-cash-flow value equal today's enterprise value; it is arithmetic on today's price, not a forecast. The cash figure behind it is the lower of last year's and the four-year average margin applied to last year's revenue. "Expected" growth starts from the lower of the three-year rate and recent growth and fades to 3% over ten years. A screen is a starting list for research, not a view on any security. General information, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, g = id => document.getElementById(id), C = D.criteria || {};
  const pct = (v, dp = 0) => F.isNum(v) ? (100 * v).toFixed(dp) + '%' : '—';
  const LABEL = {
    universe: () => 'Filers with four years of revenue', min_revenue: v => `Revenue at least ${F.moneyC(v)}`,
    min_revenue_cagr: v => `Revenue growth ${pct(v)}+ a year (3 yrs)`, min_growth_each_year: v => `No year below ${pct(v)} growth`,
    min_latest_year_growth: v => `Last year still ${pct(v)}+`, min_latest_quarter_growth: v => `Latest quarter ${pct(v)}+ vs a year ago`,
    min_gross_margin: v => `Gross margin ${pct(v)}+`, operating_margin_improving: () => 'Operating margin improving',
    min_operating_margin: v => `Operating margin ${pct(v)}+`, min_fcf_margin: v => `Free-cash-flow margin ${pct(v)}+`,
    fcf_positive_latest: () => 'Free cash flow positive last year', fcf_positive_all_years: () => 'Free cash flow positive every year',
    max_share_growth: v => `Share count growing ${pct(v, 1)} a year or less`, max_sbc_pct: v => `Stock pay ${pct(v)} of revenue or less`,
    max_debt_to_equity: v => `Debt below ${F.num(v, 1)}× equity`, financial_excluded: () => 'Financial sector set aside',
    financial_filer: () => 'Banks, insurers and lenders set aside', sector_excluded: () => `Left out: ${(C.exclude_sectors || []).join(', ')}`,
    min_roce: v => `Return on capital ${pct(v)}+`, net_income_positive_all_years: () => 'Profit every year',
    pays_dividend_all_years: () => 'Dividend paid every year', max_net_debt_to_ebit: v => `Net debt ${F.num(v, 1)}× operating profit or less`,
    min_current_ratio: v => `Current assets ${F.num(v, 1)}× current liabilities`, max_debt_to_working_capital: v => `Debt within ${F.num(v, 1)}× working capital`,
    min_f_score: v => `Piotroski score ${F.num(v, 0)}+ of 9`, max_payout_to_fcf: v => `Payout within ${F.num(v, 1)}× free cash flow`,
    min_earnings_yield: v => `Earnings yield ${pct(v, 1)}+`, min_shareholder_yield: v => `Payout yield ${pct(v, 1)}+`,
    max_pe_times_pb: v => `P/E × P/B ${F.num(v, 1)} or less`, min_momentum: v => `12-month price change ${pct(v)}+`,
    min_market_cap: v => `Market value ${F.moneyC(v)}+`, min_fcf_yield: v => `Cash yield ${pct(v, 1)}+ of market value`,
    max_pe: v => `P/E ${F.num(v, 0)} or less`, max_ps: v => `Price/sales ${F.num(v, 1)} or less`,
    max_implied_growth: v => `Price implies ${pct(v)} growth or less`, min_growth_gap: v => `Expected growth beats implied by ${pct(v)}+`,
  };
  const label = k => (LABEL[k] ? LABEL[k](C[k]) : k);
  const preset = D.preset || 'custom';
  g('h1').textContent = `Stock Screener — ${preset}`;
  g('sub').textContent = `As of ${D.as_of} · fiscal years ${D.years[0]}–${D.years[D.years.length - 1]} · latest quarters ${(D.latest_quarter_periods || []).join(', ')} · ${D.sources && D.sources.prices ? 'prices ' + D.sources.prices : 'not priced'}`;
  FA.explain(g('explain'), `<p>Every US-listed company that files financials with the SEC, put through the ${F.esc(preset)} tests one after another; the survivors are the starting list for research.</p>
    <p>The bars show how many companies were left after each test, so you can see which test did the most narrowing. Loosen that one first if the list is too short.</p>
    <p>In the survivors table, <b>Price implies</b> is how fast free cash flow (after stock pay) would have to grow for ten years to justify today's market value. <b>Expected</b> is the growth the screen credits the company with: the lower of its three-year rate and its recent growth, fading to 3% over ten years, because fast growth rarely lasts. <b>Gap</b> is expected minus implied: a large gap means the price assumes much less than that. That is a question to research (why does the market doubt it?), not an answer.</p>
    <p>A flag of <b>cash outruns profit</b> means cash flow is far above operating profit, often customer money or timing, so the price figures make it look cheaper than it is. <b>Profit above operating profit</b> usually means a one-off gain, so the P/E flatters. <b>Price falling</b> means the share price is down more than 20% over twelve months.</p>`);
  const S = D.survivors || [];
  const PRICE_STAGES = ['financial_excluded', 'sector_excluded', 'min_market_cap', 'min_fcf_yield', 'min_earnings_yield', 'min_shareholder_yield', 'max_pe', 'max_ps', 'max_pe_times_pb', 'max_implied_growth', 'min_growth_gap', 'min_momentum'];
  const RANK = {growth_gap: 'gap', fcf_yield: 'cash yield', magic_rank: 'magic-formula rank', pe_times_pb: 'P/E × P/B', shareholder_yield: 'payout yield', earnings_yield: 'earnings yield', roce: 'return on capital', f_score: 'Piotroski score', revenue_cagr: 'growth'};
  const ASC = ['magic_rank', 'pe', 'pe_times_pb', 'ps'];
  const tiles = [['Screened', F.num(D.universe, 0), `${F.num(D.dropped_incomplete || 0, 0)} left out for missing years`],
    ['Passed the business tests', F.num((D.funnel.filter(s => !PRICE_STAGES.includes(s.stage)).slice(-1)[0] || {}).remaining, 0), 'before any price test'],
    ['Priced', D.priced ? `${D.priced.count} of ${D.priced.of}` : '—', D.priced && D.priced.of > D.priced.limit ? `limit ${D.priced.limit}` : 'Yahoo, delayed'],
    ['Survivors', F.num(S.length, 0), `ranked by ${RANK[D.rank_by] || D.rank_by}${D.held ? ` · ${D.held.survivors_held.length} already held${D.held.excluded ? ', left out' : ''}` : ''}`]];
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${F.esc(k)}</div><div class="v">${F.esc(v)}</div><div class="d">${F.esc(d)}</div></div>`).join('');
  const top = D.funnel[0] ? D.funnel[0].remaining : 1;
  F.bars(g('funnel'), D.funnel.map((s, i) => ({label: label(s.stage), share: s.remaining / Math.max(top, 1), text: F.num(s.remaining, 0), color: i === D.funnel.length - 1 ? 'var(--s1)' : 'var(--s3)'})));
  const FLAG = {CASH_OUTRUNS_PROFIT: 'cash outruns profit', SPLIT_OR_LISTING_YEAR_SKIPPED: 'split/listing year skipped', CASH_ABOVE_ITS_AVERAGE: 'cash above its average',
    PROFIT_ABOVE_OPERATING_PROFIT: 'profit above operating profit', CAPEX_NOT_REPORTED: 'no capital-spending figure', LATEST_QUARTER_NOT_REPORTED: 'no latest quarter',
    ACQUISITIVE: 'growth partly bought', PRICE_FALLING: 'price falling', MISSCALED: 'a figure was mis-scaled'};
  const rows = S.map(s => ({ticker: s.ticker, name: s.name, held: s.held, ...s.metrics, flags: (s.flags || []).map(f => FLAG[f] || f).join(', '), nr: (s.not_reported || []).length}));
  // Each ranking shows the columns that explain it; the rest stay in the data for a custom page.
  const LEAD = ['ticker', 'name', 'revenue_latest', 'revenue_cagr', 'latest_quarter_growth'];
  const BY_RANK = {
    growth_gap: ['expected_growth', 'fcf_after_sbc_margin', 'market_cap', 'implied_growth', 'growth_gap', 'pe'],
    fcf_yield: ['fcf_after_sbc_margin', 'roce', 'market_cap', 'fcf_yield', 'pe', 'f_score', 'momentum'],
    magic_rank: ['roce', 'earnings_yield', 'magic_rank', 'market_cap', 'pe', 'momentum'],
    pe_times_pb: ['roce', 'market_cap', 'pe', 'pe_times_pb', 'momentum'],
    shareholder_yield: ['fcf_after_sbc_margin', 'market_cap', 'shareholder_yield', 'fcf_yield', 'pe', 'momentum'],
  };
  const SHOW = [...LEAD, ...(BY_RANK[D.rank_by] || ['expected_growth', 'fcf_after_sbc_margin', 'roce', 'f_score']), 'flags'];
  g('surv-sub').textContent = S.length ? `${S.length} companies passed every test. Click a column to sort.` : 'No company passed every test. The funnel shows which test to loosen.';
  const t = F.table(g('surv'), [
    {key: 'ticker', label: 'Ticker', left: true, fmt: (v, r) => `<b>${F.esc(v || '—')}</b>${r && r.held ? ' <span class="chip">held</span>' : ''}`},
    {key: 'name', label: 'Company', left: true, fmt: v => F.esc((v || '').slice(0, 30))},
    {key: 'revenue_latest', label: 'Revenue', fmt: F.moneyC},
    {key: 'revenue_cagr', label: '3-yr growth', fmt: v => pct(v)},
    {key: 'latest_quarter_growth', label: 'Latest qtr', fmt: v => pct(v)},
    {key: 'expected_growth', label: 'Expected', fmt: v => pct(v)},
    {key: 'fcf_after_sbc_margin', label: 'Cash margin', fmt: v => pct(v)},
    {key: 'roce', label: 'Return on capital', fmt: v => pct(v)},
    {key: 'market_cap', label: 'Mkt value', fmt: F.moneyC},
    {key: 'implied_growth', label: 'Price implies', fmt: v => pct(v)},
    {key: 'growth_gap', label: 'Gap', fmt: v => pct(v), cls: F.cls},
    {key: 'fcf_yield', label: 'Cash yield', fmt: v => pct(v, 1)},
    {key: 'earnings_yield', label: 'Earnings yield', fmt: v => pct(v, 1)},
    {key: 'shareholder_yield', label: 'Payout yield', fmt: v => pct(v, 1)},
    {key: 'pe', label: 'P/E', fmt: v => F.isNum(v) ? F.num(v, 0) : '—'},
    {key: 'pe_times_pb', label: 'P/E × P/B', fmt: v => F.isNum(v) ? F.num(v, 1) : '—'},
    {key: 'magic_rank', label: 'Magic rank', fmt: v => F.isNum(v) ? F.num(v, 0) : '—'},
    {key: 'f_score', label: 'Piotroski', fmt: v => F.isNum(v) ? `${F.num(v, 0)}/9` : '—'},
    {key: 'momentum', label: '12-mo price', fmt: v => pct(v), cls: F.cls},
    {key: 'flags', label: 'Flags', left: true, fmt: v => v ? `<span class="neg">${F.esc(v)}</span>` : ''},
  ].filter(c => SHOW.includes(c.key)),
  rows, {sortKey: D.rank_by in (rows[0] || {}) ? D.rank_by : 'revenue_cagr', desc: !ASC.includes(D.rank_by)});
  g('q').addEventListener('input', e => t.setQuery(e.target.value));
  const N = D.near_misses || [];
  if (N.length) { g('near-card').hidden = false;
    F.table(g('near'), [
      {key: 'ticker', label: 'Ticker', left: true, fmt: v => `<b>${F.esc(v)}</b>`}, {key: 'name', label: 'Company', left: true, fmt: v => F.esc((v || '').slice(0, 30))},
      {key: 'revenue_latest', label: 'Revenue', fmt: F.moneyC}, {key: 'revenue_cagr', label: '3-yr growth', fmt: v => pct(v)},
      {key: 'missed', label: 'Failed', left: true, fmt: v => F.esc(v)}],
      N.map(n => ({ticker: n.ticker, name: n.name, revenue_latest: n.metrics.revenue_latest, revenue_cagr: n.metrics.revenue_cagr, missed: label(n.failed[0])})), {sortKey: 'revenue_cagr'}); }
  const set = Object.entries(C).filter(([k, v]) => v !== null && v !== false && LABEL[k]);
  g('crit').innerHTML = set.map(([k]) => `<span class="chip">${F.esc(label(k))}</span>`).join('') +
    `<span class="chip">Cash basis: ${C.fcf_basis === 'fcf' ? 'free cash flow' : 'free cash flow after stock pay'}</span>`;
  // card help
  const fun = D.funnel || [], first = fun[0], last = fun[fun.length - 1];
  let cut = null; fun.forEach((st, i) => { if (i && (!cut || fun[i - 1].remaining - st.remaining > cut.n)) cut = {stage: st.stage, n: fun[i - 1].remaining - st.remaining}; });
  F.help(g('funnel-card'), {lead: 'How many companies were left after each test, in the order the tests ran.',
    sections: first && last ? [{title: 'From all companies to the survivors', html: F.flow([{label: 'companies screened', value: F.num(first.remaining, 0)}, {op: '−', label: 'removed by the tests', value: F.num(first.remaining - last.remaining, 0)}, {op: '=', label: 'survivors', value: F.num(last.remaining, 0)}]) +
      (cut ? `<p>The test that removed the most was “${F.esc(label(cut.stage))}”, with ${F.num(cut.n, 0)} ${cut.n === 1 ? 'company' : 'companies'}.</p>` : '')}] : []});
  const s0 = S[0], m0 = s0 ? s0.metrics || {} : {};
  F.help(g('surv-card'), {lead: 'The companies that passed every test, ranked as the table header shows.',
    sections: s0 && F.isNum(m0.expected_growth) && F.isNum(m0.implied_growth) ? [{title: `The gap, using ${s0.ticker}`, html: F.flow([{label: 'growth the screen expects', value: pct(m0.expected_growth)}, {op: '−', label: 'growth the price implies', value: pct(m0.implied_growth)}, {op: '=', label: 'gap', value: pct(m0.expected_growth - m0.implied_growth)}]) +
      `<p>"Expected" starts from the lower of the three-year rate (${pct(m0.revenue_cagr)}) and recent growth, and fades to 3% over ten years. "Price implies" is how fast free cash flow would have to grow for ten years to justify today’s market value. A positive gap means the price assumes less than the screen expects.</p>`}]
      : [{title: 'Reading a row', html: '<p>"Expected" is the growth the screen credits the company with, faded over ten years; "Price implies" is how fast free cash flow would have to grow to justify today’s market value; "Gap" is the first minus the second.</p>'}]});
  const nearC = g('near-card'); if (nearC && !nearC.hidden) F.help(nearC, {lead: 'Companies that passed every business test but one.',
    sections: [{title: 'Reading a row', html: '<p>The missed column names the one test each failed and by how much, so you can see which threshold kept it out.</p>'}]});
  F.help(g('crit-card'), {lead: 'The tests and thresholds used for this run.',
    sections: [{title: 'Where the numbers come from', html: '<p>Growth, margins and cash flow come from companies’ own SEC filings; prices are delayed quotes. Each chip is one test, applied in the order of the bars above.</p>'}]});
  const fl = D.flags || [];
  g('flags').innerHTML = fl.length ? fl.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def build(data: object) -> tuple[str, str, dict]:
    if not isinstance(data, dict) or not isinstance(data.get("funnel"), list) or "survivors" not in data:
        raise InvalidInput("input must be a screen.py result (with funnel and survivors)")
    title = f"Stock Screener — {data.get('preset') or 'custom'}"
    return title, page.render(title, data, BODY, SCRIPT), {"title": title, "survivors": len(data["survivors"]), "universe": data.get("universe")}


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
            raise InvalidInput(f"could not read the screen JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
