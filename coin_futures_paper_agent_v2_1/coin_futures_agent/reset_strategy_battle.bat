@echo off
cd /d %~dp0
title Reset Strategy Battle

echo.
echo ==========================================================
echo  WARNING: THIS WILL CLEAR OLD FUTURES PAPER TRADING DATA
echo  A backup of agent.db and .env will be created first.
echo ==========================================================
echo.
set /p CONFIRM=Type RESET to continue: 
if /I not "%CONFIRM%"=="RESET" (
  echo Cancelled.
  pause
  exit /b 0
)

if not exist .venv\Scripts\python.exe (
  echo [ERROR] .venv not found. Run run.bat once first.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
python -m app.reset_battle
if errorlevel 1 (
  echo.
  echo [ERROR] Reset failed. Do not start the agent yet.
  pause
  exit /b 1
)

echo.
echo Reset completed. You can now run run.bat.
pause
