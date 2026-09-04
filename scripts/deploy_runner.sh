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

echo "Checking public login + CSRF path through production nginx..."
public_cookie_jar="$(mktemp)"
public_login_html="$(mktemp)"
trap 'rm -f "$public_cookie_jar" "$public_login_html"' EXIT

public_get_code="$(curl -sS -o "$public_login_html" -c "$public_cookie_jar" -w '%{http_code}' --max-time 8 \
  -H 'Host: staff.greenlifeclinics.com' \
  -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:8085/login/ || true)"

if [[ "$public_get_code" != "200" ]]; then
  echo "Public login GET healthcheck failed with HTTP $public_get_code." >&2
  exit 1
fi

csrf_token="$(python3 - "$public_login_html" <<'PY'
import re, sys
html = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'name=["\x27]csrfmiddlewaretoken["\x27]\s+value=["\x27]([^"\x27]+)', html)
print(m.group(1) if m else "")
PY
)"

if [[ -z "$csrf_token" ]]; then
  echo "Public login CSRF token was not rendered." >&2
  exit 1
fi

# The internal probe reaches nginx over plain HTTP while explicitly preserving the
# external HTTPS scheme. Django correctly marks the CSRF cookie Secure, so curl
# will not resend it to an http:// probe automatically. Read the cookie value
# from the jar and send it explicitly; this tests Django's real CSRF origin,
# referer and cookie validation instead of failing only because the probe itself
# is not using TLS.
csrf_cookie="$(awk '$6 ~ /csrftoken$/ {print $7}' "$public_cookie_jar" | tail -1)"
if [[ -z "$csrf_cookie" ]]; then
  echo "Public login CSRF cookie was not issued." >&2
  exit 1
fi

public_post_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 \
  -H 'Host: staff.greenlifeclinics.com' \
  -H 'X-Forwarded-Proto: https' \
  -H 'Origin: https://staff.greenlifeclinics.com' \
  -H 'Referer: https://staff.greenlifeclinics.com/login/' \
  -H "Cookie: csrftoken=$csrf_cookie" \
  --data-urlencode "csrfmiddlewaretoken=$csrf_token" \
  --data-urlencode "username=__deploy_smoke_test__" \
  --data-urlencode "password=__invalid__" \
  http://127.0.0.1:8085/login/ || true)"

if [[ "$public_post_code" != "200" ]]; then
  echo "Public login CSRF POST healthcheck failed with HTTP $public_post_code." >&2
  exit 1
fi
echo "Public login + CSRF healthcheck OK."

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
