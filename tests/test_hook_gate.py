"""hooks/gate.sh: block the plugin's analysis scripts until onboarding ran or was skipped."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GATE = PLUGIN_ROOT / "hooks" / "gate.sh"
PY = '"${SNAPTRADE_PY:-python3}"'


def run(tmp_path: Path, command: str | None, *, root: Path = PLUGIN_ROOT, raw: str | None = None, **extra: str) -> subprocess.CompletedProcess:
    payload = raw if raw is not None else json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_DATA"}
    env.update({"CLAUDE_PLUGIN_ROOT": str(root), "SECOND_OPINION_DATA": str(tmp_path / "data"), **extra})
    return subprocess.run(["bash", str(GATE)], input=payload, capture_output=True, text=True, env=env, timeout=30)


def test_hooks_json_registers_the_gate() -> None:
    data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    entry = data["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    hook = entry["hooks"][0]
    assert hook == {"type": "command", "command": "bash", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/gate.sh"], "timeout": 5}


def test_blocks_analysis_script_without_profile(tmp_path: Path) -> None:
    proc = run(tmp_path, f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/valuation/scripts/inputs.py" KO')
    assert proc.returncode == 2
    assert "onboarding has not run" in proc.stderr and "skip for now" in proc.stderr
    assert proc.stdout == ""


@pytest.mark.parametrize("skill", ["onboarding", "setup"])
def test_exempt_skills_pass_without_profile(tmp_path: Path, skill: str) -> None:
    proc = run(tmp_path, f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/{skill}/scripts/profile.py" show')
    assert proc.returncode == 0 and proc.stderr == ""


def test_passes_once_profile_exists(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "profile.json").write_text("{}")
    proc = run(tmp_path, f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/valuation/scripts/inputs.py" KO')
    assert proc.returncode == 0 and proc.stderr == ""


def test_ignores_host_injected_claude_plugin_data(tmp_path: Path) -> None:
    """Claude Code sets CLAUDE_PLUGIN_DATA per load path (e.g. .../second-opinion-skills-dir) in hook
    processes only; the scripts never see it. The gate must read the same directory the scripts use."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "profile.json").write_text("{}")
    (tmp_path / "host").mkdir()
    proc = run(tmp_path, f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/valuation/scripts/inputs.py" KO', CLAUDE_PLUGIN_DATA=str(tmp_path / "host"))
    assert proc.returncode == 0 and proc.stderr == ""


def test_ignores_commands_that_are_not_plugin_scripts(tmp_path: Path) -> None:
    for cmd in ("git status", "ls skills/", "python3 other-plugin/skills/foo/scripts/bar.py"):
        proc = run(tmp_path, cmd)
        assert proc.returncode == 0, cmd


def test_ignores_scripts_of_skills_that_do_not_exist(tmp_path: Path) -> None:
    proc = run(tmp_path, f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/nonexistent/scripts/x.py"')
    assert proc.returncode == 0


def test_passes_when_onboarding_skill_is_not_installed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "skills" / "valuation" / "scripts").mkdir(parents=True)
    proc = run(tmp_path, f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/valuation/scripts/inputs.py" KO', root=root)
    assert proc.returncode == 0


def test_survives_malformed_or_empty_stdin(tmp_path: Path) -> None:
    assert run(tmp_path, None, raw="").returncode == 0
    assert run(tmp_path, None, raw="not json {").returncode == 0


def test_matches_path_adjacent_to_json_escaped_quote(tmp_path: Path) -> None:
    raw = '{"tool_name":"Bash","tool_input":{"command":"\\"$SNAPTRADE_PY\\" \\"$CLAUDE_PLUGIN_ROOT/skills/valuation/scripts/inputs.py\\" KO"}}'
    proc = run(tmp_path, None, raw=raw)
    assert proc.returncode == 2
    assert "onboarding has not run" in proc.stderr and "skip for now" in proc.stderr


ORDER_COMMANDS = [
    f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/trading/scripts/place-order.py" ACC AAPL BUY 1 --limit 100 --confirm',
    f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/trading/scripts/cancel-order.py" ACC 123 --confirm',
    f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/connect/scripts/disconnect.py" conn-1 --confirm',
    f'cd /tmp && {PY} /x/skills/trading/scripts/place-order.py ACC AAPL SELL 2 --confirm 2>&1 | tail -5',
]


def _decision(proc: subprocess.CompletedProcess) -> dict:
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


@pytest.mark.parametrize("command", ORDER_COMMANDS)
def test_confirmed_orders_always_ask_the_human(tmp_path: Path, command: str) -> None:
    out = _decision(run(tmp_path, command))
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "ask"
    assert out["permissionDecisionReason"].startswith("Second Opinion: this command will ")


@pytest.mark.parametrize("command", ORDER_COMMANDS[:3])
def test_confirmed_orders_ask_even_after_onboarding(tmp_path: Path, command: str) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "profile.json").write_text("{}")
    assert _decision(run(tmp_path, command))["permissionDecision"] == "ask"


def test_disconnect_reason_names_the_disconnect(tmp_path: Path) -> None:
    assert "disconnect a brokerage connection" in _decision(run(tmp_path, ORDER_COMMANDS[2]))["permissionDecisionReason"]
    assert "real brokerage order" in _decision(run(tmp_path, ORDER_COMMANDS[0]))["permissionDecisionReason"]


def test_ask_output_is_valid_json_through_escaped_quotes(tmp_path: Path) -> None:
    raw = '{"tool_name":"Bash","tool_input":{"command":"\\"$SNAPTRADE_PY\\" \\"$CLAUDE_PLUGIN_ROOT/skills/trading/scripts/place-order.py\\" A B BUY 1 --confirm"}}'
    assert _decision(run(tmp_path, None, raw=raw))["permissionDecision"] == "ask"


@pytest.mark.parametrize(
    "command",
    [
        f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/trading/scripts/place-order.py" ACC AAPL BUY 1 --limit 100',  # a preview: exits 3
        f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/trading/scripts/preview-order.py" ACC AAPL BUY 1 --confirm-later',
        f'{PY} "${{CLAUDE_PLUGIN_ROOT}}/skills/trading/scripts/orders.py" ACC',
    ],
)
def test_previews_and_reads_do_not_ask(tmp_path: Path, command: str) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "profile.json").write_text("{}")
    proc = run(tmp_path, command)
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""


@pytest.mark.parametrize("command", ORDER_COMMANDS)
def test_confirmed_orders_are_blocked_in_bypass_permissions_mode(tmp_path: Path, command: str) -> None:
    """bypassPermissions may auto-approve a hook's "ask", so there the gate denies outright."""
    raw = json.dumps({"tool_name": "Bash", "permission_mode": "bypassPermissions", "tool_input": {"command": command}})
    proc = run(tmp_path, None, raw=raw)
    assert proc.returncode == 2 and proc.stdout == ""
    assert "bypass" in proc.stderr and "ask the user" in proc.stderr


def test_other_permission_modes_still_ask(tmp_path: Path) -> None:
    raw = json.dumps({"tool_name": "Bash", "permission_mode": "acceptEdits", "tool_input": {"command": ORDER_COMMANDS[0]}})
    assert _decision(run(tmp_path, None, raw=raw))["permissionDecision"] == "ask"
