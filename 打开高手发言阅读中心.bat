@echo off
chcp 65001 >nul
call "%~dp002_daily_replay\entry_support\open_expert_reader_local.bat" %*
