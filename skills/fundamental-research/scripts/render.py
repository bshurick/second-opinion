#!/usr/bin/env python3
"""Usage: render.py [--in holdings.json] --out page.html

Turns one ``holdings.py`` result (a file, or stdin when ``--in`` is omitted) into a self-contained
interactive HTML page for the Artifact tool: stat tiles (reported value and its change versus the
prior quarter, position count with new and exited, top-5 and top-10 concentration, filing lag), the
ten largest holdings as weight bars, a concentration donut (top ten plus the rest), a sortable table
of every reported holding, four sortable tables
(new, exited, increased, trimmed) with share changes and weights, the filing links, flags and the
script's notes. Prints ``{"out", "title", "manager", "positions", "changes", "flags"}``. Exit 2 on a
missing or malformed input.

The page is a fragment (no html/head/body tags): the Artifact host wraps it. Every number shown comes
from the JSON; the page formats and draws, it never recomputes a figure.
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

TITLE = "13F Holdings"

BODY = """
<h1 id="title">13F Holdings</h1>
<p class="sub" id="asof">{{HEADLINE}}</p>
<div id="explain"></div>
<div class="tiles" id="tiles"></div>
<style>#top .bar{grid-template-columns:minmax(150px,1.3fr) 4fr auto}</style>
<div class="grid2">
  <div class="card"><h2 id="top-h">Top holdings</h2><p class="sub">The ten largest positions by reported value, as a share of the whole report.</p><div id="top"></div></div>
  <div class="card"><h2 id="conc-h">Concentration</h2><p class="sub">How much of the report sits in the ten largest positions.</p><div id="conc"></div><p class="note" id="conc-note"></p></div>
