@echo off
chcp 65001 >nul
title 打包图片溯源工具为 EXE

rem ─────────────────────────────────────────────────────────────
rem ⚠️ 仅适用于 Windows，且自 v0.2 包结构重构后【未经实测】。
rem    - CLI 入口已改为 run_cli.py（原 main.py 已移入 imgsearch/cli.py）
rem    - GUI 目前仍是 tkinter 版；P5 迁移到 PySide6 后本脚本需重做
rem    日常使用请优先用 run.bat，不必打包。
rem ─────────────────────────────────────────────────────────────

echo ============================================
echo  正在打包图片溯源工具为 EXE
echo  使用 PyInstaller 打包
echo ============================================
echo.

REM 检查 PyInstaller 是否安装
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [安装 PyInstaller...]
    pip install pyinstaller
)

echo.
echo ============================================
echo  请选择打包模式:
echo    1 - CLI 模式 (命令行, run_cli.py)
echo    2 - GUI 模式 (图形界面, run_gui.py)
echo    3 - 全部打包
echo ============================================
echo.

set /p MODE="请输入 [1/2/3] (默认: 1): "
if "%MODE%"=="" set MODE=1

echo.
echo [清理旧构建文件...]
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "*.spec" del /f /q "*.spec"

echo.
echo [开始打包...]

REM 通用打包参数
set COMMON_ARGS=--onefile --paths . --collect-submodules imgsearch --hidden-import "PIL._tkinter_finder" --hidden-import "bs4" --hidden-import "lxml" --hidden-import "cloudscraper" --clean --noconfirm

if "%MODE%"=="2" goto GUI_MODE
if "%MODE%"=="3" goto ALL_MODE

:CLI_MODE
echo.
echo [打包 CLI 版本...]
pyinstaller %COMMON_ARGS% --console --name "ImageTrace" run_cli.py
if %errorlevel% equ 0 (
    echo.
    echo  ✅ CLI 打包成功!
    echo  📁 EXE 位置: dist\ImageTrace.exe
) else (
    echo  ❌ CLI 打包失败!
)
if not "%MODE%"=="3" goto END

:GUI_MODE
echo.
echo [打包 GUI 版本...]
pyinstaller %COMMON_ARGS% --windowed --name "ImageTrace-GUI" --icon NONE run_gui.py
if %errorlevel% equ 0 (
    echo.
    echo  ✅ GUI 打包成功!
    echo  📁 EXE 位置: dist\ImageTrace-GUI.exe
) else (
    echo  ❌ GUI 打包失败!
)
if "%MODE%"=="2" goto END

:ALL_MODE
echo.
echo [打包 CLI 版本...]
pyinstaller %COMMON_ARGS% --console --name "ImageTrace" run_cli.py
if %errorlevel% equ 0 (
    echo.
    echo  ✅ CLI 打包成功!
    echo  📁 EXE 位置: dist\ImageTrace.exe
) else (
    echo  ❌ CLI 打包失败!
)

echo.
echo [打包 GUI 版本...]
pyinstaller %COMMON_ARGS% --windowed --name "ImageTrace-GUI" run_gui.py
if %errorlevel% equ 0 (
    echo.
    echo  ✅ GUI 打包成功!
    echo  📁 EXE 位置: dist\ImageTrace-GUI.exe
) else (
    echo  ❌ GUI 打包失败!
)

:END
echo.
echo ============================================
if "%MODE%"=="1" (
    echo  ✅ CLI 打包完成!
    echo  📁 dist\ImageTrace.exe
) else if "%MODE%"=="2" (
    echo  ✅ GUI 打包完成!
    echo  📁 dist\ImageTrace-GUI.exe
) else (
    echo  ✅ 全部打包完成!
    echo  📁 dist\ImageTrace.exe  (CLI)
    echo  📁 dist\ImageTrace-GUI.exe  (GUI)
)
echo ============================================
echo.
echo  📝 注意:
echo   1. config.json 会在首次运行时自动创建；凭据请用 .env（见 .env.example）
echo   2. 使用前请先配置 API Key:
echo      ImageTrace.exe config set saucenao_key YOUR_KEY   (写入 .env)
echo      ImageTrace-GUI.exe (图形界面版，首次启动后可在界面上配置)
echo.
echo  🚀 使用示例 (CLI):
echo      ImageTrace.exe search "图片路径"
echo      ImageTrace.exe batch "目录路径"
echo.
