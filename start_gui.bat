@echo off
rem ---------------------------------------------------------------
rem Legacy entry point. This used to launch the tkinter GUI (gui.py).
rem The GUI is now Qt6, so delegate to run-gui.bat to avoid starting
rem the old interface by accident.
rem (The old tkinter implementation still lives in gui.py; run it
rem  directly with "python gui.py" if you ever need it.)
rem
rem ASCII-only by design -- see the note in run.bat.
rem ---------------------------------------------------------------
call "%~dp0run-gui.bat" %*
