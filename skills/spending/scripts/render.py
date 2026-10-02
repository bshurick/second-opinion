#!/usr/bin/env python3
"""Usage: render.py [--in month.json] [--changes changes.json] --out page.html

Turns one ``spend.py month`` result (a file, or stdin when ``--in`` is omitted) into a self-contained
interactive HTML page for the Artifact tool: a banner for PARTIAL_MONTH and NO_INCOME_DATA, stat tiles
(spend, income, net, savings rate), category bars that drill down on click to the merchants inside a
category and then to that merchant's transactions (client-side, from the result's ``transactions``,
item rows included, with a back control), a monthly cash-flow line when ``months`` has several months,
the top merchants, new merchants, the recurring charges, the flags in plain words and a closing note.
``--changes`` adds the matching ``spend.py changes`` result as a "What changed" section (category and
merchant moves with the charges behind them, recurring charges missing or newly detected). Prints
``{"out": path, "title": ..., "month": ..., "transactions": n, "flags": n}``. Exit 2 on a missing or
malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the JSON; the page formats, sorts, filters and groups rows, it never recomputes totals.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

TITLE = "Spending Review"

BODY = """
<style>
.bar.click{cursor:pointer;border-radius:4px}.bar.click:hover .l,.bar.click:focus-visible .l{text-decoration:underline}
.bar.click:focus-visible{outline:2px solid var(--s1);outline-offset:1px}
.crumb{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:8px;font-size:13px;color:var(--ink2)}
.crumb b{color:var(--ink)}
button.back{font:inherit;font-size:12px;color:var(--ink);background:var(--surface);border:1px solid var(--grid);border-radius:5px;padding:3px 9px;cursor:pointer}
.kv{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--ink2);margin:-12px 0 24px;font-variant-numeric:tabular-nums}
.kv b{color:var(--ink);font-weight:500}
</style>
<h1>Spending review</h1>
<p class="sub" id="lede">__LEDE__</p>
<div id="explain"></div>
<ul class="flags" id="banner" hidden></ul>
<div class="tiles" id="tiles"></div>
<div class="kv" id="kv"></div>
<section class="card" id="cats-card"><h2>Categories</h2><p class="sub" id="cats-sub"></p>
  <div class="crumb"><button class="back" id="back" type="button" hidden>&larr; Back</button><span id="crumb"></span></div>
  <div id="cats"></div></section>
<section class="card" id="flow-card" hidden><h2 id="h-flow">Monthly cash flow</h2><p class="sub" id="flow-sub"></p><div id="flow"></div></section>
<section class="card" id="changes-card" hidden><h2>What changed</h2><p class="sub" id="changes-sub"></p>
  <div class="grid2" style="margin-bottom:0">
    <div><h2>Categories</h2><ul class="news" id="chg-cats"></ul></div>
    <div><h2>Merchants</h2><ul class="news" id="chg-mers"></ul></div>
  </div></section>
<div class="grid2">
  <div class="card" id="mer-card"><h2>Top merchants</h2><p class="sub">The merchants that took the most money this month.</p><div class="twrap" id="merchants"></div>
    <h2 style="margin-top:14px">New this month</h2><p id="new-merchants" class="sub" style="margin-bottom:0"></p></div>
  <div class="card"><h2 id="h-rec">Recurring charges</h2><p class="sub" id="rec-sub"></p><div class="twrap" id="recurring"></div>
    <div id="rec-due"></div></div>
