"""The plugin version is bumped in both manifests and has a changelog entry."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_versions_match_and_changelog_has_entry():
    v = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
    m = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"][0]["version"]
    assert v == m == "1.7.0"
    assert f"## {v}" in (ROOT / "CHANGELOG.md").read_text()


def test_check_version_script_passes_with_no_tag(tmp_path):
    repo = tmp_path / "r"
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin/plugin.json").write_text('{"version": "1.0.0"}')
    run = lambda *a: subprocess.run(a, cwd=repo, capture_output=True, text=True)
    run("git", "init", "-q")
    run("git", "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    script = ROOT / "scripts/check-version.sh"
    assert run("bash", str(script)).returncode == 0
    run("git", "tag", "v1.0.0")
    (repo / "lib").mkdir()
    (repo / "lib/a.py").write_text("x")
    run("git", "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "y")
    r = run("bash", str(script))
    assert r.returncode == 1 and "version not bumped since v1.0.0" in r.stdout
