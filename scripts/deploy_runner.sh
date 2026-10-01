#!/usr/bin/env bash
set -Eeuo pipefail
# Runtime diagnostic refresh marker. Emergency production recovery trigger 2026-09-30.

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

  echo "Waiting for PostgreSQL readiness..."
  db_ready=0
  for i in {1..30}; do
    if "${COMPOSE[@]}" exec -T db pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-${POSTGRES_USER:-postgres}}" >/dev/null 2>&1; then
      db_ready=1
      echo "PostgreSQL is ready."
      break
    fi
    if [[ "$i" == "6" ]]; then
      echo "PostgreSQL still not ready; restarting database container once..." >&2
      "${COMPOSE[@]}" restart db || true
    fi
    sleep 2
  done
  if [[ "$db_ready" != "1" ]]; then
    echo "PostgreSQL did not become ready. Recent database log:" >&2
    "${COMPOSE[@]}" logs --no-color --tail=120 db >&2 || true
    exit 1
  fi
fi

# Summarize the outgoing web container before replacement. Only aggregate
# exception classes are emitted; request/user data and tracebacks are discarded.
if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx web; then
  "${COMPOSE[@]}" logs --no-color --tail=2000 web 2>&1 \
    | python3 "$DEPLOY_PATH/scripts/summarize_runtime_errors.py" || true
fi

# Data backup happens before migrations/container replacement.
./scripts/backup.sh

# Snapshot the currently running application images before any build replaces
# their normal tags. These local rollback tags make recovery independent of
# Docker Hub/network availability.
if docker ps --format '{{.Names}}' | grep -qx 'greenlife-staff-runtime-web-1'; then
  docker tag "$(docker inspect -f '{{.Image}}' greenlife-staff-runtime-web-1)" greenlife-staff-rollback-web:latest
  echo "Snapshot saved: public web image."
fi
if docker ps --format '{{.Names}}' | grep -qx 'greenlife-staff-runtime-web_lan-1'; then
  docker tag "$(docker inspect -f '{{.Image}}' greenlife-staff-runtime-web_lan-1)" greenlife-staff-rollback-web_lan:latest
  echo "Snapshot saved: LAN web image."
elif docker image inspect greenlife-staff-rollback-web:latest >/dev/null 2>&1; then
  docker tag greenlife-staff-rollback-web:latest greenlife-staff-rollback-web_lan:latest
  echo "Snapshot recovered: LAN image from public web image."
fi

APP_BUILD_REQUIRED="${APP_BUILD_REQUIRED:-1}"
if [[ "$APP_BUILD_REQUIRED" == "1" ]]; then
  echo "Preparing application image..."

  # Fast, network-independent path for source-only application changes:
  # reuse the exact currently running image only when both dependency manifest
  # and Dockerfile are byte-for-byte identical to the previous production image.
  local_overlay_ok=0
  old_requirements="$DEPLOY_PATH/.rollback/requirements.previous"
  old_dockerfile="$DEPLOY_PATH/.rollback/Dockerfile.previous"
  overlay_dockerfile="$DEPLOY_PATH/.rollback/Dockerfile.overlay"
  rm -f "$old_requirements" "$old_dockerfile" "$overlay_dockerfile"

  if docker image inspect greenlife-staff-rollback-web:latest >/dev/null 2>&1; then
    if docker run --rm --entrypoint cat greenlife-staff-rollback-web:latest /app/requirements.txt >"$old_requirements" 2>/dev/null \
      && docker run --rm --entrypoint cat greenlife-staff-rollback-web:latest /app/Dockerfile >"$old_dockerfile" 2>/dev/null \
      && cmp -s requirements.txt "$old_requirements" \
      && cmp -s Dockerfile "$old_dockerfile"; then
      local_overlay_ok=1
    fi
  fi

  if [[ "$local_overlay_ok" == "1" ]]; then
    echo "Dependencies and Dockerfile are unchanged; building from approved local production image without Docker Hub."
    cat >"$overlay_dockerfile" <<'EOF'
FROM greenlife-staff-rollback-web:latest
WORKDIR /app
COPY . .
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
EOF
    DOCKER_BUILDKIT=0 docker build --pull=false -f "$overlay_dockerfile" -t greenlife-staff-runtime-web:latest .
    docker tag greenlife-staff-runtime-web:latest greenlife-staff-runtime-web_lan:latest
  else
    echo "Dependency manifest or Dockerfile changed; a full application build is required."
    if ! DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 "${COMPOSE[@]}" build; then
      echo "WARNING: Local-cache build failed; retrying with BuildKit without --pull." >&2
      "${COMPOSE[@]}" build
    fi
  fi
