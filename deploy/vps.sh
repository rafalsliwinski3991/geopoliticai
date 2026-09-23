#!/usr/bin/env bash
# Production release steps, run on the VPS as the `deploy` user over SSH.
# deploy.yml copies this script, backup.sh and both compose files into
# $ROOT/releases/<sha>/ before calling it. The shared .env, releases.log and
# every snapshot live outside the release directories.
set -euo pipefail

ROOT="${VPS_ROOT:-/srv/geopoliticai}"
BACKUPS="${VPS_BACKUPS:-/srv/backups}"
LOG="$ROOT/releases.log"
KEEP=5
SHA_RE='^[0-9a-f]{40}$'

compose() { docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"; }

# cd into a release directory and pin its image tag.
enter() {
  cd "$ROOT/releases/$1"
  ln -sfn "$ROOT/.env" .env
  export IMAGE_TAG="$1"
}

previous() { tail -n 1 "$LOG" 2>/dev/null || true; }

# pre-<sha>-20260923T1402Z.sql.gz -> delete-data-since-20260923T1402Z
confirmation() {
  local ts=${1##*-}
  echo "delete-data-since-${ts%.sql.gz}"
}

# Keep the newest $KEEP releases, their directories and the one snapshot each
# release's .snapshot names (retried deploys leave older ones behind).
prune() {
  local keep dir f snaps=""
  keep=$(tail -n "$KEEP" "$LOG")
  printf '%s\n' "$keep" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  for dir in "$ROOT"/releases/*/; do
    dir=${dir%/}
    if grep -qx "${dir##*/}" <<<"$keep"; then
      snaps+="$(cat "$dir/.snapshot" 2>/dev/null || true)"$'\n'
    else
      rm -rf "$dir"
    fi
  done
  for f in "$BACKUPS"/pre-*.sql.gz; do
    [ -e "$f" ] || continue
    grep -qxF "$f" <<<"$snaps" || rm -f "$f"
  done
}

# Snapshot, migrate in README order, start. The old app containers keep
# serving until the final `up` (`run agentic-backend` does start the new
# phoenix early, through depends_on); a failure leaves them running for `abort`.
deploy() {
  local sha=$1 snap
  enter "$sha"
  rm -f .snapshot
  compose pull
  compose up -d --no-build --wait postgres
  mkdir -p "$BACKUPS"
  snap="$BACKUPS/pre-$sha-$(date -u +%Y%m%dT%H%MZ).sql.gz"
  compose exec -T postgres pg_dump -U geopoliticai geopoliticai | gzip > "$snap"
  echo "$snap" > .snapshot
  compose run --rm web-backend .venv/bin/python manage.py migrate --noinput
  compose run --rm web-backend .venv/bin/python manage.py createcachetable
  compose run --rm agentic-backend .venv/bin/alembic upgrade head
  compose up -d --no-build --wait --remove-orphans
}

# Record a release that passed the public health check.
finish() {
  local sha=$1 prev
  prev=$(previous)
  enter "$sha"
  { grep -vx "$sha" "$LOG" 2>/dev/null || true; echo "$sha"; } > "$LOG.tmp"
  mv "$LOG.tmp" "$LOG"
  ln -sfn "$ROOT/releases/$sha" "$ROOT/current"
  prune
  if [ -n "$prev" ] && [ "$prev" != "$sha" ]; then
    echo "Rollback to the previous release: target=$prev confirm=$(confirmation "$(cat .snapshot)")"
  else
    echo "No earlier release to roll back to."
  fi
}

case "${1:-}" in
  deploy|finish)
    [[ ${2:-} =~ $SHA_RE ]] || { echo "usage: $0 $1 <sha>" >&2; exit 2; }
    "$1" "$2" ;;
  *) echo "usage: $0 deploy|finish <sha>" >&2; exit 2 ;;
esac
