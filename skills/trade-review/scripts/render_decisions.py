#!/usr/bin/env python3
"""Usage: render_decisions.py [--in page.json] --out page.html

Turns a trade-review deep review into one self-contained HTML page for the Artifact tool. Input::

    {"as_of", "headline" (25 words at most), "summary", "review": <decisions.py output>,
     "missing_roles": [...], "notes": [...]}

Sections: the headline, stat tiles, Skill or luck (grade against result), Decisions (largest first;
rows open to what was known then, kept apart from what came out later), Patterns, Flags. Prints
{"out", "title", "decisions", "flags"}. Exit 2 on a missing headline or review, a headline over the
limit, or one of the verbs the compliance rules forbid in the headline, summary, notes or a grade's
reason. Sourced claims keep their own words. Every figure comes from decisions.py; nothing is
fetched at runtime.
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

BODY = """
<style>
.lead{border:1px solid var(--grid);border-radius:8px;padding:14px 16px;margin:0 0 20px}
.lead .h{font-size:18px;font-weight:600;margin:0 0 6px}.lead .s{font-size:14px;color:var(--ink2);margin:0}
.grid22{display:grid;grid-template-columns:90px 1fr 1fr;gap:8px;font-size:13px;align-items:stretch}.grid22 .hd{color:var(--muted);font-size:12px;align-self:end}
.cellb{border:1px solid var(--grid);border-radius:6px;padding:10px 12px}.cellb .n{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}.cellb .l{color:var(--ink2)}
.row{border-bottom:1px solid var(--grid);padding:8px 0}.row summary{cursor:pointer;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;list-style:none}
.row summary::-webkit-details-marker{display:none}.row summary::after{content:'›';color:var(--muted);margin-left:auto;transition:transform .15s}.row[open] summary::after{transform:rotate(90deg)}
.row .n2{font-weight:600}.row .m{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}.row .d{font-size:13px;margin-top:6px}
.row ul{margin:4px 0 0;padding-left:18px;font-size:13px}.row h4{font-size:12px;margin:12px 0 2px;color:var(--muted);font-weight:600}
.chip2{font-size:11px;padding:1px 6px;border:1px solid var(--grid);border-radius:10px;color:var(--ink2);white-space:nowrap}.chip2.mistake{color:var(--warn);border-color:var(--warn)}
.src{color:var(--muted);font-size:12px}.scroll{overflow-x:auto}
table.t{width:100%;border-collapse:collapse;font-size:13px}table.t th{font-weight:500;color:var(--muted);font-size:12px}
table.t td,table.t th{padding:4px 10px 4px 0;border-bottom:1px solid var(--grid);vertical-align:top;text-align:left;white-space:normal}table.t .r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
</style>
<h1>Decision review</h1>
<p class="sub" id="sub"></p>
<div class="lead"><p class="h" id="headline"></p><p class="s" id="summary"></p></div>
<div class="tiles" id="tiles"></div>
<section class="card" id="cell-card"><h2>Skill or luck</h2><p class="sub">Each decision's grade, made without seeing its result, set against how it turned out.</p><div class="grid22" id="cells"></div><p class="src" id="unclear" style="margin-top:8px"></p></section>
<section class="card" id="dec-card"><h2>Decisions</h2><p class="sub">The largest by money moved, chosen without looking at results. Open a row for what was known at the time.</p><div id="dec"></div></section>
<section class="card" id="pat-card"><h2>Patterns</h2><p class="sub" id="pat-sub"></p><div class="scroll" id="pat"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Grades rest on public evidence, not on what you knew or intended at the time, and they describe past decisions, not what to do next. General information, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, R = D.review, g = id => document.getElementById(id), esc = F.esc;
  const money = v => F.isNum(v) ? F.money(v, 0) : '—', pct = v => F.isNum(v) ? F.pct(v, 1, true) : '—', C = R.cells, rows = R.decisions;
  const CELL = {skill: 'Skill', luck: 'Luck', bad_luck: 'Bad luck', mistake: 'Mistake', unclear: 'Unclear'};
  const scored = rows.filter(r => F.isNum(r.outcome.score)).length;
  g('sub').textContent = `As of ${D.as_of} · ${rows.length} decisions · ${scored} with a result`;
  g('headline').textContent = D.headline; g('summary').textContent = D.summary || '';
  const tile = (k, v, d) => `<div class="tile"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="d">${esc(d)}</div></div>`;
  const gap = R.patterns.process_gap;
  g('tiles').innerHTML = [
    tile('Sound decisions', String(rows.filter(r => r.quality === 'sound').length), 'graded blind, on what was public then'),
    tile('Weak decisions', String(rows.filter(r => r.quality === 'weak').length), 'graded blind, on what was public then'),
    tile('Lucky or unlucky', String(C.luck + C.bad_luck), 'result ran against the grade'),
    tile('Process gap', F.isNum(gap) ? pct(gap) : '—', F.isNum(gap) ? 'average result, sound less weak' : 'needs three sound and three weak'),
  ].join('');

  const box = (k, t) => `<div class="cellb"><div class="n">${C[k]}</div><div class="l">${esc(t)}</div></div>`;
  g('cells').innerHTML = `<div></div><div class="hd">Good result</div><div class="hd">Bad result</div><div class="hd">Sound</div>${box('skill', 'Skill')}${box('bad_luck', 'Bad luck')}<div class="hd">Weak</div>${box('luck', 'Luck')}${box('mistake', 'Mistake')}`;
  g('unclear').textContent = C.unclear ? `${C.unclear} more ${C.unclear === 1 ? 'is' : 'are'} unclear: a mixed or unknown grade, a flat result, or too soon to tell.` : '';
  F.help(g('cell-card'), {lead: 'A grader saw only the evidence dated by each decision, with no result. A good result is a sale followed by the stock lagging the benchmark by 5% or more over 90 days, or a buy up 5% or more. A bad result is the reverse. Few decisions can land in a box by chance.'});

  const claims = xs => `<ul>${xs.map(c => `<li>${esc(c.claim)} <span class="src">${esc(c.source)}, ${esc(c.date)}</span></li>`).join('')}</ul>`;
  const side = (r, cut, t) => { const xs = r.known.filter(c => c.cut === cut); return `<h4>${t}</h4>${xs.length ? claims(xs) : '<div class="d muted">None found.</div>'}`; };
  g('dec').innerHTML = rows.map(r => `<details class="row"><summary><span class="n2">${esc(r.action === 'sell' ? 'Sold' : 'Bought')} ${esc(r.symbol)}</span><span class="m">${esc(r.date)} · ${money(r.outcome.amount)}</span><span class="chip2">${esc(r.quality)}</span><span class="chip2 ${esc(r.cell)}">${esc(CELL[r.cell])}</span><span class="m">${esc(r.outcome.verdict.replace('_', ' '))}${F.isNum(r.outcome.measure) ? ' · ' + pct(r.outcome.measure) : ''}</span></summary>
      <div class="d"><b>Why this grade:</b> ${esc(r.grade_reason)}</div>${r.stated_reason ? `<div class="d"><b>Your stated reason:</b> ${esc(r.stated_reason)}</div>` : ''}
      ${side(r, 'for', 'Known then, in favor of the decision')}${side(r, 'against', 'Known then, against it')}
      <h4>The result</h4><div class="d">${esc(r.outcome.basis)}: ${pct(r.outcome.measure)}. Profit or loss ${money(r.outcome.total_pnl)}.</div>
      ${r.later.length ? `<h4>What came out later</h4>${claims(r.later)}<div class="d muted">Not used in the grade.</div>` : ''}</details>`).join('');
  F.help(g('dec-card'), {lead: 'Claims are split by date. Only what was public by the day of the decision counts as known. What came out later is shown apart and played no part in the grade.'});

  const P = R.patterns, names = {by_quality: 'By grade', by_catalyst: 'By what was happening', by_action: 'By kind of decision'};
  g('pat-sub').textContent = 'Average result in each group. A positive score means the decision worked. Thin means fewer than three decisions, too few to read anything into.';
  g('pat').innerHTML = Object.keys(names).map(k => P[k].length ? `<h3 style="font-size:13px;margin:10px 0 2px">${names[k]}</h3><table class="t"><tr><th>Group</th><th class="r">Decisions</th><th class="r">Average score</th><th class="r">Worked</th><th></th></tr>${P[k].map(x => `<tr><td>${esc(x.group.replace('_', ' '))}</td><td class="r">${x.n}</td><td class="r">${pct(x.avg_score)}</td><td class="r">${F.pct(x.hit_rate, 0)}</td><td>${x.thin ? '<span class="chip2">thin</span>' : ''}</td></tr>`).join('')}</table>` : '').join('') || '<p class="muted">No decision has a result yet.</p>';
  F.help(g('pat-card'), {lead: 'If grades carry information, sound decisions earn more than weak ones over enough decisions. The process gap measures that once there are three of each. A small gap across a few trades says little either way.'});

  const flags = [...R.flags, ...(D.missing_roles || []).map(r => ({code: 'RESEARCH_MISSING', message: `The ${r} role did not complete, so its findings are absent.`})), ...(D.notes || []).map(n => ({code: 'NOTE', message: n}))];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${esc(f.code)}</b>${esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render_decisions.py: {message}")


def _no_advice(text: object, what: str) -> None:
    found = FORBIDDEN_VERB_RE.search(text) if isinstance(text, str) else None
    if found:
        raise InvalidInput(f"{what} uses the forbidden word {found.group(0)!r}")


def _validate(data: object) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a JSON object")
    review = data.get("review")
    if not isinstance(review, dict) or not review.get("decisions") or not isinstance(review.get("cells"), dict):
        raise InvalidInput("review (a decisions.py result) is required")
    headline = data.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        raise InvalidInput("headline is required")
    words = len(headline.split())
    if words > HEADLINE_WORDS:
        raise InvalidInput(f"headline is {words} words; the limit is {HEADLINE_WORDS} words")
    _no_advice(headline, "headline")
    _no_advice(data.get("summary"), "summary")
    for note in data.get("notes") or []:
        _no_advice(note, "a note")
    for d in review["decisions"]:
        _no_advice(d.get("grade_reason"), f"decision {d.get('id')} grade_reason")


def build(data: dict) -> tuple[str, str, dict]:
    _validate(data)
    title = "Decision Review"
    markup = page.render(title, data, BODY, SCRIPT)
    review = data["review"]
    return title, markup, {"title": title, "decisions": len(review["decisions"]),
                           "flags": len(review.get("flags") or []) + len(data.get("missing_roles") or []) + len(data.get("notes") or [])}


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render_decisions.py", add_help=False)
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
