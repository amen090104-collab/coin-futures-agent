@echo off
cd /d %~dp0
title Coin Research and Paper Platform V4

if not exist .env (
  copy .env.example .env >nul
  echo [V4] Created .env from .env.example
)

if not exist .venv\Scripts\python.exe (
  echo [V4] Creating local Python environment...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create Python virtual environment.
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate.bat
echo [V4] Checking dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency installation failed.
  pause
  exit /b 1
)

echo [V4] Starting at http://127.0.0.1:8000
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000'"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo Agent stopped.
pause
