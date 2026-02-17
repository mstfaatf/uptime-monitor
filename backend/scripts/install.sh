#!/usr/bin/env bash
# Install dependencies (run from backend/)
set -e
cd "$(dirname "$0")/.."
pip install -r requirements.txt
