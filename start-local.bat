@echo off
setlocal

cd /d "%~dp0"

if "%APP_PORT%"=="" set APP_PORT=7860
set APP_URL=http://127.0.0.1:%APP_PORT%

echo [HK-maintenance] Local server launcher
echo Project: %CD%
echo URL: %APP_URL%
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found. Install Python 3.11 or newer, then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: Failed to create .venv.
    pause
    exit /b 1
  )
)

echo Installing/updating Python packages...
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 (
  echo ERROR: Failed to install requirements.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
  echo A server is already running on port %APP_PORT%.
  echo Opening %APP_URL%
  start "" "%APP_URL%"
  pause
  exit /b 0
)

echo Starting local server...
echo Close this window or press Ctrl+C to stop the server.
echo.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"
".venv\Scripts\python.exe" backend\app.py

pause
