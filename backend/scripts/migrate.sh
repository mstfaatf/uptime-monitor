#!/usr/bin/env bash
# Run Alembic migrations (run from backend/)
# Requires DATABASE_URL (sync URL derived from postgresql+asyncpg -> postgresql)
set -e
cd "$(dirname "$0")/.."
alembic upgrade head
