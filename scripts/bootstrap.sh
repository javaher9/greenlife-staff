#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo "Docker is required"; exit 1; }
docker compose version >/dev/null
command -v git >/dev/null || { echo "Git is required"; exit 1; }
command -v curl >/dev/null || { echo "curl is required"; exit 1; }
[[ -f .env ]] || { cp .env.example .env; echo "Created .env from template. Edit secrets before deploy."; exit 2; }
chmod +x scripts/*.sh
./scripts/deploy.sh
