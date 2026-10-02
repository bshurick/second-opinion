from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def _add(capsys, *extra):
    return run_json(load_script("financial-education/scripts/progress.py"), ["add", *extra], capsys)


def _list(capsys):
    return run_json(load_script("financial-education/scripts/progress.py"), ["list"], capsys)


def test_list_on_missing_file_is_empty(data_dir, capsys) -> None:
    rc, out = _list(capsys)
    assert rc == 0
    assert out == {
        "learner_path": str(data_dir / "learner.json"),
        "sessions": [],
        "concepts_covered": [],
        "missed_history": [],
        "level": None,
    }


def test_add_records_a_session(data_dir, capsys) -> None:
    rc, out = _add(
        capsys,
        "--level", "beginner", "--concept", "compound interest", "--concept", "index funds",
        "--missed", "l1-q1", "--date", "2026-01-05",
    )
    assert rc == 0, out
    assert out["added"] == {
        "date": "2026-01-05", "level": "beginner",
        "concepts": ["compound interest", "index funds"], "missed": ["l1-q1"], "placed": False,
    }
    assert out["learner_path"] == str(data_dir / "learner.json") and out["count"] == 1
    book = json.loads((data_dir / "learner.json").read_text())
    assert book["sessions"][0]["level"] == "beginner"


def test_add_validation(data_dir, capsys) -> None:
    rc, out = run_json(load_script("financial-education/scripts/progress.py"), ["add", "--level", "beginner"], capsys)
    assert rc == 2 and "--concept" in out["error"]
    rc, out = run_json(
        load_script("financial-education/scripts/progress.py"),
        ["add", "--concept", "compound interest"],
        capsys,
    )
    assert rc == 2


def test_place_marks_latest_session_at_level(data_dir, capsys) -> None:
    _add(capsys, "--level", "beginner", "--concept", "compound interest", "--date", "2026-01-05")
    _add(capsys, "--level", "beginner", "--concept", "index funds", "--date", "2026-01-06")
    rc, out = run_json(
        load_script("financial-education/scripts/progress.py"), ["place", "--level", "beginner"], capsys
    )
    assert rc == 0
    assert out["placed"]["date"] == "2026-01-06" and out["placed"]["placed"] is True
    book = json.loads((data_dir / "learner.json").read_text())
    assert book["sessions"][0]["placed"] is False and book["sessions"][1]["placed"] is True


def test_place_with_no_matching_session_is_invalid(data_dir, capsys) -> None:
    rc, out = run_json(
        load_script("financial-education/scripts/progress.py"), ["place", "--level", "advanced"], capsys
    )
    assert rc == 2 and "no session recorded at level" in out["error"]


def test_list_summarizes_concepts_missed_history_and_level(data_dir, capsys) -> None:
    _add(capsys, "--level", "beginner", "--concept", "compound interest", "--missed", "l1-q1", "--date", "2026-01-06")
    _add(
        capsys,
        "--level", "beginner", "--concept", "index funds", "--concept", "fees",
        "--missed", "l1-q1", "--missed", "l1-q2", "--date", "2026-01-05",
    )
    _add(capsys, "--level", "intermediate", "--concept", "diversification", "--date", "2026-01-07")
    rc, out = _list(capsys)
    assert rc == 0, out
    # ascending by date, ties broken by insertion order
    assert [s["date"] for s in out["sessions"]] == ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert out["concepts_covered"] == ["compound interest", "diversification", "fees", "index funds"]
    assert out["missed_history"] == [{"quiz_id": "l1-q1", "count": 2}, {"quiz_id": "l1-q2", "count": 1}]
    # no session placed yet: level falls back to the latest session (by date)
    assert out["level"] == "intermediate"
    run_json(load_script("financial-education/scripts/progress.py"), ["place", "--level", "beginner"], capsys)
    rc, out = _list(capsys)
    assert out["level"] == "beginner"


def test_corrupt_learner_file_exits_5(data_dir, capsys) -> None:
    (data_dir / "learner.json").write_text("{not json")
    rc, out = _list(capsys)
    assert rc == 5 and out["code"] == "LEARNER_STATE_CORRUPT"


def test_malformed_learner_shape_exits_5(data_dir, capsys) -> None:
    (data_dir / "learner.json").write_text(json.dumps({"sessions": "nope"}))
    rc, out = _add(capsys, "--level", "beginner", "--concept", "fees")
    assert rc == 5 and out["code"] == "LEARNER_STATE_CORRUPT"
