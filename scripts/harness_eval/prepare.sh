#!/usr/bin/env bash
# Build an agent's workspace for the harness eval: the task's start commit
# with only its own history (later commits hold the answer), the current
# harness committed on top, and the one input file the job may see.
#
# Usage: prepare.sh <src-repo> <start-sha> <fixture> <dest> <workspace>
# Prints the overlay commit's SHA, the base the candidate is diffed against.
set -euo pipefail

src=$1 start=$2 fixture=$3 dest=$4 ws=$5
HARNESS=(.claude .opencode .agents .github/prompts AGENTS.md opencode.jsonc
  scripts/log_metrics.py docs/harness_logs/TEMPLATE.md)

# Fetching a ref brings only its ancestors; fetching by SHA from a plain
# repo is refused unless the source allows unadvertised objects. The ref is
# private to this process and removed on exit, so concurrent runs cannot see
# each other's SHA and the source repo's own refs are left as they were.
ref=refs/eval/start-$$
git -C "$src" update-ref "$ref" "$start"
trap 'git -C "$src" update-ref -d "$ref"' EXIT
git init -q "$ws"
git -C "$ws" fetch -q --no-tags "$src" "$ref"
git -C "$ws" checkout -q -b eval-base FETCH_HEAD

for p in "${HARNESS[@]}"; do
  rm -rf "${ws:?}/$p"
  mkdir -p "$(dirname "$ws/$p")"
  cp -a "$src/$p" "$ws/$p"
done
git -C "$ws" add -A
git -C "$ws" -c user.name=harness-eval -c user.email=harness-eval@users.noreply.github.com \
  commit -q --allow-empty -m "eval: overlay the current harness"

# The start commits predate the gitignore line for the run logs; without it
# every ledger and brief would land in the candidate diff.
echo "docs/harness_logs/" >> "$ws/.git/info/exclude"

mkdir -p "$(dirname "$ws/$dest")"
cp "$src/$fixture" "$ws/$dest"
git -C "$ws" rev-parse HEAD
