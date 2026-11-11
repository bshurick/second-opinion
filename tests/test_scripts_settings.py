from __future__ import annotations

import json

import pytest

from scripts_util import load_script, run_json

GROUPS = ["Depth", "Accounts", "Portfolio plan", "Taxes", "Guardrails", "Replies", "Lessons"]


@pytest.fixture
def mod():
    return load_script("get-started/scripts/settings.py")


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_OPINION_DATA", str(tmp_path))
    monkeypatch.setenv("SECOND_OPINION_LATEST_PLUGIN_JSON", str(tmp_path / "no-latest.json"))
    return tmp_path


@pytest.fixture
def fake_plugin_version(tmp_path, monkeypatch):
    p = tmp_path / "plugin-under-test.json"
    monkeypatch.setenv("SECOND_OPINION_PLUGIN_JSON", str(p))

    def set_version(v: str) -> None:
        p.write_text(json.dumps({"version": v}))
    return set_version


def test_show_groups_in_order(mod, tmp_data, capsys):
    rc, out = run_json(mod, ["show"], capsys)
    assert rc == 0
    assert [g["group"] for g in out["groups"]] == GROUPS
    depth = out["groups"][0]["rows"][0]
    assert depth["key"] == "depth" and depth["is_default"] is True and depth["changed_on"] is None
    assert out["warnings"] == []


def test_show_lists_dynamic_keys_and_changed_on(mod, tmp_data, capsys):
    run_json(mod, ["set", "accounts.A1.role", "savings", "--today", "2026-11-01"], capsys)
    run_json(mod, ["set", "plan.sleeves.GROWTH.target", "0.2", "--today", "2026-11-02"], capsys)
    run_json(mod, ["set", "depth", "deep", "--today", "2026-11-03"], capsys)
    _, out = run_json(mod, ["show"], capsys)
    rows = {r["key"]: r for g in out["groups"] for r in g["rows"]}
    assert rows["accounts.A1.role"]["value"] == "savings" and rows["accounts.A1.role"]["changed_on"] == "2026-11-01"
    assert rows["plan.sleeves.GROWTH.target"]["value"] == 0.2
    assert rows["depth"]["changed_on"] == "2026-11-03" and rows["depth"]["is_default"] is False
    by_group = {g["group"]: [r["key"] for r in g["rows"]] for g in out["groups"]}
    assert "accounts.A1.role" in by_group["Accounts"]
    assert "plan.sleeves.GROWTH.target" in by_group["Portfolio plan"]
    assert "meta" not in rows and "history" not in rows


def test_set_then_get_plain(mod, tmp_data, capsys):
    assert run_json(mod, ["set", "replies.follow_ups", "on"], capsys)[1]["previous"] is False
    assert mod.main(["get", "replies.follow_ups", "--plain"]) == 0
    assert capsys.readouterr().out.strip() == "on"
    rc, out = run_json(mod, ["get", "replies.follow_ups"], capsys)
    assert out == {"key": "replies.follow_ups", "value": True}


def test_set_bad_value_exits_2(mod, tmp_data, capsys):
    assert mod.main(["set", "depth", "extreme"]) == 2


def test_unknown_key_exits_2(mod, tmp_data, capsys):
    assert mod.main(["get", "nope"]) == 2


def test_set_on_newer_schema_exits_5(mod, tmp_data, capsys):
    (tmp_data / "settings.json").write_text('{"schema": 3}')
    assert mod.main(["set", "depth", "deep"]) == 5


def test_corrupt_exits_5(mod, tmp_data, capsys):
    (tmp_data / "settings.json").write_text("{not json")
    assert mod.main(["show"]) == 5


def test_notice_first_run_silent_then_update(mod, tmp_data, fake_plugin_version, capsys):
    fake_plugin_version("1.1.0")
    assert mod.main(["notice"]) == 0 and capsys.readouterr().out == ""
    fake_plugin_version("1.2.0")
    assert mod.main(["notice"]) == 0
    assert "Second Opinion updated to 1.2.0 (was 1.1.0)" in capsys.readouterr().out
    assert mod.main(["notice"]) == 0 and capsys.readouterr().out == ""


def test_notice_never_fails(mod, tmp_data, fake_plugin_version, capsys):
    (tmp_data / "settings.json").write_text("{not json")
    fake_plugin_version("1.1.0")
    assert mod.main(["notice"]) == 0 and capsys.readouterr().out == ""
    assert mod.main(["notice", "--bogus"]) == 0 and capsys.readouterr().out == ""


def test_version_report_checkout(mod, tmp_data, fake_plugin_version, capsys, monkeypatch):
    fake_plugin_version("1.1.0")
    (tmp_data / "installed.json").write_text(json.dumps({"source_path": "/src/so"}))
    latest = tmp_data / "latest.json"
    latest.write_text(json.dumps({"version": "1.3.0"}))
    monkeypatch.setenv("SECOND_OPINION_LATEST_PLUGIN_JSON", str(latest))
    _, out = run_json(mod, ["version"], capsys)
    assert out["installed"] == "1.1.0" and out["latest"] == "1.3.0"
    assert out["seen"] is None and out["updated"] is False
    assert out["update_command"] == "cd /src/so && git pull && node install.js"


