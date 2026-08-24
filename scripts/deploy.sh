#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

LOCKFILE="/tmp/greenlife_staff_deploy.lock"
exec 9>"$LOCKFILE"
flock -n 9 || { echo "Another deployment is already running."; exit 1; }

BRANCH="${DEPLOY_BRANCH:-main}"
PREV_COMMIT="$(git rev-parse HEAD 2>/dev/null || true)"

echo "== GreenLife Staff deploy =="
echo "Branch: $BRANCH"
echo "Current commit: ${PREV_COMMIT:-unknown}"

./scripts/backup.sh

git fetch --all --prune
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
NEW_COMMIT="$(git rev-parse HEAD)"
echo "Deploying commit: $NEW_COMMIT"

# Build first; existing containers keep running until replacement.
docker compose build --pull

# Explicit migrations before switch-over. entrypoint also runs migrate safely.
docker compose run --rm --entrypoint python web manage.py migrate --noinput

docker compose up -d --remove-orphans

if ./scripts/healthcheck.sh; then
  echo "$NEW_COMMIT" > .last_good_commit
  echo "Deploy successful: $NEW_COMMIT"
  docker compose ps
  exit 0
fi

echo "Deploy failed. Attempting code rollback..." >&2
if [[ -n "$PREV_COMMIT" ]]; then
  git reset --hard "$PREV_COMMIT"
  docker compose build
  docker compose up -d --remove-orphans
  ./scripts/healthcheck.sh || true
fi

echo "Rollback attempted. Check logs with: docker compose logs --tail=200 web" >&2
exit 1