</div>
<section class="card"><h2>All reported holdings</h2><p class="sub" id="all-sub">Every position in the report, largest first; sort by any column.</p><div class="twrap" id="all"></div></section>
<section class="card"><h2>New</h2><p class="sub">Positions in this report that were not in the prior quarter's.</p><div class="twrap" id="new"></div></section>
<section class="card"><h2>Exited</h2><p class="sub">Positions in the prior quarter's report that are gone from this one.</p><div class="twrap" id="exited"></div></section>
<section class="card"><h2>Increased</h2><p class="sub">Positions with more shares than last quarter, ranked by value.</p><div class="twrap" id="increased"></div></section>
<section class="card"><h2>Trimmed</h2><p class="sub">Positions with fewer shares than last quarter, ranked by value.</p><div class="twrap" id="trimmed"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul><ul class="news" id="notes"></ul><p class="note" id="links"></p></section>
<p class="note">A 13F lists a manager's US-listed long positions and options at quarter end, filed up to 45 days later; it omits short positions, bonds, cash and non-US holdings, so the total is not the fund's assets and the picture is already dated when published. Changes are classified by share count so price moves do not masquerade as buying. Nothing here explains why a position changed, and nothing here is a recommendation. General information from the filings named, not financial advice.</p>
<noscript><p class="note">JavaScript is off: the charts and tables are not drawn. The headline figures are in the line under the title; the full result is embedded in the page as JSON.</p></noscript>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, T = D.totals || {}, M = D.manager || {}, C = D.current || {}, P = D.previous;
  const g = id => document.getElementById(id);
  const isNum = F.isNum;
  const big = v => { if (!isNum(v)) return '—'; const a = Math.abs(v), s = v < 0 ? '-' : ''; return a >= 1e9 ? s + '$' + (a / 1e9).toFixed(2) + 'B' : a >= 1e6 ? s + '$' + (a / 1e6).toFixed(1) + 'M' : s + '$' + F.num(a, 0); };
  const p1 = v => isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(1) + '%' : '—';
  const w1 = v => isNum(v) ? v.toFixed(2) + '%' : '—';
  const n0 = v => F.num(v, 0);
  const setHtml = (id, html) => { const n = g(id); n.innerHTML = html; F.armTerms(n); };
  Object.assign(F.glossary, {
    '13f': ['A quarterly SEC filing in which managers with over $100 million list the US-listed stocks and options they held at quarter end, due 45 days later.', 'https://www.investopedia.com/terms/f/form-13f.asp'],
    'cusip': ['The nine-character identifier of a security; a 13F reports holdings by CUSIP rather than ticker.', 'https://www.investopedia.com/terms/c/cusipnumber.asp'],
    'weight': ['A position\'s reported value as a share of the whole report.', 'https://www.investopedia.com/terms/p/portfolio-weight.asp'],
    'concentration': ['How much of the total sits in a few positions.', 'https://www.investopedia.com/terms/c/concentrationrisk.asp'],
    'put': ['An option to sell shares at a set price; in a 13F it is listed as its own row and usually marks a hedge or a bet on a fall.', 'https://www.investopedia.com/terms/p/putoption.asp'],
    'call': ['An option to buy shares at a set price; in a 13F it is listed as its own row.', 'https://www.investopedia.com/terms/c/calloption.asp'],
  });
  const ident = r => `<b>${F.esc(r.issuer)}</b> <span class="muted">${F.esc(r.class)}${r.put_call ? ' · ' + FA.term(String(r.put_call).toLowerCase(), r.put_call) : ''}</span>`;
  FA.explain(g('explain'), `<p>This page compares one manager's latest ${FA.term('13f', '13F')} filing with the previous quarter's. The tiles give the size of the report and how concentrated it is; the bars show the largest positions by ${FA.term('weight')}; the four tables list what was added, dropped, increased or trimmed, judged by share count so that price moves do not look like trading.</p><p>What it cannot show: short positions, bonds, cash, non-US holdings, anything filed confidentially, and the reason behind any change. The filing was already up to 45 days old when it appeared.</p>`);
  const changes = ['new', 'exited', 'increased', 'trimmed'].map(k => (D[k] || []).length + ((D.truncated || {})[k] || 0));
  const tiles = [
    ['Reported value', big(T.value), P ? `${p1(T.value_change_pct)} vs ${F.esc(P.report_date || 'prior')} (${big(T.previous_value)})` : 'no prior quarter in the index'],
    ['Positions', String(T.positions ?? '—'), `${changes[0]} new · ${changes[1]} exited · ${changes[2]} increased · ${changes[3]} trimmed · ${D.unchanged ?? 0} unchanged`],
    [FA.term('concentration', 'Concentration'), w1((D.concentration || {}).top_5_pct), `top 5 · top 10 ${w1((D.concentration || {}).top_10_pct)}`],
    ['Filing lag', isNum(D.lag_days) ? `${D.lag_days} days` : '—', `quarter ended ${F.esc(C.report_date || '—')}, filed ${F.esc(C.filing_date || '—')}`],
  ];
  setHtml('tiles', tiles.map(([k, v, d]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join(''));
  setHtml('title', `${F.esc(M.name || 'Manager')} — ${FA.term('13f', '13F')} holdings`);
  setHtml('top-h', `Top holdings by ${FA.term('weight')}`);
  const top = D.top || [];
  if (top.length) F.bars(g('top'), top.slice(0, 10).map((h, i) => ({label: h.issuer, share: (h.weight_pct || 0) / 100, color: F.S[i % 8], text: `${w1(h.weight_pct)} · ${big(h.value)}`, tip: `${ident(h)}<br>${FA.term('cusip', 'CUSIP')} ${F.esc(h.cusip)} · ${n0(h.shares)} shares · ${big(h.value)} · ${w1(h.weight_pct)}`})));
  else g('top').innerHTML = '<span class="muted">no holdings</span>';
  if (top.length) {
    F.table(g('all'), [{key: 'issuer', label: 'Issuer', left: true, fmt: (v, r) => ident(r)}, {key: 'shares', label: 'Shares', fmt: n0}, {key: 'value', label: 'Value', fmt: big}, {key: 'weight_pct', label: 'Weight', fmt: w1}, {key: 'cusip', label: 'CUSIP', fmt: F.esc}], top, {sortKey: 'value'});
    const missing = (T.positions || 0) - top.length;
    setHtml('all-sub', `${top.length} of ${T.positions ?? top.length} positions, largest first; sort by any column.${missing > 0 ? ` ${missing} smaller position${missing > 1 ? 's are' : ' is'} not listed (raise --limit).` : ''}`);
  } else g('all').innerHTML = '<span class="muted">no holdings</span>';
  setHtml('conc-h', FA.term('concentration', 'Concentration'));
  const ten = top.slice(0, 10); const tenVal = ten.reduce((a, h) => a + (h.value || 0), 0); const rest = Math.max((T.value || 0) - tenVal, 0);
  if (ten.length) F.donut(g('conc'), [...ten.map((h, i) => ({label: h.issuer, value: h.value || 0, color: F.S[i % 8]})), ...(rest > 0 ? [{label: 'All other positions', value: rest, color: 'var(--grid)'}] : [])], `top ${ten.length}`);
  setHtml('conc-note', `Top 5 ${w1((D.concentration || {}).top_5_pct)} · top 10 ${w1((D.concentration || {}).top_10_pct)} of ${big(T.value)} reported.`);
  const cusipCol = {key: 'cusip', label: 'CUSIP', fmt: F.esc};
  const tables = {
    new: [{key: 'issuer', label: 'Issuer', left: true, fmt: (v, r) => ident(r)}, {key: 'shares', label: 'Shares', fmt: n0}, {key: 'value', label: 'Value', fmt: big}, {key: 'weight_pct', label: 'Weight', fmt: w1}, cusipCol],
    exited: [{key: 'issuer', label: 'Issuer', left: true, fmt: (v, r) => ident(r)}, {key: 'previous_shares', label: 'Shares held', fmt: n0}, {key: 'previous_value', label: 'Prior value', fmt: big}, cusipCol],
    increased: [{key: 'issuer', label: 'Issuer', left: true, fmt: (v, r) => ident(r)}, {key: 'shares', label: 'Shares', fmt: n0}, {key: 'previous_shares', label: 'Prior shares', fmt: n0}, {key: 'shares_change_pct', label: 'Change', fmt: p1, cls: F.cls}, {key: 'value', label: 'Value', fmt: big}, {key: 'weight_pct', label: 'Weight', fmt: w1}, cusipCol],
    trimmed: [{key: 'issuer', label: 'Issuer', left: true, fmt: (v, r) => ident(r)}, {key: 'shares', label: 'Shares', fmt: n0}, {key: 'previous_shares', label: 'Prior shares', fmt: n0}, {key: 'shares_change_pct', label: 'Change', fmt: p1, cls: F.cls}, {key: 'value', label: 'Value', fmt: big}, {key: 'weight_pct', label: 'Weight', fmt: w1}, cusipCol],
  };
  for (const [k, cols] of Object.entries(tables)) {
    const rows = D[k] || []; const root = g(k);
    if (!rows.length) { root.innerHTML = `<span class="muted">${P || k === 'new' ? 'none' : 'no prior quarter to compare'}</span>`; continue; }
    F.table(root, cols, rows, {sortKey: k === 'exited' ? 'previous_value' : 'value'});
    const th = root.querySelector('th[data-key="weight_pct"]'); if (th) th.innerHTML = FA.term('weight', 'Weight');
    const tc = root.querySelector('th[data-key="cusip"]'); if (tc) tc.innerHTML = FA.term('cusip', 'CUSIP');
    F.armTerms(root);
    const cut = (D.truncated || {})[k]; if (cut) root.insertAdjacentHTML('beforeend', `<p class="note">${cut} more not shown (raise --limit).</p>`);
  }
  // card help
  const card = id => g(id).parentElement;
  const qtr = `the quarter ended ${F.esc(C.report_date || '—')}`;
  const t0 = top[0];
  F.help(card('top-h'), {lead: `The ten largest positions in the manager’s 13F for ${qtr}, as a share of everything reported.`,
    sections: t0 ? [{title: `How a weight is worked out, using ${t0.issuer}`, html: F.flow([{label: 'position value', value: big(t0.value)}, {op: '÷', label: 'whole report', value: big(T.value)}, {op: '=', label: 'weight', value: w1(t0.weight_pct)}]) +
      `<p>A 13F lists only US-listed stocks and options held at quarter end, filed up to 45 days later${isNum(D.lag_days) ? ` (this one ${D.lag_days} days)` : ''}, so it can be months out of date.</p>`}] : []});
  F.help(card('conc-h'), {lead: 'How much of the report sits in the ten largest positions.',
    sections: ten.length ? [{title: 'Top ten against the rest', html: F.flow([{label: 'top ten', value: big(tenVal)}, {op: '+', label: 'every other position', value: big(rest)}, {op: '=', label: 'whole report', value: big(T.value)}]) + '<p>A high top-ten share means the manager makes a few large bets rather than many small ones.</p>'}] : []});
  F.help(card('all-sub'), {lead: 'Every position in the report, largest first.',
    sections: [{title: 'Reading a row', html: '<p>Value is what the position was worth at quarter end; weight is its share of the report. An option row (put or call) is listed separately from the shares of the same company.</p>'}]});
  const chg = {new: ['Positions in this report that were not in the prior quarter’s.', 'A new line can be a fresh purchase or a holding that crossed the reporting threshold.'],
    exited: ['Positions in the prior quarter’s report that are gone from this one.', 'An exit can be a full sale, or a position that shrank below what has to be reported.'],
    increased: ['Positions with more shares than last quarter.', 'The change column compares share counts, so price moves do not count as buying.'],
    trimmed: ['Positions with fewer shares than last quarter.', 'The change column compares share counts, so price moves do not count as selling.']};
  for (const [k, [lead, note]] of Object.entries(chg)) { const r0 = (D[k] || [])[0];
    const sec = (k === 'increased' || k === 'trimmed') && r0 && isNum(r0.shares) && isNum(r0.previous_shares) ? [{title: r0.issuer, html: F.flow([{label: 'shares now', value: n0(r0.shares)}, {op: '−', label: 'shares last quarter', value: n0(r0.previous_shares)}, {op: '=', label: 'change', value: (r0.shares >= r0.previous_shares ? '+' : '') + n0(r0.shares - r0.previous_shares)}]) + `<p>${note}</p>`}]
      : [{title: 'Reading it', html: `<p>${note}</p>`}];
    F.help(card(k), {lead, sections: sec}); }
  const flags = D.flags || [];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${F.esc(f.code)}</b>${F.esc(f.message)}</li>`).join('') : '<li class="muted" style="border-color:var(--grid)">None</li>';
  g('notes').innerHTML = (D.notes || []).map(n => `<li>${F.esc(n)}</li>`).join('');
  const link = f => f && f.url ? `<a href="${F.esc(f.url)}" target="_blank" rel="noopener">${F.esc(f.accession)}</a> (quarter ended ${F.esc(f.report_date || '—')}, filed ${F.esc(f.filing_date || '—')})` : '—';
  setHtml('links', `Filings on EDGAR: current ${link(C)}${P ? ` · previous ${link(P)}` : ''} · CIK ${F.esc(M.cik ?? '—')}${M.alias ? ` · alias ${F.esc(M.alias)}` : ''} · as of ${F.esc(D.as_of || '—')}.`);
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render.py: {message}")


def _big(v: object) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "—"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    return f"{sign}${a:,.0f}"


def _count(result: dict, key: str) -> int:
    return len(result.get(key) or []) + int((result.get("truncated") or {}).get(key) or 0)


def _headline(result: dict) -> str:
    """Static one-line summary so the page reads without JavaScript."""
    m, c, p, t = result.get("manager") or {}, result.get("current") or {}, result.get("previous"), result.get("totals") or {}
    lag = f" ({result['lag_days']} days later)" if isinstance(result.get("lag_days"), int) else ""
    parts = [
        f"{m.get('name') or 'Manager'} (CIK {m.get('cik', '—')})",
        f"quarter ended {c.get('report_date') or '—'}, filed {c.get('filing_date') or '—'}{lag}",
        f"{_big(t.get('value'))} in {t.get('positions', '—')} positions",
    ]
    if p:
        chg = t.get("value_change_pct")
        chg_s = f"{chg:+.1f}%" if isinstance(chg, (int, float)) else "—"
        parts.append(f"{chg_s} vs the quarter ended {p.get('report_date') or '—'}")
    else:
        parts.append("no prior quarter in the index")
    parts.append(f"{_count(result, 'new')} new · {_count(result, 'exited')} exited · {_count(result, 'increased')} increased · {_count(result, 'trimmed')} trimmed · {result.get('unchanged', 0)} unchanged")
    return " · ".join(parts)


def build(result: dict) -> str:
    if not isinstance(result, dict) or "manager" not in result or "totals" not in result or "top" not in result:
        raise InvalidInput("input must be a holdings.py result (a JSON object with manager, totals and top)")
    body = BODY.replace("{{HEADLINE}}", html.escape(_headline(result)))
    return page.render(TITLE, result, body, SCRIPT)


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
            raise InvalidInput(f"could not read holdings JSON: {exc}") from exc
        out = page.write(ns.out, build(result))
        changes = sum(_count(result, k) for k in ("new", "exited", "increased", "trimmed"))
        return {"out": str(out), "title": TITLE, "manager": (result.get("manager") or {}).get("name"), "positions": (result.get("totals") or {}).get("positions"), "changes": changes, "flags": len(result.get("flags") or [])}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
