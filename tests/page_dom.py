"""Headless-Chrome DOM audit for page.py pages: render, open with #fa-audit, read the JSON it writes."""
from __future__ import annotations

import html as html_mod
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts_util import load_script, run_json

_CANDIDATES = [os.environ.get("CHROME") or "", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


def _find_chrome() -> str | None:
    for c in _CANDIDATES:
        if not c:
            continue
        if Path(c).exists():
            return c
        if shutil.which(c):
            return shutil.which(c)
    return None


CHROME = _find_chrome()
requires_chrome = pytest.mark.skipif(CHROME is None, reason="Google Chrome not found")
ADVICE = re.compile(r"\b(recommend\w*|advis\w*|should|suggest\w*)\b", re.I)
_AUDIT = re.compile(r'<script type="application/json" id="fa-audit">(.*?)</script>', re.S)


def audit_html(fragment: str, tmp_path: Path) -> dict:
    doc = f'<!doctype html><html><head><meta charset="utf-8"></head><body>{fragment}</body></html>'
    p = tmp_path / "audit.html"
    p.write_text(doc, encoding="utf-8")
    out = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=3000",
                          "--window-size=1280,2000", "--dump-dom", p.as_uri() + "#fa-audit"],
                         capture_output=True, text=True, timeout=90)
    m = _AUDIT.search(out.stdout)
    assert m, f"no audit JSON in Chrome output; stderr tail: {out.stderr[-500:]}"
    return json.loads(html_mod.unescape(m.group(1)))


def render_and_audit(script_rel: str, args: list[str], tmp_path: Path, capsys) -> dict:
    out = tmp_path / "page.html"
    rc, res = run_json(load_script(script_rel), [*args, "--out", str(out)], capsys)
    assert rc == 0, res
    return audit_html(out.read_text(encoding="utf-8"), tmp_path)


def assert_page_help(audit: dict) -> None:
    """A converted page: no '?' links, every visible card authored (or exempt), one button, modal sane."""
    assert audit["help_links"] == 0
    # a page whose script died leaves every card hidden; that must fail, not pass vacuously
    assert any(not c["hidden"] and c["help"] != "exempt" for c in audit["cards"]), "no visible card: did the page script fail?"
    for c in audit["cards"]:
        if c["hidden"] or c["help"] == "exempt":
            continue
        assert c["help"] == "authored", f"card {c['h2']!r} has help {c['help']!r}"
        assert c["buttons"] == 1, c
        m = c["modal"]
        assert m and m["lead"].strip(), f"card {c['h2']!r} modal has no lead"
        assert len(m["terms"]) == len(set(m["terms"])), m["terms"]
        hit = ADVICE.search(m["authored"])  # the glossary list has its own reviewed digest (test_output.py)
        assert not hit, f"advice verb in {c['h2']!r}: {hit and hit.group(0)}"


def card_text(audit: dict, h2_prefix: str) -> str:
    """The authored modal text of the first card whose heading starts with ``h2_prefix``."""
    for c in audit["cards"]:
        if c["h2"].startswith(h2_prefix) and c["modal"]:
            return c["modal"]["authored"]
    raise AssertionError(f"no card starting {h2_prefix!r}: {[c['h2'] for c in audit['cards']]}")
