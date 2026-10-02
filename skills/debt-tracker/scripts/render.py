#!/usr/bin/env python3
"""Usage: render.py [--in debts.json] --out page.html

Turns one ``debts.py`` result (a file, or stdin when ``--in`` is omitted) into a self-contained
interactive HTML page for the Artifact tool: a banner for STALE and PAST_DUE, stat tiles (total debt,
revolving against installment, weighted APR, minimums due with the next due date, interest paid over
the trailing twelve months), the register as a table sortable by balance, APR, due date and the rest
with past-due and stale rows highlighted, balance by account and utilization bars for the revolving
accounts, an interest-paid trend line from ``history`` when any account has more than one statement,
the flags in plain words and a closing note. Prints ``{"out": path, "title": ..., "accounts": n,
"flags": n}``. Exit 2 on a missing or malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the JSON; the page formats, sorts and filters, it never recomputes totals.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Debt Picture"

BODY = """
<style>
tr.past-due td{background:color-mix(in srgb,var(--down) 9%,transparent)}
tr.past-due td:first-child{box-shadow:inset 3px 0 0 var(--down)}
tr.stale td{color:var(--muted)}tr.stale td:first-child{box-shadow:inset 3px 0 0 var(--warn)}
.fchip{display:inline-block;font-size:10.5px;letter-spacing:.04em;border:1px solid var(--grid);border-radius:999px;padding:1px 7px;margin-right:4px;color:var(--ink2)}
.fchip.hot{border-color:var(--down);color:var(--down)}.fchip.warm{border-color:var(--warn);color:var(--warn)}
.kv{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--ink2);margin:-12px 0 24px;font-variant-numeric:tabular-nums}
.kv b{color:var(--ink);font-weight:500}
</style>
<h1>Debt picture</h1>
<p class="sub" id="lede">__LEDE__</p>
<div id="explain"></div>
<ul class="flags" id="banner" hidden></ul>
<div class="tiles" id="tiles"></div>
<div class="kv" id="kv"></div>
<section class="card" id="reg-card"><h2>Register</h2><p class="sub" id="reg-sub">Latest statement per account. Click a heading to sort; past-due rows are marked red, stale ones amber.</p>
  <div class="twrap" id="register"></div></section>
<div class="grid2">
  <div class="card" id="bal-card"><h2>Balance by account</h2><p class="sub">How the total you owe splits across accounts, largest balance first.</p><div id="balances"></div></div>
  <div class="card"><h2 id="h-util">Utilization</h2><p class="sub" id="util-sub"></p><div id="util"></div></div>
