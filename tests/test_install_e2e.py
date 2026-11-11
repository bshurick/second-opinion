"""The built installer (install.js) against a data dir that still holds the 1.0.0 files.

Regression for the installer writing settings.json before the migration ran: the switches now go
through skills/get-started/scripts/settings.py, whose first write migrates the old files. Runs in a temp
HOME and SECOND_OPINION_DATA; the venv is pre-seeded (a stub interpreter plus a matching
requirements stamp) so no pip runs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "settings-migrate" / "full"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _scene(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir()
    shutil.copytree(FIXTURE, data)
    stub = data / "venv" / "bin" / "python"
    stub.parent.mkdir(parents=True)
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    shutil.copy(ROOT / "requirements.txt", data / "requirements.installed.txt")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SECOND_OPINION", "FINANCE_ANALYST", "PROFICI", "PYTHON", "SNAPTRADE", "ETRADE", "EDGAR"))}
    env.update(HOME=str(home), SECOND_OPINION_DATA=str(data))
    return data, env


def _install(env: dict[str, str], *flags: str) -> dict:
    r = subprocess.run([NODE, str(ROOT / "install.js"), "--json", "--yes", "--no-smoke", *flags],
                       capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def _show(env: dict[str, str], skill: str) -> dict:
    r = subprocess.run(["python3", str(ROOT / "skills" / skill / "scripts" / "settings.py"), "show"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def _assert_migrated(data: Path, env: dict[str, str]) -> None:
    shown = {r["key"]: r["value"] for g in _show(env, "get-started")["groups"] for r in g["rows"]}
    assert shown["plan.sleeves.PICKS.target"] is None and shown["plan.sleeves.PICKS.weighting"] == "valuation"
    assert shown["plan.sleeves.EMPLOYER.members"] == ["AMZN"] and shown["taxes.short_term_gain_policy"] == "allow"
    saved = json.loads((data / "settings.json").read_text())
    assert saved["schema"] == 2
    assert saved["meta"]["migrated_at"]
    assert saved["plan"]["targets"] == {"VTI": 0.6, "BND": 0.4}
    assert saved["accounts"]["acct-1"]["role"] == "retirement"
    assert saved["guardrails"]["pre_buy_check"] is True  # the fixture's trade-journal extra
    assert (data / "core-satellite.json.migrated").is_file() and not (data / "core-satellite.json").exists()


def test_configure_run_migrates_the_old_files(tmp_path):
    data, env = _scene(tmp_path)
    _install(env, "--configure")
    _assert_migrated(data, env)


def test_guided_rerun_migrates_the_old_files(tmp_path):
    data, env = _scene(tmp_path)
    target = tmp_path / "home" / ".claude" / "plugins" / "second-opinion"
    _install(env, "--no-link", "--target", str(target),
             "--snaptrade-client-id", "id", "--snaptrade-consumer-key", "secret-key-1234")
    _assert_migrated(data, env)
