#!/usr/bin/env bash
# Encrypt and send latest matching database + media backups to TWO independent restic repositories.
# No offsite credentials, keys, or patient data are stored in Git.
set -Eeuo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."
CONFIG="${OFFSITE_CONFIG:-/etc/greenlife/offsite-backup.env}"
[[ -f "$CONFIG" ]] || { echo "ERROR: offsite config missing: $CONFIG" >&2; exit 2; }
# shellcheck disable=SC1090
source "$CONFIG"
: "${BACKUP_DIR:=/home/ubuntu/greenlife-staff-runtime/backups}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE required}"
: "${RESTIC_REPOSITORY_HOME:?RESTIC_REPOSITORY_HOME required}"
: "${RESTIC_REPOSITORY_CLOUD:?RESTIC_REPOSITORY_CLOUD required}"
[[ -r "$RESTIC_PASSWORD_FILE" ]] || { echo 'ERROR: missing encryption password file' >&2; exit 2; }
command -v restic >/dev/null || { echo 'ERROR: install restic first' >&2; exit 2; }
[[ -d "$BACKUP_DIR" ]] || { echo 'ERROR: local backup directory missing' >&2; exit 2; }
# Disallow simultaneous jobs, and reject missing backup pair.
exec 9>/tmp/greenlife-offsite-backup.lock
flock -n 9 || { echo 'ERROR: offsite backup already running' >&2; exit 2; }
db="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'db_*.dump' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
media="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'media_*.tar.gz' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
[[ -n "$db" && -s "$db" && -n "$media" && -s "$media" ]] || { echo 'ERROR: no complete nonempty DB/media pair; refusing upload' >&2; exit 2; }
# Validate latest media is reasonably aligned with the latest DB (24h).
if (( $(date +%s) - $(stat -c %Y "$db") > 86400 || $(date +%s) - $(stat -c %Y "$media") > 86400 )); then
 echo 'ERROR: backup files are older than 24h; run scheduled local backup before offsite upload' >&2; exit 2
fi
if command -v pg_restore >/dev/null; then pg_restore --list "$db" >/dev/null; fi
tar -tzf "$media" >/dev/null
# Restic encrypts and authenticates data before uploading. Both destinations are mandatory.
export RESTIC_PASSWORD_FILE
failed=0
for dest in HOME CLOUD; do
  case "$dest" in
    HOME) repo="$RESTIC_REPOSITORY_HOME";;
    CLOUD) repo="$RESTIC_REPOSITORY_CLOUD";;
  esac
  export RESTIC_REPOSITORY="$repo"
  if ! restic snapshots --json >/dev/null 2>&1; then
    echo "ERROR: destination $dest repository unavailable or uninitialized; initialize it separately" >&2
    failed=1
    continue
  fi
  if restic backup --tag greenlife-staff --tag "destination-$dest" -- "$db" "$media" && restic snapshots --latest 1 >/dev/null; then
    echo "OK: encrypted backup verified present in $dest snapshot listing"
  else
    echo "ERROR: upload or listing failed for $dest" >&2
    failed=1
  fi
done
exit "$failed"
