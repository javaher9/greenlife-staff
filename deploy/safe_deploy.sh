#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DEPLOY_PATH="${DEPLOY_PATH:-$ROOT}"

# The production PostgreSQL server is external. The canonical deploy runner
# backs it up through scripts/backup.sh before building or migrating.
exec "$ROOT/scripts/deploy_runner.sh"
