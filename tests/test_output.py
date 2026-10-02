from __future__ import annotations

import json
from decimal import Decimal

import pytest

from second_opinion import config, output, page
from second_opinion.errors import ApiError, ConfigError, InvalidInput, NotConfirmed


def _out(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_run_emits_dict_result_and_returns_zero(capsys) -> None:
    rc = output.run(lambda argv: {"ok": True, "units": Decimal("1.5"), "argv": argv}, ["a"])
    assert rc == 0
    assert _out(capsys) == {"ok": True, "units": "1.5", "argv": ["a"]}


def test_run_passes_through_int_result(capsys) -> None:
    assert output.run(lambda argv: 3, []) == 3
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "exc,exit_code,code",
    [
        (InvalidInput("bad qty"), 2, "INVALID_INPUT"),
        (NotConfirmed("preview only", preview={"x": 1}), 3, "NOT_CONFIRMED"),
        (ConfigError("missing", hint=config.SETUP_HINT), 4, "CONFIG_MISSING"),
        (ApiError("boom", http_status=429), 5, "API_ERROR"),
    ],
)
def test_run_maps_script_errors(capsys, exc, exit_code, code) -> None:
    def fn(argv):
        raise exc

    assert output.run(fn, []) == exit_code
    body = _out(capsys)
    assert body["code"] == code
    assert body["error"] == str(exc)
    for k, v in exc.extra.items():
        assert body[k] == v


def test_run_maps_import_error_to_dependency_missing(capsys, monkeypatch) -> None:
    monkeypatch.setenv("SNAPTRADE_INSTALL_LOG", "/tmp/install.log")

    def fn(argv):
        raise ImportError("No module named 'snaptrade_client'", name="snaptrade_client")

    assert output.run(fn, []) == 6
    body = _out(capsys)
    assert body["code"] == "DEPENDENCY_MISSING"
    assert body["missing"] == "snaptrade_client"
    assert body["requirements"].endswith("requirements.txt")
    assert body["install_log"] == "/tmp/install.log"


def test_run_maps_unknown_exception_to_api_error(capsys) -> None:
    class Boom(Exception):
        status = 500

    def fn(argv):
        raise Boom("upstream down")

    assert output.run(fn, []) == 5
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body == {"error": "upstream down", "code": "API_ERROR", "http_status": 500, "type": "Boom"}
    assert "Traceback" in captured.err


def test_render_escapes_a_title_that_closes_its_own_tag() -> None:
    # ``title`` is caller-supplied and lands in markup, and renderers pass live
    # values into it -- a symbol, a fund name. Unescaped, a symbol of
    # ``X</title><h1>..</h1><script>..</script><title>y`` closed the title element
    # and put an arbitrary heading and an executable script at the top of the page,
    # which for a finance skill means a trade signal on a page a user reads.
    html = page.render(
        'X</title><h1>BUY: a strong buy.</h1><script>alert(1)</script><title>y',
        {},
        "<p>body</p>",
        "",
    )
    assert "<h1>BUY: a strong buy.</h1>" not in html
    assert "<script>alert(1)</script>" not in html
    # Exactly one title element, and the hostile text is inert inside it.
    assert html.count("<title>") == 1 and html.count("</title>") == 1
    assert "&lt;h1&gt;BUY: a strong buy.&lt;/h1&gt;" in html


def test_render_escapes_the_description() -> None:
    # Same argument for the other caller-supplied string that lands in markup.
    html = page.render("T", {}, "<p>body</p>", "", description="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_render_leaves_ordinary_titles_readable() -> None:
    # Escaping must not disfigure the ordinary case: quote=False keeps apostrophes
    # and quotes as themselves, since the title is text content, not an attribute.
    assert "<title>Fixed Income — BND</title>" in page.render("Fixed Income — BND", {}, "", "")
    assert "<title>Moody's Baa</title>" in page.render("Moody's Baa", {}, "", "")


def _shared_text(name: str) -> str:
    """The reviewable text of one shared constant, as bytes a digest can be taken over."""
    value = getattr(page, name)
    if isinstance(value, str):
        return value
    return json.dumps({k: list(v) for k, v in value.items()}, sort_keys=True, separators=(",", ":"))


# Every skill's page is wrapped in these three constants. A `content:` rule added to the CSS, a DOM
# write added to the JS, or a glossary definition rewritten to a verdict renders text on FIFTEEN
# skills' pages at once -- and no renderer's own completeness pin can see it, because those pins are
# built from these same constants. So the guard belongs here, beside page.render's other behaviour,
# rather than in one skill's test file where it would fail in a surprising place and leave the other
# fourteen renderers unguarded.
#
# GLOSSARY is on this list for the same reason as the other two, and it is the least obvious: it is
# data, not markup, but page.JS's `armTerms` writes every definition into a tooltip at view time and
# fourteen renderers emit `.term[data-term]` nodes. A definition rewritten to advisory text is on
# those pages and out of every test's reach.
#
# A digest is a change detector, and that is the intent: it catches an edit of any shape, including
# the ones nobody enumerated. The value the failure prints is for a maintainer to paste AFTER the
# review it names, not instead of it.
SHARED_CSS_SHA256 = "1ff5bcb86c68f8fb86897c6f2f4ea33c7dbb3e176b40ef2db9128a5e5762e444"
SHARED_JS_SHA256 = "89bb9be43e54460970c60c4d595717fc1aa2bce61c03249895f0d90529cc2818"
SHARED_GLOSSARY_SHA256 = "5f9580e6bdcc5364f207f45310fb7fd8b71bacb0469744e254f002c1f802c80d"


@pytest.mark.parametrize(
    "name,expected",
    [("CSS", SHARED_CSS_SHA256), ("JS", SHARED_JS_SHA256), ("GLOSSARY", SHARED_GLOSSARY_SHA256)],
)
def test_the_shared_page_toolkit_is_not_edited_unreviewed(name: str, expected: str) -> None:
    import hashlib

    actual = hashlib.sha256(_shared_text(name).encode("utf-8")).hexdigest()
    assert actual == expected, (
        f"page.{name} changed, and fifteen skills' pages carry it.\n"
        f"Before pasting the new digest, the person making this change reads "
        f"`git diff -- lib/second_opinion/page.py` and confirms that NOTHING in the diff puts text "
        f"in front of a reader that they would be content to see on all fifteen pages: no `content:` "
        f"declaration, no string written into the DOM, no rewritten glossary definition, and above "
        f"all nothing that reads as a recommendation, a fair value, or a cheap/expensive verdict on "
        f"a security. Updating this digest without reading that diff defeats the only check that "
        f"sees such an edit at all.\n"
        f"Once that is done: {actual}"
    )
