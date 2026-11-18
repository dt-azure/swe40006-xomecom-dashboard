#!/usr/bin/env bash
# Smoke test
#   bash scripts/smoke_test.sh [API_URL] [DASHBOARD_URL]
#   bash scripts/smoke_test.sh http://localhost:5000 http://localhost:8501
#
# Optional environment variables:
#   EXPECTED_VERSION  commit SHA that /health must report
#   SMOKE_RETRIES     attempts per check (default 20)
#   SMOKE_DELAY       seconds between attempts (default 3)

set -euo pipefail

API_URL="${1:-http://localhost:5000}"
DASHBOARD_URL="${2:-http://localhost:8501}"
RETRIES="${SMOKE_RETRIES:-20}"
DELAY="${SMOKE_DELAY:-3}"
EXPECTED_VERSION="${EXPECTED_VERSION:-}"

failures=0

# check <name> <url> [text the response must contain]
check() {
  local name="$1" url="$2" expect="${3:-}" body=""
  for ((i = 1; i <= RETRIES; i++)); do
    if body="$(curl -fsS --max-time 5 "$url" 2>/dev/null)"; then
      if [[ -z "$expect" || "$body" == *"$expect"* ]]; then
        echo "PASS  $name  ($url)"
        return 0
      fi
    fi
    sleep "$DELAY"
  done
  echo "FAIL  $name  ($url)"
  [[ -n "$body" ]] && echo "      last response: ${body:0:300}"
  [[ -n "$expect" ]] && echo "      expected to contain: $expect"
  failures=$((failures + 1))
  return 0
}

check "API health"         "$API_URL/health"               '"status":"ok"'
if [[ -n "$EXPECTED_VERSION" ]]; then
  check "API version"      "$API_URL/health"               "$EXPECTED_VERSION"
fi
check "Dashboard health"   "$DASHBOARD_URL/_stcore/health" "ok"
check "Dashboard page"     "$DASHBOARD_URL/"

if ((failures > 0)); then
  echo "Smoke test failed: $failures check(s)"
  exit 1
fi
echo "Smoke test passed"
