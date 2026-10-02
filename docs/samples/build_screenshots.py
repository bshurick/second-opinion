#!/usr/bin/env python3
"""Usage: build_screenshots.py [--only NAME ...] [--chrome PATH] [--keep-html DIR]

Renders the README screenshots in ``docs/images/`` from the fictional sample results in this
directory. Every page goes through the skill's real ``render.py``; nothing is fetched and no user
data is read, so the images show the made-up household in ``HOUSEHOLD.md`` and nothing else.

Each page is wrapped in a light-theme document, captured with headless Google Chrome at 1280 CSS px
wide and 2x scale, trimmed of trailing background, cut at the page's ``crop`` height (CSS px) when
one is set (moved up to the nearest blank gap so no card is sliced), and saved as an optimized 256-colour PNG.

Needs Google Chrome (or ``--chrome`` / ``$CHROME``) and Pillow. Run it after changing a renderer or a
sample fixture, then commit the updated PNGs.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parents[1]
IMAGES = PLUGIN_ROOT / "docs" / "images"

WIDTH = 1280  # CSS px; the page body caps itself at 1120 and centers
SCALE = 2
WINDOW_HEIGHT = 7000  # tall enough for every page; trailing background is trimmed
PAGE_BG = (0xF7, 0xF7, 0xF5)  # --page in the light theme (lib/second_opinion/page.py)

# name -> (skill, render.py arguments relative to this directory, crop height in CSS px or None)
PAGES: dict[str, tuple[str, list[str], int | None]] = {
    "portfolio-brief": ("portfolio-snapshot", ["--in", "portfolio-brief.json"], 2290),
    "risk-analysis": ("risk-analysis", ["--in", "risk-analysis.json"], 2260),
    "valuation": ("valuation", ["--in", "valuation.json"], 1380),
    "retirement": ("retirement", ["--in", "retirement.json"], 1780),
    "rebalancing": ("rebalancing", ["--in", "rebalancing.json"], 1660),
    "spending": ("spending", ["--in", "spending-month.json", "--changes", "spending-changes.json"], 1860),
    # Uncropped, unlike every page above. This skill's point is that each figure ships
    # with the disclosure that bounds it, and those run to the end: the circularity note
    # at 3321 and the whole assumptions section from 3439 to 5931. Cropping at the ~2290
    # the other pages use would have shown the numbers and none of the caveats, and even
    # 4200 cut the assumptions off mid-section. It sits in a collapsed block, so the
    # length costs the reader nothing until they open it.
    "fixed-income": ("fixed-income", ["--in", "fixed-income.json"], None),
}

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]


def find_chrome(explicit: str | None) -> str:
    for candidate in [explicit, os.environ.get("CHROME"), *CHROME_CANDIDATES]:
        if not candidate:
            continue
        found = candidate if Path(candidate).exists() else shutil.which(candidate)
        if found:
            return found
    sys.exit("Google Chrome not found; pass --chrome PATH or set CHROME")


def render_page(skill: str, args: list[str], out: Path) -> None:
    script = PLUGIN_ROOT / "skills" / skill / "scripts" / "render.py"
    resolved = [str(HERE / a) if a.endswith(".json") else a for a in args]
    proc = subprocess.run(
        [sys.executable, str(script), *resolved, "--out", str(out)],
        capture_output=True, text=True, cwd=PLUGIN_ROOT,
    )
    if proc.returncode != 0:
        sys.exit(f"{skill} render.py exited {proc.returncode}: {proc.stdout.strip()} {proc.stderr.strip()}")


def wrap_light(fragment: Path, page: Path) -> None:
    """The renderer emits a fragment the Artifact host wraps; wrap it the same way, pinned to light."""
    body = fragment.read_text(encoding="utf-8")
    page.write_text(
        '<!doctype html>\n<html lang="en" data-theme="light">\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n{body}\n</html>\n',
        encoding="utf-8",
    )


def capture(chrome: str, page: Path, png: Path) -> None:
    proc = subprocess.run(
        [
            chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--force-color-profile=srgb", f"--force-device-scale-factor={SCALE}",
            f"--window-size={WIDTH},{WINDOW_HEIGHT}", "--virtual-time-budget=3000",
            f"--screenshot={png}", page.as_uri(),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if not png.exists():
        sys.exit(f"Chrome did not write {png}: {proc.stderr.strip()[-400:]}")


def trim_and_save(raw: Path, dest: Path, crop: int | None) -> tuple[int, int]:
    from PIL import Image  # only the image step needs Pillow; tests import PAGES without it

    img = Image.open(raw).convert("RGB")
    w, h = img.size
    px = img.load()
    bottom = h
    step = SCALE * 4
    for y in range(h - 1, -1, -step):  # walk up from the bottom until a row differs from the page colour
        if any(px[x, y] != PAGE_BG for x in range(0, w, step)):
            bottom = min(h, y + 32 * SCALE)
            break
    if crop is not None and crop * SCALE < bottom:
        y = crop * SCALE
        blank = lambda row: all(px[x, row] == PAGE_BG for x in range(0, w, step))  # noqa: E731
        while y > 0 and not blank(y):
            y -= SCALE  # climb into the plain page background between two cards
        while y > 0 and blank(y):
            y -= SCALE  # then to the last row of the card above that gap
        bottom = min(bottom, y + 12 * SCALE)
    img = img.crop((0, 0, w, bottom))
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 256 colours without dithering keeps text and flat chart fills crisp at about a third of the size
    img.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(dest, optimize=True)
    return img.size


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", nargs="*", choices=sorted(PAGES), help="build just these pages")
    p.add_argument("--chrome", help="path to a Chrome or Chromium binary")
    p.add_argument("--keep-html", help="also keep the wrapped HTML pages in this directory")
    a = p.parse_args(argv)
    chrome = find_chrome(a.chrome)
    names = a.only or list(PAGES)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name in names:
            skill, args, crop = PAGES[name]
            fragment, page, raw = work / f"{name}.fragment.html", work / f"{name}.html", work / f"{name}.raw.png"
            render_page(skill, args, fragment)
            wrap_light(fragment, page)
            if a.keep_html:
                Path(a.keep_html).mkdir(parents=True, exist_ok=True)
                shutil.copy(page, Path(a.keep_html) / page.name)
            capture(chrome, page, raw)
            size = trim_and_save(raw, IMAGES / f"{name}.png", crop)
            print(f"{name}: docs/images/{name}.png {size[0]}x{size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
