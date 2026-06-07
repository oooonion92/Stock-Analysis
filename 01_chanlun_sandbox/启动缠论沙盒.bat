@echo off
setlocal
cd /d "%~dp0"
echo Starting Chanlun sandbox at http://127.0.0.1:8765/
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_chanlun_sandbox_keepalive.ps1"
endlocal
