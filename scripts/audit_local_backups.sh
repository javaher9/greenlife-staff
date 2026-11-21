#!/usr/bin/env bash
# Read-only inspection of existing GreenLife Staff local backups.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -f .env ]]; then
  # Read only backup destination, never print secrets.
  BACKUP_DIR="$(sed -n 's/^BACKUP_DIR=//p' .env | tail -1 | tr -d '\r"')"
fi
BACKUP_DIR="${BACKUP_DIR:-./backups}"
printf 'Backup directory: %s\n' "$BACKUP_DIR"
if [[ ! -d "$BACKUP_DIR" ]]; then echo 'ERROR: backup directory missing' >&2; exit 1; fi
for pattern in 'db_*.dump' 'media_*.tar.gz'; do
  echo "== $pattern =="
  find "$BACKUP_DIR" -maxdepth 1 -type f -name "$pattern" -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %f\n' | sort -r | head -10
done
newest_db="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'db_*.dump' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
newest_media="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'media_*.tar.gz' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
[[ -n "$newest_db" && -s "$newest_db" ]] || { echo 'ERROR: missing nonempty DB backup' >&2; exit 2; }
[[ -n "$newest_media" && -s "$newest_media" ]] || { echo 'ERROR: missing nonempty media backup' >&2; exit 2; }
if command -v pg_restore >/dev/null 2>&1; then
  pg_restore --list "$newest_db" >/dev/null || { echo 'ERROR: pg_restore cannot read DB dump' >&2; exit 2; }
  echo 'DB archive index: OK (NOT a complete restore test)'
else echo 'WARNING: pg_restore unavailable; DB format unverified'; fi
tar -tzf "$newest_media" >/dev/null || { echo 'ERROR: media tar unreadable' >&2; exit 2; }
echo 'Media tar stream: OK (NOT a full restore test)'
echo 'Audit passed for presence and readable backup formats; restore test still required.'
