#!/usr/bin/env python3
"""Usage: render_review.py [--in page.json] --out page.html

Turns a portfolio deep review into one self-contained HTML page for the Artifact tool. Input::

    {"as_of", "headline" (25 words at most), "summary",
     "conclusions": [2 to 5 sentences, 40 words at most each], "exposure": <exposure.py output>,
     "missing_roles": [...], "notes": [...]}

The page reads top to bottom as one account. Stat tiles open it. "What this review did" says what question the
research asked and how. "What it found" gives the headline, the summary, the conclusions and the
same result in numbers. Then the evidence: Shared bets (largest first, each with a
plain-language reading; rows open to the holdings, income, evidence on both sides and what prices
show), Overlaps, Not yet mapped, What to watch, Flags. Every section opens with a sentence saying
what it holds and why it matters, and a "How to read this page" walkthrough steps through them.

Prints {"out", "title", "bets", "conclusions", "flags"}. Exit 2 on a missing headline, exposure or
conclusions, a headline or conclusion over its limit, or one of the verbs the compliance rules
forbid in the headline, summary, conclusions, notes or a bet's name or belief. Sourced claims keep
their own words. Every figure comes from exposure.py; nothing is fetched at runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402
from second_opinion.summary_card import FORBIDDEN_VERB_RE  # noqa: E402

HEADLINE_WORDS = 25
CONCLUSION_WORDS = 40
MIN_CONCLUSIONS, MAX_CONCLUSIONS = 2, 5

BODY = """
<style>
.lead{border:1px solid var(--grid);border-radius:8px;padding:14px 16px;margin:0 0 14px}
#about p{font-size:14px;margin:0 0 8px;max-width:76ch}h3.mini{font-size:12px;font-weight:600;color:var(--muted);margin:14px 0 4px}
ul.plain{margin:0;padding-left:18px;font-size:14px;max-width:76ch}ul.plain li{margin:3px 0}.sub.last{margin:14px 0 0}
.row .plainly{font-size:13px;margin-top:6px;color:var(--ink2)}
.lead .h{font-size:18px;font-weight:600;margin:0 0 6px}.lead .s{font-size:14px;color:var(--ink2);margin:0}
.row{border-bottom:1px solid var(--grid);padding:8px 0}.row summary{cursor:pointer;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;list-style:none}
.row summary::-webkit-details-marker{display:none}.row summary::after{content:'›';color:var(--muted);margin-left:auto;transition:transform .15s}.row[open] summary::after{transform:rotate(90deg)}
.row .n{font-weight:600}.row .m{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}.row .d{font-size:13px;margin-top:6px}
.row ul{margin:4px 0 0;padding-left:18px;font-size:13px}.row h4{font-size:12px;margin:12px 0 2px;color:var(--muted);font-weight:600}
.vd{font-size:11px;padding:1px 6px;border:1px solid var(--grid);border-radius:10px;color:var(--ink2)}.vd.weakening{color:var(--warn)}
.src{color:var(--muted);font-size:12px}.scroll{overflow-x:auto}
table.links{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}table.links th{text-align:left;font-weight:500;color:var(--muted);font-size:12px}
table.links td,table.links th{padding:3px 8px 3px 0;border-bottom:1px solid var(--grid);vertical-align:top;text-align:left;white-space:normal}table.links .r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
</style>
<h1 id="h1">Portfolio deep review</h1>
<p class="sub" id="sub"></p>
<div class="tiles" id="tiles"></div>
<section class="card" id="about-card" data-help="none"><h2>What this review did</h2><div id="about"></div><div id="intro"></div></section>
<section class="card" id="found-card" data-help="none"><h2>What it found</h2>
<div class="lead"><p class="h" id="headline"></p><p class="s" id="summary"></p></div>
<h3 class="mini">Conclusions</h3><ul class="plain" id="conclusions"></ul>
<h3 class="mini">The same result in numbers</h3><ul class="plain" id="numbers"></ul>
<p class="sub last">The sections below are the evidence for these conclusions, in the order to read them.</p></section>
<section class="card" id="bets-card"><h2>1. Shared bets</h2><p class="sub">Start here. Each row is one belief that several of your holdings rest on, largest first. It shows the dollars that depend on the belief and what an assumed shock would cost if it proved wrong. Bets overlap, so these losses do not add up. Open a row for the holdings and the evidence on both sides.</p><p class="sub" id="legend"></p><div id="bars"></div><div id="bets"></div></section>
<section class="card" id="over-card"><h2>2. Overlaps</h2><p class="sub">Holdings that rest on two bets at once. They matter because one holding can be hit twice if both beliefs fail.</p><div id="over"></div></section>
<section class="card" id="un-card"><h2>3. Not yet mapped</h2><p class="sub">Holdings of at least 1% of the portfolio that no bet covers. The review says nothing about them, so the conclusions above leave them out.</p><div id="un"></div></section>
<section class="card" id="watch-card"><h2>4. What to watch</h2><p class="sub">How you would find out a bet is breaking: the evidence to check and the result that would break it, earliest date first.</p><div id="watch"></div></section>
<section data-help="none" id="flags-section"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Shares and shocks are stated assumptions backed by dated evidence, not forecasts, and a bet is not a call to change a holding. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, X = D.exposure, T = X.totals, g = id => document.getElementById(id), esc = F.esc;
  const money = v => F.money(v, 0), pct = v => F.pct(v, 1), top = X.bets[0];
  const nameOf = id => (X.bets.find(b => b.id === id) || {}).name || id;
  const VERDICT = {holding: 'the evidence supports the belief', contested: 'there is serious evidence on both sides', weakening: 'recent evidence runs against the belief', open: 'nothing available can settle it yet'};
  const n = X.bets.length, bets = k => `${k} ${k === 1 ? 'bet' : 'bets'}`, links = new Set(X.bets.flatMap(b => b.links.map(l => l.symbol))).size;
  g('about').innerHTML = `<p>This review asked one question: which beliefs do several of your holdings share, so that one thing going wrong would hit them together? Research subagents read company filings, fund holdings and economic data for the portfolio as of ${esc(D.as_of)}${T.income_included ? ', and for the income you named' : ''}.</p>`
    + `<p>They found ${bets(n)} across ${links} ${links === 1 ? 'holding' : 'holdings'}. A bet is a belief that could prove wrong, for example: “${esc(top.belief)}”. For each bet the page shows the dollars that rest on it, what an assumed shock would cost, and the dated evidence for and against.</p>`
    + `<p>The review describes what the holdings depend on. It does not say what to do about it.</p>`;
  F.intro(g('intro'), {lead: 'Read “What it found” first. The numbered sections after it are the evidence.', steps: [
    {target: '#tiles', title: 'Four figures', html: '<p>The size of the largest bet, the share of the portfolio resting on it, how much of the invested money the review covers, and how many bets share a holding.</p>'},
    {target: '#found-card', title: 'What it found', html: '<p>The headline and summary name the belief that carries the most money. The conclusions are the research’s reading of all the bets together. The numbers under them come straight from the calculation.</p>'},
    {target: '#bets-card', title: '1. Shared bets', html: '<p>One row per belief, largest first. “Exposed” is the money that depends on the belief. “If wrong” is that money times an assumed shock. The label on each row says where the evidence stands. Open a row to see the holdings and the sources.</p>'},
    {target: '#over-card', title: '2. Overlaps', html: '<p>Two bets can share a holding. That is why the losses in section 1 are never added together.</p>'},
    {target: '#un-card', title: '3. Not yet mapped', html: '<p>The holdings the review could not tie to any shared bet. Nothing above describes them.</p>'},
    {target: '#watch-card', title: '4. What to watch', html: '<p>For each bet, the evidence to check, the date to check it by, and the result that would break the bet.</p>'},
    {target: '#flags-section', title: 'Flags', html: '<p>Where the review rests on thin, old or one-sided evidence, or where a research role did not finish.</p>'}]});
  g('conclusions').innerHTML = (D.conclusions || []).map(c => `<li>${esc(c)}</li>`).join('');
  const counts = Object.keys(VERDICT).map(v => [v, X.bets.filter(b => b.verdict === v).length]).filter(c => c[1]);
  const due = X.bets.flatMap(b => b.watch.map(w => ({...w, bet: b.name}))).sort((a, b) => a.check_by < b.check_by ? -1 : 1)[0];
  g('numbers').innerHTML = [
    `The largest bet is “${esc(top.name)}”. ${money(top.exposed_value)} of the portfolio (${pct(top.exposed_pct)}) rests on it. If it proves wrong, the assumed shocks put ${money(top.at_stake)} at stake${top.income_at_risk ? `, including ${money(top.income_at_risk)} of one year’s income` : ''}.`,
    `Where the evidence stands: ${counts.map(c => `for ${bets(c[1])}, ${VERDICT[c[0]]} (${c[0]})`).join('; ')}.`,
    T.coverage === null ? null : `${pct(T.coverage)} of invested value rests on at least one bet. ${X.unmapped.length ? `${X.unmapped.length} larger ${X.unmapped.length === 1 ? 'holding rests' : 'holdings rest'} on none (section 3).` : 'Every holding of at least 1% is covered.'}`,
    X.overlaps.length ? `${X.overlaps.length} ${X.overlaps.length === 1 ? 'pair of bets shares' : 'pairs of bets share'} a holding, so the bets’ losses do not add up (section 2).` : n > 1 ? 'No holding rests on two bets, but the bets’ losses still do not add up to a forecast.' : null,
    due ? `The next check is “${esc(due.what)}” by ${esc(due.check_by)}, for the bet “${esc(due.bet)}” (section 4).` : null,
  ].filter(Boolean).map(t => `<li>${t}</li>`).join('');
  g('legend').innerHTML = 'The label on each row: ' + Object.entries(VERDICT).map(([k, v]) => `<span class="vd ${k}">${k}</span> ${v}`).join(' · ') + '.';
  const plainly = b => `<div class="plainly"><b>In plain terms:</b> ${money(b.exposed_value)} of your holdings (${pct(b.exposed_pct)} of the portfolio) depends on this belief. If it proves wrong, the assumed shocks put ${money(b.at_stake)} at stake${b.income_at_risk ? `, including ${money(b.income_at_risk)} of one year’s income` : ''}. Right now ${VERDICT[b.verdict] || esc(b.verdict)}.</div>`;
  g('sub').textContent = `As of ${D.as_of} · ${X.bets.length} shared ${X.bets.length === 1 ? 'bet' : 'bets'}${T.income_included ? ' · income included' : ' · holdings only, no income given'}`;
  g('headline').textContent = D.headline;
  g('summary').textContent = D.summary || '';

  const tile = (k, v, d) => `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="d">${esc(d)}</div></div>`;
  g('tiles').innerHTML = [
    tile('Largest bet', money(top.at_stake), `at stake if “${top.name}” is wrong`),
    tile('Resting on it', pct(top.exposed_pct), `${money(top.exposed_value)} of ${money(T.total_value)}`),
    tile('On some bet', T.coverage === null ? '—' : pct(T.coverage), 'of invested value, without cash-like funds'),
    tile('Overlaps', String(X.overlaps.length), 'pairs of bets that share a holding'),
  ].join('');

  const most = Math.max(1, ...X.bets.map(b => b.at_stake));
  F.bars(g('bars'), X.bets.map((b, i) => ({label: b.name, share: b.at_stake / most, text: money(b.at_stake), color: F.S[i % 8]})));
  const claims = xs => xs.length ? `<ul>${xs.map(c => `<li>${esc(c.claim)} <span class="src">${esc(c.source)}, ${esc(c.date)}</span></li>`).join('')}</ul>` : '<div class="d muted">None found.</div>';
  const seen = h => !h ? 'Not enough price history to say.' : h.reading === 'moves_together'
    ? `These holdings have moved together more than the portfolio has (average correlation ${F.num(h.avg_correlation)} against ${F.num(h.portfolio_avg_correlation)}), so prices already show this bet.`
    : `These holdings have moved together no more than the portfolio has (average correlation ${F.num(h.avg_correlation)} against ${F.num(h.portfolio_avg_correlation)}), so correlations would not show this bet.`;
  const holdings = b => b.links.length ? `<h4>Holdings</h4><div class="scroll"><table class="links"><tr><th>Holding</th><th class="r">Share</th><th class="r">Exposed</th><th class="r">Shock</th><th class="r">If wrong</th><th>Why</th></tr>${b.links.map(l =>
    `<tr><td>${esc(l.symbol)}</td><td class="r">${F.pct(l.share, 0)}</td><td class="r">${money(l.exposed_value)}</td><td class="r">${F.pct(l.shock, 0, true)}</td><td class="r">${money(l.loss_if_wrong)}</td><td>${esc(l.why)} <span class="src">${esc(l.source)}, ${esc(l.date)}</span></td></tr>`).join('')}</table></div>` : '';
  const income = b => b.income_links.length ? `<h4>Income</h4><ul>${b.income_links.map(l => `<li>${esc(l.name)}: ${money(l.income_at_risk)} of one year at risk. ${esc(l.why)} <span class="src">${esc(l.source)}, ${esc(l.date)}</span></li>`).join('')}</ul>` : '';
  g('bets').innerHTML = X.bets.map(b => `<details class="row"${b.id === X.largest ? ' open' : ''}><summary><span class="n">${esc(b.name)}</span><span class="vd ${esc(b.verdict)}">${esc(b.verdict)}</span>
      <span class="m">${money(b.exposed_value)} exposed · ${money(b.loss_if_wrong)} if wrong${b.income_at_risk ? ` · ${money(b.income_at_risk)} of income` : ''}</span></summary>
      <div class="d"><b>The belief:</b> ${esc(b.belief)}</div>${plainly(b)}${holdings(b)}${income(b)}
      <h4>Evidence for</h4>${claims(b.for)}<h4>Evidence against</h4>${claims(b.against)}
      <h4>What prices show</h4><div class="d">${esc(seen(b.history))}</div></details>`).join('');
  F.help(g('bets-card'), {lead: 'A holding’s exposed value is its market value times the share that depends on the belief. If wrong is the exposed value times the assumed shock. At stake adds one year of any income at risk. Shares and shocks are stated assumptions with a source behind each.'});

  g('over').innerHTML = X.overlaps.length ? X.overlaps.map(o => `<div class="row"><span class="n">${esc(nameOf(o.a))}</span> and <span class="n">${esc(nameOf(o.b))}</span> <span class="m">share ${money(o.shared_value)} through ${esc(o.symbols.join(', '))}</span></div>`).join('') : '<p class="muted">None: no holding rests on two bets.</p>';
  F.help(g('over-card'), {lead: 'The shared value sums the smaller exposure of each holding the two bets have in common. If both beliefs fail, that money is hit by both.'});
  g('un').innerHTML = X.unmapped.length ? X.unmapped.map(u => `<div class="row"><span class="n">${esc(u.symbol)}</span> <span class="m">${money(u.value)} · ${pct(u.weight)} of the portfolio</span></div>`).join('') : '<p class="muted">None: every holding of at least 1% is covered.</p>';
  if (X.small_unmapped && X.small_unmapped.count) g('un').insertAdjacentHTML('beforeend', `<p class="muted" style="font-size:13px">Plus ${X.small_unmapped.count} smaller ${X.small_unmapped.count === 1 ? 'holding' : 'holdings'} worth ${money(X.small_unmapped.value)} in all.</p>`);
  F.help(g('un-card'), {lead: 'Being here means the research tied the holding to no shared bet. It does not mean the holding carries no risk.'});

  const watch = X.bets.flatMap(b => b.watch.map(w => ({...w, bet: b.name}))).sort((a, b) => a.check_by < b.check_by ? -1 : 1);
  g('watch').innerHTML = watch.length ? watch.map(w => `<div class="row"><span class="n">${esc(w.what)}</span> <span class="m">by ${esc(w.check_by)} · ${esc(w.bet)}</span><div class="d">Breaks if: ${esc(w.breaks_if)}</div></div>`).join('') : '<p class="muted">None.</p>';
  F.help(g('watch-card'), {lead: 'Each item names evidence to check by a date and what result would break the bet. A later check lists the items that have come due.'});

  const flags = [...X.flags, ...(D.missing_roles || []).map(r => ({code: 'RESEARCH_MISSING', message: `The ${r} did not complete, so its findings are absent.`})), ...(D.notes || []).map(n => ({code: 'NOTE', message: n}))];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${esc(f.code)}</b>${esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render_review.py: {message}")


def _no_advice(text: object, what: str) -> None:
    found = FORBIDDEN_VERB_RE.search(text) if isinstance(text, str) else None
    if found:
        raise InvalidInput(f"{what} uses the forbidden word {found.group(0)!r}")


def _validate(data: object) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a JSON object")
    x = data.get("exposure")
    if not isinstance(x, dict) or not x.get("bets") or not isinstance(x.get("totals"), dict):
        raise InvalidInput("exposure (an exposure.py result) is required")
    headline = data.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        raise InvalidInput("headline is required")
    words = len(headline.split())
    if words > HEADLINE_WORDS:
        raise InvalidInput(f"headline is {words} words; the limit is {HEADLINE_WORDS} words")
    _no_advice(headline, "headline")
    _no_advice(data.get("summary"), "summary")
    conclusions = data.get("conclusions")
    if not isinstance(conclusions, list) or not MIN_CONCLUSIONS <= len(conclusions) <= MAX_CONCLUSIONS:
        raise InvalidInput(f"conclusions is required: {MIN_CONCLUSIONS} to {MAX_CONCLUSIONS} sentences saying what the review found")
    for i, line in enumerate(conclusions, start=1):
        if not isinstance(line, str) or not line.strip():
            raise InvalidInput(f"conclusion {i} is empty")
        words = len(line.split())
        if words > CONCLUSION_WORDS:
            raise InvalidInput(f"conclusion {i} is {words} words; the limit is {CONCLUSION_WORDS} words")
        _no_advice(line, f"conclusion {i}")
    for note in data.get("notes") or []:
        _no_advice(note, "a note")
    for bet in x["bets"]:
        _no_advice(bet.get("name"), f"bet {bet.get('id')} name")
        _no_advice(bet.get("belief"), f"bet {bet.get('id')} belief")


def build(data: dict) -> tuple[str, str, dict]:
    _validate(data)
    title = "Portfolio Deep Review"
    markup = page.render(title, data, BODY, SCRIPT)
    x = data["exposure"]
    return title, markup, {"title": title, "bets": len(x["bets"]), "conclusions": len(data["conclusions"]),
                           "flags": len(x.get("flags") or []) + len(data.get("missing_roles") or []) + len(data.get("notes") or [])}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render_review.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read the review JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
