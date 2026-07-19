@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3 is required. Install it from https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the local Python environment...
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)

echo Installing GIFmakerAthome and its bundled media tools...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo Installation complete. Double-click start.bat to open GIFmakerAthome.
pause
exit /b 0

:failed
echo.
echo Installation did not complete. Check the messages above and try again.
pause
exit /b 1
