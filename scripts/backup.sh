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

# Use a temporary PostgreSQL client container; no host package required.
docker run --rm \
  -e PGPASSWORD="$POSTGRES_PASSWORD" \
  postgres:17-alpine \
  pg_dump -Fc -h "$POSTGRES_HOST" -p "${POSTGRES_PORT:-5432}" -U "$POSTGRES_USER" "$POSTGRES_DB" > "$DB_FILE"

# Use the resolved named volume directly. This also preserves media when the
# new Compose project intentionally reuses the version 17 volume name.
MEDIA_VOL="${MEDIA_VOLUME_NAME:-greenlife_staff_media_data}"
if docker volume inspect "$MEDIA_VOL" >/dev/null 2>&1; then
  docker run --rm -v "$MEDIA_VOL":/data:ro -v "$(realpath "$BACKUP_DIR")":/backup alpine:3.20 \
    sh -c "tar czf /backup/$(basename "$MEDIA_FILE") -C /data ."
fi

find "$BACKUP_DIR" -type f -mtime +"$RETENTION_DAYS" -delete || true

echo "Backup complete: $DB_FILE"
[[ -f "$MEDIA_FILE" ]] && echo "Media backup: $MEDIA_FILE"
