@echo off
rem ─────────────────────────────────────────────────────────────
rem image-search CLI 启动器（Windows）
rem
rem   run.bat search 图片.jpg
rem   run.bat batch 待查目录
rem   run.bat engines list
rem
rem 首次运行会自动创建 .venv 并安装依赖。
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
    echo 正在安装依赖（首次约 1-2 分钟）...
    "%PY%" -m pip install --quiet -r "%REPO_DIR%requirements.txt"
    rem 可选：注册 imgsearch 命令（失败不影响使用，下面用 PYTHONPATH 兜底）
    "%PY%" -m pip install --quiet --no-deps -e "%REPO_DIR%"
    echo 依赖安装完成。
)

if not exist "%REPO_DIR%.env" (
    echo 提示：尚未配置凭据。可执行  copy .env.example .env  后填入 SAUCENAO_KEY
)

set "PYTHONPATH=%REPO_DIR%"
"%PY%" -m imgsearch %*
