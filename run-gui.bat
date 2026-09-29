@echo off
rem ─────────────────────────────────────────────────────────────
rem image-search 图形界面启动器（Windows）
rem
rem   run-gui.bat
rem
rem 首次运行会自动创建 .venv 并安装 GUI 依赖（PySide6 / Qt6）。
rem ─────────────────────────────────────────────────────────────
chcp 65001 >nul
setlocal

set "REPO_DIR=%~dp0"
set "VENV=%REPO_DIR%.venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo 首次运行：正在创建虚拟环境 .venv ...
    python -m venv "%VENV%"
    "%PY%" -m pip install --quiet --upgrade pip
    echo 正在安装依赖（首次约 2-3 分钟，PySide6 较大）...
    "%PY%" -m pip install --quiet -r "%REPO_DIR%requirements-gui.txt"
    "%PY%" -m pip install --quiet --no-deps -e "%REPO_DIR%"
)

"%PY%" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo 正在安装 GUI 依赖 PySide6 ...
    "%PY%" -m pip install --quiet PySide6
)

set "PYTHONPATH=%REPO_DIR%"
"%PY%" -m imgsearch_gui %*
