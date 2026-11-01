"""The headline analysis card: the rules a model-written summary must meet, and its HTML."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest

from second_opinion.errors import InvalidInput
from second_opinion.summary_card import FORBIDDEN_VERB_RE, card_html, full_read_today, load

GOOD = {
    "headline": "Tech leads a drop",
    "stands_out": "Tech fell 4.9%.",
    "look_into": "[Sectors](sec-card): the gap.",
}
TARGETS = ["sec-card", "flags-section"]


def _write(tmp_path, value):
    path = tmp_path / "summary.json"
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return str(path)


def _words(n):
    return " ".join(["word"] * n)


def test_load_returns_a_valid_summary(tmp_path):
    assert load(_write(tmp_path, GOOD), TARGETS) == GOOD


def test_load_accepts_the_optional_for_you(tmp_path):
    summary = {**GOOD, "for_you": "Stocks are 26% of the accounts."}
    assert load(_write(tmp_path, summary), TARGETS) == summary


@pytest.mark.parametrize("missing", ["headline", "stands_out", "look_into"])
def test_load_rejects_a_missing_required_field(tmp_path, missing):
    summary = {k: v for k, v in GOOD.items() if k != missing}
    with pytest.raises(InvalidInput, match=missing):
        load(_write(tmp_path, summary), TARGETS)


@pytest.mark.parametrize(
    "field,limit", [("headline", 20), ("stands_out", 90), ("look_into", 90), ("for_you", 70)]
)
def test_load_enforces_word_limits_at_the_boundary(tmp_path, field, limit):
    assert load(_write(tmp_path, {**GOOD, field: _words(limit)}), TARGETS)[field] == _words(limit)
    with pytest.raises(InvalidInput, match=field):
        load(_write(tmp_path, {**GOOD, field: _words(limit + 1)}), TARGETS)


def test_word_limit_counts_a_link_label_not_its_target(tmp_path):
    text = _words(89) + " [Sectors](sec-card)"
    assert load(_write(tmp_path, {**GOOD, "look_into": text}), TARGETS)["look_into"] == text


def test_word_limit_counts_every_word_of_a_link_label(tmp_path):
    text = _words(89) + " [Two words](sec-card)"
    with pytest.raises(InvalidInput, match="look_into"):
        load(_write(tmp_path, {**GOOD, "look_into": text}), TARGETS)


@pytest.mark.parametrize("field", ["headline", "stands_out", "look_into", "for_you"])
@pytest.mark.parametrize("word", ["recommend", "Recommends", "advise", "adviser", "SHOULD", "suggesting"])
def test_load_rejects_forbidden_verbs_in_any_field(tmp_path, field, word):
    with pytest.raises(InvalidInput, match=field):
        load(_write(tmp_path, {**GOOD, field: f"You {word} this"}), TARGETS)


def test_forbidden_pattern_ignores_words_that_only_contain_a_stem():
    assert not FORBIDDEN_VERB_RE.search("shoulder and shoulders")


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "extra": "x"},
        {**GOOD, "headline": 5},
        {**GOOD, "stands_out": None},
        {**GOOD, "look_into": ""},
        {**GOOD, "for_you": "   "},
    ],
)
def test_load_rejects_unknown_key_non_string_and_empty(tmp_path, bad):
    with pytest.raises(InvalidInput):
        load(_write(tmp_path, bad), TARGETS)


def test_load_rejects_a_link_to_an_undeclared_section(tmp_path):
    with pytest.raises(InvalidInput, match="nope-card"):
        load(_write(tmp_path, {**GOOD, "look_into": "[Nope](nope-card)"}), TARGETS)


@pytest.mark.parametrize("target", ["Sec_Card", "https://example.com", ""])
def test_load_rejects_a_link_whose_target_is_not_a_section_id(tmp_path, target):
    with pytest.raises(InvalidInput, match="look_into"):
        load(_write(tmp_path, {**GOOD, "look_into": f"[Sectors]({target})"}), TARGETS)


@pytest.mark.parametrize("field", ["headline", "stands_out", "for_you"])
def test_load_rejects_a_link_outside_look_into(tmp_path, field):
    with pytest.raises(InvalidInput, match=field):
        load(_write(tmp_path, {**GOOD, field: "[Sectors](sec-card)"}), TARGETS)


@pytest.mark.parametrize("content", ["not json", "[1]"])
def test_load_rejects_a_bad_file(tmp_path, content):
    with pytest.raises(InvalidInput):
        load(_write(tmp_path, content), TARGETS)


def test_load_rejects_a_missing_file(tmp_path):
    with pytest.raises(InvalidInput):
        load(str(tmp_path / "nothing.json"), TARGETS)


def test_card_html_is_empty_for_none():
    assert card_html(None) == ""


def test_card_html_escapes_text():
    html = card_html({**GOOD, "stands_out": "<script>x</script>"})
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_card_html_escapes_a_link_label():
    html = card_html({**GOOD, "look_into": "[<b>x</b>](sec-card)"})
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>" not in html


def test_card_html_renders_a_link_as_a_scroll_target():
    html = card_html(GOOD)
    assert 'data-summary-target="sec-card"' in html
    assert 'href="#' not in html
    assert ">Sectors</a>" in html
    assert "[Sectors]" not in html


def test_card_html_folds_for_you_and_omits_it_when_absent():
    assert "<details" not in card_html(GOOD)
    assert "What this means for you" not in card_html(GOOD)
    html = card_html({**GOOD, "for_you": "Stocks are 26%."})
    assert "<details" in html
    assert "<details open" not in html
    assert "What this means for you" in html
    assert "Stocks are 26%." in html


def test_card_labels_the_two_paragraphs():
    html = card_html(GOOD)
    assert "What stands out" in html
    assert "What to look into" in html


def test_card_is_exempt_from_the_page_help_button():
    html = card_html(GOOD)
    assert 'data-help="none"' in html
    assert "<h2" not in html


def _last_check(monkeypatch, tmp_path, record):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    if record is None:
        return
    text = record if isinstance(record, str) else json.dumps(record)
    (tmp_path / "portfolio-last-check.json").write_text(text)


def test_full_read_today_true_for_a_full_read_today(monkeypatch, tmp_path):
    now = datetime.now().astimezone()
    _last_check(monkeypatch, tmp_path, {"as_of": now.isoformat(), "partial": False})
    assert full_read_today() is True


@pytest.mark.parametrize(
    "record",
    [
        None,
        "not json",
        "[1]",
        {"as_of": "<yesterday>", "partial": False},
        {"as_of": "<today>", "partial": True},
        {"as_of": "<today>"},
        {"partial": False},
        {"as_of": "junk", "partial": False},
        {"as_of": 5, "partial": False},
    ],
)
def test_full_read_today_false_when_in_doubt(monkeypatch, tmp_path, record):
    now = datetime.now().astimezone()
    if isinstance(record, dict) and isinstance(record.get("as_of"), str):
        swap = {"<today>": now, "<yesterday>": now - timedelta(days=1)}
        if record["as_of"] in swap:
            record = {**record, "as_of": swap[record["as_of"]].isoformat()}
    _last_check(monkeypatch, tmp_path, record)
    assert full_read_today() is False


def test_full_read_today_compares_local_dates(monkeypatch, tmp_path):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        _last_check(monkeypatch, tmp_path, {"as_of": "2026-11-01T02:00:00+00:00", "partial": False})
        assert full_read_today(datetime(2026, 10, 31, 20, 0).astimezone()) is True
        assert full_read_today(datetime(2026, 11, 1, 20, 0).astimezone()) is False
    finally:
        monkeypatch.undo()
        time.tzset()
