#!/usr/bin/env bash
# Runs ON the server, from /opt/xom (the deploy workflow copies it there with compose.yml
# and smoke_test.sh).
#
#   bash /opt/xom/deploy.sh <environment> <image-prefix> <release-tag>
#   bash /opt/xom/deploy.sh production ghcr.io/dt-azure sha-1a2b3c4d...
#   bash /opt/xom/deploy.sh rollback          back to the release before the current one
#
# <environment> is "test" or "production": the GitHub environment being deployed. The
# settings in /opt/xom/.env must belong to it (see "Server settings" below).
#
# Pulls the two images for that release, restarts the stack, then checks that the new
# version answers and that every long-running service stays up.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

die() { echo "deploy: $*" >&2; exit 1; }
compose() { docker compose --env-file .env --env-file release.env -f compose.yml "$@"; }
# Value of KEY in a KEY=value file, without running the file as a script
setting() { sed -n "s/^$1=//p" "${2:-.env}" | tail -n1; }

[[ -f .env ]] || die "/opt/xom/.env is missing (see deploy/server.env.example)"

# --- Which release -----------------------------------------------------------
if [[ "${1:-}" == "rollback" ]]; then
  [[ -f release.env.prev ]] || die "no previous release recorded"
  cp release.env.prev release.env.next
  env_name="$(setting DEPLOY_ENV release.env.next)"
  env_name="${env_name:-$(setting APP_ENV)}" # releases recorded before DEPLOY_ENV existed
else
  [[ $# -eq 3 ]] || die "usage: deploy.sh <test|production> <image-prefix> <release-tag> | rollback"
  env_name="$1" prefix="${2%/}" tag="$3"
  cat > release.env.next <<EOF
DEPLOY_ENV=${env_name}
RELEASE_TAG=${tag}
PIPELINE_IMAGE=${prefix}/xom-pipeline:${tag}
DASHBOARD_IMAGE=${prefix}/xom-dashboard:${tag}
EOF
fi
tag="$(setting RELEASE_TAG release.env.next)"

# --- Server settings ---------------------------------------------------------
# The settings must belong to the environment being deployed. This catches a .env copied
# from the other server, e.g. production users pointed at the test databases. It relies on
# the naming in the infra guide: users and databases are named xom_test_* / xom_prod_*.
case "$env_name" in
  test) mine=test other=prod ;;
  production) mine=prod other=test ;;
  *) die "environment must be test or production, got '${env_name}'" ;;
esac

app_env="$(setting APP_ENV)"
[[ "$app_env" == "$env_name" ]] \
  || die "APP_ENV in /opt/xom/.env is '${app_env}', but this is the ${env_name} deploy"

for var in DATABASE_URL SOURCE_DATABASE_URL DASHBOARD_DATABASE_URL; do
  url="$(setting "$var")"
  [[ -n "$url" ]] || die "${var} is not set in /opt/xom/.env"
  rest="${url#*://}"
  user="${rest%%@*}" user="${user%%:*}"
  db="${rest#*/}" db="${db%%\?*}"
  for name in "$user" "$db"; do
    if [[ "$name" == *"_${other}"* || "$name" != *"_${mine}"* ]]; then
      die "${var} uses user '${user}' and database '${db}', but this is the ${env_name} server: both names should contain '_${mine}' (check /opt/xom/.env)"
    fi
  done
done
echo "PASS  Settings belong to ${env_name}"

dashboard_port="$(setting DASHBOARD_PORT)"
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
