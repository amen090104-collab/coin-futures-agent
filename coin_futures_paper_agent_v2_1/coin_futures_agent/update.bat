@echo off
cd /d "%~dp0"
title Update Coin Futures Agent (safe backup)
echo [1/3] Backing up SQLite database (including WAL) and .env...
if exist .venv\Scripts\python.exe (
  ".venv\Scripts\python.exe" safe_preupdate_backup.py
) else (
  python safe_preupdate_backup.py
)
if errorlevel 1 (
  echo [ERROR] Database backup failed. Update stopped.
  pause
  exit /b 1
)
echo [2/3] Pulling the current approved main branch...
git pull --ff-only origin main
if errorlevel 1 (
  echo [ERROR] Git update failed or local changes conflict.
  echo Original agent.db and settings are untouched; backups remain in backups.
  pause
  exit /b 1
)
echo [3/3] Update complete. Start run.bat.
echo V4.4 research mode is isolated and can be toggled via enable_v44_shadow.bat.
echo All existing paper case balances and histories remain untouched.
pause
