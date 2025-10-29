#!/usr/bin/env bash
set -e
cd /Users/badr/Documents/tv-alert-bridge
. .venv/bin/activate
export $(grep -v '^#' .env | xargs)
exec uvicorn app:app --host 0.0.0.0 --port 8000 --reload
