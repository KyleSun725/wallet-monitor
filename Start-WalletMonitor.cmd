@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "%~dp0wallet_monitor.py"
) else (
  start "" pythonw.exe "%~dp0wallet_monitor.py"
)
endlocal