</div>
<section class="card" id="trend-card" hidden><h2>Interest paid per statement</h2><p class="sub" id="trend-sub"></p><div id="trend"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note" id="note"></p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, T = D.totals || {}, AS = D.assumptions || {};
  const g = id => document.getElementById(id);
  const rows = D.accounts || [], FL = D.flags || [];
  const byId = {}; rows.forEach(r => { byId[r.id] = r; });
  const name = id => (byId[id] && byId[id].name) || id;
  const color = {}; rows.forEach((r, i) => { color[r.id] = F.S[i % 8]; });
  const day = s => s ? new Date(s + 'T00:00:00Z').toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'}) : '—';
  // terms this page needs that the shared glossary lacks
  Object.assign(FA.glossary, {
    'weighted apr': ['The average interest rate across the accounts, each counted in proportion to its balance, so large balances matter more.', 'https://www.investopedia.com/terms/w/weightedaverage.asp'],
    'interest run rate': ['What carrying the current balance costs in interest each month at its APR: balance × APR ÷ 12.', 'https://www.investopedia.com/terms/r/runrate.asp'],
    'credit limit': ['The most a card lets you borrow; balances near it push utilization up and weigh on credit scores.', 'https://www.investopedia.com/terms/c/credit_limit.asp'],
    'interest': ['What the lender charges for the balance you carry, added to what you owe each statement.', 'https://www.investopedia.com/terms/i/interest.asp'],
    'past due': ['A payment whose due date has passed; late fees and penalty rates can follow.', 'https://www.investopedia.com/terms/p/past-due.asp'],
  });
  FA.explain(g('explain'),
    `<p>This page shows every card and loan you have recorded, using the latest statement for each one. <b>Total debt</b> adds up those balances; ${FA.term('revolving debt', 'revolving')} is cards you can keep drawing on and ${FA.term('installment debt', 'installment')} is loans repaid in fixed payments. The ${FA.term('weighted apr', 'weighted APR')} is the average interest rate with big balances counting for more, and ${FA.term('utilization')} is how much of your card limits you are using.</p>` +
    `<p>The register lists one row per account; click a heading to sort. Red rows are ${FA.term('past due')}, grey rows have a statement older than ${AS.stale_days ?? 45} days. The bars compare balances and how full each card is, and the line chart tracks ${FA.term('interest')} charged statement by statement.</p>` +
    `<p>The main caveat: figures are only as current as the statements you have recorded. A payment made since the last statement is not reflected, and the ${FA.term('minimum payment', 'minimums')} shown are what keeps the accounts in good standing, not what pays them off.</p>`);
  const WORDS = {
    STALE: `the latest statement is older than ${AS.stale_days ?? 45} days`,
    PAST_DUE: 'the due date on the latest statement has passed; whether the payment was made is not recorded here',
    HIGH_UTILIZATION: `balance above ${F.pct(AS.utilization_warn, 0)} of the limit`,
    MINIMUM_ONLY: 'the last two payments were the minimum',
    MINIMUM_BELOW_INTEREST: 'the minimum does not cover a month of interest, so it is left out of the payoff input',
    OVER_LIMIT: 'balance above the credit limit',
    NO_STATEMENTS: 'no statement recorded yet',
  };
  const flagLine = f => { const [code, id] = f.split(':'); return `<li><b>${F.esc(code)}</b>${F.esc(name(id))} — ${F.esc(WORDS[code] || '')}</li>`; };
  const banner = FL.filter(f => f.startsWith('STALE:') || f.startsWith('PAST_DUE:'));
  if (banner.length) { g('banner').hidden = false; g('banner').innerHTML = banner.map(flagLine).join(''); }
  // tiles
  const nd = T.next_due;
  const tiles = [
    ['Total debt', F.money(T.total_debt), F.isNum(T.change_vs_prior) ? `<span class="${T.change_vs_prior > 0 ? 'neg' : T.change_vs_prior < 0 ? 'pos' : ''}">${F.moneyS(T.change_vs_prior)}</span> since the prior statements` : `${rows.length} accounts`],
    [FA.term('revolving debt', 'Revolving'), F.money(T.revolving), `${FA.term('installment debt', 'installment')} ${F.money(T.installment)}`],
    [FA.term('weighted apr', 'Weighted APR'), F.pct(T.weighted_apr, 2), `revolving ${F.pct(T.revolving_weighted_apr, 2)} · ${FA.term('interest run rate', 'run rate')} ${F.money(T.monthly_interest_run_rate)}/mo`],
    [FA.term('minimum payment', 'Minimums due'), F.money(T.minimum_payments_total), nd ? `next: ${F.esc(name(nd.account_id))} ${F.money(nd.amount)} on ${day(nd.due_date)}` : 'nothing due on or after the as-of date'],
    [`${FA.term('interest', 'Interest paid')}, ${FA.term('trailing 12 months', 'TTM')}`, F.money(T.interest_ttm), `revolving ${F.money(T.interest_ttm_revolving)} · statements recorded in the last year`],
  ];
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  g('kv').innerHTML = [
    `As of <b>${F.esc(day(D.as_of))}</b>`,
    `${FA.term('credit limit', 'Credit limits')} <b>${F.money(T.credit_limit_total)}</b>`,
    `${FA.term('utilization', 'Utilization')} <b>${F.pct(T.utilization)}</b> of the revolving limits`,
  ].map(s => `<span>${s}</span>`).join('');
  // register
  g('reg-sub').innerHTML = `Latest statement per account. Click a heading to sort; ${FA.term('past due', 'past-due')} rows are marked red, stale ones (statement older than ${AS.stale_days ?? 45} days) amber.`;
  const chips = fl => (fl || []).map(f => `<span class="fchip ${f === 'PAST_DUE' || f === 'OVER_LIMIT' ? 'hot' : f === 'STALE' || f === 'HIGH_UTILIZATION' ? 'warm' : ''}">${F.esc(f.replace(/_/g, ' '))}</span>`).join('');
  const reg = rows.map(r => ({...r, flag_text: (r.flags || []).join(' ')}));
  F.table(g('register'), [
    {key: 'name', label: 'Account', left: true, fmt: (v, r) => `<b>${F.esc(v)}</b>${r.issuer ? `<div class="muted" style="font-size:11.5px">${F.esc(r.issuer)}</div>` : ''}`},
    {key: 'kind', label: 'Kind', left: true},
    {key: 'balance', label: 'Balance', fmt: v => F.money(v)},
    {key: 'apr', label: 'APR', fmt: v => F.pct(v, 2)},
    {key: 'minimum_payment', label: 'Min / payment', fmt: v => F.money(v)},
    {key: 'due_date', label: 'Due', left: true, fmt: (v, r) => v ? `${F.esc(day(v))}<div class="muted" style="font-size:11.5px">${F.isNum(r.days_to_due) ? (r.days_to_due < 0 ? `${-r.days_to_due} days past` : `in ${r.days_to_due} days`) : ''}</div>` : '—'},
    {key: 'utilization', label: 'Utilization', fmt: v => F.pct(v)},
    {key: 'interest_this_period', label: 'Interest', fmt: v => F.money(v)},
    {key: 'change_vs_prior', label: 'Change', fmt: v => F.moneyS(v), cls: v => F.isNum(v) ? (v > 0 ? 'neg' : v < 0 ? 'pos' : '') : ''},
    {key: 'period_end', label: 'Statement', left: true, fmt: (v, r) => v ? `${F.esc(day(v))}<div class="muted" style="font-size:11.5px">${r.statement_age_days ?? '—'} days old</div>` : '—'},
    {key: 'flag_text', label: 'Flags', left: true, fmt: (v, r) => chips(r.flags) || '<span class="muted">—</span>'},
  ], reg, {sortKey: 'balance', onDraw: vis => {
    const trs = g('register').querySelectorAll('tbody tr');
    vis.forEach((r, i) => { const fl = r.flags || []; trs[i].className = fl.includes('PAST_DUE') ? 'past-due' : fl.includes('STALE') ? 'stale' : ''; });
  }});
  // jargon in the table headings: FA.table escapes labels, so mark the terms after the head is built (the head is not redrawn on sort)
  const termHeads = (root, map) => { root.querySelectorAll('th[data-key]').forEach(th => { if (map[th.dataset.key]) { th.innerHTML = map[th.dataset.key]; } }); FA.armTerms(root); };
  termHeads(g('register'), {
    apr: FA.term('apr', 'APR'), minimum_payment: FA.term('minimum payment', 'Min / payment'), utilization: FA.term('utilization', 'Utilization'),
    interest_this_period: FA.term('interest', 'Interest'),
  });
  // balances and utilization
  const live = rows.filter(r => F.isNum(r.balance));
  F.bars(g('balances'), live.slice().sort((a, b) => b.balance - a.balance).map(r => ({label: r.name, share: F.isNum(T.total_debt) && T.total_debt > 0 ? r.balance / T.total_debt : 0, color: color[r.id], text: F.money(r.balance, 0),
    tip: `<b>${F.esc(r.name)}</b> ${F.esc(r.kind)}<br>${F.money(r.balance)} at ${F.pct(r.apr, 2)} · run rate ${F.money(r.monthly_interest_run_rate)}/mo${r.paid_in_full ? '<br>paid in full last period: the run rate is the cost if the balance were carried' : ''}`})));
  const rev = rows.filter(r => F.isNum(r.utilization));
  g('h-util').innerHTML = FA.term('utilization', 'Utilization');
  g('util-sub').innerHTML = rev.length ? `Balance as a share of the ${FA.term('credit limit')} on each card; above ${F.pct(AS.utilization_warn, 0)} is flagged HIGH_UTILIZATION.` : '';
  if (rev.length) {
    // width is the utilization itself (full track = the whole limit), not relative to the highest account
    const root = g('util'); root.innerHTML = '';
    for (const r of rev.slice().sort((a, b) => b.utilization - a.utilization)) {
      const row = F.el('div', {class: 'bar'});
      row.appendChild(F.el('span', {class: 'l'}, F.esc(r.name)));
      const track = F.el('div', {class: 'track'}), fill = F.el('div', {class: 'fill'});
      fill.style.width = (100 * Math.min(r.utilization, 1)) + '%'; fill.style.background = color[r.id]; track.appendChild(fill); row.appendChild(track);
      row.appendChild(F.el('span', {class: 'n'}, `${F.pct(r.utilization)}${(r.flags || []).includes('HIGH_UTILIZATION') ? ' · high' : ''}`));
      F.bindTip(row, `<b>${F.esc(r.name)}</b> ${F.money(r.balance)} of ${F.money(r.credit_limit)}`);
      root.appendChild(row);
    }
  } else g('util').innerHTML = '<span class="muted">no revolving account with a credit limit</span>';
  // interest trend from the statement history
  const H = D.history || [];
  const counts = {}; H.forEach(h => { counts[h.account_id] = (counts[h.account_id] || 0) + 1; });
  const multi = rows.filter(r => (counts[r.id] || 0) >= 2);
  if (multi.length) {
    g('trend-card').hidden = false;
    const series = multi.map(r => ({name: r.name, color: color[r.id], points: H.filter(h => h.account_id === r.id).map(h => [Date.parse(h.period_end + 'T00:00:00Z'), h.interest])}));
    F.lines(g('trend'), {series, xIsDate: true, yFmt: v => F.money(v, 0), aria: 'Interest paid per statement', height: 260, yMin: 0,
      xFmt: t => new Date(t).toLocaleDateString('en-US', {month: 'short', year: '2-digit', timeZone: 'UTC'})});
    g('trend-sub').textContent = `Interest charged on each recorded statement, by statement date, for the ${multi.length} account${multi.length === 1 ? '' : 's'} with more than one statement.`;
  }
  // card help
  const costly = live.filter(r => F.isNum(r.apr) && F.isNum(r.monthly_interest_run_rate)).sort((a, b) => b.monthly_interest_run_rate - a.monthly_interest_run_rate)[0];
  F.help(g('reg-card'), {lead: 'Every card and loan from its latest statement: what you owe, the rate, and the next payment.',
    sections: costly ? [{title: `What ${costly.name} costs a month`, html: F.flow([{label: 'balance', value: F.money(costly.balance, 0)}, {op: '×', label: 'APR', value: F.pct(costly.apr, 2)}, {op: '÷', label: 'months', value: '12'}, {op: '=', label: 'interest a month', value: F.money(costly.monthly_interest_run_rate)}]) +
      (costly.paid_in_full ? '<p>This card was paid in full last period, so nothing was charged; the figure is what carrying the balance would cost.</p>' : '<p>That is the interest on today’s balance; it shrinks as the balance is paid down.</p>')}] : []});
  F.help(g('bal-card'), {lead: 'Where the money you owe sits, largest balance first.',
    sections: F.isNum(T.total_debt) ? [{title: 'Reading the bars', html: `<p>Each bar is that account’s share of the ${F.money(T.total_debt, 0)} total. Hover a bar for its rate and monthly interest.</p>`}] : []});
  const topU = rev.slice().sort((a, b) => b.utilization - a.utilization)[0];
  F.help(g('h-util').parentElement, {lead: 'How much of each card’s credit limit is in use.',
    sections: topU ? [{title: topU.name, html: F.flow([{label: 'balance', value: F.money(topU.balance, 0)}, {op: '÷', label: 'credit limit', value: F.money(topU.credit_limit, 0)}, {op: '=', label: 'utilization', value: F.pct(topU.utilization)}]) +
      `<p>Credit scores weigh utilization on each card and across all cards; lower generally reads better. The page flags anything above ${F.pct(AS.utilization_warn, 0)}.</p>`}] : []});
  if (multi.length) F.help(g('trend-card'), {lead: 'Interest charged on each recorded statement, over time.',
    sections: [{title: 'Reading the lines', html: '<p>Each line is one account; each point is one statement. A rising line means interest is growing, usually because the balance or the rate went up.</p>'}]});
  // flags
  g('flags').innerHTML = FL.length ? FL.map(flagLine).join('') : '<li class="muted">None</li>';
  FA.armTerms(document);
  g('note').textContent = `Figures come from the recorded statements as of ${day(D.as_of)}; the run rate is balance × APR / 12 on the latest balance and the trailing-twelve-month figures cover the statements recorded in that window. Payoff order belongs to the personal-finance skill. General information, not financial advice.`;
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _money(v: object) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "—"
    return ("-" if v < 0 else "") + f"${abs(v):,.2f}"


