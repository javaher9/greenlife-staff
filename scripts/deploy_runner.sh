#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/home/ubuntu/greenlife-staff-runtime}"
cd "$DEPLOY_PATH"

COMPOSE_FILE="$DEPLOY_PATH/docker-compose.yml"
ENV_FILE="$DEPLOY_PATH/.env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --project-directory "$DEPLOY_PATH")

LOCKFILE="/tmp/greenlife_staff_deploy.lock"
exec 9>"$LOCKFILE"
flock -n 9 || { echo "Another deployment is already running."; exit 1; }

[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE is missing" >&2; exit 1; }
[[ -f "$COMPOSE_FILE" ]] || { echo "ERROR: $COMPOSE_FILE is missing" >&2; exit 1; }
command -v docker >/dev/null || { echo "ERROR: docker is required" >&2; exit 1; }
docker compose version >/dev/null

# Keep the server-owned .env file, but replace known placeholder settings and
# enforce safe production flags before Docker reads it. Secret values are never
# written to the GitHub Actions log.
python3 "$DEPLOY_PATH/scripts/harden_env.py" "$ENV_FILE"

set -a
# shellcheck disable=SC1091
source "$ENV_FILE"
set +a

if [[ "${NGINX_PORT:-8085}" != "8085" ]]; then
  echo "WARNING: NGINX_PORT is ${NGINX_PORT}; the approved production value is 8085." >&2
fi

echo "== GreenLife Staff self-hosted deployment =="
echo "Path: $DEPLOY_PATH"
echo "NGINX port: ${NGINX_PORT:-8085}"

# The approved production Compose owns PostgreSQL. Start it before the first
# backup so a clean server can bootstrap without deleting or replacing data.
if "${COMPOSE[@]}" config --services | grep -qx db; then
  echo "Ensuring PostgreSQL service is running..."
  "${COMPOSE[@]}" up -d db
fi

# Data backup happens before migrations/container replacement.
./scripts/backup.sh

echo "Building application image..."
if ! "${COMPOSE[@]}" build --pull; then
  echo "WARNING: Registry refresh failed; retrying with the locally cached base image." >&2
  "${COMPOSE[@]}" build
fi

echo "Validating production configuration..."
"${COMPOSE[@]}" run --rm --entrypoint python web manage.py check --deploy

echo "Applying database migrations..."
"${COMPOSE[@]}" run --rm --entrypoint python web manage.py migrate --noinput

echo "Starting/replacing containers..."
"${COMPOSE[@]}" up -d --remove-orphans

if ./scripts/healthcheck.sh; then
  echo "Deploy successful."
  "${COMPOSE[@]}" ps
  exit 0
fi

echo "Healthcheck failed. Existing database backup is available in backups/." >&2
echo "Code rollback is handled by the GitHub workflow source snapshot." >&2
exit 1
