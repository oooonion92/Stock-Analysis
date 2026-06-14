@echo off
chcp 65001 >nul
setlocal

call "%~dp0one_click_collect_today.bat" %*
