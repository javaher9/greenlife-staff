#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/greenlife-staff}"
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

echo "Starting/replacing containers..."
docker compose up -d --remove-orphans

if ./scripts/healthcheck.sh; then
  echo "Deploy successful."
  docker compose ps
  exit 0
fi

echo "Healthcheck failed. Existing database backup is available in backups/." >&2
echo "Code rollback is handled by the GitHub workflow source snapshot." >&2
exit 1
