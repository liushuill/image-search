@echo off
rem ---------------------------------------------------------------
rem image-search GUI launcher (Windows)
rem
rem   run-gui.bat
rem
rem Creates .venv and installs PySide6 (Qt6) on first run.
rem ASCII-only by design -- see the note in run.bat.
rem ---------------------------------------------------------------
setlocal

set "BOOT=%~dp0bootstrap.py"
if not exist "%BOOT%" (
    echo [ERROR] bootstrap.py not found next to this script.
    exit /b 1
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 "%BOOT%" gui %*
    exit /b %errorlevel%
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python "%BOOT%" gui %*
    exit /b %errorlevel%
)

echo.
echo [ERROR] Python 3 was not found on this system.
echo.
echo   Install Python 3.10 or newer, and make sure "Add python.exe to PATH"
echo   is checked during setup:
echo.
echo       https://www.python.org/downloads/
echo.
echo   If you just installed it, close and reopen this window so PATH refreshes.
echo.
pause
exit /b 1
