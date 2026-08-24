@echo off
REM LineLens launcher.
REM Double-click to start; the interface opens in your browser automatically.
REM Close THIS window (or press Ctrl+C) to stop the app. It never runs in the
REM background because the server lives in this console and dies with it.

cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo.
  echo  LineLens needs "uv", but it was not found on PATH.
  echo  Install it from https://docs.astral.sh/uv/ , then double-click again.
  echo.
  pause
  exit /b 1
)

REM First run only: web\dist is built from source and is not committed.
if not exist "web\dist\index.html" (
  echo.
  echo  Building the LineLens interface, first run only...
  where npm >nul 2>nul
  if errorlevel 1 (
    echo.
    echo  Node.js needed for first build - install from https://nodejs.org
    echo  then double-click again.
    echo.
    pause
    exit /b 1
  )
  cd web
  call npm ci && call npm run build
  if errorlevel 1 (
    cd /d "%~dp0"
    echo.
    echo  The frontend build failed - see the errors above.
    echo.
    pause
    exit /b 1
  )
  cd /d "%~dp0"
)

echo.
echo  Starting LineLens...  your browser will open at http://127.0.0.1:8741
echo  Close this window (or press Ctrl+C) to stop it.
echo.

REM No "start": the server runs in THIS console, so closing it kills the app.
uv run --extra web --extra forecast python api.py

if errorlevel 1 pause
