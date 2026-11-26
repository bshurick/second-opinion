"""Every page opens with its stat tiles: the headline text, summary card or analysis sits under them."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TILES = re.compile(r'<div class="tiles" id="(?:tiles|headline)"></div>')
# the headline text a page can carry: the model's summary card, a lead paragraph, or a review's findings
TEXT = re.compile(r'\{\{SUMMARY\}\}|<div class="lead">|id="about-card"|<div id="about"></div>')
PAGES = sorted(p for p in (ROOT / "skills").glob("*/scripts/render*.py") if TILES.search(p.read_text()) and TEXT.search(p.read_text()))


def test_pages_with_tiles_and_headline_text_are_found() -> None:
    names = {f"{p.parts[-3]}/{p.name}" for p in PAGES}
    assert {"market-analysis/render.py", "portfolio-analysis/render_brief.py", "portfolio-analysis/render_review.py",
            "real-estate/render_case.py", "tax-aware/render_plans.py", "trade-review/render_decisions.py",
            "valuation/render_deep.py"} <= names


@pytest.mark.parametrize("path", PAGES, ids=lambda p: f"{p.parts[-3]}/{p.name}")
def test_tiles_come_before_the_headline_text(path: Path) -> None:
    src = path.read_text()
    assert TILES.search(src).start() < TEXT.search(src).start()
