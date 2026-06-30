@echo off
REM US Corn Dashboard - gather data and rebuild index.html
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found on PATH.
  echo Install Python 3.10+ from https://www.python.org/downloads/ ^(check "Add to PATH"^).
  pause
  exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Using Python %PYVER%

python src\update.py
if errorlevel 1 (
  echo.
  echo Update failed - see messages above.
  pause
  exit /b 1
)

echo.
echo Opening dashboard...
start "" "%~dp0index.html"
endlocal
