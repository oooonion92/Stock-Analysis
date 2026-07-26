@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
set "CRAWLER_DIR=%SCRIPT_DIR%..\tools\forum_crawler"
set "RUNNER=%CRAWLER_DIR%\run_collect_forum_posts.ps1"

if not exist "%RUNNER%" (
  echo Cannot find collector runner:
  echo %RUNNER%
  pause
  exit /b 1
)

echo Starting forum post collector from local project...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%RUNNER%" %*
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
