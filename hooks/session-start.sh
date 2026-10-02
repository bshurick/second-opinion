#!/usr/bin/env bash
# SessionStart hook: make sure a venv with the plugin's Python deps exists in
# the persistent plugin data dir, and export SNAPTRADE_PY for skill scripts.
# Never touches secrets. Never fails the session (always exits 0).
set -u

# shellcheck source=common.sh
HOOKS_DIR="${BASH_SOURCE[0]%/*}"; [ "$HOOKS_DIR" = "${BASH_SOURCE[0]}" ] && HOOKS_DIR=.  # no dirname: PATH may be bare
. "$HOOKS_DIR/common.sh"
# Move the pre-rename data dir (~/.claude/plugins/data/finance-analyst) once, unless an override is set.
if [ -z "${SECOND_OPINION_DATA:-}" ] && [ -z "${FINANCE_ANALYST_DATA:-}" ]; then
  so_migrate_data || echo "second-opinion: could not move $SO_OLD_DATA to $SO_NEW_DATA; still reading the old directory" >&2
fi
so_resolve_data_dir
REQ="${SNAPTRADE_REQUIREMENTS:-$PLUGIN_ROOT/requirements.txt}"
ENV_FILE="${CLAUDE_ENV_FILE:-}"
LOG="$DATA_DIR/install.log"

export_line() {
  # %q: a path with a space (or other shell-special character) still sources cleanly
  if [ -n "$ENV_FILE" ]; then
    printf 'export %s=%q\n' "$1" "$2" >> "$ENV_FILE"
  fi
}

# Print one line of profile context to stdout (Claude Code adds hook stdout
# to the session). Silent when the onboarding skill is not installed or no
# usable python is found; never fails the session.
profile_context() {
  local py="$1"
  local script="$PLUGIN_ROOT/skills/onboarding/scripts/profile.py"
  [ -f "$script" ] || return 0
  [ -n "$py" ] && [ -x "$py" ] || return 0
  "$py" "$script" context 2>/dev/null || true
}

# Print the standing rules (hooks/broker-login.md only when an E*Trade key is configured, then
# hooks/follow-ups.md only when that opt-in extra is on) on every exit path, after whatever
# profile context was printed. Editing those files changes the rule for all skills at once.
standing_rules() {
  if so_etrade_configured && [ -f "$PLUGIN_ROOT/hooks/broker-login.md" ]; then
    printf '%s\n' "$(<"$PLUGIN_ROOT/hooks/broker-login.md")"
  fi
  if so_extra_on follow_ups && [ -f "$PLUGIN_ROOT/hooks/follow-ups.md" ]; then
    printf '%s\n' "$(<"$PLUGIN_ROOT/hooks/follow-ups.md")"
  fi
  return 0
}
trap standing_rules EXIT

# 1. Explicit interpreter override (SECOND_OPINION_PYTHON; FINANCE_ANALYST_PYTHON / PROFICI_PYTHON still work).
if so_python_override; then
  if [ -x "$SO_PYTHON" ]; then
    export_line SNAPTRADE_PY "$SO_PYTHON"
    profile_context "$SO_PYTHON"
    exit 0
  fi
  echo "second-opinion: $SO_PYTHON_VAR=$SO_PYTHON is not executable; falling back to a managed venv" >&2
fi

mkdir -p "$DATA_DIR"
export_line SNAPTRADE_INSTALL_LOG "$LOG"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "second-opinion: python3 not found on PATH; install Python 3.10+ (or set SECOND_OPINION_PYTHON)" >&2
  exit 0
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "second-opinion: python3 is older than 3.10; install a newer Python or set SECOND_OPINION_PYTHON" >&2
  exit 0
fi

VENV="$DATA_DIR/venv"
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*) VENV_PY="$VENV/Scripts/python.exe" ;;
  *) VENV_PY="$VENV/bin/python" ;;
esac
STAMP="$DATA_DIR/requirements.installed.txt"

needs_install=0
[ -x "$VENV_PY" ] || needs_install=1
[ -f "$STAMP" ] && cmp -s "$REQ" "$STAMP" || needs_install=1

if [ "$needs_install" = 1 ]; then
  echo "Second Opinion: installing its Python dependencies (first run or requirements changed); log: $LOG"
  {
    echo "== $(date) creating venv at $VENV"
    [ -x "$VENV_PY" ] || "$PY" -m venv "$VENV"
    "$VENV_PY" -m pip install --disable-pip-version-check -q -r "$REQ"
  } >> "$LOG" 2>&1
  if [ $? -eq 0 ]; then
    cp "$REQ" "$STAMP"
  else
    echo "second-opinion: dependency install failed; see $LOG" >&2
  fi
fi

if [ -x "$VENV_PY" ]; then
  export_line SNAPTRADE_PY "$VENV_PY"
  profile_context "$VENV_PY"
else
  profile_context "$PY"
fi
exit 0
