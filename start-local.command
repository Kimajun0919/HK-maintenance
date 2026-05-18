#!/bin/bash
set -e
cd "$(dirname "$0")"
APP_PORT="${APP_PORT:-7860}"
APP_URL="http://127.0.0.1:${APP_PORT}"
echo "[HK-maintenance] Local server launcher"
echo "URL: ${APP_URL}"
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 was not found."
  read -r -p "Press Enter to close..."
  exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi
".venv/bin/python" -m pip install -r backend/requirements.txt
if lsof -nP -iTCP:"${APP_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  open "${APP_URL}"
  read -r -p "Press Enter to close..."
  exit 0
fi
(sleep 2 && open "${APP_URL}") &
".venv/bin/python" backend/app.py
read -r -p "Press Enter to close..."
