@echo off
chcp 65001 >nul
call "%~dp002_daily_replay\entry_support\collect_forum_posts_local.bat" %*
