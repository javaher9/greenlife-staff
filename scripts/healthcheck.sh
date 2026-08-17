#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
URL="${HEALTHCHECK_URL:-http://127.0.0.1:${NGINX_PORT:-8085}/api/health/}"
TRIES="${HEALTHCHECK_TRIES:-30}"
SLEEP="${HEALTHCHECK_SLEEP:-3}"
for ((i=1;i<=TRIES;i++)); do
  if curl -fsS --max-time 5 "$URL" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    echo "Healthcheck OK: $URL"
    exit 0
  fi
  echo "Waiting for app ($i/$TRIES)..."
  sleep "$SLEEP"
done

echo "Healthcheck FAILED: $URL" >&2
exit 1
