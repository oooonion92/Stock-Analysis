@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
set "RUNNER=%SCRIPT_DIR%publish_expert_dashboard.ps1"

if not exist "%RUNNER%" (
  echo Cannot find dashboard publisher:
  echo %RUNNER%
  pause
  exit /b 1
)

echo Starting expert dashboard publisher...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%RUNNER%" %*
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
  echo Finished. You can close this window.
) else (
  echo Publishing stopped with error code: %EXITCODE%
  echo The previous GitHub data has been preserved.
)
echo.
pause
exit /b %EXITCODE%
