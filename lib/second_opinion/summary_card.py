"""The headline analysis card at the top of a summary page.

The model writes the text after reading the script results; this module holds it to the rules and
turns it into HTML. Its length is enforced here so the card cannot grow into a report. Nothing here
writes prose or checks the numbers in it: formatting and rounding make that check brittle, so the
skill instructions carry the rule that every number comes from the run's output.

Summary file: ``{"headline", "stands_out", "look_into", "for_you"?}``. The first three are non-empty
strings. Links take the form ``[label](section-id)``, in ``look_into`` only, and the page declares
which ids exist.

``for_you`` is the one part that goes deep, because it sits folded: a list of one to five
``{"topic", "text"}`` points, each topic a short label and each text its own paragraph. A plain
string is still read as one unlabelled paragraph.

``chart`` is optional: the name of one chart the page draws beside the text. A page declares
which charts it offers by passing ``charts`` to ``load``; a page that passes none rejects the key,
and a card with no chart is text alone. ``chart_note`` is optional and needs ``chart``: one short line,
written by the model, saying why this chart shows the headline's point. ``CHART_CSS`` and ``CHART_JS`` are the shared pieces a page
adds when the card names one: the layout, diverging bars (``SC.rows``), markers on a scale
(``SC.marks``) and ``SC.mount``, which draws the named chart or removes the figure when its data is
missing. The page supplies the chart definitions, so each chart reads only that page's data.
"""
from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from second_opinion import config
from second_opinion.errors import InvalidInput

# The verbs the compliance block bans for financial actions. Stems, so "recommends",
# "recommendation", "adviser" and "suggesting" are caught too. tests/test_skills_structure.py runs
# the same pattern over the reference files.
FORBIDDEN_VERB_RE = re.compile(r"\b(recommend\w*|advis\w*|should|suggest\w*)\b", re.IGNORECASE)

HEADLINE_WORDS = 20
PARAGRAPH_WORDS = 90
FOR_YOU_WORDS = 70  # per paragraph: the plain string, or each point's text
FOR_YOU_POINTS = 5
FOR_YOU_TOPIC_WORDS = 4
CHART_NOTE_WORDS = 25
WORD_LIMITS = {
    "headline": HEADLINE_WORDS,
    "chart_note": CHART_NOTE_WORDS,
    "stands_out": PARAGRAPH_WORDS,
    "look_into": PARAGRAPH_WORDS,
    "for_you": FOR_YOU_WORDS,
}
REQUIRED = ("headline", "stands_out", "look_into")

# Any target at all, so a mistyped one is rejected rather than printed as literal brackets.
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")


