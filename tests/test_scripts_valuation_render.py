"""valuation/scripts/render.py: the quick valuation page."""

from __future__ import annotations

import json

from scripts_util import PLUGIN_ROOT, load_script, run_json

RENDER = load_script("valuation/scripts/render.py")
SAMPLE = PLUGIN_ROOT / "docs" / "samples" / "valuation.json"


def test_quick_page_is_stamped_standard_depth(tmp_path, capsys) -> None:
    out_html = tmp_path / "p.html"
    rc, res = run_json(RENDER, ["--in", str(SAMPLE), "--out", str(out_html)], capsys)
    assert rc == 0 and res["depth"] == "standard"
    assert '<p class="depth">Standard depth</p>' in out_html.read_text()


def test_stamp_does_not_follow_the_saved_depth(tmp_path, capsys, monkeypatch) -> None:
    from second_opinion import settings
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    settings.set_value("depth", "deep")
    rc, res = run_json(RENDER, ["--in", str(SAMPLE), "--out", str(tmp_path / "p.html")], capsys)
    assert rc == 0 and res["depth"] == "standard"
