@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
title Coin Futures Agent - Local Update
if exist ".venv\Scripts\python.exe" goto use_venv
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo [ERROR] Cai Python 3.13.5 va Git for Windows cho user hien tai, sau do bam lai.
pause
exit /b 1
:use_venv
".venv\Scripts\python.exe" "local_update.py" %1
goto finish
:use_py
py -3 "local_update.py" %1
goto finish
:use_python
python "local_update.py" %1
:finish
set "agent_exit=%errorlevel%"
echo.
if not "%agent_exit%"=="0" echo [ERROR] Khong hoan tat. Khong chia se .env hoac noi dung backups.
pause
exit /b %agent_exit%
