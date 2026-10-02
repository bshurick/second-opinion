"""onboarding/scripts/profile.py: the CLI over the profile library."""

from __future__ import annotations

import json

import pytest
from scripts_util import load_script, run_json
from second_opinion import profile


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    return tmp_path


def script():
    return load_script("onboarding/scripts/profile.py")


def test_set_creates_a_profile_and_writes_the_field(data_dir, capsys) -> None:
    rc, out = run_json(script(), ["set", "approach", "value,", "index"], capsys)
    assert rc == 0, out
    assert out["field"] == "approach" and out["value"] == ["value", "index"] and out["source"] == "declared"
    saved = json.loads((data_dir / "profile.json").read_text())
    assert saved["onboarding"]["status"] == "skipped" and saved["fields"]["approach"]["value"] == ["value", "index"]


def test_set_rejects_bad_vocabulary_with_exit_2(capsys) -> None:
    rc, out = run_json(script(), ["set", "horizon", "decades"], capsys)
    assert rc == 2 and "horizon must be one of" in out["error"]


def test_skip_creates_a_skipped_profile_and_complete_upgrades_it(data_dir, capsys) -> None:
    rc, out = run_json(script(), ["skip"], capsys)
    assert rc == 0 and out["onboarding"]["status"] == "skipped"
    rc, out = run_json(script(), ["complete"], capsys)
    assert rc == 0 and out["onboarding"]["status"] == "complete"
    assert json.loads((data_dir / "profile.json").read_text())["onboarding"]["status"] == "complete"


def test_show_returns_profile_with_summary_and_pending(capsys) -> None:
    run_json(script(), ["set", "horizon", "years"], capsys)
    rc, out = run_json(script(), ["show"], capsys)
    assert rc == 0
    assert out["fields"]["horizon"]["value"] == "years"
    assert out["summary"].startswith("Second Opinion profile")
    assert out["pending_proposals"] == [] and out["learning"] is True


def test_show_without_profile_exits_4_with_hint(capsys) -> None:
    rc, out = run_json(script(), ["show"], capsys)
    assert rc == 4 and out["code"] == "NO_PROFILE" and "get started with Second Opinion" in out["hint"]


def test_show_with_bad_shaped_proposals_exits_5(data_dir, capsys) -> None:
    (data_dir / "profile.json").write_text(json.dumps({
        "version": 1, "created": "2026-09-10", "updated": "2026-09-10", "learning": True,
        "onboarding": {"status": "complete", "at": "2026-09-10", "version": 1},
        "fields": {}, "proposals": "oops", "declined": [],
    }))
    rc, out = run_json(script(), ["show"], capsys)
    assert rc == 5 and out["code"] == "PROFILE_CORRUPT"


def test_unset_and_learning_toggle(capsys) -> None:
    run_json(script(), ["set", "goals", "retirement"], capsys)
    rc, out = run_json(script(), ["unset", "goals"], capsys)
    assert rc == 0 and "goals" not in out["fields"]
    rc, out = run_json(script(), ["learning", "off"], capsys)
    assert rc == 0 and out["learning"] is False
    rc, out = run_json(script(), ["learning", "on"], capsys)
    assert rc == 0 and out["learning"] is True


def test_context_prints_plain_text(capsys) -> None:
    rc = script().main(["context"])
    assert rc == 0 and capsys.readouterr().out.strip() == profile.NO_PROFILE_LINE
    run_json(script(), ["skip"], capsys)
    script().main(["context"])
    assert capsys.readouterr().out.strip() == profile.SKIPPED_LINE
    run_json(script(), ["set", "horizon", "years"], capsys)
    script().main(["context"])
    assert capsys.readouterr().out.strip().startswith("Second Opinion profile (declared")


def test_context_prints_one_line_on_malformed_field_entry(data_dir, capsys) -> None:
    (data_dir / "profile.json").write_text(json.dumps({
        "version": 1, "created": "2026-09-10", "updated": "2026-09-10", "learning": True,
        "onboarding": {"status": "complete", "at": "2026-09-10", "version": 1},
        "fields": {"horizon": {"source": "declared", "at": "2026-09-10"}},
        "proposals": [], "declined": [],
    }))
    rc = script().main(["context"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out == "Second Opinion profile file could not be read; say 'show my profile' to see the error and the fix.\n"


def test_next_steps_offline_uses_installed_skills_on_disk(monkeypatch, capsys) -> None:
    run_json(script(), ["set", "approach", "value"], capsys)
    run_json(script(), ["set", "goals", "retirement"], capsys)
    monkeypatch.delenv("SNAPTRADE_CLIENT_ID", raising=False)
    monkeypatch.delenv("ETRADE_CONSUMER_KEY", raising=False)
    monkeypatch.setenv("EDGAR_USER_AGENT", "test me@example.com")
    rc, out = run_json(script(), ["next-steps", "--offline"], capsys)
    assert rc == 0, out
    assert out["connected_accounts"] == 0 and out["installed_skills"]  # real skills dir
    assert out["try_asking"][0].startswith("Does KO pass Graham")
    assert "Am I on track to retire at 60?" in out["try_asking"]


def test_delete_requires_confirm(data_dir, capsys) -> None:
    run_json(script(), ["skip"], capsys)
    rc, out = run_json(script(), ["delete"], capsys)
    assert rc == 3 and out["code"] == "NOT_CONFIRMED"
    assert (data_dir / "profile.json").exists()
    rc, out = run_json(script(), ["delete", "--confirm"], capsys)
    assert rc == 0 and out["deleted"] == ["profile.json"]
    assert not (data_dir / "profile.json").exists()


def test_usage_on_no_command(capsys) -> None:
    rc, out = run_json(script(), [], capsys)
    assert rc == 2 and "usage" in out["error"].lower()
