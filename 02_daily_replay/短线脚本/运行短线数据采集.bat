@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title A股最近交易日短线数据采集

set "SCRIPT_DIR=%~dp0"
set "PY_SCRIPT=%SCRIPT_DIR%collect_short_term_data.py"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "OUTPUT_DIR=D:\OneDrive\Stock\短线数据采集"
set "BASE_PY="

echo ============================================================
echo A股短线数据采集（最近已收盘交易日）
echo 日期：自动识别；交易日 15:30 前回退上一交易日
echo 输出：%OUTPUT_DIR%
echo ============================================================
echo.

if not exist "%PY_SCRIPT%" (
    echo [错误] 未找到脚本：%PY_SCRIPT%
    goto :failed
)

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>nul
    if not errorlevel 1 goto :venv_ready
    echo [错误] 已有 .venv 不是可用的 Python 3 环境。
    goto :failed
)

where py >nul 2>nul
if not errorlevel 1 set "BASE_PY=py -3"
if not defined BASE_PY (
    where python >nul 2>nul
    if not errorlevel 1 set "BASE_PY=python"
)
if not defined BASE_PY if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "BASE_PY="%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe""
if not defined BASE_PY (
    echo [错误] 未找到 Python 3。请安装 Python 3 后重试。
    goto :failed
)

echo [1/4] 检查 Python 3...
%BASE_PY% -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>nul
if errorlevel 1 (
    echo [错误] 检测到的解释器不是 Python 3。
    goto :failed
)

echo [2/4] 创建项目虚拟环境 .venv...
%BASE_PY% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [错误] 创建 .venv 失败。
    goto :failed
)

:venv_ready
echo [3/4] 检查依赖 akshare、pandas、openpyxl...
"%VENV_PY%" -c "import akshare, pandas, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo 正在把缺失依赖安装到项目 .venv，请稍候...
    "%VENV_PY%" -m pip install akshare pandas openpyxl
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络连接。
        goto :failed
    )
)

echo [4/4] 识别、采集并校验最近已收盘交易日...
echo.
"%VENV_PY%" "%PY_SCRIPT%" --output-dir "%OUTPUT_DIR%" %*
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo 运行成功。最终输出位置：
echo %OUTPUT_DIR%
echo ============================================================
echo.
pause
exit /b 0

:failed
echo.
echo ============================================================
echo 运行失败。请保留本窗口并查看上方明确错误。
echo ============================================================
echo.
pause
exit /b 1
