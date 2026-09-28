@echo off
chcp 65001 >nul
title ImageTraceGUI

cd /d "%~dp0"
call .venv\Scripts\activate.bat
python gui.py
deactivate
pause
