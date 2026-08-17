#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/greenlife-staff}"
LEGACY_COMPOSE_FILE="${LEGACY_COMPOSE_FILE:-/home/ubuntu/staff-gl/greenlife_staff_v17/docker-compose.yml}"
cd "$DEPLOY_PATH"

LOCKFILE="/tmp/greenlife_staff_deploy.lock"
exec 9>"$LOCKFILE"
flock -n 9 || { echo "Another deployment is already running."; exit 1; }

[[ -f .env ]] || { echo "ERROR: $DEPLOY_PATH/.env is missing" >&2; exit 1; }
command -v docker >/dev/null || { echo "ERROR: docker is required" >&2; exit 1; }
docker compose version >/dev/null

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ "${NGINX_PORT:-8085}" != "8085" ]]; then
  echo "WARNING: NGINX_PORT is ${NGINX_PORT}; the approved production value is 8085." >&2
fi

echo "== GreenLife Staff self-hosted deployment =="
echo "Path: $DEPLOY_PATH"
echo "NGINX port: ${NGINX_PORT:-8085}"

# Data backup happens before migrations/container replacement.
./scripts/backup.sh

echo "Building application image..."
docker compose build --pull

echo "Applying database migrations..."
docker compose run --rm --entrypoint python web manage.py migrate --noinput

LEGACY_STOPPED=0
restore_legacy_on_error() {
  status=$?
  if [[ "$status" -ne 0 && "$LEGACY_STOPPED" -eq 1 ]]; then
    echo "Deployment failed; restoring the version 17 web services..." >&2
    docker compose down --remove-orphans || true
    docker compose -f "$LEGACY_COMPOSE_FILE" up -d db web nginx || true
  fi
  exit "$status"
}
trap restore_legacy_on_error EXIT

# Version 17 owns port 8085. Stop only its web tier immediately before the
# switch; PostgreSQL remains running and its existing data volume is untouched.
if [[ -f "$LEGACY_COMPOSE_FILE" ]] && \
   docker compose -f "$LEGACY_COMPOSE_FILE" ps --status running --services | grep -qx nginx; then
  echo "Stopping version 17 web services for controlled port handover..."
  docker compose -f "$LEGACY_COMPOSE_FILE" stop nginx web
  LEGACY_STOPPED=1
fi

echo "Starting/replacing version 18 containers..."
docker compose up -d --remove-orphans

if ./scripts/healthcheck.sh; then
  trap - EXIT
  echo "Deploy successful. PostgreSQL remained online during the switch."
  docker compose ps
  exit 0
fi

echo "Healthcheck failed. Existing database backup is available in backups/." >&2
echo "Code rollback is handled by the GitHub workflow source snapshot." >&2
exit 1
