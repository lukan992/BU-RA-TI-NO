#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

docker compose -f docker-compose.local.yml up -d postgres

for _ in $(seq 1 30); do
  if docker compose -f docker-compose.local.yml exec -T postgres pg_isready -U buratino -d buratino_smoke >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

cp -n .env.smoke.example .env.smoke 2>/dev/null || true
set -a
. ./.env.smoke
set +a

uv run buratino migrate
uv run buratino seed-smoke-db
uv run buratino worker --max-jobs 4
uv run buratino smoke-check
