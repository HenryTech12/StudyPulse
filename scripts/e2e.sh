#!/usr/bin/env bash
# Starts the real backend on a temp database, runs the React UI tests against it, then stops it.
set -e
cd "$(dirname "$0")/.."
PORT=${E2E_PORT:-8765}
DB="$(mktemp -u).db"
(cd backend && DATABASE_URL="sqlite:///$DB" UPLOAD_DIR="$(mktemp -d)" python -m uvicorn app.main:app --port "$PORT" --log-level warning) &
PID=$!
trap 'kill $PID 2>/dev/null || true; rm -f "$DB"' EXIT
for _ in $(seq 1 40); do curl -s "http://127.0.0.1:$PORT/api/me" >/dev/null && break; sleep 0.5; done
(cd frontend && E2E_API="http://127.0.0.1:$PORT" npx vitest run)
