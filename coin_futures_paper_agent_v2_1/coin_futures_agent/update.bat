@echo off
cd /d %~dp0
title Update Coin Platform

if not exist backups mkdir backups
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set TS=%%i

echo [1/3] Backing up local runtime data...
if exist agent.db copy /Y agent.db backups\agent-preupdate-%TS%.db >nul
if exist .env copy /Y .env backups\env-preupdate-%TS%.txt >nul

echo [2/3] Pulling latest main branch...
git pull origin main
if errorlevel 1 (
  echo.
  echo [ERROR] Git update failed. Your backup is still in the backups folder.
  pause
  exit /b 1
)

echo [3/3] Update complete.
echo Backups are stored in: %CD%\backups
echo.
echo You can now run run.bat.
pause
