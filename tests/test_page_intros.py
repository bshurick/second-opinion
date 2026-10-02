"""Every section on every summary page opens with a one-line plain-language intro (``<p class="sub">``)."""
from __future__ import annotations

import re

import pytest

from scripts_util import PLUGIN_ROOT, load_script
from second_opinion import page

RENDERERS = sorted(PLUGIN_ROOT.glob("skills/*/scripts/render.py"))
ADVICE = re.compile(r"\b(recommend\w*|advis\w*|should|suggest\w*)\b", re.I)
# a card or section, its heading, then what follows the heading
SECTION = re.compile(r'<(section|div|details)([^>]*)>\s*<h2[^>]*>(.*?)</h2>\s*(<p class="sub[^"]*"[^>]*>(.*?)</p>)?', re.S)


def _body(path) -> str:
    mod = load_script(str(path.relative_to(PLUGIN_ROOT / "skills")))
    return next(v for k, v in vars(mod).items() if k in ("BODY", "BODY_HTML", "HTML", "BODY_TEMPLATE") and isinstance(v, str))


def _sections(path):
    for m in SECTION.finditer(_body(path)):
        tag, attrs, title, sub, text = m.groups()
        if tag == "section" or "card" in attrs:
            yield re.sub(r"<[^>]+>", "", title).strip() or attrs, sub, text or ""


@pytest.mark.parametrize("path", RENDERERS, ids=lambda p: p.parts[-3])
def test_every_section_opens_with_an_intro(path) -> None:
    missing = [title for title, sub, _ in _sections(path) if not sub]
    assert not missing, f"sections without an intro line: {missing}"


@pytest.mark.parametrize("path", RENDERERS, ids=lambda p: p.parts[-3])
def test_intros_carry_no_advice_words(path) -> None:
    for title, _, text in _sections(path):
        hit = ADVICE.search(re.sub(r"<[^>]+>", "", text))
        assert not hit, f"{title!r}: {hit.group(0)}"


def test_flags_sections_share_one_intro() -> None:
    assert page.FLAGS_INTRO and not ADVICE.search(page.FLAGS_INTRO)
    for path in RENDERERS:
        if path.parts[-3] == "trade-review":  # its Flags are findings about your trades, with their own intro
            continue
        body = _body(path)
        if ">Flags</h2>" in body:
            assert page.FLAGS_INTRO in body, path.parts[-3]
