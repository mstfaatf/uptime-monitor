#!/usr/bin/env bash
# Run the API with uvicorn (run from backend/)
set -e
cd "$(dirname "$0")/.."
uvicorn main:app --reload --host 0.0.0.0 --port 8000
