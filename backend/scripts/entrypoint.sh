#!/bin/sh
# Run migrations then start the API (for Docker).
set -e
cd /app
alembic upgrade head
exec uvicorn main:app --host 0.0.0.0 --port 8000
