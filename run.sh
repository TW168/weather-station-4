#!/usr/bin/env bash
# run.sh  –  install deps & start the FastAPI app
set -e
cd "$(dirname "$0")"

echo "📦  Installing dependencies..."
pip install -r requirements.txt --quiet

echo "🚀  Starting PWS Weather Dashboard on http://0.0.0.0:8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
