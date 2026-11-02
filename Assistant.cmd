@echo off
setlocal
set "GUI_PYTHON=%EPIC7_GUI_PYTHON%"
if not defined GUI_PYTHON if exist "%~dp0gui\pythonw.exe" set "GUI_PYTHON=%~dp0gui\pythonw.exe"
if not defined GUI_PYTHON set "GUI_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
if not exist "%GUI_PYTHON%" (
  echo GUI runtime missing. Fully extract the offline share package or set EPIC7_GUI_PYTHON.
  pause
  exit /b 1
)
start "" "%GUI_PYTHON%" -B -X utf8 "%~dp0portable_entry.py" %*
