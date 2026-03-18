#!/usr/bin/env bash
# Simple local startup script for OpenClaw Mission Control.
# Starts the backend (FastAPI) and frontend (Next.js) concurrently.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check for backend .env
if [ ! -f "$SCRIPT_DIR/backend/.env" ]; then
  echo "ERROR: backend/.env not found."
  echo "Copy backend/.env.example to backend/.env and set LOCAL_AUTH_TOKEN."
  exit 1
fi

echo "Starting OpenClaw Mission Control..."
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo ""

# Start backend
(
  cd "$SCRIPT_DIR/backend"
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
) &
BACKEND_PID=$!

# Start frontend
(
  cd "$SCRIPT_DIR/frontend"
  npm run dev
) &
FRONTEND_PID=$!

# Cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

wait
