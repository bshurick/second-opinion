#!/usr/bin/env bash
# UserPromptSubmit hook: print one line when the portfolio was last read on an earlier day
# (`freshness.py`, plain text, no network), so the model refreshes holdings before discussing
# changes to them. Silent when it was read today, when the portfolio-analysis skill is not
# installed, when no usable python is found, or when the script fails; never fails the prompt
# (always exits 0).
set -u

# shellcheck source=common.sh
HOOKS_DIR="${BASH_SOURCE[0]%/*}"; [ "$HOOKS_DIR" = "${BASH_SOURCE[0]}" ] && HOOKS_DIR=.  # no dirname: PATH may be bare
. "$HOOKS_DIR/common.sh"
so_resolve_data_dir
SCRIPT="$PLUGIN_ROOT/skills/portfolio-analysis/scripts/freshness.py"
[ -f "$SCRIPT" ] || exit 0
[ -d "$DATA_DIR" ] || exit 0

so_resolve_python
[ -n "$PY" ] || exit 0

"$PY" "$SCRIPT" 2>/dev/null || true
exit 0
