# Shared helpers for the plugin's hooks; sourced, never run. bash builtins only where it
# matters (PATH may lack coreutils and python when a hook runs). Every function returns 0/1
# and never exits, so a hook keeps its "always exit 0" contract.

# HOOKS_DIR is set by the sourcing hook (the directory holding this file).
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${HOOKS_DIR:-.}/.." && pwd)}"
SO_DATA_BASE="$HOME/.claude/plugins/data"
SO_NEW_DATA="$SO_DATA_BASE/second-opinion"
SO_OLD_DATA="$SO_DATA_BASE/finance-analyst"   # the plugin's data dir before it was renamed

# True when a directory holds nothing but regenerable caches (*-cache, *-cache.json), or nothing.
so_cache_only() {
  local entry name
  for entry in "$1"/* "$1"/.[!.]*; do
    [ -e "$entry" ] || continue
    name="${entry##*/}"
    case "$name" in
      *-cache|*-cache.json|.DS_Store) ;;
      *) return 1 ;;
    esac
  done
  return 0
}

# One-time move of the pre-rename data dir. Idempotent; never overwrites and never deletes:
# - new dir absent: rename old -> new.
# - new dir holds only caches (a script ran before the move): move each old entry that the new
#   dir lacks, then remove the old dir only if that left it empty.
so_migrate_data() {
  [ -d "$SO_OLD_DATA" ] || return 0
  if [ ! -e "$SO_NEW_DATA" ]; then
    mkdir -p "$SO_DATA_BASE" 2>/dev/null
    mv "$SO_OLD_DATA" "$SO_NEW_DATA" 2>/dev/null && return 0
    return 1
  fi
  [ -d "$SO_NEW_DATA" ] && so_cache_only "$SO_NEW_DATA" || return 0
  local entry name
  for entry in "$SO_OLD_DATA"/* "$SO_OLD_DATA"/.[!.]*; do
    [ -e "$entry" ] || continue
    name="${entry##*/}"
    [ -e "$SO_NEW_DATA/$name" ] || mv "$entry" "$SO_NEW_DATA/$name" 2>/dev/null
  done
  rmdir "$SO_OLD_DATA" 2>/dev/null
  return 0
}

# Sets DATA_DIR. SECOND_OPINION_DATA (or the older FINANCE_ANALYST_DATA), never CLAUDE_PLUGIN_DATA:
# Claude Code sets that only in hook processes and names it after the load path, so the scripts
# would never see it. Without an override and before migration, reads through to the old dir.
so_resolve_data_dir() {
  if [ -n "${SECOND_OPINION_DATA:-}" ]; then
    DATA_DIR="$SECOND_OPINION_DATA"
  elif [ -n "${FINANCE_ANALYST_DATA:-}" ]; then
    DATA_DIR="$FINANCE_ANALYST_DATA"
  elif [ -d "$SO_OLD_DATA" ] && { [ ! -e "$SO_NEW_DATA" ] || { [ -d "$SO_NEW_DATA" ] && so_cache_only "$SO_NEW_DATA"; }; }; then
    DATA_DIR="$SO_OLD_DATA"
  else
    DATA_DIR="$SO_NEW_DATA"
  fi
}

# Sets SO_PYTHON to the explicit interpreter override, if any: SECOND_OPINION_PYTHON, then the
# older FINANCE_ANALYST_PYTHON / PROFICI_PYTHON. SO_PYTHON_VAR names the variable it came from.
so_python_override() {
  SO_PYTHON="" SO_PYTHON_VAR=""
  local var
  for var in SECOND_OPINION_PYTHON FINANCE_ANALYST_PYTHON PROFICI_PYTHON; do
    if [ -n "${!var:-}" ]; then
      SO_PYTHON="${!var}" SO_PYTHON_VAR="$var"
      return 0
    fi
  done
  return 1
}

# Sets SO_RECORD to the installer's record: <data dir>/installed.json, else the plugin root's copy.
so_record() {
  SO_RECORD=""
  local rec
  for rec in "$DATA_DIR/installed.json" "$PLUGIN_ROOT/installed.json"; do
    if [ -f "$rec" ]; then
      SO_RECORD="$rec"
      return 0
    fi
  done
  return 1
}

# Optional extras are opt-in: on only when the record says "<key>": true. No record, a record
# from before extras, or anything unreadable means off.
so_extra_on() {
  so_record || return 1
  local text
  text="$(<"$SO_RECORD")" 2>/dev/null || return 1
  [[ "$text" =~ \"$1\"[[:space:]]*:[[:space:]]*true ]]
}

# True when an E*Trade key is configured: the process env, the data dir's .env, or the plugin root's.
so_etrade_configured() {
  [ -n "${ETRADE_CONSUMER_KEY:-}" ] && return 0
  local file line value
  for file in "$DATA_DIR/.env" "$PLUGIN_ROOT/.env"; do
    [ -f "$file" ] || continue
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line#"${line%%[![:space:]]*}"}"
      line="${line#export }"
      line="${line#"${line%%[![:space:]]*}"}"
      case "$line" in
        ETRADE_CONSUMER_KEY=*|ETRADE_CONSUMER_KEY[[:space:]]*=*)
          value="${line#*=}"
          value="${value//[[:space:]\"\']/}"
          [ -n "$value" ] && return 0
          ;;
      esac
    done < "$file"
  done
  return 1
}
