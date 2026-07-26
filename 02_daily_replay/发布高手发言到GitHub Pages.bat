@echo off
chcp 65001 >nul
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\forum_crawler\publish_expert_dashboard.ps1"
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
  echo GitHub Pages data published.
) else (
  echo Publishing failed. The existing Pages data was not replaced.
)
pause
exit /b %EXITCODE%
