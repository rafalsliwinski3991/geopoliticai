#!/usr/bin/env bash
# Fail when the test password reached any Playwright artifact: traces, results,
# error contexts, report data, or the HTML report (whose data is a base64 zip
# inside index.html). Fails closed (exit 2) when it cannot check.
set -euo pipefail
cd "$(dirname "$0")"

# Read the one line instead of sourcing .env: dotenv syntax is not shell syntax.
if [ -z "${E2E_PASSWORD:-}" ] && [ -f ../.env ]; then
  E2E_PASSWORD="$(grep -m1 '^E2E_PASSWORD=' ../.env | cut -d= -f2- | tr -d '\r' || true)"
  # Strip one pair of surrounding quotes.
  E2E_PASSWORD="${E2E_PASSWORD#[\"\']}"
  E2E_PASSWORD="${E2E_PASSWORD%[\"\']}"
fi
if [ -z "${E2E_PASSWORD:-}" ]; then echo "e2e: E2E_PASSWORD is not set" >&2; exit 2; fi
command -v unzip >/dev/null || { echo "e2e: unzip is required" >&2; exit 2; }

if [ ! -d test-results ] && [ ! -d playwright-report ]; then
  echo "e2e: neither test-results/ nor playwright-report/ exists; nothing was checked" >&2
  exit 2
fi

found=0
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Unzip every archive into its own folder, then search plain files only.
n=0
while IFS= read -r -d '' zip; do
  n=$((n + 1))
  unzip -qo "$zip" -d "$tmp/$n" >/dev/null 2>&1 || { echo "e2e: cannot unzip $zip" >&2; exit 2; }
  printf '%s\n' "$zip" > "$tmp/$n.source"
done < <(find test-results playwright-report -name '*.zip' -print0 2>/dev/null)

if [ -f playwright-report/index.html ]; then
  payload="$(grep -o 'data:application/zip;base64,[A-Za-z0-9+/=]*' playwright-report/index.html || true)"
  if [ -z "$payload" ]; then
    echo "e2e: no report payload found in playwright-report/index.html; cannot check it" >&2
    exit 2
  fi
  printf '%s' "${payload#data:application/zip;base64,}" | base64 -d > "$tmp/report.zip" \
    || { echo "e2e: cannot decode the report payload in playwright-report/index.html" >&2; exit 2; }
  unzip -qo "$tmp/report.zip" -d "$tmp/report" >/dev/null 2>&1 \
    || { echo "e2e: cannot unzip the report payload in playwright-report/index.html" >&2; exit 2; }
fi

# grep exits 0 on a match and 1 on none; anything else means it could not read.
dirs=("$tmp")
for dir in test-results playwright-report; do [ -d "$dir" ] && dirs+=("$dir"); done
status=0
matches="$(grep -rlF --exclude='*.zip' -- "$E2E_PASSWORD" "${dirs[@]}")" || status=$?
if [ "$status" -gt 1 ]; then echo "e2e: grep failed (exit $status); cannot check" >&2; exit 2; fi
while IFS= read -r file; do
  [ -n "$file" ] || continue
  echo "e2e: the test password appears in ${file#"$tmp/"}" >&2
  found=1
done <<< "$matches"

if [ "$found" -eq 0 ]; then echo "e2e: no password in test-results/ or playwright-report/"; fi
exit "$found"
