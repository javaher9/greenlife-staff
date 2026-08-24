#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  if [[ -f .last_good_commit ]]; then TARGET="$(cat .last_good_commit)"; else echo "Usage: $0 <git-commit>"; exit 1; fi
fi
./scripts/backup.sh
CURRENT="$(git rev-parse HEAD)"
echo "Rolling back code from $CURRENT to $TARGET"
git fetch --all --prune
git reset --hard "$TARGET"
docker compose build
docker compose up -d --remove-orphans
./scripts/healthcheck.sh

echo "Code rollback complete. NOTE: database migrations are not automatically reversed."
