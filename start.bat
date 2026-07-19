@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo GIFmakerAthome needs its one-time local setup.
  call install.bat
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo GIFmakerAthome stopped because of an error.
  pause
)
