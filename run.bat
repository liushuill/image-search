@echo off
rem ---------------------------------------------------------------
rem image-search CLI launcher (Windows)
rem
rem   run.bat search image.jpg
rem   run.bat engines list
rem
rem This file is intentionally ASCII-only: cmd.exe parses batch files
rem using the active code page, and non-ASCII text inside if-blocks is a
rem common source of breakage. All user-facing messages come from
rem bootstrap.py instead (Python handles UTF-8 reliably).
rem
rem The real bootstrap logic lives in bootstrap.py so that Windows and
rem Linux share one implementation.
rem ---------------------------------------------------------------
setlocal

set "BOOT=%~dp0bootstrap.py"
if not exist "%BOOT%" (
    echo [ERROR] bootstrap.py not found next to this script.
    exit /b 1
)

rem Prefer the "py" launcher (handles multiple installed versions),
rem then fall back to a plain "python" on PATH.
where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 "%BOOT%" cli %*
    exit /b %errorlevel%
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python "%BOOT%" cli %*
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
