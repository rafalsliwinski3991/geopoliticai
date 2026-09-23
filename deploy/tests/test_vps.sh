#!/usr/bin/env bash
# Exercises vps.sh against a stub `docker` in a temp root:
# no Docker daemon, no VPS. Run: bash deploy/tests/test_vps.sh
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export VPS_ROOT=$T/root VPS_BACKUPS=$T/backups DOCKER_LOG=$T/docker.log
mkdir -p "$VPS_ROOT" "$T/bin"
: > "$VPS_ROOT/.env"
cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "IMAGE_TAG=${IMAGE_TAG:-} $*" >> "$DOCKER_LOG"
if [ -n "${FAIL_ON:-}" ] && [[ "$*" == *"$FAIL_ON"* ]]; then exit 1; fi
if [[ "$*" == *pg_dump* ]]; then echo "-- dump"; fi
EOF
chmod +x "$T/bin/docker"
export PATH="$T/bin:$PATH"

fail() { echo "FAIL: $*" >&2; exit 1; }
sha() { printf '%040d' "$1"; }
ship() { mkdir -p "$VPS_ROOT/releases/$1"; }
run() { bash "$HERE/../vps.sh" "$@"; }

# Six good releases: the newest five survive, with their snapshots.
for n in 1 2 3 4 5 6; do
  ship "$(sha "$n")"
  run deploy "$(sha "$n")"
  # A leftover snapshot from an earlier, retried attempt of the same release.
  if [ "$n" = 6 ]; then : > "$VPS_BACKUPS/pre-$(sha 6)-19700101T0000Z.sql.gz"; fi
  run finish "$(sha "$n")" > "$T/summary"
done
[ "$(wc -l < "$VPS_ROOT/releases.log")" -eq 5 ] || fail "releases.log not pruned to 5"
[ ! -d "$VPS_ROOT/releases/$(sha 1)" ] || fail "release 1 not pruned"
[ "$(find "$VPS_BACKUPS" -name 'pre-*' | wc -l)" -eq 5 ] || fail "snapshots not pruned to 5"
[ "$(readlink "$VPS_ROOT/current")" = "$VPS_ROOT/releases/$(sha 6)" ] || fail "current is not release 6"
grep -q "target=$(sha 5) confirm=delete-data-since-" "$T/summary" || fail "summary lacks the rollback line"

echo "deploy script tests passed"
