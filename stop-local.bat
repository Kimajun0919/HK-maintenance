@echo off
setlocal
if "%APP_PORT%"=="" set APP_PORT=7860
echo [HK-maintenance] Stopping local server on port %APP_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$owners = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if (-not $owners) { Write-Host 'No server is listening on this port.'; exit 0 }; foreach ($owner in $owners) { Write-Host ('Stopping PID ' + $owner); Stop-Process -Id $owner -Force }"
pause
