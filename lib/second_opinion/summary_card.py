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
and a card with no chart is text alone.
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
WORD_LIMITS = {
    "headline": HEADLINE_WORDS,
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
            '<figcaption class="sc-title" id="sc-title"></figcaption><div id="sc-body"></div>'
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
