#!/usr/bin/env bash
# Smoke test: is the stack up and answering?
#
#   bash scripts/smoke_test.sh [--api URL] [--dashboard URL]
#
#   Local / CI:   --api http://localhost:5000 --dashboard http://localhost:8501
#   On a server:  --api http://127.0.0.1:5000 --dashboard http://127.0.0.1   (deploy.sh does this)
#   From outside: --dashboard http://<test-ip>  or  --dashboard http://<alb-dns>
#
# Optional environment variables:
#   EXPECTED_VERSION  release tag the API's /health must report (proves the new version is
#                     the one running)
#   SMOKE_RETRIES     attempts per check (default 30)
#   SMOKE_DELAY       seconds between attempts (default 3)
#
# Note: Streamlit answers /_stcore/health even if the dashboard's Python code fails, so this
# proves the service is up, not that every page works. The dashboard tests (AppTest) cover that.
set -euo pipefail

API_URL=""
DASHBOARD_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api) API_URL="${2%/}"; shift 2 ;;
    --dashboard) DASHBOARD_URL="${2%/}"; shift 2 ;;
    *) echo "usage: smoke_test.sh [--api URL] [--dashboard URL]" >&2; exit 64 ;;
  esac
done
[[ -n "$API_URL" || -n "$DASHBOARD_URL" ]] || { echo "smoke_test.sh: nothing to check" >&2; exit 64; }

RETRIES="${SMOKE_RETRIES:-30}"
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

if [[ -n "$API_URL" ]]; then
  check "API health" "$API_URL/health" '"status":"ok"'
  [[ -n "$EXPECTED_VERSION" ]] && check "API version" "$API_URL/health" "\"version\":\"$EXPECTED_VERSION\""
fi
if [[ -n "$DASHBOARD_URL" ]]; then
  check "Dashboard health" "$DASHBOARD_URL/_stcore/health" "ok"
  check "Dashboard page" "$DASHBOARD_URL/"
fi

if ((failures > 0)); then
  echo "Smoke test failed: $failures check(s)"
  exit 1
fi
echo "Smoke test passed"
