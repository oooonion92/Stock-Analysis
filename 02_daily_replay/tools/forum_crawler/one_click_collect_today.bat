@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"

echo Starting forum post collector...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_collect_forum_posts.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
  echo Finished. You can close this window.
) else (
  echo Finished with error code: %EXITCODE%
  echo Please check the status above and the log file shown in the window.
)
echo.
pause
exit /b %EXITCODE%