def _check_field(field: str, value: object, targets: set[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"summary {field} must be a non-empty string")
    links = list(_LINK_RE.finditer(value))
    if links and field != "look_into":
        raise InvalidInput(f"summary {field} cannot hold links; only look_into can")
    for link in links:
        if link.group(2) not in targets:
            raise InvalidInput(
                f"summary look_into links to {link.group(2)!r}, which is not a section on this page: "
                f"{', '.join(sorted(targets))}"
            )
    words = len(_LINK_RE.sub(r"\1", value).split())
    if words > WORD_LIMITS[field]:
        raise InvalidInput(f"summary {field} is {words} words; the limit is {WORD_LIMITS[field]}")
    found = FORBIDDEN_VERB_RE.search(value)
    if found:
        raise InvalidInput(f"summary {field} uses the forbidden word {found.group(0)!r}")


def _check_for_you(value: object, targets: set[str]) -> None:
    """A plain paragraph, or one to five {"topic", "text"} points held to the same rules each."""
    if isinstance(value, str):
        _check_field("for_you", value, targets)
        return
    if not isinstance(value, list) or not value:
        raise InvalidInput('summary for_you must be a non-empty string or a list of {"topic", "text"} points')
    if len(value) > FOR_YOU_POINTS:
        raise InvalidInput(f"summary for_you has {len(value)} points; the limit is {FOR_YOU_POINTS}")
    for i, point in enumerate(value):
        if not isinstance(point, dict) or set(point) != {"topic", "text"}:
            raise InvalidInput(f'summary for_you[{i}] must be an object with exactly "topic" and "text"')
        topic = point["topic"]
        if not isinstance(topic, str) or not topic.strip():
            raise InvalidInput(f"summary for_you[{i}] topic must be a non-empty string")
        if len(topic.split()) > FOR_YOU_TOPIC_WORDS:
            raise InvalidInput(f"summary for_you[{i}] topic is over {FOR_YOU_TOPIC_WORDS} words")
        if _LINK_RE.search(topic) or FORBIDDEN_VERB_RE.search(topic):
            raise InvalidInput(f"summary for_you[{i}] topic cannot hold a link or a forbidden word")
        try:
            _check_field("for_you", point["text"], targets)
        except InvalidInput as exc:
            raise InvalidInput(str(exc).replace("summary for_you", f"summary for_you[{i}] text", 1)) from exc


def load(path: str, targets: Iterable[str], charts: Iterable[str] = ()) -> dict:
    """Read and validate a summary file. Raises InvalidInput naming the rule it breaks."""
    try:
        summary = json.loads(Path(path).read_text())
    except OSError as exc:
        raise InvalidInput(f"cannot read summary file {path}: {exc}") from exc
    except ValueError as exc:
        raise InvalidInput(f"summary file {path} is not valid JSON: {exc}") from exc
    if not isinstance(summary, dict):
        raise InvalidInput(f"summary file {path} must hold a JSON object")
    offered = sorted(set(charts))
    if "chart" in summary:
        if not offered:
            raise InvalidInput("summary chart is not offered on this page")
        if summary["chart"] not in offered:
            raise InvalidInput(f"summary chart {summary['chart']!r} is not one of: {', '.join(offered)}")
    if "chart_note" in summary and "chart" not in summary:
        raise InvalidInput("summary chart_note needs a chart")
    unknown = sorted(set(summary) - set(WORD_LIMITS) - {"chart"})
    if unknown:
        raise InvalidInput(f"summary has unknown keys: {', '.join(unknown)}")
    for field in REQUIRED:
        if field not in summary:
            raise InvalidInput(f"summary is missing {field}")
    allowed = set(targets)
    for field, value in summary.items():
        if field == "chart":
            continue
        if field == "for_you":
            _check_for_you(value, allowed)
        else:
            _check_field(field, value, allowed)
    return summary


def _with_links(text: str) -> str:
    """Escape everything, turning each link into a scroll target with no hash change."""
    parts: list[str] = []
    end = 0
    for link in _LINK_RE.finditer(text):
        parts.append(html.escape(text[end : link.start()]))
        parts.append(
            '<a class="summary-link" role="button" tabindex="0" '
            f'data-summary-target="{html.escape(link.group(2), quote=True)}">{html.escape(link.group(1))}</a>'
        )
        end = link.end()
    parts.append(html.escape(text[end:]))
    return "".join(parts)


def _for_you_html(for_you: object) -> str:
    if isinstance(for_you, str):
        return f"<p>{html.escape(for_you)}</p>"
    return "".join(
        f'<p><span class="summary-label">{html.escape(point["topic"])}</span>{html.escape(point["text"])}</p>'
        for point in for_you
    )


def card_html(summary: dict | None) -> str:
    """The card, or an empty string when there is no summary."""
    if summary is None:
        return ""
    for_you = summary.get("for_you")
    fold = (
        '<details class="summary-fold"><summary>What this means for you</summary>'
        f"{_for_you_html(for_you)}</details>"
        if for_you
        else ""
    )
    text = (
        f'<p class="summary-head">{html.escape(summary["headline"])}</p>'
        f'<p><span class="summary-label">What stands out</span>{html.escape(summary["stands_out"])}</p>'
        f'<p><span class="summary-label">What to look into</span>{_with_links(summary["look_into"])}</p>'
        f"{fold}"
    )
    chart = summary.get("chart")
    if chart:
        text = (
            f'<div class="sum-grid"><div class="sum-text">{text}</div>'
            f'<figure class="sum-chart" id="sum-chart" data-chart="{html.escape(chart, quote=True)}">'
            '<figcaption class="sc-title" id="sc-title"></figcaption>'
            + (f'<p class="sc-why">{html.escape(summary["chart_note"])}</p>' if summary.get("chart_note") else "")
            + '<div id="sc-body"></div><p class="sc-lead" id="sc-lead" hidden></p>'
            '<p class="sc-note" id="sc-note"></p></figure></div>'
        )
    return f'<section class="card summary-card" data-help="none" id="summary-card">{text}</section>'



def full_read_today(now: datetime | None = None) -> bool:
    """True when portfolio-last-check.json shows a full read on today's local date. False when in doubt."""
    try:
        record = json.loads((config.data_dir() / "portfolio-last-check.json").read_text())
        if record["partial"] is not False:
            return False
        read_at = datetime.fromisoformat(record["as_of"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return read_at.astimezone().date() == (now or datetime.now()).astimezone().date()


CHART_CSS = """<style>
.summary-card .sum-grid{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:28px;align-items:start}
@media (max-width:900px){.summary-card .sum-grid{grid-template-columns:1fr}}
.sum-chart{margin:0;padding:14px 16px;border:1px solid var(--ring);border-radius:6px}
.sc-title{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin-bottom:10px;font-weight:600}
.summary-card .sum-chart .sc-note{font-size:12px;color:var(--muted);margin:10px 0 0}
.summary-card .sum-chart .sc-why{font-size:12.5px;color:var(--ink2);margin:-4px 0 10px}
.summary-card .sum-chart .sc-lead{font-size:12.5px;color:var(--ink);margin:10px 0 0}
.sc-row{display:grid;grid-template-columns:72px minmax(0,1fr) 76px;align-items:center;gap:8px;font-size:12.5px;margin:5px 0;color:var(--ink2)}
.sc-row.mk{grid-template-columns:72px minmax(0,1fr) 96px}
.sc-row .val{white-space:nowrap}
.sc-row .lab{color:var(--ink);font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sc-row .val{text-align:right;font-variant-numeric:tabular-nums}
.sc-track{position:relative;height:14px}
.sc-axis{position:absolute;top:-3px;bottom:-3px;width:1px;background:var(--ring)}
.sc-bar{position:absolute;top:0;height:14px;border-radius:2px}
.sc-rail{position:absolute;top:6px;height:2px;left:0;right:0;background:var(--grid)}
.sc-band{position:absolute;top:2px;height:10px;border-radius:2px;opacity:.28}
.sc-tick{position:absolute;top:0;height:14px;width:2px;background:var(--muted)}
.sc-dot{position:absolute;top:2px;width:10px;height:10px;margin-left:-5px;border-radius:50%;border:2px solid var(--surface);box-sizing:content-box;margin-top:-2px}
.sc-row.net .lab,.sc-row.net .val{font-weight:700;color:var(--ink)}
.sc-sep{border-top:1px solid var(--ring);margin:8px 0}
.sc-stack{display:flex;height:22px;border-radius:3px;overflow:hidden;margin:4px 0 12px}
.sc-key{display:grid;grid-template-columns:12px 1fr auto;gap:6px 8px;font-size:12.5px;color:var(--ink2);align-items:center}
.sc-key i{width:10px;height:10px;border-radius:2px;display:block}
.sc-key .val{font-variant-numeric:tabular-nums}
</style>
"""

# Drawing helpers for the card's chart. They format and place figures the page already holds; none
# computes a statistic. A chart definition returns {title, html, lead?, note} or null when its data is
# missing; lead is one line reading the figures drawn (which rows sit where), note says how to read them.
CHART_JS = r"""
const SC = (() => {
  const F = FA, esc = F.esc, num = v => typeof v === 'number' && isFinite(v);
  const row = (r, track, val, cls = '') => `<div class="sc-row${r.net ? ' net' : ''}${cls}" title="${esc(r.tip || '')}"><span class="lab">${esc(r.label)}</span>` +
    `<span class="sc-track">${track}</span><span class="val">${val}</span></div>`;
  // diverging bars on one zero axis; a row may start where the one above ended (from)
  const rows = (items, fmt = F.moneyS) => {
    const ends = items.filter(r => !r.sep).flatMap(r => [r.from || 0, (r.from || 0) + r.v]);
    const lo = Math.min(0, ...ends), hi = Math.max(0, ...ends), span = (hi - lo) || 1, x = v => (v - lo) / span * 100;
    return items.map(r => {
      if (r.sep) return '<div class="sc-sep"></div>';
      const a = r.from || 0, b = a + r.v, L = Math.min(x(a), x(b)), W = Math.max(Math.abs(x(b) - x(a)), 0.8);
      const col = r.color || (r.v >= 0 ? 'var(--up)' : 'var(--down)');
      return row(r, `<span class="sc-axis" style="left:${x(0)}%"></span><span class="sc-bar" style="left:${L}%;width:${W}%;background:${col}"></span>`, fmt(r.v));
    }).join('');
  };
  // one marker per row on a shared scale [lo, hi], with optional shaded bands ([from, to, color]) and a tick
  const marks = (items, {lo, hi, fmt, bands = []}) => {
    const ends = items.flatMap(r => [r.v, ...(r.bands || []).flatMap(b => [b[0], b[1]]), ...(num(r.tick) ? [r.tick] : [])]).filter(num);
    const a = num(lo) ? lo : Math.min(...ends), b = num(hi) ? hi : Math.max(...ends), span = (b - a) || 1;
    const x = v => Math.max(0, Math.min(100, (v - a) / span * 100));
    return items.map(r => {
      const shade = [...bands, ...(r.bands || [])].map(([p, q, c]) => `<span class="sc-band" style="left:${x(p)}%;width:${Math.max(x(q) - x(p), 0.8)}%;background:${c || 'var(--warn)'}"></span>`).join('');
      const tick = num(r.tick) ? `<span class="sc-tick" style="left:${x(r.tick)}%"></span>` : '';
      return row(r, `<span class="sc-rail"></span>${shade}${tick}<span class="sc-dot" style="left:${x(r.v)}%;background:${r.color || 'var(--s1)'}"></span>`, r.val ?? fmt(r.v), ' mk');
    }).join('');
  };
  // draws the chart the card names; a chart whose data is missing removes the figure
  const mount = charts => {
    const g = id => document.getElementById(id), fig = g('sum-chart');
    if (!fig) return;
    const make = charts[fig.dataset.chart], r = make ? make() : null;
    if (!r) { fig.remove(); return; }
    g('sc-title').textContent = r.title; g('sc-body').innerHTML = r.html; g('sc-note').textContent = r.note || '';
    const lead = g('sc-lead'); lead.textContent = r.lead || ''; lead.hidden = !r.lead;
  };
  return {num, rows, marks, mount};
})();
"""
