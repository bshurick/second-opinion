#!/usr/bin/env bash
# SessionStart hook: print the watchlist skill's summary of its last stored check
# (`watchlist.py summary`, plain text, no network) so the session opens with it.
# Silent when the watchlist skill is not installed, when no watchlist has been
# saved yet, when no usable python is found, or when the script fails; never
# fails the session (always exits 0).
set -u

# shellcheck source=common.sh
HOOKS_DIR="${BASH_SOURCE[0]%/*}"; [ "$HOOKS_DIR" = "${BASH_SOURCE[0]}" ] && HOOKS_DIR=.  # no dirname: PATH may be bare
. "$HOOKS_DIR/common.sh"
# Same data dir as session-start.sh and the scripts (SECOND_OPINION_DATA, never CLAUDE_PLUGIN_DATA).
so_resolve_data_dir
SCRIPT="$PLUGIN_ROOT/skills/watchlist/scripts/watchlist.py"
[ -f "$SCRIPT" ] || exit 0
[ -f "$DATA_DIR/watchlist.json" ] || exit 0   # a new user has no watchlist: say nothing

# Interpreter, in session-start.sh's order: explicit override, the managed venv, then PATH.
# SessionStart hooks run side by side, so SNAPTRADE_PY from session-start.sh is not visible here.
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*) VENV_PY="$DATA_DIR/venv/Scripts/python.exe" ;;
  *) VENV_PY="$DATA_DIR/venv/bin/python" ;;
esac
PY=""
if so_python_override && [ -x "$SO_PYTHON" ]; then
  PY="$SO_PYTHON"
elif [ -x "$VENV_PY" ]; then
  PY="$VENV_PY"
else
  PY="$(command -v python3 || true)"
fi
[ -n "$PY" ] || exit 0

"$PY" "$SCRIPT" summary 2>/dev/null || true
exit 0
