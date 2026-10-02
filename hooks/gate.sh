#!/usr/bin/env bash
# PreToolUse hook (Bash), two gates:
# 1. Hard order gate: a command that runs the trading skill's place-order.py or cancel-order.py,
#    or the connect skill's disconnect.py, with --confirm always gets permissionDecision "ask",
#    whatever the onboarding state, so a human approves every real order, cancel and disconnect
#    even when Claude Code would otherwise run the command without asking.
# 2. First-use gate: until onboarding has run or been skipped (profile.json exists), block runs
#    of this plugin's own analysis scripts with one sentence telling Claude what to do. Never
#    blocks when the onboarding skill itself is not installed.
# In bypassPermissions mode gate 1 blocks (exit 2) instead of asking. Passes everything else; exits 0
# except for those deliberate blocks.
set -u

# shellcheck source=common.sh
HOOKS_DIR="${BASH_SOURCE[0]%/*}"; [ "$HOOKS_DIR" = "${BASH_SOURCE[0]}" ] && HOOKS_DIR=.  # no dirname: PATH may be bare
. "$HOOKS_DIR/common.sh"
so_resolve_data_dir

input="$(cat 2>/dev/null || true)"
[ -n "$input" ] || exit 0

# 1. Orders, cancels and disconnects that would act now. Fails safe: any command naming one of
#    these scripts and --confirm asks, even if --confirm belongs to another part of the command.
if printf '%s' "$input" | grep -qE 'skills/(trading/scripts/(place|cancel)-order|connect/scripts/disconnect)\.py' \
  && printf '%s' "$input" | grep -qE -- '--confirm([^A-Za-z0-9_-]|$)'; then
  what="place or cancel a real brokerage order"
  printf '%s' "$input" | grep -qE 'skills/connect/scripts/disconnect\.py' && what="disconnect a brokerage connection"
  # bypassPermissions may auto-approve an "ask", so there the only safe answer is a block.
  if printf '%s' "$input" | grep -qE '"permission_mode"[[:space:]]*:[[:space:]]*"bypassPermissions"'; then
    echo "Second Opinion: this command would $what, and this session is in bypass-permissions mode, where a hook cannot make Claude Code ask the user. Nothing was run. Show the preview, ask the user to confirm, and tell them to rerun it from a session that is not in bypass mode." >&2
    exit 2
  fi
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"Second Opinion: this command will %s. Approve only if it matches what you asked for."}}\n' "$what"
  exit 0
fi

# 2. Cheap filter: does the command run skills/<name>/scripts/<file>.py?
# The . in [A-Za-z0-9_.-] allows dotted filenames; trailing \.py anchors at first .py.
# First matched path decides: an exempt script named earlier in a pipeline exempts the whole command (the gate is a backstop, and every miss fails open).
skill="$(printf '%s' "$input" | grep -oE 'skills/[a-z0-9-]+/scripts/[A-Za-z0-9_.-]+\.py' | head -n1 | cut -d/ -f2)"
[ -n "$skill" ] || exit 0
[ -d "$PLUGIN_ROOT/skills/$skill" ] || exit 0          # not one of ours
[ -d "$PLUGIN_ROOT/skills/onboarding" ] || exit 0      # onboarding not installed: never gate
case "$skill" in
  onboarding|setup) exit 0 ;;
esac
[ -f "$DATA_DIR/profile.json" ] && exit 0

echo "Second Opinion onboarding has not run, so ask the onboarding skill's six questions (the user can say 'get started with Second Opinion') or record 'skip for now' with profile.py skip, then retry this command." >&2
exit 2
