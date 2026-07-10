@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%tools\forum_crawler\one_click_collect_today.bat" %*
