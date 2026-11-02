@echo off
setlocal
set "GUI_PYTHON=%EPIC7_GUI_PYTHON%"
if not defined GUI_PYTHON set "GUI_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
if not exist "%GUI_PYTHON%" (
  echo Python with Tkinter is required. Set EPIC7_GUI_PYTHON to pythonw.exe.
  exit /b 1
)
start "" "%GUI_PYTHON%" "%~dp0assistant_app.py" %*
