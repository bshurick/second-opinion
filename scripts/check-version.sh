#!/usr/bin/env bash
# Fails when shipped files changed since the latest v* tag but plugin.json still has that tag's version.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
cd "$root"
tag=$(git tag --list 'v*' --sort=-v:refname | head -n 1)
if [ -z "$tag" ]; then
  echo "no v* tag yet; nothing to check"
  exit 0
fi
paths=(skills lib hooks install.js .claude-plugin)
existing=()
for p in "${paths[@]}"; do [ -e "$p" ] && existing+=("$p"); done
if git diff --quiet "$tag" HEAD -- "${existing[@]}"; then
  exit 0
fi
version=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')
if [ "$version" = "${tag#v}" ]; then
  echo "version not bumped since $tag"
  exit 1
fi
