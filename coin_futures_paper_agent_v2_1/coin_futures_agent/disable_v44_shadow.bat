@echo off
cd /d "%~dp0"
title Disable V4.4 Research Shadow
if exist .venv\Scripts\python.exe (
  ".venv\Scripts\python.exe" configure_v44.py disable
) else (
  python configure_v44.py disable
)
if errorlevel 1 (
  echo Failed to update .env.
) else (
  echo Research Shadow disabled after restart. Existing paper accounts unchanged.
)
pause
