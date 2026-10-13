@echo off
cd /d "%~dp0"
title Enable V4.4 Research Shadow
if exist .venv\Scripts\python.exe (
  ".venv\Scripts\python.exe" configure_v44.py enable
) else (
  python configure_v44.py enable
)
if errorlevel 1 (
  echo Failed to update .env. No trading settings were changed.
) else (
  echo.
  echo Research Shadow will run after restart.
  echo Existing paper cases are unchanged; this does not activate live trading.
)
pause
