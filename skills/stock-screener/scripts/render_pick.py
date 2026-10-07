#!/usr/bin/env python3
"""Usage: render_pick.py [--in pick.json] --out page.html

Turns a deep-picker run into one self-contained HTML page for the Artifact tool. Input::

    {"as_of", "profile", "gate": <gate.py output>,
     "funnel": [{"stage", "count"}],
     "industries": [{"sector", "industry", "verdict": "favored"|"neutral"|"unfavored", "contrarian",
                     "temperature", "growth", "sentiment", "leaders": [{"ticker", "name", "trend"}],
                     "evidence": [{"claim", "source", "date"}]}],
     "candidates": [{"ticker", "name", "industry", "origin": "industry"|"screen"|"both", "held",
                     "scores": {"quality", "direction", "tailwind", "value"} (1-5),
                     "reasons": {...}, "missing", "bad_pick", "health", "finalist"}],
     "picks": {"SYMBOL": {"thesis", "bad_pick"}}, "missing_roles": [...], "notes": [...]}

Sections: Picks (each gate pass or pass_flagged result, with central and worst annual return, the
range of scenario values,
thesis, what would make it a bad pick, and a link to its deep valuation; a plain "none passed"
card otherwise), Near misses (each fail with its reasons), Funnel, Industry map (grouped favored,
contrarian, neutral, unfavored; rows open to growth, sentiment and dated evidence), Candidates
(highest total first; rows open to the reasons), Flags. Prints {"out", "title", "picks",
"near_misses", "industries", "candidates", "flags"}. Exit 2 on a missing gate, an unknown industry
verdict, a score outside 1-5, an evidence claim without a source or date, a picks entry that is
not a passing gate result, a funnel entry without a numeric count, a page link that is not https,
or any list holding something other than objects. Every figure comes from the scripts; nothing is fetched at runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from second_opinion import output, page  # noqa: E402
from second_opinion.errors import InvalidInput  # noqa: E402

VERDICTS = ("favored", "neutral", "unfavored")
SCORES = ("quality", "direction", "tailwind", "value")

BODY = """
<style>
.pickc{border:1px solid var(--grid);border-radius:8px;padding:12px 14px;margin:0 0 10px}
.pickc h3{margin:0 0 4px;font-size:16px}.pickc .r{font-variant-numeric:tabular-nums;font-size:13px;color:var(--muted)}
.pickc .t{margin:8px 0 4px;font-size:14px}.pickc .b{font-size:13px;color:var(--muted)}.pickc .w{font-size:13px;color:var(--warn);margin-top:6px}
.row{border-bottom:1px solid var(--grid);padding:8px 0}.row summary{cursor:pointer;display:flex;gap:10px;align-items:baseline;list-style:none}
.row summary::-webkit-details-marker{display:none}.row summary::after{content:'›';color:var(--muted);margin-left:10px;transition:transform .15s}.row[open] summary::after{transform:rotate(90deg)}
.row .n{font-weight:600}.row .m{color:var(--muted);font-size:12px;flex:1}.row .d{font-size:13px;margin-top:6px}.row ul{margin:6px 0 0;padding-left:18px;font-size:13px}
.lg{font-size:13px;margin:14px 0 2px}.lg.favored{color:var(--s1)}.lg.unfavored{color:var(--warn)}.lg.contrarian{color:var(--s3)}.lg.neutral{color:var(--muted)}
.src{color:var(--muted);font-size:12px}
.row .sc{display:flex;gap:8px;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}.row .sc b{color:var(--ink);min-width:20px;text-align:right}
</style>
<h1 id="h1">Deep picks</h1>
<p class="sub" id="sub"></p>
<div id="intro"></div>
<section class="card" id="picks-card"><h2>Picks</h2><p class="sub">Finalists whose deep valuation shows no scenario losing money over five years and a central case that clears the hurdle.</p><div id="picks"></div></section>
<section class="card" id="near-card"><h2>Near misses</h2><p class="sub">Finalists that were valued in depth but failed the downside gate, and why.</p><div id="near"></div></section>
<section class="card" id="funnel-card"><h2>Funnel</h2><p class="sub">How many companies were left after each stage of the search.</p><div id="funnel"></div></section>
<section class="card" id="ind-card"><h2>Industry map</h2><p class="sub">Each industry the scan covered, grouped by its verdict, with the leaders and the dated evidence behind the call.</p><div id="ind"></div></section>
<section class="card" id="cand-card"><h2>Candidates</h2><p class="sub">Every company in the merged pool, scored 1 to 5 on business quality (Q), direction (D), industry tailwind (T) and price against value (V).</p><div id="cand"></div></section>
<section data-help="none"><h2>Flags</h2>""" + page.FLAGS_INTRO + """<ul class="flags" id="flags"></ul></section>
<p class="note">Industry verdicts and candidate scores are judgement backed by dated evidence, not forecasts. A pick passed a downside test on stated assumptions; it is not a recommendation. General information at the stated assumptions, not financial, tax, or legal advice.</p>
"""

SCRIPT = r"""
(() => {
  const D = window.DATA, F = FA, G = D.gate, g = id => document.getElementById(id), esc = F.esc;
  const pct = v => F.isNum(v) ? F.pct(v, 1, true) : '—', money = v => F.isNum(v) ? F.money(v) : '—';
  const passes = G.results.filter(r => r.verdict !== 'fail'), fails = G.results.filter(r => r.verdict === 'fail');
  g('sub').textContent = `As of ${D.as_of}${D.profile ? ' · ' + D.profile : ''} · hurdle ${F.pct(G.hurdle, 1)} · floor ${F.pct(G.floor, 1)}`;
  F.intro(g('intro'), {lead: `${passes.length} of ${G.results.length} finalists passed the downside gate: no scenario loses money over five years, and the central case earns at least ${F.pct(G.hurdle, 1)} a year at today’s price.`});

  g('picks').innerHTML = passes.length ? passes.map(r => { const p = (D.picks || {})[r.symbol] || {};
    return `<div class="pickc"><h3>${esc(r.symbol)}</h3><div class="r"><b>Central value ${money(r.central.value_per_share)} vs price ${money(r.price)} · ${pct(r.central.irr)} a year</b><br>${esc(r.central.name)} case · worst ${esc(r.worst.name)} ${pct(r.worst.irr)}${r.value_range ? ` · value ${money(r.value_range[0])} – ${money(r.value_range[1])}` : ''}</div>
      ${p.thesis ? `<div class="t">${esc(p.thesis)}</div>` : ''}${p.bad_pick ? `<div class="b"><b>What would make this a bad pick:</b> ${esc(p.bad_pick)}</div>` : ''}
      ${r.verdict === 'pass_flagged' ? `<div class="w">${esc(r.reasons[r.reasons.length - 1])}</div>` : ''}
      ${r.page ? `<div class="b" style="margin-top:6px"><a href="${esc(r.page)}" target="_blank" rel="noopener">Deep valuation →</a></div>` : ''}</div>`; }).join('')
    : '<p><b>No finalist passed the downside gate.</b> The near misses below show which test each failed.</p>';
  F.help(g('picks-card'), {lead: 'The central case is the first scenario of the deep valuation; the scenarios are not averaged. A pick is a finalist whose deep valuation passed two tests at today’s price: no scenario loses money over five years, dividends included, and the central scenario earns at least the hurdle. A warning line means every scenario sits above the price, which can mean a downside case is missing.'});

  g('near').innerHTML = fails.length ? fails.map(r => `<details class="row"><summary><span class="n">${esc(r.symbol)}</span><span class="m">central ${money(r.central.value_per_share)} · ${pct(r.central.irr)} a year · worst ${r.worst ? pct(r.worst.irr) : '—'}</span></summary>
      <ul>${r.reasons.map(x => `<li>${esc(x)}</li>`).join('')}</ul>${r.page ? `<div class="d"><a href="${esc(r.page)}" target="_blank" rel="noopener">Deep valuation →</a></div>` : ''}</details>`).join('')
    : '<p class="muted">None: every finalist passed.</p>';
  F.help(g('near-card'), {lead: 'Finalists that were valued in depth and failed: a scenario that loses money, a central case below the hurdle, or a return that could not be computed.'});

  const fmax = Math.max(1, ...(D.funnel || []).map(s => s.count || 0));
  F.bars(g('funnel'), (D.funnel || []).map((s, i) => ({label: s.stage, share: (s.count || 0) / fmax, text: String(s.count), color: F.S[i % 8]})));
  F.help(g('funnel-card'), {lead: 'The search narrows in stages: industries scanned, screen survivors, the merged pool, the health check, quick reads, finalists and picks.'});

  const groups = [['favored', 'Favored', i => i.verdict === 'favored' && !i.contrarian], ['contrarian', 'Contrarian: out of favour, fundamentals improving', i => i.contrarian],
                  ['neutral', 'Neutral', i => i.verdict === 'neutral' && !i.contrarian], ['unfavored', 'Unfavored', i => i.verdict === 'unfavored' && !i.contrarian]];
  const ev = xs => (xs || []).map(x => `<li>${esc(x.claim)} <span class="src">${esc(x.source)}, ${esc(x.date)}</span></li>`).join('');
  g('ind').innerHTML = groups.map(([k, t, f]) => { const xs = (D.industries || []).filter(f); return xs.length ? `<h3 class="lg ${k}">${esc(t)} <span class="muted">(${xs.length})</span></h3>` + xs.map(i =>
    `<details class="row"><summary><span class="n">${esc(i.industry)}</span><span class="m">${esc(i.sector)} · ${esc(i.temperature)}</span></summary>
      <div class="d"><b>Leaders:</b> ${(i.leaders || []).map(l => `${esc(l.ticker)} (${esc(l.trend)})`).join(', ') || '—'}</div>
      <div class="d"><b>Growth:</b> ${esc(i.growth || '—')}</div><div class="d"><b>Sentiment:</b> ${esc(i.sentiment || '—')}</div><ul>${ev(i.evidence)}</ul></details>`).join('') : ''; }).join('');
  F.help(g('ind-card'), {lead: 'The industry scan’s call on each industry, from dated growth forecasts, cycle position, pricing power, policy, structural threats, sentiment and valuation against its own history. Contrarian industries are out of favour while their fundamentals improve.'});

  const label = {quality: 'Quality', direction: 'Direction', tailwind: 'Tailwind', value: 'Value'};
  const cands = (D.candidates || []).map(c => ({...c, total: SCORES.reduce((a, k) => a + (c.scores[k] || 0), 0)})).sort((a, b) => b.total - a.total || (b.finalist - a.finalist));
  g('cand').innerHTML = cands.map(c => `<details class="row"><summary><span class="n">${esc(c.ticker)}${c.finalist ? ' ★' : ''}</span><span class="m">${esc(c.industry)} · found by ${esc(c.origin)}${c.held ? ' · held' : ''}</span>
      <span class="sc">${SCORES.map(k => `<span title="${label[k]}">${label[k][0]}${c.scores[k]}</span>`).join('')}<b>${c.total}</b></span></summary>
      <ul>${SCORES.map(k => `<li><b>${label[k]} ${c.scores[k]}/5:</b> ${esc((c.reasons || {})[k] || '—')}</li>`).join('')}</ul>
      <div class="d"><b>What the market may be missing:</b> ${esc(c.missing || '—')}</div><div class="d"><b>What would make this a bad pick:</b> ${esc(c.bad_pick || '—')}</div>
      <div class="d muted">Health check: ${esc(c.health || '—')}</div></details>`).join('');
  F.help(g('cand-card'), {lead: 'Every company in the merged pool, highest total first. Each score runs 1 to 5 and comes from a quick read of the filings and dated news: Q quality of the business, D direction (improving or worsening), T industry tailwind, V price against value. ★ marks a finalist. Open a row for the reasons.'});

  const flags = [...(D.missing_roles || []).map(r => ({code: 'RESEARCH_MISSING', message: `The ${r} did not complete, so its findings are absent.`})), ...(D.notes || []).map(n => ({code: 'NOTE', message: n}))];
  g('flags').innerHTML = flags.length ? flags.map(f => `<li><b>${esc(f.code)}</b>${esc(f.message)}</li>`).join('') : '<li class="muted">None</li>';
})();
""".replace("SCORES", '["quality","direction","tailwind","value"]')


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise InvalidInput(f"render_pick.py: {message}")


def _list_of_dicts(v: object, what: str) -> list:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        raise InvalidInput(f"{what} must be a list of objects")
    return v


def _validate(data: dict) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("input must be a JSON object")
    gate = data.get("gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("results"), list):
        raise InvalidInput("gate (a gate.py result) is required")
    for r in _list_of_dicts(gate["results"], "gate.results"):
        link = r.get("page")
        if link is not None and not (isinstance(link, str) and link.lower().startswith("https://")):
            raise InvalidInput(f"gate result {r.get('symbol', '?')}: page must be an https:// link")
    for s in _list_of_dicts(data.get("funnel"), "funnel"):
        if not s.get("stage") or isinstance(s.get("count"), bool) or not isinstance(s.get("count"), (int, float)):
            raise InvalidInput("each funnel entry needs a stage and a numeric count")
    for i in _list_of_dicts(data.get("industries"), "industries"):
        name = i.get("industry", "?")
        if i.get("verdict") not in VERDICTS:
            raise InvalidInput(f"industry {name}: verdict must be one of {', '.join(VERDICTS)}")
        _list_of_dicts(i.get("leaders"), f"industry {name}: leaders")
        for e in _list_of_dicts(i.get("evidence"), f"industry {name}: evidence"):
            for f in ("claim", "source", "date"):
                if not e.get(f):
                    raise InvalidInput(f"industry {name}: an evidence claim has no {f}")
    for c in _list_of_dicts(data.get("candidates"), "candidates"):
        if not isinstance(c.get("scores"), dict):
            raise InvalidInput(f"candidate {c.get('ticker', '?')}: scores must be an object")
        for k in SCORES:
            v = c["scores"].get(k)
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5:
                raise InvalidInput(f"candidate {c.get('ticker', '?')}: score {k} must be a whole number from 1 to 5")
    picks = data.get("picks") or {}
    if not isinstance(picks, dict) or not all(isinstance(v, dict) for v in picks.values()):
        raise InvalidInput("picks must map each symbol to {thesis, bad_pick}")
    passing = {r["symbol"] for r in gate["results"] if r.get("verdict") in ("pass", "pass_flagged")}
    for sym in picks:
        if sym not in passing:
            raise InvalidInput(f"picks has {sym}, which did not pass the gate")


def build(data: dict) -> tuple[str, str, dict]:
    _validate(data)
    title = "Deep Picks"
    markup = page.render(title, data, BODY, SCRIPT)
    res = data["gate"]["results"]
    info = {"title": title, "picks": [r["symbol"] for r in res if r["verdict"] != "fail"],
            "near_misses": [r["symbol"] for r in res if r["verdict"] == "fail"],
            "industries": len(data.get("industries") or []), "candidates": len(data.get("candidates") or []),
            "flags": len(data.get("missing_roles") or []) + len(data.get("notes") or [])}
    return title, markup, info


def main(argv: list[str] | None = None) -> int:
    def go(args: list[str]) -> dict:
        p = _Parser(prog="render_pick.py", add_help=False)
        p.add_argument("--in", dest="inp", default=None)
        p.add_argument("--out", required=True)
        ns = p.parse_args(args)
        try:
            raw = Path(ns.inp).read_text(encoding="utf-8") if ns.inp else sys.stdin.read()
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"could not read the deep-picker JSON: {exc}") from exc
        _, markup, info = build(data)
        out = page.write(ns.out, markup)
        return {"out": str(out), **info}

    return output.run(go, argv)


if __name__ == "__main__":
    sys.exit(main())
