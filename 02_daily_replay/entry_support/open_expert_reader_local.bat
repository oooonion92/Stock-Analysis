@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
set "APP=%SCRIPT_DIR%..\tools\forum_crawler\expert_reader_server.py"
set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "URL=http://127.0.0.1:8765/"

if not exist "%PY%" set "PY=python"

if not exist "%APP%" (
  echo Cannot find reader app:
  echo %APP%
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ok=$false; try { Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -TimeoutSec 2 | Out-Null; $ok=$true } catch {}; if ($ok) { Start-Process '%URL%'; exit 77 }"

if "%ERRORLEVEL%"=="77" exit /b 0

echo Starting expert reader center from local project...
echo %URL%
echo.
"%PY%" "%APP%"
pause
