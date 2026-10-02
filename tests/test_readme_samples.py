"""The README screenshots come from fictional fixtures in docs/samples; keep them renderable and linked."""
from __future__ import annotations

import re

import pytest

from scripts_util import PLUGIN_ROOT, load_script, run_json

SAMPLES = PLUGIN_ROOT / "docs" / "samples"
IMAGES = PLUGIN_ROOT / "docs" / "images"
README = PLUGIN_ROOT / "README.md"

# image name -> (renderer, render.py arguments naming fixtures in docs/samples)
PAGES = {
    "portfolio-brief": ("portfolio-snapshot/scripts/render.py", ["--in", "portfolio-brief.json"]),
    "risk-analysis": ("risk-analysis/scripts/render.py", ["--in", "risk-analysis.json"]),
    "valuation": ("valuation/scripts/render.py", ["--in", "valuation.json"]),
    "retirement": ("retirement/scripts/render.py", ["--in", "retirement.json"]),
    "rebalancing": ("rebalancing/scripts/render.py", ["--in", "rebalancing.json"]),
    "spending": ("spending/scripts/render.py", ["--in", "spending-month.json", "--changes", "spending-changes.json"]),
    "fixed-income": ("fixed-income/scripts/render.py", ["--in", "fixed-income.json"]),
}


def _build_script():
    return load_script("../docs/samples/build_screenshots.py")


@pytest.mark.parametrize("name", sorted(PAGES))
def test_sample_fixture_still_renders(name, tmp_path, capsys) -> None:
    script, args = PAGES[name]
    argv = [str(SAMPLES / a) if a.endswith(".json") else a for a in args]
    rc, res = run_json(load_script(script), [*argv, "--out", str(tmp_path / "page.html")], capsys)
    assert rc == 0, res
    html = (tmp_path / "page.html").read_text()
    assert "window.DATA = " in html and "NaN" not in html.split("<script>")[0]


def test_build_script_and_this_test_cover_the_same_pages() -> None:
    build = _build_script()
    assert set(build.PAGES) == set(PAGES)
    for name, (skill, args, _crop) in build.PAGES.items():
        assert PAGES[name] == (f"{skill}/scripts/render.py", args)


def test_readme_images_exist_and_none_are_orphaned() -> None:
    linked = set(re.findall(r"\]\(docs/images/([\w-]+)\.png\)", README.read_text()))
    on_disk = {p.stem for p in IMAGES.glob("*.png")}
    assert linked == set(PAGES)
    assert on_disk == set(PAGES)


def test_sample_accounts_are_visibly_fictional() -> None:
    """Every account a sample page names is a 'Sample ...' account, so a real one cannot slip in."""
    import json

    brief = json.loads((SAMPLES / "portfolio-brief.json").read_text())
    assert brief["accounts"] and all(a["name"].startswith("Sample ") for a in brief["accounts"])
    rebalancing = json.loads((SAMPLES / "rebalancing.json").read_text())
    assert all(a.startswith("Sample ") for a in rebalancing["accounts"])
    assert all(t["account"].startswith("Sample ") for t in rebalancing["trades"])
    spending = json.loads((SAMPLES / "spending-month.json").read_text())
    assert all(a["name"].startswith("Sample ") for a in spending["accounts"].values())
