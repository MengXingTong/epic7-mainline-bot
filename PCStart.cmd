@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if exist "%~dp0python\python.exe" (
  "%~dp0python\python.exe" -B -X utf8 "%~dp0pc_launcher.py" start
) else (
  py -3.12 -B -X utf8 "%~dp0pc_launcher.py" start
)
echo.
pause
