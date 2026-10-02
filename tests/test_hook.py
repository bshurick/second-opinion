from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_ROOT / "hooks" / "session-start.sh"


_OVERRIDES = ("SECOND_OPINION_PYTHON", "FINANCE_ANALYST_PYTHON", "PROFICI_PYTHON", "FINANCE_ANALYST_DATA", "ETRADE_CONSUMER_KEY", "CLAUDE_PLUGIN_DATA")


def _base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _OVERRIDES}


def _run(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess, Path]:
    env_file = tmp_path / "env.sh"
    base = _base_env()
    full = {**base, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "SECOND_OPINION_DATA": str(tmp_path / "data"), "CLAUDE_ENV_FILE": str(env_file), **env}
    return subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=full, timeout=300), env_file


def test_hook_json_points_at_script() -> None:
    import json

    data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    entry = data["hooks"]["SessionStart"][0]["hooks"][0]
    assert entry["type"] == "command" and entry["command"] == "bash" and entry["args"] == ["${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"]
    assert entry["timeout"] == 300


WATCHLIST_HOOK = PLUGIN_ROOT / "hooks" / "watchlist-summary.sh"


def test_hook_json_registers_the_watchlist_summary() -> None:
    import json

    data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    hooks = data["hooks"]["SessionStart"][0]["hooks"]
    assert [h["args"][0].rsplit("/", 1)[1] for h in hooks] == ["session-start.sh", "watchlist-summary.sh"]
    assert hooks[1] == {"type": "command", "command": "bash", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/watchlist-summary.sh"], "timeout": 15}


def _run_watchlist_hook(tmp_path: Path, root: Path, **env: str) -> subprocess.CompletedProcess:
    full = {**_base_env(), "CLAUDE_PLUGIN_ROOT": str(root), "SECOND_OPINION_DATA": str(tmp_path / "data"), **env}
    return subprocess.run(["bash", str(WATCHLIST_HOOK)], capture_output=True, text=True, env=full, timeout=60)


def _stub_watchlist(root: Path, body: str, *, saved: bool = True) -> None:
    script = root / "skills" / "watchlist" / "scripts" / "watchlist.py"
    script.parent.mkdir(parents=True)
    script.write_text(body)
    if saved:  # the hook stays silent until the user has saved a watchlist
        data = root.parent / "data"
        data.mkdir(exist_ok=True)
        (data / "watchlist.json").write_text("{}")


def test_watchlist_summary_hook_is_silent_without_a_saved_watchlist(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _stub_watchlist(root, "print('Watchlist: nothing saved')\n", saved=False)
    proc = _run_watchlist_hook(tmp_path, root, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""


def test_watchlist_summary_hook_prints_the_stored_summary(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _stub_watchlist(root, "import sys\nassert sys.argv[1:] == ['summary'], sys.argv\nprint('Watchlist: 2 of 5 rules triggered')\n")
    proc = _run_watchlist_hook(tmp_path, root, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "Watchlist: 2 of 5 rules triggered" and proc.stderr == ""


def test_watchlist_summary_hook_is_silent_without_the_skill(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "skills").mkdir(parents=True)
    proc = _run_watchlist_hook(tmp_path, root, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""


def test_watchlist_summary_hook_never_fails_the_session(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _stub_watchlist(root, "import sys\nprint('boom', file=sys.stderr)\nsys.exit(4)\n")
    proc = _run_watchlist_hook(tmp_path, root, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""  # the script's stderr is swallowed


def test_watchlist_summary_hook_prefers_the_managed_venv(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _stub_watchlist(root, "raise SystemExit('the real python3 must not run')\n")
    # a stand-in for <data>/venv/bin/python: the hook must call this one, with the script and "summary"
    venv_py = tmp_path / "data" / "venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/usr/bin/env bash\nprintf 'venv-python %s %s\\n' \"$(basename \"$1\")\" \"$2\"\n")
    venv_py.chmod(0o755)
    proc = _run_watchlist_hook(tmp_path, root)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "venv-python watchlist.py summary"


@pytest.mark.parametrize("var", ["SECOND_OPINION_PYTHON", "FINANCE_ANALYST_PYTHON", "PROFICI_PYTHON"])
def test_python_override_skips_venv(tmp_path: Path, var: str) -> None:
    proc, env_file = _run(tmp_path, **{var: sys.executable})
    assert proc.returncode == 0, proc.stderr
    assert f"export SNAPTRADE_PY={sys.executable}" in env_file.read_text()
    assert not (tmp_path / "data" / "venv").exists()


def test_first_install_prints_one_line_with_the_log(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("")
    proc, _ = _run(tmp_path, SNAPTRADE_REQUIREMENTS=str(req))
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if "installing its Python dependencies" in line]
    assert len(lines) == 1 and str(tmp_path / "data" / "install.log") in lines[0]
    proc2, _ = _run(tmp_path, SNAPTRADE_REQUIREMENTS=str(req))
    assert "installing its Python dependencies" not in proc2.stdout


def test_venv_created_once_and_reused(tmp_path: Path) -> None:
    req = tmp_path / "requirements.txt"
    req.write_text("")  # empty: offline-safe
    proc, env_file = _run(tmp_path, SNAPTRADE_REQUIREMENTS=str(req))
    assert proc.returncode == 0, proc.stderr
    venv_py = tmp_path / "data" / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert venv_py.exists()
    text = env_file.read_text()
    assert f"export SNAPTRADE_PY={venv_py}" in text and "export SNAPTRADE_INSTALL_LOG=" in text
    assert "No Second Opinion profile exists" in proc.stdout
    stamp = tmp_path / "data" / "requirements.installed.txt"
    first = stamp.stat().st_mtime_ns
    proc2, _ = _run(tmp_path, SNAPTRADE_REQUIREMENTS=str(req))
    assert proc2.returncode == 0 and stamp.stat().st_mtime_ns == first


def test_hook_never_fails_session_when_python_missing(tmp_path: Path) -> None:
    # subprocess.run(["bash", ...]) resolves "bash" itself via
    # os.get_exec_path(env) (see CPython subprocess.Popen._execute_child),
    # i.e. via the PATH we pass in `env`, not the calling process's real
    # PATH. So an empty-directory PATH hides bash itself, not just python3,
    # and the hook never even starts. Give PATH a single directory that
    # contains nothing but a symlink to the real bash, so bash still
    # launches while python3 (and every other tool) stays unreachable.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_bash = os.environ.get("BASH") or subprocess.run(
        ["command", "-v", "bash"], shell=True, capture_output=True, text=True
    ).stdout.strip() or "/bin/bash"
    (bin_dir / "bash").symlink_to(real_bash)
    proc, env_file = _run(tmp_path, PATH=str(bin_dir))  # no python3 on PATH
    assert proc.returncode == 0
    assert "python3" in proc.stderr.lower()


def test_session_start_prints_no_profile_line(tmp_path: Path) -> None:
    proc, _ = _run(tmp_path, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0, proc.stderr
    assert "No Second Opinion profile exists" in proc.stdout
    assert "first finance request" in proc.stdout


def test_session_start_prints_profile_summary(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    import json as _json

    data.joinpath("profile.json").write_text(_json.dumps({
        "version": 1, "created": "2026-09-10", "updated": "2026-09-10", "learning": True,
        "onboarding": {"status": "complete", "at": "2026-09-10", "version": 1},
        "fields": {"horizon": {"value": "years", "source": "declared", "at": "2026-09-10"}},
        "proposals": [], "declined": [],
    }))
    proc, _ = _run(tmp_path, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().startswith("Second Opinion profile (declared 2026-09-10): horizon years")


def test_session_start_survives_corrupt_profile(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    data.joinpath("profile.json").write_text("{broken")
    proc, _ = _run(tmp_path, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0
    # context now guards both load() and rendering, so invalid JSON reads as
    # "could not be read" rather than "no profile exists".
    assert "could not be read" in proc.stdout


def test_session_start_survives_malformed_field_entry(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    import json as _json

    data.joinpath("profile.json").write_text(_json.dumps({
        "version": 1, "created": "2026-09-10", "updated": "2026-09-10", "learning": True,
        "onboarding": {"status": "complete", "at": "2026-09-10", "version": 1},
        "fields": {"horizon": {"source": "declared", "at": "2026-09-10"}},
        "proposals": [], "declined": [],
    }))
    proc, _ = _run(tmp_path, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0
    lines = [line for line in proc.stdout.splitlines() if line]
    assert "could not be read" in lines[0]
    assert sum("profile" in line.lower() and "could not be read" in line for line in lines) == 1


FOLLOW_UPS = PLUGIN_ROOT / "hooks" / "follow-ups.md"


def _turn_on_follow_ups(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "installed.json").write_text('{"skills": [], "extras": {"follow_ups": true}}')


def test_new_user_session_start_is_quiet(tmp_path: Path) -> None:
    """No record, no E*Trade key: no follow-ups rule and no broker-login rule, only the profile line."""
    proc, _ = _run(tmp_path, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0, proc.stderr
    assert "Next you could ask:" not in proc.stdout and "ETRADE_REAUTH" not in proc.stdout
    assert [line for line in proc.stdout.splitlines() if line.strip()] == [proc.stdout.strip()]


def test_session_start_prints_follow_ups_rule(tmp_path: Path) -> None:
    _turn_on_follow_ups(tmp_path)
    proc, _ = _run(tmp_path, SECOND_OPINION_PYTHON=sys.executable)
    assert proc.returncode == 0, proc.stderr
    assert "Next you could ask:" in proc.stdout
    assert proc.stdout.rstrip().endswith(FOLLOW_UPS.read_text().rstrip())
    assert proc.stdout.count("Next you could ask:") == FOLLOW_UPS.read_text().count("Next you could ask:")


def test_follow_ups_rule_printed_even_without_python(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_bash = os.environ.get("BASH") or subprocess.run(
        ["command", "-v", "bash"], shell=True, capture_output=True, text=True
    ).stdout.strip() or "/bin/bash"
    (bin_dir / "bash").symlink_to(real_bash)
    _turn_on_follow_ups(tmp_path)
    proc, _ = _run(tmp_path, PATH=str(bin_dir))
    assert proc.returncode == 0
    assert "Next you could ask:" in proc.stdout


def test_follow_ups_rule_wording() -> None:
    text = FOLLOW_UPS.read_text()
    assert "Should I buy" in text  # the counter-example must be present so the model sees what to avoid
    for banned in ("recommend", "advise"):
        assert banned not in text.lower(), f"follow-ups rule must not use '{banned}'"


@pytest.mark.parametrize(
    ("record", "shown"),
    [
        (None, False),  # a marketplace install before setup, or a checkout: extras are opt-in
        ('{"skills": [], "extras": {"follow_ups": true}}', True),
        ('{"skills": [], "extras": {"follow_ups": false}}', False),
        ('{\n "skills": [],\n "extras": {\n  "follow_ups" : true\n }\n}', True),  # pretty-printed, spaced
        ('{"skills": []}', False),  # a record written before extras existed
        ("not json", False),
    ],
)
@pytest.mark.parametrize("where", ["root", "data"])
def test_follow_ups_rule_follows_the_extras_record(tmp_path: Path, record: str | None, shown: bool, where: str) -> None:
    root = tmp_path / "root"
    shutil.copytree(PLUGIN_ROOT / "hooks", root / "hooks")
    shutil.copy(PLUGIN_ROOT / "requirements.txt", root / "requirements.txt")
    (tmp_path / "data").mkdir()
    if record is not None:
        (root / "installed.json" if where == "root" else tmp_path / "data" / "installed.json").write_text(record)
    env = {**_base_env(), "CLAUDE_PLUGIN_ROOT": str(root), "SECOND_OPINION_DATA": str(tmp_path / "data"), "CLAUDE_ENV_FILE": str(tmp_path / "env.sh"), "SECOND_OPINION_PYTHON": sys.executable, "ETRADE_CONSUMER_KEY": "k"}
    proc = subprocess.run(["bash", str(root / "hooks" / "session-start.sh")], capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert ("Next you could ask:" in proc.stdout) is shown
    assert BROKER_LOGIN.read_text().rstrip() in proc.stdout  # the login rule follows the E*Trade key, not the extras


BROKER_LOGIN = PLUGIN_ROOT / "hooks" / "broker-login.md"


def test_session_start_prints_broker_login_rule(tmp_path: Path) -> None:
    _turn_on_follow_ups(tmp_path)
    proc, _ = _run(tmp_path, SECOND_OPINION_PYTHON=sys.executable, ETRADE_CONSUMER_KEY="k")
    assert proc.returncode == 0, proc.stderr
    text = BROKER_LOGIN.read_text().rstrip()
    assert text in proc.stdout
    assert proc.stdout.index(text) < proc.stdout.index("Next you could ask:")  # login rule, then follow-ups


@pytest.mark.parametrize(
    ("where", "line", "shown"),
    [
        ("data", "ETRADE_CONSUMER_KEY=abc", True),
        ("data", "export ETRADE_CONSUMER_KEY = 'abc'", True),
        ("root", "ETRADE_CONSUMER_KEY=abc", True),
        ("data", "ETRADE_CONSUMER_KEY=", False),
        ("data", 'ETRADE_CONSUMER_KEY=""', False),
        ("data", "# ETRADE_CONSUMER_KEY=abc", False),
        ("data", "SNAPTRADE_CLIENT_ID=abc", False),
    ],
)
def test_broker_login_rule_only_with_an_etrade_key(tmp_path: Path, where: str, line: str, shown: bool) -> None:
    root = tmp_path / "root"
    shutil.copytree(PLUGIN_ROOT / "hooks", root / "hooks")
    shutil.copy(PLUGIN_ROOT / "requirements.txt", root / "requirements.txt")
    (tmp_path / "data").mkdir()
    (root / ".env" if where == "root" else tmp_path / "data" / ".env").write_text(line + "\n")
    env = {**_base_env(), "CLAUDE_PLUGIN_ROOT": str(root), "SECOND_OPINION_DATA": str(tmp_path / "data"), "CLAUDE_ENV_FILE": str(tmp_path / "env.sh"), "SECOND_OPINION_PYTHON": sys.executable}
    proc = subprocess.run(["bash", str(root / "hooks" / "session-start.sh")], capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert ("ETRADE_REAUTH" in proc.stdout) is shown


def _home_env(home: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in _base_env().items() if k != "SECOND_OPINION_DATA"}
    return {**env, "HOME": str(home), "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "CLAUDE_ENV_FILE": str(home / "env.sh"), "SECOND_OPINION_PYTHON": sys.executable, **extra}


def test_session_start_moves_the_pre_rename_data_dir(tmp_path: Path) -> None:
    base = tmp_path / ".claude" / "plugins" / "data"
    (base / "finance-analyst").mkdir(parents=True)
    (base / "finance-analyst" / "journal.json").write_text('{"entries": []}')
    proc = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=_home_env(tmp_path), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert (base / "second-opinion" / "journal.json").read_text() == '{"entries": []}'
    assert not (base / "finance-analyst").exists()
    proc2 = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=_home_env(tmp_path), timeout=60)
    assert proc2.returncode == 0 and (base / "second-opinion" / "journal.json").exists()  # idempotent


def test_migration_never_overwrites_a_real_new_dir(tmp_path: Path) -> None:
    base = tmp_path / ".claude" / "plugins" / "data"
    (base / "finance-analyst").mkdir(parents=True)
    (base / "finance-analyst" / "journal.json").write_text("old")
    (base / "second-opinion").mkdir()
    (base / "second-opinion" / "journal.json").write_text("new")
    proc = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=_home_env(tmp_path), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert (base / "second-opinion" / "journal.json").read_text() == "new"
    assert (base / "finance-analyst" / "journal.json").read_text() == "old"  # never deleted


def test_migration_merges_into_a_cache_only_new_dir(tmp_path: Path) -> None:
    base = tmp_path / ".claude" / "plugins" / "data"
    (base / "finance-analyst" / "edgar-cache").mkdir(parents=True)
    (base / "finance-analyst" / "edgar-cache" / "x.json").write_text("old cache")
    (base / "finance-analyst" / "profile.json").write_text("{}")
    (base / "second-opinion" / "edgar-cache").mkdir(parents=True)
    proc = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=_home_env(tmp_path), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert (base / "second-opinion" / "profile.json").exists()
    assert (base / "finance-analyst" / "edgar-cache" / "x.json").read_text() == "old cache"  # the clash stays put


def test_migration_is_skipped_with_an_explicit_data_dir(tmp_path: Path) -> None:
    base = tmp_path / ".claude" / "plugins" / "data"
    (base / "finance-analyst").mkdir(parents=True)
    proc = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=_home_env(tmp_path, SECOND_OPINION_DATA=str(tmp_path / "elsewhere")), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert (base / "finance-analyst").is_dir() and not (base / "second-opinion").exists()


def test_broker_login_rule_wording() -> None:
    text = BROKER_LOGIN.read_text()
    for needed in ("ETRADE_REAUTH", "--partial", "etrade-login.py --verifier", "url"):
        assert needed in text
    for banned in ("recommend", "advise"):
        assert banned not in text.lower(), f"broker-login rule must not use '{banned}'"
