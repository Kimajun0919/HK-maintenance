#!/bin/bash
set -e

cd "$(dirname "$0")"

APP_PORT="${APP_PORT:-7860}"
APP_URL="http://127.0.0.1:${APP_PORT}"

echo "[HK-maintenance] Local server launcher"
echo "Project: $(pwd)"
echo "URL: ${APP_URL}"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 was not found. Install Python 3.11 or newer, then run this file again."
  read -r -p "Press Enter to close..."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Installing/updating Python packages..."
".venv/bin/python" -m pip install -r backend/requirements.txt

if lsof -nP -iTCP:"${APP_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "A server is already running on port ${APP_PORT}."
  echo "Opening ${APP_URL}"
  open "${APP_URL}"
  read -r -p "Press Enter to close..."
  exit 0
fi

echo "Starting local server..."
echo "Close this window or press Ctrl+C to stop the server."
echo
(sleep 2 && open "${APP_URL}") &
".venv/bin/python" backend/app.py

read -r -p "Press Enter to close..."
