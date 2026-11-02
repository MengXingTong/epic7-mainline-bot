@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "RUNTIME="
if exist "%~dp0python\python.exe" set "RUNTIME=%~dp0python\python.exe"
if not defined RUNTIME if exist "%~dp0.venv\Scripts\python.exe" set "RUNTIME=%~dp0.venv\Scripts\python.exe"
if not defined RUNTIME if exist "%~dp0.local\python-path.txt" set /p "RUNTIME="<"%~dp0.local\python-path.txt"
if defined RUNTIME if not exist "%RUNTIME%" set "RUNTIME="
if defined RUNTIME (
  "%RUNTIME%" -B -X utf8 "%~dp0pc_quickstart.py" %1
) else (
  py -3.12 -B -X utf8 "%~dp0pc_quickstart.py" %1
)
echo.
pause