</div>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note" id="note"></p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, C = D.changes || null;
  const g = id => document.getElementById(id);
  const FL = D.flags || [], TX = D.transactions || [], A = D.accounts || {};
  const acct = id => (A[id] && A[id].name) || id || '—';
  // terms this page needs that the shared glossary lacks
  Object.assign(FA.glossary, {
    'cash flow': ['Money coming in (income) set against money going out (spend) over a period.', 'https://www.investopedia.com/terms/c/cashflow.asp'],
    'net cash flow': ['Income minus spend for the month; positive means money was left over, negative means more went out than came in.', 'https://www.investopedia.com/terms/c/cashflow.asp'],
    'fees and interest': ['Bank or card fees plus interest charged on balances: the cost of holding the account or borrowing, not a purchase.', 'https://www.investopedia.com/terms/i/interest.asp'],
    'transfer': ['Money moved between your own accounts, such as paying a card from checking; not spending, so it is left out of the totals.', 'https://www.investopedia.com/terms/t/transfer.asp'],
  });
  FA.explain(g('explain'),
    `<p>This page adds up the card and bank exports (or transcribed receipts) you imported for ${F.esc(D.month || 'the month')}. <b>Spend</b> is what went out to merchants after refunds; <b>income</b> is deposits into checking or savings; <b>net</b> is income minus spend and the ${FA.term('savings rate')} is net as a share of income. ${FA.term('transfer', 'Transfers')} between your own accounts are not spending and sit outside the totals.</p>` +
    `<p>The category bars show where the money went, longest bar first, with the change against your recent average; click a bar to see the merchants inside it, then a merchant to see each charge. ${FA.term('recurring charge', 'Recurring charges')} are merchants that bill you on a steady schedule.</p>` +
    `<p>The main caveat: totals only cover the accounts you imported. With only card exports, income and the savings rate are unknown, and a month that is not over yet shows partial figures.</p>`);
  const WORDS = {
    PARTIAL_MONTH: 'The month is not over or the export stops early, so these totals are partial.',
    NO_INCOME_DATA: 'No checking or savings export is imported, so income and the savings rate are unknown.',
    UNCATEGORIZED_HIGH: 'Over 10% of spend has no category; category rules would sort it.',
    SINGLE_ACCOUNT: 'Only one account is imported, so transfers cannot be matched across accounts yet.',
  };
  const flagLine = f => `<li><b>${F.esc(f)}</b>${F.esc(WORDS[f] || '')}</li>`;
  // banner: the flags that qualify the headline figures
  const banner = FL.filter(f => f === 'PARTIAL_MONTH' || f === 'NO_INCOME_DATA');
  if (banner.length) { g('banner').hidden = false; g('banner').innerHTML = banner.map(flagLine).join(''); }
  // tiles
  const noInc = FL.includes('NO_INCOME_DATA');
  const U = D.uncategorized || {};
  const tiles = [
    ['Spend', F.money(D.spend_total), `${(D.by_category || []).length} categories · refunds ${F.money(D.refunds_total)}`],
    ['Income', noInc ? '—' : F.money(D.income_total), noInc ? 'no checking data' : 'checking and savings deposits'],
    [FA.term('net cash flow', 'Net'), noInc ? '—' : `<span class="${F.cls(D.net)}">${F.moneyS(D.net)}</span>`, noInc ? 'needs income data' : 'income minus spend'],
    [FA.term('savings rate', 'Savings rate'), noInc ? '—' : F.pct(D.savings_rate), noInc ? 'needs income data' : 'net as a share of income'],
  ];
  g('tiles').innerHTML = tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
  g('kv').innerHTML = [
    `${FA.term('transfer', 'Transfers')} <b>${F.money(D.transfers_total)}</b> (both sides of each pair counted)`,
    `${FA.term('fees and interest', 'Fees & interest')} <b>${F.money(D.fees_and_interest)}</b>`,
    `Uncategorized <b>${F.money(U.amount)}</b> (${U.count ?? 0} rows)`,
  ].map(s => `<span>${s}</span>`).join('');
  // categories with drill-down: category -> merchants -> that merchant's transactions
  const cats = D.by_category || [];
  const color = {}; cats.forEach((c, i) => { color[c.category] = F.S[i % 8]; });
  const exploded = TX.some(t => t.item_name != null);
  g('cats-sub').textContent = `Share of spend; change against the average of the prior ${D.compare_months ?? '—'} months with spend. ` +
    (exploded ? 'Receipt items are broken out into their own rows.' : 'Charges as imported.') + ' Click a bar to drill down.';
  let level = 0, cat = null, mer = null;
  const root = g('cats'), crumb = g('crumb'), back = g('back');
  const barRow = (label, share, col, text, tip, onClick) => {
    const attrs = {class: 'bar' + (onClick ? ' click' : '')};
    if (onClick) { attrs.role = 'button'; attrs.tabindex = '0'; }
    const r = F.el('div', attrs);
    r.appendChild(F.el('span', {class: 'l'}, label));
    const track = F.el('div', {class: 'track'}), fill = F.el('div', {class: 'fill'});
    fill.style.width = (100 * share) + '%'; fill.style.background = col; track.appendChild(fill); r.appendChild(track);
    r.appendChild(F.el('span', {class: 'n'}, text));
    if (tip) F.bindTip(r, tip);
    if (onClick) { r.addEventListener('click', onClick); r.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }); }
    return r;
  };
  const deltaHtml = c => F.isNum(c.delta) ? `<span class="${c.delta > 0 ? 'neg' : c.delta < 0 ? 'pos' : ''}">${F.moneyS(c.delta)}</span>` : '<span class="muted">new</span>';
  const draw = () => {
    root.innerHTML = ''; back.hidden = level === 0;
    if (level === 0) {
      crumb.innerHTML = '<b>All categories</b>';
      if (!cats.length) { root.innerHTML = '<span class="muted">no spend this month</span>'; return; }
      const max = Math.max(...cats.map(c => Math.abs(c.amount || 0)), 1e-9);
      for (const c of cats) {
        const tip = `<b>${F.esc(c.category)}</b> ${F.money(c.amount)} · ${F.pct(c.share)} of spend<br>avg prior ${F.money(c.avg_prior)} · change ${F.moneyS(c.delta)} (${F.pct(c.delta_pct, 0, true)})<br>${c.transactions ?? 0} rows`;
        root.appendChild(barRow(`<b>${F.esc(c.category)}</b>`, Math.abs(c.amount || 0) / max, color[c.category], `${F.money(c.amount)} · ${F.pct(c.share)} · ${deltaHtml(c)}`, tip, () => { level = 1; cat = c.category; draw(); }));
      }
    } else if (level === 1) {
      crumb.innerHTML = `All categories &rsaquo; <b>${F.esc(cat)}</b>`;
      const groups = {};
      for (const t of TX) { if (t.category !== cat) continue; const gp = groups[t.merchant] || (groups[t.merchant] = {merchant: t.merchant, amount: 0, n: 0}); gp.amount += t.amount || 0; gp.n += 1; }
      const rows = Object.values(groups).sort((a, b) => b.amount - a.amount || a.merchant.localeCompare(b.merchant));
      if (!rows.length) { root.innerHTML = '<span class="muted">no transaction rows carried for this category</span>'; return; }
      const max = Math.max(...rows.map(r => Math.abs(r.amount)), 1e-9);
      for (const r of rows) root.appendChild(barRow(F.esc(r.merchant), Math.abs(r.amount) / max, color[cat], `${F.money(r.amount)} · ${r.n} row${r.n === 1 ? '' : 's'}`, null, () => { level = 2; mer = r.merchant; draw(); }));
    } else {
      crumb.innerHTML = `All categories &rsaquo; ${F.esc(cat)} &rsaquo; <b>${F.esc(mer)}</b>`;
      const rows = TX.filter(t => t.category === cat && t.merchant === mer).sort((a, b) => a.date.localeCompare(b.date));
      const wrap = F.el('div', {class: 'twrap'});
      wrap.innerHTML = '<table><thead><tr><th class="l">Date</th><th class="l">Description</th><th class="l">Item</th><th class="l">Detail</th><th class="l">Account</th><th>Amount</th></tr></thead><tbody>' +
        rows.map(t => `<tr><td class="l">${F.esc(t.date)}</td><td class="l">${F.esc(t.description || '')}</td><td class="l">${t.item_name != null ? F.esc(t.item_name) : (t.has_items ? '<span class="muted">remainder</span>' : '')}</td><td class="l">${F.esc(t.detail || '')}</td><td class="l">${F.esc(acct(t.account_id))}</td><td class="${t.amount < 0 ? 'pos' : ''}">${F.money(t.amount)}</td></tr>`).join('') + '</tbody></table>';
      root.appendChild(wrap);
    }
  };
  back.addEventListener('click', () => { if (level === 2) { mer = null; level = 1; } else { cat = null; level = 0; } draw(); });
  draw();
  // monthly cash flow when several months are carried
  const M = D.months || [];
  if (M.length >= 2) {
    g('flow-card').hidden = false;
    g('h-flow').innerHTML = `Monthly ${FA.term('cash flow')}`;
    const x = m => Date.parse(m.month + '-01T00:00:00Z');
    const series = [{name: 'Spend', points: M.map(m => [x(m), m.spend]), color: F.S[0]}];
    if (M.some(m => F.isNum(m.income))) {
      series.push({name: 'Income', points: M.map(m => [x(m), m.income]), color: F.S[1]});
      series.push({name: 'Net', points: M.map(m => [x(m), m.net]), color: F.S[2]});
    }
    const fmt = t => new Date(t).toLocaleDateString('en-US', {month: 'short', year: '2-digit', timeZone: 'UTC'});
    F.lines(g('flow'), {series, xIsDate: true, zeroLine: true, yFmt: v => F.money(v, 0), xFmt: fmt, aria: 'Monthly cash flow', height: 260});
    g('flow-sub').textContent = `${M.length} months, ${M[0].month} to ${M[M.length - 1].month}. Income counts checking and savings deposits only; transfers are excluded.`;
  }
  // what changed (spend.py changes)
  if (C) {
    g('changes-card').hidden = false;
    g('changes-sub').textContent = `Moves over ${F.pct(C.threshold, 0)} of the prior ${C.compare_months ?? '—'}-month average and $25; the charges behind each move follow.`;
    const line = e => {
      const name = e.category || e.merchant;
      const head = e.new ? `<b>${F.esc(name)}</b> new this month at ${F.money(e.amount)}`
        : `<b>${F.esc(name)}</b> ${F.money(e.amount)} vs avg ${F.money(e.avg_prior)} (<span class="${e.delta > 0 ? 'neg' : 'pos'}">${F.moneyS(e.delta)}, ${F.pct(e.delta_pct, 0, true)}</span>)`;
      const ex = (e.explained_by || []).map(x => `${F.esc(x.date)} ${F.esc(x.merchant)} ${F.money(x.amount)}`).join(' · ');
      return `<li>${head}${ex ? `<div class="muted">${ex}</div>` : ''}</li>`;
    };
    g('chg-cats').innerHTML = (C.categories || []).length ? C.categories.map(line).join('') : '<li class="muted">no category moved past the threshold</li>';
    g('chg-mers').innerHTML = (C.merchants || []).length ? C.merchants.map(line).join('') : '<li class="muted">no merchant moved past the threshold</li>';
  }
  // top merchants
  const TM = D.top_merchants || [];
  if (TM.length) F.table(g('merchants'), [
    {key: 'merchant', label: 'Merchant', left: true},
    {key: 'amount', label: 'Amount', fmt: v => F.money(v)},
    {key: 'count', label: 'Charges'},
    {key: 'categories', label: 'Categories', left: true, fmt: v => F.esc((v || []).join(', '))},
  ], TM, {sortKey: 'amount'});
  else g('merchants').innerHTML = '<span class="muted">none</span>';
  const NM = D.new_merchants || [];
  g('new-merchants').textContent = NM.length ? NM.join(', ') : 'none';
  // recurring charges through the month's end
  const R = D.recurring || [];
  g('h-rec').innerHTML = FA.term('recurring charge', 'Recurring charges');
  g('rec-sub').textContent = R.length ? 'Merchants that bill on a steady schedule (the cadence), detected through the month; creep is how much the latest charge has risen above the first.' : '';
  if (R.length) F.table(g('recurring'), [
    {key: 'merchant', label: 'Merchant', left: true},
    {key: 'cadence', label: 'Cadence', left: true},
    {key: 'typical_amount', label: 'Typical', fmt: v => F.money(v)},
    {key: 'count', label: 'Charges'},
    {key: 'creep_pct', label: 'Creep', fmt: v => F.pct(v, 0, true), cls: v => F.isNum(v) && v > 0 ? 'neg' : ''},
    {key: 'annual_cost', label: 'Per year', fmt: v => F.money(v)},
    {key: 'next_expected', label: 'Next', left: true},
  ], R, {sortKey: 'annual_cost'});
  else g('recurring').innerHTML = '<span class="muted">no recurring series detected yet (three charges at a steady cadence are needed)</span>';
  if (C) {
    const miss = C.missing_recurring || [], fresh = C.new_recurring || [];
    let h = '';
    if (miss.length) h += `<p class="sub" style="margin:12px 0 4px">Due but not charged this month</p><ul class="news">${miss.map(m => `<li><b>${F.esc(m.merchant)}</b> ${F.money(m.typical_amount)} ${F.esc(m.cadence)}, expected ${F.esc(m.expected)}</li>`).join('')}</ul>`;
    if (fresh.length) h += `<p class="sub" style="margin:12px 0 4px">Newly recurring this month</p><ul class="news">${fresh.map(m => `<li><b>${F.esc(m.merchant)}</b> ${F.money(m.typical_amount)} ${F.esc(m.cadence)}</li>`).join('')}</ul>`;
    g('rec-due').innerHTML = h || '<p class="sub" style="margin:12px 0 0">Recurring due: none missing, none new.</p>';
  }
  // card help
  const c0 = cats[0];
  F.help(g('cats-card'), {lead: `Where the money went in ${F.esc(D.month || 'the month')}, by category. Click a category for its merchants, and a merchant for its charges.`,
    sections: c0 && F.isNum(D.spend_total) && D.spend_total ? [{title: `${c0.category}’s share`, html: F.flow([{label: c0.category, value: F.money(c0.amount)}, {op: '÷', label: 'all spending', value: F.money(D.spend_total)}, {op: '=', label: 'share', value: F.pct(c0.amount / D.spend_total)}]) +
      '<p>Spending leaves out income and transfers between your own accounts, so moving money to savings does not count as spending.</p>'}] : []});
  const mLast = M[M.length - 1];
  if (M.length >= 2) F.help(g('flow-card'), {lead: 'Money in, money out, and what was left, month by month.',
    sections: mLast && F.isNum(mLast.income) ? [{title: mLast.month, html: F.flow([{label: 'income', value: F.money(mLast.income)}, {op: '−', label: 'spending', value: F.money(mLast.spend)}, {op: '=', label: 'left over', value: F.moneyS(mLast.net)}]) +
      (F.isNum(mLast.savings_rate) ? `<p>Left over as a share of income is the savings rate: ${F.pct(mLast.savings_rate)} that month.</p>` : '')}] : []});
  if (C) F.help(g('changes-card'), {lead: 'Categories and merchants that moved a lot against your recent average, with the charges behind each move.',
    sections: [{title: 'What counts as a move', html: `<p>A change is listed when it is more than ${F.pct(C.threshold, 0)} away from the average of the prior ${C.compare_months ?? '—'} months and at least $25, so small wobbles stay off the list.</p>`}]});
  F.help(g('mer-card'), {lead: 'The merchants that took the most money this month.',
    sections: [{title: 'New this month', html: '<p>Merchants listed underneath had no charges in the months before, which is a quick way to spot a new subscription or a one-off.</p>'}]});
  const r0 = R.slice().sort((a, b) => (b.annual_cost || 0) - (a.annual_cost || 0))[0];
  F.help(g('h-rec').parentElement, {lead: 'Charges that repeat on a steady schedule, with what each costs over a year.',
    sections: r0 && F.isNum(r0.typical_amount) && F.isNum(r0.annual_cost) ? [{title: `${r0.merchant} over a year`, html: F.flow([{label: `typical ${r0.cadence || ''} charge`, value: F.money(r0.typical_amount)}, {op: '×', label: 'charges a year', value: F.num(r0.annual_cost / r0.typical_amount, 0)}, {op: '=', label: 'per year', value: F.money(r0.annual_cost)}]) +
      '<p>Creep is how much the latest charge has risen above the first one in the series; it catches quiet price increases.</p>'}] : [{title: 'How a series is found', html: '<p>Three charges from the same merchant at a steady interval make a recurring series.</p>'}]});
  // flags
  g('flags').innerHTML = FL.length ? FL.map(flagLine).join('') : '<li class="muted">None</li>';
  FA.armTerms(document);
  g('note').textContent = `Figures come from imported exports through the latest transaction date of ${D.month || 'the month'}; a spend row excludes income and transfers, so refunds net out. ` +
    (C ? 'What changed and the recurring lists come from the matching changes report. ' : '') + 'General information, not financial advice.';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _money(v: object) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "—"
    return ("-" if v < 0 else "") + f"${abs(v):,.2f}"


