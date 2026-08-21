@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher was not found. Install Python 3.8 or newer first.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

if not exist ".env" copy /y ".env.example" ".env" >nul

echo.
echo Setup complete. Add your API key to .env, then run Start-WalletMonitor.cmd.
pause
exit /b 0

:failed
echo.
echo Setup failed. Review the message above and try again.
pause
exit /b 1