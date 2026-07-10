@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "APP=%SCRIPT_DIR%reader_board_app\reader_board_server.py"

if not exist "%PY%" set "PY=python"

echo Starting expert reader board...
"%PY%" "%APP%"
pause
