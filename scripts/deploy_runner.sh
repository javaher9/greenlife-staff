#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/home/ubuntu/greenlife-staff-runtime}"
cd "$DEPLOY_PATH"

COMPOSE_FILE="$DEPLOY_PATH/docker-compose.yml"
LAN_COMPOSE_FILE="$DEPLOY_PATH/docker-compose.lan.yml"
ENV_FILE="$DEPLOY_PATH/.env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
if [[ -f "$LAN_COMPOSE_FILE" ]]; then
  COMPOSE+=( -f "$LAN_COMPOSE_FILE" )
fi
COMPOSE+=( --project-directory "$DEPLOY_PATH" )

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
echo "Public NGINX port: ${NGINX_PORT:-8085}"
if [[ -f "$LAN_COMPOSE_FILE" ]]; then
  echo "Private LAN call-center port: 8086"
fi

# The approved production Compose owns PostgreSQL. Start it before the first
# backup so a clean server can bootstrap without deleting or replacing data.
if "${COMPOSE[@]}" config --services | grep -qx db; then
  echo "Ensuring PostgreSQL service is running..."
  "${COMPOSE[@]}" up -d db
fi

# Summarize the outgoing web container before replacement. Only aggregate
# exception classes are emitted; request/user data and tracebacks are discarded.
if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx web; then
  "${COMPOSE[@]}" logs --no-color --tail=2000 web 2>&1 \
    | python3 "$DEPLOY_PATH/scripts/summarize_runtime_errors.py" || true
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

echo "Repairing staff account integrity..."
"${COMPOSE[@]}" run --rm --entrypoint python web manage.py repair_staff_accounts --apply --verify-sessions

echo "Starting/replacing containers..."
"${COMPOSE[@]}" up -d --remove-orphans

if ! ./scripts/healthcheck.sh; then
  echo "Healthcheck failed. Existing database backup is available in backups/." >&2
  echo "Code rollback is handled by the GitHub workflow source snapshot." >&2
  exit 1
fi

if [[ -f "$LAN_COMPOSE_FILE" ]]; then
  echo "Checking private LAN login endpoint..."
  lan_ok=0
  for i in {1..30}; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -H 'Host: 192.168.40.96' http://127.0.0.1:8086/login/ || true)"
    if [[ "$code" == "200" ]]; then
      lan_ok=1
      echo "LAN login endpoint OK: http://192.168.40.96:8086/login/"
      break
    fi
    echo "Waiting for LAN login endpoint ($i/30), HTTP ${code:-none}..."
    sleep 2
  done
  if [[ "$lan_ok" != "1" ]]; then
    echo "LAN login healthcheck failed." >&2
    exit 1
  fi
fi

echo "Deploy successful."
"${COMPOSE[@]}" ps
