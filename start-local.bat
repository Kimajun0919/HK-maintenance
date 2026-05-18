@echo off
setlocal
cd /d "%~dp0"
if "%APP_PORT%"=="" set APP_PORT=7860
set APP_URL=http://127.0.0.1:%APP_PORT%
echo [HK-maintenance] Local server launcher
echo URL: %APP_URL%
where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
  start "" "%APP_URL%"
  pause
  exit /b 0
)
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"
".venv\Scripts\python.exe" backend\app.py
pause
