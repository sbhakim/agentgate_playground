#!/usr/bin/env bash
# Build the frontend and serve the whole app from one process on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python}"
if [ -f .env ]; then set -a; . ./.env; set +a; fi

echo "==> Building frontend"
(cd frontend && { [ -d node_modules ] || npm ci; } && npm run build)

echo "==> Running backend tests"
(cd backend && "$PY" -m pytest -q)

echo "==> Serving on http://127.0.0.1:8000  (Ctrl+C to stop; restarting clears all demo state)"
cd backend && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
