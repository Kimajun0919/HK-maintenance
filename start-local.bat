@echo off
setlocal
cd /d "%~dp0"
if "%APP_PORT%"=="" set APP_PORT=7860
if "%USE_LLM%"=="" set USE_LLM=0
if "%EMBEDDING_BACKEND%"=="" set EMBEDDING_BACKEND=none
set PYTHONUTF8=1
set APP_URL=http://127.0.0.1:%APP_PORT%
echo [HK-maintenance] Local server launcher
echo URL: %APP_URL%
echo USE_LLM=%USE_LLM%
echo EMBEDDING_BACKEND=%EMBEDDING_BACKEND%
where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -Command "$owners = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($owner in $owners) { Write-Host ('Stopping existing local server PID ' + $owner); Stop-Process -Id $owner -Force }"
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"
".venv\Scripts\python.exe" -u backend\app.py
pause