def _lede(picture: dict) -> str:
    """The static one-line summary (readable without JS); formats the JSON's own figures."""
    t = picture.get("totals") or {}
    apr = t.get("weighted_apr")
    nd = t.get("next_due") or {}
    parts = [
        f"as of {picture.get('as_of') or '—'}",
        f"total debt {_money(t.get('total_debt'))}",
        f"revolving {_money(t.get('revolving'))}",
        f"installment {_money(t.get('installment'))}",
        f"weighted APR {100 * apr:.2f}%" if isinstance(apr, (int, float)) else "weighted APR —",
        f"minimums {_money(t.get('minimum_payments_total'))}",
        f"next due {nd.get('due_date')} ({nd.get('account_id')})" if nd else "nothing due",
    ]
    return html.escape(" · ".join(parts))


def build(picture: dict) -> str:
    if not isinstance(picture, dict) or "totals" not in picture or "debt_input" not in picture:
        raise InvalidInput("input must be a debts.py result (a JSON object with totals, accounts and debt_input)")
    return page.render(TITLE, picture, BODY.replace("__LEDE__", _lede(picture)), SCRIPT)


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            picture = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read debts JSON: {exc}") from exc
        out = page.write(ns.out, build(picture))
        return {"out": str(out), "title": TITLE, "accounts": len(picture.get("accounts") or []), "flags": len(picture.get("flags") or [])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
