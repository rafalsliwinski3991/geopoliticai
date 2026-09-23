#!/usr/bin/env bash
# Nightly off-site copy of the production database, run by the deploy user's
# crontab from $ROOT/current. The bucket's 14-day lifecycle rule (README
# runbook) deletes old copies; this script only uploads. aws-cli is pinned by
# digest to 2.22.35, the newest version OVH lists as compatible: later
# versions send checksum headers OVH Object Storage rejects
# (ovh/public-cloud-roadmap#781).
set -euo pipefail

ROOT="${VPS_ROOT:-/srv/geopoliticai}"
BUCKET=dramatic-wieman
ENDPOINT=https://s3.eu-west-par.io.cloud.ovh.net
REGION=eu-west-par

# The dump lands in a local file first: a pg_dump that dies partway through
# would otherwise stream a truncated prefix to gzip, whose output is still a
# valid-looking .sql.gz, and the newest object in the bucket would be an
# unusable backup. Only a complete dump is ever uploaded.
tmp=$(mktemp "${TMPDIR:-/tmp}/nightly-XXXXXX.sql.gz")
trap 'rm -f "$tmp"' EXIT

cd "$ROOT/current"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
    pg_dump -U geopoliticai geopoliticai \
  | gzip > "$tmp"
docker run --rm --env-file "$ROOT/backup.env" \
  amazon/aws-cli:2.22.35@sha256:6977c83ae3dc99f28fcf8276b9ea5eec33833cd5be40574b34112e98113ec7a2 \
    s3 cp "$tmp" "s3://$BUCKET/nightly/$(date -u +%Y%m%dT%H%MZ).sql.gz" \
    --endpoint-url "$ENDPOINT" --region "$REGION"
