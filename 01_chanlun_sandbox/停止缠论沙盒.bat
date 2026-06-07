@echo off
setlocal
cd /d "%~dp0"

set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8765 .*LISTENING"') do (
  set "FOUND=1"
  taskkill /PID %%P /F >nul 2>&1
)

if "%FOUND%"=="1" (
  echo Sandbox stopped.
) else (
  echo No listening process found on port 8765.
)

endlocal
