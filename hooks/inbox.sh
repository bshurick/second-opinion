#!/usr/bin/env bash
# SessionStart hook: print the session inbox (get-started's `inbox.py`, plain text, no network): at most
# six things that need attention (cash or vested shares that arrived, picks due for a re-check,
# new watchlist alerts), each with the sentence that handles it. Silent when there is nothing to
# report, when the script is missing, when no usable python is found, or when the script fails;
# never fails the session (always exits 0).
set -u

# shellcheck source=common.sh
HOOKS_DIR="${BASH_SOURCE[0]%/*}"; [ "$HOOKS_DIR" = "${BASH_SOURCE[0]}" ] && HOOKS_DIR=.  # no dirname: PATH may be bare
. "$HOOKS_DIR/common.sh"
so_resolve_data_dir
SCRIPT="$PLUGIN_ROOT/skills/get-started/scripts/inbox.py"
[ -f "$SCRIPT" ] || exit 0
[ -d "$DATA_DIR" ] || exit 0   # a new user has nothing to report

so_resolve_python
[ -n "$PY" ] || exit 0

"$PY" "$SCRIPT" 2>/dev/null || true
exit 0
