@echo off
setlocal
set "CONTROL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%CONTROL_PYTHON%" exit /b 1
"%CONTROL_PYTHON%" "%~dp0assistant_control.py" stop