def test_version_report_marketplace_and_no_latest(mod, tmp_data, fake_plugin_version, capsys):
    fake_plugin_version("1.1.0")
    _, out = run_json(mod, ["version"], capsys)  # no source_path recorded -> marketplace install
    assert out["latest"] is None
    assert out["update_command"] == ("claude plugin marketplace update second-opinion && "
                                     "claude plugin update second-opinion@second-opinion, then restart Claude Code")


def test_version_updated_flag(mod, tmp_data, fake_plugin_version, capsys):
    fake_plugin_version("1.1.0")
    mod.main(["notice"])
    capsys.readouterr()
    fake_plugin_version("1.2.0")
    _, out = run_json(mod, ["version"], capsys)
    assert out["seen"] == "1.1.0" and out["updated"] is True


def test_set_runs_on_a_bare_python_before_the_venv_exists(tmp_path):
    """The installer writes its switches with the system Python, before the venv exists: standard library only."""
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "settings-migrate" / "full"
    for f in fixture.iterdir():
        shutil.copy(f, tmp_path / f.name)
    script = Path(__file__).resolve().parents[1] / "skills" / "get-started" / "scripts" / "settings.py"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["SECOND_OPINION_DATA"] = str(tmp_path)
    r = subprocess.run([sys.executable, "-S", "-I", str(script), "set", "replies.follow_ups", "on"],
                       capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["replies"]["follow_ups"] is True
    assert saved["plan"]["sleeves"]["PICKS"]["target"] is None  # migrated before the set (ceiling 1.0)


def test_account_role_can_be_cleared_with_none(mod, tmp_data, capsys):
    run_json(mod, ["set", "accounts.A1.role", "savings"], capsys)
    rc, out = run_json(mod, ["set", "accounts.A1.role", "none"], capsys)
    assert rc == 0 and out["value"] is None and out["previous"] == "savings"
    assert mod.main(["get", "accounts.A1.role", "--plain"]) == 0
    assert capsys.readouterr().out.strip() == "none"


def test_notice_after_a_migration_from_1_0_0(mod, tmp_data, fake_plugin_version, capsys):
    fake_plugin_version("1.1.0")
    (tmp_data / "targets.json").write_text('{"targets": {"VTI": 1.0}}')
    assert mod.main(["notice"]) == 0
    assert capsys.readouterr().out.strip() == (
        'Second Opinion updated to 1.1.0: your settings moved into settings.json (say "show my settings" to see them).')
    assert mod.main(["notice"]) == 0 and capsys.readouterr().out == ""


def test_notice_after_a_migration_counts_the_warnings(mod, tmp_data, fake_plugin_version, capsys):
    fake_plugin_version("1.1.0")
    (tmp_data / "core-satellite.json").write_text('{"ceiling": 5, "weighting": "bogus", "short_term_gain_policy": "allow"}')
    assert mod.main(["notice"]) == 0
    assert capsys.readouterr().out.strip() == (
        'Second Opinion updated to 1.1.0: your settings moved into settings.json (say "show my settings" to see them). '
        '2 setting(s) could not be moved; "show my settings" lists them.')
    assert mod.main(["notice"]) == 0 and capsys.readouterr().out == ""


def test_notice_fresh_install_stays_silent(mod, tmp_data, fake_plugin_version, capsys):
    fake_plugin_version("1.1.0")
    assert mod.main(["notice"]) == 0 and capsys.readouterr().out == ""
    assert json.loads((tmp_data / "settings.json").read_text())["meta"]["seen_version"] == "1.1.0"


def test_notice_silent_after_a_fresh_install_by_the_installer(mod, tmp_data, fake_plugin_version, capsys):
    """The installer writes installed.json (a skills list, no extras) and then its switches: nothing moved."""
    fake_plugin_version("1.1.0")
    (tmp_data / "installed.json").write_text(json.dumps({"skills": ["trade-journal", "spending"], "mode": "copy"}))
    run_json(mod, ["set", "replies.follow_ups", "off"], capsys)
    assert json.loads((tmp_data / "settings.json").read_text())["meta"]["migrated_from"] == []
    assert mod.main(["notice"]) == 0 and capsys.readouterr().out == ""


def test_show_lists_deep_paths(mod, tmp_data, capsys):
    from second_opinion import settings
    rc, out = run_json(mod, ["show"], capsys)
    assert rc == 0 and [r["skill"] for r in out["deep_paths"]] == sorted(settings.DEEP_PATHS)
    assert all(r["what"] for r in out["deep_paths"])
