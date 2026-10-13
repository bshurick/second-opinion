#!/usr/bin/env bash
# SessionStart hook: print which saved picks are due for a re-check (`picks.py summary`, plain
# text, no network): earnings reported since the last check, a 10-Q still awaited, or a 15% price
# move in the watchlist's last check. Silent when the stock-screener skill is not installed, when
# no pick has been saved, when no usable python is found, or when the script fails; never fails
# the session (always exits 0).
set -u

# shellcheck source=common.sh
HOOKS_DIR="${BASH_SOURCE[0]%/*}"; [ "$HOOKS_DIR" = "${BASH_SOURCE[0]}" ] && HOOKS_DIR=.  # no dirname: PATH may be bare
. "$HOOKS_DIR/common.sh"
so_resolve_data_dir
SCRIPT="$PLUGIN_ROOT/skills/stock-screener/scripts/picks.py"
[ -f "$SCRIPT" ] || exit 0
[ -f "$DATA_DIR/picks.json" ] || exit 0   # nothing saved: say nothing

# Interpreter, in session-start.sh's order: explicit override, the managed venv, then PATH.
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