def _month_name(month: object) -> str:
    try:
        return datetime.strptime(str(month), "%Y-%m").strftime("%B %Y")
    except ValueError:
        return str(month or "")


def _lede(month: dict) -> str:
    """The static one-line summary (readable without JS); formats the JSON's own figures."""
    flags = month.get("flags") or []
    no_income = "NO_INCOME_DATA" in flags
    rate = month.get("savings_rate")
    rate_s = f"{100 * rate:.1f}%" if isinstance(rate, (int, float)) and not no_income else "—"
    parts = [
        _month_name(month.get("month")),
        f"spend {_money(month.get('spend_total'))}",
        "income —" if no_income else f"income {_money(month.get('income_total'))}",
        "net —" if no_income else f"net {_money(month.get('net'))}",
        f"savings rate {rate_s}",
    ]
    return html.escape(" · ".join(parts))


def build(month: dict, changes: dict | None = None) -> str:
    if not isinstance(month, dict) or "by_category" not in month or "spend_total" not in month:
        raise InvalidInput("input must be a spend.py month result (a JSON object with by_category and spend_total)")
    if changes is not None and (not isinstance(changes, dict) or "categories" not in changes or "merchants" not in changes):
        raise InvalidInput("--changes must be a spend.py changes result (a JSON object with categories and merchants)")
    data = {**month, "changes": changes}
    return page.render(TITLE, data, BODY.replace("__LEDE__", _lede(month)), SCRIPT)


def _read(path: str | None, what: str) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
        return json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInput(f"could not read {what} JSON: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--changes", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        month = _read(ns.inp, "month")
        changes = _read(ns.changes, "changes") if ns.changes else None
        out = page.write(ns.out, build(month, changes))
        return {"out": str(out), "title": TITLE, "month": month.get("month"), "transactions": len(month.get("transactions") or []), "flags": len(month.get("flags") or [])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
