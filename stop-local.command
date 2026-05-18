#!/bin/bash
set -e
cd "$(dirname "$0")"
APP_PORT="${APP_PORT:-7860}"
echo "[HK-maintenance] Stopping local server on port ${APP_PORT}..."
PIDS="$(lsof -tiTCP:"${APP_PORT}" -sTCP:LISTEN || true)"
if [ -z "${PIDS}" ]; then
  echo "No server is listening on this port."
  read -r -p "Press Enter to close..."
  exit 0
fi
for PID in ${PIDS}; do
  echo "Stopping PID ${PID}"
  kill "${PID}" || true
done
read -r -p "Press Enter to close..."
