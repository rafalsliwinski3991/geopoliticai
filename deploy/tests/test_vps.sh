#!/usr/bin/env bash
# Exercises vps.py against a stub `docker` in a temp root:
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
# Only the snapshot load and the S3 upload read stdin; `psql -c` calls do not.
if [[ ( "$*" == *psql* && "$*" != *" -c "* ) || "$*" == *"s3 cp"* ]]; then cat > /dev/null; fi
if [ -n "${FAIL_ON:-}" ] && [[ "$*" == *"$FAIL_ON"* ]]; then exit 1; fi
if [[ "$*" == *pg_dump* ]]; then echo "-- dump"; fi
if [[ "$*" == *pg_sequences* ]]; then echo 7; fi
if [[ "$*" == *"images --format"* ]]; then
  printf '%s\n' \
    "ghcr.io/rafalsliwinski3991/geopoliticai-frontend:$(printf '%040d' 0)" \
    "ghcr.io/rafalsliwinski3991/geopoliticai-frontend:latest"
fi
EOF
chmod +x "$T/bin/docker"
export PATH="$T/bin:$PATH"

fail() { echo "FAIL: $*" >&2; exit 1; }
sha() { printf '%040d' "$1"; }
ship() { mkdir -p "$VPS_ROOT/releases/$1"; }
run() { python3 "$HERE/../vps.py" "$@"; }

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

# Pruning also drops the :<sha> image tags of unrecorded releases, and never
# the :latest tag a rollback may need.
grep -q "image rm ghcr.io/rafalsliwinski3991/geopoliticai-frontend:$(printf '%040d' 0)" \
  "$DOCKER_LOG" || fail "stale image tag not pruned"
if grep -q "image rm.*latest" "$DOCKER_LOG"; then fail "pruned the latest tag"; fi

# A failed pg_dump leaves no snapshot behind to be trusted.
: > "$DOCKER_LOG"
ship "$(sha 7)"
if FAIL_ON=pg_dump run deploy "$(sha 7)"; then fail "deploy should fail on a failed pg_dump"; fi
[ "$(find "$VPS_BACKUPS" -name 'pre-*' | wc -l)" -eq 5 ] || fail "a failed pg_dump left a snapshot"
[ ! -e "$VPS_ROOT/releases/$(sha 7)/.snapshot" ] || fail "marker written for a failed dump"

# A failed migration: abort restores the snapshot and restarts release 6.
: > "$DOCKER_LOG"
ship "$(sha 7)"
if FAIL_ON="alembic upgrade" run deploy "$(sha 7)"; then fail "deploy should fail"; fi
run abort "$(sha 7)"
grep -q 'RENAME TO geopoliticai_failed' "$DOCKER_LOG" || fail "abort did not restore the snapshot"
grep -q "IMAGE_TAG=$(sha 6) .* up -d --no-build --wait" "$DOCKER_LOG" || fail "release 6 not restarted"
setval="setval(pg_get_serial_sequence('users_user', 'id'), 7)"
grep -qF "$setval" "$DOCKER_LOG" || fail "users id sequence not moved past the replaced database"
[ "$(tail -n 1 "$VPS_ROOT/releases.log")" = "$(sha 6)" ] || fail "failed release was recorded"

# A failure before the snapshot: abort must not restore anything.
: > "$DOCKER_LOG"
ship "$(sha 8)"
if FAIL_ON=" pull" run deploy "$(sha 8)"; then fail "deploy should fail"; fi
run abort "$(sha 8)"
if grep -q 'RENAME TO geopoliticai_failed' "$DOCKER_LOG"; then fail "restored without a fresh snapshot"; fi

# Manual rollback: a wrong confirmation changes nothing; the right one goes back.
: > "$DOCKER_LOG"
if run rollback "$(sha 5)" delete-data-since-19700101T0000Z 2>/dev/null; then fail "accepted a wrong confirmation"; fi
if grep -q 'RENAME TO geopoliticai_failed' "$DOCKER_LOG"; then fail "restored on a wrong confirmation"; fi
confirm=$(grep -o 'delete-data-since-[0-9TZ]*' "$T/summary")
run rollback "$(sha 5)" "$confirm"
grep -q 'RENAME TO geopoliticai_failed' "$DOCKER_LOG" || fail "rollback did not restore"
[ "$(tail -n 1 "$VPS_ROOT/releases.log")" = "$(sha 5)" ] || fail "releases.log not cut back to 5"
[ "$(readlink "$VPS_ROOT/current")" = "$VPS_ROOT/releases/$(sha 5)" ] || fail "current is not release 5"

# A corrupt snapshot is rejected before anything is touched: no rename, no
# restart, releases.log and current unchanged.
: > "$DOCKER_LOG"
truncate -s 1 "$VPS_BACKUPS"/pre-"$(sha 5)"-*.sql.gz
if run rollback "$(sha 4)" "$confirm" 2>/dev/null; then fail "accepted a corrupt snapshot"; fi
if grep -q 'RENAME TO geopoliticai_failed' "$DOCKER_LOG"; then fail "touched the databases over a corrupt snapshot"; fi
[ "$(readlink "$VPS_ROOT/current")" = "$VPS_ROOT/releases/$(sha 5)" ] || fail "current moved on a corrupt snapshot"

echo "deploy script tests passed"