else
  echo "Infrastructure-only change detected; reusing approved local application image."
  docker image inspect greenlife-staff-runtime-web:latest >/dev/null 2>&1 || {
    echo "ERROR: approved local public web image is missing." >&2
    exit 1
  }
  if ! docker image inspect greenlife-staff-runtime-web_lan:latest >/dev/null 2>&1; then
    docker tag greenlife-staff-runtime-web:latest greenlife-staff-runtime-web_lan:latest
    echo "Recovered LAN image tag from approved public web image."
  fi
fi

echo "Validating production configuration..."
"${COMPOSE[@]}" run --rm --entrypoint python web manage.py check --deploy

echo "Applying database migrations..."
"${COMPOSE[@]}" run --rm --entrypoint python web manage.py migrate --noinput

echo "Repairing staff account integrity..."
"${COMPOSE[@]}" run --rm --entrypoint python web manage.py repair_staff_accounts --apply --verify-sessions

echo "Preparing shared static files before blue-green cutover..."
"${COMPOSE[@]}" run --rm --entrypoint python web manage.py collectstatic --noinput
"${COMPOSE[@]}" run --rm --entrypoint python web manage.py seed_initial_data

echo "Starting blue-green candidate containers beside live production..."
PUBLIC_WEB="greenlife-staff-runtime-web-1"
LAN_WEB="greenlife-staff-runtime-web_lan-1"
PUBLIC_NGINX="greenlife-staff-runtime-nginx-1"
LAN_NGINX="greenlife-staff-runtime-nginx_lan-1"
RELEASE_ID="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$(date +%s)"
PUBLIC_CANDIDATE="greenlife-web-candidate-${RELEASE_ID}"
LAN_CANDIDATE="greenlife-web-lan-candidate-${RELEASE_ID}"
NETWORK="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$PUBLIC_WEB")"
[[ -n "$NETWORK" ]] || { echo "ERROR: could not determine production Docker network." >&2; exit 1; }

cleanup_candidates() {
  docker rm -f "$PUBLIC_CANDIDATE" "$LAN_CANDIDATE" >/dev/null 2>&1 || true
}
trap 'cleanup_candidates' EXIT

docker rm -f "$PUBLIC_CANDIDATE" "$LAN_CANDIDATE" >/dev/null 2>&1 || true
docker image inspect greenlife-staff-runtime-web:latest >/dev/null 2>&1 || { echo "ERROR: candidate image missing." >&2; exit 1; }

docker run -d --name "$PUBLIC_CANDIDATE" \
  --network "$NETWORK" --env-file "$ENV_FILE" --volumes-from "$PUBLIC_WEB" \
  --entrypoint gunicorn greenlife-staff-runtime-web:latest greenlife.wsgi:application \
  --bind 0.0.0.0:8005 --workers "${GUNICORN_WORKERS:-3}" --timeout 120 >/dev/null

if docker ps --format '{{.Names}}' | grep -qx "$LAN_WEB"; then
  if ! docker image inspect greenlife-staff-runtime-web_lan:latest >/dev/null 2>&1; then
    docker tag greenlife-staff-runtime-web:latest greenlife-staff-runtime-web_lan:latest
  fi
  docker run -d --name "$LAN_CANDIDATE" \
    --network "$NETWORK" --env-file "$ENV_FILE" --volumes-from "$LAN_WEB" \
    -e LAN_MODE=1 -e ALLOWED_HOSTS="192.168.40.96,localhost,127.0.0.1" \
    -e CSRF_TRUSTED_ORIGINS="http://192.168.40.96:8086" \
    --entrypoint gunicorn greenlife-staff-runtime-web_lan:latest greenlife.wsgi:application \
    --bind 0.0.0.0:8005 --workers 2 --timeout 120 >/dev/null
fi

probe_candidate() {
  local proxy="$1" target="$2" host="$3"
  for i in {1..40}; do
    if docker exec "$proxy" sh -c "wget -q -O- -T 4 --header='Host: $host' http://$target:8005/api/health/" 2>/dev/null \
      | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
      echo "Healthy candidate: $target"
      return 0
    fi
    sleep 2
  done
  echo "ERROR: candidate $target failed direct healthcheck." >&2
  docker logs --tail=160 "$target" >&2 || true
  return 1
}

probe_candidate "$PUBLIC_NGINX" "$PUBLIC_CANDIDATE" "staff.greenlifeclinics.com"
if docker ps --format '{{.Names}}' | grep -qx "$LAN_CANDIDATE"; then
  probe_candidate "$LAN_NGINX" "$LAN_CANDIDATE" "192.168.40.96"
fi

set_public_upstream() {
  local target="$1"
  sed -E -i "s#set \\$greenlife_web_upstream [^;]+;#set \\$greenlife_web_upstream ${target}:8005;#" "$DEPLOY_PATH/deploy/nginx.conf"
}
set_lan_upstream() {
  local target="$1"
  sed -E -i "s#set \\$greenlife_lan_upstream [^;]+;#set \\$greenlife_lan_upstream ${target}:8005;#" "$DEPLOY_PATH/deploy/nginx-lan.conf"
}
reload_public_nginx() {
  docker exec "$PUBLIC_NGINX" nginx -t
  docker exec "$PUBLIC_NGINX" nginx -s reload
}
reload_lan_nginx() {
  docker exec "$LAN_NGINX" nginx -t
  docker exec "$LAN_NGINX" nginx -s reload
}

