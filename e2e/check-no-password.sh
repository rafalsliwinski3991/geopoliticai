#!/usr/bin/env bash
# Fail when the test password reached any Playwright artifact: traces, results,
# error contexts, report data, or the HTML report (whose data is a base64 zip
# inside index.html). Fails closed (exit 2) when it cannot check.
set -euo pipefail
cd "$(dirname "$0")"

# Read the one line instead of sourcing .env: dotenv syntax is not shell syntax.
if [ -z "${E2E_PASSWORD:-}" ] && [ -f ../.env ]; then
  E2E_PASSWORD="$(grep -m1 '^E2E_PASSWORD=' ../.env | cut -d= -f2- || true)"
fi
if [ -z "${E2E_PASSWORD:-}" ]; then echo "e2e: E2E_PASSWORD is not set" >&2; exit 2; fi
command -v unzip >/dev/null || { echo "e2e: unzip is required" >&2; exit 2; }

found=0
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Unzip every archive into its own folder, then search plain files only.
n=0
while IFS= read -r -d '' zip; do
  n=$((n + 1))
  unzip -qo "$zip" -d "$tmp/$n"
  printf '%s\n' "$zip" > "$tmp/$n.source"
done < <(find test-results playwright-report -name '*.zip' -print0 2>/dev/null)

if [ -f playwright-report/index.html ]; then
  payload="$(grep -o 'data:application/zip;base64,[A-Za-z0-9+/=]*' playwright-report/index.html || true)"
  if [ -z "$payload" ]; then
    echo "e2e: no report payload found in playwright-report/index.html; cannot check it" >&2
    exit 2
  fi
  printf '%s' "${payload#data:application/zip;base64,}" | base64 -d > "$tmp/report.zip"
  unzip -qo "$tmp/report.zip" -d "$tmp/report"
fi

while IFS= read -r file; do
  echo "e2e: the test password appears in ${file#"$tmp/"}" >&2
  found=1
done < <(grep -rlF --exclude='*.zip' -- "$E2E_PASSWORD" test-results playwright-report "$tmp" 2>/dev/null || true)

if [ "$found" -eq 0 ]; then echo "e2e: no password in test-results/ or playwright-report/"; fi
exit "$found"
