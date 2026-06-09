@echo off
setlocal

cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

echo Starting local server...
echo URL: http://127.0.0.1:%PORT%/start.html
echo.
echo Press Ctrl+C to stop the server.
echo.

python server.py %PORT%

if errorlevel 1 (
  echo.
  echo Server exited with an error. Check whether the port is already in use.
  pause
)
