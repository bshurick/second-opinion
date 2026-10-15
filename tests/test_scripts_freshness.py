"""freshness.py: the line the UserPromptSubmit hook prints when the portfolio was last read on an
earlier day. Times are fixed so the local-date comparison is deterministic."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from scripts_util import load_script

FR = load_script("portfolio-snapshot/scripts/freshness.py")


def _local(y, m, d, hh=12, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm).astimezone()


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _mark(data_dir, when: datetime, partial: bool = False) -> None:
    (data_dir / "portfolio-last-check.json").write_text(json.dumps({"as_of": when.isoformat(), "partial": partial}))


def test_silent_when_read_today(data_dir) -> None:
    _mark(data_dir, _local(2026, 10, 15, 8))
    assert FR.line(data_dir, _local(2026, 10, 15, 21)) is None


def test_line_when_read_on_an_earlier_day(data_dir) -> None:
    _mark(data_dir, _local(2026, 10, 14, 17, 58))
    text = FR.line(data_dir, _local(2026, 10, 15, 9, 10))
    assert "2026-10-15 09:10 local time" in text and "last read 2026-10-14 17:58 (15 hours ago)" in text
    assert "brief.py --no-headlines" in text


def test_age_in_days_after_two_days(data_dir) -> None:
    _mark(data_dir, _local(2026, 10, 10))
    assert "(5 days ago)" in FR.line(data_dir, _local(2026, 10, 15))


def test_partial_read_is_named(data_dir) -> None:
    _mark(data_dir, _local(2026, 10, 14), partial=True)
    assert "left out a broker" in FR.line(data_dir, _local(2026, 10, 15))


def test_silent_for_a_new_user(data_dir) -> None:
    assert FR.line(data_dir, _local(2026, 10, 15)) is None


def test_connected_but_never_read(data_dir) -> None:
    (data_dir / "brokers.json").write_text("{}")
    assert "has not been read" in FR.line(data_dir, _local(2026, 10, 15))


def test_falls_back_to_the_last_brief_or_saved_snapshot(data_dir) -> None:
    (data_dir / "brief-last.json").write_text(json.dumps({"as_of": _local(2026, 10, 13).isoformat()}))
    (data_dir / "snapshots.json").write_text(json.dumps({"snapshots": [{"as_of": _local(2026, 10, 14, 9).isoformat()}]}))
    assert "last read 2026-10-14 09:00" in FR.line(data_dir, _local(2026, 10, 15))


def test_a_corrupt_marker_falls_back_and_main_never_fails(data_dir, capsys) -> None:
    (data_dir / "portfolio-last-check.json").write_text("{oops")
    assert FR.main(["--now", _local(2026, 10, 15).isoformat()]) == 0
    assert FR.main(["--now", "not a date"]) == 0
