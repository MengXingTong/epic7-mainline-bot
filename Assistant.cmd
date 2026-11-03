@echo off
setlocal
chcp 65001 >nul
set "GUI_PYTHON=%EPIC7_GUI_PYTHON%"
if not defined GUI_PYTHON if exist "%~dp0gui\pythonw.exe" set "GUI_PYTHON=%~dp0gui\pythonw.exe"
if not defined GUI_PYTHON set "GUI_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
if not exist "%GUI_PYTHON%" (
  echo 缺少界面运行库。请完整解压离线分享包，或设置 EPIC7_GUI_PYTHON。
  pause
  exit /b 1
)
start "" "%GUI_PYTHON%" -B -X utf8 "%~dp0portable_entry.py" %*
