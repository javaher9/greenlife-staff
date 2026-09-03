#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

DB_FILE="$BACKUP_DIR/db_${STAMP}.dump"
MEDIA_FILE="$BACKUP_DIR/media_${STAMP}.tar.gz"

: "${POSTGRES_HOST:?POSTGRES_HOST missing}"
: "${POSTGRES_DB:?POSTGRES_DB missing}"
: "${POSTGRES_USER:?POSTGRES_USER missing}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD missing}"

# Back up through the already-running PostgreSQL service. This avoids pulling a
# temporary postgres image during deploy and keeps backups working even when
# Docker Hub is temporarily unreachable from the production server.
docker compose exec -T \
  -e PGPASSWORD="$POSTGRES_PASSWORD" \
  db \
  pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" > "$DB_FILE"

# Back up the named media volume without depending on an external helper image.
# Reuse the locally available application image, which is already present on a
# healthy production host and includes standard tar utilities.
MEDIA_VOL="$(docker compose config --volumes | grep -E '(^|_)media_data$' | head -n1 || true)"
if [[ -n "$MEDIA_VOL" ]]; then
  PROJECT="$(basename "$PWD" | tr '[:upper:]' '[:lower:]')"
  FULL_VOL="${COMPOSE_PROJECT_NAME:-$PROJECT}_${MEDIA_VOL}"
  if docker volume inspect "$FULL_VOL" >/dev/null 2>&1; then
    WEB_IMAGE="$(docker compose images -q web 2>/dev/null | head -n1 || true)"
    if [[ -n "$WEB_IMAGE" ]]; then
      docker run --rm \
        --entrypoint sh \
        -v "$FULL_VOL":/data:ro \
        -v "$(realpath "$BACKUP_DIR")":/backup \
        "$WEB_IMAGE" \
        -c "tar czf /backup/$(basename "$MEDIA_FILE") -C /data ."
    else
      echo "WARNING: media backup skipped because the local web image is unavailable." >&2
    fi
  fi
fi

find "$BACKUP_DIR" -type f -mtime +"$RETENTION_DAYS" -delete || true

echo "Backup complete: $DB_FILE"
[[ -f "$MEDIA_FILE" ]] && echo "Media backup: $MEDIA_FILE"
