#!/usr/bin/env bash
# Runs ON the server, from /opt/xom (the deploy workflow copies it there with compose.yml
# and smoke_test.sh).
#
#   bash /opt/xom/deploy.sh <image-prefix> <release-tag>
#   bash /opt/xom/deploy.sh ghcr.io/dt-azure sha-1a2b3c4d...
#   bash /opt/xom/deploy.sh rollback          back to the release before the current one
#
# Pulls the two images for that release, restarts the stack, then checks that the new
# version answers and that every long-running service stays up.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

die() { echo "deploy: $*" >&2; exit 1; }
compose() { docker compose --env-file .env --env-file release.env -f compose.yml "$@"; }

# --- Which release -----------------------------------------------------------
if [[ "${1:-}" == "rollback" ]]; then
  [[ -f release.env.prev ]] || die "no previous release recorded"
  cp release.env.prev release.env.next
else
  [[ $# -eq 2 ]] || die "usage: deploy.sh <image-prefix> <release-tag> | rollback"
  prefix="${1%/}" tag="$2"
  cat > release.env.next <<EOF
RELEASE_TAG=${tag}
PIPELINE_IMAGE=${prefix}/xom-pipeline:${tag}
DASHBOARD_IMAGE=${prefix}/xom-dashboard:${tag}
EOF
fi
# shellcheck disable=SC1091
tag="$(. ./release.env.next && echo "$RELEASE_TAG")"

# --- Server settings ---------------------------------------------------------
[[ -f .env ]] || die "/opt/xom/.env is missing (see deploy/server.env.example)"
for var in DATABASE_URL SOURCE_DATABASE_URL DASHBOARD_DATABASE_URL; do
  grep -Eq "^${var}=.+" .env || die "${var} is not set in /opt/xom/.env"
done
dashboard_port="$(sed -n 's/^DASHBOARD_PORT=//p' .env | tail -n1)"
dashboard_port="${dashboard_port:-80}"

# --- Deploy ------------------------------------------------------------------
[[ -f release.env ]] && cp release.env release.env.prev
mv release.env.next release.env
echo "deploy: release ${tag}"

compose pull --quiet
compose up -d --remove-orphans

# --- Check -------------------------------------------------------------------
EXPECTED_VERSION="$tag" bash ./smoke_test.sh \
  --api http://127.0.0.1:5000 \
  --dashboard "http://127.0.0.1:${dashboard_port}"

# The dashboard has no version endpoint, so confirm its container runs the new image.
want="$(sed -n 's/^DASHBOARD_IMAGE=//p' release.env)"
have="$(docker inspect --format '{{.Config.Image}}' "$(compose ps -q dashboard)")"
[[ "$have" == "$want" ]] || die "dashboard runs ${have}, expected ${want}"
echo "PASS  Dashboard image  (${have})"

# A service in a crash loop still shows "running" between restarts, so compare restart
# counts across a short window.
long_running=(kafka api consumer poller transform-runner dashboard)
restarts() { for s in "${long_running[@]}"; do docker inspect --format '{{.RestartCount}}' "$(compose ps -q "$s")"; done; }
before="$(restarts)"
sleep "${STABILITY_SECONDS:-30}"
after="$(restarts)"
for s in "${long_running[@]}"; do
  state="$(docker inspect --format '{{.State.Status}}' "$(compose ps -q "$s")")"
  [[ "$state" == "running" ]] || die "${s} is ${state} (see: docker compose logs ${s})"
done
[[ "$before" == "$after" ]] || die "a service restarted during the check (see: docker compose ps -a)"
echo "PASS  All services stable for ${STABILITY_SECONDS:-30}s"

# --- Tidy up -----------------------------------------------------------------
# Remove our older images (they carry the OCI source label); Kafka's are left alone.
docker image prune -af --filter "label=org.opencontainers.image.source" > /dev/null
echo "deploy: ${tag} is live"
