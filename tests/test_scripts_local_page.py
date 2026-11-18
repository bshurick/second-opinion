from __future__ import annotations

import webbrowser

import pytest

from scripts_util import load_script, run_json
from second_opinion import page


@pytest.fixture
def mod():
    return load_script("get-started/scripts/local_page.py")


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path / "data"))
    return tmp_path


def _fragment(tmp_path, name="portfolio-snapshot.html"):
    src = tmp_path / name
    page.write(src, page.render("Portfolio Snapshot", {"a": 1}, "<h1>Brief — today</h1>", "void 0;"))
    return src


def test_standalone_wraps_a_fragment_once() -> None:
    doc = page.standalone(page.render("T & Co", {}, "<h1>x</h1>", ""))
    assert doc.startswith("<!doctype html>") and '<meta charset="utf-8">' in doc
    head = doc[: doc.index("</head>")]
    assert "<title>T &amp; Co</title>" in head and "<style>" not in head
    assert doc.count("<title>") == 1 and doc.rstrip().endswith("</html>")
    assert page.standalone(doc) == doc


def test_saves_a_whole_document_in_the_data_directory_and_opens_it(mod, tmp_data, monkeypatch, capsys) -> None:
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **kw: opened.append(url) or True)
    rc, out = run_json(mod, ["--in", str(_fragment(tmp_data))], capsys)
    assert rc == 0
    saved = tmp_data / "data" / "pages" / "portfolio-snapshot.html"
    assert out["path"] == str(saved) and out["opened"] is True and out["title"] == "Portfolio Snapshot"
    assert opened == [out["url"]] and out["url"].startswith("file://")
    text = saved.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and "Brief — today" in text


def test_no_browser_still_saves_the_file(mod, tmp_data, capsys) -> None:
    rc, out = run_json(mod, ["--in", str(_fragment(tmp_data)), "--name", "brief"], capsys)
    assert rc == 0 and out["opened"] is False
    assert (tmp_data / "data" / "pages" / "brief.html").is_file()


def test_no_open_never_calls_the_browser(mod, tmp_data, monkeypatch, capsys) -> None:
    monkeypatch.setattr(webbrowser, "open", lambda *a, **kw: pytest.fail("browser opened"))
    rc, out = run_json(mod, ["--in", str(_fragment(tmp_data)), "--no-open"], capsys)
    assert rc == 0 and out["opened"] is False


@pytest.mark.parametrize("args", [[], ["--in", "missing.html"], ["--in", "PAGE", "--name", "../x"]])
def test_bad_input_exits_2(mod, tmp_data, capsys, args) -> None:
    if args[:2] == ["--in", "PAGE"]:
        args = ["--in", str(_fragment(tmp_data)), *args[2:]]
    rc, out = run_json(mod, args, capsys)
    assert rc == 2 and "error" in out