echo "Gracefully switching public traffic to the healthy candidate..."
set_public_upstream "$PUBLIC_CANDIDATE"
reload_public_nginx
if docker ps --format '{{.Names}}' | grep -qx "$LAN_CANDIDATE"; then
  echo "Gracefully switching LAN traffic to the healthy candidate..."
  set_lan_upstream "$LAN_CANDIDATE"
  reload_lan_nginx
fi

if ! HEALTHCHECK_TRIES=15 HEALTHCHECK_SLEEP=1 ./scripts/healthcheck.sh; then
  echo "Candidate cutover failed; returning traffic to untouched stable services." >&2
  set_public_upstream web
  reload_public_nginx || true
  if docker ps --format '{{.Names}}' | grep -qx "$LAN_WEB"; then
    set_lan_upstream web_lan
    reload_lan_nginx || true
  fi
  exit 1
fi

echo "Candidate is serving traffic. Updating stable web containers behind it..."
"${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate web
if "${COMPOSE[@]}" config --services | grep -qx web_lan; then
  "${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate web_lan
fi

probe_candidate "$PUBLIC_NGINX" "$PUBLIC_WEB" "staff.greenlifeclinics.com"
if docker ps --format '{{.Names}}' | grep -qx "$LAN_WEB"; then
  probe_candidate "$LAN_NGINX" "$LAN_WEB" "192.168.40.96"
fi

echo "Gracefully returning traffic to upgraded stable services..."
set_public_upstream web
reload_public_nginx
if docker ps --format '{{.Names}}' | grep -qx "$LAN_WEB"; then
  set_lan_upstream web_lan
  reload_lan_nginx
fi

HEALTHCHECK_TRIES=20 HEALTHCHECK_SLEEP=1 ./scripts/healthcheck.sh

if "${COMPOSE[@]}" config --services | grep -qx sms_worker; then
  echo "Refreshing SMS worker after successful cutover..."
  "${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate sms_worker
fi

cleanup_candidates
trap - EXIT
echo "Blue-green cutover complete; nginx was never restarted."

echo "Checking public login + CSRF path through production nginx..."
public_cookie_jar="$(mktemp)"
public_login_html="$(mktemp)"
public_login_headers="$(mktemp)"
trap 'rm -f "$public_cookie_jar" "$public_login_html" "$public_login_headers"' EXIT

public_get_code="$(curl -sS -D "$public_login_headers" -o "$public_login_html" -c "$public_cookie_jar" -w '%{http_code}' --max-time 8 \
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
# Read the CSRF cookie from the actual Set-Cookie header first. Curl may decline
# to persist a Secure cookie in its jar when this internal probe reaches nginx
# through plain http://127.0.0.1 even though X-Forwarded-Proto correctly marks
# the original request as HTTPS.
csrf_cookie="$(python3 - "$public_login_headers" <<'PY'
import re, sys
headers = open(sys.argv[1], encoding='iso-8859-1').read()
m = re.search(r'(?im)^set-cookie:\s*csrftoken=([^;\r\n]+)', headers)
print(m.group(1) if m else "")
PY
)"
if [[ -z "$csrf_cookie" ]]; then
  csrf_cookie="$(awk '$6 ~ /csrftoken$/ {print $7}' "$public_cookie_jar" | tail -1)"
fi
if [[ -z "$csrf_cookie" ]]; then
  echo "Public login CSRF cookie was not issued." >&2
  echo "Set-Cookie headers seen: $(grep -ic '^Set-Cookie:' "$public_login_headers" || true)" >&2
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

echo "Checking real public HTTPS endpoint from production host..."
external_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 12 https://staff.greenlifeclinics.com/login/ || true)"
if [[ "$external_code" == "200" ]]; then
  echo "External public HTTPS login endpoint OK."
else
  # Some hosts cannot hairpin back to their own public 443 endpoint. Do not
  # roll back an otherwise healthy proxy/app deployment for that network-only
  # condition; the internal production-nginx CSRF test above remains blocking.
  echo "WARNING: production host could not self-connect to public HTTPS (HTTP ${external_code:-none}); keeping healthy deployment." >&2
fi

if [[ -f "$LAN_COMPOSE_FILE" ]]; then
  echo "Checking private LAN login endpoint..."
  lan_ok=0
  for i in {1..30}; do
    # Use the real LAN Host, not localhost: localhost is accepted by both web
    # services and could hide a stale nginx_lan upstream after a Docker IP swap.
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
